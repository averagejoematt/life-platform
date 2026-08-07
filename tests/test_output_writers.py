"""tests/test_output_writers.py — behavioral unit tests for lambdas/content/output_writers.py (#1658).

output_writers is the daily brief's post-email side-effect layer: it computes the
avatar/reward/protocol state that html_builder renders, sanitizes the demo email, and
writes the four public JSON artifacts (public_stats, dashboard, clinical, buddy) to S3.
Before this file it had ~4.6% coverage — every one of those artifacts was unpinned.

The module takes its collaborators through `init()` (s3 client, DDB table, the brief's
fetch_range/fetch_date readers, the whoop-sleep normalizer), so the whole surface drives
offline against small hand-written fakes: `FakeS3` records put_object calls into a dict
and serves canned get_object bodies, `FakeTable` dispatches query() on the partition key
and logs update_item calls. No MagicMock — several of these fakes are iterated in loops
inside the code under test, and a Mock that yields forever has taken out a CI runner here
before.

Time is frozen (`_freeze_now`, Wednesday 2026-03-04 UTC) by swapping the module's
`datetime` for a subclass whose `now()` is fixed. Every window the writers derive
(today-7, today-30, this Monday) is then a literal, so the fixtures are absolute dates
and no assertion does fixture-date-plus-wall-clock arithmetic.
"""

import json
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from content import output_writers as ow

# ==============================================================================
# FIXED CLOCK
# ==============================================================================

# Wednesday. weekday() == 2, so the buddy writer's "days into week" is 3 and its
# week-start Monday is 2026-03-02 — both load-bearing for the status branches below.
FROZEN_NOW = datetime(2026, 3, 4, 15, 30, 0, tzinfo=timezone.utc)
TODAY = date(2026, 3, 4)
YESTERDAY = "2026-03-03"


class _FrozenDatetime(datetime):
    """datetime subclass with a pinned now(); strptime/strftime keep real behavior."""

    @classmethod
    def now(cls, tz=None):
        return FROZEN_NOW if tz is not None else FROZEN_NOW.replace(tzinfo=None)


@pytest.fixture(autouse=True)
def _freeze_now(monkeypatch):
    monkeypatch.setattr(ow, "datetime", _FrozenDatetime)


# ==============================================================================
# FAKES
# ==============================================================================


class _Body:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return self._payload


class FakeS3:
    """Records put_object calls; serves canned get_object bodies."""

    def __init__(self, objects=None, put_error=None, get_error=None):
        self.objects = dict(objects or {})
        self.put_calls = []
        self.puts = {}
        self.put_error = put_error
        self.get_error = get_error

    def put_object(self, **kwargs):
        if self.put_error is not None:
            raise self.put_error
        self.put_calls.append(kwargs)
        self.puts[kwargs["Key"]] = kwargs
        return {}

    def get_object(self, Bucket=None, Key=None):
        if self.get_error is not None:
            raise self.get_error
        if Key not in self.objects:
            raise RuntimeError("NoSuchKey: " + str(Key))
        return {"Body": _Body(self.objects[Key])}

    # -- assertion helpers --------------------------------------------------
    def written(self, key):
        return json.loads(self.puts[key]["Body"])


class FakeTable:
    """In-memory DDB table double that dispatches query() on the :pk value.

    `responses` maps a partition key to a list of items. A COUNT query (Select=COUNT)
    gets {"Count": len(items)}; otherwise {"Items": items[:Limit]}. `query_error` /
    `update_error` inject failures for the fail-soft paths.
    """

    def __init__(self, responses=None, query_error=None, update_error=None):
        self.responses = dict(responses or {})
        self.query_error = query_error
        self.update_error = update_error
        self.queries = []
        self.updates = []

    def query(self, **kwargs):
        self.queries.append(kwargs)
        if self.query_error is not None:
            raise self.query_error
        pk = (kwargs.get("ExpressionAttributeValues") or {}).get(":pk")
        items = list(self.responses.get(pk, []))
        if kwargs.get("Select") == "COUNT":
            return {"Count": len(items)}
        limit = kwargs.get("Limit")
        if limit is not None:
            items = items[:limit]
        return {"Items": items}

    def update_item(self, **kwargs):
        if self.update_error is not None:
            raise self.update_error
        self.updates.append(kwargs)
        return {}


class FakeRanges:
    """fetch_range(source, start, end) over a {source: [records]} map, logging windows.

    `errors` names sources whose read raises, for the fail-soft sections.
    """

    def __init__(self, by_source=None, errors=()):
        self.by_source = dict(by_source or {})
        self.errors = set(errors)
        self.calls = []

    def __call__(self, source, start, end):
        self.calls.append((source, start, end))
        if source in self.errors:
            raise RuntimeError("query failed for " + source)
        return list(self.by_source.get(source, []))

    def window_for(self, source):
        """(start, end) of the first call for `source`."""
        for src, start, end in self.calls:
            if src == source:
                return start, end
        raise AssertionError("fetch_range was never called for " + source)


def _passthrough_normalize(item):
    return item


def _init(s3=None, table=None, fetch_range=None, fetch_date=None, normalize=None):
    """Wire the module with fakes; returns (s3, table, fetch_range)."""
    s3 = s3 if s3 is not None else FakeS3()
    table = table if table is not None else FakeTable()
    fetch_range = fetch_range if fetch_range is not None else FakeRanges()
    ow.init(
        s3_client=s3,
        table_client=table,
        bucket="test-bucket",
        user_id="matthew",
        user_prefix="USER#matthew#SOURCE#",
        fetch_range_fn=fetch_range,
        fetch_date_fn=fetch_date if fetch_date is not None else (lambda source, date_str: None),
        normalize_whoop_fn=normalize if normalize is not None else _passthrough_normalize,
    )
    return s3, table, fetch_range


PROFILE = {
    "journey_start_weight_lbs": 320.0,
    "goal_weight_lbs": 185.0,
    "journey_start_date": "2026-01-01",
    "max_heart_rate": 184,
}


# ==============================================================================
# init()
# ==============================================================================


def test_init_derives_the_user_scoped_keys():
    _init()
    assert ow._REWARDS_PK == "USER#matthew#SOURCE#rewards"
    assert ow._DASHBOARD_KEY == "dashboard/matthew/data.json"
    assert ow._CS_CONFIG_KEY == "config/matthew/character_sheet.json"


# ==============================================================================
# _safe_float / _get_current_phase
# ==============================================================================


def test_safe_float_coerces_strings_and_falls_back_on_junk():
    assert ow._safe_float({"w": "180.5"}, "w") == 180.5
    assert ow._safe_float({"w": "n/a"}, "w") is None
    assert ow._safe_float({"w": "n/a"}, "w", default=0.0) == 0.0
    assert ow._safe_float({"w": 1}, "missing") is None
    assert ow._safe_float(None, "w") is None


def test_get_current_phase_returns_first_phase_whose_end_weight_is_not_yet_reached():
    profile = {
        "weight_loss_phases": [
            {"name": "Phase 1", "start_lbs": 320, "end_lbs": 285},
            {"name": "Phase 2", "start_lbs": 285, "end_lbs": 240},
            {"name": "Phase 3", "start_lbs": 240, "end_lbs": 185},
        ]
    }
    assert ow._get_current_phase(profile, 300)["name"] == "Phase 1"
    # Boundary: weight exactly at a phase's end still counts as inside that phase.
    assert ow._get_current_phase(profile, 285)["name"] == "Phase 1"
    assert ow._get_current_phase(profile, 284.9)["name"] == "Phase 2"
    # Past the last phase's end weight — the final phase is the floor, not None.
    assert ow._get_current_phase(profile, 170)["name"] == "Phase 3"


def test_get_current_phase_with_no_phases_is_none():
    assert ow._get_current_phase({}, 300) is None
    assert ow._get_current_phase({"weight_loss_phases": []}, 300) is None


# ==============================================================================
# _build_avatar_data
# ==============================================================================


def _sheet(**overrides):
    sheet = {
        "character_tier": "Foundation",
        "character_level": 10,
        "character_xp": 1000,
    }
    sheet.update(overrides)
    return sheet


def test_build_avatar_data_without_a_character_sheet_is_none():
    assert ow._build_avatar_data(None, PROFILE, 300) is None
    assert ow._build_avatar_data({}, PROFILE, 300) is None


@pytest.mark.parametrize(
    "current_weight,expected_score,expected_frame",
    [
        (320.0, 0.0, 1),  # no progress yet
        (271.4, 36.0, 2),  # exactly the dim/mid frame boundary
        (218.75, 75.0, 3),  # exactly the top frame boundary
        (185.0, 100.0, 3),  # goal reached
        (170.0, 100.0, 3),  # past goal — clamped, never >100
        (330.0, 0.0, 1),  # heavier than the start — clamped, never <0
    ],
)
def test_build_avatar_composition_score_and_body_frame_thresholds(current_weight, expected_score, expected_frame):
    avatar = ow._build_avatar_data(_sheet(), PROFILE, current_weight)
    assert avatar["composition_score"] == expected_score
    assert avatar["body_frame"] == expected_frame


def test_build_avatar_falls_back_to_start_weight_when_current_is_missing():
    avatar = ow._build_avatar_data(_sheet(), PROFILE, None)
    assert avatar["composition_score"] == 0.0
    assert avatar["body_frame"] == 1


