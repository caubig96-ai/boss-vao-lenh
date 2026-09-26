const API="https://api.predict.fun";
const INTERVAL=300;
const PATTERN_VERSION="image-8-v1";
const JSON_HEADERS={"content-type":"application/json; charset=utf-8","access-control-allow-origin":"*"};

const PATTERNS={
  RGRR:"R",
  GRGR:"G",
  RRGR:"R",
  GGRR:"G",
  RGRG:"R",
  GRGG:"G",
  RRGG:"R",
  GGRG:"G"
};

function numericEnv(value,fallback){
  const n=Number(value);
  return Number.isFinite(n)?n:fallback;
}

function tradeSettings(env){
  const bet1=Math.max(0,numericEnv(env.CLOUD_BET1,1));
  const bet2=Math.max(0,numericEnv(env.CLOUD_BET2,2));
  const payoutPct=Math.max(0,numericEnv(env.CLOUD_PAYOUT_PERCENT,80));
  const startBalance=numericEnv(env.CLOUD_START_BALANCE,0);
  return {bet1,bet2,payout:payoutPct/100,payoutPct,startBalance};
}

function money(value){
  const n=Number(value)||0;
  return (n>=0?"+":"")+n.toFixed(2)+" USDT";
}

function amountText(value){
  return Number(value||0).toFixed(2)+" USDT";
}

function dayTextFromSeconds(ts){
  return new Intl.DateTimeFormat("en-CA",{
    timeZone:"Asia/Ho_Chi_Minh",
    year:"numeric",month:"2-digit",day:"2-digit"
  }).format(new Date(ts*1000));
}

function freshTradeState(day){
  return {
    day,
    step:1,
    pnl:0,
    wins:0,
    losses:0,
    lossStreak:0,
    pauseUntil:0,
    pending:null,
    unsentResult:null,
    completed:[],
    updatedAt:new Date().toISOString()
  };
}

async function readTradeState(env,nowSec=Math.floor(Date.now()/1000)){
  const raw=await env.BOSS_KV.get("telegram:trade_state");
  let state=null;
  try{state=raw?JSON.parse(raw):null}catch(_){}
  if(!state||typeof state!=="object")state=freshTradeState(dayTextFromSeconds(nowSec));
  if(!Number.isFinite(Number(state.step)))state.step=1;
  if(!Number.isFinite(Number(state.pnl)))state.pnl=0;
  if(!Number.isFinite(Number(state.wins)))state.wins=0;
  if(!Number.isFinite(Number(state.losses)))state.losses=0;
  if(!Number.isFinite(Number(state.lossStreak)))state.lossStreak=0;
  if(!Number.isFinite(Number(state.pauseUntil)))state.pauseUntil=0;
  if(!Array.isArray(state.completed))state.completed=[];
  if(state.unsentResult===undefined)state.unsentResult=null;
  if(!state.day)state.day=dayTextFromSeconds(nowSec);
  return state;
}

async function writeTradeState(env,state){
  state.updatedAt=new Date().toISOString();
  await env.BOSS_KV.put("telegram:trade_state",JSON.stringify(state));
  return state;
}

function nextStepAfter(step,win){
  return Number(step)===1&&win?2:1;
}

function amountForStep(settings,step){
  return Number(step)===2?settings.bet2:settings.bet1;
}

function json(data,status=200){
  return new Response(JSON.stringify(data),{status,headers:JSON_HEADERS});
}

async function api(path,key){
  const r=await fetch(API+path,{headers:{"x-api-key":key,"accept":"application/json"}});
  if(!r.ok)throw new Error("Predict API "+r.status+": "+(await r.text()).slice(0,180));
  return r.json();
}

async function apiCategory(ts,key){
  const r=await fetch(API+"/v1/categories/btc-updown-5m-"+Math.floor(ts),{
    headers:{"x-api-key":key,"accept":"application/json"}
  });
  if(r.status===404)return null;
  if(!r.ok)throw new Error("Predict API "+r.status+": "+(await r.text()).slice(0,180));
  return r.json();
}

function pick(obj,...paths){
  for(const p of paths){
    let v=obj;
    for(const k of p.split("."))v=v?.[k];
    if(v!==undefined&&v!==null)return v;
  }
}

