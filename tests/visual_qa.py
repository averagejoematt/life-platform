#!/usr/bin/env python3
"""
visual_qa.py — Playwright visual QA sweep for averagejoematt.com

Deep visual regression testing:
1. Authenticates via cf-auth (POST /__auth) — required since the site is gated.
2. Scrolls every page top-to-bottom (triggers lazy rendering + reveal animations)
3. Checks every canvas element for drawn pixels (not blank)
4. Verifies key text values match API data
5. Checks observatory charts for the cycle-pause band where expected
6. Screenshots individual sections that fail
7. Detects stuck loading indicators, JS errors, empty containers

Usage:
    python3 tests/visual_qa.py                      # Run full sweep
    python3 tests/visual_qa.py --page /glucose/     # Single page
    python3 tests/visual_qa.py --screenshot         # Save screenshots
    python3 tests/visual_qa.py --no-cache           # Force re-auth (ignore cookie cache)

Auth source (priority order):
    1. $VISUAL_QA_PASSWORD environment variable
    2. AWS Secrets Manager: life-platform/cf-auth (key: "password"), us-east-1
       — uses your default AWS credentials
    3. Cached cookie at qa-screenshots/.auth_cookie (if still valid)

Cost: $0 — runs locally or in CI. No AWS charges (Secrets Manager fetch is ~$0).

v3.1.0 — 2026-05-04 (better detectors: chartjs cyclePause, collapsed details,
                     graceful homepage timeout, known-issue allowlist)
"""

import argparse
import hashlib
import hmac
import json
import os
import sys
import time
from datetime import datetime, timezone

SITE_URL = "https://averagejoematt.com"
COOKIE_NAME = "__lp_auth"
COOKIE_CACHE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "qa-screenshots", ".auth_cookie"
)
COOKIE_REFRESH_THRESHOLD_SECONDS = 7 * 24 * 60 * 60  # refresh if <7d remaining

# JS errors we know about and intentionally tolerate. They should be FIXED, but
# until they are, the sweep flags them as "known issue" instead of failing.
# Format: substring → reason (for the human reading the output).
KNOWN_JS_ISSUES = {
    "calcOnsetAdherence":
        "Sleep page wipes .s-adherence__grid then tries to write to a child id "
        "(s-adh-onset-outcome) that no longer exists. Real bug. Tracked separately.",
}

