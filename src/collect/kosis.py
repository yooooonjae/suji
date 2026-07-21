"""KOSIS(통계청 국가통계포털) 수집기: 미분양·준공후미분양·인허가·착공·준공·건설공사비지수.

실행: python3 src/collect/kosis.py
산출: data/kosis.json
  {"unsold":            {"서울": [{"ym":"201607","value":...}, ...], ...},  # 미분양 호수(월별)
   "unsold_completed":  {"서울": [...], ...},                              # 준공후 미분양 호수(월별)
   "permits":           {"서울": [{"ym":"2016","value":...}, ...], ...},   # 주택건설 인허가 호수(★연별)
   "starts":            {"서울": [...], ...},                              # 주택건설 착공 호수(월별)
   "completions":       {"서울": [...], ...},                              # 주택건설 준공 호수(월별)
   "cci":               [{"ym":"201607","value":...}, ...],               # 건설공사비지수(전국, 2020=100)
   "tables_used": [...], "collected_at", "source"}

API: statisticsParameterData.do(method=getList). err 20 "(objL)" = 필수 분류축 누락 →
표별 objL1..objLN 요구가 달라 getMeta 로 축 구조를 실측해 필요한 objL만 채움(주석 참조).
원본 응답은 data/raw/kosis/ 에 전량 캐시(재실행 시 API 재호출 스킵).

주의: 주택건설 인허가는 시도별 월별 표가 KOSIS에 없어(DT_MLTM_626/666 = 연별 전용)
      permits 는 연별(ym="YYYY")로 수집한다. docs/api-status.md 기록.
"""

import datetime
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from collect.common import ROOT, SIDO, api_get, load_config  # noqa: E402

RAW_DIR = ROOT / "data" / "raw" / "kosis"
URL = "https://kosis.kr/openapi/Param/statisticsParameterData.do"
YEARS = 10

VALID_SIDO = set(SIDO.values())  # 17개
NORMALIZE = {
    "서울특별시": "서울", "부산광역시": "부산", "대구광역시": "대구", "인천광역시": "인천",
    "광주광역시": "광주", "대전광역시": "대전", "울산광역시": "울산", "세종특별자치시": "세종",
    "경기도": "경기", "강원도": "강원", "강원특별자치도": "강원", "충청북도": "충북",
    "충청남도": "충남", "전라북도": "전북", "전북특별자치도": "전북", "전라남도": "전남",
    "경상북도": "경북", "경상남도": "경남", "제주도": "제주", "제주특별자치도": "제주",
}


def _norm(name: str):
    """KOSIS 지역명 → common.SIDO 단축명. 시도 아님(수도권·지방권 등)이면 None."""
    if name in VALID_SIDO:
        return name
    return NORMALIZE.get(name)


# 계열 정의: (out_key, orgId, tblId, itmId, {objLn:code}, prdSe, region_col, 이름)
#   objL 코드는 getMeta 실측값. 'ALL' = 전 항목(시도축 전개).
#   region_col = 응답에서 시도가 담기는 열(C1_NM=objL1, C3_NM=objL3 …).
SERIES = [
    ("unsold", "116", "DT_MLTM_2080", "13103792722T1",
     {"objL1": "ALL", "objL2": "13102792722B.0001", "objL3": "13102792722C.0001"},
     "M", "C1_NM", "규모별 미분양현황(부문·규모 총합)"),
    # 시군구축: 전국은 '합계'(B.0001), 각 시도는 '계'(B.0002) — 둘 다 '+' 로 요청해 시도 총계 확보
    ("unsold_completed", "116", "DT_MLTM_5328", "13103871088T1",
     {"objL1": "ALL", "objL2": "13102871088B.0001+13102871088B.0002",
      "objL3": "13102871088C.0001", "objL4": "13102871088D.0001"},
     "M", "C1_NM", "공사완료후 미분양현황(부문·규모 계)"),
    ("permits", "116", "DT_MLTM_666", "ALL",
     {"objL1": "ALL"},
     "Y", "C1_NM", "지역별 주택건설 인허가실적(연별)"),
    ("starts", "116", "DT_MLTM_5386", "13103766971T1",
     {"objL1": "13102766971A.0001", "objL2": "13102766971B.0001", "objL3": "ALL"},
     "M", "C3_NM", "주택건설 착공실적(월계, 총계)"),
    ("completions", "116", "DT_MLTM_5372", "13103766972T1",
     {"objL1": "13102766972A.0001", "objL2": "13102766972B.0001", "objL3": "ALL"},
     "M", "C3_NM", "주택건설 준공실적(월계, 총계)"),
    ("cci", "397", "DT_39701_A003", "ALL",
     {"objL1": "ALL"},
     "M", "C1_NM", "건설공사비지수(2020=100, 전국)"),
]


def _period(prd_se: str):
    t = datetime.date.today()
    if prd_se == "M":
        return f"{t.year - YEARS}{t.month:02d}", f"{t.year}{t.month:02d}"
    return f"{t.year - YEARS}", f"{t.year}"


