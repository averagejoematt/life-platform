"""tests/test_adherence_calc.py — programmed-vs-performed."""

from __future__ import annotations

import pytest
from health import adherence_calc
from health.adherence_calc import calculate_adherence
from training import effort_ceilings
from training.routine_ir import ExerciseBlock, RoutineSpec, Set

# #5058: the program-default ceilings are the charter's (`effort_ceilings.by_movement_class`)
_COMPOUND_CEILING = effort_ceilings.ceiling(effort_ceilings.COMPOUNDS)
_LAST_ISOLATION_CEILING = effort_ceilings.ceiling(effort_ceilings.LAST_ISOLATION_SET)


def _ir() -> RoutineSpec:
    return RoutineSpec(
        routine_id="r-1",
        target_date="2026-06-01",
        archetype="upper",
        exercises=[
            ExerciseBlock(movement_key="db_bench_press_flat", sets=[Set(), Set(), Set()]),
            ExerciseBlock(movement_key="lat_pulldown", sets=[Set(), Set(), Set()]),
        ],
    )


def test_full_completion_is_100():
    # Hevy template IDs sourced from the live reconciled catalog (commit 989cbdf).
    performed = {
        "exercises": [
            {"exercise_template_id": "3601968B", "sets": [{}, {}, {}]},  # db_bench_press_flat
            {"exercise_template_id": "6A6C31A5", "sets": [{}, {}, {}]},  # lat_pulldown
        ]
    }
    result = calculate_adherence(_ir(), performed)
    assert result["overall_pct"] == 100.0
    assert result["per_muscle"]["chest"] == 100.0
    assert result["per_muscle"]["back"] == 100.0
    assert result["missing"] == []


def test_partial_completion_reports_per_muscle():
    performed = {
        "exercises": [
            {"exercise_template_id": "3601968B", "sets": [{}, {}]},  # 2 of 3
        ]
    }
    result = calculate_adherence(_ir(), performed)
    assert result["per_muscle"]["chest"] < 100.0
    assert result["per_muscle"]["back"] == 0.0
    assert "lat_pulldown" in result["missing"]


def test_extra_exercises_listed():
    performed = {
        "exercises": [
            {"exercise_template_id": "3601968B", "sets": [{}, {}, {}]},
            {"exercise_template_id": "6A6C31A5", "sets": [{}, {}, {}]},
            {"exercise_template_id": "DEADBEEF", "sets": [{}]},  # unprogrammed
        ]
    }
    result = calculate_adherence(_ir(), performed)
    assert "DEADBEEF" in result["extra"]


# ─────────────────────────────────────────────────────────────────────────────
# #3714 — adherence carries an INTENSITY dimension, not set-count alone.
#
# THE REGRESSION FIXTURE IS THE WIRE. Both sessions below are transcribed from live
# production on 2026-09-14:
#   • performed sets  — s3://matthew-life-platform/raw/hevy/{e5c2f877-…,a9abb0cf-…}.json
#                       (`type`/`rpe` verbatim, including the three `warmup` sets that
#                       open the 09-07 bench with no RPE at all)
#   • the prescription — DDB `USER#matthew#ROUTINE#947454183948792a30a5207ad212aca2`
#                       and `…#f2d24cf6a1a94159315095025ad7091f`, sk `VERSION#current`.
#                       The intensity-bearing clauses of `notes` are VERBATIM; the
#                       surrounding coaching prose is elided (it is not read by the
#                       calculator, and the fixture should not carry more of a private
#                       routine than the assertion needs).
# Both sessions were stored with `overall_pct: 100.0` and no intensity field of any
# kind — that stored row is the defect this file now pins.
# ─────────────────────────────────────────────────────────────────────────────


def _sets(*rpes, set_type="normal"):
    return [{"type": set_type, "rpe": r, "reps": 10, "weight_kg": 30.0} for r in rpes]


@pytest.fixture
def live_template_cache(monkeypatch):
    """`barbell_bench_press` is an ADR-069 title-resolved movement: it carries NO catalog
    hint on purpose, and its real Hevy id lives in `config/hevy_template_cache.json`,
    which is S3-resident and not in the repo. This is the live mapping (the id the
    2026-09-07 record actually carries), supplied so the fixture can keep the movement
    key the routine really used instead of substituting a hinted stand-in."""
    monkeypatch.setattr(
        adherence_calc,
        "_load_template_cache",
        lambda: {"movements": {"barbell_bench_press": {"hevy_template_id": "79D0BB3A"}}},
    )


def _push_0907_ir() -> RoutineSpec:
    """The routine actually pushed for 2026-09-07 — intensity prescribed in RIR."""
    return RoutineSpec(
        routine_id="947454183948792a30a5207ad212aca2",
        target_date="2026-09-08",
        archetype="push",
        notes=(
            "Day 1, Foundation block. High-rep push (WS4SB hi day). No failure sets today — session 1 of the block. "
            "RECOVERY BRANCH — use the LOWER of (Whoop band, how you feel); feel only downgrades. "
            "GREEN 67-100: climb bench toward 175 if set 1 is 4+ RIR, last set of incline + pushdown to 1-2 RIR. Still no failure sets."
        ),
        exercises=[
            ExerciseBlock(
                movement_key="barbell_bench_press",
                sets=[Set()] * 7,
                notes="PRIMARY. Ramp first: 45x10, 95x5, 115x3. Then 4x8 at 155. Target 3 RIR. "
                "PERFORMANCE-GATED: if set 1 moves at 4+ RIR, climb to 165-175 for the rest.",
            ),
            ExerciseBlock(
                movement_key="incline_db_press",
                sets=[Set()] * 3,
                notes="Upper chest — the flat bench under-hits it. 2s down, press up and slightly in. 3 RIR. 50 lb is a feeler.",
            ),
            ExerciseBlock(
                movement_key="db_lateral_raise", sets=[Set()] * 3, notes="Side delts. Strict. 4+ RIR, this is a pump not a grind."
            ),
        ],
    )


