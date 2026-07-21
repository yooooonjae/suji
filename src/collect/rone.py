"""한국부동산원 R-ONE 수집기: 아파트 매매·전세가격지수(시도별 월별), 민간아파트 평균 분양가격.

실행: python3 src/collect/rone.py
산출: data/rone.json
  {"sale_index":   {"서울": [{"ym":"201607","value":...}, ...], ...},   # 지수 (2026.01=100)
   "jeonse_index": {"서울": [...], ...},                                # 지수 (2026.01=100)
   "presale_price":{"서울": [...], ...},                               # 민간아파트 ㎡당 평균분양가격(천원/㎡)
   "tables_used": [{"id","name"}], "collected_at", "source"}

API: SttsApiTbl.do(표 목록) / SttsApiTblData.do(자료).
분류축(CLS)은 SttsApiTblData 실측으로 파악:
  - 지수표: CLS_FULLNM 이 "서울"·"전국" 처럼 '>' 없는 최상위 = 시도. CLS_ID 로 시계열 필터.
  - 분양가표: CLS_FULLNM 이 "...>서울>전체" 처럼 '전체'로 끝나고 직전 세그먼트가 시도.
원본 응답은 data/raw/rone/ 에 전량 캐시(재실행 시 API 재호출 스킵).
"""

import datetime
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from collect.common import ROOT, SIDO, api_get, load_config  # noqa: E402

RAW_DIR = ROOT / "data" / "raw" / "rone"
BASE = "https://www.reb.or.kr/r-one/openapi"
YEARS = 10

VALID_SIDO = set(SIDO.values())  # {"서울","부산",...,"강원"} — 17개
VALID = VALID_SIDO | {"전국"}

# R-ONE 표: (키, STATBL_ID, 이름, 모드)  모드=index → CLS 최상위 시도 / presale → '...>시도>전체'
TABLES = [
    ("sale_index", "A_2024_00045", "(월) 매매가격지수_아파트", "index"),
    ("jeonse_index", "A_2024_00050", "(월) 전세가격지수_아파트", "index"),
    ("presale_price", "T249233134451237", "지역별 규모별 ㎡당 평균 분양가격", "presale"),
]


def _cutoff_ym() -> str:
    t = datetime.date.today()
    return f"{t.year - YEARS}{t.month:02d}"


def _ym_minus(offset: int) -> str:
    t = datetime.date.today()
    m = t.month - offset
    y = t.year
    while m <= 0:
        m += 12
        y -= 1
    return f"{y}{m:02d}"


def _get(params: dict) -> list:
    """SttsApiTblData.do 호출 → row 리스트 (오류는 즉시 예외)."""
    st, tx = api_get(f"{BASE}/SttsApiTblData.do", params, retries=1)
    if st != 200:
        raise RuntimeError(f"R-ONE HTTP {st}: {tx[:200]}")
    doc = json.loads(tx)
    obj = doc.get("SttsApiTblData")
    if obj is None:  # RESULT-only 응답: INFO-200(빈 결과)만 허용, 그 외는 오류
        code = doc.get("RESULT", {}).get("CODE")
        if code == "INFO-200":
            return []
        raise RuntimeError(f"R-ONE 비정상 응답 {params.get('STATBL_ID')}: {tx[:200]}")
    head = obj[0]["head"]
    result = head[1]["RESULT"]
    if result["CODE"] != "INFO-000":
        raise RuntimeError(f"R-ONE 오류 {params.get('STATBL_ID')}: {result}")
    total = int(head[0]["list_total_count"])
    rows = list(obj[1]["row"])
    page = 2
    while len(rows) < total:  # 방어적 페이지네이션(시도별 계열은 보통 1페이지)
        p = dict(params, pIndex=str(page))
        st, tx = api_get(f"{BASE}/SttsApiTblData.do", p, retries=1)
        rows.extend(json.loads(tx)["SttsApiTblData"][1]["row"])
        page += 1
        time.sleep(0.3)
    return rows


