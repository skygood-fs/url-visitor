#!/bin/bash
cd "$(dirname "$0")" || exit 1
echo "========================================"
echo "  网址自动访问器 —— 状态"
echo "========================================"
echo
./service.sh status
echo
echo "界面地址：http://127.0.0.1:8765"
echo
read -r -p "按 回车键 关闭本窗口..."