def test_build_avatar_degenerate_goal_equal_to_start_is_fully_complete():
    profile = {"journey_start_weight_lbs": 200.0, "goal_weight_lbs": 200.0}
    avatar = ow._build_avatar_data(_sheet(), profile, 200.0)
    assert avatar["composition_score"] == 100
    assert avatar["body_frame"] == 3


def test_build_avatar_badge_thresholds_per_pillar():
    sheet = _sheet(
        pillar_sleep={"level": 61},  # bright at exactly 61
        pillar_movement={"level": 60},  # dim just below
        pillar_nutrition={"level": 41},  # dim at exactly 41
        pillar_metabolic={"level": 40},  # hidden just below
        # mind / relationships / consistency absent -> default level 1 -> hidden
    )
    avatar = ow._build_avatar_data(sheet, PROFILE, 300)
    assert avatar["badges"] == {
        "sleep": "bright",
        "movement": "dim",
        "nutrition": "dim",
        "metabolic": "hidden",
        "mind": "hidden",
        "relationships": "hidden",
        "consistency": "hidden",
    }


def test_build_avatar_expressions_read_the_four_driving_pillars():
    high = ow._build_avatar_data(
        _sheet(
            pillar_sleep={"level": 61},
            pillar_movement={"level": 61},
            pillar_metabolic={"level": 61},
            pillar_consistency={"level": 61},
        ),
        PROFILE,
        300,
    )
    assert high["expressions"] == {"eyes": "bright", "posture": "forward", "skin_tone": "warm", "ground": "solid"}

    low = ow._build_avatar_data(
        _sheet(
            pillar_sleep={"level": 34},
            pillar_movement={"level": 34},
            pillar_metabolic={"level": 34},
            pillar_consistency={"level": 34},
        ),
        PROFILE,
        300,
    )
    assert low["expressions"] == {"eyes": "dim", "posture": "normal", "skin_tone": "cool", "ground": "faded"}

    mid = ow._build_avatar_data(
        _sheet(
            pillar_sleep={"level": 35},
            pillar_movement={"level": 35},
            pillar_metabolic={"level": 35},
            pillar_consistency={"level": 35},
        ),
        PROFILE,
        300,
    )
    assert mid["expressions"] == {"eyes": "normal", "posture": "normal", "skin_tone": "normal", "ground": "normal"}


def test_build_avatar_effect_names_are_slugified_and_nameless_effects_dropped():
    sheet = _sheet(active_effects=[{"name": "Deep Sleep Bonus"}, {"emoji": "x"}, {"name": ""}, {"name": "Well Fed"}])
    avatar = ow._build_avatar_data(sheet, PROFILE, 300)
    assert avatar["effects"] == ["deep_sleep_bonus", "well_fed"]


def test_build_avatar_tier_is_slugified_and_defaults_to_foundation():
    assert ow._build_avatar_data(_sheet(character_tier="Deep Discipline"), PROFILE, 300)["tier"] == "deep_discipline"
    assert ow._build_avatar_data(_sheet(character_tier=None), PROFILE, 300)["tier"] == "foundation"


def test_build_avatar_crown_and_ring_require_level_81_and_all_bright():
    all_bright = {f"pillar_{p}": {"level": 70} for p in ow._PILLAR_ORDER}
    avatar = ow._build_avatar_data(_sheet(character_level=81, **all_bright), PROFILE, 300)
    assert avatar["elite_crown"] is True
    assert avatar["alignment_ring"] is True

    # One pillar merely "dim" breaks the ring; level 80 breaks the crown.
    all_bright["pillar_mind"] = {"level": 50}
    avatar2 = ow._build_avatar_data(_sheet(character_level=80, **all_bright), PROFILE, 300)
    assert avatar2["elite_crown"] is False
    assert avatar2["alignment_ring"] is False


# ==============================================================================
# evaluate_rewards
# ==============================================================================


def _reward(reward_id, condition, status="active", **extra):
    item = {
        "pk": "USER#matthew#SOURCE#rewards",
        "sk": "REWARD#" + reward_id,
        "reward_id": reward_id,
        "status": status,
        "condition": condition,
        "title": "Title " + reward_id,
        "description": "Desc " + reward_id,
    }
    item.update(extra)
    return item


def _rewards_table(items, **kwargs):
    return FakeTable(responses={"USER#matthew#SOURCE#rewards": items}, **kwargs)


def test_evaluate_rewards_without_a_character_sheet_is_empty():
    _init()
    assert ow.evaluate_rewards(None) == []


def test_evaluate_rewards_applies_the_adr058_phase_filter_to_its_query():
    table = _rewards_table([])
    _init(table=table)
    ow.evaluate_rewards(_sheet())
    kwargs = table.queries[0]
    assert "phase" in kwargs["ExpressionAttributeNames"]["#phase"]
    assert "attribute_not_exists(#phase)" in kwargs["FilterExpression"]
    assert kwargs["ExpressionAttributeValues"][":prefix"] == "REWARD#"


def test_evaluate_rewards_query_failure_is_fail_soft():
    table = _rewards_table([], query_error=RuntimeError("throttled"))
    _init(table=table)
    assert ow.evaluate_rewards(_sheet()) == []


def test_evaluate_rewards_character_level_condition_marks_the_row_triggered():
    table = _rewards_table([_reward("r1", {"type": "character_level", "level": 10})])
    _init(table=table)

    triggered = ow.evaluate_rewards(_sheet(character_level=10))

    assert [t["reward_id"] for t in triggered] == ["r1"]
    assert triggered[0]["title"] == "Title r1"
    assert triggered[0]["description"] == "Desc r1"
    assert triggered[0]["condition"] == {"type": "character_level", "level": 10}
    assert len(table.updates) == 1
    update = table.updates[0]
    assert update["Key"] == {"pk": "USER#matthew#SOURCE#rewards", "sk": "REWARD#r1"}
    assert update["ExpressionAttributeValues"][":s"] == "triggered"
    assert update["ExpressionAttributeValues"][":t"] == FROZEN_NOW.isoformat()


def test_evaluate_rewards_skips_unmet_and_non_active_rows():
    table = _rewards_table(
        [
            _reward("below", {"type": "character_level", "level": 11}),
            _reward("already", {"type": "character_level", "level": 1}, status="triggered"),
            _reward("no_type", {}),
        ]
    )
    _init(table=table)
    assert ow.evaluate_rewards(_sheet(character_level=10)) == []
    assert table.updates == []


def test_evaluate_rewards_tier_conditions_compare_by_tier_order():
    table = _rewards_table(
        [
            _reward("meets", {"type": "character_tier", "tier": "Momentum"}),
            _reward("exceeds", {"type": "character_tier", "tier": "Discipline"}),
            _reward("beyond", {"type": "character_tier", "tier": "Mastery"}),
            _reward("bogus", {"type": "character_tier", "tier": "Legendary"}),
        ]
    )
    _init(table=table)
    triggered = ow.evaluate_rewards(_sheet(character_tier="Discipline"))
    assert sorted(t["reward_id"] for t in triggered) == ["exceeds", "meets"]


def test_evaluate_rewards_pillar_level_and_pillar_tier_conditions():
    table = _rewards_table(
        [
            _reward("lvl_hit", {"type": "pillar_level", "pillar": "sleep", "level": 45}),
            _reward("lvl_miss", {"type": "pillar_level", "pillar": "sleep", "level": 60}),
            _reward("tier_hit", {"type": "pillar_tier", "pillar": "sleep", "tier": "Momentum"}),
            _reward("tier_miss", {"type": "pillar_tier", "pillar": "mind", "tier": "Momentum"}),
        ]
    )
    _init(table=table)
    triggered = ow.evaluate_rewards(_sheet(pillar_sleep={"level": 45, "tier": "Discipline"}))
    assert sorted(t["reward_id"] for t in triggered) == ["lvl_hit", "tier_hit"]


def test_evaluate_rewards_parses_a_json_string_condition_and_skips_unparseable_ones():
    table = _rewards_table(
        [
            _reward("stringly", json.dumps({"type": "character_level", "level": 5})),
            _reward("garbage", "{not json"),
        ]
    )
    _init(table=table)
    triggered = ow.evaluate_rewards(_sheet(character_level=10))
    assert [t["reward_id"] for t in triggered] == ["stringly"]
    assert triggered[0]["condition"] == {"type": "character_level", "level": 5}


def test_evaluate_rewards_update_failure_drops_that_reward_but_does_not_raise():
    table = _rewards_table(
        [_reward("r1", {"type": "character_level", "level": 1})],
        update_error=RuntimeError("ConditionalCheckFailed"),
    )
    _init(table=table)
    assert ow.evaluate_rewards(_sheet(character_level=10)) == []


# ==============================================================================
# get_protocol_recs
# ==============================================================================

_CONFIG_KEY = "config/matthew/character_sheet.json"


def _config_s3(config):
    return FakeS3(objects={_CONFIG_KEY: json.dumps(config).encode()})


def test_get_protocol_recs_without_a_sheet_or_config_is_empty():
    _init(s3=_config_s3({"protocols": {"sleep": {"Foundation": ["a"]}}}))
    assert ow.get_protocol_recs(None) == []

    _init(s3=_config_s3({}))
    assert ow.get_protocol_recs(_sheet()) == []