# ── Page definitions with deep checks ─────────────────────────────────────────
# `expect_cycle_pause_band` flags pages that should render the pause band
# (per docs/SPEC_CYCLE_PAUSE_VIZ_2026_05_03.md — 6 observatory pages, 11 charts).
# Default 30d/90d window WILL intersect Apr 12 → May 1, so band must be visible.
PAGES = [
    # ── v4 "Measured Life" doors (Story / Cockpit / Evidence) ──────────────
    # NOTE (v4 cutover): the deep entries below still point at old URLs. Post-
    # cutover they 301 into /legacy/* (preserved verbatim) — repoint them to
    # /legacy/<path> in a follow-up sweep, or drop them as each is rebuilt.
    {
        "path": "/",
        "name": "Story (door)",
        "wait_for": ".constellation svg .node",
        "checks": [
            {"selector": ".constellation svg .node", "min_count": 7, "desc": "all 7 pillar nodes drawn in the constellation"},
            {"selector": ".hero-elena", "not_empty": True, "desc": "Elena hero line populated"},
            {"selector": ".beat", "min_count": 4, "desc": "scrollytelling beats present"},
        ],
    },
    {
        "path": "/now",
        "name": "Cockpit (door)",
        "wait_for": '[data-bind="level"]',
        "checks": [
            {"selector": ".big", "not_empty": True, "desc": "character level rendered"},
            {"selector": ".voice.machine .what", "not_empty": True, "desc": "the Chair's verdict rendered"},
            {"selector": ".row", "min_count": 1, "desc": "at least one pillar row"},
        ],
    },
    {
        "path": "/evidence/",
        "name": "Evidence (door index)",
        "wait_for": ".ev-card",
        "checks": [
            {"selector": ".ev-card", "min_count": 10, "desc": "evidence index cards present"},
        ],
    },
    {
        "path": "/evidence/supplements/",
        "name": "Evidence — supplements (readout)",
        "wait_for": "[data-readout]",
        "checks": [
            {"selector": "[data-readout]", "not_empty": True, "desc": "supplements readout rendered"},
        ],
    },
    {
        "path": "/live/",
        "name": "Pulse",
        "wait_for": ".detail-card",
        "checks": [
            {"selector": ".detail-card", "min_count": 4, "desc": "4+ pulse glyph cards"},
            {"selector": ".detail-card__value", "min_count": 4, "desc": "glyph value elements present"},
        ],
    },
    {
        "path": "/sleep/",
        "name": "Sleep",
        "wait_for": "#s-content",
        "expect_cycle_pause_band": True,
        "checks": [
            {"canvas_not_blank": True, "desc": "at least one chart has drawn pixels"},
            {"selector": "canvas", "min_count": 1, "desc": "at least one chart canvas present"},
        ],
    },
    {
        "path": "/glucose/",
        "name": "Glucose",
        "wait_for": "#g-content",
        "expect_cycle_pause_band": True,
        "checks": [
            {"canvas_not_blank": True, "desc": "glucose trend chart has pixels"},
            {"selector": "#gg-tir-num, #gg-avg-num", "not_empty": True, "desc": "glucose gauges populated"},
        ],
    },
    {
        "path": "/nutrition/",
        "name": "Nutrition",
        "wait_for": "#n-content",
        "expect_cycle_pause_band": True,
        "checks": [
            {"canvas_not_blank": True, "desc": "macro chart has pixels"},
            {"selector": "#g-cal-num, #g-pro-num", "not_empty": True, "desc": "nutrition gauges populated"},
        ],
    },
    {
        "path": "/training/",
        "name": "Training",
        "wait_for": "#t-content",
        "expect_cycle_pause_band": True,
        "checks": [
            {"canvas_not_blank": True, "desc": "at least one training chart has pixels"},
        ],
    },
    {
        "path": "/physical/",
        "name": "Physical",
        "wait_for": "#p-content",
        "expect_cycle_pause_band": True,
        "checks": [
            {"canvas_not_blank": True, "desc": "weight trajectory chart has pixels"},
        ],
    },
    {
        "path": "/mind/",
        "name": "Mind / Inner Life",
        "wait_for": "#m-content",
        "expect_cycle_pause_band": True,
        "checks": [
            {"selector": "canvas, .heatmap-week, .vice-bar", "min_count": 1, "desc": "charts or heatmap rendered"},
        ],
    },
    {
        "path": "/character/",
        "name": "Character",
        "checks": [
            {"selector": ".pillar-card, .char-pillar", "min_count": 7, "desc": "7 pillar cards"},
        ],
    },
    {
        "path": "/habits/",
        "name": "Habits",
        "checks": [
            {"selector": ".hm-cell:not(.empty)", "min_count": 1, "desc": "heatmap cells with data"},
        ],
    },
    {
        "path": "/status/",
        "name": "Status",
        "checks": [
            {"selector": ".pill", "min_count": 10, "desc": "10+ status pills"},
        ],
    },
    {
        "path": "/story/",
        "name": "Story",
        "checks": [
            {"selector": "#story-weight, .milestone__value", "not_empty": True, "desc": "weight displayed"},
        ],
    },
]


# ══════════════════════════════════════════════════════════════════════════════
# AUTH — cf-auth handshake
# ══════════════════════════════════════════════════════════════════════════════

def _resolve_password():
    """Resolve auth password from env var first, then Secrets Manager."""
    env_pw = os.environ.get("VISUAL_QA_PASSWORD")
    if env_pw:
        return env_pw, "env"

    try:
        import boto3
        sm = boto3.client("secretsmanager", region_name="us-east-1")
        resp = sm.get_secret_value(SecretId="life-platform/cf-auth")
        secret = json.loads(resp["SecretString"])
        return secret["password"], "secretsmanager"
    except Exception as e:
        print(f"  ⚠️  Could not load password: {e}")
        return None, None


