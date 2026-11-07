# Social & Community engine (module 2 of the Buzz Scouts Engine)

Lives inside the link-engine repo. One Railway service per brand, same code; `PROJECT=<name>` loads `configs/<name>.js`
(no PROJECT = ThePestHelp defaults in `src/config.js`). The dashboard talks to it through `ENGINE_API_TOKEN`
over Railway's private network (`http://<service>.railway.internal:8080`).

Deploy (from the repo root): `railway up social_engine --path-as-root --service social-<brand> --detach`
New brand: copy `configs/tshirtcrisis.js` -> `configs/<brand>.js`, create a service with a /data volume and
PROJECT, ENGINE_API_TOKEN, ANTHROPIC_API_KEY, TELEGRAM_BOT_TOKEN, PORT=8080, then connect it under Accounts -> social_engine.

---

# ThePestHelp Answer Engine (Reddit)

Every 30 min: finds fresh Reddit threads about attic animals, droppings, mice, roaches etc. → Claude filters to real US homeowner problems the offer pays for → drafts a genuinely helpful reply (guide link in ~1 of 2, with disclosure + UTM) → sends to your Telegram with buttons.

You post the reply yourself (Reddit bans auto-posting), then tap **✅ Posted it**.

## Telegram buttons / commands
- ✅ Posted it · 🔁 Redraft · 🔗/🚫 Toggle link · ❌ Skip
- `/scan` run now · `/stats` counts · `/start` shows your chat ID

## Setup (one time)
1. **Telegram bot:** message @BotFather → `/newbot` → copy token.
2. **Reddit:** no key needed. The engine reads Reddit's public RSS feeds. (Optional: if Reddit approves you under its Responsible Builder Policy, add `REDDIT_CLIENT_ID`/`REDDIT_CLIENT_SECRET` for faster scans with comment counts.)
3. **Anthropic key:** console.anthropic.com → API Keys.
4. **Railway:** New Project → Deploy from GitHub repo → add a **Volume** mounted at `/data` → Variables:
   - `ANTHROPIC_API_KEY`, `TELEGRAM_BOT_TOKEN`
   - `REDDIT_USER_AGENT` = `thepesthelp-answer-engine/1.0 by u/YOURUSERNAME`
5. Deploy → send `/start` to your bot → copy the chat ID → add `TELEGRAM_CHAT_ID` → redeploy. Drafts start arriving.

## Autorun
The 30-min scans and Pinterest posting are **off by default** (still in development). Set `AUTORUN=true` on Railway to turn them on. While off, the bot still responds and `/scan` runs a scan on demand.

## Tuning
`src/config.js`: search phrases, subreddits, link frequency, pages, rejected topics.

## Posting rules (protect the account)
- Use an aged account; comment normally in those subs too. Max ~5–8 answers/day.
- Read each sub's rules; skip links where self-promo is banned (`avoidSubreddits`).
- Edit drafts so they sound like you.

Test offline: `npm test`

## Pinterest engine
Pins live on the site at `thepesthelp.com/pins/` (44 pins, made by `tools/make_pins.py` in the site repo).
- **Now (no API approval needed):** Pinterest → Create → **Bulk create Pins** → upload `pins.csv` (from the site repo, `static/pins/pins.csv`). It schedules 3 pins/day automatically.
- **Later (auto):** create a Pinterest app (developers.pinterest.com), get Standard access, add `PINTEREST_TOKEN` to Railway. The engine then posts `PINS_PER_DAY` (default 3) from `pins.json`.
- Create these 3 boards first (exact names): **Animal Droppings ID**, **Wildlife in the House**, **Home Pest Control Tips**.