def test_get_protocol_recs_config_load_failure_is_fail_soft():
    _init(s3=FakeS3(get_error=RuntimeError("AccessDenied")))
    assert ow.get_protocol_recs(_sheet()) == []


def test_get_protocol_recs_returns_struggling_pillars_in_pillar_order_capped_at_two():
    config = {
        "protocols": {
            "sleep": {"Foundation": ["p1", "p2", "p3"]},
            "nutrition": {"Foundation": ["n1"]},
            "mind": {"Foundation": ["m1"]},
        }
    }
    _init(s3=_config_s3(config))
    sheet = _sheet(
        pillar_sleep={"level": 20, "tier": "Foundation"},
        pillar_nutrition={"level": 40, "tier": "Foundation"},  # 40 < 41 -> struggling
        pillar_mind={"level": 41, "tier": "Foundation"},  # 41 -> not struggling
    )
    recs = ow.get_protocol_recs(sheet)

    assert [r["pillar"] for r in recs] == ["sleep", "nutrition"]
    assert recs[0]["protocols"] == ["p1", "p2"]  # capped at 2
    assert recs[0]["level"] == 20
    assert recs[0]["tier"] == "Foundation"
    assert recs[0]["dropped"] is False


def test_get_protocol_recs_includes_a_high_level_pillar_that_just_dropped():
    config = {"protocols": {"movement": {"Mastery": ["deload week"]}}}
    _init(s3=_config_s3(config))
    sheet = _sheet(
        pillar_movement={"level": 70, "tier": "Mastery"},
        level_events=[{"pillar": "movement", "type": "pillar_level_down"}],
    )
    recs = ow.get_protocol_recs(sheet)
    assert len(recs) == 1
    assert recs[0]["pillar"] == "movement"
    assert recs[0]["dropped"] is True
    assert recs[0]["protocols"] == ["deload week"]


def test_get_protocol_recs_skips_pillars_missing_from_config_or_with_an_empty_tier():
    config = {"protocols": {"sleep": {"Mastery": ["only-for-mastery"]}, "mind": {"Foundation": []}}}
    _init(s3=_config_s3(config))
    sheet = _sheet(
        pillar_sleep={"level": 10, "tier": "Foundation"},  # tier not in config
        pillar_mind={"level": 10, "tier": "Foundation"},  # tier present but empty list
        pillar_metabolic={"level": 10, "tier": "Foundation"},  # pillar absent from config
    )
    assert ow.get_protocol_recs(sheet) == []


# ==============================================================================
# sanitize_for_demo
# ==============================================================================


def test_sanitize_for_demo_without_rules_returns_the_html_untouched():
    html = "<p>305.4 lbs</p>"
    assert ow.sanitize_for_demo(html, {"latest_weight": 305.4}, {}) == html


def test_sanitize_for_demo_hides_marked_sections():
    html = "<p>keep</p><!-- S:weight --><p>secret</p><!-- /S:weight --><p>keep2</p>"
    profile = {"demo_mode_rules": {"hide_sections": ["weight"]}}
    out = ow.sanitize_for_demo(html, {}, profile)
    assert "secret" not in out
    assert "keep" in out and "keep2" in out


def test_sanitize_for_demo_masks_weight_values_in_both_rendered_precisions():
    html = "<p>Today 305.4 lbs, a week ago 308 lbs. Goal 185. Started at 320.</p>"
    data = {"latest_weight": 305.4, "week_ago_weight": 308.0}
    profile = {
        "demo_mode_rules": {"replace_values": {"weight_lbs": "###"}},
        "goal_weight_lbs": 185,
        "journey_start_weight_lbs": 320,
        "weight_loss_phases": [{"start_lbs": 320, "end_lbs": 285}],
    }
    out = ow.sanitize_for_demo(html, data, profile)
    for leaked in ("305.4", "308", "185", "320"):
        assert leaked not in out
    assert out.count("###") >= 4


def test_sanitize_for_demo_masks_calories_and_protein():
    html = "<p>2100 kcal / 190g protein (target 2200)</p>"
    data = {"macrofactor": {"total_calories_kcal": 2100, "total_protein_g": 190}}
    profile = {"demo_mode_rules": {"replace_values": {"calories": "[cal]", "protein": "[pro]"}}, "calorie_target": 2200}
    out = ow.sanitize_for_demo(html, data, profile)
    assert "2100" not in out and "2200" not in out and "190" not in out
    assert "[cal]" in out and "[pro]" in out


def test_sanitize_for_demo_redacts_patterns_case_insensitively_with_common_suffixes():
    html = "<p>Drinking and drinks and DRINK, but sprinkle survives.</p>"
    profile = {"demo_mode_rules": {"redact_patterns": ["drink"]}}
    out = ow.sanitize_for_demo(html, {}, profile)
    assert "Drinking" not in out and "drinks" not in out and "DRINK" not in out
    assert out.count("[redacted]") == 3
    assert "sprinkle" in out  # word-boundary anchored, not a substring sweep


def test_sanitize_for_demo_inserts_the_banner_after_the_header_block():
    html = "<div><div>header</div></div><main>body</main>"
    profile = {"demo_mode_rules": {"redact_patterns": []}}
    out = ow.sanitize_for_demo(html, {}, profile)
    assert "DEMO VERSION" in out
    assert out.index("DEMO VERSION") > out.index("header")
    assert out.index("DEMO VERSION") < out.index("body")


def test_sanitize_for_demo_without_the_header_marker_adds_no_banner():
    html = "<p>no header structure here</p>"
    out = ow.sanitize_for_demo(html, {}, {"demo_mode_rules": {"redact_patterns": []}})
    assert "DEMO VERSION" not in out


# ==============================================================================
# write_public_stats_json
# ==============================================================================


def test_write_public_stats_json_computes_the_delta_story():
    s3, _, _ = _init()
    ow.write_public_stats_json({"latest_weight": 300.0}, PROFILE, streak_data={"tier0_streak": 12})

    stats = s3.written("generated/public_stats.json")
    assert stats["days_in"] == 62  # 2026-01-01 -> 2026-03-04
    assert stats["lbs_lost"] == 20.0
    assert stats["journey_pct"] == 14.8  # 20 / 135
    assert stats["tier0_streak"] == 12
    assert stats["goal_lbs"] == 185
    assert stats["journey_start_date"] == "2026-01-01"
    assert stats["updated_at"] == FROZEN_NOW.isoformat()

    put = s3.puts["generated/public_stats.json"]
    assert put["Bucket"] == "test-bucket"
    assert put["ContentType"] == "application/json"
    assert put["CacheControl"] == "max-age=300"


def test_write_public_stats_json_without_a_weight_omits_the_derived_fields():
    s3, _, _ = _init()
    ow.write_public_stats_json({}, PROFILE)
    stats = s3.written("generated/public_stats.json")
    assert stats["lbs_lost"] is None
    assert stats["journey_pct"] is None
    assert stats["tier0_streak"] is None


def test_write_public_stats_json_clamps_percentage_and_survives_a_bad_start_date():
    s3, _, _ = _init()
    profile = dict(PROFILE, journey_start_date="not-a-date")
    # Heavier than the journey start: progress is negative, must floor at 0, never go red.
    ow.write_public_stats_json({"latest_weight": 330.0}, profile)
    stats = s3.written("generated/public_stats.json")
    assert stats["days_in"] == 0
    assert stats["lbs_lost"] == -10.0
    assert stats["journey_pct"] == 0


def test_write_public_stats_json_falls_back_to_the_data_dict_for_the_streak():
    s3, _, _ = _init()
    ow.write_public_stats_json({"latest_weight": 300.0, "tier0_streak": 4}, PROFILE)
    assert s3.written("generated/public_stats.json")["tier0_streak"] == 4


def test_write_public_stats_json_reraises_on_write_failure():
    # Contract per the source: a stale public_stats.json breaks the homepage and the
    # OG images, so this writer must NOT swallow its error the way the others do.
    _init(s3=FakeS3(put_error=RuntimeError("s3 down")))
    with pytest.raises(RuntimeError):
        ow.write_public_stats_json({"latest_weight": 300.0}, PROFILE)


# ==============================================================================
# write_dashboard_json
# ==============================================================================

_DASH_KEY = "dashboard/matthew/data.json"


def _dashboard_ranges():
    return FakeRanges(
        {
            "whoop": [
                {"sk": "DATE#2026-03-01", "sleep_score": 80, "hrv": 60},
                {"sk": "DATE#2026-03-02", "sleep_score": 88, "hrv": 65},
            ],
            "withings": [
                {"sk": "DATE#2026-02-28", "weight_lbs": 306.0},
                {"sk": "DATE#2026-03-02", "weight_lbs": 305.0},
            ],
            "strava": [
                {
                    "sk": "DATE#2026-03-03",
                    "activities": [
                        {"average_heartrate": 120, "moving_time_seconds": 3600},  # in zone 2
                        {"average_heartrate": 150, "moving_time_seconds": 1800},  # above zone 2
                    ],
                }
            ],
        }
    )


