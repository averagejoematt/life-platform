"""tests/test_mcp_tools_nutrition_behavior.py — behavioral contracts for the
owner-facing nutrition tools in ``mcp/tools_nutrition.py``:

    get_nutrition               (summary | macros | meal_timing | micronutrients)
    get_deficit_sustainability  (the 5-channel cut early-warning)
    _get_metabolic_adaptation   (TDEE-divergence tracker, reached through get_benchmark)

These answer "how is my nutrition?", "am I cutting too hard?" and "has my
metabolism adapted?" inside Claude Desktop — and their output is read as fact.
The ``mcp/tools_*`` family had zero dedicated behavioral coverage before this
file. What is pinned here:

  * ADR-104 honest numbers — a nutrient that was never logged has NO average.
    ``totals_sum.get(f, 0) / max(totals_count.get(f, 1), 1)`` turns an absence
    into a factual 0.0 and then into dietary advice, which is the single most
    reader-visible defect class in this module.
  * ADR-105 rigor — an average or a "chronic deficiency" verdict ships with the
    n behind it, and a "trend" is not computed from windows that overlap.
  * Reader/writer field agreement — every DynamoDB field these tools read is
    checked against a writer that produces it. Where the writer's transform is
    pure (``ingestion.strava_lambda.transform``) the produced field set is
    DERIVED by calling it; where it is not, the writer module's source is
    inspected. Two whole channels of the 5-channel deficit tracker turn out to
    read fields nothing writes.
  * Internal consistency — one tool must not answer the same question two ways.
    ``view=summary`` and ``view=macros`` publish different calorie and fiber
    targets for the same day.
  * #1917 window-name honesty and ADR-058 phase filtering.
  * Privacy — food delivery / binge frequency is NUTRITION_DELIVERY_PUBLIC-gated
    elsewhere in the serving path, and genome/labs are Tier-2/CROSS_PHASE; a
    nutrition answer has no business reaching any of them.

Everything runs against a hand-rolled bounded DynamoDB double patched onto
``mcp.core.table``, so the REAL ``query_source`` / ``parallel_query_sources``
execute — phase filter, ``sk BETWEEN`` window, pagination and thread fan-out all
included. No MagicMock near a pagination loop, no AWS, no network. Both clocks
the module observes are frozen: ``tools_nutrition.datetime`` via a ``datetime``
subclass, and ``pacific_today`` (which anchors every default range) via a stub.

Every arithmetic expectation is hand-derived in a comment beside the literal.
"""

from __future__ import annotations

import copy
import inspect
import os
import threading
from datetime import datetime, timedelta, timezone

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")  # mcp.config reads these at import
os.environ.setdefault("USER_ID", "matthew")

import pytest  # noqa: E402
from pacific_clock import freeze_pacific  # #2817: the Pacific clock a converted module actually reads

from mcp import core as mcore, tools_nutrition as tn  # noqa: E402
from mcp.registry import TOOLS  # noqa: E402

# ──────────────────────────────────────────────────────────────────────────────
# Frozen clocks
# ──────────────────────────────────────────────────────────────────────────────

NOW = datetime(2026, 5, 10, 17, 40, 0, tzinfo=timezone.utc)  # 10:40 PT — same PT/UTC calendar day
PT_TODAY = "2026-05-10"
THROUGH = "2026-05-09"  # _nutrition_through_date(): the latest COMPLETE MacroFactor day
_FROZEN = [NOW]
_PT = [PT_TODAY]


class _FrozenDatetime(datetime):
    """``datetime`` with a pinned ``now()`` — a subclass so ``strptime``,
    ``strftime('%G-W%V')`` and ``timedelta`` arithmetic keep working on the same
    name the module under test uses."""

    @classmethod
    def now(cls, tz=None):
        return _FROZEN[0].astimezone(tz) if tz is not None else _FROZEN[0].replace(tzinfo=None)

    @classmethod
    def utcnow(cls):
        return _FROZEN[0].replace(tzinfo=None)


def d(date_str: str, days: int) -> str:
    """Fixture-date arithmetic — never combined with a live clock."""
    return (datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=days)).strftime("%Y-%m-%d")


def span_days(start: str, end: str) -> int:
    """Inclusive date count of a ``sk BETWEEN DATE#start .. DATE#end~`` window."""
    return (datetime.strptime(end, "%Y-%m-%d") - datetime.strptime(start, "%Y-%m-%d")).days + 1


# ──────────────────────────────────────────────────────────────────────────────
# Bounded, hand-rolled DynamoDB double
# ──────────────────────────────────────────────────────────────────────────────


def _flatten(cond, out):
    """Walk a boto3 ``KeyConditionExpression`` tree into (operator, values) pairs
    so the fake honours the tool's REAL key expression rather than flattering it."""
    expr = cond.get_expression()
    if expr["operator"] == "AND":
        for sub in expr["values"]:
            _flatten(sub, out)
    else:
        out.append((expr["operator"], [getattr(v, "name", v) for v in expr["values"]]))
    return out


class FakeTable:
    """In-memory stand-in for the boto3 ``Table`` held by ``mcp.core``.

    Honours ``pk =`` / ``sk BETWEEN`` from the real condition tree, the ADR-058
    phase ``FilterExpression`` (reading the wanted value out of the caller's own
    ``ExpressionAttributeValues``, so it cannot drift from ``core``), and — with
    ``page_size`` — real ``LastEvaluatedKey`` pagination driven by a BOUNDED
    generator rather than a Mock. ``parallel_query_sources`` fans out over
    threads, so the call log is lock-guarded.
    """

    def __init__(self, rows=None, profile=None, page_size=None, raise_sources=frozenset()):
        self.rows = [copy.deepcopy(r) for r in (rows or [])]
        self.profile = copy.deepcopy(profile) if profile is not None else None
        self.queries: list[tuple[str, str, str]] = []
        self.page_count = 0
        self.page_size = page_size
        self.raise_sources = set(raise_sources)
        self._lock = threading.Lock()

    def get_item(self, Key=None, **kwargs):
        key = Key if Key is not None else kwargs.get("Key", {})
        if self.profile is not None and key.get("sk") == "PROFILE#v1":
            return {"Item": copy.deepcopy(self.profile)}
        return {}

    def query(self, **kwargs):
        parts = dict((op, vals) for op, vals in _flatten(kwargs["KeyConditionExpression"], []))
        pk = parts["="][1]
        lo = parts["BETWEEN"][1].replace("DATE#", "")
        hi = parts["BETWEEN"][2].replace("DATE#", "").rstrip("~")
        source = pk.split("#SOURCE#")[-1]
        if kwargs.get("ExclusiveStartKey") is None:
            with self._lock:
                self.queries.append((source, lo, hi))
        if source in self.raise_sources:
            raise RuntimeError(f"simulated DynamoDB failure reading {source}")

        matched = sorted(
            (r for r in self.rows if r.get("pk") == pk and lo <= str(r.get("sk", "")).replace("DATE#", "") <= hi),
            key=lambda r: r.get("sk", ""),
        )
        fexpr = kwargs.get("FilterExpression") or ""
        if "attribute_not_exists(#phase)" in fexpr:
            want = kwargs["ExpressionAttributeValues"][":phase_experiment"]
            matched = [r for r in matched if r.get("phase") is None or r.get("phase") == want]

        start = 0
        if kwargs.get("ExclusiveStartKey"):
            last = kwargs["ExclusiveStartKey"]["sk"]
            start = next((i for i, r in enumerate(matched) if r.get("sk") == last), -1) + 1
        page = matched[start:] if self.page_size is None else matched[start : start + self.page_size]
        with self._lock:
            self.page_count += 1
        out: dict = {"Items": [copy.deepcopy(r) for r in page]}
        if self.page_size is not None and page and (start + len(page)) < len(matched):
            out["LastEvaluatedKey"] = {"pk": pk, "sk": page[-1]["sk"]}
        return out

    def window_for(self, source: str) -> tuple[str, str]:
        for s, lo, hi in self.queries:
            if s == source:
                return lo, hi
        raise AssertionError(f"{source!r} was never queried; queries={self.queries}")

    @property
    def sources_read(self) -> set[str]:
        return {q[0] for q in self.queries}


# ──────────────────────────────────────────────────────────────────────────────
# Row builders — keyed exactly the way the real partitions are keyed
# ──────────────────────────────────────────────────────────────────────────────

PK = "USER#matthew#SOURCE#"


def row(source: str, date: str, **fields) -> dict:
    return {"pk": PK + source, "sk": f"DATE#{date}", "date": date, **fields}


def mf(date: str, **fields) -> dict:
    """A MacroFactor day. ``ingestion/macrofactor_lambda.py`` prefixes every
    nutrient rollup with ``total_`` and drops zero totals entirely."""
    return row("macrofactor", date, **fields)


def meal(time: str, calories_kcal: float, **extra) -> dict:
    """A `food_log` entry the way ``macrofactor_lambda.parse_entry`` builds one."""
    return {"food_name": "Something", "time": time, "calories_kcal": calories_kcal, **extra}


def whoop(date: str, **fields) -> dict:
    return row("whoop", date, **fields)


def habitify(date: str, **fields) -> dict:
    return row("habitify", date, **fields)


def strava(date: str, **fields) -> dict:
    return row("strava", date, **fields)


def withings(date: str, **fields) -> dict:
    return row("withings", date, **fields)


def eightsleep(date: str, **fields) -> dict:
    return row("eightsleep", date, **fields)


PROFILE = {"pk": "USER#matthew", "sk": "PROFILE#v1", "tdee_estimate": 2500}
#: ADR-152 (#2310): the TDEE estimate needs a profile HEIGHT — Mifflin is 6.25 kcal per
#: cm — so a profile without one yields no estimate at all rather than a guess.
PROFILE_WITH_HEIGHT = {"pk": "USER#matthew", "sk": "PROFILE#v1", "height_inches": 72}


# ──────────────────────────────────────────────────────────────────────────────
# Harness
# ──────────────────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _frozen_and_isolated(monkeypatch):
    """Freeze BOTH clocks the module reads and clear ``core``'s process-level
    profile cache.

    ``tools_nutrition`` mixes two time frames: ``datetime.now(timezone.utc)`` for
    every default ``start_date`` and ``pacific_today()`` for every default
    ``end_date``. Pinning only one would hide the frame mismatch that §1 asserts.
    ``mcp.core._PROFILE_CACHE`` is a module global that would otherwise leak the
    first test's profile into every later one.
    """
    _FROZEN[0] = NOW
    _PT[0] = PT_TODAY
    monkeypatch.setattr(tn, "datetime", _FrozenDatetime)
    freeze_pacific(monkeypatch, tn, _FrozenDatetime)  # #2817: pin the PACIFIC helpers this module now calls
    monkeypatch.setattr(tn, "pacific_today", lambda: _PT[0])
    monkeypatch.setattr(mcore, "_PROFILE_CACHE", None, raising=False)
    yield
    mcore._PROFILE_CACHE = None
    _FROZEN[0] = NOW
    _PT[0] = PT_TODAY


def install(monkeypatch, rows=None, profile=PROFILE, page_size=None, raise_sources=frozenset()) -> FakeTable:
    t = FakeTable(rows=rows, profile=profile, page_size=page_size, raise_sources=raise_sources)
    monkeypatch.setattr(mcore, "table", t)
    return t


# ──────────────────────────────────────────────────────────────────────────────
# 0. The tool SET + the view SET, derived from the registry
# ──────────────────────────────────────────────────────────────────────────────

