"""tests/test_site_api_meals_behavior.py — behavioral contracts for the four
reader-facing meal endpoints served by ``lambdas/web/site_api_meals.py``:

    GET /api/protein_sources          (protein_sources)
    GET /api/frequent_meals           (frequent_meals)
    GET /api/meal_glucose             (meal_glucose)
    GET /api/food_delivery_overview   (food_delivery_overview)

(``/api/meal_responses`` was retired by #2327 — SOURCE#meal_responses was a dead
partition with no writer, queried on every glucose-door load.)

These are the numbers a human reader sees on averagejoematt.com's nutrition and
glucose doors: which foods actually carry the protein, what gets eaten over and
over, which meals move glucose, and how often food arrives by delivery. The
contracts pinned here are the ones a reader — and the front-end binding that
serves them (`site/assets/js/evidence_nutrition.js`,
`site/legacy/{nutrition,glucose}/index.html`) — depends on:

  * ADR-104 honest numbers — an unmeasurable meal is ABSENT, never a factual 0
    and never a fabricated curve shape.
  * ADR-105 rigor — the n behind an average ships beside it.
  * #1917 window-name honesty — a field named for an N-day window either spans a
    real N days or carries no value; the registry that decides which keys are
    INTENSIVE vs EXTENSIVE is `web.window_registry`, and this file DERIVES its
    expectations from it rather than restating a list ("guard the SET").
  * Envelope parity — the empty-state payload must publish the same keys the
    populated one does, or a front-end binding written against real data breaks
    the moment the platform is quiet (this is exactly the shape that broke the
    nutrition door after a cycle reset).
  * Privacy — food delivery / binge frequency is PRIVATE-by-default elsewhere in
    the serving path (`site_api_nutrition._DELIVERY_PUBLIC`, P2.3).

Everything is driven through the real handler with the facade's injection surface
(`_g`) supplied by hand, a frozen clock, and hand-rolled bounded fakes — never a
MagicMock inside a pagination-shaped read, never a real AWS or HTTP call.

Arithmetic expectations are hand-derived in the test body and written as literals
with the derivation shown in a comment — never "whatever the code returned".

CLOCK CAVEAT (a real property of the module, asserted in §5): ``frequent_meals``
and ``meal_glucose`` re-import ``datetime`` INSIDE the function body, which
shadows the module-level binding — so ``monkeypatch.setattr(meals, "datetime",
...)`` cannot reach them. Content tests for those two therefore use a source fake
with window filtering switched off, and assert the window separately from the
call the handler actually recorded.
"""

from __future__ import annotations

import inspect
import json
from datetime import datetime, timedelta, timezone

import pytest
from web import site_api_common as sac, site_api_meals as meals
from web.window_registry import INTENSIVE, REGISTRY

# ──────────────────────────────────────────────────────────────────────────────
# Frozen clock
# ──────────────────────────────────────────────────────────────────────────────

DEFAULT_NOW = datetime(2026, 5, 10, 17, 40, 0, tzinfo=timezone.utc)  # 10:40 PT — same PT/UTC date
_FROZEN = [DEFAULT_NOW]

TODAY = "2026-05-10"
# #2338: the INCLUSIVE start of a 30-day window ending TODAY — TODAY - 29, not
# TODAY - 30. `_query_source`/`between` are inclusive on both ends, so [D30, TODAY]
# is exactly 30 calendar dates.
D30 = "2026-04-11"
GENESIS_FAR = "2026-01-01"  # far enough back that no 30-day window is genesis-clamped


class _FrozenDatetime(datetime):
    """``datetime`` subclass with a pinned ``now()``.

    A subclass rather than a Mock so ``strptime``, ``timedelta`` arithmetic and
    ``.astimezone()`` — all of which the code under test uses on the same name —
    keep working. ``site_api_common`` calls ``now(timezone.utc)`` for the raw
    lookback and ``now(PT)`` for the today-clamp; both resolve through this.
    """

    @classmethod
    def now(cls, tz=None):
        if tz is None:
            return _FROZEN[0].replace(tzinfo=None)
        return _FROZEN[0].astimezone(tz)

    @classmethod
    def utcnow(cls):
        return _FROZEN[0].replace(tzinfo=None)


def freeze(dt: datetime) -> None:
    """Move the pinned clock (both the module's and site_api_common's)."""
    _FROZEN[0] = dt


# ──────────────────────────────────────────────────────────────────────────────
# Bounded hand-rolled fakes
# ──────────────────────────────────────────────────────────────────────────────


def _date_of(rec: dict) -> str:
    return rec.get("date") or str(rec.get("sk", "")).replace("DATE#", "")


class FakeSources:
    """Stand-in for ``site_api_common._query_source``.

    Faithful to the real thing where the handlers depend on it: it filters to the
    requested inclusive ``[start, end]`` window (the real one issues an
    ``sk BETWEEN``), returns ``[]`` when ``start > end`` (the future-genesis
    guard), hands back a fresh copy of each row, returns ``[]`` for an unknown
    source, and records every call so a test can assert which partitions were —
    and, for privacy, were NOT — read.

    ``filter_window=False`` disables the date filter. Needed only for the two
    handlers whose clock cannot be frozen (see the module docstring): their
    window is asserted from ``.calls`` instead.
    """

    def __init__(self, *, filter_window: bool = True, raises: Exception | None = None, **by_source):
        self.data = {k: list(v) for k, v in by_source.items()}
        self.calls: list[tuple[str, str, str]] = []
        self.filter_window = filter_window
        self.raises = raises

    def __call__(self, source, start, end, include_pilot=False):
        self.calls.append((source, start, end))
        if self.raises is not None:
            raise self.raises
        if start > end:
            return []
        rows = self.data.get(source, [])
        if self.filter_window:
            rows = [r for r in rows if start <= _date_of(r) <= end]
        return [dict(r) for r in rows]

    @property
    def sources_read(self) -> set[str]:
        return {c[0] for c in self.calls}

    def window_for(self, source: str) -> tuple[str, str]:
        for s, start, end in self.calls:
            if s == source:
                return start, end
        raise AssertionError(f"{source!r} was never queried; calls={self.calls}")


def mf(date: str, *food_log, **fields) -> dict:
    """A MacroFactor day record keyed the way the real partition keys it."""
    rec = {"pk": "USER#matthew#SOURCE#macrofactor", "sk": f"DATE#{date}", **fields}
    if food_log:
        rec["food_log"] = list(food_log)
    return rec


def food(name, protein_g=0, calories_kcal=0, carbs_g=0, fat_g=0, **extra) -> dict:
    return {
        "food_name": name,
        "protein_g": protein_g,
        "calories_kcal": calories_kcal,
        "carbs_g": carbs_g,
        "fat_g": fat_g,
        **extra,
    }


def cgm(date: str, avg=None, peak=None, low=None, tir=None) -> dict:
    rec: dict = {"pk": "USER#matthew#SOURCE#apple_health", "sk": f"DATE#{date}"}
    if avg is not None:
        rec["blood_glucose_avg"] = avg
    if peak is not None:
        rec["blood_glucose_max"] = peak
    if low is not None:
        rec["blood_glucose_min"] = low
    if tir is not None:
        rec["blood_glucose_time_in_range_pct"] = tir
    return rec


def delivery(date: str, amount=0.0, platform="DoorDash", **extra) -> dict:
    return {"pk": "USER#matthew#SOURCE#food_delivery", "sk": f"DATE#{date}", "amount": amount, "platform": platform, **extra}


@pytest.fixture(autouse=True)
def _frozen_and_isolated(monkeypatch):
    """Freeze both clocks the handlers observe, pin genesis, and clear the
    module-level request-id cache.

    * ``meals.datetime`` is what ``protein_sources`` / ``food_delivery_overview``
      call ``now()`` on.
    * ``sac.datetime`` is what the REAL ``_experiment_date`` / ``_clamp_today``
      call it on — and the tests hand the handlers the real ``_experiment_date``
      rather than a reimplementation, so the genesis-clamp semantics exercised
      here are the shipped ones.
    * ``sac._current_request_id`` is MODULE-LEVEL MUTABLE STATE shared by every
      ``_ok``/``_error`` in the process. A test that sets it would leak the id
      into every later test's headers, so it is reset both before and after.
    * The pinned clock itself is module-level (``_FROZEN``) so a test can move it;
      it is restored to the default here for the same reason.
    """
    freeze(DEFAULT_NOW)
    sac.set_request_id(None)
    monkeypatch.setattr(meals, "datetime", _FrozenDatetime)
    monkeypatch.setattr(sac, "datetime", _FrozenDatetime)
    monkeypatch.setattr(sac, "EXPERIMENT_START", GENESIS_FAR)
    yield
    sac.set_request_id(None)
    freeze(DEFAULT_NOW)


@pytest.fixture
def delivery_public(monkeypatch):
    """Opt IN to the ungated food-delivery reader.

    `/api/food_delivery_overview` ships PRIVATE-by-default (#2209/#2210): with
    `NUTRITION_DELIVERY_PUBLIC` unset the handler returns `{"food_delivery": None}`
    and never queries the partition. Every test below that asserts on delivery
    *content* — counts, spend, binge days, platform breakdown, weekly trend — is
    exercising the flag-ON path, so it must say so explicitly. Without this,
    those tests do not fail on the shipped default; they read `None` and raise.

    `_DELIVERY_PUBLIC` is a module-level constant computed at IMPORT time
    (`site_api_meals.py:29`), so the env var is already frozen by the time a test
    runs — patch the module attribute, never the environment.

    Tests that pin the GATE itself (`test_food_delivery_respects_the_same_privacy
    _flag_its_sibling_endpoint_does`) deliberately do NOT take this fixture.
    """
    monkeypatch.setattr(meals, "_DELIVERY_PUBLIC", True)


