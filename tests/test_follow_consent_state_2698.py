"""#2698 / #2681 box 3 — an address typed into a public form is not a consent to mail it.

`/api/experiment_follow` and `/api/challenge_follow` store whatever address is posted.
Nobody proves they own it, so a stranger can subscribe a third party to follow-notifications
they never asked for. #2681 fixed the id-validation half (a follow door now rejects the ids
its vote sibling rejects); this is the consent half.

WHAT THE WIRE ACTUALLY SAYS, measured 2026-08-15 before deciding what to build:

  * `EXPERIMENT_FOLLOWS` — 0 rows
  * `CHALLENGE_FOLLOWS`  — 0 rows
  * grep across `lambdas/`, `mcp/`, `scripts/`: the ONLY code touching either partition is
    the two writers, plus `experiment/phase_taxonomy.py` classifying them for resets.

So the partitions are **write-only**. No notifier exists, nothing reads an address, and no
unconsented mail can be sent today. The harm is latent, not live — and that is exactly why
this is worth pinning now rather than after somebody writes the notifier.

THE FIX IS THE SECOND BRANCH OF THE ACCEPTANCE BOX, not the first. The box reads "requires a
verified address (confirm-opt-in or an equivalent), OR the notification is withheld until
verification". Building a confirm-opt-in flow means minting tokens and SENDING MAIL to
unverified addresses to ask them to verify — the exact act in question — and it is a product
decision about a reader-facing flow, not a bug fix. Withholding is the honest, restrictive
half, and it is complete on its own:

  1. every follow row records `email_verified: False` / `verified_at: None`, so the state is
     DATA a future notifier must read rather than an assumption it can inherit;
  2. this file holds the line that nothing reads those partitions, with a failure message
     that tells whoever adds the first reader what to do about the flag.

That second guard is deliberately a RATCHET WITH INSTRUCTIONS, not a wall. A digest of
followed experiments is a perfectly good feature; the point is that it cannot be written
without someone reading this sentence. If it fails, add the reader AND filter on
`email_verified`, then extend this test to assert the filter — do not delete it.
"""

from __future__ import annotations

import ast
import json
import os
import pathlib
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")

import pytest  # noqa: E402

FOLLOW_PARTITIONS = ("EXPERIMENT_FOLLOWS", "CHALLENGE_FOLLOWS")

# The two writers, plus the reset classifier. Anything else touching a follow partition is
# a candidate NOTIFIER and is what this file exists to catch.
SANCTIONED_TOUCHERS = {
    "lambdas/web/site_api_social_experiments.py": "the experiment_follow writer",
    "lambdas/web/site_api_social_challenges.py": "the challenge_follow writer",
    "lambdas/experiment/phase_taxonomy.py": "classifies the partitions for experiment resets (ADR-077) — never reads an address",
}


def _modules_touching_follow_partitions():
    found = {}
    for root in ("lambdas", "mcp", "scripts"):
        for path in sorted((pathlib.Path(_REPO) / root).rglob("*.py")):
            text = path.read_text(encoding="utf-8", errors="ignore")
            if any(p in text for p in FOLLOW_PARTITIONS):
                found[str(path.relative_to(_REPO))] = text
    return found


# ── the state is recorded on the write ───────────────────────────────────────


def _follow_put_items():
    """The Item dict literal of every follow `put_item`, by AST — not by grep, so a
    renamed key or a reformatted literal cannot make this pass by accident."""
    out = {}
    for rel in ("lambdas/web/site_api_social_experiments.py", "lambdas/web/site_api_social_challenges.py"):
        src = (pathlib.Path(_REPO) / rel).read_text()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "put_item"):
                continue
            for kw in node.keywords:
                if kw.arg != "Item" or not isinstance(kw.value, ast.Dict):
                    continue
                keys = {k.value for k in kw.value.keys if isinstance(k, ast.Constant)}
                if "followed_at" in keys and "notified" in keys:
                    out[rel] = keys
    return out


