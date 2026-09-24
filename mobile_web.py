from __future__ import annotations

import json
import logging
from typing import Any

from aiohttp import web

log = logging.getLogger("boss-mobile")

HTML = r"""<!doctype html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="theme-color" content="#0f1318">
<link rel="manifest" href="/manifest.webmanifest">
<title>Boss 5 Nến</title>
<style>
:root{color-scheme:dark;--bg:#0f1318;--panel:#171d24;--line:#28313b;--txt:#f3f6f8;--muted:#93a0ad;--g:#08bf73;--r:#ff4545;--b:#4ba3ff}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--txt);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
main{max-width:620px;margin:auto;padding:calc(16px + env(safe-area-inset-top)) 14px calc(28px + env(safe-area-inset-bottom))}
h1{font-size:23px;margin:0}.sub{color:var(--muted);margin:5px 0 16px;font-size:13px}.card{background:var(--panel);border:1px solid var(--line);border-radius:17px;padding:15px;margin:11px 0}
.row{display:flex;align-items:center;justify-content:space-between;gap:10px}.label{color:var(--muted);font-size:13px}.big{font-size:28px;font-weight:800}.green{color:var(--g)}.red{color:var(--r)}.blue{color:var(--b)}
.candles{display:grid;grid-template-columns:repeat(5,1fr);gap:8px;margin:14px 0}.dot{height:54px;border-radius:13px;background:#242c35;display:grid;place-items:center;font-size:34px}.g{color:var(--g)}.r{color:var(--r)}
.stats{display:grid;grid-template-columns:1fr 1fr;gap:9px}.stat{background:#11161c;border-radius:12px;padding:11px}.stat b{display:block;font-size:20px;margin-top:3px}
.history{display:grid;grid-template-columns:repeat(10,1fr);gap:4px}.cell{aspect-ratio:1;border-radius:7px;background:#11161c;display:grid;place-items:center;font:700 12px ui-monospace,monospace}.v{background:#103a2b;color:#55e9a1}.x{background:#462323;color:#ff7a7a}
.err{white-space:pre-wrap;color:#ff9b9b;font-size:12px}.ok{color:#67dfaa;font-size:12px}.foot{color:var(--muted);font-size:12px;line-height:1.45;margin-top:15px}
button{border:0;border-radius:12px;padding:11px 14px;background:var(--b);color:white;font-weight:700;font-size:14px}
</style>
</head>
<body><main>
<h1>Boss 5 Nến</h1>
<div class="sub" id="source">Đang kết nối...</div>

<section class="card">
  <div class="label">5 kết quả BTC Up/Down 5m gần nhất đã chốt</div>
  <div class="candles" id="candles"></div>
  <div class="row"><div><div class="label">Lệnh vòng kế tiếp</div><div class="big" id="buy">CHỜ</div></div><div style="text-align:right"><div class="label">Khung giờ</div><b id="frame">--</b><div class="label" id="bet">--</div></div></div>
</section>

<section class="card">
  <div class="stats">
    <div class="stat"><span class="label">Thắng hôm nay</span><b class="green" id="wins">0</b></div>
    <div class="stat"><span class="label">Thua hôm nay</span><b class="red" id="losses">0</b></div>
    <div class="stat"><span class="label">Lãi / lỗ</span><b id="pnl">0.00</b></div>
    <div class="stat"><span class="label">Số dư cuối ngày</span><b id="balance">0.00</b></div>
  </div>
</section>

<section class="card">
  <div class="row"><div><b>100 lệnh gần nhất</b><div class="label">V = thắng • X = thua</div></div><button onclick="refresh()">Làm mới</button></div>
  <div class="history" id="history" style="margin-top:13px"></div>
</section>

<section class="card">
  <div class="label">Telegram</div>
  <div id="telegram" class="ok">--</div>
  <div id="error" class="err"></div>
</section>

<div class="foot">Trên iPhone: mở trang này bằng Safari → Chia sẻ → Thêm vào Màn hình chính. Tool đọc kết quả đã phân xử của BTC Up/Down 5m, không dùng màu nến Futures làm màu kết quả Prediction.</div>
</main>
<script>
const $=id=>document.getElementById(id);
function money(v){return Number(v||0).toFixed(2)+" USDT"}
async function refresh(){
  try{
    const r=await fetch("/api/status",{cache:"no-store"});
    const s=await r.json();
    $("source").textContent=(s.source_label||"Prediction")+" • "+(s.connected?"Đang chạy":"Đang chờ dữ liệu");
    $("candles").innerHTML="";
    (s.colors||[]).forEach(c=>{const d=document.createElement("div");d.className="dot "+(c==="G"?"g":"r");d.textContent="●";$("candles").appendChild(d)});
    while($("candles").children.length<5){const d=document.createElement("div");d.className="dot";d.textContent="·";$("candles").appendChild(d)}
    const rec=s.recommendation;
    $("buy").textContent=rec==="G"?"MUA XANH":rec==="R"?"MUA ĐỎ":"KHÔNG KHỚP MẪU";
    $("buy").className="big "+(rec==="G"?"green":rec==="R"?"red":"");
    $("frame").textContent=s.frame||"--";
    $("bet").textContent="Lệnh "+(s.current_step||1)+" • "+money(s.next_bet);
    $("wins").textContent=s.wins||0;$("losses").textContent=s.losses||0;
    $("pnl").textContent=money(s.daily_pnl);$("pnl").className=Number(s.daily_pnl)>0?"green":Number(s.daily_pnl)<0?"red":"";
    $("balance").textContent=money(s.end_balance);
    const marks=(s.history||[]).slice(-100);$("history").innerHTML="";
    for(let i=0;i<100;i++){const d=document.createElement("div");const m=marks[i-(100-marks.length)];d.className="cell "+(m==="V"?"v":m==="X"?"x":"");d.textContent=m||"·";$("history").appendChild(d)}
    $("telegram").textContent=s.telegram_status||"Chưa có trạng thái";
    $("error").textContent=s.error||s.source_error||"";
  }catch(e){$("error").textContent="Không kết nối được Boss: "+e}
}
setInterval(refresh,2000);refresh();
if("serviceWorker" in navigator){navigator.serviceWorker.register("/sw.js").catch(()=>{})}
</script></body></html>"""

