"""training/calibration_cadence.py — when the tape, the progress photos and the DEXA are due (#5061, epic #5067).

The charter's `calibration` block names the cadences (`charter_value`): tape + photos every
`every_weeks` (2) weeks with a dead-man after `dead_man_missed_cycles` (2) missed cycles, and a DEXA about
every `every_weeks_approx` (12) weeks. This module is the ONE place that turns those numbers and the dates a
thing was last logged into a state and a prompt. Pure: the readers are INJECTED (a callable returning the
dates logged, or raising), the clock is the `today` argument, and nothing here touches AWS.

THE CYCLE. `due_on` = last logged + one cycle (a kind never logged anchors on the experiment start, so its
first tape is due one cycle after genesis). A cycle is MISSED when its due day has passed with no log:

  ok         today is before `due_on`
  due        today is `due_on`
  overdue    a due day has passed (1 missed cycle)
  missed_2   `dead_man_missed_cycles` due days have passed — the DEAD-MAN (tape and photos only; owner-only)

A new log moves `last_logged`, so `due_on`, `cycle_start` and the state reset together. `cycle_start` (the last
log's date, or the anchor) is the idempotency stamp: `prompt_key` = `CALIB_PROMPT#<kind>#<cycle_start>`, so a
prompt is sent at most once per cycle and a new log opens a new key.

DEXA is a cadence, not a behavioural dead-man (a scan is booked, not forgotten): it carries `due_on`/`state`
(never `missed_2`), and when no scan row is readable it is `unknown` and names the ingest that would supply it
(#4639, not built) rather than guessing a date.

FOOD-DELIVERY UPLOAD (#5006/#5108, owner ruling 2026-10-23). Food delivery is not a live feed: it is a
6-monthly manual upload ritual, and tracking stays PAUSED between uploads (the registry's `paused` facet,
so freshness, coach questions, the nudge and the daily-brief modifier never read it). This row is the
reminder: a cadence like DEXA (no dead-man), its cycle the charter's
`nutrition.food_delivery.upload_every_months` (never a second number here), its last-logged date the newest `import_date` the
ingestion Lambda stamps on the partition's `DATE#` rows. It fires while the source is paused: that is
the point of it.

PRIVACY (PUBLIC repo; owner ruling 2026-10-03, stored is not published). The output is dates, counts and
prose — never a photo key, a pose path or a reading. Owner-only: `tests/test_calibration_cadence_5061.py`
holds that no `lambdas/web/` or `lambdas/emails/` module imports this one and that the only published-tree
module that names the photo partition is the owner-gated viewer.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any, Callable, Mapping, Optional

VERSION = "calibration-cadence@1.2.0"  # 1.2.0 #5006/#5108: food_delivery_upload; 1.1.0 #5111: lab_draw
KINDS = ("tape", "photos", "dexa", "lab_draw", "food_delivery_upload")
OK, DUE, OVERDUE, MISSED_2, UNKNOWN, READ_FAILED = "ok", "due", "overdue", "missed_2", "unknown", "read_failed"
PROMPT_PREFIX = "CALIB_PROMPT"
DEADMAN_PREFIX = "CALIB_DEADMAN"
DEADMAN_TOKEN = DEADMAN_PREFIX  # the log token the nightly dead-man check emits
DEXA_INGEST_ISSUE = 4639
SRC = {
    "tape": "USER#matthew#SOURCE#measurements (DATE# rows)",
    "photos": "USER#matthew#SOURCE#progress_photos (DATE#<day>#<pose> index rows; dates only, never a key)",
    "dexa": "USER#matthew#SOURCE#dexa (scan_date)",
    "lab_draw": "USER#matthew#SOURCE#labs (draw_date) + USER#matthew#SOURCE#clinical (LABS#<date> sort keys); dates only, never a result",
    "food_delivery_upload": "USER#matthew#SOURCE#food_delivery (DATE# rows, import_date); the upload date only, never an order or an amount",
}
PROMPTS = {
    "tape": "Tape day: measure waist (navel, narrowest, iliac crest) and the other sites, then log it with your coach. Last tape {last}.",
    "photos": "Photo day: front, side and back, same light and spot as last time; send each to the bot as /progress front (side, back). Last set {last}.",
    "dexa": "DEXA is due about now ({due}). Book the scan; the labs/DEXA ingest (#4639) is not built, so tell your coach the date once it is done.",
    "lab_draw": "The follow-up draw is due about {due}. Book it; tell your coach the date once it is done. Last draw {last}.",
    "food_delivery_upload": (
        "The food-delivery upload is due ({due}): export the delivery transactions since the last upload as CSV "
        "and drop it in imports/food_delivery/. Tracking stays paused between uploads. Last upload {last}."
    ),
}


def _cv(path: str, default: Any = None) -> Any:
    from training.training_charter import charter_value

    return charter_value(path, default)


def _day(v: Any) -> Optional[_dt.date]:
    from common.pacific_time import parse_day_key

    return parse_day_key(str(v)[:10])


def prompt_key(kind: str, cycle_start: str) -> str:
    return f"{PROMPT_PREFIX}#{kind}#{cycle_start}"


def deadman_key(kind: str, cycle_start: str) -> str:
    return f"{DEADMAN_PREFIX}#{kind}#{cycle_start}"


def cycle_state(
    kind: str, logged: Optional[list], today: str, cycle_days: int, *, anchor: Optional[str] = None, dead_cycles: Optional[int] = 2
) -> dict[str, Any]:
    """One kind's cycle from the dates it was logged (≤ today; later dates are ignored). Pure."""
    t = _day(today)
    if t is None or cycle_days < 1:
        raise ValueError("a calibration cycle needs a valid today and a positive cycle length")
    days = sorted(d for d in (_day(x) for x in logged or ()) if d is not None and d <= t)
    last = days[-1] if days else None
    start = last or _day(anchor)
    if start is None:
        return {"kind": kind, "state": UNKNOWN, "last_logged": None, "cycle_start": None, "due_on": None, "missed_cycles": 0}
    due = start + _dt.timedelta(days=cycle_days)
    # due days strictly before today: due, due+c, ... -> (t - due - 1)//c + 1 for t > due
    missed = 0 if t <= due else ((t - due).days - 1) // cycle_days + 1
    if t < due:
        state = OK
    elif t == due:
        state = DUE
    elif dead_cycles and missed >= int(dead_cycles):
        state = MISSED_2
    else:
        state = OVERDUE
    return {
        "kind": kind,
        "state": state,
        "last_logged": last.isoformat() if last else None,
        "cycle_start": start.isoformat(),
        "anchored_on_genesis": last is None,
        "due_on": due.isoformat(),
        "days_until_due": (due - t).days,
        "missed_cycles": missed,
        "cycle_days": cycle_days,
    }


