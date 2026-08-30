"""tests/test_closure_contract_3318.py — the closure contract's five primitives, proven (#3318).

WHAT IS UNDER TEST
  scripts/closure_contract.py      the registry (requirements, grammar, grace, dated ledger, posture)
  scripts/closure_sweep.py         detector A — comments after `closedAt`, unhomed residuals,
                                   silent closes, epics closed over open children
  scripts/check_pr_closing_set.py  detector B — the PR's closing set vs the declared target
  deploy/wait_pr_green.sh          the merge-time seam that runs detector B
  scripts/assert_pr_green.py       the other pre-merge assertion the hook layer accepts
  scripts/wrap_gates.py + wrap.md  the session-scoped sweep and its asserted marker line
  docs/CONVENTIONS.md §4a2         the rendered block — byte-equal to the registry's render

THE FIXTURE IS THE WIRE (§9a). tests/fixtures/closure_contract/*.json are GraphQL Issue nodes
and `gh pr view --json` payloads captured from the live repo on 2026-08-30 — the Session K
audit corpus (#2848, #2670, #3208, #2938, #2921, #3222), PR #3226 (the #3222 stray-Fixes)
and PR #3253 (the #2848 partial-acceptance close) — plus two NEGATIVE CONTROLS (#3289, PR
#3313: clean closes under the contract). Where a fixture reconstructs a state the wire no
longer shows (#2848 is OPEN again; #3226's body was repaired), the fixture says so in a
`_reconstructed` field and the test cites the same evidence.

MUTATION PROOFS. Each detector is shown to go red on its incident shape and green on the
control; the dated ledger is shown to reject an undated entry; the doc block is shown to
red when hand-edited; the derivations (not-work grammar, wrap marker, watcher seam) are
asserted against the real files, not against copies.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
FIX = ROOT / "tests" / "fixtures" / "closure_contract"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = mod  # py3.14: a frozen dataclass under `from __future__ import annotations` resolves its module via sys.modules
    spec.loader.exec_module(mod)
    return mod


cc = _load("closure_contract_3318", SCRIPTS / "closure_contract.py")
sweep = _load("closure_sweep_3318", SCRIPTS / "closure_sweep.py")
cset = _load("check_pr_closing_set_3318", SCRIPTS / "check_pr_closing_set.py")
rq = _load("check_residual_queue_1340", SCRIPTS / "check_residual_queue.py")


def _fixture(name: str) -> dict:
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def _issues(name: str) -> dict:
    raw = _fixture(name)
    return {int(n["number"]): sweep.parse_issue(n) for n in raw["issues"]}


def _codes(findings) -> set:
    return {f.code for f in findings}


# ═══════════════════════════════════════════════════════════════════════════════
# 1. REGISTRY — one vocabulary, derived by every consumer
# ═══════════════════════════════════════════════════════════════════════════════


def test_registry_ids_and_finding_codes_are_unique_and_owned():
    ids = [r.id for r in cc.CLOSURE_CONTRACT]
    assert len(ids) == len(set(ids)) >= 6, ids
    codes = [c for r in cc.CLOSURE_CONTRACT for c in r.finding_codes]
    assert len(codes) == len(set(codes)), "a finding code owned by two requirements is a vocabulary fork"
    for r in cc.CLOSURE_CONTRACT:
        assert (ROOT / r.detector).is_file(), f"{r.id}: detector {r.detector} does not exist"
        assert len(r.rule) > 60, f"{r.id}: a rule this short is a label, not a rule"


def test_every_finding_code_a_detector_can_emit_is_registered():
    """Guard the SET: the codes the detectors' source strings emit ⊆ the registry's codes."""
    import re

    emitted = set()
    for script in (SCRIPTS / "closure_sweep.py", SCRIPTS / "check_pr_closing_set.py"):
        emitted |= set(re.findall(r"Finding\(\s*\"([a-z][a-z-]+)\"", script.read_text(encoding="utf-8")))
    assert emitted, "extractor found nothing — the Finding(...) idiom moved; fix the extractor, not the assertion"
    assert emitted <= cc.ALL_FINDING_CODES, f"unregistered finding code(s): {sorted(emitted - cc.ALL_FINDING_CODES)}"
    assert cc.ALL_FINDING_CODES <= emitted, f"registered but never emitted: {sorted(cc.ALL_FINDING_CODES - emitted)}"


def test_not_work_grammar_is_imported_from_the_residual_queue_gate_not_copied():
    """The handover rule (#1340) and the closure rule are ONE rule on two surfaces."""
    assert cc.NOT_WORK_TAG.pattern == rq.NOT_WORK_TAG.pattern
    assert cc.ISSUE_REF.pattern == rq.ISSUE_REF.pattern
    src = (SCRIPTS / "closure_contract.py").read_text(encoding="utf-8")
    assert (
        "check_residual_queue.py" in src and 're.compile(r"not-work' not in src
    ), "closure_contract must import the tag grammar, never re-type it"


def test_posture_defaults_to_warn_and_the_env_override_only_accepts_known_modes(monkeypatch):
    assert cc.DEFAULT_MODE == "warn", "the flip to block is a dated, measured decision — see the registry docstring"
    monkeypatch.delenv(cc.MODE_ENV, raising=False)
    assert cc.mode() == "warn"
    monkeypatch.setenv(cc.MODE_ENV, "block")
    assert cc.mode() == "block"
    monkeypatch.setenv(cc.MODE_ENV, "sideways")
    assert cc.mode() == cc.DEFAULT_MODE, "an unknown mode must not silently arm or disarm"


def test_flip_bar_is_numeric_and_documented():
    assert cc.FLIP_BAR["consecutive_clean_wraps"] >= 10 and cc.FLIP_BAR["real_merges_observed"] >= 25
    assert "FLIP_BAR" in (cc.__doc__ or "") and "re-measured" in (cc.__doc__ or "")


# ═══════════════════════════════════════════════════════════════════════════════
# 2. RATCHET — the dated ledger of dispositioned escapes
# ═══════════════════════════════════════════════════════════════════════════════


def _ledger_ok(ledger: dict) -> list:
    bad = []
    for num, d in ledger.items():
        try:
            datetime.strptime(d.date, "%Y-%m-%d")
        except (TypeError, ValueError):
            bad.append(f"#{num}: undated ({d.date!r})")
        if len(d.reason or "") < 40:
            bad.append(f"#{num}: reason too short to prove someone looked ({len(d.reason or '')} chars)")
        if not isinstance(num, int):
            bad.append(f"{num!r}: key must be the issue number")
    return bad


def test_every_dispositioned_escape_is_dated_with_a_real_reason():
    assert not _ledger_ok(cc.DISPOSITIONED_ESCAPES)
    assert {2848, 2670, 3208, 2938, 2921} <= set(cc.DISPOSITIONED_ESCAPES), "the Session K audit's five escapes are the seed ledger"


def test_MUTATION_an_undated_or_terse_entry_fails_the_ledger_rule():
    assert _ledger_ok({9999: cc.Disposition("soon", "x" * 50)})
    assert _ledger_ok({9999: cc.Disposition("2026-08-30", "handled")})
    assert not _ledger_ok({9999: cc.Disposition("2026-08-30", "reopened after the audit found the close was made by a stray Fixes line")})


# ═══════════════════════════════════════════════════════════════════════════════
# 3. DETECTOR A — the close, audited (fixtures are captured wire nodes)
# ═══════════════════════════════════════════════════════════════════════════════


def test_wire_parser_reads_the_real_graphql_node_shape():
    issues = _issues("session_k_escapes.json")
    i = issues[2670]
    assert i.closed_at == datetime(2026, 8, 20, 15, 36, 3, tzinfo=timezone.utc)
    assert i.state_reason == "COMPLETED" and "type:bug" in i.labels
    assert len(i.comments) >= 5 and all(t is not None for t, _, _ in i.comments)
    assert [t for t, _, _ in i.comments] == sorted(t for t, _, _ in i.comments), "comments must be time-ordered for the post-close scan"


def test_2848_the_stray_fixes_false_close_is_caught_STRUCTURALLY_by_timestamp():
    """#2848: PR #3253 merged 21:57:55Z; the author wrote 'stays OPEN' at 22:12:54Z (+14m59s)
    and a third comment ~3h later. The structural leg names both without reading words."""
    fx = _fixture("session_k_escapes.json")
    node = next(n for n in fx["issues"] if n["number"] == 2848)
    assert node.get("_reconstructed"), "the fixture must say it restored the 2026-08-27 closed state"
    findings = sweep.evaluate_issue(sweep.parse_issue(node))
    structural = [f for f in findings if f.code == "post-close-comment"]
    assert len(structural) >= 2, findings
    assert any("+14m" in f.detail for f in structural), structural
    assert "post-close-assertion" in _codes(findings), "the lexical leg also fires on 'stays OPEN'"


def test_2670_post_closure_scope_assertion_is_a_hit_and_the_2min_correction_is_inside_grace():
    findings = sweep.evaluate_issue(_issues("session_k_escapes.json")[2670])
    structural = [f for f in findings if f.code == "post-close-comment"]
    delays = sorted(int(f.detail.split("m")[0].lstrip("+")) for f in structural)
    assert delays and delays[0] >= cc.POST_CLOSE_GRACE_MINUTES, "the +2m correction must NOT be a hit"
    assert any(d >= 150 for d in delays), f"the +2.5h post-closure assertion must be a hit: {delays}"


def test_2938_residual_named_with_no_carrier_is_an_unhomed_residual():
    """#2938: 'partial — the post-fix RED has not been observed end-to-end' with no carrier."""
    findings = sweep.evaluate_issue(_issues("session_k_escapes.json")[2938])
    assert "unhomed-residual" in _codes(findings), findings


def test_3208_evaded_the_verdict_shape_and_that_is_its_detectable_failure():
    """#3208's closing comment is `## Verdict — closing as shipped … **Outcome (operator).**` — not
    the ADR-099 two-line shape — and names its residual as 'any remaining member of the family
    … is a latent pipeline red', a phrasing OUTSIDE the residual-cue grammar. Stated blind spot:
    the residual leg is lexical at the naming step; the structural rule that catches #3208 is
    the verdict shape, which is why `no-outcome-verdict` is asserted here and not inferred."""
    findings = sweep.evaluate_issue(_issues("session_k_escapes.json")[3208])
    assert _codes(findings) == {"no-outcome-verdict"}, findings


def test_2921_closed_by_a_negated_keyword_shows_as_reopen_assertions_after_close():
    findings = sweep.evaluate_issue(_issues("session_k_escapes.json")[2921])
    assert "post-close-assertion" in _codes(findings) or "post-close-comment" in _codes(findings), findings


def test_NEGATIVE_CONTROL_a_clean_close_produces_no_findings():
    """#3289: closed by PR #3312's merge, (e8) verdict 61 minutes later, nothing else. The
    verdict is sanctioned by SHAPE (`**Outcome:**`), never by timing."""
    (issue,) = _issues("clean_close_3289.json").values()
    delay = max(t for t, _, _ in issue.comments) - issue.closed_at
    assert delay > timedelta(minutes=cc.POST_CLOSE_GRACE_MINUTES), "the control's verdict is outside the grace on purpose"
    assert sweep.evaluate_issue(issue) == []


def test_MUTATION_the_control_goes_red_when_its_verdict_marker_is_removed():
    (issue,) = _issues("clean_close_3289.json").values()
    t, login, body = issue.comments[-1]
    issue.comments[-1] = (t, login, body.replace("**Outcome:**", "Outcome:"))
    codes = _codes(sweep.evaluate_issue(issue))
    assert {"no-outcome-verdict", "post-close-comment"} <= codes, codes


def test_MUTATION_the_control_goes_red_when_a_partial_verdict_names_no_home():
    (issue,) = _issues("clean_close_3289.json").values()
    t, login, body = issue.comments[-1]
    body = body.split("**Outcome:**")[0] + "**Outcome:** partial — the wire half is not yet observed"
    issue.comments[-1] = (t, login, body)
    assert "unhomed-residual" in _codes(sweep.evaluate_issue(issue))
    issue.comments[-1] = (t, login, body + " — carrier #9999")
    assert "unhomed-residual" not in _codes(sweep.evaluate_issue(issue)), "a carrier anywhere in the verdict comment homes it"
    issue.comments[-1] = (t, login, body + " (not-work — the owner's Monday check)")
    assert "unhomed-residual" not in _codes(sweep.evaluate_issue(issue))


def test_a_pr_cite_is_not_a_home():
    assert cc.homes_in("**Outcome:** partial — shipped in PR #2940, the red not yet seen") == []
    assert cc.homes_in("residual filed as #3315") == ["#3315"]


def test_negated_residual_cues_do_not_name_a_residual():
    assert not cc.names_residual("### The three secondary mechanisms — all fixed, none deferred")
    assert not cc.names_residual("no follow-up needed; nothing left open")
    assert cc.names_residual("Residual by design: the warmer deletion left as an allowlist decision")


def test_bot_comments_and_pre_close_comments_never_count():
    (issue,) = _issues("clean_close_3289.json").values()
    late = issue.closed_at + timedelta(hours=5)
    issue.comments.append((late, "github-actions[bot]", "automated note"))
    issue.comments.append((issue.closed_at - timedelta(hours=1), "averagejoematt", "progress before the close, reopen later maybe"))
    assert sweep.evaluate_issue(issue) == []


def test_epic_closed_over_an_open_child_is_a_hit_and_the_child_index_reads_the_epic_line():
    fx = _fixture("epic_open_children_synthetic.json")
    idx = sweep.open_children_index(fx["open_issues"])
    assert idx == {9001: (9002,), 42: (9003,)}
    issues = [sweep.parse_issue(n) for n in fx["issues"]]
    result = sweep.sweep(issues, fx["open_issues"])
    assert _codes(result["findings"]) == {"epic-children-open"}
    assert sweep.sweep(issues, [])["findings"] == [], "no open child → no finding"


def test_dispositioned_escapes_are_reported_separately_and_a_MUTATION_of_the_ledger_surfaces_them(monkeypatch):
    issues = list(_issues("session_k_escapes.json").values())
    result = sweep.sweep(issues, [])
    assert result["findings"] == [] and len(result["dispositioned"]) == 6
    monkeypatch.setattr(sweep.cc, "DISPOSITIONED_ESCAPES", {})  # the sweep's own registry binding
    result = sweep.sweep(issues, [])
    assert len({f.issue for f in result["findings"]}) == 6, "with the ledger emptied every escape is a live hit"


def test_render_exit_code_follows_the_posture():
    issues = list(_issues("session_k_escapes.json").values())
    hits = sweep.sweep(issues, [])
    code, lines = sweep.render(hits, "fixture", "warn")
    assert code == 0 and lines[-1].startswith("CLOSURE-SWEEP scanned=6") and "dispositioned=6" in lines[-1]
    fx = _fixture("epic_open_children_synthetic.json")
    live = sweep.sweep([sweep.parse_issue(n) for n in fx["issues"]], fx["open_issues"])
    assert sweep.render(live, "fixture", "warn")[0] == 0, "advisory: a hit never exits non-zero"
    assert sweep.render(live, "fixture", "block")[0] == 1, "block: a hit exits 1"


def test_cli_fixture_mode_runs_offline_and_prints_the_contract_line():
    p = subprocess.run(
        [sys.executable, str(SCRIPTS / "closure_sweep.py"), "--fixture", str(FIX / "clean_close_3289.json")],
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, cc.MODE_ENV: "warn"},
    )
    assert p.returncode == 0, p.stdout + p.stderr
    assert p.stdout.strip().splitlines()[-1].startswith("CLOSURE-SWEEP scanned=1"), p.stdout