def _push_0907_performed() -> dict:
    return {
        "routine_id": "7f906e65-3362-4fef-bd86-52fbbf665eb3",
        "start_time": "2026-09-07T17:59:49+00:00",
        "exercises": [
            {  # barbell_bench_press — three warm-ups with NO rpe, then four working sets
                "exercise_template_id": "79D0BB3A",
                "sets": _sets(None, None, None, set_type="warmup") + _sets(6.0, 7.0, 7.0, 8.5),
            },
            {"exercise_template_id": "07B38369", "sets": _sets(8.5, 9.0, 10.0)},  # incline_db_press — RPE 10 = to failure
            {"exercise_template_id": "422B08F1", "sets": _sets(8.0, 8.0, 9.5)},  # db_lateral_raise
        ],
    }


def test_0907_session_trained_to_failure_does_not_report_full_adherence(live_template_cache):
    """THE MUST-FAIL TEST (#3714). Every programmed set was performed, so set-count
    adherence is a legitimate 100% — and the session was still not trained as
    prescribed: the plan said "No failure sets", 3 RIR (= RPE 7), and the incline
    press was logged at RPE 10. Before this change the whole record said 100.0 and
    nothing else."""
    result = calculate_adherence(_push_0907_ir(), _push_0907_performed())

    # The set-count dimension is unchanged and honestly 100 — and now says so by name.
    assert result["overall_pct"] == 100.0
    assert result["overall_pct_dimension"] == "sets_only"
    assert result["sets_adherence"]["pct"] == 100.0

    # The intensity dimension is the half that was missing.
    intensity = result["intensity_adherence"]
    assert intensity["status"] == "graded"
    assert intensity["pct"] is not None and intensity["pct"] < 100.0
    assert intensity["sets_over_ceiling"] >= 1
    assert "incline_db_press" in intensity["over_ceiling_movements"]

    # RPE 10 against a 3-RIR (RPE 7) prescription is a 3.0 overage, not a rounding wobble.
    incline = next(m for m in result["movements"] if m["movement_key"] == "incline_db_press")
    assert incline["pct"] == 100.0  # every set done
    assert incline["intensity"]["ceiling_rpe"] == 7.0
    assert incline["intensity"]["basis"] == "exercise_notes:rir"
    assert incline["intensity"]["max_rpe"] == 10.0
    assert incline["intensity"]["sets_over_ceiling"] == 3
    assert incline["intensity"]["max_overage"] == 3.0

    # And the one-line verdict a reader acts on.
    assert result["as_prescribed"]["verdict"] == "no"
    assert any("RPE ceiling" in r for r in result["as_prescribed"]["reasons"])


def test_0907_warmup_sets_are_not_graded_or_counted_absent(live_template_cache):
    """The bench opened 45x10 / 95x5 / 115x3 as `warmup` with no RPE. Grading those
    against a top-set ceiling — or reporting them as an RPE hole — would both be wrong."""
    result = calculate_adherence(_push_0907_ir(), _push_0907_performed())
    bench = next(m for m in result["movements"] if m["movement_key"] == "barbell_bench_press")
    assert bench["performed_sets"] == 7  # set COUNT still includes the warm-ups
    assert bench["intensity"]["working_sets"] == 4
    assert bench["intensity"]["sets_graded"] == 4
    assert bench["intensity"]["sets_rpe_absent"] == 0
    assert bench["intensity"]["ceiling_rpe"] == 7.0  # max(10-3, 10-4) — the permissive read
    assert bench["intensity"]["sets_over_ceiling"] == 1  # the 8.5


def test_0908_session_ceiling_falls_back_to_the_routines_own_session_note():
    """2026-09-08's routine note is literally "Pull, RPE 8 hard cap, nothing to failure."
    Movements that name no intensity of their own inherit that session ceiling — and the
    basis says so, so a session-wide fallback is never mistaken for a per-lift cap."""
    ir = RoutineSpec(
        routine_id="f2d24cf6a1a94159315095025ad7091f",
        target_date="2026-09-08",
        archetype="pull",
        notes="Pull, RPE 8 hard cap, nothing to failure. Lifting defends lean mass; the walk is the fat-loss lever.",
        exercises=[
            ExerciseBlock(movement_key="lat_pulldown", sets=[Set()] * 3, notes="RPE 8 cap. 120 lb anchored on 3 Sept (120x12,12,10)."),
            ExerciseBlock(movement_key="db_curl", sets=[Set()] * 3, notes="GREEN only: optional 4th set."),
        ],
    )
    performed = {
        "routine_id": "7da4dd70-546b-4522-bb48-11a9e4a8f1df",
        "start_time": "2026-09-08T17:30:00+00:00",
        "exercises": [
            {"exercise_template_id": "6A6C31A5", "sets": _sets(8.0, 7.5, 9.0)},  # lat_pulldown
            {"exercise_template_id": "37FCC2BB", "sets": _sets(8.5, 8.5, 8.5, 9.0)},  # db_curl — a 4th set, all over
        ],
    }
    result = calculate_adherence(ir, performed)

    lat = next(m for m in result["movements"] if m["movement_key"] == "lat_pulldown")
    assert lat["intensity"]["ceiling_rpe"] == 8.0
    assert lat["intensity"]["basis"] == "exercise_notes:rpe"
    assert lat["intensity"]["sets_beat_ceiling"] == 1

    curl = next(m for m in result["movements"] if m["movement_key"] == "db_curl")
    assert curl["intensity"]["ceiling_rpe"] == 8.0
    assert curl["intensity"]["basis"] == "routine_notes:rpe"  # inherited, and labelled as inherited
    assert curl["intensity"]["sets_beat_ceiling"] == 4

    assert result["overall_pct"] == 100.0
    # #5058: every set above the RPE-8 cap is within the charter's +1 tolerance — within_tolerance, never a breach
    assert lat["intensity"]["sets_over_ceiling"] == 0 and lat["intensity"]["sets_within_tolerance"] == 1
    assert curl["intensity"]["sets_over_ceiling"] == 0 and curl["intensity"]["sets_within_tolerance"] == 4
    assert result["as_prescribed"]["verdict"] == "yes"


