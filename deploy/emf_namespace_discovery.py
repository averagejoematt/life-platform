"""deploy/emf_namespace_discovery.py — who WRITES and who READS each custom metric namespace (#2837).

The custom-metric estate had no inventory: 743 series across 35 namespaces
(elite review 2026-08-16) added ad hoc by ~16 emitting modules, so sprawl was
visible only when the CloudWatch bill landed — ``USW2-CW:MetricMonitorUsage``
went $4.41 (Jun) -> $16.46 (Jul), overtaking AlarmMonitorUsage. This module is
the derivation half of the fix: it answers "which namespaces does this repo
emit, from where, and does anything actually consume them" **structurally**, by
AST, so the ledger in ``deploy/emf_namespace_ledger.py`` cannot quietly drift
from the code.

Producers come in three shapes and the inventory is wrong if any is missed:

  * ``put_metric_data(Namespace=...)`` — the direct boto3 emit;
  * an EMF blob — a dict literal carrying **both** a ``"Namespace"`` and a
    ``"Metrics"`` key, i.e. one ``_aws.CloudWatchMetrics`` entry;
  * ``logs.MetricFilter(..., metric_namespace=...)`` — a namespace minted in
    **CDK**, from log text, with no Python emitter anywhere.
    ``LifePlatform/Lambda`` and ``LifePlatform/Privacy`` exist only this way; a
    Python-only sweep reports them as alarms watching a namespace nothing
    writes, which is precisely backwards.

Each discriminator exists because the loose form is wrong in a different
direction. A bare ``grep '"LifePlatform'`` reports the
``User-Agent: LifePlatform/1.0`` header (``notion_lambda.py``) as a namespace.
A bare ``Namespace=`` kwarg scan promotes ``get_metric_statistics`` **readers**
into emitters. A bare ``"Namespace"`` dict-key scan does the same to the
``{"Metric": {"Namespace": ..., "MetricName": ...}}`` query dicts that
``traffic_digest_lambda`` and ``site_api_budget`` build.

``discover_readers()`` — modules that READ a namespace they do not emit. A
module-level ``*NAMESPACE* = "LifePlatform/..."`` binding, or a
namespace-valued call argument, in a module that emits nothing there, exists
for one reason: to query it. This sweep is why the ledger can record
``LifePlatform/QaSmoke`` as consumed even though no alarm reads it — the daily
traffic digest does (``traffic_digest_lambda.py:497``). Without it, genuinely
consumed namespaces would be listed as retirement candidates.

``discover_cdk_consumers()`` — CDK constructs that name a namespace, read by
AST and never by importing ``aws_cdk`` (not installed in the unit lanes; see
``reference_cdk_synth_python_resolution``). Any namespace-valued call argument
in ``cdk/stacks/*.py`` counts: the alarm helpers spell it four different ways
(``namespace=``, a positional third argument, a module ``_NAMESPACE``
constant, a kwargs-spread) and pattern-matching the spellings goes blind the
day a fifth appears. Docstrings that mention a namespace do not count — they
are bare ``Expr`` constants, not call arguments. A ``MetricFilter``-minted
namespace is alarm-consumed when the filter's own variable feeds an ``Alarm``
in the same stack (``db_mf.metric(...)``), which is the only way those four
namespaces reach an alarm at all.

Name resolution follows module-level bindings, function-parameter defaults
(``timeout_watchdog.arm(..., namespace=_NAMESPACE)`` emits through one), and
``lambdas/common/metric_namespaces.py``: #3002 forbids ``lambdas/web/`` from
containing the site-API namespace as a literal at all — that guard exists
because a retyped ``SiteApi`` twin went live unwatched — so the only way to see
``LifePlatform/SiteAPI`` from ``site_api_common.py`` is to follow the import. A
literal-only scan reports the repo's largest namespace as unemitted.

Nothing here touches AWS. The live half — how many *series* each namespace
carries, which is what CloudWatch bills for — is
``deploy/emf_series_census.py``, which needs credentials and skips loudly
without them.
"""

