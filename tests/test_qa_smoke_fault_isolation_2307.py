"""tests/test_qa_smoke_fault_isolation_2307.py — the nightly sweep cannot be
cancelled by one bad field, and the null-coercion defect class stays fixed (#2307).

Two guards, both DERIVED rather than hand-typed (#1917 / "guard the SET, not the
instance"):

1. **Fault isolation.** ``qa_smoke_lambda.lambda_handler`` used to accumulate all
   21 check calls inside a single ``try`` whose ``except`` re-raises. A stored
   ``null`` in ``day_grade`` raised ``AttributeError`` out of
   ``check_score_sanity`` and cancelled the **16** ``all_checks +=`` calls that
   sat after it. These tests walk the REAL run list (``qa.check_steps()``) and
   make each member raise in turn, asserting the handler still completes and
   reports that one step as a red ``sweep:<label>`` — never as a pass (ADR-104:
   a check that could not evaluate must SAY so), never as a lost sweep.

2. **The null-coercion class.** ``d.get(k, {})`` defaults only on a MISSING key;
   an explicitly stored ``null`` returns ``None`` and the next ``.get`` raises.
   An AST sweep over ``lambdas/operational/`` flags that form wherever the
   receiver is a parsed-JSON document (``json.loads`` output — the only values
   that can actually be ``null``). boto3 response shapes (``Contents``,
   ``Items``, ``Error``, ``Datapoints``…) are never explicitly null and are
   deliberately NOT flagged; that narrowness is what makes the guard enforceable
   (59 hits in this package with the naive rule, 5 with this one).

Fully offline — no AWS, no SES (the handler runs dry-run).
"""

import ast
import inspect
import os
import pathlib
import sys
import tempfile

import pytest

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("EMAIL_RECIPIENT", "qa@example.com")
os.environ.setdefault("EMAIL_SENDER", "qa@example.com")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "lambdas"))

from operational import qa_smoke_lambda as qa  # noqa: E402
from operational.qa_check import CONTENT_TRUTH, Check, run_isolated  # noqa: E402

OPERATIONAL = REPO / "lambdas" / "operational"


# ──────────────────────────────────────────────────────────────────────────────
# 1. Fault isolation — derived over the handler's own run list
# ──────────────────────────────────────────────────────────────────────────────


@pytest.fixture()
def stub_steps(monkeypatch):
    """Replace every real check with a cheap sentinel so the handler runs
    offline, but keep the DERIVED label set and the real wiring shape.

    Returns a callable ``(label_to_break) -> [Check]`` running the whole handler.
    """
    labels = [label for label, _fn in qa.check_steps()]

    def run(break_label=None, exc=RuntimeError("synthetic boom")):
        def fake_steps():
            steps = []
            for label in labels:
                if label == break_label:

                    def raiser(_e=exc):
                        raise _e

                    steps.append((label, raiser))
                else:

                    def ok(_lab=label):
                        return [Check(f"stub:{_lab}", "Stub", CONTENT_TRUTH).ok("stub")]

                    steps.append((label, ok))
            return steps

        captured = {}
        real_build = qa.build_report_html

        def spy(all_checks, run_time_str):
            captured["checks"] = list(all_checks)
            return real_build(all_checks, run_time_str)

        monkeypatch.setattr(qa, "check_steps", fake_steps)
        monkeypatch.setattr(qa, "build_report_html", spy)
        result = qa.lambda_handler({"dry_run": True}, None)
        assert result["statusCode"] == 200, f"handler did not complete: {result}"
        return captured["checks"]

    run.labels = labels
    return run


def test_the_run_list_is_the_handlers_only_accumulation_path():
    """No ``all_checks += <direct call>`` may survive in the handler — every
    check must route through ``run_isolated``, or one raise cancels the sweep."""
    tree = ast.parse(inspect.getsource(qa.lambda_handler))
    unguarded = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name) and node.target.id == "all_checks"):
            continue
        val = node.value
        if not (isinstance(val, ast.Call) and isinstance(val.func, ast.Name) and val.func.id == "run_isolated"):
            unguarded.append(ast.unparse(node))
    assert not unguarded, "handler accumulates a check outside run_isolated — one raise can cancel the sweep again (#2307):\n" + "\n".join(
        unguarded
    )


def test_the_derived_run_list_still_covers_the_whole_sweep():
    labels = [label for label, _fn in qa.check_steps()]
    # Derived, but sanity-anchored: the sweep had 21 accumulation steps when
    # #2307 landed. A shrink is a real signal, not a refactor artifact.
    assert len(labels) >= 21, f"the nightly run list shrank to {len(labels)} steps — a check was dropped, not moved"
    assert len(set(labels)) == len(labels), f"duplicate step labels: {labels}"
    assert "score_sanity" in labels and "blog_links" in labels
    assert all(callable(fn) for _label, fn in qa.check_steps())


