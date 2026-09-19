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

import doc_drift_verdict as _verdict  # noqa: E402 — #3646: the bot-owned/human-owned partition
import sync_doc_metadata as sync  # noqa: E402


def _isolate(monkeypatch, tmp_path, doc_text, widget_count):
    """Point sync at a synthetic single-doc/single-rule world in tmp_path.

    Keeps the test from touching real repo docs or lambdas/web/platform_counts.py
    (both of which _sync_platform_counts / the real RULES would otherwise reach for).
    """
    doc = tmp_path / "FAKE_DOC.md"
    doc.write_text(doc_text, encoding="utf-8")
    monkeypatch.setattr(sync, "ROOT", tmp_path)
    monkeypatch.setattr(sync, "RULES", [("FAKE_DOC.md", r"\d+ Widgets", "{widget_count} Widgets")])
    monkeypatch.setattr(sync, "PLATFORM_FACTS", {**sync.PLATFORM_FACTS, "widget_count": widget_count})
    monkeypatch.setattr(sync, "_apply_auto_discovered", lambda facts: facts)  # no real AST/CDK discovery
    monkeypatch.setattr(sync, "_sync_platform_counts", lambda facts, dry_run: [])  # no real platform_counts.py (#3101)
    monkeypatch.setattr(sync._alarm_inv, "sync", lambda dry_run, by_stack: [])  # no real docs/MONITORING.md or cdk/stacks
    return doc


def test_check_exits_pending_reconcile_on_bot_owned_drift(tmp_path, monkeypatch):
    """A deliberately-wrong literal (doc says 99, truth is 42) is BOT-OWNED drift.

    #3646 changed this expectation from 1 to 3, deliberately. `--apply` — the exact
    command the reconcile job runs — rewrites this literal, so on a merge commit the
    bot's own next commit carries the fix and a `failure` verdict names the bot's
    future commit as a defect. The run is PENDING, not red. The exit code is still
    non-zero, so nothing that treats "not 0" as "not clean" silently loosens; only a
    caller that explicitly knows a reconcile bot follows may tolerate 3.
    """
    doc = _isolate(monkeypatch, tmp_path, "Header: v1 (99 Widgets)\n", widget_count=42)
    monkeypatch.setattr(sys, "argv", ["sync_doc_metadata.py", "--check"])

    with pytest.raises(SystemExit) as exc:
        sync.main()

    assert exc.value.code == _verdict.EXIT_PENDING_RECONCILE
    assert doc.read_text(encoding="utf-8") == "Header: v1 (99 Widgets)\n", "--check must never write"


def test_push_to_main_tolerates_pending_reconcile_but_nothing_else_does(tmp_path, monkeypatch):
    """The event branch (#3646): exit 0 + a ::warning:: ONLY on a push to refs/heads/main.

    Deliberately narrow. A pull_request, a branch push, a workflow_dispatch and a laptop
    all still get the distinct non-zero 3 — nothing follows them that would commit the
    regenerated literals, so the author must run `--apply` exactly as before. The branch
    lives in the script rather than in a `run: |` block because
    `deploy/restart_verify_gates.py` derives Docs CI's gate list from single-line
    `run: python3 …` steps, and a block scalar would delete this gate from the reset
    pipeline's and the wrap battery's lists (#3477/#3534).
    """
    doc = _isolate(monkeypatch, tmp_path, "Header: v1 (99 Widgets)\n", widget_count=42)
    assert doc.exists()
    monkeypatch.setattr(sys, "argv", ["sync_doc_metadata.py", "--check"])

    for env, expected in (
        ({"GITHUB_EVENT_NAME": "push", "GITHUB_REF": "refs/heads/main"}, _verdict.EXIT_SUCCESS),
        ({"GITHUB_EVENT_NAME": "push", "GITHUB_REF": "refs/heads/issue-1-x"}, _verdict.EXIT_PENDING_RECONCILE),
        ({"GITHUB_EVENT_NAME": "pull_request", "GITHUB_REF": "refs/pull/1/merge"}, _verdict.EXIT_PENDING_RECONCILE),
        ({"GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_REF": "refs/heads/main"}, _verdict.EXIT_PENDING_RECONCILE),
        ({}, _verdict.EXIT_PENDING_RECONCILE),  # a laptop
    ):
        monkeypatch.delenv("GITHUB_EVENT_NAME", raising=False)
        monkeypatch.delenv("GITHUB_REF", raising=False)
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        with pytest.raises(SystemExit) as exc:
            sync.main()
        assert exc.value.code == expected, f"{env or 'no CI env'} expected exit {expected}, got {exc.value.code}"


