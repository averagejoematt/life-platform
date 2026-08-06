"""tests/test_check_ci_warnings.py — regression guard for the #1966 /wrap
standing-warning triage gate (scripts/check_ci_warnings.py).

Proves, with synthetic input, that:
  * a `::warning::` annotation on the latest green main run is flagged (the
    negative test — the gate must actually bite);
  * a green run with NO annotations is silent;
  * a non-"warning" annotation level (e.g. "notice"/"failure") is not flagged —
    this gate is scoped to `::warning::` only;
  * a check run with `annotations_count == 0` is skipped without even being
    asked for its (empty) annotations list;
  * the newest completed run NOT being green reads as "nothing to triage yet",
    not as an error — that's check_main_green.py's job;
  * cancelled/in-progress runs are skipped when picking the newest completed run
    (mirrors check_main_green.py's latest_completed_run semantics);
  * the render()/main() contract matches check_main_green.py's decode shape
    (untriaged -> exit 1; --decoded -> exit 0 with an acknowledgement line);
  * GitHub-unreachable degrades honestly (never crashes, never reports a false
    clean board) — no live `gh`/network required anywhere in this file;
  * the /wrap driver actually wires the gate (a script nobody invokes isn't a gate).
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import check_ci_warnings as ccw  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _run(id_, name, annotations_count):
    return {"id": id_, "name": name, "output": {"annotations_count": annotations_count}}


# ── warning_annotations() — pure filtering logic ────────────────────────────


def test_warning_level_annotation_is_flagged():
    check_runs = [_run(1, "test / Unit Tests", 1)]
    annotations_by_id = {1: [{"annotation_level": "warning", "title": "Over budget", "message": "649s over 480s"}]}
    out = ccw.warning_annotations(check_runs, annotations_by_id)
    assert out == [("test / Unit Tests", "Over budget", "649s over 480s")]


def test_no_annotations_is_silent():
    check_runs = [_run(1, "test / Unit Tests", 0)]
    out = ccw.warning_annotations(check_runs, annotations_by_id={})
    assert out == []


def test_zero_count_run_never_queried_for_annotations():
    """A check run with annotations_count == 0 must not even be looked up in the
    injected mapping — proves the caller can skip the live fetch for it too."""
    check_runs = [_run(1, "test / Unit Tests", 0)]
    # Deliberately supply a warning under id 1 to prove it's ignored because the
    # run's own annotations_count says there's nothing to fetch.
    annotations_by_id = {1: [{"annotation_level": "warning", "title": "should not appear", "message": "x"}]}
    out = ccw.warning_annotations(check_runs, annotations_by_id)
    assert out == []


def test_non_warning_levels_are_not_flagged():
    check_runs = [_run(1, "Plan deployments", 2)]
    annotations_by_id = {
        1: [
            {"annotation_level": "notice", "title": "n", "message": "informational"},
            {"annotation_level": "failure", "title": "f", "message": "a real failure, not this gate's job"},
        ]
    }
    out = ccw.warning_annotations(check_runs, annotations_by_id)
    assert out == []


def test_mixed_runs_flags_only_the_warning_annotations():
    check_runs = [_run(1, "Smoke test", 1), _run(2, "test / Unit Tests", 1), _run(3, "Lint", 0)]
    annotations_by_id = {
        1: [{"annotation_level": "notice", "title": "n", "message": "ignore me"}],
        2: [{"annotation_level": "warning", "title": "Unit Tests job is over its duration budget", "message": "649s over 480s"}],
    }
    out = ccw.warning_annotations(check_runs, annotations_by_id)
    assert out == [("test / Unit Tests", "Unit Tests job is over its duration budget", "649s over 480s")]


# ── latest_green_main_info() semantics (mirrors check_main_green.py) ───────


def test_latest_green_main_info_skips_cancelled_and_in_progress(monkeypatch):
    runs = [
        {"status": "completed", "conclusion": "cancelled", "headSha": "aaa111"},
        {"status": "in_progress", "conclusion": "", "headSha": "bbb222"},
        {"status": "completed", "conclusion": "success", "headSha": "ccc333"},
    ]
    monkeypatch.setattr(ccw, "_gh_json", lambda args: runs)
    sha, err = ccw.latest_green_main_info()
    assert (sha, err) == ("ccc333", None)


def test_latest_green_main_info_not_green_reads_as_no_sha_no_error(monkeypatch):
    runs = [{"status": "completed", "conclusion": "failure", "headSha": "ddd444"}]
    monkeypatch.setattr(ccw, "_gh_json", lambda args: runs)
    sha, err = ccw.latest_green_main_info()
    assert (sha, err) == (None, None)


def test_latest_green_main_info_gh_failure_degrades_to_error(monkeypatch):
    def _boom(args):
        raise RuntimeError("gh: command not found")

    monkeypatch.setattr(ccw, "_gh_json", _boom)
    sha, err = ccw.latest_green_main_info()
    assert sha is None
    assert err is not None and "command not found" in err


# ── render() — exit-code + message contract (mirrors check_main_green.py) ──


def test_render_untriaged_warning_is_gate_failure():
    code, message = ccw.render([("test / Unit Tests", "Over budget", "649s over 480s")], sha="abcd1234", unreachable_error=None)
    assert code == 1
    assert "test / Unit Tests" in message
    assert "649s over 480s" in message


def test_render_clean_green_run_is_ok():
    code, message = ccw.render([], sha="abcd1234", unreachable_error=None)
    assert code == 0
    assert "no ::warning::" in message


def test_render_not_green_yet_is_ok_and_informational():
    code, message = ccw.render([], sha=None, unreachable_error=None)
    assert code == 0
    assert "check_main_green.py owns that" in message


def test_render_unreachable_degrades_honestly_not_a_false_clean():
    code, message = ccw.render([], sha=None, unreachable_error="gh: not authenticated")
    assert code == 0
    assert "UNVERIFIED" in message
    assert "unreachable" in message.lower()


# ── main()/CLI — --decoded contract, no live gh/network required ───────────


def test_main_exits_nonzero_on_untriaged_and_zero_with_decoded(monkeypatch, capsys):
    monkeypatch.setattr(ccw, "latest_green_main_info", lambda: ("abcd1234", None))
    monkeypatch.setattr(ccw, "fetch_warnings_for_sha", lambda sha: ([("test / Unit Tests", "t", "649s over 480s")], None))

    monkeypatch.setattr(sys, "argv", ["check_ci_warnings.py"])
    assert ccw.main() == 1
    out = capsys.readouterr().out
    assert "649s over 480s" in out

    monkeypatch.setattr(sys, "argv", ["check_ci_warnings.py", "--decoded"])
    assert ccw.main() == 0
    out = capsys.readouterr().out
    assert "--decoded acknowledged" in out


def test_main_clean_board_exits_zero(monkeypatch):
    monkeypatch.setattr(ccw, "latest_green_main_info", lambda: ("abcd1234", None))
    monkeypatch.setattr(ccw, "fetch_warnings_for_sha", lambda sha: ([], None))
    monkeypatch.setattr(sys, "argv", ["check_ci_warnings.py"])
    assert ccw.main() == 0


def test_main_not_green_yet_exits_zero_without_fetching_warnings(monkeypatch):
    monkeypatch.setattr(ccw, "latest_green_main_info", lambda: (None, None))

    def _should_not_be_called(sha):
        raise AssertionError("fetch_warnings_for_sha must not be called when main isn't green")

    monkeypatch.setattr(ccw, "fetch_warnings_for_sha", _should_not_be_called)
    monkeypatch.setattr(sys, "argv", ["check_ci_warnings.py"])
    assert ccw.main() == 0


def test_main_gh_unreachable_never_crashes_and_exits_zero(monkeypatch):
    monkeypatch.setattr(ccw, "latest_green_main_info", lambda: (None, "gh: not authenticated"))
    monkeypatch.setattr(sys, "argv", ["check_ci_warnings.py"])
    assert ccw.main() == 0


# ── fetch_warnings_for_sha() — real function, but any failure must degrade ──


def test_fetch_warnings_for_sha_degrades_on_any_exception(monkeypatch):
    def _boom(args):
        raise RuntimeError("HTTP 403: rate limited")

    monkeypatch.setattr(ccw, "_gh_json", _boom)
    warnings, err = ccw.fetch_warnings_for_sha("abcd1234")
    assert warnings == []
    assert err is not None and "rate limited" in err


# ── the /wrap driver actually wires this gate ───────────────────────────────


def test_wrap_skill_wires_the_gate():
    with open(os.path.join(REPO, ".claude", "commands", "wrap.md"), encoding="utf-8") as f:
        wrap = f.read()
    assert "check_ci_warnings.py" in wrap
    assert "**CI warnings:**" in wrap
