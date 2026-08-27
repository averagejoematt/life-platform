"""tests/test_backlog_hygiene_gate.py — the ADR-099 filing-contract linter (#1867, epic #1863).

Replays the PM backlog review's finding 11: exactly one rule validated a filed issue
(`check_story_labels.py`'s `model:*` check), so a filing that skipped the contract was
invisible. #1858 and #1859, filed 2026-07-27 mid-session, carried no milestone, no score
line and no outcome section and nothing noticed.

House style is #1189's "no vacuous scans": every rule below is planted with a fixture
that violates it AND a fixture that satisfies it, so a rule that silently stopped biting
(or bit everything) fails here. The wrap-wiring assertions mirrored the retired
tests/test_story_label_gate_1349.py, which #1872 deleted alongside the script it tested
(scripts/check_story_labels.py) once this linter's --blocking default absorbed its rule.
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "scripts"))

import advisory_failure_issue as afi  # noqa: E402
import backlog_contract as bc  # noqa: E402
import check_backlog_hygiene as hy  # noqa: E402
from skill_paths import require_skill as _skill  # the ONE skill registry (no hard-coded .claude paths)

ROOT = Path(_REPO)
WRAP = _skill("wrap")

NOW = datetime(2026, 7, 27, tzinfo=timezone.utc)
CANONICAL_SCORE = "**Score:** P2 · Impact 3 × Confidence 1.0 / Effort S(1) = 3.00 → Now"


def _body(
    outcome="**operator** — the contract stops depending on which agent read the brief.",
    acceptance=3,
    score=CANONICAL_SCORE,
    epic="**Epic:** #1863",
):
    parts = []
    if outcome:
        parts.append(f"## Problem\n\nsomething is wrong.\n\n## Outcome\n\n{outcome}\n")
    else:
        parts.append("## Problem\n\nsomething is wrong.\n")
    if acceptance:
        parts.append("## Acceptance\n\n" + "\n".join(f"- [ ] criterion {i}" for i in range(acceptance)) + "\n")
    tail = [line for line in (score, epic) if line]
    if tail:
        parts.append("\n".join(tail))
    return "\n".join(parts)


def _issue(
    number=1,
    title="a story",
    labels=("type:story", "area:claude-workflow", "model:opus", "prio:P2"),
    milestone="Now",
    body=None,
    updated="2026-07-27T00:00:00Z",
):
    return {
        "number": number,
        "title": title,
        "labels": [{"name": n} for n in labels],
        "milestone": {"title": milestone} if milestone else None,
        "body": _body() if body is None else body,
        "updatedAt": updated,
    }


def _ctx(**kwargs):
    return hy.build_ctx(_issue(**kwargs))


def _rules(findings):
    return sorted({f.rule for f in findings})


def _live_now_queue(n=3, start=900):
    """Three clean, non-blocked `Now` stories — the minimum live queue.

    Every whole-corpus test carries these so a fixture's own violation is the only
    thing the assertions see, rather than an incidental now_liveness firing.
    """
    return [_issue(number=start + i, labels=("type:story", "area:infra", "model:sonnet", "prio:P3")) for i in range(n)]


# ── the gate is wired into the /wrap skill (mirrors the old test_story_label_gate_1349) ──
def test_wrap_skill_invokes_the_hygiene_linter():
    wrap = WRAP.read_text(encoding="utf-8")
    assert "check_backlog_hygiene.py" in wrap, "#1867: the linter must actually be invoked from wrap.md, not merely described"


def test_wrap_e7_invocation_is_bare_blocking_not_advisory():
    """#1872: the (e7) gate invocation itself must be the bare (blocking-by-default) form —
    `--advisory` may still appear elsewhere (the (e9) later_staleness report, and as the
    documented opt-out), but not on the gate's own command line."""
    section = _wrap_step("e7")
    assert "python3 scripts/check_backlog_hygiene.py\n" in section, "(e7) must invoke the linter bare — blocking is the default post-#1872"
    assert "check_backlog_hygiene.py --advisory\n" not in section, "(e7)'s own gate call must not opt back into advisory mode"


def test_wrap_no_longer_references_the_deleted_label_gate_script():
    """#1872's proof: scripts/check_story_labels.py is deleted and no wrap step invokes it
    (mentioning it in past-tense narrative, e.g. 'absorbed and deleted', is fine)."""
    wrap = WRAP.read_text(encoding="utf-8")
    assert not (ROOT / "scripts" / "check_story_labels.py").exists()
    assert "python3 scripts/check_story_labels.py" not in wrap


def test_wrap_says_the_linter_is_blocking_by_default_and_names_the_flip_issue():
    wrap = WRAP.read_text(encoding="utf-8")
    section = wrap.split("check_backlog_hygiene.py")[1][:1200]
    assert "#1872" in section, "the wrap step must name the issue that flipped it blocking"


# ── the three #1870 wrap steps: gate (e7), closure comment (e8), queue upkeep (e9) ──
def _wrap_step(letter: str) -> str:
    """The body of one lettered wrap step, up to the next `### (` heading."""
    wrap = WRAP.read_text(encoding="utf-8")
    marker = f"### ({letter})"
    assert marker in wrap, f"#1870: wrap.md has no {marker} step"
    return wrap.split(marker, 1)[1].split("### (", 1)[0]


