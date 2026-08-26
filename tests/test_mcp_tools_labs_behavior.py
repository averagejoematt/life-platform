"""tests/test_mcp_tools_labs_behavior.py — behavioral contracts for the MCP lab
tools served by ``mcp/tools_labs.py``:

    get_labs               (view = results | trends | out_of_range)
    get_freshness_status   (per-source staleness / interior gaps)

These are the numbers Matthew reads through Claude Desktop when he asks "show my
blood work", "is my LDL trending down", "what's chronically out of range" and
"are we OK?". Nothing between this module and his eyes re-checks the arithmetic —
whatever it returns is read as clinical fact and acted on. The ``mcp/tools_*``
family had **zero** dedicated behavioural coverage before #1658 tranche 3.

The contracts pinned here:

  * **ADR-104 honest numbers** — an unmeasured biomarker is ABSENT, never a
    factual 0; a projection outside the metric's physical domain is not a number.
  * **ADR-105 rigor** — an average, slope, projection or persistence class ships
    with the n behind it; a "trend" from 2 points is labelled as such.
  * **Reference-range / flag logic** — the stored ``flag`` is passed through
    verbatim, and a ``category`` filter must not leave the *counts* describing a
    different (wider) set than the values shown.
  * **Privacy** — genome identifiers (gene, rsID, genotype) are Tier 2 owner-only.
    They ARE returned here (MCP is the owner-only surface, which is sanctioned),
    but the module's own declared guardrail must actually be wired up.
  * **ADR-058 phase filtering** — ``labs`` is CROSS_PHASE in
    ``experiment.phase_taxonomy``; the query must therefore carry NO phase filter,
    or a cycle reset would truncate a clinical archive. This file DERIVES that
    expectation from the taxonomy rather than restating it ("guard the SET").
  * **Envelope / freshness honesty** — a status tool whose whole job is "are we
    OK?" must never answer green about a source it could not read.
  * **Registry parity** — the tool set, the declared ``view`` enum and the
    declared input properties are DERIVED from ``mcp/registry.py``'s ``TOOLS``
    dict, never restated.

Everything is driven through the real tool entry points (``tool_get_labs`` /
``tool_get_freshness_status``) with the declared arguments, a frozen clock, and
hand-rolled bounded fakes — never a MagicMock inside a pagination-shaped read,
never a real AWS or network call.

Arithmetic expectations are hand-derived in the test body and written as
literals, with the derivation shown in a comment — never "whatever the code
returned".

NOT covered here (deliberate, see the report): ``find_interior_gaps`` already has
dedicated coverage in ``tests/test_freshness_interior_gaps_mcp.py``; only its
integration into the freshness envelope is exercised.
"""

from __future__ import annotations

import os

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")  # mcp.config requires these at import
os.environ.setdefault("USER_ID", "matthew")

from datetime import datetime, timezone  # noqa: E402

import pytest  # noqa: E402
from experiment import phase_taxonomy  # noqa: E402
from ingestion.source_registry import DEFAULT_STALE_HOURS, mcp_sources, stale_hours_overrides  # noqa: E402
from pacific_clock import freeze_pacific  # #2817: the Pacific clock a converted module actually reads

from mcp import labs_helpers as lh, tools_labs as tl  # noqa: E402
from mcp.registry import TOOLS  # noqa: E402

# ──────────────────────────────────────────────────────────────────────────────
# Frozen clock
# ──────────────────────────────────────────────────────────────────────────────

# 2026-08-08 17:00Z. Chosen so that every hand-derived "days since" below is a
# clean integer and never depends on the wall clock of the machine running this.
NOW = datetime(2026, 8, 8, 17, 0, 0, tzinfo=timezone.utc)
TODAY = "2026-08-08"

_FROZEN = [NOW]


class _FrozenDatetime(datetime):
    """``datetime`` subclass with a pinned ``now()``.

    A subclass rather than a Mock because ``tools_labs`` calls ``strptime`` and
    ``timedelta`` arithmetic on the SAME name it calls ``now()`` on — a Mock
    would break the first and silently fabricate the second.

    ``_build_cadence_trackers`` calls ``datetime.now()`` with no argument (naive,
    LOCAL time — see ``test_cadence_clock_is_local_not_utc``) while
    ``tool_get_freshness_status`` calls ``datetime.now(timezone.utc)``. Both
    resolve through here.
    """

    @classmethod
    def now(cls, tz=None):
        if tz is None:
            return _FROZEN[0].replace(tzinfo=None)
        return _FROZEN[0].astimezone(tz)

    @classmethod
    def utcnow(cls):
        return _FROZEN[0].replace(tzinfo=None)


@pytest.fixture(autouse=True)
def frozen_clock(monkeypatch):
    _FROZEN[0] = NOW
    monkeypatch.setattr(tl, "datetime", _FrozenDatetime)
    freeze_pacific(monkeypatch, tl, _FrozenDatetime)  # #2817: pin the PACIFIC helpers this module now calls
    yield


@pytest.fixture(autouse=True)
def _clear_genome_cache():
    """``labs_helpers._GENOME_CACHE_V2`` is a process-lifetime module global.

    Left alone it leaks one test's genome fixture into the next (and into any
    other test file in the same session), so it is reset on both sides.
    """
    lh._GENOME_CACHE_V2 = None
    yield
    lh._GENOME_CACHE_V2 = None


# ──────────────────────────────────────────────────────────────────────────────
# Bounded hand-rolled fakes
# ──────────────────────────────────────────────────────────────────────────────


def _condition_strings(expr) -> list:
    """Flatten the string leaves out of a boto3 ``Key(...)`` condition tree.

    boto3 conditions nest as ``And(Equals(Key('pk'), 'USER#…'), BeginsWith(…))``
    with the operands on ``._values``. Walking them lets the fakes below dispatch
    on the real partition key the code under test asked for, instead of ignoring
    kwargs the way a canned-rows stub would.
    """
    out: list = []
    for v in getattr(expr, "_values", ()):
        if isinstance(v, str):
            out.append(v)
        else:
            out.extend(_condition_strings(v))
    return out


def _pk_of(kwargs) -> str | None:
    for s in _condition_strings(kwargs.get("KeyConditionExpression")):
        if s.startswith("USER#"):
            return s
    return None


class FakeLabsTable:
    """Bounded DynamoDB ``Table`` double for the labs/genome/dexa partitions.

    Dispatches on the real partition key, serves rows in sk order (what DynamoDB
    guarantees), and can hand back a **bounded** two-page response so the
    ``LastEvaluatedKey`` loop in ``labs_helpers._query_all_lab_draws`` is actually
    executed. ``paginate`` splits after the first row and the second page always
    terminates — there is no unbounded generator anywhere in this file.
    """

    def __init__(self, rows_by_pk: dict | None = None, *, paginate: bool = False, raises: bool = False):
        self.rows_by_pk = {k: list(v) for k, v in (rows_by_pk or {}).items()}
        self.paginate = paginate
        self.raises = raises
        self.query_calls: list = []

    def query(self, **kwargs):
        self.query_calls.append(kwargs)
        if self.raises:
            raise RuntimeError("ddb down")
        rows = sorted(self.rows_by_pk.get(_pk_of(kwargs), []), key=lambda r: r.get("sk", ""))
        if not self.paginate or len(rows) < 2:
            return {"Items": rows}
        # Exactly two pages, ever: [0] then the rest.
        if "ExclusiveStartKey" not in kwargs:
            return {"Items": rows[:1], "LastEvaluatedKey": {"pk": rows[0]["pk"], "sk": rows[0]["sk"]}}
        return {"Items": rows[1:]}


class FakeFreshnessTable:
    """Bounded double for ``tool_get_freshness_status``'s per-source reads.

    Honors the three things the tool actually depends on: partition dispatch,
    ``ScanIndexForward=False`` (newest first), and ``Limit``. Unknown partitions
    answer empty, which is what a real table does for a source that never wrote.
    """

    def __init__(self, rows_by_pk: dict | None = None, *, raises_for: set | None = None):
        self.rows_by_pk = {k: list(v) for k, v in (rows_by_pk or {}).items()}
        self.raises_for = raises_for or set()
        self.query_calls: list = []

    def query(self, **kwargs):
        self.query_calls.append(kwargs)
        pk = _pk_of(kwargs)
        if pk in self.raises_for:
            raise RuntimeError("throttled")
        rows = sorted(self.rows_by_pk.get(pk, []), key=lambda r: r.get("sk", ""))
        if kwargs.get("ScanIndexForward") is False:
            rows = list(reversed(rows))
        limit = kwargs.get("Limit")
        if limit is not None:
            rows = rows[:limit]
        return {"Items": rows}


def _draw(date: str, biomarkers: dict, **extra) -> dict:
    """One labs DATE# row, shaped the way the lab importer writes it."""
    oor = [k for k, v in biomarkers.items() if v.get("flag") in ("high", "low")]
    row = {
        "pk": "USER#matthew#SOURCE#labs",
        "sk": f"DATE#{date}",
        "draw_date": date,
        "lab_provider": "Function Health",
        "lab_network": "Quest",
        "physician": "Dr. Example",
        "fasting": True,
        "total_biomarkers": len(biomarkers),
        "out_of_range_count": len(oor),
        "out_of_range": oor,
        "biomarkers": biomarkers,
    }
    row.update(extra)
    return row


