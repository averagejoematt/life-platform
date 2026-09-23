"""tests/test_ci_stand_ins_derive.py — #3528: every git-push caller derives its CI stand-in.

THE CLASS (forensic RCA 2026-09-05, root-cause class 1 — "the ungated landing path"). A
direct push to main met only a formatter, and the two pipelines that DID stand in for CI
before pushing (the reset: 1 of Docs CI's 12 gates; the wrap: 4 of 12) each carried a
hand-listed subset. #3528's amended shape: code direct-pushes are refused; docs pushes and
the reset pass through stand-ins DERIVED from the workflow YAML by ONE function,
`scripts/ci_gate_commands.ci_gate_commands(workflow)`.

THE SET THIS FILE GUARDS is not typed here. `discover_pushers()` walks every file under
`scripts/` and `deploy/` and finds the ones that actually run `git push` (AST for Python —
a `["git", …, "push", …]` argv or a shell string handed to subprocess/os.system; the
command position for shell — never an `echo`ed hint or a comment). Each discovered pusher
must either:
  • IMPORT `ci_gate_commands` (a .py pusher), or
  • INVOKE a python module that does (a .sh pusher — agent_commit.sh → direct_push_gate.py), or
  • be a DECLARED exemption below, with a reason, whose pushes never target main.

A NEGATIVE CONTROL plants a new pusher that hand-types its gate list and asserts the guard
reds naming it — a derivation guard nobody has watched fail is not yet a guard.
"""

from __future__ import annotations

import ast
import os
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "deploy"))

import ci_gate_commands as cgc  # noqa: E402
import direct_push_gate as dpg  # noqa: E402
import restart_verify_gates as rvg  # noqa: E402

SCAN_ROOTS = ("scripts", "deploy")

# Directories whose contents are not live surface. Each with its reason.
EXCLUDED_DIRS = {
    "deploy/archive": "retired one-off release scripts (2026-03), kept for history; no caller, no schedule, no skill names them",
}

# Pushers that deliberately do NOT import ci_gate_commands — each pushes a ref that is
# never main, so there is no CI gate on main for it to stand in for.
PUSHER_EXEMPT = {
    "scripts/archive_handover.py": (
        "pushes ONLY refs/heads/session-archive (the #1650 handover archive branch): prose, no "
        "workflow triggers on that branch, never main"
    ),
    "deploy/merge_train.sh": (
        "force-pushes (leased) a reconciled PR HEAD branch back to that same PR branch — the "
        "push lands IN the premerge lane, which then runs on it; never main"
    ),
}

_SH_PUSH = re.compile(r"(?:^|[;&|(!{]\s*|\b(?:then|do|if|else|elif|until|while)\s+)git(?:\s+-[Cc]\s+\S+)*\s+push\b")
_SH_PY_REF = re.compile(r"\b((?:deploy|scripts)/[\w/.-]+\.py)\b")
_SUBPROCESS_FUNCS = {"run", "call", "check_call", "check_output", "Popen", "system"}


def _is_excluded(rel: str) -> bool:
    return any(rel == d or rel.startswith(d + "/") for d in EXCLUDED_DIRS)


