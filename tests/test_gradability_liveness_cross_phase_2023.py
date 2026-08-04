"""tests/test_gradability_liveness_cross_phase_2023.py — #2023: the #813 gradability
gate reads raw-source liveness CROSS-PHASE.

The #813 write-time gate downgrades a metric-backed prediction to `qualitative`
unless its source shows >= 5 numeric values in the last 30 days — a good gate: a
prediction about `blood_glucose_avg` with the CGM sensor inactive can only ever
expire inconclusive. But the liveness query applied `with_phase_filter`, and the
experiment reset tags every pre-genesis row `phase=pilot` (ADR-077). So in a young
cycle the 30-day lookback could only see the days elapsed SINCE genesis: on Day 1
that is one row, far under the 5-point bar, and essentially every correctly
extracted metric prediction fell to qualitative. Measured on cycle 11: ~1.4%
gradable share against a ~9% pilot baseline — the ADR-105 graded track record
could not accumulate exactly in the window where a reader is watching a fresh
cycle start.

That is a recurrence of the CLOSED #1203 class (a phase filter blinding a
raw-timeseries consumer) in a different consumer, so this file guards on three
levels:

  1. the instance — a genesis-day scenario where the pre-genesis rows are all
     phase-tagged and liveness must still see them;
  2. the SET OF SOURCES this consumer reads — derived from `METRIC_SOURCES` and
     checked against `phase_taxonomy`, so a future metric mapped to a source
     that IS legitimately phase-scoped cannot sneak past the reasoning above;
  3. the SET OF CALL SITES — every raw-source read in `lambdas/` that applies the
     phase filter is derived by AST scan and must be either cross-phase or
     explicitly sanctioned as a current-cycle view. A new raw-source consumer
     fails this guard until someone classifies it.

The fake table below is faithful where it matters: it applies the phase
FilterExpression, and it honours the `sk BETWEEN` bounds — so the "a genuinely
stale source is still rejected" test is non-vacuous (the 30-day WINDOW, not the
phase tag, is what bounds recency).
"""

from __future__ import annotations

import ast
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "lambdas"))
sys.path.insert(0, str(REPO_ROOT / "lambdas" / "coach"))

import coach_state_updater as updater  # noqa: E402
from common.constants import EXPERIMENT_PHASE_CURRENT  # noqa: E402
from experiment import (
    measurable_metrics as mm,  # noqa: E402
    phase_taxonomy as tax,  # noqa: E402
)
from experiment.phase_filter import with_phase_filter  # noqa: E402


class PhaseAwareFakeTable:
    """Mini-DynamoDB that honours BOTH the `sk BETWEEN` key condition and the phase
    FilterExpression, so a phase-filtered read of a pilot-tagged partition really
    does come back short — the mechanism of the bug, not a stand-in for it."""

    def __init__(self, rows):
        self.rows = rows
        self.query_calls = []

    def query(self, **kwargs):
        self.query_calls.append(kwargs)
        vals = kwargs.get("ExpressionAttributeValues") or {}
        items = list(self.rows)
        lo, hi = vals.get(":s"), vals.get(":e")
        if lo is not None and hi is not None:
            items = [it for it in items if lo <= it["sk"] <= hi]
        if kwargs.get("FilterExpression") and ":phase_experiment" in vals:
            current = vals[":phase_experiment"]
            items = [it for it in items if it.get("phase") in (None, current)]
        return {"Items": items}


def _rows_for_a_young_cycle(field="hrv", days=30, genesis_days_ago=0, value=42.0):
    """One row per day for the last `days` days. Rows dated before genesis carry
    `phase=pilot` (what the reset tagger writes); rows on/after genesis are
    untagged, exactly as a fresh ingestion write lands them."""
    today = datetime.now(timezone.utc).date()
    genesis = today - timedelta(days=genesis_days_ago)
    rows = []
    for back in range(days):
        d = today - timedelta(days=back)
        row = {"sk": "DATE#" + d.isoformat(), field: value + back}
        if d < genesis:
            row["phase"] = "pilot"
        rows.append(row)
    return rows


# ── 1. Non-vacuous anchor: the fixture really models the blindfold ──────────────


