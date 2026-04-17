# Sub-Brand Expansion Plan — DEEPENED 2026-04-16

Output of 7 parallel research/review agents on the 3-layer US sub-brand expansion plan. Where deepening contradicts the original plan, the deepening wins — findings were empirically validated against live AA Hotels API + Supabase data.

---

## Enhancement Summary

**Deepened on**: 2026-04-16
**Layers**: 3 (Dashboard defaults · Scraper expansion · Search configs)
**Research agents used**: Explore×3 (per layer) + performance-oracle + data-integrity-guardian + best-practices-researcher + supabase-postgres-best-practices + domain-patterns

### Key improvements

1. **CRITICAL BUG DISCOVERED — broken Agoda place IDs in existing CITIES list.** 7+ cities in the current scraper resolve to wrong locations (Cadiz Spain instead of Indianapolis, Jena Germany instead of Columbus, Bolton UK instead of Cincinnati, etc.). "Zero deals" from those cities was a bug signature, not yield reality. **Fixing these is free (no bandwidth), may unlock 7-10 more Detroit-style gems.**
2. **Layer 3 hypothesis empirically validated**: LP earning DOES vary by nights. 1N=2,700, 2N=6,800 LP at same property — 2-night stays earn 2.5x, not 2x. Layer 3 is additive. BUT skip day-of-week patterns (not worth 2x volume) and skip 4+ nights (hits 15K cap, low ROI).
3. **Pre-existing data integrity risk**: current unique key `(hotel_name, check_in, check_out)` allows cross-city collisions (two "Hampton Inn & Suites" in different cities). Must be fixed before Layer 3 — include `agoda_hotel_id` in new unique key.
4. **Postgres generated column for `sub_brand`**: STORED computation classifies once at INSERT, enables indexed filtering (vs 7× ILIKE on every dashboard render).
5. **Proxy budget is tighter than estimated**: +40% cities would exceed 3 GB Webshare cap. Options documented below.
6. **Next.js 16 Cache Components + Suspense** replaces `force-dynamic` — dramatic TTFB improvement while scraper data refreshes every 6h.

### New considerations discovered

- **Hilton Honors devaluation Jan 2026**: Homewood + Spark base earning cut from 10x → 5x (direct Hilton, not AAH). Signal: AAH commission may INCREASE at these brands to fill rooms.
- **Hilton promo April-Dec 2026**: +2,500 Honors bonus per stay at Hampton/HGI/Spark/Tru in US. Stacks with AA LP. Worth tagging stays that qualify.
- **`get_top_cities()` bias risk (Layer 3)**: `LIMIT 1000` in scrape.py:358 will bias toward cities with most config permutations when we 3x the config fanout. Needs `DISTINCT ON`.
- **Silent upsert errors**: scrape.py:335 `upsert_batch` has no try/except. If a schema/key mismatch happens mid-migration, the scraper quietly writes zero rows. Must add error handling.
- **Rocketmiles comparison dead** (2023 devaluation). Don't build fallback logic.

---

## Revised execution sequence

```
Priority 0 (free, high value):      Fix 7+ broken Agoda place IDs       [30 min]
Priority 1 (dashboard-only):        Layer 1 filter redesign             [2 hr]
Priority 2 (schema + scraper):      Data integrity cleanup              [1 hr]
Priority 3 (infra-dependent):       Layer 2 expansion (30, not 60)      [3 hr + waits]
Priority 4 (after Layer 2 stable):  Layer 3 config scraping             [3 hr]
```

Old plan had Layer 1 → 2 → 3. New plan inserts **Priority 0 (broken IDs)** and **Priority 2 (unique key fix)** as prerequisites.

---

## Priority 0 — Fix broken Agoda place IDs (NEW)

**Discovery**: the best-practices-researcher agent probed AA Hotels' API for every existing city in `scrape.py` CITIES list. Several IDs don't resolve to the intended city.

### Confirmed broken IDs (probe against `place.id` and `place.city` fields)

