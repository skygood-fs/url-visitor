# 网址自动访问器

用真实浏览器（Chrome）按顺序 / 随机循环访问网址列表，实时记录每次访问的次数、耗时和当时的本机公网 IP。

## 安装（换台电脑 / 给别人用）

```bash
git clone https://github.com/<你的用户名>/url-visitor.git
cd url-visitor
python3 -m venv .venv
source .venv/bin/activate          # Windows 用：.venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium        # 可选：只想用本机 Chrome 就不用装
python3 app.py
```

然后浏览器打开 `http://127.0.0.1:8765` 即可。
macOS 上还能用 `./service.sh start/stop/status` 管理服务与开机自启；Windows / Linux 直接 `python3 app.py` 就行。

## 隐私说明

所有访问记录（网址、次数、耗时、**公网 IP**）只存在本机的 `data.db` 里，
该文件已在 `.gitignore` 中排除，不会上传到任何地方。

## 许可

MIT，见 `LICENSE`。

## 启动 / 停止 / 开机自启

### 最简单：双击（不用懂命令）

在访达里打开 `url-visitor` 文件夹，双击下面任一文件即可：

| 双击这个文件 | 作用 |
|---|---|
| `1-启动服务.command` | 启动并自动打开界面 |
| `2-打开界面.command` | 服务已在跑时，重新打开界面 |
| `3-停止服务.command` | 停止，界面会打不开 |
| `4-查看状态.command` | 看是否在跑、开机自启是否开启 |
| `5-开机自启-开启.command` | 以后开机自动启动 |
| `6-开机自启-关闭.command` | 取消开机自启 |

窗口里出现提示后按**回车键**关闭黑框窗口；关掉窗口不影响服务继续运行。
首次双击若提示"无法打开"，**右键点它 → 打开**即可（只用一次）。

### 也可以用命令

在**终端 App** 里执行：

```bash
cd url-visitor
./service.sh start           # 启动并自动打开 http://127.0.0.1:8765
./service.sh stop            # 停止
./service.sh restart         # 重启
./service.sh status          # 看是否在跑、开机自启是否开启
./service.sh logs            # 实时看运行日志（Ctrl+C 退出）

./service.sh autostart-on    # 开启开机自启（登录即启动，崩溃自动拉起）
./service.sh autostart-off   # 关闭开机自启并停掉当前实例
```

也可以直接 `./run.sh` 前台运行（ Ctrl + C 停止）。
换端口：`VV_PORT=9000 ./service.sh start`；只想后台静默跑：`VV_NO_OPEN=1 ./run.sh`。

开机自启走的是用户级 launchd（无需管理员权限），配置在
`~/Library/LaunchAgents/com.urlvisitor.plist`，`autostart-off` 会删除它。

## 怎么用

1. 在「网址列表」粘贴网址（每行一个或逗号分隔），点添加；可单独停用/启用某条
2. 左侧设置运行参数，点「启动」，可随时暂停 / 继续 / 停止
3. 右侧实时看：成功数、失败数、进度、当前轮次、平均耗时、逐条访问记录
4. 需要留档点「导出 CSV」（Excel 打开不乱码）

## 运行参数

| 参数 | 说明 |
|---|---|
| 浏览器内核 | 本机 Chrome（默认，免下载）/ Playwright 内置 Chromium（需先 `playwright install chromium`）|
| 遍历方式 | 按顺序 / 随机 |
| 循环轮次 | 跑几轮就停，`0` = 无限循环 |
| 间隔 | 下限/上限（秒），上限 > 下限则在区间内随机，模拟真人节奏 |
| 怎样算一次访问 | 服务器有响应 / 内容加载完 / 完全加载，见上文判定表 |
| 404·500 也算一次 | 勾选后错误页也计入成功 |
| 单页超时 | 超时记为「超时」，不计成功 |
| 浏览器窗口 | 后台无头（默认）/ 可见窗口（排查用）|
| IP 探测频率 | 每次访问都探测 / 每轮探测一次（访问量大时省时间）|
| 代理 | 填 `http://127.0.0.1:7890` 这类即可让浏览器走代理，留空直连 |

## 「算一次访问」的判定

界面左栏「怎样算一次访问」可切换三档，默认最快那档：

| 档位 | 判定 | 单次耗时参考 |
|---|---|---|
| **服务器有响应就算**（默认） | 浏览器的请求到达服务器、收到响应头即计数 | 0.1 ~ 0.3 秒 |
| 页面内容加载完才算 | 等到 `domcontentloaded` | 0.5 ~ 2 秒 |
| 完全加载才算 | `load` + `networkidle` + `readyState=complete` | 3 ~ 10 秒 |

下面还有个勾选项：**404 / 500 等错误页也算一次**（默认勾选）——因为服务器确实收到并回应了请求。
域名解析失败、连不上、超时这种「服务器压根没反应」的情况，一律记为失败，不计入成功数。

## 手机远程添加

不在电脑旁边时，用手机就能往列表里加网址，还能让它**下一个就访问**。

1. 电脑界面上勾选「手机远程添加 → 开启」（会自动重启一次服务，几秒后页面刷新）
2. 界面上会出现二维码和一个形如 `http://192.168.x.x:8765/m?token=XXXXXX` 的网址
3. **手机和电脑连同一个 WiFi**，用相机扫码（或手机浏览器打开那个网址）
4. 手机页面上粘贴链接 → 点「添加并马上访问」

- 勾选「只添加到列表」则不插队，等下一轮轮到它。
- 建议把手机页加到主屏幕（Safari：分享 → 添加到主屏幕），以后一键打开。
- 口令在二维码里带着，别人扫不到就加不了；同一 WiFi 的人也只能打开手机页，
  看不到也改不了电脑上的主界面（局域网访问主界面会被拒绝）。
- 想从外网（不在家）添加，需要内网穿透，例如 `cloudflared tunnel --url http://localhost:8765`。

程序也留了纯链接接口，方便接 iOS 快捷指令等自动化工具：

```
http://192.168.x.x:8765/api/inbox?token=XXXXXX&url=要添加的网址&immediate=1
```

公网 IP 用**同一个浏览器上下文**打开 IP 探测站读取（ipify → 淘宝 getip → ipip 依次兜底），因此浏览器配了代理时，记录的也是真实出口 IP。

## 文件

```
app.py      Web 服务 + WebSocket 实时推送
engine.py   访问引擎（Playwright）+ 调度器
db.py       SQLite：网址、访问记录、配置
static/     界面（原生 HTML/CSS/JS，无构建步骤）
data.db     运行后自动生成，存网址与全部访问记录
```

数据都在本地 `data.db`，删掉该文件即完全重置。
