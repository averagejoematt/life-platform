"""tests/test_ai_output_validator_behavior.py — safety-tier behavior for the
post-generation AI output validator (lambdas/ai_output_validator.py, AI-3).

This is the last gate before AI coaching reaches a reader: it BLOCKs empty /
truncated output, dangerous training recs against a red recovery score, and
dangerously-low calorie guidance; it WARNs on correlation-as-causation framing
and hallucinated metrics. Pre-#1658 only three narrow hallucination cases were
tested — the BLOCK tiers (the injury/safety-critical ones) had zero coverage.

All checks are deterministic; every test passes an explicit health_context so no
DynamoDB autoload is involved (and conftest pins AI_VALIDATOR_AUTOLOAD=off).
"""

from ai import ai_output_validator as v
from ai.ai_output_validator import AIOutputType, validate_ai_output

# ── BLOCK tier ───────────────────────────────────────────────────────────────


def test_empty_output_blocked_with_typed_fallback():
    r = validate_ai_output("", AIOutputType.BOD_COACHING, {})
    assert r.blocked
    assert "Empty" in r.block_reason
    # sanitized_text swaps in the type-specific safe fallback.
    assert r.sanitized_text == r.safe_fallback == v._fallback_for_type(AIOutputType.BOD_COACHING)
    assert r.sanitized_text  # non-empty


def test_whitespace_only_output_blocked():
    assert validate_ai_output("      \n\t ", AIOutputType.TLDR, {}).blocked


def test_too_short_output_blocked():
    r = validate_ai_output("ok", AIOutputType.GUIDANCE, {}, min_length=10)
    assert r.blocked
    assert "too short" in r.block_reason.lower()


def test_truncated_output_blocked():
    r = validate_ai_output(
        "You should really focus on your training consistency this week and",
        AIOutputType.TRAINING_COACH,
        {},
    )
    assert r.blocked
    assert "truncated" in r.block_reason.lower()


def test_dangerous_training_with_red_recovery_blocked():
    r = validate_ai_output(
        "You should push hard with HIIT today and go all out on the bike.",
        AIOutputType.TRAINING_COACH,
        {"recovery_score": 20},
    )
    assert r.blocked
    assert "red recovery" in r.block_reason.lower()
    # Fallback must steer to rest, not training.
    assert "rest" in r.safe_fallback.lower()


def test_dangerous_low_calorie_nutrition_blocked():
    r = validate_ai_output(
        "Try to eat only 500 calories today to lose weight fast.",
        AIOutputType.NUTRITION_COACH,
        {},
    )
    assert r.blocked
    assert "calorie" in r.block_reason.lower()


def test_calorie_deficit_context_is_not_blocked():
    # "800 calorie deficit" is legitimate guidance, not a starvation target.
    r = validate_ai_output(
        "Aim for an 800 calorie deficit this week for steady, sustainable loss.",
        AIOutputType.NUTRITION_COACH,
        {},
    )
    assert not r.blocked


# ── #2215: per-item macro labelling vs. a daily starvation target ────────────
# The low-calorie BLOCK could not tell a recipe card's per-serving macro line
# apart from "eat 500 calories today", so every prompt-compliant Weekly Plate
# edition was replaced by the nutritionist-warning fallback. These four pin the
# distinction from BOTH sides — the permissive direction is only safe while the
# blocking direction below still fires.


def test_a_per_serving_macro_line_is_not_a_starvation_recommendation():
    """The shape weekly_plate's own SYSTEM_PROMPT demands on every recipe card."""
    r = validate_ai_output(
        "<div><strong>Smoky Turkey Kofte Bowls</strong><div>520 cal · 42P / 30C / 18F · weeknight easy</div></div>",
        AIOutputType.NUTRITION_COACH,
        {},
    )
    assert not r.blocked, r.block_reason


