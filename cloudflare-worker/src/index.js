const API="https://api.predict.fun";
const INTERVAL=300;
const JSON_HEADERS={"content-type":"application/json; charset=utf-8","access-control-allow-origin":"*"};

const SOURCE_STEP=600;       // 00,10,20,30,40,50
const ENTRY_DELAY=600;       // order candle starts 10 minutes after source and closes at +15
const STRATEGY_VERSION="even-10m-2loss-waitwin-v4";

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
    lossStreak:0,
    lossCapitalMode:false,
    autoStrategyMode:true,
    reverseColorMode:false,
    lastResultWin:null,
    reverseAfterSecondLossActive:false,
    waitForWin:false,
    waitAfterTarget:0,
    waitLastCheckedTarget:0,
    waitWinTarget:0,
    balanceBase:null,
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

  // A strategy change must not carry an old pending order, old streak or old PnL
  // into the new method.
  if(state.strategyVersion!==STRATEGY_VERSION){
    const balanceBase=state.balanceBase===null||state.balanceBase===undefined?null:Number(state.balanceBase);
    state=freshTradeState(dayTextFromSeconds(nowSec));
    state.balanceBase=Number.isFinite(balanceBase)?balanceBase:null;
    await writeTradeState(env,state);
  }

  if(!Number.isFinite(Number(state.step)))state.step=1;
  if(!Number.isFinite(Number(state.pnl)))state.pnl=0;
  if(!Number.isFinite(Number(state.wins)))state.wins=0;
  if(!Number.isFinite(Number(state.losses)))state.losses=0;
  if(!Number.isFinite(Number(state.lossStreak)))state.lossStreak=0;
  if(typeof state.lossCapitalMode!=="boolean")state.lossCapitalMode=false;
  if(typeof state.autoStrategyMode!=="boolean")state.autoStrategyMode=true;
  if(typeof state.reverseColorMode!=="boolean")state.reverseColorMode=false;
  if(typeof state.lastResultWin!=="boolean")state.lastResultWin=null;
  if(typeof state.reverseAfterSecondLossActive!=="boolean")state.reverseAfterSecondLossActive=false;
  if(typeof state.waitForWin!=="boolean")state.waitForWin=false;
  if(!Number.isFinite(Number(state.waitAfterTarget)))state.waitAfterTarget=0;
  if(!Number.isFinite(Number(state.waitLastCheckedTarget)))state.waitLastCheckedTarget=0;
  if(!Number.isFinite(Number(state.waitWinTarget)))state.waitWinTarget=0;
  if(state.balanceBase!==null&&!Number.isFinite(Number(state.balanceBase)))state.balanceBase=null;
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