import ast
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Trees that may emit or read custom metrics. `tests/` is in the sweep because
# `tests/golden_brief_eval.py` is a scheduled CI harness that emits to
# PRODUCTION CloudWatch (`LifePlatform/GoldenBrief`, 5 live series) — excluding
# it hid a real billed namespace. The strict producer discriminators keep
# ordinary regression tests out: asserting about a namespace is not calling
# `put_metric_data`.
PRODUCER_ROOTS = ("lambdas", "mcp", "scripts", "deploy", "web", "tests")

# `tests/` is swept for PRODUCERS but never for READERS. A test asserting about a
# namespace is not a consumer of its data, and counting it as one lets a namespace
# justify its own `keep` verdict with its own regression test — which is how a
# registry stops meaning anything. Caught on this module's first full table: THIS
# discovery's guard file was being reported as the sole "reader" of
# LifePlatform/SiteAPI, whose real consumers are an alarm and a dashboard.
READER_ROOTS = tuple(r for r in PRODUCER_ROOTS if r != "tests")

# deploy/archive/onetime/ holds frozen copies of retired handlers (they still
# contain EMF blobs); they ship nothing.
_EXCLUDED_DIR_PARTS = (
    os.path.join("deploy", "archive"),
    os.path.join("cdk", "cdk.out"),
    "node_modules",
    ".git",
)

CDK_STACKS_DIR = ROOT / "cdk" / "stacks"
DASHBOARD_STACK = "monitoring_dashboards.py"

# The shared constants module whose exported literals other modules import
# rather than retype (#3002). It defines namespaces; it neither emits nor reads.
NAMESPACE_CONSTANTS_MODULE = ROOT / "lambdas" / "common" / "metric_namespaces.py"

# A namespace this repo owns. `AWS/*` is Amazon's, free, and out of scope.
OWN_NAMESPACE_RE = re.compile(r"^LifePlatform(/[A-Za-z0-9][A-Za-z0-9._-]*)?$")

_NAMESPACE_NAME_RE = re.compile(r"NAMESPACE")

PUT_METRIC_DATA = "put_metric_data"
METRIC_FILTER_NAMESPACE_KWARG = "metric_namespace"  # logs.MetricFilter, and nothing else
_ALARM_CTORS = ("Alarm", "create_alarm")

PRODUCER_EMIT = "emit"  # put_metric_data / EMF blob, from Python
PRODUCER_LOG_FILTER = "log-metric-filter"  # minted in CDK from log text

CONSUMER_ALARM = "alarm"
CONSUMER_DASHBOARD = "dashboard"
CONSUMER_READER = "reader"


# ─────────────────────────── file walking / parsing ───────────────────────────


def _iter_py_files(roots=PRODUCER_ROOTS):
    for root in roots:
        base = ROOT / root
        if not base.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            rel = os.path.relpath(dirpath, ROOT)
            if any(part in rel for part in _EXCLUDED_DIR_PARTS):
                dirnames[:] = []
                continue
            dirnames[:] = [d for d in dirnames if d not in ("__pycache__", "node_modules")]
            for fn in sorted(filenames):
                if fn.endswith(".py"):
                    yield Path(dirpath) / fn


def _parse(path: Path) -> ast.AST | None:
    try:
        return ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError, OSError):
        return None


# ────────────────────────────── name resolution ───────────────────────────────


def _module_str_bindings(tree: ast.AST) -> dict[str, str]:
    """`{name: value}` for every module-level `NAME = "literal"` assignment.

    Both plain and annotated assignments — `metric_namespaces.py` writes
    `SITE_API_METRIC_NAMESPACE: str = "LifePlatform/SiteAPI"`.
    """
    out: dict[str, str] = {}
    for node in getattr(tree, "body", []):
        targets: list = []
        value = None
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.target is not None:
            targets, value = [node.target], node.value
        if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
            continue
        for t in targets:
            if isinstance(t, ast.Name):
                out[t.id] = value.value
    return out


