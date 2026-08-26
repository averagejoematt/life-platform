"""tests/test_main_green_head_discriminator_3212.py — #3212.

`scripts/check_main_green.py` owned a tested discriminator
(`classify_zero_run_head`, #2826) that told a genuine SWALLOWED PUSH apart from
an ordinary path-filter skip — and wired it into exactly ONE of its two
consumers. The scheduled `--head-coverage-check` path called it; `main()`, the
gate every session runs at boot and at wrap, printed the #2762 swallowed-push
text on any `uncovered` HEAD without ever asking.

Live-proved at Session E boot — same repo, same file, same sha (main's HEAD
57baffd9, Session D's docs-only wrap commit), two different answers:

    $ python3 scripts/check_main_green.py                       # EXIT 1, "swallowed-push shape"
    $ python3 scripts/check_main_green.py --head-coverage-check # EXIT 0, "expected path-filter skip"

The second was correct: five sibling workflows minted runs at that exact sha,
and a swallow is zero runs of ANY workflow.

THE MUTATION PROOF THIS FILE EXISTS FOR
  A fix that silences BOTH directions is a false green — the specific outcome
  this issue exists to prevent. So the two headline tests pull in opposite
  directions and both fail on the pre-fix code:

    * `test_MUTATION_genuine_swallow_still_reds_the_gate` — a HEAD with zero
      runs of anything must still exit 1, and must NAME `swallowed` (pre-fix:
      exits 1 by accident, but names nothing — no state is ever concluded).
    * `test_MUTATION_path_filter_skip_head_does_not_red_the_gate` — a HEAD whose
      diff touches none of ci-cd.yml's `paths:` filter, with sibling workflows
      present, must exit 0 (pre-fix: exits 1, claiming a swallowed push).

  Deleting the discriminator call fails the second; hardcoding "expected skip"
  fails the first. Neither can be satisfied by a suppressor that always says yes.

Every test drives the REAL CLI entry points (`main()`, `main_head_coverage()`)
with a faked `gh`, never the pure helpers alone — the whole bug was a tested
pure function nobody could reach from the command a human runs.
"""

import importlib.util
import os
import sys
import types

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("cmg_3212", os.path.join(_REPO, "scripts", "check_main_green.py"))
cmg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cmg)

sys.path.insert(0, os.path.join(_REPO, "scripts"))
import wrap_gates as wg  # noqa: E402

HEAD = "b" * 40
OLD = "a" * 40
GREEN_RUN_AT_OLD = {"status": "completed", "conclusion": "success", "headSha": OLD, "databaseId": 1, "createdAt": "2026-08-26T01:00:00Z"}

# The real shapes, from the payloads #2826's fixtures captured.
SIBLING_RUNS = [
    {"id": 32412461126, "name": "Docs CI", "status": "completed", "conclusion": "success"},
    {"id": 32415036516, "name": "Visual QA (standalone)", "status": "in_progress", "conclusion": None},
]
DOCS_ONLY_FILES = ["CLAUDE.md", "handovers/HANDOVER_LATEST.md", "docs/CONVENTIONS.md"]
IN_SCOPE_FILES = ["lambdas/ingestion/whoop_ingestion.py"]


class _FakeGh:
    """Dispatches on the `gh` argv from canned responses keyed by a substring,
    and raises on anything NOT stubbed — a test passes only if the CLI made the
    calls it claims to and no others."""

    def __init__(self, responses: dict):
        self.responses = responses
        self.calls: list = []

    def __call__(self, args: list):
        self.calls.append(args)
        joined = " ".join(str(a) for a in args)
        for key, value in self.responses.items():
            if key in joined:
                if isinstance(value, Exception):
                    raise value
                return value
        raise AssertionError(f"unstubbed gh call in test: {args}")


@pytest.fixture(autouse=True)
def _offline_wedge_detector(monkeypatch):
    """`main()` imports check_deploy_wedge and calls collect(), which hits the
    network. Stub it to the "no wedge" answer so these tests are hermetic."""
    fake = types.ModuleType("check_deploy_wedge")
    fake.collect = lambda: ([], {}, {})
    fake.classify_fleet = lambda *_a, **_k: {"verdicts": []}
    monkeypatch.setitem(sys.modules, "check_deploy_wedge", fake)


