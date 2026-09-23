"""named_human_contact.py — the named-human contact path (#4063; v0.3 §9 / §13.3).

WHAT THIS IS. The owner designated one named human (2026-09-22) who should hear from
the platform when he goes quiet on it. The owner's ruling on #4063 box 1 (2026-09-23,
option A) is DISENGAGEMENT ONLY — no mood instrument, no PHQ-9 path:

  * rung ``quiet``    — the owner has gone quiet on the platform for a while → ONE
                         check-in email to the named contact;
  * rung ``four_week`` — no platform use for four weeks → a second (and last) email.

THE QUIET DEFINITION (ruled here, derived from existing signals — nothing new is
measured). "Platform use" is the registry's own answer to "which sources STOP when
Matthew disengages?": the ``engagement_channel`` facet in
``ingestion.source_registry`` (food / MacroFactor, measurement / Withings weigh-in,
training / Hevy, journal / Notion, habits / Habitify) — the same channel set, with the
same per-source "counts as logged" predicates, that ``content.engagement_core``'s
presence instrument reads. Quiet is:

    NO engagement channel has logged a day for N lag-adjusted days — i.e. no food
    log AND no weigh-in AND no workout AND no journal entry AND no completed habit.

``quiet_days`` uses engagement_core's 24h-lag grace (a channel logged today OR
yesterday reads 0), because nutrition in particular lands end-of-day.

  * N = 7 for the first email — ``ENGAGEMENT_SEVERITY_ALARM_CHANNEL_QUIET_DAYS``, the
    registry's existing line for "channels quiet long enough that the stall IS the
    story" (the presence ladder's alarm rung). It is imported, not restated, so the
    two cannot drift. It is deliberately stricter than that rung (ALL channels, not
    three), because this one reaches a person outside the system.
  * N = 28 for the second — the owner's own stated "four weeks of no use".

A logged ``travel`` day inside the trailing 7 is a PLANNED pause and holds the first
email (the engagement_core planned-pause precedent). It never holds the four-week
email: four weeks of no use is the owner's trigger unconditionally. Sick days do NOT
hold either rung — a sick week with no logging is exactly when a check-in is welcome.

EPISODES, DE-DUP, COOLDOWN. An episode is identified by its ANCHOR — the last day any
channel logged. While he stays quiet the anchor is constant; any log moves it and ends
the episode. Each rung sends at most once per episode (``four_week`` supersedes
``quiet`` when both are due on the same run, so one run sends at most one email). A new
episode's first email additionally waits out a ``QUIET_COOLDOWN_DAYS`` cooldown from the
previous first email, so a one-meal blip between two quiet weeks cannot mail the contact
twice in a fortnight. State lives in ONE DynamoDB row,
``USER#<user>#SOURCE#named_human_contact`` / ``STATE#current`` — SYSTEM_STATE in
``experiment.phase_taxonomy``, owner-only (Tier 2) in ``privacy.field_tiers``. It holds
dates and modes only; the contact's identity is NEVER written to it.

THE CONTACT. Read at runtime from the PRIVATE object
``s3://<bucket>/config/coaching/named_human.json`` (``name``, ``contact.email``,
``status``) and only once a rung is actually due. Fail closed: an absent/unreadable
object, ``status != "DESIGNATED"``, or a malformed name/email sends nothing. The name
and address are never logged, never stored, and never appear in this repo — tests use a
fake on a reserved ``.invalid`` domain.

ARMING. ``CONTACT_PATH_ARMED`` (env, default off). Unarmed, the exact body the contact
would receive is rendered to the OWNER's inbox instead, with a preview banner — the
owner's approval step before the first real send. Arming is an owner act: set
``CONTACT_PATH_ARMED=true`` on the ``evening-nudge`` function in
``cdk/stacks/email_stack.py`` and deploy LifePlatformEmail. A preview does not consume
the armed send: arming mid-episode still sends the real email once.

NO HEALTH DATA. The rendered body is a fixed template: that he has gone quiet on the
platform (in words — "about a week" / "about four weeks"), a nudge to check in, and
that it is automated at his request. No metric, mood, intake, note, number or date.
``render_email`` enforces it at runtime (no digit, no PII pattern, no banned vocabulary
term) and refuses to render otherwise; ``tests/test_named_human_contact_4063.py`` holds
the same contract plus the sensitive-content filter.

HOST. A fail-soft leg of the existing daily ``evening-nudge`` Lambda (03:00 UTC) — no
new cron. Every failure logs ``CONTACT_LEG_FAILED_TOKEN`` and never breaks the nudge.
"""

