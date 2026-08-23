#!/usr/bin/env python3
"""tests/test_operating_calendar_2832.py — the operating calendar's guards (#2832).

Three layers, matching the charter primitives the calendar is built from:

  * registry well-formedness — every entry parses, points at a real skill and a real
    probe target, and carries a substantive reason (a registry whose reasons are all
    one sentence records that nobody looked);
  * the SET guard — every review-family skill in .claude/commands is either ON the
    calendar or a dated exemption, both directions (guard the set, not the instance:
    deleting a calendar entry without exempting its skill is a mutation this file
    catches);
  * dead-man mutation proofs — the sweep is shown FAILING on a stale artifact, on a
    never-ran ritual past its anchor window, and via the CLI exit code. A gate that
    was never watched failing is a green light wired to nothing (#2578).

Repo-shape sweep (reads .claude/commands + docs/reviews) → classified pre-merge in
tests/conftest.py's _PREMERGE_EXTRA_FILES, per the #2372 contract.
"""

import importlib.util
import os
import re
from datetime import date

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)


def _load():
    path = os.path.join(REPO, "scripts", "operating_calendar.py")
    spec = importlib.util.spec_from_file_location("_operating_calendar", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


oc = _load()

# Rituals with run history at adoption — their probes MUST resolve. If one goes None,
# the artifact naming drifted and every future "last run" silently becomes "never":
# exactly the lying-gauge shape this calendar exists to kill. craft-review and
# proportionality-reread are deliberately absent (no history yet); their first real
# run makes them eligible, never required.
HISTORY = ("fullreview-delta", "fullreview-full", "accuracy-full", "sdlc-review", "frontier-plan")


# ── Registry well-formedness ──────────────────────────────────────────────────
@pytest.mark.parametrize("name", sorted(oc.CALENDAR))
def test_entry_well_formed(name):
    e = oc.CALENDAR[name]
    assert e["cadence_days"] > 0 and e["grace_days"] >= 0
    assert e["attendance"] in (oc.AUTONOMOUS, oc.SESSION, oc.OWNER)
    assert len(e["reason"]) >= 40, f"{name}: a reason under 40 chars records that nobody looked"
    kind, target, pattern = e["probe"]
    assert kind in (oc.NEWEST_DATED_FILE, oc.REGEX_IN_FILE)
    rx = re.compile(pattern)
    assert rx.groups == 1, f"{name}: probe regex must have exactly one group (the date)"
    abs_target = os.path.join(REPO, target)
    if kind == oc.NEWEST_DATED_FILE:
        assert os.path.isdir(abs_target), f"{name}: probe dir {target} does not exist"
    else:
        assert os.path.isfile(abs_target), f"{name}: probe file {target} does not exist"
    if e["skill"]:
        skill_path = os.path.join(REPO, ".claude", "commands", e["skill"] + ".md")
        assert os.path.isfile(skill_path), f"{name}: skill {e['skill']} has no command file"


@pytest.mark.parametrize("name", sorted(oc.EXEMPT))
def test_exemption_dated_and_substantive(name):
    d, reason = oc.EXEMPT[name]
    parsed = oc._parse_date(d)
    assert parsed is not None, f"{name}: exemption date {d!r} does not parse"
    assert parsed <= date.today(), f"{name}: exemption dated in the future"
    assert len(reason) >= 40, f"{name}: exemption reason under 40 chars"


@pytest.mark.parametrize("name", HISTORY)
def test_history_probe_resolves(name):
    assert oc.newest_run(oc.CALENDAR[name]) is not None, (
        f"{name}: probe found NO dated artifact, but this ritual has run history — "
        "either docs/reviews naming drifted or the probe regex broke. Every future "
        "'last run' would silently read 'never'."
    )


def test_full_probe_rejects_delta_and_partial():
    """The monthly-full claim is load-bearing: a delta must NOT reset the full clock."""
    full_rx = re.compile(oc.CALENDAR["fullreview-full"]["probe"][2])
    delta_rx = re.compile(oc.CALENDAR["fullreview-delta"]["probe"][2])
    assert full_rx.match("fullreview_grades_2026-08-16.json")
    assert not full_rx.match("fullreview_grades_2026-08-16_delta.json")
    assert not full_rx.match("fullreview_grades_2026-07-28_partial.json")
    assert delta_rx.match("fullreview_grades_2026-08-16_delta.json")
    assert delta_rx.match("fullreview_grades_2026-08-16.json"), "a full run also satisfies the weekly claim"


# ── The SET guard (both directions) ───────────────────────────────────────────
def test_every_review_skill_classified():
    unclassified, phantom = oc.classification_gaps(oc.CALENDAR, oc.EXEMPT, oc.review_skill_files())
    assert not unclassified, (
        f"review skill(s) {sorted(unclassified)} are neither on the calendar nor a dated "
        "exemption — a ritual that half-exists off-calendar is the #2832 failure mode"
    )
    assert not phantom, f"calendar/exemption row(s) name skills that no longer exist: {sorted(phantom)}"


def test_set_guard_catches_deleted_entry():
    """Mutation proof: dropping a calendar entry (without exempting its skill) is caught."""
    mutated = {k: v for k, v in oc.CALENDAR.items() if k != "craft-review"}
    unclassified, _ = oc.classification_gaps(mutated, oc.EXEMPT, oc.review_skill_files())
    assert "craft-review" in unclassified


def test_set_guard_catches_phantom_exemption():
    mutated = dict(oc.EXEMPT, **{"a-review-skill-that-never-existed": ("2026-08-23", "x" * 40)})
    _, phantom = oc.classification_gaps(oc.CALENDAR, mutated, oc.review_skill_files())
    assert "a-review-skill-that-never-existed" in phantom


# ── Dead-man mutation proofs ──────────────────────────────────────────────────
def _synthetic(tmp_path, artifact_name):
    d = tmp_path / "reviews"
    d.mkdir(exist_ok=True)
    if artifact_name:
        (d / artifact_name).write_text("{}")
    return {
        "skill": None,
        "cadence_days": 7,
        "grace_days": 3,
        "attendance": oc.SESSION,
        "probe": (oc.NEWEST_DATED_FILE, "reviews", r"^grades_(\d{4}-\d{2}-\d{2})\.json$"),
        "obligations": (),
        "reason": "synthetic entry for the dead-man mutation proofs, forty chars of reason",
    }


def test_deadman_fails_on_stale_artifact(tmp_path):
    e = _synthetic(tmp_path, "grades_2026-09-01.json")
    st = oc.status(e, today=date(2026, 10, 1), repo=str(tmp_path))
    assert st["state"] == oc.OVERDUE, "artifact 30d old on a 7+3d window must be OVERDUE"


def test_deadman_ok_on_fresh_artifact(tmp_path):
    e = _synthetic(tmp_path, "grades_2026-09-29.json")
    st = oc.status(e, today=date(2026, 10, 1), repo=str(tmp_path))
    assert st["state"] == oc.OK


def test_deadman_fails_on_never_ran_past_anchor_window(tmp_path):
    """A ritual that NEVER produces its artifact still screams once the adoption
    anchor's window closes — the craft-review shape, proven synthetically."""
    e = _synthetic(tmp_path, None)
    st = oc.status(e, today=oc.ADOPTED.fromordinal(oc.ADOPTED.toordinal() + 11), repo=str(tmp_path))
    assert st["last"] is None
    assert st["state"] == oc.OVERDUE


def test_deadman_grace_is_due_not_overdue(tmp_path):
    e = _synthetic(tmp_path, "grades_2026-09-01.json")
    st = oc.status(e, today=date(2026, 9, 10), repo=str(tmp_path))
    assert st["state"] == oc.DUE, "inside grace: run it now, nothing screams yet"


def test_cli_exit_codes():
    """--due exits 1 on an overdue ritual (far-future today makes everything overdue);
    the bare report never gates; --check agrees with the committed doc."""
    assert oc.main(["--due", "--today", "2099-01-01"]) == 1
    assert oc.main(["--today", "2099-01-01"]) == 0
    assert oc.main(["--check"]) == 0
    assert oc.main(["--due", "--today", "not-a-date"]) == 2


def test_committed_doc_matches_registry():
    """The docs-ci --check gate, as an in-suite drift detector too."""
    committed = open(os.path.join(REPO, oc.DOC_PATH), encoding="utf-8").read()
    assert committed == oc.render_doc(), "docs/OPERATING_CALENDAR.md drifted — run --apply"


def test_anchor_is_not_refloated():
    """The anchor is the adoption date, a constant. If someone re-anchors to silence an
    overdue ritual, this pins the honest value; changing it must be a deliberate,
    reviewed act that also updates this test's reasoning."""
    assert oc.ADOPTED == date(2026, 8, 22)
