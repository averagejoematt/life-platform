"""tests/test_horizons_calibration_1708.py — the Horizons feedback loop (#1708, epic #1686 S4).

Pins the three acceptance criteria, all offline (no Bedrock, no DynamoDB, no network):

  AC1 — a reaction to a pick enriches the journal corpus (Mind pillar / coach signal)
        with `channel` provenance: it rides the EXISTING conversational enrichment
        sweep (#1577 — no second pipeline, #1572) as the distinct
        ``prescription_reaction`` channel, and the write carries which pick it was
        about (enriched_prescription_week / _curator) alongside the standard stamps.
  AC2 — the reading profile updates from the reaction so future picks calibrate: a
        deterministic ledger on READING#PROFILE/CURRENT (counts, rates with n, honest
        nulls — never a model verdict, ADR-104/105), refreshed on answer AND on the
        6:30 AM enrichment cadence, surfaced to the curating coach on
        get_horizons + curate_horizon's dry-run preview.
  AC3 — personal feedback is NOT auto-published, fail-closed: no verbatim text ever
        enters the ledger, the ledger is a registered PRIVATE profile field, the
        public Horizons card carries nothing from S4, and the only door to a public
        surface (`is_publishable_reaction`) is a positive match on BOTH an explicit
        owner consent tier AND a CLEARED #1673 sensitivity verdict.
"""

from __future__ import annotations

import json
import os

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")  # mcp.config requires these at import
os.environ.setdefault("USER_ID", "matthew")

import pytest  # noqa: E402
from ai import conversation_enrichment as ce  # noqa: E402
from coach import coach_checkin as cc  # noqa: E402
from reading import (  # noqa: E402
    horizons_calibration as hc,
    horizons_verify,
    reading_store as rs,
    reading_visibility as rv,
)
from reading_fakes import FakeTable  # noqa: E402
from web import site_api_reading as sar  # noqa: E402

from mcp import tools_coach_checkin as tcc, tools_reading as tr  # noqa: E402

# ── fixtures ─────────────────────────────────────────────────────────────────


class UpdatableFakeTable(FakeTable):
    """FakeTable + the minimal `SET a = :a, b = :b` update_item the MCP write path uses."""

    def update_item(self, Key, UpdateExpression, ExpressionAttributeValues=None, ExpressionAttributeNames=None, **kw):
        item = self.store.setdefault((Key["pk"], Key["sk"]), dict(Key))
        names = ExpressionAttributeNames or {}
        for assignment in UpdateExpression.removeprefix("SET ").split(","):
            lhs, rhs = (part.strip() for part in assignment.split("=", 1))
            item[names.get(lhs, lhs)] = (ExpressionAttributeValues or {})[rhs]
        return {}


@pytest.fixture()
def fake_table(monkeypatch):
    t = UpdatableFakeTable()
    monkeypatch.setattr(rs, "table", t)
    monkeypatch.setattr(tr, "table", t)
    monkeypatch.setattr(tcc, "_table_ref", t)
    monkeypatch.setattr(sar.reading_store, "table", t)
    return t


def _ok_fetch(url, timeout):
    return 200, b"<html><body>" + b"x" * 900 + b"</body></html>"


def _pick(week, *, url="https://hubermanlab.com/x", fmt="podcast", tag="experiment-relevant", follow_up=None):
    pick = {
        "week": week,
        "format": fmt,
        "url": url,
        "title": f"Pick {week}",
        "source": "Huberman Lab",
        "rationale_tag": tag,
        "curator": "mind",
    }
    if follow_up:
        pick["follow_up"] = follow_up
    return pick


def _reaction(sk="CHECKIN#2026-07-27#aaaa1111", *, answer="", status="open", **extra):
    item = {
        "pk": cc.checkin_pk("mind"),
        "sk": sk,
        "coach_id": "mind",
        "coach_name": "the Mind coach",
        "question": "Did that episode land?",
        "status": status,
        "generated_by": "prescription_followup",
        "prescription_week": "2026-W31",
        "prescription_curator": "mind",
    }
    if answer:
        item["answer"] = answer
    item.update(extra)
    return item


LONG_ANSWER = "It actually reframed how I think about the evening wind-down, and I tried it two nights running."


# ══════════════════════════════════════════════════════════════════════════════
# AC1 — channel provenance on the EXISTING enrichment path (no second pipeline)
# ══════════════════════════════════════════════════════════════════════════════
def test_prescription_followup_gets_its_own_channel():
    assert ce.checkin_channel(_reaction(answer=LONG_ANSWER, status="answered")) == ce.CHANNEL_PRESCRIPTION_REACTION
    plain = {"pk": cc.checkin_pk("mind"), "sk": "CHECKIN#2026-07-27#b", "answer": "x", "generated_by": "bedrock"}
    assert ce.checkin_channel(plain) == ce.CHANNEL_COACH_CHECKIN
    assert ce.checkin_channel({}) == ce.CHANNEL_COACH_CHECKIN  # unstamped legacy rows stay put


