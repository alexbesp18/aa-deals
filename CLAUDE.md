# AA Hotel Deals Dashboard

One-pager showing 30x+ AA Advantage hotel redemptions across US cities.

## Commands

```bash
npm run dev          # Local dev server
npm run build        # Production build

# Scraper (Python)
pip install -r scraper/requirements.txt
python scraper/scrape.py   # Requires SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY
```

## Architecture

```
User -> Vercel (Next.js) -> Supabase (aa_hotels schema)
                                ^
GitHub Actions (daily) -> Python scraper -> Supabase
```

- **Frontend**: Next.js 15, Server Components, Server Actions, Tailwind CSS
- **Data**: Supabase `aa_hotels.deals` table
- **Scraper**: Python async (httpx), 85 cities, 45 days ahead, 30x+ threshold
- **Cron**: GitHub Actions daily at 11 AM UTC

## Key decisions

- Brand detection by hotel name pattern matching (hilton, marriott, ihg, hyatt)
- `is_booked` preserved across scraper upserts (not in upsert payload)
- Deals auto-cleaned when check_in < today
- Service role key used server-side only (server-only import guard)
