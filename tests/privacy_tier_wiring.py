"""tests/privacy_tier_wiring.py — the derived Tier-2 consumer registry (#2803).

WHY THIS EXISTS
---------------
`lambdas/privacy/field_tiers.py` declares which fields are Tier-2 owner-only. This
derives, from the tree, **who mentions them** — and forces an explicit decision on every
(module, field) pair, so a new consumer cannot appear silently.

The failure this prevents is measured, not imagined. #2782's consumer sweep declared "all
current consumers are field-selective"; #2809 found it FALSE — `mcp/tools_data.py` had
been dumping whole withings rows into Claude context for weeks. A hand sweep missed one
module. So the module set is **discovered** here, never hand-listed, and `CONSUMERS` below
supplies only the *policy* for what discovery finds.

HOW IT'S GUARDED (guard the SET, not the instance)
--------------------------------------------------
`scan_tree()` AST-scans `lambdas/` and `mcp/` for any mention of a Tier-2 field name —
as a string constant, an attribute, a dict key, or a bare name. `CONSUMERS` records one
`(module, field) -> decision` per discovered pair. The test asserts BOTH directions:

  * every discovered pair has a `CONSUMERS` entry -> a NEW module touching a Tier-2 field
    fails the build until someone classifies it;
  * every `CONSUMERS` entry still resolves to a real discovered pair -> the registry
    cannot rot into a stale hand-list describing code that no longer exists.

and a pair whose module is in a PUBLIC or AI family may only carry `EXCLUDED` — `SAW` is
structurally unavailable there. That is the build-breaking half: to publish a Tier-2 field
you must first change this file, and changing it is the recorded decision.

WHY A MENTION AND NOT A READ
----------------------------
The scan is deliberately WIDER than "reads the value". Proving a genuine read requires
dataflow analysis the repo does not have, and the #2809 miss was a module that never named
the field at all — it dumped the row. Mentions are cheap to classify (there are 4 in the
whole tree) and a false positive costs one `EXCLUDED` line with a reason, which is exactly
the artifact this issue wants. The row-dump hole is closed separately, by
`tools_data._strip_tier2` deriving its strip set from `field_tiers.strip_map()`.
"""

from __future__ import annotations

import ast
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(_HERE)

import sys  # noqa: E402

sys.path.insert(0, os.path.join(REPO, "lambdas"))

from privacy.field_tiers import TIER_OWNER_ONLY, fields_at_tier  # noqa: E402

# ── Consumer families ─────────────────────────────────────────────────────────
# A module's family is decided by its path. PUBLIC and AI are the two the SCHEMA ruling
# names ("never on a public surface and never quoted into an AI narrative context"); a
# pair in either may ONLY be EXCLUDED.
FAMILY_PUBLIC = "public"  # serves averagejoematt.com
FAMILY_AI = "ai"  # builds narrative/prompt context
FAMILY_OWNER = "owner"  # the owner's own MCP surface — field-selective reads sanctioned
FAMILY_WRITER = "writer"  # ingestion: writes the field, by definition sees it
FAMILY_INTERNAL = "internal"  # everything else — ops, compute, tooling

RESTRICTED_FAMILIES = frozenset({FAMILY_PUBLIC, FAMILY_AI})


def family_of(rel_path: str) -> str:
    """The consumer family for a module path.

    Ordered most-specific first. `lambdas/web/site_api*` is the public serving path;
    `lambdas/ai/` and `lambdas/coach/` build narrative context. `mcp/` is the owner-only
    surface (ADR: MCP is reached only through Matthew's own Claude clients).
    """
    if rel_path.startswith("lambdas/web/site_api"):
        return FAMILY_PUBLIC
    if rel_path.startswith(("lambdas/ai/", "lambdas/coach/", "lambdas/content/")):
        return FAMILY_AI
    if rel_path.startswith("mcp/"):
        return FAMILY_OWNER
    if rel_path.startswith("lambdas/ingestion/"):
        return FAMILY_WRITER
    return FAMILY_INTERNAL


# ── Decisions ─────────────────────────────────────────────────────────────────
SAW = "SAW"  # this module legitimately handles the field
EXCLUDED = "EXCLUDED"  # the mention is not a value read, or the value is stripped here
VALID_DECISIONS = frozenset({SAW, EXCLUDED})