function tradePlan(settings,state){
  const step=Number(state.step)===2?2:1;
  const lossStreak=Math.max(0,Number(state.lossStreak||0));
  const mode=!!state.lossCapitalMode;

  if(mode&&lossStreak>0){
    const capitalStage=Math.min(4,lossStreak+1);
    const multiplier=capitalStage===2?1:capitalStage===3?2:4;
    return {
      step,
      capitalStage,
      amount:Number(settings.bet1)*multiplier,
      label:"Lệnh vốn "+capitalStage+"/4"
    };
  }

  if(step===2){
    return {step:2,capitalStage:0,amount:amountForStep(settings,2),label:"Lệnh thắng x2"};
  }

  return {
    step:1,
    capitalStage:mode?1:0,
    amount:amountForStep(settings,1),
    label:mode?"Lệnh vốn 1/4":"Lệnh 1"
  };
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

function isSourceStart(ts){
  return Number.isFinite(Number(ts))&&Math.floor(Number(ts))%SOURCE_STEP===0;
}

function sourceStartForTarget(targetStart){
  const source=Number(targetStart)-ENTRY_DELAY;
  return isSourceStart(source)?source:null;
}

function tradeDirectionFromSource(sourceColor,reverseColorMode=false){
  if(sourceColor!=="G"&&sourceColor!=="R")return null;
  if(!reverseColorMode)return sourceColor;
  return sourceColor==="G"?"R":"G";
}


const BINANCE_KLINES_URL="https://api.binance.com/api/v3/klines";
const BINANCE_KLINES_FALLBACK_URL="https://data-api.binance.vision/api/v3/klines";
const BINANCE_AUTO_SYMBOL="BTCUSDT";
const BINANCE_AUTO_INTERVAL="5m";
const BINANCE_AUTO_LIMIT=288;
const BINANCE_AUTO_PATTERN_LEN=3;
const BINANCE_AUTO_CACHE_SECONDS=30;

function binanceColor(open,close){
  const o=Number(open),c=Number(close);
  if(!Number.isFinite(o)||!Number.isFinite(c))return "DOJI";
  return c>o?"G":c<o?"R":"DOJI";
}

async function fetchBinanceKlines(symbol=BINANCE_AUTO_SYMBOL,interval=BINANCE_AUTO_INTERVAL,limit=BINANCE_AUTO_LIMIT){
  const qs="?symbol="+encodeURIComponent(String(symbol).toUpperCase())+
    "&interval="+encodeURIComponent(interval)+
    "&limit="+encodeURIComponent(String(limit));
  let lastError=null;
  for(const base of [BINANCE_KLINES_URL,BINANCE_KLINES_FALLBACK_URL]){
    try{
      const r=await fetch(base+qs,{headers:{"accept":"application/json"}});
      if(!r.ok){
        lastError=new Error("Binance API "+r.status+": "+(await r.text()).slice(0,180));
        continue;
      }
      const raw=await r.json();
      if(!Array.isArray(raw))throw new Error("Binance API trả dữ liệu không hợp lệ");
      return raw.map(k=>({
        openTime:Number(k?.[0]),
        open:Number(k?.[1]),
        high:Number(k?.[2]),
        low:Number(k?.[3]),
        close:Number(k?.[4]),
        volume:Number(k?.[5]),
        color:binanceColor(k?.[1],k?.[4])
      })).filter(x=>Number.isFinite(x.openTime));
    }catch(e){
      lastError=e;
    }
  }
  throw lastError||new Error("Không lấy được dữ liệu Binance");
}

function streakTransitionTable(colors){
  const table=new Map();
  let i=0;
  const n=colors.length;
  while(i<n-1){
    const color=colors[i];
    if(color==="DOJI"){i++;continue;}
    let streak=1;
    let j=i+1;
    while(j<n&&colors[j]===color){streak++;j++;}
    if(j<n){
      const next=colors[j];
      const key=color+":"+Math.min(streak,6);
      if(next==="G"||next==="R"){
        const row=table.get(key)||{G:0,R:0,total:0};
        row[next]++;
        row.total++;
        table.set(key,row);
      }
    }
    i=j;
  }
  return table;
}

function currentStreak(colors){
  if(!colors.length)return {color:null,streak:0};
  const lastColor=colors[colors.length-1];
  let streak=1;
  for(let i=colors.length-2;i>=0;i--){
    if(colors[i]===lastColor)streak++;
    else break;
  }
  return {color:lastColor,streak};
}

function patternMatchPredict(colors,patternLen=BINANCE_AUTO_PATTERN_LEN){
  if(colors.length<=patternLen)return null;
  const currentPattern=colors.slice(-patternLen);
  const outcomes={G:0,R:0};
  for(let i=0;i<colors.length-patternLen-1;i++){
    let same=true;
    for(let k=0;k<patternLen;k++){
      if(colors[i+k]!==currentPattern[k]){same=false;break;}
    }
    if(!same)continue;
    const next=colors[i+patternLen];
    if(next==="G"||next==="R")outcomes[next]++;
  }
  return {pattern:currentPattern,outcomes,total:outcomes.G+outcomes.R};
}

function backtestStrategies(colors){
  const valid=colors.filter(c=>c!=="DOJI");
  if(valid.length<2)return null;
  const greenCount=valid.filter(c=>c==="G").length;
  const redCount=valid.length-greenCount;
  const majorityColor=greenCount>=redCount?"G":"R";
  const results={
    trend:0,oppositeTrend:0,dayMajority:0,total:0,
    majorityColor,lastValidColor:valid[valid.length-1]
  };
  for(let i=0;i<valid.length-1;i++){
    const prev=valid[i];
    const actualNext=valid[i+1];
    const opposite=oppositeColor(prev);
    results.total++;
    if(prev===actualNext)results.trend++;
    if(opposite===actualNext)results.oppositeTrend++;
    if(majorityColor===actualNext)results.dayMajority++;
  }
  return results;
}

function colorName(color){
  return color==="G"?"XANH":color==="R"?"ĐỎ":"DOJI";
}

function buildBinanceAutoCandidates(colors){
  const candidates=[];
  const streakNow=currentStreak(colors);
  const table=streakTransitionTable(colors);

  if((streakNow.color==="G"||streakNow.color==="R")&&streakNow.streak>0){
    const key=streakNow.color+":"+Math.min(streakNow.streak,6);
    const row=table.get(key);
    if(row&&row.total>=5&&row.G!==row.R){
      const direction=row.G>row.R?"G":"R";
      const wins=Math.max(row.G,row.R);
      candidates.push({
        id:"streak",
        name:"Streak "+streakNow.streak+"x "+colorName(streakNow.color),
        direction,wins,losses:row.total-wins,total:row.total,rate:wins/row.total,
        detail:{currentColor:streakNow.color,streak:streakNow.streak,nextGreen:row.G,nextRed:row.R}
      });
    }
  }

  const pm=patternMatchPredict(colors,BINANCE_AUTO_PATTERN_LEN);
  if(pm&&pm.total>0&&pm.outcomes.G!==pm.outcomes.R){
    const direction=pm.outcomes.G>pm.outcomes.R?"G":"R";
    const wins=Math.max(pm.outcomes.G,pm.outcomes.R);
    candidates.push({
      id:"pattern3",
      name:"Mẫu 3 nến "+pm.pattern.map(colorName).join("-"),
      direction,wins,losses:pm.total-wins,total:pm.total,rate:wins/pm.total,
      detail:{pattern:pm.pattern,nextGreen:pm.outcomes.G,nextRed:pm.outcomes.R}
    });
  }

  const bt=backtestStrategies(colors);
  if(bt&&bt.total>0){
    const backtests=[
      {id:"trend",name:"Theo xu hướng",direction:bt.lastValidColor,wins:bt.trend},
      {id:"opposite_trend",name:"Ngược xu hướng",direction:oppositeColor(bt.lastValidColor),wins:bt.oppositeTrend},
      {id:"day_majority",name:"Theo màu đa số 24h",direction:bt.majorityColor,wins:bt.dayMajority}
    ];
    for(const x of backtests){
      candidates.push({
        ...x,
        losses:bt.total-x.wins,total:bt.total,rate:x.wins/bt.total,
        detail:{majorityColor:bt.majorityColor,lastValidColor:bt.lastValidColor}
      });
    }
  }
  return {candidates,streakNow,pattern:pm,backtest:bt};
}

function chooseBinanceAutoCandidate(candidates){
  const ranked=(candidates||[]).filter(x=>
    (x.direction==="G"||x.direction==="R")&&
    Number.isFinite(Number(x.rate))&&
    Number(x.total)>0
  ).slice();
  ranked.sort((a,b)=>
    Number(b.rate)-Number(a.rate) ||
    Number(b.total)-Number(a.total) ||
    Number(b.wins)-Number(a.wins)
  );
  return {best:ranked[0]||null,ranked};
}

async function binanceAutoStrategyAnalysis(){
  const candles=await fetchBinanceKlines();
  const colors=candles.map(c=>c.color);
  const greenCount=colors.filter(c=>c==="G").length;
  const redCount=colors.filter(c=>c==="R").length;
  const dojiCount=colors.length-greenCount-redCount;
  const built=buildBinanceAutoCandidates(colors);
  const chosen=chooseBinanceAutoCandidate(built.candidates);
  const best=chosen.best;
  const fallbackColor=colors.slice().reverse().find(c=>c==="G"||c==="R")||null;

  return {
    engine:"BINANCE_24H_STATS_V1",
    symbol:BINANCE_AUTO_SYMBOL,
    interval:BINANCE_AUTO_INTERVAL,
    candleCount:colors.length,
    generatedAt:Date.now(),
    id:best?.id||"trend",
    name:best?.name||"Theo xu hướng",
    direction:best?.direction||fallbackColor,
    successRate:best?best.rate:null,
    wins:best?best.wins:0,
    losses:best?best.losses:0,
    sampleCount:best?best.total:0,
    validateRate:best?best.rate:null,
    validateWins:best?best.wins:0,
    validateLosses:best?best.losses:0,
    overview:{
      total:colors.length,green:greenCount,red:redCount,doji:dojiCount,
      lastColor:colors[colors.length-1]||null,
      streakColor:built.streakNow.color,streak:built.streakNow.streak
    },
    pattern:built.pattern,
    backtest:built.backtest,
    candidates:chosen.ranked.slice(0,5)
  };
}

async function cachedBinanceAutoStrategy(env,force=false){
  const key="auto:binance24h:v1";
  const now=Date.now();
  if(!force){
    try{
      const raw=await env.BOSS_KV.get(key);
      if(raw){
        const cached=JSON.parse(raw);
        if(cached&&now-Number(cached.generatedAt||0)<BINANCE_AUTO_CACHE_SECONDS*1000)return cached;
      }
    }catch(_){}
  }
  const analysis=await binanceAutoStrategyAnalysis();
  try{await env.BOSS_KV.put(key,JSON.stringify(analysis),{expirationTtl:120})}catch(_){}
  return analysis;
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

async function shadowSignalAt(env,payload,targetStart,reverseColorMode=false){
  const sourceStart=sourceStartForTarget(targetStart);
  if(sourceStart===null)return null;
  const [sourceColor,actual]=await Promise.all([
    resolvedColorAt(env,payload,sourceStart),
    resolvedColorAt(env,payload,targetStart)
  ]);
  const direction=tradeDirectionFromSource(sourceColor,reverseColorMode);
  if(!sourceColor||!direction||!actual)return null;
  return {
    sourceStart,
    targetStart:Number(targetStart),
    sourceColor,
    direction,
    actual,
    reverseColorMode:!!reverseColorMode,
    win:direction===actual
  };
}

async function advanceWaitForWin(env,payload,state,currentTarget){
  if(!state.waitForWin)return {state,unlocked:false,winTarget:0};

  let cursor=Number(state.waitLastCheckedTarget||state.waitAfterTarget||0);
  if(!cursor)return {state,unlocked:false,winTarget:0};

  for(let target=cursor+SOURCE_STEP;target<Number(currentTarget);target+=SOURCE_STEP){
    // Khi chuỗi đã chạm giới hạn thua, lossStreak được reset về 0.
    // Nhịp giả lập chờ thắng vì thế luôn kiểm tra theo màu nến gốc,
    // đúng với cách một chuỗi mới sẽ bắt đầu ở lệnh 1.
    const reverseThisOrder=
      !!state.reverseColorMode &&
      !!state.reverseAfterSecondLossActive &&
      state.lastResultWin===false;
    const shadow=await shadowSignalAt(env,payload,target,reverseThisOrder);
    if(!shadow)break;

    state.waitLastCheckedTarget=target;
    if(shadow.win){
      state.waitForWin=false;
      state.waitWinTarget=target;
      await writeTradeState(env,state);
      return {state,unlocked:true,winTarget:target};
    }
  }

  await writeTradeState(env,state);
  return {state,unlocked:false,winTarget:0};
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


async function settlePreviousOrder(env,payload,nowSec,state){
  const pending=state.pending;
  if(!pending)return {state,result:null};

  const currentStart=Math.floor(nowSec/INTERVAL)*INTERVAL;
  if(Number(pending.targetStart)>=currentStart)return {state,result:null};

  const rounds=internalRounds(payload);
  let actual=rounds.find(x=>x.t===Number(pending.targetStart))?.c||null;

  // Do not depend only on the cached history. The just-finished Predict round
  // can resolve after the history snapshot was written, so fetch that exact
  // target round directly before giving up.
  if(!actual){
    try{
      const raw=await apiCategory(Number(pending.targetStart),env.PREDICT_API_KEY);
      const normalized=normalizeCategory(raw);
      actual=normalized?.color==="V"?"G":normalized?.color==="X"?"R":null;

      // Once the target frame has closed, price data is a safe fallback while
      // Predict's explicit resolution is still propagating.
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
    state.lastSettlementCheckAt=new Date().toISOString();
    state.lastSettlementTarget=Number(pending.targetStart);
    await writeTradeState(env,state).catch(()=>{});
    return {state,result:null};
  }

  const settings=tradeSettings(env);
  const win=String(pending.direction)===actual;
  const amount=Number(pending.amount)||0;
  const payout=Number(pending.payoutRate);
  const effectivePayout=Number.isFinite(payout)?payout:settings.payout;
  const delta=win?amount*effectivePayout:-amount;

  state.pnl=Number(state.pnl||0)+delta;
  if(win)state.wins=Number(state.wins||0)+1;
  else state.losses=Number(state.losses||0)+1;

  // Chỉ kích hoạt quy tắc đảo màu SAU KHI lệnh vốn 2/4 bị THUA.
  // Trước thời điểm đó, lệnh 1 và lệnh 2 luôn đi đúng công thức màu đã cài.
  // Khi đã kích hoạt: lệnh trước thua => lệnh sau đảo màu; gặp một lệnh thắng
  // thì tắt trạng thái đặc biệt và quay về công thức màu gốc.
  state.lastResultWin=win;

  if(win){
    state.lossStreak=0;
    state.reverseAfterSecondLossActive=false;
  }else{
    if(
      state.lossCapitalMode &&
      Number(pending.capitalStage||0)===2
    ){
      state.reverseAfterSecondLossActive=true;
    }
    state.lossStreak=Number(state.lossStreak||0)+1;
    if(state.lossCapitalMode&&state.lossStreak>=4)state.lossStreak=0;
  }

  // Không còn chờ nhịp giả lập thắng. Tool tiếp tục chạy đúng các mốc giờ.
  state.waitForWin=false;
  state.waitAfterTarget=0;
  state.waitLastCheckedTarget=0;
  state.waitWinTarget=0;
  const waitTriggered=false;

  const nextStep=nextStepAfter(pending.step,win);
  state.step=nextStep;
  const balanceBase=state.balanceBase===null?settings.startBalance:Number(state.balanceBase);

  const result={
    id:pending.id,
    targetStart:Number(pending.targetStart),
    sourceStart:Number(pending.sourceStart),
    sourceColor:pending.sourceColor,
    direction:pending.direction,
    actual,
    step:Number(pending.step),
    amount,
    win,
    delta,
    pnlAfter:Number(state.pnl||0),
    balanceAfter:balanceBase+Number(state.pnl||0),
    winsAfter:Number(state.wins||0),
    lossesAfter:Number(state.losses||0),
    nextStep,
    capitalStage:Number(pending.capitalStage||0),
    lossCapitalMode:!!pending.lossCapitalMode,
    reverseColorMode:!!pending.reverseColorMode,
    lossStreakAfter:Number(state.lossStreak||0),
    waitTriggered,
    lastResultWinAfter:state.lastResultWin,
    waitForWinAfter:false,
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

  // The next 5-minute frame is the possible order frame.
  const targetStart=liveStart+INTERVAL;
  const sourceStart=sourceStartForTarget(targetStart);
  if(sourceStart===null)return;

  // Only send when the real order frame is about 1 minute away.
  // Example: source 17:00 -> order frame 17:10-17:15 -> alert around 17:09.
  const secondsToTarget=targetStart-nowSec;
  if(secondsToTarget>70||secondsToTarget<=45)return;

  let state=await readTradeState(env,nowSec);
  const currentDay=dayTextFromSeconds(targetStart);

  if(state.day!==currentDay&&!state.pending){
    const carriedLossStreak=Number(state.lossStreak||0);
    const carriedLossCapitalMode=!!state.lossCapitalMode;
    const carriedAutoStrategyMode=!!state.autoStrategyMode;
    const carriedReverseColorMode=!!state.reverseColorMode;
    const carriedLastResultWin=typeof state.lastResultWin==="boolean"?state.lastResultWin:null;
    const carriedReverseAfterSecondLossActive=!!state.reverseAfterSecondLossActive;
    const carriedWaitForWin=false;
    const carriedWaitAfterTarget=Number(state.waitAfterTarget||0);
    const carriedWaitLastCheckedTarget=Number(state.waitLastCheckedTarget||0);
    const carriedWaitWinTarget=Number(state.waitWinTarget||0);
    state=freshTradeState(currentDay);
    state.lossStreak=carriedLossStreak;
    state.lossCapitalMode=carriedLossCapitalMode;
    state.autoStrategyMode=carriedAutoStrategyMode;
    state.reverseColorMode=carriedReverseColorMode;
    state.lastResultWin=carriedLastResultWin;
    state.reverseAfterSecondLossActive=carriedReverseAfterSecondLossActive;
    state.waitForWin=false;
    state.waitAfterTarget=carriedWaitAfterTarget;
    state.waitLastCheckedTarget=carriedWaitLastCheckedTarget;
    state.waitWinTarget=carriedWaitWinTarget;
  }

  // Không tạo lệnh kế tiếp khi lệnh trước vẫn chưa có kết quả.
  // Khi pending đã được settle và xóa, tool mới xét khung giờ hợp lệ tiếp theo.
  const resumedFromWaitTarget=0;
  if(state.pending&&Number(state.pending.targetStart)!==targetStart)return;

  const sourceColor=await resolvedColorAt(env,payload,sourceStart);

  // AUTO BINANCE 24H: streak, mẫu 3 nến, xu hướng, ngược xu hướng và màu đa số.
  const auto=state.autoStrategyMode
    ?await cachedBinanceAutoStrategy(env,true)
    :{id:"source",name:"Theo màu mốc",direction:sourceColor,successRate:null,wins:0,losses:0,sampleCount:0};
  const direction=auto.direction||sourceColor;
  const reverseThisOrder=!!sourceColor&&direction!==sourceColor;
  if(!direction)return;

  const settings=tradeSettings(env);
  if(!state.pending){
    const plan=tradePlan(settings,state);
    state.pending={
      id:String(targetStart)+"-"+String(sourceStart),
      day:currentDay,
      sourceStart,
      sourceColor,
      targetStart,
      direction,
      strategy:"EVEN_10M_ENTRY10_CLOSE15",
      reverseColorMode:reverseThisOrder,
      autoStrategyMode:!!state.autoStrategyMode,
      autoStrategyId:auto.id,
      autoStrategyName:auto.name,
      autoStrategyEngine:auto.engine||null,
      autoSuccessRate:auto.successRate===null||auto.successRate===undefined
        ?null
        :(Number.isFinite(Number(auto.successRate))?Number(auto.successRate):null),
      autoWins:Number(auto.wins||0),
      autoLosses:Number(auto.losses||0),
      autoSampleCount:Number(auto.sampleCount||0),
      autoValidateRate:auto.successRate===null||auto.successRate===undefined
        ?null
        :(Number.isFinite(Number(auto.successRate))?Number(auto.successRate):null),
      autoValidateWins:Number(auto.wins||0),
      autoValidateLosses:Number(auto.losses||0),
      step:plan.step,
      capitalStage:plan.capitalStage,
      planLabel:plan.label,
      lossCapitalMode:!!state.lossCapitalMode,
      amount:plan.amount,
      payoutRate:settings.payout,
      resumeFromWaitTarget:resumedFromWaitTarget||0,
      entrySent:false,
      createdAt:new Date().toISOString()
    };
    state.waitWinTarget=0;
    await writeTradeState(env,state);
  }

  const pending=state.pending;
  if(pending.entrySent)return;

  const buy=pending.direction==="G"?"🟢 <b>MUA XANH NGAY</b>":"🔴 <b>MUA ĐỎ NGAY</b>";
  const sourceText=pending.sourceColor==="G"?"🟢 XANH":"🔴 ĐỎ";
  const autoRate=Number(pending.autoSuccessRate??pending.autoValidateRate);
  const autoWins=Number((pending.autoWins??pending.autoValidateWins)??0);
  const autoLosses=Number((pending.autoLosses??pending.autoValidateLosses)??0);
  const autoLine=pending.autoStrategyMode
    ?"🧠 BINANCE 24H: <b>"+String(pending.autoStrategyName||pending.autoStrategyId||"AUTO")+"</b>"+
      (Number.isFinite(autoRate)?" • lịch sử <b>"+(autoRate*100).toFixed(1)+"%</b> ("+autoWins+"T/"+autoLosses+"B)":"")+"\n"
    :"";

  await sendTelegram(env,
    "🚨 <b>CÒN ~1 PHÚT • BÁO LỆNH PHIÊN SAU</b>\n"+
    "Mốc lấy màu: <b>"+timeText(pending.sourceStart)+"</b> • "+sourceText+"\n"+
    "Quy tắc: <b>vào phiên +10 phút, chốt màu ở +15 phút</b>\n"+
    autoLine+
    "➡️ "+buy+"\n"+
    "<b>"+(pending.planLabel||("Lệnh "+Number(pending.step)))+" • "+amountText(pending.amount)+"</b>\n"+
    (pending.lossCapitalMode?"Chế độ vốn thua 4 lệnh: <b>BẬT</b>\n":"")+
    "Phiên đặt lệnh: <b>"+frameText(pending.targetStart)+"</b>"
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
  const balance=Number.isFinite(Number(result.balanceAfter))
    ?Number(result.balanceAfter)
    :settings.startBalance+Number(result.pnlAfter||0);
  const waitLine=result.waitTriggered
    ?(result.lossCapitalMode
      ?"\n⏳ <b>ĐÃ CHẠM GIỚI HẠN 4 LỆNH THUA • CHỜ 1 NHỊP GIẢ LẬP THẮNG</b>; lệnh kế tiếp mới vào lại."
      :"\n⏳ <b>THUA 2 LỆNH LIÊN TIẾP • CHỜ 1 NHỊP GIẢ LẬP THẮNG</b>; lệnh kế tiếp mới vào lại.")
    :"";

  return (
    title+"\n"+
    (Number.isFinite(Number(result.sourceStart))?"Mốc lấy màu: <b>"+timeText(result.sourceStart)+"</b>\n":"")+
    "Phiên vừa xong: <b>"+frameText(result.targetStart)+"</b>\n"+
    "Đã mua: "+entered+" • Kết quả: "+actualText+"\n"+
    "Lãi/lỗ lệnh này: <b>"+money(result.delta)+"</b>\n"+
    "Tổng lãi/lỗ sau reset: <b>"+money(result.pnlAfter)+"</b>\n"+
    "Số dư theo dõi: <b>"+money(balance)+"</b>"+
    waitLine
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

  await schedulePrepareAt60(env,payload).catch(()=>{});
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
        sourceStepMinutes:SOURCE_STEP/60,
        entryDelayMinutes:ENTRY_DELAY/60,
        waitForWinAfterTwoLosses:false,
        previousResultColorRule:false,
        autoStrategy24h:true,
        autoStrategyEngine:"BINANCE_24H_STATS_V1",
        autoStrategySource:"Binance Spot BTCUSDT",
        autoStrategyInterval:"5m",
        autoStrategyCandles:288,
        autoStrategyPatternLength:3,
        autoStrategyMethods:["streak","pattern3","trend","opposite_trend","day_majority"],
        lossCapitalModeSupported:true,
        lossCapitalSequence:[1,1,2,4],
        reverseColorModeSupported:false,
        reverseColorRuleIncludedAsCandidate:false,
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


    if(u.pathname==="/auto-strategy"){
      const nowSec=Math.floor(Date.now()/1000);
      const targetParam=Number(u.searchParams.get("target"));
      const targetStart=Number.isFinite(targetParam)&&targetParam>0
        ?Math.floor(targetParam/INTERVAL)*INTERVAL
        :Math.floor(nowSec/INTERVAL)*INTERVAL+INTERVAL;
      const payload=await readHistory(env);
      const sourceStart=sourceStartForTarget(targetStart);
      const sourceColor=sourceStart===null?null:await resolvedColorAt(env,payload,sourceStart);
      try{
        const analysis=await cachedBinanceAutoStrategy(env,false);
        return json({
          ok:true,targetStart,sourceStart,sourceColor,
          ...analysis,
          direction:analysis.direction||sourceColor
        });
      }catch(e){
        return json({ok:false,targetStart,sourceStart,sourceColor,error:String(e.message||e)},502);
      }
    }


    if(u.pathname==="/trade-mode"){
      if(req.method!=="POST")return json({ok:false,error:"Chỉ chấp nhận POST"},405);
      let body={};
      try{body=await req.json()}catch(_){}

      const hasLossCapital=typeof body?.lossCapitalMode==="boolean";
      const hasAutoStrategy=typeof body?.autoStrategyMode==="boolean";
      const hasReverseColor=typeof body?.reverseColorMode==="boolean";
      if(!hasLossCapital&&!hasAutoStrategy&&!hasReverseColor){
        return json({ok:false,error:"Cần lossCapitalMode hoặc autoStrategyMode boolean"},400);
      }

      const nowSec=Math.floor(Date.now()/1000);
      const state=await readTradeState(env,nowSec);
      if(hasLossCapital)state.lossCapitalMode=body.lossCapitalMode;
      if(hasAutoStrategy)state.autoStrategyMode=body.autoStrategyMode;
      if(hasReverseColor)state.reverseColorMode=body.reverseColorMode;

      // A mode change starts a fresh sequence, but keeps existing PnL/history.
      state.lossStreak=0;
      state.waitForWin=false;
      state.waitAfterTarget=0;
      state.waitLastCheckedTarget=0;
      state.waitWinTarget=0;
      state.lastResultWin=null;
      state.reverseAfterSecondLossActive=false;
      state.step=1;
      await writeTradeState(env,state);

      let message="Đã cập nhật chế độ.";
      if(hasLossCapital){
        message=state.lossCapitalMode
          ?"Đã bật chế độ vốn thua tối đa 4 lệnh."
          :"Đã tắt chế độ vốn thua 4 lệnh.";
      }
      if(hasAutoStrategy){
        message=state.autoStrategyMode
          ?"Đã bật AUTO BINANCE 24H: quét 288 nến 5 phút và chọn phương pháp thống kê có tỷ lệ lịch sử cao nhất."
          :"Đã tắt AUTO BINANCE 24H: tool quay về đánh theo màu mốc.";
      }

      return json({
        ok:true,
        lossCapitalMode:state.lossCapitalMode,
        autoStrategyMode:state.autoStrategyMode,
        reverseColorMode:state.reverseColorMode,
        message
      });
    }

    if(u.pathname==="/trade-reset"){
      if(req.method!=="POST")return json({ok:false,error:"Chỉ chấp nhận POST"},405);
      let body={};
      try{body=await req.json()}catch(_){}
      if(body?.confirm!=="RESET")return json({ok:false,error:"Thiếu xác nhận RESET"},400);

      const nowSec=Math.floor(Date.now()/1000);
      const previous=await readTradeState(env,nowSec);
      const state=freshTradeState(dayTextFromSeconds(nowSec));
      state.lossCapitalMode=!!previous.lossCapitalMode;
      state.autoStrategyMode=!!previous.autoStrategyMode;
      state.reverseColorMode=!!previous.reverseColorMode;
      state.balanceBase=0;
      await writeTradeState(env,state);

      return json({
        ok:true,
        message:"Đã reset lệnh thực tế, thắng/thua, lãi/lỗ, số dư theo dõi và trạng thái chờ thắng về 0.",
        state
      });
    }

    if(u.pathname==="/sync"){
      try{return json(await sync(env))}
      catch(e){return json({ok:false,error:String(e.message||e)},500)}
    }

    return json({ok:true,endpoints:["/health","/category?ts=...","/history","/trade-state","/auto-strategy","/trade-mode","/trade-reset","/sync"]});
  },

  async scheduled(controller,env,ctx){
    ctx.waitUntil(scheduledTick(env));
  }
};
