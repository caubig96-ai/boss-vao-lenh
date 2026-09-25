const C="boss-iphone-static-v2";
self.addEventListener("install",e=>{
  self.skipWaiting();
  e.waitUntil(caches.open(C).then(c=>c.addAll(["./","./index.html","./manifest.webmanifest"])));
});
self.addEventListener("activate",e=>{
  e.waitUntil(Promise.all([
    caches.keys().then(keys=>Promise.all(keys.filter(k=>k!==C).map(k=>caches.delete(k)))),
    self.clients.claim()
  ]));
});
self.addEventListener("fetch",e=>{
  if(e.request.url.includes("api.predict.fun"))return;
  if(e.request.mode==="navigate"){
    e.respondWith(fetch(e.request,{cache:"no-store"}).catch(()=>caches.match("./index.html")));
    return;
  }
  e.respondWith(fetch(e.request,{cache:"no-store"}).then(r=>{
    const copy=r.clone();
    caches.open(C).then(c=>c.put(e.request,copy));
    return r;
  }).catch(()=>caches.match(e.request)));
});