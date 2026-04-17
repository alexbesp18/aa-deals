# Manual Actions — AA Rehaul 2026-04-16

User-gated steps. In priority order. Check off as you go.

---

## 🟢 No longer needed (completed automatically)

- ~~Expose `aa_tools` schema in Dashboard~~ — `register_exposed_schema('aa_tools')` succeeded; portal scraper writes successfully.
- ~~Kill zombie Vercel projects~~ — 4 killed today.
- ~~Kill Railway projects~~ — 6 killed today (incl. `us-hotel-scraper`). Railway account = 0 projects.
- ~~Kill DigitalOcean droplet~~ — you destroyed `ubuntu-s-1vcpu-1gb-sfo2-01` today.
- ~~Fix 12 broken Agoda place IDs~~ — removed from scraper, 2,089 polluted rows deleted.

---

## 🟡 Pending (optional, low-urgency)

### 1. Capture SimplyMiles session (only if you want SimplyMiles stacking)
Currently disabled (`.github/workflows/scrape-simplymiles.yml.disabled`) so you don't get failed cron emails. To activate:
```bash
cd ~/projects/aa-deals
pip install playwright && playwright install chromium
python scripts/capture_session.py
# Browser opens → log in with AA + MFA → press Enter
# Script prints a 'gh secret set' command — paste it
mv .github/workflows/scrape-simplymiles.yml.disabled .github/workflows/scrape-simplymiles.yml
git add -A && git commit -m "enable simplymiles" && git push
```
**Recurring**: repeat every 5-7 days. **Skip entirely** if you're not using SimplyMiles stacking — your main LP play is AA hotels, not portal/card-linked offers.
- **Time**: 2 min + weekly refresh

### 2. Enable daily digest (Resend or migrate to Telegram)
Currently disabled (`.github/workflows/health-digest.yml.disabled`). Two options:

**Option A — Resend** (email):
```bash
gh secret set RESEND_API_KEY --body "re_..." -R alexbesp18/aa-deals
gh secret set DIGEST_TO --body "alexbespalovtx@gmail.com" -R alexbesp18/aa-deals
mv .github/workflows/health-digest.yml.disabled .github/workflows/health-digest.yml
```

**Option B — Telegram** (requires migrating `scripts/digest.py` to use Telegram API; pattern exists in other repos like `miner-capitulation-alerts/lib/telegram.py`). ~30 min work. Reuses `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` you already have in cc-tracker/dylan-tracker.

- **Time**: 2 min (Resend) or 30 min (Telegram migration)

### 3. Rotate service role key (deferred per your decision)
- Current risk: 4 deleted Vercel zombies held copies of this key (Dec 2025 – March 2026)
- To rotate: Dashboard → Settings → API → "Reset `service_role` secret" → give me the new key → I propagate to Vercel/GH secrets/local .env

### 4. Remove `aa_scraper` from Dashboard Exposed Schemas (after 2026-04-23)
7-day canary started 2026-04-16 (writes revoked). If no permission-denied errors in Supabase logs by 2026-04-23, safe to drop via `docs/rehaul-plan-deepened-2026-04-16.md` §PKT-009.

### 5. AA Hotels nerf verification
Book one $100-200 stay. Wait for LP credit to post (1-2 weeks). Compare actual LP vs `aa_hotels.deals.total_miles` prediction. Confirms whether 10K cap (1-3 nights) + 15K cap (4+ nights) math actually holds.

### 6. Pick 1-2 corrected Agoda place IDs (optional, high value)
The 12 cities I removed (Cleveland, Indianapolis, Cincinnati, Columbus OH, Milwaukee, Pittsburgh, Charlotte, Raleigh, Tucson, Albuquerque, Charleston SC, Savannah GA, Washington DC, Minneapolis, Memphis, Fort Lauderdale, Maui) are all "Detroit-class" mid-size markets likely to yield 30x+ Hilton sub-brand gems.

Quickest fix: search `https://www.agoda.com/?s=<city>` → inspect the page URL for `city=<ID>` → send me the ID → I verify + re-add. Each city = 1 min.

Start with Cincinnati or Columbus OH (cold Midwest + mid-size = high probability of Detroit-HGI-class finds).

---

## ✅ What shipped in this session

**Infrastructure cleaned**:
- ✅ 6 Railway projects killed (us-hotel-scraper, heroic-connection, desirable-patience, laudable-optimism, captivating-youth, options-tracker)
- ✅ 1 DO droplet destroyed (aa-scraper VPS, idle since Jan)
- ✅ 4 Vercel zombies deleted (quick_aa_hotels, aa_streak_optimizer, us_hotel_scraper, 002-aa-streak-optimizer)
- ✅ Railway: 0 projects. DO: 0 droplets. Savings: ~$430/yr.

**Data integrity**:
- ✅ PKT-001: RLS enabled + forced on `aa_hotels.deals` and `scrape_progress`
- ✅ PKT-003: `aa_tools` schema (4 tables + view) with RLS from day one
- ✅ 12 broken Agoda place IDs removed from scraper (2,089 polluted rows deleted)
- ✅ `sub_brand` generated column + 3 partial indexes
- ✅ `country_code` column with backfill (US/state collision fixed)
- ✅ `aa_hotels.deals_best` view (1 row per property at best yield)
- ✅ `upsert_batch` error handling (fail-loud instead of silent)
- ✅ `aa_scraper` writes revoked (canary for 7-day drop)

**Scrapers**:
- ✅ Hotels scraper: healthy, running daily + weekly
- ✅ Portal scraper: running every 6h, 1,004 merchants live in `aa_tools.portal_rates`
- ✅ Lever-scraper (job-scrapers repo): migrated from Railway to GH Actions daily
- ⏸️ SimplyMiles: disabled pending user cookie capture
- ⏸️ Daily digest: disabled pending Resend/Telegram decision

**Dashboard (https://aa-deals.vercel.app)**:
- ✅ Default: 30x+ yield, US-only, all brands
- ✅ Region filter (US / International / All)
- ✅ Brand Mode: all / hilton / sub_brand
- ✅ ⭐ sub-brand gems section (top 2 per sub-brand, dynamic)
- ✅ +2.5k HH bonus badge (Hilton promo Apr 7–Dec 31 2026)
- ✅ 1 row per property (no more 60-row-same-hotel pollution)
- ✅ `/stacks` route (awaiting SimplyMiles data)

**Documentation**:
- ✅ CLAUDE.md refreshed
- ✅ `docs/rehaul-plan-2026-04-16.md` + `-deepened` version
- ✅ `docs/subbrand-expansion-plan-deepened-2026-04-16.md`
- ✅ `docs/preserved-gems.md` (Cartera API, SM auth, parsers)
- ✅ This file

---

## Inventory status (2026-04-16, after all fixes)

- **US 30x+ unique properties**: 24 — Vegas Caesars (7), Detroit HGI (1), Dallas-area (2), Madison WI, Winston-Salem NC, Galveston TX, Myrtle Beach SC, etc.
- **US 25x+ unique properties**: 191 — massive backup pool
- **International 30x+ unique properties**: 50 — available via Region filter

**Bottom line**: supply side covers your 20-stay goal with margin. Execution is now in your hands.