MODULE_TOOLS = {name: spec for name, spec in TOOLS.items() if getattr(spec["fn"], "__module__", "") == tn.__name__}
EXERCISED = {"get_nutrition", "get_deficit_sustainability"}


def test_the_registry_still_wires_tools_out_of_this_module():
    assert MODULE_TOOLS, "mcp/registry.py no longer registers any mcp.tools_nutrition function"


def test_every_registered_tools_nutrition_tool_is_exercised_by_this_file():
    assert set(MODULE_TOOLS) == EXERCISED, f"undriven tools_nutrition tools: {sorted(set(MODULE_TOOLS) - EXERCISED)}"


@pytest.mark.parametrize("name", sorted(EXERCISED))
def test_no_tool_declares_a_required_argument(name):
    assert MODULE_TOOLS[name]["schema"]["inputSchema"]["required"] == []


VIEWS = MODULE_TOOLS["get_nutrition"]["schema"]["inputSchema"]["properties"]["view"]["enum"]


def test_get_nutrition_routes_every_view_the_registry_declares(monkeypatch):
    """Derived-SET guard: the schema `view` enum and the dispatcher's VALID_VIEWS
    must not drift. A declared-but-unrouted view would answer 'Unknown view' to a
    schema-conformant client."""
    install(monkeypatch, [])
    for view in VIEWS:
        out = tn.tool_get_nutrition({"view": view})
        assert "Unknown view" not in str(out.get("error", "")), view


def test_get_nutrition_rejects_an_unknown_view_with_the_declared_alternatives(monkeypatch):
    install(monkeypatch, [])
    out = tn.tool_get_nutrition({"view": "calories"})
    assert "Unknown view" in out["error"]
    assert set(out["valid_views"]) == set(VIEWS)


def test_metabolic_adaptation_is_reachable_from_a_registered_tool():
    """`_get_metabolic_adaptation` is private to this module but is driven by the
    registered `get_benchmark` tool, so it is live code, not a dead helper."""
    from mcp import tools_benchmark

    assert "_get_metabolic_adaptation" in inspect.getsource(tools_benchmark)


# ──────────────────────────────────────────────────────────────────────────────
# 1. Default ranges — MacroFactor is ~24h behind BY DESIGN
# ──────────────────────────────────────────────────────────────────────────────


def test_the_default_end_date_is_the_latest_complete_pacific_day(monkeypatch):
    """MacroFactor is a manual end-of-day upload, so "today" does not exist yet.
    Anchoring the default end to PT-yesterday is what stops Claude reading an
    absent today as "0 calories logged" — a pipeline property mis-framed as a
    user failure."""
    t = install(monkeypatch, [])
    tn.tool_get_nutrition({"view": "summary"})
    assert t.window_for("macrofactor")[1] == THROUGH


def test_the_default_end_date_follows_the_pacific_calendar_not_utc(monkeypatch):
    """AUDIT BUG-03: in the UTC-evening window the UTC date has already rolled
    over while the Pacific day has not. The end must track Pacific."""
    _FROZEN[0] = datetime(2026, 5, 11, 3, 0, 0, tzinfo=timezone.utc)  # 2026-05-10 20:00 PT
    _PT[0] = "2026-05-10"
    t = install(monkeypatch, [])
    tn.tool_get_nutrition({"view": "summary"})
    assert t.window_for("macrofactor")[1] == "2026-05-09"


@pytest.mark.parametrize("utc_now", [NOW, datetime(2026, 5, 11, 3, 0, 0, tzinfo=timezone.utc)])
@pytest.mark.parametrize("view", ["summary", "micronutrients", "meal_timing", "macros"])
def test_the_default_window_really_spans_thirty_days(monkeypatch, utc_now, view):
    """#1917 + frame mixing: the default `end_date` is `_nutrition_through_date()` — a
    PACIFIC-anchored yesterday — while the default `start_date` used to be
    `datetime.now(timezone.utc) - 29 days`. Two calendar frames defining one window made its
    LENGTH depend on where the clock sat relative to the UTC/PT boundary, while the registry
    documents `start_date` as 'default: 30 days ago'. `_nutrition_default_range` derives the
    start from the RESOLVED end, so the span is 30 inclusive dates at every hour — asserted
    across all four views, not just the one that happened to be measured."""
    _FROZEN[0] = utc_now
    _PT[0] = "2026-05-10"
    t = install(monkeypatch, [])
    tn.tool_get_nutrition({"view": view})
    lo, hi = t.window_for("macrofactor")
    assert span_days(lo, hi) == 30
    assert hi == "2026-05-09"  # still Pacific-anchored, both frames agree


# ──────────────────────────────────────────────────────────────────────────────
# 2. view=micronutrients — RDA scoring and the longevity commentary
# ──────────────────────────────────────────────────────────────────────────────

MICRO_ARGS = {"view": "micronutrients", "start_date": "2026-05-01", "end_date": "2026-05-03"}
UL_FIELDS = {f for f, m in tn._MICRONUTRIENT_TARGETS.items() if m.get("upper_limit")}


def micro_rows(**field_values) -> list[dict]:
    """Three identical MacroFactor days carrying only the named nutrients."""
    return [mf(f"2026-05-0{i}", **field_values) for i in (1, 2, 3)]


def test_micronutrients_scores_a_nutrient_against_rda_and_optimal_with_its_n(monkeypatch):
    """fiber 20 / 30 / 40 -> average 30.0
    pct_rda     = 30/38  * 100 = 78.947 -> 78.9  (60 <= x < 90 -> LOW)
    pct_optimal = 30/50  * 100 = 60.0
    """
    install(monkeypatch, [mf("2026-05-01", total_fiber_g=20), mf("2026-05-02", total_fiber_g=30), mf("2026-05-03", total_fiber_g=40)])
    out = tn.tool_get_nutrition(MICRO_ARGS)
    fiber = out["by_category"]["Macros"][0]
    assert fiber["field"] == "total_fiber_g"
    assert fiber["average"] == 30.0
    assert fiber["pct_rda"] == 78.9
    assert fiber["pct_optimal"] == 60.0
    assert fiber["status"] == "LOW"
    assert fiber["days_logged"] == 3
    assert out["period"]["days_with_data"] == 3
    assert out["summary"]["near_gaps"] == 1


def test_micronutrients_calls_a_sustained_shortfall_deficient(monkeypatch):
    """fiber 10 -> 10/38 * 100 = 26.3 -> below 60 -> DEFICIENT."""
    install(monkeypatch, micro_rows(total_fiber_g=10))
    out = tn.tool_get_nutrition(MICRO_ARGS)
    assert out["summary"]["deficiencies"] == 1
    assert out["deficiencies"][0]["pct_rda"] == 26.3


def test_micronutrients_flags_a_scored_nutrient_above_its_tolerable_upper_limit(monkeypatch):
    """iron 90 mg/day: rda 8 (pct 1125), upper limit 45 -> ABOVE_UPPER_LIMIT."""
    install(monkeypatch, micro_rows(total_iron_mg=90))
    out = tn.tool_get_nutrition(MICRO_ARGS)
    assert [e["field"] for e in out["exceedances"]] == ["total_iron_mg"]
    assert out["exceedances"][0]["upper_limit"] == 45


def test_micronutrients_reports_the_omega_ratio_and_its_inflammatory_flag(monkeypatch):
    """omega-6 12 g / omega-3 2 g = 6.0 : 1, above the 4:1 target -> HIGH."""
    install(monkeypatch, micro_rows(total_omega6_g=12, total_omega3_total_g=2))
    out = tn.tool_get_nutrition(MICRO_ARGS)
    assert out["summary"]["omega6_omega3_ratio"] == 6.0
    assert out["summary"]["omega6_omega3_status"] == "HIGH"
    assert any("Omega-6:Omega-3 ratio is 6.0:1" in f for f in out["longevity_flags"])


def test_micronutrients_errors_on_an_empty_range_and_echoes_the_window(monkeypatch):
    install(monkeypatch, [])
    out = tn.tool_get_nutrition(MICRO_ARGS)
    assert "error" in out
    assert out["start_date"] == "2026-05-01" and out["end_date"] == "2026-05-03"


def test_micronutrients_hides_a_pilot_phase_macrofactor_row(monkeypatch):
    """ADR-058 — query_source's phase filter runs on every partition, so a row
    tombstoned by a cycle reset cannot re-enter a current-cycle average."""
    rows = micro_rows(total_fiber_g=40)
    rows.append(mf("2026-05-02", total_fiber_g=0.5, phase="pilot"))
    install(monkeypatch, rows)
    out = tn.tool_get_nutrition(MICRO_ARGS)
    assert out["by_category"]["Macros"][0]["average"] == 40.0
    assert out["by_category"]["Macros"][0]["days_logged"] == 3


def test_micronutrients_makes_no_longevity_claim_about_a_nutrient_never_logged(monkeypatch):
    """ADR-104: the three longevity flags were computed as
    `totals_sum.get(f, 0) / max(totals_count.get(f, 1), 1)`, so a nutrient appearing in NO
    record averaged to a factual 0.0 — and every threshold is a `<`, so absence fired all
    three. On a range that only ever logged fiber the tool asserted 'DHA averages 0.0g/day',
    'Magnesium averages 0mg/day' and 'Vitamin D from food averages 0.0mcg/day', each with a
    supplement recommendation attached. Derived over the SET of flagged nutrients, so a
    fourth flag added with the same wiring mistake joins this assertion automatically."""
    install(monkeypatch, micro_rows(total_fiber_g=40))
    out = tn.tool_get_nutrition(MICRO_ARGS)
    assert out["longevity_flags"] == []
    # and the flags still fire when the nutrient IS logged and IS short
    install(monkeypatch, micro_rows(total_fiber_g=40, total_omega3_dha_g=0.1, total_magnesium_mg=100, total_vitamin_d_mcg=1))
    assert len(tn.tool_get_nutrition(MICRO_ARGS)["longevity_flags"]) == 3


def test_micronutrients_publishes_no_omega_ratio_when_omega_six_was_never_logged(monkeypatch):
    """ADR-104: with omega-6 never logged, `omega6` evaluated to 0.0 (sum default 0 over a
    count floored to 1) and the published ratio became 0.0:1 — a PERFECT anti-inflammatory
    score invented out of a missing column, sitting next to an `omega6_omega3_status` of
    'insufficient_data' (correct only because 0.0 happens to be falsy). Both sides must have
    readings before a ratio exists."""
    install(monkeypatch, micro_rows(total_omega3_total_g=2))
    out = tn.tool_get_nutrition(MICRO_ARGS)
    assert out["summary"]["omega6_omega3_ratio"] is None
    assert out["summary"]["omega6_omega3_status"] == "insufficient_data"
    # the mirror case — omega-3 absent — was already handled and must stay handled
    install(monkeypatch, micro_rows(total_omega6_g=12))
    assert tn.tool_get_nutrition(MICRO_ARGS)["summary"]["omega6_omega3_ratio"] is None


def test_every_nutrient_with_an_upper_limit_can_actually_flag_an_exceedance(monkeypatch):
    """Fixed by #2248: ABOVE_UPPER_LIMIT no longer nests under `if meta.get("score")`
    (or under `if rda`, which caffeine — rda: None — never even entered). This test
    DERIVES the set of upper-limit nutrients from _MICRONUTRIENT_TARGETS rather than
    hardcoding "sodium and caffeine", so a future nutrient with the same wiring
    mistake joins it automatically."""
    unflagged = []
    for field in sorted(UL_FIELDS):
        ul = tn._MICRONUTRIENT_TARGETS[field]["upper_limit"]
        install(monkeypatch, micro_rows(**{field: ul * 2}))
        out = tn.tool_get_nutrition(MICRO_ARGS)
        if field not in {e["field"] for e in out["exceedances"]}:
            unflagged.append(field)
    assert unflagged == []


