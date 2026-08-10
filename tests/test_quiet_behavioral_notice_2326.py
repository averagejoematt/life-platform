"""tests/test_quiet_behavioral_notice_2326.py — the quiet notice for
load-bearing behavioral sources.

#2326: MacroFactor ingested nothing for 45 days with a perfectly healthy pipe —
a `behavioral: True` source never pages by design (#392), but "never page" had
in practice also become "never mention": no surface an operator reads said so.
The fix is a NON-PAGING quiet notice in the daily brief for every source whose
registry facets are `behavioral: True` AND `posture: load-bearing`, with the set
and thresholds DERIVED from the registry (quiet_after_days = several multiples
of the canonical stale_hours — a distinct signal, never a re-threshold of the
stale_hours facets, which encode each writer's cadence).

Guards here, in the order the issue's acceptance asks for them:

  1. the watch set derives from the registry facets — never hand-typed, and the
     motivating instance (macrofactor) is in it;
  2. the quiet threshold is strictly beyond the staleness threshold (distinct
     signal) and the watch set cannot feed the paging metric (non-paging);
  3. the MUTATION PROOF — for every watched source, pushing that source's
     newest-record date back past its quiet threshold makes the notice fire for
     exactly that source, and a fresh fixture stays silent;
  4. the read is cross-phase (#2080 class — a reset must not blind it) and every
     watched partition is a never-hidden phase class;
  5. the rendered notice states the absence honestly (ADR-104): a quiet source
     is re-homed OUT of the amber "stale" banner (which reads as breakage) into
     the calm quiet block.

Every date is PINNED; nothing does now-math against the wall clock.
"""

from __future__ import annotations

import os
import sys
from datetime import date, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("EMAIL_RECIPIENT", "test@example.com")
os.environ.setdefault("EMAIL_SENDER", "noreply@example.com")

sys.path.insert(0, str(REPO_ROOT / "lambdas"))
sys.path.insert(0, str(REPO_ROOT / "lambdas" / "emails"))

import freshness_checker_lambda as checker  # noqa: E402
from emails import brief_data_status as bds  # noqa: E402
from experiment import phase_taxonomy as tax  # noqa: E402
from ingestion import source_registry as registry  # noqa: E402

_TODAY = date(2026, 8, 9)

# The facet-level derivation the acceptance names, restated independently of the
# accessor so a hand-typed list sneaking into either side fails loudly.
_EXPECTED_WATCH = {
    k
    for k, v in registry.SOURCE_REGISTRY.items()
    if v["behavioral"] and v.get("posture") == "load-bearing" and v.get("partition") is not False and not v.get("paused")
}


class FakeTable:
    """Newest-first Limit-N pk/sk-prefix queries over fixture rows — the only
    shapes scan_quiet_behavioral_sources issues. Records every call's kwargs so
    the cross-phase contract can be asserted against the wire."""

    def __init__(self, rows):
        self.rows = rows
        self.query_calls = []

    def query(self, **kwargs):
        self.query_calls.append(kwargs)
        pk_val, sk_prefix = _flatten_key_condition(kwargs["KeyConditionExpression"].get_expression())
        items = [dict(r) for r in self.rows if r.get("pk") == pk_val and str(r.get("sk", "")).startswith(sk_prefix or "")]
        items.sort(key=lambda it: it["sk"], reverse=not kwargs.get("ScanIndexForward", True))
        limit = kwargs.get("Limit")
        if limit is not None:
            items = items[:limit]
        # Limit is applied BEFORE any filter (DynamoDB's real order — the #2080
        # mechanism): if the scan ever re-grows a phase filter, the pilot-tagged
        # fixtures below make it return empty and the cross-phase test fails.
        vals = kwargs.get("ExpressionAttributeValues") or {}
        if kwargs.get("FilterExpression") is not None and ":phase_experiment" in vals:
            current = vals[":phase_experiment"]
            items = [it for it in items if it.get("phase") in (None, current)]
        return {"Items": items}


def _flatten_key_condition(expr):
    """(pk_value, sk_begins_with_prefix) from a boto3 Key condition object."""
    pk_val, sk_prefix = None, None
    stack = [expr]
    while stack:
        e = stack.pop()
        operator = e.get("operator")
        values = e.get("values", ())
        if operator == "AND":
            stack.extend(sub.get_expression() for sub in values)
            continue
        name = getattr(values[0], "name", None)
        if name == "pk" and operator == "=":
            pk_val = values[1]
        elif name == "sk" and operator == "begins_with":
            sk_prefix = values[1]
    return pk_val, sk_prefix


