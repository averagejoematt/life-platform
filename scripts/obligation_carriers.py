#!/usr/bin/env python3
"""scripts/obligation_carriers.py — a waiver, deferral or residue ledger carries a condition,
an expiry and a carrier, and the calendar probes it (#3597, epic #3592).

THE CLASS (root-cause class 7 of the 2026-09-05 forensic RCA — 15 member findings)
  A waiver, citation, exemption or deferral outlives its condition and has no carrier.
  `docs/PROPORTIONALITY.md` recorded two demote triggers that fired unnoticed for a month; a
  `fresh-eyes` row's own revisit trigger fired on 2026-07-26 and nobody noticed for a month;
  #2877's "fast-follow, not done here" for whoop/habitify was never ticketed (INT-3, fixed
  only when #3504 re-found it); and every residue ledger the review panel proposed would be
  this class on landing. The instances were each fixed; nothing owned the class.

THE RULE — three parts, one module, each part a registry with a derivation guard
  1. OBLIGATION VOCABULARY (`OBLIGATION_CUE_RE`). A block on a governed surface
     (`OBLIGATION_SURFACES`: the ADRs, the proportionality ledger, the alarm-citation
     registry) that states an obligation — `revisit`, `fast-follow`, `owner decides`, or a
     deferral to `later` / `step N` / `phase N` — must carry a HOME: a carrier `#N`, the
     `not-work — <home>` tag (the #1340 grammar, imported), or a DATE that the calendar
     probes. A date nobody probes is a wish; so a dated obligation is homed only when
     (surface, date) is registered in `DATED_OBLIGATIONS`, whose entries the daily calendar
     sweep reds once past (`scripts/operating_calendar.py --due`, exit 5), and whose window
     is capped at `MAX_EXPIRY_DAYS` so "revisit 2031-01-01" cannot be a home either.
     The same vocabulary is composed into the closure contract's residual cue
     (`scripts/closure_contract.RESIDUAL_CUE_RE`), whose `unhomed-residual` code is armed
     BLOCK by this issue — a closing comment saying "fast-follow" with no `#N` is the #2877
     shape on the surface where it happened.

     STRUCTURAL, NOT PHRASE-SUPPRESSED (the #2959 lesson). The cue only NOMINATES a block;
     the verdict is the structural presence of a home, exactly `check_residual_queue`'s
     "every bullet carries #N or not-work" rule. Bare `later` and bare `step N` are NOT cues:
     measured on 2026-09-23 they appear 40 and 5 times in DECISIONS.md, almost all narrative
     ("later that week", "step 4 of the wrap") — they are cues only inside a deferral
     construction (`deferred to later`, `parked until step 4`). Past tense (`revisited`) is
     history, not an obligation, and is not a cue.

     Pre-existing unhomed obligations are pinned, content-keyed and shrink-only, in
     `tests/obligation_residue_3597.py::OBLIGATION_RESIDUE` (the conformance-residue
     precedent): editing a pinned block re-keys it, and the only green path is a home.

  2. THE RESIDUE REGISTRY (`RESIDUE_LEDGERS`). Every residue/allowlist ledger — a
     dated, shrink-only record of accepted debt — is registered with a `carrier` (#N, the
     issue that owns draining it), a `condition` (what empties or retires it), an `expires`
     date (≤ MAX_EXPIRY_DAYS after `declared`; past it the calendar reds and the entry must
     be re-reviewed and re-dated or the ledger drained) and a `consumer` (the test that
     holds it shrink-only). The derivation guard: every module-level binding named
     `*_RESIDUE` in a tracked first-party Python file (`discover_residue_ledgers`) must be
     registered — a new ledger that is not reds — and every registered symbol must exist
     (no phantoms). Ledgers whose name predates the convention (`mypy_clean_set.DIRTY`, the
     a11y baseline JSON) are registered by hand in the same dict.

  3. THE PROBE (`expired_carriers`). One pure function the operating calendar's daily
     dead-man calls: every registry entry and every dated obligation past its expiry. It
     is time-based on purpose and lives ONLY in the scheduled sweep — never in the unit
     suite, where a calendar date would red whichever innocent PR ran next (#2975).

THE DATE GRAMMAR IS NOT RE-TYPED HERE. `parse_day_literal` / `is_past` are imported from
`lambdas/operational/proof_probe.py` (#4022), whose `## Proof probe` block's `expires:`
line this rule generalises — one day parser for every expiry in the closure layer.

USAGE
  python3 scripts/obligation_carriers.py            # the live report: unhomed / pinned / registry
  python3 scripts/obligation_carriers.py --keys     # print the current unhomed keys (seeding aid)
  python3 scripts/obligation_carriers.py --expired [--today YYYY-MM-DD]
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent


def _load_by_path(name: str, path: Path):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules.setdefault(name, mod)  # dataclasses resolve their module by name
    spec.loader.exec_module(mod)
    return sys.modules[name]


# The same module names closure_contract.py uses, so both scripts share ONE instance.
_PP = _load_by_path("_proof_probe_4022", ROOT / "lambdas" / "operational" / "proof_probe.py")
_RQ = _load_by_path("_check_residual_queue_1340", Path(__file__).resolve().parent / "check_residual_queue.py")
parse_day_literal = _PP.parse_day_literal  # imported, not copied (#4022)
is_past = _PP.is_past
NOT_WORK_TAG = _RQ.NOT_WORK_TAG  # `not-work —` — imported, not copied (#1340)

# ── 1. the obligation vocabulary ───────────────────────────────────────────────────────────
OBLIGATION_CUE_PATTERN = (
    r"\brevisit(?:s|ing)?\b(?!ed)"
    r"|\bre-visit\b"
    r"|\bfast[- ]?follow(?:s|-ups?)?\b"
    r"|\bowner (?:decides|to decide|will decide|must decide)\b"
    r"|\b(?:deferred|parked|punted|pushed|left) (?:to|until|for) (?:a )?(?:later\b|step \d+|phase \d+)"
)
OBLIGATION_CUE_RE = re.compile(OBLIGATION_CUE_PATTERN, re.I)
# A cue negated just before it names the ABSENCE of an obligation ("no revisit needed").
_NEGATION_RE = re.compile(r"\b(?:none|nothing|no|zero|without|not|never)\b(?:\s+\w+){0,2}\s*$", re.I)
CARRIER_RE = re.compile(r"#\d{2,6}\b")
ISO_DAY_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
MAX_EXPIRY_DAYS = 90

OBLIGATION_SURFACES: Tuple[str, ...] = (
    "docs/DECISIONS.md",
    "docs/PROPORTIONALITY.md",
    "docs/alarm_citations.json",
)

# (surface, YYYY-MM-DD) → the registration that makes a dated obligation a HOME.
# `declared` ≤ `expires` ≤ declared + MAX_EXPIRY_DAYS; the calendar reds past `expires`.
# Empty at seeding: no live obligation on a governed surface is homed by a date today.
DATED_OBLIGATIONS: Dict[Tuple[str, str], Dict[str, str]] = {}


def names_obligation(block: str) -> bool:
    """True when a block states an obligation — a cue NOT negated within two words before it."""
    for m in OBLIGATION_CUE_RE.finditer(block or ""):
        if not _NEGATION_RE.search(block[max(0, m.start() - 40) : m.start()]):
            return True
    return False


def markdown_blocks(text: str) -> List[str]:
    """The unit an obligation is stated in: each table row alone, otherwise a paragraph.

    Fenced code is skipped (a quoted example is not an obligation) and so are headings
    (a heading names a section; the paragraph under it states — and must home — the
    obligation)."""
    blocks: List[str] = []
    para: List[str] = []
    fenced = False

    def flush() -> None:
        if para:
            blocks.append("\n".join(para))
            para.clear()

    for line in (text or "").splitlines():
        if line.lstrip().startswith("```"):
            flush()
            fenced = not fenced
            continue
        if fenced:
            continue
        stripped = line.strip()
        if not stripped or re.match(r"^#{1,6}\s", stripped):
            flush()
            continue
        if stripped.startswith("|"):
            flush()
            if not re.fullmatch(r"\|[\s:|-]*\|?", stripped):
                blocks.append(stripped)
            continue
        para.append(line)
    flush()
    return blocks


def json_blocks(doc: Any) -> List[str]:
    """One block per top-level entry of a JSON registry — every string it carries, joined."""

    def strings(node: Any) -> Iterable[str]:
        if isinstance(node, str):
            yield node
        elif isinstance(node, dict):
            for v in node.values():
                yield from strings(v)
        elif isinstance(node, list):
            for v in node:
                yield from strings(v)

    if isinstance(doc, dict):
        return [f"{k}: " + " ".join(strings(v)) for k, v in doc.items() if not str(k).startswith("_")]
    return [" ".join(strings(doc))]


def surface_blocks(rel: str, text: str) -> List[str]:
    if rel.endswith(".json"):
        try:
            return json_blocks(json.loads(text))
        except ValueError:
            return [text]
    return markdown_blocks(text)


def _cue_sentence(block: str) -> str:
    """The first sentence carrying a live cue — what the residue key hashes."""
    for sentence in re.split(r"(?<=[.!?])\s+|\n", block):
        if names_obligation(sentence):
            return sentence
    return block


def obligation_key(rel: str, block: str) -> str:
    """Content key: path + a sha256 of the cue sentence, digits masked and whitespace folded.

    Digits are masked so a doc-literal sync rewriting a count in the same sentence does not
    re-key a pinned obligation (the reconcile bot edits these docs); any WORD edit re-keys it,
    and a re-keyed obligation must then be homed — the conformance-residue contract."""
    norm = re.sub(r"\d+", "0", re.sub(r"\s+", " ", _cue_sentence(block)).strip().lower())
    return f"{rel}::{hashlib.sha256(norm.encode('utf-8')).hexdigest()[:12]}"


def obligation_home(rel: str, block: str, dated: Optional[Dict[Tuple[str, str], Dict[str, str]]] = None) -> Tuple[Optional[str], str]:
    """(home, reason). home is `#N`, `not-work`, or `date:<day>`; None when unhomed.

    A date in the block is a home ONLY when (surface, date) is registered in the dated
    registry — the registration is what puts it on the calendar's daily probe."""
    registry = DATED_OBLIGATIONS if dated is None else dated
    m = CARRIER_RE.search(block)
    if m:
        return m.group(0), "carrier issue"
    if NOT_WORK_TAG.search(block):
        return "not-work", "explicit not-work tag"
    days = ISO_DAY_RE.findall(block)
    for d in days:
        if (rel, d) in registry:
            return f"date:{d}", "a registered, calendar-probed date"
    if days:
        return None, f"dated obligation ({', '.join(days[:3])}) with no calendar probe — register it in DATED_OBLIGATIONS or cite #N"
    return None, "obligation with no carrier (#N), no not-work tag and no calendar-probed date"


