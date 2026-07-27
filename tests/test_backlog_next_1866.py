"""tests/test_backlog_next_1866.py — the ranked backlog selector (#1866, epic #1863).

Replays the PM backlog review's headline finding: the stored ADR-099 rank was written
on every issue and read by nothing at selection time, and the one documented seed query
returned `[]` because all three open `Now` stories carried `gate:owner` — a silent empty
list where a fall-through was possible (finding 1).

Every test here plants a fixture and proves the rule bites (#1189 house style — no
vacuous scans): the canonical grammar parses, each measured legacy grammar does NOT and
is reported rather than dropped, blocked work is counted rather than hidden, and an empty
`Now` produces a loud fall-through instead of an empty result.
"""

import json
import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "scripts"))

import argparse  # noqa: E402

import backlog_contract as bc  # noqa: E402
import backlog_next as bn  # noqa: E402

# The frozen grammar from the ADR-099 2026-07-27 amendment (#1865). If this string
# has to change, the amendment changed — and #1867's linter changes with it.
CANONICAL = "**Score:** P2 · Impact 3 × Confidence 1.0 / Effort S(1) = 3.00 → Now"


def _body(score=None, outcome=None, acceptance=("do the thing",), extra=""):
    parts = []
    if outcome:
        parts.append(f"## Outcome\n\n{outcome}\n")
    if acceptance:
        parts.append("## Acceptance\n\n" + "\n".join(f"- [ ] {a}" for a in acceptance) + "\n")
    if extra:
        parts.append(extra + "\n")
    if score:
        parts.append(score)
    return "\n".join(parts)


def _issue(number, title="t", labels=(), milestone="Now", body=""):
    return {
        "number": number,
        "title": title,
        "labels": [{"name": n} for n in labels],
        "milestone": {"title": milestone} if milestone else None,
        "body": body,
    }


def _rows(issues):
    return [bn.build_row(i) for i in issues if bn.is_rankable(i)]


def _render(result, rows, limit=0, include_blocked=False):
    args = argparse.Namespace(limit=limit, include_blocked=include_blocked)
    return "\n".join(bn.render(result, rows, args))


# ── the canonical score line ────────────────────────────────────────────────────
def test_canonical_score_line_parses_every_field():
    score = bc.parse_score_line(_body(score=CANONICAL))
    assert score is not None, "the frozen canonical exemplar must parse — the whole contract hangs off it"
    assert (score.prio, score.impact, score.confidence) == ("P2", 3, 1.0)
    assert (score.effort, score.effort_points) == ("S", 1)
    assert score.value == 3.00
    assert score.milestone == "Now"
    assert score.raw == CANONICAL


def test_canonical_score_line_tolerates_a_trailing_rationale():
    """#1866's own score line carries a parenthetical after the milestone."""
    line = CANONICAL + " (severity→milestone disposition, PM-set — the epic's headline fix)"
    score = bc.parse_score_line(line)
    assert score is not None and score.milestone == "Now"


def test_score_grammar_variants_across_prio_effort_and_milestone():
    for prio in ("P0", "P1", "P2", "P3"):
        for effort, pts in (("S", 1), ("M", 2), ("L", 4)):
            for ms in ("Now", "Next", "Later"):
                line = f"**Score:** {prio} · Impact 4 × Confidence 0.75 / Effort {effort}({pts}) = 1.00 → {ms}"
                score = bc.parse_score_line(line)
                assert score is not None, f"canonical variant rejected: {line}"
                assert (score.prio, score.effort, score.effort_points, score.milestone) == (prio, effort, pts, ms)


# ── the legacy grammars are rejected, but REPORTED (finding 3) ──────────────────
LEGACY_LINES = [
    "**Score:** T4×W4/M",  # the form with no ADR basis at all
    "**Score:** T3×W5/M · $0 run-rate.",
    "**Score:** P2*1.0/L=4 = 0.75",
    "**Score:** P2 → Impact 3 × Confidence 1.0 / Effort S(1) = 3.0 → **Now**",  # arrow, not ·; bold milestone
    "**Score:** Impact 2 × Confidence 0.9 / Effort S(1) = **1.8** (Next)",  # no prio; parenthesised milestone
    "**Score:** P3 · Impact 2 × Confidence 0.75 / Effort M(2) = 0.75 → **Later**",  # canonical but bold milestone
    "**Priority score:** 4×3/2 = **6.0**.",
    "**Score:** P2 - Impact 3 x Confidence 1.0 / Effort S(1) = 3.00 -> Now",  # ASCII lookalikes
]


def test_legacy_score_grammars_do_not_parse_as_canonical():
    for line in LEGACY_LINES:
        assert bc.parse_score_line(line) is None, f"legacy grammar leaked through the canonical parser: {line}"


