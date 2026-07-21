"""부동산 개발사업 수지분석 모델 코어.

단위: 금액=원, 면적=㎡, 이율=소수(연이율). 이후 JS(site/js/feasibility.js)로
1:1 이식되므로 구조를 단순하게 유지하고, 각 계산 단계를 순수 함수로 분리한다.

수식 요약(신축분양 · 스펙 고정):
  분양수입   = Σ(count × supply_m2 × price_per_m2) × sell_through + other_income
  토지비     = purchase × (1 + acq_tax_rate + misc_rate)
  공사비     = gfa_m2 × unit_cost_per_m2
  간접비     = 공사비 × indirect_rate
  판매비     = 분양수입 × marketing_rate
  금융비     = bridge.amount×bridge.rate×bridge.months/12
             + pf.amount×pf.drawdown×pf.rate×pf.months/12
             + (bridge.amount + pf.amount) × fee_rate
  예비비     = (토지비 + 공사비 + 간접비) × contingency_rate
  총지출     = 토지+공사+간접+판매+금융+예비
  개발이익   = 총수입 − 총지출
  margin_on_revenue = 이익 / 총수입   (총수입 0 → None)
  margin_on_cost    = 이익 / 총지출   (총지출 0 → None)
  roe               = 이익 / equity   (equity 0 → None)
  NPV = Σ cf_q / (1 + r_q)^q,   r_q = (1 + discount_rate)^(1/4) − 1
  IRR(연율) = (1 + irr_q)^4 − 1,  irr_q 는 분기 현금흐름의 이분법 해

정비사업 모드(inputs["mode"] ∈ {"재개발","재건축","리모델링"}):
  inputs["redevelopment"] 블록을 추가로 읽어 조합원분양·비례율·분담금을 산출한다.
  유효조합원수  = member_count × (1 − cash_settlement_ratio)
  조합원분양수입 = 유효조합원수 × member_supply_m2 × member_price_per_m2
  일반분양수입   = Σ(general_units)×sell_through, 재개발이면 ×(1 − rental_ratio)
  총수입        = 조합원분양 + 일반분양 + other_income
  추가 사업비    = demolition_cost + 이주비이자(amount×rate×months/12)
                 + 현금청산비(prior_asset_value × cash_settlement_ratio)
  비례율         = (총수입 − 총사업비) / prior_asset_value   (소수 표기, 예 1.05)
  권리가액(평균) = (prior_asset_value / member_count) × 비례율
  세대당분담금   = (member_supply_m2 × member_price_per_m2) − 권리가액
  신축분양 모드에서는 proportion_rate·rights_value·member_contribution 이 None.
  (리모델링은 재건축과 동일 산식 — 증축분 general_units 만 소량, 별도 특례 없음)
"""

import math

# 정비사업 모드(비-신축). rental_ratio 는 재개발에만 적용된다.
_REDEV_MODES = ("재개발", "재건축", "리모델링")


# --------------------------------------------------------------------------- #
# 수입부
# --------------------------------------------------------------------------- #
def compute_revenue(revenue: dict) -> dict:
    """분양수입 계산.

    반환: {"sales": 분양분수입, "other": 기타수입, "total": 총수입}
      sales = Σ(count × supply_m2 × price_per_m2) × sell_through
      total = sales + other_income
    sales 와 other 를 분리해 반환하는 이유는 현금흐름에서 10/60/30 분납은
    sales(분양분)에만 적용하고 기타수입은 마지막 분기에 별도 유입시키기 때문이다.
    """
    gross = 0.0
    for u in revenue.get("units", []):
        gross += u["count"] * u["supply_m2"] * u["price_per_m2"]
    sales = gross * revenue.get("sell_through", 1.0)
    other = revenue.get("other_income", 0) or 0
    return {"sales": sales, "other": other, "total": sales + other}


# --------------------------------------------------------------------------- #
# 지출부 (개별 순수 함수)
# --------------------------------------------------------------------------- #
def compute_land_cost(land: dict) -> float:
    """토지비 = purchase × (1 + acq_tax_rate + misc_rate)."""
    return land["purchase"] * (1 + land["acq_tax_rate"] + land["misc_rate"])


