# Link Engine v2 — Product Spec

Decisions agreed with the owner on 2026-11-05. First client project: **tshirtcrisis.com** (new site, no rankings yet). Seed competitor: **crazydogtshirts.com**.

## Goal
Earn real backlinks of every kind, both self-published and editorial, with heavy automation and minimal human input. Must work across multiple clients and brands, each as a separate project. No spam: no captcha solving, no stealth form submission, no sockpuppets.

## Platform
- **Web app on Railway.** It has three services: `web` (FastAPI + React dashboard), `worker` (job queue + scheduler) and **Postgres**. Railway's disk is wiped on every deploy, so all state goes in Postgres. Large files go on a Railway volume.
- Rebuild as a web app. Port the useful logic from the PyQt app: link monitor, IMAP handling, journalist CRM and analyzers. Drop `form_submitter.py` and `captcha_api.py`.
- Claude API writes all content. Default model is `claude-sonnet-5-5`, with `claude-opus-5-5` for important pieces (PR pitches, pillar articles). The model can be set per task.

## Users & tenancy
- Each client brand is a project with its own settings, accounts, inboxes, limits and quality thresholds.
- Roles: **admin**, **team** (all projects), and **client** (read-only view of their own project).
- Secrets (API keys, SMTP/IMAP passwords, OAuth tokens) are encrypted at rest.

## Brand voice
- Auto-built from the brand's site (homepage, products, About page) into a profile covering tone, audience, words to use and avoid, products and example posts. You edit it once, and every piece of generated content uses it.

## Discovery
- **Competitors:** discovered automatically from Ahrefs organic competitors and the domains ranking for seed keywords. **If too little data is found (new sites), the tool stops and asks for at least one competitor that has enough data**, then continues. You confirm the list.
- **Data sources (all pluggable):** Ahrefs API, DataForSEO, free sources (SERP API, Common Crawl, on-page crawl), and Google Search Console per client.
- **Quality filter:** thresholds are set per project (min DR/traffic, relevance, link-seller signals, blocklists).

## Strategies
1. **Self-publish replication.** Classify competitor backlinks by source type (Medium, Quora, Reddit, Pinterest, Tumblr, profiles, directories, etc.) and queue up the same kinds of posts for the brand.
2. **Link gap + outreach.** Sites linking to 2+ competitors but not to us.
3. **Digital PR / journalist requests.** Qwoted, Featured, SourceBottle, #journorequest.
4. **Unlinked mentions, broken competitor pages, resource pages.**
5. **AI-recommended extras.** Claude proposes further link types based on the competitor profile.

## Content & posting
- Content types: articles and guides, Q&A answers, visual posts (Pinterest, Tumblr, Flickr), profiles and directories, plus AI-suggested types.
- Posts as **brand and founder accounts** only, stored per project.
- Posting uses official APIs where they exist (Medium, Tumblr, Blogger, WordPress.com, Dev.to, Reddit, Pinterest). Otherwise posting is **assisted**: the tool prepares everything and you paste it in with one click (e.g. Quora).
- **Approval queue by default.** Each channel can be switched to auto-publish once it has a good track record.

## Email & outreach
- **Sending through Brevo.** Replies come in through Brevo inbound parsing or IMAP on the outreach mailbox.
- **Sent from outreach subdomains** (e.g. `outreach.tshirtcrisis.com`). The tool checks SPF/DKIM/DMARC before a subdomain can send.
- **Default limits per inbox (all editable per project and per inbox):** start at 5 a day and ramp to a max of 30 a day over 4 weeks, random 3–12 minute gaps, business hours only, 1 follow-up after 5 days, auto-pause if bounces go above 3%. Every email has an unsubscribe link, a `List-Unsubscribe` header and a physical address.
- **Replies:** Claude labels each one (interested / wants payment / not interested / out of office / link placed), stops the follow-ups, and drafts a response for your one-click approval.

## Dashboard
- Pipeline funnel (found → approved → published or pitched → replied → live)
- Links earned over time (by type, dofollow vs nofollow, DR, links lost)
- Approval queue and alerts (inbox paused, bounce spike, link removed, API budget low)
- Results (referring domains, DR, traffic, keywords from Ahrefs and GSC)
- Other at-a-glance views to make running it easier

