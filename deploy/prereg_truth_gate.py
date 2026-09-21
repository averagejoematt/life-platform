"""prereg_truth_gate.py — the #3599 pre-seal truth contract (acceptance box 3).

THE CLAIM THIS PROTECTS
───────────────────────
A sealed pre-registration is the platform's strongest credibility artifact: bytes
published before Day 1, hash-stamped, and verifiable by any reader with `curl` and
`shasum`. Two gates already guard it and neither asks whether it is TRUE:

  deploy/prereg_seal_gate.py        (#1979) — does a cycle HAVE a published seal?
  deploy/prereg_provenance_gate.py  (#3511) — does the live LEDGER agree with it?

Both can be perfectly green over an artifact that seals a coach who does not exist,
a starting weight the platform does not hold, and a "minimum effect" nobody priced.
A seal makes a claim PERMANENT — `genesis_prereg_stamp.py` refuses to re-stamp the
same genesis with different bytes, and `stamped_at` is never backdated — so an
untrue seal cannot be corrected later, only amended in public. The cheapest moment
to catch it is before the stamp is written.

THE THREE CLAUSES (issue #3599, acceptance box 3)
─────────────────────────────────────────────────
  COACH_NOT_OPERATIONAL  a coach id in the artifact that is not in the operational
                         persona set (`coach.persona_registry.OPERATIONAL_COACH_IDS`).
                         The R2 defect (#3520): the seeder's roster was a hand list
                         and rotted — cycle 17 sealed `training_coach`, retired at the
                         cycle-13 genesis (ADR-153, the Performance seat absorbed it).
  COACH_NAME_MISMATCH    an operational id whose byline in the artifact disagrees with
                         the registry's. Cycle 17 sealed `physical_coach` as
                         "Dr. Victor Reyes" while /api/coaches and /api/predictions
                         both resolve the registry name — one seat, two first names,
                         on two reader surfaces.
  BASELINE_MISMATCH      a starting weight asserted by the artifact that disagrees
                         with `common.constants.EXPERIMENT_BASELINE_WEIGHT_LBS`. The
                         CTO-3 defect: a frozen artifact quoting a superseded baseline,
                         the #1985 class recurring on the third reset.
  MIN_EFFECT_UNDERIVED   a hypothesis whose pre-registered bar does not travel with the
                         variance it came from — metric, sd, n and window (QS-5/#3552).
                         `experiment/prereg_effect.derive_min_effect` has produced that
                         block since #3552; an artifact frozen before it carries bare
                         literals, and a reader cannot tell a demanding bar from a
                         decorative one.

THE SECOND CENSUS (#3621 box 2) — THE ONE CLAUSE HERE THAT IS NOT ABOUT BYTES
─────────────────────────────────────────────────────────────────────────────
  CENSUS_FAMILY_APPEARED a pk family present in a census taken AFTER the wipe and absent
                         from the one taken before it. DA-7's window is the specimen: the
                         reset-time tagger ran at 16:37Z and six `INSIGHT#` rows were
                         written at 17:09Z — after every instrument that could have seen
                         them, and before the seal that would make the cycle's record
                         permanent. Nothing looked twice, so nothing could tell.

  The other four clauses grade an artifact's BYTES. This one grades the TABLE, because
  the untruth it catches is not in the artifact at all: it is a seal asserting "this is
  what cycle N was" over rows that arrived after the reset stopped looking. The predicate
  is still pure — `audit_census_delta(before, after)` takes two family maps, does no I/O
  and has no clock. `run_second_census_gate()` is the ONE credentialed wrapper, and it
  delegates the enumeration to `experiment.pk_census.family_census` rather than writing a
  second scanner (one derivation, two verdicts — see that module's own note).

  THE INVERSE IS DELIBERATELY NOT HERE. A family present before and ABSENT after would
  mean rows were DELETED, and the wipe never deletes — it tombstones (Interpretation B,
  the module docstring of restart_intelligence_wipe). Row-level survival is
  `deploy/restart_verify.py`'s census, which reads counts this one never does. Two
  implementations of one rule is how a comparison gate goes blind.

THE ISSUE'S FOURTH REFUSAL REASON LIVES NEXT DOOR, DELIBERATELY
───────────────────────────────────────────────────────────────
#3599 also names "a seed whose season ids ⊄ the artifact". That clause exists and is
NOT reimplemented here: `deploy/prereg_provenance_gate.py` (#3511) owns it in both
directions — PRE_GENESIS_WRITE / BACKDATED_UNSEALED for a season row the artifact
never sealed, SEALED_ROW_MISSING for the mirror — and `genesis_prereg_stamp.py
--apply` calls its `require_clean_for_publish()` before any byte goes up, which
`tests/test_prereg_pregenesis_contract_3511.py::test_restart_verify_and_the_seal_
publisher_both_call_this_predicate` pins. It reads the live ledger, so it belongs on
the credentialed publish path; this module is pure and runs on every seal path. Two
implementations of one rule is how a comparison gate goes blind, so the seal
chokepoint COMPOSES them rather than merging them.

WHAT NO PRE-SEAL CLAUSE CAN REACH — #3599's other half
──────────────────────────────────────────────────────
Everything here binds seals being MINTED. Eight seals are already published
(2026-07-19 through 2026-09-06; all eight still hash-verify, measured 2026-09-20),
and the live cycle-17 one disagrees with the platform on three counts today.
`deploy/prereg_amendment.py` is the only instrument that reaches them: a separate,
append-only, public correction record that leaves the sealed bytes as they stand.

WHY THE BASELINE CLAUSE READS PROSE
───────────────────────────────────
The artifact has no `baseline` field to compare — the baseline lives in the CLAIMS
("...from the stated start weight of 326.2 lbs..."), which is exactly how the defect
reaches a reader. So the clause resolves the asserted baseline two ways, in order:
an explicit `baseline` / `baseline_weight_lbs` field when a future artifact carries
one, else every weight figure in the artifact's own text that sits within
`_ANCHOR_CHARS` of a start-of-experiment word. Agreement is judged at the PRECISION
THE ARTIFACT STATES: "327.3 lbs" agrees with a 327.34 baseline, "326.2 lbs" does not.

An artifact that asserts no baseline at all produces no finding here, which is a real
vacuity risk, so `asserted_baselines()` is exported separately and the test asserts it
is non-empty against the committed cycle-17 specimen.

WHERE IT RUNS
─────────────
`audit_prereg_truth()` is PURE — artifact in, findings out. No I/O, no clock, no
credentials, no network. That is what lets the same predicate run in both places:

  the seal      `genesis_prereg_stamp.write_stamp()` — the ONE function that mints a
                seal, reached by the seeder's freeze-time stamp and by that module's
                CLI alike — calls `require_clean_for_seal()` just after the idempotent
                already-stamped return. Unlike the #3511 ledger gate this one needs
                nothing but the file, so there is no reason to defer it to the
                credentialed `--apply` path. It binds seals being MINTED only: a seal
                that already exists is left exactly as it stands (#3552's ruling — a
                published pre-registration is amended in public, never edited), and
                the module's CLI prints the standing verdict so it is still visible.
  CI            `tests/test_prereg_truth_gate_3599.py` runs it against the committed,
                published cycle-17 artifact (the positive control — that seal is live
                and its sha256 matches the stamp) and against a repaired copy (the
                negative control).

THE POSITIVE CONTROL IS MEASURED, NOT ASSUMED
─────────────────────────────────────────────
Issue #3599 says "today's cycle-16 artifact fails on two counts". That artifact is
gone; cycle 17 (genesis 2026-09-06) has been live since. Re-measured against the
cycle-17 seal on 2026-09-18 the verdict is SEVEN blocking findings — every one of the
four kinds above, so each clause has a live specimen rather than only a synthetic one.
The sealed bytes are committed at `tests/fixtures/prereg_cycle17_2026-09-06.json` and
the counts are asserted there.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(REPO_ROOT / "lambdas") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "lambdas"))

FROZEN_PATH = REPO_ROOT / "deploy" / "generated" / "genesis_preregistration.json"

COACH_NOT_OPERATIONAL = "COACH_NOT_OPERATIONAL"
COACH_NAME_MISMATCH = "COACH_NAME_MISMATCH"
BASELINE_MISMATCH = "BASELINE_MISMATCH"
MIN_EFFECT_UNDERIVED = "MIN_EFFECT_UNDERIVED"
CENSUS_FAMILY_APPEARED = "CENSUS_FAMILY_APPEARED"

#: Every finding kind this module can emit. Guard-the-set: `audit_prereg_truth` asserts
#: its own output is drawn from this tuple, so a new kind cannot be added without the
#: tests (which enumerate it) noticing. Deliberately NOT named `*_CLASSES`/`*_RULES` —
#: those spellings are registry names the gate census expands entry by entry, and four
#: finding labels are not four gates.
FINDING_KINDS = (COACH_NOT_OPERATIONAL, COACH_NAME_MISMATCH, BASELINE_MISMATCH, MIN_EFFECT_UNDERIVED)

#: #3621 box 2's clause, declared SEPARATELY and on purpose. `FINDING_KINDS` above is the
#: set an ARTIFACT can reach, and `tests/test_prereg_truth_gate_3599.py` asserts the live
#: cycle-17 seal reaches every one of them — a guard-the-set control that a kind no
#: artifact can ever produce would silently break. The census clause grades the TABLE, so
#: it gets its own set and `audit_census_delta` asserts its own output against it.
CENSUS_FINDING_KINDS = (CENSUS_FAMILY_APPEARED,)
ALL_FINDING_KINDS = FINDING_KINDS + CENSUS_FINDING_KINDS

#: The derivation a pre-registered `min_effect` must travel with. `window` is accepted
#: under either spelling because `prereg_effect.derive_min_effect` emits `window_days`
#: and issue #3599 names it `window`; requiring the issue's literal spelling would red
#: the very shape #3552 shipped.
_DERIVATION_FIELDS = ("metric", "sd", "n")
_WINDOW_FIELDS = ("window", "window_days")

#: Where the derivation block may live on a test_spec: the shipped seeder key first,
#: then `prereg_effect.derive_min_effect`'s own return key.
_DERIVATION_KEYS = ("min_effect_derivation", "derived_from")

#: A body-weight figure in prose: "326.2 lbs", "326.2-lb", "327 pounds". The 100..600
#: range test happens in code — a bare `\d{2,3}` here would also catch "1500 kcal".
_WEIGHT_FIGURE = re.compile(r"(?<![\d.])(\d{2,3}(?:\.\d+)?)\s*-?\s*(?:lbs?|pounds?)\b", re.IGNORECASE)

#: Words that make a nearby weight figure a claim about where the experiment STARTED
#: rather than about a target, a milestone or a current reading.
_ANCHOR_WORDS = re.compile(r"\b(start|starts|started|starting|baseline|initial|initially|outset|beginning|began)\b", re.IGNORECASE)

#: How far either side of a figure an anchor word still binds to it.
_ANCHOR_CHARS = 48

#: Plausible body weights, in lbs. Outside this a figure is not a baseline claim.
_WEIGHT_MIN_LBS = 100.0
_WEIGHT_MAX_LBS = 600.0


@dataclass(frozen=True)
class Finding:
    """One truth violation. `blocking` decides whether the seal may be written."""

    kind: str
    where: str
    detail: str
    blocking: bool = True

    def __str__(self) -> str:  # pragma: no cover - formatting only
        return f"{self.kind} {self.where}: {self.detail}"


@dataclass(frozen=True)
class BaselineClaim:
    """A starting-weight assertion the artifact makes, and where it makes it."""

    value: float
    #: The digits exactly as the artifact writes them — the precision the claim commits
    #: to, which is what agreement is judged at.
    literal: str
    where: str
    quote: str

    @property
    def decimals(self) -> int:
        return len(self.literal.split(".")[1]) if "." in self.literal else 0


# ──────────────────────────────────────────────────────────────────────────────
# repo-derived inputs — resolved ONCE here so the pure audit takes plain values
# ──────────────────────────────────────────────────────────────────────────────


def load_frozen(path: Path | None = None) -> dict:
    """The frozen pre-registration as a dict. Raises rather than returning {} — a gate
    that reads an unreadable artifact as 'nothing to check' is the vacuous pass this
    module exists to prevent."""
    target = Path(path) if path is not None else FROZEN_PATH
    data = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "coaches" not in data:
        raise ValueError(f"{target} is not a pre-registration artifact (no 'coaches' key) — refusing to vouch for it")
    return data


def repo_baseline_lbs() -> float:
    from common.constants import EXPERIMENT_BASELINE_WEIGHT_LBS

    return float(EXPERIMENT_BASELINE_WEIGHT_LBS)


def repo_coach_bylines() -> tuple[dict[str, str], tuple[str, ...]]:
    """(operational id -> registry byline, retired ids). Derived from the persona
    registry, never a hand list — the R2 defect was a hand list that rotted."""
    from coach import persona_registry

    people = persona_registry.personas()
    bylines = {cid: (people.get(cid) or {}).get("name") or "" for cid in persona_registry.OPERATIONAL_COACH_IDS}
    return bylines, tuple(persona_registry.RETIRED_COACH_IDS)


# ──────────────────────────────────────────────────────────────────────────────
# the baseline clause
# ──────────────────────────────────────────────────────────────────────────────


def _strings(node: Any, path: str = "") -> Iterator[tuple[str, str]]:
    """Every string leaf in the artifact, with a dotted path to it."""
    if isinstance(node, str):
        yield path, node
    elif isinstance(node, dict):
        for key, value in node.items():
            yield from _strings(value, f"{path}.{key}" if path else str(key))
    elif isinstance(node, list):
        for i, value in enumerate(node):
            yield from _strings(value, f"{path}[{i}]")


def _explicit_baseline(artifact: dict) -> BaselineClaim | None:
    """A structured baseline field, if a future artifact carries one. Checked first so
    the prose scan is a fallback for the shape that exists today, not the contract."""
    for key in ("baseline_weight_lbs", "baseline"):
        raw = artifact.get(key)
        if isinstance(raw, dict):
            raw = raw.get("weight_lbs")
        if raw is None or isinstance(raw, bool):
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        literal = f"{raw}" if not isinstance(raw, float) else repr(raw)
        return BaselineClaim(value=value, literal=literal, where=key, quote=f"{key}={raw!r}")
    return None


def asserted_baselines(artifact: dict) -> list[BaselineClaim]:
    """Every starting-weight the artifact asserts. Exported so the tests can assert the
    clause is NOT vacuous on the real specimen: an artifact that mentions no start
    weight produces no finding here, and a clause with nothing to check would pass
    forever without anyone noticing."""
    explicit = _explicit_baseline(artifact)
    if explicit is not None:
        return [explicit]

    claims: list[BaselineClaim] = []
    for where, text in _strings(artifact):
        for m in _WEIGHT_FIGURE.finditer(text):
            literal = m.group(1)
            value = float(literal)
            if not (_WEIGHT_MIN_LBS <= value <= _WEIGHT_MAX_LBS):
                continue
            lo = max(0, m.start() - _ANCHOR_CHARS)
            hi = min(len(text), m.end() + _ANCHOR_CHARS)
            if not _ANCHOR_WORDS.search(text[lo:hi]):
                continue
            claims.append(BaselineClaim(value=value, literal=literal, where=where, quote=text[lo:hi].strip()))
    return claims


def _agrees_at_stated_precision(claim: BaselineClaim, baseline_lbs: float) -> bool:
    """ "327.3 lbs" agrees with a 327.34 baseline; "326.2 lbs" does not. A claim is held
    only to the precision it commits to — rounding the artifact's own figure UP in
    precision would red every correctly-rounded restatement of the true number."""
    dp = claim.decimals
    return abs(round(baseline_lbs, dp) - round(claim.value, dp)) < 10 ** -(dp + 3)


# ──────────────────────────────────────────────────────────────────────────────
# the min_effect clause
# ──────────────────────────────────────────────────────────────────────────────


def _usable(value: Any) -> bool:
    """A derivation field is present only if it carries something. `"sd": null` states
    the bar came from a variance nobody measured just as loudly as an absent key."""
    if value is None or isinstance(value, bool):
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def missing_derivation_fields(spec: Any) -> list[str] | None:
    """The derivation fields a test_spec's `min_effect` does NOT carry, or None when the
    spec is complete. Pure and separately exported so a caller can report WHICH field
    is absent rather than only that something is."""
    if not isinstance(spec, dict):
        return ["test_spec"]
    if not _usable(spec.get("min_effect")):
        return ["min_effect"]
    block: Any = None
    for key in _DERIVATION_KEYS:
        if isinstance(spec.get(key), dict):
            block = spec[key]
            break
    if block is None:
        return [*_DERIVATION_FIELDS, _WINDOW_FIELDS[0]]
    absent = [f for f in _DERIVATION_FIELDS if not _usable(block.get(f))]
    if not any(_usable(block.get(f)) for f in _WINDOW_FIELDS):
        absent.append(_WINDOW_FIELDS[0])
    return absent or None


# ──────────────────────────────────────────────────────────────────────────────
# the audit
# ──────────────────────────────────────────────────────────────────────────────


def audit_prereg_truth(
    artifact: dict,
    *,
    baseline_lbs: float,
    coach_bylines: dict[str, str],
    retired_ids: tuple[str, ...] = (),
) -> list[Finding]:
    """Every truth violation in `artifact`. PURE: no I/O, no clock, no credentials.

    `coach_bylines` is the operational id -> byline map; ids outside it are not
    operational. `retired_ids` only enriches the message — an id is refused because it
    is absent from the operational set, never because it appears on a retirement list,
    so a coach retired WITHOUT being recorded is caught just the same.
    """
    findings: list[Finding] = []

    for coach_id, block in (artifact.get("coaches") or {}).items():
        name = (block or {}).get("coach_name") or ""
        if coach_id not in coach_bylines:
            why = "retired" if coach_id in retired_ids else "not in the operational persona set"
            findings.append(
                Finding(
                    COACH_NOT_OPERATIONAL,
                    f"coaches.{coach_id}",
                    f"sealed as {name!r} but {coach_id} is {why} — the artifact would pre-register bets for a seat "
                    f"no reader surface serves (operational: {sorted(coach_bylines)})",
                )
            )
            continue
        expected = coach_bylines[coach_id]
        if expected and name != expected:
            findings.append(
                Finding(
                    COACH_NAME_MISMATCH,
                    f"coaches.{coach_id}",
                    f"sealed byline {name!r} but the persona registry says {expected!r} — /api/coaches and "
                    "/api/predictions resolve the registry, so the seal and the site would name one seat twice",
                )
            )

    for claim in asserted_baselines(artifact):
        if _agrees_at_stated_precision(claim, baseline_lbs):
            continue
        findings.append(
            Finding(
                BASELINE_MISMATCH,
                claim.where,
                f"asserts a starting weight of {claim.literal} lbs but EXPERIMENT_BASELINE_WEIGHT_LBS is "
                f"{baseline_lbs} — a seal is permanent, so a superseded baseline in it can never be corrected, "
                f'only amended in public. Quote: "...{claim.quote}..."',
            )
        )

    for i, hypothesis in enumerate(artifact.get("hypotheses") or []):
        hid = (hypothesis or {}).get("hypothesis_id") or f"[{i}]"
        absent = missing_derivation_fields((hypothesis or {}).get("test_spec"))
        if absent:
            findings.append(
                Finding(
                    MIN_EFFECT_UNDERIVED,
                    f"hypotheses.{hid}",
                    f"pre-registers a minimum effect with no {', '.join(absent)} — a public threshold that does not "
                    "travel with the variance it came from cannot be told from a decorative one "
                    "(experiment/prereg_effect.derive_min_effect emits the block)",
                )
            )

    unknown = [f.kind for f in findings if f.kind not in FINDING_KINDS]
    if unknown:  # pragma: no cover - structurally impossible, asserted anyway
        raise AssertionError(f"finding kinds outside FINDING_KINDS: {sorted(set(unknown))}")
    return findings


def audit_frozen(path: Path | None = None, artifact: dict | None = None) -> list[Finding]:
    """`audit_prereg_truth` with the repo as its source of truth."""
    data = artifact if artifact is not None else load_frozen(path)
    bylines, retired = repo_coach_bylines()
    if not bylines:
        raise RuntimeError("the persona registry resolved to zero operational coaches — refusing to vouch for a seal it cannot check")
    return audit_prereg_truth(data, baseline_lbs=repo_baseline_lbs(), coach_bylines=bylines, retired_ids=retired)


def blocking(findings: list[Finding]) -> list[Finding]:
    return [f for f in findings if f.blocking]


def require_clean_for_seal(path: Path | None = None, artifact: dict | None = None) -> list[Finding]:
    """The "else the seal may not be written" clause. Returns the blocking findings —
    an empty list means the stamp may proceed. Never writes anything."""
    return blocking(audit_frozen(path=path, artifact=artifact))


def summarize(findings: list[Finding]) -> dict[str, int]:
    return {kind: sum(1 for f in findings if f.kind == kind) for kind in FINDING_KINDS if any(f.kind == kind for f in findings)}


def render_report(findings: list[Finding], artifact: dict) -> str:
    lines = [
        f"prereg truth contract (#3599) — genesis {artifact.get('genesis')}",
        f"  coaches sealed     : {len(artifact.get('coaches') or {})}",
        f"  hypotheses sealed  : {len(artifact.get('hypotheses') or [])}",
        f"  baselines asserted : {len(asserted_baselines(artifact))}",
        f"  findings           : {summarize(findings) or 'none'}",
        f"  blocking           : {len(blocking(findings))}",
    ]
    for f in findings:
        lines.append(f"  {'BLOCK' if f.blocking else 'note '}  {f}")
    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────────
# the second-census clause (#3621 box 2) — pure predicate, one credentialed wrapper
# ──────────────────────────────────────────────────────────────────────────────


def audit_census_delta(before: dict, after: dict) -> list[Finding]:
    """Every pk family present in `after` and absent from `before`. PURE: no I/O, no
    clock, no credentials — two family maps in (`{family: (rep_pk, rep_sk)}`, the shape
    `experiment.pk_census.family_census` returns), findings out.

    An EMPTY census on either side RAISES rather than returning []. "No new families"
    over an empty enumeration is a check that cannot fail reporting success — which is
    the exact failure mode this clause exists to close, so it is refused here too rather
    than only inside the scanner.
    """
    if not before:
        raise ValueError(
            "second-census clause: the FIRST census is empty. A delta against an empty "
            "before-set reports every live family as new; against an empty after-set it "
            "reports nothing at all. Neither is a verdict — refusing to grade it."
        )
    if not after:
        raise ValueError(
            "second-census clause: the SECOND census is empty. The scan after the wipe "
            "enumerated ZERO pk families, which certifies nothing (the vacuous-scan trap) "
            "— refusing to read it as 'no family appeared'."
        )
    findings: list[Finding] = []
    for family in sorted(set(after) - set(before)):  # the direction IS the clause
        rep_pk, rep_sk = after[family]
        findings.append(
            Finding(
                CENSUS_FAMILY_APPEARED,
                f"census.{family}",
                f"pk family {family!r} exists in the census taken AFTER the wipe and did not exist in the "
                f"one taken before it (representative row pk={rep_pk!r} sk={rep_sk!r}). A writer wrote into "
                "the cycle after every instrument that archives it had already looked — DA-7's window, in "
                "which the tagger ran at 16:37Z and six INSIGHT# rows landed at 17:09Z. Sealing here would "
                "make a permanent public claim about a cycle whose record is still moving: stop the writer "
                "(or the schedule), re-run the wipe, and take the census again.",
            )
        )
    unknown = [f.kind for f in findings if f.kind not in CENSUS_FINDING_KINDS]
    if unknown:  # pragma: no cover - structurally impossible, asserted anyway
        raise AssertionError(f"census finding kinds outside CENSUS_FINDING_KINDS: {sorted(set(unknown))}")
    return findings


def render_census_delta(findings: list[Finding], before: dict, after: dict) -> str:
    return "\n".join(
        [
            "second-census clause (#3621) — pk families before/after the wipe",
            f"  families before : {len(before)}",
            f"  families after  : {len(after)}",
            f"  appeared        : {len(findings)}",
            *[f"  BLOCK  {f}" for f in findings],
        ]
    )


def run_second_census_gate(before: dict, *, table=None, printer=print) -> list[Finding]:
    """THE CREDENTIALED WRAPPER. Takes the SECOND census and grades it against `before`.

    The only I/O in this module. It delegates the enumeration to
    `experiment.pk_census.family_census` — the same function that produced `before` — so
    the two sides of the comparison can never be two different derivations (the #3792
    lesson). Returns the blocking findings; an empty list means the reset may proceed to
    the seal. NEVER writes, and never swallows: a census that cannot be taken raises,
    because "the scan failed" must not read as "nothing appeared".
    """
    import sys as _sys
    from pathlib import Path as _Path

    _lam = str(_Path(__file__).resolve().parent.parent / "lambdas")
    if _lam not in _sys.path:
        _sys.path.insert(0, _lam)
    from experiment.pk_census import family_census

    after = family_census(table)
    findings = blocking(audit_census_delta(before, after))
    printer(render_census_delta(findings, before, after))
    return findings


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - CLI
    import argparse

    ap = argparse.ArgumentParser(description="Audit a frozen pre-registration against the platform's own facts (#3599)")
    ap.add_argument("--path", default=None, help=f"artifact to audit (default: {FROZEN_PATH})")
    ap.add_argument("--json", action="store_true", help="emit findings as JSON")
    args = ap.parse_args(argv)

    artifact = load_frozen(Path(args.path) if args.path else None)
    findings = audit_frozen(artifact=artifact)
    if args.json:
        print(json.dumps([f.__dict__ for f in findings], indent=2))
    else:
        print(render_report(findings, artifact))
    return 1 if blocking(findings) else 0


if __name__ == "__main__":  # pragma: no cover - CLI
    sys.exit(main())