def test_absent_rpe_is_absent_not_compliant():
    """ADR-104. A working set with no logged RPE never enters the within-ceiling
    numerator OR the denominator, and it blocks a clean "yes" on a movement that
    carried its own prescribed ceiling."""
    ir = RoutineSpec(
        routine_id="r-absent",
        target_date="2026-09-10",
        archetype="pull",
        notes="",
        exercises=[ExerciseBlock(movement_key="lat_pulldown", sets=[Set()] * 3, notes="RPE 8 cap.")],
    )
    performed = {"exercises": [{"exercise_template_id": "6A6C31A5", "sets": _sets(None, None, None)}]}
    result = calculate_adherence(ir, performed)

    lat = next(m for m in result["movements"] if m["movement_key"] == "lat_pulldown")
    assert lat["pct"] == 100.0  # every set completed
    assert lat["intensity"]["status"] == "unreadable"
    assert lat["intensity"]["pct_within_ceiling"] is None  # NOT 100
    assert lat["intensity"]["sets_rpe_absent"] == 3
    assert result["intensity_adherence"]["status"] == "unreadable"
    assert result["intensity_adherence"]["pct"] is None
    assert result["as_prescribed"]["verdict"] == "unknown"


def test_cardio_with_no_prescribed_intensity_stays_unprescribed_never_compliant():
    """A movement the program itself has nothing to say about intensity for — cardio,
    per `program_structure.classify_movement` — cannot grade one even after #4073's
    program-default fallback: it says `unprescribed` and returns a verdict of `unknown`.
    It does not invent a ceiling and it does not call the session compliant."""
    ir = RoutineSpec(
        routine_id="r-none",
        target_date="2026-09-10",
        archetype="pull",
        notes="Easy day.",
        exercises=[ExerciseBlock(movement_key="treadmill", sets=[Set()] * 3, notes="Full range of motion.")],
    )
    performed = {"exercises": [{"exercise_template_id": "243710DE", "sets": _sets(9.5, 9.5, 10.0)}]}  # treadmill's own hint id
    result = calculate_adherence(ir, performed)
    assert result["intensity_adherence"]["status"] == "unprescribed"
    assert result["intensity_adherence"]["pct"] is None
    assert result["intensity_adherence"]["sets_over_ceiling"] == 0
    assert result["as_prescribed"]["verdict"] == "unknown"


def test_a_session_trained_inside_its_ceiling_reads_yes():
    """The positive control — the verdict is reachable, not a gate that always says no."""
    ir = RoutineSpec(
        routine_id="r-good",
        target_date="2026-09-10",
        archetype="pull",
        notes="Pull, RPE 8 hard cap.",
        exercises=[ExerciseBlock(movement_key="lat_pulldown", sets=[Set()] * 3, notes="RPE 8 cap.")],
    )
    performed = {"exercises": [{"exercise_template_id": "6A6C31A5", "sets": _sets(7.0, 7.5, 8.0)}]}
    result = calculate_adherence(ir, performed)
    assert result["intensity_adherence"]["status"] == "graded"
    assert result["intensity_adherence"]["pct"] == 100.0
    assert result["intensity_adherence"]["sets_over_ceiling"] == 0
    assert result["as_prescribed"]["verdict"] == "yes"


# ─────────────────────────────────────────────────────────────────────────────
# #3929 — a Hevy template ALIAS (the same movement under two catalog template ids)
# resolves BEFORE missing/extra, instead of scoring one missing + one extra.
#
# Specimen (the issue's own): prescribed `21310F5F` ("Triceps Extension (Cable)") vs
# performed `B5EFBF9C` ("Overhead Triceps Extension (Cable)") — one physical movement,
# two Hevy catalog ids. The registry is `config/hevy_template_aliases.json`, seeded
# with exactly this pair; these tests exercise the SHIPPED config, not a synthetic one,
# except where a test is explicitly about the pre-fix (registry-absent) contrast.
#
# `tmpl:<id>` is the existing ADR-069 escape hatch in `_ir_movement_to_template` — used
# here so the specimen needs no `config/movement_catalog.json` entry of its own (the
# real Hevy catalog has no `movements` entry for either triceps-extension id today).
# ─────────────────────────────────────────────────────────────────────────────


def _triceps_alias_ir() -> RoutineSpec:
    return RoutineSpec(
        routine_id="r-alias",
        target_date="2026-09-15",
        archetype="push",
        exercises=[ExerciseBlock(movement_key="tmpl:21310F5F", sets=[Set(), Set(), Set()])],
    )


def _triceps_alias_performed() -> dict:
    return {"exercises": [{"exercise_template_id": "B5EFBF9C", "sets": [{}, {}, {}]}]}


def test_template_alias_resolves_before_missing_and_extra():
    """Acceptance: a planted alias pair yields ZERO missing/extra, under the shipped
    (not monkeypatched) registry."""
    result = calculate_adherence(_triceps_alias_ir(), _triceps_alias_performed())
    assert result["missing"] == []
    assert result["extra"] == []
    assert result["overall_pct"] == 100.0


def test_template_alias_fix_scores_at_or_above_the_broken_pre_fix_value(monkeypatch):
    """Before #3929, template_id was the ONLY join key, so this exact session scored
    one missing (`21310F5F` never seen performed) + one extra (`B5EFBF9C` never seen
    prescribed) — demonstrated here by forcing the pre-fix state (an empty registry)
    for contrast. The alias-resolved score must read AT OR ABOVE that broken value,
    never below it."""
    ir, performed = _triceps_alias_ir(), _triceps_alias_performed()
    real_load_aliases = adherence_calc._load_template_aliases

    monkeypatch.setattr(adherence_calc, "_load_template_aliases", lambda: {})
    broken = calculate_adherence(ir, performed)
    assert broken["missing"] == ["tmpl:21310F5F"]
    assert broken["extra"] == ["B5EFBF9C"]
    assert broken["overall_pct"] < 100.0

    monkeypatch.setattr(adherence_calc, "_load_template_aliases", real_load_aliases)
    fixed = calculate_adherence(ir, performed)
    assert fixed["overall_pct"] >= broken["overall_pct"]
    assert fixed["overall_pct"] == 100.0
    assert fixed["missing"] == []
    assert fixed["extra"] == []


def test_unresolvable_alias_movement_key_fails_open(monkeypatch):
    """An alias entry whose movement_key resolves to no template id (a bad config
    entry) must not raise — it fails open to pre-#3929 behavior rather than half-apply."""
    monkeypatch.setattr(adherence_calc, "_load_template_aliases", lambda: {"aliases": {"B5EFBF9C": "no_such_movement_key"}})
    result = calculate_adherence(_triceps_alias_ir(), _triceps_alias_performed())
    assert result["extra"] == ["B5EFBF9C"]
    assert "tmpl:21310F5F" in result["missing"]


# ── find_alias_candidates — the shrink-only-honest reporting tool ──────────────


