"""tests/test_chronicle_data_packet.py — behavioral coverage for
``lambdas/emails/chronicle_data.py`` (the weekly gather + narrative packet
builder split out of wednesday_chronicle_lambda.py in #1654). Part of the
#1658 coverage-floor ratchet.

What is actually asserted here (no import smoke, no `is not None` filler):

  * ``build_calendar_facts`` — the deterministic date→weekday grounding block
    (#1220): every day in the window labelled, the genesis tagged exactly once
    whether it sits inside or outside the window, and hard-fail → "".
  * ``build_data_packet`` — driven with small hand-built fixtures and asserted
    on the rendered text: genesis-anchored week arithmetic at the week-1/week-2
    boundary, the pre-genesis (prologue) branch, the weight story, the
    per-source empty branches, journal truncation + signal rendering, the
    character-sheet progression/level-event/stable branches, and the ADR-142
    consent gating (a non-consented row renders NOTHING; a consented row
    renders sanctioned fields only, never its private text).
  * ``gather_chronicle_data`` / ``_load_engagement_signal`` — driven through a
    hand-written ``_g`` facade dict (the production facade passes ``globals()``)
    plus a hand-written DynamoDB stub. Deliberately NOT MagicMock: the gather
    iterates query results, and a self-propagating mock has OOM'd the CI runner.

Time discipline: ``gather_chronicle_data`` derives its window from
``datetime.now(timezone.utc)``, so every gather test freezes the module clock.
No test mixes a fixture date with a live now() — that combination is a time
bomb that reds main months later.

All content in these fixtures is obviously-synthetic placeholder text.

Run with:   python3 -m pytest tests/test_chronicle_data_packet.py -q
"""

import os
import sys
from datetime import datetime, timezone
from decimal import Decimal

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

from emails import chronicle_data as cd  # noqa: E402
from pacific_clock import freeze_pacific  # #2817: the Pacific clock a converted module actually reads
from privacy import diary_consent  # noqa: E402

# The genesis every packet fixture is anchored to. Explicit — never read off the
# wall clock, never off constants (a re-anchor must not silently move these
# hand-derived week numbers).
GENESIS = "2026-08-03"  # a Monday


# ══════════════════════════════════════════════════════════════════════════════
# Hand-written stubs (no MagicMock — see module docstring)
# ══════════════════════════════════════════════════════════════════════════════


class _StubLogger:
    def __init__(self):
        self.info_msgs = []
        self.warning_msgs = []
        self.error_msgs = []

    def info(self, msg, *a, **k):
        self.info_msgs.append(str(msg))

    def warning(self, msg, *a, **k):
        self.warning_msgs.append(str(msg))

    def error(self, msg, *a, **k):
        self.error_msgs.append(str(msg))


def _pk_from_condition(cond):
    """Pull the COACH# partition out of a boto3 Key condition tree.

    The conversation-reference gather builds its KeyConditionExpression as a
    boto3 condition object (not a ":pk" placeholder), so the stub has to read
    the partition back out to answer per-coach.
    """
    get_expr = getattr(cond, "get_expression", None)
    if get_expr is None:
        return None
    for value in get_expr().get("values", ()):
        if isinstance(value, str) and value.startswith("COACH#"):
            return value
        found = _pk_from_condition(value)
        if found:
            return found
    return None


class _StubTable:
    """Minimal DynamoDB Table stand-in: query() answers by partition key,
    get_item() answers by (pk, sk). Both can be told to raise, so the module's
    fail-soft except-branches can be exercised."""

    def __init__(self, *, items_by_pk=None, items_by_key=None, query_error=None, get_error=None):
        self.items_by_pk = items_by_pk or {}
        self.items_by_key = items_by_key or {}
        self.query_error = query_error
        self.get_error = get_error
        self.query_kwargs = []
        self.get_keys = []

    def query(self, **kwargs):
        self.query_kwargs.append(kwargs)
        if self.query_error:
            raise self.query_error
        pk = (kwargs.get("ExpressionAttributeValues") or {}).get(":pk")
        if pk is None:
            pk = _pk_from_condition(kwargs.get("KeyConditionExpression"))
        return {"Items": list(self.items_by_pk.get(pk, []))}

    def get_item(self, Key=None, **kwargs):  # noqa: N803 — boto3's parameter name
        self.get_keys.append(Key)
        if self.get_error:
            raise self.get_error
        item = self.items_by_key.get((Key["pk"], Key["sk"]))
        return {"Item": item} if item is not None else {}


def _make_g(*, table=None, profile=None, ranges=None, lists=None, genesis=GENESIS, logger=None):
    """The `_g` facade hand-off. Production passes wednesday_chronicle_lambda's
    globals(); the module only ever reads the keys built here."""
    ranges = ranges or {}
    lists = lists or {}
    range_calls = []

    def query_range(source, start_date, end_date):
        range_calls.append((source, start_date, end_date))
        return dict(ranges.get(source, {}))

    def query_range_list(source, start_date, end_date):
        range_calls.append((source, start_date, end_date))
        return [dict(r) for r in lists.get(source, [])]

    return {
        "query_range": query_range,
        "query_range_list": query_range_list,
        "fetch_profile": lambda: profile,
        "table": table if table is not None else _StubTable(),
        "USER_ID": "matthew",
        "USER_PREFIX": "USER#matthew#SOURCE#",
        "EXPERIMENT_START_DATE": genesis,
        "logger": logger if logger is not None else _StubLogger(),
        # test-only handles (the module never reads these)
        "_range_calls": range_calls,
    }


class _FrozenClock(datetime):
    """datetime subclass with a pinned now(). Every gather test installs this so
    the derived window is hand-checkable instead of wall-clock dependent."""

    FIXED = datetime(2026, 8, 12, 17, 30, tzinfo=timezone.utc)  # a Wednesday, ISO 2026-W33

    @classmethod
    def now(cls, tz=None):
        return cls.FIXED if tz is None else cls.FIXED.astimezone(tz)


def _freeze(monkeypatch):
    monkeypatch.setattr(cd, "datetime", _FrozenClock)
    freeze_pacific(monkeypatch, cd, _FrozenClock)  # #2817: pin the PACIFIC helpers this module now calls
    # today = 2026-08-12 → end = yesterday, start = 7 days back, weights 30 back
    return {"start": "2026-08-05", "end": "2026-08-11", "weight_start": "2026-07-13"}


# ══════════════════════════════════════════════════════════════════════════════
# Packet fixtures
# ══════════════════════════════════════════════════════════════════════════════


