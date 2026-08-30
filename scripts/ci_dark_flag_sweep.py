#!/usr/bin/env python3
"""scripts/ci_dark_flag_sweep.py — the dark-flag sweep (#3315, #2938's unclaimed box).

THE CLASS: a CI step invokes a script or tool flag whose dependency the job never
installs. `setup-ci` installs NO packages (the #3234 lesson), so every job's installed
set is exactly what its own `pip install` lines declare — and when a script reaches a
third-party import the job did not install, one of three things happens:

  * a module-scope import dies loudly at start (the "dies on import, not on drift" shape
    config-drift.yml documents) — visible, but the step can never do its job;
  * a lazy import inside the flagged code path raises when the flag is exercised — the
    step is green until the day the flag matters (fresh-eyes.yml + Pillow, found here);
  * a try/except around the import swallows it and the step degrades to a wrong verdict
    with a warning line (#2938: visual-qa's `⚠ AI-QA unavailable` + exit 0 for months;
    deploy-wedge-watch's `--head-coverage-check` + PyYAML, found here).

This module pins the class, not the instances. For every job in every workflow it
derives the installed set step by step (ci_pins.py arguments, `pip install -r`, literal
`pip install`, `playwright install <browser>`), follows every python invocation — in
the step's own `run:` block, inside the `bash deploy/*.sh` scripts those steps call, in
`python3 - <<'PY'` heredocs and `python3 -c` one-liners — computes each entry script's
transitive repo-local import closure, and reports every third-party distribution that
closure can reach which the job has not installed by that step. Tool flags with a
plugin dependency (pytest `--cov*` → pytest-cov, `-n` → pytest-xdist, `--timeout` →
pytest-timeout) and the bare gate tools (mypy/black/ruff/flake8/pip-audit/pip-licenses)
are checked the same way.

A job that never ran setup-python runs the runner's SYSTEM interpreter; the sweep models
that as "nothing installed" on purpose — an undeclared system package is the same class
one layer down (it is whatever the runner image happens to ship this month).

A reach that is genuinely unexercised in a given job (the import sits behind a flag the
job does not pass) is recorded in ALLOWED_ABSENT with the reason, keyed by workflow +
job + script + distribution. Every entry must still be LIVE — if the closure no longer
reaches that import, the entry is stale and the sweep fails, so the ledger cannot rot
into a blanket waiver.

Coverage is reported with n (ADR-105): steps total, steps evaluated per class, and the
steps the sweep could NOT evaluate named one by one rather than silently skipped.

Run:   python3 scripts/ci_dark_flag_sweep.py            # exit 1 on a violation or a stale waiver
       python3 scripts/ci_dark_flag_sweep.py --report   # the full per-job table + coverage
Guard: tests/test_ci_dark_flag_sweep_3315.py (runs the sweep + mutation proofs).
"""

from __future__ import annotations

import argparse
import ast
import glob
import os
import re
import shlex
import sys
from dataclasses import dataclass, field

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Import name → distribution name (PEP 503-normalized on comparison). An import the
# sweep cannot map is reported as `?name` and counts as a violation until it is mapped
# here or is a repo-local root the resolver needs to learn.
DIST_FOR_IMPORT = {
    "boto3": "boto3",
    "botocore": "botocore",
    "s3transfer": "boto3",
    "dateutil": "botocore",
    "jmespath": "botocore",
    "urllib3": "botocore",
    "yaml": "pyyaml",
    "PIL": "pillow",
    "playwright": "playwright",
    "hypothesis": "hypothesis",
    "pytest": "pytest",
    "_pytest": "pytest",
    "pytest_cov": "pytest-cov",
    "aws_cdk": "aws-cdk-lib",
    "constructs": "constructs",
    "claude_agent_sdk": "claude-agent-sdk",
    "anthropic": "anthropic",
    "requests": "requests",
    "garth": "garth",
    "garminconnect": "garminconnect",
    "openpyxl": "openpyxl",
    "lameenc": "lameenc",
    "mypy": "mypy",
    "black": "black",
    "ruff": "ruff",
    "flake8": "flake8",
}

# The directories a repo script's `sys.path.insert(...)` can point at. A top-level import
# name that resolves under any of these is repo-local and is followed, not required.
_LOCAL_ROOTS = [".", "scripts", "deploy", "deploy/lib", "tests", "lambdas", "mcp", "remediation", "cdk"]
_LOCAL_ROOTS += sorted(
    os.path.relpath(d, _REPO) for d in glob.glob(os.path.join(_REPO, "lambdas", "*")) if os.path.isdir(d) and not d.endswith("__pycache__")
)

_STDLIB = set(sys.stdlib_module_names) | {"__future__"}

