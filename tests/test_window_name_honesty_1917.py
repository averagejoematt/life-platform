"""tests/test_window_name_honesty_1917.py — #1917 window-name honesty, guarded as a SET.

THE DEFECT. `/api/vitals` published `weight_delta_30d: -4.1` and `hrv_30d_avg: 55.2`
on Day 6 of cycle 11. The arithmetic was honest — #1084 clamps live trailing windows
at genesis (ADR-077 "clamped, not hidden") so neither number reached into a prior
cycle. What was NOT honest was the NAME: a genesis-clamped window carried 6 days of
data under a key that claims 30. qa-smoke's reader_truth check flagged it, and since
qa-smoke is ci-cd's smoke oracle, it auto-rolled-back 100 healthy Lambdas.

WHY A DERIVED GUARD. The two offenders were found by an AI prose check, not by an
invariant — a third would not have been caught. `tests/test_honest_read_guards_1084.py`
already asserted these exact fields' min-n semantics and still missed the naming bug,
because it was written against the fields someone REMEMBERED. So this file does not
enumerate: it AST-scans `lambdas/web/` for every published `_Nd`-suffixed JSON key and
requires each to be REGISTERED below. A new window-named field fails this test until
its author states what window it really covers. See the memory note "guard the SET,
not the instance".

THE RUBRIC. Not every short window is a lie, and conflating the two would make the
guard noise. The distinction is extensive vs. intensive:

  * EXTENSIVE (counts, sums, totals) — "3 workouts in the last 30 days" is TRUE on
    Day 6. A count over a partly-elapsed window understates; it never overstates.
    These need only be declared.

  * INTENSIVE (averages, means, deltas, rates, percentages) — "30-day average = 55.2"
    computed from 6 days is a DIFFERENT CLAIM than its name makes. These must either
    gate the `_Nd`-named key on a genuinely full window, or carry an explicit,
    issue-linked `gap` recording that they do not yet.

`gap` is the honest escape hatch, and it is deliberately load-bearing: it keeps
un-fixed debt VISIBLE in a registry rather than invisible in the absence of a test.
"""

import ast
import json
import os
import pathlib
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

from web import site_api_vitals as vitals  # noqa: E402

_WEB = pathlib.Path(__file__).resolve().parent.parent / "lambdas" / "web"

# The canonical registry moved to lambdas/web/window_registry.py (#1922) so the
# runtime phase-plausibility checker and this set-guard share ONE source of truth.
# This file keeps the AST scan + the guards; the registry entries live there.
from web.window_registry import EXTENSIVE, INTENSIVE, REGISTRY, WINDOW_KEY as _WINDOW_KEY  # noqa: E402,F401


