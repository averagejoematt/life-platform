"""tests/test_coach_plain_words_4649.py — a coach's watch list is words a friend can read (#4649).

THE RULE (lambdas/coach/plain_words.py), stated here because the issue asks for it in the
test: one ``focused_on_now`` item is served only when

    it is at most 80 characters,
    it has no word of 13 or more letters,
    it has at most one word of 11 or more letters, and
    it uses none of the reader-vocabulary registry's renamed or cut terms
    (site/data/glossary.json: reset, chronicle, model, as of, Third Wall, pillar, gate,
    character level).

No model is called anywhere in the check. The fixtures below are the eight items
/api/coach/sleep_coach and /api/coach/mind_coach served on 2026-10-04, word for word, and
the twelve authored stage items the other coaches served the same day.

What is held:
  * the rule itself, one reason per broken clause, and its copy of the registry;
  * the writer asks once more when an item fails, keeps the better draft, and stores only
    the items that pass;
  * the route withholds a stored item that fails (nothing stands in for it), serves the
    stage ladder beside a stance, and no longer carries ``working_hypotheses``.
"""

import json
import os
import sys

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "web"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "coach"))

import coach_history_summarizer as chs  # noqa: E402
from coach import plain_words, stance_lint  # noqa: E402
from web import site_api_coach as api  # noqa: E402

# Served 2026-10-04 under stance.focused_on_now — every one was written for a specialist.
SERVED_SLEEP = [
    "Whether the simplified three-word check is generating usable signal after protocol redesign",
    "Protein intake stabilization at threshold as a mechanistic lever for slow-wave architecture",
    "Thermal environment context to anchor deep sleep variability interpretation",
    "Arrival of Zone 2 training volume in Strava as the key predictor for adenosine-driven slow-wave increases",
    "Persistent sensor-subjective divergence from late September and whether it reflects device construction or genuine physiological decoupling",
]
SERVED_MIND = [
    "Whether the recovery spike represents genuine restoration or statistical mean reversion masking internal depletion—my prediction "
    "miss here forced me to recalibrate how much I trust device stability as a proxy for his actual state.",
    "The emotional texture of his journaling silence: does it feel heavy (something unready to name) or empty (no signal, no pull)? "
    "This distinction determines whether I should invite or wait.",
    "The three-way opposition now widened: recovery climbing, deep sleep declining, journaling flat despite protein recovery. Each "
    "signal is telling a different story, and I need to understand which one he believes.",
]
# The authored stage lists four coaches served the same day (config/coaches/*_stance.json).
SERVED_AUTHORED = [
    "clean, complete data capture",
    "resisting premature conclusions",
    "establishing baselines",
    "a complete baseline panel exists",
    "the obvious red flags (if any)",
    "supplement adherence as prescribed",
    "log food most days",
    "honest entries over complete ones",
    "no shame about what's in them",
    "weight trending down at all",
    "blood pressure and resting heart rate",
    "reducing metabolic load",
]
PLAIN = "whether more protein helps his deep sleep"
JARGON = SERVED_SLEEP[1]


def _body(resp):
    assert resp["statusCode"] == 200, resp
    return json.loads(resp["body"])


# ── the rule ─────────────────────────────────────────────────────────────────


