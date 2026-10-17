"""tests/test_steps_truth_resolver_4630.py — one resolver for the day's steps (#4630 boxes 2/4/5).

Three things are pinned here:

1. The resolver (`lambdas/common/metric_truth.py`) applies the registry's `METRIC_TRUTH["steps"]`
   facet: Whoop's `step_count` when the Whoop day row has one, Apple Health's `steps` otherwise,
   paused Garmin last (with its 1000 floor). Fixtures are the WIRE — the field sets and value
   types of real stored DATE# rows (Whoop 2026-10-14 and Apple Health 2026-10-14, read-only
   `get-item` on 2026-10-16: Whoop `step_count` is an integer Decimal, Apple `steps` is a
   fractional Decimal because HAE sums per-reading counts).
2. The guard: no module under `lambdas/` or `mcp/` reads a steps field off a stored row
   directly. A line that matches a read pattern either lives in an exempt file (a writer, a
   per-source liveness check, the resolver/registry themselves) or carries a
   `# steps-truth: <reason>` marker naming why the value it reads is already resolved.
3. Box 5: `get_sot()` and the static SOT map no longer state a truth for steps.
"""

# premerge-gate: sweeps lambdas/ and mcp/ for a direct read of a steps field (the #4630 reader guard)

import os
import re
import sys
from decimal import Decimal

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))
sys.path.insert(0, ROOT)

for _k, _v in (
    ("TABLE_NAME", "life-platform-test"),
    ("USER_ID", "matthew"),
    ("S3_BUCKET", "test-bucket"),
    ("AWS_ACCESS_KEY_ID", "FAKE"),
    ("AWS_SECRET_ACCESS_KEY", "FAKE"),
    ("AWS_DEFAULT_REGION", "us-west-2"),
):
    os.environ.setdefault(_k, _v)

from common import metric_truth as mt  # noqa: E402
from ingestion import source_registry as reg  # noqa: E402

# ── the wire: real stored row shapes (values from DATE#2026-10-14, field sets abridged) ──
WHOOP_ROW = {
    "pk": "USER#matthew#SOURCE#whoop",
    "sk": "DATE#2026-10-14",
    "date": "2026-10-14",
    "source": "whoop",
    "recovery_score": Decimal("61"),
    "strain": Decimal("12.4"),
    "kilojoule": Decimal("10612.3"),
    "step_count": Decimal("17739"),
    "schema_version": Decimal("1"),
}
APPLE_ROW = {
    "pk": "USER#matthew#SOURCE#apple_health",
    "sk": "DATE#2026-10-14",
    "date": "2026-10-14",
    "source": "apple_health",
    "steps": Decimal("11525.99"),
    "active_calories": Decimal("812.4"),
    "distance_walk_run_miles": Decimal("5.21"),
    "flights_climbed": Decimal("4"),
    "webhook_ingested_at": "2026-10-15T06:12:09Z",
}
# A Whoop row from before 2026-09-21 (no step_count on the cycle payload) — the fallback case.
WHOOP_ROW_NO_STEPS = {k: v for k, v in WHOOP_ROW.items() if k != "step_count"} | {"sk": "DATE#2026-09-10", "date": "2026-09-10"}
APPLE_ROW_0910 = APPLE_ROW | {"sk": "DATE#2026-09-10", "date": "2026-09-10", "steps": Decimal("8231.0")}
GARMIN_PHANTOM = {"pk": "USER#matthew#SOURCE#garmin", "sk": "DATE#2026-05-02", "date": "2026-05-02", "steps": Decimal("298")}
GARMIN_ROW = {"pk": "USER#matthew#SOURCE#garmin", "sk": "DATE#2026-05-01", "date": "2026-05-01", "steps": Decimal("9120")}


# ── 1. the resolver ──────────────────────────────────────────────────────────


def test_whoop_wins_when_both_devices_have_a_count():
    r = mt.resolve_steps({"whoop": WHOOP_ROW, "apple_health": APPLE_ROW})
    assert (r.source, r.field, r.count) == ("whoop", "step_count", 17739)
    assert r.candidates["apple_health"] == pytest.approx(11525.99)
    assert "truth source" in r.reason


def test_apple_health_when_whoop_has_no_count():
    r = mt.resolve_steps({"whoop": WHOOP_ROW_NO_STEPS, "apple_health": APPLE_ROW_0910})
    assert (r.source, r.field, r.count) == ("apple_health", "steps", 8231)
    assert "fallback #2" in r.reason and "no usable step_count" in r.reason


def test_unfetched_source_is_named_in_the_reason():
    r = mt.resolve_steps({"apple_health": APPLE_ROW})
    assert r.source == "apple_health" and "not fetched" in r.reason


