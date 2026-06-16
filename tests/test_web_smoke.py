"""Playwright smoke test for the public site (web/public/index.html).

Catches page behaviour the JSON-shape contract (test_web_data_contract.py) can't: a stuck
splash overlay, the forecast table not rendering, missing images/assets, JS console errors,
and horizontal overflow on mobile. Serves web/public over a throwaway HTTP server (the page
fetches data/*.json by relative path, so file:// won't do) and drives a headless browser.

Skips cleanly when Playwright or a browser isn't installed, so plain CI still runs. Set
PW_CHROMIUM=/path/to/chromium to use a system browser instead of Playwright's download.
"""

import contextlib
import functools
import http.server
import os
import threading
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright  # noqa: E402

WEB = Path(__file__).resolve().parents[1] / "web" / "public"


@pytest.fixture(scope="module")
def base_url():
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(WEB))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}/"
    httpd.shutdown()


@contextlib.contextmanager
def _page(url, viewport=None):
    with sync_playwright() as p:
        exe = os.environ.get("PW_CHROMIUM")
        try:
            browser = p.chromium.launch(executable_path=exe) if exe else p.chromium.launch()
        except Exception as e:  # noqa: BLE001 - browser not installed -> skip, don't fail
            pytest.skip(f"no Playwright browser available: {e}")
        page = browser.new_page(viewport=viewport) if viewport else browser.new_page()
        errors, failed = [], []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("response", lambda r: failed.append((r.url, r.status)) if r.status >= 400 else None)
        page.goto(url, wait_until="load")
        try:
            yield page, errors, failed
        finally:
            browser.close()


def test_splash_dismisses_and_content_renders(base_url):
    with _page(base_url) as (page, errors, failed):
        # the intro splash must auto-dismiss — never a stuck full-screen overlay
        page.wait_for_selector("#splash", state="detached", timeout=13000)
        # the forecast table renders its rows (top teams)
        page.wait_for_selector("#forecast-table tbody tr", timeout=8000)
        assert page.locator("#forecast-table tbody tr").count() >= 5
        # fixtures + track-record sections render something
        assert page.locator("#fixture-list .fx").count() >= 1
        assert page.locator("#track-list .tr").count() >= 1
        assert not errors, f"console/page errors: {errors[:5]}"
        assert not failed, f"failed asset requests: {failed[:5]}"


def test_key_assets_load(base_url):
    with _page(base_url) as (page, _errors, _failed):
        for asset in ("splash.jpg", "og.png", "favicon.svg", "trionda.glb",
                      "vendor/three.module.min.js", "data/simulation.json",
                      "data/predictions_live.json", "data/track_record.json"):
            resp = page.request.get(base_url + asset)
            assert resp.ok, f"{asset} -> HTTP {resp.status}"


def test_mobile_has_no_horizontal_overflow(base_url):
    with _page(base_url, viewport={"width": 390, "height": 844}) as (page, _e, _f):
        page.wait_for_selector("#splash", state="detached", timeout=13000)
        overflow = page.evaluate(
            "() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
        assert overflow <= 2, f"horizontal overflow on a 390px viewport: {overflow}px"
