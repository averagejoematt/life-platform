"""tests/test_pain_dismissal_4036.py — an owner may dismiss a pain flag, and it re-arms.

THE DEFECT (#4036)
  The derived note layer flags pain over-inclusively ON PURPOSE — its own reader says
  "confirm or dismiss before loading that movement" — and under the v0.3 program a tripped
  `pain_flag_named_site` substitutes the movement pattern for two weeks. There was nowhere
  for the "dismiss" half to live. On 2026-09-21 Matthew said the right lower back flagged
  from the 2026-09-13 Romanian Deadlift note ("could feel my right side of my lower back
  more consciously… not pain or ache") was gone, and neither `plan_engine._tripwire_states`
  nor `coach/critics.py::build_joints_packet` could hear it. A stale flag benches the lift
  against his own word.

WHAT IS PINNED HERE
  1. THE RECORD — `build_dismissal_record` validates what a dismissal must carry (site, the
     date he said it, his VERBATIM words, the flag instance it dismisses) and is
     Decimal-safe by construction: no float ever reaches DynamoDB from it.
  2. THE ROUND TRIP — flag → dismissal → the tripwire reads `dismissed_by_owner` (never
     `clear`, because an absence and an override are different facts), the honesty line
     names it, and the joints critic approves the drafted movement instead of vetoing it.
  3. THE RE-ARM — a note on the same movement dated AFTER the dismissal trips the flag
     again, marks the dismissal superseded, and restores the veto. He never has to remember
     he once dismissed it.
  4. THE HONEST EDGE — a flag whose note date cannot be read is NOT dismissed, and a
     dismissal on a different movement does not cover this one.

MUTATION EVIDENCE
  The whole issue is one date comparison, in `training_context_registry.resolve_flag`:

      if dates[-1] > dismissed_on:   # re-armed

  Removing it (so a dismissal never expires) was applied to the real tracked module,
  verified changed, and the verdict read before restoring. The output is recorded in the
  PR body: the two re-arm tests below FAIL, and the four dismissal/approval tests stay
  green — i.e. the green of this file is bought by the comparison, not by the fixtures.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "lambdas"))

from coach import critics as c  # noqa: E402
from training import plan_engine, training_context_registry as tcr  # noqa: E402
from training.routine_ir import ExerciseBlock, RoutineSpec, Set  # noqa: E402

KG = 1 / c._LBS_PER_KG
RDL = "Romanian Deadlift (Barbell)"

# The first live entry, verbatim (#4036). Used as the fixture so the test and the record
# the driver writes describe the same event.
OWNER_WORDS = "right lower back gone"
DISMISSED_ON = "2026-09-21"
FLAG_NOTE_DATE = "2026-09-13"


def _dismissal(site="right lower back", dismissed_on=DISMISSED_ON, movements=(RDL,), flag_note_date=FLAG_NOTE_DATE):
    return tcr.build_dismissal_record(
        site=site,
        dismissed_on=dismissed_on,
        words=OWNER_WORDS,
        movements=list(movements),
        flag_note_date=flag_note_date,
        recorded_at="2026-09-21T20:00:00Z",
    )


def _tripwires(*, note_dates, dismissals):
    return plan_engine._tripwire_states(
        protein_days_missed_7d=0,
        readiness_low_streak_days=0,
        anchor_lift_drop_pct=0.0,
        anchor_lift_drop_sessions=0,
        pain_flag_sites=[RDL],
        pain_flag_instances=[{"movement": RDL, "note_dates": list(note_dates)}],
        pain_dismissals=dismissals,
        pain_layer_status="ok",
        weight_stall_days=0,
        adherence_on_plan=True,
    )


def _pain_row(tripwires):
    return next(t for t in tripwires if t["id"] == "pain_flag_named_site")


# ── 1. the record ─────────────────────────────────────────────────────────────


class TestTheRecord:
    def test_it_carries_site_date_verbatim_words_and_the_flag_instance(self):
        r = _dismissal()
        assert r["sk"] == "DISMISSAL#right_lower_back#2026-09-21"
        assert r["site"] == "right lower back" and r["site_key"] == "right_lower_back"
        assert r["words"] == OWNER_WORDS, "the owner's words are stored VERBATIM, never paraphrased"
        assert r["movements"] == [RDL] and r["flag_note_date"] == FLAG_NOTE_DATE
        assert r["dismissed_on"] == DISMISSED_ON

    def test_no_float_can_reach_dynamodb_from_it(self):
        """boto3 rejects native float. Every value here is a str or a list of str, so the
        record is Decimal-safe by construction rather than by a walker nobody re-runs."""

        def walk(v):
            if isinstance(v, dict):
                return all(walk(x) for x in v.values())
            if isinstance(v, (list, tuple)):
                return all(walk(x) for x in v)
            return isinstance(v, str)

        assert walk(_dismissal())

    @pytest.mark.parametrize(
        "kwargs,needle",
        [
            ({"site": ""}, "site is required"),
            ({"words": "  "}, "VERBATIM"),
            ({"dismissed_on": "21-09-2026"}, "dismissed_on must be YYYY-MM-DD"),
            ({"movements": []}, "at least one movement"),
            ({"flag_note_date": ""}, "flag_note_date must be YYYY-MM-DD"),
            ({"flag_note_date": "2026-09-30"}, "cannot precede the flag it dismisses"),
        ],
    )
    def test_a_dismissal_that_cannot_name_what_it_dismisses_is_refused(self, kwargs, needle):
        base = {
            "site": "right lower back",
            "dismissed_on": DISMISSED_ON,
            "words": OWNER_WORDS,
            "movements": [RDL],
            "flag_note_date": FLAG_NOTE_DATE,
            "recorded_at": "2026-09-21T20:00:00Z",
        }
        with pytest.raises(ValueError) as e:
            tcr.build_dismissal_record(**{**base, **kwargs})
        assert needle in str(e.value)

    def test_two_spellings_of_one_site_are_one_record(self):
        assert tcr.dismissal_sk("Right Lower Back", DISMISSED_ON) == tcr.dismissal_sk("right_lower_back", DISMISSED_ON)


# ── 2. the tripwire ───────────────────────────────────────────────────────────


class TestTheTripwire:
    def test_without_a_dismissal_the_flag_is_tripped(self):
        row = _pain_row(_tripwires(note_dates=[FLAG_NOTE_DATE], dismissals=[]))
        assert row["state"] == "tripped" and row["observed"] == [RDL]
        assert "dismissals" not in row

    def test_with_the_dismissal_it_reads_dismissed_by_owner_never_clear(self):
        row = _pain_row(_tripwires(note_dates=[FLAG_NOTE_DATE], dismissals=[_dismissal()]))
        assert row["state"] == "dismissed_by_owner", row
        assert row["state"] != "clear", "a dismissal is an override, not an absence"
        assert DISMISSED_ON in row["detail"] and OWNER_WORDS in row["detail"]
        assert row["dismissals"][0]["dismissed"] is True
        assert row["dismissals"][0]["superseded"] is False

    def test_the_block_names_the_dismissal_in_its_honesty_lines(self):
        block = plan_engine.constraint_block(
            date="2026-09-22",
            pain_flag_sites=[RDL],
            pain_flag_instances=[{"movement": RDL, "note_dates": [FLAG_NOTE_DATE]}],
            pain_dismissals=[_dismissal()],
            pain_layer_status="ok",
        )
        assert "pain_flag_named_site" not in block["tripped"]
        assert block["owner_dismissals"] and block["owner_dismissals"][0]["site"] == "right lower back"
        line = next((h for h in block["honesty"] if "owner dismissal" in h), None)
        assert line and OWNER_WORDS in line and DISMISSED_ON in line, block["honesty"]

    def test_a_flag_with_no_readable_note_date_is_not_dismissed(self):
        """#3767 applied to an override: with nothing to compare, 'dismissed' is an
        assumption wearing a verdict's clothes."""
        row = _pain_row(_tripwires(note_dates=[], dismissals=[_dismissal()]))
        assert row["state"] == "tripped"
        assert row["dismissals"][0]["state"] == "undated_flag"

    def test_a_dismissal_on_another_movement_does_not_cover_this_flag(self):
        row = _pain_row(_tripwires(note_dates=[FLAG_NOTE_DATE], dismissals=[_dismissal(movements=("Back Squat (Barbell)",))]))
        assert row["state"] == "tripped" and not row.get("dismissals")

    def test_the_re_arm_a_later_note_on_the_same_site_trips_it_again(self):
        """MUTATION TARGET. Remove the `dates[-1] > dismissed_on` comparison in
        `resolve_flag` and this test reds — the dismissal never expires."""
        row = _pain_row(_tripwires(note_dates=[FLAG_NOTE_DATE, "2026-09-25"], dismissals=[_dismissal()]))
        assert row["state"] == "tripped", "a note AFTER the dismissal must re-arm the flag"
        res = row["dismissals"][0]
        assert res["state"] == "re_armed" and res["superseded"] is True and res["dismissed"] is False
        assert "2026-09-25" in res["detail"] and DISMISSED_ON in res["detail"]