def test_garmin_last_and_floored():
    assert mt.resolve_steps({"garmin": GARMIN_ROW}).count == 9120
    assert mt.resolve_steps({"garmin": GARMIN_PHANTOM}).value is None
    assert mt.resolve_steps({"apple_health": APPLE_ROW, "garmin": GARMIN_ROW}).source == "apple_health"


def test_a_zero_report_counts_only_when_no_source_has_a_positive_count():
    r = mt.resolve_steps({"whoop": {"step_count": Decimal("0")}, "apple_health": APPLE_ROW})
    assert (r.source, r.count) == ("apple_health", 11526) and "whoop (reported 0)" in r.reason
    r = mt.resolve_steps({"whoop": WHOOP_ROW_NO_STEPS, "apple_health": {"steps": Decimal("0")}})
    assert (r.source, r.value) == ("apple_health", 0.0) and "reported 0" in r.reason
    assert mt.resolve_steps({"garmin": {"steps": 0}}).value == 0.0  # #1658: a genuine 0-step day is a reading


def test_absent_bool_and_junk_are_not_counts():
    for bad in (None, True, "n/a", Decimal("-5")):
        r = mt.resolve_steps({"whoop": {"step_count": bad}, "apple_health": {"steps": bad}})
        assert r.value is None and r.source is None, bad
    assert mt.resolve_steps({}).reason == "no source has a usable count"


def test_by_date_resolves_each_day_and_takes_the_per_source_max():
    dup = APPLE_ROW_0910 | {"steps": Decimal("120")}
    out = mt.steps_by_date({"whoop": [WHOOP_ROW, WHOOP_ROW_NO_STEPS], "apple_health": [APPLE_ROW, dup, APPLE_ROW_0910]})
    assert out == {"2026-09-10": 8231, "2026-10-14": 17739}
    assert mt.steps_series({"whoop": [WHOOP_ROW], "apple_health": [APPLE_ROW_0910]}) == [8231.0, 17739.0]


def test_resolver_reads_the_registry_facet_not_its_own_list():
    facet = reg.metric_truth("steps")
    assert mt.steps_sources() == facet["fallback_order"] == ("whoop", "apple_health", "garmin")
    assert facet["truth_source"] == "whoop" and facet["overlap_rule"] == "first_positive_else_first_zero"
    src = open(os.path.join(ROOT, "lambdas", "common", "metric_truth.py")).read()
    for literal in ('"whoop"', '"apple_health"', '"garmin"', '"step_count"'):
        assert literal not in src, f"the resolver names {literal} — the precedence belongs in METRIC_TRUTH"


def test_facet_refuses_a_malformed_truth(monkeypatch):
    monkeypatch.setitem(reg.METRIC_TRUTH, "steps", dict(reg.METRIC_TRUTH["steps"], fallback_order=("apple_health", "whoop")))
    with pytest.raises(ValueError, match="truth_source"):
        reg._validate_metric_truth()


# ── 2. the reader guard ──────────────────────────────────────────────────────

_F = r"['\"](?:steps|step_count)['\"]"
READ_PATTERNS = (
    re.compile(r"\.get\(\s*" + _F),  # row.get("steps")
    re.compile(r"\[\s*" + _F + r"\s*\](?!\s*(?:=(?!=)|\|=|\+=))"),  # row["steps"] (not an assignment)
    re.compile(r"[A-Za-z_]\w*\(\s*[^()]*,\s*" + _F + r"\s*\)"),  # safe_float(row, "steps") — a CALL, not a tuple
    re.compile(_F + r"\s+(?:not\s+)?in\s+[A-Za-z_]"),  # "steps" in row
    re.compile(r"['\"](?:apple_health|garmin|whoop)['\"]\s*,\s*" + _F),  # ("apple_health", "steps", …) metric tables
    re.compile(r"['\"](?:apple_health|garmin|whoop)['\"]\s*:\s*\[[^\]]*" + _F),  # {"garmin": ["steps"]} field lists
    re.compile(r"['\"]steps['\"]\s*:\s*['\"](?:apple_health|garmin|whoop)['\"]"),  # {"steps": "apple_health"} SOT maps
)
MARKER = re.compile(r"#\s*steps-truth:\s*\S")

# Files that legitimately touch a steps field per SOURCE — they never answer "the day's steps".
EXEMPT_FILES = {
    "lambdas/common/metric_truth.py": "the resolver itself",
    "lambdas/ingestion/source_registry.py": "the METRIC_TRUTH facet and the per-source capture facets",
    "lambdas/ingestion/whoop_lambda.py": "the writer: stores Whoop's own step_count (box 1)",
    "lambdas/ingestion/health_auto_export_lambda.py": "the writer: stores Apple's own steps",
    "lambdas/ingestion/ingestion_validator.py": "write-time per-source type/range validation",
    "lambdas/emails/freshness_checker_lambda.py": "per-source liveness (is the Apple steps stream flowing?)",
    "lambdas/operational/continuity_watch.py": "per-source liveness",
    "lambdas/training/walking_volume.py": "refuses steps as a walking proxy by construction (#3930)",
    "lambdas/training/redline_rate.py": "a rate schedule's 'steps' list, not step counts",
    "lambdas/experiment/plan_facts.py": "the plan's step TARGETS parsed from prose, not a stored count",
}


