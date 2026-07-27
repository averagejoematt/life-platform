"""tests/test_adr141_takeaway_screen_1789.py — the ADR-141 §4 carve-out screen (#1789).

The finding: ADR-141 §4 called `answer_quote` AND `takeaway` Matthew-private, while §3
deliberately folds conversation learnings into the STANCE#/COMPRESSED# grounding — whose
prose serves publicly. The 2026-07-26 hardening removed the verbatim `answer_quote` from
both prompts and claimed leakage was then "structurally impossible"; that held for the
quote only. The `takeaway` is LLM-authored from Matthew's verbatim answer, and its ONLY
barrier to a publicly-served prompt was the generating model's discretion — the numeric
gates downstream inspect digits, not semantics.

This pins the resolution:
  * the carve-out is real — a CLEAN takeaway still reaches both prompts (§3 is intact);
  * it is gated by CODE, not prompt text — the standing content absolutes are screened
    deterministically, reusing `coach_dossier.find_dossier_violations`;
  * it is FAIL-CLOSED in every direction — a hit, an empty value, a broken screen, or a
    screen missing from the bundle all withhold; nothing unscreened ever reaches a prompt;
  * `answer_quote` remains absent from both prompts unconditionally (regression pin).

Hermetic — no AWS, no LLM.
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

import coach_calibration as ccal  # noqa: E402
import coach_dossier  # noqa: E402
import coach_history_summarizer as chs  # noqa: E402
import pytest  # noqa: E402

CLEAN = "Evenings are the lever — the routine collapsed after travel."


def _conv_learning(takeaway=CLEAN, **over):
    rec = {
        "sk": "LEARNING#2026-07-20#conv-abcd1234-sleep_quality",
        "date": "2026-07-20",
        "channel": "conversation",
        "status": "insight",
        "subdomain": "sleep_quality",
        "takeaway": takeaway,
        "answer_quote": "I stopped winding down and just doomscrolled",
        "checkin_id": "CHECKIN#2026-07-20#abcd1234",
        "confidence_direction": "down",
    }
    rec.update(over)
    return rec


def _compression_state(*learnings):
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
        "learning_outcomes": list(learnings),
    }


# ══════════════════════════════════════════════════════════════════════════════
# The carve-out is REAL: a clean takeaway still grounds the §3 prompts
# ══════════════════════════════════════════════════════════════════════════════
def test_clean_takeaway_clears_the_screen_and_reaches_both_prompts():
    safe, violations = ccal.screen_takeaway_for_public_prompt(CLEAN)
    assert safe == CLEAN and violations == []

    msg = chs._build_compression_message("sleep_coach", _compression_state(_conv_learning()))
    assert "Evenings are the lever" in msg

    track = chs._summarize_track_record([_conv_learning()], [])
    assert track["conversation_learnings"]["recent"][0]["takeaway"] == CLEAN


def test_clean_takeaway_is_truncated_to_the_prompt_budget_not_dropped():
    long_clean = "the routine collapses on travel weeks and rebuilds within three days. " * 6
    safe, violations = ccal.screen_takeaway_for_public_prompt(long_clean)
    assert violations == []
    assert len(safe) == ccal.PUBLIC_PROMPT_TAKEAWAY_CHARS


# ══════════════════════════════════════════════════════════════════════════════
# It is gated by CODE: every standing content absolute withholds
# ══════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize(
    "dirty",
    [
        "he says the weed helps him wind down",  # substances (privacy_guard.VICE_KEYWORDS)
        "he split a bottle of wine and slept badly",  # the widened alcohol family
        "he is comparing his protocol to andrew huberman's",  # banned real name
        "my sister moving in reset his whole evening",  # family specifics
        "the funeral week is what broke the routine",  # private events
        "at 47 years old the recovery curve flattened",  # chronological age (PhenoAge Option A)
        "his APOE e3/e4 genotype is driving the sleep read",  # genotype strings (PRE-13)
        "he asked me to follow up at matt@example.com",  # PII (broadcast_sensitivity_gate)
        "call him on 415-555-1212 before the next block",  # PII (phone)
    ],
)
def test_every_content_absolute_withholds_the_takeaway(dirty):
    safe, violations = ccal.screen_takeaway_for_public_prompt(dirty)
    assert safe is None, f"screen let through: {dirty!r}"
    assert violations, "a withheld takeaway must report why"


def test_withheld_takeaway_never_reaches_the_publicly_served_prompts():
    dirty = "he says the weed helps him wind down and my sister noticed too"
    rec = _conv_learning(takeaway=dirty)

    msg = chs._build_compression_message("sleep_coach", _compression_state(rec))
    assert "weed" not in msg and "my sister" not in msg
    assert ccal.TAKEAWAY_WITHHELD_MARKER in msg
    # the structural signal survives — an honest absence, not a vanished record (ADR-104)
    assert "## Conversation Learnings (1 newest" in msg
    assert "(checkin CHECKIN#2026-07-20#abcd1234)" in msg

    track = chs._summarize_track_record([rec], [])
    entry = track["conversation_learnings"]["recent"][0]
    assert entry["takeaway"] == ccal.TAKEAWAY_WITHHELD_MARKER
    assert "weed" not in str(entry)
    assert entry["checkin_id"] == "CHECKIN#2026-07-20#abcd1234"
    assert track["conversation_learnings"]["count"] == 1


def test_the_screen_reads_the_full_takeaway_not_the_truncated_prompt_form():
    """Truncation must never launder a violation out of view."""
    dirty_late = ("a" * (ccal.PUBLIC_PROMPT_TAKEAWAY_CHARS + 50)) + " and the weed helped"
    assert len(dirty_late[: ccal.PUBLIC_PROMPT_TAKEAWAY_CHARS]) == ccal.PUBLIC_PROMPT_TAKEAWAY_CHARS
    assert coach_dossier.find_dossier_violations(dirty_late[: ccal.PUBLIC_PROMPT_TAKEAWAY_CHARS]) == []
    assert ccal.screen_takeaway_for_public_prompt(dirty_late)[0] is None


# ══════════════════════════════════════════════════════════════════════════════
# FAIL-CLOSED: a screen that cannot vouch withholds — it never passes text through
# ══════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("empty", [None, "", "   "])
def test_empty_takeaway_is_withheld_not_rendered_blank(empty):
    assert ccal.screen_takeaway_for_public_prompt(empty)[0] is None
    assert ccal.public_prompt_takeaway({"takeaway": empty}) == ccal.TAKEAWAY_WITHHELD_MARKER


def test_a_raising_screen_withholds(monkeypatch):
    def _boom(_text):
        raise RuntimeError("screen exploded")

    monkeypatch.setattr(coach_dossier, "find_dossier_violations", _boom)
    safe, violations = ccal.screen_takeaway_for_public_prompt(CLEAN)
    assert safe is None
    assert violations and violations[0][0] == "screen_unavailable"
    assert ccal.public_prompt_takeaway(_conv_learning()) == ccal.TAKEAWAY_WITHHELD_MARKER


def test_summarizer_withholds_when_the_screen_helper_is_unavailable(monkeypatch):
    """The bundle-missing path: privacy gates fail CLOSED even where sibling
    quality gates in the same module fail open."""
    monkeypatch.setattr(chs, "_public_prompt_takeaway", None)
    assert chs._screened_takeaway(_conv_learning()) == chs.TAKEAWAY_WITHHELD_MARKER

    def _boom(_rec):
        raise RuntimeError("helper exploded")

    monkeypatch.setattr(chs, "_public_prompt_takeaway", _boom)
    assert chs._screened_takeaway(_conv_learning()) == chs.TAKEAWAY_WITHHELD_MARKER


def test_the_screen_reuses_the_house_vocabulary_rather_than_forking_one(monkeypatch):
    """One list, three consumers — a widening in journal_quotes/privacy_guard is
    inherited here for free. Pinned by delegation, not by duplicated keywords."""
    seen = []

    def _spy(text):
        seen.append(text)
        return [("spy", "hit")]

    monkeypatch.setattr(coach_dossier, "find_dossier_violations", _spy)
    assert ccal.screen_takeaway_for_public_prompt("anything at all")[0] is None
    assert seen == ["anything at all"]


# ══════════════════════════════════════════════════════════════════════════════
# Regression pin: answer_quote stays unconditionally absent (no carve-out)
# ══════════════════════════════════════════════════════════════════════════════
def test_answer_quote_is_never_in_a_publicly_served_prompt_even_when_clean():
    rec = _conv_learning()
    msg = chs._build_compression_message("sleep_coach", _compression_state(rec))
    assert "doomscrolled" not in msg
    track = chs._summarize_track_record([rec], [])
    assert "doomscrolled" not in str(track)
    assert "answer_quote" not in str(track)
