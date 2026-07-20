"""tests/test_redirect_spotcheck.py — #1430: weekly legacy-redirect spot-check.

84 legacy pages 301 via the CloudFront v4-redirects function generated 1:1
from redirects.map; nothing continuously verified those redirects still
resolve correctly. lambdas/redirect_spotcheck.py adds a deterministic,
date-seeded, rotating sample + a redirect-following-DISABLED HTTP verifier;
qa_smoke_lambda.py wires it to a weekly (Monday PT) cadence.

Covers the issue's three acceptance criteria:
  1. A sampled entry asserts BOTH status (301/308) and Location header.
  2. Sampling rotates by ISO-week bucket so the full map is covered over a
     bounded (~1 month) window — proven by sweeping n_buckets consecutive
     weeks and checking every entry was sampled exactly once.
  3. check_redirect_spotcheck() only runs the network check on the
     scheduled weekday; other days report an explicit paused line (not a
     silent no-op) — and a real failure is exposed as a genuine `.fail()`
     Check, which is qa_smoke_lambda's existing "surfaces visibly" pipeline
     (FailCount metric -> qa-smoke-failures alarm -> digest / direct email,
     per tests/test_qa_smoke_metrics.py) — no new mechanism invented.

Determinism: the real lambda run derives its bucket from the wall-clock ISO
week (date-seeded, per the issue). Every test here pins an explicit
iso_week/weekday instead of touching the clock, so the suite can't flake.
"""

import os
import sys
import urllib.error

# qa_smoke_lambda reads these at import time (conftest supplies fake AWS creds).
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("EMAIL_RECIPIENT", "qa@example.com")
os.environ.setdefault("EMAIL_SENDER", "qa@example.com")

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

import redirect_spotcheck as rs  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ENTRIES = [
    ("/about/", "/story/about/"),
    ("/accountability/", "/data/vices/"),
    ("/achievements/", "/cockpit/"),
    ("/ask/", "/method/ask/"),
    ("/benchmarks/", "/method/benchmarks/"),
    ("/biology/", "/method/biology/"),
    ("/board/", "/method/board/"),
    ("/builders/", "/"),
    ("/challenges/", "/protocols/challenges/"),
    ("/character/", "/cockpit/"),
    ("/chronicle/", "/story/chronicle/"),
    ("/coaches/", "/method/board/"),
]


# ---------------------------------------------------------------------------
# 1. load_redirects_map — parses the REAL committed redirects.map
# ---------------------------------------------------------------------------


def test_load_redirects_map_reads_real_file():
    entries = rs.load_redirects_map(os.path.join(REPO_ROOT, "redirects.map"))
    assert len(entries) > 50, "redirects.map should carry the full ~84-entry legacy surface"
    assert all(old.startswith("/") and new.startswith("/") for old, new in entries)
    # tab-separated, sorted by the generator (scripts/v4_migration_inventory.py)
    assert entries == sorted(entries)


def test_load_redirects_map_missing_file_raises():
    import pytest

    with pytest.raises(FileNotFoundError):
        rs.load_redirects_map("/no/such/path/redirects.map")


# ---------------------------------------------------------------------------
# 2. Deterministic bucketing + full-map rotation over ~1 month
# ---------------------------------------------------------------------------


def test_bucket_for_week_is_pure_and_deterministic():
    assert rs.bucket_for_week(1) == rs.bucket_for_week(1)
    # Wraps modulo n_buckets
    assert rs.bucket_for_week(0, n_buckets=5) == 0
    assert rs.bucket_for_week(5, n_buckets=5) == 0
    assert rs.bucket_for_week(7, n_buckets=5) == 2


def test_sample_entries_partitions_by_index():
    for bucket in range(5):
        sample = rs.sample_entries(ENTRIES, bucket, n_buckets=5)
        assert all(ENTRIES.index(pair) % 5 == bucket for pair in sample)


def test_rotation_covers_full_map_over_n_buckets_consecutive_weeks():
    """The AC's literal requirement: sampling rotates so the full map is
    covered over a bounded (~1 month) window. Sweep N_BUCKETS consecutive
    ISO weeks starting from an arbitrary week and assert every entry in the
    map was sampled EXACTLY once across the sweep — no gaps, no double
    coverage that would starve another entry."""
    seen = []
    start_week = 11  # arbitrary — bucketing is a pure function of week % n_buckets
    for wk in range(start_week, start_week + rs.N_BUCKETS):
        bucket = rs.bucket_for_week(wk, n_buckets=rs.N_BUCKETS)
        seen.extend(rs.sample_entries(ENTRIES, bucket, n_buckets=rs.N_BUCKETS))
    assert sorted(seen) == sorted(ENTRIES)
    assert len(seen) == len(ENTRIES), "each entry must be sampled exactly once per full rotation"