# Commands the ubuntu-latest runner image provides. A step whose external commands are
# all in this set (or shell builtins) is evaluated as "runner-provided"; anything else
# makes the step UNEVALUATED and it is named in the coverage report.
RUNNER_PROVIDED = {
    "aws",
    "gh",
    "jq",
    "curl",
    "node",
    "npm",
    "npx",
    "git",
    "tar",
    "sha256sum",
    "chmod",
    "rm",
    "mkdir",
    "mktemp",
    "cat",
    "head",
    "tail",
    "grep",
    "sed",
    "tr",
    "sort",
    "uniq",
    "wc",
    "date",
    "base64",
    "find",
    "xargs",
    "tee",
    "true",
    "false",
    "sleep",
    "cp",
    "mv",
    "ls",
    "dirname",
    "basename",
    "env",
    "printf",
    "echo",
    "exit",
    "test",
    "python",
    "python3",
    "pip",
    "pip3",
    "bash",
    "sh",
    "source",
}
_SHELL_WORDS = {
    "if",
    "then",
    "else",
    "elif",
    "fi",
    "for",
    "do",
    "done",
    "while",
    "until",
    "case",
    "esac",
    "in",
    "{",
    "}",
    "!",
    "[",
    "[[",
    "set",
    "export",
    "local",
    "return",
    "cd",
    "read",
    "shift",
    "break",
    "continue",
    ":",
    "function",
}
# Tools a step may install in-line and then invoke; when invoked they must be installed.
# (Named so scripts/gate_census.py's registry discovery — `.*_GATES|GATE_.*` — does not read
# a list of lint-tool names as six gates; it did, on this PR's first push.)
_LINT_TOOL_DISTS = ("mypy", "black", "ruff", "flake8", "pip-audit", "pip-licenses")
# A distribution that hard-depends on another: installing the left makes the right
# importable, and a waiver on the left covers the right. (boto3 pins botocore exactly.)
IMPLIES = {"boto3": ("botocore",), "aws-cdk-lib": ("constructs",), "pytest-cov": ("pytest",)}

# (workflow, job, entry script, dist, reason) — reaches that are real in the closure but
# provably unexercised in THAT job. Keep the reason a sentence someone can falsify.
ALLOWED_ABSENT = (
    # ── reconcile / docs-ci / verify: generators that import lambda code to read registries.
    # Neither job holds an AWS role, so an exercised boto3 path would fail on credentials
    # regardless; the reaches below sit in lambda RUNTIME paths a generator never calls.
    (
        "ci-cd.yml",
        "reconcile",
        "deploy/sync_doc_metadata.py",
        "boto3",
        "boto3 is imported only under --refresh-secrets (sync_doc_secret_inventory.refresh_secret_count); --apply never reaches it",
    ),
    (
        "ci-cd.yml",
        "reconcile",
        "deploy/verify_doc_facts_derivable.py",
        "boto3",
        "reached only through sync_doc_secret_inventory.refresh_secret_count, the --refresh-secrets path; the self-check never calls it",
    ),
    (
        "ci-cd.yml",
        "reconcile",
        "scripts/generate_platform_model.py",
        "boto3",
        "reached only inside coach_checkin's DynamoDB write path / retry_utils' botocore error classes — lambda runtime code the "
        "model generator imports for its registries but never executes; the job holds no AWS role and has run green without boto3 since #2986",
    ),
    (
        "ci-cd.yml",
        "reconcile",
        "scripts/v4_build_game_explained.py",
        "boto3",
        "reached only inside privacy.content_filter_channel's S3 config fallback, which the game-explained shell build never calls; "
        "the job holds no AWS role",
    ),
    (
        "docs-ci.yml",
        "wiki-gates",
        "deploy/sync_doc_metadata.py",
        "boto3",
        "boto3 is imported only under --refresh-secrets (sync_doc_secret_inventory.refresh_secret_count); --check never reaches it",
    ),
    (
        "docs-ci.yml",
        "wiki-gates",
        "scripts/generate_platform_model.py",
        "boto3",
        "same reach as ci-cd.yml::reconcile — lambda runtime paths the --check model build never executes; the job holds no AWS role",
    ),
    # ── deterministic QA runs: the AI/deploy-time paths are behind flags they do not pass.
    (
        "webkit-mobile-qa.yml",
        "webkit-mobile-qa",
        "tests/visual_qa.py",
        "boto3",
        "deploy_convergence's CloudWatch emit is reached only with VISUAL_QA_EXPECT_BUILD set (the deploy-time path); "
        "the weekly WebKit sweep is deterministic-only and holds no AWS role for it",
    ),
    (
        "webkit-mobile-qa.yml",
        "webkit-mobile-qa",
        "tests/visual_qa.py",
        "pillow",
        "PIL is reached only through visual_ai_qa under --ai-qa/--reader-truth; the WebKit sweep passes neither ($0 Bedrock by design)",
    ),
    (
        "v4-gate.yml",
        "render-accuracy-gate",
        "tests/pr_render_gate.py",
        "boto3",
        "accuracy_audit's boto3 is its DynamoDB path; the render gate calls impossible_values/sanity_scan against a mocked local API",
    ),
    (
        "v4-gate.yml",
        "render-accuracy-gate",
        "tests/pr_render_gate.py",
        "pillow",
        "PIL is reached only through visual_ai_qa under --ai-qa; the render gate is deterministic",
    ),
    # ── the site smoke job holds no AWS credentials BY DESIGN (deploy_convergence.emit's
    # docstring); the boto3 put is armed only by DEPLOY_RACE_PUT_METRIC=1, which it never sets.
    (
        "site-deploy.yml",
        "smoke",
        "deploy/deploy_convergence.py",
        "boto3",
        "the CloudWatch PutMetricData path is armed only by DEPLOY_RACE_PUT_METRIC=1; the smoke job holds no AWS credentials by design "
        "and the EMF log line is the durable record",
    ),
    # ── the PII gate reaches playwright only through accuracy_audit's optional visual_qa
    # import (screenshot sanity_scan); pii_surface_guard never screenshots.
    (
        "site-deploy.yml",
        "deploy-site",
        "deploy/pii_surface_guard.py",
        "playwright",
        "reached only via capture_api_schemas → accuracy_audit → its lazy `import visual_qa` (screenshot sanity scan), "
        "which the PII surface gate never calls",
    ),
    (
        "site-deploy.yml",
        "rollback-site-on-failure",
        "deploy/pii_surface_guard.py",
        "playwright",
        "same reach as deploy-site — the rollback re-runs the canonical build, which runs the PII gate, which never screenshots",
    ),
)


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _read_pins(path: str) -> set:
    out = set()
    rx = re.compile(r"^([A-Za-z][A-Za-z0-9_.\-]*)==")
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                m = rx.match(line.strip())
                if m:
                    out.add(normalize(m.group(1)))
    except OSError:
        pass
    return out


