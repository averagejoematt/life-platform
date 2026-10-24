"""tests/test_response_protocol_owner_5126.py — M6: one coach owns the early-warning response, and the mind
coach's predictions are about the mind domain and read the check-in (#5126, epic #5120).

  1. The repo's plan root names ONE owner (`failure_mode.response_owner`), an operational coach, and its
     protocol prose names no other persona or role. A two-claimant fixture (the pre-#5126 prose: "the board
     lead" + "Maya") FAILS the same check — the acceptance's "a test fails when two personas claim the response".
  2. The coach context (#5071) carries the protocol on the owner channel and never on a published one.
  3. The mind coach's own Telegram thread reads the owner-only evening check-in and the protocol; absence is
     stated, never a rating.
  4. A mind-coach prediction graded on another domain's metric is refused at emission; a mind-domain or
     check-in call is kept (as an observation — no mind metric is gradable, and grading from the owner-only
     check-in would publish it). Other coaches are unaffected.
"""

import json
import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "coach"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from coach import (
    coach_domain_facts as cdf,  # noqa: E402
    prediction_scope as ps,  # noqa: E402
    response_protocol as rp,  # noqa: E402
)
from coach.persona_registry import OPERATIONAL_COACH_IDS  # noqa: E402
from training import coach_context  # noqa: E402

_PRE_5126_PROSE = (
    "The correct response is: (1) the board lead acknowledges the signal directly and with empathy, "
    "(2) Maya addresses the behavioral pattern, (3) the weekly priority shifts to ONE thing."
)


def _goals() -> dict:
    with open(os.path.join(_REPO, "config", "user_goals.json"), encoding="utf-8") as fh:
        return json.load(fh)


def _names() -> dict:
    with open(os.path.join(_REPO, "config", "personas.json"), encoding="utf-8") as fh:
        return {pid: p.get("name", "") for pid, p in json.load(fh)["personas"].items()}


# ── 1. one owner ──────────────────────────────────────────────────────────────────────────


def test_the_plan_root_names_exactly_one_operational_owner():
    fm = _goals()["failure_mode"]
    assert rp.problems(fm, _names(), OPERATIONAL_COACH_IDS) == []
    assert rp.claimants(fm, _names()) == ["mind_coach"]
    assert "Maya" not in fm["coach_response"] and "board lead" not in fm["coach_response"].lower()


def test_two_personas_claiming_the_response_fails():
    fm = {"response_owner": "mind_coach", "coach_response": _PRE_5126_PROSE}
    who = rp.claimants(fm, _names())
    assert who == ["eli_marsh", "maya_rodriguez", "mind_coach"]
    msgs = rp.problems(fm, _names(), OPERATIONAL_COACH_IDS)
    assert any("3 personas claim the early-warning response" in m for m in msgs), msgs
    # The pre-#5126 shape exactly: no owner field, two personas in prose — still two claimants, still a failure.
    bare = {"coach_response": _PRE_5126_PROSE}
    assert len(rp.claimants(bare, _names())) == 2 and len(rp.problems(bare, _names(), OPERATIONAL_COACH_IDS)) == 2


def test_an_owner_that_is_not_an_operational_coach_fails():
    msgs = rp.problems({"response_owner": "maya_rodriguez", "coach_response": "Maya answers it."}, _names(), OPERATIONAL_COACH_IDS)
    assert any("not an operational coach" in m for m in msgs)
    assert rp.problems({"coach_response": "x"}, _names(), OPERATIONAL_COACH_IDS)[0].startswith("failure_mode.response_owner is not set")


def test_a_board_twin_sharing_the_owners_name_is_the_owner_not_a_second_claim():
    # paul_conti's board persona carries the mind coach's display name; naming it in prose is not a second owner.
    fm = {"response_owner": "mind_coach", "coach_response": "Nathan Reeves acknowledges the signal."}
    assert rp.claimants(fm, _names()) == ["mind_coach"]


def test_the_view_carries_owner_signals_and_protocol():
    v = rp.view(_goals(), _names())
    assert v["owner"] == "mind_coach" and v["owner_name"] == "Nathan Reeves"
    assert len(v["signals"]) == len(_goals()["failure_mode"]["early_warning_signals"]) and v["protocol"]
    assert v["line"].startswith("Owner: Nathan Reeves (mind_coach)")
    assert rp.view({}, _names()) is None


# ── 2. the coach context carries it (owner channel only) ─────────────────────────────────


def test_coach_context_carries_the_protocol_on_the_owner_channel_only():
    v = rp.view(_goals(), _names())
    owner = coach_context.assemble("2026-10-24", packet=None, constraint_block=None, response_protocol=v)
    assert owner["response_protocol"] == v and "EARLY-WARNING RESPONSE" in owner["text"] and v["line"] in owner["text"]
    assert coach_context.summary(owner)["response_owner"] == "mind_coach"
    pub = coach_context.assemble("2026-10-24", packet=None, constraint_block=None, response_protocol=v, published=True)
    assert pub["response_protocol"] is None and "EARLY-WARNING RESPONSE" not in pub["text"]
    none = coach_context.assemble("2026-10-24", packet=None, constraint_block=None)
    assert none["response_protocol"] is None and "EARLY-WARNING RESPONSE" not in none["text"]