def test_the_rule_withholds_what_was_served_and_keeps_plain_words():
    """Every item a specialist wrote fails; every plain authored item passes; each clause of
    the rule fails on its own. One test, every offender reported."""
    wrongly_kept = [item for item in SERVED_SLEEP + SERVED_MIND if plain_words.is_plain(item)]
    wrongly_dropped = [(item, plain_words.reasons(item)) for item in SERVED_AUTHORED + [PLAIN] if not plain_words.is_plain(item)]
    assert not wrongly_kept and not wrongly_dropped, (wrongly_kept, wrongly_dropped)
    # the numbers the rule is stated with
    assert (plain_words.MAX_CHARS, plain_words.LONG_WORD, plain_words.MAX_LONG_WORDS, plain_words.TOO_LONG_WORD) == (80, 11, 1, 13)
    # each clause, alone
    assert plain_words.is_plain("go " * 26 + "on") and not plain_words.is_plain("go " * 26 + "on.")  # 80 and 81 characters
    assert plain_words.reasons("the interpretation of his sleep") == ["a word of 13 or more letters: interpretation"]
    assert plain_words.is_plain("how his environment affects sleep")  # one long word is allowed
    assert plain_words.reasons("environment and variability") == ["more than 1 word of 11 or more letters: environment, variability"]
    assert plain_words.reasons("whether my model of his sleep holds") == ["a word the site does not use with readers: model"]
    assert plain_words.is_plain("whether the remodel of his week holds")  # word-bounded: "remodel" is not "model"
    # a hyphenated compound is its parts, and an empty item is never plain
    assert plain_words.is_plain("sensor-against-feeling gaps")
    assert plain_words.reasons("") == ["empty"] and plain_words.reasons(None) == ["empty"]
    # the list helpers keep order, drop the rest, and replace nothing
    mixed = [PLAIN, JARGON, "", "log food most days"]
    assert plain_words.plain_items(mixed) == [PLAIN, "log food most days"]
    assert plain_words.failing(mixed) == [JARGON]
    assert plain_words.plain_items(None) == [] and plain_words.failing("not a list") == []


def test_the_refused_terms_are_the_reader_vocabulary_registry():
    """plain_words keeps a copy because a Lambda cannot read site/. This holds the copy equal
    to the registry's rename and cut rulings, so there is one vocabulary, not two."""
    with open(os.path.join(_REPO, "site", "data", "glossary.json"), encoding="utf-8") as f:
        ruled = [t["term"] for t in json.load(f)["terms"] if t.get("ruling") in ("rename", "cut")]
    assert ruled, "the registry lists no renamed or cut term — the derivation has gone blind"
    assert list(plain_words.REGISTRY_TERMS) == ruled, "copy the registry's rename/cut terms into plain_words.REGISTRY_TERMS"
    assert {"model", "chronicle"} <= set(plain_words.REGISTRY_TERMS)


# ── the writer ───────────────────────────────────────────────────────────────


def _draft(focus):
    return {"headline_read": "His sleep base is forming.", "focused_on_now": list(focus), "stage": {"label": "foundation"}}


def test_the_prompt_asks_for_plain_words_and_states_the_cap():
    prompt = chs.STANCE_SYSTEM_PROMPT
    assert "GENERAL READER" in prompt and "a friend with no training in this field" in prompt
    assert f"{plain_words.MAX_CHARS} characters" in prompt
    assert "An item that is not plain is not shown at all." in prompt


def test_the_writer_asks_once_more_keeps_the_better_draft_and_stores_only_plain_items(monkeypatch):
    calls = []

    def fake(responses):
        def _call(**k):
            calls.append(k)
            return responses[min(len(calls), len(responses)) - 1]

        return _call

    # 1) a jargon item triggers ONE retry that names the item; the plainer retry is kept
    monkeypatch.setattr(chs, "_call_haiku", fake([_draft([JARGON, PLAIN]), _draft([PLAIN, "log food most days"])]))
    out = chs._generate_stance("sleep_coach", {"corrections_made": []}, {}, None)
    assert len(calls) == 2
    assert "STRICT CORRECTION" in calls[1]["user_message"] and JARGON in calls[1]["user_message"]
    assert out["focused_on_now"] == [PLAIN, "log food most days"]

    # 2) a plain draft costs no second call
    calls.clear()
    monkeypatch.setattr(chs, "_call_haiku", fake([_draft([PLAIN])]))
    chs._generate_stance("sleep_coach", {"corrections_made": []}, {}, None)
    assert len(calls) == 1

    # 3) a retry that is no plainer is not kept, and never a third call
    calls.clear()
    monkeypatch.setattr(chs, "_call_haiku", fake([_draft([PLAIN, JARGON]), _draft([JARGON, SERVED_SLEEP[2]])]))
    out = chs._generate_stance("sleep_coach", {"corrections_made": []}, {}, None)
    assert len(calls) == 2 and out["focused_on_now"] == [PLAIN, JARGON]

    # 4) whatever still fails is dropped at the write: both stored rows carry only plain items
    written = []
    monkeypatch.setattr(chs, "_put_item", lambda item: written.append(item) or True)
    assert chs._write_stance("sleep_coach", dict(out, as_of="2026-10-04"))
    assert [w["sk"] for w in written] == ["STANCE#2026-10-04", "STANCE#latest"]
    assert [w["focused_on_now"] for w in written] == [[PLAIN], [PLAIN]]

    # the retry rule, directly: a leaked number outranks plainness; a tie goes to more plain items
    leaky = {"headline_read": "RHR 53 bpm, steady", "focused_on_now": [PLAIN]}
    clean = {"headline_read": "steady", "focused_on_now": [JARGON]}
    assert stance_lint.retry_is_better(clean, leaky) and not stance_lint.retry_is_better(leaky, clean)
    assert not stance_lint.retry_is_better("not json", clean)
    assert stance_lint.self_correction(_draft([PLAIN])) == ""
    both = stance_lint.self_correction({"headline_read": "RHR 53 bpm", "focused_on_now": [JARGON]})
    assert "ZERO numbers" in both and JARGON in both


