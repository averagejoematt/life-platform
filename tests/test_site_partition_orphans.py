"""tests/test_site_partition_orphans.py — orphan read-partition guard (#1218).

The #1218 incident: /method/benchmarks read DDB partition
`USER#matthew#SOURCE#benchmarks` — a partition with NO writer anywhere in the
codebase (Count=0 even unfiltered) — while promising the reader it would
"re-populate from the current genesis." An endpoint that reads a partition
nothing ever writes is a permanently-empty surface masquerading as data.

This guard makes that a standing check rather than a manual discovery: every
`SOURCE#<name>` partition READ by the site-API (`lambdas/web/`) must have a
WRITER somewhere in the producer code (`lambdas/`, `mcp/`, `deploy/`,
`scripts/`), or the source name must be on ALLOWLIST_ORPHANS below WITH a
reason. Adding a name to the allowlist is a recorded decision — the honesty
test prunes any entry that has since gained a writer.

Detection is static (AST) and recognises the two pk-construction forms in use:
  * a string constant carrying `...#SOURCE#<name>` (literals and f-string chunks
    like `f"USER#{USER_ID}#SOURCE#life_events"`), and
  * a USER_PREFIX join — `f"{USER_PREFIX}whoop"` / `USER_PREFIX + "dexa"` —
    where `USER_PREFIX == "USER#matthew#SOURCE#"`.
Fully-dynamic writes (`f"{USER_PREFIX}{partition}"`) contribute no static name
by design, so a source reachable only through a dynamic writer is treated as
unresolved and belongs on the allowlist with that reason.

Non-vacuity: `benchmarks` is a real orphan today (proven by
`test_benchmarks_is_a_real_orphan`); remove its ALLOWLIST_ORPHANS entry and
`test_no_unlisted_orphan_read_partitions` reds.
"""

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "lambdas" / "web"
PRODUCER_DIRS = [ROOT / "lambdas", ROOT / "mcp", ROOT / "deploy", ROOT / "scripts"]

# phase_taxonomy.py classifies every SOURCE name (a bare-key registry) but writes
# nothing — excluding it keeps a classification entry from masquerading as a writer.
REFERENCE_ONLY = {"phase_taxonomy.py"}

_SOURCE_RE = re.compile(r"SOURCE#([a-z0-9_]+)")
_USER_PREFIX = re.compile(r"USER_PREFIX")
_LEADING_NAME = re.compile(r"^([a-z0-9_]+)")

# Read partitions with no statically-resolvable writer. Each entry is a recorded
# decision; test_allowlist_stays_honest prunes any that gains a writer.
ALLOWLIST_ORPHANS = {
    # RETIRED (#1218): SOURCE#benchmarks has no writer anywhere — BENCH-1 writes
    # weight_episodes/training_reference, never this partition. This PR retired the
    # Wednesday-chronicle hook and the "will re-populate" empty-state copy. Remove
    # this entry only once a real writer for the partition ships.
    "benchmarks": "#1218 — retired: no writer exists; chronicle hook + empty-state copy fixed in this PR",
    # Pre-existing orphans surfaced by this new guard, OUT OF SCOPE for #1218 —
    # allowlisted so the guard lands green; each warrants its own follow-up.
    "meal_responses": "pre-existing orphan (out of #1218 scope): /api/meal_responses reads SOURCE#meal_responses "
    "but the CGM x MacroFactor join that would write it was never built — no writer anywhere",
    "state_of_mind": "pre-existing orphan (out of #1218 scope): the reader queries SOURCE#state_of_mind, but HAE "
    "merges State-of-Mind aggregates into SOURCE#apple_health (merge_day_to_dynamo), so the dedicated partition "
    "has no writer",
}


def _pkform_tokens(node: ast.AST) -> set[str]:
    """SOURCE source-names appearing in a subtree via the two pk-construction forms."""
    names: set[str] = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            names.update(_SOURCE_RE.findall(n.value))
        if isinstance(n, ast.JoinedStr):
            vals = n.values
            for i, v in enumerate(vals):
                if isinstance(v, ast.FormattedValue) and i + 1 < len(vals):
                    ref = v.value.id if isinstance(v.value, ast.Name) else (v.value.attr if isinstance(v.value, ast.Attribute) else "")
                    nxt = vals[i + 1]
                    if _USER_PREFIX.search(ref) and isinstance(nxt, ast.Constant) and isinstance(nxt.value, str):
                        m = _LEADING_NAME.match(nxt.value)
                        if m:
                            names.add(m.group(1))
        if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Add):
            left = n.left
            ref = left.id if isinstance(left, ast.Name) else (left.attr if isinstance(left, ast.Attribute) else "")
            if _USER_PREFIX.search(ref) and isinstance(n.right, ast.Constant) and isinstance(n.right.value, str):
                m = _LEADING_NAME.match(n.right.value)
                if m:
                    names.add(m.group(1))
    return names


def _parse(path: Path) -> ast.AST | None:
    try:
        return ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError, ValueError):
        return None


def _read_partitions() -> set[str]:
    """SOURCE names the site-API reads — any pk-form across lambdas/web/."""
    out: set[str] = set()
    for p in WEB.rglob("*.py"):
        tree = _parse(p)
        if tree is not None:
            out |= _pkform_tokens(tree)
    return out


def _writer_partitions() -> set[str]:
    """SOURCE names with a writer: any pk-form in producer code, plus site-API
    self-writes (the interactive votes/follows/suggestions put_item/update_item)."""
    out: set[str] = set()
    seen: set[Path] = set()
    for base in PRODUCER_DIRS:
        for p in base.rglob("*.py"):
            if p in seen or WEB in p.parents or p.name in REFERENCE_ONLY:
                continue
            seen.add(p)
            tree = _parse(p)
            if tree is not None:
                out |= _pkform_tokens(tree)
    for p in WEB.rglob("*.py"):
        tree = _parse(p)
        if tree is None:
            continue
        for n in ast.walk(tree):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in {"put_item", "update_item"}:
                out |= _pkform_tokens(n)
    return out


def test_no_unlisted_orphan_read_partitions():
    reads = _read_partitions()
    writers = _writer_partitions()
    orphans = sorted(s for s in reads if s not in writers and s not in ALLOWLIST_ORPHANS)
    assert not orphans, (
        f"site-API reads SOURCE partitions with no writer: {orphans} — ship a writer, or if the "
        "endpoint is retired/pre-launch add the name to ALLOWLIST_ORPHANS with a reason (see #1218)"
    )


def test_benchmarks_is_a_real_orphan():
    """Non-vacuity: benchmarks must be READ and have NO writer — so dropping its
    ALLOWLIST_ORPHANS entry genuinely reds test_no_unlisted_orphan_read_partitions."""
    reads = _read_partitions()
    writers = _writer_partitions()
    assert "benchmarks" in reads, "benchmarks no longer read by the site-API — prune it from ALLOWLIST_ORPHANS"
    assert "benchmarks" not in writers, "benchmarks gained a writer — remove it from ALLOWLIST_ORPHANS and delete the retirement"


def test_allowlist_stays_honest():
    """An ALLOWLIST_ORPHANS entry must still be a genuine orphan (read, no writer)."""
    reads = _read_partitions()
    writers = _writer_partitions()
    for name, reason in ALLOWLIST_ORPHANS.items():
        assert name in reads, f"ALLOWLIST_ORPHANS has a dead entry {name!r} ({reason}) — no site-API endpoint reads it; prune it"
        assert name not in writers, f"ALLOWLIST_ORPHANS entry {name!r} now has a writer ({reason}) — the flag is stale; prune it"
