#!/usr/bin/env python3
"""
deploy/refresh_upstream_fixtures.py — the LIVE-refresh path for the upstream-API
contract fixtures (ER-02).

The committed fixtures under tests/fixtures/upstream/{source}/{endpoint}.json pin
the *shape* each ingestion transform depends on. tests/test_upstream_contracts.py
asserts against those committed files — fully offline, no creds. THIS script is the
only place that touches live vendor APIs: it re-pulls one day per source, scrubs
tokens/PII, and prints a unified diff vs the committed fixture.

    The diff IS the drift report. A non-empty diff on a refresh means the vendor
    changed the payload out from under the transform — exactly the silent-drift
    class ER-02 exists to catch. Review the diff, then re-run with --apply to
    rewrite the fixture and let the contract test re-baseline.

Usage (run in your terminal, with AWS creds — Matthew runs all live calls):

    # Show the drift for every live-refreshable source (no writes):
    python3 deploy/refresh_upstream_fixtures.py --date 2026-06-08

    # Refresh just Whoop and write the updated fixtures:
    python3 deploy/refresh_upstream_fixtures.py --source whoop --date 2026-06-08 --apply

    # Scrub + install a manually captured raw payload (webhook/normalized sources):
    python3 deploy/refresh_upstream_fixtures.py --source hae --endpoint blood_glucose \
        --from-file ~/captured_hae_payload.json --apply

Live-refreshable (SIMP-2 fetch_day returns the raw vendor shape):  whoop, withings, garmin.
--from-file only (push/normalized sources):                        strava, hae.

NB: the live path calls each ingestion Lambda's real authenticate(), which for
Whoop/Withings rotates the OAuth refresh token (secret write-back). That is the
genuine ingestion path; it is safe but it does mutate the stored token.

This module's TOP-LEVEL imports are stdlib-only on purpose, so the contract test
can `from refresh_upstream_fixtures import scan_for_secrets` without dragging in
boto3 / the ingestion Lambdas. Heavy imports happen lazily inside _fetch_live().
"""
from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURE_ROOT = os.path.join(REPO, "tests", "fixtures", "upstream")

# ── Scrub / secret-scan (shared with the contract test) ──────────────────────
#
# Single source of truth for "what counts as a token/PII leak in a fixture."
# scan_for_secrets() is imported by tests/test_upstream_contracts.py to assert
# the *committed* fixtures are clean; scrub()+scan are used here before any write.

# Keys whose VALUE is a credential when it's a non-empty string. Exact (lowered)
# match — so pagination cursors like "next_token" are NOT flagged.
SECRET_KEYS = frozenset(
    {
        "access_token",
        "refresh_token",
        "id_token",
        "token",
        "client_secret",
        "client_id",
        "secret",
        "password",
        "passwd",
        "api_key",
        "apikey",
        "authorization",
        "auth",
        "bearer",
    }
)

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_JWT_RE = re.compile(r"eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}")
_BEARER_RE = re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{6,}")

_REDACTED = "[redacted]"
_REDACTED_EMAIL = "[redacted-email]"


def _scrub_str(value: str) -> str:
    out = _JWT_RE.sub(_REDACTED, value)
    out = _BEARER_RE.sub("Bearer " + _REDACTED, out)
    out = _EMAIL_RE.sub(_REDACTED_EMAIL, out)
    return out


def scrub(obj):
    """Return a copy of obj with credential-valued keys DROPPED and inline token/PII redacted.

    Credential keys are dropped (not placeholder-redacted) so the result is clean
    under scan_for_secrets() — a token field is never part of a transform contract,
    so removing it cannot break a fixture's shape."""
    if isinstance(obj, dict):
        clean = {}
        for k, v in obj.items():
            if isinstance(k, str) and k.lower() in SECRET_KEYS and isinstance(v, str) and v.strip():
                continue  # drop the credential field entirely
            clean[k] = scrub(v)
        return clean
    if isinstance(obj, list):
        return [scrub(v) for v in obj]
    if isinstance(obj, str):
        return _scrub_str(obj)
    return obj


def scan_for_secrets(obj, path: str = "$") -> list[str]:
    """Return a list of human-readable violations (empty == clean)."""
    found: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            here = f"{path}.{k}"
            if isinstance(k, str) and k.lower() in SECRET_KEYS and isinstance(v, str) and v.strip():
                found.append(f"{here}: credential-valued key carries a non-empty string")
            found.extend(scan_for_secrets(v, here))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            found.extend(scan_for_secrets(v, f"{path}[{i}]"))
    elif isinstance(obj, str):
        if _JWT_RE.search(obj):
            found.append(f"{path}: looks like a JWT")
        elif _BEARER_RE.search(obj):
            found.append(f"{path}: looks like a bearer token")
        elif _EMAIL_RE.search(obj):
            found.append(f"{path}: looks like an email address")
    return found


# ── Source registry ──────────────────────────────────────────────────────────
#
# derive(raw) maps one fetch_day() blob → {endpoint: payload}. Only sources whose
# fetch_day returns the RAW vendor shape are live-refreshable; the rest are
# --from-file only (their fetch_day already normalizes, or they are webhook-push).