# ── the route ────────────────────────────────────────────────────────────────


def _stored_stance(focus):
    return {
        "headline_read": "I am waiting on steadier nights before I say more.",
        "focused_on_now": list(focus),
        "set_aside_for_now": ["one bad night"],
        "stage": {"label": "Waiting on steadier nights", "rationale": "Too few clean nights so far."},
        "how_my_read_changed": "",
        "confidence_note": "Low.",
        "as_of": "2026-10-04",
    }


def test_the_route_withholds_a_stored_jargon_item_and_serves_the_ladder_beside_the_stance(monkeypatch):
    """Fixture = the live 2026-10-04 sleep stance's own watch list plus one plain item."""
    monkeypatch.setattr(api, "_stance_latest", lambda cid: _stored_stance(SERVED_SLEEP + [PLAIN]) if cid == "sleep_coach" else None)
    data = _body(api.handle_coach({"rawPath": "/api/coach/sleep_coach"}))
    st = data["stance"]
    # the coach's own stance, with only the readable item left and nothing put in its place
    assert st["source"] == "stance" and st["as_of"] == "2026-10-04"
    assert st["focused_on_now"] == [PLAIN]
    # …and the author's stage ladder beside it: the same five keys the ladder-only shape carries
    assert st["band_metric"] == "weight_lbs" and st["rung"]["stage_id"] == "foundation"
    assert len(st["ladder"]) >= 2 and all(set(s) == {"stage_id", "headline"} for s in st["ladder"])
    assert "graduation_gate" in st and st["current_value"]
    assert "_authored_headline" not in st
    # the stance's own stage is not overwritten by the ladder's
    assert st["stage"]["label"] == "Waiting on steadier nights"
    # working_hypotheses left the contract (it was [] for every coach: the read's Limit ran
    # before the phase filter, and the rows it would serve pass no reader check)
    assert "working_hypotheses" not in data

    # every stored item unreadable -> an empty list, never a filler line
    monkeypatch.setattr(api, "_stance_latest", lambda cid: _stored_stance(SERVED_SLEEP))
    assert _body(api.handle_coach({"rawPath": "/api/coach/sleep_coach"}))["stance"]["focused_on_now"] == []

    # a coach with no stance keeps the ladder-only shape, unchanged; the lead still has neither
    monkeypatch.setattr(api, "_stance_latest", lambda cid: None)
    ladder_only = _body(api.handle_coach({"rawPath": "/api/coach/physical_coach"}))
    assert ladder_only["stance"]["source"] == "ladder" and ladder_only["stance"]["ladder"]
    assert "_authored_headline" not in ladder_only["stance"] and "working_hypotheses" not in ladder_only
    lead = _body(api.handle_coach({"rawPath": "/api/coach/eli_marsh"}))
    assert lead["stance"] == {"source": "none", "headline_read": "", "stage": {}} and "working_hypotheses" not in lead

    # /api/coach_team reads `rung` to tell a scaffold from a stance: _stance_block does not gain it
    monkeypatch.setattr(api, "_stance_latest", lambda cid: _stored_stance([PLAIN, JARGON]))
    block = api._stance_block("sleep_coach", 306)
    assert "rung" not in block and "ladder" not in block and block["focused_on_now"] == [PLAIN]