def test_human_owned_drift_is_not_tolerated_even_on_a_push_to_main(tmp_path, monkeypatch):
    """The event branch must never reach un-repairable drift — the bot cannot clear it."""
    _isolate(monkeypatch, tmp_path, "Header: v1 (no widget line here at all)\n", widget_count=42)
    monkeypatch.setenv("GITHUB_EVENT_NAME", "push")
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    monkeypatch.setattr(sys, "argv", ["sync_doc_metadata.py", "--check"])

    with pytest.raises(SystemExit) as exc:
        sync.main()

    assert exc.value.code == _verdict.EXIT_FAILURE


def test_check_exits_failure_on_human_owned_drift(tmp_path, monkeypatch):
    """THE NEGATIVE CONTROL (#3646). Drift `--apply` cannot repair still fails, exit 1.

    The doc no longer carries the shape the rule guards at all, so the rule matches
    NOTHING — the "133 tools" class (#wiki-pr1), where a literal quietly stops being
    guarded. `--apply` rewrites nothing for it, so the reconcile bot's commit would
    NOT clear it: tolerating this as pending-reconcile would mint a gate that can never
    red over a doc that stays broken forever. This is the control the partition exists
    to keep failing, and it is the assertion the mutation below must break.
    """
    doc = _isolate(monkeypatch, tmp_path, "Header: v1 (no widget line here at all)\n", widget_count=42)
    monkeypatch.setattr(sys, "argv", ["sync_doc_metadata.py", "--check"])

    with pytest.raises(SystemExit) as exc:
        sync.main()

    assert exc.value.code == _verdict.EXIT_FAILURE, (
        "a rule whose pattern matched NOTHING is not repairable by --apply and must never " "be classified pending-reconcile (#3646)"
    )
    assert doc.read_text(encoding="utf-8") == "Header: v1 (no widget line here at all)\n"


def test_mixed_drift_is_failure_not_pending_reconcile(tmp_path, monkeypatch):
    """One human-owned record alongside bot-owned ones outranks them: the whole run fails.

    Partitioning must not be a majority vote — the bot's commit clears its own records and
    leaves the human's, so a run whose set is mixed is still red after the reconcile lands.
    """
    doc = tmp_path / "FAKE_DOC.md"
    doc.write_text("Header: v1 (99 Widgets)\n", encoding="utf-8")
    monkeypatch.setattr(sync, "ROOT", tmp_path)
    monkeypatch.setattr(
        sync,
        "RULES",
        [
            ("FAKE_DOC.md", r"\d+ Widgets", "{widget_count} Widgets"),  # bot-owned: --apply rewrites it
            ("FAKE_DOC.md", r"\d+ Gadgets", "{widget_count} Gadgets"),  # human-owned: matches nothing
        ],
    )
    monkeypatch.setattr(sync, "PLATFORM_FACTS", {**sync.PLATFORM_FACTS, "widget_count": 42})
    monkeypatch.setattr(sync, "_apply_auto_discovered", lambda facts: facts)
    monkeypatch.setattr(sync, "_sync_platform_counts", lambda facts, dry_run: [])
    monkeypatch.setattr(sync._alarm_inv, "sync", lambda dry_run, by_stack: [])
    monkeypatch.setattr(sys, "argv", ["sync_doc_metadata.py", "--check"])

    with pytest.raises(SystemExit) as exc:
        sync.main()

    assert exc.value.code == _verdict.EXIT_FAILURE


