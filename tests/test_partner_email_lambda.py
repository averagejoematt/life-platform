"""tests/test_partner_email_lambda.py — the Sunday partner weekly email (#1658 coverage ratchet).

Hermetic: no AWS, no SES, no Anthropic/Bedrock, no wall-clock now-math. Every
time-dependent path either takes an explicit date string or runs against a
monkeypatched `datetime` whose `now()` is pinned, so a fixture date can never
drift into a failure months from now.

What is pinned here:
  - the scalar helpers (`avg`, `_normalize_whoop_sleep`) including their
    divide-by-zero / already-present-field guards
  - `gather_all`'s aggregation + every plain-English label threshold, driven by
    monkeypatched readers (no DDB)
  - `parse_sections` — the emoji header split, incl. the markdown markers Sonnet
    likes to prepend and preamble text before the first header
  - the HTML builders (`section_html`, `signal_dot`, `weight_sentence`,
    `build_html`) asserted on real rendered substrings
  - `_recipient`'s SSM lookup, its failure fallback, and its warm cache
  - `build_commentary`'s prompt/payload composition + the single retry_utils
    inference seam (#2423 retired the direct-bedrock fallback) + the ADR-104
    grounding gate: regenerate-once-then-HOLD, fabricated numbers held
  - `lambda_handler`: the kill switch must NOT send, the happy path composes the
    exact SES payload, and an AI failure or a grounding HOLD still sends the
    deterministic data-only email — never a fabricated narrative to a third party.
"""

import json
import os
import sys
from datetime import datetime, timezone

import pytest

os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")
# Read at import time by the module under test (module-level `os.environ[...]`).
os.environ.setdefault("EMAIL_SENDER", "test@example.com")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "emails"))

import partner_email_lambda as partner  # noqa: E402
from pacific_clock import freeze_pacific  # #2817: the Pacific clock a converted module actually reads

# ── A pinned "today" so nothing in this file does fixture-date + now() math ───
FIXED_TODAY = datetime(2026, 8, 6, 12, 0, 0, tzinfo=timezone.utc)
WEEK_START = "2026-07-30"  # today - 7
WEEK_END = "2026-08-05"  # today - 1


class _FixedDatetime(datetime):
    """datetime subclass with a pinned now(); strptime/strftime inherited."""

    @classmethod
    def now(cls, tz=None):
        return FIXED_TODAY if tz else FIXED_TODAY.replace(tzinfo=None)


class FakeSes:
    """Records send_email calls. Never touches the network."""

    def __init__(self):
        self.sends = []

    def send_email(self, **kwargs):
        self.sends.append(kwargs)
        return {"MessageId": "m%d" % len(self.sends)}


class ExplodingSes:
    """Any send at all is a test failure."""

    def send_email(self, **kwargs):
        raise AssertionError("SES send attempted on a path that must not send")


@pytest.fixture(autouse=True)
def _no_real_ses(monkeypatch):
    """Belt-and-braces: the module-level SES client is never the real one here."""
    monkeypatch.setattr(partner, "ses", ExplodingSes())


@pytest.fixture(autouse=True)
def _clear_recipient_cache():
    partner._recipient_cache["v"] = None
    yield
    partner._recipient_cache["v"] = None


# ══════════════════════════════════════════════════════════════════════════════
# avg
# ══════════════════════════════════════════════════════════════════════════════


def test_avg_ignores_none_and_rounds_to_one_decimal():
    assert partner.avg([1, 2, None, 4]) == 2.3  # 7/3 = 2.333… → 2.3
    assert partner.avg([80, 60]) == 70.0


def test_avg_returns_none_for_empty_and_all_none():
    assert partner.avg([]) is None
    assert partner.avg([None, None]) is None


def test_avg_of_single_zero_is_zero_not_none():
    # 0.0 is a real measurement; the None-guard must not swallow it.
    assert partner.avg([0]) == 0.0


# ══════════════════════════════════════════════════════════════════════════════
# _normalize_whoop_sleep
# ══════════════════════════════════════════════════════════════════════════════


def test_normalize_whoop_sleep_aliases_quality_score_and_derives_stage_pcts():
    out = partner._normalize_whoop_sleep(
        {"sleep_quality_score": 82, "sleep_duration_hours": 7.0, "slow_wave_sleep_hours": 1.4, "rem_sleep_hours": 1.75}
    )
    assert out["sleep_score"] == 82
    assert out["deep_pct"] == 20.0  # 1.4 / 7.0
    assert out["rem_pct"] == 25.0  # 1.75 / 7.0


def test_normalize_whoop_sleep_does_not_clobber_existing_fields():
    out = partner._normalize_whoop_sleep(
        {"sleep_quality_score": 82, "sleep_score": 61, "sleep_duration_hours": 8.0, "slow_wave_sleep_hours": 2.0, "deep_pct": 11.0}
    )
    assert out["sleep_score"] == 61  # the explicit field wins over the alias
    assert out["deep_pct"] == 11.0  # already present → not recomputed


def test_normalize_whoop_sleep_zero_duration_skips_pct_division():
    out = partner._normalize_whoop_sleep({"sleep_duration_hours": 0, "slow_wave_sleep_hours": 1.2, "rem_sleep_hours": 1.0})
    assert "deep_pct" not in out
    assert "rem_pct" not in out


def test_normalize_whoop_sleep_unparseable_duration_is_treated_as_zero():
    out = partner._normalize_whoop_sleep({"sleep_duration_hours": "n/a", "rem_sleep_hours": 1.0})
    assert "rem_pct" not in out
    assert out["sleep_duration_hours"] == "n/a"  # input echoed, not mutated away


def test_normalize_whoop_sleep_returns_a_copy():
    src = {"sleep_quality_score": 70, "sleep_duration_hours": 7.0}
    out = partner._normalize_whoop_sleep(src)
    assert out is not src
    assert "sleep_score" not in src  # caller's record untouched


def test_normalize_whoop_sleep_missing_stage_fields_is_a_noop():
    out = partner._normalize_whoop_sleep({"sleep_score": 55, "sleep_duration_hours": 6.5})
    assert out == {"sleep_score": 55, "sleep_duration_hours": 6.5}


def test_normalize_whoop_sleep_unparseable_stage_value_fails_soft():
    """A garbage stage value must drop that one pct, not blow up the whole night."""
    out = partner._normalize_whoop_sleep(
        {"sleep_score": 70, "sleep_duration_hours": 7.0, "slow_wave_sleep_hours": "n/a", "rem_sleep_hours": 1.75}
    )
    assert "deep_pct" not in out  # the bad one is dropped
    assert out["rem_pct"] == 25.0  # the good one still lands


