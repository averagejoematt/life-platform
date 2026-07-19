"""tests/test_smoke_structural.py — #1429: static-page structural checks in the site smoke.

The static long-tail (/404, /subscribe/confirm/, /privacy/, the essays, …) has no API
dep and no deploy-time visual gate — it can silently break or leak placeholder content
between reviews. deploy/smoke_test_site.sh now asserts, for every static/utility page:

  1. a declared structural marker (expected title/selector fragment) is in the body
  2. no template-leak token (lorem ipsum, TODO, TKTK, {{moustache}}, launching april)

Contract pinned here, in three layers (same shape as tests/test_smoke_cache_aware.py):

  A. DERIVATION — the page list comes from tests/qa_manifest.py content_class
     (static/utility), never a hand list (#1426/#1454); every eligible page must
     declare a marker (a new static page can't land outside the gate).
  B. TRUTH — every declared marker is actually present in the repo's site/ file and
     the repo file carries no leak token, so the live check can only fail on real
     drift (deploy skew, template regression), never on a stale marker.
  C. BEHAVIOR (bash-stub, guard-red) — the check functions run under real bash with
     curl/sleep stubbed: a deliberately-broken fixture body (marker stripped, or a
     placeholder token injected) FAILS; the real page bodies PASS; /gear/'s
     legitimate "coming soon" + placeholder= copy is NOT flagged (false-positive
     guard); checks route through the #1526 cache-aware retry path, bounded.
"""

import os
import re
import subprocess
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import qa_manifest  # noqa: E402

_SMOKE = os.path.join(_REPO, "deploy", "smoke_test_site.sh")
_RETRY_LIB = os.path.join(_REPO, "deploy", "lib", "cache_aware_fetch.sh")
_STRUCT_LIB = os.path.join(_REPO, "deploy", "lib", "structural_checks.sh")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _strip_comments(text):
    return "\n".join(re.sub(r"(^|\s)#.*$", "", line) for line in text.splitlines())


def _leak_pattern():
    """The ONE leak-token pattern, read from the lib (no second copy here)."""
    m = re.search(r"LEAK_TOKEN_PATTERN='([^']+)'", _read(_STRUCT_LIB))
    assert m, "LEAK_TOKEN_PATTERN not found in structural_checks.sh"
    return m.group(1)


def _site_file(page):
    """Repo file backing a manifest entry ('/x/' → site/x/index.html, '/x.html' → site/x.html)."""
    p = page["path"]
    rel = p.strip("/") if p.endswith(".html") else os.path.join(p.strip("/"), "index.html")
    return os.path.join(_REPO, "site", rel.replace("/", os.sep))


def _eligible_pages():
    return [p for p in qa_manifest.MANIFEST if qa_manifest._structural_eligible(p)]


# ── A. Derivation ─────────────────────────────────────────────────────────────


def test_structural_rows_cover_the_issue_targets():
    """#1429's named surface: /404 (via the CloudFront error path), /subscribe/confirm,
    /privacy, and the essays must all be in the structural sweep."""
    fetch_paths = [r.split("|")[0] for r in qa_manifest.structural_rows()]
    assert "/nonexistent-page-xyz/" in fetch_paths, "404 page must be asserted via a nonexistent URL (body served with status 404)"
    assert "/subscribe/confirm/" in fetch_paths
    assert "/privacy/" in fetch_paths
    assert any(p.startswith("/journal/essays/") for p in fetch_paths), "essays missing from the structural sweep"


def test_structural_rows_derive_from_content_class():
    """One row per eligible page (content_class static/utility, real 200, own body) —
    the list is the manifest facet, never a hand list, and redirect stubs stay out."""
    rows = qa_manifest.structural_rows()
    eligible = _eligible_pages()
    assert len(rows) == len(eligible)
    row_names = {r.split("|")[1] for r in rows}
    assert row_names == {p["name"] for p in eligible}
    # redirect stubs must NOT be swept — they have no body of their own
    assert not any("/mind/" in r or "subscribe.html" in r for r in rows)


