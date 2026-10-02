const JSON_HEADERS={"content-type":"application/json; charset=utf-8","access-control-allow-origin":"*"};
const BINANCE="https://fapi.binance.com";
const SYMBOL="BTCUSDT";
const STRATEGY_VERSION="binance-15m-hedge-v1";
const CYCLE_SECONDS=900;

function nenv(v,f){const n=Number(v);return Number.isFinite(n)?n:f}
function benv(v,f=false){if(v===undefined||v===null||v==="")return f;return String(v).toLowerCase()==="true"}
function cfg(env){
  return {
    symbol:SYMBOL,
    notional:Math.max(5,nenv(env.HEDGE_NOTIONAL_USDT,10)),
    leverage:Math.max(1,Math.min(125,Math.floor(nenv(env.HEDGE_LEVERAGE,1)))),
    ka:Math.max(.01,nenv(env.HEDGE_KA,1.5)),
    kb:Math.max(.01,nenv(env.HEDGE_KB,.5)),
    be:benv(env.HEDGE_BE,true),
    fee:Math.max(0,nenv(env.HEDGE_FEE,.0005)),
    slip:Math.max(0,nenv(env.HEDGE_SLIP,.0001)),
    filter:benv(env.HEDGE_FILTER,true),
    live:benv(env.BINANCE_LIVE_TRADING,false)
  };
}
function tgToken(env){return String(env.CLOUD_TELEGRAM_BOT_TOKEN||env.TELEGRAM_BOT_TOKEN||"").trim()}
function tgChat(env){return String(env.CLOUD_TELEGRAM_CHAT_ID||env.TELEGRAM_CHAT_ID||"").trim()}
function tgOK(env){return !!(tgToken(env)&&tgChat(env))}
async function sendTelegram(env,text){
  if(!tgOK(env))return false;
  const r=await fetch("https://api.telegram.org/bot"+tgToken(env)+"/sendMessage",{
    method:"POST",headers:{"content-type":"application/json"},
    body:JSON.stringify({chat_id:tgChat(env),text,parse_mode:"HTML",disable_web_page_preview:true})
  });
  const j=await r.json().catch(()=>({}));
  if(!r.ok||!j?.ok)throw new Error("Telegram: "+String(j?.description||r.status));
  return true;
}
function money(v){const n=Number(v)||0;return (n>=0?"+":"")+n.toFixed(4)+" USDT"}
function pct(v){return (Number(v||0)*100).toFixed(3)+"%"}
function nowIso(){return new Date().toISOString()}
function cycleStartSec(ms=Date.now()){return Math.floor(ms/1000/CYCLE_SECONDS)*CYCLE_SECONDS}
function timeText(sec){return new Intl.DateTimeFormat("vi-VN",{timeZone:"Asia/Ho_Chi_Minh",hour:"2-digit",minute:"2-digit",hour12:false}).format(new Date(sec*1000))}
function json(data,status=200){return new Response(JSON.stringify(data),{status,headers:JSON_HEADERS})}
async function kvGet(env,key,fallback=null){
  try{const raw=await env.BOSS_KV.get(key);return raw?JSON.parse(raw):fallback}catch(_){return fallback}
}
async function kvPut(env,key,value){await env.BOSS_KV.put(key,JSON.stringify(value))}
function freshState(){
  return {
    strategyVersion:STRATEGY_VERSION,
    active:null,
    history:[],
    skipped:[],
    lastCycleStart:0,
    lastError:null,
    lastTick:null,
    updatedAt:nowIso()
  };
}
async function readState(env){
  let s=await kvGet(env,"hedge:state",null);
  if(!s||s.strategyVersion!==STRATEGY_VERSION)s=freshState();
  if(!Array.isArray(s.history))s.history=[];
  if(!Array.isArray(s.skipped))s.skipped=[];
  return s;
}
async function writeState(env,s){
  s.updatedAt=nowIso();
  await kvPut(env,"hedge:state",s);
  return s;
}