def test_fixture_reproduces_the_phase_blindfold():
    """If this stops holding, every guard below is vacuous: a phase-filtered read of
    a genesis-day partition must see ONE row, and a cross-phase read all 30."""
    table = PhaseAwareFakeTable(_rows_for_a_young_cycle())
    today = datetime.now(timezone.utc).date()
    base = {
        "ExpressionAttributeValues": {
            ":s": "DATE#" + (today - timedelta(days=30)).isoformat(),
            ":e": "DATE#" + today.isoformat(),
        }
    }
    blinded = table.query(**with_phase_filter(dict(base)))
    assert len(blinded["Items"]) == 1, "the phase filter must hide pilot-tagged raw rows"
    assert len(blinded["Items"]) < updater._LIVENESS_MIN_POINTS, "…and land under the gate's bar"
    passed = table.query(**with_phase_filter(dict(base), include_pilot=True))
    assert len(passed["Items"]) == 30


# ── 2. The instance: genesis-day liveness ───────────────────────────────────────


def test_liveness_sees_pre_genesis_raw_rows_on_genesis_day(monkeypatch):
    """The issue's negative test. Genesis is TODAY; the raw partition holds a month
    of history, all of it phase-tagged. Liveness must still call the metric alive —
    the sensor is plainly producing data, and that is the only question the gate asks."""
    table = PhaseAwareFakeTable(_rows_for_a_young_cycle(genesis_days_ago=0))
    monkeypatch.setattr(updater, "table", table)
    assert updater._metric_has_recent_data("hrv", {}) is True
    assert all(kw.get("FilterExpression") is None for kw in table.query_calls), "liveness must not phase-filter"


def test_liveness_survives_every_day_of_the_opening_week(monkeypatch):
    """Not just Day 1 — the collapse ran the whole opening stretch, because the
    filter-visible point count is exactly the cycle's age in days."""
    for age in range(0, 7):
        table = PhaseAwareFakeTable(_rows_for_a_young_cycle(genesis_days_ago=age))
        monkeypatch.setattr(updater, "table", table)
        assert updater._metric_has_recent_data("hrv", {}) is True, f"blind on day {age + 1} of the cycle"


def test_aggregate_form_also_sees_pre_genesis_rows(monkeypatch):
    """`hrv_7day_avg` resolves to the same base metric and the same raw partition."""
    monkeypatch.setattr(updater, "table", PhaseAwareFakeTable(_rows_for_a_young_cycle()))
    cache: dict = {}
    assert updater._metric_has_recent_data("hrv_7day_avg", cache) is True
    assert cache == {"hrv": True}


def test_a_genuinely_dead_source_is_still_rejected(monkeypatch):
    """The #813 gate must keep doing its job. The 30-day WINDOW is what bounds
    recency — not the phase tag — so a source whose newest row is months old stays
    ungradable even though the read is now cross-phase."""
    stale = _rows_for_a_young_cycle(field="body_fat_pct", days=30)
    for row in stale:  # shift the whole history a quarter into the past
        d = datetime.fromisoformat(row["sk"][len("DATE#") :]) - timedelta(days=120)
        row["sk"] = "DATE#" + d.date().isoformat()
        row["phase"] = "pilot"
    monkeypatch.setattr(updater, "table", PhaseAwareFakeTable(stale))
    assert updater._metric_has_recent_data("body_fat_pct", {}) is False


def test_sparse_but_current_source_is_still_rejected(monkeypatch):
    """Under the 5-point bar in-window is still ungradable — un-blinding raises the
    ~1.4% share back to the ~9% baseline, it does not switch the gate off."""
    rows = _rows_for_a_young_cycle(field="blood_glucose_avg", days=3)
    monkeypatch.setattr(updater, "table", PhaseAwareFakeTable(rows))
    assert updater._metric_has_recent_data("blood_glucose_avg", {}) is False


def test_read_error_still_fails_open(monkeypatch):
    """Unchanged #813 contract: an AWS hiccup must never downgrade a whole run."""

    class _Boom:
        def query(self, **kwargs):
            raise RuntimeError("throttled")

    monkeypatch.setattr(updater, "table", _Boom())
    assert updater._metric_has_recent_data("hrv", {}) is True


# ── 3. The SET OF SOURCES this consumer reads (derived from METRIC_SOURCES) ─────


NEVER_HIDDEN_CLASSES = frozenset({tax.RAW_TIMESERIES, tax.CROSS_PHASE})