| City expected | ID in scrape.py | Actual place resolved |
|---|---|---|
| Cleveland OH | 1141 | Mason OH |
| Indianapolis IN | 5270 | Cadiz, Spain |
| Cincinnati OH | 4614 | Bolton, UK |
| Columbus OH | 7621 | Jena, Germany |
| Savannah GA | 5097 | Heiligenblut, Austria |
| Milwaukee WI | 6052 | null place |
| Pittsburgh PA | 4040 | null place |
| Charlotte NC | 2339 | null place |
| Raleigh NC | 11206 | null place |
| Tucson AZ | 7787 | null place |
| Albuquerque NM | 14437 | null place |
| Charleston SC | 9050 | null place |

**Impact**: these cities have been scraped for months returning empty/wrong data. Fixing them costs ZERO additional proxy bandwidth (same search count).

### Fix strategy (robust, not manual lookup)

Replace manual ID mapping with runtime city resolution via AA Hotels' autocomplete endpoint. Pseudo:

```python
def resolve_place_id(city: str, state: str) -> str | None:
    """Query AA Hotels with query= only, let server resolve place_id."""
    r = httpx.get(
        f"https://www.aadvantagehotels.com/searchRequest",
        params={
            "adults": 2,
            "checkIn": tomorrow, "checkOut": tomorrow+1,
            "query": f"{city}, {state}",
            "locationType": "CITY",
            "language": "en", "currency": "USD", "source": "AGODA",
        },
        headers=HEADERS, timeout=20,
    )
    data = r.json()
    place = data.get("place", {})
    resolved_id = place.get("id", "").replace("AGODA_CITY|", "")
    resolved_city = place.get("city", "")
    # Validate: city name similarity check
    if city.lower() in resolved_city.lower():
        return resolved_id
    return None  # broken, log + skip
```

Run once, write corrected IDs back to CITIES list. Cache in a `cities_validated.json` so we don't re-resolve on every scrape.

### Acceptance
- [ ] All 151 existing CITIES entries have their `place_id` validated against the `place.city` field returned by AA Hotels
- [ ] Broken entries replaced with correct IDs or removed
- [ ] Each city has ≥1 non-error response in a validation run
- [ ] Commit includes new `scripts/validate_cities.py` for future use

### Rollback
- Git revert — the CITIES list change is a single file edit

---

## Priority 1 — Layer 1: Dashboard filter redesign

Original plan: change defaults + add sub-brand filter + surface Detroit gem.

### Research insights applied

**Filter UX decision** (from domain-patterns + Layer 1 Explore):
- Keep native `<form method="get">` — filter is navigation, not mutation. Server Action would be an anti-pattern here.
- Replace `brand` dropdown with a `brand_mode` radio group: `all` / `hilton` / `sub_brand`
- Add `sub_brand_only` as a derived URL param (or encode via `brand_mode`)
- **URL schema**: `?min_yield=25&brand_mode=sub_brand&state=all`

**Don't re-use `brand` param name** — `brand_mode=sub_brand` is semantically distinct.

**Server-compute the "⭐ gem" badge** — pass `is_gem: bool` as a prop per row. Don't ship classification logic to client.

**Replace `force-dynamic` with Cache Components (Next.js 16)**:
```tsx
// app/page.tsx — wrap the deals query in 'use cache'
async function getDeals(params: Filters) {
  'use cache'
  cacheTag('deals')
  cacheLife('hours') // scraper refreshes every 6h
  // ... Supabase query
}
```
Scraper after each run: `revalidateTag('deals')`. Dramatic TTFB win over force-dynamic.

**Wrap the table in `<Suspense>`** — filter shell renders instant, table streams.

**Zod schema for search params**:
```ts
// lib/schemas/filters.ts
export const FiltersSchema = z.object({
  min_yield: z.coerce.number().int().min(10).max(100).default(25),
  brand_mode: z.enum(['all','hilton','sub_brand']).default('all'),
  state: z.string().length(2).or(z.literal('all')).default('all'),
});
```

**Accessibility upgrades**:
- Wrap filter in `<fieldset><legend>`
- Each label needs `htmlFor` matched to input `id`
- `aria-live="polite"` on the deal count
- Keyboard-visible focus rings (check tailwind preset)

