#!/bin/bash
# 双击或在终端执行本文件即可启动；启动后自动打开 http://127.0.0.1:8765
cd "$(dirname "$0")"
PY="$(cd "$(dirname "$0")" && pwd)/.venv/bin/python"
[ -x "$PY" ] || PY="$HOME/.workbuddy/binaries/python/envs/default/bin/python"
[ -x "$PY" ] || PY="python3"
exec "$PY" app.py
