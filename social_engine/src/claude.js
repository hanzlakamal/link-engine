const cfg = require("./config");
async function ask(model, system, user, maxTokens = 900) {
  const r = await fetch("https://api.anthropic.com/v1/messages", {
    method: "POST",
    headers: { "x-api-key": process.env.ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json" },
    body: JSON.stringify({ model, max_tokens: maxTokens, system, messages: [{ role: "user", content: user }] }),
  });
  if (!r.ok) throw new Error(`Claude ${r.status}: ${await r.text()}`);
  return (await r.json()).content.map((c) => c.text || "").join("").trim();
}
const json = (t) => JSON.parse(t.slice(t.indexOf("{"), t.lastIndexOf("}") + 1));
const where = (t) => (t.source === "quora" ? "Quora question" : `Subreddit: r/${t.sub}`);
const pageList = () => cfg.pages.map((p) => (typeof p === "string" ? p : `${p.url}${p.about ? ` (${p.about})` : ""}`)).join("; ");

// Everything brand-specific comes from cfg.brand, so one engine serves any brand.
async function score(t) {
  const b = cfg.brand;
  const sys = `You triage ${t.source === "quora" ? "Quora questions" : "Reddit posts"} for ${b.name}: ${b.offer}.
Return ONLY JSON: {"relevant":bool,"live_problem":bool,"us_likely":bool,"category":string,"reject_reason":string|null,"page":string|null,"why":string}
relevant = ${b.relevant || `the poster is asking about something ${b.name} genuinely helps with`}.
live_problem = ${b.live_problem || "they are actively looking for help, ideas or recommendations now (not news, not a vendor promoting, not a meme)"}.
us_likely = likely in the US or Canada (true if unclear).
category = a 1-3 word topic label.
Reject if about: ${cfg.rejectTopics.join(", ") || "nothing specific"}; or if answering with a brand mention would be unwelcome.
page = the single best matching path from this list, or null: ${pageList()}`;
  return json(await ask(cfg.models.score, sys, `${where(t)}\nTitle: ${t.title}\nBody: ${t.body || "(none)"}`, 300));
}

async function draft(t, page, withLink) {
  const b = cfg.brand, quora = t.source === "quora";
  const link = withLink && page ? `${cfg.site}${page}${page.includes("?") ? "&" : "?"}utm_source=${t.source}&utm_medium=answer&utm_campaign=${encodeURIComponent(t.id)}` : null;
  const sys = `You write a ${quora ? "Quora answer" : "Reddit comment"} as ${b.persona || `someone who knows this topic well`}.
Rules:
- Genuinely answer THEIR question first: specific, practical, honest. Give real options, not just one product.
- ${quora ? "120-250 words. Can use a short list if it helps." : "80-180 words."} Plain, friendly, no headings, no emojis, no marketing tone, no "Great question".
- Never invent personal anecdotes with fake details. Never claim to be someone you're not.
${b.rules ? `- ${b.rules}` : ""}
${link ? `- End with ONE natural line that includes this link and discloses the connection, e.g. "${b.link_line || "Full disclosure, I'm involved with this shop, but it might help:"} ${link}". Use the link exactly once.` : "- Do NOT include any links or mention any website or brand."}
Return only the ${quora ? "answer" : "comment"} text.`;
  return ask(cfg.models.draft, sys, `${where(t)}\nTitle: ${t.title}\nBody: ${t.body || "(none)"}`);
}
module.exports = { score, draft, ask };
