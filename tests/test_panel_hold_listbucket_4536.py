"""#4536 — the coach-panel-podcast role can LIST the holds prefix, so a missing hold answers 404.

The incident: `_read_hold` does a GetObject on `panelcast-holds/wk<N>.json`. The #4449 grant
gave GetObject + DeleteObject on that prefix, but S3 answers a GetObject on a key that does
not exist with 403 AccessDenied (not 404 NoSuchKey) when the caller lacks `s3:ListBucket` on
the bucket. A week with no hold is the common case, so every MON/WED sweep logged
`[panel] hold read wk6 FAILED — An error occurred (AccessDenied) when calling the GetObject
operation` (2026-10-18T04:31:07Z, /aws/lambda/coach-panel-podcast) and the sweep read {} —
it could not tell "no hold" from "cannot see the hold".

Read from SOURCE (AST), not by importing role_policies: other test files stub
aws_cdk.aws_iam with a PolicyStatement that drops `conditions`, so an import-based check
would see a different object depending on test order (the #4622 precedent).
"""

import ast
import os
import re

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROLES = os.path.join(REPO, "cdk", "stacks", "role_policies_email.py")
LAMBDA = os.path.join(REPO, "lambdas", "emails", "coach_panel_podcast_lambda.py")


def _statements(src: str, fn_name: str) -> list[dict]:
    tree = ast.parse(src)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == fn_name)
    out = []
    for call in ast.walk(fn):
        if isinstance(call, ast.Call) and getattr(call.func, "attr", None) == "PolicyStatement":
            kw = {k.arg: k.value for k in call.keywords}
            out.append(
                {
                    "sid": ast.literal_eval(kw["sid"]),
                    "actions": ast.literal_eval(kw["actions"]),
                    "resources": ast.unparse(kw["resources"]),
                    "conditions": ast.literal_eval(kw["conditions"]) if "conditions" in kw else None,
                }
            )
    return out


def _hold_prefix() -> str:
    m = re.search(r'^HOLD_PREFIX = "([^"]+)"', open(LAMBDA, encoding="utf-8").read(), re.M)
    assert m, "HOLD_PREFIX moved — re-point this test"
    return m.group(1)


@pytest.fixture(scope="module")
def panel_statements() -> list[dict]:
    return _statements(open(ROLES, encoding="utf-8").read(), "email_coach_panel_podcast")


def test_the_panel_role_lists_the_holds_prefix_and_only_that(panel_statements):
    lists = [s for s in panel_statements if "s3:ListBucket" in s["actions"]]
    assert len(lists) == 1, f"expected exactly one ListBucket statement on the Panel role, got {lists}"
    (lb,) = lists
    assert lb["sid"] == "PanelcastHoldsList"
    assert lb["actions"] == ["s3:ListBucket"], "ListBucket rides alone — it is a bucket-level action"
    assert lb["resources"] == "[BUCKET_ARN]", "ListBucket is a bucket action; an object ARN grants nothing"
    assert lb["conditions"] == {"StringLike": {"s3:prefix": [f"{_hold_prefix()}/*"]}}


def test_the_list_prefix_is_the_prefix_the_lambda_reads(panel_statements):
    """The condition names the lambda's own HOLD_PREFIX, so a rename of either side fails here
    instead of re-opening the AccessDenied silently."""
    lb = next(s for s in panel_statements if s["sid"] == "PanelcastHoldsList")
    (prefix_glob,) = lb["conditions"]["StringLike"]["s3:prefix"]
    assert prefix_glob == f"{_hold_prefix()}/*"
    read_delete = next(s for s in panel_statements if s["sid"] == "PanelcastHoldsReadDelete")
    assert f"{_hold_prefix()}/*" in read_delete["resources"], "the GetObject grant and the List grant must name the same prefix"


def test_mutation_control_a_missing_or_unscoped_grant_is_caught():
    """Mutation control: delete the statement → the first test's `len == 1` fails; widen the
    condition (drop it, or point it at generated/*) → the condition assertion fails. Proven by
    running the checks against the mutated source in-process, not by hand."""
    src = open(ROLES, encoding="utf-8").read()
    # (a) grant removed entirely
    start = src.index('                sid="PanelcastHoldsList",')
    stmt_open = src.rindex("iam.PolicyStatement(", 0, start)
    stmt_close = src.index("),\n", start) + len("),\n")
    removed = src[:stmt_open] + src[stmt_close:]
    assert not [s for s in _statements(removed, "email_coach_panel_podcast") if "s3:ListBucket" in s["actions"]]
    # (b) condition widened to a different prefix
    widened = src.replace('"s3:prefix": ["panelcast-holds/*"]', '"s3:prefix": ["generated/*"]')
    assert widened != src
    lb = next(s for s in _statements(widened, "email_coach_panel_podcast") if s["sid"] == "PanelcastHoldsList")
    assert lb["conditions"] != {"StringLike": {"s3:prefix": [f"{_hold_prefix()}/*"]}}
    # (c) condition dropped → unconditioned bucket-wide list
    dropped = re.sub(r'\n\s*conditions=\{"StringLike": \{"s3:prefix": \["panelcast-holds/\*"\]\}\},', "", src)
    assert dropped != src
    lb = next(s for s in _statements(dropped, "email_coach_panel_podcast") if s["sid"] == "PanelcastHoldsList")
    assert lb["conditions"] is None
