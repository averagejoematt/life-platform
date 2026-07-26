"""tests/test_coach_calibration_1481.py — conversational self-calibration (#1481, ADR-141).

Coaches update their own read of Matthew from check-in answers: a bounded
CONFIDENCE# move (source=conversation) + a LEARNING# record
(channel=conversation) grounded BY ID in the verbatim CHECKIN# answer.

Covers every acceptance criterion:
  AC1 — a logged answer produces a confidence update + learning attributable
        to that answer's checkin_id (core + MCP tool end-to-end);
  AC2 — STANCE# regeneration inputs (track-record reduction + compression
        message + stance grounding message) incorporate conversation-channel
        learnings and DISTINGUISH them from data-derived ones;
  AC3 — get_coach_track_record / observatory surfaces show provenance
        (data vs conversation);
plus the ADR-141 rules: bounds (weight clamp, per-answer cap, idempotent
replay), grounding (excerpt must be a real substring; skip is never evidence),
the data path's provenance stamps + accumulator carry-forward, and the
public-surface privacy filter.

Hermetic — FakeDdbTable everywhere, no AWS, no LLM.
"""

import os
import sys

os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "coach"))
sys.path.insert(0, os.path.join(_REPO, "tests"))

import coach_calibration as ccal  # noqa: E402
import coach_checkin as cc  # noqa: E402
import coach_history_summarizer as chs  # noqa: E402
import coach_observatory_renderer as cobs  # noqa: E402
import coach_prediction_evaluator as cpe  # noqa: E402
from fakes import FakeDdbTable  # noqa: E402

import mcp.tools_coach_checkin as tcc  # noqa: E402
import mcp.tools_coach_intelligence as tci  # noqa: E402

ANSWER = "Honestly the evenings fell apart after the trip — I stopped winding down and just doomscrolled until midnight."


def _answered_item(coach_id="sleep", date="2026-07-20", uid="abcd1234", **over):
    item = {
        "pk": cc.checkin_pk(coach_id),
        "sk": f"CHECKIN#{date}#{uid}",
        "record_type": "coach_checkin",
        "coach_id": coach_id,
        "coach_name": "Dr. Lisa Park",
        "question": "How have the evenings before bed actually been feeling lately?",
        "status": cc.STATUS_ANSWERED,
        "answer": ANSWER,
        "asked_at": f"{date}T18:00:00Z",
        "answered_at": f"{date}T19:00:00Z",
        "provenance": "mcp",
    }
    item.update(over)
    return item


def _conditional_put_hook(table, item, **kwargs):
    """Emulate DynamoDB's attribute_not_exists conditional put."""
    if kwargs.get("ConditionExpression") and table._key_of(item) in table.store:
        raise Exception("ConditionalCheckFailedException: the conditional request failed")
    table.store[table._key_of(item)] = item


def _prefix_query_hook(table, **kwargs):
    """Serve begins_with(pk, prefix) queries from the store — enough for the
    per-answer cap probe (the only query the core module issues)."""
    values = getattr(kwargs.get("KeyConditionExpression"), "get_expression", lambda: None)()

    def _walk(expr, out):
        if expr is None:
            return
        vals = expr.get("values", ())
        for v in vals:
            if hasattr(v, "get_expression"):
                _walk(v.get_expression(), out)
            else:
                out.append(v)

    out = []
    _walk(values, out)
    strings = [v for v in out if isinstance(v, str)]
    pk = next((s for s in strings if s.startswith("COACH#")), None)
    prefix = next((s for s in strings if s.startswith("LEARNING#")), "")
    items = [it for (p, sk), it in table.store.items() if p == pk and str(sk).startswith(prefix)]
    return {"Items": items}


def _fake_table(rows=None):
    return FakeDdbTable(rows=rows or [], put_item_hook=_conditional_put_hook, query_hook=_prefix_query_hook)


def _apply(table, item=None, **over):
    kwargs = {
        "subdomain": "sleep_quality",
        "direction": "down",
        "takeaway": "The wind-down routine collapsed after travel — evenings are the lever, not bedtime itself.",
    }
    kwargs.update(over)
    return ccal.apply_conversation_calibration(table, item or _answered_item(), **kwargs)


# ── AC1: answer → confidence update + learning, attributable by checkin_id ──


