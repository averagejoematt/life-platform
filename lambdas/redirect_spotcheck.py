"""redirect_spotcheck.py — #1430: weekly legacy-redirect spot-check.

84 legacy pages 301 via the CloudFront `v4-redirects` function, generated
1:1 from redirects.map by scripts/v4_migration_inventory.py (see
deploy/v4_cutover.sh). Nothing continuously verified those redirects still
resolve correctly — a CloudFront function edit or a redirects.map drift
could silently rot old-URL link equity and reader bookmarks.

Pure sampling/verification logic lives here (no AWS, unit-testable offline);
qa_smoke_lambda.py wires it into a Check and gates it to a weekly cadence.

Design (per the issue's acceptance criteria):
  - Deterministic, DATE-SEEDED sampling: which bucket runs is a function of
    the ISO week number, not `random`, so a real run is naturally
    date-dependent while a pinned date/seed makes the unit tests
    deterministic (no flakes).
  - Full-map rotation: entries are partitioned into N_BUCKETS by their index
    in the (sorted) map; the bucket sampled = iso_week % N_BUCKETS. With
    N_BUCKETS=5 every entry gets checked roughly once every 5 weeks (~1
    month), not just entries that happen to draw a lucky random pick.
  - Read-only GETs with redirect-following DISABLED. urllib.request follows
    redirects automatically via the default HTTPRedirectHandler — verified
    empirically (2026-07-20, live against averagejoematt.com) that even a
    custom HTTPRedirectHandler whose redirect_request() returns None does
    NOT make urlopen() return the 301 response object; CPython's
    HTTPRedirectHandler.http_error_302 just returns None in that case,
    which is treated as "unhandled" and falls through to
    HTTPDefaultErrorHandler, which raises urllib.error.HTTPError. So the
    correct + verified pattern is: build the opener WITH the
    redirect-request-blocking handler (belt-and-suspenders — it guarantees
    the redirect is never silently followed even if handler dispatch order
    ever changes), and read the real status/Location off the raised
    HTTPError.
"""

from __future__ import annotations

import os
import urllib.error
import urllib.request

N_BUCKETS = 5  # ~1 calendar month to cover the whole map at one bucket/week
EXPECTED_REDIRECT_CODES = (301, 308)  # CloudFront function emits 301; 308 tolerated if it ever changes


def _redirects_map_candidates():
    """Search order for redirects.map. In the bundled lambdas/ tree the file
    is staged alongside this module (deploy/build_bundle.py); locally it
    lives at the repo root."""
    here = os.path.dirname(os.path.abspath(__file__))
    return [
        os.environ.get("REDIRECTS_MAP_PATH"),
        os.path.join(here, "redirects.map"),  # bundled: staged at the tree root, alongside this module
        os.path.join(os.path.dirname(here), "redirects.map"),  # repo: lambdas/../redirects.map
    ]


def load_redirects_map(path=None):
    """Parse redirects.map into a list of (old_path, new_path) tuples, in file order.

    redirects.map is tab-separated, one `old\\tnew` pair per line, written
    sorted by scripts/v4_migration_inventory.py — so file order is stable
    and index-based bucketing is reproducible run over run.
    """
    candidates = [path] if path else _redirects_map_candidates()
    for cand in candidates:
        if cand and os.path.exists(cand):
            pairs = []
            with open(cand, encoding="utf-8") as fh:
                for line in fh:
                    line = line.rstrip("\n")
                    if not line or "\t" not in line:
                        continue
                    old, new = line.split("\t", 1)
                    pairs.append((old, new))
            return pairs
    raise FileNotFoundError(f"redirects.map not found in any of: {[c for c in candidates if c]}")


def bucket_for_week(iso_week: int, n_buckets: int = N_BUCKETS) -> int:
    """Deterministic bucket index for a given ISO week number. Pure — the
    date-seeded part of the sampling: the real lambda run derives iso_week
    from the wall clock, the unit test passes an explicit int."""
    return iso_week % n_buckets


