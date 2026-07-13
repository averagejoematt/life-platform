"""tests/test_panelcast_craft.py — the podcast craft layer (#1180, epic #1082).

Offline coverage (no live Bedrock — every model call is a stub) of the three pieces:
the punch-up pass and its HARD LOCKS (a punch that changes turn count / speaker order /
numbers falls back to the un-punched draft), the evidence-citing Sonnet craft judge (a
flat-but-compliant script FAILS the humour item when no beats can be cited; JSON incl.
`cited_beats` parses), and the ledger fields (`punched`, `citations`).
"""

import json
import logging
import os
import sys

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "emails"))

from emails import (  # noqa: E402
    panelcast_craft as craft,
    panelcast_qa as qa,
    panelcast_repair as repair,
)

_LOG = logging.getLogger("test-panelcast-craft")

# A clean, compliant, alternating draft — deterministically fine, but flat (no humour).
_DRAFT = [
    {"speaker": "elena_voss", "line": "Here is the hook that got me into this whole thing."},
    {"speaker": "eli_marsh", "line": "The platform tracks 15 signals every single day."},
    {"speaker": "elena_voss", "line": "And the readers see all of it, unfiltered?"},
    {"speaker": "eli_marsh", "line": "Every line of it, good week or bad."},
]


def _invoke_returning(payload):
    """A fake bedrock_client.invoke returning `payload` serialized as the model's text."""

    def _invoke(body, model_name=None):
        return {"content": [{"text": json.dumps(payload) if not isinstance(payload, str) else payload}]}

    return _invoke


# ── piece 2: punch-up locks ───────────────────────────────────────────────────


def test_punch_up_applies_a_valid_in_place_rewrite():
    # A rewrite that keeps turn count, speaker order, and every number → applied.
    rewrite = [
        {"speaker": "elena_voss", "line": "Okay — here's the hook that reeled me in, embarrassingly fast."},
        {"speaker": "eli_marsh", "line": "The platform quietly clocks 15 signals a day, whether you like it or not."},
        {"speaker": "elena_voss", "line": "And the readers get all of it? Unfiltered?"},
        {"speaker": "eli_marsh", "line": "Every last line. Glorious week, or a total dumpster fire."},
    ]
    out, punched = craft.punch_up_script(_DRAFT, _invoke_returning(rewrite), "m", panel_extract_json(), _LOG)
    assert punched is True and out == rewrite


def test_punch_up_rejected_when_turn_count_changes():
    dropped = _DRAFT[:3]  # one turn fewer
    out, punched = craft.punch_up_script(_DRAFT, _invoke_returning(dropped), "m", panel_extract_json(), _LOG)
    assert punched is False and out == _DRAFT  # falls back to the un-punched draft


def test_punch_up_rejected_when_speaker_order_changes():
    reordered = [dict(t) for t in _DRAFT]
    reordered[1]["speaker"] = "elena_voss"  # was eli_marsh — order no longer matches
    out, punched = craft.punch_up_script(_DRAFT, _invoke_returning(reordered), "m", panel_extract_json(), _LOG)
    assert punched is False and out == _DRAFT


def test_punch_up_rejected_when_a_number_is_added_or_changed():
    # The punch invents "5 AM" and changes 15 → 20: the number multiset no longer matches.
    tampered = [
        {"speaker": "elena_voss", "line": "Here is the hook that got me into this whole thing."},
        {"speaker": "eli_marsh", "line": "The platform tracks 20 signals every day, starting at 5 AM."},
        {"speaker": "elena_voss", "line": "And the readers see all of it, unfiltered?"},
        {"speaker": "eli_marsh", "line": "Every line of it, good week or bad."},
    ]
    out, punched = craft.punch_up_script(_DRAFT, _invoke_returning(tampered), "m", panel_extract_json(), _LOG)
    assert punched is False and out == _DRAFT


def test_punch_up_rejected_when_a_line_exceeds_the_word_cap():
    over = [dict(t) for t in _DRAFT]
    over[1]["line"] = "word " * (qa._QA_MAX_WORDS_PER_TURN + 5)
    out, punched = craft.punch_up_script(_DRAFT, _invoke_returning(over), "m", panel_extract_json(), _LOG)
    assert punched is False and out == _DRAFT


def test_punch_up_honors_the_callers_per_line_gate():
    tainted = [dict(t) for t in _DRAFT]
    tainted[2]["line"] = "And he weighed himself again this morning, right?"
    out, punched = craft.punch_up_script(
        _DRAFT, _invoke_returning(tainted), "m", panel_extract_json(), _LOG, line_ok=lambda line: "weighed" not in line
    )
    assert punched is False and out == _DRAFT


def test_punch_up_reverts_on_a_deterministic_regression_craft_check():
    # A rewrite that passes the locks but reads as a same-speaker seam per craft_check →
    # the craft_check callback vetoes it (the punch can only help, never regress).
    ok_locks = [dict(t) for t in _DRAFT]
    out, punched = craft.punch_up_script(
        _DRAFT, _invoke_returning(ok_locks), "m", panel_extract_json(), _LOG, craft_check=lambda ts: ["synthetic regression"]
    )
    assert punched is False and out == _DRAFT


