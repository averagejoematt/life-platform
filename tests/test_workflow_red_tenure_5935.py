"""#5935 — the workflow-red tenure rule and its boot-brief line.

`operating-calendar.yml` was red on every scheduled run from 2026-09-30 for ~45 days and no
issue owned it: alarms had a tenure rule, workflow reds did not. The rule lives in
`scripts/check_cron_freshness.py` (`--file-tenure`, run on every push to main by
`cron-freshness.yml`): the third consecutive scheduled red files ONE deduped tracker, an open
tracker is refreshed in place, a green newest run closes it — and the SessionStart boot brief
prints days-red for every open workflow tracker.

Every GitHub write here goes through a fake client; `scheduled_runs` is monkeypatched in the
one test that drives `run_tenure`/`main`, so nothing in this file touches the network.
"""

import datetime as dt
import importlib.util
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import advisory_failure_issue as afi  # noqa: E402
import check_backlog_hygiene as hy  # noqa: E402
import check_cron_freshness as watch  # noqa: E402
import operating_calendar as oc  # noqa: E402

_spec = importlib.util.spec_from_file_location("bb5935", ROOT / "scripts" / "boot_brief.py")
bb = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = bb
_spec.loader.exec_module(bb)

NOW = dt.datetime(2026, 11, 14, 18, 0, tzinfo=dt.timezone.utc)
WF = "operating-calendar.yml"
NAME = "Operating calendar dead-man"


def _run(day, conclusion, status="completed"):
    return {
        "created_at": f"2026-11-{day:02d}T15:42:00Z",
        "status": status,
        "conclusion": conclusion,
        "html_url": f"https://example.invalid/runs/{day}",
    }


class FakeClient:
    """advisory_failure_issue.GitHubClient's surface, recording every write."""

    def __init__(self, issues=None, race_twin=None):
        self.issues = list(issues or [])
        self.calls = []
        self.next_number = 9000
        self.race_twin = race_twin  # an issue a concurrent run "creates" first

    def list_open_issues(self, label):
        self.calls.append(("list", label))
        return [i for i in self.issues if i.get("state", "open") == "open"]

    def ensure_label(self, name, color, description):
        self.calls.append(("label", name))

    def create_issue(self, title, body, labels):
        self.next_number += 1
        issue = {"number": self.next_number, "title": title, "body": body, "labels": [{"name": n} for n in labels]}
        if self.race_twin is not None:
            self.issues.append(dict(self.race_twin, body=body))
        self.issues.append(issue)
        self.calls.append(("create", self.next_number, title, tuple(labels)))
        return issue

    def update_issue_body(self, number, body):
        self.calls.append(("update", number))
        for i in self.issues:
            if i["number"] == number:
                i["body"] = body

    def comment(self, number, body):
        self.calls.append(("comment", number, body))

    def close_issue(self, number):
        self.calls.append(("close", number))
        for i in self.issues:
            if i["number"] == number:
                i["state"] = "closed"

    def writes(self, kind):
        return [c for c in self.calls if c[0] == kind]


# ── the streak ───────────────────────────────────────────────────────────────


def test_streak_counts_consecutive_reds_back_to_the_last_green_in_any_page_order():
    runs = [_run(11, "failure"), _run(14, "failure"), _run(10, "success"), _run(12, "failure"), _run(13, "failure")]
    s = watch.red_streak(runs)
    assert s["streak"] == 4
    assert s["red_since"] == "2026-11-11T15:42:00Z"
    assert s["newest_red_url"].endswith("/14")
    assert s["latest"] == "red" and s["lower_bound"] is False


def test_in_progress_and_neutral_runs_are_stepped_over_not_read_as_green():
    runs = [_run(14, None, status="in_progress"), _run(13, "cancelled"), _run(12, "failure"), _run(11, "timed_out"), _run(10, "success")]
    s = watch.red_streak(runs)
    assert s["streak"] == 2 and s["latest"] == "red"


def test_a_page_that_is_red_end_to_end_is_a_lower_bound():
    runs = [_run(d, "failure") for d in range(1, 11)]
    assert watch.red_streak(runs, sample=10)["lower_bound"] is True
    assert watch.red_streak(runs, sample=30)["lower_bound"] is False  # fewer runs than a page: the whole history


# ── the plan: the third red files, never two owners ──────────────────────────


def _streak(n, latest="red"):
    return {"streak": n, "red_since": "2026-11-12T15:42:00Z", "newest_red_url": "u", "latest": latest, "lower_bound": False}


def test_the_third_consecutive_red_files_and_the_second_does_not():
    """The must-fail control: the boundary is exact in both directions."""
    assert watch.plan_tenure({WF: _streak(3)}, [])[0]["action"] == watch.T_FILE
    assert watch.plan_tenure({WF: _streak(2)}, [])[0]["action"] == watch.T_BELOW
    assert watch.plan_tenure({WF: _streak(0, latest="green")}, []) == []
    # mutation: lower the threshold and the second red WOULD file — the check can fail.
    assert watch.plan_tenure({WF: _streak(2)}, [], threshold=2)[0]["action"] == watch.T_FILE


