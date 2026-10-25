"""网址自动访问器 —— Web 服务端（FastAPI + WebSocket 实时推送）。"""
import asyncio
import os
import socket
import sys
import threading
import time
import webbrowser
from contextlib import asynccontextmanager

from fastapi import Body, FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles

import db as dbmod
from engine import Scheduler

BASE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(BASE, "static")
PORT = int(os.environ.get("VV_PORT", "8765"))

QUEUE: asyncio.Queue = asyncio.Queue()
CLIENTS = set()
LOOP = None
DB = dbmod.DB()
SCHED = Scheduler(DB, lambda ev: emit(ev))


def _ensure_token():
    """首次启动自动生成远程添加口令。"""
    cfg = DB.get_settings()
    if not (cfg.get("remote_token") or "").strip():
        import secrets
        cfg = DB.set_settings({"remote_token": secrets.token_hex(3).upper()})
    return cfg


def _lan_ip():
    """本机在 WiFi/局域网里的 IP，手机要用它访问。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def _remote_on():
    return str(DB.get_settings().get("remote_enabled", "0")) == "1"


def emit(ev):
    if LOOP is not None:
        try:
            asyncio.run_coroutine_threadsafe(QUEUE.put(ev), LOOP)
        except RuntimeError:
            pass


async def _broadcaster():
    while True:
        ev = await QUEUE.get()
        dead = []
        for ws in list(CLIENTS):
            try:
                await ws.send_json(ev)
            except Exception:
                dead.append(ws)
        for ws in dead:
            CLIENTS.discard(ws)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global LOOP
    LOOP = asyncio.get_running_loop()
    task = asyncio.create_task(_broadcaster())
    yield
    task.cancel()


app = FastAPI(lifespan=lifespan)

REMOTE_PATHS = ("/m", "/api/inbox", "/api/qrcode.svg", "/api/remote-info")


@app.middleware("http")
async def lan_guard(request: Request, call_next):
    """开启手机添加后监听局域网，但局域网只能访问 /m 与收件接口，本机不受限制。"""
    path = request.url.path
    if _remote_on() and not path.startswith(REMOTE_PATHS):
        client = request.client.host if request.client else ""
        if client not in ("127.0.0.1", "::1", "localhost"):
            return PlainTextResponse("局域网仅开放手机添加页面 /m", status_code=403)
    return await call_next(request)


# ---------------- 页面 ----------------
@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC, "index.html"))


app.mount("/static", StaticFiles(directory=STATIC), name="static")


# ---------------- 实时通道 ----------------
@app.websocket("/ws")
async def ws_endpoint(sock: WebSocket):
    await sock.accept()
    CLIENTS.add(sock)
    try:
        await sock.send_json({"type": "snapshot", "data": {
            "urls": DB.list_urls(),
            "settings": DB.get_settings(),
            "visits": DB.list_visits(80),
            "summary": DB.summary(),
            "state": SCHED.snapshot(),
        }})
        while True:
            await sock.receive_text()   # 心跳/占位，断线抛异常即退出
    except WebSocketDisconnect:
        pass
    finally:
        CLIENTS.discard(sock)


# ---------------- 网址 ----------------
@app.get("/api/urls")
def api_urls():
    return DB.list_urls()


@app.post("/api/urls")
def api_add_urls(payload: dict = Body(...)):
    text = payload.get("text") or ""
    items = [x.strip() for x in text.replace(",", "\n").splitlines()]
    n = len(DB.add_urls(items))
    urls = DB.list_urls()
    emit({"type": "urls", "data": urls})
    return {"added": n, "urls": urls}


@app.post("/api/urls/{url_id}")
def api_update_url(url_id: int, payload: dict = Body(...)):
    if "enabled" in payload:
        DB.set_enabled(url_id, bool(payload["enabled"]))
    if "note" in payload:
        DB.set_note(url_id, payload["note"])
    urls = DB.list_urls()
    emit({"type": "urls", "data": urls})
    return urls


@app.delete("/api/urls/{url_id}")
def api_delete_url(url_id: int):
    DB.delete_url(url_id)
    urls = DB.list_urls()
    emit({"type": "urls", "data": urls})
    return urls


@app.delete("/api/urls")
def api_clear_urls():
    DB.clear_urls()
    urls = DB.list_urls()
    emit({"type": "urls", "data": urls})
    return urls


# ---------------- 记录 ----------------
@app.get("/api/visits")
def api_visits(limit: int = 200):
    return DB.list_visits(limit)


@app.delete("/api/visits")
def api_clear_visits():
    DB.clear_visits()
    emit({"type": "visits", "data": DB.list_visits(80)})
    emit({"type": "urls", "data": DB.list_urls()})
    return {"ok": True}


@app.get("/api/export.csv")
def api_export():
    return Response(
        DB.export_csv(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="visits.csv"'},
    )


# ---------------- 配置 ----------------
@app.get("/api/settings")
def api_get_settings():
    return DB.get_settings()


@app.post("/api/settings")
def api_set_settings(payload: dict = Body(...)):
    cfg = DB.set_settings(payload)
    emit({"type": "settings", "data": cfg})
    return cfg


# ---------------- 手机远程添加 ----------------
@app.get("/m")
def mobile_page():
    return FileResponse(os.path.join(STATIC, "m.html"))


@app.get("/api/remote-info")
def api_remote_info():
    cfg = DB.get_settings()
    ip = _lan_ip()
    return {
        "enabled": _remote_on(),
        "ip": ip,
        "port": PORT,
        "token": cfg.get("remote_token", ""),
        "url": f"http://{ip}:{PORT}/m?token={cfg.get('remote_token', '')}",
        "running": SCHED.is_alive(),
        "state": SCHED.snapshot(),
        "summary": DB.summary(),
        "urls": DB.list_urls(),
    }


@app.get("/api/qrcode.svg")
def api_qrcode():
    cfg = DB.get_settings()
    target = f"http://{_lan_ip()}:{PORT}/m?token={cfg.get('remote_token', '')}"
    try:
        import segno
        svg = segno.make(target).svg_inline(scale=9, border=2)
    except Exception:
        return PlainTextResponse("二维码库缺失，直接用上面的网址", status_code=500)
    return Response(svg, media_type="image/svg+xml")


def _inbox(payload: dict):
    cfg = DB.get_settings()
    if not _remote_on():
        return JSONResponse({"ok": False, "msg": "未开启手机添加"}, status_code=403)
    if str((payload or {}).get("token", "")).upper() != str(cfg.get("remote_token", "")).upper():
        return JSONResponse({"ok": False, "msg": "口令不对"}, status_code=401)
    text = (payload or {}).get("url") or (payload or {}).get("text") or ""
    rows = DB.add_urls([x.strip() for x in text.replace(",", "\n").splitlines()])
    if not rows:
        return JSONResponse({"ok": False, "msg": "没识别到网址"}, status_code=400)
    queued = []
    if str((payload or {}).get("immediate", 1)) not in ("0", "false", "False"):
        for r in rows:
            if SCHED.add_now(r):
                queued.append(r["url"])
    urls = DB.list_urls()
    emit({"type": "urls", "data": urls})
    emit({"type": "toast", "level": "info",
          "msg": f"手机添加 {len(rows)} 个网址" + (f"，{len(queued)} 个已插队" if queued else "")})
    return {"ok": True, "added": [r["url"] for r in rows],
            "queued": queued, "running": SCHED.is_alive()}


@app.post("/api/inbox")
def api_inbox_post(payload: dict = Body(...)):
    return _inbox(payload or {})


@app.get("/api/inbox")
def api_inbox_get(token: str = "", url: str = "", text: str = "", immediate: int = 1):
    """GET 版本：方便手机快捷指令 / 自动化工具直接调一个链接。"""
    return _inbox({"token": token, "url": url or text, "immediate": immediate})


def _inbox_delete(payload: dict):
    cfg = DB.get_settings()
    if not _remote_on():
        return JSONResponse({"ok": False, "msg": "未开启手机添加"}, status_code=403)
    if str((payload or {}).get("token", "")).upper() != str(cfg.get("remote_token", "")).upper():
        return JSONResponse({"ok": False, "msg": "口令不对"}, status_code=401)
    try:
        url_id = int((payload or {}).get("id"))
    except (TypeError, ValueError):
        return JSONResponse({"ok": False, "msg": "缺少网址 id"}, status_code=400)
    target = next((u for u in DB.list_urls() if u["id"] == url_id), None)
    if not target:
        return JSONResponse({"ok": False, "msg": "这个网址已经不在列表里"}, status_code=404)
    DB.delete_url(url_id)
    SCHED.remove_url(url_id)
    emit({"type": "urls", "data": DB.list_urls()})
    emit({"type": "toast", "level": "info", "msg": f"手机删除了：{target['url']}"})
    return {"ok": True, "deleted": target["url"]}


@app.post("/api/inbox/delete")
def api_inbox_delete_post(payload: dict = Body(...)):
    return _inbox_delete(payload or {})


@app.get("/api/inbox/delete")
def api_inbox_delete_get(token: str = "", id: int = 0):
    return _inbox_delete({"token": token, "id": id})


# ---------------- 控制 ----------------
@app.post("/api/control")
def api_control(payload: dict = Body(...)):
    action = (payload or {}).get("action")
    if action == "start":
        SCHED.start()
    elif action == "pause":
        SCHED.pause()
    elif action == "resume":
        SCHED.resume()
    elif action == "stop":
        SCHED.stop()
    else:
        return JSONResponse({"ok": False, "msg": f"未知指令 {action}"}, status_code=400)
    return {"ok": True, "state": SCHED.snapshot()}


@app.get("/api/state")
def api_state():
    return {"state": SCHED.snapshot(), "summary": DB.summary()}


@app.post("/api/restart")
def api_restart():
    """切换监听地址后需要重启进程才能生效。"""
    def _do():
        time.sleep(0.6)
        os.execv(sys.executable, [sys.executable, os.path.join(BASE, "app.py")])
    threading.Thread(target=_do, daemon=True).start()
    return {"ok": True, "msg": "restarting"}


if __name__ == "__main__":
    import uvicorn

    _ensure_token()
    host = "0.0.0.0" if _remote_on() else "127.0.0.1"
    if os.environ.get("VV_NO_OPEN") != "1":
        threading.Timer(1.2, lambda: webbrowser.open(f"http://127.0.0.1:{PORT}")).start()
    uvicorn.run(app, host=host, port=PORT, log_level="warning")
