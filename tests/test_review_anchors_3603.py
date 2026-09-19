"""tests/test_review_anchors_3603.py — the review ritual as an instrument (#3603, epic #3593).

Three properties, each with the negative control the story's `done_when` names:

1. **Frozen anchors.** A run records the anchor text it grades against, fingerprinted at its
   own commit. Control: text that differs from the recorded fingerprint is named by
   `anchor_drift()`; identical text produces an empty list (a drift detector that always
   fires is not one).
2. **The 28-day carry-forward cap.** A grade carried past the cap is expired, dropped from
   the carried set and printed as `stale carry-forward: <lens>`. Control: the same run one
   day inside the cap is clean, and raising `CARRY_FORWARD_MAX_DAYS` to 10,000 makes the
   35-day case pass — which is what "the cap is load-bearing" means.
3. **Planted controls.** A run whose verifiers confirmed a planted false finding is
   UNCALIBRATED and does not advance the calendar clock. Control: the identical artifact
   with a CALIBRATED verdict does advance it.

Nothing here walks the tree: every path is named. The skill-text assertions are the boxes
of the story, pinned so the procedure and the code cannot drift apart.
"""

from __future__ import annotations

import importlib.util
import json
import os
from datetime import date

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load(name: str):
    path = os.path.join(REPO, "scripts", f"{name}.py")
    spec = importlib.util.spec_from_file_location(f"_{name}_3603", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


oc = _load("operating_calendar")
ra = _load("review_anchors")
bb = _load("boot_brief")

SPINE = os.path.join(REPO, ".claude", "skills", "review", "SKILL.md")
FULL_RUBRIC = os.path.join(REPO, ".claude", "skills", "review", "references", "full.md")


def _run(day: str, graded: dict[str, str], carried=None) -> tuple[date, dict]:
    """One grades artifact: `graded` are the rows this run derived from scratch, `carried`
    the rows it carried forward as {lens: the date of the run that graded it}."""
    body = {"date": day, "lenses": {k: {"grade": v} for k, v in graded.items()}}
    if carried is not None:
        body["unchanged_lenses"] = carried
    return (date.fromisoformat(day), body)


def _write_runs(tmp_path, runs) -> str:
    reviews = tmp_path / "docs" / "reviews"
    reviews.mkdir(parents=True)
    for when, body in runs:
        suffix = "_delta" if body.get("unchanged_lenses") is not None else ""
        (reviews / f"fullreview_grades_{when.isoformat()}{suffix}.json").write_text(json.dumps(body), encoding="utf-8")
    return str(tmp_path)


# ── 2. the carry-forward cap ─────────────────────────────────────────────────


def test_a_35_day_old_carried_grade_is_reported_stale():
    """The story's first negative control, verbatim: feed the calendar probe a grades JSON
    whose `unchanged_lenses` cites a run 35 days old and it reports the lens as stale."""
    today = date(2026, 9, 19)
    runs = [
        _run("2026-08-15", {"cpo": "B", "cto": "A"}),
        _run("2026-09-12", {"cto": "A"}, carried={"cpo": "2026-08-15"}),
    ]
    expired = oc.expired_carry_forward(runs, today)
    assert [row["lens"] for row in expired] == ["cpo"], expired
    assert expired[0]["age_days"] == 35
    assert expired[0]["last_scratch"] == date(2026, 8, 15)


def test_a_carried_grade_inside_the_cap_is_clean():
    """The positive control of the same measurement — a cap that flags everything is not a
    cap, it is a broken clock."""
    today = date(2026, 9, 19)
    runs = [
        _run("2026-09-01", {"cpo": "B", "cto": "A"}),
        _run("2026-09-12", {"cto": "A"}, carried={"cpo": "2026-09-01"}),
    ]
    assert oc.expired_carry_forward(runs, today) == []


def test_the_cap_is_load_bearing():
    """Mutation: raise the cap to 10,000 days and the 35-day case passes. The first test
    takes the cap from the module constant, so an edit to that constant fails it — which is
    the only thing that makes the number real."""
    today = date(2026, 9, 19)
    runs = [
        _run("2026-08-15", {"cpo": "B"}),
        _run("2026-09-12", {}, carried={"cpo": "2026-08-15"}),
    ]
    assert oc.CARRY_FORWARD_MAX_DAYS == 28
    assert oc.expired_carry_forward(runs, today, max_days=oc.CARRY_FORWARD_MAX_DAYS)
    assert oc.expired_carry_forward(runs, today, max_days=10_000) == []


def test_carrying_a_grade_is_not_grading_it():
    """The finding in one assertion: the age runs from the run that GRADED the row, not from
    the delta that carried it. Three consecutive carries do not refresh anything."""
    runs = [
        _run("2026-08-01", {"qs": "B"}),
        _run("2026-08-08", {}, carried={"qs": "2026-08-01"}),
        _run("2026-08-15", {}, carried={"qs": "2026-08-08"}),
        _run("2026-08-22", {}, carried={"qs": "2026-08-01"}),
    ]
    assert oc.scratch_dates(runs)["qs"] == date(2026, 8, 1)


def test_a_carry_that_names_no_source_run_is_expired_not_fresh():
    runs = [_run("2026-09-12", {"cto": "A"}, carried={"reader": ""})]
    expired = oc.expired_carry_forward(runs, date(2026, 9, 19))
    assert [row["lens"] for row in expired] == ["reader"]
    assert expired[0]["age_days"] is None


def test_a_lens_the_newest_artifact_no_longer_claims_is_not_stale():
    """`ai-quality` was graded in the 2026-07-16 run and the panel later renamed it `aiq`.
    An unscoped sweep reports the retired name as permanently stale — a red nobody can
    clear, which is how a gate gets ignored."""
    runs = [
        _run("2026-07-16", {"ai-quality": "B"}),
        _run("2026-09-12", {"aiq": "B"}),
    ]
    assert oc.expired_carry_forward(runs, date(2026, 9, 19)) == []


def test_the_prose_form_of_unchanged_lenses_still_parses():
    """The four committed artifacts carry prose, not the structured form. Oldest date wins:
    a grade carried through a chain is only as fresh as the run that actually looked."""
    carried = oc.carried_lenses(
        {
            "unchanged_lenses": (
                "reader, data-architect (2026-08-09 delta); cpo, designer, dataviz, qs, a11y, cost, devex, growth "
                "(2026-08-02 delta / 2026-07-28 partial) — grades stand."
            )
        }
    )
    assert carried["reader"] == date(2026, 8, 9)
    assert carried["data-architect"] == date(2026, 8, 9)
    assert carried["cpo"] == date(2026, 7, 28)
    assert carried["growth"] == date(2026, 7, 28)
    assert "grades stand" not in carried


def test_the_sweep_prints_the_stale_line_and_exits_distinctly(tmp_path):
    """End to end over files on disk: the probe reads the artifacts, the report names the
    lens, and `--due` reports it as its own state rather than folding it into clean."""
    repo = _write_runs(
        tmp_path,
        [
            _run("2026-08-15", {"cpo": "B", "cto": "A"}),
            _run("2026-09-12", {"cto": "A"}, carried={"cpo": "2026-08-15"}),
        ],
    )
    lines, expired = oc.carry_forward_report(date(2026, 9, 19), repo)
    text = "\n".join(lines)
    assert "stale carry-forward: cpo" in text, text
    assert "re-verify or refile" in text
    assert len(expired) == 1
    assert oc.EXIT_STALE_CARRY == 4 and oc.EXIT_STALE_CARRY not in (oc.EXIT_CLEAN, oc.EXIT_OVERDUE, oc.EXIT_NEVER_RUN)


def test_the_committed_corpus_is_measurable_and_clean_today():
    """The live artifacts, not a fixture: the 2026-09-05 baseline graded every row from
    scratch, so nothing is expired. If this ever fails, the next delta owes those rows."""
    runs = oc.load_grade_runs(REPO)
    assert runs, "no fullreview grades artifacts found — the cap would be measuring nothing"
    assert oc.expired_carry_forward(runs, date(2026, 9, 19)) == []


# ── 3. the planted controls ──────────────────────────────────────────────────


def _entry_over(repo_dir: str) -> dict:
    return {
        "probe": (oc.NEWEST_DATED_FILE, "docs/reviews", r"^fullreview_grades_(\d{4}-\d{2}-\d{2})(?:_delta)?\.json$"),
        "qualifier": oc.calibrated_run,
        "cadence_days": 7,
        "grace_days": 3,
        "hold": None,
        "starts": None,
    }


def test_an_uncalibrated_run_does_not_reset_the_clock(tmp_path):
    """The story's second negative control: a run whose verifiers confirmed a planted false
    finding is not evidence the ritual happened, so the clock keeps counting down."""
    good, bad = _run("2026-09-01", {"cto": "A"}), _run("2026-09-12", {"cto": "A"})
    bad[1]["calibration"] = {"verdict": "UNCALIBRATED", "planted_false_findings": {"n": 3, "confirmed_by_verifiers": ["CTO-P1"]}}
    repo = _write_runs(tmp_path, [good, bad])
    assert oc.newest_run(_entry_over(repo), repo) == date(2026, 9, 1)


def test_a_calibrated_run_does_reset_the_clock(tmp_path):
    """The positive control: the identical artifact whose controls fired advances the clock.
    Without this, a probe that skipped everything would pass the test above."""
    good, fresh = _run("2026-09-01", {"cto": "A"}), _run("2026-09-12", {"cto": "A"})
    fresh[1]["calibration"] = {
        "verdict": "CALIBRATED",
        "planted_false_findings": {"n": 3, "confirmed_by_verifiers": []},
        "withheld_known_issues": {"n": 2, "found": ["#3601", "#3593"], "missed_by_graders": []},
    }
    repo = _write_runs(tmp_path, [good, fresh])
    assert oc.newest_run(_entry_over(repo), repo) == date(2026, 9, 12)


def test_the_numbers_beat_the_self_reported_word():
    """A run grading its own controls green while its own numbers say otherwise is exactly
    the failure the controls exist to catch."""
    claimed_clean = {"calibration": {"verdict": "CALIBRATED", "planted_false_findings": {"n": 2, "confirmed_by_verifiers": ["DESIGNER-3"]}}}
    assert oc.calibration_verdict(claimed_clean) == oc.UNCALIBRATED
    missed = {"calibration": {"verdict": "CALIBRATED", "withheld_known_issues": {"n": 2, "missed_by_graders": ["#3601", "#3593"]}}}
    assert oc.calibration_verdict(missed) == oc.UNCALIBRATED
    assert oc.calibration_verdict({}) == oc.UNSTATED


def test_history_is_not_retroactively_disqualified(tmp_path):
    """Every artifact before #3603 states no calibration. UNSTATED counts as a run and says
    so — arming a gate over history is how a gate is born red and then ignored."""
    repo = _write_runs(tmp_path, [_run("2026-09-12", {"cto": "A"})])
    assert oc.newest_run(_entry_over(repo), repo) == date(2026, 9, 12)
    lines, _ = oc.carry_forward_report(date(2026, 9, 13), repo)
    assert "calibration UNSTATED" in "\n".join(lines)


def test_the_live_review_clocks_read_the_calibrated_probe():
    for name in ("fullreview-delta", "fullreview-full"):
        assert oc.CALENDAR[name]["qualifier"] is oc.calibrated_run, f"{name} advances on an artifact nobody calibrated"


# ── 1. the frozen anchors ────────────────────────────────────────────────────


def _rubric_tree(tmp_path, spine="SPINE v1\n", rubric="RUBRIC v1\n"):
    d = tmp_path / ".claude" / "skills" / "review" / "references"
    d.mkdir(parents=True)
    (tmp_path / ".claude" / "skills" / "review" / "SKILL.md").write_text(spine, encoding="utf-8")
    (d / "full.md").write_text(rubric, encoding="utf-8")
    return str(tmp_path)


def test_the_freeze_records_the_anchor_text_it_graded_against(tmp_path):
    repo = _rubric_tree(tmp_path)
    header = ra.frozen_anchor_header("full", "abc123", date(2026, 9, 19), read_text=ra.read_from_tree(repo))
    assert set(header["rubric"]) == set(ra.rubric_paths("full"))
    assert all(v.startswith("sha256:") for v in header["rubric"].values())
    assert header["graded_sha"] == "abc123" and header["frozen_at"] == "2026-09-19"
    assert "between runs" in header["rule"]


def test_anchor_text_that_moved_during_the_run_is_named(tmp_path):
    """The story's third negative control: a run's anchor text that differs from the
    versioned rubric at that run's commit must red, naming which file moved."""
    repo = _rubric_tree(tmp_path)
    header = ra.frozen_anchor_header("full", "abc123", date(2026, 9, 19), read_text=ra.read_from_tree(repo))
    (tmp_path / ".claude" / "skills" / "review" / "references" / "full.md").write_text(
        "RUBRIC v1\nAn A now also requires a live curl.\n", encoding="utf-8"
    )
    drift = ra.anchor_drift(header, ra.read_from_tree(repo))
    assert len(drift) == 1 and "references/full.md" in drift[0] and "the anchors moved" in drift[0], drift


def test_unmoved_anchor_text_does_not_red(tmp_path):
    """The positive control. A drift detector that always fires is not a detector."""
    repo = _rubric_tree(tmp_path)
    header = ra.frozen_anchor_header("full", "abc123", date(2026, 9, 19), read_text=ra.read_from_tree(repo))
    assert ra.anchor_drift(header, ra.read_from_tree(repo)) == []


def test_a_missing_anchor_file_is_recorded_not_dropped(tmp_path):
    repo = _rubric_tree(tmp_path)
    os.remove(os.path.join(repo, ".claude", "skills", "review", "references", "full.md"))
    header = ra.frozen_anchor_header("full", "abc123", date(2026, 9, 19), read_text=ra.read_from_tree(repo))
    assert header["rubric"][".claude/skills/review/references/full.md"] == "MISSING"


def test_a_run_with_no_freeze_block_cannot_be_checked_and_says_so():
    drift = ra.anchor_drift({"lens": "full"}, ra.read_from_tree(REPO))
    assert drift and "recorded no anchor text" in drift[0]


def test_the_live_spine_and_rubric_fingerprint():
    header = ra.frozen_anchor_header("full", "HEAD", date(2026, 9, 19))
    assert "MISSING" not in header["rubric"].values(), header["rubric"]
    assert header["carry_forward_cap_days"] == oc.CARRY_FORWARD_MAX_DAYS, "the cap must have exactly one home"


# ── the boot brief prints the expired set ────────────────────────────────────


def test_the_boot_brief_prints_the_stale_lens_line():
    model = bb.load_model()
    lines = "\n".join(bb.render_lines(model))
    assert f"lenses not graded from scratch in >{oc.CARRY_FORWARD_MAX_DAYS}d:" in lines, lines


def test_the_boot_brief_line_fails_soft(tmp_path):
    """A boot brief that raises kills the SessionStart hook for every session, so the
    failure has to arrive as a printed reason rather than a traceback."""
    out = bb.stale_review_lenses(date(2026, 9, 19), repo=tmp_path)
    assert out["error"], out
    assert out["expired"] == []


# ── the procedure and the code cannot drift apart ────────────────────────────


@pytest.mark.parametrize(
    "needle",
    [
        "python3 scripts/review_anchors.py --freeze",
        "may not be extended, narrowed or reworded while it is in flight",
        "Planted controls",
        "confirmed_by_verifiers",
        "does not reset the calendar clock",
        "filed OR explicitly declined with a written reason",
    ],
)
def test_the_spine_states_the_procedure(needle):
    assert needle in open(SPINE, encoding="utf-8").read(), f"the review spine no longer states: {needle}"


def test_the_spine_no_longer_sanctions_in_run_anchor_extension():
    """The exact sentence this story reverses. Its presence is the defect."""
    text = open(SPINE, encoding="utf-8").read()
    # Matched on the clause that ONLY the sanction carried: the new text quotes the old
    # phrase in order to reverse it, and a matcher that reads the prose explaining a rule
    # as a breach of it is this repo's most repeated gate defect.
    assert "(a new A-criterion, stated as new), never silently redefined" not in text
    assert "Extend an anchor **between** runs," in text


@pytest.mark.parametrize(
    "needle",
    [
        "stale carry-forward: <lens>",
        "expired, re-verify or refile",
        "CARRY_FORWARD_MAX_DAYS",
        'The reset "event term" is deliberately NOT added',
        "#3601",
    ],
)
def test_the_full_rubric_states_the_cap_and_the_rejected_event_term(needle):
    assert needle in open(FULL_RUBRIC, encoding="utf-8").read(), f"the full rubric no longer states: {needle}"
