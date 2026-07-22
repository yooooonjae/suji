"""계산기 골든 테스트 — 손계산으로 검산한 **절대값** 기준 사례.

기존 test_parity.py 는 Python 코어 ↔ JS 이식본이 *서로 같은지*(패리티)만 본다.
패리티는 "둘 다 틀린" 경우를 못 잡는다. 이 파일은 외부에서 손으로 검산 가능한
기준 정답(golden)을 절대값으로 못박아, 두 구현이 *옳은지*를 검증한다.

기준 정답은 모두 엔진과 **독립적으로** 도출했다(뉴턴법·직접 합산·대수 손계산).
엔진이 기대값과 달라도 엔진을 고치지 않는다 — 불일치 발견 자체가 성과다.

────────────────────────────────────────────────────────────────────────────
골든 사례 표 (손계산 검산)
────────────────────────────────────────────────────────────────────────────
| ID              | 입력                                   | 산식                              | 기대값                         |
|-----------------|----------------------------------------|-----------------------------------|--------------------------------|
| CASE-DEV-001    | 토지 100·공사 200·기타(간접) 50·매출 420| 이익 = 매출 − 총지출               | 이익 70 · 이익률 70/420=16.67% |
|                 | (세금·판매·금융·예비 = 0)              | 이익률 = 이익/매출                 | margin_on_cost 70/350=20%      |
| CASE-INCOME-001 | NOI 10억 · cap 5%                      | 가치 = NOI ÷ (cap/100)            | 200억 (=1e9/0.05=2e10)         |
| CASE-IRR-001    | 현금흐름 [-1000, 500, 500, 500]        | Σ cf/(1+r)^i = 0 (뉴턴법)         | 기간이율 23.3752% (Excel IRR)  |
|                 |                                        | 엔진 연율 = (1+r_q)^4 − 1          | 연율 131.6922%                 |
| CASE-NPV-001    | 현금흐름 [-1000, 500, 500, 500]        | Σ cf/(1+r)^i                      | r=0 → 500.0                    |
|                 |                                        | 분기이율 10%(dr=1.1^4−1=0.4641)  | 243.4260                       |

주의 — 엔진의 기간 가정:
  compute_npv / compute_irr_annual 은 현금흐름 원소를 **분기**로 간주한다.
  · compute_npv(cf, dr): 분기이율 r_q = (1+dr)^(1/4) − 1 로 할인.
  · compute_irr_annual(cf): 분기 IRR r_q 를 구해 (1+r_q)^4 − 1 로 **연율화** 반환.
  따라서 Excel 의 *기간* IRR(23.3752%)은 엔진 연율값에서 (1+연율)^(1/4)−1 로 역산해 대조한다.
"""

import math
import os
import subprocess

import pytest

from src.analysis.feasibility import (
    run_feasibility,
    compute_npv,
    compute_irr_annual,
)
from src.analysis import zoning
from src.analysis.cases import build_inputs_from_state, PY


# --------------------------------------------------------------------------- #
# 외부 검증 기준값 (엔진과 독립적으로 도출 — 뉴턴법·직접합산·대수)
# --------------------------------------------------------------------------- #
IRR_CF = [-1000.0, 500.0, 500.0, 500.0]

# [-1000,500,500,500] 의 기간 IRR: 500(x+x²+x³)=1000 → x³+x²+x−2=0 의 근 x≈0.810536,
# r = 1/x − 1. 뉴턴법으로 소수 10자리까지 독립 도출(scratch verify 스크립트로 재현).
GOLDEN_IRR_PER_PERIOD = 0.2337519285      # ≈ 23.3752% (Excel IRR 규약, 기간이율)
GOLDEN_IRR_ANNUAL = 1.3169218123          # (1+0.2337519285)^4 − 1 — 엔진 연율화 반환값

# NPV: 분기이율 0 → 단순 합 = -1000+500+500+500 = 500
GOLDEN_NPV_AT_ZERO = 500.0
# 분기이율 10% 를 만들려면 연 할인율 dr = 1.1^4 − 1 = 0.4641 (엔진이 (1+dr)^0.25 로 분기환산)
DR_ANNUAL_FOR_10PCT_Q = 0.4641
# 500/1.1 + 500/1.21 + 500/1.331 − 1000 = 243.4259954921 (직접 합산, 독립)
GOLDEN_NPV_AT_10PCT_Q = 243.4259954921


