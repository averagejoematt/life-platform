#!/usr/bin/env python3
"""scripts/owner_outbound_volume.py — count what the platform sends the owner, per week, before and after the trial (#6176).

READ-ONLY. CloudWatch Logs ``FilterLogEvents``, CloudWatch ``GetMetricStatistics`` and DynamoDB ``Query``; nothing is
written, invoked or sent. It prints COUNTS only (no subjects, bodies or addresses), so its output can be shared.

WHAT IT COUNTS, per 7-day window ending on ``--end`` (default: yesterday, Pacific):
  * owner-directed sends by type — each type's own success log line (``SENDS``) or its own send marker in DynamoDB
    (``MARKER_SENDS``); a type with no countable record is reported as such, never as 0;
  * sends the trial suppressed — the ``[outbound-trial] {"event": "suppressed", ...}`` lines (``common.outbound_trial``);
  * Lambda errors per sending function (``AWS/Lambda Errors``);
  * owner responses — rows only he creates: evening check-ins, evening-ritual taps, story-question replies,
    and decisions (advice links and ask responses have their own sanctioned readers — read them in a session);
  * owner actions — ``Do:`` emails the ADR-170 digest sent, and chronicle drafts still waiting for approval after 7 days
    (the owner action measurably missed).

Log groups keep 30 days (90 for the DLQ consumer and the canary), so run it within 30 days of the window it reports.

Usage:
    python3 scripts/owner_outbound_volume.py --weeks 2 [--end YYYY-MM-DD] [--out PATH.md]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

PT = ZoneInfo("America/Los_Angeles")
REGION = "us-west-2"
TABLE = "life-platform"
USER = "matthew"

#: (type, log group, filter pattern) — one row per owner-directed send type counted from its success line.
SENDS: tuple[tuple[str, str, str], ...] = (
    ("Morning Brief", "/aws/lambda/daily-brief", '"Sent: Morning Brief"'),
    ("Evening nudge", "/aws/lambda/evening-nudge", '"[nudge] Sent:"'),
    ("Weekly Plate (Fri)", "/aws/lambda/weekly-plate", '"Sent:" "Weekly Plate"'),
    ("Nutrition Review (Sat)", "/aws/lambda/nutrition-review", '"Sent: Nutrition Review"'),
    ("Weekly Report (Sun)", "/aws/lambda/weekly-digest", '"Sent."'),
    ("Sunday 'what changed' (trial)", "/aws/lambda/weekly-digest", '"Sent (what changed)"'),
    ("Monday Compass", "/aws/lambda/monday-compass", '"Sent:" "Monday Compass"'),
    ("Monthly Coach's Letter", "/aws/lambda/monthly-digest", '"Sent:" "Monthly Coach"'),
    ("AI Review Pack (Sun)", "/aws/lambda/ai-review-pack", '"Sent:" "Review Pack"'),
    ("Chronicle preview / approval", "/aws/lambda/wednesday-chronicle", '"Preview email sent"'),
    ("Anomaly alert", "/aws/lambda/anomaly-detector", '"Alert email sent"'),
    ("LP alert digest (before ADR-170, 2026-11-22)", "/aws/lambda/life-platform-alert-digest", '"digest_sent"'),
    ("Do: owner action (ADR-170 digest)", "/aws/lambda/life-platform-alert-digest", '"owner_action_sent"'),
    ("QA smoke failure email", "/aws/lambda/life-platform-qa-smoke", '"email sent"'),
    ("DLQ escalation summary", "/aws/lambda/life-platform-dlq-consumer", '"Escalation summary sent"'),
    ("Canary failure email", "/aws/lambda/life-platform-canary", '"Alert sent:"'),
    ("Monday ops pack", "/aws/lambda/life-platform-traffic-digest", '"ops pack Sent"'),
    ("Traffic no-log-source alert", "/aws/lambda/life-platform-traffic-digest", '"alert email sent"'),
)

#: Send types whose success line did not exist before #6176, so a pre-trial window cannot be counted from logs.
NO_HISTORY_BEFORE_6176 = {"Monday ops pack", "Sunday 'what changed' (trial)"}

#: Functions whose Lambda error count is reported.
FUNCTIONS = (
    "daily-brief",
    "evening-nudge",
    "weekly-plate",
    "nutrition-review",
    "weekly-digest",
    "monday-compass",
    "monthly-digest",
    "ai-review-pack",
    "wednesday-chronicle",
    "life-platform-alert-digest",
    "life-platform-qa-smoke",
    "life-platform-dlq-consumer",
    "life-platform-canary",
    "life-platform-traffic-digest",
    "telegram-coach-worker",
)

#: Every log group a trial suppression line can appear in.
SUPPRESSION_GROUPS = (
    "/aws/lambda/weekly-digest",
    "/aws/lambda/monday-compass",
    "/aws/lambda/weekly-plate",
    "/aws/lambda/ai-review-pack",
    "/aws/lambda/wednesday-chronicle",
    "/aws/lambda/evening-nudge",
    "/aws/lambda/telegram-coach-worker",
    "/aws/lambda/life-platform-dlq-consumer",
    "/aws/lambda/life-platform-canary",
    "/aws/lambda/life-platform-traffic-digest",
)


def windows(end: date, weeks: int) -> list[tuple[date, date]]:
    """``weeks`` consecutive 7-day windows (inclusive Pacific days), oldest first, the last ending on ``end``."""
    out = []
    for i in range(weeks - 1, -1, -1):
        e = end - timedelta(days=7 * i)
        out.append((e - timedelta(days=6), e))
    return out


def _ms(d: date, end_of_day: bool = False) -> int:
    t = datetime(d.year, d.month, d.day, tzinfo=PT) + (timedelta(days=1) if end_of_day else timedelta())
    return int(t.astimezone(timezone.utc).timestamp() * 1000)


def count_log_events(logs: Any, group: str, pattern: str, start: date, end: date) -> Optional[int]:
    """Events matching ``pattern`` in ``group`` over the Pacific days start..end; None if the group can't be read."""
    kwargs = {"logGroupName": group, "filterPattern": pattern, "startTime": _ms(start), "endTime": _ms(end, end_of_day=True) - 1}
    n = 0
    try:
        while True:
            resp = logs.filter_log_events(**kwargs)
            n += len(resp.get("events") or [])
            tok = resp.get("nextToken")
            if not tok:
                return n
            kwargs["nextToken"] = tok
    except Exception as e:  # noqa: BLE001 — reported as unreadable, never as zero
        print(f"  [warn] {group} {pattern}: {type(e).__name__}", file=sys.stderr)
        return None