def make_g(sources: FakeSources | None = None) -> dict:
    """The facade's injection surface, hand-built.

    Mirrors what ``site_api_observatory.handle_*`` passes (`globals()`): the
    names every handler in this module reads off ``_g``.
    """
    return {
        "_query_source": sources if sources is not None else FakeSources(),
        "_experiment_date": sac._experiment_date,
    }


def body_of(resp: dict) -> dict:
    assert resp["statusCode"] == 200, resp
    return json.loads(resp["body"])


def call(name: str, sources=None) -> dict:
    return body_of(HANDLERS[name](_g=make_g(sources)))


# ──────────────────────────────────────────────────────────────────────────────
# The handler SET, derived from the module (never a hand-typed list)
# ──────────────────────────────────────────────────────────────────────────────


def _discover_handlers() -> dict:
    """Every public endpoint function this module defines.

    Derived, not enumerated: a sixth meal endpoint added to site_api_meals joins
    every envelope contract below automatically instead of shipping untested.
    The signature shape (`*, _g`) is what the facade delegators call.
    """
    out = {}
    for name, obj in vars(meals).items():
        if name.startswith("_") or not inspect.isfunction(obj) or obj.__module__ != meals.__name__:
            continue
        params = inspect.signature(obj).parameters
        if "_g" in params and params["_g"].kind is inspect.Parameter.KEYWORD_ONLY:
            out[name] = obj
    return out


HANDLERS = _discover_handlers()


def _scan_window_keys() -> set[str]:
    """Every published `_Nd`-style JSON key this module emits, found structurally.

    Deliberately an AST walk over dict-display keys rather than a regex over the
    source: a regex also matches window names in comments, docstrings and local
    variables, none of which a reader ever sees. Same technique — and the same
    `WINDOW_KEY` pattern — as tests/test_window_name_honesty_1917.py, so the two
    guards agree on what counts as a published window field.
    """
    import ast
    import pathlib

    from web.window_registry import WINDOW_KEY

    src = pathlib.Path(inspect.getfile(meals)).read_text()
    found = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Dict):
            for k in node.keys:
                if isinstance(k, ast.Constant) and isinstance(k.value, str) and WINDOW_KEY.match(k.value):
                    found.add(k.value)
    return found


_MODULE_WINDOW_KEYS = _scan_window_keys()
# The intensive, un-gapped subset — averages/rates whose `_Nd` name is a claim
# about N days of data, with no issue-linked `gap` excusing them.
_MODULE_INTENSIVE_WINDOW_KEYS = {k for k in _MODULE_WINDOW_KEYS if k in REGISTRY and REGISTRY[k][0] is INTENSIVE and REGISTRY[k][1] is None}
_MODULE_EXTENSIVE_WINDOW_KEYS = {k for k in _MODULE_WINDOW_KEYS if k in REGISTRY and REGISTRY[k][0] is not INTENSIVE}


def test_every_window_named_key_this_module_publishes_is_classified_in_the_registry():
    """The precondition for both guards below: an unregistered `_Nd` key would
    make them silently vacuous."""
    assert _MODULE_WINDOW_KEYS, "the AST scan found nothing — the technique has drifted from the source"
    assert not (_MODULE_WINDOW_KEYS - set(REGISTRY)), f"unclassified: {sorted(_MODULE_WINDOW_KEYS - set(REGISTRY))}"


# A populated `_g` per endpoint, used by the envelope-parity contracts. The
# ASSERTIONS are derived (a set difference between two live payloads); this table
# only supplies enough data to reach each handler's populated branch.
def _populated_g(name: str) -> dict:
    if name == "protein_sources":
        return make_g(FakeSources(macrofactor=[mf("2026-04-15", food("Chicken Breast", protein_g=40, calories_kcal=200))]))
    if name == "frequent_meals":
        return make_g(FakeSources(filter_window=False, macrofactor=[mf("2026-04-15", food("Eggs", protein_g=18, calories_kcal=200))]))
    if name == "meal_glucose":
        return make_g(
            FakeSources(
                filter_window=False,
                macrofactor=[mf("2026-04-15", food("Pizza", protein_g=30, calories_kcal=800, carbs_g=90))],
                apple_health=[cgm("2026-04-15", avg=100, peak=140, low=80, tir=85)],
            )
        )
    if name == "food_delivery_overview":
        return make_g(FakeSources(food_delivery=[delivery("2026-04-15", amount=24.5)]))
    raise AssertionError(f"no populated fixture registered for new handler {name!r} — add one")


def test_every_endpoint_this_module_defines_has_a_populated_fixture():
    """The derived-SET guard's own guard: a new handler must be given data here,
    or every parity contract below would silently skip it."""
    for name in HANDLERS:
        assert _populated_g(name), name


# ──────────────────────────────────────────────────────────────────────────────
# 1. HTTP envelope — what CloudFront and the browser see
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("name", sorted(HANDLERS))
def test_every_meal_endpoint_answers_200_on_a_platform_with_no_data(name):
    """A quiet platform (genesis week, or a reset) must never surface an error to
    a reader — the page renders an empty state, not a broken door."""
    assert HANDLERS[name](_g=make_g())["statusCode"] == 200


@pytest.mark.parametrize("name", sorted(HANDLERS))
def test_every_meal_endpoint_returns_a_json_object_the_browser_can_parse(name):
    parsed = json.loads(HANDLERS[name](_g=make_g())["body"])
    assert isinstance(parsed, dict)


@pytest.mark.parametrize("name", sorted(HANDLERS))
def test_every_meal_endpoint_declares_json_and_the_browser_security_headers(name):
    """Derived from CORS_HEADERS itself: the site is served cross-origin from
    CloudFront, so a handler that hand-rolls its headers must still ship the full
    set. Deriving means a NEW security header added to CORS_HEADERS is enforced
    here on day one."""
    headers = HANDLERS[name](_g=make_g())["headers"]
    for key, value in sac.CORS_HEADERS.items():
        assert headers.get(key) == value, f"{name} dropped {key}"


@pytest.mark.parametrize("name", sorted(HANDLERS))
def test_every_meal_endpoint_sets_an_explicit_cache_control(name):
    """These are CDN-fronted GETs; an absent Cache-Control means CloudFront
    guesses, and the reader gets either a stale page or an origin stampede."""
    assert HANDLERS[name](_g=make_g())["headers"].get("Cache-Control")


@pytest.mark.parametrize("name", sorted(HANDLERS))
def test_no_meal_endpoint_raises_when_its_data_source_is_completely_empty(name):
    """Belt-and-braces on the empty path: an exception here becomes a 502 at the
    Function URL, which is what the site smoke test rolls the fleet back for."""
    HANDLERS[name](_g=make_g())


def test_a_populated_protein_page_is_cached_for_an_hour():
    resp = meals.protein_sources(_g=_populated_g("protein_sources"))
    assert resp["headers"]["Cache-Control"] == "public, max-age=3600, s-maxage=3600"
    assert json.loads(resp["body"])["_meta"]["cache_seconds"] == 3600


def test_the_empty_protein_page_is_cached_only_briefly_so_first_data_appears_fast():
    """Genesis week: a short TTL so the page stops saying "nothing yet" as soon as
    the first upload lands, rather than an hour later."""
    resp = meals.protein_sources(_g=make_g())
    assert resp["headers"]["Cache-Control"] == "public, max-age=300, s-maxage=300"


def test_frequent_meals_and_meal_glucose_cache_for_an_hour():
    for fn in (meals.frequent_meals, meals.meal_glucose):
        assert fn(_g=make_g())["headers"]["Cache-Control"] == "public, max-age=3600, s-maxage=3600"


@pytest.mark.parametrize("name", sorted(HANDLERS))
def test_every_ok_enveloped_endpoint_publishes_generated_at_so_the_reader_can_date_the_page(name):
    meta = json.loads(HANDLERS[name](_g=make_g())["body"])["_meta"]
    assert meta["generated_at"].startswith("2026-05-10T17:40")


@pytest.mark.parametrize("name", sorted(HANDLERS))
def test_a_request_id_set_by_the_lambda_is_echoed_back_for_support_correlation(name):
    """`set_request_id` is how a reader-reported "this page is wrong" is tied to a
    CloudWatch line. Every `_ok` response echoes it."""
    sac.set_request_id("req-abc-123")
    resp = HANDLERS[name](_g=make_g())
    assert resp["headers"].get("x-request-id") == "req-abc-123"


# ──────────────────────────────────────────────────────────────────────────────
# 2. Empty-state / populated-state key parity
#
# The failure this guards: a front-end binding written against the populated
# payload (`d.weekly_trend.map(...)`, `d.protein_sources.slice(...)`) throws the
# moment the platform goes quiet — which is precisely what happens on Day 1 of
# every cycle reset. The assertion is a SET DIFFERENCE between two live payloads,
# not a hand-typed key list.
# ──────────────────────────────────────────────────────────────────────────────