def test_a_workflow_with_its_own_open_advisory_tracker_is_owned_not_double_filed():
    owner = {"number": 77, "body": afi.issue_marker("operating-calendar-advisory")}
    plan = watch.plan_tenure({WF: _streak(5)}, [owner], {WF: ["operating-calendar-advisory"]})
    assert plan == [{"file": WF, "action": watch.T_OWNED, "issue": 77}]
    # mutation: without the slug map the same red would file a second owner.
    assert watch.plan_tenure({WF: _streak(5)}, [owner])[0]["action"] == watch.T_FILE


def test_an_open_tenure_tracker_is_refreshed_while_red_and_closed_on_green():
    tracker = {"number": 88, "body": afi.issue_marker(watch.tenure_slug(WF))}
    assert watch.plan_tenure({WF: _streak(9)}, [tracker])[0] == {"file": WF, "action": watch.T_REFRESH, "issue": 88}
    assert watch.plan_tenure({WF: _streak(0, latest="green")}, [tracker])[0] == {"file": WF, "action": watch.T_CLOSE, "issue": 88}


def test_a_failed_lookup_is_unverified_never_green():
    assert watch.plan_tenure({WF: False}, [])[0]["action"] == watch.T_UNVERIFIED


def test_advisory_slugs_reads_literals_and_skips_templates():
    text = "      with:\n          workflow-slug: fresh-eyes-discovery\n          workflow-slug: ${{ matrix.slug }}\n"
    assert watch.advisory_slugs(text) == ["fresh-eyes-discovery"]


# ── applying it: one tracker, the filing contract, never twice ───────────────


def _apply(client, streaks):
    open_issues = client.list_open_issues(afi.MARKER_LABEL)
    plan = watch.plan_tenure(streaks, open_issues)
    return watch.apply_tenure(plan, streaks, {WF: NAME}, open_issues, client, NOW)


def test_filing_then_rerunning_refreshes_the_same_issue_and_never_files_twice():
    client = FakeClient()
    results, errors = _apply(client, {WF: _streak(3)})
    assert errors == [] and len(client.writes("create")) == 1
    _, number, title, labels = client.writes("create")[0]
    assert title == f"[auto-filed] {NAME}: red on 3+ consecutive scheduled runs"
    assert labels == ("auto-filed", "area:infra")
    # the next watcher run (one more red) sees its own tracker and refreshes it
    results, errors = _apply(client, {WF: _streak(4)})
    assert errors == [] and len(client.writes("create")) == 1, "a second create = filed twice"
    assert client.writes("update")[-1] == ("update", number)


def test_the_filed_issue_satisfies_the_hygiene_tracker_contract():
    client = FakeClient()
    _apply(client, {WF: _streak(3)})
    issue = client.issues[-1]
    ctx = hy.build_ctx(dict(issue, milestone=None, createdAt="2026-11-14T18:00:00Z", updatedAt="2026-11-14T18:00:00Z"))
    assert hy.is_tracker(ctx), "must ride the #3065 tracker carve-out (auto-filed + marker + no type:*)"
    findings = [f for rule in hy.TRACKER_RULES for f in rule(ctx)]
    assert findings == [], findings
    # mutation: strip the close policy and the hygiene rule fires — the contract can fail.
    stripped = dict(ctx, body=ctx["body"].replace(hy.TRACKER_CLOSE_POLICY, "Close:"))
    assert hy.rule_tracker_close_policy(stripped)


def test_a_concurrent_racer_converges_on_the_lowest_numbered_tracker():
    twin = {"number": 10, "title": "x", "labels": []}
    client = FakeClient(race_twin=twin)
    results, errors = _apply(client, {WF: _streak(3)})
    assert errors == []
    assert ("close", 9001) in client.calls, "the later duplicate must close itself"
    assert any("Duplicate of #10" in c[2] for c in client.writes("comment"))


def test_green_closes_the_tracker_with_a_recovery_comment():
    tracker = {"number": 88, "body": afi.issue_marker(watch.tenure_slug(WF))}
    client = FakeClient([tracker])
    _apply(client, {WF: _streak(0, latest="green")})
    assert client.writes("close") == [("close", 88)]
    assert "Recovered" in client.writes("comment")[0][2]


def test_refresh_keeps_the_earlier_red_since_only_when_the_read_was_a_lower_bound():
    body = watch.build_tenure_body(WF, NAME, dict(_streak(3), red_since="2026-09-30T15:40:00Z"), NOW)
    bounded = dict(_streak(30), red_since="2026-10-16T15:45:00Z", lower_bound=True)
    assert "workflow-red-since: 2026-09-30T15:40:00Z" in watch.refresh_tenure_body(body, bounded, NOW)
    exact = dict(_streak(3), red_since="2026-11-12T15:42:00Z")
    assert "workflow-red-since: 2026-11-12T15:42:00Z" in watch.refresh_tenure_body(body, exact, NOW)


