# AA Hotel Deals Dashboard

One-pager showing 30x+ AA Advantage hotel redemptions globally. Cherry-picks the best miles-per-dollar deals from aadvantagehotels.com.

**Live**: https://aa-deals.vercel.app
**Repo**: https://github.com/alexbesp18/aa-deals (private)

## Commands

```bash
npm run dev          # Local dev server
npm run build        # Production build

# Scraper (Python)
cd scraper && pip install -r requirements.txt
SUPABASE_URL=... SUPABASE_SERVICE_ROLE_KEY=... PROXY_USERNAME=... PROXY_PASSWORD=... python scrape.py
```

## Architecture

```
User -> Vercel (Next.js 16) -> Supabase (aa_hotels schema)
                                    ^
GitHub Actions (every 2h) -> Python scraper -> Webshare proxy -> AA Hotels API -> Supabase
```

### Stack
- **Frontend**: Next.js 16, Server Components, Server Actions, Tailwind CSS 4, Geist font
- **Data**: Supabase `aa_hotels` schema — `deals` table + `scrape_progress` table
- **Scraper**: Python 3.12, async httpx, 196 cities (152 US + 44 international), 90 days ahead
- **Proxy**: Webshare rotating residential (each request = fresh IP, avoids Cloudflare)
- **Cron**: GitHub Actions every 2 hours, resumable across runs via `scrape_progress`
- **Deploy**: Vercel auto-deploy from main, GitHub Actions for scraper

### Data Flow
1. Scraper checks `scrape_progress` for cities already done today
2. For each remaining city: searches 90 dates in parallel (semaphore=50)
3. Filters deals >= 15x yield, upserts to `deals` table (preserving `is_booked`)
4. Marks city done in `scrape_progress`
5. If run times out (60 min), next 2-hour run picks up remaining cities
6. Dashboard queries `deals` WHERE yield >= 30, is_booked = false, check_in >= today

### Key Design Decisions
- **Store 15x+, display 30x+**: Scraper stores more data; dashboard has yield dropdown (15/20/25/30/40x)
- **is_booked preserved**: Upsert payload excludes `is_booked` -> survives daily re-scrapes
- **Per hotel-date granularity**: Same hotel on Wed and Fri = two separate rows (both bookable)
- **Brand detection**: Pattern-match hotel names -> 7 families (Hilton, Marriott, IHG, Hyatt, Wyndham, BestWestern, Choice)
- **Incremental upsert**: City-by-city processing means partial runs still produce data
- **Past deals auto-cleaned**: `DELETE WHERE check_in < today` at start of each run

## Database Schema (Supabase `aa_hotels`)

```sql
-- Main deals table
deals (
  id BIGINT PK,
  hotel_name TEXT, brand TEXT, city_name TEXT, state TEXT, stars INT,
  check_in DATE, check_out DATE, nights INT,
  total_cost NUMERIC, total_miles INT, yield_ratio NUMERIC,
  url TEXT, agoda_hotel_id TEXT, is_booked BOOLEAN DEFAULT false,
  scraped_at TIMESTAMPTZ, created_at TIMESTAMPTZ,
  UNIQUE(hotel_name, check_in, check_out)
)

-- Resume tracking
scrape_progress (
  city TEXT, state TEXT, scraped_date DATE, deals_found INT,
  completed_at TIMESTAMPTZ,
  PRIMARY KEY(city, state, scraped_date)
)
```

## City Coverage (196 total)

- **88 US metros**: NY, LA, Chicago, Dallas, Houston, etc.
- **19 additional MSAs**: Rochester, Fresno, Fort Worth, Reno, etc.
- **45 US resort/tourism**: Sedona, Park City, Jackson Hole, Vail, Key West, Myrtle Beach, etc.
- **44 international**: Middle East (Riyadh 43x, Abu Dhabi 36x, Dubai 31x), Latin America (Cartagena 29x, Cusco 31x), SE Asia, Europe, East Asia

## Secrets / Env Vars

| Secret | Location | Purpose |
|--------|----------|---------|
| `SUPABASE_URL` | Vercel + GH Actions | (see Vercel env vars) |
| `SUPABASE_SERVICE_ROLE_KEY` | Vercel + GH Actions | Service role (server-only) |
| `PROXY_USERNAME` | GH Actions | Webshare rotating residential |
| `PROXY_PASSWORD` | GH Actions | Webshare rotating residential |

## Yield Mechanics (reverse-engineered)

- Miles follow a **non-linear accelerating formula** tied to Agoda commission per property
- **Hard cap at 10,000 miles** per booking
- **Sweet spot: $200-300 hotels** where acceleration is steepest before hitting cap
- Caesars/Vegas properties have promotional multipliers (+10-15x above baseline)
- International: Middle East outperforms US (Riyadh 43x > Las Vegas 34x)
- Cheap international hotels ($10-30) earn minimum miles (100-300) = low yield
