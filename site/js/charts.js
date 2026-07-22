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
  // 단일 색상 명도 변조 (amt -1..1) — 그라데이션 스톱용. 동일 색상군 내 깊이감만 주고
  // 값 인코딩은 길이/위치가 담당한다 (색은 정체성 유지).
  function shade(hex, amt) {
    const h = hex.replace("#", "");
    const f = h.length === 3 ? h.split("").map(c => c + c).join("") : h;
    const n = parseInt(f, 16);
    if (isNaN(n)) return hex;
    const t = amt < 0 ? 0 : 255, a = Math.abs(amt);
    const r = Math.round(((n >> 16) & 255) + (t - ((n >> 16) & 255)) * a);
    const g = Math.round(((n >> 8) & 255) + (t - ((n >> 8) & 255)) * a);
    const b = Math.round((n & 255) + (t - (n & 255)) * a);
    return "#" + ((r << 16) | (g << 8) | b).toString(16).padStart(6, "0");
  }
  // SVG 그라데이션 (차트당 색상별 1회 정의, fill용 url 반환). dir: "h"(좌→우)|"v"(상→하)
  let gradSeq = 0;
  function grad(svg, color, dir, s0, s1, o0, o1) {
    if (!svg._grads) svg._grads = new Map();
    const key = color + dir + s0 + s1 + (o0 || 1) + (o1 || 1);
    if (svg._grads.has(key)) return svg._grads.get(key);
    let defs = svg.querySelector("defs") || el("defs", {}, svg);
    const id = "gr" + (++gradSeq);
    const lg = el("linearGradient", dir === "v"
      ? { id, x1: 0, y1: 0, x2: 0, y2: 1 } : { id, x1: 0, y1: 0, x2: 1, y2: 0 }, defs);
    el("stop", { offset: "0%", "stop-color": shade(color, s0), "stop-opacity": o0 == null ? 1 : o0 }, lg);
    el("stop", { offset: "100%", "stop-color": shade(color, s1), "stop-opacity": o1 == null ? 1 : o1 }, lg);
    const url = `url(#${id})`;
    svg._grads.set(key, url);
    return url;
  }
  const fmt = {
    eok(v) { // 원 → 억원
      const e = v / 1e8, a = Math.abs(e);
      if (a >= 9999.5) return (e / 10000).toFixed(1).replace(/\.0$/, "") + "조"; // 억 반올림으로 1조 도달분 포함
      if (a >= 100) return Math.round(e).toLocaleString() + "억";
      const t = e.toFixed(1).replace(/\.0$/, "");
      return (t === "-0" ? "0" : t) + "억";
    },
    pct(v, d) { const t = (v * 100).toFixed(d == null ? 1 : d); return (parseFloat(t) === 0 ? t.replace("-", "") : t) + "%"; },
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

  // 이산 마크(히트맵·워터폴·토네이도·수평바·산점) 툴팁 바인딩 공통화 — 데스크톱 hover +
  // 모바일 탭 동시 지원. html: () => string. pointer 이벤트라 마우스·터치 동일 경로.
  let tipDocBound = false;
  function bindTip(node, html) {
    const show = ev => { const p = (ev.touches && ev.touches[0]) || ev; tipShow(html(), p.clientX, p.clientY); };
    node.addEventListener("pointerenter", show);
    node.addEventListener("pointermove", show);
    node.addEventListener("click", show);
    node.addEventListener("pointerleave", tipHide);
    if (!tipDocBound) { // 차트 밖을 탭하면 툴팁 닫기 (1회 등록)
      tipDocBound = true;
      document.addEventListener("pointerdown", ev => {
        if (!(ev.target && ev.target.closest && ev.target.closest("svg"))) tipHide();
      });
    }
  }

  // 다계열 라인 정렬 — 계열을 라벨 합집합(정렬) 기준으로 재색인해 툴팁·수직선의 인덱스 i가
  // 전 계열에서 같은 날짜를 가리키게 한다. 결측은 NaN(엔진의 Number.isFinite 가드가 갭 처리).
  function alignByLabel(series) {
    const labels = [...new Set(series.flatMap(s => s.points.map(p => p.label)))].sort();
    return series.map(s => {
      const byLabel = new Map(s.points.map(p => [p.label, p.y]));
      return { ...s, points: labels.map((label, x) => ({ x, label, y: byLabel.has(label) ? byLabel.get(label) : NaN })) };
    });
  }
  // 이미 동일 라벨 시퀀스면 정렬 불필요 — 사전순 정렬이 오히려 깨뜨리는 라벨(예: "Q10"<"Q2")을 보호.
  function labelsAligned(series) {
    const a = series[0].points;
    return series.every(s => s.points.length === a.length && s.points.every((p, i) => p.label === a[i].label));
  }

  function extent(arr) {
    let lo = Infinity, hi = -Infinity;
    for (const v of arr) { if (!Number.isFinite(v)) continue; if (v < lo) lo = v; if (v > hi) hi = v; }
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

  /* ---------- 차트 인터랙션 공통 (트레이딩뷰식) ---------- */
  // 라벨 → 연 단위 시간값. "2016.07"→2016.54, "2016 Q3"→2016.63, "2016"→2016.5
  function timeOf(label) {
    if (/^\d{4}\.\d{2}$/.test(label)) return +label.slice(0, 4) + (+label.slice(5) - 0.5) / 12;
    const q = /^(\d{4}) Q(\d)$/.exec(label);
    if (q) return +q[1] + (+q[2] * 3 - 1.5) / 12;
    if (/^\d{4}$/.test(label)) return +label + 0.5;
    return null;
  }
  // 툴바: [단위 세그먼트] … 힌트 · [↺ 전체 보기]
  function makeTools(root, units, onUnit, onReset, curUnit) {
    const bar = document.createElement("div");
    bar.className = "chart-tools";
    const unitBtns = {};
    if (units) {
      const seg = document.createElement("div");
      seg.className = "unit-seg"; seg.setAttribute("role", "group"); seg.setAttribute("aria-label", "시간 단위");
      units.forEach(u => {
        const b = document.createElement("button");
        b.type = "button"; b.textContent = u;
        b.setAttribute("aria-pressed", String(u === curUnit));
        b.addEventListener("click", () => {
          for (const k in unitBtns) unitBtns[k].setAttribute("aria-pressed", String(k === u));
          onUnit(u);
        });
        seg.appendChild(b); unitBtns[u] = b;
      });
      bar.appendChild(seg);
    }
    const hint = document.createElement("span");
    hint.className = "zoom-hint"; hint.textContent = "드래그로 구간 확대 · 더블클릭으로 전체 보기";
    bar.appendChild(hint);
    const resetBtn = document.createElement("button");
    resetBtn.type = "button"; resetBtn.className = "zoom-reset"; resetBtn.hidden = true;
    resetBtn.textContent = "↺ 전체 보기";
    resetBtn.addEventListener("click", onReset);
    bar.appendChild(resetBtn);
    root.appendChild(bar);
    return resetBtn;
  }

  /* ---------- 라인 차트 (다중 계열 + 크로스헤어 + 드래그 확대 + 시간 단위) ---------- */
  // series: [{name, color(css var명 "--s1"), points:[{x(index), label, y}]}]
  // 원천이 월간 통계라 최소 단위는 월 — 분기·연은 기간 평균 집계.
  // 줌·단위 상태는 root._chartState 에 보존 (테마 전환·시도 전환 재렌더에도 유지).
  function line(root, series, opts) {
    opts = opts || {};
    const W = opts.width || 1160, H = opts.height || 300;
    const M = { t: 14, r: opts.rightPad || 74, b: 26, l: 46 };
    root.innerHTML = "";

    series = series.filter(s => s.points && s.points.length); // 빈 계열 제거 (기준 계열 크래시 방지)
    if (!series.length) {
      root.innerHTML = '<p class="caption" style="padding:12px 0">표시할 자료가 없다.</p>';
      return null;
    }
    // 다계열이 라벨 불일치면 라벨 기준 조인 (툴팁·수직선 인덱스 정합). 이미 정렬됐으면 무해하게 건너뜀.
    if (series.length > 1 && !labelsAligned(series)) series = alignByLabel(series);
    const isYm = series[0].points.length > 0 &&
      series.every(s => s.points.every(p => /^\d{4}\.\d{2}$/.test(p.label || "")));
    const interactive = opts.interactive !== false;
    const st = root._chartState || (root._chartState = { unit: "월", view: null });
    if (!isYm) st.unit = "월";

    // 시간값: 시간형 라벨이 아니면 전역 인덱스로 대체 (줌만 지원)
    const tval = (p, gi) => { const t = timeOf(p.label || ""); return t == null ? gi : t; };

    function aggregate() {
      if (!isYm || st.unit === "월") return series;
      return series.map(s => {
        const order = [], byKey = new Map();
        s.points.forEach(p => {
          if (!Number.isFinite(p.y)) return; // 결측은 평균 분모에서 제외 (codex 지적)
          const yr = p.label.slice(0, 4), mo = +p.label.slice(5);
          const key = st.unit === "연" ? yr : yr + " Q" + (Math.floor((mo - 1) / 3) + 1);
          if (!byKey.has(key)) { byKey.set(key, []); order.push(key); }
          byKey.get(key).push(p.y);
        });
        return { ...s, points: order.map((k, i) => ({ x: i, label: k, y: byKey.get(k).reduce((a, b) => a + b, 0) / byKey.get(k).length })) };
      });
    }

    let resetBtn = null;
    if (interactive) {
      resetBtn = makeTools(root, isYm ? ["월", "분기", "연"] : null,
        u => { st.unit = u; draw(); }, () => { st.view = null; draw(); }, st.unit);
    }
    const box = document.createElement("div");
    root.appendChild(box);

    let lastSvg = null;
    function draw() {
      const S = aggregate();
      const base = S[0].points;
      let i0 = 0, i1 = base.length - 1;
      if (st.view) {
        let a = base.findIndex((p, i) => tval(p, i) >= st.view[0]);
        let b = -1;
        for (let i = base.length - 1; i >= 0; i--) if (tval(base[i], i) <= st.view[1]) { b = i; break; }
        if (a >= 0 && b >= 0) {
          while (b - a < 2 && (a > 0 || b < base.length - 1)) { // 최소 3포인트 확보 (전환 시 줌 소실 방지)
            if (a > 0) a--;
            if (b - a < 2 && b < base.length - 1) b++;
          }
          if (b - a >= 2) { i0 = a; i1 = b; } else st.view = null;
        } else st.view = null;
      }
      if (resetBtn) resetBtn.hidden = !st.view;
      const V = S.map(s => ({ ...s, points: s.points.slice(i0, i1 + 1) }));

      box.innerHTML = "";
      const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": opts.aria || "" }, box);
      lastSvg = svg;
      const n = Math.max(...V.map(s => s.points.length));
      const ys = V.flatMap(s => s.points.map(p => p.y));
      let [lo, hi] = opts.yDomain || extent(ys); // 보이는 구간 기준 y 자동 스케일
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
      const lp = V[0].points;
      [0, Math.floor((n - 1) / 2), n - 1].forEach(i => {
        if (!lp[i]) return;
        el("text", { x: x(i), y: H - 8, "text-anchor": i === 0 ? "start" : i === n - 1 ? "end" : "middle", "font-size": 11.5, fill: css("--ink-3") }, svg)
          .textContent = lp[i].label;
      });

      // 계열 (강조 계열엔 은은한 영역 워시 — 스몰멀티플과 동일 문법)
      const ends = [];
      V.forEach(s => {
        if (!s.points.length) return;
        const col = css(s.color || "--s1");
        let d = "", pen = false; // 비유한 y는 갭 — 선을 끊는다 (codex 지적)
        s.points.forEach((p, i) => {
          if (!Number.isFinite(p.y)) { pen = false; return; }
          d += (pen ? "L" : "M") + x(i).toFixed(1) + " " + y(p.y).toFixed(1);
          pen = true;
        });
        if (s.emph && !s.dim) {
          const base = H - M.b;
          const area = d + `L${x(s.points.length - 1).toFixed(1)} ${base}L${x(0).toFixed(1)} ${base}Z`;
          el("path", { d: area, fill: grad(svg, col, "v", 0, 0, 0.14, 0), "pointer-events": "none" }, svg);
        }
        el("path", { d, fill: "none", stroke: col, "stroke-width": s.emph ? 2.6 : 2, "stroke-linejoin": "round", opacity: s.dim ? 0.35 : 1 }, svg);
        // 라벨 앵커는 마지막 유한점 (라벨 조인으로 말단이 결측일 수 있음 — NaN 위치 방지)
        let last = null;
        for (let li = s.points.length - 1; li >= 0; li--) { if (Number.isFinite(s.points[li].y)) { last = s.points[li]; break; } }
        if (last) ends.push({ name: s.name, col, ty: y(last.y) + 4 });
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

      // 크로스헤어 + 선택 영역 + 툴팁
      const cross = el("line", { y1: M.t, y2: H - M.b, stroke: css("--axis"), "stroke-width": 1, "stroke-dasharray": "3 3", opacity: 0 }, svg);
      const selRect = el("rect", { x: 0, y: M.t, width: 0, height: H - M.t - M.b, fill: css("--blueprint"), opacity: 0, "pointer-events": "none" }, svg);
      const hot = el("rect", { x: M.l, y: M.t, width: W - M.l - M.r, height: H - M.t - M.b, fill: "transparent" }, svg);
      hot.style.touchAction = "pan-y";          // 모바일 세로 스크롤 보존
      if (interactive) hot.style.cursor = "crosshair";
      const pxOf = ev => { const r = svg.getBoundingClientRect(); return (ev.clientX - r.left) * (W / r.width); };
      const idxOf = px => Math.round(((px - M.l) / (W - M.l - M.r)) * (n - 1));
      let dragFrom = null;

      hot.addEventListener("pointerdown", ev => {
        if (!interactive || ev.button > 0) return;
        dragFrom = pxOf(ev);
        try { hot.setPointerCapture(ev.pointerId); } catch (e) { /* 합성 이벤트 */ }
      });
      hot.addEventListener("pointermove", ev => {
        const px = pxOf(ev);
        if (dragFrom != null) {
          tipHide(); cross.setAttribute("opacity", 0);
          const a = Math.max(M.l, Math.min(dragFrom, px)), b = Math.min(W - M.r, Math.max(dragFrom, px));
          selRect.setAttribute("x", a); selRect.setAttribute("width", Math.max(0, b - a));
          selRect.setAttribute("opacity", 0.16);
          return;
        }
        const i = idxOf(px);
        if (i < 0 || i >= n) return;
        cross.setAttribute("x1", x(i)); cross.setAttribute("x2", x(i)); cross.setAttribute("opacity", 1);
        const rows = V.map(s => {
          const p = s.points[i]; if (!p) return "";
          return `<div><span style="color:${css(s.color || "--s1")}">●</span> ${s.name} <b class="num">${opts.yFmt ? opts.yFmt(p.y) : fmt.num(p.y)}</b></div>`;
        }).join("");
        const unitTag = st.unit === "월" ? "" : ` <span style="opacity:.7">(${st.unit}평균)</span>`;
        tipShow(`<div class="t-title">${lp[i] ? lp[i].label : ""}${unitTag}</div>${rows}`, ev.clientX, ev.clientY);
      });
      const endDrag = ev => {
        if (dragFrom == null) return;
        const a = Math.min(dragFrom, pxOf(ev)), b = Math.max(dragFrom, pxOf(ev));
        dragFrom = null; selRect.setAttribute("opacity", 0);
        const ia = Math.max(0, idxOf(a)), ib = Math.min(n - 1, idxOf(b));
        if (ib - ia >= 2) { st.view = [tval(lp[ia], i0 + ia), tval(lp[ib], i0 + ib)]; draw(); }
      };
      hot.addEventListener("pointerup", endDrag);
      hot.addEventListener("pointercancel", () => { dragFrom = null; selRect.setAttribute("opacity", 0); });
      hot.addEventListener("mouseleave", () => { cross.setAttribute("opacity", 0); tipHide(); });
      hot.addEventListener("dblclick", () => { st.view = null; draw(); });
    }
    draw();
    return lastSvg;
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
      const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, "aria-hidden": "true" });
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
    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": opts.aria || "수지 구성도" }, root);
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
      const r = el("rect", { x: cx + bw * 0.14, y: top, width: bw * 0.72, height: h,
        fill: grad(svg, col, "v", 0.12, -0.14), rx: 5, opacity: isSum ? 1 : 0.9 }, svg);
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
      bindTip(r, () => `<div class="t-title">${s.name}</div><b class="num">${fmt.eok(isSum ? s.y1 : s.value)}원</b>`);
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
    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "민감도 그래프" }, root);
    const all = items.flatMap(it => [it.low, it.high]).concat([base]);
    let [lo, hi] = extent(all);
    const pad2 = (hi - lo) * 0.14 || 1; // 좌우 수치 라벨 자리 확보 (라벨-변수명 충돌 방지)
    lo -= pad2; hi += pad2;
    const x = v => M.l + ((v - lo) / (hi - lo || 1)) * (W - M.l - M.r);
    items.forEach((it, i) => {
      const cy = M.t + i * 44 + 22;
      el("text", { x: M.l - 10, y: cy + 4, "text-anchor": "end", "font-size": 12, "font-weight": 700, fill: css("--ink-2") }, svg).textContent = it.name;
      const xl = x(Math.min(it.low, it.high)), xr = x(Math.max(it.low, it.high));
      const neg = el("rect", { x: x(Math.min(it.low, base)), y: cy - 9, width: Math.abs(x(base) - x(Math.min(it.low, base))) || 1, height: 18, fill: css("--neg"), opacity: .78, rx: 5 }, svg);
      const pos = el("rect", { x: x(base), y: cy - 9, width: Math.abs(x(Math.max(it.high, base)) - x(base)) || 1, height: 18, fill: css("--s1"), opacity: .85, rx: 5 }, svg);
      el("text", { x: xl - 6, y: cy + 4, "text-anchor": "end", "font-size": 11.5, fill: css("--ink-3"), "font-family": "var(--font-num)" }, svg).textContent = fmt.eok(it.low);
      el("text", { x: xr + 6, y: cy + 4, "font-size": 11.5, fill: css("--ink-3"), "font-family": "var(--font-num)" }, svg).textContent = fmt.eok(it.high);
      [neg, pos].forEach(r2 => bindTip(r2, () =>
        `<div class="t-title">${it.name}</div>나빠질 때 <b class="num">${fmt.eok(it.low)}</b> · 현재 기준 <b class="num">${fmt.eok(base)}</b> · 좋아질 때 <b class="num">${fmt.eok(it.high)}</b>`));
    });
    el("line", { x1: x(base), x2: x(base), y1: M.t, y2: H - M.b, stroke: css("--ink"), "stroke-width": 1.4 }, svg);
    el("text", { x: x(base), y: H - 12, "text-anchor": "middle", "font-size": 12, "font-weight": 700, fill: css("--ink-2"), "font-family": "var(--font-num)" }, svg)
      .textContent = "기준 " + fmt.eok(base);
    return svg;
  }

  /* ---------- 히트맵 (2변수 손익분기 · 상관 등 범용) ---------- */
  // grid: {xs:[...], ys:[...], cells:[[v]]}
  // opts.vFmt: 값 포맷(기본 억원) · opts.vLabel: 값 명칭 · opts.legend: 상단 범례 문구
  // opts.cellText: 셀 안에 값 직접 표기 · 음수는 |v| 강도에 비례한 적색
  function heatmap(root, grid, opts) {
    opts = opts || {};
    const W = opts.width || 720, cellH = opts.cellH || 30;
    const M = { t: 30, r: 16, b: 44, l: opts.labelW || 74 };
    const H = M.t + grid.ys.length * cellH + M.b;
    root.innerHTML = "";
    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": opts.aria || "손익분기 지도" }, root);
    const cw = (W - M.l - M.r) / grid.xs.length;
    const vs = grid.cells.flat().filter(Number.isFinite);
    const maxAbs = Math.max(...vs.map(Math.abs)) || 1;
    const seq = ["--seq-100", "--seq-200", "--seq-300", "--seq-400", "--seq-500", "--seq-600", "--seq-700"];
    const vFmt = opts.vFmt || (v => fmt.eok(v) + "원");
    grid.ys.forEach((yv, r) => {
      grid.xs.forEach((xv, c) => {
        const v = grid.cells[r][c];
        if (!Number.isFinite(v)) { // 결측 — 무상관(0)으로 위장하지 않고 빈 셀로 (codex 지적)
          const miss = el("rect", { x: M.l + c * cw + 1, y: M.t + r * cellH + 1,
            width: cw - 2, height: cellH - 2, fill: css("--surface-2"), rx: 5,
            stroke: css("--hairline"), "stroke-dasharray": "3 3" }, svg);
          bindTip(miss, () =>
            `<div class="t-title">${opts.xName || "X"} ${xv} · ${opts.yName || "Y"} ${yv}</div>자료 없음`);
          return;
        }
        // 발산형 파랑↔주황: 음수 = 파랑(강도 비례), 양수 = 주황 램프 (한국 관행: 하락=파랑)
        let fill, op;
        if (v < 0) { fill = css("--s2"); op = 0.22 + 0.68 * (Math.abs(v) / maxAbs); }
        else { fill = css(seq[Math.min(6, Math.floor((v / maxAbs) * 6.99))]); op = 1; }
        const rect = el("rect", {
          x: M.l + c * cw + 1, y: M.t + r * cellH + 1,
          width: cw - 2, height: cellH - 2, fill, rx: 5, opacity: op,
        }, svg);
        if (opts.cellText) {
          const strong = Math.abs(v) / maxAbs > 0.5; // 진한 배경에만 흰 글자 (연한 셀은 먹색 — 대비 확보)
          el("text", { x: M.l + c * cw + cw / 2, y: M.t + r * cellH + cellH / 2 + 4, "text-anchor": "middle",
            "font-size": 11.5, "font-weight": 700, "font-family": "var(--font-num)", "pointer-events": "none",
            fill: strong ? "#fff" : css("--ink-2") }, svg).textContent = (opts.cellFmt || vFmt)(v);
        }
        bindTip(rect, () =>
          `<div class="t-title">${opts.xName || "X"} ${xv} · ${opts.yName || "Y"} ${yv}</div>${opts.vLabel || "이익"} <b class="num">${vFmt(v)}</b>`);
      });
      el("text", { x: M.l - 8, y: M.t + r * cellH + cellH / 2 + 4, "text-anchor": "end", "font-size": 11.5, fill: css("--ink-2"), "font-family": "var(--font-num)" }, svg).textContent = yv;
    });
    grid.xs.forEach((xv, c) => {
      el("text", { x: M.l + c * cw + cw / 2, y: H - M.b + 16, "text-anchor": "middle", "font-size": 11.5, fill: css("--ink-2"), "font-family": "var(--font-num)" }, svg).textContent = xv;
    });
    el("text", { x: M.l, y: 16, "font-size": 12, fill: css("--ink-3") }, svg)
      .textContent = opts.legend != null ? opts.legend : (opts.yName || "") + " ↓ / " + (opts.xName || "") + " →   (파랑 = 손실, 주황 = 이익)";
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
    if (t > 0.001) {
      const gc = value >= (opts.goodFrom != null ? opts.goodFrom : 0) ? css("--s1") : css("--neg");
      arc(A0, A0 + t * Math.PI, grad(svg, gc, "h", -0.16, 0.14), 10);
    }
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

  /* ---------- 팬차트 (예측 + 드래그 확대) ---------- */
  // hist: [{label, y}], fc: {median:[], q10:[], q90:[], labels:[]}
  // 줌 상태는 root._chartState.view = [za, zb] (전역 인덱스) — 재렌더에도 유지.
  function fan(root, hist, fc, opts) {
    opts = opts || {};
    const W = opts.width || 960, H = opts.height || 320;
    const M = { t: 14, r: 60, b: 26, l: 46 };
    root.innerHTML = "";
    const N = hist.length + fc.median.length;
    const labels = hist.map(p => p.label).concat(fc.labels || []);
    const interactive = opts.interactive !== false;
    const st = root._chartState || (root._chartState = { view: null });
    let resetBtn = null;
    if (interactive) {
      resetBtn = makeTools(root, null, null, () => { st.view = null; draw(); }, null);
    }
    const box = document.createElement("div");
    root.appendChild(box);

    let lastSvg = null;
    function draw() {
      let za = 0, zb = N - 1;
      if (st.view) {
        za = Math.max(0, st.view[0]); zb = Math.min(N - 1, st.view[1]);
        if (zb - za < 2) { st.view = null; za = 0; zb = N - 1; }
      }
      if (resetBtn) resetBtn.hidden = !st.view;
      const n = zb - za + 1;
      // 보이는 구간의 실적/예측 분할 (h0v = 실적 마지막의 로컬 인덱스, 없으면 -1)
      const h0v = Math.min(hist.length - 1, zb) - za;      // <0 이면 예측만 보임
      const fcFrom = Math.max(0, za - hist.length);        // 보이는 예측 시작 (fc 인덱스)
      const fcTo = zb - hist.length;                       // 보이는 예측 끝 (<0 이면 실적만)

      box.innerHTML = "";
      const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": opts.aria || "12개월 예측 그래프" }, box);
      lastSvg = svg;
      const vis = [];
      for (let i = za; i <= zb; i++) {
        if (i < hist.length) vis.push(hist[i].y);
        else { const j = i - hist.length; vis.push(fc.q10[j], fc.q90[j], fc.median[j]); }
      }
      let [lo, hi] = extent(vis); const pad = (hi - lo) * 0.1 || 1; lo -= pad; hi += pad;
      const x = gi => M.l + ((gi - za) / Math.max(1, n - 1)) * (W - M.l - M.r);
      const y = v => M.t + (1 - (v - lo) / (hi - lo)) * (H - M.t - M.b);
      for (const tv of niceTicks(lo, hi, 4)) {
        el("line", { x1: M.l, x2: W - M.r, y1: y(tv), y2: y(tv), stroke: css("--grid"), "stroke-width": 1 }, svg);
        el("text", { x: M.l - 7, y: y(tv) + 4, "text-anchor": "end", "font-size": 11.5, fill: css("--ink-3"), "font-family": "var(--font-num)" }, svg).textContent = fmt.num(tv, 0);
      }
      const h0 = hist.length - 1;
      // 80% 구간 밴드 (보이는 예측 구간만; 실적 마지막이 보이면 그 점에서 시작)
      if (fcTo >= 0) {
        const anchor = h0v >= 0 && za <= h0;
        let band = "";
        if (anchor && fcFrom === 0) band = "M" + x(h0) + " " + y(hist[h0].y);
        else band = "M" + x(hist.length + fcFrom) + " " + y(fc.q90[fcFrom]);
        for (let j = fcFrom; j <= fcTo; j++) band += "L" + x(hist.length + j) + " " + y(fc.q90[j]);
        for (let j = fcTo; j >= fcFrom; j--) band += "L" + x(hist.length + j) + " " + y(fc.q10[j]);
        band += "Z";
        el("path", { d: band, fill: grad(svg, css("--blueprint-wash"), "h", 0, -0.04, 0.55, 0.95) }, svg);
      }
      // 실적선
      if (h0v >= 0) {
        let dh = "";
        for (let i = za; i <= Math.min(h0, zb); i++) dh += (dh ? "L" : "M") + x(i).toFixed(1) + " " + y(hist[i].y).toFixed(1);
        el("path", { d: dh, fill: "none", stroke: css("--ink-2"), "stroke-width": 2 }, svg);
      }
      // 중앙값 예측선 (점선)
      if (fcTo >= 0) {
        let dm = (h0v >= 0 && za <= h0 && fcFrom === 0) ? "M" + x(h0) + " " + y(hist[h0].y) : "";
        for (let j = fcFrom; j <= fcTo; j++) dm += (dm ? "L" : "M") + x(hist.length + j) + " " + y(fc.median[j]);
        el("path", { d: dm, fill: "none", stroke: css("--blueprint"), "stroke-width": 2.4, "stroke-dasharray": "5 4" }, svg);
        el("text", { x: W - M.r + 5, y: y(fc.median[fcTo]) + 4, "font-size": 12, "font-weight": 700, fill: css("--blueprint") }, svg).textContent = "예측";
      }
      // 실적/예측 경계 수직선
      if (za <= h0 && zb > h0) {
        el("line", { x1: x(h0), x2: x(h0), y1: M.t, y2: H - M.b, stroke: css("--axis"), "stroke-width": 1, "stroke-dasharray": "3 3" }, svg);
        el("text", { x: x(h0) - 5, y: M.t + 10, "text-anchor": "end", "font-size": 11.5, fill: css("--ink-3") }, svg).textContent = "← 실적";
      }
      // x 라벨
      [za, za <= h0 && zb > h0 ? h0 : Math.round((za + zb) / 2), zb].forEach(gi => {
        el("text", { x: x(gi), y: H - 8, "text-anchor": gi === za ? "start" : gi === zb ? "end" : "middle", "font-size": 11.5, fill: css("--ink-3") }, svg).textContent = labels[gi] || "";
      });
      // 호버 + 드래그 확대
      const selRect = el("rect", { x: 0, y: M.t, width: 0, height: H - M.t - M.b, fill: css("--blueprint"), opacity: 0, "pointer-events": "none" }, svg);
      const hot = el("rect", { x: M.l, y: M.t, width: W - M.l - M.r, height: H - M.t - M.b, fill: "transparent" }, svg);
      hot.style.touchAction = "pan-y";
      if (interactive) hot.style.cursor = "crosshair";
      const pxOf = ev => { const r = svg.getBoundingClientRect(); return (ev.clientX - r.left) * (W / r.width); };
      const giOf = px => za + Math.round(((px - M.l) / (W - M.l - M.r)) * (n - 1));
      let dragFrom = null;
      hot.addEventListener("pointerdown", ev => {
        if (!interactive || ev.button > 0) return;
        dragFrom = pxOf(ev);
        try { hot.setPointerCapture(ev.pointerId); } catch (e) { /* 합성 이벤트 */ }
      });
      hot.addEventListener("pointermove", ev => {
        const px = pxOf(ev);
        if (dragFrom != null) {
          tipHide();
          const a = Math.max(M.l, Math.min(dragFrom, px)), b = Math.min(W - M.r, Math.max(dragFrom, px));
          selRect.setAttribute("x", a); selRect.setAttribute("width", Math.max(0, b - a));
          selRect.setAttribute("opacity", 0.16);
          return;
        }
        const i = giOf(px);
        if (i < za || i > zb) return;
        let html;
        if (i <= h0) html = `<div class="t-title">${labels[i]}</div>실적 <b class="num">${fmt.num(hist[i].y)}</b>`;
        else {
          const j = i - h0 - 1;
          html = `<div class="t-title">${labels[i]} (예측)</div>중앙값 <b class="num">${fmt.num(fc.median[j])}</b><br>80% 구간 <span class="num">${fmt.num(fc.q10[j])} ~ ${fmt.num(fc.q90[j])}</span>`;
        }
        tipShow(html, ev.clientX, ev.clientY);
      });
      const endDrag = ev => {
        if (dragFrom == null) return;
        const a = Math.min(dragFrom, pxOf(ev)), b = Math.max(dragFrom, pxOf(ev));
        dragFrom = null; selRect.setAttribute("opacity", 0);
        const ia = Math.max(0, giOf(a)), ib = Math.min(N - 1, giOf(b));
        if (ib - ia >= 2) { st.view = [ia, ib]; draw(); }
      };
      hot.addEventListener("pointerup", endDrag);
      hot.addEventListener("pointercancel", () => { dragFrom = null; selRect.setAttribute("opacity", 0); });
      hot.addEventListener("mouseleave", tipHide);
      hot.addEventListener("dblclick", () => { st.view = null; draw(); });
    }
    draw();
    return lastSvg;
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
    // 결측(value가 유한수 아님)은 스케일에서 제외 — NaN 하나가 전체 폭을 오염시키지 않게
    const finite = items.filter(d => Number.isFinite(d.value));
    const hi = Math.max(...finite.map(d => d.value), 0) || 1;
    items.forEach((d, i) => {
      const cy = M.t + i * rowH;
      if (!Number.isFinite(d.value)) { // 결측 행: 바 없이 사유 표기
        el("text", { x: M.l - 11, y: cy + rowH / 2 + 5, "text-anchor": "end", "font-size": 13.5, fill: css("--ink-3"), "font-weight": 700 }, svg).textContent = d.name;
        el("text", { x: M.l, y: cy + rowH / 2 + 5, "font-size": 12, fill: css("--ink-3"), "font-style": "italic" }, svg)
          .textContent = d.note || "자료 없음";
        return;
      }
      const w2 = ((W - M.l - M.r) * d.value) / hi;
      const isSel = opts.selected === d.name;
      const isEm = isSel || (opts.emph && opts.emph.indexOf(d.name) >= 0); // 강조 행(예: 강남3구)
      const lab = el("text", { x: M.l - 11, y: cy + rowH / 2 + 5, "text-anchor": "end", "font-size": 13.5, fill: isEm ? css("--blueprint") : css("--ink-2"), "font-weight": isEm ? 800 : 700 }, svg);
      lab.textContent = d.name;
      const barCol = css(isEm ? "--s1" : (opts.color || "--s1"));
      const bar = el("rect", { x: M.l, y: cy + 8, width: Math.max(2, w2), height: rowH - 16,
        fill: grad(svg, barCol, "h", -0.18, 0.16), rx: 6, opacity: isSel ? 1 : .95 }, svg);
      el("text", { x: M.l + Math.max(2, w2) + 9, y: cy + rowH / 2 + 5, "font-size": 13, fill: css("--ink-2"), "font-family": "var(--font-num)", "font-weight": 700 }, svg)
        .textContent = opts.fmt ? opts.fmt(d.value) : fmt.num(d.value, 0);
      bindTip(bar, () => `<div class="t-title">${d.name}</div><b class="num">${opts.fmt ? opts.fmt(d.value) : fmt.num(d.value, 0)}</b>${opts.onSelect ? '<br><span style="opacity:.7">클릭: 상세 보기</span>' : ""}`);
      if (opts.onSelect) {
        [bar, lab].forEach(nd => {
          nd.style.cursor = "pointer";
          nd.addEventListener("click", () => opts.onSelect(d.name));
        });
        bar.setAttribute("role", "button");
        bar.setAttribute("tabindex", "0");
        bar.setAttribute("aria-label", d.name + " 선택");
        bar.addEventListener("keydown", ev => {
          if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); opts.onSelect(d.name); }
        });
      }
    });
    return svg;
  }

  /* ---------- 국면 사분면 (지수 YoY × 미분양 YoY) ---------- */
  // pts: [{name, x(미분양 증감%), y(지수 YoY%)}]
  function phase(root, pts, opts) {
    opts = opts || {};
    const W = opts.width || 1160, H = 470;
    const M = { t: 28, r: 96, b: 44, l: 56 };
    root.innerHTML = "";
    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "시장 온도 진단" }, root);
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
    const quad = [["확장기", M.l + 8, M.t + 16], ["둔화기", W - M.r - 8, M.t + 16], ["회복기", M.l + 8, H - M.b - 8], ["침체기", W - M.r - 8, H - M.b - 8]];
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
      const isSel = opts.selected === p.name;
      // 파랑 기조 + 전국·선택 시도만 주황 강조 (파랑 혼용 지시)
      const c = el("circle", { cx: cx0, cy: cy0, r: p.name === "전국" ? 7 : isSel ? 7 : 5.5, fill: p.name === "전국" || isSel ? css("--s1") : css("--s2"), stroke: isSel ? css("--ink") : css("--surface"), "stroke-width": 2 }, svg);
      if (opts.onSelect && p.name !== "전국") {
        c.style.cursor = "pointer";
        c.addEventListener("click", () => opts.onSelect(p.name));
        c.setAttribute("role", "button");
        c.setAttribute("tabindex", "0");
        c.setAttribute("aria-label", p.name + " 상세 보기");
        c.addEventListener("keydown", ev => {
          if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); opts.onSelect(p.name); }
        });
      }
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
      bindTip(c, () => `<div class="t-title">${p.name}</div>매매지수 1년 변동 <b class="num">${p.y >= 0 ? "+" : ""}${p.y.toFixed(1)}%</b><br>미분양 1년 증감 <b class="num">${p.x >= 0 ? "+" : ""}${p.x.toFixed(0)}%</b>`);
    });
    return svg;
  }

  global.Charts = { line, smallMultiples, waterfall, tornado, heatmap, gauge, fan, hbars, phase, fmt, tipHide };
})(typeof window !== "undefined" ? window : globalThis);
