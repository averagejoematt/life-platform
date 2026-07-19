"""tests/test_qa_audit.py — #1450: the /qa audit coverage-map recompute.

The audit turns the three-agent archaeology dig (site/ vs manifest vs sweeps vs
alarms) into a deterministic ~seconds script. These tests pin its contract:

  1. It exists, imports cleanly offline (no AWS/Playwright deps at import), and
     builds a full audit dict over the real repo.
  2. The coverage map is DERIVED (manifest + repo files), never hand-listed —
     totals must agree with qa_manifest's own facets.
  3. Uncovered surface + silent-skip states are enumerated explicitly (#1450 AC:
     "output enumerates uncovered surface and silent-skip states explicitly").
  4. Drift detection is real: consumer files that stop deriving from the manifest,
     unregistered/ghost pages, and API endpoints declared in the manifest but
     status-checked nowhere are all reported; hard drift exits non-zero.

Proven RED pre-fix (scripts/qa_audit.py did not exist — collection ImportError).
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
for p in (os.path.join(_REPO, "scripts"), _HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import qa_audit  # noqa: E402
import qa_manifest  # noqa: E402


def test_build_audit_runs_offline_over_the_real_repo():
    audit = qa_audit.build_audit()
    for key in ("pages", "registry", "sweeps", "uncovered", "silent_skips", "consumers", "alarms", "workflows", "drift"):
        assert key in audit, f"audit missing section {key!r}"


def test_registry_section_matches_manifest_truth():
    audit = qa_audit.build_audit()
    reg = audit["registry"]
    assert reg["pages_total"] == len(qa_manifest.MANIFEST)
    # healthy repo: the completeness gate holds (a red here is REAL drift to fix)
    assert reg["unregistered"] == [], f"pages under site/ not in the manifest: {reg['unregistered']}"
    assert reg["ghosts"] == [], f"manifest entries with no file under site/: {reg['ghosts']}"
    assert reg["exempt"], "the EXEMPT ledger (with reasons) must surface in the audit"


def test_sweep_coverage_derives_from_manifest_facets():
    audit = qa_audit.build_audit()
    sw = audit["sweeps"]
    assert sw["smoke"]["pages"] == len(qa_manifest.smoke_rows())
    assert sw["visual"]["pages"] == sum(1 for p in qa_manifest.MANIFEST if p.get("visual"))
    assert sw["leak_scan"]["pages"] == len(qa_manifest.leak_scan_paths())
    assert sw["structural"]["pages"] == len(qa_manifest.structural_rows())
    assert sw["static_core"]["pages"] == len(qa_manifest.static_core_paths())
    # the tiered AI + WebKit buckets are subsets of the visual sweep
    assert sw["ai_vision_deploy"]["pages"] <= sw["visual"]["pages"]
    assert sw["webkit_weekly"]["pages"] <= len(qa_manifest.visual_pages())


def test_uncovered_surface_enumerated_explicitly():
    audit = qa_audit.build_audit()
    unc = audit["uncovered"]
    expected_no_visual = sorted(p["path"] for p in qa_manifest.MANIFEST if not p.get("visual") and not p.get("visual_variants"))
    assert unc["no_visual_def"] == expected_no_visual
    # endpoints the manifest declares but no smoke status-check covers — a list,
    # never a bare count (the AC says enumerate)
    assert isinstance(unc["api_deps_unchecked"], list)
    declared = {d for p in qa_manifest.MANIFEST for d in (p.get("api_deps") or []) if d.startswith("/api/")}
    assert set(unc["api_deps_unchecked"]) <= declared


def test_silent_skips_enumerated():
    audit = qa_audit.build_audit()
    kinds = {s["kind"] for s in audit["silent_skips"]}
    for expected in ("ai_vision_weekly_only", "leak_scan_excluded", "exempt_by_policy", "budget_pause", "qa_level_dial"):
        assert expected in kinds, f"silent-skip class {expected!r} not enumerated (#1450 AC)"
    for s in audit["silent_skips"]:
        assert s.get("detail"), f"silent-skip {s['kind']} carries no detail — must be explicit, not a label"


def test_consumer_drift_clean_on_healthy_repo_and_detects_a_broken_consumer(tmp_path):
    assert qa_audit.consumer_drift() == []
    rogue = tmp_path / "rogue_sweep.py"
    rogue.write_text("PAGES = ['/cockpit/']\n")
    drift = qa_audit.consumer_drift({str(rogue): "qa_manifest"})
    assert drift and str(rogue) in drift[0], "a consumer that stopped deriving from the manifest must be reported"


def test_alarm_coverage_finds_the_qa_smoke_alarms():
    audit = qa_audit.build_audit()
    names = {a["name"] for a in audit["alarms"]["qa_alarms"]}
    assert any("qa-smoke" in n for n in names), "the #1445 qa-smoke alarms not found — alarm-coverage scan broken or alarms gone"


def test_workflow_inventory_covers_gating_and_advisory_copies():
    audit = qa_audit.build_audit()
    by_file = {w["file"]: w for w in audit["workflows"]}
    assert "visual-qa.yml" in by_file and by_file["visual-qa.yml"]["gating"] is False
    assert "webkit-mobile-qa.yml" in by_file and by_file["webkit-mobile-qa.yml"]["gating"] is False
    assert "ci-cd.yml" in by_file and by_file["ci-cd.yml"]["gating"] is True
    for w in audit["workflows"]:
        assert "dial_sensitive" in w, "each workflow row must state whether the #1452 dial can scale it"


def test_hard_drift_gate_is_wired_to_exit_code():
    audit = qa_audit.build_audit()
    assert qa_audit.hard_drift(audit) == [], f"healthy repo reports hard drift: {qa_audit.hard_drift(audit)}"
    broken = dict(audit)
    broken["registry"] = dict(audit["registry"], unregistered=["/new-page/"])
    assert qa_audit.hard_drift(broken), "an unregistered page must count as hard drift (non-zero exit)"


def test_render_report_mentions_every_section():
    audit = qa_audit.build_audit()
    text = qa_audit.render(audit)
    for needle in ("COVERAGE MAP", "UNCOVERED", "SILENT-SKIP", "ALARM", "CONSUMER", "DRIFT"):
        assert needle in text, f"rendered report missing the {needle} section"