def test_wrap_e7_is_the_hygiene_gate_in_the_established_shape():
    """#1870 AC1: the #1867 advisory line is formalized into its own (e7) gate slot —
    same 'same shape as (d)/(e)/(e2)...' lettering every other wrap gate carries.
    #1872 flipped this gate's own invocation to the bare (blocking) form."""
    section = _wrap_step("e7")
    assert "same shape as" in section.splitlines()[0], "(e7) must declare the established gate shape in its heading"
    assert "python3 scripts/check_backlog_hygiene.py\n" in section
    assert "may not be left unfixed" in section, "#1870: the wrap discipline is that a printed violator gets fixed"
    assert "#1872" in section, "(e7) must name the issue that flipped the exit code, or it reads as a permanent no-op"


def test_wrap_e8_carries_the_adr099_closure_contract_verbatim():
    """#1870 AC2: the closure comment is ADR-099's amendment ¶3, quoted — not re-invented."""
    section = _wrap_step("e8")
    assert "**Shipped:** <what changed> · PR #N · <live evidence>" in section
    assert "**Outcome:** <realized|partial|not-realized> — <did the ## Outcome sentence come true?>" in section
    assert "not planned" in section, "a `not planned` close gets the same comment with a one-clause reason"
    assert "gh issue comment" in section, "the step must name the command, not merely describe the duty"
    # the ADR is the single source of the contract's shape — the two must not drift apart
    adr = (ROOT / "docs" / "DECISIONS.md").read_text(encoding="utf-8")
    assert "**Shipped:** <what changed> · PR #N · <live evidence>" in adr


def test_wrap_e9_refills_now_and_sweeps_later():
    """#1870 AC3+AC4: one step, two halves — the Now refill (via the ranker) and the
    `Later` promote-or-close call (via the linter's later_staleness rule)."""
    section = _wrap_step("e9")
    assert "backlog_next.py --milestone Next" in section, "the refill must promote by the stored rank, not a fresh re-score"
    assert "--rule later_staleness" in section, "the Later sweep's input is the linter's own staleness rule"
    assert f"{hy.NOW_LIVENESS_MIN} actionable" in section or f"fewer than\n  {hy.NOW_LIVENESS_MIN}" in section
    assert "promote-or-close" in section
    assert "**Backlog:**" in section, "#1870: the promotion has to be noted in the handover"


def test_wrap_guardrails_register_all_three_1870_steps():
    """The guardrails list is the wrap's own contract restatement — a step absent from it
    is a step a hurried session can skip silently."""
    guardrails = WRAP.read_text(encoding="utf-8").split("## Guardrails", 1)[1]
    assert guardrails.count("#1870") >= 3, "each of (e7)/(e8)/(e9) needs its own guardrail bullet"
    for phrase in ("check_backlog_hygiene.py", "closure comment", "promote-or-close"):
        assert phrase in guardrails, f"#1870: the guardrails list never mentions {phrase!r}"


def test_conventions_gate_registry_routes_all_three_1870_steps():
    """AC1 says 'registered in both files' — the §9 registry is the routing index a
    session reads to answer 'which gate owns this defect class?'."""
    registry = (ROOT / "docs" / "CONVENTIONS.md").read_text(encoding="utf-8")
    section = registry.split("## 9. Gate registry", 1)[1].split("## Facts that drift", 1)[0]
    for step in ("step (e7)", "step (e8)", "step (e9)"):
        assert step in section, f"#1870: the gate registry has no row pointing at {step}"
    assert "step (e6) — advisory" not in section, "#1870: the filing-contract row still points at the old (e6) slot"
    assert "backlog_next.py" in section


# ── one contract surface: the linter compiles no grammar of its own ─────────────
def test_linter_imports_the_shared_contract_and_compiles_no_regex():
    """The failure this guards: a second copy of the grammar drifting from the ranker's.
    Same bar tests/test_backlog_next_1866.py holds backlog_next.py to."""
    src = (ROOT / "scripts" / "check_backlog_hygiene.py").read_text(encoding="utf-8")
    assert "import backlog_contract" in src
    assert "re.compile" not in src, "the linter must import the grammar from backlog_contract, never compile its own"


def test_epic_link_and_stories_parsers_live_in_the_contract_module():
    for name in ("parse_epic_link", "find_epic_line", "story_refs", "EPIC_LINE_RE"):
        assert hasattr(bc, name), f"backlog_contract.{name} is the shared contract surface the linter imports"


# ── rule: exactly one type:* ───────────────────────────────────────────────────
def test_one_type_label_bites_on_zero_and_on_two():
    assert hy.rule_one_type_label(_ctx()) == []
    assert _rules(hy.rule_one_type_label(_ctx(labels=("area:infra", "model:opus")))) == ["one_type_label"]
    assert _rules(hy.rule_one_type_label(_ctx(labels=("type:story", "type:bug", "area:infra", "model:opus")))) == ["one_type_label"]


# ── rule: exactly one area:* ───────────────────────────────────────────────────
def test_one_area_label_bites_on_zero_and_on_two():
    assert hy.rule_one_area_label(_ctx()) == []
    assert _rules(hy.rule_one_area_label(_ctx(labels=("type:story", "model:opus")))) == ["one_area_label"]
    assert _rules(hy.rule_one_area_label(_ctx(labels=("type:story", "area:infra", "area:site-ux", "model:opus")))) == ["one_area_label"]


