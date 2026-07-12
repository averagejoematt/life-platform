"""tests/test_sync_doc_metadata_check.py — the doc-drift gate (#389) actually gates.

sync_doc_metadata.py used to only ever rewrite docs on --apply; nothing ran the
diff assertively, so a fixed literal (e.g. CLAUDE.md's "~85 Lambdas") re-drifted
the moment the underlying fact changed again and nobody happened to rerun
--apply. --check reuses the exact same rule-matching machinery (RULES +
process_doc) but exits non-zero instead of silently reporting, so CI catches
drift instead of a diligent human.

Two isolated unit tests exercise the core mechanism (process_doc / main()
exit-code branching) against a synthetic doc in tmp_path — never the real repo
files, so these can't corrupt anything a concurrent session is editing. One
integration test runs the real script against the real repo HEAD to confirm
the gate is actually clean (the state this PR is required to leave main in).
"""

import os
import subprocess
import sys

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "deploy"))

import sync_doc_metadata as sync  # noqa: E402


def _isolate(monkeypatch, tmp_path, doc_text, widget_count):
    """Point sync at a synthetic single-doc/single-rule world in tmp_path.

    Keeps the test from touching real repo docs or lambdas/web/site_api_common.py
    (both of which _sync_platform_stats / the real RULES would otherwise reach for).
    """
    doc = tmp_path / "FAKE_DOC.md"
    doc.write_text(doc_text, encoding="utf-8")
    monkeypatch.setattr(sync, "ROOT", tmp_path)
    monkeypatch.setattr(sync, "RULES", [("FAKE_DOC.md", r"\d+ Widgets", "{widget_count} Widgets")])
    monkeypatch.setattr(sync, "PLATFORM_FACTS", {**sync.PLATFORM_FACTS, "widget_count": widget_count})
    monkeypatch.setattr(sync, "_apply_auto_discovered", lambda facts: facts)  # no real AST/CDK discovery
    monkeypatch.setattr(sync, "_sync_platform_stats", lambda facts, dry_run: [])  # no real site_api_common.py
    monkeypatch.setattr(sync, "_sync_alarm_inventory", lambda dry_run: [])  # no real docs/MONITORING.md or cdk/stacks
    return doc


def test_check_exits_nonzero_on_drift(tmp_path, monkeypatch):
    """A deliberately-wrong literal (doc says 99, truth is 42) fails --check."""
    doc = _isolate(monkeypatch, tmp_path, "Header: v1 (99 Widgets)\n", widget_count=42)
    monkeypatch.setattr(sys, "argv", ["sync_doc_metadata.py", "--check"])

    with pytest.raises(SystemExit) as exc:
        sync.main()

    assert exc.value.code == 1
    assert doc.read_text(encoding="utf-8") == "Header: v1 (99 Widgets)\n", "--check must never write"


def test_check_exits_zero_when_current(tmp_path, monkeypatch):
    """The doc already matches the discovered value -> --check passes clean."""
    doc = _isolate(monkeypatch, tmp_path, "Header: v1 (42 Widgets)\n", widget_count=42)
    monkeypatch.setattr(sys, "argv", ["sync_doc_metadata.py", "--check"])

    with pytest.raises(SystemExit) as exc:
        sync.main()

    assert exc.value.code == 0
    assert doc.read_text(encoding="utf-8") == "Header: v1 (42 Widgets)\n"


def test_check_and_apply_are_mutually_exclusive(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path, "Header: v1 (42 Widgets)\n", widget_count=42)
    monkeypatch.setattr(sys, "argv", ["sync_doc_metadata.py", "--check", "--apply"])

    with pytest.raises(SystemExit) as exc:
        sync.main()

    assert exc.value.code == 2


def test_check_is_clean_on_repo_head():
    """Integration smoke test: the real gate, against the real repo, must pass.

    This is the state #389 requires main to be in before --check ships as a CI
    gate — if this test ever reds, a doc literal has drifted from the value
    sync_doc_metadata.py auto-discovers and `--apply` needs to be rerun.
    """
    result = subprocess.run(
        [sys.executable, os.path.join(_REPO, "deploy", "sync_doc_metadata.py"), "--check"],
        cwd=_REPO,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        "sync_doc_metadata.py --check found drift on repo HEAD — run "
        f"`python3 deploy/sync_doc_metadata.py --apply` and commit the fix.\n{result.stdout}\n{result.stderr}"
    )


