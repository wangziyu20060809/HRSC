#!/usr/bin/env bash
# 一键启动本地预览服务：http://127.0.0.1:8777
set -e
cd "$(dirname "$0")/../src"
echo "HRSC Demo: http://127.0.0.1:8777  (Ctrl+C 停止)"
exec python -m http.server 8777 --bind 127.0.0.1
