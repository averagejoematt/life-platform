"""tests/test_date_range_end_bound_4129.py — a date-range read of a partition with suffixed sort
keys must close its END day (#4129).

THE BUG
  Hevy per-workout rows are `DATE#YYYY-MM-DD#WORKOUT#<id>`, which sorts AFTER `DATE#YYYY-MM-DD`.
  `sk BETWEEN DATE#{start} AND DATE#{end}` therefore returns every per-workout row EXCEPT the
  end day's. `daily-metrics-compute`'s `fetch_range` put each lifting session into TSB a day
  late; `/api/training_overview` (via `site_api_common._query_source`) divided its per-muscle
  rate by days whose sessions it had not read (21.0 vs 23.7 back sets/wk, 2026-09-23).

THIS FILE
  1. THE SET — `scripts/date_range_read_census.py` enumerates every sk `between` /
     `begins_with` date-range read in lambdas/ + mcp/ (both the boto3 resource form and the
     `"sk BETWEEN :s AND :e"` expression form), and classifies each against the SUFFIXED
     partitions DERIVED from docs/SCHEMA.md + the live pk-family census. The guard: no
     unsuffixed end bound on a suffixed partition, or on a HELPER whose partition is a
     parameter (any caller can hand it hevy). No hand list of partitions exists — both legs
     are derived; the specimen floor below pins that the derivation still sees hevy/whoop.
  2. MUTATION CONTROLS — the guard reds on (a) a synthetic unsuffixed helper, (b) a synthetic
     unsuffixed hevy read, (c) the REAL `fetch_range` with its suffix stripped; and each
     derivation leg reds when its evidence is removed.
  3. THE BEHAVIOUR — a session logged on the END day is read by `fetch_range` (and so enters
     the TSB load map) and by the site training window (and so is counted in the per-muscle
     volume). The mutation control re-executes each function with the `~` dropped and proves
     the same fixture then loses the session.
"""

from __future__ import annotations

import inspect
import os
import re
import sys
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "lambdas"))
sys.path.insert(0, str(REPO / "scripts"))

# The lambdas' own defaults. NOT a test-only name: an env var set at collection leaks into every
# later-imported module, and methods_registry's closure fingerprint hashes a module-level
# `table`'s repr — a "test-table" here re-keyed coach_prediction_evaluator's fingerprint for
# every test collected after this file.
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_REGION", "us-west-2")

import date_range_read_census as census  # noqa: E402

HEVY_PK = "USER#matthew#SOURCE#hevy"
START, MID, END = "2026-09-20", "2026-09-21", "2026-09-22"


# ── 1. the derived suffixed-partition set ────────────────────────────────────────


def test_the_suffixed_set_is_derived_and_still_sees_the_specimens():
    """The specimen floor: hevy (the #4129 bug) and whoop (WORKOUT# sub-rows, #3442) must be
    derived as suffixed, plus the journal/transaction partitions. If this reds, a derivation
    leg stopped parsing — not a reason to add a hand list."""
    suffixed = census.suffixed_sources()
    for src in ("hevy", "whoop", "notion", "food_delivery", "macrofactor_meals", "training_notes"):
        assert src in suffixed, f"{src} is no longer derived as a suffixed partition: {sorted(suffixed)}"
    # and it is not everything — a daily-only source is not suffixed
    for src in ("withings", "habitify", "computed_metrics", "character_sheet"):
        assert src not in suffixed, f"{src} derived as suffixed: {suffixed[src]}"


def test_the_schema_leg_alone_finds_hevy_because_the_live_census_cannot():
    """The live census's representative hevy sk is a legacy BARE daily row, so the schema leg
    is the only one that knows hevy is suffixed. Pinned so nobody 'simplifies' to one leg."""
    assert "hevy" in census.schema_suffixed_sources()
    assert "whoop" in census.schema_suffixed_sources()


