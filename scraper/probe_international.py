#!/usr/bin/env python3
"""
Probe ~80 international cities via AA Hotels API for high-yield deals (23x+).
One date search per city (14 days out, 1 night). Sequential with 2s delay.
"""

import asyncio
import time
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import quote

import httpx

BASE = "https://www.aadvantagehotels.com"
PROXY = "http://REDACTED:REDACTED@p.webshare.io:80"
HIGH_YIELD_THRESHOLD = 23.0
DELAY_BETWEEN_CITIES = 2.0

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.5",
}

# (city, country_code, agoda_id)
CITIES: list[tuple[str, str, str]] = [
    # Middle East / North Africa
    ("Abu Dhabi", "AE", "5786"),
    ("Doha", "QA", "3642"),
    ("Amman", "JO", "5765"),
    ("Beirut", "LB", "5765"),
    ("Muscat", "OM", "8635"),
    ("Riyadh", "SA", "6038"),
    ("Jeddah", "SA", "14260"),
    ("Bahrain", "BH", "7770"),
    ("Sharm El Sheikh", "EG", "1007"),
    ("Hurghada", "EG", "5463"),
    ("Cairo", "EG", "13302"),
    ("Casablanca", "MA", "17337"),
    ("Fes", "MA", "12050"),
    ("Tangier", "MA", "11826"),
    # South America
    ("Santiago", "CL", "7183"),
    ("Sao Paulo", "BR", "11462"),
    ("Rio de Janeiro", "BR", "10553"),
    ("Montevideo", "UY", "3679"),
    ("Quito", "EC", "10666"),
    ("Guayaquil", "EC", "15305"),
    ("Cusco", "PE", "12061"),
    ("Santa Marta", "CO", "8523"),
    ("Cali", "CO", "7285"),
    ("Panama City", "PA", "5765"),
    # Caribbean
    ("Turks and Caicos", "TC", "5746"),
    ("Grand Cayman", "KY", "8050"),
    ("Barbados", "BB", "4694"),
    ("St. Maarten", "SX", "7960"),
    ("Curacao", "CW", "5503"),
    ("Bermuda", "BM", "4145"),
    ("Antigua", "AG", "9345"),
    ("St. Lucia", "LC", "14139"),
    ("Trinidad", "TT", "16070"),
    # Southeast Asia
    ("Kuala Lumpur", "MY", "8395"),
    ("Penang", "MY", "8393"),
    ("Manila", "PH", "8639"),
    ("Cebu", "PH", "9498"),
    ("Ho Chi Minh City", "VN", "13170"),
    ("Hanoi", "VN", "2758"),
    ("Da Nang", "VN", "9424"),
    ("Chiang Mai", "TH", "7401"),
    ("Phuket", "TH", "2093"),
    ("Phnom Penh", "KH", "9453"),
    ("Siem Reap", "KH", "2792"),
    ("Colombo", "LK", "5765"),
    ("Taipei", "TW", "4951"),
    ("Hong Kong", "HK", "7627"),
    # Europe
    ("Barcelona", "ES", "4698"),
    ("Madrid", "ES", "5765"),
    ("Paris", "FR", "15470"),
    ("Rome", "IT", "16594"),
    ("Milan", "IT", "12089"),
    ("Athens", "GR", "3924"),
    ("Budapest", "HU", "10647"),
    ("Dubrovnik", "HR", "2297"),
    ("Santorini", "GR", "4254"),
    ("Amalfi", "IT", "14438"),
    ("Porto", "PT", "8738"),
    ("Berlin", "DE", "2366"),
    ("Amsterdam", "NL", "15826"),
    ("Vienna", "AT", "2081"),
    ("Zurich", "CH", "13506"),
    ("Edinburgh", "GB", "2289"),
    # Africa
    ("Cape Town", "ZA", "1063"),
    ("Nairobi", "KE", "8944"),
    ("Zanzibar", "TZ", "7762"),
    # East Asia
    ("Osaka", "JP", "3472"),
    ("Kyoto", "JP", "1784"),
    ("Beijing", "CN", "1281"),
    ("Shanghai", "CN", "1519"),
]


async def search_city(
    client: httpx.AsyncClient,
    city: str,
    country_code: str,
    agoda_id: str,
    check_in: datetime,
    check_out: datetime,
) -> list[dict[str, Any]]:
    """Search one city for one date. Returns all hotels with yield data."""
    place_id = f"AGODA_CITY|{agoda_id}"
    ci = f"{check_in.month:02}/{check_in.day:02}/{check_in.year}"
    co = f"{check_out.month:02}/{check_out.day:02}/{check_out.year}"
    query_str = f"{city}, {country_code}"

    # Step 1: initiate search
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
            return []
        uuid = r.json().get("uuid")
        if not uuid:
            return []
    except Exception as e:
        print(f"  ERROR (search init): {e}")
        return []

    # Small delay before fetching results
    await asyncio.sleep(0.5)

    # Step 2: fetch results
    try:
        r = await client.get(
            f"{BASE}/rest/aadvantage-hotels/search/{uuid}?pageSize=45&pageNumber=1"
        )
        if r.status_code != 200:
            return []
        results_list = r.json().get("results", [])
    except Exception as e:
        print(f"  ERROR (results fetch): {e}")
        return []

    if not results_list:
        return []

    nights = (check_out - check_in).days
    hotels = []
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

        total_miles = max(
            int(h.get("rewards", 0)),
            int(h.get("roomTypeResultTeaser", {}).get("rewards", 0)),
        )
        if total_miles <= 0:
            continue

        yield_ratio = total_miles / total_cost

        hotels.append({
            "name": name,
            "stars": int(hotel.get("stars", 0)),
            "cost": round(total_cost, 2),
            "miles": total_miles,
            "yield": round(yield_ratio, 2),
        })

    # Sort by yield descending
    hotels.sort(key=lambda x: x["yield"], reverse=True)
    return hotels


