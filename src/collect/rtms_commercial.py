"""국토부 RTMS 신규 3종 실거래가 수집기: 상업업무용(nrg)·오피스텔(offi)·토지(land).

실행: python3 src/collect/rtms_commercial.py
산출: data/rtms_commercial.json (시도별 요약 우선, 원시 전량은 raw 캐시)
  {"nrg":  {"서울": {"n","median_per_m2","p25","p75","by_use":{...}}, ...},
   "offi": {"서울": {"n","median_per_m2","p25","p75"}, ...},
   "land": {"서울": {"n","median_per_m2","p25","p75","by_jimok":{...}}, ...},
   "months": "YYYYMM~YYYYMM", "trim": {...종별 물리범위·제외수...},
   "sample_note", "coverage", "collected_at", "source"}

원본 XML은 data/raw/rtms_commercial/{kind}_{code}_{ym}_p{page}.xml 로 전량 캐시(있으면 재호출 스킵).

㎡당가 = dealAmount(만원→원) / 면적. 면적 필드는 종별로 다름:
  - nrg : buildingAr  (건물면적)  · by_use=buildingUse(건축물주용도) · plottageAr(대지)는 미사용
  - offi: excluUseAr  (전용면적)
  - land: dealArea    (거래면적)  · by_jimok=jimok(지목)

이상치 절사 = 종별 물리범위(원/㎡) 하드 게이트(파싱·단위·지분왜곡 오류 배제). 근거는 TRIM_RANGE 참조.
중위/사분위(median·p25·p75)는 그 자체로 강건 추정치이므로 게이트 통과분에 대해 산출.
호출 예의 0.25초 간격, 5xx/네트워크 백오프 재시도, 응답 오류는 예외로 전파(삼킴 금지).

주의: src/collect/rtms.py 는 수정하지 않음. REGIONS(시도별 대표 시군구)만 그 값과 동일하게 복제.
"""

import datetime
import json
import statistics
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from collect.common import ROOT, api_get, load_config  # noqa: E402

RAW_DIR = ROOT / "data" / "raw" / "rtms_commercial"

# 종별 엔드포인트(아파트 rtms.py 와 동일 호출문법: serviceKey·LAWD_CD·DEAL_YMD)
URLS = {
    "nrg":  "https://apis.data.go.kr/1613000/RTMSDataSvcNrgTrade/getRTMSDataSvcNrgTrade",
    "offi": "https://apis.data.go.kr/1613000/RTMSDataSvcOffiTrade/getRTMSDataSvcOffiTrade",
    "land": "https://apis.data.go.kr/1613000/RTMSDataSvcLandTrade/getRTMSDataSvcLandTrade",
}
KIND_NAME = {"nrg": "상업업무용", "offi": "오피스텔", "land": "토지"}

# 종별 (면적필드, 분류필드) — 분류필드는 by_* 집계용(없으면 None)
AREA_FIELD = {"nrg": "buildingAr", "offi": "excluUseAr", "land": "dealArea"}
CLASS_FIELD = {"nrg": "buildingUse", "offi": None, "land": "jimok"}

MONTHS = 36
CALL_GAP = 0.25
PER_PAGE = 1000

# ㎡당 가격 물리 유효범위(원/㎡). 벗어난 행은 제외(사유·표본 기록).
#   land: 토지는 지목·입지에 따라 산포가 극단적(임야<대지). 과제 지정 1만~5억/㎡ 채택.
#         하한 1만은 파싱·단위오류 및 초저가 임야 오염 배제, 상한 5억은 프라임 대지 상한.
#   offi: 오피스텔은 전용면적 기준. 아파트범위[2M,50M]보다 넓게 — 소형·전용률낮음으로 ㎡당 상향,
#         지방 노후 오피스텔은 하향 → [1M, 60M].
#   nrg : 상업업무용은 건물면적 기준·집합(구분상가)~일반(근생/공장)로 아파트보다 산포 큼.
#         지분거래는 buildingAr(전체면적) 대비 지분가로 ㎡당 저평가될 수 있음 → 하한 30만으로만 게이트,
#         상한 2억(건물기준, 토지 5억보다 낮게).
TRIM_RANGE = {
    "nrg":  (300_000,   200_000_000),
    "offi": (1_000_000,  60_000_000),
    "land": (10_000,    500_000_000),
}