def test_partition_is_fail_closed_for_an_unrecognised_record():
    """A drift record the partition cannot prove bot-owned counts as human-owned.

    Guards the default for a drift source added to --check later: `human = total - bot`,
    so a new record shape is red until someone deliberately teaches the partition about it.
    """
    assert _verdict.classify(3, 3) == (_verdict.VERDICT_PENDING_RECONCILE, 0)
    assert _verdict.classify(3, 2) == (_verdict.VERDICT_FAILURE, 1)
    assert _verdict.classify(0, 0) == (_verdict.VERDICT_SUCCESS, 0)
    # The shapes the checker actually emits, classified by the shipped helper.
    assert _verdict.bot_owned(
        [
            "  ~ '99 Widgets'\n    → '42 Widgets'",
            "  ! rule pattern matched NOTHING (doc or rule drifted — fix one): '\\d+ Gadgets'",
            "  SKIP (not found): docs/GONE.md",
        ]
    ) == ["  ~ '99 Widgets'\n    → '42 Widgets'"]


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
    try:
        result = subprocess.run(
            [sys.executable, os.path.join(_REPO, "deploy", "sync_doc_metadata.py"), "--check"],
            cwd=_REPO,
            capture_output=True,
            text=True,
            # #3849, the Set's third member. This was 30s, and on 2026-09-16 it
            # TimeoutExpired in the pre-merge lane on a branch whose diff could not slow a
            # doc-sync scan. The checker measures ~11s locally; 30s was ~2.7x that, which
            # reads like headroom and is not — under #3797's parallel lane the whole suite
            # is competing for the same runner, and the first member of this Set failed at
            # 2.73s against a budget built on the same reasoning.
            #
            # The distinction that fixes it: THIS NUMBER IS NOT AN ASSERTION. The property
            # under test is `--check` exits 0 on repo HEAD; how long it takes is not a
            # claim this test makes. So the timeout is sized as a HANG DETECTOR — large
            # enough that only a genuinely wedged subprocess reaches it, never as a
            # performance budget that a busy machine can trip. ~27x the measured cost.
            timeout=300,
        )
    except subprocess.TimeoutExpired as e:  # pragma: no cover — only a real hang reaches this
        raise AssertionError(
            "sync_doc_metadata.py --check did not finish in 300s. That is a HANG, not slowness: "
            "the checker measures ~11s and this ceiling is ~27x that. Do not raise it — find what "
            "is blocking (a network read that should not be there, a lock, an infinite walk). (#3849)"
        ) from e
    assert result.returncode == 0, (
        "sync_doc_metadata.py --check found drift on repo HEAD — run "
        "`python3 deploy/sync_doc_metadata.py --apply` and commit the fix. NB #3646: exit 3 "
        "(pending-reconcile) is not clean HERE — the reconcile bot only follows a push to "
        "main, so a branch must carry its own regenerated literals as it always has."
        f"\n{result.stdout}\n{result.stderr}"
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
    block = sync._alarm_inv.render(by_stack)
    rendered = re.findall(r"^- `([^`]+)`$", block, re.MULTILINE)
    assert sorted(rendered) == sorted(sync._auto_discover_alarm_names())
    assert len(rendered) == len(set(rendered)), "a name was rendered more than once"


def test_sync_alarm_inventory_fills_markers_and_is_idempotent(tmp_path, monkeypatch):
    """--apply writes the block between the markers; a second pass is a no-op."""
    fake = {"monitoring_stack": ["alpha-alarm", "beta-alarm"], "serve_stack": ["gamma-alarm"]}
    doc = tmp_path / "MONITORING.md"
    doc.write_text(
        f"# Monitoring\n\n{sync._alarm_inv.ALARM_INV_BEGIN}\nstale placeholder\n{sync._alarm_inv.ALARM_INV_END}\n\n## Next\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(sync._alarm_inv, "MONITORING_PATH", doc)

    first = sync._alarm_inv.sync(dry_run=False, by_stack=fake)
    assert any(c.startswith("  ~") for c in first)
    text = doc.read_text(encoding="utf-8")
    for n in ("alpha-alarm", "beta-alarm", "gamma-alarm"):
        assert f"- `{n}`" in text
    assert "stale placeholder" not in text
    assert text.startswith("# Monitoring") and text.rstrip().endswith("## Next")  # content outside markers preserved

    assert sync._alarm_inv.sync(dry_run=False, by_stack=fake) == [], "second apply must be a clean no-op"


def test_sync_alarm_inventory_flags_missing_markers(tmp_path, monkeypatch):
    """A MONITORING.md with no marker pair is drift the gate must report."""
    doc = tmp_path / "MONITORING.md"
    doc.write_text("# Monitoring\n\nno markers here\n", encoding="utf-8")
    monkeypatch.setattr(sync._alarm_inv, "MONITORING_PATH", doc)

    result = sync._alarm_inv.sync(dry_run=True, by_stack={"serve_stack": ["gamma-alarm"]})
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
        'PAGES = ["/", "/cockpit/"]\nJSON_ENDPOINTS = ["/api/vitals"]\n', encoding="utf-8"
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


# ── #1437: AST-discovered site-api endpoint count ───────────────────────────────


def test_endpoint_count_discovers_real_count_from_site_api():
    """Against the real lambdas/web/site_api_lambda.py: comfortably past the sanity
    floor and (verified 2026-07-18) an order of magnitude past the docs' stale
    "60+" — this is exactly the drift class #1437 exists to kill."""
    count = sync._auto_discover_endpoint_count()
    assert count is not None
    assert count >= 100, f"endpoint count ({count}) suspiciously low vs. the known ~115 live count"


def test_endpoint_count_dedupes_across_all_three_mechanisms(tmp_path, monkeypatch):
    """A path registered in ROUTES (as a None placeholder), reserved again in
    _SIMPLE_ROUTES, AND checked again inline must count ONCE — not three times.

    Exercises the real shipped `_auto_discover_endpoint_count()` (not a reimplementation)
    against a synthetic fixture padded past the >=50 sanity floor: 55 unique ROUTES
    entries (3 of them None placeholders standing in for _SIMPLE_ROUTES/inline dispatch:
    verify_subscriber, board_ask, predictions), one genuinely-new path only in
    _SIMPLE_ROUTES (nudge — verify_subscriber there is a dup of the ROUTES placeholder),
    and two genuinely-new paths only checked inline (healthz via `==`, `/api/coach/` via
    `.startswith(...)` — board_ask/predictions there are dups of ROUTES placeholders).
    Expected unique total: 55 + 1 + 2 = 58 — which would be 55 + 2 + 4 = 61 if the three
    mechanisms' raw entries were naively summed instead of deduplicated.
    """
    fake_web = tmp_path / "lambdas" / "web"
    fake_web.mkdir(parents=True)
    routes_entries = "\n".join(f'    "/api/path{i}": handle_path{i},' for i in range(52))
    routes_entries += (
        '\n    "/api/verify_subscriber": None,  # dispatched via _SIMPLE_ROUTES below'
        '\n    "/api/board_ask": None,  # inline-checked below too'
        '\n    "/api/predictions": None,  # inline-checked below too'
    )
    (fake_web / "site_api_lambda.py").write_text(
        f"ROUTES = {{\n{routes_entries}\n}}\n"
        "\n"
        "_SIMPLE_ROUTES = {\n"
        '    "/api/verify_subscriber": ({"GET"}, _handle_verify_subscriber),\n'
        '    "/api/nudge": ({"POST"}, _handle_nudge),  # new, not in ROUTES\n'
        "}\n"
        "\n"
        "def lambda_handler(event, context):\n"
        '    path = event.get("rawPath")\n'
        '    if path == "/api/board_ask":\n'
        "        return _forward()\n"
        '    if path == "/api/predictions":\n'
        "        return handle_predictions(event)\n"
        '    if path == "/api/healthz":  # new, not in ROUTES or _SIMPLE_ROUTES\n'
        "        return _health()\n"
        '    if path.startswith("/api/coach/"):  # new prefix route\n'
        "        return handle_coach(event)\n"
        "    return ROUTES.get(path)\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(sync, "ROOT", tmp_path)

    count = sync._auto_discover_endpoint_count()
    assert count == 58, f"expected 55 ROUTES-registered + 1 new-in-_SIMPLE_ROUTES + 2 new-inline = 58 unique, got {count}"


def test_endpoint_count_sanity_floor_rejects_tiny_fixture(tmp_path, monkeypatch):
    """A truncated/broken site_api_lambda.py (too few routes) falls back to None
    rather than reporting a suspiciously small "real" count."""
    fake_site_api = tmp_path / "lambdas" / "web"
    fake_site_api.mkdir(parents=True)
    (fake_site_api / "site_api_lambda.py").write_text(
        "ROUTES = {\n"
        '    "/api/vitals": handle_vitals,\n'
        "}\n"
        "\n"
        "_SIMPLE_ROUTES = {}\n"
        "\n"
        "def lambda_handler(event, context):\n"
        '    path = event.get("rawPath")\n'
        "    return ROUTES.get(path)\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(sync, "ROOT", tmp_path)
    assert sync._auto_discover_endpoint_count() is None


def test_endpoint_count_none_when_lambda_handler_missing(tmp_path, monkeypatch):
    """A file with ROUTES but no lambda_handler def can't be trusted — fall back."""
    fake_site_api = tmp_path / "lambdas" / "web"
    fake_site_api.mkdir(parents=True)
    (fake_site_api / "site_api_lambda.py").write_text('ROUTES = {"/api/vitals": handle_vitals}\n', encoding="utf-8")
    monkeypatch.setattr(sync, "ROOT", tmp_path)
    assert sync._auto_discover_endpoint_count() is None


def test_endpoint_count_docs_match_discovered_value():
    """CLAUDE.md and docs/ONBOARDING.md must quote the SAME endpoint count the
    AST discoverer finds — this is the literal that used to say a stale "60+"
    against a real count over 100 (#1437). Mirrors the rule --check enforces,
    but asserts it directly against repo HEAD so a future non-doc-sync edit to
    either file can't quietly reintroduce a mismatched number."""
    import re as _re

    count = sync._auto_discover_endpoint_count()
    assert count is not None

    claude_md = (sync.ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    m = _re.search(r"with ~(\d+) endpoints including", claude_md)
    assert m, "CLAUDE.md's Site API Lambda bullet no longer matches the expected 'with ~N endpoints including' shape"
    assert int(m.group(1)) == count

    onboarding_md = (sync.ROOT / "docs" / "ONBOARDING.md").read_text(encoding="utf-8")
    m2 = _re.search(r"site-api Lambda \(~(\d+) endpoints, primarily read-only — ADR-037\)", onboarding_md)
    assert m2, "docs/ONBOARDING.md's site-api line no longer matches the expected shape"
    assert int(m2.group(1)) == count