# =========================================================================== #
# CASE-DEV-001 — 신축분양 최소 사례 (금융비·세금 0)
# =========================================================================== #
# 엔진 스키마 대응(손계산):
#   매출  = 1세대 × 1㎡ × 420 × sell_through 1.0 + other 0 = 420
#   토지비 = purchase 100 × (1 + 0 + 0)             = 100
#   공사비 = gfa 1 × unit 200                        = 200
#   간접비 = 공사비 200 × indirect_rate 0.25         = 50   ← "기타 50" 을 간접비 한 채널로
#   판매·금융·예비 = 0 (요율/차입 모두 0)
#   총지출 = 100 + 200 + 50 = 350
#   이익   = 420 − 350 = 70
#   margin_on_revenue = 70/420 = 1/6 = 0.16666… (16.67%)
#   margin_on_cost    = 70/350 = 0.2 (20%)
def dev_case_001():
    return {
        "revenue": {
            "units": [{"name": "X", "count": 1, "supply_m2": 1, "price_per_m2": 420}],
            "sell_through": 1.0,
            "other_income": 0,
        },
        "cost": {
            "land": {"purchase": 100, "acq_tax_rate": 0.0, "misc_rate": 0.0},
            "construction": {"gfa_m2": 1, "unit_cost_per_m2": 200},
            "indirect_rate": 0.25,          # 200 × 0.25 = 50 (=기타)
            "marketing_rate": 0.0,
            "contingency_rate": 0.0,
        },
        "finance": {
            "equity": 350,
            "bridge": {"amount": 0, "rate": 0.0, "months": 0},
            "pf": {"amount": 0, "rate": 0.0, "months": 0, "drawdown": 0.0},
            "fee_rate": 0.0,
        },
        "schedule": {"months_total": 12},
        "discount_rate": 0.08,
    }


def test_dev_001_revenue_is_420():
    assert run_feasibility(dev_case_001())["revenue_total"] == 420


def test_dev_001_cost_breakdown_golden():
    c = run_feasibility(dev_case_001())["cost"]
    assert c["land"] == 100          # 토지비 (세금 0)
    assert c["construction"] == 200  # 공사비
    assert c["indirect"] == 50       # 기타(간접비)
    assert c["marketing"] == 0
    assert c["finance"] == 0         # 금융비 0 (무차입)
    assert c["contingency"] == 0


def test_dev_001_cost_total_is_350():
    assert run_feasibility(dev_case_001())["cost_total"] == 350


def test_dev_001_profit_is_70():
    assert run_feasibility(dev_case_001())["profit"] == 70


def test_dev_001_margins_golden():
    r = run_feasibility(dev_case_001())
    # 이익률 16.67% = 70/420 = 1/6
    assert r["margin_on_revenue"] == pytest.approx(1 / 6, abs=1e-12)
    assert round(r["margin_on_revenue"] * 100, 2) == 16.67
    # 비용 대비 이익률 = 70/350 = 20%
    assert r["margin_on_cost"] == pytest.approx(0.20, abs=1e-12)


# =========================================================================== #
# CASE-INCOME-001 — 수익형 자본환원(cap rate) 가치평가
# =========================================================================== #
# 가치 = NOI ÷ (cap/100).  NOI 10억·cap 5% → 1e9 / 0.05 = 2e10 (200억).
# 이 산식은 cases.build_inputs_from_state (및 calc-ui.js buildInputs) 의 실경로에 있다.
def _value_of(noi, cap_pct):
    """수익형 매각가치 = NOI ÷ (cap rate).  (cases.py:113 · calc-ui.js:172 산식)"""
    return noi / (cap_pct / 100)


def test_income_001_valuation_formula_golden():
    # 손계산 앵커: NOI 10억, cap 5% → 200억
    assert _value_of(1_000_000_000, 5) == 20_000_000_000