# 수집 대상 (시도명[common.SIDO 단축명], 시군구명, [법정동 시군구 5자리...]).
# rtms.py REGIONS 값을 동일하게 복제(동시편집 결합 회피). 화성은 2025 구신설로 41590~41593 병합.
REGIONS = [
    ("서울", "강남구",       ["11680"]),
    ("서울", "노원구",       ["11350"]),
    ("부산", "해운대구",     ["26350"]),
    ("대구", "수성구",       ["27260"]),
    ("인천", "연수구",       ["28185"]),
    ("광주", "광산구",       ["12330"]),
    ("대전", "유성구",       ["30200"]),
    ("울산", "남구",         ["31140"]),
    ("세종", "세종시",       ["36110"]),
    ("경기", "수원시영통구", ["41117"]),
    ("경기", "화성시",       ["41590", "41591", "41592", "41593"]),
    ("강원", "춘천시",       ["51110"]),
    ("충북", "청주시흥덕구", ["43113"]),
    ("충남", "천안시서북구", ["44133"]),
    ("전북", "전주시완산구", ["52111"]),
    ("전남", "순천시",       ["12150"]),
    ("경북", "포항시북구",   ["47113"]),
    ("경남", "창원시성산구", ["48123"]),
    ("제주", "제주시",       ["50110"]),
]

# 시도 0건 시 대체 시군구 1회 허용(과제 명시): 광주 북구·전남 순천(순천은 이미 기본값이라 동일).
FALLBACK = {
    "광주": ("광산구", "12330"),
    "전남": ("순천시", "12150"),
}


