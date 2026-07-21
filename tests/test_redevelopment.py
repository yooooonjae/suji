"""정비사업(재개발·재건축·리모델링) 모드 테스트.

수기(hand-calc)로 검산한 소형 사례를 기대값으로 assert 한다.
비례율·권리가액·분담금의 손계산 값과 경계(현금청산·임대의무비율·모드 무시)를 검증한다.

핵심 수기 검산(재건축 소형):
  조합원 100명·현금청산 0 → 유효조합원 100
  조합원 세대당 분양가액 = 100㎡ × 10,000,000 = 1,000,000,000
  조합원분양수입 = 100 × 1,000,000,000 = 100,000,000,000
  일반분양(40세대 × 100㎡ × 10,000,000 × sell_through 1.0) = 40,000,000,000
  총수입 = 140,000,000,000
  공사비 = 25,000㎡ × 2,000,000 = 50,000,000,000  (토지비 0)
  철거비 = 5,000,000,000, 이주비이자 = 20,000,000,000 × 0.05 × 12/12 = 1,000,000,000
  현금청산비 = 80,000,000,000 × 0 = 0
  총사업비 = 56,000,000,000
  개발이익 = 140,000,000,000 − 56,000,000,000 = 84,000,000,000
  비례율   = 84,000,000,000 / 80,000,000,000 = 1.05
  권리가액(세대평균) = (80,000,000,000/100) × 1.05 = 800,000,000 × 1.05 = 840,000,000
  세대당분담금 = 1,000,000,000 − 840,000,000 = 160,000,000
"""

import pytest

from src.analysis.feasibility import run_feasibility


# --------------------------------------------------------------------------- #
# 입력 빌더
# --------------------------------------------------------------------------- #
def _base_cost(gfa_m2):
    """정비사업 관행: 토지비 0. 요율은 전부 0으로 두어 수기 검산을 단순화."""
    return {
        "land": {"purchase": 0, "acq_tax_rate": 0.0, "misc_rate": 0.0},
        "construction": {"gfa_m2": gfa_m2, "unit_cost_per_m2": 2_000_000},
        "indirect_rate": 0.0,
        "marketing_rate": 0.0,
        "contingency_rate": 0.0,
    }


def _no_debt_finance():
    return {
        "equity": 0,
        "bridge": {"amount": 0, "rate": 0.0, "months": 0},
        "pf": {"amount": 0, "rate": 0.0, "months": 0, "drawdown": 0.0},
        "fee_rate": 0.0,
    }


def rebuild_case():
    """재건축 소형(현금청산 0·임대 없음) — 비례율 1.05 수기 검산."""
    return {
        "mode": "재건축",
        "revenue": {"sell_through": 1.0, "other_income": 0},
        "redevelopment": {
            "prior_asset_value": 80_000_000_000,
            "member_count": 100,
            "member_supply_m2": 100,
            "member_price_per_m2": 10_000_000,
            "general_units": [
                {"name": "G", "count": 40, "supply_m2": 100, "price_per_m2": 10_000_000},
            ],
            "relocation_loan": {"amount": 20_000_000_000, "rate": 0.05, "months": 12},
            "demolition_cost": 5_000_000_000,
        },
        "cost": _base_cost(25_000),
        "finance": _no_debt_finance(),
        "schedule": {"months_total": 24},
        "discount_rate": 0.08,
    }


def redevelopment_case():
    """재개발 소형(현금청산 0.3·임대의무 0.2) — 비례율 0.75 수기 검산.

      유효조합원 = 100 × (1−0.3) = 70
      조합원분양수입 = 70 × (100×10,000,000) = 70,000,000,000
      일반분양 = (100×100×10,000,000) × 1.0 × (1−0.2) = 80,000,000,000
      총수입 = 150,000,000,000
      공사비 = 30,000 × 2,000,000 = 60,000,000,000
      철거 5,000,000,000 + 이주비이자 1,000,000,000
      현금청산비 = 80,000,000,000 × 0.3 = 24,000,000,000
      총사업비 = 90,000,000,000
      이익 = 60,000,000,000 → 비례율 = 60,000,000,000/80,000,000,000 = 0.75
      권리가액 = 800,000,000 × 0.75 = 600,000,000
      분담금 = 1,000,000,000 − 600,000,000 = 400,000,000
    """
    return {
        "mode": "재개발",
        "revenue": {"sell_through": 1.0, "other_income": 0},
        "redevelopment": {
            "prior_asset_value": 80_000_000_000,
            "member_count": 100,
            "member_supply_m2": 100,
            "member_price_per_m2": 10_000_000,
            "general_units": [
                {"name": "G", "count": 100, "supply_m2": 100, "price_per_m2": 10_000_000},
            ],
            "relocation_loan": {"amount": 20_000_000_000, "rate": 0.05, "months": 12},
            "demolition_cost": 5_000_000_000,
            "rental_ratio": 0.2,
            "cash_settlement_ratio": 0.3,
        },
        "cost": _base_cost(30_000),
        "finance": _no_debt_finance(),
        "schedule": {"months_total": 24},
        "discount_rate": 0.08,
    }


