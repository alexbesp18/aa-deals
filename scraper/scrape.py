#!/usr/bin/env python3
"""
AA Hotels scraper — finds high-yield miles/dollar deals across US cities.
Writes to Supabase aa_hotels.deals. Resumable across runs via scrape_progress.
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
MIN_YIELD = 15.0
MAX_CONCURRENT = 50  # Each request gets a fresh proxy IP
DAYS_AHEAD = 90
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.5",
}
US_STATES = {
    "AL","AK","AZ","AR","CA","CO","CT","DC","DE","FL","GA","HI","ID","IL","IN",
    "IA","KS","KY","LA","ME","MD","MA","MI","MN","MS","MO","MT","NE","NV","NH",
    "NJ","NM","NY","NC","ND","OH","OK","OR","PA","PR","RI","SC","SD","TN","TX",
    "UT","VT","VA","WA","WV","WI","WY",
}

# ── Brand detection ──────────────────────────────────────────────────────────

BRAND_PATTERNS: dict[str, list[str]] = {
    "hilton": [
        "Hilton", "Hampton", "DoubleTree", "Embassy Suites", "Waldorf",
        "Conrad", "Curio", "Tru by", "Home2", "Homewood", "Garden Inn",
        "LXR", "Motto", "Spark by", "Tempo by", "Tapestry", "Signia", "Canopy",
    ],
    "marriott": [
        "Marriott", "Sheraton", "Westin", "St. Regis", "Ritz-Carlton",
        "JW Marriott", "Courtyard", "Residence Inn", "SpringHill", "Fairfield",
        "TownePlace", "Four Points", "Aloft", "Element", "Moxy", "AC Hotel",
        "Autograph", "Tribute", "W Dallas", "W Miami", "W Hotel",
    ],
    "ihg": [
        "InterContinental", "Holiday Inn", "Crowne Plaza", "Kimpton",
        "Hotel Indigo", "Staybridge", "Candlewood", "avid hotel",
        "Even Hotel", "Vignette", "Regent",
    ],
    "hyatt": [
        "Hyatt", "Andaz", "Thompson Hotels", "Alila", "Caption",
        "Park Hyatt", "Grand Hyatt",
    ],
    "wyndham": [
        "Wyndham", "La Quinta", "Ramada", "Days Inn", "Super 8",
        "Microtel", "Baymont", "Wingate", "AmericInn", "Hawthorn",
    ],
    "bestwestern": [
        "Best Western", "SureStay", "Aiden", "BW Signature",
    ],
    "choice": [
        "Cambria", "Comfort Inn", "Comfort Suites", "Quality Inn",
        "Clarion", "Sleep Inn", "Ascend", "WoodSpring",
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
    # ── US metros (deal-producing only, 44 zero-deal cities removed) ─────────
    ("New York", "NY", "318"), ("Los Angeles", "CA", "12772"),
    ("Dallas", "TX", "8683"), ("Houston", "TX", "1178"),
    ("Washington", "DC", "2320"), ("Philadelphia", "PA", "2082"),
    ("Boston", "MA", "9254"), ("San Francisco", "CA", "13801"),
    ("Minneapolis", "MN", "8934"), ("Las Vegas", "NV", "17072"),
    ("Austin", "TX", "4542"), ("Cincinnati", "OH", "4614"),
    ("Indianapolis", "IN", "5270"), ("Cleveland", "OH", "1141"),
    ("Tulsa", "OK", "5266"), ("Savannah", "GA", "5097"),
    ("Fort Lauderdale", "FL", "2396"), ("Riverside", "CA", "21764"),
    ("Detroit", "MI", "3322"), ("Virginia Beach", "VA", "8163"),
    ("Providence", "RI", "11639"), ("Grand Rapids", "MI", "17080"),
    ("Omaha", "NE", "13630"), ("Knoxville", "TN", "11658"),
    ("El Paso", "TX", "7692"), ("Baton Rouge", "LA", "4359"),
    ("Colorado Springs", "CO", "10680"), ("Madison", "WI", "17136"),
    ("Wichita", "KS", "12289"), ("Toledo", "OH", "17123"),
    ("Dayton", "OH", "1394"), ("Spokane", "WA", "13796"),
    ("Chattanooga", "TN", "14566"), ("Greenville", "SC", "11356"),
    ("Durham", "NC", "2394"), ("Harrisburg", "PA", "6031"),
    ("Albany", "NY", "17096"), ("Columbia", "SC", "2299"),
    ("Sarasota", "FL", "804"), ("Greensboro", "NC", "4689"),
    ("Fort Myers", "FL", "6861"), ("Little Rock", "AR", "407"),
    ("Akron", "OH", "17138"), ("Des Moines", "IA", "20802"),
    ("Provo", "UT", "1537"), ("Daytona Beach", "FL", "3965"),
    ("Melbourne", "FL", "11456"), ("Syracuse", "NY", "5831"),
    ("Maui", "HI", "9296"), ("Palm Beach", "FL", "16947"),
    ("Memphis", "TN", "3003"),
    # ── Additional MSAs ──────────────────────────────────────────────────────
    ("Rochester", "NY", "17127"), ("Fresno", "CA", "13602"),
    ("Worcester", "MA", "19522"), ("Scranton", "PA", "14274"),
    ("Modesto", "CA", "8418"), ("Augusta", "GA", "17253"),
    ("Bridgeport", "CT", "22599"), ("Bakersfield", "CA", "14094"),
    ("New Haven", "CT", "3984"), ("McAllen", "TX", "5397"),
    ("Oxnard", "CA", "10157"), ("Allentown", "PA", "1868"),
    ("Stockton", "CA", "13336"), ("Lakeland", "FL", "7485"),
    ("Springfield", "MA", "570"), ("Winston-Salem", "NC", "19842"),
    ("Ogden", "UT", "10860"), ("Fort Worth", "TX", "17487"),
    ("Reno", "NV", "6214"),
    # ── Resort & tourism ─────────────────────────────────────────────────────
    ("Sedona", "AZ", "9768"), ("Park City", "UT", "12399"),
    ("Anchorage", "AK", "11740"), ("Myrtle Beach", "SC", "9442"),
    ("Palm Springs", "CA", "1579"), ("Branson", "MO", "11267"),
    ("Gatlinburg", "TN", "4197"), ("San Juan", "PR", "17823"),
    ("Cancun", "MX", "5954"), ("Cabo San Lucas", "MX", "9739"),
    ("Santa Fe", "NM", "9589"), ("Hilton Head Island", "SC", "13747"),
    ("Destin", "FL", "6882"), ("Asheville", "NC", "7165"),
    ("Monterey", "CA", "4635"), ("South Lake Tahoe", "CA", "5283"),
    ("Pensacola", "FL", "8053"), ("Galveston", "TX", "10196"),
    ("Wilmington", "NC", "17055"), ("Newport", "RI", "17260"),
    ("Williamsburg", "VA", "6942"), ("Pigeon Forge", "TN", "10501"),
    ("Gulf Shores", "AL", "23541"), ("Panama City", "FL", "17589"),
    ("Corpus Christi", "TX", "7436"), ("Clearwater", "FL", "9974"),
    ("Naples", "FL", "342"), ("St. Augustine", "FL", "16395"),
    ("Bend", "OR", "2295"), ("Flagstaff", "AZ", "6958"),
    ("Moab", "UT", "8145"), ("Traverse City", "MI", "13240"),
    ("Santa Barbara", "CA", "8292"), ("Miami Beach", "FL", "18720"),
    ("Nassau", "BS", "10440"), ("Punta Cana", "DO", "3332"),
    ("Kauai", "HI", "513641"),
    # ── International 23x+ (verified via API probe) ──────────────────────────
    # Middle East (43x Riyadh tops Las Vegas)
    ("Riyadh", "SA", "5349"), ("Bahrain", "BH", "16630"),
    ("Abu Dhabi", "AE", "10182"), ("Dubai", "AE", "2994"),
    ("Cairo", "EG", "7923"), ("Doha", "QA", "4472"),
    ("Muscat", "OM", "6445"), ("Hurghada", "EG", "6700"),
    ("Sharm El Sheikh", "EG", "15897"),
    # Latin America
    ("Bogota", "CO", "4926"), ("Cartagena", "CO", "10838"),
    ("Medellin", "CO", "10309"), ("Cali", "CO", "15464"),
    ("Santa Marta", "CO", "7678"), ("Cusco", "PE", "16970"),
    ("Panama City", "PA", "3356"), ("Buenos Aires", "AR", "9294"),
    ("Sao Paulo", "BR", "16638"), ("Santiago", "CL", "86197"),
    ("Montevideo", "UY", "5534"), ("Quito", "EC", "9909"),
    ("Antigua Guatemala", "GT", "18181"),
    # Africa
    ("Zanzibar", "TZ", "9846"), ("Marrakech", "MA", "11825"),
    ("Fes", "MA", "12050"),
    # Southeast Asia
    ("Ho Chi Minh City", "VN", "13170"), ("Hanoi", "VN", "2758"),
    ("Colombo", "LK", "7835"), ("Cebu", "PH", "4001"),
    ("Manila", "PH", "1622"), ("Bangkok", "TH", "9395"),
    ("Bali", "ID", "17193"),
    # Europe
    ("Budapest", "HU", "10647"), ("Dubrovnik", "HR", "4839"),
    ("Santorini", "GR", "4254"), ("Istanbul", "TR", "14932"),
    ("Lisbon", "PT", "16364"), ("Athens", "GR", "16571"),
    ("Amalfi", "IT", "9286"),
    # East Asia
    ("Osaka", "JP", "9590"), ("Kyoto", "JP", "1784"),
    ("Hong Kong", "HK", "16808"), ("Singapore", "SG", "4064"),
    ("Tokyo", "JP", "5085"),
]


# ── API helpers ──────────────────────────────────────────────────────────────

async def search_city_date(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    city: str, state: str, agoda_id: str,
    check_in: datetime, check_out: datetime,
) -> list[dict[str, Any]]:
    """Search hotels for one city/date combo. Returns parsed deals above MIN_YIELD."""
    async with sem:
        await asyncio.sleep(random.uniform(0.02, 0.1))

        place_id = f"AGODA_CITY|{agoda_id}"
        ci = f"{check_in.month:02}/{check_in.day:02}/{check_in.year}"
        co = f"{check_out.month:02}/{check_out.day:02}/{check_out.year}"
        query_str = f"{city} ({state}), United States" if state in US_STATES else city

        try:
            r = await client.get(
                f"{BASE}/rest/aadvantage-hotels/searchRequest?"
                f"adults=2&checkIn={quote(ci, safe='')}&checkOut={quote(co, safe='')}"
                f"&children=0&currency=USD&language=en&locationType=CITY&mode=earn"
                f"&numberOfChildren=0&placeId={quote(place_id, safe='')}"
                f"&program=aadvantage&promotion&query={quote(query_str, safe='')}"
                f"&rooms=1&source=AGODA"
            )
            if r.status_code != 200:
                return [{"_error": f"search_request_{r.status_code}"}]
            uuid = r.json().get("uuid")
            if not uuid:
                return [{"_error": "no_uuid"}]
        except Exception as e:
            return [{"_error": f"search_request_exc_{type(e).__name__}"}]

        await asyncio.sleep(random.uniform(0.05, 0.15))

        try:
            r = await client.get(f"{BASE}/rest/aadvantage-hotels/search/{uuid}?pageSize=45&pageNumber=1")
            if r.status_code != 200:
                return [{"_error": f"search_results_{r.status_code}"}]
            results_list = r.json().get("results", [])
        except Exception as e:
            return [{"_error": f"search_results_exc_{type(e).__name__}"}]

        if not results_list:
            return []

        nights = (check_out - check_in).days
        deals = []
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
            if yield_ratio < MIN_YIELD:
                continue

            hotel_id = str(hotel.get("id", ""))
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
                "url": f"{BASE}/search?adults=2&checkIn={quote(ci, safe='')}&checkOut={quote(co, safe='')}&currency=USD&language=en&locationType=CITY&mode=earn&placeId={quote(place_id, safe='')}&program=aadvantage&query={quote(query_str, safe='')}&rooms=1&source=AGODA",
                "agoda_hotel_id": hotel_id,
                "scraped_at": datetime.now(UTC).isoformat(),
            })

        return deals


# ── Supabase helpers ─────────────────────────────────────────────────────────

def get_supabase():
    return create_client(
        os.environ["SUPABASE_URL"],
        os.environ["SUPABASE_SERVICE_ROLE_KEY"],
        options=ClientOptions(schema="aa_hotels"),
    )


def upsert_batch(sb, deals: list[dict[str, Any]]) -> int:
    if not deals:
        return 0
    stored = 0
    for i in range(0, len(deals), 100):
        batch = deals[i : i + 100]
        result = sb.table("deals").upsert(batch, on_conflict="hotel_name,check_in,check_out").execute()
        stored += len(result.data) if result.data else 0
    return stored


def get_completed_cities(sb, today_str: str) -> set[tuple[str, str]]:
    result = sb.table("scrape_progress").select("city,state").eq("scraped_date", today_str).execute()
    return {(r["city"], r["state"]) for r in (result.data or [])}


def mark_city_done(sb, city: str, state: str, today_str: str, deals_found: int):
    sb.table("scrape_progress").upsert(
        {"city": city, "state": state, "scraped_date": today_str, "deals_found": deals_found},
        on_conflict="city,state,scraped_date",
    ).execute()


# ── Main ─────────────────────────────────────────────────────────────────────

async def scrape_all() -> int:
    """Scrape remaining cities for today. Parallelizes ALL (city,date) pairs."""
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    today_str = today.strftime("%Y-%m-%d")
    dates = [(today + timedelta(days=d), today + timedelta(days=d + 1)) for d in range(1, DAYS_AHEAD + 1)]

    sb = get_supabase()
    sb.table("scrape_progress").delete().lt("scraped_date", today_str).execute()

    done = get_completed_cities(sb, today_str)
    remaining = [(c, s, a) for c, s, a in CITIES if (c, s) not in done]

    if not remaining:
        log.info(f"All {len(CITIES)} cities done today")
        return 0

    log.info(f"{len(done)} done, {len(remaining)} remaining ({len(remaining) * len(dates)} searches)")

    # Proxy setup
    proxy_user = os.environ.get("PROXY_USERNAME", "")
    proxy_pass = os.environ.get("PROXY_PASSWORD", "")
    proxy_url = f"http://{proxy_user}-rotate:{proxy_pass}@p.webshare.io:80" if proxy_user else None
    log.info(f"Proxy: {'rotating residential' if proxy_url else 'NONE (will hit Cloudflare)'}")

    sem = asyncio.Semaphore(MAX_CONCURRENT)
    total_stored = 0

    async with httpx.AsyncClient(
        timeout=30.0, headers=HEADERS, follow_redirects=True, proxy=proxy_url,
        limits=httpx.Limits(max_connections=100, max_keepalive_connections=60),
    ) as client:

        # Process city by city so we can mark progress + upsert incrementally
        for idx, (city, state, aid) in enumerate(remaining):
            # Fire all dates for this city in parallel
            tasks = [
                search_city_date(client, sem, city, state, aid, ci, co)
                for ci, co in dates
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Collect + dedupe, track errors
            best: dict[str, dict] = {}
            errors: dict[str, int] = {}
            for r in results:
                if isinstance(r, list):
                    for d in r:
                        if "_error" in d:
                            errors[d["_error"]] = errors.get(d["_error"], 0) + 1
                        elif "hotel_name" in d:
                            key = f"{d['hotel_name']}|{d['check_in']}"
                            if key not in best or d["yield_ratio"] > best[key]["yield_ratio"]:
                                best[key] = d

            unique = list(best.values())
            stored = upsert_batch(sb, unique) if unique else 0
            total_stored += stored
            mark_city_done(sb, city, state, today_str, stored)

            top_str = f" (top {max(d['yield_ratio'] for d in unique):.1f}x)" if unique else ""
            err_str = f" ERRORS: {errors}" if errors else ""
            log.info(f"[{idx+1}/{len(remaining)}] {city}, {state}: {stored} deals{top_str}{err_str}")

    # Clean past deals AFTER successful processing (not before — avoids empty DB on crash)
    deleted = sb.table("deals").delete().lt("check_in", today_str).execute()
    log.info(f"Run complete: {total_stored} deals, {len(done)+len(remaining)}/{len(CITIES)} cities done, cleaned past deals")
    return total_stored


async def main():
    log.info(f"AA Hotels scraper — {len(CITIES)} cities, {DAYS_AHEAD}d, {MIN_YIELD}x+, concurrency={MAX_CONCURRENT}")
    await scrape_all()


if __name__ == "__main__":
    asyncio.run(main())