def _empty_data(*, start="2026-08-05", end="2026-08-11", profile=None):
    """A structurally complete week with no data in it — the missing-source path."""
    return {
        "profile": profile if profile is not None else {"journey_start_date": GENESIS},
        "dates": {"start": start, "end": end},
        "whoop": {},
        "eightsleep": {},
        "garmin": {},
        "strava": {},
        "withings": {},
        "macrofactor": {},
        "apple_health": {},
        "journal_entries": [],
        "day_grades": {},
        "habit_scores": {},
        "habitify": {},
        "state_of_mind": {},
        "supplements": {},
        "experiments": [],
        "anomalies": {},
        "weather": {},
        "character_sheet": {},
        "prev_installments": [],
        "conversation_refs": [],
        "field_notes": None,
    }


# ══════════════════════════════════════════════════════════════════════════════
# build_calendar_facts (#1220 — deterministic weekday grounding)
# ══════════════════════════════════════════════════════════════════════════════


def test_calendar_facts_labels_every_day_and_appends_an_outside_genesis():
    out = cd.build_calendar_facts("2026-08-05", "2026-08-11", genesis=GENESIS)
    lines = out.split("\n")

    assert lines[0].startswith("=== CALENDAR")
    # 7 window days + the genesis, which falls OUTSIDE the window and is added
    assert len(lines) == 1 + 8
    # sorted ascending, genesis first because it predates the window
    assert lines[1] == "- 2026-08-03 was a Monday (experiment genesis)"
    assert lines[2] == "- 2026-08-05 was a Wednesday"
    assert lines[3] == "- 2026-08-06 was a Thursday"
    assert lines[-1] == "- 2026-08-11 was a Tuesday"
    # exactly one genesis tag
    assert sum("(experiment genesis)" in ln for ln in lines) == 1


def test_calendar_facts_genesis_inside_window_is_tagged_not_duplicated():
    out = cd.build_calendar_facts(GENESIS, "2026-08-05", genesis=GENESIS)
    lines = out.split("\n")[1:]

    assert lines == [
        "- 2026-08-03 was a Monday (experiment genesis)",
        "- 2026-08-04 was a Tuesday",
        "- 2026-08-05 was a Wednesday",
    ]


def test_calendar_facts_single_day_window_emits_one_day():
    out = cd.build_calendar_facts("2026-08-09", "2026-08-09")
    assert out.split("\n")[1:] == ["- 2026-08-09 was a Sunday"]


def test_calendar_facts_ignores_an_unparseable_genesis():
    out = cd.build_calendar_facts("2026-08-05", "2026-08-06", genesis="week-of-august")
    lines = out.split("\n")[1:]

    assert lines == ["- 2026-08-05 was a Wednesday", "- 2026-08-06 was a Thursday"]
    assert "genesis" not in out.split("\n", 1)[1]


def test_calendar_facts_returns_empty_string_on_bad_window_dates():
    assert cd.build_calendar_facts("08/05/2026", "2026-08-11") == ""
    assert cd.build_calendar_facts("2026-08-05", None) == ""
    assert cd.build_calendar_facts(None, None) == ""


# ══════════════════════════════════════════════════════════════════════════════
# build_data_packet — week arithmetic (genesis-anchored, #1086)
# ══════════════════════════════════════════════════════════════════════════════


def test_packet_week_one_at_the_seventh_day_after_genesis():
    """2026-08-03 genesis + week ending 2026-08-09 → Day 7 → still week 1."""
    text, week_num = cd.build_data_packet(_empty_data(start=GENESIS, end="2026-08-09"))

    assert week_num == 1
    assert "Week number: 1" in text
    assert f"Journey start (experiment genesis): {GENESIS}" in text
    assert "is Day 7 of the experiment — Week 1, Foundation stage" in text
    assert "Week ending: 2026-08-09" in text


def test_packet_rolls_to_week_two_on_the_eighth_day():
    """The boundary: one day later is Day 8 → week 2 (7-day weeks, genesis-anchored)."""
    text, week_num = cd.build_data_packet(_empty_data(start="2026-08-04", end="2026-08-10"))

    assert week_num == 2
    assert "Week number: 2" in text
    assert "is Day 8 of the experiment — Week 2, Foundation stage" in text


def test_packet_pre_genesis_window_publishes_as_week_one():
    """A lead-in dated before genesis has week_num 0 from the phase context; the
    packet still labels it week 1 (week_num feeds filenames/DDB keys)."""
    text, week_num = cd.build_data_packet(_empty_data(start="2026-07-25", end="2026-07-31"))

    assert week_num == 1
    assert "Week number: 1" in text
    assert "PRE-START: the experiment has NOT begun" in text
    assert "NUMBERS THAT CANNOT EXIST YET" in text


def test_packet_flags_pre_genesis_prologue_installments_only():
    data = _empty_data(start=GENESIS, end="2026-08-09")
    data["prev_installments"] = [
        {"sk": "DATE#2026-07-15"},  # prologue (pre-genesis)
        {"date": "2026-07-22"},  # prologue, `date` field form
        {"sk": "DATE#2026-08-05"},  # this cycle — not prologue
        {"sk": "WEEK#garbage"},  # no parseable date → ignored
    ]
    text, _ = cd.build_data_packet(data)

    assert "TIMELINE — CRITICAL: 2 earlier installment(s) are PRE-GENESIS PROLOGUE" in text
    assert f"backstory dated before the {GENESIS} genesis" in text
    assert "This is experiment WEEK 1; the measured experiment is 1 week(s) old." in text


def test_packet_omits_the_timeline_warning_without_prologue():
    data = _empty_data(start=GENESIS, end="2026-08-09")
    data["prev_installments"] = [{"sk": "DATE#2026-08-05"}]
    text, _ = cd.build_data_packet(data)

    assert "PRE-GENESIS PROLOGUE" not in text


def test_packet_calendar_block_covers_the_window_and_the_genesis():
    text, _ = cd.build_data_packet(_empty_data(start="2026-08-05", end="2026-08-11"))

    assert "- 2026-08-03 was a Monday (experiment genesis)" in text
    assert "- 2026-08-11 was a Tuesday" in text


# ══════════════════════════════════════════════════════════════════════════════
# build_data_packet — profile / weight
# ══════════════════════════════════════════════════════════════════════════════


def test_packet_profile_lines_prefer_profile_over_fallbacks():
    data = _empty_data(start=GENESIS, end="2026-08-09")
    data["profile"] = {
        "journey_start_date": GENESIS,
        "journey_start_weight_lbs": 331.0,
        "goal_weight_lbs": 199,
        "age": 41,
        "calorie_target": 2100,
        "protein_target_g": 205,
    }
    text, _ = cd.build_data_packet(data)

    assert "Journey start weight: 331.0 lbs" in text
    assert "Goal weight: 199 lbs" in text
    assert "Age: 41" in text
    assert "Targets: 2100 cal, 205g protein" in text


