#!/usr/bin/env python3
"""tests/test_cron_freshness_3213.py — the dead-man for GitHub's cron scheduler (#3213,
epic #2799).

WHAT IS BEING GUARDED, AND WHY IT NEEDS MUTATION PROOFS MORE THAN MOST
----------------------------------------------------------------------
The subject under test is a watcher whose entire job is detecting an ABSENCE. That is
the exact shape this repo has shipped broken most often — "a SILENT pass == a check that
never ran" (#1994), "#3200 shipped verdict-closed with 60 green tests and was
non-functional" (#3209), "two watchers had NEVER worked" (Session A). A broken
absence-detector looks identical to a working one from outside: both say nothing.

So every gate below is shown FAILING on a planted defect, and every "is reported" test
has an "and this one is not" twin. A one-directional proof would demonstrate only that
the function returns something.

  D1  cron cadence is DERIVED exactly (and a naive derivation is shown getting it wrong)
  D2  registry completeness, BOTH directions (unruled workflow / orphaned policy row)
  B2  the watcher's own workflow does not share the trigger it watches
  B3  "fired and failed" is structurally outside this instrument's reach
  B4  stale IS reported / in-window is NOT — the headline mutation pair
  I*  the instrument can say "I could not look" instead of "clean"
  M*  mutation proofs for each of the above

Run:  python3 -m pytest tests/test_cron_freshness_3213.py -v

v1.0.0 — 2026-08-27 (#3213, epic #2799)
"""

from __future__ import annotations

import importlib.util
import inspect
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SCRIPTS = os.path.join(ROOT, "scripts")
WORKFLOW_DIR = os.path.join(ROOT, ".github", "workflows")
WATCHER_WORKFLOW = os.path.join(WORKFLOW_DIR, "cron-freshness.yml")

if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