def _data_keys(payload: dict) -> set[str]:
    return set(payload) - {"_meta"}


@pytest.mark.parametrize(
    "name",
    [
        "frequent_meals",
        "meal_glucose",
        "protein_sources",
        "food_delivery_overview",
    ],
)
def test_the_empty_state_publishes_every_key_the_populated_state_does(delivery_public, name):
    """FIXED (#2221). `protein_sources` used to publish a COMPLETELY DISJOINT
    empty-state payload — populated `{protein_sources, total_protein_*,
    days_analyzed}` vs empty `{sources, as_of_date}`, zero keys in common — and
    `food_delivery_overview` dropped `platform_breakdown`/`weekly_trend` on a
    quiet window. Both now build their payload through one shape.

    NB this runs with the delivery gate ON. The gate-OFF payload is deliberately
    the bare `{"food_delivery": None}` and is pinned as such by
    tests/test_food_delivery_gate_2209.py — parity is a contract of the PUBLISHED
    endpoint, not a licence to emit delivery-shaped keys while it is private."""
    empty = _data_keys(body_of(HANDLERS[name](_g=make_g())))
    populated = _data_keys(body_of(HANDLERS[name](_g=_populated_g(name))))
    missing = populated - empty
    assert not missing, f"{name}: empty-state payload omits {sorted(missing)} that the populated one publishes"


def test_protein_sources_publishes_as_of_date_only_when_it_has_nothing_to_say():
    """The inverse half of the same divergence, pinned separately because it is
    the one a "last updated" caption would bind to: `as_of_date` exists ONLY on
    the empty payload, so the caption vanishes exactly when data arrives."""
    assert "as_of_date" in call("protein_sources")
    assert "as_of_date" not in body_of(meals.protein_sources(_g=_populated_g("protein_sources")))


def test_frequent_meals_keeps_publishing_its_period_when_there_are_no_meals():
    b = call("frequent_meals")
    assert b["meals"] == [] and b["period_days"] == 30


def test_meal_glucose_keeps_publishing_has_cgm_when_there_are_no_meals():
    b = call("meal_glucose")
    assert b["meals"] == [] and b["has_cgm"] is False and b["period_days"] == 30


# ──────────────────────────────────────────────────────────────────────────────
# 3. ADR-104 — absence is never a factual number
# ──────────────────────────────────────────────────────────────────────────────


def test_an_empty_delivery_window_reports_absence_rather_than_zero_orders(delivery_public):
    """ "0 orders in 30 days" is a *claim of abstinence*. The honest answer when
    the partition is empty is "no delivery record", which is what `None` says."""
    assert call("food_delivery_overview")["food_delivery"] is None


def test_a_meal_with_no_cgm_coverage_is_graded_unknown_rather_than_good():
    """Grade "?" is the honest verdict for a meal eaten on a day the sensor was
    off — a reader must not read it as "this meal is fine"."""
    src = FakeSources(filter_window=False, macrofactor=[mf("2026-04-15", food("Oatmeal", calories_kcal=350, carbs_g=60))])
    meal = call("meal_glucose", src)["meals"][0]
    assert meal["grade"] == "?"


def test_a_meal_with_no_glucose_sample_reports_an_absent_spike_not_a_zero_rise():
    """FIXED (#2221). `meal_glucose` published `avg_spike if avg_spike is not None
    else 0` — an unmeasurable meal (no CGM coverage that day, or carbs <= 5 g so no
    spike sample was taken) shipped spike=0, i.e. "this meal produced no glucose
    rise". The grade field was already honest ("?"), so one payload said both
    "unknown" and "0 mg/dL rise"."""
    src = FakeSources(filter_window=False, macrofactor=[mf("2026-04-15", food("Oatmeal", calories_kcal=350, carbs_g=60))])
    meal = call("meal_glucose", src)["meals"][0]
    assert meal["spike"] is None, "an unmeasured spike must be absent, not 0"


def test_an_unmeasured_meal_does_not_borrow_the_curve_shape_of_a_good_one():
    """FIXED (#2221): the unmeasured curve is now "unknown". It used to be
    "gentle" — the SAME string a genuinely gentle grade-B meal (spike 16-25 mg/dL)
    gets, so an unmeasured meal was indistinguishable from a measured-and-good one
    in the field a chart binds its shape to."""
    src = FakeSources(
        filter_window=False,
        macrofactor=[
            mf("2026-04-15", food("Unmeasured", calories_kcal=350, carbs_g=60)),
            mf("2026-04-16", food("GenuinelyGentle", calories_kcal=350, carbs_g=60)),
        ],
        # only 04-16 has sensor coverage; peak-avg = 20 -> 20*0.8 = 16 -> grade B / gentle
        apple_health=[cgm("2026-04-16", avg=100, peak=120, low=90, tir=90)],
    )
    by_name = {m["meal"]: m for m in call("meal_glucose", src)["meals"]}
    assert by_name["GenuinelyGentle"]["curve"] == "gentle"
    assert by_name["Unmeasured"]["curve"] != "gentle", "unknown must not share the shape word with a measured good meal"


def test_a_synced_day_with_no_food_logged_is_excluded_from_the_protein_average():
    """FIXED (#2221). The denominator was `len(items)` — EVERY macrofactor row in
    the window, including rows carrying no `food_log` at all (a day the source
    synced but no meals were entered). Those days added 0 to the numerator and 1
    to the denominator, publishing a lower protein average as fact and dragging
    the ADR-105 n away from the days actually measured.

    NB the exclusion is on `food_log` PRESENCE, not on qualifying protein: a day
    on which only olive oil was logged IS a measured day that carried ~0 g of
    qualifying protein, and it stays in the denominator (see
    test_zero_protein_foods_are_dropped_rather_than_listed_as_zero_contributors)."""
    src = FakeSources(
        macrofactor=[
            mf("2026-04-15", food("Chicken Breast", protein_g=60, calories_kcal=300)),
            mf("2026-04-16"),  # synced, nothing logged — food_log absent entirely
            mf("2026-04-17"),
        ]
    )
    b = call("protein_sources", src)
    # Hand-derived: only ONE day carries measured protein, so the honest average is
    # 60 / 1 = 60.0 g/day over n=1 — not 60 / 3 = 20.0 g/day over n=3.
    assert b["days_analyzed"] == 1
    assert b["total_protein_avg_g"] == 60.0


def test_a_food_with_no_calorie_figure_reports_an_absent_protein_calorie_share():
    """FIXED (#2221): `... if total_cal > 0 else None`. It used to be `else 0` —
    "none of this food's calories are protein", the exact inverse of the truth for
    a hand-entered pure-protein whole food.

    The `frequent_meals` sibling shipped 0 for the same situation until #2330
    flipped it (paired with the legacy nutrition page's grade rendering); the two
    endpoints' agreement on None is pinned by
    test_frequent_meals_and_protein_sources_agree_on_the_absence_value."""
    src = FakeSources(macrofactor=[mf("2026-04-15", {"food_name": "Chicken Breast", "protein_g": 40})])
    assert call("protein_sources", src)["protein_sources"][0]["protein_cal_pct"] is None


def test_zero_protein_foods_are_dropped_rather_than_listed_as_zero_contributors():
    """A protein-sources table exists to name what carries the protein; listing
    olive oil at 0 g would be noise, not honesty."""
    src = FakeSources(
        macrofactor=[mf("2026-04-15", food("Olive Oil", protein_g=0, calories_kcal=120), food("Steak", protein_g=45, calories_kcal=400))]
    )
    assert [s["food"] for s in call("protein_sources", src)["protein_sources"]] == ["Steak"]


def test_a_sub_gram_protein_food_is_dropped_at_the_one_gram_floor():
    """`pro < 1` is the published floor. 0.9 g of protein in a condiment is not a
    protein source; 1.0 g in a supplement is on the boundary and stays."""
    src = FakeSources(
        macrofactor=[
            mf("2026-04-15", food("Ketchup", protein_g=0.9, calories_kcal=20), food("Bone Broth", protein_g=1.0, calories_kcal=40))
        ]
    )
    assert [s["food"] for s in call("protein_sources", src)["protein_sources"]] == ["Bone Broth"]


# ──────────────────────────────────────────────────────────────────────────────
# 4. Aggregation arithmetic — every expectation hand-derived
# ──────────────────────────────────────────────────────────────────────────────

# Three logged days. Derivations are written out beside each assertion.
PROTEIN_FIXTURE = FakeSources(
    macrofactor=[
        mf(
            "2026-04-15",
            food("Chicken Breast", protein_g=40, calories_kcal=200),
            food("Rice", protein_g=5, calories_kcal=300),
            food("Olive Oil", protein_g=0, calories_kcal=120),  # dropped: protein < 1 g
            food("Ok", protein_g=30, calories_kcal=100),  # dropped: name shorter than 3 chars
        ),
        mf("2026-04-16", food("Chicken Breast", protein_g=30, calories_kcal=160), food("Rice", protein_g=5, calories_kcal=300)),
        mf(
            "2026-04-17",
            food("  Chicken Breast  ", protein_g=20, calories_kcal=140),  # whitespace-padded: must merge
            food("Whey Shake", protein_g=25, calories_kcal=120),
        ),
    ]
)


