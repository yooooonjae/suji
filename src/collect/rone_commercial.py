"""한국부동산원 R-ONE 상업용부동산 임대동향조사 수집기: 오피스·중대형상가 분기별 시계열.

실행: python3 src/collect/rone_commercial.py
산출: data/rone_commercial.json
  {"office_rent_index":  {"서울": [{"yq":"2016Q3","value":...}, ...], "전국": [...], ...},  # 지수(2024.2Q=100)
   "office_vacancy":     {...},                                    # 공실률 %
   "office_yield":       {"서울": [{"yq","total","income","capital"}, ...], ...},  # 투자/소득/자본수익률 %(분기)
   "office_rent_level":  {...},                                    # 임대료 천원/㎡(㎡당)
   "retail_rent_index":  {...},                                    # 중대형상가 임대가격지수(2024.2Q=100)
   "retail_vacancy":     {...},                                    # 중대형상가 공실률 %
   "region_type":        "시도",
   "tables_used": [{"id","name"}], "collected_at", "source"}

R-ONE 구조(SttsApiTblData 실측):
  - 상업용 임대동향은 분기(QY). WRTTIME_IDTFR_ID = "YYYYQQ"(예 202601 = 2026년 1분기).
  - 지역축(CLS): 최상위(CLS_FULLNM 에 '>' 없음) = 전국·시도 → common.SIDO 단축명과 일치.
    하위(CLS_FULLNM 에 '>') = 상권/권역(도심>광화문 등) — 본 수집은 시도 레벨만 사용.
  - 지수는 기준시점 재설정(rebase) 때문에 기간별 표가 나뉘나, '임대가격지수(시계열)' 표가
    2013Q1~현재를 단일 기준(2024.2Q=100)으로 연결 제공 → 지수는 시계열 표 1개 사용.
  - 공실률·수익률·임대료(수준)는 레벨값이라 rebase 무관 → 기간별 표(2013~2016 … 2024Q3~)를
    분기 겹침 없이 이어 붙여(stitch) 시계열 구성. 수익률표는 투자/소득/자본 3개 항목(ITM) 동시 수록.
원본 응답은 data/raw/rone_commercial/ 에 STATBL_ID 단위로 전량 캐시(재실행 시 API 재호출 스킵).
"""

import datetime
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from collect.common import ROOT, SIDO, api_get, load_config  # noqa: E402

RAW_DIR = ROOT / "data" / "raw" / "rone_commercial"
BASE = "https://www.reb.or.kr/r-one/openapi"
YEARS = 10
CALL_GAP = 0.3
PSIZE = 1000  # R-ONE pSize 상한(초과 시 ERROR-336)

VALID = {"전국"} | set(SIDO.values())  # 전국 + 17시도

# 지수: 단일 '시계열' 표(2013Q1~현재, 기준 2024.2Q=100) — (출력키, STATBL_ID, 표명)
RENT_INDEX = [
    ("office_rent_index", "TT244963134453269", "임대동향 지역별 임대가격지수(시계열)_오피스"),
    ("retail_rent_index", "TT248473134635539", "임대동향 지역별 임대가격지수(시계열)_중대형 상가"),
]

# 레벨값: 기간별 표를 분기 겹침 없이 이어붙임(2013~2016 → … → 2024Q3~). ITM 단일.
STITCH_SINGLE = {
    "office_vacancy": (
        "공실률",
        ["A_2024_00238", "A_2024_00241", "A_2024_00244", "A_2024_00247",
         "A_2024_00250", "A_2024_00253", "TT244763134428698"],
        "임대동향 지역별 공실률_오피스(2013~2026, 기간표 stitch)",
    ),
    "retail_vacancy": (
        "공실률",
        ["A_2024_00239", "A_2024_00242", "A_2024_00245", "A_2024_00248",
         "A_2024_00251", "A_2024_00254", "T249633134845544"],
        "임대동향 지역별 공실률_중대형 상가(2013~2026, 기간표 stitch)",
    ),
    "office_rent_level": (
        "임대료",
        ["A_2024_00257", "A_2024_00261", "A_2024_00265", "A_2024_00269",
         "A_2024_00273", "A_2024_00277", "TT249843134237374"],
        "임대동향 지역별 임대료(천원/㎡)_오피스(2013~2026, 기간표 stitch)",
    ),
}

# 수익률: 투자/소득/자본 3개 항목을 한 표에 수록. 기간별 표 stitch.
YIELD = {
    "office_yield": (
        ["A_2024_00346", "A_2024_00350", "A_2024_00354", "A_2024_00358",
         "A_2024_00362", "A_2024_00366", "T245883135037859"],
        "임대동향 수익률(분기, 투자/소득/자본)_오피스(2013~2026, 기간표 stitch)",
    ),
}
YIELD_ITM = {"투자수익률": "total", "소득수익률": "income", "자본수익률": "capital"}


