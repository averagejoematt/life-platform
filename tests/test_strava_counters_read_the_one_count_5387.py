"""tests/test_strava_counters_read_the_one_count_5387.py — no module counts Strava activities on its own (#5387).

Fifteen readers counted or summed Strava activities directly — `len(activities)`, the day row's
`activity_count`, a sum of `moving_time_seconds`, the day's `total_zone2_seconds` — outside the
cross-source resolver, so one gym visit (Hevy's whole-session push plus the ride inside it) read as two
sessions and 220 minutes. They now read `training.session_count` (THE count over
`training.workout_identity`'s parts) and, for Zone 2, `training.zone2_minutes` through it. This guards the
SET, not the fifteen: every module under `lambdas/` and `mcp/` is parsed, so a NEW module that counts or
sums Strava activities across a day without the helper reds CI wherever it lands.

The detector reads the AST (comments and docstrings cannot trip it) and flags:
  * a READ of a Strava day total — `activity_count`, `total_moving_time_seconds`, `total_zone2_seconds` —
    as a subscript, a `.get(...)`, a `safe_float(row, "...")`-style argument or an `in` test (a dict-literal
    key or an assignment target is a write, not a read);
  * `sum(...)`, `+` or `+=` over a per-activity `moving_time_seconds` / `zone2_seconds`;
  * `len(...)` of anything named for activities, and a `+= 1` inside a loop over activities.
A module the Strava writers own (`lambdas/ingestion/`), the four shared rules (the read seam, the resolver,
THE Zone 2 computation and THE count itself) and the residual below are exempt; a single line may carry
`# session-count: <reason>`. The residual is a ratchet: an entry whose module no longer trips the detector
must be pruned, and a module may never join it silently.
"""

# premerge-gate: sweeps every module under lambdas/ and mcp/ — a repo-shape ratchet whose verdict depends only on the tree

from __future__ import annotations

import ast
import functools
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCAN_DIRS = ("lambdas", "mcp")

DAY_TOTALS = frozenset({"activity_count", "total_moving_time_seconds", "total_zone2_seconds"})
PER_ACTIVITY = frozenset({"moving_time_seconds", "zone2_seconds"})
ACTIVITIES = re.compile(r"activit", re.I)
LINE_MARKER = "# session-count:"

#: The writers (`lambdas/ingestion/*`) and the shared rules every reader calls.
EXEMPT_PREFIXES = ("lambdas/ingestion/",)
SHARED_RULES = frozenset(
    {
        "lambdas/common/strava_read_seam.py",  # the multi-device fold, which restates the day totals it dedupes
        "lambdas/training/workout_identity.py",  # the cross-source resolver
        "lambdas/training/zone2_minutes.py",  # THE Zone 2 computation (#4627)
        "lambdas/training/session_count.py",  # THE count (#5387)
    }
)

#: The issue's Set (#5387): each must read THE count and trip nothing.
SET = (
    "lambdas/web/site_api_training.py",
    "lambdas/intelligence/labelled_facts.py",
    "lambdas/health/character_engine.py",
    "lambdas/emails/weekly_digest_extractors.py",
    "lambdas/emails/monthly_digest_lambda.py",
    "lambdas/emails/partner_email_lambda.py",
    "lambdas/emails/daily_brief_lambda.py",
    "lambdas/health/milestone_ledger.py",
    "lambdas/compute/hypothesis_engine_lambda.py",
    "lambdas/compute/daily_insight_compute_lambda.py",
    "lambdas/health/scoring_engine.py",
    "lambdas/ai/ai_summaries.py",
    "lambdas/intelligence/field_notes_lambda.py",
    "mcp/helpers.py",
    "lambdas/training/training_load.py",
)