def test_answer_produces_learning_and_confidence_attributable_to_checkin():
    table = _fake_table([_answered_item()])
    out = _apply(table)
    assert out["status"] == "saved"

    learning = table.store[(cc.checkin_pk("sleep"), out["learning_sk"])]
    assert learning["channel"] == "conversation"
    assert learning["checkin_id"] == "CHECKIN#2026-07-20#abcd1234"  # attributable BY ID
    assert learning["status"] == "insight"  # never confirmed/refuted
    assert learning["answer_quote"] and learning["answer_quote"] in ANSWER  # verbatim (ADR-104)
    assert learning["evaluation_type"] == "conversation_calibration"

    conf = table.store[(cc.checkin_pk("sleep"), "CONFIDENCE#sleep_quality")]
    assert conf["source"] == "conversation"
    assert conf["last_checkin_id"] == "CHECKIN#2026-07-20#abcd1234"
    # direction=down from the uninformed prior Beta(1,1) with default weight 0.5
    assert float(conf["beta_param"]) == 1.5 and float(conf["alpha"]) == 1.0
    assert out["confidence"]["mean_before"] == 0.5
    assert out["confidence"]["mean_after"] == round(1.0 / 2.5, 3)


def test_learning_sk_is_deterministic_per_answer_and_subdomain():
    sk = ccal.calibration_learning_sk("CHECKIN#2026-07-20#abcd1234", "Sleep Quality!")
    assert sk == "LEARNING#2026-07-20#conv-abcd1234-sleep_quality"
    assert ccal.calibration_learning_sk("BADKEY", "x") is None


# ── ADR-141 bounds ───────────────────────────────────────────────────────────


def test_confidence_move_is_bounded_to_one_pseudo_observation():
    table = _fake_table([_answered_item()])
    out = _apply(table, direction="up", weight=5.0)  # tries a ±3-tier swing
    conf = table.store[(cc.checkin_pk("sleep"), "CONFIDENCE#sleep_quality")]
    assert float(conf["alpha"]) == 2.0  # clamped to MAX_WEIGHT_PER_ANSWER=1.0
    assert out["confidence"]["weight"] == 1.0


def test_replay_is_idempotent_never_double_counted():
    table = _fake_table([_answered_item()])
    first = _apply(table)
    again = _apply(table)
    assert first["status"] == "saved"
    assert again["status"] == "already_recorded" and again["confidence_moved"] is False
    conf = table.store[(cc.checkin_pk("sleep"), "CONFIDENCE#sleep_quality")]
    assert float(conf["beta_param"]) == 1.5  # moved exactly once


def test_per_answer_subdomain_cap():
    table = _fake_table([_answered_item()])
    assert _apply(table, subdomain="sleep_quality")["status"] == "saved"
    assert _apply(table, subdomain="sleep_consistency")["status"] == "saved"
    third = _apply(table, subdomain="deep_sleep")
    assert "calibration bound" in third["error"]


def test_hold_records_learning_without_confidence_move():
    table = _fake_table([_answered_item()])
    out = _apply(table, direction="hold")
    assert out["status"] == "saved" and out["confidence_moved"] is False
    assert (cc.checkin_pk("sleep"), "CONFIDENCE#sleep_quality") not in table.store


# ── ADR-104 grounding ────────────────────────────────────────────────────────


def test_skip_and_open_checkins_are_never_evidence():
    table = _fake_table()
    skipped = _answered_item(status=cc.STATUS_SKIPPED, answer="")
    assert "error" in _apply(table, item=skipped)
    open_q = _answered_item(status=cc.STATUS_OPEN, answer="")
    assert "error" in _apply(table, item=open_q)
    assert not table.puts


def test_excerpt_must_be_a_real_substring_of_the_answer():
    table = _fake_table([_answered_item()])
    bad = _apply(table, answer_excerpt="I sleep great, no issues at all")
    assert "not a substring" in bad["error"]

    good = _apply(table, answer_excerpt="stopped winding down and just   DOOMSCROLLED")  # ws/case-insensitive
    assert good["status"] == "saved"
    assert good["answer_quote"] == "stopped winding down and just   DOOMSCROLLED"


# ── AC2: STANCE#/compression inputs distinguish conversation learnings ──────


def _conv_learning(date="2026-07-20", subdomain="sleep_quality"):
    return {
        "sk": f"LEARNING#{date}#conv-abcd1234-{subdomain}",
        "date": date,
        "channel": "conversation",
        "status": "insight",
        "subdomain": subdomain,
        "takeaway": "Evenings are the lever — the routine collapsed after travel.",
        "answer_quote": "I stopped winding down and just doomscrolled",
        "checkin_id": "CHECKIN#2026-07-20#abcd1234",
        "confidence_direction": "down",
    }