def _py_calls_git_push(src: str) -> bool:
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if isinstance(node, (ast.List, ast.Tuple)):
            consts = [e.value for e in node.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
            if "git" in consts and "push" in consts[consts.index("git") :]:
                return True
        if isinstance(node, ast.Call) and node.args:
            fn = node.func
            name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
            arg = node.args[0]
            if name in _SUBPROCESS_FUNCS and isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                if re.search(r"\bgit\b.*\bpush\b", arg.value):
                    return True
    return False


def _sh_calls_git_push(src: str) -> bool:
    for raw in src.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or re.match(r"(echo|printf)\b", line):
            continue
        if _SH_PUSH.search(line):
            return True
    return False


def _py_imports_ci_gate_commands(src: str) -> bool:
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[-1] == "ci_gate_commands":
            if any(a.name == "ci_gate_commands" for a in node.names):
                return True
        if isinstance(node, ast.Import) and any(a.name.split(".")[-1] == "ci_gate_commands" for a in node.names):
            return True
    return False


def discover_pushers(root: Path) -> list[str]:
    """Every live file under scripts/ + deploy/ that runs `git push` — derived, never listed."""
    out = []
    for scan in SCAN_ROOTS:
        for path in sorted((root / scan).rglob("*")):
            if not path.is_file() or path.suffix not in (".py", ".sh"):
                continue
            rel = path.relative_to(root).as_posix()
            if _is_excluded(rel):
                continue
            src = path.read_text(encoding="utf-8", errors="replace")
            if (_py_calls_git_push if path.suffix == ".py" else _sh_calls_git_push)(src):
                out.append(rel)
    return out


def derives_its_stand_in(root: Path, rel: str) -> bool:
    """A .py pusher imports ci_gate_commands; a .sh pusher invokes a .py that does."""
    src = (root / rel).read_text(encoding="utf-8", errors="replace")
    if rel.endswith(".py"):
        return _py_imports_ci_gate_commands(src)
    for ref in set(_SH_PY_REF.findall(src)):
        target = root / ref
        if target.is_file() and _py_imports_ci_gate_commands(target.read_text(encoding="utf-8", errors="replace")):
            return True
    return False


def undeclared_pushers(root: Path) -> list[str]:
    return [p for p in discover_pushers(root) if p not in PUSHER_EXEMPT and not derives_its_stand_in(root, p)]


# ── the enumeration guard ───────────────────────────────────────────────────────────


def test_the_pusher_census_finds_the_known_pushers():
    """Positive control on the detector itself: the three known live pushers are found.
    A detector that found nothing would make every assertion below vacuous."""
    found = set(discover_pushers(REPO))
    assert {"deploy/agent_commit.sh", "deploy/merge_train.sh", "scripts/archive_handover.py"} <= found, found


def test_every_git_push_caller_imports_ci_gate_commands():
    bad = undeclared_pushers(REPO)
    assert not bad, (
        f"{bad} run `git push` without deriving a CI stand-in from ci_gate_commands(workflow) (#3528). "
        "Import it (a .sh pusher: invoke a python module that does), or — only if the push can never "
        "target main — declare it in PUSHER_EXEMPT with the reason."
    )


def test_agent_commit_derives_through_the_direct_push_gate():
    assert "deploy/agent_commit.sh" in discover_pushers(REPO)
    assert derives_its_stand_in(REPO, "deploy/agent_commit.sh")
    assert _py_imports_ci_gate_commands((REPO / "deploy" / "direct_push_gate.py").read_text(encoding="utf-8"))


def test_every_exemption_is_a_live_pusher_that_never_targets_main():
    found = set(discover_pushers(REPO))
    for rel, reason in PUSHER_EXEMPT.items():
        assert rel in found, f"PUSHER_EXEMPT names {rel}, which no longer runs git push — drop the stale exemption"
        assert reason.strip(), rel
        src = (REPO / rel).read_text(encoding="utf-8")
        assert not re.search(r"refs/heads/main\b|:main\b|origin main\b", src), f"exempt pusher {rel} names main as a push target"


def _plant(tmp_path: Path, rel: str, body: str) -> Path:
    for scan in SCAN_ROOTS:
        (tmp_path / scan).mkdir(parents=True, exist_ok=True)
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return tmp_path


def test_NEGATIVE_CONTROL_a_planted_py_pusher_without_the_import_reds(tmp_path):
    root = _plant(
        tmp_path,
        "scripts/sneaky_push.py",
        "import subprocess\nGATES = [['python3', 'scripts/check_doc_links.py']]  # a hand copy\n"
        "subprocess.run(['git', 'push', 'origin', 'HEAD:main'], check=True)\n",
    )
    assert undeclared_pushers(root) == ["scripts/sneaky_push.py"]


def test_NEGATIVE_CONTROL_a_planted_sh_pusher_without_a_deriving_module_reds(tmp_path):
    root = _plant(tmp_path, "deploy/sneaky_push.sh", "#!/bin/sh\npython3 scripts/check_doc_links.py && git push origin main\n")
    assert undeclared_pushers(root) == ["deploy/sneaky_push.sh"]


def test_the_planted_pushers_go_green_once_they_derive(tmp_path):
    root = _plant(
        tmp_path,
        "scripts/good_push.py",
        "import subprocess\nfrom ci_gate_commands import ci_gate_commands\n"
        "for c in ci_gate_commands('x'):\n    subprocess.run(c)\nsubprocess.run(['git', '-C', '.', 'push'])\n",
    )
    _plant(root, "deploy/good_push.sh", "#!/bin/sh\npython3 scripts/good_push.py\nif git push origin HEAD; then :; fi\n")
    assert set(discover_pushers(root)) == {"scripts/good_push.py", "deploy/good_push.sh"}
    assert undeclared_pushers(root) == []


def test_echoed_hints_and_comments_are_not_pushers(tmp_path):
    root = _plant(
        tmp_path,
        "deploy/hint.sh",
        '#!/bin/sh\n# git push origin main\necho "next: git push -u origin x"\nprintf "git push\\n"\n',
    )
    _plant(root, "scripts/hint.py", "print('run `git push origin main`')\n")
    assert discover_pushers(root) == []


# ── the one derivation ──────────────────────────────────────────────────────────────


def test_every_stand_in_reads_the_same_derivation():
    derived = cgc.ci_gate_commands(cgc.DOCS_CI_WORKFLOW)
    assert rvg.docs_ci_gate_commands() == derived
    readonly, tail = dpg.stand_in_commands(restart=False)
    assert [*readonly, *tail] == [c for c in derived if " ".join(c[1:]) not in rvg.MUTATING_GATES] + [
        c for c in derived if " ".join(c[1:]) in rvg.MUTATING_GATES
    ]
    assert len(derived) >= 12, derived  # the twelve Docs CI ran on 2026-09-05; only ever grows


def test_the_derivation_raises_on_an_empty_or_missing_workflow(tmp_path):
    empty = tmp_path / "wf.yml"
    empty.write_text("name: x\njobs: {}\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="ZERO gates"):
        cgc.ci_gate_commands(empty)
    with pytest.raises(RuntimeError, match="cannot read"):
        cgc.ci_gate_commands(tmp_path / "missing.yml")


def test_a_gate_added_to_a_workflow_is_derived_without_editing_any_stand_in(tmp_path):
    wf = tmp_path / "wf.yml"
    wf.write_text(
        cgc.DOCS_CI_WORKFLOW.read_text(encoding="utf-8") + "\n      - name: new\n        run: python3 scripts/new_gate.py --check\n"
    )
    assert cgc.ci_gate_commands(wf)[-1] == ["python3", "scripts/new_gate.py", "--check"]


# ── the docs class ──────────────────────────────────────────────────────────────────


def test_every_docs_class_glob_is_gated_by_docs_ci_on_push():
    """The docs-only stand-in IS Docs CI's gate set, so every docs-class path must be one
    Docs CI actually runs on for a push to main — otherwise the stand-in stands in for nothing."""
    pytest.importorskip("yaml")
    push_paths = cgc.workflow_push_paths(cgc.DOCS_CI_WORKFLOW)
    assert push_paths, "docs-ci.yml has no push paths filter — the derivation changed shape"
    for glob, reason in dpg.DOCS_CLASS.items():
        assert reason.strip(), glob
        probe = glob.replace("**", "a/b.md").replace("*", "x")
        assert any(cgc.glob_matches(p, probe) for p in push_paths), f"DOCS_CLASS {glob!r} is not in docs-ci.yml's push paths"


@pytest.mark.parametrize(
    "path,cls",
    [
        ("lambdas/x.py", "code"),
        ("tests/test_x.py", "code"),
        ("scripts/check_doc_links.py", "code"),
        ("config/character_sheet.json", "code"),
        ("site/index.html", "code"),
        (".github/workflows/docs-ci.yml", "code"),
        ("handovers/HANDOVER_LATEST.md", "code"),
        ("docs/CONVENTIONS.md", "docs"),
        ("docs/reviews/x.json", "docs"),
        ("CLAUDE.md", "docs"),
        (".claude/skills/wrap/SKILL.md", "docs"),
        ("lambdas/web/platform_counts.py", "docs"),
        ("lambdas/web/site_api_common.py", "code"),
    ],
)
def test_classification(path, cls):
    docs, code = dpg.classify([path])
    assert (docs if cls == "docs" else code) == [path]


# ── the reset stand-in (#3529 leg) ──────────────────────────────────────────────────


def test_the_restart_stand_in_runs_the_derived_artifact_reader_set():
    readonly, _ = dpg.stand_in_commands(restart=True)
    pytest_legs = [c for c in readonly if c[1:3] == ["-m", "pytest"]]
    assert len(pytest_legs) == 1
    files = [a for a in pytest_legs[0] if a.startswith("tests/")]
    assert "tests/test_plan_literal_reconciliation.py" in files
    assert files == rvg.reset_artifact_test_files()


def test_an_empty_artifact_reader_derivation_RAISES_in_the_restart_stand_in(monkeypatch):
    def _empty():
        raise RuntimeError("derived ZERO tests — the detector went blind")

    monkeypatch.setattr(rvg, "pytest_leg_command", _empty)
    with pytest.raises(RuntimeError, match="ZERO"):
        dpg.stand_in_commands(restart=True)
    # and the gate turns that into UNEVALUABLE, never a pass
    monkeypatch.setattr(dpg, "pushed_paths", lambda base, staged: ["lambdas/common/constants.py"])
    monkeypatch.setattr(dpg, "unstaged_paths", lambda: set())
    monkeypatch.setenv("RESTART_PIPELINE", "1")
    assert dpg.main(["--list"]) == 2


def test_the_docs_stand_in_carries_no_pytest_leg():
    readonly, tail = dpg.stand_in_commands(restart=False)
    assert not any(c[1:3] == ["-m", "pytest"] for c in [*readonly, *tail])


# ── box 5: the PR template names the premerge lane ──────────────────────────────────


def test_the_pr_template_names_the_premerge_lane_not_targeted_pytest():
    text = (REPO / ".github" / "pull_request_template.md").read_text(encoding="utf-8")
    assert "Targeted `pytest` for what I touched passes locally" not in text
    assert "premerge" in text and "pr-checks.yml" in text
    assert "agent_commit.sh --push" in text


def test_this_file_is_not_itself_a_pusher():
    assert os.path.relpath(__file__, REPO) not in discover_pushers(REPO)