def _bm(value, *, flag="normal", unit="mg/dL", category="lipids", ref_text="") -> dict:
    return {"value_numeric": value, "flag": flag, "unit": unit, "category": category, "ref_text": ref_text}


LABS_PK = "USER#matthew#SOURCE#labs"
GENOME_PK = "USER#matthew#SOURCE#genome"


@pytest.fixture
def labs_table(monkeypatch):
    """Install a FakeLabsTable on both modules that hold a ``table`` reference.

    ``labs_helpers`` and ``tools_labs`` each imported ``table`` by value from
    ``mcp.config``, so a single patch would leave one of them bound to the real
    boto3 resource (a re-export is not a patch point).
    """

    def _install(rows_by_pk, **kw):
        t = FakeLabsTable(rows_by_pk, **kw)
        monkeypatch.setattr(lh, "table", t)
        monkeypatch.setattr(tl, "table", t)
        return t

    return _install


# ──────────────────────────────────────────────────────────────────────────────
# §1 — Registry parity: the tool set and its declared schema
# ──────────────────────────────────────────────────────────────────────────────


def _tools_from_this_module() -> dict:
    """DERIVED, not restated: every registry tool whose handler lives in tools_labs."""
    return {name: spec for name, spec in TOOLS.items() if getattr(spec["fn"], "__module__", "") == tl.__name__}


def test_registry_wires_every_labs_tool_to_a_real_callable():
    wired = _tools_from_this_module()
    # The set is derived; if a tool is added to tools_labs and registered, it is
    # covered by the schema tests below automatically.
    assert wired, "no registry tool resolves to mcp.tools_labs — the module is unwired"
    for name, spec in wired.items():
        assert callable(spec["fn"])
        assert spec["schema"]["name"] == name
        assert spec["schema"]["inputSchema"]["type"] == "object"


def test_declared_view_enum_matches_the_dispatchers_valid_views():
    """The enum a client sees must be the set the dispatcher will actually accept.

    Both sides are derived: the enum from the registry schema, the accepted set
    from the dispatcher's own error envelope (which publishes ``valid_views``).
    """
    enum = set(TOOLS["get_labs"]["schema"]["inputSchema"]["properties"]["view"]["enum"])
    accepted = set(tl.tool_get_labs({"view": "__nope__"})["valid_views"])
    assert enum == accepted


def test_unknown_view_returns_a_hint_and_never_raises(labs_table):
    labs_table({})
    out = tl.tool_get_labs({"view": "RESULTS "})  # case + whitespace are normalised
    assert "error" not in out or "No lab draws" in out["error"]


def test_trends_honors_the_declared_start_date_window(labs_table):
    labs_table(
        {
            LABS_PK: [
                _draw("2026-01-01", {"ldl_c": _bm(160)}),
                _draw("2026-06-01", {"ldl_c": _bm(120)}),
            ]
        }
    )
    props = TOOLS["get_labs"]["schema"]["inputSchema"]["properties"]
    assert "start_date" in props and "end_date" in props  # the schema really does declare them
    out = tl.tool_get_labs({"view": "trends", "biomarker": "ldl_c", "start_date": "2026-05-01", "end_date": "2026-12-31"})
    assert out["trends"]["ldl_c"]["data_points"] == 1
    assert out["trends"]["ldl_c"]["values"][0]["date"] == "2026-06-01"  # the 2026-01-01 draw is OUT
    assert out["window"] == {"start_date": "2026-05-01", "end_date": "2026-12-31"}
    assert out["total_draws"] == 1  # and the envelope's own counts describe the window, not the archive


def test_trends_window_that_selects_nothing_says_so_rather_than_widening(labs_table):
    """The failure mode a silent window has: answering the question that WASN'T asked."""
    labs_table({LABS_PK: [_draw("2026-01-01", {"ldl_c": _bm(160)})]})
    out = tl.tool_get_labs({"view": "trends", "biomarker": "ldl_c", "start_date": "2026-05-01"})
    assert out["trends"] == {}
    assert "No lab draws between 2026-05-01" in out["error"]


def test_trends_biomarker_partial_match_as_documented(labs_table):
    labs_table({LABS_PK: [_draw("2026-01-01", {"cholesterol_total": _bm(190)})]})
    desc = TOOLS["get_labs"]["schema"]["inputSchema"]["properties"]["biomarker"]["description"]
    assert "partial match" in desc  # the promise being tested
    out = tl.tool_get_labs({"view": "trends", "biomarker": "cholesterol"})
    assert "error" not in out["trends"]["cholesterol"]
    # The caller reads back the name it asked with, and is told what that resolved to —
    # a partial match must never leave the reader guessing WHICH biomarker they got.
    assert out["trends"]["cholesterol"]["resolved_biomarker"] == "cholesterol_total"
    assert out["trends"]["cholesterol"]["values"][0]["value"] == 190


def test_trends_ambiguous_partial_match_expands_rather_than_guessing(labs_table):
    """Two biomarkers match 'cholesterol'. Picking one silently would be a wrong number."""
    labs_table({LABS_PK: [_draw("2026-01-01", {"cholesterol_total": _bm(190), "non_hdl_cholesterol_calc": _bm(140)})]})
    out = tl.tool_get_labs({"view": "trends", "biomarker": "cholesterol"})
    note = out["trends"]["cholesterol"]
    assert note["matched_biomarkers"] == ["cholesterol_total", "non_hdl_cholesterol_calc"]
    assert "error" not in note
    # …and both are actually reported, under their real keys.
    assert out["trends"]["cholesterol_total"]["values"][0]["value"] == 190
    assert out["trends"]["non_hdl_cholesterol_calc"]["values"][0]["value"] == 140


def test_trends_unmatched_name_still_gets_the_no_data_envelope(labs_table):
    """Partial matching must not swallow the honest 'never measured' answer."""
    labs_table({LABS_PK: [_draw("2026-01-01", {"ldl_c": _bm(130)})]})
    out = tl.tool_get_labs({"view": "trends", "biomarker": "selenium"})
    assert out["trends"]["selenium"]["error"] == "No data for 'selenium'"


# ──────────────────────────────────────────────────────────────────────────────
# §2 — view = results
# ──────────────────────────────────────────────────────────────────────────────


def test_results_empty_platform_returns_an_error_envelope(labs_table):
    labs_table({})
    out = tl.tool_get_labs({})  # results is the default view
    assert out["error"] == "No lab draws found in DynamoDB"
    # The FH-v2 augment attaches to error envelopes too, so the key is stable.
    assert out["cadence_trackers"] == {}


def test_results_summary_lists_every_draw_newest_last(labs_table):
    labs_table(
        {
            LABS_PK: [
                _draw("2026-06-01", {"ldl_c": _bm(120)}),
                _draw("2025-02-02", {"ldl_c": _bm(150, flag="high")}),
            ]
        }
    )
    out = tl.tool_get_labs({"view": "results"})
    assert out["total_draws"] == 2
    # _query_all_lab_draws sorts by draw date, so the summary is chronological.
    assert [d["draw_date"] for d in out["draws"]] == ["2025-02-02", "2026-06-01"]
    assert out["draws"][0]["out_of_range"] == ["ldl_c"]
    assert out["draws"][0]["out_of_range_count"] == 1
    assert "hint" in out


def test_draws_are_ordered_by_the_draw_date_not_the_import_key(labs_table):
    """The sk is the IMPORT key; `draw_date` is when the blood was actually taken.

    They agree on every row in the live archive, which is why this is latent rather
    than a live wrong number — but a panel backfilled after a later draw files under
    a LATER sk than the draw it contains, and EVERY reader here indexes [0]/[-1] as
    earliest/latest. The sibling shape was live in `tools_cgm`, where an sk-ordered
    fasting glucose of 88 -> 92 -> 101 was narrated as "trending down".
    """
    late_sk_early_draw = _draw("2026-01-05", {"ldl_c": _bm(160, flag="high")})
    late_sk_early_draw["sk"] = "DATE#2026-09-30"  # imported last, drawn first
    labs_table({LABS_PK: [late_sk_early_draw, _draw("2026-06-01", {"ldl_c": _bm(120)})]})

    out = tl.tool_get_labs({"view": "results"})
    assert [d["draw_date"] for d in out["draws"]] == ["2026-01-05", "2026-06-01"]

    tr = tl.tool_get_labs({"view": "trends", "biomarker": "ldl_c"})["trends"]["ldl_c"]
    assert tr["earliest"] == 160 and tr["latest"] == 120
    assert tr["direction"] == "falling"  # sk order would have said "rising"


def test_a_draw_missing_its_draw_date_recovers_the_date_from_its_sort_key(labs_table):
    """The sk still carries the date, so an importer that dropped `draw_date` has
    lost a field, not the chronology. Recovering it beats dropping the draw."""
    undated = _draw("2026-01-01", {"ldl_c": _bm(130)})
    undated.pop("draw_date")
    labs_table({LABS_PK: [undated]})
    assert lh._draw_date_of(undated) == "2026-01-01"
    assert tl.tool_get_labs({"view": "results"})["draws"][0]["draw_date"] == "2026-01-01"


