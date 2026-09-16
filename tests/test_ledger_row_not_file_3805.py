"""tests/test_ledger_row_not_file_3805.py — #3805: the gate checked the FILE, not the ROW.

`scripts/check_proportionality_ledger.py` exists to stop one thing — its own error text:
*"a claimed row the ledger never saw is the exact silent pass this gate replaces"*. It
checked `ledger_diff_this_session()`, which returned True for ANY commit touching
docs/PROPORTIONALITY.md since the last `docs(wrap` commit.

That file carries a MACHINE-WRITTEN literal: `<n> declared gates`, the `gate_census_count`
fact, rewritten by deploy/sync_census_fact.py on any PR that adds a source-scanning guard.
So the gate was satisfiable by a bot bumping a counter — and every session that adds a
guard bumps it.

Demonstrated on `spike/xdist-3025`, whose ONLY change to that file was
`639 declared gates` -> `640`: the gate printed OK, and the claim it validated belonged to a
DIFFERENT session.
"""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEDGER = ROOT / "docs" / "PROPORTIONALITY.md"


def _gate():
    spec = importlib.util.spec_from_file_location("_plg_3805", ROOT / "scripts" / "check_proportionality_ledger.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


g = _gate()


def _real_census_line() -> str:
    """The REAL line from the REAL file — box 4 asks for the specimen, not a hand-typed twin."""
    lines = [ln for ln in LEDGER.read_text(encoding="utf-8").splitlines() if "declared gates" in ln]
    assert lines, "no `<n> declared gates` line in the ledger — the sync-owned fact moved"
    return lines[0]


def _counter_only_diff() -> str:
    real = _real_census_line()
    m = re.search(r"(\d+) declared gates", real)
    bumped = real.replace(m.group(0), f"{int(m.group(1)) + 1} declared gates")
    return f"--- a/docs/PROPORTIONALITY.md\n+++ b/docs/PROPORTIONALITY.md\n-{real}\n+{bumped}\n"


# ── box 1: the row, not the file ─────────────────────────────────────────────────────────
def test_the_sync_owned_pattern_is_DERIVED_from_the_writer_not_retyped():
    """If the bot's own rule changes, the exclusion must move with it."""
    pats = g._sync_owned_patterns(ROOT)
    assert pats is not None, "the derivation failed — the gate must go UNVERIFIED, not pass"
    src = (ROOT / "scripts" / "check_proportionality_ledger.py").read_text(encoding="utf-8")
    assert "sync_census_fact.py" in src and "_RULE" in src, "the pattern is re-typed rather than derived"
    assert any("declared gates" in p.pattern for p in pats)


def test_MUST_FAIL_a_counter_only_diff_is_NOT_a_ledger_row():
    """The spike/xdist-3025 specimen, reproduced from the real file."""
    pats = g._sync_owned_patterns(ROOT)
    assert (
        g._substantive_ledger_lines(_counter_only_diff(), pats) == []
    ), "a counter-only bump still reads as a ledger row — the gate is satisfiable by a bot (#3805)"


def test_a_REAL_row_beside_the_counter_bump_is_still_seen():
    """The control without which the fix above is just a disabled gate."""
    pats = g._sync_owned_patterns(ROOT)
    row = "| A brand new subsystem | Load-bearing | some rent | some evidence |"
    found = g._substantive_ledger_lines(_counter_only_diff() + f"+{row}\n", pats)
    assert any("A brand new subsystem" in f for f in found), f"a real added row was swallowed: {found}"


def test_a_bare_date_restamp_is_also_cosmetic():
    """#2986's class, same reasoning — no manufactured freshness."""
    pats = g._sync_owned_patterns(ROOT)
    diff = "--- a/x\n+++ b/x\n-**Re-read**: 2026-08-27\n+**Re-read**: 2026-09-16\n"
    assert g._substantive_ledger_lines(diff, pats) == []


def test_an_UNAVAILABLE_derivation_is_UNVERIFIED_not_a_pass(monkeypatch):
    """A gate whose evidence source is missing must not silently succeed."""
    monkeypatch.setattr(g, "_sync_owned_patterns", lambda _root: None)
    assert g.ledger_diff_this_session(ROOT) is None


# ── box 2: the claim and the diff are anchored to the same session ───────────────────────
def test_MUST_FAIL_a_previous_sessions_claim_cannot_be_validated_by_this_sessions_diff():
    ok, msgs = g.evaluate("**Ledger:** progress-photo capture row added\n", True, handover_is_this_session=False)
    assert ok is False
    assert any("UNANCHORED" in m for m in msgs), msgs


def test_the_same_claim_passes_when_the_handover_IS_this_session():
    ok, _msgs = g.evaluate("**Ledger:** progress-photo capture row added\n", True, handover_is_this_session=True)
    assert ok is True


def test_the_anchor_is_UNKNOWN_safe():
    """`None` (git unreachable, or --diff forced) must not fabricate an anchor verdict."""
    ok, _msgs = g.evaluate("**Ledger:** a row added\n", True, handover_is_this_session=None)
    assert ok is True


# ── box 3: the four unexamined VERIFY gates get a stated verdict ─────────────────────────
VERIFY_SIBLINGS = (
    "check_handover_lines.py",
    "check_residual_queue.py",
    "content_policy_scan.py",
    "validate_beats.py",
)


def test_the_sibling_VERIFY_gates_read_CONTENT_not_a_diff_proxy():
    """Box 3 asks for a verdict on each, not silence.

    Measured 2026-09-16: all four parse the artifact's CONTENT and none consults git for a
    diff/existence signal, so none can be satisfied by a machine-written line moving. The
    shape is unique to check_proportionality_ledger among the VERIFY battery.

    This is an assertion rather than a comment so the verdict expires loudly: if a sibling
    ever grows a git-diff proxy, it must be re-examined rather than inheriting a clean bill
    of health from a sweep nobody re-ran.
    """
    offenders = []
    for name in VERIFY_SIBLINGS:
        src = (ROOT / "scripts" / name).read_text(encoding="utf-8")
        code = "\n".join(ln for ln in src.splitlines() if not ln.lstrip().startswith("#"))
        if re.search(r"""subprocess\.run\(\s*\[\s*["']git["']""", code):
            offenders.append(name)
    assert offenders == [], (
        f"{offenders} now shell out to git — re-examine each for the #3805 shape "
        "(asserting an artifact CHANGED without asserting WHAT changed)"
    )


def test_the_gate_still_runs_end_to_end_on_the_real_repo():
    out = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_proportionality_ledger.py"), str(ROOT / "handovers" / "HANDOVER_LATEST.md")],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    assert out.returncode in (0, 1), out.stdout + out.stderr
    assert out.stdout.strip(), "the gate printed nothing — a silent gate is the #3805 class again"


# ── THE SEAM: the gate must actually USE the row-level check ─────────────────────────────
def _tmp_repo_with(tmp_path, ledger_body, extra_commit=None):
    """A throwaway git repo carrying a `docs(wrap` boundary, then one ledger change."""
    import os

    r = tmp_path / "repo"
    (r / "docs").mkdir(parents=True)
    (r / "scripts").mkdir(parents=True)
    (r / "deploy").mkdir(parents=True)
    # the derivation source the gate reads, copied from the real repo so the pattern is real
    (r / "deploy" / "sync_census_fact.py").write_text(
        (ROOT / "deploy" / "sync_census_fact.py").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (r / "docs" / "PROPORTIONALITY.md").write_text(ledger_body, encoding="utf-8")
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    run = lambda *a: subprocess.run(["git", *a], cwd=r, capture_output=True, text=True, env=env)  # noqa: E731
    run("init", "-q", ".")
    run("add", "-A")
    run("commit", "-q", "-m", "docs(wrap): session boundary")
    if extra_commit is not None:
        (r / "docs" / "PROPORTIONALITY.md").write_text(extra_commit, encoding="utf-8")
        run("add", "-A")
        run("commit", "-q", "-m", "chore: a change")
    return r


_BASE_LEDGER = "| Gate census | Load-bearing | rent | 646 declared gates with measured error bars |\n"


def test_SEAM_MUST_FAIL_ledger_diff_this_session_returns_False_on_a_counter_only_commit(tmp_path):
    """Without this, reverting the wiring to "any diff at all" goes UNDETECTED.

    The pure `_substantive_ledger_lines` controls above pass either way — they never
    exercise whether `ledger_diff_this_session` calls it. A check nothing calls is not a
    fix; this is the seam.
    """
    repo = _tmp_repo_with(
        tmp_path,
        _BASE_LEDGER,
        extra_commit=_BASE_LEDGER.replace("646 declared gates", "647 declared gates"),
    )
    assert g.ledger_diff_this_session(repo) is False, (
        "a counter-only commit still reads as a ledger row through the real entry point — " "the row-level check is not wired in (#3805)"
    )


def test_SEAM_a_real_added_row_DOES_return_True(tmp_path):
    """The matched control: the seam must still see genuine work."""
    repo = _tmp_repo_with(
        tmp_path,
        _BASE_LEDGER,
        extra_commit=_BASE_LEDGER + "| A brand new subsystem | Load-bearing | rent | evidence |\n",
    )
    assert g.ledger_diff_this_session(repo) is True


def test_SEAM_no_ledger_change_at_all_is_False(tmp_path):
    repo = _tmp_repo_with(tmp_path, _BASE_LEDGER)
    assert g.ledger_diff_this_session(repo) is False