def _d(decision: str, reason: str) -> dict:
    return {"decision": decision, "reason": reason}


# `(rel_path, field) -> decision`. Every entry carries a reason SPECIFIC to it — a
# registry whose reasons are all one sentence records that nobody looked (the #2056
# lesson from grounding_wiring).
CONSUMERS: dict[tuple[str, str], dict] = {
    ("lambdas/ingestion/withings_lambda.py", "vascular_age"): _d(
        SAW,
        "The ingester: MEAS_TYPES maps device measure 155 to this name. It writes the "
        "field, so it necessarily names it; the writer is where the tier is assigned, "
        "not where it leaks.",
    ),
    ("lambdas/ingestion/withings_lambda.py", "metabolic_age"): _d(
        SAW,
        "Same map, device measure 227. Written by the same #2782 BodyScan-2 path.",
    ),
    ("lambdas/ingestion/withings_lambda.py", "afib_result"): _d(
        SAW,
        "Same map, device measure 130 (ECG screening; 0 = ran, not detected). Stored as "
        "an event-class result, never rolled into a trend stat.",
    ),
    # NOTE — `mcp/tools_data.py` is deliberately ABSENT. It was the #2809 leak site and
    # it carried a hand-written `TIER2_STRIP_FIELDS` literal naming all three fields.
    # #2803 made it derive from `field_tiers.strip_map()`, so it no longer names any of
    # them and discovery no longer finds it. That is the intended end state, not a gap:
    # the strip is now structural, and adding a Tier-2 field to the registry strips it
    # there with no edit. A phantom entry here would red the no-rot assertion.
    ("lambdas/web/site_api_vitals_depth.py", "vascular_age"): _d(
        EXCLUDED,
        "Public surface. The string appears ONLY as a declined-panel identifier in the "
        "reason payload ('panel': 'vascular_age') — the endpoint tells the reader a "
        "panel was withheld and names which one. No value is read, and naming a "
        "withheld panel is the opposite of publishing it.",
    ),
}


# ── The derivation ────────────────────────────────────────────────────────────
def _scan_dirs() -> tuple[str, ...]:
    return ("lambdas", "mcp")


def scan_source(rel_path: str, source: str, vocabulary: frozenset[str]) -> set[str]:
    """Every Tier-2 field name mentioned anywhere in one module's AST.

    Catches the four shapes a field name takes in this repo: a string constant (dict
    keys, `.get("field")`, map values), an attribute (`row.field`), a bare Name, and a
    keyword-argument name. Comments are NOT scanned — a comment is not a consumer, and
    counting them would make every SCHEMA cross-reference a finding.
    """
    found: set[str] = set()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return found
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in vocabulary:
            found.add(node.value)
        elif isinstance(node, ast.Attribute) and node.attr in vocabulary:
            found.add(node.attr)
        elif isinstance(node, ast.Name) and node.id in vocabulary:
            found.add(node.id)
        elif isinstance(node, ast.keyword) and node.arg in vocabulary:
            found.add(node.arg)
    return found


def scan_tree(repo: str = REPO) -> dict[tuple[str, str], str]:
    """`{(rel_path, field): family}` for every Tier-2 mention under lambdas/ and mcp/.

    `lambdas/privacy/field_tiers.py` is skipped: it DECLARES the vocabulary, so every
    field name necessarily appears there and it is not a consumer of anything.
    """
    vocabulary = fields_at_tier(TIER_OWNER_ONLY)
    out: dict[tuple[str, str], str] = {}
    if not vocabulary:
        return out
    for top in _scan_dirs():
        root_dir = os.path.join(repo, top)
        for dirpath, dirnames, filenames in os.walk(root_dir):
            dirnames[:] = [d for d in dirnames if d not in {"__pycache__", ".pytest_cache"}]
            for name in filenames:
                if not name.endswith(".py"):
                    continue
                full = os.path.join(dirpath, name)
                rel = os.path.relpath(full, repo).replace(os.sep, "/")
                if rel == "lambdas/privacy/field_tiers.py":
                    continue
                try:
                    with open(full, encoding="utf-8") as fh:
                        source = fh.read()
                except OSError:
                    continue
                for field in scan_source(rel, source, vocabulary):
                    out[(rel, field)] = family_of(rel)
    return out