def _read(reader: Optional[Callable[[], Any]]) -> tuple[Optional[list], Optional[str]]:
    if reader is None:
        return None, "NoReader"
    try:
        return list(reader() or []), None
    except Exception as e:  # noqa: BLE001 — a broken read is `read_failed` by class, never "nothing logged"
        return None, type(e).__name__


def _behavioural(kind: str, readers: Mapping[str, Callable], today: str, anchor: Optional[str]) -> dict[str, Any]:
    every = _cv("calibration.tape_and_photos.every_weeks")
    dead = _cv("calibration.tape_and_photos.dead_man_missed_cycles")
    base = {"kind": kind, "source": SRC[kind], "cycle_weeks": every, "dead_man_missed_cycles": dead}
    dates, err = _read(readers.get(kind))
    if err:
        return {**base, "state": READ_FAILED, "error": err}
    if not every:
        return {**base, "state": UNKNOWN, "detail": "the charter names no tape/photo cadence"}
    return {**base, **cycle_state(kind, dates, today, int(every) * 7, anchor=anchor, dead_cycles=dead)}


def tape_row(rows: Any, as_of: str, anchor: Optional[str] = None) -> dict[str, Any]:
    """The tape cycle as of `as_of` from rows already in hand (the May tracker's measurements read) — no second read."""
    dates = [str(r.get("date") or str(r.get("sk") or "").replace("DATE#", ""))[:10] for r in rows or ()]
    row = _behavioural("tape", {"tape": lambda: dates}, as_of, anchor)
    row["prompt"] = _prompt(row)
    return row


def _dexa(readers: Mapping[str, Callable], today: str) -> dict[str, Any]:
    weeks = _cv("calibration.dexa.every_weeks_approx")
    base = {"kind": "dexa", "source": SRC["dexa"], "cycle_weeks": weeks, "cadence": "approximate"}
    dates, err = _read(readers.get("dexa"))
    if err:
        return {**base, "state": READ_FAILED, "error": err, "ingest": {"issue": DEXA_INGEST_ISSUE}}
    if not weeks:
        return {**base, "state": UNKNOWN, "detail": "the charter names no DEXA cadence"}
    cyc = cycle_state("dexa", dates, today, int(weeks) * 7, anchor=None, dead_cycles=None)
    out = {**base, **cyc}
    if not dates:
        out["detail"] = f"no DEXA scan row is readable — the labs/DEXA ingest is #{DEXA_INGEST_ISSUE} (not built)"
        out["ingest"] = {"issue": DEXA_INGEST_ISSUE, "built": False}
    return out