def _cutoff_yq() -> str:
    """10년 전 분기 키(YYYYQQ). 예: 2026Q3 기준 → '201603'."""
    t = datetime.date.today()
    q = (t.month - 1) // 3 + 1
    return f"{t.year - YEARS}{q:02d}"


def _yq(wrttime: str) -> str:
    """'202601' → '2026Q1'."""
    return f"{wrttime[:4]}Q{int(wrttime[4:])}"


def _get_page(statbl_id: str, page: int) -> tuple:
    """SttsApiTblData.do 한 페이지 → (total, rows). 오류 삼킴 금지(비정상은 예외)."""
    key = load_config()["rone_key"]
    p = {"KEY": key, "Type": "json", "STATBL_ID": statbl_id, "DTACYCLE_CD": "QY",
         "pIndex": str(page), "pSize": str(PSIZE)}
    status, text = None, ""
    for attempt in range(4):  # 게이트웨이 일시오류(5xx/네트워크/336) 백오프 재시도
        status, text = api_get(f"{BASE}/SttsApiTblData.do", p, retries=1)
        time.sleep(CALL_GAP)
        if status == 200:
            break
        if status == -1 or 500 <= status < 600:
            time.sleep(2.0 * (attempt + 1))
            continue
        break
    if status != 200:
        raise RuntimeError(f"R-ONE HTTP {status} ({statbl_id}): {text[:200]}")
    doc = json.loads(text)
    obj = doc.get("SttsApiTblData")
    if obj is None:  # RESULT-only
        code = doc.get("RESULT", {}).get("CODE")
        if code == "INFO-200":
            return 0, []
        raise RuntimeError(f"R-ONE 비정상 응답 {statbl_id}: {text[:200]}")
    head = obj[0]["head"]
    result = head[1]["RESULT"]
    if result["CODE"] != "INFO-000":
        raise RuntimeError(f"R-ONE 오류 {statbl_id}: {result}")
    total = int(head[0]["list_total_count"])
    rows = list(obj[1]["row"])
    return total, rows


def _fetch_table(statbl_id: str) -> list:
    """한 표의 전체 분기 행(전 페이지). STATBL_ID 단위 캐시."""
    cache = RAW_DIR / f"{statbl_id}.json"
    if cache.exists():
        return json.loads(cache.read_text())
    total, rows = _get_page(statbl_id, 1)
    page = 2
    while len(rows) < total:
        _, more = _get_page(statbl_id, page)
        if not more:
            break
        rows.extend(more)
        page += 1
    cache.write_text(json.dumps(rows, ensure_ascii=False))
    return rows


def _sido_rows(rows: list, itm_nm: str | None = None) -> list:
    """시도 레벨(CLS_FULLNM 에 '>' 없음) + VALID 만. itm_nm 지정 시 해당 항목만."""
    out = []
    for r in rows:
        full = r.get("CLS_FULLNM") or ""
        if ">" in full:
            continue
        nm = r.get("CLS_NM")
        if nm not in VALID:
            continue
        if itm_nm is not None and r.get("ITM_NM") != itm_nm:
            continue
        if r.get("DTA_VAL") is None:
            continue
        out.append(r)
    return out


def _collect_single(itm_nm: str, ids: list, cutoff: str) -> dict:
    """단일 항목 계열(지수/공실률/임대료) → {시도: [{yq,value}...]}. 기간표 stitch·중복 분기 최신 우선."""
    by_region = {}  # region -> {wrttime: value}
    for sid in ids:
        for r in _sido_rows(_fetch_table(sid), itm_nm):
            wt = r.get("WRTTIME_IDTFR_ID")
            if wt is None or wt < cutoff:
                continue
            by_region.setdefault(r["CLS_NM"], {})[wt] = round(float(r["DTA_VAL"]), 4)
    out = {}
    for region, wmap in by_region.items():
        pts = [{"yq": _yq(w), "value": v} for w, v in sorted(wmap.items())]
        if pts:
            out[region] = pts
    return out