def test_sodium_and_caffeine_are_the_score_less_upper_limit_nutrients(monkeypatch):
    """Pins the claim in #2248 itself: of the ~13 _MICRONUTRIENT_TARGETS entries
    carrying an `upper_limit`, exactly total_sodium_mg and total_caffeine_mg lack
    `score` — every other one (calcium, iron, zinc, selenium, copper, vitamin
    A/D/E, B3, B6, folate) has it. If a future entry adds an upper_limit without
    `score`, this test documents the new score-less set rather than staying silent."""
    score_less_ul_fields = {f for f in UL_FIELDS if not tn._MICRONUTRIENT_TARGETS[f].get("score")}
    assert score_less_ul_fields == {"total_sodium_mg", "total_caffeine_mg"}


def test_sodium_exceedance_is_not_also_reported_as_deficient_or_low(monkeypatch):
    """Acceptance criterion #2: fixing the exceedance gate must not pull sodium into
    the DEFICIENT/LOW branches it was (accidentally) shielded from before — those
    stay scoped to `score`, which sodium and caffeine still do not carry."""
    install(monkeypatch, micro_rows(total_sodium_mg=100))  # far below rda 1500 and ul 2300
    out = tn.tool_get_nutrition(MICRO_ARGS)
    assert out["summary"]["deficiencies"] == 0
    assert out["summary"]["near_gaps"] == 0
    sodium_row = next(r for r in out["by_category"]["Minerals"] if r["field"] == "total_sodium_mg")
    assert "status" not in sodium_row


def test_an_unlogged_upper_limit_nutrient_is_omitted_not_implied_adequate(monkeypatch):
    """ADR-104: caffeine never logged in the window must not surface at all — and in
    particular must never be reported as ABOVE_UPPER_LIMIT's implicit opposite,
    'within limits'. The absence gate (`totals_count[field] == 0: continue`) already
    covers this; this test pins that the #2248 fix didn't change that for the
    now-independent upper-limit branch."""
    install(monkeypatch, micro_rows(total_fiber_g=40))  # no caffeine field anywhere in range
    out = tn.tool_get_nutrition(MICRO_ARGS)
    other_fields = {r["field"] for r in out["by_category"].get("Other", [])}
    assert "total_caffeine_mg" not in other_fields
    assert "total_caffeine_mg" not in {e["field"] for e in out["exceedances"]}


def test_a_deficiency_entry_states_how_many_days_it_averaged(monkeypatch):
    """ADR-105: the per-category rows carried `days_logged` but the `deficiencies` /
    `near_gaps` / `exceedances` lists — the part a reader quotes, and the part the summary
    counts — dropped it. The docstring calls these 'chronic'; a single logged day produced
    one identical in shape to a thirty-day one. Asserted over all three quoted lists."""
    install(monkeypatch, [mf("2026-05-01", total_fiber_g=5)])
    out = tn.tool_get_nutrition(MICRO_ARGS)
    assert out["deficiencies"][0].get("days_logged") == 1
    install(monkeypatch, micro_rows(total_fiber_g=30, total_iron_mg=90))  # 78.9% RDA -> LOW; iron over its UL
    out = tn.tool_get_nutrition(MICRO_ARGS)
    assert out["near_gaps"][0].get("days_logged") == 3
    assert out["exceedances"][0].get("days_logged") == 3


# ──────────────────────────────────────────────────────────────────────────────
# 3. view=meal_timing — the eating window
# ──────────────────────────────────────────────────────────────────────────────

TIMING_ARGS = {"view": "meal_timing", "start_date": "2026-05-05", "end_date": "2026-05-06"}

TIMING_ROWS = [
    mf("2026-05-05", total_calories_kcal=2000, food_log=[meal("08:00", 400), meal("12:30", 700), meal("19:00", 900)]),
    mf("2026-05-06", total_calories_kcal=1500, food_log=[meal("09:00", 500), meal("21:00", 1000)]),
]


def test_meal_timing_reports_hand_derived_first_bite_last_bite_and_window(monkeypatch):
    """day 1: bites at 8.0 / 12.5 / 19.0 -> window 19.0 - 8.0 = 11.0 h
    day 2: bites at 9.0 / 21.0          -> window 21.0 - 9.0 = 12.0 h
    avg first bite  = (8.0 + 9.0)/2 =  8.5 -> 08:30
    avg last bite   = (19.0 + 21.0)/2 = 20.0 -> 20:00
    avg window      = (11.0 + 12.0)/2 = 11.5 -> BORDERLINE (10 < x <= 12)
    """
    install(monkeypatch, TIMING_ROWS)
    ew = tn.tool_get_nutrition(TIMING_ARGS)["eating_window"]
    assert ew["avg_first_bite"] == "08:30"
    assert ew["avg_last_bite"] == "20:00"
    assert ew["avg_window_hrs"] == 11.5
    assert ew["trf_status"] == "BORDERLINE"


def test_meal_timing_reports_circadian_consistency_as_a_sample_standard_deviation(monkeypatch):
    """first bites [8.0, 9.0] -> sd = sqrt(0.5/1) = 0.7071 -> 0.71
    last  bites [19.0, 21.0] -> sd = sqrt(2.0/1) = 1.4142 -> 1.41"""
    install(monkeypatch, TIMING_ROWS)
    ew = tn.tool_get_nutrition(TIMING_ARGS)["eating_window"]
    assert ew["first_bite_consistency_sd_hrs"] == 0.71
    assert ew["last_bite_consistency_sd_hrs"] == 1.41


def test_meal_timing_distributes_calories_across_the_day_and_flags_late_eating(monkeypatch):
    """day 1 (total 2000): morning 400 -> 20.0%, midday 700 -> 35.0%, evening 900 -> 45.0%
    day 2 (total 1500): morning 500 -> 33.3%, late 1000 -> 66.7%; last bite 21:00 >= 20:00
    -> 1 of 2 days late = 50.0%
    """
    install(monkeypatch, TIMING_ROWS)
    out = tn.tool_get_nutrition(TIMING_ARGS)
    day1, day2 = out["daily_breakdown"]
    assert day1["distribution"] == {"morning_pct": 20.0, "midday_pct": 35.0, "evening_pct": 45.0, "late_pct": 0.0}
    assert day2["distribution"]["late_pct"] == 66.7
    assert day2["late_eating_flag"] is True
    assert out["late_eating"] == {"days_eating_after_8pm": 1, "pct_days": 50.0}
    assert any("Eating after 8pm on 1/2 days" in f for f in out["circadian_flags"])


def test_meal_timing_flags_a_window_wider_than_the_trf_target(monkeypatch):
    """bites at 06:00 and 22:00 -> a 16.0 h window, wider than 12 -> WIDE + flag."""
    rows = [mf(f"2026-05-0{i}", total_calories_kcal=2000, food_log=[meal("06:00", 800), meal("22:00", 1200)]) for i in (5, 6)]
    install(monkeypatch, rows)
    out = tn.tool_get_nutrition(TIMING_ARGS)
    assert out["eating_window"]["avg_window_hrs"] == 16.0
    assert out["eating_window"]["trf_status"] == "WIDE"
    assert any("wider than the 10h TRF target" in f for f in out["circadian_flags"])


def test_meal_timing_errors_when_no_entry_carries_a_timestamp(monkeypatch):
    install(monkeypatch, [mf("2026-05-05", total_calories_kcal=2000, food_log=[{"food_name": "X", "calories_kcal": 2000}])])
    assert "No food log entries with timestamps" in tn.tool_get_nutrition(TIMING_ARGS)["error"]


def test_meal_timing_errors_when_the_range_is_empty(monkeypatch):
    install(monkeypatch, [])
    assert "error" in tn.tool_get_nutrition(TIMING_ARGS)


def test_meal_timing_reports_no_sleep_data_rather_than_a_null_gap(monkeypatch):
    """The honest half: with nothing in the eightsleep partition the overlap block
    says so instead of publishing a bare null."""
    install(monkeypatch, TIMING_ROWS)
    overlap = tn.tool_get_nutrition(TIMING_ARGS)["sleep_overlap"]
    assert overlap["avg_last_bite_to_sleep_hrs"] is None
    assert overlap["status"] == "no_sleep_data"


def test_meal_timing_computes_the_pre_sleep_gap_when_the_onset_field_is_present(monkeypatch):
    """The sleep-overlap arithmetic: onset 23.0 minus the 20:00 average last bite = a 3.0 h
    gap -> GOOD (Panda's >=3h). `sleep_onset_hour` is the LOCAL fractional hour the Eight
    Sleep writer derives (see the writer-shape test below)."""
    rows = TIMING_ROWS + [eightsleep("2026-05-05", sleep_onset_hour=23.0), eightsleep("2026-05-06", sleep_onset_hour=23.0)]
    install(monkeypatch, rows)
    overlap = tn.tool_get_nutrition(TIMING_ARGS)["sleep_overlap"]
    assert overlap["avg_last_bite_to_sleep_hrs"] == 3.0
    assert overlap["status"] == "GOOD"


def test_meal_timing_flags_a_last_bite_too_close_to_sleep(monkeypatch):
    """Onset 21.5 minus the 20:00 average last bite = 1.5 h -> below the
    2.5 h floor, so the GLP-1 clearance flag fires and the status is TOO_CLOSE."""
    rows = TIMING_ROWS + [eightsleep(day, sleep_onset_hour=21.5) for day in ("2026-05-05", "2026-05-06")]
    install(monkeypatch, rows)
    out = tn.tool_get_nutrition(TIMING_ARGS)
    assert out["sleep_overlap"]["avg_last_bite_to_sleep_hrs"] == 1.5
    assert out["sleep_overlap"]["status"] == "TOO_CLOSE"
    assert any("GLP-1 clearance" in f for f in out["circadian_flags"])


def test_meal_timing_wraps_a_pre_sleep_gap_across_midnight(monkeypatch):
    """A recorded onset EARLIER in the clock day than the last bite is a
    next-morning wake/onset artefact, not a negative gap: 9.0 - 20.0 = -11.0,
    wrapped to 13.0 h."""
    rows = TIMING_ROWS + [eightsleep(day, sleep_onset_hour=9.0) for day in ("2026-05-05", "2026-05-06")]
    install(monkeypatch, rows)
    assert tn.tool_get_nutrition(TIMING_ARGS)["sleep_overlap"]["avg_last_bite_to_sleep_hrs"] == 13.0


def test_meal_timing_still_answers_when_the_sleep_partition_read_fails(monkeypatch):
    """The overlap block is wrapped in its own try: an Eight Sleep outage costs the
    gap, not the eating-window report."""
    install(monkeypatch, TIMING_ROWS, raise_sources={"eightsleep"})
    out = tn.tool_get_nutrition(TIMING_ARGS)
    assert out["eating_window"]["avg_window_hrs"] == 11.5
    assert out["sleep_overlap"]["status"] == "no_sleep_data"


def test_meal_timing_flags_an_inconsistent_first_bite(monkeypatch):
    """First bites at 06:00 and 11:00 -> sd = sqrt(12.5/1) = 3.54 h, past the 1.5 h
    circadian-consistency threshold."""
    rows = [
        mf("2026-05-05", total_calories_kcal=2000, food_log=[meal("06:00", 1000), meal("14:00", 1000)]),
        mf("2026-05-06", total_calories_kcal=2000, food_log=[meal("11:00", 1000), meal("14:00", 1000)]),
    ]
    install(monkeypatch, rows)
    out = tn.tool_get_nutrition(TIMING_ARGS)
    assert out["eating_window"]["first_bite_consistency_sd_hrs"] == 3.54
    assert any("inconsistent circadian signalling" in f for f in out["circadian_flags"])