async function publicGet(path,params={}){
  const q=new URLSearchParams(Object.entries(params).filter(([,v])=>v!==undefined&&v!==null).map(([k,v])=>[k,String(v)]));
  const r=await fetch(BINANCE+path+(q.size?"?"+q:""),{headers:{"accept":"application/json"}});
  const text=await r.text();
  if(!r.ok)throw new Error("Binance "+r.status+": "+text.slice(0,300));
  return text?JSON.parse(text):{};
}
function hex(buf){return [...new Uint8Array(buf)].map(b=>b.toString(16).padStart(2,"0")).join("")}
async function hmac(secret,msg){
  const key=await crypto.subtle.importKey("raw",new TextEncoder().encode(secret),{name:"HMAC",hash:"SHA-256"},false,["sign"]);
  return hex(await crypto.subtle.sign("HMAC",key,new TextEncoder().encode(msg)));
}
function binanceConfigured(env){return !!(String(env.BINANCE_API_KEY||"").trim()&&String(env.BINANCE_API_SECRET||"").trim())}
async function signed(env,method,path,params={}){
  const key=String(env.BINANCE_API_KEY||"").trim();
  const secret=String(env.BINANCE_API_SECRET||"").trim();
  if(!key||!secret)throw new Error("Chưa cấu hình BINANCE_API_KEY/BINANCE_API_SECRET");
  const entries={...params,recvWindow:5000,timestamp:Date.now()};
  const qs=new URLSearchParams(Object.entries(entries).filter(([,v])=>v!==undefined&&v!==null).map(([k,v])=>[k,String(v)])).toString();
  const signature=await hmac(secret,qs);
  const r=await fetch(BINANCE+path+"?"+qs+"&signature="+signature,{
    method,headers:{"X-MBX-APIKEY":key,"accept":"application/json"}
  });
  const text=await r.text();
  if(!r.ok)throw new Error("Binance signed "+r.status+": "+text.slice(0,500));
  return text?JSON.parse(text):{};
}
async function signedSafe(env,method,path,params={}){
  try{return await signed(env,method,path,params)}catch(e){return {__error:String(e.message||e)}}
}

function stepFloor(v,step){
  const s=Number(step);if(!s)return Number(v);
  const p=Math.max(0,(String(step).split(".")[1]||"").length);
  return Number((Math.floor((Number(v)+1e-12)/s)*s).toFixed(p));
}
function tickRound(v,tick){
  const t=Number(tick);if(!t)return Number(v);
  const p=Math.max(0,(String(tick).split(".")[1]||"").length);
  return Number((Math.round(Number(v)/t)*t).toFixed(p));
}
async function symbolRules(){
  const x=await publicGet("/fapi/v1/exchangeInfo");
  const s=(x.symbols||[]).find(z=>z.symbol===SYMBOL);
  if(!s)throw new Error("Không tìm thấy "+SYMBOL+" trong exchangeInfo");
  const lot=(s.filters||[]).find(z=>z.filterType==="MARKET_LOT_SIZE")||(s.filters||[]).find(z=>z.filterType==="LOT_SIZE")||{};
  const price=(s.filters||[]).find(z=>z.filterType==="PRICE_FILTER")||{};
  return {stepSize:Number(lot.stepSize||.001),minQty:Number(lot.minQty||.001),tickSize:Number(price.tickSize||.1)};
}
async function ensureHedgeMode(env){
  const mode=await signed(env,"GET","/fapi/v1/positionSide/dual");
  if(mode?.dualSidePosition!==true)throw new Error("Tài khoản Binance Futures chưa bật Hedge Mode");
  return true;
}
async function setLeverage(env,lev){
  return signed(env,"POST","/fapi/v1/leverage",{symbol:SYMBOL,leverage:lev});
}

async function closed15mBodies(){
  const raw=await publicGet("/fapi/v1/klines",{symbol:SYMBOL,interval:"15m",limit:110});
  const now=Date.now();
  const closed=raw.filter(k=>Number(k[6])<now).slice(-100);
  if(closed.length<100)throw new Error("Chưa đủ 100 nến 15m đã đóng");
  const bodies=closed.map(k=>Math.abs(Number(k[4])-Number(k[1]))/Number(k[1]));
  const b20=bodies.slice(-20).reduce((a,b)=>a+b,0)/20;
  const b100=bodies.reduce((a,b)=>a+b,0)/100;
  return {b20,b100,lastClose:Number(closed[closed.length-1][4]),lastCloseTime:Number(closed[closed.length-1][6])};
}
async function tickerPrice(){const x=await publicGet("/fapi/v1/ticker/price",{symbol:SYMBOL});return Number(x.price)}
async function placeOrder(env,params){return signed(env,"POST","/fapi/v1/order",{symbol:SYMBOL,...params})}
async function cancelOrder(env,orderId){return signedSafe(env,"DELETE","/fapi/v1/order",{symbol:SYMBOL,orderId})}
async function getOrder(env,orderId){return signedSafe(env,"GET","/fapi/v1/order",{symbol:SYMBOL,orderId})}
async function positions(env){return signed(env,"GET","/fapi/v3/positionRisk",{symbol:SYMBOL})}

