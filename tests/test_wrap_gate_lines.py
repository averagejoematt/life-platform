"""tests/test_wrap_gate_lines.py — the /wrap marker-line assertion + the batched runner (#3006/#3007).

#3006 measured the prose era: eight of eleven wrap gate lines had no assertion, and 20
missing lines in a 25-handover window all fell in four truncated wraps. The fix is
`scripts/check_handover_lines.py` (markers DERIVED from wrap.md, never hand-listed) run
from `scripts/wrap_gates.py --verify` before the wrap commit.

House style is #1189's "no vacuous scans": every rule is planted with a fixture that
violates it AND one that satisfies it. The derivation gets its own mutation proof — a
wrap text with no contract phrases must ERROR (exit 2), never pass-by-empty-set.
"""

import importlib.util
import sys
from pathlib import Path

from skill_paths import require_skill as _skill  # the ONE skill registry (no hard-coded .claude paths)

ROOT = Path(__file__).resolve().parent.parent
WRAP = _skill("wrap")
sys.path.insert(0, str(ROOT / "scripts"))


def _load(name, script):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / script)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


chl = _load("_chl_3006", "check_handover_lines.py")
wg = _load("_wg_3007", "wrap_gates.py")

# The eleven gates' markers as of #3006 — the test's fixture list, NOT the script's
# source of truth (the script derives from wrap.md; this pins that the derivation
# actually finds the full set today).
EXPECTED = {
    "Build beat": "d",
    "Docs": "e",
    "Decisions": "e",
    "Main": "e2",
    "Incidents": "e3",
    "Stash/hooks": "e5",
    "Closures": "e8",
    "Backlog": "e9",
    "Alarms": "e10",
    "CI warnings": "e11",
    "Ledger": "e12",
}


def _markers():
    return chl.derive_markers(WRAP.read_text(encoding="utf-8"))


RESIDUAL = "\n## Residual / next picks\n- #4262 something parked\n"


def _full_handover() -> str:
    return "# Handover\n" + "\n".join(f"**{name}:** something on record" for name in EXPECTED) + RESIDUAL


# ── the derivation reads wrap.md, and finds the whole set ───────────────────────


def test_derivation_finds_every_gate_marker_with_its_step():
    markers = _markers()
    for name, step in EXPECTED.items():
        assert name in markers, f"#3006: wrap.md's ({step}) contract for **{name}:** was not derived"
        assert markers[name] == step, f"**{name}:** derived from step ({markers[name]}), expected ({step})"


def test_derivation_is_not_hand_listed():
    """Acceptance box 2: the marker set must come from wrap.md, so a new gate that states
    the house contract phrase is picked up with NO script change."""
    twelfth = WRAP.read_text(encoding="utf-8") + (
        "\n### (e13) Imaginary gate — a wrap gate, same shape as (d)\n\n- The handover carries one line either way: `**Imaginary:** done`.\n"
    )
    markers = chl.derive_markers(twelfth)
    assert markers.get("Imaginary") == "e13", "#3006: a twelfth gate stating the contract phrase must be derived automatically"


def test_empty_derivation_is_an_error_not_a_pass(tmp_path, capsys):
    """The vacuous-scan guard (#1189): a wrap.md whose contract phrases vanished must exit
    2, never green an empty marker set."""
    bad_wrap = tmp_path / "wrap.md"
    bad_wrap.write_text("### (a) do things\n\nno contracts here\n", encoding="utf-8")
    handover = tmp_path / "h.md"
    handover.write_text(_full_handover(), encoding="utf-8")
    rc = chl.main([str(handover), "--wrap", str(bad_wrap)])
    out = capsys.readouterr().out
    assert rc == 2
    assert "derived only" in out


# ── mutation proofs: green on a complete handover, red on exactly the missing line ──


def test_complete_handover_passes():
    ok, messages = chl.evaluate(_full_handover(), _markers())
    assert ok, f"a handover with every line must pass, got: {messages}"


def test_current_repo_handover_passes():
    """The live green leg: the checked-in HANDOVER_LATEST.md carries all lines today."""
    ok, messages = chl.evaluate((ROOT / "handovers" / "HANDOVER_LATEST.md").read_text(encoding="utf-8"), _markers())
    assert ok, f"the checked-in handover regressed a marker line: {messages}"


def test_each_missing_marker_is_a_named_prompt_not_a_red():
    """#4262: marker lines passed on the presence of a sentence, so they are prompts now —
    a dropped one is NAMED (so the session sees it) but never fails the wrap."""
    markers = _markers()
    for dropped in EXPECTED:
        text = "# Handover\n" + "\n".join(f"**{n}:** something" for n in EXPECTED if n != dropped) + RESIDUAL
        ok, messages = chl.evaluate(text, markers)
        joined = "\n".join(messages)
        assert ok, f"#4262: dropping the optional **{dropped}:** line must NOT fail, got: {joined}"
        assert f"PROMPT — `**{dropped}:**`" in joined, f"the absent line must still be NAMED as a prompt, got: {joined}"
        assert "MISSING" not in joined, f"only an optional line was removed but got: {joined}"