def test_meal_timing_carries_a_minute_that_rounds_up_into_the_next_hour(monkeypatch):
    """Average first bite (7 + 59/60 + 8.0)/2 = 7.99167 h; the minute term rounds
    to 60, which must roll the hour rather than print '07:60'."""
    rows = [
        mf("2026-05-05", total_calories_kcal=1000, food_log=[meal("07:59", 1000)]),
        mf("2026-05-06", total_calories_kcal=1000, food_log=[meal("08:00", 1000)]),
    ]
    install(monkeypatch, rows)
    assert tn.tool_get_nutrition(TIMING_ARGS)["eating_window"]["avg_first_bite"] == "08:00"


def test_meal_timing_computes_the_last_bite_to_sleep_gap_from_the_eightsleep_writer_shape(monkeypatch):
    """Reader/writer field agreement, DERIVED by calling the writer.

    CORRECTION to the original marker: it prescribed the wrong remedy — it asserted the
    Eight Sleep WRITER should start producing `sleep_start_local`. It should not. That is a
    GARMIN field name (`ingestion/garmin_lambda.py:709`, written to the garmin partition);
    `sleep_onset_local` has no writer anywhere in the repo. The Eight Sleep writer already
    publishes exactly what this tool needs — `sleep_onset_hour`, the LOCAL fractional hour
    derived with the night's tz offset — alongside the raw UTC ISO `sleep_start`. The fix is
    in the READER. (The marker's second half was right: the old code sliced
    `str(onset_str)[:5]` off what both candidate writers store as a full ISO timestamp, so
    even the correct field name would have parsed '2026-' and yielded None. Two faults over
    one feature is why nobody had ever seen `sleep_overlap` fail — it was always
    'no_sleep_data' and Panda's >=3h flag could never fire.)
    """
    from ingestion import eightsleep_lambda

    produced = eightsleep_lambda.compute_derived_fields(
        {"sleep_start": "2026-05-06T06:00:00Z", "sleep_end": "2026-05-06T14:00:00Z"}, tz_offset=-7
    )
    assert "sleep_onset_hour" in produced, "the Eight Sleep writer no longer derives the field this tool reads"
    assert produced["sleep_onset_hour"] == 23.0  # 06:00Z at UTC-7 == 23:00 the previous local evening

    rows = TIMING_ROWS + [eightsleep(day, **produced) for day in ("2026-05-05", "2026-05-06")]
    install(monkeypatch, rows)
    overlap = tn.tool_get_nutrition(TIMING_ARGS)["sleep_overlap"]
    assert overlap["avg_last_bite_to_sleep_hrs"] == 3.0  # onset 23.0 - avg last bite 20.0
    assert overlap["status"] == "GOOD"
    assert not any("GLP-1 clearance" in f for f in tn.tool_get_nutrition(TIMING_ARGS)["circadian_flags"])


def test_meal_timing_falls_back_to_the_raw_iso_sleep_start(monkeypatch):
    """Rows written before `compute_derived_fields` shipped carry only the raw UTC ISO
    `sleep_start`. Converted to Pacific (the same conversion `mcp/helpers.py` back-fills
    with), 2026-05-06T06:00Z is 23:00 PDT — a 3.0 h gap, not a dark section."""
    rows = TIMING_ROWS + [eightsleep(day, sleep_start=f"{day}T06:00:00Z") for day in ("2026-05-05", "2026-05-06")]
    install(monkeypatch, rows)
    assert tn.tool_get_nutrition(TIMING_ARGS)["sleep_overlap"]["avg_last_bite_to_sleep_hrs"] == 3.0


def test_meal_timing_ignores_the_garmin_field_name_it_used_to_read(monkeypatch):
    """The dead names must stay dead: an eightsleep row carrying only `sleep_start_local`
    (which nothing writes to that partition) reports no sleep data rather than a gap."""
    rows = TIMING_ROWS + [eightsleep(day, sleep_start_local="23:00") for day in ("2026-05-05", "2026-05-06")]
    install(monkeypatch, rows)
    assert tn.tool_get_nutrition(TIMING_ARGS)["sleep_overlap"]["status"] == "no_sleep_data"


def test_meal_timing_reports_no_consistency_figure_from_a_single_day(monkeypatch):
    """ADR-104/105: `stdev` returned the literal 0 below n=2 and published it as
    `first_bite_consistency_sd_hrs`. Zero is not a neutral placeholder on a consistency
    scale — it is the BEST possible value, so ONE logged day read as perfect circadian
    consistency AND suppressed the '>1.5h SD' flag: the single case where the tool has no
    idea was the case where it reassured him. None, with the n stated beside it."""
    install(monkeypatch, [TIMING_ROWS[0]])
    ew = tn.tool_get_nutrition(TIMING_ARGS)["eating_window"]
    assert ew["first_bite_consistency_sd_hrs"] is None
    assert ew["last_bite_consistency_sd_hrs"] is None
    assert ew["consistency_n_days"] == 1
    assert not any("inconsistent circadian signalling" in f for f in tn.tool_get_nutrition(TIMING_ARGS)["circadian_flags"])


def test_meal_timing_distribution_reflects_the_entries_it_actually_bucketed(monkeypatch):
    """ADR-104: the caloric distribution divided by the DAY-LEVEL `total_calories_kcal`,
    not by the sum of the food_log entries it had just bucketed. `macrofactor_lambda` drops
    zero-valued rollups at write time, so a day without that field published a factual 0.0%
    in every bucket — a fully logged day reading as 'no calories in any part of the day'.

    Same three meals as day 1, but with no day-level total: 400/700/900 of 2000
    logged kcal is still 20 / 35 / 45 percent."""
    install(monkeypatch, [mf("2026-05-05", food_log=[meal("08:00", 400), meal("12:30", 700), meal("19:00", 900)])])
    day = tn.tool_get_nutrition(TIMING_ARGS)["daily_breakdown"][0]
    assert day["distribution"] == {"morning_pct": 20.0, "midday_pct": 35.0, "evening_pct": 45.0, "late_pct": 0.0}
    assert sum(day["distribution"].values()) == pytest.approx(100.0, abs=0.3)
    assert day["located_calories"] == 2000


def test_meal_timing_percentages_sum_to_100_when_the_rollup_disagrees_with_the_entries(monkeypatch):
    """The other half of the same defect: when the day-level rollup and the entries
    disagree, the four percentages used to silently fail to sum to 100 with nothing saying
    so. Bucketing against the located total makes them sum, and both figures are published
    so the disagreement is visible rather than absorbed."""
    install(monkeypatch, [mf("2026-05-05", total_calories_kcal=3000, food_log=[meal("08:00", 400), meal("19:00", 600)])])
    day = tn.tool_get_nutrition(TIMING_ARGS)["daily_breakdown"][0]
    assert sum(day["distribution"].values()) == pytest.approx(100.0, abs=0.3)
    assert (day["total_calories"], day["located_calories"]) == (3000, 1000)


def test_meal_timing_reports_entries_it_could_not_parse(monkeypatch):
    """`t2d` parses only `HH:MM`; a 12-hour '7:30 PM' from the MacroFactor CSV column (whose
    format the platform does not control) returns None and the entry is dropped from BOTH
    the bite times and the calorie buckets — silently shrinking the eating window. The drop
    still happens; it is now COUNTED, and the calories of a dropped entry no longer sit
    inside a denominator its own bucket never entered."""
    install(monkeypatch, [mf("2026-05-05", total_calories_kcal=2000, food_log=[meal("08:00", 400), meal("7:30 PM", 1600)])])
    day = tn.tool_get_nutrition(TIMING_ARGS)["daily_breakdown"][0]
    assert day["entries_skipped"] == 1
    assert day["located_calories"] == 400
    assert day["distribution"]["morning_pct"] == 100.0  # of what was located, not 20% of an unlocated 2000
    # a fully-parsed day states zero skipped rather than omitting the count
    install(monkeypatch, TIMING_ROWS)
    assert [r["entries_skipped"] for r in tn.tool_get_nutrition(TIMING_ARGS)["daily_breakdown"]] == [0, 0]


@pytest.mark.parametrize("view", ["meal_timing", "summary", "macros"])
def test_the_sorting_views_tolerate_a_row_with_no_date_attribute(monkeypatch, view):
    """All three sorting views used `key=lambda x: x['date']`, a bare subscript: one
    malformed partition row without the attribute raised KeyError out of the tool and took
    down the whole answer, where the micronutrient view (which does not sort) kept working.
    Parametrised over the SET of sorting views so a fourth cannot regress silently."""
    broken = {"pk": PK + "macrofactor", "sk": "DATE#2026-05-05", "total_calories_kcal": 2000}
    install(monkeypatch, TIMING_ROWS + [broken])
    out = tn.tool_get_nutrition(dict(TIMING_ARGS, view=view))
    assert isinstance(out, dict) and "error" not in out


# ──────────────────────────────────────────────────────────────────────────────
# 4. view=summary — daily macros and rolling averages
# ──────────────────────────────────────────────────────────────────────────────

SUMMARY_ARGS = {"view": "summary", "start_date": "2026-05-01", "end_date": "2026-05-02"}

SUMMARY_ROWS = [
    mf("2026-05-01", total_calories_kcal=2000, total_protein_g=150, total_fiber_g=30, entries_count=6),
    mf("2026-05-02", total_calories_kcal=2500, total_protein_g=100, entries_count=4),
]


def test_summary_derives_protein_share_and_fiber_density_per_day(monkeypatch):
    """day 1: protein 150 g * 4 kcal/g = 600 of 2000 kcal -> 30.0%
             fiber 30 g per (2000/1000) = 15.0 g per 1000 kcal
    day 2: protein 100 g * 4 = 400 of 2500 -> 16.0%; no fiber logged -> no density
    """
    install(monkeypatch, SUMMARY_ROWS)
    day1, day2 = tn.tool_get_nutrition(SUMMARY_ARGS)["daily_breakdown"]
    assert day1["protein_pct_of_calories"] == 30.0
    assert day1["fiber_per_1000kcal"] == 15.0
    assert day2["protein_pct_of_calories"] == 16.0
    assert "fiber_per_1000kcal" not in day2


def test_summary_averages_only_the_days_that_carry_each_field(monkeypatch):
    """calories (2000 + 2500)/2 = 2250.0 ; protein (150 + 100)/2 = 125.0
    fiber appears on ONE day -> 30.0 ; sodium appears on none -> None, never 0."""
    install(monkeypatch, SUMMARY_ROWS)
    avgs = tn.tool_get_nutrition(SUMMARY_ARGS)["daily_averages"]
    assert avgs["calories_kcal"] == 2250.0
    assert avgs["protein_g"] == 125.0
    assert avgs["fiber_g"] == 30.0
    assert avgs["sodium_mg"] is None  # ADR-104: absent, not a factual 0


def test_summary_compares_each_average_to_its_target_with_a_signed_gap(monkeypatch):
    """protein average 125.0 vs the 180 g target -> gap -55.0, 69.4% of target, over the
    n=2 days that carried protein."""
    install(monkeypatch, SUMMARY_ROWS)
    tc = tn.tool_get_nutrition(SUMMARY_ARGS)["target_comparison"]["protein_g"]
    assert tc == {"target": 180, "average": 125.0, "gap": -55.0, "pct_of_target": 69.4, "n": 2}