yaml = pytest.importorskip("yaml", reason="PyYAML parses the workflow documents under test")


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"{name}_3213", os.path.join(SCRIPTS, f"{name}.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


reg = _load("scheduled_workflow_registry")
watch = _load("check_cron_freshness")

NOW = datetime(2026, 8, 27, 4, 0, tzinfo=timezone.utc)


def _ago(hours: float) -> str:
    return (NOW - timedelta(hours=hours)).isoformat().replace("+00:00", "Z")


def _synthetic_workflow(directory, filename: str, cron: str | None, name: str = "Synthetic") -> None:
    sched = f"on:\n  schedule:\n    - cron: '{cron}'\n" if cron else "on:\n  push:\n    branches: [main]\n"
    (directory / filename).write_text(
        f"name: {name}\n\n{sched}\njobs:\n  j:\n    runs-on: ubuntu-latest\n    steps:\n      - run: 'true'\n", encoding="utf-8"
    )


# ═════════════════════════════════════════════════════════════════════════════
# D1 — the cadence is derived from the workflow's own cron, exactly
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize(
    "expr,expected_hours,why",
    [
        ("7 20 * * *", 24.0, "daily"),
        ("*/15 * * * *", 0.25, "every 15 minutes"),
        ("0 15 * * 0", 168.0, "weekly on Sunday — cron dow 0"),
        ("13 12 * * 6", 168.0, "weekly on Saturday"),
        ("0 15 * * 7", 168.0, "weekly on Sunday spelled as dow 7 (cron's second Sunday)"),
        ("45 14 * * 1,3,5", 72.0, "Mon/Wed/Fri — the worst gap is Fri->Mon, not 48h"),
        ("23 16 3 * *", 744.0, "monthly on the 3rd — 31 days, not 30"),
        ("0 0,12 * * *", 12.0, "twice daily — the intra-day hole governs"),
    ],
)
def test_d1_cron_cadence_is_derived_exactly(expr, expected_hours, why):
    assert reg.cron_max_gap_hours(expr) == pytest.approx(expected_hours), why


def test_d1m_a_naive_daily_assumption_would_be_wrong_here():
    """MUTATION PROOF for D1: the derivation is load-bearing, not decoration.

    Hand-declaring "remediation-agent is roughly daily" (the hand-list this issue exists
    to eliminate) understates its worst legitimate silence by 3x — a watcher built on it
    would report a healthy weekend as a stopped cron every single week.
    """
    derived = reg.cron_max_gap_hours("45 14 * * 1,3,5")
    naive_daily = 24.0
    assert derived == 72.0
    assert derived != naive_daily
    # And the dom/dow OR semantics. `0 0 1 * 1` is "the 1st OR any Monday" — the weekly
    # Mondays hold the worst gap at 168h. An AND reading ("the 1st, only when it lands
    # on a Monday") fires a handful of times a year and would derive a gap of many
    # months, so a watcher built on it would stay silent through an outage that lasted
    # most of a year.
    both_restricted = reg.cron_max_gap_hours("0 0 1 * 1")
    assert both_restricted == pytest.approx(
        168.0
    ), "dom and dow both set must mean 'the 1st OR any Monday', not 'the 1st if it is a Monday'"
    assert both_restricted < 1000.0


def test_d1_a_malformed_cron_raises_rather_than_defaulting():
    for bad in ["7 20 * *", "99 20 * * *", "7 20 * * 9", ""]:
        with pytest.raises(ValueError):
            reg.cron_max_gap_hours(bad)


def test_d1_the_real_workflows_all_derive_a_cadence():
    rows = reg.discover_scheduled_workflows()
    assert (
        len(rows) >= reg.SCHEDULED_WORKFLOW_FLOOR
    ), f"derivation found only {len(rows)} scheduled workflows — below the population floor; it has gone blind"
    for name, row in rows.items():
        assert row["crons"], f"{name} was classified scheduled with no cron"
        assert row["cadence_hours"] > 0, f"{name} derived a non-positive cadence"


# ═════════════════════════════════════════════════════════════════════════════
# D2 — registry completeness, both directions (#3213 box 5)
# ═════════════════════════════════════════════════════════════════════════════


def test_d2_every_scheduled_workflow_carries_a_ruling():
    unruled = reg.unruled_workflows()
    assert not unruled, (
        f"{unruled} have a `cron:` and no row in WATCH_POLICY. Silence about a scheduled "
        "workflow is not a ruling (#3213 box 5) — add watched=True with a grace window, or "
        "watched=False with the reason it is safe to lose."
    )


def test_d2_no_policy_row_rules_on_a_workflow_that_is_gone():
    orphaned = reg.orphaned_policy_rows()
    assert not orphaned, f"WATCH_POLICY rules on {orphaned}, which no longer has a `cron:` — that reads as coverage it does not have"


def test_d2_every_row_carries_its_argument():
    for name, row in reg.WATCH_POLICY.items():
        assert (row.get("reason") or "").strip(), f"{name} has no reason"
        assert len(row["reason"]) > 60, f"{name}'s reason is too thin to be a ruling: {row['reason']!r}"
        if row["watched"]:
            assert isinstance(row.get("grace_hours"), (int, float)), f"{name} is watched with no grace window"
            assert (
                row.get("basis") or ""
            ).strip(), f"{name}'s grace window has no stated basis — ADR-105 forbids a number with no derivation"
        else:
            assert row.get("grace_hours") is None, f"{name} is unwatched but carries a grace window — one of the two is wrong"
            assert "RE-RULE IF" in row["reason"], f"{name} is deliberately unwatched with no stated condition for revisiting the ruling"


def test_d2m_an_unruled_workflow_is_reported(tmp_path):
    """MUTATION PROOF for D2, direction 1: plant a scheduled workflow with no ruling."""
    _synthetic_workflow(tmp_path, "visual-qa.yml", "7 20 * * *")  # ruled
    assert reg.unruled_workflows(str(tmp_path)) == []
    _synthetic_workflow(tmp_path, "synthetic-unruled-3213.yml", "0 3 * * *")  # not ruled
    assert reg.unruled_workflows(str(tmp_path)) == ["synthetic-unruled-3213.yml"]


def test_d2m_a_ruling_on_a_vanished_workflow_is_reported(tmp_path):
    """MUTATION PROOF for D2, direction 2: a workflow dir missing most ruled files."""
    _synthetic_workflow(tmp_path, "visual-qa.yml", "7 20 * * *")
    orphaned = reg.orphaned_policy_rows(str(tmp_path))
    assert "visual-qa.yml" not in orphaned
    assert "operating-calendar.yml" in orphaned and len(orphaned) == len(reg.WATCH_POLICY) - 1


def test_d2m_a_workflow_that_loses_its_cron_becomes_orphaned(tmp_path):
    """The rot that matters most: the file still exists, but the `schedule:` was removed."""
    _synthetic_workflow(tmp_path, "visual-qa.yml", None)  # push-only now
    assert "visual-qa.yml" in reg.orphaned_policy_rows(str(tmp_path))
    assert "visual-qa.yml" not in reg.discover_scheduled_workflows(str(tmp_path))


# ═════════════════════════════════════════════════════════════════════════════
# B4 — stale IS reported, in-window is NOT. The headline mutation pair.
# ═════════════════════════════════════════════════════════════════════════════


def test_b4_a_stale_scheduled_run_is_reported():
    verdict, age = watch.classify(_ago(40.0), deadline_hours=38.0, now=NOW)
    assert verdict == watch.STALE and age == pytest.approx(40.0)


def test_b4_a_run_inside_its_window_is_not_reported():
    verdict, age = watch.classify(_ago(11.7), deadline_hours=38.0, now=NOW)
    assert verdict == watch.OK and age == pytest.approx(11.7)


def test_b4_the_boundary_is_the_deadline_itself():
    assert watch.classify(_ago(38.0), 38.0, NOW)[0] == watch.OK
    assert watch.classify(_ago(38.01), 38.0, NOW)[0] == watch.STALE


def test_b4m_the_pair_moves_together_end_to_end():
    """MUTATION PROOF for B4 at the render level — exit code, not just a verdict string.

    The pre-fix state this pins: with visual-qa's real cadence and grace, a run 40h old
    must exit 1 and a run 5h old must exit 0. If `render` ever loses its stale branch,
    the first assertion fails; if it starts reporting healthy rows, the second does.
    """
    rows = {
        "visual-qa.yml": {
            "watched": True,
            "name": "Visual QA (standalone)",
            "crons": ["7 20 * * *"],
            "cadence_hours": 24.0,
            "grace_hours": 14.0,
            "deadline_hours": 38.0,
        }
    }
    stale_code, stale_report = watch.render(watch.evaluate(rows, {"visual-qa.yml": _ago(40.0)}, NOW), [], [], 11)
    assert stale_code == 1 and "STALE" in stale_report

    ok_code, ok_report = watch.render(watch.evaluate(rows, {"visual-qa.yml": _ago(5.0)}, NOW), [], [], 11)
    assert ok_code == 0 and "STALE" not in ok_report


def test_b4_never_fired_is_its_own_verdict_not_merely_stale():
    """#3213 box 3, half one: 'the cron has never once been delivered' is a different
    defect from 'it stopped' — nothing will ever auto-close it, and the fix is a cron
    expression or a disabled workflow, not a retry."""
    verdict, age = watch.classify(None, deadline_hours=38.0, now=NOW)
    assert verdict == watch.NEVER_FIRED and age is None
    assert watch.NEVER_FIRED != watch.STALE


# ═════════════════════════════════════════════════════════════════════════════
# B3 — "fired and failed" is structurally outside this instrument (#3213 box 3)
# ═════════════════════════════════════════════════════════════════════════════


def test_b3_classify_cannot_see_a_conclusion():
    """The signature IS the non-duplication guarantee.

    scripts/advisory_failure_issue.py owns a run that failed. If `classify` ever grows a
    `conclusion` parameter, the two instruments have started overlapping and this repo
    gets a second copy of an existing classification — which is literally how #3212
    happened.
    """
    params = set(inspect.signature(watch.classify).parameters)
    assert params == {"newest_created_at", "deadline_hours", "now"}, f"classify grew a parameter: {sorted(params)}"
    assert "conclusion" not in params


def test_b3_a_recent_failed_run_is_ok_here():
    """Behavioural twin of the signature proof, on a real observed row.

    webkit-mobile-qa's newest scheduled run on 2026-08-27 concluded `failure` and was
    ~30h old against a weekly cadence. That is the advisory filer's problem. This
    instrument must be silent about it — a second issue filed for the same red is spam
    that trains the operator to ignore the channel.
    """
    assert watch.classify(_ago(30.0), deadline_hours=192.0, now=NOW)[0] == watch.OK


def test_b3_the_watcher_files_under_its_own_slug():
    text = open(WATCHER_WORKFLOW, encoding="utf-8").read()
    assert "advisory-failure-issue" in text, "the watcher must reuse the #1447 filer, not grow a second issue-filing path"
    assert "workflow-slug: cron-freshness" in text
    # The slug is the filer's dedup key. Colliding with a watched workflow's slug would
    # make this instrument close (or comment on) that workflow's own auto-filed issue.
    for other in ("visual-qa-standalone", "golden-brief-eval", "fresh-eyes"):
        assert f"workflow-slug: {other}" not in text


# ═════════════════════════════════════════════════════════════════════════════
# B2 — the watcher does not share the trigger it watches (#3213 box 2)
# ═════════════════════════════════════════════════════════════════════════════


def _trigger_names(workflow_text: str) -> set[str]:
    doc = yaml.safe_load(workflow_text) or {}
    triggers = doc.get("on", doc.get(True))
    return set(triggers) if isinstance(triggers, dict) else set()


def test_b2_the_watcher_is_not_itself_on_a_schedule():
    """The load-bearing constraint.

    GitHub silences cron as a CLASS: scheduled runs may be dropped under load, and
    scheduled workflows are auto-disabled after 60 days of repository inactivity. A
    watcher on `schedule` sits inside that blast radius and goes dark with the workflows
    it watches — unable, by construction, to detect its own absence.
    """
    triggers = _trigger_names(open(WATCHER_WORKFLOW, encoding="utf-8").read())
    assert "schedule" not in triggers, "cron-freshness.yml must never trigger on `schedule` — it would go dark with its own subjects"
    assert "push" in triggers, "the watcher needs a repository-event trigger; `push` cannot be silenced by the cron scheduler"


def test_b2m_a_scheduled_watcher_would_be_caught(tmp_path):
    """MUTATION PROOF for B2: plant the defect and show the detector fires.

    Without this, `test_b2_...` only proves that `_trigger_names` returned something.
    """
    good = "name: W\non:\n  push:\n    branches: [main]\n  workflow_dispatch: {}\njobs: {}\n"
    bad = "name: W\non:\n  push:\n    branches: [main]\n  schedule:\n    - cron: '0 6 * * *'\njobs: {}\n"
    assert "schedule" not in _trigger_names(good)
    assert "schedule" in _trigger_names(
        bad
    ), "the trigger detector cannot see a schedule trigger — it would pass the very defect it screens for"


def test_b2_the_watcher_is_not_in_the_registry_it_watches():
    """It has no cron, so it must not appear as a subject — and if someone ever gives it
    one, D2's unruled gate catches that in the same breath."""
    assert "cron-freshness.yml" not in reg.discover_scheduled_workflows()
    assert "cron-freshness.yml" not in reg.WATCH_POLICY


def test_b2_the_watcher_grants_the_permissions_its_two_jobs_need():
    doc = yaml.safe_load(open(WATCHER_WORKFLOW, encoding="utf-8").read())
    perms = doc.get("permissions") or {}
    assert perms.get("actions") == "read", "reading another workflow's run history needs actions:read"
    assert perms.get("issues") == "write", "the #1447 filer needs issues:write or every detection evaporates into the run log"


# ═════════════════════════════════════════════════════════════════════════════
# I* — the instrument can say "I could not look" instead of "clean"
# ═════════════════════════════════════════════════════════════════════════════


def _one_row(deadline: float = 38.0) -> dict:
    return {
        "w.yml": {
            "watched": True,
            "name": "W",
            "crons": ["7 20 * * *"],
            "cadence_hours": 24.0,
            "grace_hours": 14.0,
            "deadline_hours": deadline,
        }
    }


def test_i_a_failed_lookup_is_unverified_not_never_fired():
    """The two must not collapse. `False` = the API call failed; `None` = the API
    answered and the answer was zero runs. A rate-limited run that reported
    `never-fired` on eight healthy workflows would be this instrument inverted.
    """
    assert watch.evaluate(_one_row(), {"w.yml": False}, NOW)[0]["verdict"] == watch.UNVERIFIED
    assert watch.evaluate(_one_row(), {"w.yml": None}, NOW)[0]["verdict"] == watch.NEVER_FIRED
    # A workflow absent from the lookup map entirely is unverified, never assumed green.
    assert watch.evaluate(_one_row(), {}, NOW)[0]["verdict"] == watch.UNVERIFIED


def test_i_a_wholly_blind_run_exits_2_not_0():
    code, report = watch.render(watch.evaluate(_one_row(), {"w.yml": False}, NOW), [], [], 11)
    assert code == 2 and "DARK" in report, "a run that could verify nothing must not report a clean board"


def test_i_a_blind_derivation_exits_2_even_with_no_findings():
    """The vacuous-empty shape, pinned: zero scheduled workflows discovered is a broken
    derivation, not an empty problem set."""
    code, report = watch.render([], [], [], 0)
    assert code == 2 and "DARK" in report


def test_i_a_partial_blindness_still_reports_the_stale_row():
    findings = watch.evaluate(
        {**_one_row(), "x.yml": {**_one_row()["w.yml"], "name": "X"}},
        {"w.yml": False, "x.yml": _ago(99.0)},
        NOW,
    )
    code, report = watch.render(findings, [], [], 11)
    assert code == 1 and "STALE" in report and "could NOT be verified       n = 1" in report


def test_i_registry_drift_alone_reds_the_run():
    code, report = watch.render(watch.evaluate(_one_row(), {"w.yml": _ago(1.0)}, NOW), ["new-thing.yml"], [], 11)
    assert code == 1 and "UNRULED" in report
    code, report = watch.render(watch.evaluate(_one_row(), {"w.yml": _ago(1.0)}, NOW), [], ["gone.yml"], 11)
    assert code == 1 and "ORPHANED" in report


def test_i_a_clean_board_says_so_with_its_population():
    code, report = watch.render(watch.evaluate(_one_row(), {"w.yml": _ago(1.0)}, NOW), [], [], 11)
    assert code == 0
    assert "scheduled workflows found   n = 11" in report and "watched by the registry     n = 1" in report


def test_i_an_unparseable_timestamp_is_unverified_not_ok():
    assert watch.classify("not-a-timestamp", 38.0, NOW)[0] == watch.UNVERIFIED


def test_i_the_two_dark_causes_are_not_downgradable_alike(monkeypatch):
    """`--allow-unverified` covers a blind NETWORK, never a missing parser.

    Measured by hand before this test existed: with `gh` absent the flag turns exit 2
    into 0 (correct — the offline operator chose that at the call site), and with
    PyYAML absent it stays 2 with or without the flag. Without a parser there are no
    subjects and no registry cross-check, so there is no board to opt out of reporting.
    Pinned here so the two paths cannot quietly converge on the permissive one.
    """

    def _no_yaml(*_a, **_k):
        raise ImportError("No module named 'yaml'")

    monkeypatch.setattr(watch, "discover_scheduled_workflows", _no_yaml)
    assert watch.main([]) == 2
    assert watch.main(["--allow-unverified"]) == 2

    # The lookup-blind path, by contrast, IS downgradable.
    monkeypatch.undo()
    monkeypatch.setattr(watch, "newest_scheduled_run", lambda _f: False)
    assert watch.main([]) == 2
    assert watch.main(["--allow-unverified"]) == 0


# ═════════════════════════════════════════════════════════════════════════════
# #3982 — a NEWBORN watched workflow (zero scheduled runs) is judged from its BIRTH
# instant, not from "now". Before this: PR #3976 registered pii-endpoint-sweep.yml
# (cadence 24h, grace 14h) as watched; the very next push-triggered run read its zero
# scheduled runs as an instant `never-fired` — three hours before the sweep's own
# first cron could exist — and auto-filed #3980. #3980's own recovery comment records
# it self-closing at 17:20Z the same day on the workflow's first green scheduled run:
# correct eventually, but a false red for the whole of its own declared grace window.
# ═════════════════════════════════════════════════════════════════════════════


def _newborn_row(deadline_hours: float = 24.0, cadence_hours: float = 24.0, grace_hours: float = 0.0) -> dict:
    return {
        "newborn.yml": {
            "watched": True,
            "name": "Newborn",
            "crons": ["0 0 * * *"],
            "cadence_hours": cadence_hours,
            "grace_hours": grace_hours,
            "deadline_hours": deadline_hours,
        }
    }


def test_3982_a_cron_born_within_the_last_hour_is_not_a_finding():
    """The issue's acceptance, box 1: a workflow file committed 1h ago, cadence 24h —
    inside its first cadence+grace window, zero runs is expected, not a finding."""
    verdict, age = watch.classify_newborn(_ago(1.0), deadline_hours=24.0, now=NOW)
    assert verdict == watch.BORN and age == pytest.approx(1.0)


def test_3982m_the_same_workflow_30h_after_birth_with_no_run_is_a_finding():
    """The issue's must-fail control: once the birth deadline has passed with still
    zero runs, this reports exactly like the pre-#3982 behaviour did for every case."""
    verdict, age = watch.classify_newborn(_ago(30.0), deadline_hours=24.0, now=NOW)
    assert verdict == watch.NEVER_FIRED and age == pytest.approx(30.0)


def test_3982_the_boundary_is_the_birth_deadline_itself():
    assert watch.classify_newborn(_ago(24.0), 24.0, NOW)[0] == watch.BORN
    assert watch.classify_newborn(_ago(24.01), 24.0, NOW)[0] == watch.NEVER_FIRED


def test_3982_an_undiscoverable_birth_is_a_finding_never_a_fresh_one():
    """A zero-run workflow whose file has no `A` commit reachable at all must never be
    treated as recently born — that would report BORN forever and hide a genuinely
    stopped (or renamed-away) cron behind an unfalsifiable green."""
    verdict, age = watch.classify_newborn(None, deadline_hours=24.0, now=NOW)
    assert verdict == watch.NEVER_FIRED and age is None


def test_3982_evaluate_end_to_end_born_vs_the_must_fail_control():
    """The acceptance's exact pair, at the evaluate() level with an injected birth map —
    the boundary a real `main()` run would actually exercise."""
    rows = _newborn_row()

    fresh = watch.evaluate(rows, {"newborn.yml": None}, NOW, {"newborn.yml": _ago(1.0)})
    assert fresh[0]["verdict"] == watch.BORN
    code, report = watch.render(fresh, [], [], 11)
    assert code == 0 and "BORN" in report and "NEVER" not in report

    stale_zero = watch.evaluate(rows, {"newborn.yml": None}, NOW, {"newborn.yml": _ago(30.0)})
    assert stale_zero[0]["verdict"] == watch.NEVER_FIRED
    code2, report2 = watch.render(stale_zero, [], [], 11)
    assert code2 == 1 and "NEVER" in report2


def test_3982_a_zero_run_workflow_with_unknown_birth_reports_the_reason_explicitly():
    """No birth map at all — the shape a caller that forgot to look one up would
    produce. Must read as an explicit 'birth unknown' finding, never silently green."""
    rows = _newborn_row()
    findings = watch.evaluate(rows, {"newborn.yml": None}, NOW)
    assert findings[0]["verdict"] == watch.NEVER_FIRED
    assert findings[0]["newborn_note"] and "birth unknown" in findings[0]["newborn_note"]
    code, report = watch.render(findings, [], [], 11)
    assert code == 1 and "birth unknown" in report


def test_3982_main_prefers_a_declared_registered_at_over_the_git_lookup(monkeypatch, capsys):
    """`main()`'s birth source is the registry's declared `registered_at` FIRST,
    `first_commit_time()` only as a fallback — proven by POISONING the git lookup with
    a value that would flip the verdict if it were ever consulted.

    `main()` reads the REAL wall clock (`datetime.now`), not this module's fixed
    `NOW` — so the birth instant below is computed off the real clock too.
    """
    real_now = datetime.now(timezone.utc)
    registered_at = (real_now - timedelta(hours=1)).isoformat()
    rows = {
        "newborn.yml": {
            "file": "newborn.yml",
            "name": "Newborn",
            "crons": ["0 0 * * *"],
            "cadence_hours": 24.0,
            "watched": True,
            "grace_hours": 0.0,
            "basis": "test",
            "reason": "x" * 70,
            "registered_at": registered_at,
            "deadline_hours": 24.0,
        }
    }
    monkeypatch.setattr(watch, "SCHEDULED_WORKFLOW_FLOOR", 1)
    monkeypatch.setattr(watch, "discover_scheduled_workflows", lambda: dict(rows))
    monkeypatch.setattr(watch, "unruled_workflows", lambda: [])
    monkeypatch.setattr(watch, "orphaned_policy_rows", lambda: [])
    monkeypatch.setattr(watch, "newest_scheduled_run", lambda _f: None)
    monkeypatch.setattr(watch, "scheduled_run_history", lambda _f, per_page=watch.GRACE_HISTORY_SAMPLE: [])
    # Poison: if `main()` ever fell through to the git lookup despite a declared
    # `registered_at`, this ancient birth would flip the verdict to NEVER_FIRED.
    monkeypatch.setattr(watch, "first_commit_time", lambda *_a, **_k: "2000-01-01T00:00:00+00:00")

    assert watch.main([]) == 0
    out = capsys.readouterr().out
    assert "BORN" in out and "NEVER" not in out


_GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.com",
}


