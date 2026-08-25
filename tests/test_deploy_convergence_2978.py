"""#2978 — the deploy-race class's owner, mutation-proved.

Four proofs the issue asks for, and the fourth is the one that keeps this honest:

  1. a fabricated race-window timeline (edge still on the prior build) classifies
     `raced` and the gate WAITS instead of sleeping a guessed duration;
  2. the 2026-08-25 20:43Z merge-train timeline — a REAL mixed state, correctly
     auto-rolled-back — still classifies `real` and still fails hard;
  3. a convergence signal that cannot be read yields `unverified` and a loud
     non-zero exit, never a silent pass (#2578);
  4. the taxonomy cannot excuse a check kind it does not cover, and an UNDECLARED
     window is a CLOSED window.

Every probe here runs against an injected `fetch` and an injected clock/sleeper —
no network, no wall clock. `reference_fixture_must_be_the_wire`: the fixtures are
the exact documents the live probes parse (`/version.json` as
sync_site_to_s3.sh stamps it, `/api/healthz` as site_api_lambda.py returns it,
`api_deploy_sequencing.json` as the #2831 registry writes it), so a change to
either end breaks a test rather than passing vacuously.
"""

import json
import os
import subprocess
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_REPO, "deploy"))

import deploy_convergence as dc  # noqa: E402

# The SHA the 08-25 merge train deployed (short form as version.json stamps it).
DEPLOYED_SHA = "e11ce47f0a1b2c3d4e5f60718293a4b5c6d7e8f9"
DEPLOYED_SHORT = "e11ce47"
PRIOR_SHORT = "fc1186a"


def _healthz(warm=True):
    """Exactly the payload lambdas/web/site_api_lambda.py's /api/healthz returns."""
    return json.dumps(
        {
            "status": "ok",
            "version": "v4.5.1",
            "checks": {"dynamodb": {"status": "ok", "latency_ms": 12}, "last_daily_refresh": "2026-08-25T11:30:00Z", "lambda_warm": warm},
            "response_ms": 41,
        }
    )


def _version(build):
    """Exactly the document sync_site_to_s3.sh writes (build + deployed, no-cache)."""
    return json.dumps({"build": build, "deployed": "2026-08-25T20:31:07Z"})


def _fetch_map(mapping):
    """An injected fetch: path -> (status, body) or a callable returning one."""

    def fetch(url, timeout=10):
        path = url.split("averagejoematt.com", 1)[-1] if "averagejoematt.com" in url else url
        entry = mapping.get(path, (404, "{}"))
        return entry() if callable(entry) else entry

    return fetch


BASE = "https://averagejoematt.com"


class _Clock:
    """Monotonic clock advanced only by the injected sleeper — no wall time."""

    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


# ── PROOF 1: a fabricated race window classifies `raced` and the gate waits ───


def test_stale_edge_is_a_race_window_and_the_gate_waits_for_the_signal():
    """The #1526 timeline: deploy finished, edge still serving the prior object.

    The old fix was `sleep 60` — a guess that lost the race at 05:40Z on
    2026-07-19. Here the gate polls the FINGERPRINT and stops the moment it
    flips, so it waits exactly as long as convergence actually took.
    """
    clock = _Clock()
    polls = {"n": 0}

    def version_json():
        polls["n"] += 1
        # The invalidation lands between the 2nd and 3rd poll.
        return (200, _version(DEPLOYED_SHORT if polls["n"] >= 3 else PRIOR_SHORT))

    fetch = _fetch_map({"/version.json": version_json, "/api/healthz": (200, _healthz(warm=True))})
    report = dc.await_convergence(BASE, DEPLOYED_SHA, fetch=fetch, sleeper=clock.sleep, clock=clock, routes=[])

    assert report["overall"] == dc.CONVERGED
    assert report["windows"]["site-edge-invalidation"]["polls"] == 3
    # It waited on the signal (2 poll intervals), not on a fixed 60s guess.
    assert clock.t == 2 * dc.RACE_WINDOWS["site-edge-invalidation"]["poll_s"]


