"""tests/test_stance_behavioral_gate_2195.py — #2195: arming the #1699 gate on the stance writer.

WHAT #2056 LEFT, AND WHY IT WAS RIGHT TO LEAVE IT
-------------------------------------------------
#2056's census armed the ungrounded-behavioral class on 5 of 15 grounding surfaces and
replaced a 12-surface blanket exemption with per-surface written reasons. Exactly ONE
surface came out of that measurement as "genuinely armable, but not for free":
``coach_history_summarizer::_apply_grounding_gate``. Its pipeline reads only the COACH#
partition (OUTPUT#/THREAD#/PREDICTION#/CONFIDENCE#/RELATIONSHIP#/VOICE#/INTERACTION#/
LEARNING#) — none of those is a behavior log, so unlike the four surfaces #2056 wired,
there was nothing already in hand to derive a per-generation-date map from. Arming it
meant adding a read, and #2056 wrote that down as a cost decision instead of guessing a
map (a guessed or empty map is worse than none — an empty set reads as "no logs today"
and flags every same-day claim).

THE MEASUREMENT #2195 MADE, AND WHY IT PAID
-------------------------------------------
The read is ONE eventually-consistent ``GetItem`` on the platform-wide
``engagement_state`` / ``STATE#current`` singleton, hoisted above the 8-coach loop — so
the marginal cost of arming all eight stances is one read, not eight. Cadence is the
weekly ``cron(0 17 ? * SUN *)`` batch plus the ≤2/day platform-wide event-refresh cap:
≤~780 reads a year on a sub-4KB item. No IAM change (the table grant is table-level,
no leading-key condition) and no CDK change.

The ordering is what makes the map REAL rather than merely present, and it is asserted
here rather than asserted in prose: adaptive-mode writes the record at 16:35 UTC daily,
25 minutes before the weekly compression at 17:00 UTC, so the signal's own ``date``
equals the stance's ``as_of``. On the mid-week event path (triggered from the 16:00 UTC
evaluator, 35 minutes BEFORE adaptive-mode) the record still carries the previous day
and the derivation answers ``LogAvailability.none()`` — the class goes dark instead of
grading a same-day claim against yesterday's logs. Both halves are pinned below.

THE PATTERN
-----------
This extends ``tests/test_behavioral_availability_2056.py``'s differential pattern:
every claim about the wiring is proved by running the REAL gate function on the REAL
composition and showing armed and unarmed disagree on identical input. The
``TestGateActuallyFires`` class is the mutation check — delete ``available_logs=`` from
``_apply_grounding_gate``'s ``_findings_fn`` and it goes red, so the guard cannot pass
against a re-export string instead of behavior.
"""

import json
import os
import re
import sys

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "coach"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# The summarizer stamps a stance's as_of from the UTC wall clock (chs `today =
# datetime.now(timezone.utc)`), and behavior_logs treats a presence signal older
# than the target day as answering NOTHING. So these fixture days must TRACK the
# clock — the original dated literals were a #2376-class midnight bomb, and they
# detonated at 2026-08-10T00:00Z (genesis midnight), reddening main.
from datetime import datetime, timedelta, timezone  # noqa: E402

import coach_history_summarizer as chs  # noqa: E402
from ai import behavior_logs as bl  # noqa: E402

_NOW = datetime.now(timezone.utc)
GENERATION_DAY = _NOW.strftime("%Y-%m-%d")
STALE_LOG_DAY = (_NOW - timedelta(days=2)).strftime("%Y-%m-%d")  # a log that predates the stance's day
YESTERDAY = (_NOW - timedelta(days=1)).strftime("%Y-%m-%d")
WINDOW_START = (_NOW - timedelta(days=6)).strftime("%Y-%m-%d")


def _signal(**channels):
    """An engagement_state STATE#current record shaped like engagement_core writes it.

    Same helper shape as test_behavioral_availability_2056.py — deliberately duplicated
    rather than imported, so a change to that file's fixtures cannot silently rewrite
    what this one is asserting about a different surface.
    """
    return {
        "date": channels.pop("_date", GENERATION_DAY),
        "experiment_window_start": channels.pop("_window", WINDOW_START),
        "channel_detail": {src: {"last_log_date": d, "gap_days": 0} for src, d in channels.items()},
    }


def _stance(headline):
    """A stance dict as `_generate_stance` hands it to the gate (as_of already set)."""
    return {
        "headline_read": headline,
        "focused_on_now": [],
        "set_aside_for_now": [],
        "stage": {},
        "how_my_read_changed": "",
        "confidence_note": "",
        "evidence_basis": [],
        "coach_id": "nutrition_coach",
        "display_name": "Nutrition Coach",
        "domain": "nutrition",
        "as_of": GENERATION_DAY,
        "generated_at": GENERATION_DAY + "T17:00:00+00:00",
    }