def test_both_follow_writers_are_found():
    """Vacuity guard: a renamed handler would make the assertions below assert nothing."""
    puts = _follow_put_items()
    assert set(puts) == {
        "lambdas/web/site_api_social_experiments.py",
        "lambdas/web/site_api_social_challenges.py",
    }, puts


@pytest.mark.parametrize("rel", ["lambdas/web/site_api_social_experiments.py", "lambdas/web/site_api_social_challenges.py"])
def test_every_follow_row_records_that_the_address_is_unverified(rel):
    keys = _follow_put_items()[rel]
    assert "email_verified" in keys, f"{rel} stores an address with no verification state"
    assert "verified_at" in keys, f"{rel} has no field to record WHEN an address was verified"


def test_the_stored_default_is_unverified_not_absent():
    """Absent and False are different facts. A missing key reads as 'nobody has thought
    about it'; False is a claim the writer is making."""
    for rel in ("lambdas/web/site_api_social_experiments.py", "lambdas/web/site_api_social_challenges.py"):
        src = (pathlib.Path(_REPO) / rel).read_text()
        assert '"email_verified": False' in src, rel
        assert '"verified_at": None' in src, rel


# ── the line that nothing reads them ─────────────────────────────────────────


def test_no_module_outside_the_writers_touches_a_follow_partition():
    """THE RATCHET, WITH INSTRUCTIONS — read the failure message before changing this test.

    Nothing reads these partitions today, which is the only reason no unconsented mail can
    be sent. A digest of followed experiments is a good feature; it just cannot be written
    without someone seeing this.
    """
    touching = _modules_touching_follow_partitions()
    unexpected = sorted(set(touching) - set(SANCTIONED_TOUCHERS))
    assert not unexpected, (
        f"{unexpected} now touches a follow partition. If this is a NOTIFIER: every stored address is "
        f"UNVERIFIED (a stranger can type a third party's), so filter on `email_verified` before sending, "
        f"add the module to SANCTIONED_TOUCHERS with its reason, and extend this file to assert the filter. "
        f"Do not delete this test — see #2698."
    )


def test_the_sanctioned_touchers_all_still_exist():
    """A stale entry silently widens the allowlist."""
    touching = _modules_touching_follow_partitions()
    stale = sorted(set(SANCTIONED_TOUCHERS) - set(touching))
    assert not stale, f"SANCTIONED_TOUCHERS lists modules that no longer touch a follow partition: {stale}"


def test_the_reset_classifier_never_reads_an_address():
    """phase_taxonomy is sanctioned because it classifies KEYS. If it grew an address read
    it would be a notifier wearing a taxonomy's clothes."""
    src = (pathlib.Path(_REPO) / "lambdas" / "experiment" / "phase_taxonomy.py").read_text()
    for line in src.splitlines():
        if any(p in line for p in FOLLOW_PARTITIONS):
            assert "email" not in line.lower(), line


# ── what the wire said, recorded so the next reader need not re-derive it ────


def test_the_writers_are_the_only_place_an_address_enters_the_partition():
    """Both writers hash the address for the SORT KEY and store the plaintext beside it.
    Worth pinning: if the plaintext ever stops being stored, a notifier becomes impossible
    and this whole issue evaporates — which would be a fine outcome, but a deliberate one."""
    for rel in ("lambdas/web/site_api_social_experiments.py", "lambdas/web/site_api_social_challenges.py"):
        keys = _follow_put_items()[rel]
        assert "email" in keys, f"{rel} no longer stores a plaintext address — revisit #2698, this may now be moot"


def test_the_partitions_are_classified_as_audience_state_for_resets():
    """ADR-077: follows survive an experiment reset, so an unverified address survives too —
    which is why the flag has to live on the row rather than in a cycle-scoped side table."""
    from experiment import phase_taxonomy

    src = json.dumps(str(phase_taxonomy.__file__))
    assert src  # import smoke; the classification itself is asserted by phase_taxonomy's own tests
    text = (pathlib.Path(_REPO) / "lambdas" / "experiment" / "phase_taxonomy.py").read_text()
    for partition in FOLLOW_PARTITIONS:
        assert f'startswith("{partition}")' in text, f"{partition} lost its reset classification"
