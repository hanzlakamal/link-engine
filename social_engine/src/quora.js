// Quora question finder. Quora has no public API or feeds, so we ask Google (via DataForSEO SERP)
// for quora.com questions matching each phrase. ~$0.002 per query. Needs DATAFORSEO_LOGIN / DATAFORSEO_PASSWORD.
const LIVE = "https://api.dataforseo.com/v3/serp/google/organic/live/regular";

const cfg = require("./config");
const creds = () => ({ login: process.env.DATAFORSEO_LOGIN || cfg.dataforseo?.login, password: process.env.DATAFORSEO_PASSWORD || cfg.dataforseo?.password });
const enabled = () => !!(creds().login && creds().password);

function questionUrl(url) {
  // https://www.quora.com/What-is-X/answer/Some-Name -> https://www.quora.com/What-is-X
  const u = new URL(url);
  if (!/(^|\.)quora\.com$/.test(u.hostname)) return null;
  const parts = u.pathname.split("/").filter(Boolean);
  if (!parts.length || ["profile", "topic", "spaces", "q", "search", "unanswered"].includes(parts[0].toLowerCase())) return null;
  return `https://www.quora.com/${parts[0]}`;
}

async function search(q) {
  if (!enabled()) return [];
  const auth = Buffer.from(`${creds().login}:${creds().password}`).toString("base64");
  const r = await fetch(LIVE, {
    method: "POST",
    headers: { Authorization: `Basic ${auth}`, "content-type": "application/json" },
    body: JSON.stringify([{ keyword: `site:quora.com ${q}`, location_code: 2840, language_code: "en", depth: 20 }]),
  });
  if (!r.ok) throw new Error(`DataForSEO ${r.status}`);
  const items = (await r.json()).tasks?.[0]?.result?.[0]?.items || [];
  const out = new Map();
  for (const it of items) {
    if (it.type !== "organic" || !it.url) continue;
    const url = questionUrl(it.url);
    if (!url || out.has(url)) continue;
    const slug = url.split("/").pop();
    out.set(url, { id: `quora_${slug.slice(0, 80)}`, source: "quora", sub: "Quora", title: (it.title || slug.replace(/-/g, " ")).replace(/ - Quora$/, ""),
                   body: (it.description || "").slice(0, 1000), url, created: Date.now(), comments: 0, locked: false, over18: false });
  }
  return [...out.values()];
}

module.exports = { search, enabled, questionUrl };