def test_packet_profile_falls_back_when_fields_are_absent():
    text, _ = cd.build_data_packet(_empty_data(start=GENESIS, end="2026-08-09"))

    # Derived, not pinned: the fallback IS the live constant, and a reset re-anchors it
    # (321.6 pinned here redded main at the cycle-14 reset — the genesis-relative-fixture class).
    assert f"Journey start weight: {cd.EXPERIMENT_BASELINE_WEIGHT_LBS} lbs" in text
    assert "Goal weight: 185 lbs" in text
    assert "Age: 37" in text
    assert "Targets: 1800 cal, 190g protein" in text


def test_packet_weight_story_uses_the_in_window_anchor_not_the_30_day_read():
    data = _empty_data()
    data["profile"] = {"journey_start_date": GENESIS, "journey_start_weight_lbs": 331.0}
    data["withings"] = {
        "2026-07-15": {"weight_lbs": Decimal("330.0")},  # inside the 30d weight pull, outside the week
        "2026-08-05": {"weight_lbs": Decimal("325.0")},  # first in-window weigh-in
        "2026-08-08": {"weight_lbs": Decimal("323.9")},
        "2026-08-11": {"weight_lbs": Decimal("322.5")},
    }
    text, _ = cd.build_data_packet(data)

    assert "Current: 322.5 lbs (2026-08-11)" in text
    assert "Week change: -2.5 lbs" in text  # vs 2026-08-05, NOT vs the 07-15 read
    assert "Total journey loss: 8.5 lbs" in text


def test_packet_weight_section_is_silent_without_weigh_ins():
    data = _empty_data()
    data["withings"] = {"2026-08-06": {}, "2026-08-07": {"weight_lbs": 0}}
    text, _ = cd.build_data_packet(data)

    assert "=== WEIGHT ===" in text
    assert "Current:" not in text
    assert "Total journey loss" not in text


def test_packet_single_weigh_in_reports_total_loss_but_no_week_change():
    data = _empty_data()
    data["profile"] = {"journey_start_date": GENESIS, "journey_start_weight_lbs": 331.0}
    data["withings"] = {"2026-08-11": {"weight_lbs": 328.0}}
    text, _ = cd.build_data_packet(data)

    assert "Current: 328.0 lbs (2026-08-11)" in text
    assert "Week change" not in text
    assert "Total journey loss: 3.0 lbs" in text


# ══════════════════════════════════════════════════════════════════════════════
# build_data_packet — biometrics / training / habits
# ══════════════════════════════════════════════════════════════════════════════


def _section(text, header, next_header):
    """The lines of one packet section, headers and blank lines stripped."""
    body = text.split(header)[1].split(next_header)[0]
    return [ln for ln in body.split("\n") if ln.strip() and not ln.startswith("(Frame:")]


def test_packet_recovery_line_omits_absent_fields():
    data = _empty_data()
    data["whoop"] = {
        "2026-08-05": {"recovery_score": 61, "hrv": 44.6, "resting_heart_rate": 58, "strain": Decimal("12.34")},
        "2026-08-06": {"recovery_score": 70},
    }
    text, _ = cd.build_data_packet(data)

    lines = _section(text, "=== RECOVERY & PHYSIOLOGY ===", "=== SLEEP (Whoop")
    # rounded from the raw record, and only the fields that were actually present
    assert lines == [
        "2026-08-05: | Recovery 61% | HRV 45ms | RHR 58 | Strain 12.3",
        "2026-08-06: | Recovery 70%",
    ]


def test_packet_sleep_line_derives_deep_and_rem_percentages():
    data = _empty_data()
    data["whoop"] = {
        "2026-08-05": {
            "sleep_quality_score": 82,
            "sleep_duration_hours": 7.5,
            "sleep_efficiency_percentage": 91.2,
            "rem_sleep_hours": 1.5,
            "slow_wave_sleep_hours": 1.125,
        }
    }
    text, _ = cd.build_data_packet(data)

    # 1.125/7.5 = 15%, 1.5/7.5 = 20% — derived, not read off the record
    assert "2026-08-05: | Score 82 | 7.5h | Eff 91% | Deep 15% | REM 20%" in text


def test_packet_sleep_percentages_are_dropped_when_duration_is_missing():
    data = _empty_data()
    data["whoop"] = {"2026-08-05": {"sleep_quality_score": 74, "rem_sleep_hours": 1.5, "slow_wave_sleep_hours": 1.1}}
    text, _ = cd.build_data_packet(data)

    lines = _section(text, "=== SLEEP (Whoop — source of truth) ===", "=== SLEEP RESTLESSNESS")
    assert lines == ["2026-08-05: | Score 74"]


def test_packet_restlessness_accepts_either_toss_field_and_skips_empty_days():
    data = _empty_data()
    data["eightsleep"] = {
        "2026-08-05": {"toss_and_turns": 12},
        "2026-08-06": {"toss_turn_count": Decimal("7")},
        "2026-08-07": {"some_other_field": 3},
    }
    text, _ = cd.build_data_packet(data)

    section = text.split("=== SLEEP RESTLESSNESS (Eight Sleep) ===")[1].split("=== TRAINING ===")[0]
    assert "2026-08-05: Tosses 12" in section
    assert "2026-08-06: Tosses 7" in section
    assert "2026-08-07" not in section


def test_packet_training_renders_each_activity_with_derived_distance():
    data = _empty_data()
    data["strava"] = {
        "2026-08-06": {
            "activities": [
                {
                    "name": "Synthetic Morning Walk",
                    "sport_type": "Walk",
                    "moving_time_seconds": 2700,
                    "distance_meters": 4023.4,
                    "average_heartrate": 118,
                    "total_elevation_gain_feet": 150,
                    "start_date_local": "2026-08-06T07:15:00Z",
                },
                {"name": "Synthetic Lift", "sport_type": "WeightTraining", "moving_time_seconds": 1800},
            ]
        }
    }
    text, _ = cd.build_data_packet(data)

    assert "2026-08-06 07:15: Synthetic Morning Walk (Walk, 45min, 2.5mi, HR 118, 150ft gain)" in text
    # no distance/HR/elevation → those clauses are omitted entirely
    assert "2026-08-06 : Synthetic Lift (WeightTraining, 30min)" in text
    assert "No activities recorded this week." not in text