def test_each_derivation_leg_can_fail():
    """Mutation controls for the derivation: evidence present → derived; removed → not."""
    row = "| `…SOURCE#newsrc` / `DATE#<d>#<id>` | a many-per-day thing | w | r | raw_timeseries | ✓ |"
    assert "newsrc" in census.schema_suffixed_sources(row)
    assert "newsrc" not in census.schema_suffixed_sources(row.replace("DATE#<d>#<id>", "DATE#<d>"))
    # a parenthetical sub-item on a grouped row is NOT applied to every member of the group
    grouped = "| `…SOURCE#{aa, bb}` / `DATE#<d>` (+ `DATE#<d>#WORKOUT#<id>` sub-items) | x | w | r | c | ✓ |"
    assert census.schema_suffixed_sources(grouped) == {}
    live = {"families": {"SOURCE#newsrc": {"rep_sk": "DATE#2026-01-01#TXN#001"}, "SOURCE#daily": {"rep_sk": "DATE#2026-01-01"}}}
    assert set(census.census_suffixed_sources(live)) == {"newsrc"}


# ── 1b. the census itself ────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def reads():
    return census.census()


def test_the_census_is_not_vacuous(reads):
    """A scanner that silently matches nothing would pass the guard. Both spellings and a
    realistic population must be present."""
    dated = census.date_range_reads(reads)
    assert len(dated) >= 150, f"only {len(dated)} date-range reads found — the scanner broke"
    forms = {r.form for r in dated}
    assert forms == {"resource", "expression"}, forms
    assert any(r.op == "begins_with" for r in dated)


@pytest.mark.parametrize(
    "path,func",
    [
        ("lambdas/compute/daily_metrics_compute_lambda.py", "fetch_range"),
        ("lambdas/web/site_api_common.py", "_query_source"),
        ("lambdas/web/site_api_common.py", "_latest_item_asof"),
        ("lambdas/common/digest_utils.py", "query_range"),
    ],
)
def test_the_named_helpers_are_members_and_closed(reads, path, func):
    """The two consumers #4129 names, plus the helpers they share a shape with, are in the SET
    as HELPERS (partition = caller's choice) and close their end day."""
    suffixed = census.suffixed_sources()
    members = [r for r in reads if r.path == path and r.func == func and r.op == "between"]
    assert members, f"{path}::{func} is not in the census"
    for r in members:
        assert r.is_helper, f"{path}::{func} pk rendered {r.pk!r} — expected a caller-supplied partition"
        assert r.verdict(suffixed) == "ok-suffixed-end", (r.hi, r.verdict(suffixed))


def test_no_unsuffixed_end_bound_on_a_suffixed_or_caller_supplied_partition(reads):
    """THE GUARD. Fix a red by ending the range with `~` (the house spelling — on a partition
    with no suffixed rows it admits nothing extra) or by reading `begins_with` per day."""
    bad = census.violations(reads)
    assert not bad, "unsuffixed end bound on a partition that can carry DATE#<d>#… rows (#4129):\n" + "\n".join(
        f"  {r.path}:{r.line} {r.func} [{r.partition_class(census.suffixed_sources())}] {r.lo} .. {r.hi}" for r in bad
    )


# ── 2. mutation controls for the guard ───────────────────────────────────────────

_HELPER_SRC = textwrap.dedent("""
    from boto3.dynamodb.conditions import Key
    USER_PREFIX = "USER#matthew#SOURCE#"

    def fetch(source, start, end):
        return table.query(KeyConditionExpression=Key("pk").eq(USER_PREFIX + source) & Key("sk").between(f"DATE#{start}", f"DATE#{end}{SUFFIX}"))

    def fetch_expr(source, start, end):
        return table.query(
            KeyConditionExpression="pk = :pk AND sk BETWEEN :s AND :e",
            ExpressionAttributeValues={":pk": USER_PREFIX + source, ":s": "DATE#" + start, ":e": "DATE#" + end + "{SUFFIX}"},
        )

    def hevy_window(start, end):
        return table.query(KeyConditionExpression=Key("pk").eq(f"{USER_PREFIX}hevy") & Key("sk").between(f"DATE#{start}", f"DATE#{end}{SUFFIX}"))

    def withings_window(start, end):
        return table.query(KeyConditionExpression=Key("pk").eq(f"{USER_PREFIX}withings") & Key("sk").between(f"DATE#{start}", f"DATE#{end}"))
    """)


