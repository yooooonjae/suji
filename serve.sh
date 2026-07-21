#!/bin/zsh
# 「수지(收支)」 로컬 서버 — http://localhost:8765
cd "$(dirname "$0")"
exec python3 -m http.server 8765 --directory web