from __future__ import annotations

import html
import json
import os
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Mapping, Optional

from common.email_identity import OWNER_SENDER
from ingestion.source_registry import ENGAGEMENT_SEVERITY_ALARM_CHANNEL_QUIET_DAYS, engagement_channels

# ── The ruled thresholds ────────────────────────────────────────────────────────────
QUIET_DAYS = ENGAGEMENT_SEVERITY_ALARM_CHANNEL_QUIET_DAYS  # rung 1 — 7 lag-adjusted days, all channels
FOUR_WEEK_DAYS = 28  # rung 2 — the owner's "four weeks of no use"
QUIET_COOLDOWN_DAYS = 14  # min spacing between two first-rung emails across episodes
TRAVEL_HOLD_DAYS = QUIET_DAYS  # a travel log in the trailing week holds rung 1 only
# How far back a channel is searched for its last logged day. Past the four-week line
# with margin; a channel with nothing in the window reads as "quiet >= LOOKBACK".
LOOKBACK_DAYS = 35

RUNG_QUIET = "quiet"
RUNG_FOUR_WEEK = "four_week"
RUNGS = (RUNG_QUIET, RUNG_FOUR_WEEK)

MODE_ARMED = "armed"
MODE_PREVIEW = "preview"

STATE_SOURCE = "named_human_contact"
STATE_SK = "STATE#current"
CONFIG_KEY = "config/coaching/named_human.json"
DESIGNATED = "DESIGNATED"

# The ONE log token for every failure of this leg — a MetricFilter can count it.
CONTACT_LEG_FAILED_TOKEN = "NAMED-HUMAN-CONTACT-FAILED"  # noqa: S105 — a log token, not a credential

# Health vocabulary the rendered body may never carry (checked case-insensitively on
# word boundaries). The body is a fixed template, so this is a tripwire on a future
# edit of the template, not a filter on data — there is no data in it to filter.
BANNED_BODY_TERMS: tuple[str, ...] = (
    "weight",
    "weigh",
    "lbs",
    "pound",
    "kcal",
    "calorie",
    "calories",
    "food",
    "meal",
    "eat",
    "eating",
    "intake",
    "drink",
    "alcohol",
    "mood",
    "depressed",
    "depression",
    "anxiety",
    "phq",
    "sleep",
    "hrv",
    "heart",
    "glucose",
    "journal",
    "note",
    "notes",
    "workout",
    "training",
    "habit",
    "habits",
    "score",
    "metric",
    "health data",
    "diagnos",
)

_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+$")
_PII_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_DIGIT_RE = re.compile(r"\d")


# ── Env ─────────────────────────────────────────────────────────────────────────────
def is_armed(env: Optional[Mapping[str, str]] = None) -> bool:
    """True only for an explicit truthy CONTACT_PATH_ARMED. Absent/anything else → off."""
    value = (env if env is not None else os.environ).get("CONTACT_PATH_ARMED", "")
    return str(value).strip().lower() in ("1", "true", "yes", "on")


# ── Pure: the quiet computation ─────────────────────────────────────────────────────
def _to_date(value: Any) -> Optional[date]:
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def quiet_days_since(anchor: Optional[str], today: str, lookback_days: int = LOOKBACK_DAYS) -> Optional[int]:
    """Lag-adjusted days since `anchor` (engagement_core's grace: today/yesterday → 0).

    `anchor` None means no channel logged inside the lookback window, which is quiet for
    AT LEAST `lookback_days`. Returns None only when `today` itself is unparseable.
    """
    t = _to_date(today)
    if t is None:
        return None
    if anchor is None:
        return lookback_days
    a = _to_date(anchor)
    if a is None:
        return None
    return max(0, (t - a).days - 1)


def last_platform_use(channel_last: Mapping[str, Optional[str]]) -> Optional[str]:
    """The newest day across all channels (None = nothing logged in the window)."""
    days = [str(d)[:10] for d in channel_last.values() if d is not None and _to_date(d) is not None]
    return max(days) if days else None


