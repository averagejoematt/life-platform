"""tests/test_live_proof_closure_3595.py — `Refs` not `Fixes` for instruments, and the one
closure-contract code armed BLOCK from day one (#3595).

WHAT IS UNDER TEST
  scripts/closure_contract.py      the `live-proof-before-close` requirement, `BLOCK_CODES`,
                                   `arming_for`, the live-proof grammar, the three
                                   class-derivation legs, the AST instrument-site detector
  scripts/closure_sweep.py         detector A — an instrument closed with no live output named
  scripts/check_pr_closing_set.py  detector B — a closing keyword aimed at an instrument
  the four surfaces that state the rule: the PR template, `issue-filer.md`,
  `worktree-implementer.md`, `/land` §5 and `/wrap` (e8)

THE CLASS (forensic RCA 2026-09-05, class 3 — `docs/reviews/FORENSIC_RCA_2026-09-05.md`)
  `Fixes #N` closes at MERGE, before the deploy, and `closure_contract.DEFAULT_MODE` has been
  `warn` since #3318 with a flip bar never met. Four instruments read CLOSED while
  non-functional: INT-1 #1480 (49 days), G-3 #2254 (28), OBS-1 #1956 (30+), CPO-2 #532 (21
  runs). The fix is not a seventh warn-mode rule: it is one code that blocks.

THE FIXTURE IS THE WIRE (§9a). tests/fixtures/closure_contract/live_proof_3595.json holds the
six Issue nodes as `gh api graphql` returned them on 2026-09-05 — the four dead instruments,
#3502 (which the story named as its positive control) and #3413 (the closest thing the corpus
has to a close made on live evidence). Two facts the fixture states rather than hides, and
these tests assert both rather than working around them:

  * **#3502 has zero comments.** It was closed by `Fixes #3502` in PR #3573 at 06:56:12Z; the
    acceptance's "positive control" does not exist on the wire. The positive control here is
    therefore CONSTRUCTED, in the test body, by adding ONE line to #3413's real verdict — and
    #3413's verdict as it actually stands is asserted to FAIL, because its live evidence
    ("ALARM→OK 12:20:36 PT") is real prose no machine can address.
  * **No issue carries `closure:live-proof`**, because this change mints that label. The
    label leg's tests add it in the test body, where the mutation is visible.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
FIX = ROOT / "tests" / "fixtures" / "closure_contract"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


cc = _load("closure_contract_3595", SCRIPTS / "closure_contract.py")
sweep = _load("closure_sweep_3595", SCRIPTS / "closure_sweep.py")
cset = _load("check_pr_closing_set_3595", SCRIPTS / "check_pr_closing_set.py")

WIRE = json.loads((FIX / "live_proof_3595.json").read_text(encoding="utf-8"))
NODES = {int(n["number"]): n for n in WIRE["issues"]}

# The one line the contract asks for, in the shape the registry recognises.
PROOF_LINE = "**Live proof:** 2026-09-01 12:20:36 PT — CloudWatch `ai-canary-overall` ALARM→OK, the first non-degraded verdict"


def _codes(findings) -> set:
    return {f.code for f in findings}


def _node(number: int, *, labelled: bool = False, closed: str | None = None) -> dict:
    """A deep copy of the captured wire node, with the two mutations named ABOVE the call."""
    node = copy.deepcopy(NODES[number])
    if labelled:
        node["labels"]["nodes"].append({"name": cc.INSTRUMENT_LABEL})
    if closed:
        node["closedAt"] = closed
    return node


# ══════════════════════════════════════════════════════════════════════════════
# 1. REGISTRY — the requirement, and the one code that does not ride the flip bar
# ══════════════════════════════════════════════════════════════════════════════


def test_the_requirement_is_registered_with_both_detectors_and_a_real_rule():
    (req,) = [r for r in cc.CLOSURE_CONTRACT if r.id == "live-proof-before-close"]
    assert req.finding_codes == ("no-live-proof",)
    assert req.detectors == ("scripts/closure_sweep.py", "scripts/check_pr_closing_set.py")
    for d in req.detectors:
        assert (ROOT / d).is_file(), f"detector {d} does not exist"
    assert "Refs" in req.rule and "Fixes" in req.rule
    assert "no-live-proof" in cc.ALL_FINDING_CODES


def test_no_live_proof_is_armed_block_from_day_one_and_the_env_cannot_disarm_it(monkeypatch):
    """The other six ride FLIP_BAR; this one does not. `CLOSURE_CONTRACT_MODE=warn` is the
    exact bypass a 2am lane would reach for, so it must not work here."""
    assert cc.BLOCK_CODES == frozenset({"no-live-proof"})
    assert cc.DEFAULT_MODE == "warn", "the flip of the OTHER six is still a dated, measured decision"
    monkeypatch.setenv(cc.MODE_ENV, "warn")
    assert cc.arming_for("no-live-proof") == "block"
    assert cc.arming_for("no-live-proof", "warn") == "block"
    assert cc.arming_for("unhomed-residual", "warn") == "warn"
    assert cc.arming_for("unhomed-residual") == "warn"
    monkeypatch.setenv(cc.MODE_ENV, "block")
    assert cc.arming_for("unhomed-residual") == "block", "an ambient block still arms the other six"


def test_the_rendered_doc_block_states_the_block_arming_and_the_three_legs():
    block = cc.render_conventions_block()
    assert "`no-live-proof`, armed **block** from day one" in block
    assert cc.INSTRUMENT_LABEL in block and "**Closure class:**" in block
    assert cc.LIVE_PROOF_SINCE in block, "a going-forward-only rule states its start date in the doc"
    doc = (ROOT / "docs" / "CONVENTIONS.md").read_text(encoding="utf-8")
    i = doc.index(cc.RENDER_BEGIN)
    j = doc.index(cc.RENDER_END) + len(cc.RENDER_END)
    assert doc[i:j] == block, "re-run `python3 scripts/closure_contract.py --render` and splice §4a2"


# ══════════════════════════════════════════════════════════════════════════════
# 2. THE GRAMMAR — against the real closing comments of the four dead instruments
# ══════════════════════════════════════════════════════════════════════════════


def test_the_four_instruments_that_read_CLOSED_while_dead_all_fail_the_live_proof_rule():
    """#1480 and #532 closed with ZERO comments; #2254 and #1956 closed with long, careful
    verdicts that describe code and promise a deploy. None names an observed live output."""
    silent = [n for n in (1480, 532) if not NODES[n]["comments"]["nodes"]]
    assert silent == [1480, 532], "the fixture must still show these two closing with no comment at all"
    for number in (2254, 1956):
        bodies = [c["body"] for c in NODES[number]["comments"]["nodes"]]
        assert bodies, f"#{number} lost its closing comment in the capture"
        assert not any(cc.names_live_proof(b) for b in bodies), f"#{number} must fail: no live output is named"
    # #2254's verdict says the quiet part out loud — the shape the rule exists for.
    assert "Deploy: pending" in NODES[2254]["comments"]["nodes"][-1]["body"]


def test_3502_the_stories_named_positive_control_does_not_exist_on_the_wire():
    """Stated, not worked around: #3502 was closed by `Fixes #3502` in PR #3573 with no comment
    at all — so it fails `no-outcome-verdict` too, and cannot be anyone's positive control."""
    assert NODES[3502]["comments"]["totalCount"] == 0
    assert NODES[3502]["stateReason"] == "COMPLETED"


