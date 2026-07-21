/* ============================================================
   guard — 공개 배포 보호 레이어 (localhost에서는 비활성)
   주의: 클라이언트 코드는 원천적으로 완전 보호가 불가능하다.
   본 레이어는 캐주얼한 복제(우클릭·단축키·개발자도구)를 억제하는
   실효 수준의 장치이며, 그 한계를 인지하고 사용한다.
   ============================================================ */
(function () {
  "use strict";
  const h = location.hostname;
  if (h === "localhost" || h === "127.0.0.1" || h === "") return; // 로컬 개발 예외

  // 1) 우클릭·이미지 드래그 차단
  addEventListener("contextmenu", e => e.preventDefault());
  addEventListener("dragstart", e => e.preventDefault());

  // 2) 개발자도구·소스보기 단축키 차단
  addEventListener("keydown", e => {
    const k = e.key.toUpperCase();
    const meta = e.ctrlKey || e.metaKey;
    if (e.key === "F12" ||
        (meta && e.shiftKey && (k === "I" || k === "J" || k === "C")) ||
        (meta && e.altKey && (k === "I" || k === "J" || k === "C" || k === "U")) ||
        (meta && (k === "U" || k === "S"))) {
      e.preventDefault(); e.stopPropagation();
    }
  }, true);

  // 3) 개발자도구 열림 휴리스틱 → 안내 오버레이 (완전 차단이 아닌 억제)
  let overlay = null;
  function checkDevtools() {
    const gapW = window.outerWidth - window.innerWidth;
    const gapH = window.outerHeight - window.innerHeight;
    const open = gapW > 200 || gapH > 220;
    if (open && !overlay) {
      overlay = document.createElement("div");
      overlay.style.cssText = "position:fixed;inset:0;z-index:9999;display:grid;place-items:center;" +
        "background:color-mix(in srgb, var(--ground) 92%, transparent);backdrop-filter:blur(14px);" +
        "font-weight:800;font-size:18px;color:var(--ink-2);text-align:center;padding:24px";
      overlay.textContent = "본 연구는 저작물입니다 — 코드·데이터의 무단 복제를 삼가주세요.";
      document.body.appendChild(overlay);
    } else if (!open && overlay) {
      overlay.remove(); overlay = null;
    }
  }
  setInterval(checkDevtools, 800);

  // 4) 인쇄 차단 — @media print에서 본문을 숨기고 고지문만 출력.
  //    (스크린샷은 OS 영역이라 웹 기술로 차단 불가 — 한계 인지하고 인쇄만 막는다)
  const printCss = document.createElement("style");
  printCss.textContent =
    "@media print { body > * { display: none !important; } " +
    "body::before { content: '본 연구는 저작물입니다 — 인쇄가 허용되지 않습니다. 열람: yooooonjae.pages.dev'; " +
    "display: block; padding: 48px; font-size: 16px; font-weight: 700; } }";
  document.head.appendChild(printCss);
  addEventListener("beforeprint", () => { /* 차단 CSS가 본문을 숨김 — 이벤트는 흔적용 */ });
  addEventListener("keydown", e => {
    if ((e.ctrlKey || e.metaKey) && e.key.toUpperCase() === "P") { e.preventDefault(); e.stopPropagation(); }
  }, true);

  // 5) 콘솔 저작권 고지
  try {
    console.log("%c수지(收支) — 개인 연구 저작물", "font-size:16px;font-weight:800;color:#1e5d95");
    console.log("코드·데이터의 무단 복제와 재배포를 금합니다.");
  } catch (_) { /* noop */ }
})();
