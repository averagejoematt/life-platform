"""qa_check_subscriber_promise.py — the subscriber weekly-send promise <->
kill-switch regression guard (#1951, epic #1890 growth-1 finding).

Root cause this guards against: /subscribe/ and the confirmation email
promise "The Measured Life every Wednesday" unconditionally, but delivery to
confirmed subscribers is gated behind EXTERNAL_EMAILS_ENABLED, a Lambda
env-var kill switch. It was pinned "false" on the three subscriber-facing
weekly senders (chronicle-email-sender, weekly-signal, between-chronicle)
from 2026-04-23 (commit 0e7abd03, privacy mode) and never lifted when the
site went public — nothing coupled the live page promise to the actual send
state, so a confirmed subscriber could opt in and receive nothing, ever, with
every dashboard green. Reproduced live 2026-08-02
(docs/reviews/FULLREVIEW_2026-08-02_DELTA.md, growth-1).

Owner decision 2026-08-02 (issue #1951 comment): LIFT the switch rather than
disclose a pause — the promise becomes true, not smaller. This check is the
DURABLE half that survives either direction: it is a regression guard, not a
one-time fix. If a sender is ever re-pinned off (deliberately or by drift)
while /subscribe/ keeps soliciting AND confirmed subscribers already exist,
this fires loud — the exact "pause that never lifts" class ADR-147/#1927
named for budget pauses, one layer out.

Reads the LIVE Lambda control plane (list_functions' Environment.Variables),
not the committed CDK source — this must catch drift between what's deployed
and what's merely committed, not just a source-level promise. Uses the
qa-smoke role's existing `lambda:ListFunctions` grant (#1665's
check_lambda_secrets already depends on it) — no new IAM needed.

`assess_subscriber_promise_truth` is the pure assessor (no AWS/HTTP calls)
tests exercise directly; `check_subscriber_promise_truth` is the
live-fetching/live-introspecting wrapper qa_smoke_lambda wires into the
nightly run. Own module (the module-size ceiling split idiom,
#1665/#1944/#1972/#1993).
"""

import json
import os
import re
import urllib.error
import urllib.request

import boto3
from common import subscriber_cadence  # #3564 — the derived promise, rendered from the senders' crons

from operational.qa_check import CONTENT_TRUTH, Check
from operational.qa_check_reader_truth import SITE_BASE_URL

REGION = os.environ.get("AWS_REGION", "us-west-2")

# The subscriber-facing weekly senders named in the owner decision (#1951) —
# deliberately NOT partner-weekly-email, which sends to one private address
# and is a separate privacy-mode posture, never part of the /subscribe/
# promise to readers.
SUBSCRIBER_FACING_SENDERS = ["chronicle-email-sender", "weekly-signal", "between-chronicle"]


def assess_subscriber_promise_truth(site_up: bool, confirmed_count: int, sender_flags: dict) -> tuple:
    """Pure: (ok, message). FAILS exactly the acceptance-criterion shape —
    /subscribe/ live-soliciting AND confirmed subscribers > 0 AND any
    subscriber-facing weekly sender not enabled. A missing/unreadable sender
    flag counts as not-enabled too — from a waiting subscriber's seat, an
    unreadable switch and a paused one are the same defect."""
    if not site_up:
        return True, "/subscribe/ is not live-soliciting (non-200) — no promise is being made, nothing to reconcile"
    if confirmed_count <= 0:
        return True, "0 confirmed subscribers — no reader is owed a send yet (a promise/switch mismatch would be latent, not live)"
    not_enabled = {name: flag for name, flag in sender_flags.items() if str(flag).lower() != "true"}
    if not_enabled:
        return False, (
            f"/subscribe/ is live-soliciting and {confirmed_count} confirmed subscriber(s) exist, but "
            f"{len(not_enabled)}/{len(SUBSCRIBER_FACING_SENDERS)} subscriber-facing weekly sender(s) are NOT "
            f"enabled: {not_enabled} — the live promise and the send infrastructure disagree (#1951 growth-1 class)"
        )
    return True, (
        f"{confirmed_count} confirmed subscriber(s), /subscribe/ live-soliciting, all "
        f"{len(SUBSCRIBER_FACING_SENDERS)} subscriber-facing weekly senders enabled — promise and infra agree"
    )


def _fetch_json(path, timeout=15):
    req = urllib.request.Request(SITE_BASE_URL + path, headers={"User-Agent": "life-platform-qa-smoke"})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 — fixed trusted host
        return json.loads(r.read().decode("utf-8", "replace"))