def test_legacy_score_grammars_are_still_surfaced_not_dropped():
    """ "Unscored" and "scored with a retired grammar" are different facts; the ranker
    says which one it is, so #1868's backfill has a visible worklist."""
    for line in LEGACY_LINES:
        assert bc.find_score_line(line) == line, f"legacy grammar vanished instead of being reported: {line}"


def test_find_score_line_is_none_when_there_is_no_score_line_at_all():
    assert bc.find_score_line(_body(outcome="**operator** — value")) is None


def test_a_body_that_merely_quotes_the_grammar_is_not_scored_by_it():
    """#1865's acceptance criteria quote the canonical line inside a checkbox. Reading
    that as the issue's own score would give the contract doc a phantom rank."""
    body = f"## Acceptance\n\n- [ ] ADR-099 specifies the canonical score line `{CANONICAL}`\n"
    assert bc.parse_score_line(body) is None


# ── the ## Outcome extractor ────────────────────────────────────────────────────
def test_outcome_line_reads_the_canonical_section():
    body = _body(score=CANONICAL, outcome="**operator** — one command answers what to work on next.")
    assert bc.outcome_line(body) == "**operator** — one command answers what to work on next."


def test_outcome_line_stops_at_the_next_heading():
    body = "## Outcome\n\n**reader** — the value.\n\n## Acceptance\n\n- [ ] not the outcome\n"
    assert bc.outcome_line(body) == "**reader** — the value."


def test_outcome_line_is_none_when_absent_rather_than_empty_string():
    """Finding 4 is a visibility finding: an absent outcome must be reportable as absent,
    not silently rendered as a blank row."""
    assert bc.outcome_line(_body(score=CANONICAL)) is None


def test_legacy_outcome_variants_are_recognised_as_legacy():
    for heading in ("## outcome_if_fixed", "## Outcome if fixed", "## Outcome hypothesis"):
        body = f"{heading}\n\nthe old value statement\n"
        assert bc.outcome_line(body) is None, f"{heading} must NOT count as the canonical section"
        assert bc.legacy_outcome_line(body) == "the old value statement"


def test_legacy_outcome_inline_form_is_recognised():
    body = "**outcome_if_fixed:** the decision ledger becomes browsable.\n"
    assert bc.outcome_line(body) is None
    assert bc.legacy_outcome_line(body) == "the decision ledger becomes browsable."


def test_crlf_bodies_still_parse():
    """GitHub round-trips CRLF; every regex here is line-anchored, so a stray \\r would
    silently defeat the `$` anchors and make a well-formed issue look unscored."""
    body = f"## Outcome\r\n\r\n**operator** — value.\r\n\r\n{CANONICAL}\r\n"
    assert bc.parse_score_line(body) is not None
    assert bc.outcome_line(body) == "**operator** — value."


# ── ## Acceptance checkboxes are section-scoped ────────────────────────────────
def test_acceptance_checkboxes_are_counted_only_under_the_acceptance_heading():
    """An epic's `## Stories` task list is checkbox syntax that is not acceptance
    criteria — a whole-body count reads ten stories as ten ACs."""
    body = "## Acceptance\n\n- [x] one\n- [ ] two\n\n## Stories\n\n- [ ] #1864 — a story\n- [ ] #1865 — another\n"
    items = bc.acceptance_items(body)
    assert [checked for checked, _ in items] == [True, False], f"acceptance scan leaked outside its section: {items}"


def test_acceptance_checkboxes_empty_when_the_section_is_missing():
    assert bc.acceptance_items("## Stories\n\n- [ ] #1 — a story\n") == []


# ── ranking ────────────────────────────────────────────────────────────────────
def _scored(number, value, prio="P2", milestone="Now", labels=("type:story", "model:opus"), effort="S(1)"):
    line = f"**Score:** {prio} · Impact 3 × Confidence 1.0 / Effort {effort} = {value:.2f} → {milestone}"
    return _issue(number, f"issue {number}", labels, milestone, _body(score=line, outcome=f"**operator** — value {number}"))


def test_sorted_by_score_descending():
    rows = _rows([_scored(1, 1.50), _scored(2, 3.00), _scored(3, 0.75)])
    result = bn.rank(rows, "Now")
    assert [r["number"] for r in result["rows"]] == [2, 1, 3]


def test_milestone_breaks_a_score_tie_with_now_first():
    rows = _rows([_scored(1, 2.00, milestone="Later"), _scored(2, 2.00, milestone="Next"), _scored(3, 2.00, milestone="Now")])
    result = bn.rank(rows, None)
    assert [r["number"] for r in result["rows"]] == [3, 2, 1]