def _dashboard_data(**overrides):
    data = {
        "hrv": {"hrv_7d": 62.0, "hrv_30d": 58.0},
        "whoop": {"hrv": 65},
        "sleep": {"sleep_score": 88, "sleep_duration_hours": 7.4, "sleep_efficiency_pct": 92, "deep_pct": 21, "rem_pct": 24},
        "apple": {"blood_glucose_avg": 101, "blood_glucose_time_in_range_pct": 88, "blood_glucose_std_dev": 15.5, "blood_glucose_min": 78},
        "apple_7d": [{"blood_glucose_avg": 99}, {"blood_glucose_avg": 104}],
        "macrofactor": {"total_calories_kcal": 2100},
        "latest_weight": 305.0,
        "week_ago_weight": 307.2,
        "journal": [{"text": "wrote something"}],
    }
    data.update(overrides)
    return data


def _write_dashboard(s3, data=None, profile=None, **overrides):
    kwargs = {
        "day_grade_score": 84,
        "grade": "B",
        "component_scores": {"sleep_quality": 90, "recovery": 70, "nutrition": 80, "movement": 60, "habits_mvp": 75},
        "readiness_score": 72,
        "readiness_colour": "yellow",
        "tldr_guidance": {"tldr": "Solid day."},
        "yesterday": YESTERDAY,
        "component_details": {"habits_mvp": {"tier0": {"done": 3}, "tier1": {"done": 2}}},
        "character_sheet": None,
    }
    kwargs.update(overrides)
    ow.write_dashboard_json(data if data is not None else _dashboard_data(), profile if profile is not None else PROFILE, **kwargs)
    return s3.written(_DASH_KEY)


def test_write_dashboard_json_shape_and_derived_values():
    ranges = _dashboard_ranges()
    s3, _, _ = _init(fetch_range=ranges)
    dash = _write_dashboard(s3)

    assert dash["date"] == YESTERDAY
    assert dash["generated_at"] == FROZEN_NOW.isoformat()
    assert dash["readiness"] == {
        "score": 72,
        "color": "yellow",
        "label": "Moderate",
        "training_rec": "Moderate effort · Zone 2 or easy strength",
    }
    assert dash["sleep"]["score"] == 88.0
    assert dash["sleep"]["sparkline"] == [80.0, 88.0]
    assert dash["hrv"] == {"value": 65.0, "avg_7d": 62.0, "avg_30d": 58.0, "sparkline": [60.0, 65.0]}
    assert dash["glucose"] == {
        "avg": 101.0,
        "tir_pct": 88.0,
        "variability": 15.5,
        "fasting_proxy": 78.0,
        "sparkline": [99.0, 104.0],
    }
    assert dash["day_grade"]["letter"] == "B"
    assert dash["day_grade"]["tldr"] == "Solid day."
    assert dash["day_grade"]["components"]["habits_tier0"] == 3
    assert dash["day_grade"]["components"]["habits_tier1"] == 2
    assert dash["day_grade"]["components"]["hydration"] is None  # absent component -> null, not dropped
    # whoop + sleep + macrofactor + apple present, plus journal
    assert dash["sources_active"] == 5

    put = s3.puts[_DASH_KEY]
    assert put["Bucket"] == "test-bucket"
    assert put["ContentType"] == "application/json"
    assert put["CacheControl"] == "max-age=300"


def test_write_dashboard_json_windows_are_anchored_on_today():
    ranges = _dashboard_ranges()
    s3, _, _ = _init(fetch_range=ranges)
    _write_dashboard(s3)
    assert ranges.window_for("whoop") == ("2026-02-25", YESTERDAY)
    assert ranges.window_for("withings") == ("2026-02-18", YESTERDAY)
    # Zone 2 is week-to-date: Monday of the frozen Wednesday.
    assert ranges.window_for("strava") == ("2026-03-02", YESTERDAY)


def test_write_dashboard_json_weight_sparkline_forward_fills_missing_days():
    ranges = _dashboard_ranges()
    s3, _, _ = _init(fetch_range=ranges)
    dash = _write_dashboard(s3)
    # Days 02-25..03-03; first weigh-in is 02-28 (306.0), next is 03-02 (305.0).
    assert dash["weight"]["sparkline"] == [306.0, 306.0, 305.0, 305.0]
    assert dash["weight"]["current"] == 305.0
    assert dash["weight"]["weekly_delta"] == -2.2
    assert dash["weight"]["journey_pct"] == 11  # (320-305)/135 -> 11%


def test_write_dashboard_json_zone2_counts_only_in_band_activities():
    ranges = _dashboard_ranges()
    s3, _, _ = _init(fetch_range=ranges)
    dash = _write_dashboard(s3)
    # max_hr 184 -> band 110.4–128.8bpm. Only the 120bpm/3600s session qualifies.
    assert dash["zone2_min"] == 60


@pytest.mark.parametrize(
    "colour,label,rec",
    [
        ("green", "Go", "Hard workout OK · Follow today's plan"),
        ("yellow", "Moderate", "Moderate effort · Zone 2 or easy strength"),
        ("red", "Easy", "Active recovery only · Walk, yoga, stretch"),
        ("gray", "No Data", ""),
    ],
)
def test_write_dashboard_json_readiness_colour_drives_label_and_recommendation(colour, label, rec):
    s3, _, _ = _init(fetch_range=FakeRanges())
    dash = _write_dashboard(s3, readiness_colour=colour)
    assert dash["readiness"]["label"] == label
    assert dash["readiness"]["training_rec"] == rec


@pytest.mark.parametrize(
    "tsb,expected",
    [
        (-25, "Overreached · Deload recommended"),
        (-20, "Hard workout OK · Follow today's plan"),  # boundary: not < -20
        (16, "Fresh legs · Good day for a hard session"),
        (15, "Hard workout OK · Follow today's plan"),  # boundary: not > 15
    ],
)
def test_write_dashboard_json_training_stress_balance_overrides_the_readiness_rec(tsb, expected):
    s3, _, _ = _init(fetch_range=FakeRanges())
    dash = _write_dashboard(s3, data=_dashboard_data(tsb=tsb), readiness_colour="green")
    assert dash["tsb"] == tsb
    assert dash["readiness"]["training_rec"] == expected


def test_write_dashboard_json_em_dash_grade_becomes_null():
    s3, _, _ = _init(fetch_range=FakeRanges())
    dash = _write_dashboard(s3, grade="—")
    assert dash["day_grade"]["letter"] is None
    assert dash["day_grade"]["score"] == 84


def test_write_dashboard_json_without_a_character_sheet_nulls_both_blocks():
    s3, _, _ = _init(fetch_range=FakeRanges())
    dash = _write_dashboard(s3)
    assert dash["character_sheet"] is None
    assert dash["avatar"] is None


def test_write_dashboard_json_projects_the_character_sheet_and_avatar():
    s3, _, _ = _init(fetch_range=_dashboard_ranges())
    sheet = _sheet(
        character_level=42,
        character_tier="Discipline",
        character_tier_emoji="B",
        character_xp=9001,
        pillar_sleep={"level": 65, "tier": "Mastery", "raw_score": 88.5},
        level_events=[{"pillar": "sleep", "type": "pillar_level_up"}],
        active_effects=[{"name": "Deep Sleep Bonus", "emoji": "Z", "extra": "dropped"}],
    )
    dash = _write_dashboard(s3, character_sheet=sheet)

    cs = dash["character_sheet"]
    assert cs["level"] == 42
    assert cs["tier"] == "Discipline"
    assert cs["tier_emoji"] == "B"
    assert cs["xp"] == 9001
    assert cs["pillars"]["sleep"] == {"level": 65, "tier": "Mastery", "raw_score": 88.5}
    assert cs["pillars"]["mind"] == {"level": None, "tier": None, "raw_score": None}
    assert list(cs["pillars"].keys()) == ow._PILLAR_ORDER
    assert cs["events"] == [{"pillar": "sleep", "type": "pillar_level_up"}]
    assert cs["effects"] == [{"name": "Deep Sleep Bonus", "emoji": "Z"}]  # only name+emoji surface
    assert dash["avatar"]["badges"]["sleep"] == "bright"


def test_write_dashboard_json_prefers_avatar_weight_over_latest_weight():
    s3, _, _ = _init(fetch_range=FakeRanges())
    data = _dashboard_data(avatar_weight=218.75)
    dash = _write_dashboard(s3, data=data, character_sheet=_sheet())
    assert dash["avatar"]["composition_score"] == 75.0


def test_write_dashboard_json_zone2_is_null_when_the_strava_read_fails():
    # The zone-2 block is individually fail-soft: the rest of the dashboard must still ship.
    s3, _, _ = _init(fetch_range=FakeRanges(errors={"strava"}))
    dash = _write_dashboard(s3)
    assert dash["zone2_min"] is None
    assert dash["readiness"]["score"] == 72


def test_write_dashboard_json_swallows_a_write_failure():
    # The dashboard is a best-effort side effect of the brief: a failure must not
    # take the email down (contrast write_public_stats_json, which re-raises).
    s3 = FakeS3(put_error=RuntimeError("s3 down"))
    _init(s3=s3, fetch_range=FakeRanges())
    ow.write_dashboard_json(
        _dashboard_data(),
        PROFILE,
        day_grade_score=84,
        grade="B",
        component_scores={},
        readiness_score=72,
        readiness_colour="green",
        tldr_guidance=None,
        yesterday=YESTERDAY,
    )
    assert s3.puts == {}


