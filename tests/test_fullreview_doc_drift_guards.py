"""Regression guards for the /fullreview 2026-07-16 doc-drift cluster.

Each test pins a specific stale claim the review found and fixed, so the exact
drift can't silently reappear. Every assertion FAILS on the pre-fix tree (proven
by stashing the fixes and re-running) — the non-vacuity bar from PR #1189.

Covered issues: #1258 (deploy quickstart args), #1245 (panelcast viewer path),
#1241 (mypy ENFORCED not advisory), #1253 (remediation Mon/Wed/Fri not daily),
#1256 (raw_layout filename facets), #1238 (ADR-103 ledger rows).
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


# ── #1258: the quickstart deploy commands require <source-file> ────────────────
def test_deploy_quickstart_commands_include_source_file():
    txt = _read("CLAUDE.md")
    # the bare one-arg forms (which exit 1) must not appear as documented commands
    assert "deploy/deploy_lambda.sh <function-name>\n" not in txt, "CLAUDE.md deploy_lambda.sh command omits <source-file> (#1258)"
    assert "deploy/deploy_and_verify.sh <function-name>\n" not in txt, "CLAUDE.md deploy_and_verify.sh command omits <source-file> (#1258)"
    assert "deploy/deploy_lambda.sh <function-name> <source-file>" in txt


# ── #1245: the Story-door panelcast source is the viewer path, not the S3 key ──
def test_site_map_panelcast_uses_viewer_path():
    txt = _read("docs/SITE_MAP_AND_INTENT.md")
    assert "`/generated/panelcast/episodes.json`" not in txt, "SITE_MAP points the Story door at a 404 S3-key path (#1245)"
    assert "`/panelcast/episodes.json`" in txt


# ── #1241: mypy is ENFORCED (blocking) on the clean set, not 'advisory' ────────
def test_mypy_labeled_enforced_not_advisory():
    mypy_ini = _read("mypy.ini")
    reqs = _read("requirements-dev.txt")
    assert "Advisory mypy — non-blocking" not in mypy_ini, "mypy.ini calls the gate advisory/non-blocking while CI enforces it (#1241)"
    assert "ENFORCED" in mypy_ini or "Enforced" in mypy_ini
    # requirements-dev.txt must not open its type-checking note with a bare 'advisory'
    assert "# Type checking (advisory —" not in reqs, "requirements-dev.txt calls mypy advisory while CI enforces it (#1241)"


# ── #1253: the remediation agent runs Mon/Wed/Fri, not daily ───────────────────
def test_remediation_cadence_is_mon_wed_fri():
    for rel in ("CLAUDE.md", "docs/DECISIONS.md", "docs/RUNBOOK.md"):
        txt = _read(rel)
        assert "07:45 PT daily" not in txt, f"{rel} claims remediation runs daily; cron is Mon/Wed/Fri (#1253)"
        assert "every morning ~07:45 PT" not in txt, f"{rel} claims remediation runs every morning; cron is Mon/Wed/Fri (#1253)"
    # and the true cadence is stated somewhere in the canonical docs
    assert "Mon/Wed/Fri" in _read("CLAUDE.md")


# ── #1256: every date-tree raw_layout carries a filename facet ──────────────────
def test_raw_layout_date_tree_entries_have_filename_facet():
    import importlib.util

    spec = importlib.util.spec_from_file_location("_srcreg", ROOT / "lambdas" / "source_registry.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    missing = [k for k, v in m.raw_layouts().items() if v.get("scheme") == "date-tree" and "filename" not in v]
    assert not missing, f"date-tree raw_layout(s) missing the filename facet (#1256): {missing}"
    # CLAUDE.md must no longer assert the universal {DD}.json leaf form
    assert "{YYYY}/{MM}/{DD}.json`" not in _read("CLAUDE.md"), "CLAUDE.md still documents the universal {DD}.json filename (#1256)"


# ── #1238: ADR-103 ledger rows reflect the executed MCP prune + live Panel ─────
def test_adr103_ledger_rows_current():
    txt = _read("docs/DECISIONS.md")
    assert (
        "revival is backlog #374, not retirement" not in txt
    ), "ADR-103 still says the Panel pipeline is dark; it shipped (ADR-135) (#1238)"
    assert (
        "~105 unused tools are the retire-candidate INSIDE it (#398)" not in txt
    ), "ADR-103 still lists the MCP prune as pending; it executed (#395) (#1238)"
