#!/bin/bash
# url-visitor 服务管理
# 用法：./service.sh start | stop | restart | status | autostart-on | autostart-off | logs
set -u

DIR="$(cd "$(dirname "$0")" && pwd)"
# Python 解释器：优先仓库自带虚拟环境，其次本机已装环境，最后系统 python3
PY="$DIR/.venv/bin/python"
[ -x "$PY" ] || PY="$HOME/.workbuddy/binaries/python/envs/default/bin/python"
[ -x "$PY" ] || PY="$(command -v python3)"
PORT="${VV_PORT:-8765}"
LABEL="com.urlvisitor"
PIDFILE="$DIR/.uv.pid"
LOGFILE="$DIR/uv.log"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
URL="http://127.0.0.1:$PORT"
UID_NUM="$(id -u)"

port_busy() { lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; }
# 按端口找到占用进程的 PID（不管它是怎么启动的）
port_pid() { lsof -nP -iTCP:"$PORT" -sTCP:LISTEN -t 2>/dev/null | head -1; }
pid_alive() { [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE" 2>/dev/null)" 2>/dev/null; }
launchd_loaded() { launchctl list "$LABEL" >/dev/null 2>&1; }

wait_up() {
  for _ in $(seq 1 20); do
    port_busy && return 0
    sleep 0.5
  done
  return 1
}

do_start() {
  if port_busy; then
    echo "已经在运行了 → $URL"
    return 0
  fi
  if launchd_loaded; then
    launchctl kickstart "gui/$UID_NUM/$LABEL" 2>/dev/null || \
      launchctl bootstrap "gui/$UID_NUM" "$PLIST" 2>/dev/null
  else
    [ -f "$PIDFILE" ] && rm -f "$PIDFILE"
    (cd "$DIR" && VV_NO_OPEN=1 VV_PORT="$PORT" nohup "$PY" app.py >>"$LOGFILE" 2>&1 & echo $! >"$PIDFILE")
  fi
  if wait_up; then
    echo "已启动 → $URL"
    [ "${UV_OPEN:-1}" = "1" ] && command -v open >/dev/null && open "$URL"
  else
    echo "启动失败，看日志：tail -30 $LOGFILE"
    return 1
  fi
}

do_stop() {
  local stopped=0
  # 先摘掉 launchd，否则 KeepAlive 会立刻把进程拉起来
  if launchd_loaded; then
    launchctl bootout "gui/$UID_NUM/$LABEL" 2>/dev/null && stopped=1
  fi
  # 再按端口杀进程：无论是双击、nohup 还是手动 python 启动的都跑不掉
  local pid
  pid="$(port_pid)"
  if [ -n "$pid" ]; then
    kill "$pid" 2>/dev/null && stopped=1
    for _ in 1 2 3 4 5 6 7 8; do
      port_busy || break
      sleep 0.5
    done
    port_busy && kill -9 "$pid" 2>/dev/null
  fi
  rm -f "$PIDFILE"
  if [ "$stopped" = 1 ]; then
    echo "已停止"
    if [ -f "$PLIST" ]; then
      echo "（开机自启配置保留，下次开机/登录会自动回来；要彻底取消请执行 autostart-off）"
    fi
  else
    echo "当前没有在运行"
  fi
}

do_status() {
  if port_busy; then
    echo "状态：运行中 → $URL"
  else
    echo "状态：未运行"
  fi
  if launchd_loaded; then
    echo "开机自启：已开启（登录时自动启动，崩溃自动拉起）"
  elif [ -f "$PLIST" ]; then
    echo "开机自启：已配置，下次登录生效（现在可手动 ./service.sh start）"
  else
    echo "开机自启：未开启"
  fi
}

do_autostart_on() {
  mkdir -p "$HOME/Library/LaunchAgents"
  cat >"$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array><string>$PY</string><string>$DIR/app.py</string></array>
  <key>WorkingDirectory</key><string>$DIR</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>VV_PORT</key><string>$PORT</string>
    <key>VV_NO_OPEN</key><string>1</string>
    <key>PATH</key><string>/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$LOGFILE</string>
  <key>StandardErrorPath</key><string>$LOGFILE</string>
</dict>
</plist>
EOF
  launchctl bootout "gui/$UID_NUM/$LABEL" 2>/dev/null
  launchctl bootstrap "gui/$UID_NUM" "$PLIST" 2>/dev/null
  sleep 1
  if launchd_loaded; then
    echo "开机自启已开启：以后开机/登录自动启动，崩溃也会自动拉起"
  else
    # 非图形会话（SSH/脚本环境）里 bootstrap 会失败，但 plist 已就位，下次登录照样生效
    echo "已写入登录项，下次开机/登录自动启动（$PLIST）"
    echo "想立刻启动：在「终端」里执行 ./service.sh start"
  fi
}

do_autostart_off() {
  launchctl bootout "gui/$UID_NUM/$LABEL" 2>/dev/null
  rm -f "$PLIST"
  echo "开机自启已关闭，当前实例也已停止；需要时再 ./service.sh start"
}

case "${1:-status}" in
  start)         do_start ;;
  stop)          do_stop ;;
  restart)       do_stop; sleep 1; do_start ;;
  status)        do_status ;;
  autostart-on)  do_autostart_on ;;
  autostart-off) do_autostart_off ;;
  logs)          tail -f "$LOGFILE" ;;
  *)
    echo "用法：./service.sh start | stop | restart | status | autostart-on | autostart-off | logs"
    exit 1
    ;;
esac
