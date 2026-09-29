const API="https://api.predict.fun";
const INTERVAL=300;
const JSON_HEADERS={"content-type":"application/json; charset=utf-8","access-control-allow-origin":"*"};

const SIGNAL_STEP=600;       // mốc màu: :00/:10/:20/:30/:40/:50
const ALERT_LEAD=420;         // báo trước 7 phút, ví dụ 16:23 cho phiên 16:30
const PAUSE_SECONDS=1800;     // giờ CHẴN và giờ LẺ cùng thua gần nhất => nghỉ 30 phút
const STRATEGY_VERSION="even-odd-hour-3color-v2";
// Strategy: even/odd local hour + 3-color pattern + win x2.

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
    strategyVersion:STRATEGY_VERSION,
    step:1,
    pnl:0,
    wins:0,
    losses:0,
    balanceBase:null,
    pendingOrders:[],
    completed:[],
    unsentResults:[],
    laneResults:{EVEN:null,ODD:null},
    laneLastResultTarget:{EVEN:0,ODD:0},
    pauseUntil:0,
    pauseReason:null,
    updatedAt:new Date().toISOString()
  };
}

async function readTradeState(env,nowSec=Math.floor(Date.now()/1000)){
  const raw=await env.BOSS_KV.get("telegram:trade_state");
  let state=null;
  try{state=raw?JSON.parse(raw):null}catch(_){}
  if(!state||typeof state!=="object")state=freshTradeState(dayTextFromSeconds(nowSec));

  if(state.strategyVersion!==STRATEGY_VERSION){
    const balanceBase=state.balanceBase===null||state.balanceBase===undefined?null:Number(state.balanceBase);
    state=freshTradeState(dayTextFromSeconds(nowSec));
    state.balanceBase=Number.isFinite(balanceBase)?balanceBase:null;
    await writeTradeState(env,state);
  }

  if(!Number.isFinite(Number(state.step)))state.step=1;
  state.step=Number(state.step)===2?2:1;
  if(!Number.isFinite(Number(state.pnl)))state.pnl=0;
  if(!Number.isFinite(Number(state.wins)))state.wins=0;
  if(!Number.isFinite(Number(state.losses)))state.losses=0;
  if(state.balanceBase!==null&&!Number.isFinite(Number(state.balanceBase)))state.balanceBase=null;
  if(!Array.isArray(state.pendingOrders))state.pendingOrders=[];
  if(!Array.isArray(state.completed))state.completed=[];
  if(!Array.isArray(state.unsentResults))state.unsentResults=[];
  if(!state.laneResults||typeof state.laneResults!=="object")state.laneResults={EVEN:null,ODD:null};
  if(!state.laneLastResultTarget||typeof state.laneLastResultTarget!=="object")state.laneLastResultTarget={EVEN:0,ODD:0};
  if(!Number.isFinite(Number(state.pauseUntil)))state.pauseUntil=0;
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

function tradePlan(settings,state){
  const step=Number(state.step)===2?2:1;
  return step===2
    ?{step:2,capitalStage:0,amount:Number(settings.bet2),label:"Lệnh 2 x2"}
    :{step:1,capitalStage:0,amount:Number(settings.bet1),label:"Lệnh 1"};
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

function localTimeParts(ts){
  const parts=new Intl.DateTimeFormat("en-GB",{
    timeZone:"Asia/Ho_Chi_Minh",
    hour:"2-digit",minute:"2-digit",hourCycle:"h23"
  }).formatToParts(new Date(Number(ts)*1000));
  const get=type=>Number(parts.find(p=>p.type===type)?.value);
  return {hour:get("hour"),minute:get("minute")};
}

function laneForTarget(targetStart){
  const {hour}=localTimeParts(targetStart);
  return hour%2===0?"EVEN":"ODD";
}

function laneText(lane){
  return lane==="EVEN"?"GIỜ CHẴN":"GIỜ LẺ";
}

function isPatternTarget(targetStart){
  const {minute}=localTimeParts(targetStart);
  return minute===30||minute===40||minute===50;
}

function patternMarksForTarget(targetStart){
  const t=Number(targetStart);
  return [t-3*SIGNAL_STEP,t-2*SIGNAL_STEP,t-SIGNAL_STEP];
}

function fourPreviousMarksForTarget(targetStart){
  const t=Number(targetStart);
  return [t-4*SIGNAL_STEP,t-3*SIGNAL_STEP,t-2*SIGNAL_STEP,t-SIGNAL_STEP];
}

function roundStartForMark(markTs){
  return Number(markTs)-INTERVAL;
}

function directionFromThree(colors){
  if(!Array.isArray(colors)||colors.length!==3)return null;
  const [a,b,d]=colors;
  if(!["G","R"].includes(a)||!["G","R"].includes(b)||!["G","R"].includes(d))return null;
  if(a===b&&b===d)return {direction:a,patternType:"SAME"};
  if(a===d&&a!==b)return {direction:b,patternType:"ALTERNATE"};
  return null;
}

async function resolvedColorAt(env,payload,ts){
  const rounds=internalRounds(payload);
  const cached=rounds.find(x=>x.t===Number(ts))?.c||null;
  if(cached)return cached;
  try{
    const raw=await apiCategory(Number(ts),env.PREDICT_API_KEY);
    const normalized=normalizeCategory(raw);
    let color=normalized?.color==="V"?"G":normalized?.color==="X"?"R":null;
    if(!color)color=liveColorFromCategory(raw);
    return color||null;
  }catch(_){
    return null;
  }
}

async function colorAtMark(env,payload,markTs){
  return resolvedColorAt(env,payload,roundStartForMark(markTs));
}

async function patternSignalForTarget(env,payload,targetStart){
  const target=Number(targetStart);
  if(!Number.isFinite(target)||target%INTERVAL!==0||!isPatternTarget(target))return null;
  const lane=laneForTarget(target);
  const marks=fourPreviousMarksForTarget(target);
  const colors=await Promise.all(marks.map(m=>colorAtMark(env,payload,m)));
  const decisionColors=colors.slice(1);
  const decision=directionFromThree(decisionColors);
  return {
    targetStart:target,
    lane,
    laneText:laneText(lane),
    marks,
    colors,
    decisionMarks:marks.slice(1),
    decisionColors,
    direction:decision?.direction||null,
    patternType:decision?.patternType||null
  };
}

function alertTargetForNow(nowSec){
  const base=Math.floor(Number(nowSec)/INTERVAL)*INTERVAL;
  for(let i=1;i<=16;i++){
    const target=base+i*INTERVAL;
    const remain=target-Number(nowSec);
    if(isPatternTarget(target)&&remain<=450&&remain>=390)return target;
  }
  return null;
}

function laneResultText(value){
  return value==="WIN"?"THẮNG":value==="LOSS"?"THUA":"CHƯA CÓ";
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


async function settleDueOrders(env,payload,nowSec,state){
  const currentStart=Math.floor(nowSec/INTERVAL)*INTERVAL;
  const settings=tradeSettings(env);
  const stillPending=[];
  const results=[];

  for(const pending of (state.pendingOrders||[]).slice().sort((a,b)=>Number(a.targetStart)-Number(b.targetStart))){
    if(Number(pending.targetStart)>=currentStart){
      stillPending.push(pending);
      continue;
    }

    const rounds=internalRounds(payload);
    let actual=rounds.find(x=>x.t===Number(pending.targetStart))?.c||null;
    if(!actual){
      try{
        const raw=await apiCategory(Number(pending.targetStart),env.PREDICT_API_KEY);
        const normalized=normalizeCategory(raw);
        actual=normalized?.color==="V"?"G":normalized?.color==="X"?"R":null;
        if(!actual)actual=liveColorFromCategory(raw);
        if(actual){
          const existing=await readHistory(env);
          const synthetic={
            slug:"btc-updown-5m-"+Number(pending.targetStart),
            ts:Number(pending.targetStart),
            color:actual==="G"?"V":"X",
            outcome:actual==="G"?"UP":"DOWN"
          };
          await writeHistory(env,[...(existing.rounds||[]),synthetic],{
            rawMatched:Math.max(Number(existing.rawMatched||0),Number(existing.count||0)+1),
            skippedWithoutOutcome:Number(existing.skippedWithoutOutcome||0)
          }).catch(()=>{});
        }
      }catch(_){}
    }

    if(!actual){
      stillPending.push(pending);
      continue;
    }

    const win=String(pending.direction)===actual;
    const amount=Number(pending.amount)||0;
    const payout=Number(pending.payoutRate);
    const effectivePayout=Number.isFinite(payout)?payout:settings.payout;
    const delta=win?amount*effectivePayout:-amount;
    state.pnl=Number(state.pnl||0)+delta;
    if(win)state.wins=Number(state.wins||0)+1;
    else state.losses=Number(state.losses||0)+1;

    const lane=pending.lane==="ODD"?"ODD":"EVEN";
    state.laneResults[lane]=win?"WIN":"LOSS";
    state.laneLastResultTarget[lane]=Number(pending.targetStart);

    const nextStep=nextStepAfter(pending.step,win);
    state.step=nextStep;

    const bothLanesLost=state.laneResults.EVEN==="LOSS"&&state.laneResults.ODD==="LOSS";
    let pauseTriggered=false;
    if(bothLanesLost){
      state.pauseUntil=Math.max(
        Number(state.pauseUntil||0),
        Number(pending.targetStart)+INTERVAL+PAUSE_SECONDS
      );
      state.pauseReason="CHẴN và LẺ đều có kết quả gần nhất là THUA";
      pauseTriggered=true;
    }

    const balanceBase=state.balanceBase===null?settings.startBalance:Number(state.balanceBase);
    const result={
      id:pending.id,
      targetStart:Number(pending.targetStart),
      lane,
      laneText:laneText(lane),
      marks:pending.marks||[],
      colors:pending.colors||[],
      decisionColors:pending.decisionColors||[],
      direction:pending.direction,
      actual,
      amount,
      win,
      delta,
      pnlAfter:Number(state.pnl||0),
      balanceAfter:balanceBase+Number(state.pnl||0),
      winsAfter:Number(state.wins||0),
      lossesAfter:Number(state.losses||0),
      step:Number(pending.step||1),
      nextStep,
      laneResultsAfter:{...state.laneResults},
      pauseTriggered,
      pauseUntil:Number(state.pauseUntil||0),
      settledAt:new Date().toISOString(),
      sent:false
    };

    state.completed.push({...result});
    state.completed=state.completed.slice(-300);
    state.unsentResults.push({...result});
    state.unsentResults=state.unsentResults.slice(-20);
    results.push(result);

    if(pauseTriggered){
      state.step=1;
      state.laneResults={EVEN:null,ODD:null};
      state.laneLastResultTarget={EVEN:0,ODD:0};
    }
  }

  state.pendingOrders=stillPending;
  await writeTradeState(env,state);
  return {state,results};
}

async function maybePrepare(env,payload,nowSec){
  if(!telegramConfigured(env))return;

  let state=await readTradeState(env,nowSec);
  if(Number(state.pauseUntil||0)>Number(nowSec))return;
  if(Number(state.pauseUntil||0)>0&&Number(state.pauseUntil)<=Number(nowSec)){
    state.pauseUntil=0;
    state.pauseReason=null;
    state.step=1;
    state.laneResults={EVEN:null,ODD:null};
    state.laneLastResultTarget={EVEN:0,ODD:0};
    await writeTradeState(env,state);
  }

  const targetStart=alertTargetForNow(nowSec);
  if(!targetStart)return;
  if((state.pendingOrders||[]).length)return;
  if((state.pendingOrders||[]).some(p=>Number(p.targetStart)===targetStart))return;

  const signal=await patternSignalForTarget(env,payload,targetStart);
  if(!signal?.direction)return;

  const settings=tradeSettings(env);
  const plan=tradePlan(settings,state);
  const previousEven=state.laneResults?.EVEN||null;
  const previousOdd=state.laneResults?.ODD||null;

  const pending={
    id:String(targetStart)+"-"+signal.lane,
    day:dayTextFromSeconds(targetStart),
    targetStart,
    lane:signal.lane,
    laneText:signal.laneText,
    marks:signal.marks,
    colors:signal.colors,
    decisionMarks:signal.decisionMarks,
    decisionColors:signal.decisionColors,
    patternType:signal.patternType,
    direction:signal.direction,
    strategy:"EVEN_ODD_3COLOR",
    step:plan.step,
    amount:plan.amount,
    planLabel:plan.label,
    payoutRate:settings.payout,
    previousEven,
    previousOdd,
    entrySent:false,
    createdAt:new Date().toISOString()
  };
  state.pendingOrders.push(pending);
  state.pendingOrders=state.pendingOrders.slice(-12);
  await writeTradeState(env,state);

  const icon=color=>color==="G"?"🟢":color==="R"?"🔴":"⚪";
  const fourLine=pending.marks.map((m,i)=>timeText(m)+" "+icon(pending.colors[i])).join(" • ");
  const threeLine=pending.decisionColors.map(icon).join(" ");
  const buy=pending.direction==="G"?"🟢 <b>MUA XANH</b>":"🔴 <b>MUA ĐỎ</b>";
  const rule=pending.patternType==="SAME"?"3 màu giống nhau → theo cùng màu":"mẫu xen kẽ A-B-A → tiếp tục màu B";

  await sendTelegram(env,
    "🚨 <b>BÁO LỆNH KHUNG "+pending.laneText+"</b>\n"+
    "4 màu trước: "+fourLine+"\n"+
    "3 màu quyết định: <b>"+threeLine+"</b>\n"+
    "Quy tắc: <b>"+rule+"</b>\n"+
    "➡️ "+buy+"\n"+
    "Phiên mua: <b>"+frameText(pending.targetStart)+"</b>\n"+
    "<b>"+pending.planLabel+" • "+amountText(pending.amount)+"</b>\n"+
    "Lệnh gần nhất CHẴN: <b>"+laneResultText(previousEven)+"</b> • LẺ: <b>"+laneResultText(previousOdd)+"</b>"
  );

  pending.entrySent=true;
  pending.entrySentAt=new Date().toISOString();
  await writeTradeState(env,state);
  await env.BOSS_KV.put("telegram:last_prepare",String(targetStart));
}

async function schedulePatternAlert(env,payload){
  const nowSec=Math.floor(Date.now()/1000);
  await maybePrepare(env,payload,nowSec);
}

function resultMessagePart(result,settings){
  if(!result)return "";
  const title=result.win?"✅ <b>THẮNG LỆNH "+result.laneText+"</b>":"❌ <b>THUA LỆNH "+result.laneText+"</b>";
  const actualText=result.actual==="G"?"🟢 XANH":"🔴 ĐỎ";
  const entered=result.direction==="G"?"🟢 XANH":"🔴 ĐỎ";
  const balance=Number.isFinite(Number(result.balanceAfter))
    ?Number(result.balanceAfter)
    :settings.startBalance+Number(result.pnlAfter||0);
  const pauseLine=result.pauseTriggered
    ?"\n⏸ <b>CHẴN + LẺ ĐỀU THUA → DỪNG 30 PHÚT</b> • xét lại sau "+timeText(result.pauseUntil)
    :"";
  const laneEven=result.laneResultsAfter?.EVEN||null;
  const laneOdd=result.laneResultsAfter?.ODD||null;

  return (
    title+"\n"+
    "Phiên vừa xong: <b>"+frameText(result.targetStart)+"</b>\n"+
    "Đã mua: "+entered+" • Kết quả: "+actualText+"\n"+
    "Kết quả gần nhất CHẴN: <b>"+laneResultText(laneEven)+"</b> • LẺ: <b>"+laneResultText(laneOdd)+"</b>\n"+
    "Đã dùng: <b>Lệnh "+Number(result.step||1)+"</b> • lệnh kế tiếp: <b>Lệnh "+Number(result.nextStep||1)+(Number(result.nextStep||1)===2?" x2":"")+"</b>\n"+
    "Lãi/lỗ lệnh này: <b>"+money(result.delta)+"</b>\n"+
    "Tổng lãi/lỗ sau reset: <b>"+money(result.pnlAfter)+"</b>\n"+
    "Số dư theo dõi: <b>"+money(balance)+"</b>"+
    pauseLine
  );
}

async function maybeSendSettlement(env,payload,nowSec){
  if(!telegramConfigured(env))return;
  let state=await readTradeState(env,nowSec);
  const settled=await settleDueOrders(env,payload,nowSec,state);
  state=settled.state;

  const queue=Array.isArray(state.unsentResults)?state.unsentResults.slice():[];
  if(!queue.length)return;

  const settings=tradeSettings(env);
  const sentIds=new Set();
  for(const result of queue){
    await sendTelegram(env,resultMessagePart(result,settings));
    sentIds.add(result.id);
  }
  state.unsentResults=(state.unsentResults||[]).filter(r=>!sentIds.has(r.id));
  await writeTradeState(env,state);
}

async function scheduledTick(env){
  const nowSec=Math.floor(Date.now()/1000);
  const minute=Math.floor(nowSec/60);
  let payload=await readHistory(env);

  await sendReadyOnce(env).catch(()=>{});

  // Settle first. This prevents a slow full-history sync at the 5-minute
  // boundary from delaying or skipping the win/loss Telegram message.
  await maybeSendSettlement(env,payload,nowSec).catch(()=>{});

  try{
    payload=(!payload.rounds?.length||minute%5===0)
      ?await sync(env)
      :await refreshRecent(env);
  }catch(_){
    payload=await readHistory(env);
  }

  await schedulePatternAlert(env,payload).catch(()=>{});
}

export default {
  async fetch(req,env){
    const u=new URL(req.url);

    if(req.method==="OPTIONS"){
      return new Response(null,{headers:{
        ...JSON_HEADERS,
        "access-control-allow-methods":"GET,POST,OPTIONS",
        "access-control-allow-headers":"content-type"
      }});
    }

    if(u.pathname==="/health"){
      return json({
        ok:true,
        service:"Boss Moc Chan Cloud",
        strategyVersion:STRATEGY_VERSION,
        signalStepMinutes:SIGNAL_STEP/60,
        evenOddByLocalHour:true,
        evenHours:[0,2,4,6,8,10,12,14,16,18,20,22],
        oddHours:[1,3,5,7,9,11,13,15,17,19,21,23],
        colorMarks:["00","10","20","30","40","50"],
        entryMinutes:["30","40","50"],
        alertLeadMinutes:ALERT_LEAD/60,
        patternRules:["AAA->A","ABA->B"],
        pauseAfterBothLaneLossesMinutes:PAUSE_SECONDS/60,
        winDoubleRule:true,
        moneyRule:"Lệnh 1 thắng -> Lệnh 2 x2; sau Lệnh 2 hoặc Lệnh 1 thua -> về Lệnh 1",
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
        balance:(state.balanceBase===null?settings.startBalance:Number(state.balanceBase))+Number(state.pnl||0),
        total:Number(state.wins||0)+Number(state.losses||0)
      });
    }


    if(u.pathname==="/pattern-signal"){
      const nowSec=Math.floor(Date.now()/1000);
      const targetParam=Number(u.searchParams.get("target"));
      let targetStart=Number.isFinite(targetParam)&&targetParam>0
        ?Math.floor(targetParam/INTERVAL)*INTERVAL
        :null;
      if(!targetStart){
        const base=Math.floor(nowSec/INTERVAL)*INTERVAL;
        for(let i=1;i<=24;i++){
          const candidate=base+i*INTERVAL;
          if(isPatternTarget(candidate)){targetStart=candidate;break}
        }
      }
      const payload=await readHistory(env);
      const signal=await patternSignalForTarget(env,payload,targetStart);
      const state=await readTradeState(env,nowSec);
      return json({
        ok:true,
        ...signal,
        paused:Number(state.pauseUntil||0)>nowSec,
        pauseUntil:Number(state.pauseUntil||0),
        laneResults:state.laneResults||{EVEN:null,ODD:null},
        step:Number(state.step||1),
        amount:tradePlan(tradeSettings(env),state).amount
      });
    }


    if(u.pathname==="/trade-reset"){
      if(req.method!=="POST")return json({ok:false,error:"Chỉ chấp nhận POST"},405);
      let body={};
      try{body=await req.json()}catch(_){}
      if(body?.confirm!=="RESET")return json({ok:false,error:"Thiếu xác nhận RESET"},400);

      const nowSec=Math.floor(Date.now()/1000);
      const state=freshTradeState(dayTextFromSeconds(nowSec));
      state.balanceBase=0;
      await writeTradeState(env,state);

      return json({
        ok:true,
        message:"Đã reset lệnh thực tế, thắng/thua, lãi/lỗ, trạng thái CHẴN/LẺ và thời gian nghỉ về 0.",
        state
      });
    }

    if(u.pathname==="/sync"){
      try{return json(await sync(env))}
      catch(e){return json({ok:false,error:String(e.message||e)},500)}
    }

    return json({ok:true,endpoints:["/health","/category?ts=...","/history","/trade-state","/pattern-signal?target=...","/trade-reset","/sync"]});
  },

  async scheduled(controller,env,ctx){
    ctx.waitUntil(scheduledTick(env));
  }
};
