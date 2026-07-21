#!/bin/zsh
# 「수지(收支)」 로컬 서버 (수동 기동용) — 보호 서버(serve.py)로 위임.
# 봇 UA 필터·noindex 헤더 포함. 상시 서빙은 launchd com.suji.web 담당.
exec /usr/bin/python3 "$(dirname "$0")/serve.py" "${1:-8765}"
