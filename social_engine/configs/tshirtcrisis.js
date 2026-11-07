// T-Shirt Crisis (funny graphic tees, US). Same engine, different targets. Edit freely.
module.exports = {
  site: "https://www.tshirtcrisis.com",
  scanEveryMinutes: Number(process.env.SCAN_EVERY_MINUTES || 60),
  maxAgeHours: 24,
  maxComments: 60,
  maxDraftsPerScan: 5,
  linkEveryNth: 3,          // gift threads tolerate fewer links than help threads
  queries: [
    "funny t-shirt gift", "gift ideas for dad", "gift for brother", "gift for husband funny",
    "white elephant gift ideas", "secret santa gift under 30", "thanksgiving shirt", "family christmas shirts",
    "where to buy funny shirts", "graphic tee recommendations", "sarcastic shirt", "gag gift ideas"
  ],
  subreddits: ["GiftIdeas", "gifts", "secretsanta", "tshirts", "findfashion", "HelpMeFind", "Christmas"],
  avoidSubreddits: ["tshirts"],   // read for trends; self-promo is not welcome there
  pages: [
    { url: "/", about: "funny graphic tees for every crisis, free US shipping" },
    { url: "/shop/", about: "full catalog of funny and sarcastic t-shirts and hoodies" }
    // Add collection pages here, e.g. { url: "/product-category/christmas/", about: "funny Christmas shirts" }
  ],
  rejectTopics: ["wholesale", "custom printing business", "bulk order", "uniforms"],
  models: { score: process.env.SCORE_MODEL || "claude-haiku-5-5", draft: process.env.DRAFT_MODEL || "claude-sonnet-5-5" }
};