def test_find_alias_candidates_surfaces_the_specimen_pair_unconfirmed():
    titles = {"21310F5F": "Triceps Extension (Cable)", "B5EFBF9C": "Overhead Triceps Extension (Cable)"}
    candidates = adherence_calc.find_alias_candidates(titles, known_aliases={})
    assert candidates == [{"normalized_title": "triceps extension (cable)", "template_ids": ["21310F5F", "B5EFBF9C"]}]


def test_find_alias_candidates_excludes_an_already_confirmed_pair():
    """Shrink-only-honest: once the registry confirms a pairing, it drops out of the
    candidate list — the residue is exactly what still needs a human decision. Nothing
    here writes the registry; this only proves the candidate report shrinks to match it."""
    titles = {"21310F5F": "Triceps Extension (Cable)", "B5EFBF9C": "Overhead Triceps Extension (Cable)"}
    candidates = adherence_calc.find_alias_candidates(titles, known_aliases={"B5EFBF9C": "tmpl:21310F5F"})
    assert candidates == []


def test_find_alias_candidates_never_merges_a_genuinely_different_movement():
    """Negative control: incline vs flat bench are DIFFERENT movements (see
    `config/movement_catalog.json` — different default rep ranges, different primary
    emphasis) — the conservative modifier word list must not fold them together."""
    titles = {"3601968B": "Bench Press (Dumbbell)", "07B38369": "Incline Bench Press (Dumbbell)"}
    assert adherence_calc.find_alias_candidates(titles) == []


# ─────────────────────────────────────────────────────────────────────────────
# #4073 — a set with no PRESCRIBED ceiling grades against the program's own
# class-level default (`training.program_structure.EXPOSURES`) instead of dropping out
# of the intensity dimension entirely.
# ─────────────────────────────────────────────────────────────────────────────


def test_accessory_with_no_prescribed_ceiling_defaults_to_rpe_9_and_lowers_adherence():
    """THE ISSUE'S OWN SPECIMEN (#4073): an isolation accessory with no exercise/routine
    RPE note, logged at RPE 9.5, used to read `status: unprescribed` and drop out of the
    intensity dimension entirely — so an RPE-9.5 isolation set never touched the verdict.
    The movement is the SAME triceps-extension alias pair #3929 already resolves (`tmpl:
    21310F5F` prescribed, `B5EFBF9C` performed — the shipped, not monkeypatched, registry),
    so this one fixture proves BOTH halves of #4073 at once: the alias still resolves
    (zero missing/extra) AND the unprescribed ceiling now grades."""
    ir = RoutineSpec(
        routine_id="r-accessory-default",
        target_date="2026-09-15",
        archetype="push",
        exercises=[ExerciseBlock(movement_key="tmpl:21310F5F", sets=[Set(), Set(), Set()])],
    )
    performed = {"exercises": [{"exercise_template_id": "B5EFBF9C", "sets": _sets(9.5, 9.0, 8.0)}]}
    result = calculate_adherence(ir, performed)

    # Alias resolution (#3929) still holds — this is not a regression of that fix.
    assert result["missing"] == []
    assert result["extra"] == []
    assert result["overall_pct"] == 100.0  # set-count dimension: every set done

    movement = result["movements"][0]
    assert movement["intensity"]["ceiling_rpe"] == _COMPOUND_CEILING  # #5058: the charter's, earlier sets at the compounds band
    assert movement["intensity"]["last_set_ceiling_rpe"] == _LAST_ISOLATION_CEILING  # and the last set at the isolation band
    assert movement["intensity"]["basis"] == "program_default:accessory"
    assert movement["intensity"]["status"] == "graded"
    assert movement["intensity"]["sets_beat_ceiling"] == 1  # the 9.5 on the first set

    assert result["intensity_adherence"]["status"] == "graded"
    # THE MUST-FAIL LINE: before #4073 this read "unprescribed" and the composite verdict
    # was "unknown" no matter how high the logged RPE went — the 93%-reads-fine bug the
    # owner traced across 8 coaching sessions 2026-09-14 -> 09-22. #5058: the 9.5 is within
    # the charter's +1, so it is graded and NOT a breach.
    assert result["as_prescribed"]["verdict"] == "yes"
    assert movement["intensity"]["sets_within_tolerance"] == 1


def test_accessory_default_breach_still_grades_no_when_the_tolerance_is_zero(monkeypatch):
    """#5058 mutation control on the #4073 specimen: with the charter's tolerance at 0 the 9.5 IS a breach —
    the tolerance is the only thing that moved the verdict, read from the charter, never typed."""
    from training import load_progression

    real = load_progression.charter_value
    monkeypatch.setattr(
        load_progression, "charter_value", lambda p, d=None: 0 if p == "effort_ceilings.overage_tolerance_rpe" else real(p, d)
    )
    ir = RoutineSpec(
        routine_id="r-accessory-default",
        target_date="2026-09-15",
        archetype="push",
        exercises=[ExerciseBlock(movement_key="tmpl:21310F5F", sets=[Set(), Set(), Set()])],
    )
    result = calculate_adherence(ir, {"exercises": [{"exercise_template_id": "B5EFBF9C", "sets": _sets(9.5, 9.0, 8.0)}]})
    assert result["movements"][0]["intensity"]["sets_over_ceiling"] == 1
    assert result["as_prescribed"]["verdict"] == "no"
    assert any("RPE ceiling" in r for r in result["as_prescribed"]["reasons"])


def test_anchor_pattern_with_no_prescribed_ceiling_defaults_to_the_charter_compounds_ceiling():
    """An anchor-pattern movement (vertical pull, via `lat_pulldown`'s catalog title)
    with no exercise/routine note defaults to the charter's compounds ceiling (#5058; the
    heavy exposure's top_rpe 8 before) rather than being left ungraded."""
    ir = RoutineSpec(
        routine_id="r-anchor-default",
        target_date="2026-09-10",
        archetype="pull",
        notes="Easy day.",
        exercises=[ExerciseBlock(movement_key="lat_pulldown", sets=[Set()] * 3, notes="Full range of motion.")],
    )
    performed = {"exercises": [{"exercise_template_id": "6A6C31A5", "sets": _sets(9.5, 9.5, 10.0)}]}
    result = calculate_adherence(ir, performed)

    lat = result["movements"][0]
    assert lat["intensity"]["ceiling_rpe"] == _COMPOUND_CEILING
    assert lat["intensity"]["basis"] == "program_default:anchor:vertical_pull"
    assert lat["intensity"]["last_set_ceiling_rpe"] is None  # a compound reads one band for every set
    assert lat["intensity"]["sets_beat_ceiling"] == 3
    assert result["intensity_adherence"]["status"] == "graded"
    # 9.5 / 9.5 / 10 against RPE 9: all three beat it, none by more than the charter's +1
    assert lat["intensity"]["sets_over_ceiling"] == 0 and result["as_prescribed"]["verdict"] == "yes"