def suppressed_by_item(logs: Any, start: date, end: date) -> dict[str, int]:
    """Trial suppressions in the window, by item — parsed from each ``[outbound-trial]`` JSON line."""
    counts: dict[str, int] = defaultdict(int)
    for group in SUPPRESSION_GROUPS:
        kwargs = {
            "logGroupName": group,
            "filterPattern": '"[outbound-trial]" "suppressed"',
            "startTime": _ms(start),
            "endTime": _ms(end, end_of_day=True) - 1,
        }
        try:
            while True:
                resp = logs.filter_log_events(**kwargs)
                for ev in resp.get("events") or []:
                    msg = ev.get("message", "")
                    i = msg.find("{", msg.find("[outbound-trial]"))
                    try:
                        rec = json.loads(msg[i : msg.rfind("}") + 1])
                        counts[str(rec.get("item"))] += 1
                    except (ValueError, TypeError):
                        counts["unparsed"] += 1
                if not resp.get("nextToken"):
                    break
                kwargs["nextToken"] = resp["nextToken"]
        except Exception as e:  # noqa: BLE001
            print(f"  [warn] {group} suppression read: {type(e).__name__}", file=sys.stderr)
            counts["unreadable_groups"] += 1
    return dict(counts)


def lambda_errors(cw: Any, fn: str, start: date, end: date) -> Optional[int]:
    try:
        resp = cw.get_metric_statistics(
            Namespace="AWS/Lambda",
            MetricName="Errors",
            Dimensions=[{"Name": "FunctionName", "Value": fn}],
            StartTime=datetime.fromtimestamp(_ms(start) / 1000, tz=timezone.utc),
            EndTime=datetime.fromtimestamp(_ms(end, end_of_day=True) / 1000, tz=timezone.utc),
            Period=86400,
            Statistics=["Sum"],
        )
        return int(sum(p.get("Sum", 0) for p in resp.get("Datapoints") or []))
    except Exception as e:  # noqa: BLE001
        print(f"  [warn] errors {fn}: {type(e).__name__}", file=sys.stderr)
        return None


def _query_sks(table: Any, pk: str, prefix: str, attrs: str = "sk") -> list[dict]:
    from boto3.dynamodb.conditions import Key

    cond = Key("pk").eq(pk) & Key("sk").begins_with(prefix) if prefix else Key("pk").eq(pk)
    kwargs = {"KeyConditionExpression": cond, "ProjectionExpression": attrs}
    out: list[dict] = []
    while True:
        resp = table.query(**kwargs)
        out.extend(resp.get("Items") or [])
        if not resp.get("LastEvaluatedKey"):
            return out
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


def _pt_day(iso: Any) -> Optional[str]:
    try:
        t = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return t.astimezone(PT).date().isoformat()