def test_packet_training_low_elevation_is_not_reported():
    data = _empty_data()
    data["strava"] = {
        "2026-08-06": {
            "activities": [{"name": "Flat Walk", "sport_type": "Walk", "moving_time_seconds": 600, "total_elevation_gain_feet": 40}]
        }
    }
    text, _ = cd.build_data_packet(data)

    assert "2026-08-06 : Flat Walk (Walk, 10min)" in text
    assert "ft gain" not in text


def test_packet_training_empty_branch_states_no_activities():
    data = _empty_data()
    data["strava"] = {"2026-08-06": {}}  # a present day with no record still counts as none
    text, _ = cd.build_data_packet(data)

    assert "No activities recorded this week." in text


def test_packet_day_grades_and_habit_performance():
    data = _empty_data()
    data["day_grades"] = {
        "2026-08-05": {"total_score": 87.4, "letter_grade": "B+"},
        "2026-08-06": {"total_score": 91},  # no letter grade → "?"
    }
    data["habit_scores"] = {
        "2026-08-05": {
            "tier0_done": 4,
            "tier0_total": 5,
            "tier1_done": 2,
            "tier1_total": 4,
            "vices_held": 3,
            "vices_total": 3,
            "missed_tier0": ["habit-a", "habit-b", "habit-c", "habit-d"],
        },
        "2026-08-06": {"tier0_done": 5, "tier0_total": 5, "tier1_done": 4, "tier1_total": 4},
    }
    text, _ = cd.build_data_packet(data)

    assert "2026-08-05: 87/100 (B+)" in text
    assert "2026-08-06: 91/100 (?)" in text
    # only the first three misses are named
    assert "2026-08-05: T0 4/5, T1 2/4, Vices 3/3 | MISSED T0: habit-a, habit-b, habit-c" in text
    assert "habit-d" not in text
    # a clean day carries no MISSED clause, and absent vice counts default to 0
    assert "2026-08-06: T0 5/5, T1 4/4, Vices 0/0" in text


def test_packet_nutrition_skips_days_without_calories():
    data = _empty_data()
    data["macrofactor"] = {
        "2026-08-05": {"total_calories_kcal": 1820.6, "total_protein_g": 196.2},
        "2026-08-06": {"total_protein_g": 150},  # no calories → not rendered
    }
    text, _ = cd.build_data_packet(data)

    assert "2026-08-05: 1821 cal, 196g protein" in text
    section = text.split("=== NUTRITION ===")[1].split("=== JOURNAL")[0]
    assert "2026-08-06" not in section


def test_packet_day_grades_missing_total_score_renders_no_grade_instead_of_crashing():
    """#2177 regression: a day_grades row with calories/other fields but no
    total_score must not raise — safe_float returns None (ADR-104 absence),
    and f"{None:.0f}" is a TypeError. The row degrades to an honest line."""
    data = _empty_data()
    data["day_grades"] = {
        "2026-08-05": {"letter_grade": "B"},  # no total_score — partial record
        "2026-08-06": {"total_score": 91},  # unaffected sibling day still grades
    }
    text, _ = cd.build_data_packet(data)  # must not raise

    assert "2026-08-05: no grade recorded" in text
    assert "2026-08-06: 91/100 (?)" in text


def test_packet_nutrition_missing_protein_renders_calories_with_a_not_logged_marker():
    """#2177 regression: a macrofactor row with calories logged but no
    total_protein_g must not raise the same TypeError the calories guard
    already prevents — it degrades to an honest 'protein not logged' clause
    rather than dropping the whole day or crashing the weekly packet build."""
    data = _empty_data()
    data["macrofactor"] = {
        "2026-08-05": {"total_calories_kcal": 1800},  # no total_protein_g
    }
    text, _ = cd.build_data_packet(data)  # must not raise

    assert "2026-08-05: 1800 cal, protein not logged" in text


# ══════════════════════════════════════════════════════════════════════════════
# build_data_packet — journal
# ══════════════════════════════════════════════════════════════════════════════


def test_packet_journal_truncates_text_and_caps_each_signal_list():
    data = _empty_data()
    data["journal_entries"] = [
        {
            "sk": "DATE#2026-08-06#journal#evening#uuid-1",
            "template": "evening",
            "raw_text": "S" * 1500 + "TAIL-BEYOND-THE-CAP",
            "enriched_mood": 3,
            "enriched_energy": 2,
            "enriched_stress": 4,
            "enriched_themes": ["theme-1", "theme-2", "theme-3", "theme-4", "theme-5"],
            "enriched_emotions": ["emo-1", "emo-2", "emo-3", "emo-4", "emo-5", "emo-6"],
            "enriched_cognitive_patterns": ["pattern-1", "pattern-2", "pattern-3", "pattern-4"],
            "enriched_avoidance_flags": ["flag-1", "flag-2"],
            "enriched_social_quality": "synthetic-social-value",
            "enriched_ownership": "synthetic-ownership-value",
        }
    ]
    text, _ = cd.build_data_packet(data)

    # date falls back to the SK when no `date` field is present
    assert "--- 2026-08-06 (evening) ---" in text
    assert "TAIL-BEYOND-THE-CAP" not in text
    assert "Text: " + "S" * 1500 in text
    assert "Mood:3/5 | Energy:2/5 | Stress:4/5" in text
    assert "Themes: theme-1, theme-2, theme-3, theme-4 |" in text
    assert "theme-5" not in text
    assert "Emotions: emo-1, emo-2, emo-3, emo-4, emo-5 |" in text
    assert "emo-6" not in text
    assert "Cognitive: pattern-1, pattern-2, pattern-3 |" in text
    assert "pattern-4" not in text
    assert "AVOIDANCE FLAGS: flag-1, flag-2" in text
    assert "Social: synthetic-social-value" in text
    assert "Ownership: synthetic-ownership-value" in text


def test_packet_journal_entry_without_signals_renders_only_its_header():
    data = _empty_data()
    data["journal_entries"] = [{"date": "2026-08-07", "sk": "DATE#2026-08-07#journal#morning#uuid-2", "raw_text": ""}]
    text, _ = cd.build_data_packet(data)

    assert "--- 2026-08-07 (?) ---" in text  # template defaults to "?"
    assert "Signals:" not in text
    assert "Text:" not in text


def test_packet_journal_entries_are_ordered_by_sort_key():
    data = _empty_data()
    data["journal_entries"] = [
        {"sk": "DATE#2026-08-09#journal#evening#z", "template": "evening"},
        {"sk": "DATE#2026-08-05#journal#morning#a", "template": "morning"},
    ]
    text, _ = cd.build_data_packet(data)

    assert text.index("--- 2026-08-05 (morning) ---") < text.index("--- 2026-08-09 (evening) ---")


