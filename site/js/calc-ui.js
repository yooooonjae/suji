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
    land_area: 10000, zone: "R2", far_override: 0, nb_ratio: 0,      // 토지
    avg_supply: 84.9, price_py: 2400, sell_through: 95,               // 분양 (평당만원)
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
  const py2m2 = v => v / PY;             // 평당만원 → 원/㎡: (v×1e4)/PY
  const pricePerM2 = v => (v * 1e4) / PY * 10; // 평당 v만원 → 원/㎡  (v×10000원/평 ÷ 3.3058㎡ ... )

  // 정밀: 평당 X만원 = X*10000 원/평 = X*10000/3.305785 원/㎡
  function pyman_to_wonm2(x) { return (x * 10000) / PY; }

  /* ---------- 프리셋 (사례 데이터 기반 — cases.json에서 주입) ---------- */
  let presets = {};
  function applyPreset(p) { Object.assign(st, p); syncInputs(); recalc(); }

  /* ---------- 입력 구성 ---------- */
  const FIELDS = {
    공통토지: [
      ["land_area", "대지면적", "㎡", 1000, 60000, 500],
      ["zone", "용도지역", "select", [["R1", "제1종일반주거"], ["R2", "제2종일반주거"], ["R3", "제3종일반주거"], ["RS", "준주거"], ["CG", "일반상업"], ["IS", "준공업"]]],
      ["nb_ratio", "근생 비율", "%", 0, 30, 1],
    ],
    분양: [
      ["avg_supply", "평균 공급면적", "㎡", 40, 160, 0.1],
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
      ["prior_eok", "종전자산평가액", "억원", 100, 20000, 50],
      ["members", "조합원 수", "명", 50, 5000, 10],
      ["mem_price_py", "조합원 평당분양가", "만원", 600, 5000, 10],
      ["gen_units", "일반분양 세대", "세대", 0, 3000, 10],
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
      <label for="f-${key}">${name} <span class="fv"><span id="v-${key}"></span> <small>${unit}</small></span></label>
      <input type="range" id="f-${key}" data-k="${key}" min="${a}" max="${b}" step="${step}">
    </div>`;
  }

  function groupsForMode() {
    if (mode === "신축분양") return [["① 토지", FIELDS.공통토지], ["② 분양", FIELDS.분양], ["③ 원가", FIELDS.원가], ["④ 금융", FIELDS.금융]];
    return [["① 정비 개요", FIELDS.정비], ["② 분양", FIELDS.분양], ["③ 원가", FIELDS.원가], ["④ 금융", FIELDS.금융]];
  }

  function renderInputs() {
    const host = $("#calc-fields");
    host.innerHTML = groupsForMode().map(([title, fs]) =>
      `<div class="in-group"><div class="g-title">${title}</div>${fs.map(fieldHTML).join("")}</div>`).join("");
    host.querySelectorAll("input,select").forEach(inp => {
      inp.addEventListener("input", () => {
        const k = inp.dataset.k;
        st[k] = inp.tagName === "SELECT" ? inp.value : parseFloat(inp.value);
        scheduleRecalc();
      });
    });
    syncInputs();
  }
  function syncInputs() {
    document.querySelectorAll("#calc-fields input,#calc-fields select").forEach(inp => {
      const k = inp.dataset.k;
      if (st[k] == null) return;
      inp.value = st[k];
      const v = document.getElementById("v-" + k);
      if (v) v.textContent = typeof st[k] === "number" ? fmt.num(st[k], 1).replace(/\.0$/, "") : st[k];
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
    if (mode === "신축분양") {
      units.push({ name: "주거", count: zi.units_est, supply_m2: s.avg_supply, price_per_m2: pyman_to_wonm2(s.price_py) });
      if (zi.neighborhood_gfa_m2 > 0) {
        units.push({ name: "근생", count: 1, supply_m2: zi.neighborhood_gfa_m2 * 0.6, price_per_m2: pyman_to_wonm2(s.price_py) * 1.15 });
      }
    }
    const inputs = {
      mode,
      revenue: { units, sell_through: s.sell_through / 100, other_income: 0 },
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
    return { inputs, zoning: zi };
  }

  /* ---------- 출력 렌더 ---------- */
  function kpiHTML(r) {
    const kpis = [
      ["총수입", fmt.eok(r.revenue_total), ""],
      ["총지출", fmt.eok(r.cost_total), ""],
      ["개발이익", fmt.eok(r.profit), r.profit >= 0 ? "pos" : "neg"],
      ["마진율(수입)", fmt.pct(r.margin_on_revenue || 0), (r.margin_on_revenue || 0) >= 0 ? "pos" : "neg"],
      ["IRR(연)", r.irr_annual == null ? "―" : fmt.pct(r.irr_annual), (r.irr_annual || 0) >= 0 ? "pos" : "neg"],
    ];
    if (mode !== "신축분양") {
      kpis.push(["비례율", r.proportion_rate == null ? "―" : fmt.pct(r.proportion_rate, 1), (r.proportion_rate || 0) >= 1 ? "pos" : "neg"]);
      kpis.push(["세대당 분담금", r.member_contribution == null ? "―" : fmt.eok(r.member_contribution), ""]);
    }
    return kpis.map(([k, v, cls]) => `<div class="kpi"><div class="v ${cls}">${v}</div><div class="k">${k}</div></div>`).join("");
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
  function scheduleRecalc() { cancelAnimationFrame(raf); raf = requestAnimationFrame(recalc); }

  function recalc() {
    let out;
    try {
      const { inputs, zoning } = buildInputs();
      out = F.run(inputs);
      // 토지 요약
      const zEl = $("#calc-zoning");
      if (zEl) {
        zEl.innerHTML = mode === "신축분양"
          ? `${zoning.zone_name} · 용적률 <b class="num">${fmt.pct(zoning.far_applied, 0)}</b> → 연면적 <b class="num">${fmt.num(zoning.buildable_gfa_m2, 0)}㎡</b> · 추정 <b class="num">${zoning.units_est}세대</b>`
          : `정비사업 모드 — 연면적 <b class="num">${fmt.num(zoning.buildable_gfa_m2, 0)}㎡</b> 기준 공사비 산정`;
      }
    } catch (e) {
      $("#calc-kpis").innerHTML = `<div class="kpi"><div class="v neg">입력 오류</div><div class="k">${String(e.message || e)}</div></div>`;
      return;
    }
    $("#calc-kpis").innerHTML = kpiHTML(out);
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
    C.gauge($("#g-irr"), out.irr_annual == null ? 0 : out.irr_annual, { label: "IRR(연)", min: -0.2, max: 0.6, target: 0.15, fmt: v => out.irr_annual == null ? "―" : fmt.pct(v, 0) });
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
      { name: "분양가 ±10%", low: vary(c => scalePrice(c, 0.9)), high: vary(c => scalePrice(c, 1.1)) },
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

  /* ---------- 초기화 ---------- */
  function init(presetData) {
    presets = presetData || {};
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
        if (p) { mode = p.__mode || "신축분양"; syncModeTabs(); applyPreset(p); renderSensitivity(); }
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
    // 부팅 기본값: 실데이터 기반 수도권 프리셋 (있으면) — 첫 화면부터 성립하는 딜
    if (presets["수도권아파트"]) Object.assign(st, presets["수도권아파트"]);
    renderInputs(); recalc(); renderSensitivity();
  }
  function syncModeTabs() {
    document.querySelectorAll(".mode-tabs button").forEach(x => x.setAttribute("aria-pressed", x.dataset.mode === mode ? "true" : "false"));
  }
  function renderSensitivity() {
    const { items, base } = sensitivity();
    C.tornado($("#sens-tornado"), items, base);
    C.heatmap($("#sens-heat"), breakevenGrid(), { xName: "분양가", yName: "공사비" });
  }

  // refresh: 테마 토글 등 토큰 색 변경 후 SVG 재렌더용 (codex 리뷰 반영)
  global.CalcUI = { init, refresh() { recalc(); renderSensitivity(); }, get mode() { return mode; } };
})(typeof window !== "undefined" ? window : globalThis);