### Dynamic "⭐ top sub-brand gem" SQL

Replaces the hardcoded Detroit HGI. Surfaces top 3 per sub-brand class at ≥30x:

```sql
WITH ranked AS (
  SELECT
    id, hotel_name, sub_brand, city_name, state,
    yield_ratio, total_cost, total_miles, check_in, check_out, url,
    ROW_NUMBER() OVER (
      PARTITION BY sub_brand ORDER BY yield_ratio DESC, total_cost ASC
    ) AS rank_in_sub_brand
  FROM aa_hotels.deals
  WHERE is_booked = false
    AND yield_ratio >= 30
    AND check_in >= CURRENT_DATE
    AND sub_brand IS NOT NULL
)
SELECT *, '⭐ ' || sub_brand || ' gem' AS gem_label
FROM ranked
WHERE rank_in_sub_brand <= 3
ORDER BY yield_ratio DESC, total_cost ASC;
```

Cheap query at 87K rows (~2-5 ms with the generated column + partial index described below).

### Layer 1 sort order change

Current: `ORDER BY yield_ratio DESC`.
New: `ORDER BY yield_ratio DESC, total_cost ASC`.
Rationale: at 32-37x yield, $162 is psychologically safer than $188 for the walk-in strategy. Cheaper floats to top of each yield tier.

### Edge case the original plan missed

**"Just-booked gem" disappears silently**: if user books the Detroit HGI deal and `is_booked=true`, the next dashboard render loses the gem. Instead of "no gems" empty state, surface it with a "⚠️ just booked" indicator for 24h before hiding. Implementation: `is_booked && booked_at > now() - interval '24 hours'`.

### Acceptance
- [ ] Default `min_yield` = 25, `brand_mode` = all
- [ ] New `/?brand_mode=sub_brand` returns only Hampton/Homewood/HGI/DoubleTree/Embassy/Tru/Home2
- [ ] Dynamic gem query returns ≥1 row when yield≥30 data exists
- [ ] `force-dynamic` removed, Cache Components in use
- [ ] `aa-deals.vercel.app` still renders 200 post-deploy
- [ ] Zod schema rejects invalid params (e.g., `min_yield=999`) gracefully

---

## Priority 2 — Data integrity cleanup (NEW — BLOCKS Layer 3)

Two pre-existing issues that must be fixed before Layer 3 or any schema change.

### 2a. Fix unique key (add `agoda_hotel_id`)

**Current bug**: `UNIQUE (hotel_name, check_in, check_out)` collides cross-city. Example: two "Hampton Inn & Suites" in Dallas and Houston share the hotel name — one silently overwrites the other.

```sql
-- Fix: include agoda_hotel_id in unique key.
CREATE UNIQUE INDEX CONCURRENTLY deals_hotel_id_dates_unique
  ON aa_hotels.deals (agoda_hotel_id, check_in, check_out)
  WHERE agoda_hotel_id IS NOT NULL AND agoda_hotel_id != '';

BEGIN;
  ALTER TABLE aa_hotels.deals
    DROP CONSTRAINT deals_hotel_name_check_in_check_out_key;
  ALTER TABLE aa_hotels.deals
    ADD CONSTRAINT deals_hotel_id_dates_unique
    UNIQUE USING INDEX deals_hotel_id_dates_unique;
COMMIT;
```

Scraper must be **paused** during the atomic swap — mid-migration uniqueness violations silently fail (see 2b).

### 2b. Add error handling to `upsert_batch()`

Current scrape.py:335:
```python
result = sb.table("deals").upsert(batch, on_conflict="hotel_name,check_in,check_out").execute()
stored += len(result.data) if result.data else 0
```

**No try/except. If PostgREST errors (bad on_conflict column), `result.data` is empty, count is 0, scraper logs "Upserted 0 rows" — same as legitimate empty scrape.** Silent data loss.

