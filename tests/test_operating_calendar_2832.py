#!/usr/bin/env python3
"""tests/test_operating_calendar_2832.py — the operating calendar's guards (#2832, #3250).

Layers, matching the charter primitives the calendar is built from:

  * registry well-formedness — every entry parses, points at a real skill and a real
    probe target, and carries a substantive reason (a registry whose reasons are all
    one sentence records that nobody looked);
  * the SET guard — every judgment procedure discovered from the tree is either ON the
    calendar or a dated exemption, both directions (guard the set, not the instance:
    deleting a calendar entry without exempting its procedure is a mutation this file
    catches). Since #3250 the unit is a `/review <lens>` RUBRIC, not a command file, so a
    new `.claude/skills/review/references/<lens>.md` is unclassified — loud — from the
    moment it exists, and a calendar entry naming a rubric nobody wrote is a phantom;
  * **#3250 — the ADR-099 filing contract has exactly ONE home.** Six of the nine review
    files restated it. The guard is derived, not phrase-matched: it reads the contract's
    machine-readable mechanics OUT of `.claude/agents/issue-filer.md` and counts how many
    each review-corpus file reproduces. The real paraphrases measured 3–4; a pointer
    measures 0–1;
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
    if e["lens"]:
        # #3250: the lens is the PROCEDURE, and a procedure that does not exist is exactly
        # the defect this issue filed (`fullreview-delta` counting down toward a mode
        # nothing implemented). Resolved to a real rubric file, never assumed.
        assert e["skill"] == oc.REVIEW_SPINE, f"{name}: a lens entry must be dispatched by /{oc.REVIEW_SPINE}"
        lenses = oc.review_lenses()
        assert e["lens"] in lenses, f"{name}: lens {e['lens']!r} has no rubric file under the review spine"
        assert os.path.isfile(os.path.join(REPO, lenses[e["lens"]])), f"{name}: rubric {lenses[e['lens']]} missing"


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
def test_every_review_procedure_classified():
    unclassified, phantom = oc.classification_gaps(oc.CALENDAR, oc.EXEMPT, oc.review_procedures())
    assert not unclassified, (
        f"review procedure(s) {sorted(unclassified)} are neither on the calendar nor a dated "
        "exemption — a ritual that half-exists off-calendar is the #2832 failure mode"
    )
    assert not phantom, f"calendar/exemption row(s) name procedures that do not exist: {sorted(phantom)}"


def test_the_discovered_set_is_derived_from_the_tree():
    """The discovery half must actually walk the filesystem, or the SET guard degenerates
    into 'the registry agrees with itself'. Every discovered name resolves to a real file,
    every lens is a rubric beside the spine, and the spine itself is deliberately NOT a
    procedure (it grades nothing on a clock; its lenses do)."""
    procs = oc.review_procedures()
    assert procs, "discovery returned nothing — a set guard over an empty set proves nothing"
    for name, rel_path in procs.items():
        assert os.path.isfile(os.path.join(REPO, rel_path)), f"{name}: {rel_path} does not exist"
    lenses = oc.review_lenses()
    assert set(lenses) >= {"accuracy", "craft", "sdlc", "full"}, "the calendared lenses must be discoverable"
    for lens, rel_path in lenses.items():
        assert rel_path == f".claude/skills/review/references/{lens}.md"
    assert oc.REVIEW_SPINE not in procs, "the spine is a shell, not a ritual — it must not need a calendar row"


def test_set_guard_catches_deleted_entry():
    """Mutation proof: dropping a calendar entry (without exempting its lens) is caught."""
    mutated = {k: v for k, v in oc.CALENDAR.items() if k != "craft-review"}
    unclassified, _ = oc.classification_gaps(mutated, oc.EXEMPT, oc.review_procedures())
    assert "craft" in unclassified


def test_set_guard_catches_a_new_unclassified_lens():
    """THE 'a future entry cannot drift green' proof. Someone adds a rubric file and forgets
    the registry: the new lens must come up UNCLASSIFIED, not silently green. Synthesized
    against the live registry rather than by touching the real tree."""
    discovered = dict(oc.review_procedures())
    discovered["a-brand-new-lens"] = ".claude/skills/review/references/a-brand-new-lens.md"
    unclassified, _ = oc.classification_gaps(oc.CALENDAR, oc.EXEMPT, discovered)
    assert "a-brand-new-lens" in unclassified, "a new rubric with no registry row must be loud"


def test_set_guard_catches_a_calendar_entry_naming_a_missing_procedure():
    """The other direction, and the one #3250 filed: `fullreview-delta` named a delta mode
    nothing implemented while its clock counted down toward a hard date. An entry whose
    procedure does not exist is a PHANTOM the moment it is written."""
    mutated = dict(oc.CALENDAR)
    mutated["ghost-review"] = dict(oc.CALENDAR["craft-review"], lens="a-lens-nobody-wrote")
    _, phantom = oc.classification_gaps(mutated, oc.EXEMPT, oc.review_procedures())
    assert "a-lens-nobody-wrote" in phantom


def test_set_guard_catches_phantom_exemption():
    mutated = dict(oc.EXEMPT, **{"a-review-lens-that-never-existed": ("2026-08-23", "x" * 40)})
    _, phantom = oc.classification_gaps(oc.CALENDAR, mutated, oc.review_procedures())
    assert "a-review-lens-that-never-existed" in phantom


def test_the_spine_dispatches_every_lens_that_exists():
    """The spine's contract test, and the third face of the SET guard.

    `/review <lens>` only works if the spine's dispatch table names the lens and points at its
    rubric path. A rubric added without a dispatch row is unreachable prose — the same
    half-existence the calendar exemptions were papering over, one layer up — so the table is
    asserted against the DISCOVERED set rather than a hand list.
    """
    from skill_paths import require_skill

    spine = require_skill("review").read_text(encoding="utf-8")
    for lens, rel_path in sorted(oc.review_lenses().items()):
        assert f"`{rel_path}`" in spine, f"the /review dispatch table never points at the {lens} rubric ({rel_path})"
        assert re.search(rf"\|\s*`{re.escape(lens)}`\s*\|", spine), f"lens {lens!r} has a rubric but no dispatch row"


def test_the_retired_rituals_are_deleted_not_orphaned():
    """#3250's third defect: three rituals were retired by a dated EXEMPT row on 2026-08-22
    and their command files were left in the tree for six days. An exemption retires a
    CLOCK, not a capability — so the standalone skill must be GONE while the lens rubric
    it became still exists and stays classified."""
    skills = set(_registry().skill_names())
    retired = ("platform-review", "site-review", "journey-review", "fullreview", "accuracy-review", "craft-review", "sdlc-review")
    for name in retired:
        assert name not in skills, f"{name} still exists as a standalone skill — the orphan-file defect"
    for lens in ("platform", "site", "journey"):
        assert lens in oc.EXEMPT, f"{lens} lost its dated exemption"
        assert lens in oc.review_lenses(), f"{lens} was deleted outright — the exemption retired its clock, not the lens"


# ── Dead-man mutation proofs ──────────────────────────────────────────────────
def _synthetic(tmp_path, artifact_name):
    d = tmp_path / "reviews"
    d.mkdir(exist_ok=True)
    if artifact_name:
        (d / artifact_name).write_text("{}")
    return {
        "skill": None,
        "lens": None,
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
    """#3250: the calendar entry named a procedure the rubric did not implement. The clock
    and the procedure must not drift apart, so the rubric has to define delta mode AND name
    the exact artifact filename this entry's probe reads. Resolved through the registry's
    lens discovery, so the assertion follows the rubric wherever it lives."""
    rel_path = oc.review_lenses()[oc.CALENDAR["fullreview-delta"]["lens"]]
    text = open(os.path.join(REPO, rel_path), encoding="utf-8").read()
    assert re.search(r"^##\s+Delta mode", text, re.M), f"{rel_path} must define delta mode as its own section"
    assert "fullreview_grades_<date>_delta.json" in text, "delta mode must name the artifact the calendar probes"
    probe_rx = re.compile(oc.CALENDAR["fullreview-delta"]["probe"][2])
    assert probe_rx.match("fullreview_grades_2026-09-30_delta.json"), "the documented filename must satisfy the probe"


def test_every_calendared_rubric_names_the_artifact_its_probe_reads():
    """Generalized from the delta defect: a rubric that does not name its own artifact
    filename lets a run land its report where the dead-man cannot see it — and the sweep
    then reports 'never ran' over a ritual that did. The literal filename stem from each
    entry's probe regex must appear in the rubric it schedules."""
    misses = []
    for name, e in sorted(oc.CALENDAR.items()):
        if not e["lens"]:
            continue
        text = open(os.path.join(REPO, oc.review_lenses()[e["lens"]]), encoding="utf-8").read()
        # The probe regex's fixed prefix, before the date group — e.g. `craft_grades_`.
        stem = re.match(r"\^([A-Za-z_]+)", e["probe"][2])
        assert stem, f"{name}: probe pattern has no literal filename stem to check"
        if stem.group(1) not in text:
            misses.append((name, stem.group(1), oc.review_lenses()[e["lens"]]))
    assert not misses, f"rubric(s) never name the artifact filename their clock probes: {misses}"


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


