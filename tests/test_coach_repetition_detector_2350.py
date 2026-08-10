#!/usr/bin/env python3
"""tests/test_coach_repetition_detector_2350.py — #2350 self-repetition detector.

Mutation-proof contracts (the issue's acceptance list, made executable):

  * a genuinely repeated output MUST fire the detector, and the finding must
    NAME the earlier output it resembles with the score (checkable, not
    asserted);
  * a paraphrase below threshold must NOT fire;
  * the threshold is DERIVED from the measured pairwise distribution of the
    coach's own history (stated derivation, with n) — a repetitive corpus earns
    a higher bar than a diverse one, clamped to the stated domain floor/ceiling;
  * missing/short history or an internal failure yields verdict=None — absence,
    never a green "novel" (ADR-104/#2350 fail-soft clause);
  * the quality-gate wiring is advisory: the `repetition` section is attached
    to the report and never flips `passed`, and a DDB failure degrades to an
    honest no-verdict section.

Everything is offline: the detector is pure, and the gate wiring is exercised
with module-attribute fakes (no boto3 endpoints, no LLM).
"""

import os
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LAMBDAS = os.path.join(ROOT, "lambdas")
if LAMBDAS not in sys.path:
    sys.path.insert(0, LAMBDAS)

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from coach import coach_repetition_detector as repdet  # noqa: E402

# ──────────────────────────────────────────────────────────────────────────────
# Fixture history — 8 distinct daily-commentary-shaped outputs (same domain,
# shared vocabulary, different phrasing), each comfortably over MIN_TOKENS.
# ──────────────────────────────────────────────────────────────────────────────

HISTORY_TEXTS = [
    "Recovery came in at 61 percent this morning with HRV holding near your baseline. "
    "I want to see how the deadlift session lands before we judge the week — log the RPE honestly tonight.",
    "Sleep told the story today: six hours and ten minutes with a late bedtime, and the "
    "readiness number followed it down. Protect the 10pm wind-down tonight and we reassess tomorrow.",
    "Zone 2 volume is quietly stacking up — three sessions this week, ninety-eight minutes total. "
    "The aerobic base work is the least glamorous thing you do and it is paying for everything else.",
    "Your squat triple moved well on video, but the bar path drifted forward on the last rep. "
    "Cue the mid-foot pressure tomorrow and keep the load where it is for one more session.",
    "Glucose stayed in range all day except the 3pm spike after the flat white and pastry. "
    "That pattern has shown up twice now; pair the coffee with protein and watch what happens.",
    "The strain-to-recovery ratio ran hot for the third consecutive day. Nothing is broken, "
    "but the trend line says take the optional rest day rather than banking another hard run.",
    "Body weight ticked down again and the seven-day average is now below the phase target. "
    "The deficit is doing its job; the priority this week is keeping protein at the floor.",
    "Mood scores and training quality moved together again this week — the correlation keeps "
    "reappearing whenever bedtime slips past eleven. The lever is boring and it is bedtime.",
]


def _history(texts=None, prefix="OUTPUT#2026-07-"):
    texts = HISTORY_TEXTS if texts is None else texts
    return [{"id": f"{prefix}{i + 1:02d}#daily", "content": t} for i, t in enumerate(texts)]


# ──────────────────────────────────────────────────────────────────────────────
# Pure-function sanity
# ──────────────────────────────────────────────────────────────────────────────


def test_normalize_tokens_strips_punctuation_and_case():
    assert repdet.normalize_tokens("HRV, holding — near baseline!") == ["hrv", "holding", "near", "baseline"]


def test_similarity_identical_text_is_one():
    sim = repdet.similarity(HISTORY_TEXTS[0], HISTORY_TEXTS[0])
    assert sim["shingle_jaccard"] == 1.0
    assert sim["token_jaccard"] == 1.0


def test_similarity_unrelated_same_domain_prose_is_low():
    # Two honest, different outputs about the same life share vocabulary but
    # not phrasing — the flagging metric must stay under the domain floor.
    sim = repdet.similarity(HISTORY_TEXTS[1], HISTORY_TEXTS[6])
    assert sim["shingle_jaccard"] < repdet.THRESHOLD_FLOOR


# ──────────────────────────────────────────────────────────────────────────────
# The acceptance pair: verbatim repeat fires, paraphrase does not
# ──────────────────────────────────────────────────────────────────────────────


def test_verbatim_repeat_fires_and_names_the_earlier_output():
    candidate = HISTORY_TEXTS[3]  # the coach says the squat thing again, word for word
    report = repdet.detect(candidate, _history())
    assert report["status"] == "ok"
    assert report["verdict"] == "repeat"
    assert report["score"] == 1.0
    # The claim is checkable: the finding names the resembled output + score.
    assert report["most_similar"]["id"] == "OUTPUT#2026-07-04#daily"
    assert "OUTPUT#2026-07-04#daily" in report["finding"]
    assert str(report["threshold"]["threshold"]) in report["finding"] or "threshold" in report["finding"]
    assert report["advisory"] is True


