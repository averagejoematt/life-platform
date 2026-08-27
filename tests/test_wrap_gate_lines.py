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


def _full_handover() -> str:
    return "# Handover\n" + "\n".join(f"**{name}:** something on record" for name in EXPECTED)


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


def test_each_missing_line_is_red_and_named():
    markers = _markers()
    for dropped in EXPECTED:
        text = "# Handover\n" + "\n".join(f"**{n}:** something" for n in EXPECTED if n != dropped)
        ok, messages = chl.evaluate(text, markers)
        joined = "\n".join(messages)
        assert not ok, f"dropping **{dropped}:** must fail"
        assert f"`**{dropped}:**`" in joined and "MISSING" in joined, f"the missing line must be NAMED, got: {joined}"
        # exactly the dropped one, not a shotgun
        assert joined.count("MISSING") == 1, f"only **{dropped}:** was removed but got: {joined}"


def test_marker_matching_tolerates_the_house_variants():
    markers = {"Ledger": "e12"}
    for line in ("**Ledger:** none — x", "Ledger: none — x", "- **Ledger:** none — x", "  **ledger:** none — x"):
        ok, _ = chl.evaluate(f"# H\n{line}\n", markers)
        assert ok, f"house-variant line {line!r} must count"
    ok, _ = chl.evaluate("# H\nthe session ledger; was updated\n", markers)
    assert not ok, "a prose mention without the colon marker must NOT count"


# ── the batched runner (#3007): battery composition, not behaviour re-tests ─────


def test_gather_battery_runs_every_non_handover_gate():
    cmds = [" ".join(g.cmd) for g in wg.GATHER]
    for script in (
        "scripts/check_main_green.py",
        "scripts/check_backlog_hygiene.py",
        "scripts/check_alarm_citations.py",
        "scripts/check_ci_warnings.py",
        "scripts/check_doc_links.py",
        "scripts/check_doc_tombstones.py",
        "scripts/check_doc_index.py",
        "scripts/generate_adr_index.py --check",
        "deploy/session_postflight.py",
    ):
        assert any(script in c for c in cmds), f"#3007: the gather battery must run {script}"
    assert any(g.cmd[:3] == ["git", "stash", "list"] for g in wg.GATHER), "#3007: the (e5) stash check must be in the batch"


def test_gather_battery_preserves_e7_blocking_default():
    (e7,) = [g for g in wg.GATHER if "check_backlog_hygiene.py" in " ".join(g.cmd)]
    assert "--advisory" not in e7.cmd, "#1872: the batch must not weaken (e7) back to advisory"


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


def test_no_gate_appears_in_both_phases():
    gather = {" ".join(g.cmd) for g in wg.GATHER}
    verify = {" ".join(g.cmd) for g in wg.VERIFY}
    assert not gather & verify


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
