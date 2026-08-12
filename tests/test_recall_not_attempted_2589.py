"""tests/test_recall_not_attempted_2589.py — #2589: the THIRD retrieval outcome.

#2560 shipped `retrieval_log_line` so #2347's corpus-scope decision would have hit/miss
data, and #2589 was filed reporting the line had recorded nothing at all in the week
since. **The report's premise was wrong, and how it was wrong is worth pinning here:**

  * The line WAS firing. The 2026-08-11 17:00 UTC daily brief emitted seven of them,
    one per coach, all `outcome=miss resolved=0 threshold=0.75 top_similarity=n/a`.
  * `aws logs filter-log-events --no-paginate` is what reported zero. CloudWatch scans
    log streams incrementally and returns partial (often EMPTY) pages with a
    `nextToken`; `--no-paginate` takes only the first page and stops. The same window
    with no filter at all returned 4 events, against 107 in a single stream read
    directly with `get-log-events`. `--no-paginate` is the correct fix for
    `--query 'length(events)'` printing one number PER PAGE, and the wrong tool for an
    existence question — for those, let the CLI auto-paginate and count the merged
    `events` list once.

So NO early return was firing, and this file does not pretend otherwise. What #2589
found that survives measurement is the STRUCTURAL half of its own report: the coach
entry point had exits that emit nothing, and "nothing" is indistinguishable from "the
instrument is dead" — which is exactly the ambiguity #2560 set out to remove, one level
up the call stack. It was true by inspection whether or not it was firing that week, and
the false alarm is itself the evidence that a silent branch costs real investigation
time.

The guarantee these tests pin is therefore about SHAPE, not about a branch:
**no path out of the coach retrieval path is silent.** It is enforced by a
`try/finally`, so a future early return cannot opt out of it by forgetting to print.
`web/ask_retrieval.py` already had this shape (a `finally:` that logs a `status` on
every exit including `skipped:no-question` and `skipped:budget`) — audited as part of
this issue and found clean; it is the model the coach path now copies.
"""

import ai.ai_calls as ac
import ai.semantic_recall as sr
import pytest


@pytest.fixture
def _armed(monkeypatch):
    """Arm the real call path: budget open, embedding stubbed, retrieval stubbed.

    Deliberately the same shape as the #2347 fixture — the function is exercised
    through `ai_calls._semantic_recall_for_coach`, its production entry point, so these
    assertions cannot drift from what the daily brief actually runs.
    """
    import ai.bedrock_client as bc
    import ai.budget_guard as bg

    monkeypatch.setattr(bg, "allow", lambda *a, **k: True)
    monkeypatch.setattr(bc, "embed_text", lambda *a, **k: [0.1, 0.2, 0.3])
    monkeypatch.setattr(sr, "retrieve", lambda *a, **k: [])
    monkeypatch.setattr(sr, "recall_block", lambda p: "BLOCK" if p else "")
    return sr


def _call(capsys, *, query="how did the cut go", coach="nutrition"):
    block, got = ac._semantic_recall_for_coach(coach, query, table=object())
    return capsys.readouterr().out, block, got


def _outcomes(out):
    """Every `outcome=<x>` in the captured output — ONE regex for all three states.

    That a single pattern reads hit, miss and not_attempted is itself the contract:
    a scraper counting four weeks of #2347 data must not need to know which shape it
    is looking at.
    """
    import re

    return re.findall(r"semantic recall: outcome=(\w+)", out)


# ── the guarantee: no silent exit ───────────────────────────────────────────
def test_an_empty_query_is_a_recorded_outcome_not_silence(_armed, capsys):
    """THE regression this file exists for.

    Mutation-proof: delete the `finally:` from `recall_for_coach` and this goes red —
    the empty-query return produces no output whatsoever, exactly as it did on main.
    """
    out, block, got = _call(capsys, query="   ")
    assert (block, got) == ("", [])
    assert out.strip(), "an empty query exited SILENTLY — indistinguishable from recall never running"
    assert _outcomes(out) == ["not_attempted"]
    assert "reason=empty_query" in out


