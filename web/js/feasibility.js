/**
 * 부동산 개발사업 수지분석 모델 코어 (JavaScript 이식본).
 *
 * src/analysis/feasibility.py 의 1:1 이식이다. 동일 수식·동일 스키마·동일 연산
 * 순서를 유지하여 Python 결과와 부동소수 수준까지 일치시킨다.
 *   - npv 는 스칼라(number), cost 만 dict(object)
 *   - Python None ↔ JS null
 *   - `x ** q` 는 Math.pow(x, q) 로 이식 (같은 libm pow → 비트 동일)
 *   - 합산은 좌→우 순서를 그대로 유지 (Python sum 과 동일)
 *
 * 브라우저/노드 겸용. import/export 없이 global.Feasibility 에 노출한다.
 * (아티팩트 인라인 삽입을 위해 모듈 구문 금지)
 */
(function (global) {
  "use strict";

  // 정비사업 모드(비-신축). rental_ratio 는 재개발에만 적용된다.
  var _REDEV_MODES = ["재개발", "재건축", "리모델링"];

  // ------------------------------------------------------------------ //
  // 보조: 좌→우 합산 (Python sum(iterable, 0) 과 동일 순서)
  // ------------------------------------------------------------------ //
  function _sum(arr) {
    var acc = 0;
    for (var i = 0; i < arr.length; i++) acc += arr[i];
    return acc;
  }

  // ------------------------------------------------------------------ //
  // 수입부
  // ------------------------------------------------------------------ //
  // 분양수입 계산.
  // 반환: {sales, other, total}
  //   sales = Σ(count × supply_m2 × price_per_m2) × sell_through
  //   total = sales + other_income
  function compute_revenue(revenue) {
    var gross = 0.0;
    var units = revenue.units || [];
    for (var i = 0; i < units.length; i++) {
      var u = units[i];
      gross += u.count * u.supply_m2 * u.price_per_m2;
    }
    // revenue.get("sell_through", 1.0): 키 없을 때만 기본값
    var sellThrough = revenue.sell_through === undefined ? 1.0 : revenue.sell_through;
    var sales = gross * sellThrough;
    // revenue.get("other_income", 0) or 0: falsy(0/None/undefined) → 0
    var other = revenue.other_income || 0;
    return { sales: sales, other: other, total: sales + other };
  }

  // ------------------------------------------------------------------ //
  // 지출부 (개별 순수 함수)
  // ------------------------------------------------------------------ //
  // 토지비 = purchase × (1 + acq_tax_rate + misc_rate)
  function compute_land_cost(land) {
    return land.purchase * (1 + land.acq_tax_rate + land.misc_rate);
  }

  // 공사비 = gfa_m2 × unit_cost_per_m2
  function compute_construction_cost(construction) {
    return construction.gfa_m2 * construction.unit_cost_per_m2;
  }

  // 금융비 = 브릿지 이자 + PF 이자 + 취급수수료
  //   브릿지 이자 = amount × rate × months/12
  //   PF 이자     = amount × drawdown × rate × months/12
  //   취급수수료   = (bridge.amount + pf.amount) × fee_rate
  function compute_finance_cost(finance) {
    var b = finance.bridge;
    var p = finance.pf;
    var bridge_interest = (b.amount * b.rate * b.months) / 12;
    var pf_interest = (p.amount * p.drawdown * p.rate * p.months) / 12;
    var fee = (b.amount + p.amount) * finance.fee_rate;
    return bridge_interest + pf_interest + fee;
  }

  // 지출 항목별 집계. 반환 키: land, construction, indirect, marketing,
  // finance, contingency (모두 원 단위). 예비비 base 는 직접비 합(토지+공사+간접).
  function compute_costs(cost, finance, revenue_total) {
    var land = compute_land_cost(cost.land);
    var construction = compute_construction_cost(cost.construction);
    var indirect = construction * cost.indirect_rate;
    var marketing = revenue_total * cost.marketing_rate;
    var finance_cost = compute_finance_cost(finance);
    var contingency = (land + construction + indirect) * cost.contingency_rate;
    return {
      land: land,
      construction: construction,
      indirect: indirect,
      marketing: marketing,
      finance: finance_cost,
      contingency: contingency,
    };
  }

  // ------------------------------------------------------------------ //
  // 분기 현금흐름
  // ------------------------------------------------------------------ //
  // 분기별 순현금흐름 리스트(cf_q, q=0..N) 생성.
  // 분기 수 Q = ceil(months_total/3), 마지막 분기 인덱스 N = Q-1.
  function compute_cashflow(sales, other_income, cost, months_total) {
    var quarters = Math.max(1, Math.ceil(months_total / 3));
    var last = quarters - 1; // 마지막 분기 인덱스 (N)

    var inflow = new Array(quarters);
    var outflow = new Array(quarters);
    for (var i = 0; i < quarters; i++) {
      inflow[i] = 0.0;
      outflow[i] = 0.0;
    }

    // --- 유입 ---
    inflow[0] += sales * 0.1; // 계약금 10%
    // middle = range(1, last) → q1..last-1
    var middleCount = last - 1; // len(range(1, last)) = max(0, last-1)
    if (middleCount < 0) middleCount = 0;
    if (middleCount > 0) {
      var each = (sales * 0.6) / middleCount; // 중도금 균등
      for (var q = 1; q < last; q++) {
        inflow[q] += each;
      }
    } else {
      inflow[last] += sales * 0.6; // 중간 분기 없음 → 마지막 분기
    }
    inflow[last] += sales * 0.3; // 잔금
    inflow[last] += other_income; // 기타수입

    // --- 유출 ---
    // 정비사업 전용 항목은 키 부재(신축분양) 시 0 → 결과 불변.
    var demolition = cost.demolition === undefined ? 0 : cost.demolition;
    var reloc_int = cost.relocation_interest === undefined ? 0 : cost.relocation_interest;
    var cash_settlement = cost.cash_settlement === undefined ? 0 : cost.cash_settlement;
    outflow[0] += cost.land; // 토지비 q0
    outflow[0] += cash_settlement; // 현금청산비 q0(정비사업)
    var even_direct =
      (cost.construction + cost.indirect + cost.contingency + demolition + reloc_int) / quarters;
    var even_finance = cost.finance / quarters;
    for (var q2 = 0; q2 < quarters; q2++) {
      outflow[q2] += even_direct + even_finance;
    }

    var total_inflow = _sum(inflow); // = 총수입
    if (total_inflow > 0) {
      // 판매비: 유입 비례 (0이면 판매비도 0)
      for (var q3 = 0; q3 < quarters; q3++) {
        outflow[q3] += cost.marketing * (inflow[q3] / total_inflow);
      }
    }

    var cf = new Array(quarters);
    for (var q4 = 0; q4 < quarters; q4++) {
      cf[q4] = inflow[q4] - outflow[q4];
    }
    return cf;
  }

  // ------------------------------------------------------------------ //
  // NPV / IRR
  // ------------------------------------------------------------------ //
  // NPV = Σ cf_q / (1 + r_q)^q,  r_q = (1 + discount_rate)^(1/4) − 1
  function compute_npv(cashflows, discount_rate) {
    var rq = Math.pow(1 + discount_rate, 0.25) - 1;
    var acc = 0;
    for (var q = 0; q < cashflows.length; q++) {
      acc += cashflows[q] / Math.pow(1 + rq, q);
    }
    return acc;
  }

  // 분기이율 rate 에서의 현재가치 합(내부 IRR 탐색용).
  function _npv_at(cashflows, rate) {
    var acc = 0;
    for (var q = 0; q < cashflows.length; q++) {
      acc += cashflows[q] / Math.pow(1 + rate, q);
    }
    return acc;
  }

  // 분기 IRR 을 이분법(범위 [-0.5, 1.0], 200회)으로 구해 연율화.
  // 반환: (1 + irr_q)^4 − 1. 부호 변화 없거나 범위 내 근 없으면 null.
  function compute_irr_annual(cashflows) {
    var nonzero = [];
    for (var i = 0; i < cashflows.length; i++) {
      if (cashflows[i] !== 0) nonzero.push(cashflows[i]);
    }
    if (
      nonzero.length === 0 ||
      nonzero.every(function (c) { return c > 0; }) ||
      nonzero.every(function (c) { return c < 0; })
    ) {
      return null; // 부호 변화 없음
    }

    var lo = -0.5;
    var hi = 1.0;
    var flo = _npv_at(cashflows, lo);
    var fhi = _npv_at(cashflows, hi);
    if (flo === 0) return Math.pow(1 + lo, 4) - 1;
    if (fhi === 0) return Math.pow(1 + hi, 4) - 1;
    if (flo * fhi > 0) return null; // 범위 내 근 없음

    for (var k = 0; k < 200; k++) {
      var mid = (lo + hi) / 2;
      var fmid = _npv_at(cashflows, mid);
      if (flo * fmid <= 0) {
        hi = mid;
      } else {
        lo = mid;
        flo = fmid;
      }
    }
    var irr_q = (lo + hi) / 2;
    return Math.pow(1 + irr_q, 4) - 1;
  }

  // ------------------------------------------------------------------ //
  // 정비사업(재개발·재건축·리모델링)
  // ------------------------------------------------------------------ //
  // 이주비 대여 이자 = amount × rate × months / 12 (이자만 사업비).
  function compute_relocation_interest(loan) {
    if (!loan) return 0.0;
    var amount = loan.amount === undefined ? 0 : loan.amount;
    var rate = loan.rate === undefined ? 0 : loan.rate;
    var months = loan.months === undefined ? 0 : loan.months;
    return (amount * rate * months) / 12;
  }

  // 정비사업 수입. 반환: {member, general, other, sales, total}.
  //   유효조합원수 = member_count × (1 − cash_settlement_ratio)
  //   member  = 유효조합원수 × member_supply_m2 × member_price_per_m2
  //   general = Σ(general_units)×sell_through, 재개발이면 ×(1 − rental_ratio)
  //   sales = member + general, other = other_income, total = sales + other
  function compute_redevelopment_revenue(redev, revenue, mode) {
    var cash_ratio = redev.cash_settlement_ratio || 0;
    var eff_members = redev.member_count * (1 - cash_ratio);
    var member_unit_price = redev.member_supply_m2 * redev.member_price_per_m2;
    var member = eff_members * member_unit_price;

    var sell_through = revenue.sell_through === undefined ? 1.0 : revenue.sell_through;
    var general_rev = compute_revenue({
      units: redev.general_units || [],
      sell_through: sell_through,
    });
    var rental_ratio = mode === "재개발" ? redev.rental_ratio || 0 : 0.0;
    var general = general_rev.sales * (1 - rental_ratio);

    var other = revenue.other_income || 0;
    var sales = member + general;
    return { member: member, general: general, other: other, sales: sales, total: sales + other };
  }

  // ------------------------------------------------------------------ //
  // 진입점
  // ------------------------------------------------------------------ //
  // 분모 0 이면 null, 아니면 나눗셈.
  function _safe_div(num, den) {
    return den === 0 ? null : num / den;
  }

  // 수지분석 실행. 입력·출력 스키마는 Python 과 동일.
  function run_feasibility(inputs) {
    var mode = inputs.mode === undefined ? "신축분양" : inputs.mode;
    var is_redev = _REDEV_MODES.indexOf(mode) !== -1;
    var revenue = inputs.revenue === undefined ? {} : inputs.revenue;

    // --- 수입 ---
    var rev, sales, other, revenue_total;
    if (is_redev) {
      var redev = inputs.redevelopment;
      rev = compute_redevelopment_revenue(redev, revenue, mode);
      sales = rev.sales;
      other = rev.other;
      revenue_total = rev.total;
    } else {
      rev = compute_revenue(revenue);
      sales = rev.sales;
      other = rev.other;
      revenue_total = rev.total;
    }

    // --- 지출 ---
    var cost = compute_costs(inputs.cost, inputs.finance, revenue_total);
    var costVals = [
      cost.land,
      cost.construction,
      cost.indirect,
      cost.marketing,
      cost.finance,
      cost.contingency,
    ];
    if (is_redev) {
      var redevC = inputs.redevelopment;
      var cash_ratio = redevC.cash_settlement_ratio || 0;
      cost.demolition = redevC.demolition_cost || 0;
      cost.relocation_interest = compute_relocation_interest(redevC.relocation_loan);
      cost.cash_settlement = redevC.prior_asset_value * cash_ratio;
      // sum 순서: 기존 6키 → demolition → relocation_interest → cash_settlement
      costVals.push(cost.demolition, cost.relocation_interest, cost.cash_settlement);
    }
    var cost_total = _sum(costVals);

    var profit = revenue_total - cost_total;

    // --- 정비사업 지표(비례율·권리가액·분담금) ---
    var proportion_rate = null;
    var rights_value = null;
    var member_contribution = null;
    if (is_redev) {
      var redevM = inputs.redevelopment;
      var prior = redevM.prior_asset_value;
      proportion_rate = _safe_div(profit, prior);
      var base_rights = _safe_div(prior, redevM.member_count);
      rights_value =
        proportion_rate === null || base_rights === null ? null : base_rights * proportion_rate;
      var member_unit_price = redevM.member_supply_m2 * redevM.member_price_per_m2;
      member_contribution = rights_value === null ? null : member_unit_price - rights_value;
    }

    var equity = inputs.finance.equity === undefined ? 0 : inputs.finance.equity;
    var months_total = inputs.schedule.months_total;
    var discount_rate = inputs.discount_rate === undefined ? 0.08 : inputs.discount_rate;

    var cashflows = compute_cashflow(sales, other, cost, months_total);

    return {
      revenue_total: revenue_total,
      cost: cost,
      cost_total: cost_total,
      profit: profit,
      margin_on_revenue: _safe_div(profit, revenue_total),
      margin_on_cost: _safe_div(profit, cost_total),
      roe: _safe_div(profit, equity),
      cashflow_quarterly: cashflows,
      npv: compute_npv(cashflows, discount_rate),
      irr_annual: compute_irr_annual(cashflows),
      proportion_rate: proportion_rate,
      rights_value: rights_value,
      member_contribution: member_contribution,
    };
  }

  // ------------------------------------------------------------------ //
  // 노출
  // ------------------------------------------------------------------ //
  global.Feasibility = {
    run: run_feasibility,
    compute_revenue: compute_revenue,
    compute_land_cost: compute_land_cost,
    compute_construction_cost: compute_construction_cost,
    compute_finance_cost: compute_finance_cost,
    compute_costs: compute_costs,
    compute_cashflow: compute_cashflow,
    compute_npv: compute_npv,
    compute_irr_annual: compute_irr_annual,
    compute_relocation_interest: compute_relocation_interest,
    compute_redevelopment_revenue: compute_redevelopment_revenue,
  };
})(typeof window !== "undefined" ? window : globalThis);