# ── rule: exactly one model:* (absorbed from check_story_labels.py, #1349) ─────
def test_one_model_label_bites_and_absorbs_the_check_story_labels_rule():
    assert hy.rule_one_model_label(_ctx()) == []
    hit = hy.rule_one_model_label(_ctx(labels=("type:story", "area:infra")))
    assert [f.rule for f in hit] == ["one_model_label"]
    assert "model:*" in hit[0].message


def test_one_model_label_is_stricter_than_the_script_it_absorbs():
    """check_story_labels.py accepts "some model:* label"; this rule requires exactly one,
    which is why it can replace it rather than merely duplicate it."""
    two = _ctx(labels=("type:story", "area:infra", "model:opus", "model:sonnet"))
    assert _rules(hy.rule_one_model_label(two)) == ["one_model_label"]


# ── rule: prio:* on work issues ────────────────────────────────────────────────
def test_prio_label_bites_on_a_story_without_one_and_spares_epics():
    assert hy.rule_prio_label(_ctx()) == []
    assert _rules(hy.rule_prio_label(_ctx(labels=("type:story", "area:infra", "model:opus")))) == ["prio_label"]
    epic = _ctx(labels=("type:epic", "area:infra", "model:fable"), milestone=None)
    assert hy.rule_prio_label(epic) == [], "an epic is a container, not ranked work — the prio rule must not fire on it"


# ── rule: a milestone on work issues ───────────────────────────────────────────
def test_milestone_bites_on_the_pinned_1858_1859_evidence():
    """The exact filings the epic measured: no milestone, so invisible to every ranked query."""
    assert hy.rule_milestone(_ctx()) == []
    for number in (1858, 1859):
        hit = hy.rule_milestone(_ctx(number=number, milestone=None))
        assert [f.number for f in hit] == [number]
        assert "invisible to every ranked query" in hit[0].message


# ── rule: ## Outcome names a sanctioned audience ───────────────────────────────
def test_outcome_audience_bites_when_the_section_is_missing():
    assert hy.rule_outcome_audience(_ctx()) == []
    hit = hy.rule_outcome_audience(_ctx(body=_body(outcome=None)))
    assert [f.rule for f in hit] == ["outcome_audience"]
    assert "no `## Outcome` section" in hit[0].message


def test_outcome_audience_bites_when_no_sanctioned_audience_is_named():
    hit = hy.rule_outcome_audience(_ctx(body=_body(outcome="**stakeholders** — things improve broadly.")))
    assert [f.rule for f in hit] == ["outcome_audience"]
    assert "no sanctioned audience" in hit[0].message


def test_every_sanctioned_audience_is_accepted():
    """All four north-star audiences (PLATFORM_NORTH_STAR.md:48) plus the amendment's
    `operator`. A typo'd token set here would silently reject the whole corpus."""
    for lead in ("Reddit newcomers", "Matthew (the N=1 subject)", "Friends & family", "Health / quantified-self enthusiasts", "operator"):
        line = f"**{lead}** — the value that changes for them."
        assert hy.outcome_audience(line) is not None, f"sanctioned audience rejected: {lead}"


def test_audience_is_read_from_the_lead_not_the_whole_sentence():
    """ "Matthew" appears in half the outcome sentences on this platform; matching the whole
    line would hand every audience-free issue a phantom audience."""
    assert hy.outcome_audience("**stakeholders** — Matthew gets a better dashboard.") is None
    assert hy.outcome_audience("Matthew (the N=1 subject) — a daily instrument.") == "Matthew (the N=1 subject)"


def test_legacy_outcome_if_fixed_is_reported_as_its_own_kind_of_violation():
    hit = hy.rule_outcome_audience(_ctx(body="**outcome_if_fixed:** the ledger becomes browsable.\n"))
    assert [f.rule for f in hit] == ["outcome_audience"]
    assert "retired `outcome_if_fixed` form" in hit[0].message


# ── rule: 3–5 ## Acceptance boxes ──────────────────────────────────────────────
def test_acceptance_count_bites_below_3_above_5_and_at_zero():
    assert hy.rule_acceptance_count(_ctx()) == []
    for n in (0, 1, 2, 6, 9):
        hit = hy.rule_acceptance_count(_ctx(body=_body(acceptance=n)))
        assert [f.rule for f in hit] == ["acceptance_count"], f"{n} acceptance boxes should violate the 3–5 contract"
    for n in (3, 4, 5):
        assert hy.rule_acceptance_count(_ctx(body=_body(acceptance=n))) == []


def test_acceptance_count_does_not_count_checkboxes_outside_the_section():
    """The trap found while filing #1867 itself: a body legitimately quotes `- [ ]` when
    describing the rule, and a whole-body count reads those as acceptance criteria."""
    body = _body(acceptance=3) + "\n\n## Notes\n\n- [ ] not a criterion\n- [ ] nor this\n- [ ] nor this either\n"
    assert hy.rule_acceptance_count(hy.build_ctx(_issue(body=body))) == []


# ── rule: the canonical score line, milestone-agreed ───────────────────────────
def test_score_line_bites_when_absent():
    hit = hy.rule_score_line_canonical(_ctx(body=_body(score=None)))
    assert [f.rule for f in hit] == ["score_line_canonical"]
    assert "no `**Score:**` line" in hit[0].message


