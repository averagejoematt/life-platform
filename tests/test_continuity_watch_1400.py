#!/usr/bin/env python3
"""tests/test_continuity_watch_1400.py — the dead-man's switch, and the ways it
must refuse to fire (#1400).

A switch that trips on a broken query is worse than no switch: it would tell
people Matthew had stopped because a DynamoDB call timed out. So most of this
file is about the *negative* space — the conditions under which the clock is
required to say ``unknown`` and do nothing.

The watched set is derived from the source registry's ``behavioral`` facet
rather than hand-listed, so the tests below prove the derivation (by flipping
the facet on a copied registry and watching the set move), not a copy of it.
"""

from __future__ import annotations

import os
import sys
from datetime import date

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if os.path.join(ROOT, "lambdas") not in sys.path:
    sys.path.insert(0, os.path.join(ROOT, "lambdas"))

from ingestion.source_registry import SOURCE_REGISTRY  # noqa: E402
from operational import continuity_watch as watch  # noqa: E402

TODAY = date(2026, 8, 10)


# ── the watched set is derived, and the registry is covered ─────────────────
def test_every_registry_source_has_a_liveness_role():
    """A source cannot join the platform without someone deciding whether its
    silence means anything. Unclassified is not a state this file allows."""
    for source in sorted(SOURCE_REGISTRY):
        role = watch.liveness_role(source)
        assert role in ("presence", "value_gated", "ambient"), f"{source}: {role}"


def test_every_ambient_source_declares_why_it_cannot_be_a_presence_signal():
    ambient = {s for s in SOURCE_REGISTRY if watch.liveness_role(s) == "ambient"}
    missing = sorted(ambient - set(watch.AMBIENT_REASONS))
    assert not missing, "these sources are excluded from the clock with no stated reason:\n" + "\n".join(f"  {s}" for s in missing)
    stale = sorted(set(watch.AMBIENT_REASONS) - ambient - set(watch.VALUE_GATED))
    assert not stale, f"reasons recorded for sources that are not ambient: {stale}"
    for source, reason in watch.AMBIENT_REASONS.items():
        assert len(reason) >= 25, f"{source}: reason too thin to review — {reason!r}"


def test_unknown_source_raises_rather_than_defaulting():
    with pytest.raises(KeyError):
        watch.liveness_role("a_source_that_does_not_exist")


def test_watched_set_is_derived_from_the_behavioral_facet(monkeypatch):
    """Mutation proof: the set must move when the registry moves. A hand-copied
    list would pass every other test in this file and silently stop watching a
    new source."""
    before = set(watch.presence_sources())
    assert "hevy" in before, "hevy logs a workout — it is a presence signal"
    assert "weather" not in before, "an external forecast pull is not a presence signal"

    patched = {k: dict(v) for k, v in SOURCE_REGISTRY.items()}
    patched["hevy"]["behavioral"] = False
    patched["weather"]["behavioral"] = True
    monkeypatch.setattr(watch, "SOURCE_REGISTRY", patched)
    after = set(watch.presence_sources())
    assert "hevy" not in after and "weather" in after


def test_paused_sources_are_not_watched(monkeypatch):
    """A source with no live schedule is silent for reasons that have nothing
    to do with a person; counting it would let a vendor lockout drag the clock
    toward a trigger."""
    patched = {k: dict(v) for k, v in SOURCE_REGISTRY.items()}
    patched["hevy"]["paused"] = True
    monkeypatch.setattr(watch, "SOURCE_REGISTRY", patched)
    assert "hevy" not in watch.presence_sources()


# ── the ladder ──────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "days,expected",
    [
        (0, watch.STATE_ACTIVE),
        (29, watch.STATE_ACTIVE),
        (30, watch.STATE_NOTICE),
        (59, watch.STATE_NOTICE),
        (60, watch.STATE_WARNING),
        (89, watch.STATE_WARNING),
        (90, watch.STATE_TRIGGERED),
        (365, watch.STATE_TRIGGERED),
        (None, watch.STATE_UNKNOWN),
    ],
)
def test_state_ladder_boundaries(days, expected):
    assert watch.state_for(days) == expected


# ── evaluate: the negative space ────────────────────────────────────────────
def test_a_total_read_failure_is_unknown_never_triggered():
    """The single most important assertion in this file. Every source
    unreadable must produce ``unknown``, not ninety days of silence."""
    signals = {s: ("error", None) for s in watch.watched_sources()}
    verdict = watch.evaluate(signals, TODAY)
    assert verdict["state"] == watch.STATE_UNKNOWN
    assert verdict["days_silent"] is None
    assert verdict["sources_readable"] == 0
    assert verdict["sources_unreadable"] == len(signals)


