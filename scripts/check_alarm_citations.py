#!/usr/bin/env python3
"""scripts/check_alarm_citations.py — the /wrap alarm-citation gate (#1959).

THE PROBLEM
  Nothing owned "an alarm red >72h must cite an incident row or issue #". The #1329
  standing-alarms step in `.claude/commands/wrap.md` existed but was scoped to
  freshness/staleness + secret-rotation alarms and was advisory (a note in
  next-picks, no fail condition, no `describe-alarms` enumeration). At the 2026-07-28
  /fullreview, 6 alarms were simultaneously red and the session ledger recorded
  exactly one incident row — a red board had normalized, and a NEW red could hide
  among the old ones.

THE FIX
  A deterministic, read-only gate mirroring `check_main_green.py`'s decode contract:
  enumerate every CloudWatch alarm currently in ALARM (`describe_alarms`, read-only —
  no writes, no alarm mutation), and require every one that has been red longer than
  ALARM_AGE_CITATION_HOURS to have an entry in the curated registry
  `docs/alarm_citations.json` (an issue `#N` or an incident-row reference, hand-
  maintained the same way `remediation/agent.py`'s MANUAL_ROTATION_SECRETS is —
  citations are asserted by an operator, not pattern-matched out of prose, because an
  alarm name rarely appears verbatim in the issue that explains it). An alarm with no
  entry is printed by name; the gate exits 1 unless `--decoded` (the operator wrote
  the shortfall explicitly into the handover, same shape as check_main_green.py).

  This folds the #1329 step's scope: freshness/staleness alarms ARE CloudWatch
  alarms and are covered here for free. Manual-rotation SECRET staleness is NOT a
  CloudWatch alarm (Secrets Manager DescribeSecret, not describe-alarms) and stays a
  separate reminder (docs/SECRETS_ROTATION.md "Monitoring" +
  remediation/agent.py's stale_secret_escalations) — one owner per signal type.

DEGRADE HONESTLY
  If CloudWatch can't be reached (no creds, offline, throttled) this prints a clear
  UNVERIFIED notice and exits 0 — a gate that can't measure anything must not claim
  a clean board (mirrors the gh-unavailable fail-open shape in check_backlog_hygiene.py
  ). The handover should still say so rather than silently
  skipping the line.

USAGE
  python3 scripts/check_alarm_citations.py             # gate: uncited long-red -> exit 1
  python3 scripts/check_alarm_citations.py --decoded    # operator named the shortfall; exit 0
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CITATIONS_PATH = ROOT / "docs" / "alarm_citations.json"
REGION = "us-west-2"

# Matches remediation/agent.py's ALARM_AGE_ESCALATION_HOURS (#1204) — the same 72h
# aging window, now also the citation-required threshold (#1959 widens the #1329
# step to the full alarm board). Kept as an INDEPENDENT constant on purpose: this
# script must run standalone and read-only without importing remediation/agent.py's
# module-level boto3 clients / drift_report dependency. tests/test_check_alarm_
# citations.py greps both source files to keep the two literals from drifting apart.
ALARM_AGE_CITATION_HOURS = 72


def _parse_ts(ts):
    """Parse a CloudWatch StateUpdatedTimestamp string into an aware datetime, or
    None if it can't be parsed — an unparseable stamp must never manufacture a
    false citation requirement."""
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def alarm_age_hours(alarm, now):
    """Hours `alarm` (a dict with an `updated` ISO timestamp) has been in its
    current state. None if the timestamp is missing/unparseable."""
    dt = _parse_ts(alarm.get("updated"))
    if dt is None:
        return None
    return (now - dt).total_seconds() / 3600.0


def load_citations(path=CITATIONS_PATH):
    """The curated alarm-name -> citation registry. Missing/malformed file degrades
    to an empty registry (every long-red alarm then reads as uncited, which is the
    honest and safe direction to fail in)."""
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def uncited_long_reds(alarms, citations, now=None, threshold_hours=ALARM_AGE_CITATION_HOURS):
    """(alarm_name, age_hours) for every ALARM-state alarm older than
    threshold_hours with no entry in `citations`. Pure and deterministic — no I/O —
    so it's exercised directly by the regression test with synthetic input,
    independent of live AWS/registry state (per the #1959 negative-test requirement).
    """
    now = now or datetime.now(timezone.utc)
    out = []
    for a in alarms:
        name = a.get("name") or "?"
        age = alarm_age_hours(a, now)
        if age is None or age <= threshold_hours:
            continue
        entry = citations.get(name)
        if not entry or not str(entry.get("citation", "")).strip():
            out.append((name, age))
    return out


def fetch_alarms():
    """Live `describe_alarms(StateValue="ALARM")` read — read-only, no writes, no
    alarm mutation. Returns (alarms, error): `error` is a human string when AWS is
    unreachable (missing creds, network, throttling, IAM), in which case `alarms`
    is always `[]` — callers must treat that as UNVERIFIED, never as a clean board.
    """
    try:
        import boto3

        cw = boto3.client("cloudwatch", region_name=REGION)
        resp = cw.describe_alarms(StateValue="ALARM", MaxRecords=100)
    except Exception as e:  # noqa: BLE001 — any AWS/boto3 failure must degrade, not crash
        return [], str(e)
    alarms = [{"name": a.get("AlarmName", "?"), "updated": str(a.get("StateUpdatedTimestamp", ""))} for a in resp.get("MetricAlarms", [])]
    return alarms, None


def render(uncited, unreachable_error):
    """(exit_code, message) for a computed result. Pure — unit-tested offline."""
    if unreachable_error is not None:
        return 0, (
            f"⚠️  check_alarm_citations: CloudWatch unreachable ({unreachable_error}) — "
            "alarm citations UNVERIFIED this run. Note that explicitly in the handover "
            "(`**Alarms:** unverified — AWS unreachable`) rather than claiming a clean board."
        )
    if not uncited:
        return 0, "✅ every alarm in ALARM state >72h cites an incident row or issue (or none are that old)."
    lines = [f"❌ {len(uncited)} alarm(s) in ALARM >72h with no citation in {CITATIONS_PATH.relative_to(ROOT)}:"]
    for name, age in sorted(uncited):
        lines.append(f"   - {name}  (red {age / 24:.1f}d / {age:.0f}h)")
    lines.append(
        '   Add an entry to docs/alarm_citations.json — {"<AlarmName>": {"citation": "#N", '
        '"note": "..."}} — or write the shortfall explicitly into the handover '
        "(`**Alarms:** <M> uncited — named: ...`) and re-run with --decoded."
    )
    return 1, "\n".join(lines)


def main():
    decoded = "--decoded" in sys.argv
    alarms, err = fetch_alarms()
    citations = load_citations()
    uncited = [] if err else uncited_long_reds(alarms, citations)
    code, message = render(uncited, err)
    print(message)
    if code == 0:
        return 0
    if decoded:
        print("   --decoded acknowledged: the handover MUST name each uncited alarm explicitly.")
        return 0
    print("   The wrap may not report a clean alarm board over this. Either add citations, or --decoded after naming the shortfall.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
