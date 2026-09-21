#!/usr/bin/env python3
"""prereg_amendment.py — the public AMENDMENT record for an already-sealed
pre-registration (#3599 box 3, the second half).

WHY THIS EXISTS
───────────────
`deploy/prereg_truth_gate.py` refuses to MINT a seal that disagrees with the
platform's own facts. It deliberately binds new seals only — `genesis_prereg_stamp`
calls it after the idempotent already-stamped return — because the repair for a
PUBLISHED pre-registration is not a better seal. The bytes are content-addressed,
hash-stamped, and readers have been told they never change:

    curl -s https://averagejoematt.com/experiments/prereg/genesis-2026-09-06.json | shasum -a 256

Editing them would break that promise exactly as loudly as the defect being
repaired. So #3599 names the other move — "a wrong seal already published gets a
visible amendment record, never an edit" — and until now that sentence existed only
as prose in a refusal message. `genesis_prereg_stamp.main()` prints "the repair for
a published seal is a public amendment record" and there was no such record, no
shape for one, and nowhere to put it. This module is that shape.

WHAT AN AMENDMENT IS
────────────────────
A SEPARATE, APPEND-ONLY object published beside the seal it speaks about:

    generated/experiments/prereg/genesis-{genesis}.amendments.json
    → https://averagejoematt.com/experiments/prereg/genesis-{genesis}.amendments.json

It names the sealed sha256 it amends, states what the artifact claims, states what
is actually true, and leaves the sealed bytes untouched. Four invariants make it a
correction rather than a quiet second edit — all enforced in `validate_amendment`,
not merely described here:

  1. IT NAMES THE BYTES.   `amends.sha256` must equal the sha256 of the artifact
     handed in. A record that floats free of a specific seal could be re-pointed at
     any artifact later, which is the laundering this whole chain exists to stop.
  2. IT CARRIES NO ARTIFACT. A record holding `coaches`/`hypotheses`/`artifact` keys
     is a replacement pre-registration wearing an amendment's name. Refused.
  3. IT IS NEVER BACKDATED. `authored_at` is the real authoring moment and must be
     at or after the seal's `stamped_at` — the same honesty rule the stamp takes.
  4. IT APPENDS.           `sequence` is len(prior)+1 and every earlier record must
     survive byte-identical. An amendment ledger that can be rewritten is an edit
     surface with extra steps.

THE FACTS AN AMENDMENT IS JUDGED AGAINST — the trap this module refuses to walk into
────────────────────────────────────────────────────────────────────────────────────
The truth gate compares an artifact against TODAY's constants, which is right for a
seal being minted today and WRONG for a seal minted three cycles ago. Measured
read-only on 2026-09-20 over the live published seals:

    genesis 2026-09-05 (cycle 16)  BASELINE_MISMATCH x3 — "324.64 lbs" vs today's 327.34
    genesis 2026-09-06 (cycle 17)  BASELINE_MISMATCH x3 — "326.2 lbs"  vs today's 327.34

324.64 was cycle 16's own starting weight. Publishing an amendment that calls it
wrong would put a FALSE correction on the public record in the name of honesty. So
`facts_in_force()` refuses to resolve the comparands for any genesis other than the
current `EXPERIMENT_START_DATE` unless they are supplied explicitly on the command
line — "could not tell" is not "fine", the same fail-closed posture as the seal and
provenance gates. An amendment is only ever published against the facts that were in
force when the seal was minted.

WHAT THIS MODULE DOES NOT DO
────────────────────────────
It does not decide that an amendment SHOULD be published. Every finding here is a
claim about the platform in public, so the record is printed for review and written
only under `--apply` by an attended operator, exactly like the seal publish itself.
Nothing is written to S3 by import, by CI, or by any scheduled job.

Usage:
    python3 deploy/prereg_amendment.py                      # the standing verdict + the record it WOULD publish
    python3 deploy/prereg_amendment.py --artifact <path>    # audit a downloaded published seal instead
    python3 deploy/prereg_amendment.py --genesis 2026-09-05 --baseline-lbs 324.64   # a prior cycle, facts supplied
    python3 deploy/prereg_amendment.py --apply --author matthew --reason "<why>"    # attended publish
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (REPO_ROOT, REPO_ROOT / "lambdas", REPO_ROOT / "deploy"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import prereg_truth_gate as truth  # noqa: E402

REGION = "us-west-2"
S3_BUCKET = "matthew-life-platform"
SITE_URL = "https://averagejoematt.com"

RECORD_TYPE = "prereg_amendment"
LEDGER_TYPE = "prereg_amendment_ledger"
SCHEMA_VERSION = 1

#: Top-level keys that would make the record a replacement artifact rather than a
#: correction of one. Invariant 2 — checked by name, because "it's obviously not an
#: artifact" is exactly what a 400-line JSON blob says about itself.
FORBIDDEN_PAYLOAD_KEYS = ("coaches", "hypotheses", "plan_facts", "artifact", "corrected_artifact", "replaces")

EFFECT = (
    "The sealed bytes stand unchanged and their sha256 still verifies. This record is the "
    "correction of record: read it alongside the seal, not instead of it."
)


class FactsNotInForce(RuntimeError):
    """The comparands for this genesis are not resolvable from the repo as it stands."""


def amendment_key(genesis: str) -> str:
    return f"generated/experiments/prereg/genesis-{genesis}.amendments.json"


def amendment_url(genesis: str) -> str:
    return f"{SITE_URL}/experiments/prereg/genesis-{genesis}.amendments.json"


# ──────────────────────────────────────────────────────────────────────────────
# the facts an amendment is judged against
# ──────────────────────────────────────────────────────────────────────────────


def facts_in_force(genesis: str, *, baseline_lbs: float | None = None, coach_bylines: dict[str, str] | None = None) -> dict[str, Any]:
    """The comparands that were in force at `genesis`, or raise.

    Today's repo constants describe the CURRENT cycle. For any earlier genesis they
    are a different cycle's facts, and an amendment built from them would publish a
    correction that is itself untrue (the 324.64 case in the module docstring). So
    the supplied values win, and when they are absent for a non-current genesis this
    raises rather than quietly substituting today's.
    """
    from common.constants import EXPERIMENT_START_DATE

    current = str(EXPERIMENT_START_DATE)
    registry_bylines, retired = truth.repo_coach_bylines()
    if coach_bylines is None and genesis != current:
        raise FactsNotInForce(
            f"genesis {genesis} is not the current cycle ({current}), so the persona registry as it stands today is "
            "NOT the roster that was in force when that seal was minted. Supply the roster explicitly, or amend only "
            "the current cycle's seal — an amendment judged against the wrong facts is a false correction published "
            "in the name of honesty."
        )
    if baseline_lbs is None and genesis != current:
        raise FactsNotInForce(
            f"genesis {genesis} is not the current cycle ({current}) — EXPERIMENT_BASELINE_WEIGHT_LBS today is that "
            "cycle's starting weight, not this one's. Pass --baseline-lbs with the weight that was in force at "
            f"{genesis} (the restart archive holds it), or amend only the current cycle's seal."
        )
    bylines = dict(coach_bylines) if coach_bylines is not None else registry_bylines
    if not bylines:
        raise FactsNotInForce(
            "the persona registry resolved to zero operational coaches — refusing to vouch for an amendment it cannot check"
        )
    return {
        "basis": "repo-constants-at-current-genesis" if genesis == current else "supplied-for-a-prior-cycle",
        "baseline_weight_lbs": float(baseline_lbs) if baseline_lbs is not None else truth.repo_baseline_lbs(),
        "baseline_source": (
            "lambdas/common/constants.EXPERIMENT_BASELINE_WEIGHT_LBS" if baseline_lbs is None else "supplied on the command line"
        ),
        "operational_coaches": bylines,
        "coach_source": "lambdas/coach/persona_registry" if coach_bylines is None else "supplied on the command line",
        "retired_coaches": list(retired),
    }


def standing_findings(artifact: dict, facts: dict) -> list[truth.Finding]:
    """The truth-gate findings against a PUBLISHED artifact, judged at `facts`."""
    return truth.blocking(
        truth.audit_prereg_truth(
            artifact,
            baseline_lbs=float(facts["baseline_weight_lbs"]),
            coach_bylines=dict(facts["operational_coaches"]),
            retired_ids=tuple(facts.get("retired_coaches") or ()),
        )
    )


# ──────────────────────────────────────────────────────────────────────────────
# the record
# ──────────────────────────────────────────────────────────────────────────────


def correction_for(finding: truth.Finding, facts: dict) -> dict[str, Any]:
    """One correction entry: what the seal says, and what is true instead.

    `correct_value` is resolved from the same facts the finding was judged against —
    never restated by hand, or the amendment could disagree with its own comparand.
    A kind with no single true value says so in `correction_unknown_reason`; an
    entry may not be silent on both.
    """
    entry: dict[str, Any] = {
        "kind": finding.kind,
        "where": finding.where,
        "sealed_claim": finding.detail,
        "correct_value": None,
        "correction_unknown_reason": None,
        "status": "standing",
    }
    if finding.kind == truth.BASELINE_MISMATCH:
        entry["correct_value"] = f"{facts['baseline_weight_lbs']} lbs"
    elif finding.kind == truth.COACH_NAME_MISMATCH:
        coach_id = finding.where.split(".")[-1]
        entry["correct_value"] = facts["operational_coaches"].get(coach_id)
    elif finding.kind == truth.COACH_NOT_OPERATIONAL:
        entry["correction_unknown_reason"] = (
            "the seat does not exist, so there is no corrected byline — the bets sealed under it are withdrawn, "
            f"not re-attributed (operational seats: {sorted(facts['operational_coaches'])})"
        )
    elif finding.kind == truth.MIN_EFFECT_UNDERIVED:
        entry["correction_unknown_reason"] = (
            "the pre-registered bar was never derived from a measured variance, so it cannot be restated here; "
            "the hypothesis is graded as ungraded-by-construction for this cycle (experiment/prereg_effect."
            "derive_min_effect emits the block a future seal carries)"
        )
    return entry


def build_amendment(
    artifact_bytes: bytes,
    stamp: dict,
    findings: list[truth.Finding],
    facts: dict,
    *,
    author: str,
    reason: str,
    sequence: int = 1,
    now: datetime | None = None,
) -> dict[str, Any]:
    """The amendment record for `findings` against the seal `stamp` describes."""
    genesis = str(stamp.get("genesis") or "")
    authored_at = (now or datetime.now(timezone.utc)).isoformat()
    return {
        "record_type": RECORD_TYPE,
        "schema_version": SCHEMA_VERSION,
        "amendment_id": f"genesis-{genesis}/A{sequence}",
        "sequence": sequence,
        "genesis": genesis,
        "amends": {
            "artifact_url": stamp.get("public_artifact_url"),
            "sha256": hashlib.sha256(artifact_bytes).hexdigest(),
            "stamped_at": stamp.get("stamped_at"),
        },
        "authored_at": authored_at,
        "authored_by": author,
        "reason": reason,
        "facts_basis": facts,
        "corrections": [correction_for(f, facts) for f in findings],
        "effect": EFFECT,
        "verify": f"curl -s {stamp.get('public_artifact_url')} | shasum -a 256   # still {stamp.get('sha256')}",
    }


def validate_amendment(record: dict, *, artifact_bytes: bytes, prior: list[dict] | None = None) -> list[str]:
    """Every way `record` fails to be an amendment. [] means it may be published."""
    prior = list(prior or [])
    problems: list[str] = []
    if record.get("record_type") != RECORD_TYPE:
        problems.append(f"record_type is {record.get('record_type')!r}, not {RECORD_TYPE!r}")
    if record.get("schema_version") != SCHEMA_VERSION:
        problems.append(f"schema_version {record.get('schema_version')!r} is not the shipped {SCHEMA_VERSION}")

    # 1 — it names the bytes.
    sealed = hashlib.sha256(artifact_bytes).hexdigest()
    named = (record.get("amends") or {}).get("sha256")
    if named != sealed:
        problems.append(f"amends.sha256 {named!r} is not the sha256 of the artifact handed in ({sealed}) — an amendment names ONE seal")

    # 2 — it carries no artifact.
    carried = [k for k in FORBIDDEN_PAYLOAD_KEYS if k in record]
    if carried:
        problems.append(f"carries artifact payload {carried} — that is a replacement pre-registration, not an amendment of one")

    # 3 — it is never backdated.
    authored_at = str(record.get("authored_at") or "")
    stamped_at = str((record.get("amends") or {}).get("stamped_at") or "")
    if not authored_at:
        problems.append("no authored_at — an amendment states its real moment")
    elif stamped_at and authored_at < stamped_at:
        problems.append(f"authored_at {authored_at} predates the seal it amends ({stamped_at}) — records are never backdated")

    # 4 — it appends.
    if record.get("sequence") != len(prior) + 1:
        problems.append(f"sequence {record.get('sequence')!r} is not {len(prior) + 1} — the ledger appends, it never rewrites")
    if any(p.get("amendment_id") == record.get("amendment_id") for p in prior):
        problems.append(f"amendment_id {record.get('amendment_id')!r} already exists in the ledger")

    # the corrections themselves
    corrections = record.get("corrections")
    if not isinstance(corrections, list) or not corrections:
        problems.append("no corrections — an amendment with nothing to correct is noise on the public record")
        corrections = []
    for i, c in enumerate(corrections):
        if not isinstance(c, dict):
            problems.append(f"corrections[{i}] is not an object")
            continue
        if c.get("kind") not in truth.FINDING_KINDS:
            problems.append(f"corrections[{i}].kind {c.get('kind')!r} is outside the gate's finding kinds {list(truth.FINDING_KINDS)}")
        if not c.get("correct_value") and not c.get("correction_unknown_reason"):
            problems.append(f"corrections[{i}] states neither a corrected value nor why there is none")
    return problems


def append_to_ledger(existing: dict | None, record: dict) -> dict:
    """The ledger `record` would be appended to. Refuses to alter a published entry."""
    prior = list((existing or {}).get("amendments") or [])
    return {
        "record_type": LEDGER_TYPE,
        "schema_version": SCHEMA_VERSION,
        "genesis": record.get("genesis"),
        "note": "Append-only. A published amendment is never edited or removed; a later record supersedes an earlier one by sequence.",
        "amendments": [*prior, record],
    }


def load_ledger(genesis: str, s3=None) -> dict | None:
    """The published ledger for `genesis`, or None. Read-only."""
    if s3 is None:  # pragma: no cover - credentialed path
        import boto3

        s3 = boto3.client("s3", region_name=REGION)
    try:
        body = s3.get_object(Bucket=S3_BUCKET, Key=amendment_key(genesis))["Body"].read()
    except Exception:
        return None
    return json.loads(body)


def publish(record: dict, artifact_bytes: bytes, s3=None) -> dict:
    """Append `record` to the published ledger. Attended only — the CLI reaches this
    under --apply, nothing else does. Validates against the LIVE ledger first, so a
    record built against a stale view of it cannot overwrite an entry."""
    if s3 is None:  # pragma: no cover - credentialed path
        import boto3

        s3 = boto3.client("s3", region_name=REGION)
    genesis = str(record.get("genesis") or "")
    existing = load_ledger(genesis, s3=s3)
    prior = list((existing or {}).get("amendments") or [])
    problems = validate_amendment(record, artifact_bytes=artifact_bytes, prior=prior)
    if problems:
        raise SystemExit("REFUSED — this is not a publishable amendment:\n  - " + "\n  - ".join(problems))
    ledger = append_to_ledger(existing, record)
    s3.put_object(
        Bucket=S3_BUCKET,
        Key=amendment_key(genesis),
        Body=(json.dumps(ledger, indent=2) + "\n").encode("utf-8"),
        ContentType="application/json",
        CacheControl="public, max-age=300",
    )
    return ledger


def render(record: dict, findings: list[truth.Finding]) -> str:
    lines = [
        f"prereg amendment (#3599) — {record['amendment_id']}",
        f"  amends            : {record['amends']['artifact_url']}",
        f"  sealed sha256     : {record['amends']['sha256']}",
        f"  facts basis       : {record['facts_basis']['basis']} (baseline {record['facts_basis']['baseline_weight_lbs']} lbs)",
        f"  corrections       : {truth.summarize(findings) or 'none'}",
        f"  would publish to  : {amendment_url(record['genesis'])}",
    ]
    for c in record["corrections"]:
        lines.append(f"  {c['kind']} {c['where']} -> {c['correct_value'] or c['correction_unknown_reason']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - CLI
    import argparse

    ap = argparse.ArgumentParser(description="Build (and, attended, publish) the amendment record for a sealed pre-registration (#3599)")
    ap.add_argument("--artifact", default=None, help=f"sealed artifact to amend (default: {truth.FROZEN_PATH})")
    ap.add_argument("--stamp", default=None, help="its hash stamp (default: the sidecar beside the frozen file)")
    ap.add_argument("--genesis", default=None, help="genesis of the seal, when auditing a downloaded artifact")
    ap.add_argument(
        "--baseline-lbs", type=float, default=None, help="the starting weight in force at that genesis (required for a prior cycle)"
    )
    ap.add_argument(
        "--coach-bylines",
        default=None,
        help='the roster in force at that genesis: a JSON file, or inline {"id": "byline"} (required for a prior cycle)',
    )
    ap.add_argument("--author", default="matthew", help="who is making the correction")
    ap.add_argument(
        "--reason", default="The sealed pre-registration disagrees with the platform's own facts; the bytes stand, this corrects them."
    )
    ap.add_argument("--apply", action="store_true", help="publish the record to S3 (attended; default is print-only)")
    args = ap.parse_args(argv)

    artifact_path = Path(args.artifact) if args.artifact else truth.FROZEN_PATH
    artifact_bytes = artifact_path.read_bytes()
    artifact = json.loads(artifact_bytes)
    genesis = args.genesis or str(artifact.get("genesis") or "")

    if args.stamp:
        stamp = json.loads(Path(args.stamp).read_text())
    else:
        import genesis_prereg_stamp as gps

        stamp = gps.load_stamp() or {}
        if stamp.get("genesis") != genesis:
            stamp = {
                "genesis": genesis,
                "sha256": hashlib.sha256(artifact_bytes).hexdigest(),
                "stamped_at": str(artifact.get("generated_at") or ""),
                "public_artifact_url": f"{SITE_URL}/experiments/prereg/genesis-{genesis}.json",
            }

    bylines = None
    if args.coach_bylines:
        raw = Path(args.coach_bylines)
        bylines = json.loads(raw.read_text() if raw.exists() else args.coach_bylines)

    try:
        facts = facts_in_force(genesis, baseline_lbs=args.baseline_lbs, coach_bylines=bylines)
    except FactsNotInForce as e:
        print(f"REFUSED — the facts this seal must be judged against are not resolvable:\n  {e}")
        return 2
    findings = standing_findings(artifact, facts)
    if not findings:
        print(f"genesis {genesis}: the published seal agrees with the facts in force — nothing to amend.")
        return 0

    prior = list((load_ledger(genesis) or {}).get("amendments") or []) if args.apply else []
    record = build_amendment(artifact_bytes, stamp, findings, facts, author=args.author, reason=args.reason, sequence=len(prior) + 1)
    problems = validate_amendment(record, artifact_bytes=artifact_bytes, prior=prior)
    print(render(record, findings))
    if problems:
        print("\nNOT PUBLISHABLE:\n  - " + "\n  - ".join(problems))
        return 1
    if not args.apply:
        print("\nDRY RUN — the record above is what --apply would append. The sealed bytes are never touched.")
        print(json.dumps(record, indent=2))
        return 0
    publish(record, artifact_bytes)
    print(f"\nPUBLISHED {record['amendment_id']} → {amendment_url(genesis)}")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI
    sys.exit(main())