def _scan_snippet(tmp_path, suffix):
    p = tmp_path / "snippet.py"
    p.write_text(_HELPER_SRC.replace("{SUFFIX}", suffix), encoding="utf-8")
    return {r.func: r.verdict(census.suffixed_sources()) for r in census.scan_file(p, "snippet.py")}


def test_mutation_control_the_guard_reds_on_unsuffixed_reads(tmp_path):
    verdicts = _scan_snippet(tmp_path, "")
    assert verdicts["fetch"] == "VIOLATION-helper"
    assert verdicts["fetch_expr"] == "VIOLATION-helper"
    assert verdicts["hevy_window"] == "VIOLATION-suffixed"
    # a daily-only partition's unsuffixed read is exact, not a violation
    assert verdicts["withings_window"] == "ok-partition-has-no-suffixed-sk"


def test_mutation_control_the_same_reads_pass_once_suffixed(tmp_path):
    verdicts = _scan_snippet(tmp_path, "~")
    assert verdicts["fetch"] == verdicts["fetch_expr"] == verdicts["hevy_window"] == "ok-suffixed-end"


def test_mutation_control_stripping_the_real_fetch_range_suffix_reds(tmp_path):
    """The real file, mutated: drop the `~` from daily_metrics_compute_lambda.fetch_range."""
    src = (REPO / "lambdas/compute/daily_metrics_compute_lambda.py").read_text(encoding="utf-8")
    mutated = src.replace('":e": "DATE#" + end + "~",', '":e": "DATE#" + end,')
    assert mutated != src, "fetch_range no longer spells its end bound the way this control expects"
    p = tmp_path / "dmc_mutated.py"
    p.write_text(mutated, encoding="utf-8")
    bad = census.violations(census.scan_file(p, "dmc_mutated.py"))
    assert [r.func for r in bad] == ["fetch_range"]


# ── 3. behaviour: the END day's session is read ──────────────────────────────────

_EXPR_BETWEEN = re.compile(r"pk = (:\w+) AND sk BETWEEN (:\w+) AND (:\w+)")


def _eval_key(cond, item):
    expr = cond.get_expression()
    op, vals = expr["operator"], expr["values"]
    if op == "AND":
        return _eval_key(vals[0], item) and _eval_key(vals[1], item)
    actual = str(item.get(vals[0].name, ""))
    if op == "=":
        return actual == vals[1]
    if op == "BETWEEN":
        return vals[1] <= actual <= vals[2]
    if op == "begins_with":
        return actual.startswith(vals[1])
    raise AssertionError(f"fake table: unhandled key operator {op!r}")


class _FakeTable:
    """Evaluates the key condition for real — both spellings — so the sort order is the one
    DynamoDB applies (byte order of the sk string)."""

    def __init__(self, rows):
        self.rows = rows

    def query(self, **kw):
        kce = kw["KeyConditionExpression"]
        if isinstance(kce, str):
            m = _EXPR_BETWEEN.search(kce)
            assert m, f"fake table: unhandled expression {kce!r}"
            eav = kw["ExpressionAttributeValues"]
            pk, lo, hi = eav[m.group(1)], eav[m.group(2)], eav[m.group(3)]
            rows = [r for r in self.rows if r["pk"] == pk and lo <= r["sk"] <= hi]
        else:
            rows = [r for r in self.rows if _eval_key(kce, r)]
        return {"Items": sorted(rows, key=lambda r: r["sk"])}


def _bench(date, uid, n_sets=4):
    return {
        "pk": HEVY_PK,
        "sk": f"DATE#{date}#WORKOUT#{uid}",
        "date": date,
        "phase": "experiment",
        "duration_sec": 3600,
        "exercises": [
            {
                "name": "Bench Press (Barbell)",
                "template_id": "79D0BD87",
                "notes": "",
                "sets": [{"type": "normal", "weight_kg": 60.0, "reps": 8, "rpe": None, "set_index": i} for i in range(n_sets)],
            }
        ],
    }


