"""tests/test_visual_qa_verdict_3352.py — #3352: the rollback scope check, on the
REAL shapes of the incidents it exists for.

Every fixture below is transcribed from a measured run, not invented:

  * ``P1_DATA_DOOR``   — 2026-08-31 P1 (INCIDENT_LOG): PR #3349's assets-first reorder put
    the Data-JSON sync ahead of the HTML sync, so all 20 `/data/*` pages were uploaded
    with ``--content-type application/json``. The sweep read them with no ``<title>``,
    no ``lang``, no viewport meta and ``js_bytes 0``. The rollback re-ran the same script
    and re-broke the door identically. MUST classify ``deploy-script`` / unreachable.
  * ``P3_ASSET_RACE`` — 2026-08-31 P3 (INCIDENT_LOG, run 33353122904): the HTML landed
    7s before the hashed JS it references, the edge cached the 404, and 43 pages read
    ``Refused to execute script … motion.15f49da6.js … MIME type ('text/html')``.
    ``hashed-asset`` / REACHABLE — the previous build's HTML and assets are mutually
    consistent, so a revert genuinely clears the dangling reference.
  * ``API_STALE``     — the 2026-08-27 Session G class: a defect in content served from
    DynamoDB. That rollback reverted a wanted published build beat and never touched the
    defect. ``api`` / unreachable.
  * ``A11Y_RED``      — a genuine `site/**` regression (the #1433 axe gate). ``site-shell``
    / REACHABLE — today's behaviour, unchanged.

Plus the NEGATIVE CONTROL, which is the load-bearing one: an issue string the classifier
has never seen classifies ``site-shell`` and the rollback still runs. This change may only
ever remove a rollback we can prove is futile; a silent widening of the decline set would
turn a blunt instrument into a dark one.
"""

import json
import os
import subprocess
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "tests"))

import visual_qa_verdict as V  # noqa: E402

# ── fixtures: the wire shapes ────────────────────────────────────────────────────


def _result(path, issues, *, status="FAIL", js_bytes=180_000, shell_content_type="text/html", **over):
    r = {
        "page": path.strip("/") or "Home",
        "path": path,
        "status": status,
        "issues": list(issues),
        "warnings": [],
        "screenshots": {},
        "perf": {"lcp_ms": 900, "cls": 0.01, "js_bytes": js_bytes},
        "shell_content_type": shell_content_type,
    }
    r.update(over)
    return r


def _p1_page(path, *, with_content_type=True):
    """The 2026-08-31 P1 fingerprint: an HTML shell served as application/json."""
    return _result(
        path,
        [
            "NEW serious a11y violation (axe: document-title): Documents must have <title> element to aid in navigation — 1 node(s) (#1433)",
            "NEW serious a11y violation (axe: html-has-lang): <html> element must have a lang attribute — 1 node(s) (#1433)",
            "Missing width=device-width viewport meta (#1004 class)",
        ],
        js_bytes=0,
        shell_content_type=("application/json" if with_content_type else None),
    )


P1_DATA_DOOR = [_p1_page(f"/data/{slug}/") for slug in ("sleep", "weight", "training", "nutrition", "cgm")]

P3_ASSET_RACE = [
    _result(
        "/cockpit/",
        [
            "1 JS error(s): Refused to execute script from 'https://averagejoematt.com/assets/js/motion.15f49da6.js' "
            "because its MIME type ('text/html') is not executable, and strict MIME type checking is enabled."
        ],
    )
]

API_STALE = [
    _result(
        "/story/",
        ['Stale text: "Day 6 of the experiment" — the day counter must track the live experiment day'],
    )
]

API_BROKEN_CALL = [_result("/cockpit/", ["1 broken API call(s): 502 /api/vitals"])]

READER_TRUTH = [
    _result(
        "/story/",
        ["Reader-truth (high) [phase]: the page says this is week 1 of the cut while the live phase record is week 3"],
    )
]

A11Y_RED = [
    _result(
        "/protocols/",
        [
            "NEW serious a11y violation (axe: color-contrast): Elements must meet minimum color contrast ratio "
            "thresholds — 4 node(s) (#1433)",
            "Horizontal overflow at 390px — content exceeds viewport by 37px",
        ],
    )
]

