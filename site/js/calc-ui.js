/* ============================================================
   계산기 UI — 토지 스텝(Zoning) → 수지 입력 → Feasibility.run
   4모드(신축분양·재개발·재건축·리모델링) · 시나리오 A/B
   ============================================================ */
(function (global) {
  "use strict";
  const F = global.Feasibility, Z = global.Zoning, C = global.Charts;
  const $ = s => document.querySelector(s);
  const fmt = C.fmt;
  const EOK = 1e8; // 억원

  /* ---------- 상태 ---------- */
  let mode = "신축분양";
  let snapshotA = null;
  const st = { // 입력 상태 (UI 단위: 억원·평당만원 등 실무 단위, 계산 직전 원·㎡ 변환)
    land_area: 10000, zone: "R2", nb_ratio: 0,                        // 토지
    asset: "apt",                                                     // 자산유형: apt·office·retail
    avg_supply: 84.9, price_py: 2400, sell_through: 95, units_override: 0,  // 분양 (평당만원)
    rent_py: 11, vacancy: 5, opex: 27, cap: 4.2, eff_ratio: 65,       // 수익형(오피스·상업)
    land_eok: 800, unit_cost_py: 780, months: 36,                     // 원가 (평당만원 공사비)
    indirect: 6, marketing: 3.5, contingency: 1,                      // 요율 %
    equity_eok: 300, bridge_eok: 600, bridge_rate: 8.5, bridge_mo: 10,
    pf_eok: 2000, pf_rate: 6.5, pf_draw: 55, fee: 1.5,
    // 정비사업
    prior_eok: 1500, members: 500, mem_supply: 84.9, mem_price_py: 2000,
    gen_units: 200, relo_eok: 800, relo_rate: 5.0, demo_eok: 150,
    rental: 15, cashout: 5,
  };
  const PY = 3.305785; // ㎡/평

  // 정밀: 평당 X만원 = X*10000 원/평 = X*10000/3.305785 원/㎡
  function pyman_to_wonm2(x) { return (x * 10000) / PY; }

  /* ---------- 프리셋 (사례 데이터 기반 — cases.json에서 주입) ---------- */
  let presets = {};
  function applyPreset(p) { Object.assign(st, p); syncInputs(); recalc(); }

  /* ---------- 입력 구성 ---------- */
  const FIELDS = {
    공통토지: [
      ["asset", "자산 유형", "select", [["apt", "공동주택 (분양)"], ["office", "오피스 (임대 후 매각)"], ["retail", "상업시설 (임대 후 매각)"]]],
      ["land_area", "대지면적", "㎡", 1000, 60000, 500],
      ["zone", "용도지역", "select", [["R1", "제1종일반주거"], ["R2", "제2종일반주거"], ["R3", "제3종일반주거"], ["RS", "준주거"], ["CG", "일반상업"], ["IS", "준공업"]]],
      ["nb_ratio", "근생 비율", "%", 0, 30, 1],
    ],
    수익형: [
      ["eff_ratio", "임대 가능 면적 비율", "%", 45, 90, 1],
      ["rent_py", "월 임대료(평당)", "만원", 3, 45, 0.5],
      ["vacancy", "공실률", "%", 0, 30, 1],
      ["opex", "운영경비율(임대수입 대비)", "%", 10, 45, 1],
      ["cap", "매각 환원율(cap rate)", "%", 3, 10, 0.1],
    ],
    분양: [
      ["avg_supply", "평균 공급면적", "㎡", 40, 160, 0.1],
      ["units_override", "세대수 직접 입력(0=자동)", "세대", 0, 6000, 10],
      ["price_py", "평당 분양가", "만원", 800, 6500, 10],
      ["sell_through", "분양률", "%", 0, 100, 1],
    ],
    원가: [
      ["land_eok", "토지비", "억원", 0, 5000, 10],
      ["unit_cost_py", "평당 공사비", "만원", 450, 1300, 5],
      ["months", "사업기간", "개월", 12, 72, 1],
      ["indirect", "간접비율(공사비 대비)", "%", 0, 15, 0.5],
      ["marketing", "판매비율(수입 대비)", "%", 0, 8, 0.5],
    ],
    금융: [
      ["equity_eok", "자기자본", "억원", 0, 3000, 10],
      ["bridge_eok", "브릿지론", "억원", 0, 3000, 10],
      ["bridge_rate", "브릿지 금리", "%", 3, 15, 0.1],
      ["pf_eok", "PF 한도", "억원", 0, 10000, 50],
      ["pf_rate", "PF 금리", "%", 3, 12, 0.1],
    ],
    정비: [
      ["prior_eok", "기존 자산 평가액(종전자산)", "억원", 100, 20000, 50],
      ["members", "조합원 수", "명", 50, 5000, 10],
      ["mem_price_py", "조합원 평당 분양가", "만원", 600, 5000, 10],
      ["gen_units", "일반분양 세대(임대 차감 전)", "세대", 0, 3000, 10],
      ["relo_eok", "이주비 대여", "억원", 0, 10000, 50],
      ["demo_eok", "철거·명도비", "억원", 0, 2000, 10],
      ["rental", "임대주택 비율(재개발)", "%", 0, 30, 1],
      ["cashout", "현금청산 비율", "%", 0, 30, 1],
    ],
  };

  function fieldHTML([key, name, unit, a, b, step]) {
    if (unit === "select") {
      const opts = a.map(([v, t]) => `<option value="${v}">${t}</option>`).join("");
      return `<div class="field"><label for="f-${key}">${name}</label><select id="f-${key}" data-k="${key}">${opts}</select></div>`;
    }
    return `<div class="field">
      <label for="f-${key}">${name} <span class="fv"><input type="number" id="n-${key}" data-nk="${key}" min="${a}" max="${b}" step="${step}" inputmode="decimal" aria-label="${name} 직접 입력"> <small>${unit}</small></span></label>
      <input type="range" id="f-${key}" data-k="${key}" min="${a}" max="${b}" step="${step}">
    </div>`;
  }

  const isIncome = () => mode === "신축분양" && st.asset !== "apt";
  function groupsForMode() {
    if (mode === "신축분양") {
      const g2 = isIncome() ? ["② 임대·매각", FIELDS.수익형] : ["② 분양", FIELDS.분양];
      return [["① 토지", FIELDS.공통토지], g2, ["③ 원가", FIELDS.원가], ["④ 금융", FIELDS.금융]];
    }
    // 정비사업: 대지면적·용도지역을 노출(공사비 산정의 숨은 의존 제거 — codex 지적),
    // 토지 매입비는 정비 모드에서 미사용이라 원가 그룹에서 제외(무효 입력 노출 방지)
    const landFields = FIELDS.공통토지.filter(f => f[0] !== "asset");
    const costFields = FIELDS.원가.filter(f => f[0] !== "land_eok");
    return [["① 토지·정비 개요", [...landFields, ...FIELDS.정비]], ["② 분양", FIELDS.분양],
            ["③ 원가", costFields], ["④ 금융", FIELDS.금융]];
  }

  function clearPresetActive() {
    document.querySelectorAll("[data-preset]").forEach(x => x.removeAttribute("aria-pressed"));
  }

  function renderInputs() {
    const host = $("#calc-fields");
    host.innerHTML = groupsForMode().map(([title, fs]) =>
      `<div class="in-group"><div class="g-title">${title}</div>${fs.map(fieldHTML).join("")}</div>`).join("");
    host.querySelectorAll("input[type=range],select").forEach(inp => {
      inp.addEventListener("input", () => {
        const k = inp.dataset.k;
        st[k] = inp.tagName === "SELECT" ? inp.value : parseFloat(inp.value);
        clearPresetActive();
        if (k === "asset") { renderInputs(); recalc(); renderSensitivity(); return; } // 그룹 구조 전환
        updateLabel(k); // 라벨 실시간 갱신
        scheduleRecalc();
      });
    });
    // 숫자 직접 입력 — 슬라이더와 양방향 동기화
    host.querySelectorAll("input[type=number]").forEach(inp => {
      inp.addEventListener("input", () => {
        const k = inp.dataset.nk, v = parseFloat(inp.value);
        if (!isFinite(v)) return;
        st[k] = Math.min(parseFloat(inp.max), Math.max(parseFloat(inp.min), v));
        const r = document.getElementById("f-" + k);
        if (r) r.value = st[k];
        clearPresetActive();
        scheduleRecalc();
      });
      inp.addEventListener("change", () => syncInputs()); // blur 시 범위 클램프 값 반영
    });
    syncInputs();
  }
  function updateLabel(k) {
    const n = document.getElementById("n-" + k);
    if (n && typeof st[k] === "number" && document.activeElement !== n) n.value = st[k];
  }
  function syncInputs() {
    document.querySelectorAll("#calc-fields input[type=range],#calc-fields select").forEach(inp => {
      const k = inp.dataset.k;
      if (st[k] == null) return;
      inp.value = st[k];
      updateLabel(k);
    });
  }

  /* ---------- 입력 → 모델 스키마 ---------- */
  function buildInputs(s) {
    s = s || st;
    const zi = Z.derive(s.land_area, s.zone, {
      mix: { residential: 1 - s.nb_ratio / 100, neighborhood: s.nb_ratio / 100 },
      avg_supply_m2: s.avg_supply,
    });
    const units = [];
    let income = null; // 수익형 산출 (NOI·매각가치) — KPI·판정에 사용
    if (mode === "신축분양") {
      if (s.asset !== "apt") {
        // 수익형: NOI = 임대면적(평)×월임대료×12×(1−공실)×(1−경비율), 매각가치 = NOI ÷ cap rate
        const nra_py = (zi.buildable_gfa_m2 * (s.eff_ratio / 100)) / PY;
        const noi = nra_py * s.rent_py * 1e4 * 12 * (1 - s.vacancy / 100) * (1 - s.opex / 100);
        const exit_value = s.cap > 0 ? noi / (s.cap / 100) : 0;
        units.push({ name: s.asset === "office" ? "오피스" : "상업시설", count: 1, supply_m2: 1, price_per_m2: exit_value });
        income = { noi, exit_value, nra_py };
      } else {
        units.push({ name: "주거", count: s.units_override > 0 ? s.units_override : zi.units_est,
                     supply_m2: s.avg_supply, price_per_m2: pyman_to_wonm2(s.price_py) });
        if (zi.neighborhood_gfa_m2 > 0) {
          units.push({ name: "근생", count: 1, supply_m2: zi.neighborhood_gfa_m2 * 0.6, price_per_m2: pyman_to_wonm2(s.price_py) * 1.15 });
        }
      }
    }
    const inputs = {
      mode,
      revenue: { units, sell_through: income ? 1 : s.sell_through / 100, other_income: 0,
                 schedule: income ? "terminal" : "presale" },
      cost: {
        land: { purchase: mode === "신축분양" ? s.land_eok * EOK : 0, acq_tax_rate: 0.046, misc_rate: 0.01 },
        construction: { gfa_m2: zi.buildable_gfa_m2, unit_cost_per_m2: pyman_to_wonm2(s.unit_cost_py) },
        indirect_rate: s.indirect / 100,
        marketing_rate: s.marketing / 100,
        contingency_rate: s.contingency / 100,
      },
      finance: {
        equity: s.equity_eok * EOK,
        bridge: { amount: s.bridge_eok * EOK, rate: s.bridge_rate / 100, months: s.bridge_mo },
        pf: { amount: s.pf_eok * EOK, rate: s.pf_rate / 100, months: Math.round(s.months * 0.8), drawdown: s.pf_draw / 100 },
        fee_rate: s.fee / 100,
      },
      schedule: { months_total: s.months },
    };
    if (mode !== "신축분양") {
      inputs.redevelopment = {
        prior_asset_value: s.prior_eok * EOK,
        member_count: s.members,
        member_supply_m2: s.mem_supply,
        member_price_per_m2: pyman_to_wonm2(s.mem_price_py),
        general_units: [{ name: "일반", count: s.gen_units, supply_m2: s.avg_supply, price_per_m2: pyman_to_wonm2(s.price_py) }],
        relocation_loan: { amount: s.relo_eok * EOK, rate: s.relo_rate / 100, months: Math.round(s.months * 0.7) },
        demolition_cost: s.demo_eok * EOK,
        rental_ratio: mode === "재개발" ? s.rental / 100 : 0,
        cash_settlement_ratio: s.cashout / 100,
      };
    }
    return { inputs, zoning: zi, income };
  }

  /* ---------- 출력 렌더 ---------- */
  let lastIncome = null;
  function kpiHTML(r) {
    const kpis = [
      ["개발이익", fmt.eok(r.profit), r.profit >= 0 ? "pos" : "neg", "hero"],
      ["수입 대비 이익률", r.margin_on_revenue == null ? "―" : Math.abs(r.margin_on_revenue) > 10 ? "±1,000% 초과" : fmt.pct(r.margin_on_revenue), (r.margin_on_revenue || 0) >= 0 ? "pos" : "neg"],
      ["IRR(연)", r.irr_annual == null ? "―" : fmt.pct(r.irr_annual), (r.irr_annual || 0) >= 0 ? "pos" : "neg"],
      [lastIncome ? "매각가치(총수입)" : "총수입", fmt.eok(r.revenue_total), ""],
      ["총지출", fmt.eok(r.cost_total), ""],
    ];
    // Peak Funding Gap — 누적 현금흐름 최저점 (자기자본·차입 유입 前 사업 자체 현금흐름 기준)
    if (r.cashflow_quarterly && r.cashflow_quarterly.length) {
      let cum = 0, minCum = 0;
      r.cashflow_quarterly.forEach(c => { cum += c; if (cum < minCum) minCum = cum; });
      kpis.push(["최대 자금부족", minCum < 0 ? fmt.eok(-minCum) : "0억", minCum < 0 ? "neg" : "pos"]);
    }
    if (lastIncome) {
      kpis.splice(3, 0, ["연 NOI", fmt.eok(lastIncome.noi), ""],
        ["총사업비 대비 수익률(YoC)", r.cost_total ? fmt.pct(lastIncome.noi / r.cost_total) : "―",
         (lastIncome.noi / (r.cost_total || 1)) >= st.cap / 100 ? "pos" : "neg"]);
    }
    if (mode !== "신축분양") {
      // 비례율은 수학적으로 무경계 — 실무 정상역(80~130%)만 양호색, 극단은 표시 가드
      const pr = r.proportion_rate;
      const prTxt = pr == null ? "―" : Math.abs(pr) > 10 ? "±1,000% 초과" : fmt.pct(pr, 1);
      kpis.push(["비례율", prTxt, pr != null && pr >= 0.8 && pr <= 1.3 ? "pos" : "neg"]);
      const mc = r.member_contribution;
      kpis.push(["세대당 분담금", mc == null ? "―" : mc < 0 ? "환급 " + fmt.eok(-mc) : fmt.eok(mc), mc != null && mc < 0 ? "pos" : ""]);
    }
    return kpis.map(([k, v, cls, hero]) =>
      `<div class="kpi${hero ? " kpi-hero" : ""}"><div class="v ${cls}">${v}</div><div class="k">${k}</div></div>`).join("");
  }

  // 판정 문장 — 지표를 실무 기준선과 비교해 한 줄로 해석
  function verdictHTML(r) {
    let cls, txt;
    if (lastIncome) {
      const yoc = r.cost_total ? lastIncome.noi / r.cost_total : 0;
      const spread = yoc - st.cap / 100;
      const sp = (spread * 100).toFixed(2) + "%p";
      if (spread >= 0.015) { cls = "good"; txt = `우량 — 총사업비 대비 수익률 ${fmt.pct(yoc)}가 매각 환원율보다 ${sp} 높다. 개발 후 이익 여력이 충분하다`; }
      else if (spread >= 0.0075) { cls = "good"; txt = `성립 — 총사업비 대비 수익률 ${fmt.pct(yoc)}, 매각 환원율보다 +${sp}. 통상 요구 폭(0.75~1.5%p) 안이다`; }
      else if (spread >= 0) { cls = "warn"; txt = `경계 — 수익률과 매각 환원율 차이가 ${sp}에 불과. 임대료·공실 가정을 점검해야 한다`; }
      else { cls = "bad"; txt = `부적정 — 총사업비 대비 수익률 ${fmt.pct(yoc)}가 매각 환원율보다 낮다. 매각가치가 원가에 미달한다`; }
    } else {
      // 정비사업 비현실 입력 가드 — 비례율이 실무 가능역을 크게 벗어나면 판정 대신 재검토 안내
      if (mode !== "신축분양" && r.proportion_rate != null && (r.proportion_rate < 0.5 || r.proportion_rate > 3)) {
        const prTxt = Math.abs(r.proportion_rate) > 10 ? "±1,000% 초과" : fmt.pct(r.proportion_rate, 1);
        return `<div class="verdict bad">입력 조합이 비현실적이다 — 비례율 ${prTxt}. 종전자산평가액·조합원 수·분양가의 균형을 확인해야 한다</div>`;
      }
      const m = r.margin_on_revenue || 0;
      if (m >= 0.15) { cls = "good"; txt = `우량 — 마진율 ${fmt.pct(m)}, 통상 목표(10~15%)를 상회한다`; }
      else if (m >= 0.10) { cls = "good"; txt = `성립 — 마진율 ${fmt.pct(m)}, 통상 목표 구간(10~15%) 안이다`; }
      else if (m >= 0.05) { cls = "warn"; txt = `경계 — 마진율 ${fmt.pct(m)}, 분양가·공사비 민감도(Ⅳ장) 점검이 필요하다`; }
      else if (m >= 0) { cls = "warn"; txt = `한계 — 마진율 ${fmt.pct(m)}, 원가 절감이나 분양가 재검토 없이는 착수가 어렵다`; }
      else { cls = "bad"; txt = `부적정 — 손실 ${fmt.eok(-r.profit)}, 현재 구조로는 성립하지 않는다`; }
      if (r.irr_annual != null) txt += ` · 연 IRR ${fmt.pct(r.irr_annual)}`;
      if (mode !== "신축분양" && r.proportion_rate != null) {
        txt += ` · 비례율 ${fmt.pct(r.proportion_rate, 1)}` + (r.proportion_rate >= 1 ? " (조합원 부담 줄일 여지)" : " (분담금 부담 증가)");
      }
    }
    return `<div class="verdict ${cls}">${txt}</div>`;
  }

  function ledgerHTML(r) {
    const c = r.cost;
    const rows = [
      ["Ⅰ. 총수입", r.revenue_total, "sum-in"],
      ["토지비", c.land], ["공사비", c.construction], ["간접비", c.indirect],
      ["판매비", c.marketing], ["금융비", c.finance], ["예비비", c.contingency],
    ];
    if (c.demolition != null) rows.push(["철거·명도비", c.demolition]);
    if (c.relocation_interest != null) rows.push(["이주비 이자", c.relocation_interest]);
    if (c.cash_settlement != null && c.cash_settlement > 0) rows.push(["현금청산", c.cash_settlement]);
    let html = `<table class="ledger" aria-label="사업수지표"><thead><tr><th>항목</th><th>금액</th><th>비중</th></tr></thead><tbody>`;
    html += `<tr><td><b>Ⅰ. 총수입</b></td><td class="num"><b>${fmt.eok(r.revenue_total)}</b></td><td class="num">100%</td></tr>`;
    rows.slice(1).forEach(([name, v]) => {
      html += `<tr class="sub"><td>　${name}</td><td class="num">${fmt.eok(v)}</td><td class="num">${r.cost_total ? fmt.pct(v / r.cost_total, 1) : "―"}</td></tr>`;
    });
    html += `<tr><td><b>Ⅱ. 총지출</b></td><td class="num"><b>${fmt.eok(r.cost_total)}</b></td><td class="num"></td></tr>`;
    html += `<tr class="sum"><td>개발이익 (Ⅰ−Ⅱ)</td><td class="num" style="color:var(${r.profit >= 0 ? "--pos" : "--neg"})">${fmt.eok(r.profit)}</td><td class="num">${r.revenue_total ? fmt.pct(r.profit / r.revenue_total, 1) : "―"}</td></tr>`;
    html += `</tbody></table>`;
    return html;
  }

  let raf = 0;
  function scheduleRecalc() { clearTimeout(raf); raf = setTimeout(recalc, 16); } // 타이머 디바운스 (rAF는 백그라운드 탭·헤드리스에서 굶는다)

  function recalc() {
    let out;
    try {
      const { inputs, zoning, income } = buildInputs();
      lastIncome = income;
      out = F.run(inputs);
      // 토지 요약
      const zEl = $("#calc-zoning");
      if (zEl) {
        if (income) {
          zEl.innerHTML = `${zoning.zone_name} · 용적률 <b class="num">${fmt.pct(zoning.far_applied, 0)}</b> → 연면적 <b class="num">${fmt.num(zoning.buildable_gfa_m2, 0)}㎡</b> · 임대면적 <b class="num">${fmt.num(income.nra_py, 0)}평</b> · cap <b class="num">${st.cap}%</b>`;
        } else {
          zEl.innerHTML = mode === "신축분양"
            ? `${zoning.zone_name} · 용적률 <b class="num">${fmt.pct(zoning.far_applied, 0)}</b> → 연면적 <b class="num">${fmt.num(zoning.buildable_gfa_m2, 0)}㎡</b> · ${st.units_override > 0 ? `직접 입력 <b class="num">${st.units_override}세대</b>` : `이론 추정 <b class="num">${zoning.units_est}세대</b> <small>(용적률 기준 — 일조·주차·심의 등 설계 조건 미반영)</small>`}`
            : `정비사업 모드 — 연면적 <b class="num">${fmt.num(zoning.buildable_gfa_m2, 0)}㎡</b> 기준 공사비 산정`;
        }
      }
    } catch (e) {
      $("#calc-kpis").innerHTML = `<div class="kpi"><div class="v neg">입력 오류</div><div class="k">${String(e.message || e)}</div></div>`;
      return;
    }
    $("#calc-kpis").innerHTML = kpiHTML(out);
    const vd = $("#calc-verdict");
    if (vd) vd.innerHTML = verdictHTML(out);
    $("#calc-ledger").innerHTML = ledgerHTML(out);
    // 워터폴
    const items = [
      { name: "총수입", value: out.revenue_total, kind: "in" },
      { name: "토지비", value: -out.cost.land, kind: "out" },
      { name: "공사비", value: -out.cost.construction, kind: "out" },
      { name: "간접·판매", value: -(out.cost.indirect + out.cost.marketing), kind: "out" },
      { name: "금융비", value: -out.cost.finance, kind: "out" },
      { name: "기타", value: -(out.cost.contingency + (out.cost.demolition || 0) + (out.cost.relocation_interest || 0) + (out.cost.cash_settlement || 0)), kind: "out" },
      { name: "개발이익", kind: "sum" },
    ];
    C.waterfall($("#calc-wf"), items, { height: 280 });
    // 게이지
    C.gauge($("#g-margin"), out.margin_on_revenue || 0, { label: "마진율(수입)", min: -0.1, max: 0.35, target: 0.1 });
    C.gauge($("#g-irr"), out.irr_annual == null ? 0 : out.irr_annual, { label: "IRR(연)", min: -0.2, max: 0.6, target: 0.15, fmt: v => out.irr_annual == null ? "―" : fmt.pct(v, 1) });
    // 분기 현금흐름 + 누적 잔액 (리뷰 반영: Peak Funding Gap 시각화)
    const cfEl = $("#calc-cf");
    if (cfEl && out.cashflow_quarterly) {
      const cf = out.cashflow_quarterly;
      let acc = 0;
      const cumPts = cf.map((c, i) => { acc += c; return { x: i, label: "Q" + (i + 1), y: acc / EOK }; });
      const cfPts = cf.map((c, i) => ({ x: i, label: "Q" + (i + 1), y: c / EOK }));
      C.line(cfEl, [
        { name: "누적", color: "--s1", emph: true, points: cumPts },
        { name: "분기", color: "--s2", points: cfPts },
      ], { aria: "분기 현금흐름·누적 잔액", yFmt: v => fmt.num(v, 0) + "억", width: 1160, height: 300, rightPad: 64, interactive: false });
      let minCum = 0, minQ = 0; acc = 0;
      cf.forEach((c, i) => { acc += c; if (acc < minCum) { minCum = acc; minQ = i + 1; } });
      $("#calc-cf-cap").textContent = minCum < 0
        ? `누적 현금흐름 최저점 = Q${minQ}에 ${fmt.eok(-minCum)} 부족 — 자기자본·차입으로 메워야 하는 최대 규모(Peak Funding Gap)다. 분양 잔금(마지막 분기)이 들어와야 누적이 이익으로 돌아선다.`
        : "전 구간 누적 현금흐름이 양(+) — 초기 유입(계약금 등)이 지출을 앞선다.";
    }
    // A/B 표시
    renderAB(out);
    global.__calcLast = out;
  }

  function renderAB(cur) {
    const host = $("#ab-result");
    if (!snapshotA) { host.innerHTML = ""; return; }
    const d = cur.profit - snapshotA.profit;
    host.innerHTML = `<span class="ab-badge">A 대비</span> 이익 <b class="num" style="color:var(${d >= 0 ? "--pos" : "--neg"})">${d >= 0 ? "+" : ""}${fmt.eok(d)}</b>
      · 마진 <b class="num">${fmt.pct((cur.margin_on_revenue || 0) - (snapshotA.margin_on_revenue || 0), 1)}p</b>`;
  }

  /* ---------- 민감도 (Ⅳ장에서 사용) ---------- */
  function sensitivity() {
    const { inputs } = buildInputs();
    const base = F.run(inputs).profit;
    const vary = (mut) => {
      const c = JSON.parse(JSON.stringify(inputs));
      mut(c); return F.run(c).profit;
    };
    const items = [
      { name: (isIncome() ? "임대료·매각가치" : "분양가") + " ±10%", low: vary(c => scalePrice(c, 0.9)), high: vary(c => scalePrice(c, 1.1)) },
      { name: "공사비 ±10%", low: vary(c => { c.cost.construction.unit_cost_per_m2 *= 1.1; }), high: vary(c => { c.cost.construction.unit_cost_per_m2 *= 0.9; }) },
      { name: "분양률 ±10%p", low: vary(c => { c.revenue.sell_through = Math.max(0, c.revenue.sell_through - 0.1); }), high: vary(c => { c.revenue.sell_through = Math.min(1, c.revenue.sell_through + 0.1); }) },
      { name: "금리 ±2%p", low: vary(c => { c.finance.pf.rate += 0.02; c.finance.bridge.rate += 0.02; }), high: vary(c => { c.finance.pf.rate = Math.max(0, c.finance.pf.rate - 0.02); c.finance.bridge.rate = Math.max(0, c.finance.bridge.rate - 0.02); }) },
      { name: "사업기간 ±6개월", low: vary(c => { c.schedule.months_total += 6; c.finance.pf.months += 5; }), high: vary(c => { c.schedule.months_total = Math.max(6, c.schedule.months_total - 6); c.finance.pf.months = Math.max(1, c.finance.pf.months - 5); }) },
    ];
    items.sort((a, b2) => (Math.abs(b2.high - b2.low)) - (Math.abs(a.high - a.low)));
    return { items, base };
    function scalePrice(c, k) {
      c.revenue.units.forEach(u => u.price_per_m2 *= k);
      if (c.redevelopment) {
        c.redevelopment.member_price_per_m2 *= k;
        c.redevelopment.general_units.forEach(u => u.price_per_m2 *= k);
      }
    }
  }

  function breakevenGrid() {
    const { inputs } = buildInputs();
    const px = [-15, -10, -5, 0, 5, 10, 15];           // 분양가 %
    const cy = [15, 10, 5, 0, -5, -10, -15];           // 공사비 %
    const cells = cy.map(dc => px.map(dp => {
      const c = JSON.parse(JSON.stringify(inputs));
      c.revenue.units.forEach(u => u.price_per_m2 *= 1 + dp / 100);
      if (c.redevelopment) {
        c.redevelopment.member_price_per_m2 *= 1 + dp / 100;
        c.redevelopment.general_units.forEach(u => u.price_per_m2 *= 1 + dp / 100);
      }
      c.cost.construction.unit_cost_per_m2 *= 1 + dc / 100;
      return F.run(c).profit;
    }));
    return { xs: px.map(v => (v > 0 ? "+" : "") + v + "%"), ys: cy.map(v => (v > 0 ? "+" : "") + v + "%"), cells };
  }

  /* ---------- 대상지 검토 카드 (디지털트윈국토 빌드타임 실조회) ---------- */
  function renderSiteCards() {
    const host = $("#site-cards");
    const SITES = global.__DATA_SITES;
    if (!host || !SITES) return;
    const byName = {};
    Object.entries(Z.ZONES).forEach(([code, z]) => { byName[z.name] = { code, ...z }; });
    host.innerHTML = Object.values(SITES).map(site => {
      const zoneName = (site.zones || [])[0] || "";
      const z = byName[zoneName];
      const ppm = site.land_price_won_m2;
      const rows = [
        ["지번(지오코딩)", site.jibun || "―"],
        ["용도지역", zoneName || "―"],
        z ? ["법정 건폐/용적률", (z.bcr_legal * 100).toFixed(0) + "% / " + (z.far_seoul * 100).toFixed(0) + "% (서울 조례)"] : null,
        ppm ? ["개별공시지가", ppm.toLocaleString() + "원/㎡ · 평당 " + (ppm * 3.305785 >= 1e8 ? fmt.eok(ppm * 3.305785) : Math.round(ppm * 3.305785 / 1e4).toLocaleString() + "만원") + " (" + site.land_price_year + ")"] : null,
      ].filter(Boolean);
      return `<div class="site-card"><h5>${site.name}</h5>` +
        rows.map(([k, v]) => `<div class="row"><span>${k}</span><b>${v}</b></div>`).join("") +
        (z ? `<button type="button" data-site-zone="${z.code}">이 용도지역(${zoneName})으로 계산기 설정</button>` : "") +
        `</div>`;
    }).join("");
    host.querySelectorAll("[data-site-zone]").forEach(btn => btn.addEventListener("click", () => {
      st.zone = btn.dataset.siteZone;
      clearPresetActive();
      syncInputs(); recalc(); renderSensitivity();
      const zi = document.getElementById("calc-zoning");
      if (zi) zi.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "center" });
    }));
  }

  /* ---------- 초기화 ---------- */
  function init(presetData) {
    presets = presetData || {};
    // 수익형 예시 프리셋 (로컬 정의 — 서울 일반상업지 오피스 개발 가정)
    presets["서울오피스"] = presets["서울오피스"] || {
      // 2026-07-21 정합성 검증 반영: cap 4.0%(Savills 서울 프라임 실질)·공사비 890만/평(서울 실측)
      // 성립 조합(엔진 실측): 이익 810억·YoC 4.92%(cap +0.92%p)·매각가치는 준공 시 일시 유입(terminal)
      __mode: "신축분양", asset: "office", land_area: 8000, zone: "CG", nb_ratio: 0,
      eff_ratio: 65, rent_py: 16.5, vacancy: 5, opex: 27, cap: 4.0,
      land_eok: 1000, unit_cost_py: 890, months: 42, indirect: 6, marketing: 1.5,
      equity_eok: 800, bridge_eok: 1000, bridge_rate: 8.25, pf_eok: 4000, pf_rate: 6.25,
    };
    // 모드 탭
    document.querySelectorAll(".mode-tabs button").forEach(b => {
      b.addEventListener("click", () => {
        mode = b.dataset.mode;
        document.querySelectorAll(".mode-tabs button").forEach(x => x.setAttribute("aria-pressed", x === b ? "true" : "false"));
        renderInputs(); recalc(); renderSensitivity();
      });
    });
    // 프리셋
    document.querySelectorAll("[data-preset]").forEach(b => {
      b.addEventListener("click", () => {
        const p = presets[b.dataset.preset];
        if (p) {
          mode = p.__mode || "신축분양"; syncModeTabs();
          if (p.asset === undefined) st.asset = "apt"; // 주거 프리셋은 자산유형 복원
          Object.assign(st, p); renderInputs(); recalc(); renderSensitivity();
          document.querySelectorAll("[data-preset]").forEach(x => x.setAttribute("aria-pressed", x === b ? "true" : "false"));
        }
      });
    });
    // A/B
    $("#btn-snap").addEventListener("click", () => {
      snapshotA = global.__calcLast;
      $("#btn-snap").textContent = "A 저장됨 ✓";
      setTimeout(() => $("#btn-snap").textContent = "현재를 A로 저장", 1600);
      renderAB(global.__calcLast);
    });
    $("#btn-sens").addEventListener("click", renderSensitivity);
    renderSiteCards();
    // 부팅 기본값: 실데이터 기반 수도권 프리셋 (있으면) — 첫 화면부터 성립하는 딜
    if (presets["수도권아파트"]) Object.assign(st, presets["수도권아파트"]);
    renderInputs(); recalc(); renderSensitivity();
  }
  function syncModeTabs() {
    document.querySelectorAll(".mode-tabs button").forEach(x => x.setAttribute("aria-pressed", x.dataset.mode === mode ? "true" : "false"));
  }
  function renderSensitivity() {
    const { items, base } = sensitivity();
    C.tornado($("#sens-tornado"), items, base, { width: 1160 });
    C.heatmap($("#sens-heat"), breakevenGrid(), { xName: "분양가", yName: "공사비", width: 1160, cellText: true, cellFmt: v => fmt.eok(v) });
  }

  // refresh: 테마 토글 등 토큰 색 변경 후 SVG 재렌더용 (codex 리뷰 반영)
  global.CalcUI = { init, refresh() { recalc(); renderSensitivity(); }, get mode() { return mode; } };
})(typeof window !== "undefined" ? window : globalThis);