def test_summary_errors_and_echoes_the_window_when_macrofactor_is_silent(monkeypatch):
    install(monkeypatch, [])
    out = tn.tool_get_nutrition(SUMMARY_ARGS)
    assert "error" in out and out["start_date"] == "2026-05-01" and out["end_date"] == "2026-05-02"


def test_summary_paginates_the_macrofactor_partition_without_dropping_days(monkeypatch):
    """query_source's `while True` pagination loop, driven by a BOUNDED fake that
    really returns LastEvaluatedKey."""
    rows = [mf(d("2026-05-01", i), total_calories_kcal=2000 + i) for i in range(6)]
    t = install(monkeypatch, rows, page_size=2)
    out = tn.tool_get_nutrition({"view": "summary", "start_date": "2026-05-01", "end_date": "2026-05-06"})
    assert out["period"]["days_with_data"] == 6
    assert t.page_count > len(t.queries), "the fake never paginated — the loop was not exercised"


def test_summary_states_the_per_field_sample_behind_each_target_comparison(monkeypatch):
    """ADR-105: `avg(field)` averages a per-FIELD sample, but the only n published was
    `period.days_with_data`, the count of ROWS. Fiber logged on 1 of 2 days was reported as
    a 30.0 g/day average beside 'days_with_data: 2', scored at 100% of its target — a
    smaller, invisible sample than the payload advertised. Every comparison now carries its
    own n, asserted over the whole SET rather than the one field that happened to differ."""
    install(monkeypatch, SUMMARY_ROWS)
    out = tn.tool_get_nutrition(SUMMARY_ARGS)
    assert out["period"]["days_with_data"] == 2
    assert out["target_comparison"]["fiber_g"]["n"] == 1
    assert out["target_comparison"]["protein_g"]["n"] == 2
    missing_n = [f for f, tc in out["target_comparison"].items() if "n" not in tc]
    assert missing_n == []


def test_the_two_nutrition_views_agree_on_the_fiber_target(monkeypatch):
    """Self-inconsistency: `_get_nutrition_summary` published fiber_g = 30, `_get_macro_targets`
    published 25 under `targets`, and the macros view's `hit_fiber` compared against a THIRD
    literal 25 — so 27 g/day was simultaneously 90% of target and a hit. One tool, one set of
    arguments, one target: `_FIBER_TARGET_G`. The scoring threshold is asserted too, since a
    published target the hit test does not use is the same defect wearing a different hat."""
    install(monkeypatch, SUMMARY_ROWS)
    summary_target = tn.tool_get_nutrition(SUMMARY_ARGS)["target_comparison"]["fiber_g"]["target"]
    macros = tn.tool_get_nutrition(dict(SUMMARY_ARGS, view="macros"))
    assert summary_target == macros["targets"]["fiber_g"] == tn._FIBER_TARGET_G
    # a day exactly ON the published target is a hit; one under it is not
    at_target = tn._FIBER_TARGET_G
    install(monkeypatch, [mf("2026-05-01", total_calories_kcal=2000, total_fiber_g=at_target)])
    assert tn.tool_get_nutrition(dict(SUMMARY_ARGS, view="macros"))["daily_breakdown"][0]["hit_fiber_target"] is True
    install(monkeypatch, [mf("2026-05-01", total_calories_kcal=2000, total_fiber_g=at_target - 1)])
    assert tn.tool_get_nutrition(dict(SUMMARY_ARGS, view="macros"))["daily_breakdown"][0]["hit_fiber_target"] is False


# ──────────────────────────────────────────────────────────────────────────────
# 5. view=macros — adherence against a TDEE-derived target
# ──────────────────────────────────────────────────────────────────────────────

MACRO_ROWS = [
    mf("2026-05-01", total_calories_kcal=2000, total_protein_g=150, total_fiber_g=30, total_fat_g=70, total_carbs_g=200),
    mf("2026-05-02", total_calories_kcal=1500, total_protein_g=100, total_fiber_g=20, total_fat_g=50, total_carbs_g=150),
]
MACRO_ARGS = {"view": "macros", "start_date": "2026-05-01", "end_date": "2026-05-02", "calorie_target": 2000, "protein_target": 150}


def test_macros_scores_daily_adherence_against_the_given_targets(monkeypatch):
    """target 2000 kcal / 150 g protein / 25 g fiber
    day 1: 2000/2000 = 100.0% (0.85 <= 1.00 <= 1.10 -> hit); 150 >= 142.5 -> hit; 30 >= 25 -> hit
    day 2: 1500/2000 =  75.0% (miss);  100/150 = 66.7% (miss);  20 < 25 (miss)
    -> 1 of 2 on every axis = 50.0%
    """
    install(monkeypatch, MACRO_ROWS)
    out = tn.tool_get_nutrition(MACRO_ARGS)
    day1, day2 = out["daily_breakdown"]
    assert (day1["calories_pct"], day1["protein_pct"]) == (100.0, 100.0)
    assert (day2["calories_pct"], day2["protein_pct"]) == (75.0, 66.7)
    assert [day1["hit_calorie_target"], day1["hit_protein_target"], day1["hit_fiber_target"]] == [True, True, True]
    assert out["adherence"] == {
        "calorie_target_hit_pct": 50.0,
        "protein_target_hit_pct": 50.0,
        "fiber_target_hit_pct": 50.0,
        "days_scored": {"calorie": 2, "protein": 2, "fiber": 2},
    }


def test_macros_rolling_window_spans_exactly_the_days_requested(monkeypatch):
    """#1917, done right: `start = end - (days - 1)` over an INCLUSIVE `sk BETWEEN`
    really is 7 dates. Pinned as the correct reference the readiness/energy window
    bugs should be measured against."""
    t = install(monkeypatch, MACRO_ROWS)
    tn.tool_get_nutrition({"view": "macros", "days": 7, "end_date": "2026-05-09"})
    lo, hi = t.window_for("macrofactor")
    assert (lo, hi) == ("2026-05-03", "2026-05-09")
    assert span_days(lo, hi) == 7


def test_macros_estimates_the_calorie_target_from_the_latest_weigh_in(monkeypatch):
    """ADR-152 (#2310): 220 lbs -> 99.79024 kg
    BMR   = 10*99.79024 + 6.25*182.88 - 5*35 + 5 = 1970.9024 -> 1971
    TDEE  = BMR + measured 7d exercise energy / 7 = 1971 + 0 (no strava rows) = 1971
    target = TDEE - 500 deficit                                               = 1471
    The retired form published round(1970.9024 * 1.55) = 3055 — a MAINTENANCE figure,
    from a flat multiplier, labelled as the day's calorie target.
    """
    install(monkeypatch, MACRO_ROWS + [withings("2026-05-02", weight_lbs=220.0)], profile=PROFILE_WITH_HEIGHT)
    out = tn.tool_get_nutrition({"view": "macros", "start_date": "2026-05-01", "end_date": "2026-05-02"})
    assert out["targets"]["calories_kcal"] == 1471


def test_macros_publishes_the_method_and_the_inputs_behind_its_calorie_target(monkeypatch):
    """ADR-105/ADR-152: the number is checkable without reading the source — TDEE, the
    deficit, the target, the method name, and the inputs (including the exercise-capture
    gap tell `exercise_energy_days`) all ship on the payload."""
    install(monkeypatch, MACRO_ROWS + [withings("2026-05-02", weight_lbs=220.0)], profile=PROFILE_WITH_HEIGHT)
    t = tn.tool_get_nutrition({"view": "macros", "start_date": "2026-05-01", "end_date": "2026-05-02"})["targets"]
    detail = t["calorie_target_detail"]
    assert detail["method"] == "mifflin_bmr_plus_measured_7d_exercise"
    assert (detail["tdee"], detail["deficit"], detail["target"]) == (1971, 500, 1471)
    assert detail["target"] == t["calories_kcal"]  # the published target IS the payload's
    assert detail["inputs"]["bmr_kcal"] == 1971 and detail["inputs"]["weight_lbs"] == 220.0
    assert detail["inputs"]["age_basis"] == "no_date_of_birth_in_profile"
    # honest absence, never a fabricated multiplier: no strava in the window
    assert detail["inputs"]["exercise_energy_days"] == 0
    assert detail["inputs"]["exercise_kcal_7d"] == 0
    assert t["calorie_target_basis"] == "mifflin_bmr_plus_measured_7d_exercise_minus_deficit"


def test_macros_grades_adherence_against_the_target_not_against_maintenance(monkeypatch):
    """The re-base (#2310). A 1500 kcal day is 102% of the 1471 target -> a HIT; against
    the retired 3055 maintenance figure it was 49% -> a miss. Same day, same food."""
    rows = [mf("2026-05-01", total_calories_kcal=1500), withings("2026-05-01", weight_lbs=220.0)]
    install(monkeypatch, rows, profile=PROFILE_WITH_HEIGHT)
    out = tn.tool_get_nutrition({"view": "macros", "start_date": "2026-05-01", "end_date": "2026-05-01"})
    assert out["targets"]["calories_kcal"] == 1471
    assert out["daily_breakdown"][0]["hit_calorie_target"] is True
    assert out["adherence"]["calorie_target_hit_pct"] == 100.0


def test_macros_falls_back_to_the_flat_default_when_no_weigh_in_exists(monkeypatch):
    install(monkeypatch, MACRO_ROWS, profile=PROFILE_WITH_HEIGHT)
    out = tn.tool_get_nutrition({"view": "macros", "start_date": "2026-05-01", "end_date": "2026-05-02"})
    assert out["targets"]["calories_kcal"] == 2400
    assert out["targets"]["protein_g"] == 180


def test_macros_errors_when_macrofactor_is_silent(monkeypatch):
    install(monkeypatch, [])
    assert "error" in tn.tool_get_nutrition(MACRO_ARGS)


def test_macros_still_answers_when_the_weight_lookup_fails(monkeypatch):
    """A Withings outage costs the personalised target, not the whole report."""
    install(monkeypatch, MACRO_ROWS, profile=PROFILE_WITH_HEIGHT, raise_sources={"withings"})
    out = tn.tool_get_nutrition({"view": "macros", "start_date": "2026-05-01", "end_date": "2026-05-02"})
    assert out["targets"]["calories_kcal"] == 2400
    assert out["adherence"]["protein_target_hit_pct"] == 0.0  # 150 and 100 both short of 180*0.95


def test_macros_ignores_a_withings_row_that_carries_no_weight(monkeypatch):
    """ADR-104: `float(wt_items_sorted[0].get('weight_lbs', 0))` defaulted a missing weight
    to ZERO and carried it into Mifflin-St Jeor — BMR 973, target round(973*1.55) = 1508 kcal.
    The surrounding try/except never caught it, because 0 is a perfectly good float. A
    Withings row that synced without a weight (body-composition-only, a partial sync) made
    the tool tell a 220 lb man to eat 1508 kcal/day. An absent weight is not a weight."""
    install(monkeypatch, MACRO_ROWS + [withings("2026-05-02", fat_ratio=38.0)], profile=PROFILE_WITH_HEIGHT)
    out = tn.tool_get_nutrition({"view": "macros", "start_date": "2026-05-01", "end_date": "2026-05-02"})
    assert out["targets"]["calories_kcal"] == 2400
    assert out["targets"]["calorie_target_basis"] == "flat_default_no_weight_or_height"
    assert out["targets"]["calorie_target_detail"] is None
    # and a weightless row NEWER than a real weigh-in must not mask the weigh-in either
    rows = MACRO_ROWS + [withings("2026-05-01", weight_lbs=220.0), withings("2026-05-02", fat_ratio=38.0)]
    install(monkeypatch, rows, profile=PROFILE_WITH_HEIGHT)
    out = tn.tool_get_nutrition({"view": "macros", "start_date": "2026-05-01", "end_date": "2026-05-02"})
    assert out["targets"]["calories_kcal"] == 1471  # ADR-152: 1971 TDEE - 500 deficit


