"""制御サーバー(標準ライブラリ http.server)。

エンドポイント:
  GET  /                → ダッシュボード(HTML)
  GET  /api/state       → 現在の状態(JSON)
  GET  /api/events      → 直近イベント(JSON)
  POST /api/start       → 開始
  POST /api/stop        → 停止
  POST /api/stake       → 掛け金変更 {"stake": 10, "mode": "fixed"}

外部依存なし。FastAPI 等に載せ替えたい場合は state()/start()/stop() を呼ぶだけ。
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional

from .session import PaperSession

_DASHBOARD = """<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>alpaca_clone control</title>
<style>
 :root{color-scheme:light dark}
 body{font-family:system-ui,-apple-system,'Segoe UI',sans-serif;margin:0;
   background:#0e1116;color:#e6edf3}
 header{padding:16px 20px;border-bottom:1px solid #30363d;display:flex;
   align-items:center;gap:12px;flex-wrap:wrap}
 h1{font-size:16px;margin:0;font-weight:600}
 .pill{padding:2px 10px;border-radius:999px;font-size:12px;border:1px solid #30363d}
 .on{background:#12331f;color:#3fb950;border-color:#2ea04326}
 .off{background:#341414;color:#f85149;border-color:#f8514926}
 main{padding:20px;max-width:960px;margin:0 auto}
 .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}
 .card{background:#161b22;border:1px solid #30363d;border-radius:10px;padding:14px}
 .card .k{font-size:12px;color:#8b949e}
 .card .v{font-size:22px;font-weight:600;margin-top:4px}
 button{background:#238636;color:#fff;border:0;border-radius:8px;padding:8px 14px;
   font-size:14px;cursor:pointer}
 button.stop{background:#da3633}
 button:disabled{opacity:.5;cursor:not-allowed}
 input{background:#0d1117;color:#e6edf3;border:1px solid #30363d;border-radius:8px;
   padding:7px 9px;width:80px}
 table{width:100%;border-collapse:collapse;margin-top:10px;font-size:13px}
 th,td{text-align:left;padding:6px 8px;border-bottom:1px solid #21262d}
 .win{color:#3fb950}.loss{color:#f85149}
 .row{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:16px 0}
 .note{color:#8b949e;font-size:12px;margin-top:20px;line-height:1.6}
</style></head>
<body>
<header>
 <h1>alpaca_clone <span style="color:#8b949e;font-weight:400">control panel</span></h1>
 <span id="status" class="pill off">stopped</span>
 <span id="strat" class="pill"></span>
</header>
<main>
 <div class="row">
  <button id="startBtn" onclick="ctl('start')">▶ 開始</button>
  <button id="stopBtn" class="stop" onclick="ctl('stop')">■ 停止</button>
  <label>掛け金 <input id="stake" type="number" step="0.1" value="10"></label>
  <button onclick="setStake()">更新</button>
 </div>
 <div class="grid">
  <div class="card"><div class="k">残高</div><div class="v" id="balance">-</div></div>
  <div class="card"><div class="k">勝率</div><div class="v" id="winrate">-</div></div>
  <div class="card"><div class="k">勝 / 負</div><div class="v" id="wl">-</div></div>
  <div class="card"><div class="k">取引数</div><div class="v" id="trades">-</div></div>
  <div class="card"><div class="k">建玉</div><div class="v" id="open">-</div></div>
  <div class="card"><div class="k">直近シグナル</div><div class="v" id="sig">-</div></div>
  <div class="card"><div class="k">受信足数</div><div class="v" id="candles">-</div></div>
 </div>
 <h3 style="margin-top:24px">直近の取引</h3>
 <table><thead><tr><th>方向</th><th>入</th><th>出</th><th>結果</th><th>損益</th></tr></thead>
 <tbody id="tbody"></tbody></table>
 <p class="note">
  ※ これはペーパー(仮想)運用です。実弾ではありません。相場データは検証用の合成値です。<br>
  ※ バイナリーオプションは高リスクで、多くのブラウザ型業者は自動売買を規約で禁止しています。
 </p>
</main>
<script>
async function ctl(action){
  await fetch('/api/'+action,{method:'POST'}); refresh();
}
async function setStake(){
  const v=parseFloat(document.getElementById('stake').value)||10;
  await fetch('/api/stake',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({stake:v,mode:'fixed'})}); refresh();
}
function fmt(n){return (n===null||n===undefined)?'-':n}
async function refresh(){
  try{
    const s=await (await fetch('/api/state')).json();
    const on=s.running;
    const st=document.getElementById('status');
    st.textContent=on?'running':'stopped'; st.className='pill '+(on?'on':'off');
    document.getElementById('strat').textContent=s.strategy||'';
    document.getElementById('balance').textContent=fmt(s.balance);
    document.getElementById('winrate').textContent=((s.win_rate*100)||0).toFixed(1)+'%';
    document.getElementById('wl').textContent=s.wins+' / '+s.losses;
    document.getElementById('trades').textContent=fmt(s.closed_trades);
    document.getElementById('open').textContent=fmt(s.open_positions);
    document.getElementById('sig').textContent=fmt(s.last_signal);
    document.getElementById('candles').textContent=fmt(s.candles_seen);
    document.getElementById('startBtn').disabled=on;
    document.getElementById('stopBtn').disabled=!on;
    const tb=document.getElementById('tbody'); tb.innerHTML='';
    (s.recent_trades||[]).slice().reverse().forEach(t=>{
      const cls=t.outcome==='WIN'?'win':(t.outcome==='LOSS'?'loss':'');
      tb.insertAdjacentHTML('beforeend',
        `<tr><td>${t.direction}</td><td>${t.entry_price}</td><td>${t.exit_price??'-'}</td>`+
        `<td class="${cls}">${t.outcome}</td><td class="${cls}">${t.pnl}</td></tr>`);
    });
  }catch(e){/* サーバ未応答時は無視 */}
}
setInterval(refresh,1000); refresh();
</script>
</body></html>
"""


def _make_handler(session: PaperSession):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # ログを静かに
            pass

        def _send_json(self, obj, code: int = 200):
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_html(self, html: str):
            body = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path in ("/", "/index.html"):
                self._send_html(_DASHBOARD)
            elif self.path == "/api/state":
                self._send_json(session.state())
            elif self.path.startswith("/api/events"):
                self._send_json({"events": session.events()})
            else:
                self._send_json({"error": "not found"}, 404)

        def do_POST(self):
            if self.path == "/api/start":
                self._send_json({"started": session.start()})
            elif self.path == "/api/stop":
                self._send_json({"stopped": session.stop()})
            elif self.path == "/api/stake":
                length = int(self.headers.get("Content-Length", 0) or 0)
                raw = self.rfile.read(length) if length else b"{}"
                try:
                    data = json.loads(raw or b"{}")
                except json.JSONDecodeError:
                    self._send_json({"error": "invalid json"}, 400)
                    return
                session.set_stake(float(data.get("stake", 10)), data.get("mode"))
                self._send_json({"ok": True})
            else:
                self._send_json({"error": "not found"}, 404)

    return Handler


def serve(session: PaperSession, host: str = "127.0.0.1", port: int = 8787,
          autostart: bool = False) -> None:
    """ブロッキングでサーバーを起動する。"""
    if autostart:
        session.start()
    httpd = ThreadingHTTPServer((host, port), _make_handler(session))
    print(f"[alpaca_clone] ダッシュボード: http://{host}:{port}  (Ctrl+C で停止)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[alpaca_clone] 停止します...")
    finally:
        session.stop()
        httpd.server_close()