def test_an_explicit_per_serving_qualifier_is_not_a_starvation_recommendation():
    r = validate_ai_output(
        "Charred cabbage tacos come in around 450 kcal per serving and freeze well for lunches.",
        AIOutputType.NUTRITION_COACH,
        {},
    )
    assert not r.blocked, r.block_reason


def test_a_daily_framing_still_blocks_even_when_dressed_as_a_macro_line():
    """The exemption must not be buyable: annotating a starvation target with
    macros is still a starvation target."""
    r = validate_ai_output(
        "Your target for today: 500 cal · 40P / 30C / 10F. Stick to it every day this week.",
        AIOutputType.NUTRITION_COACH,
        {},
    )
    assert r.blocked
    assert "calorie" in r.block_reason.lower()


def test_a_recipe_cards_macros_do_not_exempt_a_bare_low_target_on_the_next_line():
    """The exemption is per-figure and segment-local: one card's macro line must
    not launder a starvation figure written in the next element. No daily-intake
    wording here on purpose — the segment clipping is what has to catch it."""
    r = validate_ai_output(
        "<div>Smoky Turkey Kofte Bowls — 520 cal · 42P / 30C / 18F</div>" "<div>And to speed things up, try 600 cal on rest days.</div>",
        AIOutputType.NUTRITION_COACH,
        {},
    )
    assert r.blocked
    assert "600" in r.block_reason
    assert "520" not in r.block_reason


# ── #2216: a thousands separator is not a second figure ──────────────────────
# The confirming regex read the last three digits of "1,700 kcal" as its own
# 100-799 figure, so a nutrition panel reporting a perfectly normal weekly
# average was BLOCKED as a starvation prescription. Surfaced when nutrition_
# review's validation gate was switched on for the first time.


def test_a_thousands_separated_average_is_not_a_starvation_figure():
    r = validate_ai_output(
        "You averaged 1,700 kcal per day this week against your 1,800 target.",
        AIOutputType.NUTRITION_COACH,
        {},
    )
    assert not r.blocked, r.block_reason


def test_a_thousands_separated_figure_written_as_calories_is_also_safe():
    r = validate_ai_output(
        "Last week you averaged 2,100 calories per day; this week 1,750.",
        AIOutputType.NUTRITION_COACH,
        {},
    )
    assert not r.blocked, r.block_reason


def test_a_bare_low_daily_figure_is_still_blocked_after_the_separator_fix():
    """The separator fix must not open a hole: an un-separated 100-799 daily
    figure is exactly what Check 5 exists for."""
    r = validate_ai_output(
        "Eat only 600 calories per day this week and the scale will move fast.",
        AIOutputType.NUTRITION_COACH,
        {},
    )
    assert r.blocked
    assert "600" in r.block_reason


# ── WARN tier (used as-is, but flagged) ──────────────────────────────────────


def test_borderline_recovery_aggressive_language_warns_not_blocks():
    r = validate_ai_output(
        "You should push hard with HIIT today and go all out on the bike.",
        AIOutputType.TRAINING_COACH,
        {"recovery_score": 40},  # 34-50 borderline band
    )
    assert not r.blocked
    assert any("borderline recovery" in w for w in r.warnings)


def test_healthy_recovery_aggressive_language_passes():
    r = validate_ai_output(
        "You should push hard with HIIT today — you have the headroom for it.",
        AIOutputType.TRAINING_COACH,
        {"recovery_score": 70},
    )
    assert not r.blocked
    assert not any("recovery" in w for w in r.warnings)


def test_causation_language_warns():
    r = validate_ai_output(
        "The data clearly shows that this is causing your poor sleep quality lately.",
        AIOutputType.BOD_COACHING,
        {},
    )
    assert not r.blocked
    assert any("causation" in w.lower() for w in r.warnings)


def test_hallucinated_metric_warns_when_deviation_exceeds_tolerance():
    r = validate_ai_output(
        "Your recovery score is 40 percent, so let's take it easy and prioritise rest.",
        AIOutputType.BOD_COACHING,
        {"recovery_score": 80},  # text 40 vs actual 80 = 50% deviation > 25%
    )
    assert any("Hallucinated recovery score" in w for w in r.warnings)


