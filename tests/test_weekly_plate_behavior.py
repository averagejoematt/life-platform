#!/usr/bin/env python3
"""tests/test_weekly_plate_behavior.py — behavioral contracts of
`lambdas/emails/weekly_plate_lambda.py` (The Weekly Plate, Friday food email).

Part of #1658 tranche 2. The caller here is a human reading an email, so the
contracts under test are the ones that reach him:

  * what the AI is *told* — the prompt must carry the data it claims to
    summarise (food names, frequencies, weight trend, targets) and the
    anti-repeat block must carry the previous editions;
  * honest numbers (ADR-104) — an absent weigh-in, an absent macro total or an
    empty food log must never surface as a fabricated 0 or an invented claim;
  * honest degradation — a failed or blocked AI call must not silently ship a
    canned stub as if it were this week's writing, and must not be filed into
    the insight ledger as genuine coaching;
  * partial records — a day record missing `food_log`, a withings row missing
    `weight_lbs`, a stored plate summary missing `wildcard`: none may abort the
    weekly build;
  * the reader-visible HTML — the numbers and sections a reader sees, never the
    exact markup (that is `tests/test_email_render_goldens.py`'s job);
  * the handler — which branches send and which do not. No test in this file
    can reach a real SES/DynamoDB/Bedrock call: every client the module holds is
    replaced with a hand-rolled bounded fake.

Time is frozen module-wide by an autouse fixture — no fixture date is ever
combined with the real clock.
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LAMBDAS = os.path.join(ROOT, "lambdas")
if LAMBDAS not in sys.path:
    sys.path.insert(0, LAMBDAS)

# The module reads these at import time (os.environ[...] — no defaults).
os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("EMAIL_RECIPIENT", "reader@example.invalid")
os.environ.setdefault("EMAIL_SENDER", "plate@example.invalid")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("AI_VALIDATOR_AUTOLOAD", "off")

_import_err = None
try:
    import weekly_plate_lambda as wp
    from common.constants import EXPERIMENT_BASELINE_WEIGHT_LBS
    from experiment.phase_filter import PHASE_FILTER_EXPRESSION
except ImportError as _e:  # pragma: no cover — only when the bundle layout changes
    _import_err = _e
    wp = None  # type: ignore

if _import_err is not None:  # pragma: no cover
    pytestmark = pytest.mark.skip(reason=f"weekly_plate_lambda unavailable: {_import_err}")  # type: ignore


# ──────────────────────────────────────────────────────────────────────────────
# Frozen clock
# ──────────────────────────────────────────────────────────────────────────────

# The Lambda fires Friday 18:00 PT == Saturday 02:00 UTC.
FROZEN_NOW = datetime(2026, 6, 6, 2, 0, 0, tzinfo=timezone.utc)

TODAY = "2026-06-06"  # now().date()
END = "2026-06-05"  # today - 1  → the last complete day
START_14D = "2026-05-23"  # today - 14
WEIGHT_START = "2026-05-07"  # today - 30
WEEK_CUTOFF = "2026-05-30"  # today - 7  (the 7-day weight window's inclusive floor)
HISTORY_START = "2026-03-28"  # today - 70 (plate-history lower bound)


class _FrozenDatetime(datetime):
    """`datetime` subclass with a pinned `now()`.

    A subclass (not a Mock) keeps `strptime`, arithmetic and `.date()` working —
    the module uses all three off the same name.
    """

    @classmethod
    def now(cls, tz=None):
        return FROZEN_NOW if tz else FROZEN_NOW.replace(tzinfo=None)

    @classmethod
    def utcnow(cls):
        return FROZEN_NOW.replace(tzinfo=None)


@pytest.fixture(autouse=True)
def frozen_clock(monkeypatch):
    monkeypatch.setattr(wp, "datetime", _FrozenDatetime)
    return FROZEN_NOW


# ──────────────────────────────────────────────────────────────────────────────
# Test doubles — hand-rolled and bounded (never a MagicMock in a read loop)
# ──────────────────────────────────────────────────────────────────────────────


class FakeTable:
    """DynamoDB Table stand-in keyed the way this module keys the real table.

    Honours the one query shape the module issues (`pk = :pk AND sk BETWEEN
    :s AND :e`) plus `Limit` / `ScanIndexForward`, and records every call so a
    test can assert on the key window and the ADR-058 phase filter.
    """

    def __init__(self, items=None):
        self.items = {(i["pk"], i["sk"]): i for i in (items or [])}
        self.puts = []
        self.queries = []
        self.query_error = None
        self.put_error = None
        self.get_error = None
        self.pages = None  # optional LastEvaluatedKey-chained responses

    def put_item(self, Item=None, **kwargs):
        self.puts.append(Item)
        if self.put_error is not None:
            raise self.put_error
        self.items[(Item["pk"], Item["sk"])] = Item
        return {}

    def get_item(self, Key=None, **kwargs):
        if self.get_error is not None:
            raise self.get_error
        item = self.items.get((Key["pk"], Key["sk"]))
        return {"Item": item} if item is not None else {}

    def query(self, **kwargs):
        self.queries.append(kwargs)
        if self.query_error is not None:
            raise self.query_error
        if self.pages:
            return self.pages.pop(0)
        vals = kwargs.get("ExpressionAttributeValues", {})
        pk = vals.get(":pk")
        rows = [v for (p, _s), v in self.items.items() if p == pk]
        if ":s" in vals and ":e" in vals:
            rows = [r for r in rows if vals[":s"] <= r["sk"] <= vals[":e"]]
        rows.sort(key=lambda r: r["sk"], reverse=not kwargs.get("ScanIndexForward", True))
        limit = kwargs.get("Limit")
        if limit is not None:
            rows = rows[:limit]
        return {"Items": rows}


class FakeSes:
    """SESv2 stand-in. Nothing in this file can reach a real send path."""

    def __init__(self):
        self.sent = []
        self.error = None

    def send_email(self, **kwargs):
        if self.error is not None:
            raise self.error
        self.sent.append(kwargs)
        return {"MessageId": "fake"}


class FakeInsightWriter:
    def __init__(self, context=""):
        self.context = context
        self.context_error = None
        self.written = []

    def build_insights_context(self, **kwargs):
        if self.context_error is not None:
            raise self.context_error
        return self.context

    def write_insight(self, **kwargs):
        self.written.append(kwargs)
        return True


# ──────────────────────────────────────────────────────────────────────────────
# Row builders
# ──────────────────────────────────────────────────────────────────────────────


def food(name, cal=None, protein=None, carbs=None, fat=None, fiber=None, at=None):
    item = {"food_name": name}
    if at is not None:
        item["time"] = at
    for key, val in (
        ("calories_kcal", cal),
        ("protein_g", protein),
        ("carbs_g", carbs),
        ("fat_g", fat),
        ("fiber_g", fiber),
    ):
        if val is not None:
            item[key] = val
    return item


def mf_rec(foods=None, **totals):
    """A macrofactor day record as `query_range` hands it back (already d2f'd)."""
    rec = {}
    if foods is not None:
        rec["food_log"] = foods
    rec.update(totals)
    return rec


def mf_row(date_str, foods=None, **totals):
    row = {"pk": wp.USER_PREFIX + "macrofactor", "sk": f"DATE#{date_str}", "date": date_str}
    row.update(mf_rec(foods, **totals))
    return row


def wi_row(date_str, **fields):
    return {"pk": wp.USER_PREFIX + "withings", "sk": f"DATE#{date_str}", "date": date_str, **fields}


def profile_row(**fields):
    return {"pk": "USER#matthew", "sk": "PROFILE#v1", **fields}


def memory_row(date_str, **fields):
    return {"pk": wp.USER_PREFIX_MEMORY, "sk": f"MEMORY#weekly_plate#{date_str}", **fields}


@pytest.fixture
def table(monkeypatch):
    t = FakeTable()
    monkeypatch.setattr(wp, "table", t)
    return t


@pytest.fixture
def ses(monkeypatch):
    s = FakeSes()
    monkeypatch.setattr(wp, "ses", s)
    return s


# A realistic shape for what Sonnet returns: five sections, cards, bold names.
AI_HTML = (
    '<div style="font-size:17px;font-weight:700;">🍳 This Week on Your Plate</div>'
    "<div>You leaned hard on ground turkey and eggs.</div>"
    '<div style="font-size:17px;font-weight:700;">🏆 Your Greatest Hits</div>'
    '<div style="border-left:2px solid #4cc9f0;">'
    "<strong>Ground Turkey 93/7</strong> — your protein workhorse.</div>"
    '<div style="font-size:17px;font-weight:700;">🍲 Try This</div>'
    '<div style="background:#16213e;"><strong>Smoky Turkey Kofte Bowls</strong>'
    "<div>weeknight easy · high protein</div></div>"
    '<div style="background:#16213e;"><strong>Charred Cabbage Tacos</strong>'
    "<div>weeknight easy · big fibre hit</div></div>"
    '<div style="font-size:17px;font-weight:700;">🎲 The Wildcard</div>'
    '<div style="border-left:3px solid #f59e0b;">Miso paste, the umami shortcut.</div>'
    '<div style="font-size:17px;font-weight:700;">🛒 The Grocery Run</div>'
)

# The same edition written the way SYSTEM_PROMPT actually demands: "Approximate
# macros per serving (cal/P/C/F)" on every Try This card.
AI_HTML_WITH_PER_SERVING_MACROS = AI_HTML.replace("weeknight easy · high protein", "520 cal · 42P / 30C / 18F · weeknight easy").replace(
    "weeknight easy · big fibre hit", "410 cal · 12P / 44C / 14F · weeknight easy"
)


def _supplement_terms():
    """The supplement-exclusion terms, DERIVED from the module — never a literal
    list here, so the guard grows with the set (repo rule: guard the SET)."""
    for const in wp.extract_food_data.__code__.co_consts:
        if isinstance(const, (tuple, frozenset, set)) and const and all(isinstance(x, str) for x in const):
            if any("supplement" in x for x in const):
                return sorted(const)
    raise AssertionError("could not locate the supplement-exclusion term set in extract_food_data")


# ══════════════════════════════════════════════════════════════════════════════
# Plate history — the anti-repeat memory
# ══════════════════════════════════════════════════════════════════════════════


class TestLoadPlateHistory:
    def test_history_reads_a_seventy_day_window_ending_today(self, table):
        wp.load_plate_history(TODAY)
        vals = table.queries[0]["ExpressionAttributeValues"]
        assert vals[":pk"] == wp.USER_PREFIX_MEMORY
        assert vals[":s"] == f"MEMORY#weekly_plate#{HISTORY_START}"
        assert vals[":e"] == f"MEMORY#weekly_plate#{TODAY}"

    def test_history_asks_for_the_newest_editions_first_up_to_the_module_limit(self, table):
        wp.load_plate_history(TODAY)
        q = table.queries[0]
        assert q["ScanIndexForward"] is False
        # Derived from the module constant so raising MAX_PLATE_HISTORY can't
        # silently leave this assertion behind.
        assert q["Limit"] == wp.MAX_PLATE_HISTORY

    def test_history_read_carries_the_phase_filter(self, table):
        """ADR-058 default-deny: a previous cycle's plates must not leak back in."""
        wp.load_plate_history(TODAY)
        assert PHASE_FILTER_EXPRESSION in table.queries[0]["FilterExpression"]

    def test_history_returns_the_stored_editions_newest_first(self, table):
        for d in ("2026-05-15", "2026-05-22", "2026-05-29"):
            row = memory_row(d, plate_date=d, wildcard=f"w-{d}")
            table.items[(row["pk"], row["sk"])] = row
        hist = wp.load_plate_history(TODAY)
        assert [h["plate_date"] for h in hist] == ["2026-05-29", "2026-05-22", "2026-05-15"]

    def test_history_never_returns_more_than_the_module_limit(self, table):
        for i in range(wp.MAX_PLATE_HISTORY + 3):
            d = f"2026-04-{10 + i:02d}"
            row = memory_row(d, plate_date=d)
            table.items[(row["pk"], row["sk"])] = row
        assert len(wp.load_plate_history(TODAY)) == wp.MAX_PLATE_HISTORY

    def test_history_values_arrive_as_plain_floats_not_decimals(self, table):
        row = memory_row("2026-05-29", plate_date="2026-05-29", calories=Decimal("1810.5"))
        table.items[(row["pk"], row["sk"])] = row
        assert wp.load_plate_history(TODAY)[0]["calories"] == 1810.5

    def test_a_failed_history_read_degrades_to_no_history_rather_than_aborting(self, table):
        """Anti-repeat context is a nice-to-have; the email still has to ship."""
        table.query_error = RuntimeError("throttled")
        assert wp.load_plate_history(TODAY) == []


class TestPlateHistoryContext:
    def test_no_history_produces_no_context_block_at_all(self):
        """Empty string, so the handler prepends nothing to the prompt."""
        assert wp.build_plate_history_context([]) == ""

    def test_each_past_wildcard_is_named_with_an_explicit_do_not_repeat(self):
        ctx = wp.build_plate_history_context([{"plate_date": "2026-05-29", "wildcard": "Miso paste"}])
        assert "Miso paste" in ctx
        line = [ln for ln in ctx.splitlines() if "Miso paste" in ln][0]
        assert "DO NOT REPEAT" in line

    def test_past_recipes_are_named_with_an_explicit_do_not_repeat(self):
        ctx = wp.build_plate_history_context([{"plate_date": "2026-05-29", "recipes": ["Turkey Kofte Bowls"]}])
        line = [ln for ln in ctx.splitlines() if "Turkey Kofte Bowls" in ln][0]
        assert "DO NOT REPEAT" in line

    def test_weeks_are_numbered_backwards_from_the_most_recent(self):
        ctx = wp.build_plate_history_context([{"plate_date": "2026-05-29", "wildcard": "a"}, {"plate_date": "2026-05-22", "wildcard": "b"}])
        assert "Week -1 (2026-05-29)" in ctx
        assert "Week -2 (2026-05-22)" in ctx

    def test_greatest_hits_are_capped_at_six_names_per_past_week(self):
        foods = [f"food-{i}" for i in range(10)]
        ctx = wp.build_plate_history_context([{"plate_date": "2026-05-29", "top_foods": foods}])
        assert "food-5" in ctx
        assert "food-6" not in ctx

    def test_past_recipes_are_capped_at_four_per_week(self):
        recipes = [f"Recipe {i}" for i in range(6)]
        ctx = wp.build_plate_history_context([{"plate_date": "2026-05-29", "recipes": recipes}])
        assert "Recipe 3" in ctx
        assert "Recipe 4" not in ctx

    def test_a_past_edition_with_no_wildcard_renders_no_empty_wildcard_line(self):
        """Partial record: absence is omitted, not rendered as 'Wildcard was: '."""
        ctx = wp.build_plate_history_context([{"plate_date": "2026-05-29", "top_foods": ["eggs"]}])
        assert "Wildcard was" not in ctx

    def test_a_past_edition_with_only_a_date_does_not_crash_the_build(self):
        ctx = wp.build_plate_history_context([{"plate_date": "2026-05-29"}])
        assert "Week -1 (2026-05-29)" in ctx

    def test_a_past_edition_with_no_date_at_all_renders_a_placeholder_not_a_crash(self):
        ctx = wp.build_plate_history_context([{"wildcard": "Miso paste"}])
        assert "Week -1 (?)" in ctx

    def test_the_context_states_the_anti_repeat_rules_the_ai_must_follow(self):
        ctx = wp.build_plate_history_context([{"plate_date": "2026-05-29", "wildcard": "Miso paste"}])
        assert "ANTI-REPEAT RULES" in ctx
        assert "different ingredient" in ctx


# ══════════════════════════════════════════════════════════════════════════════
# Plate summary extraction + storage
# ══════════════════════════════════════════════════════════════════════════════


class TestExtractPlateSummary:
    def test_summary_carries_the_plate_date_and_the_top_foods_it_was_given(self):
        s = wp.extract_plate_summary(AI_HTML, ["ground turkey", "eggs"], END)
        assert s["plate_date"] == END
        assert s["top_foods"] == ["ground turkey", "eggs"]

    def test_top_foods_are_capped_at_eight(self):
        s = wp.extract_plate_summary(AI_HTML, [f"f{i}" for i in range(12)], END)
        assert s["top_foods"] == [f"f{i}" for i in range(8)]

    def test_the_wildcard_ingredient_is_recovered_from_the_wildcard_section(self):
        s = wp.extract_plate_summary(AI_HTML, [], END)
        assert s["wildcard"].startswith("Miso paste")

    def test_the_suggested_recipe_names_are_recovered(self):
        s = wp.extract_plate_summary(AI_HTML, [], END)
        assert "Smoky Turkey Kofte Bowls" in s["recipes"]
        assert "Charred Cabbage Tacos" in s["recipes"]

    def test_section_headers_are_not_mistaken_for_recipe_names(self):
        html = "<strong>Your Greatest Hits</strong>x<strong>The Grocery Run</strong>y<strong>Bourbon Glazed Salmon</strong>z"
        s = wp.extract_plate_summary(html, [], END)
        assert s["recipes"] == ["Bourbon Glazed Salmon"]

    def test_short_bold_fragments_are_not_recorded_as_recipes(self):
        """A bolded macro label ('520 cal') must not become an anti-repeat entry."""
        html = "<strong>Protein</strong>a<strong>Cal</strong>b"
        assert wp.extract_plate_summary(html, [], END)["recipes"] == []

    def test_no_more_than_five_recipes_are_stored(self):
        html = "".join(f"<strong>Recipe Number {i} Special</strong>x" for i in range(9))
        assert len(wp.extract_plate_summary(html, [], END)["recipes"]) == 5

    def test_content_with_no_recognisable_sections_yields_empty_fields_not_junk(self):
        """The AI-failure stub goes through here too — it must not invent a wildcard."""
        stub = '<div style="background:#16213e;">AI content unavailable this week. Check CloudWatch logs.</div>'
        s = wp.extract_plate_summary(stub, ["eggs"], END)
        assert s["wildcard"] == ""
        assert s["recipes"] == []

    def test_the_stored_wildcard_is_length_capped(self):
        long_wc = "W" + "o" * 200
        html = f'<div>The Wildcard</div><div style="x">{long_wc}</div>'
        assert len(wp.extract_plate_summary(html, [], END)["wildcard"]) <= 80

    def test_a_greatest_hits_food_name_is_not_stored_as_a_recipe_to_avoid(self):
        """FIXED (#2221): the recipe regex scanned the WHOLE email, so bolded Greatest
        Hits food names — by construction his most-frequent REAL foods — were stored as
        'recipes' and replayed into the next edition inside the DO-NOT-REPEAT block,
        steering the writer away from his own staples. The scan is now section-scoped."""
        s = wp.extract_plate_summary(AI_HTML, ["ground turkey 93/7"], END)
        assert "Ground Turkey 93/7" not in s["recipes"]
        assert s["recipes"] == ["Smoky Turkey Kofte Bowls", "Charred Cabbage Tacos"]

    def test_a_greatest_hits_name_stays_out_even_when_it_is_not_a_listed_top_food(self):
        """The section fence does the work — not a name-matching filter against the
        top-foods list, which is only the second line of defence."""
        assert "Ground Turkey 93/7" not in wp.extract_plate_summary(AI_HTML, [], END)["recipes"]

    def test_the_two_sections_the_extractor_fences_on_are_sections_the_prompt_demands(self):
        """Guard the SET: if SYSTEM_PROMPT renames either section, the fence would
        silently fall back to scanning the whole email again."""
        titles = wp.plate_section_titles()
        assert "Try This" in titles
        assert "Your Greatest Hits" in titles


class TestStorePlateSummary:
    def test_the_summary_is_keyed_into_the_platform_memory_partition_for_today(self, table):
        wp.store_plate_summary({"plate_date": END, "top_foods": ["eggs"]}, TODAY)
        item = table.puts[0]
        assert item["pk"] == wp.USER_PREFIX_MEMORY
        assert item["sk"] == f"MEMORY#weekly_plate#{TODAY}"
        assert item["category"] == "weekly_plate"

    def test_the_summary_records_the_data_window_end_not_the_write_date(self, table):
        wp.store_plate_summary({"plate_date": END}, TODAY)
        assert table.puts[0]["plate_date"] == END

    def test_the_write_is_stamped_with_the_run_time(self, table):
        wp.store_plate_summary({"plate_date": END}, TODAY)
        assert table.puts[0]["stored_at"] == FROZEN_NOW.isoformat()

    def test_absent_fields_are_omitted_rather_than_written_as_empty_values(self, table):
        """An empty wildcard must not be stored — it would render a blank
        'Wildcard was: ' anti-repeat line in every future edition."""
        wp.store_plate_summary({"plate_date": END, "wildcard": "", "recipes": [], "top_foods": []}, TODAY)
        item = table.puts[0]
        assert "wildcard" not in item
        assert "recipes" not in item
        assert "top_foods" not in item

    def test_populated_fields_round_trip_verbatim(self, table):
        wp.store_plate_summary(
            {"plate_date": END, "top_foods": ["eggs"], "wildcard": "Miso paste", "recipes": ["Kofte Bowls"]},
            TODAY,
        )
        item = table.puts[0]
        assert item["top_foods"] == ["eggs"]
        assert item["wildcard"] == "Miso paste"
        assert item["recipes"] == ["Kofte Bowls"]

    def test_a_failed_summary_write_is_non_fatal(self, table):
        """Memory is a nice-to-have; it must never take the email down."""
        table.put_error = RuntimeError("ProvisionedThroughputExceeded")
        wp.store_plate_summary({"plate_date": END}, TODAY)  # must not raise


# ══════════════════════════════════════════════════════════════════════════════
# Data gathering
# ══════════════════════════════════════════════════════════════════════════════


class TestGatherData:
    def test_no_profile_means_no_email_rather_than_a_default_shaped_one(self, table):
        assert wp.gather_data() is None

    def test_the_food_window_is_the_last_fourteen_complete_days(self, table):
        table.items[("USER#matthew", "PROFILE#v1")] = profile_row(calorie_target=1800)
        data = wp.gather_data()
        assert data["dates"] == {"start": START_14D, "end": END}

    def test_the_food_window_excludes_today_whose_log_is_still_being_written(self, table):
        table.items[("USER#matthew", "PROFILE#v1")] = profile_row()
        assert wp.gather_data()["dates"]["end"] < TODAY

    def test_weight_is_read_over_a_wider_thirty_day_window_than_food(self, table):
        table.items[("USER#matthew", "PROFILE#v1")] = profile_row()
        wp.gather_data()
        windows = {
            q["ExpressionAttributeValues"][":pk"]: (
                q["ExpressionAttributeValues"][":s"],
                q["ExpressionAttributeValues"][":e"],
            )
            for q in table.queries
        }
        assert windows[wp.USER_PREFIX + "macrofactor"] == (f"DATE#{START_14D}", f"DATE#{END}")
        assert windows[wp.USER_PREFIX + "withings"] == (f"DATE#{WEIGHT_START}", f"DATE#{END}")

    def test_gathered_records_are_keyed_by_date(self, table):
        table.items[("USER#matthew", "PROFILE#v1")] = profile_row()
        for row in (mf_row("2026-05-30", [food("Eggs", cal=180)]), wi_row("2026-05-30", weight_lbs=Decimal("306.0"))):
            table.items[(row["pk"], row["sk"])] = row
        data = wp.gather_data()
        assert list(data["macrofactor"]) == ["2026-05-30"]
        assert data["withings"]["2026-05-30"]["weight_lbs"] == 306.0

    def test_records_outside_the_window_are_not_gathered(self, table):
        table.items[("USER#matthew", "PROFILE#v1")] = profile_row()
        for row in (mf_row("2026-04-01", [food("Eggs", cal=180)]), mf_row(END, [food("Eggs", cal=180)])):
            table.items[(row["pk"], row["sk"])] = row
        assert list(wp.gather_data()["macrofactor"]) == [END]


# ══════════════════════════════════════════════════════════════════════════════
# Food extraction — what the AI is actually shown
# ══════════════════════════════════════════════════════════════════════════════


class TestExtractFoodData:
    def test_days_come_back_in_chronological_order(self):
        mf = {d: mf_rec([food("Eggs", cal=180)]) for d in ("2026-06-04", "2026-06-02", "2026-06-03")}
        days, _ = wp.extract_food_data(mf)
        assert [d["date"] for d in days] == ["2026-06-02", "2026-06-03", "2026-06-04"]

    def test_every_logged_food_reaches_the_flat_list_in_day_order(self):
        mf = {
            "2026-06-03": mf_rec([food("Eggs", cal=180), food("Rice", cal=200)]),
            "2026-06-04": mf_rec([food("Ground Turkey 93/7", cal=320)]),
        }
        _, all_foods = wp.extract_food_data(mf)
        assert [f["name"] for f in all_foods] == ["Eggs", "Rice", "Ground Turkey 93/7"]

    def test_a_food_items_macros_pass_through_unchanged(self):
        mf = {"2026-06-04": mf_rec([food("Ground Turkey 93/7", cal=320, protein=44, carbs=0, fat=14, fiber=0, at="12:30")])}
        _, all_foods = wp.extract_food_data(mf)
        assert all_foods[0] == {
            "name": "Ground Turkey 93/7",
            "time": "12:30",
            "cal": 320.0,
            "protein_g": 44.0,
            "carbs_g": 0.0,
            "fat_g": 14.0,
            "fiber_g": 0.0,
        }

    def test_daily_totals_are_taken_from_the_record_not_recomputed_from_items(self):
        """MacroFactor's own day totals are authoritative — they include items
        this extractor drops (supplements)."""
        mf = {
            "2026-06-04": mf_rec(
                [food("Eggs", cal=180)],
                total_calories_kcal=1810,
                total_protein_g=195,
                total_carbs_g=120,
                total_fat_g=60,
                total_fiber_g=28,
            )
        }
        days, _ = wp.extract_food_data(mf)
        assert (days[0]["total_calories"], days[0]["total_protein_g"]) == (1810.0, 195.0)
        assert (days[0]["total_carbs_g"], days[0]["total_fat_g"], days[0]["total_fiber_g"]) == (120.0, 60.0, 28.0)

    def test_an_unlogged_daily_total_is_absent_not_zero(self):
        """ADR-104: a day with no fiber figure is not a zero-fiber day."""
        mf = {"2026-06-04": mf_rec([food("Eggs", cal=180)], total_calories_kcal=1810)}
        days, _ = wp.extract_food_data(mf)
        assert days[0]["total_fiber_g"] is None
        assert days[0]["total_protein_g"] is None

    def test_a_day_record_with_no_food_log_still_produces_a_day_not_a_crash(self):
        """MacroFactor's API-refresh path writes day records whose food_log is
        dropped — the weekly build must survive them."""
        mf = {"2026-06-04": mf_rec(None, total_calories_kcal=1810)}
        days, all_foods = wp.extract_food_data(mf)
        assert days[0]["foods"] == []
        assert all_foods == []

    def test_a_day_record_with_an_empty_food_log_produces_a_day_with_no_foods(self):
        days, all_foods = wp.extract_food_data({"2026-06-04": mf_rec([])})
        assert days[0]["foods"] == [] and all_foods == []

    def test_an_item_with_no_name_is_labelled_unknown_rather_than_dropped_silently(self):
        _, all_foods = wp.extract_food_data({"2026-06-04": mf_rec([{"calories_kcal": 100}])})
        assert all_foods[0]["name"] == "unknown"

    def test_an_item_with_no_logged_time_is_marked_unknown_not_given_a_fake_time(self):
        """The prompt tells the AI to infer meals from same date AND time — a
        fabricated time would license a fabricated meal composition."""
        _, all_foods = wp.extract_food_data({"2026-06-04": mf_rec([food("Eggs", cal=180)])})
        assert all_foods[0]["time"] == "?"

    @pytest.mark.parametrize("term", _supplement_terms() if wp is not None else [])
    def test_each_supplement_term_is_excluded_from_the_food_narrative(self, term):
        mf = {"2026-06-04": mf_rec([food(f"Optimum {term.title()} Blend", cal=30), food("Eggs", cal=180)])}
        _, all_foods = wp.extract_food_data(mf)
        assert [f["name"] for f in all_foods] == ["Eggs"]

    def test_supplement_matching_is_case_insensitive(self):
        mf = {"2026-06-04": mf_rec([food("CREATINE Monohydrate", cal=0), food("Eggs", cal=180)])}
        _, all_foods = wp.extract_food_data(mf)
        assert [f["name"] for f in all_foods] == ["Eggs"]

    def test_a_real_food_whose_name_merely_resembles_nothing_is_kept(self):
        mf = {"2026-06-04": mf_rec([food("Vitamix Green Smoothie", cal=180), food("Salmon", cal=300)])}
        _, all_foods = wp.extract_food_data(mf)
        assert "Salmon" in [f["name"] for f in all_foods]

    def test_decimal_valued_macros_from_dynamodb_become_floats(self):
        mf = {"2026-06-04": mf_rec([food("Eggs", cal=Decimal("180.5"))], total_calories_kcal=Decimal("1810.4"))}
        days, all_foods = wp.extract_food_data(mf)
        assert all_foods[0]["cal"] == 180.5
        assert days[0]["total_calories"] == 1810.4
        assert not isinstance(days[0]["total_calories"], Decimal)

    def test_an_item_with_no_logged_macros_is_absent_not_a_zero_calorie_food(self):
        """ADR-104 (#2558, was xfail): an absent item macro is None, like the day totals."""
        _, all_foods = wp.extract_food_data({"2026-06-04": mf_rec([food("Leftover casserole")])})
        assert all_foods[0]["cal"] is None
        assert all_foods[0]["protein_g"] is None


class TestAnalyzeFoodPatterns:
    def test_frequency_counts_are_the_number_of_times_each_food_was_logged(self):
        foods = [{"name": n} for n in ("Eggs", "Rice", "Eggs", "Eggs", "Rice", "Salmon")]
        top = wp.analyze_food_patterns(foods)["top_foods"]
        counts = {f["name"]: f["count"] for f in top}
        assert counts == {"eggs": 3, "rice": 2, "salmon": 1}

    def test_the_most_frequent_food_is_listed_first(self):
        foods = [{"name": n} for n in ("Rice", "Eggs", "Eggs", "Eggs", "Rice")]
        assert wp.analyze_food_patterns(foods)["top_foods"][0] == {"name": "eggs", "count": 3}

    def test_the_same_food_logged_with_different_casing_or_padding_counts_once(self):
        foods = [{"name": n} for n in ("Eggs", " eggs ", "EGGS")]
        top = wp.analyze_food_patterns(foods)["top_foods"]
        assert top == [{"name": "eggs", "count": 3}]

    def test_at_most_twenty_foods_are_reported(self):
        foods = [{"name": f"food-{i}"} for i in range(30)]
        assert len(wp.analyze_food_patterns(foods)["top_foods"]) == 20

    def test_an_empty_food_log_produces_no_greatest_hits_rather_than_a_placeholder(self):
        """ADR-104: nothing logged means nothing claimed."""
        assert wp.analyze_food_patterns([])["top_foods"] == []


# ══════════════════════════════════════════════════════════════════════════════
# Weight trend + weight context
# ══════════════════════════════════════════════════════════════════════════════

WITHINGS = {
    "2026-05-08": {"weight_lbs": 310.0},
    "2026-06-01": {"weight_lbs": 306.0},
    "2026-06-04": {"weight_lbs": 304.2},
}


class TestWeightTrend:
    def test_no_weigh_ins_produces_no_trend_rather_than_a_zero_trend(self):
        """ADR-104: an empty scale window must not read as 'held steady'."""
        assert wp.extract_weight_trend({}) is None

    def test_records_without_a_weight_field_produce_no_trend(self):
        assert wp.extract_weight_trend({"2026-06-01": {"fat_ratio": 38.0}}) is None

    def test_the_latest_weigh_in_is_the_most_recent_by_date(self):
        assert wp.extract_weight_trend(WITHINGS)["latest_weight_lbs"] == 304.2

    def test_the_thirty_day_change_spans_the_first_and_last_weigh_in(self):
        # 304.2 - 310.0 = -5.8
        assert wp.extract_weight_trend(WITHINGS)["change_30d_lbs"] == -5.8

    def test_the_seven_day_change_uses_only_weigh_ins_inside_the_last_week(self):
        # window floor 2026-05-30 → 306.0 (06-01) then 304.2 (06-04) → -1.8
        assert wp.extract_weight_trend(WITHINGS)["change_7d_lbs"] == -1.8

    def test_the_seven_day_window_floor_is_seven_days_back_from_today(self):
        just_inside = wp.extract_weight_trend({WEEK_CUTOFF: {"weight_lbs": 310.0}, "2026-06-04": {"weight_lbs": 304.2}})
        assert just_inside["change_7d_lbs"] == -5.8
        day_before = (datetime.strptime(WEEK_CUTOFF, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
        just_outside = wp.extract_weight_trend({day_before: {"weight_lbs": 310.0}, "2026-06-04": {"weight_lbs": 304.2}})
        assert just_outside["change_7d_lbs"] is None

    def test_a_single_weigh_in_this_week_yields_no_weekly_change_claim(self):
        """One point is not a trend — absence beats a fabricated 0.0."""
        t = wp.extract_weight_trend({"2026-06-04": {"weight_lbs": 304.2}})
        assert t["change_7d_lbs"] is None
        assert t["change_30d_lbs"] == 0.0  # first == last, an honest identity

    def test_the_legacy_weight_lb_field_name_is_still_understood(self):
        assert wp.extract_weight_trend({"2026-06-04": {"weight_lb": 304.2}})["latest_weight_lbs"] == 304.2

    def test_the_measurement_count_reports_only_days_that_actually_had_a_weight(self):
        data = dict(WITHINGS)
        data["2026-06-02"] = {"fat_ratio": 38.0}
        assert wp.extract_weight_trend(data)["measurements"] == 3


class TestWeightContext:
    def test_the_context_states_current_start_goal_lost_and_remaining(self):
        ctx = wp.build_weight_context(WITHINGS, {"journey_start_weight_lbs": 321.6, "goal_weight_lbs": 185})
        # 321.6 - 304.2 = 17.4 lost;  304.2 - 185 = 119.2 to go
        assert "Currently 304.2 lbs" in ctx
        assert "started 321.6" in ctx and "goal 185" in ctx
        assert "17.4 lost" in ctx and "119.2 to go" in ctx

    def test_a_losing_week_is_reported_with_a_signed_negative_change(self):
        ctx = wp.build_weight_context(WITHINGS, {"journey_start_weight_lbs": 321.6, "goal_weight_lbs": 185})
        assert "-1.8 lbs this week" in ctx

    def test_a_gaining_week_is_reported_with_an_explicit_plus(self):
        gaining = {"2026-06-01": {"weight_lbs": 304.2}, "2026-06-04": {"weight_lbs": 306.0}}
        ctx = wp.build_weight_context(gaining, {"journey_start_weight_lbs": 321.6, "goal_weight_lbs": 185})
        assert "+1.8 lbs this week" in ctx

    def test_no_weekly_data_point_means_no_weekly_claim_in_the_prompt(self):
        one = {"2026-06-04": {"weight_lbs": 304.2}}
        ctx = wp.build_weight_context(one, {"journey_start_weight_lbs": 321.6, "goal_weight_lbs": 185})
        assert "this week" not in ctx

    def test_a_missing_journey_start_falls_back_to_the_experiment_baseline(self):
        ctx = wp.build_weight_context(WITHINGS, {"goal_weight_lbs": 185})
        assert f"started {EXPERIMENT_BASELINE_WEIGHT_LBS}" in ctx

    def test_with_no_weigh_ins_the_context_states_the_goal_and_invents_no_weight(self):
        """ADR-104: the AI must not be handed a current weight that doesn't exist."""
        ctx = wp.build_weight_context({}, {"journey_start_weight_lbs": 321.6, "goal_weight_lbs": 185})
        assert ctx == "Goal: 321.6 -> 185 lbs"
        assert "Currently" not in ctx


# ══════════════════════════════════════════════════════════════════════════════
# The prompt — does it carry the data it claims to summarise?
# ══════════════════════════════════════════════════════════════════════════════


def _payload(mf=None, withings=None, profile=None):
    data = {
        "macrofactor": mf if mf is not None else {},
        "withings": withings if withings is not None else {},
        "profile": profile if profile is not None else {},
        "dates": {"start": START_14D, "end": END},
    }
    return json.loads(wp.build_user_message(data))


class TestUserMessage:
    def test_the_payload_is_valid_json(self):
        assert isinstance(_payload(), dict)

    def test_every_logged_food_name_reaches_the_prompt(self):
        mf = {"2026-06-04": mf_rec([food("Ground Turkey 93/7", cal=320), food("Charred Cabbage", cal=60)])}
        names = [f["name"] for d in _payload(mf)["food_log_14_days"] for f in d["foods"]]
        assert names == ["Ground Turkey 93/7", "Charred Cabbage"]

    def test_the_prompt_carries_the_frequency_table_the_greatest_hits_section_needs(self):
        mf = {
            "2026-06-03": mf_rec([food("Eggs", cal=180), food("Eggs", cal=180)]),
            "2026-06-04": mf_rec([food("Eggs", cal=180), food("Rice", cal=200)]),
        }
        freq = {f["name"]: f["count"] for f in _payload(mf)["food_frequency"]["top_foods"]}
        assert freq == {"eggs": 3, "rice": 1}

    def test_the_prompt_carries_the_weight_trend(self):
        assert _payload(withings=WITHINGS)["weight_trend"]["latest_weight_lbs"] == 304.2

    def test_with_no_weigh_ins_the_prompt_carries_a_null_trend_not_a_zero(self):
        """ADR-104 at the prompt boundary — the AI cannot 'weave in' a number
        that isn't there if it is handed null."""
        assert _payload(withings={})["weight_trend"] is None

    def test_the_prompt_carries_the_profile_targets(self):
        targets = _payload(profile={"calorie_target": 2000, "protein_target_g": 210, "goal_weight_lbs": 190})["profile_targets"]
        assert targets["calorie_target"] == 2000
        assert targets["protein_target_g"] == 210
        assert targets["goal_weight_lbs"] == 190

    def test_absent_targets_fall_back_to_the_documented_defaults(self):
        targets = _payload(profile={})["profile_targets"]
        assert (targets["calorie_target"], targets["protein_target_g"], targets["goal_weight_lbs"]) == (1800, 190, 185)

    def test_the_eating_window_is_stated_so_the_ai_can_time_its_suggestions(self):
        assert "16:8" in _payload()["profile_targets"]["eating_window"]

    def test_a_decimal_valued_record_does_not_break_serialisation(self):
        mf = {"2026-06-04": mf_rec([food("Eggs", cal=Decimal("180"))], total_calories_kcal=Decimal("1810"))}
        assert _payload(mf)["food_log_14_days"][0]["foods"][0]["cal"] == 180.0


class TestSystemPrompt:
    def test_the_system_prompt_has_no_unfilled_placeholders(self):
        rendered = wp.build_system_prompt({"calorie_target": 1800, "protein_target_g": 190}, WITHINGS)
        assert "{weight_context}" not in rendered
        assert "{calorie_target}" not in rendered
        assert "{protein_target_g}" not in rendered

    def test_the_system_prompt_carries_the_weight_context(self):
        rendered = wp.build_system_prompt({"journey_start_weight_lbs": 321.6, "goal_weight_lbs": 185}, WITHINGS)
        assert "Currently 304.2 lbs" in rendered

    def test_the_system_prompt_carries_the_calorie_and_protein_targets(self):
        rendered = wp.build_system_prompt({"calorie_target": 2000, "protein_target_g": 210}, WITHINGS)
        assert "2000 cal/day" in rendered
        assert "210g protein" in rendered

    def test_absent_targets_render_the_documented_defaults(self):
        rendered = wp.build_system_prompt({}, WITHINGS)
        assert "1800 cal/day" in rendered and "190g protein" in rendered

    def test_the_system_prompt_states_the_grounding_rules_that_keep_meals_honest(self):
        """The 'no invented pairings' instruction is the module's own
        hallucination guard — losing it silently would license fabricated meals."""
        rendered = wp.build_system_prompt({}, WITHINGS)
        assert "HALLUCINATION PREVENTION" in rendered
        assert "Do NOT invent side dishes" in rendered


# ══════════════════════════════════════════════════════════════════════════════
# The rendered email — what the reader sees
# ══════════════════════════════════════════════════════════════════════════════


class TestEmailHtml:
    def test_the_ai_body_is_embedded_verbatim(self):
        html = wp.build_email_html(AI_HTML, {"end": END}, None)
        assert AI_HTML in html

    def test_the_masthead_and_edition_footer_are_present(self):
        html = wp.build_email_html(AI_HTML, {"end": END}, None)
        assert "The Weekly Plate" in html
        assert "Friday Edition" in html

    def test_the_medical_disclaimer_is_present(self):
        html = wp.build_email_html(AI_HTML, {"end": END}, None)
        assert "not medical advice" in html

    def test_the_edition_date_is_rendered_in_long_human_form(self):
        html = wp.build_email_html(AI_HTML, {"end": END}, None)
        assert "June 5, 2026" in html

    def test_an_unparseable_window_end_falls_back_to_the_raw_string(self):
        html = wp.build_email_html(AI_HTML, {"end": "unknown"}, None)
        assert "unknown" in html

    def test_the_current_weight_and_weekly_loss_are_shown_to_the_reader(self):
        html = wp.build_email_html(AI_HTML, {"end": END}, {"latest_weight_lbs": 304.2, "change_7d_lbs": -1.8})
        assert "304.2 lbs" in html
        assert "↓ 1.8 this week" in html

    def test_a_weekly_gain_is_shown_with_an_up_arrow_not_hidden(self):
        html = wp.build_email_html(AI_HTML, {"end": END}, {"latest_weight_lbs": 306.0, "change_7d_lbs": 1.8})
        assert "↑ 1.8 this week" in html

    def test_a_flat_week_is_shown_as_flat(self):
        html = wp.build_email_html(AI_HTML, {"end": END}, {"latest_weight_lbs": 306.0, "change_7d_lbs": 0.0})
        assert "→ 0.0 this week" in html

    def test_a_weight_with_no_weekly_comparison_shows_the_weight_and_no_claim(self):
        # Neutral body so the assertion can only be about the chrome the module renders.
        html = wp.build_email_html("<p>BODY</p>", {"end": END}, {"latest_weight_lbs": 304.2, "change_7d_lbs": None})
        assert "304.2 lbs" in html
        assert "this week" not in html

    def test_with_no_weigh_in_at_all_no_weight_line_is_rendered(self):
        """ADR-104: absence must not render as '0.0 lbs · → 0.0 this week'."""
        html = wp.build_email_html("<p>BODY</p>", {"end": END}, None)
        assert " lbs" not in html
        assert "this week" not in html


# ══════════════════════════════════════════════════════════════════════════════
# Send bookkeeping
# ══════════════════════════════════════════════════════════════════════════════


class TestRecordEmailSend:
    def test_a_successful_send_is_recorded_for_the_status_page(self, table):
        wp.record_email_send(table, "weekly_plate", "week:2026-W34")
        item = table.puts[0]
        assert item["pk"] == "USER#matthew#SOURCE#email_log#weekly_plate"
        assert item["sk"] == f"DATE#{TODAY}"
        assert item["status"] == "success"

    def test_the_record_expires_after_about_ninety_days(self, table):
        """90 days after the row's OWN `sent_at` — #3113 put the ttl and the
        date on the same clock (the ttl used to read `time.time()` while the
        date read `datetime.now()`, which a frozen-datetime fixture split)."""
        wp.record_email_send(table, "weekly_plate", "week:2026-W34")
        row = table.puts[0]
        assert row["ttl"] == int(datetime.fromisoformat(row["sent_at"]).timestamp()) + 90 * 86400

    def test_a_failed_bookkeeping_write_is_non_fatal(self, table):
        table.put_error = RuntimeError("throttled")
        wp.record_email_send(table, "weekly_plate", "week:2026-W34")  # must not raise


# ══════════════════════════════════════════════════════════════════════════════
# The handler
# ══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def wired(monkeypatch, table, ses):
    """A fully-stubbed happy path: profile + 3 food days + 3 weigh-ins, a
    canned AI response, and a fake insight writer. No real client remains."""
    rows = [
        profile_row(calorie_target=1800, protein_target_g=190, goal_weight_lbs=185, journey_start_weight_lbs=Decimal("321.6")),
        mf_row("2026-06-03", [food("Eggs", cal=180, protein=Decimal("12"))], total_calories_kcal=Decimal("1790")),
        mf_row("2026-06-04", [food("Ground Turkey 93/7", cal=320, protein=44)], total_calories_kcal=Decimal("1810")),
        mf_row(END, [food("Salmon", cal=300, protein=34)], total_calories_kcal=Decimal("1750")),
        wi_row("2026-05-08", weight_lbs=Decimal("310.0")),
        wi_row("2026-06-01", weight_lbs=Decimal("306.0")),
        wi_row("2026-06-04", weight_lbs=Decimal("304.2")),
    ]
    for row in rows:
        table.items[(row["pk"], row["sk"])] = row

    calls = []

    def fake_call(system_prompt, user_message):
        calls.append({"system": system_prompt, "user": user_message})
        return AI_HTML

    monkeypatch.setattr(wp, "call_anthropic", fake_call)

    writer = FakeInsightWriter()
    monkeypatch.setattr(wp, "insight_writer", writer)
    monkeypatch.setattr(wp, "_HAS_INSIGHT_WRITER", True)

    return {"table": table, "ses": ses, "calls": calls, "writer": writer}


class TestHandlerGuards:
    def test_no_profile_means_no_email_and_a_failure_status(self, table, ses, monkeypatch):
        monkeypatch.setattr(wp, "call_anthropic", lambda s, u: AI_HTML)
        result = wp.lambda_handler({}, None)
        assert result["statusCode"] == 500
        assert ses.sent == []

    def test_no_food_records_in_the_window_means_no_email(self, table, ses, monkeypatch):
        table.items[("USER#matthew", "PROFILE#v1")] = profile_row()
        monkeypatch.setattr(wp, "call_anthropic", lambda s, u: AI_HTML)
        result = wp.lambda_handler({}, None)
        assert result["statusCode"] == 500
        assert result["body"] == "No food data"
        assert ses.sent == []

    def test_the_ai_is_never_called_when_there_is_no_data_to_summarise(self, table, ses, monkeypatch):
        """Bedrock spend must not be incurred on a run that cannot ship."""
        called = []
        monkeypatch.setattr(wp, "call_anthropic", lambda s, u: called.append(1) or AI_HTML)
        wp.lambda_handler({}, None)
        assert called == []

    def test_a_window_of_days_with_no_logged_foods_does_not_ship_an_invented_plate(self, table, ses, monkeypatch):
        """ADR-104 (#2558, was xfail): the gate counts FOOD ITEMS, not day records."""
        table.items[("USER#matthew", "PROFILE#v1")] = profile_row()
        for i in range(14):
            d = (datetime.strptime(END, "%Y-%m-%d") - timedelta(days=i)).strftime("%Y-%m-%d")
            row = mf_row(d, [], total_calories_kcal=Decimal("0"))
            table.items[(row["pk"], row["sk"])] = row
        called = []
        monkeypatch.setattr(wp, "call_anthropic", lambda s, u: called.append(1) or AI_HTML)
        wp.lambda_handler({}, None)
        assert ses.sent == []
        # ...and the fabrication never even got commissioned.
        assert called == []


class TestHandlerHappyPath:
    def test_exactly_one_email_is_sent_to_the_configured_recipient(self, wired):
        wp.lambda_handler({}, None)
        assert len(wired["ses"].sent) == 1
        sent = wired["ses"].sent[0]
        assert sent["Destination"]["ToAddresses"] == [wp.RECIPIENT]
        assert sent["FromEmailAddress"] == wp.SENDER

    def test_the_subject_names_the_edition_and_its_window_end(self, wired):
        wp.lambda_handler({}, None)
        subject = wired["ses"].sent[0]["Content"]["Simple"]["Subject"]["Data"]
        assert "The Weekly Plate" in subject
        assert "Jun 5" in subject

    def test_the_body_carries_the_ai_writing_the_reader_is_here_for(self, wired):
        wp.lambda_handler({}, None)
        html = wired["ses"].sent[0]["Content"]["Simple"]["Body"]["Html"]["Data"]
        assert "Smoky Turkey Kofte Bowls" in html

    def test_the_body_carries_the_readers_current_weight(self, wired):
        wp.lambda_handler({}, None)
        html = wired["ses"].sent[0]["Content"]["Simple"]["Body"]["Html"]["Data"]
        assert "304.2 lbs" in html

    def test_a_successful_run_reports_success(self, wired):
        assert wp.lambda_handler({}, None)["statusCode"] == 200

    def test_the_prompt_carries_the_foods_the_email_will_talk_about(self, wired):
        wp.lambda_handler({}, None)
        user_msg = wired["calls"][0]["user"]
        assert "Ground Turkey 93/7" in user_msg
        assert "Salmon" in user_msg

    def test_the_prompt_carries_the_weight_context_it_is_told_to_weave_in(self, wired):
        wp.lambda_handler({}, None)
        assert "Currently 304.2 lbs" in wired["calls"][0]["system"]

    def test_previous_editions_are_prepended_to_the_prompt_as_anti_repeat_context(self, wired):
        row = memory_row("2026-05-29", plate_date="2026-05-29", wildcard="Miso paste", recipes=["Turkey Kofte Bowls"])
        wired["table"].items[(row["pk"], row["sk"])] = row
        wp.lambda_handler({}, None)
        user_msg = wired["calls"][0]["user"]
        assert "PREVIOUS WEEKLY PLATE EDITIONS" in user_msg
        assert "Miso paste" in user_msg
        assert user_msg.index("PREVIOUS WEEKLY PLATE EDITIONS") < user_msg.index("food_log_14_days")

    def test_with_no_stored_history_no_anti_repeat_block_is_prepended(self, wired):
        wp.lambda_handler({}, None)
        assert "PREVIOUS WEEKLY PLATE EDITIONS" not in wired["calls"][0]["user"]

    def test_recent_nutrition_insights_are_prepended_when_available(self, wired, monkeypatch):
        wired["writer"].context = "RECENT NUTRITION INSIGHTS (context for meal planning):\n  - protein timing"
        wp.lambda_handler({}, None)
        assert "RECENT NUTRITION INSIGHTS" in wired["calls"][0]["user"]

    def test_a_failing_insights_context_lookup_does_not_stop_the_email(self, wired):
        wired["writer"].context_error = RuntimeError("ddb down")
        assert wp.lambda_handler({}, None)["statusCode"] == 200
        assert len(wired["ses"].sent) == 1

    def test_this_editions_wildcard_and_recipes_are_stored_for_next_week(self, wired):
        wp.lambda_handler({}, None)
        stored = [p for p in wired["table"].puts if p["pk"] == wp.USER_PREFIX_MEMORY]
        assert len(stored) == 1
        assert stored[0]["wildcard"].startswith("Miso paste")
        assert "Smoky Turkey Kofte Bowls" in stored[0]["recipes"]

    def test_the_stored_summary_records_the_actual_top_foods_of_the_window(self, wired):
        wp.lambda_handler({}, None)
        stored = [p for p in wired["table"].puts if p["pk"] == wp.USER_PREFIX_MEMORY][0]
        assert set(stored["top_foods"]) == {"eggs", "ground turkey 93/7", "salmon"}

    def test_a_failed_summary_store_does_not_stop_the_email(self, wired, monkeypatch):
        monkeypatch.setattr(wp, "store_plate_summary", lambda s, t: (_ for _ in ()).throw(RuntimeError("boom")))
        assert wp.lambda_handler({}, None)["statusCode"] == 200
        assert len(wired["ses"].sent) == 1

    def test_the_send_is_recorded_for_the_status_page(self, wired):
        wp.lambda_handler({}, None)
        logged = [p for p in wired["table"].puts if p["pk"].startswith("USER#matthew#SOURCE#email_log#")]
        assert logged and logged[0]["sk"] == f"DATE#{TODAY}"

    def test_the_edition_is_filed_as_a_nutrition_insight(self, wired):
        wp.lambda_handler({}, None)
        assert len(wired["writer"].written) == 1
        ins = wired["writer"].written[0]
        assert ins["digest_type"] == "weekly_plate"
        assert ins["pillars"] == ["nutrition"]
        assert ins["date"] == END

    def test_a_failed_insight_write_does_not_fail_the_run(self, wired, monkeypatch):
        def boom(**kwargs):
            raise RuntimeError("ddb down")

        monkeypatch.setattr(wired["writer"], "write_insight", boom)
        assert wp.lambda_handler({}, None)["statusCode"] == 200


class TestHandlerAiDegradation:
    def test_a_failed_ai_call_still_ships_an_email(self, wired, monkeypatch):
        monkeypatch.setattr(wp, "call_anthropic", lambda s, u: (_ for _ in ()).throw(RuntimeError("bedrock 500")))
        assert wp.lambda_handler({}, None)["statusCode"] == 200
        assert len(wired["ses"].sent) == 1

    def test_a_failed_ai_call_tells_the_reader_the_writing_is_missing(self, wired, monkeypatch):
        """Honest degradation: the reader must be able to tell this week's copy
        never got written, not read a canned paragraph as if it were fresh."""
        monkeypatch.setattr(wp, "call_anthropic", lambda s, u: (_ for _ in ()).throw(RuntimeError("bedrock 500")))
        wp.lambda_handler({}, None)
        html = wired["ses"].sent[0]["Content"]["Simple"]["Body"]["Html"]["Data"]
        assert "unavailable" in html

    def test_a_failed_ai_call_does_not_fabricate_recipes_or_a_wildcard_for_next_week(self, wired, monkeypatch):
        monkeypatch.setattr(wp, "call_anthropic", lambda s, u: (_ for _ in ()).throw(RuntimeError("bedrock 500")))
        wp.lambda_handler({}, None)
        stored = [p for p in wired["table"].puts if p["pk"] == wp.USER_PREFIX_MEMORY][0]
        assert "wildcard" not in stored
        assert "recipes" not in stored

    def test_a_blocked_ai_output_is_replaced_by_the_validators_safe_fallback(self, wired, monkeypatch):
        class Blocked:
            blocked = True
            block_reason = "Dangerously low calorie recommendation"
            safe_fallback = "Nutrition data received. Aim for your protein target."
            warnings = []

        monkeypatch.setattr(wp, "validate_ai_output", lambda text, kind: Blocked())
        monkeypatch.setattr(wp, "_HAS_AI_VALIDATOR", True)
        wp.lambda_handler({}, None)
        html = wired["ses"].sent[0]["Content"]["Simple"]["Body"]["Html"]["Data"]
        assert "Nutrition data received" in html
        assert "Smoky Turkey Kofte Bowls" not in html

    def test_a_blocked_output_with_no_fallback_still_degrades_to_an_honest_notice(self, wired, monkeypatch):
        class Blocked:
            blocked = True
            block_reason = "empty"
            safe_fallback = ""
            warnings = []

        monkeypatch.setattr(wp, "validate_ai_output", lambda text, kind: Blocked())
        monkeypatch.setattr(wp, "_HAS_AI_VALIDATOR", True)
        wp.lambda_handler({}, None)
        html = wired["ses"].sent[0]["Content"]["Simple"]["Body"]["Html"]["Data"]
        assert "unavailable" in html

    def test_validator_warnings_do_not_suppress_the_ai_writing(self, wired, monkeypatch):
        class Warned:
            blocked = False
            block_reason = ""
            safe_fallback = ""
            warnings = ["Generic coaching phrases detected"]

        monkeypatch.setattr(wp, "validate_ai_output", lambda text, kind: Warned())
        monkeypatch.setattr(wp, "_HAS_AI_VALIDATOR", True)
        wp.lambda_handler({}, None)
        html = wired["ses"].sent[0]["Content"]["Simple"]["Body"]["Html"]["Data"]
        assert "Smoky Turkey Kofte Bowls" in html

    def test_a_per_serving_recipe_macro_does_not_get_the_whole_edition_blocked(self, wired, monkeypatch):
        """FIXED (#2215): weekly_plate validates its output as AIOutputType.NUTRITION_COACH,
        whose Check-5 blocked ANY three-digit calorie figure 100-799 followed by
        cal/kcal/calories — while this module's own SYSTEM_PROMPT *requires* every 'Try This'
        recipe card to carry 'Approximate macros per serving (cal/P/C/F)'. Every
        prompt-compliant edition was therefore replaced wholesale by the validator's one-line
        fallback. The check now distinguishes a per-item macro label from a daily intake
        prescription (ai_output_validator._is_per_item_calorie_figure). Runs the real
        validator — no stub."""
        monkeypatch.setattr(wp, "call_anthropic", lambda s, u: AI_HTML_WITH_PER_SERVING_MACROS)
        wp.lambda_handler({}, None)
        html = wired["ses"].sent[0]["Content"]["Simple"]["Body"]["Html"]["Data"]
        assert "Smoky Turkey Kofte Bowls" in html
        assert "Calorie guidance review needed" not in html

    def test_an_edition_without_per_serving_calorie_figures_survives_validation(self, wired):
        """Control for the defect above: the same edition, macros omitted, ships intact."""
        wp.lambda_handler({}, None)
        html = wired["ses"].sent[0]["Content"]["Simple"]["Body"]["Html"]["Data"]
        assert "Smoky Turkey Kofte Bowls" in html

    def test_a_failed_ai_call_is_not_filed_as_a_genuine_coaching_insight(self, wired, monkeypatch):
        """FIXED (#2221): the guard `'unavailable' not in ai_content[:50]` could never fire
        on this module's OWN failure stub — the stub opens with a 78-char inline-styled
        <div>, so the word sits at index ~89, outside the 50-char probe. Every AI failure
        therefore filed the stub as a genuine `coaching` insight (confidence=medium,
        actionable=True, pillars=[nutrition]), which build_insights_context replayed into
        later meal-planning prompts. Replaced by an `ai_written` flag set at the failure."""
        monkeypatch.setattr(wp, "call_anthropic", lambda s, u: (_ for _ in ()).throw(RuntimeError("bedrock 500")))
        wp.lambda_handler({}, None)
        assert wired["writer"].written == []

    def test_the_failure_stub_is_not_run_through_the_ai_output_validator(self, wired, monkeypatch):
        """The same broken probe was also what skipped AI-3 for the stub — the stub is
        this module's own text, not model output, so validating it is meaningless work."""
        seen = []
        monkeypatch.setattr(wp, "call_anthropic", lambda s, u: (_ for _ in ()).throw(RuntimeError("bedrock 500")))
        monkeypatch.setattr(wp, "validate_ai_output", lambda text, kind: seen.append(text))
        monkeypatch.setattr(wp, "_HAS_AI_VALIDATOR", True)
        wp.lambda_handler({}, None)
        assert seen == []

    def test_a_validator_blocked_edition_is_not_filed_as_a_genuine_coaching_insight(self, wired, monkeypatch):
        """Same class as the stub: the fallback notice is a degradation message, not
        coaching, and must not be replayed into next week's prompt as one."""

        class Blocked:
            blocked = True
            block_reason = "Dangerously low calorie recommendation"
            safe_fallback = "Nutrition data received. Aim for your protein target."
            warnings = []

        monkeypatch.setattr(wp, "validate_ai_output", lambda text, kind: Blocked())
        monkeypatch.setattr(wp, "_HAS_AI_VALIDATOR", True)
        wp.lambda_handler({}, None)
        assert wired["writer"].written == []


class TestHandlerDryRun:
    def test_a_dry_run_invoke_does_not_send_a_real_email(self, wired):
        """FIXED by #2222 — this handler now honours a dry-run suppressor.

        It was an `xfail` describing a real defect: the handler ignored `event`
        entirely, so there was no safe way to exercise it and every verification
        invoke mailed Matthew and burned a Sonnet call. #2222 put all 17 SES-sending
        handlers behind one derived guard, which made this marker stale — it xpassed,
        i.e. it was still asserting a defect that no longer exists. Flipped to a real
        assertion so it now protects the fix instead of describing the bug."""
        wp.lambda_handler({"dry_run": True}, None)
        assert wired["ses"].sent == []
