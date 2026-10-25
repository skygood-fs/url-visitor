#!/bin/bash
cd "$(dirname "$0")" || exit 1
echo "========================================"
echo "  网址自动访问器 —— 发布到 GitHub"
echo "========================================"
echo

if [ -z "$(git log --oneline 2>/dev/null)" ]; then
  git add -A
  git commit -q -m "init: 网址自动访问器" || { echo "本地提交失败"; exit 1; }
fi
echo "本地提交已就绪："
git log --oneline | head -3
echo
echo "----------------------------------------"
echo "先在网页上做一步（只需做一次）："
echo "  1) 打开  https://github.com/new"
echo "  2) Repository name 填：url-visitor（或你喜欢的名字）"
echo "  3) 选 Public（公开）或 Private（私有）"
echo "  4) 下面三个勾都不要打（README / .gitignore / license 都别勾）"
echo "  5) 点 Create repository"
echo "----------------------------------------"
echo
read -r -p "你的 GitHub 用户名： " GHUSER
read -r -p "仓库名（直接回车用 url-visitor）： " GHREPO
GHREPO="${GHREPO:-url-visitor}"
echo
echo "接下来终端会问你要用户名和密码："
echo "  · 用户名：$GHUSER"
echo "  · 密  码：不是登录密码！"
echo "     打开 https://github.com/settings/tokens"
echo "     → Generate new token (classic) → 勾选 repo → 生成后复制"
echo "     粘贴时屏幕不显示任何字符，这是正常的，粘完直接按回车"
echo
read -r -p "准备好了按回车开始上传..."

git remote remove origin 2>/dev/null
git remote add origin "https://github.com/$GHUSER/$GHREPO.git"
git branch -M main
if git push -u origin main; then
  echo
  echo "🎉 上传成功 → https://github.com/$GHUSER/$GHREPO"
  echo "以后改了代码，再双击本文件就能同步更新。"
else
  echo
  echo "上传失败。常见原因："
  echo "  1) token 没勾选 repo 权限"
  echo "  2) 用户名或仓库名拼错"
  echo "  3) 网页上的仓库还没创建"
  echo "改好后重新双击本文件即可。"
fi
echo
read -r -p "按 回车键 关闭本窗口..."
