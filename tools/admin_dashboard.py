#!/usr/bin/env python3
"""Local signups dashboard for FinalWhistle.

Runs entirely on your machine (stdlib only — no deps). It holds your
RECOMPUTE_TOKEN server-side, fetches the token-guarded /api/internal/stats from
the live backend, and serves a small live dashboard at http://localhost:8787 so
the token never touches the browser and there's no CORS to fight.

Usage:
    RECOMPUTE_TOKEN=<your token> python tools/admin_dashboard.py
    # then open http://localhost:8787

Get the token from Render → pitchprophet-api → Environment → RECOMPUTE_TOKEN.

Env:
    RECOMPUTE_TOKEN   required — the internal-endpoints secret
    API_URL           default https://pitchprophet-api.onrender.com
    PORT              default 8787
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

API_URL = os.environ.get("API_URL", "https://pitchprophet-api.onrender.com").rstrip("/")
TOKEN = os.environ.get("RECOMPUTE_TOKEN", "")
PORT = int(os.environ.get("PORT", "8787"))


def fetch_stats() -> tuple[int, dict]:
    """Server-side call to the token-guarded stats endpoint."""
    req = urllib.request.Request(
        f"{API_URL}/api/internal/stats",
        headers={"X-Recompute-Token": TOKEN},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return 200, json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read())
        except Exception:
            body = {"error": {"message": str(e)}}
        return e.code, body
    except Exception as e:  # network/timeout (Render cold start, offline, …)
        return 502, {"error": {"message": f"Could not reach the API: {e}"}}


PAGE = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>FinalWhistle · Signups</title>
<style>
  :root { --bg:#0a140e; --card:#11201a; --line:#21362b; --muted:#8aa599; --fg:#eaf3ee; --win:#a3e635; }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--fg);
    font:15px/1.5 ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,sans-serif; }
  .wrap { max-width:880px; margin:0 auto; padding:32px 20px 64px; }
  h1 { font-size:22px; font-weight:800; letter-spacing:-.02em; margin:0 0 2px; }
  .sub { color:var(--muted); font-size:13px; margin-bottom:24px; }
  .cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:12px; margin-bottom:28px; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:16px; padding:16px 18px; }
  .card .k { color:var(--muted); font-size:11px; text-transform:uppercase; letter-spacing:.12em; }
  .card .v { font-size:30px; font-weight:800; margin-top:6px; font-variant-numeric:tabular-nums; }
  .card .v.win { color:var(--win); }
  h2 { font-size:12px; text-transform:uppercase; letter-spacing:.14em; color:var(--muted); margin:26px 0 12px; }
  .row { display:flex; align-items:center; gap:12px; padding:8px 0; border-top:1px solid var(--line); }
  .row:first-child { border-top:0; }
  .flag { font-size:20px; width:26px; text-align:center; }
  .name { flex:1; min-width:0; }
  .name small { color:var(--muted); }
  .bar { height:8px; border-radius:999px; background:#1c2f25; flex:1; max-width:240px; overflow:hidden; }
  .bar > i { display:block; height:100%; background:linear-gradient(90deg,#6fae27,var(--win)); }
  .count { width:48px; text-align:right; font-weight:700; font-variant-numeric:tabular-nums; }
  .empty,.err { color:var(--muted); background:var(--card); border:1px solid var(--line);
    border-radius:12px; padding:16px; }
  .err { color:#fda4af; }
  .foot { color:var(--muted); font-size:12px; margin-top:28px; }
  .dot { display:inline-block; width:7px; height:7px; border-radius:50%; background:var(--win); margin-right:6px;
    vertical-align:middle; }
</style></head>
<body><div class="wrap">
  <h1>FinalWhistle — Signups</h1>
  <div class="sub"><span class="dot"></span>live from <code id="api"></code> · refreshes every 20s</div>
  <div id="content"><div class="empty">Loading…</div></div>
  <div class="foot" id="foot"></div>
</div>
<script>
const flag = (cc) => (cc && cc.length===2 && /^[A-Z]{2}$/.test(cc))
  ? String.fromCodePoint(...[...cc].map(c=>0x1F1E6 + c.charCodeAt(0)-65)) : "🏳️";
function card(k,v,win){ return `<div class="card"><div class="k">${k}</div><div class="v ${win?'win':''}">${v}</div></div>`; }
function rows(list, max, render){
  if(!list || !list.length) return '<div class="empty">No signups with location yet.</div>';
  return list.map(render(max)).join('');
}
async function load(){
  try{
    const r = await fetch('/data'); const d = await r.json();
    document.getElementById('api').textContent = d._api || '';
    if(d.error){ document.getElementById('content').innerHTML =
      `<div class="err">${d.error.message||'Error'} (is RECOMPUTE_TOKEN correct?)</div>`; return; }
    const maxC = Math.max(1, ...(d.by_country||[]).map(x=>x.count));
    const maxCity = Math.max(1, ...(d.by_city||[]).map(x=>x.count));
    document.getElementById('content').innerHTML =
      `<div class="cards">
        ${card('Total signups', d.users, true)}
        ${card('Last 24h', d.signups_last_24h)}
        ${card('Brackets saved', d.brackets)}
        ${card('On leaderboard', d.public_brackets)}
       </div>
       <h2>By country</h2>
       ${rows(d.by_country, maxC, (m)=>(x)=>`<div class="row">
          <span class="flag">${x.country==='??'?'🌐':flag(x.country)}</span>
          <span class="name">${x.country==='??'?'Unknown':x.country}</span>
          <span class="bar"><i style="width:${Math.round(x.count/m*100)}%"></i></span>
          <span class="count">${x.count}</span></div>`)}
       <h2>Top cities</h2>
       ${rows(d.by_city, maxCity, (m)=>(x)=>`<div class="row">
          <span class="flag">${x.country==='??'?'🌐':flag(x.country)}</span>
          <span class="name">${x.city} <small>${x.country}</small></span>
          <span class="bar"><i style="width:${Math.round(x.count/m*100)}%"></i></span>
          <span class="count">${x.count}</span></div>`)}`;
    document.getElementById('foot').textContent =
      'Latest signup: ' + (d.latest_signup ? new Date(d.latest_signup).toLocaleString() : '—');
  }catch(e){
    document.getElementById('content').innerHTML = `<div class="err">${e}</div>`;
  }
}
load(); setInterval(load, 20000);
</script>
</body></html>"""


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/" or self.path.startswith("/index"):
            self._send(200, PAGE.encode(), "text/html; charset=utf-8")
        elif self.path.startswith("/data"):
            code, data = fetch_stats()
            data = {**data, "_api": API_URL}
            self._send(code if code != 502 else 200, json.dumps(data).encode(), "application/json")
        else:
            self._send(404, b"not found", "text/plain")

    def log_message(self, *args) -> None:  # quiet
        pass


def main() -> None:
    if not TOKEN:
        raise SystemExit(
            "RECOMPUTE_TOKEN is not set.\n"
            "Get it from Render → pitchprophet-api → Environment → RECOMPUTE_TOKEN, then:\n"
            "  RECOMPUTE_TOKEN=<token> python tools/admin_dashboard.py"
        )
    print(f"FinalWhistle signups dashboard → http://localhost:{PORT}  (API: {API_URL})")
    print("Press Ctrl+C to stop.")
    try:
        ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")


if __name__ == "__main__":
    main()
