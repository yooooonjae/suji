if (typeof WebSocket === "undefined") { console.log("skip: 이 Node에는 내장 WebSocket이 없어 반응형 검사를 건너뜀(로컬 Node 22+에서 실행됨)"); process.exit(0); }
#!/usr/bin/env node
/*
 * responsive_check.js — 경량 다중 해상도 반응형 스모크 (Playwright 없이 CDP 직접)
 *
 * 검사 (5뷰포트: 320×740·390×844·768×1024·1024×768·1440×900):
 *   ① 가로 오버플로 0        — document.documentElement.scrollWidth ≤ clientWidth
 *   ② 핵심 터치 타깃 ≥ 44px  — 44px 미디어쿼리가 적용되는 뷰포트에서만(보이는 요소 한정)
 *
 * 브라우저: 시스템 Chrome/Chromium 헤드리스(CDP over WebSocket, 의존성 0).
 *   미탐지 시 skip(exit 0) — 로컬·CI green 유지. (스크린샷 픽셀 회귀는 제외)
 *
 * 대상 파일: RESP_TARGET(env) 우선, 없으면 아래 TARGET 기본값.
 */
'use strict';
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawn, spawnSync } = require('node:child_process');
const { pathToFileURL } = require('node:url');

const ROOT = path.resolve(__dirname, '..');

/* ─── repo별 설정 (여기만 저장소마다 다름) ─────────────────────────── */
const TARGET = process.env.RESP_TARGET
  ? path.resolve(process.env.RESP_TARGET)
  : path.join(ROOT, "web/index.html");            // 빌드 산출물
// 터치 타깃: {sel, maxWidth} — maxWidth 이하 뷰포트에서만 44px 요구(미디어쿼리 반영)
const TOUCH = [
  { sel: ".mode-tabs button", maxWidth: 640 },
  { sel: ".preset-row button", maxWidth: 640 },
  { sel: ".chart-tools button", maxWidth: 640 },
  { sel: ".km-metros .btn", maxWidth: 640 },
];
/* ──────────────────────────────────────────────────────────────── */

const VIEWPORTS = [
  { w: 320, h: 740 }, { w: 390, h: 844 },
  { w: 768, h: 1024 }, { w: 1024, h: 768 }, { w: 1440, h: 900 },
];
const MIN_TOUCH = 44;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function findChrome() {
  const cands = [
    process.env.CHROME, process.env.CHROME_PATH,
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    '/Applications/Chromium.app/Contents/MacOS/Chromium',
    '/usr/bin/google-chrome', '/usr/bin/google-chrome-stable',
    '/usr/bin/chromium', '/usr/bin/chromium-browser', '/snap/bin/chromium',
  ].filter(Boolean);
  for (const c of cands) { try { if (fs.existsSync(c)) return c; } catch { /* ignore */ } }
  for (const bin of ['google-chrome', 'google-chrome-stable', 'chromium', 'chromium-browser', 'chrome']) {
    const r = spawnSync(process.platform === 'win32' ? 'where' : 'which', [bin], { encoding: 'utf8' });
    if (r.status === 0 && r.stdout.trim()) return r.stdout.trim().split('\n')[0];
  }
  return null;
}

// 최소 CDP 클라이언트 (Node 내장 global WebSocket 사용)
class CDP {
  constructor(url) {
    this.ws = new WebSocket(url);
    this.id = 0; this.pending = new Map(); this.waiters = new Map();
    this.ws.addEventListener('message', (ev) => {
      const m = JSON.parse(ev.data);
      if (m.id && this.pending.has(m.id)) {
        const { res, rej } = this.pending.get(m.id); this.pending.delete(m.id);
        m.error ? rej(new Error(m.error.message)) : res(m.result);
      } else if (m.method && this.waiters.has(m.method)) {
        const w = this.waiters.get(m.method); this.waiters.delete(m.method); w();
      }
    });
  }
  ready() {
    return new Promise((res, rej) => {
      this.ws.addEventListener('open', () => res());
      this.ws.addEventListener('error', () => rej(new Error('WebSocket 오류')));
    });
  }
  send(method, params = {}) {
    const id = ++this.id;
    return new Promise((res, rej) => {
      this.pending.set(id, { res, rej });
      this.ws.send(JSON.stringify({ id, method, params }));
    });
  }
  wait(method) { return new Promise((res) => this.waiters.set(method, res)); }
  close() { try { this.ws.close(); } catch { /* ignore */ } }
}

async function waitReady(port) {
  for (let i = 0; i < 120; i++) {
    try { const r = await fetch(`http://127.0.0.1:${port}/json/version`); if (r.ok) return; } catch { /* not up yet */ }
    await sleep(100);
  }
  throw new Error('Chrome DevTools 엔드포인트 응답 없음');
}
async function pageWsUrl(port) {
  const r = await fetch(`http://127.0.0.1:${port}/json`);
  const list = await r.json();
  const page = list.find((t) => t.type === 'page' && t.webSocketDebuggerUrl);
  if (!page) throw new Error('page 타깃 없음');
  return page.webSocketDebuggerUrl;
}

