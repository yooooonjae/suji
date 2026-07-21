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
    const blocked = !ua || (!ALLOW.some(a => ua.includes(a)) && BLOCK.some(b => ua.includes(b)));
    if (blocked) {
      return new Response("403", {
        status: 403,
        headers: { "content-type": "text/plain; charset=utf-8", "x-robots-tag": "noindex, nofollow, noarchive" },
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
