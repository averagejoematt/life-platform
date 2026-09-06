"""tests/test_subscriber_cadence_promise_3564.py — #3564 (epic #3498): the
/subscribe/ promise and the senders' real schedules could not disagree again.

The defect: `/subscribe/` said "One email a week, then quiet until next
Wednesday" and the confirmation email said "every Wednesday", while the three
subscriber-facing senders #1951 enabled delivered up to THREE emails a week —
weekly-signal Sunday 16:30 UTC, between-chronicle Sunday 17:00 UTC, and the
chronicle Wednesday 15:10 UTC that, unapproved, actually lands FRIDAY 18:00 UTC
via the 48h auto-publish sweep. Zero tests mentioned either promise literal, and
`qa_check_subscriber_promise` (#1951) checks the kill SWITCH, so nothing on the
platform could see a promise that named the wrong count and the wrong day.

The guards here, in the order they matter:

  MIRROR      every cron this module derives from equals the live `schedule=`
              literal under its construct in cdk/stacks/email_stack.py, and
              CHRONICLE_AUTOPUBLISH_HOURS equals the deployed env var. A mirror
              that can go stale silently is the whole #3564 class one level down.
  DERIVATION  the Friday a subscriber actually receives an unapproved installment
              on is COMPUTED (draft cron + window + sweep cron), never asserted.
  PIN         every subscriber-facing surface — the page, the three site JS
              strings, the confirmation email, the welcome email, the onboarding
              email — carries the one rendered promise sentence, byte for byte.
  NEGATIVE    move a cron in the registry and the pin MUST red. A pin that passes
              against a mutated registry is pinning nothing (#1189).
  NO-SECOND-CLAIM  no surface states a weekly volume other than the derived one.
"""

import os
import re
import sys
from datetime import date, datetime

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

from common import subscriber_cadence as sc  # noqa: E402

_EMAIL_STACK = os.path.join(_REPO, "cdk", "stacks", "email_stack.py")


def _stack_src():
    with open(_EMAIL_STACK, encoding="utf-8") as f:
        return f.read()


def _cdk_schedule(construct_id: str) -> str:
    """The `schedule=` cron literal on a construct, read from the CDK source —
    the same idiom tests/test_onboarding_schedule_docstring.py (#1257) uses."""
    src = _stack_src()
    idx = src.index(f'"{construct_id}"')
    m = re.search(r'schedule="(cron\([^"]+\))"', src[idx:])
    assert m, f"no schedule= cron found after the {construct_id} construct in email_stack.py"
    return m.group(1)


# ── MIRROR: the registry is the stack ─────────────────────────────────────────


@pytest.mark.parametrize("sender", sc.SUBSCRIBER_SENDERS, ids=[s.function_name for s in sc.SUBSCRIBER_SENDERS])
def test_each_sender_cron_matches_the_live_cdk_literal(sender):
    live = _cdk_schedule(sender.construct_id)
    assert sender.cron == live, (
        f"common/subscriber_cadence.py mirrors {sender.function_name} as {sender.cron}, but "
        f"cdk/stacks/email_stack.py schedules it {live} — the promise is rendered from this "
        "mirror, so a stale entry publishes a false cadence to every subscriber."
    )


def test_chronicle_draft_and_sweep_crons_match_the_live_cdk_literals():
    assert sc.CHRONICLE_DRAFT_CRON == _cdk_schedule(sc.CHRONICLE_DRAFT_CONSTRUCT)
    assert sc.CHRONICLE_APPROVE_SWEEP_CRON == _cdk_schedule(sc.CHRONICLE_APPROVE_CONSTRUCT)


def test_autopublish_window_matches_the_live_cdk_env_var():
    m = re.search(r'"CHRONICLE_AUTOPUBLISH_HOURS":\s*"(\d+)"', _stack_src())
    assert m, "CHRONICLE_AUTOPUBLISH_HOURS is no longer set in email_stack.py"
    assert sc.CHRONICLE_AUTOPUBLISH_HOURS == int(m.group(1))