UNKNOWN_SHAPE = [_result("/coaching/", ["Some future check nobody has written yet said no (#9999)"])]


def _verdict(results, **kw):
    return V.classify_report({"results": list(results)}, **kw)


# ── the four named incident classes ──────────────────────────────────────────────


def test_the_2026_08_31_p1_json_door_is_deploy_script_and_unreachable():
    v = _verdict(P1_DATA_DOOR)
    assert v["reachable"] is False, "re-running the sync re-runs the defect — this is the incident"
    assert set(v["surfaces"]) == {V.DEPLOY_SCRIPT}
    assert v["surfaces"][V.DEPLOY_SCRIPT] == len(P1_DATA_DOOR)
    assert "application/json" in v["pages"][0]["reason"]


def test_the_p1_shape_is_caught_without_a_content_type_header_when_it_clusters():
    """A report from a sweep that never recorded the shell Content-Type (an older run,
    or a response the browser did not surface) must still classify: the no-title/no-lang/
    no-viewport + js_bytes 0 SHAPE across pages is a sync step's include set, not a page."""
    v = _verdict([_p1_page(f"/data/{s}/", with_content_type=False) for s in ("sleep", "weight", "training")])
    assert v["reachable"] is False
    assert v["surfaces"] == {V.DEPLOY_SCRIPT: 3}
    assert "3 pages" in v["pages"][0]["reason"]


def test_one_page_with_the_shell_shape_is_not_a_deploy_verdict():
    """The fail-safe half of the cluster rule: one page missing a title is a page bug and
    the rollback still runs. Only the CONTENT-TYPE evidence promotes a single page."""
    v = _verdict([_p1_page("/data/sleep/", with_content_type=False)])
    assert v["reachable"] is True
    assert v["surfaces"] == {V.SITE_SHELL: 1}


def test_the_2026_08_31_p3_asset_race_is_hashed_asset_and_reachable():
    v = _verdict(P3_ASSET_RACE)
    assert v["surfaces"] == {V.HASHED_ASSET: 1}
    assert v["reachable"] is True, "the prior build's HTML and its hashed assets are mutually consistent"


def test_a_stale_data_bound_red_is_api_and_unreachable():
    """The 2026-08-27 Session G case: the rollback reverted a wanted build beat over a
    DynamoDB-sourced defect it could not fix, and reported success."""
    v = _verdict(API_STALE)
    assert v["surfaces"] == {V.API: 1}
    assert v["reachable"] is False


def test_a_broken_api_call_and_a_reader_truth_finding_are_both_api():
    assert _verdict(API_BROKEN_CALL)["surfaces"] == {V.API: 1}
    assert _verdict(READER_TRUTH)["surfaces"] == {V.API: 1}
    assert _verdict(READER_TRUTH)["reachable"] is False


def test_a_genuine_a11y_regression_still_rolls_back():
    v = _verdict(A11Y_RED)
    assert v["surfaces"] == {V.SITE_SHELL: 1}
    assert v["reachable"] is True
    assert "color-contrast" in v["pages"][0]["reason"]


# ── the negative control ─────────────────────────────────────────────────────────


def test_an_unknown_issue_string_classifies_site_shell_and_still_rolls_back():
    """THE control. An unrecognised failure must not silently join the decline set —
    the only sanctioned direction for this change is removing a rollback we can PROVE is
    futile. Unknown means "behave exactly as we did before #3352"."""
    v = _verdict(UNKNOWN_SHAPE)
    assert v["surfaces"] == {V.SITE_SHELL: 1}
    assert v["reachable"] is True


def test_a_report_with_no_failures_or_no_report_at_all_is_reachable():
    assert _verdict([])["reachable"] is True
    assert V.classify_report({})["reachable"] is True
    assert V.classify_report({"results": [_result("/", [], status="PASS")]})["surfaces"] == {}


# ── mixed pages: precedence points at the LEAST reachable surface ────────────────


