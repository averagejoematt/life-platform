"""tests/test_coach_interaction_memory_533.py — #533 interaction memory,
pieces 1 & 3: the weekly compression sees field-note pushback interactions AND
resolved prediction outcomes.

Piece 2 (reader board Q&A -> COACH#{id}/INTERACTION#) already shipped with #531
and is pinned by tests/test_persona_core.py. Piece 2's field-note write path has
its own test file (tests/test_field_note_interaction_writeback.py). This file
covers the read/render side in coach_history_summarizer.py:
  - a field_note_pushback-typed INTERACTION# record renders distinctly from a
    board_qa one in the compression message
  - _gather_coach_state fetches recent resolved LEARNING# records (read-only,
    no new write path — coach_prediction_evaluator already writes them) and
    _build_compression_message turns them into a "Prediction Outcomes" section

All offline — pure function calls on synthetic state / a patched query fn.
"""

import os
import sys

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "coach"))

import coach_history_summarizer as chs  # noqa: E402


def _base_state():
    return {
        "outputs": [],
        "open_threads": [],
        "open_threads_total": 0,
        "active_predictions": [],
        "active_predictions_total": 0,
        "confidence_records": [],
        "relationship_state": None,
        "voice_state": None,
        "interactions": [],
        "learning_outcomes": [],
    }


# ── field-note pushback rendering ──────────────────────────────────────────


def test_field_note_pushback_interaction_renders_distinctly():
    state = _base_state()
    state["interactions"] = [
        {
            "sk": "INTERACTION#2026-05-11#fieldnote-2026-W20",
            "interaction_type": "field_note_pushback",
            "week": "2026-W20",
            "agreement": "disagree",
            "notes": "The HRV dip was illness, not travel.",
            "disputed": ["the travel framing"],
        }
    ]
    msg = chs._build_compression_message("mind_coach", state)
    assert "Matthew's field-note response" in msg
    assert "agreement=disagree" in msg
    assert "illness, not travel" in msg
    assert "Disputed: the travel framing" in msg


def test_board_qa_interaction_still_renders_as_before():
    state = _base_state()
    state["interactions"] = [
        {
            "sk": "INTERACTION#2026-05-11#ab12cd34",
            "interaction_type": "board_qa",
            "question": "Why is my HRV low this week?",
            "answer": "Likely the travel stretch you logged.",
            "grounded": True,
        }
    ]
    msg = chs._build_compression_message("sleep_coach", state)
    assert "A reader asked: Why is my HRV low this week?" in msg
    assert "You answered: Likely the travel stretch you logged." in msg


def test_no_interactions_renders_none_section():
    msg = chs._build_compression_message("sleep_coach", _base_state())
    assert "Reader Interactions & Field-Note Pushback: NONE" in msg


# ── prediction outcomes (LEARNING#) fold-in ────────────────────────────────


def _learning(status, subdomain="recovery", metric="hrv_ms", reason="reason text", date="2026-06-20"):
    return {
        "sk": f"LEARNING#{date}#pred-{status}",
        "coach_id": "training_coach",
        "date": date,
        "status": status,
        "subdomain": subdomain,
        "metric": metric,
        "reason": reason,
    }


def test_gather_coach_state_reads_learning_records():
    """_gather_coach_state fetches LEARNING# newest-first, bounded — the same
    recency-window contract as INTERACTION# and PREDICTION#."""
    calls = {}

    def _fake_query(pk, sk_prefix, scan_forward=True, limit=None, include_pilot=False, max_pages=None):
        calls[sk_prefix] = {"scan_forward": scan_forward, "limit": limit}
        if sk_prefix == "LEARNING#":
            return [_learning("confirmed"), _learning("refuted")]
        return []

    orig = chs._query_begins_with
    chs._query_begins_with = _fake_query
    orig_get = chs._get_item
    chs._get_item = lambda pk, sk: None
    try:
        state = chs._gather_coach_state("training_coach")
    finally:
        chs._query_begins_with = orig
        chs._get_item = orig_get

    assert calls["LEARNING#"]["scan_forward"] is False
    assert calls["LEARNING#"]["limit"] == chs.MAX_LEARNING_IN_PROMPT
    assert len(state["learning_outcomes"]) == 2


def test_prediction_outcomes_section_lists_confirmed_and_refuted():
    state = _base_state()
    state["learning_outcomes"] = [
        _learning("confirmed", reason="RHR trended down as predicted"),
        _learning("refuted", subdomain="sleep", metric="deep_sleep_pct", reason="No sustained improvement"),
    ]
    msg = chs._build_compression_message("training_coach", state)
    assert "## Prediction Outcomes (2 newest resolved)" in msg
    assert "CONFIRMED (recovery, hrv_ms): RHR trended down as predicted" in msg
    assert "REFUTED (sleep, deep_sleep_pct): No sustained improvement" in msg


def test_no_learning_outcomes_renders_none_section():
    msg = chs._build_compression_message("training_coach", _base_state())
    assert "## Prediction Outcomes: NONE" in msg


def test_compression_system_prompt_tells_haiku_to_reference_outcomes():
    assert "Resolved prediction outcomes" in chs.COMPRESSION_SYSTEM_PROMPT
    assert "I was wrong about" in chs.COMPRESSION_SYSTEM_PROMPT
    assert "Matthew's own pushback" in chs.COMPRESSION_SYSTEM_PROMPT


# ── acceptance sketch bullet 3: "at least the mind/nutrition/training coach
# briefs demonstrably reference a real interaction when one exists" ─────────
#
# The daily brief itself is generated by a live LLM call (out of scope to
# invoke here, and #533's budget note is explicit: no new generation calls).
# The deterministic proxy is the compression MESSAGE — the actual text hand
# each of these coaches' briefs is built from (COMPRESSED#latest, produced by
# compressing exactly this message) — so this pins that a real interaction is
# textually present in every one of the three named coaches' inputs whenever
# one exists, not just structurally present in the returned dict.


def test_mind_nutrition_training_briefs_see_a_real_interaction_when_one_exists():
    for coach_id in ("mind_coach", "nutrition_coach", "training_coach"):
        state = _base_state()
        state["interactions"] = [
            {
                "sk": "INTERACTION#2026-05-11#fieldnote-2026-W20",
                "interaction_type": "field_note_pushback",
                "week": "2026-W20",
                "agreement": "disagree",
                "notes": "I don't buy the caffeine-timing read this week.",
                "disputed": [],
            }
        ]
        state["learning_outcomes"] = [_learning("confirmed", reason="deload call paid off as predicted")]
        msg = chs._build_compression_message(coach_id, state)
        assert "caffeine-timing" in msg, f"{coach_id} brief input lost the field-note pushback"
        assert "deload call paid off as predicted" in msg, f"{coach_id} brief input lost the prediction outcome"


def test_windowing_still_fits_the_input_budget_with_learning_added():
    """#410's budget guard must still hold now that a 4th bounded section
    (learning_outcomes) rides in the same message."""
    state = _base_state()
    state["outputs"] = [
        {"sk": f"OUTPUT#2026-06-{d:02d}", "themes": ["recovery"], "content": "A weekly read. " * 20, "word_count": 400}
        for d in range(1, 21)
    ]
    state["learning_outcomes"] = [_learning("confirmed", date=f"2026-06-{d:02d}") for d in range(1, chs.MAX_LEARNING_IN_PROMPT + 1)]
    msg = chs._build_bounded_compression_message("training_coach", state)
    assert len(msg) <= chs.MAX_COMPRESSION_INPUT_CHARS
