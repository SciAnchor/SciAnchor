#!/usr/bin/env python3
"""Headless Zenodo login → create personal access token → print token.

Credentials via env only (never commit passwords/tokens to git):
  export ZENODO_EMAIL='you@example.com'
  export ZENODO_PASSWORD='...'

Usage:
  python scripts/zenodo_auto_token.py              # production
  python scripts/zenodo_auto_token.py --sandbox    # sandbox (separate account)
  python scripts/zenodo_auto_token.py --print-export
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright


def _base(sandbox: bool) -> str:
    return "https://sandbox.zenodo.org" if sandbox else "https://zenodo.org"


def login_and_create_token(
    *,
    email: str,
    password: str,
    sandbox: bool,
    token_name: str,
    headless: bool = True,
    scopes: tuple[str, ...] = ("deposit:write", "deposit:actions"),
) -> str:
    base = _base(sandbox)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_page()
        page.set_default_timeout(60_000)

        page.goto(f"{base}/login/", wait_until="networkidle")
        page.fill('input[name="email"]', email)
        page.fill('input[name="password"]', password)
        page.click('button[type="submit"]')
        page.wait_for_timeout(2500)
        if "/login" in page.url:
            body = page.inner_text("body")
            browser.close()
            raise RuntimeError(
                f"Login failed (url={page.url}). "
                f"Hint snippet={body[:300]!r}"
            )

        page.goto(
            f"{base}/account/settings/applications/tokens/new/",
            wait_until="networkidle",
        )
        page.fill('input[name="name"]', token_name)
        for scope in scopes:
            box = page.locator(f'input[type="checkbox"][value="{scope}"]')
            if box.count() == 0:
                browser.close()
                raise RuntimeError(f"Scope checkbox not found: {scope}")
            if not box.first.is_checked():
                box.first.check()

        page.locator('button[type="submit"]:has-text("Create")').first.click()
        page.wait_for_timeout(2500)

        # Token shown once: "Access token" section / first long code-like string
        text = page.inner_text("body")
        m = re.search(
            r"Access token\s+([A-Za-z0-9]{30,})\s+Please copy",
            text,
            re.I | re.S,
        )
        token = m.group(1) if m else None
        if not token:
            codes = page.eval_on_selector_all(
                "code, pre",
                "els => els.map(e => (e.innerText||'').trim()).filter(Boolean)",
            )
            for c in codes:
                if re.fullmatch(r"[A-Za-z0-9]{30,}", c):
                    token = c
                    break
        if not token:
            shot = Path("/tmp/zenodo_token_page.png")
            page.screenshot(path=str(shot), full_page=True)
            browser.close()
            raise RuntimeError(
                f"Token form submitted but token not parsed. screenshot={shot} url={page.url}"
            )

        browser.close()
        return token


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sandbox", action="store_true")
    ap.add_argument("--token-name", default=None)
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--email", default=None)
    ap.add_argument("--password", default=None)
    ap.add_argument("--print-export", action="store_true")
    args = ap.parse_args(argv)

    email = args.email or os.environ.get("ZENODO_EMAIL")
    password = args.password or os.environ.get("ZENODO_PASSWORD")
    if not email or not password:
        print("Set ZENODO_EMAIL and ZENODO_PASSWORD.", file=sys.stderr)
        return 2

    name = args.token_name or f"rh-auto-{int(time.time())}"
    try:
        token = login_and_create_token(
            email=email,
            password=password,
            sandbox=args.sandbox,
            token_name=name,
            headless=not args.headed,
        )
    except Exception as e:
        print(f"FAIL: {e}", file=sys.stderr)
        return 1

    if args.print_export:
        print(f"export ZENODO_TOKEN={token}")
    else:
        print(token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