def _in(day: Optional[str], start: date, end: date) -> bool:
    return bool(day) and start.isoformat() <= str(day)[:10] <= end.isoformat()


def marker_sends(table: Any, start: date, end: date) -> dict[str, int]:
    """Story-desk sends from their send-once markers (``STORYQ#W<n>`` Monday, ``…#TUE`` Tuesday) by sent_at day."""
    rows = _query_sks(table, f"USER#{USER}#SOURCE#chronicle", "STORYQ#W", "sk, sent_at")
    mon = sum(1 for r in rows if not str(r["sk"]).endswith("#TUE") and _in(_pt_day(r.get("sent_at")), start, end))
    tue = sum(1 for r in rows if str(r["sk"]).endswith("#TUE") and _in(_pt_day(r.get("sent_at")), start, end))
    return {"Story questions (Mon)": mon, "Owner-words question (Tue)": tue}


def telegram_evening(table: Any, start: date, end: date) -> dict[str, int]:
    """The Telegram 20:00 check-in prompt's verdicts (``COACH#evening_checkin / EVAL#<day>``) in the window."""
    rows = _query_sks(table, "COACH#evening_checkin", "EVAL#", "sk, reason, #s")
    return _verdicts(rows, start, end)


def _verdicts(rows: list[dict], start: date, end: date) -> dict[str, int]:
    out: dict[str, int] = defaultdict(int)
    for r in rows:
        day = str(r.get("sk", ""))[len("EVAL#") :]
        if _in(day, start, end):
            out[str(r.get("reason") or r.get("status") or "?")] += 1
    return dict(out)


def responses(table: Any, start: date, end: date) -> dict[str, Optional[int]]:
    """Rows only the owner creates, in the window. A partition that can't be read is None."""
    out: dict[str, Optional[int]] = {}

    def days(source: str) -> Optional[int]:
        try:
            rows = _query_sks(table, f"USER#{USER}#SOURCE#{source}", "DATE#")
        except Exception:  # noqa: BLE001
            return None
        return sum(1 for r in rows if _in(str(r["sk"])[5:15], start, end))

    out["Evening check-in replies (Telegram/MCP)"] = days("evening_checkin")
    out["Evening-ritual taps (email one-tap links)"] = days("evening_ritual")
    try:
        qa = _query_sks(table, f"USER#{USER}#SOURCE#chronicle", "STORYQA#W", "sk, received_at")
        out["Story-question replies stored"] = sum(1 for r in qa if _in(_pt_day(r.get("received_at")), start, end))
    except Exception:  # noqa: BLE001
        out["Story-question replies stored"] = None
    try:
        from boto3.dynamodb.conditions import Key

        cond = Key("pk").eq(f"USER#{USER}#SOURCE#decisions") & Key("sk").begins_with("DECISION#")
        dec = table.query(KeyConditionExpression=cond, ProjectionExpression="sk").get("Items") or []
        out["Decisions logged"] = sum(1 for r in dec if _in(_pt_day(str(r["sk"])[9:]), start, end))
    except Exception:  # noqa: BLE001
        out["Decisions logged"] = None
    return out


def chronicle_waiting(table: Any, end: date, days: int = 7) -> Optional[int]:
    """Chronicle drafts still unapproved ``days`` after their date — an owner action measurably not taken."""
    try:
        rows = _query_sks(table, f"USER#{USER}#SOURCE#chronicle", "DATE#", "sk, #s, tombstone")
    except Exception:  # noqa: BLE001
        return None
    cutoff = (end - timedelta(days=days)).isoformat()
    return sum(
        1 for r in rows if not r.get("tombstone") and r.get("status") in ("draft", "changes_requested") and str(r["sk"])[5:15] <= cutoff
    )


def _query_with_names(table: Any):
    """Wrap ``table.query`` so a ``#s`` projection resolves to ``status``."""

    class _T:
        def query(self, **kw):
            if "#s" in kw.get("ProjectionExpression", ""):
                kw["ExpressionAttributeNames"] = {"#s": "status"}
            return table.query(**kw)

    return _T()


def _cell(v: Any) -> str:
    return "unreadable" if v is None else str(v)


