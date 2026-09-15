"""scripts/check_ingestion_hardcoded_literals.py — the #3662 generalized guard.

`measurements_ingestion_lambda.py` wrote `"measured_by": "partner"` as a hard-coded
string literal on every ingested item. The bug wasn't that ONE field was wrong — it
was that nothing in the repo would have caught a SECOND one landing the same way in
a different ingestion Lambda (#3662's own framing: "the generalised set ... is the
one worth sweeping; this is the instance that surfaced it").

WHAT THIS DETECTS
-----------------
Per file in `lambdas/ingestion/`, this walks the AST and:

1. Collects every "read name" — a string literal passed to a `.get("field")` call,
   or used as a Load-context subscript key (`row["field"]`) — anywhere in the file.
   This is the set of source-column names the file is DEMONSTRABLY capable of
   reading (from a CSV row dict, a parsed JSON payload, an API response, etc).

2. Collects every "hard-coded literal field" — a plain string key mapped to a plain
   string VALUE (not a variable, not an f-string, not a function call) inside a dict
   literal that looks like a DDB item (heuristically: the dict also has a `"pk"` or
   `"sk"` key, or the dict literal is passed as the `Item=` keyword to a `put_item`
   call).

A field is a VIOLATION when its name appears in BOTH sets: the file reads a
same-named column somewhere, yet the write path throws that reading away for a
constant — which is exactly the shape that made `measured_by` unfixable by the CSV.
This is deliberately narrower than "any hard-coded string in an item dict" (most of
those — `"unit": "in"`, `"phase": "..."` — are genuinely constant metadata, not a
column the source could ever override) and it generalizes the ONE bug #3662 found
into a check that would catch a re-introduction, or a new ingestion Lambda landing
the same mistake, in ANY file under this directory.

EXEMPTIONS
----------
A (file, field) pair with a real reason for being both read and hard-coded (e.g. a
value read for validation/logging only, never eligible to override the write) is
registered in `EXEMPTIONS` below with a one-line written reason — never silently.
"""

from __future__ import annotations

import ast
import os

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INGESTION_DIR = os.path.join(_REPO, "lambdas", "ingestion")

# DDB's own keying-scheme attributes are never a "source column" by construction —
# every ingestion Lambda builds pk/sk from the record's date/id, they are never a
# value the CSV/API could supply, so they are excluded globally rather than via a
# per-file exemption (there is nothing file-specific to say about any of them).
_STRUCTURAL_KEY_FIELDS = frozenset({"pk", "sk", "gsi1pk", "gsi1sk", "gsi2pk", "gsi2sk"})

# {filename: {field_name: "reason"}} — a registered exemption suppresses the finding
# for that exact (file, field) pair. Every entry needs a reason; there is no
# blanket/wildcard exemption.
EXEMPTIONS: dict[str, dict[str, str]] = {
    "habitify_lambda.py": {
        # The read (`existing.get("supplements", [])`'s entries `.get("source")`) is
        # filtering PREVIOUSLY-STORED rows to find manual (non-bridge) entries; the
        # hardcoded write is this Lambda stamping its own provenance tag on a NEW row.
        # Same field name, disjoint payloads — not the #3662 shape (a same-ROW column
        # thrown away).
        "source": "provenance tag on a freshly-written row; the read is filtering OLD stored rows by their own tag, not a same-row CSV/API column (verified 2026-09-14, #3662)",
    },
    "macrofactor_lambda.py": {
        # `item.get("source", csv_type)` reads the value THIS SAME hardcode just wrote
        # a few lines earlier (a self-referential default-label lookup), not an
        # external column with a competing value.
        "source": "self-referential — reads the value this Lambda's own hardcode just wrote onto the same item dict, not an external CSV/API column (verified 2026-09-14, #3662)",
    },
    "whoop_lambda.py": {
        # `m["kind"]` / `missing.append({"kind": "daily", ...})` — a type discriminator
        # this Lambda invents for its OWN internal "what's missing" bookkeeping list;
        # there is no external "kind" column, Whoop's API never sends one.
        "kind": "internal discriminator tag for a self-built bookkeeping list, not a field read from the Whoop API (verified 2026-09-14, #3662)",
    },
}


def _dict_item_keys(node: ast.Dict) -> dict[str, ast.AST]:
    """Plain-string-keyed entries of a dict literal, keyed by the string."""
    out = {}
    for k, v in zip(node.keys, node.values):
        if isinstance(k, ast.Constant) and isinstance(k.value, str):
            out[k.value] = v
    return out


def _looks_like_ddb_item(node: ast.Dict) -> bool:
    keys = _dict_item_keys(node)
    return "pk" in keys or "sk" in keys


def _is_plain_string_literal(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def scan_file(path: str) -> list[tuple[str, str]]:
    """Returns [(field_name, literal_value), ...] violations for one file."""
    with open(path, encoding="utf-8") as f:
        src = f.read()
    try:
        tree = ast.parse(src, filename=path)
    except SyntaxError:
        return []

    read_names: set[str] = set()
    item_dicts: list[ast.Dict] = []

    for node in ast.walk(tree):
        # `.get("field", ...)` anywhere — a demonstrated read capability.
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get":
            if node.args:
                name = _is_plain_string_literal(node.args[0])
                if name:
                    read_names.add(name)
        # `row["field"]` in LOAD context — same signal, subscript form.
        elif isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Load):
            key_node = node.slice
            name = _is_plain_string_literal(key_node)
            if name:
                read_names.add(name)
        # Dict literals that look like a DDB item (has pk/sk), OR are passed as
        # `Item=` to a put_item-style call.
        elif isinstance(node, ast.Dict) and _looks_like_ddb_item(node):
            item_dicts.append(node)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in ("put_item", "update_item"):
            for kw in node.keywords:
                if kw.arg == "Item" and isinstance(kw.value, ast.Dict):
                    item_dicts.append(kw.value)

    violations: list[tuple[str, str]] = []
    seen: set[str] = set()
    for d in item_dicts:
        for field, value_node in _dict_item_keys(d).items():
            if field in _STRUCTURAL_KEY_FIELDS:
                continue
            literal_value = _is_plain_string_literal(value_node)
            if literal_value is None:
                continue
            if field in read_names and field not in seen:
                seen.add(field)
                violations.append((field, literal_value))
    return violations


def scan_all(ingestion_dir: str = INGESTION_DIR, exemptions: dict | None = None) -> dict[str, list[tuple[str, str]]]:
    """{relative_filename: [(field, value), ...]} for every un-exempted violation."""
    exemptions = EXEMPTIONS if exemptions is None else exemptions
    out: dict[str, list[tuple[str, str]]] = {}
    for name in sorted(os.listdir(ingestion_dir)):
        if not name.endswith(".py"):
            continue
        path = os.path.join(ingestion_dir, name)
        found = scan_file(path)
        exempt_fields = exemptions.get(name, {})
        remaining = [(f, v) for f, v in found if f not in exempt_fields]
        if remaining:
            out[name] = remaining
    return out


if __name__ == "__main__":
    results = scan_all()
    if not results:
        print("check_ingestion_hardcoded_literals: clean — no un-exempted hard-coded literal fields")
    else:
        for fname, viols in results.items():
            for field, value in viols:
                print(f"{fname}: field {field!r} is hard-coded to {value!r} but the file also reads a column named {field!r}")
        raise SystemExit(1)
