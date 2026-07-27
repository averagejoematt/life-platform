"""tests/test_backlog_hygiene_gate.py — the ADR-099 filing-contract linter (#1867, epic #1863).

Replays the PM backlog review's finding 11: exactly one rule validated a filed issue
(`check_story_labels.py`'s `model:*` check), so a filing that skipped the contract was
invisible. #1858 and #1859, filed 2026-07-27 mid-session, carried no milestone, no score
line and no outcome section and nothing noticed.

House style is #1189's "no vacuous scans": every rule below is planted with a fixture
that violates it AND a fixture that satisfies it, so a rule that silently stopped biting
(or bit everything) fails here. The wrap-wiring assertions mirror
tests/test_story_label_gate_1349.py.
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "scripts"))

import backlog_contract as bc  # noqa: E402
import check_backlog_hygiene as hy  # noqa: E402

ROOT = Path(_REPO)
WRAP = ROOT / ".claude" / "commands" / "wrap.md"

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


# ── the gate is wired into the /wrap skill (mirrors test_story_label_gate_1349) ──
def test_wrap_skill_invokes_the_hygiene_linter():
    wrap = WRAP.read_text(encoding="utf-8")
    assert "check_backlog_hygiene.py" in wrap, "#1867: the linter must actually be invoked from wrap.md, not merely described"
    assert "--advisory" in wrap, "#1867: the wrap invocation must be the advisory one until #1872 flips it"


def test_wrap_still_invokes_the_absorbed_label_gate_until_1872():
    """The `model:*` rule is duplicated on purpose: this linter absorbs it, but deleting
    scripts/check_story_labels.py is #1872's proof, gated on the #1868 backfill."""
    wrap = WRAP.read_text(encoding="utf-8")
    assert "check_story_labels.py" in wrap
    assert (ROOT / "scripts" / "check_story_labels.py").exists()


def test_wrap_says_the_linter_is_advisory_and_names_the_flip_issue():
    wrap = WRAP.read_text(encoding="utf-8")
    section = wrap.split("check_backlog_hygiene.py")[1][:1200]
    assert "exits 0" in section
    assert "#1872" in section, "the wrap step must name what flips it blocking, or it reads as a permanent no-op"


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
    """The AC: lands advisory. A day-one blocking gate would red the wrap over #1868's
    outstanding backfill — the ADR-108 promotion pattern."""
    fixture = tmp_path / "issues.json"
    fixture.write_text(json.dumps([_issue(number=1858, labels=("type:story",), milestone=None, body="nothing")]), encoding="utf-8")
    rc = hy.main(["--issues-json", str(fixture), "--now", "2026-07-27T00:00:00Z"])
    out = capsys.readouterr().out
    assert rc == 0, "advisory mode must never exit non-zero"
    assert "#1858" in out and "ADVISORY MODE" in out


def test_cli_blocking_mode_exists_and_exits_one(tmp_path, capsys):
    """#1872 flips the default to this; the flag must already work, or the flip is a rewrite."""
    fixture = tmp_path / "issues.json"
    fixture.write_text(json.dumps([_issue(number=1858, labels=("type:story",), milestone=None, body="nothing")]), encoding="utf-8")
    rc = hy.main(["--issues-json", str(fixture), "--blocking", "--now", "2026-07-27T00:00:00Z"])
    capsys.readouterr()
    assert rc == 1


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


def test_cli_is_fail_open_when_gh_is_unavailable_in_both_modes(monkeypatch, capsys):
    """No network/gh auth in CI's test job — a live-fetch failure must never red the suite
    or block a wrap, in either mode (check_story_labels.py's advisory contract)."""
    monkeypatch.setattr(hy, "_fetch_live_issues", lambda: None)
    assert hy.main([]) == 0
    assert hy.main(["--blocking"]) == 0
    capsys.readouterr()
