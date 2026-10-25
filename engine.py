"""浏览器访问引擎 + 调度器。
判定规则：只有页面真实渲染完成（load 完成且 document.readyState==complete）才计为一次成功访问。
公网 IP：在同一个浏览器上下文里打开 IP 探测站读取，保证与真实访问出口一致。
"""
import json
import random
import re
import threading
import time
from datetime import datetime

from playwright.sync_api import sync_playwright

IP_CANDIDATES = [
    "https://api.ipify.org?format=json",
    "https://api64.ipify.org?format=json",
    "https://www.taobao.com/help/getip.php",
    "http://myip.ipip.net",
]
IP_RE = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class Visitor:
    def __init__(self, cfg):
        self.cfg = cfg
        self._pw = None
        self._browser = None
        self._ctx = None

    def open(self):
        self._pw = sync_playwright().start()
        launch = {"headless": str(self.cfg.get("headless", "1")) in ("1", "true", "True")}
        proxy = (self.cfg.get("proxy") or "").strip()
        if proxy:
            launch["proxy"] = {"server": proxy}
        self._browser = self._launch(launch)
        self._ctx = self._browser.new_context(
            ignore_https_errors=True,
            user_agent=UA,
            viewport={"width": 1440, "height": 900},
        )

    def _launch(self, launch):
        """优先用本机 Chrome（免下载），失败自动回退 Playwright 内置 Chromium。"""
        if self.cfg.get("browser", "chrome") == "chrome":
            try:
                return self._pw.chromium.launch(channel="chrome", **launch)
            except Exception:
                pass
        return self._pw.chromium.launch(**launch)

    def close(self):
        for obj, fn in ((self._ctx, "close"), (self._browser, "close")):
            try:
                if obj:
                    getattr(obj, fn)()
            except Exception:
                pass
        try:
            if self._pw:
                self._pw.stop()
        except Exception:
            pass

    def visit(self, url):
        """打开一个网址，返回访问记录 dict。"""
        rec = {"url": url, "started_at": _now(), "status": "failed",
               "http_status": None, "title": None, "error": None,
               "duration_ms": 0, "public_ip": None, "ip_source": None}
        t0 = time.time()
        page = None
        timeout = int(self.cfg.get("timeout_ms", 30000))
        idle_wait = int(self.cfg.get("idle_wait_ms", 8000))
        try:
            page = self._ctx.new_page()
            resp = page.goto(url, wait_until="domcontentloaded", timeout=timeout)
            page.wait_for_load_state("load", timeout=timeout)
            try:
                page.wait_for_load_state("networkidle", timeout=idle_wait)
            except Exception:
                pass  # 长轮询/广告类页面永不 idle，不算失败
            ready = page.evaluate("() => document.readyState")
            try:
                rec["title"] = (page.title() or "")[:300]
            except Exception:
                pass
            rec["http_status"] = resp.status if resp else None
            if ready == "complete":
                rec["status"] = "success"
            else:
                rec["status"] = "timeout"
                rec["error"] = f"页面未完全加载（readyState={ready}）"
        except Exception as e:
            msg = str(e).split("\n")[0][:400]
            rec["status"] = "timeout" if "Timeout" in msg or "timeout" in msg else "failed"
            rec["error"] = msg
        finally:
            rec["duration_ms"] = int((time.time() - t0) * 1000)
            rec["finished_at"] = _now()
            if page:
                try:
                    page.close()
                except Exception:
                    pass
        return rec

    def detect_ip(self):
        """用同一个浏览器上下文探测公网 IP，返回 (ip, 来源)。"""
        custom = (self.cfg.get("ip_api") or "").strip()
        services = ([custom] if custom else []) + IP_CANDIDATES
        for url in services:
            page = None
            try:
                page = self._ctx.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=15000)
                text = (page.inner_text("body") or "")[:2000]
                try:
                    data = json.loads(text)
                    if isinstance(data, dict) and data.get("ip"):
                        return data["ip"], url
                except Exception:
                    pass
                m = IP_RE.search(text)
                if m:
                    return m.group(1), url
            except Exception:
                continue
            finally:
                if page:
                    try:
                        page.close()
                    except Exception:
                        pass
        return None, None