# ── #934: AST-discovered alarm NAMES ────────────────────────────────────────────


def test_alarm_names_discovers_real_set_from_cdk():
    """The discoverer finds real CDK alarms across every alarm-defining stack, and
    excludes both the SRE-grader phantom names (#932) and the consolidated
    ingestion-error-* fleet (error_alarm=False, so no alarm is created)."""
    names = sync._auto_discover_alarm_names()
    assert names is not None and len(names) >= 20

    # Real names spanning the three construction shapes + multiple stacks.
    for real in (
        "mcp-warmer-error",  # direct cloudwatch.Alarm(...) in mcp_stack
        "life-platform-canary-anthropic-failure",  # _canary_alarm helper, operational
        "slo-source-freshness",  # _alarm helper, monitoring
        "ingest-consecutive-failures-whoop",  # f-string over a static loop var, monitoring
        "site-api-errors",  # direct, serve_stack
        "email-subscriber-errors",  # direct, web_stack
    ):
        assert real in names, f"expected real CDK alarm {real!r} missing from discovered set"

    # Phantom names the doc used to carry (hand-fixed in #932) must NOT appear.
    for phantom in (
        "slo-anthropic-canary",
        "life-platform-mcp-warmer-error",
        "life-platform-slo-budget-alarm",
        "life-platform-token-burn",
    ):
        assert phantom not in names, f"phantom alarm {phantom!r} leaked into discovered set"

    # The ingestion fleet's per-Lambda alarms are consolidated away, not real.
    assert "ingestion-error-whoop" not in names


def test_alarm_names_count_matches_alarm_count_discoverer():
    """One canonical name per alarm — the name-set size equals the #795 count."""
    names = sync._auto_discover_alarm_names()
    count = sync._auto_discover_alarm_count()
    assert names is not None and count is not None
    assert len(names) == count, f"name set ({len(names)}) diverged from alarm count ({count})"


def test_render_alarm_inventory_round_trips_the_name_set():
    """Every discovered name renders as a backticked bullet exactly once."""
    import re

    by_stack = sync._auto_discover_alarm_names_by_stack()
    assert by_stack is not None
    block = sync._render_alarm_inventory(by_stack)
    rendered = re.findall(r"^- `([^`]+)`$", block, re.MULTILINE)
    assert sorted(rendered) == sorted(sync._auto_discover_alarm_names())
    assert len(rendered) == len(set(rendered)), "a name was rendered more than once"