def test_a_draw_with_no_recoverable_date_is_absent_from_the_time_axis(labs_table):
    """…but when NEITHER the field nor the sk parses there is no date to invent."""
    lost = _draw("2026-01-01", {"ldl_c": _bm(130)})
    lost["draw_date"], lost["sk"] = "sometime in spring", "PROVIDER#function_health"
    assert lh._draw_date_of(lost) is None
    labs_table({LABS_PK: [lost, _draw("2026-03-02", {"ldl_c": _bm(110)})]})
    tr = tl.tool_get_labs({"view": "trends", "biomarker": "ldl_c"})["trends"]["ldl_c"]
    assert tr["data_points"] == 1  # the datable draw only…
    assert tr["undated_draws_skipped"] == 1  # …and the omission is declared, not silent


def test_results_paginates_the_draw_query(labs_table):
    """The draw read must survive a paged DynamoDB response, not stop at page 1."""
    t = labs_table(
        {
            LABS_PK: [
                _draw("2026-01-01", {"ldl_c": _bm(150)}),
                _draw("2026-03-01", {"ldl_c": _bm(140)}),
                _draw("2026-05-01", {"ldl_c": _bm(130)}),
            ]
        },
        paginate=True,
    )
    out = tl.tool_get_labs({"view": "results"})
    assert out["total_draws"] == 3
    assert any("ExclusiveStartKey" in c for c in t.query_calls)


def test_results_unknown_draw_date_lists_the_available_ones(labs_table):
    labs_table({LABS_PK: [_draw("2026-01-01", {"ldl_c": _bm(150)})]})
    out = tl.tool_get_labs({"view": "results", "draw_date": "1999-12-31"})
    assert out["error"] == "No draw for 1999-12-31"
    assert out["available_dates"] == ["2026-01-01"]


def test_results_single_draw_passes_the_stored_flag_through_verbatim(labs_table):
    """No reference-range arithmetic happens here — the flag is the lab's, not ours.

    Pinned because the opposite (recomputing a flag from a hard-coded range) is
    where sex/age-specific ranges get silently mis-applied.
    """
    labs_table(
        {
            LABS_PK: [
                _draw(
                    "2026-01-01",
                    {
                        "hdl": _bm(39, flag="low", ref_text=">40 mg/dL"),
                        "ldl_c": _bm(160, flag="high", ref_text="<100 mg/dL"),
                        "glucose": _bm(99, flag="normal", category="metabolic", ref_text="70-99 mg/dL"),
                    },
                )
            ]
        }
    )
    out = tl.tool_get_labs({"view": "results", "draw_date": "2026-01-01"})
    # HDL is better HIGH and LDL better LOW — the direction lives in the stored
    # flag, and both survive the round trip unmodified.
    assert out["biomarkers"]["hdl"]["flag"] == "low"
    assert out["biomarkers"]["ldl_c"]["flag"] == "high"
    assert out["biomarkers"]["glucose"]["flag"] == "normal"  # 99 at the top of 70-99 is IN range
    assert out["categories_in_draw"] == ["lipids", "metabolic"]
    assert out["provider"] == "Function Health" and out["lab_network"] == "Quest"


def test_results_category_filter_also_narrows_the_counts(labs_table):
    labs_table(
        {
            LABS_PK: [
                _draw(
                    "2026-01-01",
                    {
                        "ldl_c": _bm(90),
                        "hdl": _bm(55),
                        "glucose": _bm(115, flag="high", category="metabolic"),
                    },
                )
            ]
        }
    )
    out = tl.tool_get_labs({"view": "results", "draw_date": "2026-01-01", "category": "lipids"})
    assert set(out["biomarkers"]) == {"ldl_c", "hdl"}  # the filter itself works
    # 2 lipid biomarkers shown, 0 of them flagged.
    assert out["total_biomarkers"] == 2
    assert out["out_of_range_count"] == 0
    assert out["out_of_range"] == []


# ──────────────────────────────────────────────────────────────────────────────
# §3 — view = trends (slope, projection, derived ratios)
# ──────────────────────────────────────────────────────────────────────────────


def test_trends_and_out_of_range_share_the_empty_platform_envelope(labs_table):
    """Envelope parity across the three views on a quiet platform."""
    labs_table({})
    for view in ("trends", "out_of_range"):
        out = tl.tool_get_labs({"view": view, "biomarker": "ldl_c"})
        assert out["error"] == "No lab draws found"
        assert out["cadence_trackers"] == {}


def test_trends_single_biomarker_slope_and_change_are_hand_derived(labs_table):
    labs_table(
        {
            LABS_PK: [
                _draw("2026-01-01", {"ldl_c": _bm(130, flag="high")}),
                _draw("2026-03-02", {"ldl_c": _bm(110)}),
            ]
        }
    )
    out = tl.tool_get_labs({"view": "trends", "biomarker": "ldl_c"})
    tr = out["trends"]["ldl_c"]
    # Derivation. x = days since the first draw: 2026-01-01 -> 0, 2026-03-02 -> 60
    # (31 Jan + 28 Feb + 1). OLS on [(0,130),(60,110)]:
    #   mean x = 30, mean y = 120
    #   ss_xy = (0-30)(130-120) + (60-30)(110-120) = -300 + -300 = -600
    #   ss_xx = 900 + 900 = 1800
    #   slope  = -600/1800 = -0.3333... -> _linear_regression rounds to -0.3333
    #   slope_per_year = round(-0.3333 * 365.25, 2)
    #                  = round(-(121.6545 + 0.083325), 2) = round(-121.737825, 2) = -121.74
    assert tr["data_points"] == 2  # ADR-105: the n ships with the slope
    assert tr["direction"] == "falling"
    assert tr["slope_per_year"] == -121.74
    assert tr["r_squared"] == 1.0  # two points always fit a line exactly
    assert tr["earliest"] == 130 and tr["latest"] == 110
    assert tr["total_change"] == -20  # 110 - 130
    assert [p["date"] for p in tr["values"]] == ["2026-01-01", "2026-03-02"]


def test_trends_projection_stays_inside_the_biomarkers_physical_domain(labs_table):
    labs_table(
        {
            LABS_PK: [
                _draw("2026-01-01", {"ldl_c": _bm(130, flag="high")}),
                _draw("2026-03-02", {"ldl_c": _bm(110)}),
            ]
        }
    )
    tr = tl.tool_get_labs({"view": "trends", "biomarker": "ldl_c"})["trends"]["ldl_c"]
    # Derivation of the extrapolation that must NOT be published:
    #   intercept = 120 - (-0.3333 * 30) = 129.999 -> round(.,2) = 130.0
    #   projected = 130.0 + (-0.3333 * (60 + 365.25)) = 130.0 - 141.7358 = -141.74 + 130 = -11.74
    # A negative LDL cholesterol is not a possible human value, so it is withheld and
    # the reason is published in its place — never silently replaced by a plausible number.
    assert tr["projected_1yr"] is None
    assert "outside the physical domain" in tr["projection_note"]
    assert "-11.74" in tr["projection_note"]  # the withheld value is still shown, named as withheld
    # The rest of the trend is unaffected — only the forecast is refused.
    assert tr["direction"] == "falling" and tr["data_points"] == 2


def test_trends_an_in_domain_projection_from_two_points_ships_with_its_caveat(labs_table):
    """ADR-105: a forecast the code IS willing to publish still says what n=2 cannot buy.

    The two markers in this cluster disagree about n=2 — one asks for no projection at
    all below an interval, its sibling pins `projected_1yr == latest + slope_per_year`
    on exactly two draws. The reconciliation is to publish the number WITH the missing
    uncertainty named, rather than to publish it bare or to withhold a projection the
    sibling contract requires.
    """
    labs_table({LABS_PK: [_draw("2026-01-01", {"hdl": _bm(40)}), _draw("2026-03-02", {"hdl": _bm(52)})]})
    tr = tl.tool_get_labs({"view": "trends", "biomarker": "hdl"})["trends"]["hdl"]
    assert tr["projected_1yr"] == 125.05
    assert "n=2" in tr["projection_caveat"] and "prediction interval" in tr["projection_caveat"]


def test_trends_slope_per_year_and_projection_use_the_same_year_length(labs_table):
    labs_table(
        {
            LABS_PK: [
                _draw("2026-01-01", {"hdl": _bm(40)}),
                _draw("2026-03-02", {"hdl": _bm(52)}),
            ]
        }
    )
    tr = tl.tool_get_labs({"view": "trends", "biomarker": "hdl"})["trends"]["hdl"]
    # slope = +12/60 = 0.2/day exactly. One year from the last draw:
    #   with 365.25: 52 + 73.05 = 125.05     with 365: 52 + 73.0 = 125.0
    assert tr["slope_per_year"] == 73.05
    assert tr["projected_1yr"] == pytest.approx(tr["latest"] + tr["slope_per_year"], abs=0.01)


