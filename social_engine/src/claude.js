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

async function score(t) {
  const sys = `You triage Reddit posts for a US referral site that connects homeowners with local pest control and wildlife removal pros.
Return ONLY JSON: {"relevant":bool,"live_problem":bool,"us_likely":bool,"category":"wildlife|pest|other","reject_reason":string|null,"page":string|null,"why":string}
relevant = the poster has (or is asking about) an animal/pest problem in or around their home.
live_problem = it's happening now at their house or apartment (not a pet, not curiosity, not a business).
Reject if about: ${cfg.rejectTopics.join(", ")}; pets; commercial property; outside the US/Canada.
page = the single best matching path from this list, or null: ${cfg.pages.map((p) => `${p.url} (${p.about})`).join("; ")}`;
  return json(await ask(cfg.models.score, sys, `Subreddit: r/${t.sub}\nTitle: ${t.title}\nBody: ${t.body || "(none)"}`, 300));
}

async function draft(t, page, withLink) {
  const link = withLink && page ? `${cfg.site}${page}?utm_source=${t.source}&utm_medium=answer&utm_campaign=${t.id}` : null;
  const sys = `You write a Reddit comment as a knowledgeable homeowner who has dealt with pest and wildlife problems.
Rules:
- Genuinely answer THEIR situation first: likely culprit, how to tell, what to do now, safety. Specific and practical.
- 80-180 words. Plain, friendly, no headings, no emojis, no marketing tone, no "Great question".
- Never claim to be a professional or to have done a specific job. Never invent personal anecdotes with fake details.
- Safety: never advise handling wild animals; droppings = wet cleanup, never sweep or vacuum dry (hantavirus, roundworm, histoplasmosis as relevant). Bats: don't seal them in; contact a doctor if bat contact while sleeping.
- Suggest calling a licensed local wildlife/pest pro when it's warranted.
- Never use the words "free quote", "same day", "24/7", "guarantee".
${link ? `- End with ONE natural line that includes this link and discloses it: e.g. "I put together a guide on this, if it helps: ${link}". Use the link exactly once.` : "- Do NOT include any links or mention any website."}
Return only the comment text.`;
  return ask(cfg.models.draft, sys, `Subreddit: r/${t.sub}\nTitle: ${t.title}\nBody: ${t.body || "(none)"}`);
}
module.exports = { score, draft, ask };