def test_macros_excludes_a_day_with_no_calorie_rollup_from_the_hit_rate(monkeypatch):
    """ADR-104: every macro was read as `float(item.get(field, 0) or 0)`, so a row with no
    calorie rollup — which `macrofactor_lambda` produces for a day it could not total, since
    zero rollups are dropped at write time — was published as `calories_kcal: 0` and counted
    as a MISSED target. The hit-rate he is graded on fell for days he simply did not upload."""
    rows = MACRO_ROWS[:1] + [mf("2026-05-02", total_protein_g=150, total_fiber_g=30)]
    install(monkeypatch, rows)
    out = tn.tool_get_nutrition(MACRO_ARGS)
    assert out["adherence"]["calorie_target_hit_pct"] == 100.0  # 1 of 1 measured day
    assert out["adherence"]["days_scored"] == {"calorie": 1, "protein": 2, "fiber": 2}
    # the unmeasured day is present and explicitly blank, never a factual zero
    day2 = out["daily_breakdown"][1]
    assert day2["calories_kcal"] is None and day2["calories_pct"] is None and day2["hit_calorie_target"] is None


def test_the_macro_target_and_the_energy_view_agree_on_todays_calorie_target(monkeypatch):
    """ADR-152 / #2310 — the marker this replaces was accurate: both tools answered "what
    should I eat?" from the SAME weight, both called it Mifflin-St Jeor, and they disagreed
    by ~1500 kcal. `_get_macro_targets` hardcoded height 182.88 cm / age 35 and multiplied
    BMR by a flat 1.55 with NO deficit (3055 kcal, labelled `calories_kcal` under
    `targets`), while `_get_energy_expenditure` read height from the profile, added
    MEASURED exercise energy, and subtracted 500 (1557 kcal).

    Both now derive from the one implementation in `health.tdee`:
        BMR(220 lb, 72 in, 35 y)             = 1971 kcal
        measured 7d exercise (3600 s proxy)  = round(6 * 99.79 kg * 1 h) = 599 kcal
        TDEE = 1971 + round(599 / 7)         = 2057 kcal   (MAINTENANCE)
        target = 2057 - 500                  = 1557 kcal   (what he eats)
    """
    from mcp import tools_health as th

    monkeypatch.setattr(th, "datetime", _FrozenDatetime)
    freeze_pacific(monkeypatch, th, _FrozenDatetime)  # #2817: pin the PACIFIC helpers this module now calls
    rows = MACRO_ROWS + [withings(PT_TODAY, weight_lbs=220.0), strava(PT_TODAY, total_moving_time_seconds=3600)]
    install(monkeypatch, rows, profile=PROFILE_WITH_HEIGHT)
    macros = tn.tool_get_nutrition({"view": "macros", "start_date": "2026-05-01", "end_date": PT_TODAY})
    energy = th.tool_get_daily_metrics({"view": "energy"})
    assert macros["targets"]["calories_kcal"] == energy["calorie_target_based_on_7d"] == 1557
    # ...and not merely equal by luck: the same TDEE, deficit and method underneath.
    assert macros["targets"]["calorie_target_detail"] == energy["calorie_target"]
    assert energy["calorie_target"]["tdee"] == energy["tdee_7d_avg"] == 2057
    assert energy["calorie_target"]["inputs"]["exercise_energy_days"] == 1


# ──────────────────────────────────────────────────────────────────────────────
# 6. get_deficit_sustainability — the 5-channel cut early-warning
# ──────────────────────────────────────────────────────────────────────────────

SUST_ARGS = {"days": 7, "end_date": "2026-05-09"}  # window 2026-05-03 .. 2026-05-09
_SUST_DAYS = [d("2026-05-03", i) for i in range(6)]  # six whoop days inside the window
FLAT = [50, 50, 50, 40, 40, 40]


def sust_rows(hrv=None, eff=None, rec=None, cal=1800, t0=None, kj=None) -> list[dict]:
    """Seven MacroFactor days (the tool's own floor) plus six Whoop days, optionally
    plus habitify / strava series for channels 4 and 5."""
    rows = [mf(d("2026-05-03", i), total_calories_kcal=cal) for i in range(7)]
    for i, day in enumerate(_SUST_DAYS):
        fields: dict = {}
        if hrv:
            fields["hrv"] = hrv[i]
        if eff:
            fields["sleep_efficiency_percentage"] = eff[i]
        if rec:
            fields["recovery_score"] = rec[i]
        if fields:
            rows.append(whoop(day, **fields))
    if t0:
        # exactly the shape ingestion/habitify_lambda.py writes
        rows += [habitify(day, completion_pct=t0[i], total_completed=8, total_possible=10) for i, day in enumerate(_SUST_DAYS)]
    if kj:
        # DERIVED from the real writer: ingestion/strava_lambda.transform() rolls the
        # per-activity `kilojoules` up into a day-level `total_kilojoules`, so the fixture
        # cannot drift from what the strava partition actually holds.
        from ingestion import strava_lambda

        for i, day in enumerate(_SUST_DAYS):
            raw = {"activities": [{"kilojoules": kj[i], "moving_time_seconds": 3600}]}
            produced = {k: v for k, v in strava_lambda.transform(raw, day)[0].items() if k not in ("source", "date")}
            rows.append(strava(day, **produced))
    return rows


def channel(out: dict, name: str) -> dict:
    return next(c for c in out["channels"] if c["name"] == name)


def test_deficit_detects_the_deficit_and_labels_its_aggressiveness(monkeypatch):
    """intake 1800 vs the profile's 2500 TDEE -> deficit 700 kcal/day
    700 / 2500 * 100 = 28.0% -> above 25 -> 'aggressive'"""
    install(monkeypatch, sust_rows(hrv=FLAT))
    out = tn.tool_get_deficit_sustainability(SUST_ARGS)
    assert out["deficit"] == {
        "in_deficit": True,
        "avg_intake_kcal": 1800,
        "estimated_tdee": 2500,
        "deficit_kcal": 700,
        "deficit_pct": 28.0,
        "deficit_label": "aggressive",
    }


def test_deficit_raises_a_warning_when_three_channels_degrade_together(monkeypatch):
    """first-third vs last-third of each six-day series:
    HRV      50 -> 40 : (40-50)/50 * 100 = -20.0%  (|20| > 8  -> degraded)
    Sleep    95 -> 85 : (85-95)/95 * 100 = -10.5%  (|10.5| > 3 -> degraded)
    Recovery 70 -> 50 : (50-70)/70 * 100 = -28.6%  (|28.6| > 10 -> degraded)
    3 of 5 -> WARNING
    """
    install(monkeypatch, sust_rows(hrv=FLAT, eff=[95, 95, 95, 85, 85, 85], rec=[70, 70, 70, 50, 50, 50]))
    out = tn.tool_get_deficit_sustainability(SUST_ARGS)
    assert channel(out, "HRV")["delta_pct"] == -20.0
    assert channel(out, "Sleep Quality")["delta_pct"] == -10.5
    assert channel(out, "Recovery")["delta_pct"] == -28.6
    assert out["degraded_count"] == 3
    assert out["severity"] == "WARNING"
    assert "200 kcal/day" in out["recommendation"]


def test_deficit_reports_stable_channels_and_their_averages(monkeypatch):
    """HRV avg      = (50*3 + 40*3)/6 = 270/6 = 45.0
    Recovery avg = (70*3 + 50*3)/6 = 360/6 = 60.0"""
    install(monkeypatch, sust_rows(hrv=FLAT, rec=[70, 70, 70, 50, 50, 50]))
    out = tn.tool_get_deficit_sustainability(SUST_ARGS)
    assert channel(out, "HRV")["avg"] == 45.0
    assert channel(out, "Recovery")["avg"] == 60.0


def test_deficit_says_so_plainly_when_there_is_no_deficit(monkeypatch):
    """intake 2450 vs TDEE 2500 -> 50 kcal, under the 200 kcal detection floor."""
    install(monkeypatch, sust_rows(hrv=FLAT, cal=2450))
    out = tn.tool_get_deficit_sustainability(SUST_ARGS)
    assert out["deficit"]["in_deficit"] is False
    assert out["severity"] == "NOT_IN_DEFICIT"


def test_deficit_refuses_to_answer_from_fewer_than_seven_logged_days(monkeypatch):
    """ADR-105: a floor, stated in the error, rather than a verdict from 3 days."""
    rows = [mf(d("2026-05-03", i), total_calories_kcal=1800) for i in range(3)]
    install(monkeypatch, rows)
    out = tn.tool_get_deficit_sustainability(SUST_ARGS)
    assert "Need ≥7 days" in out["error"] and "Found 3" in out["error"]


def test_deficit_estimates_tdee_from_withings_when_the_profile_has_none(monkeypatch):
    """ADR-152: the SAME definition the macros and energy views use — and TDEE means
    MAINTENANCE here, because this tracker's whole signal is `tdee - intake`. Folding the
    500 kcal deficit into the TDEE would double-count it. 220 lbs, 72 in, no strava in the
    window -> BMR 1971 + 0 exercise = 1971."""
    rows = sust_rows(hrv=FLAT) + [withings("2026-05-08", weight_lbs=220.0)]
    install(monkeypatch, rows, profile=PROFILE_WITH_HEIGHT)
    assert tn.tool_get_deficit_sustainability(SUST_ARGS)["deficit"]["estimated_tdee"] == 1971


def test_deficit_raises_a_watch_not_an_alarm_when_two_channels_degrade(monkeypatch):
    """HRV -20% and recovery -28.6% degrade; efficiency is flat -> 2 of 5 -> WATCH."""
    install(monkeypatch, sust_rows(hrv=FLAT, eff=[90] * 6, rec=[70, 70, 70, 50, 50, 50]))
    out = tn.tool_get_deficit_sustainability(SUST_ARGS)
    assert channel(out, "Sleep Quality")["status"] == "stable"
    assert out["degraded_count"] == 2 and out["severity"] == "WATCH"


def test_deficit_reads_a_channel_that_starts_from_zero_as_stable(monkeypatch):
    """Two rest days open the window, so the training series starts at 0 kJ. There
    is no percentage change to state from a zero baseline — the channel must say
    stable rather than divide by zero."""
    install(monkeypatch, sust_rows(hrv=FLAT, kj=[0, 0, 50, 50, 80, 80]))
    train = channel(tn.tool_get_deficit_sustainability(SUST_ARGS), "Training Output")
    assert train["direction"] == "stable" and train["delta_pct"] == 0
    assert train["status"] == "stable"


def test_deficit_reports_a_small_drift_as_stable_rather_than_as_a_trend(monkeypatch):
    """HRV 50 -> 49 is (49-50)/50 * 100 = -2.0%, inside the +/-5% dead band, so the
    channel reports the delta AND calls it stable — noise is not a trend."""
    install(monkeypatch, sust_rows(hrv=[50, 50, 50, 49, 49, 49]))
    hrv = channel(tn.tool_get_deficit_sustainability(SUST_ARGS), "HRV")
    assert hrv["delta_pct"] == -2.0 and hrv["direction"] == "stable" and hrv["status"] == "stable"