def compute_construction_cost(construction: dict) -> float:
    """공사비 = gfa_m2 × unit_cost_per_m2."""
    return construction["gfa_m2"] * construction["unit_cost_per_m2"]


def compute_finance_cost(finance: dict) -> float:
    """금융비 = 브릿지 이자 + PF 이자 + 취급수수료.

      브릿지 이자 = amount × rate × months/12
      PF 이자     = amount × drawdown × rate × months/12   (인출률 반영)
      취급수수료   = (bridge.amount + pf.amount) × fee_rate
    """
    b = finance["bridge"]
    p = finance["pf"]
    bridge_interest = b["amount"] * b["rate"] * b["months"] / 12
    pf_interest = p["amount"] * p["drawdown"] * p["rate"] * p["months"] / 12
    fee = (b["amount"] + p["amount"]) * finance["fee_rate"]
    return bridge_interest + pf_interest + fee


def compute_costs(cost: dict, finance: dict, revenue_total: float) -> dict:
    """지출 항목별 집계. 반환 키: land, construction, indirect, marketing,
    finance, contingency (모두 원 단위).

    예비비 base 는 직접비 합(토지+공사+간접)이며 판매비·금융비는 제외한다.
    """
    land = compute_land_cost(cost["land"])
    construction = compute_construction_cost(cost["construction"])
    indirect = construction * cost["indirect_rate"]
    marketing = revenue_total * cost["marketing_rate"]
    finance_cost = compute_finance_cost(finance)
    contingency = (land + construction + indirect) * cost["contingency_rate"]
    return {
        "land": land,
        "construction": construction,
        "indirect": indirect,
        "marketing": marketing,
        "finance": finance_cost,
        "contingency": contingency,
    }


# --------------------------------------------------------------------------- #
# 분기 현금흐름
# --------------------------------------------------------------------------- #
def compute_cashflow(sales: float, other_income: float, cost: dict, months_total: int) -> list:
    """분기별 순현금흐름 리스트(cf_q, q=0..N) 생성.

    분기 수 Q = ceil(months_total/3), 인덱스 q=0..N (N = Q−1, 마지막 분기).

    유입:
      계약금 10%           → q0
      중도금 60%           → q1..N-1 균등 (중간 분기 없으면 마지막 분기로 이월)
      잔금   30%           → 마지막 분기(qN)
      기타수입(other)      → 마지막 분기(qN)
      (10/60/30 은 sales 기준, other 는 별도)

    유출:
      토지비               → q0
      현금청산비            → q0 (정비사업, 키 없으면 0)
      공사비+간접비+예비비  → 전 분기 균등
      철거비+이주비이자     → 전 분기 균등 (정비사업, 키 없으면 0)
      판매비               → 분양수입 유입 분기에 비례
      금융비               → 전 분기 균등

    정비사업 가정: 조합원분양수입도 일반분양과 동일한 10/60/30 스케줄로 본다
    (sales 인자에 조합원분양+일반분양을 합산해 전달). 철거비·이주비이자는 전 분기
    균등, 현금청산비는 착공 시점(q0) 일시 유출로 가정한다.

    설계상 Σ유입 = sales + other = 총수입, Σ유출 = 총사업비 이 성립하므로
    Σcf = 이익(부동소수 오차 제외)이 보장된다.
    """
    quarters = max(1, math.ceil(months_total / 3))
    last = quarters - 1  # 마지막 분기 인덱스 (N)

    inflow = [0.0] * quarters
    outflow = [0.0] * quarters

    # --- 유입 ---
    inflow[0] += sales * 0.10                      # 계약금
    middle = list(range(1, last))                  # q1..N-1
    if middle:
        each = sales * 0.60 / len(middle)          # 중도금 균등
        for q in middle:
            inflow[q] += each
    else:
        inflow[last] += sales * 0.60               # 중간 분기 없음 → 마지막 분기
    inflow[last] += sales * 0.30                    # 잔금
    inflow[last] += other_income                    # 기타수입

    # --- 유출 ---
    # 정비사업 전용 항목은 .get 으로 읽어 신축분양(키 부재)에선 0 → 결과 불변.
    outflow[0] += cost["land"]                      # 토지비 q0
    outflow[0] += cost.get("cash_settlement", 0)    # 현금청산비 q0(정비사업)
    even_direct = (cost["construction"] + cost["indirect"] + cost["contingency"]
                   + cost.get("demolition", 0) + cost.get("relocation_interest", 0)) / quarters
    even_finance = cost["finance"] / quarters
    for q in range(quarters):
        outflow[q] += even_direct + even_finance

    total_inflow = sum(inflow)                      # = 총수입
    if total_inflow > 0:                            # 판매비: 유입 비례 (0이면 판매비도 0)
        for q in range(quarters):
            outflow[q] += cost["marketing"] * (inflow[q] / total_inflow)

    return [inflow[q] - outflow[q] for q in range(quarters)]