def sample_entries(entries, bucket: int, n_buckets: int = N_BUCKETS):
    """Return the subset of `entries` whose index falls in `bucket` (index % n_buckets == bucket).

    Index-based (not hash-based) so the partition is legible and stable
    across runs as long as redirects.map's sort order doesn't change; a
    resort only reshuffles which entries share a bucket, it never drops
    coverage (every index still lands in exactly one of the n_buckets).
    """
    return [pair for i, pair in enumerate(entries) if i % n_buckets == bucket]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Blocks automatic redirect-following. See module docstring — combined
    with catching urllib.error.HTTPError in verify_redirect(), this is the
    empirically-verified way to inspect a 301's real status + Location
    header instead of silently landing on the final destination."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def build_no_redirect_opener():
    """Build a urllib opener that never follows redirects."""
    return urllib.request.build_opener(_NoRedirect)


def verify_redirect(opener, base_url: str, old_path: str, expected_target: str, timeout: int = 10):
    """GET base_url + old_path through `opener` and assert it's the expected redirect.

    Returns (kind, message) where kind is one of:
      "ok"    — status + Location matched (301/308 to the expected target)
      "fail"  — a REAL redirect regression: wrong status, wrong Location, or
                no redirect observed at all (link equity / bookmark rot)
      "error" — a transient fetch problem (DNS/timeout/connection) — never a
                verdict on the redirect itself, kept separate so one flaky
                connection doesn't read as a broken redirect
    Never raises.
    """
    url = base_url.rstrip("/") + old_path
    try:
        resp = opener.open(url, timeout=timeout)
    except urllib.error.HTTPError as e:
        if e.code not in EXPECTED_REDIRECT_CODES:
            return "fail", f"{old_path} -> HTTP {e.code} (expected a {EXPECTED_REDIRECT_CODES} redirect)"
        location = e.headers.get("Location")
        if location != expected_target:
            return "fail", f"{old_path} -> {e.code} but Location={location!r} (expected {expected_target!r})"
        return "ok", f"{old_path} -> {e.code} {location} (ok)"
    except Exception as e:
        return "error", f"{old_path} -> request error (fail-soft): {str(e)[:150]}"
    else:
        # No exception at all means the opener followed the redirect (or the
        # path 200'd directly) instead of surfacing it — either way redirects.map
        # promised a 301 that didn't happen as expected. This is a real finding,
        # not a fetch error.
        return "fail", f"{old_path} -> no redirect observed (got HTTP {getattr(resp, 'status', '?')} directly)"


def run_spotcheck(
    base_url: str, iso_week: int, redirects_path=None, opener=None, entries=None, n_buckets: int = N_BUCKETS, timeout: int = 10
):
    """Orchestrate one weekly sample: load the map, pick this week's bucket, verify each entry.

    `entries` lets a caller (tests) inject a fixed map instead of reading
    redirects.map from disk. `opener` lets a caller inject a fake opener.
    Returns a dict: {bucket, n_total, n_sampled, sampled, failures, errors}.
    `failures` are real redirect regressions; `errors` are transient fetch
    problems (kept separate — see verify_redirect's docstring).
    """
    if entries is None:
        entries = load_redirects_map(redirects_path)
    bucket = bucket_for_week(iso_week, n_buckets)
    sampled = sample_entries(entries, bucket, n_buckets)
    if opener is None:
        opener = build_no_redirect_opener()

    failures, errors = [], []
    for old_path, new_path in sampled:
        kind, message = verify_redirect(opener, base_url, old_path, new_path, timeout=timeout)
        if kind == "fail":
            failures.append(message)
        elif kind == "error":
            errors.append(message)

    return {
        "bucket": bucket,
        "n_buckets": n_buckets,
        "n_total": len(entries),
        "n_sampled": len(sampled),
        "sampled": sampled,
        "failures": failures,
        "errors": errors,
    }