def _lab_draw(readers: Mapping[str, Callable], today: str) -> dict[str, Any]:
    """#5111: the follow-up draw cadence — the last draw date (`labs`, dates only) + `nutrition.labs.follow_up_weeks`.
    No draw readable: the owner-only `lab_followup.next_draw_on` (the private twin) is the due date; neither → unknown.
    The reminder window opens `reminder_lead_days` before the due day (state `due`); nothing here reads a result."""
    weeks, lead = _cv("nutrition.labs.follow_up_weeks"), _cv("nutrition.labs.reminder_lead_days", 0)
    base = {"kind": "lab_draw", "source": SRC["lab_draw"], "cycle_weeks": weeks, "cadence": "approximate", "reminder_lead_days": lead}
    dates, err = _read(readers.get("lab_draw"))
    if err:
        return {**base, "state": READ_FAILED, "error": err, "ingest": {"issue": DEXA_INGEST_ISSUE}}
    if not weeks:
        return {**base, "state": UNKNOWN, "detail": "the charter names no follow-up draw cadence"}
    days, fixed = int(weeks) * 7, _day(_cv("lab_followup.next_draw_on"))
    anchor = (fixed - _dt.timedelta(days=days)).isoformat() if fixed and not dates else None
    out = {**base, **cycle_state("lab_draw", dates, today, days, anchor=anchor, dead_cycles=None)}
    if out["state"] == OK and out["days_until_due"] <= int(lead or 0):
        out["state"] = DUE  # the reminder window: at most one prompt per cycle (the prompt key is the cycle start)
    if out["state"] == UNKNOWN:
        out["detail"] = "no draw date is readable and no owner-only follow-up date is set"
    return out


def _food_delivery_upload(readers: Mapping[str, Callable], today: str) -> dict[str, Any]:
    """#5006/#5108: the 6-monthly food-delivery upload reminder. The cycle is the charter's
    `nutrition.food_delivery.upload_every_months` x the registry's `DAYS_PER_CADENCE_MONTH` (the month the
    /api/status due panel counts in); no readable upload date is `unknown` (no anchor is guessed)."""
    from ingestion.source_registry import DAYS_PER_CADENCE_MONTH

    months = _cv("nutrition.food_delivery.upload_every_months")
    base = {"kind": "food_delivery_upload", "source": SRC["food_delivery_upload"], "cycle_months": months, "cadence": "approximate"}
    dates, err = _read(readers.get("food_delivery_upload"))
    if err:
        return {**base, "state": READ_FAILED, "error": err}
    if not months:
        return {**base, "state": UNKNOWN, "detail": "the charter names no food-delivery upload cadence"}
    cycle_days = int(months) * DAYS_PER_CADENCE_MONTH
    out = {**base, **cycle_state("food_delivery_upload", dates, today, cycle_days, anchor=None, dead_cycles=None)}
    if out["state"] == UNKNOWN:
        out["detail"] = "no food-delivery upload date is readable"
    return out


def _prompt(row: dict[str, Any]) -> Optional[str]:
    if row.get("state") not in (DUE, OVERDUE, MISSED_2):
        return None
    last = row.get("last_logged") or "never logged"
    return PROMPTS[row["kind"]].format(last=last, due=row.get("due_on"))


def compute(today: str, readers: Mapping[str, Callable[[], Any]], *, anchor: Optional[str] = None) -> dict[str, Any]:
    """The whole cadence block: `{kind: row}` for tape, photos and dexa. `anchor` = the experiment start,
    the cycle start of a kind never logged. Each reader returns the dates logged or raises."""
    rows = {"tape": _behavioural("tape", readers, today, anchor), "photos": _behavioural("photos", readers, today, anchor)}
    rows["dexa"] = _dexa(readers, today)
    rows["lab_draw"] = _lab_draw(readers, today)
    rows["food_delivery_upload"] = _food_delivery_upload(readers, today)
    for r in rows.values():
        r["prompt"] = _prompt(r)
        if r.get("cycle_start"):
            r["prompt_key"] = prompt_key(r["kind"], r["cycle_start"])
    from training.training_charter import charter_version

    return {"version": VERSION, "charter_version": charter_version(), "as_of": today, "kinds": rows, "tier": "owner_only"}


def deadman_kinds(block: Mapping[str, Any]) -> list[str]:
    """Kinds at `missed_2` (the owner-only dead-man)."""
    return [k for k, r in (block.get("kinds") or {}).items() if r.get("state") == MISSED_2]