def test_deficit_names_an_improving_channel_as_improving(monkeypatch):
    """HRV 40 -> 50 is (50-40)/40 * 100 = +25.0%: a rising channel is reported as
    improving, never merely as 'not degraded'."""
    install(monkeypatch, sust_rows(hrv=[40, 40, 40, 50, 50, 50]))
    hrv = channel(tn.tool_get_deficit_sustainability(SUST_ARGS), "HRV")
    assert hrv["delta_pct"] == 25.0 and hrv["direction"] == "improving" and hrv["status"] == "stable"


def test_deficit_falls_back_to_a_flat_tdee_when_neither_profile_nor_scale_answers(monkeypatch):
    install(monkeypatch, sust_rows(hrv=FLAT), profile={"pk": "USER#matthew", "sk": "PROFILE#v1"})
    assert tn.tool_get_deficit_sustainability(SUST_ARGS)["deficit"]["estimated_tdee"] == 2400


def test_deficit_marks_a_channel_with_too_few_points_as_insufficient_data(monkeypatch):
    """ADR-105 again: a trend is not asserted from fewer than 6 observations, and
    the channel says which state it is in rather than defaulting to 'stable'."""
    install(monkeypatch, sust_rows(hrv=FLAT))
    out = tn.tool_get_deficit_sustainability(SUST_ARGS)
    assert channel(out, "Habit Completion")["direction"] == "insufficient_data"
    assert channel(out, "Training Output")["direction"] == "insufficient_data"


def test_the_habit_channel_reads_a_field_the_habitify_writer_produces(monkeypatch):
    """Reader/writer field agreement, channel 4.

    `ingestion/habitify_lambda.py` writes `completion_pct` (pending-aware),
    `completion_pct_strict`, `by_group[*].pct`, `total_completed`, `total_possible`. The tool
    read `tier_0_completion_rate` or `t0_rate` — NEITHER produced by any writer in the repo
    (there is no "Tier 0" group; `P40_GROUPS` is the nine named groups). The channel had
    therefore never carried a value: always [], always 'insufficient_data', `habits_degraded`
    always False — behavioural unravelling, the earliest sign a cut is failing, structurally
    invisible to the tool built to catch it.

    CORRECTION to the original marker: it prescribed asserting the WRITER produces
    `tier_0_completion_rate`. It should not — the writer is right and the reader was wrong.
    The dead names are asserted dead below."""
    from ingestion import habitify_lambda

    src = inspect.getsource(habitify_lambda)
    assert '"completion_pct"' in src, "the habitify writer no longer produces the field this channel reads"
    assert '"tier_0_completion_rate"' not in src and '"t0_rate"' not in src

    install(monkeypatch, sust_rows(hrv=FLAT, t0=[0.9, 0.9, 0.9, 0.3, 0.3, 0.3]))
    out = tn.tool_get_deficit_sustainability(SUST_ARGS)
    hab = channel(out, "Habit Completion")
    assert hab["direction"] == "declining"
    assert hab["delta_pct"] == -66.7  # (0.3 - 0.9) / 0.9 * 100
    assert hab["status"] == "degraded"
    assert hab["avg"] == 0.6


def test_the_habit_channel_stays_dark_on_the_field_names_it_used_to_read(monkeypatch):
    """The dead names must stay dead: a habitify row carrying only `tier_0_completion_rate`
    is not a habit reading, so the channel says insufficient_data rather than inventing one."""
    rows = sust_rows(hrv=FLAT)
    rows += [habitify(day, tier_0_completion_rate=v) for day, v in zip(_SUST_DAYS, [0.9, 0.9, 0.9, 0.3, 0.3, 0.3])]
    install(monkeypatch, rows)
    assert channel(tn.tool_get_deficit_sustainability(SUST_ARGS), "Habit Completion")["direction"] == "insufficient_data"


def test_the_training_channel_reads_a_field_the_strava_writer_produces(monkeypatch):
    """Reader/writer field agreement, channel 5 — DERIVED by calling the real transform.

    CORRECTION to the original marker: its stated cause is FALSE on current main. It claimed
    `strava_lambda.transform()` "never writes" `total_kilojoules`; the writer rolls the
    per-activity `kilojoules` up into a day-level `total_kilojoules` and says so in a comment
    naming this very reader. The tool's read was already correct — what was stale was the
    FIXTURE, which built strava rows carrying only `activities`, so the channel measured a
    column the test itself had failed to write. `sust_rows` now builds its strava rows
    THROUGH `transform`, which is what makes this assertion mean anything."""
    from ingestion import strava_lambda

    produced = strava_lambda.transform({"activities": [{"kilojoules": 900, "moving_time_seconds": 3600}]}, "2026-05-03")[0]
    assert produced["total_kilojoules"] == 900
    install(monkeypatch, sust_rows(hrv=FLAT, kj=[1000, 1000, 1000, 300, 300, 300]))
    out = tn.tool_get_deficit_sustainability(SUST_ARGS)
    train = channel(out, "Training Output")
    assert train["direction"] == "declining"
    assert train["delta_pct"] == -70.0  # (300 - 1000) / 1000 * 100
    assert train["status"] == "degraded"


def test_a_total_collapse_across_all_five_channels_reaches_critical(monkeypatch):
    """The composite consequence of the two field mismatches above: the tool advertises five
    channels and escalates at 3+ (WARNING) / 4+ (CRITICAL), but with habits and training
    wired to dead names only three could ever change state — so CRITICAL was unreachable and
    WARNING required ALL THREE surviving channels (which all read the same Whoop record) to
    degrade at once. The escalation ladder was calibrated against a denominator of 5 while
    only 3 could fire."""
    rows = sust_rows(
        hrv=FLAT,
        eff=[95, 95, 95, 85, 85, 85],
        rec=[70, 70, 70, 50, 50, 50],
        t0=[0.9, 0.9, 0.9, 0.3, 0.3, 0.3],
        kj=[1000, 1000, 1000, 300, 300, 300],
    )
    install(monkeypatch, rows)
    out = tn.tool_get_deficit_sustainability(SUST_ARGS)
    assert out["degraded_count"] == 5
    assert [c["status"] for c in out["channels"]] == ["degraded"] * 5
    assert out["severity"] == "CRITICAL"


def test_deficit_refuses_to_score_a_window_with_no_calorie_data(monkeypatch):
    """ADR-104: `cals` was collected with a truthiness filter and then `avg_cal = sum/len if
    cals else 0`. Seven MacroFactor rows carrying no `total_calories_kcal` — reachable, since
    `macrofactor_lambda` drops zero-valued totals at write time — cleared the `len(mf_items)
    < 7` floor and averaged to a factual ZERO intake, making `2500 - 0` a 100% 'aggressive'
    deficit fabricated out of missing data, with every severity verdict computed against it."""
    rows = [mf(d("2026-05-03", i), total_protein_g=150) for i in range(7)]
    install(monkeypatch, rows + sust_rows(hrv=FLAT)[7:])
    out = tn.tool_get_deficit_sustainability(SUST_ARGS)
    assert "error" in out, f"reported a {out.get('deficit', {}).get('deficit_pct')}% deficit from no intake data"
    assert "deficit" not in out and "severity" not in out
    assert "calorie rollup" in out["error"]


def test_deficit_states_how_many_days_actually_carried_intake(monkeypatch):
    """ADR-105/#1917: `period` published `days` — the REQUESTED window — and nothing else,
    while every intake figure was computed over however many days carried a rollup. Seven
    logged days inside a 14-day request produced a payload that said 'days: 14'."""
    install(monkeypatch, sust_rows(hrv=FLAT))
    out = tn.tool_get_deficit_sustainability({"days": 14, "end_date": "2026-05-09"})
    assert out["period"]["days"] == 14
    assert out["period"]["days_with_data"] == 7


# ──────────────────────────────────────────────────────────────────────────────
# 7. _get_metabolic_adaptation — TDEE divergence (reached via get_benchmark)
# ──────────────────────────────────────────────────────────────────────────────

# Eight consecutive ISO weeks, 2026-W12 .. 2026-W19; Monday of each.
_MONDAYS = [d("2026-03-16", 7 * i) for i in range(8)]
_WEEKLY_WEIGHTS = [320.0, 319.7, 319.4, 319.1, 318.8, 318.5, 318.2, 317.9]  # 0.3 lb/week, 2.1 lb total
ADAPT_ARGS = {"end_date": "2026-05-10", "weeks": 8}


def adapt_rows(days_per_week=2, weights=None) -> list[dict]:
    """`days_per_week` MacroFactor days at 2000 kcal in each of eight ISO weeks,
    plus one Withings weigh-in per week."""
    weights = weights or _WEEKLY_WEIGHTS
    rows = []
    for wi, monday in enumerate(_MONDAYS):
        for offset in range(days_per_week):
            rows.append(mf(d(monday, offset), total_calories_kcal=2000))
        rows.append(withings(monday, weight_lbs=weights[wi]))
    return rows


def test_metabolic_adaptation_aggregates_by_iso_week_and_keeps_the_per_week_n(monkeypatch):
    """The count of days behind each weekly average IS stored — `cal_days` /
    `wt_days` — which is what makes the deficit bug below a fix rather than a
    redesign."""
    install(monkeypatch, adapt_rows())
    out = tn._get_metabolic_adaptation(ADAPT_ARGS)
    assert out["period"]["weeks_analysed"] == 8
    assert [w["week"] for w in out["weekly_data"]][:2] == ["2026-W12", "2026-W13"]
    assert all(w["cal_days"] == 2 and w["wt_days"] == 1 for w in out["weekly_data"])


def test_metabolic_adaptation_reports_the_hand_derived_weekly_loss_rates(monkeypatch):
    """Weights fall 0.3 lb/week, so every week after the first reports 0.3, the
    first reports None (no prior week to difference against), and the recent and
    early four-week averages are both 0.3."""
    install(monkeypatch, adapt_rows())
    out = tn._get_metabolic_adaptation(ADAPT_ARGS)
    assert out["weekly_data"][0]["weekly_loss_lbs"] is None
    assert [w["weekly_loss_lbs"] for w in out["weekly_data"][1:]] == [0.3] * 7
    assert out["rate_analysis"]["recent_avg_lbs_per_week"] == 0.3
    assert out["rate_analysis"]["early_avg_lbs_per_week"] == 0.3


@pytest.mark.parametrize(
    "rate,expected_actual,expected_ratio,severity",
    [
        # 8 fully-logged weeks at 2000 kcal vs a 2500 TDEE -> expected loss
        # 8 * (2500-2000) * 7 / 3500 = 8.0 lb. Actual = rate * 7 weeks of drop.
        (1.0, 7.0, 0.88, "NONE"),
        (0.8, 5.6, 0.70, "MILD"),
        (0.5, 3.5, 0.44, "MODERATE"),
        (0.3, 2.1, 0.26, "SEVERE"),
    ],
)
def test_metabolic_adaptation_bands_the_ratio_of_actual_to_expected_loss(monkeypatch, rate, expected_actual, expected_ratio, severity):
    weights = [round(320.0 - rate * i, 2) for i in range(8)]
    install(monkeypatch, adapt_rows(days_per_week=7, weights=weights))
    ma = tn._get_metabolic_adaptation(ADAPT_ARGS)["metabolic_adaptation"]
    assert ma["expected_loss_lbs"] == 8.0
    assert ma["actual_loss_lbs"] == expected_actual
    assert ma["adaptation_ratio"] == expected_ratio
    assert ma["severity"] == severity