def test_act_without_a_token_files_nothing_and_says_so(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.setattr(watch, "scheduled_runs", lambda _f, per_page=watch.TENURE_SAMPLE: [_run(d, "failure") for d in (12, 13, 14)])
    report, summary, errors = watch.run_tenure({WF: {"name": NAME}}, NOW, act=True)
    assert errors and "no GITHUB_TOKEN" in errors[0]
    assert summary["results"] == []


def test_main_wires_file_tenure_and_a_failed_write_reds_the_run(monkeypatch, capsys):
    rows = {WF: {"name": NAME, "watched": False, "crons": ["40 15 * * *"], "cadence_hours": 24.0, "grace_hours": 8, "deadline_hours": 32}}
    monkeypatch.setattr(watch, "SCHEDULED_WORKFLOW_FLOOR", 1)
    monkeypatch.setattr(watch, "discover_scheduled_workflows", lambda: dict(rows))
    monkeypatch.setattr(watch, "unruled_workflows", lambda: [])
    monkeypatch.setattr(watch, "orphaned_policy_rows", lambda: [])
    monkeypatch.setattr(watch, "scheduled_runs", lambda _f, per_page=watch.TENURE_SAMPLE: [_run(d, "failure") for d in (12, 13, 14)])

    class Broken(FakeClient):
        def create_issue(self, **_kw):
            raise RuntimeError("422")

    monkeypatch.setattr(watch, "_tenure_client", lambda: Broken())
    assert watch.main(["--file-tenure"]) == 1
    out = capsys.readouterr().out
    assert "WORKFLOW-RED TENURE" in out and "file failed" in out
    # without the flag the tenure pass does not run at all (hermetic default)
    assert watch.main([]) == 0


def test_the_workflow_runs_the_filing_pass_with_issue_write():
    text = (ROOT / ".github" / "workflows" / "cron-freshness.yml").read_text(encoding="utf-8")
    assert "run: python3 scripts/check_cron_freshness.py --file-tenure" in text
    assert "issues: write" in text and "GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}" in text


# ── the boot brief prints days-red ───────────────────────────────────────────


def test_boot_brief_prints_days_red_for_tenure_and_advisory_trackers():
    tenure = {
        "number": 6001,
        "title": f"[auto-filed] {NAME}: red on 3+ consecutive scheduled runs",
        "body": watch.build_tenure_body(WF, NAME, dict(_streak(45), red_since="2026-09-30T15:40:00Z"), NOW),
    }
    advisory = {
        "number": 6002,
        "title": "[auto-filed] Visual QA (standalone): scheduled advisory run failing",
        "body": afi.build_issue_body("visual-qa-standalone", "Visual QA (standalone)", "u", "2026-11-13T18:00:00Z", "schedule"),
    }
    lines = bb.workflow_red_lines(NOW, reader=lambda: [advisory, tenure, {"number": 1, "title": "unrelated", "body": "x"}])
    assert len(lines) == 2
    assert lines[0].startswith("  WF RED      Operating calendar dead-man — red 45d02h since 2026-09-30 (#6001, tenure tracker)")
    assert "Visual QA (standalone) — red 1d00h since 2026-11-13 (#6002, advisory tracker)" in lines[1]


def test_boot_brief_unreadable_is_unverified_and_empty_is_none():
    def boom():
        raise OSError("gh missing")

    assert "UNVERIFIED" in bb.workflow_red_lines(NOW, reader=boom)[0]
    assert "none" in bb.workflow_red_lines(NOW, reader=lambda: [])[0]


def test_the_sessionstart_hook_prints_the_workflow_red_lines(monkeypatch, capsys):
    spec = importlib.util.spec_from_file_location("sp5935", ROOT / "scripts" / "hooks" / "session_preflight.py")
    sp = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = sp
    spec.loader.exec_module(sp)
    monkeypatch.setenv("CLAUDE_HOOK_INERT", "1")
    assert "wf reds     UNVERIFIED" in sp._workflow_reds()[0]
    assert "_workflow_reds()" in (ROOT / "scripts" / "hooks" / "session_preflight.py").read_text(encoding="utf-8").split("def main")[1]


# ── the ritual ruling: emf-series-census is deferred with a date, not exempted by silence ──


def test_emf_series_census_is_held_to_2026_11_28_by_the_owner_ruling():
    declared, until, reason = oc.CALENDAR["emf-series-census"]["hold"]
    assert (declared, until) == ("2026-11-14", "2026-11-28")
    assert reason.startswith("#5888: the census cannot pass before its window ends")
    assert oc.status(oc.CALENDAR["emf-series-census"], dt.date(2026, 11, 20))["state"] == oc.HELD
    # an EXEMPT row could not carry it: EXEMPT is keyed by review procedure (the set guard's phantom rule)
    assert "emf-series-census" not in oc.EXEMPT