def _calendared_rubric_paths():
    """Scope: the prompt text the calendar actually schedules — the `/review` spine plus each
    CALENDARED lens rubric, plus any standalone skill an entry names. An off-calendar (EXEMPT)
    lens grades nothing on a clock, so its rubric is not load-bearing.

    Derived from the registry, never a layout literal. This helper hard-coded
    `.claude/commands/<n>.md` once and broke on the #3245 rename exactly as that PR's note
    predicted — loudly, which is the design working. #3250 moved the rubrics again, from
    `<skill>/SKILL.md` into `review/references/<lens>.md`, and the SCOPE HAS TO FOLLOW THE
    CONTENT: had it not, the magnitude guard would have kept passing over a spine that no
    longer contains a single anchor, which is a gate quietly measuring nothing.
    """
    from skill_paths import skill_path

    out: dict[str, str] = {}
    lenses = oc.review_lenses()
    for e in oc.CALENDAR.values():
        if e["lens"] and e["lens"] in lenses:
            out[f"review:{e['lens']}"] = os.path.join(REPO, lenses[e["lens"]])
        if e["skill"] and skill_path(e["skill"]):
            out[e["skill"]] = str(skill_path(e["skill"]))
    return out


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
    for skill, path in sorted(_calendared_rubric_paths().items()):
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
    for path in _calendared_rubric_paths().values():
        if not os.path.isfile(path):
            continue
        text = open(path, encoding="utf-8").read()
        cited |= {k for k in mod.DERIVATIONS if f"`{k}`" in text}
    assert cited, "no calendared rubric cites a derived anchor — the derivation is not wired to anything"
    assert cited <= set(values), f"rubric cites anchor key(s) the deriver does not produce: {sorted(cited - set(values))}"


