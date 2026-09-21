"""tests/test_scoped_writer_provenance_guard_3599.py — the per-entrant scoped-writer guard (#3599 box 2).

WHAT THIS IS
  The #2119 guard asserts that a writer landing a NEW row on `COACH#`/`ENSEMBLE#` calls
  `experiment_stamp()`. Its scope is those two prefixes and nothing else, which leaves the
  partitions the 2026-09-05 forensic RCA actually indicted — the `USER#matthew#SOURCE#*`
  EXPERIMENT_SCOPED families — with no writer-side contract at all. #3513 (`insight_writer`
  never adopted a stamp; measured live at 109 unstamped rows), #3877 (the nudge writer) and
  this box are all the same shape. This file is that contract for the SOURCE tier.

WHAT A "SCOPED SOURCE WRITER" IS, AND WHO RULES ON IT
  A producer-dir function that calls `<expr>.put_item(...)` and names a `#SOURCE#<name>`
  family, where THE LIVE CENSUS says that family is EXPERIMENT_SCOPED. The ruling comes
  from `deploy/generated/pk_family_census.json`'s measured representative row — a real pk
  and a real sk off the live table — never from a synthetic sk invented here. That matters:
  `classify()` is sk-dependent, so grading `COACH#outbound_events` against a made-up
  `DATE#…` sk returns EXPERIMENT_SCOPED while its real `EVENT#…` rows are SYSTEM_STATE.
  A guard that invents its own fixture invents its own defects (fixture-must-be-the-wire).

THE THREE PROVENANCE CLASSES (the distinction is the point, #3598)
  * `stamped`      — `experiment_stamp_for` / `experiment_stamp` / `tag_record`, directly or
                     through a same-module private delegate. All three derive the phase from
                     the WRITE'S OWN DATE, so a countdown-window write cannot claim the
                     experiment it precedes.
  * `hand-stamped` — a literal `"phase"` key the writer sets itself. Not nothing, and not the
                     contract either: `{"phase": "experiment"}` written between the wipe and
                     genesis is exactly the row #3598 retired the constant default for.
  * `none`         — no provenance. The row relies entirely on the reset-time tagger.

  `none` and `hand-stamped` both require a dated ledger line. Green means "stamped", or
  "waived, with a reason, a condition and an expiry".

WHAT THE GUARD CAN AND CANNOT SEE — measured, not asserted
  `reach_census()` is the honest version of the #3877 measurement comment, re-run with THIS
  guard's helpers. A pk assembled purely at runtime (a parameter, a dict field, a helper
  return) is invisible to any AST rule, and this file does not pretend otherwise:
  `test_a_runtime_assembled_pk_is_unobserved_by_this_guard` is an `xfail(strict=True)`, so
  the blind spot is a recorded fact that reds the day someone closes it and forgets to say
  so. What this guard DID close relative to #2119's helpers is the one-hop cases: the
  `#SOURCE#<name>` fragment inside an f-string whose user segment is a variable, and a
  module-level pk constant (`insight_writer._PK`) referenced by the writer.

WHY PRE-MERGE (tests/conftest.py::_PREMERGE_EXTRA_FILES)
  The verdict depends only on the repo tree, and the defect is introduced by the very PR
  that adds a writer. Post-merge is after the unstamped rows exist.
"""

from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PRODUCER_DIRS = [ROOT / "lambdas", ROOT / "mcp", ROOT / "deploy", ROOT / "scripts"]
EXCLUDED_DIRS = [ROOT / "deploy" / "archive"]  # retired one-shots, same exclusion as #2119
CENSUS_ARTIFACT = ROOT / "deploy" / "generated" / "pk_family_census.json"

from scoped_writer_residue_3599 import SCOPED_WRITER_RESIDUE, SEED_DATE  # noqa: E402

# The stamping calls that satisfy the contract. Same vocabulary as the #2119 guard plus
# `tag_record` — the compute tier's equivalent chokepoint (it resolves `phase` from the
# write's own date and is what #3513 named as the thing insight_writer never adopted).
STAMP_CALLS = ("experiment_stamp", "experiment_stamp_for", "tag_record")

