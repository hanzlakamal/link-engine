const API = () => `https://api.telegram.org/bot${process.env.TELEGRAM_BOT_TOKEN}`;
const CHAT = () => process.env.TELEGRAM_CHAT_ID;
async function call(method, body) {
  const r = await fetch(`${API()}/${method}`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
  const j = await r.json(); if (!j.ok) throw new Error(`Telegram ${method}: ${j.description}`); return j.result;
}
const esc = (s) => String(s).replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
const where = (it) => (it.source === "quora" ? "<b>Quora</b>" : `<b>r/${esc(it.sub)}</b> · ${it.comments} comments`);
const card = (it) => `${where(it)} · ${esc(it.category)}\n<b>${esc(it.title)}</b>\n${esc(it.url)}\n\n<i>Why:</i> ${esc(it.why || "")}\n\n<b>Draft${it.withLink ? " (with link)" : " (no link)"}:</b>\n<code>${esc(it.draft)}</code>`;
const kb = (id) => ({ inline_keyboard: [[{ text: "✅ Posted it", callback_data: `posted:${id}` }, { text: "🔁 Redraft", callback_data: `redraft:${id}` }], [{ text: "🔗/🚫 Toggle link", callback_data: `toggle:${id}` }, { text: "❌ Skip", callback_data: `skip:${id}` }]] });
module.exports = {
  esc, call,
  send: (text, chatId) => call("sendMessage", { chat_id: chatId || CHAT(), text, parse_mode: "HTML", disable_web_page_preview: true }),
  sendItem: (it) => call("sendMessage", { chat_id: CHAT(), text: card(it), parse_mode: "HTML", disable_web_page_preview: true, reply_markup: kb(it.id) }),
  editItem: (it, msg, note) => call("editMessageText", { chat_id: msg.chat.id, message_id: msg.message_id, text: card(it) + (note ? `\n\n<b>${esc(note)}</b>` : ""), parse_mode: "HTML", disable_web_page_preview: true, reply_markup: note ? undefined : kb(it.id) }),
  answer: (cbId, text) => call("answerCallbackQuery", { callback_query_id: cbId, text }),
  updates: (offset) => call("getUpdates", { offset, timeout: 50, allowed_updates: ["callback_query", "message"] }),
};
