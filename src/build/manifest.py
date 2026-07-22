"""DATA_MANIFEST.json 생성 — data/ 각 원천의 공통 데이터 원장.

원장은 원천마다 다음을 분리 기록한다 (5차 리뷰 「공통 데이터 원장」 사양):
  - source          : 발급 기관·데이터셋 명칭 (data/*.json 의 source 필드)
  - observed_through : 데이터가 실제 **관측**하는 마지막 시점 (관측월)
  - collected_at     : API 를 호출해 **수집**한 날짜 (수집일)
  - rows             : 데이터 규모 — 실거래는 거래 건수, 지수는 관측치 수
  - coverage         : 지역·주기·기간 커버리지 한 줄 요약

관측월(observed_through)과 수집일(collected_at)의 간격이 곧 데이터 지연이다.
두 값을 뭉뚱그리지 않고 나눠 적는 것이 이 파일의 목적이다.

data_cutoff = 전 원천의 월간 관측월 중 **현재 달을 제외한** 최신 월(마지막 완결월).
              현재 달(부분 관측)은 신뢰 기준월에서 제외한다.

실행:  python3 src/build/manifest.py         →  data/DATA_MANIFEST.json 생성·검증 출력
사용:  from src.build.manifest import build_manifest  (assemble.py 가 빌드 시 호출)
"""

import datetime
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
MANIFEST_PATH = DATA / "DATA_MANIFEST.json"

_YM = re.compile(r"^(19|20)\d{2}(0[1-9]|1[0-2])$")
_YQ = re.compile(r"^(19|20)\d{2}Q[1-4]$")