# ── #3250: the ADR-099 filing contract has exactly ONE home ───────────────────
# The finding: six of the nine review files restated the filing contract. Six copies is five
# opportunities to drift, and the paraphrases had already drifted — one still routed won't-do
# items at a CLOSED pointer issue, another linked stories to a CLOSED epic.
#
# STRUCTURAL, NOT PHRASE-MATCHED (the #2959/#3003/#3199 lesson — every phrase-matched member of
# that family has failed in the field). The guard does not look for sentences about filing. It
# reads the contract's MACHINE-READABLE MECHANICS out of the owner file itself — label literals,
# body-heading literals, score-line field literals, the reconcile query — by SHAPE, and counts how
# many of them each review-corpus file reproduces. Because the vocabulary is derived from the
# owner, changing the contract re-arms the guard the same day instead of leaving it pinned to a
# 2026-08 snapshot.
ADR099_OWNER = ".claude/agents/issue-filer.md"

#: A backticked literal in the owner file is a contract MECHANIC if it has one of these shapes.
#: Shapes, not values: `type:story` and a label invented next month both match the first row.
_MECHANIC_SHAPES = (
    re.compile(r"^(?:type|area|model|prio|review|gate):"),  # the label taxonomy
    re.compile(r"^##\s+\S"),  # the required body headings
    re.compile(r"^\*\*(?:Score|Epic|Shipped|Outcome):"),  # the required body fields
    re.compile(r"^(?:Impact|Confidence|Effort)\b"),  # the score-line grammar
    re.compile(r"^P<"),
    re.compile(r"^→\s*<"),  # the milestone arrow
    re.compile(r"^gh issue list --label review:"),  # the idempotency reconcile
    re.compile(r"^Part of #"),  # the retired linkage form
)