# ═══════════════════════════════════════════════════════════════════════════════
# 4. DETECTOR B — the closing set (fixtures are `gh pr view --json` payloads)
# ═══════════════════════════════════════════════════════════════════════════════


def test_closing_keyword_grammar_matches_github_and_ignores_non_adjacent_refs():
    refs = cc.closing_refs("Fixes #12, closes: #13 and Resolved owner/repo#14.\nSee #99. fixes the bug in #15")
    assert [n for n, _ in refs] == [12, 13, 14], refs
    assert cc.closing_refs("Fixes https://github.com/averagejoematt/life-platform/issues/7", "averagejoematt/life-platform") == [
        (7, "fixes")
    ]
    assert cc.closing_refs("Fixes other/repo#7", "averagejoematt/life-platform") == [("other/repo#7", "fixes")]


def test_declared_target_comes_from_the_lane_branch_name():
    assert cc.declared_target("issue-3318-closure-contract") == 3318
    assert cc.declared_target("issue-42") == 42
    assert cc.declared_target("feature/issue-42-x") is None and cc.declared_target(None) is None


def test_pr3226_the_3222_stray_fixes_is_NONGREEN_on_declared_target_and_body_vs_commits():
    fx = _fixture("pr_3226_stray_fixes.json")
    assert fx.get("_reconstructed"), "the fixture must say the repaired body had its stray line restored"
    rep = cset.report_from_pr_json(fx, cset.REPO)
    assert rep.declared == 3217 and rep.body == {3217, 3222} and rep.commits == {3217} and rep.github == {3217, 3222}
    assert {"declared-target-mismatch", "body-commits-disagree"} <= {f.code for f in rep.findings}
    assert "epic-in-closing-set" not in {f.code for f in rep.findings}