def test_3982_first_commit_time_reads_a_real_git_history(tmp_path):
    """End-to-end proof of the IO half: a synthetic git repo with one commit adding the
    workflow file, and `first_commit_time()` must recover THAT commit's own timestamp —
    not 'now', not the repo's most recent commit."""
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / ".github" / "workflows" / "synthetic-3982.yml").write_text(
        "name: Synthetic\non:\n  schedule:\n    - cron: '0 0 * * *'\njobs: {}\n", encoding="utf-8"
    )
    born_at = "2026-09-19T12:00:00+00:00"
    env = {**_GIT_ENV, "GIT_AUTHOR_DATE": born_at, "GIT_COMMITTER_DATE": born_at}
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True, env=env)
    subprocess.run(["git", "commit", "-q", "-m", "add synthetic workflow"], cwd=tmp_path, check=True, env=env)

    result = watch.first_commit_time("synthetic-3982.yml", repo_root=str(tmp_path))
    assert result not in (None, False)
    assert result.startswith("2026-09-19T12:00:00")


def test_3982_first_commit_time_reports_none_with_no_add_commit_ever(tmp_path):
    """The other half: a real git repo where the workflow file was NEVER added — the
    shallow-checkout / history-rewrite shape. Must return None, never guess a birth."""
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    (tmp_path / "README.md").write_text("x", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True, env=_GIT_ENV)
    subprocess.run(["git", "commit", "-q", "-m", "unrelated"], cwd=tmp_path, check=True, env=_GIT_ENV)

    assert watch.first_commit_time("synthetic-3982-never-added.yml", repo_root=str(tmp_path)) is None


def test_3982_first_commit_time_reports_false_when_git_itself_fails(tmp_path):
    """Sentinel-compatible with the other IO lookups: NOT a git checkout at all must be
    `False` (lookup failed), never collapsed onto `None` (birth genuinely unknown)."""
    assert watch.first_commit_time("whatever.yml", repo_root=str(tmp_path)) is False


def test_3982_the_watcher_checkout_step_has_full_history():
    """`first_commit_time()` needs real git history. GitHub's default `fetch-depth: 1`
    checkout carries only the tip commit, which would make every zero-run row read as
    birth-unknown forever, for any workflow file older than the triggering push."""
    doc = yaml.safe_load(open(WATCHER_WORKFLOW, encoding="utf-8").read())
    steps = doc["jobs"]["cadence"]["steps"]
    checkout = next(s for s in steps if str(s.get("uses", "")).startswith("actions/checkout"))
    assert checkout.get("with", {}).get("fetch-depth") == 0
