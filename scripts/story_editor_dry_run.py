#!/usr/bin/env python3
"""scripts/story_editor_dry_run.py — one past week through writer draft → editor → hard gates, every write blocked (#6179).

PRIVATE OUTPUT. It prints the week's draft, the editor's revision, the mechanical no-new-claims check and the hard-gate
results. Redirect it into a private folder, never into the repo, a PR or an issue: the evidence packet behind it is the
owner's data.

What it does:
  * blocks every AWS write before anything runs: any botocore operation that is not a read (Get/List/Query/Scan/
    BatchGet/Describe/Head) or a model call (InvokeModel/Converse/CountTokens) raises — so no DynamoDB, S3, SSM or
    CloudWatch write can happen, including the usage metrics the Bedrock chokepoint would normally emit;
  * reads the stored chronicle row for the week, its desk budget, the season ledger it saw and the two installments
    published before it, and rebuilds the week's dossier (all reads);
  * the writer draft is the row's stored text (``--draft stored``, default: no writer call) or a fresh writer call
    (``--draft write``);
  * runs ``story_editor.revise`` on it (at most two Haiku calls), then the hard gates (``_Gates.post_hard``: the
    deterministic gates and the Sonnet fact read) on the draft and on the revision.

It never calls ``story_pipeline.live_week``, never stores a row, never approves, publishes or re-drafts a week. Spend goes
through the laptop AI cap (``ai.dev_session_cap``: $5 a run). A typical run is a few cents.

    python3 scripts/story_editor_dry_run.py --week-end 2026-10-06 > <private dir>/editor_dry_run.txt
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

CHRONICLE_PK = "USER#matthew#SOURCE#chronicle"
_READ_PREFIXES = ("Get", "List", "Query", "Scan", "BatchGet", "Describe", "Head")
_MODEL_OPS = ("InvokeModel", "InvokeModelWithResponseStream", "Converse", "CountTokens")
BLOCKED: List[str] = []


def block_writes() -> None:
    """Refuse every AWS operation that is not a read or a model call, process-wide (botocore's one dispatch point)."""
    from botocore.client import BaseClient

    original = BaseClient._make_api_call

    def guarded(self, operation_name, api_params):
        if operation_name.startswith(_READ_PREFIXES) or operation_name in _MODEL_OPS:
            return original(self, operation_name, api_params)
        BLOCKED.append(f"{self.meta.service_model.service_name}:{operation_name}")
        raise PermissionError(f"dry run: {operation_name} on {self.meta.service_model.service_name} is a write and is blocked")

    BaseClient._make_api_call = guarded


def _strip_stored(md: str) -> str:
    """The stored row's text as the writer's format: title, body, footer — no machine stat header, no dek."""
    from content import story_pipeline

    lines = [ln for ln in (md or "").splitlines() if not story_pipeline._STAT_HEADER.match(ln)]
    return story_pipeline.strip_dek("\n".join(lines)).strip()


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--week-end", required=True, help="the stored week's end date, YYYY-MM-DD (an already-published week)")
    ap.add_argument("--draft", choices=("stored", "write"), default="stored")
    args = ap.parse_args(argv)

    block_writes()
    import boto3
    from ai import bedrock_client
    from content import story_dossier, story_editor, story_ledger, story_pipeline, story_writers

    spend: List[Dict[str, Any]] = []
    real = bedrock_client.invoke_with_retry

    def metered(body, model_name=None):
        resp = real(body, model_name)
        mid = bedrock_client.resolve_model_id(model_name)
        spend.append(
            {"model": model_name, "usage": resp.get("usage") or {}, "usd": bedrock_client.estimate_cost_usd(resp.get("usage") or {}, mid)}
        )
        return resp

    bedrock_client.invoke_with_retry = metered

    table = boto3.resource("dynamodb", region_name="us-west-2").Table("life-platform")
    wk = next((w for w in story_dossier.season_weeks(through=args.week_end) if w["end"] == args.week_end), None)
    if wk is None:
        print(f"{args.week_end} is not a season week end")
        return 2
    n = wk["week"]
    row = table.get_item(Key={"pk": CHRONICLE_PK, "sk": f"DATE#{args.week_end}"}).get("Item") or {}
    if row.get("status") != "published":
        print(f"refusing: the row for {args.week_end} is {row.get('status')!r}, not an already-published week")
        return 2
    dossier, _nye = story_dossier.week_dossier(table, wk)
    ledger = story_ledger.latest_visible(table, CHRONICLE_PK, args.week_end)
    previous = story_pipeline._published_before(table, CHRONICLE_PK, args.week_end, n)
    budget = json.loads(row.get("desk_budget_json") or "{}")
    g = story_pipeline._Gates(n, dossier, budget, ledger, None, previous)

    if args.draft == "write":
        draft, stop = story_writers.write_chronicle(dossier, budget, ledger, week=n, previous=previous.get(n - 1))
    else:
        draft, stop = _strip_stored(str(row.get("content_markdown") or "")), "end_turn"

    packet = story_editor.packet_for(dossier, budget, ledger, n, previous.get(n - 1))
    allowed = g.allowed | story_editor.packet_numbers(dossier, budget, ledger)
    rec = story_editor.revise(
        draft,
        packet=packet,
        allowed=allowed,
        notes_for=lambda body: story_editor.craft_notes(
            body, dossier=dossier, weight_known=g.weight_known, previous=g.previous, owner_lines=g.owner_lines
        )
        + story_editor.review_notes(body, dossier),
        hard_check=lambda text: g.post_deterministic(text, "end_turn"),
        log=lambda m: print(m, file=sys.stderr),
    )
    revised = rec.pop("text")
    hard_draft = g.post_hard(draft, stop)
    hard_revised = g.post_hard(revised, "end_turn") if revised != draft else hard_draft
    claims = story_editor.new_claims(revised, draft, packet, allowed)

    def words(md: str) -> int:
        return len(story_writers.split_title(md)[1].split())

    print(f"# Story editor dry run — week {n} (ending {args.week_end}), draft source: {args.draft}\n")
    print(
        f"editor model: {rec['model']} · writer model: {story_writers.WRITER_MODEL} · rounds: {len(rec['rounds'])} · accepted: {rec['accepted']}\n"
    )
    print(f"## The writer's draft ({words(draft)} body words)\n\n{draft}\n")
    print(f"## The editor's revision ({words(revised)} body words){' — IDENTICAL to the draft' if revised == draft else ''}\n\n{revised}\n")
    print("## Rounds\n")
    for r in rec["rounds"]:
        print(f"- round {r['round']}: {r['outcome']}")
        for k in ("notes_in", "why", "editor_notes"):
            for x in r.get(k) or []:
                print(f"    - {k}: {x}")
    print("\n## Mechanical no-new-claims check (final text against the draft and the packet)\n")
    print(
        "\n".join(f"- {c}" for c in claims)
        or "- nothing new: every number, date word, name, quotation and marker is in the draft or the packet"
    )
    print("\n## Hard gates (unchanged code: story_checks + exact quote + callback + the fact read)\n")
    print(f"### on the draft ({len(hard_draft)})\n" + ("\n".join(f"- {f}" for f in hard_draft) or "- none"))
    print(f"\n### on the revision ({len(hard_revised)})\n" + ("\n".join(f"- {f}" for f in hard_revised) or "- none"))
    print("\n## Advisory notes for the owner (what the row would carry; never a blocker)\n")
    print("\n".join(f"- {x}" for x in story_editor.advisory_lines({**rec, "text": revised})))
    total = sum(s["usd"] for s in spend)
    print("\n## Spend (list-price estimate, every model call in this run)\n")
    for s in spend:
        u = s["usage"]
        print(
            f"- {s['model']}: in {u.get('input_tokens', 0)} · out {u.get('output_tokens', 0)} · cache write "
            f"{u.get('cache_creation_input_tokens', 0)} · cache read {u.get('cache_read_input_tokens', 0)} · ${s['usd']:.4f}"
        )
    print(f"- editor only: ${rec['cost_usd']:.4f} · whole run: ${total:.4f}")
    print(f"\nwrites refused by the guard: {BLOCKED or 'none attempted'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