def test_pr3253_the_2848_close_is_NONGREEN_on_partial_acceptance():
    """The body carried `Fixes #2848` two paragraphs under '- [ ] Verified by test … not satisfied.'"""
    rep = cset.report_from_pr_json(_fixture("pr_3253_partial_acceptance.json"), cset.REPO)
    assert rep.declared == 2848 and rep.parsed == {2848} and rep.github == {2848}
    assert {f.code for f in rep.findings} == {"partial-acceptance-close"}, rep.findings


def test_NEGATIVE_CONTROL_pr3313_is_OK():
    rep = cset.report_from_pr_json(_fixture("pr_3313_clean.json"), cset.REPO)
    assert rep.ok and rep.declared == 3293 and rep.parsed == {3293} == rep.github


def test_MUTATION_each_closing_set_rule_reds_the_clean_control_on_its_own():
    fx = _fixture("pr_3313_clean.json")
    base = dict(fx)

    def codes(**over):
        d = dict(base)
        d.update(over)
        return {f.code for f in cset.report_from_pr_json(d, cset.REPO).findings}

    assert codes() == set()
    assert "declared-target-mismatch" in codes(headRefName="issue-9999-other-lane")
    assert "body-commits-disagree" in codes(commits=[{"messageHeadline": "fix: x", "messageBody": "Fixes #3293\nCloses #3294"}])
    assert "github-parse-disagree" in codes(closingIssuesReferences=[{"number": 3293}, {"number": 4000}])
    assert "epic-in-closing-set" in codes(issue_labels={"3293": ["type:epic"]})
    assert "partial-acceptance-close" in codes(body=base["body"] + "\n\n- [ ] one box still open\n")
    assert "negated-closing-keyword" in codes(body=base["body"] + "\n\nThis does NOT close #77.\n")


