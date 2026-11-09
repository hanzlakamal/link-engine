// Offline: dashboard inbox API (list, edit, posted, skip, restore) with token auth.
const assert = require("assert");
process.env.DATA_DIR = require("path").join(__dirname, ".tmp-api"); require("fs").rmSync(process.env.DATA_DIR, { recursive: true, force: true });
process.env.ENGINE_API_TOKEN = "t".repeat(32); process.env.PORT = "18731";
const store = require("../src/store");
store.put({ id: "reddit_z", source: "reddit", sub: "gifts", title: "Gift for dad?", url: "https://reddit.com/x", draft: "d1", status: "pending", found: new Date().toISOString() });
const api = require("../src/api");
const H = { authorization: "Bearer " + process.env.ENGINE_API_TOKEN, "content-type": "application/json" };
const call = (m, p, b) => fetch("http://127.0.0.1:18731" + p, { method: m, headers: H, body: b ? JSON.stringify(b) : undefined }).then((r) => r.json().then((j) => [r.status, j]));
(async () => {
  await new Promise((r) => setTimeout(r, 200));
  assert.equal((await fetch("http://127.0.0.1:18731/api/items")).status, 401);
  let [s, j] = await call("GET", "/api/items?status=pending"); assert.equal(s, 200); assert.equal(j.total, 1);
  [s, j] = await call("POST", "/api/items/reddit_z/edit", { draft: "edited" }); assert.equal(j.draft, "edited");
  [s, j] = await call("POST", "/api/items/reddit_z/posted", { by: "emp1@x.com" }); assert.equal(j.status, "posted"); assert.equal(j.by, "emp1@x.com");
  assert.equal(store.db.approvedCount, 1);
  [s, j] = await call("POST", "/api/items/reddit_z/posted", { by: "emp1@x.com" }); assert.equal(store.db.approvedCount, 1); // no double count
  [s, j] = await call("POST", "/api/items/reddit_z/restore", {}); assert.equal(j.status, "pending");
  [s, j] = await call("POST", "/api/items/nope/skip", {}); assert.equal(s, 404);
  console.log("PASS api"); api.server().closeAllConnections(); api.server().close();
})().catch((e) => { console.error(e); process.exit(1); });