def test_packet_journal_empty_branch():
    text, _ = cd.build_data_packet(_empty_data())
    assert "No journal entries this week." in text


# ══════════════════════════════════════════════════════════════════════════════
# build_data_packet — ADR-142 tier-2 consent gating (#1483)
# ══════════════════════════════════════════════════════════════════════════════


def test_packet_conversation_block_renders_sanctioned_fields_only():
    """A RAW LEARNING# row handed to the packet builder must be re-laundered:
    the block may say a conversation happened, its coarse theme, and how the
    coach's read moved — and nothing that was actually said."""
    data = _empty_data()
    data["conversation_refs"] = [
        {
            "pk": "COACH#mind_coach",
            "sk": "LEARNING#2026-08-06#synthetic",
            "channel": "conversation",
            "date": "2026-08-06",
            "coach_id": "mind_coach",
            "subdomain": "anxiety_management",
            "confidence_direction": "up",
            "confidence_weight": 0.4,
            "answer_quote": "SYNTHETIC-PRIVATE-QUOTE-MUST-NOT-LEAK",
            "takeaway": "SYNTHETIC-PRIVATE-TAKEAWAY-MUST-NOT-LEAK",
            "question": "SYNTHETIC-PRIVATE-QUESTION-MUST-NOT-LEAK",
        }
    ]
    text, _ = cd.build_data_packet(data)

    assert diary_consent.CONVERSATION_BLOCK_HEADER in text
    assert (
        "- 2026-08-06: Matthew and his mind coach talked about stress and worry; "
        "the coach came away more confident in their read." in text
    )
    for private in ("SYNTHETIC-PRIVATE-QUOTE", "SYNTHETIC-PRIVATE-TAKEAWAY", "SYNTHETIC-PRIVATE-QUESTION", "anxiety_management"):
        assert private not in text


def test_packet_excludes_non_consented_records_entirely():
    """channel != conversation (a data-channel learning) and a malformed date are
    both unsanctionable — the block must not render at all."""
    data = _empty_data()
    data["conversation_refs"] = [
        {"channel": "data", "date": "2026-08-06", "coach_id": "sleep_coach", "answer_quote": "SYNTHETIC-DATA-CHANNEL-TEXT"},
        {"channel": "conversation", "date": "not-a-date", "coach_id": "sleep_coach", "answer_quote": "SYNTHETIC-BAD-DATE-TEXT"},
    ]
    text, _ = cd.build_data_packet(data)

    assert diary_consent.CONVERSATION_BLOCK_HEADER not in text
    assert "SYNTHETIC-DATA-CHANNEL-TEXT" not in text
    assert "SYNTHETIC-BAD-DATE-TEXT" not in text


def test_packet_no_conversation_block_on_a_quiet_week():
    text, _ = cd.build_data_packet(_empty_data())
    assert diary_consent.CONVERSATION_BLOCK_HEADER not in text


# ══════════════════════════════════════════════════════════════════════════════
# build_data_packet — state of mind / experiments / anomalies / weather / supps
# ══════════════════════════════════════════════════════════════════════════════


def test_packet_state_of_mind_renders_valence_with_optional_clauses():
    data = _empty_data()
    data["state_of_mind"] = {
        "2026-08-06": {"som_avg_valence": 0.234, "som_top_labels": "calm, content", "som_top_associations": "work"},
        "2026-08-07": {"som_avg_valence": Decimal("-0.5")},
        # a SoM day whose valence did not survive normalization: skipped silently
        # rather than rendered as a labels-only line
        "2026-08-08": {"som_top_labels": "SYNTHETIC-LABEL"},
    }
    text, _ = cd.build_data_packet(data)

    lines = _section(text, "=== STATE OF MIND (How We Feel) ===", "=== WEATHER (Seattle) ===")
    assert lines == [
        "2026-08-06: valence 0.23 | emotions: calm, content | areas: work",
        "2026-08-07: valence -0.50",
    ]
    assert "SYNTHETIC-LABEL" not in text
    assert "No State of Mind check-ins this week." not in text


def test_packet_state_of_mind_empty_branch():
    text, _ = cd.build_data_packet(_empty_data())
    assert "No State of Mind check-ins this week." in text


def test_packet_active_experiments_section():
    data = _empty_data()
    data["experiments"] = [
        {"name": "Synthetic Protocol A", "hypothesis": "synthetic hypothesis text", "start_date": "2026-08-04", "days_active": 5},
        {"name": "Synthetic Protocol B"},
    ]
    text, _ = cd.build_data_packet(data)

    assert "=== ACTIVE EXPERIMENTS ===" in text
    assert "- Synthetic Protocol A (started 2026-08-04, 5 days active)" in text
    assert "  Hypothesis: synthetic hypothesis text" in text
    assert "- Synthetic Protocol B (started ?, ? days active)" in text


def test_packet_omits_the_experiments_section_when_none_are_active():
    text, _ = cd.build_data_packet(_empty_data())
    assert "=== ACTIVE EXPERIMENTS ===" not in text


def test_packet_anomalies_filtered_to_moderate_and_high():
    data = _empty_data()
    data["anomalies"] = {
        "2026-08-05": {"date": "2026-08-05", "severity": "low", "anomalous_metrics": [{"label": "Steps"}]},
        "2026-08-06": {
            "date": "2026-08-06",
            "severity": "high",
            "anomalous_metrics": [{"label": "HRV"}, {"label": "RHR"}],
            "hypothesis": "synthetic anomaly hypothesis",
        },
        "2026-08-07": {"date": "2026-08-07", "severity": "moderate", "anomalous_metrics": []},
    }
    text, _ = cd.build_data_packet(data)

    assert "=== ANOMALY EVENTS ===" in text
    assert "2026-08-06: high — HRV, RHR" in text
    # #2422: the hypothesis is still shown to Elena, but fenced as model conjecture
    # so the grounding allow-list derivation can strip it.
    assert "synthetic anomaly hypothesis" in text
    assert f"  Hypothesis: {cd.MODEL_CONJECTURE_OPEN} synthetic anomaly hypothesis {cd.MODEL_CONJECTURE_CLOSE}" in text
    assert "2026-08-07: moderate — " in text
    assert "Steps" not in text


def test_packet_omits_the_anomaly_section_when_all_are_low():
    data = _empty_data()
    data["anomalies"] = {"2026-08-05": {"severity": "low"}}
    text, _ = cd.build_data_packet(data)

    assert "=== ANOMALY EVENTS ===" not in text