def test_metabolic_adaptation_says_insufficient_data_when_there_was_no_deficit(monkeypatch):
    """Intake equal to TDEE -> every weekly deficit is 0 -> no expected loss to
    divide by, so the ratio is None and the verdict says so instead of inferring
    adaptation from an undefined denominator."""
    rows = [r for r in adapt_rows(days_per_week=7) if "macrofactor" not in r["pk"]]
    for monday in _MONDAYS:
        rows += [mf(d(monday, o), total_calories_kcal=2500) for o in range(7)]
    install(monkeypatch, rows)
    ma = tn._get_metabolic_adaptation(ADAPT_ARGS)["metabolic_adaptation"]
    assert ma["adaptation_ratio"] is None
    assert ma["severity"] == "INSUFFICIENT_DATA"


def test_metabolic_adaptation_estimates_base_tdee_from_the_first_weeks_weight(monkeypatch):
    """No `tdee_estimate` in the profile: 320 lbs -> 145.14944 kg
    BMR = 10*145.14944 + 6.25*182.88 - 5*35 + 5 = 2424.4944 -> 2424
    base_tdee = BMR + measured 7d exercise energy (none in these rows) = 2424 (ADR-152).
    The retired form published round(2424.4944 * 1.55) = 3758 — and an inflated BASE TDEE
    inflates every "expected loss" this tracker grades actual loss against.
    """
    install(monkeypatch, adapt_rows(days_per_week=7), profile=PROFILE_WITH_HEIGHT)
    assert tn._get_metabolic_adaptation(ADAPT_ARGS)["metabolic_adaptation"]["estimated_base_tdee"] == 2424


def test_metabolic_adaptation_needs_two_weeks_of_nutrition_before_it_speaks(monkeypatch):
    install(monkeypatch, [mf(d("2026-05-01", i), total_calories_kcal=2000) for i in range(5)])
    assert "Need ≥14 days" in tn._get_metabolic_adaptation(ADAPT_ARGS)["error"]


def test_metabolic_adaptation_needs_four_weigh_ins_before_it_speaks(monkeypatch):
    """Plenty of nutrition, not enough scale data: the floors are separate and
    each names the shortfall rather than answering from what it has."""
    rows = [mf(d("2026-04-01", i), total_calories_kcal=2000) for i in range(20)]
    rows += [withings(d("2026-04-01", i), weight_lbs=320.0 - i) for i in range(2)]
    install(monkeypatch, rows)
    out = tn._get_metabolic_adaptation(ADAPT_ARGS)
    assert "Need ≥4 Withings" in out["error"] and "Found 2" in out["error"]


def test_metabolic_adaptation_needs_three_paired_weeks(monkeypatch):
    """14 nutrition days and 4 weigh-ins, but only two ISO weeks carry both."""
    rows = [mf(d("2026-04-27", i), total_calories_kcal=2000) for i in range(14)]
    rows += [withings(d("2026-04-27", i), weight_lbs=320.0 - i * 0.1) for i in range(4)]
    install(monkeypatch, rows)
    assert "≥3 weeks" in tn._get_metabolic_adaptation(ADAPT_ARGS)["error"]


def test_metabolic_adaptation_scales_the_expected_deficit_to_the_days_actually_logged(monkeypatch):
    """ADR-104/105: `weekly_deficit = (base_tdee - wd['avg_cal']) * 7` charged every ISO week
    a FULL SEVEN DAYS of deficit regardless of how many were logged — while `cal_days`, the
    honest multiplier, was computed two blocks earlier and sat unused in the very dict being
    iterated. At 2 logged days a week that inflated expected loss 3.5x (8.0 lb against a real
    2.3) and collapsed the ratio from an honest 0.91 ('NONE') to 0.26 -> SEVERE: '2-3 week
    reverse diet... check thyroid markers (TSH, T3, T4) at next blood draw.' Partial logging
    alone manufactured a metabolic-suppression diagnosis and a medical follow-up."""
    install(monkeypatch, adapt_rows(days_per_week=2))
    out = tn._get_metabolic_adaptation(ADAPT_ARGS)
    # 8 weeks * (2500 - 2000) kcal * 2 logged days = 8000 kcal / 3500 = 2.3 lb expected
    assert out["metabolic_adaptation"]["expected_loss_lbs"] == 2.3
    assert out["metabolic_adaptation"]["actual_loss_lbs"] == 2.1
    assert out["metabolic_adaptation"]["adaptation_ratio"] == 0.91
    assert out["metabolic_adaptation"]["severity"] == "NONE"
    assert "thyroid" not in out["recommendation"]


@pytest.mark.parametrize("days_per_week,expected", [(2, 2.3), (3, 3.4), (4, 4.6), (7, 8.0)])
def test_metabolic_adaptation_expected_loss_scales_with_logging_density(monkeypatch, days_per_week, expected):
    """The same fix stated as a monotone SET rather than one measured point: 8 weeks x
    (2500-2000) kcal x n logged days / 3500. Only the fully-logged 7-day case may reach the
    8.0 lb the flat multiplier used to charge everyone."""
    install(monkeypatch, adapt_rows(days_per_week=days_per_week))
    assert tn._get_metabolic_adaptation(ADAPT_ARGS)["metabolic_adaptation"]["expected_loss_lbs"] == expected


def test_metabolic_adaptation_gives_no_slowdown_when_early_and_recent_overlap(monkeypatch):
    """ADR-105: `recent_rates = weekly_data[-4:]` and `early_rates = weekly_data[1:5]` were
    published with a `rate_slowdown_pct` between them — but below nine weeks those slices
    OVERLAP, and at the three-week minimum this tool accepts they are the IDENTICAL two
    weeks, so a 0.0% slowdown was presented as a measured comparison of a period against
    itself. The two averages are each real and stay published; only the comparison between
    them waits for disjoint windows, and `rate_windows_disjoint` says which state it is in."""
    rows = []
    for wi, monday in enumerate(_MONDAYS[5:]):  # three ISO weeks
        rows += [mf(d(monday, o), total_calories_kcal=2000) for o in range(5)]
        rows.append(withings(monday, weight_lbs=[319.9, 319.0, 318.0][wi]))
    rows.append(withings(d(_MONDAYS[5], 1), weight_lbs=319.9))  # 4th weigh-in
    install(monkeypatch, rows)
    out = tn._get_metabolic_adaptation(ADAPT_ARGS)
    assert out["period"]["weeks_analysed"] == 3
    assert out["rate_analysis"]["rate_slowdown_pct"] is None
    assert out["rate_analysis"]["rate_windows_disjoint"] is False
    assert out["rate_analysis"]["early_avg_lbs_per_week"] is not None  # each average is still real


def test_metabolic_adaptation_publishes_a_slowdown_once_the_windows_are_disjoint(monkeypatch):
    """The other half of the derived check: at nine weeks `[1:5]` and `[-4:]` no longer
    share an index, so the comparison becomes meaningful and IS published. Without this the
    fix above would be indistinguishable from deleting the feature."""
    mondays = [d("2026-03-09", 7 * i) for i in range(9)]
    weights = [320.0 - i for i in range(5)] + [316.0 - 0.5 * (i + 1) for i in range(4)]  # 1.0 lb/wk then 0.5
    rows = []
    for wi, monday in enumerate(mondays):
        rows += [mf(d(monday, o), total_calories_kcal=2000) for o in range(7)]
        rows.append(withings(monday, weight_lbs=weights[wi]))
    install(monkeypatch, rows)
    out = tn._get_metabolic_adaptation({"end_date": "2026-05-10", "weeks": 10})
    assert out["period"]["weeks_analysed"] == 9
    assert out["rate_analysis"]["rate_windows_disjoint"] is True
    # early weeks 1-4 fall 1.0 lb/wk, recent weeks 5-8 fall 0.5 -> a 50% slowdown
    assert out["rate_analysis"]["early_avg_lbs_per_week"] == 1.0
    assert out["rate_analysis"]["recent_avg_lbs_per_week"] == 0.5
    assert out["rate_analysis"]["rate_slowdown_pct"] == 50.0


def test_metabolic_adaptation_does_not_describe_a_weight_gain_as_losing(monkeypatch):
    """ADR-104: `adaptation_ratio = actual_loss / expected_loss` goes NEGATIVE when weight
    went up, falls through every band to SEVERE and is then interpolated into
    f'Losing only {round(ratio*100)}% of expected' — a 1.9 lb GAIN reported as 'Losing only
    -63% of expected'. The severity is right; the sentence is nonsense, and the sentence is
    what a reader quotes."""
    rows = []
    for wi, monday in enumerate(_MONDAYS[5:]):
        rows += [mf(d(monday, o), total_calories_kcal=2000) for o in range(5)]
        rows.append(withings(monday, weight_lbs=[320.0, 321.0, 322.0][wi]))
    rows.append(withings(d(_MONDAYS[5], 1), weight_lbs=320.2))
    install(monkeypatch, rows)
    out = tn._get_metabolic_adaptation(ADAPT_ARGS)
    assert out["metabolic_adaptation"]["actual_loss_lbs"] < 0
    assert "Losing only -" not in out["recommendation"]
    assert "Losing" not in out["recommendation"] and "UP 1.9 lb" in out["recommendation"]
    assert out["metabolic_adaptation"]["severity"] == "SEVERE"  # the verdict was never the wrong part


# ──────────────────────────────────────────────────────────────────────────────
# 8. Cross-cutting: blast radius
# ──────────────────────────────────────────────────────────────────────────────


def test_get_nutrition_reads_only_the_partitions_each_view_needs(monkeypatch):
    """summary/macros/micronutrients answer from MacroFactor (plus Withings for the
    TDEE estimate); meal_timing additionally reads eightsleep. Pinned so a future
    'while we're here' read shows up as a failure rather than as quiet scope creep
    on an owner-facing tool."""
    t = install(monkeypatch, SUMMARY_ROWS + TIMING_ROWS)
    for view in VIEWS:
        tn.tool_get_nutrition({"view": view, "start_date": "2026-05-01", "end_date": "2026-05-06"})
    assert t.sources_read <= {"macrofactor", "withings", "eightsleep"}


def test_no_nutrition_tool_reaches_food_delivery_genome_or_labs(monkeypatch):
    """Food-delivery spend and binge frequency are NUTRITION_DELIVERY_PUBLIC-gated
    in the serving path; genome per-variant identifiers are Tier-2 owner-only and
    labs are CROSS_PHASE clinical truth. None of them belongs in a macro report —
    asserted across every registered tool in the module at once."""
    t = install(monkeypatch, SUMMARY_ROWS + sust_rows(hrv=FLAT) + adapt_rows())
    for name in sorted(MODULE_TOOLS):
        MODULE_TOOLS[name]["fn"]({})
    for view in VIEWS:
        tn.tool_get_nutrition({"view": view})
    tn._get_metabolic_adaptation(ADAPT_ARGS)
    assert not (t.sources_read & {"food_delivery", "genome", "labs", "dexa", "macrofactor_meals"})


def test_every_view_answers_a_quiet_platform_with_an_error_never_a_zero(monkeypatch):
    """ADR-104 envelope check across the whole declared view SET: a reset or a
    genesis week must produce an explicit 'no data' rather than a payload of
    zeros a reader would take as measured."""
    install(monkeypatch, [])
    for view in VIEWS:
        out = tn.tool_get_nutrition({"view": view})
        assert "error" in out, view
        assert "daily_averages" not in out and "adherence" not in out
    assert "error" in tn.tool_get_deficit_sustainability({})
    assert "error" in tn._get_metabolic_adaptation({})
