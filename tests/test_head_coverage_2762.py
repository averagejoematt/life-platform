"""#2762 — check_main_green must vouch for the sha main actually points at.

The swallowed-push shape (#2662 class): a push that mints ZERO workflow runs
leaves the newest completed run on an OLDER sha, and the completed-run verdict
reads green against a HEAD nothing ever tested. `latest_completed_run` had no
head_sha comparison at all (`grep -c head_sha` → 0 at filing).
"""

import importlib.util
import os

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("cmg", os.path.join(_REPO, "scripts", "check_main_green.py"))
cmg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cmg)

OLD = {"status": "completed", "conclusion": "success", "headSha": "a" * 40, "databaseId": 1, "createdAt": "2026-08-16T01:00:00Z"}
HEAD = "b" * 40


def test_swallowed_push_reads_uncovered():
    assert cmg.head_coverage([OLD], HEAD)["state"] == "uncovered"


def test_inflight_run_at_head_is_pending_not_uncovered():
    runs = [{"status": "in_progress", "conclusion": None, "headSha": HEAD, "databaseId": 2, "createdAt": "x"}, OLD]
    cov = cmg.head_coverage(runs, HEAD)
    assert cov["state"] == "pending" and cov["pending"]["databaseId"] == 2


def test_completed_run_at_head_is_covered():
    runs = [{"status": "completed", "conclusion": "success", "headSha": HEAD, "databaseId": 3, "createdAt": "x"}]
    assert cmg.head_coverage(runs, HEAD)["state"] == "covered"


def test_cancelled_at_head_does_not_count_as_coverage():
    runs = [{"status": "completed", "conclusion": "cancelled", "headSha": HEAD, "databaseId": 4, "createdAt": "x"}]
    assert cmg.head_coverage(runs, HEAD)["state"] == "pending"


def test_unreadable_head_is_unknown_never_a_verdict():
    assert cmg.head_coverage([OLD], None)["state"] == "unknown"


def test_green_over_uncovered_head_exits_nonzero_and_names_both_shas():
    """#3212 amendment: an uncovered HEAD is only a CONFIRMED swallow once the
    #2826 discriminator says so — the caller now supplies that verdict. The
    #2762 contract itself is unchanged: a green over a HEAD that nothing tested
    still exits 1 and still names both shas."""
    state = cmg.classify_pipeline([OLD])
    state["head_sha"] = HEAD
    state["head_cov"] = cmg.head_coverage([OLD], HEAD)
    state["head_zr"] = {"state": cmg.ZR_SWALLOWED, "reason": "no workflow run of any kind references head_sha"}
    code, msg = cmg.render(state)
    assert code == 1
    assert "swallowed-push" in msg and ("a" * 8) in msg and ("b" * 8) in msg


def test_green_over_an_undiagnosed_uncovered_head_still_exits_nonzero():
    """#3212: without a discriminator verdict the gate knows nothing — it must
    still refuse to declare green (never a silent pass), and must not claim a
    confirmed swallow it did not prove."""
    state = cmg.classify_pipeline([OLD])
    state["head_sha"] = HEAD
    state["head_cov"] = cmg.head_coverage([OLD], HEAD)
    code, msg = cmg.render(state)
    assert code == 1
    assert "swallowed-push" not in msg


def test_green_with_pending_head_still_exits_zero():
    runs = [{"status": "in_progress", "conclusion": None, "headSha": HEAD, "databaseId": 2, "createdAt": "x"}, OLD]
    state = cmg.classify_pipeline(runs)
    state["head_sha"] = HEAD
    state["head_cov"] = cmg.head_coverage(runs, HEAD)
    code, msg = cmg.render(state)
    assert code == 0 and "in flight" in msg


def test_green_covered_is_untouched():
    runs = [{"status": "completed", "conclusion": "success", "headSha": HEAD, "databaseId": 3, "createdAt": "x"}]
    state = cmg.classify_pipeline(runs)
    state["head_sha"] = HEAD
    state["head_cov"] = cmg.head_coverage(runs, HEAD)
    code, msg = cmg.render(state)
    assert code == 0 and "swallowed" not in msg