def test_a_page_failing_for_both_reasons_declines_rather_than_half_reverting():
    mixed = [
        _result(
            "/cockpit/",
            [
                "NEW serious a11y violation (axe: color-contrast): contrast — 2 node(s) (#1433)",
                "1 broken API call(s): 503 /api/vitals",
            ],
        )
    ]
    v = _verdict(mixed)
    assert v["pages"][0]["surface"] == V.API, "a site/** revert cannot make this page pass"
    assert v["pages"][0]["surfaces"] == [V.API, V.SITE_SHELL], "the reason must still name the site-shell half"
    assert v["reachable"] is False


def test_one_unreachable_page_declines_the_whole_rollback():
    v = _verdict(list(A11Y_RED) + list(API_STALE))
    assert v["surfaces"] == {V.SITE_SHELL: 1, V.API: 1}
    assert v["reachable"] is False, "a partial revert of a mixed failure is the worst of both"


def test_an_accuracy_audit_red_is_an_api_surface():
    v = _verdict([], accuracy_audit_failed=True)
    assert v["surfaces"] == {V.API: 1}
    assert v["reachable"] is False
    assert _verdict([], accuracy_audit_failed=False)["reachable"] is True


# ── the injected live-proof results go through the SAME rules ────────────────────


def test_injected_results_classify_to_the_surface_they_claim():
    """No bypass: the live proof exercises the production rule path. If these ever stop
    agreeing, the dispatch would prove a decline the classifier would not make."""
    for surface in (V.API, V.DEPLOY_SCRIPT):
        r = V.injected_result(surface)
        assert r["status"] == "FAIL" and r["injected"] is True
        assert "[INJECTED" in r["issues"][0], "an injected failure must be labelled wherever it is read"
        v = _verdict([r])
        assert v["surfaces"] == {surface: 1}, f"{surface} injection classified as {v['surfaces']}"
        assert v["reachable"] is False
        assert v["pages"][0]["injected"] is True


def test_injection_is_a_closed_choice_set():
    assert V.injected_result("none") is None
    assert V.injected_result("") is None
    assert V.injected_result("site-shell") is None, "injecting a REACHABLE surface would prove nothing"
    assert V.injection_choices() == ["none", V.API, V.DEPLOY_SCRIPT]


# ── the CLI contract the workflow depends on ─────────────────────────────────────


def test_cli_writes_verdict_json_and_github_outputs(tmp_path):
    report = tmp_path / "report.json"
    report.write_text(json.dumps({"results": P1_DATA_DOOR}), encoding="utf-8")
    out = tmp_path / "verdict.json"
    gh_out = tmp_path / "gh_output"
    gh_out.write_text("", encoding="utf-8")

    env = dict(os.environ, GITHUB_OUTPUT=str(gh_out))
    proc = subprocess.run(
        [
            sys.executable,
            os.path.join(_REPO, "tests", "visual_qa_verdict.py"),
            "--report",
            str(report),
            "--out",
            str(out),
            "--github-output",
        ],
        capture_output=True,
        text=True,
        env=env,
    )
    assert proc.returncode == 0, f"the classifier is an instrument, not a gate: {proc.stderr}"
    verdict = json.loads(out.read_text(encoding="utf-8"))
    assert verdict["reachable"] is False
    assert verdict["rule_version"] == V.RULE_VERSION
    assert set(verdict) >= {"reachable", "surfaces", "pages", "rule_version"}

    outputs = dict(line.split("=", 1) for line in gh_out.read_text(encoding="utf-8").strip().splitlines())
    assert outputs["site_reachable"] == "false"
    assert outputs["surfaces"] == f"{V.DEPLOY_SCRIPT}:{len(P1_DATA_DOOR)}"
    assert "NOT site/**-reachable" in outputs["summary"]
    assert "\n" not in outputs["summary"], "a multi-line GITHUB_OUTPUT value silently truncates without a heredoc"


def test_cli_on_a_missing_report_is_reachable_and_says_why(tmp_path):
    out = tmp_path / "verdict.json"
    rc = V.main(["--report", str(tmp_path / "nope.json"), "--out", str(out)])
    assert rc == 0
    verdict = json.loads(out.read_text(encoding="utf-8"))
    assert verdict["reachable"] is True, "a gate that died before writing a report gets today's behaviour"
    assert "not found" in verdict["note"]
