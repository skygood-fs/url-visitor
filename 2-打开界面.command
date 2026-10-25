#!/bin/bash
cd "$(dirname "$0")" || exit 1
echo "正在打开界面 http://127.0.0.1:8765 ..."
echo
if ./service.sh status | grep -q "运行中"; then
  open "http://127.0.0.1:8765"
  echo "已打开。如果浏览器没反应，说明服务没启动，请先双击「1-启动服务」。"
else
  echo "服务当前没有在运行，请先双击「1-启动服务」。"
fi
echo
read -r -p "按 回车键 关闭本窗口..."