def test_every_gradable_metric_source_is_a_never_hidden_class():
    """The reasoning behind the fix, enforced over the derived set rather than the
    one metric that was measured. Reading liveness cross-phase is correct precisely
    because every source the gate can reach is kept across resets by taxonomy
    contract. Map a future metric onto an EXPERIMENT_SCOPED source and this fails,
    which is the moment to revisit the read — not silently inherit it."""
    for metric, source in sorted(mm.METRIC_SOURCES.items()):
        cls = tax.SOURCE_CLASS.get(source)
        assert cls is not None, f"{metric} → source '{source}' is unclassified in phase_taxonomy"
        assert cls in NEVER_HIDDEN_CLASSES, f"{metric} → '{source}' is {cls}; a cross-phase liveness read is unjustified"


def test_current_phase_rows_are_not_excluded_by_the_fix():
    """Sanity on the filter semantics the fix relies on: untagged AND current-phase
    rows both pass either way, so nothing that used to count stops counting."""
    rows = [
        {"sk": "DATE#2026-08-03", "hrv": 50},
        {"sk": "DATE#2026-08-02", "hrv": 51, "phase": EXPERIMENT_PHASE_CURRENT},
    ]
    table = PhaseAwareFakeTable(rows)
    assert len(table.query(**with_phase_filter({}))["Items"]) == 2
    assert len(table.query(**with_phase_filter({}, include_pilot=True))["Items"]) == 2


# ── 4. The SET OF CALL SITES (derived by AST scan, per #1203-class discipline) ──
#
# Guard the SET, not the instance. The inventory is DERIVED: every function under
# lambdas/ that builds its own `#SOURCE#` partition key, applies `with_phase_filter`,
# and whose key resolves to a RAW_TIMESERIES source — or to no fixed source at all
# (an interpolated `f"…#SOURCE#{src}"`, which can be pointed at anything). Sources
# that phase_taxonomy classes EXPERIMENT_SCOPED or CROSS_PHASE are pruned by the
# taxonomy, not by hand: on those partitions the filter is respectively load-bearing
# or a no-op, and neither is this defect class.
#
# Each derived site must then be one of:
#
#   * cross-phase              — it passes include_pilot=True (nothing to classify);
#   * a sanctioned current-cycle view — hiding pre-genesis rows is CORRECT for it,
#     with the reason recorded below;
#   * recorded debt            — same defect class as #1203/#2023, deliberately not
#     fixed in this PR, with the reason recorded below.
#
# Anything else fails, so a NEW raw-source consumer cannot be added phase-blind in
# silence. Sanctioning is a claim about intent, never a claim of "looks fine".
#
# Derivation boundary, stated honestly: this covers modules that construct the
# partition key themselves. The site-api family reads raw sources through three
# central helpers in `site_api_common` (`_query_source`, `_latest_item`,
# `_latest_item_asof`) which take `include_pilot` as an explicit parameter — that
# family is classified per call site instead, and
# `test_site_api_raw_helpers_expose_include_pilot` below keeps that hatch honest.

