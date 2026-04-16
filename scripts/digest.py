#!/usr/bin/env python3
"""Daily digest email — top stacks + new hotels + session health.

Silent-day rule: skips the email entirely if no stacks, no new deals,
and SimplyMiles session isn't stale. Aligns with "advisors not monitors".

Exit 0 on success (or silent-skip).
Exit 1 on fatal error.
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timedelta, UTC

import resend
from supabase import create_client, ClientOptions

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

RESEND_FROM = "digest@novaconsultpro.com"
DIGEST_TO_DEFAULT = "alexbespalovtx@gmail.com"

STALE_SM_HOURS = 24 * 5   # 5 days — matches security review recommendation
NEW_DEALS_WINDOW_HOURS = 24


# ── Queries ──────────────────────────────────────────────────────────────────

def client_for(schema: str):
    return create_client(
        os.environ["SUPABASE_URL"],
        os.environ["SUPABASE_SERVICE_ROLE_KEY"],
        options=ClientOptions(schema=schema),
    )


def get_top_stacks(limit: int = 5) -> list[dict]:
    sb = client_for("aa_tools")
    try:
        resp = (
            sb.table("stack_view")
            .select("merchant_name,portal_rate,sm_type,sm_miles_amount,sm_min_spend,sm_expires_at,combined_yield,portal_click_url")
            .gte("combined_yield", 10)
            .order("combined_yield", desc=True)
            .limit(limit)
            .execute()
        )
        return resp.data or []
    except Exception as e:
        log.warning(f"stack_view query failed: {type(e).__name__}")
        return []


def get_new_hotels(hours: int = NEW_DEALS_WINDOW_HOURS, limit: int = 5) -> list[dict]:
    sb = client_for("aa_hotels")
    cutoff = (datetime.now(UTC) - timedelta(hours=hours)).isoformat()
    try:
        resp = (
            sb.table("deals")
            .select("hotel_name,city_name,state,yield_ratio,total_cost,total_miles,check_in,check_out,url")
            .gt("created_at", cutoff)
            .eq("is_booked", False)
            .order("yield_ratio", desc=True)
            .limit(limit)
            .execute()
        )
        return resp.data or []
    except Exception as e:
        log.warning(f"new hotels query failed: {type(e).__name__}")
        return []


def get_session_health() -> dict:
    """Return {'source': ..., 'last_success_at': ..., 'stale': bool} or {} if unknown."""
    sb = client_for("aa_tools")
    try:
        resp = sb.table("session_state").select("*").eq("source", "simplymiles").limit(1).execute()
    except Exception as e:
        log.warning(f"session_state query failed: {type(e).__name__}")
        return {}
    rows = resp.data or []
    if not rows:
        return {"source": "simplymiles", "last_success_at": None, "stale": True, "never_succeeded": True}
    last = rows[0].get("last_success_at")
    if not last:
        return {"source": "simplymiles", "last_success_at": None, "stale": True, "never_succeeded": True}
    age_hours = (datetime.now(UTC) - datetime.fromisoformat(last.replace("Z", "+00:00"))).total_seconds() / 3600
    return {
        "source": "simplymiles",
        "last_success_at": last,
        "age_hours": round(age_hours, 1),
        "stale": age_hours >= STALE_SM_HOURS,
        "never_succeeded": False,
    }


# ── HTML rendering ───────────────────────────────────────────────────────────

def html_escape(s: str) -> str:
    return (str(s or "")
            .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;").replace("'", "&#39;"))


def render_stack_row(s: dict) -> str:
    merchant = html_escape(s.get("merchant_name", ""))
    url = s.get("portal_click_url")
    merchant_html = f'<a href="{html_escape(url)}" style="color:#0066cc;text-decoration:none;">{merchant}</a>' if url else merchant
    portal = Number_fmt(s.get("portal_rate"))
    combined = Number_fmt(s.get("combined_yield"))
    sm_type = s.get("sm_type")
    sm_amount = s.get("sm_miles_amount", 0)
    sm_min = s.get("sm_min_spend")
    if sm_type == "flat_bonus" and sm_min:
        sm_text = f"+{sm_amount} mi on ${Number_fmt(sm_min)}+"
    elif sm_type == "per_dollar":
        sm_text = f"+{sm_amount} mi/$"
    else:
        sm_text = f"+{sm_amount} mi"
    return f"""
      <tr style="border-bottom:1px solid #eee;">
        <td style="padding:10px;font-weight:600;">{merchant_html}</td>
        <td style="padding:10px;color:#666;font-size:13px;">{portal}x portal · {html_escape(sm_text)}</td>
        <td style="padding:10px;text-align:right;color:#0f7938;font-weight:700;">{combined}x</td>
      </tr>
    """


def render_hotel_row(d: dict) -> str:
    name = html_escape(d.get("hotel_name", ""))
    city = html_escape(f"{d.get('city_name','')}, {d.get('state','')}")
    yield_ = Number_fmt(d.get("yield_ratio"))
    ci = d.get("check_in", "")
    url = d.get("url")
    name_html = f'<a href="{html_escape(url)}" style="color:#0066cc;text-decoration:none;">{name}</a>' if url else name
    return f"""
      <tr style="border-bottom:1px solid #eee;">
        <td style="padding:10px;">
          <div style="font-weight:600;">{name_html}</div>
          <div style="font-size:12px;color:#777;">{city} · {html_escape(ci)}</div>
        </td>
        <td style="padding:10px;text-align:right;color:#0f7938;font-weight:700;">{yield_}x</td>
      </tr>
    """


def Number_fmt(v) -> str:
    if v is None:
        return "—"
    try:
        n = float(v)
        return f"{n:.1f}".rstrip("0").rstrip(".") if n != int(n) else f"{int(n)}"
    except (TypeError, ValueError):
        return str(v)


def render_html(stacks: list[dict], hotels: list[dict], session: dict) -> str:
    today = datetime.now(UTC).strftime("%Y-%m-%d")

    stacks_section = ""
    if stacks:
        rows = "".join(render_stack_row(s) for s in stacks)
        stacks_section = f"""
          <h2 style="margin:24px 0 12px 0;font-size:16px;color:#333;">Top Stacks</h2>
          <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;background:#fff;border:1px solid #ddd;border-radius:4px;">
            {rows}
          </table>
        """

    hotels_section = ""
    if hotels:
        rows = "".join(render_hotel_row(h) for h in hotels)
        hotels_section = f"""
          <h2 style="margin:24px 0 12px 0;font-size:16px;color:#333;">New Hotel Deals (24h)</h2>
          <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;background:#fff;border:1px solid #ddd;border-radius:4px;">
            {rows}
          </table>
        """

    status_section = ""
    if session.get("stale"):
        reason = "never captured" if session.get("never_succeeded") else "stale"
        status_section = f"""
          <div style="margin-top:24px;background:#fff3cd;border-left:4px solid #ffc107;padding:12px;border-radius:4px;">
            <p style="margin:0;font-weight:600;color:#856404;">SimplyMiles session {reason}</p>
            <p style="margin:4px 0 0 0;font-size:13px;color:#856404;">
              Run <code style="background:#fff;padding:2px 4px;border-radius:2px;">python scripts/capture_session.py</code> locally to refresh.
            </p>
          </div>
        """

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>AA Digest · {today}</title>
</head>
<body style="margin:0;padding:16px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f9f9f9;line-height:1.5;">
  <table width="100%" cellpadding="0" cellspacing="0" style="max-width:600px;margin:0 auto;">
    <tr><td style="padding:0 0 12px 0;border-bottom:2px solid #e0e0e0;">
      <h1 style="margin:0;font-size:20px;color:#0066cc;">AA Digest</h1>
      <p style="margin:4px 0 0 0;font-size:12px;color:#999;">{today}</p>
    </td></tr>
    <tr><td>{stacks_section}{hotels_section}{status_section}</td></tr>
    <tr><td style="padding:24px 0 0 0;border-top:1px solid #e0e0e0;text-align:center;">
      <p style="margin:0;font-size:12px;color:#999;">
        <a href="https://aa-deals.vercel.app" style="color:#0066cc;text-decoration:none;">Dashboard</a> ·
        <a href="https://aa-deals.vercel.app/stacks" style="color:#0066cc;text-decoration:none;">Stacks</a>
      </p>
    </td></tr>
  </table>
</body></html>"""


