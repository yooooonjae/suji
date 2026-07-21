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

  /* ---------- 클릭 결과 노출 — 갱신된 상세가 화면 밖이면 부드럽게 스크롤 ---------- */
  function revealEl(el) {
    if (!el) return;
    const r = el.getBoundingClientRect();
    if (r.top < 64 || r.bottom > innerHeight) {
      el.scrollIntoView({ behavior: "smooth", block: r.height > innerHeight - 140 ? "start" : "center" });
    }
  }

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
    // 시장 온도 진단 — 점 클릭 시 해당 시도로 전환 (유기적 연결, 상세 차트로 스크롤)
    C.phase($("#chart-phase"), M.phase_points, {
      selected: selSido,
      onSelect: n => {
        if (!M.sale_index[n]) return;
        selSido = n; selSub = null; renderMarket(); renderForecast();
        revealEl($("#chart-detail").closest("figure"));
      },
    });
    // 마진 스퀴즈: 분양가지수 vs 공사비지수 (전국) — 주황 vs 파랑 대비
    C.line($("#chart-squeeze"), [
      { name: "분양가", color: "--s1", emph: true, points: mk(M.presale_indexed) },
      { name: "공사비", color: "--s2", points: mk(M.cci_indexed) },
    ], { aria: "분양가 vs 공사비 지수화 추이" });
    // 금리
    C.line($("#chart-rates"), [
      { name: "기준금리", color: "--s1", emph: true, points: mk(M.base_rate) },
      { name: "주담대", color: "--s4", points: mk(M.mortgage_rate) },
      { name: "기업대출", color: "--s2", points: mk(M.corp_loan_rate) },
    ], { aria: "금리 추이", yFmt: v => v.toFixed(1) + "%", width: 560, height: 330, rightPad: 72 });
  }

  /* ---------- 예측 ---------- */
  let selModel = "sarima"; // 벤치마크 표 행 클릭으로 전환
  const MODEL_NAMES = { sarima: "SARIMA", chronos: "Chronos-Bolt (제로샷)", naive: "Naive", lightgbm: "LightGBM",
                        seasonal_naive: "계절 Naive", lstm: "LSTM (시도 풀링)" };
  function renderForecast() {
    const f = FC.forecasts[selSido] || FC.forecasts["전국"];
    const model = f.models[selModel] || Object.values(f.models)[0];
    const hist = seriesOf(M.sale_index, selSido).slice(-36).map(p => ({ label: fmt.ym(p.ym), y: p.value }));
    const labels = model.median.map((_, i) => "+" + (i + 1) + "M");
    C.fan($("#chart-fan"), hist, { median: model.median, q10: model.q10, q90: model.q90, labels }, { aria: selSido + " 12개월 예측" });
    $("#fan-title").textContent = selSido + " — 매매가격지수 12개월 예측 (" + (MODEL_NAMES[selModel] || selModel) + " · 80% 구간)";
    // 벤치마크 표 — 행 클릭 시 위 예측 차트가 그 모델로 전환
    const tb = $("#bench-body");
    if (tb && !tb.dataset.done) {
      tb.dataset.done = "1";
      FC.benchmark.slice().sort((a, b) => a.mae - b.mae).forEach((r, i) => {
        const tr = document.createElement("tr");
        tr.dataset.model = r.model;
        tr.setAttribute("role", "button"); tr.tabIndex = 0;
        tr.style.cursor = "pointer";
        tr.innerHTML = `<td>${i + 1}</td><td>${MODEL_NAMES[r.model] || r.model}</td>
          <td class="num">${r.mae.toFixed(3)}</td><td class="num">${r.smape.toFixed(3)}%</td>`;
        if (i === 0) tr.style.fontWeight = "800";
        const pick = () => { selModel = r.model; renderForecast(); };
        tr.addEventListener("click", pick);
        tr.addEventListener("keydown", e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pick(); } });
        tb.appendChild(tr);
      });
    }
    if (tb) tb.querySelectorAll("tr").forEach(tr =>
      tr.classList.toggle("sel", tr.dataset.model === selModel));
  }

  /* ---------- Ⅰ-보론. 탐색적 데이터 분석 (EDA) ---------- */
  function renderEda() {
    const E = window.__DATA_EDA;
    if (!E || !$("#eda-corr")) return;
    // ① 시차상관 히트맵 — 지표 × 선행 시차
    const corr = E.correlation.data.national, labels = E.correlation.data.driver_labels;
    const lagKeys = ["0", "3", "6", "12"];
    const drivers = Object.keys(corr);
    C.heatmap($("#eda-corr"), {
      xs: ["동시", "3개월 선행", "6개월 선행", "12개월 선행"],
      ys: drivers.map(k => labels[k] || k),
      cells: drivers.map(k => lagKeys.map(l => (corr[k].by_lag[l] || { r: 0 }).r)),
    }, { xName: "시차", yName: "지표", labelW: 150, cellH: 40, cellText: true, width: 1160,
         vFmt: v => (v >= 0 ? "+" : "") + v.toFixed(2), vLabel: "상관계수 r",
         legend: "값 = 전국 매매지수 YoY와의 상관계수 r · 파랑 = 역상관, 주황 = 정상관 (진할수록 강함)", aria: "지표별 시차 상관" });
    // ①-보조 시도별 동시상관 (17행 × 5지표 — 셀 텍스트 없이 색+툴팁)
    const xs2 = E.correlation.data.cross_sido;
    if (xs2 && $("#eda-corr-sido")) {
      const cols = ["base_rate_level", "base_rate_12mchg", "unsold_yoy_own", "cci_yoy", "presale_yoy"];
      const colLabels = { base_rate_level: "기준금리 레벨", base_rate_12mchg: "금리 12개월 변화",
                          unsold_yoy_own: "자체 미분양 YoY", cci_yoy: "공사비 YoY", presale_yoy: "분양가 YoY" };
      const rows = SIDO_ORDER.filter(n => n !== "전국" && xs2.some(r => r.sido === n))
        .map(n => xs2.find(r => r.sido === n));
      C.heatmap($("#eda-corr-sido"), {
        xs: cols.map(c => colLabels[c]),
        ys: rows.map(r => r.sido),
        cells: rows.map(r => cols.map(c => r[c] == null ? 0 : r[c])),
      }, { xName: "지표", yName: "시도", labelW: 62, cellH: 26, width: 1160,
           vFmt: v => "r = " + (v >= 0 ? "+" : "") + v.toFixed(2), vLabel: "동시상관",
           legend: "파랑 = 역상관, 주황 = 정상관 (진할수록 강함) · 각 시도 매매지수 YoY 기준",
           aria: "시도별 지표 동시상관" });
    }
    // ② 지역 동조화 — 횡단면 표준편차 (라인 재활용: 드래그 확대·단위 전환 지원)
    const S = E.synchronization.data;
    C.line($("#eda-sync"), [{
      name: "σ", color: "--s2", emph: true,
      points: S.ym.map((ym, i) => ({ x: i, label: fmt.ym(ym), y: S.cross_sd_pp[i] })),
    }], { aria: "시도 간 상승률 격차", yFmt: v => v.toFixed(1) + "%p", rightPad: 40 });
    // ③ 실거래 ㎡당가 분포 — 시도별 중위 (광주·전남은 원천 무거래 — 결측 행으로 정직 표기)
    const D = E.distribution.data.by_sido.slice()
      .sort((a, b) => (b.median || 0) - (a.median || 0));
    C.hbars($("#eda-dist"), D.map(d => ({
      name: d.sido,
      value: Number.isFinite(d.median) ? d.median / 1e4 : null,
      note: d.note ? "원천 무거래 (수집 시군구 0건)" : undefined,
    })), { color: "--s2", fmt: v => fmt.num(v, 0) + "만", labelW: 60, rowH: 34, aria: "시도별 ㎡당 매매가 중위" });
    // ④ 계절성 스트립 (1×12)
    const sea = E.seasonality.data;
    C.heatmap($("#eda-season"), { xs: sea.months.map(m => m + "월"), ys: ["평균"], cells: [sea.mom_avg_pct] },
      { xName: "월", yName: "MoM", labelW: 50, cellH: 40, vFmt: v => (v >= 0 ? "+" : "") + v.toFixed(2) + "%",
        vLabel: "월평균 변동", legend: "전국 매매지수 월별 평균 MoM 변동률 · 파랑 = 하락, 주황 = 상승", aria: "계절성" });
    // ⑤ 금리 국면 타일 — 한국 관행 색: 하락=파랑, 상승=주황
    const rr = E.rate_regime.data.regimes;
    $("#eda-regime").innerHTML = rr.map(g =>
      `<div class="kpi"><div class="v" style="color:var(${g.sale_mom_avg_pct >= 0 ? "--s1" : "--s2"})">${g.sale_mom_avg_pct >= 0 ? "+" : ""}${g.sale_mom_avg_pct.toFixed(2)}%</div>
       <div class="k">${g.regime} 월평균 · ${g.months}개월</div></div>`).join("");
    // 인사이트 문장 바인딩
    [["correlation", "#eda-ins-corr"], ["synchronization", "#eda-ins-sync"],
     ["distribution", "#eda-ins-dist"], ["rate_regime", "#eda-ins-regime"],
     ["seasonality", "#eda-ins-season"]].forEach(([k, sel]) => {
      const n = $(sel); if (n && E[k]) n.textContent = E[k].insight;
    });
  }

  /* ---------- Ⅴ. 상권 ---------- */
  let selCommerceSido = "서울"; // 시도 바 클릭 → 업종 구성 전환
  function renderCommerce() {
    const counts = SB.counts;
    const totals = Object.entries(counts).map(([sido, m]) => ({ name: sido, value: Object.values(m).reduce((a, b) => a + b, 0) }))
      .sort((a, b) => b.value - a.value);
    C.hbars($("#chart-sbiz-sido"), totals, {
      aria: "시도별 상가업소 수", color: "--s2", fmt: v => fmt.num(v, 0), labelW: 60, width: 1160, rowH: 30,
      selected: selCommerceSido,
      onSelect: n => {
        selCommerceSido = n; renderCommerce();
        revealEl($("#chart-sbiz-upjong").closest("figure"));
      },
    });
    // 선택 시도 업종 구성 (시도 바를 클릭하면 전환)
    const upjong = Object.entries(counts[selCommerceSido] || {}).map(([k, v]) => ({ name: k, value: v }))
      .sort((a, b) => b.value - a.value).slice(0, 10);
    const ut = $("#upjong-title");
    if (ut) ut.textContent = selCommerceSido + " 업종 구성 (상위 10)";
    C.hbars($("#chart-sbiz-upjong"), upjong, { aria: selCommerceSido + " 업종 구성", color: "--s2", fmt: v => fmt.num(v, 0), labelW: 130, width: 1160, rowH: 30 });
    // 주요상권 시도별 — 파랑 계열
    const zones = Object.entries(SB.zones.by_sido).map(([k, v]) => ({ name: k, value: v })).sort((a, b) => b.value - a.value).slice(0, 12);
    C.hbars($("#chart-zones"), zones, { aria: "시도별 주요상권 수", color: "--s2", fmt: v => v + "곳", labelW: 60, width: 1160, rowH: 30 });
    renderOffice();
  }

  // 상업용 부동산 (R-ONE 임대동향, 분기) — 상권 시도 선택과 연동
  function renderOffice() {
    const CM = window.__DATA_COMMERCIAL;
    if (!CM || !$("#chart-office-vac")) return;
    const sido = selCommerceSido;
    const mkq = s => s.map((p, i) => ({ x: i, label: p.yq.replace("Q", " Q"), y: p.value }));
    const vac = CM.office_vacancy[sido], rent = CM.office_rent_index[sido], yld = CM.office_yield[sido];
    const vt = $("#office-vac-title"), yt = $("#office-yield-title");
    if (!vac || !rent || !yld) { // 세종: 오피스 임대동향 조사 대상 아님
      vt.textContent = sido + " — 오피스 조사 대상 아님";
      yt.textContent = sido + " — 오피스 조사 대상 아님";
      $("#chart-office-vac").innerHTML = $("#chart-office-rent").innerHTML = $("#chart-office-yield").innerHTML =
        `<p class="caption" style="padding:var(--sp-3) 0">${sido}은(는) 한국부동산원 오피스 임대동향조사 대상 지역이 아니다. 다른 시도를 선택해 보라.</p>`;
      $("#office-yield-cap").textContent = "";
      return;
    }
    vt.textContent = sido + " — 오피스 공실률·임대가격지수";
    yt.textContent = sido + " — 오피스 투자수익률 분해";
    C.line($("#chart-office-vac"), [
      { name: "공실률", color: "--s2", emph: true, points: mkq(vac) },
    ], { aria: sido + " 오피스 공실률", yFmt: v => v.toFixed(1) + "%", width: 700, height: 220, rightPad: 56 });
    C.line($("#chart-office-rent"), [
      { name: "임대지수", color: "--s1", emph: true, points: mkq(rent) },
    ], { aria: sido + " 오피스 임대가격지수", width: 700, height: 200, rightPad: 64 });
    C.line($("#chart-office-yield"), [
      { name: "투자", color: "--s1", emph: true, points: yld.map((p, i) => ({ x: i, label: p.yq.replace("Q", " Q"), y: p.total })) },
      { name: "소득", color: "--s2", points: yld.map((p, i) => ({ x: i, label: p.yq.replace("Q", " Q"), y: p.income })) },
      { name: "자본", color: "--s3", points: yld.map((p, i) => ({ x: i, label: p.yq.replace("Q", " Q"), y: p.capital })) },
    ], { aria: sido + " 오피스 투자수익률", yFmt: v => v.toFixed(1) + "%", width: 700, height: 452, rightPad: 60 });
    const lastY = yld[yld.length - 1];
    $("#office-yield-cap").textContent =
      `최근 분기(${lastY.yq}) 소득수익률 ${lastY.income.toFixed(2)}% — 연환산 약 ${(lastY.income * 4).toFixed(1)}%. ` +
      "이 값이 Ⅲ장 수익형 계산기 cap rate 가정의 실측 근거다 (자본수익률은 가격 변동분).";
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
      const pick = () => showCase(i, true);
      el2.addEventListener("click", pick);
      el2.addEventListener("keydown", e => { if (e.key === "Enter") pick(); });
      grid.appendChild(el2);
    });
    showCase(0);
  }
  function showCase(i, scroll) {
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
    C.waterfall($("#case-wf"), items, { width: 1160, height: 280 });
    $("#case-notes").innerHTML = c.notes.map(n => `<li>${n}</li>`).join("");
    if (scroll) revealEl($("#case-wf").closest("figure")); // 클릭 시에만 (첫 로드는 스크롤 금지)
    // 유기적 연결: 이 사례를 Ⅲ장 계산기 프리셋으로 열기 (검증된 프리셋 버튼 경로 재사용)
    const open = $("#case-open-calc");
    if (open) {
      open.hidden = !c.preset;
      open.onclick = () => {
        location.hash = "#/ch3";
        const btn = document.querySelector(`[data-preset="${c.preset}"]`);
        if (btn) btn.click();
      };
    }
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

  // ?selftest=chart — 차트 드래그 확대·시간 단위·유기 연결 실이벤트 검증
  function chartTest() {
    if (!location.search.includes("selftest=chart")) return;
    location.hash = "#/ch1";
    setTimeout(() => {
      const out = [];
      const root = $("#chart-detail");
      const svg = root.querySelector("svg");
      const hot = svg.querySelector('rect[fill="transparent"]');
      const r = svg.getBoundingClientRect();
      const pv = (type, fx) => hot.dispatchEvent(new PointerEvent(type, {
        bubbles: true, pointerId: 1, button: 0,
        clientX: r.left + r.width * fx, clientY: r.top + r.height / 2,
      }));
      const segCount = () => (root.querySelector("svg path").getAttribute("d").match(/L/g) || []).length;
      const before = segCount();
      // ① 드래그 확대
      pv("pointerdown", 0.3); pv("pointermove", 0.7); pv("pointerup", 0.7);
      const afterZoom = segCount();
      const resetVisible = !root.querySelector(".zoom-reset").hidden;
      out.push(`zoom:${afterZoom < before && resetVisible ? "PASS" : "FAIL"}(${before}→${afterZoom},reset=${resetVisible})`);
      // ② 단위 전환 (연) — 확대 유지된 채 포인트 축소
      const yearBtn = [...root.querySelectorAll(".unit-seg button")].find(b => b.textContent === "연");
      yearBtn.click();
      const afterYear = segCount();
      out.push(`unit연:${afterYear < afterZoom ? "PASS" : "FAIL"}(${afterYear})`);
      // ③ 더블클릭 리셋 + 월 복귀
      [...root.querySelectorAll(".unit-seg button")].find(b => b.textContent === "월").click();
      root.querySelector(".zoom-reset").click();
      out.push(`reset:${segCount() === before ? "PASS" : "FAIL"}`);
      // ④ 온도 진단 점 클릭 → 시도 전환
      const dots = [...document.querySelectorAll("#chart-phase circle")];
      const busan = dots.find(d => d.style.cursor === "pointer");
      if (busan) busan.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      out.push(`phase클릭:${busan ? "PASS" : "FAIL"}(fan=${$("#fan-title").textContent.slice(0, 6)})`);
      // ⑤ 벤치마크 행 클릭 → 모델 전환
      const row = [...document.querySelectorAll("#bench-body tr")].find(t => t.dataset.model === "chronos");
      row.click();
      out.push(`bench클릭:${$("#fan-title").textContent.includes("Chronos") ? "PASS" : "FAIL"}`);
      const badge = document.createElement("div");
      badge.id = "selftest-result";
      badge.textContent = "CHARTTEST " + out.join(" | ");
      badge.style.cssText = "position:fixed;top:60px;right:8px;z-index:99;background:#000;color:#0f0;padding:6px 10px;font-size:12px;font-family:monospace";
      document.body.appendChild(badge);
    }, 900);
  }

  function renderAll() {
    renderMarket(); renderForecast(); renderEda(); renderCommerce(); renderCases();
  }

  /* ---------- 부팅 ---------- */
  addEventListener("DOMContentLoaded", () => {
    initChrome(); initTheme(); counters();
    renderAll();
    window.CalcUI.init(CS.presets || {});
    addEventListener("hashchange", route);
    route();
    selfTest(); probe(); chartTest();
  });
})();