# --------------------------------------------------------------------------- #
# NPV / IRR
# --------------------------------------------------------------------------- #
def compute_npv(cashflows: list, discount_rate: float) -> float:
    """NPV = Σ cf_q / (1 + r_q)^q,  r_q = (1 + discount_rate)^(1/4) − 1."""
    rq = (1 + discount_rate) ** 0.25 - 1
    return sum(cf / (1 + rq) ** q for q, cf in enumerate(cashflows))


def _npv_at(cashflows: list, rate: float) -> float:
    """분기이율 rate 에서의 현재가치 합(내부 IRR 탐색용)."""
    return sum(cf / (1 + rate) ** q for q, cf in enumerate(cashflows))


def compute_irr_annual(cashflows: list):
    """분기 IRR 을 이분법(범위 [-0.5, 1.0], 200회)으로 구해 연율화.

    반환: (1 + irr_q)^4 − 1. 현금흐름에 부호 변화가 없거나 해당 범위에서
    부호가 잡히지 않으면 None.
    """
    nonzero = [c for c in cashflows if c != 0]
    if not nonzero or all(c > 0 for c in nonzero) or all(c < 0 for c in nonzero):
        return None  # 부호 변화 없음

    lo, hi = -0.5, 1.0
    flo = _npv_at(cashflows, lo)
    fhi = _npv_at(cashflows, hi)
    if flo == 0:
        return (1 + lo) ** 4 - 1
    if fhi == 0:
        return (1 + hi) ** 4 - 1
    if flo * fhi > 0:
        return None  # 범위 내 근 없음

    for _ in range(200):
        mid = (lo + hi) / 2
        fmid = _npv_at(cashflows, mid)
        if flo * fmid <= 0:
            hi = mid
        else:
            lo, flo = mid, fmid
    irr_q = (lo + hi) / 2
    return (1 + irr_q) ** 4 - 1


# --------------------------------------------------------------------------- #
# 정비사업(재개발·재건축·리모델링)
# --------------------------------------------------------------------------- #
def compute_relocation_interest(loan: dict) -> float:
    """이주비 대여 이자 = amount × rate × months / 12 (원금은 사업비 아님, 이자만)."""
    if not loan:
        return 0.0
    return loan.get("amount", 0) * loan.get("rate", 0) * loan.get("months", 0) / 12


def compute_redevelopment_revenue(redev: dict, revenue: dict, mode: str) -> dict:
    """정비사업 수입 계산. 반환: {"member", "general", "other", "sales", "total"}.

      유효조합원수  = member_count × (1 − cash_settlement_ratio)
      member(조합원분양) = 유효조합원수 × member_supply_m2 × member_price_per_m2
      general(일반분양)  = Σ(general_units)×sell_through, 재개발이면 ×(1 − rental_ratio)
      sales = member + general (현금흐름 10/60/30 대상), other = other_income
      total = member + general + other
    rental_ratio 는 재개발 모드에서만 반영한다(재건축·리모델링은 무시).
    """
    cash_ratio = redev.get("cash_settlement_ratio", 0) or 0
    eff_members = redev["member_count"] * (1 - cash_ratio)
    member_unit_price = redev["member_supply_m2"] * redev["member_price_per_m2"]
    member = eff_members * member_unit_price

    general_rev = compute_revenue(
        {"units": redev.get("general_units", []),
         "sell_through": revenue.get("sell_through", 1.0)}
    )
    rental_ratio = (redev.get("rental_ratio", 0) or 0) if mode == "재개발" else 0.0
    general = general_rev["sales"] * (1 - rental_ratio)

    other = revenue.get("other_income", 0) or 0
    sales = member + general
    return {"member": member, "general": general, "other": other,
            "sales": sales, "total": sales + other}


