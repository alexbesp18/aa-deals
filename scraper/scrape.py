#!/usr/bin/env python3
"""
AA Hotels scraper — finds high-yield miles/dollar deals across US cities.
Writes to Supabase aa_hotels.deals. Designed for GitHub Actions daily cron.
Stores 15x+ deals; dashboard filters to 30x+ for display.
"""

import asyncio
import logging
import os
import random
from datetime import datetime, timedelta, UTC
from typing import Any
from urllib.parse import quote

import httpx
from supabase import create_client, ClientOptions

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

BASE = "https://www.aadvantagehotels.com"
MIN_YIELD = 15.0  # Store 15x+, dashboard filters to 30x+
MAX_CONCURRENT = 15  # Slightly lower to avoid Cloudflare triggers
DAYS_AHEAD = 90
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.5",
}

# ── Brand detection ──────────────────────────────────────────────────────────

BRAND_PATTERNS: dict[str, list[str]] = {
    "hilton": [
        "Hilton", "Hampton", "DoubleTree", "Embassy Suites", "Waldorf",
        "Conrad", "Curio", "Tru by", "Home2", "Homewood", "Garden Inn",
        "LXR", "Motto", "Spark by", "Tempo by", "Tapestry", "Signia", "Canopy",
    ],
    "marriott": [
        "Marriott", "Sheraton", "Westin", "W Hotel", "St. Regis",
        "Ritz-Carlton", "JW Marriott", "Courtyard", "Residence Inn",
        "SpringHill", "Fairfield", "TownePlace", "Four Points", "Aloft",
        "Element", "Moxy", "AC Hotel", "Autograph", "Tribute",
    ],
    "ihg": [
        "InterContinental", "Holiday Inn", "Crowne Plaza", "Kimpton",
        "Hotel Indigo", "Staybridge", "Candlewood", "avid hotel",
        "Even Hotel", "Vignette", "Regent",
    ],
    "hyatt": [
        "Hyatt", "Andaz", "Thompson", "Alila", "Caption",
        "Park Hyatt", "Grand Hyatt",
    ],
}


def detect_brand(name: str) -> str | None:
    name_lower = name.lower()
    for brand, patterns in BRAND_PATTERNS.items():
        for p in patterns:
            if p.lower() in name_lower:
                return brand
    return None


# ── City data (Agoda place IDs) ─────────────────────────────────────────────

