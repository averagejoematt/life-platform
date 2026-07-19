"""tests/test_residual_queue_gate_1340.py — the /wrap residual-queue gate (#1340).

Replays the SDLC-review finding: `handovers/HANDOVER_LATEST.md`'s residual/next-picks
section is a sanctioned place to park real follow-up work, but nothing enforced that a
parked item ever became a filed issue — a live defect ("live chronicle item ... a tiny
follow-up if desired") sat with no `#N` and no tag, and a separate un-filed OG-card defect
got independently re-derived (and re-paid-for) by a later review (#1260). The fix: every
residual bullet cites an issue or is explicitly tagged `not-work — <reason>`.

Every test here fails on the pre-#1340 tree (missing gate wiring / an ungated bullet in the
live handover / a vacuous checker).
"""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WRAP = ROOT / ".claude" / "commands" / "wrap.md"
HANDOVER_LATEST = ROOT / "handovers" / "HANDOVER_LATEST.md"


def _load(script):
    spec = importlib.util.spec_from_file_location("_residualq_1340", ROOT / script)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# ── the gate is wired into the /wrap skill ──────────────────────────────────────
def test_wrap_skill_has_residual_queue_gate():
    wrap = WRAP.read_text(encoding="utf-8")
    assert "Residual-queue gate" in wrap, "#1340: the /wrap residual-queue gate step is missing"
    assert "not-work" in wrap
    assert "check_residual_queue.py" in wrap, "#1340: the gate script must actually be invoked from wrap.md, not just described"


def test_guardrails_section_lists_the_residual_queue_gate():
    wrap = WRAP.read_text(encoding="utf-8")
    guardrails = wrap.split("## Guardrails")[1]
    assert "#1340" in guardrails
    assert "not-work" in guardrails


# ── the checker itself is non-vacuous (#1189 house style) ───────────────────────
def test_residual_gate_is_not_vacuous(tmp_path):
    chk = _load("scripts/check_residual_queue.py")

    bad = tmp_path / "bad.md"
    bad.write_text(
        "## Residual / next picks\n"
        "- **a live defect with no citation and no tag at all** — should be flagged.\n"
        "- #123 a properly-cited item — should pass.\n"
        "## Next section\n"
        "- #999 outside the section, irrelevant\n"
    )
    section = chk._extract_section(bad.read_text())
    hits = chk.ungated_bullets(section)
    assert len(hits) == 1, f"residual-queue scan is VACUOUS or over-flags — got {len(hits)} hits, expected 1"
    assert "no citation and no tag" in hits[0]

    good = tmp_path / "good.md"
    good.write_text(
        "## Residual / next picks\n"
        "- #456 a filed follow-up.\n"
        "- a standing ops reminder — not-work — routine verification, not a backlog item.\n"
    )
    assert chk.ungated_bullets(chk._extract_section(good.read_text())) == []


def test_residual_gate_recognizes_various_not_work_dash_styles():
    chk = _load("scripts/check_residual_queue.py")
    for dash in ("-", "–", "—"):
        text = f"## Residual / next picks\n- a decision pending Matthew — not-work {dash} awaiting a call.\n"
        assert chk.ungated_bullets(chk._extract_section(text)) == [], f"dash style {dash!r} not recognized"


# ── the one-time reconciliation actually landed on the live handover ────────────
def test_handover_latest_residuals_are_gated():
    chk = _load("scripts/check_residual_queue.py")
    text = HANDOVER_LATEST.read_text(encoding="utf-8")
    section = chk._extract_section(text)
    assert section.strip(), "#1340: expected a 'Residual / next picks' section in the live HANDOVER_LATEST.md"
    hits = chk.ungated_bullets(section)
    assert hits == [], "#1340: HANDOVER_LATEST.md still has ungated residual bullets:\n" + "\n".join(hits)


def test_check_residual_queue_cli_clean_on_live_handover():
    import subprocess
    import sys

    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "check_residual_queue.py")], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