# ══════════════════════════════════════════════════════════════════════════════
# DDB readers (query_range / query_journal_range / fetch_profile)
# ══════════════════════════════════════════════════════════════════════════════


class _FakeTable:
    """Returns a fixed, finite list of query pages. Raises past the end rather
    than looping forever (a non-terminating pager has OOM'd CI before)."""

    def __init__(self, pages):
        self.pages = list(pages)
        self.queries = []

    def query(self, **kwargs):
        self.queries.append(kwargs)
        return self.pages[len(self.queries) - 1]


def test_query_range_delegates_to_the_shared_digest_util(monkeypatch):
    """#970: this module must not carry its own paginator."""
    seen = {}

    def _fake(table, source, start_date, end_date, user_id="matthew"):
        seen.update(table=table, source=source, start=start_date, end=end_date, user_id=user_id)
        return {"2026-07-30": {"sleep_score": 70}}

    monkeypatch.setattr(partner.digest_utils, "query_range", _fake)
    assert partner.query_range("whoop", WEEK_START, WEEK_END) == {"2026-07-30": {"sleep_score": 70}}
    assert seen == {"table": partner.table, "source": "whoop", "start": WEEK_START, "end": WEEK_END, "user_id": partner.USER_ID}


def test_query_journal_range_groups_by_date_paginates_and_converts_decimals(monkeypatch):
    from decimal import Decimal

    pk = "USER#%s#SOURCE#notion" % partner.USER_ID
    page1 = {
        "Items": [
            {"pk": pk, "sk": "DATE#2026-07-30#journal#001", "enriched_mood": Decimal("4")},
            {"pk": pk, "sk": "DATE#2026-07-30#journal#002", "enriched_mood": Decimal("3.5")},
        ],
        "LastEvaluatedKey": {"pk": pk, "sk": "DATE#2026-07-30#journal#002"},
    }
    page2 = {"Items": [{"pk": pk, "sk": "DATE#2026-08-01#journal#001", "enriched_stress": Decimal("2")}]}
    fake = _FakeTable([page1, page2])
    monkeypatch.setattr(partner, "table", fake)

    out = partner.query_journal_range(WEEK_START, WEEK_END)
    assert sorted(out) == ["2026-07-30", "2026-08-01"]
    assert len(out["2026-07-30"]) == 2
    assert out["2026-07-30"][1]["enriched_mood"] == 3.5
    assert isinstance(out["2026-07-30"][1]["enriched_mood"], float)  # d2f applied
    assert out["2026-08-01"][0]["enriched_stress"] == 2.0
    assert isinstance(out, dict) and not hasattr(out, "default_factory")  # plain dict, not defaultdict


def test_query_journal_range_scopes_the_key_range_and_applies_the_phase_filter(monkeypatch):
    fake = _FakeTable([{"Items": []}])
    monkeypatch.setattr(partner, "table", fake)
    partner.query_journal_range(WEEK_START, WEEK_END)

    kwargs = fake.queries[0]
    vals = kwargs["ExpressionAttributeValues"]
    assert vals[":pk"] == "USER#%s#SOURCE#notion" % partner.USER_ID
    assert vals[":s"] == "DATE#" + WEEK_START + "#journal#"
    assert vals[":e"] == "DATE#" + WEEK_END + "#journal#zzz"
    # ADR-058 default-deny: pilot-phase rows must be filtered out
    assert "#phase" in kwargs["ExpressionAttributeNames"]
    assert "attribute_not_exists(#phase)" in kwargs["FilterExpression"]


def test_query_journal_range_passes_the_cursor_forward_on_the_second_page(monkeypatch):
    cursor = {"pk": "p", "sk": "s"}
    fake = _FakeTable([{"Items": [], "LastEvaluatedKey": cursor}, {"Items": []}])
    monkeypatch.setattr(partner, "table", fake)
    partner.query_journal_range(WEEK_START, WEEK_END)

    assert len(fake.queries) == 2
    assert "ExclusiveStartKey" not in fake.queries[0]
    assert fake.queries[1]["ExclusiveStartKey"] == cursor


def test_fetch_profile_delegates_to_intelligence_common(monkeypatch):
    import intelligence.intelligence_common as ic

    seen = {}

    def _fake(table, user_id):
        seen.update(table=table, user_id=user_id)
        return {"goal_weight_lbs": 185}

    monkeypatch.setattr(ic, "fetch_profile", _fake)
    assert partner.fetch_profile() == {"goal_weight_lbs": 185}
    assert seen == {"table": partner.table, "user_id": partner.USER_ID}


# ══════════════════════════════════════════════════════════════════════════════
# gather_all
# ══════════════════════════════════════════════════════════════════════════════

PROFILE = {
    "calorie_target": 1800,
    "protein_target_g": 190,
    "max_heart_rate": 186,
    "goal_weight_lbs": 185,
    "journey_start_weight_lbs": 300,
    "journey_start_date": "2026-07-16",
}

RAW = {
    "whoop": {
        "2026-07-30": {
            "sleep_quality_score": 80,
            "sleep_duration_hours": 7.0,
            "slow_wave_sleep_hours": 1.4,
            "recovery_score": 70,
            "hrv": 60,
        },
        "2026-07-31": {"sleep_score": 60, "sleep_duration_hours": 6.0, "recovery_score": 50, "hrv": 40},
    },
    "apple_health": {},
    "macrofactor": {
        "2026-07-30": {"total_calories_kcal": 1700, "total_protein_g": 200},
        "2026-07-31": {"total_calories_kcal": 2400, "total_protein_g": 150},
    },
    "habitify": {"2026-07-30": {"completion_pct": 0.8}, "2026-07-31": {"completion_pct": 0.6}},
    "strava": {
        "2026-07-30": {
            "activities": [
                {"average_heartrate": 120, "moving_time_seconds": 1800},  # in zone 2 (111.6–130.2)
                {"average_heartrate": 160, "moving_time_seconds": 600},  # above zone 2
            ]
        }
    },
    "withings": {"2026-07-30": {"weight_lbs": 296.0}, "2026-08-04": {"weight_lbs": 293.5}},
    "day_grade": {"2026-07-30": {"total_score": 72}, "2026-07-31": {"total_score": 60}},
}

JOURNAL = {
    "2026-07-30": [
        {
            "enriched_mood": 4,
            "enriched_energy": 3,
            "enriched_stress": 2,
            "enriched_themes": ["work", "sleep"],
            "enriched_emotions": ["tired"],
            "enriched_avoidance_flags": ["scrolling"],
            "enriched_defense_patterns": ["intellectualising"],
            "enriched_notable_quote": "I keep pushing.",
        }
    ],
    "2026-07-31": [
        {
            "morning_mood": 3,
            "morning_energy": 4,
            "stress_level": 3,
            "enriched_themes": ["work"],
            "enriched_emotions": ["tired", "flat"],
            "enriched_notable_quote": "Quieter today.",
        }
    ],
}


