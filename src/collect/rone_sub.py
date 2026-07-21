"""한국부동산원 R-ONE 시군구(하위지역) 수집기: 아파트 매매·전세가격지수 월별.

실행: python3 src/collect/rone_sub.py
산출: data/rone_sub.json
  {"sale_sub":   {"서울": {"강남구": [{"ym","value"}...], ...}, "경기": {...}, ...},
   "jeonse_sub": {...동일 구조...} | null,   # 전세지수(A_2024_00050); 수집 불가 시 null·기록
   "regions":    {"서울": ["강남구", ...], ...},   # 시도별 하위지역 목록
   "collected_at", "source"}

CLS 계층(SttsApiTblData 실측): 시도는 최상위 CLS, 시군구는 하위 CLS(CLS_FULLNM 에 '>').
가변 depth라 시도별 접미사로 리프를 선별한다(중간 '권역'은 '권'·'지역'으로 끝나 자동 배제):
  - 서울 25구: '서울>{권역}>{구}'               (depth 3)  접미사 '구'
  - 경기 시:   '경기>{권역}>{시}'               (depth 2)  접미사 '시'  (구는 제외)
  - 부산 구·군: '부산>{권역}>{구|군}'           (depth 2)  접미사 '구/군'
  - 대구·인천·광주·대전·울산: '{시도}>{구|군}'  (depth 1)  접미사 '구/군'
시도 최상위 노드(예: '대구' 자기 자신)는 세그먼트 1개라 배제한다.
원본 응답은 data/raw/rone_sub/ 에 전량 캐시(재실행 시 API 재호출 스킵). 5xx/네트워크는 백오프 재시도.
"""

import datetime
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from collect.common import ROOT, api_get, load_config  # noqa: E402
from collect.rone import _cutoff_ym, _ym_minus  # noqa: E402  (10년 창·월 헬퍼 재사용)

RAW_DIR = ROOT / "data" / "raw" / "rone_sub"
BASE = "https://www.reb.or.kr/r-one/openapi"
CALL_GAP = 0.3  # 호출 간 대기(초)

# 수집 대상 시도(특별·광역시 우선) 와 하위지역 리프 접미사
UNIT_SUFFIX = {
    "서울": ("구",),
    "경기": ("시",),          # 시 단위(수원·용인 등 하위 구는 제외)
    "부산": ("구", "군"),
    "대구": ("구", "군"),
    "인천": ("구", "군"),
    "광주": ("구", "군"),
    "대전": ("구", "군"),
    "울산": ("구", "군"),
}
TARGET = list(UNIT_SUFFIX)

# R-ONE 표: (출력키, STATBL_ID, 이름, 필수여부)
TABLES = [
    ("sale_sub", "A_2024_00045", "(월) 매매가격지수_아파트", True),
    ("jeonse_sub", "A_2024_00050", "(월) 전세가격지수_아파트", False),
]

INDEX_LO, INDEX_HI = 20.0, 200.0  # 지수 유효범위


def _get(key: str, params: dict) -> list:
    """SttsApiTblData.do 호출 → row 리스트. 5xx/네트워크는 백오프 재시도(오류 삼킴 금지)."""
    url = f"{BASE}/SttsApiTblData.do"
    p = dict(params, KEY=key, Type="json")
    status, text = None, ""
    for attempt in range(5):
        status, text = api_get(url, p, retries=2)
        time.sleep(CALL_GAP)
        if status == 200:
            break
        if status == -1 or 500 <= status < 600:  # 게이트웨이 일시 오류 → 백오프
            time.sleep(2.0 * (attempt + 1))
            continue
        break
    if status != 200:
        raise RuntimeError(f"R-ONE HTTP {status} ({params.get('STATBL_ID')}): {text[:200]}")
    doc = json.loads(text)
    obj = doc.get("SttsApiTblData")
    if obj is None:  # RESULT-only: INFO-200(빈 결과)만 허용
        code = doc.get("RESULT", {}).get("CODE")
        if code == "INFO-200":
            return []
        raise RuntimeError(f"R-ONE 비정상 응답 {params.get('STATBL_ID')}: {text[:200]}")
    head = obj[0]["head"]
    result = head[1]["RESULT"]
    if result["CODE"] != "INFO-000":
        raise RuntimeError(f"R-ONE 오류 {params.get('STATBL_ID')}: {result}")
    total = int(head[0]["list_total_count"])
    rows = list(obj[1]["row"])
    page = 2
    while len(rows) < total:  # 방어적 페이지네이션(단일 CLS 시계열은 보통 1페이지)
        pg = dict(p, pIndex=str(page))
        st, tx = api_get(url, pg, retries=2)
        if st != 200:
            raise RuntimeError(f"R-ONE HTTP {st} (page {page}, {params.get('STATBL_ID')})")
        rows.extend(json.loads(tx)["SttsApiTblData"][1]["row"])
        page += 1
        time.sleep(CALL_GAP)
    return rows


