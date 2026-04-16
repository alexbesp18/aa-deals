# Preserved Gems from aa-tools — 2026-04-16

Technical reference extracted from the dormant `aa-tools` monorepo before its deletion. These are hard-won API discoveries, auth flows, and parser recipes that would be expensive to rediscover. Each block is self-contained and ready to port into aa-deals scrapers.

Source: `/tmp/aa-audit/aa-tools/` (cloned from `alexbesp18/aa-tools`, single consolidation commit from 2026-03-21).

---

## 1. AAdvantage eShopping Portal — Cartera API

**Endpoint discovered 2024-12-28 via network inspection.** The portal's frontend calls a public Cartera Commerce API. No auth needed.

```python
CARTERA_API_URL = "https://api.cartera.com/content/v4/merchants/all"
CARTERA_PARAMS = {
    'brand_id': '251',        # AAdvantage eShopping
    'app_key': '9ec260e91abc101aaec68280da6a5487',
    'app_id': '672b9fbb',
    'limit': '2000',          # Get all merchants in one call
    'sort_by': 'name',
    'fields': 'name,type,id,showRebate,rebate,clickUrl,offers',
}

async with httpx.AsyncClient(timeout=30.0) as client:
    response = await client.get(CARTERA_API_URL, params=CARTERA_PARAMS)
    data = response.json()
    merchants = data.get('response', [])
    total = data.get('metadata', {}).get('total', len(merchants))
    # Each merchant has: name, id, showRebate, rebate (HTML string), clickUrl, offers[]
```

**Key fields per merchant**:
- `name` — display name
- `showRebate` — boolean, skip if false
- `rebate` — HTML string like `"Earn 2 miles/$"` or `"Now 4 miles/$"` (elevated)
- `offers` — array of promo objects (sometimes present)
- `clickUrl` — affiliate URL

**Fallback**: if Cartera API 403s/changes, scrape HTML directly (see §4).

---

## 2. SimplyMiles API

**Endpoint**: `https://www.simplymiles.com/get-pclo-and-rakuten-offers` (POST)

**Requires authenticated session cookies** (AA SSO login). Runs on Rakuten RCLON network — no public reverse engineering exists.

```python
# Request
cookie_str = '; '.join(f"{k}={v}" for k, v in cookies.items())
headers = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)',
    'Accept': 'application/json, text/plain, */*',
    'Content-Type': 'application/json',
    'Cookie': cookie_str,
    # XSRF-TOKEN header required
    'X-XSRF-TOKEN': xsrf_token,
}
body = {"page_type": "landing"}
```

**XSRF token extraction** (cookies must be URL-decoded for the token value):

```python
import urllib.parse
for c in cookies:
    if c['name'] == 'XSRF-TOKEN':
        xsrf_token = urllib.parse.unquote(c['value'])
```

---

## 3. SimplyMiles manual auth flow (setup_auth.py)

Headed Playwright + persistent context. User logs in manually, cookies get dumped to JSON.

```python
from playwright.async_api import async_playwright

SIMPLYMILES_URL = "https://www.simplymiles.com/"

async with async_playwright() as p:
    context = await p.chromium.launch_persistent_context(
        user_data_dir="./browser_data",
        headless=False,
        viewport={"width": 1280, "height": 800},
        args=["--disable-blink-features=AutomationControlled"],
    )
    page = await context.new_page()
    await page.goto(SIMPLYMILES_URL)
    input("Press Enter when you're logged in and can see your offers...")

    # Export cookies to JSON (the portable auth artifact)
    import json
    cookies = await context.cookies(["https://www.simplymiles.com"])
    with open("simplymiles_cookies.json", 'w') as f:
        json.dump(cookies, f, indent=2)

    await context.close()
```

For GH Actions: run this locally, then `gh secret set SIMPLYMILES_SESSION < simplymiles_cookies.json`. Workflow decodes the secret at runtime into the same JSON format.

---

## 4. SimplyMiles offer headline parser

Parses card-linked offer headlines like:
- `"135 miles + 135 Loyalty Points on a purchase of $5 or more"` → flat_bonus
- `"4 miles + 4 Loyalty Points per $1 spent on any purchase"` → per_dollar

