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


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (#1917 + frame mixing, P2, mcp/tools_nutrition.py:73-74, 179-180, 341-342): the "
        "default `end_date` is `_nutrition_through_date()` — a PACIFIC-anchored yesterday — while "
        "the default `start_date` is `datetime.now(timezone.utc) - 29 days`. Two different calendar "
        "frames define one window, so its LENGTH depends on where the clock sits relative to the "
        "UTC/PT boundary: 29 dates in the PT morning and 28 in the UTC-evening window. The registry "
        "documents `start_date` as 'default: 30 days ago'. Every average, deficiency verdict and "
        "ratio in the micronutrient/summary/meal-timing views is computed over that window."
    ),
)
@pytest.mark.parametrize("utc_now", [NOW, datetime(2026, 5, 11, 3, 0, 0, tzinfo=timezone.utc)])
def test_the_default_window_really_spans_thirty_days(monkeypatch, utc_now):
    _FROZEN[0] = utc_now
    _PT[0] = "2026-05-10"
    t = install(monkeypatch, [])
    tn.tool_get_nutrition({"view": "summary"})
    lo, hi = t.window_for("macrofactor")
    assert span_days(lo, hi) == 30


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


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (ADR-104, P1, mcp/tools_nutrition.py:140-154 _get_micronutrient_report): the three "
        "longevity flags are computed as `totals_sum.get(field, 0) / max(totals_count.get(field, 1), "
        "1)`, so a nutrient that appears in NO record averages to a factual 0.0 — and every "
        "threshold is a `<`, so absence fires all three. On a range that only ever logged fiber the "
        "tool asserts 'DHA averages 0.0g/day - below the 1g+ associated with cognitive protection', "
        "'Magnesium averages 0mg/day' and 'Vitamin D from food averages 0.0mcg/day', each with a "
        "supplement recommendation attached. Every other number in this function is correctly gated "
        "on `totals_count[field] == 0`; only the flag block is not. Who it hurts: three fabricated "
        "deficiencies, stated as measured averages, that he can act on by buying supplements."
    ),
)
def test_micronutrients_makes_no_longevity_claim_about_a_nutrient_never_logged(monkeypatch):
    install(monkeypatch, micro_rows(total_fiber_g=40))
    out = tn.tool_get_nutrition(MICRO_ARGS)
    assert out["longevity_flags"] == []


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (ADR-104, P2, mcp/tools_nutrition.py:131-133 _get_micronutrient_report): when "
        "omega-6 was never logged, `omega6` evaluates to 0.0 (sum default 0 over a count floored to "
        "1) and the published `omega6_omega3_ratio` becomes 0.0:1 — a PERFECT anti-inflammatory "
        "score invented out of a missing column. The sibling `omega6_omega3_status` correctly reads "
        "'insufficient_data' only because 0.0 happens to be falsy, so the summary block contradicts "
        "itself: an insufficient-data status beside a concrete ratio. The ratio must be None when "
        "either side has no readings."
    ),
)
def test_micronutrients_publishes_no_omega_ratio_when_omega_six_was_never_logged(monkeypatch):
    install(monkeypatch, micro_rows(total_omega3_total_g=2))
    out = tn.tool_get_nutrition(MICRO_ARGS)
    assert out["summary"]["omega6_omega3_ratio"] is None


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


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (ADR-105, P2, mcp/tools_nutrition.py:115-118 _get_micronutrient_report): the "
        "per-category rows carry `days_logged`, but the `deficiencies` / `near_gaps` lists — the "
        "part a reader actually quotes, and the part the summary counts — drop it. The docstring "
        "calls these 'chronic deficiencies'; a single logged day produces one identical in shape to "
        "a thirty-day one, and nothing in the payload distinguishes them."
    ),
)
def test_a_deficiency_entry_states_how_many_days_it_averaged(monkeypatch):
    install(monkeypatch, [mf("2026-05-01", total_fiber_g=5)])
    out = tn.tool_get_nutrition(MICRO_ARGS)
    assert out["deficiencies"][0].get("days_logged") == 1


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
    """The sleep-overlap arithmetic itself is correct: onset 23:00 (23.0) minus the
    20:00 average last bite = a 3.0 h gap -> GOOD (Panda's >=3h). It is simply
    never reached in production, because nothing writes `sleep_start_local` (see
    the xfail immediately below)."""
    rows = TIMING_ROWS + [eightsleep("2026-05-05", sleep_start_local="23:00"), eightsleep("2026-05-06", sleep_start_local="23:00")]
    install(monkeypatch, rows)
    overlap = tn.tool_get_nutrition(TIMING_ARGS)["sleep_overlap"]
    assert overlap["avg_last_bite_to_sleep_hrs"] == 3.0
    assert overlap["status"] == "GOOD"