def test_trends_unknown_biomarker_names_itself_in_the_error(labs_table):
    labs_table({LABS_PK: [_draw("2026-01-01", {"ldl_c": _bm(130)})]})
    out = tl.tool_get_labs({"view": "trends", "biomarker": "not_a_marker"})
    assert out["trends"]["not_a_marker"]["error"] == "No data for 'not_a_marker'"
    assert "search_biomarker" in out["trends"]["not_a_marker"]["hint"]


def test_trends_without_a_biomarker_argument_says_so(labs_table):
    labs_table({LABS_PK: [_draw("2026-01-01", {"ldl_c": _bm(130)})]})
    out = tl.tool_get_labs({"view": "trends"})
    assert out["trends"] == {}  # today's behaviour, pinned
    assert "error" in out or "hint" in out


def test_trends_keeps_a_biomarker_measured_at_zero(labs_table):
    labs_table(
        {
            LABS_PK: [
                _draw("2026-01-01", {"crp_hs": _bm(0.0, category="inflammation", unit="mg/L")}),
                _draw("2026-03-02", {"crp_hs": _bm(1.2, category="inflammation", unit="mg/L")}),
            ]
        }
    )
    out = tl.tool_get_labs({"view": "trends", "biomarker": "crp_hs"})
    tr = out["trends"]["crp_hs"]
    assert tr["data_points"] == 2
    # The zero is present AS A ZERO, not merely counted — and it is the earliest point,
    # so it is the one the "total_change" and the slope both hinge on.
    assert [p["value"] for p in tr["values"]] == [0.0, 1.2]
    assert tr["earliest"] == 0.0
    assert tr["total_change"] == 1.2


def test_trends_survives_a_draw_with_no_draw_date(labs_table):
    bad = _draw("2026-01-01", {"ldl_c": _bm(130)})
    bad.pop("draw_date")  # sk is still DATE#2026-01-01
    labs_table({LABS_PK: [bad, _draw("2026-03-02", {"ldl_c": _bm(110)})]})
    out = tl.tool_get_labs({"view": "trends", "biomarker": "ldl_c"})
    assert "trends" in out


def test_trends_derived_ratios_are_hand_derived(labs_table):
    labs_table(
        {
            LABS_PK: [
                _draw(
                    "2026-01-01",
                    {
                        "triglycerides": _bm(150),
                        "hdl": _bm(50),
                        "cholesterol_total": _bm(200),
                    },
                )
            ]
        }
    )
    out = tl.tool_get_labs({"view": "trends", "biomarker": "hdl"})
    d = out["derived_ratios"]
    # tg/hdl  = 150/50  = 3.0
    # non-hdl = 200-50  = 150
    # tc/hdl  = 200/50  = 4.0
    assert d["tg_hdl_ratio"][0]["value"] == 3.0
    assert d["non_hdl_cholesterol"][0]["value"] == 150.0
    assert d["tc_hdl_ratio"][0]["value"] == 4.0
    # Each ratio carries the direction of "better" in its own interpretation string —
    # the guard against an inverted comparison downstream.
    assert "optimal <1.0" in d["tg_hdl_ratio"][0]["interpretation"]
    assert "optimal <130" in d["non_hdl_cholesterol"][0]["interpretation"]
    assert "optimal <3.5" in d["tc_hdl_ratio"][0]["interpretation"]


def test_trends_ratio_is_omitted_rather_than_divided_by_zero(labs_table):
    """A missing or zero HDL yields NO ratio — never a fabricated one (ADR-104).

    This used to hold for two reasons, only ONE of them deliberate: an explicit
    ``hdl_v > 0`` guard blocked the two divisions, and the truthiness ``or`` fallback
    turned a stored 0 into ``None`` so non-HDL (a subtraction, needing no guard of its
    own) dropped out by accident. Fixing the truthiness bug removed the accident —
    a real 0 would have started producing ``non_hdl = 200 - 0 = 200``. The guard now
    covers all three ratios on purpose: an HDL of 0 is not a physiologic measurement,
    so nothing derived from it is a number worth publishing.
    """
    labs_table({LABS_PK: [_draw("2026-01-01", {"triglycerides": _bm(150), "hdl": _bm(0), "cholesterol_total": _bm(200)})]})
    out = tl.tool_get_labs({"view": "trends", "biomarker": "triglycerides"})
    assert out.get("derived_ratios", {}) == {}
    assert "derived_ratios" not in out  # absent, not an empty shell


def test_trends_non_hdl_is_computed_without_a_division(labs_table):
    labs_table({LABS_PK: [_draw("2026-01-01", {"cholesterol_total": _bm(200), "hdl": _bm(62)})]})
    d = tl.tool_get_labs({"view": "trends", "biomarker": "hdl"})["derived_ratios"]
    # non-HDL = 200 - 62 = 138 -> "borderline 130-159" per its own interpretation band.
    assert d["non_hdl_cholesterol"][0]["value"] == 138.0
    assert "tg_hdl_ratio" not in d  # triglycerides absent -> no fabricated ratio


def test_trends_derived_ratios_suppressed_when_opted_out(labs_table):
    labs_table({LABS_PK: [_draw("2026-01-01", {"triglycerides": _bm(150), "hdl": _bm(50)})]})
    out = tl.tool_get_labs({"view": "trends", "biomarker": "hdl", "include_derived_ratios": False})
    assert "derived_ratios" not in out


def test_trends_single_draw_reports_insufficient_data_not_a_direction(labs_table):
    """One point is not a trend — ADR-105. Pinned as CORRECT behaviour."""
    labs_table({LABS_PK: [_draw("2026-01-01", {"ldl_c": _bm(130)})]})
    tr = tl.tool_get_labs({"view": "trends", "biomarker": "ldl_c"})["trends"]["ldl_c"]
    assert tr["data_points"] == 1
    assert tr["direction"] == "insufficient_data"
    assert tr["slope_per_year"] is None
    assert tr["projected_1yr"] is None


# ──────────────────────────────────────────────────────────────────────────────
# §4 — view = out_of_range (persistence classification)
# ──────────────────────────────────────────────────────────────────────────────


def test_out_of_range_flag_rate_and_ordering_are_hand_derived(labs_table):
    labs_table(
        {
            LABS_PK: [
                _draw("2026-01-01", {"ldl_c": _bm(160, flag="high"), "ferritin": _bm(20, flag="low", category="minerals")}),
                _draw("2026-03-02", {"ldl_c": _bm(155, flag="high"), "ferritin": _bm(90)}),
                _draw("2026-05-03", {"ldl_c": _bm(150, flag="high"), "ferritin": _bm(95)}),
            ]
        }
    )
    out = tl.tool_get_labs({"view": "out_of_range"})
    by_key = {f["biomarker"]: f for f in out["flagged_biomarkers"]}
    # ldl_c: flagged 3 of 3 tested -> 100.0% -> >=60 -> "chronic"
    assert by_key["ldl_c"]["times_flagged"] == 3
    assert by_key["ldl_c"]["times_tested"] == 3
    assert by_key["ldl_c"]["flag_rate_pct"] == 100.0
    assert by_key["ldl_c"]["persistence"] == "chronic"
    # ferritin: flagged 1 of 3 tested -> 33.3% -> >=30 and <60 -> "recurring"
    assert by_key["ferritin"]["flag_rate_pct"] == 33.3
    assert by_key["ferritin"]["persistence"] == "recurring"
    # Most-flagged first.
    assert [f["biomarker"] for f in out["flagged_biomarkers"]] == ["ldl_c", "ferritin"]
    assert out["chronic_flags"] == ["ldl_c"]
    assert out["total_unique_flags"] == 2
    assert out["date_range"] == "2026-01-01 to 2026-05-03"


def test_out_of_range_publishes_the_n_behind_every_rate(labs_table):
    """ADR-105: the denominator ships with the percentage, on every row."""
    labs_table({LABS_PK: [_draw("2026-01-01", {"ldl_c": _bm(160, flag="high")})]})
    out = tl.tool_get_labs({"view": "out_of_range"})
    for f in out["flagged_biomarkers"]:
        assert {"times_flagged", "times_tested", "flag_rate_pct"} <= set(f)


def test_out_of_range_does_not_call_a_single_observation_chronic(labs_table):
    labs_table({LABS_PK: [_draw("2026-01-01", {"ferritin": _bm(400, flag="high", category="minerals")})]})
    out = tl.tool_get_labs({"view": "out_of_range"})
    row = out["flagged_biomarkers"][0]
    assert row["times_tested"] == 1
    assert row["persistence"] == "single_observation"
    # …and the downstream consequence, which is the reason the label matters: the
    # "genetic baseline rather than lifestyle failure" narrative is keyed on chronic_flags.
    assert out["chronic_flags"] == []
    assert out["insight"] is None


