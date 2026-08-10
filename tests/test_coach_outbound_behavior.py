"""tests/test_coach_outbound_behavior.py — bounded unsolicited outbound (Act 1b).

The feature under test is a coach texting FIRST, so almost every test here is a
test that NOTHING was sent. That asymmetry is the point: a reply is a wrong answer
to a question he asked, an unsolicited text is the platform deciding his phone
should buzz, and the second one has to be earned.

  O1  the marker: parsed as a whole line, stripped from every bubble that is
      actually sent, resolved against the REGISTRY (never trusted as typed)
  O2  the deterministic gate: seven independent ways a handoff stays dark, each
      one proved to send nothing — parameterized, because a guard written for one
      condition and never exercised on the others is a guard that guards nothing
  O3  the happy path: exactly ONE message, through the REFERRED bot's token, into
      the REFERRED coach's own partition, stamped telegram_referral
  O4  the morning check-in: dark until the bot exists, weekday-only, and silent
      again after two ignored check-ins
  O5  the shared ledger: cap 2/day across both features, referral sub-cap 1/day,
      and every failure mode (cap, race, storage error) reads as "don't send"
  O6  provenance ranking (#2490): six features, two slots, a reserved second one
  O7  the event ledger: one real-world fact, one text, ever
  O8  detection: every threshold is a statement about MATTHEW, not a constant
  O9  the event sweep: exactly one outbound from a seeded trigger, no repeat-fire
  O10 liveness: the sweep reports itself on EVERY outcome, so a dead cron reads as
      silence rather than as a quiet week — the failure an error alarm cannot see

Wall-clock discipline: every moment is injected. Nothing here reads the real
clock, so none of it becomes a time bomb on a Saturday or after 9pm.
"""

import os
import sys
from datetime import datetime

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

from coach import coach_chat, coach_outbound  # noqa: E402
from common.pacific_time import PACIFIC  # noqa: E402

# Fixture moments. 2026-08-12 is a Wednesday; 2026-08-15 a Saturday.
WEDNESDAY_10AM = datetime(2026, 8, 12, 10, 15, tzinfo=PACIFIC)
WEDNESDAY_10PM = datetime(2026, 8, 12, 22, 5, tzinfo=PACIFIC)
SATURDAY_10AM = datetime(2026, 8, 15, 10, 15, tzinfo=PACIFIC)


class _CCF(Exception):
    """Stand-in for botocore's ConditionalCheckFailedException (name-matched)."""

    def __init__(self):
        super().__init__("The conditional request failed")

    __name__ = "ConditionalCheckFailedException"


_CCF.__name__ = "ConditionalCheckFailedException"


class LedgerTable:
    """A DynamoDB stand-in that actually implements the ADD + condition contract.

    Hand-rolled rather than mocked because the assertion that matters is
    behavioural — "the third claim of the day fails" — and a mock that records
    calls can only prove the call was made. The real atomicity guarantee is
    DynamoDB's; what this pins is that the expression we send expresses the cap
    we think it does.
    """

    def __init__(self):
        self.items = {}
        self.calls = []

    def update_item(self, Key, UpdateExpression, ConditionExpression, ExpressionAttributeNames, ExpressionAttributeValues):
        self.calls.append(
            {
                "Key": Key,
                "UpdateExpression": UpdateExpression,
                "ConditionExpression": ConditionExpression,
                "ExpressionAttributeNames": ExpressionAttributeNames,
                "ExpressionAttributeValues": ExpressionAttributeValues,
            }
        )
        key = (Key["pk"], Key["sk"])
        item = dict(self.items.get(key) or {})
        total = item.get("total", 0)
        refs = item.get("referrals", 0)
        is_referral = ":rcap" in ExpressionAttributeValues
        # The caps are read out of the CONDITION, not assumed: a claim that stops
        # asking for the guard must stop being capped, or this emulation would
        # keep passing over a ledger that no longer guards anything.
        if "#total < :cap" in ConditionExpression and total >= ExpressionAttributeValues[":cap"]:
            raise _CCF()
        if is_referral and "#ref < :rcap" in ConditionExpression and refs >= ExpressionAttributeValues[":rcap"]:
            raise _CCF()
        item["total"] = total + 1
        if is_referral:
            item["referrals"] = refs + 1
        self.items[key] = item
        return {}


class QuietTable:
    """Reads return nothing; writes are recorded. The worker's storage surface."""

    def __init__(self, claim=True):
        self.puts = []
        self.updates = []
        self.claim = claim  # True | "cap" | "boom"

    def query(self, **kwargs):
        return {"Items": []}

    def get_item(self, **kwargs):
        return {}

    def put_item(self, **kwargs):
        self.puts.append(kwargs["Item"])

    def update_item(self, **kwargs):
        self.updates.append(kwargs)
        if self.claim is True:
            return {}
        if self.claim == "cap":
            raise _CCF()
        raise RuntimeError("ddb is having a day")


# ── O1: the marker ────────────────────────────────────────────────────────────


def test_marker_is_parsed_off_its_own_line():
    assert coach_outbound.parse_referral("Sleep first.\n[[refer: pattern_coach]]") == "pattern_coach"


def test_marker_tolerates_spacing_and_case():
    assert coach_outbound.parse_referral("x\n  [[ Refer :  eli_marsh ]]  ") == "eli_marsh"


def test_marker_mid_sentence_is_not_a_marker():
    # A coach explaining the mechanism must not trigger it.
    assert coach_outbound.parse_referral("I could write [[refer: x]] but I won't.") is None


def test_no_marker_is_no_handoff():
    assert coach_outbound.parse_referral("just a normal reply") is None
    assert coach_outbound.parse_referral("") is None
    assert coach_outbound.parse_referral(None) is None


def test_two_markers_take_the_last():
    assert coach_outbound.parse_referral("[[refer: a]]\nmore\n[[refer: pattern_coach]]") == "pattern_coach"


def test_stripping_removes_the_line_and_keeps_the_reply():
    out = coach_outbound.strip_referral_markers(["Sleep first.\n[[refer: pattern_coach]]", "Talk tomorrow."])
    assert out == ["Sleep first.", "Talk tomorrow."]


def test_a_bubble_that_is_only_a_marker_disappears():
    assert coach_outbound.strip_referral_markers(["real text", "[[refer: pattern_coach]]"]) == ["real text"]


def test_a_reply_that_is_only_a_marker_sends_nothing():
    assert coach_outbound.strip_referral_markers(["[[refer: pattern_coach]]"]) == []


def test_resolution_is_registry_backed_not_string_trust():
    from coach.persona_registry import personas

    reg = personas()
    assert coach_outbound.resolve_referral_target("pattern_coach", reg, "sleep_coach") == "pattern_coach"
    # The display name expresses the same intent — accepted, fail-soft.
    assert coach_outbound.resolve_referral_target("Dr. Nora Vale", reg, "sleep_coach") == "pattern_coach"
    # An id the model invented resolves to nothing at all.
    assert coach_outbound.resolve_referral_target("dream_coach", reg, "sleep_coach") is None
    # A coach cannot hand a conversation to itself.
    assert coach_outbound.resolve_referral_target("sleep_coach", reg, "sleep_coach") is None
    assert coach_outbound.resolve_referral_target("Dr. Lisa Park", reg, "sleep_coach") is None


# ── O5 (pure half): quiet hours + the shared ledger ───────────────────────────


@pytest.mark.parametrize("hour", [21, 22, 23, 0, 3, 6])
def test_quiet_hours_cover_the_evening_and_the_night(hour):
    assert coach_outbound.in_quiet_hours(WEDNESDAY_10AM.replace(hour=hour)) is True