def _collect_yield(ids: list, cutoff: str) -> dict:
    """수익률 계열 → {시도: [{yq,total,income,capital}...]}. 3개 항목 병합."""
    by_region = {}  # region -> {wrttime: {total,income,capital}}
    for sid in ids:
        for r in _sido_rows(_fetch_table(sid)):
            field = YIELD_ITM.get(r.get("ITM_NM"))
            if field is None:
                continue
            wt = r.get("WRTTIME_IDTFR_ID")
            if wt is None or wt < cutoff:
                continue
            slot = by_region.setdefault(r["CLS_NM"], {}).setdefault(wt, {})
            slot[field] = round(float(r["DTA_VAL"]), 4)
    out = {}
    for region, wmap in by_region.items():
        pts = []
        for w, d in sorted(wmap.items()):
            pt = {"yq": _yq(w)}
            pt.update(d)
            pts.append(pt)
        if pts:
            out[region] = pts
    return out


def _validate(series_kind: str, key: str, data: dict):
    """검증 assert: 공실률 0~50%, 지수 20~200, 수익률 -10~20%, 계열(전국·서울) 행수 ≥ 20."""
    ranges = {"index": (20.0, 200.0), "vacancy": (0.0, 50.0), "yield": (-10.0, 20.0)}
    for region, pts in data.items():
        if series_kind == "yield":
            lo, hi = ranges["yield"]
            for p in pts:
                for f in ("total", "income", "capital"):
                    if f in p:
                        assert lo <= p[f] <= hi, f"{key}/{region}: 수익률 범위 밖 {f}={p[f]} @{p['yq']}"
        elif series_kind in ("index", "vacancy"):
            lo, hi = ranges[series_kind]
            for p in pts:
                assert lo <= p["value"] <= hi, f"{key}/{region}: 범위 밖 {p['value']} @{p['yq']}"
        else:  # rent_level: 양수만
            for p in pts:
                assert p["value"] > 0, f"{key}/{region}: 임대료 비양수 {p['value']} @{p['yq']}"
    for anchor in ("전국", "서울"):
        if anchor in data:
            assert len(data[anchor]) >= 20, f"{key}: {anchor} 행수 부족 {len(data[anchor])}"


def collect() -> dict:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    cutoff = _cutoff_yq()
    out = {}
    tables_used = []
    summary = []

    for key, sid, name in RENT_INDEX:
        data = _collect_single_index(sid, cutoff)
        _validate("index", key, data)
        out[key] = data
        tables_used.append({"id": sid, "name": name})
        summary.append(_fmt(key, data))

    for key, (itm, ids, name) in STITCH_SINGLE.items():
        data = _collect_single(itm, ids, cutoff)
        kind = "vacancy" if "vacancy" in key else "rent_level"
        _validate(kind, key, data)
        out[key] = data
        tables_used.append({"id": "+".join(ids), "name": name})
        summary.append(_fmt(key, data))

    for key, (ids, name) in YIELD.items():
        data = _collect_yield(ids, cutoff)
        _validate("yield", key, data)
        out[key] = data
        tables_used.append({"id": "+".join(ids), "name": name})
        summary.append(_fmt(key, data, yield_=True))

    result = {
        **out,
        "region_type": "시도",
        "tables_used": tables_used,
        "collected_at": datetime.date.today().isoformat(),
        "source": "한국부동산원 부동산통계정보 R-ONE 상업용부동산 임대동향조사",
    }
    path = ROOT / "data" / "rone_commercial.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=1))
    return {"ok": True, "path": str(path), "cutoff": cutoff, "summary": summary}


def _collect_single_index(sid: str, cutoff: str) -> dict:
    """지수 시계열 표(ITM='지수' 단일) → {시도: [{yq,value}...]}."""
    by_region = {}
    for r in _sido_rows(_fetch_table(sid)):
        wt = r.get("WRTTIME_IDTFR_ID")
        if wt is None or wt < cutoff:
            continue
        by_region.setdefault(r["CLS_NM"], {})[wt] = round(float(r["DTA_VAL"]), 4)
    return {reg: [{"yq": _yq(w), "value": v} for w, v in sorted(wm.items())]
            for reg, wm in by_region.items() if wm}


def _fmt(key: str, data: dict, yield_: bool = False) -> str:
    regs = len(data)
    nat = data.get("전국") or data.get("서울") or next(iter(data.values()), [])
    span = f"{nat[0]['yq']}~{nat[-1]['yq']}" if nat else "-"
    last = nat[-1] if nat else {}
    val = (f"투{last.get('total')}/소{last.get('income')}/자{last.get('capital')}"
           if yield_ else last.get("value"))
    return f"{key:<18} 지역 {regs}  분기 {len(nat)}  {span}  최신={val}"


if __name__ == "__main__":
    print("R-ONE 상업용부동산 임대동향 수집:")
    r = collect()
    for line in r["summary"]:
        print("  " + line)
    print(r)