def test_a_budget_pause_is_a_recorded_outcome_not_silence(_armed, capsys, monkeypatch):
    """The second pre-retrieval return. Budget was RULED OUT as the live cause (SSM
    tier 1 < the band-2 cutoff), but a tier-2 month must not read as a dead instrument.

    Mutation-proof: force the guard closed and the line must name the budget — not
    merely say `not_attempted`, or an operator cannot tell a paused month from a bug.
    """
    import ai.budget_guard as bg

    monkeypatch.setattr(bg, "allow", lambda *a, **k: False)
    out, block, got = _call(capsys)
    assert (block, got) == ("", [])
    assert _outcomes(out) == ["not_attempted"]
    assert "reason=budget_paused" in out


def test_an_error_is_a_recorded_outcome_and_keeps_its_human_diagnostic(_armed, capsys, monkeypatch):
    """A raising retrieve must yield BOTH lines: the diagnostic carrying the exception
    MESSAGE (worth reading), and the outcome line carrying only its TYPE (worth
    counting). #2347's scrape must not have to parse free-form exception text.
    """
    monkeypatch.setattr(sr, "retrieve", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("ddb down")))
    out, block, got = _call(capsys)
    assert (block, got) == ("", [])
    assert "unavailable (non-blocking): ddb down" in out
    assert _outcomes(out) == ["not_attempted"]
    assert "reason=error:RuntimeError" in out


def test_a_failure_after_retrieval_does_not_publish_a_hit_or_miss(_armed, capsys, monkeypatch):
    """Ordering guard: `outcome_line` is assigned only after `recall_block` returns, so
    a render that blows up reports `not_attempted`, never a hit/miss for a retrieval
    that did not complete.

    Mutation-proof: hoist the `retrieval_log_line` assignment above `recall_block` and
    this goes red — the run publishes `outcome=hit` for output the coach never got.
    """
    monkeypatch.setattr(sr, "retrieve", lambda *a, **k: [{"similarity": 0.9, "date": "2026-01-01"}])
    monkeypatch.setattr(sr, "recall_block", lambda p: (_ for _ in ()).throw(ValueError("bad precedent")))
    out, block, got = _call(capsys)
    assert (block, got) == ("", [])
    assert _outcomes(out) == ["not_attempted"]
    assert "reason=error:ValueError" in out


def test_a_missing_module_still_reports_not_attempted(capsys, monkeypatch):
    """The ONE exit `semantic_recall` cannot instrument — its own import failing. The
    `ai_calls` wrapper covers it, in the module's own vocabulary.

    Mutation-proof: drop the second print from the wrapper's except and this goes red.

    An ImportError raised BY `recall_for_coach` is the same observable the wrapper sees
    when the `from ai import semantic_recall` line itself fails, and it does not require
    breaking `__import__` for the whole session to produce it.
    """
    monkeypatch.setattr(sr, "recall_for_coach", lambda *a, **k: (_ for _ in ()).throw(ImportError("no module")))
    out, block, got = _call(capsys)
    assert (block, got) == ("", [])
    assert _outcomes(out) == ["not_attempted"]
    assert "reason=no_module" in out


# ── the states still separate ───────────────────────────────────────────────
def test_hit_and_miss_are_unchanged_by_the_third_state(_armed, capsys, monkeypatch):
    """#2560's two outcomes must read exactly as before — the third state is additive.
    Regression guard against a refactor that routes a real retrieval through the
    not_attempted line."""
    out, block, got = _call(capsys)
    assert _outcomes(out) == ["miss"] and "resolved=0" in out and (block, got) == ("", [])

    monkeypatch.setattr(sr, "retrieve", lambda *a, **k: [{"similarity": 0.81}, {"similarity": 0.93}])
    out, block, got = _call(capsys)
    assert _outcomes(out) == ["hit"] and "resolved=2" in out and "top_similarity=0.93" in out
    assert block == "BLOCK" and len(got) == 2


