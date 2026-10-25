"""数据层：SQLite 存储网址列表、访问记录与配置。"""
import os
import sqlite3
import threading

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("VV_DB", os.path.join(BASE, "data.db"))

DEFAULTS = {
    "browser": "chrome",        # chrome=本机 Google Chrome | bundled=Playwright 内置 Chromium
    "load_mode": "commit",      # commit=服务器一有响应就计数 | domcontentloaded | complete=完全加载
    "count_http_error": "1",    # 服务器返回 4xx/5xx 时是否也算一次访问
    "remote_enabled": "0",      # 手机远程添加：0=只本机 1=同一 WiFi 下的手机可访问
    "remote_token": "",         # 远程添加口令（首次启动自动生成）
    "mode": "order",            # order=顺序 | random=随机
    "rounds": "1",              # 循环轮次，0=无限
    "interval_min": "5",        # 每次访问间隔（秒）下限
    "interval_max": "5",        # 上限（>下限则区间内随机）
    "headless": "1",            # 1=后台无头 0=可见窗口
    "timeout_ms": "30000",      # 单页加载超时
    "idle_wait_ms": "8000",     # networkidle 额外等待上限
    "ip_check": "every_visit",  # every_visit=每次访问探测 | every_round=每轮探测
    "ip_api": "https://api.ipify.org?format=json",
    "proxy": "",                # 形如 http://127.0.0.1:7890，留空则直连
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS urls(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  url TEXT NOT NULL UNIQUE,
  note TEXT DEFAULT '',
  enabled INTEGER DEFAULT 1,
  created_at TEXT
);
CREATE TABLE IF NOT EXISTS visits(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  url_id INTEGER,
  url TEXT,
  round_no INTEGER,
  status TEXT,
  started_at TEXT,
  finished_at TEXT,
  duration_ms INTEGER,
  public_ip TEXT,
  ip_source TEXT,
  http_status INTEGER,
  title TEXT,
  error TEXT
);
CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY, v TEXT);
CREATE INDEX IF NOT EXISTS idx_visits_url ON visits(url_id);
CREATE INDEX IF NOT EXISTS idx_visits_time ON visits(id DESC);
"""

URL_FIELDS = ("id", "url", "note", "enabled", "created_at")


def _now():
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class DB:
    def __init__(self, path=DB_PATH):
        self.path = path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    # ---------- 网址 ----------
    def list_urls(self):
        sql = """
        SELECT u.id, u.url, u.note, u.enabled, u.created_at,
               (SELECT COUNT(*) FROM visits v WHERE v.url_id=u.id AND v.status='success') AS ok,
               (SELECT COUNT(*) FROM visits v WHERE v.url_id=u.id AND v.status!='success') AS bad,
               (SELECT v.public_ip FROM visits v WHERE v.url_id=u.id AND v.public_ip IS NOT NULL
                   ORDER BY v.id DESC LIMIT 1) AS last_ip,
               (SELECT v.finished_at FROM visits v WHERE v.url_id=u.id ORDER BY v.id DESC LIMIT 1) AS last_at
        FROM urls u ORDER BY u.id
        """
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql)]

    def list_enabled_urls(self):
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM urls WHERE enabled=1 ORDER BY id").fetchall()
        return [dict(r) for r in rows]

    def add_urls(self, raw_list):
        """批量添加，返回 [{'id','url'}]（已存在的也会返回，方便插队）；自动补全协议、去重。"""
        added = []
        with self._lock:
            for raw in raw_list:
                url = (raw or "").strip()
                if not url:
                    continue
                if not url.startswith(("http://", "https://")):
                    url = "https://" + url
                try:
                    cur = self._conn.execute(
                        "INSERT INTO urls(url, note, enabled, created_at) VALUES(?,?,1,?)",
                        (url, "", _now()))
                    added.append({"id": cur.lastrowid, "url": url})
                except sqlite3.IntegrityError:
                    row = self._conn.execute(
                        "SELECT id, url FROM urls WHERE url=?", (url,)).fetchone()
                    if row:
                        added.append({"id": row["id"], "url": row["url"]})
            self._conn.commit()
        return added

    def set_enabled(self, url_id, enabled):
        with self._lock:
            self._conn.execute("UPDATE urls SET enabled=? WHERE id=?",
                               (1 if enabled else 0, url_id))
            self._conn.commit()

    def set_note(self, url_id, note):
        with self._lock:
            self._conn.execute("UPDATE urls SET note=? WHERE id=?", (note or "", url_id))
            self._conn.commit()

    def delete_url(self, url_id):
        with self._lock:
            self._conn.execute("DELETE FROM urls WHERE id=?", (url_id,))
            self._conn.commit()

    def clear_urls(self):
        with self._lock:
            self._conn.execute("DELETE FROM urls")
            self._conn.commit()

    # ---------- 访问记录 ----------
    def add_visit(self, rec):
        cols = ("url_id", "url", "round_no", "status", "started_at", "finished_at",
                "duration_ms", "public_ip", "ip_source", "http_status", "title", "error")
        with self._lock:
            self._conn.execute(
                f"INSERT INTO visits({','.join(cols)}) VALUES({','.join('?' * len(cols))})",
                [rec.get(c) for c in cols])
            self._conn.commit()

    def list_visits(self, limit=200):
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM visits ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def clear_visits(self):
        with self._lock:
            self._conn.execute("DELETE FROM visits")
            self._conn.commit()

    def summary(self):
        sql = """SELECT
            COUNT(*) AS total,
            SUM(status='success') AS ok,
            SUM(status!='success') AS bad,
            AVG(CASE WHEN status='success' THEN duration_ms END) AS avg_ms
        FROM visits"""
        with self._lock:
            row = dict(self._conn.execute(sql).fetchone())
        row["avg_ms"] = int(row["avg_ms"] or 0)
        return row

    def export_csv(self):
        import csv
        import io
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["ID", "轮次", "网址", "状态", "HTTP", "公网IP", "IP来源",
                    "开始时间", "结束时间", "耗时ms", "标题", "错误"])
        with self._lock:
            rows = self._conn.execute("SELECT * FROM visits ORDER BY id").fetchall()
            for r in rows:
                w.writerow([r["id"], r["round_no"], r["url"], r["status"], r["http_status"],
                            r["public_ip"], r["ip_source"], r["started_at"], r["finished_at"],
                            r["duration_ms"], r["title"], r["error"]])
        return "\ufeff" + buf.getvalue()   # BOM：Excel 打开不乱码

    # ---------- 配置 ----------
    def get_settings(self):
        with self._lock:
            rows = {r["k"]: r["v"] for r in self._conn.execute("SELECT k,v FROM settings")}
        cfg = dict(DEFAULTS)
        cfg.update(rows)
        return cfg

    def set_settings(self, patch):
        clean = {k: str(v) for k, v in patch.items() if k in DEFAULTS}
        with self._lock:
            for k, v in clean.items():
                self._conn.execute(
                    "INSERT INTO settings(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                    (k, v))
            self._conn.commit()
        return self.get_settings()
