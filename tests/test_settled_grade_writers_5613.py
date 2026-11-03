"""tests/test_settled_grade_writers_5613.py — a settled grade changes only through grade_corrections (#5613).

Owner integrity item 7 (2026-11-02): versioned rules never silently rewrite history. The rule lives in
``lambdas/coach/grade_corrections.py`` (THE INVARIANTS): ``status / outcome / outcome_notes`` on a settled
``PREDICTION#`` row are written only by ``grade_corrections.apply_correction`` (and its ledgered inverse
``revert_correction``); the scheduled grader writes through ``grade_corrections.write_first_grade``, which
refuses a settled row.

This guard is the structural half: an AST sweep of ``lambdas/``, ``deploy/``, ``scripts/`` and ``mcp/``
for every function that writes a DynamoDB update (``update_item`` / ``transact_write_items``, or an
``UpdateExpression`` it builds for one) whose expression SETs ``outcome`` or ``outcome_notes`` — the
grading vocabulary — or SETs ``status`` in a module that names ``PREDICTION#`` rows. Every such writer
must be in ``SANCTIONED`` (grade_corrections) or in ``OTHER_ROW_FAMILIES`` with the row family it
writes and why that is not a settled prediction grade. A new writer of a settled grade anywhere else
fails here; so does a stale entry (an entry whose writer no longer matches is pruned, never left to
licence a regrowth).

The detector is syntactic and says so: an expression assembled entirely from runtime values (no string
constant naming the field) is invisible to it. Its population floor (``test_the_sweep_sees_the_known_writers``)
fails if the sweep goes blind.
"""

from __future__ import annotations

import ast
import functools
import os
import re

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOTS = ("lambdas", "deploy", "scripts", "mcp")
_SKIP_DIRS = {"node_modules", "__pycache__", ".venv", "cdk.out"}

# premerge-gate: 5613: an os.walk sweep of lambdas/, deploy/, scripts/ and mcp/ for any NEW writer of a settled PREDICTION# row's status/outcome/outcome_notes outside coach.grade_corrections — a writer that rewrites a grade without the correction ledger must red BEFORE merge, not after a grading run has rewritten history.

GRADE_FIELDS = ("status", "outcome", "outcome_notes")
_SET_LHS = re.compile(r"(?<![\w.])(#?\w+)\s*=\s*:")
_WRITE_CALLS = {"update_item", "transact_write_items"}

#: The ONE module allowed to change a settled grade: every write here keeps the original and records
#: corrected_at / reason / evaluator_version (apply_correction, revert_correction) or refuses a settled row
#: (write_first_grade).
SANCTIONED = {
    ("lambdas/coach/grade_corrections.py", "apply_correction"),
    ("lambdas/coach/grade_corrections.py", "revert_correction"),
    ("lambdas/coach/grade_corrections.py", "write_first_grade"),
}

#: Writers the sweep matches that are NOT a settled prediction grade — each with its row family and reason —
#: plus the four pre-ledger, run-once PREDICTION# corrections whose --apply #5613 retired (their apply()
#: bodies stay for the record and their own tests; main() refuses --apply before any AWS call, asserted below).
OTHER_ROW_FAMILIES = {
    ("lambdas/coach/commitment_grading.py", "write_status"): "COMMITMENT# rows — a commitment's follow-through, not a prediction grade",
    ("lambdas/coach/dispute_docket.py", "_mark_resolved"): "the docket's OPEN# rows — a resolution marker, not a prediction grade",
    ("lambdas/intelligence/intelligence_common.py", "complete_action"): "SOURCE#coach_actions rows — an action's completion state",
    ("lambdas/emails/coach_nudge_lambda.py", "run_grading_pass"): "NUDGE rows — a nudge's outcome + Brier, not a prediction grade",
    ("deploy/archive/end_april_failures_2026_05_03.py", "end_experiment"): "EXPERIMENT rows — an archived one-off, not a prediction grade",
    ("deploy/archive/end_april_failures_2026_05_03.py", "end_challenge"): "CHALLENGE rows — an archived one-off, not a prediction grade",
    ("mcp/tools_decisions.py", "tool_update_decision_outcome"): "DECISION rows — the owner's own decision outcome",
    ("mcp/tools_lifestyle.py", "tool_update_insight_outcome"): "INSIGHT# rows — an insight's acted/resolved state",
    ("mcp/tools_lifestyle.py", "tool_end_experiment"): "EXPERIMENT rows — the owner ending an N=1 experiment",
    ("mcp/tools_coach_checkin.py", "tool_log_coach_checkin"): "CHECKIN rows — a check-in's answered state",
    ("scripts/training_block_retro.py", "prediction_update"): (
        "OPEN-ONLY: the block retro's first grade of an open charter prediction, conditional on `#s = :open` — "
        "it cannot change a settled grade (asserted below)"
    ),
    ("scripts/regrade_tomorrow_calls_4618.py", "_write"): "RETIRED (#5613): pre-ledger run-once PREDICTION# correction; --apply refused",
    ("scripts/regrade_level_claims_3551.py", "apply"): "RETIRED (#5613): pre-ledger run-once PREDICTION# correction; --apply refused",
    ("scripts/regrade_count_claims_4541.py", "apply"): "RETIRED (#5613): pre-ledger run-once PREDICTION# correction; --apply refused",
    (
        "scripts/regrade_direction_calls_4617.py",
        "update_kwargs",
    ): "RETIRED (#5613): pre-ledger run-once PREDICTION# correction; --apply refused",
}