def _wire_gather(monkeypatch, raw=None, journal=None, profile=None):
    """Point gather_all at in-memory fixtures and a pinned clock."""
    raw = RAW if raw is None else raw
    journal = JOURNAL if journal is None else journal
    profile = PROFILE if profile is None else profile
    seen = {"ranges": []}

    def _query_range(source, start_date, end_date):
        seen["ranges"].append((source, start_date, end_date))
        return raw.get(source, {})

    monkeypatch.setattr(partner, "datetime", _FixedDatetime)
    freeze_pacific(monkeypatch, partner, _FixedDatetime)  # #2817: pin the PACIFIC helpers this module now calls
    monkeypatch.setattr(partner, "query_range", _query_range)
    monkeypatch.setattr(partner, "query_journal_range", lambda s, e: journal)
    monkeypatch.setattr(partner, "fetch_profile", lambda: profile)
    return seen


def test_gather_all_uses_the_trailing_seven_day_window_ending_yesterday(monkeypatch):
    seen = _wire_gather(monkeypatch)
    data = partner.gather_all()
    assert data["dates"] == {"start": WEEK_START, "end": WEEK_END}
    # every source is queried over exactly that window
    assert {r[1:] for r in seen["ranges"]} == {(WEEK_START, WEEK_END)}
    assert [r[0] for r in seen["ranges"]] == [
        "whoop",
        "apple_health",
        "macrofactor",
        "habitify",
        "strava",
        "withings",
        "day_grade",
    ]


def test_gather_all_sleep_and_recovery_aggregates(monkeypatch):
    _wire_gather(monkeypatch)
    data = partner.gather_all()
    assert data["sleep"] == {"score_avg": 70.0, "duration_avg": 6.5, "nights": 2, "quality_label": "mixed"}
    assert data["recovery"] == {"avg": 60.0, "hrv_avg": 50.0}


def test_gather_all_mood_aggregates_fall_back_through_the_field_ladder(monkeypatch):
    _wire_gather(monkeypatch)
    mood = partner.gather_all()["mood"]
    # day 1 uses enriched_*, day 2 has none so morning_mood / stress_level are used
    assert mood["mood_avg"] == 3.5
    assert mood["energy_avg"] == 3.5
    assert mood["stress_avg"] == 2.5
    assert mood["mood_label"] == "neutral"
    assert mood["entries"] == 2
    assert mood["days_journaled"] == 2
    assert mood["top_themes"] == [("work", 2), ("sleep", 1)]
    assert mood["top_emotions"] == [("tired", 2), ("flat", 1)]
    assert mood["avoidance_flags"] == ["scrolling"]
    assert mood["defense_patterns"] == ["intellectualising"]
    assert mood["notable_quotes"] == [
        {"date": "2026-07-30", "quote": "I keep pushing."},
        {"date": "2026-07-31", "quote": "Quieter today."},
    ]


def test_gather_all_nutrition_hit_rates_use_the_ten_percent_calorie_grace(monkeypatch):
    _wire_gather(monkeypatch)
    nu = partner.gather_all()["nutrition"]
    assert nu["calories_avg"] == 2050.0
    assert nu["protein_avg"] == 175.0
    assert nu["days_logged"] == 2
    assert nu["cal_hit_rate"] == 50  # 1700 <= 1800*1.1; 2400 is not
    assert nu["prot_hit_rate"] == 50  # 200 >= 190; 150 is not
    assert nu["cal_target"] == 1800
    assert nu["prot_target"] == 190


def test_gather_all_zone2_counts_only_activities_inside_the_hr_band(monkeypatch):
    _wire_gather(monkeypatch)
    tr = partner.gather_all()["training"]
    assert tr["activity_count"] == 2  # both activities counted
    assert tr["zone2_minutes"] == 30  # only the 120 bpm / 30 min one is in-band
    assert tr["zone2_target"] == 150


def test_gather_all_weight_progress_math(monkeypatch):
    _wire_gather(monkeypatch)
    w = partner.gather_all()["weight"]
    assert w["latest"] == 293.5  # chronologically last, not dict order
    assert w["week_delta"] == -2.5
    assert w["lbs_lost"] == 6.5
    assert w["lbs_to_go"] == 108.5
    assert w["pct_to_goal"] == 6  # 6.5 / (300-185) → 5.65% → 6
    assert w["goal"] == 185
    assert w["journey_start"] == 300


def test_gather_all_habits_and_day_grade_labels(monkeypatch):
    _wire_gather(monkeypatch)
    data = partner.gather_all()
    assert data["habits"] == {"avg_pct": 70, "days_tracked": 2}  # fractions scaled to %
    assert data["day_grade"] == {"avg": 66.0, "days": 2, "week_summary": "solid week"}


def test_gather_all_journey_week_is_one_indexed_from_the_profile_start(monkeypatch):
    _wire_gather(monkeypatch)
    # 2026-07-16 → 2026-08-06 is 21 days → week 4
    assert partner.gather_all()["journey_week"] == 4


def test_gather_all_journey_week_floors_at_one_for_a_future_genesis(monkeypatch):
    _wire_gather(monkeypatch, profile=dict(PROFILE, journey_start_date="2026-09-01"))
    assert partner.gather_all()["journey_week"] == 1


def test_gather_all_with_no_data_emits_honest_no_data_labels(monkeypatch):
    _wire_gather(monkeypatch, raw={}, journal={}, profile={"journey_start_date": "2026-08-01"})
    data = partner.gather_all()
    assert data["sleep"] == {"score_avg": None, "duration_avg": None, "nights": 0, "quality_label": "no data"}
    assert data["recovery"] == {"avg": None, "hrv_avg": None}
    assert data["mood"]["mood_label"] == "no data"
    assert data["mood"]["mood_avg"] is None
    assert data["mood"]["top_themes"] == []
    assert data["day_grade"] == {"avg": None, "days": 0, "week_summary": "no data"}
    assert data["nutrition"]["cal_hit_rate"] is None
    assert data["nutrition"]["prot_hit_rate"] is None
    assert data["training"] == {"activity_count": 0, "zone2_minutes": 0, "zone2_target": 150}
    assert data["weight"]["latest"] is None
    assert data["weight"]["lbs_lost"] is None
    assert data["habits"] == {"avg_pct": None, "days_tracked": 0}