def test_track_record_summary_separates_conversation_from_verdicts():
    learning = [
        {"sk": "LEARNING#2026-06-20#a", "verdict": "confirmed", "claim_natural": "sleep would stabilize"},
        {"sk": "LEARNING#2026-06-18#b", "verdict": "refuted", "claim": "deep sleep up"},
        _conv_learning(),
    ]
    conf = [
        {"subdomain": "duration", "mean_confidence": 0.72},
        {"subdomain": "sleep_quality", "mean_confidence": 0.4, "source": "conversation"},
    ]
    t = chs._summarize_track_record(learning, conf)
    # hit rate stays data-derived: the conversation record is not a verdict
    assert (t["confirmed"], t["refuted"], t["decided"]) == (1, 1, 2)
    assert all(r["claim"] != "" or r["verdict"] for r in t["recent"])
    assert len(t["recent"]) == 2  # conversation learning is NOT in the data recents
    cl = t["conversation_learnings"]
    assert cl["count"] == 1
    assert cl["recent"][0]["checkin_id"] == "CHECKIN#2026-07-20#abcd1234"
    assert cl["recent"][0]["his_words"] == "I stopped winding down and just doomscrolled"
    assert t["confidence_provenance"] == {"duration": "data", "sleep_quality": "conversation"}


def test_compression_message_renders_conversation_learnings_distinctly():
    state = {
        "outputs": [],
        "open_threads": [],
        "open_threads_total": 0,
        "active_predictions": [],
        "active_predictions_total": 0,
        "confidence_records": [],
        "relationship_state": None,
        "voice_state": None,
        "interactions": [],
        "learning_outcomes": [
            {"sk": "LEARNING#2026-06-20#a", "status": "confirmed", "subdomain": "sleep", "reason": "deload call paid off"},
            _conv_learning(),
        ],
    }
    msg = chs._build_compression_message("sleep_coach", state)
    assert "## Prediction Outcomes (1 newest resolved)" in msg  # conversation not counted here
    assert "## Conversation Learnings (1 newest" in msg
    assert "NOT data-derived" in msg
    assert 'grounded in his answer: "I stopped winding down and just doomscrolled"' in msg


def test_stance_grounding_message_carries_and_flags_conversation_learnings():
    track = chs._summarize_track_record([_conv_learning()], [])
    msg = chs._build_stance_message("sleep_coach", {"summary": "s"}, track, None)
    assert '"conversation_learnings"' in msg
    assert "Evenings are the lever" in msg
    assert "distinct from your data-derived prediction verdicts" in msg


# ── AC1 + AC3: MCP tool end-to-end + track-record provenance ────────────────


def test_tool_log_coach_calibration_end_to_end(monkeypatch):
    fake = _fake_table([_answered_item()])
    monkeypatch.setattr(tcc, "_table_ref", fake)
    monkeypatch.setattr(cc, "_cycle_cache", {"value": 10, "read": True})

    out = tcc.tool_log_coach_calibration(
        {
            "checkin_id": "CHECKIN#2026-07-20#abcd1234",
            "coach_id": "sleep",
            "subdomain": "sleep_quality",
            "direction": "down",
            "takeaway": "The wind-down routine collapsed after travel.",
        }
    )
    assert out["status"] == "saved"
    assert out["checkin_id"] == "CHECKIN#2026-07-20#abcd1234"
    assert out["channel"] == "conversation"
    assert "channel=conversation" in out["message"]
    learning = fake.store[(cc.checkin_pk("sleep"), out["learning_sk"])]
    assert learning["cycle"] == 10
    conf = fake.store[(cc.checkin_pk("sleep"), "CONFIDENCE#sleep_quality")]
    assert conf["source"] == "conversation"


def test_tool_rejects_skips_and_unknown_checkins(monkeypatch):
    fake = _fake_table([_answered_item(status=cc.STATUS_SKIPPED, answer="", uid="ffff0000")])
    monkeypatch.setattr(tcc, "_table_ref", fake)
    out = tcc.tool_log_coach_calibration(
        {"checkin_id": "CHECKIN#2026-07-20#ffff0000", "coach_id": "sleep", "subdomain": "sleep", "direction": "up", "takeaway": "x"}
    )
    assert "skip is a boundary" in out["error"]
    missing = tcc.tool_log_coach_calibration(
        {"checkin_id": "CHECKIN#2026-07-20#deadbeef", "coach_id": "sleep", "subdomain": "sleep", "direction": "up", "takeaway": "x"}
    )
    assert "not found" in missing["error"]