#: Modules the detector trips that are NOT the issue's Set — read by hand on this branch, each with its
#: disposition. `not-a-count` = the shape is there but nothing is counted across a day's sources;
#: `residual (follow-up)` = a real direct count the issue's grep missed, left for a carrier issue (the PR
#: names them). Ratchet: prune an entry once its module stops tripping the detector; never add one to hide a
#: new counter.
RESIDUAL: dict[str, str] = {
    # the issue's own "not members", re-read
    "lambdas/ai/ai_context.py": "not-a-count: the activity_count read is discarded; activity_count_7d is len(day rows) = days",
    "lambdas/emails/freshness_checker_lambda.py": "not-a-count: the field name as a freshness key",
    "mcp/tools_data.py": "not-a-count: field names only",
    "mcp/tools_lifestyle.py": "not-a-count: a trained-today boolean (activity_count > 0)",
    "lambdas/web/site_api_autonomic.py": "not-a-count: the resolver's own weekly activity_count (zone2_minutes.weekly)",
    "mcp/tools_correlation.py": "not-a-count: the resolver's own weekly activity_count (zone2_minutes.weekly)",
    "lambdas/health/tdee.py": "not-a-count: energy splits by modality and claims Hevy's span (#5370 audit row 4)",
    # the renderers/recomputers beside Set members: they read THE count's output, or restate the seam's totals
    "lambdas/emails/monthly_digest_render.py": "not-a-count: renders ex_strava's activity_count (THE count)",
    "lambdas/emails/weekly_digest_lambda.py": "not-a-count: renders ex_strava's activity_count (THE count)",
    "lambdas/compute/daily_metrics_compute_lambda.py": "not-a-count: its multi-device dedupe restates the seam's day totals; the day grade counts through scoring_engine (THE count)",
    "lambdas/common/digest_utils.py": "not-a-count: the pre-seam dedupe's early return (len <= 1)",
    "lambdas/compute/dashboard_refresh_lambda.py": "not-a-count: the pre-seam dedupe's early return (len <= 1)",
    "lambdas/emails/daily_brief_signals.py": "not-a-count: the pre-seam dedupe (early return, richness score)",
    "lambdas/compute/episode_detect_lambda.py": "not-a-count: counts its own classified episodes by kind",
    # residual: direct counters the issue's grep missed (follow-up named on the PR)
    "lambdas/intelligence/ai_expert_analyzer_lambda.py": "residual (follow-up): strava_sessions = len(activities), total_active_min = hevy_min + strava_min",
    "lambdas/content/output_writers.py": "residual (follow-up): total_sessions over 28 days of Strava activities, an average-HR Zone 2",
    "lambdas/emails/chronicle_render.py": "residual (follow-up): training_sessions = len(the day's activities)",
    "lambdas/compute/weekly_correlation_compute_lambda.py": "residual (follow-up): training_mins = the day's summed moving_time_seconds",
    "mcp/tools_health.py": "residual (follow-up): a day's exercise minutes = summed moving_time_seconds",
    "mcp/tools_training.py": "residual (follow-up): weekly sessions counted per Strava activity",
}


def _names(node: ast.AST) -> set[str]:
    out: set[str] = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Name):
            out.add(n.id)
        elif isinstance(n, ast.Attribute):
            out.add(n.attr)
        elif isinstance(n, ast.Constant) and isinstance(n.value, str):
            out.add(n.value)
    return out


def _names_activities(node: ast.AST) -> bool:
    return any(ACTIVITIES.search(n) for n in _names(node))


def _writes(tree: ast.AST) -> set[int]:
    """ids of the string constants that are WRITES: dict-literal keys, assignment-target subscripts and
    docstrings — the detector's day-total read never fires on them."""
    skip: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            skip.update(id(k) for k in node.keys if k is not None)
        elif isinstance(node, ast.Subscript) and isinstance(node.ctx, (ast.Store, ast.Del)):
            skip.add(id(node.slice))
        elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            skip.add(id(node.value))
    return skip


def offenders(source: str | ast.AST, rel: str = "<snippet>", lines: list[str] | None = None) -> list[str]:
    """`rel:line shape` for every place `source` counts or sums Strava activities on its own."""
    try:
        tree = ast.parse(source) if isinstance(source, str) else source
    except SyntaxError:
        return []
    if lines is None:
        lines = source.splitlines() if isinstance(source, str) else []
    skip = _writes(tree)
    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        shape = None
        if isinstance(node, ast.Constant) and node.value in DAY_TOTALS and id(node) not in skip:
            shape = f"reads the day's {node.value}"
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("sum", "len") and node.args:
            arg = node.args[0]
            if node.func.id == "sum" and _names(arg) & PER_ACTIVITY:
                shape = "sums per-activity time"
            elif node.func.id == "len" and _names_activities(arg):
                shape = "counts activities"
        elif isinstance(node, ast.AugAssign) and isinstance(node.op, ast.Add) and _names(node.value) & PER_ACTIVITY:
            shape = "sums per-activity time"
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add) and (_names(node.left) | _names(node.right)) & PER_ACTIVITY:
            shape = "sums per-activity time"
        elif isinstance(node, ast.For) and _names_activities(node.iter):
            for inner in ast.walk(node):
                if (
                    isinstance(inner, ast.AugAssign)
                    and isinstance(inner.op, ast.Add)
                    and isinstance(inner.value, ast.Constant)
                    and inner.value.value == 1
                ):
                    hits.append((inner.lineno, "counts activities in a loop"))
        if shape:
            hits.append((getattr(node, "lineno", 0), shape))
    out = []
    for lineno, shape in sorted(set(hits)):
        if 0 < lineno <= len(lines) and LINE_MARKER in lines[lineno - 1]:
            continue
        out.append(f"{rel}:{lineno} {shape}")
    return out


