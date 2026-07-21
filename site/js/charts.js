/* ============================================================
   Charts — 인라인 SVG 차트 라이브러리 (외부 의존 0)
   규격: 2px 라인 · 얇은 마크 · 직접 라벨 · 크로스헤어 툴팁 ·
         절제된 그리드 · 시리즈 색은 토큰(--s1..) 고정 순서
   ============================================================ */
(function (global) {
  "use strict";
  const NS = "http://www.w3.org/2000/svg";

  /* ---------- 유틸 ---------- */
  function el(tag, attrs, parent) {
    const n = document.createElementNS(NS, tag);
    for (const k in attrs) n.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(n);
    return n;
  }
  function css(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }
  const fmt = {
    eok(v) { // 원 → 억원
      const e = v / 1e8;
      if (Math.abs(e) >= 10000) return (e / 10000).toFixed(1).replace(/\.0$/, "") + "조";
      if (Math.abs(e) >= 100) return Math.round(e).toLocaleString() + "억";
      return e.toFixed(1).replace(/\.0$/, "") + "억";
    },
    pct(v, d) { return (v * 100).toFixed(d == null ? 1 : d) + "%"; },
    num(v, d) { return Number(v).toLocaleString(undefined, { maximumFractionDigits: d == null ? 1 : d }); },
    ym(ym) { return ym.slice(0, 4) + "." + ym.slice(4); },
  };

  /* ---------- 툴팁 (싱글턴) ---------- */
  let tipEl = null;
  function tip() {
    if (!tipEl) {
      tipEl = document.createElement("div");
      tipEl.id = "tip";
      document.body.appendChild(tipEl);
    }
    return tipEl;
  }
  function tipShow(html, x, y) {
    const t = tip();
    t.innerHTML = html;
    t.style.left = x + "px";
    t.style.top = y + "px";
    t.classList.add("on");
  }
  function tipHide() { if (tipEl) tipEl.classList.remove("on"); }

  function extent(arr) {
    let lo = Infinity, hi = -Infinity;
    for (const v of arr) { if (v == null) continue; if (v < lo) lo = v; if (v > hi) hi = v; }
    if (lo === Infinity) { lo = 0; hi = 1; }
    if (lo === hi) { lo -= 1; hi += 1; }
    return [lo, hi];
  }
  function niceTicks(lo, hi, n) {
    const span = hi - lo, step0 = span / Math.max(1, n);
    const mag = Math.pow(10, Math.floor(Math.log10(step0)));
    const step = [1, 2, 2.5, 5, 10].map(m => m * mag).find(s => span / s <= n) || mag * 10;
    const ticks = [];
    for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) ticks.push(v);
    return ticks;
  }

  /* ---------- 라인 차트 (다중 계열 + 크로스헤어) ---------- */
  // series: [{name, color(css var명 "--s1"), points:[{x(index), label, y}]}]
  function line(root, series, opts) {
    opts = opts || {};
    const W = opts.width || 760, H = opts.height || 300;
    const M = { t: 14, r: opts.rightPad || 74, b: 26, l: 46 };
    root.innerHTML = "";
    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": opts.aria || "" }, root);
    const n = Math.max(...series.map(s => s.points.length));
    const ys = series.flatMap(s => s.points.map(p => p.y));
    let [lo, hi] = opts.yDomain || extent(ys);
    const pad = (hi - lo) * 0.08; lo -= pad; hi += pad;
    const x = i => M.l + (i / Math.max(1, n - 1)) * (W - M.l - M.r);
    const y = v => M.t + (1 - (v - lo) / (hi - lo)) * (H - M.t - M.b);

    // 그리드(수평만, 헤어라인) + y라벨
    for (const tv of niceTicks(lo, hi, 4)) {
      el("line", { x1: M.l, x2: W - M.r, y1: y(tv), y2: y(tv), stroke: css("--grid"), "stroke-width": 1 }, svg);
      el("text", { x: M.l - 7, y: y(tv) + 4, "text-anchor": "end", "font-size": 11.5, fill: css("--ink-3"), "font-family": "var(--font-num)" }, svg)
        .textContent = opts.yFmt ? opts.yFmt(tv) : fmt.num(tv, 0);
    }
    // x라벨 (양끝 + 중앙)
    const lp = series[0].points;
    [0, Math.floor((n - 1) / 2), n - 1].forEach(i => {
      if (!lp[i]) return;
      el("text", { x: x(i), y: H - 8, "text-anchor": i === 0 ? "start" : i === n - 1 ? "end" : "middle", "font-size": 11.5, fill: css("--ink-3") }, svg)
        .textContent = lp[i].label;
    });

    // 계열
    const ends = [];
    series.forEach(s => {
      const col = css(s.color || "--s1");
      const d = s.points.map((p, i) => (i ? "L" : "M") + x(p.x != null ? p.x : i).toFixed(1) + " " + y(p.y).toFixed(1)).join("");
      el("path", { d, fill: "none", stroke: col, "stroke-width": s.emph ? 2.6 : 2, "stroke-linejoin": "round", opacity: s.dim ? 0.35 : 1 }, svg);
      const last = s.points[s.points.length - 1];
      ends.push({ name: s.name, col, ty: y(last.y) + 4 });
    });
    // 직접 라벨 — 세로 충돌 회피(위→아래 정렬 후 최소 15px 간격 보장)
    ends.sort((a, b) => a.ty - b.ty);
    for (let i = 1; i < ends.length; i++) {
      if (ends[i].ty - ends[i - 1].ty < 15) ends[i].ty = ends[i - 1].ty + 15;
    }
    ends.forEach(e2 => {
      el("text", { x: W - M.r + 6, y: Math.min(H - M.b - 2, Math.max(M.t + 8, e2.ty)), "font-size": 12, "font-weight": 700, fill: e2.col }, svg)
        .textContent = e2.name;
    });

    // 크로스헤어 + 툴팁
    const cross = el("line", { y1: M.t, y2: H - M.b, stroke: css("--axis"), "stroke-width": 1, "stroke-dasharray": "3 3", opacity: 0 }, svg);
    const hot = el("rect", { x: M.l, y: M.t, width: W - M.l - M.r, height: H - M.t - M.b, fill: "transparent" }, svg);
    hot.addEventListener("mousemove", ev => {
      const r = svg.getBoundingClientRect();
      const px = (ev.clientX - r.left) * (W / r.width);
      const i = Math.round(((px - M.l) / (W - M.l - M.r)) * (n - 1));
      if (i < 0 || i >= n) return;
      cross.setAttribute("x1", x(i)); cross.setAttribute("x2", x(i)); cross.setAttribute("opacity", 1);
      const rows = series.map(s => {
        const p = s.points[i]; if (!p) return "";
        return `<div><span style="color:${css(s.color || "--s1")}">●</span> ${s.name} <b class="num">${opts.yFmt ? opts.yFmt(p.y) : fmt.num(p.y)}</b></div>`;
      }).join("");
      tipShow(`<div class="t-title">${lp[i] ? lp[i].label : ""}</div>${rows}`, ev.clientX, ev.clientY);
    });
    hot.addEventListener("mouseleave", () => { cross.setAttribute("opacity", 0); tipHide(); });
    return svg;
  }

  /* ---------- 스몰 멀티플 (시도별 스파크라인) ---------- */
  // data: {시도명: [{ym, value}...]}, onSelect(시도명)
  function smallMultiples(root, data, opts) {
    opts = opts || {};
    root.innerHTML = "";
    root.className = "smallmult";
    const names = opts.order || Object.keys(data);
    names.forEach(name => {
      const ser = data[name]; if (!ser || !ser.length) return;
      const cell = document.createElement("div");
      cell.className = "sm-cell" + (opts.selected === name ? " sel" : "");
      cell.setAttribute("role", "button"); cell.tabIndex = 0;
      const first = ser[0].value, last = ser[ser.length - 1].value;
      const yoyIdx = ser.length - 13;
      const yoy = yoyIdx >= 0 ? (last / ser[yoyIdx].value - 1) : (last / first - 1);
      const dir = yoy >= 0 ? "up" : "down";
      cell.innerHTML = `<div class="sm-name"><span>${name}</span><span class="sm-delta ${dir}">${yoy >= 0 ? "+" : ""}${(yoy * 100).toFixed(1)}%</span></div>`;
      const W = 150, H = 52;
      const svg = el("svg", { viewBox: `0 0 ${W} ${H}` });
      const [lo, hi] = extent(ser.map(p => p.value));
      const x = i => (i / (ser.length - 1)) * W;
      const y = v => 4 + (1 - (v - lo) / (hi - lo)) * (H - 8);
      const d = ser.map((p, i) => (i ? "L" : "M") + x(i).toFixed(1) + " " + y(p.value).toFixed(1)).join("");
      el("path", { d: d + `L${W} ${H}L0 ${H}Z`, fill: css("--blueprint-wash"), opacity: .7 }, svg);
      el("path", { d, fill: "none", stroke: css("--blueprint-2"), "stroke-width": 1.8 }, svg);
      el("circle", { cx: x(ser.length - 1), cy: y(last), r: 2.6, fill: css("--blueprint") }, svg);
      cell.appendChild(svg);
      const pick = () => opts.onSelect && opts.onSelect(name);
      cell.addEventListener("click", pick);
      cell.addEventListener("keydown", e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pick(); } });
      root.appendChild(cell);
    });
  }

  /* ---------- 워터폴 (수지 구조) ---------- */
  // items: [{name, value(+수입/−지출), kind:"in"|"out"|"sum"}]
  function waterfall(root, items, opts) {
    opts = opts || {};
    const W = opts.width || 760, H = opts.height || 320;
    const M = { t: 16, r: 16, b: 54, l: 16 };
    root.innerHTML = "";
    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": opts.aria || "수지 워터폴" }, root);
    let run = 0; const steps = [];
    items.forEach(it => {
      if (it.kind === "sum") { steps.push({ ...it, y0: 0, y1: run }); }
      else { steps.push({ ...it, y0: run, y1: run + it.value }); run += it.value; }
    });
    const hi = Math.max(...steps.map(s => Math.max(s.y0, s.y1)), 0);
    const lo = Math.min(...steps.map(s => Math.min(s.y0, s.y1)), 0);
    const y = v => M.t + (1 - (v - lo) / (hi - lo || 1)) * (H - M.t - M.b);
    const bw = (W - M.l - M.r) / steps.length;
    steps.forEach((s, i) => {
      const cx = M.l + i * bw;
      const isSum = s.kind === "sum";
      const col = isSum ? (s.y1 >= 0 ? css("--pos") : css("--neg")) : s.kind === "in" ? css("--s1") : css("--ink-3");
      const top = Math.min(y(s.y0), y(s.y1)), h = Math.max(2, Math.abs(y(s.y0) - y(s.y1)));
      const r = el("rect", { x: cx + bw * 0.14, y: top, width: bw * 0.72, height: h, fill: col, rx: 2, opacity: isSum ? 1 : 0.88 }, svg);
      // 연결선
      if (i < steps.length - 1 && !isSum) {
        el("line", { x1: cx + bw * 0.86, x2: cx + bw + bw * 0.14, y1: y(s.y1), y2: y(s.y1), stroke: css("--axis"), "stroke-width": 1, "stroke-dasharray": "2 3" }, svg);
      }
      // 라벨
      const tx = cx + bw / 2;
      el("text", { x: tx, y: H - 36, "text-anchor": "middle", "font-size": 11.5, fill: css("--ink-2"), "font-weight": isSum ? 800 : 400 }, svg)
        .textContent = s.name;
      el("text", { x: tx, y: H - 22, "text-anchor": "middle", "font-size": 11.5, "font-weight": 700, fill: col, "font-family": "var(--font-num)" }, svg)
        .textContent = fmt.eok(isSum ? s.y1 : s.value);
      r.addEventListener("mousemove", ev => tipShow(`<div class="t-title">${s.name}</div><b class="num">${fmt.eok(isSum ? s.y1 : s.value)}원</b>`, ev.clientX, ev.clientY));
      r.addEventListener("mouseleave", tipHide);
    });
    // 0 기준선
    el("line", { x1: M.l, x2: W - M.r, y1: y(0), y2: y(0), stroke: css("--axis"), "stroke-width": 1.2 }, svg);
    return svg;
  }

  /* ---------- 토네이도 (민감도) ---------- */
  // items: [{name, low, high, base}] — low/high = 변수 ±시 이익
  function tornado(root, items, base, opts) {
    opts = opts || {};
    const W = opts.width || 720, H = items.length * 44 + 40;
    const M = { t: 8, r: 70, b: 30, l: 128 };
    root.innerHTML = "";
    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "민감도 토네이도" }, root);
    const all = items.flatMap(it => [it.low, it.high]).concat([base]);
    let [lo, hi] = extent(all);
    const pad2 = (hi - lo) * 0.14 || 1; // 좌우 수치 라벨 자리 확보 (라벨-변수명 충돌 방지)
    lo -= pad2; hi += pad2;
    const x = v => M.l + ((v - lo) / (hi - lo || 1)) * (W - M.l - M.r);
    items.forEach((it, i) => {
      const cy = M.t + i * 44 + 22;
      el("text", { x: M.l - 10, y: cy + 4, "text-anchor": "end", "font-size": 12, "font-weight": 700, fill: css("--ink-2") }, svg).textContent = it.name;
      const xl = x(Math.min(it.low, it.high)), xr = x(Math.max(it.low, it.high));
      const neg = el("rect", { x: x(Math.min(it.low, base)), y: cy - 9, width: Math.abs(x(base) - x(Math.min(it.low, base))) || 1, height: 18, fill: css("--neg"), opacity: .78, rx: 2 }, svg);
      const pos = el("rect", { x: x(base), y: cy - 9, width: Math.abs(x(Math.max(it.high, base)) - x(base)) || 1, height: 18, fill: css("--s1"), opacity: .85, rx: 2 }, svg);
      el("text", { x: xl - 6, y: cy + 4, "text-anchor": "end", "font-size": 11.5, fill: css("--ink-3"), "font-family": "var(--font-num)" }, svg).textContent = fmt.eok(it.low);
      el("text", { x: xr + 6, y: cy + 4, "font-size": 11.5, fill: css("--ink-3"), "font-family": "var(--font-num)" }, svg).textContent = fmt.eok(it.high);
      [neg, pos].forEach(r2 => {
        r2.addEventListener("mousemove", ev => tipShow(
          `<div class="t-title">${it.name}</div>악화 <b class="num">${fmt.eok(it.low)}</b> · 기준 <b class="num">${fmt.eok(base)}</b> · 개선 <b class="num">${fmt.eok(it.high)}</b>`, ev.clientX, ev.clientY));
        r2.addEventListener("mouseleave", tipHide);
      });
    });
    el("line", { x1: x(base), x2: x(base), y1: M.t, y2: H - M.b, stroke: css("--ink"), "stroke-width": 1.4 }, svg);
    el("text", { x: x(base), y: H - 12, "text-anchor": "middle", "font-size": 12, "font-weight": 700, fill: css("--ink-2"), "font-family": "var(--font-num)" }, svg)
      .textContent = "기준 " + fmt.eok(base);
    return svg;
  }

  /* ---------- 히트맵 (2변수 손익분기) ---------- */
  // grid: {xs:[...], ys:[...], cells:[[v]]} v=이익
  function heatmap(root, grid, opts) {
    opts = opts || {};
    const W = opts.width || 720, cellH = 30;
    const M = { t: 30, r: 16, b: 44, l: 74 };
    const H = M.t + grid.ys.length * cellH + M.b;
    root.innerHTML = "";
    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "손익분기 히트맵" }, root);
    const cw = (W - M.l - M.r) / grid.xs.length;
    const vs = grid.cells.flat();
    const maxAbs = Math.max(...vs.map(Math.abs)) || 1;
    const seq = ["--seq-100", "--seq-200", "--seq-300", "--seq-400", "--seq-500", "--seq-600", "--seq-700"];
    grid.ys.forEach((yv, r) => {
      grid.xs.forEach((xv, c) => {
        const v = grid.cells[r][c];
        let fill;
        if (v < 0) fill = css("--neg");
        else fill = css(seq[Math.min(6, Math.floor((v / maxAbs) * 6.99))]);
        const rect = el("rect", {
          x: M.l + c * cw + 1, y: M.t + r * cellH + 1,
          width: cw - 2, height: cellH - 2, fill, rx: 2, opacity: v < 0 ? .8 : 1,
        }, svg);
        rect.addEventListener("mousemove", ev => tipShow(
          `<div class="t-title">${opts.xName || "X"} ${xv} · ${opts.yName || "Y"} ${yv}</div>이익 <b class="num">${fmt.eok(v)}원</b>`, ev.clientX, ev.clientY));
        rect.addEventListener("mouseleave", tipHide);
      });
      el("text", { x: M.l - 8, y: M.t + r * cellH + cellH / 2 + 4, "text-anchor": "end", "font-size": 11.5, fill: css("--ink-2"), "font-family": "var(--font-num)" }, svg).textContent = yv;
    });
    grid.xs.forEach((xv, c) => {
      el("text", { x: M.l + c * cw + cw / 2, y: H - M.b + 16, "text-anchor": "middle", "font-size": 11.5, fill: css("--ink-2"), "font-family": "var(--font-num)" }, svg).textContent = xv;
    });
    el("text", { x: M.l, y: 16, "font-size": 12, fill: css("--ink-3") }, svg).textContent = (opts.yName || "") + " ↓ / " + (opts.xName || "") + " →   (적색 = 손실)";
    return svg;
  }

  /* ---------- 게이지 (마진·IRR) ---------- */
  function gauge(root, value, opts) {
    opts = opts || {};
    const W = 168, H = 108, cx = W / 2, cy = 92, R = 66;
    const lo = opts.min != null ? opts.min : -0.1, hi = opts.max != null ? opts.max : 0.3;
    root.innerHTML = "";
    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": opts.label || "게이지" }, root);
    const arc = (a0, a1, color, w2) => {
      const p0 = [cx + R * Math.cos(a0), cy + R * Math.sin(a0)];
      const p1 = [cx + R * Math.cos(a1), cy + R * Math.sin(a1)];
      el("path", { d: `M${p0[0]} ${p0[1]} A${R} ${R} 0 ${a1 - a0 > Math.PI ? 1 : 0} 1 ${p1[0]} ${p1[1]}`, fill: "none", stroke: color, "stroke-width": w2, "stroke-linecap": "round" }, svg);
    };
    const A0 = Math.PI, A1 = 2 * Math.PI;
    arc(A0, A1, css("--surface-2"), 10);
    const t = Math.max(0, Math.min(1, (value - lo) / (hi - lo)));
    if (t > 0.001) arc(A0, A0 + t * Math.PI, value >= (opts.goodFrom != null ? opts.goodFrom : 0) ? css("--s1") : css("--neg"), 10);
    // 목표 눈금
    if (opts.target != null) {
      const ta = A0 + Math.max(0, Math.min(1, (opts.target - lo) / (hi - lo))) * Math.PI;
      el("line", { x1: cx + (R - 9) * Math.cos(ta), y1: cy + (R - 9) * Math.sin(ta), x2: cx + (R + 9) * Math.cos(ta), y2: cy + (R + 9) * Math.sin(ta), stroke: css("--ink-2"), "stroke-width": 2 }, svg);
    }
    const txt = el("text", { x: cx, y: cy - 8, "text-anchor": "middle", "font-size": 23, "font-weight": 700, fill: css("--ink"), "font-family": "var(--font-num)" }, svg);
    txt.textContent = opts.fmt ? opts.fmt(value) : fmt.pct(value);
    el("text", { x: cx, y: cy + 12, "text-anchor": "middle", "font-size": 11.5, fill: css("--ink-3") }, svg).textContent = opts.label || "";
    return svg;
  }

  /* ---------- 팬차트 (예측) ---------- */
  // hist: [{label, y}], fc: {median:[], q10:[], q90:[], labels:[]}
  function fan(root, hist, fc, opts) {
    opts = opts || {};
    const W = opts.width || 760, H = opts.height || 300;
    const M = { t: 14, r: 60, b: 26, l: 46 };
    root.innerHTML = "";
    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": opts.aria || "예측 팬차트" }, root);
    const n = hist.length + fc.median.length;
    const all = hist.map(p => p.y).concat(fc.q10, fc.q90);
    let [lo, hi] = extent(all); const pad = (hi - lo) * 0.1; lo -= pad; hi += pad;
    const x = i => M.l + (i / (n - 1)) * (W - M.l - M.r);
    const y = v => M.t + (1 - (v - lo) / (hi - lo)) * (H - M.t - M.b);
    for (const tv of niceTicks(lo, hi, 4)) {
      el("line", { x1: M.l, x2: W - M.r, y1: y(tv), y2: y(tv), stroke: css("--grid"), "stroke-width": 1 }, svg);
      el("text", { x: M.l - 7, y: y(tv) + 4, "text-anchor": "end", "font-size": 11.5, fill: css("--ink-3"), "font-family": "var(--font-num)" }, svg).textContent = fmt.num(tv, 0);
    }
    const h0 = hist.length - 1;
    // 80% 구간 밴드
    let band = "M" + x(h0) + " " + y(hist[h0].y);
    fc.q90.forEach((v, i) => band += "L" + x(h0 + 1 + i) + " " + y(v));
    for (let i = fc.q10.length - 1; i >= 0; i--) band += "L" + x(h0 + 1 + i) + " " + y(fc.q10[i]);
    band += "Z";
    el("path", { d: band, fill: css("--blueprint-wash"), opacity: .9 }, svg);
    // 실적선
    const dh = hist.map((p, i) => (i ? "L" : "M") + x(i).toFixed(1) + " " + y(p.y).toFixed(1)).join("");
    el("path", { d: dh, fill: "none", stroke: css("--ink-2"), "stroke-width": 2 }, svg);
    // 중앙값 예측선 (점선)
    let dm = "M" + x(h0) + " " + y(hist[h0].y);
    fc.median.forEach((v, i) => dm += "L" + x(h0 + 1 + i) + " " + y(v));
    el("path", { d: dm, fill: "none", stroke: css("--blueprint"), "stroke-width": 2.4, "stroke-dasharray": "5 4" }, svg);
    // 경계 수직선
    el("line", { x1: x(h0), x2: x(h0), y1: M.t, y2: H - M.b, stroke: css("--axis"), "stroke-width": 1, "stroke-dasharray": "3 3" }, svg);
    // 직접 라벨
    el("text", { x: W - M.r + 5, y: y(fc.median[fc.median.length - 1]) + 4, "font-size": 12, "font-weight": 700, fill: css("--blueprint") }, svg).textContent = "예측";
    el("text", { x: x(h0) - 5, y: M.t + 10, "text-anchor": "end", "font-size": 11.5, fill: css("--ink-3") }, svg).textContent = "실적←";
    // x 라벨
    const labels = hist.map(p => p.label).concat(fc.labels || []);
    [0, h0, n - 1].forEach(i => {
      el("text", { x: x(i), y: H - 8, "text-anchor": i === 0 ? "start" : i === n - 1 ? "end" : "middle", "font-size": 11.5, fill: css("--ink-3") }, svg).textContent = labels[i] || "";
    });
    // 호버
    const hot = el("rect", { x: M.l, y: M.t, width: W - M.l - M.r, height: H - M.t - M.b, fill: "transparent" }, svg);
    hot.addEventListener("mousemove", ev => {
      const r = svg.getBoundingClientRect();
      const px = (ev.clientX - r.left) * (W / r.width);
      const i = Math.round(((px - M.l) / (W - M.l - M.r)) * (n - 1));
      if (i < 0 || i >= n) return;
      let html;
      if (i <= h0) html = `<div class="t-title">${labels[i]}</div>실적 <b class="num">${fmt.num(hist[i].y)}</b>`;
      else {
        const j = i - h0 - 1;
        html = `<div class="t-title">${labels[i]} (예측)</div>중앙값 <b class="num">${fmt.num(fc.median[j])}</b><br>80% 구간 <span class="num">${fmt.num(fc.q10[j])} ~ ${fmt.num(fc.q90[j])}</span>`;
      }
      tipShow(html, ev.clientX, ev.clientY);
    });
    hot.addEventListener("mouseleave", tipHide);
    return svg;
  }

  /* ---------- 수평 바 (업종 구성 등) ---------- */
  // items: [{name, value}], 단일 계열 → 색 1개 + 직접 라벨
  function hbars(root, items, opts) {
    opts = opts || {};
    const W = opts.width || 760, rowH = opts.rowH || 40;
    const M = { t: 6, r: 96, b: 6, l: opts.labelW || 132 };
    const H = M.t + items.length * rowH + M.b;
    root.innerHTML = "";
    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": opts.aria || "" }, root);
    const hi = Math.max(...items.map(d => d.value)) || 1;
    items.forEach((d, i) => {
      const cy = M.t + i * rowH;
      const w2 = ((W - M.l - M.r) * d.value) / hi;
      el("text", { x: M.l - 11, y: cy + rowH / 2 + 5, "text-anchor": "end", "font-size": 13.5, fill: css("--ink-2"), "font-weight": 700 }, svg).textContent = d.name;
      const bar = el("rect", { x: M.l, y: cy + 8, width: Math.max(2, w2), height: rowH - 16, fill: css(opts.color || "--s1"), rx: 3, opacity: .92 }, svg);
      el("text", { x: M.l + Math.max(2, w2) + 9, y: cy + rowH / 2 + 5, "font-size": 13, fill: css("--ink-2"), "font-family": "var(--font-num)", "font-weight": 700 }, svg)
        .textContent = opts.fmt ? opts.fmt(d.value) : fmt.num(d.value, 0);
      bar.addEventListener("mousemove", ev => tipShow(`<div class="t-title">${d.name}</div><b class="num">${opts.fmt ? opts.fmt(d.value) : fmt.num(d.value, 0)}</b>`, ev.clientX, ev.clientY));
      bar.addEventListener("mouseleave", tipHide);
    });
    return svg;
  }

  /* ---------- 국면 사분면 (지수 YoY × 미분양 YoY) ---------- */
  // pts: [{name, x(미분양 증감%), y(지수 YoY%)}]
  function phase(root, pts, opts) {
    opts = opts || {};
    const W = opts.width || 720, H = 520;
    const M = { t: 28, r: 96, b: 44, l: 56 };
    root.innerHTML = "";
    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "시장 국면 맵" }, root);
    const xe = extent(pts.map(p => p.x)), ye = extent(pts.map(p => p.y));
    const xm = Math.max(Math.abs(xe[0]), Math.abs(xe[1])) * 1.15 || 1;
    const ym2 = Math.max(Math.abs(ye[0]), Math.abs(ye[1])) * 1.15 || 1;
    const x = v => M.l + ((v + xm) / (2 * xm)) * (W - M.l - M.r);
    const y = v => M.t + (1 - (v + ym2) / (2 * ym2)) * (H - M.t - M.b);
    // 사분면 배경 워시
    el("rect", { x: M.l, y: M.t, width: x(0) - M.l, height: y(0) - M.t, fill: css("--blueprint-wash"), opacity: .5 }, svg);   // 좌상: 회복·확장(미분양↓·지수↑)
    el("rect", { x: x(0), y: y(0), width: W - M.r - x(0), height: H - M.b - y(0), fill: css("--neg"), opacity: .06 }, svg);  // 우하: 침체
    // 축
    el("line", { x1: M.l, x2: W - M.r, y1: y(0), y2: y(0), stroke: css("--axis"), "stroke-width": 1.2 }, svg);
    el("line", { x1: x(0), x2: x(0), y1: M.t, y2: H - M.b, stroke: css("--axis"), "stroke-width": 1.2 }, svg);
    el("text", { x: W - 8, y: y(0) - 6, "text-anchor": "end", "font-size": 11.5, fill: css("--ink-3") }, svg).textContent = "미분양 증가 →";
    el("text", { x: x(0) + 6, y: M.t + 10, "font-size": 11.5, fill: css("--ink-3") }, svg).textContent = "↑ 가격 상승";
    const quad = [["확장", M.l + 8, M.t + 16], ["과열·공급과잉", W - M.r - 8, M.t + 16], ["회복", M.l + 8, H - M.b - 8], ["침체", W - M.r - 8, H - M.b - 8]];
    quad.forEach(([t2, tx, ty], i) => el("text", { x: tx, y: ty, "text-anchor": i % 2 ? "end" : "start", "font-size": 12, "font-weight": 800, fill: css("--ink-3"), opacity: .75 }, svg).textContent = t2);
    // 점 라벨 충돌 회피: 점·기배치 라벨을 장애물 삼아 8방향 후보 중 빈 자리, 없으면 최소겹침 자리
    const placed = pts.map(p => ({ x1: x(p.x) - 7, x2: x(p.x) + 7, y1: y(p.y) - 7, y2: y(p.y) + 7 }));
    const overlapArea = bx => placed.reduce((s2, b) => {
      const ox = Math.min(bx.x2, b.x2) - Math.max(bx.x1, b.x1);
      const oy = Math.min(bx.y2, b.y2) - Math.max(bx.y1, b.y1);
      return s2 + (ox > 0 && oy > 0 ? ox * oy : 0);
    }, 0);
    pts.forEach(p => {
      const cx0 = x(p.x), cy0 = y(p.y);
      const c = el("circle", { cx: cx0, cy: cy0, r: p.name === "전국" ? 7 : 5.5, fill: p.name === "전국" ? css("--seal") : css("--s1"), stroke: css("--surface"), "stroke-width": 2 }, svg);
      const tw = p.name.length * 11.6 + 4, th = 13;
      let cands = [
        { x: cx0 + 10, y: cy0 + 4, anchor: "start" },
        { x: cx0 - 10, y: cy0 + 4, anchor: "end" },
        { x: cx0, y: cy0 - 11, anchor: "middle" },
        { x: cx0, y: cy0 + 18, anchor: "middle" },
        { x: cx0 + 9, y: cy0 - 10, anchor: "start" },
        { x: cx0 + 9, y: cy0 + 16, anchor: "start" },
        { x: cx0 - 9, y: cy0 - 10, anchor: "end" },
        { x: cx0 - 9, y: cy0 + 16, anchor: "end" },
      ];
      if (cx0 > W - M.r - 60) cands = [cands[1], cands[6], cands[7], cands[2], cands[3], cands[0], cands[4], cands[5]];
      const boxOf = cd => {
        const x1 = cd.anchor === "start" ? cd.x : cd.anchor === "end" ? cd.x - tw : cd.x - tw / 2;
        return { x1, x2: x1 + tw, y1: cd.y - th, y2: cd.y + 2 };
      };
      let pick = cands[0], pickBox = boxOf(cands[0]), best = Infinity;
      for (const cd of cands) {
        const box = boxOf(cd), a = overlapArea(box);
        if (a === 0) { pick = cd; pickBox = box; break; }
        if (a < best) { best = a; pick = cd; pickBox = box; }
      }
      placed.push(pickBox);
      el("text", { x: pick.x, y: pick.y, "text-anchor": pick.anchor, "font-size": 11.5, "font-weight": 700, fill: css("--ink-2") }, svg).textContent = p.name;
      c.addEventListener("mousemove", ev => tipShow(`<div class="t-title">${p.name}</div>매매지수 1년 변동 <b class="num">${p.y >= 0 ? "+" : ""}${p.y.toFixed(1)}%</b><br>미분양 1년 증감 <b class="num">${p.x >= 0 ? "+" : ""}${p.x.toFixed(0)}%</b>`, ev.clientX, ev.clientY));
      c.addEventListener("mouseleave", tipHide);
    });
    return svg;
  }

  global.Charts = { line, smallMultiples, waterfall, tornado, heatmap, gauge, fan, hbars, phase, fmt, tipHide };
})(typeof window !== "undefined" ? window : globalThis);