def test_sync_alarm_inventory_fills_markers_and_is_idempotent(tmp_path, monkeypatch):
    """--apply writes the block between the markers; a second pass is a no-op."""
    fake = {"monitoring_stack": ["alpha-alarm", "beta-alarm"], "serve_stack": ["gamma-alarm"]}
    monkeypatch.setattr(sync, "_auto_discover_alarm_names_by_stack", lambda: fake)
    doc = tmp_path / "MONITORING.md"
    doc.write_text(
        f"# Monitoring\n\n{sync._ALARM_INV_BEGIN}\nstale placeholder\n{sync._ALARM_INV_END}\n\n## Next\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(sync, "_MONITORING_PATH", doc)

    first = sync._sync_alarm_inventory(dry_run=False)
    assert any(c.startswith("  ~") for c in first)
    text = doc.read_text(encoding="utf-8")
    for n in ("alpha-alarm", "beta-alarm", "gamma-alarm"):
        assert f"- `{n}`" in text
    assert "stale placeholder" not in text
    assert text.startswith("# Monitoring") and text.rstrip().endswith("## Next")  # content outside markers preserved

    assert sync._sync_alarm_inventory(dry_run=False) == [], "second apply must be a clean no-op"


def test_sync_alarm_inventory_flags_missing_markers(tmp_path, monkeypatch):
    """A MONITORING.md with no marker pair is drift the gate must report."""
    monkeypatch.setattr(sync, "_auto_discover_alarm_names_by_stack", lambda: {"serve_stack": ["gamma-alarm"]})
    doc = tmp_path / "MONITORING.md"
    doc.write_text("# Monitoring\n\nno markers here\n", encoding="utf-8")
    monkeypatch.setattr(sync, "_MONITORING_PATH", doc)

    result = sync._sync_alarm_inventory(dry_run=True)
    assert result and result[0].startswith("  !")


# ── #973: restart verify-surface counts + hypothesis-engine cadence ────────────


def test_restart_url_counts_match_the_verify_script():
    """The discoverer reads the SAME lists restart_verify_rendered.py actually fetches.

    Loads the verify script as a module and compares len(PAGES)/len(JSON_ENDPOINTS)
    against the AST-discovered pair — self-updating, so adding a page to the verify
    surface can never silently diverge from what the docs claim.
    """
    import importlib.util

    counts = sync._auto_discover_restart_url_counts()
    assert counts is not None
    spec = importlib.util.spec_from_file_location("_rvr", os.path.join(_REPO, "deploy", "restart_verify_rendered.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert counts == (len(mod.PAGES), len(mod.JSON_ENDPOINTS))


def test_restart_url_counts_sanity_floor(tmp_path, monkeypatch):
    """A suspiciously small parse (e.g. a truncated file) falls back to None."""
    (tmp_path / "deploy").mkdir()
    (tmp_path / "deploy" / "restart_verify_rendered.py").write_text(
        'PAGES = ["/", "/now/"]\nJSON_ENDPOINTS = ["/api/vitals"]\n', encoding="utf-8"
    )
    monkeypatch.setattr(sync, "ROOT", tmp_path)
    assert sync._auto_discover_restart_url_counts() is None


def test_restart_url_counts_none_on_non_literal_lists(tmp_path, monkeypatch):
    """A computed (non-literal) list can't be counted statically — fall back, don't guess."""
    (tmp_path / "deploy").mkdir()
    (tmp_path / "deploy" / "restart_verify_rendered.py").write_text(
        "PAGES = [f'/data/{t}/' for t in TOPICS]\nJSON_ENDPOINTS = ['/a', '/b', '/c']\n", encoding="utf-8"
    )
    monkeypatch.setattr(sync, "ROOT", tmp_path)
    assert sync._auto_discover_restart_url_counts() is None


def test_hypothesis_cadence_from_real_cdk():
    """Against the real compute_stack.py: a weekly 'Day HH:MM UTC' phrase comes back."""
    import re as _re

    cadence = sync._auto_discover_hypothesis_cadence()
    assert cadence is not None
    assert _re.fullmatch(r"(Sun|Mon|Tue|Wed|Thu|Fri|Sat) \d{2}:\d{2} UTC", cadence)


def test_hypothesis_cadence_renders_weekly_cron(tmp_path, monkeypatch):
    """cron(30 7 ? * MON *) → 'Mon 07:30 UTC' (zero-padded, day title-cased)."""
    stacks = tmp_path / "cdk" / "stacks"
    stacks.mkdir(parents=True)
    (stacks / "compute_stack.py").write_text(
        "create_platform_lambda(\n"
        "    self,\n"
        '    "HypothesisEngine",\n'
        '    function_name="hypothesis-engine",\n'
        '    schedule="cron(30 7 ? * MON *)",\n'
        ")\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(sync, "ROOT", tmp_path)
    assert sync._auto_discover_hypothesis_cadence() == "Mon 07:30 UTC"


def test_hypothesis_cadence_none_when_not_weekly(tmp_path, monkeypatch):
    """A daily cron no longer fits the 'runs weekly (…)' sentence — fall back, don't guess."""
    stacks = tmp_path / "cdk" / "stacks"
    stacks.mkdir(parents=True)
    (stacks / "compute_stack.py").write_text(
        'create_platform_lambda(self, "HypothesisEngine", function_name="hypothesis-engine", schedule="cron(0 19 * * ? *)")\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(sync, "ROOT", tmp_path)
    assert sync._auto_discover_hypothesis_cadence() is None


def test_restart_url_count_fact_is_recomputed_as_sum(monkeypatch):
    """The headline 40 is always page_count + endpoint_count, even off the fallbacks."""
    monkeypatch.setattr(sync, "_auto_discover_restart_url_counts", lambda: (35, 8))
    monkeypatch.setattr(sync, "_auto_discover_hypothesis_cadence", lambda: None)
    facts = sync._apply_auto_discovered(dict(sync.PLATFORM_FACTS))
    assert facts["restart_page_count"] == 35
    assert facts["restart_endpoint_count"] == 8
    assert facts["restart_url_count"] == 43
