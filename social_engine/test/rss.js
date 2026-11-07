const { parseAtom } = require("../src/reddit");
const xml = `<feed><entry><author><name>/u/x</name></author><category term="homeowners" label="r/homeowners"/><content type="html">&lt;!-- SC_OFF --&gt;&lt;div class=&quot;md&quot;&gt;&lt;p&gt;Loud thumping in attic &amp;amp; droppings&lt;/p&gt;&lt;/div&gt; submitted by /u/x</content><id>t3_abc123</id><link href="https://www.reddit.com/r/homeowners/comments/abc123/x/"/><updated>2026-11-04T08:00:00+00:00</updated><published>2026-11-04T07:55:00+00:00</published><title>Raccoon in attic?</title></entry></feed>`;
const [p] = parseAtom(xml); console.log(p);
if (p.id !== "reddit_abc123" || p.sub !== "homeowners" || !p.body.includes("thumping") || isNaN(p.created)) { console.error("FAIL"); process.exit(1); }
console.log("PASS");