async function conditionClose(env,positionSide,type,stopPrice,tickSize){
  const side=positionSide==="LONG"?"SELL":"BUY";
  return placeOrder(env,{side,positionSide,type,stopPrice:tickRound(stopPrice,tickSize),closePosition:"true",workingType:"CONTRACT_PRICE",priceProtect:"false"});
}
function entryPrice(order,fallback){
  const avg=Number(order?.avgPrice);
  if(avg>0)return avg;
  const qty=Number(order?.executedQty),quote=Number(order?.cumQuote);
  if(qty>0&&quote>0)return quote/qty;
  return Number(fallback);
}
async function closePositionMarket(env,positionSide){
  const p=await positions(env);
  const row=(Array.isArray(p)?p:[]).find(x=>x.symbol===SYMBOL&&x.positionSide===positionSide);
  const amt=Math.abs(Number(row?.positionAmt||0));
  if(!(amt>0))return null;
  const side=positionSide==="LONG"?"SELL":"BUY";
  return placeOrder(env,{side,positionSide,type:"MARKET",quantity:amt,newOrderRespType:"RESULT"});
}
async function cancelLegOrders(env,leg){
  if(leg?.slOrderId)await cancelOrder(env,leg.slOrderId);
  if(leg?.tpOrderId)await cancelOrder(env,leg.tpOrderId);
}
async function cyclePnl(env,startMs,endMs){
  const j=await signedSafe(env,"GET","/fapi/v1/userTrades",{symbol:SYMBOL,startTime:startMs,endTime:endMs,limit:1000});
  if(!Array.isArray(j))return {pnl:null,realized:null,commission:null};
  let realized=0,commission=0;
  for(const t of j){realized+=Number(t.realizedPnl||0);commission+=Number(t.commission||0)}
  return {pnl:realized-commission,realized,commission};
}

async function openCycle(env,state,cycleStart){
  const c=cfg(env);
  const body=await closed15mBodies();
  const a=c.ka*body.b20,b=c.kb*body.b20;
  const ratio=body.b100>0?body.b20/body.b100:0;
  const filterPass=!c.filter||(ratio>=.8&&ratio<=2&&(a-b)>4*c.fee);
  const id=String(cycleStart);

  if(!filterPass){
    state.lastCycleStart=cycleStart;
    state.skipped.push({id,cycleStart,reason:"FILTER",b20:body.b20,b100:body.b100,ratio,a,b,at:nowIso()});
    state.skipped=state.skipped.slice(-192);
    await writeState(env,state);
    return state;
  }
  if(!c.live){
    state.lastCycleStart=cycleStart;
    state.skipped.push({id,cycleStart,reason:"LIVE_OFF",b20:body.b20,b100:body.b100,ratio,a,b,at:nowIso()});
    state.skipped=state.skipped.slice(-192);
    await writeState(env,state);
    return state;
  }
  if(!binanceConfigured(env))throw new Error("Chưa có Binance API key/secret trong Cloudflare Secret");
  await ensureHedgeMode(env);
  await setLeverage(env,c.leverage);
  const rules=await symbolRules();
  const px=await tickerPrice();
  const qty=Math.max(rules.minQty,stepFloor(c.notional/px,rules.stepSize));

  let lo=null,so=null;
  try{
    lo=await placeOrder(env,{side:"BUY",positionSide:"LONG",type:"MARKET",quantity:qty,newOrderRespType:"RESULT"});
    so=await placeOrder(env,{side:"SELL",positionSide:"SHORT",type:"MARKET",quantity:qty,newOrderRespType:"RESULT"});
  }catch(e){
    await closePositionMarket(env,"LONG").catch(()=>{});
    await closePositionMarket(env,"SHORT").catch(()=>{});
    throw e;
  }

  const eL=entryPrice(lo,px),eS=entryPrice(so,px);
  const legs={
    L:{positionSide:"LONG",entry:eL,tp:eL*(1+a),sl:eL*(1-b),slKind:"sl",done:false},
    S:{positionSide:"SHORT",entry:eS,tp:eS*(1-a),sl:eS*(1+b),slKind:"sl",done:false}
  };
  try{
    const lsl=await conditionClose(env,"LONG","STOP_MARKET",legs.L.sl,rules.tickSize);
    const ltp=await conditionClose(env,"LONG","TAKE_PROFIT_MARKET",legs.L.tp,rules.tickSize);
    const ssl=await conditionClose(env,"SHORT","STOP_MARKET",legs.S.sl,rules.tickSize);
    const stp=await conditionClose(env,"SHORT","TAKE_PROFIT_MARKET",legs.S.tp,rules.tickSize);
    legs.L.slOrderId=lsl.orderId;legs.L.tpOrderId=ltp.orderId;
    legs.S.slOrderId=ssl.orderId;legs.S.tpOrderId=stp.orderId;
  }catch(e){
    await cancelLegOrders(env,legs.L);await cancelLegOrders(env,legs.S);
    await closePositionMarket(env,"LONG").catch(()=>{});
    await closePositionMarket(env,"SHORT").catch(()=>{});
    throw e;
  }

  state.active={
    id,cycleStart,cycleEnd:cycleStart+CYCLE_SECONDS,openedAt:nowIso(),
    config:c,b20:body.b20,b100:body.b100,ratio,a,b,qty,rules,legs,beMoved:false
  };
  state.lastCycleStart=cycleStart;
  await writeState(env,state);
  await sendTelegram(env,
    "🟦 <b>HEDGE 15M ĐÃ MỞ</b>\n"+
    "BTCUSDT • "+timeText(cycleStart)+"–"+timeText(cycleStart+CYCLE_SECONDS)+"\n"+
    "LONG + SHORT • "+qty+" BTC mỗi chiều\n"+
    "ka "+c.ka+" • kb "+c.kb+" • BE "+(c.be?"BẬT":"TẮT")+"\n"+
    "b20 "+pct(body.b20)+" • b100 "+pct(body.b100)+"\n"+
    "TP "+pct(a)+" • SL "+pct(b)+" • đòn bẩy "+c.leverage+"x"
  ).catch(()=>{});
  return state;
}