def test_a_partial_read_failure_still_measures_from_what_was_read():
    signals = {"hevy": ("error", None), "withings": ("ok", "2026-08-09"), "strava": ("empty", None)}
    verdict = watch.evaluate(signals, TODAY)
    assert verdict["state"] == watch.STATE_ACTIVE
    assert verdict["days_silent"] == 1
    assert verdict["sources_unreadable"] == 1


def test_the_most_recent_signal_wins():
    """Silence is the gap since the LAST signal from ANY watched source — one
    active source is enough to say the platform is not silent."""
    signals = {
        "hevy": ("ok", "2026-01-01"),
        "withings": ("ok", "2026-08-08"),
        "macrofactor": ("ok", "2026-03-15"),
    }
    verdict = watch.evaluate(signals, TODAY)
    assert verdict["last_signal_date"] == "2026-08-08"
    assert verdict["days_silent"] == 2


def test_ninety_days_of_real_silence_does_trigger():
    """The positive control: the switch must actually be able to fire, or the
    negative tests above are guarding nothing."""
    signals = {s: ("ok", "2026-05-12") for s in ("hevy", "withings", "strava")}
    verdict = watch.evaluate(signals, TODAY)
    assert verdict["days_silent"] == 90
    assert verdict["state"] == watch.STATE_TRIGGERED


def test_a_future_dated_row_is_zero_not_negative():
    """Timezone edges and backfills produce tomorrow's date. That is not
    evidence of anything, but it is certainly not silence."""
    verdict = watch.evaluate({"hevy": ("ok", "2026-08-12")}, TODAY)
    assert verdict["days_silent"] == 0
    assert verdict["state"] == watch.STATE_ACTIVE


def test_every_source_empty_is_unknown_not_silent():
    """No rows anywhere cannot be distinguished from a table that was never
    written to. Unmeasurable, so it says so."""
    verdict = watch.evaluate({s: ("empty", None) for s in ("hevy", "withings")}, TODAY)
    assert verdict["state"] == watch.STATE_UNKNOWN


def test_published_verdict_carries_its_own_thresholds():
    """The reader should not have to find the source to know what 61 means."""
    verdict = watch.evaluate({"hevy": ("ok", "2026-08-09")}, TODAY)
    assert verdict["thresholds_days"] == {"notice": 30, "warning": 60, "triggered": 90}
    assert verdict["as_of"] == "2026-08-10"


# ── reading DynamoDB ────────────────────────────────────────────────────────
class _FakeTable:
    def __init__(self, rows, boom=()):
        self.rows = rows  # {source: [item, ...]} newest first
        self.boom = set(boom)
        self.queries = []

    def query(self, **kwargs):
        pk = kwargs["ExpressionAttributeValues"][":pk"]
        source = pk.rsplit("#", 1)[-1]
        self.queries.append((source, kwargs.get("Limit")))
        if source in self.boom:
            raise RuntimeError("ddb hiccup")
        items = self.rows.get(source, [])
        return {"Items": items[: kwargs.get("Limit", len(items))]}


def test_partition_read_returns_the_newest_date():
    table = _FakeTable({"hevy": [{"sk": "DATE#2026-08-09"}, {"sk": "DATE#2026-08-01"}]})
    assert watch._last_partition_day(table, "matthew", "hevy") == ("ok", "2026-08-09")


def test_partition_read_reports_an_error_distinctly_from_emptiness():
    table = _FakeTable({}, boom={"hevy"})
    assert watch._last_partition_day(table, "matthew", "hevy") == ("error", None)
    assert watch._last_partition_day(table, "matthew", "strava") == ("empty", None)


def test_a_malformed_sort_key_is_not_a_date():
    table = _FakeTable({"hevy": [{"sk": "DATE#not-a-date"}]})
    assert watch._last_partition_day(table, "matthew", "hevy") == ("empty", None)


def test_value_gated_source_ignores_rows_with_no_movement():
    """Apple Health's partition stays warm from automations that need no
    person. Reading the partition would make a phone in a drawer look alive;
    reading the steps value does not."""
    table = _FakeTable(
        {
            "apple_health": [
                {"sk": "DATE#2026-08-09", "steps": 0},
                {"sk": "DATE#2026-08-08", "steps": None},
                {"sk": "DATE#2026-08-05", "steps": 8214},
            ]
        }
    )
    assert watch._last_value_day(table, "matthew", "apple_health", "steps", 14) == ("ok", "2026-08-05")


def test_value_gated_source_with_no_movement_at_all_is_empty_not_ok():
    table = _FakeTable({"apple_health": [{"sk": "DATE#2026-08-09", "steps": 0}]})
    assert watch._last_value_day(table, "matthew", "apple_health", "steps", 14) == ("empty", None)


def test_read_signals_covers_the_whole_watched_set():
    table = _FakeTable({})
    signals = watch.read_signals(table, "matthew")
    assert set(signals) == set(watch.watched_sources())
    assert {s for s, _limit in table.queries} == set(watch.watched_sources())