def test_unscored_rows_sort_last_but_are_never_dropped():
    unscored = _issue(9, "legacy", ["type:story"], "Now", _body(score="**Score:** T4×W4/M"))
    rows = _rows([unscored, _scored(1, 0.25)])
    result = bn.rank(rows, "Now")
    assert [r["number"] for r in result["rows"]] == [1, 9], "an unscored issue must rank last, not disappear"


def test_epics_are_not_ranked_as_work():
    """An epic is a container with its own score line; ranking it puts a program, not a
    task, at the top of "what do I work on next"."""
    epic = _issue(100, "[EPIC] container", ["type:epic"], "Now", _body(score=CANONICAL))
    rows = _rows([epic, _scored(1, 1.0)])
    assert [r["number"] for r in rows] == [1]


# ── blocked work is hidden but COUNTED (never silently dropped) ─────────────────
def test_gate_owner_and_blocked_dep_are_hidden_by_default_and_counted():
    gated = _scored(1, 3.00, labels=("type:story", "model:opus", "gate:owner"))
    dep = _scored(2, 2.00, labels=("type:story", "model:opus", "blocked:dep"))
    rows = _rows([gated, dep, _scored(3, 0.50)])
    result = bn.rank(rows, "Now")
    assert [r["number"] for r in result["rows"]] == [3]
    assert result["blocked_count"] == 2
    out = _render(result, rows)
    assert "2 issue(s) hidden" in out and "gate:owner" in out


def test_include_blocked_shows_them_inline():
    gated = _scored(1, 3.00, labels=("type:story", "model:opus", "gate:owner"))
    rows = _rows([gated, _scored(3, 0.50)])
    result = bn.rank(rows, "Now", include_blocked=True)
    assert [r["number"] for r in result["rows"]] == [1, 3]
    out = _render(result, rows, include_blocked=True)
    assert "[gate:owner]" in out, "a shown blocked row must still be labelled as blocked"


# ── the finding-1 failure mode: an empty Now must fall through, loudly ──────────
def test_empty_now_falls_through_to_next_and_says_so():
    """The exact measured failure: all open `Now` stories carry gate:owner, so the
    documented seed query returned `[]` and a session found nothing to do."""
    now_gated = [_scored(n, 3.00, labels=("type:story", "model:opus", "gate:owner")) for n in (1738, 1622, 1571)]
    nxt = _scored(1871, 2.00, milestone="Next")
    rows = _rows(now_gated + [nxt])
    result = bn.select(rows, milestone="Now")
    assert [r["number"] for r in result["rows"]] == [1871]
    assert result["milestone"] == "Next"
    out = _render(result, rows)
    assert "Falling through" in out, "the fall-through must be announced, not silent"
    assert "ALL gate:owner/blocked:*" in out
    assert "#1871" in out


def test_fall_through_walks_past_an_entirely_empty_next():
    rows = _rows([_scored(1, 1.0, labels=("type:story", "model:opus", "gate:owner")), _scored(2, 1.0, milestone="Later")])
    result = bn.select(rows, milestone="Now")
    assert result["milestone"] == "Later" and [r["number"] for r in result["rows"]] == [2]


def test_nothing_anywhere_is_reported_as_exhausted_not_as_a_bare_empty_list():
    rows = _rows([_scored(1, 1.0, labels=("type:story", "model:opus", "gate:owner"))])
    result = bn.select(rows, milestone="Now")
    assert result["rows"] == [] and result.get("exhausted") is True
    out = _render(result, rows)
    assert "NOTHING ACTIONABLE anywhere" in out


# ── filters ────────────────────────────────────────────────────────────────────
def test_model_filter_selects_one_fan_out_lane():
    rows = _rows(
        [
            _scored(1, 3.0, labels=("type:story", "model:sonnet")),
            _scored(2, 2.0, labels=("type:story", "model:opus")),
            _scored(3, 1.0, labels=("type:story", "model:fable")),
        ]
    )
    assert [r["number"] for r in bn.rank(rows, "Now", model="opus")["rows"]] == [2]
    assert [r["number"] for r in bn.rank(rows, "Now", model="fable")["rows"]] == [3]


def test_limit_truncates_the_printed_rows_but_not_the_count():
    rows = _rows([_scored(n, float(n)) for n in (1, 2, 3, 4)])
    result = bn.rank(rows, "Now")
    out = _render(result, rows, limit=2)
    assert "(2 of 4 shown" in out
    assert "#4" in out and "#3" in out and "#2 " not in out