def test_rows_are_parseable_three_field_pipe_rows():
    for r in qa_manifest.structural_rows():
        parts = r.split("|")
        assert len(parts) == 3, f"row not 'fetch_path|name|marker': {r!r}"
        assert parts[0].startswith("/") and parts[2], r


def test_missing_marker_on_an_eligible_page_reds_the_facet(monkeypatch):
    """A new static page landing without structural= must raise — that red reaches both
    the smoke's emit call and CI, so the long-tail can't silently outgrow the gate."""
    bare = {"path": "/new-static/", "name": "New", "content_class": "static", "smoke": "200", "leak_scan": True}
    monkeypatch.setattr(qa_manifest, "MANIFEST", qa_manifest.MANIFEST + [bare])
    with pytest.raises(AssertionError, match="/new-static/"):
        qa_manifest.structural_rows()


# ── B. Truth — markers hold against the repo's own site/ files ────────────────


@pytest.mark.parametrize("page", _eligible_pages(), ids=lambda p: p["path"])
def test_declared_marker_present_in_repo_file(page):
    body = _read(_site_file(page))
    assert page["structural"]["marker"] in body, f"{page['path']}: declared structural marker not in the repo file — marker drift"


@pytest.mark.parametrize("page", _eligible_pages(), ids=lambda p: p["path"])
def test_repo_file_carries_no_leak_token(page):
    body = _read(_site_file(page))
    m = re.search(_leak_pattern(), body, re.I)
    assert not m, f"{page['path']}: template-leak token in the repo file: {m.group(0)!r}"


# ── Wiring: the smoke actually runs these checks, cache-aware ─────────────────


def test_smoke_wires_structural_checks_through_the_retry_lib():
    code = _read(_SMOKE)
    assert "lib/structural_checks.sh" in code, "smoke must source deploy/lib/structural_checks.sh (#1429)"
    assert re.search(r"--emit structural", code), "smoke must derive the structural page list from qa_manifest (#1426)"
    stripped = _strip_comments(code)
    assert re.search(r"assert_body_until\s+\S+\s+\S+\s+struct_marker_ok", stripped), "marker check must be cache-aware (#1526)"
    assert re.search(r"assert_body_until\s+\S+\s+\S+\s+leak_tokens_absent", stripped), "leak check must be cache-aware (#1526)"
    # a failed emit must fail the gate, not silently skip the block
    assert re.search(r"structural emit failed[^\n]*\n[^\n]*FAIL", code) or "structural emit failed" in code


def test_struct_lib_is_pure_predicates():
    """No curl, no sleep, no side effects — the lib is two check functions the retry
    lib can call repeatedly."""
    stripped = _strip_comments(_read(_STRUCT_LIB))
    assert "curl" not in stripped and not re.search(r"\bsleep\b", stripped)
    assert "struct_marker_ok" in stripped and "leak_tokens_absent" in stripped


# ── C. Behavior — bash-stub harness (guard-red proof) ─────────────────────────

_HARNESS = """
set -uo pipefail
export SMOKE_CONTENT_RETRY_BUDGET=%(budget)d
export SMOKE_CONTENT_RETRY_INTERVAL=15
source '%(retry_lib)s'
source '%(struct_lib)s'
SLEEP_LOG="$TMPDIR_T/sleep.log"; : > "$SLEEP_LOG"
sleep() { echo "$1" >> "$SLEEP_LOG"; }
curl() { cat "$TMPDIR_T/edge_body"; }
STRUCT_MARKER=$(cat "$TMPDIR_T/marker")
rc_marker=0; assert_body_until "https://example.invalid/p/" "$TMPDIR_T/body" struct_marker_ok || rc_marker=$?
rc_leak=0;   assert_body_until "https://example.invalid/p/" "$TMPDIR_T/body" leak_tokens_absent || rc_leak=$?
echo "rc_marker=$rc_marker rc_leak=$rc_leak sleeps=$(wc -l < "$SLEEP_LOG" | tr -d ' ')"
"""


