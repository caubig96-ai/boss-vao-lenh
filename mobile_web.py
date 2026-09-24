from __future__ import annotations

import hashlib
import hmac
import json
import logging
from typing import Any

from aiohttp import web

log = logging.getLogger("boss-mobile")

LOGIN_HTML = r"""<!doctype html>
<html lang="vi"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#0f1318"><title>Boss Login</title>
<style>
:root{color-scheme:dark}*{box-sizing:border-box}body{margin:0;background:#0f1318;color:#f3f6f8;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
main{max-width:440px;margin:auto;padding:80px 18px}section{background:#171d24;border:1px solid #28313b;border-radius:20px;padding:22px}
h1{margin:0 0 8px;font-size:25px}.muted{color:#93a0ad;font-size:13px;margin-bottom:18px}input,button{width:100%;border:0;border-radius:12px;padding:14px;font-size:16px}
input{background:#0f1318;color:white;border:1px solid #28313b;margin-bottom:12px}button{background:#4ba3ff;color:white;font-weight:800}.err{color:#ff8585;margin-top:12px}
</style></head><body><main><section>
<h1>Boss 5 Nến</h1><div class="muted">Đăng nhập giao diện iPhone</div>
<form method="post" action="/login">
<input type="password" name="password" placeholder="Mật khẩu" autocomplete="current-password" autofocus>
<button type="submit">MỞ BOSS</button>
</form>
<div class="err">__ERROR__</div>
</section></main></body></html>"""

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
button,input{border:0;border-radius:12px;padding:11px 12px;font-size:14px}button{background:var(--b);color:white;font-weight:800}button.secondary{background:#2a333d}button.danger{background:#6d2e2e}
input{background:#0f1318;color:white;border:1px solid var(--line);width:100%}.form{display:grid;grid-template-columns:1fr 1fr;gap:9px}.field .label{margin-bottom:5px}.wide{grid-column:1/-1}.msg{font-size:12px;color:var(--muted);margin-top:8px}
</style>
</head>
<body><main>
<div class="row"><div><h1>Boss 5 Nến</h1><div class="sub" id="source">Đang kết nối...</div></div><button class="secondary" onclick="location.href='/logout'">Thoát</button></div>

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
  <b>Cài đặt</b>
  <div class="form" style="margin-top:12px">
    <div class="field"><div class="label">Lệnh 1 (USDT)</div><input id="bet1" inputmode="decimal"></div>
    <div class="field"><div class="label">Lệnh 2 (USDT)</div><input id="bet2" inputmode="decimal"></div>
    <div class="field"><div class="label">Vốn đầu ngày</div><input id="start" inputmode="decimal"></div>
    <div class="field"><div class="label">Trả thưởng (%)</div><input id="payout" inputmode="decimal"></div>
    <div class="wide row"><label><input id="tgEnabled" type="checkbox" style="width:auto"> Gửi Telegram</label><button onclick="saveSettings()">LƯU</button></div>
    <div class="wide row"><button class="secondary" onclick="testTelegram()">TEST TELEGRAM</button><span id="actionMsg" class="msg"></span></div>
  </div>
</section>

<section class="card">
  <div class="row"><div><b>100 lệnh gần nhất</b><div class="label">V = thắng • X = thua</div></div><button onclick="refresh()">Làm mới</button></div>
  <div class="history" id="history" style="margin-top:13px"></div>
</section>

<section class="card">
  <div class="label">Telegram / Cloud</div>
  <div id="telegram" class="ok">--</div>
  <div id="error" class="err"></div>
</section>

<div class="foot">Boss chạy trên cloud 24/7. Anh có thể tắt PC và tắt iPhone; server vẫn tiếp tục đọc kết quả 5 phút, lưu lịch sử và gửi Telegram. Khi cần xem lại, chỉ mở biểu tượng Boss trên iPhone.</div>
</main>
<script>
const $=id=>document.getElementById(id);let loaded=false;
function money(v){return Number(v||0).toFixed(2)+" USDT"}
async function api(url,opt={}){const r=await fetch(url,{cache:"no-store",...opt});if(r.status===401){location.href="/login";throw new Error("Phiên đăng nhập hết hạn")}const j=await r.json();if(!r.ok)throw new Error(j.error||"Lỗi");return j}
async function refresh(){
  try{
    const s=await api("/api/status");
    $("source").textContent=(s.source_label||"Prediction")+" • "+(s.connected?"Đang chạy 24/7":"Đang chờ dữ liệu");
    $("candles").innerHTML="";
    (s.colors||[]).forEach(c=>{const d=document.createElement("div");d.className="dot "+(c==="G"?"g":"r");d.textContent="●";$("candles").appendChild(d)});
    while($("candles").children.length<5){const d=document.createElement("div");d.className="dot";d.textContent="·";$("candles").appendChild(d)}
    const rec=s.recommendation;$("buy").textContent=rec==="G"?"MUA XANH":rec==="R"?"MUA ĐỎ":"KHÔNG KHỚP MẪU";$("buy").className="big "+(rec==="G"?"green":rec==="R"?"red":"");
    $("frame").textContent=s.frame||"--";$("bet").textContent="Lệnh "+(s.current_step||1)+" • "+money(s.next_bet);
    $("wins").textContent=s.wins||0;$("losses").textContent=s.losses||0;$("pnl").textContent=money(s.daily_pnl);$("pnl").className=Number(s.daily_pnl)>0?"green":Number(s.daily_pnl)<0?"red":"";$("balance").textContent=money(s.end_balance);
    const marks=(s.history||[]).slice(-100);$("history").innerHTML="";for(let i=0;i<100;i++){const d=document.createElement("div");const m=marks[i-(100-marks.length)];d.className="cell "+(m==="V"?"v":m==="X"?"x":"");d.textContent=m||"·";$("history").appendChild(d)}
    $("telegram").textContent=s.telegram_status||"Chưa có trạng thái";$("error").textContent=s.error||s.source_error||"";
    if(!loaded){$("bet1").value=Number(s.bet1||1).toFixed(2);$("bet2").value=Number(s.bet2||2).toFixed(2);$("start").value=Number(s.start_balance||0).toFixed(2);$("payout").value=Number(s.payout_percent||80).toFixed(2);$("tgEnabled").checked=!!s.telegram_enabled;loaded=true}
  }catch(e){$("error").textContent=String(e)}
}
async function saveSettings(){
  try{
    $("actionMsg").textContent="Đang lưu...";
    await api("/api/settings",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({bet1:Number($("bet1").value),bet2:Number($("bet2").value),start_balance:Number($("start").value),payout_percent:Number($("payout").value),telegram_enabled:$("tgEnabled").checked})});
    $("actionMsg").textContent="Đã lưu";loaded=false;await refresh();
  }catch(e){$("actionMsg").textContent="Lỗi: "+e}
}
async function testTelegram(){
  try{$("actionMsg").textContent="Đang gửi...";await api("/api/test-telegram",{method:"POST"});$("actionMsg").textContent="Đã gửi tin test";await refresh()}catch(e){$("actionMsg").textContent="Lỗi: "+e}
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

ICON = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128"><rect width="128" height="128" rx="28" fill="#0f1318"/><circle cx="38" cy="38" r="18" fill="#08bf73"/><circle cx="90" cy="38" r="18" fill="#ff4545"/><circle cx="38" cy="90" r="18" fill="#ff4545"/><circle cx="90" cy="90" r="18" fill="#08bf73"/></svg>"""
SW = """const C='boss-v42';self.addEventListener('install',e=>e.waitUntil(caches.open(C).then(c=>c.addAll(['/manifest.webmanifest','/icon.svg']))));self.addEventListener('fetch',e=>{if(e.request.method!=='GET'||e.request.url.includes('/api/')||e.request.url.includes('/login'))return;e.respondWith(fetch(e.request).catch(()=>caches.match(e.request)))})"""


class MobileWebServer:
    def __init__(self, bot: Any, host: str, port: int, password: str):
        self.bot = bot
        self.host = host
        self.port = int(port)
        self.password = str(password)
        self.runner: web.AppRunner | None = None
        self.cookie_value = hashlib.sha256(("boss-v42:" + self.password).encode("utf-8")).hexdigest()

    def _authorized(self, request: web.Request) -> bool:
        value = request.cookies.get("boss_session", "")
        return bool(value) and hmac.compare_digest(value, self.cookie_value)

    def _need_auth(self, request: web.Request, *, api: bool = False):
        if self._authorized(request):
            return None
        if api:
            return web.json_response({"error": "Chưa đăng nhập"}, status=401)
        raise web.HTTPFound("/login")

    async def start(self) -> None:
        app = web.Application(client_max_size=64 * 1024)
        app.router.add_get("/login", self.login_form)
        app.router.add_post("/login", self.login)
        app.router.add_get("/logout", self.logout)
        app.router.add_get("/", self.index)
        app.router.add_get("/api/status", self.status)
        app.router.add_post("/api/settings", self.settings)
        app.router.add_post("/api/test-telegram", self.test_telegram)
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

    async def login_form(self, request: web.Request) -> web.Response:
        if self._authorized(request):
            raise web.HTTPFound("/")
        return web.Response(text=LOGIN_HTML.replace("__ERROR__", ""), content_type="text/html")

    async def login(self, request: web.Request) -> web.Response:
        data = await request.post()
        supplied = str(data.get("password", ""))
        if not hmac.compare_digest(supplied, self.password):
            return web.Response(
                text=LOGIN_HTML.replace("__ERROR__", "Sai mật khẩu."),
                content_type="text/html",
                status=401,
            )
        response = web.HTTPFound("/")
        response.set_cookie(
            "boss_session",
            self.cookie_value,
            max_age=60 * 60 * 24 * 30,
            httponly=True,
            samesite="Lax",
            secure=request.secure,
        )
        return response

    async def logout(self, _request: web.Request) -> web.Response:
        response = web.HTTPFound("/login")
        response.del_cookie("boss_session")
        return response

    async def index(self, request: web.Request) -> web.Response:
        auth = self._need_auth(request)
        if auth:
            return auth
        return web.Response(text=HTML, content_type="text/html")

    async def status(self, request: web.Request) -> web.Response:
        auth = self._need_auth(request, api=True)
        if auth:
            return auth
        return web.json_response(self.bot.snapshot(), dumps=lambda obj: json.dumps(obj, ensure_ascii=False))

    async def settings(self, request: web.Request) -> web.Response:
        auth = self._need_auth(request, api=True)
        if auth:
            return auth
        try:
            payload = await request.json()
            await self.bot.update_settings(
                bet1=float(payload["bet1"]),
                bet2=float(payload["bet2"]),
                start_balance=float(payload["start_balance"]),
                payout_percent=float(payload["payout_percent"]),
                telegram_enabled=bool(payload["telegram_enabled"]),
            )
            return web.json_response({"ok": True})
        except Exception as exc:
            return web.json_response({"error": str(exc)}, status=400)

    async def test_telegram(self, request: web.Request) -> web.Response:
        auth = self._need_auth(request, api=True)
        if auth:
            return auth
        try:
            message_id = await self.bot.test_telegram()
            return web.json_response({"ok": True, "message_id": message_id})
        except Exception as exc:
            return web.json_response({"error": str(exc)}, status=502)

    async def manifest(self, _request: web.Request) -> web.Response:
        return web.json_response(MANIFEST)

    async def service_worker(self, _request: web.Request) -> web.Response:
        return web.Response(text=SW, content_type="application/javascript")

    async def icon(self, _request: web.Request) -> web.Response:
        return web.Response(text=ICON, content_type="image/svg+xml")