def test_the_planning_callers_pass_the_protocol():
    # Both owner-channel assemblers hand the protocol in (the MCP packet path and the Telegram training thread).
    for rel in ("mcp/plan_helpers.py", "lambdas/coach/coach_domain_facts.py"):
        with open(os.path.join(_REPO, rel), encoding="utf-8") as fh:
            assert "response_protocol=_response_protocol()" in fh.read(), rel


# ── 3. the mind coach's own thread reads the check-in ────────────────────────────────────


class _Table:
    def __init__(self, rows):
        self.rows = rows
        self.pks = []

    def query(self, **kw):
        pk = kw["ExpressionAttributeValues"][":pk"]
        self.pks.append(pk)
        return {"Items": self.rows if pk.endswith("#evening_checkin") else []}


def test_the_mind_pack_reads_the_checkin_and_the_protocol(monkeypatch):
    monkeypatch.setattr(cdf, "_response_protocol", lambda: rp.view(_goals(), _names()))
    rows = [
        {"sk": "DATE#2026-10-22", "hunger": 2, "stress": 3, "cravings": 1, "word": "tired"},
        {"sk": "DATE#2026-10-23", "hunger": 1, "stress": 1, "cravings": 2, "word": "calm"},
    ]
    t = _Table(rows)
    lines = cdf._PACKS["mind"](t, "2026-10-24")
    # ONE mind pack: #5123's mood read (journal, then the check-in) first, then this lane's recent week + protocol.
    assert set(t.pks) == {"USER#matthew#SOURCE#notion", "USER#matthew#SOURCE#evening_checkin"}
    assert lines[0].startswith("Mood read")
    text = "\n".join(lines)
    assert "2 of the last 7 evenings answered" in text and "stress mean 2.0 over 2 evening(s)" in text
    assert "Latest evening 2026-10-23: stress 1, hunger 1, cravings 2." in text
    assert "calm" not in text and "tired" not in text  # never the check-in word (#5123's rule for this thread)
    assert lines[-1].startswith("Early-warning response: Owner: Nathan Reeves (mind_coach)")


def test_a_dark_checkin_is_stated_absent_never_a_rating(monkeypatch):
    monkeypatch.setattr(cdf, "_response_protocol", lambda: None)
    lines = cdf._mind_pack(_Table([{"sk": "DATE#2026-10-23", "word": None}]), "2026-10-24")
    assert lines[0].startswith("Mood read: unavailable")
    assert lines[1:] == ["Evening check-in: no answered evening in the last 7 days — absent. Say so; never infer a rating."]


# ── 4. mind-coach predictions are about the mind domain ──────────────────────────────────


def test_a_mind_call_graded_on_another_domain_is_refused():
    for metric in ("hrv", "recovery_score", "sleep_duration_hours", "weight_lbs", "total_protein_g", "steps", "hrv_7day_avg"):
        why = ps.out_of_scope("mind_coach", metric, metric, "As stress eases this will improve")
        assert why and "outside mind_coach's domain" in why, metric
    # A hint-less claim that names only another domain's measure is refused too.
    assert ps.out_of_scope("mind_coach", None, "", "Weight will drop two pounds by Friday")


def test_mind_domain_and_checkin_calls_are_kept():
    keep = [
        ("checkin stress", "His evening check-in stress will ease below 2 this week"),
        ("mood", "Mood will lift once the routine is back"),
        (None, "The cravings he rates in the evening will settle"),
        (None, "He will journal again before the weekend"),
        (None, "You'll feel more like yourself"),
    ]
    for hint, claim in keep:
        assert ps.out_of_scope("mind_coach", hint, "", claim) is None, claim


def test_other_coaches_are_unaffected():
    assert ps.out_of_scope("sleep_coach", "hrv", "hrv", "HRV will rise") is None
    assert ps.out_of_scope("nutrition_coach", None, "", "Mood will lift") is None


def test_the_state_updater_does_not_write_an_out_of_domain_mind_prediction(monkeypatch):
    import coach_state_updater as su
    import test_coach_state_updater as base

    t = base.FakeTable(liveness_pages=[{"Items": [{"hrv": v} for v in (60, 61, 62, 63, 64)]}])
    monkeypatch.setattr(su, "table", t)
    monkeypatch.setattr(su, "_cw", base.FakeCloudWatch())
    monkeypatch.setattr(
        su,
        "_call_haiku",
        lambda **k: base._extraction(
            predictions_made=[
                {"claim_natural": "HRV will improve over the next two weeks", "metric_hint": "hrv", "direction": "up"},
                {"claim_natural": "His evening stress will ease this week", "metric_hint": None},
            ]
        ),
    )
    su.lambda_handler(
        {"coach_id": "mind_coach", "output_text": "p1\n\np2", "output_type": "daily_brief", "generation_date": "2026-10-24"}, None
    )
    preds = [p for p in t.puts if str(p.get("sk", "")).startswith("PREDICTION#")]
    assert [p["claim_natural"] for p in preds] == ["His evening stress will ease this week"]
    assert preds[0]["status"] == "observation"  # kept, ungraded: nothing grades a mind call from the owner-only check-in
