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

### 3. Capture SimplyMiles session (first time)
After I build PKT-006, run this locally:
```bash
cd ~/projects/aa-deals
python scripts/capture_session.py
# Browser opens, you log in to simplymiles.com with AA credentials + MFA
# Script prints a base64 blob
gh secret set SIMPLYMILES_SESSION_B64 --body '<blob>' -R alexbesp18/aa-deals
```
**Recurring**: repeat every 5-7 days when scraper workflow fails with "session expired" email.
- **Time**: 2 min (first + each refresh)

---

## 🟢 Nice-to-have verification

### 4. Verify AA Hotels nerf math (per research agent bombshell)
- Book one cheap stay via aadvantagehotels.com (~$100-200)
- Wait for LP credit to post (1-2 weeks)
- Compare actual LP vs what `aa_hotels.deals.total_miles` predicted for that hotel/date
- Per [One Mile at a Time](https://onemileatatime.com/guides/american-aadvantage-hotels/), AA capped at 10K LP per stay (1-3 nights) or 15K LP per stay (4+ nights) **per stay, not per night** — pre-2023 math no longer applies
- **Decision gate**: if nerf confirmed, the whole hotels scraper may be archive-only. Portal × SimplyMiles stacking becomes the main play.

---

## 🔵 Deferred (do later)

### 5. Rotate service role key (PKT-000.5 — skipped per your call)
- Current risk: 4 deleted Vercel zombies held copies of this key (Dec 2025 – March 2026)
- To rotate: Dashboard → Settings → API → "Reset `service_role` secret" → give me the new key → I propagate to Vercel/GH/local `.env`
- **Do this if**: you ever want to audit who has DB access, or before exposing any admin surfaces publicly.

### 6. Remove `aa_scraper` from Dashboard Exposed Schemas (after 2026-04-23)
- 7-day canary started today (writes already revoked). After 2026-04-23, if no permission-denied errors in Supabase logs for `aa_scraper.*`, this is safe.
- [Supabase Dashboard → Settings → API](https://supabase.com/dashboard/project/rxsmmrmahnvaarwsngtb/settings/api) → Exposed Schemas → remove `aa_scraper` → Save
- Then I can run the drop sequence per `rehaul-plan-deepened-2026-04-16.md` §PKT-009.

---

## What's already done (2026-04-16)

- ✅ Audit report + 4-strategist synthesis + deepened plan (3 docs in `docs/`)
- ✅ 4 Vercel zombies deleted (`quick_aa_hotels`, `aa_streak_optimizer`, `us_hotel_scraper`, `002-aa-streak-optimizer`)
- ✅ PKT-001: RLS enabled + forced on `aa_hotels.deals` and `aa_hotels.scrape_progress`
- ✅ PKT-002: 3 docs + CLAUDE.md committed and pushed
- ✅ PKT-003: `aa_tools` schema created with 4 tables + placeholder view + RLS forced + deny-anon/auth + service-role-all policies
- ✅ Canary: writes on `aa_scraper` revoked (7-day monitor starts now)
- ✅ Production verified green (dashboard HTTP 200, advisor clean for aa_hotels)

## What I'll do next (autonomously)

Once you knock out #1 (expose `aa_tools` in Dashboard) and #2 (`!railway login`):

1. Kill Railway service (PKT-004)
2. Build PKT-005 — portal scraper (Cartera API + HTML fallback)
3. Build PKT-006 — SimplyMiles scraper + capture script (waits on your #3 cookie capture to actually run)
4. Build PKT-007 — `/stacks` route + real `stack_view` body
5. Build PKT-008 — daily digest workflow
6. On 2026-04-23: remind you about #6, then run PKT-009