def _param_default_bindings(fn: ast.AST, bindings: dict[str, str]) -> dict[str, str]:
    """`{param: default}` for string-literal defaults on one function.

    `timeout_watchdog.arm(context, *, namespace=_NAMESPACE, ...)` emits with
    `Namespace=namespace` — the value is only knowable through the default, and
    without it the module reads as a *reader* of the namespace it writes.
    """
    args = getattr(fn, "args", None)
    if args is None:
        return {}
    out: dict[str, str] = {}
    pairs = list(zip(reversed(args.posonlyargs + args.args), reversed(args.defaults)))
    pairs += [(a, d) for a, d in zip(args.kwonlyargs, args.kw_defaults) if d is not None]
    for arg, default in pairs:
        # The default is usually a NAME, not a literal (`namespace=_NAMESPACE`),
        # so it has to resolve through the enclosing module's bindings.
        value = _resolve(default, bindings)
        if value is not None:
            out[arg.arg] = value
    return out


def shared_namespace_constants() -> dict[str, str]:
    """Namespace literals exported by `lambdas/common/metric_namespaces.py`."""
    tree = _parse(NAMESPACE_CONSTANTS_MODULE)
    if tree is None:
        return {}
    return {k: v for k, v in _module_str_bindings(tree).items() if OWN_NAMESPACE_RE.match(v)}


