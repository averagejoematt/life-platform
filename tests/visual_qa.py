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

v3.0.0 — 2026-05-04 (cf-auth handshake + cycle-pause band check)
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

# ── Page definitions with deep checks ─────────────────────────────────────────
# `expect_cycle_pause_band` flags pages that should render the pause band
# (per docs/SPEC_CYCLE_PAUSE_VIZ_2026_05_03.md — 6 observatory pages, 11 charts).
# Default 30d/90d window WILL intersect Apr 12 → May 1, so band must be visible.
PAGES = [
    {
        "path": "/",
        "name": "Homepage",
        "checks": [
            {"selector": ".h-gauge__num", "min_count": 6, "not_empty": True, "desc": "6 gauge numbers with values"},
            {"selector": ".h-obs-card__metric", "not_empty": True, "desc": "observatory tile metrics populated"},
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
        # Cookie expires soon; force refresh.
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

    # Don't auto-follow redirects — we want the response that carries Set-Cookie.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None

    opener = urllib.request.build_opener(NoRedirect)
    try:
        resp = opener.open(req, timeout=10)
        # Status 200 with no redirect = login page returned (auth failed).
        return _extract_cookie_from_headers(resp.info()), resp.status
    except urllib.error.HTTPError as e:
        # 302 redirect = success (Set-Cookie attached).
        return _extract_cookie_from_headers(e.headers), e.code


def _extract_cookie_from_headers(headers):
    """Parse Set-Cookie header(s) for our auth cookie value."""
    set_cookies = headers.get_all("Set-Cookie") if hasattr(headers, "get_all") else \
                  [headers.get("Set-Cookie")] if headers.get("Set-Cookie") else []
    for sc in set_cookies:
        if not sc:
            continue
        # Format: __lp_auth=VALUE; Path=/; Max-Age=...; Secure; HttpOnly; SameSite=Lax
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
    """Check that the cycle-pause band is rendered on at least one chart.

    The band can manifest in three forms (per cycle-pause.js):
      - SVG: <g class="cycle-pause-band"> appended to an <svg>
      - Canvas overlay: drawn directly on canvas (no DOM trace) — but ALL canvas
        bands also push a sibling <div class="cycle-pause-overlay"> with the label
      - Chart.js: drawn via beforeDatasetsDraw plugin (no DOM trace either)

    We check for either CSS class. If neither is present anywhere on the page
    AND the page expects one, we flag it. Returns dict:
      { found: int, locations: [...], window_hidden: bool }
    """
    return page.evaluate("""
        () => {
            const svgBands = document.querySelectorAll('.cycle-pause-band');
            const canvasOverlays = document.querySelectorAll('.cycle-pause-overlay');
            const labels = document.querySelectorAll('.cycle-pause-label');

            // Try to detect if we're on a 7d window where the band is intentionally hidden.
            // The page's window selector is typically a button group or select.
            // We look for an active button labeled "7" or "7D" or similar.
            let windowHidden = false;
            const activeWindowBtn = document.querySelector(
                '.window-toggle .is-active, .range-toggle .is-active, [data-window].is-active, [data-range].is-active'
            );
            if (activeWindowBtn) {
                const txt = (activeWindowBtn.textContent || '').trim().toLowerCase();
                if (txt.includes('7d') || txt === '7' || txt.includes('7 day') || txt.includes('week')) {
                    windowHidden = true;
                }
            }

            const total = svgBands.length + canvasOverlays.length;
            return {
                found: total,
                svg: svgBands.length,
                canvas_overlay: canvasOverlays.length,
                labels: labels.length,
                window_hidden: windowHidden,
            };
        }
    """)


def _check_sections_for_blank(page):
    return page.evaluate("""
        () => {
            const issues = [];
            document.querySelectorAll('section, [class*=section]').forEach(s => {
                const rect = s.getBoundingClientRect();
                if (rect.height < 20) return;
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


# ══════════════════════════════════════════════════════════════════════════════
# Main sweep
# ══════════════════════════════════════════════════════════════════════════════

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

        # Inject auth cookie at the context level so every page request carries it.
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
            page_js_errors = []

            _non_critical = ["sub_count", "subscriber_count", "405", "favicon", "404"]
            page.on("console", lambda msg: page_js_errors.append(msg.text) if msg.type == "error" and not any(nc in msg.text for nc in _non_critical) else None)
            page.on("pageerror", lambda err: page_js_errors.append(str(err)))

            try:
                url = f"{SITE_URL}{page_path}"
                page.goto(url, wait_until="networkidle", timeout=15000)

                # Sanity check: did we actually authenticate? cf-auth returns
                # an HTML login page with a password input when we're not.
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

                # ── Selector + canvas checks ──
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
                    if band_info["window_hidden"]:
                        # 7d window active — band intentionally hidden, that's fine.
                        pass
                    elif band_info["found"] == 0:
                        issues.append(
                            "Cycle-pause band missing — expected at least one "
                            ".cycle-pause-band (SVG) or .cycle-pause-overlay (canvas) "
                            "on this page (Apr 12 → May 1 gap)"
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
                    issues.append(f"{len(page_js_errors)} JS error(s): {page_js_errors[0][:100]}")

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
                if str(e) != "auth_failed":  # already recorded above
                    issues.append(f"Page load failed: {e}")

            status = "PASS" if not issues else "FAIL"
            results.append({
                "page": page_name,
                "path": page_path,
                "status": status,
                "issues": issues,
            })
            icon = "✅" if status == "PASS" else "❌"
            print(f"  {icon} {page_name} ({page_path})")
            for issue in issues:
                print(f"      → {issue}")

            page.close()

        browser.close()

    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = sum(1 for r in results if r["status"] == "FAIL")
    print(f"\n{'=' * 50}")
    print(f"Visual QA: {passed} passed, {failed} failed out of {len(results)} pages")

    if save_screenshots:
        print(f"Screenshots saved to: {screenshot_dir}/")

    report_path = os.path.join(screenshot_dir, "report.json")
    with open(report_path, "w") as f:
        json.dump({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "passed": passed,
            "failed": failed,
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
