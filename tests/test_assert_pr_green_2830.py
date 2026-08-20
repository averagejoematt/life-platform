"""tests/test_assert_pr_green_2830.py — mutation proof for the PR-green rollup
assertion (#2830, epic #2753 #5).

`gh pr checks <N> | grep -c` reads BOTH "genuinely zero not-green checks" and
"zero checks have registered at all" as the same green-looking `0`. This file
proves `scripts/assert_pr_green.py` cannot make that mistake by driving its
pure `classify_rollup`/`render` pair (no `gh`, no network) through the three
failure shapes named in the issue, plus the deliberate skip semantics and the
"distinguish no-checks from all-green in the text alone" acceptance box.

Every test that asserts a FAILURE also captures and prints the real message
text (not just the exit code) — the driver asked for the actual failing
output, not a description of it.
"""

import importlib.util
import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SCRIPT = os.path.join(_REPO, "scripts", "assert_pr_green.py")


def _load():
    spec = importlib.util.spec_from_file_location("assert_pr_green_2830", _SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


apg = _load()


def _check_run(name, conclusion, status="COMPLETED"):
    return {"name": name, "status": status, "conclusion": conclusion}


# ── shape 1: empty check list (total == 0) ──────────────────────────────────
def test_empty_check_list_exits_nonzero():
    state = apg.classify_rollup([], expected=None)
    code, message = apg.render(state)
    print("\n--- shape 1: empty check list ---")
    print(f"exit code: {code}")
    print(message)
    assert code != 0
    assert state["total"] == 0
    # The acceptance box: the text alone must distinguish "no checks" from
    # "all green" — assert on the actual distinguishing words, not just != 0.
    assert "EMPTY" in message
    assert "NOT green" in message
    assert "ALL GREEN" not in message


def test_empty_check_list_is_textually_distinct_from_all_green():
    """Same assertion from the other direction: an all-green rollup's message
    must never share the empty-list's language, so an operator (or another
    script) can tell the two apart by string content alone."""
    empty_code, empty_message = apg.render(apg.classify_rollup([], expected=None))
    green_code, green_message = apg.render(
        apg.classify_rollup([_check_run("Collect + deploy-critical + format", "SUCCESS")], expected=None)
    )
    assert empty_code != 0
    assert green_code == 0
    assert "ALL GREEN" in green_message
    assert "ALL GREEN" not in empty_message
    assert "EMPTY" in empty_message
    assert "EMPTY" not in green_message


# ── shape 2: a not-green member present ─────────────────────────────────────
def test_a_failing_check_exits_nonzero():
    entries = [
        _check_run("Collect + deploy-critical + format", "SUCCESS"),
        _check_run("gitleaks (PR commit range only, not full history)", "FAILURE"),
    ]
    state = apg.classify_rollup(entries, expected=None)
    code, message = apg.render(state)
    print("\n--- shape 2: a not-green member present ---")
    print(f"exit code: {code}")
    print(message)
    assert code != 0
    assert len(state["red"]) == 1
    assert state["red"][0]["name"] == "gitleaks (PR commit range only, not full history)"
    assert state["red"][0]["state"] == "FAILURE"
    assert "NOT GREEN" in message
    assert "gitleaks" in message


def test_an_in_progress_check_counts_as_not_green():
    """A check that simply hasn't finished yet is exactly the "hasn't
    registered / hasn't reported a verdict" shape — it must not read as
    green just because it isn't a hard failure."""
    entries = [_check_run("Collect + deploy-critical + format", None, status="IN_PROGRESS")]
    state = apg.classify_rollup(entries, expected=None)
    code, _ = apg.render(state)
    assert code != 0
    assert len(state["red"]) == 1
    assert state["red"][0]["state"] == "IN_PROGRESS"


# ── shape 3: a missing expected check ───────────────────────────────────────
def test_missing_expected_check_exits_nonzero_even_when_rollup_is_all_green():
    entries = [_check_run("Collect + deploy-critical + format", "SUCCESS")]
    expected = {"Collect + deploy-critical + format", "gitleaks (PR commit range only, not full history)"}
    state = apg.classify_rollup(entries, expected=expected)
    code, message = apg.render(state)
    print("\n--- shape 3: missing expected check (rollup otherwise all green) ---")
    print(f"exit code: {code}")
    print(message)
    assert code != 0
    # The rollup itself has zero red entries — proves the missing-expected
    # path is a SEPARATE assertion from the not-green count, per the issue's
    # "gh pr checks 2915 --json bucket: notgreen=0, total=7" near-miss shape.
    assert state["red"] == []
    assert state["missing_expected"] == ["gitleaks (PR commit range only, not full history)"]
    assert "MISSING from the rollup entirely" in message
    assert "gitleaks" in message


def test_expected_check_present_only_as_skipped_is_not_green():
    """A distinct failure mode from "missing entirely": the check ran (or was
    evaluated) and reported SKIPPED, so it is present-but-unsatisfying, not
    absent. Both must fail, with different wording."""
    entries = [_check_run("validate", "SKIPPED")]
    state = apg.classify_rollup(entries, expected={"validate"})
    code, message = apg.render(state)
    assert code != 0
    assert state["missing_expected"] == []
    assert state["not_green_expected"] == ["validate"]
    assert "present but NOT GREEN" in message


# ── skip semantics: deliberate third state, never silently green or red ────
def test_skip_does_not_fail_the_aggregate_assertion():
    """A skipped check (e.g. Dependabot Validate on a human PR) must not make
    an otherwise-clean PR read as not-green."""
    entries = [
        _check_run("Collect + deploy-critical + format", "SUCCESS"),
        _check_run("validate", "SKIPPED"),
    ]
    state = apg.classify_rollup(entries, expected=None)
    code, message = apg.render(state)
    assert code == 0
    assert state["red"] == []
    assert len(state["skipped"]) == 1
    assert "ALL GREEN" in message
    assert "skipped" in message.lower()


def test_skip_is_not_silently_treated_as_green_either():
    """Skip is excluded from BOTH the red count and the green_names set — it
    must never satisfy an expected-check requirement (see the present-only-
    as-skipped test above) even though it also never fails assertion 1 alone."""
    state = apg.classify_rollup([_check_run("validate", "SKIPPED")], expected=None)
    assert state["green_names"] == []
    assert state["red"] == []
    assert len(state["skipped"]) == 1


# ── derivation source (posture-file, not a live gh/network call) ───────────
def test_derive_expected_from_posture_reads_real_required_contexts():
    names = apg.derive_expected_from_posture()
    assert names is not None
    assert "Collect + deploy-critical + format" in names
    assert "gitleaks (PR commit range only, not full history)" in names


def test_derive_expected_from_posture_fails_soft_on_missing_file():
    assert apg.derive_expected_from_posture(path="/nonexistent/does/not/exist.json") is None


# ── CLI wiring smoke: main() degrades loudly, never silently, on a gh error ─
def test_main_degrades_to_nonzero_on_gh_failure(monkeypatch):
    def _boom(args):
        raise RuntimeError("gh pr view 999999 failed (exit 1): could not resolve to a PullRequest")

    monkeypatch.setattr(apg, "_gh_json", _boom)
    code = apg.main(["999999"])
    assert code != 0


if __name__ == "__main__":
    # Smoke block per the driver brief: run the three failure shapes and
    # print their real message text without pytest's capture.
    for label, entries, expected in [
        ("empty check list", [], None),
        (
            "a not-green member present",
            [
                _check_run("Collect + deploy-critical + format", "SUCCESS"),
                _check_run("gitleaks (PR commit range only, not full history)", "FAILURE"),
            ],
            None,
        ),
        (
            "missing expected check",
            [_check_run("Collect + deploy-critical + format", "SUCCESS")],
            {"Collect + deploy-critical + format", "gitleaks (PR commit range only, not full history)"},
        ),
    ]:
        c, m = apg.render(apg.classify_rollup(entries, expected=expected))
        print(f"\n=== {label} === exit={c}")
        print(m)
    sys.exit(0)