def test_program_default_never_overrides_an_explicit_routine_ceiling():
    """Mutation control: the default is a FALLBACK applied only when `resolve_ceiling`
    found nothing. A routine that DID name a ceiling keeps its own number even though the
    movement also classifies to a program default that would read differently (8.0)."""
    ir = RoutineSpec(
        routine_id="r-explicit-wins",
        target_date="2026-09-10",
        archetype="pull",
        notes="",
        exercises=[ExerciseBlock(movement_key="lat_pulldown", sets=[Set()] * 3, notes="RPE 6 cap.")],
    )
    performed = {"exercises": [{"exercise_template_id": "6A6C31A5", "sets": _sets(7.0, 7.0, 7.0)}]}
    result = calculate_adherence(ir, performed)
    lat = result["movements"][0]
    assert lat["intensity"]["ceiling_rpe"] == 6.0  # the routine's OWN number, not the 8.0 anchor default
    assert lat["intensity"]["basis"] == "exercise_notes:rpe"
    assert lat["intensity"]["sets_beat_ceiling"] == 3  # every set (7.0) over the explicit 6.0 cap


def test_movement_with_no_resolvable_title_still_stays_unprescribed():
    """Mutation control on the OTHER side of #4073: a movement_key the catalog and the
    alias registry both carry no title for cannot be classified, so it gets no default
    either — ADR-104's "the plan never said" must stay legible when the program truly has
    nothing to say, not only for the cardio case."""
    ir = RoutineSpec(
        routine_id="r-no-title",
        target_date="2026-09-15",
        archetype="push",
        exercises=[ExerciseBlock(movement_key="tmpl:FFFFFFFF", sets=[Set(), Set()])],
    )
    performed = {"exercises": [{"exercise_template_id": "FFFFFFFF", "sets": _sets(9.8, 9.9)}]}
    result = calculate_adherence(ir, performed)
    movement = result["movements"][0]
    assert movement["intensity"]["status"] == "unprescribed"
    assert movement["intensity"]["ceiling_rpe"] is None


def test_a_tmpl_movement_the_catalog_knows_by_template_id_gets_the_default_and_its_muscle():
    """LIVE SPECIMEN (2026-09-23, deployed c1e902a9): the 09-22 legs session keyed its
    movements `tmpl:<id>`, and 7 of 9 read `status: unprescribed, basis: null` with
    `per_muscle: {unknown: 100}` — the #4108 catalog holds these templates by NAME with the id
    as `hevy_template_id_hint`, and the resolver only looked the catalog up by movement_key.
    `tmpl:75A4F6C4` is Leg Extension (Machine) in the shipped catalog."""
    ir = RoutineSpec(
        routine_id="r-tmpl-hint",
        target_date="2026-09-22",
        archetype="legs",
        exercises=[ExerciseBlock(movement_key="tmpl:75A4F6C4", sets=[Set(), Set(), Set()])],
    )
    performed = {"exercises": [{"exercise_template_id": "75A4F6C4", "sets": _sets(8.0, 9.0, 9.5)}]}
    result = calculate_adherence(ir, performed)

    movement = result["movements"][0]
    assert movement["intensity"]["basis"] == "program_default:accessory", movement
    assert movement["intensity"]["ceiling_rpe"] == _COMPOUND_CEILING
    assert movement["intensity"]["sets_beat_ceiling"] == 0  # 8 / 9 under 9, the last set's 9.5 under the isolation 10
    assert result["per_muscle"] == {"quadriceps": 100.0}, result["per_muscle"]


# ─────────────────────────────────────────────────────────────────────────────
# #4160 — a routine note that NAMES a movement scopes to it, not the whole session.
#
# LIVE SPECIMEN (verbatim, 09-24, routine `b1b9960468f374e30dcdeca8630dd18f`, Hevy
# workout `3ca1117e…`): "Upper/Lower blk 1 - Lower-heavy. Squat novel-again: exposure 1
# of 3, RPE 7 max." Before this fix `resolve_ceiling` read the whole block as a
# SESSION-WIDE RPE-7 ceiling: RDL, leg press, leg curl and calf press were all graded
# against 7 instead of their own program-default ceiling (v0.3 accessories default to
# RPE 9 per #4102/#4073; the hinge/squat anchor families default to RPE 8), and the
# session read 15 sets over ceiling and 11.8% adherence.
# ─────────────────────────────────────────────────────────────────────────────


def _live_0924_lower_ir() -> RoutineSpec:
    return RoutineSpec(
        routine_id="b1b9960468f374e30dcdeca8630dd18f",
        target_date="2026-09-24",
        archetype="lower",
        notes="Upper/Lower blk 1 - Lower-heavy. Squat novel-again: exposure 1 of 3, RPE 7 max.",
        exercises=[
            ExerciseBlock(movement_key="squat_barbell", sets=[Set()] * 3),
            ExerciseBlock(movement_key="romanian_deadlift_barbell", sets=[Set()] * 3),
            ExerciseBlock(movement_key="leg_press", sets=[Set()] * 3),
            ExerciseBlock(movement_key="leg_curl", sets=[Set()] * 3),
            ExerciseBlock(movement_key="calf_raise_machine", sets=[Set()] * 3),
        ],
    )


def _catalog_hint(movement_key: str) -> str:
    """The performed template id FOR a planned key, read from the catalog the resolver reads —
    never a hand-copied hint (#4176 remapped leg_curl/calf_raise_machine and a literal here went
    red on main the same night)."""
    import json

    from common.repo_config import config_path

    with open(config_path("movement_catalog.json")) as f:
        return json.load(f)["movements"][movement_key]["hevy_template_id_hint"]