def _gh_for(all_runs, files, committer="averagejoematt"):
    """A green CI/CD run at an OLDER sha (so HEAD reads `uncovered`), plus the
    fleet-level facts the discriminator needs at HEAD."""
    return _FakeGh(
        {
            "run list": [GREEN_RUN_AT_OLD],
            "branches/main": {"commit": {"sha": HEAD}},
            f"actions/runs?head_sha={HEAD}": {"workflow_runs": all_runs},
            f"commits/{HEAD}": {"files": [{"filename": f} for f in files], "committer": {"login": committer}},
        }
    )


def _run_main(monkeypatch, gh, argv=("check_main_green.py",)):
    monkeypatch.setattr(cmg, "_gh_json", gh)
    monkeypatch.setattr(sys, "argv", list(argv))
    return cmg.main()


# ─────────────────────────────────────────────────────────────────────────
# THE TWO MUTATION PROOFS — they must pull in opposite directions
# ─────────────────────────────────────────────────────────────────────────


def test_MUTATION_genuine_swallow_still_reds_the_gate(monkeypatch, capsys):
    """Zero runs of ANY workflow at HEAD (the #2662 / PR-#2916 shape) is a real
    swallowed push: exit 1, the #2762 recovery text preserved verbatim, and the
    concluded state NAMED as `swallowed`.

    Pre-fix this exits 1 for the wrong reason — the gate never concludes a
    state at all, so the `HEAD-COVERAGE:` assertion fails."""
    gh = _gh_for(all_runs=[], files=IN_SCOPE_FILES)
    code = _run_main(monkeypatch, gh)
    out = capsys.readouterr().out
    assert code == 1, out
    assert "swallowed-push shape (#2762)" in out
    assert "Re-push or workflow_dispatch ci-cd.yml" in out
    assert f"{cmg.HEAD_COVERAGE_PREFIX} {cmg.ZR_SWALLOWED} {HEAD[:8]}" in out


def test_MUTATION_path_filter_skip_head_does_not_red_the_gate(monkeypatch, capsys):
    """The live Session E shape: CI/CD absent at HEAD, sibling workflows present,
    the diff touching none of ci-cd.yml's `paths:` filter. Expected, not an
    incident — exit 0, no swallow claim, state named.

    Pre-fix this exits 1 and prints the swallowed-push text."""
    gh = _gh_for(all_runs=SIBLING_RUNS, files=DOCS_ONLY_FILES)
    code = _run_main(monkeypatch, gh)
    out = capsys.readouterr().out
    assert code == 0, out
    assert "swallowed-push shape (#2762)" not in out
    assert "🛑" not in out
    assert f"{cmg.HEAD_COVERAGE_PREFIX} {cmg.ZR_PATH_FILTER_SKIP} {HEAD[:8]}" in out
    assert "Docs CI" in out  # it names WHY, not just that it declined to fail


# ─────────────────────────────────────────────────────────────────────────
# the other two states
# ─────────────────────────────────────────────────────────────────────────


def test_bot_push_that_cannot_dispatch_is_not_a_gate_failure(monkeypatch, capsys):
    """The nightly `chore(reconcile)` commit: pushed with GITHUB_TOKEN (which
    GitHub never dispatches workflows for) AND touching lambdas/** — the
    partial-swallow branch, were it not for the committer check."""
    gh = _gh_for(all_runs=[], files=["lambdas/web/platform_counts.py"], committer="github-actions[bot]")
    code = _run_main(monkeypatch, gh)
    out = capsys.readouterr().out
    assert code == 0, out
    assert f"{cmg.HEAD_COVERAGE_PREFIX} {cmg.ZR_BOT_PUSH_NO_DISPATCH} {HEAD[:8]}" in out
    assert "swallowed-push shape (#2762)" not in out


def test_indeterminate_neither_passes_silently_nor_claims_a_swallow(monkeypatch, capsys):
    """The all-workflow read failed: the gate cannot tell. It must stay
    non-green (never a silent pass) while explicitly NOT asserting a confirmed
    swallow — the two must not be conflated, exactly as the scheduled consumer's
    exit-2 band already refuses to conflate them."""
    gh = _FakeGh(
        {
            "run list": [GREEN_RUN_AT_OLD],
            "branches/main": {"commit": {"sha": HEAD}},
            f"actions/runs?head_sha={HEAD}": RuntimeError("API rate limited"),
        }
    )
    code = _run_main(monkeypatch, gh)
    out = capsys.readouterr().out
    assert code == 1, out
    assert "swallowed-push shape (#2762)" not in out
    assert "could NOT be determined" in out
    assert f"{cmg.HEAD_COVERAGE_PREFIX} {cmg.ZR_INDETERMINATE} {HEAD[:8]}" in out