```python
import re

def parse_offer_headline(headline: str) -> dict:
    result = {
        'offer_type': 'unknown',
        'miles_amount': 0,
        'lp_amount': 0,
        'min_spend': None,
    }
    text = headline.lower().strip()

    # Flat bonus
    flat_pattern = r'(\d+)\s*miles?\s*\+\s*(\d+)\s*loyalty\s*points?\s*on\s*(?:a\s*)?purchase\s*of\s*\$(\d+(?:\.\d+)?)'
    m = re.search(flat_pattern, text)
    if m:
        return {
            'offer_type': 'flat_bonus',
            'miles_amount': int(m.group(1)),
            'lp_amount': int(m.group(2)),
            'min_spend': float(m.group(3)),
        }

    # Per-dollar
    per_dollar_pattern = r'(\d+)\s*miles?\s*\+\s*(\d+)\s*loyalty\s*points?\s*per\s*\$1'
    m = re.search(per_dollar_pattern, text)
    if m:
        return {
            'offer_type': 'per_dollar',
            'miles_amount': int(m.group(1)),
            'lp_amount': int(m.group(2)),
            'min_spend': None,
        }

    # Fallback: extract individual numbers
    miles_m = re.search(r'(\d+)\s*miles?', text)
    lp_m = re.search(r'(\d+)\s*loyalty\s*points?', text)
    spend_m = re.search(r'\$(\d+(?:\.\d+)?)', text)
    if miles_m: result['miles_amount'] = int(miles_m.group(1))
    if lp_m: result['lp_amount'] = int(lp_m.group(1))
    if spend_m: result['min_spend'] = float(spend_m.group(1))
    result['offer_type'] = 'per_dollar' if 'per' in text else ('flat_bonus' if result['min_spend'] else 'unknown')
    return result
```

---

## 5. Portal miles rate parser

Handles all known eShopping rate formats:

```python
import re

def parse_miles_rate(text: str) -> float | None:
    """
    Parses:
      "Earn 2 miles/$", "Now 4 miles/$" (elevated), "0.5 mile/$"
      "Up to 4,900 miles" (flat bonus), "Earn 600 miles"
      "Xpt/$", "X point/$", "X per dollar", "5X"
    """
    if not text:
        return None
    text = text.lower().strip().replace(',', '')

    # X miles/$ or X mile/$
    m = re.search(r'(\d+(?:\.\d+)?)\s*miles?/\$', text)
    if m: return float(m.group(1))

    # Earn X miles/$, Now X miles/$, Was X miles/$
    m = re.search(r'(?:earn|now|was)\s*(\d+(?:\.\d+)?)\s*miles?/\$', text)
    if m: return float(m.group(1))

    # X mi/$
    m = re.search(r'(\d+(?:\.\d+)?)\s*mi/\$', text)
    if m: return float(m.group(1))

    # Flat bonus "X miles" (no /$)
    if re.search(r'(\d+)\s*miles?(?!\s*/)', text) and '/$' not in text:
        m = re.search(r'(\d+(?:\.\d+)?)\s*miles?', text)
        if m: return float(m.group(1))

    # Points variants
    m = re.search(r'(\d+(?:\.\d+)?)\s*(?:pt|points?)(?:\s*/\s*\$)?', text)
    if m: return float(m.group(1))

    m = re.search(r'(\d+(?:\.\d+)?)\s*per\s*dollar', text)
    if m: return float(m.group(1))

    # "5X" notation
    m = re.search(r'(\d+(?:\.\d+)?)\s*x', text)
    if m: return float(m.group(1))

    return None


def is_bonus_rate(text: str) -> bool:
    text = (text or "").lower()
    return any(i in text for i in ['bonus', 'elevated', 'special', 'limited time', 'up to', 'double', 'triple'])
```

---

## 6. Portal HTML selectors (fallback path)

Verified from eShopping portal inspection. Portal uses `mn_` (merchant network) prefixed classes.

```python
from bs4 import BeautifulSoup

soup = BeautifulSoup(html, 'lxml')
rebate_elements = soup.select('.mn_rebateV4')

for rebate in rebate_elements:
    parent = rebate.find_parent(['li', 'div', 'td'])
    name_link = parent.select_one('a')
    merchant_name = name_link.get_text(strip=True)

    old_value = rebate.select_one('.mn_elevationOldValue')   # base rate
    new_value = rebate.select_one('.mn_elevationNewValue')   # current (elevated) rate
    tiered = rebate.select_one('.mn_rebateTiered, .mn_tieredPrefix')

    # Prefer new value (current), fall back to old
    rate_text = new_value.get_text(strip=True) if new_value else old_value.get_text(strip=True)
    is_elevated = bool(old_value) or bool(tiered)

    url = name_link.get('href', '')
    # Relative URLs: prefix with "https://www.aadvantageeshopping.com"
```