@pytest.mark.parametrize("hour", [7, 9, 12, 17, 20])
def test_daytime_is_not_quiet_hours(hour):
    assert coach_outbound.in_quiet_hours(WEDNESDAY_10AM.replace(hour=hour)) is False


def test_an_unknown_moment_is_treated_as_quiet():
    assert coach_outbound.in_quiet_hours(None) is True


def test_ledger_expression_is_well_formed():
    """Every declared name and value must be USED — DynamoDB rejects the request
    outright otherwise, and a ValidationException at 10:15am is a silent feature.
    """
    for referral in (False, True):
        table = LedgerTable()
        coach_outbound.claim_outbound(table, "2026-08-12", referral=referral)
        call = table.calls[-1]
        blob = call["UpdateExpression"] + " " + call["ConditionExpression"]
        for name in call["ExpressionAttributeNames"]:
            assert name in blob, f"unused ExpressionAttributeName {name} (referral={referral})"
        for value in call["ExpressionAttributeValues"]:
            assert value in blob, f"unused ExpressionAttributeValue {value} (referral={referral})"
        assert call["Key"] == {"pk": "COACH#outbound_ledger", "sk": "DAY#2026-08-12"}


def test_the_two_features_share_one_daily_cap():
    table = LedgerTable()
    assert coach_outbound.claim_outbound(table, "2026-08-12") is True  # check-in
    assert coach_outbound.claim_outbound(table, "2026-08-12", referral=True) is True  # referral
    # Third of the day, either kind, is refused: the caps are not per-feature.
    assert coach_outbound.claim_outbound(table, "2026-08-12") is False
    assert coach_outbound.claim_outbound(table, "2026-08-12", referral=True) is False


def test_referrals_have_their_own_sub_cap():
    table = LedgerTable()
    assert coach_outbound.claim_outbound(table, "2026-08-12", referral=True) is True
    # Slot 2 of 2 is still free, but the referral sub-cap is spent.
    assert coach_outbound.claim_outbound(table, "2026-08-12", referral=True) is False
    assert coach_outbound.claim_outbound(table, "2026-08-12") is True


def test_a_new_day_starts_clean():
    table = LedgerTable()
    coach_outbound.claim_outbound(table, "2026-08-12")
    coach_outbound.claim_outbound(table, "2026-08-12")
    assert coach_outbound.claim_outbound(table, "2026-08-12") is False
    assert coach_outbound.claim_outbound(table, "2026-08-13") is True


def test_a_ledger_race_is_a_skip_not_a_crash():
    assert coach_outbound.claim_outbound(QuietTable(claim="cap"), "2026-08-12") is False


def test_a_ledger_storage_error_is_a_skip_not_a_crash():
    # A ledger we cannot write is a count we cannot trust, and the safe reading
    # of "I don't know how many I've sent" is "don't send another".
    assert coach_outbound.claim_outbound(QuietTable(claim="boom"), "2026-08-12") is False


# ── O4 (pure half): the silence rule ─────────────────────────────────────────


def _row(role, provenance=None):
    r = {"role": role, "text": "x"}
    if provenance:
        r["provenance"] = provenance
    return r


CHECKIN = coach_outbound.PROVENANCE_CHECKIN


def test_one_checkin_on_record_is_never_a_silence_signal():
    rows = [_row("coach", CHECKIN)]
    assert coach_outbound.two_consecutive_ignored(rows, CHECKIN) is False


def test_two_ignored_checkins_stop_the_cadence():
    rows = [_row("coach", CHECKIN), _row("coach", CHECKIN)]
    assert coach_outbound.two_consecutive_ignored(rows, CHECKIN) is True


def test_a_reply_after_the_last_checkin_resets_it():
    rows = [_row("coach", CHECKIN), _row("coach", CHECKIN), _row("matthew")]
    assert coach_outbound.two_consecutive_ignored(rows, CHECKIN) is False


def test_a_reply_between_the_two_means_only_one_was_ignored():
    rows = [_row("coach", CHECKIN), _row("matthew"), _row("coach", CHECKIN)]
    assert coach_outbound.two_consecutive_ignored(rows, CHECKIN) is False


def test_ordinary_replies_are_not_checkins():
    rows = [_row("coach", "telegram"), _row("coach", "telegram")]
    assert coach_outbound.two_consecutive_ignored(rows, CHECKIN) is False


# ── the worker harness ────────────────────────────────────────────────────────

REFERRING_REPLY = "Sleep first, then the rest.\n[[refer: pattern_coach]]"

# The telegram secret, as the worker reads it: sleep is Matthew's live chat,
# pattern is Nora Vale's bot (registered, same chat), career exists with NO chat
# on it yet, and eli_marsh's `headcoach` is absent entirely — the dark state
# every chat-tier coach is in before the owner's BotFather run.
STORE = {
    "sleep": {"bot_token": "tok-sleep", "chat_ids": [4242]},
    "pattern": {"bot_token": "tok-pattern", "chat_ids": [4242]},
    "career": {"bot_token": "tok-career", "chat_ids": []},
}


class Harness:
    def __init__(self):
        self.sends = []  # (token, method, text)
        self.turns = []  # the run_turn kwargs, in order
        self.table = None


@pytest.fixture
def wired(monkeypatch):
    """The worker with every AWS edge replaced and the clock injected."""
    from coach import telegram_worker_lambda as worker

    h = Harness()
    h.table = QuietTable()

    replies = [REFERRING_REPLY, "Park mentioned the switch-off. That's mine."]

    def fake_run_turn(**kw):
        h.turns.append(kw)
        text = replies[min(len(h.turns) - 1, len(replies) - 1)]
        return coach_chat.TurnResult(text, "sent", [], 1, bubbles=coach_chat.split_bubbles(text))

    monkeypatch.setattr(worker, "_tg", lambda token, method, payload: h.sends.append((token, method, dict(payload))))
    monkeypatch.setattr(worker, "_secret_entry", lambda key: dict(STORE.get(key) or {}))
    monkeypatch.setattr(worker, "_seen_update", lambda cid, uid: False)
    monkeypatch.setattr(worker, "_chat_rows", lambda cid, limit=40: [])
    monkeypatch.setattr(worker, "_facts", lambda: {})
    monkeypatch.setattr(worker, "_memory_block", lambda cid: "")
    monkeypatch.setattr(worker, "_current_tier", lambda: 0)
    monkeypatch.setattr(worker, "_s3_client", lambda: None)
    monkeypatch.setattr(worker, "_cycle", lambda: 13)
    monkeypatch.setattr(worker, "_table", lambda: h.table)
    monkeypatch.setattr(worker, "_pacific_now", lambda: WEDNESDAY_10AM)
    monkeypatch.setattr(worker.telegram_gateway, "is_stale", lambda ts, now: False)
    monkeypatch.setattr(worker.coach_chat, "run_turn", fake_run_turn)
    monkeypatch.setattr("coach.coach_domain_facts.domain_facts_block", lambda pid, table: "")
    monkeypatch.setattr("time.sleep", lambda s: None)
    return worker, h


def _inbound(worker):
    return worker.lambda_handler({"coach_id": "sleep", "chat_id": 4242, "text": "can't switch off at night"}, None)


def _messages(h, token=None):
    return [p.get("text") for tok, method, p in h.sends if method == "sendMessage" and (token is None or tok == token)]


def _chat_ids(h, token=None):
    return [p.get("chat_id") for tok, method, p in h.sends if method == "sendMessage" and (token is None or tok == token)]


# ── O1/O2: the marker never reaches the phone, on every path ─────────────────