def prompts_due(block: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Rows whose prompt should go out now (due or overdue, not yet in dead-man — that one has its own alert)."""
    return [r for r in (block.get("kinds") or {}).values() if r.get("state") in (DUE, OVERDUE) and r.get("prompt")]


def deadman_alert(row: Mapping[str, Any]) -> str:
    if row.get("alert"):  # a row that names its own alert (#5096: the titration dead-man is a missed run, not a missed log)
        return str(row["alert"])
    return (
        f"{row['kind']} has gone {row.get('missed_cycles')} cycles with nothing logged (last {row.get('last_logged') or 'never'}). "
        "The calibration the May plan rests on is running blind; log one this week."
    )


# ── the readers over a DynamoDB table (injected table; the only I/O in this module) ───────────────────────


def _dates(table: Any, source: str, field: str) -> list[str]:
    from boto3.dynamodb.conditions import Key

    out: list[str] = []
    kw: dict[str, Any] = {
        "KeyConditionExpression": Key("pk").eq(f"USER#matthew#SOURCE#{source}"),
        "ProjectionExpression": "sk, #d",
        "ExpressionAttributeNames": {"#d": field},
    }
    while True:
        resp = table.query(**kw)
        for it in resp.get("Items") or []:
            v = str(it.get(field) or "").strip() or str(it.get("sk") or "").replace("DATE#", "")
            if _day(v):
                out.append(v[:10])
        if not resp.get("LastEvaluatedKey"):
            return sorted(set(out))
        kw["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


def _clinical_draw_dates(table: Any) -> list[str]:
    """The `LABS#<date>` sort-key dates of the clinical partition — the key only, no attribute is projected (#5111)."""
    from boto3.dynamodb.conditions import Key

    out: list[str] = []
    kw: dict[str, Any] = {
        "KeyConditionExpression": Key("pk").eq("USER#matthew#SOURCE#clinical") & Key("sk").begins_with("LABS#"),
        "ProjectionExpression": "sk",
    }
    while True:
        resp = table.query(**kw)
        for it in resp.get("Items") or []:
            v = str(it.get("sk") or "").replace("LABS#", "")
            if _day(v):
                out.append(v[:10])
        if not resp.get("LastEvaluatedKey"):
            return out
        kw["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


def upload_dates(table: Any) -> list[str]:
    """The distinct `import_date`s on the food_delivery partition's `DATE#` rows (#5006/#5108): the day each
    upload ran. Only that attribute is projected, so no order, merchant or amount leaves the read. A row without
    an `import_date` is skipped, never read as its order date (an order day is not an upload day)."""
    from boto3.dynamodb.conditions import Key

    out: set[str] = set()
    kw: dict[str, Any] = {
        "KeyConditionExpression": Key("pk").eq("USER#matthew#SOURCE#food_delivery") & Key("sk").begins_with("DATE#"),
        "ProjectionExpression": "import_date",
    }
    while True:
        resp = table.query(**kw)
        for it in resp.get("Items") or []:
            v = str(it.get("import_date") or "").strip()
            if _day(v):
                out.add(v[:10])
        if not resp.get("LastEvaluatedKey"):
            return sorted(out)
        kw["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


def draw_dates(table: Any) -> list[str]:
    """Every known draw date: the labs partition's plus the clinical record's — the latest draw may live in either."""
    return sorted(set(_dates(table, "labs", "draw_date")) | set(_clinical_draw_dates(table)))


def table_readers(table: Any) -> dict[str, Callable[[], list[str]]]:
    """The three readers over one table: tape rows (`date`), photo index rows (the `date` of each pose row —
    nothing else is projected, so no key or path ever leaves the read), DEXA rows (`scan_date`)."""
    return {
        "tape": lambda: _dates(table, "measurements", "date"),
        "photos": lambda: _dates(table, "progress_photos", "date"),
        "dexa": lambda: _dates(table, "dexa", "scan_date"),
        "lab_draw": lambda: draw_dates(table),
        "food_delivery_upload": lambda: upload_dates(table),
    }


def read(table: Any, today: str) -> dict[str, Any]:
    """The block over one table, plus the fitness battery's row (#5078): its due date and prompt come from
    `training.fitness_tests` (the program's own week), carried here so the owner channel has ONE prompt path —
    and the weekly calorie titration's dead-man row (#5096, `health.titration`: no decision for the week), and the
    dated prompt to write the post-deadline plan with its dead-man (#5130, `training.phase_after_may`)."""
    from common.constants import EXPERIMENT_START_DATE
    from health import titration

    from training import fitness_tests, phase_after_may

    block = compute(today, table_readers(table), anchor=EXPERIMENT_START_DATE)
    block["kinds"][fitness_tests.CALIBRATION_KIND] = fitness_tests.calibration_row_from_table(table, today)
    block["kinds"][titration.CALIBRATION_KIND] = titration.calibration_row_from_table(table, today)
    block["kinds"][phase_after_may.CALIBRATION_KIND] = phase_after_may.calibration_row(today)
    return block