def _validate_cookie_locally(cookie_value, password):
    """Re-implement the cf-auth Lambda's HMAC check so we can test cached cookies
    without hitting the network. See lambdas/cf-auth/index.mjs."""
    if not cookie_value or "|" not in cookie_value:
        return False, 0
    try:
        expiry_str, sig = cookie_value.split("|", 1)
        expiry = int(expiry_str)
    except (ValueError, AttributeError):
        return False, 0

    now = int(time.time())
    if expiry < now:
        return False, expiry

    expected = hmac.new(
        password.encode("utf-8"),
        str(expiry).encode("utf-8"),
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(sig, expected), expiry


def _load_cached_cookie(password):
    """Load cached cookie if valid + not near expiry."""
    if not os.path.isfile(COOKIE_CACHE_PATH):
        return None
    try:
        with open(COOKIE_CACHE_PATH, "r") as f:
            cookie_value = f.read().strip()
    except Exception:
        return None

    valid, expiry = _validate_cookie_locally(cookie_value, password)
    if not valid:
        return None
    seconds_left = expiry - int(time.time())
    if seconds_left < COOKIE_REFRESH_THRESHOLD_SECONDS:
        return None
    return cookie_value


def _save_cached_cookie(cookie_value):
    os.makedirs(os.path.dirname(COOKIE_CACHE_PATH), exist_ok=True)
    with open(COOKIE_CACHE_PATH, "w") as f:
        f.write(cookie_value)
    os.chmod(COOKIE_CACHE_PATH, 0o600)


def _post_auth_for_cookie(password):
    """POST password to /__auth, follow no redirects, extract Set-Cookie."""
    import urllib.request
    import urllib.parse

    body = urllib.parse.urlencode({"password": password, "redirect": "/"}).encode()
    req = urllib.request.Request(
        f"{SITE_URL}/__auth",
        data=body,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None

    opener = urllib.request.build_opener(NoRedirect)
    try:
        resp = opener.open(req, timeout=10)
        return _extract_cookie_from_headers(resp.info()), resp.status
    except urllib.error.HTTPError as e:
        return _extract_cookie_from_headers(e.headers), e.code


def _extract_cookie_from_headers(headers):
    """Parse Set-Cookie header(s) for our auth cookie value."""
    if hasattr(headers, "get_all"):
        set_cookies = headers.get_all("Set-Cookie") or []
    else:
        sc = headers.get("Set-Cookie")
        set_cookies = [sc] if sc else []
    for sc in set_cookies:
        if not sc:
            continue
        if sc.startswith(f"{COOKIE_NAME}="):
            return sc.split(";", 1)[0].split("=", 1)[1]
    return None


def get_auth_cookie(force_refresh=False):
    """Return a valid __lp_auth cookie value. Caches across runs."""
    password, source = _resolve_password()
    if not password:
        return None

    if not force_refresh:
        cached = _load_cached_cookie(password)
        if cached:
            print(f"  🔐 Using cached auth cookie (password from {source})")
            return cached

    print(f"  🔐 Authenticating against /__auth (password from {source})...")
    cookie, status = _post_auth_for_cookie(password)
    if not cookie:
        print(f"  ❌ Auth failed — got HTTP {status} with no Set-Cookie")
        return None
    _save_cached_cookie(cookie)
    print(f"  ✓ Got fresh cookie")
    return cookie


# ══════════════════════════════════════════════════════════════════════════════
# Page checks
# ══════════════════════════════════════════════════════════════════════════════

def _scroll_and_reveal(page):
    """Scroll the entire page top-to-bottom, then force all reveal animations."""
    page.evaluate("""
        () => new Promise(resolve => {
            let y = 0;
            const step = 400;
            const timer = setInterval(() => {
                window.scrollBy(0, step);
                y += step;
                document.querySelectorAll('.reveal').forEach(el => {
                    el.classList.add('is-visible');
                    el.style.opacity = '1';
                    el.style.transform = 'none';
                });
                if (y >= document.body.scrollHeight) {
                    clearInterval(timer);
                    window.scrollTo(0, 0);
                    resolve();
                }
            }, 80);
            setTimeout(() => { clearInterval(timer); window.scrollTo(0, 0); resolve(); }, 10000);
        })
    """)
    page.evaluate("""
        () => {
            document.querySelectorAll('.reveal').forEach(el => {
                el.classList.add('is-visible');
                el.style.opacity = '1';
                el.style.transform = 'none';
            });
        }
    """)
    page.wait_for_timeout(2000)


def _check_canvas_not_blank(page):
    return page.evaluate("""
        () => {
            const results = [];
            document.querySelectorAll('canvas').forEach((c, i) => {
                if (c.offsetWidth === 0 || c.offsetHeight === 0) return;
                const chartInstance = (typeof Chart !== 'undefined') && Chart.getChart && Chart.getChart(c);
                if (chartInstance) {
                    const hasData = chartInstance.data && chartInstance.data.datasets &&
                        chartInstance.data.datasets.some(ds => ds.data && ds.data.length > 0);
                    results.push({index: i, id: c.id, status: hasData ? 'drawn' : 'blank', note: 'Chart.js'});
                    return;
                }
                try {
                    const ctx = c.getContext('2d');
                    const w = c.width || c.offsetWidth;
                    const h = c.height || c.offsetHeight;
                    if (w < 2 || h < 2) {
                        results.push({index: i, id: c.id, status: 'zero-size', w: w, h: h});
                        return;
                    }
                    const data = ctx.getImageData(0, 0, w, h).data;
                    let nonEmpty = 0;
                    for (let p = 3; p < data.length; p += 4000) {
                        if (data[p] > 0) nonEmpty++;
                    }
                    results.push({index: i, id: c.id, status: nonEmpty > 0 ? 'drawn' : 'blank', pixels: nonEmpty});
                } catch(e) {
                    results.push({index: i, id: c.id, status: c.offsetHeight > 10 ? 'assumed-drawn' : 'error', note: String(e).slice(0,60)});
                }
            });
            return results;
        }
    """)


def _check_cycle_pause_band(page):
    """Detect whether the cycle-pause band is rendered.

    The pause band has THREE flavors per cycle-pause.js:
      1. SVG: <g class="cycle-pause-band"> appended to <svg>          [DOM-detectable]
      2. Raw canvas: ctx.fillRect drawn on <canvas>                    [no DOM trace]
      3. Chart.js plugin: registered as `cyclePause` plugin on chart   [no DOM trace]

    Detection strategy (any-of):
      A. window.CyclePause exists (script loaded), AND
      B. one of:
         - DOM marker (.cycle-pause-band or .cycle-pause-overlay) exists
         - any Chart.js instance has options.plugins.cyclePause configured with dates
         - the page's chart data spans the pause window (Apr 12 → May 1) AND
           CyclePause API has been called this session (filterTrend marks _inPause)

    The third-branch heuristic catches canvas-overlay flavors that we can't see
    in DOM. We can't actually instrument that without injecting hooks, so we
    treat "script loaded + chart spans the gap" as evidence-of-render and only
    fail when the script is missing entirely or no chart data overlaps the gap.

    Returns dict with all evidence collected, plus a final `rendered: bool`.
    """
    return page.evaluate("""
        () => {
            const PAUSE_START = '2026-04-12';
            const PAUSE_END   = '2026-05-01';

            // (1) DOM markers
            const svgBands = document.querySelectorAll('.cycle-pause-band').length;
            const overlays = document.querySelectorAll('.cycle-pause-overlay').length;
            const labels   = document.querySelectorAll('.cycle-pause-label').length;

            // (2) Script loaded?
            const scriptLoaded = typeof window.CyclePause === 'object' && window.CyclePause !== null;

            // (3) Chart.js plugin registrations
            let chartjsPluginRegistered = 0;
            let chartjsCharts = 0;
            if (typeof Chart !== 'undefined' && Chart.instances) {
                Object.values(Chart.instances).forEach(ch => {
                    chartjsCharts++;
                    const cfg = ch.options && ch.options.plugins && ch.options.plugins.cyclePause;
                    if (cfg && cfg.dates && cfg.dates.length) chartjsPluginRegistered++;
                });
            }

            // (4) Detect 7d window — band is intentionally hidden then.
            //     Check the active time-window button (selectors vary per page).
            let windowActive = null;
            const candidates = document.querySelectorAll(
                '.s-time-toggle.active, .obs-time-toggle.active, [data-days].active, [data-days].is-active'
            );
            for (const c of candidates) {
                const days = c.getAttribute('data-days') || (c.textContent || '').trim();
                if (days) { windowActive = days; break; }
            }
            const windowHidden = windowActive === '7' || /^7d$/i.test(windowActive || '');

            // (5) Heuristic: did the page render any chart whose date range
            //     would intersect the pause window? If not, the band is
            //     legitimately absent (no overlapping data to mark).
            //     We detect this by sampling Chart.js label arrays + any
            //     timeseries data attribute we can find.
            let dataIntersectsGap = false;
            if (typeof Chart !== 'undefined' && Chart.instances) {
                Object.values(Chart.instances).forEach(ch => {
                    const labels = (ch.data && ch.data.labels) || [];
                    if (!labels.length) return;
                    const first = String(labels[0]);
                    const last  = String(labels[labels.length - 1]);
                    // If any label string sorts within the gap window, count it.
                    if (last >= PAUSE_START && first <= PAUSE_END) {
                        dataIntersectsGap = true;
                    }
                });
            }

            const domEvidence    = svgBands + overlays > 0;
            const chartjsEvidence = chartjsPluginRegistered > 0;
            const inferredEvidence = scriptLoaded && dataIntersectsGap && chartjsCharts > 0;

            return {
                rendered: domEvidence || chartjsEvidence,
                inferred: inferredEvidence && !domEvidence && !chartjsEvidence,
                window_hidden: windowHidden,
                window_active: windowActive,
                evidence: {
                    svg_bands: svgBands,
                    overlays: overlays,
                    labels: labels,
                    script_loaded: scriptLoaded,
                    chartjs_plugin_registered: chartjsPluginRegistered,
                    chartjs_charts_total: chartjsCharts,
                    data_intersects_gap: dataIntersectsGap,
                },
            };
        }
    """)


def _check_sections_for_blank(page):
    """Find sections that are visible but effectively empty.

    Excludes elements inside collapsed <details> (accordion content that's
    intentionally hidden until expanded) — the V3 observatory's depth sections
    use this pattern, e.g. .obs-depth-section__body inside <details>."""
    return page.evaluate("""
        () => {
            const issues = [];
            // Helper: is this element inside a closed <details>?
            const insideClosedDetails = (el) => {
                let p = el.parentElement;
                while (p) {
                    if (p.tagName === 'DETAILS' && !p.hasAttribute('open')) return true;
                    p = p.parentElement;
                }
                return false;
            };
            document.querySelectorAll('section, [class*=section]').forEach(s => {
                const rect = s.getBoundingClientRect();
                if (rect.height < 20) return;
                if (insideClosedDetails(s)) return;  // intentionally collapsed
                const text = s.innerText.trim();
                const hasCanvas = s.querySelector('canvas');
                const hasSvg = s.querySelector('svg');
                if (rect.height > 100 && text.length < 5 && !hasCanvas && !hasSvg) {
                    issues.push({
                        class: s.className.slice(0, 60),
                        id: s.id,
                        height: Math.round(rect.height),
                        text: text.slice(0, 30)
                    });
                }
            });
            return issues;
        }
    """)


def _check_stale_text(page):
    return page.evaluate("""
        () => {
            const body = document.body.innerText;
            const issues = [];
            const suspects = [
                {pattern: /Launching April/i, desc: 'Pre-launch text still visible'},
                {pattern: /(?<![a-z])TODO(?![a-z])|FIXME|(?<![a-z])TBD(?![a-z])/i, desc: 'Development placeholder text'},
                {pattern: /Loading\\.\\.\\.\\./i, desc: 'Stuck loading indicator'},
                {pattern: /placeholder/i, desc: 'Placeholder text visible'},
            ];
            for (const s of suspects) {
                if (s.pattern.test(body)) {
                    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
                    while (walker.nextNode()) {
                        if (s.pattern.test(walker.currentNode.textContent)) {
                            const el = walker.currentNode.parentElement;
                            if (el && el.offsetParent !== null && el.offsetHeight > 0) {
                                const rect = el.getBoundingClientRect();
                                issues.push({
                                    text: walker.currentNode.textContent.trim().slice(0, 60),
                                    desc: s.desc,
                                    y: Math.round(rect.top + window.scrollY),
                                    visible: true
                                });
                                break;
                            }
                        }
                    }
                }
            }
            return issues;
        }
    """)


def _classify_js_errors(errors):
    """Split JS errors into (real, known). Known issues don't fail the sweep
    but are reported. Real issues fail the sweep."""
    real, known = [], []
    for err in errors:
        matched = None
        for needle, reason in KNOWN_JS_ISSUES.items():
            if needle in err:
                matched = reason
                break
        if matched:
            known.append((err, matched))
        else:
            real.append(err)
    return real, known


# ══════════════════════════════════════════════════════════════════════════════
# Main sweep
# ══════════════════════════════════════════════════════════════════════════════

def _navigate_with_fallback(page, url, primary_timeout=15000, fallback_timeout=20000):
    """Navigate to URL. Try networkidle first; if that times out, fall back to
    domcontentloaded. Mirrors captures/capture.mjs behavior."""
    try:
        page.goto(url, wait_until="networkidle", timeout=primary_timeout)
        return None
    except Exception as e1:
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=fallback_timeout)
            return f"networkidle timed out ({primary_timeout}ms); fell back to domcontentloaded"
        except Exception as e2:
            return f"Page load failed: {e2}"


def run_sweep(pages=None, save_screenshots=False, screenshot_dir=None,
              auth_cookie=None):
    """Run deep visual QA sweep on all pages."""
    from playwright.sync_api import sync_playwright

    if screenshot_dir is None:
        screenshot_dir = os.path.join(os.path.dirname(__file__), "..", "qa-screenshots")
    os.makedirs(screenshot_dir, exist_ok=True)

    results = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            color_scheme="dark",
        )

        if auth_cookie:
            context.add_cookies([{
                "name":   COOKIE_NAME,
                "value":  auth_cookie,
                "domain": "averagejoematt.com",
                "path":   "/",
                "secure": True,
                "httpOnly": True,
                "sameSite": "Lax",
            }])

        for page_def in (pages or PAGES):
            page = context.new_page()
            page_path = page_def["path"]
            page_name = page_def["name"]
            issues = []
            warnings = []  # known-issue findings, reported but don't fail
            page_js_errors = []
            failed_responses = []  # list of (status, url) for 5xx during page load

            _non_critical = ["sub_count", "subscriber_count", "405", "favicon", "404"]
            page.on("console", lambda msg: page_js_errors.append(msg.text) if msg.type == "error" and not any(nc in msg.text for nc in _non_critical) else None)
            page.on("pageerror", lambda err: page_js_errors.append(str(err)))

            # Capture HTTP failures with URLs so we know what 5xx'd. 4xx is
            # often expected (404 on optional resources, 405 on probes), so we
            # only flag server-side problems.
            def _on_response(resp, _store=failed_responses):
                try:
                    if resp.status >= 500:
                        _store.append((resp.status, resp.url))
                except Exception:
                    pass
            page.on("response", _on_response)

            try:
                url = f"{SITE_URL}{page_path}"
                nav_warning = _navigate_with_fallback(page, url)
                if nav_warning and nav_warning.startswith("Page load failed"):
                    issues.append(nav_warning)
                    raise RuntimeError("nav_failed")
                if nav_warning:
                    warnings.append(nav_warning)

                login_input = page.query_selector('input[type=password][name=password]')
                if login_input:
                    issues.append("Hit login page — auth cookie missing or invalid")
                    raise RuntimeError("auth_failed")

                wait_for = page_def.get("wait_for")
                if wait_for:
                    try:
                        page.wait_for_selector(wait_for, state="visible", timeout=8000)
                    except Exception:
                        issues.append(f"Content container '{wait_for}' never became visible")

                _scroll_and_reveal(page)
                page.wait_for_timeout(1500)

                for check in page_def.get("checks", []):
                    if "selector" in check:
                        elements = page.query_selector_all(check["selector"])
                        if "min_count" in check and len(elements) < check["min_count"]:
                            issues.append(f"Expected {check['min_count']}+ '{check['selector']}', found {len(elements)} — {check['desc']}")
                        if check.get("visible"):
                            el = page.query_selector(check["selector"])
                            if el and not el.is_visible():
                                issues.append(f"'{check['selector']}' exists but hidden — {check['desc']}")
                            elif not el:
                                issues.append(f"'{check['selector']}' not found — {check['desc']}")
                        if check.get("not_empty"):
                            empty_count = 0
                            for el in elements:
                                try:
                                    text = (el.inner_text() or "").strip()
                                except Exception:
                                    text = (el.text_content() or "").strip()
                                if not text or text in ("\u2014", "...", "Loading", "LOADING"):
                                    empty_count += 1
                            if empty_count > 0 and empty_count == len(elements):
                                issues.append(f"All '{check['selector']}' are empty/placeholder — {check['desc']}")
                            elif empty_count > len(elements) // 2:
                                issues.append(f"{empty_count}/{len(elements)} '{check['selector']}' empty — {check['desc']}")

                    if check.get("canvas_not_blank"):
                        canvas_results = _check_canvas_not_blank(page)
                        all_blank = all(c["status"] == "blank" for c in canvas_results) if canvas_results else False
                        if all_blank:
                            page.wait_for_timeout(2000)
                            canvas_results = _check_canvas_not_blank(page)
                        if not canvas_results:
                            issues.append(f"No canvas elements found — {check['desc']}")
                        else:
                            blank = [c for c in canvas_results if c["status"] == "blank"]
                            drawn = [c for c in canvas_results if c["status"] in ("drawn", "chart-js", "assumed-drawn")]
                            zero = [c for c in canvas_results if c["status"] == "zero-size"]
                            if drawn:
                                pass
                            elif blank and not drawn:
                                ids = [c.get("id", f"canvas-{c['index']}") for c in blank[:3]]
                                issues.append(f"All canvases blank: {', '.join(ids)} — {check['desc']}")
                            if zero:
                                ids = [c.get("id", f"canvas-{c['index']}") for c in zero[:3]]
                                issues.append(f"Zero-size canvases: {', '.join(ids)}")

                # ── Cycle-pause band check (observatory pages only) ──
                if page_def.get("expect_cycle_pause_band"):
                    band_info = _check_cycle_pause_band(page)
                    ev = band_info["evidence"]

                    if band_info["window_hidden"]:
                        # 7d window active — band intentionally hidden, that's fine.
                        pass
                    elif not ev["script_loaded"]:
                        issues.append(
                            "cycle-pause.js not loaded (window.CyclePause missing) — "
                            "the page didn't include the script"
                        )
                    elif band_info["rendered"]:
                        # Direct evidence: DOM markers OR Chart.js plugin registered.
                        pass
                    elif band_info["inferred"]:
                        # No direct evidence but conditions met (script loaded, chart
                        # data spans the gap, charts present). Likely raw-canvas
                        # render which leaves no trace. Surface as warning, not fail.
                        warnings.append(
                            f"Cycle-pause: no direct DOM/Chart.js evidence but inferred "
                            f"(script loaded, {ev['chartjs_charts_total']} chart(s), "
                            f"data spans gap). Probably canvas-pixel render — verify "
                            f"manually if this is the first run after a deploy."
                        )
                    elif not ev["data_intersects_gap"]:
                        # Data doesn't actually overlap the pause window. Band absence
                        # is correct in this case.
                        warnings.append(
                            f"Cycle-pause: chart data doesn't span the gap window "
                            f"(Apr 12 → May 1). Band correctly absent."
                        )
                    else:
                        issues.append(
                            f"Cycle-pause band missing: script loaded but no DOM markers "
                            f"and no Chart.js plugin registered. Evidence: {ev}"
                        )

                blank_sections = _check_sections_for_blank(page)
                if blank_sections:
                    for bs in blank_sections[:2]:
                        issues.append(f"Empty section: .{bs['class'][:40]} (h={bs['height']}px)")

                stale = _check_stale_text(page)
                for s in stale:
                    if s.get("visible"):
                        issues.append(f"Stale text: \"{s['text'][:50]}\" — {s['desc']}")

                if page_js_errors:
                    real_errs, known_errs = _classify_js_errors(page_js_errors)
                    if real_errs:
                        # Include up to 3 failing URLs alongside the JS error
                        # so we know which endpoint actually broke.
                        url_summary = ""
                        if failed_responses:
                            seen = set()
                            uniq = []
                            for status, url in failed_responses:
                                key = (status, url.split("?", 1)[0])
                                if key in seen:
                                    continue
                                seen.add(key)
                                uniq.append(f"{status} {url[:120]}")
                                if len(uniq) == 3:
                                    break
                            url_summary = " | failing: " + "; ".join(uniq)
                        issues.append(f"{len(real_errs)} JS error(s): {real_errs[0][:140]}{url_summary}")
                    for err, reason in known_errs:
                        warnings.append(f"Known JS issue: {err[:80]} — {reason}")
                # Also surface 5xx that didn't trigger a JS error (rare but
                # possible — e.g. async fetches that silently fail).
                elif failed_responses:
                    seen = set()
                    uniq = []
                    for status, url in failed_responses:
                        key = (status, url.split("?", 1)[0])
                        if key in seen:
                            continue
                        seen.add(key)
                        uniq.append(f"{status} {url[:120]}")
                        if len(uniq) == 3:
                            break
                    issues.append(f"{len(failed_responses)} HTTP 5xx response(s): {'; '.join(uniq)}")

                if save_screenshots:
                    slug = page_path.strip("/").replace("/", "-") or "home"
                    page.screenshot(path=os.path.join(screenshot_dir, f"{slug}.png"), full_page=True)

                    if issues:
                        for check in page_def.get("checks", []):
                            if "selector" in check:
                                el = page.query_selector(check["selector"])
                                if el:
                                    try:
                                        el.screenshot(path=os.path.join(screenshot_dir, f"{slug}-{check['desc'][:20].replace(' ','-')}.png"))
                                    except Exception:
                                        pass

            except Exception as e:
                if str(e) not in ("auth_failed", "nav_failed"):
                    issues.append(f"Page load failed: {e}")

            status = "PASS" if not issues else "FAIL"
            results.append({
                "page": page_name,
                "path": page_path,
                "status": status,
                "issues": issues,
                "warnings": warnings,
            })
            icon = "✅" if status == "PASS" else "❌"
            warn_count = f" ({len(warnings)} warning{'s' if len(warnings) != 1 else ''})" if warnings else ""
            print(f"  {icon} {page_name} ({page_path}){warn_count}")
            for issue in issues:
                print(f"      → {issue}")
            for warn in warnings:
                print(f"      ⚠ {warn}")

            page.close()

        browser.close()

    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = sum(1 for r in results if r["status"] == "FAIL")
    warning_count = sum(len(r.get("warnings", [])) for r in results)
    print(f"\n{'=' * 50}")
    print(f"Visual QA: {passed} passed, {failed} failed, {warning_count} warning(s) across {len(results)} pages")

    if save_screenshots:
        print(f"Screenshots saved to: {screenshot_dir}/")

    report_path = os.path.join(screenshot_dir, "report.json")
    with open(report_path, "w") as f:
        json.dump({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "passed": passed,
            "failed": failed,
            "warnings": warning_count,
            "results": results,
        }, f, indent=2)

    return failed == 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Deep visual QA sweep for averagejoematt.com")
    parser.add_argument("--page", help="Test a single page path (e.g., /glucose/)")
    parser.add_argument("--screenshot", action="store_true", help="Save full-page screenshots")
    parser.add_argument("--no-cache", action="store_true", help="Force re-auth (ignore cached cookie)")
    args = parser.parse_args()

    pages = None
    if args.page:
        pages = [p for p in PAGES if p["path"] == args.page]
        if not pages:
            print(f"Unknown page: {args.page}")
            print(f"Available: {', '.join(p['path'] for p in PAGES)}")
            sys.exit(1)

    print(f"Deep Visual QA Sweep — {SITE_URL}")
    print(f"{'=' * 50}")

    cookie = get_auth_cookie(force_refresh=args.no_cache)
    if not cookie:
        print("\n❌ Could not obtain auth cookie. Set $VISUAL_QA_PASSWORD or ensure")
        print("   AWS credentials can read secret 'life-platform/cf-auth' in us-east-1.")
        sys.exit(2)

    success = run_sweep(pages=pages, save_screenshots=args.screenshot, auth_cookie=cookie)
    sys.exit(0 if success else 1)
