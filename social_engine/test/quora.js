// Offline: Quora question URL normalisation + engine treats Quora items as answerable regardless of age.
const assert = require("assert");
process.env.DATA_DIR = require("path").join(__dirname, ".tmp-q"); require("fs").rmSync(process.env.DATA_DIR, { recursive: true, force: true });
const { questionUrl } = require("../src/quora");
assert.equal(questionUrl("https://www.quora.com/What-is-a-good-gift-for-dad/answer/Jane-Doe"), "https://www.quora.com/What-is-a-good-gift-for-dad");
assert.equal(questionUrl("https://www.quora.com/profile/Jane-Doe"), null);
assert.equal(questionUrl("https://example.com/x"), null);
const engine = require("../src/engine");
assert.equal(engine.prefilter({ id: "quora_x", source: "quora", title: "Gift for dad?", body: "", created: Date.now() - 999 * 36e5, comments: 0 }), true);
console.log("PASS quora");
