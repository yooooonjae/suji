"""국토부 아파트 실거래가(RTMS) 수집기: 매매(최근 36개월)·분양권(최근 24개월).

실행: python3 src/collect/rtms.py
산출: data/rtms.json
  {"trades":        {"서울": {"강남구": [{"ym","median_price_per_m2","count"}...], ...}, ...},
   "presale_trades":{...동일 구조...},
   "sigungu_used":  {"서울": {"강남구": {"codes":[...],"sale_rows":n,"presale_rows":n,"note":...}}},
   "excluded": {"sale": n, "presale": n},
   "collected_at": "...", "source": "국토교통부 RTMS 실거래가"}

원본 XML은 data/raw/rtms/{sale|presale}_{code}_{ym}_p{page}.xml 로 전량 캐시(있으면 재호출 스킵).
가격 검증: dealAmount(만원)→원 변환 후 ㎡당가가 [2백만, 5천만] 원/㎡ 밖이면 행 제외·집계.
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

RAW_DIR = ROOT / "data" / "raw" / "rtms"

SALE_URL = "https://apis.data.go.kr/1613000/RTMSDataSvcAptTrade/getRTMSDataSvcAptTrade"
PRESALE_URL = "https://apis.data.go.kr/1613000/RTMSDataSvcSilvTrade/getRTMSDataSvcSilvTrade"

SALE_MONTHS = 36
PRESALE_MONTHS = 24
CALL_GAP = 0.25          # 호출 간 대기(초)
PER_PAGE = 1000

# ㎡당 가격 유효범위(원/㎡): 벗어나면 제외
PRICE_MIN = 2_000_000
PRICE_MAX = 50_000_000

# 수집 대상: (시도명[common.SIDO와 일치], 시군구명, [법정동 시군구 5자리 코드...])
# 화성시는 2025년 구(만세·병점·효행 등) 신설로 41590(구 통합코드)이 빈 응답 → 하위 41590~41593 병합.
# 광주(29)·전남(46)은 2026-07-01 통폐합으로 '전남광주통합특별시'(신 시도코드 12) 신설. RTMS가
#   전 이력을 신 코드로 재분할 → 구 코드 29xxx/46xxx는 totalCount=0. 강원(42→51)·전북(45→52)과 동일 패턴.
#   시도명은 분석 연속성 위해 기존 '광주'/'전남' 유지, 코드만 12xxx로 교체(광산구 12330, 순천시 12150).
#   전남광주통합특별시 시군구 코드(행안부 코드 부여내역, 2026-06-22): 전남 5시 목포12110·여수12130·
#   순천12150·나주12170·광양12190, 광주 5구 동구12210·서구12240·남구12270·북구12300·광산구12330.
REGIONS = [
    ("서울", "강남구",       ["11680"]),
    ("서울", "노원구",       ["11350"]),
    ("부산", "해운대구",     ["26350"]),
    ("대구", "수성구",       ["27260"]),
    ("인천", "연수구",       ["28185"]),
    ("광주", "광산구",       ["12330"]),   # 구 29200(광주광역시 광산구) → 통합시 12330
    ("대전", "유성구",       ["30200"]),
    ("울산", "남구",         ["31140"]),
    ("세종", "세종시",       ["36110"]),
    ("경기", "수원시영통구", ["41117"]),
    ("경기", "화성시",       ["41590", "41591", "41592", "41593"]),
    ("강원", "춘천시",       ["51110"]),
    ("충북", "청주시흥덕구", ["43113"]),
    ("충남", "천안시서북구", ["44133"]),
    ("전북", "전주시완산구", ["52111"]),
    ("전남", "순천시",       ["12150"]),   # 구 46150(전라남도 순천시) → 통합시 12150
    ("경북", "포항시북구",   ["47113"]),
    ("경남", "창원시성산구", ["48123"]),
    ("제주", "제주시",       ["50110"]),
]

# 통폐합/개편으로 시도명↔코드가 어긋나는 지역의 sigungu_used 주석(감사 추적용).
REGION_NOTES = {
    ("광주", "광산구"): "2026-07-01 광주+전남 통폐합 → 전남광주통합특별시(신 시도코드 12); 구 29200 무거래·신 12330 채택",
    ("전남", "순천시"): "2026-07-01 광주+전남 통폐합 → 전남광주통합특별시(신 시도코드 12); 구 46150 무거래·신 12150 채택",
}


def _months(n: int) -> list:
    """현재 월 포함 최근 n개월 YYYYMM 리스트(과거→현재)."""
    today = datetime.date.today()
    out = []
    y, m = today.year, today.month
    for _ in range(n):
        out.append(f"{y}{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return sorted(out)


def _fetch_page(kind: str, url: str, code: str, ym: str, page: int, key: str) -> str:
    """한 페이지 원본 XML을 반환. 캐시가 있으면 재호출 스킵, 없으면 API 호출·저장."""
    cache = RAW_DIR / f"{kind}_{code}_{ym}_p{page}.xml"
    if cache.exists():
        return cache.read_text(encoding="utf-8")
    params = {
        "LAWD_CD": code, "DEAL_YMD": ym,
        "pageNo": str(page), "numOfRows": str(PER_PAGE), "serviceKey": key,
    }
    # 게이트웨이 5xx/네트워크 오류는 일시적 → 백오프 재시도(원본 캐시 무결성 보장)
    status, text = None, ""
    for attempt in range(5):
        status, text = api_get(url, params, retries=2)
        time.sleep(CALL_GAP)
        if status == 200:
            break
        if status == -1 or 500 <= status < 600:
            time.sleep(2.0 * (attempt + 1))
            continue
        break
    if status != 200:
        raise RuntimeError(f"RTMS HTTP {status} ({kind} {code} {ym}): {text[:200]}")
    root = ET.fromstring(text)
    rc = root.findtext("./header/resultCode")
    if rc not in ("00", "000"):
        msg = root.findtext("./header/resultMsg")
        raise RuntimeError(f"RTMS 응답 오류 {rc} ({kind} {code} {ym}): {msg}")
    cache.write_text(text, encoding="utf-8")
    return text


def _fetch_month(kind: str, url: str, code: str, ym: str, key: str) -> list:
    """한 (코드,월)의 전체 <item> Element 리스트(페이지네이션 포함)."""
    text = _fetch_page(kind, url, code, ym, 1, key)
    root = ET.fromstring(text)
    total = int(root.findtext("./body/totalCount") or "0")
    items = root.findall("./body/items/item")
    fetched = len(items)
    page = 1
    while fetched < total:
        page += 1
        text = _fetch_page(kind, url, code, ym, page, key)
        root = ET.fromstring(text)
        pg = root.findall("./body/items/item")
        if not pg:
            break
        items.extend(pg)
        fetched += len(pg)
    return items


def _price_per_m2(item: ET.Element):
    """(price_per_m2, reason) — 유효하면 (float, None), 무효면 (None, 사유)."""
    amt_raw = (item.findtext("dealAmount") or "").replace(",", "").strip()
    area_raw = (item.findtext("excluUseAr") or "").strip()
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
    if not (PRICE_MIN <= ppm2 <= PRICE_MAX):
        return None, f"범위밖 {ppm2:,.0f}원/㎡"
    return ppm2, None


def _collect_kind(kind: str, url: str, months: list, key: str):
    """kind('sale'|'presale') 전체 수집. (trades_by_sido, rows_by_region, excluded)."""
    trades = {}                 # 시도 → 시군구 → [{ym, median, count}]
    rows_by_region = {}         # (시도,시군구) → 총 유효행수
    excluded = 0
    excluded_samples = []
    for sido, name, codes in REGIONS:
        by_month = {}           # ym → [ppm2, ...]
        for ym in months:
            for code in codes:
                for item in _fetch_month(kind, url, code, ym, key):
                    ppm2, reason = _price_per_m2(item)
                    if ppm2 is None:
                        excluded += 1
                        if len(excluded_samples) < 20:
                            excluded_samples.append(f"{kind} {sido}{name} {ym} {reason}")
                        continue
                    by_month.setdefault(ym, []).append(ppm2)
        series = [
            {"ym": ym, "median_price_per_m2": round(statistics.median(v)), "count": len(v)}
            for ym, v in sorted(by_month.items())
        ]
        rows = sum(p["count"] for p in series)
        rows_by_region[(sido, name)] = rows
        if series:
            trades.setdefault(sido, {})[name] = series
    if excluded_samples:
        print(f"  [{kind}] 제외 표본:")
        for s in excluded_samples:
            print(f"    - {s}")
    return trades, rows_by_region, excluded


def collect() -> dict:
    key = load_config()["service_key"]
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    sale_months = _months(SALE_MONTHS)
    presale_months = _months(PRESALE_MONTHS)

    print(f"매매 {SALE_MONTHS}개월 수집 ({sale_months[0]}~{sale_months[-1]}) …")
    trades, sale_rows, sale_excl = _collect_kind("sale", SALE_URL, sale_months, key)
    print(f"분양권 {PRESALE_MONTHS}개월 수집 ({presale_months[0]}~{presale_months[-1]}) …")
    presale, presale_rows, presale_excl = _collect_kind("presale", PRESALE_URL, presale_months, key)

    # sigungu_used + 행수 검증 로그
    sigungu_used = {}
    empty_regions = []
    for sido, name, codes in REGIONS:
        sr = sale_rows.get((sido, name), 0)
        pr = presale_rows.get((sido, name), 0)
        entry = {"codes": codes, "sale_rows": sr, "presale_rows": pr}
        if sr == 0 and pr == 0:
            entry["note"] = "API 빈 응답(전 시군구·전 기간 0) — 대안 없음"
            empty_regions.append(f"{sido} {name}")
        elif (sido, name) in REGION_NOTES:
            entry["note"] = REGION_NOTES[(sido, name)]
        elif len(codes) > 1:
            entry["note"] = "구 신설 분할 코드 병합"
        sigungu_used.setdefault(sido, {})[name] = entry

    total_sale = sum(sale_rows.values())
    total_presale = sum(presale_rows.values())

    print(f"\n매매 총 {total_sale}건 (제외 {sale_excl}) / 분양권 총 {total_presale}건 (제외 {presale_excl})")
    print("시군구별 행수:")
    for sido, name, codes in REGIONS:
        sr = sale_rows.get((sido, name), 0)
        pr = presale_rows.get((sido, name), 0)
        flag = "  ← 0!" if (sr == 0 and pr == 0) else ""
        print(f"  {sido} {name:<10} 매매 {sr:>5}  분양권 {pr:>5}{flag}")
    if empty_regions:
        print(f"빈 시군구(대안 없음): {', '.join(empty_regions)}")

    result = {
        "trades": trades,
        "presale_trades": presale,
        "sigungu_used": sigungu_used,
        "excluded": {"sale": sale_excl, "presale": presale_excl},
        "collected_at": datetime.date.today().isoformat(),
        "source": "국토교통부 RTMS 아파트 실거래가(매매·분양권)",
    }
    path = ROOT / "data" / "rtms.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=1))
    return {
        "ok": True,
        "sale_rows": total_sale, "presale_rows": total_presale,
        "excluded": sale_excl + presale_excl,
        "empty_regions": empty_regions,
        "path": str(path),
    }


if __name__ == "__main__":
    print("RTMS 실거래가 수집:")
    print(collect())