@pytest.mark.parametrize(
    "dark_reason",
    [
        "clean",  # the handoff is granted — the marker is still stripped
        "unknown_persona",
        "self_referral",
        "no_bot_token",
        "chat_not_on_roster",
        "quiet_hours",
        "budget_paused",
        "cap_reached",
    ],
)
def test_the_marker_is_never_sent_to_matthew(wired, monkeypatch, dark_reason):
    """Guard the SET: whatever the gate decides, machine syntax stays internal."""
    worker, h = _apply_dark(wired, monkeypatch, dark_reason)
    _inbound(worker)
    assert h.sends, "the reply itself must always go out"
    for text in _messages(h):
        assert "[[refer" not in text
        assert "refer:" not in text


@pytest.mark.parametrize(
    "dark_reason",
    [
        "unknown_persona",
        "self_referral",
        "no_bot_token",
        "chat_not_on_roster",
        "quiet_hours",
        "budget_paused",
        "cap_reached",
    ],
)
def test_each_gate_condition_independently_sends_nothing(wired, monkeypatch, dark_reason):
    """Seven conditions, seven proofs. Each is exercised on its own so a guard
    cannot ride on a sibling's refusal — the shape that produced three privacy
    screens whose suite passed with the screen deleted."""
    worker, h = _apply_dark(wired, monkeypatch, dark_reason)
    out = _inbound(worker)

    assert out["ok"] is True
    assert "referred_to" not in out
    # Nothing left through the referred coach's bot...
    assert _messages(h, token="tok-pattern") == []
    # ...and no second turn was even generated (the model is never asked).
    assert len(h.turns) == 1
    # ...and nothing was stored under the referred coach.
    assert [p for p in h.table.puts if p.get("pk") == coach_chat.chat_pk("pattern_coach")] == []


def _apply_dark(wired, monkeypatch, reason):
    """Turn ONE gate condition red, leaving the rest passing."""
    worker, h = wired
    if reason == "unknown_persona":
        monkeypatch.setattr(worker.coach_outbound, "parse_referral", lambda t: "dream_coach")
    elif reason == "self_referral":
        monkeypatch.setattr(worker.coach_outbound, "parse_referral", lambda t: "sleep_coach")
    elif reason == "no_bot_token":
        store = {k: v for k, v in STORE.items() if k != "pattern"}
        monkeypatch.setattr(worker, "_secret_entry", lambda key: dict(store.get(key) or {}))
    elif reason == "chat_not_on_roster":
        store = dict(STORE, pattern={"bot_token": "tok-pattern", "chat_ids": [999]})
        monkeypatch.setattr(worker, "_secret_entry", lambda key: dict(store.get(key) or {}))
    elif reason == "quiet_hours":
        monkeypatch.setattr(worker, "_pacific_now", lambda: WEDNESDAY_10PM)
    elif reason == "budget_paused":
        monkeypatch.setattr(worker, "_current_tier", lambda: 2)
    elif reason == "cap_reached":
        h.table.claim = "cap"
    elif reason != "clean":  # pragma: no cover — a typo in the parameter list
        raise AssertionError(f"unknown dark reason {reason}")
    return worker, h


# ── O3: the happy path ────────────────────────────────────────────────────────


def test_a_granted_referral_sends_exactly_one_message_through_the_referred_bot(wired):
    worker, h = wired
    out = _inbound(worker)

    assert out["referred_to"] == "pattern_coach"
    referred = _messages(h, token="tok-pattern")
    assert len(referred) == 1, "a handoff is ONE text, not a burst"
    assert referred[0] == "Park mentioned the switch-off. That's mine."
    # And the original conversation is untouched by it.
    assert _messages(h, token="tok-sleep") == ["Sleep first, then the rest."]


def test_the_referred_coach_gets_the_tail_and_its_own_seat(wired):
    worker, h = wired
    _inbound(worker)

    referral_turn = h.turns[1]
    assert referral_turn["coach_name"] == "Dr. Nora Vale"
    assert "Dr. Lisa Park" in referral_turn["inbound"]  # the referring colleague, by name
    assert "can't switch off at night" in referral_turn["inbound"]  # the tail
    assert "Matthew has NOT texted you" in referral_turn["inbound"]
    # A referral cannot itself refer: no chain.
    assert "[[refer:" not in (referral_turn["colleagues_block"] or "")


def test_the_referral_lands_in_the_referred_coachs_partition_with_provenance(wired):
    worker, h = wired
    _inbound(worker)

    rows = [p for p in h.table.puts if p.get("pk") == coach_chat.chat_pk("pattern_coach")]
    assert len(rows) == 1, "only the coach's own words are stored — the frame is not Matthew speaking"
    row = rows[0]
    assert row["provenance"] == "telegram_referral"
    assert row["referred_by"] == "sleep_coach"
    assert row["role"] == coach_chat.ROLE_COACH
    assert row["sk"].startswith("CHAT#")
    assert row["cycle"] == 13


def test_the_ledger_is_claimed_before_the_referred_bot_is_touched(wired):
    worker, h = wired
    _inbound(worker)

    assert len(h.table.updates) == 1
    claim = h.table.updates[0]
    assert claim["Key"]["pk"] == "COACH#outbound_ledger"
    assert ":rcap" in claim["ExpressionAttributeValues"], "a referral must also spend its sub-cap"


def test_an_ungrounded_referral_is_never_sent(wired, monkeypatch):
    """He asked for the reply, so the reply earns the honest deferral. He did not
    ask for this, so 'let me check that' is just a buzz that says nothing."""
    worker, h = wired
    original = worker.coach_chat.run_turn

    def held_on_the_second(**kw):
        result = original(**kw)
        if len(h.turns) > 1:
            return coach_chat.TurnResult("Let me check that.", "held", [{"type": "night"}], 2)
        return result

    monkeypatch.setattr(worker.coach_chat, "run_turn", held_on_the_second)
    out = _inbound(worker)
    assert "referred_to" not in out
    assert _messages(h, token="tok-pattern") == []
    assert [p for p in h.table.puts if p.get("pk") == coach_chat.chat_pk("pattern_coach")] == []


def test_a_broken_referral_path_never_costs_matthew_his_reply(wired, monkeypatch):
    worker, h = wired
    monkeypatch.setattr(worker.coach_outbound, "resolve_referral_target", lambda *a, **k: 1 / 0)
    out = _inbound(worker)
    assert out["ok"] is True
    assert _messages(h, token="tok-sleep") == ["Sleep first, then the rest."]


def test_a_marker_only_reply_is_loud_not_silent(wired, monkeypatch):
    """The degenerate case: the coach said nothing but 'hand this over'. Stripping
    leaves no message, so nothing is sent — and rather than invent a sentence to
    fill the silence, the raw output is stored verbatim and a metric fires."""
    worker, h = wired
    metrics = []
    monkeypatch.setattr(worker, "_emit_metric", lambda name, cid: metrics.append(name))

    def marker_only_then_normal(**kw):
        h.turns.append(kw)
        if len(h.turns) == 1:
            return coach_chat.TurnResult("[[refer: pattern_coach]]", "sent", [], 1, bubbles=["[[refer: pattern_coach]]"])
        return coach_chat.TurnResult("That's mine.", "sent", [], 1, bubbles=["That's mine."])

    monkeypatch.setattr(worker.coach_chat, "run_turn", marker_only_then_normal)
    out = _inbound(worker)

    assert _messages(h, token="tok-sleep") == []
    assert "TelegramEmptyAfterMarkerStrip" in metrics
    stored = [p for p in h.table.puts if p.get("pk") == coach_chat.chat_pk("sleep_coach") and p.get("role") == coach_chat.ROLE_COACH]
    assert stored and stored[0]["text"] == "[[refer: pattern_coach]]", "the record shows exactly what the model produced"
    # The handoff still runs — Matthew does hear from the colleague.
    assert out["referred_to"] == "pattern_coach"


