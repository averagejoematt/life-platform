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

THE OWNER'S HOLD IS A THIRD STATE (#6112, owner ruling 2026-11-16)
  A week now reads as exactly one of: DELIVERED (an episode row in episodes.json), HELD (a named record says why it
  is not on air) or MISSING (neither) — and only MISSING fails. An owner hold is `panelcast-holds/wk{N}.json` with
  `hold_class: "owner"` (private, the authority — emails/panelcast_hold.py); its public face is a line in
  episodes.json's `held` list, re-derived from the private record on every index write. The line is accepted only
  when it is structurally complete — a week, a held_at date, a decider and a reason (`panelcast_hold.public_problems`,
  the writer's own validator); an empty or malformed line is NOT a hold and the week reads as missing.
  A held week is reported on the green line, named and aged — visible, never silent. It does not hold the
  delivery-FAILURE alarm red: the episode did not fail to deliver, the owner decided it should not. But a hold must
  not be forgettable either, so past OWNER_HOLD_REVIEW_DAYS the check WARNs (an alarmed warn — `qa-smoke-warnings`,
  never `qa-smoke-failures`, never chronic) until the owner releases, retires or re-records the hold. An automated
  `pending` hold keeps its 7-day FAIL escalation: that one is a gate result nobody has looked at yet.

WHAT IS NOT CLAIMED
  * The `pending` marker holds ONE week (owner holds are a list and have no such limit). Two weeks held at once show as one hold and one
    bare miss, which is the louder reading and the correct one.
  * A week the owner RETIRED by name (episodes.json `retired`, #4536) is accounted for:
    named in the green line, never a miss and never an escalated hold.
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
from emails.panelcast_hold import PUBLIC_KEY as OWNER_HELD_KEY, public_problems as owner_hold_problems
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
# #6112: an OWNER hold is reported OK until it is this old, then WARNs (alarmed, never a FAIL). Four weekly editions and
# the monthly full review: long enough that a deliberate hold is not nagged, short enough that it cannot be forgotten.
# Re-recording the hold (scripts/panel_owner_hold.py --apply with a new --decided date) is the owner's way to say
# "still held, on purpose".
OWNER_HOLD_REVIEW_DAYS = 28

# (d) `StoryQuestionsMonday` — its config/schedules.json row, Pacific wall clock (the table's
# platform_timezone, #4284 / ADR-165). Pinned to the row by tests/test_heartbeat_completeness.py,
# so moving the schedule moves the dead-man or reds.
QUESTIONS_WEEKDAY = "MON"
QUESTIONS_HOUR_PT = 9
QUESTIONS_MINUTE_PT = 0
QUESTIONS_GRACE_HOURS = 1
# The rule's first live send. A Monday before it was never owed a send.
QUESTIONS_FIRST_SEND = "2026-10-05"

EPISODE_CHECK = "story_season:episode_or_hold"
LEDGER_CHECK = "story_season:ledger_advanced"
QUESTIONS_CHECK = "story_season:monday_questions"
DOOR_CHECK = "story_season:chapter_door"

# #5520 (e) the Story door's dead-man. /api/chapters is the ONE served account of every program
# week (site_api_chapters.compose): published, held (a draft awaiting approval), skipped (with the
# writer's reason) or pending (the week in progress). The door went 27 days on a Week-6 chapter
# (approved 2026-10-18, the next approved 2026-11-14) while two drafts sat and a week went
# unwritten, and nothing on the platform said so. A newest chapter older than this reds.
CHAPTERS_PATH = "/api/chapters"
DOOR_STALE_DAYS = 10
WEEK_STATUSES = ("published", "held", "skipped", "pending")

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


def retired_weeks(doc: dict) -> dict[int, str]:
    """`{week: retired_at}` from episodes.json's public `retired` list (#4536 — the coach-panel-podcast
    `{"week": N, "retire": true}` path writes it beside the private marker in panelcast-holds/)."""
    out: dict[int, str] = {}
    for r in doc.get("retired") or []:
        if not isinstance(r, dict):
            continue
        try:
            out[int(r.get("week"))] = str(r.get("retired_at") or "")
        except (TypeError, ValueError):
            continue
    return out


def owner_holds(doc: dict) -> tuple[dict[int, dict], dict[int, str]]:
    """`(valid, malformed)` from episodes.json's `held` list — `{week: line}` and `{week: why it is not a hold}`."""
    valid: dict[int, dict] = {}
    malformed: dict[int, str] = {}
    for e in doc.get(OWNER_HELD_KEY) or []:
        problems = owner_hold_problems(e)
        try:
            wk = int(e.get("week"))
        except (AttributeError, TypeError, ValueError):
            continue  # a line naming no week excuses nothing and names nothing
        if problems:
            malformed[wk] = ", ".join(problems)
        else:
            valid[wk] = e
    return valid, malformed


def episode_verdicts(weeks: dict[int, dict], doc: dict, now: datetime) -> dict[str, list[str]]:
    """Every published week, sorted into exactly one bucket — each a list of sentences naming a week.

    delivered  an episode row in episodes.json                                  -> counted, green
    held       the owner holds it (a valid `held` line), under the review bound  -> named + aged, green
    aged       the owner holds it, past OWNER_HOLD_REVIEW_DAYS                   -> WARN (never a FAIL)
    sanctioned retired by name, inside the 48 h window, or an automated hold < 7 d -> named, green
    escalated  an automated (`pending`) hold past 7 days                         -> FAIL
    missing    past 48 h with none of the above                                  -> FAIL
    """
    aired: set[int] = set()
    for e in doc.get("episodes") or []:
        try:
            aired.add(int(e.get("week")))
        except (TypeError, ValueError):
            continue
    raw = doc.get("pending")
    pending: dict = raw if isinstance(raw, dict) else {}
    try:
        held_week: Optional[int] = int(pending.get("week")) if pending.get("reason") == HOLD_REASON else None
    except (TypeError, ValueError):
        held_week = None
    held_at = parse_iso_utc(pending.get("noted_at")) if held_week is not None else None
    retired = retired_weeks(doc)
    owner, malformed = owner_holds(doc)

    out: dict[str, list[str]] = {k: [] for k in ("delivered", "held", "aged", "sanctioned", "escalated", "missing")}
    for wk in sorted(weeks):
        published = weeks[wk]["published"]
        if wk in aired:
            out["delivered"].append(f"week {wk}")
            continue
        if wk in retired:  # #4536: the owner retired the week by name — accounted for, never a bare miss
            out["sanctioned"].append(
                f"week {wk} retired by name {retired[wk] or ''}".rstrip() + f" (chronicle published {published.isoformat()})"
            )
            continue
        if wk in owner:  # #6112: held on purpose, for a recorded reason — visible, aged, never a delivery failure
            line = owner[wk]
            since = parse_iso_utc(line.get("held_at"))
            age = (now - since).total_seconds() / 86400 if since is not None else 0.0
            sentence = (
                f"week {wk} HELD by {line.get('decided_by')} since {str(line.get('held_at'))[:10]} ({age:.1f} d): "
                f"{line.get('reason')} (chronicle published {published.isoformat()})"
            )
            out["aged" if age > OWNER_HOLD_REVIEW_DAYS else "held"].append(sentence)
            continue
        due = published + timedelta(hours=EPISODE_WINDOW_HOURS)
        if now <= due:
            out["sanctioned"].append(f"week {wk} published {published.isoformat()} — inside its {EPISODE_WINDOW_HOURS} h window")
            continue
        overdue_days = (now - due).total_seconds() / 86400
        if held_week == wk and held_at is not None:
            age_days = max((now - held_at).total_seconds() / 86400, overdue_days)
            line_s = f"week {wk} held since {held_at.isoformat()} ({age_days:.1f} d, chronicle published {published.isoformat()})"
            out["escalated" if age_days > HOLD_ESCALATE_DAYS else "sanctioned"].append(line_s)
            continue
        why = f"; its `held` line was not accepted as a hold ({malformed[wk]})" if wk in malformed else ""
        out["missing"].append(f"week {wk} (chronicle published {published.isoformat()}, {overdue_days:.1f} d past its window{why})")
    return out


def episode_findings(weeks: dict[int, dict], doc: dict, now: datetime) -> tuple[list[str], list[str], list[str]]:
    """`(missing, escalated, sanctioned)` — the #4539 shape, kept for its callers. An owner hold (held or aged) is
    folded into `sanctioned`: it is never missing and never escalated."""
    v = episode_verdicts(weeks, doc, now)
    return v["missing"], v["escalated"], v["sanctioned"] + v["held"] + v["aged"]


def ledger_gaps(weeks: dict[int, dict], ledger_rows: list[dict]) -> list[str]:
    """The published weeks with no visible `LEDGER#{date}` row for any of their dates."""
    have = {str(r.get("sk", ""))[len(LEDGER_PREFIX) :] for r in ledger_rows if singleton_visible(r)}
    return [
        f"week {wk} (expected {LEDGER_PREFIX}{' or '.join(sorted(set(w['dates'])))})"
        for wk, w in sorted(weeks.items())
        if not have & set(w["dates"])
    ]


def last_questions_send(now: datetime) -> datetime:
    """The newest scheduled `StoryQuestionsMonday` instant whose grace has elapsed, as a UTC instant.
    The schedule is Pacific wall clock (#4284), so the slot is built on the Pacific calendar — aware
    arithmetic on one ZoneInfo is wall-clock arithmetic, so 09:00 PT stays 09:00 PT across a DST change."""
    from common.pacific_time import PACIFIC

    ref = (now.astimezone(timezone.utc) - timedelta(hours=QUESTIONS_GRACE_HOURS)).astimezone(PACIFIC)
    slot = ref.replace(hour=QUESTIONS_HOUR_PT, minute=QUESTIONS_MINUTE_PT, second=0, microsecond=0)
    slot -= timedelta(days=(slot.weekday() - _WEEKDAYS.index(QUESTIONS_WEEKDAY)) % 7)
    if slot > ref:
        slot -= timedelta(days=7)
    return slot.astimezone(timezone.utc)


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
    from common import outbound_trial

    if outbound_trial.is_on(outbound_trial.STORY_QUESTIONS_PAUSED):
        # #6176 item 4: the sender reads this same committed switch and logs '[outbound-trial] ... suppressed' instead of
        # sending, so a paused Monday is the recognised state, not a miss.
        questions_c.ok(
            f"Monday story questions paused by the outbound trial ({outbound_trial.TRIAL_ISSUE}, #6174) — "
            f"no send owed for {slot.date().isoformat()}; the sender logs its suppression"
        )
    elif owed is None:
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

    v = episode_verdicts(weeks, doc, now)
    open_lines = v["held"] + v["aged"] + v["sanctioned"]
    note = f" Open: {'; '.join(open_lines)}." if open_lines else ""
    if v["missing"] or v["escalated"]:
        parts = []
        if v["missing"]:
            parts.append(
                f"published with NO Panel episode and no hold after {EPISODE_WINDOW_HOURS} h: {'; '.join(v['missing'])} — "
                "the episode was silently skipped (#4365)"
            )
        if v["escalated"]:
            parts.append(
                f"HELD more than {HOLD_ESCALATE_DAYS} days: {'; '.join(v['escalated'])} — release it, re-generate it or retire the week by name"
            )
        others = f" Also open: {'; '.join(v['held'] + v['aged'])}." if v["held"] or v["aged"] else ""
        episode_c.fail(". ".join(parts) + ". Check /aws/lambda/coach-panel-podcast and s3 panelcast-holds/." + others)
    elif v["aged"]:
        episode_c.warn(
            f"owner hold(s) older than {OWNER_HOLD_REVIEW_DAYS} days: {'; '.join(v['aged'])}. Not a delivery failure — the owner "
            "decided it — but a hold is not meant to be forgotten: release it (scripts/panel_owner_hold.py --release), retire "
            f"the week by name, or re-record the hold with a new decided date.{note}"
        )
    else:
        episode_c.ok(
            f"{len(v['delivered'])} of the {len(weeks)} published season week(s) delivered; every other one is held for a "
            f"recorded reason, retired by name, or inside its window.{note}"
        )
    return out


def door_findings(doc: dict, now: datetime) -> tuple[list[str], Optional[float], list[str]]:
    """`(unexplained, age_days, open_weeks)` for the served /api/chapters document — pure.

    * `unexplained` — an elapsed program week the route serves with no recognised status, or a
      `skipped` week with no reason: the reader is told nothing about it.
    * `age_days` — days since the newest published chapter went public (`published_at`, the owner's
      approval instant; else its `date` at midnight UTC). None when no week has published yet.
    * `open_weeks` — the held and skipped weeks, named, so a red says what is waiting and why.
    """
    unexplained: list[str] = []
    open_weeks: list[str] = []
    newest: Optional[datetime] = None
    for w in doc.get("weeks") or []:
        if not isinstance(w, dict):
            continue
        wk, status = w.get("week"), w.get("status")
        if status not in WEEK_STATUSES:
            unexplained.append(f"week {wk} served with status {status!r}")
            continue
        if status == "skipped":
            reason = str(w.get("reason") or "").strip()
            if not reason:
                unexplained.append(f"week {wk} skipped with no reason")
            else:
                open_weeks.append(f"week {wk} skipped ({reason})")
        elif status == "held":
            open_weeks.append(f"week {wk} drafted {str(w.get('drafted_at') or '?')[:10]}, awaiting approval")
        elif status == "published":
            when = parse_iso_utc(w.get("published_at")) or parse_iso_utc(str(w.get("date") or "")[:10])
            if when is not None and (newest is None or when > newest):
                newest = when
    age = None if newest is None else (now - newest).total_seconds() / 86400.0
    return unexplained, age, open_weeks


def check_chapter_door(
    check_cls: Callable[..., Any],
    partition: str,
    pt_now: Callable[[], datetime],
    *,
    site_base_url: str,
    budget: Any = None,
) -> list:
    """#5520: every elapsed program week is served with a state, and the door is never older than
    DOOR_STALE_DAYS. Read over HTTP from /api/chapters exactly as the doors read it — the route is the
    one producer of the per-week state, so this checks the served account, not a re-derivation."""
    c = check_cls(DOOR_CHECK, "Data Freshness", partition)
    now = pt_now().astimezone(timezone.utc)
    fetched = budget.get(site_base_url.rstrip("/") + CHAPTERS_PATH) if budget is not None else None
    doc = fetched.json() if fetched is not None and fetched.ok else None
    if not isinstance(doc, dict) or not isinstance(doc.get("weeks"), list):
        why = "no read budget was supplied" if fetched is None else (fetched.error or f"HTTP {fetched.status}, or not the chapters shape")
        c.warn(f"{CHAPTERS_PATH} could not be read ({why}) — no verdict was reached on the Story door")
        return [c]
    if not doc["weeks"]:
        c.warn(f"{CHAPTERS_PATH} served no program weeks (genesis {doc.get('genesis')!r}, as of {doc.get('as_of')!r}) — no verdict")
        return [c]
    unexplained, age, open_weeks = door_findings(doc, now)
    note = f" Open: {'; '.join(open_weeks)}." if open_weeks else ""
    parts = []
    if unexplained:
        parts.append(f"program week(s) the door serves with no state or no reason: {'; '.join(unexplained)}")
    if age is None:
        parts.append(f"no program week has a published chapter across {len(doc['weeks'])} served week(s)")
    elif age > DOOR_STALE_DAYS:
        parts.append(f"the newest published chapter is {age:.0f} days old (limit {DOOR_STALE_DAYS}) — the Story door has gone stale")
    if parts:
        c.fail(". ".join(parts) + "." + note + " Approve or retire the held draft, or check /aws/lambda/wednesday-chronicle.")
    else:
        c.ok(f"newest published chapter {age:.1f} days old (limit {DOOR_STALE_DAYS}); every elapsed week served with a state.{note}")
    return [c]