def test_packet_weather_flags_rain_above_the_half_mm_threshold():
    data = _empty_data()
    data["weather"] = {
        "2026-08-05": {"temp_avg_f": 71.6, "precipitation_mm": 0.0, "daylight_hours": 14.2},
        "2026-08-06": {"temp_avg_f": 60, "precipitation_mm": 1.2},
        "2026-08-07": {},
    }
    text, _ = cd.build_data_packet(data)

    assert "2026-08-05 | 72°F | Dry | 14.2h daylight" in text
    assert "2026-08-06 | 60°F | Rain" in text
    assert "\n2026-08-07\n" in text  # a bare day line when nothing was recorded


def test_packet_supplement_stack_is_a_sorted_union_across_the_week():
    data = _empty_data()
    data["supplements"] = {
        "2026-08-05": {"supplements": [{"name": "Vitamin D"}, {"name": "Creatine"}]},
        "2026-08-06": {"supplements": [{"name": "Creatine"}, {"name": "Magnesium"}]},
    }
    text, _ = cd.build_data_packet(data)

    assert "=== SUPPLEMENT STACK: Creatine, Magnesium, Vitamin D ===" in text


def test_packet_omits_the_supplement_stack_when_nothing_was_logged():
    data = _empty_data()
    data["supplements"] = {"2026-08-05": {"supplements": []}}
    text, _ = cd.build_data_packet(data)

    assert "SUPPLEMENT STACK" not in text


# ══════════════════════════════════════════════════════════════════════════════
# build_data_packet — character sheet
# ══════════════════════════════════════════════════════════════════════════════


def _character_sheet_week():
    return {
        "2026-08-05": {"character_level": 11, "pillar_sleep": {"level": 3, "tier": "Foundation"}},
        "2026-08-11": {
            "character_level": 12,
            "character_tier": "Momentum",
            "character_tier_emoji": "*",
            "character_xp": 4200,
            "pillar_sleep": {"level": 4, "tier": "Momentum", "raw_score": 72.4},
            "level_events": [
                {
                    "pillar": "sleep",
                    "event_type": "level_up",
                    "old_level": 3,
                    "new_level": 4,
                    "old_tier": "Foundation",
                    "new_tier": "Momentum",
                },
                {"pillar": "mind", "event_type": "level_up", "old_level": 2, "new_level": 3},
            ],
            "active_effects": [{"emoji": "+", "name": "Synthetic Buff", "description": "synthetic effect description"}],
        },
    }


def test_packet_character_sheet_reports_week_over_week_progression():
    data = _empty_data()
    data["character_sheet"] = _character_sheet_week()
    text, _ = cd.build_data_packet(data)

    assert "Overall: Level 12 * Momentum (+1 this week) | XP: 4200" in text
    # pillar with data: level delta vs the FIRST day of the week + the raw score
    assert "Sleep: Level 4 (Momentum) (+1) (raw: 72)" in text
    # a pillar with no record at all falls back to Level 1 Foundation, no delta
    assert "Movement: Level 1 (Foundation)" in text
    assert "Consistency: Level 1 (Foundation)" in text


def test_packet_character_sheet_level_events_are_typed_by_tier_change():
    data = _empty_data()
    data["character_sheet"] = _character_sheet_week()
    text, _ = cd.build_data_packet(data)

    assert "LEVEL EVENTS THIS WEEK (these are story moments):" in text
    assert "  2026-08-11: sleep TIER CHANGE: Foundation → Momentum (Level 3 → 4)" in text
    assert "  2026-08-11: mind level_up: Level 2 → 3" in text
    assert "ACTIVE EFFECTS (cross-pillar buffs/debuffs):" in text
    assert "  + Synthetic Buff: synthetic effect description" in text


def test_packet_character_sheet_single_day_week_is_stable_with_no_events():
    data = _empty_data()
    data["character_sheet"] = {"2026-08-11": {"character_level": 9, "character_tier": "Foundation", "character_xp": 1200}}
    text, _ = cd.build_data_packet(data)

    assert "(stable) | XP: 1200" in text
    assert "No level events this week. Stable is fine — it means no flip-flopping." in text
    assert "ACTIVE EFFECTS" not in text


def test_packet_omits_the_character_sheet_section_without_records():
    text, _ = cd.build_data_packet(_empty_data())
    assert "CHARACTER SHEET" not in text


# ══════════════════════════════════════════════════════════════════════════════
# build_data_packet — field notes + the fully-empty week
# ══════════════════════════════════════════════════════════════════════════════


def test_packet_field_notes_section_includes_matthews_response():
    data = _empty_data()
    data["field_notes"] = {
        "week": "2026-W33",
        "ai_tone": "encouraging",
        "ai_present": "SYNTHETIC-AI-ANALYSIS " * 30,
        "has_matthew_response": True,
        "matthew_agreement": "SYNTHETIC-AGREEMENT-TEXT",
    }
    text, _ = cd.build_data_packet(data)

    assert "=== FIELD NOTES THIS WEEK ===" in text
    assert "AI tone: encouraging" in text
    assert "AI preview: SYNTHETIC-AI-ANALYSIS" in text
    assert "Matthew's agreement: SYNTHETIC-AGREEMENT-TEXT" in text


def test_packet_field_notes_without_a_response_omit_the_agreement_line():
    data = _empty_data()
    data["field_notes"] = {
        "ai_tone": "mixed",
        "ai_present": "SYNTHETIC-AI-ANALYSIS",
        "has_matthew_response": False,
        "matthew_agreement": "",
    }
    text, _ = cd.build_data_packet(data)

    assert "=== FIELD NOTES THIS WEEK ===" in text
    assert "Matthew's agreement" not in text


def test_packet_empty_week_still_renders_every_mandatory_section():
    """The missing-source path: no source has data, but the packet must still be
    a well-formed, honest document rather than crashing or going blank."""
    text, week_num = cd.build_data_packet(_empty_data(start=GENESIS, end="2026-08-09"))

    for header in (
        "=== THE MEASURED LIFE — WEEKLY DATA PACKET ===",
        "=== WEIGHT ===",
        "=== RECOVERY & PHYSIOLOGY ===",
        "=== SLEEP (Whoop — source of truth) ===",
        "=== SLEEP RESTLESSNESS (Eight Sleep) ===",
        "=== TRAINING ===",
        "=== DAY GRADES ===",
        "=== HABIT PERFORMANCE ===",
        "=== NUTRITION ===",
        "=== JOURNAL (OFF THE RECORD — never quote directly) ===",
        "=== STATE OF MIND (How We Feel) ===",
        "=== WEATHER (Seattle) ===",
    ):
        assert header in text
    assert week_num == 1
    assert "No activities recorded this week." in text
    assert "No journal entries this week." in text
    assert "No State of Mind check-ins this week." in text