# Derived, not typed: the marker a `USER#…#SOURCE#<name>` pk is built from. Re-derived from
# `pk_census.TAGGER_REACHABLE_PREFIX` in test_the_waiver_condition_is_re_derived below, so
# the ledger's waiver condition ("these partitions are reachable by the reset-time tagger")
# cannot rot into prose while the constant it depends on moves.
SOURCE_MARKER = "#SOURCE#"
_SOURCE_RE = re.compile(re.escape(SOURCE_MARKER) + r"([A-Za-z0-9_]+)")


@dataclass(frozen=True)
class Writer:
    """One producer function that lands a row on an EXPERIMENT_SCOPED SOURCE partition."""

    key: str  # "<path>::<function>"
    sources: tuple  # the SOURCE families it names, sorted
    provenance: str  # "stamped" | "hand-stamped" | "none"


# ── AST helpers ──────────────────────────────────────────────────────────────


def _str_chunks(node: ast.AST) -> list[str]:
    """The literal string pieces of a Constant or an f-string. An f-string's literal
    chunks survive its runtime holes, which is why `f"USER#{uid}#SOURCE#chronicle"` is
    readable here while its full pk value is not."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.JoinedStr):
        return [v.value for v in node.values if isinstance(v, ast.Constant) and isinstance(v.value, str)]
    return []


def _all_chunks(node: ast.AST) -> list[str]:
    out: list[str] = []
    for n in ast.walk(node):
        out += _str_chunks(n)
    return out


def _string_bindings(tree: ast.AST) -> dict:
    """name -> literal string chunks, for every module-scoped string assignment in the
    file — the ONE hop this guard resolves. Includes assignments made inside a function
    (the `global _PK; _PK = f"…"` initialiser shape `content/insight_writer.py` uses),
    because the binding is module-scoped wherever the statement sits. First binding wins;
    a name rebound to two different partitions is not a shape this repo has."""
    out: dict = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
            chunks = _str_chunks(n.value)
            if chunks:
                out.setdefault(n.targets[0].id, chunks)
        if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name) and n.value is not None:
            chunks = _str_chunks(n.value)
            if chunks:
                out.setdefault(n.target.id, chunks)
    return out


def _functions(tree: ast.AST) -> dict:
    out: dict = {}
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out[n.name] = n
    return out


def _put_item_calls(node: ast.AST) -> list:
    return [n for n in ast.walk(node) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "put_item"]


def _private_delegates(node: ast.AST) -> list:
    return [n for n in ast.walk(node) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id.startswith("_")]


def _stamps_directly(node: ast.AST) -> bool:
    """True iff a STAMP_CALLS call node appears in the subtree. AST, not substring — a
    docstring that merely mentions `experiment_stamp()` is not a stamp."""
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Name) and f.id in STAMP_CALLS:
                return True
            if isinstance(f, ast.Attribute) and f.attr in STAMP_CALLS:
                return True
    return False


def _hand_stamps(node: ast.AST) -> bool:
    """True iff the function writes a literal `phase` key itself — `{"phase": …}` or
    `item["phase"] = …`."""
    for n in ast.walk(node):
        if isinstance(n, ast.Dict):
            for k in n.keys:
                if isinstance(k, ast.Constant) and k.value == "phase":
                    return True
        if isinstance(n, ast.Subscript):
            s = n.slice
            if isinstance(s, ast.Constant) and s.value == "phase":
                return True
    return False


def _provenance(fn: ast.AST, functions: dict) -> str:
    """The provenance class of one writer, resolving one hop into a same-module private
    delegate (the `_stamp(pk, sk)` / `_put_item(...)` pattern the coach tier uses)."""
    if _stamps_directly(fn):
        return "stamped"
    for call in _private_delegates(fn):
        callee = functions.get(call.func.id)
        if callee is not None and _stamps_directly(callee):
            return "stamped"
    return "hand-stamped" if _hand_stamps(fn) else "none"


# ── the scan ─────────────────────────────────────────────────────────────────


def scoped_source_classes() -> dict:
    """{source_name: class} from the COMMITTED live census — the measured ruling on which
    SOURCE families are EXPERIMENT_SCOPED. Refuses an artifact that cannot rule (a guard
    whose population is empty is a guard that passes by having nothing to check)."""
    families = (json.loads(CENSUS_ARTIFACT.read_text(encoding="utf-8")) or {}).get("families") or {}
    classes = {fam.split("#", 1)[1]: facet.get("class") for fam, facet in families.items() if fam.startswith("SOURCE#")}
    scoped = [s for s, c in classes.items() if c == "experiment_scoped"]
    assert (
        len(scoped) >= 20
    ), f"only {len(scoped)} EXPERIMENT_SCOPED SOURCE families in the committed census — truncated, not the live table"
    return classes


def scan_module(rel_path: str, src: str, classes: dict) -> list:
    """Every scoped-source writer in ONE module's source text. The single core the repo
    sweep and the scratch-module controls both run — a control that exercised a private
    copy would prove nothing about what ships."""
    try:
        tree = ast.parse(src)
    except (SyntaxError, ValueError):
        return []
    functions = _functions(tree)
    bindings = _string_bindings(tree)
    out: list = []
    for name, fn in functions.items():
        if not _put_item_calls(fn):
            continue
        chunks = _all_chunks(fn)
        for n in ast.walk(fn):
            if isinstance(n, ast.Name) and n.id in bindings:
                chunks += bindings[n.id]
        sources = {s for chunk in chunks for s in _SOURCE_RE.findall(chunk)}
        scoped = tuple(sorted(s for s in sources if classes.get(s) == "experiment_scoped"))
        if scoped:
            out.append(Writer(key=f"{rel_path}::{name}", sources=scoped, provenance=_provenance(fn, functions)))
    return out


def _producer_files() -> list:
    seen: list = []
    for base in PRODUCER_DIRS:
        for path in sorted(base.rglob("*.py")):
            if any(excl in path.parents for excl in EXCLUDED_DIRS) or path in seen:
                continue
            seen.append(path)
    return seen


def scan_repo(classes: dict | None = None) -> list:
    classes = classes if classes is not None else scoped_source_classes()
    out: list = []
    for path in _producer_files():
        try:
            src = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        out += scan_module(path.relative_to(ROOT).as_posix(), src, classes)
    return sorted(out, key=lambda w: w.key)


def reach_census() -> dict:
    """What this guard can and cannot see, measured with its OWN helpers — the #3877
    comment's census, re-run. `put_item_functions` is the denominator; `pk_visible` is
    every writer naming a resolvable `#SOURCE#` family; `blind` is the remainder, whose
    pk exists only at runtime."""
    total = visible = 0
    blind_stamped = blind_unstamped = 0
    for path in _producer_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, ValueError, UnicodeDecodeError, OSError):
            continue
        functions = _functions(tree)
        bindings = _string_bindings(tree)
        for fn in functions.values():
            if not _put_item_calls(fn):
                continue
            total += 1
            chunks = _all_chunks(fn)
            for n in ast.walk(fn):
                if isinstance(n, ast.Name) and n.id in bindings:
                    chunks += bindings[n.id]
            if any(_SOURCE_RE.findall(chunk) for chunk in chunks):
                visible += 1
            elif _provenance(fn, functions) == "stamped":
                blind_stamped += 1
            else:
                blind_unstamped += 1
    return {
        "put_item_functions": total,
        "source_pk_visible": visible,
        "blind_stamped": blind_stamped,
        "blind_unstamped": blind_unstamped,
    }


# ── the verdict ──────────────────────────────────────────────────────────────


def findings(writers: list, residue: dict, today: str) -> list:
    """Every reason this guard would red, as readable strings. Four clauses:

    1. an unstamped/hand-stamped scoped writer with NO ledger line (the entrant rule);
    2. a ledger line past its `expires` date (a waiver is a claim with an expiry);
    3. a ledger line whose writer now stamps, or no longer exists (the SHRINK consumer —
       without it the ledger goes stale in the good direction and disarms the gate, which
       is precisely how the a11y baseline rotted);
    4. a ledger line whose recorded provenance class no longer matches what the writer
       does (an `none` waiver silently becoming a hand-stamp is a different decision).
    """
    out: list = []
    by_key = {w.key: w for w in writers}
    for w in writers:
        if w.provenance == "stamped":
            continue
        entry = residue.get(w.key)
        if entry is None:
            out.append(
                f"UNRESIDUED {w.key} writes EXPERIMENT_SCOPED {list(w.sources)} with provenance={w.provenance!r} — "
                "stamp it via experiment_stamp_for/tag_record, or add a dated line to tests/scoped_writer_residue_3599.py"
            )
            continue
        if entry["expires"] < today:
            out.append(
                f"EXPIRED residue line {w.key} expired {entry['expires']} (today {today}) — stamp the writer or re-decide the waiver"
            )
        if entry["provenance"] != w.provenance:
            out.append(f"CHANGED {w.key} was waived as provenance={entry['provenance']!r} and is now {w.provenance!r} — re-read the waiver")
    for key, entry in residue.items():
        w = by_key.get(key)
        if w is None:
            out.append(f"STALE residue line {key} — that writer no longer writes a scoped SOURCE partition; delete the line")
        elif w.provenance == "stamped":
            out.append(f"STALE residue line {key} — that writer stamps now; delete the line (this is the ledger shrinking)")
    return sorted(out)


def _today() -> str:
    return date.today().isoformat()


# ── the real tree ────────────────────────────────────────────────────────────


def test_every_scoped_source_writer_stamps_or_carries_a_dated_waiver():
    """The Set guard. A new writer landing an unstamped row on an EXPERIMENT_SCOPED
    SOURCE partition reds on the PR that adds it."""
    writers = scan_repo()
    assert len(writers) >= 15, f"only {len(writers)} scoped source writers found — the sweep has gone blind, not the repo clean"
    problems = findings(writers, SCOPED_WRITER_RESIDUE, _today())
    assert not problems, "scoped-writer provenance (#3599 box 2):\n  " + "\n  ".join(problems)


def test_the_census_rules_the_class_not_a_synthetic_sk():
    """The ruling is the live census's, and it is not "everything under SOURCE# is
    scoped": `platform_memory` is CROSS_PHASE on the same measured artifact, so a guard
    that flagged every SOURCE writer would be flagging rows whose correct stamp is {}."""
    classes = scoped_source_classes()
    assert classes.get("insights") == "experiment_scoped"
    assert classes.get("chronicle") == "experiment_scoped"
    assert classes.get("platform_memory") == "cross_phase"


def test_insight_writer_the_3513_fix_is_visible_through_the_one_hop_constant():
    """#3513's shipped fix is a real fixed instance of this class, and the ONLY reason
    this guard can see it is the module-constant hop (`_PK` is bound in `init()`, never in
    the writer's own body). Without that hop the writer is invisible and a regression
    there would be silent — the exact thing #3877 measured and could not fix."""
    src = (ROOT / "lambdas" / "content" / "insight_writer.py").read_text(encoding="utf-8")
    writers = {w.key: w for w in scan_module("lambdas/content/insight_writer.py", src, scoped_source_classes())}
    w = writers.get("lambdas/content/insight_writer.py::write_insight")
    assert w is not None, "write_insight is no longer visible to the guard — the one-hop pk resolution regressed"
    assert w.sources == ("insights",)
    assert w.provenance == "stamped"


def test_the_waiver_condition_is_re_derived_from_the_tagger_constant():
    """Every ledger line's condition is "this partition is reachable by the reset-time
    tagger, so an in-cycle unstamped row is corrected at the next reset". That condition
    is re-derived from `pk_census.TAGGER_REACHABLE_PREFIX` rather than restated: if the
    tagger's reach is ever narrowed, these waivers stop being true and this reds."""
    import sys

    sys.path.insert(0, str(ROOT / "lambdas"))
    from experiment.pk_census import TAGGER_REACHABLE_PREFIX

    assert TAGGER_REACHABLE_PREFIX.endswith(SOURCE_MARKER), (
        f"the reset-time tagger no longer reaches {SOURCE_MARKER} partitions "
        f"({TAGGER_REACHABLE_PREFIX!r}) — every line in tests/scoped_writer_residue_3599.py rests on that and must be re-decided"
    )


# ── the ledger's own shape ───────────────────────────────────────────────────


def test_every_residue_line_is_dated_reasoned_and_expiring():
    defects = []
    for key, entry in SCOPED_WRITER_RESIDUE.items():
        for field_name in ("seeded", "expires", "reason", "provenance", "sources"):
            if not entry.get(field_name):
                defects.append(f"{key}: missing {field_name}")
        try:
            date.fromisoformat(entry["expires"])
            date.fromisoformat(entry["seeded"])
        except (KeyError, ValueError):
            defects.append(f"{key}: unparseable seeded/expires")
        if len(entry.get("reason", "")) < 40:
            defects.append(f"{key}: reason too short to be a decision")
        if entry.get("provenance") not in ("none", "hand-stamped"):
            defects.append(f"{key}: provenance {entry.get('provenance')!r} is not a waivable class")
    assert not defects, "tests/scoped_writer_residue_3599.py is malformed:\n  " + "\n  ".join(defects)
    assert SCOPED_WRITER_RESIDUE, "the ledger is empty — delete it and this gate's residue clauses rather than keeping a dead ledger"


def test_the_ledger_only_waives_writers_that_are_really_there():
    """Same honesty check the #2119 allowlist has: a line naming a writer the sweep does
    not find is stale, and stale lines are how a waiver ledger goes quiet."""
    keys = {w.key for w in scan_repo()}
    missing = sorted(k for k in SCOPED_WRITER_RESIDUE if k not in keys)
    assert not missing, f"residue lines with no live writer: {missing}"


# ── non-vacuity: the three legs box 2 names, on the wire shape ───────────────
#
# The pk in each scratch module is the REAL one from the census artifact
# (`USER#matthew#SOURCE#insights`), not a made-up partition, and each control runs
# `scan_module` — the same function the repo sweep runs.

_SCRATCH_UNSTAMPED = '''
def _write_scratch_insight(table, insight_id, text):
    """A scratch writer with no provenance at all — the #3513 defect, reconstructed."""
    item = {
        "pk": "USER#matthew#SOURCE#insights",
        "sk": f"INSIGHT#{insight_id}",
        "text": text,
        "status": "open",
    }
    table.put_item(Item=item)
'''

_SCRATCH_TAGGED = '''
def _write_scratch_insight(table, insight_id, text):
    """The same writer wrapped in tag_record — the contract satisfied."""
    from common.compute_metadata import tag_record

    item = tag_record(
        {
            "pk": "USER#matthew#SOURCE#insights",
            "sk": f"INSIGHT#{insight_id}",
            "text": text,
            "status": "open",
        },
        source_id="insights",
    )
    table.put_item(Item=item)
'''

_SCRATCH_RUNTIME_PK = '''
def _write_scratch_row(table, pk, insight_id, text):
    """The pk arrives as an ARGUMENT. Same partition at runtime, no literal anywhere —
    the shape no AST rule can rule on."""
    table.put_item(Item={"pk": pk, "sk": f"INSIGHT#{insight_id}", "text": text})
'''


def test_a_scratch_writer_to_source_insights_with_no_stamp_is_flagged():
    """Box 2 leg 1 — red."""
    writers = scan_module("scratch/insights_writer.py", _SCRATCH_UNSTAMPED, scoped_source_classes())
    assert [w.provenance for w in writers] == ["none"], writers
    problems = findings(writers, {}, _today())
    assert any("UNRESIDUED scratch/insights_writer.py::_write_scratch_insight" in p for p in problems), problems


def test_the_same_scratch_writer_wrapped_in_tag_record_is_green():
    """Box 2 leg 2 — green. Same module, same partition, one call different."""
    writers = scan_module("scratch/insights_writer.py", _SCRATCH_TAGGED, scoped_source_classes())
    assert [w.provenance for w in writers] == ["stamped"], writers
    assert findings(writers, {}, _today()) == []


def test_an_expired_residue_seam_reds():
    """Box 2 leg 3 — a waiver that has run out is a finding, not a permanent pass. Graded
    on the same day-string comparison the live clause uses, so this control and the real
    check cannot drift apart."""
    writers = scan_module("scratch/insights_writer.py", _SCRATCH_UNSTAMPED, scoped_source_classes())
    key = "scratch/insights_writer.py::_write_scratch_insight"
    expired = {key: {"seeded": "2026-01-01", "expires": "2026-06-30", "provenance": "none", "sources": ("insights",), "reason": "x" * 41}}
    live = {key: {"seeded": "2026-01-01", "expires": "2099-01-01", "provenance": "none", "sources": ("insights",), "reason": "x" * 41}}
    assert any(p.startswith("EXPIRED") for p in findings(writers, expired, "2026-09-21")), findings(writers, expired, "2026-09-21")
    assert findings(writers, live, "2026-09-21") == []


def test_a_waived_writer_that_starts_stamping_is_named_for_pruning():
    """The consumer of the shrink list: the ledger cannot go quiet in the good direction.
    (The RCA's a11y-3 mechanism — a baseline whose cured entries nobody deletes.)"""
    writers = scan_module("scratch/insights_writer.py", _SCRATCH_TAGGED, scoped_source_classes())
    key = "scratch/insights_writer.py::_write_scratch_insight"
    ledger = {key: {"seeded": "2026-09-21", "expires": "2099-01-01", "provenance": "none", "sources": ("insights",), "reason": "x" * 41}}
    assert any(p.startswith("STALE") for p in findings(writers, ledger, "2026-09-21"))


def test_a_hand_written_phase_key_is_not_counted_as_a_stamp():
    """#3598's class kept separate from `none`: a literal phase the writer types itself
    can claim the experiment for a pre-genesis write, so it is waivable, never green."""
    src = _SCRATCH_UNSTAMPED.replace('"status": "open",', '"status": "open",\n        "phase": "experiment",')
    writers = scan_module("scratch/insights_writer.py", src, scoped_source_classes())
    assert [w.provenance for w in writers] == ["hand-stamped"], writers
    assert any(p.startswith("UNRESIDUED") for p in findings(writers, {}, _today()))


@pytest.mark.xfail(
    strict=True, reason="UNOBSERVED (#3599): a pk assembled only at runtime is invisible to any AST rule — see reach_census()"
)
def test_a_runtime_assembled_pk_is_unobserved_by_this_guard():
    """The blind spot, recorded as a failing expectation rather than an absence. If a
    future widening resolves this shape, this test XPASSes and `strict=True` reds — the
    guard's stated reach and its real reach cannot drift apart silently."""
    writers = scan_module("scratch/runtime_pk.py", _SCRATCH_RUNTIME_PK, scoped_source_classes())
    assert writers, "a runtime-assembled pk is now visible"


def test_the_guards_reach_is_measured_and_still_partial():
    """The number in the PR body has a home in the tree. This asserts the SHAPE of the
    measurement (a real denominator, a real blind set), not the exact figures, which move
    with every writer added — the figures are what `reach_census()` prints on demand."""
    census = reach_census()
    assert census["put_item_functions"] >= 150, census
    assert census["source_pk_visible"] >= 40, census
    assert census["blind_unstamped"] > 0, "the blind set is empty — either the repo changed profoundly or this measurement broke"


def test_the_seed_date_is_not_in_the_future():
    """A ledger sealed in the future would waive writers nobody has looked at, and would
    make every `seeded` date meaningless as provenance."""
    assert date.fromisoformat(SEED_DATE) <= date.today()
    assert all(
        entry["seeded"] == SEED_DATE for entry in SCOPED_WRITER_RESIDUE.values()
    ), "a line dated off the seal must carry its own reason"