## Alerts
- Daily email digest, plus Slack / WhatsApp / Telegram for urgent items (journalist requests, positive replies, inbox paused).

## Growth OS scope (added 2026-11-06)
The tool is more than links now. It's a set of marketing modules, run by **playbooks**, for two kinds of project:
- **Launch-stage** (new sites like tshirtcrisis.com): a 72-hour sprint, then a first-30-days plan. The focus is self-publishing, creators, social, gift-guide PR and measurement.
- **Growth-stage** (established brands): a 90-day plan covering link gap, digital PR and data stories, broken links, unlinked mentions, a creator affiliate program and podcasts.

Modules: foundation and measurement, store, social, creators, links, PR, community, email, ads. Every playbook task has an owner:
- `auto`: the tool does it
- `approve`: the tool drafts it and you approve
- `human`: only you can do it, e.g. ad spend or store theme changes

### What changed from ChatGPT's 72-hour plan
- **Day 0 measurement and free channels added:** GA4, Meta Pixel + Conversions API, UTMs per channel and per creator, free Google Merchant Center listings, GSC/Bing, and Pinterest catalog sync. Without these you can't tell what worked.
- **Links run in parallel from Day 1:** claimed brand profiles give consistent business details and entity signals, plus the first links.
- **Creators:** the tool discovers and scores them by engagement rate. Each gets a unique code and UTM link for attribution, we ask for UGC reuse rights, and FTC disclosure is required.
- **Season-aware** (`app/seasons.py`): the angles change automatically with the US retail calendar.
- **Discount discipline:** when BFCM is less than 28 days away, the launch offer becomes a free gift or bundle instead of %-off, so the BFCM sale still feels like an event.
- **Gift-guide PR sprint, time-boxed:** editors fill holiday guides early.
- **Optional Google Shopping/PMax** alongside Meta for gift-intent searches.

## Extension points ("room for upgrades")
- `app/registry.py`: providers, strategies, channels and playbooks are plugins. Add a module and decorate it; nothing else changes.
- `config.DEFAULTS` + per-project overrides: new settings need no migration.
- `Opportunity.kind` and `data` JSON: new tactics need no schema change.
- The DB-backed job queue (SKIP LOCKED) can be swapped for Redis/arq later.
- The JSON API (`/api/*`) can later back a React UI or client portal.
- Planned upgrades are listed as `TODO(upgrade)` in the code, e.g. Alembic migrations, API publishers, GSC, Brevo, real user accounts.

## Roadmap
- **v1 — Self-publish engine:** projects and brand voice, competitor discovery and backlink pull, classifying links as self-publishable vs editorial, content generation and approval queue, API posting and assisted posting, link tracking, dashboard, digest.
- **v2 — Editorial:** Brevo outreach, rate limiting and warm-up, reply sorting, link gap, mentions, broken links, resource pages.
- **v3 — Digital PR:** journalist-request monitoring, expert-answer drafting, chat alerts.

## Platform structure (decided 2026-11-07)
One platform with **two modules** sharing users, projects, brand voice, approvals and Claude prompts:
1. **Links:** self-publish (profiles, directories, deal/affiliate listings, Web 2.0, own WordPress hub), outreach + PR (contacts, Brevo sequences, replies, journalist requests, gift guides), link monitor.
2. **Social & Community:** Pinterest, Facebook, Instagram, Reddit, Quora (TikTok later). The Pest Help `traffic-engine` (Node, Telegram approvals, Reddit RSS finder, Pinterest) **is reused as-is, not rebuilt**: extend its existing code for multiple projects and connect it to this dashboard through a small API.

Project **type** (ecommerce / affiliate / local / saas) switches playbooks and link strategies.
**Team:** roles admin / manager / builder / client; every draft, approval, publish and earned link is credited to a user; team dashboard shows progress per person.
**Build order:** 1) users, roles, credit tracking 2) project types + Pest Help project 3) outreach + PR 4) self-publish publishing + link monitor 5) Social & Community module.
**Human time:** about 1 hr/day per site (approvals, Reddit/Quora posting, outreach replies) + one-time account and profile setup.
