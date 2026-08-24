"""tests/conformance_guard_lib.py — the kernel conformance sweep (#2844, epic #2842).

The fleet-wide form of the charter's derivation-guard primitive (docs/CHARTER.md,
standing rule 1): no hand-maintained enumeration of registry vocabulary lands
without a dated exemption. Every silently-missed consumer the 2026-08-16 elite
review traced was a hand-typed list of registry vocabulary (SOCIAL_CHANNELS env,
_BROADCAST_SOURCES, ALL_LAMBDAS at 40 of ~106, the daily-brief channel set);
per-instance fixes close instances — this sweep closes the CLASS.

Mechanism: AST-walk ``lambdas/ mcp/ cdk/`` for literal sequences of strings (and
comma-joined string constants, the env-default idiom) whose members are drawn
from a registry vocabulary. A literal enumeration of registry vocabulary is
hand-typed by construction — a derived enumeration is a call, not a literal.
Each hit must appear in the dated, shrink-only ledger
(``tests/conformance_residue.py``); the guard test asserts both directions.

Vocabularies (v1 — the ones with executable registries today):
  sources   — ``ingestion.source_registry.SOURCE_REGISTRY`` keys
  personas  — ``config/personas.json`` persona ids (via common.repo_config)
  lambdas   — ``function_name="..."`` declarations in cdk/stacks/*.py
  alarms    — ``alarm_name="..."`` declarations in cdk/stacks/*.py
Field names wait on the #2797 wiring registry; channels on its channel facet.

Detection thresholds (false-positive control, tuned on the initial sweep):
  * only literal List/Tuple/Set of ≥2 string constants (or a comma-string of
    ≥2 tokens) is an enumeration — a single string is a reference, not a copy;
  * ≥2 members must be vocabulary tokens AND ≥60% of members must match;
  * tokens shorter than 3 chars (the source id ``x``) never establish a match
    on their own — they count only alongside ≥2 longer matched tokens.
"""

from __future__ import annotations

import ast
import json
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

sys.path.insert(0, str(ROOT / "lambdas"))
sys.path.insert(0, str(ROOT))

os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

SCAN_ROOTS = ("lambdas", "mcp", "cdk")
_SKIP_PATH_MARKERS = ("__pycache__", "_staging", "cdk.out", "node_modules", ".venv", "layer-build")

# Registries themselves (and their sanctioned sibling censuses) are the one
# place vocabulary may be spelled out — the sweep starts one level above them.
_SANCTIONED_REGISTRY_FILES = {
    "lambdas/ingestion/source_registry.py",
    "lambdas/experiment/phase_taxonomy.py",  # the partition census (ADR-077)
    "lambdas/coach/persona_registry.py",
    # The compute-input census (#3049/DIL-024): which source partitions each of the
    # five compute Lambdas reads. Sanctioned on the same grounds as phase_taxonomy —
    # it is a census, not a copy of one. No existing registry holds this fact
    # (source_registry states each source's CADENCE, never its consumers; the #2845
    # platform model resolves only literal pk constructions, which misses every read
    # routed through a `fetch_date(src, ...)` helper — it derives 0 sources for
    # hypothesis-engine). Adding it here is paid for immediately: the two copies that
    # WERE carried as debt — `hypothesis_engine_lambda.py::sources::...` and
    # `daily_metrics_compute_lambda.py::sources::...`, both dated 2026-08-17 — now
    # derive from the census and came OUT of the ledger, so the ratchet counted down
    # (charter standing rule 2), it did not grow sideways.
    "lambdas/common/input_manifest.py",
}

_MIN_MEMBERS = 2  # a one-string literal is a reference, not an enumeration
_MIN_MATCHES = 2
_MIN_RATIO = 0.60
_SHORT_TOKEN_LEN = 3  # tokens shorter than this never establish a match alone