Fix:
```python
try:
    result = sb.table("deals").upsert(batch, on_conflict="agoda_hotel_id,check_in,check_out").execute()
    if not result.data:
        log.error(f"Upsert returned empty data for batch size {len(batch)} — possible schema mismatch")
    stored += len(result.data) if result.data else 0
except Exception as e:
    log.error(f"Upsert failed: {type(e).__name__}: {e}")
    raise  # Fail loudly in CI
```

### Acceptance
- [ ] `agoda_hotel_id` present and non-null on 100% of rows (verify via SQL before migration)
- [ ] Unique constraint swapped atomically in single transaction
- [ ] Scraper `on_conflict` updated to match new key
- [ ] Scraper paused → migration → scraper redeployed → first run succeeds
- [ ] `upsert_batch` raises on error, not silent-returns

### Rollback
- Re-create old unique constraint, revert scraper `on_conflict`

---

## Priority 3 — Layer 2: Scraper expansion

Revised scope: add **30 mid-size MSAs**, not 60. Proxy budget says 60 exceeds cap.

### Proxy budget reality

performance-oracle envelope math:
- Current: 151 cities × 90 dates × weekly + 20 × 90 × daily ≈ **1.9 GB/mo base**, 2.8 GB/mo observed (retries/TLS inflation)
- Adding 60 cities weekly = +1.0 GB/mo = 3.9 GB/mo (blows 3 GB cap)
- Adding 30 cities weekly = +500 MB/mo = 3.3 GB/mo (still over)
- **Adding 30 cities bi-weekly** = +250 MB/mo = 3.05 GB/mo (tight but fits)
- **Upgrade Webshare to 5 GB plan**: ~$22/mo (+100%). Gives full flexibility.

**Recommendation**: upgrade to Webshare 5 GB plan. $22/mo is cheap for unblocking 30 cities. Solo project — don't let $200/yr bottleneck 200K LP (worth $3K+ in award travel).

### Revised 30-MSA priority list

Derived from: (a) community-cited winter/shoulder markets, (b) budget inventory density, (c) AA hub proximity, (d) deduped against existing cities and dropped-44.

**Tier 1 — Cold-winter mid-size (high probability of 25-30x Hampton/HGI)**:
1. Fort Wayne IN
2. South Bend IN
3. Dayton OH
4. Akron OH (already in — verify ID)
5. Toledo OH (in — verify)
6. Rochester NY (in — verify)
7. Syracuse NY (in — verify)
8. Buffalo NY
9. Hartford CT
10. Minneapolis burbs (Bloomington MN)

**Tier 2 — Shoulder resort**:
11. Pigeon Forge TN
12. Gatlinburg TN (already in — verify)
13. Traverse City MI
14. Asheville NC
15. Burlington VT
16. Portland ME
17. Santa Fe NM
18. Sedona AZ (in — verify)

**Tier 3 — Grand Rapids-class mid-size Midwest**:
19. Grand Rapids MI (in — verify; API-confirmed 10-12x base)
20. Madison WI (in — verify)
21. Des Moines IA (in — verify)
22. Omaha NE
23. Wichita KS (in — verify)
24. Topeka KS
25. Tulsa OK (in — verify)

**Tier 4 — Southeast/Gulf winter**:
26. Mobile AL
27. Pensacola FL (shoulder)
28. Shreveport LA
29. Lafayette LA
30. Jackson MS

**Skip list (confirmed dropped-44 or thin)**: Chicago, Atlanta, Denver, Seattle, SF, Phoenix, San Diego, Tampa, Charlotte, Nashville (most have been dropped or have thin sub-brand inventory).

### Sub-brand detection + lowered threshold

```python
SUB_BRAND_KEYWORDS = frozenset([
    'hampton',        # Hampton Inn, Hampton by Hilton
    'home2 suites',   # Home2 Suites by Hilton
    'homewood',       # Homewood Suites by Hilton
    'embassy suites', # Embassy Suites
    'tru by',         # Tru by Hilton
    'garden inn',     # Hilton Garden Inn
])

SUB_BRAND_EXCLUSIONS = frozenset([
    'grand vacations', # timeshare
    'elara',           # timeshare
    'curio',           # full-service boutique
    'lxr',             # full-service luxury
])

def is_sub_brand(hotel_name: str) -> bool:
    n = (hotel_name or '').lower()
    if any(ex in n for ex in SUB_BRAND_EXCLUSIONS):
        return False
    return any(kw in n for kw in SUB_BRAND_KEYWORDS)


# In scrape.py, when deciding whether to store:
threshold = 10.0 if is_sub_brand(hotel_name) else MIN_YIELD  # MIN_YIELD=15
if yield_ratio >= threshold:
    store(deal)
```