def test_3413_carries_real_live_evidence_and_STILL_fails_because_prose_is_not_addressable():
    """The best close in the corpus: a shipped-zip verification, a 33.9s→12.8s probe and an
    ALARM→OK transition. All true, all unreadable by a detector — which is the whole reason
    the rule is a MARKER and not a phrase list."""
    verdict = [c["body"] for c in NODES[3413]["comments"]["nodes"] if cc.has_verdict(c["body"])][-1]
    assert "ALARM→OK" in verdict and "12.8s" in verdict
    assert not cc.names_live_proof(verdict)
    assert cc.names_live_proof(verdict + "\n\n" + PROOF_LINE), "one added line is the whole ask"


def test_MUTATION_each_part_of_the_live_proof_line_is_load_bearing():
    assert cc.names_live_proof(PROOF_LINE)
    assert not cc.names_live_proof(PROOF_LINE.replace("**Live proof:**", "Live proof:")), "the marker is structural"
    assert not cc.names_live_proof("**Live proof:** the canary cleared this morning"), "no instant = a promise"
    assert not cc.names_live_proof("**Live proof:** 2026-09-01 12:20:36 PT"), "an instant with no where names no output"
    assert cc.names_live_proof("**First live output:** 2026-09-06T18:31Z — qa-smoke logged a grounded-ALARM rate"), "both markers"


# ══════════════════════════════════════════════════════════════════════════════
# 3. DETECTOR A — the close, audited
# ══════════════════════════════════════════════════════════════════════════════

_AFTER = f"{cc.LIVE_PROOF_SINCE}T18:00:00Z"


