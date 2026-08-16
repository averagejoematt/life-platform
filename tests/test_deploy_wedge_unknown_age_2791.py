"""tests/test_deploy_wedge_unknown_age_2791.py — a missing timestamp must not read as
"0 hours parked" (#2791).

From the #2639 flag-precision adjudication: `check_deploy_wedge.py`'s `_parse_iso`
returns `None` on a missing/unparseable timestamp, and `wait_h = (blocked_min or 0.0) /
60.0` (the waiting-gate branch) silently coerced that `None` to 0.0 hours — reading as a
freshly-parked, healthy-looking wait forever. That disarmed the #2467 stale-holder
detection for exactly the malformed-data case most likely to accompany a wedged state.
The same shape sat in the holder loop, where the stale check required `h_min is not
None` and silently fell through to "not stale" (a bare id, no age note) when it was
`None`.

The fix adds an explicit `UNKNOWN_AGE` verdict kind that is reported — never silently
folded into "normal" — and is at least as loud as `STRANDED_APPROVAL` (exit 1, alertable)
per the acceptance bar.

Mutation evidence (documented, not re-run here — see the PR description): the pre-fix
`_check_deploy_wedge.py` classified the exact `test_missing_started_at_is_unknown_age_
not_healthy` fixture below as `AWAITING_APPROVAL` (blocked_minutes=None, wait_h=0.0) with
exit code 0 — i.e. it passed silently as the normal post-merge state. Verified by
importing `origin/main`'s pre-fix module under a separate name and running the same
fixture through it; see PR body for the transcript.
"""

import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import check_deploy_wedge as cdw  # noqa: E402

NOW = datetime(2026, 8, 16, 18, 0, tzinfo=timezone.utc)


def _run(run_id, status="pending", head_branch="main"):
    return {
        "id": run_id,
        "status": status,
        "head_branch": head_branch,
        "head_sha": "ab" * 20,
        "created_at": "2026-08-16T17:00:00Z",
    }


def _waiting_gate_fleet(started_at):
    """One in-flight run whose Deploy job is `waiting` at the gate with the given
    (possibly None/malformed) started_at. Mirrors the real `awaiting_approval` fixture
    shape but with a single knob so each test varies exactly one thing."""
    run_id = 90000001
    runs = [_run(run_id, status="pending")]
    job = {"name": cdw.DEPLOY_JOB, "status": "waiting", "conclusion": None}
    if started_at is not None:
        job["started_at"] = started_at
    jobs_by_run = {str(run_id): [job]}
    pending_by_run = {str(run_id): [{"environment": {"name": "production"}, "current_user_can_approve": True}]}
    return runs, jobs_by_run, pending_by_run, run_id


# --------------------------------------------------------------------------
# Acceptance bullet 1: a missing/unparseable stamp is an explicit unknown-age
# state, reported — never "normal".
# --------------------------------------------------------------------------


def test_missing_started_at_is_unknown_age_not_healthy():
    """No `started_at` key at all — the shape a malformed API response would take."""
    runs, jobs_by_run, pending_by_run, run_id = _waiting_gate_fleet(started_at=None)
    state = cdw.classify_fleet(runs, jobs_by_run, pending_by_run, now=NOW)
    assert state["kind"] == cdw.UNKNOWN_AGE
    v = state["verdicts"][0]
    assert v["run_id"] == run_id
    assert v["blocked_minutes"] is None
    assert "missing or unparseable" in v["detail"]
    assert "AT LEAST as urgent" in v["detail"]


def test_unparseable_started_at_is_also_unknown_age():
    """A malformed timestamp string must classify identically to a missing one —
    `_parse_iso` returns None for both, and the fix must not special-case only absence."""
    runs, jobs_by_run, pending_by_run, run_id = _waiting_gate_fleet(started_at="not-a-real-timestamp")
    state = cdw.classify_fleet(runs, jobs_by_run, pending_by_run, now=NOW)
    assert state["kind"] == cdw.UNKNOWN_AGE
    assert state["verdicts"][0]["blocked_minutes"] is None