function outcomeFromMarket(m){
  if(!m||typeof m!=="object")return "";
  const outcomes=Array.isArray(m.outcomes)?m.outcomes:[];
  const wonOutcome=outcomes.find(o=>String(o?.status||"").toUpperCase()==="WON");
  if(wonOutcome?.name)return String(wonOutcome.name);
  const resolution=m.resolution;
  if(resolution&&typeof resolution==="object"){
    if(String(resolution.status||"").toUpperCase()==="WON"&&resolution.name){
      return String(resolution.name);
    }
    if(resolution.name)return String(resolution.name);
  }
  return "";
}

function normalizeColor(outcome){
  const s=String(outcome||"").trim().toUpperCase();
  if(!s)return null;
  if(s==="UP"||s==="YES"||s==="GREEN"||s==="TRUE"||/(^|\W)UP($|\W)/.test(s))return "V";
  if(s==="DOWN"||s==="NO"||s==="RED"||s==="FALSE"||/(^|\W)DOWN($|\W)/.test(s))return "X";
  return null;
}

function normalizeCategory(input){
  const x=input?.data||input||{};
  const slug=String(pick(x,"slug","market.slug","category.slug")||"");
  if(!/btc-updown-5m-/i.test(slug))return null;
  const ts=Number((slug.match(/(\d{10,13})$/)||[])[1]||0);
  const markets=Array.isArray(x?.markets)?x.markets:[];

  let outcome="";
  for(const market of markets){
    outcome=outcomeFromMarket(market);
    if(normalizeColor(outcome))break;
  }
  if(!outcome){
    outcome=String(
      pick(x,"outcome","result","resolution.name","market.outcome","market.result","market.resolution.name")||""
    );
  }

  return {
    slug,
    ts:ts>1e12?Math.floor(ts/1000):ts,
    color:normalizeColor(outcome),
    outcome
  };
}

function finitePrice(...values){
  for(const value of values){
    const n=Number(value);
    if(Number.isFinite(n)&&n>0)return n;
  }
  return null;
}

function liveColorFromCategory(payload){
  const d=payload?.data||payload||{};
  const m=(d.markets||[])[0]||{};
  const categoryCrypto=d?.variantDetails?.crypto||d?.variantData||{};
  const marketCrypto=m?.variantData||{};
  const startPrice=finitePrice(categoryCrypto.startPrice,marketCrypto.startPrice,d.startPrice,m.startPrice);
  const currentPrice=finitePrice(
    categoryCrypto.currentPrice,categoryCrypto.lastPrice,categoryCrypto.indexPrice,
    categoryCrypto.markPrice,categoryCrypto.endPrice,
    marketCrypto.currentPrice,marketCrypto.lastPrice,marketCrypto.indexPrice,
    marketCrypto.markPrice,marketCrypto.endPrice,
    d.currentPrice,d.lastPrice,d.indexPrice,d.markPrice
  );
  if(startPrice&&currentPrice&&currentPrice!==startPrice)return currentPrice>startPrice?"G":"R";
  return null;
}

async function readHistory(env){
  const raw=await env.BOSS_KV.get("history");
  if(!raw)return {updatedAt:null,count:0,rawMatched:0,skippedWithoutOutcome:0,rounds:[]};
  try{return JSON.parse(raw)}catch(_){return {updatedAt:null,count:0,rawMatched:0,skippedWithoutOutcome:0,rounds:[]}}
}

async function writeHistory(env,rounds,extra={}){
  const unique=[...new Map(rounds.filter(x=>x?.slug&&x?.color).map(x=>[x.slug,x])).values()]
    .sort((a,b)=>a.ts-b.ts)
    .slice(-500);
  const payload={
    updatedAt:new Date().toISOString(),
    count:unique.length,
    rawMatched:Number(extra.rawMatched??unique.length),
    skippedWithoutOutcome:Number(extra.skippedWithoutOutcome??0),
    rounds:unique
  };
  await env.BOSS_KV.put("history",JSON.stringify(payload));
  return payload;
}

