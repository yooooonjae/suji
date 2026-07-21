"""시장 분석 빌드 — 수집 데이터(data/*.json)를 통합해 사이트 임베드용
out/market.json 을 생성한다.

출력 계약(키는 site/js/app.js 가 소비 — 정확 일치 필수):
  sale_index, jeonse_index        : rone 그대로(전국 포함 18개 시도)
  unsold, unsold_completed        : kosis 그대로
  base_rate, mortgage_rate, corp_loan_rate : ecos, 최근 120개월 절단
  presale_indexed                 : HUG 전국(시도 산술평균) ㎡당가 지수(시작월=100)
  cci_indexed                     : KOSIS 건설공사비지수, presale_indexed 와 같은
                                    시작월=100 재지수화(공통 월범위 교집합)
  phase_points                    : 시도별 x=미분양 YoY%, y=매매지수 YoY%(전국 포함)
  sido_summary                    : 시도별 참고 지표(사이트 보조)
  meta                            : 소스별 최신월·출처·결측 기록·빌드일

단위·규약: ym 은 "YYYYMM" 문자열, 지수는 시작월=100 기준, YoY 는 % 단위.
"""

import datetime
import json
import statistics
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
OUT = ROOT / "out"

# 시도 표준 순서(전국 선두). app.js SIDO_ORDER 와 동일.
SIDO_ORDER = ["전국", "서울", "경기", "인천", "부산", "대구", "광주", "대전", "울산",
              "세종", "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주"]

RATE_MONTHS = 120  # 금리 계열 절단 길이(최근 120개월)


# --------------------------------------------------------------------------- #
# 로드·유틸
# --------------------------------------------------------------------------- #
def _load(name: str) -> dict:
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def _ym_minus(ym: str, months: int) -> str:
    """'YYYYMM' 에서 months 개월 전 'YYYYMM' 을 반환."""
    y, m = int(ym[:4]), int(ym[4:6])
    idx = y * 12 + (m - 1) - months
    return f"{idx // 12:04d}{idx % 12 + 1:02d}"


def _last_ym(series: list):
    return series[-1]["ym"] if series else None


def _yoy_pct(series: list):
    """최근월 전년동월대비 변화율(%). 12개월 전 값 결측이면 None, 0이면 0(나눗셈 가드)."""
    if not series:
        return None
    d = {p["ym"]: p["value"] for p in series}
    last = series[-1]["ym"]
    prev = d.get(_ym_minus(last, 12))
    if prev is None:
        return None
    if prev == 0:
        return 0.0  # 미분양 0 → 0 나눗셈 가드
    return (d[last] - prev) / prev * 100.0


# --------------------------------------------------------------------------- #
# HUG 전국 산술평균 + 분양가·공사비 지수화
# --------------------------------------------------------------------------- #
def hug_national(hug: dict) -> list:
    """HUG 시도별 ㎡당 분양가를 월별 산술평균해 전국 대표 계열 생성.

    시도 가중치(공급물량) 미보유 → 산술평균. 월마다 데이터가 있는 시도만 평균한다.
    """
    acc = defaultdict(list)
    for series in hug["presale_price"].values():
        for p in series:
            acc[p["ym"]].append(p["value"])
    return [{"ym": ym, "value": statistics.mean(acc[ym])} for ym in sorted(acc)]


def indexed_pair(hug_nat: list, cci: list):
    """분양가 전국계열과 CCI 를 공통 월범위(교집합)로 맞춰 시작월=100 재지수화.

    반환: (presale_indexed, cci_indexed). 두 계열은 동일 월 목록·동일 길이이며
    각각 공통 시작월에서 값 100 이다(app.js 가 index 기준으로 오버레이).
    """
    hd = {p["ym"]: p["value"] for p in hug_nat}
    cd = {p["ym"]: p["value"] for p in cci}
    common = sorted(set(hd) & set(cd))
    if not common:
        return [], []
    start = common[0]
    bh, bc = hd[start], cd[start]
    presale = [{"ym": ym, "value": hd[ym] / bh * 100.0} for ym in common]
    cci_idx = [{"ym": ym, "value": cd[ym] / bc * 100.0} for ym in common]
    return presale, cci_idx


# --------------------------------------------------------------------------- #
# 국면 맵(미분양 YoY vs 매매지수 YoY)
# --------------------------------------------------------------------------- #
def phase_points(sale_index: dict, unsold: dict) -> list:
    """시도별 (x=미분양 YoY%, y=매매지수 YoY%) 좌표. 전국 포함.

    미분양·매매 양쪽 계열이 있고 YoY 산출 가능한 시도만 포함한다.
    """
    pts = []
    order = [s for s in SIDO_ORDER if s in sale_index] + \
            [s for s in sale_index if s not in SIDO_ORDER]
    for sido in order:
        if sido not in unsold:
            continue
        x = _yoy_pct(unsold[sido])
        y = _yoy_pct(sale_index[sido])
        if x is None or y is None:
            continue
        pts.append({"name": sido, "x": x, "y": y})
    return pts


# --------------------------------------------------------------------------- #
# RTMS 시도 대표 실거래 중위가(㎡당) — 시군구 최근월 median 을 거래건수 가중평균
# --------------------------------------------------------------------------- #
def _rtms_sido_last(sido_dict: dict):
    num = 0.0
    wt = 0.0
    for series in sido_dict.values():
        if not series:
            continue
        last = series[-1]
        v = last.get("median_price_per_m2")
        c = last.get("count", 0) or 0
        if v is None or c <= 0:
            continue
        num += v * c
        wt += c
    return num / wt if wt > 0 else None


