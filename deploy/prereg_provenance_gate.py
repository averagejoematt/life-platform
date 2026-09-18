"""prereg_provenance_gate.py — the #3511 pre-genesis prediction provenance contract.

THE CLAIM THIS PROTECTS
───────────────────────
"The coaches' opening bets were sealed before Day 1, and you can verify it." The
#1979 gate (`deploy/prereg_seal_gate.py`) asserts a cycle HAS a published,
hash-verified seal. Nothing asserted the live ledger AGREES with that seal — so a
bet written before Day 1 that is NOT in the frozen artifact would still be graded
into the cycle's scorecard beside the sealed ones, indistinguishable to a reader.

That is the QS-1 defect (2026-09-05 `/review full`, issue #3511): the 17:09Z Day-0
`coach-state-updater` run on 2026-09-04 wrote two gradeable directional bets with
14-day windows starting on Day 0, no `pre_registered` attribute, and a self-declared
`cycle` stamp that the countdown sweep exempted. They were reconciled by hand at the
next reset. Nothing would have caught the next one.

THE CONTRACT (issue #3511, acceptance box 3)
────────────────────────────────────────────
Every non-tombstoned SEASON `PREDICTION#` row that presents as pre-genesis must have
its `prediction_id` in the frozen pre-registration artifact — and, once the cycle has
actually started, every id IN the artifact must be live in the season.

"Presents as pre-genesis" is deliberately NOT the box's literal `created_date <=
genesis`, and the reason is measured, not stylistic. Live on 2026-09-17 the season
held **9** rows with `created_date == 2026-09-06` (the genesis) whose `created_at` is
`2026-09-06T17:0xZ` — 10:0x PT on Day 1. Those are ordinary Day-1 coach calls; the
literal predicate flags all nine, every cycle, forever, and a gate that reds on
correct behaviour is one readers learn to skip. So the rule splits the box into the
two ways a row can present as pre-genesis, and each is separately falsifiable:

  PRE_GENESIS_WRITE   `created_at` at or before the genesis boundary (PT midnight of
                      genesis, in UTC) — it was physically written before Day 1.
                      This is the founding specimen's class.
  BACKDATED_UNSEALED  written after the boundary, but `created_date` strictly BEFORE
                      genesis — it READS as a pre-genesis call on /api/predictions
                      (whose `date` column is `created_date`) without being sealed.

`created_date == genesis` written after the boundary is a Day-1 call and is correct.

The mirror clause guards the set the other way:

  SEALED_ROW_MISSING  an id in the frozen artifact with no non-tombstoned season row.
                      Only APPLICABLE from genesis onward (`as_of >= genesis`): the
                      seeder runs the evening BEFORE Day 1, so at publish time the
                      sealed rows legitimately are not in the season yet. Without
                      that date test the publish gate could never be satisfied.

This clause is not decoration. Live on 2026-09-17 ALL 16 cycle-17 sealed bets carry
`phase=pilot, cycle=16` — the seeder ran at 2026-09-06T02:13Z (2026-09-05 19:13 PT,
still pre-genesis), so `experiment_stamp()` correctly said "pilot", and nothing ever
re-stamped them. They fail `PHASE_FILTER_EXPRESSION` forever: the cycle's entire
pre-registration is invisible on `/api/predictions`, while nine unsealed Day-1 calls
are served. `deploy/reconcile_prereg_season_3511.py` is the dry-run-by-default repair.

WHERE EACH HALF RUNS (the #3511 "restart_verify AND CI" box)
────────────────────────────────────────────────────────────
`audit_prereg_provenance()` is PURE — rows in, findings out, no I/O, no clock, no
credentials. That is what makes the CI half real rather than a credential-gated
no-op:

  CI (no AWS)      `tests/test_prereg_pregenesis_contract_3511.py` runs the predicate
                   against the COMMITTED frozen artifact and a COMMITTED capture of
                   the live season taken 2026-09-17 (`tests/fixtures/
                   prereg_season_rows_2026-09-17.json`, a read-only DynamoDB query,
                   claim text excluded). Both mutation controls operate on real files
                   on disk and assert their own md5 changed before any verdict is read.
  restart_verify   check 20 — fetches the live rows (`fetch_season_prediction_rows`)
                   and runs the same function. Post-genesis, credentialed.
  the seal publish `deploy/genesis_prereg_stamp.py --apply` refuses to upload the
                   artifact + stamp while a BLOCKING finding stands ("else the seal
                   cannot publish"). Pre-genesis that is exactly the two write-class
                   findings, which is satisfiable by construction.

The prediction-id derivation lives here too, and `deploy/seed_genesis_preregistration.py`
imports it — the gate and the seeder cannot disagree about what a frozen claim's id is,
because there is only one function.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, time, timezone
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(REPO_ROOT / "lambdas") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "lambdas"))

from lambdas.common.constants import EXPERIMENT_PHASE_CURRENT  # noqa: E402

FROZEN_PATH = REPO_ROOT / "deploy" / "generated" / "genesis_preregistration.json"
PT = ZoneInfo("America/Los_Angeles")
REGION = "us-west-2"
TABLE_NAME = "life-platform"

PRE_GENESIS_WRITE = "PRE_GENESIS_WRITE"
BACKDATED_UNSEALED = "BACKDATED_UNSEALED"
SEALED_ROW_MISSING = "SEALED_ROW_MISSING"

#: Every finding class this module can emit. Guard-the-set: the audit asserts its own
#: output is drawn from this tuple, so a new class cannot be added without the tests
#: (which enumerate it) noticing.
FINDING_CLASSES = (PRE_GENESIS_WRITE, BACKDATED_UNSEALED, SEALED_ROW_MISSING)


@dataclass(frozen=True)
class Finding:
    """One contract violation. `blocking` decides whether the seal may publish."""

    kind: str
    prediction_id: str
    pk: str
    detail: str
    blocking: bool = True
    #: The row's sort key. Load-bearing for locating a finding: the dispute-docket
    #: writer emits several rows that SHARE one `prediction_id` (`…-2`, `…-3`, … sks),
    #: so `prediction_id` alone does not identify the row a repair has to touch.
    sk: str = ""

    def __str__(self) -> str:  # pragma: no cover - formatting only
        where = f"{self.pk}/{self.sk}" if self.sk else self.prediction_id
        return f"{self.kind} {where}: {self.detail}"


# ──────────────────────────────────────────────────────────────────────────────
# prediction-id derivation — ONE definition, imported by the seeder
# ──────────────────────────────────────────────────────────────────────────────


def prereg_slug(claim: str) -> str:
    """The slug half of a seeded prediction id. Byte-identical to the rule
    `deploy/seed_genesis_preregistration.py` shipped before #3511 moved it here —
    the seeder now imports this, so the live ids and the ids this gate derives from
    the frozen artifact cannot fork."""
    return re.sub(r"[^a-z0-9]+", "_", claim.lower()[:40]).strip("_")


def prediction_id_for(claim: str, genesis: str) -> str:
    """`pred_{YYYYMMDD}_{slug}` — the id the seeder writes for a frozen claim."""
    return f"pred_{genesis.replace('-', '')}_{prereg_slug(claim)}"


def frozen_prediction_ids(frozen: dict) -> set[str]:
    """Every prediction id the frozen artifact seals, derived from its claims.

    Raises on a shapeless artifact rather than returning an empty set: an empty id
    set would make the write-class clauses flag EVERY pre-genesis row and the
    missing-seal clause flag none — a silently inverted gate."""
    genesis = frozen.get("genesis")
    coaches = frozen.get("coaches")
    if not isinstance(genesis, str) or not genesis or not isinstance(coaches, dict) or not coaches:
        raise ValueError(f"frozen pre-registration artifact has no genesis/coaches to derive ids from: keys={sorted(frozen)}")
    ids: set[str] = set()
    for coach_id, block in coaches.items():
        for pred in (block or {}).get("predictions", []) or []:
            claim = pred.get("claim_natural")
            if not claim:
                raise ValueError(f"frozen artifact coach {coach_id!r} has a prediction with no claim_natural")
            ids.add(prediction_id_for(claim, genesis))
    if not ids:
        raise ValueError("frozen pre-registration artifact seals zero predictions")
    return ids


def load_frozen(path: Path | str = FROZEN_PATH) -> dict:
    return json.loads(Path(path).read_text())


# ──────────────────────────────────────────────────────────────────────────────
# the contract — PURE
# ──────────────────────────────────────────────────────────────────────────────


def genesis_boundary_utc(genesis: str) -> datetime:
    """The instant Day 1 begins: PT midnight of `genesis`, as UTC.

    The experiment's day boundary is Pacific (the site's clock, #2506/#2675), so a
    UTC-naive boundary would put the whole 00:00–07:00Z stretch of genesis day on
    the wrong side of the line — the exact window the countdown-gap sweep exists for.
    """
    return datetime.combine(datetime.fromisoformat(genesis).date(), time(0, 0), tzinfo=PT).astimezone(timezone.utc)


def _parse_instant(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _row_id(row: dict) -> str:
    pid = row.get("prediction_id")
    if isinstance(pid, str) and pid:
        return pid
    sk = str(row.get("sk", ""))
    return sk.split("#", 1)[1] if sk.startswith("PREDICTION#") else sk


def in_season(row: dict) -> bool:
    """A row the scorecard grades THIS cycle: not tombstoned, current phase.

    A row with no `phase` at all counts as in-season — that is the direction
    `PHASE_FILTER_EXPRESSION` itself takes (`attribute_not_exists(phase)` passes),
    so an unstamped row IS served and must be audited, never waved through.
    """
    if row.get("tombstone"):
        return False
    phase = row.get("phase")
    return phase is None or phase == EXPERIMENT_PHASE_CURRENT


def audit_prereg_provenance(
    rows: Iterable[dict],
    frozen: dict,
    *,
    as_of: Any,
) -> list[Finding]:
    """The #3511 contract. Pure: no I/O, no ambient clock, no credentials.

    `rows` — live `PREDICTION#` rows (any shape carrying pk/sk/created_at/created_date/
    phase/tombstone). `frozen` — the pre-registration artifact. `as_of` — the date the
    audit speaks for (a `date`, or an ISO `YYYY-MM-DD` string); it decides only whether
    the missing-seal clause is applicable yet.

    Returns every finding, blocking and not. `[]` means the ledger agrees with the seal.
    """
    genesis = frozen["genesis"]
    boundary = genesis_boundary_utc(genesis)
    sealed_ids = frozen_prediction_ids(frozen)
    as_of_str = as_of if isinstance(as_of, str) else as_of.isoformat()
    cycle_started = as_of_str[:10] >= genesis

    findings: list[Finding] = []
    seen_sealed: set[str] = set()

    for row in rows:
        if not in_season(row):
            continue
        pid = _row_id(row)
        if pid in sealed_ids:
            seen_sealed.add(pid)
            continue
        written = _parse_instant(row.get("created_at"))
        created_date = row.get("created_date")
        created_date = created_date[:10] if isinstance(created_date, str) else None
        pk = str(row.get("pk", ""))
        if written is not None and written <= boundary:
            findings.append(
                Finding(
                    PRE_GENESIS_WRITE,
                    pid,
                    pk,
                    f"written {written.isoformat()}, at or before the genesis boundary {boundary.isoformat()} "
                    f"(PT midnight of {genesis}), and its id is not in the frozen pre-registration",
                    sk=str(row.get("sk", "")),
                )
            )
        elif created_date is not None and created_date < genesis:
            findings.append(
                Finding(
                    BACKDATED_UNSEALED,
                    pid,
                    pk,
                    f"created_date {created_date} is before genesis {genesis} (so /api/predictions dates it "
                    f"pre-genesis) but it was written {row.get('created_at')!r} and is not in the frozen "
                    "pre-registration",
                    sk=str(row.get("sk", "")),
                )
            )

    for pid in sorted(sealed_ids - seen_sealed):
        findings.append(
            Finding(
                SEALED_ROW_MISSING,
                pid,
                "",
                (
                    f"sealed in the frozen pre-registration for genesis {genesis} but no non-tombstoned "
                    f"{EXPERIMENT_PHASE_CURRENT}-phase row carries it — the bet cannot be graded and the reader "
                    "never sees it; repair: python3 deploy/reconcile_prereg_season_3511.py (dry-run first)"
                ),
                blocking=cycle_started,
            )
        )

    bad = {f.kind for f in findings} - set(FINDING_CLASSES)
    if bad:  # pragma: no cover - structural assertion
        raise AssertionError(f"audit emitted unregistered finding classes {sorted(bad)}")
    return findings


def blocking(findings: Iterable[Finding]) -> list[Finding]:
    return [f for f in findings if f.blocking]


def summarize(findings: Iterable[Finding]) -> dict[str, int]:
    counts = {k: 0 for k in FINDING_CLASSES}
    for f in findings:
        counts[f.kind] += 1
    return counts


# ──────────────────────────────────────────────────────────────────────────────
# the live half — I/O, credentialed callers only
# ──────────────────────────────────────────────────────────────────────────────

_PROJECTION = "pk,sk,prediction_id,created_date,created_at,#p,#c,tombstone,pre_registered,pre_registered_at,#s"
_PROJECTION_NAMES = {"#p": "phase", "#c": "cycle", "#s": "status"}


def season_partitions(frozen: dict) -> list[str]:
    """The `COACH#*` partitions to read — the UNION of the live operational roster and
    the artifact's own coach keys.

    The union is load-bearing, not belt-and-braces: the committed 2026-09-06 artifact
    seals two bets for `training_coach`, a seat that is no longer in
    `persona_registry.OPERATIONAL_COACH_IDS` (retired at the cycle-13 genesis,
    ADR-153). Reading only the live roster would silently drop those two ids into
    "missing seal"; reading only the artifact would miss a row written by a coach that
    joined after the freeze.
    """
    ids = set(frozen.get("coaches") or {})
    try:
        from coach import persona_registry

        ids |= set(persona_registry.OPERATIONAL_COACH_IDS)
    except Exception as exc:  # pragma: no cover - import guard
        raise RuntimeError(f"cannot derive the coach roster from the persona registry: {exc}") from exc
    return sorted(f"COACH#{cid}" for cid in ids)


def fetch_season_prediction_rows(frozen: dict, table=None) -> list[dict]:
    """Every `PREDICTION#` row in the coach partitions, projected to the audited
    attributes (claim text deliberately excluded — the contract keys on ids)."""
    import boto3
    from boto3.dynamodb.conditions import Key

    table = table or boto3.resource("dynamodb", region_name=REGION).Table(TABLE_NAME)
    rows: list[dict] = []
    for pk in season_partitions(frozen):
        lek = None
        while True:
            kwargs: dict[str, Any] = {
                "KeyConditionExpression": Key("pk").eq(pk) & Key("sk").begins_with("PREDICTION#"),
                "ProjectionExpression": _PROJECTION,
                "ExpressionAttributeNames": dict(_PROJECTION_NAMES),
            }
            if lek:
                kwargs["ExclusiveStartKey"] = lek
            resp = table.query(**kwargs)
            rows.extend(resp.get("Items", []))
            lek = resp.get("LastEvaluatedKey")
            if not lek:
                break
    return rows


def audit_live(as_of=None, frozen: dict | None = None, table=None) -> tuple[list[Finding], list[dict]]:
    """Fetch + audit in one call. Returns (findings, rows)."""
    frozen = frozen if frozen is not None else load_frozen()
    rows = fetch_season_prediction_rows(frozen, table=table)
    as_of = as_of or datetime.now(PT).date()
    return audit_prereg_provenance(rows, frozen, as_of=as_of), rows


def require_clean_for_publish(as_of=None, frozen: dict | None = None, table=None) -> list[Finding]:
    """The "else the seal cannot publish" clause. Returns the blocking findings —
    an empty list means the publish may proceed. Never writes anything."""
    findings, _rows = audit_live(as_of=as_of, frozen=frozen, table=table)
    return blocking(findings)


def render_report(findings: list[Finding], rows: list[dict], frozen: dict) -> str:
    lines = [
        f"prereg provenance contract (#3511) — genesis {frozen['genesis']}",
        f"  rows read          : {len(rows)} PREDICTION# ({sum(1 for r in rows if in_season(r))} in season)",
        f"  sealed ids         : {len(frozen_prediction_ids(frozen))}",
        f"  findings           : {summarize(findings)}",
        f"  blocking           : {len(blocking(findings))}",
    ]
    for f in findings:
        lines.append(f"  {'BLOCK' if f.blocking else 'note '}  {f}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - CLI
    import argparse

    ap = argparse.ArgumentParser(description="Audit the live prediction ledger against the frozen pre-registration (#3511)")
    ap.add_argument("--as-of", default=None, help="date the audit speaks for (default: today, PT)")
    ap.add_argument("--json", action="store_true", help="emit findings as JSON")
    args = ap.parse_args(argv)

    frozen = load_frozen()
    findings, rows = audit_live(as_of=args.as_of, frozen=frozen)
    if args.json:
        print(json.dumps([f.__dict__ for f in findings], indent=2))
    else:
        print(render_report(findings, rows, frozen))
    return 1 if blocking(findings) else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
