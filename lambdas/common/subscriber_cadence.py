"""subscriber_cadence.py — the ONE derivation behind every cadence promise and
week number a subscriber is shown (#3564, #3565; epic #3498).

Root cause this fixes: `/subscribe/` promised "One email a week, then quiet
until next Wednesday" and the confirmation email promised "every Wednesday",
while the three subscriber-facing senders #1951 enabled deliver up to THREE
emails a week and (measured over 35 days of CloudWatch) none of them on a
Wednesday. The promise was hand-typed prose; the cadence is entirely
cron-derivable. Nothing coupled the two, so they drifted the moment #1951
turned two more senders on.

The rule (ADR-104, honest numbers): **a promise shown to a subscriber is
rendered from the schedules that make it true**, never re-typed. `promise_sentence()`
below IS the copy that ships on `/subscribe/`, in the confirmation email, in the
welcome email and in the site's post-subscribe JS — one string, computed from
the cron literals in `cdk/stacks/email_stack.py`. If a cron moves, the sentence
moves and `tests/test_subscriber_cadence_promise_3564.py` reds until every
surface carries the new one.

WHAT A SUBSCRIBER ACTUALLY RECEIVES (derived below, verified against the live
CloudWatch delivery record in #3564):

  * `weekly-signal`        Sunday 16:30 UTC (9:30 AM PT) — the week's numbers.
                           The one unconditional weekly send.
  * `between-chronicle`    Sunday 17:00 UTC (10:00 AM PT) — only when there is
                           genuinely new, previously-unsent content (#398's
                           content-hash dedup). Often silent.
  * `chronicle-email-sender` Wednesday 15:10 UTC (8:10 AM PT) — a clean no-op
                           unless an installment actually PUBLISHED. The
                           Wednesday draft (`wednesday-chronicle`,
                           `cron(0 15 ? * WED *)`) defaults to PREVIEW_MODE and
                           waits for the owner's approval click; the
                           `chronicle-approve` sweep (`cron(0 18 * * ? *)`)
                           auto-publishes any draft older than
                           CHRONICLE_AUTOPUBLISH_HOURS=48 and invokes the sender
                           inline. 48h after Wednesday 15:00 UTC is Friday 15:00
                           UTC, and the first sweep at/after that is Friday 18:00
                           UTC — which is exactly where the trailing 35 days of
                           "Sent 1/1" datapoints landed. So the honest phrasing
                           is "Wednesday, or Friday when a draft auto-publishes",
                           and `chronicle_autopublish_weekday()` DERIVES that
                           Friday rather than asserting it.

Why the copy was corrected instead of the cadence: the senders are doing what
#1951's owner decision asked of them (make the weekly promise true), and every
delivery in the record is a real, wanted email. The defect was entirely in the
prose. Nothing in this module changes what sends, when, or to whom.

Zero AWS calls, zero `datetime.now()` — every clock-dependent function takes an
explicit `now`, so the whole module is unit-testable with a frozen clock (the
same posture as the sibling `common/content_cadence.py`).
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional

from common.constants import EXPERIMENT_START_DATE

# EventBridge day-of-week tokens → Python `weekday()` (Monday=0 … Sunday=6).
_DOW_TOKENS = {"MON": 0, "TUE": 1, "WED": 2, "THU": 3, "FRI": 4, "SAT": 5, "SUN": 6}
_WEEKDAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
_COUNT_WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven"}


@dataclass(frozen=True)
class SubscriberSender:
    """One subscriber-facing sender, mirrored from its CDK construct.

    `cron` and `construct_id` are the load-bearing pair: the construct id is how
    tests/test_subscriber_cadence_promise_3564.py locates the live `schedule=`
    literal in cdk/stacks/email_stack.py and proves this mirror has not drifted.
    `blurb` is the reader-facing clause this sender contributes to the promise.
    """

    function_name: str
    construct_id: str
    cron: str
    blurb: str
    conditional: bool


# The three senders `qa_check_subscriber_promise.SUBSCRIBER_FACING_SENDERS` names
# (partner-weekly-email is deliberately excluded there and here — one private
# address, a different privacy posture, never part of the /subscribe/ promise).
# Ordered as a subscriber meets them in a week, Sunday first.
SUBSCRIBER_SENDERS = (
    SubscriberSender(
        function_name="weekly-signal",
        construct_id="WeeklySignal",
        cron="cron(30 16 ? * SUN *)",
        blurb="the Weekly Signal every {weekday}",
        conditional=False,
    ),
    SubscriberSender(
        function_name="chronicle-email-sender",
        construct_id="ChronicleEmailSender",
        cron="cron(10 15 ? * WED *)",
        blurb="the Chronicle installment on {weekday} (or {fallback_weekday}, when an unapproved draft auto-publishes)",
        conditional=True,
    ),
    SubscriberSender(
        function_name="between-chronicle",
        construct_id="BetweenChronicle",
        cron="cron(0 17 ? * SUN *)",
        blurb="and an occasional between-chronicle note on {weekday} when there is something new",
        conditional=True,
    ),
)

# The chronicle publish path, mirrored from the same stack. These three facts
# together decide the weekday a subscriber ACTUALLY receives an unapproved
# installment on — the artifact the 35-day CloudWatch record shows.
CHRONICLE_DRAFT_CONSTRUCT = "WednesdayChronicle"
CHRONICLE_DRAFT_CRON = "cron(0 15 ? * WED *)"
CHRONICLE_APPROVE_CONSTRUCT = "ChronicleApprove"
CHRONICLE_APPROVE_SWEEP_CRON = "cron(0 18 * * ? *)"
CHRONICLE_AUTOPUBLISH_HOURS = 48


# ── cron parsing ──────────────────────────────────────────────────────────────


def _cron_fields(cron: str) -> list:
    """The 6 EventBridge fields of `cron(min hour dom month dow year)`."""
    inner = cron.strip()
    if not (inner.startswith("cron(") and inner.endswith(")")):
        raise ValueError(f"not an EventBridge cron expression: {cron!r}")
    fields = inner[len("cron(") : -1].split()
    if len(fields) != 6:
        raise ValueError(f"expected 6 cron fields, got {len(fields)}: {cron!r}")
    return fields


def cron_weekday(cron: str) -> Optional[int]:
    """Python `weekday()` index of a single-day cron, or None for a daily one."""
    dow = _cron_fields(cron)[4].upper()
    if dow in ("*", "?"):
        return None
    if dow not in _DOW_TOKENS:
        raise ValueError(f"unsupported day-of-week field {dow!r} in {cron!r} — extend _DOW_TOKENS deliberately")
    return _DOW_TOKENS[dow]


def cron_hour(cron: str) -> int:
    return int(_cron_fields(cron)[1])


def cron_minute(cron: str) -> int:
    return int(_cron_fields(cron)[0])


def required_weekday(cron: str) -> int:
    """`cron_weekday` for a cron that MUST name a day. A subscriber-facing sender
    that quietly became daily would otherwise render a promise with a hole in it."""
    day = cron_weekday(cron)
    if day is None:
        raise ValueError(f"{cron!r} names no day-of-week, but a weekly promise is rendered from it")
    return day


def weekday_name(idx: int) -> str:
    return _WEEKDAY_NAMES[idx]


# ── derived cadence ───────────────────────────────────────────────────────────


def sender(function_name: str) -> SubscriberSender:
    for s in SUBSCRIBER_SENDERS:
        if s.function_name == function_name:
            return s
    raise KeyError(function_name)


def max_weekly_emails() -> int:
    """The most a subscriber can receive in one week — one per subscriber-facing
    sender. Conditional senders make the typical week smaller, never larger."""
    return len(SUBSCRIBER_SENDERS)


def weekly_count_word() -> str:
    """The spelled-out `max_weekly_emails()` — the word every surface prints, so a
    fourth sender rewrites the copy instead of leaving a stale "three" behind."""
    return _COUNT_WORDS[max_weekly_emails()]


def signal_weekday() -> int:
    """The weekday of the one UNCONDITIONAL weekly send — what "your first
    email" and "see you <day>" must both name."""
    return required_weekday(sender("weekly-signal").cron)