def test_a_content_failure_while_the_edge_is_stale_is_raced_not_failed():
    """The verdict the class exists for: `raced — rerun after convergence`."""
    fetch = _fetch_map({"/version.json": (200, _version(PRIOR_SHORT)), "/api/healthz": (200, _healthz())})
    clock = _Clock()
    report = dc.await_convergence(BASE, DEPLOYED_SHA, fetch=fetch, sleeper=clock.sleep, clock=clock, routes=[])

    assert report["windows"]["site-edge-invalidation"]["state"] == dc.PENDING
    disposition, reason = dc.classify(dc.EDGE_CONTENT, report)
    assert disposition == dc.RACED
    assert "site-edge-invalidation" in reason
    # The budget is bounded — it did not spin forever.
    assert clock.t <= dc.RACE_WINDOWS["site-edge-invalidation"]["budget_s"]


def test_a_declared_pending_route_404_is_raced_and_converges_when_it_answers():
    """#2831's registry is the DECLARATION that opens the api-before-frontend window."""
    fetch = _fetch_map({"/version.json": (200, _version(DEPLOYED_SHORT)), "/api/healthz": (200, _healthz()), "/api/brand_new": (404, "{}")})
    clock = _Clock()
    report = dc.await_convergence(BASE, DEPLOYED_SHA, fetch=fetch, sleeper=clock.sleep, clock=clock, routes=["/api/brand_new"])
    assert dc.classify(dc.API_ROUTE, report)[0] == dc.RACED

    fetch_live = _fetch_map(
        {"/version.json": (200, _version(DEPLOYED_SHORT)), "/api/healthz": (200, _healthz()), "/api/brand_new": (200, "{}")}
    )
    clock2 = _Clock()
    report2 = dc.await_convergence(BASE, DEPLOYED_SHA, fetch=fetch_live, sleeper=clock2.sleep, clock=clock2, routes=["/api/brand_new"])
    assert report2["overall"] == dc.CONVERGED
    assert dc.classify(dc.API_ROUTE, report2)[0] == dc.REAL


def test_cold_container_is_a_race_window_for_latency_only():
    """#1911's shape: a first-hit timeout is raced; a broken page is not."""
    fetch = _fetch_map({"/version.json": (200, _version(DEPLOYED_SHORT)), "/api/healthz": (200, _healthz(warm=False))})
    clock = _Clock()
    report = dc.await_convergence(BASE, DEPLOYED_SHA, fetch=fetch, sleeper=clock.sleep, clock=clock, routes=[])
    assert dc.classify(dc.COLD_LATENCY, report)[0] == dc.RACED
    # A cold container does not excuse a content or semantic red.
    assert dc.classify(dc.EDGE_CONTENT, report)[0] == dc.REAL
    assert dc.classify(dc.SEMANTIC, report)[0] == dc.REAL


def test_the_cold_start_window_is_observed_once_and_never_stalls_the_gate():
    """The measured correction: `lambda_warm` is per-container, so it never globally closes.

    Live probe 2026-08-25 (build fc1186a): the first draft awaited this signal and
    burned 87.1s over 9 polls because a low-traffic site hands consecutive probes
    fresh containers. One observation is exactly enough — it lets a first-hit
    timeout classify `raced` — and the deploy waits zero seconds for it.
    """
    assert dc.RACE_WINDOWS["lambda-cold-start"]["blocking"] is False
    fetch = _fetch_map({"/version.json": (200, _version(DEPLOYED_SHORT)), "/api/healthz": (200, _healthz(warm=False))})
    clock = _Clock()
    report = dc.await_convergence(BASE, DEPLOYED_SHA, fetch=fetch, sleeper=clock.sleep, clock=clock, routes=[])
    assert report["windows"]["lambda-cold-start"]["polls"] == 1
    assert clock.t == 0, "a non-blocking window must cost the deploy no wall clock"
    # …and a perpetually-cold container must not turn the whole gate red.
    assert report["overall"] == dc.CONVERGED


def test_an_unreadable_non_blocking_signal_still_makes_its_own_kind_unverified():
    """Non-blocking is not un-gated: it just gates the CHECK, not the whole run."""
    fetch = _fetch_map({"/version.json": (200, _version(DEPLOYED_SHORT)), "/api/healthz": (None, "URLError: reset")})
    clock = _Clock()
    report = dc.await_convergence(BASE, DEPLOYED_SHA, fetch=fetch, sleeper=clock.sleep, clock=clock, routes=[])
    assert report["overall"] == dc.CONVERGED, "a non-blocking window may not stop the sweep from starting"
    assert dc.classify(dc.COLD_LATENCY, report)[0] == dc.UNVERIFIED
    assert dc.classify(dc.EDGE_CONTENT, report)[0] == dc.REAL