def test_unreadable_changed_files_is_indeterminate_not_an_expected_skip(monkeypatch, capsys):
    """A commits/ read failure leaves `changed_paths` unknown. It must NOT
    become a free pass — that would be a suppressor that cannot fail."""
    gh = _FakeGh(
        {
            "run list": [GREEN_RUN_AT_OLD],
            "branches/main": {"commit": {"sha": HEAD}},
            f"actions/runs?head_sha={HEAD}": {"workflow_runs": SIBLING_RUNS},
            f"commits/{HEAD}": RuntimeError("502"),
        }
    )
    code = _run_main(monkeypatch, gh)
    out = capsys.readouterr().out
    assert code == 1, out
    assert f"{cmg.HEAD_COVERAGE_PREFIX} {cmg.ZR_INDETERMINATE} {HEAD[:8]}" in out


def test_a_diff_that_DOES_touch_the_filter_is_still_a_partial_swallow(monkeypatch, capsys):
    """Siblings ran and ci-cd.yml did not, but the diff IS in scope — ci-cd.yml
    should have run. Still a swallow; the exemption is structural (the state
    constant), never "some other workflow ran, therefore fine"."""
    gh = _gh_for(all_runs=SIBLING_RUNS, files=IN_SCOPE_FILES)
    code = _run_main(monkeypatch, gh)
    out = capsys.readouterr().out
    assert code == 1, out
    assert f"{cmg.HEAD_COVERAGE_PREFIX} {cmg.ZR_SWALLOWED} {HEAD[:8]}" in out


def test_covered_head_never_fetches_the_discriminator_inputs(monkeypatch, capsys):
    """The ordinary case stays exactly as it was, and costs no extra API calls:
    the all-workflow / commits reads are unstubbed here and would raise."""
    at_head = {"status": "completed", "conclusion": "success", "headSha": HEAD, "databaseId": 7, "createdAt": "2026-08-26T01:00:00Z"}
    gh = _FakeGh({"run list": [at_head], "branches/main": {"commit": {"sha": HEAD}}})
    code = _run_main(monkeypatch, gh)
    out = capsys.readouterr().out
    assert code == 0, out
    assert f"{cmg.HEAD_COVERAGE_PREFIX} covered {HEAD[:8]}" in out
    assert len(gh.calls) == 2


# ─────────────────────────────────────────────────────────────────────────
# the wiring itself — the #3212 shape was "one consumer, not two"
# ─────────────────────────────────────────────────────────────────────────


def test_both_consumers_share_the_one_diagnose_step(monkeypatch):
    """The regression guard for this issue's actual shape: BOTH CLI paths must
    route through the same fetch+classify step. A future divergence that gives
    one consumer its own copy re-opens #3212."""
    seen = []

    def _spy(head_sha):
        seen.append(head_sha)
        return {"state": cmg.ZR_PATH_FILTER_SKIP, "reason": "spy", "warnings": []}

    monkeypatch.setattr(cmg, "diagnose_uncovered_head", _spy)
    monkeypatch.setattr(cmg, "_gh_json", _FakeGh({"run list": [GREEN_RUN_AT_OLD], "branches/main": {"commit": {"sha": HEAD}}}))
    monkeypatch.setattr(sys, "argv", ["check_main_green.py"])
    assert cmg.main() == 0
    assert cmg.main_head_coverage() == 0
    assert seen == [HEAD, HEAD], "both main() and main_head_coverage() must call diagnose_uncovered_head"


def test_render_without_a_discriminator_verdict_is_indeterminate_not_a_swallow():
    """A caller that never ran the discriminator knows NOTHING about why HEAD is
    uncovered. It must not inherit a confirmed-swallow claim (the #3212 bug in
    miniature) and must not pass either."""
    state = cmg.classify_pipeline([GREEN_RUN_AT_OLD])
    state["head_sha"] = HEAD
    state["head_cov"] = cmg.head_coverage([GREEN_RUN_AT_OLD], HEAD)
    code, msg = cmg.render(state)
    assert code == 1
    assert "swallowed-push shape (#2762)" not in msg
    assert f"{cmg.HEAD_COVERAGE_PREFIX} {cmg.ZR_INDETERMINATE}" in msg