def shinchuk_case():
    """신축분양 기본 사례(mode 미지정)."""
    return {
        "revenue": {
            "units": [
                {"name": "A", "count": 10, "supply_m2": 100, "price_per_m2": 10_000_000},
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


# --------------------------------------------------------------------------- #
# 재건축 수기 검산
# --------------------------------------------------------------------------- #
def test_rebuild_revenue_total():
    r = run_feasibility(rebuild_case())
    assert r["revenue_total"] == 140_000_000_000


def test_rebuild_cost_extras():
    c = run_feasibility(rebuild_case())["cost"]
    assert c["land"] == 0                              # 토지비 0 허용
    assert c["construction"] == pytest.approx(50_000_000_000)
    assert c["demolition"] == 5_000_000_000
    assert c["relocation_interest"] == pytest.approx(1_000_000_000)
    assert c["cash_settlement"] == 0                   # ratio 0


def test_rebuild_cost_total_and_profit():
    r = run_feasibility(rebuild_case())
    assert r["cost_total"] == pytest.approx(56_000_000_000)
    assert r["profit"] == pytest.approx(84_000_000_000)


def test_rebuild_proportion_rate():
    r = run_feasibility(rebuild_case())
    assert r["proportion_rate"] == pytest.approx(1.05)   # 소수 표기(‰ 아님)


def test_rebuild_rights_value_and_contribution():
    r = run_feasibility(rebuild_case())
    assert r["rights_value"] == pytest.approx(840_000_000)       # 세대 평균
    assert r["member_contribution"] == pytest.approx(160_000_000)  # 세대당


# --------------------------------------------------------------------------- #
# 재개발: 현금청산 + 임대의무비율
# --------------------------------------------------------------------------- #
def test_redevelopment_revenue_with_rental_and_settlement():
    r = run_feasibility(redevelopment_case())
    # 조합원 70 × 1e9 + 일반 100e9×0.8 = 70e9 + 80e9
    assert r["revenue_total"] == pytest.approx(150_000_000_000)


def test_redevelopment_cash_settlement_cost():
    c = run_feasibility(redevelopment_case())["cost"]
    assert c["cash_settlement"] == pytest.approx(24_000_000_000)


def test_redevelopment_proportion_and_contribution():
    r = run_feasibility(redevelopment_case())
    assert r["proportion_rate"] == pytest.approx(0.75)
    assert r["rights_value"] == pytest.approx(600_000_000)
    assert r["member_contribution"] == pytest.approx(400_000_000)


# --------------------------------------------------------------------------- #
# 경계: rental_ratio 는 재개발만 적용
# --------------------------------------------------------------------------- #
def test_rental_ratio_ignored_in_rebuild():
    base = run_feasibility(rebuild_case())
    with_rental = rebuild_case()
    with_rental["redevelopment"]["rental_ratio"] = 0.5  # 재건축엔 무시돼야 함
    r = run_feasibility(with_rental)
    assert r["revenue_total"] == base["revenue_total"]   # 일반분양 미차감


def test_rental_ratio_applied_in_redevelopment():
    with_rental = redevelopment_case()
    no_rental = redevelopment_case()
    no_rental["redevelopment"]["rental_ratio"] = 0.0
    r_with = run_feasibility(with_rental)
    r_without = run_feasibility(no_rental)
    # 임대 20% 차감분 = 일반 100e9 × 0.2 = 20e9 만큼 총수입 감소
    assert r_without["revenue_total"] - r_with["revenue_total"] == pytest.approx(20_000_000_000)


# --------------------------------------------------------------------------- #
# 경계: cash_settlement_ratio 0 vs 0.3
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("ratio,eff_member_rev,settle_cost", [
    (0.0, 100_000_000_000, 0),
    (0.3, 70_000_000_000, 24_000_000_000),
])
def test_cash_settlement_ratio_boundary(ratio, eff_member_rev, settle_cost):
    case = rebuild_case()
    case["redevelopment"]["cash_settlement_ratio"] = ratio
    r = run_feasibility(case)
    # 조합원분양수입 = 유효조합원수 × 세대당분양가액
    member_part = r["revenue_total"] - 40_000_000_000  # 일반분양 40e9 고정
    assert member_part == pytest.approx(eff_member_rev)
    assert r["cost"]["cash_settlement"] == pytest.approx(settle_cost)


# --------------------------------------------------------------------------- #
# 경계: 신축분양 모드는 redevelopment 블록 무시 + 새 키 null
# --------------------------------------------------------------------------- #
def test_shinchuk_new_keys_null():
    r = run_feasibility(shinchuk_case())
    assert r["proportion_rate"] is None
    assert r["rights_value"] is None
    assert r["member_contribution"] is None
    # cost dict 는 기존 6키만 (정비사업 키 없음)
    assert set(r["cost"].keys()) == {
        "land", "construction", "indirect", "marketing", "finance", "contingency"
    }


def test_shinchuk_ignores_redevelopment_block():
    base = run_feasibility(shinchuk_case())
    with_block = shinchuk_case()  # mode 미지정(=신축분양)
    with_block["redevelopment"] = {
        "prior_asset_value": 80_000_000_000,
        "member_count": 100,
        "member_supply_m2": 100,
        "member_price_per_m2": 10_000_000,
        "general_units": [{"name": "X", "count": 999, "supply_m2": 200, "price_per_m2": 2e7}],
        "demolition_cost": 9e9,
    }
    r = run_feasibility(with_block)
    # 블록 무시 → 기존 신축 결과와 동일
    assert r["revenue_total"] == base["revenue_total"]
    assert r["cost_total"] == base["cost_total"]
    assert r["profit"] == base["profit"]
    assert r["proportion_rate"] is None


def test_explicit_shinchuk_mode_equivalent_to_default():
    default = run_feasibility(shinchuk_case())
    explicit = shinchuk_case()
    explicit["mode"] = "신축분양"
    r = run_feasibility(explicit)
    assert r["revenue_total"] == default["revenue_total"]
    assert r["profit"] == default["profit"]


# --------------------------------------------------------------------------- #
# 리모델링: 동일 산식(별도 특례 없음)
# --------------------------------------------------------------------------- #
def test_remodeling_uses_same_formula():
    case = rebuild_case()
    case["mode"] = "리모델링"
    # 증축분 소량 가정: 일반분양 4세대만
    case["redevelopment"]["general_units"] = [
        {"name": "G", "count": 4, "supply_m2": 100, "price_per_m2": 10_000_000},
    ]
    r = run_feasibility(case)
    # 총수입 = 조합원 100e9 + 일반 4e9
    assert r["revenue_total"] == pytest.approx(104_000_000_000)
    # 비례율 = (104e9 − 56e9)/80e9 = 48e9/80e9 = 0.6
    assert r["proportion_rate"] == pytest.approx(0.6)
    assert r["rights_value"] == pytest.approx(800_000_000 * 0.6)


def test_remodeling_rental_ratio_ignored():
    case = rebuild_case()
    case["mode"] = "리모델링"
    case["redevelopment"]["rental_ratio"] = 0.5  # 재개발 아님 → 무시
    r = run_feasibility(case)
    assert r["revenue_total"] == pytest.approx(140_000_000_000)


# --------------------------------------------------------------------------- #
# 현금흐름: 보존 + 현금청산비 q0 편성
# --------------------------------------------------------------------------- #
def test_redevelopment_cashflow_conserves_profit():
    r = run_feasibility(redevelopment_case())
    assert abs(sum(r["cashflow_quarterly"]) - r["profit"]) < 1.0


def test_cash_settlement_loaded_in_q0():
    """현금청산비는 q0 에 편성 → 현금청산 있는 경우 q0 유출이 그만큼 커진다."""
    with_settle = redevelopment_case()
    no_settle = redevelopment_case()
    no_settle["redevelopment"]["cash_settlement_ratio"] = 0.0
    # 유효조합원 변화로 수입이 달라지므로 q0 유출 절대비교 대신,
    # 현금청산비만큼 q0 가 낮아졌는지 델타로 확인하기 위해 조합원수입을 맞춘다.
    # → 유효조합원수 동일하게: no_settle 의 member_count 를 70 으로 축소
    no_settle["redevelopment"]["member_count"] = 70
    cf_with = run_feasibility(with_settle)["cashflow_quarterly"]
    cf_no = run_feasibility(no_settle)["cashflow_quarterly"]
    # q0 차이 = 현금청산비 24e9 (다른 유출·유입은 동일 스케줄)
    assert (cf_no[0] - cf_with[0]) == pytest.approx(24_000_000_000)