async function sync(env){
  if(!env.PREDICT_API_KEY)throw new Error("Chưa cấu hình PREDICT_API_KEY");
  if(!env.BOSS_KV)throw new Error("Chưa cấu hình binding BOSS_KV");

  let after="",pages=0,found=[],rawMatched=0;
  while(pages<8&&found.length<500){
    const q=new URLSearchParams({first:"100",status:"RESOLVED",marketVariant:"CRYPTO_UP_DOWN"});
    if(after)q.set("after",after);
    const d=await api("/v1/categories?"+q,env.PREDICT_API_KEY);
    const items=d?.data?.items||d?.items||d?.data||[];
    if(!Array.isArray(items))break;

    const normalized=items.map(normalizeCategory).filter(Boolean);
    rawMatched+=normalized.length;
    found.push(...normalized.filter(x=>!!x.color));

    after=d?.data?.pageInfo?.endCursor||d?.pageInfo?.endCursor||d?.cursor||"";
    pages++;
    if(!after||items.length===0)break;
  }

  return writeHistory(env,found,{
    rawMatched,
    skippedWithoutOutcome:Math.max(0,rawMatched-found.length)
  });
}

async function refreshRecent(env){
  const history=await readHistory(env);
  const now=Math.floor(Date.now()/1000);
  const currentStart=Math.floor(now/INTERVAL)*INTERVAL;
  const additions=[];

  for(const ts of [currentStart-INTERVAL,currentStart-2*INTERVAL]){
    try{
      const raw=await apiCategory(ts,env.PREDICT_API_KEY);
      const item=normalizeCategory(raw);
      if(item?.color)additions.push(item);
    }catch(_){}
  }

  if(!additions.length)return history;
  return writeHistory(env,[...(history.rounds||[]),...additions],{
    rawMatched:Math.max(Number(history.rawMatched||0),Number(history.count||0)+additions.length),
    skippedWithoutOutcome:Number(history.skippedWithoutOutcome||0)
  });
}

function internalRounds(payload){
  return (payload?.rounds||[])
    .map(x=>({t:Number(x.ts),c:x.color==="V"?"G":x.color==="X"?"R":null}))
    .filter(x=>Number.isFinite(x.t)&&x.c)
    .sort((a,b)=>a.t-b.t);
}

function contiguous(arr){
  return arr.slice(1).every((x,i)=>x.t-arr[i].t===INTERVAL);
}

function settledSignals(rounds){
  const byTime=new Map(rounds.map(x=>[x.t,x]));
  const out=[];
  for(let i=3;i<rounds.length;i++){
    const w=rounds.slice(i-3,i+1);
    if(!contiguous(w))continue;
    const code=w.map(x=>x.c).join("");
    const pred=PATTERNS[code];
    if(!pred)continue;
    const actual=byTime.get(w[3].t+INTERVAL)?.c||null;
    if(actual)out.push({pattern:code,pred,actual,win:pred===actual,sourceT:w[3].t});
  }
  return out;
}

function decisionFor(code,rounds){
  const pred=PATTERNS[code]||null;
  if(!pred)return {allow:false,direction:null,rate:null,mode:"NONE",wins:0,losses:0,settled:0,pair:"",reason:"Không thuộc 8 nhóm"};

  const recent100=settledSignals(rounds).slice(-100);
  const sameGroup=recent100.filter(s=>s.pattern===code);
  let wins=0,losses=0;
  for(const s of sameGroup){
    if(s.win)wins++;
    else losses++;
  }

  // Two nearest results are stored newest first to match the requested reading:
  // V-V => follow; X-X => reverse; V-X => follow; X-V => reverse.
  const two=sameGroup.slice(-2).reverse();
  if(two.length<2){
    return {
      allow:false,
      direction:null,
      rate:sameGroup.length?wins/sameGroup.length*100:null,
      mode:"NEED_2",
      wins,
      losses,
      settled:sameGroup.length,
      pair:two.map(x=>x.win?"V":"X").join("-"),
      reason:"Chưa đủ 2 kết quả gần nhất của nhóm này trong 100 lệnh"
    };
  }

  const pair=two.map(x=>x.win?"V":"X").join("-");
  const latestWon=two[0].win===true;
  const direction=latestWon?pred:(pred==="G"?"R":"G");
  const mode=pair==="V-V"
    ?"FOLLOW_VV"
    :pair==="X-X"
      ?"REVERSE_XX"
      :pair==="V-X"
        ?"FOLLOW_VX"
        :"REVERSE_XV";

  return {
    allow:true,
    direction,
    rate:wins/(wins+losses)*100,
    mode,
    wins,
    losses,
    settled:sameGroup.length,
    pair,
    reason:latestWon
      ?"Kết quả gần nhất thắng → đánh theo màu gốc của nhóm"
      :"Kết quả gần nhất thua → đảo màu lệnh"
  };
}