def test_out_of_range_persistence_appears_at_the_derived_minimum_n(labs_table):
    """The threshold is derived from the module's own constant, not restated here."""
    assert tl.MIN_DRAWS_FOR_PERSISTENCE == 2
    draws = [
        _draw(f"2026-0{i + 1}-01", {"ferritin": _bm(400, flag="high", category="minerals")}) for i in range(tl.MIN_DRAWS_FOR_PERSISTENCE)
    ]
    labs_table({LABS_PK: draws})
    row = tl.tool_get_labs({"view": "out_of_range"})["flagged_biomarkers"][0]
    assert row["times_tested"] == tl.MIN_DRAWS_FOR_PERSISTENCE
    assert row["persistence"] == "chronic"


def test_out_of_range_reports_a_biomarker_measured_at_zero_as_zero(labs_table):
    """The same truthiness bug lived on the out_of_range value read (ADR-104)."""
    labs_table({LABS_PK: [_draw("2026-01-01", {"testosterone_total": _bm(0.0, flag="low", category="hormones", unit="ng/dL")})]})
    row = tl.tool_get_labs({"view": "out_of_range"})["flagged_biomarkers"][0]
    assert row["occurrences"][0]["value"] == 0.0  # not None, not dropped


def test_out_of_range_empty_when_nothing_ever_flagged(labs_table):
    labs_table({LABS_PK: [_draw("2026-01-01", {"ldl_c": _bm(90)})]})
    out = tl.tool_get_labs({"view": "out_of_range"})
    assert out["flagged_biomarkers"] == []
    assert out["chronic_flags"] == []
    assert out["genome_drivers"] is None
    assert out["insight"] is None  # no fabricated narrative on an empty set


# ──────────────────────────────────────────────────────────────────────────────
# §5 — Genome annotation + the privacy guardrail
# ──────────────────────────────────────────────────────────────────────────────


GENOME_ROWS = [
    {
        "pk": GENOME_PK,
        "sk": "SNP#rs9939609",
        "gene": "FTO",
        "rsid": "rs9939609",
        "genotype": "A;T",
        "risk_level": "elevated",
        "summary": "obesity predisposition",
    },
    {
        "pk": GENOME_PK,
        "sk": "SNP#rs1801133",
        "gene": "MTHFR",
        "rsid": "rs1801133",
        "genotype": "C;T",
        "risk_level": "moderate",
        "summary": "folate metabolism",
    },
]


def test_genome_context_annotates_only_the_cross_referenced_biomarkers(labs_table):
    labs_table({LABS_PK: [_draw("2026-01-01", {"glucose": _bm(99, category="metabolic")})], GENOME_PK: GENOME_ROWS})
    out = tl.tool_get_labs({"view": "results", "draw_date": "2026-01-01"})
    # glucose maps to FTO/IRS1/TCF7L2 in labs_helpers._GENOME_LAB_XREF; only FTO is seeded.
    assert [s["gene"] for s in out["genome_context"]["glucose"]] == ["FTO"]
    # MTHFR is present in the partition but maps to homocysteine/folate/b12 — not here.
    assert "homocysteine" not in out["genome_context"]


def test_genome_context_absent_rather_than_empty_when_nothing_matches(labs_table):
    labs_table({LABS_PK: [_draw("2026-01-01", {"tsh": _bm(2.1, category="thyroid", unit="uIU/mL")})], GENOME_PK: GENOME_ROWS})
    out = tl.tool_get_labs({"view": "results", "draw_date": "2026-01-01"})
    assert out["genome_context"] is None


def test_genome_bearing_response_carries_the_privacy_notice(labs_table):
    """#2241 — the module's SEC-GENOME banner claims the notice 'is appended to all
    genome-bearing tool outputs'. Before the fix the constant was referenced nowhere:
    the sole declared control on the one surface that really does return gene names,
    rsIDs and genotypes was inert."""
    labs_table({LABS_PK: [_draw("2026-01-01", {"glucose": _bm(99, category="metabolic")})], GENOME_PK: GENOME_ROWS})
    out = tl.tool_get_labs({"view": "results", "draw_date": "2026-01-01"})
    assert out["genome_context"]["glucose"][0]["rsid"] == "rs9939609"  # identifiers really are returned
    assert out[tl._GENOME_PRIVACY_NOTICE_KEY] == tl._GENOME_PRIVACY_NOTICE


def test_trends_view_genome_response_carries_the_privacy_notice(labs_table):
    labs_table({LABS_PK: [_draw("2026-01-01", {"glucose": _bm(99, category="metabolic")})], GENOME_PK: GENOME_ROWS})
    out = tl.tool_get_labs({"view": "trends", "biomarker": "glucose"})
    assert out["genome_context"]["glucose"][0]["genotype"] == "A;T"
    assert out[tl._GENOME_PRIVACY_NOTICE_KEY] == tl._GENOME_PRIVACY_NOTICE


def test_out_of_range_view_genome_response_carries_the_privacy_notice(labs_table):
    # Flagged on BOTH draws → 2/2 → 100% over n=2 → "chronic" → genome_drivers populated.
    # (Two draws, not one: a single observation no longer earns a persistence class.)
    labs_table(
        {
            LABS_PK: [
                _draw("2026-01-01", {"glucose": _bm(126, flag="high", category="metabolic")}),
                _draw("2026-03-02", {"glucose": _bm(131, flag="high", category="metabolic")}),
            ],
            GENOME_PK: GENOME_ROWS,
        }
    )
    out = tl.tool_get_labs({"view": "out_of_range"})
    assert out["genome_drivers"]["glucose"][0]["gene"] == "FTO"
    assert out[tl._GENOME_PRIVACY_NOTICE_KEY] == tl._GENOME_PRIVACY_NOTICE


def test_response_without_genome_identifiers_carries_no_notice(labs_table):
    """The notice is a signal, not boilerplate — a response with no identifiers in it
    must not carry one, or the notice stops meaning anything."""
    labs_table({LABS_PK: [_draw("2026-01-01", {"tsh": _bm(2.1, category="thyroid", unit="uIU/mL")})], GENOME_PK: GENOME_ROWS})
    out = tl.tool_get_labs({"view": "results", "draw_date": "2026-01-01"})
    assert out["genome_context"] is None
    assert tl._GENOME_PRIVACY_NOTICE_KEY not in out


def test_notice_detection_is_structural_not_keyed_on_todays_response_shape():
    """DERIVED guard, not a restatement of the three call sites: the detector keys on the
    identifier FIELDS, so a future view shipping them under a new container key is covered
    without editing the module. Both directions are pinned."""
    snp = {"gene": "FTO", "rsid": "rs9939609", "genotype": "A;T"}
    assert tl._carries_genome_identifiers({"some_future_key": {"glucose": [snp]}}) is True
    assert tl._carries_genome_identifiers({"deeply": {"nested": {"under": {"a": {"new": {"shape": snp}}}}}}) is True
    # An empty/absent identifier is not "bearing" — `_genome_context_for_biomarkers`
    # returns {} rather than a stub row when nothing matches.
    assert tl._carries_genome_identifiers({"genome_context": None}) is False
    assert tl._carries_genome_identifiers({"genome_context": {}}) is False
    assert tl._carries_genome_identifiers({"biomarkers": {"ldl_c": {"value": 130, "flag": "high"}}}) is False


def test_every_genome_producer_routes_through_the_notice_chokepoint():
    """'Guard the SET, not the instance': the notice is attached once, at the
    `tool_get_labs` dispatcher. This asserts that EVERY function calling
    `_genome_context_for_biomarkers` is one of the dispatched views, so a fourth
    view (or a new tool) cannot produce genome identifiers that bypass the chokepoint.
    """
    import ast
    import pathlib

    src = pathlib.Path(tl.__file__).with_suffix(".py").read_text()
    tree = ast.parse(src)

    producers = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name) and sub.func.id == "_genome_context_for_biomarkers":
                    producers.add(node.name)
    assert producers, "AST scan found no genome producers — the scan itself has broken"

    dispatched = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "tool_get_labs":
            for sub in ast.walk(node):
                if isinstance(sub, ast.Assign) and isinstance(sub.value, ast.Dict):
                    dispatched.update(v.id for v in sub.value.values if isinstance(v, ast.Name))
    assert producers <= dispatched, f"genome producers outside the tool_get_labs dispatcher: {sorted(producers - dispatched)}"

    # And no OTHER mcp module pulls the producer in directly, which would route around it.
    mcp_dir = pathlib.Path(tl.__file__).parent
    importers = sorted(
        p.name
        for p in mcp_dir.glob("*.py")
        if p.name not in ("tools_labs.py", "labs_helpers.py") and "_genome_context_for_biomarkers" in p.read_text()
    )
    assert importers == [], f"modules bypassing the SEC-GENOME chokepoint: {importers}"


def test_trends_view_also_carries_the_genome_context(labs_table):
    labs_table({LABS_PK: [_draw("2026-01-01", {"glucose": _bm(99, category="metabolic")})], GENOME_PK: GENOME_ROWS})
    out = tl.tool_get_labs({"view": "trends", "biomarker": "glucose"})
    assert out["genome_context"]["glucose"][0]["gene"] == "FTO"