def _protein_rows() -> dict:
    return {s["food"]: s for s in call("protein_sources", PROTEIN_FIXTURE)["protein_sources"]}


def test_protein_sources_are_ranked_by_total_contribution_not_by_frequency():
    """Whey Shake appears once (25 g); Rice appears twice (10 g total). The table
    answers "what carries my protein", so Whey outranks Rice."""
    order = [s["food"] for s in call("protein_sources", PROTEIN_FIXTURE)["protein_sources"]]
    assert order == ["Chicken Breast", "Whey Shake", "Rice"]


def test_the_same_food_logged_with_stray_whitespace_is_one_row_not_two():
    """MacroFactor entries are hand-typed; "  Chicken Breast  " and "Chicken
    Breast" are the same food and must not split the reader's top row in half."""
    rows = _protein_rows()
    assert "Chicken Breast" in rows and rows["Chicken Breast"]["frequency"] == 3


def test_average_daily_grams_divides_total_protein_by_days_logged():
    # Chicken Breast: 40 + 30 + 20 = 90 g over 3 logged days -> 90/3 = 30.0 g/day
    assert _protein_rows()["Chicken Breast"]["avg_daily_g"] == 30.0
    # Rice: 5 + 5 = 10 g over 3 logged days -> 10/3 = 3.333 -> 3.3
    assert _protein_rows()["Rice"]["avg_daily_g"] == 3.3


def test_percent_of_total_is_the_share_of_all_qualifying_protein():
    # total qualifying protein = 90 (chicken) + 10 (rice) + 25 (whey) = 125 g
    rows = _protein_rows()
    assert rows["Chicken Breast"]["pct_of_total"] == 72.0  # 90/125 = 72.0%
    assert rows["Whey Shake"]["pct_of_total"] == 20.0  # 25/125 = 20.0%
    assert rows["Rice"]["pct_of_total"] == 8.0  # 10/125 =  8.0%


def test_the_published_percentages_sum_to_one_hundred_so_the_share_chart_closes():
    """A donut/stacked bar bound to `pct_of_total` must not leave a phantom
    wedge. With three foods and no 12-row truncation the shares are exhaustive."""
    assert round(sum(s["pct_of_total"] for s in call("protein_sources", PROTEIN_FIXTURE)["protein_sources"]), 1) == 100.0


def test_average_protein_per_serving_divides_by_servings_not_by_days():
    """The reader's "how much do I get each time I eat this" figure — a different
    denominator from avg_daily_g, and the two are published side by side."""
    rows = _protein_rows()
    assert rows["Chicken Breast"]["avg_protein_per_serving"] == 30.0  # 90 g / 3 servings
    assert rows["Rice"]["avg_protein_per_serving"] == 5.0  # 10 g / 2 servings
    assert rows["Whey Shake"]["avg_protein_per_serving"] == 25.0  # 25 g / 1 serving


def test_protein_calorie_share_uses_four_calories_per_gram():
    rows = _protein_rows()
    assert rows["Chicken Breast"]["protein_cal_pct"] == 72  # (90*4)/500 kcal  = 72%
    assert rows["Rice"]["protein_cal_pct"] == 7  # (10*4)/600 kcal  = 6.67 -> 7%
    assert rows["Whey Shake"]["protein_cal_pct"] == 83  # (25*4)/120 kcal  = 83.3 -> 83%


def test_days_analyzed_is_the_sample_size_behind_every_average_on_the_page():
    """ADR-105: the n ships with the number. Three logged days here."""
    assert call("protein_sources", PROTEIN_FIXTURE)["days_analyzed"] == 3


def test_the_platform_wide_protein_average_is_total_over_days_logged():
    # 125 g of qualifying protein across 3 logged days -> 41.666 -> 41.7 g/day
    assert call("protein_sources", PROTEIN_FIXTURE)["total_protein_avg_g"] == 41.7


def test_the_protein_table_is_capped_at_twelve_rows_so_the_page_stays_readable():
    """Fifteen distinct foods, descending contribution — the reader gets the top
    twelve, and the cap fires exactly at twelve (not eleven, not thirteen)."""
    entries = [food(f"Protein Food {i:02d}", protein_g=100 - i, calories_kcal=200) for i in range(15)]
    b = call("protein_sources", FakeSources(macrofactor=[mf("2026-04-15", *entries)]))
    assert len(b["protein_sources"]) == 12
    assert b["protein_sources"][0]["food"] == "Protein Food 00"  # highest protein first
    assert b["protein_sources"][-1]["food"] == "Protein Food 11"


def test_the_capped_table_still_reports_percentages_of_the_full_total_not_the_visible_rows():
    """The twelve shown are a *sample of the whole*; if pct were renormalised over
    the visible rows the reader would think twelve foods are all the protein."""
    entries = [food(f"Protein Food {i:02d}", protein_g=100 - i, calories_kcal=200) for i in range(15)]
    b = call("protein_sources", FakeSources(macrofactor=[mf("2026-04-15", *entries)]))
    assert sum(s["pct_of_total"] for s in b["protein_sources"]) < 100.0


# ── frequent_meals ────────────────────────────────────────────────────────────

FREQUENT_FIXTURE = FakeSources(
    filter_window=False,
    macrofactor=[
        mf(
            "2026-04-15",
            food("Eggs", protein_g=18, calories_kcal=200, carbs_g=2, fat_g=14),
            food("Oats", protein_g=10, calories_kcal=300, carbs_g=54, fat_g=5),
        ),
        mf("2026-04-16", food("Eggs", protein_g=22, calories_kcal=250, carbs_g=3, fat_g=16)),
        mf("2026-04-17", food("Eggs", protein_g=20, calories_kcal=210, carbs_g=1, fat_g=15)),
    ],
)


def test_frequent_meals_ranks_by_how_often_a_food_is_eaten():
    meals_out = call("frequent_meals", FREQUENT_FIXTURE)["meals"]
    assert [m["name"] for m in meals_out] == ["Eggs", "Oats"]
    assert meals_out[0]["frequency"] == 3


def test_frequent_meal_macros_are_per_serving_averages():
    eggs = call("frequent_meals", FREQUENT_FIXTURE)["meals"][0]
    assert eggs["avg_calories"] == 220  # (200+250+210)/3 = 220
    assert eggs["avg_protein_g"] == 20  # ( 18+ 22+ 20)/3 = 20
    assert eggs["avg_carbs_g"] == 2  # (  2+  3+  1)/3 = 2


def test_frequent_meal_protein_share_is_derived_from_the_rounded_averages_it_publishes():
    """The published triple must be internally consistent — a reader who checks
    `avg_protein_g * 4 / avg_calories` against `protein_cal_pct` has to get the
    printed number back. It does, because the code deliberately divides the
    ALREADY-ROUNDED figures."""
    eggs = call("frequent_meals", FREQUENT_FIXTURE)["meals"][0]
    assert eggs["protein_cal_pct"] == 36  # (20*4)/220 = 36.36 -> 36, and 20/220 are the printed values


def test_the_frequent_meal_table_is_capped_at_eight_rows():
    entries = [food(f"Meal Number {i:02d}", protein_g=10, calories_kcal=200) for i in range(12)]
    assert len(call("frequent_meals", FakeSources(filter_window=False, macrofactor=[mf("2026-04-15", *entries)]))["meals"]) == 8


def test_frequent_meals_drops_short_names_the_same_way_the_protein_table_does():
    """The two tables sit on the same page; a food that qualifies for one and not
    the other would read as a bug to a reader comparing them."""
    src = FakeSources(filter_window=False, macrofactor=[mf("2026-04-15", food("Ok", calories_kcal=500), food("Chili", calories_kcal=500))])
    assert [m["name"] for m in call("frequent_meals", src)["meals"]] == ["Chili"]


def test_a_frequent_meal_with_no_calories_logged_reports_an_absent_protein_share_not_a_crash():
    """FIXED (#2330): `avg_cal > 0` is still the divide-by-zero guard, but the
    absent arm now publishes None, not 0 — a meal whose calories were never
    logged has no protein share to grade (ADR-104). The legacy nutrition page
    renders this as an explicit "not computed" state instead of coercing it
    through `|| 0` into a LOW grade."""
    src = FakeSources(filter_window=False, macrofactor=[mf("2026-04-15", {"food_name": "Mystery Bowl", "protein_g": 30})])
    m = call("frequent_meals", src)["meals"][0]
    assert m["avg_calories"] == 0 and m["protein_cal_pct"] is None


def test_frequent_meals_and_protein_sources_agree_on_the_absence_value():
    """#2330 closed the asymmetry #2221 left behind: the SAME calorie-less food
    must publish the SAME absence value (None) from both endpoints on the page."""
    src = FakeSources(filter_window=False, macrofactor=[mf("2026-04-15", {"food_name": "Chicken Breast", "protein_g": 40})])
    meal = call("frequent_meals", src)["meals"][0]
    source = call("protein_sources", src)["protein_sources"][0]
    assert meal["protein_cal_pct"] is None and source["protein_cal_pct"] is None


def test_a_frequent_meal_with_measured_zero_protein_still_computes_a_real_share():
    """Measured-zero is not absence: calories WERE logged, protein is genuinely
    0% of them — the honest figure is 0 and the page may grade it LOW."""
    src = FakeSources(filter_window=False, macrofactor=[mf("2026-04-15", food("White Rice", protein_g=0, calories_kcal=300))])
    m = call("frequent_meals", src)["meals"][0]
    assert m["avg_calories"] == 300 and m["protein_cal_pct"] == 0