def test_the_two_exempt_states_are_a_constant_set_not_a_phrase_match():
    """Suppressor rules must be structural. The exemption is a frozenset of the
    discriminator's own state constants — never a substring of a workflow name
    or of the reason text."""
    assert cmg.ZR_NOT_A_FAILURE == frozenset({cmg.ZR_PATH_FILTER_SKIP, cmg.ZR_BOT_PUSH_NO_DISPATCH})
    assert cmg.ZR_SWALLOWED not in cmg.ZR_NOT_A_FAILURE
    assert cmg.ZR_INDETERMINATE not in cmg.ZR_NOT_A_FAILURE


# ─────────────────────────────────────────────────────────────────────────
# wrap_gates.py — the marker line the handover quotes
# ─────────────────────────────────────────────────────────────────────────


def _draft_main_line(out: str, ok: bool) -> str:
    gate = wg.Gate("main-green", "e2", ["python3", "scripts/check_main_green.py"], marker="Main")
    lines = wg.draft_lines([(gate, ok, 0 if ok else 1, out)])
    return next(ln for ln in lines if ln.startswith("**Main:**"))


def test_wrap_gate_marker_names_the_path_filter_skip_instead_of_bare_green():
    """`green (5ecc3a1f)` alone would attribute the verdict to a sha that is NOT
    HEAD — the exact wrong record Session D's handover wrote by hand."""
    out = (
        "✅ main GREEN — latest completed CI/CD run (5ecc3a1f) succeeded.\n"
        f"{cmg.HEAD_COVERAGE_PREFIX} {cmg.ZR_PATH_FILTER_SKIP} 57baffd9"
    )
    line = _draft_main_line(out, ok=True)
    assert "5ecc3a1f" in line and "57baffd9" in line
    assert cmg.ZR_PATH_FILTER_SKIP in line
    assert "not a swallow" in line


def test_wrap_gate_marker_is_unchanged_for_an_ordinary_covered_green():
    out = "✅ main GREEN — latest completed CI/CD run (5ecc3a1f) succeeded.\n" f"{cmg.HEAD_COVERAGE_PREFIX} covered 5ecc3a1f"
    assert _draft_main_line(out, ok=True) == "**Main:** green (5ecc3a1f)"


def test_wrap_gate_decode_line_ignores_the_machine_readable_tail():
    """The contract line is the LAST line of the gate's output; the decode a
    human needs is the sentence above it."""
    out = "❌ main is FAILURE at 5ecc3a1f.\n" "   Unit Tests failed — see run 123.\n" f"{cmg.HEAD_COVERAGE_PREFIX} covered 5ecc3a1f"
    line = _draft_main_line(out, ok=False)
    assert "Unit Tests failed" in line
    assert cmg.HEAD_COVERAGE_PREFIX not in line


def test_wrap_gate_marker_calls_an_indeterminate_head_undetermined_not_red():
    out = "✅ main GREEN — latest completed CI/CD run (5ecc3a1f) succeeded.\n" f"{cmg.HEAD_COVERAGE_PREFIX} {cmg.ZR_INDETERMINATE} 57baffd9"
    line = _draft_main_line(out, ok=False)
    assert "undetermined" in line and "57baffd9" in line


# ─────────────────────────────────────────────────────────────────────────
# the cosmetic bug the issue asked to verify (scope-limited)
# ─────────────────────────────────────────────────────────────────────────


def test_reason_text_renders_the_paths_key_as_code_not_as_a_stray_yaml_key():
    """Live output read `…none of ci-cd.yml's paths: filter`, which parses to the
    eye as a mangled YAML key. It is prose, not a parse — backtick the key."""
    ci = ["lambdas/**", "tests/**"]
    skip = cmg.classify_zero_run_head(SIBLING_RUNS, DOCS_ONLY_FILES, ci)
    partial = cmg.classify_zero_run_head(SIBLING_RUNS, IN_SCOPE_FILES, ci)
    assert "`paths:` filter" in skip["reason"]
    assert "`paths:` filter" in partial["reason"]
    assert "s paths: filter" not in skip["reason"]