# ── Decision + send ──────────────────────────────────────────────────────────

def should_send(stacks: list, hotels: list, session: dict) -> bool:
    return bool(stacks) or bool(hotels) or session.get("stale", False)


def main() -> int:
    stacks = get_top_stacks()
    hotels = get_new_hotels()
    session = get_session_health()

    log.info(f"stacks={len(stacks)} new_hotels={len(hotels)} session_stale={session.get('stale')}")

    if not should_send(stacks, hotels, session):
        log.info("Silent day — skipping email")
        return 0

    api_key = os.environ.get("RESEND_API_KEY")
    if not api_key:
        log.error("RESEND_API_KEY not set")
        return 1

    to = os.environ.get("DIGEST_TO", DIGEST_TO_DEFAULT)
    resend.api_key = api_key

    html = render_html(stacks, hotels, session)
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    subject = f"AA Digest · {today} — {len(stacks)} stacks, {len(hotels)} new hotels"
    if session.get("stale"):
        subject += " · ⚠️ session stale"

    try:
        resp = resend.Emails.send({
            "from": RESEND_FROM,
            "to": [to],
            "subject": subject,
            "html": html,
        })
        log.info(f"Digest sent (id={resp.get('id') if isinstance(resp, dict) else 'ok'})")
        return 0
    except Exception as e:
        log.error(f"Resend send failed: {type(e).__name__}: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
