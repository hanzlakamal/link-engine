// T-Shirt Crisis (funny graphic tees, US). Starting defaults only: the dashboard pushes the live settings
// (Settings -> Social & Community), so edit there, not here.
module.exports = {
  site: "https://www.tshirtcrisis.com",
  pinsUrl: "",
  brand: {
    name: "T-Shirt Crisis",
    offer: "a US shop of funny, sarcastic graphic t-shirts and hoodies for everyday disasters (birthdays, holidays, family dinners)",
    relevant: "the poster wants gift ideas, funny/graphic shirt recommendations, or a shirt for an occasion, person or joke",
    live_problem: "they are choosing a gift or shirt now (not selling, not a design/printing business question)",
    persona: "a friendly person who loves funny gifts and graphic tees",
    rules: "Suggest several genuinely good options (not only our shop). Keep humour light. Never claim products are made in the USA; never promise shipping times or discounts.",
    link_line: "Full disclosure, I work with this shop, but this might fit:",
  },
  scanEveryMinutes: Number(process.env.SCAN_EVERY_MINUTES || 60),
  maxAgeHours: 24,
  maxComments: 60,
  maxDraftsPerScan: 5,
  linkEveryNth: 3,
  queries: [
    "funny t-shirt gift", "gift ideas for dad", "gift for brother", "gift for husband funny",
    "white elephant gift ideas", "secret santa gift under 30", "thanksgiving shirt", "family christmas shirts",
    "where to buy funny shirts", "graphic tee recommendations", "sarcastic shirt", "gag gift ideas"
  ],
  subreddits: ["GiftIdeas", "gifts", "secretsanta", "tshirts", "findfashion", "HelpMeFind", "Christmas"],
  avoidSubreddits: ["tshirts"],
  quora: true,
  quoraQueries: ["funny gift ideas for dad", "best funny t-shirts", "white elephant gift ideas", "secret santa gift ideas for coworkers"],
  pages: [
    { url: "/", about: "funny graphic tees for every crisis" },
    { url: "/shop/", about: "full catalog of funny and sarcastic t-shirts and hoodies" }
  ],
  rejectTopics: ["wholesale", "custom printing business", "bulk order", "uniforms"],
  models: { score: process.env.SCORE_MODEL || "claude-haiku-5-5", draft: process.env.DRAFT_MODEL || "claude-sonnet-5-5" }
};