def test_meal_timing_flags_a_last_bite_too_close_to_sleep(monkeypatch):
    """Onset 21:30 (21.5) minus the 20:00 average last bite = 1.5 h -> below the
    2.5 h floor, so the GLP-1 clearance flag fires and the status is TOO_CLOSE."""
    rows = TIMING_ROWS + [eightsleep(day, sleep_start_local="21:30") for day in ("2026-05-05", "2026-05-06")]
    install(monkeypatch, rows)
    out = tn.tool_get_nutrition(TIMING_ARGS)
    assert out["sleep_overlap"]["avg_last_bite_to_sleep_hrs"] == 1.5
    assert out["sleep_overlap"]["status"] == "TOO_CLOSE"
    assert any("GLP-1 clearance" in f for f in out["circadian_flags"])


def test_meal_timing_wraps_a_pre_sleep_gap_across_midnight(monkeypatch):
    """A recorded onset EARLIER in the clock day than the last bite is a
    next-morning wake/onset artefact, not a negative gap: 9.0 - 20.0 = -11.0,
    wrapped to 13.0 h."""
    rows = TIMING_ROWS + [eightsleep(day, sleep_start_local="09:00") for day in ("2026-05-05", "2026-05-06")]
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


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (reader/writer field mismatch, P1, mcp/tools_nutrition.py:277-282 "
        "_get_meal_timing): the sleep-overlap block reads `si.get('sleep_start_local') or "
        "si.get('sleep_onset_local')` from the EIGHTSLEEP partition. "
        "`ingestion/eightsleep_lambda.py:493-495` writes `sleep_start` / `sleep_end`; the only "
        "`sleep_start_local` writer in the repo is `ingestion/garmin_lambda.py:709`, which writes "
        "it to the GARMIN partition — this reads like a Garmin field name pasted into an Eight "
        "Sleep read. `sleep_onset_local` has no writer at all. The whole `sleep_overlap` section is "
        "therefore permanently dark: pre_sleep_gap is always None, the status is always "
        "'no_sleep_data', and Panda's '>=3h before sleep onset' circadian flag can never fire. "
        "A SECOND bug guards the same feature — line 280 slices `str(onset_str)[:5]` before "
        "parsing, and both candidate writers store a full ISO timestamp, so even the right field on "
        "the right partition would parse '2026-' and yield None. Two independent faults over one "
        "feature is why nobody has ever seen it fail."
    ),
)
def test_meal_timing_computes_the_last_bite_to_sleep_gap_from_the_eightsleep_writer_shape(monkeypatch):
    from ingestion import eightsleep_lambda

    src = inspect.getsource(eightsleep_lambda)
    assert '"sleep_start_local"' in src or '"sleep_onset_local"' in src, "no writer produces the field the tool reads"
    rows = TIMING_ROWS + [
        eightsleep("2026-05-05", sleep_start="2026-05-05T23:00:00"),
        eightsleep("2026-05-06", sleep_start="2026-05-06T23:00:00"),
    ]
    install(monkeypatch, rows)
    overlap = tn.tool_get_nutrition(TIMING_ARGS)["sleep_overlap"]
    assert overlap["avg_last_bite_to_sleep_hrs"] == 3.0  # onset 23.0 - avg last bite 20.0


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (ADR-104/105, P1, mcp/tools_nutrition.py:263-268 _get_meal_timing): `stdev` returns "
        "the literal 0 when fewer than two values exist, and that 0 is published as "
        "`first_bite_consistency_sd_hrs` / `last_bite_consistency_sd_hrs`. Zero is not a neutral "
        "placeholder here — it is the BEST possible value on that scale, so one logged day reads as "
        "perfect circadian consistency. It also suppresses the '>1.5h SD' inconsistency flag, so "
        "the single case where the tool has no idea is the case where it reassures him. Should be "
        "None with n stated."
    ),
)
def test_meal_timing_reports_no_consistency_figure_from_a_single_day(monkeypatch):
    install(monkeypatch, [TIMING_ROWS[0]])
    ew = tn.tool_get_nutrition(TIMING_ARGS)["eating_window"]
    assert ew["first_bite_consistency_sd_hrs"] is None


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (ADR-104, P2, mcp/tools_nutrition.py:234 + 245-250 _get_meal_timing): the caloric "
        "distribution divides by the DAY-LEVEL `total_calories_kcal` field, not by the sum of the "
        "food_log entries it just bucketed. Two consequences: (a) when that field is absent — which "
        "`macrofactor_lambda` guarantees for a zero total, since it drops zero-valued rollups — "
        "`total_cal` is 0 and every bucket publishes a factual 0.0%, so a fully logged day reads as "
        "'no calories in any part of the day'; (b) when the field and the entries disagree, the "
        "four percentages silently fail to sum to 100 with nothing saying so."
    ),
)
def test_meal_timing_distribution_reflects_the_entries_it_actually_bucketed(monkeypatch):
    """Same three meals as day 1, but with no day-level total: 400/700/900 of 2000
    logged kcal is still 20 / 35 / 45 percent."""
    install(monkeypatch, [mf("2026-05-05", food_log=[meal("08:00", 400), meal("12:30", 700), meal("19:00", 900)])])
    dist = tn.tool_get_nutrition(TIMING_ARGS)["daily_breakdown"][0]["distribution"]
    assert sum(dist.values()) == pytest.approx(100.0, abs=0.3)


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (P3, mcp/tools_nutrition.py:186-192 + 214-228 _get_meal_timing): `t2d` parses only "
        "`HH:MM`; anything else (a 12-hour `7:30 PM`, an empty string) returns None and the entry is "
        "dropped from BOTH the bite times and the calorie buckets — while its calories still sit "
        "inside the day-level `total_calories_kcal` denominator. So an unparseable timestamp "
        "silently shrinks the eating window AND deflates every distribution percentage, with no "
        "count of what was skipped. The time string comes straight from a MacroFactor CSV column "
        "(`macrofactor_lambda.py:164`), whose format the platform does not control. Measured here: "
        "a day with an 08:00 meal and a '7:30 PM' meal reports first_bite == last_bite == 08:00, "
        "`eating_window_hrs: 0.0` and 20% of its calories located — a 13.5-hour eating window "
        "published as zero."
    ),
)
def test_meal_timing_reports_entries_it_could_not_parse(monkeypatch):
    install(monkeypatch, [mf("2026-05-05", total_calories_kcal=2000, food_log=[meal("08:00", 400), meal("7:30 PM", 1600)])])
    out = tn.tool_get_nutrition(TIMING_ARGS)
    assert out["daily_breakdown"][0].get("entries_skipped") == 1


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (P3, mcp/tools_nutrition.py:210, 365, 460 — _get_meal_timing, "
        "_get_nutrition_summary, _get_macro_targets): all three sort with `key=lambda x: x['date']`, "
        "a bare subscript. One malformed partition row without a `date` attribute raises KeyError "
        "out of the tool and takes down the whole answer, where the micronutrient view (which does "
        "not sort) would have kept working. Every other read in this module uses `.get`."
    ),
)
def test_meal_timing_tolerates_a_row_with_no_date_attribute(monkeypatch):
    broken = {"pk": PK + "macrofactor", "sk": "DATE#2026-05-05", "total_calories_kcal": 2000}
    install(monkeypatch, TIMING_ROWS + [broken])
    out = tn.tool_get_nutrition(TIMING_ARGS)
    assert isinstance(out, dict)


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
    """protein average 125.0 vs the 180 g target -> gap -55.0, 69.4% of target."""
    install(monkeypatch, SUMMARY_ROWS)
    tc = tn.tool_get_nutrition(SUMMARY_ARGS)["target_comparison"]["protein_g"]
    assert tc == {"target": 180, "average": 125.0, "gap": -55.0, "pct_of_target": 69.4}


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


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (ADR-105, P2, mcp/tools_nutrition.py:383-411 _get_nutrition_summary): `avg(field)` "
        "averages `[r[field] for r in daily_rows if field in r]` — a per-FIELD n — but the only n "
        "published is `period.days_with_data`, the count of ROWS. Here fiber was logged on 1 of 2 "
        "days and is reported as a 30.0 g/day average beside 'days_with_data: 2', scored at 100% of "
        "its target. Any nutrient MacroFactor tracks sporadically silently averages over a "
        "different, smaller and invisible sample than the one the payload advertises. Each "
        "target_comparison entry should carry its own n."
    ),
)
def test_summary_states_the_per_field_sample_behind_each_target_comparison(monkeypatch):
    install(monkeypatch, SUMMARY_ROWS)
    out = tn.tool_get_nutrition(SUMMARY_ARGS)
    assert out["period"]["days_with_data"] == 2
    assert out["target_comparison"]["fiber_g"].get("n") == 1


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (self-inconsistency, P2, mcp/tools_nutrition.py:396 vs 500 — _get_nutrition_summary "
        "TARGETS['fiber_g'] = 30 while _get_macro_targets returns targets['fiber_g'] = 25, and the "
        "macros view's `hit_fiber` threshold is a third literal 25 at line 472). One tool, one set "
        "of arguments, two published fiber targets depending on which view he asks for. 27 g/day "
        "is simultaneously 90% of target and a hit."
    ),
)
def test_the_two_nutrition_views_agree_on_the_fiber_target(monkeypatch):
    install(monkeypatch, SUMMARY_ROWS)
    summary_target = tn.tool_get_nutrition(SUMMARY_ARGS)["target_comparison"]["fiber_g"]["target"]
    macros_target = tn.tool_get_nutrition(dict(SUMMARY_ARGS, view="macros"))["targets"]["fiber_g"]
    assert summary_target == macros_target


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
    assert out["adherence"] == {"calorie_target_hit_pct": 50.0, "protein_target_hit_pct": 50.0, "fiber_target_hit_pct": 50.0}


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
    """220 lbs -> 99.79024 kg
    BMR = 10*99.79024 + 6.25*182.88 - 5*35 + 5 = 1970.9024
    target = round(1970.9024 * 1.55) = 3055
    """
    install(monkeypatch, MACRO_ROWS + [withings("2026-05-02", weight_lbs=220.0)])
    out = tn.tool_get_nutrition({"view": "macros", "start_date": "2026-05-01", "end_date": "2026-05-02"})
    assert out["targets"]["calories_kcal"] == 3055