function tgToken(env){return String(env.CLOUD_TELEGRAM_BOT_TOKEN||env.TELEGRAM_BOT_TOKEN||"").trim()}
function tgChat(env){return String(env.CLOUD_TELEGRAM_CHAT_ID||env.TELEGRAM_CHAT_ID||"").trim()}
function telegramConfigured(env){return !!(tgToken(env)&&tgChat(env))}

async function sendTelegram(env,text){
  if(!telegramConfigured(env))return false;
  const r=await fetch("https://api.telegram.org/bot"+tgToken(env)+"/sendMessage",{
    method:"POST",
    headers:{"content-type":"application/json"},
    body:JSON.stringify({
      chat_id:tgChat(env),
      text,
      parse_mode:"HTML",
      disable_web_page_preview:true
    })
  });
  const data=await r.json().catch(()=>({}));
  if(!r.ok||!data?.ok)throw new Error("Telegram: "+String(data?.description||r.status));
  return true;
}

function timeText(ts){
  return new Intl.DateTimeFormat("vi-VN",{
    timeZone:"Asia/Ho_Chi_Minh",
    hour:"2-digit",
    minute:"2-digit",
    hour12:false
  }).format(new Date(ts*1000));
}

function frameText(ts){
  return timeText(ts)+"–"+timeText(ts+INTERVAL);
}

function candleIcons(code){
  return String(code||"").split("").map(c=>c==="G"?"🟢":c==="R"?"🔴":"⚪").join(" ");
}

async function sendReadyOnce(env){
  if(!telegramConfigured(env))return;
  const key="telegram:ready:v1";
  if(await env.BOSS_KV.get(key))return;
  await sendTelegram(env,
    "✅ <b>BOSS CLOUD ĐÃ CHẠY TELEGRAM</b>\n"+
    "iPhone có thể khóa màn hình. Khi có tín hiệu đạt điều kiện, Boss Cloud sẽ gửi thông báo Telegram."
  );
  await env.BOSS_KV.put(key,new Date().toISOString());
}


async function settlePreviousOrder(env,payload,nowSec,state){
  const pending=state.pending;
  if(!pending)return {state,result:null};

  const currentStart=Math.floor(nowSec/INTERVAL)*INTERVAL;
  if(Number(pending.targetStart)>=currentStart)return {state,result:null};

  const rounds=internalRounds(payload);
  const actual=rounds.find(x=>x.t===Number(pending.targetStart))?.c||null;
  if(!actual)return {state,result:null};

  const settings=tradeSettings(env);
  const win=String(pending.direction)===actual;
  const amount=Number(pending.amount)||0;
  const payout=Number(pending.payoutRate);
  const effectivePayout=Number.isFinite(payout)?payout:settings.payout;
  const delta=win?amount*effectivePayout:-amount;

  state.pnl=Number(state.pnl||0)+delta;
  if(win)state.wins=Number(state.wins||0)+1;
  else state.losses=Number(state.losses||0)+1;

  let pauseTriggered=false;
  if(win){
    state.lossStreak=0;
  }else{
    state.lossStreak=Number(state.lossStreak||0)+1;
    if(state.lossStreak>=2){
      state.pauseUntil=nowSec+15*60;
      state.lossStreak=0;
      pauseTriggered=true;
    }
  }

  const nextStep=nextStepAfter(pending.step,win);
  state.step=nextStep;

  const result={
    id:pending.id,
    targetStart:Number(pending.targetStart),
    pattern:pending.pattern,
    direction:pending.direction,
    actual,
    step:Number(pending.step),
    amount,
    win,
    delta,
    pnlAfter:Number(state.pnl||0),
    winsAfter:Number(state.wins||0),
    lossesAfter:Number(state.losses||0),
    nextStep,
    lossStreakAfter:Number(state.lossStreak||0),
    pauseTriggered,
    pauseUntilAfter:Number(state.pauseUntil||0),
    settledAt:new Date().toISOString(),
    sent:false
  };

  state.completed.push({...result});
  state.completed=state.completed.slice(-200);
  state.unsentResult=result;
  state.pending=null;
  await writeTradeState(env,state);
  return {state,result};
}