def test_a_pr_that_closes_nothing_is_not_a_finding_but_is_named():
    rep = cset.evaluate("docs only, nothing to close", [], "issue-5-docs", {}, [])
    assert rep.ok and rep.parsed == set()
    code, lines = cset.render(rep, "warn")
    assert code == 0 and any("closes nothing" in ln for ln in lines)


def test_render_is_machine_readable_and_the_exit_code_follows_the_posture():
    rep = cset.report_from_pr_json(_fixture("pr_3226_stray_fixes.json"), cset.REPO)
    code, lines = cset.render(rep, "warn")
    assert code == 0 and lines[-1].startswith("CLOSING-SET VERDICT NONGREEN mode=warn")
    assert cset.render(rep, "block")[0] == 1
    ok = cset.report_from_pr_json(_fixture("pr_3313_clean.json"), cset.REPO)
    assert cset.render(ok, "block")[1][-1].startswith("CLOSING-SET VERDICT OK mode=block")


def test_cli_fixture_mode_accepts_the_watcher_calling_convention():
    """deploy/wait_pr_green.sh appends the PR number LAST; `--pr` absorbs it in fixture mode."""
    p = subprocess.run(
        [sys.executable, str(SCRIPTS / "check_pr_closing_set.py"), "--fixture", str(FIX / "pr_3226_stray_fixes.json"), "--pr", "3226"],
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, cc.MODE_ENV: "block"},
    )
    assert p.returncode == 1, p.stdout + p.stderr
    assert "CLOSING-SET VERDICT NONGREEN mode=block" in p.stdout


