# Manual Actions — AA Rehaul 2026-04-16

Work I can't automate. In priority order. Check off as you go.

---

## 🔴 Required before scrapers can write to `aa_tools`

### 1. Expose `aa_tools` schema in Supabase Dashboard
- Go to [Supabase Dashboard → Settings → API](https://supabase.com/dashboard/project/rxsmmrmahnvaarwsngtb/settings/api)
- Scroll to "Exposed Schemas"
- Add `aa_tools` to the list
- Click Save
- **Why**: I already ran `register_exposed_schema('aa_tools')` which does the GRANTs. This UI step tells PostgREST to serve it. Until done, scrapers get `PGRST106 Invalid schema`.
- **Time**: 30 sec

---

## 🟡 Blocks PKT-004 (Railway kill)

### 2. Log in to Railway CLI
- In this chat, paste: `!railway login`
- The `!` prefix runs with interactive TTY. Browser opens, you auth, done.
- After completion, tell me so I can kill the 004-us-hotel-scraper project.
- **Time**: 1 min

---

## 🟡 Blocks PKT-006 (SimplyMiles scraper)

### 3. Capture SimplyMiles session (first time + weekly thereafter)
`scripts/capture_session.py` is shipped. Run this locally:
```bash
cd ~/projects/aa-deals
pip install playwright && playwright install chromium   # one-time
python scripts/capture_session.py
# Browser opens → log in to simplymiles.com with AA credentials + MFA → press Enter
# Script prints a gh secret set command — copy+paste it to rotate the secret
```
**Recurring**: repeat every 5-7 days when scraper workflow fails with exit 2 ("session expired" annotation).
- **Time**: 2 min (first + each refresh)

### 4. Add Resend + digest email secrets
The daily digest is built and tested (runs `scripts/digest.py`) but needs:
```bash
gh secret set RESEND_API_KEY --body "<your resend key>" -R alexbesp18/aa-deals
gh secret set DIGEST_TO --body "alexbespalovtx@gmail.com" -R alexbesp18/aa-deals
```
Get your Resend key at [resend.com/api-keys](https://resend.com/api-keys). The `novaconsultpro.com` sender domain is already verified (per `preserved-gems.md`).
- **Time**: 2 min

---

## 🟢 Nice-to-have verification

### 5. Verify AA Hotels nerf math (per research agent bombshell)
- Book one cheap stay via aadvantagehotels.com (~$100-200)
- Wait for LP credit to post (1-2 weeks)
- Compare actual LP vs what `aa_hotels.deals.total_miles` predicted for that hotel/date
- Per [One Mile at a Time](https://onemileatatime.com/guides/american-aadvantage-hotels/), AA capped at 10K LP per stay (1-3 nights) or 15K LP per stay (4+ nights) **per stay, not per night** — pre-2023 math no longer applies
- **Decision gate**: if nerf confirmed, the whole hotels scraper may be archive-only. Portal × SimplyMiles stacking becomes the main play.

---

## 🔵 Deferred (do later)

### 6. Rotate service role key (PKT-000.5 — skipped per your call)
- Current risk: 4 deleted Vercel zombies held copies of this key (Dec 2025 – March 2026)
- To rotate: Dashboard → Settings → API → "Reset `service_role` secret" → give me the new key → I propagate to Vercel/GH/local `.env`
- **Do this if**: you ever want to audit who has DB access, or before exposing any admin surfaces publicly.

### 7. Remove `aa_scraper` from Dashboard Exposed Schemas (after 2026-04-23)
- 7-day canary started today (writes already revoked). After 2026-04-23, if no permission-denied errors in Supabase logs for `aa_scraper.*`, this is safe.
- [Supabase Dashboard → Settings → API](https://supabase.com/dashboard/project/rxsmmrmahnvaarwsngtb/settings/api) → Exposed Schemas → remove `aa_scraper` → Save
- Then I can run the drop sequence per `rehaul-plan-deepened-2026-04-16.md` §PKT-009.

---

## What's already done (2026-04-16)

- ✅ Audit report + 4-strategist synthesis + deepened plan (4 docs in `docs/`)
- ✅ 4 Vercel zombies deleted (`quick_aa_hotels`, `aa_streak_optimizer`, `us_hotel_scraper`, `002-aa-streak-optimizer`)
- ✅ **PKT-001**: RLS enabled + forced on `aa_hotels.deals` and `aa_hotels.scrape_progress`
- ✅ **PKT-002**: 4 docs + CLAUDE.md committed and pushed
- ✅ **PKT-003**: `aa_tools` schema created — `portal_rates`, `portal_rates_history`, `sm_offers`, `session_state` tables + placeholder view + RLS forced + deny-anon/auth + service-role-all policies
- ✅ **Canary**: writes on `aa_scraper` revoked (7-day monitor starts now)
- ✅ **PKT-004**: Railway project `us-hotel-scraper` deleted via GraphQL (stopped ~$60/yr bleed)
- ✅ **PKT-005**: Portal scraper shipped. First run wrote **1,004 merchants** to `aa_tools.portal_rates`. Top rate 25x (Network Solutions). Workflow runs every 6h.
- ✅ **PKT-006**: SimplyMiles scraper + capture script + workflow shipped. Ready — awaits your action #3.
- ✅ **PKT-007**: `stack_view` SQL view + `/stacks` Next.js route shipped. Live at aa-deals.vercel.app/stacks (empty until SM data lands).
- ✅ **PKT-008**: Daily digest shipped. `scripts/digest.py` + `health-digest.yml` cron at 13:45 UTC. Tested end-to-end against live data — needs your action #4 (Resend key) to actually send.
- ✅ Production verified green (dashboard HTTP 200, advisor clean for aa_hotels)

## What remains (all user-gated)

1. Expose `aa_tools` in Dashboard (if PostgREST stops serving `aa_tools` routes — it's currently working via service role)
2. Capture SimplyMiles cookie + set `SIMPLYMILES_SESSION_B64`
3. Set `RESEND_API_KEY` + `DIGEST_TO` secrets
4. (Optional) Book a test AA hotel to verify nerf math
5. (On/after 2026-04-23) Drop `aa_scraper` schema per deepened-plan §PKT-009

After #1-3 are done, the system runs autonomously: portal every 6h, SimplyMiles every 4h, digest daily at 08:45 CT.