# ==============================================================================
# write_clinical_json
# ==============================================================================

_CLINICAL_KEY = "dashboard/matthew/clinical.json"


def _clinical_ranges():
    return FakeRanges(
        {
            "whoop": [
                {"sk": "DATE#2026-02-20", "resting_heart_rate": 54, "hrv": 60, "sleep_score": 80, "sleep_duration_hours": 7.0},
                {"sk": "DATE#2026-02-21", "resting_heart_rate": 56, "hrv": 64, "sleep_score": 90, "sleep_duration_hours": 8.0},
                {"sk": "DATE#2026-02-22", "sleep_score": 85},  # partial record: no rhr/hrv
            ],
            "withings": [
                {"sk": "DATE#2026-02-10", "weight_lbs": 312.4},
                {"sk": "DATE#2026-02-20", "weight_lbs": 308.0},
                {"sk": "DATE#2026-03-02", "weight_lbs": 305.0},
            ],
            "supplements": [
                {"sk": "DATE#2026-03-01", "supplements": [{"name": "Creatine", "dose": 5, "unit": "g", "timing": "AM"}]},
                {
                    "sk": "DATE#2026-03-02",
                    "supplements": [
                        {"name": "creatine", "dose": 5, "unit": "g"},  # case-insensitive duplicate
                        {"name": "Vitamin D", "dose": "2000 IU"},  # dose without a unit
                        {"name": "  ", "dose": 1},  # blank name, skipped
                    ],
                },
            ],
            "strava": [
                {
                    "sk": "DATE#2026-03-02",
                    "activities": [
                        {"sport_type": "Walk", "average_heartrate": 118, "moving_time_seconds": 1800},
                        {"sport_type": "Walk", "average_heartrate": 160, "moving_time_seconds": 1800},
                    ],
                },
                {"sk": "DATE#2026-03-03", "activities": [{"sport_type": "WeightTraining", "moving_time_seconds": 2700}]},
            ],
            "apple_health": [
                {"sk": "DATE#2026-03-01", "steps": 9000, "blood_glucose_avg": 100, "blood_glucose_time_in_range_pct": 90},
                {"sk": "DATE#2026-03-02", "steps": 11000, "blood_glucose_avg": 106, "blood_glucose_std_dev": 15.4, "blood_glucose_min": 76},
            ],
        }
    )


def _clinical_table():
    return FakeTable(
        responses={
            "USER#matthew#SOURCE#dexa": [
                {
                    "scan_date": "2026-02-01",
                    "body_composition": {"body_fat_pct": 34.2, "lean_mass_lbs": 190.1, "fat_mass_lbs": 110.0, "visceral_fat_g": 900},
                    "bone_density": {"t_score": 1.2},
                    "interpretations": {"ffmi": 22.4},
                }
            ],
            "USER#matthew#SOURCE#labs": [
                {
                    "draw_date": "2026-02-15",
                    "lab_provider": "Quest",
                    "out_of_range": ["ldl_c", "apob"],
                    "biomarkers": {
                        "ldl_c": {"category": "lipids", "value_numeric": 112.0, "unit": "mg/dL", "ref_text": "<100", "flag": "high"},
                        "hdl_c": {"category": "lipids", "value_numeric": 5.5, "unit": "mg/dL", "flag": "normal"},
                        "apob": {"category": "lipids_advanced", "value_numeric": 0.85, "unit": "g/L", "flag": "low"},
                        "occult_blood": {"category": "digestive", "value": "negative"},
                        # A category the fixed order has never heard of — must still publish.
                        "novel_marker": {"category": "exotica", "value_numeric": 3.0, "flag": "normal"},
                    },
                }
            ],
            "USER#matthew#SOURCE#genome": [
                {"gene": "MTHFR", "genotype": "C677T", "risk_level": "unfavorable", "summary": "reduced activity"},
                {"gene": "APOE", "genotype": "e3/e3", "risk_level": "neutral", "summary": "typical"},
                {"gene": "ACTN3", "genotype": "RX", "risk_level": "mixed", "summary": "mixed fibre"},
            ],
        }
    )


def _write_clinical(data=None, profile=None, table=None, ranges=None):
    s3, _, _ = _init(
        table=table if table is not None else _clinical_table(), fetch_range=ranges if ranges is not None else _clinical_ranges()
    )
    ow.write_clinical_json(
        data if data is not None else {"tsb": 4.5, "whoop": {}, "journal": []}, profile if profile is not None else PROFILE, YESTERDAY
    )
    return s3


def test_write_clinical_json_vitals_average_only_present_values():
    s3 = _write_clinical()
    vitals = s3.written(_CLINICAL_KEY)["vitals"]
    assert vitals["rhr_avg"] == 55  # (54 + 56) / 2 — the partial record contributes nothing
    assert vitals["hrv_avg"] == 62
    assert vitals["weight_current"] == 305.0  # last weigh-in in the window
    assert vitals["weight_30d_delta"] == -7.4  # 305.0 - 312.4
    assert vitals["bp_systolic"] is None


def test_write_clinical_json_report_metadata_and_s3_key():
    s3 = _write_clinical()
    clinical = s3.written(_CLINICAL_KEY)
    assert clinical["report_date"] == YESTERDAY
    assert clinical["report_period"] == "30 days ending " + YESTERDAY
    assert clinical["patient_name"] == "Matthew Walker"  # profile default
    assert clinical["generated_at"] == FROZEN_NOW.isoformat()
    assert s3.puts[_CLINICAL_KEY]["CacheControl"] == "max-age=300"


def test_write_clinical_json_body_comp_from_the_latest_dexa_scan():
    s3 = _write_clinical()
    bc = s3.written(_CLINICAL_KEY)["body_comp"]
    assert bc == {
        "scan_date": "2026-02-01",
        "body_fat_pct": 34.2,
        "ffmi": 22.4,
        "lean_mass_lbs": 190.1,
        "fat_mass_lbs": 110.0,
        "visceral_fat_area": 900,
        "bmd": 1.2,
    }


def test_write_clinical_json_labs_are_ordered_by_category_then_name():
    s3 = _write_clinical()
    labs = s3.written(_CLINICAL_KEY)["labs"]
    assert labs["latest_draw_date"] == "2026-02-15"
    assert labs["lab_provider"] == "Quest"
    assert labs["flagged_count"] == 2
    assert labs["total_draws"] == 1
    # lipids -> lipids_advanced -> digestive come from the fixed category order (names
    # sort inside each category); categories outside that order land last.
    assert [b["name"] for b in labs["biomarkers"]] == ["Hdl C", "Ldl C", "Apob", "Occult Blood", "Novel Marker"]
    by_name = {b["name"]: b for b in labs["biomarkers"]}
    assert by_name["Novel Marker"]["category"] == "Exotica"  # title-cased fallback label
    assert by_name["Ldl C"]["flag"] == "H"
    assert by_name["Apob"]["flag"] == "L"
    assert by_name["Hdl C"]["flag"] is None
    assert by_name["Ldl C"]["category"] == "Lipids"
    assert by_name["Apob"]["category"] == "Advanced Lipids"
    # display precision widens as the magnitude shrinks
    assert by_name["Ldl C"]["decimals"] == 0
    assert by_name["Hdl C"]["decimals"] == 1
    assert by_name["Apob"]["decimals"] == 2
    # non-numeric biomarkers pass through verbatim
    assert by_name["Occult Blood"]["value"] == "negative"


def test_write_clinical_json_labs_precision_survives_real_ddb_decimal_values():
    # Regression for #2176: DynamoDB numeric attributes deserialize as Decimal (this
    # repo's Decimal-before-DDB-write / Decimal-out-of-read convention), never as a
    # plain int/float. The test above exercises the precision logic with plain floats,
    # which passed even while `isinstance(val, (int, float))` silently excluded every
    # real biomarker read back from DDB — decimals stuck at 0 and the raw Decimal rode
    # through to json.dumps(..., default=str), which stringifies it ("0.85" instead of
    # 0.85). This fixture hands the writer Decimal values exactly as boto3's DynamoDB
    # resource would, so the dead path is caught if it ever regresses.
    table = FakeTable(
        responses={
            "USER#matthew#SOURCE#dexa": [],
            "USER#matthew#SOURCE#labs": [
                {
                    "draw_date": "2026-02-15",
                    "lab_provider": "Quest",
                    "out_of_range": ["ldl_c", "apob"],
                    "biomarkers": {
                        "ldl_c": {
                            "category": "lipids",
                            "value_numeric": Decimal("112.0"),
                            "unit": "mg/dL",
                            "ref_text": "<100",
                            "flag": "high",
                        },
                        "hdl_c": {"category": "lipids", "value_numeric": Decimal("5.5"), "unit": "mg/dL", "flag": "normal"},
                        "apob": {"category": "lipids_advanced", "value_numeric": Decimal("0.85"), "unit": "g/L", "flag": "low"},
                    },
                }
            ],
            "USER#matthew#SOURCE#genome": [],
        }
    )
    s3 = _write_clinical(table=table, ranges=FakeRanges({}))
    by_name = {b["name"]: b for b in s3.written(_CLINICAL_KEY)["labs"]["biomarkers"]}

    # Precision logic fires exactly as it does for the plain-float fixture above.
    assert by_name["Ldl C"]["decimals"] == 0
    assert by_name["Hdl C"]["decimals"] == 1
    assert by_name["Apob"]["decimals"] == 2

    # `by_name` above already went through the real write path — `_write_clinical`
    # calls `write_clinical_json`, which S3-puts `json.dumps(clinical, default=str)`,
    # and `s3.written()` parses that Body back with `json.loads`. So the assertion
    # below round-trips through the actual production serializer: pre-fix, the raw
    # Decimal reached json.dumps and its `default=str` fallback stringified it, so
    # `value` would decode back as the STRING "0.85", not the float 0.85.
    for name, expected in (("Ldl C", 112.0), ("Hdl C", 5.5), ("Apob", 0.85)):
        val = by_name[name]["value"]
        assert val == expected
        assert isinstance(val, float)


