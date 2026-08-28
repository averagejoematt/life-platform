"""tests/test_proportionality_ledger_gate_2761.py — the /wrap proportionality-ledger gate (#2380/#2761).

Replays the review finding: the #2380 gate was prose wedged into wrap step (e10) with a
conditional trigger nothing evaluated — a check that could not fail. Measured: zero
`docs/PROPORTIONALITY.md` commits in its first week while four standing subsystems
shipped with real rent (#2572, #2552, #2527, #2578), and zero `ledger:` lines in any
handover. The fix (#2761): the assertion becomes `scripts/check_proportionality_ledger.py`,
wired as wrap step (e12), unconditional — a `docs/PROPORTIONALITY.md` diff this session
or an explicit `**Ledger:**` line, or the wrap fails.

Every test here fails on the pre-#2761 tree (no script, no (e12) step, no guardrail).
`test_silent_omission_is_flagged` is the acceptance's labelled positive: a wrap input
lacking BOTH the diff and the line is flagged.
"""

import importlib.util
import subprocess
import sys
from pathlib import Path

from skill_paths import require_skill as _skill  # the ONE skill registry (no hard-coded .claude paths)

ROOT = Path(__file__).resolve().parent.parent
WRAP = _skill("wrap")
SCRIPT = ROOT / "scripts" / "check_proportionality_ledger.py"


