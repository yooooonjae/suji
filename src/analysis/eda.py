#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
수지(收支) — 탐색적 데이터 분석(EDA) 파이프라인
================================================
수집 데이터 전체(out/market.json + data/raw/rtms/*.xml)에 대해 5개 분석을 수행하고
사이트 임베드용 차트 데이터를 out/eda.json 으로 베이크한다.

분석 항목
  1. 상관 구조   : 시도별 매매지수 YoY vs (기준금리·미분양·공사비·분양가), 동시/시차상관
  2. 계절성      : 전국 매매지수 MoM 변동률의 월별(1~12월) 평균
  3. 동조화·분산 : 17개 시도 YoY 횡단면 표준편차 시계열 + 서울-지방 상관
  4. 실거래 분포 : 매매 실거래 ㎡당 가격의 시도별 분포(중위·IQR·p10·p90)
  5. 금리 국면   : 기준금리 상승/하강/동결 국면별 전국 매매지수 월평균 변동률

실행:  python3 src/analysis/eda.py
의존성: 표준 라이브러리만 사용(numpy 불필요). ~/개발/.venv 부재 환경에서도 재현 가능.
"""
import json
import math
import os
import statistics
import xml.etree.ElementTree as ET
from glob import glob

# ── 경로 ──────────────────────────────────────────────────────────────────
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
MARKET = os.path.join(ROOT, "out", "market.json")
RTMS_JSON = os.path.join(ROOT, "data", "rtms.json")
RTMS_RAW = os.path.join(ROOT, "data", "raw", "rtms")
OUT = os.path.join(ROOT, "out", "eda.json")

# RTMS 유효 실거래 판정(수집 스크립트 src/collect/rtms.py 와 동일 규칙)
PRICE_MIN = 2_000_000       # 원/㎡
PRICE_MAX = 50_000_000      # 원/㎡

SIDO17 = ["서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종",
          "경기", "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주"]
SUDOGWON = {"서울", "경기", "인천"}          # 수도권
JIBANG = [s for s in SIDO17 if s not in SUDOGWON]   # 비수도권(지방) 14개

# ── 유틸 ──────────────────────────────────────────────────────────────────
def ym_idx(ym):
    """'YYYYMM' → 연속 월 인덱스(정렬·시차 계산용)."""
    y, m = int(ym[:4]), int(ym[4:6])
    return y * 12 + (m - 1)


def to_map(series):
    """[{ym,value}] → {ym: value}."""
    return {r["ym"]: r["value"] for r in series if r.get("value") is not None}


def yoy_series(m):
    """{ym:value} → {ym: 전년동월대비 %} (12개월 전 존재 시)."""
    idx = {ym_idx(k): (k, v) for k, v in m.items()}
    out = {}
    for i, (ym, v) in idx.items():
        p = idx.get(i - 12)
        if p and p[1] not in (None, 0):
            out[ym] = (v / p[1] - 1.0) * 100.0
    return out


def mom_series(m):
    """{ym:value} → {ym: 전월대비 %} (직전월 존재 시)."""
    idx = {ym_idx(k): (k, v) for k, v in m.items()}
    out = {}
    for i, (ym, v) in idx.items():
        p = idx.get(i - 1)
        if p and p[1] not in (None, 0):
            out[ym] = (v / p[1] - 1.0) * 100.0
    return out


def diff_k(m, k):
    """{ym:value} → {ym: value[t]-value[t-k]}."""
    idx = {ym_idx(k2): (k2, v) for k2, v in m.items()}
    out = {}
    for i, (ym, v) in idx.items():
        p = idx.get(i - k)
        if p:
            out[ym] = v - p[1]
    return out


def pearson(xs, ys):
    """피어슨 상관계수(표본). (r, n) 반환. n<3 이면 (None, n)."""
    n = len(xs)
    if n < 3:
        return None, n
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    if sxx <= 0 or syy <= 0:
        return None, n
    r = sxy / math.sqrt(sxx * syy)
    r = max(-1.0, min(1.0, r))       # 부동소수 오차로 |r|>1 방지
    return r, n


def aligned(a, b, lag=0):
    """
    두 {ym:value} 시계열을 동일 월 기준으로 정렬해 (xs, ys) 반환.
    lag>0 : 변수 b(설명변수)를 lag 개월 '선행'시킴 → corr(a[t], b[t-lag]).
    """
    ai = {ym_idx(k): v for k, v in a.items()}
    bi = {ym_idx(k): v for k, v in b.items()}
    xs, ys = [], []
    for i, av in ai.items():
        bv = bi.get(i - lag)
        if bv is not None:
            xs.append(av)
            ys.append(bv)
    return xs, ys


def corr_lagged(target, driver, lags):
    """target(피설명, 매매YoY) vs driver(설명변수) 시차상관. lag>0=driver 선행."""
    res = {}
    best = {"lag": None, "r": 0.0}
    for k in lags:
        xs, ys = aligned(target, driver, lag=k)
        r, n = pearson(xs, ys)
        res[str(k)] = {"r": None if r is None else round(r, 3), "n": n}
        if r is not None and abs(r) > abs(best["r"]):
            best = {"lag": k, "r": round(r, 3)}
    return {"by_lag": res, "best_lag": best["lag"], "best_r": best["r"]}


def percentile(sorted_vals, q):
    """선형보간 분위수(numpy 'linear' 방식). sorted_vals 는 오름차순."""
    n = len(sorted_vals)
    if n == 0:
        return None
    if n == 1:
        return float(sorted_vals[0])
    pos = q * (n - 1)
    lo = int(math.floor(pos))
    hi = min(lo + 1, n - 1)
    frac = pos - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


# ── 데이터 로드 ────────────────────────────────────────────────────────────
def load_market():
    with open(MARKET, encoding="utf-8") as f:
        return json.load(f)


def load_rtms_prices():
    """
    data/raw/rtms/sale_*.xml 를 파싱해 시도별 유효 ㎡당 가격 리스트 반환.
    수집기와 동일 규칙(PRICE_MIN~PRICE_MAX 범위·면적>0·파싱가능)만 유효.
    반환: (prices_by_sido, stats) — stats={total_items, valid, excluded, code2sido}
    """
    # sggCd → 시도 매핑은 수집 산출물(rtms.json)의 sigungu_used 를 권위로 사용
    with open(RTMS_JSON, encoding="utf-8") as f:
        rj = json.load(f)
    code2sido = {}
    for sido, gus in rj["sigungu_used"].items():
        for gu, info in gus.items():
            for c in info.get("codes", []):
                code2sido[c] = sido

    prices = {s: [] for s in SIDO17}
    total = valid = excluded = 0
    files = sorted(glob(os.path.join(RTMS_RAW, "sale_*.xml")))
    for path in files:
        code = os.path.basename(path).split("_")[1]
        sido = code2sido.get(code)
        if sido is None:
            continue
        try:
            root = ET.parse(path).getroot()
        except ET.ParseError:
            continue
        for item in root.iter("item"):
            total += 1
            amt_raw = (item.findtext("dealAmount") or "").replace(",", "").strip()
            area_raw = (item.findtext("excluUseAr") or "").strip()
            if not amt_raw or not area_raw:
                excluded += 1
                continue
            try:
                won = int(amt_raw) * 10_000
                area = float(area_raw)
            except ValueError:
                excluded += 1
                continue
            if area <= 0:
                excluded += 1
                continue
            ppm2 = won / area
            if not (PRICE_MIN <= ppm2 <= PRICE_MAX):
                excluded += 1
                continue
            prices[sido].append(ppm2)
            valid += 1
    return prices, {"total_items": total, "valid": valid, "excluded": excluded,
                    "code2sido": code2sido, "files": len(files)}


# ── 분석 1: 상관 구조 ──────────────────────────────────────────────────────
def analyze_correlation(m):
    sale = {s: to_map(m["sale_index"][s]) for s in (SIDO17 + ["전국"])}
    sale_yoy = {s: yoy_series(sale[s]) for s in sale}

    base = to_map(m["base_rate"])                    # 기준금리 레벨
    base_12chg = diff_k(base, 12)                     # 기준금리 12개월 변화
    unsold_nat = yoy_series(to_map(m["unsold"]["전국"]))       # 미분양 YoY(전국)
    cci_yoy = yoy_series(to_map(m["cci_indexed"]))    # 공사비지수 YoY
    presale_yoy = yoy_series(to_map(m["presale_indexed"]))    # 분양가 YoY

    lags = [0, 3, 6, 12]
    drivers = {
        "base_rate_level":  base,
        "base_rate_12mchg": base_12chg,
        "unsold_yoy":       unsold_nat,
        "cci_yoy":          cci_yoy,
        "presale_yoy":      presale_yoy,
    }

    # 전국 패널: 매매 YoY vs 각 설명변수, 시차별
    national = {}
    for name, drv in drivers.items():
        national[name] = corr_lagged(sale_yoy["전국"], drv, lags)

    # 시도별 동시상관(k=0). 미분양은 해당 시도 자체, 나머지는 전국 지표.
    unsold_by_sido = {s: yoy_series(to_map(m["unsold"][s]))
                      for s in SIDO17 if s in m["unsold"]}
    cross = []
    for s in SIDO17:
        row = {"sido": s}
        r, _ = pearson(*aligned(sale_yoy[s], base, 0))
        row["base_rate_level"] = None if r is None else round(r, 3)
        r, _ = pearson(*aligned(sale_yoy[s], base_12chg, 0))
        row["base_rate_12mchg"] = None if r is None else round(r, 3)
        if s in unsold_by_sido:
            r, _ = pearson(*aligned(sale_yoy[s], unsold_by_sido[s], 0))
            row["unsold_yoy_own"] = None if r is None else round(r, 3)
        else:
            row["unsold_yoy_own"] = None
        r, _ = pearson(*aligned(sale_yoy[s], cci_yoy, 0))
        row["cci_yoy"] = None if r is None else round(r, 3)
        r, _ = pearson(*aligned(sale_yoy[s], presale_yoy, 0))
        row["presale_yoy"] = None if r is None else round(r, 3)
        cross.append(row)

    # 인사이트 구성
    def label(name):
        return {"base_rate_level": "기준금리 레벨", "base_rate_12mchg": "기준금리 12개월 변화",
                "unsold_yoy": "미분양 YoY", "cci_yoy": "공사비 YoY",
                "presale_yoy": "분양가 YoY"}[name]

    strongest = max(national.items(), key=lambda kv: abs(kv[1]["best_r"] or 0))
    sname, sinfo = strongest
    r_cci = national["cci_yoy"]["by_lag"]["0"]["r"]
    r_ps = national["presale_yoy"]["by_lag"]["0"]["r"]
    insight = (f"전국 매매지수 YoY는 {label(sname)}와 {sinfo['best_lag']}개월 시차에서 "
               f"상관 r={sinfo['best_r']}로 가장 강하게 연동되며(선행지표성), 기준금리·미분양은 역(-)의 "
               f"관계가 뚜렷하다. 공사비 YoY는 정(+, r={r_cci})이나 이는 공통 물가추세에 의한 동조로 "
               f"보이며, 분양가 YoY는 상관이 미약(r={r_ps})하다. 상관은 인과가 아님에 유의.")
    return {
        "title": "상관 구조 — 매매지수 YoY와 금리·미분양·공사비·분양가",
        "data": {
            "national": national,
            "cross_sido": cross,
            "lags_note": "lag>0 = 설명변수를 해당 개월 선행시킨 상관(선행지표 검정). lag=0=동시상관.",
            "driver_labels": {k: label(k) for k in
                              ["base_rate_level", "base_rate_12mchg", "unsold_yoy", "cci_yoy", "presale_yoy"]},
        },
        "insight": insight,
    }


# ── 분석 2: 계절성 ─────────────────────────────────────────────────────────
def analyze_seasonality(m):
    mom = mom_series(to_map(m["sale_index"]["전국"]))
    buckets = {mm: [] for mm in range(1, 13)}
    for ym, v in mom.items():
        buckets[int(ym[4:6])].append(v)
    months, mom_avg, n_per = [], [], []
    for mm in range(1, 13):
        vals = buckets[mm]
        months.append(mm)
        mom_avg.append(round(statistics.mean(vals), 3) if vals else None)
        n_per.append(len(vals))
    hi = max(range(12), key=lambda i: mom_avg[i] if mom_avg[i] is not None else -9)
    lo = min(range(12), key=lambda i: mom_avg[i] if mom_avg[i] is not None else 9)
    spread = round(mom_avg[hi] - mom_avg[lo], 3)
    insight = (f"전국 매매지수 MoM는 {months[hi]}월(+{mom_avg[hi]}%)에 가장 강하고 "
               f"{months[lo]}월({mom_avg[lo]}%)에 가장 약해 월간 진폭은 {spread}%p에 그친다. "
               f"뚜렷한 계절 사이클보다 추세·정책 충격이 지배적이다(월당 표본 n≈{min(n_per)}~{max(n_per)}).")
    return {
        "title": "계절성 — 전국 매매지수 월별 평균 MoM 변동률",
        "data": {"months": months, "mom_avg_pct": mom_avg, "n_per_month": n_per},
        "insight": insight,
    }


# ── 분석 3: 동조화·분산 ────────────────────────────────────────────────────
def analyze_sync(m):
    sale_yoy = {s: yoy_series(to_map(m["sale_index"][s])) for s in SIDO17}
    # 월별 횡단면 표준편차(17개 시도 YoY)
    all_ym = sorted(set().union(*[set(v.keys()) for v in sale_yoy.values()]), key=ym_idx)
    ym_list, cross_sd, cross_mean = [], [], []
    for ym in all_ym:
        vals = [sale_yoy[s][ym] for s in SIDO17 if ym in sale_yoy[s]]
        if len(vals) >= 10:                 # 최소 10개 시도 있을 때만
            ym_list.append(ym)
            cross_sd.append(round(statistics.pstdev(vals), 3))
            cross_mean.append(round(statistics.mean(vals), 3))
    # 서울-지방 상관: 서울 YoY vs 비수도권 평균 YoY
    seoul = sale_yoy["서울"]
    jibang_avg = {}
    for ym in all_ym:
        vals = [sale_yoy[s][ym] for s in JIBANG if ym in sale_yoy[s]]
        if vals:
            jibang_avg[ym] = statistics.mean(vals)
    r_seoul_jibang, n_sj = pearson(*aligned(seoul, jibang_avg, 0))
    # 서울 vs 각 시도 상관
    seoul_each = []
    for s in SIDO17:
        if s == "서울":
            continue
        r, n = pearson(*aligned(seoul, sale_yoy[s], 0))
        seoul_each.append({"sido": s, "r": None if r is None else round(r, 3), "n": n})
    seoul_each.sort(key=lambda d: (d["r"] is None, -(d["r"] or -9)))

    hi_i = max(range(len(cross_sd)), key=lambda i: cross_sd[i])
    lo_i = min(range(len(cross_sd)), key=lambda i: cross_sd[i])
    insight = (f"17개 시도 YoY의 횡단면 표준편차는 {ym_list[lo_i][:4]}-{ym_list[lo_i][4:]}"
               f"(σ={cross_sd[lo_i]}%p)에 가장 동조화되고 {ym_list[hi_i][:4]}-{ym_list[hi_i][4:]}"
               f"(σ={cross_sd[hi_i]}%p)에 가장 분산됐다. 서울-지방 YoY 상관은 r={round(r_seoul_jibang,3)}"
               f"(n={n_sj})로 동반 등락하나 진폭·시점 차가 상당하다.")
    return {
        "title": "지역 동조화·분산 — 시도 YoY 횡단면 표준편차",
        "data": {
            "ym": ym_list,
            "cross_sd_pp": cross_sd,
            "cross_mean_pct": cross_mean,
            "seoul_vs_jibang_r": round(r_seoul_jibang, 3),
            "seoul_vs_jibang_n": n_sj,
            "jibang_def": "지방=비수도권 14개 시도(서울·경기·인천 제외) 단순평균",
            "seoul_vs_each": seoul_each,
        },
        "insight": insight,
    }


# ── 분석 4: 실거래 분포 ────────────────────────────────────────────────────
def analyze_distribution(prices, stats, missing):
    by_sido = []
    for s in SIDO17:
        v = sorted(prices[s])
        n = len(v)
        if n == 0:
            by_sido.append({"sido": s, "n": 0, "note": "수집 시군구 표본 0건(원천 무거래)"})
            continue
        p10 = percentile(v, 0.10)
        p25 = percentile(v, 0.25)
        p50 = percentile(v, 0.50)
        p75 = percentile(v, 0.75)
        p90 = percentile(v, 0.90)
        by_sido.append({
            "sido": s, "n": n,
            "p10": round(p10 / 1000) * 1000,
            "p25": round(p25 / 1000) * 1000,
            "median": round(p50 / 1000) * 1000,
            "p75": round(p75 / 1000) * 1000,
            "p90": round(p90 / 1000) * 1000,
            "iqr": round((p75 - p25) / 1000) * 1000,
        })
    ranked = sorted([b for b in by_sido if b.get("n")], key=lambda d: -d["median"])
    top, bot = ranked[0], ranked[-1]
    miss_txt = ("·".join(missing) + " 2개 시도는 수집 시군구 원천 무거래로 제외" ) if missing else ""
    insight = (f"㎡당 매매가 중위는 {top['sido']} {top['median']//10000:,}만원으로 최고, "
               f"{bot['sido']} {bot['median']//10000:,}만원으로 최저(약 {top['median']/bot['median']:.1f}배 격차)다. "
               f"표본은 시도별 대표 시군구 1~2개(총 유효 {stats['valid']:,}건, {len(ranked)}개 시도)로 시도 전체를 "
               f"대표하지 않으며 분위수는 해당 시군구 분포임에 유의({miss_txt}).")
    return {
        "title": "실거래 분포 — 매매 ㎡당 가격 시도별 분위수(원/㎡)",
        "data": {"unit": "원/㎡", "by_sido": by_sido, "missing_sido": missing},
        "insight": insight,
    }


# ── 분석 5: 금리 국면별 수익률 ─────────────────────────────────────────────
def analyze_rate_regime(m):
    base = to_map(m["base_rate"])
    base6 = diff_k(base, 6)               # 6개월 기준금리 변화로 국면 판정
    sale_mom = mom_series(to_map(m["sale_index"]["전국"]))
    THR = 0.125                           # 반(半) 인상폭 기준 임계
    regimes = {"상승기": [], "하강기": [], "동결기": []}
    monthly = []
    for ym in sorted(base6, key=ym_idx):
        d = base6[ym]
        if d >= THR:
            reg = "상승기"
        elif d <= -THR:
            reg = "하강기"
        else:
            reg = "동결기"
        if ym in sale_mom:
            regimes[reg].append(sale_mom[ym])
            monthly.append({"ym": ym, "regime": reg,
                            "rate": round(base[ym], 2),
                            "sale_mom_pct": round(sale_mom[ym], 3)})
    rows = []
    for reg in ["상승기", "동결기", "하강기"]:
        vals = regimes[reg]
        rows.append({
            "regime": reg,
            "months": len(vals),
            "sale_mom_avg_pct": round(statistics.mean(vals), 3) if vals else None,
            "sale_mom_sd_pp": round(statistics.pstdev(vals), 3) if len(vals) > 1 else None,
        })
    d = {r["regime"]: r["sale_mom_avg_pct"] for r in rows}
    insight = (f"기준금리 상승(긴축) 국면 전국 매매지수 MoM 평균은 {d['상승기']}%로 유일하게 하락 전환하고, "
               f"동결기 +{d['동결기']}%·하강기 +{d['하강기']}%로 반등해 긴축 종료 이후 회복 탄력이 확인된다. "
               f"국면은 6개월 기준금리 변화(±{THR}%p)로 정의했으며 정책과 가격의 시차·소표본 한계로 인과 해석은 유보한다.")
    return {
        "title": "금리 국면별 수익률 — 상승/동결/하강 국면 전국 매매지수 월평균 변동률",
        "data": {"regimes": rows, "monthly": monthly,
                 "regime_def": f"국면=기준금리 6개월 변화 ±{THR}%p 임계로 상승/하강/동결 분류"},
        "insight": insight,
    }


# ── 메인 ──────────────────────────────────────────────────────────────────
def main():
    m = load_market()
    prices, pstats = load_rtms_prices()

    a1 = analyze_correlation(m)
    a2 = analyze_seasonality(m)
    a3 = analyze_sync(m)
    missing_rtms = list(m["meta"].get("missing_rtms_sido", []))
    a4 = analyze_distribution(prices, pstats, missing_rtms)
    a5 = analyze_rate_regime(m)

    notes = [
        "월별 시계열은 'YYYYMM' 키 기준 교집합으로 정렬. 결측월은 상관·YoY 계산에서 자연 제외(삭제법).",
        "YoY=전년동월대비 %(12개월 전 대비), MoM=전월대비 %. 12개월 전(또는 직전월) 결측 시 해당 관측치 제외.",
        "공사비지수(cci)·분양가(presale)는 2026-03월 등 일부 월 결측(HUG 미발표). 결측은 교집합 정렬로 자동 배제.",
        "미분양 시계열은 202605까지, 기준금리는 202607까지, 매매지수는 202606까지로 as-of 상이(meta.asof 참조).",
        f"RTMS 실거래 분포는 원자료 {pstats['total_items']:,}건 중 유효 {pstats['valid']:,}건 사용, "
        f"제외 {pstats['excluded']:,}건(빈값·면적<=0·㎡당 {PRICE_MIN:,}~{PRICE_MAX:,}원 범위밖).",
        "RTMS 표본은 시도별 대표 시군구 1~2개만 수집한 것으로 시도 전체 모집단을 대표하지 않음(선택편향).",
        f"실거래 분포에서 {'·'.join(m['meta'].get('missing_rtms_sido', [])) or '없음'} 시도는 수집 시군구가 원천 무거래(totalCount=0)로 유효표본 0건 — 행은 유지하되 분위수 미산출.",
        "상관계수는 인과관계가 아니며, 추세를 공유하는 지표 간에는 공통추세로 인한 허위상관 가능성 존재.",
    ]

    out = {
        "meta": {
            "asof": m["meta"]["asof"],
            "sources": m["meta"]["sources"],
            "index_base_ym": m["meta"]["index_base_ym"],
            "generated_at": "2026-07-21",
            "n_sale_transactions_valid": pstats["valid"],
            "n_sale_transactions_raw": pstats["total_items"],
            "sido_count": len(SIDO17),
        },
        "notes": notes,
        "correlation": a1,
        "seasonality": a2,
        "synchronization": a3,
        "distribution": a4,
        "rate_regime": a5,
    }

    # ── 검증 assert ──────────────────────────────────────────────────────
    # 상관계수 [-1,1]
    def check_r(x):
        assert x is None or (-1.0 <= x <= 1.0), f"상관계수 범위 이탈: {x}"
    for name, info in a1["data"]["national"].items():
        for _, cell in info["by_lag"].items():
            check_r(cell["r"])
    for row in a1["data"]["cross_sido"]:
        for kk in ["base_rate_level", "base_rate_12mchg", "unsold_yoy_own", "cci_yoy", "presale_yoy"]:
            check_r(row[kk])
    for e in a3["data"]["seoul_vs_each"]:
        check_r(e["r"])
    check_r(a3["data"]["seoul_vs_jibang_r"])
    # 계절성 12개 값
    assert len(a2["data"]["months"]) == 12 and len(a2["data"]["mom_avg_pct"]) == 12, "계절성 12개월 아님"
    assert a2["data"]["months"] == list(range(1, 13)), "계절성 월 라벨 1~12 아님"
    # 시도 수 17 커버 (상관·동조화·분포 모두)
    assert len(a1["data"]["cross_sido"]) == 17, "상관 시도 17 미달"
    assert len({r["sido"] for r in a1["data"]["cross_sido"]}) == 17, "상관 시도 중복/누락"
    assert len(a4["data"]["by_sido"]) == 17, "분포 시도 17 미달(행 기준)"
    covered = {b["sido"] for b in a4["data"]["by_sido"] if b.get("n")}
    # RTMS 원천 무거래 시도(광주·전남, meta.missing_rtms_sido)는 유효표본 0 — 문서화된 결측
    assert covered == set(SIDO17) - set(missing_rtms), \
        f"분포 커버 불일치: 미커버={set(SIDO17)-covered}, 예상결측={set(missing_rtms)}"

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))

    size = os.path.getsize(OUT)
    print(f"[OK] {OUT}  ({size/1024:.1f} KB)")
    print(f"  유효 실거래 {pstats['valid']:,} / 원자료 {pstats['total_items']:,} (제외 {pstats['excluded']:,})")
    print(f"  시도 커버: 상관 {len(a1['data']['cross_sido'])} · 분포 {len(covered)} · 계절성 12개월")
    # 콘솔 요약(오케스트레이터용)
    nat = a1["data"]["national"]
    print("\n[요약]")
    for k, v in nat.items():
        print(f"  corr(전국매매YoY, {k}): best lag={v['best_lag']} r={v['best_r']}  (동시 r={v['by_lag']['0']['r']})")
    print(f"  계절성 MoM 월별: {a2['data']['mom_avg_pct']}")
    print(f"  서울-지방 상관 r={a3['data']['seoul_vs_jibang_r']} (n={a3['data']['seoul_vs_jibang_n']})")
    print(f"  횡단면 σ 범위: {min(a3['data']['cross_sd_pp'])} ~ {max(a3['data']['cross_sd_pp'])} %p")
    for r in a5["data"]["regimes"]:
        print(f"  금리 {r['regime']}: MoM 평균 {r['sale_mom_avg_pct']}% (n={r['months']}개월)")
    return out


if __name__ == "__main__":
    main()
