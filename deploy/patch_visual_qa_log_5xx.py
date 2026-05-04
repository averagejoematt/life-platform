#!/usr/bin/env python3
"""
Patch tests/visual_qa.py to log 5xx URLs alongside JS errors.

Adds a Playwright `response` listener that captures status >= 500 with the URL,
then surfaces those URLs in the "JS error(s)" issue line so we know what's
actually failing.

Idempotent: running twice is a no-op.

Run from project root:
    python3 deploy/patch_visual_qa_log_5xx.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "tests" / "visual_qa.py"

# ── Edit 1: add failed_responses collector + response listener ──────────────
OLD_1 = """            page = context.new_page()
            page_path = page_def["path"]
            page_name = page_def["name"]
            issues = []
            warnings = []  # known-issue findings, reported but don't fail
            page_js_errors = []

            _non_critical = ["sub_count", "subscriber_count", "405", "favicon", "404"]
            page.on("console", lambda msg: page_js_errors.append(msg.text) if msg.type == "error" and not any(nc in msg.text for nc in _non_critical) else None)
            page.on("pageerror", lambda err: page_js_errors.append(str(err)))"""

NEW_1 = """            page = context.new_page()
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
            page.on("response", _on_response)"""

# ── Edit 2: surface failed URLs alongside JS errors in the issues list ──────
OLD_2 = """                if page_js_errors:
                    real_errs, known_errs = _classify_js_errors(page_js_errors)
                    if real_errs:
                        issues.append(f"{len(real_errs)} JS error(s): {real_errs[0][:140]}")
                    for err, reason in known_errs:
                        warnings.append(f"Known JS issue: {err[:80]} — {reason}")"""

NEW_2 = """                if page_js_errors:
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
                    issues.append(f"{len(failed_responses)} HTTP 5xx response(s): {'; '.join(uniq)}")"""


def main():
    if not TARGET.is_file():
        print(f"ERROR: {TARGET} not found")
        return 1

    src = TARGET.read_text()

    # Idempotency check — both edits must already be present, or both absent.
    has_1 = "failed_responses = []  # list of (status, url) for 5xx" in src
    has_2 = "failing: " in src

    if has_1 and has_2:
        print("Already patched — no changes made.")
        return 0

    if OLD_1 not in src:
        print(f"ERROR: Edit 1 anchor not found. File may have been modified.")
        return 2
    if OLD_2 not in src:
        print(f"ERROR: Edit 2 anchor not found. File may have been modified.")
        return 3

    src = src.replace(OLD_1, NEW_1, 1)
    src = src.replace(OLD_2, NEW_2, 1)
    TARGET.write_text(src)
    print(f"Patched {TARGET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