def test_exactly_one_outcome_line_per_call_on_every_branch(_armed, capsys, monkeypatch):
    """Double-counting is the mirror failure of silence: a state that emits two outcome
    lines inflates whichever bucket #2347 is measuring. Every branch emits exactly one.
    """
    import ai.budget_guard as bg

    assert len(_outcomes(_call(capsys, query="")[0])) == 1
    assert len(_outcomes(_call(capsys)[0])) == 1
    monkeypatch.setattr(sr, "retrieve", lambda *a, **k: [{"similarity": 0.8}])
    assert len(_outcomes(_call(capsys)[0])) == 1
    monkeypatch.setattr(sr, "retrieve", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    assert len(_outcomes(_call(capsys)[0])) == 1
    monkeypatch.setattr(bg, "allow", lambda *a, **k: False)
    assert len(_outcomes(_call(capsys)[0])) == 1


# ── the renderer, as a unit ─────────────────────────────────────────────────
def test_not_attempted_publishes_no_fabricated_zero():
    """ADR-104. `resolved=0` is a MEASURED result of a retrieval that ran; a retrieval
    that never ran measured nothing, and reporting 0 here would silently inflate the
    miss denominator #2347's decision rests on.

    Mutation-proof: emit `resolved=0` instead of `n/a` and this goes red.
    """
    line = sr.retrieval_not_attempted_line("sleep", sr.REASON_EMPTY_QUERY)
    assert "resolved=n/a" in line and "resolved=0" not in line
    assert "top_similarity=n/a" in line and "top_similarity=0" not in line


def test_not_attempted_still_publishes_the_knowable_threshold():
    """`threshold` is knowable WITHOUT retrieving, so it is published — keeping the
    field set identical across all three outcomes. Read from the module so a retuned
    DEFAULT_THRESHOLD cannot leave the line stating a stale number."""
    assert f"threshold={sr.DEFAULT_THRESHOLD}" in sr.retrieval_not_attempted_line("sleep", "empty_query")


def test_one_regex_reads_all_three_outcomes():
    """The scraper contract: same prefix, same field order, one pattern."""
    lines = [
        sr.retrieval_log_line("sleep", [{"similarity": 0.9}]),
        sr.retrieval_log_line("sleep", []),
        sr.retrieval_not_attempted_line("sleep", sr.REASON_BUDGET_PAUSED),
    ]
    assert [_outcomes(line)[0] for line in lines] == [sr.OUTCOME_HIT, sr.OUTCOME_MISS, sr.OUTCOME_NOT_ATTEMPTED]
    for line in lines:
        assert line.startswith("[COACH-V2:sleep] semantic recall: outcome=")
        assert "threshold=" in line and "top_similarity=" in line


def test_the_outcome_vocabulary_is_named_not_inlined():
    """A scraper and the emitter must share ONE spelling of each outcome. Mutation-proof:
    hardcode 'hit'/'miss' back into the f-strings and the constants stop being load-bearing
    — this pins them to the rendered output instead of merely asserting they exist."""
    assert (sr.OUTCOME_HIT, sr.OUTCOME_MISS, sr.OUTCOME_NOT_ATTEMPTED) == ("hit", "miss", "not_attempted")
    assert f"outcome={sr.OUTCOME_HIT}" in sr.retrieval_log_line("c", [{"similarity": 0.9}])
    assert f"outcome={sr.OUTCOME_MISS}" in sr.retrieval_log_line("c", [])
    assert f"outcome={sr.OUTCOME_NOT_ATTEMPTED}" in sr.retrieval_not_attempted_line("c", "r")


# ── the sibling reader path (acceptance box 5) ──────────────────────────────
def test_ask_retrieval_has_no_silent_exit():
    """Audited as part of #2589 and found CLEAN — recorded here so the next reader does
    not have to re-audit it, and so a refactor that removes the `finally:` goes red.

    `ask_retrieval.retrieve_block` logs its telemetry in a `finally:`, so its
    no-question, budget and error exits each carry a `status=` — the same guarantee the
    coach path only got here. This test is the structural proof, not prose.
    """
    import ast
    import inspect

    from web import ask_retrieval

    fn = ast.parse(inspect.getsource(ask_retrieval.retrieve_block).lstrip()).body[0]
    tries = [n for n in ast.walk(fn) if isinstance(n, ast.Try) and n.finalbody]
    assert tries, "retrieve_block lost its `finally:` — its early returns are silent again"
    src = inspect.getsource(ask_retrieval.retrieve_block)
    for status in ("skipped:no-question", "skipped:budget", "skipped:error:"):
        assert status in src, f"the {status} exit no longer names itself"