# ── transitions ─────────────────────────────────────────────────────────────
def _verdict(days):
    last = date.fromordinal(TODAY.toordinal() - days).isoformat()
    return watch.evaluate({"hevy": ("ok", last)}, TODAY)


def test_a_transition_notifies_exactly_once():
    """The clock ticks nightly. A state that notified every night would train
    its recipients to ignore it."""
    first = watch.apply_transition({"state": watch.STATE_ACTIVE}, _verdict(30), "2026-08-10T00:00:00Z")
    assert first["state"] == watch.STATE_NOTICE and first["changed"] and first["notify"]

    second = watch.apply_transition(first, _verdict(31), "2026-08-11T00:00:00Z")
    assert second["state"] == watch.STATE_NOTICE and not second["changed"] and not second["notify"]


def test_de_escalation_does_not_notify():
    prev = watch.apply_transition({"state": watch.STATE_ACTIVE}, _verdict(60), "2026-08-10T00:00:00Z")
    assert prev["state"] == watch.STATE_WARNING and prev["notify"]
    back = watch.apply_transition(prev, _verdict(0), "2026-08-11T00:00:00Z")
    assert back["state"] == watch.STATE_ACTIVE
    assert back["changed"] and not back["notify"]


def test_triggering_freezes_and_stamps_the_moment():
    doc = watch.apply_transition({"state": watch.STATE_WARNING}, _verdict(90), "2026-08-10T00:00:00Z")
    assert doc["state"] == watch.STATE_TRIGGERED
    assert doc["frozen"] is True
    assert doc["triggered_at"] == "2026-08-10T00:00:00Z"
    assert doc["notify"] is True

    later = watch.apply_transition(doc, _verdict(91), "2026-08-11T00:00:00Z")
    assert later["frozen"] is True
    assert later["triggered_at"] == "2026-08-10T00:00:00Z", "the trigger moment must not be restamped nightly"
    assert later["notify"] is False


def test_the_switch_is_reversible():
    """A measurement, not a verdict. One new reading thaws the archive."""
    triggered = watch.apply_transition({"state": watch.STATE_WARNING}, _verdict(90), "2026-08-10T00:00:00Z")
    thawed = watch.apply_transition(triggered, _verdict(1), "2026-09-01T00:00:00Z")
    assert thawed["state"] == watch.STATE_ACTIVE
    assert thawed["frozen"] is False
    assert thawed["triggered_at"] is None


def test_unknown_neither_escalates_nor_thaws():
    """An outage in the reader must not be able to announce — or retract —
    anything about a person."""
    triggered = watch.apply_transition({"state": watch.STATE_WARNING}, _verdict(90), "2026-08-10T00:00:00Z")
    blind = watch.apply_transition(triggered, {"state": watch.STATE_UNKNOWN, "days_silent": None}, "2026-08-11T00:00:00Z")
    assert blind["state"] == watch.STATE_UNKNOWN
    assert blind["notify"] is False
    assert blind["frozen"] is True, "a failed measurement must carry the prior freeze forward, not thaw it"
    assert blind["triggered_at"] == "2026-08-10T00:00:00Z"
    assert blind["measurement_failed"] is True


def test_unknown_from_an_active_state_stays_unfrozen():
    healthy = watch.apply_transition(None, _verdict(1), "2026-08-10T00:00:00Z")
    blind = watch.apply_transition(healthy, {"state": watch.STATE_UNKNOWN, "days_silent": None}, "2026-08-11T00:00:00Z")
    assert blind["frozen"] is False and blind["notify"] is False


def test_first_ever_run_has_no_previous_state():
    doc = watch.apply_transition(None, _verdict(2), "2026-08-10T00:00:00Z")
    assert doc["previous_state"] == watch.STATE_ACTIVE
    assert doc["changed"] is False and doc["notify"] is False


# ── the notification itself ─────────────────────────────────────────────────
def test_notification_says_what_the_number_does_not_mean():
    """The recipient may be reading this in the worst week of their life. The
    message must not let a broken phone read as a death notice."""
    doc = watch.apply_transition({"state": watch.STATE_ACTIVE}, _verdict(30), "2026-08-10T00:00:00Z")
    body = watch.notification_body(doc, "https://example.test/archive/latest.tar.gz", "https://example.test/archive/manifest.json")
    assert "measures data, not a person" in body
    assert "resets the clock" in body
    assert "30 days" in watch.notification_subject(doc)
    assert "https://example.test/archive/latest.tar.gz" in body


def test_a_frozen_notification_says_the_archive_is_sealed():
    doc = watch.apply_transition({"state": watch.STATE_WARNING}, _verdict(90), "2026-08-10T00:00:00Z")
    body = watch.notification_body(doc, "https://example.test/a", "https://example.test/m")
    assert "FROZEN" in body
    assert "TRIGGERED" in watch.notification_subject(doc)
