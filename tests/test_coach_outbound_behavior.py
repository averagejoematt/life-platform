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