def report(weeks: int, end: date) -> str:
    import boto3

    logs = boto3.client("logs", region_name=REGION)
    cw = boto3.client("cloudwatch", region_name=REGION)
    table = _query_with_names(boto3.resource("dynamodb", region_name=REGION).Table(TABLE))
    wins = windows(end, weeks)
    heads = [f"{s.isoformat()}..{e.isoformat()}" for s, e in wins]

    lines = [
        f"# Owner-directed outbound volume (#6176), {weeks} week(s) ending {end.isoformat()}",
        "",
        f"Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}Z by `scripts/owner_outbound_volume.py` (read-only). "
        "Windows are Pacific days, inclusive. 'unreadable' means the record could not be read; it is never a zero. "
        "'n/a' means the type had no countable success line before #6176.",
        "",
        "## Sends by type",
        "",
        "| Type | " + " | ".join(heads) + " |",
        "|---|" + "---|" * len(heads),
    ]
    totals = [0] * len(wins)
    for typ, group, pattern in SENDS:
        cells = []
        for i, (s, e) in enumerate(wins):
            v = count_log_events(logs, group, pattern, s, e)
            if v == 0 and typ in NO_HISTORY_BEFORE_6176:
                cells.append("n/a or 0")
                continue
            totals[i] += v or 0
            cells.append(_cell(v))
        lines.append(f"| {typ} | " + " | ".join(cells) + " |")
    marker_rows: dict[str, list] = defaultdict(list)
    for i, (s, e) in enumerate(wins):
        try:
            for k, v in marker_sends(table, s, e).items():
                marker_rows[k].append(v)
                totals[i] += v
        except Exception:  # noqa: BLE001
            for k in ("Story questions (Mon)", "Owner-words question (Tue)"):
                marker_rows[k].append(None)
    for k, vals in marker_rows.items():
        lines.append(f"| {k} (send marker) | " + " | ".join(_cell(v) for v in vals) + " |")
    lines.append("| **Total emails counted** | " + " | ".join(f"**{t}**" for t in totals) + " |")

    lines += [
        "",
        "## Telegram 20:00 check-in prompt (verdicts per evening)",
        "",
        "| Verdict | " + " | ".join(heads) + " |",
        "|---|" + "---|" * len(heads),
    ]
    tg = [telegram_evening(table, s, e) for s, e in wins]
    for verdict in sorted({k for d in tg for k in d}):
        lines.append(f"| {verdict} | " + " | ".join(str(d.get(verdict, 0)) for d in tg) + " |")

    lines += ["", "## Sends the trial suppressed (by item)", "", "| Item | " + " | ".join(heads) + " |", "|---|" + "---|" * len(heads)]
    sup = [suppressed_by_item(logs, s, e) for s, e in wins]
    items = sorted({k for d in sup for k in d})
    if not items:
        lines.append("| (none: no `[outbound-trial] suppressed` line in any window) | " + " | ".join("0" for _ in wins) + " |")
    for item in items:
        lines.append(f"| {item} | " + " | ".join(str(d.get(item, 0)) for d in sup) + " |")

    lines += [
        "",
        "## Lambda errors (AWS/Lambda Errors, sum)",
        "",
        "| Function | " + " | ".join(heads) + " |",
        "|---|" + "---|" * len(heads),
    ]
    for fn in FUNCTIONS:
        lines.append(f"| {fn} | " + " | ".join(_cell(lambda_errors(cw, fn, s, e)) for s, e in wins) + " |")

    lines += [
        "",
        "## Owner responses (rows only he creates)",
        "",
        "| Response | " + " | ".join(heads) + " |",
        "|---|" + "---|" * len(heads),
    ]
    rs = [responses(table, s, e) for s, e in wins]
    for k in rs[0]:
        lines.append(f"| {k} | " + " | ".join(_cell(r.get(k)) for r in rs) + " |")

    lines += [
        "",
        "## Owner actions",
        "",
        "- `Do:` emails sent: see the 'Do: owner action' row above.",
        f"- Chronicle drafts still awaiting approval more than 7 days after their date (as of {end.isoformat()}): "
        f"{_cell(chronicle_waiting(table, end))}.",
        "",
        "## Not counted",
        "",
        "- Remediation-agent email (a GitHub Actions job; it mails only on manual dispatch or a digest failure).",
        "- The continuity switch and the paging SMS (unchanged by the trial; event-driven and rare).",
        "- Subscriber mail (out of scope: the trial does not touch it).",
        "- Advice links and ask responses: their one sanctioned reader is the owner's MCP tool (get_decisions / "
        "get_advice_link_queue), so this script does not read them.",
        "- Opens and reads: SES events are not split by message type, so whether an email was read is unknown.",
    ]
    return "\n".join(lines) + "\n"


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--weeks", type=int, default=2)
    ap.add_argument("--end", help="last Pacific day of the newest window (default: yesterday, Pacific)")
    ap.add_argument("--out", help="write the markdown report here (default: stdout)")
    a = ap.parse_args(argv)
    end = date.fromisoformat(a.end) if a.end else datetime.now(PT).date() - timedelta(days=1)
    md = report(a.weeks, end)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(md)
        print(f"wrote {a.out}")
    else:
        print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