# ── import closure ────────────────────────────────────────────────────────────────────


def _resolve_local(name: str, repo: str):
    for root in _LOCAL_ROOTS:
        base = os.path.join(repo, root, name)
        if os.path.isfile(base + ".py"):
            return base + ".py"
        if os.path.isdir(base):
            init = os.path.join(base, "__init__.py")
            return init if os.path.isfile(init) else base
    return None


def _resolve_submodule(pkg_dir: str, parts: list):
    p = pkg_dir
    for part in parts:
        f, d = os.path.join(p, part + ".py"), os.path.join(p, part)
        if os.path.isfile(f):
            p = f
        elif os.path.isdir(d):
            p = d
        else:
            return p if p != pkg_dir else None
    return p


class _Imports(ast.NodeVisitor):
    """(dotted, lazy, lineno) for every import; lazy = inside a def/class or a try body."""

    def __init__(self):
        self.items = []
        self._depth = 0
        self._guard = 0

    def _add(self, dotted, node):
        self.items.append((dotted, (self._depth + self._guard) > 0, node.lineno))

    def visit_Import(self, node):
        for a in node.names:
            self._add(a.name, node)

    def visit_ImportFrom(self, node):
        if node.level:
            return
        mod = node.module or ""
        for a in node.names:
            self._add(f"{mod}.{a.name}" if mod else a.name, node)

    def visit_FunctionDef(self, node):
        self._depth += 1
        self.generic_visit(node)
        self._depth -= 1

    visit_AsyncFunctionDef = visit_FunctionDef
    visit_ClassDef = visit_FunctionDef

    def visit_Try(self, node):
        self._guard += 1
        for n in node.body:
            self.visit(n)
        self._guard -= 1
        for n in node.handlers + node.orelse + node.finalbody:
            self.visit(n)

    def visit_If(self, node):
        if "TYPE_CHECKING" in ast.unparse(node.test):
            return
        self.generic_visit(node)


def _parse(source: str, filename: str):
    try:
        return ast.parse(source, filename=filename)
    except (SyntaxError, ValueError):
        return None


def import_closure(entry_path: str, repo: str, source: str | None = None) -> dict:
    """{third_party_top_name: [(relpath, lineno, lazy)]} reachable from `entry_path`.

    `source` overrides the file content (heredoc / -c one-liners). Repo-local imports are
    followed transitively; laziness is inherited down the chain (a lazy import of a local
    module makes everything under it lazy from the entry's point of view).
    """
    seen, third = set(), {}
    stack = [(entry_path, False, source)]
    while stack:
        path, inherited_lazy, src = stack.pop()
        if (path, inherited_lazy) in seen:
            continue
        seen.add((path, inherited_lazy))
        if src is None:
            try:
                with open(path, encoding="utf-8") as fh:
                    src = fh.read()
            except (OSError, UnicodeDecodeError):
                continue
        tree = _parse(src, path)
        if tree is None:
            continue
        col = _Imports()
        col.visit(tree)
        for dotted, lazy, lineno in col.items:
            lazy = lazy or inherited_lazy
            top = dotted.split(".")[0]
            if top in _STDLIB:
                continue
            local = _resolve_local(top, repo)
            if local is None:
                third.setdefault(top, []).append((os.path.relpath(path, repo) if os.path.isabs(path) else path, lineno, lazy))
                continue
            targets = []
            if local.endswith(".py") and not local.endswith("__init__.py"):
                targets.append(local)
            else:
                pkg_dir = os.path.dirname(local) if local.endswith("__init__.py") else local
                parts = dotted.split(".")[1:]
                sub = _resolve_submodule(pkg_dir, parts) if parts else None
                if sub:
                    if os.path.isdir(sub):
                        init = os.path.join(sub, "__init__.py")
                        if os.path.isfile(init):
                            targets.append(init)
                    else:
                        targets.append(sub)
                if local.endswith("__init__.py"):
                    targets.append(local)
            for t in targets:
                stack.append((t, lazy, None))
    return third


def entry_imports_playwright(entry_path: str, repo: str, source: str | None = None) -> bool:
    """Does the entry script ITSELF import playwright (i.e. it drives a browser)?"""
    if source is None:
        try:
            with open(entry_path, encoding="utf-8") as fh:
                source = fh.read()
        except OSError:
            return False
    tree = _parse(source, entry_path)
    if tree is None:
        return False
    col = _Imports()
    col.visit(tree)
    return any(d.split(".")[0] == "playwright" for d, _, _ in col.items)