RETIRED_SCRIPTS = sorted({path for (path, _fn), why in OTHER_ROW_FAMILIES.items() if why.startswith("RETIRED")})


def _consts(node: ast.AST) -> list[str]:
    return [n.value for n in ast.walk(node) if isinstance(n, ast.Constant) and isinstance(n.value, str)]


def _is_writer(fnode: ast.AST) -> bool:
    for n in ast.walk(fnode):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in _WRITE_CALLS:
            return True
        if isinstance(n, ast.keyword) and n.arg == "UpdateExpression":
            return True
        if isinstance(n, ast.Dict) and any(isinstance(k, ast.Constant) and k.value == "UpdateExpression" for k in n.keys):
            return True
    return False


def _grade_fields_set(fnode: ast.AST) -> set[str]:
    """The grade fields this function's update expressions SET — directly, or through a ``#alias`` whose
    target name is a string constant in the same function."""
    consts = _consts(fnode)
    lhs = {m.group(1) for c in consts for m in _SET_LHS.finditer(c)}
    direct = {x for x in lhs if x in GRADE_FIELDS}
    aliased = {c for c in consts if c in GRADE_FIELDS} if any(x.startswith("#") for x in lhs) else set()
    return direct | aliased


def grade_writers(root: str = _REPO) -> dict[tuple[str, str], set[str]]:
    """``{(path, function): fields}`` for every writer of a grade field the sweep can see."""
    return dict(_grade_writers(root))


@functools.lru_cache(maxsize=None)
def _grade_writers(root: str) -> tuple:
    out: dict[tuple[str, str], set[str]] = {}
    for top in ROOTS:
        for dirpath, dirnames, filenames in os.walk(os.path.join(root, top)):
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
            for fname in filenames:
                if not fname.endswith(".py"):
                    continue
                path = os.path.join(dirpath, fname)
                rel = os.path.relpath(path, root).replace(os.sep, "/")
                try:
                    tree = ast.parse(open(path, encoding="utf-8").read())
                except (SyntaxError, UnicodeDecodeError):
                    continue
                names_predictions = any("PREDICTION#" in c for c in _consts(tree))
                for fnode in ast.walk(tree):
                    if not isinstance(fnode, (ast.FunctionDef, ast.AsyncFunctionDef)) or not _is_writer(fnode):
                        continue
                    fields = _grade_fields_set(fnode)
                    if fields & {"outcome", "outcome_notes"} or ("status" in fields and names_predictions):
                        out[(rel, fnode.name)] = fields
    return tuple(out.items())


def test_no_writer_changes_a_settled_grade_outside_grade_corrections():
    found = grade_writers()
    unexplained = sorted(k for k in found if k not in SANCTIONED and k not in OTHER_ROW_FAMILIES)
    assert not unexplained, (
        "a new writer of status/outcome/outcome_notes — a settled grade changes ONLY through "
        "coach.grade_corrections.apply_correction (original kept, corrected_at/reason/evaluator_version recorded). "
        "Route the write through grade_corrections, or — if the row family is not PREDICTION# — add it to "
        f"OTHER_ROW_FAMILIES with its family and reason: {unexplained}"
    )