def test_channel_is_in_the_declared_policy_vocabulary():
    assert ce.CHANNEL_PRESCRIPTION_REACTION in ce.CHANNELS
    assert ce.CHANNEL_PRESCRIPTION_REACTION == hc.REACTION_CHANNEL  # one literal, two modules
    assert ce.CHANNEL_PRESCRIPTION_REACTION in ce.enrichment_policy()["channels"]
    # inherits the analysis-only scope unchanged — it moves no scoring
    assert ce.enrichment_policy()["scope"] == "analysis_only"
    assert ce.enrichment_policy()["moves_character_scoring"] is False


def test_collect_routes_the_reaction_to_its_channel(monkeypatch):
    row = _reaction(answer=LONG_ANSWER, status="answered")
    monkeypatch.setattr(ce, "_query_between", lambda t, pk, lo, hi: [row] if pk == cc.checkin_pk("mind") else [])
    got = ce.collect_conversational_items(object(), "2026-07-20", "2026-07-31", coach_ids=["mind"])
    assert len(got) == 1
    assert got[0]["channel"] == ce.CHANNEL_PRESCRIPTION_REACTION
    assert got[0]["text"] == LONG_ANSWER  # verbatim answer is what grounding runs against
    assert "2026-W31" in got[0]["context"] and "Horizons" in got[0]["context"]


def test_apply_enrichment_stamps_channel_and_which_pick():
    """The Mind-pillar/coach-signal consumer can attribute the signal to its pick."""

    class Recorder:
        def __init__(self):
            self.updates = []

        def update_item(self, **kw):
            self.updates.append(kw)

    table = Recorder()
    item = _reaction(answer=LONG_ANSWER, status="answered")
    assert ce.apply_enrichment(table, item, ce.CHANNEL_PRESCRIPTION_REACTION, {"sentiment": "positive"}, LONG_ANSWER) is True
    vals = table.updates[0]["ExpressionAttributeValues"]
    assert vals[":enriched_channel"] == "prescription_reaction"
    assert vals[":enriched_prescription_week"] == "2026-W31"
    assert vals[":enriched_prescription_curator"] == "mind"
    assert vals[":enriched_scope"] == "analysis_only"  # the #1577 gate/scope, unchanged
    assert vals[":enriched_sentiment"] == "positive"


def test_plain_checkin_gets_no_prescription_stamps():
    class Recorder:
        def __init__(self):
            self.updates = []

        def update_item(self, **kw):
            self.updates.append(kw)

    table = Recorder()
    item = {"pk": cc.checkin_pk("mind"), "sk": "CHECKIN#2026-07-27#c"}
    ce.apply_enrichment(table, item, ce.CHANNEL_COACH_CHECKIN, {"sentiment": "neutral"}, LONG_ANSWER)
    names = set(table.updates[0]["ExpressionAttributeNames"].values())
    assert not {n for n in names if n.startswith("enriched_prescription")}


# ══════════════════════════════════════════════════════════════════════════════
# AC2 — the deterministic reaction ledger
# ══════════════════════════════════════════════════════════════════════════════
def test_reaction_signal_reads_the_row_deterministically():
    assert hc.reaction_signal(None)["state"] == hc.STATE_NO_FOLLOWUP
    assert hc.reaction_signal(_reaction())["state"] == hc.STATE_UNANSWERED
    assert hc.reaction_signal(_reaction(status="skipped", skipped=True))["state"] == hc.STATE_SKIPPED

    engaged = hc.reaction_signal(_reaction(answer=LONG_ANSWER, status="answered"))
    assert engaged["state"] == hc.STATE_ANSWERED and engaged["engaged"] is True

    terse = hc.reaction_signal(_reaction(answer="yeah it was fine", status="answered"))
    assert terse["state"] == hc.STATE_ANSWERED and terse["engaged"] is False  # answered != engaged


def test_valence_absence_is_unknown_never_neutral():
    """ADR-104: an un-enriched reaction has NO coded sentiment — that is 'unknown'."""
    assert hc.reaction_signal(_reaction(answer=LONG_ANSWER, status="answered"))["valence"] == hc.VALENCE_UNKNOWN
    coded = _reaction(answer=LONG_ANSWER, status="answered", enriched_sentiment="negative")
    assert hc.reaction_signal(coded)["valence"] == "negative"
    junk = _reaction(answer=LONG_ANSWER, status="answered", enriched_sentiment="ecstatic")
    assert hc.reaction_signal(junk)["valence"] == hc.VALENCE_UNKNOWN  # only the declared vocabulary


