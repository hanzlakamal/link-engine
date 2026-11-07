// Tiny JSON store. On Railway mount a volume at /data so it survives redeploys.
const fs = require("fs"), path = require("path");
const DIR = process.env.DATA_DIR || (fs.existsSync("/data") ? "/data" : path.join(__dirname, "..", "data"));
const FILE = path.join(DIR, "store.json");
fs.mkdirSync(DIR, { recursive: true });
let db = { seen: {}, items: {}, approvedCount: 0 };
try { db = { ...db, ...JSON.parse(fs.readFileSync(FILE, "utf8")) }; } catch {}
const save = () => fs.writeFileSync(FILE + ".tmp", JSON.stringify(db)) || fs.renameSync(FILE + ".tmp", FILE);
module.exports = {
  db, save,
  seen: (id) => !!db.seen[id],
  markSeen(id) { db.seen[id] = Date.now(); },
  put(item) { db.items[item.id] = item; save(); },
  get: (id) => db.items[id],
  prune() { const cut = Date.now() - 14 * 864e5; for (const [k, t] of Object.entries(db.seen)) if (t < cut) delete db.seen[k]; save(); },
  log(item, status) { item.status = status; item.updated = new Date().toISOString(); save(); }
};
