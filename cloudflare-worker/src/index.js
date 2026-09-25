const API="https://api.predict.fun";
const JSON_HEADERS={"content-type":"application/json; charset=utf-8","access-control-allow-origin":"*"};

function json(data,status=200){return new Response(JSON.stringify(data),{status,headers:JSON_HEADERS})}
async function api(path,key){
  const r=await fetch(API+path,{headers:{"x-api-key":key,"accept":"application/json"}});
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
function normalizeCategory(x){
  const slug=String(pick(x,"slug","market.slug","category.slug")||"");
  if(!/btc-updown-5m-/i.test(slug))return null;
  const ts=Number((slug.match(/(\d{10,13})$/)||[])[1]||0);
  const outcome=String(pick(x,"outcome","result","resolution","market.outcome","market.result")||"").toUpperCase();
  let color=null;
  if(/UP|YES|GREEN|TRUE/.test(outcome))color="V";
  if(/DOWN|NO|RED|FALSE/.test(outcome))color="X";
  return {slug,ts:ts>1e12?Math.floor(ts/1000):ts,color,outcome};
}
async function sync(env){
  if(!env.PREDICT_API_KEY)throw new Error("Chưa cấu hình PREDICT_API_KEY");
  let after="",pages=0,found=[];
  while(pages<8&&found.length<300){
    const q=new URLSearchParams({first:"100",status:"RESOLVED",marketVariant:"CRYPTO_UP_DOWN"});
    if(after)q.set("after",after);
    const d=await api("/v1/categories?"+q,env.PREDICT_API_KEY);
    const items=d?.data?.items||d?.items||d?.data||[];
    if(!Array.isArray(items))break;
    found.push(...items.map(normalizeCategory).filter(Boolean));
    after=d?.data?.pageInfo?.endCursor||d?.pageInfo?.endCursor||d?.cursor||"";
    pages++;
    if(!after||items.length===0)break;
  }
  const unique=[...new Map(found.map(x=>[x.slug,x])).values()].sort((a,b)=>a.ts-b.ts).slice(-500);
  const payload={updatedAt:new Date().toISOString(),count:unique.length,rounds:unique};
  await env.BOSS_KV.put("history",JSON.stringify(payload));
  return payload;
}
export default {
  async fetch(req,env){
    const u=new URL(req.url);
    if(req.method==="OPTIONS")return new Response(null,{headers:{...JSON_HEADERS,"access-control-allow-methods":"GET,OPTIONS"}});
    if(u.pathname==="/health")return json({ok:true,service:"Boss 5 Nen Cloud",time:new Date().toISOString()});
    if(u.pathname==="/history"){
      const raw=await env.BOSS_KV.get("history");
      return raw?new Response(raw,{headers:JSON_HEADERS}):json({updatedAt:null,count:0,rounds:[]});
    }
    if(u.pathname==="/sync"){
      try{return json(await sync(env))}catch(e){return json({ok:false,error:String(e.message||e)},500)}
    }
    return json({ok:true,endpoints:["/health","/history","/sync"]});
  },
  async scheduled(controller,env,ctx){ctx.waitUntil(sync(env))}
};
