#!/usr/bin/env python3
"""tests/test_merge_commit_closures_3863.py — detector D + the merge-message guard (#3863).

THE DEFECT, in one line: `check_pr_closing_set.py` validates three texts and every one is
PRE-merge, so a squash message supplied at merge time (`--body-file`, `--subject`, or the web
UI's editable box) is seen by nothing. On 2026-09-17 one retired an owner-gated issue.

WHAT IS PROVEN HERE
  1. The comparison is cut the way the INCIDENT requires, not the way the acceptance box
     reads at first glance. Measured on the real PR: taking "declared" as body|commits|github
     yields ZERO findings on the very merge this detector exists for, because the offending
     ref WAS in the branch commits — that set is the raw material detector B already warns
     about, not a declaration. body|github yields exactly the offending issue. Both readings
     are asserted below so the choice cannot be silently reverted.
  2. The benign case still passes — a closing ref the PR body declares is not a finding.
  3. The effect is MEASURED per undeclared ref, so "retired a live issue" and "wrote a
     keyword at an already-closed one" do not read identically.
  4. The pre-merge guard refuses a supplied message, and does NOT refuse a bare `--squash`.

THE SELF-REFERENCE HAZARD
  This file is about closing keywords, so its fixtures would be parsed as closing keywords —
  by GitHub, and by this repo's own guards (#3812 blocked the PR that fixed exactly this).
  Every fixture is ASSEMBLED by `_kw()` and never written whole, the same discipline
  `scripts/gate_census_mutations.py` uses for its probe payloads.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import check_merge_commit_closures as d  # noqa: E402
import closure_contract as cc  # noqa: E402


def _kw(verb: str, num: int) -> str:
    """Assemble a closing reference so it never appears whole in this source. See the header."""
    return verb + " " + "#" + str(num)


# ── 1. THE CUT — asserted against the real incident's real numbers ───────────────────────

# PR #3862's measured pre-merge sets (2026-09-17, `gh pr view 3862`) and the merge commit
# d681aecc6's own committed set. Numbers, not text, so this fixture carries no live keyword.
_INCIDENT_BODY = {3861}
_INCIDENT_COMMITS = {3715}
_INCIDENT_GITHUB = {3861}
_INCIDENT_COMMITTED = {3715, 3861}


def test_the_naive_union_does_not_catch_its_own_incident():
    """The reading the acceptance box invites — compare against all three pre-merge texts —
    is VACUOUS on the event it was written for. Recorded as an assertion so nobody re-widens
    `declared` to include the branch commits and believes they have strengthened it."""
    naive = _INCIDENT_BODY | _INCIDENT_COMMITS | _INCIDENT_GITHUB
    assert _INCIDENT_COMMITTED - naive == set(), "if this ever becomes non-empty the incident's own numbers have changed"


def test_body_plus_github_catches_it_exactly():
    declared = _INCIDENT_BODY | _INCIDENT_GITHUB
    assert _INCIDENT_COMMITTED - declared == {3715}


def test_evaluate_reds_on_the_incidents_shape_and_names_the_carrier():
    audit = d.evaluate(
        "feat(backlog): rank by what a session can FINISH (#3861)\n\n" + _kw("close:", 3715) + "\n" + _kw("Fixes", 3861),
        declared=_INCIDENT_BODY | _INCIDENT_GITHUB,
        sha="d681aecc6",
        pr=3862,
        commit_only=_INCIDENT_COMMITS - (_INCIDENT_BODY | _INCIDENT_GITHUB),
    )
    assert [f.code for f in audit.findings] == ["unvalidated-merge-closure"]
    detail = audit.findings[0].detail
    assert "#3715" in detail, detail
    assert "BRANCH COMMIT" in detail, "the finding must name HOW the ref reached the merge text"


def test_the_colon_form_is_parsed_because_github_parses_it():
    """The incident's load-bearing misreading was 'GitHub does not parse the colon form'."""
    assert d.closing_set(_kw("close:", 3715)) == {3715}
    assert d.closing_set(_kw("Fixes", 42)) == {42}


def test_a_keyword_inside_prose_or_a_code_span_still_counts():
    """GitHub ignores code spans; so must this. The wrap commit that described the incident
    re-closed the issue for exactly this reason."""
    assert d.closing_set("the commit prose read '" + _kw("close:", 3715) + "'") == {3715}
    assert d.closing_set("`" + _kw("close:", 3715) + "`") == {3715}


# ── 2. THE NEGATIVE CONTROLS — the benign cases must not red ─────────────────────────────


