#!/usr/bin/env python3
"""tests/test_coherence_stale_expert_5442.py — #5442: the `coherence-overall` ALARM of 2026-10-26.

The 18:45Z sentinel run went ALARM on two `facts_agreement` offenders. The read-only
investigation (DynamoDB `ai_analysis`, the analyzer's October logs, the `COACH#mind_coach`
OUTPUT# rows) found four code causes, each pinned here against the real shapes:

  1. `coach:mind_coach: HRV cited in bpm` was a FALSE positive. The daily-brief text is
     "…, NN.N ms HRV, NN bpm resting heart rate" (correct), and the sentinel's regex read
     "HRV, NN bpm". The output validator's Check 13 had the same class in a second regex.
     There is now ONE predicate (`ai_output_validator.hrv_cited_in_bpm`).
  2. The sleep read was HELD on every successful run from 2026-10-12 to 2026-10-18 by
     `night_scope.unlabeled_night_figure`. That check also holds a correctly
     window-labelled average ("averaged … over the last 30 nights"), the form
     `reader_checks._WINDOW_RE` sanctions (owner ruling 8, #4343/#4547), so the sleep
     expert, whose data pack is window averages, had no compliant way to cite its numbers.
  3. `held_record_ttl.renew_held` (#4703) renewed with no bound on the record's age. The
     2026-10-05 `EXPERT#sleep` served for three weeks. A renewal now declines past
     `MAX_RENEWABLE_AGE_DAYS`.
  4. An outage-tripped run (#5412) renewed every `EXPERT#<domain>` but not the board
     records (`EXPERT#integrator` & co.), which it skips or breaks the same way.

Offline: DynamoDB is a dict, the model seam is never reached; no AWS, no Bedrock. The record
shapes are the analyzer's own `put_item` keys; every health value is a placeholder.
"""

import json
import logging
import os
import re
import sys
from datetime import datetime, timedelta, timezone

