"""국토부 건축HUB 건축인허가 기본개요 수집기 — 공동주택(아파트) 인허가 시도별 월별 집계(표본).

실행: python3 src/collect/archub.py
산출: data/archub.json
  {"permits_monthly": {"서울": [{"ym":"202001","count":N,"units":N,"area":N}...], ...},
   "sample_note": "...", "sido_meta": {...}, "endpoints_used": [...], "tables_used": [...],
   "collected_at": "...", "source": "국토교통부 건축HUB 건축인허가정보"}

── 빈 응답(HTTP 200+빈 바디)의 원인과 해결 ────────────────────────────────────
과거 프로브가 200+빈 바디를 받은 원인은 **Accept 헤더 부재**였다(2026-07-21 A/B 실증).
ArchPmsHubService(건축HUB)는 요청에 Accept 헤더가 없으면 200 응답에 바디를 비워 돌려준다.
`Accept: */*` 을 넣으면 동일 파라미터로 정상 XML(<resultCode>00</resultCode>)이 온다.
(같은 키·같은 인프라의 RTMS는 Accept 없이도 동작 → 이 서비스 고유 quirk.)
부차 조건: 백엔드가 콜드일 때 응답이 1~17초로 느리다 → timeout≥50s + 빈-바디 재시도.

── API 형태(가이드+실측) ──────────────────────────────────────────────────────
- getApBasisOulnInfo(기본개요): sigunguCd(필수)·bjdongCd(필수)·startDate/endDate(YYYYMMDD)·
  numOfRows(최대 100)·pageNo. sigunguCd 단독 질의는 실패(빈 바디) → 법정동코드 필수.
- startDate/endDate는 **crtnDay(생성일자, 대량적재일) 기준** 필터라 건축허가월과 어긋난다 →
  날짜 필터를 쓰지 않고 법정동별 전량을 받아 **archPmsDay(건축허가일)로 로컬 월 binning**.
- 강원/전북은 archub이 **신 코드**(춘천 51110·전주완산 52111)만 인식(구 42110/45111=0건).
  법정동 파일(2023)은 구 프리픽스라 last-5(동 코드)만 재사용한다.

표본: 시도별 대표 시군구 1곳 × 동(리 제외, 법정동 last-5가 '00'으로 끝나는 동 단위) 전량.
"""

import datetime
import json
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from collect.common import ROOT, SIDO, api_get, load_config  # noqa: E402

BASE = "https://apis.data.go.kr/1613000/ArchPmsHubService/getApBasisOulnInfo"
RAW_DIR = ROOT / "data" / "raw" / "archub"
LDONG_FILE = RAW_DIR / "ldong_full.txt"
LDONG_URL = ("https://gist.githubusercontent.com/FinanceData/"
             "4b0a6e1818cea9e77496e57b84bb4565/raw/b682e526c7e9ebd1c30f688b789aa018f396e1c9/"
             "%EB%B2%95%EC%A0%95%EB%8F%99%EC%BD%94%EB%93%9C%EC%A0%84%EC%B2%B4%EC%9E%90%EB%A3%8C.txt")

HDR = {"Accept": "*/*"}          # ★ 빈-응답 해결 헤더
PER_PAGE = 100                    # 가이드·실측: 최대 100
CALL_GAP = 0.3                    # 호출 간 대기(초)
TIMEOUT = 55
EMPTY_RETRIES = 5                 # 200+빈 바디 재시도 횟수
START_YM = "201501"              # 월 집계 시작(최근 ~10.5년)
_CUR_YM = datetime.date.today().strftime("%Y%m")  # 상한(미래·오류연도 배제)

# 호출량 절제(무편향): 동별 페이지 상한.
#  아파트는 인허가의 소수%라 '표본 밀도' 스크리닝은 아파트多 주거동을 잘못 탈락시킨다(실측: 유성 undercount).
#  대신 **초대형 상업핵동(>4000건)만** MAX_PAGES 상한을 둔다 — 주거동(<4000건)은 전수라 아파트 누락 없음.
#  대형 상업동(역삼 9227 등)은 아파트가 희소하므로 상한 절단의 영향이 작다.
MAX_PAGES = 40                   # 동당 최대 40페이지(=4000건). 초과분만 절단(capped 기록).

# 공동주택(아파트) 판정: 주용도명 키워드(기본개요 레벨은 대부분 "공동주택"으로 통칭).
APT_KEYWORDS = ("아파트", "공동주택", "연립주택", "다세대주택")
# 신규 공급만 계상: 발코니구조변경·용도변경·대수선 등은 기존 단지에 붙어 전체 세대수를 중복
#  계상(강남 발코니변경 501건=308,912세대 오염 실측) → 건축구분이 신축/증축인 건만 인정.
NEW_SUPPLY_GB = ("신축", "증축")