def test_near_verbatim_repeat_with_cosmetic_edits_still_fires():
    # "Nine weeks running" repetition is rarely byte-identical — punctuation and
    # a couple of word swaps must not launder it.
    candidate = HISTORY_TEXTS[3].replace("tomorrow", "on Tuesday").replace("triple", "triple!")
    report = repdet.detect(candidate, _history())
    assert report["verdict"] == "repeat"
    assert report["most_similar"]["id"] == "OUTPUT#2026-07-04#daily"
    assert report["score"] >= report["threshold"]["threshold"]


def test_paraphrase_below_threshold_does_not_fire():
    # Same substance as HISTORY_TEXTS[3], genuinely re-written.
    candidate = (
        "Watched the video of today's three heavy squats: solid speed overall, though on the "
        "final repetition the barbell wandered toward your toes. Next session, think about "
        "pressure through the middle of the foot, and do not add weight yet."
    )
    report = repdet.detect(candidate, _history())
    assert report["status"] == "ok"
    assert report["verdict"] == "novel"
    assert report["score"] < report["threshold"]["threshold"]


# ──────────────────────────────────────────────────────────────────────────────
# Threshold derivation (ADR-105)
# ──────────────────────────────────────────────────────────────────────────────


def test_threshold_is_derived_and_stated_with_n():
    report = repdet.detect(HISTORY_TEXTS[0], _history())
    t = report["threshold"]
    n = len(HISTORY_TEXTS)
    assert t["n_pairs"] == n * (n - 1) // 2
    assert t["baseline_k"] == repdet.BASELINE_K
    assert "mean" in t["derivation"] and str(t["n_pairs"]) in t["derivation"]
    assert repdet.THRESHOLD_FLOOR <= t["threshold"] <= repdet.THRESHOLD_CEILING


def test_repetitive_corpus_earns_higher_threshold_than_diverse_one():
    diverse = [repdet.shingle_set(repdet.normalize_tokens(t)) for t in HISTORY_TEXTS]
    # A corpus where the coach half-repeats itself constantly: every output is
    # one of the same texts with a tweaked tail.
    repetitive_texts = [HISTORY_TEXTS[0] + f" Also, day {i}, keep the streak alive and log it." for i in range(8)]
    repetitive = [repdet.shingle_set(repdet.normalize_tokens(t)) for t in repetitive_texts]
    t_diverse = repdet.derive_threshold(diverse)["threshold"]
    t_repetitive = repdet.derive_threshold(repetitive)["threshold"]
    assert t_repetitive > t_diverse
    # ...but the ceiling means a near-duplicate still fires even there:
    assert t_repetitive <= repdet.THRESHOLD_CEILING
    report = repdet.detect(repetitive_texts[0], _history(repetitive_texts))  # exact dup in history
    assert report["verdict"] == "repeat"
    assert report["score"] == 1.0


def test_floor_clamp_on_maximally_diverse_corpus():
    disjoint = [
        "alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima mike "
        "november oscar papa quebec romeo sierra tango uniform victor whiskey xray yankee",
        "one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
        "fifteen sixteen seventeen eighteen nineteen twenty twentyone twentytwo twentythree twentyfour",
        "red orange yellow green blue indigo violet crimson scarlet amber emerald teal "
        "azure navy magenta maroon coral salmon ivory beige tan khaki gold silver",
        "monday tuesday wednesday thursday friday saturday sunday january february march "
        "april may june july august september october november december spring summer autumn winter solstice",
        "lion tiger bear wolf fox eagle hawk owl salmon trout bass pike deer elk moose "
        "bison otter beaver badger lynx cougar raven crow heron",
    ]
    sets = [repdet.shingle_set(repdet.normalize_tokens(t)) for t in disjoint]
    t = repdet.derive_threshold(sets)
    assert t["baseline_mean"] == 0.0
    assert t["threshold"] == repdet.THRESHOLD_FLOOR  # clamp, not mean+k*std=0


# ──────────────────────────────────────────────────────────────────────────────
# Honest absence — never a green "no repetition"
# ──────────────────────────────────────────────────────────────────────────────


def test_insufficient_history_yields_no_verdict():
    report = repdet.detect(HISTORY_TEXTS[0], _history(HISTORY_TEXTS[:3]))  # 3 pairs < MIN_BASELINE_PAIRS
    assert report["status"] == "insufficient_history"
    assert report["verdict"] is None
    assert report.get("score") is None


def test_empty_history_yields_no_verdict():
    report = repdet.detect(HISTORY_TEXTS[0], [])
    assert report["verdict"] is None