def test_the_stored_reply_is_what_he_actually_read(wired):
    worker, h = wired
    _inbound(worker)
    coach_rows = [p for p in h.table.puts if p.get("pk") == coach_chat.chat_pk("sleep_coach") and p.get("role") == coach_chat.ROLE_COACH]
    assert coach_rows and "[[refer" not in coach_rows[0]["text"]


# ── O4: the morning check-in ──────────────────────────────────────────────────


def test_the_checkin_is_dark_until_the_bot_exists(wired):
    """THE gating property: no feature flag, no env var — Eli has no bot in the
    telegram store, so the whole path exits clean without sending anything.

    The log line is captured by attaching a handler to the worker's own logger:
    the platform logger writes structured JSON to a stream it bound at import and
    does not propagate, so both caplog and capsys would assert vacuously here.
    """
    import logging

    worker, h = wired
    lines = []

    class _Capture(logging.Handler):
        def emit(self, record):
            lines.append(record.getMessage())

    handler = _Capture(level=logging.DEBUG)
    worker.logger.addHandler(handler)
    try:
        out = worker.lambda_handler({"kind": "morning_checkin"}, None)
    finally:
        worker.logger.removeHandler(handler)

    assert out == {"ok": True, "reason": "dark"}
    assert h.sends == []
    assert h.turns == []
    assert any("morning check-in dark" in line for line in lines), lines


def test_the_checkin_does_not_run_at_the_weekend(wired, monkeypatch):
    worker, h = wired
    monkeypatch.setattr(worker, "_pacific_now", lambda: SATURDAY_10AM)
    # Bot fully registered — the weekend guard is the only thing standing.
    monkeypatch.setattr(worker, "_secret_entry", lambda key: {"bot_token": "tok-eli", "chat_ids": [4242]})
    out = worker.lambda_handler({"kind": "morning_checkin"}, None)
    assert out == {"ok": True, "reason": "weekend"}
    assert h.sends == []


@pytest.fixture
def eli_registered(wired, monkeypatch):
    worker, h = wired
    monkeypatch.setattr(worker, "_secret_entry", lambda key: {"bot_token": "tok-eli", "chat_ids": [4242, 777]})
    return worker, h


def test_a_registered_checkin_sends_one_short_message_and_stores_it(eli_registered):
    worker, h = eli_registered
    out = worker.lambda_handler({"kind": "morning_checkin"}, None)

    assert out["ok"] is True
    sent = _messages(h, token="tok-eli")
    assert len(sent) == 1
    # The FIRST chat id on the bot, never a guess.
    assert _chat_ids(h) == [4242]
    rows = [p for p in h.table.puts if p.get("pk") == coach_chat.chat_pk("eli_marsh")]
    assert len(rows) == 1 and rows[0]["provenance"] == "telegram_checkin"
    assert rows[0]["role"] == coach_chat.ROLE_COACH
    frame = h.turns[0]["inbound"]
    assert "Morning check-in" in frame and "has not texted you" in frame


def test_two_ignored_checkins_silence_the_third(eli_registered, monkeypatch):
    worker, h = eli_registered
    monkeypatch.setattr(
        worker,
        "_chat_rows",
        lambda cid, limit=40: [_row("coach", CHECKIN), _row("coach", CHECKIN)],
    )
    out = worker.lambda_handler({"kind": "morning_checkin"}, None)
    assert out == {"ok": True, "reason": "silence respected"}
    assert h.sends == []
    assert h.table.updates == [], "a skipped check-in must not spend a ledger slot"


def test_a_reply_since_the_last_checkin_keeps_the_cadence(eli_registered, monkeypatch):
    worker, h = eli_registered
    monkeypatch.setattr(
        worker,
        "_chat_rows",
        lambda cid, limit=40: [_row("coach", CHECKIN), _row("coach", CHECKIN), _row("matthew")],
    )
    out = worker.lambda_handler({"kind": "morning_checkin"}, None)
    assert out["ok"] is True
    assert len(_messages(h, token="tok-eli")) == 1


def test_the_checkin_respects_the_shared_cap(eli_registered):
    worker, h = eli_registered
    h.table.claim = "cap"
    out = worker.lambda_handler({"kind": "morning_checkin"}, None)
    assert out == {"ok": True, "reason": "capped"}
    assert h.sends == []
    assert h.turns == [], "the cap is checked BEFORE inference — a refused send costs nothing"


def test_the_checkin_stands_down_when_the_budget_guard_is_up(eli_registered, monkeypatch):
    worker, h = eli_registered
    monkeypatch.setattr(worker, "_current_tier", lambda: 2)
    out = worker.lambda_handler({"kind": "morning_checkin"}, None)
    assert out == {"ok": True, "reason": "budget"}
    assert h.sends == []


def test_the_checkin_never_fires_in_quiet_hours(eli_registered, monkeypatch):
    """A manual invoke at 10pm is still a text at 10pm — the cron is not the guard."""
    worker, h = eli_registered
    monkeypatch.setattr(worker, "_pacific_now", lambda: WEDNESDAY_10PM)
    out = worker.lambda_handler({"kind": "morning_checkin"}, None)
    assert out["reason"] == "quiet hours"
    assert h.sends == []


def test_an_ungrounded_checkin_is_never_sent(eli_registered, monkeypatch):
    worker, h = eli_registered
    monkeypatch.setattr(
        worker.coach_chat,
        "run_turn",
        lambda **kw: h.turns.append(kw) or coach_chat.TurnResult("Let me check that.", "held", [{"type": "night"}], 2),
    )
    out = worker.lambda_handler({"kind": "morning_checkin"}, None)
    assert out == {"ok": True, "reason": "held"}
    assert h.sends == []


def test_a_scheduled_event_is_never_mistaken_for_a_work_order(wired):
    """Discriminated on `kind`, not on missing fields — a malformed work order
    must stay malformed rather than silently becoming an outbound text."""
    worker, h = wired
    out = worker.lambda_handler({"coach_id": "sleep", "chat_id": None, "text": ""}, None)
    assert out == {"ok": False, "reason": "malformed order"}
    assert h.sends == []


# ── route succession: the training bot continues as Max ──────────────────────


def test_the_training_bot_continues_as_the_performance_seat(wired):
    """Matthew's existing @ajm_training_bot chat was dead-ending at a silent
    rejection after the seat retired. It now lands in Max Reyes' own partition —
    one coach, one memory, no special first-message code."""
    worker, h = wired
    store = dict(STORE, training={"bot_token": "tok-training", "chat_ids": [4242]})
    import unittest.mock as mock

    with mock.patch.object(worker, "_secret_entry", side_effect=lambda key: dict(store.get(key) or {})):
        worker.lambda_handler({"coach_id": "training", "chat_id": 4242, "text": "squats felt heavy"}, None)

    assert h.turns[0]["coach_name"] == "Dr. Max Reyes"
    assert any(p.get("pk") == coach_chat.chat_pk("physical_coach") for p in h.table.puts)


def test_the_webhook_routes_the_training_path(wired):
    from web import telegram_webhook_lambda as hook

    assert hook.ROUTING["training"] == "training"


