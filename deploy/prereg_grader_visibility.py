#!/usr/bin/env python3
"""deploy/prereg_grader_visibility.py — the live, READ-ONLY half of the #5518 contract: is every sealed
pre-registration row on the production table visible to its grader, and is any of them overdue?

The unit half is tests/test_sealed_prereg_graders_5518.py (a synthetic document in the sealed file's shape; the
private original too, when it is available and hashes to the seal). This script asks the same questions of the live
rows, with the graders' OWN predicates — never a re-typed copy:

  * hypotheses: ``compute.sealed_hypotheses.is_sealed`` / ``grader_visible`` (the engine's loader);
  * predictions: ``coach.prereg_overdue.is_sealed_prediction`` / ``grader_visible`` (the evaluator's scan) over
    ``coach_prediction_evaluator.GRADING_COACH_IDS`` (operational AND retired seats);
  * overdue: ``coach.prereg_overdue.overdue`` (the dead-man's own rule).

``--prereg PATH`` (optional) is the private original of the sealed pre-registration. It is read only when its bytes
hash to the published seal (deploy/generated/genesis_preregistration.sha256.json); then every hypothesis_id and
prediction it seals (ids by ``prereg_provenance_gate.frozen_prediction_ids``, the seeder's derivation) must have a
live row. The file is never copied, printed or written anywhere: only ids are reported.

``--grade-dry-run`` prints, for each sealed hypothesis whose window has closed and is still open, the verdict the
engine's window grade WOULD write (``sealed_hypotheses.grade_closed_window`` over the engine's own ``gather_data``,
``build_data_narrative``, ``evaluate_test_spec``, ``deterministic_evidence``). Every call on that path is a DynamoDB
Query; nothing is put, updated, emitted or invoked.

WRITES NOTHING: DynamoDB Query only. No PutItem/UpdateItem, no PutMetricData, no Lambda invoke, no S3.

Exit 0 when every sealed row is visible and none is overdue (and, with --prereg, none is missing); 1 otherwise.

    python3 deploy/prereg_grader_visibility.py [--today YYYY-MM-DD] [--prereg PATH] [--grade-dry-run] [--json]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
for _p in (REPO / "lambdas" / "compute", REPO / "lambdas" / "coach", REPO / "lambdas", REPO / "deploy"):
    sys.path.insert(0, str(_p))
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")

SEAL_STAMP = REPO / "deploy" / "generated" / "genesis_preregistration.sha256.json"


def load_sealed_doc(path: str) -> dict:
    """The private original, only when its bytes are the sealed bytes (a redacted copy is never the seal)."""
    raw = Path(path).read_bytes()
    want = json.loads(SEAL_STAMP.read_text())["sha256"]
    got = hashlib.sha256(raw).hexdigest()
    if got != want:
        raise SystemExit(f"--prereg {path}: sha256 {got[:12]}… is not the published seal {want[:12]}… — refusing to read it")
    return json.loads(raw)


def _query(table, pk: str, prefix: str) -> list:
    kwargs = {"KeyConditionExpression": "pk = :pk AND begins_with(sk, :p)", "ExpressionAttributeValues": {":pk": pk, ":p": prefix}}
    out = []
    while True:
        resp = table.query(**kwargs)
        out.extend(resp.get("Items", []))
        if "LastEvaluatedKey" not in resp:
            return out
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


def survey(table, today: str, coach_ids, hypotheses_pk: str) -> list[dict]:
    """One record per sealed row of the current cycle, with the graders' verdicts on it."""
    from coach import prereg_overdue
    from compute import sealed_hypotheses

    members = []
    for h in _query(table, hypotheses_pk, "HYPOTHESIS#"):
        if sealed_hypotheses.is_sealed(h):
            members.append(
                {
                    "kind": "hypothesis",
                    "id": h.get("hypothesis_id"),
                    "pk": h["pk"],
                    "sk": h["sk"],
                    "phase": h.get("phase"),
                    "status": h.get("status"),
                    "due": prereg_overdue.hypothesis_horizon(h),
                    "visible": sealed_hypotheses.grader_visible(h),
                    "overdue": prereg_overdue.overdue(h, "hypothesis", today) is not None,
                    "_row": h,
                }
            )
    for c in coach_ids:
        for p in _query(table, f"COACH#{c}", "PREDICTION#"):
            if prereg_overdue.is_sealed_prediction(p):
                members.append(
                    {
                        "kind": "prediction",
                        "id": p.get("prediction_id"),
                        "pk": p["pk"],
                        "sk": p["sk"],
                        "phase": p.get("phase"),
                        "status": p.get("status"),
                        "due": prereg_overdue.prediction_horizon(p),
                        "visible": prereg_overdue.grader_visible(p),
                        "overdue": prereg_overdue.overdue(p, "prediction", today) is not None,
                    }
                )
    return members


