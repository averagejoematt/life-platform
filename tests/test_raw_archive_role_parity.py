"""tests/test_raw_archive_role_parity.py — #1949 raw-archive grant/config parity.

The weather raw-S3 archive died on 2026-03-09: the Full-IaC IAM migration
(8426d0e) shipped ingestion_weather() as "DDB write only, no S3" while
weather_lambda.py kept `s3_archive_prefix="raw/weather"`. The framework
swallowed the resulting AccessDenied twice daily for ~5 months — repo == live
(IAM parity) while the capability was dead, and the registry's raw_layout facet
kept claiming the layout was ACTUAL.

This guard makes that disagreement a red test instead of an unread log line:

  1. Every `IngestionConfig(s3_archive_prefix=...)` in lambdas/ingestion/ maps
     to a role_policies.ingestion_<source>() whose statements grant s3:PutObject
     on exactly that prefix. FAILS on the pre-#1949 tree (weather).
  2. Every such config source that appears in the source registry carries a
     non-None raw_layout whose prefix matches the config — the facet can't
     drift from what the lambda actually writes.

Guard-the-SET discipline: the config list is AST-derived from the whole
lambdas/ingestion/ tree (a new framework source is covered the day it lands),
and the scan itself is proven live by asserting it found both a plain-literal
prefix (weather) and an f-string prefix (garmin).
"""

import ast
import fnmatch
import os
import sys
import types

# ── Stub aws_cdk so role_policies.py imports without CDK installed ────────────
# (same minimal stub as tests/test_role_policies.py; setdefault keeps whichever
# test loaded first authoritative — the shapes are compatible)


class _PolicyStatement:
    def __init__(self, sid="", actions=None, resources=None, **kwargs):
        self.sid = sid
        self.actions = list(actions or [])
        self.resources = list(resources or [])


_iam_stub = types.ModuleType("aws_cdk.aws_iam")
_iam_stub.PolicyStatement = _PolicyStatement
_cdk_stub = types.ModuleType("aws_cdk")
_cdk_stub.aws_iam = _iam_stub
sys.modules.setdefault("aws_cdk", _cdk_stub)
sys.modules.setdefault("aws_cdk.aws_iam", _iam_stub)

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "cdk"))
sys.path.insert(0, os.path.join(_REPO, "cdk", "stacks"))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

import role_policies as rp  # noqa: E402

INGESTION_DIR = os.path.join(_REPO, "lambdas", "ingestion")

# The one name framework configs interpolate into archive prefixes. Every
# definition site is `USER_ID = os.environ.get("USER_ID", "matthew")`; the
# deployed default is what the role must cover.
_NAME_VALUES = {"USER_ID": "matthew"}


def _module_constants(tree):
    """Module-level `NAME = "literal"` assignments (e.g. SOURCE = "youtube")."""
    consts = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name):
                    consts[tgt.id] = node.value.value
    return consts


