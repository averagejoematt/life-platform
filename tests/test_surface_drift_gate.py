"""tests/test_surface_drift_gate.py — the #1454 PR-time surface-drift gate.

Unit-tests the gate's DECISION legs with fabricated inputs (no git, no AWS),
plus one end-to-end run over monkeypatched git plumbing — the four synthetic-
diff scenarios from the issue's proof criterion (new unregistered page / new
route / new cron / properly-registered control) are additionally proven against
real fixture branches in the PR body.

Pure-leg contract under test: every FAIL names the exact missing registration
and the file to add it to (the issue's acceptance criterion).
"""

import os
import sys
from collections import Counter

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
for _p in (os.path.join(_REPO, "scripts"), os.path.join(_REPO, "deploy")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import surface_drift_gate as g  # noqa: E402
import sync_doc_metadata  # noqa: E402

# ── exemptions ledger parsing ────────────────────────────────────────────────

_LEDGER_TEXT = """
# Surface-Drift Exemptions Ledger

prose lines are ignored
- 2026-07-18 | js | site/sw.js | service worker must live at site root
- 2026-07-18 | cron | cdk/stacks/email_stack.py | covered by the daily-brief freshness alarm
- not-a-date | js | site/x.js | malformed, must be ignored
- 2026-07-18 | banana | site/y.js | unknown kind, must be ignored
"""


def test_parse_exemptions_dated_entries_only():
    ex = g.parse_exemptions(_LEDGER_TEXT)
    assert [(e["kind"], e["token"]) for e in ex] == [("js", "site/sw.js"), ("cron", "cdk/stacks/email_stack.py")]
    assert ex[0]["date"] == "2026-07-18"
    assert "service worker" in ex[0]["reason"]


def test_exemption_matching_exact_and_prefix():
    ex = g.parse_exemptions(_LEDGER_TEXT)
    assert g.exemption_for(ex, "js", "site/sw.js") is not None
    assert g.exemption_for(ex, "js", "site/other.js") is None
    # a bare stack-file token prefixes any schedule-signature key in that file
    assert g.exemption_for(ex, "cron", "cdk/stacks/email_stack.py:events.Schedule.cron(hour='18')") is not None
    # kind must match — a js token never exempts a cron finding
    assert g.exemption_for(ex, "cron", "site/sw.js") is None


def test_real_ledger_parses_and_carries_the_sw_entry():
    with open(os.path.join(_REPO, "docs", "qa", "SURFACE_DRIFT_EXEMPTIONS.md"), encoding="utf-8") as f:
        ex = g.parse_exemptions(f.read())
    assert g.exemption_for(ex, "js", "site/sw.js") is not None


# ── PAGE leg ─────────────────────────────────────────────────────────────────


def test_page_path_normalization():
    assert g.page_path_for("site/index.html") == "/"
    assert g.page_path_for("site/data/vitals/index.html") == "/data/vitals/"
    assert g.page_path_for("site/404.html") == "/404.html"
    assert g.page_path_for("site/story/extra.html") == "/story/extra.html"
    assert g.page_path_for("site/legacy/old/index.html") is None  # legacy excluded by policy
    assert g.page_path_for("lambdas/web/site_api_lambda.py") is None


def test_page_leg_fails_added_unregistered_and_names_the_manifest():
    findings = g.page_leg({"/newpage/"}, unregistered={"/newpage/"}, ghosts=set(), exemptions=[])
    (f,) = [f for f in findings if f.severity == "fail"]
    assert f.leg == "PAGE" and f.surface == "/newpage/"
    assert "tests/qa_manifest.py" in f.fix and "_CURATED" in f.fix and "EXEMPT" in f.fix


def test_page_leg_registered_added_page_is_ok():
    findings = g.page_leg({"/newpage/"}, unregistered=set(), ghosts=set(), exemptions=[])
    assert [f.severity for f in findings] == ["ok"]


def test_page_leg_preexisting_drift_is_advisory_not_blocking():
    findings = g.page_leg(set(), unregistered={"/old-drift/"}, ghosts={"/ghost/"}, exemptions=[])
    assert {f.severity for f in findings} == {"advisory"}


def test_page_leg_ledger_exemption_clears_the_fail():
    ex = g.parse_exemptions("- 2026-07-18 | page | /newpage/ | landing order: registered in the follow-up PR #0000")
    findings = g.page_leg({"/newpage/"}, unregistered={"/newpage/"}, ghosts=set(), exemptions=ex)
    assert [f.severity for f in findings] == ["ok"]


# ── ROUTE leg ────────────────────────────────────────────────────────────────


def test_route_discoverer_union_on_synthetic_source():
    src = (
        "ROUTES = {'/api/a': h_a, '/api/b': None}\n"
        "_SIMPLE_ROUTES = {'/api/c': (('POST',), h_c)}\n"
        "def lambda_handler(event, context):\n"
        "    path = event.get('rawPath')\n"
        "    if path == '/api/d':\n"
        "        return 1\n"
        "    if path.startswith('/api/coach/'):\n"
        "        return 2\n"
    )
    assert sync_doc_metadata.discover_endpoint_paths(src) == {"/api/a", "/api/b", "/api/c", "/api/d", "/api/coach/"}
    # structural breakage → None, never a guess
    assert sync_doc_metadata.discover_endpoint_paths("def lambda_handler(e, c):\n    pass\n") is None
    assert sync_doc_metadata.discover_endpoint_paths("x = (") is None


def test_route_leg_advisory_while_schema_dir_absent():
    findings = g.route_leg({"/api/new_thing"}, schema_stems=None, exemptions=[])
    (f,) = findings
    assert f.severity == "advisory" and "#1436" in f.message and "BLOCKING automatically" in f.message


def test_route_leg_enforces_once_schema_dir_exists():
    findings = g.route_leg({"/api/new_thing"}, schema_stems={"other"}, exemptions=[])
    (f,) = findings
    assert f.severity == "fail"
    assert "tests/api_schemas/api_new_thing.json" in f.fix  # exact file to add


def test_route_leg_accepts_either_stem_spelling():
    assert [f.severity for f in g.route_leg({"/api/new_thing"}, {"api_new_thing"}, [])] == ["ok"]
    assert [f.severity for f in g.route_leg({"/api/new_thing"}, {"new_thing"}, [])] == ["ok"]


def test_route_leg_ledger_exemption():
    ex = g.parse_exemptions("- 2026-07-18 | route | /api/new_thing | internal-only diagnostics route, no public schema")
    assert [f.severity for f in g.route_leg({"/api/new_thing"}, {"other"}, ex)] == ["ok"]


# ── CRON leg ─────────────────────────────────────────────────────────────────

_STACK_ONE_CRON = (
    "from aws_cdk import aws_events as events\n" "rule = events.Rule(self, 'R', schedule=events.Schedule.cron(hour='18', minute='0'))\n"
)
_STACK_TWO_CRONS = _STACK_ONE_CRON + "rule2 = events.Rule(self, 'R2', schedule=events.Schedule.rate(Duration.hours(8)))\n"


def test_schedule_signatures_counts_schedule_calls_only():
    sigs = g.schedule_signatures(_STACK_TWO_CRONS)
    assert sum(sigs.values()) == 2
    assert any("cron" in s for s in sigs) and any("rate" in s for s in sigs)
    # unrelated .cron()/.rate() attrs on non-Schedule owners don't count
    assert sum(g.schedule_signatures("x = job.cron('* * * * *')\n").values()) == 0
    assert g.schedule_signatures("x = (") == Counter()


def test_new_schedule_detection_is_net_count_based():
    head, base = g.schedule_signatures(_STACK_TWO_CRONS), g.schedule_signatures(_STACK_ONE_CRON)
    assert sum(head.values()) > sum(base.values())
    assert list((head - base).elements()) == ["events.Schedule.rate(Duration.hours(8))"]
    # an EDITED cadence (same count) does not trigger the leg
    edited = g.schedule_signatures(_STACK_ONE_CRON.replace("hour='18'", "hour='17'"))
    assert sum(edited.values()) == sum(base.values())


def test_cron_leg_fails_without_monitoring_and_names_the_ledger():
    findings = g.cron_leg({"cdk/stacks/foo_stack.py": ["events.Schedule.cron(hour='3')"]}, monitoring_changed=False, exemptions=[])
    (f,) = findings
    assert f.severity == "fail" and f.leg == "CRON"
    assert "cdk/stacks/foo_stack.py" in f.surface
    assert "docs/qa/SURFACE_DRIFT_EXEMPTIONS.md" in f.fix and "monitoring_stack" in f.fix


def test_cron_leg_passes_with_monitoring_change_in_same_diff():
    findings = g.cron_leg({"cdk/stacks/foo_stack.py": ["sig"]}, monitoring_changed=True, exemptions=[])
    assert [f.severity for f in findings] == ["ok"]


def test_cron_leg_ledger_exemption_by_file_prefix():
    ex = g.parse_exemptions("- 2026-07-18 | cron | cdk/stacks/foo_stack.py | heartbeat lands with the G4 ledger story")
    findings = g.cron_leg({"cdk/stacks/foo_stack.py": ["sig"]}, monitoring_changed=False, exemptions=ex)
    assert [f.severity for f in findings] == ["ok"]


# ── JS leg ───────────────────────────────────────────────────────────────────


def test_import_gate_scan_marker_true_on_the_real_script():
    with open(os.path.join(_REPO, "scripts", "import_site_js_graph.mjs"), encoding="utf-8") as f:
        assert g.import_gate_scans_directory(f.read())
    assert not g.import_gate_scans_directory("// a rewritten gate with a hand-maintained file list")


def test_js_leg_scanned_dir_is_covered_by_construction():
    findings = g.js_leg({"site/assets/js/new_module.js"}, scan_intact=True, exemptions=[])
    assert [f.severity for f in findings] == ["ok"]


def test_js_leg_fails_outside_scanned_dir_naming_the_move_and_ledger():
    findings = g.js_leg({"site/other/rogue.js", "site/assets/js/sub/nested.js"}, scan_intact=True, exemptions=[])
    fails = {f.surface for f in findings if f.severity == "fail"}
    assert fails == {"site/other/rogue.js", "site/assets/js/sub/nested.js"}  # scan is non-recursive
    for f in findings:
        assert "site/assets/js" in f.fix and "SURFACE_DRIFT_EXEMPTIONS.md" in f.fix


def test_js_leg_fails_when_the_import_gate_stops_scanning():
    findings = g.js_leg(set(), scan_intact=False, exemptions=[])
    (f,) = findings
    assert f.severity == "fail" and f.surface == "scripts/import_site_js_graph.mjs"


def test_js_leg_ledger_exemption():
    ex = g.parse_exemptions("- 2026-07-18 | js | site/sw.js | service worker must live at site root")
    findings = g.js_leg({"site/sw.js"}, scan_intact=True, exemptions=ex)
    assert [f.severity for f in findings] == ["ok"]


# ── end-to-end over monkeypatched git plumbing (fabricated diff) ─────────────


class _FakeQaManifest:
    @staticmethod
    def self_check():
        return {"/newpage/"}, set()  # the added page is unregistered; no ghosts


def _fake_repo(monkeypatch, changed, base_files, head_files, qa_manifest=_FakeQaManifest, ledger=""):
    monkeypatch.setattr(g, "merge_base", lambda repo, base: "f" * 40)
    monkeypatch.setattr(g, "changed_files", lambda repo, mb: changed)
    monkeypatch.setattr(g, "read_at", lambda repo, rev, path: base_files.get(path))
    monkeypatch.setattr(g, "read_worktree", lambda repo, path: {g.LEDGER: ledger, **head_files}.get(path))
    monkeypatch.setattr(g, "_load_qa_manifest", lambda repo: qa_manifest)
    monkeypatch.setattr(g, "_load_sync_doc_metadata", lambda repo: sync_doc_metadata)


_IMPORT_GATE_SRC = 'const files = fs.readdirSync(JS_DIR); // path.join(REPO_ROOT, "site", "assets", "js")'


def test_run_gate_end_to_end_blocks_unregistered_page_route_and_cron(monkeypatch):
    base_api = "ROUTES = {'/api/a': 1}\ndef lambda_handler(e, c):\n    path = e['rawPath']\n"
    head_api = "ROUTES = {'/api/a': 1, '/api/brand_new': 2}\ndef lambda_handler(e, c):\n    path = e['rawPath']\n"
    _fake_repo(
        monkeypatch,
        changed=[
            ("A", "site/newpage/index.html"),
            ("M", g.SITE_API),
            ("M", "cdk/stacks/foo_stack.py"),
        ],
        base_files={g.SITE_API: base_api, "cdk/stacks/foo_stack.py": _STACK_ONE_CRON},
        head_files={
            g.SITE_API: head_api,
            "cdk/stacks/foo_stack.py": _STACK_TWO_CRONS,
            g.IMPORT_GATE: _IMPORT_GATE_SRC,
        },
    )
    monkeypatch.setattr(g, "_schema_stems", lambda repo: None)  # #1436 not landed
    findings, changed, mb = g.run_gate("/fake", "origin/main")
    by = {(f.leg, f.severity) for f in findings}
    assert ("PAGE", "fail") in by  # unregistered page blocks
    assert ("ROUTE", "advisory") in by  # degrades gracefully pre-#1436
    assert ("CRON", "fail") in by  # new schedule, no monitoring change
    assert ("JS", "fail") not in by
    assert g.main.__module__  # sanity
    report = g.format_report(findings, "origin/main", mb, len(changed))
    assert "RESULT: FAIL" in report and "fix →" in report


def test_run_gate_end_to_end_control_passes_clean(monkeypatch):
    class _CleanManifest:
        @staticmethod
        def self_check():
            return set(), set()

    _fake_repo(
        monkeypatch,
        changed=[
            ("A", "site/newpage/index.html"),  # registered (self_check clean)
            ("M", "cdk/stacks/foo_stack.py"),  # new cron + alarm in the same diff
            ("A", "site/assets/js/newmod.js"),  # covered by construction
        ],
        base_files={"cdk/stacks/foo_stack.py": _STACK_ONE_CRON},
        head_files={
            "cdk/stacks/foo_stack.py": _STACK_TWO_CRONS + "alarm = metric.create_alarm(self, 'A', threshold=1)\n",
            g.IMPORT_GATE: _IMPORT_GATE_SRC,
        },
        qa_manifest=_CleanManifest,
    )
    findings, changed, mb = g.run_gate("/fake", "origin/main")
    assert all(f.severity == "ok" for f in findings), [(f.leg, f.severity, f.surface) for f in findings]
    report = g.format_report(findings, "origin/main", mb, len(changed))
    assert "RESULT: PASS" in report


def test_run_gate_route_enforcing_once_schema_dir_exists(monkeypatch):
    base_api = "ROUTES = {'/api/a': 1}\ndef lambda_handler(e, c):\n    path = e['rawPath']\n"
    head_api = "ROUTES = {'/api/a': 1, '/api/brand_new': 2}\ndef lambda_handler(e, c):\n    path = e['rawPath']\n"
    _fake_repo(
        monkeypatch,
        changed=[("M", g.SITE_API)],
        base_files={g.SITE_API: base_api},
        head_files={g.SITE_API: head_api, g.IMPORT_GATE: _IMPORT_GATE_SRC},
    )
    monkeypatch.setattr(g, "_schema_stems", lambda repo: {"unrelated"})
    findings, _, _ = g.run_gate("/fake", "origin/main")
    route_fails = [f for f in findings if f.leg == "ROUTE" and f.severity == "fail"]
    assert len(route_fails) == 1 and route_fails[0].surface == "/api/brand_new"
    assert "tests/api_schemas/api_brand_new.json" in route_fails[0].fix
