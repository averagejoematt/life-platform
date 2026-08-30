"""#3294 — the absence-sourcing check must REACH every surface that asserts an absence.

THE LIVE DEFECT (two instances, one class)
------------------------------------------
A `/method/board/` coach read asserted Matthew "has not logged any food, training,
habits, or journal entries since" cycle start (2026-08-17). Ground truth for that
window: macrofactor 0 ✅, notion 0 ✅, strava 2 (08-17, 08-18) ❌, habitify 12 ❌ —
two of the four asserted absences were false. And `/api/pulse`'s lift glyph published
"No training logged — 64 days": right for Hevy, wrong for the word "training" (Strava
trained 10 days before it was published).

Both instances share one shape: *a category-level absence asserted from one source*.
The #3252/#3276 check existed and was green while both published, because the surfaces
never consulted it — the presence signal's raw `channels_quiet` list (denominator: ONE
`engagement_channel` source per label) flowed straight into prompts and labels.

WHAT THIS FILE PINS
-------------------
1. THE WIRE: the exact stored STATE#current artifact (fetched from DynamoDB
   2026-08-29, the same record class the board generated from) replayed through every
   wired surface — training and habits WITHHELD, food and journal licensed. Watched to
   fail against the pre-fix tree before the fix landed.
2. The lift glyph's label is gated on the registry denominator, and the workout
   evidence sweep consults every `evidence_for("workout")` source, not Hevy alone.
3. THE ENUMERATION (derived, AST): every module that reads `channels_quiet` is
   classified — wired through the ONE address (`content.engagement_core.sourced_quiet`)
   or documented out-of-scope with a reason. "The check exists" and "the check reaches
   this surface" are different claims; this is the second one, and it fails on any NEW
   reader that forks the raw field (guard the SET, not the instance).

The enumeration is keyed on the FIELD NAME (a data-flow key), never on narrative
phrasing — the #2959/#3003/#3199 family rules out phrase-matching, and nothing here
reads English.
"""

import ast
import os
import pathlib
import sys
from datetime import date, timedelta

import pytest

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")  # mcp.config reads these at import
os.environ.setdefault("USER_ID", "matthew")

_REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "lambdas"))
sys.path.insert(0, str(_REPO))

from ai.absence_sourcing import absence_sourcing, sourced_quiet_channels  # noqa: E402
from content.engagement_core import presence_prompt_block  # noqa: E402

# ─────────────────────────────────────────────────────────────────────────────
# THE WIRE — the stored engagement_state STATE#current artifact, verbatim.
# Fetched from DynamoDB 2026-08-29 (run b207289a); numeric types collapsed the way
# every consumer's decimal_to_float pass collapses them. The four quiet labels are
# exactly the four the board asserted; ground truth held records for two of them.
# ─────────────────────────────────────────────────────────────────────────────


def stored_artifact():
    return {
        "pk": "USER#matthew#SOURCE#engagement_state",
        "sk": "STATE#current",
        "algo_version": "1.0",
        "date": "2026-08-29",
        "computed_at": "2026-08-29T16:35:07.539310+00:00",
        "presence_class": "dark",
        "severity": "alarm",
        "gap_days": 11,
        "last_food_log_date": None,
        "last_manual_log_date": "2026-08-24",
        "channels_quiet": ["habits", "food", "training", "journal"],
        "channels_quiet_count": 4,
        "passive_still_flowing": True,
        "planned_pause": False,
        "planned_pause_reason": "",
        "returned": False,
        "resumed_after_days": None,
        "phase": "experiment",
        "experiment_window_start": "2026-08-17",
        "channel_detail": {
            "macrofactor": {"label": "food", "last_log_date": None, "gap_days": 11, "dropout_streak_days": 11},
            "habitify": {"label": "habits", "last_log_date": None, "gap_days": 11, "dropout_streak_days": 11},
            "hevy": {"label": "training", "last_log_date": None, "gap_days": 11, "dropout_streak_days": 11},
            "notion": {"label": "journal", "last_log_date": None, "gap_days": 11, "dropout_streak_days": 11},
            "withings": {"label": "measurement", "last_log_date": "2026-08-24", "gap_days": 4, "dropout_streak_days": 4},
        },
    }


LICENSED_TRUTH = ("food", "journal")  # macrofactor 0, notion 0 — the true absences
WITHHELD_TRUTH = ("habits", "training")  # habitify 12 records, strava 2 — the false ones


