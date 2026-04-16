#!/usr/bin/env python3
"""SimplyMiles offer scraper.

Uses authenticated cookies (captured locally via scripts/capture_session.py,
pushed to GH secret SIMPLYMILES_SESSION_B64). httpx only — no Playwright at
scrape-time (Playwright storage_state is broken on Linux GH Actions runners,
see https://github.com/microsoft/playwright/issues/32302).

Writes to aa_tools.sm_offers (composite unique key).

Exit codes:
  0 — success
  2 — auth failure (session expired / rejected) — signals need to refresh
  1 — other error
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import sys
import urllib.parse
from datetime import datetime, UTC
from typing import Any

import httpx
from supabase import create_client, ClientOptions

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

API_URL = "https://www.simplymiles.com/get-pclo-and-rakuten-offers"
API_BODY = {"page_type": "landing"}


# ── Cookie loading ──────────────────────────────────────────────────────────

def load_cookies_from_env() -> list[dict[str, Any]]:
    """Load Playwright-shaped cookies from SIMPLYMILES_SESSION_B64 env var."""
    b64 = os.environ.get("SIMPLYMILES_SESSION_B64", "").strip()
    if not b64:
        raise RuntimeError("SIMPLYMILES_SESSION_B64 env var not set")
    try:
        raw = base64.b64decode(b64.encode())
        cookies = json.loads(raw)
    except Exception as e:
        raise RuntimeError(f"Could not decode SIMPLYMILES_SESSION_B64: {type(e).__name__}")
    if not isinstance(cookies, list):
        raise RuntimeError("Decoded cookies is not a list")
    return cookies


def load_cookies_from_file(path: str) -> list[dict[str, Any]]:
    with open(path) as f:
        cookies = json.load(f)
    if not isinstance(cookies, list):
        raise RuntimeError("Cookies file is not a list")
    return cookies


def cookies_to_headers(cookies: list[dict[str, Any]]) -> dict[str, str]:
    cookie_header = "; ".join(f"{c['name']}={c['value']}" for c in cookies if c.get("name"))
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "Cookie": cookie_header,
        "Referer": "https://www.simplymiles.com/",
        "Origin": "https://www.simplymiles.com",
    }
    for c in cookies:
        if c.get("name") == "XSRF-TOKEN":
            headers["X-XSRF-TOKEN"] = urllib.parse.unquote(c["value"])
            break
    return headers


# ── Offer parsing ────────────────────────────────────────────────────────────

def parse_offer_headline(headline: str) -> dict[str, Any]:
    """Parse the human-readable offer text into structured fields."""
    result: dict[str, Any] = {
        "offer_type": "unknown",
        "miles_amount": 0,
        "lp_amount": 0,
        "min_spend": None,
    }
    if not headline:
        return result
    t = headline.lower().strip()

    flat_pattern = r"(\d+)\s*miles?\s*\+\s*(\d+)\s*loyalty\s*points?\s*on\s*(?:a\s*)?purchase\s*of\s*\$(\d+(?:\.\d+)?)"
    m = re.search(flat_pattern, t)
    if m:
        return {
            "offer_type": "flat_bonus",
            "miles_amount": int(m.group(1)),
            "lp_amount": int(m.group(2)),
            "min_spend": float(m.group(3)),
        }

    per_dollar_pattern = r"(\d+)\s*miles?\s*\+\s*(\d+)\s*loyalty\s*points?\s*per\s*\$1"
    m = re.search(per_dollar_pattern, t)
    if m:
        return {
            "offer_type": "per_dollar",
            "miles_amount": int(m.group(1)),
            "lp_amount": int(m.group(2)),
            "min_spend": None,
        }

    miles_m = re.search(r"(\d+)\s*miles?", t)
    lp_m = re.search(r"(\d+)\s*loyalty\s*points?", t)
    spend_m = re.search(r"\$(\d+(?:\.\d+)?)", t)
    if miles_m:
        result["miles_amount"] = int(miles_m.group(1))
    if lp_m:
        result["lp_amount"] = int(lp_m.group(1))
    if spend_m:
        result["min_spend"] = float(spend_m.group(1))
    if "per" in t:
        result["offer_type"] = "per_dollar"
    elif result["min_spend"]:
        result["offer_type"] = "flat_bonus"
    return result


def normalize_merchant(name: str) -> str:
    n = (name or "").lower().strip()
    for suf in (".com", ".net", ".org", " inc", " inc.", " llc", " co", " co.", " stores", " store"):
        if n.endswith(suf):
            n = n[: -len(suf)]
            break
    n = re.sub(r"[^a-z0-9\s\-]", "", n)
    n = re.sub(r"[\s\-]+", " ", n)
    return re.sub(r"\s+", " ", n).strip()


def extract_offer(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Normalize one SimplyMiles offer dict to our row shape."""
    merchant = (raw.get("merchantName") or raw.get("merchant_name") or raw.get("name") or "").strip()
    headline = raw.get("headline") or raw.get("title") or raw.get("description") or ""
    if not merchant:
        return None

    parsed = parse_offer_headline(headline)
    if parsed["miles_amount"] == 0 and parsed["lp_amount"] == 0:
        return None

    expires_raw = raw.get("expiration") or raw.get("expires") or raw.get("expirationDate") or raw.get("endDate")
    expires_at: str | None = None
    if expires_raw:
        try:
            # Try multiple parse strategies
            for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%m/%d/%Y"):
                try:
                    expires_at = datetime.strptime(str(expires_raw)[:len(fmt) + 2], fmt).replace(tzinfo=UTC).isoformat()
                    break
                except ValueError:
                    continue
        except Exception:
            expires_at = None

    return {
        "offer_id": str(raw.get("id") or raw.get("offerId") or "") or None,
        "merchant_name": merchant,
        "merchant_name_normalized": normalize_merchant(merchant),
        "offer_type": parsed["offer_type"],
        "miles_amount": parsed["miles_amount"],
        "lp_amount": parsed["lp_amount"],
        "min_spend": parsed["min_spend"],
        "headline_raw": (headline or "")[:500],
        "expires_at": expires_at,
        "scraped_at": datetime.now(UTC).isoformat(),
    }


