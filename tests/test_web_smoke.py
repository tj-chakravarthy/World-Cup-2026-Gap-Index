"""Playwright smoke test for the public site (web/public/index.html).

Catches page behaviour the JSON-shape contract (test_web_data_contract.py) can't: the forecast
table not rendering, missing images/assets, JS console errors, and horizontal overflow on
mobile. Serves web/public over a throwaway HTTP server (the page
fetches data/*.json by relative path, so file:// won't do) and drives a headless browser.

Browser resolution: PW_CHROMIUM if set, else an auto-detected system chromium/chrome (so a plain
`pytest` runs locally instead of skipping), else Playwright's own download. It skips cleanly only
when NONE of those is available; in CI (env CI=true) a missing browser is instead a HARD FAILURE,
so the smoke coverage can't silently vanish behind a green check.
"""

import contextlib
import functools
import http.server
import os
import threading
from pathlib import Path

import pytest

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    if os.environ.get("CI"):
        raise  # in CI Playwright must be installed — never let the smoke test silently skip
    pytest.skip("playwright not installed", allow_module_level=True)

WEB = Path(__file__).resolve().parents[1] / "web" / "public"


@pytest.fixture(scope="module")
def base_url():
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(WEB))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}/"
    httpd.shutdown()


def _system_chromium():
    """A system chromium/chrome if one is installed, so a plain `pytest` runs the smoke test
    instead of skipping when Playwright's own browser wasn't downloaded (the common local case).
    PW_CHROMIUM overrides; in CI, Playwright installs its own browser and this returns None."""
    for path in ("/usr/bin/chromium", "/usr/bin/chromium-browser",
                 "/usr/bin/google-chrome", "/usr/bin/google-chrome-stable"):
        if os.path.exists(path):
            return path
    return None


@contextlib.contextmanager
def _page(url, viewport=None):
    with sync_playwright() as p:
        exe = os.environ.get("PW_CHROMIUM") or _system_chromium()
        try:
            browser = p.chromium.launch(executable_path=exe) if exe else p.chromium.launch()
        except Exception as e:  # noqa: BLE001
            if os.environ.get("CI"):
                raise  # in CI a missing/broken browser must fail, not silently skip
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


def test_content_renders(base_url):
    with _page(base_url) as (page, errors, failed):
        # the forecast table renders its rows (top teams)
        page.wait_for_selector("#forecast-table tbody tr", timeout=8000)
        assert page.locator("#forecast-table tbody tr").count() >= 5
        # fixtures + track-record sections render something
        assert page.locator("#fixture-list .fx").count() >= 1
        assert page.locator("#track-list .tr").count() >= 1
        # the model-input bars (tale of the tape) render on the match cards
        assert page.locator(".tape").count() >= 1
        assert not errors, f"console/page errors: {errors[:5]}"
        assert not failed, f"failed asset requests: {failed[:5]}"


def test_key_assets_load(base_url):
    with _page(base_url) as (page, _errors, _failed):
        for asset in ("og.png", "favicon.svg", "data/simulation.json",
                      "data/predictions_live.json", "data/track_record.json",
                      "data/model_inputs.json", "data/movement.json"):
            resp = page.request.get(base_url + asset)
            assert resp.ok, f"{asset} -> HTTP {resp.status}"


def test_mobile_has_no_horizontal_overflow(base_url):
    with _page(base_url, viewport={"width": 390, "height": 844}) as (page, _e, _f):
        page.wait_for_selector("#forecast-table tbody tr", timeout=8000)
        overflow = page.evaluate(
            "() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
        assert overflow <= 2, f"horizontal overflow on a 390px viewport: {overflow}px"