def _rows(last_seen_by_source, pilot=False):
    """One newest row per source at its stated last-seen date (+ two older)."""
    rows = []
    for src, last in last_seen_by_source.items():
        for i in range(3):
            row = {"pk": f"USER#matthew#SOURCE#{src}", "sk": "DATE#" + (last - timedelta(days=i)).isoformat(), "value": 1}
            if pilot:
                row["phase"] = "pilot"
            rows.append(row)
    return rows


def _all_fresh():
    return {src: _TODAY - timedelta(days=1) for src in bds.QUIET_WATCH_SOURCES}


# ══════════════════════════════════════════════════════════════════════════════
# 1. The watch set derives from the registry facets
# ══════════════════════════════════════════════════════════════════════════════


def test_watch_set_is_derived_from_the_registry_facets():
    assert set(registry.quiet_watch_sources()) == _EXPECTED_WATCH
    assert set(bds.QUIET_WATCH_SOURCES) == _EXPECTED_WATCH


def test_the_motivating_instance_is_watched():
    """Non-vacuity: macrofactor — the source that went 45 days dark — is in the
    set, and the set is not somehow empty."""
    assert "macrofactor" in registry.quiet_watch_sources()
    assert len(registry.quiet_watch_sources()) >= 2


def test_every_entry_carries_a_label_and_threshold():
    for src, cfg in registry.quiet_watch_sources().items():
        assert cfg["label"] and cfg["checker_label"], src
        assert isinstance(cfg["quiet_after_days"], int), src


# ══════════════════════════════════════════════════════════════════════════════
# 2. Distinct signal, never paging
# ══════════════════════════════════════════════════════════════════════════════


def test_quiet_threshold_is_strictly_beyond_the_staleness_threshold():
    """The quiet notice is a distinct signal at a distinct (later) line — never a
    re-threshold of the canonical stale_hours facets."""
    for src, cfg in registry.quiet_watch_sources().items():
        sh = registry.SOURCE_REGISTRY[src]["stale_hours"] or registry.DEFAULT_STALE_HOURS
        assert cfg["quiet_after_days"] * 24 > sh, src
        assert cfg["quiet_after_days"] >= registry.QUIET_NOTICE_MIN_DAYS, src


def test_watched_sources_cannot_feed_the_paging_metric():
    """Every watched source the freshness checker also monitors is classified
    behavioral there, so count_infra_stale — the StaleSourceCount feeder behind
    the slo-source-freshness alarm — ignores it at ANY staleness."""
    for src in registry.quiet_watch_sources():
        if src not in checker.SOURCES:
            continue  # not on a checker surface at all (e.g. supplements, #498)
        assert src in checker.BEHAVIORAL_SOURCES, src
        assert checker.count_infra_stale([(checker.SOURCES[src], "45 days dark")]) == 0, src


# ══════════════════════════════════════════════════════════════════════════════
# 3. The mutation proof — push one source's newest record back, the notice fires
# ══════════════════════════════════════════════════════════════════════════════


def test_notice_fires_when_one_sources_newest_record_is_pushed_back():
    """For EVERY watched source in turn: all sources fresh except this one, whose
    newest record is pushed back exactly to its quiet line → the scan reports
    exactly that source, with its true last date and age."""
    for src, cfg in bds.QUIET_WATCH_SOURCES.items():
        last_seen = _all_fresh()
        last_seen[src] = _TODAY - timedelta(days=cfg["quiet_after_days"])
        quiet = bds.scan_quiet_behavioral_sources(FakeTable(_rows(last_seen)), _TODAY)
        assert [q["source"] for q in quiet] == [src]
        assert quiet[0]["age_days"] == cfg["quiet_after_days"]
        assert quiet[0]["last_date"] == last_seen[src].isoformat()


def test_no_notice_while_every_source_is_fresh():
    assert bds.scan_quiet_behavioral_sources(FakeTable(_rows(_all_fresh())), _TODAY) == []


def test_a_normal_lapse_inside_the_quiet_line_stays_silent():
    """One day short of the quiet line is a normal rest/lapse stretch — silent.
    (This is what keeps the notice from paging-by-nagging on a rest week.)"""
    last_seen = _all_fresh()
    for src, cfg in bds.QUIET_WATCH_SOURCES.items():
        last_seen[src] = _TODAY - timedelta(days=cfg["quiet_after_days"] - 1)
    assert bds.scan_quiet_behavioral_sources(FakeTable(_rows(last_seen)), _TODAY) == []


