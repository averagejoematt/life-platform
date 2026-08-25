"""tests/test_doc_facts_approx_scope_3162.py — approx tolerance is per-MATCH, not per-line (#3162).

Tonight's #2986 acceptance audit found docs/content/ESSAY_ORG_CHART_OF_ONE.md and
docs/content/CAREER_ARTIFACT_SUBMISSION_KIT.md still quoting "9 CDK stacks" months after
the platform grew to 10 (#3042/DIL-027, #3143) — the #2838 class (a public-claims surface
stale while its gate reported green) recurring, on a surface no RULES entry named.

Both files WERE already inside check_doc_facts.py's scan surface (`_scan_files()` walks
`docs/**/*.md` with no `docs/content/` exemption) and the `cdk_stacks` FACT_SPEC IS exact
(tol=0.0). The gate should have caught this. It didn't, because `main()` used to compute
`approx = any(a in line for a in APPROX)` ONCE PER LINE and apply that single flag to
EVERY FACT_SPECS match on the line. The essay's sentence puts an approximate figure
("~76 MCP tools") on the SAME line as an exact one ("9 CDK stacks" — the FACT_SPEC's own
tol is 0.0), so the `~`'s 15% tolerance leaked onto the unrelated exact claim and hid a
genuine 1-off drift (9 vs. truth 10) behind a passing gate.

`_match_is_approx(line, mo)` replaces the per-line flag with a per-match one: an APPROX
prefix marker (`~`, `≈`, "about ", "around ", "roughly ") must directly abut the matched
digits, and the postfix marker (`+`) must directly follow them. A marker anywhere else on
the line no longer counts.
"""

import importlib.util
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load():
    spec = importlib.util.spec_from_file_location("_cdf", ROOT / "scripts" / "check_doc_facts.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture(scope="module")
def facts():
    return _load()


# The measured live line (pre-fix) — an approx marker on an unrelated figure hid a real
# 1-off drift in an exact one, on this exact sentence shape.
LIVE_LINE = "99 Lambda functions, 9 CDK stacks, ~76 MCP tools, a public website, a hard $85-a-month"


def _cdk_match(line):
    return next(re.finditer(r"(?<![A-Za-z0-9.])(\d+)\s+CDK stacks?\b", line))


def _tools_match(line):
    return next(re.finditer(r"(?<![A-Za-z0-9.])(\d+)\s+MCP tools?\b", line))


def test_exact_fact_next_to_an_approx_one_is_not_treated_as_approx(facts):
    """The planted regression: "9 CDK stacks" sits on a line with "~76 MCP tools". The
    exact fact's own match must NOT inherit the approx figure's tolerance."""
    assert facts._match_is_approx(LIVE_LINE, _cdk_match(LIVE_LINE)) is False


def test_the_approx_marked_fact_on_the_same_line_is_still_approx(facts):
    """Precision half: the fix must not also blind the real approx marker it sits beside."""
    assert facts._match_is_approx(LIVE_LINE, _tools_match(LIVE_LINE)) is True


def test_full_pipeline_flags_the_stale_exact_claim_once_the_line_wide_leak_is_closed(facts):
    """End-to-end: replicate main()'s per-match loop (not just the helper in isolation)
    and confirm the stale cdk_stacks=9 claim reds even with an approx figure beside it."""
    truth = {"cdk_stacks": 10}
    hits = []
    for key, patterns, tol in facts.FACT_SPECS:
        if key != "cdk_stacks":
            continue
        for pat in patterns:
            for mo in re.finditer(pat, LIVE_LINE):
                claim = facts._to_int(mo.group(1))
                if facts._off(claim, truth[key], tol, facts._match_is_approx(LIVE_LINE, mo)):
                    hits.append(claim)
    assert hits == [9], f"the stale cdk_stacks claim must flag despite the approx figure beside it, got {hits}"


@pytest.mark.parametrize(
    "line,digit_pattern,expected_approx",
    [
        ("~76 MCP tools", r"(\d+)\s+MCP tools?\b", True),  # prefix marker directly abuts the digit
        ("76 MCP tools, 9 CDK stacks", r"(\d+)\s+CDK stacks?\b", False),  # no marker near THIS number
        ("115+ tools shipped", r"(\d+)\+", True),  # postfix "+" directly follows the digit
        ("about 76 MCP tools", r"(\d+)\s+MCP tools?\b", True),  # multi-char prefix marker
        ("9 CDK stacks and roughly 76 MCP tools", r"(\d+)\s+CDK stacks?\b", False),  # marker is on a LATER number
    ],
)
def test_marker_directionality_and_locality(facts, line, digit_pattern, expected_approx):
    mo = next(re.finditer(digit_pattern, line))
    assert facts._match_is_approx(line, mo) is expected_approx, line


def test_live_repo_no_longer_states_a_stale_cdk_stacks_count(facts):
    """Integration half: the real corpus, under the real gate, is clean today. Mutation
    proof for the lambda_count half (which this FACT_SPECS scan deliberately does not
    police) lives in tests/test_platform_claims_literal_mutation_3162.py."""
    truth = facts._ground_truth()
    hits = []
    for doc in facts._scan_files():
        for lineno, line in enumerate(doc.read_text(encoding="utf-8").splitlines(), 1):
            if facts.HISTORICAL.search(line):
                continue
            for key, patterns, tol in facts.FACT_SPECS:
                for pat in patterns:
                    for mo in re.finditer(pat, line):
                        claim = facts._to_int(mo.group(1))
                        if claim is None:
                            continue
                        if facts._off(claim, truth[key], tol, facts._match_is_approx(line, mo)):
                            hits.append(f"{doc.relative_to(ROOT)}:{lineno}: {key} claims {claim}, truth {truth[key]}")
    assert hits == [], hits