# ── 3. the joints critic ──────────────────────────────────────────────────────


def _draft():
    ir = RoutineSpec(
        routine_id="r-4036",
        target_date="2026-09-22",
        archetype="full_body",
        exercises=[
            ExerciseBlock(movement_key="tmpl:rdl", rationale_tag=RDL, sets=[Set(weight_kg=100 * KG, reps=8) for _ in range(3)]),
        ],
    )
    return c.draft_summary(ir)


def _all_packets(joints):
    """run_critics needs the full board; the other three are clean so any verdict but the
    joints critic's is an approval by construction."""
    d = _draft()
    return {
        "muscle_defense": c.build_muscle_defense_packet(
            d, anchor_trends=None, protein_days_missed_7d=0, protein_days_measured_7d=7, program_week=7
        ),
        "joints_tendons": joints,
        "rate_advocate": c.build_rate_advocate_packet(
            d, tripwires=[], walking=None, rate_target=None, current_rate_lb_wk=None, lifting_sessions_7d=2
        ),
        "blueprint_historian": c.build_historian_packet(d, weeks_in_block=0, reference=None),
    }


def _joints(note_dates, dismissals):
    return c.build_joints_packet(
        _draft(),
        pain_by_idx={0: {"pain_flag_any": True, "pain_dates": list(note_dates)}},
        days_since_by_idx={0: 9},
        loaded_lifting_streak=1,
        pain_layer_status="ok",
        dismissals=dismissals,
    )


