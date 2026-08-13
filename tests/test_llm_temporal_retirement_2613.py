"""#2613 (reopened) — retiring the pre-cycle-date temporal class from the LLM rubric.

PR #2618 shipped the ruling (the surface is correct: the trend clamps to genesis per
ADR-077 and is wake-date keyed per #1923) plus deterministic R6. The ruling did not
silence the model — measured at the real call site, 3/3 runs before the rubric clause,
3/3 with it, 4/5 with an in-payload disclosure as well, and 3/6 on a wider re-baseline
of the same code. The model re-derives the accusation from the payload's own
`trend_note` and quotes it approvingly while flagging.

So the class is retired the way #1922 retired `impossible_number`: code owns the
answerable question, the rubric stops asking it, and — because the category itself
survives for prose — `assess_prose` drops any finding that still comes back in the
retired locus × class.

These tests pin the three things that make the retirement honest:
  1. the rubric no longer asks for it, and names the owner;
  2. the drop is SCOPED — HTML pages, /api/coaches, and every non-date temporal
     finding on a strict payload all survive it;
  3. coverage did NOT drop — the genuine defects the retired clause promised to keep
     flagging (a clamp breach, a night more than one day pre-genesis) still red,
     deterministically, and are mutation-proven in both directions.

Every fixture date derives from a SYMBOLIC genesis: the ruling is about "the cycle
start", not about 2026-08-10, and ADR-077 moves genesis every cycle.

NB this suite does not sweep the source tree — it is a unit suite over two modules, so
it needs no `tests/conftest.py` registration.
"""

import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))

from operational import phase_plausibility as pp, reader_truth_qa as rt  # noqa: E402

GENESIS = "2027-03-01"
_G = date.fromisoformat(GENESIS)
SLEEP = "/api/sleep_detail"


def _d(offset):
    return (_G + timedelta(days=offset)).isoformat()


def _phase(day_n):
    return {
        "today": _d(day_n - 1),
        "start_date": GENESIS,
        "day_n": day_n,
        "pre_start": False,
        "days_until_start": 0,
    }


def _trend_row(offset):
    """A wake-date-keyed sleep_trend row: `sleep_start` is the previous evening's UTC instant."""
    return {"date": _d(offset), "hours": 7.2, "sleep_start": f"{_d(offset)}T05:05:46.420Z"}


def _payload(rows):
    return {"sleep_detail": {"as_of_date": _d(3), "frame": "last_night", "night_of": _d(2)}, "sleep_trend": rows}


def _finding(note, page=SLEEP, category="temporal_contradiction"):
    return {"page": page, "category": category, "severity": "high", "note": note}


# ── 1. the rubric no longer asks for the class, and names the owner ───────────


def test_rubric_no_longer_asks_the_llm_to_judge_payload_dates():
    prompt = rt.build_prompt([{"name": "x", "path": "/x", "prose": "hello"}], _phase(4))
    assert "/api/… PAYLOAD" in prompt or "/api/" in prompt
    assert "not yours" in prompt, "the prompt must hand the class over, not merely exempt one instance"
    # The two long genesis exemption clauses are gone: the model is told the question
    # is code's, not taught a longer list of shapes that are fine.
    assert "sleep_trend" not in prompt, "the retired clause named the field; retirement means it is not discussed"
    assert "clamp breach" not in prompt


def test_retirement_does_not_disturb_the_1922_retirement():
    assert "impossible_number" not in rt.CATEGORIES
    prompt = rt.build_prompt([{"name": "x", "path": "/x", "prose": "hello"}], _phase(4))
    assert '"impossible_number"' not in prompt
    assert "temporal_contradiction" in rt.CATEGORIES, "prose temporal contradictions stay the LLM's"


def test_the_two_passes_share_ONE_surface_list():
    from operational import qa_check_reader_truth as q

    assert q.STRICT_PLAUSIBILITY_APIS is rt.CODE_OWNED_TEMPORAL_SURFACES, (
        "the strict-swept set and the code-owned set must be the same object — a strict payload "
        "the rubric still judges (or vice versa) is the drift this derivation exists to prevent"
    )