# ── shell text → python invocations ───────────────────────────────────────────────────

_DIR_TOKENS = [
    r'\$\(cd\s+"?\$\(dirname\s+"?\$\{?0\}?"?\)"?\s*&&\s*pwd\)',
    r'\$\(dirname\s+"?\$\{?0\}?"?\)',
    r"\$\{?(?:SCRIPT_DIR|HERE|ROOT|REPO_ROOT|REPO|GITHUB_WORKSPACE|BASE_DIR)\}?",
]
_PY_CALL_RE = re.compile(
    r"""(?:^|[\s;&|(`])python3?\s+(?P<opts>(?:-[a-zA-Z]+\s+)*)(?P<target>"[^"\n]+"|'[^'\n]+'|[^\s"'|;&<>()`]+)""", re.M
)
_SH_CALL_RE = re.compile(
    r"""(?:^|[\s;&|(`])(?:(?:bash|sh|source|exec)\s+)?(?P<path>"[^"\n]*\.sh"|[^\s"'|;&<>()`]*\.sh)(?=[\s;&|)]|$)""", re.M
)
_VAR_PY_RE = re.compile(r"""^\s*(?P<var>[A-Z_][A-Z0-9_]*)=(?P<val>"[^"\n]*\.py"|'[^'\n]*\.py'|[^\s"']*\.py)\s*(?:#.*)?$""", re.M)
_HEREDOC_RE = re.compile(r"""python3?\s+-\s*<<-?\s*['"]?(?P<tag>[A-Za-z_]+)['"]?\s*\n(?P<body>.*?)\n\s*(?P=tag)\s*$""", re.S | re.M)
_INLINE_C_RE = re.compile(r"""python3?\s+-c\s+(?P<code>"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')""", re.S)
_FAIL_OPEN_RE = re.compile(r"\|\|\s*(?:echo|true|:)\b")


def _strip_comments(text: str) -> str:
    out = []
    for line in text.splitlines():
        s = line.lstrip()
        out.append("" if s.startswith("#") else line)
    return "\n".join(out)


def _normalize_dirs(text: str) -> str:
    for rx in _DIR_TOKENS:
        text = re.sub(rx, "@DIR@", text)
    return text


def _resolve_py(raw: str, repo: str, caller_dir: str | None, cd_dir: str | None):
    p = raw.strip("\"'")
    if "@DIR@" in p:
        p = p.rsplit("@DIR@/", 1)[-1]
    p = re.sub(r"^(?:\./)+", "", p)
    while p.startswith("../"):
        p = p[3:]
    if p.startswith("$") or not p.endswith(".py"):
        return None
    bases = [b for b in (cd_dir, caller_dir) if b] + ["", "deploy", "deploy/lib", "scripts", "tests"]
    for b in bases:
        cand = os.path.normpath(os.path.join(repo, b, p))
        if os.path.isfile(cand):
            return os.path.relpath(cand, repo)
    hits = [
        os.path.relpath(h, repo)
        for root in ("scripts", "deploy", "deploy/lib", "tests")
        for h in glob.glob(os.path.join(repo, root, os.path.basename(p)))
    ]
    return hits[0] if len(hits) == 1 else "UNRESOLVED:" + p


def _resolve_sh(raw: str, repo: str, caller_dir: str | None):
    p = raw.strip("\"'")
    if "@DIR@" in p:
        p = p.rsplit("@DIR@/", 1)[-1]
    p = re.sub(r"^(?:\./)+", "", p)
    while p.startswith("../"):
        p = p[3:]
    if p.startswith("$") or not p.endswith(".sh") or "://" in p or "*" in p or "::" in p:
        return None  # a URL, a glob in a log line, or a `::group::` title — not a script call
    for b in ([caller_dir] if caller_dir else []) + ["", "deploy", "deploy/lib"]:
        cand = os.path.normpath(os.path.join(repo, b, p))
        if os.path.isfile(cand) and "/archive/" not in cand:
            return os.path.relpath(cand, repo)
    hits = [h for h in glob.glob(os.path.join(repo, "deploy", "**", os.path.basename(p)), recursive=True) if "/archive/" not in h]
    return os.path.relpath(hits[0], repo) if len(hits) == 1 else "UNRESOLVED:" + p


_WRAPPER_WORDS = frozenset({"bash", "sh", "source", "exec", "time", "nice", "env"})
_ASSIGNMENT_WORD_RE = re.compile(r"[A-Za-z_]\w*=")  # `VAR=value` (value already shlex-joined into the word)
_BOUNDARY_TAIL_RE = re.compile(r"(?:;|&&|\|\||\||\(|`|\bthen|\bdo|\belse|\bif|\bwhile|\buntil|!)$")