def test_the_registry_covers_exactly_the_qa_checks_subscriber_facing_senders():
    """One list of subscriber-facing senders, not two. #1951's kill-switch check and
    this module's promise renderer must never disagree about who mails a reader."""
    from operational.qa_check_subscriber_promise import SUBSCRIBER_FACING_SENDERS

    assert sorted(s.function_name for s in sc.SUBSCRIBER_SENDERS) == sorted(SUBSCRIBER_FACING_SENDERS)


# ── DERIVATION: the Friday is computed, not claimed ───────────────────────────


def test_unapproved_draft_reaches_subscribers_on_friday_derived_not_asserted():
    """The 35-day CloudWatch record shows chronicle-email-sender delivering Friday
    18:00 UTC, not Wednesday. That is not a schedule defect — it is the 48h sweep
    doing exactly what it says. Derived here from the three facts that cause it."""
    draft = datetime(2026, 8, 12, 15, 0)  # a Wednesday, the draft cron's hour
    assert sc.chronicle_autopublish_dt(draft) == datetime(2026, 8, 14, 18, 0)  # Friday 18:00 UTC
    assert sc.weekday_name(sc.chronicle_autopublish_weekday()) == "Friday"


def test_autopublish_weekday_moves_with_the_window(monkeypatch):
    """Widen the review window by a day and the delivery weekday moves — proof the
    Friday is a computation over CHRONICLE_AUTOPUBLISH_HOURS, not a literal."""
    monkeypatch.setattr(sc, "CHRONICLE_AUTOPUBLISH_HOURS", 72)
    assert sc.weekday_name(sc.chronicle_autopublish_weekday()) == "Saturday"


def test_delivery_weekdays_are_the_days_the_senders_actually_fire():
    assert sc.delivery_weekdays() == {2, 4, 6}  # Wednesday, Friday, Sunday
    assert 2 in sc.delivery_weekdays()  # the chronicle's own cron day is still real


def test_promise_names_every_delivery_weekday_and_the_derived_count():
    promise = sc.promise_sentence()
    assert promise.startswith(f"At most {sc.weekly_count_word()} emails a week:")
    for wd in sc.delivery_weekdays():
        assert sc.weekday_name(wd) in promise, f"{sc.weekday_name(wd)} is a delivery day the promise does not name"
    # and it never re-makes the promise that failed: a bare weekly claim on a day
    # nothing ships on.
    assert "quiet until next Wednesday" not in promise


def test_promise_carries_no_quotes_or_apostrophes():
    """It ships byte-identical into HTML, a JS string literal and a plaintext email —
    a quote or apostrophe would force a per-surface re-typing, which is the defect."""
    assert not set(sc.promise_sentence()) & set("\"'`")


# ── PIN: every subscriber-facing surface carries the derived sentence ─────────

SITE_SURFACES = (
    "site/subscribe/index.html",
    "site/assets/js/subscribe_page.js",
    "site/assets/js/subscribe_confirm.js",
    "site/assets/js/engagement_ladder.js",
)


def _rendered_email_surfaces():
    """The three subscriber emails, rendered — not grepped. What a subscriber READS."""
    os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
    os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
    from web import subscriber_onboarding_lambda as onboarding
    from web.email_subscriber_lambda import _confirmation_email_content, _welcome_email_content

    surfaces = {
        "confirmation email": _confirmation_email_content("https://averagejoematt.com/api/subscribe?action=confirm&token=x")[1],
        "welcome email": _welcome_email_content("reader@example.com")[1],
    }
    # Stub the S3-backed card loader for the render, then PUT IT BACK — a module-level
    # rebind that outlives the call leaks into every later test in the session (it did,
    # and broke the sibling #3565 suite when the two ran together).
    original = onboarding._get_published_posts
    onboarding._get_published_posts = lambda max_posts=3: list(onboarding.FALLBACK_PAGES)
    try:
        surfaces["onboarding email"] = onboarding._build_onboarding_email("reader@example.com")[1]
    finally:
        onboarding._get_published_posts = original
    return surfaces


def _surfaces_missing(promise: str) -> list:
    missing = []
    for rel in SITE_SURFACES:
        with open(os.path.join(_REPO, rel), encoding="utf-8") as f:
            if promise not in f.read():
                missing.append(rel)
    for name, body in _rendered_email_surfaces().items():
        if promise not in body:
            missing.append(name)
    return missing


