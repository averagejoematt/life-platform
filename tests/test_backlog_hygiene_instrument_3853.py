"""tests/test_backlog_hygiene_instrument_3853.py — an instrument's throttle row is not backlog.

THE DEFECT (#3853, the #3851 class one gate over)
  `scripts/check_deploy_wedge.py:605` files its dedup marker with exactly ONE label
  (`deploy-wedge-alert`). The issue exists to hold throttle state (#2149) and auto-closes on
  recovery. `check_backlog_hygiene.py` graded it against the full ADR-099 filing contract and
  reported FOUR violations — `one_type_label`, `one_area_label`, `one_model_label`,
  `outcome_audience`. On the 2026-09-16 corpus that was **4 of 9, i.e. 44%**, and the class
  recurs on every wedge episode (29 closed `deploy-wedge-alert` instances since 2026-08-07).
  Hygiene is blocking by default since #1872, so this was a recurring blocking red that no
  action could clear. It cleared only when the marker self-closed.

WHY THE LIVE CORPUS CANNOT BE THE PROOF (stated on the record, per the issue's own warning)
  Issue 3850 — the specimen — self-closed before this fix was written. Run today,
  `check_backlog_hygiene.py` over the live corpus reports **5** violations, which is the number
  box 4 asks for, **for the wrong reason**: there is no instrument marker in the corpus at all,
  so the gate is not exempting one, it is failing to meet one. Satisfying box 4 against live
  would be exactly the false green this issue is about. Every count below is therefore measured
  against `tests/fixtures/backlog_hygiene_3853/corpus_2026_09_16.json` — the REAL 3850 body,
  labels, author and commenters as GitHub still serves them, plus the five standing
  `acceptance_count` issues that made up the other half of the 9.

WHAT THE FIXTURE IS NOT
  It is not the whole 121-issue corpus. The corpus/queue rules (`now_liveness`,
  `epic_story_coverage`, `later_staleness`, `now_lane_coverage`) grade the SHAPE of a full
  backlog and cannot be satisfied by six issues, so the counts below are over the per-issue
  rules — which are the only rules this change touches. `_CORPUS_RULES` names them explicitly
  rather than filtering by "whatever fires", so a new corpus rule cannot quietly join the
  exclusion.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import check_backlog_hygiene as h  # noqa: E402
import closure_contract as cc  # noqa: E402

FIXTURE = REPO_ROOT / "tests" / "fixtures" / "backlog_hygiene_3853" / "corpus_2026_09_16.json"
MARKER_NUMBER = 3850

# Rules that grade the whole backlog's shape, not one issue. Named, not inferred.
_CORPUS_RULES = {"now_liveness", "now_lane_coverage", "epic_story_coverage", "later_staleness"}


def _corpus() -> list:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _per_issue_violations(issues) -> list:
    return [f for f in h.check(issues) if f.severity == h.VIOLATION and f.rule not in _CORPUS_RULES]


# ── the fixture is the real thing ────────────────────────────────────────────


def test_the_fixture_is_the_real_marker_not_a_paraphrase():
    """If the fixture drifted into something hand-written, every count below is about a
    fiction. Pin the properties that make 3850 the specimen: filed by the App, exactly the
    one alert label, no `type:*`, and no human in the thread."""
    marker = next(i for i in _corpus() if i["number"] == MARKER_NUMBER)
    assert [lbl["name"] for lbl in marker["labels"]] == ["deploy-wedge-alert"]
    assert marker["author"]["login"] == "app/github-actions"
    assert marker["comments"] and all(c["author"]["login"] == "github-actions" for c in marker["comments"])
    assert "deploy-wedge-alert:{" in marker["body"], "the dedup marker the alerter writes is gone from the body"


# ── box 1: the marker is not graded as backlog ───────────────────────────────


def test_the_marker_is_recognised_as_an_instrument_row():
    marker = next(i for i in _corpus() if i["number"] == MARKER_NUMBER)
    assert h.is_instrument_marker(h.build_ctx(marker)) is True


def test_the_marker_produces_no_violation():
    findings = [f for f in h.check([next(i for i in _corpus() if i["number"] == MARKER_NUMBER)]) if f.severity == h.VIOLATION]
    assert [f.rule for f in findings if f.rule not in _CORPUS_RULES] == []


def test_the_exemption_is_reported_never_silent():
    """A skipped issue that nothing mentions is a hole. The exemption rides as an ADVISORY
    naming the number, so a reader sees what the gate declined to grade and why."""
    findings = h.check(_corpus())
    (adv,) = [f for f in findings if f.rule == "instrument_marker_exempt"]
    assert adv.severity == h.ADVISORY
    assert str(MARKER_NUMBER) in adv.message


# ── box 2 + box 3: the must-fail control ─────────────────────────────────────


def test_the_SAME_BODY_filed_by_a_human_is_still_graded():
    """THE control for the whole change. The exemption is about the FILER and the absence of
    human engagement — never about the labels being absent. Swap only the author login and the
    identical body must red with all four original violations."""
    marker = dict(next(i for i in _corpus() if i["number"] == MARKER_NUMBER))
    marker["author"] = {"login": "averagejoematt"}
    ctx = h.build_ctx(marker)
    assert h.is_instrument_marker(ctx) is False
    rules = {f.rule for f in _per_issue_violations([marker])}
    assert rules == {"one_type_label", "one_area_label", "one_model_label", "outcome_audience"}, rules


def test_a_human_comment_alone_removes_the_exemption():
    """The second condition, controlled on its own: once a person has engaged, the row is a
    thing someone is working and the backlog contract applies again."""
    marker = dict(next(i for i in _corpus() if i["number"] == MARKER_NUMBER))
    marker["comments"] = list(marker["comments"]) + [{"author": {"login": "averagejoematt"}}]
    assert h.is_instrument_marker(h.build_ctx(marker)) is False


def test_a_type_label_alone_removes_the_exemption():
    """The third condition: applying any `type:*` is the act of declaring the row backlog
    work, and it beats the exemption rather than the other way round."""
    marker = dict(next(i for i in _corpus() if i["number"] == MARKER_NUMBER))
    marker["labels"] = list(marker["labels"]) + [{"name": "type:bug"}]
    assert h.is_instrument_marker(h.build_ctx(marker)) is False


def test_a_missing_author_field_grades_rather_than_exempts():
    """An older offline fixture carries no `author`. A field that is absent must not be able
    to GRANT an exemption — the failure direction has to be 'grade it'."""
    marker = dict(next(i for i in _corpus() if i["number"] == MARKER_NUMBER))
    marker.pop("author", None)
    assert h.is_instrument_marker(h.build_ctx(marker)) is False


# ── box 4: the measured 9 -> 5, on the frozen corpus ─────────────────────────


def test_the_frozen_corpus_goes_from_nine_to_five(monkeypatch):
    """The issue's own table, reproduced: 4 from the marker + 5 standing `acceptance_count`
    = 9 before, 5 after. The 'before' is not a remembered number — it is measured by running
    the same corpus with the discriminator forced off."""
    corpus = _corpus()

    monkeypatch.setattr(h, "is_instrument_marker", lambda ctx: False)
    before = _per_issue_violations(corpus)
    assert len(before) == 9, sorted(f"{f.number}:{f.rule}" for f in before)
    assert sum(1 for f in before if f.rule == "acceptance_count") == 5
    assert sum(1 for f in before if f.number == MARKER_NUMBER) == 4

    monkeypatch.undo()
    after = _per_issue_violations(corpus)
    assert len(after) == 5, sorted(f"{f.number}:{f.rule}" for f in after)
    assert {f.rule for f in after} == {"acceptance_count"}
    assert MARKER_NUMBER not in {f.number for f in after}


# ── the login-shape defect this uncovered ────────────────────────────────────


@pytest.mark.parametrize("login", ["github-actions", "app/github-actions", "github-actions[bot]", "dependabot[bot]"])
def test_both_spellings_of_an_app_login_read_as_a_bot(login):
    """#3853 found this while wiring the discriminator: GitHub hands the same App back as
    `github-actions` through GraphQL (`closure_sweep.py`) and `app/github-actions` through
    `gh issue list --json author` (this script). `BOT_LOGIN_RE` is anchored, so the `app/`
    form did not match and ONE issue read as bot-filed to one caller and human-filed to the
    other. Normalised once in `closure_contract.normalize_login`, not twice at the callers."""
    assert cc.is_bot(login) is True


@pytest.mark.parametrize("login", ["averagejoematt", "app/averagejoematt", "", None])
def test_normalisation_cannot_turn_a_person_into_a_bot(login):
    """The overshoot control. Stripping `app/` is safe only because `/` is not legal in a
    GitHub login — but the widening still must not reclassify anyone."""
    assert cc.is_bot(login) is False
