@~/projects/_groups/business/CLAUDE.md

# AA Hotel Deals Dashboard

One-pager for status-chasing 25-30x+ yield AA Advantage hotel redemptions. Current goal: reach AA Executive Platinum (200K LP) via ~20-25 hotel stays in 2026.

**Live**: https://aa-deals.vercel.app
**Repo**: https://github.com/alexbesp18/aa-deals

## North star

Earn 200K AA Loyalty Points by Dec 31, 2026 via physical-check-in AA hotel bookings at **25x+ minimum yield**, preferring 30x+. Strategy: 4-5 Vegas Caesars weekends × 2-3 stays each + regional Texas Hilton sub-brand drives + opportunistic cap-hits elsewhere. Total spend ~$5-8K.

## Commands

```bash
npm run dev          # Local dev
npm run build        # Production build
pnpm lint            # ESLint
cd scraper && pip install -r requirements.txt && python scrape.py daily   # Scraper
```

## Architecture

```
User → Vercel (Next.js 16, Server Components) → Supabase aa_hotels + aa_tools
                                                    ↑
GitHub Actions crons → Python scrapers → Webshare proxy → AA Hotels API → Supabase
  • scrape.yml          daily top-20 @ 10 UTC, weekly full @ Sun 08 UTC
  • scrape-portal.yml   every 6h :17 (aa_tools.portal_rates, 1,004 merchants)
  • scrape-simplymiles.yml.disabled   (needs user to push SIMPLYMILES_SESSION_B64)
  • health-digest.yml.disabled        (needs user to push RESEND_API_KEY or migrate to Telegram)
```

### Stack
- **Frontend**: Next.js 16 App Router, Server Components, Server Actions, Tailwind 4
- **Data**: Supabase — `aa_hotels.deals` (85K rows) + `aa_hotels.scrape_progress` + `aa_tools.{portal_rates, portal_rates_history, sm_offers, session_state, stack_view}`
- **Scraper**: Python 3.12, async httpx, 139 cities (after removing 12 broken Agoda IDs 2026-04-16), 90 days ahead
- **Proxy**: Webshare rotating residential (each request = fresh IP)
- **Auth**: Server Components use `SUPABASE_SERVICE_ROLE_KEY` via `import "server-only"`. RLS on aa_hotels + aa_tools (deny anon/authenticated, service-role bypass).

### Data flow
1. Scraper checks `scrape_progress` for cities done today
2. For each remaining city: 90 dates in parallel (semaphore=50)
3. Filters yield ≥ 15x, upserts to `deals` (excludes `is_booked` to preserve booking flag)
4. Dashboard reads `aa_hotels.deals_best` view (1 row per hotel-state at best yield)

### Key design decisions
- **Dashboard floor**: 30x+ target, 25x+ backup. Never shows <25x. User's no-compromise floor.
- **Region default**: US only. International available via filter (50 unique 30x+ intl properties if user wants a Vietnam/Bangkok/Riyadh run).
- **Dedup view**: `aa_hotels.deals_best` uses `DISTINCT ON (hotel_name, state)` — main table shows 1 row per property; prevents flood of 60 same-hotel date variants.
- **Generated sub_brand column**: classifies Hampton/Homewood/HGI/DoubleTree/Embassy/Tru/Home2 at INSERT (excludes timeshare + Curio/LXR). Indexed for fast filtering.
- **⭐ gem section**: dynamic top 2 per sub-brand at 30x+, US only. Surfaces Detroit HGI-class finds automatically.
- **+2.5k HH badge**: Hampton/HGI/Tru stays in US, Apr 7 – Dec 31 2026 (Hilton Honors promo).
- **Broken Agoda place ID defense**: removed 12 cities (Washington DC, Minneapolis, Cleveland, Indianapolis, Cincinnati, Columbus, Tulsa, Savannah, Fort Lauderdale, Maui, Memphis, Fes) whose IDs resolved to Spain/UK/Chile/Germany. See commit d07548a.

### Database schema (aa_hotels)

```sql
deals (
  id BIGINT PK,
  hotel_name TEXT, brand TEXT, sub_brand TEXT GENERATED STORED,
  city_name TEXT, state TEXT, stars INT,
  check_in DATE, check_out DATE, nights INT,
  total_cost NUMERIC, total_miles INT, yield_ratio NUMERIC,
  url TEXT, agoda_hotel_id TEXT, is_booked BOOLEAN DEFAULT false,
  scraped_at TIMESTAMPTZ, created_at TIMESTAMPTZ,
  UNIQUE (hotel_name, check_in, check_out)
)
-- Indexes: idx_deals_bookable_state_yield (partial), idx_deals_subbrand_yield (partial),
--         idx_deals_30x_subbrand (partial), all WHERE is_booked=false

scrape_progress (
  city TEXT, state TEXT, scraped_date DATE, deals_found INT,
  completed_at TIMESTAMPTZ, PK (city, state, scraped_date)
)

deals_best VIEW  -- SELECT DISTINCT ON (hotel_name, state) ordered by yield DESC, cost ASC
```

## Current inventory snapshot (2026-04-16)

- **US 30x+ unique properties**: 24 (enough for 20 stays with margin)
- **US 25x+ unique properties**: 191 (massive backup pool)
- **International 30x+ unique properties**: 50 (optional — Vietnam, Bangkok, Riyadh, etc.)
- **Top US 30x+ hotels**: Vegas Caesars (Harrah's, LINQ, Horseshoe, Conrad, Rio, Paris, Mardi Gras), Detroit HGI Metro Airport (36.67x, $162), DFW area (Best Western Plus, Holiday Inn Garland), Madison WI (Econo Lodge), Winston-Salem (Best Western Plus), Galveston (Best Western Plus), Myrtle Beach (Caravelle)

## Secrets / Env Vars

| Secret | Location | Purpose | Status |
|--------|----------|---------|--------|
| `SUPABASE_URL` | Vercel + GH Actions | Supabase project URL | ✅ Active |
| `SUPABASE_SERVICE_ROLE_KEY` | Vercel + GH Actions | Service role | ✅ Active |
| `PROXY_USERNAME` / `PROXY_PASSWORD` | GH Actions | Webshare residential proxy | ✅ Active |
| `SIMPLYMILES_SESSION_B64` | GH Actions | Cookie JSON for SM scraper | ⏳ Pending user capture via `scripts/capture_session.py` |
| `RESEND_API_KEY` | GH Actions | Digest email | ⏳ Or migrate digest to Telegram (other projects use it) |

## Open follow-ups

- **Broken IDs → resolve manually**: 12 US cities removed for bad Agoda IDs. Re-add with correct IDs when bored (Cleveland, Indianapolis, Cincinnati, Columbus, etc. — all probable Detroit-class gem territory).
- **`aa_scraper` drop**: Canary revoke applied today. After 2026-04-23, if no permission errors in logs, follow the guarded 7-step drop from `docs/rehaul-plan-deepened-2026-04-16.md` §PKT-009.
- **Pace tracker**: aspirational. "You're at X LP / 200K · need Y more stays at $Z".
- **Bookings log**: aspirational. Track actual LP credit vs predicted to catch any AA nerf changes early.

## Related docs
- `docs/rehaul-plan-deepened-2026-04-16.md` — strategic synthesis
- `docs/subbrand-expansion-plan-deepened-2026-04-16.md` — Layer 1/2/3 plan + 7-agent deepening
- `docs/preserved-gems.md` — SimplyMiles auth flow, Cartera API, parser recipes
- `docs/manual-actions-2026-04-16.md` — user-gated steps