def test_write_clinical_json_supplements_dedup_case_insensitively_and_sort_by_name():
    s3 = _write_clinical()
    supps = s3.written(_CLINICAL_KEY)["supplements"]
    assert [s["name"] for s in supps] == ["Creatine", "Vitamin D"]
    assert supps[0] == {"name": "Creatine", "dose": "5 g", "timing": "AM"}
    assert supps[1]["dose"] == "2000 IU"  # dose with no unit still renders


def test_write_clinical_json_sleep_and_activity_summaries():
    s3 = _write_clinical()
    clinical = s3.written(_CLINICAL_KEY)
    sleep = clinical["sleep_30d"]
    assert sleep["avg_score"] == 85  # (80 + 90 + 85) / 3
    assert sleep["avg_duration_hrs"] == 7.5
    assert sleep["avg_efficiency"] is None  # no efficiency in the fixtures -> honest null
    assert sleep["avg_bedtime"] is None

    activity = clinical["activity"]
    assert activity["avg_sessions_week"] == 0.8  # 3 sessions / 4 weeks
    assert activity["avg_zone2_min"] == 8  # only the 118bpm/1800s walk is in band -> 30/4
    assert activity["avg_daily_steps"] == 10000
    assert activity["primary_types"] == ["Walk", "WeightTraining"]
    assert activity["tsb"] == 4.5
    assert activity["ctl"] is None


def test_write_clinical_json_glucose_summary_averages_each_metric_independently():
    s3 = _write_clinical()
    glucose = s3.written(_CLINICAL_KEY)["glucose"]
    assert glucose["mean"] == 103  # (100 + 106) / 2
    assert glucose["tir_pct"] == 90  # only one day reported TIR
    assert glucose["variability_sd"] == 15.4
    assert glucose["fasting_proxy"] == 76


def test_write_clinical_json_genome_flags_keep_only_risky_variants_unfavorable_first():
    s3 = _write_clinical()
    flags = s3.written(_CLINICAL_KEY)["genome_flags"]
    assert [f["gene"] for f in flags] == ["MTHFR", "ACTN3"]
    assert flags[0] == {"gene": "MTHFR", "variant": "C677T", "risk": "unfavorable", "note": "reduced activity"}
    assert all(f["risk"] in ("unfavorable", "mixed") for f in flags)


def test_write_clinical_json_counts_active_sources_including_journal():
    s3 = _write_clinical(data={"whoop": {"hrv": 60}, "sleep": {"sleep_score": 88}, "journal": [{"text": "x"}], "garmin": None})
    assert s3.written(_CLINICAL_KEY)["sources_active"] == 3


def test_write_clinical_json_survives_every_ddb_section_failing():
    table = FakeTable(query_error=RuntimeError("throttled"))
    s3 = _write_clinical(table=table)
    clinical = s3.written(_CLINICAL_KEY)
    # The DDB-backed sections degrade to empty; the fetch_range-backed ones still populate.
    assert clinical["body_comp"] == {}
    assert clinical["labs"] == {}
    assert clinical["genome_flags"] == []
    assert clinical["vitals"]["weight_current"] == 305.0


def test_write_clinical_json_supplement_read_failure_is_contained():
    s3 = _write_clinical(ranges=FakeRanges(dict(_clinical_ranges().by_source), errors={"supplements"}))
    clinical = s3.written(_CLINICAL_KEY)
    assert clinical["supplements"] == []
    assert clinical["vitals"]["rhr_avg"] == 55  # everything else still computed


def test_write_clinical_json_with_no_data_at_all_emits_honest_nulls():
    s3 = _write_clinical(table=FakeTable(), ranges=FakeRanges(), data={})
    clinical = s3.written(_CLINICAL_KEY)
    assert clinical["vitals"] == {
        "weight_current": None,
        "weight_30d_delta": None,
        "rhr_avg": None,
        "hrv_avg": None,
        "bp_systolic": None,
        "bp_diastolic": None,
    }
    assert clinical["sleep_30d"]["avg_score"] is None
    assert clinical["activity"]["avg_sessions_week"] == 0
    assert clinical["activity"]["primary_types"] == []
    assert clinical["glucose"]["mean"] is None
    assert clinical["supplements"] == []
    assert clinical["sources_active"] == 0


def test_write_clinical_json_swallows_a_write_failure():
    s3 = FakeS3(put_error=RuntimeError("s3 down"))
    _init(s3=s3, table=_clinical_table(), fetch_range=_clinical_ranges())
    ow.write_clinical_json({}, PROFILE, YESTERDAY)
    assert s3.puts == {}


# ==============================================================================
# BUDDY HELPERS
# ==============================================================================


def test_buddy_days_since_handles_strings_dates_and_junk():
    assert ow._buddy_days_since("2026-03-01", TODAY) == 3
    assert ow._buddy_days_since("2026-03-04", TODAY) == 0
    assert ow._buddy_days_since(date(2026, 2, 25), TODAY) == 7
    # A missing or unparseable date must read as "ancient", never as "today".
    assert ow._buddy_days_since(None, TODAY) == 99
    assert ow._buddy_days_since("", TODAY) == 99
    assert ow._buddy_days_since("last tuesday", TODAY) == 99


def test_buddy_friendly_date_formats_and_passes_junk_through():
    assert ow._buddy_friendly_date("2026-02-27") == "Fri Feb 27"
    assert ow._buddy_friendly_date("2026-03-04") == "Wed Mar 4"  # no zero padding
    assert ow._buddy_friendly_date("nonsense") == "nonsense"
    assert ow._buddy_friendly_date(None) == ""


def test_buddy_friendly_name_expands_sport_codes_only_when_the_name_adds_nothing():
    assert ow._buddy_friendly_name("Ride", "Ride") == "Bike Ride"
    assert ow._buddy_friendly_name("", "VirtualRide") == "Indoor Ride"
    assert ow._buddy_friendly_name("Morning loop", "Ride") == "Morning loop"
    # Unknown sport types fall through to the raw code rather than blanking out.
    assert ow._buddy_friendly_name("Pickleball", "Pickleball") == "Pickleball"


def _act(strava_id, start, dur, device=None, **extra):
    a = {"strava_id": strava_id, "start_date": start, "moving_time_seconds": dur}
    if device:
        a["device_name"] = device
    a.update(extra)
    return a


def test_dedup_activities_is_identity_for_zero_or_one_activity():
    assert ow._dedup_activities([]) == []
    one = [_act("a", "2026-03-03T08:00:00Z", 1800)]
    assert ow._dedup_activities(one) == one


def test_dedup_activities_keeps_the_higher_priority_device_for_an_overlapping_pair():
    whoop = _act("w1", "2026-03-03T08:00:00Z", 3600, device="WHOOP 4.0")
    garmin = _act("g1", "2026-03-03T08:05:00Z", 3500, device="Garmin Forerunner")
    kept = ow._dedup_activities([whoop, garmin])
    assert [a["strava_id"] for a in kept] == ["g1"]


def test_dedup_activities_keeps_the_first_when_devices_tie():
    a = _act("a1", "2026-03-03T08:00:00Z", 3600)
    b = _act("b1", "2026-03-03T08:02:00Z", 3600)
    kept = ow._dedup_activities([a, b])
    assert [x["strava_id"] for x in kept] == ["a1"]


def test_dedup_activities_keeps_sessions_more_than_15_minutes_apart():
    a = _act("a1", "2026-03-03T08:00:00Z", 3600, device="WHOOP")
    b = _act("b1", "2026-03-03T08:20:00Z", 3600, device="Garmin")
    kept = ow._dedup_activities([a, b])
    assert sorted(x["strava_id"] for x in kept) == ["a1", "b1"]


def test_dedup_activities_keeps_pairs_whose_durations_are_too_different():
    # Overlapping in time, but a 10-minute session is not the same workout as an hour.
    a = _act("a1", "2026-03-03T08:00:00Z", 3600, device="WHOOP")
    b = _act("b1", "2026-03-03T08:05:00Z", 600, device="Garmin")
    kept = ow._dedup_activities([a, b])
    assert sorted(x["strava_id"] for x in kept) == ["a1", "b1"]