# (시도, 대표 시군구명, archub sigunguCd, 법정동파일 prefix)
REGIONS = [
    ("서울", "강남구",       "11680", "11680"),
    ("부산", "해운대구",     "26350", "26350"),
    ("대구", "수성구",       "27260", "27260"),
    ("인천", "연수구",       "28185", "28185"),
    ("광주", "서구",         "29140", "29140"),
    ("대전", "유성구",       "30200", "30200"),
    ("울산", "남구",         "31140", "31140"),
    ("세종", "세종시",       "36110", "36110"),
    ("경기", "수원시영통구", "41117", "41117"),
    ("강원", "춘천시",       "51110", "42110"),   # archub=신51, 파일=구42
    ("충북", "청주시흥덕구", "43113", "43113"),
    ("충남", "천안시서북구", "44133", "44133"),
    ("전북", "전주시완산구", "52111", "45111"),   # archub=신52, 파일=구45
    ("전남", "순천시",       "46150", "46150"),
    ("경북", "포항시북구",   "47113", "47113"),
    ("경남", "창원시성산구", "48123", "48123"),
    ("제주", "제주시",       "50110", "50110"),
]


def _ensure_ldong() -> list:
    """법정동코드 전체자료(캐시)를 반환. 없으면 1회 다운로드."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    if not LDONG_FILE.exists():
        req = urllib.request.Request(LDONG_URL, headers={"User-Agent": "dev-research/0.1"})
        with urllib.request.urlopen(req, timeout=60) as r:
            LDONG_FILE.write_bytes(r.read())
    return LDONG_FILE.read_text(encoding="utf-8").splitlines()


def _dong_codes(ldong_lines: list, prefix: str) -> list:
    """prefix(시군구 5자리)의 활성 '동 단위'(last-5가 '00'으로 끝, 리 제외) [(bjdong5, name)]."""
    out = []
    for ln in ldong_lines[1:]:
        parts = ln.split("\t")
        if len(parts) < 3:
            continue
        code, name, status = parts[0], parts[1], parts[2]
        if len(code) != 10 or status.strip() != "존재":
            continue
        if not code.startswith(prefix):
            continue
        bj = code[5:]
        if bj == "00000" or not bj.endswith("00"):
            continue
        out.append((bj, name))
    return out


def _fetch_page(sgg: str, bj: str, page: int, key: str) -> str:
    """한 페이지 원본 XML. 캐시 있으면 스킵. 200+빈 바디는 백엔드 콜드 → 재시도.

    반환 XML은 well-formed(resultCode 존재) 보장. resultCode≠00/000 이면 예외.
    """
    cache = RAW_DIR / f"{sgg}_{bj}_p{page}.xml"
    if cache.exists():
        return cache.read_text(encoding="utf-8")
    params = {"sigunguCd": sgg, "bjdongCd": bj,
              "numOfRows": str(PER_PAGE), "pageNo": str(page), "serviceKey": key}
    text = None
    for attempt in range(EMPTY_RETRIES + 1):
        status, text = api_get(BASE, params, timeout=TIMEOUT, retries=1, headers=HDR)
        time.sleep(CALL_GAP)
        # 빈 바디/미완성 = 콜드백엔드 glitch → 재시도(원인: Accept가 아니라 지연/과부하)
        if status == 200 and text and "<resultCode>" in text:
            break
        time.sleep(2.0 * (attempt + 1))
    if not (text and "<resultCode>" in text):
        raise RuntimeError(f"archub 빈/이상 응답 {sgg}/{bj} p{page}: status={status} len={len(text or '')}")
    root = ET.fromstring(text)
    rc = root.findtext("./header/resultCode")
    if rc not in ("00", "000"):
        raise RuntimeError(f"archub 응답오류 {rc} {sgg}/{bj} p{page}: {root.findtext('./header/resultMsg')}")
    cache.write_text(text, encoding="utf-8")
    return text


def _fetch_dong(sgg: str, bj: str, key: str):
    """한 (시군구,동)의 <item> 리스트와 절단 여부. 반환 (items, capped).

    capped=True 이면 초대형 동(>MAX_PAGES 페이지)에서 상한만큼만 받은 경우.
    """
    text = _fetch_page(sgg, bj, 1, key)
    root = ET.fromstring(text)
    total = int(root.findtext("./body/totalCount") or "0")
    items = root.findall("./body/items/item")
    page = 1
    while len(items) < total:
        if page >= MAX_PAGES:
            return items, True
        page += 1
        text = _fetch_page(sgg, bj, page, key)
        pg = ET.fromstring(text).findall("./body/items/item")
        if not pg:
            break
        items.extend(pg)
    return items, False


def _hhld(it) -> int:
    try:
        return int(float(it.findtext("hhldCnt") or "0"))
    except ValueError:
        return 0


def _is_apt(purps: str, hhld: int) -> bool:
    """공동주택 계열 판정: 주용도명 키워드 or (주용도 공란 & 세대≥30, 주상복합 보정)."""
    if any(k in (purps or "") for k in APT_KEYWORDS):
        return True
    return not purps and hhld >= 30


def _is_new_supply(gb: str) -> bool:
    """신규 공급(신축·증축)만 인정 — 발코니변경/용도변경/대수선 등 중복계상 제외."""
    return any(k in (gb or "") for k in NEW_SUPPLY_GB)


def collect() -> dict:
    key = load_config()["service_key"]
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    ldong = _ensure_ldong()

    permits_monthly = {}
    sido_meta = {}
    for sido, name, sgg, prefix in REGIONS:
        dongs = _dong_codes(ldong, prefix)
        by_month = defaultdict(lambda: {"count": 0, "units": 0, "area": 0.0})
        scanned = apt_permits = 0
        dong_ok = capped = 0
        for bj, dname in dongs:
            items, was_capped = _fetch_dong(sgg, bj, key)
            if items:
                dong_ok += 1
            if was_capped:
                capped += 1
            for it in items:
                scanned += 1
                purps = (it.findtext("mainPurpsCdNm") or "").strip()
                hhld = _hhld(it)
                if not _is_apt(purps, hhld):
                    continue
                if not _is_new_supply((it.findtext("archGbCdNm") or "").strip()):
                    continue
                pms = (it.findtext("archPmsDay") or "").strip()
                if len(pms) < 6 or not pms[:6].isdigit():
                    continue
                ym = pms[:6]
                if ym < START_YM or ym > _CUR_YM:   # 미래·오류연도(예: 3xxxxx) 배제
                    continue
                try:
                    area = float(it.findtext("totArea") or "0")
                except ValueError:
                    area = 0.0
                apt_permits += 1
                b = by_month[ym]
                b["count"] += 1
                b["units"] += hhld
                b["area"] += area
        series = [{"ym": ym, "count": v["count"], "units": v["units"],
                   "area": round(v["area"], 1)}
                  for ym, v in sorted(by_month.items())]
        permits_monthly[sido] = series
        sido_meta[sido] = {"sigungu": name, "sigunguCd": sgg,
                           "dong_total": len(dongs), "dong_with_data": dong_ok,
                           "dong_capped": capped,
                           "permits_scanned": scanned, "apt_permits": apt_permits,
                           "months": len(series)}
        print(f"  {sido} {name}({sgg}): 동 {dong_ok}/{len(dongs)}(절단 {capped}), "
              f"전체 {scanned} → 공동주택 {apt_permits}건, {len(series)}개월", flush=True)

    result = {
        "permits_monthly": permits_monthly,
        "sido_meta": sido_meta,
        "sample_note": ("시도별 대표 시군구 1곳의 '동 단위 법정동'(리 제외) 표본. "
                        "공동주택 = 주용도명(아파트/공동주택/연립·다세대주택), 건축구분=신축·증축만(신규 공급) — "
                        "발코니구조변경·용도변경·대수선 등 기존단지 세대수 중복계상 제외. "
                        "월(ym)은 건축허가일(archPmsDay) 기준. "
                        f"호출절제(무편향): 주거동(<4000건)은 전수라 누락 없음; 초대형 상업핵동(>4000건)만 "
                        f"{MAX_PAGES}페이지 상한(dong_capped 기록, 아파트 희소해 영향 작음). "
                        "시도 전체가 아닌 대표 시군구 pulse — 절대량이 아닌 추세·계절성 해석용."),
        "window": f"{START_YM}~",
        "endpoints_used": [BASE],
        "tables_used": ["getApBasisOulnInfo (건축인허가 기본개요)"],
        "collected_at": datetime.date.today().isoformat(),
        "source": "국토교통부 건축HUB 건축인허가정보(기본개요)",
    }
    path = ROOT / "data" / "archub.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=1))

    # ── 검증 assert ──────────────────────────────────────────────
    covered = [s for s in SIDO.values() if permits_monthly.get(s)]
    empty = [s for s in SIDO.values() if not permits_monthly.get(s)]
    assert len(covered) >= 14, f"시도 커버 부족: {len(covered)}/17 (빈={empty})"
    total_apt = 0
    for sido, series in permits_monthly.items():
        for row in series:
            assert 0 <= row["units"] <= 50000, f"{sido} {row['ym']} 세대수 이상: {row['units']}"
            assert row["count"] >= 1, f"{sido} {row['ym']} count<1"
            total_apt += row["count"]
    assert total_apt >= 100, f"공동주택 인허가 총건수 과소: {total_apt}"

    return {"ok": True, "covered": covered, "empty_sido": empty,
            "total_apt_permits": total_apt, "path": str(path)}


if __name__ == "__main__":
    print("건축HUB 건축인허가(공동주택) 수집:")
    print(collect())