# ═════════════════════════════════════════════════════════════════════════════
# #2490 — outbound the DATA starts, and the rank that decides who gets a slot
#
#   O6  provenance ranking: six features, two slots, and a reserved second one —
#       ordering only, the cap never moves
#   O7  the event ledger: one real-world fact, one text, ever
#   O8  detection: every threshold is a statement about MATTHEW (ADR-105), and a
#       thin baseline is a reason to say nothing rather than to guess
#   O9  the sweep: exactly one outbound from a seeded trigger, no repeat-fire,
#       and every refusal proved to leave the event UNSPENT where it should
# ═════════════════════════════════════════════════════════════════════════════

from coach import (
    coach_event_triggers as triggers,  # noqa: E402
    persona_registry,  # noqa: E402
)

# 09:00 PT is the reserved-slot cutoff, so these two moments sit either side of it.
WEDNESDAY_8AM = datetime(2026, 8, 12, 8, 30, tzinfo=PACIFIC)
TODAY = "2026-08-12"


class EventTable(LedgerTable):
    """The ledger emulator plus the conditional put the event claim actually uses."""

    def __init__(self, fail=False):
        super().__init__()
        self.fail = fail
        self.puts = []

    def put_item(self, Item, ConditionExpression=None):
        if self.fail:
            raise RuntimeError("ddb is having a day")
        key = (Item["pk"], Item["sk"])
        if ConditionExpression and "attribute_not_exists(sk)" in ConditionExpression and key in self.items:
            raise _CCF()
        self.items[key] = dict(Item)
        self.puts.append(dict(Item))


def _recovery_series(values, end=TODAY):
    """{date: score} ending on `end`, one row per day, oldest first."""
    from datetime import timedelta

    last = datetime.strptime(end, "%Y-%m-%d").date()
    return {(last - timedelta(days=len(values) - 1 - i)).isoformat(): v for i, v in enumerate(values)}


def _lift_sessions(e1rms, name="Bench Press", end=TODAY):
    """A per-lift session list shaped like session_bests() output (weekly sessions)."""
    from datetime import timedelta

    last = datetime.strptime(end, "%Y-%m-%d").date()
    return {
        name: [
            {"date": (last - timedelta(days=(len(e1rms) - 1 - i) * 7)).isoformat(), "e1rm_lb": v, "weight_kg": v / 2.2046226, "reps": 1}
            for i, v in enumerate(e1rms)
        ]
    }


# ── O6: provenance ranking ────────────────────────────────────────────────────


def test_the_rank_is_the_owners_order():
    """A kept promise first, a pleasantry last. This ordering is a claim about
    what a coach owes him, so it is pinned rather than left to dict insertion."""
    order = [
        coach_outbound.PROVENANCE_PROMISE,
        coach_outbound.PROVENANCE_REFERRAL,
        coach_outbound.PROVENANCE_PRE_EVENT,
        coach_outbound.PROVENANCE_CONCERN,
        coach_outbound.PROVENANCE_CHECKIN,
        coach_outbound.PROVENANCE_CELEBRATION,
    ]
    assert sorted(order, key=coach_outbound.priority) == order


def test_an_unregistered_outbound_class_ranks_last_not_first():
    """A new feature that forgets to register may be starved; it may never starve
    a promise. Unknown must sort AFTER everything, not default to zero."""
    assert coach_outbound.priority("telegram_something_new") > coach_outbound.priority(coach_outbound.PROVENANCE_CELEBRATION)
    assert coach_outbound.priority(None) > coach_outbound.priority(coach_outbound.PROVENANCE_PROMISE)


def test_the_cap_is_ordering_not_a_raise():
    """The whole decision is that five features share TWO slots. If this number
    ever moves, the reservation stops being a trade-off and becomes a volume knob."""
    assert coach_outbound.DAILY_OUTBOUND_CAP == 2
    for prov in coach_outbound.OUTBOUND_PRIORITY:
        for moment in (WEDNESDAY_8AM, WEDNESDAY_10AM, WEDNESDAY_10PM):
            assert coach_outbound.effective_cap(prov, moment) <= coach_outbound.DAILY_OUTBOUND_CAP


def test_before_the_cutoff_nobody_is_reserved_out():
    for prov in coach_outbound.OUTBOUND_PRIORITY:
        assert coach_outbound.effective_cap(prov, WEDNESDAY_8AM) == 2


def test_after_the_cutoff_the_second_slot_belongs_to_the_reactive_classes():
    high = (coach_outbound.PROVENANCE_PROMISE, coach_outbound.PROVENANCE_REFERRAL, coach_outbound.PROVENANCE_PRE_EVENT)
    routine = (coach_outbound.PROVENANCE_CONCERN, coach_outbound.PROVENANCE_CHECKIN, coach_outbound.PROVENANCE_CELEBRATION)
    assert all(coach_outbound.effective_cap(p, WEDNESDAY_10AM) == 2 for p in high)
    assert all(coach_outbound.effective_cap(p, WEDNESDAY_10AM) == 1 for p in routine)


def test_a_routine_ping_cannot_pre_spend_the_reactive_slot():
    """The failure this exists to stop: a morning check-in and a celebration take
    both slots, and the afternoon referral — the text that was actually about a
    conversation he just had — is permanently starved."""
    t = LedgerTable()
    assert coach_outbound.claim_outbound(t, TODAY, provenance=coach_outbound.PROVENANCE_CHECKIN, now_pt=WEDNESDAY_10AM) is True
    assert coach_outbound.claim_outbound(t, TODAY, provenance=coach_outbound.PROVENANCE_CELEBRATION, now_pt=WEDNESDAY_10AM) is False
    # ...and the slot it did not spend is still there for the reactive class.
    assert coach_outbound.claim_outbound(t, TODAY, provenance=coach_outbound.PROVENANCE_REFERRAL, now_pt=WEDNESDAY_10AM) is True
    # But the cap is still a cap: three is never allowed, whoever asks.
    assert coach_outbound.claim_outbound(t, TODAY, provenance=coach_outbound.PROVENANCE_PROMISE, now_pt=WEDNESDAY_10AM) is False


def test_a_caller_that_declares_nothing_gets_the_old_unreserved_cap():
    """The reservation is opt-in by declaration — an existing caller that names no
    provenance must behave exactly as it did before #2490."""
    t = LedgerTable()
    assert coach_outbound.claim_outbound(t, TODAY) is True
    assert coach_outbound.claim_outbound(t, TODAY) is True
    assert coach_outbound.claim_outbound(t, TODAY) is False


def test_an_unknown_moment_keeps_the_reservation_on():
    """The dark direction again: if we cannot tell what time it is, the reactive
    slot stays reserved rather than being handed to a pleasantry."""
    assert coach_outbound.effective_cap(coach_outbound.PROVENANCE_CELEBRATION, object()) == 1


# ── O7: the event ledger ──────────────────────────────────────────────────────


def test_one_event_claims_once():
    t = EventTable()
    assert coach_outbound.claim_event(t, "lift_pr#bench-press#2026-08-12") is True
    assert coach_outbound.claim_event(t, "lift_pr#bench-press#2026-08-12") is False


def test_a_different_event_is_still_claimable():
    t = EventTable()
    assert coach_outbound.claim_event(t, "lift_pr#bench-press#2026-08-12") is True
    assert coach_outbound.claim_event(t, "recovery_slide#2026-08-10") is True


def test_an_event_claim_that_cannot_be_written_is_a_skip_not_a_crash():
    assert coach_outbound.claim_event(EventTable(fail=True), "lift_pr#x#2026-08-12") is False


def test_an_empty_event_id_never_claims_anything():
    t = EventTable()
    assert coach_outbound.claim_event(t, "") is False
    assert t.puts == []


# ── O8: detection — thresholds that are statements about Matthew ─────────────