# ─────────────────────────────────────────────────────────────────────────────
# 1. The split itself: the artifact's four claims, graded
# ─────────────────────────────────────────────────────────────────────────────
class TestTheStoredArtifactSplit:
    def test_two_of_four_claims_are_withheld(self):
        split = sourced_quiet_channels(stored_artifact())
        assert tuple(sorted(split.licensed)) == LICENSED_TRUTH
        assert tuple(sorted(split.withheld)) == WITHHELD_TRUTH

    def test_training_is_withheld_because_the_denominator_was_short(self):
        """The registry names apple_health/hevy/strava for `workout`; the presence
        record consulted only hevy. UNSOURCED, and the note names who was skipped."""
        split = sourced_quiet_channels(stored_artifact())
        notes = " ".join(split.notes)
        assert "strava" in notes
        assert "never consulted" in notes or "was never consulted" in notes

    def test_habits_is_withheld_because_no_source_evidences_it(self):
        """Habitify's scheduled pull writes a row every day regardless of behaviour —
        the registry carries no `evidence_for` on it, so a public "no habits logged"
        cannot be established from ingest evidence at all."""
        split = sourced_quiet_channels(stored_artifact())
        assert "habits" in split.withheld
        assert any("habits" in n and "cannot be established" in n for n in split.notes)

    def test_the_two_true_absences_survive(self):
        """The negative control: withholding must not lobotomise the honest claims.
        MacroFactor and Notion are behavioural, in-denominator, consulted, silent —
        their silence IS the absence, and deleting it would be its own ADR-104 lie."""
        split = sourced_quiet_channels(stored_artifact())
        assert "food" in split.licensed
        assert "journal" in split.licensed


# ─────────────────────────────────────────────────────────────────────────────
# 2. The board's generation input (the surface that published the false sentence)
# ─────────────────────────────────────────────────────────────────────────────
class TestPresencePromptBlock:
    def test_unlicensed_labels_never_join_the_quiet_sentence(self):
        block = presence_prompt_block(stored_artifact())
        quiet_lines = [ln for ln in block.splitlines() if "Channels with no current logs" in ln]
        assert quiet_lines, "the licensed quiet sentence must still exist — two absences are true"
        assert "training" not in quiet_lines[0]
        assert "habits" not in quiet_lines[0]
        assert "food" in quiet_lines[0] and "journal" in quiet_lines[0]

    def test_withheld_labels_are_forbidden_not_softened(self):
        block = presence_prompt_block(stored_artifact())
        assert "do NOT say he logged nothing for: habits, training" in block

    def test_the_food_sentence_is_scoped_to_food(self):
        """The old branch said "NOTHING has been logged this cycle" off a food-only
        fact — the same short-denominator defect in its most absolute form."""
        block = presence_prompt_block(stored_artifact())
        assert "NO FOOD has been logged this cycle" in block
        assert "NOTHING has been logged" not in block


# ─────────────────────────────────────────────────────────────────────────────
# 3. The other wired narrative surfaces, replaying the same artifact
# ─────────────────────────────────────────────────────────────────────────────
class TestCoachBriefSurface:
    def test_brief_carries_licensed_and_unverified_apart(self):
        from coach.coach_narrative_orchestrator import _engagement_for_brief

        brief = _engagement_for_brief(stored_artifact())
        assert brief is not None
        assert tuple(sorted(brief["channels_quiet"])) == LICENSED_TRUTH
        assert tuple(sorted(brief["channels_unverified"])) == WITHHELD_TRUTH


class TestStateOfMatthewSurface:
    def test_weekly_narration_payload_carries_the_split(self):
        from compute.state_of_matthew_lambda import gather_presence_section

        section = gather_presence_section(stored_artifact())
        assert section is not None
        assert tuple(sorted(section["channels_quiet"])) == LICENSED_TRUTH
        assert tuple(sorted(section["channels_unverified"])) == WITHHELD_TRUTH
        assert "never assert them" in section["note"]


class TestCheckinSnapshotSurface:
    def test_mcp_checkin_snapshot_carries_the_split(self, monkeypatch):
        import mcp.tools_coach_checkin as tcc

        class _FakeTable:
            def get_item(self, Key):
                assert Key["sk"] == "STATE#current"
                return {"Item": stored_artifact()}

        monkeypatch.setattr(tcc, "_table_ref", _FakeTable())
        snap = tcc._presence_snapshot()
        assert tuple(sorted(snap["channels_quiet"])) == LICENSED_TRUTH
        assert tuple(sorted(snap["channels_unverified"])) == WITHHELD_TRUTH
        assert "Never ask about them" in snap["channels_unverified_note"]


