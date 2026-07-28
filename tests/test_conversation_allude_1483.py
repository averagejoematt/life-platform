"""tests/test_conversation_allude_1483.py — #1483 (ADR-142 theme-referenceable tier).

Semi-private conversation references: public coach surfaces may allude to a
check-in conversation (that it OCCURRED, its COARSE laundered theme, the read
DELTA) but the verbatim conversation text — the CHECKIN# answer, and the
`answer_quote`/`takeaway`/`question` fields on the ADR-141 conversation
LEARNING# rows — must NEVER appear in any public payload or prompt.

The quality gate here (AC3) is adversarial by construction: we seed a
conversation record stuffed with quotable, distinctly-private text and assert
none of it surfaces through:
  - diary_consent.conversation_reference (the sanctioned projection),
  - diary_consent.conversation_prompt_block (the public-narrative prompt block),
  - /api/coach/{id} (the by-coach payload — the rendered surface, AC2),
  - the other COACH#-reading public handlers (roster, timeline, calibration,
    predictions — a sweep, since the fake serves the adversarial rows to every
    query),
  - the Wednesday chronicle data packet (what Elena is actually shown).

Hermetic — FakeDdbTable everywhere, no AWS, no LLM.
"""

import json
import os
import sys

os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "web"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "emails"))

from emails import chronicle_data  # noqa: E402
from fakes import FakeDdbTable  # noqa: E402
from privacy import diary_consent  # noqa: E402
from web import site_api_coach as api  # noqa: E402

# ── the adversarial conversation record (ADR-141 LEARNING# shape) ────────────

PRIVATE_ANSWER = "Honestly, evenings after 9pm are when I cave — Tuesday I nearly relapsed after that hard call about mom."
PRIVATE_TAKEAWAY = "He is candid that evenings are the failure window; push him softer after 9pm."
PRIVATE_QUESTION = "When do the evenings actually fall apart for you?"

ADVERSARIAL = {
    "pk": "COACH#sleep_coach",
    "sk": "LEARNING#2026-07-24#conv-Ab12Cd34-evening_discipline",
    "record_type": "coach_learning",
    "coach_id": "sleep_coach",
    "date": "2026-07-24",
    "channel": "conversation",
    "source": "conversation",
    "evaluation_type": "conversation_calibration",
    "status": "insight",
    "subdomain": "evening_discipline",
    "takeaway": PRIVATE_TAKEAWAY,
    "checkin_id": "CHECKIN#2026-07-24#Ab12Cd34",
    "question": PRIVATE_QUESTION,
    "answer_quote": PRIVATE_ANSWER,
    "confidence_direction": "down",
    "confidence_weight": 0.5,
    "created_at": "2026-07-24T19:00:00Z",
}

# Distinctive fragments of the private text — none may appear in ANY public
# output, in any casing/whitespace.
PRIVATE_FRAGMENTS = (
    "evenings after 9pm",
    "nearly relapsed",
    "hard call about mom",
    "failure window",
    "push him softer",
    "fall apart for you",
)

DATA_LEARNING = {
    "pk": "COACH#sleep_coach",
    "sk": "LEARNING#2026-07-20#sleep_score",
    "date": "2026-07-20",
    "channel": "data",
    "status": "confirmed",
    "metric": "sleep_score",
    "reason": "sleep_score rose as predicted",
}


def _norm(s):
    return " ".join(str(s).split()).lower()


def _assert_no_leak(payload, context=""):
    blob = _norm(json.dumps(payload, default=str))
    for frag in PRIVATE_FRAGMENTS:
        assert _norm(frag) not in blob, f"private fragment {frag!r} leaked into {context or 'payload'}"


# ── the sanctioned projection (diary_consent.conversation_reference) ─────────


def test_reference_is_built_from_the_allowlist_only():
    ref = diary_consent.conversation_reference(ADVERSARIAL)
    assert ref is not None
    # keys are exactly a subset of the sanctioned field list — nothing rides along
    assert set(ref) <= set(diary_consent.CONVERSATION_SANCTIONED_FIELDS)
    assert ref["occurred"] is True
    assert ref["date"] == "2026-07-24"
    assert ref["direction"] == "down" and ref["weight"] == 0.5
    assert ref["coach_id"] == "sleep_coach"
    # theme is laundered ('evening_discipline' → the coarse public category),
    # never the raw subdomain
    assert ref["theme"] == "personal_growth"
    assert "evening_discipline" not in json.dumps(ref)
    _assert_no_leak(ref, "conversation_reference")


def test_reference_fails_closed():
    # a data-channel learning is not a conversation
    assert diary_consent.conversation_reference(DATA_LEARNING) is None
    # a bare CHECKIN# record (no channel marker) never projects
    assert diary_consent.conversation_reference({"answer": PRIVATE_ANSWER, "date": "2026-07-24"}) is None
    # malformed/missing date → None (a reference must be attributable to a day)
    assert diary_consent.conversation_reference({**ADVERSARIAL, "date": "recently"}) is None
    assert diary_consent.conversation_reference({**ADVERSARIAL, "date": ""}) is None
    assert diary_consent.conversation_reference(None) is None
    assert diary_consent.conversation_reference({}) is None


def test_reference_is_idempotent_on_its_own_output():
    ref = diary_consent.conversation_reference(ADVERSARIAL)
    again = diary_consent.conversation_reference(ref)
    assert again == ref


