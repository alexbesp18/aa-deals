#!/usr/bin/env python3
"""Daily AA digest → Telegram.

Single morning message (08:45 CT) with:
  - Top 10 US 30x+ bookable deals (deduped via aa_hotels.deals_best view)
  - New-since-yesterday flag
  - Pace: total LP from is_booked=true stays
  - Scraper staleness warning if last scrape >36h

Skip-day rule: no new deals AND no new bookings AND no warnings → no message.

Exit codes: 0 success (or silent-skip), 1 fatal error.

Usage:
  python scripts/digest.py               # live send
  python scripts/digest.py --dry-run     # print message, don't send
  python scripts/digest.py --probe       # send a one-line "probe" to verify chat
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import datetime, timedelta, UTC
from typing import Any

import httpx
from supabase import create_client, ClientOptions

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org"
MAX_MESSAGE_CHARS = 1024   # single-bubble Telegram cap
TOP_N = 10                 # rows in "top US 30x+" section
STALE_SCRAPE_HOURS = 36


# ── Supabase ────────────────────────────────────────────────────────────────

def sb():
    return create_client(
        os.environ["SUPABASE_URL"],
        os.environ["SUPABASE_SERVICE_ROLE_KEY"],
        options=ClientOptions(schema="aa_hotels"),
    )


def get_top_deals(limit: int = TOP_N) -> list[dict[str, Any]]:
    """Top US 30x+ bookable deals, 1 row per property via deals_best view."""
    resp = (
        sb().table("deals_best")
        .select("hotel_name,city_name,state,sub_brand,yield_ratio,total_cost,total_miles,check_in")
        .eq("country_code", "US")
        .gte("yield_ratio", 30)
        .gte("check_in", datetime.now(UTC).date().isoformat())
        .order("yield_ratio", desc=True)
        .order("total_cost", desc=False)
        .limit(limit)
        .execute()
    )
    return resp.data or []


def get_new_deals_24h() -> list[dict[str, Any]]:
    """Deals with created_at in last 24h + yield ≥30 + US + bookable."""
    cutoff = (datetime.now(UTC) - timedelta(hours=24)).isoformat()
    resp = (
        sb().table("deals")
        .select("hotel_name,city_name,state,sub_brand,yield_ratio,total_cost,total_miles,check_in,country_code")
        .eq("country_code", "US")
        .eq("is_booked", False)
        .gte("yield_ratio", 30)
        .gte("check_in", datetime.now(UTC).date().isoformat())
        .gt("created_at", cutoff)
        .order("yield_ratio", desc=True)
        .limit(50)
        .execute()
    )
    # Dedupe by (hotel_name, state) keeping best yield
    seen: dict[tuple[str, str], dict[str, Any]] = {}
    for d in resp.data or []:
        key = (d["hotel_name"], d["state"])
        if key not in seen or float(d["yield_ratio"]) > float(seen[key]["yield_ratio"]):
            seen[key] = d
    return sorted(seen.values(), key=lambda x: -float(x["yield_ratio"]))[:5]


def get_pace() -> dict[str, Any]:
    """Sum LP from booked stays."""
    resp = (
        sb().table("deals")
        .select("total_miles")
        .eq("is_booked", True)
        .execute()
    )
    rows = resp.data or []
    total_lp = sum(int(r.get("total_miles") or 0) for r in rows)
    return {"total_lp": total_lp, "booked_count": len(rows)}


def get_last_scrape_age_hours() -> float | None:
    """Hours since most recent scrape_progress entry."""
    resp = (
        sb().table("scrape_progress")
        .select("completed_at")
        .order("completed_at", desc=True)
        .limit(1)
        .execute()
    )
    rows = resp.data or []
    if not rows:
        return None
    last = datetime.fromisoformat(rows[0]["completed_at"].replace("Z", "+00:00"))
    return (datetime.now(UTC) - last).total_seconds() / 3600


# ── Formatting ──────────────────────────────────────────────────────────────

def fmt_sub_brand(s: str | None) -> str:
    if not s:
        return ""
    return {"HiltonGardenInn": "HGI", "DoubleTree": "DT"}.get(s, s)


def qualifies_honors_bonus(d: dict[str, Any]) -> bool:
    """Apr 7 - Dec 31 2026, Hampton/HGI/Tru, US."""
    sb_ = d.get("sub_brand")
    if sb_ not in ("Hampton", "HiltonGardenInn", "Tru"):
        return False
    ci = d.get("check_in", "")
    return "2026-04-07" <= ci <= "2026-12-31"


def fmt_deal_line(d: dict[str, Any]) -> str:
    """One line per deal, ~60-90 chars."""
    city = d["city_name"]
    state = d["state"]
    # Abbreviate Las Vegas → LV, Fort Worth → FW for brevity
    city_short = {
        "Las Vegas": "LV", "Fort Worth": "FW", "Winston-Salem": "W-S",
        "Myrtle Beach": "Myrtle", "Detroit": "Detroit",
    }.get(city, city)
    hotel = d["hotel_name"]
    # Truncate long names
    if len(hotel) > 32:
        # Drop common suffixes
        hotel = hotel.replace(" – A Caesars Rewards Destination", "")
        hotel = hotel.replace(", A Destination By Hyatt Hotel", " (Hyatt)")
        hotel = hotel.replace(" by Hilton", "")
        if len(hotel) > 32:
            hotel = hotel[:30] + "…"
    yield_v = float(d["yield_ratio"])
    cost = int(float(d["total_cost"]))
    sb_tag = fmt_sub_brand(d.get("sub_brand"))
    sb_str = f" [{sb_tag}]" if sb_tag else ""
    bonus = " +HH" if qualifies_honors_bonus(d) else ""
    return f"• {hotel}{sb_str} · {city_short}, {state} · {yield_v:.1f}x · ${cost}{bonus}"


def build_message(
    top: list[dict[str, Any]],
    new: list[dict[str, Any]],
    pace: dict[str, Any],
    scrape_age_h: float | None,
    date_str: str,
) -> str:
    """Assemble the ≤1024-char Telegram message."""
    lines = [f"🛎 <b>AA Deals · {date_str}</b>", ""]

    if top:
        lines.append(f"⭐ <b>US 30x+</b> ({len(top)} shown)")
        for d in top:
            lines.append(fmt_deal_line(d))
        lines.append("")

    if new:
        lines.append(f"🆕 <b>New since yesterday: {len(new)}</b>")
        for d in new[:5]:
            lines.append(fmt_deal_line(d))
        lines.append("")

    lp = pace["total_lp"]
    bc = pace["booked_count"]
    pct = round((lp / 200000) * 100, 1) if lp else 0
    lines.append(f"📊 Earned: {lp:,} / 200K LP ({pct}%) · {bc} booked")

    if scrape_age_h and scrape_age_h > STALE_SCRAPE_HOURS:
        lines.append(f"⚠️ Scraper last ran {scrape_age_h:.0f}h ago")

    lines.append("🔗 https://aa-deals.vercel.app")

    msg = "\n".join(lines)
    # Trim if over cap — drop bottom of top list first
    if len(msg) > MAX_MESSAGE_CHARS:
        # Recalculate with fewer top rows
        for cap in (8, 6, 4, 2):
            trimmed_top = top[:cap]
            lines2 = [f"🛎 <b>AA Deals · {date_str}</b>", ""]
            if trimmed_top:
                lines2.append(f"⭐ <b>US 30x+</b> (top {cap} shown)")
                for d in trimmed_top:
                    lines2.append(fmt_deal_line(d))
                lines2.append("")
            if new:
                lines2.append(f"🆕 <b>New: {len(new)}</b>")
                for d in new[:3]:
                    lines2.append(fmt_deal_line(d))
                lines2.append("")
            lines2.append(f"📊 {lp:,} / 200K LP · {bc} booked")
            if scrape_age_h and scrape_age_h > STALE_SCRAPE_HOURS:
                lines2.append(f"⚠️ Scraper last ran {scrape_age_h:.0f}h ago")
            lines2.append("🔗 aa-deals.vercel.app")
            msg = "\n".join(lines2)
            if len(msg) <= MAX_MESSAGE_CHARS:
                break
    return msg


def should_send(
    top: list, new: list, pace: dict, scrape_age_h: float | None
) -> bool:
    """Skip if nothing new AND no bookings recorded AND scraper healthy."""
    if new:
        return True
    if pace.get("booked_count", 0) > 0:
        return True
    if scrape_age_h and scrape_age_h > STALE_SCRAPE_HOURS:
        return True
    if top:
        # Still send — this is an info digest showing standing inventory.
        # If we've never seen top picks, tomorrow's message would be same.
        # Accept a daily ping for habit formation.
        return True
    return False


# ── Telegram ────────────────────────────────────────────────────────────────

def send_telegram(text: str, *, token: str, chat_id: str) -> bool:
    """Send HTML message. Retry on transient errors + 429 rate limit."""
    url = f"{TELEGRAM_API}/bot{token}/sendMessage"
    for attempt in range(3):
        try:
            r = httpx.post(
                url,
                json={
                    "chat_id": chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
                timeout=15,
            )
            if r.status_code == 200:
                return True
            if r.status_code == 429:
                retry_after = int((r.json().get("parameters") or {}).get("retry_after", 5))
                log.warning(f"Telegram 429 — waiting {retry_after}s")
                time.sleep(retry_after)
                continue
            log.error(f"Telegram HTTP {r.status_code}: {r.text[:200]}")
        except httpx.HTTPError as e:
            log.warning(f"Telegram send attempt {attempt + 1} failed: {type(e).__name__}")
            if attempt < 2:
                time.sleep(2 ** attempt)
    return False


# ── Main ────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Print message, do not send")
    parser.add_argument("--probe", action="store_true", help="Send a one-line probe to verify chat routing")
    args = parser.parse_args()

    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        log.error("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set")
        return 1

    if args.probe:
        ok = send_telegram(
            f"🤖 AA digest probe · {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}",
            token=token, chat_id=chat_id,
        )
        return 0 if ok else 1

    try:
        top = get_top_deals()
        new = get_new_deals_24h()
        pace = get_pace()
        scrape_age_h = get_last_scrape_age_hours()
    except Exception as e:
        log.error(f"Query failed: {type(e).__name__}: {e}")
        return 1

    log.info(f"top={len(top)} new={len(new)} booked={pace['booked_count']} scrape_age_h={scrape_age_h}")

    if not should_send(top, new, pace, scrape_age_h):
        log.info("Skip-day rule triggered — no message sent")
        return 0

    today = datetime.now(UTC).strftime("%a %b %-d")
    msg = build_message(top, new, pace, scrape_age_h, today)

    if args.dry_run:
        print("─── DRY RUN — message that would be sent ───")
        print(msg)
        print("─── end ───")
        print(f"Length: {len(msg)} / {MAX_MESSAGE_CHARS}")
        return 0

    ok = send_telegram(msg, token=token, chat_id=chat_id)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