def test_every_subscriber_surface_carries_the_derived_promise():
    assert _surfaces_missing(sc.promise_sentence()) == []


def test_the_pin_reds_when_a_sender_cron_moves(monkeypatch):
    """NEGATIVE CONTROL. Move the Weekly Signal to Monday in the registry: the
    rendered promise changes, and every surface must now be reported stale. A pin
    that stays green against a mutated registry is pinning nothing (#1189)."""
    moved = tuple(
        (
            sc.SubscriberSender(s.function_name, s.construct_id, "cron(30 16 ? * MON *)", s.blurb, s.conditional)
            if s.function_name == "weekly-signal"
            else s
        )
        for s in sc.SUBSCRIBER_SENDERS
    )
    monkeypatch.setattr(sc, "SUBSCRIBER_SENDERS", moved)
    mutated = sc.promise_sentence()
    assert "every Monday" in mutated
    # The four STATIC surfaces are now stale — the pin reds, loudly, naming each one.
    assert sorted(_surfaces_missing(mutated)) == sorted(SITE_SURFACES)
    # …and the three EMAILS are not in that list, because they render the sentence at
    # send time rather than carrying a copy of it. That asymmetry is the design: the
    # emails cannot drift, the static files can, so the static files are what is pinned.
    for name, body in _rendered_email_surfaces().items():
        assert mutated in body, f"{name} did not follow the registry — it is carrying a hardcoded cadence"


def test_the_pin_reds_when_a_fourth_sender_is_added(monkeypatch):
    """NEGATIVE CONTROL 2 — the count, not just the day. Adding a subscriber-facing
    sender must invalidate every "at most three" the platform has published."""
    extra = sc.SUBSCRIBER_SENDERS + (
        sc.SubscriberSender("saturday-extra", "SaturdayExtra", "cron(0 17 ? * SAT *)", "and a note on {weekday}", True),
    )
    monkeypatch.setattr(sc, "SUBSCRIBER_SENDERS", extra)
    assert sc.promise_sentence().startswith("At most four emails a week:")
    assert _surfaces_missing(sc.promise_sentence())


# ── NO SECOND CLAIM: nothing states a different weekly volume ────────────────

_COUNT_CLAIM = re.compile(r"\b(one|two|three|four|five|six|seven|\d+)\s+emails?\s+a\s+week\b", re.IGNORECASE)


def test_no_subscriber_surface_states_a_second_weekly_volume():
    """The page's meta description said "One email a week" while its own body row
    said the same thing — two copies of one stale number. Any volume claim on any
    of these surfaces must equal the derived one."""
    truth = sc.weekly_count_word()
    bad = []
    for rel in SITE_SURFACES:
        with open(os.path.join(_REPO, rel), encoding="utf-8") as f:
            for lineno, line in enumerate(f, 1):
                for m in _COUNT_CLAIM.finditer(line):
                    if m.group(1).lower() != truth:
                        bad.append(f"{rel}:{lineno}: claims {m.group(0)!r}, derived truth is {truth}")
    for name, body in _rendered_email_surfaces().items():
        for m in _COUNT_CLAIM.finditer(body):
            if m.group(1).lower() != truth:
                bad.append(f"{name}: claims {m.group(0)!r}, derived truth is {truth}")
    assert bad == [], "\n".join(bad)


def test_the_count_claim_scan_is_not_vacuous():
    assert _COUNT_CLAIM.search("Nothing else. One email a week, then quiet until next Wednesday.")
    assert _COUNT_CLAIM.search("At most three emails a week: the Weekly Signal every Sunday.")
    assert not _COUNT_CLAIM.search("A new dispatch lands every week.")


def test_no_subscriber_surface_still_promises_a_wednesday_only_cadence():
    """The exact literals #3564 reproduced. They may not come back by hand-edit."""
    dead = ("quiet until next Wednesday", "every Wednesday, the actual numbers", "lands every Wednesday")
    for rel in SITE_SURFACES + (
        "lambdas/web/email_subscriber_lambda.py",
        "lambdas/web/subscriber_onboarding_lambda.py",
    ):
        with open(os.path.join(_REPO, rel), encoding="utf-8") as f:
            body = f.read()
        for phrase in dead:
            assert phrase not in body, f"{rel} still carries the #3564 promise literal {phrase!r}"


