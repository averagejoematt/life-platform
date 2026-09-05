"""tests/test_janitor_event_hook_3422.py — the janitor's event hook + its idempotent
rejection (#3422, the reopened leg).

THE FINDING: `deploy-wedge-watch.yml`'s `*/15` cron — the carrier #3440 pinned the
reject-only steward to — measured over its 60 newest scheduled runs (2026-08-26 →
2026-09-04): inter-run gap median 211 min, p90 417 min, max 729 min, 58 of 59 gaps
> 30 min, zero gaps ≤ 15 min. GitHub delays and drops high-frequency crons as a class,
so the design's Outcome sentence ("rejected mechanically within minutes") could never be
met by that trigger. The janitor now lives in `deploy-gate-janitor.yml`, fired by the
`deployment_status` event GitHub mints when a run parks `waiting` at the production gate
(proof in that file's header: real run 33898072296 / deployment 6269244369, 2026-09-04),
with the cron kept as the dead-man.

TWO CONTRACTS PINNED HERE, EACH WITH ITS NEGATIVE CONTROL:

1. THE TRIGGER BLOCK IS BOTH HALVES. The workflow's `on:` block must carry the proven
   event (`deployment_status`, filtered to `state == 'waiting'` at the job) AND the cron.
   Deleting either reds (the hook alone loses the dead-man; the cron alone is the ~3.5h
   cadence the issue was reopened on). The checker is a pure function run on the REAL
   file and on planted mutants of it — guard the set, not the instance (#3318).
   Plus the composition rules: the janitor is the ONLY carrier (`--janitor` must not
   remain in deploy-wedge-watch.yml, or the concurrency group covers half the sweeps),
   the concurrency group exists and never cancels in progress, and the cron has a
   ruling in scripts/scheduled_workflow_registry.py.

2. `reject_lease` IS IDEMPOTENT ON "ALREADY DISPOSED", LOUD ON A GENUINE ERROR. Two
   sweeps can now race on one lease (hook + cron, or either + a hand steward). The
   already-disposed verdict is decided STRUCTURALLY — an empty pending_deployments on
   read, or on re-read after a failed POST — never by matching the error message. A
   401/403 raises regardless (the credential is wrong; the next sweep will not fix it),
   and any other failed POST with the lease still pending raises. The fixtures are the
   wire: `gh api` on failure prints `gh: <message> (HTTP <code>)` to stderr and the JSON
   body to stdout, exit 1 (captured live 2026-09-04: `gh: Not Found (HTTP 404)` /
   `{"message":"Not Found","documentation_url":…,"status":"404"}`).

No test here ever invokes `gh` (same convention as the #3021 and #3440 files).
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "scripts"))

import check_deploy_wedge as cdw  # noqa: E402

_JANITOR_WF = Path(_REPO, ".github", "workflows", "deploy-gate-janitor.yml")
_WATCH_WF = Path(_REPO, ".github", "workflows", "deploy-wedge-watch.yml")

# The proven event and the discriminator the job filters on (see the workflow header).
PROVEN_EVENT = "deployment_status"
PROVEN_STATE = "waiting"
DEAD_MAN_CRON = "*/15 * * * *"


# ---------------------------------------------------------------------------
# 1. The trigger block — a pure checker, run on the real file and on mutants.
# ---------------------------------------------------------------------------


def _uncommented(text: str) -> str:
    return "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))


def check_trigger_block(text: str) -> list[str]:
    """Every rule the janitor workflow's trigger shape must satisfy. Returns the list of
    violations (empty = conforming). Text-based like tests/test_deploy_wedge_2052.py:
    the deploy-critical lane installs no PyYAML (#2732)."""
    body = _uncommented(text)
    problems: list[str] = []
    on_match = re.search(r"^on:\n((?:[ \t]+.*\n?|\n)+)", body, re.M)
    on_block = on_match.group(1) if on_match else ""
    if not re.search(rf"^\s+{re.escape(PROVEN_EVENT)}:\s*$", on_block, re.M):
        problems.append(f"on: block lacks the proven event `{PROVEN_EVENT}` (the fast path)")
    if not re.search(rf"^\s+-\s+cron:\s*['\"]{re.escape(DEAD_MAN_CRON)}['\"]\s*$", on_block, re.M):
        problems.append(f"on: block lacks the dead-man cron `{DEAD_MAN_CRON}`")
    if "workflow_dispatch:" not in on_block:
        problems.append("on: block lacks workflow_dispatch (the on-demand escape hatch)")
    if not re.search(rf"github\.event\.{PROVEN_EVENT}\.state\s*==\s*'{PROVEN_STATE}'", body):
        problems.append(f"no job-level filter on {PROVEN_EVENT}.state == '{PROVEN_STATE}' — every status would spend a runner")
    conc = re.search(r"^concurrency:\n((?:[ \t]+.*\n?)+)", body, re.M)
    if not conc:
        problems.append("no concurrency: group — a hook run and a cron run could dispose the same lease simultaneously")
    else:
        if not re.search(r"^\s+group:\s*\S+", conc.group(1), re.M):
            problems.append("concurrency: block names no group")
        if not re.search(r"^\s+cancel-in-progress:\s*false\s*$", conc.group(1), re.M):
            problems.append("concurrency: must never cancel a sweep in progress (a half-run sweep is a lease left waiting)")
    if "--janitor --apply" not in body:
        problems.append("the reject sweep (`--janitor --apply`) is not invoked")
    if "DEPLOY_GATE_JANITOR_TOKEN" not in body:
        problems.append("the required-reviewer credential is not wired")
    return problems


def test_the_real_workflow_carries_both_halves_and_conforms():
    assert _JANITOR_WF.exists(), "deploy-gate-janitor.yml missing — the janitor has no carrier"
    assert check_trigger_block(_JANITOR_WF.read_text()) == []


def _delete_lines(text: str, needle: str) -> str:
    out = [ln for ln in text.splitlines() if needle not in ln]
    assert len(out) < len(text.splitlines()), f"mutant is a no-op: {needle!r} not found"
    return "\n".join(out) + "\n"


def test_negative_control_deleting_the_event_half_reds():
    mutant = _delete_lines(_JANITOR_WF.read_text(), f"{PROVEN_EVENT}:")
    problems = check_trigger_block(mutant)
    assert any(PROVEN_EVENT in p and "fast path" in p for p in problems), problems


def test_negative_control_deleting_the_cron_half_reds():
    mutant = _delete_lines(_JANITOR_WF.read_text(), "cron:")
    problems = check_trigger_block(mutant)
    assert any("dead-man cron" in p for p in problems), problems


def test_negative_control_widening_the_state_filter_reds():
    # A job that runs on EVERY deployment status (in_progress/success/failure too)
    # spends four runners per deploy for one useful sweep.
    text = _JANITOR_WF.read_text()
    mutant = text.replace(f"github.event.{PROVEN_EVENT}.state == '{PROVEN_STATE}'", "true")
    assert mutant != text
    assert any("job-level filter" in p for p in check_trigger_block(mutant))


def test_negative_control_dropping_the_concurrency_group_reds():
    mutant = _delete_lines(_JANITOR_WF.read_text(), "concurrency:")
    assert any("concurrency" in p for p in check_trigger_block(mutant))


def test_negative_control_cancel_in_progress_true_reds():
    text = _JANITOR_WF.read_text()
    mutant = text.replace("cancel-in-progress: false", "cancel-in-progress: true")
    assert mutant != text
    assert any("never cancel" in p for p in check_trigger_block(mutant))


def test_the_janitor_has_exactly_one_carrier():
    # The concurrency group only serializes runs of ONE workflow. A second copy of the
    # sweep in deploy-wedge-watch.yml (where it lived until 2026-09-04) would run outside
    # the group — and that workflow is forbidden a group of its own (#2052).
    watch = _uncommented(_WATCH_WF.read_text())
    assert "--janitor" not in watch, "deploy-wedge-watch.yml still runs the janitor — two carriers, one concurrency group"
    assert "DEPLOY_GATE_JANITOR_TOKEN" not in watch
    carriers = [wf.name for wf in sorted(Path(_REPO, ".github", "workflows").glob("*.yml")) if "--janitor" in _uncommented(wf.read_text())]
    assert carriers == ["deploy-gate-janitor.yml"], carriers


def test_the_watchdog_still_owns_no_concurrency_group():
    # The reason the janitor is a sibling and not a step: the #2052 rule must survive
    # this change unweakened.
    watch = _uncommented(_WATCH_WF.read_text())
    assert not re.search(r"^\s*concurrency:", watch, re.M)


def test_the_dead_man_cron_has_a_ruling_in_the_scheduled_workflow_registry():
    import scheduled_workflow_registry as swr

    row = swr.WATCH_POLICY.get("deploy-gate-janitor.yml")
    assert row is not None, "a new cron must carry a watched/unwatched ruling (#3213)"
    assert row["watched"] is True
    assert row["grace_hours"] >= 8.0, "grace must be sized from the MEASURED tail (max gap 729 min), not the declared period"


def test_the_workflow_holds_no_aws_and_grants_no_write_beyond_reads():
    body = _uncommented(_JANITOR_WF.read_text())
    assert "aws-role" not in body and "aws-actions" not in body and "AWS_" not in body
    perms = re.search(r"^permissions:\n((?:[ \t]+.*\n?)+)", body, re.M)
    assert perms, "permissions: block missing — the default GITHUB_TOKEN grant is wider than this job needs"
    assert re.search(r"^\s+actions:\s*read\s*$", perms.group(1), re.M)
    assert "write" not in perms.group(1)


# ---------------------------------------------------------------------------
# 2. reject_lease — idempotent on already-disposed, loud on a genuine error.
# ---------------------------------------------------------------------------

_PENDING = [{"environment": {"id": 12797761864, "name": "production"}, "wait_timer": 0, "current_user_can_approve": True}]


def _gh_failure(cmd, code: int, message: str) -> subprocess.CompletedProcess:
    # The wire shape of a failed `gh api` (captured live 2026-09-04 on a 404): stderr
    # `gh: <message> (HTTP <code>)`, stdout the JSON body, exit 1.
    body = json.dumps({"message": message, "documentation_url": "https://docs.github.com/rest", "status": str(code)})
    return subprocess.CompletedProcess(cmd, 1, stdout=body, stderr=f"gh: {message} (HTTP {code})\n")


class _Wire:
    """A scripted pending_deployments endpoint + POST outcome, recording every call."""

    def __init__(self, reads, post=None):
        self.reads = list(reads)  # successive GET results
        self.post = post  # CompletedProcess to return from the POST, or None = success
        self.gets = 0
        self.posts = []

    def gh_api(self, path):
        assert path.endswith("/pending_deployments"), path
        self.gets += 1
        return self.reads.pop(0)

    def run(self, cmd, **kwargs):
        assert "--method" in cmd and "POST" in cmd
        assert kwargs.get("check") is not True, "reject_lease must classify the failure itself, not let check=True raise blind"
        self.posts.append(json.loads(kwargs["input"]))
        return self.post if self.post is not None else subprocess.CompletedProcess(cmd, 0, stdout="{}", stderr="")


def _wire(monkeypatch, reads, post=None) -> _Wire:
    w = _Wire(reads, post)
    monkeypatch.setattr(cdw, "_gh_api", w.gh_api)
    monkeypatch.setattr(cdw.subprocess, "run", w.run)
    return w


def test_happy_path_posts_once_and_reports_rejected(monkeypatch):
    w = _wire(monkeypatch, reads=[_PENDING])
    assert cdw.reject_lease(101, "c") == cdw.LEASE_REJECTED
    assert len(w.posts) == 1 and w.posts[0]["state"] == "rejected"
    assert w.gets == 1


def test_already_disposed_before_the_write_is_success_with_note_and_no_post(monkeypatch):
    # The other sweep (or a hand steward) got there between classify and apply: the
    # lease has left `waiting`, pending_deployments is empty. Pre-#3422 this RAISED and
    # redded the run — a red for an outcome that was already achieved.
    w = _wire(monkeypatch, reads=[[]])
    assert cdw.reject_lease(101, "c") == cdw.LEASE_ALREADY_DISPOSED
    assert w.posts == []


def test_a_failed_post_whose_lease_is_gone_on_reread_is_already_disposed(monkeypatch):
    # The narrower race: both sweeps read `waiting`, the other POSTed first, ours 4xxes.
    # The verdict comes from the RE-READ (structural), not from the message text.
    cmd = ["gh", "api", "x", "--method", "POST"]
    w = _wire(monkeypatch, reads=[_PENDING, []], post=_gh_failure(cmd, 422, "Validation Failed"))
    assert cdw.reject_lease(101, "c") == cdw.LEASE_ALREADY_DISPOSED
    assert len(w.posts) == 1 and w.gets == 2


def test_the_already_disposed_verdict_is_not_phrase_matched(monkeypatch):
    # Same 422, reworded message, lease gone on re-read: still already-disposed. A
    # suppressor keyed on GitHub's wording would fail the day the wording changes
    # (#2959/#3003 class); this one is keyed on the lease.
    cmd = ["gh", "api", "x", "--method", "POST"]
    w = _wire(monkeypatch, reads=[_PENDING, []], post=_gh_failure(cmd, 422, "Deployment review no longer pending"))
    assert cdw.reject_lease(101, "c") == cdw.LEASE_ALREADY_DISPOSED
    assert w.gets == 2


def test_positive_control_a_failed_post_with_the_lease_still_pending_raises(monkeypatch):
    # The POST failed and the lease is STILL there: nothing was achieved; the sweep must red.
    cmd = ["gh", "api", "x", "--method", "POST"]
    _wire(monkeypatch, reads=[_PENDING, _PENDING], post=_gh_failure(cmd, 422, "Validation Failed"))
    with pytest.raises(RuntimeError, match=r"FAILED \(HTTP 422\).*still pending"):
        cdw.reject_lease(101, "c")


@pytest.mark.parametrize("code,message", [(401, "Bad credentials"), (403, "Resource not accessible by integration")])
def test_positive_control_an_auth_refusal_raises_without_consulting_the_lease(monkeypatch, code, message):
    # The credential is wrong. Even if the lease happened to vanish meanwhile, the
    # janitor cannot do its job and the next sweep will not fix it — loud, now. The
    # re-read is never consulted (a second read would be an empty list here, which
    # must NOT convert an auth refusal into success).
    cmd = ["gh", "api", "x", "--method", "POST"]
    w = _wire(monkeypatch, reads=[_PENDING, []], post=_gh_failure(cmd, code, message))
    with pytest.raises(RuntimeError, match=rf"REFUSED \(HTTP {code}\).*required reviewer"):
        cdw.reject_lease(101, "c")
    assert w.gets == 1


def test_a_failure_with_no_parseable_status_and_a_pending_lease_still_raises(monkeypatch):
    # gh died some other way (timeout text, no `(HTTP nnn)`): never silently success.
    cmd = ["gh", "api", "x", "--method", "POST"]
    _wire(monkeypatch, reads=[_PENDING, _PENDING], post=subprocess.CompletedProcess(cmd, 1, stdout="", stderr="gh: connection reset"))
    with pytest.raises(RuntimeError, match=r"FAILED \(HTTP \?\)"):
        cdw.reject_lease(101, "c")


def test_gh_http_status_parses_the_captured_wire_line():
    assert cdw._gh_http_status("gh: Not Found (HTTP 404)\n") == 404
    assert cdw._gh_http_status("gh: Validation Failed (HTTP 422)") == 422
    assert cdw._gh_http_status("") is None
    assert cdw._gh_http_status(None) is None


def test_reject_only_survives_the_idempotency_change():
    # The #3440 structural bound, re-asserted on the new code path: still exactly one
    # writer, still only "rejected".
    src = Path(_REPO, "scripts", "check_deploy_wedge.py").read_text()
    assert re.search(r"""state["']?\s*[:=]\s*["']approved""", src) is None
    assert src.count('"state": "rejected"') == 1


# ---------------------------------------------------------------------------
# 3. The sweep's exit code: already-disposed is 0; a genuine failure is 1.
# ---------------------------------------------------------------------------

OLD_SHA = "1111" + "0" * 36
MID_SHA = "2222" + "0" * 36
NEW_SHA = "3333" + "0" * 36


def _lease(rid, sha, created):
    return {"id": rid, "head_sha": sha, "head_branch": "main", "status": "waiting", "created_at": created}


def _three_waiting_leases(monkeypatch):
    runs = [
        _lease(1, OLD_SHA, "2026-09-04T01:00:00Z"),
        _lease(2, MID_SHA, "2026-09-04T02:00:00Z"),
        _lease(3, NEW_SHA, "2026-09-04T03:00:00Z"),
    ]
    # gate_waiting_leases keys both maps by str(run id) — the shape collect() returns.
    jobs = {str(r["id"]): [{"name": "Deploy", "status": "waiting", "conclusion": None}] for r in runs}
    pending = {str(r["id"]): _PENDING for r in runs}
    monkeypatch.setattr(cdw, "collect", lambda: (runs, jobs, pending))
    monkeypatch.setattr(cdw, "_deployed_superseders", lambda min_created: [])
    monkeypatch.setattr(cdw, "_compare_is_descendant", lambda older, newer: True)


def test_sweep_exits_0_when_one_lease_was_rejected_and_the_other_already_disposed(monkeypatch, capsys):
    _three_waiting_leases(monkeypatch)
    outcomes = {1: cdw.LEASE_ALREADY_DISPOSED, 2: cdw.LEASE_REJECTED}
    monkeypatch.setattr(cdw, "reject_lease", lambda rid, comment: outcomes[rid])
    assert cdw.janitor(apply=True) == 0
    out = capsys.readouterr().out
    assert "ALREADY DISPOSED run 1" in out
    assert "REJECTED run 2" in out
    assert "run 3" in out and "never touched" in out


def test_sweep_exits_1_when_a_rejection_genuinely_fails(monkeypatch, capsys):
    _three_waiting_leases(monkeypatch)

    def reject(rid, comment):
        if rid == 1:
            raise RuntimeError("rejection of run 1 REFUSED (HTTP 403): gh: Resource not accessible (HTTP 403)")
        return cdw.LEASE_REJECTED

    monkeypatch.setattr(cdw, "reject_lease", reject)
    assert cdw.janitor(apply=True) == 1
    out = capsys.readouterr().out
    assert "FAILED to reject run 1" in out and "HTTP 403" in out
    assert "REJECTED run 2" in out  # the failure did not stop the sweep