def _live_0924_lower_performed() -> dict:
    rpes = {
        "squat_barbell": (7.0, 7.5, 8.5),
        "romanian_deadlift_barbell": (7.5, 8.0, 8.5),
        "leg_press": (7.5, 8.0, 8.5),
        "leg_curl": (8.5, 9.0, 9.5),
        "calf_raise_machine": (8.5, 9.0, 9.5),
    }
    return {"exercises": [{"exercise_template_id": _catalog_hint(k), "sets": _sets(*v)} for k, v in rpes.items()]}


def test_named_routine_note_caps_only_the_named_movement():
    """The squat — the movement the clause names — keeps the routine's own RPE 7 cap."""
    result = calculate_adherence(_live_0924_lower_ir(), _live_0924_lower_performed())
    squat = next(m for m in result["movements"] if m["movement_key"] == "squat_barbell")
    assert squat["intensity"]["basis"] == "routine_notes:rpe"
    assert squat["intensity"]["ceiling_rpe"] == 7.0
    assert squat["intensity"]["sets_beat_ceiling"] == 2  # 7.5 and 8.5; the 7.0 set is AT cap, not over


@pytest.mark.parametrize(
    "movement_key,expected_basis,expected_ceiling",
    [
        ("romanian_deadlift_barbell", "program_default:anchor:hinge", _COMPOUND_CEILING),
        ("leg_press", "program_default:anchor:squat", _COMPOUND_CEILING),
        ("leg_curl", "program_default:accessory", _COMPOUND_CEILING),
        ("calf_raise_machine", "program_default:accessory", _COMPOUND_CEILING),
    ],
)
def test_named_routine_note_does_not_cap_the_other_movements(movement_key, expected_basis, expected_ceiling):
    """MUTATION CONTROL: this is the regression #4160 fixes. If the routine-note clause
    is ever made session-wide again (the name dropped, or the scoping check removed),
    EVERY one of these movements reads `basis: "routine_notes:rpe"` and
    `ceiling_rpe: 7.0` instead of its own program-default ceiling — this test goes red
    the moment that happens."""
    result = calculate_adherence(_live_0924_lower_ir(), _live_0924_lower_performed())
    movement = next(m for m in result["movements"] if m["movement_key"] == movement_key)
    assert movement["intensity"]["basis"] == expected_basis, movement
    assert movement["intensity"]["ceiling_rpe"] == expected_ceiling, movement
    # #5058: at the charter's ceilings (compounds 9, an isolation movement's last set 10) none of 8.5 / 9.5 is over
    assert movement["intensity"]["sets_beat_ceiling"] == 0


def test_named_routine_note_session_rollup_reflects_the_scoped_ceilings():
    """Before #4160: 14 of 15 sets read "over ceiling" (session-wide RPE 7), ~6.7%
    adherence. After: only the sets over each movement's OWN ceiling are flagged."""
    result = calculate_adherence(_live_0924_lower_ir(), _live_0924_lower_performed())
    intensity = result["intensity_adherence"]
    assert intensity["status"] == "graded"
    assert intensity["sets_graded"] == 15
    # #5058: only the squat's two sets beat its own RPE 7 — 7.5 within the charter's +1, 8.5 a breach
    assert intensity["sets_beat_ceiling"] == 2 and intensity["sets_over_ceiling"] == 1 and intensity["sets_within_tolerance"] == 1
    assert intensity["pct"] == 93.3
    assert result["as_prescribed"]["verdict"] == "no"


def test_the_template_id_lookup_is_exact_and_case_insensitive():
    catalog = {"movements": {"leg_extension_machine": {"title": "Leg Extension (Machine)", "hevy_template_id_hint": "75A4F6C4"}}}
    assert adherence_calc._catalog_entry_for("tmpl:75a4f6c4", catalog)["title"] == "Leg Extension (Machine)"
    assert adherence_calc._catalog_entry_for("tmpl:75A4F6C", catalog) == {}  # a prefix is not a match
    assert adherence_calc._catalog_entry_for("leg_extension_machine", catalog)["title"] == "Leg Extension (Machine)"
    assert adherence_calc._catalog_entry_for("unknown_key", catalog) == {}


def test_5058_a_session_beaten_only_within_tolerance_reads_yes():
    """#5058: every set above the RPE-8 note but within the charter's +1 — within_tolerance, the verdict `yes`."""
    ir = RoutineSpec(
        routine_id="r-5058",
        target_date="2026-10-20",
        archetype="upper",
        exercises=[ExerciseBlock(movement_key="lat_pulldown", sets=[Set()] * 3, notes="RPE 8 cap.")],
    )
    performed = {"exercises": [{"exercise_template_id": "6A6C31A5", "sets": _sets(8.5, 9.0, 9.0)}]}
    out = calculate_adherence(ir, performed)
    lat = out["movements"][0]["intensity"]
    assert lat["sets_within_tolerance"] == 3 and lat["sets_over_ceiling"] == 0 and lat["movement_class"] == "compound"
    assert out["intensity_adherence"]["sets_beat_ceiling"] == 3
    assert out["as_prescribed"]["verdict"] == "yes"


# ─────────────────────────────────────────────────────────────────────────────
# #5058 (owner ruling 2026-10-23): "grade lifting and cardio separately. An un-RPE'd cardio block shows `unknown` on
# its own and no longer hides the lifting verdict." The 2026-10-21 session: every lifting set inside its ceiling, one
# cycling block that carried its own RPE ceiling with no RPE logged — the whole session read `unknown`.
# ─────────────────────────────────────────────────────────────────────────────
def _lift_and_ride_ir() -> RoutineSpec:
    return RoutineSpec(
        routine_id="r-5058-split",
        target_date="2026-10-21",
        archetype="upper",
        exercises=[
            ExerciseBlock(movement_key="lat_pulldown", sets=[Set()] * 3, notes="RPE 8 cap."),
            ExerciseBlock(movement_key="cycling", sets=[Set(duration_seconds=1200)], notes="Easy ride, RPE 6 max."),
        ],
    )


def _ride(rpe=None):
    return {"exercise_template_id": "D8F7F851", "sets": [{"type": "normal", "rpe": rpe, "duration_seconds": 1200}]}  # cycling