def _months(n: int) -> list:
    today = datetime.date.today()
    out, y, m = [], today.year, today.month
    for _ in range(n):
        out.append(f"{y}{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return sorted(out)


def _fetch_page(kind: str, code: str, ym: str, page: int, key: str) -> str:
    cache = RAW_DIR / f"{kind}_{code}_{ym}_p{page}.xml"
    if cache.exists():
        return cache.read_text(encoding="utf-8")
    params = {
        "LAWD_CD": code, "DEAL_YMD": ym,
        "pageNo": str(page), "numOfRows": str(PER_PAGE), "serviceKey": key,
    }
    status, text = None, ""
    for attempt in range(5):
        status, text = api_get(URLS[kind], params, retries=2)
        time.sleep(CALL_GAP)
        if status == 200:
            break
        if status == -1 or 500 <= status < 600:   # 게이트웨이 5xx·네트워크 = 일시적
            time.sleep(2.0 * (attempt + 1))
            continue
        break
    if status != 200:
        raise RuntimeError(f"RTMS-C HTTP {status} ({kind} {code} {ym}): {text[:200]}")
    root = ET.fromstring(text)
    rc = root.findtext("./header/resultCode")
    if rc not in ("00", "000"):
        raise RuntimeError(f"RTMS-C 응답오류 {rc} ({kind} {code} {ym}): {root.findtext('./header/resultMsg')}")
    cache.write_text(text, encoding="utf-8")
    return text


def _fetch_month(kind: str, code: str, ym: str, key: str) -> list:
    text = _fetch_page(kind, code, ym, 1, key)
    root = ET.fromstring(text)
    total = int(root.findtext("./body/totalCount") or "0")
    items = root.findall("./body/items/item")
    fetched = len(items)
    page = 1
    while fetched < total:
        page += 1
        text = _fetch_page(kind, code, ym, page, key)
        pg = ET.fromstring(text).findall("./body/items/item")
        if not pg:
            break
        items.extend(pg)
        fetched += len(pg)
    return items


def _price_per_m2(kind: str, item: ET.Element):
    """(ppm2, reason). 유효=(float,None), 무효=(None,사유)."""
    amt_raw = (item.findtext("dealAmount") or "").replace(",", "").strip()
    area_raw = (item.findtext(AREA_FIELD[kind]) or "").strip()
    if not amt_raw or not area_raw:
        return None, "빈 금액/면적"
    try:
        won = int(amt_raw) * 10_000        # 만원 → 원
        area = float(area_raw)
    except ValueError:
        return None, f"파싱실패 amt={amt_raw!r} area={area_raw!r}"
    if area <= 0:
        return None, "면적<=0"
    ppm2 = won / area
    lo, hi = TRIM_RANGE[kind]
    if not (lo <= ppm2 <= hi):
        return None, f"범위밖 {ppm2:,.0f}원/㎡"
    return ppm2, None


def _collect_kind(kind: str, months: list, key: str):
    """kind 전체 수집 → (summary_by_sido, total_n, excluded, excluded_samples)."""
    # 시도 → {"vals":[ppm2...], "cls":{분류:count}}
    agg = {}

    def _accumulate(sido, codes):
        n_added = 0
        for ym in months:
            for code in codes:
                for item in _fetch_month(kind, code, ym, key):
                    ppm2, reason = _price_per_m2(kind, item)
                    if ppm2 is None:
                        agg[sido]["excl"].append(reason)
                        continue
                    agg[sido]["vals"].append(ppm2)
                    n_added += 1
                    cf = CLASS_FIELD[kind]
                    if cf:
                        c = (item.findtext(cf) or "").strip() or "미상"
                        agg[sido]["cls"][c] = agg[sido]["cls"].get(c, 0) + 1
        return n_added

    for sido, _name, codes in REGIONS:
        agg.setdefault(sido, {"vals": [], "cls": {}, "excl": []})
        _accumulate(sido, codes)

    # 시도 0건 → 대체 시군구 1회(대체코드가 기본 코드와 다를 때만 실효)
    base_codes = {}
    for s, _n, cs in REGIONS:
        base_codes.setdefault(s, set()).update(cs)
    fallback_used = {}
    for sido, (fname, fcode) in FALLBACK.items():
        if sido in agg and not agg[sido]["vals"] and fcode not in base_codes.get(sido, set()):
            added = _accumulate(sido, [fcode])
            fallback_used[sido] = {"name": fname, "code": fcode, "added": added}

    summary, total_n, excluded, excl_samples = {}, 0, 0, []
    for sido, d in agg.items():
        vals = d["vals"]
        excluded += len(d["excl"])
        if excl_samples.__len__() < 20:
            for r in d["excl"][:2]:
                if len(excl_samples) < 20:
                    excl_samples.append(f"{kind} {sido} {r}")
        if not vals:
            continue
        vals_sorted = sorted(vals)
        n = len(vals)
        total_n += n
        if n >= 2:
            q = statistics.quantiles(vals_sorted, n=4, method="inclusive")
            p25, p75 = round(q[0]), round(q[2])
        else:
            p25 = p75 = round(vals_sorted[0])
        entry = {
            "n": n,
            "median_per_m2": round(statistics.median(vals_sorted)),
            "p25": p25, "p75": p75,
        }
        if CLASS_FIELD[kind]:
            key_name = "by_use" if kind == "nrg" else "by_jimok"
            entry[key_name] = dict(sorted(d["cls"].items(), key=lambda x: -x[1]))
        summary[sido] = entry
    return summary, total_n, excluded, excl_samples, fallback_used


def collect() -> dict:
    key = load_config()["service_key"]
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    months = _months(MONTHS)
    print(f"RTMS 신규 3종 {MONTHS}개월 수집 ({months[0]}~{months[-1]}) …")

    result = {}
    trim_meta, coverage, totals, fallbacks = {}, {}, {}, {}
    for kind in ("nrg", "offi", "land"):
        print(f"\n[{KIND_NAME[kind]} {kind}] 수집 …")
        summary, total_n, excluded, samples, fb = _collect_kind(kind, months, key)
        result[kind] = summary
        totals[kind] = total_n
        lo, hi = TRIM_RANGE[kind]
        trim_meta[kind] = {
            "area_field": AREA_FIELD[kind],
            "phys_range_won_per_m2": [lo, hi],
            "excluded": excluded,
            "excluded_samples": samples,
        }
        coverage[kind] = {"sido_covered": len(summary), "total_n": total_n,
                          "sido_list": sorted(summary.keys())}
        if fb:
            fallbacks[kind] = fb
        print(f"  → 전국 유효 {total_n}건, 시도 {len(summary)}/17 커버, 제외 {excluded}")
        for sido, _name, _codes in REGIONS:
            e = summary.get(sido)
            if e:
                print(f"    {sido:<4} n={e['n']:>5} median={e['median_per_m2']:>12,}원/㎡")
            else:
                print(f"    {sido:<4} 0건  ← 미커버")

    all_sido = sorted({r[0] for r in REGIONS})
    missing = {}
    for kind in ("nrg", "offi", "land"):
        got = set(result[kind].keys())
        miss = [s for s in all_sido if s not in got]
        if miss:
            missing[kind] = miss

    out = {
        **result,
        "months": f"{months[0]}~{months[-1]}",
        "trim": trim_meta,
        "coverage": coverage,
        "totals": totals,
        "missing_sido": missing,
        "fallback_used": fallbacks,
        "sample_note": "시도별 대표 시군구 표본(rtms.py REGIONS 동일). 서울=강남+노원, 경기=수원영통+화성 풀링.",
        "collected_at": datetime.date.today().isoformat(),
        "source": "국토교통부 RTMS 실거래가(상업업무용·오피스텔·토지)",
    }
    path = ROOT / "data" / "rtms_commercial.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1))

    print("\n=== 요약 ===")
    for kind in ("nrg", "offi", "land"):
        print(f"{KIND_NAME[kind]:<8} 전국 {totals[kind]:>7,}건 · {coverage[kind]['sido_covered']}/17 시도")
    if missing:
        print(f"미커버: {missing}")
    if fallbacks:
        print(f"대체 시군구 사용: {fallbacks}")
    return {"ok": True, "totals": totals, "missing": missing,
            "fallback": fallbacks, "path": str(path)}


if __name__ == "__main__":
    print(collect())