def test_missing_residual_section_is_the_one_red():
    """#4262 mutation: every marker present, the residual section absent -> exit-1 shape.
    check_residual_queue passes vacuously without the section, so this is its one guard."""
    text = "# Handover\n" + "\n".join(f"**{n}:** something" for n in EXPECTED)
    ok, messages = chl.evaluate(text, _markers())
    joined = "\n".join(messages)
    assert not ok, "#4262: a handover with no residual / next-picks section must fail"
    assert "residual / next-picks section" in joined and "MISSING" in joined
    ok, _ = chl.evaluate("# Handover\n" + RESIDUAL, _markers())
    assert ok, "#4262: the residual section alone, with no marker line, must pass"


def test_proportionality_ledger_is_advisory_in_the_wrap_battery():
    """#4262: the (e12) gate passes on a `**Ledger:**` sentence — a marker-line gate — so its
    verdict prints but never fails the wrap; it stays in VERIFY so the prompt is seen."""
    (e12,) = [g for g in wg.VERIFY if "check_proportionality_ledger.py" in " ".join(g.cmd)]
    assert e12.ok_when is not None and e12.ok_when(1, "FAIL") is True


def test_marker_matching_tolerates_the_house_variants():
    for line in ("**Ledger:** none — x", "Ledger: none — x", "- **Ledger:** none — x", "  **ledger:** none — x"):
        assert chl.marker_present(f"# H\n{line}\n", "Ledger"), f"house-variant line {line!r} must count"
    assert not chl.marker_present(
        "# H\nthe session ledger; was updated\n", "Ledger"
    ), "a prose mention without the colon marker must NOT count"


# ── the batched runner (#3007): battery composition, not behaviour re-tests ─────


def test_gather_battery_runs_every_non_handover_gate():
    cmds = [" ".join(g.cmd) for g in wg.GATHER]
    for script in (
        "scripts/check_main_green.py",
        "scripts/check_alarm_citations.py",
        "scripts/check_ci_warnings.py",
        "deploy/session_postflight.py",
    ):
        assert any(script in c for c in cmds), f"#3007: the gather battery must run {script}"
    # #4262: the Docs-CI leg left GATHER — it runs once, in VERIFY, after the docs are written.
    for doc_gate in ("scripts/check_doc_links.py", "scripts/check_doc_index.py", "scripts/generate_adr_index.py --check"):
        assert not any(doc_gate in c for c in cmds), f"#4262: {doc_gate} runs in GATHER again — the doc leg runs once, in VERIFY"
    assert any(g.cmd[:3] == ["git", "stash", "list"] for g in wg.GATHER), "#3007: the (e5) stash check must be in the batch"


def test_e7_moved_to_nightly_and_kept_its_blocking_default():
    """#4262 follow-up: (e7) left the interactive battery for wrap-nightly.yml (wg.NIGHTLY);
    the move must not weaken it back to advisory (#1872), and it must not run in both."""
    (e7,) = [g for g in wg.NIGHTLY if "check_backlog_hygiene.py" in " ".join(g.cmd)]
    assert "--advisory" not in e7.cmd, "#1872: the nightly leg must not weaken (e7) back to advisory"
    assert not any("check_backlog_hygiene.py" in " ".join(g.cmd) for g in wg.GATHER + wg.VERIFY), "#4262: (e7) runs nightly, not in /wrap"


def test_verify_battery_asserts_the_handover_lines():
    cmds = [" ".join(g.cmd) for g in wg.VERIFY]
    for script in (
        "scripts/check_handover_lines.py",
        "scripts/check_residual_queue.py",
        "scripts/check_proportionality_ledger.py",
        "scripts/validate_beats.py",
        "scripts/content_policy_scan.py",
    ):
        assert any(script in c for c in cmds), f"#3006/#3007: the verify battery must run {script}"


def test_no_gate_runs_in_both_phases():
    """#4262: the Docs-CI leg ran in BOTH phases (#3682 added the post-write run and kept
    the pre-write one) — ~11 gates twice per wrap, and the pre-write verdict was always
    superseded by the post-write one. It now runs once, in VERIFY, so the phases share
    nothing: any overlap is accidental double-running, the waste #3007 batched to remove.
    The derived leg must still be present — in VERIFY, whole."""
    gather = {" ".join(g.cmd) for g in wg.GATHER}
    verify = {" ".join(g.cmd) for g in wg.VERIFY}
    assert not (gather & verify), f"gate(s) run in both phases: {sorted(gather & verify)}"
    rvg = wg.restart_verify_gates
    derived = {" ".join(c) for c in rvg.docs_ci_gate_commands() if " ".join(c[1:]) not in rvg.MUTATING_GATES}
    assert derived and derived <= verify, f"the derived doc leg is missing from VERIFY: {sorted(derived - verify)}"


def test_draft_block_covers_every_derived_marker():
    """The Phase 1 draft the session corrects must template every marker line, so the
    one-pass handover write can be complete by construction."""
    lines = wg.draft_lines([])
    for name in _markers():
        assert any(line.startswith(f"**{name}:**") for line in lines), f"#3007: draft block missing **{name}:**"


# ── the wiring: wrap.md actually invokes the machinery ──────────────────────────


def test_wrap_skill_invokes_the_batch_and_the_line_assertion():
    wrap = WRAP.read_text(encoding="utf-8")
    assert "python3 scripts/wrap_gates.py" in wrap, "#3007: the batch runner must be invoked from wrap.md"
    assert "wrap_gates.py --verify" in wrap, "#3006: the verify pass must gate the wrap commit"
    assert "check_handover_lines.py" in wrap, "#3006: wrap.md must name the line assertion"