@pytest.mark.parametrize(
    "score,label",
    [(90, "good"), (80, "good"), (79.9, "mixed"), (60, "mixed"), (59.9, "poor"), (10, "poor")],
)
def test_gather_all_sleep_quality_label_thresholds(monkeypatch, score, label):
    _wire_gather(monkeypatch, raw={"whoop": {"2026-07-30": {"sleep_score": score, "sleep_duration_hours": 7}}}, journal={})
    assert partner.gather_all()["sleep"]["quality_label"] == label


@pytest.mark.parametrize("mood,label", [(5, "positive"), (4, "positive"), (3.9, "neutral"), (3, "neutral"), (2.9, "struggling")])
def test_gather_all_mood_label_thresholds(monkeypatch, mood, label):
    _wire_gather(monkeypatch, raw={}, journal={"2026-07-30": [{"enriched_mood": mood}]})
    assert partner.gather_all()["mood"]["mood_label"] == label


@pytest.mark.parametrize(
    "grade,label",
    [
        (95, "strong week"),
        (80, "strong week"),
        (79, "solid week"),
        (65, "solid week"),
        (64, "mixed week"),
        (50, "mixed week"),
        (49, "tough week"),
    ],
)
def test_gather_all_week_summary_thresholds(monkeypatch, grade, label):
    _wire_gather(monkeypatch, raw={"day_grade": {"2026-07-30": {"total_score": grade}}}, journal={})
    assert partner.gather_all()["day_grade"]["week_summary"] == label


# ══════════════════════════════════════════════════════════════════════════════
# parse_sections
# ══════════════════════════════════════════════════════════════════════════════

COMMENTARY = """Here is the update you asked for.

🪞 THIS WEEK IN ONE LINE
He carried a heavy week without saying so out loud.

## 💚 HOW HE'S FEELING — COACH RODRIGUEZ
He is tired in a way sleep alone will not fix.
He is also proud of showing up anyway.

**🧠 WHAT'S HAPPENING UNDERNEATH — DR. CONTI
He is measuring instead of feeling.

🤝 HOW TO SHOW UP FOR HIM — DR. MURTHY
Sit with him without a plan.

💪 HIS BODY THIS WEEK — THE CHAIR
The body is keeping up, barely."""


def test_parse_sections_splits_all_five_and_drops_the_preamble():
    s = partner.parse_sections(COMMENTARY)
    assert sorted(s) == ["chair", "conti", "lede", "murthy", "rodriguez"]
    # text before the first emoji header is discarded, not attached to a section
    assert "Here is the update you asked for." not in "\n".join(s.values())


def test_parse_sections_keeps_the_header_line_and_the_body_together():
    s = partner.parse_sections(COMMENTARY)
    assert s["lede"].startswith("🪞 THIS WEEK IN ONE LINE")
    assert s["lede"].endswith("He carried a heavy week without saying so out loud.")


def test_parse_sections_tolerates_markdown_heading_and_bold_markers():
    s = partner.parse_sections(COMMENTARY)
    # "## 💚 …" and "**🧠 …" still register as headers
    assert s["rodriguez"].startswith("## 💚")
    assert "He is tired in a way sleep alone will not fix." in s["rodriguez"]
    assert s["conti"].startswith("**🧠")
    assert "He is measuring instead of feeling." in s["conti"]


def test_parse_sections_multi_paragraph_body_preserved():
    s = partner.parse_sections(COMMENTARY)
    assert "He is also proud of showing up anyway." in s["rodriguez"]
    # and does not bleed into the next section
    assert "He is also proud" not in s["conti"]


def test_parse_sections_returns_empty_when_no_headers_present():
    assert partner.parse_sections("Just some prose with no emoji headers at all.") == {}


def test_parse_sections_partial_output_yields_only_the_sections_present():
    s = partner.parse_sections("💚 FEELING\nOne line.\n\n💪 BODY\nAnother line.")
    assert sorted(s) == ["chair", "rodriguez"]
    assert s["chair"] == "💪 BODY\nAnother line."


# ══════════════════════════════════════════════════════════════════════════════
# section_html
# ══════════════════════════════════════════════════════════════════════════════


def test_section_html_empty_input_renders_nothing():
    assert partner.section_html("", "#22c55e", "#f0fdf4", "#15803d") == ""
    assert partner.section_html(None, "#22c55e", "#f0fdf4", "#15803d") == ""


def test_section_html_wraps_in_an_accented_card():
    html = partner.section_html("💚 FEELING\nHe is doing okay.", "#22c55e", "#f0fdf4", "#15803d")
    assert html.startswith('<div style="background:#f0fdf4;border-left:4px solid #22c55e;')
    assert html.endswith("</div>")


def test_section_html_styles_the_emoji_header_differently_from_the_body():
    html = partner.section_html("💚 FEELING\nHe is doing okay.", "#22c55e", "#f0fdf4", "#15803d")
    assert "font-weight:700;color:#15803d;text-transform:uppercase" in html
    assert ">💚 FEELING</p>" in html
    assert '<p style="font-size:15px;color:#2d3748;line-height:1.8;margin:0 0 14px;">He is doing okay.</p>' in html


def test_section_html_drops_blank_lines_and_emits_one_p_per_paragraph():
    html = partner.section_html("💚 H\n\nOne.\n\n\nTwo.\n", "#22c55e", "#f0fdf4", "#15803d")
    assert html.count("<p ") == 3  # header + two paragraphs
    assert "<p ></p>" not in html


# ══════════════════════════════════════════════════════════════════════════════
# weight_sentence
# ══════════════════════════════════════════════════════════════════════════════


def test_weight_sentence_is_empty_without_a_current_weight():
    assert partner.weight_sentence({}) == ""
    assert partner.weight_sentence({"latest": None, "lbs_lost": 6.5}) == ""


def test_weight_sentence_loss_reads_as_down():
    s = partner.weight_sentence({"latest": 293.5, "week_delta": -2.5, "lbs_lost": 6.5, "pct_to_goal": 6})
    assert s == "down 2.5 lbs this week · 6.5 lbs lost overall · 6% of the way to his goal"


def test_weight_sentence_gain_reads_as_up():
    s = partner.weight_sentence({"latest": 296.0, "week_delta": 1.2, "lbs_lost": 4.0, "pct_to_goal": 3})
    assert s.startswith("up 1.2 lbs this week")


def test_weight_sentence_holds_steady_for_zero_or_missing_delta():
    assert partner.weight_sentence({"latest": 296.0, "week_delta": 0}) == "holding steady this week"
    assert partner.weight_sentence({"latest": 296.0}) == "holding steady this week"