# ─────────────────────────────────────────────────────────────────────────────
# 4. The lift glyph (`/api/pulse`) — the second live instance
# ─────────────────────────────────────────────────────────────────────────────
class TestLiftGlyph:
    def test_hevy_alone_does_not_license_the_category_claim(self):
        """The defect replay: consult only hevy (what the old code did) and the
        registry denominator refuses the "no training" claim."""
        grading = absence_sourcing("workout", sources_observed=("hevy",), window_start="2026-08-17")
        assert not grading.licenses_absence
        assert "strava" in grading.unchecked

    def test_full_denominator_with_live_pipes_licenses_it(self):
        grading = absence_sourcing(
            "workout",
            sources_observed=("hevy", "strava", "apple_health"),
            source_last_dates={"apple_health": "2026-08-29"},
            window_start="2026-08-17",
        )
        assert grading.licenses_absence

    def test_unlicensed_label_states_the_record_not_the_absence(self):
        from web.site_api_pulse import _lift_absence_label

        assert _lift_absence_label(64, "2026-06-25", False, 12, "2026-08-17") == "Last session 2026-06-25"
        assert _lift_absence_label(None, None, False, 12, "2026-08-17") == "No session on file"

    def test_licensed_label_keeps_the_honest_category_claim(self):
        from web.site_api_pulse import _lift_absence_label

        assert "No training logged — 5 days" in _lift_absence_label(5, "2026-08-24", True, 12, "2026-08-17")

    def test_workout_evidence_consults_every_denominator_source(self):
        """The sweep replaying the live 08-29 state: hevy last 06-25, strava trained
        08-17/08-18, apple_health reporting daily with no workout minutes. The category
        answer is strava's date — 11 days, not hevy's 64 — and every consulted source
        is named on the wire."""
        from web.site_api_pulse import _workout_evidence

        today = "2026-08-29"
        ah_rows = [{"sk": f"DATE#{(date(2026, 8, 29) - timedelta(days=n)).isoformat()}", "steps": 5000} for n in range(0, 10)]
        table = _FakePulseTable(
            {
                "USER#matthew#SOURCE#hevy": [{"sk": "DATE#2026-06-25"}],
                "USER#matthew#SOURCE#strava": [{"sk": "DATE#2026-08-17"}, {"sk": "DATE#2026-08-18"}],
                "USER#matthew#SOURCE#apple_health": ah_rows,
            }
        )
        last, consulted, liveness = _workout_evidence(table, today)
        assert last == "2026-08-18", "strava's record, not hevy's, is the category answer"
        assert set(consulted) == {"hevy", "strava", "apple_health"}
        assert liveness["apple_health"] == "2026-08-29"

    def test_workout_evidence_finds_apple_health_workout_fields(self):
        """An Apple Health workout with no behavioural log anywhere still counts —
        the field predicate, not row existence, is its evidence (#3294 registry facet)."""
        from web.site_api_pulse import _workout_evidence

        table = _FakePulseTable(
            {
                "USER#matthew#SOURCE#apple_health": [
                    {"sk": "DATE#2026-08-20", "steps": 4000, "recovery_workout_minutes": 25},
                    {"sk": "DATE#2026-08-21", "steps": 4000},
                ],
            }
        )
        last, consulted, _ = _workout_evidence(table, "2026-08-29")
        assert last == "2026-08-20"
        assert "apple_health" in consulted


class _FakePulseTable:
    """Answers table.query() from a {pk: [items]} fixture (the test_pulse_* idiom):
    matches Key("pk").eq(...) and an optional sk BETWEEN range, honours descending
    order and Limit."""

    def __init__(self, by_pk):
        self.by_pk = by_pk

    @staticmethod
    def _find_pk(cond):
        vals = getattr(cond, "_values", None)
        if vals is None:
            return None
        for v in vals:
            got = _FakePulseTable._find_pk(v) if hasattr(v, "_values") else (v if isinstance(v, str) else None)
            if isinstance(got, str) and got.startswith("USER#"):
                return got
        return None

    @staticmethod
    def _find_sk_range(cond):
        vals = getattr(cond, "_values", None)
        if vals is None:
            return None
        key = vals[0] if vals else None
        if getattr(key, "name", None) == "sk" and getattr(cond, "expression_operator", None) == "BETWEEN" and len(vals) == 3:
            return (vals[1], vals[2])
        for v in vals:
            if hasattr(v, "_values"):
                found = _FakePulseTable._find_sk_range(v)
                if found:
                    return found
        return None

    def query(self, **kwargs):
        cond = kwargs.get("KeyConditionExpression")
        pk = self._find_pk(cond) if cond is not None else None
        sk_range = self._find_sk_range(cond) if cond is not None else None
        items = list(self.by_pk.get(pk, []))
        if sk_range:
            lo, hi = sk_range
            items = [i for i in items if lo <= str(i.get("sk", "")) <= hi]
        if kwargs.get("ScanIndexForward") is False:
            items = sorted(items, key=lambda i: str(i.get("sk", "")), reverse=True)
        limit = kwargs.get("Limit")
        return {"Items": items[:limit] if limit else items}