def test_5058_an_unrpe_d_cardio_block_is_unknown_on_its_own_and_the_lifting_verdict_stands():
    performed = {"exercises": [{"exercise_template_id": "6A6C31A5", "sets": _sets(7.0, 7.5, 8.0)}, _ride()]}
    out = calculate_adherence(_lift_and_ride_ir(), performed)
    kinds = {m["movement_key"]: m["kind"] for m in out["movements"]}
    assert kinds == {"lat_pulldown": "lifting", "cycling": "cardio"}
    by = out["as_prescribed_by_kind"]
    assert by["lifting"]["verdict"] == "yes" and by["lifting"]["movements"] == ["lat_pulldown"]
    assert by["cardio"]["verdict"] == "unknown" and by["cardio"]["intensity_status"] == "unreadable"
    assert by["cardio"]["movements"] == ["cycling"]
    assert out["as_prescribed"]["verdict"] == "yes" and out["as_prescribed"]["scope"] == "lifting"
    assert out["as_prescribed"]["cardio_verdict"] == "unknown" and "cardio graded on its own" in out["as_prescribed"]["cardio_note"]
    # mutation control: the pre-ruling whole-session AND over the same movements is the `unknown` the 10-21 session read
    whole = adherence_calc._as_prescribed(out["overall_pct"], out["intensity_adherence"], out["movements"])
    assert whole["verdict"] == "unknown" and "cycling" in whole["reasons"][0]


def test_5058_a_lifting_breach_still_reads_no_beside_cardio_and_a_skipped_ride_never_fails_the_lift():
    over = {"exercises": [{"exercise_template_id": "6A6C31A5", "sets": _sets(9.5, 9.5, 9.5)}, _ride(5.0)]}
    out = calculate_adherence(_lift_and_ride_ir(), over)
    assert out["as_prescribed"]["verdict"] == "no" and out["as_prescribed_by_kind"]["cardio"]["verdict"] == "yes"
    assert "cardio_verdict" not in out["as_prescribed"]  # a `yes` ride is not a line on the lifting verdict
    skipped = calculate_adherence(_lift_and_ride_ir(), {"exercises": [{"exercise_template_id": "6A6C31A5", "sets": _sets(7.0, 7.5, 8.0)}]})
    assert skipped["as_prescribed"]["verdict"] == "yes" and skipped["as_prescribed_by_kind"]["cardio"]["verdict"] == "no"
    assert skipped["overall_pct"] < 100.0  # the stored whole-session number keeps its meaning


def test_5058_a_cardio_only_day_and_a_lifting_only_day_read_as_before():
    ride_only = RoutineSpec(
        routine_id="r-5058-ride",
        target_date="2026-10-21",
        archetype="aerobic",
        exercises=[ExerciseBlock(movement_key="cycling", sets=[Set(duration_seconds=1200)], notes="Easy ride, RPE 6 max.")],
    )
    out = calculate_adherence(ride_only, {"exercises": [_ride()]})
    assert out["as_prescribed"]["scope"] == "cardio" and out["as_prescribed"]["verdict"] == "unknown"
    assert out["as_prescribed_by_kind"]["lifting"] is None
    lift_only = calculate_adherence(_ir(), {"exercises": [{"exercise_template_id": "3601968B", "sets": [{}, {}, {}]}]})
    whole = adherence_calc._as_prescribed(lift_only["overall_pct"], lift_only["intensity_adherence"], lift_only["movements"])
    assert {k: lift_only["as_prescribed"][k] for k in ("verdict", "reasons")} == whole  # no cardio: the same verdict as before
    assert lift_only["as_prescribed"]["scope"] == "lifting" and lift_only["as_prescribed_by_kind"]["cardio"] is None


# ─────────────────────────────────────────────────────────────────────────────
# #5374: the performed clock shape (his own note grammar) graded against the composed note's clock rule, beside the
# cardio verdict — never folded into it. His 10-25 note, verbatim, is the fixture.
# ─────────────────────────────────────────────────────────────────────────────
_OWNER_NOTE_5374 = "8/12 for 2 mins for 20 mins / 8/14 for 2 mins for 20 mins / 8 level up every 2 mins from 40 to 60 to level 18"


def _ride_5374(notes):
    return {"exercise_template_id": "D8F7F851", "notes": notes, "sets": [{"type": "normal", "duration_seconds": 3600}]}  # cycling


def _ir_5374(notes):
    return RoutineSpec(
        routine_id="r-5374",
        target_date="2026-10-26",
        archetype="upper",
        exercises=[ExerciseBlock(movement_key="cycling", sets=[Set(duration_seconds=3600)], notes=notes)],
    )


def test_5374_adherence_grades_the_performed_shape_against_the_prescribed_one():
    from training import cardio_note

    note, _ = cardio_note.compose(movement_key="cycling", minutes=60, target_date="2026-10-26", kind="intervals", facts={"last_level": 8})
    out = calculate_adherence(_ir_5374(note), {"exercises": [_ride_5374(_OWNER_NOTE_5374)]})
    grade = out["as_prescribed_by_kind"]["cardio"]["shape"]["cycling"]
    hard = 8 + cardio_note.INTERVAL_LEVEL_STEP
    assert grade["status"] == "same_shape" and grade["minutes_delta"] == 0
    assert grade["performed"]["top_level"] == 18 and grade["prescribed"]["top_level"] == hard
    assert grade["top_level_delta"] == 18 - hard
    assert out["as_prescribed_by_kind"]["cardio"]["verdict"] == "unknown"  # the RPE half is still unread: never folded in
    # every absence is named
    blank = calculate_adherence(_ir_5374(note), {"exercises": [_ride_5374("")]})
    assert blank["as_prescribed_by_kind"]["cardio"]["shape"]["cycling"]["status"] == "performed_unread"
    prose = calculate_adherence(_ir_5374("Easy ride, RPE 6 max."), {"exercises": [_ride_5374(_OWNER_NOTE_5374)]})
    assert prose["as_prescribed_by_kind"]["cardio"]["shape"]["cycling"]["status"] == "prescribed_unread"