# ── meal_glucose ──────────────────────────────────────────────────────────────


def _glucose_meal(name, carbs, avg=100, peak=140, date="2026-04-15", **entry):
    src = FakeSources(
        filter_window=False,
        macrofactor=[mf(date, food(name, calories_kcal=500, carbs_g=carbs, **entry))],
        apple_health=[cgm(date, avg=avg, peak=peak, low=80, tir=85)],
    )
    return call("meal_glucose", src)["meals"][0]


def test_a_high_carb_meal_is_charged_eighty_percent_of_the_days_glucose_excursion():
    """The published model: daily peak-minus-average is the day's excursion, and a
    >20 g-carb meal is held responsible for 80% of it."""
    # excursion = 140 - 100 = 40 mg/dL; 40 * 0.8 = 32
    assert _glucose_meal("Pizza", carbs=90)["spike"] == 32


def test_a_moderate_carb_meal_is_charged_forty_percent_of_the_same_excursion():
    # excursion = 40 mg/dL; 40 * 0.4 = 16
    assert _glucose_meal("Chicken Salad", carbs=10)["spike"] == 16


def test_a_low_carb_meal_is_not_charged_for_the_days_excursion_at_all():
    """Below 5 g of carbs the meal takes no share — a steak eaten on a day that
    spiked must not be blamed for the spike."""
    assert _glucose_meal("Ribeye", carbs=3)["grade"] == "?"


def test_the_carb_attribution_thresholds_sit_exactly_where_the_code_says():
    """20 g and 5 g are strict `>` boundaries; a meal AT the threshold falls into
    the lower band. Pinned so a `>=` slip cannot silently re-grade the table."""
    assert _glucose_meal("At Twenty", carbs=20)["spike"] == 16  # 20g -> the 0.4 band, not 0.8
    assert _glucose_meal("At Five", carbs=5)["grade"] == "?"  # 5g -> no attribution at all


@pytest.mark.parametrize(
    "excursion,expected_spike,expected_grade,expected_curve",
    [
        (18.75, 15, "A", "flat"),  # 18.75 * 0.8 = 15.0 — the top of the A band
        (20.0, 16, "B", "gentle"),  # 16 — first point above A
        (31.25, 25, "B", "gentle"),  # 25 — the top of the B band
        (32.5, 26, "C", "moderate"),  # 26 — first point above B
        (50.0, 40, "C", "moderate"),  # 40 — the top of the C band
        (51.25, 41, "D", "steep"),  # 41 — first point above C
    ],
)
def test_the_glucose_grade_boundaries_are_exactly_fifteen_twentyfive_and_forty(excursion, expected_spike, expected_grade, expected_curve):
    """These four letters are the loudest thing on the meal table. Each boundary
    is pinned on BOTH sides so an off-by-one comparison flips a test, not a
    reader's understanding of what they ate."""
    m = _glucose_meal("Test Meal", carbs=90, avg=100.0, peak=100.0 + excursion)
    assert (m["spike"], m["grade"], m["curve"]) == (expected_spike, expected_grade, expected_curve)


def test_meals_under_a_hundred_calories_are_excluded_as_condiments():
    """Seasonings and splashes of milk would otherwise dominate the frequency
    ranking and get graded on a spike they had nothing to do with."""
    src = FakeSources(
        filter_window=False,
        macrofactor=[mf("2026-04-15", food("Hot Sauce", calories_kcal=5, carbs_g=1), food("Burrito", calories_kcal=700, carbs_g=80))],
    )
    assert [m["meal"] for m in call("meal_glucose", src)["meals"]] == ["Burrito"]


def test_the_calorie_floor_is_a_strict_hundred():
    src = FakeSources(
        filter_window=False,
        macrofactor=[
            mf("2026-04-15", food("Ninety Nine", calories_kcal=99, carbs_g=10), food("Exactly Hundred", calories_kcal=100, carbs_g=10))
        ],
    )
    assert [m["meal"] for m in call("meal_glucose", src)["meals"]] == ["Exactly Hundred"]


def test_meal_glucose_applies_the_same_three_character_name_floor_as_the_other_tables():
    """All three meal tables sit within two clicks of each other; a food that is
    graded on the glucose page but missing from the frequency page (or vice
    versa) reads as a bug to anyone comparing them."""
    src = FakeSources(
        filter_window=False,
        macrofactor=[mf("2026-04-15", food("PB", calories_kcal=400, carbs_g=20), food("Pad Thai", calories_kcal=700, carbs_g=90))],
    )
    assert [m["meal"] for m in call("meal_glucose", src)["meals"]] == ["Pad Thai"]


def test_meal_glucose_reports_per_serving_macro_averages_across_repeats():
    src = FakeSources(
        filter_window=False,
        macrofactor=[
            mf("2026-04-15", food("Burrito", protein_g=30, calories_kcal=700, carbs_g=80)),
            mf("2026-04-16", food("Burrito", protein_g=36, calories_kcal=800, carbs_g=90)),
        ],
    )
    m = call("meal_glucose", src)["meals"][0]
    assert m["calories"] == 750 and m["protein"] == 33 and m["carbs"] == 85  # (700+800)/2, (30+36)/2, (80+90)/2


def test_meal_glucose_lists_the_ten_most_frequent_meals():
    days = []
    for i in range(12):
        # meal i is logged (12 - i) times, so frequency is strictly descending
        for d in range(12 - i):
            days.append(mf(f"2026-04-{d + 1:02d}", food(f"Repeat Meal {i:02d}", calories_kcal=500, carbs_g=50)))
    out = call("meal_glucose", FakeSources(filter_window=False, macrofactor=days))["meals"]
    assert len(out) == 10
    assert out[0]["meal"] == "Repeat Meal 00"


def test_the_days_glucose_context_only_attaches_to_meals_eaten_that_same_day():
    """The join is by DATE#. A meal eaten on a sensor-free day must not inherit a
    neighbouring day's excursion."""
    src = FakeSources(
        filter_window=False,
        macrofactor=[
            mf("2026-04-15", food("Covered", calories_kcal=500, carbs_g=90)),
            mf("2026-04-16", food("Uncovered", calories_kcal=500, carbs_g=90)),
        ],
        apple_health=[cgm("2026-04-15", avg=100, peak=140, low=80, tir=85)],
    )
    by_name = {m["meal"]: m for m in call("meal_glucose", src)["meals"]}
    assert by_name["Covered"]["grade"] == "C"
    assert by_name["Uncovered"]["grade"] == "?"


def test_a_sensor_day_with_no_average_reading_does_not_count_as_cgm_coverage():
    """`has_cgm` gates the entire glucose panel in evidence_nutrition.js — when it
    is false the reader gets the designed "sensor not active" ghost state. A row
    that exists but carries no average is not coverage."""
    src = FakeSources(filter_window=False, apple_health=[cgm("2026-04-15", avg=0, peak=0, low=0, tir=0)])
    assert call("meal_glucose", src)["has_cgm"] is False


def test_a_sensor_day_with_a_real_average_does_count_as_cgm_coverage():
    src = FakeSources(filter_window=False, apple_health=[cgm("2026-04-15", avg=104, peak=138, low=82, tir=91)])
    assert call("meal_glucose", src)["has_cgm"] is True


def test_has_cgm_is_true_even_when_no_meals_were_logged_that_month():
    """Sensor state and food logging are independent; conflating them would show
    "sensor not active" to someone wearing one."""
    src = FakeSources(filter_window=False, apple_health=[cgm("2026-04-15", avg=104, peak=138, low=82, tir=91)])
    b = call("meal_glucose", src)
    assert b["meals"] == [] and b["has_cgm"] is True


@pytest.mark.parametrize(
    "time_str,expected",
    [
        ("06:45", "breakfast"),
        ("10:59", "breakfast"),
        ("11:00", "lunch"),
        ("14:30", "lunch"),
        ("15:00", "snack"),
        ("17:59", "snack"),
        ("18:00", "dinner"),
        ("22:15", "dinner"),
    ],
)
def test_a_meals_category_is_derived_from_the_hour_it_was_eaten(time_str, expected):
    assert _glucose_meal("Timed Meal", carbs=50, time=time_str)["category"] == expected


def test_a_meal_logged_without_a_time_is_labelled_generically_rather_than_guessed():
    assert _glucose_meal("Untimed Meal", carbs=50)["category"] == "meal"


def test_an_unparseable_time_leaves_the_category_generic_instead_of_failing_the_page():
    """MacroFactor exports have carried "noon" and "" in this field. One bad
    string must not 503 the whole meal table."""
    assert _glucose_meal("Odd Time", carbs=50, time="noon")["category"] == "meal"


def test_a_repeated_meal_takes_the_category_of_the_last_logged_sitting():
    """Documented quirk, pinned because a reader sees it: `category` is overwritten
    on every entry, so eggs eaten at breakfast four times and once at 7pm are
    labelled "dinner"."""
    src = FakeSources(
        filter_window=False,
        macrofactor=[
            mf("2026-04-15", food("Eggs", calories_kcal=300, carbs_g=2, time="07:30")),
            mf("2026-04-16", food("Eggs", calories_kcal=300, carbs_g=2, time="19:30")),
        ],
    )
    assert call("meal_glucose", src)["meals"][0]["category"] == "dinner"