def test_out_of_range_attaches_genome_drivers_only_to_chronic_flags(labs_table):
    labs_table(
        {
            LABS_PK: [
                _draw("2026-01-01", {"glucose": _bm(126, flag="high", category="metabolic")}),
                _draw("2026-03-02", {"glucose": _bm(131, flag="high", category="metabolic")}),
            ],
            GENOME_PK: GENOME_ROWS,
        }
    )
    out = tl.tool_get_labs({"view": "out_of_range"})
    assert out["chronic_flags"] == ["glucose"]
    assert out["genome_drivers"]["glucose"][0]["gene"] == "FTO"
    assert "genetic baseline rather than lifestyle failure" in out["insight"]


def test_genome_partition_is_read_once_and_cached_across_views(labs_table):
    """The genome cache is a module global — pinned so a future edit cannot turn
    every lab view into an extra full-partition scan without this failing."""
    t = labs_table({LABS_PK: [_draw("2026-01-01", {"glucose": _bm(99, category="metabolic")})], GENOME_PK: GENOME_ROWS})
    tl.tool_get_labs({"view": "results", "draw_date": "2026-01-01"})
    tl.tool_get_labs({"view": "results", "draw_date": "2026-01-01"})
    genome_reads = [c for c in t.query_calls if _pk_of(c) == GENOME_PK]
    assert len(genome_reads) == 1


# ──────────────────────────────────────────────────────────────────────────────
# §6 — ADR-058: labs is CROSS_PHASE, so the read must NOT be phase-filtered
# ──────────────────────────────────────────────────────────────────────────────


def test_labs_partition_class_is_cross_phase_in_the_taxonomy():
    """DERIVED from the registry that both the tagger and the wipe read."""
    assert phase_taxonomy.classify(LABS_PK, "DATE#2026-01-01") == phase_taxonomy.CROSS_PHASE
    assert phase_taxonomy.never_touch(phase_taxonomy.CROSS_PHASE)


def test_labs_query_carries_no_phase_filter(labs_table):
    """A phase filter on a CROSS_PHASE clinical archive would silently truncate
    Matthew's lab history to the current experiment cycle after every reset."""
    t = labs_table({LABS_PK: [_draw("2026-01-01", {"ldl_c": _bm(130)})]})
    tl.tool_get_labs({"view": "results"})
    lab_reads = [c for c in t.query_calls if _pk_of(c) == LABS_PK]
    assert lab_reads
    for call in lab_reads:
        assert "FilterExpression" not in call


# ──────────────────────────────────────────────────────────────────────────────
# §7 — FH v2 cadence trackers (NfL 180d / Galleri 365d)
# ──────────────────────────────────────────────────────────────────────────────


def _cadence_draws():
    return {
        LABS_PK: [
            _draw(
                "2025-06-01",
                {"nfl_neurofilament_light_chain": _bm(9.0, category="neuro", unit="pg/mL")},
            ),
            _draw(
                "2026-02-08",
                {
                    "nfl_neurofilament_light_chain": _bm(11.0, category="neuro", unit="pg/mL"),
                    "galleri_cancer_signal": {"value": "NO CANCER SIGNAL DETECTED", "category": "screening"},
                },
            ),
        ]
    }


def test_cadence_trackers_use_the_latest_draw_and_hand_derived_due_dates(labs_table):
    labs_table(_cadence_draws())
    out = tl.tool_get_labs({"view": "results"})
    ct = out["cadence_trackers"]
    # Frozen today = 2026-08-08. Latest NfL draw = 2026-02-08 (NOT the 2025-06-01 one:
    # _latest_for walks `reversed(draws)` over an sk-sorted list, so it really is latest-first —
    # this is the sorting that tranche 2 found missing on DEXA).
    #   days_since = 2026-02-08 -> 2026-08-08 = 21+31+30+31+30+31+8 = 181
    #   next_due   = 2026-02-08 + 180d = 2026-08-07
    assert ct["nfl"]["last_drawn"] == "2026-02-08"
    assert ct["nfl"]["days_since_last"] == 181
    assert ct["nfl"]["recommended_cadence_days"] == tl.NFL_CADENCE_DAYS == 180
    assert ct["nfl"]["next_due"] == "2026-08-07"
    # History is chronological and keeps both draws with their units.
    assert [h["date"] for h in ct["nfl"]["history"]] == ["2025-06-01", "2026-02-08"]
    assert ct["nfl"]["history"][0]["unit"] == "pg/mL"
    #   Galleri: 2026-02-08 + 365d = 2027-02-08
    assert ct["galleri"]["next_due"] == "2027-02-08"
    assert ct["galleri"]["recommended_cadence_days"] == tl.GALLERI_CADENCE_DAYS == 365


def test_galleri_signal_is_reframed_as_absence_of_evidence(labs_table):
    labs_table(_cadence_draws())
    ct = tl.tool_get_labs({"view": "results"})["cadence_trackers"]
    assert ct["galleri"]["last_signal"] == "No signal detected at 24-month early-detection threshold"


def test_galleri_raw_signal_is_not_republished_beside_the_reframe(labs_table):
    labs_table(_cadence_draws())
    ct = tl.tool_get_labs({"view": "results"})["cadence_trackers"]
    assert "NO CANCER SIGNAL DETECTED" not in str(ct["galleri"])
    # Whole-subtree, not just the `raw_signal` key the report named: the history
    # entries republished the identical raw string one level down, so deleting
    # `raw_signal` alone would have left the board's framing decision unenforced.
    assert ct["galleri"]["history"][-1]["signal"] == "No signal detected at 24-month early-detection threshold"


def test_galleri_non_standard_signal_is_passed_through_unreframed(labs_table):
    """The reframe is keyed on two literals; anything else is surfaced verbatim,
    which is the right default for a result that is NOT an all-clear."""
    labs_table(
        {
            LABS_PK: [
                _draw("2026-02-08", {"galleri_cancer_signal": {"value": "Signal detected — origin: colorectal", "category": "screening"}})
            ]
        }
    )
    ct = tl.tool_get_labs({"view": "results"})["cadence_trackers"]
    assert ct["galleri"]["last_signal"] == "Signal detected — origin: colorectal"


def test_cadence_unparseable_draw_date_yields_none_not_a_zero_day_gap(labs_table):
    """ADR-104: an undatable draw reports NO interval, never 'drawn 0 days ago'."""
    labs_table(
        {LABS_PK: [_draw("2026-02-08", {"nfl_neurofilament_light_chain": _bm(11.0, category="neuro", unit="pg/mL")}, draw_date="Feb 2026")]}
    )
    ct = tl.tool_get_labs({"view": "results"})["cadence_trackers"]
    assert ct["nfl"]["last_drawn"] == "Feb 2026"
    assert ct["nfl"]["days_since_last"] is None
    assert ct["nfl"]["next_due"] is None


def test_cadence_trackers_empty_when_the_sentinel_panels_were_never_drawn(labs_table):
    labs_table({LABS_PK: [_draw("2026-01-01", {"ldl_c": _bm(130)})]})
    out = tl.tool_get_labs({"view": "results"})
    assert out["cadence_trackers"] == {}  # absent, not a fabricated zero-day tracker


def test_cadence_tracker_failure_never_takes_down_the_view(labs_table, monkeypatch):
    labs_table({LABS_PK: [_draw("2026-01-01", {"ldl_c": _bm(130)})]})
    monkeypatch.setattr(tl, "_build_cadence_trackers", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    out = tl.tool_get_labs({"view": "results"})
    assert out["total_draws"] == 1
    assert "cadence_trackers" not in out


def test_cadence_clock_is_the_platform_clock(labs_table):
    """The cadence clock reads the PACIFIC day the platform keys its data by.

    Behavioural, not a source grep. The instant below is 2026-08-09 03:00Z — still
    2026-08-08 in Pacific. A naive `datetime.now()` (LOCAL, i.e. UTC on the Lambda
    host) reads 2026-08-09 and reports one extra day since the draw, every day, for
    the whole UTC-evening window; that was a THIRD clock in a module whose freshness
    tool already runs on UTC.
    """
    labs_table(_cadence_draws())
    _FROZEN[0] = datetime(2026, 8, 9, 3, 0, 0, tzinfo=timezone.utc)
    ct = tl.tool_get_labs({"view": "results"})["cadence_trackers"]
    # 2026-02-08 -> 2026-08-08 (Pacific) = 181 days. A UTC/local clock would say 182.
    assert ct["nfl"]["days_since_last"] == 181

    # And the bare zero-argument `datetime.now()` cannot come back. AST, not a
    # substring: the docstring and comments above legitimately quote the bad call.
    import ast
    import inspect
    import textwrap

    tree = ast.parse(textwrap.dedent(inspect.getsource(tl._build_cadence_trackers)))
    bare = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "attr", None) == "now" and not (n.args or n.keywords)]
    assert bare == [], "_build_cadence_trackers is back on a naive local clock"


# ──────────────────────────────────────────────────────────────────────────────
# §8 — get_freshness_status
# ──────────────────────────────────────────────────────────────────────────────

FRESH_SOURCES = mcp_sources()  # DERIVED from ingestion.source_registry, never restated
FRESH_OVERRIDES = stale_hours_overrides(FRESH_SOURCES)


def _src_pk(src: str) -> str:
    return f"USER#matthew#SOURCE#{src}"