# --------------------------------------------------------------------------- #
# 진입점
# --------------------------------------------------------------------------- #
def _safe_div(num: float, den: float):
    """분모 0 이면 None, 아니면 나눗셈."""
    return None if den == 0 else num / den


def run_feasibility(inputs: dict) -> dict:
    """수지분석 실행. 입력·출력 스키마는 스펙에 고정(JS 이식 의존).

    inputs["mode"] 로 신축분양(기본)·재개발·재건축·리모델링을 선택한다.

    출력 키:
      revenue_total, cost{...}, cost_total, profit,
      margin_on_revenue, margin_on_cost, roe, cashflow_quarterly(list), npv, irr_annual,
      proportion_rate, rights_value, member_contribution
    정비사업 모드에서 cost 에 demolition·relocation_interest·cash_settlement 키가
    추가되며, 신축분양 모드에서는 마지막 3개 지표가 None 이다.
    """
    mode = inputs.get("mode", "신축분양")
    is_redev = mode in _REDEV_MODES
    revenue = inputs.get("revenue", {})

    # --- 수입 ---
    if is_redev:
        redev = inputs["redevelopment"]
        rev = compute_redevelopment_revenue(redev, revenue, mode)
        sales, other = rev["sales"], rev["other"]
        revenue_total = rev["total"]
    else:
        rev = compute_revenue(revenue)
        sales, other = rev["sales"], rev["other"]
        revenue_total = rev["total"]

    # --- 지출 ---
    cost = compute_costs(inputs["cost"], inputs["finance"], revenue_total)
    if is_redev:
        redev = inputs["redevelopment"]
        cash_ratio = redev.get("cash_settlement_ratio", 0) or 0
        cost["demolition"] = redev.get("demolition_cost", 0) or 0
        cost["relocation_interest"] = compute_relocation_interest(redev.get("relocation_loan"))
        cost["cash_settlement"] = redev["prior_asset_value"] * cash_ratio
    cost_total = sum(cost.values())

    profit = revenue_total - cost_total

    # --- 정비사업 지표(비례율·권리가액·분담금) ---
    if is_redev:
        redev = inputs["redevelopment"]
        prior = redev["prior_asset_value"]
        proportion_rate = _safe_div(profit, prior)
        base_rights = _safe_div(prior, redev["member_count"])
        rights_value = (None if proportion_rate is None or base_rights is None
                        else base_rights * proportion_rate)
        member_unit_price = redev["member_supply_m2"] * redev["member_price_per_m2"]
        member_contribution = None if rights_value is None else member_unit_price - rights_value
    else:
        proportion_rate = None
        rights_value = None
        member_contribution = None

    equity = inputs["finance"].get("equity", 0)
    months_total = inputs["schedule"]["months_total"]
    discount_rate = inputs.get("discount_rate", 0.08)

    cashflows = compute_cashflow(sales, other, cost, months_total)

    return {
        "revenue_total": revenue_total,
        "cost": cost,
        "cost_total": cost_total,
        "profit": profit,
        "margin_on_revenue": _safe_div(profit, revenue_total),
        "margin_on_cost": _safe_div(profit, cost_total),
        "roe": _safe_div(profit, equity),
        "cashflow_quarterly": cashflows,
        "npv": compute_npv(cashflows, discount_rate),
        "irr_annual": compute_irr_annual(cashflows),
        "proportion_rate": proportion_rate,
        "rights_value": rights_value,
        "member_contribution": member_contribution,
    }