def _resolve_str(node, consts):
    """Resolve a string-valued AST node (constant, module constant, f-string), or None."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return _NAME_VALUES.get(node.id, consts.get(node.id))
    if isinstance(node, ast.JoinedStr):
        parts = []
        for piece in node.values:
            if isinstance(piece, ast.Constant):
                parts.append(str(piece.value))
            elif isinstance(piece, ast.FormattedValue):
                resolved = _resolve_str(piece.value, consts)
                if resolved is None:
                    return None  # unknown interpolation — surface it via the scan floor below
                parts.append(resolved)
            else:
                return None
        return "".join(parts)
    return None


def _scan_ingestion_configs():
    """{source_name: s3_archive_prefix} for every IngestionConfig in lambdas/ingestion/."""
    configs = {}
    unresolved = []
    for fname in sorted(os.listdir(INGESTION_DIR)):
        if not fname.endswith(".py"):
            continue
        with open(os.path.join(INGESTION_DIR, fname)) as f:
            tree = ast.parse(f.read(), filename=fname)
        consts = _module_constants(tree)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", "")) == "IngestionConfig"):
                continue
            kw = {k.arg: k.value for k in node.keywords if k.arg}
            if "s3_archive_prefix" not in kw:
                continue
            source = _resolve_str(kw.get("source_name"), consts) if "source_name" in kw else None
            prefix = _resolve_str(kw["s3_archive_prefix"], consts)
            if source is None or prefix is None:
                unresolved.append(f"{fname}: source={source!r} prefix_resolved={prefix!r}")
                continue
            configs[source] = prefix
    assert not unresolved, (
        "IngestionConfig(s3_archive_prefix=...) call(s) this guard cannot resolve — extend "
        f"_literal_prefix/_NAME_VALUES so the parity check keeps covering the full set: {unresolved}"
    )
    return configs


CONFIGS = _scan_ingestion_configs()


def _put_object_resources(fn_name):
    stmts = getattr(rp, fn_name)()
    resources = []
    for s in stmts:
        if any(a.lower() == "s3:putobject" for a in s.actions):
            resources.extend(s.resources)
    return resources


def test_scan_found_the_known_shapes():
    """Prove the AST scan is alive: a plain-literal prefix (weather) and an
    f-string prefix (garmin) must both be in the derived set."""
    assert "weather" in CONFIGS, f"scan lost the literal-prefix case; found: {sorted(CONFIGS)}"
    assert CONFIGS["weather"] == "raw/weather"
    assert "garmin" in CONFIGS, f"scan lost the f-string-prefix case; found: {sorted(CONFIGS)}"
    assert CONFIGS["garmin"] == "raw/matthew/garmin"
    assert len(CONFIGS) >= 8, f"framework config set shrank unexpectedly: {sorted(CONFIGS)}"


def test_every_archive_prefix_has_a_role_that_can_write_it():
    """#1949 acceptance: no s3_archive_prefix whose role cannot write it.

    FAILS on the pre-fix tree: ingestion_weather() had no s3:PutObject at all
    while weather_lambda.py archived to raw/weather — the exact repo==live-but-
    dead-capability state that killed the archive for five months.
    """
    problems = []
    for source, prefix in sorted(CONFIGS.items()):
        fn_name = f"ingestion_{source}"
        if not hasattr(rp, fn_name):
            problems.append(f"{source}: no role_policies.{fn_name}() for its IngestionConfig")
            continue
        # A representative key the framework will actually write — the grant may
        # be broader than the exact prefix (strava's raw/matthew/strava/* covers
        # .../strava/activities/*); coverage, not equality, is the invariant.
        representative = f"{rp.BUCKET_ARN}/{prefix}/2026/08/2026-08-02.json"
        got = _put_object_resources(fn_name)
        if not any(fnmatch.fnmatchcase(representative, pattern) for pattern in got):
            problems.append(f"{source}: {fn_name}() cannot PutObject under {prefix}/ (has: {got or 'NO s3:PutObject statement'})")
    assert not problems, "role/config raw-archive disagreement (#1949 class):\n  " + "\n  ".join(problems)


def test_registry_raw_layout_matches_the_config():
    """The raw_layout facet is documented as the ACTUAL shape (#1256) — for every
    framework source that archives, the facet must exist and its prefix must be
    the one the lambda actually writes."""
    from ingestion.source_registry import SOURCE_REGISTRY

    problems = []
    for source, prefix in sorted(CONFIGS.items()):
        entry = SOURCE_REGISTRY.get(source)
        if entry is None:
            continue  # registry-resident sources only — non-registry configs have no facet to be honest about
        layout = entry.get("raw_layout")
        if not layout:
            problems.append(f"{source}: archives to {prefix} but raw_layout is None — the facet denies a live archive")
        elif layout.get("prefix") != prefix:
            problems.append(f"{source}: raw_layout.prefix={layout.get('prefix')!r} != config s3_archive_prefix={prefix!r}")
    assert not problems, "raw_layout facet drift vs IngestionConfig:\n  " + "\n  ".join(problems)