**Fallback if `mn_` classes absent**: `soup.select('a[href*="/s__"]')` — store links follow `/s__{id}` pattern.

---

## 7. Merchant name normalizer + fuzzy match

For matching SimplyMiles offers to Portal merchants (different casing, suffixes, aliases).

```python
import re
from rapidfuzz import fuzz, process

def normalize_merchant(name: str) -> str:
    if not name: return ""
    name = name.lower().strip()

    # Strip common corporate suffixes
    suffixes = [
        '.com', '.net', '.org', '.co', '.io',
        ' inc', ' inc.', ' llc', ' llc.', ' corp', ' corp.',
        ' co', ' co.', ' company', ' corporation',
        ' stores', ' store', ' shop', ' online',
        ' us', ' usa', ' america',
    ]
    for suffix in suffixes:
        if name.endswith(suffix):
            name = name[:-len(suffix)]

    name = re.sub(r'[^a-z0-9\s\-]', '', name)       # strip special chars
    name = re.sub(r'[\s\-]+', ' ', name)            # collapse whitespace/hyphens
    name = re.sub(r'\s+', ' ', name).strip()

    # Apply aliases (e.g., "macys" -> "macy's")
    # Aliases table should live in the scraper config
    return name


def find_best_match(name: str, candidates: list[str], threshold: int = 85) -> tuple[str, int] | None:
    """token_sort_ratio handles word order differences."""
    result = process.extractOne(name, candidates, scorer=fuzz.token_sort_ratio, score_cutoff=threshold)
    if result:
        matched_name, score, _ = result
        return matched_name, score
    return None
```

---

## 8. Stack detector — SM × Portal × CC composition

The actual valuable logic from `001/core/stack_detector.py`. Simplified for porting:

```python
def detect_stacks(sm_offers: list[dict], portal_rates: list[dict], cc_rate: float = 1.0) -> list[dict]:
    """
    For each SimplyMiles offer, find matching Portal merchant (exact or fuzzy),
    compute combined yield = portal_miles + sm_miles + cc_miles per dollar.
    """
    portal_lookup = {r['merchant_name_normalized']: r for r in portal_rates}
    portal_names = list(portal_lookup.keys())

    opportunities = []
    for offer in sm_offers:
        sm_norm = offer['merchant_name_normalized']

        # Exact match first, then fuzzy
        portal_rate = portal_lookup.get(sm_norm)
        if not portal_rate:
            match = find_best_match(sm_norm, portal_names, threshold=85)
            if not match:
                continue
            portal_rate = portal_lookup[match[0]]

        # Compute combined yield
        portal_miles_per_dollar = portal_rate['miles_per_dollar']
        if offer['offer_type'] == 'flat_bonus':
            # e.g., "135 miles on purchase of $5" -> 27 miles/$
            sm_per_dollar = offer['miles_amount'] / offer['min_spend']
        else:
            sm_per_dollar = offer['miles_amount']  # "X miles per $1"

        combined_yield = portal_miles_per_dollar + sm_per_dollar + cc_rate

        opportunities.append({
            'merchant_name': offer['merchant_name'],
            'portal_rate': portal_miles_per_dollar,
            'sm_type': offer['offer_type'],
            'sm_rate': sm_per_dollar,
            'sm_min_spend': offer.get('min_spend'),
            'sm_expires': offer.get('expires_at'),
            'cc_rate': cc_rate,
            'combined_yield': combined_yield,
        })

    opportunities.sort(key=lambda o: o['combined_yield'], reverse=True)
    return opportunities
```

**In the rehaul**: express this as a SQL view over `aa_tools.portal_rates` JOIN `aa_tools.sm_offers`, not Python. The view stays fresh; a table goes stale.

---

## 9. Streak optimizer (hotels, multi-night sequences)

From `002/lib/optimizer.ts`. Finds optimal 1-10 night sequences where each night can be a different hotel. Unique capability — aa-deals' current dashboard only shows single-night yields.