Test cases (pass/fail matrix):

| Hotel Name | Expected | Why |
|---|---|---|
| `Hampton Inn Dallas Downtown` | True | Standard Hampton |
| `Hampton by Hilton Santiago Las Condes` | True | Brand rename, still Hampton |
| `Homewood Suites by Hilton Las Vegas Airport` | True | Standard Homewood |
| `Embassy Suites Dallas Park Central` | True | Standard Embassy |
| `Tru by Hilton Austin NW` | True | Standard Tru |
| `Home2 Suites by Hilton Houston` | True | Standard Home2 |
| `Hilton Garden Inn Detroit Metro Airport` | True | HGI gem case |
| `Virgin Hotels Las Vegas, Curio Collection by Hilton` | False | Excluded by Curio rule |
| `Hilton Grand Vacations Club Elara` | False | Excluded by timeshare rule |
| `Conrad Las Vegas at Resorts World` | False | No keyword match |
| `Hilton Dallas Lincoln Centre` | False | Flagship Hilton, not sub-brand |

### Cron slot recommendation

Current cron: 10:00 hotels, 12:17/18:17 portal, 12:33/16:33/20:33 SM, 13:45 digest, 15:00 lever.

**New mid-size MSA scraper: `0 4 * * *` (04:00 UTC daily)** — zero collision with existing jobs, 6 hours before 10:00 UTC main scraper.

Alternative: fold into existing `scrape-hotels.yml` with a `mode=midsize` input, run Mon/Wed/Fri only.

### Layer 2 acceptance
- [ ] Webshare plan upgraded to 5 GB (manual step)
- [ ] 30 MSAs validated via `scripts/validate_cities.py` before adding to CITIES
- [ ] `is_sub_brand()` + tests land in scraper
- [ ] Threshold logic: `10x` sub-brand, `15x` flagship
- [ ] New scraper runs successfully for 7 days with no errors
- [ ] ≥5 of 30 new cities produce ≥1 stay at ≥25x yield (pilot validation)

---

## Priority 4 — Layer 3: Config scraping (after Layer 2 stable)

Revised scope: **2A/1N, 2A/2N, 2A/3N** only. Skip 1-adult variants (minor LP difference) and skip day-of-week patterns (not worth 2x volume).

### Schema migration (MUST happen after Priority 2)

```sql
-- STEP 1 (additive, zero-downtime)
ALTER TABLE aa_hotels.deals ADD COLUMN adults INT NOT NULL DEFAULT 2;
-- nights column already exists

-- STEP 2 (verify backfill no-op — scraper always wrote 2 adults)
SELECT count(*) FROM aa_hotels.deals WHERE adults IS NULL;  -- 0 expected

-- STEP 3 (pause scraper workflow before this)
CREATE UNIQUE INDEX CONCURRENTLY deals_config_unique
  ON aa_hotels.deals (agoda_hotel_id, check_in, check_out, adults, nights)
  WHERE agoda_hotel_id IS NOT NULL AND agoda_hotel_id != '';

-- STEP 4 (atomic swap)
BEGIN;
  ALTER TABLE aa_hotels.deals DROP CONSTRAINT deals_hotel_id_dates_unique;
  ALTER TABLE aa_hotels.deals ADD CONSTRAINT deals_config_unique
    UNIQUE USING INDEX deals_config_unique;
COMMIT;

-- STEP 5 — deploy scraper with on_conflict="agoda_hotel_id,check_in,check_out,adults,nights"
-- STEP 6 — re-enable scraper workflow
```

### Empirical validation from Layer 3 Explore agent