# ── Supabase ─────────────────────────────────────────────────────────────────

def get_supabase():
    return create_client(
        os.environ["SUPABASE_URL"],
        os.environ["SUPABASE_SERVICE_ROLE_KEY"],
        options=ClientOptions(schema="aa_tools"),
    )


def upsert_offers(sb, offers: list[dict[str, Any]]) -> int:
    stored = 0
    for i in range(0, len(offers), 500):
        batch = offers[i : i + 500]
        # sm_offers_unique_key covers (merchant_name_normalized, offer_type,
        # COALESCE(expires_at,'infinity'), miles_amount)
        result = sb.table("sm_offers").upsert(
            batch,
            on_conflict="merchant_name_normalized,offer_type,expires_at,miles_amount",
        ).execute()
        stored += len(result.data) if result.data else 0
    return stored


def record_session_success(sb) -> None:
    """Update aa_tools.session_state.last_success_at so digest can flag stale sessions."""
    now = datetime.now(UTC).isoformat()
    try:
        # First-run seed: if row doesn't exist yet, insert with placeholder cookies.
        # Subsequent runs: only touch last_success_at.
        existing = sb.table("session_state").select("source").eq("source", "simplymiles").execute()
        if existing.data:
            sb.table("session_state").update({"last_success_at": now}).eq("source", "simplymiles").execute()
        else:
            sb.table("session_state").insert(
                {
                    "source": "simplymiles",
                    "cookies_encrypted": b"\x00",  # placeholder — real cookies live in GH secret
                    "captured_at": now,
                    "last_success_at": now,
                    "captured_by": "scrape-simplymiles.yml",
                }
            ).execute()
    except Exception as e:
        log.warning(f"Could not update session_state: {type(e).__name__}")


# ── Main ─────────────────────────────────────────────────────────────────────

def run(cookies_path: str | None = None) -> int:
    try:
        cookies = load_cookies_from_file(cookies_path) if cookies_path else load_cookies_from_env()
    except RuntimeError as e:
        log.error(str(e))
        return 1

    log.info(f"Loaded {len(cookies)} cookies")
    headers = cookies_to_headers(cookies)
    if "X-XSRF-TOKEN" not in headers:
        log.error("No XSRF-TOKEN cookie present — session malformed, re-capture needed")
        return 2

    try:
        resp = httpx.post(API_URL, json=API_BODY, headers=headers, timeout=20.0, follow_redirects=False)
    except httpx.HTTPError as e:
        log.error(f"HTTP error: {type(e).__name__}")
        return 1

    if resp.status_code == 302:
        loc = resp.headers.get("Location", "")
        log.error(f"302 redirect — session likely expired (Location: {loc[:80]})")
        return 2
    if resp.status_code == 401:
        log.error("401 Unauthorized — session rejected, re-capture needed")
        return 2
    if resp.status_code >= 400:
        log.error(f"HTTP {resp.status_code} from SimplyMiles API")
        return 1

    try:
        data = resp.json()
    except Exception:
        log.error("SimplyMiles returned non-JSON (possibly a login page)")
        return 2

    raw_offers: list[dict[str, Any]] = []
    if isinstance(data, dict):
        for key in ("offers", "data", "response", "pclo", "rakuten"):
            val = data.get(key)
            if isinstance(val, list):
                raw_offers.extend(val)
        # Sometimes the API returns separate pclo + rakuten top-level arrays
    elif isinstance(data, list):
        raw_offers = data

    log.info(f"Received {len(raw_offers)} raw offers from API")
    if not raw_offers:
        # Could be legit empty day OR auth failure dressed as 200. Heuristic:
        # if the response was tiny (< 500 bytes), treat as suspect.
        if len(resp.content) < 500:
            log.warning("Empty response body likely auth failure — treating as error")
            return 2
        log.info("Zero offers but response body has content — assuming legitimate empty day")

    offers = [o for o in (extract_offer(r) for r in raw_offers) if o]
    log.info(f"Parsed {len(offers)}/{len(raw_offers)} offers into rows")

    sb = get_supabase()
    stored = upsert_offers(sb, offers)
    record_session_success(sb)
    log.info(f"Upserted {stored} offer rows")
    return 0


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--cookies", help="Path to cookies.json (local testing only)")
    args = parser.parse_args()
    sys.exit(run(args.cookies))