class TestTheJointsCritic:
    def test_without_a_dismissal_the_flagged_movement_is_vetoed(self):
        p = _joints([FLAG_NOTE_DATE], None)
        assert [v["redline"] for v in p["violations"]] == ["pain_flag_loaded"]
        verdicts = c.run_critics(_all_packets(p), _draft(), invoke=None, model_allowed=False)
        joints = next(v for v in verdicts if v["critic"] == "joints_tendons")
        assert joints["verdict"] == "veto" and joints["redline"] == "pain_flag_loaded"

    def test_with_the_dismissal_the_critic_approves_and_carries_the_override(self):
        p = _joints([FLAG_NOTE_DATE], [_dismissal()])
        assert p["violations"] == [], p["violations"]
        assert p["numbers"]["pain_flag[0]"] is True, "the flag itself is still reported — it happened"
        assert p["numbers"]["pain_dismissed[0]"] is True
        assert p["owner_dismissals"][0]["words"] == OWNER_WORDS
        assert not [f for f in p["flags"] if f["metric"] == "pain_flag[0]"], "no flag on a dismissed instance (no escalation handle)"
        verdicts = c.run_critics(_all_packets(p), _draft(), invoke=None, model_allowed=False)
        joints = next(v for v in verdicts if v["critic"] == "joints_tendons")
        assert joints["verdict"] == "approve", joints
        assert [v["verdict"] for v in verdicts] == ["approve"] * 4, verdicts

    def test_the_re_arm_restores_the_veto_and_says_the_dismissal_was_superseded(self):
        """MUTATION TARGET — the same comparison as the tripwire's re-arm test."""
        p = _joints([FLAG_NOTE_DATE, "2026-09-25"], [_dismissal()])
        assert [v["redline"] for v in p["violations"]] == ["pain_flag_loaded"]
        assert "superseded" in p["violations"][0]["reason"]
        assert p["numbers"]["pain_dismissed[0]"] is False
        assert p["owner_dismissals"][0]["superseded"] is True

    def test_the_packets_stay_pairwise_disjoint_with_a_dismissal_in_play(self):
        """The #3752 mechanism: a metric name may appear in ONE packet. The new
        `pain_dismissed[i]` key must not break it."""
        joints = _joints([FLAG_NOTE_DATE], [_dismissal()])
        others = {k: v for k, v in _all_packets(joints).items() if k != "joints_tendons"}
        for name, p in others.items():
            shared = set(p["numbers"]) & set(joints["numbers"])
            assert not shared, f"joints_tendons and {name} share {shared}"


# ── 4. the rule is not restated in two places ─────────────────────────────────