def unhomed_obligations(rel: str, text: str, dated: Optional[Dict[Tuple[str, str], Dict[str, str]]] = None) -> List[Tuple[str, str, str]]:
    """Pure. (key, excerpt, reason) for every obligation block on one surface with no home."""
    out: List[Tuple[str, str, str]] = []
    for block in surface_blocks(rel, text):
        if not names_obligation(block):
            continue
        home, reason = obligation_home(rel, block, dated)
        if home is None:
            out.append((obligation_key(rel, block), re.sub(r"\s+", " ", _cue_sentence(block)).strip()[:160], reason))
    return out


def live_unhomed_obligations(root: Path = ROOT) -> List[Tuple[str, str, str]]:
    out: List[Tuple[str, str, str]] = []
    for rel in OBLIGATION_SURFACES:
        path = root / rel
        if path.is_file():
            out.extend(unhomed_obligations(rel, path.read_text(encoding="utf-8")))
    return out


# ── 2. the residue registry ────────────────────────────────────────────────────────────────
RESIDUE_NAME_RE = re.compile(r"^_?[A-Z][A-Z0-9_]*_RESIDUE$")
DISCOVERY_ROOTS: Tuple[str, ...] = ("tests", "scripts", "lambdas", "deploy", "mcp", "cdk")
REQUIRED_FIELDS: Tuple[str, ...] = ("carrier", "condition", "declared", "expires", "consumer")

