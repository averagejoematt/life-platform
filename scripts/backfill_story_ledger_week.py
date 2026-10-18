#!/usr/bin/env python3
"""scripts/backfill_story_ledger_week.py — write the season-ledger row a legacy-writer installment never got (#4533, #4914).

WHY. Week 6 ("The Quiet Accumulation", ``DATE#2026-10-13``) fell to the LEGACY writer (the desk failed on the open-ask
follow-up, #4914), so chronicle-approve had no ``desk_ledger_json`` to commit and no ``LEDGER#2026-10-13`` row exists.
The ``story_season:ledger_advanced`` qa-smoke check (alarm ``qa-smoke-failures``) fails on the gap, and week 7's desk
would read the wk5 row as "last week" and re-demand things wk6 already moved.

WHAT IT DOES. Reads (a) the published installment ``DATE#{date}`` and (b) the newest visible ledger row before it (through
``story_ledger.latest_visible`` — the one read door), then builds the SAME row the desk would have left by feeding a
*budget* derived from the installment's text through ``story_ledger.apply_budget`` — no second implementation of the
ledger's rules. The row is written with ``story_ledger.ledger_row`` (+ the write-time stamp, as chronicle-approve does)
under ``attribute_not_exists(sk)``: a second ``--apply`` is a no-op.

WHAT IT WILL NOT INVENT. Only what the text states is derived:
  * every open thread of the previous row is ACCOUNTED FOR as a ``hold`` (status and last_week unchanged — a legacy
    installment did not run the continuity desk, so no thread is claimed to have advanced); the thread carries
    ``wk{N}_accounting`` with ``backfilled: true, source: legacy-installment`` and whether its title appears in the text;
  * the previous row's open bet is scored only when it is an ``hrv_mean_ms`` bet, its rule parses, and the installment
    states the 7-day rolling average; otherwise it stays open (carried);
  * the featured coach is the persona(s) quoted in a blockquote (the interview); none → none;
  * the lead thread, the beats used, arc updates and the throughline are NOT derivable from prose — the lead entry is
    written with ``thread_id: null`` and ``backfilled: true``; beats/arcs are left as the previous row had them;
  * asks are carried UNCHANGED (no ``carried_weeks`` increment: counting a carry the desk never made could escalate an
    ask to the reply desk on a week that never followed it up).
  The row's ``backfill`` block names every field it could not derive.

RUN:  AWS_MAX_ATTEMPTS=1 python3 scripts/backfill_story_ledger_week.py --week 6 --date 2026-10-13 --dry-run [--report PATH]
      AWS_MAX_ATTEMPTS=1 python3 scripts/backfill_story_ledger_week.py --week 6 --date 2026-10-13 --apply     # DRIVER / OWNER ONLY
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import sys
from typing import Any, Dict, List, Optional, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))
os.environ.setdefault("AWS_MAX_ATTEMPTS", "1")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from content import story_ledger  # noqa: E402

TABLE = "life-platform"
PK = "USER#matthew#SOURCE#chronicle"
SOURCE = "legacy-installment"
FLAG = {"backfilled": True, "source": SOURCE}


class BackfillError(RuntimeError):
    """A precondition the backfill refuses to proceed past (nothing is written)."""


def _mentions(thread: Dict[str, Any], text: str) -> bool:
    title = re.sub(r"^(the|a)\s+", "", str(thread.get("title") or "").lower()).strip()
    return bool(title) and title in text.lower()


def score_open_bet(bet: Dict[str, Any], text: str) -> Optional[Dict[str, str]]:
    """``{result, note}`` when the installment states what this bet's rule needs, else None (the bet stays open).

    Supported honestly: a ``hrv_mean_ms`` bet whose rule is ``... <op> N`` against a "7-day rolling average ... N ms"
    sentence. Anything else is not guessed."""
    if bet.get("metric") != "hrv_mean_ms":
        return None
    rule = re.search(r"(>=|<=|>|<)\s*(\d+(?:\.\d+)?)\s*(?:ms)?\s*$", str(bet.get("rule") or "").strip())
    sentence = next(
        (s for s in re.split(r"(?<=[.!?])\s+", text) if re.search(r"7-day rolling average[^.]*?\d+(?:\.\d+)?\s*(?:milliseconds|ms)", s)),
        None,
    )
    if not rule or not sentence:
        return None
    m = re.search(r"7-day rolling average[^.]*?(\d+(?:\.\d+)?)\s*(?:milliseconds|ms)", sentence)
    value, bound = float(m.group(1)), float(rule.group(2))  # type: ignore[union-attr]
    ok = {">=": value >= bound, "<=": value <= bound, ">": value > bound, "<": value < bound}[rule.group(1)]
    return {
        "result": "right" if ok else "wrong",
        "note": f"Scored from the published installment (legacy writer, backfilled): {sentence.strip()}  Rule {bet.get('rule')!r}; stated value {value:g}.",
    }


def featured_coaches(text: str, roster: List[Dict[str, str]]) -> List[str]:
    """Coach ids whose name appears in a blockquote line (the week's interview), in roster order."""
    quoted = " ".join(ln for ln in text.splitlines() if ln.lstrip().startswith(">")).lower()
    return [r["coach_id"] for r in roster if r.get("name") and r["name"].lower() in quoted]


def derive_row(prev: Dict[str, Any], item: Dict[str, Any], *, week: int, date: str, roster: List[Dict[str, str]]) -> Dict[str, Any]:
    """The ledger the desk would have left, built through ``apply_budget``. Pure."""
    text = str(item.get("content_markdown") or "")
    if not text.strip():
        raise BackfillError("the installment has no content_markdown to derive from")
    title = str(item.get("title") or "").strip()
    if not title:
        raise BackfillError("the installment has no title")
    prev = copy.deepcopy(prev)
    budget: Dict[str, Any] = {
        "thread_actions": [{"thread_id": t["id"], "action": "hold"} for t in story_ledger.open_threads(prev)],
        "featured_coaches": featured_coaches(text, roster),
        "lead": {"thread_id": None, "angle": None},
    }
    bet = story_ledger.last_open_bet(prev)
    scored = score_open_bet(bet, text) if bet else None
    if scored:
        budget["bet_scored"] = scored
    findings = story_ledger.continuity_findings(prev, budget, week)
    if not scored:  # an ungradable bet is carried and flagged below — the desk's "score it" demand cannot be met from prose
        findings = [f for f in findings if "bet" not in f]
    if findings:
        raise BackfillError("the derived budget fails the desk's own continuity check: " + "; ".join(findings))
    led = story_ledger.apply_budget(prev, budget, week=week, date=date, title=title)

    underived = [
        "lead.thread_id",
        "lead.angle",
        "beats",
        "arc_updates",
        "throughline_advanced",
        "asks_followed_up",
        "coach_asks",
        "bet (new)",
    ]
    accounting = f"wk{week}_accounting"
    for t in led["threads"]:
        if t.get("status") in ("open", "advanced"):
            t[accounting] = {"action": "hold", "mentioned_in_text": _mentions(t, text), **FLAG}
    led["leads"][-1].update(FLAG)
    for f in led["featured"]:
        if f.get("week") == week:
            f.update({**FLAG, "basis": "quoted in the installment's blockquote"})
    if bet and scored:
        for b in led["bets"]:
            if b.get("week") == bet.get("week") and b.get("scored_week") == week:
                b.update(FLAG)
    elif bet:
        underived.append(f"bet week {bet.get('week')} result (stays open — the installment does not state it in a form the rule can grade)")
    open_asks = len(story_ledger.open_asks(led))
    led["backfill"] = {
        **FLAG,
        "week": week,
        "installment_sk": item.get("sk"),
        "installment_approved_at": item.get("approved_at"),
        "underived": underived,
        "asks_carried_unchanged": open_asks,
    }
    return led


def build(table: Any, week: int, date: str, *, cycle: Optional[str] = None) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """(ledger, row) for ``date`` — raises BackfillError on any failed precondition."""
    item = table.get_item(Key={"pk": PK, "sk": f"DATE#{date}"}).get("Item")
    if not item:
        raise BackfillError(f"no installment DATE#{date}")
    if item.get("status") != "published":
        raise BackfillError(f"DATE#{date} is {item.get('status')!r}, not published — nothing to backfill from")
    if int(item.get("week_number") or -1) != week:
        raise BackfillError(f"DATE#{date} is week {item.get('week_number')}, not {week}")
    cycle = cycle or story_ledger.current_cycle()
    if cycle is None:
        raise BackfillError("the experiment cycle is unreadable — refusing to guess it")
    prev = story_ledger.latest_visible(table, PK, date, cycle=cycle)
    if prev.get("week") != week - 1:
        raise BackfillError(f"the newest visible ledger row is week {prev.get('week')}, not {week - 1} — the chain has a gap")
    from content import story_dossier

    led = derive_row(prev, item, week=week, date=date, roster=story_dossier.roster())
    return led, story_ledger.ledger_row(PK, led, cycle=cycle)


def write(table: Any, row: Dict[str, Any]) -> bool:
    """Put the row under ``attribute_not_exists(sk)``. True = written, False = it already existed (no-op)."""
    from experiment.phase_taxonomy import experiment_stamp_for

    stamped = {**row, **experiment_stamp_for(row["pk"], row["sk"])}  # #3599: the class-gated write-time stamp, as chronicle-approve does
    try:
        table.put_item(Item=stamped, ConditionExpression="attribute_not_exists(sk)")
    except Exception as e:  # noqa: BLE001 — only the conditional failure is a no-op
        if getattr(e, "response", {}).get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return False
        raise
    return True


def summary(prev_week: int, led: Dict[str, Any]) -> str:
    wk = led["week"]
    lines = [f"LEDGER#{led['date']}  week {wk}  title {led['titles'][-1]['title']!r}  (derived from the legacy installment)"]
    for t in led["threads"]:
        acc = t.get(f"wk{wk}_accounting")
        lines.append(
            f"  thread {t['id']:32s} {t['status']:9s} last_week={t.get('last_week')}  "
            + (f"held, mentioned={acc['mentioned_in_text']}" if acc else "")
        )
    for b in led["bets"]:
        lines.append(f"  bet wk{b.get('week')} result={b.get('result')} scored_week={b.get('scored_week')}  {str(b.get('claim'))[:70]}")
    lines.append(f"  featured wk{wk}: {[f['coach_id'] for f in led['featured'] if f.get('week') == wk]}")
    lines.append(f"  asks: {len(led.get('asks', []))} total, {len(story_ledger.open_asks(led))} open (carried unchanged)")
    lines.append(f"  underived (flagged): {led['backfill']['underived']}")
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--week", type=int, required=True)
    ap.add_argument("--date", required=True, help="the installment date, YYYY-MM-DD (the LEDGER#/DATE# key)")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="print the full row, write nothing (default)")
    mode.add_argument("--apply", action="store_true", help="write the row (attribute_not_exists — a second apply is a no-op)")
    ap.add_argument("--report", help="write the derived row + summary as JSON to this path")
    args = ap.parse_args(argv)

    import boto3
    from botocore.config import Config

    table = boto3.resource("dynamodb", "us-west-2", config=Config(read_timeout=60, retries={"max_attempts": 1})).Table(TABLE)
    existing = table.get_item(Key={"pk": PK, "sk": f"{story_ledger.LEDGER_PREFIX}{args.date}"}).get("Item")
    if existing:
        print(f"LEDGER#{args.date} already exists (cycle {existing.get('cycle')}) — nothing to do.")
        return 0
    try:
        led, row = build(table, args.week, args.date)
    except BackfillError as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        return 2
    print(summary(args.week - 1, led))
    print("\nfull row (ledger_json):")
    print(json.dumps(led, indent=2, ensure_ascii=False))
    if args.report:
        with open(args.report, "w") as fh:
            json.dump({"sk": row["sk"], "cycle": row["cycle"], "phase": row["phase"], "ledger": led}, fh, indent=2, ensure_ascii=False)
    if not args.apply:
        print("\nDRY RUN — nothing written.")
        return 0
    print("\nwritten." if write(table, row) else "\nrow already existed — no-op.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
