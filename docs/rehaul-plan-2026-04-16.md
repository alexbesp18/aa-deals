# AA Miles/Hotels Rehaul Plan — 2026-04-16

Consolidates 5 codebases into one. Kills DigitalOcean + Railway. Only Vercel + Supabase + GH Actions.

> **⚠️ Verify first**: AA Advantage Hotels was nerfed in 2023 — capped at 10K LP per stay (1-3 nights) or 15K LP per stay (4+ nights). Per-stay, not per-night. The pre-nerf yield math (Middle East 43x, $200-300 sweet spot, non-linear accelerating formula) likely no longer applies. Book one cheap stay and verify actual LP credit before committing to this plan. Source: [One Mile at a Time](https://onemileatatime.com/guides/american-aadvantage-hotels/).

---

## Current state (audit 2026-04-16)

| Status | Item |
|---|---|
| ✅ Active | `aa-deals` — Next.js 16 + Python scraper, Vercel + Supabase `aa_hotels` (87,976 deals, scraped today), GH Actions daily+weekly cron. Healthy. |
| 🧟 Vercel zombie | `quick_aa_hotels` (src repo deleted, last deploy 2025-12-27) |
| 🧟 Vercel zombie | `aa_streak_optimizer` (src repo deleted, last deploy 2026-01-18) |
| 🧟 Vercel zombie | `us_hotel_scraper` (src repo deleted, last deploy 2026-01-18) |
| 🧟 Vercel zombie | `002-aa-streak-optimizer` (last deploy 2026-03-03) |
| 💀 Frozen | Supabase `aa_scraper` schema — 11 tables, 12,652 rows, last write **2026-01-19** |
| ❓ Unknown | DigitalOcean VPS hosting 001-aa-scraper — data writes stopped Jan 19, likely still billing ~$6/mo |
| ❓ Unknown | Railway service for `004-us-hotel-scraper` (3x daily cron) — likely still billing |

---

## Target architecture (convergent across 4 strategists)

```
aa-deals (single repo, public, GH Actions free)
├── app/
│   ├── (hotels)/page.tsx       existing
│   ├── portal/page.tsx         new — eShopping rate tracker
│   ├── simplymiles/page.tsx    new — card-linked offers
│   ├── stacks/page.tsx         new — SQL view joining portal × SM
│   └── admin/page.tsx          new — session age, scrape health
├── scrapers/                   flat, no monorepo nesting
│   ├── hotels.py               existing scrape.py renamed
│   ├── portal.py               extracted from 001
│   ├── simplymiles.py          extracted from 001
│   ├── streak_optimizer.ts     extracted from 002 (~90 LOC)
│   └── lib/                    shared: supabase, normalizer, proxy
└── .github/workflows/
    ├── scrape-hotels.yml       existing — no changes
    ├── scrape-portal.yml       new — every 6h
    ├── scrape-simplymiles.yml  new — every 4h
    ├── refresh-session.yml     new — manual dispatch
    └── health-digest.yml       new — daily Resend email
```

**Supabase**: keep `aa_hotels` (prod). Create fresh `aa_tools` schema for portal + SM. Eventually drop `aa_scraper`.

---

## Kill list

| Asset | Action | Saves |
|---|---|---|
| DigitalOcean VPS | Destroy | ~$72/yr |
| Railway service (004) | Cancel | ~$60/yr |
| Vercel: `quick_aa_hotels` | Delete | stale env vars |
| Vercel: `aa_streak_optimizer` | Delete | stale env vars |
| Vercel: `us_hotel_scraper` | Delete | stale env vars |
| Vercel: `002-aa-streak-optimizer` | Delete | stale env vars |
| `003-quick-aa-hotels/` code | Delete entirely | 0 unique value (template) |
| `004-us-hotel-scraper/` code | Delete entirely | strict subset of aa-deals |
| `001-aa-scraper/` 90% of code | Delete (`alerts/`, `core/database.py` 1603 LOC, 80 tests, etc.) | ~10K LOC bloat |
| `002-aa-streak-optimizer/` shell | Delete Next.js app + duplicate scraper; keep only `lib/optimizer.ts` | |
| `aa_scraper` Supabase schema | Drop after 7-day verify-no-writes (via `guard_schema_drop` proper flow) | 6.3 MB |

**Net: ~97% deletion of dormant code, ~$130/yr saved.**

---

## What to preserve (file-level gems — see `preserved-gems.md` for the code)

- **Cartera API**: endpoint + key for eShopping portal (`001/scrapers/portal.py:52-60`)
- **SimplyMiles auth flow**: manual Playwright login + cookie JSON export (`001/scripts/setup_auth.py`)
- **SimplyMiles API endpoint**: `https://www.simplymiles.com/get-pclo-and-rakuten-offers`
- **SimplyMiles offer parser**: regex for flat_bonus vs per_dollar (`001/simplymiles_api.py:119-178`)
- **Portal miles rate parser**: regex ladder for "X miles/$", "X mi/$", etc (`001/portal.py:143-207`)
- **Portal HTML selectors**: `.mn_rebateV4`, `.mn_elevationOldValue`, `.mn_elevationNewValue`, `.mn_rebateTiered` (`001/portal.py:313-374`)
- **Merchant normalizer + fuzzy match**: rapidfuzz `token_sort_ratio` (`001/core/normalizer.py:17-98`)
- **Stack detector logic**: SM × Portal × CC composition (`001/core/stack_detector.py:68-135`)
- **Streak optimizer**: multi-night sequence picker (`002/lib/optimizer.ts`)
- **Brand pattern dict**: 7 chains × 60+ substrings (`aa-deals/scraper/scrape.py:39-71`) — **already in production code, no extraction needed**
- **Webshare proxy format**: `http://{user}-rotate:{pass}@p.webshare.io:80` — the `-rotate` suffix (`aa-deals/scraper/scrape.py:420`)
- **151-city global list**: yield-pruned (`aa-deals/scraper/scrape.py:85-176`)
- **Schema-exposure tripwire call**: `aa-deals/scraper/scrape.py:280-325`

---

## The SimplyMiles auth problem

SimplyMiles requires authenticated cookies (AA SSO + MFA), expire ~weekly. Runs on Rakuten RCLON network — no public reverse engineering exists. Options:

1. ✅ **GH secret + manual weekly refresh** ($0) — Alex runs local `capture_session.py` (Playwright), pushes cookie JSON to GH secret `SIMPLYMILES_SESSION`. Workflow decodes at runtime. Community-standard.
2. **Supabase `session_state` table + `/admin/session` web paste** ($0) — upgrade path after #1 works.
3. **Browserbase Dev plan** ($20/mo) — managed headless with persistent sessions. Only if #1 proves too fragile.

---

## Cron timeout / rate limit reality

- `aa-deals` repo is **public** → unlimited GH Actions minutes. Keep public.
- New workflows: portal ~3 min/run (every 6h), SimplyMiles ~2 min/run (every 4h), stack-detect ~10s (SQL view), health-digest ~30s (daily). **Total ~70 min/day, still free.**

---

## Migration sequence (each step ends with a kill)

1. **Today, 15 min** — Delete 4 Vercel zombies. Cancel DO droplet. Cancel Railway service.
2. **30 min** — **Manual test**: book one cheap stay, verify actual LP credit matches pre-nerf expectations. Decide if hotels is still worth scraping.
3. **30 min** — Create `aa_tools` schema + RLS + register via tripwire (2-step Dashboard flow per global CLAUDE.md).
4. **1 hr** — Port portal scraper. Add workflow. Verify writes.
5. **2 hr** — Port SimplyMiles. Set up GH secret refresh script. Verify writes.
6. **1 hr** — Stack detector as SQL view (not table; stays fresh by definition).
7. **3-4 hr** — Add 4 dashboard routes (`/portal`, `/simplymiles`, `/stacks`, `/admin`).
8. **30 min** — Resend daily digest workflow.
9. **After 7 days** — If no writes to `aa_scraper`, remove from Dashboard exposed schemas, then drop (`guard_schema_drop` will block unless allow-listed).

**Total: ~10-12 hours focused work** + the LP-cap verification.

---

## Decisions for Alex (before proceeding past step 3)

1. **Verify AA Hotels nerf**: Book one test stay. If yield math is broken, hotels becomes archive-only, and SimplyMiles + Portal become the main play. This changes priorities.
2. **Are you actually using SimplyMiles?** The auth flow + scraper is meaningful work. Skip 001 extraction if the honest answer is "forgot about it for 3 months."
3. **Are you still chasing AA status?** If shifted to other airlines/programs, consider killing aa-deals entirely instead of rehauling.

---

## Strategist Reports (verbatim appendix)

Four CE strategists ran in parallel. Full reports in conversation history:
- **architecture-strategist**: target architecture + migration sequence (above synthesized from this)
- **code-simplicity-reviewer**: kill/keep/merge verdicts per codebase, minimum useful surface area, 97% deletion rate
- **pattern-recognition-specialist**: capability matrix, file:line unique-value map, hidden gems, 10 anti-patterns seen
- **best-practices-researcher**: travel-hacking landscape, AA Hotels nerf discovery, SimplyMiles RCLON finding, Browserbase/Browserless pricing, proven community tools

---

## Audit-day state

- aa-deals: latest scrape 2026-04-16 11:19 UTC (daily top-20, 15,376 deals)
- aa_hotels.deals: 87,976 rows, 57 MB, RLS disabled ⚠️
- aa_scraper.hotel_rates: last scraped 2026-01-19 03:01 UTC (87 days stale)
- GitHub Actions for aa-deals: 14 of 15 recent runs successful
- aa-deals.vercel.app: HTTP 200, 2.8s, 127KB (healthy)