def _office_state(cap=5.0):
    """수익형(오피스) 상태 — vacancy·opex 0 으로 NOI 산식을 단순화한 실경로 입력."""
    return {
        "land_area": 3000, "zone": "CG", "nb_ratio": 0, "avg_supply": 84.9,
        "asset": "office", "eff_ratio": 65, "rent_py": 11, "vacancy": 0, "opex": 0,
        "cap": cap,
        "sell_through": 100, "land_eok": 200, "unit_cost_py": 700, "months": 40,
        "indirect": 6, "marketing": 1.5, "contingency": 1,
        "equity_eok": 300, "bridge_eok": 300, "bridge_rate": 8, "bridge_mo": 10,
        "pf_eok": 900, "pf_rate": 6, "pf_draw": 55, "fee": 1.5,
    }


def _noi_independent(s):
    """문서화된 NOI 산식을 엔진과 독립적으로 재현(손계산 검산용).

    NOI = 임대면적(평) × 월임대료(만원)×1e4 × 12 × (1−공실) × (1−경비율)
    임대면적(평) = buildable_gfa_m2 × eff_ratio ÷ PY
    """
    zi = zoning.derive(s["land_area"], s["zone"], {
        "mix": {"residential": 1 - s["nb_ratio"] / 100,
                "neighborhood": s["nb_ratio"] / 100},
        "avg_supply_m2": s["avg_supply"]})
    nra_py = zi["buildable_gfa_m2"] * (s["eff_ratio"] / 100) / PY
    return (nra_py * s["rent_py"] * 1e4 * 12
            * (1 - s["vacancy"] / 100) * (1 - s["opex"] / 100))


def test_income_001_engine_uses_cap_valuation():
    """엔진 실경로(build_inputs_from_state)가 가치 = NOI/(cap/100) 을 쓰는지 검증.

    exit_value(엔진) 를, 독립 재현한 NOI 에 자본환원 산식을 적용한 값과 대조한다.
    엔진이 곱셈/÷100 누락 등으로 산식을 틀리면 여기서 실패한다.
    """
    s = _office_state(cap=5.0)
    inp = build_inputs_from_state(s, "신축분양")
    exit_value = inp["revenue"]["units"][0]["price_per_m2"]   # 엔진이 편성한 매각가치
    noi = _noi_independent(s)                                  # 독립 재현 NOI
    assert exit_value == pytest.approx(_value_of(noi, s["cap"]), rel=1e-12)
    # cap 5% → 가치배수 정확히 20배
    assert exit_value == pytest.approx(noi * 20, rel=1e-12)


def test_income_001_value_flows_to_revenue_and_terminal():
    """매각가치가 총수입으로 전달되고, terminal 스케줄로 준공 분기에 일시 유입."""
    s = _office_state(cap=5.0)
    inp = build_inputs_from_state(s, "신축분양")
    exit_value = inp["revenue"]["units"][0]["price_per_m2"]
    r = run_feasibility(inp)
    assert r["revenue_total"] == pytest.approx(exit_value, rel=1e-12)
    cf = r["cashflow_quarterly"]
    # terminal: 마지막 분기에 매출 전액 유입 → 유일한 양(+) 분기, 앞 분기는 모두 유출
    assert cf[-1] > 0
    assert all(c < 0 for c in cf[:-1])


def test_income_001_cap_inverse_monotonic():
    """cap 이 낮을수록 가치가 크다(÷cap). cap 4% 가치 > cap 5% 가치."""
    v5 = build_inputs_from_state(_office_state(5.0), "신축분양")["revenue"]["units"][0]["price_per_m2"]
    v4 = build_inputs_from_state(_office_state(4.0), "신축분양")["revenue"]["units"][0]["price_per_m2"]
    assert v4 > v5
    # 동일 NOI 이므로 비율은 정확히 5/4 = 1.25
    assert v4 / v5 == pytest.approx(5 / 4, rel=1e-12)


# =========================================================================== #
# CASE-IRR-001 / CASE-NPV-001 — 외부 검증값 대조
# =========================================================================== #
def test_npv_001_at_zero_is_500():
    # 분기이율 0 → 단순 합
    assert compute_npv(IRR_CF, 0.0) == pytest.approx(GOLDEN_NPV_AT_ZERO, abs=1e-9)


