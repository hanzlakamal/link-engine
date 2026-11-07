// Reddit reader. Uses the official API if REDDIT_CLIENT_ID/SECRET are set (needs Reddit's developer approval),
// otherwise falls back to Reddit's public RSS feeds (no key needed, slower, no comment counts).
const UA = process.env.REDDIT_USER_AGENT || "thepesthelp-answer-engine/1.0";
const useApi = () => process.env.REDDIT_CLIENT_ID && process.env.REDDIT_CLIENT_SECRET;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ---------- official API ----------
let token = null, tokenExp = 0;
async function auth() {
  if (token && Date.now() < tokenExp) return token;
  const r = await fetch("https://www.reddit.com/api/v1/access_token", {
    method: "POST",
    headers: { Authorization: "Basic " + Buffer.from(`${process.env.REDDIT_CLIENT_ID}:${process.env.REDDIT_CLIENT_SECRET}`).toString("base64"), "Content-Type": "application/x-www-form-urlencoded", "User-Agent": UA },
    body: "grant_type=client_credentials",
  });
  if (!r.ok) throw new Error(`Reddit auth ${r.status}`);
  const j = await r.json(); token = j.access_token; tokenExp = Date.now() + (j.expires_in - 60) * 1000; return token;
}
async function apiGet(path) {
  const r = await fetch("https://oauth.reddit.com" + path, { headers: { Authorization: `Bearer ${await auth()}`, "User-Agent": UA } });
  if (r.status === 429) { await sleep(10000); return apiGet(path); }
  if (!r.ok) throw new Error(`Reddit ${r.status} ${path}`);
  return (await r.json()).data.children.map((c) => c.data).map((p) => ({ id: `reddit_${p.id}`, source: "reddit", sub: p.subreddit, title: p.title, body: (p.selftext || "").slice(0, 3000), url: `https://www.reddit.com${p.permalink}`, created: p.created_utc * 1000, comments: p.num_comments, locked: p.locked || p.archived, over18: p.over_18 }));
}

// ---------- public RSS fallback ----------
const decode = (s) => s.replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&amp;/g, "&");
const strip = (h) => decode(decode(h)).replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").replace(/submitted by .*$/i, "").trim();
function parseAtom(xml) {
  return [...xml.matchAll(/<entry>([\s\S]*?)<\/entry>/g)].map(([, e]) => {
    const g = (re) => (e.match(re) || [])[1] || "";
    const id = g(/<id>t3_([^<]+)<\/id>/); if (!id) return null;
    return { id: `reddit_${id}`, source: "reddit", sub: g(/<category term="([^"]+)"/), title: decode(g(/<title>([\s\S]*?)<\/title>/)), body: strip(g(/<content[^>]*>([\s\S]*?)<\/content>/)).slice(0, 3000), url: g(/<link href="([^"]+)"/), created: Date.parse(g(/<published>([^<]+)<\/published>/) || g(/<updated>([^<]+)<\/updated>/)), comments: 0, locked: false, over18: false };
  }).filter(Boolean);
}
async function rss(path) {
  await sleep(2500); // be polite: public feeds rate-limit hard
  const r = await fetch("https://www.reddit.com" + path, { headers: { "User-Agent": UA, Accept: "application/atom+xml" } });
  if (r.status === 429) { await sleep(30000); return []; }
  if (!r.ok) throw new Error(`Reddit RSS ${r.status} ${path}`);
  return parseAtom(await r.text());
}

module.exports = {
  mode: () => (useApi() ? "api" : "rss"),
  search: (q) => (useApi() ? apiGet(`/search?q=${encodeURIComponent(q)}&sort=new&t=day&limit=25&type=link`) : rss(`/search.rss?q=${encodeURIComponent(q)}&sort=new&t=day`)),
  newIn: (sub) => (useApi() ? apiGet(`/r/${sub}/new?limit=25`) : rss(`/r/${sub}/new.rss`)),
  parseAtom,
};