LIVE_SOURCES = {
    "whoop": {
        "module": "whoop_lambda",
        "derive": lambda raw: {
            "recovery": raw.get("recovery"),
            "sleep": raw.get("sleep"),
            "cycle": raw.get("cycle"),
            "workout": raw.get("workouts"),
        },
    },
    "withings": {
        "module": "withings_lambda",
        "derive": lambda raw: {"measures": raw},
    },
    "garmin": {
        "module": "garmin_lambda",
        "derive": lambda raw: {"daily": raw},
    },
}

# Endpoints maintained only by capturing a real payload and scrubbing it.
FROM_FILE_ONLY = {
    "strava": ["activity"],  # fetch_day returns normalized output, not raw vendor JSON
    "hae": ["blood_glucose", "blood_pressure"],  # webhook-push; no pull endpoint
}


def fixture_path(source: str, endpoint: str) -> str:
    return os.path.join(FIXTURE_ROOT, source, f"{endpoint}.json")


def _load_committed(source: str, endpoint: str):
    p = fixture_path(source, endpoint)
    if not os.path.exists(p):
        return None
    with open(p) as fh:
        return json.load(fh)


def _dump(obj) -> str:
    return json.dumps(obj, indent=2, sort_keys=False, ensure_ascii=False) + "\n"


def _print_diff(source: str, endpoint: str, old, new) -> bool:
    old_s = _dump(old) if old is not None else ""
    new_s = _dump(new)
    diff = list(
        difflib.unified_diff(
            old_s.splitlines(keepends=True),
            new_s.splitlines(keepends=True),
            fromfile=f"committed/{source}/{endpoint}.json",
            tofile=f"refreshed/{source}/{endpoint}.json",
        )
    )
    if not diff:
        print(f"  [{source}/{endpoint}] no drift — fixture matches live.")
        return False
    print(f"  [{source}/{endpoint}] DRIFT:")
    sys.stdout.writelines(diff)
    return True


def _install(source: str, endpoint: str, payload, apply: bool) -> bool:
    """Scrub → assert clean → diff → (optionally) write. Returns True if drift seen."""
    clean = scrub(payload)
    leaks = scan_for_secrets(clean)
    if leaks:
        print(f"  [{source}/{endpoint}] REFUSING: scrub left {len(leaks)} potential secret(s):")
        for v in leaks:
            print(f"      {v}")
        raise SystemExit(2)
    drift = _print_diff(source, endpoint, _load_committed(source, endpoint), clean)
    if apply:
        p = fixture_path(source, endpoint)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as fh:
            fh.write(_dump(clean))
        print(f"  [{source}/{endpoint}] written → {os.path.relpath(p, REPO)}")
    return drift


def _fetch_live(source: str, date_str: str) -> dict:
    """Lazily import the ingestion Lambda + boto3, refresh creds, fetch one day."""
    import boto3  # noqa: E402  (lazy — keeps module import stdlib-only for the test)

    sys.path.insert(0, os.path.join(REPO, "lambdas"))
    sys.path.insert(0, os.path.join(REPO, "lambdas", "ingestion"))
    os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
    os.environ.setdefault("TABLE_NAME", "life-platform")
    os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

    mod = __import__(LIVE_SOURCES[source]["module"])
    secret_id = getattr(mod, "SECRET_NAME")
    sm = boto3.client("secretsmanager", region_name="us-west-2")
    secret = json.loads(sm.get_secret_value(SecretId=secret_id)["SecretString"])
    creds = mod.authenticate(secret)
    raw = mod.fetch_day(creds, date_str)
    if raw is None:
        raise SystemExit(f"{source}: fetch_day returned no data for {date_str} (no weigh-in / no activity?).")
    return LIVE_SOURCES[source]["derive"](raw)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", choices=sorted(set(LIVE_SOURCES) | set(FROM_FILE_ONLY)), help="limit to one source")
    ap.add_argument("--endpoint", help="limit to one endpoint (required with --from-file)")
    ap.add_argument("--date", default=None, help="day to pull, YYYY-MM-DD (live sources)")
    ap.add_argument("--from-file", dest="from_file", help="scrub+install a captured raw payload (no live call)")
    ap.add_argument("--apply", action="store_true", help="write fixtures (default is dry-run / diff-only)")
    args = ap.parse_args()

    if args.from_file:
        if not args.source or not args.endpoint:
            print("--from-file requires --source and --endpoint", file=sys.stderr)
            return 2
        with open(os.path.expanduser(args.from_file)) as fh:
            payload = json.load(fh)
        _install(args.source, args.endpoint, payload, args.apply)
        return 0

    if not args.date:
        print("--date YYYY-MM-DD is required for a live refresh (or use --from-file).", file=sys.stderr)
        return 2

    sources = [args.source] if args.source else list(LIVE_SOURCES)
    any_drift = False
    for source in sources:
        if source not in LIVE_SOURCES:
            print(f"  [{source}] not live-refreshable — capture a payload and use --from-file. Endpoints: {FROM_FILE_ONLY[source]}")
            continue
        print(f"Refreshing {source} for {args.date} …")
        derived = _fetch_live(source, args.date)
        for endpoint, payload in derived.items():
            if payload is None:
                print(f"  [{source}/{endpoint}] live fetch returned null — skipped.")
                continue
            any_drift |= _install(source, endpoint, payload, args.apply)

    if any_drift and not args.apply:
        print("\nDrift detected. Review above, then re-run with --apply to re-baseline the fixture(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