async function maybePrepare(env,payload,nowSec){
  if(!telegramConfigured(env))return;
  const liveStart=Math.floor(nowSec/INTERVAL)*INTERVAL;
  const remain=liveStart+INTERVAL-nowSec;
  if(remain>70||remain<=45)return;

  const rounds=internalRounds(payload);
  const byTime=new Map(rounds.map(x=>[x.t,x]));
  const closed3=[
    liveStart-3*INTERVAL,
    liveStart-2*INTERVAL,
    liveStart-INTERVAL
  ].map(t=>byTime.get(t));
  if(closed3.some(x=>!x))return;

  let liveRaw=null;
  try{liveRaw=await apiCategory(liveStart,env.PREDICT_API_KEY)}catch(_){return}
  const liveColor=liveColorFromCategory(liveRaw);
  if(!liveColor)return;

  const code=closed3.map(x=>x.c).join("")+liveColor;
  const d=decisionFor(code,rounds);
  if(!d.allow||!d.direction)return;

  const targetStart=liveStart+INTERVAL;
  const currentDay=dayTextFromSeconds(targetStart);
  let state=await readTradeState(env,nowSec);

  if(state.day!==currentDay&&!state.pending){
    const carriedPause=Number(state.pauseUntil||0);
    const carriedLossStreak=Number(state.lossStreak||0);
    state=freshTradeState(currentDay);
    state.pauseUntil=carriedPause;
    state.lossStreak=carriedLossStreak;
  }

  if(Number(state.pauseUntil||0)>nowSec)return;
  if(Number(state.pauseUntil||0)>0&&Number(state.pauseUntil||0)<=nowSec){
    state.pauseUntil=0;
    await writeTradeState(env,state);
  }

  if(state.pending&&Number(state.pending.targetStart)!==targetStart)return;

  const settings=tradeSettings(env);
  if(!state.pending){
    const step=Number(state.step)===2?2:1;
    const amount=amountForStep(settings,step);
    state.pending={
      id:String(targetStart)+"-"+code,
      day:currentDay,
      targetStart,
      pattern:code,
      direction:d.direction,
      mode:d.mode,
      recentPair:d.pair||"",
      rate:Number(d.rate||0),
      wins:Number(d.wins||0),
      losses:Number(d.losses||0),
      settled:Number(d.settled||0),
      step,
      amount,
      payoutRate:settings.payout,
      entrySent:false,
      createdAt:new Date().toISOString()
    };
    await writeTradeState(env,state);
  }

  const pending=state.pending;
  if(pending.entrySent)return;

  const buy=pending.direction==="G"?"🟢 <b>MUA XANH NGAY</b>":"🔴 <b>MUA ĐỎ NGAY</b>";
  const modeText=String(pending.mode||"").startsWith("REVERSE")?"ĐẢO MÀU":"ĐÁNH THEO MÀU GỐC";
  const statsLine="2 kết quả gần nhất: <b>"+String(pending.recentPair||"--")+"</b> • <b>"+modeText+"</b>\n"+
    "Trong 100 lệnh: <b>"+Number(pending.wins||0)+" thắng / "+Number(pending.losses||0)+" thua</b>\n";

  await sendTelegram(env,
    "🚨 <b>CÒN ~1 PHÚT • VÀO LỆNH PHIÊN SAU</b>\n"+
    "4 nến nhận dạng: <b>"+candleIcons(pending.pattern)+"</b>\n"+
    statsLine+
    buy+"\n"+
    "<b>Lệnh "+Number(pending.step)+" • "+amountText(pending.amount)+"</b>\n"+
    "Phiên mua: <b>"+frameText(pending.targetStart)+"</b>"
  );

  pending.entrySent=true;
  pending.entrySentAt=new Date().toISOString();
  await writeTradeState(env,state);
  await env.BOSS_KV.put("telegram:last_prepare",String(targetStart));
}

async function schedulePrepareAt60(env,payload){
  const nowSec=Math.floor(Date.now()/1000);
  const liveStart=Math.floor(nowSec/INTERVAL)*INTERVAL;
  const remain=liveStart+INTERVAL-nowSec;

  // Cron runs every minute; send once when the active 5-minute frame has about 60 seconds left.
  if(remain>70||remain<=45)return;
  await maybePrepare(env,payload,nowSec);
}