# ── PROOF 2: the 20:43Z REAL mixed state must still fail ─────────────────────


def _timeline_2043z():
    """docs/INCIDENT_LOG.md 2026-08-25, run 32784460571-era, 20:43Z.

    "1 novel truth high on 93 pages while the night's statics deployed ahead of
    the not-yet-deployed site-api." The site auto-deploy had COMPLETED and the
    edge was serving the merged build; the site-api half rode the end-of-train
    manual deploy. Nothing was declared in api_deploy_sequencing.json — the
    merge train did not register the ordering risk — so no window was open.
    """
    return _fetch_map(
        {
            "/version.json": (200, _version(DEPLOYED_SHORT)),  # statics DID deploy
            "/api/healthz": (200, _healthz(warm=True)),  # site-api serving, just the OLD code
        }
    )


@pytest.mark.parametrize("kind", [dc.SEMANTIC, dc.API_ROUTE, dc.EDGE_CONTENT, dc.COLD_LATENCY])
def test_the_2043z_mixed_state_still_fails_hard_for_every_check_kind(kind):
    """THE regression that must never be excused.

    That rollback was correct: the reader-facing surface really was mixed. Under
    this classifier it stays a hard failure for EVERY check kind, because the
    ordering risk was UNDECLARED — and an undeclared window is a closed one. A
    change that makes any of these read `raced` has re-opened the hole the
    convergence gate is supposed to close from the other side.
    """
    clock = _Clock()
    report = dc.await_convergence(BASE, DEPLOYED_SHA, fetch=_timeline_2043z(), sleeper=clock.sleep, clock=clock, routes=[])
    assert report["overall"] == dc.CONVERGED, report
    disposition, reason = dc.classify(kind, report)
    assert disposition == dc.REAL, f"20:43Z must stay a REAL failure for {kind}: {reason}"


def test_the_2043z_gate_exits_green_so_the_checks_themselves_render_the_verdict():
    """The gate must not *pass* the deploy — only stop blocking the checks.

    On the 20:43Z timeline every signal converged, so `await` exits 0 and the
    reader-truth gate runs and reds exactly as it did live. The convergence gate
    is a precondition on the checks, never a substitute for them.
    """
    clock = _Clock()
    report = dc.await_convergence(BASE, DEPLOYED_SHA, fetch=_timeline_2043z(), sleeper=clock.sleep, clock=clock, routes=[])
    assert report["overall"] == dc.CONVERGED
    assert report["windows"]["api-before-frontend"]["state"] == dc.CLOSED


# ── PROOF 3: an unreadable signal is UNVERIFIED, never a silent pass (#2578) ──


@pytest.mark.parametrize(
    "version_entry,why",
    [
        ((None, "URLError: timed out"), "transport failure"),
        ((503, ""), "edge 5xx"),
        ((200, "<html>not json</html>"), "unparseable body"),
        ((200, json.dumps({"deployed": "2026-08-25T20:31:07Z"})), "no build key"),
        ((200, json.dumps({"build": ""})), "empty build stamp"),
    ],
)
def test_unreadable_convergence_signal_is_unverified_not_a_pass(version_entry, why):
    fetch = _fetch_map({"/version.json": version_entry, "/api/healthz": (200, _healthz())})
    clock = _Clock()
    report = dc.await_convergence(BASE, DEPLOYED_SHA, fetch=fetch, sleeper=clock.sleep, clock=clock, routes=[])
    assert report["overall"] == dc.UNAVAILABLE, why
    disposition, reason = dc.classify(dc.EDGE_CONTENT, report)
    assert disposition == dc.UNVERIFIED, why
    assert "unreadable" in reason


def test_a_malformed_sequencing_registry_is_unavailable_not_nothing_declared(tmp_path):
    """The two facts a fail-soft read conflates, and only one excuses a red."""
    good = tmp_path / "ok.json"
    good.write_text(json.dumps({"pending_deploy_routes": [{"route": "/api/x"}]}), encoding="utf-8")
    assert dc.pending_deploy_routes(str(good)) == ["/api/x"]

    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert dc.pending_deploy_routes(str(bad)) is None
    assert dc.probe_pending_routes(BASE, None)[0] == dc.UNAVAILABLE
    assert dc.probe_pending_routes(BASE, [])[0] == dc.CLOSED


