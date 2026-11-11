"""planning_loop_qa.py — #5761: the dead-man on the weekly planning loop.

THE FAILURE THIS WATCHES FOR
  The block retro (#5496) counts a program week as CLOSED when its May-tracker row (`may_tracker / WEEK#<monday>`,
  written by the nightly pre-draft leg) and its panel grade (`training_constraints / PANEL#<sunday>`, written by the
  Monday `PanelWeeklyGrade` run) share that week's Sunday. Block 1 closed 3 of 6 weeks: the early weeks had no rows,
  and one grade was keyed to a Saturday. Each writer has its own signal, but neither one asks whether the PAIR exists
  for every week — so a week can stay open all block and be found only at retro time. This check reds it the week it
  happens.

WHEN A WEEK IS DUE
  The grade lands Monday 08:30 Pacific and the tracker row on the Monday-evening nightly run (02:00Z Tuesday), so a
  week is due from the FOLLOWING TUESDAY: the newest due week is the newest whose Sunday is at least two days behind
  today (`expected_week`, the same rule `phase_eval_qa.expected_week` keeps for the Monday run). Every due week from
  `FIRST_WEEK` (the first week both writers covered) through the last `LOOKBACK_WEEKS` (one six-week block) is checked,
  so a hole stays red until it is filled (a re-run of the job for that week fills it) or ages out of the block.

  A `PANEL#` key that is not a Sunday is a WARN naming the key: it can never pair with a tracker week. The one
  historical stray (`PANEL#2026-10-24`, a Sunday on-demand run's Sunday-to-Saturday week) waits on the owner's
  reconcile call; `mcp.panel_weekly_grade.week_to_grade` and `training.panel_judge.panel_item` stop a new one.

FAIL, CONTENT_TRUTH. A missing row is a state-of-the-world fault (the job did not land), not evidence against a deploy
in flight, so it never triggers the fleet rollback. A read failure is a WARN naming the class — never "closed".

PRIVACY. Both partitions are Tier 2 owner-only and the qa-smoke report is emailed: this check reads `sk` only and
reports week keys, never a grade, a weight or a reason. Read-only: two Queries; the qa-smoke role already holds
table-wide `dynamodb:Query`, so no IAM change.
"""

from __future__ import annotations

from datetime import timedelta

from common.pacific_time import parse_day_key

CHECK_NAME = "planning_loop_liveness"
# The first Monday-Sunday week both writers covered (WEEK#2026-10-19 + PANEL#2026-10-25): earlier weeks predate the
# tracker or the panel, so they are history the retro already scored, never a live hole.
FIRST_WEEK = "2026-10-19"
LOOKBACK_WEEKS = 6  # one program block


def _day(day: str):
    d = parse_day_key(day)
    if d is None:
        raise ValueError(f"not a YYYY-MM-DD day key: {day!r}")
    return d


def expected_week(today: str) -> str:
    """The Monday of the newest week whose loop must be closed on `today` (a Pacific YYYY-MM-DD): from Tuesday, the
    week just ended; on a Monday, the week before it."""
    d = _day(today) - timedelta(days=1)
    return (d - timedelta(days=d.weekday() + 7)).isoformat()


def due_weeks(today: str) -> list[str]:
    """The Mondays of every week checked on `today`, oldest first."""
    newest = _day(expected_week(today))
    oldest = max(_day(FIRST_WEEK), newest - timedelta(weeks=LOOKBACK_WEEKS - 1))
    weeks, d = [], oldest
    while d <= newest:
        weeks.append(d.isoformat())
        d += timedelta(weeks=1)
    return weeks


def _sks(table, pk: str, prefix: str) -> list[str]:
    from boto3.dynamodb.conditions import Key

    out: list[str] = []
    kwargs = {"KeyConditionExpression": Key("pk").eq(pk) & Key("sk").begins_with(prefix), "ProjectionExpression": "sk"}
    while True:
        resp = table.query(**kwargs)
        out += [str(i["sk"])[len(prefix) :] for i in resp.get("Items") or []]
        if not resp.get("LastEvaluatedKey"):
            return out
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


def read_keys(table, user_id: str = "matthew") -> tuple[list[str], list[str]]:
    """(tracker Mondays, panel week_ends) — the sk suffixes only. Raises on a failed read."""
    from training import may_tracker as mt
    from training.panel_judge import PANEL_SK_PREFIX
    from training.phase_evaluator import pk as constraints_pk

    return _sks(table, mt.PK, mt.SK_PREFIX), _sks(table, constraints_pk(user_id), PANEL_SK_PREFIX)


def assess(tracker_mondays, panel_ends, today: str):
    """Pure: (verdict, message). verdict is 'ok' | 'warn' | 'fail'. A week is closed when its Monday has a tracker row
    and its Sunday a panel grade."""
    from training.may_tracker import week_bounds

    tracked, graded = set(tracker_mondays), set(panel_ends)
    open_weeks = []
    for mon in due_weeks(today):
        sun = week_bounds(mon)[1]
        missing = [name for name, ok in (("tracker WEEK#" + mon, mon in tracked), ("panel PANEL#" + sun, sun in graded)) if not ok]
        if missing:
            open_weeks.append(f"week {mon}: no {' or '.join(missing)}")
    stray = sorted(e for e in graded if parse_day_key(e) is None or week_bounds(e)[1] != e)
    if open_weeks:
        return "fail", f"planning loop open — {'; '.join(open_weeks)} (due by the following Tuesday, #5761)"
    weeks = due_weeks(today)
    if stray:
        return (
            "warn",
            f"weeks {weeks[0]}..{weeks[-1]} closed; PANEL# key(s) not on a Sunday never pair with a tracker week: {stray} (#5761)",
        )
    return "ok", f"planning loop closed for weeks {weeks[0]}..{weeks[-1]} (tracker row + panel grade on each Sunday)"


def check_planning_loop_liveness(table, check_cls, partition, pt_now):
    c = check_cls(CHECK_NAME, "Data Freshness", partition)
    today = pt_now().strftime("%Y-%m-%d")
    try:
        tracker, panel = read_keys(table)
    except Exception as e:  # noqa: BLE001 — a read failure is not "closed" (#2662)
        return [c.warn(f"planning-loop rows could not be read (no verdict was reached): {type(e).__name__}")]
    verdict, msg = assess(tracker, panel, today)
    return [c.fail(msg) if verdict == "fail" else c.warn(msg) if verdict == "warn" else c.ok(msg)]
