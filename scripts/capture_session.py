#!/usr/bin/env python3
"""Capture a fresh SimplyMiles session (local only — headed browser).

Usage:
    pip install playwright
    playwright install chromium
    python scripts/capture_session.py

What it does:
  1. Launches headed Chromium at simplymiles.com
  2. You log in manually with AA credentials + MFA
  3. When your offers are visible, press Enter here
  4. Script dumps cookies as base64-encoded JSON
  5. Copy the gh command it prints — that rotates the GH secret

Frequency: every 5-7 days, or when the CI workflow fails with "Session expired".
"""

from __future__ import annotations

import asyncio
import base64
import json
import sys
from pathlib import Path

SIMPLYMILES_URL = "https://www.simplymiles.com/"


async def capture() -> None:
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("Playwright not installed. Run:\n  pip install playwright\n  playwright install chromium")
        sys.exit(1)

    script_dir = Path(__file__).resolve().parent
    profile_dir = script_dir / ".browser_profile_simplymiles"
    profile_dir.mkdir(exist_ok=True)

    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            str(profile_dir),
            headless=False,
            viewport={"width": 1280, "height": 800},
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = await ctx.new_page()
        print(f"Opening {SIMPLYMILES_URL}")
        await page.goto(SIMPLYMILES_URL)

        print("\n" + "=" * 60)
        print("LOG IN NOW. Complete MFA. Wait until your offers are visible.")
        print("Then come back here and press Enter.")
        print("=" * 60)
        input()

        cookies = await ctx.cookies(["https://www.simplymiles.com", "https://simplymiles.com"])
        await ctx.close()

    if not cookies:
        print("ERROR: no cookies extracted. Login likely didn't complete.")
        sys.exit(1)

    payload = json.dumps(cookies)
    b64 = base64.b64encode(payload.encode()).decode()

    # Write a local copy so you can inspect before pushing
    out = script_dir / "cookies.local.json"
    out.write_text(payload)

    print(f"\n{len(cookies)} cookies captured. Local copy: {out}")
    has_xsrf = any(c.get("name") == "XSRF-TOKEN" for c in cookies)
    print(f"XSRF-TOKEN present: {has_xsrf}")
    if not has_xsrf:
        print("WARNING: no XSRF-TOKEN cookie — API call may fail. Re-login?")

    print("\n=== Copy-paste this to rotate the GH secret: ===\n")
    print(f"gh secret set SIMPLYMILES_SESSION_B64 --body '{b64}' -R alexbesp18/aa-deals")
    print("\n(Or if you use a different remote, adjust the -R flag.)")
    print("\nThen trigger the workflow to verify:")
    print("gh workflow run scrape-simplymiles.yml -R alexbesp18/aa-deals")


if __name__ == "__main__":
    try:
        asyncio.run(capture())
    except KeyboardInterrupt:
        print("\nCancelled.")
        sys.exit(1)