def _scan(root: pathlib.Path) -> dict[str, list[str]]:
    """Every string dict-key in `root`/*.py that names a day-window.

    Deliberately structural (ast) rather than textual: a regex over source would
    also match window names in comments, docstrings and local variables, none of
    which a reader ever sees. Only literal keys of dict displays are published.
    """
    found: dict[str, list[str]] = {}
    for path in sorted(root.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
            if not isinstance(node, ast.Dict):
                continue
            for key in node.keys:
                if isinstance(key, ast.Constant) and isinstance(key.value, str) and _WINDOW_KEY.match(key.value):
                    found.setdefault(key.value, []).append(f"{path.name}:{key.lineno}")
    return found


# ── the set guard ───────────────────────────────────────────────────────────


def test_every_published_window_field_is_registered():
    """A new `_Nd` field must state what window it really covers."""
    unregistered = {k: v for k, v in _scan(_WEB).items() if k not in REGISTRY}
    assert not unregistered, (
        "Unregistered window-named field(s) published by lambdas/web/.\n"
        "A key named for an N-day window is a claim about N days of data. Add each to\n"
        "REGISTRY in this file as EXTENSIVE (a count/sum — safe) or INTENSIVE (a\n"
        "mean/delta/rate — must gate on a full window, or carry an issue-linked gap):\n"
        + "\n".join(f"  {k}  ({', '.join(v)})" for k, v in sorted(unregistered.items()))
    )


def test_registry_has_no_dead_entries():
    """The registry decays into fiction if removed fields linger — keep it derived."""
    published = _scan(_WEB)
    dead = sorted(k for k in REGISTRY if k not in published)
    assert not dead, f"REGISTRY lists field(s) lambdas/web/ no longer publishes; delete them: {dead}"


def test_intensive_fields_are_gated_or_carry_a_declared_gap():
    """An average over a partly-elapsed window is a different claim than its name.

    Every INTENSIVE entry must either be gated (gap is None) or name the issue that
    tracks it. This is what keeps un-fixed debt visible instead of merely untested.
    """
    for key, (kind, gap) in sorted(REGISTRY.items()):
        if kind == INTENSIVE and gap is not None:
            assert gap.startswith("#"), f"{key}: an intensive field's gap must reference an issue, got {gap!r}"


def test_scanner_actually_fires_on_a_new_field(tmp_path):
    """Negative test: prove the scan catches an injected field.

    Without this, a scanner that silently matched nothing would pass every assertion
    above — the exact failure mode that let docs-ci report a green it never earned
    (#1908). Assert the mechanism, not just its current verdict.
    """
    (tmp_path / "site_api_injected.py").write_text('def h():\n    return {"fabricated_45d_avg": 1.0}\n')
    assert "fabricated_45d_avg" in _scan(tmp_path)
    assert "fabricated_45d_avg" not in REGISTRY, "the injected fixture name must not be registered"

    # ...and that it ignores a window name that is not a published key.
    (tmp_path / "site_api_comment.py").write_text('# hrv_99d_avg in a comment\nX = "hrv_99d_avg"\n')
    assert "hrv_99d_avg" not in _scan(tmp_path)


# ── the behavioural guard: /api/vitals on a short cycle ─────────────────────

# #1922: the vitals handler's day frame is PACIFIC (the site convention — its
# UTC anchor made the payload claim Day N+1 every PT evening). Fixture dates
# must live in the SAME frame the handler anchors on, or these tests become
# time bombs that fail only between 5pm and midnight PT (the golden-test
# wall-clock lesson).
#
# #2223: a live `datetime.now(...)` read here, ONCE at import time, is itself
# a second time bomb — CI run 31244919499 fired it verbatim: fixtures built as
# "Day 5" got asserted against a handler that had already ticked to "Day 6"
# because the suite's EXECUTION crossed Pacific midnight a few minutes after
# COLLECTION. Fixed instant + freeze the handler's own clock to match (see
# _freeze_vitals_clock below, the same pattern tests/test_home_og_day_frame_1955.py
# already uses on this exact module).
_PT = ZoneInfo("America/Los_Angeles")
_NOW = datetime(2026, 7, 20, 12, 0, tzinfo=_PT)  # arbitrary fixed PT noon


def _d(days_ago: int) -> str:
    return (_NOW - timedelta(days=days_ago)).strftime("%Y-%m-%d")


class _FrozenDateTime(datetime):
    """datetime whose now() is pinned to _NOW, tz-converted like the real
    clock. site_api_vitals.py takes `datetime` as a plain module import (its
    handlers read it back via the `_g` hand-off — see the module's own
    docstring); `strptime`/`timedelta` arithmetic/`.astimezone()` all keep
    working since this subclasses the real datetime rather than mocking it."""

    @classmethod
    def now(cls, tz=None):
        if tz is None:
            return _NOW.replace(tzinfo=None)
        return _NOW.astimezone(tz)


@pytest.fixture(autouse=True)
def _freeze_vitals_clock(monkeypatch):
    """Pin site_api_vitals's live clock to the SAME instant `_NOW`/`_d()`
    build fixtures from, so the handler's own `datetime.now(PT)` (read at call
    time inside site_api_body.vitals(), injected via the `_g` hand-off) can
    never disagree with what these fixtures call "today" (#2223)."""
    monkeypatch.setattr(vitals, "datetime", _FrozenDateTime)


def _whoop(date_str, hrv):
    return {"sk": f"DATE#{date_str}", "recovery_score": 66, "hrv": hrv, "resting_heart_rate": 52, "sleep_duration_hours": 7.2}


def _weigh(date_str, lbs):
    return {"sk": f"DATE#{date_str}", "weight_lbs": lbs}


@pytest.fixture
def short_cycle(monkeypatch):
    """Reproduce cycle 11 Day 6: genesis 5 days back, 3 weigh-ins, 5 HRV readings."""
    genesis = _d(5)
    data = {
        "whoop": [_whoop(_d(i), 50.0 + i) for i in range(5, 0, -1)],
        "withings": [_weigh(_d(5), 321.1), _weigh(_d(4), 316.3), _weigh(_d(0), 317.0)],
    }
    monkeypatch.setattr(vitals, "EXPERIMENT_START", genesis)

    def _fake_query_source(source, start, end, include_pilot=False):
        return [dict(r) for r in data.get(source, []) if start <= r["sk"].replace("DATE#", "") <= end]

    monkeypatch.setattr(vitals, "_query_source", _fake_query_source)
    monkeypatch.setattr(vitals, "_latest_item", lambda *_a, **_k: {})
    monkeypatch.setattr(vitals, "_latest_item_asof", lambda *_a, **_k: {})
    monkeypatch.setattr(
        vitals.vitals_resolver,
        "resolve_vitals",
        lambda *_a, **_k: {
            "recovery_pct": 96.0,
            "recovery_status": "green",
            "hrv_ms": 55.0,
            "rhr_bpm": 63.0,
            "recovery_as_of": _d(0),
            "sleep_hours": 7.4,
            "sleep_as_of": _d(0),
            "steps": None,
            "steps_source": None,
            "steps_as_of": None,
        },
    )
    return genesis


def test_window_named_keys_are_null_on_a_short_cycle(short_cycle):
    """The #1917 regression, verbatim: no `_30d` key may carry a value on Day 6.

    Reverting the gate in site_api_vitals.py fails exactly here.
    """
    v = json.loads(vitals.handle_vitals()["body"])["vitals"]
    assert v["weight_delta_30d"] is None, "a 5-day weight delta must not publish under a 30d name"
    assert v["hrv_30d_avg"] is None, "a 5-reading mean must not publish under a 30d name"
    assert v["hrv_30d_n"] is None, "n must vanish with the average it describes, or the pair contradicts itself"


def test_the_real_numbers_are_still_published(short_cycle):
    """ "Clamped, not hidden" (ADR-077): gating the NAME must not suppress the VALUE."""
    v = json.loads(vitals.handle_vitals()["body"])["vitals"]
    assert v["weight_delta_lbs"] == -4.1, "317.0 - 321.1, the real observed change"
    assert v["weight_delta_window_days"] == 5, "the span between the first and last weigh-in used"
    assert v["hrv_avg_ms"] is not None
    assert v["hrv_avg_n"] == 5
    assert v["hrv_avg_window_days"] == 5


def test_window_numbers_are_explained_in_words(short_cycle):
    """The bare integers must come with the sentence that disambiguates them.

    `weight_delta_window_days: 5` beside "Day 6" is ambiguous — span between two
    weigh-ins, or days of history? qa-smoke's reader_truth reproducibly read it as
    a contradiction, and a human has the same ambiguity with no way to resolve it.
    """
    v = json.loads(vitals.handle_vitals()["body"])["vitals"]
    d = v["window_disclosure"]
    assert "Day 6" in d, "the disclosure must state the day number it is reconciling against"
    assert "5 day(s) apart" in d, "it must explain weight_delta_window_days as a SPAN, not a history"
    assert "*_30d stay null" in d, "it must say why the window-named keys are absent"
    # and it must never claim more history than the cycle has
    assert "at most 6 day(s) of data can exist" in d


def test_a_full_window_restores_the_window_named_keys(monkeypatch):
    """Date-independent: the same code publishes `_30d` once 30 days really elapsed."""
    genesis = _d(400)
    data = {
        "whoop": [_whoop(_d(i), 50.0 + i) for i in range(29, 0, -1)],
        "withings": [_weigh(_d(30), 321.1), _weigh(_d(0), 317.0)],
    }
    monkeypatch.setattr(vitals, "EXPERIMENT_START", genesis)
    monkeypatch.setattr(
        vitals,
        "_query_source",
        lambda source, start, end, include_pilot=False: [
            dict(r) for r in data.get(source, []) if start <= r["sk"].replace("DATE#", "") <= end
        ],
    )
    monkeypatch.setattr(vitals, "_latest_item", lambda *_a, **_k: {})
    monkeypatch.setattr(vitals, "_latest_item_asof", lambda *_a, **_k: {})
    monkeypatch.setattr(
        vitals.vitals_resolver,
        "resolve_vitals",
        lambda *_a, **_k: {
            "recovery_pct": 96.0,
            "recovery_status": "green",
            "hrv_ms": 55.0,
            "rhr_bpm": 63.0,
            "recovery_as_of": _d(0),
            "sleep_hours": 7.4,
            "sleep_as_of": _d(0),
            "steps": None,
            "steps_source": None,
            "steps_as_of": None,
        },
    )
    v = json.loads(vitals.handle_vitals()["body"])["vitals"]
    assert v["hrv_30d_avg"] is not None, "a genuinely 30-day window must publish under its name"
    assert v["hrv_30d_n"] == 29
    assert v["weight_delta_30d"] == -4.1, "a 30-day span publishes under the 30d name"
    assert v["weight_delta_window_days"] == 30
