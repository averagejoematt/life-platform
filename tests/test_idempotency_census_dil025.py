#!/usr/bin/env python3
"""tests/test_idempotency_census_dil025.py — the census stays honest (DIL-025).

`docs/IDEMPOTENCY.md` states, per external-side-effect path, what happens if it
runs twice with the same input. A census is only worth the paper it is on for as
long as it is complete, and the way these documents die is silent: someone ships
a 29th email sender, never thinks about redrive, and the file still *looks*
authoritative because nothing points at the hole.

So this file does not carry a hand-written list of senders. It **derives** the
set from source — reusing `test_ses_send_guard_set_2222.derive_ses_sending_handlers`,
the same walk the #2222 send-suppressor ratchet uses, so the census and the send
gate can never disagree about who is in the set — and asserts every member has a
row. A new SES-sending handler fails this file BY NAME until someone writes down
its replay semantics.

This is the repo's standing "guard the SET, not the instance" pattern. It is
also, deliberately, the *cheapest possible* guard: it checks presence, not
prose. It cannot tell you a row is honest — only that no path is missing one.
The rows' accuracy is the reviewer's job; the rows' existence is this file's.

Non-vacuity is proved rather than assumed (three privacy screens have shipped in
this repo whose full suite passed with the screen deleted): the derivation is
parameterised by root, so the tests below build a synthetic tree containing a
sender that is absent from the census and assert the check flags it.

Everything here is offline: no module is imported, no AWS client is built.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TESTS = REPO_ROOT / "tests"
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))

from test_ses_send_guard_set_2222 import derive_ses_sending_handlers  # noqa: E402

CENSUS = REPO_ROOT / "docs" / "IDEMPOTENCY.md"
LAMBDAS = REPO_ROOT / "lambdas"

#: Webhook / HTTP-triggered ingestion entry points that must carry a row. Held
#: as a literal because "is this reachable from the internet" is a CDK fact, not
#: a source-shape fact — see `test_the_live_webhook_set_is_still_what_the_census_says`,
#: which re-derives it from cdk/ so a new HTTP route cannot land unnoticed.
LIVE_WEBHOOK_MODULES = {
    "lambdas/ingestion/health_auto_export_lambda.py",
}

#: Modules that parse an HTTP event but are NOT deployed. The census says so; if
#: one of these ever gains a CDK route it must move to the set above.
PARKED_WEBHOOK_MODULES = {
    "lambdas/ingestion/hevy_webhook_lambda.py",
}


def census_text() -> str:
    return CENSUS.read_text(encoding="utf-8")


def missing_sender_rows(root: Path, text: str) -> list:
    """Every derived SES-sending handler with no mention in the census.

    Matches on the module's repo-relative path as it appears in the census's
    code spans (e.g. `emails/daily_brief_lambda.py`). Parameterised by root so
    the mutation tests below can drive it against a synthetic tree.
    """
    return [rel for rel in sorted(derive_ses_sending_handlers(root)) if rel not in text]


# ══════════════════════════════════════════════════════════════════════════════
# The ratchet
# ══════════════════════════════════════════════════════════════════════════════


def test_the_census_exists_and_is_not_a_stub():
    assert CENSUS.exists(), "docs/IDEMPOTENCY.md is gone — DIL-025's deliverable"
    assert len(census_text()) > 4000, "the census has been gutted to a stub"


def test_every_ses_sending_handler_has_a_census_row():
    """THE test. A 29th sender must declare its replay semantics or fail here."""
    missing = missing_sender_rows(LAMBDAS, census_text())
    assert not missing, (
        "SES-sending Lambda handlers with no row in docs/IDEMPOTENCY.md.\n"
        "Every path that can put mail on the wire must state what happens when it\n"
        "runs twice with the same payload — an honest 'N' row is a fine answer;\n"
        "silence is not (DIL-025). Add a row in §2.\n  " + "\n  ".join(missing)
    )


def test_the_derivation_actually_found_the_fleet():
    """Sanity floor: if the walk returned {} every assertion above would pass
    vacuously, which is precisely how a census guard rots into decoration."""
    derived = derive_ses_sending_handlers(LAMBDAS)
    assert len(derived) >= 25, f"derivation found only {len(derived)} SES senders — the walk is broken"


def test_the_census_states_the_size_of_the_set_it_covers():
    """The finding assumed 7 senders; the derived set is 28. That correction is
    load-bearing — if the real count drifts from the number written in the
    census, the document is lying about its own scope."""
    derived = derive_ses_sending_handlers(LAMBDAS)
    text = census_text()
    assert re.search(rf"\b{len(derived)}\b", text), (
        f"the census must state the size of the SES set it covers (now {len(derived)}) — "
        "a stale count is the first sign the document stopped being maintained"
    )


def test_every_live_webhook_has_a_census_row():
    text = census_text()
    for module in sorted(LIVE_WEBHOOK_MODULES):
        leaf = module.split("/", 1)[1]  # `ingestion/health_auto_export_lambda.py`
        assert leaf in text or module in text, f"{module} is an internet-reachable write path with no census row (DIL-025 §3)"


def cdk_defines_handler(module_rel: str, cdk_root: Path) -> bool:
    """True when cdk/stacks actually DEFINES a Lambda for `lambdas/<module_rel>`.

    AST-derived, deliberately: `hevy_webhook_lambda.py` is named four times in
    cdk/stacks — every one of them inside a comment explaining that the function
    was REMOVED (#756). A substring check reads those as a live definition and
    reports the exact opposite of the truth. Only a `handler=` or `source_file=`
    keyword on a real `Call` counts.

    HAE is defined with `code=staged_tree_asset()` rather than `source_file=`
    (see the NOTE at ingestion_stack.py:534), so both spellings are matched.
    """
    import ast

    stem = Path(module_rel).stem  # health_auto_export_lambda
    package = Path(module_rel).parent.name  # ingestion
    handler_prefix = f"{package}.{stem}."
    source_literal = f"lambdas/{module_rel}"

    for path in sorted(cdk_root.glob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for kw in node.keywords:
                if kw.arg not in ("handler", "source_file") or not isinstance(kw.value, ast.Constant):
                    continue
                value = kw.value.value
                if not isinstance(value, str):
                    continue
                if value == source_literal or value.startswith(handler_prefix):
                    return True
    return False


def test_the_live_webhook_set_is_still_what_the_census_says():
    """Re-derive "is it actually deployed" from cdk/ rather than trusting the
    literal above. A parked handler that gains an HTTP route — or a live one
    that loses it — is a census-scope change, and must fail here rather than
    quietly leaving a real write path uncensused."""
    cdk_root = REPO_ROOT / "cdk" / "stacks"
    for module in sorted(LIVE_WEBHOOK_MODULES):
        rel = module.split("/", 1)[1]
        assert cdk_defines_handler(rel, cdk_root), f"{module} is censused as LIVE but cdk/stacks defines no Lambda for it"
    for module in sorted(PARKED_WEBHOOK_MODULES):
        rel = module.split("/", 1)[1]
        assert not cdk_defines_handler(rel, cdk_root), (
            f"{module} is censused as PARKED (not deployed) but cdk/stacks now defines it — "
            "it is a live write path and its census row must move out of the parked note in §3"
        )


def test_mutation_the_cdk_definition_check_reads_definitions_not_comments(tmp_path):
    """The exact false positive this replaced: a module named only inside a
    comment about its own removal must NOT read as defined."""
    cdk_dir = tmp_path / "stacks"
    cdk_dir.mkdir(parents=True)
    (cdk_dir / "s.py").write_text(
        "# ingestion_hevy_webhook() removed — lambdas/ingestion/hevy_webhook_lambda.py stays in git history\n"
        "def build(scope):\n"
        "    create_platform_lambda(scope, 'X', handler='ingestion.other_lambda.lambda_handler')\n",
        encoding="utf-8",
    )
    assert cdk_defines_handler("ingestion/hevy_webhook_lambda.py", cdk_dir) is False
    assert cdk_defines_handler("ingestion/other_lambda.py", cdk_dir) is True


def test_the_shared_replay_primitive_is_named_so_the_next_sender_finds_it():
    """A census that diagnoses without pointing at the cure gets read once."""
    text = census_text()
    assert "common/send_ledger.py" in text
    assert (LAMBDAS / "common" / "send_ledger.py").exists(), "the census points at a primitive that does not exist"


def test_the_three_replay_vectors_are_named():
    """The census's value is that it explains WHY a duplicate happens — a reader
    who does not know about DLQ redrive will conclude the dry-run flag covers
    them (which is exactly the confusion DIL-025 found)."""
    text = census_text().lower()
    for vector in ("async retry", "redrive", "manual re-invoke"):
        assert vector in text, f"the census no longer explains the {vector!r} replay vector"


def test_the_filed_followups_are_referenced():
    """Every non-cheap gap class was filed rather than hand-waved; the census
    rows must carry the issue numbers so a reader can see the work is tracked."""
    text = census_text()
    for issue in ("#3113", "#3114", "#3115", "#3118", "#3119"):
        assert issue in text, f"census no longer references the filed follow-up {issue}"


# ══════════════════════════════════════════════════════════════════════════════
# Non-vacuity: the check must FAIL on a tree it should fail on
# ══════════════════════════════════════════════════════════════════════════════


_SENDER = """
import boto3
from common.send_guard import guarded_send_email, is_dry_run
ses = boto3.client("sesv2")

def lambda_handler(event, context):
    dry_run = is_dry_run(event)
    guarded_send_email(ses, dry_run, FromEmailAddress="a@b.c", Destination={"ToAddresses": ["d@e.f"]})
    return {"statusCode": 200}
"""


def _tree(tmp_path, name, src=_SENDER):
    p = tmp_path / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(src, encoding="utf-8")
    return tmp_path


def test_mutation_a_new_sender_absent_from_the_census_is_caught(tmp_path):
    """Inject a 29th SES-sending handler and check it against the REAL census
    text — it is not mentioned there, so the guard must name it. If this passes
    when it shouldn't, `test_every_ses_sending_handler_has_a_census_row` is
    decoration."""
    root = _tree(tmp_path, "emails/rogue_sender_lambda.py")
    missing = missing_sender_rows(root, census_text())
    assert missing == ["emails/rogue_sender_lambda.py"]


def test_mutation_a_sender_that_IS_censused_is_accepted(tmp_path):
    """Positive control — the guard must not simply flag everything."""
    root = _tree(tmp_path, "emails/rogue_sender_lambda.py")
    text = census_text() + "\n| `emails/rogue_sender_lambda.py` | schedule | test | test |\n"
    assert missing_sender_rows(root, text) == []


def test_mutation_a_gutted_census_fails_the_real_set(tmp_path):
    """The realistic rot: the file survives but its tables are emptied. Every
    real sender must then be reported missing, not zero of them."""
    missing = missing_sender_rows(LAMBDAS, "# IDEMPOTENCY.md\n\n(nothing here)\n")
    assert len(missing) >= 25, "an empty census must flag the whole fleet"


def test_mutation_a_non_sender_is_not_required_to_have_a_row(tmp_path):
    """Scope control: a helper module that mails on a handler's behalf is not
    itself invocable, so it is not a census member."""
    helper = """
import boto3
ses = boto3.client("sesv2")

def send_it():
    ses.send_email(FromEmailAddress="a@b.c")
"""
    root = _tree(tmp_path, "emails/helper_only.py", helper)
    assert missing_sender_rows(root, "") == []