CITIES: list[tuple[str, str, str]] = [
    # (city, state, agoda_id)
    ("New York", "NY", "318"), ("Los Angeles", "CA", "12772"),
    ("Chicago", "IL", "7889"), ("Dallas", "TX", "8683"),
    ("Houston", "TX", "1178"), ("Washington", "DC", "2320"),
    ("Philadelphia", "PA", "2082"), ("Miami", "FL", "13668"),
    ("Atlanta", "GA", "12226"), ("Boston", "MA", "9254"),
    ("Phoenix", "AZ", "773"), ("San Francisco", "CA", "13801"),
    ("Seattle", "WA", "4579"), ("Minneapolis", "MN", "8934"),
    ("San Diego", "CA", "1159"), ("Tampa", "FL", "14792"),
    ("Denver", "CO", "3649"), ("St. Louis", "MO", "5117"),
    ("Baltimore", "MD", "5107"), ("Orlando", "FL", "16937"),
    ("Charlotte", "NC", "2339"), ("San Antonio", "TX", "15313"),
    ("Portland", "OR", "1143"), ("Sacramento", "CA", "8952"),
    ("Pittsburgh", "PA", "4040"), ("Las Vegas", "NV", "17072"),
    ("Austin", "TX", "4542"), ("Cincinnati", "OH", "4614"),
    ("Kansas City", "MO", "4838"), ("Columbus", "OH", "7621"),
    ("Indianapolis", "IN", "5270"), ("Cleveland", "OH", "1141"),
    ("San Jose", "CA", "8951"), ("Nashville", "TN", "2687"),
    ("Milwaukee", "WI", "6052"), ("Jacksonville", "FL", "7813"),
    ("Oklahoma City", "OK", "2685"), ("Raleigh", "NC", "11206"),
    ("Memphis", "TN", "3003"), ("Richmond", "VA", "3207"),
    ("New Orleans", "LA", "4589"), ("Louisville", "KY", "3133"),
    ("Salt Lake City", "UT", "12269"), ("Hartford", "CT", "8259"),
    ("Buffalo", "NY", "4283"), ("Birmingham", "AL", "13287"),
    ("Honolulu", "HI", "4952"), ("Tucson", "AZ", "7787"),
    ("Tulsa", "OK", "5266"), ("Albuquerque", "NM", "14437"),
    ("Charleston", "SC", "9050"), ("Boise", "ID", "10695"),
    ("Savannah", "GA", "5097"), ("Fort Lauderdale", "FL", "2396"),
    ("Scottsdale", "AZ", "16295"), ("Key West", "FL", "13665"),
    ("Riverside", "CA", "21764"), ("Detroit", "MI", "3322"),
    ("Virginia Beach", "VA", "8163"), ("Providence", "RI", "11639"),
    ("Grand Rapids", "MI", "17080"), ("Omaha", "NE", "13630"),
    ("Knoxville", "TN", "11658"), ("El Paso", "TX", "7692"),
    ("Baton Rouge", "LA", "4359"), ("Colorado Springs", "CO", "10680"),
    ("Madison", "WI", "17136"), ("Wichita", "KS", "12289"),
    ("Toledo", "OH", "17123"), ("Dayton", "OH", "1394"),
    ("Spokane", "WA", "13796"), ("Chattanooga", "TN", "14566"),
    ("Greenville", "SC", "11356"), ("Durham", "NC", "2394"),
    ("Harrisburg", "PA", "6031"), ("Albany", "NY", "17096"),
    ("Columbia", "SC", "2299"), ("Sarasota", "FL", "804"),
    ("Greensboro", "NC", "4689"), ("Fort Myers", "FL", "6861"),
    ("Little Rock", "AR", "407"), ("Akron", "OH", "17138"),
    ("Des Moines", "IA", "20802"), ("Provo", "UT", "1537"),
    ("Daytona Beach", "FL", "3965"), ("Melbourne", "FL", "11456"),
    ("Syracuse", "NY", "5831"), ("Maui", "HI", "9296"),
    ("Palm Beach", "FL", "16947"), ("Napa", "CA", "10740"),
]


# ── API helpers ──────────────────────────────────────────────────────────────

async def search_city(
    client: httpx.AsyncClient,
    city: str,
    state: str,
    agoda_id: str,
    check_in: datetime,
    check_out: datetime,
) -> list[dict[str, Any]]:
    """Search hotels for one city/date combo, return parsed deals."""
    place_id = f"AGODA_CITY|{agoda_id}"
    ci = f"{check_in.month:02}/{check_in.day:02}/{check_in.year}"
    co = f"{check_out.month:02}/{check_out.day:02}/{check_out.year}"
    query_str = f"{city} ({state}), United States"

    # Step 1: create search request
    url = (
        f"{BASE}/rest/aadvantage-hotels/searchRequest?"
        f"adults=2&checkIn={quote(ci, safe='')}&checkOut={quote(co, safe='')}"
        f"&children=0&currency=USD&language=en&locationType=CITY&mode=earn"
        f"&numberOfChildren=0&placeId={quote(place_id, safe='')}"
        f"&program=aadvantage&promotion&query={quote(query_str, safe='')}"
        f"&rooms=1&source=AGODA"
    )

    try:
        r = await client.get(url)
        if r.status_code != 200:
            return []
        uuid = r.json().get("uuid")
        if not uuid:
            return []
    except Exception:
        return []

    await asyncio.sleep(random.uniform(0.1, 0.3))

    # Step 2: get results
    try:
        r = await client.get(f"{BASE}/rest/aadvantage-hotels/search/{uuid}?pageSize=45&pageNumber=1")
        if r.status_code != 200:
            return []
        data = r.json()
    except Exception:
        return []

    # Step 3: parse results
    results_list = data.get("results", [])
    if not results_list:
        log.debug(f"No results for {city}, {state} on {check_in.date()}")
        return []

    nights = (check_out - check_in).days
    deals = []
    raw_yields = []
    for h in results_list:
        hotel = h.get("hotel", {})
        name = hotel.get("name", "")
        if not name:
            continue

        price_obj = h.get("grandTotalPublishedPriceInclusiveWithFees", {})
        total_cost = float(price_obj.get("amount", 0))
        if total_cost <= 0:
            total_cost = float(h.get("totalPriceUSD", {}).get("amount", 0))
        if total_cost <= 0:
            continue

        total_miles = max(int(h.get("rewards", 0)), int(h.get("roomTypeResultTeaser", {}).get("rewards", 0)))
        if total_miles <= 0:
            continue

        yield_ratio = total_miles / total_cost
        raw_yields.append(yield_ratio)
        if yield_ratio < MIN_YIELD:
            continue

        hotel_id = str(hotel.get("id", ""))
        booking_url = (
            f"{BASE}/hotel/{hotel_id}?checkIn={quote(ci, safe='')}"
            f"&checkOut={quote(co, safe='')}&rooms=1&adults=2&mode=earn"
        ) if hotel_id else None

        deals.append({
            "hotel_name": name,
            "brand": detect_brand(name),
            "city_name": city,
            "state": state,
            "stars": int(hotel.get("stars", 0)),
            "check_in": check_in.strftime("%Y-%m-%d"),
            "check_out": check_out.strftime("%Y-%m-%d"),
            "nights": nights,
            "total_cost": round(total_cost, 2),
            "total_miles": total_miles,
            "yield_ratio": round(yield_ratio, 2),
            "url": booking_url,
            "agoda_hotel_id": hotel_id,
            "scraped_at": datetime.now(UTC).isoformat(),
        })

    return deals


