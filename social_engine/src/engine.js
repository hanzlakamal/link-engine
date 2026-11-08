const cfg = require("./config"), store = require("./store"), reddit = require("./reddit"), quora = require("./quora"), claude = require("./claude"), tg = require("./telegram");
const esc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const rejectRe = () => (cfg.rejectTopics.length ? new RegExp(cfg.rejectTopics.map(esc).join("|"), "i") : /$^/);

async function collect() {
  const out = new Map();
  for (const q of cfg.queries) { try { for (const t of await reddit.search(q)) out.set(t.id, t); } catch (e) { console.warn(e.message); } }
  for (const s of cfg.subreddits) { try { for (const t of await reddit.newIn(s)) out.set(t.id, t); } catch (e) { console.warn(e.message); } }
  if (cfg.quora && quora.enabled()) {
    for (const q of (cfg.quoraQueries.length ? cfg.quoraQueries : cfg.queries.slice(0, 6))) {
      try { for (const t of await quora.search(q)) out.set(t.id, t); } catch (e) { console.warn("quora", e.message); }
    }
  }
  return [...out.values()];
}

function prefilter(t) {
  if (store.seen(t.id)) return false;
  store.markSeen(t.id);
  if (t.locked || t.over18) return false;
  if (t.source !== "quora" && Date.now() - t.created > cfg.maxAgeHours * 36e5) return false; // Quora questions stay answerable
  if (t.comments > cfg.maxComments) return false;
  if (rejectRe().test(t.title + " " + t.body)) return false;
  return true;
}

async function handle(t) {
  const s = await claude.score(t);
  if (!s.relevant || !s.live_problem || !s.us_likely || s.reject_reason) return null;
  const linkAllowed = t.source === "quora" || !cfg.avoidSubreddits.includes(t.sub);
  const withLink = linkAllowed && !!s.page && store.db.approvedCount % cfg.linkEveryNth === 0;
  const draft = await claude.draft(t, s.page, withLink);
  return { ...t, category: s.category, page: s.page, why: s.why, withLink, draft, status: "pending", found: new Date().toISOString() };
}

async function scan() {
  const all = await collect();
  const fresh = all.filter(prefilter).sort((a, b) => a.comments - b.comments);
  let sent = 0;
  for (const t of fresh) {
    if (sent >= cfg.maxDraftsPerScan) break;
    try { const it = await handle(t); if (!it) continue; store.put(it); await tg.sendItem(it); sent++; } catch (e) { console.warn("process", e.message); }
  }
  store.prune();
  console.log(`[scan] ${all.length} found, ${fresh.length} new, ${sent} drafts sent`);
  return sent;
}

async function onCallback(cb) {
  const [action, id] = cb.data.split(":"); const it = store.get(id);
  if (!it) return tg.answer(cb.id, "Not found");
  if (action === "posted") { store.db.approvedCount++; store.log(it, "posted"); await tg.editItem(it, cb.message, "✅ Marked posted"); return tg.answer(cb.id, "Logged"); }
  if (action === "skip") { store.log(it, "skipped"); await tg.editItem(it, cb.message, "❌ Skipped"); return tg.answer(cb.id, "Skipped"); }
  if (action === "toggle") it.withLink = !it.withLink;
  if (action === "redraft" || action === "toggle") { await tg.answer(cb.id, "Redrafting…"); it.draft = await claude.draft(it, it.page, it.withLink); store.put(it); return tg.editItem(it, cb.message); }
}

async function onMessage(m) {
  const t = (m.text || "").trim();
  if (t === "/scan") { await tg.send("Scanning…", m.chat.id); const n = await scan(); return tg.send(`Done: ${n} new drafts.`); }
  if (t === "/stats") {
    const items = Object.values(store.db.items), c = (s) => items.filter((i) => i.status === s).length;
    return tg.send(`Drafts: ${items.length}\nPosted: ${c("posted")}\nSkipped: ${c("skipped")}\nPending: ${c("pending")}`);
  }
  if (t === "/start" || t === "/help") return tg.send(`Chat ID: <code>${m.chat.id}</code>\nCommands: /scan /stats`, m.chat.id);
}
module.exports = { scan, onCallback, onMessage, prefilter, handle };