# ═══════════════════════════════════════════════════════════════════════════════
# 5. THE SEAMS — watcher, assertion script, wrap battery, doc block
# ═══════════════════════════════════════════════════════════════════════════════

WAIT = ROOT / "deploy" / "wait_pr_green.sh"


def test_the_watcher_runs_detector_b_on_both_merge_eligible_verdicts_and_never_silently():
    src = WAIT.read_text(encoding="utf-8")
    assert "check_pr_closing_set.py" in src
    assert src.count('_closing_set_check "${pr}" || return 1') == 2, "exit 0 AND exit 4 are merge-eligible; both must assert the set"
    assert "CLOSING-SET VERDICT UNAVAILABLE" in src, "absence must be louder than failure — an unrunnable check prints UNAVAILABLE"


def _watcher_seam(cmd: str) -> subprocess.CompletedProcess:
    script = f"""
set -uo pipefail
export WAIT_PR_GREEN_CLOSING_SET_CMD='{cmd}'
source '{WAIT}' --source-only
_closing_set_check 3226
echo "RC=$?"
"""
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=60)


def test_watcher_seam_forwards_the_detector_output_and_honours_its_exit_code():
    fixture = FIX / "pr_3226_stray_fixes.json"
    warn = _watcher_seam(f"env {cc.MODE_ENV}=warn {sys.executable} {SCRIPTS / 'check_pr_closing_set.py'} --fixture {fixture} --pr")
    assert "CLOSING-SET VERDICT NONGREEN mode=warn" in warn.stdout and "RC=0" in warn.stdout, warn.stdout + warn.stderr
    block = _watcher_seam(f"env {cc.MODE_ENV}=block {sys.executable} {SCRIPTS / 'check_pr_closing_set.py'} --fixture {fixture} --pr")
    assert "CLOSING-SET VERDICT NONGREEN mode=block" in block.stdout and "RC=1" in block.stdout, block.stdout + block.stderr