async function main() {
  if (!fs.existsSync(TARGET)) {
    // 산출물 부재 → skip(exit 0). CI에서 빌드가 선행되지 않았거나 로컬 빌드 전일 때 green 유지.
    console.log(`· 대상 없음(${path.relative(ROOT, TARGET)}) → 반응형 검사 skip (먼저 빌드 필요, exit 0)`);
    process.exit(0);
  }
  const chrome = findChrome();
  if (!chrome) { console.log('· Chrome/Chromium 미탐지 → 반응형 검사 skip (exit 0)'); process.exit(0); }

  const port = 9200 + Math.floor(Math.random() * 700);
  const udd = fs.mkdtempSync(path.join(os.tmpdir(), 'resp-'));
  const proc = spawn(chrome, [
    '--headless=new', '--disable-gpu', '--no-sandbox', '--no-first-run',
    '--no-default-browser-check', '--disable-extensions', '--disable-background-networking',
    `--remote-debugging-port=${port}`, `--user-data-dir=${udd}`, 'about:blank',
  ], { stdio: 'ignore' });
  let cleaned = false;
  const cleanup = () => {
    if (cleaned) return; cleaned = true;
    try { proc.kill('SIGKILL'); } catch { /* ignore */ }
    try { fs.rmSync(udd, { recursive: true, force: true }); } catch { /* ignore */ }
  };
  process.on('exit', cleanup);
  process.on('SIGINT', () => { cleanup(); process.exit(130); });

  let exitCode = 0;
  try {
    await waitReady(port);
    const ws = new CDP(await pageWsUrl(port));
    await ws.ready();
    await ws.send('Page.enable');
    await ws.send('Runtime.enable');

    const fileUrl = pathToFileURL(TARGET).href;
    const rows = [];
    for (const vp of VIEWPORTS) {
      await ws.send('Emulation.setDeviceMetricsOverride', {
        width: vp.w, height: vp.h, deviceScaleFactor: 1, mobile: false,
      });
      const loaded = ws.wait('Page.loadEventFired');
      await ws.send('Page.navigate', { url: fileUrl });
      await Promise.race([loaded, sleep(9000)]);
      await sleep(550); // settle: 폰트·인라인 JS 렌더

      const sels = TOUCH.filter((t) => vp.w <= t.maxWidth).map((t) => t.sel);
      const expr = `(() => {
        const de = document.documentElement;
        const bad = [];
        for (const sel of ${JSON.stringify(sels)}) {
          for (const el of document.querySelectorAll(sel)) {
            const cs = getComputedStyle(el);
            if (cs.display === 'none' || cs.visibility === 'hidden') continue;
            const r = el.getBoundingClientRect();
            if (r.width === 0 || r.height === 0) continue;
            if (r.height < ${MIN_TOUCH} - 0.5) bad.push(sel + '=' + r.height.toFixed(1) + 'px');
          }
        }
        return JSON.stringify({ sw: de.scrollWidth, cw: de.clientWidth, bad });
      })()`;
      const res = await ws.send('Runtime.evaluate', { expression: expr, returnByValue: true });
      if (res.exceptionDetails) throw new Error('페이지 평가 예외: ' + (res.result && res.result.description || 'unknown'));
      const { sw, cw, bad } = JSON.parse(res.result.value);
      const overflow = sw > cw + 1; // 스크롤바 서브픽셀 여유 1px
      rows.push({ vp: `${vp.w}×${vp.h}`, sw, cw, overflow, bad });
    }
    ws.close();

    console.log(`\n반응형 스모크 — ${path.relative(ROOT, TARGET)}`);
    console.log('  viewport      scrollW  clientW  overflow  touch<44px');
    console.log('  ' + '-'.repeat(62));
    let failed = 0;
    for (const r of rows) {
      const ov = r.overflow ? '✗ YES' : '✓ no';
      const tt = r.bad.length ? '✗ ' + r.bad.join(', ') : '✓ ok';
      if (r.overflow || r.bad.length) failed++;
      console.log(`  ${r.vp.padEnd(12)} ${String(r.sw).padStart(6)}  ${String(r.cw).padStart(7)}  ${ov.padEnd(8)}  ${tt}`);
    }
    if (failed) { console.error(`\n✗ 반응형 검사 실패 ${failed}/${rows.length} 뷰포트`); exitCode = 1; }
    else console.log(`\n✓ 반응형 검사 통과 (${rows.length} 뷰포트 · 가로 오버플로 0 · 터치 타깃 ≥ ${MIN_TOUCH}px)`);
  } catch (e) {
    console.error('✗ 반응형 검사 오류:', e.message); exitCode = 1;
  } finally {
    cleanup();
  }
  process.exit(exitCode);
}

main();
