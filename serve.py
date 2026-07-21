#!/usr/bin/env python3
"""「수지(收支)」 보호 서버 — web/ 정적 서빙 + 봇 차단 + 보안 헤더.

- 검색엔진·크롤러·AI봇·스크립트 UA 403 (링크 미리보기 봇은 예외 — 링크드인 카드용)
- X-Robots-Tag: noindex — 헤더 수준 색인 금지
- 실행: python3 serve.py  (기본 포트 8765)
"""

import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

WEB = Path(__file__).resolve().parent / "web"
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8765

BLOCK = ("googlebot", "bingbot", "yandexbot", "baiduspider", "duckduckbot",
         "semrush", "ahrefs", "mj12bot", "petalbot", "bytespider", "gptbot",
         "ccbot", "claudebot", "claude-web", "amazonbot", "applebot",
         "crawler", "spider", "scrapy", "curl/", "wget/", "python-requests",
         "python-urllib", "go-http-client", "okhttp", "httpx", "aiohttp")
# 링크 카드 미리보기 봇 허용 (게시물 썸네일 생성)
ALLOW = ("linkedinbot", "twitterbot", "facebookexternalhit", "slackbot",
         "kakaotalk-scrap", "telegrambot", "discordbot", "whatsapp")


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(WEB), **kw)

    def end_headers(self):
        self.send_header("X-Robots-Tag", "noindex, nofollow, noarchive")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        super().end_headers()

    def _blocked(self) -> bool:
        ua = (self.headers.get("User-Agent") or "").lower()
        if not ua:
            return True
        if any(a in ua for a in ALLOW):
            return False
        return any(b in ua for b in BLOCK)

    def do_GET(self):
        if self._blocked():
            self.send_response(403)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"403")
            return
        super().do_GET()

    do_HEAD = do_GET

    def log_message(self, fmt, *args):  # 소음 축소: 403·오류만 기록
        if args and str(args[1]).startswith(("4", "5")):
            super().log_message(fmt, *args)


if __name__ == "__main__":
    print(f"수지 서버: http://localhost:{PORT} ← {WEB}")
    ThreadingHTTPServer(("", PORT), Handler).serve_forever()
