#!/usr/bin/env python3
"""tests/test_operating_calendar_2832.py — the operating calendar's guards (#2832, #3250).

Layers, matching the charter primitives the calendar is built from:

  * registry well-formedness — every entry parses, points at a real skill and a real
    probe target, and carries a substantive reason (a registry whose reasons are all
    one sentence records that nobody looked);
  * the SET guard — every review-family skill in .claude/commands is either ON the
    calendar or a dated exemption, both directions (guard the set, not the instance:
    deleting a calendar entry without exempting its skill is a mutation this file
    catches);
  * dead-man mutation proofs — the sweep is shown FAILING on a stale artifact, on a
    never-ran ritual past its anchor window, and via the CLI exit code. A gate that
    was never watched failing is a green light wired to nothing (#2578);
  * **#3250 — the anchor may not fake a run.** A ritual with no artifact must report
    NEVER-RUN and must exit non-zero under --due. Before #3250 the distinction lived
    only in the display string (`last never (anchored …)`) while the verdict printed OK,
    so the daily sweep reported "✅ no ritual outside its window" over two rituals nobody
    has ever run. These tests pin the state, the exit code, and the rule that a dated
    `hold` may move the CLOCK but never the never-run VERDICT;
  * **#3250 — no hand-typed magnitudes in a calendared review skill.** The rubric anchors
    in /sdlc-review went 2.7x stale in place (`~380 test files` vs a real 1,015). The
    numbers now come from `scripts/review_anchors.py` at run time; this file fails if one
    is typed back into a skill the calendar schedules.

Repo-shape sweep (reads the skill registry + docs/reviews) → classified pre-merge in
tests/conftest.py's _PREMERGE_EXTRA_FILES, per the #2372 contract.
"""

import importlib.util
import os
import re
from datetime import date, timedelta

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


