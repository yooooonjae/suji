"""수지분석 모델 코어 테스트.

수기(hand-calc)로 검산한 소형 사례를 기대값으로 assert 한다.
핵심 금액은 정확값으로, 비율·NPV·IRR 은 pytest.approx 로 검증한다.
"""

import math

import pytest

from src.analysis.feasibility import (
    run_feasibility,
    compute_revenue,
    compute_finance_cost,
    compute_cashflow,
    compute_npv,
    compute_irr_annual,
)


# --------------------------------------------------------------------------- #
# 소형 수기 검산 사례
# --------------------------------------------------------------------------- #
# 세대 2종류, 단순 수치. 아래 기대값은 손계산으로 도출했다.
#   분양수입(sales) = (10*100*10,000,000)*2 * 1.0 = 20,000,000,000, other=0
#   토지비 = 5,000,000,000 * (1+0.046+0.01) = 5,280,000,000
#   공사비 = 2000 * 2,000,000 = 4,000,000,000
#   간접비 = 4,000,000,000 * 0.06 = 240,000,000
#   판매비 = 20,000,000,000 * 0.035 = 700,000,000
#   금융비 = 1e9*0.10*12/12 + 4e9*0.5*0.05*24/12 + (1e9+4e9)*0.01
#          = 100,000,000 + 200,000,000 + 50,000,000 = 350,000,000
#   예비비 = (5,280,000,000+4,000,000,000+240,000,000)*0.01 = 95,200,000
#   총지출 = 10,665,200,000
#   이익   = 20,000,000,000 - 10,665,200,000 = 9,334,800,000
def small_case():
    return {
        "revenue": {
            "units": [
                {"name": "A", "count": 10, "supply_m2": 100, "price_per_m2": 10_000_000},
                {"name": "B", "count": 10, "supply_m2": 100, "price_per_m2": 10_000_000},
            ],
            "sell_through": 1.0,
            "other_income": 0,
        },
        "cost": {
            "land": {"purchase": 5_000_000_000, "acq_tax_rate": 0.046, "misc_rate": 0.01},
            "construction": {"gfa_m2": 2000, "unit_cost_per_m2": 2_000_000},
            "indirect_rate": 0.06,
            "marketing_rate": 0.035,
            "contingency_rate": 0.01,
        },
        "finance": {
            "equity": 2_000_000_000,
            "bridge": {"amount": 1_000_000_000, "rate": 0.10, "months": 12},
            "pf": {"amount": 4_000_000_000, "rate": 0.05, "months": 24, "drawdown": 0.5},
            "fee_rate": 0.01,
        },
        "schedule": {"months_total": 12},
        "discount_rate": 0.08,
    }


def test_revenue_total():
    r = run_feasibility(small_case())
    assert r["revenue_total"] == 20_000_000_000


def test_cost_breakdown_exact():
    r = run_feasibility(small_case())
    c = r["cost"]
    # 요율 곱셈은 부동소수 오차가 나므로 approx 로 검증
    assert c["land"] == pytest.approx(5_280_000_000)
    assert c["construction"] == pytest.approx(4_000_000_000)
    assert c["indirect"] == pytest.approx(240_000_000)
    assert c["marketing"] == pytest.approx(700_000_000)
    assert c["finance"] == pytest.approx(350_000_000)
    assert c["contingency"] == pytest.approx(95_200_000)
    assert r["cost_total"] == pytest.approx(10_665_200_000)


def test_profit_and_margins():
    r = run_feasibility(small_case())
    assert r["profit"] == pytest.approx(9_334_800_000)
    assert r["margin_on_revenue"] == pytest.approx(9_334_800_000 / 20_000_000_000)
    assert r["margin_on_cost"] == pytest.approx(9_334_800_000 / 10_665_200_000)
    assert r["roe"] == pytest.approx(9_334_800_000 / 2_000_000_000)


def test_cashflow_quarterly_exact():
    r = run_feasibility(small_case())
    cf = r["cashflow_quarterly"]
    # months_total=12 -> 4개 분기 (q0..q3)
    assert len(cf) == 4
    # 유입: 계약금10% q0=2e9, 중도금60% q1·q2=6e9씩, 잔금30% q3=6e9
    # 유출: 토지비 q0, (공사+간접+예비)=4,335,200,000 균등 1,083,800,000,
    #       판매비 유입비례(0.1/0.3/0.3/0.3), 금융비 350,000,000 균등 87,500,000
    #   q0 유출 = 5,280,000,000+1,083,800,000+70,000,000+87,500,000 = 6,521,300,000
    #   q1..q3 유출 = 1,083,800,000+210,000,000+87,500,000 = 1,381,300,000
    assert cf[0] == pytest.approx(2_000_000_000 - 6_521_300_000)   # -4,521,300,000
    assert cf[1] == pytest.approx(6_000_000_000 - 1_381_300_000)   #  4,618,700,000
    assert cf[2] == pytest.approx(6_000_000_000 - 1_381_300_000)
    assert cf[3] == pytest.approx(6_000_000_000 - 1_381_300_000)


