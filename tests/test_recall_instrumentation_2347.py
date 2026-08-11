"""tests/test_recall_instrumentation_2347.py — #2347 recall hit/miss instrumentation.

#2347 asks whether semantic recall's corpus scope should stay chronicle-only. AC1
needs ~4 weeks of retrieval outcomes to decide — and NOTHING was recording them.
Measured on main before this change:

  - `lambdas/ai/semantic_recall.py` contains no `put_metric_data`, no EMF block, and
    no `print` at all, so the module itself leaves no trace of an outcome.
  - The single trace in the whole tree was one `print` in `ai_calls._semantic_recall_for_coach`
    that sat INSIDE `if precedents:` — so it fired only on a HIT.

The consequence is the thing this file pins: a run that retrieved NOTHING was
indistinguishable from a run where recall never executed. The miss is the outcome
the corpus-scope decision actually turns on, and it was the one outcome not logged.

This does NOT close #2347 — AC1 still needs the four weeks of data. It makes the
four weeks *collectable*, so the review does not find the same absence again.
"""

import ai.ai_calls as ac
import pytest


@pytest.fixture
def _armed(monkeypatch):
    """Arm the real call path: budget open, embedding stubbed, table supplied.

    Patches the modules `_semantic_recall_for_coach` actually imports (`ai.bedrock_client`,
    `ai.semantic_recall`) rather than rebuilding a parallel call shape — the function is
    exercised through its real entry point so this cannot drift from production.
    """
    import ai.bedrock_client as bc
    import ai.budget_guard as bg
    import ai.semantic_recall as sr

    monkeypatch.setattr(bg, "allow", lambda *a, **k: True)
    monkeypatch.setattr(bc, "embed_text", lambda *a, **k: [0.1, 0.2, 0.3])
    return sr


def _call(capsys, sr, monkeypatch, precedents):
    monkeypatch.setattr(sr, "retrieve", lambda *a, **k: precedents)
    monkeypatch.setattr(sr, "recall_block", lambda p: "BLOCK" if p else "")
    block, got = ac._semantic_recall_for_coach("nutrition", "how did the cut go", table=object())
    return capsys.readouterr().out, block, got


def test_a_miss_is_logged_at_all(_armed, capsys, monkeypatch):
    """THE regression this file exists for: zero precedents must still emit a line.

    Mutation-proof: restore the old `if precedents:` guard around the print and this
    assertion goes red — the whole output is empty on a miss.
    """
    out, block, got = _call(capsys, _armed, monkeypatch, [])
    assert out.strip(), "a miss emitted NOTHING — the zero-hit case is invisible again"
    assert "semantic recall:" in out


def test_a_miss_is_labelled_a_miss_not_merely_a_zero(_armed, capsys, monkeypatch):
    """`outcome=` is what makes a log line greppable across four weeks of CloudWatch.

    Mutation-proof: drop the `outcome=` field from the f-string and this goes red.
    """
    out, _, _ = _call(capsys, _armed, monkeypatch, [])
    assert "outcome=miss" in out
    assert "outcome=hit" not in out
    assert "resolved=0" in out


def test_a_hit_is_labelled_a_hit_and_carries_its_count(_armed, capsys, monkeypatch):
    """The opposite direction — a gate that is on but never distinguishes the two
    outcomes is the same blindness with more characters."""
    out, block, got = _call(capsys, _armed, monkeypatch, [{"similarity": 0.81}, {"similarity": 0.77}])
    assert "outcome=hit" in out
    assert "outcome=miss" not in out
    assert "resolved=2" in out
    assert block == "BLOCK" and len(got) == 2