def _registry():
    path = os.path.join(REPO, "scripts", "skill_registry.py")
    spec = importlib.util.spec_from_file_location("_skill_registry", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


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
        # Resolved through the ONE registry, so this assertion survives a layout change
        # (.claude/commands/<n>.md -> .claude/skills/<n>/SKILL.md) instead of pinning one.
        assert _registry().skill_path(e["skill"]) is not None, f"{name}: skill {e['skill']} has no prompt file"


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
    assert oc.main(["--due", "--today", "2099-01-01"]) == oc.EXIT_OVERDUE
    assert oc.main(["--today", "2099-01-01"]) == oc.EXIT_CLEAN
    assert oc.main(["--check"]) == 0
    assert oc.main(["--due", "--today", "not-a-date"]) == oc.EXIT_BAD_ARG


# ── #3250: an anchor is a grant, not evidence ─────────────────────────────────
def test_never_run_entry_is_not_ok(tmp_path):
    """THE regression this issue exists for. A ritual with no artifact, well inside its
    anchored window, used to print the state word OK. It must not."""
    e = _synthetic(tmp_path, None)
    st = oc.status(e, today=oc.ADOPTED + timedelta(days=1), repo=str(tmp_path))
    assert st["last"] is None and st["never_ran"] is True
    assert st["state"] == oc.NEVER, "a ritual that has never produced its artifact may not report OK"
    assert st["state"] != oc.OK


def test_never_run_makes_due_exit_nonzero_and_distinct(tmp_path):
    """The distinction has to reach the VERDICT, not just the display string: exit 3,
    distinct from OVERDUE's 1 so a log reader can tell 'nobody ever did this' from
    'somebody stopped doing this'."""
    has_run, never_ran = tmp_path / "a", tmp_path / "b"  # separate roots: one probe dir each
    has_run.mkdir()
    never_ran.mkdir()
    ran = _synthetic(has_run, "grades_2026-09-29.json")
    never = _synthetic(never_ran, None)
    assert oc.status(ran, date(2026, 10, 1), repo=str(has_run))["state"] == oc.OK
    st = oc.status(never, oc.ADOPTED + timedelta(days=1), repo=str(never_ran))
    assert st["state"] == oc.NEVER
    assert oc.EXIT_NEVER_RUN == 3 and oc.EXIT_OVERDUE == 1 and oc.EXIT_NEVER_RUN != oc.EXIT_OVERDUE


def test_live_registry_never_run_entries_do_not_report_ok():
    """Against the REAL tree, not a fixture: craft-review and proportionality-reread have
    never produced an artifact, and the live sweep must say so in its exit code. If a
    future session runs them, this test keeps holding — it asserts the implication
    (never-ran => not OK => exit 3), not the identity of the laggards."""
    report, overdue, never = oc.due_report(date.today())
    for name in never:
        st = oc.status(oc.CALENDAR[name], date.today())
        assert st["state"] != oc.OK, f"{name} has never run and must not print OK"
    rc = oc.main(["--due", "--today", date.today().isoformat()])
    if never and not overdue:
        assert rc == oc.EXIT_NEVER_RUN, "a never-run ritual must make the dead-man exit 3"
    if not never and not overdue:
        assert rc == oc.EXIT_CLEAN


def test_hold_moves_the_clock_but_never_the_never_run_verdict(tmp_path):
    """A deferral is a decision about SCHEDULE. It may not manufacture evidence that a
    ritual ran — otherwise 'hold' becomes the new way to print green over an absence."""
    e = dict(_synthetic(tmp_path, None), hold=("2026-09-01", "2026-09-20", "x" * 60))
    # Deep inside the hold window, with the clock re-anchored to 2026-09-20:
    st = oc.status(e, today=date(2026, 9, 10), repo=str(tmp_path))
    assert st["clock"] == date(2026, 9, 20), "a hold re-anchors the clock"
    assert st["state"] == oc.NEVER, "a hold must NOT convert never-ran into OK/HELD"

    # Same hold over a ritual that HAS run: now HELD is the honest word.
    ran = dict(_synthetic(tmp_path, "grades_2026-08-01.json"), hold=("2026-09-01", "2026-09-20", "x" * 60))
    st2 = oc.status(ran, today=date(2026, 9, 10), repo=str(tmp_path))
    assert st2["state"] == oc.HELD and st2["state"] != oc.OK


def test_hold_expires_and_does_not_renew_itself(tmp_path):
    """One-time grant: past `until`, the entry is back on the ordinary cadence and can go
    OVERDUE like anything else. A hold that quietly kept re-anchoring would be exactly the
    'never bump the anchor to silence an overdue ritual' failure, wearing a reason."""
    ran = dict(_synthetic(tmp_path, "grades_2026-08-01.json"), hold=("2026-09-01", "2026-09-20", "x" * 60))
    assert oc.status(ran, today=date(2026, 9, 19), repo=str(tmp_path))["state"] == oc.HELD
    # cadence 7 + grace 3 off the 2026-09-20 re-anchor => due 2026-09-27, hard 2026-09-30.
    assert oc.status(ran, today=date(2026, 9, 21), repo=str(tmp_path))["state"] == oc.OK
    assert oc.status(ran, today=date(2026, 9, 28), repo=str(tmp_path))["state"] == oc.DUE
    assert oc.status(ran, today=date(2026, 10, 5), repo=str(tmp_path))["state"] == oc.OVERDUE


@pytest.mark.parametrize("name", sorted(oc.CALENDAR))
def test_hold_is_dated_bounded_and_reasoned(name):
    """A hold is only better than a silent lapse if it is written down properly: real
    dates, a bounded window, and a reason that names the cause issue."""
    hold = oc.CALENDAR[name]["hold"]
    if hold is None:
        return
    declared, until, reason = hold
    d, u = oc._parse_date(declared), oc._parse_date(until)
    assert d and u, f"{name}: hold dates must be YYYY-MM-DD"
    assert d <= u, f"{name}: hold resumes before it was declared"
    assert (u - d).days <= oc.MAX_HOLD_DAYS, f"{name}: a hold longer than {oc.MAX_HOLD_DAYS}d is a retirement — use EXEMPT"
    assert len(reason) >= 120, f"{name}: a hold reason under 120 chars records that nobody justified it"
    assert re.search(r"#\d+", reason), f"{name}: a hold reason must name the issue that caused it"


def test_the_fullreview_delta_hold_is_pinned():
    """Same shape as test_anchor_is_not_refloated: the ONE hold in force is pinned here,
    so renewing it is a deliberate, reviewed edit rather than a quiet date bump. #3245
    rewrote the review-skill corpus; the next fullreview run is a NEW BASELINE, not a
    delta (#3250)."""
    hold = oc.CALENDAR["fullreview-delta"]["hold"]
    assert hold is not None, "the #3250 decision is recorded as a hold — deleting it silently re-opens the lapse"
    assert hold[0] == "2026-08-27" and hold[1] == "2026-09-06"
    assert "#3245" in hold[2] and "BASELINE" in hold[2]


def test_delta_mode_is_a_defined_procedure():
    """#3250: the calendar entry named a procedure the skill did not implement. The clock
    and the procedure must not drift apart, so the skill has to define delta mode AND name
    the exact artifact filename this entry's probe reads."""
    text = open(os.path.join(REPO, ".claude", "commands", "fullreview.md"), encoding="utf-8").read()
    assert re.search(r"^##\s+Delta mode", text, re.M), "fullreview.md must define delta mode as its own section"
    assert "fullreview_grades_<date>_delta.json" in text, "delta mode must name the artifact the calendar probes"
    probe_rx = re.compile(oc.CALENDAR["fullreview-delta"]["probe"][2])
    assert probe_rx.match("fullreview_grades_2026-09-30_delta.json"), "the documented filename must satisfy the probe"


def test_committed_doc_matches_registry():
    """The docs-ci --check gate, as an in-suite drift detector too."""
    committed = open(os.path.join(REPO, oc.DOC_PATH), encoding="utf-8").read()
    assert committed == oc.render_doc(), "docs/OPERATING_CALENDAR.md drifted — run --apply"


# ── #3250: derived anchors, never hand-typed ones ─────────────────────────────
# Two shapes, both taken from the real defect. FUZZ catches the "about this many"
# form (`~380 test files`, `n≈135`, `60+ process docs`); NOUN catches a bare count
# attached to a magnitude noun (`1015 test files`), which FUZZ would miss.
#
# STATED BLIND SPOT: percentages are deliberately out of scope. `~50%` in these files is
# the historical first-pass false-positive RATE of agent findings — a property of how
# review runs behave, re-measured by every run's own confirmed/refuted counts, not a
# magnitude of the tree that `scripts/review_anchors.py` could derive. A stale hand-typed
# percentage elsewhere would slip past this guard; that is a known hole, not an oversight.
_FUZZ_MAGNITUDE = re.compile(r"[~≈]\s?\d{2,}(?![\d.,]*\s*%)")
_NOUN_MAGNITUDE = re.compile(
    r"[~≈]?\b\d[\d,]*\+?\s*(?:-\s*)?"
    r"(?:scripts?|test files?|tests?|process docs?|docs?|ADRs?|lenses?|lens|gates?|"
    r"lambdas?|workflows?|endpoints?|tools?|files?|modules?|commands?)\b",
    re.I,
)


def _calendared_skill_paths():
    """Scope: the skills the calendar actually schedules. An off-calendar (EXEMPT) skill
    grades nothing on a clock, so its rubric is not load-bearing — and the scope is derived
    from the registry rather than hand-listed, so adding a ritual adds it to this guard."""
    return {s: os.path.join(REPO, ".claude", "commands", s + ".md") for e in oc.CALENDAR.values() if (s := e["skill"])}


def _magnitude_hits(text):
    hits = []
    for i, line in enumerate(text.splitlines(), 1):
        for rx in (_FUZZ_MAGNITUDE, _NOUN_MAGNITUDE):
            for m in rx.finditer(line):
                hits.append((i, m.group(0).strip()))
    return hits


def test_review_skills_carry_no_hand_typed_magnitudes():
    """The #3250 regression guard. `/sdlc-review` graded the suite at `~380 test files`
    against a real 1,015 and `deploy/` at `~85 scripts` against a real 152 — 2.7x off, and
    a denominator that is 2.7x off does not grade, it flatters. Magnitudes come from
    `scripts/review_anchors.py` at run time; a number typed into a calendared rubric is a
    defect the moment it is written, not the moment it drifts."""
    offences = {}
    for skill, path in sorted(_calendared_skill_paths().items()):
        if not os.path.isfile(path):
            continue
        hits = _magnitude_hits(open(path, encoding="utf-8").read())
        if hits:
            offences[skill] = hits
    assert not offences, (
        f"hand-typed magnitude anchor(s) in calendared review skill(s): {offences}. "
        "Derive it instead: add the key to DERIVATIONS in scripts/review_anchors.py and "
        "cite the KEY in the rubric (#3250)."
    )


def test_the_magnitude_guard_actually_catches_the_original_defect():
    """A must-fail case that must actually fail — a guard nobody watched fail is a green
    light wired to nothing. Both real 2026-08-27 strings, plus the bare-count form, plus
    the percentage that must NOT trip it (proving the guard is not just 'any digit')."""
    assert _magnitude_hits("suite runtime/flake economics at ~380 test files")
    assert _magnitude_hits("the `deploy/` script surface (~85 scripts)")
    assert _magnitude_hits("ADR corpus quality at n≈135")
    assert _magnitude_hits("docs mass (60+ process docs)")
    assert _magnitude_hits("the full 17-lens panel")
    assert _magnitude_hits("suite economics at 1015 test files")
    assert not _magnitude_hits("historical first-pass false-positive rate is ~50%.")
    assert not _magnitude_hits("cap ≤8 findings per lens, ~5 actions in the path to A")


def test_review_anchors_derives_the_keys_the_rubrics_cite():
    """The other direction of the same set: every anchor KEY a calendared rubric cites must
    be one this script actually derives. A rubric citing a key nobody produces is the
    phantom-procedure shape #3250 also filed (a registry entry naming a procedure that does
    not exist), just one level down."""
    spec = importlib.util.spec_from_file_location("_review_anchors", os.path.join(REPO, "scripts", "review_anchors.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    values = mod.anchors(REPO)
    assert set(values) == set(mod.DERIVATIONS), "every derived key must carry a label + a stated derivation"
    assert all(isinstance(v, int) and v >= 0 for v in values.values())
    assert values["test_modules"] > 0 and values["deploy_entrypoints"] > 0 and values["adr_records"] > 0

    cited = set()
    for path in _calendared_skill_paths().values():
        if not os.path.isfile(path):
            continue
        text = open(path, encoding="utf-8").read()
        cited |= {k for k in mod.DERIVATIONS if f"`{k}`" in text}
    assert cited, "no calendared rubric cites a derived anchor — the derivation is not wired to anything"
    assert cited <= set(values), f"rubric cites anchor key(s) the deriver does not produce: {sorted(cited - set(values))}"


def test_anchor_is_not_refloated():
    """The anchor is the adoption date, a constant. If someone re-anchors to silence an
    overdue ritual, this pins the honest value; changing it must be a deliberate,
    reviewed act that also updates this test's reasoning."""
    assert oc.ADOPTED == date(2026, 8, 22)