def _fetch_series(key: str, statbl_id: str, cls_id) -> list:
    """CLS_ID 한 개의 전체 월별 시계열(원본 캐시)."""
    cache = RAW_DIR / f"{statbl_id}_{cls_id}.json"
    if cache.exists():
        return json.loads(cache.read_text())
    rows = _get({"KEY": key, "Type": "json", "STATBL_ID": statbl_id,
                 "DTACYCLE_CD": "MM", "CLS_ID": str(cls_id),
                 "pIndex": "1", "pSize": "1000"})
    cache.write_text(json.dumps(rows, ensure_ascii=False))
    time.sleep(0.3)
    return rows


def _discover_month(key: str, statbl_id: str):
    """데이터가 존재하는 최근 월 1개의 전체 분류(CLS) 행 — 시도 매핑용."""
    for off in range(0, 15):
        ym = _ym_minus(off)
        cache = RAW_DIR / f"{statbl_id}_month_{ym}.json"
        if cache.exists():
            rows = json.loads(cache.read_text())
        else:
            rows = _get({"KEY": key, "Type": "json", "STATBL_ID": statbl_id,
                         "DTACYCLE_CD": "MM", "WRTTIME_IDTFR_ID": ym,
                         "pIndex": "1", "pSize": "400"})
            cache.write_text(json.dumps(rows, ensure_ascii=False))
            time.sleep(0.3)
        if rows:
            return ym, rows
    raise RuntimeError(f"R-ONE {statbl_id}: 최근 15개월 내 데이터 없음")


def _region_map(rows: list, mode: str) -> dict:
    """CLS 행 목록 → {시도명: CLS_ID}."""
    out = {}
    for r in rows:
        full = r.get("CLS_FULLNM") or ""
        seg = full.split(">")
        if mode == "index":
            if len(seg) == 1 and r.get("CLS_NM") in VALID:
                out[r["CLS_NM"]] = r["CLS_ID"]
        else:  # presale: '...>시도>전체' 또는 '전국>전체'
            if seg[-1] != "전체" or len(seg) < 2:
                continue
            name = seg[-2]
            if name in VALID:
                out[name] = r["CLS_ID"]
    return out


def collect() -> dict:
    key = load_config()["rone_key"]
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    cutoff = _cutoff_ym()
    out = {}
    tables_used = []
    issues = []
    for out_key, statbl_id, name, mode in TABLES:
        _, month_rows = _discover_month(key, statbl_id)
        rmap = _region_map(month_rows, mode)
        series_by_sido = {}
        for sido, cls_id in sorted(rmap.items()):
            rows = _fetch_series(key, statbl_id, cls_id)
            pts = []
            for r in rows:
                ym = r.get("WRTTIME_IDTFR_ID")
                val = r.get("DTA_VAL")
                if ym is None or val is None or ym < cutoff:
                    continue
                pts.append({"ym": ym, "value": round(float(val), 4)})
            pts.sort(key=lambda x: x["ym"])
            if pts:
                series_by_sido[sido] = pts
        out[out_key] = series_by_sido
        tables_used.append({"id": statbl_id, "name": name})

        # 검증: 시도 커버·행수·값 범위
        covered = set(series_by_sido) & VALID_SIDO
        missing = VALID_SIDO - covered
        lo, hi = (20.0, 200.0) if mode == "index" else (100.0, 100000.0)
        for sido, pts in series_by_sido.items():
            bad = [p for p in pts if not (lo <= p["value"] <= hi)]
            assert not bad, f"{out_key}/{sido}: 범위 밖 {bad[:3]}"
        nat = series_by_sido.get("전국", [])
        assert len(nat) >= 24, f"{out_key}: 전국 행수 부족 {len(nat)}"
        if missing:
            issues.append(f"{out_key}: 시도 누락 {sorted(missing)}")
        print(f"  {out_key:<14} 시도 {len(covered)}/17  전국 {len(nat)}개월  "
              f"최신 {nat[-1]['ym']}={nat[-1]['value']} ({name})")

    result = {**out, "tables_used": tables_used,
              "collected_at": datetime.date.today().isoformat(),
              "source": "한국부동산원 부동산통계정보 R-ONE"}
    path = ROOT / "data" / "rone.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=1))
    return {"ok": True, "issues": issues, "path": str(path),
            "rows": sum(len(v) for t in out.values() for v in t.values())}


if __name__ == "__main__":
    print("R-ONE 수집:")
    r = collect()
    if r["issues"]:
        print("  [이슈]", "; ".join(r["issues"]))
    print(r)