# ── food_delivery_overview ────────────────────────────────────────────────────

DELIVERY_FIXTURE = FakeSources(
    food_delivery=[
        delivery("2026-04-13", amount=24.50, platform="DoorDash"),
        delivery("2026-04-15", amount=31.25, platform="DoorDash", binge=True),
        delivery("2026-04-20", amount=18.00, platform="Uber Eats"),
        delivery("2026-05-04", amount=12.25, platform=None),
    ]
)


def test_delivery_order_count_is_the_number_of_records_in_the_window(delivery_public):
    assert call("food_delivery_overview", DELIVERY_FIXTURE)["food_delivery"]["orders_30d"] == 4


def test_delivery_spend_totals_and_averages_are_rounded_to_cents(delivery_public):
    fd = call("food_delivery_overview", DELIVERY_FIXTURE)["food_delivery"]
    assert fd["total_spend_30d"] == 86.00  # 24.50 + 31.25 + 18.00 + 12.25
    assert fd["avg_spend"] == 21.50  # 86.00 / 4


def test_binge_days_counts_only_the_records_flagged_as_such(delivery_public):
    assert call("food_delivery_overview", DELIVERY_FIXTURE)["food_delivery"]["binge_days_30d"] == 1


def test_the_platform_breakdown_is_ordered_most_used_first(delivery_public):
    assert call("food_delivery_overview", DELIVERY_FIXTURE)["platform_breakdown"][0] == {"platform": "DoorDash", "count": 2}


def test_the_platform_breakdown_accounts_for_every_order(delivery_public):
    """A pie chart bound to this array must add up to orders_30d, or the reader
    sees a missing slice."""
    b = call("food_delivery_overview", DELIVERY_FIXTURE)
    assert sum(p["count"] for p in b["platform_breakdown"]) == b["food_delivery"]["orders_30d"]


def test_an_order_with_no_platform_recorded_is_labelled_unknown_not_dropped(delivery_public):
    """Dropping it would understate the order count the spend was computed from."""
    names = {p["platform"] for p in call("food_delivery_overview", DELIVERY_FIXTURE)["platform_breakdown"]}
    assert "Unknown" in names


def test_the_weekly_trend_buckets_orders_by_iso_week_in_chronological_order(delivery_public):
    trend = call("food_delivery_overview", DELIVERY_FIXTURE)["weekly_trend"]
    # 2026-04-13 and 2026-04-15 are both ISO week 16; 04-20 is week 17; 05-04 is week 19.
    assert trend == [{"week": "2026-W16", "orders": 2}, {"week": "2026-W17", "orders": 1}, {"week": "2026-W19", "orders": 1}]


def test_a_delivery_record_dated_only_by_its_sort_key_still_lands_in_a_week(delivery_public):
    """The partition carries both a `date` attribute and a `DATE#` sort key
    depending on ingestion generation; neither may drop out of the trend."""
    src = FakeSources(
        food_delivery=[{"pk": "USER#matthew#SOURCE#food_delivery", "sk": "DATE#2026-04-15", "amount": 20.0, "platform": "DoorDash"}]
    )
    assert call("food_delivery_overview", src)["weekly_trend"] == [{"week": "2026-W16", "orders": 1}]


def test_a_record_with_an_unparseable_date_is_kept_in_the_spend_totals(delivery_public):
    """The date parse is guarded; the order still happened and still cost money,
    so dropping it from `total_spend_30d` would understate the reader's number."""
    # filter_window off: the row has no parseable date, so the real DDB range query
    # would have had to return it on its sort key alone — the case under test.
    src = FakeSources(
        filter_window=False,
        food_delivery=[{"pk": "USER#matthew#SOURCE#food_delivery", "sk": "MALFORMED", "amount": 20.0, "platform": "DoorDash"}],
    )
    b = call("food_delivery_overview", src)
    assert b["food_delivery"]["orders_30d"] == 1 and b["food_delivery"]["total_spend_30d"] == 20.0
    assert b["weekly_trend"] == []


def test_a_week_that_straddles_new_year_is_one_bucket_in_chronological_order(delivery_public):
    """FIXED (#2256): the week label is `strftime('%G-W%V')` — ISO year-week paired
    with ISO week number, not the CALENDAR year `%Y`.

    With `%Y-W%V` the SAME ISO week split into two buckets at the boundary
    (2026-12-31 -> '2026-W53', 2027-01-01 -> '2027-W53'), and because the trend is
    sorted lexically by the label, '2027-W53' sorted AFTER '2027-W01' — the January
    chart drew late December to the right of the following week. Both assertions
    below fail against the `%Y` form: the first sees `[1, 1, 1]`, the second an
    out-of-order label list.
    """
    freeze(datetime(2027, 1, 5, 18, 0, 0, tzinfo=timezone.utc))
    src = FakeSources(
        food_delivery=[
            delivery("2026-12-31", amount=20.0),  # ISO 2026-W53
            delivery("2027-01-01", amount=20.0),  # ISO 2026-W53 — same week
            delivery("2027-01-05", amount=20.0),  # ISO 2027-W01
        ]
    )
    trend = call("food_delivery_overview", src)["weekly_trend"]
    assert [t["orders"] for t in trend] == [2, 1], f"the straddling week split into {trend}"
    assert [t["week"] for t in trend] == ["2026-W53", "2027-W01"]
    assert [t["week"] for t in trend] == sorted(t["week"] for t in trend)


# ──────────────────────────────────────────────────────────────────────────────
# 5. Date windows, genesis clamping and Pacific-time semantics
# ──────────────────────────────────────────────────────────────────────────────


def test_protein_sources_reads_exactly_the_clamped_thirty_day_window():
    src = FakeSources()
    meals.protein_sources(_g=make_g(src))
    assert src.window_for("macrofactor") == (D30, TODAY)


def test_food_delivery_reads_exactly_the_clamped_thirty_day_window(delivery_public):
    src = FakeSources()
    meals.food_delivery_overview(_g=make_g(src))
    assert src.window_for("food_delivery") == (D30, TODAY)


def test_a_genesis_inside_the_window_shortens_it_rather_than_reaching_into_the_last_cycle(monkeypatch):
    """ADR-077 "clamped, not hidden": five days into a new cycle the page shows
    five days of food, never the previous experiment's."""
    monkeypatch.setattr(sac, "EXPERIMENT_START", "2026-05-05")
    src = FakeSources()
    meals.protein_sources(_g=make_g(src))
    assert src.window_for("macrofactor") == ("2026-05-05", TODAY)


def test_a_short_window_still_publishes_the_real_average_under_the_window_generic_name(monkeypatch):
    """#1917 half one: the number is true on Day 6, so it is NOT hidden."""
    monkeypatch.setattr(sac, "EXPERIMENT_START", "2026-05-05")
    src = FakeSources(macrofactor=[mf("2026-05-06", food("Chicken Breast", protein_g=50, calories_kcal=250))])
    b = call("protein_sources", src)
    assert b["total_protein_avg_g"] == 50.0  # 50 g over the 1 logged day
    assert b["total_protein_avg_g_window_days"] == 6  # 2026-05-05 -> 2026-05-10 inclusive = 6 dates (#2338)


def test_the_thirty_day_named_key_reads_absent_until_the_window_really_spans_thirty_days(monkeypatch):
    """#1917 half two: `total_protein_30d_avg_g` is a claim about 30 days."""
    monkeypatch.setattr(sac, "EXPERIMENT_START", "2026-05-05")
    src = FakeSources(macrofactor=[mf("2026-05-06", food("Chicken Breast", protein_g=50, calories_kcal=250))])
    assert call("protein_sources", src)["total_protein_30d_avg_g"] is None


def test_the_thirty_day_named_key_carries_its_value_once_the_window_is_genuinely_full():
    b = call("protein_sources", PROTEIN_FIXTURE)
    assert b["total_protein_30d_avg_g"] == b["total_protein_avg_g"] == 41.7
    assert b["total_protein_avg_g_window_days"] == 30


@pytest.mark.parametrize("key", sorted(_MODULE_INTENSIVE_WINDOW_KEYS) or ["<none published>"])
def test_every_ungapped_intensive_window_key_this_module_publishes_nulls_on_a_short_window(monkeypatch, key):
    """Guard the SET, not the instance.

    The keys are not typed out here. They are AST-scanned out of
    ``site_api_meals.py`` (the same structural technique
    `tests/test_window_name_honesty_1917.py` uses) and then classified by
    ``web.window_registry`` — so a NEW ``_Nd``-named average added to this module
    is required to null on a short window the day it ships, without anybody
    remembering to extend this file.
    """
    assert key != "<none published>", "the AST scan found no window-named keys — the guard has gone vacuous"
    monkeypatch.setattr(sac, "EXPERIMENT_START", "2026-05-05")
    src = FakeSources(macrofactor=[mf("2026-05-06", food("Chicken Breast", protein_g=50, calories_kcal=250))])
    payload = call("protein_sources", src)
    assert key in payload, f"{key} is scanned out of the module but absent from the payload"
    assert payload[key] is None, f"{key} is an ungapped INTENSIVE window field on a 5-day window"