def _at_command_position(text: str, start: int) -> bool:
    """Is the token at `start` a command, not a word inside an echo/heredoc string or a
    `$(...)` mention? The prefix of its line must close every quote it opens and, after
    peeling any trailing `VAR=value` assignments and a `bash|sh|source|exec` wrapper word,
    end at a command boundary (line start, `;`, `&&`, `||`, `|`, `(`, `then`/`do`/`else`,
    `!`, `if`/`while`). Procedural on purpose — the first version was one regex whose
    assignment group backtracked exponentially (CodeQL py/redos on this PR)."""
    line_start = text.rfind("\n", 0, start) + 1
    prefix = text[line_start:start]
    if prefix.count('"') % 2 or prefix.count("'") % 2:
        return False
    stripped = prefix.rstrip()
    if not stripped:
        return True
    try:
        words = shlex.split(stripped, posix=True)
    except ValueError:
        words = stripped.split()
    while words and (words[-1] in _WRAPPER_WORDS or _ASSIGNMENT_WORD_RE.match(words[-1])):
        words.pop()
    rest = " ".join(words)
    return rest == "" or bool(_BOUNDARY_TAIL_RE.search(rest))


@dataclass
class Invocation:
    script: str  # repo-relative path, or "UNRESOLVED:…", or "<heredoc>"/"<-c>"
    flags: str
    via: str  # chain of shell scripts, "" when direct
    fail_open: bool
    source: str | None = None  # inline python source for heredoc / -c


def python_invocations(text: str, repo: str, via: str = "", depth: int = 0, caller_dir: str | None = None) -> list:
    """Every python entry point `text` (a run: block or a shell script) reaches, following bash scripts ≤ 3 deep."""
    text = _strip_comments(text)
    out = []
    for m in _HEREDOC_RE.finditer(text):
        out.append(Invocation("<heredoc>", "", via, False, source=m.group("body")))
    for m in _INLINE_C_RE.finditer(text):
        code = m.group("code")[1:-1]
        out.append(Invocation("<-c>", "", via, bool(_FAIL_OPEN_RE.search(text[m.end() : m.end() + 40])), source=code))
    norm = _normalize_dirs(text)
    variables = {m.group("var"): m.group("val") for m in _VAR_PY_RE.finditer(norm)}
    cd_m = re.search(r"^\s*cd\s+([^\s;&|]+)", norm, re.M)
    cd_dir = cd_m.group(1) if cd_m and not cd_m.group(1).startswith("$") else None
    for m in _PY_CALL_RE.finditer(norm):
        target = m.group("target")
        opts = m.group("opts") or ""
        if "-m" in opts.split() or "-c" in opts.split() or target.strip("\"'") == "-":
            continue
        if not _at_command_position(norm, m.start() + (1 if m.group(0)[0] != "p" else 0)):
            continue  # `echo "… run python3 x.py …"` is documentation, not an invocation
        bare = target.strip("\"'")
        var = re.fullmatch(r"\$\{?([A-Z_][A-Z0-9_]*)\}?", bare)
        if var and var.group(1) in variables:
            bare = variables[var.group(1)]
        resolved = _resolve_py(bare, repo, caller_dir, cd_dir)
        if resolved is None:
            continue
        line_end = norm.find("\n", m.end())
        rest = norm[m.end() : line_end if line_end != -1 else len(norm)]
        out.append(Invocation(resolved, rest.strip(), via, bool(_FAIL_OPEN_RE.search(rest))))
    if depth < 3:
        for m in _SH_CALL_RE.finditer(norm):
            first_char_offset = 1 if m.group(0)[:1] in " \t;&|(`\n" else 0
            if not _at_command_position(norm, m.start() + first_char_offset):
                continue  # `echo "… bash deploy/rollback_site.sh HEAD~1"` is a runbook line
            resolved = _resolve_sh(m.group("path"), repo, caller_dir)
            if resolved is None:
                continue
            if resolved.startswith("UNRESOLVED:"):
                out.append(Invocation(resolved.replace("UNRESOLVED:", "UNRESOLVED-SH:"), "", via, False))
                continue
            try:
                with open(os.path.join(repo, resolved), encoding="utf-8") as fh:
                    sub = fh.read()
            except OSError:
                continue
            chain = f"{via} > {resolved}" if via else resolved
            out.extend(python_invocations(sub, repo, chain, depth + 1, caller_dir=os.path.dirname(resolved)))
    return out


# ── installed set per step ────────────────────────────────────────────────────────────

_CI_PINS_RE = re.compile(r"scripts/ci_pins\.py\s+(?P<names>[^)\n#]+)")
_PIP_R_RE = re.compile(r"pip3?\s+install\s+(?:(?:-q|--quiet|--upgrade|-U)\s+)*-r\s+\"?(?P<file>[^\s\"]+)")
_PIP_LIT_RE = re.compile(r"pip3?\s+install\s+(?P<args>[^\n|&;]+)")
_PW_RE = re.compile(r"playwright\s+install\s+(?:--with-deps\s+)?(?P<browsers>[a-z ]+)")
_FOR_REQ_RE = re.compile(r"for\s+(?P<var>\w+)\s+in\s+(?P<items>[^;\n]+)")