def _site_up(path="/subscribe/", timeout=15):
    req = urllib.request.Request(SITE_BASE_URL + path, headers={"User-Agent": "life-platform-qa-smoke"}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 — fixed trusted host
            return r.status == 200
    except urllib.error.HTTPError:
        return False  # a non-200 /subscribe/ is a different check's problem; here it just means "not soliciting"


def _live_sender_flags():
    """Live EXTERNAL_EMAILS_ENABLED value per subscriber-facing sender, read
    from the Lambda control plane via list_functions (same API
    check_lambda_secrets already calls — no new IAM grant). A sender not
    found in the account (not yet deployed) reports "unreadable (not
    found)"; assess_ treats anything != "true" as not-enabled, so a missing
    Lambda fails closed rather than silently passing."""
    lm = boto3.client("lambda", region_name=REGION)
    flags = {name: "unreadable (not found)" for name in SUBSCRIBER_FACING_SENDERS}
    remaining = set(SUBSCRIBER_FACING_SENDERS)
    paginator = lm.get_paginator("list_functions")
    for page in paginator.paginate():
        for fn in page["Functions"]:
            name = fn.get("FunctionName")
            if name in remaining:
                flags[name] = fn.get("Environment", {}).get("Variables", {}).get("EXTERNAL_EMAILS_ENABLED", "unreadable (no env var)")
                remaining.discard(name)
        if not remaining:
            break
    return flags


def check_subscriber_promise_truth():
    """CHECK — #1951 growth-1 regression guard. Fail-soft on
    fetch/introspection errors (a transient blip must never red the
    nightly); a real promise/switch mismatch is an ALARMED content-truth
    FAIL (novel, never chronic — a live promise the infra can't keep is
    exactly the regression this guard exists to catch)."""
    check = Check("subscriber_promise:kill_switch_agreement", "Reader Truth", CONTENT_TRUTH)
    try:
        site_up = _site_up()
    except Exception as e:
        return [check.warn(f"/subscribe/ fetch failed (fail-soft): {str(e)[:120]}")]
    try:
        count_data = _fetch_json("/api/sub_count")
        confirmed_count = int(count_data.get("count", 0))
    except Exception as e:
        return [check.warn(f"/api/sub_count fetch failed (fail-soft): {str(e)[:120]}")]
    try:
        sender_flags = _live_sender_flags()
    except Exception as e:
        return [check.warn(f"sender Lambda introspection failed (fail-soft): {str(e)[:120]}")]

    ok, msg = assess_subscriber_promise_truth(site_up, confirmed_count, sender_flags)
    return [check.ok(msg) if ok else check.fail(msg)]


# ─────────────────────────────────────────────────────────────────────────────
# #3564 — the CADENCE half. #1951 above checks the kill SWITCH ("is anything
# sending at all?"); it is structurally blind to the promise being wrong about
# WHAT sends. It was green for the whole month the live page promised "One email
# a week, then quiet until next Wednesday" while three senders delivered up to
# three, none of them on a Wednesday.
# ─────────────────────────────────────────────────────────────────────────────

# Any reader-facing weekly-volume claim, in words or digits. Phrase-anchored on the
# only part that cannot be paraphrased away ("emails a week"), and the ASSERTION is
# structural: whatever number the page states must equal the number the sender
# registry produces.
_COUNT_CLAIM = re.compile(r"\b(one|two|three|four|five|six|seven|\d+)\s+emails?\s+a\s+week\b", re.IGNORECASE)


def assess_promise_cadence_agreement(page_text: str, promise: str, count_word: str) -> tuple:
    """Pure: (ok, message). The live /subscribe/ page must carry the promise
    sentence RENDERED from the senders' crons, and must state no other weekly
    volume anywhere on the page."""
    if not page_text:
        return True, "/subscribe/ served no body — nothing is being promised to reconcile"
    stale = sorted({m.group(1).lower() for m in _COUNT_CLAIM.finditer(page_text) if m.group(1).lower() != count_word})
    if promise not in page_text:
        return False, (
            "/subscribe/ does not carry the cadence promise derived from the senders' own schedules "
            f"(expected: {promise!r}"
            + (f"; the page states {stale} emails a week instead" if stale else "")
            + ") — the live page and the send infrastructure disagree about WHAT a subscriber receives (#3564)"
        )
    if stale:
        return False, (
            f"/subscribe/ carries the derived promise but ALSO claims {stale} emails a week elsewhere on the page "
            f"— two contradicting volume claims, one of them stale (#3564)"
        )
    return (
        True,
        f"/subscribe/ states exactly the cadence the {len(subscriber_cadence.SUBSCRIBER_SENDERS)} subscriber-facing senders declare",
    )


def _fetch_text(path="/subscribe/", timeout=15):
    req = urllib.request.Request(SITE_BASE_URL + path, headers={"User-Agent": "life-platform-qa-smoke"})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 — fixed trusted host
        return r.read().decode("utf-8", "replace")


def check_subscriber_promise_cadence():
    """CHECK — #3564. The promise on the live page must equal the promise the
    schedules make. Fail-soft on fetch errors (a transient blip must never red the
    nightly); a real disagreement is an ALARMED content-truth FAIL."""
    check = Check("subscriber_promise:cadence_agreement", "Reader Truth", CONTENT_TRUTH)
    try:
        page_text = _fetch_text()
    except Exception as e:
        return [check.warn(f"/subscribe/ fetch failed (fail-soft): {str(e)[:120]}")]
    ok, msg = assess_promise_cadence_agreement(
        page_text,
        subscriber_cadence.promise_sentence(),
        subscriber_cadence.weekly_count_word(),
    )
    return [check.ok(msg) if ok else check.fail(msg)]