def _mode_blocks(sent_mode: Optional[str], mode: str) -> bool:
    """Whether a prior send in `sent_mode` blocks a send in `mode`.

    An armed send blocks everything; a preview blocks only another preview, so arming
    mid-episode still delivers the real email once.
    """
    if not sent_mode:
        return False
    return sent_mode == MODE_ARMED or mode == MODE_PREVIEW


def decide(
    *,
    today: str,
    anchor: Optional[str],
    state: Optional[Mapping[str, Any]],
    armed: bool,
    travel_days: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    """Pure decision: which rung (if any) to send tonight, and the next state row.

    Returns {"send": rung|None, "reason": str, "quiet_days": int|None, "mode": str,
    "state": dict} — `state` is what to persist (identity-free) if the send succeeds.
    """
    mode = MODE_ARMED if armed else MODE_PREVIEW
    prev = dict(state or {})
    quiet = quiet_days_since(anchor, today)
    anchor_key = anchor or "none"
    out: dict[str, Any] = {"send": None, "reason": "", "quiet_days": quiet, "mode": mode, "state": {}}

    if quiet is None:
        out["reason"] = "unparseable_dates"
        return out

    # The episode: same anchor → same episode; a different anchor starts a fresh one,
    # carrying only the cross-episode cooldown fields forward.
    episode = prev if prev.get("episode_anchor") == anchor_key else {}
    new_state: dict[str, Any] = {
        "episode_anchor": anchor_key,
        "episode_quiet_days": quiet,
        "last_quiet_sent_on": prev.get("last_quiet_sent_on"),
        "last_quiet_sent_mode": prev.get("last_quiet_sent_mode"),
    }
    for rung in RUNGS:
        for suffix in ("sent_on", "mode"):
            key = f"{rung}_{suffix}"
            if episode.get(key) is not None:
                new_state[key] = episode[key]
    out["state"] = new_state

    if quiet < QUIET_DAYS:
        out["reason"] = "not_quiet"
        return out

    four_week_blocked = _mode_blocks(episode.get(f"{RUNG_FOUR_WEEK}_mode"), mode)
    if quiet >= FOUR_WEEK_DAYS:
        if four_week_blocked:
            out["reason"] = "four_week_already_sent"
            return out
        out["send"] = RUNG_FOUR_WEEK
        out["reason"] = "four_weeks_quiet"
        return out

    if _mode_blocks(episode.get(f"{RUNG_QUIET}_mode"), mode):
        out["reason"] = "quiet_already_sent"
        return out
    t = _to_date(today)
    if t is None:  # unreachable: quiet is not None ⇒ today parsed
        out["reason"] = "unparseable_dates"
        return out
    hold_from = t - timedelta(days=TRAVEL_HOLD_DAYS)
    if any((d := _to_date(x)) is not None and hold_from <= d <= t for x in travel_days):
        out["reason"] = "planned_pause_travel"
        return out
    last_sent = _to_date(prev.get("last_quiet_sent_on"))
    if last_sent is not None and _mode_blocks(prev.get("last_quiet_sent_mode"), mode) and (t - last_sent).days < QUIET_COOLDOWN_DAYS:
        out["reason"] = "cooldown"
        return out
    out["send"] = RUNG_QUIET
    out["reason"] = "quiet"
    return out


def state_after_send(decision: Mapping[str, Any], today: str) -> dict[str, Any]:
    """The state row to persist once `decision["send"]` actually went out."""
    rung, mode = decision["send"], decision["mode"]
    state = dict(decision["state"])
    state[f"{rung}_sent_on"] = today
    state[f"{rung}_mode"] = mode
    if rung == RUNG_FOUR_WEEK and not state.get(f"{RUNG_QUIET}_mode"):
        # Superseded: one run sends at most one email, and the quiet rung never sends
        # after the four-week one in the same episode.
        state[f"{RUNG_QUIET}_sent_on"] = today
        state[f"{RUNG_QUIET}_mode"] = f"superseded_{mode}"
    if rung == RUNG_QUIET:
        state["last_quiet_sent_on"] = today
        state["last_quiet_sent_mode"] = mode
    return state


# ── Pure: the contact config ────────────────────────────────────────────────────────
def parse_contact(raw: Any) -> Optional[dict[str, str]]:
    """{"name", "email"} from the private config, or None (fail closed).

    None when the payload is not a dict, `status` is not DESIGNATED, or either field is
    missing/malformed. Never raises and never echoes the payload.
    """
    if not isinstance(raw, Mapping):
        return None
    if str(raw.get("status", "")).strip().upper() != DESIGNATED:
        return None
    name = raw.get("name")
    contact = raw.get("contact")
    email = contact.get("email") if isinstance(contact, Mapping) else None
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 80 or _DIGIT_RE.search(name):
        return None
    if not isinstance(email, str) or not _EMAIL_RE.match(email.strip()):
        return None
    return {"name": name.strip(), "email": email.strip()}


# ── Pure: the rendered email ────────────────────────────────────────────────────────
_SUBJECTS = {
    RUNG_QUIET: "Checking in on Matthew",
    RUNG_FOUR_WEEK: "Still checking in on Matthew",
}
_SPAN_WORDS = {RUNG_QUIET: "about a week", RUNG_FOUR_WEEK: "about four weeks"}
_CLOSERS = {
    RUNG_QUIET: "It sends this once for a quiet stretch, and one more time only if the stretch reaches four weeks.",
    RUNG_FOUR_WEEK: "This is the last message it will send for this stretch.",
}


def _first_name(name: str) -> str:
    return name.split()[0] if name.split() else name


def render_body_text(rung: str, contact_name: str) -> str:
    """The plain-text body the contact receives — a fixed template, no data."""
    return (
        f"Hi {_first_name(contact_name)},\n\n"
        "You are getting this because Matthew named you as the one person to hear from "
        "if he goes quiet on the personal tracking platform he built.\n\n"
        f"He has not used it for {_SPAN_WORDS[rung]}. That is all it knows, and all it "
        "shares — it may be nothing at all.\n\n"
        "If you can, reach out to him directly: a message or a call to check in.\n\n"
        f"This message is automated and was set up at his own request. {_CLOSERS[rung]} "
        "Please do not reply to this address — contact Matthew himself.\n"
    )


def body_violations(text: str) -> list[str]:
    """Why a rendered body is not safe to send (empty = safe). Used at runtime AND in tests."""
    found: list[str] = []
    if _DIGIT_RE.search(text):
        found.append("digit")
    if _PII_EMAIL_RE.search(text):
        found.append("email_address")
    low = text.lower()
    for term in BANNED_BODY_TERMS:
        if re.search(rf"\b{re.escape(term)}", low):
            found.append(f"term:{term}")
    return found


def render_email(rung: str, contact_name: str, *, armed: bool) -> dict[str, str]:
    """{"subject", "text", "html"} for `rung`. Raises ValueError on a body violation.

    Unarmed, the SAME body is wrapped in a preview banner addressed to the owner; the
    violation check runs on the contact-facing body, which is the thing that matters.
    """
    if rung not in RUNGS:
        raise ValueError(f"unknown rung {rung!r}")
    text = render_body_text(rung, contact_name)
    bad = body_violations(text) + body_violations(_SUBJECTS[rung])
    if bad:
        raise ValueError(f"named-human body failed its no-health-data contract: {bad}")
    subject = _SUBJECTS[rung]
    paragraphs = "".join(f'<p style="margin:0 0 14px;">{html.escape(p)}</p>' for p in text.strip().split("\n\n"))
    body_html = f'<div style="font-family:-apple-system,Segoe UI,sans-serif;font-size:15px;line-height:1.5;color:#1f2937;max-width:560px;">{paragraphs}</div>'
    if not armed:
        banner = (
            "PREVIEW — the named-human contact path is NOT ARMED. Nothing was sent to your contact. "
            "Below is exactly what they would have received. To arm it: set CONTACT_PATH_ARMED=true "
            "on evening-nudge in cdk/stacks/email_stack.py and deploy LifePlatformEmail."
        )
        subject = f"[Preview, not sent] {subject}"
        text = f"{banner}\n\n---\n\n{text}"
        body_html = (
            f'<div style="background:#fef3c7;border-radius:8px;padding:12px 14px;margin:0 0 18px;'
            f'font-family:-apple-system,Segoe UI,sans-serif;font-size:13px;color:#92400e;">{html.escape(banner)}</div>{body_html}'
        )
    return {"subject": subject, "text": text, "html": body_html}


# ── I/O: DynamoDB reads + the state write ───────────────────────────────────────────
def _pk(user_id: str, source: str) -> str:
    return f"USER#{user_id}#SOURCE#{source}"


def channel_last_logged(table: Any, user_id: str, today: str) -> dict[str, Optional[str]]:
    """{source: newest counted-as-logged day in the lookback, or None} per channel.

    Raises on any read failure — the caller treats unknown as NOT quiet (fail closed).
    """
    from content.engagement_core import channel_counts_as_logged, channel_presence_fields

    t = _to_date(today)
    if t is None:
        raise ValueError("unparseable today")
    floor = (t - timedelta(days=LOOKBACK_DAYS)).isoformat()
    out: dict[str, Optional[str]] = {}
    for source in engagement_channels():
        projection = ", ".join(("sk",) + tuple(channel_presence_fields(source)))
        resp = table.query(
            KeyConditionExpression="pk = :pk AND sk BETWEEN :lo AND :hi",
            ExpressionAttributeValues={":pk": _pk(user_id, source), ":lo": f"DATE#{floor}", ":hi": f"DATE#{today}~"},
            ScanIndexForward=False,
            ProjectionExpression=projection,
        )
        latest = None
        for item in resp.get("Items", []):
            day = str(item.get("sk", ""))[5:15]
            if _to_date(day) is None or not channel_counts_as_logged(source, item):
                continue
            latest = day if latest is None or day > latest else latest
        out[source] = latest
    return out


def travel_days(table: Any, user_id: str, today: str) -> frozenset[str]:
    """Travel-logged days in the trailing hold window. Raises on read failure."""
    t = _to_date(today)
    if t is None:
        return frozenset()
    lo = (t - timedelta(days=TRAVEL_HOLD_DAYS)).isoformat()
    resp = table.query(
        KeyConditionExpression="pk = :pk AND sk BETWEEN :lo AND :hi",
        ExpressionAttributeValues={":pk": _pk(user_id, "travel"), ":lo": f"DATE#{lo}", ":hi": f"DATE#{today}~"},
        ProjectionExpression="sk",
    )
    return frozenset(str(i.get("sk", ""))[5:15] for i in resp.get("Items", []))


def load_state(table: Any, user_id: str) -> dict[str, Any]:
    item = table.get_item(Key={"pk": _pk(user_id, STATE_SOURCE), "sk": STATE_SK}).get("Item") or {}
    return dict(item)


def save_state(table: Any, user_id: str, state: Mapping[str, Any]) -> None:
    item = {k: v for k, v in state.items() if v is not None}
    item.update(
        {
            "pk": _pk(user_id, STATE_SOURCE),
            "sk": STATE_SK,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    table.put_item(Item=item)


def load_contact(s3_client: Any, bucket: str) -> Optional[dict[str, str]]:
    """The designated contact, or None (fail closed on ANY error). Never logs the payload."""
    try:
        body = s3_client.get_object(Bucket=bucket, Key=CONFIG_KEY)["Body"].read()
        return parse_contact(json.loads(body))
    except Exception:
        return None


def newest_row_day(table: Any, user_id: str) -> Optional[str]:
    """The newest DATE# day on ANY channel partition, with no floor and no predicate.

    Only consulted when no channel logged inside the lookback: it turns "quiet for at
    least LOOKBACK_DAYS" into a real, STABLE anchor (so the episode key does not move
    daily), and it is the fail-closed guard against a mis-keyed read — a platform with no
    rows at all is a broken read, not a four-week silence. Raises on read failure.
    """
    newest: Optional[str] = None
    for source in engagement_channels():
        resp = table.query(
            KeyConditionExpression="pk = :pk AND begins_with(sk, :pfx)",
            ExpressionAttributeValues={":pk": _pk(user_id, source), ":pfx": "DATE#"},
            ScanIndexForward=False,
            Limit=1,
            ProjectionExpression="sk",
        )
        for item in resp.get("Items", []):
            day = str(item.get("sk", ""))[5:15]
            if _to_date(day) is not None and (newest is None or day > newest):
                newest = day
    return newest


def _default_s3_client() -> Any:
    import boto3

    return boto3.client("s3", region_name=os.environ.get("AWS_REGION", "us-west-2"))


# ── The leg ─────────────────────────────────────────────────────────────────────────
def run_leg(
    *,
    table: Any,
    ses_client: Any,
    today: str,
    user_id: str,
    owner_recipient: str,
    event_dry_run: bool,
    log: Callable[[str], None],
    s3_client_factory: Optional[Callable[[], Any]] = None,
    bucket: Optional[str] = None,
    env: Optional[Mapping[str, str]] = None,
) -> dict[str, Any]:
    """Evaluate tonight's rung and (maybe) send. Identity-free result, safe to log.

    `event_dry_run` (an operator's `{"dry_run": true}` invoke) sends nothing and writes
    nothing. Unarmed, the email goes to `owner_recipient` as a preview. The contact's
    name/address never reach `log` or the returned dict.
    """
    armed = is_armed(env)
    result: dict[str, Any] = {"armed": armed, "sent": False, "rung": None, "reason": ""}
    try:
        channels = channel_last_logged(table, user_id, today)
        anchor = last_platform_use(channels)
        if anchor is None:
            anchor = newest_row_day(table, user_id)
            if anchor is None:
                result["reason"] = "no_history"
                log("[contact] no engagement-channel rows at all — treated as a broken read, no send")
                return result
        trips = travel_days(table, user_id, today)
        state = load_state(table, user_id)
    except Exception as e:  # unknown is never quiet
        result["reason"] = "read_failed"
        log(f"[contact] {CONTACT_LEG_FAILED_TOKEN} signal read failed ({type(e).__name__}) — no send")
        return result

    decision = decide(today=today, anchor=anchor, state=state, armed=armed, travel_days=trips)
    result.update({"rung": decision["send"], "reason": decision["reason"], "quiet_days": decision["quiet_days"]})
    log(f"[contact] quiet_days={decision['quiet_days']} decision={decision['reason']} rung={decision['send']} armed={armed}")
    if not decision["send"]:
        return result

    contact = load_contact(
        s3_client_factory() if s3_client_factory is not None else _default_s3_client(),
        bucket or os.environ.get("S3_BUCKET", "matthew-life-platform"),
    )
    if contact is None:
        result["reason"] = "contact_unavailable"
        log(f"[contact] {CONTACT_LEG_FAILED_TOKEN} contact config absent, unreadable or not DESIGNATED — fail closed, no send")
        return result

    try:
        email = render_email(decision["send"], contact["name"], armed=armed)
    except ValueError:
        result["reason"] = "body_contract_failed"
        log(f"[contact] {CONTACT_LEG_FAILED_TOKEN} rendered body failed the no-health-data contract — no send")
        return result

    recipient = contact["email"] if armed else owner_recipient
    audience = "named contact" if armed else "owner (preview)"
    if event_dry_run:
        result["reason"] = "event_dry_run"
        log(f"[contact] dry-run invoke: would send rung={decision['send']} to the {audience} — suppressed, state unchanged")
        return result

    # Not routed through common.send_guard.guarded_send_email: the dry-run decision is
    # made above, and that helper's dry-run log prints the recipient — which here is the
    # contact's address. The send itself is the plain SES v2 call.
    ses_client.send_email(
        FromEmailAddress=OWNER_SENDER,
        Destination={"ToAddresses": [recipient]},
        Content={
            "Simple": {
                "Subject": {"Data": email["subject"], "Charset": "UTF-8"},
                "Body": {
                    "Text": {"Data": email["text"], "Charset": "UTF-8"},
                    "Html": {"Data": email["html"], "Charset": "UTF-8"},
                },
            }
        },
    )
    result["sent"] = True
    log(f"[contact] sent rung={decision['send']} to the {audience}")
    try:
        save_state(table, user_id, state_after_send(decision, today))
    except Exception as e:
        # The mail is out; a failed marker means tomorrow may resend. Loud, not fatal.
        log(f"[contact] {CONTACT_LEG_FAILED_TOKEN} state write failed after send ({type(e).__name__}) — a resend is possible")
    return result
