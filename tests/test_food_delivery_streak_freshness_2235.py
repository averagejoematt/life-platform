"""tests/test_food_delivery_streak_freshness_2235.py — #2235: the food_delivery
`STREAK#current` record is written ONCE, at ingestion time
(`ingestion.food_delivery_lambda.ingest_food_delivery_rows`), and never
recomputed relative to "today". A live `get-item` against the real record showed
`updated_at: 2026-03-28`, `streak_days: 3` — a frozen ~133-day-old snapshot that
three consumers (daily_brief, weekly_digest, character_sheet) were each reading
and presenting as a LIVE streak.

Decision (documented in the PR body and in `common.digest_utils
.get_food_delivery_streak_state`'s docstring): WITHHOLD the whole figure once the
food_delivery source is past its `stale_hours` threshold
(`ingestion.source_registry`), rather than recompute `streak_days = today -
last_order_date`. food_delivery is a MANUAL log (hand-run CSV/statement import) —
an ingestion gap means "we don't know", not "clean". Recomputing would assert a
specific, growing abstinence streak the data has no way to back. This matches
ADR-104's behavioural-absence semantics and how every other stale source on this
platform is treated.

Two guard classes, matching the "guard the SET, not the instance" convention
this data class keeps needing (#2209/#2210/#2233 — same partition, disclosure
angle; this is the correctness angle):

  1. Behavioral / mutation-provable — `get_food_delivery_streak_state` itself:
     fresh record -> returned; stale record -> None; missing/malformed
     `updated_at` -> None (withheld, not assumed fresh); read failure -> None.

  2. Structural / guard-the-SET — every static `table.get_item(...)` call site
     anywhere under `lambdas/` whose `Key` dict reads `sk: "STREAK#current"` is
     DERIVED by an AST walk, not hand-enumerated to today's one canonical
     function. Only `common/digest_utils.py::get_food_delivery_streak_state`
     may contain that literal `get_item` call; a future fourth consumer that
     reads the partition directly (bypassing the shared function) reds this
     test the moment it's written.
"""

from __future__ import annotations

import ast
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

from common.digest_utils import get_food_delivery_streak_state  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LAMBDAS = ROOT / "lambdas"
CANONICAL_MODULE = LAMBDAS / "common" / "digest_utils.py"

STALE_HOURS = 336  # food_delivery's stale_hours in ingestion/source_registry.py (14 days)


class _FakeTable:
    """Minimal get_item-only double — this module's function never queries/puts."""

    def __init__(self, item=None, fail=False):
        self._item = item
        self._fail = fail

    def get_item(self, Key=None, **kw):
        if self._fail:
            raise RuntimeError("ddb down")
        if self._item is None:
            return {}
        return {"Item": self._item}


# ---------------------------------------------------------------------------
# Guard 1 — behavioral, mutation-provable
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 8, 8, 12, 0, 0, tzinfo=timezone.utc)


def test_no_record_yields_none():
    table = _FakeTable(item=None)
    assert get_food_delivery_streak_state(table, "matthew", now=_NOW) is None


def test_a_fresh_record_is_returned_verbatim():
    item = {
        "streak_days": 12,
        "last_order_date": "2026-07-27",
        "updated_at": (_NOW - timedelta(hours=10)).isoformat(),
    }
    table = _FakeTable(item=item)
    assert get_food_delivery_streak_state(table, "matthew", now=_NOW) == item


def test_a_record_exactly_at_the_threshold_still_counts():
    item = {"streak_days": 3, "updated_at": (_NOW - timedelta(hours=STALE_HOURS)).isoformat()}
    table = _FakeTable(item=item)
    assert get_food_delivery_streak_state(table, "matthew", now=_NOW) == item


def test_a_record_one_hour_past_the_threshold_is_withheld():
    item = {"streak_days": 3, "updated_at": (_NOW - timedelta(hours=STALE_HOURS + 1)).isoformat()}
    table = _FakeTable(item=item)
    assert get_food_delivery_streak_state(table, "matthew", now=_NOW) is None


def test_the_133_day_stale_record_from_the_live_incident_is_withheld():
    """The exact shape read from prod via a read-only get-item (#2235's finding):
    updated_at 2026-03-28, streak_days 3 — ~133 days stale relative to a plausible
    "now" of 2026-08-08. This is the regression the issue exists to fix."""
    item = {
        "streak_days": 3,
        "last_order_date": "2026-03-25",
        "updated_at": "2026-03-28T18:30:04",
    }
    table = _FakeTable(item=item)
    now = datetime(2026, 8, 8, 18, 0, 0, tzinfo=timezone.utc)
    assert get_food_delivery_streak_state(table, "matthew", now=now) is None


def test_a_missing_updated_at_is_withheld_not_assumed_fresh():
    item = {"streak_days": 40, "last_order_date": "2026-01-01"}
    table = _FakeTable(item=item)
    assert get_food_delivery_streak_state(table, "matthew", now=_NOW) is None


def test_a_malformed_updated_at_is_withheld_not_fatal():
    item = {"streak_days": 40, "updated_at": "not-a-timestamp"}
    table = _FakeTable(item=item)
    assert get_food_delivery_streak_state(table, "matthew", now=_NOW) is None


