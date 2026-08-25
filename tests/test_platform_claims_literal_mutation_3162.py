"""tests/test_platform_claims_literal_mutation_3162.py — mutation proof for #3162.

docs/content/ESSAY_ORG_CHART_OF_ONE.md and docs/content/CAREER_ARTIFACT_SUBMISSION_KIT.md
are public-claims essays (#740/#741) that quoted the platform's Lambda/CDK-stack/MCP-tool
counts in free prose. check_doc_facts.py's FACT_SPECS deliberately does NOT police
lambda_count in prose (too many legitimate subset counts elsewhere in docs/ to regex
safely — see that file's own comment), so a stale "99 Lambda functions" in these two
specific essays was invisible to every existing gate. #2838 closed on the promise that a
public-claims cost/count surface would be corrected; these two files regressed the exact
same class before that promise was even six weeks old (folded into epic #2986).

The structural fix: three file-scoped RULES entries in deploy/sync_doc_metadata.py, whose
fixed phrasing carries none of the free-prose ambiguity a generic regex would. This test
plants the exact historical defect (99 Lambdas / 9 CDK stacks, current truth 104/10) into
synthetic copies of the two essays' real sentences and proves the REAL, currently-shipped
RULES entries (not a reconstruction) flag it under --check and correct it under --apply —
the same mechanism test_sync_doc_metadata_check.py uses for the widget-count fixture.
"""

import os
import sys

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "deploy"))

import sync_doc_metadata as sync  # noqa: E402

ESSAY_PATH = "docs/content/ESSAY_ORG_CHART_OF_ONE.md"
KIT_PATH = "docs/content/CAREER_ARTIFACT_SUBMISSION_KIT.md"

# The real, currently-shipped rules for these two files — not a reconstruction. If a
# future refactor renames or drops one of these, this list comes back empty and the
# parametrized tests below simply don't run against it, so the emptiness is asserted too.
_ESSAY_RULES = [r for r in sync.RULES if r[0] == ESSAY_PATH]
_KIT_RULES = [r for r in sync.RULES if r[0] == KIT_PATH]


def test_the_three_rules_are_actually_registered():
    """Non-vacuity: the parametrized mutation tests below are worthless if the RULES
    entries they exercise silently disappeared (a rename, a revert of this fix)."""
    assert len(_ESSAY_RULES) == 1, _ESSAY_RULES
    assert len(_KIT_RULES) == 2, _KIT_RULES


def _isolate(monkeypatch, tmp_path, rel_path, doc_text, rule):
    doc = tmp_path / rel_path
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text(doc_text, encoding="utf-8")
    monkeypatch.setattr(sync, "ROOT", tmp_path)
    monkeypatch.setattr(sync, "RULES", [rule])
    monkeypatch.setattr(
        sync,
        "PLATFORM_FACTS",
        {**sync.PLATFORM_FACTS, "lambda_count": 104, "cdk_stacks": 10, "tool_count": 76},
    )
    monkeypatch.setattr(sync, "_apply_auto_discovered", lambda facts: facts)
    monkeypatch.setattr(sync, "_sync_platform_counts", lambda facts, dry_run: [])
    monkeypatch.setattr(sync._alarm_inv, "sync", lambda dry_run, by_stack: [])
    return doc


@pytest.mark.parametrize(
    "rel_path,stale_text,live_rule",
    [
        (
            ESSAY_PATH,
            "a production AWS platform — 99 Lambda functions, 9 CDK stacks, ~76 MCP tools, a public website\n",
            _ESSAY_RULES[0] if _ESSAY_RULES else None,
        ),
        (
            KIT_PATH,
            "> a production AWS platform (99 Lambdas, 9 CDK stacks,\n> a public website) running with AI agents\n",
            _KIT_RULES[0] if _KIT_RULES else None,
        ),
        (
            KIT_PATH,
            "> a live AWS platform (99 Lambdas, 9 CDK stacks, ~76 MCP tools) with one human\n",
            _KIT_RULES[1] if len(_KIT_RULES) > 1 else None,
        ),
    ],
)
def test_planted_stale_count_reds_check_and_apply_heals_it(monkeypatch, tmp_path, rel_path, stale_text, live_rule):
    if live_rule is None:
        pytest.skip("the rule this case exercises is not registered — see test_the_three_rules_are_actually_registered")

    doc = _isolate(monkeypatch, tmp_path, rel_path, stale_text, live_rule)

    # --check must red: the planted "99 Lambdas / 9 CDK stacks" disagrees with truth.
    monkeypatch.setattr(sys, "argv", ["sync_doc_metadata.py", "--check"])
    with pytest.raises(SystemExit) as exc:
        sync.main()
    assert exc.value.code == 1, f"planted stale count did not red --check for {rel_path}"
    assert "99" in doc.read_text(encoding="utf-8"), "--check must never write"

    # --apply must heal it to the live truth. (main() falls through with no sys.exit on
    # a successful --apply — only --check/--check+--apply-conflict call sys.exit; see
    # tests/test_sync_doc_metadata_check.py, which never exercises bare --apply either.)
    monkeypatch.setattr(sys, "argv", ["sync_doc_metadata.py", "--apply"])
    sync.main()
    healed = doc.read_text(encoding="utf-8")
    assert "99 Lambda" not in healed and "99 Lambdas" not in healed, healed
    assert "104 Lambda" in healed or "104 Lambdas" in healed, healed
    assert "9 CDK" not in healed, healed
    assert "10 CDK stacks" in healed, healed