# ── 2. the drop is scoped ─────────────────────────────────────────────────────


def test_the_live_false_positive_is_dropped():
    """The verbatim shape measured on 2026-08-13, with dates re-derived from the symbolic genesis."""
    note = (
        f"sleep_trend contains a row dated {_d(0)} with sleep_start {_d(0)}T05:05:46.420Z. Per the figure_scope "
        f"disclosure, sleep_trend rows are keyed by wake_date, so this row represents the night of {_d(-1)}. "
        f"However, the experiment started on {_d(0)} (Day 1)."
    )
    assert rt.is_code_owned_temporal(_finding(note), GENESIS) is True


def test_the_earlier_truncated_phrasings_are_the_same_class():
    for note in (
        f"sleep_trend contains three entries dated {_d(0)}, {_d(1)}, and {_d(2)}, but the experiment started {_d(0)}",
        f"sleep_trend contains 3 entries (dates {_d(0)}, {_d(1)}, {_d(2)}), but the sleep_start of the first",
        f"sleep_trend contains three rows dated {_d(0)}, {_d(1)}, and {_d(2)}, with the {_d(0)} row beginning {_d(-1)}",
    ):
        assert rt.is_code_owned_temporal(_finding(note), GENESIS) is True, note


def test_an_html_page_keeps_the_whole_class():
    note = f"the cockpit narrates a weigh-in on {_d(-9)}, nine days before the experiment began on {_d(0)}"
    assert rt.is_code_owned_temporal(_finding(note, page="/now/"), GENESIS) is False


def test_the_narrative_coaches_payload_keeps_the_whole_class():
    """/api/coaches is swept NON-strict, so R6/R7 never run there — the LLM is the only check."""
    note = f"a coach narrates progress measured on {_d(-4)} as this cycle's, but the cycle began {_d(0)}"
    assert rt.is_code_owned_temporal(_finding(note, page="/api/coaches"), GENESIS) is False


def test_an_in_cycle_temporal_finding_on_a_strict_payload_survives():
    """The summary/trend-row disagreement class the LLM caught on run 4 of the re-baseline."""
    note = (
        f"sleep_trend row dated {_d(3)} has sleep_start: null and all sleep metrics null, but the top-level "
        f"sleep_detail fields report sleep_score 82 for the same night"
    )
    assert rt.is_code_owned_temporal(_finding(note), GENESIS) is False


def test_a_word_number_span_on_a_strict_payload_survives():
    assert rt.is_code_owned_temporal(_finding("the note claims three weeks of trend data"), GENESIS) is False


def test_the_other_two_categories_survive_on_a_strict_payload():
    note = f"identical paragraph also on /api/vitals, both dated {_d(0)}"
    for cat in ("duplicated_narrative", "audience_violation"):
        assert rt.is_code_owned_temporal(_finding(note, category=cat), GENESIS) is False


def test_assess_prose_drops_the_class_and_keeps_the_rest(capsys):
    """End to end through the real assess_prose, with the model's reply stubbed.

    This one derives its dates from the LIVE `EXPERIMENT_START_DATE` rather than the
    symbolic genesis above: `assess_prose` resolves the cycle start through
    `phase_context`, so the fixture has to speak the same calendar it does. Still no
    literal — ADR-077 moves genesis every cycle and this follows it.
    """
    import json

    from common.constants import EXPERIMENT_START_DATE

    g = date.fromisoformat(EXPERIMENT_START_DATE)

    def gd(offset):
        return (g + timedelta(days=offset)).isoformat()

    reply = {
        "findings": [
            _finding(f"sleep_trend row dated {gd(0)} represents the night of {gd(-1)}, before the cycle start"),
            _finding(f"the {gd(3)} row is null while the summary reports a score for that night"),
            _finding(f"the cockpit narrates {gd(-9)}, before the cycle start", page="/now/"),
        ],
        "severity": "high",
    }

    def fake_invoke(body, model_name=None):
        return {"content": [{"type": "text", "text": json.dumps(reply)}]}

    pages = [{"name": n, "path": p, "prose": "x"} for n, p in (("s", SLEEP), ("c", "/now/"))]
    findings, errors = rt.assess_prose(pages, fake_invoke, today_iso=gd(3))
    assert errors == []
    notes = [f["note"] for f in findings]
    assert len(findings) == 2, notes
    assert any("null while the summary" in n for n in notes)
    assert any("the cockpit narrates" in n for n in notes)
    assert not any("before the cycle start" in n and "sleep_trend" in n for n in notes)
    assert "dropped a code-owned pre-cycle-date finding" in capsys.readouterr().out, "a drop must never be silent"