def _date_row(src: str, date: str, **extra) -> dict:
    row = {"pk": _src_pk(src), "sk": f"DATE#{date}", "date": date}
    row.update(extra)
    return row


@pytest.fixture
def freshness_table(monkeypatch):
    def _install(rows_by_pk, **kw):
        t = FakeFreshnessTable(rows_by_pk, **kw)
        monkeypatch.setattr(tl, "table", t)
        return t

    return _install


def test_freshness_fresh_source_age_is_hand_derived(freshness_table):
    freshness_table({_src_pk("whoop"): [_date_row("whoop", "2026-08-07"), _date_row("whoop", "2026-08-08")]})
    out = tl.tool_get_freshness_status({"sources": ["whoop"]})
    row = out["fresh_sources"][0]
    # Frozen today = 2026-08-08, newest whoop row = 2026-08-08 -> age 0 days.
    # whoop has no stale_hours override, so DEFAULT_STALE_HOURS (48h) -> 2.0 days.
    assert row["last_date"] == "2026-08-08"
    assert row["age_days"] == 0
    assert row["threshold_days"] == DEFAULT_STALE_HOURS // 24 == 2
    assert out["status"] == "green"
    assert out["stale_count"] == 0 and out["fresh_count"] == 1


def test_freshness_reads_the_newest_row_not_the_first(freshness_table):
    """ScanIndexForward=False + Limit=1 — the "latest" read that tranche 2 found
    missing elsewhere. Seeded out of order on purpose."""
    t = freshness_table(
        {
            _src_pk("whoop"): [
                _date_row("whoop", "2026-08-08"),
                _date_row("whoop", "2025-01-01"),
                _date_row("whoop", "2026-03-03"),
            ]
        }
    )
    out = tl.tool_get_freshness_status({"sources": ["whoop"]})
    assert out["fresh_sources"][0]["last_date"] == "2026-08-08"
    latest_call = next(c for c in t.query_calls if _pk_of(c) == _src_pk("whoop"))
    assert latest_call["ScanIndexForward"] is False and latest_call["Limit"] == 1


def test_freshness_stale_source_crosses_at_its_own_registry_threshold(freshness_table):
    # macrofactor's registry override is 96h -> 4.0 days. 2026-08-04 is exactly 4 days
    # before the frozen today, and the comparison is `>=`, so it is stale at the boundary.
    assert FRESH_OVERRIDES["macrofactor"] == 96
    freshness_table({_src_pk("macrofactor"): [_date_row("macrofactor", "2026-08-04", entries_count=12)]})
    out = tl.tool_get_freshness_status({"sources": ["macrofactor"]})
    assert out["stale_sources"][0]["age_days"] == 4
    assert out["stale_sources"][0]["status"] == "stale"
    # 1 stale, age 4 (<7) -> yellow
    assert out["status"] == "yellow"


def test_freshness_source_that_never_wrote_is_no_data_not_fresh(freshness_table):
    freshness_table({})
    out = tl.tool_get_freshness_status({"sources": ["whoop"]})
    assert out["stale_count"] == 1
    assert out["stale_sources"][0]["status"] == "no_data"
    assert out["fresh_sources"] == []


def test_freshness_no_data_rows_omit_the_age_key_the_stale_rows_publish(freshness_table):
    """Envelope parity inside one list: `stale_sources` mixes two row shapes.

    Pinned (not xfail'd) because it is the documented shape today — a consumer
    iterating `stale_sources` and reading `age_days` must use `.get`.
    """
    freshness_table({_src_pk("macrofactor"): [_date_row("macrofactor", "2026-01-01", entries_count=3)]})
    out = tl.tool_get_freshness_status({"sources": ["whoop", "macrofactor"]})
    shapes = {r["status"]: set(r) for r in out["stale_sources"]}
    assert "age_days" in shapes["stale"]
    assert "age_days" not in shapes["no_data"]
    assert "last_date" not in shapes["no_data"]


def test_freshness_query_failure_surfaces_the_source_and_its_error(freshness_table):
    """A throttled partition read is the SECOND path into the same blindness.

    It used to build a `status: unknown` row that neither `stale_sources` nor
    `fresh_sources` selected, so the source vanished and the answer was green. The
    fix is at the buckets, not at one call site — this is the sibling path.
    """
    freshness_table({}, raises_for={_src_pk("whoop")})
    out = tl.tool_get_freshness_status({"sources": ["whoop"]})
    reported = {r["source"] for r in out["stale_sources"] + out["fresh_sources"]}
    assert reported == {"whoop"}
    row = out["stale_sources"][0]
    assert row["status"] == "unreadable"
    assert "throttled" in row["error"]
    assert out["unreadable_count"] == 1
    assert out["fresh_count"] == 0
    assert out["status"] != "green"


def test_freshness_never_reports_green_about_a_source_it_could_not_read(freshness_table):
    freshness_table(
        {
            _src_pk("whoop"): [_date_row("whoop", "2026-08-08")],
            # A corrupt high-water row: present, but not a DATE# sk.
            _src_pk("apple_health"): [{"pk": _src_pk("apple_health"), "sk": "SUMMARY#latest"}],
        }
    )
    out = tl.tool_get_freshness_status({"sources": ["whoop", "apple_health"]})
    reported = {r["source"] for r in out["stale_sources"] + out["fresh_sources"]}
    assert reported == {"whoop", "apple_health"}
    assert out["status"] != "green"


def test_freshness_answers_about_every_requested_source_whatever_its_partition_holds(freshness_table):
    """GUARD THE SET: the response covers every source asked about, not the readable ones.

    Five partition shapes, four of them previously exiting the loop silently by three
    different routes (bare `continue` x2, an `unknown` row no bucket selected). The
    assertion is over the whole requested SET, so a fourth silent exit added later
    fails here without anyone remembering to add a case.
    """
    shapes = {
        "whoop": [_date_row("whoop", "2026-08-08")],  # fresh
        "macrofactor": [_date_row("macrofactor", "2026-01-01")],  # stale
        "strava": [],  # never wrote -> no_data
        "apple_health": [{"pk": _src_pk("apple_health"), "sk": "SUMMARY#latest"}],  # non-DATE# sk
        "eightsleep": [{"pk": _src_pk("eightsleep"), "sk": "DATE#2026-13-45"}],  # unparseable date
    }
    assert set(shapes) <= set(FRESH_SOURCES), "fixture drifted from the source registry"
    freshness_table({_src_pk(s): rows for s, rows in shapes.items()}, raises_for={_src_pk("garmin")})
    requested = sorted(shapes) + ["garmin"]  # + a partition read that throws

    out = tl.tool_get_freshness_status({"sources": requested})
    reported = {r["source"] for r in out["stale_sources"] + out["fresh_sources"]}
    assert reported == set(requested)
    assert out["fresh_count"] == 1  # whoop only
    assert out["unreadable_count"] == 3  # apple_health, eightsleep, garmin
    assert out["stale_count"] == len(out["stale_sources"])  # the counter and the list agree
    assert out["status"] == "red"


def test_freshness_macrofactor_drift_probe_reports_its_own_failure(freshness_table):
    freshness_table({}, raises_for={_src_pk("macrofactor")})
    out = tl.tool_get_freshness_status({"sources": ["macrofactor"]})
    assert out["macrofactor_format_drift"]["drifted"] is None  # unknown, not "healthy"
    assert "error" in out["macrofactor_format_drift"]


def test_freshness_unparseable_date_in_the_sort_key(freshness_table):
    """A DATE# sk whose payload is not a calendar date is the THIRD path in.

    2026-13-45 is a well-formed sk carrying a nonexistent date. It used to take the
    same silent `continue` as the corrupt-sk case; now it is reported unreadable with
    the offending key quoted, so the row is findable rather than merely absent."""
    freshness_table({_src_pk("whoop"): [{"pk": _src_pk("whoop"), "sk": "DATE#2026-13-45"}]})
    out = tl.tool_get_freshness_status({"sources": ["whoop"]})
    assert out["fresh_sources"] == []
    row = out["stale_sources"][0]
    assert row["source"] == "whoop" and row["status"] == "unreadable"
    assert "DATE#2026-13-45" in row["reason"]
    assert out["status"] != "green"


def test_freshness_unknown_source_keys_are_refused_not_fabricated(freshness_table):
    """SUPERSEDED BY #2662 — the anti-fabrication half stands, the silence half does not.

    This test used to assert that `["whoop", "not_a_source"]` returned whoop fresh and
    nothing stale. The no-fabrication half of that is still the ruling and is still
    asserted below: an unknown key must never produce an invented row.

    What #2662 overturned is the other half. Dropping the name meant the call answered
    `status: green` over a set that was NOT the set the caller asked about, so a typo or
    a registry rename read as "everything is fresh" — from the one tool whose job is
    answering "are we OK?". The verdict is a claim about a set; if the set is wrong, the
    verdict is wrong, not partial. See tests/test_mcp_freshness_unknown_source_2662.py.
    """
    freshness_table({_src_pk("whoop"): [_date_row("whoop", "2026-08-08")]})
    out = tl.tool_get_freshness_status({"sources": ["whoop", "not_a_source"]})
    assert "error" in out and "not_a_source" in out["error"]
    assert out.get("status") != "green"
    assert "fresh_sources" not in out and "stale_sources" not in out, "nothing may be fabricated for an unknown key"