def test_score_line_bites_on_each_measured_legacy_grammar():
    """The four grammars finding 3 measured in the wild; ADR-099 sanctions exactly one."""
    for legacy in (
        "**Score:** T4×W4/M",
        "**Score:** P2*1.0/L=4 = 0.75",
        "**Score:** P2 → Impact 3 × Confidence 1.0 / Effort S(1) = 3.0 → **Now**",
        "**Score:** Impact 2 × Confidence 0.9 / Effort S(1) = **1.8** (Next)",
    ):
        hit = hy.rule_score_line_canonical(_ctx(body=_body(score=legacy)))
        assert [f.rule for f in hit] == ["score_line_canonical"], f"legacy grammar accepted: {legacy}"
        assert "retired grammar" in hit[0].message


def test_score_line_bites_when_its_arrow_milestone_disagrees_with_the_real_one():
    """The defect that hides work from both readers: a body ranked `→ Now` on an issue
    parked in `Later` reads as live work and is unreachable to the selector."""
    line = "**Score:** P2 · Impact 3 × Confidence 1.0 / Effort S(1) = 3.00 → Now"
    hit = hy.rule_score_line_canonical(_ctx(milestone="Later", body=_body(score=line)))
    messages = [f.message for f in hit if f.severity == hy.VIOLATION]
    assert messages and "says `→ Now` but the issue is on milestone `Later`" in messages[0]


def test_score_line_milestone_agreement_passes_when_they_match():
    line = "**Score:** P3 · Impact 2 × Confidence 1.0 / Effort M(2) = 1.00 → Later"
    assert hy.rule_score_line_canonical(_ctx(milestone="Later", body=_body(score=line))) == []


def test_score_line_value_checks_are_advisory_not_blocking():
    """backlog_contract deliberately accepts P0 and any decimal so the RANKER never drops a
    well-formed line; those value rules land here, but as advisories — cosmetics must not
    outrank an unreachable-work defect once #1872 flips the gate."""
    one_decimal = "**Score:** P2 · Impact 3 × Confidence 1.0 / Effort S(1) = 3.0 → Now"
    hits = hy.rule_score_line_canonical(_ctx(body=_body(score=one_decimal)))
    assert hits and all(f.severity == hy.ADVISORY for f in hits)
    assert any("two decimal places" in f.message for f in hits)

    bad_math = "**Score:** P2 · Impact 4 × Confidence 1.0 / Effort M(2) = 3.00 → Now"
    hits = hy.rule_score_line_canonical(_ctx(body=_body(score=bad_math)))
    assert any("disagrees with its own arithmetic" in f.message and f.severity == hy.ADVISORY for f in hits)

    # Exact half boundaries, both binary-exact in float: 3 × 0.5 / 4 = 0.375 → 0.38 and
    # 3 × 0.75 / 2 = 1.125 → 1.13 under the hand-written half-up convention. An epsilon
    # compare false-fires on the first; float's half-even `.2f` rendering on the second.
    for boundary in (
        "**Score:** P3 · Impact 3 × Confidence 0.5 / Effort L(4) = 0.38 → Later",
        "**Score:** P3 · Impact 3 × Confidence 0.75 / Effort M(2) = 1.13 → Later",
    ):
        hits = hy.rule_score_line_canonical(_ctx(milestone="Later", body=_body(score=boundary)))
        assert not any("disagrees with its own arithmetic" in f.message for f in hits)

    p0 = "**Score:** P0 · Impact 3 × Confidence 1.0 / Effort S(1) = 3.00 → Now"
    assert any("P1–P3" in f.message and f.severity == hy.ADVISORY for f in hy.rule_score_line_canonical(_ctx(body=_body(score=p0))))


# ── rule: the **Epic:** link ───────────────────────────────────────────────────
def test_epic_link_bites_when_absent():
    hit = hy.rule_epic_link(_ctx(body=_body(epic=None)))
    assert [f.rule for f in hit] == ["epic_link"]
    assert "no `**Epic:**` line" in hit[0].message


def test_epic_link_accepts_an_explicit_none_with_a_reason():
    assert hy.rule_epic_link(_ctx(body=_body(epic="**Epic:** none — a standalone one-file fix"))) == []


def test_epic_link_bites_on_a_bare_none_with_no_reason():
    hit = hy.rule_epic_link(_ctx(body=_body(epic="**Epic:** none")))
    assert [f.rule for f in hit] == ["epic_link"]
    assert "carries no reason" in hit[0].message


def test_epic_link_bites_on_a_malformed_line_and_says_so():
    hit = hy.rule_epic_link(_ctx(body=_body(epic="**Epic:** part of the backlog epic")))
    assert [f.rule for f in hit] == ["epic_link"]
    assert "malformed" in hit[0].message, "'absent' and 'present but malformed' are different facts"


def test_parse_epic_link_reads_both_forms():
    assert bc.parse_epic_link("**Epic:** #1863").number == 1863
    none_form = bc.parse_epic_link("**Epic:** none — stands alone")
    assert none_form.is_none and none_form.reason == "stands alone"
    assert bc.parse_epic_link("no epic line here") is None


# ── rule: an epic's ## Stories covers every issue naming it ────────────────────
def _epic(number=1863, stories=(1867,)):
    body = "## Outcome\n\n**operator** — the program's value.\n\n## Done when\n\n- it is done\n\n## Stories\n\n" + "\n".join(
        f"- [ ] #{s} — a story (Next · opus · P2)" for s in stories
    )
    return _issue(number=number, labels=("type:epic", "area:claude-workflow", "model:fable"), milestone=None, body=body)