@pytest.mark.parametrize("key", sorted(_MODULE_EXTENSIVE_WINDOW_KEYS))
def test_extensive_delivery_counts_stay_populated_on_a_short_window(delivery_public, monkeypatch, key):
    """The other half of the same derived SET. The registry classifies these as
    EXTENSIVE, and the rubric is explicit: "3 orders in the last 30 days" is TRUE
    on Day 5 — a count over a partly elapsed window understates, it never
    overstates. So unlike the intensive average above, these must NOT be nulled;
    nulling them would hide a real number for a month after every reset."""
    monkeypatch.setattr(sac, "EXPERIMENT_START", "2026-05-05")
    src = FakeSources(food_delivery=[delivery("2026-05-06", amount=30.0, binge=True)])
    assert call("food_delivery_overview", src)["food_delivery"][key] is not None


def test_a_future_genesis_serves_an_empty_page_instead_of_five_hundreding(monkeypatch):
    """A reset stages EXPERIMENT_START in the FUTURE the night before Day 1. Every
    genesis-derived lower bound must survive that window — this is the
    `/api/fulfillment_ritual` incident class."""
    monkeypatch.setattr(sac, "EXPERIMENT_START", "2026-06-01")
    for fn in (meals.protein_sources, meals.food_delivery_overview):
        assert fn(_g=make_g(FakeSources()))["statusCode"] == 200


def test_the_lookback_lower_bound_is_clamped_to_pacific_today_not_utc_today(monkeypatch):
    """`_clamp_today` deliberately clamps in PACIFIC (the genesis-eve incident):
    at 20:00 PT the UTC date has already rolled over, and a UTC clamp would let a
    future genesis produce a lower bound past the upper one."""
    freeze(datetime(2026, 5, 11, 3, 0, 0, tzinfo=timezone.utc))  # 2026-05-10 20:00 PT
    monkeypatch.setattr(sac, "EXPERIMENT_START", "2026-06-01")
    src = FakeSources()
    meals.protein_sources(_g=make_g(src))
    start, _end = src.window_for("macrofactor")
    assert start == "2026-05-10", "the lower bound must clamp to the PACIFIC calendar day"


def test_a_food_log_from_before_genesis_never_reaches_the_protein_table(monkeypatch):
    """The end-to-end version of the clamp: prior-cycle food must not appear on a
    fresh cycle's page."""
    monkeypatch.setattr(sac, "EXPERIMENT_START", "2026-05-05")
    src = FakeSources(
        macrofactor=[
            mf("2026-04-20", food("Previous Cycle Food", protein_g=99, calories_kcal=400)),
            mf("2026-05-07", food("This Cycle Food", protein_g=40, calories_kcal=300)),
        ]
    )
    assert [s["food"] for s in call("protein_sources", src)["protein_sources"]] == ["This Cycle Food"]


def test_meal_glucose_reads_the_macrofactor_and_cgm_partitions_over_the_same_window():
    """A mismatched pair of windows would silently drop the join on the edge days."""
    src = FakeSources(filter_window=False)
    meals.meal_glucose(_g=make_g(src))
    assert src.window_for("macrofactor") == src.window_for("apple_health")


def test_meal_glucose_reads_only_the_two_partitions_it_needs():
    src = FakeSources(filter_window=False)
    meals.meal_glucose(_g=make_g(src))
    assert src.sources_read == {"macrofactor", "apple_health"}


def test_frequent_meals_asks_for_a_thirty_day_span():
    src = FakeSources(filter_window=False)
    meals.frequent_meals(_g=make_g(src))
    start, end = src.window_for("macrofactor")
    # #2338: the span is measured INCLUSIVELY — [start, end] covers 30 dates, so the
    # bare date difference is 29. Asserting 30 here is what let the endpoint fetch 31.
    span = datetime.strptime(end, "%Y-%m-%d") - datetime.strptime(start, "%Y-%m-%d")
    assert span + timedelta(days=1) == timedelta(days=30), f"{start}..{end} must span exactly 30 dates"


def test_frequent_meals_clamps_its_window_to_genesis_like_every_sibling(monkeypatch):
    """FIXED (#2221): `frequent_meals` now goes through `_g["_experiment_date"]`
    like every sibling. It used to build `(now - timedelta(days=30))` with no
    EXPERIMENT_START clamp — the only meal endpoint that reached past genesis."""
    # Run on the REAL clock: frequent_meals cannot be frozen (see the test below),
    # so a frozen genesis would be compared against a live lookback and the result
    # would depend on the wall clock rather than on the code.
    monkeypatch.setattr(sac, "datetime", datetime)
    monkeypatch.setattr(meals, "datetime", datetime)
    genesis = (datetime.now(timezone.utc) - timedelta(days=5)).strftime("%Y-%m-%d")
    monkeypatch.setattr(sac, "EXPERIMENT_START", genesis)
    src = FakeSources(filter_window=False)
    meals.frequent_meals(_g=make_g(src))
    start, _end = src.window_for("macrofactor")
    assert start >= genesis, f"frequent_meals reached back to {start}, before genesis {genesis}"


def test_the_published_period_matches_the_window_actually_queried(monkeypatch):
    """FIXED (#2221). Both handlers published `period_days: 30` as an
    unconditional literal while the actual window was genesis-clamped, so on Day 5
    of a cycle the payload claimed 30 days of meal table over 5 days of data. The
    #1917 AST guard could not see it: that guard matches `_Nd`-SUFFIXED key names,
    and `period_days` carries its window in the VALUE."""
    # Real clock (meal_glucose's `end` cannot be frozen — see the test below), with
    # genesis five days back, so this reproduces Day 5 of a cycle exactly.
    monkeypatch.setattr(sac, "datetime", datetime)
    monkeypatch.setattr(meals, "datetime", datetime)
    monkeypatch.setattr(sac, "EXPERIMENT_START", (datetime.now(timezone.utc) - timedelta(days=5)).strftime("%Y-%m-%d"))
    src = FakeSources(filter_window=False)
    body = body_of(meals.meal_glucose(_g=make_g(src)))
    start, end = src.window_for("macrofactor")
    # #2338: both bounds are inclusive, so the queried span is the difference PLUS ONE.
    actual = (datetime.strptime(end, "%Y-%m-%d") - datetime.strptime(start, "%Y-%m-%d")).days + 1
    assert body["period_days"] == actual, f"claims {body['period_days']}d, queried {actual}d"


def test_the_module_clock_can_be_frozen_for_every_handler_not_just_four_of_them():
    """FIXED (#2221): the in-function `from datetime import ...` re-imports are
    gone from both `frequent_meals` and `meal_glucose`. They shadowed the
    module-level binding, so `monkeypatch.setattr(meals, "datetime", ...)` — the
    seam every #1084/#1917 window test uses — silently no-opped for those two and
    their date arithmetic could not be pinned at a boundary at all."""
    src = FakeSources(filter_window=False)
    meals.frequent_meals(_g=make_g(src))
    _start, end = src.window_for("macrofactor")
    assert end == TODAY, f"frequent_meals ignored the frozen clock and used {end}"


# ──────────────────────────────────────────────────────────────────────────────
# 6. Privacy
# ──────────────────────────────────────────────────────────────────────────────


def test_the_meal_endpoints_never_touch_a_partition_they_were_not_asked_for(delivery_public):
    """The generic containment check: each handler reads its own sources and no
    others, so a private partition cannot be pulled in by a refactor."""
    expected = {
        "protein_sources": {"macrofactor"},
        "meal_glucose": {"macrofactor", "apple_health"},
        "food_delivery_overview": {"food_delivery"},
        "frequent_meals": {"macrofactor"},
    }
    for name, want in expected.items():
        src = FakeSources(filter_window=False)
        HANDLERS[name](_g=make_g(src))
        assert src.sources_read == want, f"{name} read {src.sources_read}"


def test_food_delivery_respects_the_same_privacy_flag_its_sibling_endpoint_does():
    """FIXED by #2210 (was a tranche-2 xfail). `/api/food_delivery_overview` sits on
    the fully public, unauthenticated route table and publishes order count, spend
    and — most sensitively — `binge_days_30d`. The same data class is PRIVATE-by-
    default one module over (`site_api_nutrition`), so this endpoint now shares the
    identical `nutrition_delivery_public()` helper and the two can no longer drift.

    Asserted on the SHIPPED constant, not a patched one: `_DELIVERY_PUBLIC` is
    computed at import, so this pins the value the Lambda actually boots with."""
    assert meals._DELIVERY_PUBLIC is False, "the shipped default must be OFF — this is the P2.3 decision"

    src = FakeSources(food_delivery=[delivery("2026-04-15", amount=31.25, binge=True)])
    b = call("food_delivery_overview", src)
    assert src.sources_read == set(), "the private partition was queried with the flag off"
    assert b["food_delivery"] is None


def test_the_delivery_gate_is_what_withholds_the_data_and_not_an_empty_fixture(delivery_public):
    """The mutation proof for the test above. Same fixture, same handler, gate ON:
    the partition IS read and the private figures DO appear. Without this pair, the
    gate test would pass just as happily against a handler that had quietly stopped
    reading delivery data for any reason at all."""
    src = FakeSources(food_delivery=[delivery("2026-04-15", amount=31.25, binge=True)])
    b = call("food_delivery_overview", src)
    assert src.sources_read == {"food_delivery"}
    assert b["food_delivery"]["orders_30d"] == 1
    assert b["food_delivery"]["total_spend_30d"] == 31.25
    assert b["food_delivery"]["binge_days_30d"] == 1