def apply_installs(run_text: str, installed: set, repo: str) -> None:
    """Mutate `installed` with what this run: block installs (order-independent within a step)."""
    text = _strip_comments(run_text)
    for m in _CI_PINS_RE.finditer(text):
        for n in m.group("names").split():
            if not n.startswith(("$", "-")):
                installed.add(normalize(n))
    loops = {m.group("var"): m.group("items").split() for m in _FOR_REQ_RE.finditer(text)}
    cd_m = re.search(r"^\s*cd\s+([^\s;&|]+)", text, re.M)
    for m in _PIP_R_RE.finditer(text):
        f = m.group("file")
        var = re.fullmatch(r"\$\{?(\w+)\}?", f)
        files = loops.get(var.group(1), []) if var else [f]
        for f2 in files:
            cands = [os.path.join(repo, f2)]
            if cd_m:
                cands.insert(0, os.path.join(repo, cd_m.group(1), f2))
            for c in cands:
                if os.path.isfile(c):
                    installed |= _read_pins(c)
                    break
    for m in _PIP_LIT_RE.finditer(text):
        args = m.group("args").split()
        if "-r" in args:
            continue
        for a in args:
            if a.startswith(("-", "$")) or a == "pip":
                continue
            installed.add(normalize(re.split(r"[=<>!\[]", a)[0]))
    for m in _PW_RE.finditer(text):
        for b in m.group("browsers").split():
            if b in ("chromium", "webkit", "firefox"):
                installed.add("playwright-browser:" + b)
    for left, rights in IMPLIES.items():
        if left in installed:
            installed.update(rights)


def tool_requirements(run_text: str) -> list:
    """[(what, dist)] for tool/flag invocations in a run: block that need an installed dist."""
    text = _strip_comments(run_text)
    reqs = []
    if re.search(r"(?:^|[\s;(])(?:python3?\s+-m\s+)?pytest\b", text, re.M):
        reqs.append(("pytest", "pytest"))
        if re.search(r"--cov(?:[=\s-]|$)", text):
            reqs.append(("pytest --cov*", "pytest-cov"))
        if re.search(r"(?:^|\s)-n\s*\d|--numprocesses", text):
            reqs.append(("pytest -n", "pytest-xdist"))
        if re.search(r"--timeout[= ]", text):
            reqs.append(("pytest --timeout", "pytest-timeout"))
        for m in re.finditer(r"(?:^|\s)-p\s+(?!no:)([A-Za-z_][\w.]*)", text):
            reqs.append((f"pytest -p {m.group(1)}", "?" + m.group(1)))
    for tool in _LINT_TOOL_DISTS:
        if re.search(rf"(?:^|[\s;(])(?:python3?\s+-m\s+)?{re.escape(tool)}(?=\s|$)", text, re.M):
            reqs.append((tool, tool))
    return reqs


# ── evaluation ────────────────────────────────────────────────────────────────────────


@dataclass
class ScriptResult:
    script: str
    flags: str
    via: str
    fail_open: bool
    needs: dict = field(default_factory=dict)  # dist -> [(import, file, line, lazy)]
    missing: dict = field(default_factory=dict)  # subset of needs the job lacks
    allowed: dict = field(default_factory=dict)  # subset of missing covered by ALLOWED_ABSENT (dist -> reason)


@dataclass
class StepResult:
    workflow: str
    job: str
    index: int
    name: str
    kind: str  # action | python | runner-provided | shell-noop | unevaluated
    runtime: str  # setup | system | n/a
    installed: tuple
    detail: str = ""
    tools: list = field(default_factory=list)  # [(what, dist, ok)]
    scripts: list = field(default_factory=list)
    unresolved: list = field(default_factory=list)


_STRINGS_RE = re.compile(r'"(?:[^"\\]|\\.)*"|\'[^\']*\'', re.S)
_ARITH_RE = re.compile(r"\$\(\([^)]*\)\)")
_HEREDOC_BODY_RE = re.compile(r"<<-?\s*['\"]?(\w+)['\"]?\s*\n.*?\n\s*\1\s*$", re.S | re.M)
_CASE_ARM_RE = re.compile(r"^(?:[^\s()|]+\|)*[^\s()|]+\)(?:\s|$)")
# A binary the job builds for itself in an earlier step (`chmod +x gitleaks` after a
# checksum-verified download) — invoked as `./gitleaks`, it is installed, not runner-provided.
_BUILT_TOOL_RE = re.compile(r"chmod\s+\+x\s+(?:\./)?([\w.-]+)")


def _command_token_ok(tok: str) -> bool:
    tok = tok.lstrip("!(")
    if not tok or "=" in tok or tok[0].isdigit():
        return False
    if tok.startswith(("$", '"', "'", "[", "{", "}", ")", "*", "<", ">", "-")) or tok.endswith(")"):
        return False
    return True


def _external_commands(run_text: str) -> set:
    """Best-effort first-word extraction — every miss lands in the NOT EVALUATED list, never in a pass."""
    text = _strip_comments(run_text).replace("\\\n", " ")  # join backslash-continued lines
    text = _HEREDOC_BODY_RE.sub("", text)
    text = _ARITH_RE.sub("0", text)
    text = _STRINGS_RE.sub('""', text)
    cmds = set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", "-", "|", "&&", "||", ")", "}", "fi", "done", "esac", "then", "else", "do")):
            continue
        if _CASE_ARM_RE.match(line):
            continue  # `full|standard|lean|off)` / `*)` — a case pattern, not commands
        for seg in re.split(r"\|\||&&|\||;|\$\(|`|\(\s*$", line):
            seg = seg.strip()
            if not seg:
                continue
            words = seg.split()
            tok = words[0]
            if tok.lstrip("!(") in _SHELL_WORDS:
                if tok.lstrip("!(") in ("if", "while", "until", "elif", "!") and len(words) > 1 and _command_token_ok(words[1]):
                    if words[1].lstrip("!(") not in _SHELL_WORDS:
                        cmds.add(words[1].lstrip("!("))
                continue
            if _command_token_ok(tok):
                cmds.add(tok.lstrip("!("))
    return cmds


