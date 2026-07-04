"""#397 — the ask loop closes: 'you asked → the board answered' is a real public feed.

The capture side (POST /api/board_question) and the qa tab existed, but the
payoff surface didn't: CloudFront had no /board_answers/* behavior (the fetch
fell through to the site origin and 404'd) and the publish script ran zero
content/privacy gates. These tests pin the loop's three legs: routing, the
fail-closed publish gate, and the honest empty state.
"""

import os
import sys

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "scripts"))

WEB_STACK_SRC = open(os.path.join(_REPO, "cdk/stacks/web_stack.py")).read()
COACHING_JS = open(os.path.join(_REPO, "site/assets/js/coaching.js")).read()


def _publish_mod():
    import publish_board_answer as pba

    return pba


def test_cloudfront_routes_board_answers_to_generated_origin():
    """The feed URL must route to S3GeneratedOrigin — the 404 that hid the
    whole payoff surface was this behavior missing."""
    idx = WEB_STACK_SRC.find('path_pattern="/board_answers/*"')
    assert idx != -1, "no /board_answers/* CloudFront behavior"
    window = WEB_STACK_SRC[idx : idx + 400]
    assert 'target_origin_id="S3GeneratedOrigin"' in window


def test_qa_tab_reads_the_feed_and_has_honest_empty_state():
    assert '"/board_answers/answers.json"' in COACHING_JS
    assert "No reader questions answered yet" in COACHING_JS
    # No seeded fake content — the empty state is words, not placeholder answers.
    assert "sample question" not in COACHING_JS.lower()


def test_publish_gate_passes_clean_entry():
    pba = _publish_mod()
    entry = {
        "id": "abc123",
        "question": "Is the glucose spike the supplement, or just a bad night's sleep?",
        "note": "Great question — exactly the confound we test for.",
        "responses": [
            {"name": "Dr. Lisa Park", "text": "The sleep data points at the short night, not the supplement."},
            {"name": "Dr. Amara Patel", "text": "I disagree slightly — the meal response window matters more here."},
        ],
    }
    assert pba.assert_entry_publishable(entry) is entry


def test_publish_gate_blocks_vice_terms_fail_closed():
    import privacy_guard

    pba = _publish_mod()
    bad = {
        "id": "x",
        "question": "What happened during the marijuana experiment?",
        "responses": [],
    }
    with pytest.raises(privacy_guard.PrivacyViolation):
        pba.assert_entry_publishable(bad)


def test_publish_gate_blocks_banned_names_in_answers():
    import privacy_guard

    pba = _publish_mod()
    bad = {
        "id": "x",
        "question": "A fine question about sleep.",
        "answer": "As Attia says, sleep is the foundation.",
    }
    with pytest.raises(privacy_guard.PrivacyViolation):
        pba.assert_entry_publishable(bad)


def test_publish_script_wires_the_gate_before_put():
    """Source-level: cmd_answer must gate BEFORE writing the feed."""
    src = open(os.path.join(_REPO, "scripts/publish_board_answer.py")).read()
    gate_at = src.find("assert_entry_publishable(entry)")
    put_at = src.find("_put_json(FEED_KEY, feed)")
    assert gate_at != -1 and put_at != -1 and gate_at < put_at
