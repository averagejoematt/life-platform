"""#3002 — the site-API CloudWatch namespace is ONE spelling, guarded as a SET.

CloudWatch namespaces are case-sensitive, so a casing variant is a whole other
namespace. `lambdas/web/site_api_common.py` wrote the canonical spelling at one
line and a lowercase-i `SiteApi` twin 424 lines apart; both went live (322
series vs 5), every alarm and dashboard read the capital spelling, and
`ContentFilterFallback` — the privacy content filter degrading to its
fail-closed sentinel — was emitted where nothing looked. A real 9-day fallback
episode (2026-03-21 -> 29, 62 datapoints, peak 16/day) passed unwatched.

Guard the SET, not the instance (a grep-and-sweep is how the twin appeared):

  1. the canonical literal lives in exactly one place
     (`lambdas/common/metric_namespaces.py`) and has the alarmed spelling;
  2. `lambdas/web/` may not contain the namespace as a string literal AT ALL —
     emitters must import the constant, so a retyped twin is unexpressible;
  3. every textual occurrence of the namespace (any casing, comments included)
     in the emitting package and the CDK stacks is exactly the canonical
     spelling;
  4. the CDK consumers (serve_stack alarm, dashboard widget) reference the
     canonical spelling — the emitted namespace IS a consumed namespace;
  5. the `ContentFilterFallback` alarm exists in serve_stack.py, reads the
     canonical namespace, and carries the ADR-105 distribution-derived
     threshold (Sum >= 1/day over a zero-inflated metric);
  6. repo-wide, no two `LifePlatform/*` namespace string literals differ only
     by case — the whole defect class, not just this instance.

CDK facts are read by AST (never by importing aws_cdk — it is not installed in
the unit-test lanes and fails at collection; see
`reference_test_importing_aws_cdk_reds_ci`).
"""

import ast
import collections
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CONSTANT_MODULE = os.path.join(ROOT, "lambdas", "common", "metric_namespaces.py")
CONSTANT_NAME = "SITE_API_METRIC_NAMESPACE"
SERVE_STACK = os.path.join(ROOT, "cdk", "stacks", "serve_stack.py")
DASHBOARDS = os.path.join(ROOT, "cdk", "stacks", "monitoring_dashboards.py")

# Directories whose .py files are scanned. cdk/ is entered at stacks/ so the
# walk never touches cdk/node_modules.
SCAN_DIRS = ["lambdas", os.path.join("cdk", "stacks"), "mcp", "scripts", "deploy", "tests"]

_NS_SHAPE = re.compile(r"^LifePlatform/[A-Za-z0-9]+$")


def _canonical() -> str:
    """The one blessed spelling, read from the constant module by AST."""
    tree = ast.parse(open(CONSTANT_MODULE, encoding="utf-8").read())
    for node in ast.walk(tree):
        targets = []
        if isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            targets = [node.target.id]
        if CONSTANT_NAME in targets:
            value = node.value
            assert isinstance(value, ast.Constant) and isinstance(value.value, str)
            return value.value
    raise AssertionError(f"{CONSTANT_NAME} not found in {CONSTANT_MODULE}")


def _py_files(dirs):
    for d in dirs:
        for dirpath, subdirs, files in os.walk(os.path.join(ROOT, d)):
            subdirs[:] = [s for s in subdirs if s not in ("__pycache__", "node_modules", ".git")]
            for f in files:
                if f.endswith(".py"):
                    yield os.path.join(dirpath, f)


def test_canonical_constant_is_the_alarmed_spelling():
    """The constant must carry the spelling the alarms/dashboards consume —
    unify on the consumers' casing, move the emitters (#3002)."""
    assert _canonical() == "LifePlatform/SiteAPI"


def test_web_package_has_no_namespace_string_literal():
    """No file in lambdas/web/ may contain the site-API namespace as a string
    literal in ANY casing — emitters import SITE_API_METRIC_NAMESPACE. This is
    what makes the twin unexpressible rather than merely currently absent."""
    canonical_ci = _canonical().lower()
    offenders = []
    for path in _py_files([os.path.join("lambdas", "web")]):
        tree = ast.parse(open(path, encoding="utf-8").read())
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value.lower() == canonical_ci:
                offenders.append(f"{os.path.relpath(path, ROOT)}:{node.lineno} {node.value!r}")
    assert (
        not offenders
    ), "site-API namespace retyped as a literal in lambdas/web/ — import SITE_API_METRIC_NAMESPACE instead:\n" + "\n".join(offenders)