def test_punch_up_fails_soft_on_model_error_never_raises():
    def _boom(*a, **k):
        raise RuntimeError("bedrock down")

    out, punched = craft.punch_up_script(_DRAFT, _boom, "m", panel_extract_json(), _LOG)
    assert punched is False and out == _DRAFT  # a punch-up problem never fails the run


# ── piece 3: the evidence-citing Sonnet craft judge ───────────────────────────


def test_craft_judge_parses_pass_with_cited_beats(monkeypatch):
    import bedrock_client

    verdict = {"pass": True, "fails": [], "cited_beats": ["Every last line. Glorious week, or a total dumpster fire.", "reeled me in"]}
    monkeypatch.setattr(bedrock_client, "invoke", _invoke_returning(verdict))
    ok, fails, cited = qa._craft_judge(_DRAFT, qa._WEEKLY_CRAFT_RUBRIC)
    assert ok is True and fails == []
    assert cited == verdict["cited_beats"]  # the quoted evidence is returned for the ledger


def test_flat_compliant_script_fails_the_craft_judge_when_no_beats_can_be_cited(monkeypatch):
    # The whole point of #1180: a flat-but-compliant script FAILS the humour item because
    # the judge cannot cite two lines that would make a stranger smile.
    import bedrock_client

    verdict = {
        "pass": False,
        "fails": ["HUMOUR: could not find two lines that would make a stranger smile — reads as a briefing"],
        "cited_beats": [],
    }
    monkeypatch.setattr(bedrock_client, "invoke", _invoke_returning(verdict))
    ok, fails, cited = qa._craft_judge(_DRAFT, qa._WEEKLY_CRAFT_RUBRIC)
    assert ok is False
    assert any("HUMOUR" in f for f in fails)
    assert cited == []  # no beats credited → the honest empty citation


def test_craft_judge_strips_fences_and_fails_closed_on_error(monkeypatch):
    import bedrock_client

    # Fenced JSON is tolerated.
    monkeypatch.setattr(bedrock_client, "invoke", _invoke_returning('```json\n{"pass": true, "cited_beats": ["a line"]}\n```'))
    ok, fails, cited = qa._craft_judge(_DRAFT, qa._INTRO_CRAFT_RUBRIC)
    assert ok is True and cited == ["a line"]

    # A judge/infra error FAILS CLOSED (holds) — matching the Haiku judge's posture.
    def _boom(*a, **k):
        raise RuntimeError("bedrock down")

    monkeypatch.setattr(bedrock_client, "invoke", _boom)
    ok, fails, cited = qa._craft_judge(_DRAFT, qa._INTRO_CRAFT_RUBRIC)
    assert ok is False and cited == [] and "craft-judge-error" in fails[0] and "bedrock down" in fails[0]


def test_craft_model_is_sonnet_tier_and_env_overridable(monkeypatch):
    import importlib

    # ADR-049: craft judgment is narrative → the Sonnet tier, env-overridable.
    assert "sonnet" in qa.CRAFT_MODEL.lower()
    assert "sonnet" in craft.PUNCH_UP_MODEL.lower()
    monkeypatch.setenv("AI_MODEL_SONNET", "custom-sonnet-id")
    importlib.reload(qa)
    importlib.reload(craft)
    assert qa.CRAFT_MODEL == "custom-sonnet-id" and craft.PUNCH_UP_MODEL == "custom-sonnet-id"
    monkeypatch.delenv("AI_MODEL_SONNET", raising=False)
    importlib.reload(qa)
    importlib.reload(craft)


# ── the ledger records punched + citations (#1180) ────────────────────────────


def test_ledger_records_punched_and_citations():
    cited = ["a genuinely funny line", "a warm human aside"]
    e = repair.ledger_entry(1, 0, [], ["some judge note"], repaired_seams=0, punched=True, citations=cited)
    assert e["punched"] is True
    assert e["citations"] == cited
    # A row that never reaches the craft layer omits both fields (no-candidate / editor-hold).
    bare = repair.ledger_entry(1, 0, ["no usable candidate"], [])
    assert "punched" not in bare and "citations" not in bare
    # punched=False is recorded honestly (the punch ran and was rejected/no-op).
    rejected = repair.ledger_entry(2, 1, [], [], punched=False, citations=[])
    assert rejected["punched"] is False and rejected["citations"] == []


# ── the craft rubrics carry the evidence demand + the new arc item ────────────


def test_craft_rubrics_carry_the_three_craft_items():
    for rubric in (qa._INTRO_CRAFT_RUBRIC, qa._WEEKLY_CRAFT_RUBRIC):
        assert "ARC RHYTHM" in rubric  # the NEW emotional-arc-rhythm item
        assert "TURING TEST" in rubric  # moved off the Haiku judge
        assert "HUMOUR" in rubric.upper()  # the taste item that must cite evidence


def panel_extract_json():
    """The lambda's tolerant JSON parser — imported lazily so this module has no hard
    dependency on the heavy lambda for the pure-craft tests above."""
    from emails import coach_panel_podcast_lambda as panel

    return panel._extract_json
