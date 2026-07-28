"""test_confidence_sample_size_honesty_1787.py — `n` on a CONFIDENCE# row is a
GRADED-PREDICTION count (ADR-105 honest n, ADR-141 §3 channel split).

#1787: `coach_calibration` folds CONVERSATIONAL pseudo-observations (fractional
weights 0.1–1.0) into the SAME Beta the graded-prediction path increments, then wrote
`sample_size = int(alpha + beta - 2)`. Two dishonest outcomes, both reproduced below:

  (a) TRUNCATION — one default-weight (0.5) answer → alpha=1.5/beta=1 →
      `mean_confidence 0.6` published as `sleep_quality: 0.600 (n=0)`.
  (b) CHANNEL CONFLATION — two weight-1.0 answers → `n=1`, i.e. a chat published as a
      graded prediction when ZERO predictions had ever been graded.

The rendered string feeds COMPRESSED#/STANCE# generation via
`coach/coach_history_summarizer._build_compression_message`, so a wrong n propagates
into every downstream coach surface.

Pinned here:
  1. the (b) repro — the conversation-only row reports n=0 no matter how many answers
  2. mixed channels — n counts ONLY the graded outcomes
  3. the data path and the conversation path agree on ONE definition
  4. the summarizer DISCLOSES the conversational weight instead of hiding it in n,
     and a data-only row renders exactly as it always did

Hermetic — FakeDdbTable, no AWS, no LLM.

Run with:   python3 -m pytest tests/test_confidence_sample_size_honesty_1787.py -v
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

import coach_history_summarizer as chs  # noqa: E402
from coach import (
    coach_calibration as ccal,  # noqa: E402
    coach_checkin as cc,  # noqa: E402
)
from test_coach_calibration_1481 import _answered_item, _fake_table  # noqa: E402 — reuse the #1481 harness

CONF_SK = "CONFIDENCE#sleep_quality"


def _apply(table, *, uid, subdomain="sleep_quality", direction="up", weight=None):
    return ccal.apply_conversation_calibration(
        table,
        _answered_item(uid=uid),
        subdomain=subdomain,
        direction=direction,
        takeaway="The wind-down routine is holding — evenings are the lever.",
        weight=weight,
    )


# ── 1. Conversation-only rows never report a graded n ────────────────────────
def test_single_default_weight_answer_reports_zero_graded_n():
    """Repro (a): alpha=1.5/beta=1 → mean 0.6. The confidence moved; the GRADED count
    is still 0, because nothing has been graded."""
    table = _fake_table([_answered_item(uid="abcd1234")])
    assert _apply(table, uid="abcd1234")["status"] == "saved"

    conf = table.store[(cc.checkin_pk("sleep"), CONF_SK)]
    assert float(conf["alpha"]) == 1.5 and float(conf["beta_param"]) == 1.0
    assert round(float(conf["mean_confidence"]), 3) == 0.6
    assert int(conf["sample_size"]) == 0
    assert float(conf["conversation_alpha"]) == 0.5  # the move stays visible in its own channel


def test_two_full_weight_answers_still_report_zero_graded_n():
    """Repro (b): the exact case that used to publish `0.714 (n=1)` with ZERO graded
    predictions. Conversational weight accumulates; the graded n does not move."""
    table = _fake_table([_answered_item(uid="abcd1234"), _answered_item(uid="efab5678")])
    assert _apply(table, uid="abcd1234", weight=1.0)["status"] == "saved"
    assert _apply(table, uid="efab5678", weight=1.0)["status"] == "saved"

    conf = table.store[(cc.checkin_pk("sleep"), CONF_SK)]
    assert float(conf["alpha"]) == 3.0 and float(conf["beta_param"]) == 1.0
    assert round(float(conf["mean_confidence"]), 3) == 0.75
    assert int(conf["sample_size"]) == 0, "a conversational pseudo-observation was published as a graded prediction"
    assert float(conf["conversation_alpha"]) == 2.0


# ── 2. Mixed channels — n counts only the graded outcomes ────────────────────
def test_mixed_channels_count_only_graded_outcomes():
    """3 graded successes + 1 refutation + a 0.5-weight chat: Beta carries all five
    contributions, `sample_size` reports the four graded ones."""
    # 3 successes + 1 failure from the data path → alpha=4, beta=2 (from Beta(1,1))
    seeded = {
        "pk": cc.checkin_pk("sleep"),
        "sk": CONF_SK,
        "alpha": ccal._dec(4.0),
        "beta_param": ccal._dec(2.0),
        "mean_confidence": ccal._dec(4.0 / 6.0),
        "sample_size": 4,
        "subdomain": "sleep_quality",
        "coach_id": "sleep",
    }
    table = _fake_table([_answered_item(uid="abcd1234"), seeded])
    assert _apply(table, uid="abcd1234", weight=0.5)["status"] == "saved"

    conf = table.store[(cc.checkin_pk("sleep"), CONF_SK)]
    assert float(conf["alpha"]) == 4.5  # the chat did move the Beta …
    assert int(conf["sample_size"]) == 4  # … but not the graded count


# ── 3. ONE definition, shared by both writers ────────────────────────────────
def test_graded_sample_size_is_the_one_shared_definition():
    """The pure helper both write paths call. Floors at 0, never counts a fraction of a
    graded prediction, and is a no-op on rows with no conversation provenance."""
    assert ccal.graded_sample_size(1, 1) == 0  # uninformed prior
    assert ccal.graded_sample_size(4, 2) == 4  # data-only, unchanged from the old formula
    assert ccal.graded_sample_size(1.5, 1.0, 0.5, 0) == 0
    assert ccal.graded_sample_size(3.0, 1.0, 2.0, 0) == 0
    assert ccal.graded_sample_size(4.5, 2.0, 0.5, 0) == 4
    assert ccal.graded_sample_size(1.0, 1.0, 0.5, 0.5) == 0  # never negative
    assert ccal.graded_sample_size(None, None) == 0  # missing fields fail soft, not loud


def test_data_path_uses_the_same_definition_and_excludes_conversation():
    """`coach/coach_prediction_evaluator._update_bayesian_confidence` grades by +1 per
    outcome and MUST subtract the conversational accumulators it carries forward — the
    old `int(alpha + beta - 2)` there would have counted them."""
    import coach_prediction_evaluator as cpe

    src = open(os.path.join(_REPO, "lambdas", "coach", "coach_prediction_evaluator.py"), encoding="utf-8").read()
    assert "graded_sample_size" in src, "the data path re-forked its own sample_size formula"
    assert "int(alpha + beta_val - 2)" not in src

    # One graded success on top of two full-weight chats: alpha=4, conv_alpha=2 → n=1.
    assert cpe is not None
    assert ccal.graded_sample_size(4.0, 1.0, 2.0, 0.0) == 1


# ── 4. The summarizer discloses the split ────────────────────────────────────
def _confidence_line(conf_record):
    msg = chs._build_compression_message("sleep_coach", {"confidence_records": [conf_record]})
    return next(line for line in msg.splitlines() if line.strip().startswith("- sleep_quality"))


def test_summarizer_discloses_conversational_weight_beside_n():
    line = _confidence_line(
        {
            "subdomain": "sleep_quality",
            "mean_confidence": 0.6,
            "sample_size": 0,
            "conversation_alpha": 0.5,
            "conversation_beta": 0,
        }
    )
    assert "0.600" in line
    assert "n=0" in line
    assert "conversational" in line, "the conversational contribution vanished from the grounding string"
    assert "0.5" in line


def test_summarizer_data_only_row_renders_unchanged():
    """No conversation provenance ⇒ no extra clause (the pre-#1787 rendering)."""
    line = _confidence_line({"subdomain": "sleep_quality", "mean_confidence": 0.75, "sample_size": 4})
    assert line.strip() == "- sleep_quality: 0.750 (n=4)"