Actual HTTP probes confirmed LP DOES vary by config:

| Config | Westgate LV | Paris LV |
|---|---|---|
| 1A/1N | 2,700 LP | 2,500 LP |
| 2A/1N | 2,700 LP | 2,600 LP |
| 1A/2N | 6,800 LP | 7,100 LP |
| 2A/2N | 6,900 LP | 7,100 LP |

**Findings**:
- Adult count: ~100-300 LP variance (marginal). **Skip 1-adult scraping.**
- Night count: 1N → 2N yields 2.5× LP (not 2×). **Layer 3 is worth it for nights, not adults.**

### Scraper code change

Currently: 1 night per date, 2 adults.
New: for each date, try 1, 2, 3 nights with 2 adults.

```python
NIGHT_LENGTHS = [1, 2, 3]  # covers the 10K LP cap tier

for date in dates:
    for n in NIGHT_LENGTHS:
        check_out = date + timedelta(days=n)
        deals = await search(..., adults=2, nights=n)
        for d in deals:
            d['adults'] = 2
            d['nights'] = n
```

Data volume increase: ~3x per scrape. But Layer 2 is already +30 cities. Combined = ~5x raw search volume. **Need Webshare 5 GB plan definitely.**

### Preventing `get_top_cities()` bias

performance-oracle flagged: current `get_top_cities()` does `LIMIT 1000` then Python aggregation. With 3x config fanout, daily top-20 selection biases toward cities with most config variants.

Fix:
```sql
-- Replace LIMIT 1000 with DISTINCT ON per (city, hotel_name, check_in)
SELECT DISTINCT ON (city_name, state, hotel_name, check_in)
  city_name, state, yield_ratio
FROM aa_hotels.deals
WHERE yield_ratio >= 25 AND check_in >= CURRENT_DATE
ORDER BY city_name, state, hotel_name, check_in, yield_ratio DESC
LIMIT 1000;
```

### Layer 3 acceptance
- [ ] Priority 2 schema fix applied first (unique key includes agoda_hotel_id)
- [ ] `adults` + `nights` columns present, backfill verified
- [ ] New unique index swapped atomically
- [ ] Scraper writes (2A, 1N), (2A, 2N), (2A, 3N) rows per date
- [ ] Empirical yield lift measured over 7 days; if 2N/3N doesn't beat 1N, roll back
- [ ] `get_top_cities()` migrated to `DISTINCT ON`

### Rollback
- Disable scraper workflow
- Revert scraper code to single-config
- Drop new unique index, recreate old
- Scraper resumes writing 1N only

---

## Supporting infrastructure (cross-layer)

### Postgres indexes (from Supabase best-practices agent)

Add generated column + 3 partial composite indexes. Table rewrite on GENERATED STORED is ~2-5s lock — do during low-traffic window.

```sql
-- Generated sub_brand column (classifies once at INSERT)
ALTER TABLE aa_hotels.deals
  ADD COLUMN sub_brand text
  GENERATED ALWAYS AS (
    CASE
      WHEN hotel_name ILIKE '%Hampton%' THEN 'Hampton'
      WHEN hotel_name ILIKE '%Homewood%' THEN 'Homewood'
      WHEN hotel_name ILIKE '%Home2%' THEN 'Home2'
      WHEN hotel_name ILIKE '%Garden Inn%' THEN 'GardenInn'
      WHEN hotel_name ILIKE '%DoubleTree%' THEN 'DoubleTree'
      WHEN hotel_name ILIKE '%Embassy Suites%' THEN 'Embassy'
      WHEN hotel_name ILIKE '%Tru by%' THEN 'Tru'
      ELSE NULL
    END
  ) STORED;

-- Partial index for "bookable now + ≥25x"
CREATE INDEX CONCURRENTLY idx_deals_bookable_state_yield
  ON aa_hotels.deals (state, yield_ratio DESC)
  INCLUDE (hotel_name, brand, city_name, check_in, check_out, total_cost, total_miles, stars)
  WHERE is_booked = false AND yield_ratio >= 25;

-- Partial index for sub-brand filter
CREATE INDEX CONCURRENTLY idx_deals_subbrand_yield
  ON aa_hotels.deals (sub_brand, yield_ratio DESC)
  INCLUDE (hotel_name, state, city_name, check_in, check_out, total_cost, total_miles, stars)
  WHERE is_booked = false AND sub_brand IS NOT NULL;

-- Trigram fallback for ad-hoc substring searches
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE INDEX CONCURRENTLY idx_deals_hotel_name_trgm
  ON aa_hotels.deals USING gin (hotel_name gin_trgm_ops)
  WHERE is_booked = false;

-- After all DDL:
ANALYZE aa_hotels.deals;
```