def test_theme_output_vocabulary_is_the_allowlist():
    allowed = set(diary_consent.CONVERSATION_THEME_COPY)
    for sub in (
        "evening_discipline",
        "sleep_quality",
        "protein_intake",
        "stress_response",
        "family_time",
        "work_deadlines",
        "totally_unknown_slug",
        "mom's diagnosis and the private thing",  # adversarial free text
        "",
        None,
        42,
    ):
        theme = diary_consent.conversation_theme(sub)
        assert theme in allowed, f"{sub!r} laundered to off-vocabulary {theme!r}"
    # weird direction/weight inputs clamp, never propagate raw
    ref = diary_consent.conversation_reference({**ADVERSARIAL, "confidence_direction": "sideways", "confidence_weight": "lots"})
    assert ref["direction"] == "hold" and ref["weight"] == 0.0
    ref = diary_consent.conversation_reference({**ADVERSARIAL, "confidence_weight": 99})
    assert ref["weight"] == 1.0


# ── the prompt block (public narrative generation input) ─────────────────────


def test_prompt_block_carries_sanctioned_fields_and_the_boundary():
    block = diary_consent.conversation_prompt_block([ADVERSARIAL])
    assert diary_consent.CONVERSATION_BLOCK_HEADER in block
    assert "2026-07-24" in block
    assert "his sleep coach" in block
    assert "habits and growth" in block  # the laundered theme's reader copy
    assert "NEVER quote" in block
    _assert_no_leak(block, "conversation_prompt_block")


def test_prompt_block_is_silent_when_nothing_qualifies():
    assert diary_consent.conversation_prompt_block([]) == ""
    assert diary_consent.conversation_prompt_block(None) == ""
    # data learnings and malformed records produce NO block, not an empty scaffold
    assert diary_consent.conversation_prompt_block([DATA_LEARNING, {}, None]) == ""


# ── AC2: the by-coach public surface renders the reference ───────────────────


def test_coach_payload_carries_sanctioned_conversation_reference(monkeypatch):
    monkeypatch.setattr(api, "table", FakeDdbTable(rows=[ADVERSARIAL, DATA_LEARNING]))
    resp = api.handle_coach({"rawPath": "/api/coach/sleep_coach"})
    assert resp["statusCode"] == 200
    data = json.loads(resp["body"])
    conv = data["conversations"]
    assert conv["count"] == 1
    ref = conv["references"][0]
    assert set(ref) <= set(diary_consent.CONVERSATION_SANCTIONED_FIELDS)
    assert ref["date"] == "2026-07-24" and ref["theme"] == "personal_growth" and ref["direction"] == "down"
    assert "private" in conv["note"].lower()


# ── AC3: the quality gate — no CHECKIN# verbatim in ANY public payload ───────


def test_no_public_coach_payload_leaks_conversation_text(monkeypatch):
    # The fake serves the adversarial rows to EVERY query each handler makes —
    # if any public payload can carry the verbatim text, this sweep catches it.
    fake = FakeDdbTable(rows=[ADVERSARIAL, DATA_LEARNING])
    monkeypatch.setattr(api, "table", fake)
    surfaces = (
        ("/api/coach/{id}", api.handle_coach({"rawPath": "/api/coach/sleep_coach"})),
        ("/api/coaches", api.handle_coaches({})),
        ("/api/coach_team", api.handle_coach_team({})),
        ("/api/coach_timeline", api.handle_coach_timeline({"queryStringParameters": {"coach_id": "sleep"}})),
        ("/api/calibration", api.handle_calibration({})),
        ("/api/predictions", api.handle_predictions({"queryStringParameters": {}})),
    )
    for name, resp in surfaces:
        assert resp["statusCode"] == 200, name
        _assert_no_leak(json.loads(resp["body"]), name)


def test_track_record_still_excludes_conversation_learnings(monkeypatch):
    # regression pin on the ADR-141 filter this feature builds beside
    monkeypatch.setattr(api, "table", FakeDdbTable(rows=[ADVERSARIAL, DATA_LEARNING]))
    out = api._track_record("sleep_coach")
    assert out["confirmed"] == 1 and out["decided"] == 1
    _assert_no_leak(out, "_track_record")


# ── the Wednesday chronicle packet (what Elena is shown) ─────────────────────


def _chronicle_data(conversation_refs):
    from ai import ai_context

    return {
        "profile": {
            "journey_start_date": ai_context.EXPERIMENT_START_DATE,
            "journey_start_weight_lbs": 300.8,
            "goal_weight_lbs": 185,
        },
        "dates": {"start": "2026-07-20", "end": "2026-07-26"},
        "withings": {},
        "whoop": {},
        "strava": {},
        "macrofactor": {},
        "eightsleep": {},
        "journal_entries": [],
        "day_grades": {},
        "habit_scores": {},
        "habitify": {},
        "state_of_mind": {},
        "supplements": {},
        "experiments": [],
        "anomalies": {},
        "weather": {},
        "character_sheet": {},
        "prev_installments": [],
        "narrative_arc": {},
        "experiment_arc": {},
        "field_notes": [],
        "conversation_refs": conversation_refs,
    }


def test_chronicle_packet_alludes_without_the_words():
    # even a RAW adversarial LEARNING# row handed to the packet builder renders
    # as sanctioned fields only — the block re-projects, it never passes through
    packet, _ = chronicle_data.build_data_packet(_chronicle_data([ADVERSARIAL]))
    assert diary_consent.CONVERSATION_BLOCK_HEADER in packet
    assert "his sleep coach" in packet and "2026-07-24" in packet
    _assert_no_leak(packet, "chronicle data packet")


def test_chronicle_packet_has_no_block_on_a_quiet_week():
    packet, _ = chronicle_data.build_data_packet(_chronicle_data([]))
    assert diary_consent.CONVERSATION_BLOCK_HEADER not in packet
    # tolerant of the key being absent entirely (older gathers / fixtures)
    d = _chronicle_data([])
    d.pop("conversation_refs")
    packet, _ = chronicle_data.build_data_packet(d)
    assert diary_consent.CONVERSATION_BLOCK_HEADER not in packet
