// Offline test: mocks Reddit, Claude and Telegram to check the pipeline logic.
process.env.TELEGRAM_BOT_TOKEN = "x"; process.env.TELEGRAM_CHAT_ID = "1";
process.env.DATA_DIR = require("path").join(__dirname, ".tmp"); require("fs").rmSync(process.env.DATA_DIR, { recursive: true, force: true });
const reddit = require("../src/reddit"), claude = require("../src/claude"), tg = require("../src/telegram");
const now = Date.now();
const posts = [
  { id: "reddit_a", source: "reddit", sub: "homeowners", title: "Thumping in attic every night, found big droppings", body: "Ohio, sounds heavy", url: "u1", created: now - 36e5, comments: 3 },
  { id: "reddit_b", source: "reddit", sub: "homeowners", title: "Bed bugs in my apartment", body: "", url: "u2", created: now - 36e5, comments: 2 },
  { id: "reddit_c", source: "reddit", sub: "DIY", title: "Old post about mice", body: "", url: "u3", created: now - 72 * 36e5, comments: 1 },
];
reddit.search = async () => posts; reddit.newIn = async () => []; reddit.rules = async () => "";
claude.score = async (t) => ({ relevant: true, live_problem: true, us_likely: true, category: "wildlife", reject_reason: null, page: "/guides/raccoon-poop/", why: "raccoon latrine likely" });
claude.draft = async (t, p, l) => `draft for ${t.id} link=${l}`;
const sent = []; tg.sendItem = async (it) => sent.push(it);
require("../src/engine").scan().then((n) => {
  console.log("sent", n, sent.map((s) => `${s.id} withLink=${s.withLink}`));
  if (n !== 1 || sent[0].id !== "reddit_a") { console.error("FAIL"); process.exit(1); }
  console.log("PASS");
});
