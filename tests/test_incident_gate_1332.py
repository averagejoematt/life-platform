"""tests/test_incident_gate_1332.py — the /wrap incident gate (#1332).

Replays the SDLC-review finding: ≥6 site auto-rollback firings plus several other
incident-class events (a ~26h-unnoticed ci-cd red, the artifact-quota rollback class, the
#1297 collection-red) happened but lived only in memory topic files or a handover clause —
`docs/INCIDENT_LOG.md` looked like a clean month since 2026-07-03/07-10. The fix mirrors
the build-beat gate (#736): every wrap either logs a row for any incident-class event or
states `**Incidents:** none` explicitly.

Every test here fails on the pre-#1332 tree (missing gate text / missing backfilled rows).
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WRAP = ROOT / ".claude" / "commands" / "wrap.md"
LOG = ROOT / "docs" / "INCIDENT_LOG.md"


def _wrap_text() -> str:
    return WRAP.read_text(encoding="utf-8")


def _log_text() -> str:
    return LOG.read_text(encoding="utf-8")


# ── the gate is actually wired into the /wrap skill ─────────────────────────────
def test_wrap_skill_has_incident_gate():
    wrap = _wrap_text()
    assert "Incident gate" in wrap, "#1332: the /wrap incident gate step is missing"
    assert "docs/INCIDENT_LOG.md" in wrap
    assert "**Incidents:**" in wrap, "#1332: the handover incident-line marker is missing from wrap.md"
    assert "none" in wrap.split("Incident gate")[1][:2000].lower(), "#1332: the explicit-skip form ('none') must be documented"


def test_incident_gate_mirrors_build_beat_shape():
    """The gate must be framed as beat-or-explicit-skip, never silence — same shape as #736,
    not a softer 'nice to have'."""
    wrap = _wrap_text()
    section = wrap.split("### (e3) Incident gate")[1].split("### (e4)")[0]
    normalized = " ".join(section.lower().split())  # collapse line-wrap whitespace before matching
    assert "silent omission is not an outcome" in normalized or "never silence" in normalized


def test_guardrails_section_lists_the_incident_gate():
    wrap = _wrap_text()
    guardrails = wrap.split("## Guardrails")[1]
    assert "#1332" in guardrails
    assert "Incidents:" in guardrails


# ── the backfill actually landed (non-vacuous: specific known incidents present) ────────
def test_incident_log_backfilled_known_2026_07_events():
    """#1332's own body named 7 specific missing events (plus tonight's rollback) — assert
    each is now represented in the log by a durable, greppable marker (a PR/issue number or
    an unambiguous keyword), not just a vague new row."""
    log = _log_text()
    expectations = [
        ("2026-07-09 deploy-order 404", "vitals_depth"),
        ("2026-07-10 pre-start gates", "pre_start"),
        ("2026-07-11 mobile-overflow true positive", "#1008"),
        ("2026-07-12 cached-404 class #1158", "#1158"),
        ("~26h-unnoticed ci-cd red", "26h"),
        ("#1297 collection-red", "#1297"),
        ("2026-07-16/17 quota false positives", "quota"),
        ("tonight's genesis-eve deploy-order rollback", "character_calibration"),
    ]
    for label, needle in expectations:
        assert needle in log, f"#1332: backfill missing for {label} (expected '{needle}' in docs/INCIDENT_LOG.md)"


def test_incident_log_last_updated_bumped():
    log = _log_text()
    # ">= the backfill date", not "== the backfill date": later sessions legitimately
    # bump the line again (the 2026-07-20 wrap did), and an exact-date pin turns every
    # honest bump into a red — the golden-date trap.
    m = re.search(r"Last updated: (\d{4}-\d{2}-\d{2})", log)
    assert m, "#1332: no dated Last-updated line in docs/INCIDENT_LOG.md"
    assert m.group(1) >= "2026-07-19", "#1332: the Last-updated line was not bumped for the backfill"
    assert "#1332" in log.split("Last updated:")[1][:400]


def test_backfilled_rows_are_well_formed():
    """A hand-authored backfill row with a stray/missing pipe silently breaks the markdown
    table. Scoped to the #1332 backfill rows specifically (some pre-existing legacy rows
    from 2026-03 predate this gate and are a separate, pre-existing drift class — not
    re-litigated here)."""
    log = _log_text()
    lines = log.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("| Date | Severity |"))
    header_fields = lines[start].count("|")
    backfill_markers = ("vitals_depth", "pre_start", "#1008", "#1158", "26h", "#1297", "quota", "character_calibration")
    checked = 0
    for line in lines[start + 2 :]:
        if not line.startswith("|"):
            break
        if any(marker in line for marker in backfill_markers):
            assert line.count("|") == header_fields, f"malformed #1332 backfill row: {line[:80]}..."
            checked += 1
    assert checked >= 8, f"expected at least 8 of the #1332 backfill rows to be found by their markers, found {checked}"