# ---------------------------------------------------------------------------
# 3. verify_redirect — redirect-following DISABLED, status + Location asserted
# ---------------------------------------------------------------------------


class _FakeResp:
    def __init__(self, status):
        self.status = status


class _FakeOpener:
    """Stands in for build_no_redirect_opener(): scripted per-URL responses."""

    def __init__(self, script):
        self.script = script  # url -> ("http_error", code, location) | ("ok", status) | ("raise", Exception)

    def open(self, url, timeout=10):
        kind, *rest = self.script[url]
        if kind == "http_error":
            code, location = rest
            headers = {"Location": location} if location else {}

            class _H(dict):
                def get(self, k, default=None):
                    return headers.get(k, default)

            raise urllib.error.HTTPError(url, code, "redirect", _H(), None)
        if kind == "ok":
            (status,) = rest
            return _FakeResp(status)
        if kind == "raise":
            raise rest[0]
        raise AssertionError(f"unscripted URL in fake opener: {url}")


def test_verify_redirect_ok_on_matching_301_and_location():
    opener = _FakeOpener({"https://example.com/about/": ("http_error", 301, "/story/about/")})
    kind, msg = rs.verify_redirect(opener, "https://example.com", "/about/", "/story/about/")
    assert kind == "ok", msg


def test_verify_redirect_fails_on_wrong_status_code():
    opener = _FakeOpener({"https://example.com/about/": ("http_error", 404, None)})
    kind, msg = rs.verify_redirect(opener, "https://example.com", "/about/", "/story/about/")
    assert kind == "fail"
    assert "404" in msg


def test_verify_redirect_fails_on_wrong_location():
    opener = _FakeOpener({"https://example.com/about/": ("http_error", 301, "/wrong/target/")})
    kind, msg = rs.verify_redirect(opener, "https://example.com", "/about/", "/story/about/")
    assert kind == "fail"
    assert "/wrong/target/" in msg and "/story/about/" in msg


def test_verify_redirect_fails_when_no_redirect_observed_at_all():
    """A path that 200s directly (the opener never raised HTTPError at all)
    is a real regression — redirects.map promised a 301 that didn't happen."""
    opener = _FakeOpener({"https://example.com/about/": ("ok", 200)})
    kind, msg = rs.verify_redirect(opener, "https://example.com", "/about/", "/story/about/")
    assert kind == "fail"


def test_verify_redirect_accepts_308_as_a_valid_redirect_code():
    opener = _FakeOpener({"https://example.com/about/": ("http_error", 308, "/story/about/")})
    kind, msg = rs.verify_redirect(opener, "https://example.com", "/about/", "/story/about/")
    assert kind == "ok", msg


def test_verify_redirect_network_error_is_a_separate_kind_not_a_fail():
    """A transient connection error must never read as a broken redirect —
    it's a distinct 'error' kind so one flaky fetch can't red the run."""
    opener = _FakeOpener({"https://example.com/about/": ("raise", TimeoutError("timed out"))})
    kind, msg = rs.verify_redirect(opener, "https://example.com", "/about/", "/story/about/")
    assert kind == "error"


# ---------------------------------------------------------------------------
# 4. run_spotcheck — end-to-end orchestration with injected entries + opener
# ---------------------------------------------------------------------------


def test_run_spotcheck_all_ok():
    script = {f"https://example.com{old}": ("http_error", 301, new) for old, new in ENTRIES}
    result = rs.run_spotcheck("https://example.com", iso_week=11, entries=ENTRIES, opener=_FakeOpener(script), n_buckets=5)
    assert result["failures"] == []
    assert result["errors"] == []
    assert result["n_sampled"] > 0
    assert result["n_total"] == len(ENTRIES)


def test_run_spotcheck_surfaces_a_real_failure():
    script = {f"https://example.com{old}": ("http_error", 301, new) for old, new in ENTRIES}
    # Break exactly one entry that's in bucket 0 (index 0 -> /about/)
    script["https://example.com/about/"] = ("http_error", 301, "/broken-target/")
    result = rs.run_spotcheck("https://example.com", iso_week=0, entries=ENTRIES, opener=_FakeOpener(script), n_buckets=5)
    assert any("/about/" in f for f in result["failures"])