def _cdk_declared_names(kwarg: str) -> set[str]:
    """Collect every string passed as ``<kwarg>="..."`` in cdk/stacks/*.py.

    The CDK keyword *declaration* site is the registry for lambda/alarm names;
    a literal collection of those names anywhere (including inside a stack) is
    a hand-typed copy.
    """
    names: set[str] = set()
    for path in sorted((ROOT / "cdk" / "stacks").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for kw in node.keywords:
                if kw.arg == kwarg and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                    names.add(kw.value.value)
    return names


def load_vocabularies() -> dict[str, set[str]]:
    from ingestion.source_registry import SOURCE_REGISTRY

    personas_path = ROOT / "config" / "personas.json"
    persona_ids = set(json.loads(personas_path.read_text(encoding="utf-8"))["personas"].keys())

    return {
        "sources": set(SOURCE_REGISTRY.keys()),
        "personas": persona_ids,
        "lambdas": _cdk_declared_names("function_name"),
        "alarms": _cdk_declared_names("alarm_name"),
    }


def _literal_string_members(node: ast.AST) -> list[str] | None:
    """Members of a List/Tuple/Set of string constants, else None.

    A sequence whose elements are themselves pure-string tuples (the mapping-table
    idiom: ``[("cgm", "apple_health"), ...]``) flattens to ONE enumeration site —
    the table is the hand-typed list, not each row.
    """
    if not isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return None
    members: list[str] = []
    for elt in node.elts:
        if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
            members.append(elt.value)
        elif (
            isinstance(elt, (ast.Tuple, ast.List))
            and elt.elts
            and all(isinstance(e, ast.Constant) and isinstance(e.value, str) for e in elt.elts)
        ):
            members.extend(e.value for e in elt.elts)
        else:
            return None  # mixed/derived content — not a pure hand-typed enumeration
    return members if len(members) >= _MIN_MEMBERS else None


def _comma_string_members(node: ast.AST) -> list[str] | None:
    """Tokens of a bare "a,b,c" string constant (the env-default idiom), else None."""
    if not (isinstance(node, ast.Constant) and isinstance(node.value, str) and "," in node.value):
        return None
    tokens = [t.strip() for t in node.value.split(",")]
    if len(tokens) < _MIN_MEMBERS or any(not t or " " in t for t in tokens):
        return None  # prose with commas, not a token list
    return tokens


def _matched(members: list[str], vocab: set[str]) -> list[str]:
    distinct = set(members)
    hits = distinct & vocab
    long_hits = {h for h in hits if len(h) >= _SHORT_TOKEN_LEN}
    if len(long_hits) < _MIN_MATCHES:
        return []  # short tokens (e.g. source id "x") never carry a match alone
    if len(hits) / len(distinct) < _MIN_RATIO:
        return []
    return sorted(hits)


def site_key(relpath: str, vocab_name: str, matched: list[str]) -> str:
    """Content-keyed, line-number-independent identity for a violation site.

    Keying on the matched members is deliberate: EDITING an exempted hand-list
    (the missed-consumer moment) changes the key, surfaces as a new violation,
    and forces the site to derive — re-dating the ledger is not an option.
    """
    return f"{relpath}::{vocab_name}::{','.join(matched)}"


def sweep(vocabularies: dict[str, set[str]] | None = None) -> dict[str, list[str]]:
    """Return {site_key: matched_members} for every hand-typed enumeration."""
    vocabs = vocabularies if vocabularies is not None else load_vocabularies()
    findings: dict[str, list[str]] = {}
    for scan_root in SCAN_ROOTS:
        for path in sorted((ROOT / scan_root).rglob("*.py")):
            rel = path.relative_to(ROOT).as_posix()
            if any(marker in rel for marker in _SKIP_PATH_MARKERS):
                continue
            if rel in _SANCTIONED_REGISTRY_FILES:
                continue
            findings.update(sweep_source(path.read_text(encoding="utf-8"), rel, vocabs))
    return findings


def sweep_source(source: str, relpath: str, vocabs: dict[str, set[str]]) -> dict[str, list[str]]:
    """Sweep one file's source text (separated for the mutation self-tests)."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {}
    findings: dict[str, list[str]] = {}
    consumed: set[int] = set()  # children of a flattened table are part of ITS site
    for node in ast.walk(tree):
        if id(node) in consumed:
            continue
        members = _literal_string_members(node)
        if members is not None and isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            for elt in node.elts:
                for child in ast.walk(elt):
                    consumed.add(id(child))
        if members is None:
            members = _comma_string_members(node)
        if members is None:
            continue
        for vocab_name, vocab in vocabs.items():
            hits = _matched(members, vocab)
            if hits:
                findings[site_key(relpath, vocab_name, hits)] = hits
    return findings