_SEEDED = "2026-09-23"
_REVIEW_BY = "2026-12-21"  # declared + 89 days — inside MAX_EXPIRY_DAYS
_DRAIN_CARRIER = "#4122"  # the residue-drain carrier filed with this rule (#3597's residual)

# key = `path::SYMBOL` for a Python ledger, or the file path for a data-file ledger.
RESIDUE_LEDGERS: Dict[str, Dict[str, str]] = {
    "tests/conformance_residue.py::CONFORMANCE_RESIDUE": {
        "carrier": _DRAIN_CARRIER,
        "condition": "empties when every exempted hand-typed enumeration is a registry projection (#2844)",
        "declared": _SEEDED,
        "expires": _REVIEW_BY,
        "consumer": "tests/test_conformance_guard_2844.py",
    },
    "tests/pair_seam_residue.py::PAIR_SEAM_RESIDUE": {
        "carrier": _DRAIN_CARRIER,
        "condition": "a row leaves when its seam disappears or a PairContract covers it (#2847)",
        "declared": _SEEDED,
        "expires": _REVIEW_BY,
        "consumer": "tests/test_pair_seam_conformance_2847.py",
    },
    "tests/mypy_clean_set.py::DIRTY": {
        "carrier": _DRAIN_CARRIER,
        "condition": "stays EMPTY (#1656) — a re-added module is a regression out of the type gate",
        "declared": _SEEDED,
        "expires": _REVIEW_BY,
        "consumer": "tests/test_mypy_clean_modules.py",
    },
    "tests/a11y_baseline.json": {
        "carrier": _DRAIN_CARRIER,
        "condition": "serious/critical rows each carry their own `issue` (#3548); rows leave on a harvest (#3546)",
        "declared": _SEEDED,
        "expires": _REVIEW_BY,
        "consumer": "tests/test_a11y_shrink_deadman_3546.py",
    },
    "tests/gate_census_unproven_residue.py::UNPROVEN_RESIDUE": {
        "carrier": "#3610",
        "condition": "a gate leaves when it is proven able to fail or adjudicated unprovable (#3000/#3610)",
        "declared": _SEEDED,
        "expires": _REVIEW_BY,
        "consumer": "tests/test_gate_census_lane_3000.py",
    },
    "tests/scoped_writer_residue_3599.py::SCOPED_WRITER_RESIDUE": {
        "carrier": _DRAIN_CARRIER,
        "condition": "a writer leaves when it stamps phase provenance at write time (#3599)",
        "declared": _SEEDED,
        "expires": _REVIEW_BY,
        "consumer": "tests/test_scoped_writer_provenance_guard_3599.py",
    },
    "tests/test_fixture_frame_pairing_3222.py::_PT_PAIRED_RESIDUE": {
        "carrier": _DRAIN_CARRIER,
        "condition": "a fixture leaves when its frame is paired to the clock it is read under (#3222)",
        "declared": _SEEDED,
        "expires": _REVIEW_BY,
        "consumer": "tests/test_fixture_frame_pairing_3222.py",
    },
    "tests/test_reader_truth_structural_rulings_3337.py::TIEBREAK_RESIDUE": {
        "carrier": _DRAIN_CARRIER,
        "condition": "a row leaves when its tiebreak is ruled structurally (#3337)",
        "declared": _SEEDED,
        "expires": _REVIEW_BY,
        "consumer": "tests/test_reader_truth_structural_rulings_3337.py",
    },
    "tests/test_time_invariant_helpers_1964.py::_ISO_IDIOM_RESIDUE": {
        "carrier": _DRAIN_CARRIER,
        "condition": "a site leaves when it reads the day through the time helpers (#1964)",
        "declared": _SEEDED,
        "expires": _REVIEW_BY,
        "consumer": "tests/test_time_invariant_helpers_1964.py",
    },
    "tests/test_utc_day_fleet_ratchet_2811.py::_UTC_DAY_RESIDUE": {
        "carrier": _DRAIN_CARRIER,
        "condition": "a site leaves when it reads the Pacific day, not the UTC day (#2811)",
        "declared": _SEEDED,
        "expires": _REVIEW_BY,
        "consumer": "tests/test_utc_day_fleet_ratchet_2811.py",
    },
    "tests/obligation_residue_3597.py::OBLIGATION_RESIDUE": {
        "carrier": _DRAIN_CARRIER,
        "condition": "a pinned obligation leaves when its block gains a home (#N / not-work / a probed date)",
        "declared": _SEEDED,
        "expires": _REVIEW_BY,
        "consumer": "tests/test_obligation_carriers_3597.py",
    },
}


