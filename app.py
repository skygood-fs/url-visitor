"""网址自动访问器 —— Web 服务端（FastAPI + WebSocket 实时推送）。"""
import asyncio
import os
import threading
import webbrowser
from contextlib import asynccontextmanager

from fastapi import Body, FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response
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
    n = DB.add_urls(items)
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


if __name__ == "__main__":
    import uvicorn

    if os.environ.get("VV_NO_OPEN") != "1":
        threading.Timer(1.2, lambda: webbrowser.open(f"http://127.0.0.1:{PORT}")).start()
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