_SANCTIONED_CURRENT_CYCLE_VIEWS: dict[str, str] = {
    "lambdas/ai/platform_memory.py::_query_conversation_records": (
        "SOURCE#platform_memory is split BY CATEGORY, not by phase: the durable categories are "
        "CROSS_PHASE and never tagged (filter is a no-op), the rest are EXPERIMENT_SCOPED and "
        "correctly hidden. Not a raw timeseries despite the interpolated key."
    ),
    "lambdas/compute/character_sheet_lambda.py::fetch_journal_entries": (
        "Single-date notion fetch (yesterday's entry). A one-day window has no genesis interaction."
    ),
    "lambdas/compute/character_sheet_lambda.py::assemble_data": (
        "14-day COUNT sweep over notion feeding the character sheet, which is genesis-anchored by "
        "design — hiding pre-genesis days is equivalent to the date clamp the taxonomy prescribes."
    ),
    "lambdas/emails/monday_compass_lambda.py::query_source": (
        "<=7-day windows for the week-ahead compass — a current-week view; pre-genesis days are " "out of scope for it by intent."
    ),
    "lambdas/emails/monday_compass_lambda.py::query_source_latest": (
        "Newest-first Limit:1 — the liveness SHAPE — but its only caller reads computed_metrics "
        "(EXPERIMENT_SCOPED), where the filter is correct. Repointing it at a raw source would "
        "make it an exact clone of the #2023 defect, so re-classify it if that ever happens."
    ),
    "lambdas/emails/nutrition_review_lambda.py::query_all": (
        "Unbounded partition scan, but its callers pass genome/labs/dexa — all CROSS_PHASE, so "
        "those rows are never tagged and the filter is a literal no-op."
    ),
    "lambdas/emails/partner_email_lambda.py::query_journal_range": (
        "Notion journal entries for the reported week only — a this-week digest by definition."
    ),
    "lambdas/emails/weekly_digest_lambda.py::query_journal_range": (
        "Same shape: this week plus the prior week. Only the opening fortnight of a cycle straddles "
        "genesis, and a weekly digest is meant to be a current-cycle view."
    ),
    "lambdas/web/site_api_lambda.py::lambda_handler": (
        "The raw-source literal here is an UNFILTERED DynamoDB connectivity health-check get_item; "
        "the function's phase-filtered queries read coach_actions and COACH# (EXPERIMENT_SCOPED). "
        "Function-granularity co-location, not a phase-filtered raw read."
    ),
    "lambdas/web/site_api_meals.py::meal_responses": (
        "SOURCE#meal_responses is a derived CGM x MacroFactor projection, not a raw timeseries — "
        "and it is absent from SOURCE_CLASS with no writer anywhere in the repo (dead partition)."
    ),
    "lambdas/web/site_stats_refresh_lambda.py::_get_latest": (
        "Two-day bounded Limit:1 read: it means 'today's number', not 'is this pipe alive'. On a "
        "miss it falls back to the previously published S3 value rather than claiming no data."
    ),
    "lambdas/web/site_stats_refresh_lambda.py::lambda_handler": (
        "The strava window starts at EXPERIMENT_START_DATE — explicitly genesis-anchored, so the "
        "phase filter is redundant with the date clamp the taxonomy asks for."
    ),
}

# Same defect class as #1203/#2023, found by this scan, deliberately NOT fixed in the
# PR that introduced the guard: each touches a different Lambda with a different deploy
# surface, and #2023 was scoped to the gradability gate ahead of a same-day reset.
# Recorded rather than sanctioned so the debt is visible and reviewable, not blessed.
#
# The ledger is a ratchet, so entries LEAVE it as they are fixed — they do not get
# re-marked in place. Cleared so far:
#   * daily_brief_lambda's per-source staleness scan (#2080) — extracted to
#     `scan_stale_sources` and read cross-phase;
#   * anomaly_detector_lambda.fetch_range (#2081) — the rolling-baseline read.
# Both are held cross-phase by `test_the_scan_sees_the_fixed_consumers_as_cross_phase`
# below, plus tests/test_genesis_blind_reads_2080_2081.py for their behaviour.
#
# NB the same class was ALSO fixed in daily_brief_lambda's two shared readers,
# `_latest_item` and `fetch_range` (#2089 — the trend windows and the "latest
# measurements" line). They never appeared in either ledger and are absent from the
# derived set below, because they build the partition key from the module-level
# USER_PREFIX constant and this scan keys on a literal "#SOURCE#" INSIDE the function
# body. That structural blind spot is #2090's job to close — deliberately not papered
# over here with a hand-added entry, which would hide the gap rather than fix it.
# Those two sites are pinned by tests/test_genesis_blind_brief_windows_2089.py.
_KNOWN_CROSS_CYCLE_DEBT: dict[str, str] = {
    "lambdas/common/digest_utils.py::query_range": (
        "The shared paginated raw-source range reader exposes NO include_pilot parameter, so a "
        "caller with cross-cycle intent (60d Banister load, 30d weight trend) physically cannot "
        "opt out. Root enabler rather than a defect in itself."
    ),
    "lambdas/common/digest_utils.py::query_range_list": (
        "Same chokepoint, the per-workout (hevy) variant — no include_pilot parameter to pass."
    ),
    "lambdas/emails/monthly_digest_lambda.py::fetch_range": (
        "Drives the prior-month comparison arm and a 60-day Strava window for CTL/ATL/TSB. In a reset "
        "month the prior-month arm is entirely pre-genesis, so deltas blank and the load model is "
        "computed over a stub window."
    ),
    "lambdas/web/site_api_vitals.py::handle_timeline": (
        "The unbounded SOURCE#life_events query is RAW_TIMESERIES: those annotations exist to caption "
        "the pre-genesis part of the transformation arc, so after a reset the timeline keeps its "
        "weight line (date-clamped) but loses every narrative caption."
    ),
}