def test_epic_story_coverage_bites_when_a_child_is_not_listed():
    child = _issue(number=1867, body=_body(epic="**Epic:** #1863"))
    ctxs = [hy.build_ctx(i) for i in (_epic(stories=(1866,)), child)]
    hits = hy.rule_epic_story_coverage(ctxs)
    assert [(f.rule, f.number) for f in hits] == [("epic_story_coverage", 1863)]
    assert "#1867" in hits[0].message


def test_epic_story_coverage_passes_when_the_roster_is_complete():
    child = _issue(number=1867, body=_body(epic="**Epic:** #1863"))
    ctxs = [hy.build_ctx(i) for i in (_epic(stories=(1867,)), child)]
    assert hy.rule_epic_story_coverage(ctxs) == []


def test_epic_story_coverage_ignores_epics_outside_the_fetched_corpus():
    """A story naming a CLOSED epic can't be verified from the open corpus — skip it
    rather than manufacture a violation nobody can fix."""
    child = _issue(number=1867, body=_body(epic="**Epic:** #1234"))
    assert hy.rule_epic_story_coverage([hy.build_ctx(child)]) == []


def test_story_refs_is_section_scoped():
    """An epic body cites plenty of issue numbers in prose; only the task list is the roster."""
    body = "## Problem\n\nsee #1111 and #2222 for evidence.\n\n## Stories\n\n- [ ] #1864 — a story\n- [x] #1865 — another\n"
    assert bc.story_refs(body) == [1864, 1865]


# ── queue rule: Now-liveness ───────────────────────────────────────────────────
def test_now_liveness_bites_on_the_measured_all_gated_now_queue():
    """The measured failure: all three open `Now` stories carried `gate:owner`, so the
    documented seed query returned zero actionable work and nobody was told."""
    gated = [
        hy.build_ctx(_issue(number=n, labels=("type:story", "area:infra", "model:opus", "prio:P2", "gate:owner")))
        for n in (1738, 1622, 1571)
    ]
    hits = hy.rule_now_liveness(gated)
    assert [f.rule for f in hits] == ["now_liveness"]
    assert hits[0].number is None, "a queue-level finding is not attributable to one issue"
    assert "0 non-blocked story(ies)" in hits[0].message and "3 more are gate:owner" in hits[0].message


def test_now_liveness_passes_with_three_startable_stories():
    assert hy.rule_now_liveness([hy.build_ctx(i) for i in _live_now_queue()]) == []


def test_now_liveness_bites_at_two():
    assert _rules(hy.rule_now_liveness([hy.build_ctx(i) for i in _live_now_queue(n=2)])) == ["now_liveness"]


# ── queue rule: Later staleness (advisory, injected clock) ─────────────────────
def test_later_staleness_bites_past_60_days_and_is_advisory():
    old = (NOW - timedelta(days=90)).isoformat().replace("+00:00", "Z")
    ctxs = [hy.build_ctx(_issue(number=7, milestone="Later", updated=old))]
    hits = hy.rule_later_staleness(ctxs, NOW)
    assert [(f.rule, f.number, f.severity) for f in hits] == [("later_staleness", 7, hy.ADVISORY)]
    assert "untouched for 90d" in hits[0].message


def test_later_staleness_spares_fresh_later_issues_and_stale_now_issues():
    fresh = (NOW - timedelta(days=10)).isoformat().replace("+00:00", "Z")
    old = (NOW - timedelta(days=400)).isoformat().replace("+00:00", "Z")
    ctxs = [
        hy.build_ctx(_issue(number=1, milestone="Later", updated=fresh)),
        hy.build_ctx(_issue(number=2, milestone="Now", updated=old)),
    ]
    assert hy.rule_later_staleness(ctxs, NOW) == []


def test_staleness_clock_is_injected_never_wall_clock():
    """The golden-tests wall-clock lesson: a rule that calls datetime.now() internally is a
    time bomb no fixture can pin. `--now` must actually move the cutoff."""
    stamp = (NOW - timedelta(days=61)).isoformat().replace("+00:00", "Z")
    ctxs = [hy.build_ctx(_issue(number=5, milestone="Later", updated=stamp))]
    assert len(hy.rule_later_staleness(ctxs, NOW)) == 1
    assert hy.rule_later_staleness(ctxs, NOW - timedelta(days=30)) == [], "moving --now backwards must un-stale the issue"


# ── the whole check + the CLI contract ─────────────────────────────────────────
def test_a_fully_contract_compliant_corpus_is_clean():
    """The non-vacuous half: if this ever fails, a rule is over-flagging and every real
    violation below is noise."""
    corpus = _live_now_queue()
    findings = hy.check(corpus, now=NOW)
    assert findings == [], f"a compliant corpus must lint clean, got: {findings}"


def test_check_reports_every_rule_over_a_deliberately_dirty_corpus():
    dirty = _live_now_queue() + [
        _issue(number=1858, labels=("type:story", "area:infra"), milestone=None, body="just a paragraph, no sections at all."),
        _issue(number=1867, labels=("type:story", "area:infra", "model:opus", "prio:P2"), body=_body(epic="**Epic:** #1863")),
        _epic(number=1863, stories=()),
        _issue(
            number=99,
            milestone="Later",
            updated="2026-01-01T00:00:00Z",
            body=_body(score="**Score:** P3 · Impact 2 × Confidence 1.0 / Effort M(2) = 1.00 → Later"),
        ),
    ]
    rules = _rules(hy.check(dirty, now=NOW))
    for expected in (
        "one_model_label",
        "prio_label",
        "milestone",
        "outcome_audience",
        "acceptance_count",
        "score_line_canonical",
        "epic_link",
        "epic_story_coverage",
        "later_staleness",
    ):
        assert expected in rules, f"rule {expected} did not fire on a corpus planted to violate it: {rules}"