def test_freshness_defaults_to_the_full_registry_source_set(freshness_table):
    """The default sweep is DERIVED from ingestion.source_registry.mcp_sources()."""
    t = freshness_table({})
    tl.tool_get_freshness_status({})
    swept = {_pk_of(c) for c in t.query_calls}
    assert {_src_pk(s) for s in FRESH_SOURCES} <= swept


def test_freshness_escalation_tiers_are_hand_derived(freshness_table):
    # Three stale sources -> red (stale_count >= 3), regardless of age.
    #
    # #2715: the third source used to be `garmin`, which is paused by design (ADR-074) and
    # no longer counts toward stale_count — so the case would have silently degraded to a
    # 2-source test of a >=3 threshold, i.e. it would have stopped exercising the tier it
    # is named after. Swapped for `eightsleep`, a live source, so the assertion still means
    # what it says. The paused-source behaviour has its own coverage in
    # tests/test_paused_is_not_stale_2715.py.
    rows = {_src_pk(s): [_date_row(s, "2026-07-01")] for s in ("whoop", "strava", "eightsleep")}
    freshness_table(rows)
    out = tl.tool_get_freshness_status({"sources": ["whoop", "strava", "eightsleep"]})
    # 2026-07-01 -> 2026-08-08 = 30 + 8 = 38 days; all three exceed their thresholds.
    assert all(r["age_days"] == 38 for r in out["stale_sources"])
    assert out["stale_count"] == 3
    assert out["status"] == "red"


def test_freshness_two_stale_sources_inside_the_window_are_orange(freshness_table):
    rows = {_src_pk(s): [_date_row(s, "2026-08-05")] for s in ("whoop", "strava")}
    freshness_table(rows)
    out = tl.tool_get_freshness_status({"sources": ["whoop", "strava"]})
    # 2026-08-05 -> 2026-08-08 = 3 days, both past their 48h default -> 2 stale, max age 3.
    assert out["stale_count"] == 2
    assert out["status"] == "orange"


def test_freshness_thresholds_note_indexes_keys_the_registry_must_still_carry():
    """`thresholds_note` (line 683) hard-indexes SOURCE_STALE_HOURS['food_delivery']
    and ['measurements']. If either loses its registry override the f-string raises
    KeyError and the WHOLE freshness tool 500s. Derived guard, not a restated list."""
    for key in ("food_delivery", "measurements"):
        assert key in FRESH_OVERRIDES, f"tool_get_freshness_status hard-indexes SOURCE_STALE_HOURS[{key!r}]"


def test_every_registry_threshold_is_a_whole_number_of_days():
    """`threshold_days` is reported as `int(hours/24)` (line 569) but compared as a
    float (line 560). Whole-day thresholds keep the two identical; a 36h threshold
    would report '1 day' while enforcing 1.5. Derived guard over the whole set."""
    for key, hours in FRESH_OVERRIDES.items():
        assert hours % 24 == 0, f"{key}={hours}h would be misreported by int(hours/24)"
    assert DEFAULT_STALE_HOURS % 24 == 0


def test_freshness_flags_macrofactor_summary_format_drift(freshness_table):
    """A source can be perfectly FRESH and still be starving the meal grouper."""
    freshness_table(
        {
            _src_pk("macrofactor"): [
                _date_row("macrofactor", "2026-08-07", entries_count=0),
                _date_row("macrofactor", "2026-08-08", entries_count=0),
            ]
        }
    )
    out = tl.tool_get_freshness_status({"sources": ["macrofactor"]})
    drift = out["macrofactor_format_drift"]
    assert drift["drifted"] is True
    assert drift["records_checked"] == 2 and drift["consecutive_empty"] == 2
    assert drift["last_food_log_date"] is None
    assert "starved" in drift["note"]


def test_freshness_macrofactor_healthy_when_a_food_log_is_present(freshness_table):
    freshness_table(
        {
            _src_pk("macrofactor"): [
                _date_row("macrofactor", "2026-08-07", entries_count=14),
                _date_row("macrofactor", "2026-08-08", entries_count=0),
            ]
        }
    )
    drift = tl.tool_get_freshness_status({"sources": ["macrofactor"]})["macrofactor_format_drift"]
    assert drift["drifted"] is False
    # Newest-first scan, so the first row carrying a log is the most recent one.
    assert drift["last_food_log_date"] == "2026-08-07"


def test_freshness_macrofactor_block_is_absent_when_not_requested(freshness_table):
    freshness_table({_src_pk("whoop"): [_date_row("whoop", "2026-08-08")]})
    out = tl.tool_get_freshness_status({"sources": ["whoop"]})
    assert out["macrofactor_format_drift"] is None


def test_freshness_surfaces_an_interior_gap_behind_the_high_water_mark(freshness_table):
    """The Strava-walks blindness: newest row present, a hole two days back.

    (`find_interior_gaps` itself is covered by tests/test_freshness_interior_gaps_mcp.py;
    what is pinned here is that the freshness ENVELOPE actually runs it and reports
    a non-zero count for a daily source.)
    """
    freshness_table(
        {
            _src_pk("whoop"): [
                _date_row("whoop", "2026-08-05"),
                # 2026-08-06 missing
                _date_row("whoop", "2026-08-07"),
                _date_row("whoop", "2026-08-08"),
            ]
        }
    )
    out = tl.tool_get_freshness_status({"sources": ["whoop"]})
    assert out["interior_gaps"] == {"whoop": ["2026-08-06"]}
    assert out["interior_gap_count"] == 1
    # …and the source still reads "fresh", which is exactly why the gap scan exists.
    assert out["fresh_sources"][0]["status"] == "fresh"


def test_freshness_interior_scan_only_covers_the_daily_source_set(freshness_table):
    """DERIVED from the module's own DAILY_SOURCES_INTERIOR — sparse sources are
    excluded because an empty day there is legitimate, not a hole."""
    sparse = sorted(set(FRESH_SOURCES) - tl.DAILY_SOURCES_INTERIOR)
    assert sparse, "every registry source is marked daily — the exclusion has stopped meaning anything"
    freshness_table({_src_pk(s): [_date_row(s, "2026-08-05"), _date_row(s, "2026-08-08")] for s in sparse})
    out = tl.tool_get_freshness_status({"sources": sparse})
    assert out["interior_gaps"] == {}


# ──────────────────────────────────────────────────────────────────────────────
# §9 — the ImmunoCAP allergen surface (pure helpers)
# ──────────────────────────────────────────────────────────────────────────────


def test_ige_class_boundaries_are_exact_at_every_edge():
    """Derived from `_IGE_CLASS_BOUNDARIES` itself: each boundary is the FIRST value
    of the next class, and one ulp below it still belongs to the previous one."""
    prev_class = 0
    for boundary, cls in tl._IGE_CLASS_BOUNDARIES:
        assert tl._ige_class(boundary - 1e-9) == cls, f"just below {boundary} must stay class {cls}"
        prev_class = cls
    assert prev_class == 5
    # Above the last boundary (50.0 kU/L) everything is the maximum class.
    assert tl._ige_class(50.0) == 6
    assert tl._ige_class(1e6) == 6
    # And the label table covers exactly classes 0-6.
    assert set(tl._IGE_CLASS_LABELS) == set(range(7))


def test_ige_class_is_absent_for_unmeasurable_input():
    assert tl._ige_class(None) is None
    assert tl._ige_class("not a number") is None
    assert tl._ige_class("0.5") == 2  # a numeric string is still measured: 0.35 <= 0.5 < 0.70


def test_allergen_meta_strips_the_prefix_and_categorises():
    assert tl._allergen_meta("allergy_cat_dander") == ("cat_dander", "dander")
    assert tl._allergen_meta("allergy_birch") == ("birch", "environmental_pollen")
    assert tl._allergen_meta("allergy_unknown_thing") == ("unknown_thing", "other")
    # Only the FIRST occurrence is stripped, so a doubled prefix is not silently eaten.
    assert tl._allergen_meta("allergy_allergy_birch")[0] == "allergy_birch"


def test_every_allergen_category_value_is_one_of_the_documented_five():
    assert set(tl._ALLERGEN_CATEGORIES.values()) == {"dust_mite", "environmental_pollen", "dander", "mold", "other"}


def test_the_allergen_surface_is_unreachable_from_the_registry():
    """`_ALLERGEN_CATEGORIES`'s comment says the categories are 'used in the
    get_allergies response'. No such tool exists, and no registry handler calls
    `_ige_class`/`_allergen_meta` — the whole surface is dead code. Derived from
    the registry so it flips green the day the tool is actually wired up.

    (Reported as P3 rather than xfail'd: dead code is not a wrong number.)
    """
    assert "get_allergies" not in TOOLS
    import inspect

    callers = [name for name, spec in TOOLS.items() if "_ige_class" in inspect.getsource(spec["fn"])]
    assert callers == []