def _resolve(node: ast.AST | None, bindings: dict[str, str]) -> str | None:
    """A string value from a literal, a bound name, or `mod.NAME`."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return bindings.get(node.id)
    if isinstance(node, ast.Attribute):
        return bindings.get(node.attr)
    return None


def _walk_scoped(tree: ast.AST, base: dict[str, str]):
    """Yield `(node, bindings)` for every node, entering function scopes.

    A function scope inherits the module bindings and adds its own
    string-literal parameter defaults, so a namespace passed as a defaulted
    argument resolves at the call sites inside that function.
    """
    stack = [(tree, base)]
    while stack:
        node, bindings = stack.pop()
        yield node, bindings
        for child in ast.iter_child_nodes(node):
            child_bindings = bindings
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                child_bindings = {**bindings, **_param_default_bindings(child, bindings)}
            stack.append((child, child_bindings))


# ───────────────────────────── producer detection ─────────────────────────────


def _dict_keys(node: ast.Dict) -> set[str]:
    return {k.value for k in node.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)}


def _is_put_metric_data(node: ast.Call) -> bool:
    func = node.func
    return (isinstance(func, ast.Attribute) and func.attr == PUT_METRIC_DATA) or (isinstance(func, ast.Name) and func.id == PUT_METRIC_DATA)


def _keep(found: set[str], value: str | None) -> None:
    if value and OWN_NAMESPACE_RE.match(value):
        found.add(value)


def _emitted_namespaces(tree: ast.AST, base: dict[str, str]) -> set[str]:
    """Namespaces this module WRITES — put_metric_data kwarg, or an EMF entry dict."""
    found: set[str] = set()
    for node, bindings in _walk_scoped(tree, base):
        if isinstance(node, ast.Call) and _is_put_metric_data(node):
            for kw in node.keywords:
                if kw.arg == "Namespace":
                    _keep(found, _resolve(kw.value, bindings))
        elif isinstance(node, ast.Dict):
            keys = _dict_keys(node)
            # One `_aws.CloudWatchMetrics` entry: Namespace + Metrics together.
            # A GetMetricData query dict has Namespace + MetricName and no
            # Metrics key — excluded by construction.
            if "Namespace" in keys and "Metrics" in keys:
                for k, v in zip(node.keys, node.values):
                    if isinstance(k, ast.Constant) and k.value == "Namespace":
                        _keep(found, _resolve(v, bindings))
    return found


def _referenced_namespaces(tree: ast.AST, base: dict[str, str]) -> set[str]:
    """Namespaces this module NAMES at all — `*NAMESPACE*` constants + call arguments.

    Bare expression constants (docstrings) are excluded: documenting a
    namespace is not being wired to it. Dict *values* are excluded too — that
    is how `headers={"User-Agent": "LifePlatform/1.0"}` stops being a namespace.
    """
    found: set[str] = set()
    for name, value in _module_str_bindings(tree).items():
        if _NAMESPACE_NAME_RE.search(name):
            _keep(found, value)
    for node, bindings in _walk_scoped(tree, base):
        if isinstance(node, ast.Call):
            for arg in list(node.args) + [kw.value for kw in node.keywords]:
                _keep(found, _resolve(arg, bindings))
    return found


# Each sweep re-parses ~900 files (~5.7s), and the guard runs several sweeps inside
# the pre-merge lane whose duration is a measured ratchet (#3025). The per-file
# result is cached on (path, mtime, size) rather than on the path alone, so a file
# edited inside one process still invalidates.
_SCAN_CACHE: dict[tuple, tuple | None] = {}


def _scan_module(path: Path, shared: dict[str, str]):
    try:
        st = path.stat()
        key = (str(path), st.st_mtime_ns, st.st_size)
    except OSError:
        return None
    if key not in _SCAN_CACHE:
        tree = _parse(path)
        if tree is None:
            _SCAN_CACHE[key] = None
        else:
            base = dict(shared)
            base.update(_module_str_bindings(tree))
            _SCAN_CACHE[key] = (_emitted_namespaces(tree, base), _referenced_namespaces(tree, base))
    return _SCAN_CACHE[key]


def discover_cdk_log_filter_namespaces() -> dict[str, set[str]]:
    """`{namespace: {stack file, ...}}` for namespaces minted by `logs.MetricFilter`."""
    out: dict[str, set[str]] = {}
    if not CDK_STACKS_DIR.is_dir():
        return out
    for path in sorted(CDK_STACKS_DIR.glob("*.py")):
        tree = _parse(path)
        if tree is None:
            continue
        bindings = _module_str_bindings(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for kw in node.keywords:
                if kw.arg == METRIC_FILTER_NAMESPACE_KWARG:
                    ns = _resolve(kw.value, bindings)
                    if ns and OWN_NAMESPACE_RE.match(ns):
                        out.setdefault(ns, set()).add(path.name)
    return out


def discover_producers() -> dict[str, dict[str, set[str]]]:
    """`{namespace: {"emit": {module, ...}, "log-metric-filter": {stack, ...}}}`.

    Fully derived — there is no baseline list to drift.
    """
    shared = shared_namespace_constants()
    producers: dict[str, dict[str, set[str]]] = {}
    for path in _iter_py_files():
        scanned = _scan_module(path, shared)
        if scanned is None:
            continue
        emitted, _ = scanned
        for ns in emitted:
            producers.setdefault(ns, {}).setdefault(PRODUCER_EMIT, set()).add(path.relative_to(ROOT).as_posix())
    for ns, stacks in discover_cdk_log_filter_namespaces().items():
        producers.setdefault(ns, {}).setdefault(PRODUCER_LOG_FILTER, set()).update(stacks)
    return producers


def producer_modules(namespace: str, producers: dict | None = None) -> set[str]:
    """Every place that writes `namespace`, both producer kinds flattened."""
    producers = discover_producers() if producers is None else producers
    out: set[str] = set()
    for where in producers.get(namespace, {}).values():
        out.update(where)
    return out


# ───────────────────────────── consumer detection ─────────────────────────────


def discover_readers() -> dict[str, set[str]]:
    """`{namespace: {module that queries it but does not emit it, ...}}`."""
    shared = shared_namespace_constants()
    readers: dict[str, set[str]] = {}
    constants_module = NAMESPACE_CONSTANTS_MODULE.relative_to(ROOT).as_posix()
    for path in _iter_py_files(READER_ROOTS):
        rel = path.relative_to(ROOT).as_posix()
        if rel == constants_module:
            continue  # defines the literal; neither emits nor reads
        scanned = _scan_module(path, shared)
        if scanned is None:
            continue
        emitted, referenced = scanned
        for ns in referenced - emitted:
            readers.setdefault(ns, set()).add(rel)
    return readers


def _alarm_fed_filter_namespaces(tree: ast.AST, bindings: dict[str, str]) -> set[str]:
    """Namespaces whose `logs.MetricFilter` variable feeds an `Alarm` in this stack.

    `db_mf = logs.MetricFilter(..., metric_namespace="LifePlatform/Lambda")`
    then `cloudwatch.Alarm(..., metric=db_mf.metric(...))` — the alarm never
    names the namespace, so nothing textual connects the two.
    """
    filter_ns: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
            continue
        for kw in node.value.keywords:
            if kw.arg == METRIC_FILTER_NAMESPACE_KWARG:
                ns = _resolve(kw.value, bindings)
                if ns and OWN_NAMESPACE_RE.match(ns):
                    for t in node.targets:
                        if isinstance(t, ast.Name):
                            filter_ns[t.id] = ns
    if not filter_ns:
        return set()
    out: set[str] = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in _ALARM_CTORS):
            continue
        names = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
        if isinstance(node.func.value, ast.Name):
            names.add(node.func.value.id)
        for var, ns in filter_ns.items():
            if var in names:
                out.add(ns)
    return out


def discover_cdk_consumers() -> dict[str, dict[str, set[str]]]:
    """`{namespace: {"alarm": {stack, ...}, "dashboard": {stack, ...}}}`."""
    consumers: dict[str, dict[str, set[str]]] = {}
    if not CDK_STACKS_DIR.is_dir():
        return consumers
    minted = discover_cdk_log_filter_namespaces()
    for path in sorted(CDK_STACKS_DIR.glob("*.py")):
        tree = _parse(path)
        if tree is None:
            continue
        bindings = _module_str_bindings(tree)
        kind = CONSUMER_DASHBOARD if path.name == DASHBOARD_STACK else CONSUMER_ALARM
        named = _referenced_namespaces(tree, bindings)
        # A namespace named ONLY as a MetricFilter's `metric_namespace` is being
        # produced there, not consumed; it becomes a consumer only via an alarm
        # built on that filter.
        for ns in named:
            if ns in minted and path.name in minted[ns] and ns not in _alarm_fed_filter_namespaces(tree, bindings):
                continue
            consumers.setdefault(ns, {}).setdefault(kind, set()).add(path.name)
        for ns in _alarm_fed_filter_namespaces(tree, bindings):
            consumers.setdefault(ns, {}).setdefault(CONSUMER_ALARM, set()).add(path.name)
    return consumers


def discover_consumers() -> dict[str, dict[str, set[str]]]:
    """Every consumer of every namespace, merged: CDK alarms, dashboards, readers.

    A namespace with an empty entry here is genuinely write-only: the series is
    billed every month and nothing on the platform ever looks at it.
    """
    merged = {ns: {k: set(v) for k, v in kinds.items()} for ns, kinds in discover_cdk_consumers().items()}
    for ns, mods in discover_readers().items():
        merged.setdefault(ns, {}).setdefault(CONSUMER_READER, set()).update(mods)
    return merged


def consumer_kinds(namespace: str, consumers: dict | None = None) -> set[str]:
    """The set of consumer kinds for one namespace — `set()` means write-only."""
    consumers = discover_consumers() if consumers is None else consumers
    return {k for k, v in consumers.get(namespace, {}).items() if v}


def _main() -> int:  # pragma: no cover - operator convenience
    producers = discover_producers()
    consumers = discover_consumers()
    for ns in sorted(set(producers) | set(consumers)):
        kinds = ",".join(sorted(consumer_kinds(ns, consumers))) or "WRITE-ONLY"
        print(f"{ns:36s} consumer={kinds:26s} producers={len(producer_modules(ns, producers))}")
        for kind, where in sorted(producers.get(ns, {}).items()):
            for w in sorted(where):
                print(f"      {kind:16s} <- {w}")
        for kind, where in sorted(consumers.get(ns, {}).items()):
            for w in sorted(where):
                print(f"      {kind:16s} -> {w}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