def test_cli_advisory_mode_prints_violations_and_exits_zero(tmp_path, capsys):
    """The explicit `--advisory` opt-out: report the violations, never fail the caller.
    Pre-#1872 this was the unflagged default; post-#1872 it must be requested."""
    fixture = tmp_path / "issues.json"
    fixture.write_text(json.dumps([_issue(number=1858, labels=("type:story",), milestone=None, body="nothing")]), encoding="utf-8")
    rc = hy.main(["--issues-json", str(fixture), "--advisory", "--now", "2026-07-27T00:00:00Z"])
    out = capsys.readouterr().out
    assert rc == 0, "advisory mode must never exit non-zero"
    assert "#1858" in out and "ADVISORY MODE" in out


def test_cli_blocking_mode_exists_and_exits_one(tmp_path, capsys):
    """The explicit `--blocking` flag must keep working (kept for explicit callers) even
    though it is now redundant with the default."""
    fixture = tmp_path / "issues.json"
    fixture.write_text(json.dumps([_issue(number=1858, labels=("type:story",), milestone=None, body="nothing")]), encoding="utf-8")
    rc = hy.main(["--issues-json", str(fixture), "--blocking", "--now", "2026-07-27T00:00:00Z"])
    capsys.readouterr()
    assert rc == 1


# ── mutation proof #1 (#1872): a deliberately non-conforming issue, DEFAULT invocation ──
def test_cli_default_mode_is_now_blocking_and_exits_one(tmp_path, capsys):
    """#1872's core flip, proven directly: the BARE invocation (no --advisory, no
    --blocking) must behave exactly like --blocking now — this is what "the --advisory
    default is removed" means operationally. A deliberately non-conforming issue (no
    type/area/model/prio/milestone/outcome/acceptance/score/epic — a fixture that
    violates nearly every rule at once) must exit 1 with zero flags passed."""
    fixture = tmp_path / "issues.json"
    fixture.write_text(
        json.dumps(
            [
                {
                    "number": 99999,
                    "title": "a deliberately non-conforming issue",
                    "labels": [],
                    "milestone": None,
                    "body": "just a paragraph, no sections, no score line, no epic link.",
                    "updatedAt": "2026-08-08T00:00:00Z",
                }
            ]
        ),
        encoding="utf-8",
    )
    rc = hy.main(["--issues-json", str(fixture), "--now", "2026-08-08T00:00:00Z"])
    capsys.readouterr()
    assert rc == 1, "the default invocation (no flags) must exit 1 on a violating corpus post-#1872"


def test_cli_blocking_mode_does_not_fail_on_advisories_alone(tmp_path, capsys):
    """Staleness is a triage signal, not a defect — it must stay non-blocking after the flip."""
    old = (NOW - timedelta(days=200)).isoformat().replace("+00:00", "Z")
    stale = _issue(
        number=42,
        milestone="Later",
        updated=old,
        body=_body(score="**Score:** P3 · Impact 2 × Confidence 1.0 / Effort M(2) = 1.00 → Later"),
    )
    fixture = tmp_path / "issues.json"
    fixture.write_text(json.dumps(_live_now_queue() + [stale]), encoding="utf-8")
    rc = hy.main(["--issues-json", str(fixture), "--blocking", "--now", "2026-07-27T00:00:00Z"])
    out = capsys.readouterr().out
    assert "later_staleness" in out
    assert rc == 0, "an advisory-only corpus must pass even in blocking mode"


def test_cli_clean_corpus_prints_ok(tmp_path, capsys):
    fixture = tmp_path / "issues.json"
    fixture.write_text(json.dumps(_live_now_queue()), encoding="utf-8")
    rc = hy.main(["--issues-json", str(fixture), "--now", "2026-07-27T00:00:00Z"])
    out = capsys.readouterr().out
    assert rc == 0 and out.startswith("OK —")


def test_cli_rule_filter_narrows_the_report(tmp_path, capsys):
    fixture = tmp_path / "issues.json"
    fixture.write_text(json.dumps([_issue(number=1858, labels=("type:story",), milestone=None, body="nothing")]), encoding="utf-8")
    hy.main(["--issues-json", str(fixture), "--rule", "milestone", "--now", "2026-07-27T00:00:00Z"])
    out = capsys.readouterr().out
    assert "milestone" in out and "acceptance_count" not in out


# ── mutation proof #2 (#1872): a simulated gh/network failure, DEFAULT invocation ──
def test_cli_is_fail_open_when_gh_is_unavailable_in_both_modes(monkeypatch, capsys):
    """No network/gh auth in CI's test job — a live-fetch failure must never red the suite
    or wedge a wrap, in ANY mode, including the new blocking default. `hy.main([])` here
    IS the post-#1872 default (no flags) — this is the fail-open half of the flip's
    non-negotiable bar: a missing `gh` auth must exit 0 even though violations would
    otherwise exit 1."""
    monkeypatch.setattr(hy, "_fetch_live_issues", lambda: None)
    assert hy.main([]) == 0, "bare invocation (the blocking default) must still fail OPEN on a live-fetch failure"
    assert hy.main(["--blocking"]) == 0
    assert hy.main(["--advisory"]) == 0
    capsys.readouterr()