def test_weight_sentence_omits_clauses_it_has_no_data_for():
    s = partner.weight_sentence({"latest": 296.0, "week_delta": -1.0, "lbs_lost": None, "pct_to_goal": None})
    assert s == "down 1.0 lbs this week"
    assert "·" not in s


# ══════════════════════════════════════════════════════════════════════════════
# signal_dot
# ══════════════════════════════════════════════════════════════════════════════


def test_signal_dot_no_data_is_a_grey_hollow_circle():
    html = partner.signal_dot("Mood: no data", None, None)
    assert 'color:#9ca3af;font-size:10px;">○</span>' in html
    assert html.endswith("Mood: no data</span>")


def test_signal_dot_good_is_green_filled():
    assert 'color:#059669;font-size:10px;">●</span>' in partner.signal_dot("Sleep: good", True, True)


def test_signal_dot_not_good_but_neutral_is_amber():
    assert 'color:#d97706;font-size:10px;">●</span>' in partner.signal_dot("Sleep: mixed", False, True)


def test_signal_dot_not_good_and_not_neutral_is_red():
    assert 'color:#dc2626;font-size:10px;">●</span>' in partner.signal_dot("Sleep: poor", False, False)


def test_signal_dot_missing_neutral_argument_falls_through_to_red():
    assert 'color:#dc2626;font-size:10px;">●</span>' in partner.signal_dot("Week: tough week", False)


# ══════════════════════════════════════════════════════════════════════════════
# build_html
# ══════════════════════════════════════════════════════════════════════════════


def _data(**over):
    base = {
        "sleep": {"score_avg": 70.0, "duration_avg": 6.5, "nights": 2, "quality_label": "mixed"},
        "recovery": {"avg": 60.0, "hrv_avg": 50.0},
        "mood": {
            "mood_avg": 3.5,
            "energy_avg": 3.5,
            "stress_avg": 2.5,
            "mood_label": "neutral",
            "entries": 2,
            "days_journaled": 2,
            "top_themes": [("work", 2), ("sleep", 1)],
            "top_emotions": [("tired", 2)],
            "avoidance_flags": ["scrolling"],
            "defense_patterns": ["intellectualising"],
            "notable_quotes": [{"date": "2026-07-30", "quote": "I keep pushing."}, {"date": "2026-07-31", "quote": "Quieter today."}],
        },
        "nutrition": {
            "calories_avg": 2050.0,
            "protein_avg": 175.0,
            "days_logged": 2,
            "cal_hit_rate": 50,
            "prot_hit_rate": 50,
            "cal_target": 1800,
            "prot_target": 190,
        },
        "training": {"activity_count": 2, "zone2_minutes": 30, "zone2_target": 150},
        "weight": {
            "latest": 293.5,
            "week_delta": -2.5,
            "lbs_lost": 6.5,
            "lbs_to_go": 108.5,
            "pct_to_goal": 6,
            "goal": 185,
            "journey_start": 300,
        },
        "habits": {"avg_pct": 70, "days_tracked": 2},
        "day_grade": {"avg": 66.0, "days": 2, "week_summary": "solid week"},
        "dates": {"start": WEEK_START, "end": WEEK_END},
        "journey_week": 4,
        "profile": PROFILE,
    }
    base.update(over)
    return base


def test_build_html_renders_a_human_week_label():
    html = partner.build_html(_data(), COMMENTARY)
    assert "Jul 30 – Aug 5, 2026" in html


def test_build_html_falls_back_to_raw_dates_when_they_are_unparseable():
    html = partner.build_html(_data(dates={"start": "week-of", "end": "sunday"}), COMMENTARY)
    assert "week-of – sunday" in html


def test_build_html_lede_uses_the_first_body_line_not_the_emoji_header():
    html = partner.build_html(_data(), COMMENTARY)
    assert ">This week</p>" in html  # the lede card's eyebrow label
    assert "He carried a heavy week without saying so out loud." in html
    assert "THIS WEEK IN ONE LINE" not in html


def test_build_html_omits_the_lede_card_when_the_ai_gave_no_lede():
    html = partner.build_html(_data(), "💚 FEELING\nHe is doing okay.")
    assert ">This week</p>" not in html
    assert "He is doing okay." in html  # the section that DID come back still renders


def test_build_html_renders_every_board_section_with_its_own_accent():
    html = partner.build_html(_data(), COMMENTARY)
    for accent, line in [
        ("#22c55e", "He is tired in a way sleep alone will not fix."),
        ("#a855f7", "He is measuring instead of feeling."),
        ("#3b82f6", "Sit with him without a plan."),
        ("#6b7280", "The body is keeping up, barely."),
    ]:
        assert "border-left:4px solid " + accent in html
        assert line in html


def test_build_html_at_a_glance_dots_reflect_the_metric_bands():
    html = partner.build_html(
        _data(
            mood={**_data()["mood"], "mood_avg": 4.0, "mood_label": "positive"},
            sleep={"score_avg": 60.0, "duration_avg": 6.0, "nights": 3, "quality_label": "mixed"},
            day_grade={"avg": 40.0, "days": 3, "week_summary": "tough week"},
        ),
        COMMENTARY,
    )
    assert "At a glance" in html
    assert partner.signal_dot("Mood: positive", True, True) in html  # 4.0 >= 3.5 → green
    assert partner.signal_dot("Sleep: mixed", False, True) in html  # 55 <= 60 < 70 → amber
    assert partner.signal_dot("Week: tough week", False, False) in html  # 40 < 55 → red


def test_build_html_glance_dots_are_hollow_when_there_is_no_data():
    html = partner.build_html(
        _data(
            mood={**_data()["mood"], "mood_avg": None, "mood_label": "no data", "notable_quotes": []},
            sleep={"score_avg": None, "duration_avg": None, "nights": 0, "quality_label": "no data"},
            day_grade={"avg": None, "days": 0, "week_summary": "no data"},
        ),
        COMMENTARY,
    )
    assert html.count('color:#9ca3af;font-size:10px;">○</span>') == 3


def test_build_html_renders_at_most_one_journal_quote_with_its_date():
    html = partner.build_html(_data(), COMMENTARY)
    assert '"I keep pushing."' in html
    assert "From his journal · 2026-07-30" in html
    assert "Quieter today." not in html  # only the first quote is surfaced


def test_build_html_omits_the_quote_card_when_there_are_no_quotes():
    html = partner.build_html(_data(mood={**_data()["mood"], "notable_quotes": []}), COMMENTARY)
    assert "From his journal" not in html


