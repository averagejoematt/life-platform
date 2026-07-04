"""
tests/test_ddb_key_contracts.py — DynamoDB key-contract gate (2026-06-12).

Root cause of: three code paths reading profile keys that have NEVER existed,
each silently degrading to {} via a bare except —
  - hypothesis_engine: USER#matthew#profile / PROFILE   (profile was {} since inception)
  - site-api AI ctx:   USER#matthew#SOURCE#profile / PROFILE (always fell back to constants)
  - (canonical is USER#matthew / PROFILE#v1 — the only key that exists)

The class: an exact-key `get_item` whose pk/sk literal drifts from what's in the
table fails *silently* — get_item returns no Item, the except-or-default path
hides it, and downstream logic runs on empty data forever.

The gate: AST-extract every statically-resolvable exact-key get_item from
lambdas/ + mcp/, then verify each (pk, sk) actually exists in the live table.
Keys with runtime-variable parts (dates, ids) can't be checked and are skipped;
the test reports how many were skipped so coverage erosion is visible.

Keys that are legitimately absent at times (e.g. wiped at an experiment reset
and lazily recreated) belong in KNOWN_OPTIONAL with a reason.

Run:  python3 -m pytest tests/test_ddb_key_contracts.py -v -m integration
"""

import ast
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCAN_DIRS = ["lambdas", "mcp"]
TABLE = "life-platform"
REGION = "us-west-2"

pytestmark = pytest.mark.integration

# (pk, sk) pairs that may legitimately be absent — reason required.
KNOWN_OPTIONAL: dict[tuple, str] = {
    ("USER#matthew#ledger", "TOTALS#current"): "zeroed/recreated by restart_ledger_reset (ADR-072)",
    (
        "USER#matthew#SOURCE#panelcast",
        "STATE#current",
    ): "The Panel series_state — seeded on the first published weekly episode; _state_read tolerates absence (returns {})",
    (
        "USER#matthew#SOURCE#email_digest",
        "STATE#between_chronicle",
    ): "#398 dedup marker — created on the first between-chronicle send; the read tolerates absence (empty marker = send)",
    (
        "PERSONA#elena",
        "STANCE#latest",
    ): "#537 Elena's editorial stance — seeded by elena-state-updater on the first post-publish extraction; every reader fail-softs to ''",
    (
        "PERSONA#elena",
        "MOTIF#state",
    ): "#537 Elena's running motifs — seeded on the first post-publish extraction; readers tolerate absence",
    (
        "USER#matthew#SOURCE#panelcast",
        "SHOW#memory",
    ): "#547 the show-memory ledger — seeded on the first v2 episode publish; _load_show_memory tolerates absence (empty memory)",
}

# Module-level constant values used to resolve f-strings statically.
STATIC_NAMES = {
    "USER_ID": "matthew",
    "USER_PREFIX": "USER#matthew#SOURCE#",
    "PROFILE_PK": "USER#matthew",
}


def _resolve(node, local_consts):
    """Statically resolve a str constant or f-string AST node, else None."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts = []
        for v in node.values:
            if isinstance(v, ast.Constant):
                parts.append(str(v.value))
            elif isinstance(v, ast.FormattedValue) and isinstance(v.value, ast.Name):
                name = v.value.id
                val = local_consts.get(name, STATIC_NAMES.get(name))
                if val is None:
                    return None
                parts.append(str(val))
            else:
                return None
        return "".join(parts)
    if isinstance(node, ast.Name):
        return local_consts.get(node.id, STATIC_NAMES.get(node.id))
    return None


def _module_consts(tree):
    consts = {}
    for n in tree.body:
        if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
            val = _resolve(n.value, consts)
            if val is not None:
                consts[n.targets[0].id] = val
    return consts


def _extract_get_item_keys():
    """Yield (file:line, pk, sk) for statically-resolvable get_item calls; count skips."""
    found, skipped = [], 0
    for d in SCAN_DIRS:
        for path in (ROOT / d).rglob("*.py"):
            if "__pycache__" in str(path) or "layer-build" in str(path):
                continue
            try:
                tree = ast.parse(path.read_text())
            except (SyntaxError, UnicodeDecodeError):
                continue
            consts = _module_consts(tree)
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get_item"):
                    continue
                key_kw = next((k for k in node.keywords if k.arg == "Key"), None)
                if not key_kw or not isinstance(key_kw.value, ast.Dict):
                    continue
                kv = {}
                for k, v in zip(key_kw.value.keys, key_kw.value.values):
                    kname = _resolve(k, consts)
                    if kname in ("pk", "sk"):
                        kv[kname] = _resolve(v, consts)
                if "pk" not in kv:
                    continue
                if kv.get("pk") is None or kv.get("sk") is None:
                    skipped += 1
                    continue
                rel = str(path.relative_to(ROOT))
                found.append((f"{rel}:{node.lineno}", kv["pk"], kv["sk"]))
    return found, skipped


def _has_aws():
    try:
        import boto3

        boto3.client("sts", region_name=REGION).get_caller_identity()
        return True
    except Exception:
        return False


def test_every_static_get_item_key_exists_in_table():
    """Every statically-resolvable exact-key read must hit a real item."""
    if os.environ.get("SKIP_AWS_TESTS") or not _has_aws():
        pytest.skip("no AWS credentials")
    import boto3

    table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE)
    found, skipped = _extract_get_item_keys()
    assert found, "extractor found no static get_item keys — extraction regressed"

    missing = []
    for loc, pk, sk in sorted(set(found)):
        if (pk, sk) in KNOWN_OPTIONAL:
            continue
        resp = table.get_item(Key={"pk": pk, "sk": sk}, ProjectionExpression="pk")
        if "Item" not in resp:
            missing.append(f"{loc}: ({pk!r}, {sk!r}) — no such item; reads silently return nothing")

    print(f"\n  key-contract coverage: {len(set(found))} static keys verified, {skipped} dynamic keys skipped")
    assert (
        not missing
    ), "Dead DynamoDB key reads (the hypothesis_engine bug class — fix the key " "or add to KNOWN_OPTIONAL with a reason):\n" + "\n".join(
        missing
    )
