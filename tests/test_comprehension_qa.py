"""tests/test_comprehension_qa.py — the newcomer-comprehension judge (#4182, M4).

Every test here mocks Bedrock — no live model call, no live network, no live AWS.
Coverage: the grader's tolerant JSON parsing (fixtures for score 0/1/2 plus every
unreadable shape), the reader's own unreadable-answer classification, the "always
writes a count" dead-man contract, the budget-checked-FIRST ordering, the six doors'
`intent` facet (present and <=30 words), and `main()`'s "fails only when the
artifact is missing" contract — the last of which is also this module's CI-step
census proof (see docs/CONVENTIONS.md's Gate registry).

Deliberately does NOT `import qa_manifest` directly (only `comprehension_qa`, which
reads it internally) — see `tests/premerge_derivation.py`'s sweeping-helper rule:
qa_manifest.py enumerates the whole `site/` tree directly (its `site_files()`
facet), so a test file that imports it by name is classified as a tree-sweeping
structural-test gate. This file is a parsing/scoring unit-test suite, not a tree
sweep, and stays out of that census family by construction.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
_LAMBDAS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas")
sys.path.insert(0, _LAMBDAS)

import comprehension_qa as cq  # noqa: E402
from ai import budget_guard  # noqa: E402 — the REAL module; tests monkeypatch its functions directly


# ── the six doors' declared intent (tests/qa_manifest.py) ────────────────────────
def test_every_door_has_an_intent_at_or_under_thirty_words():
    for path in cq.DOORS:
        intent = cq._door_intent(path)
        assert intent, f"{path} has no declared intent — the grader would have nothing to grade against"
        n = len(intent.split())
        assert n <= 30, f"{path}'s intent is {n} words, over the 30-word cap: {intent!r}"


def test_an_unregistered_path_reports_no_intent_rather_than_raising():
    assert cq._door_intent("/this-path-does-not-exist/") is None


# ── the grader's tolerant JSON extraction ─────────────────────────────────────────
def test_parse_grade_score_two():
    v = cq._parse_grade('{"score": 2, "note": "named the purpose and the click"}')
    assert v["score"] == 2
    assert "purpose" in v["note"]
    assert cq._vqa._UNEVALUATED_FIELD not in v


def test_parse_grade_score_one():
    v = cq._parse_grade('{"score": 1, "note": "named the click but not the purpose"}')
    assert v["score"] == 1


def test_parse_grade_score_zero():
    v = cq._parse_grade('{"score": 0, "note": "generic — could describe any page"}')
    assert v["score"] == 0


def test_parse_grade_tolerates_prose_and_fences_around_the_json():
    v = cq._parse_grade('Here is my verdict:\n```json\n{"score": 2, "note": "clear"}\n```\nDone.')
    assert v["score"] == 2


def test_parse_grade_no_json_is_unevaluated_no_verdict():
    v = cq._parse_grade("I refuse to answer in JSON.")
    assert v["score"] is None
    assert v[cq._vqa._UNEVALUATED_FIELD] == cq._vqa._KIND_NO_VERDICT


def test_parse_grade_unparseable_json_is_unevaluated():
    v = cq._parse_grade('{"score": 2, "note": unquoted}')
    assert v["score"] is None
    assert v[cq._vqa._UNEVALUATED_FIELD] == cq._vqa._KIND_UNPARSEABLE


def test_parse_grade_out_of_range_score_is_unevaluated_unparseable():
    v = cq._parse_grade('{"score": 3, "note": "not a valid score"}')
    assert v["score"] is None
    assert v[cq._vqa._UNEVALUATED_FIELD] == cq._vqa._KIND_UNPARSEABLE


def test_parse_grade_missing_score_is_unevaluated_unparseable():
    v = cq._parse_grade('{"note": "forgot the score field"}')
    assert v["score"] is None
    assert v[cq._vqa._UNEVALUATED_FIELD] == cq._vqa._KIND_UNPARSEABLE


def test_parse_grade_boolean_is_not_mistaken_for_an_int_score():
    """Python's bool is an int subclass — True == 1 would silently pass a naive
    `score in (0, 1, 2)` check. Guarded explicitly (#3540 class: a garbled reply
    must not read as a clean verdict)."""
    v = cq._parse_grade('{"score": true, "note": "..."}')
    assert v["score"] is None
    assert v[cq._vqa._UNEVALUATED_FIELD] == cq._vqa._KIND_UNPARSEABLE


# ── unreadable-response classification (#3540 vocabulary, reused) ────────────────
def test_reader_unreadable_kind_truncated():
    assert cq._reader_unreadable_kind({"stop_reason": "max_tokens", "content": []}) == cq._vqa._KIND_TRUNCATED


def test_reader_unreadable_kind_empty_text_is_no_verdict():
    assert cq._reader_unreadable_kind({"stop_reason": "end_turn", "content": []}) == cq._vqa._KIND_NO_VERDICT


def test_reader_unreadable_kind_readable_answer_is_none():
    resp = {"stop_reason": "end_turn", "content": [{"type": "text", "text": "It shows today's numbers."}]}
    assert cq._reader_unreadable_kind(resp) is None


def test_grade_unreadable_kind_truncated():
    assert cq._grade_unreadable_kind({"stop_reason": "max_tokens", "content": []}) == cq._vqa._KIND_TRUNCATED


def test_grade_unreadable_kind_readable_grade_is_none():
    resp = {"stop_reason": "end_turn", "content": [{"type": "text", "text": '{"score": 2, "note": "ok"}'}]}
    assert cq._grade_unreadable_kind(resp) is None


# ── end-to-end assess_doors() with everything mocked ──────────────────────────────
class _FakeBedrock:
    """Stands in for lambdas/ai/bedrock_client — no `attributed_to`, so
    `_vqa._attributed_invoke` falls back to an unlabelled call (its own documented
    degradation path, already covered by test_bedrock_feature_attribution_2888.py).
    """

    def __init__(self, script):
        self._script = list(script)
        self.calls = []

    def invoke(self, body, model_name=None):
        self.calls.append(body)
        return self._script.pop(0)


def _text_resp(text, stop_reason="end_turn"):
    return {"content": [{"type": "text", "text": text}], "stop_reason": stop_reason}


def test_assess_doors_writes_the_schema_every_field(tmp_path, monkeypatch):
    out = tmp_path / "comprehension.json"
    monkeypatch.setattr(cq, "_capture_fold", lambda path, base_url=None: (str(tmp_path / "shot.png"), "some page text"))
    # a tiny valid PNG so _prepare_image (real, reused) accepts it
    (tmp_path / "shot.png").write_bytes(
        bytes.fromhex(
            "89504e470d0a1a0a0000000d494844520000000100000001080600000"
            "01f15c4890000000a4944415478da6360000002000155a2415d0000000049454e44ae426082"
        )
    )
    script = []
    for _ in cq.DOORS:
        script.append(_text_resp("It shows today's numbers and I'd click the main tile."))
        script.append(_text_resp('{"score": 2, "note": "named the purpose and a click"}'))
    bedrock = _FakeBedrock(script)
    monkeypatch.setattr(cq._vqa, "_import_bedrock", lambda: bedrock)

    def _allow(feature):
        assert feature == "comprehension_qa"
        return True

    monkeypatch.setattr(budget_guard, "allow", _allow)
    monkeypatch.setattr(budget_guard, "current_tier", lambda: 0)

    doc = cq.assess_doors(base_url="https://example.invalid", out_path=str(out))

    assert doc["expected"] == 6
    assert doc["scored"] == 6
    assert doc["unevaluated"] == 0
    assert doc["skipped_by_budget"] is False
    assert {"run_at", "expected", "scored", "unevaluated", "skipped_by_budget", "pages"} <= set(doc)
    assert len(doc["pages"]) == 6
    for p in doc["pages"]:
        assert {"path", "answer", "score", "grader_note"} <= set(p)
        assert p["score"] == 2
    assert out.exists()
    on_disk = json.loads(out.read_text())
    assert on_disk == doc


def test_budget_paused_run_never_touches_capture_or_bedrock(tmp_path, monkeypatch):
    """The budget check runs FIRST (#4182 M4) — a paused run must not launch a
    browser or spend a token. `_capture_fold` raising proves it was never called."""
    out = tmp_path / "comprehension.json"

    def _must_not_run(path, base_url=None):
        raise AssertionError(f"_capture_fold was called for {path} on a budget-paused run")

    monkeypatch.setattr(cq, "_capture_fold", _must_not_run)
    bedrock = _FakeBedrock([])  # empty script — any invoke() call is a bug and pops from []
    monkeypatch.setattr(cq._vqa, "_import_bedrock", lambda: bedrock)

    def _deny(feature):
        assert feature == "comprehension_qa"
        return False

    monkeypatch.setattr(budget_guard, "allow", _deny)
    monkeypatch.setattr(budget_guard, "current_tier", lambda: 1)

    doc = cq.assess_doors(out_path=str(out))

    assert doc["skipped_by_budget"] == 1
    assert doc["scored"] == 0
    assert doc["pages"] == []
    assert not bedrock.calls
    assert out.exists(), "a paused run must still write the artifact"


def test_bedrock_unavailable_still_writes_a_count(tmp_path, monkeypatch, capsys):
    """The 'always writes a count' rule: even total Bedrock unavailability produces
    a real artifact with an honest unevaluated count, never a silent skip."""
    out = tmp_path / "comprehension.json"
    monkeypatch.setattr(cq._vqa, "_import_bedrock", lambda: None)

    doc = cq.assess_doors(out_path=str(out))

    assert doc["unevaluated"] == 6
    assert doc["scored"] == 0
    assert out.exists()
    printed = capsys.readouterr().out
    assert "::notice::comprehension scored=0/6" in printed


def test_low_scores_and_unevaluated_doors_each_emit_a_warning(tmp_path, monkeypatch, capsys):
    out = tmp_path / "comprehension.json"
    monkeypatch.setattr(cq, "_capture_fold", lambda path, base_url=None: ("irrelevant.png", "text"))
    monkeypatch.setattr(cq, "_ask_reader", lambda invoke_fn, png, text, path: {"/": "a bad answer"}.get(path, "some answer"))

    _call_count = [0]

    def _fake_grader(invoke_fn, intent, answer):
        # first door (call 0) scores 0, second (call 1) scores 1, the rest are unevaluated (None)
        idx = _call_count[0]
        _call_count[0] += 1
        if idx == 0:
            return 0, "wrong"
        if idx == 1:
            return 1, "partial"
        return None, "grader returned no readable verdict (no_verdict)"

    monkeypatch.setattr(cq, "_ask_grader", _fake_grader)
    monkeypatch.setattr(cq._vqa, "_import_bedrock", lambda: _FakeBedrock([]))
    monkeypatch.setattr(budget_guard, "allow", lambda feature: True)
    monkeypatch.setattr(budget_guard, "current_tier", lambda: 0)

    doc = cq.assess_doors(out_path=str(out))
    printed = capsys.readouterr().out

    assert doc["scored"] == 2
    assert doc["unevaluated"] == 4
    assert "::warning::comprehension judge — / scored 0/2" in printed
    assert "scored 1/2" in printed
    assert "UNEVALUATED" in printed
    assert f"::notice::comprehension scored={doc['scored']}/6" in printed


# ── main()'s "fails only when the artifact is missing" contract ──────────────────
# This is also the CI-step census proof (docs/CONVENTIONS.md §9): the workflow step
# is `python3 tests/comprehension_qa.py`, whose exit code IS main()'s return value.
def test_main_returns_zero_when_the_artifact_was_written(tmp_path, monkeypatch):
    artifact = tmp_path / "comprehension.json"
    artifact.write_text("{}")
    monkeypatch.setattr(cq, "_ARTIFACT_PATH", str(artifact))
    monkeypatch.setattr(cq, "assess_doors", lambda: {"expected": 6})
    assert cq.main() == 0


def test_main_returns_one_when_the_artifact_is_missing(tmp_path, monkeypatch, capsys):
    missing = tmp_path / "never-written" / "comprehension.json"
    monkeypatch.setattr(cq, "_ARTIFACT_PATH", str(missing))
    monkeypatch.setattr(cq, "assess_doors", lambda: {"expected": 6})  # writes nothing to disk
    assert cq.main() == 1
    assert "was not written" in capsys.readouterr().out


def test_main_returns_one_when_assess_doors_raises_before_writing(tmp_path, monkeypatch, capsys):
    missing = tmp_path / "comprehension.json"

    def _boom():
        raise RuntimeError("simulated crash before the artifact was written")

    monkeypatch.setattr(cq, "_ARTIFACT_PATH", str(missing))
    monkeypatch.setattr(cq, "assess_doors", _boom)
    assert cq.main() == 1
    assert "crashed" in capsys.readouterr().out