def test_macros_falls_back_to_the_flat_default_when_no_weigh_in_exists(monkeypatch):
    install(monkeypatch, MACRO_ROWS)
    out = tn.tool_get_nutrition({"view": "macros", "start_date": "2026-05-01", "end_date": "2026-05-02"})
    assert out["targets"]["calories_kcal"] == 2400
    assert out["targets"]["protein_g"] == 180


def test_macros_errors_when_macrofactor_is_silent(monkeypatch):
    install(monkeypatch, [])
    assert "error" in tn.tool_get_nutrition(MACRO_ARGS)


def test_macros_still_answers_when_the_weight_lookup_fails(monkeypatch):
    """A Withings outage costs the personalised target, not the whole report."""
    install(monkeypatch, MACRO_ROWS, raise_sources={"withings"})
    out = tn.tool_get_nutrition({"view": "macros", "start_date": "2026-05-01", "end_date": "2026-05-02"})
    assert out["targets"]["calories_kcal"] == 2400
    assert out["adherence"]["protein_target_hit_pct"] == 0.0  # 150 and 100 both short of 180*0.95


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (ADR-104, P1, mcp/tools_nutrition.py:446-452 _get_macro_targets): "
        "`float(wt_items_sorted[0].get('weight_lbs', 0))` defaults a missing weight to ZERO and "
        "carries it straight into Mifflin-St Jeor: BMR = 10*0 + 6.25*182.88 - 175 + 5 = 973, "
        "target = round(973 * 1.55) = 1508 kcal. The surrounding `try/except` catches type errors "
        "but not this one, because 0 is a perfectly good float — so a Withings row that synced "
        "without a weight (body-composition-only, a partial sync) makes the tool tell a 220 lb man "
        "to eat 1508 kcal/day, under the 1500 floor its own sibling tool warns about. An absent "
        "weight must fall through to the 2400 default, not through a zero-weight human."
    ),
)
def test_macros_ignores_a_withings_row_that_carries_no_weight(monkeypatch):
    install(monkeypatch, MACRO_ROWS + [withings("2026-05-02", fat_ratio=38.0)])
    out = tn.tool_get_nutrition({"view": "macros", "start_date": "2026-05-01", "end_date": "2026-05-02"})
    assert out["targets"]["calories_kcal"] == 2400


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (ADR-104, P2, mcp/tools_nutrition.py:461-476 _get_macro_targets): every macro is "
        "read as `float(item.get(field, 0) or 0)`, so a partition row with no calorie rollup — "
        "which `macrofactor_lambda` produces for a day it could not total (zero rollups are dropped "
        "at write time, line 307) — is published as `calories_kcal: 0, calories_pct: 0.0` and "
        "counted as a MISSED calorie target. Unlogged days are folded into the adherence "
        "denominator as failures, so the hit-rate he is graded on falls for days he simply did not "
        "upload."
    ),
)
def test_macros_excludes_a_day_with_no_calorie_rollup_from_the_hit_rate(monkeypatch):
    rows = MACRO_ROWS[:1] + [mf("2026-05-02", total_protein_g=150, total_fiber_g=30)]
    install(monkeypatch, rows)
    out = tn.tool_get_nutrition(MACRO_ARGS)
    assert out["adherence"]["calorie_target_hit_pct"] == 100.0  # 1 of 1 measured day


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (self-inconsistency, P1, mcp/tools_nutrition.py:450-455 vs "
        "mcp/tools_health.py:611-646): both tools answer 'what should I eat?' from the SAME weight "
        "and both call it Mifflin-St Jeor, and they disagree by ~1500 kcal. `_get_macro_targets` "
        "hardcodes height 182.88 cm and age 35 and multiplies BMR by a 1.55 activity factor with no "
        "deficit (220 lbs -> 3055 kcal, labelled 'calories_kcal' under `targets`), while "
        "`_get_energy_expenditure` reads height from the profile, adds measured exercise energy "
        "instead of a multiplier, and subtracts a 500 kcal deficit (-> 1557 kcal). A third figure, "
        "2400, is hardcoded in `_get_nutrition_summary`. Three calorie targets for one day."
    ),
)
def test_the_macro_target_and_the_energy_view_agree_on_todays_calorie_target(monkeypatch):
    from mcp import tools_health as th

    monkeypatch.setattr(th, "datetime", _FrozenDatetime)
    rows = MACRO_ROWS + [withings(PT_TODAY, weight_lbs=220.0), strava(PT_TODAY, total_moving_time_seconds=3600)]
    install(monkeypatch, rows, profile={"pk": "USER#matthew", "sk": "PROFILE#v1", "height_inches": 72})
    macros = tn.tool_get_nutrition({"view": "macros", "start_date": "2026-05-01", "end_date": PT_TODAY})
    energy = th.tool_get_daily_metrics({"view": "energy"})
    # macros: round(Mifflin(220 lb, 72 in, 35 y) * 1.55)          = 3055 kcal
    # energy: Mifflin 1971 + 86 kcal exercise - 500 kcal deficit  = 1557 kcal
    assert macros["targets"]["calories_kcal"] == pytest.approx(energy["calorie_target_based_on_7d"], rel=0.1)


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
        rows += [strava(day, activities=[{"kilojoules": kj[i], "moving_time_seconds": 3600}]) for i, day in enumerate(_SUST_DAYS)]
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
    """220 lbs -> the same Mifflin*1.55 = 3055 the macros view computes."""
    rows = sust_rows(hrv=FLAT) + [withings("2026-05-08", weight_lbs=220.0)]
    install(monkeypatch, rows, profile={"pk": "USER#matthew", "sk": "PROFILE#v1"})
    assert tn.tool_get_deficit_sustainability(SUST_ARGS)["deficit"]["estimated_tdee"] == 3055


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


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (reader/writer field mismatch, P1, mcp/tools_nutrition.py:635 "
        "tool_get_deficit_sustainability): channel 4 collects "
        "`h.get('tier_0_completion_rate') or h.get('t0_rate')` from the habitify partition. "
        "`ingestion/habitify_lambda.py:359-372` writes `completion_pct`, `completion_pct_strict`, "
        "`by_group[*].pct`, `total_completed`, `total_possible` — NEITHER field the tool reads is "
        "produced by any writer in the repo (grep confirms only readers). The Habit Completion "
        "channel has therefore never carried a value: `t0_rates` is always [], the direction is "
        "always 'insufficient_data', and `habits_degraded` is always False. Behavioural unravelling "
        "— the earliest and most actionable sign a cut is failing — is structurally invisible to "
        "the tool built to catch it. (The site-api sibling at lambdas/web/site_api_nutrition.py:854 "
        "reads the same two dead names.)"
    ),
)
def test_the_habit_channel_reads_a_field_the_habitify_writer_produces(monkeypatch):
    from ingestion import habitify_lambda

    src = inspect.getsource(habitify_lambda)
    assert '"tier_0_completion_rate"' in src or '"t0_rate"' in src, "no writer produces either field the tool reads"
    install(monkeypatch, sust_rows(hrv=FLAT, t0=[0.9, 0.9, 0.9, 0.3, 0.3, 0.3]))
    out = tn.tool_get_deficit_sustainability(SUST_ARGS)
    assert channel(out, "Habit Completion")["direction"] == "declining"


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (reader/writer field mismatch, P1, mcp/tools_nutrition.py:646 "
        "tool_get_deficit_sustainability): channel 5 sums `s.get('total_kilojoules', 0)` per day, "
        "and `ingestion/strava_lambda.py:300-311 transform()` never writes that key — it rolls up "
        "distance / moving time / elevation / zone-2 seconds only. This test calls the real "
        "transform so it cannot drift from the writer. Consequence: `training_vals` is all zeros, "
        "`trend_direction` short-circuits on `first_avg == 0` and returns ('stable', 0), so the "
        "Training Output channel can never degrade either. The per-activity `kilojoules` IS "
        "captured (strava_lambda.py:173) and is right there in `activities` — it is simply never "
        "summed."
    ),
)
def test_the_training_channel_reads_a_field_the_strava_writer_produces(monkeypatch):
    from ingestion import strava_lambda

    produced = strava_lambda.transform({"activities": [{"kilojoules": 900, "moving_time_seconds": 3600}]}, "2026-05-03")[0]
    assert "total_kilojoules" in produced
    install(monkeypatch, sust_rows(hrv=FLAT, kj=[1000, 1000, 1000, 300, 300, 300]))
    out = tn.tool_get_deficit_sustainability(SUST_ARGS)
    assert channel(out, "Training Output")["direction"] == "declining"


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (P1, the composite consequence of the two field mismatches above, "
        "mcp/tools_nutrition.py:653-693 tool_get_deficit_sustainability): the tool advertises five "
        "channels and escalates at 3+ (WARNING) and 4+ (CRITICAL), but only three of the five can "
        "ever change state — habits and training are wired to fields no writer produces. So "
        "CRITICAL is unreachable, and WARNING requires ALL THREE surviving channels (which all read "
        "the same Whoop record) to degrade at once. Here every one of the five real signals "
        "collapses — HRV -20%, efficiency -10.5%, recovery -28.6%, T0 habits 0.9 -> 0.3, training "
        "1000 -> 300 kJ — and the tool still answers WARNING/3, understating a textbook "
        "back-off-now week. Who it hurts: the escalation ladder is calibrated against a denominator "
        "of 5 while only 3 can fire."
    ),
)
def test_a_total_collapse_across_all_five_channels_reaches_critical(monkeypatch):
    rows = sust_rows(
        hrv=FLAT,
        eff=[95, 95, 95, 85, 85, 85],
        rec=[70, 70, 70, 50, 50, 50],
        t0=[0.9, 0.9, 0.9, 0.3, 0.3, 0.3],
        kj=[1000, 1000, 1000, 300, 300, 300],
    )
    install(monkeypatch, rows)
    out = tn.tool_get_deficit_sustainability(SUST_ARGS)
    assert out["degraded_count"] >= 4
    assert out["severity"] == "CRITICAL"


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (ADR-104, P1, mcp/tools_nutrition.py:557-576 tool_get_deficit_sustainability): "
        "`cals` is collected with a truthiness filter and then `avg_cal = sum/len if cals else 0`. "
        "Seven MacroFactor rows that carry no `total_calories_kcal` rollup — reachable, since "
        "`macrofactor_lambda` drops zero-valued totals at write time and its daily-summary path "
        "writes protein-only rows — pass the `len(mf_items) < 7` floor and then average to a "
        "factual ZERO intake. `deficit_kcal = 2500 - 0` makes it a 2500 kcal/day, 100%, "
        "'aggressive' deficit fabricated entirely out of missing data, and every severity verdict "
        "downstream is computed against it. Absent intake must be an error, exactly as the <7-day "
        "case already is."
    ),
)
def test_deficit_refuses_to_score_a_window_with_no_calorie_data(monkeypatch):
    rows = [mf(d("2026-05-03", i), total_protein_g=150) for i in range(7)]
    install(monkeypatch, rows + sust_rows(hrv=FLAT)[7:])
    out = tn.tool_get_deficit_sustainability(SUST_ARGS)
    assert "error" in out, f"reported a {out.get('deficit', {}).get('deficit_pct')}% deficit from no intake data"


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (ADR-105 / #1917, P2, mcp/tools_nutrition.py:696-706 "
        "tool_get_deficit_sustainability): `period` publishes `days` — the REQUESTED window — and "
        "nothing else, while `avg_intake_kcal`, `deficit_kcal` and `deficit_pct` are computed over "
        "however many days actually carried a calorie rollup. Seven logged days inside a 14-day "
        "request produce a payload that says 'days: 14'. Every other range tool in this module "
        "publishes `days_with_data`; this one, the one that issues the strongest recommendations, "
        "does not."
    ),
)
def test_deficit_states_how_many_days_actually_carried_intake(monkeypatch):
    install(monkeypatch, sust_rows(hrv=FLAT))
    out = tn.tool_get_deficit_sustainability({"days": 14, "end_date": "2026-05-09"})
    assert out["period"].get("days_with_data") == 7


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
    BMR = 10*145.14944 + 6.25*182.88 - 5*35 + 5 = 2424.4944
    base_tdee = round(2424.4944 * 1.55) = 3758
    """
    install(monkeypatch, adapt_rows(days_per_week=7), profile={"pk": "USER#matthew", "sk": "PROFILE#v1"})
    assert tn._get_metabolic_adaptation(ADAPT_ARGS)["metabolic_adaptation"]["estimated_base_tdee"] == 3758


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


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (ADR-104/105, P1, mcp/tools_nutrition.py:791-796 _get_metabolic_adaptation): "
        "`weekly_deficit = (base_tdee - wd['avg_cal']) * 7` charges every ISO week a FULL SEVEN "
        "DAYS of deficit regardless of how many days were actually logged — and `cal_days` is "
        "computed two blocks earlier and sits unused in the very dict being iterated. With 2 logged "
        "days a week the expected loss is inflated 3.5x (8.0 lb instead of 2.3 lb) against an "
        "actual 2.1 lb, so the adaptation ratio collapses from an honest 0.91 ('NONE - tracking "
        "close to expected') to 0.26 -> SEVERE: 'plateau territory... 2-3 week reverse diet... "
        "check thyroid markers (TSH, T3, T4) at next blood draw.' Partial logging alone "
        "manufactures a metabolic-suppression diagnosis and a medical follow-up. Who it hurts: "
        "anyone who logs some days and not others, which is everyone."
    ),
)
def test_metabolic_adaptation_scales_the_expected_deficit_to_the_days_actually_logged(monkeypatch):
    install(monkeypatch, adapt_rows(days_per_week=2))
    out = tn._get_metabolic_adaptation(ADAPT_ARGS)
    # 8 weeks * (2500 - 2000) kcal * 2 logged days = 8000 kcal / 3500 = 2.3 lb expected
    assert out["metabolic_adaptation"]["expected_loss_lbs"] == 2.3
    assert out["metabolic_adaptation"]["actual_loss_lbs"] == 2.1
    assert out["metabolic_adaptation"]["severity"] == "NONE"


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (ADR-105, P2, mcp/tools_nutrition.py:812-819 _get_metabolic_adaptation): "
        "`recent_rates = weekly_data[-4:]` and `early_rates = weekly_data[1:5]` are published as "
        "`recent_avg_lbs_per_week` vs `early_avg_lbs_per_week` with a `rate_slowdown_pct` between "
        "them — but below eight weeks those slices OVERLAP, and at the three-week minimum the tool "
        "accepts they are the IDENTICAL two weeks. The result is a 0.0% slowdown presented as a "
        "measured comparison of two periods that are the same period. Should be None until the "
        "windows are disjoint."
    ),
)
def test_metabolic_adaptation_gives_no_slowdown_when_early_and_recent_overlap(monkeypatch):
    rows = []
    for wi, monday in enumerate(_MONDAYS[5:]):  # three ISO weeks
        rows += [mf(d(monday, o), total_calories_kcal=2000) for o in range(5)]
        rows.append(withings(monday, weight_lbs=[319.9, 319.0, 318.0][wi]))
    rows.append(withings(d(_MONDAYS[5], 1), weight_lbs=319.9))  # 4th weigh-in
    install(monkeypatch, rows)
    out = tn._get_metabolic_adaptation(ADAPT_ARGS)
    assert out["period"]["weeks_analysed"] == 3
    assert out["rate_analysis"]["rate_slowdown_pct"] is None


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (ADR-104, P2, mcp/tools_nutrition.py:800-801 + 842-849 _get_metabolic_adaptation): "
        "`adaptation_ratio = actual_loss / expected_loss` goes NEGATIVE when weight went up, falls "
        "through every band to SEVERE, and is then interpolated into "
        "f'Losing only {round(ratio*100)}% of expected' — so a 1.9 lb GAIN is reported as 'Losing "
        "only -63% of expected'. The severity happens to be right; the sentence is nonsense, and it "
        "is the sentence a reader quotes. A gain needs its own branch."
    ),
)
def test_metabolic_adaptation_does_not_describe_a_weight_gain_as_losing(monkeypatch):
    rows = []
    for wi, monday in enumerate(_MONDAYS[5:]):
        rows += [mf(d(monday, o), total_calories_kcal=2000) for o in range(5)]
        rows.append(withings(monday, weight_lbs=[320.0, 321.0, 322.0][wi]))
    rows.append(withings(d(_MONDAYS[5], 1), weight_lbs=320.2))
    install(monkeypatch, rows)
    out = tn._get_metabolic_adaptation(ADAPT_ARGS)
    assert out["metabolic_adaptation"]["actual_loss_lbs"] < 0
    assert "Losing only -" not in out["recommendation"]


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
