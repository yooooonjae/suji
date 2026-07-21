"""시장 분석 빌드 테스트 — market.json·cases.json 계약·지수화·패리티 검증.

검증 항목:
  - 지수화: presale_indexed·cci_indexed 첫 값 100, 동일 월범위 정렬
  - phase_points: YoY 를 원자료에서 독립 재계산해 대조(수기 표본)
  - YoY 나눗셈 가드(12개월 전 0 → 0, 결측 → None)
  - market.json 계약 키 존재
  - cases: result.profit == run_feasibility(inputs) 재계산 일치
  - 프리셋 키가 계산기(calc-ui.js) st 상태 키와 일치
  - rtms 결측 시도(광주·전남) trade_median_last=null 허용 + meta 기록
"""

import json

import pytest

from src.analysis import market, cases
from src.analysis.feasibility import run_feasibility


# --------------------------------------------------------------------------- #
# 픽스처
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def M():
    return market.build()


@pytest.fixture(scope="module")
def CS():
    return cases.build()


# --------------------------------------------------------------------------- #
# 지수화
# --------------------------------------------------------------------------- #
def test_indexed_first_value_is_100(M):
    ps, cci = M["presale_indexed"], M["cci_indexed"]
    assert ps and cci
    assert ps[0]["value"] == pytest.approx(100.0)
    assert cci[0]["value"] == pytest.approx(100.0)


def test_indexed_series_aligned(M):
    """두 지수 계열은 동일 월범위(교집합)·동일 길이·동일 시작월이어야 오버레이가 정합."""
    ps, cci = M["presale_indexed"], M["cci_indexed"]
    assert len(ps) == len(cci)
    assert [p["ym"] for p in ps] == [c["ym"] for c in cci]
    assert ps[0]["ym"] == cci[0]["ym"] == M["meta"]["index_base_ym"]