# ─────────────────────────────────────────────────────────────────────────────
# 5. THE ENUMERATION — derived from the tree, never hand-asserted "it's wired"
# ─────────────────────────────────────────────────────────────────────────────

# Every module allowed to touch the raw field, with its disposition. A reader absent
# from this map fails the set-equality test below — a NEW consumer cannot fork the
# raw list without either wiring through the ONE address or writing its reason here.
_DISPOSITIONS = {
    "lambdas/ai/absence_sourcing.py": "check",  # the check itself reads the signal
    "lambdas/content/engagement_core.py": "wired",  # producer + the ONE address + prompt block
    "lambdas/coach/coach_narrative_orchestrator.py": "wired",
    "lambdas/compute/state_of_matthew_lambda.py": "wired",
    "mcp/tools_coach_checkin.py": "wired",
    # Publishes len(channels_quiet) only — a channel-level count that names no
    # category and asserts no "he did not do X"; the licensing check adjudicates
    # category-level absence claims, which a bare count is not.
    "lambdas/web/site_api_freshness.py": "count_only",
}

_WIRED_CALLS = {"sourced_quiet", "sourced_quiet_channels", "quiet_fields_for_brief"}


def _modules_reading_channels_quiet():
    """Every shipped module whose AST contains the string constant `channels_quiet`."""
    found = {}
    for base in ("lambdas", "mcp"):
        for path in sorted((_REPO / base).rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            if any(isinstance(n, ast.Constant) and n.value == "channels_quiet" for n in ast.walk(tree)):
                found[str(path.relative_to(_REPO))] = tree
    return found


class TestCoverageEnumeration:
    def test_every_reader_has_a_disposition(self):
        """Set equality, both directions: an unlisted reader is an unwired surface;
        a listed non-reader is a stale enumeration lying about coverage."""
        readers = set(_modules_reading_channels_quiet())
        assert readers == set(_DISPOSITIONS), (
            f"readers without a disposition: {sorted(readers - set(_DISPOSITIONS))}; "
            f"stale dispositions: {sorted(set(_DISPOSITIONS) - readers)} — a new consumer of the raw "
            "channels_quiet field must route through content.engagement_core.sourced_quiet (the ONE "
            "address) or document why it is out of the licensing check's scope, here."
        )

    def test_wired_modules_actually_call_the_one_address(self):
        """ "Wired" is a claim about the AST, not about this file's opinion."""
        trees = _modules_reading_channels_quiet()
        for mod, disposition in _DISPOSITIONS.items():
            if disposition != "wired":
                continue
            calls = {
                n.func.id if isinstance(n.func, ast.Name) else getattr(n.func, "attr", None)
                for n in ast.walk(trees[mod])
                if isinstance(n, ast.Call)
            }
            assert calls & _WIRED_CALLS, f"{mod} is marked wired but never calls {_WIRED_CALLS}"

    def test_count_only_modules_never_touch_the_list_itself(self):
        """site_api_freshness may publish a count; the moment the raw list value
        escapes a len() there, it becomes a narrative input and must wire through
        the check. Structural: every `channels_quiet` constant in the module sits
        inside a len(...) call."""
        trees = _modules_reading_channels_quiet()
        for mod, disposition in _DISPOSITIONS.items():
            if disposition != "count_only":
                continue
            offending = []
            for node in ast.walk(trees[mod]):
                if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "len"):
                    continue
                for inner in ast.walk(node):
                    if isinstance(inner, ast.Constant) and inner.value == "channels_quiet":
                        offending.append(id(inner))
            all_reads = [id(n) for n in ast.walk(trees[mod]) if isinstance(n, ast.Constant) and n.value == "channels_quiet"]
            assert set(all_reads) <= set(offending), f"{mod}: raw channels_quiet escapes its len()-only license"

    def test_the_glyph_surface_consults_the_licensing_check(self):
        """The second instance's pin: site_api_pulse's absence label is gated on an
        absence_sourcing verdict, and the payload discloses the consulted sources —
        "the check reached this surface" is readable from the wire."""
        src = (_REPO / "lambdas" / "web" / "site_api_pulse.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        calls = {
            n.func.id if isinstance(n.func, ast.Name) else getattr(n.func, "attr", None) for n in ast.walk(tree) if isinstance(n, ast.Call)
        }
        assert "absence_sourcing" in calls, "the glyph path no longer consults the check"
        keys = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
        assert "absence_sources_checked" in keys and "absence_licensed" in keys


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