def _load():
    spec = importlib.util.spec_from_file_location("_prop_ledger_2761", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# A realistic no-ledger-line handover body — the exact shape of the 2026-08-10→16 week's
# handovers (the word "ledger" appears in prose, colon-free, and must NOT satisfy the gate).
SILENT_HANDOVER = (
    "# HANDOVER 2026-08-14 — bug-bash queue\n\n"
    "Shipped the gate census (#2578) and the permanence nightly writer (#2572).\n"
    "The accountability ledger rolled into LIFETIME# as designed; the session ledger\n"
    "carries one incident row.\n\n"
    "**Build beat:** none — internal machinery only.\n"
    "**Docs:** none needed — no page invalidated.\n"
)


# ── the gate is wired into the /wrap skill ──────────────────────────────────────
def test_wrap_skill_has_proportionality_ledger_gate_step():
    wrap = WRAP.read_text(encoding="utf-8")
    assert "Proportionality-ledger gate" in wrap, "#2761: the (e12) step is missing from wrap.md"
    assert "check_proportionality_ledger.py" in wrap, "#2761: the gate script must actually be invoked from wrap.md, not just described"
    assert "**Ledger:**" in wrap, "#2761: wrap.md must name the mandatory handover line"


def test_wrap_skill_no_longer_wedges_2380_prose_inside_e10():
    """The old failure mode: the gate lived as an unlabelled paragraph inside the alarm
    step, where it could not be a checklist item. The prose form must be gone."""
    wrap = WRAP.read_text(encoding="utf-8")
    assert "Proportionality ledger gate (#2380):**" not in wrap, "#2761: the prose-only #2380 paragraph is still wedged inside step (e10)"


def test_guardrails_section_lists_the_ledger_gate():
    wrap = WRAP.read_text(encoding="utf-8")
    guardrails = wrap.split("## Guardrails")[1]
    assert "#2761" in guardrails
    assert "check_proportionality_ledger.py" in guardrails


# ── the labelled positive (acceptance box 3): silence is flagged ────────────────
def test_silent_omission_is_flagged():
    """A wrap input with NEITHER a docs/PROPORTIONALITY.md diff NOR a ledger line —
    the exact input every session 2026-08-10→16 produced — must fail."""
    chk = _load()
    ok, messages = chk.evaluate(SILENT_HANDOVER, ledger_diff=False)
    assert not ok, "#2761: the silent-omission wrap input passed — the gate still cannot fail"
    assert any("FAIL" in m for m in messages)
    assert any("Ledger" in m for m in messages)


def test_silent_omission_fails_even_when_git_is_unreachable():
    """Git-unreachable must not become a silent green (the #2938 dark-gate class):
    with no line and no verifiable diff, the gate still fails, loudly UNVERIFIED."""
    chk = _load()
    ok, messages = chk.evaluate(SILENT_HANDOVER, ledger_diff=None)
    assert not ok
    assert any("UNVERIFIED" in m for m in messages)


def test_prose_mentions_of_other_ledgers_do_not_satisfy_the_gate():
    """'session ledger', 'accountability ledger', 'calibration ledger' in prose are not
    declarations — only a `Ledger:` line (or `ledger: omitted — …`) counts."""
    chk = _load()
    assert chk.find_ledger_claims(SILENT_HANDOVER) == []


# ── the sanctioned explicit forms pass ──────────────────────────────────────────
def test_explicit_omitted_line_passes():
    chk = _load()
    text = SILENT_HANDOVER + "**Ledger:** omitted — rows held for the #2761 enforcement session.\n"
    ok, _ = chk.evaluate(text, ledger_diff=False)
    assert ok


def test_original_2380_inline_omitted_form_passes():
    """The #2380 prose sanctioned a lowercase inline `ledger: omitted — <reason>` line;
    the enforcement leg honors the original contract's spelling too."""
    chk = _load()
    text = SILENT_HANDOVER + "ledger: omitted — the row rides the next quarterly re-read.\n"
    ok, _ = chk.evaluate(text, ledger_diff=False)
    assert ok


def test_explicit_none_line_passes():
    chk = _load()
    text = SILENT_HANDOVER + "**Ledger:** none — no standing machinery shipped.\n"
    ok, _ = chk.evaluate(text, ledger_diff=False)
    assert ok


def test_all_dash_styles_recognized():
    chk = _load()
    for dash in ("-", "–", "—"):
        text = SILENT_HANDOVER + f"**Ledger:** omitted {dash} deferred with a reason.\n"
        ok, _ = chk.evaluate(text, ledger_diff=False)
        assert ok, f"dash style {dash!r} not recognized"


def test_diff_without_line_passes_with_a_nudge():
    """The acceptance's other leg: a real docs/PROPORTIONALITY.md diff in the session
    satisfies the gate even before the handover line is written."""
    chk = _load()
    ok, messages = chk.evaluate(SILENT_HANDOVER, ledger_diff=True)
    assert ok
    assert any("note" in m for m in messages), "the diff-only pass should still nudge for the named line"


# ── the loopholes are closed ────────────────────────────────────────────────────
def test_row_claim_without_a_ledger_diff_fails():
    """Writing `**Ledger:** X row added` while the ledger has no diff is the silent
    pass in a new costume — it must fail."""
    chk = _load()
    text = SILENT_HANDOVER + "**Ledger:** gate census row added (#2578).\n"
    ok, messages = chk.evaluate(text, ledger_diff=False)
    assert not ok
    assert any("no diff" in m for m in messages)
    # ... and the same claim WITH the diff is the happy path.
    ok, _ = chk.evaluate(text, ledger_diff=True)
    assert ok


def test_bare_omitted_without_reason_fails():
    """`omitted` with no `— <reason>` is an alibi, not a record."""
    chk = _load()
    for bad in ("**Ledger:** omitted\n", "**Ledger:** none\n", "**Ledger:**\n"):
        ok, messages = chk.evaluate(SILENT_HANDOVER + bad, ledger_diff=False)
        assert not ok, f"reason-free form passed: {bad!r}"


# ── classifier is non-vacuous (#1189 house style) ───────────────────────────────
def test_classifier_distinguishes_all_four_kinds():
    chk = _load()
    assert chk.classify("omitted — held for next session") == "omitted"
    assert chk.classify("none — no standing machinery shipped") == "none"
    assert chk.classify("permanence archive row added (#2572)") == "row"
    assert chk.classify("omitted") == "malformed"
    assert chk.classify("") == "malformed"


# ── the CLI is a real gate (exit codes, both directions) ────────────────────────
def test_cli_exit_codes_on_fixtures(tmp_path):
    bad = tmp_path / "silent.md"
    bad.write_text(SILENT_HANDOVER, encoding="utf-8")
    r = subprocess.run([sys.executable, str(SCRIPT), str(bad), "--diff", "no"], capture_output=True, text=True)
    assert r.returncode == 1, f"silent wrap input must exit 1, got {r.returncode}: {r.stdout}{r.stderr}"
    assert "FAIL" in r.stdout

    good = tmp_path / "explicit.md"
    good.write_text(SILENT_HANDOVER + "**Ledger:** none — no standing machinery shipped.\n", encoding="utf-8")
    r = subprocess.run([sys.executable, str(SCRIPT), str(good), "--diff", "no"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
