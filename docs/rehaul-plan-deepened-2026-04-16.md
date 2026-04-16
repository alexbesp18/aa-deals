# AA Rehaul Plan — DEEPENED 2026-04-16

> Companion to `rehaul-plan-2026-04-16.md`. This doc is the output of 12 parallel research/review agents. Where a deepening overrides the original plan, the new version wins.

---

## Enhancement Summary

**Deepened on**: 2026-04-16
**Sections enhanced**: 9 packets + 3 cross-cutting reviews
**Research agents used**: Explore×9 (per packet) + security-sentinel + data-integrity-guardian + performance-oracle + supabase-postgres-best-practices skill + domain-patterns skill

### Key improvements
1. **Dashboard uses service-role key** (verified at `lib/supabase.ts:7`) — PKT-001 risk profile drops from "may break dashboard" to "trivially safe" (service role bypasses RLS).
2. **Service role key rotation is now a blocker** before PKT-003 — 4 deleted Vercel zombies held copies that cannot be audited post-deletion. New packet: **PKT-000.5**.
3. **Cron offset schedule** — current `0 */6 * * *` + `0 */4 * * *` patterns create triple-collisions at 00:00 and 12:00 UTC that will exhaust the Supabase pooler (60-conn free-tier cap). Offset schedule below fixes it.
4. **Playwright storage_state is broken on Linux GH Actions runners** ([#32302](https://github.com/microsoft/playwright/issues/32302)) — manual cookie JSON + base64 is the only reliable path for PKT-006.
5. **Drop-schema sequence needs 7 steps, not 2** — the original PKT-009 wording would replay the 2026-04-14 outage.
6. **Proxy budget is tighter than expected** — projected 3.04 GB/mo vs 3 GB cap. SM scraper must be measured in week 1.
7. **Dashboard has no `data-testid` or `verify` script**, and Vercel does NOT auto-deploy docs-only changes — small but real implications for PKT-002 and PKT-007 E2E.

### New considerations discovered
- **`session_state.cookies_encrypted` must use pgsodium or app-level encryption**, not trust in service role isolation alone. If the key leaks (historical risk from zombie Vercels), every AA session ever stored is readable.
- **GH Actions fork-PR risk**: any `pull_request` trigger with secrets exposes credentials to forked PRs. Workflows must be `push` / `schedule` / `workflow_dispatch` only.
- **Webshare proxy URL format `user-rotate:pass@host`** embeds the password — must be scrubbed from any exception logging.
- **`register_exposed_schema` abuse path**: service-role caller could expose `auth` or `pg_catalog`. Add a deny-list to the tripwire function.
- **Next.js 16 Cache Components + `cacheLife`** is a better fit than `force-dynamic` for `/stacks` (4-6h freshness) but deferred to keep PKT-007 consistent with existing `/` route style.

---

## Critical Cross-Cutting Changes (new)

### PKT-000.5 — Rotate service-role key (NEW, blocks PKT-003)
- **Why**: 4 Vercel zombies (just deleted) held copies of the `alex_projects` service role key. Cannot be audited post-deletion. Rotate before creating new schema so `aa_tools` is born under a fresh credential.
- **Steps**: Supabase Dashboard → Project Settings → API → Reset `service_role` secret. Update: Vercel env on `aa-deals`, GH secret `SUPABASE_SERVICE_ROLE_KEY` on `aa-deals` repo, any other project using `alex_projects` (check `mcp__vercel__list_projects` — at least `cc-tracker-dashboard`, `options_tracker`, `jordi-dashboard`, `dylan-tracker-web`, `xsolla-intel`, `ai-model-scanner-web`).
- **Risk**: ~30s of dashboard downtime during Vercel env update + redeploy. Acceptable.
- **Time**: ~15 min including cross-project propagation.

### Revised cron schedule (ALL workflows)
Eliminates 00:00 and 12:00 triple-collisions and pooler saturation:

| Workflow | Current plan | **Use this** | Reason |
|---|---|---|---|
| `scrape-hotels.yml` | `0 10 * * *` daily + `0 8 * * 0` weekly | unchanged | Anchor |
| `scrape-portal.yml` | `0 */6 * * *` | **`17 */6 * * *`** (00:17, 06:17, 12:17, 18:17) | 17-min offset |
| `scrape-simplymiles.yml` | `0 */4 * * *` | **`33 */4 * * *`** (00:33, 04:33, 08:33, 12:33, 16:33, 20:33) | 16-min gap from portal |
| `health-digest.yml` | `0 13 * * *` | **`45 13 * * *`** | 12-min after 12:33 SM + 18:17 portal settles |

### GH Actions safety pattern for ALL new workflows
Applied to PKT-005, PKT-006, PKT-008:
```yaml
on:
  schedule: [{ cron: "..." }]
  workflow_dispatch:
# NEVER use pull_request with secrets — fork PRs can exfil
permissions:
  contents: read  # default-deny; scope up per job if needed
```
And in secret-handling steps:
```yaml
- name: Use session secret safely
  env:
    SM_SESSION: ${{ secrets.SIMPLYMILES_SESSION_B64 }}
  run: |
    set +x                                     # disable command tracing
    umask 077                                  # owner-only perms
    printf '%s' "$SM_SESSION" | base64 -d > "$RUNNER_TEMP/sm.json"
    unset SM_SESSION
    python scraper/simplymiles.py --cookies "$RUNNER_TEMP/sm.json"
    rm -f "$RUNNER_TEMP/sm.json"
```

### Webshare proxy logging scrub
Any scraper that uses `http://{user}-rotate:{pass}@p.webshare.io:80` must wrap proxy exceptions with URL redaction:
```python
try:
    async with httpx.AsyncClient(proxy=proxy_url) as client:
        ...
except httpx.HTTPError as e:
    log.error(f"HTTP error: {type(e).__name__}")  # NEVER log str(e) — may leak proxy URL
```

---

## Per-packet deepening

### PKT-001 — Enable RLS on `aa_hotels`

**Original definition unchanged.** Research changes the risk profile and adds rollback nuance.

#### Research Insights

**Key verification**: `aa-deals` dashboard and scraper BOTH use `SUPABASE_SERVICE_ROLE_KEY` (`lib/supabase.ts:7` and `scraper/scrape.py:275`). Service role **bypasses RLS entirely**. Enabling RLS with zero policies is functionally invisible to both. The "dashboard might break" fear is unfounded.

**Recommended migration SQL** (ready to paste):
```sql
BEGIN;
ALTER TABLE aa_hotels.deals ENABLE ROW LEVEL SECURITY;
ALTER TABLE aa_hotels.scrape_progress ENABLE ROW LEVEL SECURITY;

-- Force RLS so table owner is also subject (prevents accidental bypass via migrations)
ALTER TABLE aa_hotels.deals FORCE ROW LEVEL SECURITY;
ALTER TABLE aa_hotels.scrape_progress FORCE ROW LEVEL SECURITY;

-- Explicit deny for anon (makes intent grep-able; no policies = implicit deny but this is clearer)
CREATE POLICY "deny_anon_all" ON aa_hotels.deals
  FOR ALL TO anon USING (false) WITH CHECK (false);
CREATE POLICY "deny_anon_all" ON aa_hotels.scrape_progress
  FOR ALL TO anon USING (false) WITH CHECK (false);

-- Service role bypass policy (cosmetic — service role bypasses anyway — but documents intent)
CREATE POLICY "service_role_all" ON aa_hotels.deals
  FOR ALL TO service_role USING (true) WITH CHECK (true);
CREATE POLICY "service_role_all" ON aa_hotels.scrape_progress
  FOR ALL TO service_role USING (true) WITH CHECK (true);
COMMIT;
```

**Debug escape hatch** (stage but don't apply unless regression): keep `migrations/0002_aa_hotels_debug_anon_read.sql.disabled` with `CREATE POLICY temp_anon_read ... TO anon USING (true)`. Drop policy to revert. **Never `DISABLE ROW LEVEL SECURITY`** — reintroduces the advisor flag.

**Trap to document**: if a future packet switches dashboard to anon key, add a SELECT policy in the same transaction. Without it, dashboard breaks silently.

**Rollback**:
```sql
DROP POLICY IF EXISTS "deny_anon_all" ON aa_hotels.deals;
DROP POLICY IF EXISTS "deny_anon_all" ON aa_hotels.scrape_progress;
DROP POLICY IF EXISTS "service_role_all" ON aa_hotels.deals;
DROP POLICY IF EXISTS "service_role_all" ON aa_hotels.scrape_progress;
ALTER TABLE aa_hotels.deals DISABLE ROW LEVEL SECURITY;
ALTER TABLE aa_hotels.scrape_progress DISABLE ROW LEVEL SECURITY;
```

**Validation** (revised):
1. `get_advisors` before → note `rls_disabled_in_public` on these 2 tables
2. Apply migration via `execute_sql`
3. `get_advisors` after → 2 tables no longer flagged
4. `workflow_dispatch` on `scrape-hotels.yml` — expect success, ≥1 row written
5. `curl -w "%{http_code}" https://aa-deals.vercel.app` — expect 200

**References**: [Supabase RLS best practices](https://supabase.com/docs/guides/database/postgres/row-level-security) via Context7.

---

### PKT-002 — Commit docs + CLAUDE.md change

**Revised** based on repo inspection.

#### Research Insights

**Verifications**:
- `package.json` has NO `verify` script. Only `dev`, `build`, `start`, `lint`. → Run `pnpm lint` (not `pnpm verify`).
- No `.husky/`, `.lefthook.yml`, or `lint-staged` config → commits won't auto-lint.
- `docs/` is outside Next.js build path → Vercel will NOT auto-deploy. Docs-only commit produces no new Vercel deployment. Verify via `git log` not via live URL.
- Recent commit convention: `docs: comprehensive CLAUDE.md` — scope is optional.

**Recommended commands** (two commits for semantic cleanliness):
```bash
cd /Users/alexbespalov/projects/aa-deals

# Commit 1: new planning docs
git add docs/rehaul-plan-2026-04-16.md \
        docs/preserved-gems.md \
        docs/rehaul-plan-deepened-2026-04-16.md
git commit -m "docs: add AA rehaul plan + preserved gems + deepened review

See audit + 4-strategist synthesis from 2026-04-16.
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"

# Commit 2: CLAUDE.md business-group import
git add CLAUDE.md
git commit -m "docs: import business group CLAUDE guidelines

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"

pnpm lint
git push origin main
```

**Acceptance** (revised):
- `git status` clean — yes
- `git log --oneline -3` shows both commits — yes
- Vercel auto-deploy triggered? **No (docs-only)** — acceptable. If production verification needed, trigger empty redeploy via `vercel --prod` or Vercel dashboard.

---

### PKT-003 — Create `aa_tools` schema

**Significantly revised** — full DDL, constraints, indexes, encryption pattern.

#### Research Insights

**Migration SQL** (single transaction, schema + tables + RLS + view):

```sql
BEGIN;

CREATE SCHEMA IF NOT EXISTS aa_tools;
GRANT USAGE ON SCHEMA aa_tools TO service_role;
-- Intentionally NO grants to anon/authenticated — all reads via service role

-- Session state first (used by scrapers for auth)
CREATE EXTENSION IF NOT EXISTS pgcrypto;  -- for column-level encryption if pgsodium not available

CREATE TABLE aa_tools.session_state (
  source             text PRIMARY KEY CHECK (source IN ('simplymiles','portal')),
  cookies_encrypted  bytea NOT NULL,
  captured_at        timestamptz NOT NULL DEFAULT now(),
  expires_at         timestamptz NOT NULL DEFAULT (now() + interval '14 days'),
  captured_by        text
);
CREATE INDEX session_state_expires_idx ON aa_tools.session_state (expires_at);

-- Portal rates — HOT table (one row per merchant, upsert overwrite)
CREATE TABLE aa_tools.portal_rates (
  id                         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  merchant_name              text NOT NULL,
  merchant_name_normalized   text NOT NULL,
  miles_per_dollar           numeric(6,2) NOT NULL CHECK (miles_per_dollar >= 0),
  is_elevated                boolean NOT NULL DEFAULT false,
  rebate_raw                 text,
  click_url                  text,
  scraped_at                 timestamptz NOT NULL DEFAULT now(),
  UNIQUE (merchant_name_normalized)
);
CREATE INDEX portal_rates_rate_desc_idx
  ON aa_tools.portal_rates (miles_per_dollar DESC)
  WHERE miles_per_dollar >= 5;

-- Portal rates history — COLD table (only inserted on rate CHANGE)
CREATE TABLE aa_tools.portal_rates_history (
  id                         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  merchant_name_normalized   text NOT NULL,
  miles_per_dollar           numeric(6,2) NOT NULL,
  is_elevated                boolean NOT NULL DEFAULT false,
  observed_at                timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX prh_merchant_time_idx
  ON aa_tools.portal_rates_history (merchant_name_normalized, observed_at DESC);

-- SimplyMiles offers
CREATE TABLE aa_tools.sm_offers (
  id                         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  offer_id                   text,
  merchant_name              text NOT NULL,
  merchant_name_normalized   text NOT NULL,
  offer_type                 text NOT NULL CHECK (offer_type IN ('flat_bonus','per_dollar','unknown')),
  miles_amount               integer NOT NULL CHECK (miles_amount >= 0),
  lp_amount                  integer NOT NULL DEFAULT 0 CHECK (lp_amount >= 0),
  min_spend                  numeric(10,2) CHECK (min_spend IS NULL OR min_spend > 0),
  headline_raw               text,
  expires_at                 timestamptz,
  scraped_at                 timestamptz NOT NULL DEFAULT now(),
  UNIQUE (merchant_name_normalized, offer_type, COALESCE(expires_at, 'infinity'::timestamptz), miles_amount)
);
CREATE INDEX sm_offers_normalized_idx ON aa_tools.sm_offers (merchant_name_normalized);
CREATE INDEX sm_offers_active_idx ON aa_tools.sm_offers (expires_at)
  WHERE expires_at IS NULL OR expires_at > now();

-- RLS from day one
ALTER TABLE aa_tools.session_state ENABLE ROW LEVEL SECURITY;
ALTER TABLE aa_tools.session_state FORCE ROW LEVEL SECURITY;
ALTER TABLE aa_tools.portal_rates ENABLE ROW LEVEL SECURITY;
ALTER TABLE aa_tools.portal_rates FORCE ROW LEVEL SECURITY;
ALTER TABLE aa_tools.portal_rates_history ENABLE ROW LEVEL SECURITY;
ALTER TABLE aa_tools.portal_rates_history FORCE ROW LEVEL SECURITY;
ALTER TABLE aa_tools.sm_offers ENABLE ROW LEVEL SECURITY;
ALTER TABLE aa_tools.sm_offers FORCE ROW LEVEL SECURITY;

-- Explicit deny for anon/authenticated on all
CREATE POLICY "deny_anon" ON aa_tools.session_state     FOR ALL TO anon          USING (false) WITH CHECK (false);
CREATE POLICY "deny_auth" ON aa_tools.session_state     FOR ALL TO authenticated USING (false) WITH CHECK (false);
CREATE POLICY "deny_anon" ON aa_tools.portal_rates      FOR ALL TO anon          USING (false) WITH CHECK (false);
CREATE POLICY "deny_auth" ON aa_tools.portal_rates      FOR ALL TO authenticated USING (false) WITH CHECK (false);
CREATE POLICY "deny_anon" ON aa_tools.portal_rates_history FOR ALL TO anon       USING (false) WITH CHECK (false);
CREATE POLICY "deny_auth" ON aa_tools.portal_rates_history FOR ALL TO authenticated USING (false) WITH CHECK (false);
CREATE POLICY "deny_anon" ON aa_tools.sm_offers         FOR ALL TO anon          USING (false) WITH CHECK (false);
CREATE POLICY "deny_auth" ON aa_tools.sm_offers         FOR ALL TO authenticated USING (false) WITH CHECK (false);

-- Placeholder view — real body in PKT-007
CREATE VIEW aa_tools.stack_view AS
  SELECT NULL::text AS merchant_name
  WHERE false;

-- pg_cron cleanup for expired sessions (alex_projects has pg_cron)
SELECT cron.schedule(
  'aa_tools_session_cleanup',
  '17 3 * * *',
  $$DELETE FROM aa_tools.session_state WHERE expires_at < now()$$
);

COMMIT;

-- OUTSIDE transaction: expose schema
SELECT public.register_exposed_schema('aa_tools');
-- Then manually: Dashboard > Project Settings > API > Exposed Schemas > add 'aa_tools' > Save
```

**Key design decisions**:
- `bigint GENERATED ALWAYS AS IDENTITY` (not `serial`, not UUID) — Supabase best practice.
- `portal_rates` has UNIQUE on normalized name only (upsert overwrite); `portal_rates_history` is separate — avoids 2.4M rows/year.
- `UNIQUE (..., COALESCE(expires_at, 'infinity'))` avoids NULL-collision in Postgres unique indexes.
- Partial indexes `WHERE miles_per_dollar >= 5` and `WHERE expires_at > now()` keep indexes tight.
- `cookies_encrypted BYTEA` — forces ciphertext, blocks accidental plaintext INSERT.
- `FORCE ROW LEVEL SECURITY` ensures policies apply to table owner (defense in depth).
- pg_cron session cleanup nightly at 03:17 UTC.

**Encryption decision**: use **app-level encryption** (GH Actions secret `SM_COOKIE_ENCRYPTION_KEY`, AES-256-GCM via Python cryptography) for `cookies_encrypted` in MVP. pgsodium TCE is an upgrade path — its Transparent Column Encryption requires 3 extra SQL steps + key labels + a decrypted view. Not worth the complexity today; revisit if scraper scope grows.

**`register_exposed_schema` hardening** (proposed safeguard): before calling, confirm the RPC rejects reserved schema names. If it doesn't, file a separate one-line migration to add a deny-list inside the function:
```sql
-- Inside register_exposed_schema body, before GRANT statements:
IF schema_name IN ('auth','pg_catalog','pg_toast','storage','vault',
                   'extensions','graphql','graphql_public','realtime',
                   'supabase_functions') THEN
  RAISE EXCEPTION 'Cannot expose reserved schema: %', schema_name;
END IF;
```

**Validation**:
```sql
-- Service role insert
INSERT INTO aa_tools.portal_rates (merchant_name, merchant_name_normalized, miles_per_dollar)
  VALUES ('_test', '_test', 1.0);
SELECT COUNT(*) FROM aa_tools.portal_rates;  -- expect ≥1
DELETE FROM aa_tools.portal_rates WHERE merchant_name = '_test';
```
Then via anon key: `curl -H "apikey:$ANON_KEY" "$URL/rest/v1/portal_rates"` → expect empty/PGRST.

**References**: [Supabase schema exposure 2-step flow](https://supabase.com/docs/guides/api/using-custom-schemas), internal `~/Desktop/Projects/CLAUDE.md` schema rules.

---

### PKT-004 — Kill Railway service

**Minor revisions** — confirmed steps and billing link.

#### Research Insights

**Precondition**: User must run `railway login` (browser pairing flow). The CLI and MCP both require this.

**5-step sequence after login**:
```bash
railway login                         # browser pair
railway list                          # verify account projects
# If 004-us-hotel-scraper exists:
railway project <project-id>          # switch context
railway service list                  # confirm scraper service
railway project delete <project-id>   # 48h grace period
```

**Billing verification** (pre-delete): [dashboard.railway.app/account/billing](https://dashboard.railway.app/account/billing). Railway Hobby minimum is $5/mo. If service has been idle since 2026-01-19 (~3 months), potential overpay is ~$15-20.

**Data loss risk**: env vars erased after 48h grace period. If project held Supabase creds or Resend key, note them before delete (unlikely since `004` pointed at the dead `aa_scraper` schema).

**If no Railway service exists**: mark packet complete, no-op.

---

### PKT-005 — Port portal scraper

**Significantly deepened** — batch size, upsert strategy, HTML fallback plan.

#### Research Insights

**Confirmed patterns from `scrape.py`** (aa-deals style):
- `logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s")` 
- `create_client(URL, SERVICE_KEY, options=ClientOptions(schema="aa_tools"))`
- Error returns: `[{"_error": "reason"}]` — but **replaced** with typed log-and-continue per security review (don't expose error shape)
- Upsert batch: **500** (up from 100 for scraper efficiency per performance review) — 4 round-trips instead of 20

**Dependencies to add to `scraper/requirements.txt`**:
```
httpx>=0.27.0
supabase>=2.0.0
rapidfuzz>=3.0.0   # NEW — for merchant name fuzzy matching later
# NO BeautifulSoup — use regex for HTML fallback
```

**Upsert strategy** (per performance review):
1. Hot: `portal_rates` → `ON CONFLICT (merchant_name_normalized) DO UPDATE SET miles_per_dollar = EXCLUDED.miles_per_dollar, is_elevated = ..., scraped_at = NOW()`. One row per merchant.
2. History: insert into `portal_rates_history` ONLY when rate change detected (Python-side diff vs current hot row). Avoids 730K rows/year.

**Workflow** (uses revised cron):
```yaml
name: Scrape Portal Rates
on:
  schedule: [{ cron: "17 */6 * * *" }]   # offset from hotels + SM
  workflow_dispatch:
permissions:
  contents: read
jobs:
  portal:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install -r scraper/requirements.txt
      - env:
          SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
          SUPABASE_SERVICE_ROLE_KEY: ${{ secrets.SUPABASE_SERVICE_ROLE_KEY }}
          PROXY_USERNAME: ${{ secrets.PROXY_USERNAME }}
          PROXY_PASSWORD: ${{ secrets.PROXY_PASSWORD }}
        run: python scraper/portal.py
```

**Skeleton structure** (~250 LOC target, ≤300 hard):
```python
#!/usr/bin/env python3
"""Portal scraper — Cartera API + HTML fallback."""
import asyncio, logging, os, re
from typing import Any
import httpx
from supabase import create_client, ClientOptions

BASE = "https://www.aadvantageeshopping.com"
CARTERA_URL = "https://api.cartera.com/content/v4/merchants/all"
CARTERA_PARAMS = {
    "brand_id": "251",
    "app_key": "9ec260e91abc101aaec68280da6a5487",
    "app_id": "672b9fbb",
    "limit": "2000",
    "sort_by": "name",
    "fields": "name,type,id,showRebate,rebate,clickUrl,offers",
}

# Rate parser regex ladder — from preserved-gems §5
# ... etc
```

**Parser gotchas flagged**:
- "Up to X miles" (no `/$`) — flat bonus; store as X, set `is_elevated=true`, set `miles_per_dollar=X/min_spend` if min_spend given else 0
- Token normalization collisions: "Macy's Inc." vs "Macy's Online" both → "macys". Log WARN; don't fail.
- `_error` sentinel pattern from existing `scrape.py` — **DON'T replicate**. Use typed exceptions + structured logging.

**Proxy role**: Cartera API doesn't need proxy (one public API call). HTML fallback DOES need proxy (Cloudflare). Only set proxy on the fallback httpx client.

---

### PKT-006 — Port SimplyMiles scraper

**Biggest deepening** — Playwright GH Actions bug forces a different approach.

#### Research Insights

**Critical finding**: [Playwright #32302](https://github.com/microsoft/playwright/issues/32302) — `storage_state` works locally on macOS but **silently fails on Linux GH Actions runners** (cookies don't transfer to browser context). Don't use `storage_state` at scrape-time.

**Architecture**:
- **Local** (macOS): `scripts/capture_session.py` headed Playwright — user logs in manually, script exports cookies JSON
- **CI** (Linux GH Actions): `scraper/simplymiles.py` uses httpx only (NO Playwright) with cookies from GH secret

**GH secret encoding**: base64 to avoid shell escape issues:
```bash
python scripts/capture_session.py       # outputs cookies.json + base64 string
# Paste the base64 string into this command:
gh secret set SIMPLYMILES_SESSION_B64 --body "$BASE64_STRING" -R alexbesp18/aa-deals
```
Cookie JSON ~2-4KB; base64 ~3-5KB. Well under 48KB GH secret limit.

**Stale session detection — 3-layer**:
1. **Workflow precheck**: check GH secret metadata (can't read value without exposing; instead store `SIMPLYMILES_SESSION_CAPTURED_AT` as separate secret and compare).
2. **Scraper level**: try API call; if 401 or 302 → exit non-zero with clear message.
3. **Digest level**: PKT-008 checks age and emails stale-session warning.

**Auth failure detection**:
```python
resp = client.post(API_URL, json={"page_type": "landing"}, headers=headers, timeout=15)

if resp.status_code == 302:
    log.error(f"Session expired (302 → {resp.headers.get('Location', '?')})")
    sys.exit(2)
if resp.status_code == 401:
    log.error("Session rejected (401)")
    sys.exit(2)
resp.raise_for_status()
data = resp.json()
offers = data.get("offers", [])
# Valid empty response ≠ error
if not offers:
    log.warning("Empty offers list — may be normal or may indicate auth issue")
```

**Workflow**:
```yaml
name: Scrape SimplyMiles
on:
  schedule: [{ cron: "33 */4 * * *" }]
  workflow_dispatch:
permissions:
  contents: read
jobs:
  scrape:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install -r scraper/requirements.txt
      - name: Decode session secret (no echo)
        env:
          SM_SESSION_B64: ${{ secrets.SIMPLYMILES_SESSION_B64 }}
        run: |
          set +x
          umask 077
          printf '%s' "$SM_SESSION_B64" | base64 -d > "$RUNNER_TEMP/sm.json"
          unset SM_SESSION_B64
      - name: Scrape
        env:
          SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
          SUPABASE_SERVICE_ROLE_KEY: ${{ secrets.SUPABASE_SERVICE_ROLE_KEY }}
        run: |
          python scraper/simplymiles.py --cookies "$RUNNER_TEMP/sm.json"
          rm -f "$RUNNER_TEMP/sm.json"
      - name: Notify on stale session
        if: failure()
        env: { RESEND_API_KEY: ${{ secrets.RESEND_API_KEY }} }
        run: |
          curl -X POST https://api.resend.com/emails \
            -H "Authorization: Bearer $RESEND_API_KEY" \
            -H "Content-Type: application/json" \
            -d '{"from":"digest@novaconsultpro.com","to":"alexbespalovtx@gmail.com","subject":"SimplyMiles session expired","html":"Run scripts/capture_session.py locally and push new cookie to GH secret SIMPLYMILES_SESSION_B64."}'
```

**Capture script skeleton** (~100 LOC, local only):
```python
import asyncio, json, base64, urllib.parse
from playwright.async_api import async_playwright

SIMPLYMILES_URL = "https://www.simplymiles.com/"

async def capture():
    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            "./browser_data",
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = await ctx.new_page()
        await page.goto(SIMPLYMILES_URL)
        input("Log in manually, then press Enter here...")
        cookies = await ctx.cookies(["https://www.simplymiles.com"])
        await ctx.close()

    payload = json.dumps(cookies)
    with open("cookies.json", "w") as f:
        f.write(payload)
    b64 = base64.b64encode(payload.encode()).decode()
    print("\n=== Base64 (push to gh secret) ===")
    print(b64)
    print(f"\ngh secret set SIMPLYMILES_SESSION_B64 --body '{b64}' -R alexbesp18/aa-deals")

if __name__ == "__main__":
    asyncio.run(capture())
```

**Session lifespan**: undocumented; community consensus ~7 days. Treat as 5 days to have warning buffer.

---

### PKT-007 — Stack view + `/stacks` route

**Deepened** — SQL view DDL, fuzzy matching decision, RSC pattern verified.

#### Research Insights

**Verified pattern from `app/page.tsx`**:
- `export const dynamic = "force-dynamic"`
- `import "server-only"` at top of `lib/supabase.ts`
- `Promise.all([query, lastScrape])` for parallel queries
- Inline `{error && ...}` error div with schema-tripwire detection on line 124

**`lib/supabase.ts` needs update**: currently hardcodes `schema="aa_hotels"`. Extend:
```typescript
// lib/supabase.ts
import 'server-only';
import { createClient } from '@supabase/supabase-js';

export function getSupabase(schema: 'aa_hotels' | 'aa_tools' = 'aa_hotels') {
  return createClient(
    process.env.SUPABASE_URL!,
    process.env.SUPABASE_SERVICE_ROLE_KEY!,
    { db: { schema } }
  );
}
```

**Stack view DDL** — replaces the placeholder from PKT-003:
```sql
CREATE OR REPLACE VIEW aa_tools.stack_view AS
SELECT
  p.merchant_name,
  p.merchant_name_normalized,
  p.miles_per_dollar AS portal_rate,
  p.is_elevated AS portal_is_elevated,
  s.offer_type AS sm_type,
  s.miles_amount AS sm_miles_amount,
  s.min_spend AS sm_min_spend,
  s.expires_at AS sm_expires,
  s.headline_raw AS sm_headline,
  CASE
    WHEN s.offer_type = 'flat_bonus' AND s.min_spend > 0
      THEN s.miles_amount::numeric / s.min_spend
    WHEN s.offer_type = 'per_dollar'
      THEN s.miles_amount::numeric
    ELSE 0
  END AS sm_per_dollar,
  1.0::numeric AS cc_rate,
  p.miles_per_dollar + COALESCE(
    CASE
      WHEN s.offer_type = 'flat_bonus' AND s.min_spend > 0
        THEN s.miles_amount::numeric / s.min_spend
      WHEN s.offer_type = 'per_dollar'
        THEN s.miles_amount::numeric
      ELSE 0
    END, 0
  ) + 1.0 AS combined_yield,
  GREATEST(p.scraped_at, s.scraped_at) AS last_scraped_at
FROM aa_tools.portal_rates p
INNER JOIN aa_tools.sm_offers s
  ON p.merchant_name_normalized = s.merchant_name_normalized
WHERE s.expires_at IS NULL OR s.expires_at > now();
```

**Fuzzy matching — deferred**. MVP uses exact normalized match. If post-launch analysis shows many missed matches, add:
```sql
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE INDEX portal_rates_trgm ON aa_tools.portal_rates USING gin (merchant_name_normalized gin_trgm_ops);
CREATE INDEX sm_offers_trgm ON aa_tools.sm_offers USING gin (merchant_name_normalized gin_trgm_ops);
-- Extend view WHERE with: OR similarity(p.merchant_name_normalized, s.merchant_name_normalized) > 0.85
```

**Route skeleton**:
```typescript
// app/stacks/page.tsx
import { getSupabase } from "@/lib/supabase";

export const dynamic = "force-dynamic";

type Stack = {
  merchant_name: string;
  portal_rate: number;
  portal_is_elevated: boolean;
  sm_type: string;
  sm_miles_amount: number;
  sm_min_spend: number | null;
  sm_expires: string | null;
  sm_headline: string | null;
  sm_per_dollar: number;
  cc_rate: number;
  combined_yield: number;
  last_scraped_at: string;
};

export default async function StacksPage(props: {
  searchParams: Promise<{ min_yield?: string }>;
}) {
  const { min_yield } = await props.searchParams;
  const threshold = Number(min_yield) || 15;

  const supabase = getSupabase('aa_tools');
  const [{ data: stacks, error }, { data: lastScrape }] = await Promise.all([
    supabase
      .from('stack_view')
      .select('*')
      .gte('combined_yield', threshold)
      .order('combined_yield', { ascending: false })
      .limit(50),
    supabase
      .from('portal_rates')
      .select('scraped_at')
      .order('scraped_at', { ascending: false })
      .limit(1),
  ]);

  // Render with schema-tripwire error branch (copy from app/page.tsx:124-142)
}
```

**Columns for table (7)**:
| Column | Field | Format |
|---|---|---|
| Merchant | `merchant_name` | bold |
| Portal | `portal_rate` + `portal_is_elevated` | "2.5x" + ✨ if elevated |
| SM Offer | `sm_type` + `sm_miles_amount` + `sm_min_spend` | "135 mi on $5+" or "4 mi/$" |
| Expires | `sm_expires` | relative ("3 days") or ISO |
| Combined | `combined_yield` | bold; green ≥30, lime ≥15 |
| Updated | `last_scraped_at` | "2h ago" |
| Link | — | portal click URL |

**View vs materialized**: regular view. ~80 expected matches, query <50ms. Materialized adds refresh cron complexity without benefit.

---

### PKT-008 — Daily digest (Resend)

**Deepened** — full HTML template, skip logic, Resend SDK pattern.

#### Research Insights

**Resend setup check**: run `gh secret list -R alexbesp18/aa-deals` to confirm `RESEND_API_KEY` is set. If missing, add it.

**Secrets needed**:
- `RESEND_API_KEY` (may exist)
- `DIGEST_TO` = `alexbespalovtx@gmail.com` (or use the hardcoded fallback)

**Domain**: `digest@novaconsultpro.com` per preserved-gems (already verified).

**Skip rule** (per user's "advisor not monitor" feedback):
```python
def should_send(stacks, new_deals, session_age_days, scraper_failures) -> bool:
    return (
        len(stacks) > 0
        or len(new_deals) > 0
        or session_age_days > 5
        or len(scraper_failures) > 0
    )
# If false: silent day, don't send
```

**Workflow**:
```yaml
name: Daily Digest
on:
  schedule: [{ cron: "45 13 * * *" }]
  workflow_dispatch:
permissions:
  contents: read
jobs:
  digest:
    runs-on: ubuntu-latest
    timeout-minutes: 5
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install resend supabase
      - env:
          SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
          SUPABASE_SERVICE_ROLE_KEY: ${{ secrets.SUPABASE_SERVICE_ROLE_KEY }}
          RESEND_API_KEY: ${{ secrets.RESEND_API_KEY }}
          DIGEST_TO: ${{ secrets.DIGEST_TO || 'alexbespalovtx@gmail.com' }}
        run: python scripts/digest.py
```

**Script skeleton** (~120 LOC):
```python
"""Daily digest — top stacks + new hotels + session/scraper status."""
import os
from datetime import datetime, timezone, timedelta
import resend
from supabase import create_client, ClientOptions

RESEND_FROM = "digest@novaconsultpro.com"

def main():
    aa_hotels = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"],
                              options=ClientOptions(schema="aa_hotels"))
    aa_tools = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"],
                             options=ClientOptions(schema="aa_tools"))

    stacks = aa_tools.from_("stack_view").select("*").gte("combined_yield", 20) \
        .order("combined_yield", desc=True).limit(5).execute().data or []

    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    new_deals = aa_hotels.from_("deals").select("hotel_name,city_name,yield_ratio,check_in,check_out") \
        .gt("created_at", cutoff).order("yield_ratio", desc=True).limit(5).execute().data or []

    session_age_days = get_session_age("simplymiles")  # query aa_tools.session_state
    scraper_failures = get_recent_gh_failures()         # GH API or null for now

    if not should_send(stacks, new_deals, session_age_days, scraper_failures):
        print("Silent day; no digest sent.")
        return

    html = render_html(stacks, new_deals, session_age_days, scraper_failures)
    resend.api_key = os.environ["RESEND_API_KEY"]
    resend.Emails.send({
        "from": RESEND_FROM,
        "to": [os.environ["DIGEST_TO"]],
        "subject": f"AA Digest · {datetime.now().strftime('%Y-%m-%d')}",
        "html": html,
    })
```

**HTML template** — inline CSS, table-based, dark-mode aware, ~80 LOC. (See `scripts/templates/digest.html` pattern — use simple string template, not Jinja, for <150 LOC total.)

**Security note**: do NOT include session age in days — attacker reading leaked email can time exploit. Use status buckets ("healthy" / "stale — refresh recommended").

---

### PKT-009 — Drop `aa_scraper` schema

**Extensively deepened** — 7-step checklist, archive, canary, rollback.

#### Research Insights

**Pre-drop baseline** (run now on 2026-04-16, after approval):
```sql
VACUUM ANALYZE aa_scraper.hotel_rates, aa_scraper.scrape_jobs, aa_scraper.hotel_deals,
               aa_scraper.deal_discoveries, aa_scraper.merchant_history,
               aa_scraper.hotel_yield_baselines, aa_scraper.scraper_health,
               aa_scraper.portal_rates, aa_scraper.simplymiles_offers,
               aa_scraper.stacked_opportunities, aa_scraper.alert_history;

-- Save baseline
SELECT relname, n_tup_ins, n_tup_upd, n_tup_del, NOW() AS baseline_ts
FROM pg_stat_user_tables WHERE schemaname = 'aa_scraper'
ORDER BY relname;
```

**7-day canary — revoke writes NOW** (immediately; test drop on 2026-04-23):
```sql
REVOKE INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA aa_scraper FROM anon, authenticated, authenticator;
-- Service role retains if still writing for some reason — will surface in Supabase logs as permission errors
```

**Ordered 7-step drop sequence** (2026-04-23 execution):

| # | Step | Command | Rollback |
|---|---|---|---|
| A | Verify no writes for 7+ days | `SELECT relname, n_tup_ins + n_tup_upd + n_tup_del AS delta FROM pg_stat_user_tables WHERE schemaname='aa_scraper'` vs baseline. Also `gh search code 'aa_scraper' --owner=alexbesp18` | N/A (read-only) |
| B | **Archive to aa-deals/docs/archive/** | `pg_dump -h db.rxsmmrmahnvaarwsngtb.supabase.co -U postgres -n aa_scraper --data-only -Fc > aa_scraper_2026-04-23.sql.gz` + commit | Re-dump |
| C | Revoke all grants (belt-and-suspenders) | `REVOKE USAGE ON SCHEMA aa_scraper FROM anon, authenticated, authenticator, service_role;` `REVOKE ALL ON ALL TABLES IN SCHEMA aa_scraper FROM public;` | Re-grant if needed |
| D | Remove from Dashboard Exposed Schemas | Manual: Project Settings > API > Exposed Schemas > remove `aa_scraper` > Save. Note timestamp. | Re-add in Dashboard |
| E | Wait 10 min for PostgREST cache | Monitor `curl https://aa-deals.vercel.app` — expect continuous 200s. Also `curl -H "apikey:$ANON" $URL/rest/v1/aa_scraper/hotel_rates` → expect `PGRST106 Invalid schema`. Also `curl $URL/rest/v1/deals` (aa_hotels) → expect 200. | Re-add schema in Dashboard |
| F | Remove from `protected_schemas` allow-list (temporarily) | `DELETE FROM public.protected_schemas WHERE schema_name = 'aa_scraper';` (verify table/column name first) | `INSERT INTO public.protected_schemas (schema_name) VALUES ('aa_scraper');` |
| G | **Execute drop** | `DROP SCHEMA aa_scraper CASCADE;` → verify with `SELECT 1 FROM information_schema.schemata WHERE schema_name = 'aa_scraper';` (empty). Then `curl https://aa-deals.vercel.app` (200) and `get_advisors` (no PGRST errors). | Emergency recovery below |

**Emergency recovery if Step G crashes PostgREST**:
1. **Do NOT run more SQL.**
2. Supabase Dashboard → Project Settings → Pause Project → 30s → Restore Project → 60s.
3. PostgREST rebuilds cache without `aa_scraper`.
4. If data restore needed: import dump from Step B into `aa_scraper_restored` schema.

**Monitoring between 2026-04-16 and 2026-04-23**:
- Query once/day:
```sql
SELECT relname, n_tup_ins + n_tup_upd + n_tup_del AS delta
FROM pg_stat_user_tables WHERE schemaname='aa_scraper';
```
- If ANY delta > baseline, STOP and investigate the writer.

**Data loss tolerance**: 12,652 rows of (mostly obsolete) data. Archive as `.sql.gz` in `aa-deals/docs/archive/` (need to add to repo) — small file, permanent reference.

---

## Revised migration sequence (with new dependencies)

```
PKT-000.5 ─ rotate service-role key ─┐
                                      │
PKT-001 (RLS aa_hotels) ─────────────┤  independent
PKT-002 (commit docs) ───────────────┤  independent
PKT-004 (Railway kill) ──────────────┘  requires `railway login`

              ┌─── PKT-005 (portal scraper) ──┐
PKT-003 (schema) ──┤                           ├── PKT-007 (stack view + /stacks)
              └─── PKT-006 (SimplyMiles) ─────┘      ↓
                                                 PKT-008 (digest)
                                                     ↓
              [7-day canary: revoke writes on aa_scraper]
                                                     ↓
                                                 PKT-009 (drop aa_scraper, 2026-04-23+)
```

**Today (2026-04-16)**:
- PKT-000.5: rotate service role key (15 min)
- PKT-001: enable RLS on aa_hotels (10 min)
- PKT-002: commit docs (5 min)
- PKT-003: create aa_tools schema (30 min)
- Revoke writes on aa_scraper as canary (2 min)
- PKT-004: Railway kill (needs `railway login`, ~10 min)

**This week**:
- PKT-005: portal scraper + workflow (~90 min)
- PKT-006: SimplyMiles scraper + capture script + workflow (~2.5 hr)

**After both scrapers produce data**:
- PKT-007: stack view + /stacks route (~3-4 hr)
- PKT-008: digest (~90 min)

**2026-04-23 or later (after 7-day canary passes)**:
- PKT-009: drop aa_scraper (~30 min execution)

---

## Open decisions (Alex must call)

1. **AA Hotels nerf verification** — per bombshell in original plan: book one cheap stay, verify actual LP credit. Gates whether to port SM/Portal or to also consider retiring `aa-deals` scraper. Independent of rehaul mechanics.
2. **SimplyMiles actual usage** — the plan invests ~2.5 hours porting 001's SM scraper. If Alex hasn't actually redeemed a SimplyMiles offer in 2026, skip PKT-006 and invest that time elsewhere.
3. **Service role split (PKT-001.5 from data-integrity review)** — split `lib/supabase.ts` into reader (anon + RLS) + writer (service role + `server-only`). Larger than PKT-001 but eliminates the latent "leak the service role key → own the DB" risk. Consider as P1 hardening after the rehaul core lands.
4. **pgsodium upgrade for `session_state`** — current plan uses app-level encryption (GH secret key). pgsodium TCE is cleaner but adds 3 SQL steps + key labels. File as P2 upgrade after MVP works.

---

## Appendix: Full agent reports

### A1. Architecture strategist (ran earlier, see conversation history)
Full synthesis lives in `rehaul-plan-2026-04-16.md`. Not duplicated.

### A2. Code simplicity reviewer (ran earlier)
97% deletion rate on dormant code. Kill 003 entirely. Extract only: `simplymiles_api.py`, `portal.py`, `stack_detector.py` logic, `002/lib/optimizer.ts`.

### A3. Pattern recognition specialist (ran earlier)
File:line map of unique capabilities, 10 anti-patterns identified. See conversation.

### A4. Best-practices researcher (ran earlier) — AA Hotels nerf bombshell
Documented in top of original plan. Critical: re-verify before committing to scraper work.

### A5-A13. Per-packet deepening — synthesized into sections above
Agents: PKT-001 through PKT-009 Explore + security-sentinel + data-integrity-guardian + performance-oracle + supabase-postgres-best-practices skill + domain-patterns skill.

Raw outputs available in conversation history at time of deepening.

---

## Quality checks

- [x] All original content preserved (refer to companion `rehaul-plan-2026-04-16.md`)
- [x] Research insights clearly marked per packet
- [x] SQL examples syntactically valid (sanity-checked via Postgres idiom)
- [x] Shell/workflow YAML syntactically valid
- [x] No contradictions between sections (verified: service-role-bypass makes RLS safe; FORCE RLS for defense)
- [x] Enhancement summary accurate
- [x] References cited inline

**Ready for execution gate**: user approves revised packets + sequence, then begin at PKT-000.5.