# ── the qa_smoke live check ──────────────────────────────────────────────────


def test_cadence_check_passes_on_a_page_carrying_the_derived_promise():
    from operational import qa_check_subscriber_promise as qsp

    page = f"<html><p>Nothing else. {sc.promise_sentence()}</p></html>"
    ok, msg = qsp.assess_promise_cadence_agreement(page, sc.promise_sentence(), sc.weekly_count_word())
    assert ok, msg


def test_cadence_check_fails_on_the_live_pre_fix_page():
    """Non-vacuous: the assessor must FAIL on the copy that was actually live."""
    from operational import qa_check_subscriber_promise as qsp

    page = "<html><p>Nothing else. No ads. One email a week, then quiet until next Wednesday.</p></html>"
    ok, msg = qsp.assess_promise_cadence_agreement(page, sc.promise_sentence(), sc.weekly_count_word())
    assert not ok
    assert "one" in msg and "#3564" in msg


def test_cadence_check_fails_when_a_stale_second_claim_survives_beside_the_new_one():
    from operational import qa_check_subscriber_promise as qsp

    page = f"<html><meta content='One email a week'><p>{sc.promise_sentence()}</p></html>"
    ok, msg = qsp.assess_promise_cadence_agreement(page, sc.promise_sentence(), sc.weekly_count_word())
    assert not ok
    assert "contradicting" in msg


def test_cadence_check_is_wired_into_the_nightly_sweep():
    with open(os.path.join(_REPO, "lambdas", "operational", "qa_smoke_lambda.py"), encoding="utf-8") as f:
        src = f.read()
    assert "check_subscriber_promise_cadence" in src
    assert '("subscriber_promise_cadence", check_subscriber_promise_cadence)' in src


# ── ONE week numbering ───────────────────────────────────────────────────────


def test_genesis_week_number_is_anchored_on_the_experiment_not_the_calendar():
    from common.constants import EXPERIMENT_START_DATE

    genesis = date.fromisoformat(EXPERIMENT_START_DATE)
    from datetime import timedelta

    assert sc.genesis_week_number(genesis) == 1
    assert sc.genesis_week_label(genesis) == "Week 1"
    # Week 1 spans the genesis week; the following Monday starts week 2.
    monday_after = genesis + timedelta(days=(7 - genesis.weekday()))
    assert sc.genesis_week_number(monday_after) == 2


def test_pre_genesis_reads_prologue_never_an_invented_week():
    from datetime import timedelta

    from common.constants import EXPERIMENT_START_DATE

    before = date.fromisoformat(EXPERIMENT_START_DATE) - timedelta(days=14)
    assert sc.genesis_week_number(before) <= 0
    assert sc.genesis_week_label(before) == "Prologue"


def test_weekly_signal_titles_itself_with_the_shared_week_number_not_strftime_W():
    """#3564(c): "Week 34" (the Gregorian calendar week) and "Week 2" (the
    chronicle's) described the same seven days to the same subscriber."""
    with open(os.path.join(_REPO, "lambdas", "compute", "weekly_signal_lambda.py"), encoding="utf-8") as f:
        src = f.read()
    assert 'strftime("%W")' not in src, "weekly-signal is back on the calendar week number"
    assert "genesis_week_label" in src and "genesis_week_number" in src


def test_onboarding_bridge_window_is_measured_to_the_signal_day():
    """The bridge email's own gate counted down to Wednesday — a day nothing ships
    on. It now counts to the weekday weekly-signal's cron declares."""
    with open(os.path.join(_REPO, "lambdas", "web", "subscriber_onboarding_lambda.py"), encoding="utf-8") as f:
        src = f.read()
    assert "def _days_until_wednesday" not in src
    assert "days_until_next(signal_weekday()" in src
    # Sunday send: from a Monday the next Signal is 6 days out, from a Friday 2.
    assert sc.days_until_next(sc.signal_weekday(), date(2026, 9, 7)) == 6  # Monday
    assert sc.days_until_next(sc.signal_weekday(), date(2026, 9, 11)) == 2  # Friday
    assert sc.days_until_next(sc.signal_weekday(), date(2026, 9, 13)) == 7  # the Sunday itself