Without these indexes, Layer 1's sub-brand filter on 87K rows = full table scan (~500ms). With them: ~5-20ms.

### Hilton sub-brand 2,500 bonus Honors flag (NEW)

Per [Loyalty Lobby 2026-04-03](https://loyaltylobby.com/2026/04/03/hilton-2500-bonus-honors-per-stay-at-hampton-hilton-garden-inn-spark-tru-hotels-in-the-us-april-7-december-31-2026-book-by-july-1/): April 7 – Dec 31, 2026 promo. +2,500 bonus Honors per US stay at Hampton/HGI/Spark/Tru. **Stacks with AA LP earn**.

- Book by July 1, 2026
- Only US properties
- Only the listed sub-brands

Dashboard addition: tag qualifying stays with "💎 +2500 Honors" badge. This is a 6-line change in the `/app/page.tsx` render.

---

## Resource budget projection

| Resource | Current | After Priority 0 | After Layer 2 (30) | After Layer 3 (3 configs) | Limit |
|---|---|---|---|---|---|
| Webshare bandwidth/mo | 2.8 GB | 2.8 GB | 3.3 GB (tight) | 6-8 GB | 3 GB current, 5 GB if upgraded |
| Supabase DB size | 123 MB | 123 MB | ~170 MB | ~350-450 MB | 500 MB free / 8 GB paid |
| GHA minutes (public) | unlimited | unlimited | unlimited | unlimited | unlimited |
| GHA concurrent jobs | 5 | 5 | 6 | 6 | 20 (free) |
| Dashboard query p95 | ~200ms | ~200ms | ~250ms | ~400ms | subjective 1s target |

**Verdict**: Layer 3 requires Webshare 5 GB upgrade. DB size approaches free tier ceiling — moving to Supabase Pro ($25/mo) may be warranted regardless.

---

## Open questions for user

1. **Webshare 5 GB upgrade** ($22/mo) — approve?
2. **Supabase Pro** ($25/mo, 8 GB DB, better perf) — approve or stay on free tier?
3. **Cache Components migration** — OK to replace `force-dynamic` with `'use cache'`? Requires scraper to call `revalidateTag('deals')` post-run (~5 LOC change).
4. **Broken place IDs — manual review of 7+ cities** — want me to run the validation script and share the correct IDs for your approval, or auto-apply fixes?
5. **Priority 0 + 2 before Priority 1?** Technically Priority 1 (dashboard) doesn't depend on the schema fixes, but the broken place IDs do affect data correctness. Fix-first or ship-first?

---

## Deep-dive references (for re-visiting)

- Full 7-agent outputs: conversation history 2026-04-16
- Live Supabase: `aa_hotels.deals` at project `rxsmmrmahnvaarwsngtb`
- AA Hotels API: `https://www.aadvantagehotels.com/rest/aadvantage-hotels/searchRequest`
- Community: FlyerTalk 2065145 (AAH data points, 338 pages), FlyerTalk 1902412 (mattress run app check-in)
- Hilton 2026 promos: [Loyalty Lobby bonus Honors](https://loyaltylobby.com/2026/04/03/...)
- Frequent Miler: [Favorite Hotels 2025](https://frequentmiler.com/frequent-milers-favorite-hotels-of-2025/)
- Next.js 16 Cache Components: https://nextjs.org/docs/app/building-your-application/caching
- Postgres generated columns: https://www.postgresql.org/docs/17/ddl-generated-columns.html