MANIFEST = {
    "name": "Boss 5 Nến",
    "short_name": "Boss 5 Nến",
    "start_url": "/",
    "display": "standalone",
    "background_color": "#0f1318",
    "theme_color": "#0f1318",
    "icons": [{"src": "/icon.svg", "sizes": "any", "type": "image/svg+xml", "purpose": "any maskable"}],
}

ICON = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128">
<rect width="128" height="128" rx="28" fill="#0f1318"/>
<circle cx="38" cy="38" r="18" fill="#08bf73"/><circle cx="90" cy="38" r="18" fill="#ff4545"/>
<circle cx="38" cy="90" r="18" fill="#ff4545"/><circle cx="90" cy="90" r="18" fill="#08bf73"/>
</svg>"""

SW = """const C='boss-v41';self.addEventListener('install',e=>e.waitUntil(caches.open(C).then(c=>c.addAll(['/','/manifest.webmanifest','/icon.svg']))));self.addEventListener('fetch',e=>{if(e.request.url.includes('/api/'))return;e.respondWith(fetch(e.request).catch(()=>caches.match(e.request)))})"""


class MobileWebServer:
    def __init__(self, bot: Any, host: str, port: int):
        self.bot = bot
        self.host = host
        self.port = int(port)
        self.runner: web.AppRunner | None = None

    async def start(self) -> None:
        app = web.Application()
        app.router.add_get("/", self.index)
        app.router.add_get("/api/status", self.status)
        app.router.add_get("/manifest.webmanifest", self.manifest)
        app.router.add_get("/sw.js", self.service_worker)
        app.router.add_get("/icon.svg", self.icon)
        self.runner = web.AppRunner(app, access_log=None)
        await self.runner.setup()
        site = web.TCPSite(self.runner, self.host, self.port)
        await site.start()
        log.info("iPhone dashboard listening on %s:%s", self.host, self.port)

    async def stop(self) -> None:
        if self.runner:
            await self.runner.cleanup()
            self.runner = None

    async def index(self, _request: web.Request) -> web.Response:
        return web.Response(text=HTML, content_type="text/html")

    async def status(self, _request: web.Request) -> web.Response:
        return web.json_response(self.bot.snapshot(), dumps=lambda obj: json.dumps(obj, ensure_ascii=False))

    async def manifest(self, _request: web.Request) -> web.Response:
        return web.json_response(MANIFEST)

    async def service_worker(self, _request: web.Request) -> web.Response:
        return web.Response(text=SW, content_type="application/javascript")

    async def icon(self, _request: web.Request) -> web.Response:
        return web.Response(text=ICON, content_type="image/svg+xml")