def test_every_registered_writer_still_exists_so_no_entry_licences_a_regrowth():
    found = grade_writers()
    stale = sorted(k for k in list(SANCTIONED) + list(OTHER_ROW_FAMILIES) if k not in found)
    assert not stale, f"registered writer no longer matched — prune the entry: {stale}"


def test_the_sweep_sees_the_known_writers():
    """Population floor: the sweep must see grade_corrections' own writers and at least the registered
    families, or it has gone blind (an AST change, a moved root) and every other assertion here is vacuous."""
    found = grade_writers()
    assert SANCTIONED <= set(found), sorted(SANCTIONED - set(found))
    assert len(found) >= len(SANCTIONED) + len(OTHER_ROW_FAMILIES)


def test_an_open_only_writer_is_conditional_on_the_open_status():
    """The OPEN-ONLY entries are allowed only because their write cannot land on a settled row."""
    open_only = [k for k, why in OTHER_ROW_FAMILIES.items() if why.startswith("OPEN-ONLY")]
    assert open_only
    for rel, fn in open_only:
        tree = ast.parse(open(os.path.join(_REPO, rel), encoding="utf-8").read())
        fnode = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == fn)
        conds = [
            v.value
            for n in ast.walk(fnode)
            if isinstance(n, ast.Dict)
            for k, v in zip(n.keys, n.values)
            if isinstance(k, ast.Constant) and k.value == "ConditionExpression" and isinstance(v, ast.Constant)
        ]
        assert conds == ["#s = :open"], f"{rel}::{fn} must stay conditional on the open status: {conds}"


def test_the_evaluator_no_longer_writes_a_grade_itself():
    """The scheduled grader's write-back is grade_corrections.write_first_grade (refuses a settled row)."""
    found = grade_writers()
    assert not [k for k in found if k[0] == "lambdas/coach/coach_prediction_evaluator.py"]
    src = open(os.path.join(_REPO, "lambdas", "coach", "coach_prediction_evaluator.py"), encoding="utf-8").read()
    assert "grade_corrections.write_first_grade(" in src and "grade_corrections.is_settled(item)" in src


def test_the_detector_catches_a_planted_writer(tmp_path):
    """Mutation in a synthetic tree: a fresh writer of outcome_notes on a PREDICTION# row is caught, and an
    aliased ``#s = :s`` status write in a PREDICTION# module is caught too."""
    pkg = tmp_path / "lambdas" / "coach"
    pkg.mkdir(parents=True)
    (pkg / "rogue.py").write_text(
        "def regrade(table, row):\n"
        "    table.update_item(Key={'pk': row['pk'], 'sk': 'PREDICTION#' + row['id']},\n"
        "                      UpdateExpression='SET outcome_notes = :n', ExpressionAttributeValues={':n': 'x'})\n"
        "def flip(table, row):\n"
        "    table.update_item(Key={'pk': row['pk'], 'sk': row['sk']}, UpdateExpression='SET #s = :s',\n"
        "                      ExpressionAttributeNames={'#s': 'status'}, ExpressionAttributeValues={':s': 'refuted'})\n",
        encoding="utf-8",
    )
    found = grade_writers(str(tmp_path))
    assert set(found) == {("lambdas/coach/rogue.py", "regrade"), ("lambdas/coach/rogue.py", "flip")}


def test_the_retired_scripts_refuse_apply_before_any_aws_call(monkeypatch):
    import importlib.util
    import sys

    for rel in RETIRED_SCRIPTS:
        spec = importlib.util.spec_from_file_location(f"_retired_{os.path.basename(rel)[:-3]}", os.path.join(_REPO, rel))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert "#5613" in mod.RETIRED_APPLY
        monkeypatch.setattr(sys, "argv", [rel, "--apply"])

        def _no_aws(*_a, **_k):
            raise AssertionError(f"{rel} reached AWS with --apply")

        import boto3

        monkeypatch.setattr(boto3, "resource", _no_aws)
        monkeypatch.setattr(boto3, "client", _no_aws)
        try:
            rc = mod.main(["--apply"])
        except TypeError:  # main() reads sys.argv
            rc = mod.main()
        assert rc == 2, rel