def test_a_partition_with_no_record_at_all_is_reported_honestly():
    """No rows → age_days None ("no record on file"), never a fabricated number
    (ADR-104)."""
    last_seen = _all_fresh()
    gone = sorted(bds.QUIET_WATCH_SOURCES)[0]
    del last_seen[gone]
    quiet = bds.scan_quiet_behavioral_sources(FakeTable(_rows(last_seen)), _TODAY)
    assert [q["source"] for q in quiet] == [gone]
    assert quiet[0]["age_days"] is None and "last_date" not in quiet[0]


def test_a_read_failure_is_non_fatal():
    class Exploding:
        def query(self, **kwargs):
            raise RuntimeError("boom")

    assert bds.scan_quiet_behavioral_sources(Exploding(), _TODAY) == []


# ══════════════════════════════════════════════════════════════════════════════
# 4. Cross-phase (#2080 class) + never-hidden partitions
# ══════════════════════════════════════════════════════════════════════════════


def test_quiet_scan_survives_a_reset_that_pilot_tags_every_row():
    """Genesis-day worst case: every row pre-dates genesis and is pilot-tagged.
    A fresh source must still read fresh (no false notice), and a genuinely
    quiet one must still fire with its true age."""
    cfg = bds.QUIET_WATCH_SOURCES["macrofactor"]
    last_seen = _all_fresh()
    last_seen["macrofactor"] = _TODAY - timedelta(days=45)
    quiet = bds.scan_quiet_behavioral_sources(FakeTable(_rows(last_seen, pilot=True)), _TODAY)
    assert [q["source"] for q in quiet] == ["macrofactor"]
    assert quiet[0]["age_days"] == 45 and 45 >= cfg["quiet_after_days"]


def test_quiet_scan_does_not_phase_filter():
    """The contract stated directly against the wire kwargs (mirrors #2080)."""
    table = FakeTable(_rows(_all_fresh()))
    bds.scan_quiet_behavioral_sources(table, _TODAY)
    assert table.query_calls, "the scan issued no queries at all"
    assert all(kw.get("FilterExpression") is None for kw in table.query_calls)


def test_every_watched_partition_is_a_never_hidden_phase_class():
    never_hidden = {tax.RAW_TIMESERIES, tax.CROSS_PHASE}
    for src in registry.quiet_watch_sources():
        assert tax.classify(f"USER#matthew#SOURCE#{src}") in never_hidden, src


# ══════════════════════════════════════════════════════════════════════════════
# 5. The rendered notice — honest phrasing, re-homed out of the amber banner
# ══════════════════════════════════════════════════════════════════════════════

_STALE_WHOOP = {"source": "whoop", "age_days": 5, "last_date": "2026-08-04"}
_QUIET_MACRO = {"source": "macrofactor", "label": "MacroFactor", "age_days": 45, "last_date": "2026-06-24", "quiet_after_days": 14}


def test_quiet_source_is_rehomed_out_of_the_amber_stale_list():
    """macrofactor is in BOTH scans' output (45d >> its 96h stale threshold);
    the render must place it ONLY in the calm quiet block — a logging lapse is
    never dressed up as breakage (ADR-104)."""
    stale = [_STALE_WHOOP, {"source": "macrofactor", "age_days": 45, "last_date": "2026-06-24"}]
    html = bds.build_data_status_banner_html(stale, [_QUIET_MACRO])
    amber, quiet_block = html.split("Quiet inputs", 1)
    assert "Data Status" in amber and "whoop" in amber
    assert "macrofactor" not in amber and "MacroFactor" not in amber
    assert "MacroFactor" in quiet_block
    assert "nothing logged since 2026-06-24 (45 days)" in quiet_block
    assert "not an outage" in quiet_block and "#2326" in quiet_block


def test_quiet_notice_renders_without_any_stale_source():
    html = bds.build_data_status_banner_html([], [_QUIET_MACRO])
    assert "Quiet inputs" in html and "Data Status" not in html


def test_stale_banner_unchanged_when_nothing_is_quiet():
    html = bds.build_data_status_banner_html([_STALE_WHOOP], [])
    assert "Data Status — 1 source stale" in html
    assert "whoop — last update 2026-08-04 (5d ago)" in html
    assert "Quiet inputs" not in html


def test_nothing_to_say_renders_empty():
    assert bds.build_data_status_banner_html([], []) == ""


def test_no_record_on_file_phrasing():
    q = dict(_QUIET_MACRO, age_days=None)
    q.pop("last_date")
    html = bds.build_data_status_banner_html([], [q])
    assert "no record on file" in html