def _tracked_py(root: Path) -> List[str]:
    try:
        out = subprocess.run(["git", "ls-files", "--", *DISCOVERY_ROOTS], cwd=root, capture_output=True, text=True, check=True).stdout
        files = [ln for ln in out.splitlines() if ln.endswith(".py")]
    except (OSError, subprocess.CalledProcessError):
        files = []
    if not files:  # not a git checkout (a tmp fixture repo) — walk the roots instead
        files = [p.relative_to(root).as_posix() for r in DISCOVERY_ROOTS for p in sorted((root / r).rglob("*.py"))]
    return sorted(f for f in files if "/node_modules/" not in f and "/cdk.out/" not in f)


def discover_residue_ledgers(root: Path = ROOT) -> List[str]:
    """Every module-level `*_RESIDUE` binding in a first-party Python file, as `path::SYMBOL`."""
    found: List[str] = []
    for rel in _tracked_py(root):
        try:
            tree = ast.parse((root / rel).read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        for node in tree.body:
            targets: List[ast.expr] = []
            if isinstance(node, ast.Assign):
                targets = list(node.targets)
            elif isinstance(node, ast.AnnAssign):
                targets = [node.target]
            for t in targets:
                if isinstance(t, ast.Name) and RESIDUE_NAME_RE.match(t.id):
                    found.append(f"{rel}::{t.id}")
    return sorted(set(found))


def _symbol_exists(root: Path, key: str) -> bool:
    path, _, symbol = key.partition("::")
    target = root / path
    if not target.is_file():
        return False
    if not symbol:
        return True
    return re.search(rf"^{re.escape(symbol)}\s*[:=]", target.read_text(encoding="utf-8"), re.M) is not None


def registry_findings(
    registry: Optional[Dict[str, Dict[str, str]]] = None,
    discovered: Optional[Iterable[str]] = None,
    root: Path = ROOT,
) -> List[str]:
    """Pure over its inputs. Every way the residue registry fails its contract."""
    reg = RESIDUE_LEDGERS if registry is None else registry
    found = discover_residue_ledgers(root) if discovered is None else list(discovered)
    problems: List[str] = []
    for key, entry in sorted(reg.items()):
        missing = [f for f in REQUIRED_FIELDS if not str((entry or {}).get(f) or "").strip()]
        if missing:
            problems.append(f"{key}: missing {', '.join(missing)} — a residue ledger carries a carrier, a condition and an expiry")
            continue
        if not re.fullmatch(r"#\d+", entry["carrier"].strip()):
            problems.append(f"{key}: carrier {entry['carrier']!r} is not an issue `#N`")
        declared, expires = parse_day_literal(entry["declared"]), parse_day_literal(entry["expires"])
        if declared is None or expires is None:
            problems.append(f"{key}: declared/expires must be YYYY-MM-DD (got {entry['declared']!r}/{entry['expires']!r})")
        elif not (declared < expires and (expires - declared).days <= MAX_EXPIRY_DAYS):
            problems.append(f"{key}: expires {expires} must fall within {MAX_EXPIRY_DAYS} days after declared {declared}")
        if not (root / entry["consumer"]).is_file():
            problems.append(f"{key}: shrink consumer {entry['consumer']} does not exist")
        elif (key.partition("::")[2] or Path(key).name) not in (root / entry["consumer"]).read_text(encoding="utf-8"):
            problems.append(f"{key}: shrink consumer {entry['consumer']} never names the ledger it is supposed to hold")
        if not _symbol_exists(root, key):
            problems.append(f"{key}: registered ledger does not exist (phantom entry)")
    for key in found:
        if key not in reg:
            problems.append(f"{key}: a residue ledger that is NOT in RESIDUE_LEDGERS — register it with a carrier, condition and expiry")
    return problems


def dated_obligation_findings(dated: Optional[Dict[Tuple[str, str], Dict[str, str]]] = None) -> List[str]:
    reg = DATED_OBLIGATIONS if dated is None else dated
    problems: List[str] = []
    for (rel, day), entry in sorted(reg.items()):
        expires, declared = parse_day_literal(day), parse_day_literal((entry or {}).get("declared"))
        if rel not in OBLIGATION_SURFACES:
            problems.append(f"{rel}@{day}: not a governed obligation surface")
        if expires is None or declared is None:
            problems.append(f"{rel}@{day}: the date and `declared` must be YYYY-MM-DD")
        elif not (declared <= expires and (expires - declared).days <= MAX_EXPIRY_DAYS):
            problems.append(f"{rel}@{day}: a dated home must fall within {MAX_EXPIRY_DAYS} days of `declared` {declared}")
        if not str((entry or {}).get("what") or "").strip():
            problems.append(f"{rel}@{day}: `what` must say what is due on that date")
    return problems


# ── 3. the probe the calendar runs ─────────────────────────────────────────────────────────
def expired_carriers(
    today: date,
    registry: Optional[Dict[str, Dict[str, str]]] = None,
    dated: Optional[Dict[Tuple[str, str], Dict[str, str]]] = None,
) -> List[str]:
    """Pure. Every residue ledger and dated obligation strictly past its expiry on `today`."""
    reg = RESIDUE_LEDGERS if registry is None else registry
    dreg = DATED_OBLIGATIONS if dated is None else dated
    out: List[str] = []
    for key, entry in sorted(reg.items()):
        exp = parse_day_literal((entry or {}).get("expires"))
        if exp is None or is_past(exp, today):
            out.append(f"residue ledger {key} — expires {exp or 'UNPARSEABLE'} (carrier {(entry or {}).get('carrier', '?')})")
    for (rel, day), entry in sorted(dreg.items()):
        exp = parse_day_literal(day)
        if exp is None or is_past(exp, today):
            out.append(f"dated obligation {rel} @ {day} — {(entry or {}).get('what', '?')}")
    return out


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--keys", action="store_true", help="print every current unhomed obligation key")
    ap.add_argument("--expired", action="store_true", help="the calendar probe: exit 1 if any entry is past its expiry")
    ap.add_argument("--today", default=None)
    args = ap.parse_args(argv)
    if args.keys:
        for key, excerpt, _reason in live_unhomed_obligations():
            print(f"{key}\t{excerpt}")
        return 0
    if args.expired:
        today = parse_day_literal(args.today) if args.today else date.today()
        if today is None:
            print(f"--today {args.today!r} is not YYYY-MM-DD")
            return 2
        lapsed = expired_carriers(today)
        for line in lapsed:
            print(f"EXPIRED  {line}")
        print(f"{len(lapsed)} expired carrier(s) as of {today}")
        return 1 if lapsed else 0
    unhomed = live_unhomed_obligations()
    problems = registry_findings() + dated_obligation_findings()
    print(f"obligations unhomed on governed surfaces: {len(unhomed)}")
    print(f"residue ledgers registered: {len(RESIDUE_LEDGERS)} · dated obligations: {len(DATED_OBLIGATIONS)}")
    for p in problems:
        print(f"PROBLEM  {p}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
