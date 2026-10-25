const $ = (s) => document.querySelector(s);
const el = (tag, cls, text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined) n.textContent = text;
  return n;
};
const fmt = (ms) => (ms >= 1000 ? (ms / 1000).toFixed(1) + " s" : ms + " ms");

let settings = {};
let curState = "idle";
let toastTimer = null;

function toast(msg, level = "info") {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "toast show " + level;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.className = "toast " + level), 2600);
}

/* ---------- 配置 ---------- */
function fillSettings(cfg) {
  settings = cfg;
  $("#mode").value = cfg.mode || "order";
  $("#rounds").value = cfg.rounds;
  $("#interval_min").value = cfg.interval_min;
  $("#interval_max").value = cfg.interval_max;
  $("#timeout_sec").value = Math.round((+cfg.timeout_ms || 30000) / 1000);
  $("#browser").value = cfg.browser || "chrome";
  $("#headless").value = String(cfg.headless);
  $("#ip_check").value = cfg.ip_check || "every_visit";
  $("#proxy").value = cfg.proxy || "";
}

function collectSettings() {
  return {
    mode: $("#mode").value,
    rounds: $("#rounds").value,
    interval_min: $("#interval_min").value,
    interval_max: $("#interval_max").value,
    timeout_ms: String(Math.max(5, +$("#timeout_sec").value || 30) * 1000),
    browser: $("#browser").value,
    headless: $("#headless").value,
    ip_check: $("#ip_check").value,
    proxy: $("#proxy").value.trim(),
  };
}

async function saveSettings() {
  const r = await fetch("/api/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(collectSettings()),
  });
  settings = await r.json();
}

/* ---------- 状态 ---------- */
function renderState(st) {
  curState = st.state;
  const badge = $("#badge");
  badge.className = "badge " + (st.state === "running" ? "running" : st.state === "paused" ? "paused" : "idle");
  badge.textContent = { idle: "空闲", running: "运行中", paused: "已暂停" }[st.state] || st.state;

  const s = st.stats || {};
  $("#sOk").textContent = s.success || 0;
  $("#sBad").textContent = s.failed || 0;
  $("#sProg").textContent = `${s.done || 0} / ${s.planned || 0}`;
  $("#sRound").textContent = `${s.round || 0} / ${s.rounds === 0 ? "∞" : s.rounds || 0}`;
  if (s.current_ip && s.current_ip !== "-") $("#curIp").textContent = s.current_ip;

  $("#btnStart").disabled = st.state !== "idle";
  $("#btnPause").disabled = st.state === "idle";
  $("#btnPause").textContent = st.state === "paused" ? "继续" : "暂停";
  $("#btnStop").disabled = st.state === "idle";
}

function renderSummary(sum) {
  $("#sAvg").textContent = fmt(sum.avg_ms || 0);
}