def test_watcher_seam_prints_UNAVAILABLE_when_the_detector_cannot_run():
    p = _watcher_seam("/nonexistent/closing_set_check")
    assert "CLOSING-SET VERDICT UNAVAILABLE" in p.stdout and "RC=1" in p.stdout, p.stdout + p.stderr


def test_assert_pr_green_carries_the_same_check_so_the_hook_layer_has_no_bypass():
    apg = (SCRIPTS / "assert_pr_green.py").read_text(encoding="utf-8")
    assert "check_pr_closing_set.py" in apg and "--no-closing-set" in apg
    hook = (SCRIPTS / "hooks" / "guard_bash.py").read_text(encoding="utf-8")
    assert "assert_pr_green" in hook and "wait_pr_green" in hook, "both names the hook accepts before a merge carry detector B"


def test_wrap_battery_runs_the_session_sweep_and_rides_the_asserted_closures_line():
    wg = _load("wrap_gates_3318", SCRIPTS / "wrap_gates.py")
    chl = _load("check_handover_lines_3318", SCRIPTS / "check_handover_lines.py")
    (gate,) = [g for g in wg.GATHER if "closure_sweep.py" in " ".join(g.cmd)]
    assert "--session" in gate.cmd and gate.marker == "Closures" and gate.step == "e8"
    markers = chl.derive_markers(chl.DEFAULT_WRAP.read_text(encoding="utf-8"))
    assert markers.get("Closures") == "e8", "the sweep rides the (e8) line check_handover_lines already asserts"
    assert "Closure DoD" not in markers, "no thirteenth marker: the current handover must keep passing check_handover_lines"
    closures = next(ln for ln in wg.draft_lines([]) if ln.startswith("**Closures:**"))
    assert "DoD:" in closures