def _discover_month(key: str, statbl_id: str):
    """데이터가 존재하는 최근 월 1개의 전체 분류(CLS) 행 — 시군구 매핑용."""
    for off in range(0, 15):
        ym = _ym_minus(off)
        cache = RAW_DIR / f"{statbl_id}_month_{ym}.json"
        if cache.exists():
            rows = json.loads(cache.read_text())
        else:
            rows = _get(key, {"STATBL_ID": statbl_id, "DTACYCLE_CD": "MM",
                              "WRTTIME_IDTFR_ID": ym, "pIndex": "1", "pSize": "500"})
            cache.write_text(json.dumps(rows, ensure_ascii=False))
        if rows:
            return ym, rows
    raise RuntimeError(f"R-ONE {statbl_id}: 최근 15개월 내 데이터 없음")


def _fetch_series(key: str, statbl_id: str, cls_id) -> list:
    """CLS_ID 한 개의 전체 월별 시계열(원본 캐시)."""
    cache = RAW_DIR / f"{statbl_id}_{cls_id}.json"
    if cache.exists():
        return json.loads(cache.read_text())
    rows = _get(key, {"STATBL_ID": statbl_id, "DTACYCLE_CD": "MM",
                      "CLS_ID": str(cls_id), "pIndex": "1", "pSize": "1000"})
    cache.write_text(json.dumps(rows, ensure_ascii=False))
    return rows


def _region_map(rows: list) -> dict:
    """CLS 행 목록 → {시도: {하위지역명: CLS_ID}}. 시도별 접미사 리프만 선별."""
    out = {s: {} for s in TARGET}
    for r in rows:
        full = r.get("CLS_FULLNM") or ""
        seg = full.split(">")
        if len(seg) < 2:  # 시도 최상위 노드(예: '대구') 배제
            continue
        sido = seg[0]
        suffix = UNIT_SUFFIX.get(sido)
        if suffix is None:
            continue
        nm = r.get("CLS_NM") or ""
        if r.get("DTA_VAL") is None:  # 해당 월 결측 노드 제외
            continue
        if nm.endswith(suffix):
            out[sido][nm] = r["CLS_ID"]
    return out


def _series_for(key: str, statbl_id: str, cls_id, cutoff: str) -> list:
    """한 CLS_ID 의 최근 10년(cutoff 이후) {ym,value} 시계열."""
    pts = []
    for r in _fetch_series(key, statbl_id, cls_id):
        ym = r.get("WRTTIME_IDTFR_ID")
        val = r.get("DTA_VAL")
        if ym is None or val is None or ym < cutoff:
            continue
        pts.append({"ym": ym, "value": round(float(val), 4)})
    pts.sort(key=lambda x: x["ym"])
    return pts


def _collect_table(key: str, statbl_id: str, cutoff: str) -> dict:
    """표 한 개 → {시도: {하위지역: [{ym,value}...]}}. 검증 포함."""
    _, month_rows = _discover_month(key, statbl_id)
    rmap = _region_map(month_rows)
    by_sido = {}
    for sido in TARGET:
        units = {}
        for unit, cls_id in sorted(rmap[sido].items()):
            pts = _series_for(key, statbl_id, cls_id, cutoff)
            bad = [p for p in pts if not (INDEX_LO <= p["value"] <= INDEX_HI)]
            assert not bad, f"{statbl_id}/{sido}/{unit}: 지수 범위 밖 {bad[:3]}"
            if pts:
                units[unit] = pts
        by_sido[sido] = units
    assert len(by_sido["서울"]) == 25, f"{statbl_id}: 서울 {len(by_sido['서울'])}개≠25"
    return by_sido


def collect() -> dict:
    key = load_config()["rone_key"]
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    cutoff = _cutoff_ym()
    out = {}
    regions = {}
    issues = []
    for out_key, statbl_id, name, required in TABLES:
        try:
            by_sido = _collect_table(key, statbl_id, cutoff)
        except Exception as e:  # noqa: BLE001
            if required:
                raise
            out[out_key] = None
            issues.append(f"{out_key} 수집 실패(매매만 진행): {e}")
            print(f"  {out_key:<11} [실패] {e}")
            continue
        out[out_key] = by_sido
        if out_key == "sale_sub":
            regions = {s: sorted(by_sido[s]) for s in TARGET}
        rows = sum(len(p) for u in by_sido.values() for p in u.values())
        cov = " ".join(f"{s}{len(by_sido[s])}" for s in TARGET)
        print(f"  {out_key:<11} 지역 {sum(len(by_sido[s]) for s in TARGET)}  행 {rows}  ({cov})  {name}")

    result = {
        "sale_sub": out["sale_sub"],
        "jeonse_sub": out.get("jeonse_sub"),
        "regions": regions,
        "collected_at": datetime.date.today().isoformat(),
        "source": "한국부동산원 부동산통계정보 R-ONE",
    }
    path = ROOT / "data" / "rone_sub.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=1))
    total_rows = sum(len(p) for u in (out["sale_sub"] or {}).values() for p in u.values())
    if out.get("jeonse_sub"):
        total_rows += sum(len(p) for u in out["jeonse_sub"].values() for p in u.values())
    return {"ok": True, "issues": issues, "path": str(path), "rows": total_rows,
            "regions": {s: len(v) for s, v in regions.items()},
            "jeonse": out.get("jeonse_sub") is not None}


if __name__ == "__main__":
    print("R-ONE 시군구 수집:")
    r = collect()
    if r["issues"]:
        print("  [이슈]", "; ".join(r["issues"]))
    print(r)