import pytest

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (os.path.join(_REPO, "lambdas"), os.path.join(_REPO, "lambdas", "intelligence")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import ai_expert_analyzer_lambda as az  # noqa: E402
from ai import (
    ai_output_validator as v,  # noqa: E402
    night_scope as ns,  # noqa: E402
)
from coach import reader_checks as rc  # noqa: E402
from experiment import coherence_invariants as ci  # noqa: E402
from intelligence import (
    held_record_ttl as held,  # noqa: E402
    vendor_outage_breaker as vob,  # noqa: E402
)

# ── 1. the HRV-in-bpm false positive ─────────────────────────────────────────
# The 2026-10-26 `daily_brief_mind` sentence, structure kept, every value a placeholder.
MIND_SPECIMEN = (
    "Over the last 20 logged days, protein has been averaging 150.0 grams a day, and the wearables "
    "from the night of Saturday, October 25th show 70% recovery, 50.0 ms HRV, 60 bpm resting heart "
    "rate — a body that looks, by the numbers, like it's doing okay."
)
SENTINEL_FACTS = {"recovery_pct": 70, "hrv_ms": 50.0, "rhr_bpm": 60, "latest_weight": 300.0}
_LONG = " and the recovery trend held steady through the week with no concerning signals at all."


def _validator_warns(text):
    r = v.validate_ai_output(text + _LONG, v.AIOutputType.CHRONICLE, min_length=10)
    return [w for w in r.warnings if "HRV" in w and "bpm" in w]


def _sentinel_unit_offenders(text):
    f = ci.check_facts_agreement([text], SENTINEL_FACTS, surfaces=["coach:mind_coach"])
    return [o for o in f.offenders if "bpm" in o]


class TestHrvInBpmIsOnePredicate:
    def test_the_live_mind_coach_shape_is_not_an_hrv_unit_error(self):
        assert not v.hrv_cited_in_bpm(MIND_SPECIMEN)
        assert _sentinel_unit_offenders(MIND_SPECIMEN) == []
        assert _validator_warns(MIND_SPECIMEN) == []

    @pytest.mark.parametrize(
        "text",
        [
            "HRV climbed to 42 bpm overnight, a strong sign.",
            "HRV improved to 44.7 bpm this week",
            "Your HRV of 53 bpm is up.",
        ],
    )
    def test_a_real_hrv_in_bpm_still_fires_in_both_surfaces(self, text):
        assert v.hrv_cited_in_bpm(text)
        assert _sentinel_unit_offenders(text), "the sentinel went blind to a real unit error"
        assert _validator_warns(text), "the validator went blind to a real unit error"

    @pytest.mark.parametrize(
        "text",
        [
            "HRV is 25 ms and your resting heart rate sits at 58 bpm.",
            "HRV 25 ms and RHR 64 bpm.",  # the old validator regex reached past the 25 ms to 64 bpm
            "HRV, 52 bpm resting heart rate, 70% recovery.",
        ],
    )
    def test_two_metrics_in_one_sentence_never_fire(self, text):
        assert not v.hrv_cited_in_bpm(text)

    def test_the_sentinel_has_no_second_hrv_bpm_regex(self):
        """Guard the SET: the sentinel calls the validator's predicate, it does not restate it."""
        assert ci.hrv_cited_in_bpm is v.hrv_cited_in_bpm
        src = open(ci.__file__, encoding="utf-8").read()
        restated = [ln for ln in src.splitlines() if re.search(r"hrv\[\^", ln, re.IGNORECASE) and "bpm" in ln]
        assert restated == [], f"a local HRV-bpm regex came back in coherence_invariants: {restated}"

    def test_mutation_control_without_the_value_order_guards_the_specimen_fires(self, monkeypatch):
        never = re.compile(r"(?!x)x")
        monkeypatch.setattr(v, "_HRV_OWN_MS_BEFORE_RE", never)
        monkeypatch.setattr(v, "_BPM_BELONGS_TO_NEXT_RE", never)
        assert v.hrv_cited_in_bpm(MIND_SPECIMEN), "the specimen test cannot detect the regression it guards"
        assert _sentinel_unit_offenders(MIND_SPECIMEN)


# ── 2. the night-scope gate vs a window-labelled average ─────────────────────
WINDOWED = [
    "Your HRV averaged 50.0 ms over the last 30 nights, a genuine improvement from where we started.",
    "You averaged 8.0 hours of sleep over the last 14 nights.",
    "Resting heart rate averaged 60 bpm this week.",
]
STILL_UNLABELED = [
    "HRV is 50.0 ms.",
    # the 2026-10-12 held sentence's shape: "across the month" is not a window in the owner's vocabulary
    "You're at 50.0 ms average HRV across the month, which is a genuine improvement.",
    # the 2026-10-18 held sentence's shape: "per night" names no window
    "You maintained 8.0 hours of sleep per night.",
    # a window in ANOTHER clause does not label a single reading
    "Sleep has been steady over the last 30 nights, and HRV was 41 ms.",
]


def _unlabeled(text):
    return [f for f in ns.night_scoped_vitals_findings(text, nightly_vitals={}) if f["type"] == "unlabeled_night_figure"]


class TestAWindowedAverageIsNotAnUnlabeledNight:
    @pytest.mark.parametrize("text", WINDOWED)
    def test_a_window_labelled_average_passes_the_night_gate(self, text):
        assert _unlabeled(text) == []
        assert rc.unlabeled_window_figure(text) == [], "precondition: the reader rule accepts this window"

    @pytest.mark.parametrize("text", STILL_UNLABELED)
    def test_a_figure_with_neither_night_nor_window_still_holds(self, text):
        assert _unlabeled(text), f"the night gate went blind: {text!r}"

    def test_the_whole_grounding_chokepoint_agrees(self):
        """The analyzer's `_gate_prose` composes `grounding_findings`; the windowed average must
        clear THAT path, not only the module function."""
        from ai import grounded_generation as gg

        found = gg.grounding_findings(
            WINDOWED[0],
            facts={"hrv_ms": 50.0, "night_of": "2026-10-25", "as_of": "2026-10-26"},
            allowed={50.0, 30.0},
            nightly_vitals=ns.nightly_vitals_from_facts({"hrv_ms": 50.0, "night_of": "2026-10-25"}),
        )
        assert [f for f in found if f.get("type") in ns.FINDING_TYPES] == []

    def test_the_correction_and_the_prompt_offer_the_window_form(self):
        line = ns.correction_line(_unlabeled(STILL_UNLABELED[0])[0])
        assert "window" in line and "average" in line
        prompt = ns.night_label_line({"night_of": "2026-10-25", "as_of": "2026-10-26", "hrv_ms": 50.0})
        assert "AVERAGE" in prompt and "window" in prompt
        # the example carries no digits: allowed_numbers() reads the prompt, so a literal would
        # silently become a number the fabricated-number gate accepts
        tail = prompt.split("AVERAGE", 1)[1]
        assert not re.search(r"\d", tail)

    def test_mutation_control_without_the_window_rule_the_average_holds(self, monkeypatch):
        monkeypatch.setattr(rc, "windowed_average_at", lambda sentence, pos: False)
        assert _unlabeled(WINDOWED[0]), "the windowed-average test cannot detect the regression it guards"


# ── 3. a hold that never releases ────────────────────────────────────────────
T0 = datetime(2026, 10, 5, 14, 1, 7, 24000, tzinfo=timezone.utc)  # a Monday write, microseconds as isoformat stamps them


class _CondFailed(Exception):
    response = {"Error": {"Code": "ConditionalCheckFailedException"}}


class TtlTable:
    """Dict-backed DDB double that honours `ttl` (an item at/past its ttl is gone) and evaluates
    each clause of `renew_held`'s ConditionExpression ONLY when the clause is present — so a
    mutation that drops a clause changes the double's verdict exactly as it would DynamoDB's."""

    def __init__(self, clock):
        self.clock = clock
        self.items = {}

    def _live(self, key):
        item = self.items.get(key)
        if item is not None and "ttl" in item and int(item["ttl"]) <= int(self.clock.timestamp()):
            del self.items[key]
            return None
        return item

    def update_item(
        self, Key=None, UpdateExpression="", ConditionExpression="", ExpressionAttributeNames=None, ExpressionAttributeValues=None
    ):
        cond, vals = ConditionExpression, ExpressionAttributeValues
        row = self._live((Key["pk"], Key["sk"]))
        ok = row is not None
        if ok and "attribute_not_exists(tombstone)" in cond:
            ok = not row.get("tombstone")
        if ok and "#ttl < :ttl" in cond:
            ok = "ttl" not in row or int(row["ttl"]) < vals[":ttl"]
        if ok and "attribute_exists(generated_at)" in cond:
            ok = "generated_at" in row
        if ok and "generated_at >= :floor" in cond:
            ok = str(row["generated_at"]) >= vals[":floor"]
        if not ok:
            raise _CondFailed()
        row["ttl"] = vals[":ttl"]
        row["held_renewed_at"] = vals[":at"]

    def get_item(self, Key=None, **_):
        item = self._live((Key["pk"], Key["sk"]))
        return {"Item": dict(item)} if item else {}


def _domain_record(sk="EXPERT#sleep", generated=T0, **extra):
    """The keys `generate_and_cache` writes for EXPERT#<domain> (values are placeholders)."""
    row = {
        "pk": az.CACHE_PK,
        "sk": sk,
        "expert_key": sk.split("#", 1)[1],
        "analysis": "A grounded weekly read.",
        "key_recommendation": "One move.",
        "generated_at": generated.isoformat(),
        "data_through": generated.date().isoformat(),
        "data_snapshot": "{}",
        "week_number": 5,
        "days_in_experiment": 30,
        "ttl": held.ttl_from(generated, held.WEEKLY_TTL_DAYS),
    }
    row.update(extra)
    return row


def _hold_at(table, days, sk="EXPERT#sleep"):
    when = T0 + timedelta(days=days)
    table.clock = when
    held.renew_held(table, az.CACHE_PK, sk, held.WEEKLY_TTL_DAYS, now=when)
    return when


def _served(table, days, sk="EXPERT#sleep"):
    table.clock = T0 + timedelta(days=days)
    return bool(table.get_item(Key={"pk": az.CACHE_PK, "sk": sk}).get("Item"))


class TestAHoldReleases:
    def test_two_missed_mondays_keep_serving_the_third_lets_it_lapse(self):
        t = TtlTable(T0)
        t.items[(az.CACHE_PK, "EXPERT#sleep")] = _domain_record()
        _hold_at(t, 7)
        _hold_at(t, 14)
        assert _served(t, 21), "a record held twice must still serve at the third Monday"
        _hold_at(t, 21)  # age 21 > the cap: declined
        assert _served(t, 21.9)
        assert not _served(t, 22.1), "a record held three Mondays running is still serving — the hold never releases"

    def test_the_cap_covers_exactly_two_weekly_renewals(self):
        assert 14 < held.MAX_RENEWABLE_AGE_DAYS < 21

    def test_a_record_with_no_generated_at_is_never_renewed(self):
        t = TtlTable(T0)
        row = _domain_record()
        del row["generated_at"]
        t.items[(az.CACHE_PK, "EXPERT#sleep")] = row
        _hold_at(t, 7)
        assert t.items[(az.CACHE_PK, "EXPERT#sleep")]["ttl"] == held.ttl_from(T0, held.WEEKLY_TTL_DAYS)

    def test_the_floor_orders_against_the_stamp_the_analyzer_writes(self):
        """DynamoDB compares the two as STRINGS; both must be ISO-8601 UTC with the same offset form."""
        now = T0 + timedelta(days=20)
        floor = held.renewable_floor(now)
        assert floor.endswith("+00:00") and T0.isoformat().endswith("+00:00")
        assert T0.isoformat() < floor  # 20 days old: below the floor
        assert (T0 + timedelta(days=6)).isoformat() >= floor  # 14 days old: renewable

    def test_mutation_control_without_the_age_clause_the_hold_never_releases(self, monkeypatch):
        monkeypatch.setattr(held, "RENEW_CONDITION", held.RENEW_CONDITION.replace(" AND generated_at >= :floor", ""))
        t = TtlTable(T0)
        t.items[(az.CACHE_PK, "EXPERT#sleep")] = _domain_record()
        for d in (7, 14, 21):
            _hold_at(t, d)
        assert _served(t, 22.1), "the cap test cannot detect the regression it guards"

    def test_the_renewal_lines_reach_the_lambda_log(self):
        """The 10-12/10-18 renewals left no `[held-ttl]` line: the module logger inherited the
        Lambda root's WARNING. It now sets INFO like the analyzer's own logger."""
        root = logging.getLogger()
        saved = root.level
        try:
            root.setLevel(logging.WARNING)
            assert held.logger.isEnabledFor(logging.INFO)
        finally:
            root.setLevel(saved)


# ── 4. an outage renews the board records it skips ───────────────────────────
@pytest.fixture
def handler(monkeypatch):
    renewed = []
    monkeypatch.setattr(az, "_build_shared_system_prompt", lambda: "SHARED")
    monkeypatch.setattr(az, "_absent_coaches", lambda: {})
    monkeypatch.setattr(az._held, "renew_held", lambda table, pk, sk, days: renewed.append(sk))
    return renewed


BOARD = [sk for sk, _ in held.BOARD_RECORDS]


def _trip():
    vob._state.tripped = True
    raise vob.VendorOutageSkipped("tripped (test)")


class TestAnOutageRenewsTheBoardRecords:
    def test_an_outage_before_the_board_stages_renews_every_board_record(self, handler, monkeypatch):
        monkeypatch.setattr(az, "generate_and_cache", lambda key, shared_system=None: _trip())
        for stage in ("generate_synthesis", "generate_experiment_arc", "generate_month_rollup"):
            monkeypatch.setattr(az, stage, lambda *a, _s=stage: pytest.fail(f"{_s} ran into a tripped outage"))
        out = json.loads(az.lambda_handler({}, None)["body"])
        assert all(out[k]["status"] == "error" for k in az.EXPERTS)
        assert set(BOARD) <= set(handler), f"board records left to expire after an outage: {set(BOARD) - set(handler)}"

    def test_an_outage_during_the_board_stages_renews_only_what_was_not_written(self, handler, monkeypatch):
        monkeypatch.setattr(az, "generate_and_cache", lambda key, shared_system=None: f"{key} read")
        monkeypatch.setattr(az, "generate_synthesis", lambda outs: {"weekly_priority": "p"})  # written this run
        monkeypatch.setattr(az, "generate_experiment_arc", lambda: _trip())
        monkeypatch.setattr(az, "generate_month_rollup", lambda: None)
        out = json.loads(az.lambda_handler({}, None)["body"])
        assert out["integrator"]["status"] == "ok"
        assert "EXPERT#integrator" not in handler, "a record written this run was stamped as held"
        assert {"EXPERT#experiment_arc", "EXPERT#integrator_month"} <= set(handler)

    def test_a_healthy_run_renews_nothing(self, handler, monkeypatch):
        monkeypatch.setattr(az, "generate_and_cache", lambda key, shared_system=None: f"{key} read")
        monkeypatch.setattr(az, "generate_synthesis", lambda outs: {"weekly_priority": "p"})
        monkeypatch.setattr(az, "generate_experiment_arc", lambda: {"week_count": 3})
        monkeypatch.setattr(az, "generate_month_rollup", lambda: {"week_count": 4})
        az.lambda_handler({}, None)
        assert handler == []

    def test_mutation_control_the_handler_reads_the_breaker(self, handler, monkeypatch):
        """With the breaker reporting healthy, the same all-error run renews no board record — so
        the first test above is measuring the outage branch, not some other renewal."""
        monkeypatch.setattr(az, "generate_and_cache", lambda key, shared_system=None: _trip())
        monkeypatch.setattr(az._outage, "tripped", lambda: False)
        az.lambda_handler({}, None)
        assert not set(BOARD) & set(handler)