def test_both_consumers_derive_from_the_one_rule_module():
    """Two copies of the date comparison is how one consumer keeps dismissing a flag the
    other has already re-armed. Both must call the registry."""
    engine = (REPO / "lambdas" / "training" / "plan_engine.py").read_text()
    critic = (REPO / "lambdas" / "coach" / "critics.py").read_text()
    assert "training_context_registry.resolve_flags(" in engine
    assert (
        "training_context_registry.resolve_flags(" in critic
    ), "#4174: the critic resolves per (movement, site) through the same entry point"
    for consumer in (engine, critic):
        assert "training_context_registry.expand_instances(" in consumer, "the per-site split is the registry's, not a local copy (#4174)"


def test_the_store_is_classified_tiered_and_documented():
    """The three places a new owner-only SOURCE# family has to land (#3669/#3514/#3045)."""
    sys.path.insert(0, str(REPO / "lambdas"))
    from experiment import phase_taxonomy
    from privacy import field_tiers

    assert phase_taxonomy.SOURCE_CLASS[tcr.DISMISSAL_SOURCE] == phase_taxonomy.CROSS_PHASE
    assert field_tiers.source_tier_of(tcr.DISMISSAL_SOURCE) == field_tiers.TIER_OWNER_ONLY
    assert not field_tiers.is_publishable(field_tiers.source_tier_of(tcr.DISMISSAL_SOURCE))
    assert tcr.DISMISSAL_SOURCE in (REPO / "docs" / "SCHEMA.md").read_text()


def test_the_census_disposition_follow_up_is_armed():
    """#3669: a live `SOURCE#` partition needs a registry entry, a platform-written taxonomy
    class, or a dated `UNREGISTERED_PARTITIONS` reason. CROSS_PHASE is none of those, and an
    exemption for a partition the census cannot see is itself a red
    (`test_no_exemption_describes_a_partition_that_is_not_there`). So the disposition lands
    with the first live record, and this test says so out loud on whichever side of that
    line the repo is standing — rather than letting the next census regeneration red main
    with nobody knowing why."""
    import json

    from ingestion import source_registry as reg

    census = json.loads((REPO / "deploy" / "generated" / "pk_family_census.json").read_text())
    family = f"SOURCE#{tcr.DISMISSAL_SOURCE}"
    if family in census.get("families", {}):
        assert tcr.DISMISSAL_SOURCE in reg.UNREGISTERED_PARTITIONS, (
            f"{family} is now live in the census: add the dated UNREGISTERED_PARTITIONS entry "
            "(#4036 named the text in its PR body) or #3669's guard reds with no explanation."
        )
    else:
        assert tcr.DISMISSAL_SOURCE not in reg.UNREGISTERED_PARTITIONS, "an exemption for a partition the census cannot see is fiction"


def test_the_write_is_wired_on_the_tool_that_owns_the_pain_flag_surface():
    """#4036's ONE MCP write. It is an ACTION on `get_exercise_notes` rather than a tool of
    its own: minting a tool moves `mcp_tools`, a generated literal that lives only in
    `lambdas/web/platform_counts.py` and that no branch may carry (#3101/#3984), so the
    stale-number gate would red the PR on doc headers the reconcile job owns. The issue's
    acceptance sanctions an action on an existing owner tool, and this is the tool whose own
    `note` says "confirm or dismiss before loading that movement"."""
    import os

    os.environ.setdefault("TABLE_NAME", "life-platform")
    os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
    os.environ.setdefault("USER_ID", "matthew")
    os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
    sys.path.insert(0, str(REPO))

    from mcp import tools_training_notes as ttn
    from mcp.tools_descriptions import GET_EXERCISE_NOTES_INPUT

    action = GET_EXERCISE_NOTES_INPUT["properties"]["action"]
    assert set(action["enum"]) == {"read", "dismiss", "dismissals"}
    for field in ("site", "words", "flag_note_date", "dismissed_on"):
        assert field in GET_EXERCISE_NOTES_INPUT["properties"], f"{field} is not documented on the tool that writes it"

    # dispatch, without touching DynamoDB: an unknown action is named, never silently read.
    out = ttn.tool_get_exercise_notes({"action": "nope"})
    assert "error" in out and out["valid_actions"] == ["read", "dismiss", "dismissals"]

    # a dismissal that cannot name its instance is refused BEFORE any read or write.
    refused = ttn.tool_get_exercise_notes({"action": "dismiss", "site": "right lower back", "words": ""})
    assert refused["error"].startswith("refused:") and "VERBATIM" in refused["error"]


