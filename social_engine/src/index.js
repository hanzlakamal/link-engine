const cfg = require("./config"), engine = require("./engine"), tg = require("./telegram"), pinterest = require("./pinterest");
// Telegram is optional: without it the engine still scans for the dashboard's Social inbox.
if (!process.env.ANTHROPIC_API_KEY) { console.error("Missing env var: ANTHROPIC_API_KEY"); process.exit(1); }

async function pollLoop() {
  if (!process.env.TELEGRAM_BOT_TOKEN) { console.log("No TELEGRAM_BOT_TOKEN: Telegram off, dashboard inbox only."); return; }
  let offset = 0;
  for (;;) {
    try {
      for (const u of await tg.updates(offset)) {
        offset = u.update_id + 1;
        try {
          if (u.callback_query) await engine.onCallback(u.callback_query);
          else if (u.message && (!process.env.TELEGRAM_CHAT_ID || String(u.message.chat.id) === String(process.env.TELEGRAM_CHAT_ID) || u.message.text === "/start")) await engine.onMessage(u.message);
        } catch (e) { console.warn("update", e.message); }
      }
    } catch (e) { console.warn("poll", e.message); await new Promise((r) => setTimeout(r, 5000)); }
  }
}
async function scanLoop() {
  for (;;) { try { await engine.scan(); } catch (e) { console.warn("scan", e.message); } await new Promise((r) => setTimeout(r, cfg.scanEveryMinutes * 60000)); }
}
async function pinLoop() { for (;;) { try { await pinterest.postDue(); } catch (e) { console.warn("pins", e.message); } await new Promise((r) => setTimeout(r, 60 * 60000)); } }
// Auto scans + auto pin posting are OFF unless AUTORUN=true. The Telegram bot still answers (/scan works manually).
const autorun = process.env.AUTORUN === "true";
console.log(`Traffic engine running (Reddit via ${require("./reddit").mode()}). Autorun: ${autorun ? "ON" : "OFF (set AUTORUN=true to enable)"}.`);
pollLoop();
if (autorun) { scanLoop(); pinLoop(); }
require("./api"); // dashboard API (only if ENGINE_API_TOKEN is set)