# ══ #3065: the `auto-filed` ops-tracker carve-out (design (a), decided 2026-08-26) ══
#
# The evidence: #3064, auto-filed by the visual-qa advisory workflow, was open during
# the 2026-08-23 D1 wrap and red this blocking gate. Design (b) — teach the FILER to
# emit the full ADR-099 shape — was rejected (see the linter's docstring); design (a)
# carves these issues out and holds them to TRACKER_RULES instead.
#
# Everything below builds its tracker from the REAL filer (`advisory_failure_issue.run`
# through a recording client), never from a hand-typed replica of its body. A replica
# is exactly the fixture that stops being the wire the day the template changes.

SLUG_3064 = "visual-qa-standalone"


class _RecordingClient:
    """The minimum `advisory_failure_issue.run` needs, recording the filed issue."""

    def __init__(self):
        self.created = []

    def list_open_issues(self, label):
        return []

    def ensure_label(self, name, color, description):
        pass

    def create_issue(self, title, body, labels):
        self.created.append({"title": title, "body": body, "labels": labels})
        return {"number": 3064}

    def comment(self, number, body):
        pass

    def close_issue(self, number):
        pass


def _filed_tracker(number=3064, labels=None, body=None, milestone=None):
    """The issue the advisory filer ACTUALLY creates, as `gh issue list --json` shapes it."""
    client = _RecordingClient()
    afi.run(
        "file",
        SLUG_3064,
        "Visual QA (standalone)",
        "3 pages failed the inline-SVG assertion",
        "https://github.com/averagejoematt/life-platform/actions/runs/123456",
        "schedule",
        client,
        now_iso="2026-08-23T09:14:00Z",
    )
    filed = client.created[0]
    return {
        "number": number,
        "title": filed["title"],
        "labels": [{"name": n} for n in (filed["labels"] if labels is None else labels)],
        "milestone": {"title": milestone} if milestone else None,
        "body": filed["body"] if body is None else body,
        "updatedAt": "2026-08-23T09:14:00Z",
    }


# ── the join: the linter's three literals are the filer's, not a copy ──────────
def test_carve_out_literals_are_pinned_to_the_filer_not_retyped():
    """A rename in advisory_failure_issue.py must red HERE rather than silently widen
    the carve-out (a wrong label matches nothing) or silently void it (the marker
    stops matching and every tracker reds the next wrap)."""
    assert hy.TRACKER_LABEL == afi.MARKER_LABEL
    assert afi.issue_marker(SLUG_3064).startswith(hy.TRACKER_MARKER)
    assert hy.TRACKER_CLOSE_POLICY in afi.build_issue_body(SLUG_3064, "n", "u", "t", "schedule")


def test_the_carve_out_predicate_is_the_filers_own_ownership_test():
    """`is_tracker`'s first two conditions are exactly what `find_open_issue` matches on
    when it decides which issue to CLOSE. That equivalence is the deterrent: forging the
    pair to dodge the contract hands the workflow the right to close your issue."""
    filed = _filed_tracker()
    assert hy.is_tracker(hy.build_ctx(filed))
    api_shaped = {"number": 3064, "body": filed["body"], "labels": [{"name": afi.MARKER_LABEL}]}
    assert afi.find_open_issue([api_shaped], SLUG_3064) is api_shaped


# ── the negative control, measured BEFORE it is trusted ───────────────────────
def test_the_filed_tracker_really_does_violate_the_adr099_backlog_contract():
    """The pre-#3065 state, measured rather than asserted from memory — this is the red
    that #3064 produced at the D1 wrap. If this ever comes back empty, every "passes
    now" assertion below is vacuous: the tracker would have been contract-clean all
    along and the carve-out would be proving nothing."""
    ctx = hy.build_ctx(_filed_tracker())
    violated = sorted({f.rule for rule in hy.PER_ISSUE_RULES for f in rule(ctx)})
    assert violated, "a tracker that already satisfies the backlog contract makes this whole test block vacuous"
    for rule in ("one_type_label", "one_model_label", "outcome_audience"):
        assert rule in violated, f"#3064's measured red included {rule}; got {violated}"


# ── ACCEPTANCE BOX 3: a wrap with an open auto-filed issue passes (e7) clean ───
def test_e7_passes_clean_with_an_open_auto_filed_tracker_in_the_corpus(tmp_path):
    """Box 3, proved by RUNNING the gate as (e7) runs it — a real subprocess, the bare
    blocking invocation, a real exit status. Reading the linter and reasoning that it
    would pass is the thing this repo has been burned by."""
    fixture = tmp_path / "issues.json"
    fixture.write_text(json.dumps(_live_now_queue() + [_filed_tracker()]), encoding="utf-8")
    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "check_backlog_hygiene.py"),
            "--issues-json",
            str(fixture),
            "--now",
            "2026-08-23T00:00:00Z",
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, f"(e7) still reds on an open auto-filed tracker:\n{proc.stdout}\n{proc.stderr}"
    assert proc.stdout.startswith("OK —"), proc.stdout


