"""tests/test_unlinked_closures_3812.py — detector C: the close that never happened (#3812).

The class, measured: Session AF swept 40 open issues by hand and 11 no longer reproduced —
every one already fixed by a merged PR, open 7-17 days. TEN of the eleven named the issue in
the merge commit's subject with no closing keyword. This file is that finding's regression.

The REGRESSION FIXTURE is the real commits (`REAL_AF_COMMITS` below, taken verbatim from
`git log origin/main`), not a paraphrase — a fixture that is not the wire is the class this
repo has been bitten by most (`reference_fixture_must_be_the_wire`).
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"_{name}", SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


uc = _load("check_unlinked_closures")
cc = _load("closure_contract")


def commit(sha="deadbeef1", when="2026-09-15", subject="", body=""):
    return uc.Commit(sha=sha, when=when, subject=subject, body=body)


def issue(number, title="an open issue", labels=()):
    return uc.IssueFacts(number=number, title=title, labels=frozenset(labels))


def codes(findings):
    return sorted(f"{f.code}#{f.issue}" for f in findings)


# ── the real wire ────────────────────────────────────────────────────────────────────────
# Verbatim subjects from origin/main. Each shipped a fix and left its issue open.
REAL_AF_COMMITS = [
    ("f88ea4cb3", 3688, "fix(qa): retry an unreadable judge verdict before calling the surface UNEVALUATED (#3688) (#3811)"),
    ("cf281a65e", 3642, "fix(#3642): agent_commit.sh's --no-verify SET guard — every bypass site enumerated and ratcheted (#3807)"),
    ("aad1d234d", 3753, "feat(training): one server-side planning engine, and the owner's redlines as a file he edits (#3753) (#3776)"),
    ("28247778f", 3830, "fix(canary): a vendor transient is not a deploy-plausible cause — classify the FAILURE (#3830) (#3831)"),
]


def test_the_AF_regression_fixture_is_reported_every_one():
    commits = [commit(sha=sha, subject=subj) for sha, _n, subj in REAL_AF_COMMITS]
    open_issues = {n: issue(n) for _s, n, _t in REAL_AF_COMMITS}
    findings, held = uc.evaluate(commits, open_issues)
    assert codes(findings) == sorted(f"shipped-unlinked#{n}" for _s, n, _t in REAL_AF_COMMITS)
    assert held == []


def test_MUTATION_a_planted_merge_commit_naming_an_open_issue_is_reported():
    """The must-fail control: plant one, it must be named."""
    planted = commit(subject="fix(nothing): a synthetic commit that names an open issue (#99001) (#99999)")
    findings, _held = uc.evaluate([planted], {99001: issue(99001, "a planted open issue")})
    assert codes(findings) == ["shipped-unlinked#99001"]
    assert "99001" in findings[0].detail and "deadbeef1" in findings[0].detail


def test_MUTATION_the_control_goes_SILENT_the_moment_a_closing_keyword_is_added():
    """The same commit with `Fixes #N` must produce nothing — otherwise the detector is
    measuring subject refs, not missing closures."""
    linked = commit(subject="fix(nothing): a synthetic commit (#99001) (#99999)", body="Fixes #99001")
    findings, _held = uc.evaluate([linked], {99001: issue(99001)})
    assert findings == []


@pytest.mark.parametrize("keyword", ["Fixes", "fixes", "Closes", "closed", "Resolves", "resolve"])
def test_every_github_closing_keyword_silences_it(keyword):
    c = commit(subject="fix(x): work (#99001) (#99999)", body=f"{keyword} #99001")
    assert uc.evaluate([c], {99001: issue(99001)})[0] == []


def test_a_live_proof_issue_is_HELD_not_reported():
    """#3595: an instrument closes on its first live output, so `Refs #N` is CORRECT.
    Reporting it would ask the author to do the thing the contract forbids."""
    c = commit(subject="fix(experiment): a config-anchor registry (#3671) (#3810)")
    findings, held = uc.evaluate([c], {3671: issue(3671, "config anchors", labels=[cc.INSTRUMENT_LABEL])})
    assert findings == []
    assert [n for n, _t, _w in held] == [3671]


def test_a_declared_instrument_closure_class_also_holds_it():
    c = commit(subject="fix(x): an instrument (#99001) (#99999)", body="**Closure class:** instrument — closes on its first live emission")
    findings, held = uc.evaluate([c], {99001: issue(99001)})
    assert findings == []
    assert [n for n, _t, _w in held] == [99001]


def test_an_epic_is_never_reported():
    """An epic closes on its Outcome sentence after its children reconcile; detector B
    names an epic IN a closing set as a finding, so C must not ask for one."""
    c = commit(subject="feat(recap): the daily card, as a campaign post (#3741, #3744) (#3780)")
    findings, held = uc.evaluate([c], {3741: issue(3741, "[EPIC] the daily card", labels=["type:epic"])})
    assert findings == [] and held == []


def test_a_closed_issue_is_silent_by_construction():
    c = commit(subject="fix(x): work (#4242) (#99999)")
    assert uc.evaluate([c], {})[0] == []  # 4242 not in the OPEN set


def test_the_trailing_squash_PR_number_is_not_mistaken_for_an_issue():
    """`fix(a): b (#3811)` — GitHub's squash suffix. If it were read as an issue every
    merge would raise a finding against its own PR number."""
    c = commit(subject="fix(qa): retry an unreadable judge verdict (#3811)")
    _closing, subject_refs, _body = uc.parse_refs(c)
    assert subject_refs == set()


def test_a_body_only_ref_is_not_a_finding():
    """`Refs #N` and `**Epic:** #N` are correct and common — 43 raw mentions in the 60-day
    window collapse to 20 subject-level ones. Reporting body refs buries the signal."""
    c = commit(subject="chore(docs): unrelated (#99999)", body="Refs #99001\n**Epic:** #99002")
    findings, _held = uc.evaluate([c], {99001: issue(99001), 99002: issue(99002)})
    assert findings == []


def test_multiple_commits_on_one_issue_collapse_to_one_finding_and_count_them():
    cs = [commit(sha="aaa", subject="fix(a): one (#99001) (#1)"), commit(sha="bbb", subject="fix(a): two (#99001) (#2)")]
    findings, _held = uc.evaluate(cs, {99001: issue(99001)})
    assert len(findings) == 1 and "2 merged commit(s)" in findings[0].detail


def test_the_dispositioned_ledger_suppresses_and_a_MUTATION_of_it_surfaces_the_issue(monkeypatch):
    c = commit(subject="fix(x): work (#99001) (#99999)")
    monkeypatch.setitem(uc.DISPOSITIONED, 99001, "2026-09-16 — context, not a fix")
    assert uc.evaluate([c], {99001: issue(99001)})[0] == []
    monkeypatch.delitem(uc.DISPOSITIONED, 99001)
    assert codes(uc.evaluate([c], {99001: issue(99001)})[0]) == ["shipped-unlinked#99001"]


def test_the_closing_grammar_is_IMPORTED_from_the_registry_not_re_typed():
    """One grammar, one home (#3318). A second regex is how detectors drift apart."""
    src = (SCRIPTS / "check_unlinked_closures.py").read_text(encoding="utf-8")
    assert "cc.CLOSING_REF_RE" in src
    assert "close|closes|closed" not in src, "the keyword list was re-typed instead of imported"


def test_the_finding_code_is_registered_in_the_contract():
    assert "shipped-unlinked" in cc.ALL_FINDING_CODES
    owner = [r for r in cc.CLOSURE_CONTRACT if "shipped-unlinked" in r.finding_codes]
    assert len(owner) == 1 and owner[0].detector == "scripts/check_unlinked_closures.py"


def test_cli_fixture_mode_runs_offline_and_prints_the_contract_line(tmp_path):
    fixture = tmp_path / "f.json"
    fixture.write_text(
        json.dumps(
            {
                "commits": [{"sha": "abc123456", "when": "2026-09-15", "subject": "fix(x): work (#99001) (#99999)", "body": ""}],
                "issues": [{"number": 99001, "title": "an open issue", "labels": []}],
            }
        ),
        encoding="utf-8",
    )
    out = subprocess.run(
        [sys.executable, str(SCRIPTS / "check_unlinked_closures.py"), "--fixture", str(fixture)],
        capture_output=True,
        text=True,
    )
    assert out.returncode == 0, out.stderr  # advisory posture: findings never exit nonzero
    assert "shipped-unlinked  #99001" in out.stdout
    assert "UNLINKED-CLOSURE VERDICT NONGREEN mode=warn" in out.stdout
    assert "findings=1 held=0" in out.stdout


# ── the footgun detector B found in detector C's own name (#3812) ────────────────────────
def test_no_finding_code_ends_in_a_GITHUB_CLOSING_KEYWORD():
    """A detector's REPORT must not be a closing-keyword injection.

    Detector C shipped as `unlinked-shipped-fix`, so its own output line —
        `unlinked-shipped-fix  #3830  1 merged commit(s) name #3830 ...`
    parses as `fix #3830` under GitHub's grammar. Pasting a sweep report into a PR body
    would have CLOSED every issue it names. Detector B caught it on this file's own PR.
    """
    offenders = cc.codes_ending_in_a_closing_keyword()
    assert offenders == {}, (
        "finding code(s) end in a GitHub closing keyword, so printing them next to an issue "
        f"number is a closing reference: {offenders}. Rename, or add a dated ledger entry."
    )


def test_MUTATION_the_guard_reds_on_a_planted_bad_code():
    planted = {"some-new-finding-fixes", "harmless-code"}
    assert cc.codes_ending_in_a_closing_keyword(planted) == {"some-new-finding-fixes": "fixes"}


def test_MUTATION_emptying_the_exemption_ledger_surfaces_the_known_pre_existing_one(monkeypatch):
    """The ledger is hiding exactly one real offender, and it must stay visible as such."""
    monkeypatch.setattr(cc, "CODE_KEYWORD_EXEMPTIONS", {})
    assert cc.codes_ending_in_a_closing_keyword() == {"partial-acceptance-close": "close"}


def test_every_exemption_is_dated_and_reasoned():
    for code, reason in cc.CODE_KEYWORD_EXEMPTIONS.items():
        assert re.match(r"^\d{4}-\d{2}-\d{2} — ", reason), f"{code}: undated exemption"
        assert len(reason) >= 80, f"{code}: reason too thin to audit"


def test_THE_REAL_OUTPUT_LINE_no_longer_parses_as_a_closing_reference():
    """The end-to-end property, on a line the detector actually prints."""
    line = "  shipped-unlinked  #3830  1 merged commit(s) name #3830 in the subject"
    assert [m.group("num") for m in cc.CLOSING_REF_RE.finditer(line)] == []
    bad = line.replace("shipped-unlinked", "unlinked-shipped-fix")
    assert [m.group("num") for m in cc.CLOSING_REF_RE.finditer(bad)] == [
        "3830"
    ], "the old name no longer reproduces the defect — this control has stopped measuring it"
