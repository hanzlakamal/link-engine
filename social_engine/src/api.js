// Token-protected API used by the Buzz Scouts dashboard (Social inbox, stats, settings, scans).
// Enabled only when ENGINE_API_TOKEN is set. Railway provides PORT.
const http = require("http"), crypto = require("crypto");
const store = require("./store"), engine = require("./engine"), cfg = require("./config"), claude = require("./claude");
const TOKEN = process.env.ENGINE_API_TOKEN || "";
const ok = (req) => {
  const got = Buffer.from((req.headers.authorization || "").replace(/^Bearer /, ""));
  const want = Buffer.from(TOKEN);
  return TOKEN.length >= 24 && got.length === want.length && crypto.timingSafeEqual(got, want);
};
const view = (i) => ({ id: i.id, source: i.source, sub: i.sub, title: i.title, body: (i.body || "").slice(0, 600), url: i.url,
  category: i.category, why: i.why, page: i.page, withLink: i.withLink, draft: i.draft, status: i.status || "pending",
  found: i.found, updated: i.updated, by: i.by, comments: i.comments });

async function body(req) {
  let raw = "";
  for await (const chunk of req) { raw += chunk; if (raw.length > 200000) throw new Error("too large"); }
  return JSON.parse(raw || "{}");
}

let server = null;
if (TOKEN) {
  let scanning = false;
  server = http.createServer(async (req, res) => {
    const send = (code, b) => { res.writeHead(code, { "content-type": "application/json" }); res.end(JSON.stringify(b)); };
    const url = new URL(req.url, "http://x");
    if (url.pathname === "/healthz") return send(200, { ok: true });
    if (!ok(req)) return send(401, { error: "unauthorized" });
    try {
      if (req.method === "GET" && url.pathname === "/api/stats") {
        const items = Object.values(store.db.items);
        const byStatus = items.reduce((a, i) => ((a[i.status || "pending"] = (a[i.status || "pending"] || 0) + 1), a), {});
        const recent = items.sort((a, b) => String(b.updated || b.found || "").localeCompare(String(a.updated || a.found || ""))).slice(0, 10)
          .map((i) => ({ status: i.status, updated: i.updated, title: i.title, sub: i.sub, source: i.source, url: i.url }));
        return send(200, { project: process.env.PROJECT || "thepesthelp", brand: cfg.brand.name, site: cfg.site,
          quora: !!(cfg.quora && require("./quora").enabled()), telegram: require("./telegram").enabled(), byStatus,
          approved: store.db.approvedCount, seen: Object.keys(store.db.seen).length, scanning, recent });
      }
      // Social inbox: newest first, filter by status / source, paginated
      if (req.method === "GET" && url.pathname === "/api/items") {
        const status = url.searchParams.get("status") || "pending", source = url.searchParams.get("source") || "";
        const limit = Math.min(100, Number(url.searchParams.get("limit") || 50)), offset = Number(url.searchParams.get("offset") || 0);
        const all = Object.values(store.db.items).filter((i) => (status === "all" || (i.status || "pending") === status) && (!source || i.source === source))
          .sort((a, b) => String(b.updated || b.found || "").localeCompare(String(a.updated || a.found || "")));
        return send(200, { total: all.length, items: all.slice(offset, offset + limit).map(view) });
      }
      const m = url.pathname.match(/^\/api\/items\/([A-Za-z0-9_\-]+)\/(posted|skip|redraft|toggle|restore|edit)$/);
      if (req.method === "POST" && m) {
        const it = store.get(m[1]); if (!it) return send(404, { error: "not found" });
        const b = await body(req), by = String(b.by || "").slice(0, 120);
        if (m[2] === "posted") { if (it.status !== "posted") store.db.approvedCount++; it.by = by; if (b.draft) it.draft = String(b.draft).slice(0, 5000); store.log(it, "posted"); }
        else if (m[2] === "skip") { it.by = by; store.log(it, "skipped"); }
        else if (m[2] === "restore") { store.log(it, "pending"); }
        else if (m[2] === "edit") { it.draft = String(b.draft || it.draft).slice(0, 5000); store.put(it); }
        else {
          if (m[2] === "toggle") it.withLink = !it.withLink;
          it.draft = await claude.draft(it, it.page, it.withLink); store.put(it);
        }
        return send(200, view(it));
      }
      if (req.method === "GET" && url.pathname === "/api/config") return send(200, cfg.public());
      if (req.method === "POST" && url.pathname === "/api/config") return send(200, { saved: Object.keys(cfg.update(await body(req))) });
      if (req.method === "POST" && url.pathname === "/api/scan") {
        if (scanning) return send(409, { error: "scan already running" });
        scanning = true;
        engine.scan().catch((e) => console.warn("api scan", e.message)).finally(() => { scanning = false; });
        return send(202, { started: true });
      }
    } catch (e) { return send(400, { error: String(e.message).slice(0, 160) }); }
    send(404, { error: "not found" });
  }).listen(process.env.PORT || 8080, () => console.log("Engine API listening"));
}
module.exports = { server: () => server };