def test_metric_within_tolerance_does_not_warn():
    r = validate_ai_output(
        "Your recovery score is 78 percent today, a solid green — build on it.",
        AIOutputType.BOD_COACHING,
        {"recovery_score": 80},  # 78 vs 80 = 2.5% deviation, within tolerance
    )
    assert not any("Hallucinated" in w for w in r.warnings)


# ── validate_json_output ─────────────────────────────────────────────────────


def test_validate_json_none_blocked():
    r = v.validate_json_output(None, ["training"], AIOutputType.TRAINING_COACH)
    assert r.blocked


def test_validate_json_missing_required_key_blocked():
    r = v.validate_json_output({"training": ""}, ["training"], AIOutputType.TRAINING_COACH)
    assert r.blocked
    assert "training" in r.block_reason


def test_validate_json_replaces_blocked_string_value_in_place():
    parsed = {"training": ""}  # empty → sub-validation blocks
    # 'training' present-but-empty is caught as a missing required key first; use a
    # too-short-but-present value to exercise the in-place safe-text replacement.
    parsed = {"nutrition": "x"}  # present, but sub-validation blocks as too-short
    r = v.validate_json_output(parsed, ["nutrition"], AIOutputType.NUTRITION_COACH)
    assert r.blocked
    # The failing value was swapped for the type's safe fallback in-place.
    assert parsed["nutrition"] == v._fallback_for_type(AIOutputType.NUTRITION_COACH)


def test_validate_json_valid_dict_passes():
    parsed = {
        "training": "Solid zone-2 session today; keep the effort conversational and steady throughout.",
        "nutrition": "Hit your protein target and stay within your calorie range for the day.",
    }
    r = v.validate_json_output(parsed, ["training", "nutrition"], AIOutputType.TRAINING_COACH)
    assert not r.blocked


# ── validate_daily_brief_outputs aggregation ─────────────────────────────────


def test_daily_brief_blocks_empty_bod_and_reports_it():
    out = v.validate_daily_brief_outputs(
        bod_insight="",  # blocked → fallback
        training_nutrition={"training": "Good steady effort today, keep it conversational.", "nutrition": "Hit protein."},
        journal_coach_text="Reflect on what worked and what you'd adjust tomorrow.",
        tldr_guidance={"tldr": "Rest well and recover fully today.", "guidance": ["Prioritise quality sleep tonight for recovery."]},
        health_context={},
    )
    assert out["bod_insight"] == v._fallback_for_type(AIOutputType.BOD_COACHING)
    assert any("[bod] BLOCKED" in w for w in out["validation_warnings"])
    # Non-blocked surfaces pass through unchanged.
    assert out["tldr_guidance"]["guidance"] == ["Prioritise quality sleep tonight for recovery."]


def test_daily_brief_blocked_journal_coach_is_reported():
    """#2918: jc_result had its .blocked flag set and acted on (fallback swapped in)
    but never reported — the operator's warning count undercounted. Inject the
    BLOCKED state through the real assembly path and assert it reaches the
    aggregate the brief reads."""
    out = v.validate_daily_brief_outputs(
        bod_insight="Solid recovery today; keep the intensity conversational and steady throughout the session.",
        training_nutrition={
            "training": "Good steady effort today, keep it conversational and controlled.",
            "nutrition": "Hit your protein target and stay within your calorie range today.",
        },
        journal_coach_text="",  # blocked → fallback, and MUST be reported
        tldr_guidance={"tldr": "Rest well and recover fully today.", "guidance": []},
        health_context={},
    )
    assert out["journal_coach_text"] == v._fallback_for_type(AIOutputType.JOURNAL_COACH)
    blocked_entries = [w for w in out["validation_warnings"] if "BLOCKED" in w]
    assert any(w.startswith("[journal_coach] BLOCKED:") for w in blocked_entries), out["validation_warnings"]
    # Exactly one output was blocked; exactly one BLOCKED entry may report it.
    assert len(blocked_entries) == 1