def test_short_candidate_yields_no_verdict():
    report = repdet.detect("Nice work today.", _history())
    assert report["status"] == "insufficient_text"
    assert report["verdict"] is None


def test_short_history_entries_are_excluded_not_counted():
    texts = ["ok", "great job", None] + HISTORY_TEXTS[:3]
    entries = [{"id": f"OUTPUT#2026-07-{i:02d}", "content": t} for i, t in enumerate(texts)]
    report = repdet.detect(HISTORY_TEXTS[0], entries)
    assert report["status"] == "insufficient_history"
    assert report["n_history"] == 3


def test_detect_never_raises_on_garbage():
    for bad in [None, 123, ["x"], {"content": "y"}]:
        report = repdet.detect(bad, _history())
        assert report["verdict"] is None
    report = repdet.detect(HISTORY_TEXTS[0], [None, {"nope": 1}, {"id": None, "content": None}])
    assert report["verdict"] is None


# ──────────────────────────────────────────────────────────────────────────────
# Quality-gate wiring — advisory, deterministic-first, fail-soft
# ──────────────────────────────────────────────────────────────────────────────


@pytest.fixture()
def gate(monkeypatch):
    from coach import coach_quality_gate as g

    # No LLM: canned verdict; no S3: voice_spec passed in event; no cross-coach.
    monkeypatch.setattr(g, "_run_quality_gate", lambda *a, **k: {"passed": True, "score": 88, "suggestions": []})
    return g


def _gate_event(text):
    # voice_spec is non-empty so the handler never falls back to the S3 load.
    return {"coach_id": "training_coach", "output_text": text, "voice_spec": {"persona": {"name": "t"}}, "skip_cross_coach": True}


def _ddb_items(entries):
    """The gate reads DynamoDB items (sk/content), not detector entries (id/content)."""
    return [{"sk": h["id"], "content": h["content"]} for h in entries]


def test_gate_attaches_repetition_section_and_does_not_flip_passed(gate, monkeypatch):
    monkeypatch.setattr(gate, "_query_begins_with", lambda pk, prefix, **k: _ddb_items(_history()))
    result = gate.lambda_handler(_gate_event(HISTORY_TEXTS[3]), None)
    rep = result["repetition"]
    assert rep["verdict"] == "repeat"
    assert rep["most_similar"]["id"] == "OUTPUT#2026-07-04#daily"
    assert result["passed"] is True  # advisory: a repeat verdict never blocks (ADR-108 posture)


def test_gate_repetition_queries_own_partition(gate, monkeypatch):
    seen = {}

    def fake_query(pk, prefix, **k):
        seen["pk"], seen["prefix"] = pk, prefix
        return _ddb_items(_history())

    monkeypatch.setattr(gate, "_query_begins_with", fake_query)
    gate.lambda_handler(_gate_event(HISTORY_TEXTS[0]), None)
    assert seen["pk"] == "COACH#training_coach"
    assert seen["prefix"] == "OUTPUT#"


def test_gate_excludes_same_day_identical_self_record(gate, monkeypatch):
    from datetime import datetime, timezone

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    candidate = HISTORY_TEXTS[3]
    items = [{"sk": f"OUTPUT#{today}#daily", "content": candidate}] + _ddb_items(_history(HISTORY_TEXTS[:3] + HISTORY_TEXTS[4:]))
    # History no longer contains texts[3]-as-earlier-output — only the same-day
    # self-record, which must be excluded → verdict must NOT be "repeat" at 1.0.
    monkeypatch.setattr(gate, "_query_begins_with", lambda pk, prefix, **k: items)
    result = gate.lambda_handler(_gate_event(candidate), None)
    rep = result["repetition"]
    assert rep["most_similar"]["shingle_jaccard"] < 1.0
    assert rep["verdict"] == "novel"


def test_gate_ddb_failure_degrades_to_no_verdict_not_green(gate, monkeypatch):
    def boom(pk, prefix, **k):
        raise RuntimeError("ddb down")

    monkeypatch.setattr(gate, "_query_begins_with", boom)
    result = gate.lambda_handler(_gate_event(HISTORY_TEXTS[0]), None)
    rep = result["repetition"]
    assert rep["status"] == "error"
    assert rep["verdict"] is None
    assert result["passed"] is True  # gate itself unaffected


def test_gate_wiring_is_actually_load_bearing(gate, monkeypatch):
    # Mutation guard for the wiring itself: if _self_repetition_report were
    # unplugged, the report would carry no repetition key at all.
    monkeypatch.setattr(gate, "_query_begins_with", lambda pk, prefix, **k: _ddb_items(_history()))
    result = gate.lambda_handler(_gate_event(HISTORY_TEXTS[0]), None)
    assert "repetition" in result
    assert result["repetition"]["status"] in {"ok", "insufficient_history", "insufficient_text", "error"}