def test_the_live_registry_parses():
    """The wire, not a fixture: the committed #2831 registry must read cleanly."""
    assert dc.pending_deploy_routes() is not None, "deploy/api_deploy_sequencing.json no longer parses — the gate would go UNVERIFIED"


def _run_cli(monkeypatch, mapping):
    """Drive main()'s exit-code + annotation contract over an injected clock.

    The injection goes through `await_convergence` rather than the network layer
    on purpose: a no-op sleeper against a REAL monotonic clock spins for the full
    budget, which is how the first draft of this file hung for 300s.
    """
    real = dc.await_convergence

    def fake(base, expect_build, **_kw):
        clock = _Clock()
        return real(base, expect_build, fetch=_fetch_map(mapping), sleeper=clock.sleep, clock=clock, routes=[])

    monkeypatch.setattr(dc, "await_convergence", fake)
    return dc.main(["await", "--base", BASE, "--expect-build", DEPLOYED_SHA])


def test_cli_exit_code_pending(monkeypatch, capsys):
    rc = _run_cli(monkeypatch, {"/version.json": (200, _version(PRIOR_SHORT)), "/api/healthz": (200, _healthz())})
    assert rc == dc.EXIT_PENDING
    out = capsys.readouterr().out
    assert "::error::convergence NOT reached" in out
    assert json.loads([ln for ln in out.splitlines() if '"issue": "2978"' in ln][0])["disposition"] == dc.RACED


def test_cli_exit_code_unavailable(monkeypatch, capsys):
    rc = _run_cli(monkeypatch, {"/version.json": (500, ""), "/api/healthz": (200, _healthz())})
    assert rc == dc.EXIT_UNAVAILABLE
    out = capsys.readouterr().out
    assert "UNREADABLE" in out
    assert json.loads([ln for ln in out.splitlines() if '"issue": "2978"' in ln][0])["disposition"] == dc.UNVERIFIED


def test_cli_exit_code_converged_emits_nothing_and_blocks_nothing(monkeypatch, capsys):
    rc = _run_cli(monkeypatch, {"/version.json": (200, _version(DEPLOYED_SHORT)), "/api/healthz": (200, _healthz())})
    assert rc == dc.EXIT_CONVERGED
    assert "::error::" not in capsys.readouterr().out


# ── PROOF 4: the taxonomy's own invariants ───────────────────────────────────


def test_an_unknown_check_kind_cannot_be_excused():
    report = {"windows": {w: {"state": dc.CONVERGED, "detail": "", "polls": 1} for w in dc.RACE_WINDOWS}, "overall": dc.CONVERGED}
    assert dc.classify("something_new", report)[0] == dc.UNVERIFIED


def test_no_window_can_falsify_a_semantic_verdict():
    """#2959's shape may not hide inside #2978's excuse.

    No convergence signal makes a wrong published number right, so a
    reader-truth/AI-vision high must never classify as a race.
    """
    for spec in dc.RACE_WINDOWS.values():
        assert dc.SEMANTIC not in spec["falsifies"]


@pytest.mark.parametrize("wid", sorted(dc.RACE_WINDOWS))
def test_every_window_is_well_formed(wid):
    spec = dc.RACE_WINDOWS[wid]
    assert spec["pipeline"] and spec["opens_on"] and spec["converges_on"]
    assert spec["signal"], f"{wid}: a window with no signal is a sleep with extra steps"
    assert spec["falsifies"] and all(k in dc.CHECK_KINDS for k in spec["falsifies"])
    assert spec["evidence"], f"{wid}: a window with no incident evidence is speculation"
    assert isinstance(spec["blocking"], bool)
    if spec["blocking"]:
        assert 0 < spec["poll_s"] <= spec["budget_s"], f"{wid}: budget must admit at least one poll interval"
    else:
        assert spec["budget_s"] == 0, f"{wid}: an observed-only window must not claim a wait budget"


def test_at_least_one_window_actually_blocks():
    """The gate has to gate. A taxonomy where nothing is awaited is documentation."""
    assert any(spec["blocking"] for spec in dc.RACE_WINDOWS.values())