# ══════════════════════════════════════════════════════════════════════════════
# gather_chronicle_data
# ══════════════════════════════════════════════════════════════════════════════


def test_gather_returns_none_and_logs_when_the_profile_is_missing(monkeypatch):
    _freeze(monkeypatch)
    logger = _StubLogger()
    g = _make_g(profile=None, logger=logger)

    assert cd.gather_chronicle_data(_g=g) is None
    assert any("No profile found" in m for m in logger.error_msgs)
    assert g["_range_calls"] == []  # bails before any query


def test_gather_derives_the_window_from_the_clock_and_widens_only_for_weight(monkeypatch):
    win = _freeze(monkeypatch)
    g = _make_g(profile={"journey_start_date": GENESIS})

    out = cd.gather_chronicle_data(_g=g)

    assert out["dates"] == {"start": win["start"], "end": win["end"]}
    calls = dict((src, (s, e)) for src, s, e in g["_range_calls"])
    assert calls["whoop"] == (win["start"], win["end"])
    assert calls["strava"] == (win["start"], win["end"])
    # withings alone reaches 30 days back so the journey trend has an anchor
    assert calls["withings"] == (win["weight_start"], win["end"])
    assert calls["notion"] == (win["start"], win["end"])


def test_gather_keeps_only_journal_records_from_the_notion_partition(monkeypatch):
    _freeze(monkeypatch)
    g = _make_g(
        profile={"journey_start_date": GENESIS},
        lists={
            "notion": [
                {"sk": "DATE#2026-08-06#journal#evening#a", "raw_text": "SYNTHETIC-JOURNAL"},
                {"sk": "DATE#2026-08-06#task#b"},
                {"sk": "DATE#2026-08-07#journal#morning#c"},
                {"sk": "DATE#2026-08-07"},
            ]
        },
    )

    out = cd.gather_chronicle_data(_g=g)

    assert [e["sk"] for e in out["journal_entries"]] == [
        "DATE#2026-08-06#journal#evening#a",
        "DATE#2026-08-07#journal#morning#c",
    ]


def test_gather_state_of_mind_keeps_only_apple_health_days_with_a_valence(monkeypatch):
    _freeze(monkeypatch)
    apple = {
        "2026-08-05": {"steps": 8000},
        "2026-08-06": {"steps": 9000, "som_avg_valence": Decimal("0.25")},
        "2026-08-07": {"som_avg_valence": None},
    }
    g = _make_g(profile={"journey_start_date": GENESIS}, ranges={"apple_health": apple})

    out = cd.gather_chronicle_data(_g=g)

    assert set(out["apple_health"]) == {"2026-08-05", "2026-08-06", "2026-08-07"}  # unfiltered
    assert list(out["state_of_mind"]) == ["2026-08-06"]


def test_gather_experiments_and_previous_installments(monkeypatch):
    _freeze(monkeypatch)
    table = _StubTable(
        items_by_pk={
            "USER#matthew#SOURCE#experiments": [
                {"name": "Synthetic Active", "status": "active", "days_active": Decimal("5")},
                {"name": "Synthetic Completed", "status": "completed"},
                {"name": "Synthetic Draft"},
            ],
            "USER#matthew#SOURCE#chronicle": [
                {"sk": "DATE#2026-08-05", "week_num": Decimal("2")},
                {"sk": "DATE#2026-07-29", "week_num": Decimal("1")},
            ],
        }
    )
    g = _make_g(profile={"journey_start_date": GENESIS}, table=table)

    out = cd.gather_chronicle_data(_g=g)

    assert [e["name"] for e in out["experiments"]] == ["Synthetic Active"]
    assert out["experiments"][0]["days_active"] == 5.0  # d2f-converted, not Decimal
    assert isinstance(out["experiments"][0]["days_active"], float)
    assert [i["sk"] for i in out["prev_installments"]] == ["DATE#2026-08-05", "DATE#2026-07-29"]
    assert out["prev_installments"][0]["week_num"] == 2.0
    # the chronicle read is newest-first and deep enough to see past dormant rows
    chron_kwargs = [k for k in table.query_kwargs if (k.get("ExpressionAttributeValues") or {}).get(":pk", "").endswith("#chronicle")][0]
    assert chron_kwargs["ScanIndexForward"] is False
    assert chron_kwargs["Limit"] == 25


def test_gather_is_fail_soft_when_dynamodb_queries_raise(monkeypatch):
    _freeze(monkeypatch)
    logger = _StubLogger()
    table = _StubTable(query_error=RuntimeError("synthetic-ddb-outage"))
    g = _make_g(profile={"journey_start_date": GENESIS}, table=table, logger=logger)

    out = cd.gather_chronicle_data(_g=g)

    assert out["experiments"] == []
    assert out["prev_installments"] == []
    assert out["conversation_refs"] == []
    assert any("synthetic-ddb-outage" in m for m in logger.warning_msgs)


def test_gather_is_fail_soft_when_dynamodb_get_items_raise(monkeypatch):
    """The three get_item reads (field notes, narrative arc, experiment arc) are
    each individually fail-soft: a read outage degrades the packet, never the run."""
    _freeze(monkeypatch)
    logger = _StubLogger()
    g = _make_g(
        profile={"journey_start_date": GENESIS},
        table=_StubTable(get_error=RuntimeError("synthetic-getitem-outage")),
        logger=logger,
    )

    out = cd.gather_chronicle_data(_g=g)

    assert out["field_notes"] is None
    assert out["narrative_arc"] is None
    assert out["experiment_arc"] is None
    assert sum("synthetic-getitem-outage" in m for m in logger.warning_msgs) == 3


def test_gather_field_notes_reads_the_current_iso_week_and_truncates(monkeypatch):
    _freeze(monkeypatch)  # 2026-08-12 → ISO 2026-W33
    table = _StubTable(
        items_by_key={
            ("USER#matthew#SOURCE#field_notes", "WEEK#2026-W33"): {
                "ai_tone": "direct",
                "ai_present": "P" * 600,
                "matthew_agreement": "A" * 400,
            }
        }
    )
    g = _make_g(profile={"journey_start_date": GENESIS}, table=table)

    out = cd.gather_chronicle_data(_g=g)

    fn = out["field_notes"]
    assert fn["week"] == "2026-W33"
    assert fn["ai_tone"] == "direct"
    assert len(fn["ai_present"]) == 500
    assert len(fn["matthew_agreement"]) == 300
    assert fn["has_matthew_response"] is True