def test_pick_category_matches_the_garden_and_is_honest_off_garden():
    assert hc.pick_category({"url": "https://www.hubermanlab.com/episode/1"}) == "health"
    assert hc.pick_category({"url": "https://blog.nesslabs.com/x"}) == "mind"  # subdomain still matches
    assert hc.pick_category({"url": "https://somewhere-unknown.example/x"}) == "off-garden"
    assert hc.pick_category({"url": "", "source": "Quanta Magazine"}) == "science"  # name fallback


def test_ledger_counts_states_and_gates_rates_on_n():
    pairs = [
        (_pick("2026-W31"), _reaction(answer=LONG_ANSWER, status="answered", enriched_sentiment="positive")),
        (_pick("2026-W30"), _reaction(answer="fine", status="answered")),
        (_pick("2026-W29"), _reaction(status="skipped", skipped=True)),
        (_pick("2026-W28"), None),  # no follow-up attached — a valid pick
    ]
    cal = hc.build_calibration(pairs, now="2026-07-27T00:00:00Z")
    assert cal["n_picks"] == 4 and cal["n_followups"] == 3
    assert cal["n_reactions"] == 2 and cal["n_skipped"] == 1
    assert cal["method"] == "deterministic_counts"

    health = cal["by_category"]["health"]
    assert health["picks"] == 4 and health["followed_up"] == 3 and health["engaged"] == 1
    assert health["engagement_rate"] == round(1 / 3, 3)
    assert health["sentiment"]["positive"] == 1 and health["sentiment"][hc.VALENCE_UNKNOWN] == 1
    # n=3 clears the signal gate; everything below it is deliberately absent
    ranked = {(r["dimension"], r["key"]) for r in cal["signal"]["ranked"]}
    assert ("by_category", "health") in ranked
    assert cal["signal"]["min_n"] == hc.MIN_N_FOR_SIGNAL


def test_empty_ledger_reports_absence_not_zero():
    cal = hc.build_calibration([], now="2026-07-27T00:00:00Z")
    assert cal["n_picks"] == 0 and cal["n_reactions"] == 0
    assert cal["confidence"] == "none"
    assert cal["totals"]["engagement_rate"] is None  # never 0.0 — that would be a claim
    assert cal["signal"]["ranked"] == []
    assert "No reaction has landed yet" in cal["note"]

    # a pick with one un-engaged reaction is still below the n-gate: data, not preference
    one = hc.build_calibration([(_pick("2026-W31"), _reaction(answer=LONG_ANSWER, status="answered"))])
    assert one["confidence"] == "very-low" and one["signal"]["ranked"] == []


def test_refresh_writes_the_ledger_onto_the_profile_and_is_idempotent(fake_table):
    rs.put_horizon_pick(_pick("2026-W31", follow_up={"surfaced_checkin_sk": "CHECKIN#2026-07-27#aaaa1111", "surfaced_coach": "mind"}))
    rs.put_horizon_pick(_pick("2026-W30"))
    fake_table.put_item(Item=_reaction(answer=LONG_ANSWER, status="answered"))

    first = hc.refresh(fake_table, now="2026-07-27T00:00:00Z")
    assert first["n_picks"] == 2 and first["n_reactions"] == 1
    stored = rs.get_horizons_calibration()
    assert stored["n_reactions"] == 1 and stored["version"] == hc.CALIBRATION_VERSION

    second = hc.refresh(fake_table, now="2026-07-27T00:00:00Z")
    assert second == first  # full recompute ⇒ idempotent
    profile = rs.get_profile()
    assert set(profile) >= {hc.PROFILE_FIELD}


def test_refresh_reads_only_the_rows_the_picks_point_at(fake_table):
    """Bounded: one GetItem per pick that actually surfaced a follow-up. No scan."""
    calls = []
    original = fake_table.get_item
    fake_table.get_item = lambda Key: (calls.append(Key["sk"]), original(Key))[1]  # type: ignore[method-assign]

    rs.put_horizon_pick(_pick("2026-W31", follow_up={"surfaced_checkin_sk": "CHECKIN#2026-07-27#aaaa1111", "surfaced_coach": "mind"}))
    rs.put_horizon_pick(_pick("2026-W30"))  # no follow-up
    rs.put_horizon_pick(_pick("2026-W29", follow_up={"type": "question", "text": "no checkin was surfaced"}))
    calls.clear()
    hc.refresh(fake_table)
    # exactly one reaction read (plus the profile read the ledger write merges onto)
    assert [sk for sk in calls if sk.startswith("CHECKIN#")] == ["CHECKIN#2026-07-27#aaaa1111"]


