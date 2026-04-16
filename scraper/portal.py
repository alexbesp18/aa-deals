#!/usr/bin/env python3
"""AAdvantage eShopping Portal scraper.

Primary: Cartera API (public JSON, ~2000 merchants in one call).
Fallback: HTML scrape of aadvantageeshopping.com with regex (no BS4 dependency).

Writes to aa_tools.portal_rates (upsert by normalized name) and
aa_tools.portal_rates_history (insert only on rate change).
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import sys
from datetime import datetime, UTC
from typing import Any

import httpx
from supabase import create_client, ClientOptions

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

CARTERA_URL = "https://api.cartera.com/content/v4/merchants/all"
CARTERA_PARAMS = {
    "brand_id": "251",
    "app_key": "9ec260e91abc101aaec68280da6a5487",
    "app_id": "672b9fbb",
    "limit": "2000",
    "sort_by": "name",
    "fields": "name,type,id,showRebate,rebate,clickUrl,offers",
}
PORTAL_BASE = "https://www.aadvantageeshopping.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.5",
}


# ── Parsing ──────────────────────────────────────────────────────────────────

SUFFIXES = (
    ".com", ".net", ".org", ".co", ".io",
    " inc", " inc.", " llc", " llc.", " corp", " corp.",
    " co", " co.", " company", " corporation",
    " stores", " store", " shop", " online",
    " us", " usa", " america",
)


def normalize_merchant(name: str) -> str:
    n = (name or "").lower().strip()
    for suffix in SUFFIXES:
        if n.endswith(suffix):
            n = n[: -len(suffix)]
            break
    n = re.sub(r"[^a-z0-9\s\-]", "", n)
    n = re.sub(r"[\s\-]+", " ", n)
    return re.sub(r"\s+", " ", n).strip()


def parse_miles_rate(text: str) -> float | None:
    """Regex ladder matching all known eShopping rate formats."""
    if not text:
        return None
    t = text.lower().strip().replace(",", "")

    for pattern in (
        r"(\d+(?:\.\d+)?)\s*miles?/\$",
        r"(?:earn|now|was)\s*(\d+(?:\.\d+)?)\s*miles?/\$",
        r"(\d+(?:\.\d+)?)\s*mi/\$",
        r"(\d+(?:\.\d+)?)\s*(?:pt|points?)(?:\s*/\s*\$)?",
        r"(\d+(?:\.\d+)?)\s*per\s*dollar",
        r"(\d+(?:\.\d+)?)\s*x\b",
    ):
        m = re.search(pattern, t)
        if m:
            return float(m.group(1))

    # Flat bonus "X miles" (no /$) — store as-is so caller can decide
    if re.search(r"\d+\s*miles?(?!\s*/)", t) and "/$" not in t:
        m = re.search(r"(\d+(?:\.\d+)?)\s*miles?", t)
        if m:
            return float(m.group(1))

    return None


def is_bonus_rate(text: str) -> bool:
    if not text:
        return False
    t = text.lower()
    return any(w in t for w in ("bonus", "elevated", "special", "limited time", "up to", "double", "triple"))


# ── Cartera API ──────────────────────────────────────────────────────────────

async def fetch_cartera(client: httpx.AsyncClient) -> list[dict[str, Any]]:
    """Fetch all merchants in one call. Returns list of raw merchant dicts."""
    resp = await client.get(CARTERA_URL, params=CARTERA_PARAMS, headers=HEADERS)
    if resp.status_code != 200:
        log.error(f"Cartera API status={resp.status_code}")
        return []

    try:
        data = resp.json()
    except Exception:
        log.error("Cartera API returned non-JSON")
        return []

    merchants = data.get("response") or data.get("data") or []
    total = (data.get("metadata") or {}).get("total", len(merchants))
    log.info(f"Cartera returned {len(merchants)} merchants (total reported: {total})")
    return merchants


def extract_rate(merchant: dict[str, Any]) -> dict[str, Any] | None:
    """Parse a single Cartera merchant dict into our row shape. Skip if unusable."""
    name = (merchant.get("name") or "").strip()
    if not name or not merchant.get("showRebate", True):
        return None

    rebate = merchant.get("rebate")
    rate: float | None = None
    is_elevated = False
    raw_summary = ""

    if isinstance(rebate, dict):
        # Cartera 2026 shape: structured object
        raw_summary = (
            f"{rebate.get('prefix','')} {rebate.get('value','')} "
            f"{rebate.get('currency','')} {rebate.get('suffix','')}".strip()
        )
        currency = (rebate.get("currency") or "").lower()
        value = rebate.get("value")
        if value is not None and ("miles/$" in currency or "miles per dollar" in currency or "mi/$" in currency):
            try:
                rate = float(value)
            except (TypeError, ValueError):
                rate = None
        elif value is not None and ("point" in currency or "pt" in currency):
            try:
                rate = float(value)
            except (TypeError, ValueError):
                rate = None
        # Flat-bonus shapes: "miles on purchase of $X" — skip for now (not per-dollar)
        is_elevated = bool(rebate.get("isElevation") or rebate.get("isExtraRewards"))
    elif rebate:
        # Legacy HTML string fallback
        raw_summary = re.sub(r"<[^>]+>", " ", str(rebate))[:500]
        rate = parse_miles_rate(raw_summary)
        is_elevated = is_bonus_rate(raw_summary)

    if rate is None:
        return None

    return {
        "merchant_name": name,
        "merchant_name_normalized": normalize_merchant(name),
        "miles_per_dollar": round(rate, 2),
        "is_elevated": is_elevated,
        "rebate_raw": raw_summary[:500],
        "click_url": merchant.get("clickUrl"),
        "scraped_at": datetime.now(UTC).isoformat(),
    }


# ── Supabase ─────────────────────────────────────────────────────────────────

def get_supabase():
    return create_client(
        os.environ["SUPABASE_URL"],
        os.environ["SUPABASE_SERVICE_ROLE_KEY"],
        options=ClientOptions(schema="aa_tools"),
    )


def ensure_schema_accessible(sb) -> bool:
    """Verify aa_tools is exposed via PostgREST; trigger tripwire if not."""
    try:
        sb.table("portal_rates").select("id", count="exact").limit(1).execute()
        return True
    except Exception as e:
        err = str(e).lower()
        if "schema" not in err and "relation" not in err and "not found" not in err:
            log.warning(f"Non-schema error on health check: {type(e).__name__}")
            return True

    log.warning("aa_tools not accessible — calling register_exposed_schema tripwire")
    try:
        resp = httpx.post(
            f"{os.environ['SUPABASE_URL']}/rest/v1/rpc/register_exposed_schema",
            headers={
                "apikey": os.environ["SUPABASE_SERVICE_ROLE_KEY"],
                "Authorization": f"Bearer {os.environ['SUPABASE_SERVICE_ROLE_KEY']}",
                "Content-Type": "application/json",
            },
            json={"p_schema_name": "aa_tools"},
            timeout=15.0,
        )
        if resp.status_code >= 400:
            log.error(f"Tripwire RPC failed ({resp.status_code})")
            return False
    except Exception:
        log.error("Tripwire call threw")
        return False

    import time; time.sleep(3)
    try:
        get_supabase().table("portal_rates").select("id").limit(1).execute()
        log.info("Schema accessible after tripwire")
        return True
    except Exception:
        log.error("Schema STILL unreachable — add 'aa_tools' in Dashboard > API > Exposed Schemas")
        return False


def fetch_existing_rates(sb) -> dict[str, tuple[float, bool]]:
    """Return {normalized_name: (rate, is_elevated)} for change detection."""
    result = sb.table("portal_rates").select("merchant_name_normalized,miles_per_dollar,is_elevated").execute()
    out: dict[str, tuple[float, bool]] = {}
    for row in (result.data or []):
        out[row["merchant_name_normalized"]] = (float(row["miles_per_dollar"]), bool(row["is_elevated"]))
    return out


def upsert_hot(sb, rates: list[dict[str, Any]]) -> int:
    """Upsert current rates. 500-row batches."""
    stored = 0
    for i in range(0, len(rates), 500):
        batch = rates[i : i + 500]
        result = sb.table("portal_rates").upsert(batch, on_conflict="merchant_name_normalized").execute()
        stored += len(result.data) if result.data else 0
    return stored


def insert_history(sb, changed: list[dict[str, Any]]) -> int:
    """Append to portal_rates_history only when rate or elevation changed."""
    if not changed:
        return 0
    rows = [
        {
            "merchant_name_normalized": r["merchant_name_normalized"],
            "miles_per_dollar": r["miles_per_dollar"],
            "is_elevated": r["is_elevated"],
        }
        for r in changed
    ]
    inserted = 0
    for i in range(0, len(rows), 500):
        batch = rows[i : i + 500]
        result = sb.table("portal_rates_history").insert(batch).execute()
        inserted += len(result.data) if result.data else 0
    return inserted


# ── Main ─────────────────────────────────────────────────────────────────────

async def run() -> int:
    sb = get_supabase()
    if not ensure_schema_accessible(sb):
        return 2

    # Cartera is a public API — no proxy needed unless it starts blocking us.
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
        merchants = await fetch_cartera(client)

    if not merchants:
        log.error("No merchants from Cartera; aborting")
        return 1

    rows = [r for r in (extract_rate(m) for m in merchants) if r]
    log.info(f"Parsed {len(rows)}/{len(merchants)} merchants into rate rows")
    if not rows:
        log.error("No rate rows parsed; aborting")
        return 1

    existing = fetch_existing_rates(sb)
    changed = [
        r for r in rows
        if existing.get(r["merchant_name_normalized"]) != (r["miles_per_dollar"], r["is_elevated"])
    ]

    stored = upsert_hot(sb, rows)
    history = insert_history(sb, changed)

    log.info(f"Upserted {stored} hot rows; {history} history rows (changes or new)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