_META = {"display_name": "Nutrition Coach", "domain": "nutrition"}
# The stance's allow-list source. Deliberately number-free and date-free so the ONLY
# class that can produce a finding in these tests is the behavioral one — a finding
# from the numbers/dates/freshness gates would make the differential meaningless.
_USER_MESSAGE = "Your compressed history, your track record, and your previous stance."


def _gate(headline, presence_signal, monkeypatch):
    """Run the REAL `_apply_grounding_gate` with the regen call stubbed out.

    `_call_haiku` returning None makes `regen_once`'s rewrite empty, so the original
    findings survive and are what the assertions read — the same disposition the live
    path has when Haiku cannot improve the draft.
    """
    monkeypatch.setattr(chs, "_call_haiku", lambda **kw: None)
    result = _stance(headline)
    _best, findings = chs._apply_grounding_gate("nutrition_coach", _META, {}, None, _USER_MESSAGE, result, presence_signal=presence_signal)
    return findings


# ─────────────────────────────────────────────────────────────────────────────
# 1. The gate actually fires — negative + positive on the real function.
#    This class is the mutation check: drop `available_logs=` from _findings_fn
#    and every test in it fails.
# ─────────────────────────────────────────────────────────────────────────────


class TestGateActuallyFires:
    UNGROUNDED = "You logged your meals today, and the pattern I care about is holding."
    UNSEEN = "You hit your steps today, and the pattern I care about is holding."

    def test_negative_ungrounded_same_day_claim_is_flagged(self, monkeypatch):
        """The claim no number or date gate can see: a completed ACTION with no log."""
        sig = _signal(macrofactor=STALE_LOG_DAY)  # latest food log predates the stance's day
        found = _gate(self.UNGROUNDED, sig, monkeypatch)
        assert [f["type"] for f in found] == ["ungrounded_behavioral"]
        assert found[0]["category"] == "nutrition"

    def test_positive_same_claim_with_the_log_present_passes(self, monkeypatch):
        sig = _signal(macrofactor=GENERATION_DAY)
        assert _gate(self.UNGROUNDED, sig, monkeypatch) == []

    def test_unarmed_is_the_difference(self, monkeypatch):
        """The differential proper: identical stance text, identical everything else —
        the ONLY variable is whether the caller handed the gate a map. Without it the
        surface behaves exactly as it did before #2195 (the opt-out contract)."""
        sig = _signal(macrofactor=STALE_LOG_DAY)
        assert _gate(self.UNGROUNDED, sig, monkeypatch) != []
        assert _gate(self.UNGROUNDED, None, monkeypatch) == []

    def test_no_false_flag_from_a_category_the_surface_cannot_see(self, monkeypatch):
        """ADR-104 on the gate's own input. The presence record says nothing about steps
        (no engagement channel records them, and garmin is paused per ADR-074), so a step
        claim is UNKNOWN, never "absent". A gate that fires when it could not see is the
        noise that gets a gate switched off."""
        sig = _signal(macrofactor=GENERATION_DAY)
        assert _gate(self.UNSEEN, sig, monkeypatch) == []

    def test_workout_and_journal_are_covered_too(self, monkeypatch):
        sig = _signal(macrofactor=GENERATION_DAY, hevy=STALE_LOG_DAY, notion=STALE_LOG_DAY)
        found = _gate("You completed your workout today and you journaled today.", sig, monkeypatch)
        assert sorted(f["category"] for f in found) == ["journal", "workout"]

    def test_advice_framing_is_not_a_completed_action_claim(self, monkeypatch):
        sig = _signal(macrofactor=STALE_LOG_DAY)
        assert _gate("You should log your meals today.", sig, monkeypatch) == []

    def test_prior_period_claim_stays_out_of_scope(self, monkeypatch):
        sig = _signal(macrofactor=STALE_LOG_DAY)
        assert _gate("Last week you logged your meals every day.", sig, monkeypatch) == []

    def test_a_finding_survives_a_regen_that_does_not_improve(self, monkeypatch):
        """Disposition is INHERITED, not chosen here: findings that survive the one
        regen flow back to `_run_stance`, which fail-keep-priors. Proving the finding
        reaches the caller is proving the gate has consequences."""
        sig = _signal(macrofactor=STALE_LOG_DAY)
        monkeypatch.setattr(chs, "_call_haiku", lambda **kw: {"headline_read": "You logged your meals today."})
        result = _stance(self.UNGROUNDED)
        best, findings = chs._apply_grounding_gate("nutrition_coach", _META, {}, None, _USER_MESSAGE, result, presence_signal=sig)
        assert findings and findings[0]["type"] == "ungrounded_behavioral"
        assert best["headline_read"] == self.UNGROUNDED  # the un-improved rewrite is discarded