def test_three_days_under_his_own_p25_is_the_trigger():
    rec = _recovery_series([70] * 30 + [66, 62, 58] + [30, 28, 33])
    ev = triggers.detect_recovery_slide(rec, TODAY)
    assert ev is not None
    assert ev["provenance"] == coach_outbound.PROVENANCE_CONCERN
    assert ev["persona_id"] == triggers.RECOVERY_OWNER


def test_a_universal_constant_would_have_fired_here_and_the_personal_band_does_not():
    """The ADR-105 proof. Three days at 30-ish percent trip every off-the-shelf
    'poor recovery' rule. Against HIS OWN distribution — where 30 is ordinary —
    they are not a slide, and the coach says nothing."""
    rec = _recovery_series([28, 30, 32] * 10 + [31, 30, 29])
    assert min(rec.values()) < 33  # a fixed "<33%" threshold fires on this data
    assert triggers.detect_recovery_slide(rec, TODAY) is None


def test_the_same_days_against_a_high_baseline_do_fire():
    """Same three numbers, different person-shaped history — and now it IS news.
    The trigger is the distribution, which is exactly the point."""
    rec = _recovery_series([78, 80, 82] * 10 + [31, 30, 29])
    assert triggers.detect_recovery_slide(rec, TODAY) is not None


def test_a_thin_recovery_history_is_a_reason_to_say_nothing():
    rec = _recovery_series([70] * 5 + [20, 19, 18])
    assert triggers.detect_recovery_slide(rec, TODAY) is None


def test_two_bad_days_are_not_a_slide():
    rec = _recovery_series([70] * 34 + [28, 27])
    assert triggers.detect_recovery_slide(rec, TODAY) is None


def test_a_gap_in_the_data_is_not_a_run_of_bad_days():
    """Whoop missing two nights must never be read as two bad nights."""
    rec = _recovery_series([70] * 30 + [66, 62, 58] + [28, 27, 26])
    del rec[sorted(rec)[-2]]
    assert triggers.detect_recovery_slide(rec, TODAY) is None


def test_a_slide_that_ended_last_week_is_not_texted_about():
    rec = _recovery_series([70] * 30 + [66, 62, 58] + [28, 27, 26], end="2026-08-01")
    assert triggers.detect_recovery_slide(rec, TODAY) is None


def test_a_slide_that_keeps_sliding_keeps_the_same_event_id():
    """Day four of the same slide derives the ID day three already spent — which
    is the whole no-repeat-fire mechanism, and it lives in the id, not in a flag."""
    base = [70] * 30 + [66, 62, 58]
    day3 = triggers.detect_recovery_slide(_recovery_series(base + [28, 27, 26]), TODAY)
    day4 = triggers.detect_recovery_slide(_recovery_series(base + [28, 27, 26, 25], end="2026-08-13"), "2026-08-13")
    assert day3["event_id"] == day4["event_id"]


def test_a_pr_must_clear_the_lifts_own_noise():
    """A lift that swings 15 lb between sessions does not get a text for 2 lb."""
    noisy = _lift_sessions([200, 215, 202, 218, 205, 220])
    assert triggers.detect_lift_pr(noisy, TODAY) is None


def test_a_real_pr_on_a_steady_lift_fires():
    ev = triggers.detect_lift_pr(_lift_sessions([200, 201, 202, 203, 204, 215]), TODAY)
    assert ev is not None
    assert ev["provenance"] == coach_outbound.PROVENANCE_CELEBRATION
    assert ev["persona_id"] == triggers.LIFT_OWNER
    assert ev["event_id"] == "lift_pr#bench-press#" + TODAY


def test_a_thin_lift_history_has_no_personal_noise_scale_and_so_no_pr():
    assert triggers.detect_lift_pr(_lift_sessions([200, 205, 260]), TODAY) is None


def test_matching_the_previous_best_is_not_a_pr():
    assert triggers.detect_lift_pr(_lift_sessions([200, 201, 202, 203, 215, 215]), TODAY) is None


def test_a_pr_logged_last_month_is_not_todays_news():
    assert triggers.detect_lift_pr(_lift_sessions([200, 201, 202, 203, 204, 215], end="2026-07-01"), TODAY) is None


def test_the_estimated_1rm_is_the_sites_estimated_1rm():
    """The phone and /cockpit/ are not allowed to disagree about the same lift."""
    assert round(triggers.e1rm_lb(100, 5)) == round((100 * 2.2046226) * (1 + 5 / 30.0))
    assert triggers.e1rm_lb(100, 20) is None  # Epley's rep gate, same as the site's
    assert triggers.e1rm_lb(0, 5) is None


def test_session_bests_takes_the_best_set_of_each_session():
    workouts = [
        {
            "date": TODAY,
            "exercises": [{"name": "Squat", "sets": [{"weight_kg": 80, "reps": 5}, {"weight_kg": 100, "reps": 3}]}],
        }
    ]
    best = triggers.session_bests(workouts)
    assert list(best) == ["Squat"]
    assert best["Squat"][0]["weight_kg"] == 100


def test_a_weight_milestone_is_consumed_from_the_ledger_never_re_derived():
    """#1626/#1628 already own what a weight milestone IS — trailing 7-day mean,
    n>=3, cooldown, write-once, spiral-gated. A second threshold here would be a
    second platform opinion about the same crossing."""
    ev = triggers.detect_milestone(
        [
            {
                "milestone_id": "weight_sub_250",
                "label": "Sub-250",
                "ladder": "weight",
                "description": "Trailing 7-day mean weight under 250 lbs",
                "event_date": TODAY,
                "measurement": {"mean": 249.2, "n": 5, "window_days": 7},
            }
        ],
        TODAY,
    )
    assert ev["persona_id"] == triggers.NUTRITION_OWNER
    assert "n=5" in ev["evidence"] and "249.2" in ev["evidence"]


def test_an_unmapped_ladder_belongs_to_the_head_coach_not_a_random_specialist():
    ev = triggers.detect_milestone([{"milestone_id": "x_1", "label": "X", "ladder": "brand_new", "event_date": TODAY}], TODAY)
    assert ev["persona_id"] == triggers.LEAD_OWNER


def test_old_milestones_are_history_not_news():
    assert triggers.detect_milestone([{"milestone_id": "w", "label": "W", "ladder": "weight", "event_date": "2026-06-01"}], TODAY) is None


def test_every_domain_owner_is_a_coach_who_can_actually_text():
    owners = {triggers.LIFT_OWNER, triggers.RECOVERY_OWNER, triggers.NUTRITION_OWNER, triggers.LEAD_OWNER}
    owners |= set(triggers.MILESTONE_LADDER_OWNER.values())
    assert owners <= set(persona_registry.TEXTING_PERSONA_IDS)


def test_an_event_with_no_evidence_cannot_be_built_at_all():
    """Grounding is not relaxed for feel: a ping with nothing behind it is made
    unrepresentable here rather than caught three layers later."""
    assert coach_outbound.event_frame(coach_outbound.PROVENANCE_CELEBRATION, "") == ""
    assert coach_outbound.event_frame("telegram_unknown_kind", "- something happened") == ""
    assert (
        triggers._event(
            kind="x", event_id="x#1", provenance=coach_outbound.PROVENANCE_CELEBRATION, persona_id="physical_coach", evidence=[]
        )
        is None
    )


def test_the_frame_says_out_loud_that_matthew_did_not_write():
    """The outbound failure mode: a coach answering a message that was never sent."""
    for prov in (coach_outbound.PROVENANCE_CELEBRATION, coach_outbound.PROVENANCE_CONCERN):
        frame = coach_outbound.event_frame(prov, "- a thing")
        assert "has not texted you" in frame
        assert "a thing" in frame