# ─────────────────────────────────────────────────────────────────────────────
# #5374 (10-26, 10-28): a cardio SWAP. The routine prescribed a cycling hills ride; he walked the treadmill instead and
# noted "3.5 incline / 3.2 speed". The treadmill landed only as a template id in `extra` and the cycling block read
# `performed_unread` — the note he wrote for the engine was never read. The treadmill row below is the 10-28 Hevy
# /v1/workouts exercise item verbatim (raw/hevy, workout 0adcac0c); the lift row and the routine are synthetic.
# ─────────────────────────────────────────────────────────────────────────────
_TREADMILL_1028 = {
    "index": 5,
    "title": "Treadmill",
    "notes": "3.5 incline / 3.2 speed",
    "exercise_template_id": "243710DE",
    "superset_id": None,
    "sets": [
        {
            "index": 0,
            "type": "normal",
            "weight_kg": None,
            "reps": None,
            "distance_meters": 2527,
            "duration_seconds": 1800,
            "rpe": None,
            "custom_metric": None,
        }
    ],
}
_LIFT_ROW_5374 = {
    "index": 0,
    "title": "Lat Pulldown (Cable)",
    "notes": None,
    "exercise_template_id": "6A6C31A5",
    "sets": _sets(7.0, 7.5, 8.0),
}


def _hills_note_5374(minutes=30):
    from training import cardio_note

    note, _ = cardio_note.compose(movement_key="cycling", minutes=minutes, target_date="2026-10-28", kind="hills", facts={"last_level": 11})
    return note


def _swap_ir_5374(*cardio_keys):
    return RoutineSpec(
        routine_id="r-5374-swap",
        target_date="2026-10-28",
        archetype="lower",
        exercises=[ExerciseBlock(movement_key="lat_pulldown", sets=[Set()] * 3, notes="RPE 8 cap.")]
        + [ExerciseBlock(movement_key=k, sets=[Set(duration_seconds=1800)], notes=_hills_note_5374()) for k in cardio_keys],
    )


def _verdicts(out):
    """Every verdict-bearing field of an adherence record — what the swap read must leave untouched."""
    by = out["as_prescribed_by_kind"]
    return {
        "as_prescribed": out["as_prescribed"],
        "by_kind": {
            k: (None if v is None else {f: v[f] for f in ("verdict", "reasons", "sets_pct", "intensity_status", "movements")})
            for k, v in by.items()
        },
        "overall_pct": out["overall_pct"],
        "intensity_adherence": out["intensity_adherence"],
        "missing": out["missing"],
        "extra": out["extra"],
    }


def _without_extra_read(monkeypatch, ir, performed):
    """The pre-fix record: the same session with the extra-cardio read switched off (the mutation control)."""
    with monkeypatch.context() as m:
        m.setattr(adherence_calc, "_extra_cardio_shapes", lambda *a, **k: {})
        return calculate_adherence(ir, performed)


def test_5374_a_machine_swap_reads_the_performed_note_against_the_prescribed_clock(monkeypatch):
    ir = _swap_ir_5374("cycling")
    performed = {"exercises": [_LIFT_ROW_5374, _TREADMILL_1028]}
    out = calculate_adherence(ir, performed)
    shape = out["as_prescribed_by_kind"]["cardio"]["shape"]
    tread = shape["treadmill"]
    assert tread["substituted_for"] == "cycling" and tread["template_id"] == "243710DE"
    assert tread["performed"]["family"] == "steady" and tread["performed"]["speed_mph"] == 3.2
    assert tread["performed"]["levels"] == [3.5] and tread["performed"]["unit"] == "%" and tread["performed"]["total_min"] == 30
    assert tread["prescribed"]["family"] == "hills" and tread["prescribed"]["unit"] == "level"
    assert tread["status"] == "different_shape" and tread["minutes_delta"] == 0
    # a bike level minus a treadmill incline % is not a number: the pair is named, no level delta is emitted
    assert tread["units_differ"] == ["level", "%"]
    assert "mean_level_delta" not in tread and "top_level_delta" not in tread
    assert shape["cycling"]["status"] == "performed_unread" and shape["cycling"]["substituted_by"] == "treadmill"
    # mutation control: the pre-fix record never read the treadmill note, and every verdict is identical either way
    before = _without_extra_read(monkeypatch, ir, performed)
    assert "treadmill" not in before["as_prescribed_by_kind"]["cardio"]["shape"]
    assert _verdicts(before) == _verdicts(out)
    assert out["missing"] == ["cycling"] and out["extra"] == ["243710DE"]


def test_5374_a_day_without_a_swap_reads_as_before(monkeypatch):
    ir = _swap_ir_5374("cycling")
    ride = {
        "index": 1,
        "title": "Cycling",
        "notes": "Level 11 flat",
        "exercise_template_id": "D8F7F851",
        "sets": [{"type": "normal", "duration_seconds": 1800}],
    }
    for performed in ({"exercises": [_LIFT_ROW_5374, ride]}, {"exercises": [_LIFT_ROW_5374]}):
        out = calculate_adherence(ir, performed)
        before = _without_extra_read(monkeypatch, ir, performed)
        assert out == before  # nothing extra performed on a cardio machine: the record is byte-identical to the pre-fix one
        assert set(out["as_prescribed_by_kind"]["cardio"]["shape"]) == {"cycling"}
        assert "substituted_by" not in out["as_prescribed_by_kind"]["cardio"]["shape"]["cycling"]


def test_5374_an_ambiguous_swap_is_unprogrammed_never_a_guess(monkeypatch):
    elliptical = {
        "index": 6,
        "title": "Elliptical Trainer",
        "notes": "Level 6",
        "exercise_template_id": "3303376C",
        "sets": [{"type": "normal", "duration_seconds": 600}],
    }
    cases = (
        ("two blocks missing", _swap_ir_5374("cycling", "rowing_machine"), {"exercises": [_LIFT_ROW_5374, _TREADMILL_1028]}),
        ("two machines added", _swap_ir_5374("cycling"), {"exercises": [_LIFT_ROW_5374, _TREADMILL_1028, elliptical]}),
    )
    offenders = []
    for name, ir, performed in cases:
        out = calculate_adherence(ir, performed)
        shape = out["as_prescribed_by_kind"]["cardio"]["shape"]
        tread = shape.get("treadmill") or {}
        if tread.get("status") != "unprogrammed" or "substituted_for" in tread or tread.get("prescribed") is not None:
            offenders.append(f"{name}: treadmill read {tread}")
        if (tread.get("performed") or {}).get("speed_mph") != 3.2:
            offenders.append(f"{name}: his treadmill note was not read ({tread.get('performed')})")
        if any("substituted_by" in (v or {}) for v in shape.values()):
            offenders.append(f"{name}: a programmed block was named as replaced")
        if _verdicts(out) != _verdicts(_without_extra_read(monkeypatch, ir, performed)):
            offenders.append(f"{name}: a verdict moved")
    assert not offenders, offenders
