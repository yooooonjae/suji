/* Cloudflare Pages 엣지 워커 — serve.py의 보호 규칙을 동일 재현.
   빈 UA·크롤러·AI봇·스크립트 403 (링크 카드 미리보기 봇은 예외) + 보안 헤더. */

const BLOCK = ["googlebot", "bingbot", "yandexbot", "baiduspider", "duckduckbot",
  "semrush", "ahrefs", "mj12bot", "petalbot", "bytespider", "gptbot",
  "ccbot", "claudebot", "claude-web", "amazonbot", "applebot",
  "crawler", "spider", "scrapy", "curl/", "wget/", "python-requests",
  "python-urllib", "go-http-client", "okhttp", "httpx", "aiohttp"];
const ALLOW = ["linkedinbot", "twitterbot", "facebookexternalhit", "slackbot",
  "kakaotalk-scrap", "telegrambot", "discordbot", "whatsapp"];

export default {
  async fetch(request, env) {
    const ua = (request.headers.get("user-agent") || "").toLowerCase();
    // 정적 이미지(og·파비콘 등)는 UA 관계없이 개방 — 링크 미리보기 페처가
    // LinkedInBot 외 UA로 이미지를 가져와도 카드가 생성되게 한다.
    // (보호 대상은 HTML 콘텐츠·코드이지 이미지가 아님)
    if (/\.(png|jpe?g|gif|webp|svg|ico)$/i.test(new URL(request.url).pathname)) {
      const img = await env.ASSETS.fetch(request);
      const ih = new Headers(img.headers);
      ih.set("X-Content-Type-Options", "nosniff");
      return new Response(img.body, { status: img.status, headers: ih });
    }
    // 차단 토큰이 있으면 무조건 차단 — allow 토큰을 섞어 붙인 우회("Slackbot GPTBot") 방지.
    // ALLOW는 향후 BLOCK에 일반 토큰이 추가될 때 미리보기 봇을 구제하는 목적의 목록으로 유지.
    const blockHit = BLOCK.some(b => ua.includes(b));
    const blocked = !ua || blockHit; // 현 BLOCK 목록엔 미리보기 봇과 겹치는 토큰 없음 (겹치면 ALLOW로 구제)
    if (blocked) {
      return new Response("403", {
        status: 403,
        headers: {
          "content-type": "text/plain; charset=utf-8",
          "x-robots-tag": "noindex, nofollow, noarchive",
          "x-content-type-options": "nosniff",
          "x-frame-options": "DENY",
          "referrer-policy": "no-referrer",
        },
      });
    }
    const res = await env.ASSETS.fetch(request);
    const h = new Headers(res.headers);
    h.set("X-Robots-Tag", "noindex, nofollow, noarchive");
    h.set("X-Content-Type-Options", "nosniff");
    h.set("X-Frame-Options", "DENY");
    h.set("Referrer-Policy", "no-referrer");
    return new Response(res.body, { status: res.status, statusText: res.statusText, headers: h });
  },
};