# ─────────────────────────────────────────────────────────────────────────────
# 2. The whole stance path, not just the gate helper
# ─────────────────────────────────────────────────────────────────────────────


class TestEndToEndStancePath:
    def test_generate_stance_threads_the_signal_into_the_gate(self, monkeypatch):
        """`_generate_stance` is the real entry point. Same stubbed model, same text —
        with the signal the stance carries a behavioral finding, without it none."""
        monkeypatch.setattr(chs, "_coach_meta", lambda cid: dict(_META))
        monkeypatch.setattr(
            chs,
            "_call_haiku",
            lambda **kw: {"headline_read": "You logged your meals today, and that is the read I hold."},
        )
        sig = _signal(macrofactor=STALE_LOG_DAY)
        armed = chs._generate_stance("nutrition_coach", {}, {}, None, presence_signal=sig)
        unarmed = chs._generate_stance("nutrition_coach", {}, {}, None)
        assert [f["type"] for f in armed["_adr104_findings"]] == ["ungrounded_behavioral"]
        assert unarmed["_adr104_findings"] == []

    def test_run_stance_keeps_the_prior_rather_than_writing_the_ungrounded_one(self, monkeypatch):
        """The consequence, end to end: an ungrounded same-day behavioral claim now
        blocks the STANCE# write exactly as an ungrounded NUMBER already did."""
        monkeypatch.setattr(chs, "_coach_meta", lambda cid: dict(_META))
        monkeypatch.setattr(
            chs,
            "_call_haiku",
            lambda **kw: {"headline_read": "You logged your meals today, and that is the read I hold."},
        )
        monkeypatch.setattr(chs, "_gather_learning", lambda cid, limit=40: [])
        monkeypatch.setattr(chs, "_get_item", lambda pk, sk: None)
        writes = []
        monkeypatch.setattr(chs, "_write_stance", lambda cid, st: writes.append(cid) or True)
        out = chs._run_stance("nutrition_coach", {}, {}, presence_signal=_signal(macrofactor=STALE_LOG_DAY))
        assert out["written"] is False
        assert out["reason"] == "adr104_gate_failed_no_prior"
        assert writes == []


# ─────────────────────────────────────────────────────────────────────────────
# 3. The cost decision, asserted (this is what makes the exemption discharged)
# ─────────────────────────────────────────────────────────────────────────────


class TestTheReadIsOnePerInvocation:
    def test_the_weekly_batch_reads_the_signal_once_for_all_eight_coaches(self, monkeypatch):
        """The measured cost only holds if the read is hoisted. Eight coaches, ONE read
        — if someone moves `_presence_signal()` inside the loop this goes to 8 and
        fails, which is the whole cost argument turning into a regression test."""
        calls = []
        monkeypatch.setattr(chs, "_presence_signal", lambda: calls.append(1) or _signal(macrofactor=GENERATION_DAY))
        monkeypatch.setattr(chs, "_gather_coach_state", lambda cid: {"outputs": [{"sk": "OUTPUT#1"}]})
        # #2428: the compression takes the same hoisted signal (its own gate arms #1699 too)
        monkeypatch.setattr(chs, "_compress_coach", lambda cid, st, presence_signal=None: {"summary": "s"})
        monkeypatch.setattr(chs, "_write_compressed_state", lambda cid, c: True)
        seen = []
        monkeypatch.setattr(
            chs,
            "_run_stance",
            lambda cid, c, st, trigger="weekly", event_context=None, presence_signal=None: seen.append(presence_signal) or {},
        )
        chs.lambda_handler({}, None)
        assert len(calls) == 1, "the engagement_state read must be hoisted above the coach loop"
        assert len(seen) == len(chs.ALL_COACH_IDS)
        assert all(s is not None for s in seen), "every coach must get the one signal"

    def test_the_read_targets_the_engagement_state_singleton_through_the_phase_filter(self, monkeypatch):
        """Two facts in one: the key is the canonical engagement_state partition, and it
        goes through `_get_item` — so a restart's TOMBSTONED record (#1895/#1969) is
        filtered out and cannot seed a fresh cycle's availability map."""
        seen = {}
        monkeypatch.setattr(chs, "_get_item", lambda pk, sk: seen.update(pk=pk, sk=sk) or {"date": GENERATION_DAY})
        chs._presence_signal()
        assert seen == {"pk": "USER#matthew#SOURCE#engagement_state", "sk": "STATE#current"}

    def test_a_failed_or_tombstoned_read_leaves_the_class_unarmed(self, monkeypatch):
        """Fail-soft, and honestly: no signal ⇒ no map ⇒ no findings, never a guess."""
        monkeypatch.setattr(chs, "_get_item", lambda pk, sk: None)
        assert chs._presence_signal() is None
        assert _gate("You logged your meals today.", chs._presence_signal(), monkeypatch) == []