def test_presale_national_is_arithmetic_mean():
    """HUG 전국 계열은 월별 시도 산술평균이어야 한다(임의 월 표본)."""
    hug = market._load("hug.json")
    nat = market.hug_national(hug)
    d = {p["ym"]: p["value"] for p in nat}
    sample = nat[len(nat) // 2]["ym"]
    vals = [s[i]["value"] for s in hug["presale_price"].values()
            for i in range(len(s)) if s[i]["ym"] == sample]
    assert d[sample] == pytest.approx(sum(vals) / len(vals))


# --------------------------------------------------------------------------- #
# phase_points — YoY 독립 재계산 대조
# --------------------------------------------------------------------------- #
def _independent_yoy(series):
    """market 과 다른 경로로 YoY 재계산: 12개월 전 ym 을 (연-1, 동월) 문자열로."""
    d = {p["ym"]: p["value"] for p in series}
    last = series[-1]["ym"]
    y, m = int(last[:4]), int(last[4:6])
    prev = f"{y - 1}{m:02d}"
    return (d[last] - d[prev]) / d[prev] * 100.0


def test_phase_points_match_independent_yoy(M):
    rone = market._load("rone.json")
    kosis = market._load("kosis.json")
    pt = {p["name"]: p for p in M["phase_points"]}
    for sido in ("서울", "경기", "부산", "전국"):
        exp_y = _independent_yoy(rone["sale_index"][sido])
        exp_x = _independent_yoy(kosis["unsold"][sido])
        assert pt[sido]["y"] == pytest.approx(exp_y)
        assert pt[sido]["x"] == pytest.approx(exp_x)


def test_phase_points_handcheck_literal(M):
    """수기 대조(고정 원자료): 서울 매매 +10.727%, 미분양 -0.404%."""
    seoul = next(p for p in M["phase_points"] if p["name"] == "서울")
    assert seoul["y"] == pytest.approx(10.726884634065287, rel=1e-9)
    assert seoul["x"] == pytest.approx(-0.40444893832153694, rel=1e-9)


def test_phase_points_include_nationwide(M):
    names = {p["name"] for p in M["phase_points"]}
    assert "전국" in names
    assert len(M["phase_points"]) == 18


# --------------------------------------------------------------------------- #
# YoY 나눗셈 가드
# --------------------------------------------------------------------------- #
def test_yoy_zero_guard():
    # 12개월 전 값이 0 → 0 반환(0으로 나눔 방지)
    series = [{"ym": "202401", "value": 0.0}] + \
             [{"ym": f"2024{m:02d}", "value": 100.0} for m in range(2, 13)] + \
             [{"ym": "202501", "value": 50.0}]
    assert market._yoy_pct(series) == 0.0


def test_yoy_missing_prev_returns_none():
    series = [{"ym": "202501", "value": 100.0}, {"ym": "202502", "value": 110.0}]
    assert market._yoy_pct(series) is None


def test_ym_minus_wraps_year():
    assert market._ym_minus("202606", 12) == "202506"
    assert market._ym_minus("202601", 1) == "202512"
    assert market._ym_minus("202603", 12) == "202503"


# --------------------------------------------------------------------------- #
# 계약 키 존재
# --------------------------------------------------------------------------- #
REQUIRED_MARKET_KEYS = [
    "sale_index", "jeonse_index", "sub_index", "unsold", "unsold_completed",
    "base_rate", "mortgage_rate", "corp_loan_rate",
    "presale_indexed", "cci_indexed", "phase_points", "sido_summary", "meta",
]


def test_market_contract_keys(M):
    for k in REQUIRED_MARKET_KEYS:
        assert k in M, f"market.json 누락 키: {k}"


def test_market_sale_index_has_nationwide_and_18(M):
    assert "전국" in M["sale_index"]
    assert len(M["sale_index"]) == 18
    assert "전국" in M["jeonse_index"]


# --------------------------------------------------------------------------- #
# sub_index — 시군구 드릴다운(R-ONE 하위지역)
# --------------------------------------------------------------------------- #
def test_sub_index_region_counts(M):
    """서울 25구·경기 28시·부산 16구군 등 시도별 하위지역 수(원자료 실측)."""
    sub = M["sub_index"]
    assert len(sub["서울"]) == 25
    assert len(sub["경기"]) == 28
    assert len(sub["부산"]) == 16
    for sido in ("대구", "인천"):
        assert len(sub[sido]) == 8
    for sido in ("광주", "대전", "울산"):
        assert len(sub[sido]) == 5


def test_sub_index_value_range(M):
    """모든 하위지역 지수는 유효범위 20~200 내."""
    for units in M["sub_index"].values():
        for series in units.values():
            for p in series:
                assert 20.0 <= p["value"] <= 200.0, p


def test_sub_index_latest_month_matches_sido(M):
    """하위지역 최근월은 상위 시도 매매지수 최근월과 동일해야 정합(드릴다운 기준)."""
    for sido, units in M["sub_index"].items():
        sido_last = M["sale_index"][sido][-1]["ym"]
        for name, series in units.items():
            assert series[-1]["ym"] == sido_last, f"{sido}/{name}"


def test_sub_index_seoul_has_gangnam(M):
    gangnam = M["sub_index"]["서울"]["강남구"]
    assert gangnam and all(set(p) == {"ym", "value"} for p in gangnam)
    assert len(gangnam) >= 24  # 최근 10년(120개월) 수집이나 최소 하한만 강제


def test_rate_series_truncated_to_120(M):
    for k in ("base_rate", "mortgage_rate", "corp_loan_rate"):
        assert len(M[k]) <= market.RATE_MONTHS
        assert all("ym" in p and "value" in p for p in M[k])


def test_sido_summary_shape(M):
    s = M["sido_summary"]["서울"]
    assert set(s) == {"sale_yoy", "unsold_last", "presale_m2_last", "trade_median_last"}


def test_meta_asof_populated(M):
    asof = M["meta"]["asof"]
    for k in ("rone_sale", "kosis_unsold", "kosis_cci", "ecos_base_rate",
              "hug_presale", "rtms"):
        assert asof[k] and len(asof[k]) == 6  # YYYYMM


# --------------------------------------------------------------------------- #
# rtms 결측 시도 처리
# --------------------------------------------------------------------------- #
def test_rtms_missing_sido_null_and_recorded(M):
    # 2026-07 행정구역 통폐합 신코드(12) 재수집으로 광주·전남 채움 — 17시도 완비가 정상
    missing = M["meta"]["missing_rtms_sido"]
    assert missing == [], f"결측 시도 재발생: {missing}"
    for sido in missing:
        # 결측이어도 요약엔 시도가 존재하되 실거래 중위가만 null
        assert M["sido_summary"][sido]["trade_median_last"] is None
        # 다른 지표는 살아있음(삼키지 않음)
        assert M["sido_summary"][sido]["unsold_last"] is not None


def test_rtms_present_sido_has_trade_median(M):
    assert M["sido_summary"]["서울"]["trade_median_last"] is not None


# --------------------------------------------------------------------------- #
# cases 패리티 — result == run_feasibility(inputs) 재계산
# --------------------------------------------------------------------------- #
def test_cases_count_and_types(CS):
    assert len(CS["cases"]) == 4
    types = [c["type"] for c in CS["cases"]]
    assert types.count("신축분양") == 3
    assert types.count("재건축") == 1


def test_cases_result_equals_recompute(CS):
    for c in CS["cases"]:
        recomputed = run_feasibility(c["inputs"])
        assert recomputed["profit"] == c["result"]["profit"]
        assert recomputed == c["result"]  # 결정적 재계산 → 전체 일치


def test_cases_profit_positive(CS):
    # 표준 사례는 모두 이익 양수(실무 표준 가정)
    for c in CS["cases"]:
        assert c["result"]["profit"] > 0, c["name"]


def test_cases_notes_count(CS):
    for c in CS["cases"]:
        assert 4 <= len(c["notes"]) <= 7, c["name"]  # 재건축 7개(재초환 미반영 노트 포함)
        assert all(isinstance(n, str) and n for n in c["notes"])


def test_redevelopment_case_has_proportion_rate(CS):
    redev = next(c for c in CS["cases"] if c["type"] == "재건축")
    r = redev["result"]
    assert r["proportion_rate"] is not None
    assert r["member_contribution"] is not None
    # 현실적 비례율 범위(0.9~1.3)
    assert 0.9 < r["proportion_rate"] < 1.3


# --------------------------------------------------------------------------- #
# 프리셋 ↔ 계산기 st 키 정합
# --------------------------------------------------------------------------- #
# calc-ui.js 의 st 상태 키(실무단위) 전체 집합 + __mode(특수).
CALC_UI_ST_KEYS = {
    "land_area", "zone", "far_override", "nb_ratio",
    "avg_supply", "price_py", "sell_through",
    "land_eok", "unit_cost_py", "months", "indirect", "marketing", "contingency",
    "equity_eok", "bridge_eok", "bridge_rate", "bridge_mo",
    "pf_eok", "pf_rate", "pf_draw", "fee",
    "prior_eok", "members", "mem_supply", "mem_price_py", "gen_units",
    "relo_eok", "relo_rate", "demo_eok", "rental", "cashout",
    "__mode",
}


def test_presets_keys_subset_of_calc_ui(CS):
    for name, p in CS["presets"].items():
        unknown = set(p) - CALC_UI_ST_KEYS
        assert not unknown, f"{name}: 계산기 미지원 키 {unknown}"


def test_required_presets_present(CS):
    for name in ("수도권아파트", "지방아파트", "서울재건축"):
        assert name in CS["presets"]
    assert CS["presets"]["서울재건축"]["__mode"] == "재건축"


def test_preset_values_are_realistic(CS):
    p = CS["presets"]["수도권아파트"]
    assert p["zone"] in ("R1", "R2", "R3", "RS", "CG", "IS")
    assert 800 <= p["price_py"] <= 6500       # calc-ui 슬라이더 범위 내
    assert 450 <= p["unit_cost_py"] <= 1300


# --------------------------------------------------------------------------- #
# 파일 산출물 유효성
# --------------------------------------------------------------------------- #
def test_build_writes_valid_json(tmp_path, monkeypatch):
    monkeypatch.setattr(market, "OUT", tmp_path)
    monkeypatch.setattr(cases, "OUT", tmp_path)
    mp = market.main()
    cp = cases.main()
    assert json.loads(mp.read_text(encoding="utf-8"))["sale_index"]
    assert json.loads(cp.read_text(encoding="utf-8"))["cases"]