@functools.lru_cache(maxsize=1)
def _swept() -> tuple[int, tuple[tuple[str, tuple[str, ...]], ...]]:
    """(modules swept, (rel path, its offenders) for every module with at least one)."""
    swept = 0
    found = []
    for top in SCAN_DIRS:
        for dirpath, dirnames, filenames in os.walk(os.path.join(ROOT, top)):
            dirnames[:] = [d for d in dirnames if d not in {"__pycache__", ".pytest_cache", "node_modules"}]
            for name in filenames:
                if not name.endswith(".py"):
                    continue
                full = os.path.join(dirpath, name)
                rel = os.path.relpath(full, ROOT).replace(os.sep, "/")
                swept += 1
                if rel.startswith(EXEMPT_PREFIXES) or rel in SHARED_RULES:
                    continue
                with open(full, encoding="utf-8") as fh:
                    text = fh.read()
                hits = offenders(text, rel, text.splitlines())
                if hits:
                    found.append((rel, tuple(hits)))
    return swept, tuple(found)


def test_no_module_counts_strava_activities_on_its_own():
    swept, found = _swept()
    assert swept > 200, f"the sweep read only {swept} modules — the scan root moved"
    new = [hit for rel, hits in found if rel not in RESIDUAL for hit in hits]
    assert not new, (
        "a module counts or sums Strava activities on its own — one gym visit is Hevy's push plus the ride inside "
        "it, so a direct count reads it as two sessions (#5387). Read `training.session_count` (and its "
        f"`zone2_*` for Zone 2), or mark a line that counts nothing with `{LINE_MARKER} <reason>`: {new}"
    )


def test_every_set_member_reads_the_one_count_and_trips_nothing():
    swept_hits = dict(_swept()[1])
    for rel in SET:
        assert rel not in RESIDUAL and rel not in SHARED_RULES, rel
        with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        imports = {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module == "training" for a in n.names}
        assert "session_count" in imports, f"{rel}: does not import training.session_count"
        assert rel not in swept_hits, f"{rel}: {swept_hits.get(rel)}"


def test_the_residual_is_a_ratchet():
    """Every residual entry still trips the detector (prune it the day it stops) and names its disposition."""
    tripped = {rel for rel, _ in _swept()[1]}
    stale = sorted(rel for rel in RESIDUAL if rel not in tripped)
    assert not stale, f"residual entries whose module no longer counts on its own — delete them: {stale}"
    assert all(r.split(":", 1)[0] in ("not-a-count", "residual (follow-up)") for r in RESIDUAL.values())


def test_every_shape_is_caught_and_a_write_is_not():
    """Mutation controls: each planted shape reds — the retired Set readings among them — and a write of
    the same names (the writer's own dict, an assignment target) and a docstring do not."""
    planted = {
        "len_of_flattened": "n = len(_dedup_whoop(_flatten_day_activities(rows)))\n",
        "len_of_day_list": "n = sum(len(d.get('activities') or []) for d in days)\n",
        "day_count_get": "n = int(day.get('activity_count') or 0)\n",
        "day_count_safe_float": "n = safe_float(strava, 'activity_count')\n",
        "day_minutes_subscript": "t = row['total_moving_time_seconds'] / 60\n",
        "day_zone2_in_test": "z = st['total_zone2_seconds'] if 'total_zone2_seconds' in st else None\n",
        "sum_moving": "t = sum(float(a.get('moving_time_seconds') or 0) for a in acts)\n",
        "augassign_zone2": "for a in acts:\n    z += float(a.get('zone2_seconds') or 0) / 60\n",
        "loop_count": "for a in r.get('activities', []):\n    total_acts += 1\n",
    }
    for shape, src in planted.items():
        assert offenders(src), f"the {shape} shape was not caught: {src!r}"
    clean = (
        '"""activity_count and total_moving_time_seconds in a docstring."""\n'
        "out = {'activity_count': n, 'total_moving_time_seconds': t}\n"
        "row['activity_count'] = n\n"
        "secs = a.get('moving_time_seconds')\n"
        "n = len(acts)  # session-count: a list length the caller never serves\n"
    )
    assert offenders(clean) == []
    assert offenders("n = len(activities)  # session-count: the dedupe's early return\n") == []


def test_the_population_is_live():
    """Not vacuous: the sweep finds the residual's real hits (a vocabulary rename would empty it)."""
    _, found = _swept()
    assert len(found) >= len([r for r in RESIDUAL.values() if r.startswith("residual")]), found