def test_gather_field_notes_absent_when_the_week_has_no_ai_analysis(monkeypatch):
    _freeze(monkeypatch)
    table = _StubTable(items_by_key={("USER#matthew#SOURCE#field_notes", "WEEK#2026-W33"): {"ai_tone": "direct"}})
    g = _make_g(profile={"journey_start_date": GENESIS}, table=table)

    assert cd.gather_chronicle_data(_g=g)["field_notes"] is None


def test_gather_conversation_refs_are_sanctioned_and_window_scoped(monkeypatch):
    win = _freeze(monkeypatch)
    table = _StubTable(
        items_by_pk={
            "COACH#mind_coach": [
                {
                    "channel": "conversation",
                    "date": "2026-08-06",
                    "coach_id": "mind_coach",
                    "subdomain": "anxiety_management",
                    "confidence_direction": "up",
                    "confidence_weight": Decimal("0.4"),
                    "answer_quote": "SYNTHETIC-PRIVATE-QUOTE-MUST-NOT-LEAK",
                    "takeaway": "SYNTHETIC-PRIVATE-TAKEAWAY",
                },
                {  # before the covered window → dropped
                    "channel": "conversation",
                    "date": "2026-07-30",
                    "coach_id": "mind_coach",
                    "subdomain": "sleep_timing",
                    "confidence_direction": "down",
                },
                {  # data-channel learning → never sanctionable
                    "channel": "data",
                    "date": "2026-08-07",
                    "coach_id": "mind_coach",
                    "answer_quote": "SYNTHETIC-DATA-CHANNEL-TEXT",
                },
            ]
        }
    )
    g = _make_g(profile={"journey_start_date": GENESIS}, table=table)

    refs = cd.gather_chronicle_data(_g=g)["conversation_refs"]

    assert len(refs) == 1
    ref = refs[0]
    assert win["start"] <= ref["date"] <= win["end"]
    assert ref == {
        "kind": diary_consent.CONVERSATION_KIND,
        "occurred": True,
        "date": "2026-08-06",
        "theme": "anxiety_stress",
        "direction": "up",
        "weight": 0.4,
        "coach_id": "mind_coach",
    }
    # the private fields are structurally unreachable, not merely unrendered
    assert set(ref) <= set(diary_consent.CONVERSATION_SANCTIONED_FIELDS)


def test_gather_narrative_arc_visible_only_when_current_and_untombstoned(monkeypatch):
    _freeze(monkeypatch)
    arc = {"summary": "SYNTHETIC-ARC-SUMMARY", "entered_date": "2026-08-04"}
    g = _make_g(
        profile={"journey_start_date": GENESIS},
        table=_StubTable(items_by_key={("NARRATIVE#arc", "STATE#current"): arc}),
    )

    assert cd.gather_chronicle_data(_g=g)["narrative_arc"]["summary"] == "SYNTHETIC-ARC-SUMMARY"


def test_gather_narrative_arc_dropped_when_tombstoned_or_pre_genesis(monkeypatch):
    _freeze(monkeypatch)

    tombstoned = _make_g(
        profile={"journey_start_date": GENESIS},
        table=_StubTable(
            items_by_key={("NARRATIVE#arc", "STATE#current"): {"summary": "SYNTHETIC", "entered_date": "2026-08-04", "tombstone": True}}
        ),
    )
    assert cd.gather_chronicle_data(_g=tombstoned)["narrative_arc"] is None

    # entered before this cycle's genesis → the previous cycle's story
    stale = _make_g(
        profile={"journey_start_date": GENESIS},
        table=_StubTable(items_by_key={("NARRATIVE#arc", "STATE#current"): {"summary": "SYNTHETIC", "entered_date": "2026-07-01"}}),
    )
    assert cd.gather_chronicle_data(_g=stale)["narrative_arc"] is None


def test_gather_experiment_arc_respects_the_singleton_phase_filter(monkeypatch):
    _freeze(monkeypatch)
    key = ("USER#matthew#SOURCE#ai_analysis", "EXPERT#experiment_arc")

    visible = _make_g(
        profile={"journey_start_date": GENESIS},
        table=_StubTable(items_by_key={key: {"arc": "SYNTHETIC-EXPERIMENT-ARC", "confidence": Decimal("0.8")}}),
    )
    out = cd.gather_chronicle_data(_g=visible)
    assert out["experiment_arc"]["arc"] == "SYNTHETIC-EXPERIMENT-ARC"
    assert out["experiment_arc"]["confidence"] == 0.8  # d2f-converted

    wiped = _make_g(
        profile={"journey_start_date": GENESIS},
        table=_StubTable(items_by_key={key: {"arc": "SYNTHETIC-EXPERIMENT-ARC", "tombstone": True}}),
    )
    assert cd.gather_chronicle_data(_g=wiped)["experiment_arc"] is None

    missing = _make_g(profile={"journey_start_date": GENESIS}, table=_StubTable())
    assert cd.gather_chronicle_data(_g=missing)["experiment_arc"] is None


def test_gather_output_feeds_build_data_packet_end_to_end(monkeypatch):
    """The two halves are a contract: whatever gather returns must be a complete
    input for build_data_packet (every key the builder indexes unconditionally)."""
    _freeze(monkeypatch)
    g = _make_g(
        profile={"journey_start_date": GENESIS, "journey_start_weight_lbs": 331.0},
        ranges={
            "withings": {"2026-08-11": {"weight_lbs": Decimal("324.0")}},
            "whoop": {"2026-08-11": {"recovery_score": 55, "hrv": 40}},
        },
    )

    data = cd.gather_chronicle_data(_g=g)
    text, week_num = cd.build_data_packet(data)

    assert "Week ending: 2026-08-11" in text
    assert "Current: 324.0 lbs (2026-08-11)" in text
    assert "Total journey loss: 7.0 lbs" in text
    assert "2026-08-11: | Recovery 55% | HRV 40ms" in text
    assert week_num == 2  # genesis 2026-08-03 → 2026-08-11 is Day 9


# ══════════════════════════════════════════════════════════════════════════════
# _load_engagement_signal (#914)
# ══════════════════════════════════════════════════════════════════════════════


def test_load_engagement_signal_returns_the_state_record():
    table = _StubTable(items_by_key={("USER#matthew#SOURCE#engagement_state", "STATE#current"): {"quiet_days": 3, "state": "quiet"}})
    g = _make_g(table=table)

    assert cd._load_engagement_signal(_g=g) == {"quiet_days": 3, "state": "quiet"}
    assert table.get_keys == [{"pk": "USER#matthew#SOURCE#engagement_state", "sk": "STATE#current"}]


def test_load_engagement_signal_returns_empty_dict_when_absent():
    assert cd._load_engagement_signal(_g=_make_g(table=_StubTable())) == {}