def test_npv_001_at_10pct_quarter_golden():
    # dr = 1.1^4 − 1 → 분기이율 정확히 10% → 500/1.1+500/1.21+500/1.331−1000
    npv = compute_npv(IRR_CF, DR_ANNUAL_FOR_10PCT_Q)
    assert npv == pytest.approx(GOLDEN_NPV_AT_10PCT_Q, abs=1e-6)
    assert round(npv, 4) == 243.4260


def test_irr_001_per_period_matches_excel():
    """엔진 연율값에서 기간 IRR 을 역산해 Excel 규약값(23.3752%)과 대조."""
    irr_annual = compute_irr_annual(IRR_CF)
    assert irr_annual is not None
    irr_pp = (1 + irr_annual) ** 0.25 - 1                      # 분기(기간) 이율 역산
    assert irr_pp == pytest.approx(GOLDEN_IRR_PER_PERIOD, abs=1e-7)
    assert round(irr_pp * 100, 3) == 23.375                    # Excel IRR 23.375%


def test_irr_001_annualized_golden():
    """엔진이 반환하는 연율값 자체가 (1+기간이율)^4−1 골든과 일치."""
    irr_annual = compute_irr_annual(IRR_CF)
    assert irr_annual == pytest.approx(GOLDEN_IRR_ANNUAL, abs=1e-6)
    # 근 검증: 역산한 기간이율에서 NPV 잔차 ≈ 0
    irr_pp = (1 + irr_annual) ** 0.25 - 1
    residual = sum(cf / (1 + irr_pp) ** i for i, cf in enumerate(IRR_CF))
    assert residual == pytest.approx(0.0, abs=1e-6)


# =========================================================================== #
# JS 교차구현 골든 — 동일 골든 리터럴을 site/js/feasibility.js 로도 대조
# (패리티가 아니라 절대값: JS 도 옳은지 확인)
# =========================================================================== #
import shutil
NODE = shutil.which("node") or "/opt/homebrew/bin/node"
JS_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "site", "js", "feasibility.js")
)


def _run_js_golden():
    """node 로 JS 엔진의 골든 출력(DEV·NPV·IRR)을 한 번에 회수."""
    runner = (
        "require(" + repr(JS_PATH).replace("'", '"') + ");"
        "const F=global.Feasibility;"
        "const CF=[-1000,500,500,500];"
        "const dev=JSON.parse(process.argv[1]);"
        "const r=F.run(dev);"
        "process.stdout.write(JSON.stringify({"
        "  dev_revenue:r.revenue_total, dev_profit:r.profit,"
        "  dev_mor:r.margin_on_revenue, dev_moc:r.margin_on_cost, dev_cost:r.cost,"
        "  npv0:F.compute_npv(CF,0.0), npv10:F.compute_npv(CF,0.4641),"
        "  irr_annual:F.compute_irr_annual(CF)"
        "}));"
    )
    import json
    proc = subprocess.run(
        [NODE, "-e", runner, json.dumps(dev_case_001())],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError("node 실행 실패:\n" + proc.stderr)
    return json.loads(proc.stdout)


@pytest.mark.skipif(not os.path.exists(NODE), reason="node 미설치 — JS 골든 생략")
def test_js_golden_matches_hand_calc():
    js = _run_js_golden()
    # CASE-DEV-001
    assert js["dev_revenue"] == 420
    assert js["dev_profit"] == 70
    assert js["dev_mor"] == pytest.approx(1 / 6, abs=1e-12)
    assert js["dev_moc"] == pytest.approx(0.20, abs=1e-12)
    assert js["dev_cost"]["land"] == 100
    assert js["dev_cost"]["construction"] == 200
    assert js["dev_cost"]["indirect"] == 50
    assert js["dev_cost"]["finance"] == 0
    # CASE-NPV-001
    assert js["npv0"] == pytest.approx(GOLDEN_NPV_AT_ZERO, abs=1e-9)
    assert js["npv10"] == pytest.approx(GOLDEN_NPV_AT_10PCT_Q, abs=1e-6)
    # CASE-IRR-001
    assert js["irr_annual"] == pytest.approx(GOLDEN_IRR_ANNUAL, abs=1e-6)
    irr_pp = (1 + js["irr_annual"]) ** 0.25 - 1
    assert irr_pp == pytest.approx(GOLDEN_IRR_PER_PERIOD, abs=1e-7)