```typescript
import { HotelRate, NightSelection, StreakResult } from './types'

function addDays(dateStr: string, days: number): string {
  // ⚠️ Local-time parsing required to avoid UTC off-by-one
  // Per Alex's global date-formatting rule:
  const [y, m, d] = dateStr.split('-').map(Number)
  const date = new Date(y!, m! - 1, d!)
  date.setDate(date.getDate() + days)
  return date.toISOString().split('T')[0]
}

function findBestForNight(rates: HotelRate[], targetDate: string): NightSelection | null {
  const matchingRates = rates.filter(r => r.stay_date.split('T')[0] === targetDate)
  if (matchingRates.length === 0) return null
  const best = matchingRates.sort((a, b) => b.pts_per_dollar - a.pts_per_dollar)[0]
  return {
    date: targetDate,
    hotel_name: best.hotel_name,
    cash_price: best.cash_price,
    points_required: best.points_required,
    pts_per_dollar: best.pts_per_dollar,
    stars: best.stars,
  }
}

export function findOptimalStreaks(rates: HotelRate[], checkIn: string): StreakResult[] {
  const results: StreakResult[] = []
  for (let duration = 1; duration <= 10; duration++) {
    const nights: NightSelection[] = []
    let totalPoints = 0
    let totalCost = 0

    for (let i = 0; i < duration; i++) {
      const targetDate = addDays(checkIn, i)
      const best = findBestForNight(rates, targetDate)
      if (best) {
        nights.push(best)
        totalPoints += best.points_required
        totalCost += best.cash_price
      }
    }

    if (nights.length === duration) {
      results.push({
        duration,
        nights,
        total_points: totalPoints,
        total_cost: totalCost,
        avg_pts_per_dollar: totalCost > 0 ? Math.round((totalPoints / totalCost) * 100) / 100 : 0,
      })
    }
  }
  return results
}
```

**Note**: The original used `new Date(dateStr)` which is UTC — produced off-by-one errors. Patched above to local-time parsing per Alex's global rule.

**Also from 002**: anomaly detection (`anomaly.ts:93-142`) — flags same-hotel 4-7 night stays where pts/$ ≥ 1.5× historical DoW average. Second useful algorithm; port if streak optimizer UI works.

---

## 10. Agoda city ID corpus (US MSAs)

`004/core/city_discovery.py` has 210 US MSA→Agoda ID mappings organized in discovery batches. aa-deals has 151 globally (pruned yield-verified). The 004 list adds ~60 smaller US MSAs that may be worth probing if scraper capacity allows.

**Don't import blindly** — aa-deals dropped 44 US cities that produced zero deals. Some 004 entries likely fall in that bucket. Merge carefully.

---

## 11. Date rotation (time-of-day sampling)

`004/core/date_rotation.py` + `railway/auto_pattern_scrape.py:30-49` — CT-anchored morning/afternoon/evening sampling, 3x daily. Potentially more thorough than aa-deals' current blanket sweep. Optional ~30 LOC extract if the AA Hotels nerf doesn't kill the scraper entirely.

---

## Things explicitly NOT worth preserving

- `001/core/database.py` (1,603 LOC SQLite DAL) — replaced by 12-line supabase-py usage in aa-deals
- `001/alerts/formatter.py` (1,313 LOC HTML email templates) — simpler Resend digest sufficient
- `001/verification.py`, `001/optimizer.py` — academic; unused in practice
- `001/scripts/session_keepalive.py` — invented complexity; GH secret model is simpler
- 80+ test files — most test the scaffolding, not the scrapers
- `002/python/scrape_hotels.py` — duplicates aa-deals scraper, uses Desktop path import that's broken
- `003/*` — create-next-app template, 0 original logic
- `004/web/app.py` — FastAPI + Jinja2 dashboard, less evolved than aa-deals Next.js version
- `004/railway/*` — dead, the whole point of the rehaul is killing Railway

---

## Provenance

- `001-aa-scraper` commits range 2024-12-28 (initial) → 2026-01-04 (Supabase migration, last real work)
- `002-aa-streak-optimizer` — initial 2026-01-17, no further iteration
- `003-quick-aa-hotels` — initial 2025-12-27, one "doclikealex" commit, abandoned
- `004-us-hotel-scraper` — 2026-01-09 to 2026-01-18, fast iteration then abandoned
- All 4 consolidated into `aa-tools` monorepo 2026-03-21 (single "Initial consolidation" commit)