def _workflow_docs(wf_dir: str):
    import yaml  # local: the sweep's only third-party dependency

    for path in sorted(glob.glob(os.path.join(wf_dir, "*.yml"))):
        with open(path, encoding="utf-8") as fh:
            yield os.path.basename(path), yaml.safe_load(fh) or {}


def evaluate_job(workflow: str, job_id: str, job: dict, repo: str, allowed=ALLOWED_ABSENT) -> list:
    """StepResult per step of one job, tracking the installed set as steps run."""
    results = []
    installed: set = set()
    built_tools: set = set()
    runtime = "system"
    allowed_here = {(s, normalize(d)): r for wf, j, s, d, r in allowed if wf == workflow and j == job_id}
    for i, st in enumerate(job.get("steps") or []):
        uses = st.get("uses") or ""
        run = st.get("run") or ""
        name = st.get("name") or (uses.split("@")[0] if uses else f"step {i}")
        with_ = st.get("with") or {}
        if uses:
            if "setup-python" in uses or ("setup-ci" in uses and str(with_.get("python", "true")).lower() != "false"):
                runtime = "setup"
            results.append(StepResult(workflow, job_id, i, name, "action", "n/a", tuple(sorted(installed)), detail=uses))
            continue
        apply_installs(run, installed, repo)
        for m in _BUILT_TOOL_RE.finditer(_strip_comments(run)):
            built_tools.update({m.group(1), "./" + m.group(1)})
        step_fail_open = bool(st.get("continue-on-error"))
        invs = python_invocations(run, repo)
        tools = [
            (what, dist, normalize(dist.lstrip("?")) in installed and not dist.startswith("?")) for what, dist in tool_requirements(run)
        ]
        if not invs and not tools:
            cmds = _external_commands(run)
            unknown = sorted(c for c in cmds if c not in RUNNER_PROVIDED and c not in _SHELL_WORDS and c not in built_tools)
            kind = "unevaluated" if unknown else ("runner-provided" if cmds else "shell-noop")
            results.append(
                StepResult(workflow, job_id, i, name, kind, runtime, tuple(sorted(installed)), detail=", ".join(unknown or sorted(cmds)))
            )
            continue
        res = StepResult(workflow, job_id, i, name, "python", runtime, tuple(sorted(installed)), tools=tools)
        for inv in invs:
            if inv.script.startswith("UNRESOLVED"):
                res.unresolved.append(f"{inv.script} (via {inv.via or 'step'})")
                continue
            entry = os.path.join(repo, inv.script) if inv.source is None else inv.script
            third = import_closure(entry, repo, source=inv.source)
            sr = ScriptResult(inv.script, inv.flags, inv.via, inv.fail_open or step_fail_open)
            for top, sites in third.items():
                dist = DIST_FOR_IMPORT.get(top, "?" + top)
                sr.needs.setdefault(dist, []).extend((top, f, ln, lazy) for f, ln, lazy in sites)
            if entry_imports_playwright(entry, repo, source=inv.source):
                b = re.search(r"--browser\s+(\w+)", inv.flags)
                sr.needs.setdefault("playwright-browser:" + (b.group(1) if b else "chromium"), []).append(
                    ("playwright", inv.script, 0, True)
                )
            for dist, sites in sr.needs.items():
                key = dist if dist.startswith("playwright-browser:") else normalize(dist.lstrip("?"))
                if dist.startswith("?") or key not in installed:
                    sr.missing[dist] = sites
                    reason = allowed_here.get((inv.script, key))
                    if reason is None:  # a waiver on boto3 covers botocore (IMPLIES) — one reason, not two copies
                        for left, rights in IMPLIES.items():
                            if key in rights and (inv.script, left) in allowed_here:
                                reason = allowed_here[(inv.script, left)]
                    if reason:
                        sr.allowed[dist] = reason
            res.scripts.append(sr)
        results.append(res)
    return results


def evaluate_repo(repo: str = _REPO, allowed=ALLOWED_ABSENT, wf_dir: str | None = None) -> list:
    out = []
    for wf_name, doc in _workflow_docs(wf_dir or os.path.join(repo, ".github", "workflows")):
        for job_id, job in (doc.get("jobs") or {}).items():
            if not job.get("steps"):
                continue
            out.extend(evaluate_job(wf_name, job_id, job, repo, allowed))
    return out


def violations(results: list) -> list:
    """Human-readable violation lines: a missing dist not covered by ALLOWED_ABSENT, an unmet tool, an unresolved script."""
    out = []
    seen = set()  # one line per (job, script, dist) — the report lists every step; the verdict names each reach once
    for r in results:
        where = f"{r.workflow}::{r.job}::step {r.index} {r.name!r}"
        for what, dist, ok in r.tools:
            if not ok and (r.workflow, r.job, what, dist) not in seen:
                seen.add((r.workflow, r.job, what, dist))
                out.append(f"{where}: `{what}` needs {dist} — not installed in this job by this step (runtime={r.runtime})")
        for s in r.scripts:
            for dist, sites in s.missing.items():
                if dist in s.allowed or (r.workflow, r.job, s.script, dist) in seen:
                    continue
                seen.add((r.workflow, r.job, s.script, dist))
                site = sites[0]
                kind = "lazy/guarded" if all(x[3] for x in sites) else "module-scope"
                via = f" via {s.via}" if s.via else ""
                fo = " [FAIL-OPEN: `|| echo`/continue-on-error hides it]" if s.fail_open else ""
                out.append(
                    f"{where}: {s.script}{via} reaches `import {site[0]}` ({dist}, {kind}, {site[1]}:{site[2]}) — "
                    f"not installed in this job by this step (runtime={r.runtime}){fo}"
                )
        for u in r.unresolved:
            out.append(f"{where}: could not resolve invoked script {u}")
    return out