def test_cashflow_sum_equals_profit():
    r = run_feasibility(small_case())
    # 부동소수 누적오차 방어: 합계는 이익과 ±1원 이내
    assert abs(sum(r["cashflow_quarterly"]) - r["profit"]) < 1.0


def test_npv_matches_formula():
    r = run_feasibility(small_case())
    rq = (1 + 0.08) ** 0.25 - 1
    cf = r["cashflow_quarterly"]
    expected = sum(c / (1 + rq) ** q for q, c in enumerate(cf))
    assert r["npv"] == pytest.approx(expected)


def test_irr_annual_is_root():
    r = run_feasibility(small_case())
    # 유입/유출 부호 변화 존재 -> IRR 실수 해 존재
    assert r["irr_annual"] is not None
    irr_q = (1 + r["irr_annual"]) ** 0.25 - 1
    residual = sum(c / (1 + irr_q) ** q for q, c in enumerate(r["cashflow_quarterly"]))
    assert residual == pytest.approx(0.0, abs=1.0)


# --------------------------------------------------------------------------- #
# 경계 테스트
# --------------------------------------------------------------------------- #
def test_sell_through_zero_negative_profit():
    inp = small_case()
    inp["revenue"]["sell_through"] = 0.0
    inp["revenue"]["other_income"] = 0
    r = run_feasibility(inp)
    assert r["revenue_total"] == 0
    assert r["profit"] < 0                       # 이익 음수
    assert r["margin_on_revenue"] is None         # 총수입 0 -> None 가드
    # 판매비도 0 (수입×요율)
    assert r["cost"]["marketing"] == 0


def test_finance_cost_zero_when_no_debt():
    inp = small_case()
    inp["finance"]["bridge"]["amount"] = 0
    inp["finance"]["pf"]["amount"] = 0
    r = run_feasibility(inp)
    assert r["cost"]["finance"] == 0


def test_irr_none_when_all_negative():
    inp = small_case()
    inp["revenue"]["sell_through"] = 0.0
    inp["revenue"]["other_income"] = 0
    r = run_feasibility(inp)
    # 전 분기 음수 cf -> 부호 변화 없음 -> None
    assert all(c <= 0 for c in r["cashflow_quarterly"])
    assert r["irr_annual"] is None


def test_roe_none_when_equity_zero():
    inp = small_case()
    inp["finance"]["equity"] = 0
    r = run_feasibility(inp)
    assert r["roe"] is None


def test_default_discount_rate():
    # discount_rate 미지정 시 기본 0.08 적용
    inp = small_case()
    del inp["discount_rate"]
    r = run_feasibility(inp)
    rq = (1 + 0.08) ** 0.25 - 1
    cf = r["cashflow_quarterly"]
    expected = sum(c / (1 + rq) ** q for q, c in enumerate(cf))
    assert r["npv"] == pytest.approx(expected)


# --------------------------------------------------------------------------- #
# 순수 함수 단위 테스트
# --------------------------------------------------------------------------- #
def test_compute_revenue_pure():
    rev = compute_revenue(small_case()["revenue"])
    assert rev["sales"] == 20_000_000_000
    assert rev["other"] == 0
    assert rev["total"] == 20_000_000_000


def test_compute_finance_cost_pure():
    fin = small_case()["finance"]
    assert compute_finance_cost(fin) == 350_000_000


def test_compute_cashflow_conserves_sum():
    # 임의 값으로 유입·유출 합계 보존 확인
    cf = compute_cashflow(
        sales=1_000_000_000,
        other_income=50_000_000,
        cost={
            "land": 400_000_000,
            "construction": 300_000_000,
            "indirect": 20_000_000,
            "marketing": 35_000_000,
            "finance": 10_000_000,
            "contingency": 7_000_000,
        },
        months_total=15,
    )
    inflow_total = 1_000_000_000 + 50_000_000
    outflow_total = 400_000_000 + 300_000_000 + 20_000_000 + 35_000_000 + 10_000_000 + 7_000_000
    assert abs(sum(cf) - (inflow_total - outflow_total)) < 1.0


def test_compute_npv_and_irr_pure():
    cf = [-1000.0, 400.0, 400.0, 400.0]
    npv0 = compute_npv(cf, 0.0)          # 할인율 0 -> 단순 합
    assert npv0 == pytest.approx(200.0)
    irr = compute_irr_annual(cf)
    assert irr is not None
    irr_q = (1 + irr) ** 0.25 - 1
    assert sum(c / (1 + irr_q) ** q for q, c in enumerate(cf)) == pytest.approx(0.0, abs=1e-6)


def test_compute_irr_none_no_sign_change():
    assert compute_irr_annual([-100.0, -50.0, -20.0]) is None
    assert compute_irr_annual([100.0, 50.0, 20.0]) is None