def test_build_html_never_leaks_raw_numbers_or_the_weight_block():
    """Design rule: the partner email is narrative — no dashboards, no weight line."""
    html = partner.build_html(_data(), COMMENTARY)
    for leaked in ("293.5", "lbs lost overall", "% of the way to his goal", "2050", "zone2", "HRV"):
        assert leaked not in html


def test_build_html_is_a_complete_document_with_the_partner_framing():
    html = partner.build_html(_data(), COMMENTARY)
    assert html.startswith("<!DOCTYPE html>")
    assert html.rstrip().endswith("</html>")
    assert "For Partner · Weekly Update" in html
    assert "How Matthew's Week Went" in html


# ══════════════════════════════════════════════════════════════════════════════
# _recipient
# ══════════════════════════════════════════════════════════════════════════════


class _FakeSsm:
    def __init__(self, value=None, error=None):
        self.value = value
        self.error = error
        self.calls = []

    def get_parameter(self, Name):  # noqa: N803 - boto3 kwarg casing
        self.calls.append(Name)
        if self.error:
            raise self.error
        return {"Parameter": {"Value": self.value}}


class _FakeBoto3:
    def __init__(self, ssm):
        self.ssm = ssm

    def client(self, service, **kwargs):
        assert service == "ssm"
        return self.ssm


def test_recipient_reads_and_strips_the_ssm_parameter(monkeypatch):
    ssm = _FakeSsm(value="  partner@example.com \n")
    monkeypatch.setattr(partner, "boto3", _FakeBoto3(ssm))
    assert partner._recipient() == "partner@example.com"
    assert ssm.calls == [partner._RECIPIENT_PARAM]


def test_recipient_is_cached_warm_after_the_first_lookup(monkeypatch):
    ssm = _FakeSsm(value="partner@example.com")
    monkeypatch.setattr(partner, "boto3", _FakeBoto3(ssm))
    partner._recipient()
    partner._recipient()
    partner._recipient()
    assert len(ssm.calls) == 1  # one SSM read per warm container, not per call


def test_recipient_falls_back_to_the_env_var_when_ssm_fails(monkeypatch):
    monkeypatch.setattr(partner, "boto3", _FakeBoto3(_FakeSsm(error=RuntimeError("ParameterNotFound"))))
    monkeypatch.setenv("PARTNER_EMAIL", "fallback@example.com")
    assert partner._recipient() == "fallback@example.com"


def test_recipient_fallback_default_is_the_owners_own_address(monkeypatch):
    """No SSM parameter and no env override → the mail goes to Matthew, never nowhere."""
    monkeypatch.setattr(partner, "boto3", _FakeBoto3(_FakeSsm(error=RuntimeError("boom"))))
    monkeypatch.delenv("PARTNER_EMAIL", raising=False)
    got = partner._recipient()
    assert got == "awsdev@mattsusername.com"


# ══════════════════════════════════════════════════════════════════════════════
# build_commentary
# ══════════════════════════════════════════════════════════════════════════════


def test_build_commentary_composes_the_anthropic_payload_and_returns_the_text(monkeypatch):
    import common.retry_utils as retry_utils

    captured = {}

    def _fake_call(req, timeout=55):
        captured["req"] = req
        captured["timeout"] = timeout
        return {"content": [{"text": "🪞 THIS WEEK IN ONE LINE\nHe held the line."}]}

    monkeypatch.setattr(retry_utils, "call_anthropic_raw", _fake_call)
    monkeypatch.setenv("AI_MODEL", "claude-sonnet-4-6")

    out = partner.build_commentary(_data())
    assert out == "🪞 THIS WEEK IN ONE LINE\nHe held the line."

    req = captured["req"]
    assert req.full_url == "https://api.anthropic.com/v1/messages"
    assert req.get_method() == "POST"
    body = json.loads(req.data.decode())
    assert body["model"] == "claude-sonnet-4-6"
    assert body["max_tokens"] == 1400
    assert len(body["messages"]) == 1
    assert body["messages"][0]["role"] == "user"
    assert captured["timeout"] == 45


def test_build_commentary_prompt_is_fully_substituted_with_this_weeks_context(monkeypatch):
    import common.retry_utils as retry_utils

    captured = {}

    def _fake_call(req, timeout=55):
        captured["p"] = json.loads(req.data.decode())["messages"][0]["content"]
        return {"content": [{"text": "ok"}]}

    monkeypatch.setattr(retry_utils, "call_anthropic_raw", _fake_call)
    partner.build_commentary(_data())
    prompt = captured["p"]
    assert "{" not in prompt and "}" not in prompt  # no unsubstituted placeholders
    assert "week 4 of his transformation" in prompt
    assert "Overall week: solid week" in prompt
    assert "Mood: neutral (avg 3.5/5" in prompt
    assert "Sleep quality: mixed (70.0% avg Whoop score, 2 nights tracked)" in prompt
    assert "Training: 2 workouts this week" in prompt
    assert "Journal themes: work, sleep" in prompt
    assert "Emotional patterns: tired" in prompt
    assert "Avoidance flags: scrolling" in prompt
    assert 'Notable journal quotes: "I keep pushing." | "Quieter today."' in prompt


def test_build_commentary_renders_unknown_and_none_for_absent_signals(monkeypatch):
    import common.retry_utils as retry_utils

    captured = {}

    def _fake_call(req, timeout=55):
        captured["p"] = json.loads(req.data.decode())["messages"][0]["content"]
        return {"content": [{"text": "ok"}]}

    monkeypatch.setattr(retry_utils, "call_anthropic_raw", _fake_call)
    empty = _data(
        sleep={"score_avg": None, "duration_avg": None, "nights": 0, "quality_label": "no data"},
        recovery={"avg": None, "hrv_avg": None},
        mood={
            "mood_avg": None,
            "energy_avg": None,
            "stress_avg": None,
            "mood_label": "no data",
            "top_themes": [],
            "top_emotions": [],
            "avoidance_flags": [],
            "defense_patterns": [],
            "notable_quotes": [],
        },
        day_grade={"avg": None, "days": 0, "week_summary": "no data"},
    )
    partner.build_commentary(empty)
    prompt = captured["p"]
    assert "Mood: no data (avg unknown/5" in prompt
    assert "Recovery: unknown% average" in prompt
    assert "Journal themes: none" in prompt
    assert "Emotional patterns: none" in prompt
    assert "Avoidance flags: none" in prompt
    assert "Defence patterns: none" in prompt
    assert "Notable journal quotes: none" in prompt


def test_build_commentary_holds_when_retry_utils_is_absent(monkeypatch):
    """#2423: the direct-bedrock fallback seam is GONE. retry_utils ships in every
    bundle (#781); if the import genuinely fails, the narrative is held (None) and
    the handler sends the deterministic data-only email — never an ungated
    narrative through a second seam."""
    monkeypatch.setitem(sys.modules, "common.retry_utils", None)  # → ImportError on the from-import
    assert partner.build_commentary(_data()) is None