def test_unknown_age_exits_nonzero_same_as_stranded():
    """The whole point: this must page a human, not read as exit 0 'normal'."""
    runs, jobs_by_run, pending_by_run, _ = _waiting_gate_fleet(started_at=None)
    state = cdw.classify_fleet(runs, jobs_by_run, pending_by_run, now=NOW)
    code, message = cdw.render(state)
    assert code == 1
    assert "UNKNOWN-AGE" in message


def test_unknown_age_is_an_alertable_kind():
    """(#2149) unknown-age must not be a quieter, informational-only path — it has to
    trigger the SAME urgent-alarm channel as a confirmed stale holder."""
    assert cdw.UNKNOWN_AGE in cdw.ALERT_KINDS


def test_unknown_age_is_at_least_as_severe_as_stranded_approval():
    """Ordering invariant behind 'at least as loud as stale': UNKNOWN_AGE must not
    rank below STRANDED_APPROVAL in the worst-first severity list."""
    assert cdw._SEVERITY.index(cdw.UNKNOWN_AGE) >= cdw._SEVERITY.index(cdw.STRANDED_APPROVAL)


# --------------------------------------------------------------------------
# The control: a fresh, valid, recent timestamp must stay quiet.
# --------------------------------------------------------------------------


def test_fresh_valid_timestamp_stays_quiet():
    """A normal, recently-parked gate wait must classify as ordinary AWAITING_APPROVAL —
    no unknown-age, no stale alarm. Proves the fix is not over-eager."""
    fresh = "2026-08-16T17:58:00Z"  # 2 minutes before NOW
    runs, jobs_by_run, pending_by_run, _ = _waiting_gate_fleet(started_at=fresh)
    state = cdw.classify_fleet(runs, jobs_by_run, pending_by_run, now=NOW)
    assert state["kind"] == cdw.AWAITING_APPROVAL
    code, _ = cdw.render(state)
    assert code == 0
    v = state["verdicts"][0]
    assert v["blocked_minutes"] == 2.0
    assert v.get("stale_holder") is not True


# --------------------------------------------------------------------------
# Acceptance bullet 2: the holder loop (:287-289) treats h_min is None as
# unknown-age, not as "not stale".
# --------------------------------------------------------------------------


def _blocked_behind_unknown_age_holder():
    """A QUEUED_BEHIND shape: run B is blocked behind holder A, and A's Deploy job is
    `waiting` at the gate with NO started_at — the exact shape from :287-289."""
    holder_id = 90000002
    blocked_id = 90000003
    runs = [
        _run(holder_id, status="pending"),
        _run(blocked_id, status="pending"),
    ]
    holder_job = {"name": cdw.DEPLOY_JOB, "status": "waiting", "conclusion": None}  # no started_at
    blocked_job = {"name": cdw.DEPLOY_JOB, "status": "pending", "conclusion": None, "started_at": "2026-08-16T17:00:00Z"}
    jobs_by_run = {str(holder_id): [holder_job], str(blocked_id): [blocked_job]}
    pending_by_run = {str(holder_id): [], str(blocked_id): []}
    return runs, jobs_by_run, pending_by_run, holder_id, blocked_id


def test_holder_with_unknown_age_is_not_silently_read_as_not_stale():
    runs, jobs_by_run, pending_by_run, holder_id, blocked_id = _blocked_behind_unknown_age_holder()
    state = cdw.classify_fleet(runs, jobs_by_run, pending_by_run, now=NOW, threshold_min=1.0)
    by_id = {v["run_id"]: v for v in state["verdicts"]}

    # The blocked run's own detail must name the holder as UNKNOWN AGE, not as a bare id
    # (the old `else: descs.append(str(hid))` fallback) and not silently omit it.
    blocked = by_id[blocked_id]
    assert blocked["kind"] == cdw.QUEUED_BEHIND
    assert "UNKNOWN AGE" in blocked["detail"]
    assert str(holder_id) in blocked["detail"]

    # The holder itself — independently classified — must be UNKNOWN_AGE, not a quiet
    # AWAITING_APPROVAL. This is what makes the fleet verdict page a human.
    holder = by_id[holder_id]
    assert holder["kind"] == cdw.UNKNOWN_AGE

    # Fleet-level: unknown-age must dominate (it outranks queued-behind).
    assert state["kind"] == cdw.UNKNOWN_AGE
    code, _ = cdw.render(state)
    assert code == 1