def test_an_instrument_closed_with_no_live_output_is_a_no_live_proof_hit():
    issue = sweep.parse_issue(_node(2254, labelled=True, closed=_AFTER))
    findings = sweep.evaluate_issue(issue)
    assert "no-live-proof" in _codes(findings), findings
    (hit,) = [f for f in findings if f.code == "no-live-proof"]
    assert hit.issue == 2254 and cc.INSTRUMENT_LABEL in hit.detail


def test_NEGATIVE_CONTROL_the_same_close_with_the_proof_line_is_clean_on_this_code():
    node = _node(2254, labelled=True, closed=_AFTER)
    node["comments"]["nodes"][-1]["body"] += "\n\n" + PROOF_LINE
    assert "no-live-proof" not in _codes(sweep.evaluate_issue(sweep.parse_issue(node)))


def test_the_rule_is_going_forward_only_and_says_so_by_date():
    """The ADR-099 CONTRACT_SINCE shape: reconstructing a live proof for an August close would
    be guesswork on record. #2254 closed 2026-08-08 — labelled or not, it is out of scope."""
    before = (datetime.fromisoformat(cc.LIVE_PROOF_SINCE) - timedelta(days=1)).date().isoformat()
    issue = sweep.parse_issue(_node(2254, labelled=True, closed=f"{before}T18:00:00Z"))
    assert "no-live-proof" not in _codes(sweep.evaluate_issue(issue))


def test_STATED_BLIND_SPOT_an_unlabelled_instrument_is_invisible_to_detector_A():
    """A sweep sees labels, never a diff. #1480 was an instrument by any reading and carried no
    label, so detector A cannot reach it — which is why the issue-filer stamps the label at
    FILING and why detector B's AST leg exists on the other surface. Asserted, not assumed."""
    issue = sweep.parse_issue(_node(2254, labelled=False, closed=_AFTER))
    assert "no-live-proof" not in _codes(sweep.evaluate_issue(issue))


def test_a_silent_close_of_an_instrument_reds_on_BOTH_codes():
    """#3502's real shape: closed by `Fixes` with no comment at all."""
    issue = sweep.parse_issue(_node(3502, labelled=True, closed=_AFTER))
    assert {"no-outcome-verdict", "no-live-proof"} <= _codes(sweep.evaluate_issue(issue))


def test_the_sweep_exits_1_on_this_code_even_in_warn_and_names_it_on_the_contract_line():
    issues = [sweep.parse_issue(_node(2254, labelled=True, closed=_AFTER))]
    result = sweep.sweep(issues, [])
    code, lines = sweep.render(result, "fixture", "warn")
    assert code == 1, "\n".join(lines)
    assert lines[-1].endswith("blocking=no-live-proof"), lines[-1]
    clean = sweep.sweep([sweep.parse_issue(_node(2254, labelled=False, closed=_AFTER))], [])
    ok_code, ok_lines = sweep.render(clean, "fixture", "warn")
    assert ok_code == 0 and ok_lines[-1].endswith("blocking=none"), ok_lines[-1]


def test_the_dated_ledger_still_suppresses_a_dispositioned_escape():
    """The ratchet is not bypassed by the new code: a dispositioned issue stays dispositioned."""
    node = _node(3413, labelled=True, closed=_AFTER)
    result = sweep.sweep([sweep.parse_issue(node)], [])
    assert result["findings"] == [] and len(result["dispositioned"]) == 1
    assert 3413 in cc.DISPOSITIONED_ESCAPES


# ══════════════════════════════════════════════════════════════════════════════
# 4. DETECTOR B — a closing keyword aimed at an instrument
# ══════════════════════════════════════════════════════════════════════════════

FAIL_SOFT_SOURCE = (ROOT / "lambdas" / "emails" / "chronicle_email_sender_lambda.py").read_text(encoding="utf-8")
PRODUCT_SOURCE = (ROOT / "lambdas" / "common" / "constants.py").read_text(encoding="utf-8")


def _rep(body, *, labels=None, sources=None, branch="issue-2254-chronicle", commits=None):
    return cset.evaluate(body, commits or [], branch, labels or {}, None, None, cset.REPO, sources)


def test_the_label_leg_BLOCKS_a_fixes_aimed_at_an_instrument():
    rep = _rep("Fixes #2254", labels={2254: [cc.INSTRUMENT_LABEL, "type:bug"]})
    assert "no-live-proof" in _codes(rep.findings)
    code, lines = cset.render(rep, "warn")
    assert code == 1, "\n".join(lines)
    assert "blocking=no-live-proof" in lines[-1]
    assert any("[block]" in ln and "no-live-proof" in ln for ln in lines)


