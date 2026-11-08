// Engine settings. Three layers, later wins:
//   1. built-in defaults below (ThePestHelp), or configs/<PROJECT>.js when PROJECT is set
//   2. settings pushed by the Buzz Scouts dashboard (POST /api/config), saved in <DATA_DIR>/config.json
// So a new brand needs no code: the dashboard fills its targets with Claude and pushes them here.
const fs = require("fs"), path = require("path");
const project = (process.env.PROJECT || "").replace(/[^a-z0-9_-]/gi, "");
const DIR = process.env.DATA_DIR || (fs.existsSync("/data") ? "/data" : path.join(__dirname, "..", "data"));
const OVERRIDES = path.join(DIR, "config.json");

const PEST = {
  site: "https://thepesthelp.com",
  pinsUrl: "https://thepesthelp.com/pins/pins.json",
  brand: {
    name: "ThePestHelp",
    offer: "a US referral site that connects homeowners with local pest control and wildlife removal pros",
    relevant: "the poster has (or is asking about) an animal/pest problem in or around their home",
    live_problem: "it's happening now at their house or apartment (not a pet, not curiosity, not a business)",
    persona: "a knowledgeable homeowner who has dealt with pest and wildlife problems",
    rules: "Genuinely answer THEIR situation first: likely culprit, how to tell, what to do now, safety. " +
      "Never claim to be a professional or to have done a specific job. " +
      "Safety: never advise handling wild animals; droppings = wet cleanup, never sweep or vacuum dry (hantavirus, roundworm, histoplasmosis as relevant). Bats: don't seal them in; contact a doctor if bat contact while sleeping. " +
      "Suggest calling a licensed local wildlife/pest pro when it's warranted. " +
      "Never use the words \"free quote\", \"same day\", \"24/7\", \"guarantee\".",
    link_line: "I put together a guide on this, if it helps:",
  },
  scanEveryMinutes: Number(process.env.SCAN_EVERY_MINUTES || 30),
  maxAgeHours: 24,          // ignore older threads
  maxComments: 40,          // crowded threads rarely get seen
  maxDraftsPerScan: 6,      // keep the approval queue small
  linkEveryNth: 2,          // include a link in at most 1 of every N approved answers
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
  subreddits: ["homeowners", "HomeImprovement", "pestcontrol", "whatsthisbug", "Wildlife", "FirstTimeHomeBuyer", "DIY", "RealEstate"],
  avoidSubreddits: ["pestcontrol"],
  quora: false,             // Quora search costs a little per query (DataForSEO); enable per brand
  quoraQueries: [],
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
  rejectTopics: ["bed bugs", "termites", "wasps", "bees", "hornets", "fleas", "ticks", "mosquitoes", "commercial", "restaurant", "warehouse", "mobile home"],
  models: { score: process.env.SCORE_MODEL || "claude-haiku-5-5", draft: process.env.DRAFT_MODEL || "claude-sonnet-5-5" }
};

const base = project && project !== "thepesthelp" ? require("../configs/" + project) : PEST;
const cfg = { ...PEST, ...base, brand: { ...PEST.brand, ...(base.brand || {}) } };

// keys the dashboard may set (anything else is ignored)
const PUSHABLE = ["site", "brand", "queries", "subreddits", "avoidSubreddits", "pages", "rejectTopics", "quora",
  "quoraQueries", "linkEveryNth", "maxDraftsPerScan", "maxAgeHours", "maxComments", "pinsUrl", "dataforseo"];

function applyOverrides(o) {
  for (const k of PUSHABLE) {
    if (o[k] === undefined || o[k] === null) continue;
    if (Array.isArray(o[k]) && !o[k].length) continue;      // empty list = keep the default
    cfg[k] = k === "brand" ? { ...cfg.brand, ...o[k] } : o[k];
  }
}
try { applyOverrides(JSON.parse(fs.readFileSync(OVERRIDES, "utf8"))); } catch {}

cfg.update = (o) => {
  const clean = Object.fromEntries(PUSHABLE.filter((k) => o[k] !== undefined).map((k) => [k, o[k]]));
  fs.mkdirSync(DIR, { recursive: true });
  fs.writeFileSync(OVERRIDES, JSON.stringify(clean, null, 1));
  applyOverrides(clean);
  return clean;
};
cfg.public = () => Object.fromEntries(Object.entries(cfg).filter(([k, v]) => typeof v !== "function" && k !== "dataforseo"));
module.exports = cfg;