# ──────────────────────────────────────────────────────────────────────────────
# 7. Malformed data — one bad row must not take a page down
# ──────────────────────────────────────────────────────────────────────────────


def test_frequent_meals_degrades_to_a_503_when_the_source_read_fails():
    """503 + no-store is the honest answer: "temporarily unavailable", not an
    empty table that reads as "you ate nothing"."""
    resp = meals.frequent_meals(_g=make_g(FakeSources(raises=RuntimeError("DDB throttled"))))
    assert resp["statusCode"] == 503
    assert json.loads(resp["body"])["error"] == "Meal data temporarily unavailable."
    assert resp["headers"]["Cache-Control"] == "no-cache, no-store"


def test_meal_glucose_degrades_to_a_503_when_the_source_read_fails():
    resp = meals.meal_glucose(_g=make_g(FakeSources(filter_window=False, raises=RuntimeError("DDB throttled"))))
    assert resp["statusCode"] == 503
    assert json.loads(resp["body"])["error"] == "Meal glucose data temporarily unavailable."


def test_an_error_response_is_never_cached_by_cloudfront():
    """A cached 503 would pin "temporarily unavailable" onto the page for the
    whole TTL after the outage cleared."""
    for fn, src in (
        (meals.frequent_meals, FakeSources(raises=RuntimeError("x"))),
        (meals.meal_glucose, FakeSources(filter_window=False, raises=RuntimeError("x"))),
    ):
        assert "no-store" in fn(_g=make_g(src))["headers"]["Cache-Control"]


def test_one_unparseable_macro_value_does_not_take_down_the_frequent_meals_table():
    """A single junk row from a hand-edited export must cost one row, not the
    panel. frequent_meals' try/except converts it to an honest 503 rather than a
    502 from the Function URL — degraded, but shaped."""
    src = FakeSources(filter_window=False, macrofactor=[mf("2026-04-15", {"food_name": "Broken Row", "calories_kcal": "n/a"})])
    assert meals.frequent_meals(_g=make_g(src))["statusCode"] == 503


def test_one_unparseable_protein_value_does_not_five_hundred_the_protein_page():
    """FIXED (#2221): protein_sources now degrades to a 503 like its two siblings.
    It had NO exception guard at all, so one non-numeric `protein_g` escaped the
    handler AND the facade delegator and the Function URL answered 502 — which the
    site smoke test reads as a fleet-wide regression and auto-rolls-back on."""
    src = FakeSources(
        macrofactor=[
            mf("2026-04-15", {"food_name": "Broken Row", "protein_g": "n/a"}, food("Chicken Breast", protein_g=40, calories_kcal=200)),
        ]
    )
    assert meals.protein_sources(_g=make_g(src))["statusCode"] in (200, 503)


def test_one_currency_formatted_amount_does_not_five_hundred_the_delivery_page(delivery_public):
    """FIXED (#2221). `sum(float(i.get("amount") or 0) ...)` raised ValueError on a
    currency-formatted amount ("$24.50" — the shape a hand-entered or scraped
    record takes) and 502'd. The module already guarded the WEEK PARSE of the same
    records, so the omission was inconsistent inside one function."""
    src = FakeSources(food_delivery=[delivery("2026-04-15", amount="$24.50"), delivery("2026-04-16", amount=18.0)])
    assert meals.food_delivery_overview(_g=make_g(src))["statusCode"] in (200, 503)


def test_a_day_record_with_no_food_log_key_is_simply_skipped():
    """`day.get("food_log") or []` — the common shape for a synced-but-empty day."""
    src = FakeSources(macrofactor=[mf("2026-04-15"), mf("2026-04-16", food("Chicken Breast", protein_g=40, calories_kcal=200))])
    assert [s["food"] for s in call("protein_sources", src)["protein_sources"]] == ["Chicken Breast"]


def test_a_food_entry_with_no_name_is_skipped_rather_than_listed_as_blank():
    src = FakeSources(
        macrofactor=[mf("2026-04-15", {"protein_g": 40, "calories_kcal": 200}, food("Chicken Breast", protein_g=30, calories_kcal=150))]
    )
    assert [s["food"] for s in call("protein_sources", src)["protein_sources"]] == ["Chicken Breast"]


def test_a_null_food_name_is_skipped_rather_than_crashing_the_strip():
    """`(entry.get("food_name") or "").strip()` — an explicit JSON null in the
    export is the case the `or ""` exists for."""
    src = FakeSources(macrofactor=[mf("2026-04-15", {"food_name": None, "protein_g": 40}, food("Steak", protein_g=45, calories_kcal=400))])
    assert [s["food"] for s in call("protein_sources", src)["protein_sources"]] == ["Steak"]


def test_a_delivery_flag_recorded_as_the_string_false_is_counted_as_a_binge(delivery_public):
    """Documented truthiness hazard, pinned as a tripwire: `if i.get("binge")` is a
    truthiness test, so any non-empty string — including "false" or "no" — counts.
    Boolean and numeric encodings behave correctly; a string encoding would
    silently inflate the reader's binge count."""
    src = FakeSources(food_delivery=[delivery("2026-04-15", amount=20.0, binge="false")])
    assert call("food_delivery_overview", src)["food_delivery"]["binge_days_30d"] == 1

    honest = FakeSources(food_delivery=[delivery("2026-04-15", amount=20.0, binge=False), delivery("2026-04-16", amount=20.0, binge=0)])
    assert call("food_delivery_overview", honest)["food_delivery"]["binge_days_30d"] == 0


# ──────────────────────────────────────────────────────────────────────────────
# §12 — The glucose door's meal table binds only keys this module publishes (#2329)
# ──────────────────────────────────────────────────────────────────────────────
#
# The front-end (`site/assets/js/evidence_nutrition.js` renderGlucose) prints a
# table header for every column it renders. #2329's defect: two headers (`peak`,
# `Δ rise`) bound keys (`peak`/`peak_mgdl`, `delta`/`rise`) that NO serving
# endpoint publishes — every row rendered two blank cells. These guards pin the
# binding to the endpoint's real contract, in both directions: every `m.<key>`
# accessor in the table template must be a key a populated `meal_glucose` row
# actually carries, and every header must have a cell. They fail the moment a
# header is added without a backing key — or a published key is renamed out from
# under the door.


def _meal_table_template() -> str:
    import pathlib
    import re as _re

    js = (pathlib.Path(__file__).resolve().parents[1] / "site" / "assets" / "js" / "evidence_nutrition.js").read_text()
    m = _re.search(r'sec\("Meal glucose response",\s*`(.*?)`\s*\)', js, _re.S)
    assert m, "the glucose door's meal-table template moved — update this guard alongside it"
    return m.group(1)


def _populated_meal_glucose_row() -> dict:
    """One real row from the handler on a populated fixture — the published contract."""
    src = FakeSources(
        filter_window=False,
        macrofactor=[mf(TODAY, food("Chicken Burrito Bowl", protein_g=45, calories_kcal=650, carbs_g=55, time="12:30"))],
        apple_health=[cgm(TODAY, avg=105, peak=145, low=88, tir=92)],
    )
    meals_out = call("meal_glucose", src)["meals"]
    assert meals_out, "the fixture must produce at least one meal row"
    return meals_out[0]


def test_every_key_the_meal_table_binds_is_one_meal_glucose_publishes():
    """#2329 acceptance: the rendered column set is a subset of the keys the
    serving endpoint publishes. `m.<key>` accessors are read out of the template
    itself, so a header added over a phantom key fails here before it ships two
    blank columns to a reader."""
    import re as _re

    tmpl = _meal_table_template()
    bound = set(_re.findall(r"\bm\.([A-Za-z_]\w*)", tmpl))
    assert bound, "no bindings found in the meal-table template — the extraction regex has gone stale"
    published = set(_populated_meal_glucose_row())
    missing = bound - published
    assert not missing, f"the meal table binds keys /api/meal_glucose never publishes: {sorted(missing)}"


def test_the_meal_table_prints_exactly_one_cell_per_header():
    """A header with no cell — or a cell with no header — is the same reader lie
    in column form; the render-level twin lives in
    tests/js/evidence_nutrition_meal_table_2329.test.mjs."""
    import re as _re

    tmpl = _meal_table_template()
    headers = _re.findall(r"<th>", tmpl)
    cells = _re.findall(r"<td[^>]*>", tmpl)
    assert len(headers) == len(cells), f"{len(headers)} headers over {len(cells)} cells"


def test_the_retired_phantom_columns_stay_retired():
    """`peak`/`delta` per meal are not derivable from the daily CGM aggregates
    this endpoint reads (`blood_glucose_avg/max/min` per DAY) — a day-level max
    attributed to a single meal would be a fabricated number (ADR-104/105). The
    honest per-meal figure is the carb-weighted `spike` estimate, which is what
    the door now renders. If a future writer lands true per-meal CGM windows
    (#2327 direction 2), delete this test alongside that contract change."""
    row = _populated_meal_glucose_row()
    for phantom in ("peak", "peak_mgdl", "delta", "rise"):
        assert phantom not in row, f"meal_glucose now publishes {phantom!r} — retire this guard and rebind the door"
