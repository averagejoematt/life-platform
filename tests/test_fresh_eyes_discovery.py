"""
tests/test_fresh_eyes_discovery.py — offline unit tests for the pure parts of
scripts/fresh_eyes_discovery.py (#823's weekly unattended fresh-eyes routine).

Only the deterministic pieces are covered here (no AWS, no Playwright, no gh
CLI, no live network): the budget gate predicate, the vision-verdict parser,
the candidate flattener, the backlog dedup, the ranking, and the Sonnet-board
parser + fallback. Everything with real I/O (screenshot capture, Bedrock
calls, SES, gh) only runs for real inside the scheduled workflow.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import fresh_eyes_discovery as fed  # noqa: E402

# ── budget gate ──────────────────────────────────────────────────────────────


def test_should_skip_for_budget_below_tier_2_runs():
    assert fed.should_skip_for_budget(0) is False
    assert fed.should_skip_for_budget(1) is False


def test_should_skip_for_budget_at_or_above_tier_2_skips():
    assert fed.should_skip_for_budget(2) is True
    assert fed.should_skip_for_budget(3) is True


# ── parse_findings (Haiku vision verdict) ───────────────────────────────────


def test_parse_findings_happy_path():
    text = (
        "Here is my read.\n```json\n"
        '{"findings": [{"audience": "reddit_newcomer", "severity": "med", '
        '"note": "The loop diagram is below the fold on mobile"}]}\n```'
    )
    out = fed.parse_findings(text, "Home", "/", "mobile")
    assert len(out) == 1
    assert out[0]["audience"] == "reddit_newcomer"
    assert out[0]["severity"] == "med"
    assert out[0]["page"] == "Home"
    assert out[0]["path"] == "/"
    assert out[0]["viewport"] == "mobile"


def test_parse_findings_drops_unknown_audience():
    text = '{"findings": [{"audience": "martian", "severity": "high", "note": "n/a"}]}'
    assert fed.parse_findings(text, "Home", "/", "page") == []


def test_parse_findings_drops_empty_note():
    text = '{"findings": [{"audience": "matthew_daily", "severity": "low", "note": ""}]}'
    assert fed.parse_findings(text, "Home", "/", "page") == []


def test_parse_findings_defaults_bad_severity_to_low():
    text = '{"findings": [{"audience": "qs_enthusiast", "severity": "critical", "note": "something"}]}'
    out = fed.parse_findings(text, "Data hub", "/data/", "page")
    assert out[0]["severity"] == "low"


def test_parse_findings_no_json_is_empty():
    assert fed.parse_findings("I couldn't find anything notable.", "Home", "/", "page") == []


def test_parse_findings_empty_findings_list_is_valid():
    assert fed.parse_findings('{"findings": []}', "Home", "/", "page") == []


# ── extract_candidates ───────────────────────────────────────────────────────


def test_extract_candidates_flattens_lists_of_lists():
    a = [{"note": "a"}]
    b = []
    c = [{"note": "c1"}, {"note": "c2"}]
    assert fed.extract_candidates([a, b, c]) == [{"note": "a"}, {"note": "c1"}, {"note": "c2"}]


# ── dedup_against_backlog ────────────────────────────────────────────────────


def _cand(note, audience="reddit_newcomer", path="/", severity="med"):
    return {"note": note, "audience": audience, "path": path, "severity": severity, "page": "p", "viewport": "page"}


def test_dedup_drops_near_duplicate_of_open_issue_title():
    candidates = [_cand("the chronicle looks stale and hasn't updated in weeks")]
    open_titles = ["The chronicle looks stale and hasn't updated in weeks"]
    assert fed.dedup_against_backlog(candidates, open_titles) == []


def test_dedup_keeps_unrelated_candidate():
    candidates = [_cand("the cockpit pillar disclosure animation stutters on mobile Safari")]
    open_titles = ["Add a weekly fresh-eyes discovery routine"]
    survivors = fed.dedup_against_backlog(candidates, open_titles)
    assert len(survivors) == 1


def test_dedup_fail_open_when_no_open_titles():
    candidates = [_cand("anything")]
    assert fed.dedup_against_backlog(candidates, []) == candidates


# ── rank_candidates ───────────────────────────────────────────────────────────


def test_rank_prefers_multi_audience_echo_at_equal_severity():
    # One single-audience finding...
    single = _cand("the story hub tabs never load past chronicle", audience="reddit_newcomer", severity="med")
    # ...vs. the SAME theme (near-duplicate wording) raised independently by two
    # different audiences at the SAME severity. Echo across audiences should win
    # the tie (rank_candidates' docstring: "of the same severity").
    echoed_a = _cand("the pillar disclosure never reveals the day-grade replay detail", audience="matthew_daily", severity="med")
    echoed_b = _cand("pillar disclosure fails to reveal the day grade replay detail", audience="qs_enthusiast", severity="med")

    ranked = fed.rank_candidates([single, echoed_a, echoed_b], max_items=5)
    assert len(ranked) == 2  # echoed_a/echoed_b grouped into one
    assert ranked[0]["count"] == 2
    assert set(ranked[0]["audiences"]) == {"matthew_daily", "qs_enthusiast"}
    assert ranked[1]["count"] == 1


def test_rank_respects_max_items():
    distinct_notes = [
        "the loop diagram never appears above the fold",
        "sleep readout shows a blank chart frame",
        "the coaching roster links all 404",
        "protocols hub hides the experiment CTA",
        "training zone chart has no drawn geometry",
        "the chronicle hasn't published in three weeks",
        "nutrition delivery table is missing units",
        "the footer mega-menu overlaps the page content",
    ]
    candidates = [_cand(note, audience="reddit_newcomer") for note in distinct_notes]
    ranked = fed.rank_candidates(candidates, max_items=3)
    assert len(ranked) == 3


def test_rank_empty_input_is_empty():
    assert fed.rank_candidates([]) == []


# ── parse_board (Sonnet synthesis) + fallback ────────────────────────────────


def test_parse_board_happy_path():
    text = '[{"title": "Fix the thing", "why": "it breaks the loop", "audience": "matthew_daily", "suggested_first_step": "do X"}]'
    board = fed.parse_board(text)
    assert len(board) == 1
    assert board[0]["title"] == "Fix the thing"


def test_parse_board_truncates_to_max_items():
    items = [{"title": f"item {i}"} for i in range(10)]
    text = str(items).replace("'", '"')
    board = fed.parse_board(text)
    assert len(board) == fed.MAX_BOARD_ITEMS


def test_parse_board_drops_non_dict_and_titleless_entries():
    text = '[{"title": "keep me"}, "a bare string", {"why": "no title here"}]'
    board = fed.parse_board(text)
    assert board == [{"title": "keep me"}]


def test_parse_board_no_array_is_empty():
    assert fed.parse_board("no structured board here") == []


def test_fallback_board_shape_from_ranked():
    ranked = [{"note": "some finding", "audiences": ["reddit_newcomer"], "pages": ["/"], "severity": "med", "count": 1, "score": 2.0}]
    board = fed.fallback_board(ranked)
    assert len(board) == 1
    assert board[0]["title"] == "some finding"
    assert "reddit_newcomer" in board[0]["audience"]