def _rtms_national_last(trades: dict):
    """전국 대표: 모든 시군구 최근월 median 을 거래건수 가중평균."""
    num = 0.0
    wt = 0.0
    for sido_dict in trades.values():
        for series in sido_dict.values():
            if not series:
                continue
            last = series[-1]
            v = last.get("median_price_per_m2")
            c = last.get("count", 0) or 0
            if v is None or c <= 0:
                continue
            num += v * c
            wt += c
    return num / wt if wt > 0 else None


def _rtms_last_ym(trades: dict):
    best = None
    for sido_dict in trades.values():
        for series in sido_dict.values():
            if series:
                ym = series[-1]["ym"]
                if best is None or ym > best:
                    best = ym
    return best


# --------------------------------------------------------------------------- #
# 시도 요약(참고 지표)
# --------------------------------------------------------------------------- #
def sido_summary(rone: dict, kosis: dict, hug: dict, rtms: dict, hug_nat: list) -> dict:
    sale = rone["sale_index"]
    unsold = kosis["unsold"]
    hug_ps = hug["presale_price"]
    trades = rtms["trades"]

    summary = {}
    order = [s for s in SIDO_ORDER if s in sale] + \
            [s for s in sale if s not in SIDO_ORDER]
    for sido in order:
        # 분양가(㎡당) 최근월 — 전국은 산술평균 계열의 마지막값
        if sido == "전국":
            presale_last = hug_nat[-1]["value"] if hug_nat else None
        elif sido in hug_ps and hug_ps[sido]:
            presale_last = hug_ps[sido][-1]["value"]
        else:
            presale_last = None
        # 실거래 중위가(㎡당) 최근월 — 전국은 전 시군구 가중평균, 결측 시도는 null 허용
        if sido == "전국":
            trade_last = _rtms_national_last(trades)
        elif sido in trades:
            trade_last = _rtms_sido_last(trades[sido])
        else:
            trade_last = None  # 광주·전남 등 rtms 결측 → null (meta 에 기록)

        summary[sido] = {
            "sale_yoy": _yoy_pct(sale[sido]),
            "unsold_last": (unsold[sido][-1]["value"] if sido in unsold and unsold[sido] else None),
            "presale_m2_last": presale_last,
            "trade_median_last": trade_last,
        }
    return summary


# --------------------------------------------------------------------------- #
# 빌드
# --------------------------------------------------------------------------- #
def build() -> dict:
    rone = _load("rone.json")
    kosis = _load("kosis.json")
    ecos = _load("ecos.json")
    hug = _load("hug.json")
    rtms = _load("rtms.json")

    hug_nat = hug_national(hug)
    presale_indexed, cci_indexed = indexed_pair(hug_nat, kosis["cci"])

    # 금리: 최근 120개월 절단
    def tail(series):
        return series[-RATE_MONTHS:]

    sale = rone["sale_index"]
    unsold = kosis["unsold"]

    # rtms 결측 시도(매매지수엔 있으나 rtms trades 엔 없음)
    missing_rtms = [s for s in sale if s != "전국" and s not in rtms["trades"]]

    market = {
        "sale_index": sale,
        "jeonse_index": rone["jeonse_index"],
        "unsold": unsold,
        "unsold_completed": kosis["unsold_completed"],
        "base_rate": tail(ecos["base_rate"]),
        "mortgage_rate": tail(ecos["mortgage_rate"]),
        "corp_loan_rate": tail(ecos["corp_loan_rate"]),
        "presale_indexed": presale_indexed,
        "cci_indexed": cci_indexed,
        "phase_points": phase_points(sale, unsold),
        "sido_summary": sido_summary(rone, kosis, hug, rtms, hug_nat),
        "meta": {
            "asof": {
                "rone_sale": _last_ym(sale.get("전국") or next(iter(sale.values()))),
                "rone_jeonse": _last_ym(rone["jeonse_index"].get("전국")
                                        or next(iter(rone["jeonse_index"].values()))),
                "kosis_unsold": _last_ym(unsold.get("전국") or next(iter(unsold.values()))),
                "kosis_cci": _last_ym(kosis["cci"]),
                "ecos_base_rate": _last_ym(ecos["base_rate"]),
                "hug_presale": _last_ym(hug_nat),
                "rtms": _rtms_last_ym(rtms["trades"]),
            },
            "sources": [rone.get("source"), kosis.get("source"), ecos.get("source"),
                        hug.get("source"), rtms.get("source")],
            "missing_rtms_sido": missing_rtms,
            "index_base_ym": (presale_indexed[0]["ym"] if presale_indexed else None),
            "built_at": datetime.date.today().isoformat(),
        },
    }
    return market


def main() -> Path:
    market = build()
    OUT.mkdir(exist_ok=True)
    path = OUT / "market.json"
    path.write_text(json.dumps(market, ensure_ascii=False, indent=2), encoding="utf-8")
    m = market["meta"]
    print(f"market.json 생성: {path}")
    print(f"  시도 {len(market['sale_index'])}개 · phase_points {len(market['phase_points'])}개 · "
          f"분양가지수 {len(market['presale_indexed'])}개월(시작 {m['index_base_ym']})")
    print(f"  asof: {m['asof']} · rtms 결측 {m['missing_rtms_sido']}")
    return path


if __name__ == "__main__":
    main()