def test_dedup_activities_prefers_apple_over_whoop():
    whoop = _act("w1", "2026-03-03T08:00:00Z", 3600, device="WHOOP 4.0")
    apple = _act("a1", "2026-03-03T08:03:00Z", 3550, device="Apple Watch")
    assert [a["strava_id"] for a in ow._dedup_activities([whoop, apple])] == ["a1"]


def test_dedup_activities_does_not_reconsider_an_already_dropped_duplicate():
    # The Garmin hour and the WHOOP hour are the same workout (Garmin wins); the
    # 10-minute walk overlaps both but is too short to be a duplicate of either, so
    # it survives — and must not be re-paired against the already-dropped WHOOP row.
    garmin = _act("g1", "2026-03-03T08:00:00Z", 3600, device="Garmin Forerunner")
    short = _act("s1", "2026-03-03T08:02:00Z", 600)
    whoop = _act("w1", "2026-03-03T08:04:00Z", 3500, device="WHOOP 4.0")
    kept = ow._dedup_activities([garmin, short, whoop])
    assert [a["strava_id"] for a in kept] == ["g1", "s1"]


def test_dedup_activities_keeps_everything_when_start_times_are_unparseable():
    a = _act("a1", "", 3600, device="WHOOP")
    b = _act("b1", "", 3600, device="Garmin")
    assert len(ow._dedup_activities([a, b])) == 2


# ==============================================================================
# write_buddy_json
# ==============================================================================

_BUDDY_KEY = "buddy/matthew/data.json"


@pytest.fixture
def _frozen_pacific(monkeypatch):
    """Pin the buddy writer's friendly timestamp (it reads a live Pacific clock)."""
    from common import pacific_time

    monkeypatch.setattr(pacific_time, "pacific_now", lambda: datetime(2026, 3, 4, 9, 5, 0))


def _buddy_ranges(**overrides):
    by_source = {
        "macrofactor": [{"sk": f"DATE#2026-02-2{d}", "total_calories_kcal": 2200, "total_protein_g": 190} for d in range(6, 9)]
        + [{"sk": f"DATE#2026-03-0{d}", "total_calories_kcal": 2000, "total_protein_g": 180} for d in range(1, 5)],
        "strava": [
            {
                "sk": "DATE#2026-03-02",
                "activities": [{"sport_type": "Run", "name": "Run", "distance_miles": 3.05, "moving_time_seconds": 1800}],
            },
            {
                "sk": "DATE#2026-03-03",
                "activities": [
                    {"sport_type": "WeightTraining", "name": "Push day", "moving_time_seconds": 3600},
                    {"sport_type": "Walk", "name": "Walk", "distance_miles": 0.05, "moving_time_seconds": 600},
                ],
            },
            {
                "sk": "DATE#2026-03-04",
                "activities": [{"sport_type": "Ride", "name": "Ride", "distance_miles": 12.0, "moving_time_seconds": 2700}],
            },
        ],
        "habitify": [{"sk": f"DATE#2026-03-0{d}", "completed_count": 6} for d in range(1, 5)]
        + [{"sk": "DATE#2026-02-28", "completed_count": 0}],
        "withings": [
            {"sk": "DATE#2026-02-26", "weight_lbs": 308.0},
            {"sk": "DATE#2026-03-03", "weight_lbs": 305.0},
        ],
    }
    by_source.update(overrides)
    return FakeRanges(by_source)


def test_write_buddy_json_all_green_week(_frozen_pacific):
    ranges = _buddy_ranges()
    s3, _, _ = _init(fetch_range=ranges)
    ow.write_buddy_json({}, PROFILE, YESTERDAY)

    buddy = s3.written(_BUDDY_KEY)
    assert buddy["beacon"] == "green"
    assert buddy["beacon_label"] == "Matt's doing his thing"
    assert {line["area"]: line["status"] for line in buddy["status_lines"]} == {
        "Food Logging": "green",
        "Exercise": "green",
        "Routine": "green",
        "Weight": "green",
    }
    by_area = {line["area"]: line["text"] for line in buddy["status_lines"]}
    assert by_area["Food Logging"] == "Consistent — logged meals 7 of last 7 days"
    assert by_area["Exercise"] == "Active — 4 sessions this week"  # Mon-Wed of the frozen week
    assert by_area["Weight"] == "Heading in the right direction"
    assert buddy["food_snapshot"] == "Averaging about 2,085 calories per day this week with 184g protein."
    assert buddy["date"] == YESTERDAY
    assert buddy["last_updated_friendly"] == "Wednesday morning, March 4 at 9:05am PT"
    assert s3.puts[_BUDDY_KEY]["ContentType"] == "application/json"


def test_write_buddy_json_activity_highlights_are_newest_first_and_capped_at_four(_frozen_pacific):
    ranges = _buddy_ranges()
    s3, _, _ = _init(fetch_range=ranges)
    ow.write_buddy_json({}, PROFILE, YESTERDAY)

    highlights = s3.written(_BUDDY_KEY)["activity_highlights"]
    assert len(highlights) == 4
    assert highlights[0]["name"] == "Bike Ride"  # 03-04, sport code expanded
    assert highlights[0]["detail"] == "12.0 mi, 45 min"
    assert highlights[0]["date"] == "Wed Mar 4"
    assert highlights[1]["name"] == "Push day"  # custom name kept verbatim
    assert highlights[1]["detail"] == "60 min"  # no distance on a lift
    walk = [h for h in highlights if h["name"] == "Walk"][0]
    assert walk["detail"] == "10 min"  # 0.05mi is below the 0.1mi floor, dropped
    assert "sort_date" not in highlights[0]  # internal sort key is not published


def test_write_buddy_json_all_signals_quiet_raises_the_red_beacon(_frozen_pacific):
    s3, _, _ = _init(fetch_range=FakeRanges())
    ow.write_buddy_json({}, PROFILE, YESTERDAY)

    buddy = s3.written(_BUDDY_KEY)
    assert buddy["beacon"] == "red"
    assert buddy["beacon_label"] == "Check in on him"
    assert "reach out" in buddy["prompt_for_tom"]
    assert [line["status"] for line in buddy["status_lines"]] == ["red", "red", "red", "red"]
    by_area = {line["area"]: line["text"] for line in buddy["status_lines"]}
    assert by_area["Food Logging"] == "No food logged in 99 days — might be off track"
    # Wednesday is day 3 of the week, past the "too early to tell" grace window.
    assert by_area["Exercise"] == "No exercise this week — last session 99 days ago"
    assert by_area["Weight"] == "No weigh-in in 99+ days"
    assert buddy["activity_highlights"] == []
    assert buddy["food_snapshot"] == ""


def test_write_buddy_json_single_amber_signal_yields_a_yellow_beacon(_frozen_pacific):
    # Food logged only 3 of 7 days but recent, no habits at all -> one red + one green
    # => "red_count >= 1" branch.
    ranges = _buddy_ranges(
        habitify=[],
        macrofactor=[{"sk": f"DATE#2026-03-0{d}", "total_calories_kcal": 2000} for d in range(2, 5)],
    )
    s3, _, _ = _init(fetch_range=ranges)
    ow.write_buddy_json({}, PROFILE, YESTERDAY)

    buddy = s3.written(_BUDDY_KEY)
    by_area = {line["area"]: line for line in buddy["status_lines"]}
    assert by_area["Food Logging"]["status"] == "green"
    assert by_area["Food Logging"]["text"] == "Logging food — 3 of last 7 days tracked"
    assert by_area["Routine"]["status"] == "red"
    assert buddy["beacon"] == "yellow"
    assert buddy["beacon_label"] == "Might be a quiet stretch"
    # Protein absent from every entry -> the snapshot drops the protein clause.
    assert buddy["food_snapshot"] == "Averaging about 2,000 calories per day this week."


def test_write_buddy_json_ignores_sub_threshold_food_and_weight_rows(_frozen_pacific):
    # A 150kcal day is a partial log, not a logged day; a 90lb reading is a scale glitch.
    ranges = _buddy_ranges(
        macrofactor=[{"sk": "DATE#2026-03-03", "total_calories_kcal": 150}],
        withings=[{"sk": "DATE#2026-03-03", "weight_lbs": 90.0}],
    )
    s3, _, _ = _init(fetch_range=ranges)
    ow.write_buddy_json({}, PROFILE, YESTERDAY)

    buddy = s3.written(_BUDDY_KEY)
    by_area = {line["area"]: line for line in buddy["status_lines"]}
    assert by_area["Food Logging"]["status"] == "red"
    assert by_area["Weight"]["status"] == "red"
    assert buddy["food_snapshot"] == ""


def test_write_buddy_json_single_weigh_in_and_upward_drift_branches(_frozen_pacific):
    only_one = _buddy_ranges(withings=[{"sk": "DATE#2026-03-03", "weight_lbs": 305.0}])
    s3, _, _ = _init(fetch_range=only_one)
    ow.write_buddy_json({}, PROFILE, YESTERDAY)
    weight_line = [line for line in s3.written(_BUDDY_KEY)["status_lines"] if line["area"] == "Weight"][0]
    assert weight_line == {"area": "Weight", "status": "green", "text": "Weighed in recently"}

    gaining = _buddy_ranges(withings=[{"sk": "DATE#2026-02-26", "weight_lbs": 305.0}, {"sk": "DATE#2026-03-03", "weight_lbs": 307.0}])
    s3b, _, _ = _init(fetch_range=gaining)
    ow.write_buddy_json({}, PROFILE, YESTERDAY)
    weight_line_b = [line for line in s3b.written(_BUDDY_KEY)["status_lines"] if line["area"] == "Weight"][0]
    assert weight_line_b["status"] == "yellow"
    assert weight_line_b["text"] == "Weight ticked up slightly this week"