def _fetch(key: str, org: str, tbl: str, itm: str, objl: dict, prd_se: str) -> list:
    """statisticsParameterData 호출 → row 리스트(원본 캐시). 오류는 즉시 예외."""
    cache = RAW_DIR / f"{tbl}.json"
    if cache.exists():
        return json.loads(cache.read_text())
    start, end = _period(prd_se)
    params = {"method": "getList", "apiKey": key, "orgId": org, "tblId": tbl,
              "itmId": itm, "format": "json", "jsonVD": "Y",
              "prdSe": prd_se, "startPrdDe": start, "endPrdDe": end}
    params.update(objl)
    st, tx = api_get(URL, params, retries=1)
    if st != 200:
        raise RuntimeError(f"KOSIS HTTP {st} {tbl}: {tx[:200]}")
    tx = tx.strip()
    if not tx.startswith("["):  # {"err":..} — 오류를 절대 삼키지 않는다
        raise RuntimeError(f"KOSIS 오류 {tbl}: {tx[:200]}")
    rows = json.loads(tx)
    cache.write_text(json.dumps(rows, ensure_ascii=False))
    time.sleep(0.3)
    return rows


def _to_series(rows: list, region_col: str, out_key: str) -> dict:
    """행 목록 → {시도명: [{ym,value}]}."""
    by = {}
    for r in rows:
        raw = r.get(region_col)
        if raw is None:
            continue
        if out_key == "permits" and raw == "실적":  # 666: 전국 실적 = 전국 합계
            sido = "전국"
        elif out_key == "permits" and raw == "계획":  # 계획치는 제외
            continue
        elif raw == "전국":
            sido = "전국"
        else:
            sido = _norm(raw)
        if sido is None:
            continue
        val = r.get("DT")
        if val in (None, "", "-", "..."):
            continue
        by.setdefault(sido, []).append({"ym": r["PRD_DE"], "value": round(float(val), 4)})
    for s in by.values():
        s.sort(key=lambda x: x["ym"])
    return by


# 값 범위 검증 한계: (하한, 상한). 착공·준공(월 플로우)은 정정치로 음수가 나올 수 있어 하한 완화.
RANGE = {
    "unsold": (0, 200000), "unsold_completed": (0, 200000),
    "permits": (0, 1000000), "starts": (-100000, 200000), "completions": (-100000, 200000),
    "cci": (20, 200),
}


def collect() -> dict:
    key = load_config()["kosis_key"]
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    out = {}
    tables_used = []
    issues = []
    for out_key, org, tbl, itm, objl, prd_se, region_col, name in SERIES:
        rows = _fetch(key, org, tbl, itm, objl, prd_se)

        if out_key == "cci":  # 전국 단일 계열: C1_NM=='건설' 총지수
            pts = [{"ym": r["PRD_DE"], "value": round(float(r["DT"]), 4)}
                   for r in rows if r.get("C1_NM") == "건설" and r.get("DT") not in (None, "")]
            pts.sort(key=lambda x: x["ym"])
            lo, hi = RANGE[out_key]
            bad = [p for p in pts if not (lo <= p["value"] <= hi)]
            assert not bad, f"{out_key}: 범위 밖 {bad[:3]}"
            assert len(pts) >= 24, f"{out_key}: 행수 부족 {len(pts)}"
            out[out_key] = pts
            tables_used.append({"id": tbl, "name": name})
            print(f"  {out_key:<17} 전국 {len(pts)}개월  최신 {pts[-1]['ym']}={pts[-1]['value']} ({name})")
            continue

        by = _to_series(rows, region_col, out_key)
        out[out_key] = by

        # 검증: 값 범위·시도 커버·전국 행수
        lo, hi = RANGE[out_key]
        for sido, pts in by.items():
            bad = [p for p in pts if not (lo <= p["value"] <= hi)]
            assert not bad, f"{out_key}/{sido}: 범위 밖 {bad[:3]}"
        covered = set(by) & VALID_SIDO
        missing = VALID_SIDO - covered
        nat = by.get("전국", [])
        assert len(nat) >= 8, f"{out_key}: 전국 행수 부족 {len(nat)}"
        if missing:
            issues.append(f"{out_key}: 시도 누락 {sorted(missing)}")
        tables_used.append({"id": tbl, "name": name})
        unit = "개월" if prd_se == "M" else "개년"
        print(f"  {out_key:<17} 시도 {len(covered)}/17  전국 {len(nat)}{unit}  "
              f"최신 {nat[-1]['ym']}={nat[-1]['value']} ({name})")

    result = {**out, "tables_used": tables_used,
              "collected_at": datetime.date.today().isoformat(),
              "source": "통계청 국가통계포털(KOSIS) · 건설공사비지수는 한국건설기술연구원"}
    path = ROOT / "data" / "kosis.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=1))
    return {"ok": True, "issues": issues, "path": str(path),
            "rows": sum((len(v) if isinstance(v, list) else sum(len(x) for x in v.values()))
                        for k, v in out.items())}


if __name__ == "__main__":
    print("KOSIS 수집:")
    r = collect()
    if r["issues"]:
        print("  [이슈]", "; ".join(r["issues"]))
    print(r)