class Scheduler:
    def __init__(self, db, emit):
        self.db = db
        self.emit = emit
        self._stop = threading.Event()
        self._pause = threading.Event()
        self._thread = None
        self.state = "idle"   # idle | running | paused
        self.stats = {"round": 0, "rounds": 0, "planned": 0, "done": 0,
                      "success": 0, "failed": 0, "current_url": "", "current_ip": "-"}

    def snapshot(self):
        return {"state": self.state, "stats": dict(self.stats)}

    def _push_state(self):
        self.emit({"type": "state", "data": self.snapshot()})

    def is_alive(self):
        return bool(self._thread and self._thread.is_alive())

    def start(self):
        if self.is_alive():
            self.emit({"type": "toast", "level": "warn", "msg": "任务已在运行中"})
            return False
        cfg = self.db.get_settings()
        urls = self.db.list_enabled_urls()
        if not urls:
            self.emit({"type": "toast", "level": "warn", "msg": "请先添加并启用至少一个网址"})
            return False
        rounds = int(cfg["rounds"])
        self.stats.update(round=0, rounds=rounds, planned=len(urls) * (rounds or 1),
                          done=0, success=0, failed=0, current_url="", current_ip="-")
        self._stop.clear()
        self._pause.clear()
        self.state = "running"
        self._thread = threading.Thread(target=self._run, args=(cfg, urls), daemon=True)
        self._thread.start()
        self._push_state()
        return True

    def pause(self):
        if self.state == "running":
            self._pause.set()
            self.state = "paused"
            self._push_state()

    def resume(self):
        if self.state == "paused":
            self._pause.clear()
            self.state = "running"
            self._push_state()

    def stop(self):
        if self.is_alive():
            self.state = "paused"
            self._stop.set()
            self._pause.clear()   # 让等待中的 sleep 立即退出
            self._push_state()

    # ---------- 内部 ----------
    def _wait_resume(self):
        while self._pause.is_set() and not self._stop.is_set():
            time.sleep(0.2)

    def _sleep(self, seconds):
        """可中断、可暂停的等待，返回 False 表示被停止。"""
        end = time.time() + seconds
        while time.time() < end:
            if self._stop.is_set():
                return False
            if self._pause.is_set():
                end += 0.2          # 暂停期间不计入间隔
            time.sleep(0.2)
        return not self._stop.is_set()

    def _run(self, cfg, urls):
        v = Visitor(cfg)
        try:
            v.open()
            self.emit({"type": "toast", "level": "info", "msg": "浏览器已启动，开始访问"})
            rounds = int(cfg["rounds"])
            t_min = max(0.0, float(cfg["interval_min"]))
            t_max = max(t_min, float(cfg["interval_max"]))
            rnd = 0
            while not self._stop.is_set():
                if rounds > 0 and rnd >= rounds:
                    break
                rnd += 1
                order = list(urls)
                if cfg["mode"] == "random":
                    random.shuffle(order)
                round_ip = None
                self.stats.update(round=rnd, rounds=rounds, planned=len(order))
                self._push_state()

                for u in order:
                    if self._stop.is_set():
                        break
                    self._wait_resume()
                    if self._stop.is_set():
                        break

                    self.stats["current_url"] = u["url"]
                    self._push_state()
                    rec = v.visit(u["url"])

                    ip, src = None, None
                    if cfg["ip_check"] == "every_visit" or round_ip is None:
                        ip, src = v.detect_ip()
                        if ip:
                            round_ip = round_ip or ip
                            self.stats["current_ip"] = ip
                    if ip is None and cfg["ip_check"] == "every_round":
                        ip, src = round_ip, "本轮缓存"

                    rec.update(url_id=u["id"], round_no=rnd, public_ip=ip, ip_source=src)
                    self.db.add_visit(rec)
                    self.stats["done"] += 1
                    if rec["status"] == "success":
                        self.stats["success"] += 1
                    else:
                        self.stats["failed"] += 1
                    self.emit({"type": "log", "data": rec})
                    self.emit({"type": "stats", "data": dict(self.stats)})
                    self.emit({"type": "urls", "data": self.db.list_urls()})

                    wait = random.uniform(t_min, t_max) if t_max > t_min else t_min
                    if wait > 0 and not self._sleep(wait):
                        break
        except Exception as e:
            self.emit({"type": "toast", "level": "error", "msg": f"调度异常：{e}"})
        finally:
            v.close()
            self.state = "idle"
            self.stats["current_url"] = ""
            self._push_state()
            self.emit({"type": "urls", "data": self.db.list_urls()})
            self.emit({"type": "toast", "level": "info", "msg": "任务已结束"})