_SCAN_ROOT = REPO_ROOT / "lambdas"
_INTERPOLATION = "\x00"  # stands in for an f-string's {…} slots when flattening a literal


def _flatten_literal(node) -> str | None:
    """The string a node evaluates to, with interpolated slots replaced by a sentinel."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        out = ""
        for value in node.values:
            out += value.value if isinstance(value, ast.Constant) and isinstance(value.value, str) else _INTERPOLATION
        return out
    return None


def _source_names_in(func) -> tuple[set[str], bool]:
    """(literal source names, any_interpolated) for the `#SOURCE#` keys a function names."""
    names: set[str] = set()
    interpolated = False
    for node in ast.walk(func):
        text = _flatten_literal(node)
        if not text or "#SOURCE#" not in text:
            continue
        for match in re.finditer(r"#SOURCE#([A-Za-z0-9_]*)", text):
            if match.group(1):
                names.add(match.group(1))
            else:
                interpolated = True  # f"…#SOURCE#{src}" — could be any source
    return names, interpolated


def _phase_filtered_raw_reads(source_text: str, label: str) -> dict[str, bool]:
    """{"<label>::<function>": reads_cross_phase} for one module's source text.

    Kept source-text-driven (rather than path-driven) so the anchor tests can run
    the real derivation against a synthetic module and PROVE it fires on the defect
    shape — a scan that has never been shown to catch anything guards nothing.
    """
    found: dict[str, bool] = {}
    if "with_phase_filter" not in source_text or "#SOURCE#" not in source_text:
        return found
    try:
        tree = ast.parse(source_text)
    except SyntaxError:  # pragma: no cover - the repo is syntax-checked in CI
        return found
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        seg = ast.get_source_segment(source_text, node) or ""
        if "with_phase_filter" not in seg or "#SOURCE#" not in seg:
            continue
        names, interpolated = _source_names_in(node)
        # In scope when the read can land on a never-hidden measured series: an
        # interpolated source (anything), an unclassified one, or an explicit
        # RAW_TIMESERIES name. EXPERIMENT_SCOPED / CROSS_PHASE names prune out.
        in_scope = interpolated or any(
            tax.SOURCE_CLASS.get(n, "unclassified") not in (tax.EXPERIMENT_SCOPED, tax.CROSS_PHASE) for n in names
        )
        if not in_scope:
            continue
        found[f"{label}::{node.name}"] = "include_pilot=True" in seg.replace(" ", "")
    return found


def _derive_raw_source_phase_filtered_functions() -> dict[str, bool]:
    found: dict[str, bool] = {}
    for path in sorted(_SCAN_ROOT.rglob("*.py")):
        found.update(_phase_filtered_raw_reads(path.read_text(), path.relative_to(REPO_ROOT).as_posix()))
    return found


_PRE_FIX_SHAPE = '''
def _metric_has_recent_data(metric_key):
    """The #2023 defect, verbatim in shape: a rolling raw-source window, phase-filtered."""
    kwargs = {
        "KeyConditionExpression": "pk = :pk AND sk BETWEEN :s AND :e",
        "ExpressionAttributeValues": {":pk": f"USER#{USER_ID}#SOURCE#{source}"},
    }
    return len(table.query(**with_phase_filter(kwargs))["Items"]) >= 5
'''

_PRE_FIX_1203_SHAPE = '''
def _latest_date_str(source):
    """The #1203 defect in shape: newest-first Limit:1 recency read, phase-filtered."""
    kwargs = with_phase_filter({"KeyConditionExpression": f"USER#{USER_ID}#SOURCE#{source}", "Limit": 1})
    return table.query(**kwargs)["Items"]
