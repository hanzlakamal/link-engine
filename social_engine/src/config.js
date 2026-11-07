// Edit this file to tune what the engine looks for.
// Multi-project: set PROJECT=<name> to load configs/<name>.js instead (one Railway service per brand, same code).
const project = (process.env.PROJECT || "").replace(/[^a-z0-9_-]/gi, "");
if (project && project !== "thepesthelp") { module.exports = require("../configs/" + project); return; }
module.exports = {
  site: "https://thepesthelp.com",
  pinsUrl: "https://thepesthelp.com/pins/pins.json",
  scanEveryMinutes: Number(process.env.SCAN_EVERY_MINUTES || 30),
  maxAgeHours: 24,          // ignore older threads
  maxComments: 40,          // crowded threads rarely get seen
  maxDraftsPerScan: 6,      // keep the approval queue small
  linkEveryNth: 2,          // include a link in at most 1 of every N approved answers

  // Search phrases (Reddit search, newest first)
  queries: [
    "raccoon in attic", "raccoon in my attic", "raccoons under deck",
    "squirrel in attic", "squirrels in my attic", "squirrel in walls",
    "bats in attic", "bat in my house", "bat guano",
    "mice in walls", "mouse droppings", "mice in house", "rats in attic", "rat droppings",
    "possum under house", "opossum under deck", "skunk under porch",
    "snake in garage", "birds in dryer vent", "moles in yard",
    "what animal is in my attic", "noises in attic at night", "scratching in walls",
    "what poop is this", "droppings in attic",
    "ants in kitchen", "roaches in apartment", "german roaches", "cockroach infestation"
  ],

  // Subreddits to watch directly (new posts), plus search across all of Reddit
  subreddits: ["homeowners", "HomeImprovement", "pestcontrol", "whatsthisbug", "Wildlife", "FirstTimeHomeBuyer", "DIY", "RealEstate"],
  avoidSubreddits: ["pestcontrol"], // read for insight, but don't draft link answers where self-promo is banned (edit to taste)

  // Pages the drafter may link to (only when it truly helps)
  pages: [
    { url: "/guides/raccoon-poop/", about: "identifying raccoon droppings/latrines, roundworm risk, safe cleanup" },
    { url: "/guides/squirrel-poop/", about: "identifying squirrel droppings, squirrels vs rats in attic" },
    { url: "/guides/possum-poop/", about: "identifying opossum droppings, possums under deck/house" },
    { url: "/guides/mouse-poop/", about: "identifying mouse droppings, hantavirus, CDC wet-cleaning method" },
    { url: "/guides/rat-poop/", about: "identifying rat droppings, Norway vs roof rat" },
    { url: "/guides/bat-poop/", about: "bat guano vs mouse droppings crumble test, histoplasmosis" },
    { url: "/wildlife-removal/raccoon-removal/", about: "raccoon in attic: signs, risks, what a pro does" },
    { url: "/wildlife-removal/squirrel-removal/", about: "squirrels in attic: signs, don't seal babies in" },
    { url: "/wildlife-removal/bat-removal/", about: "bats in attic: exclusion, timing rules" },
    { url: "/wildlife-removal/rodent-control/", about: "mice/rats in walls: signs, sealing entry points" },
    { url: "/wildlife-removal/opossum-removal/", about: "opossum under deck/house" },
    { url: "/wildlife-removal/skunk-removal/", about: "skunk under porch/shed" },
    { url: "/wildlife-removal/snake-removal/", about: "snake in house/garage" },
    { url: "/wildlife-removal/bird-removal/", about: "birds in vents/attic" },
    { url: "/wildlife-removal/mole-control/", about: "moles in yard" },
    { url: "/pest-control/ant-control/", about: "ants in kitchen/walls, why sprays fail" },
    { url: "/pest-control/cockroach-control/", about: "roaches, German cockroaches" }
  ],

  // Calls the offer does NOT pay for: never draft for these
  rejectTopics: ["bed bugs", "termites", "wasps", "bees", "hornets", "fleas", "ticks", "mosquitoes", "commercial", "restaurant", "warehouse", "mobile home"],

  models: { score: process.env.SCORE_MODEL || "claude-haiku-5-5", draft: process.env.DRAFT_MODEL || "claude-sonnet-5-5" }
};