def test_module_has_no_bedrock_import():
    """The #2390 census counts seams; this module's second one must stay retired."""
    import inspect

    src = inspect.getsource(partner)
    assert "bedrock_client" not in src


# ── #2423: the grounding gate — regenerate once, then HOLD ────────────────────


def _wire_model(monkeypatch, texts):
    """Feed _call_model successive responses; capture the prompts it was sent."""
    import common.retry_utils as retry_utils

    calls = {"prompts": []}
    replies = list(texts)

    def _fake_call(req, timeout=55):
        calls["prompts"].append(json.loads(req.data.decode())["messages"][0]["content"])
        return {"content": [{"text": replies[len(calls["prompts"]) - 1]}]}

    monkeypatch.setattr(retry_utils, "call_anthropic_raw", _fake_call)
    return calls


FABRICATED = "🪞 THIS WEEK IN ONE LINE\nHis recovery sat at 133 all week, which says everything."
CLEAN = "🪞 THIS WEEK IN ONE LINE\nHe carried a heavy week without saying so out loud."


def test_grounded_commentary_passes_on_the_first_call(monkeypatch):
    calls = _wire_model(monkeypatch, [CLEAN])
    assert partner.build_commentary(_data()) == CLEAN
    assert len(calls["prompts"]) == 1


def test_fabricated_number_triggers_one_regeneration_with_the_correction(monkeypatch):
    calls = _wire_model(monkeypatch, [FABRICATED, CLEAN])
    assert partner.build_commentary(_data()) == CLEAN
    assert len(calls["prompts"]) == 2
    assert "CORRECTION REQUIRED" in calls["prompts"][1]
    assert calls["prompts"][1].startswith(calls["prompts"][0])  # base prompt + addendum


def test_fabricated_number_that_survives_regeneration_is_held(monkeypatch):
    """Regenerate-once-then-HOLD: a draft that still fabricates after the one
    correction pass returns None — the partner never receives it."""
    calls = _wire_model(monkeypatch, [FABRICATED, FABRICATED])
    assert partner.build_commentary(_data()) is None
    assert len(calls["prompts"]) == 2  # once, not a retry loop


def test_gate_allows_numbers_the_prompt_actually_contains(monkeypatch):
    """A guard that rejects everything is a guard nobody keeps: a figure handed to
    the model in the prompt (the 70.0 sleep-score average — NOT in the benign set)
    is grounded, not fabricated."""
    grounded = "🪞 THIS WEEK IN ONE LINE\nHis sleep hovered around 70 and he kept showing up anyway."
    calls = _wire_model(monkeypatch, [grounded])
    assert partner.build_commentary(_data()) == grounded
    assert len(calls["prompts"]) == 1


def test_build_commentary_respects_the_ai_model_env_override(monkeypatch):
    import common.retry_utils as retry_utils

    captured = {}

    def _fake_call(req, timeout=55):
        captured["m"] = json.loads(req.data.decode())["model"]
        return {"content": [{"text": "ok"}]}

    monkeypatch.setattr(retry_utils, "call_anthropic_raw", _fake_call)
    monkeypatch.setenv("AI_MODEL", "claude-haiku-4-5")
    partner.build_commentary(_data())
    assert captured["m"] == "claude-haiku-4-5"


# ══════════════════════════════════════════════════════════════════════════════
# lambda_handler
# ══════════════════════════════════════════════════════════════════════════════


def test_handler_kill_switch_skips_without_gathering_or_sending(monkeypatch):
    def _boom():
        raise AssertionError("gather_all must not run when the kill switch is off")

    monkeypatch.setenv("EXTERNAL_EMAILS_ENABLED", "false")
    monkeypatch.setattr(partner, "gather_all", _boom)
    # partner.ses is the ExplodingSes from the autouse fixture

    resp = partner.lambda_handler({}, None)
    assert resp["statusCode"] == 200
    assert resp["skipped"] is True
    assert "external emails disabled" in resp["body"]


@pytest.mark.parametrize("flag", ["FALSE", "0", "no", "off"])
def test_handler_kill_switch_is_any_non_true_value(monkeypatch, flag):
    monkeypatch.setenv("EXTERNAL_EMAILS_ENABLED", flag)
    monkeypatch.setattr(partner, "gather_all", lambda: (_ for _ in ()).throw(AssertionError("must not gather")))
    assert partner.lambda_handler({}, None).get("skipped") is True


def _wire_handler(monkeypatch, commentary=COMMENTARY):
    fake_ses = FakeSes()
    monkeypatch.delenv("EXTERNAL_EMAILS_ENABLED", raising=False)
    monkeypatch.setattr(partner, "ses", fake_ses)
    monkeypatch.setattr(partner, "gather_all", lambda: _data())
    monkeypatch.setattr(partner, "_recipient", lambda: "partner@example.com")
    if isinstance(commentary, Exception):
        monkeypatch.setattr(partner, "build_commentary", lambda d: (_ for _ in ()).throw(commentary))
    else:
        monkeypatch.setattr(partner, "build_commentary", lambda d: commentary)
    return fake_ses


def test_handler_sends_one_email_with_the_expected_ses_envelope(monkeypatch):
    fake_ses = _wire_handler(monkeypatch)
    resp = partner.lambda_handler({}, None)

    assert resp["statusCode"] == 200
    assert len(fake_ses.sends) == 1
    sent = fake_ses.sends[0]
    assert sent["FromEmailAddress"] == partner.SENDER
    assert sent["Destination"] == {"ToAddresses": ["partner@example.com"]}
    assert sent["ConfigurationSetName"] == "life-platform-emails"
    assert sent["EmailTags"] == [{"Name": "message_type", "Value": "partner_weekly"}]
    assert sent["Content"]["Simple"]["Subject"] == {"Data": "Matthew's Week · " + WEEK_END, "Charset": "UTF-8"}
    assert resp["body"].endswith("Matthew's Week · " + WEEK_END)


def test_handler_body_is_the_rendered_board_html(monkeypatch):
    fake_ses = _wire_handler(monkeypatch)
    # Exercise the supported layer-absent path: the AI-3 validator import fails,
    # the handler's `except ImportError: pass` lets the commentary through
    # untouched, and the HTML is rendered from it.
    monkeypatch.setitem(sys.modules, "ai.ai_output_validator", None)
    partner.lambda_handler({}, None)
    body = fake_ses.sends[0]["Content"]["Simple"]["Body"]["Html"]
    assert body["Charset"] == "UTF-8"
    html = body["Data"]
    assert html.startswith("<!DOCTYPE html>")
    assert "He carried a heavy week without saying so out loud." in html
    assert "Sit with him without a plan." in html
    assert "Jul 30 – Aug 5, 2026" in html


