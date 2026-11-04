#!/usr/bin/env python3
"""coach_provenance_dry_run.py — per coach, the provenance the next scheduled coach v2 read would be stamped with.

Owner ruling 2026-11-03: a coach read reaches a public route only when its provenance names no private family. This
script runs the CONTEXT ASSEMBLY of the daily brief's seven coach reads against live data and prints, per coach, the
source families its prompt would carry, which inputs carry each one, and the resulting publication eligibility.

READ-ONLY, NO MODEL CALL:
  * every AWS API call whose operation is not a read is refused (botocore ``_make_api_call`` guard) and counted;
  * the computation engine is not invoked — its latest stored package (COACH#computation RESULTS#) is read instead;
  * the orchestrator's Haiku step is not run — its state is gathered and its deterministic injections rendered;
  * semantic recall is not run (it embeds through Bedrock) — its possible contribution is printed per corpus kind;
  * nothing generated is printed: family names, input names, counts and the eligibility reason only.

Usage: python3 scripts/coach_provenance_dry_run.py [--json]
"""

from __future__ import annotations

import json
import os
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lambdas"))
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("EMAIL_RECIPIENT", "dry-run@example.com")  # the brief module refuses to import without them; nothing is sent
os.environ.setdefault("EMAIL_SENDER", "dry-run@example.com")

READ_OPERATIONS = frozenset(
    {
        "GetItem",
        "BatchGetItem",
        "Query",
        "Scan",
        "DescribeTable",
        "GetObject",
        "HeadObject",
        "ListObjectsV2",
        "GetParameter",
        "GetParameters",
    }
)
REFUSED: Counter = Counter()


def _install_read_only_guard() -> None:
    import botocore.client

    original = botocore.client.BaseClient._make_api_call

    def guarded(self, operation_name, api_params):
        if operation_name not in READ_OPERATIONS:
            REFUSED[f"{self.meta.service_model.service_name}:{operation_name}"] += 1
            raise RuntimeError(f"dry run: {operation_name} refused (read-only)")
        return original(self, operation_name, api_params)

    botocore.client.BaseClient._make_api_call = guarded


def _facts_block(table) -> str:
    """The pipeline's AUTHORITATIVE FACTS block (+ the forecast lines), built as `_run_coach_v2_pipeline` builds it."""
    from ai import grounded_generation
    from ai.forecast_prompt import forecast_prompt_lines
    from boto3.dynamodb.conditions import Key
    from experiment.canonical_facts import build_canonical_facts

    out = ""
    cm = table.query(KeyConditionExpression=Key("pk").eq("USER#matthew#SOURCE#computed_metrics"), ScanIndexForward=False, Limit=1)
    if cm.get("Items"):
        out = grounded_generation.authoritative_facts_block(
            {k: v for k, v in build_canonical_facts(cm["Items"][0]).items() if k != "as_of"}
        )
    fx = table.query(
        KeyConditionExpression=Key("pk").eq("USER#matthew#SOURCE#forecast") & Key("sk").begins_with("DATE#"),
        ScanIndexForward=False,
        Limit=1,
    )
    if fx.get("Items") and forecast_prompt_lines(fx["Items"][0].get("forecasts", [])):
        out += "\nMODEL EXPECTATIONS (...)"
    return out


def _brief_breakdown(state: dict, rendered: dict) -> dict:
    """Per orchestrator state part: its families, and how many stored rows it carries with no record."""
    from coach import coach_output_provenance as cop
    from common import narrative_provenance as NP

    out = {}
    for key, value in state.items():
        fams, upstream = cop.STATE_PARTS[key](rendered[key] if key in rendered else value)
        up_unrecorded = sum(1 for r in upstream if NP.record_of(r) is None)
        up_families = sorted({f for r in upstream for f in NP.merge_upstream(r) if f != NP.UNRECORDED})
        out[key] = {"families": sorted(set(fams) | set(up_families)), "rows": len(upstream), "rows_unrecorded": up_unrecorded}
    return out


