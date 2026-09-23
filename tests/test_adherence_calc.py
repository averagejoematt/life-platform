"""tests/test_adherence_calc.py — programmed-vs-performed."""

from __future__ import annotations

import pytest
from health import adherence_calc
from health.adherence_calc import calculate_adherence
from training.routine_ir import ExerciseBlock, RoutineSpec, Set


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
    assert lat["intensity"]["sets_over_ceiling"] == 1

    curl = next(m for m in result["movements"] if m["movement_key"] == "db_curl")
    assert curl["intensity"]["ceiling_rpe"] == 8.0
    assert curl["intensity"]["basis"] == "routine_notes:rpe"  # inherited, and labelled as inherited
    assert curl["intensity"]["sets_over_ceiling"] == 4

    assert result["overall_pct"] == 100.0
    assert result["as_prescribed"]["verdict"] == "no"


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
    performed = {"exercises": [{"exercise_template_id": "B5EFBF9C", "sets": _sets(8.0, 9.0, 9.5)}]}
    result = calculate_adherence(ir, performed)

    # Alias resolution (#3929) still holds — this is not a regression of that fix.
    assert result["missing"] == []
    assert result["extra"] == []
    assert result["overall_pct"] == 100.0  # set-count dimension: every set done

    movement = result["movements"][0]
    assert movement["intensity"]["ceiling_rpe"] == 9.0
    assert movement["intensity"]["basis"] == "program_default:accessory"
    assert movement["intensity"]["status"] == "graded"
    assert movement["intensity"]["sets_over_ceiling"] == 1  # the 9.5

    assert result["intensity_adherence"]["status"] == "graded"
    assert result["intensity_adherence"]["pct"] is not None and result["intensity_adherence"]["pct"] < 100.0
    # THE MUST-FAIL LINE: before #4073 this read "unprescribed" and the composite verdict
    # was "unknown" no matter how high the logged RPE went — the 93%-reads-fine bug the
    # owner traced across 8 coaching sessions 2026-09-14 -> 09-22.
    assert result["as_prescribed"]["verdict"] == "no"
    assert any("RPE ceiling" in r for r in result["as_prescribed"]["reasons"])


def test_anchor_pattern_with_no_prescribed_ceiling_defaults_to_the_heavy_top_rpe():
    """An anchor-pattern movement (vertical pull, via `lat_pulldown`'s catalog title)
    with no exercise/routine note defaults to the heavy exposure's top_rpe ceiling (8) —
    the tightest numeric ceiling `program_structure.EXPOSURES` names — rather than the
    accessory default, and rather than being left ungraded."""
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
    assert lat["intensity"]["ceiling_rpe"] == 8.0
    assert lat["intensity"]["basis"] == "program_default:anchor:vertical_pull"
    assert lat["intensity"]["sets_over_ceiling"] == 3
    assert result["intensity_adherence"]["status"] == "graded"
    assert result["as_prescribed"]["verdict"] == "no"


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
    assert lat["intensity"]["sets_over_ceiling"] == 3  # every set (7.0) over the explicit 6.0 cap


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
    assert movement["intensity"]["ceiling_rpe"] == 9.0
    assert movement["intensity"]["sets_over_ceiling"] == 1
    assert result["per_muscle"] == {"quadriceps": 100.0}, result["per_muscle"]


def test_the_template_id_lookup_is_exact_and_case_insensitive():
    catalog = {"movements": {"leg_extension_machine": {"title": "Leg Extension (Machine)", "hevy_template_id_hint": "75A4F6C4"}}}
    assert adherence_calc._catalog_entry_for("tmpl:75a4f6c4", catalog)["title"] == "Leg Extension (Machine)"
    assert adherence_calc._catalog_entry_for("tmpl:75A4F6C", catalog) == {}  # a prefix is not a match
    assert adherence_calc._catalog_entry_for("leg_extension_machine", catalog)["title"] == "Leg Extension (Machine)"
    assert adherence_calc._catalog_entry_for("unknown_key", catalog) == {}