'''


def test_the_derivation_fires_on_the_defect_shape():
    """Prove it fires. Both known members of this class — the #2023 rolling-window
    liveness read and the #1203 newest-first recency read — are flagged by the real
    derivation when written phase-blind."""
    assert _phase_filtered_raw_reads(_PRE_FIX_SHAPE, "synthetic.py") == {"synthetic.py::_metric_has_recent_data": False}
    assert _phase_filtered_raw_reads(_PRE_FIX_1203_SHAPE, "synthetic.py") == {"synthetic.py::_latest_date_str": False}


def test_the_derivation_clears_a_cross_phase_read():
    """…and clears the same shape once it reads cross-phase, so the guard is a
    classification, not a blanket ban on with_phase_filter."""
    fixed = _PRE_FIX_SHAPE.replace("with_phase_filter(kwargs)", "with_phase_filter(kwargs, include_pilot=True)")
    assert _phase_filtered_raw_reads(fixed, "synthetic.py") == {"synthetic.py::_metric_has_recent_data": True}


def test_the_scan_sees_the_fixed_consumers_as_cross_phase():
    """The real repo end of the anchor: every site this class has fixed so far is in
    the derived set, on the cross-phase side. A silent revert (or a refactor that
    drops the site out of the derivation entirely) fails here rather than waiting
    for the next reset to expose it."""
    derived = _derive_raw_source_phase_filtered_functions()
    fixed = {
        "lambdas/coach/coach_state_updater.py::_metric_has_recent_data": "the gradability liveness read (#2023)",
        "lambdas/emails/daily_brief_lambda.py::scan_stale_sources": "the brief's per-source staleness scan (#2080)",
        "lambdas/emails/anomaly_detector_lambda.py::fetch_range": "the anomaly detector's rolling baseline (#2081)",
    }
    for key, what in fixed.items():
        assert key in derived, f"the AST scan no longer sees {what} — the derivation has drifted"
        assert derived[key] is True, f"{what} must be cross-phase"


def test_every_raw_source_phase_filtered_read_is_classified():
    """The ratchet."""
    derived = _derive_raw_source_phase_filtered_functions()
    known = set(_SANCTIONED_CURRENT_CYCLE_VIEWS) | set(_KNOWN_CROSS_CYCLE_DEBT)
    unclassified = sorted(k for k, cross_phase in derived.items() if not cross_phase and k not in known)
    assert not unclassified, (
        "New/changed raw-source reads apply the phase filter without a classification.\n"
        "After a reset these see ONLY post-genesis rows (#1203, #2023). For each site below,\n"
        "either read cross-phase (with_phase_filter(..., include_pilot=True)) if its intent is\n"
        "liveness / recency / history, or record it in _SANCTIONED_CURRENT_CYCLE_VIEWS (hiding\n"
        "pre-genesis rows is correct for it) or _KNOWN_CROSS_CYCLE_DEBT (same defect, not fixed\n"
        "here) with the reason:\n  " + "\n  ".join(unclassified)
    )


def test_ledgers_have_no_dead_entries():
    """A listed site that no longer exists (renamed, deleted, or since fixed) must
    leave the ledger, or the ledger stops describing the code."""
    derived = _derive_raw_source_phase_filtered_functions()
    listed = {**_SANCTIONED_CURRENT_CYCLE_VIEWS, **_KNOWN_CROSS_CYCLE_DEBT}
    stale = sorted(k for k in listed if k not in derived or derived[k])
    assert not stale, "ledger entries no longer match a phase-filtered raw-source read: " + ", ".join(stale)


def test_no_site_is_in_both_ledgers():
    both = set(_SANCTIONED_CURRENT_CYCLE_VIEWS) & set(_KNOWN_CROSS_CYCLE_DEBT)
    assert not both, f"a site is either correct-by-design or debt, not both: {sorted(both)}"


def test_every_ledger_entry_carries_a_reason():
    for key, reason in {**_SANCTIONED_CURRENT_CYCLE_VIEWS, **_KNOWN_CROSS_CYCLE_DEBT}.items():
        assert reason and len(reason) > 20, f"{key} needs a real reason, not '{reason}'"


def test_site_api_raw_helpers_expose_include_pilot():
    """The derivation's stated boundary, enforced. The site-api family is exempt from
    the scan because its raw reads funnel through helpers that take include_pilot
    explicitly, so phase is a per-call decision there. If a helper loses that
    parameter, the exemption silently becomes a blind spot."""
    src = (REPO_ROOT / "lambdas" / "web" / "site_api_common.py").read_text()
    tree = ast.parse(src)
    helpers = {"_query_source", "_latest_item", "_latest_item_asof"}
    seen = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in helpers:
            args = [a.arg for a in node.args.args] + [a.arg for a in node.args.kwonlyargs]
            assert "include_pilot" in args, f"site_api_common.{node.name} no longer takes include_pilot"
            seen.add(node.name)
    assert seen == helpers, f"site-api raw-read helpers moved or were renamed: missing {sorted(helpers - seen)}"
