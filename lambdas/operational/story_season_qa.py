"""story_season_qa.py — #4539: the Story Desk's dead-men (epic #4531, piece 7).

THE INCIDENTS THIS EXISTS FOR
  * Episodes 1 and 2 of the Panel were never generated. Their chronicle weeks
    published on 2026-09-11 and 2026-09-18; the episodes first existed on
    2026-10-02, when the season rebuild made them. Three weeks, zero signal
    (#4365).
  * The week-3 episode was HELD on 2026-09-25. A hold alerts once, at the moment
    it is taken, and then sits: nothing ever asked how old it had become.
  * The season ledger (`LEDGER#{date}`) is what next week's desk reads as "the
    story so far". It is written only on publish, by a fail-soft `_commit_ledger`
    — and a week that fell back to the legacy writer carries no ledger at all.
    Either way the next installment starts from a season that stops one week
    short, and nothing says so.
  * `StoryQuestionsMonday` (Mondays 16:00 UTC, #4546) is a second EventBridge
    rule on `wednesday-chronicle`. The heartbeat ledger quantifies over function
    names, so a dead rule on a function whose other rule still fires is
    invisible to it.

WHY A QA-SMOKE LEG AND NOT AN ALARM
  Every fact here is a row or a public file that already exists: the chronicle
  partition (the qa-smoke role already holds table-wide `dynamodb:Query`) and
  `/panelcast/episodes.json`, read over HTTP exactly as a reader's player does.
  No new function, schedule, alarm, metric series or IAM grant — the leg rides
  the nightly `life-platform-qa-smoke` invoke and its `qa-smoke-failures` /
  `qa-smoke-heartbeat` alarms (`docs/PROPORTIONALITY.md`).

THE HOLD IS READ FROM THE PUBLIC MARKER, NOT THE PRIVATE DRAFT
  `_hold_and_alert` writes two things: the draft under `panelcast-holds/`
  (private; the qa-smoke role cannot read it and is not being granted it) and a
  public-safe `pending` marker in `episodes.json` — `{week, reason:
  "held_for_review", noted_at}`. The marker is the "named, dated hold" this
  check accepts. Its `noted_at` is REWRITTEN on every re-hold, so on its own it
  would let a retry loop keep a hold forever young; the escalation therefore
  also runs on a clock no retry can reset — how long the week has been past its
  48 h window. Whichever is older decides.

WHAT IS NOT CLAIMED
  * The marker holds ONE week. Two weeks held at once show as one hold and one
    bare miss, which is the louder reading and the correct one.
  * A week published with no chronicle row at all is not a member of the set —
    that is `chronicle-delivery-heartbeat`'s class.
  * The questions check sees the SEND MARKER (`STORYQ#W{n}`), which is written
    after SES accepts. A send whose marker write was lost reads as a miss.

CONTENT_TRUTH, never DEPLOY_HEALTH: a missing episode is not evidence about the
deploy in flight and reverting the fleet cannot conjure one (#1921).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

from boto3.dynamodb.conditions import Key
from common.pacific_time import parse_iso_utc  # #1964/#3609: THE ISO-8601 instant parser
from content.story_dossier import week_containing
from experiment.phase_filter import singleton_visible

CHRONICLE_SUFFIX = "chronicle"
INSTALLMENT_PREFIX = "DATE#"
LEDGER_PREFIX = "LEDGER#"
QUESTIONS_PREFIX = "STORYQ#W"
EPISODES_PATH = "/panelcast/episodes.json"

# Acceptance (a): a published week has an episode, or a named dated hold, within 48 h.
EPISODE_WINDOW_HOURS = 48
# Acceptance (b): a hold older than 7 days escalates.
HOLD_ESCALATE_DAYS = 7
# The reason `coach_panel_podcast_lambda._hold_and_alert` publishes. `awaiting_material`
# (the other marker) is not a hold: a PUBLISHED week has its material by definition.
HOLD_REASON = "held_for_review"

# (d) `StoryQuestionsMonday` — cdk/stacks/email_stack.py. Pinned to the rule's own cron by
# tests/test_heartbeat_completeness.py, so moving the rule moves the dead-man or reds.
QUESTIONS_WEEKDAY = "MON"
QUESTIONS_HOUR_UTC = 16
QUESTIONS_MINUTE_UTC = 0
QUESTIONS_GRACE_HOURS = 1
# The rule's first live send. A Monday before it was never owed a send.
QUESTIONS_FIRST_SEND = "2026-10-05"

EPISODE_CHECK = "story_season:episode_or_hold"
LEDGER_CHECK = "story_season:ledger_advanced"
QUESTIONS_CHECK = "story_season:monday_questions"

_WEEKDAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")


def _query(table: Any, pk: str, prefix: str, attrs: str, names: Optional[dict] = None) -> list[dict]:
    items: list[dict] = []
    lek = None
    while True:
        kw: dict = {"KeyConditionExpression": Key("pk").eq(pk) & Key("sk").begins_with(prefix), "ProjectionExpression": attrs}
        if names:
            kw["ExpressionAttributeNames"] = names
        if lek:
            kw["ExclusiveStartKey"] = lek
        resp = table.query(**kw)
        items.extend(resp.get("Items", []))
        lek = resp.get("LastEvaluatedKey")
        if not lek:
            return items


def _week_no(row: dict) -> Optional[int]:
    try:
        return int(str(row.get("week_number")))
    except (TypeError, ValueError):
        return None


def _row_date(row: dict) -> str:
    """The date a week is filed under: the `date` attribute (the prologue's sk is its URL
    slot, not its date), else the sk."""
    return str(row.get("date") or str(row.get("sk", ""))[len(INSTALLMENT_PREFIX) :])[:10]


def published_instant(row: dict) -> Optional[datetime]:
    """When the installment went public: `approved_at` (the approve path and the season
    promote both stamp it), else midnight UTC of its date (the reset's plan post)."""
    return parse_iso_utc(row.get("approved_at")) or parse_iso_utc(_row_date(row))


def published_weeks(rows: list[dict]) -> dict[int, dict]:
    """`{week: {"published": earliest instant, "dates": [...], "sks": [...]}}` for every
    season week a reader can see: published, visible in the current phase, listed."""
    weeks: dict[int, dict] = {}
    for r in rows:
        wk = _week_no(r)
        when = published_instant(r)
        if wk is None or when is None or r.get("status") != "published" or r.get("unlisted") or not singleton_visible(r):
            continue
        w = weeks.setdefault(wk, {"published": when, "dates": [], "sks": []})
        w["published"] = min(w["published"], when)
        w["dates"].append(_row_date(r))
        w["sks"].append(str(r.get("sk")))
    return weeks


def episode_findings(weeks: dict[int, dict], doc: dict, now: datetime) -> tuple[list[str], list[str], list[str]]:
    """`(missing, escalated, sanctioned)` — each a list of sentences naming a week.

    missing    past 48 h, no episode, no hold naming the week          -> FAIL
    escalated  held, and the hold or the overdue clock is past 7 days   -> FAIL
    sanctioned inside the 48 h window, or held for under 7 days         -> named, green
    """
    aired: set[int] = set()
    for e in doc.get("episodes") or []:
        try:
            aired.add(int(e.get("week")))
        except (TypeError, ValueError):
            continue
    pending = doc.get("pending") if isinstance(doc.get("pending"), dict) else {}
    try:
        held_week: Optional[int] = int(pending.get("week")) if pending.get("reason") == HOLD_REASON else None
    except (TypeError, ValueError):
        held_week = None
    held_at = parse_iso_utc(pending.get("noted_at")) if held_week is not None else None

    missing: list[str] = []
    escalated: list[str] = []
    sanctioned: list[str] = []
    for wk in sorted(weeks):
        if wk in aired:
            continue
        published = weeks[wk]["published"]
        due = published + timedelta(hours=EPISODE_WINDOW_HOURS)
        if now <= due:
            sanctioned.append(f"week {wk} published {published.isoformat()} — inside its {EPISODE_WINDOW_HOURS} h window")
            continue
        overdue_days = (now - due).total_seconds() / 86400
        if held_week == wk and held_at is not None:
            age_days = max((now - held_at).total_seconds() / 86400, overdue_days)
            line = f"week {wk} held since {held_at.isoformat()} ({age_days:.1f} d, chronicle published {published.isoformat()})"
            (escalated if age_days > HOLD_ESCALATE_DAYS else sanctioned).append(line)
        else:
            missing.append(f"week {wk} (chronicle published {published.isoformat()}, {overdue_days:.1f} d past its window)")
    return missing, escalated, sanctioned


def ledger_gaps(weeks: dict[int, dict], ledger_rows: list[dict]) -> list[str]:
    """The published weeks with no visible `LEDGER#{date}` row for any of their dates."""
    have = {str(r.get("sk", ""))[len(LEDGER_PREFIX) :] for r in ledger_rows if singleton_visible(r)}
    return [
        f"week {wk} (expected {LEDGER_PREFIX}{' or '.join(sorted(set(w['dates'])))})"
        for wk, w in sorted(weeks.items())
        if not have & set(w["dates"])
    ]


def last_questions_send(now: datetime) -> datetime:
    """The newest scheduled `StoryQuestionsMonday` instant whose grace has elapsed."""
    ref = now.astimezone(timezone.utc) - timedelta(hours=QUESTIONS_GRACE_HOURS)
    slot = ref.replace(hour=QUESTIONS_HOUR_UTC, minute=QUESTIONS_MINUTE_UTC, second=0, microsecond=0)
    slot -= timedelta(days=(slot.weekday() - _WEEKDAYS.index(QUESTIONS_WEEKDAY)) % 7)
    return slot if slot <= ref else slot - timedelta(days=7)


def check_story_season(
    table: Any,
    user_prefix: str,
    check_cls: Callable[..., Any],
    partition: str,
    pt_now: Callable[[], datetime],
    *,
    site_base_url: str,
    budget: Any = None,
) -> list:
    episode_c = check_cls(EPISODE_CHECK, "Data Freshness", partition)
    ledger_c = check_cls(LEDGER_CHECK, "Data Freshness", partition)
    questions_c = check_cls(QUESTIONS_CHECK, "Data Freshness", partition)
    out = [episode_c, ledger_c, questions_c]
    now = pt_now().astimezone(timezone.utc)
    pk = f"{user_prefix}{CHRONICLE_SUFFIX}"

    try:
        rows = _query(
            table,
            pk,
            INSTALLMENT_PREFIX,
            "sk, #d, #s, week_number, approved_at, unlisted, phase, tombstone",
            {"#d": "date", "#s": "status"},
        )
        ledger_rows = _query(table, pk, LEDGER_PREFIX, "sk, phase, tombstone")
        markers = _query(table, pk, QUESTIONS_PREFIX, "sk, sent_at")
    except Exception as e:  # noqa: BLE001 — a read failure is NOT liveness (#2662)
        for c in out:
            c.warn(f"the chronicle partition could not be read (no verdict was reached): {e}")
        return out

    # ── (d) the Monday questions — needs no season rows, so it is graded first ──
    slot = last_questions_send(now)
    owed = week_containing(slot.date().isoformat()) if slot.date().isoformat() >= QUESTIONS_FIRST_SEND else None
    if owed is None:
        questions_c.ok(
            f"no questions send owed for {slot.date().isoformat()} (first live send {QUESTIONS_FIRST_SEND}; "
            "a Monday outside every season week sends nothing)"
        )
    else:
        want = f"{QUESTIONS_PREFIX}{int(owed['week']):03d}"
        sent = [m for m in markers if str(m.get("sk")) == want and parse_iso_utc(m.get("sent_at")) is not None]
        if sent:
            questions_c.ok(f"week {owed['week']} questions sent {sent[0].get('sent_at')} ({want})")
        else:
            questions_c.fail(
                f"StoryQuestionsMonday was due {slot.isoformat()} for week {owed['week']} and no {want} send marker exists — "
                "the Monday questions never went out, so Wednesday's chronicle and episode will be written without the "
                'owner\'s voice. Check /aws/lambda/wednesday-chronicle for the {"story_questions": true} invoke; a re-send '
                "is the same event (it is idempotent on the marker)."
            )

    weeks = published_weeks(rows)
    if not weeks:
        # The vacuous-read trap: the season always has at least its prologue.
        msg = (
            f"{len(rows)} DATE# row(s) read on {pk} and NONE is a published, visible, numbered season week — "
            "a broken read or a renamed field, not an empty season. No verdict was reached."
        )
        episode_c.warn(msg)
        ledger_c.warn(msg)
        return out

    # ── (c) the ledger advanced ──
    gaps = ledger_gaps(weeks, ledger_rows)
    if gaps:
        ledger_c.fail(
            f"published week(s) with no season-ledger row: {'; '.join(gaps)}. The next installment reads the newest "
            "LEDGER# row as the story so far, so it will pick the season up from before this week — its threads, its bet "
            "and its featured coach are lost. Check chronicle-approve for '[#4533] ledger commit failed', and whether the "
            "week fell back to the legacy writer (no desk_ledger_json on the row)."
        )
    else:
        ledger_c.ok(f"every one of the {len(weeks)} published season week(s) has its LEDGER# row (weeks {min(weeks)}..{max(weeks)})")

    # ── (a) + (b) an episode, or a hold that is not yet old ──
    fetched = budget.get(site_base_url.rstrip("/") + EPISODES_PATH) if budget is not None else None
    doc = fetched.json() if fetched is not None and fetched.ok else None
    if not isinstance(doc, dict) or not isinstance(doc.get("episodes"), list):
        why = "no read budget was supplied" if fetched is None else (fetched.error or f"HTTP {fetched.status}, or not the episodes shape")
        episode_c.warn(f"{EPISODES_PATH} could not be read ({why}) — no verdict was reached on {len(weeks)} published week(s)")
        return out

    missing, escalated, sanctioned = episode_findings(weeks, doc, now)
    if missing or escalated:
        parts = []
        if missing:
            parts.append(
                f"published with NO Panel episode and no hold after {EPISODE_WINDOW_HOURS} h: {'; '.join(missing)} — "
                "the episode was silently skipped (#4365)"
            )
        if escalated:
            parts.append(
                f"HELD more than {HOLD_ESCALATE_DAYS} days: {'; '.join(escalated)} — release it, re-generate it or retire the week by name"
            )
        episode_c.fail(". ".join(parts) + ". Check /aws/lambda/coach-panel-podcast and s3 panelcast-holds/.")
    else:
        note = f" Open: {'; '.join(sanctioned)}." if sanctioned else ""
        episode_c.ok(
            f"every one of the {len(weeks)} published season week(s) has a Panel episode or a hold under {HOLD_ESCALATE_DAYS} days.{note}"
        )
    return out