#: Measured, not guessed. On 2026-08-27 the three heaviest paraphrases scored 3, 4 and 3 on this
#: metric and the two light ones scored 0 (they are caught by the pointer half below); a pointer
#: scores 0–1. The ceiling is ONE because a lens may legitimately name a single label vocabulary
#: as a grading SUBJECT — the sdlc rubric grades `model:*` routing accuracy against real usage —
#: while two or more is a restatement of the contract.
MAX_MECHANICS_PER_FILE = 1


def _contract_mechanics():
    owner = open(os.path.join(REPO, ADR099_OWNER), encoding="utf-8").read()
    return {lit.strip() for lit in re.findall(r"`([^`\n]{3,80})`", owner) if any(s.search(lit.strip()) for s in _MECHANIC_SHAPES)}


def _mechanic_hits(text, mechanics=None):
    """Which contract mechanics this text reproduces as literals of its own."""
    return sorted(m for m in (mechanics or _contract_mechanics()) if f"`{m}`" in text)


def _review_corpus():
    """The prompt files #3250 is about: the spine, every lens rubric (calendared or not — a
    paraphrase in an off-calendar rubric drifts just as well), and every standalone
    review-family skill. Derived from the same discovery the SET guard uses."""
    from skill_paths import require_skill

    out = {oc.REVIEW_SPINE: str(require_skill(oc.REVIEW_SPINE))}
    for name, rel_path in oc.review_procedures().items():
        out[name] = os.path.join(REPO, rel_path)
    return out


def test_the_contract_owner_exists_and_is_the_heaviest_statement_of_it():
    """A single-source rule is only meaningful if the source is real and substantive. If the
    owner ever scored at or below the ceiling, the metric would be measuring nothing and every
    file would pass vacuously — a positive control for the guard itself."""
    mechanics = _contract_mechanics()
    assert len(mechanics) >= 10, f"only {len(mechanics)} mechanics derived from {ADR099_OWNER} — the shapes stopped matching"
    owner_text = open(os.path.join(REPO, ADR099_OWNER), encoding="utf-8").read()
    assert len(_mechanic_hits(owner_text, mechanics)) > MAX_MECHANICS_PER_FILE * 3