def test_daily_brief_journal_declared_absent_skips_block_path():
    """#2944 / ADR-104: when the caller declares the journal input absent (no
    entries to coach on — the 2026-08-20→08-22 live shape), the empty string is
    a behavioral absence, not an AI failure. It must NOT be blocked, must NOT
    be swapped for the fallback line (which implies coaching happened), and
    must NOT raise the operator's BLOCKED count."""
    out = v.validate_daily_brief_outputs(
        bod_insight="Solid recovery today; keep the intensity conversational and steady throughout the session.",
        training_nutrition={
            "training": "Good steady effort today, keep it conversational and controlled.",
            "nutrition": "Hit your protein target and stay within your calorie range today.",
        },
        journal_coach_text="",
        tldr_guidance={"tldr": "Rest well and recover fully today.", "guidance": []},
        health_context={},
        journal_coach_absent_reason="no journal entries for 2026-08-21",
    )
    assert out["journal_coach_text"] == ""  # honestly empty — no fabricated fallback
    assert out["journal_coach_text"] != v._fallback_for_type(AIOutputType.JOURNAL_COACH)
    assert not any(w.startswith("[journal_coach]") for w in out["validation_warnings"]), out["validation_warnings"]


def test_daily_brief_declared_absence_does_not_mask_other_blocks():
    """#2944 mutation guard against over-skipping: a declared journal absence
    must only exempt the journal seat — a genuinely-empty sibling output (here
    nutrition) still goes through the BLOCK path and is still reported."""
    out = v.validate_daily_brief_outputs(
        bod_insight="Solid recovery today; keep the intensity conversational and steady throughout the session.",
        training_nutrition={
            "training": "Good steady effort today, keep it conversational and controlled.",
            "nutrition": "",  # a real empty-output failure — must still block
        },
        journal_coach_text="",
        tldr_guidance={"tldr": "Rest well and recover fully today.", "guidance": []},
        health_context={},
        journal_coach_absent_reason="no journal entries for 2026-08-21",
    )
    blocked_entries = [w for w in out["validation_warnings"] if "BLOCKED" in w]
    assert len(blocked_entries) == 1
    assert blocked_entries[0].startswith("[nutrition] BLOCKED:")
    assert out["training_nutrition"]["nutrition"] == v._fallback_for_type(AIOutputType.NUTRITION_COACH)


def test_daily_brief_blocked_tldr_is_reported():
    """#2918: a suppressed TL;DR — the brief's headline — read as a healthy run
    ('All AI outputs passed validation'). A blocked tldr_result must surface in
    validation_warnings like its four siblings."""
    out = v.validate_daily_brief_outputs(
        bod_insight="Solid recovery today; keep the intensity conversational and steady throughout the session.",
        training_nutrition={
            "training": "Good steady effort today, keep it conversational and controlled.",
            "nutrition": "Hit your protein target and stay within your calorie range today.",
        },
        journal_coach_text="Reflect on what worked and what you'd adjust tomorrow.",
        tldr_guidance={"tldr": "", "guidance": []},  # blocked headline
        health_context={},
    )
    assert out["tldr_guidance"]["tldr"] == v._fallback_for_type(AIOutputType.TLDR)
    blocked_entries = [w for w in out["validation_warnings"] if "BLOCKED" in w]
    assert any(w.startswith("[tldr] BLOCKED:") for w in blocked_entries), out["validation_warnings"]
    assert len(blocked_entries) == 1