# ── 5. #4174 — a dismissal covers its own SITE, never every note on the movement ──────
#
# THE WIRE (read-only, 2026-09-26): Cycling carries two flagged notes on two sites — 09-09
# "…more just saddle sore and uncomfortable with compression shorts" and 09-18 "…big toe
# throbbing from ingrown toe so took it easy" — and two owner dismissals dated 09-25, each
# pinning its own note (`flag_note_date`), both with `movements: ["cycling"]` as the chat
# wrote them. Pre-#4174 `_dismissal_matches` matched by MOVEMENT, so the saddle-sore record
# alone resolved the whole movement `dismissed_by_owner` with `latest_note_date 2026-09-18`.
CYCLING = "Cycling"
CYCLING_WORDS = "Dismiss the Cycling pain flag — it's resolved, no pain cycling now"
SADDLE_NOTE = {
    "date": "2026-09-09",
    "text": "Level 8 flat - cardio felt ok - more just saddle sore and uncomfortable with compression shorts",
}
TOE_NOTE = {"date": "2026-09-18", "text": "Level 10 flat - big toe throbbing from ingrown toe so took it easy"}


def _cycling_dismissal(site, flag_note_date):
    return tcr.build_dismissal_record(
        site=site,
        dismissed_on="2026-09-25",
        words=CYCLING_WORDS,
        movements=["cycling"],
        flag_note_date=flag_note_date,
        recorded_at="2026-09-26T02:21:26Z",
    )


SADDLE_SORE = _cycling_dismissal("saddle sore", "2026-09-09")
BIG_TOE = _cycling_dismissal("big toe", "2026-09-18")
CYCLING_INSTANCE = {"movement": CYCLING, "note_dates": [SADDLE_NOTE["date"], TOE_NOTE["date"]], "notes": [SADDLE_NOTE, TOE_NOTE]}


def _cycling_tripwires(dismissals):
    return plan_engine._tripwire_states(
        protein_days_missed_7d=0,
        readiness_low_streak_days=0,
        anchor_lift_drop_pct=0.0,
        anchor_lift_drop_sessions=0,
        pain_flag_sites=[CYCLING],
        pain_flag_instances=[dict(CYCLING_INSTANCE)],
        pain_dismissals=dismissals,
        pain_layer_status="ok",
        weight_stall_days=0,
        adherence_on_plan=True,
    )


def _movement_only_rule(dismissal, *, movement, site, note_dates=None):
    """The pre-#4174 matcher, verbatim in effect: any dismissal naming the movement covers it."""
    return bool(movement) and tcr.normalize_dismissal_key(movement) in tcr._movement_keys(dismissal)