def test_the_declared_leg_BLOCKS_when_the_author_says_instrument_and_still_writes_fixes():
    rep = _rep("**Closure class:** instrument — a nightly sweep\n\nFixes #2254")
    assert "no-live-proof" in _codes(rep.findings)
    assert cset.render(rep, "warn")[0] == 1


def test_a_product_declaration_with_a_reason_overrides_the_label_and_AST_legs():
    body = "**Closure class:** product — a reader-facing 500 on /api/status, proven by curl after deploy\n\nFixes #2254"
    rep = _rep(body, labels={2254: [cc.INSTRUMENT_LABEL]}, sources={"x.py": FAIL_SOFT_SOURCE})
    assert "no-live-proof" not in _codes(rep.findings)
    assert any("overridden by" in n for n in rep.notes)
    thin = _rep("**Closure class:** product — nope\n\nFixes #2254", labels={2254: [cc.INSTRUMENT_LABEL]})
    assert "no-live-proof" in _codes(thin.findings), "a reason under 20 chars is not a decision; it does not override"


def test_the_2254_diff_replayed_through_the_AST_leg_is_an_ADVISORY_hit():
    """The acceptance's own case: the diff has a fail-soft site and the body carries `Fixes`.
    Advisory by design — this leg reads code and is silent about intent, and its answer is one
    declaration line, not a blocked merge. The real chronicle sender source is the fixture."""
    rep = _rep("Fixes #2254", sources={"lambdas/emails/chronicle_email_sender_lambda.py": FAIL_SOFT_SOURCE})
    (hit,) = [f for f in rep.findings if f.code == "no-live-proof"]
    assert hit.arming == "warn" and "fail-soft-write" in hit.detail
    code, lines = cset.render(rep, "warn")
    assert code == 0 and "blocking=none" in lines[-1], "\n".join(lines)
    assert any("[warn]" in ln and "no-live-proof" in ln for ln in lines)
    assert cset.render(rep, "block")[0] == 1, "an ambient block posture still blocks everything"


def test_NEGATIVE_CONTROL_a_docs_only_pr_with_fixes_is_clean():
    rep = _rep("Fixes #2254\n\nOne paragraph in docs/CONVENTIONS.md.", sources={})
    assert rep.ok and rep.findings == [] and rep.notes == []


def test_NEGATIVE_CONTROL_a_product_module_with_no_instrument_site_is_clean():
    rep = _rep("Fixes #2254", sources={"lambdas/common/constants.py": PRODUCT_SOURCE})
    assert "no-live-proof" not in _codes(rep.findings)


def test_a_Refs_only_pr_never_fires_any_leg_which_is_the_prescribed_shape():
    body = "**Closure class:** instrument — the closure sweep\n\nRefs #3595 Refs #3596"
    rep = _rep(body, labels={3595: [cc.INSTRUMENT_LABEL]}, sources={"x.py": FAIL_SOFT_SOURCE})
    assert rep.parsed == set() and rep.ok, rep.findings


def test_an_unreadable_diff_is_a_printed_NOTE_never_a_pass():
    """`changed_sources=None` means the tree could not be read (the watcher runs from main, not
    from the lane's head). Absence is louder than failure — it is on the transcript."""
    rep = _rep("Fixes #2254", sources=None)
    assert "no-live-proof" not in _codes(rep.findings)
    assert any("instrument-AST leg NOT RUN" in n for n in rep.notes)
    assert any("NOT RUN" in ln for ln in cset.render(rep, "warn")[1])


def test_the_diff_leg_refuses_to_read_the_wrong_tree():
    """read_changed_sources returns None unless this checkout is on the PR's head branch: a file
    read from `main` is evidence about a different diff."""
    data = {"files": [{"path": "scripts/closure_contract.py"}], "headRefName": "some-other-lane"}
    assert cset.read_changed_sources(data) is None
    here = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True, cwd=ROOT).stdout.strip()
    data["headRefName"] = here
    got = cset.read_changed_sources(data)
    assert got and "scripts/closure_contract.py" in got


# ══════════════════════════════════════════════════════════════════════════════
# 5. THE AST DETECTOR — five shapes, each on real repo source
# ══════════════════════════════════════════════════════════════════════════════


def test_instrument_sites_finds_the_fail_soft_write_that_hid_G3_for_28_days():
    kinds = {k for k, _ln, _d in cc.instrument_sites(FAIL_SOFT_SOURCE, "chronicle_email_sender_lambda.py")}
    assert "fail-soft-write" in kinds
    sites = [(k, ln, d) for k, ln, d in cc.instrument_sites(FAIL_SOFT_SOURCE) if k == "fail-soft-write"]
    assert sites, "the _record_email_send put_item is the site #3563 measured"
    assert any("put_item" in d and "logs and continues" in d for _k, _ln, d in sites)