def test_run_spotcheck_is_deterministic_for_a_pinned_week():
    script = {f"https://example.com{old}": ("http_error", 301, new) for old, new in ENTRIES}
    opener = _FakeOpener(script)
    r1 = rs.run_spotcheck("https://example.com", iso_week=23, entries=ENTRIES, opener=opener, n_buckets=5)
    r2 = rs.run_spotcheck("https://example.com", iso_week=23, entries=ENTRIES, opener=opener, n_buckets=5)
    assert r1["sampled"] == r2["sampled"]
    assert r1["bucket"] == r2["bucket"]


# ---------------------------------------------------------------------------
# 5. qa_smoke_lambda wiring — weekly gate + reuse of the existing fail pipeline
# ---------------------------------------------------------------------------

import qa_smoke_lambda as qa  # noqa: E402


class _FixedNow:
    """Stand-in datetime with a fixed .weekday() and .isocalendar()."""

    def __init__(self, weekday, iso_week, iso_year=2026):
        self._weekday = weekday
        self._iso_week = iso_week
        self._iso_year = iso_year

    def weekday(self):
        return self._weekday

    def isocalendar(self):
        return (self._iso_year, self._iso_week, 1)

    def strftime(self, fmt):
        return "Tuesday" if self._weekday != 0 else "Monday"


def test_check_redirect_spotcheck_pauses_on_non_monday(monkeypatch):
    monkeypatch.setattr(qa, "pt_now", lambda: _FixedNow(weekday=2, iso_week=11))
    (check,) = qa.check_redirect_spotcheck()
    assert check.paused is True
    assert check.passed is True  # paused counts as visible-but-not-a-fault


def test_check_redirect_spotcheck_runs_and_fails_on_monday_with_a_broken_redirect(monkeypatch):
    monkeypatch.setattr(qa, "pt_now", lambda: _FixedNow(weekday=0, iso_week=11))

    import redirect_spotcheck as rs_mod

    def _fake_run_spotcheck(base_url, iso_week, **kwargs):
        assert iso_week == 11
        return {"bucket": 1, "n_buckets": 5, "n_total": 84, "n_sampled": 17, "sampled": [], "failures": ["/about/ -> broken"], "errors": []}

    monkeypatch.setattr(rs_mod, "run_spotcheck", _fake_run_spotcheck)
    checks = qa.check_redirect_spotcheck()
    fails = [c for c in checks if c.passed is False]
    assert len(fails) == 1
    assert "/about/" in fails[0].message


def test_check_redirect_spotcheck_runs_and_passes_clean_on_monday(monkeypatch):
    monkeypatch.setattr(qa, "pt_now", lambda: _FixedNow(weekday=0, iso_week=11))

    import redirect_spotcheck as rs_mod

    def _fake_run_spotcheck(base_url, iso_week, **kwargs):
        return {"bucket": 1, "n_buckets": 5, "n_total": 84, "n_sampled": 17, "sampled": [], "failures": [], "errors": []}

    monkeypatch.setattr(rs_mod, "run_spotcheck", _fake_run_spotcheck)
    checks = qa.check_redirect_spotcheck()
    assert all(c.passed is not False for c in checks)
    assert any(c.passed is True and not c.paused for c in checks)


def test_check_redirect_spotcheck_missing_map_is_warn_not_fail(monkeypatch):
    monkeypatch.setattr(qa, "pt_now", lambda: _FixedNow(weekday=0, iso_week=11))

    import redirect_spotcheck as rs_mod

    def _raise_missing(base_url, iso_week, **kwargs):
        raise FileNotFoundError("redirects.map not found")

    monkeypatch.setattr(rs_mod, "run_spotcheck", _raise_missing)
    checks = qa.check_redirect_spotcheck()
    assert all(c.passed is not False for c in checks), "a packaging gap must warn, not fail — it's not a redirect regression"


def test_check_redirect_spotcheck_wired_into_lambda_handler():
    """AST-check: lambda_handler actually calls check_redirect_spotcheck() —
    a plausible regression class is writing the Check function but never
    wiring it into the run, which the mock-based tests above wouldn't catch."""
    import ast
    import inspect

    src = inspect.getsource(qa.lambda_handler)
    tree = ast.parse(src)
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    assert "check_redirect_spotcheck" in names, "lambda_handler never calls check_redirect_spotcheck() (#1430)"