def test_handler_still_sends_a_fallback_when_the_ai_call_fails(monkeypatch):
    fake_ses = _wire_handler(monkeypatch, commentary=RuntimeError("bedrock throttled"))
    resp = partner.lambda_handler({}, None)

    assert resp["statusCode"] == 200
    assert len(fake_ses.sends) == 1  # a failed AI call must not silence the week
    html = fake_ses.sends[0]["Content"]["Simple"]["Body"]["Html"]["Data"]
    assert "The written update is unavailable this week" in html
    assert "The full written update returns next week." in html
    # the data-only body carries the deterministic labels, never model prose
    assert "Overall: solid week. Mood: neutral. Sleep: mixed." in html


def test_handler_grounding_hold_sends_the_data_only_email(monkeypatch):
    """#2423 regenerate-once-then-HOLD, end to end: build_commentary returning None
    (a held draft) must produce the deterministic data-only email — a fabricated
    narrative never reaches a third-party recipient."""
    fake_ses = _wire_handler(monkeypatch, commentary=None)
    resp = partner.lambda_handler({}, None)

    assert resp["statusCode"] == 200
    assert len(fake_ses.sends) == 1  # held narrative ≠ silenced week
    html = fake_ses.sends[0]["Content"]["Simple"]["Body"]["Html"]["Data"]
    assert "The written update is unavailable this week" in html
    assert "Overall: solid week. Mood: neutral. Sleep: mixed." in html


def test_handler_ships_clean_commentary_through_the_real_ai3_validator(monkeypatch):
    """AI-3: commentary the real validator does not block must reach the email.

    Fixed by #2173: lambda_handler used to read `_val.was_replaced` /
    `_val.final_text`, but `AIValidationResult` exposes `.blocked` /
    `.block_reason` / `.sanitized_text`. The AttributeError was swallowed by
    the surrounding `except Exception`, so clean Board commentary was
    silently discarded and every partner email shipped the canned
    'Commentary unavailable' stub — this runs the REAL validator (not a
    mock), against realistically-shaped clean input, to prove the fixed
    attribute names actually round-trip end to end.
    """
    fake_ses = _wire_handler(monkeypatch)
    partner.lambda_handler({}, None)
    html = fake_ses.sends[0]["Content"]["Simple"]["Body"]["Html"]["Data"]
    assert "He carried a heavy week without saying so out loud." in html
    assert "Commentary unavailable this week." not in html


def test_handler_ai3_validator_failure_degrades_to_the_stub_not_a_crash(monkeypatch):
    """Whatever the AI-3 seam does, the Sunday send must never raise."""
    fake_ses = _wire_handler(monkeypatch)
    resp = partner.lambda_handler({}, None)
    assert resp["statusCode"] == 200
    assert len(fake_ses.sends) == 1


def test_handler_stub_is_reachable_only_on_a_genuine_ai3_failure_and_logs_loudly(monkeypatch, caplog):
    """The fallback stub must stay reachable if the AI-3 seam itself breaks again —

    but this time the failure must not go quiet: #2173 was hidden for weeks
    because the AttributeError only ever produced a generic one-line
    `logger.warning("AI call failed: %s", e)`. Simulate a genuine validator
    failure (distinct from a `build_commentary` failure, already covered by
    `test_handler_still_sends_a_fallback_when_the_ai_call_fails`) and assert
    both that the stub still ships AND that the failure is logged with a
    traceback (`logger.exception`), not a swallowed one-liner.
    """
    fake_ses = _wire_handler(monkeypatch)
    import ai.ai_output_validator as ai3

    def _boom(text, output_type):
        raise RuntimeError("AI-3 validator itself is broken")

    monkeypatch.setattr(ai3, "validate_ai_output", _boom)

    # partner.logger (common.platform_logger.PlatformLogger) sets propagate=False
    # by design (OBS-1: JSON lines shouldn't double-emit via the root logger), so
    # caplog's root-attached handler never sees it. Attach caplog's handler to the
    # actual logger instance so this test observes exactly what CloudWatch would.
    partner.logger.addHandler(caplog.handler)
    try:
        with caplog.at_level("ERROR", logger=partner.logger.name):
            resp = partner.lambda_handler({}, None)
    finally:
        partner.logger.removeHandler(caplog.handler)

    assert resp["statusCode"] == 200
    html = fake_ses.sends[0]["Content"]["Simple"]["Body"]["Html"]["Data"]
    assert "The written update is unavailable this week" in html
    # logger.exception logs at ERROR level and (unlike the old logger.warning
    # one-liner) attaches exc_info — the traceback is what makes a genuine
    # validator bug findable instead of indistinguishable from a Bedrock hiccup.
    exc_records = [r for r in caplog.records if r.levelname == "ERROR" and r.exc_info]
    assert exc_records, "expected a loudly-logged (exc_info-attached) ERROR record"
    assert any("AI-3 validation failed" in r.message or "AI-3 validation failed" in r.getMessage() for r in exc_records)
    assert fake_ses.sends[0]["Content"]["Simple"]["Body"]["Html"]["Data"].startswith("<!DOCTYPE html>")


# ── #2222: the send-suppressor gate ───────────────────────────────────────────
# Tier A — the recipient here is a real partner, resolved from SSM at runtime
# and never visible in source. An invoke to "see what it looks like" mailed her.


def test_handler_dry_run_builds_the_email_and_mails_nobody(monkeypatch):
    fake_ses = _wire_handler(monkeypatch)

    resp = partner.lambda_handler({"dry_run": True}, None)

    assert fake_ses.sends == [], "a dry run reached SES — this mails a real partner"
    # Not a short-circuit: the handler ran the whole gather/compose path.
    assert resp["statusCode"] == 200


def test_handler_dry_run_env_var_also_suppresses(monkeypatch):
    """Scheduled rules do not let an operator pass a payload."""
    fake_ses = _wire_handler(monkeypatch)
    monkeypatch.setenv("DRY_RUN", "true")

    partner.lambda_handler({}, None)

    assert fake_ses.sends == []


def test_handler_dry_run_false_string_still_sends(monkeypatch):
    """A guard that treats the string "false" as truthy would silently disable
    the weekly email for good — the failure mode nobody would notice."""
    fake_ses = _wire_handler(monkeypatch)

    partner.lambda_handler({"dry_run": "false"}, None)

    assert len(fake_ses.sends) == 1
