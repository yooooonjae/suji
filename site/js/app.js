/* ============================================================
   app — 데이터 바인딩·시장/예측/상권 렌더·내비·리빌·카운터
   ============================================================ */
(function () {
  "use strict";
  const C = window.Charts, fmt = C.fmt;
  const $ = s => document.querySelector(s);
  const M = window.__DATA_MARKET, FC = window.__DATA_FORECAST,
        CS = window.__DATA_CASES, SB = window.__DATA_SBIZ;

  const SIDO_ORDER = ["전국", "서울", "경기", "인천", "부산", "대구", "광주", "대전", "울산", "세종",
                      "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주"];

  /* ---------- 진행바·리빌 ---------- */
  function initChrome() {
    const bar = $("#progress");
    addEventListener("scroll", () => {
      const h = document.documentElement;
      const denom = h.scrollHeight - h.clientHeight;
      bar.style.width = (denom > 0 ? (h.scrollTop / denom) * 100 : 0) + "%";
    }, { passive: true });

    const rev = new IntersectionObserver(es => {
      es.forEach(e => { if (e.isIntersecting) { e.target.classList.add("in"); rev.unobserve(e.target); } });
    }, { threshold: 0.12 });
    document.querySelectorAll(".reveal").forEach(n => rev.observe(n));
  }

  /* ---------- 라우터 (홈 ↔ 챕터 상세 뷰) ---------- */
  function route() {
    const h = location.hash.replace(/^#\/?/, "");
    const view = /^ch[1-8]$/.test(h) ? h : "home";
    document.body.dataset.view = view;
    // 전 섹션·구분선 숨김 후 대상만 표시
    document.querySelectorAll("section.chapter, .wrap > .dim-rule").forEach(n => { n.style.display = "none"; });
    const hero = document.querySelector(".hero");
    const cards = $("#home-cards");
    const foot = document.querySelector("footer.colophon");
    const isHome = view === "home";
    hero.style.display = isHome ? "" : "none";
    cards.style.display = isHome ? "" : "none";
    foot.style.display = isHome ? "" : "none";
    if (!isHome) {
      const sec = document.getElementById(view);
      sec.style.display = "";
      sec.querySelectorAll(".reveal").forEach(n => n.classList.add("in"));
    }
    document.querySelectorAll(".appbar .tabs a").forEach(a =>
      a.classList.toggle("active", a.dataset.view === view));
    scrollTo(0, 0);
  }

  /* ---------- 히어로 카운터 ---------- */
  function counters() {
    const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
    document.querySelectorAll("[data-count]").forEach(n => {
      const target = parseFloat(n.dataset.count), dec = parseInt(n.dataset.dec || "0", 10);
      if (reduce) { n.textContent = target.toLocaleString(undefined, { minimumFractionDigits: dec, maximumFractionDigits: dec }); return; }
      const t0 = performance.now(), dur = 1300;
      (function tick(t) {
        const p = Math.min(1, (t - t0) / dur), e = 1 - Math.pow(1 - p, 3);
        n.textContent = (target * e).toLocaleString(undefined, { minimumFractionDigits: dec, maximumFractionDigits: dec });
        if (p < 1) requestAnimationFrame(tick);
      })(t0);
    });
  }

  /* ---------- Ⅰ. 시장 ---------- */
  let selSido = "서울";
  let selSub = null; // 하위지역(구·시군) 선택 — 특별·광역시도 드릴다운
  function seriesOf(dict, name) { return (dict && dict[name]) || []; }

  function renderMarket() {
    // 스몰 멀티플 (매매지수)
    C.smallMultiples($("#sm-sale"), M.sale_index, {
      order: SIDO_ORDER.filter(n => M.sale_index[n]),
      selected: selSido,
      onSelect: n => { selSido = n; selSub = null; renderMarket(); renderForecast(); },
    });
    // 하위지역 드릴다운 (서울 25구 · 경기 28시군 · 광역시 구군)
    const SUB = M.sub_index || {};
    const subFig = $("#fig-sub");
    const subData = SUB[selSido];
    if (subFig) {
      if (subData) {
        subFig.hidden = false;
        $("#sub-title").textContent = selSido + " — " + (selSido === "경기" ? "시·군별" : "구·군별") + " 매매가격지수";
        const order = Object.keys(subData).sort((a, b) => a.localeCompare(b, "ko"));
        C.smallMultiples($("#sm-sub"), subData, {
          order, selected: selSub,
          onSelect: n => { selSub = selSub === n ? null : n; renderMarket(); },
        });
      } else { subFig.hidden = true; }
    }
    // 선택 상세: 구·시군 선택 시 해당 지역 vs 시도 평균, 아니면 시도 매매 vs 전세
    const mk = s => s.map((p, i) => ({ x: i, label: fmt.ym(p.ym), y: p.value }));
    const subSer = subData && selSub ? subData[selSub] : null;
    if (subSer) {
      C.line($("#chart-detail"), [
        { name: selSub, color: "--s1", emph: true, points: mk(subSer) },
        { name: selSido + " 평균", color: "--s2", dim: true, points: mk(seriesOf(M.sale_index, selSido)) },
      ], { aria: selSido + " " + selSub + " 매매지수" });
      $("#detail-title").textContent = selSido + " " + selSub + " — 매매가격지수 (시도 평균 대비)";
    } else {
      C.line($("#chart-detail"), [
        { name: "매매", color: "--s1", emph: true, points: mk(seriesOf(M.sale_index, selSido)) },
        { name: "전세", color: "--s2", points: mk(seriesOf(M.jeonse_index, selSido)) },
      ], { aria: selSido + " 매매·전세 지수" });
      $("#detail-title").textContent = selSido + " — 매매·전세가격지수";
    }
    // 미분양
    C.line($("#chart-unsold"), [
      { name: "미분양", color: "--s6", emph: true, points: mk(seriesOf(M.unsold, selSido)) },
      { name: "준공후", color: "--s3", points: mk(seriesOf(M.unsold_completed, selSido) || []) },
    ], { aria: selSido + " 미분양", yFmt: v => fmt.num(v, 0), width: 560, height: 330, rightPad: 64 });
    // 국면 맵
    C.phase($("#chart-phase"), M.phase_points, {});
    // 마진 스퀴즈: 분양가지수 vs 공사비지수 (전국)
    C.line($("#chart-squeeze"), [
      { name: "분양가", color: "--s1", emph: true, points: mk(M.presale_indexed) },
      { name: "공사비", color: "--s5", points: mk(M.cci_indexed) },
    ], { aria: "분양가 vs 공사비 지수화 추이" });
    // 금리
    C.line($("#chart-rates"), [
      { name: "기준금리", color: "--s1", emph: true, points: mk(M.base_rate) },
      { name: "주담대", color: "--s4", points: mk(M.mortgage_rate) },
      { name: "기업대출", color: "--s2", points: mk(M.corp_loan_rate) },
    ], { aria: "금리 추이", yFmt: v => v.toFixed(1) + "%", width: 560, height: 330, rightPad: 72 });
  }

  /* ---------- 예측 ---------- */
  function renderForecast() {
    const f = FC.forecasts[selSido] || FC.forecasts["전국"];
    const best = "sarima";
    const model = f.models[best] || Object.values(f.models)[0];
    const hist = seriesOf(M.sale_index, selSido).slice(-36).map(p => ({ label: fmt.ym(p.ym), y: p.value }));
    const labels = model.median.map((_, i) => "+" + (i + 1) + "M");
    C.fan($("#chart-fan"), hist, { median: model.median, q10: model.q10, q90: model.q90, labels }, { aria: selSido + " 12개월 예측" });
    $("#fan-title").textContent = selSido + " — 매매가격지수 12개월 예측 (SARIMA · 80% 구간)";
    // 벤치마크 표
    const tb = $("#bench-body");
    if (tb && !tb.dataset.done) {
      tb.dataset.done = "1";
      const names = { sarima: "SARIMA", chronos: "Chronos-Bolt (제로샷)", naive: "Naive", lightgbm: "LightGBM",
                      seasonal_naive: "계절 Naive", lstm: "LSTM (시도 풀링)" };
      FC.benchmark.slice().sort((a, b) => a.mae - b.mae).forEach((r, i) => {
        const tr = document.createElement("tr");
        tr.innerHTML = `<td>${i + 1}</td><td>${names[r.model] || r.model}</td>
          <td class="num">${r.mae.toFixed(3)}</td><td class="num">${r.smape.toFixed(3)}%</td>`;
        if (i === 0) tr.style.fontWeight = "800";
        tb.appendChild(tr);
      });
    }
  }

  /* ---------- Ⅴ. 상권 ---------- */
  function renderCommerce() {
    const counts = SB.counts;
    const totals = Object.entries(counts).map(([sido, m]) => ({ name: sido, value: Object.values(m).reduce((a, b) => a + b, 0) }))
      .sort((a, b) => b.value - a.value);
    C.hbars($("#chart-sbiz-sido"), totals, { aria: "시도별 상가업소 수", fmt: v => fmt.num(v, 0), labelW: 60 });
    // 서울 업종 구성
    const seoul = Object.entries(counts["서울"] || {}).map(([k, v]) => ({ name: k, value: v }))
      .sort((a, b) => b.value - a.value).slice(0, 10);
    C.hbars($("#chart-sbiz-upjong"), seoul, { aria: "서울 업종 구성", color: "--s2", fmt: v => fmt.num(v, 0), labelW: 130 });
    // 주요상권 시도별
    const zones = Object.entries(SB.zones.by_sido).map(([k, v]) => ({ name: k, value: v })).sort((a, b) => b.value - a.value).slice(0, 12);
    C.hbars($("#chart-zones"), zones, { aria: "시도별 주요상권 수", color: "--s5", fmt: v => v + "곳", labelW: 60 });
  }

  /* ---------- Ⅵ. 사례 ---------- */
  function renderCases() {
    const grid = $("#case-grid");
    grid.innerHTML = "";
    CS.cases.forEach((c, i) => {
      const el2 = document.createElement("div");
      el2.className = "case-card" + (i === 0 ? " sel" : "");
      el2.setAttribute("role", "button"); el2.tabIndex = 0;
      el2.innerHTML = `<div class="c-type">${c.type}</div><h4>${c.name}</h4>
        <dl><dt>총수입</dt><dd>${fmt.eok(c.result.revenue_total)}</dd>
        <dt>개발이익</dt><dd style="color:var(${c.result.profit >= 0 ? "--pos" : "--neg"})">${fmt.eok(c.result.profit)}</dd>
        <dt>마진율</dt><dd>${fmt.pct(c.result.margin_on_revenue || 0)}</dd>
        <dt>IRR</dt><dd>${c.result.irr_annual == null ? "―" : fmt.pct(c.result.irr_annual)}</dd></dl>`;
      const pick = () => showCase(i);
      el2.addEventListener("click", pick);
      el2.addEventListener("keydown", e => { if (e.key === "Enter") pick(); });
      grid.appendChild(el2);
    });
    showCase(0);
  }
  function showCase(i) {
    document.querySelectorAll(".case-card").forEach((n, j) => n.classList.toggle("sel", i === j));
    const c = CS.cases[i];
    $("#case-detail-title").textContent = c.name + " — 수지 구조";
    const r = c.result;
    const items = [
      { name: "총수입", value: r.revenue_total, kind: "in" },
      { name: "토지비", value: -r.cost.land, kind: "out" },
      { name: "공사비", value: -r.cost.construction, kind: "out" },
      { name: "간접·판매", value: -(r.cost.indirect + r.cost.marketing), kind: "out" },
      { name: "금융비", value: -r.cost.finance, kind: "out" },
      { name: "기타", value: -(r.cost.contingency + (r.cost.demolition || 0) + (r.cost.relocation_interest || 0) + (r.cost.cash_settlement || 0)), kind: "out" },
      { name: "개발이익", kind: "sum" },
    ];
    C.waterfall($("#case-wf"), items, { height: 260 });
    $("#case-notes").innerHTML = c.notes.map(n => `<li>${n}</li>`).join("");
  }

  /* ---------- 테마 토글 (히어로·앱바 공용) ---------- */
  function initTheme() {
    document.querySelectorAll(".theme-toggle").forEach(btn => btn.addEventListener("click", () => {
      const r = document.documentElement;
      const cur = r.dataset.theme || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
      r.dataset.theme = cur === "dark" ? "light" : "dark";
      renderAll(); // 차트 색 재계산
      if (window.CalcUI && window.CalcUI.refresh) window.CalcUI.refresh(); // 계산기·민감도도 재렌더
    }));
  }

  /* ---------- 셀프테스트 (?selftest=1) — 실제 이벤트 경로 검증 ---------- */

  function probe() {
    if (!location.search.includes("probe")) return;
    setTimeout(() => {
      const h = sel => { const n = document.querySelector(sel); return n ? Math.round(n.getBoundingClientRect().height) : -1; };
      document.title = JSON.stringify({
        kpirow: h("#calc-kpis"), hero: h(".kpi.hero"), kpi2: h("#calc-kpis .kpi:nth-child(2)"),
        verdict: h("#calc-verdict"), outmain: h(".out-main"), ledger: h("#calc-ledger"),
        calcout: h(".calc-out"), calcin: h(".calc-in"), panel: h(".calc-panel"),
      });
    }, 1200);
  }

  function selfTest() {
    if (!location.search.includes("selftest")) return;
    location.hash = "#/ch3";
    setTimeout(() => {
      const kpi = () => document.querySelector("#calc-kpis .kpi .v").textContent;
      const before = kpi();
      const slider = document.querySelector('#calc-fields input[data-k="price_py"]');
      slider.value = parseFloat(slider.value) + 400;
      slider.dispatchEvent(new Event("input", { bubbles: true }));
      // 재계산 디바운스(16ms) 이후 판정
      setTimeout(() => {
        const after = kpi();
        const label = document.getElementById("n-price_py").value;
        const ok = before !== after && label !== "";
        const badge = document.createElement("div");
        badge.id = "selftest-result";
        badge.textContent = `SELFTEST ${ok ? "PASS" : "FAIL"} | before=${before} after=${after} label=${label}`;
        badge.style.cssText = "position:fixed;top:60px;right:8px;z-index:99;background:#000;color:#0f0;padding:6px 10px;font-size:12px;font-family:monospace";
        document.body.appendChild(badge);
      }, 200);
    }, 700);
  }

  function renderAll() {
    renderMarket(); renderForecast(); renderCommerce(); renderCases();
  }

  /* ---------- 부팅 ---------- */
  addEventListener("DOMContentLoaded", () => {
    initChrome(); initTheme(); counters();
    renderAll();
    window.CalcUI.init(CS.presets || {});
    addEventListener("hashchange", route);
    route();
    selfTest(); probe();
  });
})();