def test_concern_outranks_celebration_inside_one_sweep():
    signals = {
        "recovery": _recovery_series([78, 80, 82] * 10 + [31, 30, 29]),
        "lift_bests": _lift_sessions([200, 201, 202, 203, 204, 215]),
    }
    found = triggers.candidates(signals, TODAY)
    assert [e["provenance"] for e in found] == [coach_outbound.PROVENANCE_CONCERN, coach_outbound.PROVENANCE_CELEBRATION]


def test_one_broken_detector_does_not_silence_the_others():
    signals = {"recovery": "not a mapping", "lift_bests": _lift_sessions([200, 201, 202, 203, 204, 215])}
    assert [e["kind"] for e in triggers.candidates(signals, TODAY)] == [triggers.KIND_LIFT_PR]


# ── O9: the sweep ─────────────────────────────────────────────────────────────


class Sweep:
    """A dry-run rig: real gate, real claims, a recorded send instead of a phone."""

    def __init__(self):
        self.table = EventTable()
        self.sent = []
        self.rows = []

    def seat(self, persona_id):
        return ("tok-" + persona_id, 4242)

    def speak(self, event, token, chat_id):
        self.sent.append((event["event_id"], event["persona_id"], event["provenance"], token, chat_id))
        return {"ok": True, "event_id": event["event_id"]}

    def chat_rows(self, persona_id):
        return list(self.rows)

    def run(self, signals, now=WEDNESDAY_8AM, **kw):
        return triggers.run_sweep(
            now_pt=now, table=self.table, seat=self.seat, speak=self.speak, chat_rows=self.chat_rows, signals=signals, **kw
        )


SLIDE = {"recovery": _recovery_series([78, 80, 82] * 10 + [31, 30, 29])}


def test_a_seeded_trigger_produces_exactly_one_outbound():
    s = Sweep()
    s.run(SLIDE)
    assert len(s.sent) == 1
    assert s.sent[0][1] == triggers.RECOVERY_OWNER
    assert s.sent[0][2] == coach_outbound.PROVENANCE_CONCERN


def test_the_same_event_never_fires_twice():
    """Re-running the sweep on the same data — the next day's cron, a retry, a
    manual invoke — must not text him again about the same three days."""
    s = Sweep()
    s.run(SLIDE)
    out = s.run(SLIDE)
    assert len(s.sent) == 1
    assert out["reason"] == "nothing sendable"


def test_only_one_text_leaves_even_when_two_events_fire():
    s = Sweep()
    s.run({**SLIDE, "lift_bests": _lift_sessions([200, 201, 202, 203, 204, 215])})
    assert len(s.sent) == 1
    assert s.sent[0][2] == coach_outbound.PROVENANCE_CONCERN  # the higher rank spoke


def test_the_sweep_never_fires_in_quiet_hours():
    s = Sweep()
    assert s.run(SLIDE, now=WEDNESDAY_10PM)["reason"] == "quiet hours"
    assert s.sent == [] and s.table.puts == []


def test_the_sweep_stands_down_when_the_budget_guard_is_up():
    s = Sweep()
    assert s.run(SLIDE, tier=3)["reason"] == "budget"
    assert s.sent == []


def test_nothing_to_say_is_the_ordinary_outcome():
    assert Sweep().run({"recovery": _recovery_series([70] * 40)})["reason"] == "no events"


def test_a_dark_bot_costs_no_event_and_no_slot():
    """The load-bearing ordering: a coach whose bot the owner has not created yet
    must not consume the event forever, or the first text after BotFather is a
    silence about something that already happened."""
    s = Sweep()
    s.seat = lambda pid: (None, None)
    assert s.run(SLIDE)["reason"] == "nothing sendable"
    assert s.table.puts == [] and s.table.items == {}


def test_two_ignored_pings_stop_this_one_too_and_leave_it_unspent():
    s = Sweep()
    s.rows = [
        {"role": "coach", "provenance": coach_outbound.PROVENANCE_CONCERN},
        {"role": "coach", "provenance": coach_outbound.PROVENANCE_CONCERN},
    ]
    assert s.run(SLIDE)["reason"] == "nothing sendable"
    assert s.sent == [] and s.table.puts == []


def test_a_capped_day_sends_nothing():
    s = Sweep()
    coach_outbound.claim_outbound(s.table, TODAY)
    coach_outbound.claim_outbound(s.table, TODAY)
    assert s.run(SLIDE)["reason"] == "capped"
    assert s.sent == []


def test_the_spiral_breaker_holds_a_celebration_but_not_a_check_in_on_him(monkeypatch):
    """During a suspected downturn the platform checks in, it does not congratulate.
    Both halves of that sentence are load-bearing, so both are pinned."""
    monkeypatch.setattr(triggers, "_celebration_allowed", lambda table, today: False)
    s = Sweep()
    assert s.run({"lift_bests": _lift_sessions([200, 201, 202, 203, 204, 215])})["reason"] == "nothing sendable"
    assert s.sent == []
    s2 = Sweep()
    s2.run(SLIDE)
    assert len(s2.sent) == 1


def test_an_unreadable_spiral_breaker_holds_the_celebration():
    """Fails closed, like every other gate in this path."""

    class Boom:
        def query(self, **kw):
            raise RuntimeError("no")

        def get_item(self, **kw):
            raise RuntimeError("no")

    assert triggers._celebration_allowed(Boom(), TODAY) is False


def test_the_celebration_is_registered_on_the_emitter_ratchet():
    from coach import spiral_breaker

    assert spiral_breaker.CELEBRATORY_EMITTERS["coach_event_outbound"]["wired"] is True


# ── O9b: through the real worker ─────────────────────────────────────────────


class SeededTable(QuietTable):
    """A table that answers the sweep's real queries by partition key."""

    def __init__(self, rows_by_pk):
        super().__init__()
        self.rows_by_pk = rows_by_pk

    def query(self, **kwargs):
        pk = (kwargs.get("ExpressionAttributeValues") or {}).get(":pk")
        return {"Items": list(self.rows_by_pk.get(pk) or [])}


def test_a_scheduled_event_sweep_is_never_mistaken_for_a_work_order(wired):
    worker, h = wired
    calls = []
    import unittest.mock as mock

    from coach import coach_event_triggers as t

    with mock.patch.object(t, "run_sweep", side_effect=lambda **kw: calls.append(kw) or {"ok": True}):
        out = worker.lambda_handler({"kind": "event_outbound"}, None)
    assert out["ok"] is True and len(calls) == 1
    assert h.sends == []  # no inbound reply was ever generated


def test_the_slide_reaches_his_phone_through_the_owning_coachs_own_bot(wired, monkeypatch):
    """End to end on the worker: seeded Whoop rows -> the personal band -> Lisa
    Park's bot -> her own partition, stamped with the provenance and the event."""
    worker, h = wired
    table = SeededTable(
        {"USER#matthew#SOURCE#whoop": [{"sk": f"DATE#{d}", "recovery_score": v} for d, v in sorted(SLIDE["recovery"].items())]}
    )
    monkeypatch.setattr(worker, "_table", lambda: table)
    monkeypatch.setattr(worker, "_secret_entry", lambda key: {"sleep": {"bot_token": "tok-sleep", "chat_ids": [4242]}}.get(key) or {})
    monkeypatch.setattr(worker, "_pacific_now", lambda: datetime(2026, 8, 12, 8, 30, tzinfo=PACIFIC))
    monkeypatch.setattr(
        worker.coach_chat,
        "run_turn",
        lambda **kw: h.turns.append(kw)
        or coach_chat.TurnResult(
            "three rough nights in a row. anything going on?", "sent", [], 1, bubbles=["three rough nights in a row. anything going on?"]
        ),
    )

    out = worker.lambda_handler({"kind": "event_outbound"}, None)

    assert out["persona_id"] == "sleep_coach"
    assert _messages(h, token="tok-sleep") == ["three rough nights in a row. anything going on?"]
    # The triggering rows are in the frame AND in the grounder's evidence.
    assert "Whoop recovery" in h.turns[0]["inbound"]
    stored = [p for p in table.puts if p.get("pk") == coach_chat.chat_pk("sleep_coach")]
    assert stored and stored[0]["provenance"] == coach_outbound.PROVENANCE_CONCERN
    assert stored[0]["event_id"] == out["event_id"]


