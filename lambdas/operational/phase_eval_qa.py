"""phase_eval_qa.py — #5575: the dead-man on the weekly phase evaluation.

THE FAILURE THIS WATCHES FOR
  The weekly phase evaluator (`mcp/phase_evaluator_leg.py`) is a fail-soft leg on the Monday panel-grade run: a crash
  in it is caught and named on that run's log line, and the grade's own dead-man (`panel-weekly-grade-missing`) stays
  green because the GRADE landed. So the one signal that the phase evaluation happened is its row — one
  `PHASE#EVAL#<monday>` per completed week in the owner-only `training_constraints` partition, written LAST by the leg.
  This check reds when the newest completed week has no EVAL row (the CS-4 rule: a missing EVAL row is reported).

WHEN A WEEK IS DUE
  The run is Monday 08:30 Pacific; qa-smoke runs nightly and on deploys, sometimes before 08:30 on a Monday. So the week
  that must be on record is the newest week whose Sunday is at least ONE full day behind today
  (`last_completed_monday(today - 1)`): a Monday sweep asks for the week before last, from Tuesday the week just ended.
  Before `ARMED_ON` (the first Monday run after the leg ships) an empty partition is "not armed yet", never red; from
  then an empty one is red like a stale one.

FAIL, CONTENT_TRUTH. A missing evaluation is a state-of-the-world fault (the job did not land), not evidence against a
deploy in flight, so it never triggers the fleet rollback. A read failure is a WARN naming the class — never "fresh".

PRIVACY. The partition is Tier 2 owner-only and the qa-smoke report is emailed: this check reads `sk` only and reports
week keys, never a gate, a verdict or a weight. Read-only: one Query; the qa-smoke role already holds table-wide
`dynamodb:Query`, so no IAM change.
"""

from __future__ import annotations

from datetime import timedelta

from common.pacific_time import parse_day_key
from training.phase_evaluator import SK_EVAL, pk

CHECK_NAME = "phase_eval_liveness"
# The first scheduled run after the leg can be live: the Monday after the merge window. Before it, absence is expected.
ARMED_ON = "2026-11-17"


def expected_week(today: str) -> str:
    """The Monday of the newest week whose EVAL row must exist on `today` (a Pacific YYYY-MM-DD)."""
    day = parse_day_key(today)
    if day is None:
        raise ValueError(f"not a YYYY-MM-DD day key: {today!r}")
    d = day - timedelta(days=1)
    return (d - timedelta(days=d.weekday() + 7)).isoformat()  # the Monday of the week before d's week


def newest_eval_week(table, user_id: str = "matthew"):
    """The newest stored EVAL week (its Monday), or None. Raises on a failed read."""
    from boto3.dynamodb.conditions import Key

    resp = table.query(
        KeyConditionExpression=Key("pk").eq(pk(user_id)) & Key("sk").begins_with(SK_EVAL),
        ScanIndexForward=False,
        Limit=1,
        ProjectionExpression="sk",
    )
    items = resp.get("Items") or []
    return str(items[0]["sk"])[len(SK_EVAL) :] if items else None


def assess(newest, today: str):
    """Pure: (verdict, message). verdict is 'ok' | 'fail' | 'not_armed'."""
    want = expected_week(today)
    if newest is None:
        if today < ARMED_ON:
            return "not_armed", f"no phase evaluation stored yet — the dead-man arms on {ARMED_ON} (the first Monday run after #5575 ships)"
        return "fail", f"no PHASE#EVAL row at all — the weekly phase evaluator has never landed (week {want} is due) (#5575)"
    if newest < want:
        return (
            "fail",
            f"newest phase evaluation is week {newest}; week {want} is due — the Monday leg on the panel-grade run did not land (#5575)",
        )
    return "ok", f"phase evaluation for week {newest} on record (due: {want})"


def check_phase_eval_liveness(table, check_cls, partition, pt_now):
    c = check_cls(CHECK_NAME, "Data Freshness", partition)
    today = pt_now().strftime("%Y-%m-%d")
    try:
        newest = newest_eval_week(table)
    except Exception as e:  # noqa: BLE001 — a read failure is not "fresh" (#2662)
        return [c.warn(f"phase evaluation rows could not be read (no verdict was reached): {type(e).__name__}")]
    verdict, msg = assess(newest, today)
    return [c.fail(msg) if verdict == "fail" else c.ok(msg)]