# ------------------------------------------------------------------ #
# 재귀 스캐너 — 중첩 구조(지역→시군구→월)에 무관하게 관측 시점 수집
# ------------------------------------------------------------------ #
def _scan_months(obj, out):
    if isinstance(obj, dict):
        for k in ("ym", "month", "date"):
            v = obj.get(k)
            if isinstance(v, (str, int)):
                s = str(v).replace("-", "")[:6]
                if _YM.match(s):
                    out.append(s)
        for v in obj.values():
            _scan_months(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _scan_months(v, out)


def _scan_quarters(obj, out):
    if isinstance(obj, dict):
        v = obj.get("yq")
        if isinstance(v, str) and _YQ.match(v):
            out.append(v)
        for v in obj.values():
            _scan_quarters(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _scan_quarters(v, out)


def _count_points(obj):
    """시계열 관측치(leaf record) 개수 — ym/yq 키를 가진 dict 를 센다."""
    n = 0
    if isinstance(obj, dict):
        if any(k in obj for k in ("ym", "yq", "month")):
            return 1
        for v in obj.values():
            n += _count_points(v)
    elif isinstance(obj, list):
        for v in obj:
            n += _count_points(v)
    return n


def _fmt_month(yyyymm):
    return f"{yyyymm[:4]}-{yyyymm[4:6]}" if yyyymm else None


def _fmt_quarter(yq):
    return f"{yq[:4]} {yq[4:]}" if yq else None  # 2026Q1 -> "2026 Q1"


def _months_span(d):
    """파일 전체에서 (최소월, 최대월) YYYYMM 반환."""
    ms = []
    _scan_months(d, ms)
    return (min(ms), max(ms)) if ms else (None, None)


# ------------------------------------------------------------------ #
# 원천별 핸들러 — 각 값이 실데이터에서 어떻게 나오는지 명시적으로 계산
# ------------------------------------------------------------------ #
def _h_rone(d):
    lo, hi = _months_span(d)
    regions = len(d.get("sale_index", {}))
    return dict(observed_through=_fmt_month(hi),
                rows=_count_points(d),
                coverage=f"{regions}개 시도·전국 · 매매·전세·분양가 3지수 · {lo[:4]}.{lo[4:]}~월별")


def _h_rone_sub(d):
    lo, hi = _months_span(d)
    sido = len(d.get("sale_sub", {}))
    return dict(observed_through=_fmt_month(hi),
                rows=_count_points(d),
                coverage=f"{sido}개 시도 하위 시군구 · 매매·전세 지수 · {lo[:4]}.{lo[4:]}~월별")


def _h_rone_commercial(d):
    qs = []
    _scan_quarters(d, qs)
    hi = max(qs) if qs else None
    lo = min(qs) if qs else None
    regions = len(d.get("office_rent_index", {}))
    return dict(observed_through=_fmt_quarter(hi),
                rows=_count_points(d),
                coverage=f"{regions}개 시도 · 오피스·상가 임대·공실·투자수익률 · {lo}~분기")


def _h_ecos(d):
    lo, hi = _months_span(d)
    return dict(observed_through=_fmt_month(hi),
                rows=_count_points(d),
                coverage=f"기준금리·주담대·기업대출 3계열 · {lo[:4]}.{lo[4:]}~월별")


def _h_kosis(d):
    lo, hi = _months_span(d)
    regions = len(d.get("unsold", {}))
    return dict(observed_through=_fmt_month(hi),
                rows=_count_points(d),
                coverage=f"{regions}개 지역 · 미분양·인허가·착공·준공+건설공사비지수 · {lo[:4]}.{lo[4:]}~월별")


def _h_hug(d):
    lo, hi = _months_span(d)
    regions = len(d.get("presale_price", {}))
    return dict(observed_through=_fmt_month(hi),
                rows=_count_points(d),
                coverage=f"{regions}개 시도 · 민간아파트 ㎡당 분양가 · {lo[:4]}.{lo[4:]}~월별")


def _h_archub(d):
    lo, hi = _months_span(d)
    regions = len(d.get("permits_monthly", {}))
    return dict(observed_through=_fmt_month(hi),
                rows=_count_points(d),
                coverage=f"{regions}개 시도 대표 시군구 · 공동주택 인허가 세대 · {lo[:4]}.{lo[4:]}~월별")


def _sum_counts(block):
    """{sido: {sigungu: [{count:..}]}} 구조에서 count 총합(거래 건수)."""
    t = 0
    for sgs in block.values():
        for ser in sgs.values():
            for row in ser:
                t += row.get("count", 0)
    return t


def _h_rtms(d):
    lo, hi = _months_span(d)
    apt = _sum_counts(d.get("trades", {}))
    presale = _sum_counts(d.get("presale_trades", {}))
    sido = len(d.get("trades", {}))
    return dict(observed_through=_fmt_month(hi),
                rows=apt + presale,
                coverage=f"{sido}개 시도 대표 시군구 · 아파트 매매 {apt:,}+분양권 {presale:,}건 · 월별 집계")


def _months_from_range(s):
    """'202308~202607' → ('2023-08','2026-07')."""
    m = re.findall(r"(\d{6})", s or "")
    if len(m) >= 2:
        return _fmt_month(m[0]), _fmt_month(m[-1])
    return None, None


def _h_rtms_seoul(d):
    lo, hi = _months_from_range(d.get("months", ""))
    rows = sum(g.get("n", 0) for g in d.get("by_gu", {}).values())
    gu = len(d.get("by_gu", {}))
    return dict(observed_through=hi,
                rows=rows,
                coverage=f"서울 {gu}개 구 전수 · 아파트 매매 실거래 · {lo}~{hi}")


def _h_rtms_commercial(d):
    lo, hi = _months_from_range(d.get("months", ""))
    totals = d.get("totals", {})
    rows = sum(totals.values())
    return dict(observed_through=hi,
                rows=rows,
                coverage=(f"17개 시도 · 상업업무 {totals.get('nrg',0):,}·"
                          f"오피스텔 {totals.get('offi',0):,}·토지 {totals.get('land',0):,}건 · {lo}~{hi}"))


def _h_sbiz(d):
    total = sum(sum(v.values()) for v in d.get("counts", {}).values())
    regions = len(d.get("counts", {}))
    upjong = len(d.get("upjong_large", []))
    return dict(observed_through=None,  # 등록 스냅샷 — 시계열 없음
                rows=total,
                coverage=f"{regions}개 시도 × {upjong}개 업종대분류 · 상가업소 등록 스냅샷")


# (key, 표시명, 기관, 핸들러) — 표시 순서 = 사이트 방법론 표 순서
SOURCES = [
    ("rone", "주택가격동향 (매매·전세·분양가 지수)", "한국부동산원 R-ONE", _h_rone),
    ("rone_sub", "시군구 하위 가격지수", "한국부동산원 R-ONE", _h_rone_sub),
    ("rone_commercial", "상업용부동산 임대동향", "한국부동산원 R-ONE", _h_rone_commercial),
    ("rtms", "아파트 매매·분양권 실거래", "국토교통부 RTMS", _h_rtms),
    ("rtms_seoul", "서울 25개 구 아파트 매매 전수", "국토교통부 RTMS", _h_rtms_seoul),
    ("rtms_commercial", "상업업무·오피스텔·토지 실거래", "국토교통부 RTMS", _h_rtms_commercial),
    ("kosis", "미분양·공급·건설공사비지수", "통계청 KOSIS·KICT", _h_kosis),
    ("archub", "건축 인허가 (공동주택 세대)", "국토교통부 건축HUB", _h_archub),
    ("ecos", "기준금리·대출금리", "한국은행 ECOS", _h_ecos),
    ("hug", "민간아파트 분양가격", "주택도시보증공사 HUG", _h_hug),
    ("sbiz", "상가업소 상권정보", "소상공인시장진흥공단", _h_sbiz),
]


def build_manifest(write: bool = True) -> dict:
    """data/*.json 을 읽어 원장을 만든다. write=True 면 DATA_MANIFEST.json 기록."""
    today = datetime.date.today()
    cur_ym = today.strftime("%Y%m")
    sources = []
    complete_months = []  # 현재 달 제외한 월간 관측월 — data_cutoff 산정용

    for key, dataset, inst, handler in SOURCES:
        path = DATA / f"{key}.json"
        if not path.exists():
            raise FileNotFoundError(f"manifest: {path} 없음")
        d = json.loads(path.read_text())
        info = handler(d)
        collected = str(d.get("collected_at", ""))[:10]
        sources.append({
            "key": key,
            "dataset": dataset,
            "institution": inst,
            "source": d.get("source", inst),
            "observed_through": info["observed_through"],
            "collected_at": collected,
            "rows": info["rows"],
            "coverage": info["coverage"],
        })
        # data_cutoff: 월간(YYYY-MM) 관측월만, 현재 달 미만인 것 중 최대
        ot = info["observed_through"]
        if ot and re.match(r"^\d{4}-\d{2}$", ot):
            ym = ot.replace("-", "")
            if ym < cur_ym:
                complete_months.append(ym)

    cutoff = max(complete_months) if complete_months else None
    manifest = {
        "generated_at": today.isoformat(),
        "data_cutoff": _fmt_month(cutoff),
        "source_count": len(sources),
        "sources": sources,
    }
    if write:
        MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=1))
    return manifest


if __name__ == "__main__":
    m = build_manifest(write=True)
    print(f"DATA_MANIFEST.json — {m['source_count']}개 원천 · 데이터 기준월 {m['data_cutoff']}")
    print(f"{'원천':<22}{'관측월':<11}{'수집일':<12}{'건수':>12}")
    print("-" * 60)
    for s in m["sources"]:
        print(f"{s['key']:<18}{str(s['observed_through'] or '스냅샷'):<13}"
              f"{s['collected_at']:<12}{s['rows']:>12,}")
    print(f"\n→ {MANIFEST_PATH}")