def run() -> dict:
    _install_read_only_guard()
    import boto3
    from ai import ai_calls, ai_context, semantic_recall
    from ai.platform_memory import platform_memory_block
    from coach import (
        coach_brief_input_gate as gate,
        coach_input_facts as ci,
        coach_narrative_orchestrator as orch,
        coach_output_provenance as cop,
        coach_presence_gate as presence,
    )
    from common import narrative_provenance as NP
    from common.pacific_time import pacific_today, shift_day_key
    from emails import daily_brief_lambda as db

    table = boto3.resource("dynamodb", region_name="us-west-2").Table("life-platform")
    s3 = boto3.client("s3", region_name="us-west-2")
    today = pacific_today()
    data = db.gather_daily_data(db.fetch_profile(), shift_day_key(today, -1))
    comp_results = orch._query_latest("COACH#computation", "RESULTS#") or {}
    facts = _facts_block(table)
    inventory = gate.data_inventory(data)

    report = {"run_date": today, "coaches": {}, "refused_writes": {}}
    for coach_id, builder in sorted(cop.BUILDERS.items()):
        row: dict = {"held_absent": bool(presence.brief_hold(coach_id))}
        try:
            voice_spec = json.loads(s3.get_object(Bucket="matthew-life-platform", Key=f"config/coaches/{coach_id}.json")["Body"].read())
        except Exception:  # noqa: BLE001
            voice_spec = {}
        domain_data = ci.coach_inputs(coach_id, getattr(ai_context, builder)(data), data, table=table)
        state = orch._gather_all_state(coach_id)
        protocols = orch._protocols_for_brief(state.get("site_protocols"))
        engagement = orch._engagement_for_brief(state.get("engagement_signal"))
        journal_mood = orch._journal_mood_for_brief(state.get("journal_mood")) if orch._coach_wants_journal_mood(coach_id) else None
        rendered = {"site_protocols": protocols, "engagement_signal": engagement, "journal_mood": journal_mood}
        brief_record = cop.brief_provenance(state, rendered=rendered)
        cycle_ctx = orch._cycle_boundary_context(today)
        envelope = {"generation_brief": {"journal_mood": journal_mood, "cycle_boundary_context": cycle_ctx}, "provenance": brief_record}
        blocks = dict(
            brief=envelope,
            facts_block=facts,
            journal_mood_block=ai_calls._build_journal_mood_prompt_block(journal_mood, voice_spec),
            cycle_boundary_block=ai_calls._build_cycle_boundary_prompt_block(cycle_ctx),
            memory_block=platform_memory_block(coach_id=coach_id),
            recall=("", []),  # not run (Bedrock embedding) — see recall_if_run
            data_inventory=inventory,
            domain_data=domain_data,
            comp_results=comp_results,
            corrections_block=ai_calls._coach_corrections_block(coach_id),
        )
        carriers = cop.pipeline_families(coach_id, data, **blocks)
        updater = cop.updater_record(cop.pipeline_provenance(coach_id, data, **blocks))
        ok, reason = NP.eligibility(updater)
        row.update(
            publishable=ok,
            reason=reason,
            private={f: carriers.get(f, ["brief"]) for f in updater["families"] if NP.classify(f) == NP.PRIVATE},
            unclassified={f: carriers.get(f, ["brief"]) for f in updater["families"] if NP.classify(f) is None},
            public=sorted(f for f in updater["families"] if NP.classify(f) == NP.PUBLIC),
            brief_parts=_brief_breakdown(state, rendered),
            recall_if_run={k: cop.RECALL_KIND_FAMILIES.get(k) for k, on in semantic_recall.COACH_KIND_DECISIONS.items() if on},
        )
        report["coaches"][coach_id] = row
    report["refused_writes"] = dict(REFUSED)
    return report


def main() -> int:
    report = run()
    if "--json" in sys.argv:
        print(json.dumps(report, default=str))  # the LAST line: the modules under test print their own log lines
        return 0
    print(f"coach v2 provenance dry run — context as of {report['run_date']} (read-only; refused writes: {report['refused_writes'] or 0})")
    for coach_id, r in report["coaches"].items():
        verdict = "PUBLISHABLE" if r["publishable"] else f"WITHHELD ({r['reason']})"
        print(f"\n{coach_id}: {verdict}{'  [held: instrument absent — no read]' if r['held_absent'] else ''}")
        for label in ("private", "unclassified"):
            for fam, names in sorted(r[label].items()):
                print(f"  {label:12} {fam:22} <- {', '.join(names)}")
        print(f"  public       {', '.join(r['public'])}")
        unrec = {k: v["rows_unrecorded"] for k, v in r["brief_parts"].items() if v["rows_unrecorded"]}
        if unrec:
            print(f"  brief rows with no record: {unrec}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