# ── 3. coverage did not drop: R6/R7 still red, mutation-proven ────────────────


def test_R6_is_clean_on_the_correct_genesis_payload():
    """The shape that provoked the false positive: rows from genesis forward, bedtimes the evening before."""
    findings = pp.check_payload(SLEEP, _payload([_trend_row(i) for i in range(4)]), 4, strict=True, start_date=GENESIS)
    assert findings == [], findings


def test_R6_reds_when_the_clamp_IS_broken():
    """MUTATION: break the ADR-077 clamp — a prior-cycle row reaches the live series."""
    rows = [_trend_row(-1)] + [_trend_row(i) for i in range(4)]
    findings = pp.check_payload(SLEEP, _payload(rows), 4, strict=True, start_date=GENESIS)
    assert len(findings) == 1, findings
    assert findings[0]["severity"] == "high" and findings[0]["category"] == "temporal_contradiction"
    assert _d(-1) in findings[0]["note"] and "predates the cycle start" in findings[0]["note"]


def test_R6_reds_on_a_deep_prior_cycle_row():
    findings = pp.check_payload(SLEEP, _payload([_trend_row(-40)]), 4, strict=True, start_date=GENESIS)
    assert len(findings) == 1 and _d(-40) in findings[0]["note"]


def test_R7_allows_the_wake_date_frame_and_reds_one_day_further_back():
    """The residual promise the retired clause made, now code's: genesis-1 is the frame, genesis-2 is a leak."""
    ok = pp.check_payload(SLEEP, {"night_of": _d(-1)}, 4, strict=True, start_date=GENESIS)
    assert ok == [], ok
    bad = pp.check_payload(SLEEP, {"night_of": _d(-2)}, 4, strict=True, start_date=GENESIS)
    assert len(bad) == 1 and bad[0]["severity"] == "high"
    assert "names a night before" in bad[0]["note"]


def test_R7_reads_a_sleep_start_timestamp_by_its_date_part():
    """MUTATION: a genesis-dated row whose bedtime is two nights early — the shape the clause promised to keep."""
    rows = [{"date": _d(0), "hours": 7.0, "sleep_start": f"{_d(-2)}T22:14:00.000Z"}]
    findings = pp.check_payload(SLEEP, _payload(rows), 4, strict=True, start_date=GENESIS)
    assert len(findings) == 1 and "sleep_start" in findings[0]["note"], findings
    # …and the correct frame (the evening before Day 1, a UTC instant on Day 1) stays clean.
    clean = pp.check_payload(SLEEP, _payload([_trend_row(0)]), 4, strict=True, start_date=GENESIS)
    assert clean == [], clean


def test_R7_covers_prefixed_night_keys():
    bad = pp.check_payload(SLEEP, {"recovery_night_of": _d(-3)}, 4, strict=True, start_date=GENESIS)
    assert len(bad) == 1 and "recovery_night_of" in bad[0]["note"]


def test_R6_R7_run_pre_start_too():
    """A FUTURE genesis (#931/#939) is when a stale prior-cycle row is most likely to leak."""
    findings = pp.check_payload(SLEEP, _payload([_trend_row(-1)]), 0, strict=True, start_date=GENESIS)
    assert len(findings) == 1 and findings[0]["category"] == "temporal_contradiction"


def test_R6_R7_stay_off_non_strict_and_off_a_missing_genesis():
    rows = _payload([_trend_row(-5)])
    assert pp.check_payload("/api/coaches", rows, 4, strict=False, start_date=GENESIS) == []
    assert pp.check_payload(SLEEP, rows, 4, strict=True, start_date=None) == []
