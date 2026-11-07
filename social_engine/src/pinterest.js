// Posts pins from https://thepesthelp.com/pins/pins.json via the Pinterest API v5.
// Needs PINTEREST_TOKEN (pins:write, boards:read). Until your app has Standard access, use the bulk CSV instead.
const store = require("./store"), tg = require("./telegram");
const API = "https://api.pinterest.com/v5", H = () => ({ Authorization: `Bearer ${process.env.PINTEREST_TOKEN}`, "Content-Type": "application/json" });
const PER_DAY = Number(process.env.PINS_PER_DAY || 3);
async function boards() {
  const r = await fetch(`${API}/boards?page_size=100`, { headers: H() }); if (!r.ok) throw new Error(`Pinterest boards ${r.status}`);
  return Object.fromEntries((await r.json()).items.map((b) => [b.name.toLowerCase(), b.id]));
}
async function postDue() {
  if (!process.env.PINTEREST_TOKEN) return 0;
  store.db.pins ||= {}; const today = new Date().toISOString().slice(0, 10);
  const doneToday = Object.values(store.db.pins).filter((d) => d.startsWith(today)).length;
  if (doneToday >= PER_DAY) return 0;
  const pins = await (await fetch("https://thepesthelp.com/pins/pins.json")).json();
  const b = await boards(); let n = 0;
  for (const p of pins) {
    if (store.db.pins[p.file] || doneToday + n >= PER_DAY) continue;
    const board_id = b[p.board.toLowerCase()]; if (!board_id) { console.warn("Missing board:", p.board); continue; }
    const r = await fetch(`${API}/pins`, { method: "POST", headers: H(), body: JSON.stringify({ board_id, title: p.title.slice(0, 100), description: p.description.slice(0, 500), link: p.link, alt_text: p.title.slice(0, 500), media_source: { source_type: "image_url", url: p.media_url } }) });
    if (!r.ok) { console.warn("Pin failed", r.status, await r.text()); break; }
    store.db.pins[p.file] = new Date().toISOString(); store.save(); n++;
  }
  if (n) await tg.send(`📌 Posted ${n} pin(s) to Pinterest.`).catch(() => {});
  return n;
}
module.exports = { postDue };
