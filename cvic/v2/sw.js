const CACHE='cesky-sklon-v2';
const ASSETS=['./','./index.html','./nouns.js','./quiz.js'];

self.addEventListener('install',e=>{
    e.waitUntil(caches.open(CACHE).then(c=>c.addAll(ASSETS)));
    self.skipWaiting();
});

self.addEventListener('activate',e=>{
    e.waitUntil(caches.keys().then(ks=>Promise.all(ks.filter(k=>k!==CACHE).map(k=>caches.delete(k)))));
    self.clients.claim();
});

self.addEventListener('fetch',e=>{
    e.respondWith(
        caches.match(e.request).then(cached=>{
            if(cached){
                fetch(e.request).then(r=>{if(r.ok){caches.open(CACHE).then(c=>c.put(e.request,r));}}).catch(()=>{});
                return cached;
            }
            return fetch(e.request).then(r=>{
                if(r.ok){const cl=r.clone();caches.open(CACHE).then(c=>c.put(e.request,cl));}
                return r;
            });
        })
    );
});
