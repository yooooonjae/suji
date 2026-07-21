/* Cloudflare Pages 엣지 워커 — 보안 헤더만 부여.
   (2026-07-21) UA 봇 차단을 제거: 링크 미리보기 크롤러(링크드인 등)가 UA·IP에
   따라 막히는 것을 원천 차단하기 위함. 코드 보호는 JS 난독화(terser)로 유지하고,
   검색 노출 정책은 HTML의 robots 메타로 관리(빌드 토글). */

export default {
  async fetch(request, env) {
    const res = await env.ASSETS.fetch(request);
    const h = new Headers(res.headers);
    h.set("X-Content-Type-Options", "nosniff");
    h.set("X-Frame-Options", "DENY");
    h.set("Referrer-Policy", "no-referrer");
    return new Response(res.body, { status: res.status, statusText: res.statusText, headers: h });
  },
};