async function refreshLeg(env,leg){
  if(leg.done)return leg;
  const sl=leg.slOrderId?await getOrder(env,leg.slOrderId):null;
  const tp=leg.tpOrderId?await getOrder(env,leg.tpOrderId):null;
  if(sl?.status==="FILLED"){leg.done=true;leg.why=leg.slKind||"sl";leg.closedAt=nowIso()}
  else if(tp?.status==="FILLED"){leg.done=true;leg.why="tp";leg.closedAt=nowIso()}
  return leg;
}
async function moveOtherToBE(env,active,stoppedKey){
  const c=active.config;
  if(!c.be||active.beMoved)return;
  const otherKey=stoppedKey==="L"?"S":"L";
  const g=active.legs[otherKey];
  if(!g||g.done||g.slKind!=="sl")return;
  await cancelOrder(env,g.slOrderId);
  const bePrice=otherKey==="L"?g.entry*(1+2*c.fee):g.entry*(1-2*c.fee);
  const o=await conditionClose(env,g.positionSide,"STOP_MARKET",bePrice,active.rules.tickSize);
  g.sl=bePrice;g.slOrderId=o.orderId;g.slKind="be";
  active.beMoved=true;
  active.beMovedAt=nowIso();
}
async function finishCycle(env,state,reason="time"){
  const a=state.active;if(!a)return state;
  for(const k of ["L","S"])await cancelLegOrders(env,a.legs[k]);
  await closePositionMarket(env,"LONG").catch(()=>{});
  await closePositionMarket(env,"SHORT").catch(()=>{});
  const p=await cyclePnl(env,a.cycleStart*1000-60000,Date.now()+60000);
  const row={...a,closedAt:nowIso(),closeReason:reason,pnl:p.pnl,realized:p.realized,commission:p.commission};
  state.history.push(row);state.history=state.history.slice(-192);state.active=null;
  await writeState(env,state);
  await sendTelegram(env,
    "⬛ <b>HEDGE 15M ĐÃ ĐÓNG</b>\n"+
    timeText(a.cycleStart)+"–"+timeText(a.cycleEnd)+" • "+reason+"\n"+
    "LONG: "+String(a.legs.L.why||"time").toUpperCase()+" • SHORT: "+String(a.legs.S.why||"time").toUpperCase()+"\n"+
    "PnL thực tế: <b>"+(p.pnl===null?"chưa đọc được":money(p.pnl))+"</b>"
  ).catch(()=>{});
  return state;
}
async function manageActive(env,state,nowSec){
  const a=state.active;if(!a)return state;
  await refreshLeg(env,a.legs.L);await refreshLeg(env,a.legs.S);
  if(a.config.be&&!a.beMoved){
    if(a.legs.L.done&&a.legs.L.why==="sl"&&!a.legs.S.done)await moveOtherToBE(env,a,"L");
    else if(a.legs.S.done&&a.legs.S.why==="sl"&&!a.legs.L.done)await moveOtherToBE(env,a,"S");
  }
  if(a.legs.L.done&&a.legs.S.done)return finishCycle(env,state,"orders");
  if(nowSec>=a.cycleEnd)return finishCycle(env,state,"time");
  await writeState(env,state);return state;
}