# ── Main scraper ─────────────────────────────────────────────────────────────

def get_supabase():
    """Get Supabase client."""
    return create_client(
        os.environ["SUPABASE_URL"],
        os.environ["SUPABASE_SERVICE_ROLE_KEY"],
        options=ClientOptions(schema="aa_hotels"),
    )


def upsert_batch(sb, deals: list[dict[str, Any]]) -> int:
    """Upsert a batch of deals, preserving is_booked."""
    if not deals:
        return 0
    stored = 0
    for i in range(0, len(deals), 100):
        batch = deals[i : i + 100]
        result = sb.table("deals").upsert(
            batch,
            on_conflict="hotel_name,check_in,check_out",
        ).execute()
        stored += len(result.data) if result.data else 0
    return stored


async def scrape_all() -> int:
    """Scrape all cities, upsert per-city. Returns total deals stored."""
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    dates = [(today + timedelta(days=d), today + timedelta(days=d + 1)) for d in range(1, DAYS_AHEAD + 1)]

    sb = get_supabase()

    # Clean past deals
    sb.table("deals").delete().lt("check_in", today.strftime("%Y-%m-%d")).execute()
    log.info("Cleaned up past deals")

    sem = asyncio.Semaphore(MAX_CONCURRENT)
    total_stored = 0

    async with httpx.AsyncClient(timeout=30.0, headers=HEADERS, follow_redirects=True) as client:

        for idx, (city, state, aid) in enumerate(CITIES):

            async def search_date(ci: datetime, co: datetime):
                async with sem:
                    await asyncio.sleep(random.uniform(0.05, 0.15))
                    return await search_city(client, city, state, aid, ci, co)

            tasks = [search_date(ci, co) for ci, co in dates]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Collect deals for this city
            city_deals: list[dict[str, Any]] = []
            for r in results:
                if isinstance(r, list):
                    city_deals.extend(r)

            # Deduplicate per city: best yield per (hotel_name, check_in)
            best: dict[str, dict] = {}
            for d in city_deals:
                key = f"{d['hotel_name']}|{d['check_in']}"
                if key not in best or d["yield_ratio"] > best[key]["yield_ratio"]:
                    best[key] = d
            unique = list(best.values())

            # Upsert immediately
            if unique:
                stored = upsert_batch(sb, unique)
                total_stored += stored
                top = max(d["yield_ratio"] for d in unique)
                log.info(f"[{idx+1}/{len(CITIES)}] {city}, {state}: {stored} deals (top {top:.1f}x)")
            else:
                log.info(f"[{idx+1}/{len(CITIES)}] {city}, {state}: 0 deals")

    log.info(f"Scrape complete: {total_stored} total deals stored across {len(CITIES)} cities")
    return total_stored


async def main():
    log.info(f"Starting AA Hotels scraper — {len(CITIES)} cities, {DAYS_AHEAD} days ahead, {MIN_YIELD}x+ threshold")
    total = await scrape_all()
    log.info(f"Done — {total} deals in database")


if __name__ == "__main__":
    asyncio.run(main())
