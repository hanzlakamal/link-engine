// Small token-protected API so the Buzz Scouts Engine dashboard can show stats and trigger a scan.
// Enabled only when ENGINE_API_TOKEN is set. Railway provides PORT.
const http = require("http"), crypto = require("crypto"), store = require("./store"), engine = require("./engine");
const TOKEN = process.env.ENGINE_API_TOKEN || "";
const ok = (req) => {
  const got = Buffer.from((req.headers.authorization || "").replace(/^Bearer /, ""));
  const want = Buffer.from(TOKEN);
  return TOKEN.length >= 24 && got.length === want.length && crypto.timingSafeEqual(got, want);
};
if (TOKEN) {
  let scanning = false;
  http.createServer(async (req, res) => {
    const send = (code, body) => { res.writeHead(code, { "content-type": "application/json" }); res.end(JSON.stringify(body)); };
    if (req.url === "/healthz") return send(200, { ok: true });
    if (!ok(req)) return send(401, { error: "unauthorized" });
    if (req.method === "GET" && req.url === "/api/stats") {
      const items = Object.values(store.db.items);
      const byStatus = items.reduce((a, i) => ((a[i.status || "new"] = (a[i.status || "new"] || 0) + 1), a), {});
      const recent = items.sort((a, b) => String(b.updated || "").localeCompare(String(a.updated || ""))).slice(0, 10)
        .map((i) => ({ status: i.status, updated: i.updated, title: i.title, subreddit: i.subreddit, url: i.url }));
      return send(200, { project: process.env.PROJECT || "thepesthelp", byStatus, approved: store.db.approvedCount,
                         seen: Object.keys(store.db.seen).length, scanning, recent });
    }
    if (req.method === "POST" && req.url === "/api/scan") {
      if (scanning) return send(409, { error: "scan already running" });
      scanning = true;
      engine.scan().catch((e) => console.warn("api scan", e.message)).finally(() => { scanning = false; });
      return send(202, { started: true });
    }
    send(404, { error: "not found" });
  }).listen(process.env.PORT || 8080, () => console.log("Engine API listening"));
}