# ─────────────────────────────────────────────────────────────────────────────
# 4. Guard the SET, not the instance
# ─────────────────────────────────────────────────────────────────────────────


def _cron(function_name):
    """The `schedule=` literal of a named lambda in the compute stack."""
    src = open(os.path.join(_REPO, "cdk", "stacks", "compute_stack.py"), encoding="utf-8").read()
    at = src.index(f'function_name="{function_name}"')
    m = re.search(r'schedule="cron\(([^)]*)\)"', src[at:])
    assert m, f"{function_name} has no schedule literal"
    minute, hour = m.group(1).split()[:2]
    return int(hour) * 60 + int(minute)


class TestTheOrderingThatMakesTheMapReal:
    def test_the_weekly_run_is_after_the_writer_of_the_record_it_reads(self):
        """The load-bearing fact behind arming this surface at all, derived from the CDK
        source rather than restated: adaptive-mode (which WRITES engagement_state) runs
        before coach-history-summarizer on the same UTC day, so the signal's `date`
        equals the stance's `as_of`. Move the summarizer earlier and this fails — which
        is the correct outcome, because the map would silently stop being same-day."""
        assert _cron("adaptive-mode-compute") < _cron("coach-history-summarizer")

    def test_a_signal_from_before_the_stance_day_answers_nothing(self):
        """The mid-week event path, which fires from the 16:00 UTC evaluator — BEFORE
        adaptive-mode's 16:35 write. The record still carries yesterday, so the honest
        answer is `none()`, not yesterday's logs applied to today's claim."""
        stale = _signal(_date=YESTERDAY, macrofactor=YESTERDAY)
        assert bl.available_logs_from_presence(stale, GENERATION_DAY) == bl.LogAvailability.none()
        assert _cron("coach-prediction-evaluator") < _cron("adaptive-mode-compute")

    def test_the_stance_prompt_is_still_a_second_person_surface_about_matthew(self):
        """The #1699 class only checks a second-person completed-action claim, and five
        of the census's remaining exemptions are exactly "`you` is not Matthew here".
        This surface qualifies BY PROMPT RULE — if that rule ever changes, the arming
        decision has to be revisited rather than left running on a stale premise."""
        assert "Address him as 'you'" in chs.STANCE_SYSTEM_PROMPT
        assert "Matthew" in chs.STANCE_SYSTEM_PROMPT

    def test_the_prose_blob_the_gate_reads_still_carries_the_narrative_fields(self):
        """The gate sees `_stance_prose_blob`, not the whole record. A field dropped
        from that tuple would silently stop being graded."""
        blob = json.loads(chs._stance_prose_blob(_stance("You logged your meals today.")))
        assert "headline_read" in blob and "how_my_read_changed" in blob
        assert "generated_at" not in blob, "bookkeeping timestamps must stay out of the graded text"


class TestCensusIsUpdated:
    def test_the_registry_arms_this_surface_and_the_tree_agrees(self):
        from grounding_wiring import SURFACES, scan_tree

        key = "lambdas/coach/coach_history_summarizer.py::_apply_grounding_gate"
        assert "behavioral" in SURFACES[key]["required"]
        assert "behavioral" in scan_tree()[key], "the registry policy must match what the AST scan finds"

    def test_the_deferred_residual_reason_is_gone_from_the_registry(self):
        """#2056 recorded this surface's exemption with the shape of its fix. The fix
        landed, so the reason must not linger as a stale decision."""
        import grounding_wiring as gw

        assert not hasattr(gw, "_HISTORY_ONLY_INPUT")
        reasons = [v["exempt"]["behavioral"] for v in gw.SURFACES.values() if "behavioral" in v["exempt"]]
        assert not any("genuine missing-map residual" in r for r in reasons)

    def test_no_exemption_reason_is_doing_blanket_duty(self):
        """The #2056 invariant, re-asserted against the smaller exempt set: a reason
        cited by a majority of exemptions is a placeholder, not a decision."""
        from grounding_wiring import SURFACES

        reasons = [v["exempt"]["behavioral"] for v in SURFACES.values() if "behavioral" in v["exempt"]]
        assert reasons, "honest partial coverage — the census should not claim 100%"
        assert max(reasons.count(r) for r in set(reasons)) <= len(reasons) // 2 + 1
        for key, entry in SURFACES.items():
            reason = entry["exempt"].get("behavioral")
            assert reason is None or len(reason) > 80, f"{key}: exemption reason is too thin to be a decision"