def chronicle_weekday() -> int:
    return required_weekday(sender("chronicle-email-sender").cron)


def chronicle_autopublish_dt(draft_dt: datetime) -> datetime:
    """When an UNAPPROVED draft actually reaches subscribers.

    Derived, not asserted: the draft becomes sweep-eligible
    CHRONICLE_AUTOPUBLISH_HOURS after it is written, and the daily
    `chronicle-approve` sweep publishes it (and invokes the sender inline) at the
    first sweep hour at or after that. Naive/aware agnostic — both crons are UTC.
    """
    eligible = draft_dt + timedelta(hours=CHRONICLE_AUTOPUBLISH_HOURS)
    sweep_hour = cron_hour(CHRONICLE_APPROVE_SWEEP_CRON)
    sweep = eligible.replace(hour=sweep_hour, minute=cron_minute(CHRONICLE_APPROVE_SWEEP_CRON), second=0, microsecond=0)
    if sweep < eligible:
        sweep += timedelta(days=1)
    return sweep


def chronicle_autopublish_weekday() -> int:
    """The weekday the auto-publish path delivers on (Friday, today) — computed
    from the draft cron + the 48h window + the sweep cron, so it moves with any
    of the three."""
    draft_weekday = required_weekday(CHRONICLE_DRAFT_CRON)
    # Any concrete week works — the answer is a weekday offset, not a date.
    anchor = datetime(2026, 1, 5)  # a Monday
    draft_dt = (anchor + timedelta(days=draft_weekday)).replace(
        hour=cron_hour(CHRONICLE_DRAFT_CRON), minute=cron_minute(CHRONICLE_DRAFT_CRON)
    )
    return chronicle_autopublish_dt(draft_dt).weekday()