def test_every_step_is_fault_isolated(stub_steps):
    """THE mutation proof, run over the DERIVED set: make each real step raise,
    one at a time, and assert the sweep survives with exactly one extra red."""
    baseline = {c.name for c in stub_steps()}
    assert len(baseline) == len(stub_steps.labels)

    for label in stub_steps.labels:
        checks = stub_steps(break_label=label)
        by_name = {c.name: c for c in checks}
        assert f"sweep:{label}" in by_name, f"step {label!r} raised and was NOT reported — the sweep swallowed or lost it"
        reported = by_name[f"sweep:{label}"]
        # ADR-104: unreadable is never a pass, and never a benign warn.
        assert reported.passed is False, f"a raising {label!r} reported passed={reported.passed!r} — must be a hard red"
        assert reported.paused is False
        assert reported.partition == qa.DEPLOY_HEALTH
        assert "did not run" in reported.message and "UNKNOWN" in reported.message
        # …and every OTHER step still ran.
        lost = baseline - set(by_name) - {f"stub:{label}"}
        assert not lost, f"making {label!r} raise also lost: {sorted(lost)}"


def test_a_raising_step_still_reaches_the_emf_line_and_the_fail_tally(stub_steps, capsys):
    """The run must still report itself — a crashed check is now a countable
    FailCount, not a dead invocation with no heartbeat (#1445)."""
    stub_steps(break_label="score_sanity")
    out = capsys.readouterr().out
    assert '"RunCompleted"' in out or "RunCompleted" in out
    assert "[QA] FAIL [deploy_health] Sweep Integrity / sweep:score_sanity" in out


def test_run_isolated_reports_any_exception_type():
    def boom():
        raise ValueError("kaboom")

    (c,) = run_isolated("mystep", boom)
    assert c.passed is False and "ValueError" in c.message and "kaboom" in c.message


def test_run_isolated_passes_a_healthy_check_through_untouched():
    sentinel = Check("x:y", "Cat", CONTENT_TRUTH).ok("fine")
    assert run_isolated("healthy", lambda: [sentinel]) == [sentinel]


# ──────────────────────────────────────────────────────────────────────────────
# 2. The null-coercion defect class — AST-derived over lambdas/operational/
# ──────────────────────────────────────────────────────────────────────────────


def _json_doc_names(fn_node):
    """Local names bound to a parsed-JSON document inside this function."""
    names = set()
    for n in ast.walk(fn_node):
        if isinstance(n, (ast.Assign, ast.AnnAssign)) and n.value is not None:
            src = ast.unparse(n.value)
            if "json.loads" in src or "json.load(" in src:
                targets = n.targets if isinstance(n, ast.Assign) else [n.target]
                names.update(t.id for t in targets if isinstance(t, ast.Name))
    return names


def _root_name(node):
    while True:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            node = node.value
        elif isinstance(node, ast.Subscript):
            node = node.value
        elif isinstance(node, ast.Call):
            node = node.func
        else:
            return None


def _is_empty_container(node):
    return (isinstance(node, ast.Dict) and not node.keys) or (isinstance(node, ast.List) and not node.elts)


def find_null_unsafe_gets(root):
    """`x.get(<literal>, {}/[])` immediately consumed, where `x` is parsed JSON."""
    offenders = []
    for path in sorted(pathlib.Path(root).rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for fn in [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
            docs = _json_doc_names(fn)
            if not docs:
                continue
            parents = {child: parent for parent in ast.walk(fn) for child in ast.iter_child_nodes(parent)}
            for node in ast.walk(fn):
                if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get"):
                    continue
                if len(node.args) != 2 or not _is_empty_container(node.args[1]):
                    continue
                if not isinstance(node.args[0], ast.Constant):
                    continue
                if _root_name(node.func.value) not in docs:
                    continue
                parent = parents.get(node)
                consumed = isinstance(parent, (ast.Attribute, ast.Subscript)) or (
                    isinstance(parent, (ast.comprehension, ast.For)) and parent.iter is node
                )
                if consumed:
                    offenders.append(f"{os.path.relpath(path, REPO)}:{node.lineno}  {ast.unparse(node)}")
    return sorted(set(offenders))


def test_no_null_unsafe_get_default_in_the_operational_package():
    """`.get(k, {})` against a stored value that can be null is the #2307 class.

    Five sites existed when this landed — qa_check_outputs.py:148 (the one that
    aborted the nightly), canary_lambda.py:314, pip_audit_lambda.py:288, and
    qa_smoke_lambda.py:300 and :842. All were converted to `or {}` / `or []`.
    Use that form, never a second default argument, on parsed-JSON reads.
    """
    offenders = find_null_unsafe_gets(OPERATIONAL)
    assert not offenders, (
        "`.get(<key>, {}/[])` on parsed JSON defaults only when the key is MISSING — a stored "
        "null returns None and the next access raises (#2307). Write `(x.get(k) or {})`:\n  " + "\n  ".join(offenders)
    )


def test_the_null_coercion_guard_can_actually_fire():
    """Mutation proof for guard #2, both directions: it must see a textbook
    offender, and must NOT fire on the correct form (else it blocks the fix)."""
    with tempfile.TemporaryDirectory() as tmp:
        pathlib.Path(tmp, "mutant.py").write_text(
            "import json\n\n\ndef f(raw):\n    data = json.loads(raw)\n    return data.get('day_grade', {}).get('components')\n",
            encoding="utf-8",
        )
        assert find_null_unsafe_gets(tmp), "the AST guard cannot see a textbook offender — it guards nothing"

    with tempfile.TemporaryDirectory() as tmp:
        pathlib.Path(tmp, "clean.py").write_text(
            "import json\n\n\ndef f(raw):\n    data = json.loads(raw)\n    return (data.get('day_grade') or {}).get('components')\n",
            encoding="utf-8",
        )
        assert not find_null_unsafe_gets(tmp), "the AST guard fires on the CORRECT form — it would block the fix"