def test_a_naive_updated_at_is_treated_as_utc():
    """put_item callers stamp isoformat() off an aware UTC datetime, but this must
    not raise (aware-vs-naive TypeError) if a row is ever missing the offset."""
    item = {"streak_days": 3, "updated_at": (_NOW.replace(tzinfo=None) - timedelta(hours=10)).isoformat()}
    table = _FakeTable(item=item)
    assert get_food_delivery_streak_state(table, "matthew", now=_NOW) == item


def test_a_read_failure_is_non_fatal():
    table = _FakeTable(fail=True)
    assert get_food_delivery_streak_state(table, "matthew", now=_NOW) is None


def test_mutation_proof_the_freshness_check_actually_gates():
    """Not a repo mutation — a live demonstration inline: with the threshold
    check disabled the stale 133-day record WOULD be returned as current. This
    is the exact assertion the PR's mutation-proof transcript breaks (by
    commenting out the `age_hours > stale_hours` branch in digest_utils.py) and
    restores; kept here as a permanent inline companion so the contract stays
    pinned even between manual mutation runs."""
    item = {"streak_days": 3, "updated_at": "2026-03-28T18:30:04+00:00"}
    now = datetime(2026, 8, 8, 18, 0, 0, tzinfo=timezone.utc)
    age_hours = (now - datetime.fromisoformat(item["updated_at"])).total_seconds() / 3600.0
    assert age_hours > STALE_HOURS, "fixture must actually be stale, or this test is vacuous"

    table = _FakeTable(item=item)
    assert get_food_delivery_streak_state(table, "matthew", now=now) is None, (
        "a stale food_delivery STREAK#current record must be withheld — if this fails, "
        "the freshness gate in common.digest_utils.get_food_delivery_streak_state was removed "
        "or its comparison direction was flipped"
    )


# ---------------------------------------------------------------------------
# Guard 2 — structural, guard-the-SET
# ---------------------------------------------------------------------------


def _parse(path: Path) -> ast.AST | None:
    try:
        return ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return None


def _key_dict_sk_constant(call: ast.Call):
    """Return the literal `sk` value of a `get_item(Key={...})` call, or None."""
    for kw in call.keywords:
        if kw.arg == "Key" and isinstance(kw.value, ast.Dict):
            for k, v in zip(kw.value.keys, kw.value.values):
                if isinstance(k, ast.Constant) and k.value == "sk" and isinstance(v, ast.Constant):
                    return v.value
    return None


def _iter_streak_current_get_item_sites(include_canonical: bool = False):
    """Every static `<x>.get_item(Key={..., "sk": "STREAK#current", ...})` call
    site under lambdas/, derived by AST walk. NOT a hardcoded module list —
    a future fourth consumer that reads the partition directly is found the
    same way the three known ones were."""
    sites = []
    for path in sorted(LAMBDAS.rglob("*.py")):
        if path == CANONICAL_MODULE and not include_canonical:
            continue
        tree = _parse(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not (isinstance(func, ast.Attribute) and func.attr == "get_item"):
                continue
            if _key_dict_sk_constant(node) == "STREAK#current":
                sites.append((path, node.lineno))
    return sites


def test_the_derivation_is_non_vacuous():
    """The AST probe must find the ONE real call site (inside the canonical
    module itself) — otherwise the guard below would pass by finding nothing
    everywhere, which is not a guard at all."""
    sites = _iter_streak_current_get_item_sites(include_canonical=True)
    found_modules = {p.name for p, _l in sites}
    assert found_modules == {"digest_utils.py"}, (
        f"expected the derivation to find exactly the one canonical STREAK#current "
        f"get_item call site, got {found_modules} — either the AST probe broke, or a "
        "reader was added/removed and needs following up"
    )


def test_no_consumer_reads_streak_current_directly():
    """Guard the SET (#2235): every OTHER call site in lambdas/ must go through
    common.digest_utils.get_food_delivery_streak_state rather than reading
    STREAK#current directly. A fourth consumer added later without using the
    shared function reds this test automatically — no allowlist to update."""
    sites = _iter_streak_current_get_item_sites(include_canonical=False)
    assert not sites, (
        "the following files read USER#...#SOURCE#food_delivery / STREAK#current directly "
        f"via table.get_item instead of common.digest_utils.get_food_delivery_streak_state: "
        f"{[f'{p.relative_to(ROOT)}:{ln}' for p, ln in sites]} — route through the shared "
        "reader so the #2235 freshness gate can't be bypassed a second time"
    )


def test_the_three_known_consumers_no_longer_carry_the_raw_literal():
    """Companion sanity check naming today's three known consumers explicitly
    (NOT the enforcement mechanism — that's the derived guard above): confirms
    the fix actually touched all three call sites the issue named, rather than
    two of three."""
    consumers = [
        LAMBDAS / "emails" / "daily_brief_lambda.py",
        LAMBDAS / "emails" / "weekly_digest_lambda.py",
        LAMBDAS / "compute" / "character_sheet_lambda.py",
    ]
    for path in consumers:
        text = path.read_text(encoding="utf-8")
        assert "get_food_delivery_streak_state" in text, f"{path} does not call the shared #2235 reader"
        assert 'sk": "STREAK#current"' not in text, f"{path} still reads STREAK#current directly"