def test_answering_a_reaction_recalibrates_immediately(fake_table, monkeypatch):
    """The MCP write path: Matthew's answer lands, and the ledger moves in the same call."""
    monkeypatch.setattr(horizons_verify, "_urllib_fetch", _ok_fetch)
    curated = tr.tool_curate_horizon(
        {
            "url": "https://hubermanlab.com/episode/1",
            "title": "A Real Episode",
            "format": "podcast",
            "rationale_tag": "experiment-relevant",
            "week": "2026-W31",
            "dry_run": False,
            "follow_up_question": "Did that episode land?",
        }
    )
    checkin_id = curated["pick"]["follow_up"]["surfaced_checkin_sk"]

    out = tcc.tool_log_coach_checkin({"checkin_id": checkin_id, "answer": LONG_ANSWER, "coach_id": "mind"})
    assert out["outcome"] == "answered"
    assert out["horizons_calibration"]["n_reactions"] == 1
    cal = rs.get_horizons_calibration()
    assert cal["n_picks"] == 1 and cal["n_reactions"] == 1
    assert cal["by_rationale_tag"]["experiment-relevant"]["answered"] == 1


def test_a_skip_also_recalibrates(fake_table, monkeypatch):
    """ADR-104: an unanswered pick is signal about the PICK, not a gap to be ignored."""
    monkeypatch.setattr(horizons_verify, "_urllib_fetch", _ok_fetch)
    curated = tr.tool_curate_horizon(
        {
            "url": "https://hubermanlab.com/episode/2",
            "title": "Another Episode",
            "format": "podcast",
            "rationale_tag": "topical",
            "week": "2026-W32",
            "dry_run": False,
            "follow_up_question": "Worth your time?",
        }
    )
    out = tcc.tool_log_coach_checkin({"checkin_id": curated["pick"]["follow_up"]["surfaced_checkin_sk"], "skip": True})
    assert out["outcome"] == "skipped" and out["horizons_calibration"]["n_reactions"] == 0
    assert rs.get_horizons_calibration()["n_skipped"] == 1


def test_a_plain_checkin_does_not_touch_the_ledger(fake_table):
    fake_table.put_item(
        Item={
            "pk": cc.checkin_pk("mind"),
            "sk": "CHECKIN#2026-07-27#plain001",
            "coach_id": "mind",
            "status": "open",
            "generated_by": "bedrock",
        }
    )
    out = tcc.tool_log_coach_checkin({"checkin_id": "CHECKIN#2026-07-27#plain001", "answer": LONG_ANSWER, "coach_id": "mind"})
    assert "horizons_calibration" not in out
    assert rs.get_horizons_calibration() is None


def test_the_curating_coach_reads_the_ledger_before_the_next_pick(fake_table, monkeypatch):
    monkeypatch.setattr(horizons_verify, "_urllib_fetch", _ok_fetch)
    hc.refresh(fake_table)  # seed an (empty, honest) ledger

    got = tr.tool_get_horizons({})
    assert got["calibration"]["n_picks"] == 0  # present even in the empty state

    preview = tr.tool_curate_horizon(
        {"url": "https://hubermanlab.com/e", "title": "T", "format": "podcast", "rationale_tag": "topical", "dry_run": True}
    )
    assert preview["status"] == "preview"
    assert preview["calibration"] is not None and "min_n" in preview["calibration_how_to_use"]


def test_enrichment_lambda_refreshes_the_ledger_on_its_own_cadence(fake_table, monkeypatch):
    """No second pipeline: the recompute rides the 6:30 AM journal-enrichment pass."""
    import ingestion.journal_enrichment_lambda as jel

    monkeypatch.setattr(jel, "table", fake_table)
    rs.put_horizon_pick(_pick("2026-W31"))
    summary = jel._refresh_horizons_calibration()
    assert summary == {"n_picks": 1, "n_reactions": 0, "confidence": "none"}
    assert rs.get_horizons_calibration()["n_picks"] == 1