def test_a_declared_closing_ref_is_not_a_finding():
    audit = d.evaluate("fix(x): thing (#99)\n\n" + _kw("Fixes", 42), declared={42}, sha="abc123def", pr=99)
    assert audit.findings == [], [f.detail for f in audit.findings]


def test_a_merge_that_closes_nothing_is_not_a_finding():
    audit = d.evaluate("docs(x): a note (#99)\n\nRefs #42", declared=set(), sha="abc123def", pr=99)
    assert audit.findings == []


def test_a_squash_pr_suffix_is_not_an_issue_closure():
    """`(#N)` appended by GitHub is a PR ref. Counting it would make every merge a finding."""
    assert d.closing_set("fix(x): thing (#3862)") == set()
    assert d.subject_pr_number("fix(x): thing (#3862)") == 3862


def test_an_unreadable_pr_is_reported_as_unmeasured_never_as_clean():
    audit = d.evaluate("fix(x): thing (#99)\n\n" + _kw("Fixes", 42), declared=None, sha="abc123def", pr=99)
    assert audit.findings == []
    assert audit.notes and "NOT compared" in audit.notes[0]
    assert "Unmeasured, not clean" in audit.notes[0]


# ── 3. THE PR-RESOLUTION TRAP the incident itself created ────────────────────────────────


def test_a_supplied_subject_can_write_a_non_pr_number_in_the_pr_slot():
    """d681aecc6's subject ends `(#3861)` — the ISSUE. Parsing the subject for the PR number
    resolves to an issue, `gh pr view` fails, and the audit degrades to 'could not read' on
    the one commit that matters. That is why pr_for_commit asks GitHub first."""
    assert d.subject_pr_number("feat(backlog): rank by what a session can FINISH, not only by stored value (#3861)") == 3861
    src = (ROOT / "scripts" / "check_merge_commit_closures.py").read_text(encoding="utf-8")
    body = src[src.index("def pr_for_commit") : src.index("def merge_commits")]
    assert body.index("_gh_json") < body.index("_SQUASH_PR_SUFFIX"), "GitHub's association must be consulted BEFORE the subject suffix"


# ── 4. THE PRE-MERGE GUARD — refuses a supplied message, allows a bare squash ────────────


def _guard(cmd: str):
    payload = '{"tool_name":"Bash","tool_input":{"command":%s}}' % __import__("json").dumps(cmd)
    p = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "hooks" / "guard_bash.py")],
        input=payload,
        capture_output=True,
        text=True,
    )
    return p.stdout + p.stderr


def test_the_guard_refuses_a_supplied_squash_message():
    for flag in ("--body-file /tmp/m.txt", "--body 'x'", "--subject 'y'"):
        out = _guard(f"bash deploy/wait_pr_green.sh 1 && gh pr merge 1 --squash {flag}")
        assert "no guard has validated" in out, f"{flag} was not refused: {out[:300]}"


def test_the_guard_allows_a_bare_squash():
    """The NEGATIVE control. A guard that refused every merge would be uninstalled in a day."""
    out = _guard("bash deploy/wait_pr_green.sh 1 && gh pr merge 1 --squash")
    assert "no guard has validated" not in out, out[:300]


# ── 5. THE REGISTRY — one home, and the Set has a stated verdict ─────────────────────────


def test_the_requirement_is_registered_with_both_legs():
    req = next(r for r in cc.CLOSURE_CONTRACT if r.id == "validated-merge-text")
    assert req.finding_codes == ("unvalidated-merge-closure",)
    assert req.detector == "scripts/check_merge_commit_closures.py"
    assert "scripts/hooks/guard_bash.py" in req.also_detected_by, "the pre-merge leg must be registered too"


def test_every_member_of_the_set_has_a_stated_verdict():
    """#3863's box 4. The verdicts live in the module docstring so they cannot rot away from
    the code that implements them; this asserts each member is actually addressed."""
    src = (ROOT / "scripts" / "check_merge_commit_closures.py").read_text(encoding="utf-8")
    for member in ("--body-file", "--subject", "web UI"):
        assert member in src, f"the Set member {member!r} has no stated verdict in the detector"


def test_the_grammar_is_imported_never_retyped():
    src = (ROOT / "scripts" / "check_merge_commit_closures.py").read_text(encoding="utf-8")
    assert "cc.CLOSING_REF_RE" in src, "the closing grammar is defined ONCE in closure_contract.py"
    assert "CLOSING_KEYWORDS = " not in src, "a second copy of the keyword list is how two detectors drift"