def test_top_similarity_is_the_max_not_the_first(_armed, capsys, monkeypatch):
    """rank_precedents returns highest-first, but the log must not DEPEND on that
    ordering — a future change to tie-breaking would silently start publishing a
    non-maximal 'top'. Ordered worst-first here on purpose.

    Mutation-proof: change `max(...)` to `precedents[0]["similarity"]` → red.
    """
    out, _, _ = _call(capsys, _armed, monkeypatch, [{"similarity": 0.76}, {"similarity": 0.93}])
    assert "top_similarity=0.93" in out


def test_a_miss_publishes_no_similarity_number_at_all(_armed, capsys, monkeypatch):
    """ADR-104: an unmeasurable top cosine is absent, never a fabricated 0.0.

    rank_precedents drops sub-threshold docs before returning, so the top cosine of a
    MISS is genuinely unavailable without a second full cosine sweep of the corpus —
    a cost this deliberately does not pay on the hot path. `n/a` states that honestly.

    Mutation-proof: emit `top_similarity=0.0` on a miss and this goes red.
    """
    out, _, _ = _call(capsys, _armed, monkeypatch, [])
    assert "top_similarity=n/a" in out
    assert "top_similarity=0" not in out


def test_the_threshold_is_published_so_a_miss_is_interpretable(_armed, capsys, monkeypatch):
    """A miss count means nothing without the bar it missed. Read from the module so a
    retuned DEFAULT_THRESHOLD can never leave the log stating a stale number."""
    out, _, _ = _call(capsys, _armed, monkeypatch, [])
    assert f"threshold={_armed.DEFAULT_THRESHOLD}" in out


def test_recall_stays_fail_soft_and_never_raises_into_the_coach(_armed, capsys, monkeypatch):
    """Instrumentation must not become load-bearing: a raising retrieve still yields
    ("", []) exactly as before, and still says so."""
    monkeypatch.setattr(_armed, "retrieve", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("ddb down")))
    block, got = ac._semantic_recall_for_coach("nutrition", "q", table=object())
    out = capsys.readouterr().out
    assert (block, got) == ("", [])
    assert "unavailable (non-blocking)" in out


def test_semantic_recall_still_publishes_no_cloudwatch_metric():
    """Pins the measured premise this issue rests on, so a future reader does not have
    to re-derive it: recall emits a LOG LINE, not a metric. #2347's AC1 therefore has
    to scrape logs. If a real metric emitter is ever added, THIS test goes red and AC1
    should be re-scoped to read the metric instead."""
    import inspect

    import ai.semantic_recall as sr

    src = inspect.getsource(sr)
    # match a CALL, not the word — this module's own docstrings discuss the absence.
    assert "put_metric_data(" not in src
    assert '"_aws"' not in src  # no embedded-metric-format block


def test_the_line_is_built_in_semantic_recall_not_inlined_at_the_call_site():
    """`ai_calls.py` is size-baselined at 2396 lines, and this instrumentation is
    exactly the kind of thing that gets re-inlined there by a later edit. Delegation is
    the contract: the formatting lives beside retrieval, the call site just prints it.

    Mutation-proof: inline the f-string back into `_semantic_recall_for_coach` → red.
    """
    import inspect

    import ai.semantic_recall as sr

    assert callable(sr.retrieval_log_line)
    src = inspect.getsource(ac._semantic_recall_for_coach)
    assert "retrieval_log_line" in src
    assert "top_similarity=" not in src, "the log line was re-inlined into the baselined module"


def test_the_helper_is_pure_and_states_both_outcomes_standalone():
    """Called directly, with no coach machinery at all — the unit contract."""
    import ai.semantic_recall as sr

    miss = sr.retrieval_log_line("sleep", [])
    hit = sr.retrieval_log_line("sleep", [{"similarity": 0.76}, {"similarity": 0.93}])
    assert "outcome=miss" in miss and "resolved=0" in miss and "top_similarity=n/a" in miss
    assert "outcome=hit" in hit and "resolved=2" in hit and "top_similarity=0.93" in hit
    assert sr.retrieval_log_line("sleep", None).count("outcome=miss") == 1  # None is a miss, not a crash