# ── row rendering: value is always in front of the selector ────────────────────
def test_every_row_prints_an_outcome_line_or_says_it_is_missing():
    with_outcome = _scored(1, 3.0)
    without = _issue(2, "no outcome", ["type:story", "model:opus"], "Now", _body(score=CANONICAL))
    rows = _rows([with_outcome, without])
    out = _render(bn.rank(rows, "Now"), rows)
    assert "↳ **operator** — value 1" in out
    assert "↳ — no ## Outcome line" in out, "an absent outcome must be stated, not blank"


def test_legacy_outcome_is_shown_and_labelled_legacy():
    issue = _issue(3, "legacy outcome", ["type:story"], "Now", "## outcome_if_fixed\n\nthe old statement\n\n" + CANONICAL)
    rows = _rows([issue])
    out = _render(bn.rank(rows, "Now"), rows)
    assert "(legacy outcome_if_fixed) the old statement" in out


def test_unscored_row_names_which_kind_of_unscored_it_is():
    legacy = _issue(1, "legacy", ["type:story"], "Now", _body(score="**Score:** T4×W4/M"))
    none = _issue(2, "none", ["type:story"], "Now", _body())
    rows = _rows([legacy, none])
    out = _render(bn.rank(rows, "Now"), rows)
    assert "not the ADR-099 canonical grammar: **Score:** T4×W4/M" in out
    assert "no **Score:** line at all" in out
    assert "2 shown row(s) UNSCORED (1 on a retired grammar)" in out


def test_prio_falls_back_to_the_body_score_with_a_visible_tilde():
    labelled = _scored(1, 3.0, labels=("type:story", "model:opus", "prio:P1"))
    unlabelled = _scored(2, 2.0)
    rows = _rows([labelled, unlabelled])
    out = _render(bn.rank(rows, "Now"), rows)
    assert "prio:P1" in out
    assert "prio:~P2" in out, "a body-derived priority must be marked as derived, not passed off as a label"


def test_unmilestoned_issues_are_reported_as_invisible_to_ranked_queries():
    rows = _rows([_scored(1, 3.0), _issue(1859, "no milestone", ["type:story"], None, _body(score=CANONICAL))])
    out = _render(bn.rank(rows, "Now"), rows)
    assert "carry NO milestone and are invisible to every ranked query: #1859" in out


# ── CLI ────────────────────────────────────────────────────────────────────────
def test_cli_offline_mode_ranks_a_fixture(tmp_path, capsys):
    fixture = tmp_path / "issues.json"
    fixture.write_text(json.dumps([_scored(1, 3.0), _scored(2, 1.0)]), encoding="utf-8")
    rc = bn.main(["--issues-json", str(fixture)])
    out = capsys.readouterr().out
    assert rc == 0
    assert out.index("#1 ") < out.index("#2 "), "offline mode must apply the same ranking as live"


def test_cli_is_fail_open_when_gh_is_unavailable(monkeypatch, capsys):
    """No network/gh auth in CI's test job — a live-fetch failure must never red the
    suite or block a session (check_story_labels.py's advisory contract)."""
    monkeypatch.setattr(bn, "_fetch_live_issues", lambda: None)
    rc = bn.main([])
    capsys.readouterr()
    assert rc == 0


def test_cli_exit_code_is_zero_even_when_nothing_is_actionable(tmp_path, capsys):
    fixture = tmp_path / "issues.json"
    fixture.write_text(json.dumps([_scored(1, 1.0, labels=("type:story", "gate:owner"))]), encoding="utf-8")
    rc = bn.main(["--issues-json", str(fixture)])
    out = capsys.readouterr().out
    assert rc == 0, "the selector is advisory — an empty backlog is a report, not an error"
    assert "NOTHING ACTIONABLE anywhere" in out


# ── contract-module shape: #1867 imports these ─────────────────────────────────
def test_shared_contract_exposes_the_symbols_the_hygiene_linter_will_import():
    """One contract, two consumers (#1866 ranker, #1867 linter). If these move, the two
    scripts can silently disagree about what a valid filing is."""
    for name in (
        "SCORE_LINE_RE",
        "parse_score_line",
        "find_score_line",
        "outcome_line",
        "legacy_outcome_line",
        "acceptance_items",
        "label_names",
        "milestone_title",
        "is_blocked",
        "model_lane",
        "MILESTONE_ORDER",
    ):
        assert hasattr(bc, name), f"backlog_contract.{name} is the shared contract surface — #1867 imports it"


def test_ranker_consumes_the_shared_parser_rather_than_its_own_copy():
    """The failure this guards: a second regex drifting from the linter's."""
    with open(os.path.join(_REPO, "scripts", "backlog_next.py"), encoding="utf-8") as fh:
        src = fh.read()
    assert "import backlog_contract" in src
    assert "re.compile" not in src, "backlog_next must not compile its own copy of the grammar — import it from backlog_contract"