def test_the_carve_out_does_not_silence_a_malformed_backlog_issue_beside_it(tmp_path):
    """The other direction, same corpus: a genuinely malformed STORY still reds even when
    a clean tracker sits next to it. An exemption that quietly took the gate down with it
    would be indistinguishable from one that works."""
    malformed = _issue(number=1858, labels=("type:story", "area:infra"), milestone=None, body="just a paragraph, no sections at all.")
    fixture = tmp_path / "issues.json"
    fixture.write_text(json.dumps(_live_now_queue() + [_filed_tracker(), malformed]), encoding="utf-8")
    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "check_backlog_hygiene.py"),
            "--issues-json",
            str(fixture),
            "--now",
            "2026-08-23T00:00:00Z",
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 1, f"a malformed story must still red the gate:\n{proc.stdout}"
    assert "#1858" in proc.stdout and "#3064" not in proc.stdout


# ── what stops the carve-out becoming a hole: each condition, mutated ──────────
def _rc(*issues, now=datetime(2026, 8, 23, tzinfo=timezone.utc)):
    return [f for f in hy.check(list(issues) + _live_now_queue(), now=now) if f.severity == hy.VIOLATION]


def test_a_type_label_beats_the_exemption_so_a_real_story_cannot_wear_it():
    """The hole the brief names: add one label to a real story and drive it through.
    Declaring a `type:*` IS declaring backlog work, so the full contract reapplies —
    a `type:story` wearing `auto-filed` and the marker reds exactly as it would without
    them."""
    smuggled = _filed_tracker(labels=(afi.MARKER_LABEL, "area:infra", "type:story"))
    rules = sorted({f.rule for f in _rc(smuggled)})
    assert not hy.is_tracker(hy.build_ctx(smuggled))
    for expected in (
        "one_model_label",
        "prio_label",
        "milestone",
        "outcome_audience",
        "acceptance_count",
        "score_line_canonical",
        "epic_link",
    ):
        assert expected in rules, f"the full contract must reapply to a type-labelled issue; got {rules}"


def test_the_label_alone_is_not_enough_without_the_filers_marker():
    """Hand-slapping `auto-filed` onto an ordinary type-less issue does NOT exempt it:
    the body marker is the filer's signature and this issue does not carry it."""
    faked = _filed_tracker(labels=(afi.MARKER_LABEL, "area:infra"), body="I am not really an ops tracker.\n\n**Close policy:** trust me.")
    assert not hy.is_tracker(hy.build_ctx(faked))
    assert "one_type_label" in {f.rule for f in _rc(faked)}


def test_the_marker_alone_is_not_enough_without_the_label():
    """And the mirror: the marker without `auto-filed` is not the pair the filer owns."""
    unlabelled = _filed_tracker(labels=("area:infra",))
    assert not hy.is_tracker(hy.build_ctx(unlabelled))
    assert "one_type_label" in {f.rule for f in _rc(unlabelled)}


def test_the_tracker_contract_is_not_zero_rules_the_close_policy_is_required():
    """The price of the carve-out. The exemption is granted BECAUSE the lifecycle lives
    in the body; strip the close policy out of the filer's template and this bites."""
    stripped = _filed_tracker()
    stripped["body"] = stripped["body"].replace(hy.TRACKER_CLOSE_POLICY, "**Notes:**")
    assert hy.is_tracker(hy.build_ctx(stripped))
    hits = _rc(stripped)
    assert [f.rule for f in hits] == ["tracker_close_policy"], hits
    assert "#3065" in hits[0].message


def test_a_tracker_still_has_to_be_routable_to_one_area():
    """The other half of TRACKER_RULES — exempt from ADR-099 is not exempt from being
    findable. Zero `area:*` and two `area:*` both red."""
    for labels in ((afi.MARKER_LABEL,), (afi.MARKER_LABEL, "area:infra", "area:site-ux")):
        hits = _rc(_filed_tracker(labels=labels))
        assert [f.rule for f in hits] == ["one_area_label"], f"{labels} -> {hits}"


def test_the_carve_out_cannot_be_used_to_fake_a_live_now_queue():
    """Reason 1 for rejecting design (b), enforced rather than argued: `now_liveness`
    counts `type:story`, so trackers can never prop the queue up — three of them parked
    on `Now` still leave the queue measured as dead."""
    trackers = [_filed_tracker(number=3060 + i, milestone="Now") for i in range(3)]
    ctxs = [hy.build_ctx(t) for t in trackers]
    assert all(hy.is_tracker(c) for c in ctxs)
    assert _rules(hy.rule_now_liveness(ctxs)) == ["now_liveness"]


def test_the_dated_decision_and_the_rejected_alternative_are_recorded_in_both_modules():
    """Acceptance boxes 1 and 2: the decision is dated where it is ENFORCED (the linter),
    and the rejection is recorded where the rejected design would have been BUILT (the
    filer's template) — so neither side can be re-litigated by accident."""
    linter = (ROOT / "scripts" / "check_backlog_hygiene.py").read_text(encoding="utf-8")
    filer = (ROOT / "scripts" / "advisory_failure_issue.py").read_text(encoding="utf-8")
    for src, name in ((linter, "check_backlog_hygiene.py"), (filer, "advisory_failure_issue.py")):
        assert "2026-08-26" in src, f"{name}: the decision must carry its date"
        assert "#3065" in src, f"{name}: the decision must name its issue"
        assert "REJECTED" in src or "rejected" in src, f"{name}: the losing design must be recorded as rejected, with the reason"
    assert "backlog_next.py" in linter and "rule_now_liveness" in filer, "the rejection has to state its reasons, not just its verdict"