# ══════════════════════════════════════════════════════════════════════════════
# AC3 — fail-closed privacy: personal feedback is never auto-published
# ══════════════════════════════════════════════════════════════════════════════
def test_the_ledger_carries_no_verbatim_reaction_text():
    secret = "I relapsed on Tuesday and the essay just made me feel worse about it."
    cal = hc.build_calibration([(_pick("2026-W31"), _reaction(answer=secret, status="answered", enriched_sentiment="negative"))])
    blob = json.dumps(cal)
    assert secret not in blob
    for word in ("relapsed", "Tuesday", "worse"):
        assert word not in blob
    # no free-text carrier anywhere in the ledger — counts, rates and labels only
    for key in ("answer", "question", "notable_quote", "quote", "text"):
        assert f'"{key}"' not in blob


def test_the_ledger_is_a_registered_private_profile_field():
    assert hc.PROFILE_FIELD in rv.PRIVATE_FIELDS[rv.READING_PROFILE]
    projected = rv.project_public(rv.READING_PROFILE, {"wheelDistribution": {"fiction": 2}, hc.PROFILE_FIELD: {"n_reactions": 3}})
    assert projected == {"wheelDistribution": {"fiction": 2}}


def test_the_public_horizons_card_carries_nothing_from_s4(fake_table):
    pick = _pick("2026-W31")
    pick.update(
        {
            "follow_up": {"surfaced_checkin_sk": "CHECKIN#x", "surfaced_coach": "mind", "text": "did it land?"},
            "reaction": "this is a private reaction that must never ship",
            "horizons": {"n_reactions": 3},
        }
    )
    rs.put_horizon_pick(pick)
    body = json.loads(sar.handle_horizons()["body"])
    card = body["items"][0]
    assert card["week"] == "2026-W31"
    assert "reaction" not in card and "follow_up" not in card and "horizons" not in card
    assert "private reaction" not in json.dumps(body)


def test_a_reaction_is_not_publishable_by_default():
    """Fail-closed on EVERY missing precondition — the Social Membrane posture."""
    from privacy import broadcast_sensitivity_gate as gate, diary_consent

    answered = _reaction(answer=LONG_ANSWER, status="answered")
    assert hc.is_publishable_reaction(answered) is False  # no consent, no verdict
    assert hc.is_publishable_reaction(None) is False
    # consent alone is not enough
    consented = dict(answered, **{diary_consent.CONSENT_FIELD: diary_consent.TIER_ALLUDE})
    assert hc.is_publishable_reaction(consented) is False
    # a HELD verdict + consent is still not publishable
    held = dict(consented, **gate.sensitivity_attrs(gate.Verdict(gate.SENSITIVITY_HELD, ("off_topic",), "r", 0.0)))
    assert hc.is_publishable_reaction(held) is False
    # cleared + consent is the ONLY publishable combination
    cleared = dict(consented, **{gate.STATUS_ATTR: gate.SENSITIVITY_CLEARED})
    assert hc.is_publishable_reaction(cleared) is True
    # and it must actually be a prescription reaction, not any old row
    assert hc.is_publishable_reaction(dict(cleared, generated_by="bedrock")) is False


def test_capture_stamps_a_held_verdict_deterministically():
    from privacy import broadcast_sensitivity_gate as gate

    attrs = hc.sensitivity_attrs_for_reaction(LONG_ANSWER)
    assert attrs[gate.STATUS_ATTR] == gate.SENSITIVITY_HELD  # no classifier wired ⇒ cannot vouch ⇒ hold
    vice = hc.sensitivity_attrs_for_reaction("smoked zzq after listening to it")
    assert vice[gate.STATUS_ATTR] == gate.SENSITIVITY_HELD
    assert gate.CATEGORY_VICE in vice[gate.CATEGORIES_ATTR]  # deterministic, offline, always on


def test_the_stamp_lands_on_the_stored_reaction(fake_table, monkeypatch):
    from privacy import broadcast_sensitivity_gate as gate

    monkeypatch.setattr(horizons_verify, "_urllib_fetch", _ok_fetch)
    curated = tr.tool_curate_horizon(
        {
            "url": "https://hubermanlab.com/episode/3",
            "title": "Third",
            "format": "podcast",
            "rationale_tag": "topical",
            "week": "2026-W33",
            "dry_run": False,
            "follow_up_question": "Did it land?",
        }
    )
    sk = curated["pick"]["follow_up"]["surfaced_checkin_sk"]
    tcc.tool_log_coach_checkin({"checkin_id": sk, "answer": LONG_ANSWER, "coach_id": "mind"})
    stored = fake_table.get_item(Key={"pk": cc.checkin_pk("mind"), "sk": sk})["Item"]
    assert stored["answer"] == LONG_ANSWER  # verbatim, ADR-104
    assert stored[gate.STATUS_ATTR] == gate.SENSITIVITY_HELD
    assert hc.is_publishable_reaction(stored) is False
