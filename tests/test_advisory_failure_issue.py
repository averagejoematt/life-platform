"""
tests/test_advisory_failure_issue.py — offline unit tests for
scripts/advisory_failure_issue.py (#1447: advisory scheduled workflows file a
deduped GitHub issue on failure, and auto-close it on recovery).

Everything here is pure/offline (no network, no gh CLI): the marker + dedup
logic, the ADR-099-shaped body builders, and the file/recover orchestration
against a fake GitHub client. The urllib client only runs for real inside the
scheduled workflows via .github/actions/advisory-failure-issue.

The dedup contract under test (the issue's acceptance criteria):
  - one open issue per workflow — a repeat failure COMMENTS on the existing
    open issue instead of filing a duplicate;
  - a different workflow's open issue is never mistaken for ours;
  - recovery (a green run) comments + closes the open issue, and is a no-op
    when nothing is open.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import advisory_failure_issue as afi  # noqa: E402

SLUG = "visual-qa-standalone"
NAME = "Visual QA (standalone)"
RUN_URL = "https://github.com/averagejoematt/life-platform/actions/runs/123456"
NOW = "2026-07-19T20:15:00Z"


def _issue(number, slug, state="open", extra=None):
    d = {
        "number": number,
        "state": state,
        "title": f"[auto-filed] workflow {slug} failing",
        "body": f"some preamble\n{afi.issue_marker(slug)}\nrest of body",
        "labels": [{"name": afi.MARKER_LABEL}],
    }
    if extra:
        d.update(extra)
    return d


class FakeClient:
    """Records every write; serves a canned open-issue list."""

    def __init__(self, open_issues=None, fail_on=None):
        self.open_issues = list(open_issues or [])
        self.fail_on = fail_on
        self.created = []
        self.comments = []
        self.closed = []
        self.labels_ensured = []

    def _maybe_fail(self, op):
        if self.fail_on == op:
            raise RuntimeError(f"boom on {op}")

    def list_open_issues(self, label):
        self._maybe_fail("list")
        return [i for i in self.open_issues if any(lbl.get("name") == label for lbl in i.get("labels", []))]

    def ensure_label(self, name, color, description):
        self._maybe_fail("ensure_label")
        self.labels_ensured.append(name)

    def create_issue(self, title, body, labels):
        self._maybe_fail("create")
        self.created.append({"title": title, "body": body, "labels": labels})
        return {"number": 900 + len(self.created), "html_url": "https://example.invalid/900"}

    def comment(self, number, body):
        self._maybe_fail("comment")
        self.comments.append({"number": number, "body": body})

    def close_issue(self, number):
        self._maybe_fail("close")
        self.closed.append(number)


# ── marker + dedup ───────────────────────────────────────────────────────────


def test_issue_marker_is_slug_scoped_html_comment():
    m = afi.issue_marker(SLUG)
    assert m.startswith("<!--") and m.endswith("-->")
    assert SLUG in m
    # different slugs → different markers (dedup key is per-workflow)
    assert afi.issue_marker("fresh-eyes-discovery") != m


def test_find_open_issue_matches_only_our_slug():
    ours = _issue(41, SLUG)
    theirs = _issue(42, "fresh-eyes-discovery")
    assert afi.find_open_issue([theirs, ours], SLUG)["number"] == 41
    assert afi.find_open_issue([theirs], SLUG) is None
    assert afi.find_open_issue([], SLUG) is None


def test_find_open_issue_ignores_pull_requests():
    pr = _issue(43, SLUG, extra={"pull_request": {"url": "x"}})
    assert afi.find_open_issue([pr], SLUG) is None


def test_find_open_issue_tolerates_null_body():
    nobody = _issue(44, SLUG)
    nobody["body"] = None
    assert afi.find_open_issue([nobody], SLUG) is None


# ── body builders (ADR-099 shape: what failed, run link, first-failure ts) ──


def test_issue_body_carries_marker_run_link_and_first_failure():
    body = afi.build_issue_body(SLUG, NAME, RUN_URL, NOW, "schedule", "summary text")
    assert afi.issue_marker(SLUG) in body
    assert RUN_URL in body
    assert NOW in body
    assert NAME in body
    assert "summary text" in body


def test_failure_comment_carries_run_link_and_timestamp():
    c = afi.build_failure_comment(RUN_URL, NOW, "schedule", "again")
    assert RUN_URL in c and NOW in c and "again" in c


def test_recovery_comment_carries_run_link():
    c = afi.build_recovery_comment(RUN_URL, NOW)
    assert RUN_URL in c and NOW in c


# ── file mode: create vs dedup-comment ───────────────────────────────────────


def test_file_mode_creates_issue_when_none_open():
    client = FakeClient()
    result = afi.run("file", SLUG, NAME, "s", RUN_URL, "schedule", client, now_iso=NOW)
    assert len(client.created) == 1
    assert client.comments == []
    created = client.created[0]
    assert afi.MARKER_LABEL in created["labels"]
    assert afi.issue_marker(SLUG) in created["body"]
    assert RUN_URL in created["body"]
    assert afi.MARKER_LABEL in client.labels_ensured
    assert result.startswith("created:")


def test_file_mode_comments_on_existing_issue_instead_of_duplicating():
    client = FakeClient(open_issues=[_issue(41, SLUG)])
    result = afi.run("file", SLUG, NAME, "s", RUN_URL, "schedule", client, now_iso=NOW)
    assert client.created == []  # THE dedup assertion: no duplicate issue
    assert len(client.comments) == 1
    assert client.comments[0]["number"] == 41
    assert RUN_URL in client.comments[0]["body"]
    assert result == "commented:41"


def test_file_mode_ignores_other_workflows_issue_and_creates_ours():
    client = FakeClient(open_issues=[_issue(42, "golden-brief-eval")])
    afi.run("file", SLUG, NAME, "s", RUN_URL, "schedule", client, now_iso=NOW)
    assert len(client.created) == 1
    assert client.comments == []


# ── recover mode: comment + close, or no-op ──────────────────────────────────


def test_recover_mode_comments_and_closes_open_issue():
    client = FakeClient(open_issues=[_issue(41, SLUG)])
    result = afi.run("recover", SLUG, NAME, "", RUN_URL, "schedule", client, now_iso=NOW)
    assert client.closed == [41]
    assert len(client.comments) == 1
    assert client.comments[0]["number"] == 41
    assert client.created == []
    assert result == "closed:41"


def test_recover_mode_noop_when_nothing_open():
    client = FakeClient()
    result = afi.run("recover", SLUG, NAME, "", RUN_URL, "schedule", client, now_iso=NOW)
    assert client.closed == [] and client.comments == [] and client.created == []
    assert result == "noop"


def test_run_rejects_unknown_mode():
    try:
        afi.run("nonsense", SLUG, NAME, "", RUN_URL, "schedule", FakeClient(), now_iso=NOW)
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


# ── error posture: a red filing step must not fake green (file mode), and a ──
# ── recovery hiccup must never red an otherwise-green advisory run ──────────


def test_exit_code_for_error_file_mode_is_nonzero():
    assert afi.exit_code_for_error("file") == 1


def test_exit_code_for_error_recover_mode_is_zero():
    assert afi.exit_code_for_error("recover") == 0


# ── #4262 box 2: wrap-nightly's run step — a degrade is a red, and the check's rc is kept ──
# The step is executed as GitHub runs it (`bash -eo pipefail`), with CHECK_CMD swapped for a
# stand-in, so these pin the step text itself, not a paraphrase of it.
_WRAP_NIGHTLY = os.path.join(os.path.dirname(__file__), "..", ".github", "workflows", "wrap-nightly.yml")


def _wrap_nightly_step() -> str:
    import yaml

    with open(_WRAP_NIGHTLY, encoding="utf-8") as fh:
        steps = yaml.safe_load(fh)["jobs"]["check"]["steps"]
    return next(s["run"] for s in steps if "CHECK_CMD" in (s.get("run") or ""))


def _run_wrap_step(tmp_path, body: str) -> int:
    """Run the step with CHECK_CMD pointing at a stand-in script whose body is `body`."""
    import subprocess

    stand_in = tmp_path / "stand_in.sh"
    stand_in.write_text(body + "\n", encoding="utf-8")
    env = {**os.environ, "CHECK_CMD": f"bash {stand_in}"}
    return subprocess.run(
        ["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", _wrap_nightly_step()], env=env, capture_output=True
    ).returncode


def test_wrap_nightly_step_keeps_the_checks_own_exit_code(tmp_path):
    assert _run_wrap_step(tmp_path, "echo OK; exit 0") == 0
    assert _run_wrap_step(tmp_path, "echo 'UNGATED residual bullets'; exit 1") == 1
    assert _run_wrap_step(tmp_path, "exit 2") == 2


def test_wrap_nightly_step_reds_a_check_that_declined_to_look(tmp_path):
    """Both degrade shapes exit 0 from the check itself; nobody reads them at night."""
    assert _run_wrap_step(tmp_path, "echo 'alarm citations UNVERIFIED this run'; exit 0") == 1
    assert _run_wrap_step(tmp_path, "echo 'check_backlog_hygiene: gh issue list exited 4: auth; skipping (advisory).'; exit 0") == 1


def test_wrap_nightly_legs_cover_the_wrap_only_checks_it_claims():
    """The legs ARE wrap_gates.NIGHTLY, in both directions (#4262 follow-up): a check that left
    the interactive wrap has a nightly home, and a leg runs a real wrap gate command. The two
    left out are named in the file, with their reasons."""
    import re

    import yaml

    with open(_WRAP_NIGHTLY, encoding="utf-8") as fh:
        text = fh.read()
    legs = yaml.safe_load(text)["jobs"]["check"]["strategy"]["matrix"]["include"]
    import wrap_gates

    nightly = {" ".join(g.cmd) for g in wrap_gates.NIGHTLY}
    assert len({leg["slug"] for leg in legs}) == len(legs) == 5
    for leg in legs:
        assert leg["cmd"] in nightly, f"{leg['slug']} runs {leg['cmd']!r}, which is not a wrap_gates.NIGHTLY gate"
    missing = nightly - {leg["cmd"] for leg in legs}
    assert not missing, f"#4262: wrap_gates.NIGHTLY names {sorted(missing)} but no wrap-nightly.yml leg runs it — it would run nowhere"
    # a check that moved OUT of the wrap must not still run in it; the two shared with VERIFY
    # (handover-lines, residual-queue) are the declared exceptions — they judge the new handover.
    interactive = {" ".join(g.cmd) for g in wrap_gates.GATHER + wrap_gates.VERIFY}
    moved = {" ".join(g.cmd) for g in wrap_gates.NIGHTLY if g.name not in ("handover-lines", "residual-queue")}
    assert moved and not (moved & interactive), f"#4262: moved to nightly but still in the wrap battery: {sorted(moved & interactive)}"
    for left_out in ("proportionality-ledger", "alarm-citations"):
        assert re.search(rf"{left_out}\s+NOT a leg", text), f"{left_out} must be named, with its reason, as deliberately left out"