/* ---------- 网址列表 ---------- */
function renderUrls(list) {
  const body = $("#urlBody");
  body.textContent = "";
  if (!list.length) {
    const tr = el("tr");
    const td = el("td", "empty", "还没有网址，先在上方添加");
    td.colSpan = 7;
    tr.appendChild(td);
    body.appendChild(tr);
    return;
  }
  list.forEach((u) => {
    const tr = el("tr");
    const tdOn = el("td");
    const chk = el("input");
    chk.type = "checkbox";
    chk.checked = !!u.enabled;
    chk.onchange = () =>
      fetch(`/api/urls/${u.id}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: chk.checked }),
      });
    tdOn.appendChild(chk);

    const tdUrl = el("td");
    const a = el("a", "url", u.url);
    a.href = u.url;
    a.target = "_blank";
    a.rel = "noopener noreferrer";
    tdUrl.appendChild(a);

    const tdOk = el("td", "num", String(u.ok || 0));
    const tdBad = el("td", "num", String(u.bad || 0));
    const tdIp = el("td", "num", u.last_ip || "—");
    const tdAt = el("td", "num muted", u.last_at || "—");

    const tdOp = el("td");
    const del = el("button", "mini danger", "删除");
    del.onclick = () => {
      if (confirm(`删除网址？\n${u.url}`)) fetch(`/api/urls/${u.id}`, { method: "DELETE" });
    };
    tdOp.appendChild(del);

    [tdOn, tdUrl, tdOk, tdBad, tdIp, tdAt, tdOp].forEach((td) => tr.appendChild(td));
    body.appendChild(tr);
  });
}

/* ---------- 访问记录 ---------- */
function logRow(r, isNew) {
  const tr = el("tr");
  if (isNew) tr.className = "new";
  const cells = [
    el("td", "num muted", r.finished_at || r.started_at || ""),
    el("td", "num", r.round_no != null ? "#" + r.round_no : ""),
  ];
  const tdUrl = el("td");
  const a = el("a", "url", r.url);
  a.href = r.url;
  a.target = "_blank";
  a.rel = "noopener noreferrer";
  tdUrl.appendChild(a);
  cells.push(tdUrl);

  const label = { success: "成功", timeout: "超时", failed: "失败" }[r.status] || r.status;
  const tdSt = el("td");
  tdSt.appendChild(el("span", "tag " + r.status, label));
  cells.push(tdSt);
  cells.push(el("td", "num", r.http_status ?? "—"));
  cells.push(el("td", "num", r.public_ip || "—"));
  cells.push(el("td", "num", fmt(r.duration_ms || 0)));
  cells.push(el("td", "muted", (r.status === "success" ? r.title : r.error) || ""));
  cells.forEach((c) => tr.appendChild(c));
  return tr;
}

function renderLogs(rows) {
  const body = $("#logBody");
  body.textContent = "";
  if (!rows.length) {
    const tr = el("tr");
    const td = el("td", "empty", "暂无访问记录");
    td.colSpan = 8;
    tr.appendChild(td);
    body.appendChild(tr);
    return;
  }
  rows.forEach((r) => body.appendChild(logRow(r, false)));
}

function pushLog(r) {
  const body = $("#logBody");
  const emptyRow = body.querySelector(".empty");
  if (emptyRow) body.textContent = "";
  body.insertBefore(logRow(r, true), body.firstChild);
  while (body.rows.length > 300) body.deleteRow(body.rows.length - 1);
  if ($("#autoScroll").checked) window.scrollTo({ top: document.body.scrollHeight, behavior: "smooth" });
}

/* ---------- 事件绑定 ---------- */
$("#btnStart").onclick = async () => {
  await saveSettings();
  await fetch("/api/control", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action: "start" }),
  });
};
$("#btnPause").onclick = () =>
  fetch("/api/control", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action: curState === "paused" ? "resume" : "pause" }),
  });
$("#btnStop").onclick = () =>
  fetch("/api/control", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action: "stop" }),
  });

$("#btnAdd").onclick = async () => {
  const text = $("#newUrls").value.trim();
  if (!text) return toast("请先粘贴网址", "warn");
  const r = await fetch("/api/urls", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  const d = await r.json();
  $("#newUrls").value = "";
  toast(`已添加 ${d.added} 个网址`);
};

$("#btnAllOn").onclick = () => setAllEnabled(true);
$("#btnAllOff").onclick = () => setAllEnabled(false);
async function setAllEnabled(v) {
  const list = await (await fetch("/api/urls")).json();
  for (const u of list) {
    if (!!u.enabled !== v) {
      await fetch(`/api/urls/${u.id}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: v }),
      });
    }
  }
}
$("#btnClearUrls").onclick = async () => {
  if (confirm("清空整个网址列表？")) await fetch("/api/urls", { method: "DELETE" });
};
$("#btnClearVisits").onclick = async () => {
  if (confirm("清空所有访问记录？（计数会归零）")) await fetch("/api/visits", { method: "DELETE" });
};
$("#btnExport").onclick = () => (location.href = "/api/export.csv");

["browser", "mode", "rounds", "interval_min", "interval_max", "timeout_sec", "headless", "ip_check"].forEach((id) => {
  $("#" + id).addEventListener("change", saveSettings);
});
$("#proxy").addEventListener("blur", saveSettings);

/* ---------- WebSocket ---------- */
function onMsg(msg) {
  switch (msg.type) {
    case "snapshot":
      fillSettings(msg.data.settings);
      renderUrls(msg.data.urls);
      renderLogs(msg.data.visits);
      renderSummary(msg.data.summary);
      renderState(msg.data.state);
      break;
    case "urls": renderUrls(msg.data); break;
    case "settings": fillSettings(msg.data); break;
    case "state": renderState(msg.data); break;
    case "stats": renderState({ state: curState, stats: msg.data }); break;
    case "log": pushLog(msg.data); break;
    case "visits": renderLogs(msg.data); break;
    case "toast": toast(msg.data.msg, msg.data.level); break;
  }
}

function connect() {
  const ws = new WebSocket(`ws://${location.host}/ws`);
  ws.onmessage = (e) => onMsg(JSON.parse(e.data));
  ws.onclose = () => setTimeout(connect, 1500);
}
connect();

setInterval(() => {
  $("#clock").textContent = new Date().toLocaleTimeString("zh-CN", { hour12: false });
}, 1000);
