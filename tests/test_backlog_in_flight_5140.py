"""tests/test_backlog_in_flight_5140.py — the in-flight limit and the charter wave order (#5140).

Owner ruling 2026-10-23 on #5140: `backlog_next.py` shows at most 25 `Now` rows in
charter wave order and lists the overflow as QUEUED. Code only — nothing is relabelled
or moved. These tests pin the ordering (wave first, then the stored score), the limit,
that blocked rows never take an in-flight slot, that `--model` reads the board-wide cut,
and that the committed wave file carries the ruled limit.
"""

import argparse
import json
import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "scripts"))

import backlog_next as bn  # noqa: E402


def _body(score_value=3.0, epic=None):
    impact = {3.0: "Impact 3 × Confidence 1.0 / Effort S(1) = 3.00", 1.0: "Impact 1 × Confidence 1.0 / Effort S(1) = 1.00"}[score_value]
    lines = ["## Outcome\n\nOperator: x\n", "## Acceptance\n\n- [ ] a\n", f"**Score:** P2 · {impact} → Now"]
    if epic:
        lines.append(f"**Epic:** #{epic}")
    return "\n".join(lines)


def _issue(number, score=3.0, labels=("type:story",), epic=None, milestone="Now"):
    return {
        "number": number,
        "title": f"story {number}",
        "labels": [{"name": n} for n in labels],
        "milestone": {"title": milestone} if milestone else None,
        "body": _body(score, epic),
    }


SPEC = {
    "in_flight_limit": 3,
    "waves": [
        {"id": "W0", "issues": [30], "epics": []},
        {"id": "W1", "issues": [20], "epics": [900]},
    ],
}


def _rows(issues):
    return [bn.build_row(i) for i in issues if bn.is_rankable(i)]


def _corpus():
    return _rows(
        [
            _issue(10, score=3.0),  # unwaved, high score
            _issue(11, score=1.0),  # unwaved, low score
            _issue(20, score=1.0),  # W1 by number
            _issue(21, score=3.0, epic=900),  # W1 by epic parent
            _issue(30, score=1.0, labels=("type:story", "model:sonnet")),  # W0
            _issue(40, score=3.0, labels=("type:story", "gate:owner")),  # blocked: never in flight
            _issue(50, score=3.0, milestone="Next"),  # not on Now
        ]
    )


def test_wave_order_first_then_score_and_unwaved_last():
    in_flight, queued = bn.split_in_flight(_corpus(), SPEC["waves"], limit=0)
    assert [r["number"] for r in in_flight] == [30, 21, 20, 10, 11]
    assert queued == []


def test_the_limit_cuts_in_wave_order_and_the_rest_is_queued():
    in_flight, queued = bn.split_in_flight(_corpus(), SPEC["waves"], limit=3)
    assert [r["number"] for r in in_flight] == [30, 21, 20]
    assert [r["number"] for r in queued] == [10, 11]


def test_render_names_the_overflow_as_queued_with_its_wave():
    rows = _corpus()
    result = bn.apply_in_flight(bn.select(rows, milestone="Now"), rows, SPEC, limit=3)
    assert [r["number"] for r in result["rows"]] == [30, 21, 20]
    out = "\n".join(bn.render(result, rows, argparse.Namespace(limit=0, include_blocked=False)))
    assert "IN FLIGHT — Now" in out and "limit of 3" in out
    assert "QUEUED — 2 startable Now row(s) over the in-flight limit of 3" in out
    assert "#10    · unwaved · story 10" in out
    assert "1 issue(s) hidden: gate:owner" in out, "the blocked row is counted, never given a slot"


def test_mutation_control_no_limit_shows_the_whole_board_and_no_queue():
    rows = _corpus()
    result = bn.apply_in_flight(bn.select(rows, milestone="Now"), rows, SPEC, limit=0)
    assert "queued" not in result and len(result["rows"]) == 5
    out = "\n".join(bn.render(result, rows, argparse.Namespace(limit=0, include_blocked=False)))
    assert "QUEUED" not in out and "RANKED — Now" in out


def test_a_model_filter_reads_the_board_wide_cut_not_its_own_25():
    rows = _corpus()
    result = bn.apply_in_flight(bn.select(rows, milestone="Now", model="sonnet"), rows, SPEC, limit=1)
    assert [r["number"] for r in result["rows"]] == [30]
    assert result["queued_board"] == 4 and result["queued"] == [], "the queued rows are not sonnet's"


def test_a_fall_through_to_next_is_not_cut():
    rows = _rows([_issue(50, milestone="Next"), _issue(51, milestone="Next")])
    result = bn.apply_in_flight(bn.select(rows, milestone="Now"), rows, SPEC, limit=1)
    assert result["milestone"] == "Next" and len(result["rows"]) == 2 and "queued" not in result


def test_the_committed_wave_file_carries_the_owner_limit_and_valid_waves():
    spec = bn.load_waves()
    assert spec["in_flight_limit"] == 25, "owner ruling 2026-10-23 on #5140: 25, not 15"
    ids = [w["id"] for w in spec["waves"]]
    assert len(ids) == len(set(ids)) and ids
    seen = []
    for w in spec["waves"]:
        assert all(isinstance(n, int) for n in w["issues"] + w["epics"]), w["id"]
        seen += w["issues"]
    assert len(seen) == len(set(seen)), "an issue listed in two waves has an ambiguous place"


def test_cli_prints_at_most_the_limit_and_names_the_queue(tmp_path, capsys):
    issues = [_issue(n) for n in range(100, 130)]
    fixture = tmp_path / "issues.json"
    fixture.write_text(json.dumps(issues), encoding="utf-8")
    assert bn.main(["--issues-json", str(fixture)]) == 0
    out = capsys.readouterr().out
    assert "the board holds 25 of a limit of 25" in out
    assert "QUEUED — 5 startable Now row(s)" in out
    assert out.count("· Now · story ") == 25


def test_an_unreadable_wave_file_degrades_to_no_cut(tmp_path):
    spec = bn.load_waves(tmp_path / "missing.json")
    assert spec == {"in_flight_limit": 0, "waves": []}