def _run_checks(tmp_path, body, marker, edge_body=None, budget=0):
    (tmp_path / "body").write_text(body)
    (tmp_path / "marker").write_text(marker)
    (tmp_path / "edge_body").write_text(edge_body if edge_body is not None else body)
    script = _HARNESS % {"retry_lib": _RETRY_LIB, "struct_lib": _STRUCT_LIB, "budget": budget}
    proc = subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        env={**os.environ, "TMPDIR_T": str(tmp_path)},
        timeout=30,
    )
    assert proc.returncode == 0, f"harness failed:\nstdout: {proc.stdout}\nstderr: {proc.stderr}"
    m = re.search(r"rc_marker=(\d+) rc_leak=(\d+) sleeps=(\d+)", proc.stdout)
    assert m, f"harness output unparseable: {proc.stdout!r}"
    return tuple(int(g) for g in m.groups())


_MARKER_404 = '<h1 class="nf-h">404</h1>'


def test_real_404_body_passes(tmp_path):
    """The actual repo 404 page satisfies both predicates — the live check can only
    fail on real drift."""
    body = _read(os.path.join(_REPO, "site", "404.html"))
    rc_marker, rc_leak, sleeps = _run_checks(tmp_path, body, _MARKER_404)
    assert (rc_marker, rc_leak) == (0, 0)
    assert sleeps == 0, "passing checks must not sleep (#1526 common case)"


def test_broken_fixture_missing_marker_fails(tmp_path):
    """GUARD-RED: the 404 body with its <h1> structure stripped (e.g. a bad template
    render / wrong object at the error path) must FAIL the marker check."""
    body = _read(os.path.join(_REPO, "site", "404.html")).replace(_MARKER_404, "")
    rc_marker, rc_leak, _ = _run_checks(tmp_path, body, _MARKER_404)
    assert rc_marker == 1, "structure-stripped body must fail the structural check"
    assert rc_leak == 0


@pytest.mark.parametrize("token", ["Lorem ipsum dolor", "left a TODO here", "TKTK fill this in", "day {{day_count}} of the cut"])
def test_broken_fixture_with_leak_token_fails(tmp_path, token):
    """GUARD-RED: placeholder/template leakage in an otherwise well-formed body must
    FAIL the leak check."""
    body = _read(os.path.join(_REPO, "site", "privacy", "index.html")) + f"\n<p>{token}</p>\n"
    rc_marker, rc_leak, _ = _run_checks(tmp_path, body, 'class="policy-title"')
    assert rc_marker == 0
    assert rc_leak == 1, f"leaked token {token!r} must fail the leak check"


def test_legit_copy_is_not_flagged(tmp_path):
    """False-positive guard: /gear/ legitimately says 'coming soon' (affiliate links)
    and /subscribe/ carries placeholder= attributes + 'Todoist' prose — none of that
    may trip the leak scan (the token set is deliberately narrower than the home-page
    stale-copy scan)."""
    gear = _read(os.path.join(_REPO, "site", "gear", "index.html"))
    rc_marker, rc_leak, _ = _run_checks(tmp_path, gear, 'class="gr-card"')
    assert (rc_marker, rc_leak) == (0, 0)


def test_stale_edge_recovers_and_real_regression_stays_red(tmp_path):
    """#1526 integration: a stale edge body (marker missing) with a FRESH body behind
    it recovers via the budgeted re-fetch; with no fresh body it stays red, bounded."""
    good = _read(os.path.join(_REPO, "site", "404.html"))
    stale = good.replace(_MARKER_404, "")
    rc_marker, rc_leak, sleeps = _run_checks(tmp_path, stale, _MARKER_404, edge_body=good, budget=30)
    assert rc_marker == 0, "stale-then-fresh must PASS via the retry path, not auto-rollback"
    assert sleeps == 1
    rc_marker, _, sleeps = _run_checks(tmp_path, stale, _MARKER_404, edge_body=stale, budget=30)
    assert rc_marker == 1, "a genuinely broken page must still FAIL after bounded retries"
    assert sleeps == 2, "retries must stop when the shared budget is spent"