class TestPerSite4174:
    def test_the_split_keys_each_note_to_its_own_site_and_leaves_the_unnamed_one_open(self):
        inst = tcr.expand_instances([CYCLING_INSTANCE], [SADDLE_SORE])
        assert [(i["site"], i["note_dates"]) for i in inst] == [("saddle_sore", ["2026-09-09"]), (None, ["2026-09-18"])]
        both = tcr.expand_instances([CYCLING_INSTANCE], [SADDLE_SORE, BIG_TOE])
        assert [(i["site"], i["note_dates"]) for i in both] == [("big_toe", ["2026-09-18"]), ("saddle_sore", ["2026-09-09"])]

    def test_the_words_tie_an_unpinned_note_to_its_site(self):
        """A second saddle note the dismissal did not pin still belongs to `saddle_sore` by its
        own words — and a note dated after the dismissal re-arms it, the #4036 rule unchanged."""
        again = {"date": "2026-09-20", "text": "saddle still sore, shorter ride"}
        inst = tcr.expand_instances(
            [{"movement": CYCLING, "note_dates": ["2026-09-09", "2026-09-20"], "notes": [SADDLE_NOTE, again]}], [SADDLE_SORE]
        )
        assert [(i["site"], i["note_dates"]) for i in inst] == [("saddle_sore", ["2026-09-09", "2026-09-20"])]
        res = tcr.resolve_flags(inst, [SADDLE_SORE])
        assert res[0]["state"] == "dismissed_by_owner", "both notes predate the 09-25 dismissal"
        later = {"date": "2026-09-27", "text": "saddle sore again"}
        res = tcr.resolve_flags(
            [{"movement": CYCLING, "note_dates": ["2026-09-09", "2026-09-27"], "notes": [SADDLE_NOTE, later]}], [SADDLE_SORE]
        )
        assert res[0]["state"] == "re_armed" and res[0]["superseded"] is True

    def test_one_dismissal_on_a_two_site_movement_stays_tripped_with_the_toe_open(self):
        """Acceptance box 1, first half. The saddle-sore record covers 09-09 and nothing else."""
        row = _pain_row(_cycling_tripwires([SADDLE_SORE]))
        assert row["state"] == "tripped", row
        assert row["by_movement"] == {CYCLING: "tripped"}
        states = {(r["site"], r["state"], r["dismissal_state"]) for r in row["by_site"]}
        assert states == {("saddle_sore", "dismissed_by_owner", "dismissed_by_owner"), (None, "tripped", "none")}
        assert [d["sk"] for d in row["dismissals"]] == ["DISMISSAL#saddle_sore#2026-09-25"]
        assert row["dismissals"][0]["latest_note_date"] == "2026-09-09", "the saddle row must not carry the toe note's date"
        assert "2026-09-18" in row["detail"] and "name no dismissed site" in row["detail"]

    def test_both_dismissals_read_dismissed_by_owner_and_the_block_lists_both(self):
        """Acceptance box 1, second half, and box 2: every dismissal in play is listed."""
        row = _pain_row(_cycling_tripwires([SADDLE_SORE, BIG_TOE]))
        assert row["state"] == "dismissed_by_owner", row
        assert sorted(d["sk"] for d in row["dismissals"]) == ["DISMISSAL#big_toe#2026-09-25", "DISMISSAL#saddle_sore#2026-09-25"]
        assert {r["site"]: r["state"] for r in row["by_site"]} == {"big_toe": "dismissed_by_owner", "saddle_sore": "dismissed_by_owner"}
        block = plan_engine.constraint_block(
            date="2026-09-26",
            pain_flag_sites=[CYCLING],
            pain_flag_instances=[dict(CYCLING_INSTANCE)],
            pain_dismissals=[SADDLE_SORE, BIG_TOE],
            pain_layer_status="ok",
        )
        assert sorted(d["sk"] for d in block["owner_dismissals"]) == ["DISMISSAL#big_toe#2026-09-25", "DISMISSAL#saddle_sore#2026-09-25"]
        assert "pain_flag_named_site" not in block["tripped"]

    def test_the_joints_critic_vetoes_until_every_site_on_the_lift_is_dismissed(self):
        def packet(dismissals):
            return c.build_joints_packet(
                _draft(),
                pain_by_idx={
                    0: {"pain_flag_any": True, "pain_dates": [SADDLE_NOTE["date"], TOE_NOTE["date"]], "pain_notes": [SADDLE_NOTE, TOE_NOTE]}
                },
                days_since_by_idx={0: 3},
                loaded_lifting_streak=1,
                pain_layer_status="ok",
                dismissals=dismissals,
            )

        one = packet([{**SADDLE_SORE, "movements": [RDL], "movement_keys": [tcr.normalize_dismissal_key(RDL)]}])
        assert [v["redline"] for v in one["violations"]] == ["pain_flag_loaded"], "one site dismissed, the other open: the veto stands"
        assert "2026-09-18" in one["violations"][0]["reason"] and "#4174" in one["violations"][0]["reason"]
        assert one["numbers"]["pain_dismissed[0]"] is False
        both = packet([{**d, "movements": [RDL], "movement_keys": [tcr.normalize_dismissal_key(RDL)]} for d in (SADDLE_SORE, BIG_TOE)])
        assert both["violations"] == [] and both["numbers"]["pain_dismissed[0]"] is True
        assert sorted(d["sk"] for d in both["owner_dismissals"]) == ["DISMISSAL#big_toe#2026-09-25", "DISMISSAL#saddle_sore#2026-09-25"]

    def test_mutation_control_the_per_movement_rule_hides_the_big_toe_note_again(self, monkeypatch):
        """THE control for #4174. Both halves in one run: under the shipped per-site matcher the
        one-dismissal case stays `tripped` with the toe note open; put the pre-#4174
        movement-only matcher back and the same inputs read `dismissed_by_owner` — the
        defect, reproduced — so the green above is bought by the site leg, not the fixture."""
        intact = _pain_row(_cycling_tripwires([SADDLE_SORE]))
        assert intact["state"] == "tripped"
        monkeypatch.setattr(tcr, "_dismissal_matches", _movement_only_rule)
        broken = _pain_row(_cycling_tripwires([SADDLE_SORE]))
        assert broken["state"] == "dismissed_by_owner", "the movement-only rule no longer hides the toe note — the control is dead"
        assert all(r["state"] == "dismissed_by_owner" for r in broken["by_site"]), broken["by_site"]