async function scheduledTick(env){
  const nowSec=Math.floor(Date.now()/1000);
  let state=await readState(env);
  state.lastTick=nowIso();
  try{
    state=await manageActive(env,state,nowSec);
    const cs=cycleStartSec();
    if(!state.active&&state.lastCycleStart!==cs){
      state=await openCycle(env,state,cs);
    }
    state.lastError=null;
  }catch(e){
    state.lastError=String(e.message||e);
    await sendTelegram(env,"⚠️ <b>HEDGE BOT LỖI</b>\n"+state.lastError).catch(()=>{});
  }
  await writeState(env,state);
}

function summarize24h(state){
  const since=Date.now()-24*3600*1000;
  const rows=(state.history||[]).filter(x=>new Date(x.closedAt||0).getTime()>=since);
  const pnl=rows.reduce((s,x)=>s+(Number.isFinite(Number(x.pnl))?Number(x.pnl):0),0);
  const wins=rows.filter(x=>Number(x.pnl)>0).length;
  const losses=rows.filter(x=>Number(x.pnl)<0).length;
  return {cycles:rows.length,wins,losses,pnl,rows};
}

export default {
  async fetch(req,env){
    const u=new URL(req.url);
    if(req.method==="OPTIONS")return new Response(null,{headers:{...JSON_HEADERS,"access-control-allow-methods":"GET,POST,OPTIONS","access-control-allow-headers":"content-type"}});
    if(u.pathname==="/health"){
      const c=cfg(env);
      return json({
        ok:true,service:"Boss Binance Hedge",strategyVersion:STRATEGY_VERSION,
        symbol:SYMBOL,interval:"15m",entry:"LONG+SHORT",binanceConfigured:binanceConfigured(env),
        liveTrading:c.live,hedgeModeRequired:true,telegramConfigured:tgOK(env),config:c,time:nowIso()
      });
    }
    if(u.pathname==="/state"){
      const s=await readState(env);return json({...s,summary24h:summarize24h(s),config:cfg(env),binanceConfigured:binanceConfigured(env)});
    }
    if(u.pathname==="/ticker"){
      try{return json({ok:true,price:await tickerPrice(),time:Date.now()})}catch(e){return json({ok:false,error:String(e.message||e)},502)}
    }
    if(u.pathname==="/klines"){
      const interval=String(u.searchParams.get("interval")||"1m");
      const limit=Math.max(1,Math.min(1500,Number(u.searchParams.get("limit")||1500)));
      const startTime=Number(u.searchParams.get("startTime")||0)||undefined;
      const endTime=Number(u.searchParams.get("endTime")||0)||undefined;
      try{return json(await publicGet("/fapi/v1/klines",{symbol:SYMBOL,interval,limit,startTime,endTime}))}
      catch(e){return json({ok:false,error:String(e.message||e)},502)}
    }
    if(u.pathname==="/mode"){
      try{
        if(!binanceConfigured(env))return json({ok:false,error:"Chưa có Binance API key/secret"},400);
        return json({ok:true,mode:await signed(env,"GET","/fapi/v1/positionSide/dual")});
      }catch(e){return json({ok:false,error:String(e.message||e)},502)}
    }
    if(u.pathname==="/reset"&&req.method==="POST"){
      const old=await readState(env);
      if(old.active)return json({ok:false,error:"Đang có chu kỳ hedge mở; không reset khi còn vị thế."},409);
      const s=freshState();await writeState(env,s);return json({ok:true,state:s});
    }
    if(u.pathname==="/tick"&&req.method==="POST"){
      await scheduledTick(env);return json({ok:true,state:await readState(env)});
    }
    return json({ok:true,endpoints:["/health","/state","/ticker","/klines","/mode","/reset","/tick"]});
  },
  async scheduled(controller,env,ctx){ctx.waitUntil(scheduledTick(env))}
};