def test_sha_matching_is_prefix_safe_in_both_directions_and_rejects_stubs():
    assert dc._sha_matches(DEPLOYED_SHA, DEPLOYED_SHORT)
    assert dc._sha_matches(DEPLOYED_SHORT, DEPLOYED_SHA)
    assert not dc._sha_matches(DEPLOYED_SHA, PRIOR_SHORT)
    # A too-short or empty stamp must never satisfy the fingerprint.
    for stub in ("", "e1", "unknown"):
        assert not dc._sha_matches(DEPLOYED_SHA, stub), stub


# ── the metric: the rate becomes measurable, in the repo's EMF shape ─────────


def test_emf_record_is_a_valid_emf_blob_in_the_registered_namespace():
    rec = dc.emf_record(dc.RACED, dc.EDGE_CONTENT, "site-edge-invalidation", "edge on prior build", clock=lambda: 1756150000.0)
    entry = rec["_aws"]["CloudWatchMetrics"][0]
    assert entry["Namespace"] == dc.METRIC_NAMESPACE == "LifePlatform/QA"
    assert entry["Metrics"] == [{"Name": "DeployRaceRaced", "Unit": "Count"}]
    assert entry["Dimensions"] == [[]], "no dimensions — three flat series, never a fan-out (#2837)"
    assert rec["DeployRaceRaced"] == 1 and rec["issue"] == "2978"
    assert rec["_aws"]["Timestamp"] == 1756150000000


def test_every_disposition_has_its_own_series():
    assert set(dc.METRIC_BY_DISPOSITION) == {dc.RACED, dc.REAL, dc.UNVERIFIED}
    assert len(set(dc.METRIC_BY_DISPOSITION.values())) == 3


def test_the_namespace_is_registered_in_the_2837_ledger():
    sys.path.insert(0, os.path.join(_REPO, "deploy"))
    import emf_namespace_ledger as led

    row = led.LEDGER.get(dc.METRIC_NAMESPACE)
    assert row, f"{dc.METRIC_NAMESPACE} must carry a #2837 ledger row"
    assert row["series_budget"] >= len(dc.METRIC_BY_DISPOSITION) + 1, "budget must admit the three disposition series plus QAPausedByBudget"


def test_emit_prints_the_record_and_does_not_put_without_the_arm(monkeypatch, capsys):
    monkeypatch.delenv("DEPLOY_RACE_PUT_METRIC", raising=False)
    dc.emit(dc.REAL, dc.SEMANTIC, None, "reader-truth high")
    line = json.loads(capsys.readouterr().out.strip())
    assert line["disposition"] == "real" and line["DeployRaceReal"] == 1


# ── the wiring: the gate must actually be in the two post-deploy surfaces ────


def test_smoke_script_runs_the_convergence_gate_before_any_check():
    smoke = open(os.path.join(_REPO, "deploy", "smoke_test_site.sh"), encoding="utf-8").read()
    assert "deploy_convergence.py" in smoke, "smoke lost its #2978 convergence gate"
    assert "SMOKE_EXPECT_BUILD" in smoke
    gate_at = smoke.index("deploy_convergence.py")
    first_check = smoke.index("── v4 pages (HTTP status")
    assert gate_at < first_check, "the convergence gate must run BEFORE the first check, not after"


def test_visual_qa_runs_the_convergence_gate():
    vq = open(os.path.join(_REPO, "tests", "visual_qa.py"), encoding="utf-8").read()
    assert "VISUAL_QA_EXPECT_BUILD" in vq and "deploy_convergence" in vq


def test_site_deploy_workflow_supplies_the_expected_build_to_both_gates():
    wf = open(os.path.join(_REPO, ".github", "workflows", "site-deploy.yml"), encoding="utf-8").read()
    assert "SMOKE_EXPECT_BUILD" in wf, "the smoke job must be told which build it is judging"
    assert "VISUAL_QA_EXPECT_BUILD" in wf, "the visual-qa job must be told which build it is judging"


def test_the_taxonomy_renders_for_humans():
    table = subprocess.run(
        [sys.executable, os.path.join(_REPO, "deploy", "deploy_convergence.py"), "--table"], capture_output=True, text=True, timeout=60
    )
    assert table.returncode == 0, table.stderr
    for wid in dc.RACE_WINDOWS:
        assert wid in table.stdout