async def main():
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    check_in = today + timedelta(days=14)
    check_out = check_in + timedelta(days=1)

    print("=" * 90)
    print(f"AA Hotels International Probe — {len(CITIES)} cities")
    print(f"Check-in: {check_in.strftime('%Y-%m-%d')} | Check-out: {check_out.strftime('%Y-%m-%d')}")
    print(f"Proxy: rotating residential | High-yield threshold: {HIGH_YIELD_THRESHOLD}x+")
    print("=" * 90)

    high_yield_deals: list[dict] = []
    all_results: list[dict] = []

    async with httpx.AsyncClient(
        timeout=30.0,
        headers=HEADERS,
        follow_redirects=True,
        proxy=PROXY,
    ) as client:
        for idx, (city, cc, aid) in enumerate(CITIES):
            print(f"\n[{idx + 1}/{len(CITIES)}] {city}, {cc} (agoda_id={aid})")

            hotels = await search_city(client, city, cc, aid, check_in, check_out)

            city_result = {
                "city": city,
                "country": cc,
                "hotel_count": len(hotels),
                "top_yield": hotels[0]["yield"] if hotels else 0,
                "top_3": hotels[:3],
            }
            all_results.append(city_result)

            if not hotels:
                print(f"  -> 0 hotels found")
            else:
                print(f"  -> {len(hotels)} hotels | top yield: {hotels[0]['yield']:.1f}x")
                for i, h in enumerate(hotels[:3]):
                    flag = " *** HIGH YIELD ***" if h["yield"] >= HIGH_YIELD_THRESHOLD else ""
                    print(
                        f"     #{i + 1}: {h['name'][:55]:<55} "
                        f"${h['cost']:>8.2f} | {h['miles']:>7,} mi | {h['yield']:>6.1f}x{flag}"
                    )

                # Collect high-yield deals
                for h in hotels:
                    if h["yield"] >= HIGH_YIELD_THRESHOLD:
                        high_yield_deals.append({
                            "city": city,
                            "country": cc,
                            **h,
                        })

            # Delay between cities
            if idx < len(CITIES) - 1:
                await asyncio.sleep(DELAY_BETWEEN_CITIES)

    # ── Summary ──────────────────────────────────────────────────────────────
    print("\n" + "=" * 90)
    print("SUMMARY")
    print("=" * 90)

    # Cities with results, sorted by top yield
    cities_with_results = [r for r in all_results if r["hotel_count"] > 0]
    cities_with_results.sort(key=lambda x: x["top_yield"], reverse=True)

    print(f"\nCities scanned: {len(all_results)}")
    print(f"Cities with results: {len(cities_with_results)}")
    print(f"Cities with 0 hotels: {len(all_results) - len(cities_with_results)}")

    # Top 20 cities by yield
    print(f"\n{'─' * 90}")
    print("TOP 20 CITIES BY YIELD:")
    print(f"{'─' * 90}")
    for i, r in enumerate(cities_with_results[:20]):
        flag = " *** HIGH YIELD ***" if r["top_yield"] >= HIGH_YIELD_THRESHOLD else ""
        print(
            f"  {i + 1:>2}. {r['city']:<25} {r['country']}  "
            f"| {r['hotel_count']:>3} hotels | top: {r['top_yield']:>6.1f}x{flag}"
        )

    # All high-yield deals
    if high_yield_deals:
        high_yield_deals.sort(key=lambda x: x["yield"], reverse=True)
        print(f"\n{'─' * 90}")
        print(f"ALL HIGH-YIELD DEALS ({HIGH_YIELD_THRESHOLD}x+): {len(high_yield_deals)} found")
        print(f"{'─' * 90}")
        for i, d in enumerate(high_yield_deals):
            print(
                f"  {i + 1:>3}. {d['city']:<20} {d['country']} | {d['name'][:45]:<45} "
                f"| ${d['cost']:>8.2f} | {d['miles']:>7,} mi | {d['yield']:>6.1f}x"
            )
    else:
        print(f"\nNo deals found at {HIGH_YIELD_THRESHOLD}x+ threshold.")

    # Zero-result cities
    zero_cities = [r for r in all_results if r["hotel_count"] == 0]
    if zero_cities:
        print(f"\n{'─' * 90}")
        print(f"CITIES WITH 0 HOTELS ({len(zero_cities)}):")
        print(f"{'─' * 90}")
        print("  " + ", ".join(f"{r['city']} ({r['country']})" for r in zero_cities))

    print(f"\n{'=' * 90}")
    print("PROBE COMPLETE")
    print(f"{'=' * 90}")


if __name__ == "__main__":
    asyncio.run(main())