def test_every_textual_occurrence_is_the_canonical_casing():
    """Text-level (comments and docstrings included): any occurrence of the
    namespace in the emitting package or the CDK stacks, in any casing, must be
    the canonical spelling. A twin in prose is how the next twin gets pasted
    into code. The negative lookahead keeps sibling namespaces (e.g. the AI
    lambda's `...ApiAi`) out of scope."""
    canonical = _canonical()
    pat = re.compile(re.escape(canonical) + r"(?![A-Za-z0-9])", re.IGNORECASE)
    offenders = []
    for path in _py_files([os.path.join("lambdas", "web"), os.path.join("cdk", "stacks")]):
        text = open(path, encoding="utf-8").read()
        for m in pat.finditer(text):
            if m.group(0) != canonical:
                line = text.count("\n", 0, m.start()) + 1
                offenders.append(f"{os.path.relpath(path, ROOT)}:{line} {m.group(0)!r}")
    assert not offenders, f"casing variant of {canonical!r} found:\n" + "\n".join(offenders)


def test_cdk_consumers_reference_the_emitted_namespace():
    """The vice-versa direction: the namespace the Lambdas emit is one the CDK
    consumers actually read. Both known consumers must reference the canonical
    literal (CDK is synth-time and does not import lambda modules, so the
    literal is pinned here instead of imported)."""
    canonical = _canonical()
    for path in (SERVE_STACK, DASHBOARDS):
        tree = ast.parse(open(path, encoding="utf-8").read())
        literals = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
        assert (
            canonical in literals
        ), f"{os.path.relpath(path, ROOT)} no longer references {canonical!r} — consumer drifted from the emitters"


def _alarm_calls(tree):
    """Every cloudwatch.Alarm(...) call in a stack module, as (kwargs dict)."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "Alarm":
            yield {kw.arg: kw.value for kw in node.keywords if kw.arg}


def test_content_filter_fallback_alarm_exists_and_reads_the_canonical_namespace():
    """#3002 acceptance: the fallback signal has an alarm reading the namespace
    it actually writes. Asserted against the CDK declaration by AST — name,
    namespace, metric, and the ADR-105 threshold (Sum >= 1 per day: measured
    distribution is zero-inflated — 62 datapoints over 9 days in 2026-03, then
    0/day for ~5 months — so any datapoint is an incident)."""
    canonical = _canonical()
    tree = ast.parse(open(SERVE_STACK, encoding="utf-8").read())
    matches = []
    for kwargs in _alarm_calls(tree):
        name = kwargs.get("alarm_name")
        if isinstance(name, ast.Constant) and name.value == "site-api-content-filter-fallback":
            matches.append(kwargs)
    assert len(matches) == 1, "expected exactly one site-api-content-filter-fallback Alarm() in serve_stack.py"
    kwargs = matches[0]

    metric_call = kwargs["metric"]
    assert isinstance(metric_call, ast.Call), "alarm metric must be an inline cloudwatch.Metric(...) call"
    mkw = {kw.arg: kw.value for kw in metric_call.keywords if kw.arg}
    assert isinstance(mkw["namespace"], ast.Constant) and mkw["namespace"].value == canonical
    assert isinstance(mkw["metric_name"], ast.Constant) and mkw["metric_name"].value == "ContentFilterFallback"
    assert isinstance(mkw["statistic"], ast.Constant) and mkw["statistic"].value == "Sum"

    threshold = kwargs["threshold"]
    assert isinstance(threshold, ast.Constant) and threshold.value == 1

    # Wired to the digest topic, not declared-and-dropped: the assigned alarm
    # variable must have an add_alarm_action call.
    src = open(SERVE_STACK, encoding="utf-8").read()
    assert "_site_api_content_filter_fallback.add_alarm_action" in src


def test_no_case_twin_namespaces_anywhere():
    """The class, not the instance: across the repo's Python surface, no two
    `LifePlatform/*` namespace string literals may differ only by case. This is
    the check that would have caught the original twin at introduction time,
    whichever pair of files it appeared in."""
    groups = collections.defaultdict(set)
    for path in _py_files(SCAN_DIRS):
        try:
            tree = ast.parse(open(path, encoding="utf-8").read())
        except SyntaxError:
            continue  # non-importable scratch — the syntax gate owns it
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and _NS_SHAPE.match(node.value):
                groups[node.value.lower()].add((node.value, os.path.relpath(path, ROOT)))
    twins = {k: sorted(v) for k, v in groups.items() if len({spelling for spelling, _ in v}) > 1}
    assert not twins, "CloudWatch namespace casing twins (case-sensitive to CloudWatch, invisible to a reader):\n" + "\n".join(
        f"  {k}: {v}" for k, v in sorted(twins.items())
    )