def grade_dry_run(members: list[dict], today: str) -> list[dict]:
    """The verdict the engine's window grade would write for each closed, open sealed hypothesis. Reads only."""
    import hypothesis_engine_lambda as eng
    from common.digest_utils import d2f
    from compute import sealed_hypotheses

    out = []
    for m in members:
        row = d2f(m.get("_row") or {})
        if m["kind"] != "hypothesis" or not sealed_hypotheses.due_for_window_grade(row, today):
            continue
        _h, status, evidence, stats, resolution = sealed_hypotheses.grade_closed_window(
            row, eng.gather_data, eng.build_data_narrative, eng.evaluate_test_spec, eng.deterministic_evidence
        )
        out.append(
            {
                "id": m["id"],
                "sk": m["sk"],
                "current_status": m["status"],
                "would_be": status,
                "resolution": resolution,
                "evidence": evidence,
                "stats": stats,
            }
        )
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--today", help="the Pacific day to judge as of (default: today, Pacific)")
    ap.add_argument("--prereg", help="path to the PRIVATE original of the sealed pre-registration (seal-checked)")
    ap.add_argument("--grade-dry-run", action="store_true", help="print the verdict each closed sealed hypothesis would get")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    import boto3
    import coach_prediction_evaluator as ev
    from common.pacific_time import pacific_today

    today = args.today or pacific_today()
    table = boto3.resource("dynamodb", region_name=os.environ["AWS_REGION"]).Table(os.environ["TABLE_NAME"])
    members = survey(table, today, ev.GRADING_COACH_IDS, ev.HYPOTHESES_PK)

    missing = []
    if args.prereg:
        import prereg_provenance_gate

        doc = load_sealed_doc(args.prereg)
        have = {(m["kind"], m["id"]) for m in members}
        missing = [f"hypothesis {h['hypothesis_id']}" for h in doc.get("hypotheses", []) if ("hypothesis", h["hypothesis_id"]) not in have]
        missing += [
            f"prediction {pid}" for pid in sorted(prereg_provenance_gate.frozen_prediction_ids(doc)) if ("prediction", pid) not in have
        ]

    grades = grade_dry_run(members, today) if args.grade_dry_run else []
    public = [{k: v for k, v in m.items() if k != "_row"} for m in members]
    bad = [m for m in public if not m["visible"] or m["overdue"]]
    if args.json:
        print(json.dumps({"as_of": today, "members": public, "missing": missing, "grade_dry_run": grades}, indent=2, default=str))
    else:
        print(f"sealed rows of the current cycle as of {today}: {len(public)}")
        for m in public:
            flag = "OK " if m["visible"] and not m["overdue"] else "BAD"
            print(
                f"  {flag} {m['kind']:<10} {m['pk']}/{m['sk']}  phase={m['phase']} status={m['status']} due={m['due']} visible={m['visible']} overdue={m['overdue']}"
            )
        for line in missing:
            print(f"  MISSING {line}")
        for g in grades:
            print(f"  DRY-RUN {g['id']} {g['sk']}: {g['current_status']} -> {g['would_be']} ({g['resolution']})\n      {g['evidence']}")
        print("dry run — nothing written." if args.grade_dry_run else "read-only — nothing written.")
    return 1 if bad or missing else 0


if __name__ == "__main__":
    sys.exit(main())