ROWS = [_bench(START, "w-start"), _bench(MID, "w-mid"), _bench(END, "w-end")]


def _without_suffix(module, func_name, old, new):
    """Re-execute `module.func_name` with its end-bound suffix removed, in a copy of the
    module's globals (so the monkeypatched fake table is the one it reads)."""
    src = textwrap.dedent(inspect.getsource(getattr(module, func_name)))
    assert old in src, f"{func_name} no longer spells its end bound as {old!r}"
    ns = dict(module.__dict__)
    exec(compile(src.replace(old, new), f"<mutated {func_name}>", "exec"), ns)  # noqa: S102 — test-only mutation control
    return ns[func_name]


@pytest.fixture
def dmc(monkeypatch):
    from compute import daily_metrics_compute_lambda as mod

    monkeypatch.setattr(mod, "table", _FakeTable(list(ROWS)))
    return mod


def test_fetch_range_reads_the_end_day_session_and_tsb_sees_it(dmc):
    from training import training_load

    got = dmc.fetch_range("hevy", START, END)
    assert {r["sk"] for r in got} == {r["sk"] for r in ROWS}, "the END day's per-workout row was dropped"
    load_by_day, _basis = training_load.daily_training_load([], got, None)
    assert END in load_by_day and load_by_day[END] > 0, f"the end-day session never reached the load map: {load_by_day}"


def test_mutation_control_fetch_range_without_the_suffix_drops_the_end_day(dmc):
    mutated = _without_suffix(dmc, "fetch_range", '"DATE#" + end + "~"', '"DATE#" + end')
    got = mutated("hevy", START, END)
    assert {r["date"] for r in got} == {START, MID}, "the control must reproduce the #4129 drop, or it proves nothing"


@pytest.fixture
def common(monkeypatch):
    import web.site_api_common as mod

    monkeypatch.setattr(mod, "table", _FakeTable(list(ROWS)))
    return mod


def test_site_training_window_counts_the_end_day_session(common):
    from web.site_api_training import _compute_muscle_volume

    items = common._query_source("hevy", START, END)
    assert END in {r["date"] for r in items}, "the site window dropped the END day's session"
    chest = {row["muscle"]: row for row in _compute_muscle_volume(items, 1.0, start_date=START, end_date=END)}["Chest"]
    assert chest["total_sets"] == 12, chest  # 3 sessions x 4 working sets — the end day included


def test_mutation_control_site_window_without_the_suffix_undercounts(common):
    from web.site_api_training import _compute_muscle_volume

    mutated = _without_suffix(common, "_query_source", 'f"DATE#{end_date}~"', 'f"DATE#{end_date}"')
    items = mutated("hevy", START, END)
    assert END not in {r["date"] for r in items}
    chest = {row["muscle"]: row for row in _compute_muscle_volume(items, 1.0, start_date=START, end_date=END)}["Chest"]
    assert chest["total_sets"] == 8, chest  # the #4129 shape: the rate's window counts a day it did not read


def test_the_fingerprint_reads_the_day_strain_not_a_workouts(monkeypatch):
    """Adversarial review of this PR (2026-09-23): `/api/fingerprint` reads ONE day, so once the
    end bound includes end-day sub-rows a `#WORKOUT#` row's strain overwrote the day's."""
    from web import site_api_fingerprint as fp

    rows = {
        "whoop": [
            {"sk": "DATE#2026-09-22", "strain": 14.2, "recovery_score": 55},
            {"sk": "DATE#2026-09-22#WORKOUT#abc", "strain": 6.3},
        ]
    }
    monkeypatch.setattr(fp, "_query_source", lambda src, s, e, **k: rows.get(src, []))
    assert fp._metrics_index("2026-09-22", "2026-09-22")["2026-09-22"]["strain"] == 14.2