function resultMessagePart(result,settings){
  if(!result)return "";
  const title=result.win?"✅ <b>THẮNG LỆNH</b>":"❌ <b>THUA LỆNH</b>";
  const actualText=result.actual==="G"?"🟢 XANH":"🔴 ĐỎ";
  const entered=result.direction==="G"?"🟢 XANH":"🔴 ĐỎ";
  const balance=settings.startBalance+Number(result.pnlAfter||0);
  const pauseLine=result.pauseTriggered
    ?"\n⏸ <b>TẠM DỪNG BÁO LỆNH 15 PHÚT</b> • chạy lại sau "+timeText(result.pauseUntilAfter)
    :"";

  return (
    title+"\n"+
    "Phiên: <b>"+frameText(result.targetStart)+"</b>\n"+
    "Đã mua: "+entered+" • Kết quả: "+actualText+"\n"+
    "Lãi/lỗ lệnh: <b>"+money(result.delta)+"</b>\n"+
    "Lãi/lỗ hôm nay: <b>"+money(result.pnlAfter)+"</b>\n"+
    "Thắng/Thua hôm nay: <b>"+Number(result.winsAfter)+"/"+Number(result.lossesAfter)+"</b>\n"+
    "Số dư theo dõi: <b>"+money(balance)+"</b>"+
    pauseLine
  );
}

async function maybeSendSettlement(env,payload,nowSec){
  if(!telegramConfigured(env))return;
  let state=await readTradeState(env,nowSec);
  const settled=await settlePreviousOrder(env,payload,nowSec,state);
  state=settled.state;

  const result=state.unsentResult&&!state.unsentResult.sent?state.unsentResult:null;
  if(!result)return;

  const settings=tradeSettings(env);
  await sendTelegram(env,resultMessagePart(result,settings));
  state.unsentResult=null;
  await writeTradeState(env,state);
}

async function scheduledTick(env){
  const nowSec=Math.floor(Date.now()/1000);
  const minute=Math.floor(nowSec/60);
  let payload;

  try{
    const current=await readHistory(env);
    payload=(!current.rounds?.length||minute%5===0)
      ?await sync(env)
      :await refreshRecent(env);
  }catch(_){
    payload=await readHistory(env);
  }

  await sendReadyOnce(env).catch(()=>{});
  await maybeSendSettlement(env,payload,nowSec).catch(()=>{});
  await schedulePrepareAt60(env,payload).catch(()=>{});
}

export default {
  async fetch(req,env){
    const u=new URL(req.url);

    if(req.method==="OPTIONS"){
      return new Response(null,{headers:{
        ...JSON_HEADERS,
        "access-control-allow-methods":"GET,OPTIONS"
      }});
    }

    if(u.pathname==="/health"){
      return json({
        ok:true,
        service:"Boss 8 Nhom Cloud",
        patternVersion:PATTERN_VERSION,
        patternCount:Object.keys(PATTERNS).length,
        kvConfigured:!!env.BOSS_KV,
        apiKeyConfigured:!!env.PREDICT_API_KEY,
        telegramConfigured:telegramConfigured(env),
        moneySettings:tradeSettings(env),
        time:new Date().toISOString()
      });
    }

    if(u.pathname==="/category"){
      const ts=Number(u.searchParams.get("ts"));
      if(!Number.isFinite(ts)||ts<=0)return json({ok:false,error:"Thiếu hoặc sai ts"},400);
      try{
        const data=await apiCategory(Math.floor(ts),env.PREDICT_API_KEY);
        return data?json(data):json({ok:false,error:"Không tìm thấy vòng"},404);
      }catch(e){
        return json({ok:false,error:String(e.message||e)},502);
      }
    }

    if(u.pathname==="/history"){
      return json(await readHistory(env));
    }

    if(u.pathname==="/trade-state"){
      const state=await readTradeState(env);
      const settings=tradeSettings(env);
      return json({
        ...state,
        settings,
        balance:settings.startBalance+Number(state.pnl||0),
        total:Number(state.wins||0)+Number(state.losses||0)
      });
    }


    if(u.pathname==="/sync"){
      try{return json(await sync(env))}
      catch(e){return json({ok:false,error:String(e.message||e)},500)}
    }

    return json({ok:true,endpoints:["/health","/category?ts=...","/history","/trade-state","/sync"]});
  },

  async scheduled(controller,env,ctx){
    ctx.waitUntil(scheduledTick(env));
  }
};