def test_review_corpus_points_at_the_contract_instead_of_restating_it():
    """The #3250 acceptance box, both halves.

    (a) No review-corpus file reproduces more than one contract mechanic — that is what a
        restatement looks like structurally.
    (b) Any file that NAMES ADR-099 must also name the owner's path. This half catches the
        light paraphrases the mechanic count cannot see (the old /fullreview line, "ADR-099:
        epics + ranked stories, Now/Next/Later", named zero literals and was still a second
        copy of the contract): a mention without a pointer is a paraphrase in the making.
    """
    mechanics = _contract_mechanics()
    restating, unpointed = {}, []
    for name, path in sorted(_review_corpus().items()):
        text = open(path, encoding="utf-8").read()
        hits = _mechanic_hits(text, mechanics)
        if len(hits) > MAX_MECHANICS_PER_FILE:
            restating[name] = hits
        if "ADR-099" in text and ADR099_OWNER not in text:
            unpointed.append(name)
    assert not restating, (
        f"review file(s) restate the ADR-099 filing contract: {restating}. It lives in exactly "
        f"ONE place ({ADR099_OWNER}) — point at it, do not paraphrase it (#3250)."
    )
    assert not unpointed, f"file(s) name ADR-099 without pointing at {ADR099_OWNER}: {unpointed}"


# The real paraphrases, verbatim from the 2026-08-27 tree, kept as the must-fail control. A guard
# nobody watched fail is a green light wired to nothing (#2578) — and these are the actual strings
# the issue was filed against, not a synthesized approximation of them.
_REAL_PARAPHRASES_2026_08_27 = {
    "platform-review": (
        "**Phase 4 — Rank + file (ADR-099).** Score = (Impact × Confidence) / Effort → Now/Next/Later; one `area:*` + "
        "one `model:*` label; epic per dimension with ≥3 findings, stories linked `Part of #epic`. Idempotency is the "
        "`review:*` label, reconciled via `gh issue list --label review:<slug> --state all` before filing."
    ),
    "sdlc-review": (
        "- File via the `issue-filer` agent per ADR-099: one epic per lens with ≥3 confirmed findings, scored stories, "
        "`area:*` mapping (most SDLC findings → `area:claude-workflow`), privacy discipline. Idempotency is the "
        "`review:*` label. Any QA-scorecard axis that regressed files a story the same way (`type:story`)."
    ),
    "craft-review": (
        "- File confirmed findings via the `issue-filer` agent per **ADR-099**: `type:story` (3–5 acceptance criteria, "
        "evidence, score line); `type:epic` when a dimension has ≥3 confirmed. `gate:owner` stamps human-only acts — "
        "stamp, don't skip filing."
    ),
}


@pytest.mark.parametrize("origin,text", sorted(_REAL_PARAPHRASES_2026_08_27.items()))
def test_the_paraphrase_guard_catches_the_real_paraphrases(origin, text):
    """Must-fail control: each real paraphrase must exceed the ceiling through the SAME
    function the live test uses."""
    hits = _mechanic_hits(text)
    assert len(hits) > MAX_MECHANICS_PER_FILE, f"{origin}: the guard did not catch a REAL paraphrase (hits={hits})"


def test_the_paraphrase_guard_does_not_flag_a_pointer_or_a_grading_subject():
    """The negative controls, without which the test above is just 'any mention of filing'.
    A pointer names the owner and no mechanics; a rubric grading one label vocabulary as its
    SUBJECT names exactly one and stays under the ceiling."""
    pointer = (
        "Filing is the `issue-filer` agent's contract, and it lives in exactly ONE place: "
        "`.claude/agents/issue-filer.md`. Read it there and hand the agent the verified findings."
    )
    subject = "| 3 | AI-engineering practice | The Claude org | `model:*` routing accuracy vs actual usage |"
    assert _mechanic_hits(pointer) == [], "a pointer must not trip the guard"
    assert len(_mechanic_hits(subject)) <= MAX_MECHANICS_PER_FILE, "grading one label vocabulary is not a restatement"


def test_anchor_is_not_refloated():
    """The anchor is the adoption date, a constant. If someone re-anchors to silence an
    overdue ritual, this pins the honest value; changing it must be a deliberate,
    reviewed act that also updates this test's reasoning."""
    assert oc.ADOPTED == date(2026, 8, 22)