def test_instrument_sites_finds_alarms_schedules_emf_and_chronic_results():
    stack = (ROOT / "cdk" / "stacks" / "operational_stack.py").read_text(encoding="utf-8")
    kinds = {k for k, _ln, _d in cc.instrument_sites(stack)}
    assert {"cw-alarm", "scheduled-job"} <= kinds, kinds
    qa = (ROOT / "lambdas" / "operational" / "qa_check_outputs.py").read_text(encoding="utf-8")
    assert "chronic-check" in {k for k, _ln, _d in cc.instrument_sites(qa)}
    emf = "import boto3\ncw = boto3.client('cloudwatch')\ncw.put_metric_data(Namespace='x', MetricData=[])\n"
    assert [k for k, _ln, _d in cc.instrument_sites(emf)] == ["emf-emitter"]


def test_MUTATION_a_write_that_RERAISES_is_not_a_fail_soft_site():
    """The distinguishing property is the swallow, not the try. A handler that re-raises is a
    loud failure and never the 49-day silence this class is about."""
    swallow = "try:\n    t.put_item(Item={})\nexcept Exception as e:\n    log.info('nope %s', e)\n"
    loud = "try:\n    t.put_item(Item={})\nexcept Exception as e:\n    log.info('nope %s', e)\n    raise\n"
    assert [k for k, _ln, _d in cc.instrument_sites(swallow)] == ["fail-soft-write"]
    assert cc.instrument_sites(loud) == []
    assert cc.instrument_sites("t.put_item(Item={})\n") == [], "an unguarded write fails loudly; not this class"
    assert cc.instrument_sites("def f(:\n") == [], "unparseable source yields no evidence, never a crash"


# ══════════════════════════════════════════════════════════════════════════════
# 6. THE FOUR SURFACES — one line each, no second copy of the registry
# ══════════════════════════════════════════════════════════════════════════════

_SURFACES = (
    ".github/PULL_REQUEST_TEMPLATE.md",
    ".claude/agents/issue-filer.md",
    ".claude/agents/worktree-implementer.md",
    ".claude/skills/land/SKILL.md",
    ".claude/skills/wrap/SKILL.md",
)


def test_every_surface_states_the_rule_and_none_re_lists_the_registry():
    for rel in _SURFACES:
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert "Refs" in text and "3595" in text, f"{rel} does not carry the `Refs`-not-`Fixes` rule"
        assert "`outcome-verdict`" not in text, f"{rel} re-lists the registry's requirement ids — a second copy"
    template = (ROOT / _SURFACES[0]).read_text(encoding="utf-8")
    assert "**Closure class:**" in template and "Refs #" in template
    filer = (ROOT / _SURFACES[1]).read_text(encoding="utf-8")
    assert cc.INSTRUMENT_LABEL in filer, "the filer is where the label gets stamped"
    for rel in (".claude/skills/land/SKILL.md", ".claude/skills/wrap/SKILL.md"):
        assert "scripts/closure_contract.py" in (ROOT / rel).read_text(encoding="utf-8")


def test_the_watcher_seam_is_unchanged_and_still_carries_detector_B():
    """This change adds a code, not a seam: `deploy/wait_pr_green.sh` already runs detector B on
    both merge-eligible verdicts, so the block arrives with no workflow edit."""
    src = (ROOT / "deploy" / "wait_pr_green.sh").read_text(encoding="utf-8")
    assert src.count('_closing_set_check "${pr}" || return 1') == 2


def test_cli_fixture_mode_exits_1_on_a_blocking_finding_under_an_explicit_warn_env(tmp_path):
    fixture = tmp_path / "pr_3595_probe.json"
    fixture.write_text(
        json.dumps(
            {
                "number": 9999,
                "body": "**Closure class:** instrument — the nightly sweep\n\nFixes #2254",
                "headRefName": "issue-2254-x",
                "commits": [{"messageHeadline": "fix(x): y", "messageBody": ""}],
                "closingIssuesReferences": [{"number": 2254}],
                "issue_labels": {},
            }
        ),
        encoding="utf-8",
    )
    p = subprocess.run(
        [sys.executable, str(SCRIPTS / "check_pr_closing_set.py"), "--fixture", str(fixture)],
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, cc.MODE_ENV: "warn"},
    )
    assert p.returncode == 1, p.stdout + p.stderr
    assert "blocking=no-live-proof" in p.stdout, p.stdout