def test_daily_brief_blocked_count_equals_blocked_outputs():
    """#2918 acceptance: the blocked-output count the operator reads equals the
    number of outputs actually blocked. Reproduces the 2026-08-20 live shape
    (nutrition + journal both empty → 2 blocks) plus a blocked TL;DR → 3."""
    out = v.validate_daily_brief_outputs(
        bod_insight="Solid recovery today; keep the intensity conversational and steady throughout the session.",
        training_nutrition={
            "training": "Good steady effort today, keep it conversational and controlled.",
            "nutrition": "",  # blocked (the one that WAS reported on 2026-08-20)
        },
        journal_coach_text="",  # blocked (silent pre-fix)
        tldr_guidance={"tldr": "", "guidance": []},  # blocked (silent pre-fix)
        health_context={},
    )
    blocked_entries = [w for w in out["validation_warnings"] if "BLOCKED" in w]
    assert len(blocked_entries) == 3, out["validation_warnings"]
    tags = {w.split("]")[0] + "]" for w in blocked_entries}
    assert tags == {"[nutrition]", "[journal_coach]", "[tldr]"}


# ── #2918 structural guard: every validate_ai_output result must have its ────
# ── .blocked checked — guard the SET, not the instance ───────────────────────


def _daily_brief_blocked_coverage(src: str):
    """AST over validate_daily_brief_outputs (the idiom that found #2918):
    return (results assigned from validate_ai_output, names with an
    `if X.blocked` guard)."""
    import ast
    import textwrap

    fn = ast.parse(textwrap.dedent(src)).body[0]
    assigned, checked = set(), set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Assign):
            call = node.value
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "validate_ai_output":
                assigned.update(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, ast.If):
            for sub in ast.walk(node.test):
                if isinstance(sub, ast.Attribute) and sub.attr == "blocked" and isinstance(sub.value, ast.Name):
                    checked.add(sub.value.id)
    return assigned, checked


def test_daily_brief_every_validation_result_has_blocked_checked():
    """#2918: two of six results (jc_result, tldr_result) set .blocked, swapped
    in the fallback, and never reported. Structural guard so a seventh output
    added later cannot repeat this: every name bound to a validate_ai_output
    call inside validate_daily_brief_outputs must appear in an `if X.blocked`
    test somewhere in the function."""
    import inspect

    assigned, checked = _daily_brief_blocked_coverage(inspect.getsource(v.validate_daily_brief_outputs))
    # Self-check the instrument: the function creates six results today; if the
    # AST sweep ever finds none, the guard is measuring nothing (silent pass).
    assert len(assigned) >= 6, f"AST sweep found only {sorted(assigned)} — instrument broken?"
    unchecked = assigned - checked
    assert not unchecked, f"validate_ai_output results with .blocked never checked (the #2918 defect): {sorted(unchecked)}"


def test_daily_brief_blocked_guard_goes_red_on_mutation():
    """Mutation proof for the structural guard: strip one `if X.blocked` branch
    from the real source and the coverage sweep must report that name."""
    import inspect
    import re

    src = inspect.getsource(v.validate_daily_brief_outputs)
    mutated = re.sub(
        r"if jc_result\.blocked:\n\s*all_warnings\.append\([^\n]+\)\n",
        "",
        src,
    )
    assert mutated != src, "mutation did not apply — regex drifted from source"
    assigned, checked = _daily_brief_blocked_coverage(mutated)
    assert "jc_result" in assigned - checked


# ── small helpers ────────────────────────────────────────────────────────────


def test_is_truncated_heuristics():
    assert v._is_truncated("short")  # under 20 chars
    assert v._is_truncated("This is a long enough sentence but it ends with a conjunction and")
    assert not v._is_truncated("This is a complete, well-formed coaching sentence.")


def test_safe_float_none_and_garbage():
    assert v._safe_float(None) is None
    assert v._safe_float("not-a-number") is None
    assert v._safe_float("42.5") == 42.5


def test_fallback_for_type_is_nonempty_for_every_type():
    for t in AIOutputType:
        assert v._fallback_for_type(t), f"empty fallback for {t}"


def test_autoload_killswitch_returns_empty(monkeypatch):
    monkeypatch.setenv("AI_VALIDATOR_AUTOLOAD", "off")
    assert v._autoload_health_context() == {}