def _offenders():
    out = []
    for top in ("lambdas", "mcp"):
        for dirpath, _dirs, files in os.walk(os.path.join(ROOT, top)):
            if "__pycache__" in dirpath:
                continue
            for fn in files:
                if not fn.endswith(".py"):
                    continue
                path = os.path.join(dirpath, fn)
                rel = os.path.relpath(path, ROOT)
                if rel in EXEMPT_FILES:
                    continue
                with open(path, encoding="utf-8") as fh:
                    for n, line in enumerate(fh, 1):
                        code = line.split("#", 1)[0] if "steps-truth" not in line else line
                        if any(p.search(code) for p in READ_PATTERNS) and not MARKER.search(line):
                            out.append(f"{rel}:{n}: {line.strip()}")
    return out


def test_no_reader_reads_a_steps_field_directly():
    offenders = _offenders()
    assert not offenders, (
        "a steps field is read off a row outside the resolver — route it through common.metric_truth "
        "(resolve_steps / steps_by_date) or mark an already-resolved value with '# steps-truth: <reason>':\n  " + "\n  ".join(offenders)
    )


def test_guard_can_fail():
    """Mutation proof: a planted direct read is caught; the marker clears it."""
    planted = 'v = _safe_float(apple, "steps")'
    assert any(p.search(planted) for p in READ_PATTERNS)
    assert MARKER.search(planted + "  # steps-truth: resolved upstream")
    assert not any(p.search('details["steps"] = round(steps)') for p in READ_PATTERNS)


def test_exempt_files_exist():
    for rel in EXEMPT_FILES:
        assert os.path.exists(os.path.join(ROOT, rel)), f"stale exemption: {rel}"


# ── 3. box 5: no second place states the truth ───────────────────────────────


def test_get_sot_refuses_steps():
    from mcp import core

    with pytest.raises(ValueError, match="metric_truth"):
        core.get_sot("steps")


def test_static_sot_map_has_no_steps():
    from mcp import config

    assert "steps" not in config.SOURCE_OF_TRUTH


# ── the writer ⇄ facet seam (#2847): the field the facet reads is the field the writer writes ──


def _writer_writes(path: str, field_literal: str) -> bool:
    with open(os.path.join(ROOT, path), encoding="utf-8") as fh:
        return field_literal in fh.read()


def test_the_facet_fields_are_the_fields_the_writers_write():
    """Two-sided: the whoop writer stores `step_count` (box 1, PR #4926) and the HAE writer maps
    Step Count onto `steps`; the facet must name exactly those. Mutation control: rename the facet's
    whoop field and the first assertion reds; drop the writer line and the second does."""
    fields = reg.metric_truth("steps")["field_by_source"]
    assert fields["whoop"] == "step_count"
    assert _writer_writes("lambdas/ingestion/whoop_lambda.py", '_set_dec(fields, "step_count"')
    assert fields["apple_health"] == "steps"
    assert _writer_writes("lambdas/ingestion/health_auto_export_lambda.py", '{"field": "steps", "agg": "sum"')


# ── box 4: the reproduce command, driven over a fake table holding the wire rows ──


class _FakeTable:
    def __init__(self, items):
        self._items = items

    def get_item(self, Key):
        item = self._items.get((Key["pk"], Key["sk"]))
        return {"Item": dict(item)} if item else {}


def test_the_reproduce_command_names_the_winner_and_rebuilds_the_movement_score():
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import resolve_steps_day_4630 as cmd

    day = "2026-10-14"
    table = _FakeTable(
        {
            (WHOOP_ROW["pk"], WHOOP_ROW["sk"]): WHOOP_ROW,
            (APPLE_ROW["pk"], APPLE_ROW["sk"]): APPLE_ROW,
            ("USER#matthew#SOURCE#strava", "DATE#" + day): {"activity_count": Decimal("1"), "total_moving_time_seconds": Decimal("10057")},
            ("USER#matthew", "PROFILE#v1"): {"step_target": Decimal("7000")},
            ("USER#matthew#SOURCE#day_grade", "DATE#" + day): {"component_movement": Decimal("100")},
        }
    )
    lines = cmd.explain_day(table, day)
    assert "  whoop         17,739" in lines and "  garmin        no row" in lines
    assert lines[4] == "resolved 17739 from whoop — whoop is the truth source and has a count"
    assert lines[5].startswith("movement 100 = exercise 100 x0.50 + steps 100 x0.50")
    assert lines[6] == "stored component_movement 100 (matches)"