def test_wrap_draft_line_reads_the_sweep_contract_line_not_its_prose():
    wg = _load("wrap_gates_3318b", SCRIPTS / "wrap_gates.py")
    (gate,) = [g for g in wg.GATHER if "closure_sweep.py" in " ".join(g.cmd)]
    out = (
        "HIT #1\n   - post-close-comment: x\nCLOSURE-SWEEP scanned=3 window=closed>=2026-08-30 hits=1 findings=1 dispositioned=0 mode=warn"
    )
    line = next(ln for ln in wg.draft_lines([(gate, True, 0, out)]) if ln.startswith("**Closures:**"))
    assert "scanned=3" in line and "hits=1" in line
    unv_out = "CLOSURE-SWEEP UNVERIFIED — could not read GitHub"
    unv = next(ln for ln in wg.draft_lines([(gate, True, 0, unv_out)]) if ln.startswith("**Closures:**"))
    assert "unverified" in unv


def test_conventions_block_is_byte_equal_to_the_registry_render_and_a_MUTATION_reds():
    doc = (ROOT / "docs" / "CONVENTIONS.md").read_text(encoding="utf-8")
    i, j = doc.index(cc.RENDER_BEGIN), doc.index(cc.RENDER_END) + len(cc.RENDER_END)
    assert (
        doc[i:j] == cc.render_conventions_block()
    ), "docs/CONVENTIONS.md §4a2 drifted — re-run `python3 scripts/closure_contract.py --render` and splice"
    assert doc.count(cc.RENDER_BEGIN) == 1, "one rendered copy, never two"
    mutated = doc[:i] + doc[i:j].replace("EXACTLY one home", "a home somewhere") + doc[j:]
    assert mutated[i : mutated.index(cc.RENDER_END) + len(cc.RENDER_END)] != cc.render_conventions_block()


def test_the_rule_is_not_restated_as_a_second_copy_elsewhere():
    """One rule, one page: the other homes point at the registry, they do not re-list the rules."""
    for rel in ("docs/OPERATING_DISCIPLINE.md", ".claude/skills/land/SKILL.md", ".claude/skills/wrap/SKILL.md"):
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert "scripts/closure_contract.py" in text, f"{rel} must point at the registry"
        assert "`outcome-verdict`" not in text, f"{rel} re-lists the registry's requirement ids — that is a second copy"