def delivery_weekdays() -> set:
    """Every weekday a subscriber can hear from the platform on."""
    days = {required_weekday(s.cron) for s in SUBSCRIBER_SENDERS}
    days.add(chronicle_autopublish_weekday())
    return days


def promise_sentence() -> str:
    """THE cadence promise. Every subscriber-facing surface renders this exact
    string — the site page, the confirmation email, the welcome email and the
    post-subscribe JS confirmations.

    Deliberately free of apostrophes and quotes so the identical bytes can sit in
    HTML, in a plaintext email and in a JS string literal without entity or
    escaping games (a promise that has to be re-typed per surface is a promise
    that drifts per surface — that is the #3564 defect).
    """
    clauses = []
    for s in SUBSCRIBER_SENDERS:
        clauses.append(
            s.blurb.format(
                weekday=weekday_name(required_weekday(s.cron)),
                fallback_weekday=weekday_name(chronicle_autopublish_weekday()),
            )
        )
    return f"At most {weekly_count_word()} emails a week: " + ", ".join(clauses) + "."


def confirmation_cadence_phrase() -> str:
    """The short form for a subject line — named after the one unconditional
    send, never after a conditional one."""
    return f"every {weekday_name(signal_weekday())}"


def days_until_next(weekday: int, today: date) -> int:
    """Days from `today` until the next occurrence of `weekday`. Today itself
    counts as 7 (the send for today has its own schedule; the bridge email is
    about the NEXT one)."""
    days = (weekday - today.weekday()) % 7
    return days if days > 0 else 7


# ── one week numbering ────────────────────────────────────────────────────────


def genesis_week_number(day: date) -> int:
    """Genesis-anchored week number. Week 1 is the week containing
    EXPERIMENT_START_DATE; anything earlier is <= 0 (the prologue).

    The ONE week numbering the subscriber-facing senders share. Before #3564 the
    weekly signal titled itself off `datetime.strftime("%W")` — the ISO-ish
    CALENDAR week — so a subscriber received "Week 34" from one sender and
    "Week 2" from another about the same seven days. A calendar week number is
    a fact about the Gregorian year, not about this experiment.
    """
    genesis = date.fromisoformat(EXPERIMENT_START_DATE)
    g_monday = genesis - timedelta(days=genesis.weekday())
    d_monday = day - timedelta(days=day.weekday())
    return (d_monday - g_monday).days // 7 + 1


def genesis_week_label(day: date) -> str:
    """'Week N' post-genesis, 'Prologue' before it — the same convention the
    chronicle manifest's `label` field carries (chronicle_render.py)."""
    n = genesis_week_number(day)
    return f"Week {n}" if n >= 1 else "Prologue"
