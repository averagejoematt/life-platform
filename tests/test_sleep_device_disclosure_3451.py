"""tests/test_sleep_device_disclosure_3451.py — #3451: the /sleep hero must name
the device behind its headline "hours" figure.

THE DEFECT. `/data/sleep/`'s hero rendered `sleep_detail.total_sleep_hours` — which
is unconditionally Eight Sleep's duration, never Whoop's (site_api_sleep.py's
`figure_scope.total_sleep_hours_source`) — with a bare "hours" caption. The live
specimen: home vitals said 6.8h (Whoop, the #1369 Truth Spine SoT) while the /sleep
hero said 1.1h (Eight Sleep, a mattress-partial night) for the same night, with no
label on either surface. #2921 already sanctioned two devices disagreeing — its
closing rule, "saying so, every time", was not honoured at the point of render.

This is a real render check (the render-qa pattern, #408's pr_render_gate harness),
not a source-text assertion: it serves site/ locally, route-mocks `/api/sleep_detail`
with `tests/fixtures/render_gate/sleep_detail.json` — the SAME fixture
pr_render_gate.py already uses for its "populated whoop" pass, and which already
carries a live-shaped divergence (Eight Sleep 3.7h vs Whoop 7.4h, one night) — and
asserts the actually-rendered DOM captions the Eight Sleep figure with its device,
using the real evidence_sleep.js module executed by a real browser.

Skips cleanly when Playwright (or its chromium) isn't installed, matching every
other render-qa test in this suite (test_pre_start_render.py's posture).
"""

import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)

pw = pytest.importorskip("playwright.sync_api", reason="playwright not installed — render check runs where it is")

from pr_render_gate import _serve, _wait_port  # noqa: E402

FIXTURE_PATH = os.path.join(REPO, "tests", "fixtures", "render_gate", "sleep_detail.json")


@pytest.fixture(scope="module")
def sleep_page():
    """One browser pass over /data/sleep/ with the real cross-device fixture."""
    with open(FIXTURE_PATH) as f:
        sleep_payload = json.load(f)

    # The live #3451 specimen shape: Eight Sleep and Whoop disagree by hours on
    # the SAME night, and the API discloses which device `total_sleep_hours` is.
    sd = sleep_payload["sleep_detail"]
    assert sd["total_sleep_hours"] != sd["whoop_hours"], "fixture must carry a real cross-device divergence"
    assert sd["figure_scope"]["total_sleep_hours_source"] == "eightsleep"

    site_dir = os.path.join(REPO, "site")
    base_url, shutdown = _serve(site_dir)
    host, port = base_url.replace("http://", "").split(":")
    assert _wait_port(host, int(port)), "local static server never came up"

    out = {}
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(headless=True)
            except Exception as e:  # noqa: BLE001 — chromium not installed
                pytest.skip(f"playwright chromium unavailable: {e}")
            context = browser.new_context(viewport={"width": 1440, "height": 900}, service_workers="block")

            def _json(payload):
                def _h(route):
                    route.fulfill(status=200, content_type="application/json", body=json.dumps(payload))

                return _h

            # Catch-all FIRST (Playwright matches last-registered-first), then the
            # specific sleep_detail mock, matching pr_render_gate's harness rule.
            context.route("**/api/**", _json({}))
            context.route("**/api/sleep_detail", _json(sleep_payload))

            page = context.new_page()
            errors = []
            page.on("pageerror", lambda e, _errs=errors: _errs.append(str(e)))
            page.goto(base_url + "/data/sleep/", wait_until="networkidle", timeout=30000)
            page.wait_for_timeout(1200)  # let the async render settle
            out["errors"] = errors
            out["fig_labels"] = page.eval_on_selector_all(".fig-k", "els => els.map(e => e.textContent)")
            out["fig_values"] = page.eval_on_selector_all(".fig-v", "els => els.map(e => e.textContent)")
            out["text"] = page.inner_text("body")
            page.close()
            browser.close()
    finally:
        shutdown()
    return out


def test_no_js_errors(sleep_page):
    assert not sleep_page["errors"], f"/data/sleep/ threw: {sleep_page['errors']}"


def test_the_hours_figure_names_its_device(sleep_page):
    """#3451: the Eight Sleep hours figure must caption its device — not a bare 'hours'."""
    labels = sleep_page["fig_labels"]
    hours_labels = [lbl for lbl in labels if "hour" in lbl.lower()]
    assert hours_labels, f"no 'hours' figure rendered at all — labels were {labels}"
    assert any("eight sleep" in lbl.lower() for lbl in hours_labels), (
        f"the hours figure must caption its device (Eight Sleep) per #2921's 'saying so, every time' rule — " f"got {hours_labels!r}"
    )


def test_the_captioned_figure_is_the_real_divergent_value(sleep_page):
    """The label isn't just present somewhere — it rides WITH the actual 3.7h figure."""
    labels, values = sleep_page["fig_labels"], sleep_page["fig_values"]
    idx = next(i for i, lbl in enumerate(labels) if "eight sleep" in lbl.lower())
    assert values[idx] == "3.7", f"the Eight Sleep caption sits on the wrong figure — got value {values[idx]!r}"