def stale_waivers(results: list, allowed=ALLOWED_ABSENT) -> list:
    """ALLOWED_ABSENT entries whose reach no longer exists (or whose dist is now installed) — the ledger must not rot."""
    live = set()
    for r in results:
        for s in r.scripts:
            for dist in s.missing:
                live.add((r.workflow, r.job, s.script, normalize(dist.lstrip("?"))))
    return [f"{wf}::{j}::{s}::{d} — {reason}" for wf, j, s, d, reason in allowed if (wf, j, s, normalize(d)) not in live]


def coverage(results: list) -> dict:
    by_kind: dict = {}
    for r in results:
        by_kind[r.kind] = by_kind.get(r.kind, 0) + 1
    return {
        "steps_total": len(results),
        "by_kind": by_kind,
        "unevaluated": [
            f"{r.workflow}::{r.job}::step {r.index} {r.name!r} — unknown command(s): {r.detail}" for r in results if r.kind == "unevaluated"
        ],
        "unresolved_scripts": [u for r in results for u in r.unresolved],
        "scripts_evaluated": sum(len(r.scripts) for r in results),
        "jobs": len({(r.workflow, r.job) for r in results}),
    }


def render_report(results: list, allowed=ALLOWED_ABSENT) -> str:
    lines = []
    cur = None
    for r in results:
        if (r.workflow, r.job) != cur:
            cur = (r.workflow, r.job)
            lines.append("=" * 96)
            lines.append(f"{r.workflow} :: {r.job}")
        if r.kind != "python":
            lines.append(f"  step {r.index:<2} [{r.kind:<15}] {r.name[:70]}" + (f"  ({r.detail})" if r.kind == "unevaluated" else ""))
            continue
        lines.append(f"  step {r.index:<2} [python/{r.runtime:<6}] {r.name[:70]}")
        lines.append(f"           installed: {', '.join(r.installed) or '(nothing)'}")
        for what, dist, ok in r.tools:
            lines.append(f"           tool {what} → {dist}: {'ok' if ok else 'MISSING'}")
        for s in r.scripts:
            via = f" (via {s.via})" if s.via else ""
            fo = " [fail-open]" if s.fail_open else ""
            lines.append(f"           {s.script} {s.flags[:50]!r}{via}{fo}")
            if not s.needs:
                lines.append("             needs: nothing third-party")
            for dist in sorted(s.needs):
                if dist in s.allowed:
                    lines.append(f"             {dist}: absent, WAIVED — {s.allowed[dist]}")
                elif dist in s.missing:
                    site = s.missing[dist][0]
                    lines.append(f"             {dist}: MISSING ({site[1]}:{site[2]}, {'lazy' if site[3] else 'module-scope'})")
                else:
                    lines.append(f"             {dist}: ok")
        for u in r.unresolved:
            lines.append(f"           UNRESOLVED {u}")
    cov = coverage(results)
    lines.append("=" * 96)
    lines.append(
        f"coverage: {cov['jobs']} jobs, {cov['steps_total']} steps — "
        + ", ".join(f"{k}={v}" for k, v in sorted(cov["by_kind"].items()))
        + f"; scripts evaluated={cov['scripts_evaluated']}; waivers={len(allowed)}"
    )
    for u in cov["unevaluated"]:
        lines.append(f"  NOT EVALUATED: {u}")
    for u in cov["unresolved_scripts"]:
        lines.append(f"  UNRESOLVED: {u}")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--report", action="store_true", help="print the full per-job table + coverage, not just verdicts")
    ap.add_argument("--repo", default=_REPO, help=argparse.SUPPRESS)
    ap.add_argument(
        "--workflows-dir",
        default=None,
        help="sweep these workflow files against the current tree instead of .github/workflows/ (mutation proofs: point it at copies of an older revision)",
    )
    args = ap.parse_args(argv)
    results = evaluate_repo(args.repo, wf_dir=args.workflows_dir)
    if args.report:
        print(render_report(results))
        print()
    bad = violations(results)
    stale = stale_waivers(results)
    cov = coverage(results)
    for v in bad:
        print(f"VIOLATION: {v}")
    for s in stale:
        print(f"STALE WAIVER: {s}")
    for u in cov["unevaluated"]:
        print(f"NOT EVALUATED: {u}")
    print(
        f"ci_dark_flag_sweep: {cov['jobs']} jobs / {cov['steps_total']} steps / {cov['scripts_evaluated']} script invocations — "
        f"{len(bad)} violation(s), {len(stale)} stale waiver(s), {len(cov['unevaluated'])} step(s) not evaluated"
    )
    return 1 if (bad or stale) else 0


if __name__ == "__main__":
    sys.exit(main())