def test_an_ungrounded_event_ping_is_never_sent(wired, monkeypatch):
    worker, h = wired
    table = SeededTable(
        {"USER#matthew#SOURCE#whoop": [{"sk": f"DATE#{d}", "recovery_score": v} for d, v in sorted(SLIDE["recovery"].items())]}
    )
    monkeypatch.setattr(worker, "_table", lambda: table)
    monkeypatch.setattr(worker, "_secret_entry", lambda key: {"sleep": {"bot_token": "tok-sleep", "chat_ids": [4242]}}.get(key) or {})
    monkeypatch.setattr(worker, "_pacific_now", lambda: datetime(2026, 8, 12, 8, 30, tzinfo=PACIFIC))
    monkeypatch.setattr(
        worker.coach_chat, "run_turn", lambda **kw: coach_chat.TurnResult("", "held_ungrounded", ["fabrication"], 2, bubbles=[])
    )

    out = worker.lambda_handler({"kind": "event_outbound"}, None)
    assert out["reason"] == "held"
    assert h.sends == []


def test_the_event_claims_survive_an_experiment_reset():
    """A wiped claim would let the next sweep say the same thing twice. "I already
    texted him about this PR" is not an artifact of the cycle that produced it."""
    from experiment.phase_taxonomy import SYSTEM_STATE, classify

    assert classify(coach_outbound.EVENT_LEDGER_PK, coach_outbound.event_sk("lift_pr#bench-press#2026-08-12")) == SYSTEM_STATE


def test_every_statistical_claim_in_the_evidence_carries_its_n():
    """ADR-105 rule 1, on the surface where it is easiest to forget: the coach can
    only say what the evidence says, so the evidence has to state its own n."""
    pr = triggers.detect_lift_pr(_lift_sessions([200, 201, 202, 203, 204, 215]), TODAY)
    assert "n=5 changes" in pr["evidence"] and "SD" in pr["evidence"]
    slide = triggers.detect_recovery_slide(SLIDE["recovery"], TODAY)
    assert "n=33 recorded days" in slide["evidence"]
    assert "Matthew's, not a general threshold" in slide["evidence"]


# ── O10: liveness — the sweep has to be able to say it ran ───────────────────
#
# This path's characteristic failure is INVISIBLE ABSENCE. An error alarm needs an
# invocation to fire, and a rule that quietly stops firing produces none: "no
# celebration this month" and "the cron is dead" look identical from outside. So the
# sweep reports itself on every completed run and a heartbeat alarms on the silence.


def test_every_sweep_outcome_reports_a_candidate_count():
    """Guard the SET, not one branch: a return that forgets `candidates` emits a
    heartbeat of 0 that is indistinguishable from a real quiet day, which is the
    metric quietly becoming a lie. Every reachable outcome is exercised."""
    outcomes = {}

    def _record(reason, out):
        outcomes[reason] = out

    quiet = Sweep()
    _record("quiet hours", quiet.run(SLIDE, now=WEDNESDAY_10PM))
    _record("budget", Sweep().run(SLIDE, tier=3))
    _record("no events", Sweep().run({"recovery": _recovery_series([70] * 40)}))

    dark = Sweep()
    dark.seat = lambda pid: (None, None)
    _record("nothing sendable", dark.run(SLIDE))

    capped = Sweep()
    coach_outbound.claim_outbound(capped.table, TODAY)
    coach_outbound.claim_outbound(capped.table, TODAY)
    _record("capped", capped.run(SLIDE))

    _record("sent", Sweep().run(SLIDE))

    assert set(outcomes) == {"quiet hours", "budget", "no events", "nothing sendable", "capped", "sent"}
    for reason, out in outcomes.items():
        assert "candidates" in out, f"{reason} reports no candidate count — the heartbeat would read as a quiet day"
        assert isinstance(out["candidates"], int)


def test_a_quiet_day_is_a_datapoint_of_zero_not_a_silence():
    """The distinction the whole heartbeat rests on: nothing to say still reports."""
    assert Sweep().run({"recovery": _recovery_series([70] * 40)})["candidates"] == 0
    assert Sweep().run(SLIDE)["candidates"] == 1


def test_the_worker_emits_the_heartbeat_on_every_sweep_including_a_stand_down(wired, monkeypatch):
    from coach import coach_event_triggers as t

    emitted = []
    worker_mod = wired[0]
    monkeypatch.setattr(worker_mod, "_emit_metric", lambda name, cid, value=1: emitted.append((name, cid, value)))
    monkeypatch.setattr(t, "run_sweep", lambda **kw: {"ok": True, "reason": "no events", "candidates": 0})
    worker_mod.lambda_handler({"kind": "event_outbound"}, None)

    monkeypatch.setattr(t, "run_sweep", lambda **kw: {"ok": True, "reason": "quiet hours", "candidates": 0})
    worker_mod.lambda_handler({"kind": "event_outbound"}, None)

    assert emitted == [
        (worker_mod.EVENT_SWEEP_METRIC, worker_mod.EVENT_SWEEP_DIMENSION, 0.0),
        (worker_mod.EVENT_SWEEP_METRIC, worker_mod.EVENT_SWEEP_DIMENSION, 0.0),
    ]


def test_the_heartbeat_carries_the_number_of_events_found(wired, monkeypatch):
    """One series, two questions: does it exist (did the cron run) and how big is it
    (is detection still finding anything)."""
    from coach import coach_event_triggers as t

    emitted = []
    worker_mod = wired[0]
    monkeypatch.setattr(worker_mod, "_emit_metric", lambda name, cid, value=1: emitted.append(value))
    monkeypatch.setattr(t, "run_sweep", lambda **kw: {"ok": True, "reason": "nothing sendable", "candidates": 2})
    worker_mod.lambda_handler({"kind": "event_outbound"}, None)
    assert emitted == [2.0]


def test_the_heartbeat_alarm_watches_the_metric_the_worker_actually_emits():
    """The alarm and the emitter are in different files and different languages of
    intent; nothing but this test stops a rename on one side from silently darkening
    the other (tests/test_heartbeat_completeness.py only proves the NAME exists)."""
    import os

    from coach import telegram_worker_lambda as worker_mod

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "cdk", "stacks", "serve_stack.py"), encoding="utf-8") as fh:
        stack = fh.read()

    assert 'alarm_name="telegram-event-sweep-heartbeat"' in stack
    assert f'metric_name="{worker_mod.EVENT_SWEEP_METRIC}"' in stack
    assert f'dimensions_map={{"Coach": "{worker_mod.EVENT_SWEEP_DIMENSION}"}}' in stack
    # Absence must be the ALARM condition — a heartbeat on NOT_BREACHING is a
    # heartbeat that can never fire, which is the whole failure it exists to catch.
    assert "TreatMissingData.BREACHING" in stack