def test_get_coach_track_record_shows_provenance(monkeypatch):
    rows = [
        {"pk": "COACH#sleep_coach", "sk": "LEARNING#2026-07-19#a", "status": "confirmed", "subdomain": "sleep", "metric": "sleep_score"},
        {"pk": "COACH#sleep_coach", "sk": "LEARNING#2026-07-18#b", "status": "refuted", "subdomain": "sleep", "metric": "sleep_score"},
        {"pk": "COACH#sleep_coach", **_conv_learning()},
    ]
    fake = FakeDdbTable(rows=rows)
    monkeypatch.setattr(tci, "table", fake)
    out = tci.tool_get_coach_track_record({"coach_id": "sleep", "days": 30})
    assert out["by_channel"] == {"data": 2, "conversation": 1}
    assert out["decided_count"] == 2 and out["hit_rate_pct"] == 50.0  # conversation never in the hit rate
    assert out["conversation_learnings"]["count"] == 1
    recent_conv = out["conversation_learnings"]["recent"][0]
    assert recent_conv["checkin_id"] == "CHECKIN#2026-07-20#abcd1234"
    assert all(r["channel"] == "data" for r in out["recent_evaluations"])


# ── AC3: observatory provenance helpers ──────────────────────────────────────


def test_observatory_confidence_provenance_counts():
    recs = [{"subdomain": "a"}, {"subdomain": "b", "source": "conversation"}, {"subdomain": "c", "source": "data"}]
    assert cobs._confidence_provenance(recs) == {"data": 2, "conversation": 1}
    assert cobs._confidence_provenance([]) == {"data": 0, "conversation": 0}


def test_observatory_tally_excludes_conversation_from_verdicts():
    items = [
        {"status": "confirmed"},
        {"status": "refuted"},
        {"status": "insight", "channel": "conversation"},
        {"status": "confirmed", "channel": "data"},
    ]
    counts, conv = cobs._tally_learning_statuses(items)
    assert counts["confirmed"] == 2 and counts["refuted"] == 1
    assert conv == 1


# ── data-path provenance stamps + accumulator carry-forward ─────────────────


def test_evaluator_confidence_stamps_data_source_and_carries_accumulators(monkeypatch):
    from decimal import Decimal

    existing = {
        "pk": "COACH#sleep_coach",
        "sk": "CONFIDENCE#sleep_quality",
        "alpha": Decimal("2.5"),
        "beta_param": Decimal("1.5"),
        "conversation_alpha": Decimal("0.5"),
        "conversation_beta": Decimal("0.5"),
    }
    fake = FakeDdbTable(rows=[existing])
    monkeypatch.setattr(cpe, "table", fake)
    cpe._update_bayesian_confidence("sleep_coach", "sleep_quality", "success")
    written = fake.puts[-1]
    assert written["source"] == "data"
    assert float(written["alpha"]) == 3.5
    assert float(written["conversation_alpha"]) == 0.5  # carried forward, not erased
    assert float(written["conversation_beta"]) == 0.5


def test_evaluator_learning_record_stamps_data_channel(monkeypatch):
    fake = FakeDdbTable()
    monkeypatch.setattr(cpe, "table", fake)
    cpe._write_learning_record("sleep_coach", "2026-07-20", {"prediction_id": "p1", "status": "confirmed", "subdomain": "sleep"})
    assert fake.puts[-1]["channel"] == "data"


# ── ADR-141 privacy: public surface never renders conversation learnings ────


def test_public_track_record_filters_conversation_learnings(monkeypatch):
    sys.path.insert(0, os.path.join(_REPO, "lambdas", "web"))
    from web import site_api_coach as capi

    rows = [
        {"pk": "COACH#sleep_coach", "sk": "LEARNING#2026-07-19#a", "status": "confirmed", "metric": "sleep_score", "reason": "ok"},
        # adversarial: a conversation learning that ALSO carries a decided-looking status
        {"pk": "COACH#sleep_coach", **_conv_learning(), "status": "confirmed", "reason": ANSWER},
    ]
    fake = FakeDdbTable(rows=rows)
    monkeypatch.setattr(capi, "table", fake)
    out = capi._track_record("sleep_coach")
    assert out["confirmed"] == 1 and out["decided"] == 1
    assert all("doomscrolled" not in str(r) for r in out["recent"])