def test_write_buddy_json_journey_stats_use_the_latest_weigh_in(_frozen_pacific):
    profile = dict(PROFILE, start_weight_lbs=320.0, journey_start_date="2026-01-01")
    s3, _, _ = _init(fetch_range=_buddy_ranges())
    ow.write_buddy_json({}, profile, YESTERDAY)

    journey = s3.written(_BUDDY_KEY)["journey"]
    assert journey["days"] == 62
    assert journey["lost_lbs"] == 15.0  # 320 -> 305 (the 03-03 weigh-in)
    assert journey["pct_complete"] == 11  # 15 / 135
    assert journey["goal_lbs"] == 185


def test_write_buddy_json_journey_falls_back_to_avatar_weight_without_a_weigh_in(_frozen_pacific):
    profile = dict(PROFILE, start_weight_lbs=320.0)
    s3, _, _ = _init(fetch_range=_buddy_ranges(withings=[]))
    ow.write_buddy_json({"avatar_weight": 310.0}, profile, YESTERDAY)
    assert s3.written(_BUDDY_KEY)["journey"]["lost_lbs"] == 10.0


def test_write_buddy_json_projects_the_character_sheet_and_avatar(_frozen_pacific):
    sheet = _sheet(
        character_level=30,
        character_tier="Momentum",
        character_tier_emoji="M",
        character_xp=4200,
        pillar_sleep={"level": 55, "tier": "Discipline", "raw_score": 71.0},
    )
    profile = dict(PROFILE, start_weight_lbs=320.0)
    s3, _, _ = _init(fetch_range=_buddy_ranges())
    ow.write_buddy_json({}, profile, YESTERDAY, character_sheet=sheet)

    buddy = s3.written(_BUDDY_KEY)
    cs = buddy["character_sheet"]
    assert cs["level"] == 30
    assert cs["tier"] == "Momentum"
    assert cs["xp"] == 4200
    # The buddy page shows level/tier only — raw_score stays private to the dashboard.
    assert cs["pillars"]["sleep"] == {"level": 55, "tier": "Discipline"}
    assert cs["pillars"]["mind"] == {"level": None, "tier": None}
    assert buddy["avatar"]["badges"]["sleep"] == "dim"
    assert buddy["avatar"]["composition_score"] == 11.1  # 15 of 135 lbs


def test_write_buddy_json_without_a_character_sheet_nulls_both_blocks(_frozen_pacific):
    s3, _, _ = _init(fetch_range=_buddy_ranges())
    ow.write_buddy_json({}, PROFILE, YESTERDAY)
    buddy = s3.written(_BUDDY_KEY)
    assert buddy["character_sheet"] is None
    assert buddy["avatar"] is None


def test_write_buddy_json_lookback_window_is_seven_days_through_today(_frozen_pacific):
    ranges = _buddy_ranges()
    _init(fetch_range=ranges)
    ow.write_buddy_json({}, PROFILE, YESTERDAY)
    for source in ("macrofactor", "strava", "habitify", "withings"):
        assert ranges.window_for(source) == ("2026-02-25", "2026-03-04")


def _freeze_at(monkeypatch, moment):
    """Re-pin the module clock for the branches that depend on the day of week."""

    class _At(datetime):
        @classmethod
        def now(cls, tz=None):
            return moment if tz is not None else moment.replace(tzinfo=None)

    monkeypatch.setattr(ow, "datetime", _At)


def _buddy_status(s3, area):
    return [line for line in s3.written(_BUDDY_KEY)["status_lines"] if line["area"] == area][0]


def test_write_buddy_json_stale_food_log_is_amber_before_it_is_red(_frozen_pacific):
    # Two logged days, most recent 2 days ago: too thin for the "consistent" branches,
    # not yet the 4+ day silence that reads as off track.
    ranges = _buddy_ranges(
        macrofactor=[
            {"sk": "DATE#2026-03-01", "total_calories_kcal": 2000},
            {"sk": "DATE#2026-03-02", "total_calories_kcal": 2100},
        ]
    )
    s3, _, _ = _init(fetch_range=ranges)
    ow.write_buddy_json({}, PROFILE, YESTERDAY)
    assert _buddy_status(s3, "Food Logging") == {
        "area": "Food Logging",
        "status": "yellow",
        "text": "Last food log was 2 days ago",
    }


def test_write_buddy_json_one_recent_session_this_week_still_reads_green(_frozen_pacific):
    ranges = _buddy_ranges(
        strava=[{"sk": "DATE#2026-03-03", "activities": [{"sport_type": "Run", "name": "Run", "moving_time_seconds": 1800}]}]
    )
    s3, _, _ = _init(fetch_range=ranges)
    ow.write_buddy_json({}, PROFILE, YESTERDAY)
    assert _buddy_status(s3, "Exercise") == {
        "area": "Exercise",
        "status": "green",
        "text": "1 session so far this week",
    }


def test_write_buddy_json_one_stale_session_this_week_reads_amber(monkeypatch, _frozen_pacific):
    # Frozen to Friday: the only session was Monday, so it's inside the week but 4 days old.
    _freeze_at(monkeypatch, datetime(2026, 3, 6, 15, 30, tzinfo=timezone.utc))
    ranges = _buddy_ranges(
        strava=[{"sk": "DATE#2026-03-02", "activities": [{"sport_type": "Run", "name": "Run", "moving_time_seconds": 1800}]}]
    )
    s3, _, _ = _init(fetch_range=ranges)
    ow.write_buddy_json({}, PROFILE, YESTERDAY)
    assert _buddy_status(s3, "Exercise") == {
        "area": "Exercise",
        "status": "yellow",
        "text": "1 session this week, last was 4 days ago",
    }


def test_write_buddy_json_no_sessions_early_in_the_week_is_amber_not_red(monkeypatch, _frozen_pacific):
    # Frozen to Monday: an empty week so far is not yet evidence of anything.
    _freeze_at(monkeypatch, datetime(2026, 3, 2, 15, 30, tzinfo=timezone.utc))
    s3, _, _ = _init(fetch_range=_buddy_ranges(strava=[]))
    ow.write_buddy_json({}, PROFILE, YESTERDAY)
    assert _buddy_status(s3, "Exercise") == {
        "area": "Exercise",
        "status": "yellow",
        "text": "No sessions yet this week (Monday)",
    }


@pytest.mark.parametrize(
    "habit_date,expected_status,expected_text",
    [
        ("2026-03-03", "green", "Routine is holding, habits being logged"),
        ("2026-03-01", "yellow", "Habit tracking quiet for 3 days"),
    ],
)
def test_write_buddy_json_routine_middle_branches(_frozen_pacific, habit_date, expected_status, expected_text):
    ranges = _buddy_ranges(habitify=[{"sk": "DATE#" + habit_date, "completed_count": 5}])
    s3, _, _ = _init(fetch_range=ranges)
    ow.write_buddy_json({}, PROFILE, YESTERDAY)
    routine = _buddy_status(s3, "Routine")
    assert routine["status"] == expected_status
    assert routine["text"] == expected_text


def test_write_buddy_json_flat_weight_reads_as_holding_steady(_frozen_pacific):
    ranges = _buddy_ranges(
        withings=[
            {"sk": "DATE#2026-02-26", "weight_lbs": 305.0},
            {"sk": "DATE#2026-03-03", "weight_lbs": 304.8},
        ]
    )
    s3, _, _ = _init(fetch_range=ranges)
    ow.write_buddy_json({}, PROFILE, YESTERDAY)
    assert _buddy_status(s3, "Weight") == {"area": "Weight", "status": "green", "text": "Weight holding steady"}


def test_write_buddy_json_unparseable_journey_start_zeroes_the_day_count(_frozen_pacific):
    profile = dict(PROFILE, journey_start_date="whenever", start_weight_lbs=320.0)
    s3, _, _ = _init(fetch_range=_buddy_ranges())
    ow.write_buddy_json({}, profile, YESTERDAY)
    assert s3.written(_BUDDY_KEY)["journey"]["days"] == 0


def test_write_buddy_json_falls_back_to_the_report_date_when_the_pacific_clock_fails(monkeypatch):
    from common import pacific_time

    def _boom():
        raise RuntimeError("zoneinfo unavailable")

    monkeypatch.setattr(pacific_time, "pacific_now", _boom)
    s3, _, _ = _init(fetch_range=_buddy_ranges())
    ow.write_buddy_json({}, PROFILE, YESTERDAY)
    assert s3.written(_BUDDY_KEY)["last_updated_friendly"] == YESTERDAY


def test_write_buddy_json_swallows_a_write_failure(_frozen_pacific):
    s3 = FakeS3(put_error=RuntimeError("s3 down"))
    _init(s3=s3, fetch_range=_buddy_ranges())
    ow.write_buddy_json({}, PROFILE, YESTERDAY)
    assert s3.puts == {}
