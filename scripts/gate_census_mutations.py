"""scripts/gate_census_mutations.py — the mechanised can-it-fail verdicts for census
family 5, the tree-sweeping structural pytest gates (#2999, epic #2578 slice 2).

# module-size-exception: a MUTATION-SPEC + PROOF REGISTRY, same shape and same reason
# as gate_census_proofs.py's own exception a few lines up the import graph — one
# `MutationSpec` (the plant, the target, the expected direction) plus one recorded
# verdict per gate that earned one. It grows by exactly one spec/proof pair each time a
# gate is proved, which is the ratchet working, not drift; there is no logic here to
# factor smaller, and splitting the specs from their proofs would put a gate's plant and
# its verdict in two files for no reason (#3731 crossed 1,000 lines adding four such
# pairs for the newly-discovered tree-sweeping gates in tests/repo_scan_cache.py).

WHY ITS OWN MODULE
──────────────────
`scripts/gate_census.py` sits at 1,164 lines against the 1,200-line hard ceiling
(`tests/test_module_size_guard.py`, #1665) and was never baselined — #2610's policy is
extraction, never a new BASELINE entry. A batch of verdicts does not fit. Same one-way
split shape as `gate_census_proofs.py` / `gate_census_structural.py`: this module has
ZERO dependency on `gate_census`, so there is no import cycle even when `gate_census.py`
runs directly as `__main__`. It exports plain dicts and `gate_census` builds its own
`Proof` from them.

WHY A HARNESS AND NOT PROSE
───────────────────────────
#2999's problem statement: "verdicts at 490-scale cannot be hand-driven ... where the
mutation can be generated and run automatically, the verdict is a build product, not a
session's attention." The other two verdict batches in this census (`PROVEN_CAN_FAIL`,
`SENTINEL_PROOFS`) are hand-written records of a mutation a human performed once. They
are honest, and they do not re-run — a gate that goes dark six months from now keeps its
`can-fail (proven)` stamp, which is precisely the "a stamp is a human claim" failure
(#973/#2619). Family 5 is the family where that can be fixed, because every gate in it
is a pytest file that sweeps the tracked tree, so its defect is a FILE you can write.

So each verdict here is a `MutationSpec` — the plant, the target, and the expected
direction — and `run_spec()` executes the whole control, in this order:

    1. BASELINE   run the target on the clean tree      -> must be GREEN
    2. MUTATED    plant the defect (git-add if the gate  -> must be RED
                  reads the tracked set), run again
    3. REVERTED   remove the plant, run again           -> must be GREEN again

A gate is ARMED only when all three hold. Step 1 is what stops a already-red target from
counting as a proof; step 3 is what stops a leaked plant from poisoning the next spec.
A RED in step 2 with no GREEN on either side proves nothing, and the runner says so
rather than reporting a verdict.

    python3 scripts/gate_census_mutations.py --run              # every spec
    python3 scripts/gate_census_mutations.py --run --gate test_xfail_hygiene.py
    python3 scripts/gate_census_mutations.py --list

WHAT A DARK RESULT IS, AND IS NOT
─────────────────────────────────
A spec that does not go red is a LEAD, not a `cannot-fail` verdict. The overwhelmingly
likely cause is that the plant missed the predicate (wrong directory, wrong suffix, the
gate reads the git index and the plant was not added). Only after the plant is confirmed
to sit inside the gate's declared scope is "the gate could not fail" the finding — and
then it gets an issue, per #2999's third acceptance box. Nothing here is allowed to
report a verdict it did not watch.

AN md5 ON THE SOURCE IS NOT A PROOF THE MUTATION RAN (#3599, 2026-09-18)
────────────────────────────────────────────────────────────────────────
The standing rule for a hand-driven control in this repo is "assert the file's md5
CHANGED before you read the verdict", because a `sed -i ''` that matched nothing exits 0
on macOS and a silent no-op reports the guard working. That rule is necessary and it is
NOT sufficient, and #3599 is the specimen: its mutation M3 edited `_WEIGHT_MIN_LBS =
100.0` to `400.0` in the real tracked module, the md5 duly changed, and the target still
reported 39 passed. The gate was fine. The control was blind.

`100.0` and `400.0` are the same number of bytes, and CPython validates a cached
bytecode file on `(source mtime, source size)` — neither moved past the granularity the
check uses, so the interpreter re-used the compiled copy under the target's
`__pycache__` and ran the ORIGINAL module. **A hash over the source proves the FILE
changed; it never proves the CODE UNDER TEST did.** With the cache purged, the same
mutation reds 11 tests.

`run_spec()` below is immune by construction — it plants a NEW file rather than editing
an existing one, so there is no stale compiled copy to hit. A hand-driven control has no
such protection, so it must do both:

  * assert the md5 (or a diff) changed — the plant landed on disk at all; and
  * make the compiled copy irrelevant — delete the target's `__pycache__` and run the
    child interpreter with `-B` / `PYTHONDONTWRITEBYTECODE=1` before reading a verdict.

Prefer a mutation that also changes the file's LENGTH where the choice is free; it makes
the trap unreachable rather than merely handled. Do not rely on that as the guard,
though — "I happened to pick a longer replacement" is not a property the next author
inherits.

THE PLANT LITERALS ARE ASSEMBLED, ON PURPOSE
────────────────────────────────────────────
Several of the gates below sweep EVERY tracked file, including this one. Writing their
banned literal into this module verbatim would red them permanently — the harness would
become the defect it exists to plant. Those bodies are assembled from fragments by
`_lit()`, with the reason on each call site. This is not obfuscation for its own sake:
an un-assembled literal here is a self-inflicted repo-wide failure.
"""

from __future__ import annotations

import argparse
import copy
import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent


def _lit(*parts: str) -> str:
    """Join fragments into a literal that must not appear verbatim in this file.

    See the module docstring: these are the banned strings the planted gates sweep the
    whole tracked tree for, this file included.
    """
    return "".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# The specs
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class MutationSpec:
    """One generated mutation. `plants` + `target` must be enough to re-run it."""

    gate_id: str  # the census id this proves, e.g. "structural::test_xfail_hygiene.py"
    target: str  # the pytest target, repo-relative
    detects: str  # one line: the defect class the plant introduces
    plants: tuple[tuple[str, str], ...]  # (repo-relative path, content)
    track: bool = True  # git-add the plants (the gate reads the tracked set)
    extra_args: tuple[str, ...] = field(default_factory=tuple)


_CONFLICT_BLOCK = "\n".join(
    [
        "# probe",
        # Assembled: tests/test_no_conflict_markers.py sweeps every tracked file for
        # exactly these three prefixes, and this module is a tracked file.
        _lit("<" * 7, " HEAD"),
        "left side",
        _lit("=" * 7),
        "right side",
        _lit(">" * 7, " branch"),
        "",
    ]
)

# Assembled: tests/test_no_private_markers_3043.py sweeps every tracked text file for a
# doc-status header declaring the file itself private, and only allowlists its own source.
_PRIVATE_MARKER_DOC = "# probe\n\n> **Status:** " + _lit("PRIV", "ATE") + " / internal. Do not surface.\n"

# Assembled: tests/test_no_tool_attribution_3005.py bans any MENTION of any of the three
# banned attribution forms (co-author trailer, session-link line, generated-with footer —
# #3328) on any tracked file outside CLAUDE.md and the guard itself. This plant is form 1.
_ATTRIBUTION_DOC = "# probe\n\n" + _lit("Co-Author", "ed-By") + ": Claude Opus 5 <noreply@anthropic.com>\n"

# Assembled: tests/test_timezone_discipline.py scans scripts/ as well as lambdas/, so the
# banned fixed-offset idiom cannot appear verbatim in this file. This one is not
# hypothetical — the first draft of this module wrote the idiom whole into a single
# fragment, and the harness's own BASELINE step caught it (`baseline is already RED`)
# before a single verdict was recorded. That is the control doing its job on its author.
_FIXED_OFFSET_PY = (
    '"""probe."""\n\n'
    "from datetime import timedelta, timezone\n"
    "from datetime import datetime\n\n\n"
    "def probe():\n"
    "    return datetime."
    + _lit(
        "now(timezone.utc) - timedelta(",
        "hours=8)",
    )
    + "\n"
)

_PACIFIC_FORK_PY = (
    '"""probe."""\n\n'
    "from datetime import datetime\n"
    "from zoneinfo import ZoneInfo\n\n\n"
    "def probe():\n"
    '    return datetime.now(ZoneInfo("America/Los_Angeles")).date().isoformat()\n'
)

_PII_LOG_PY = (
    '"""probe."""\n\n'
    "import logging\n\n"
    "logger = logging.getLogger(__name__)\n\n\n"
    "def probe(email):\n"
    '    logger.info(f"sending to {email}")\n'
)

_UNTYPED_HANDLERS_PY = '"""probe."""\n\n' + "\n\n".join("def lambda_handler(event, context):\n    return {}" for _ in range(24))

_XFAIL_PY = '"""probe."""\n\n' "import pytest\n\n\n" "@pytest.mark.xfail\n" "def test_probe():\n" "    assert False\n"

# #3609 box 3: a hand-rolled DynamoDB query naming an unsanctioned GSI (ADR-097's set is
# exactly {GSI1, GSI2}) — the shape the literal-IndexName scan in
# tests/test_gsi_set_premerge_3609.py exists to catch before it ever reaches AWS.
_UNSANCTIONED_GSI_QUERY_PY = (
    '"""probe."""\n\n'
    "\n"
    "def probe(table, key_condition):\n"
    '    return table.query(IndexName="GSI9", KeyConditionExpression=key_condition)\n'
)

# These carry a secret NAME, never a secret value (Secrets-Manager-only, per CLAUDE.md).
# The identifiers deliberately say `ID` rather than `SECRET`: ruff's flake8-bandit S105
# rules on the TARGET NAME, and `_..._SECRET_PY = "<string>"` reads to it as a hardcoded
# credential. Renaming keeps the gate honest instead of noqa-ing it.
#
# #3255 (2026-08-27) PROMOTED the masked form from DARK_CONTROLS to the armed spec.
# Until then, `test_secret_references.FALSE_POSITIVE_PATTERNS` dropped any LINE
# containing `SECRET_NAME`, so `_MASKED_ID_PY` — the exact wrong-default shape the
# guard's own docstring cites as its reason to exist — left the gate GREEN, and the
# armed spec had to use `_UNKNOWN_ID_PY`, a bare literal that dodges the mask. The gate
# now extracts string CONSTANTS from the AST, where identifiers are unrepresentable, so
# the hard shape is the one worth planting and `_UNKNOWN_ID_PY` is the easy subset of it.
_UNKNOWN_ID_PY = '"""probe."""\n\n' '_PROBE_ID = "life-platform/probe-2999-not-a-real-secret"\n'

_MASKED_ID_PY = (
    '"""probe — the documented root-cause shape (#3255): a wrong secret default."""\n\n'
    "import os\n\n"
    'SECRET_NAME = os.environ.get("SECRET_NAME", "life-platform/probe-2999-not-a-real-secret")\n'
)

# The successor blind spot, measured 2026-08-27 after #3255 landed: the SAME unknown id,
# assembled from two constants instead of written as one. Neither half full-matches a
# secret name, so no `ast.Constant` in the module is a reference and the gate stays green.
# In scope by every reading — it is a shipping Lambda module naming a secret that does not
# exist — and dark, which is what makes it a control rather than a broken plant.
_SPLIT_ID_PY = (
    '"""probe — an unknown secret id assembled from parts rather than written whole."""\n\n'
    '_PREFIX = "life-platform/"\n'
    '_PROBE_ID = _PREFIX + "probe-2999-not-a-real-secret"\n'
)

_DEAD_SYMBOL_PY = '"""probe."""\n\n\n' "def probe(client):\n" "    return client.write_action()\n"

_DEAD_ID_DOCSTRING_PY = '"""probe.\n\nSecret: life-platform/probe-2999-nope (Secrets Manager)\n"""\n'

_ORPHAN_PAGE_HTML = "<!doctype html>\n<html><head><title>probe</title></head><body><p>probe</p></body></html>\n"

_HARDCODED_TIER_PY = (
    '"""probe."""\n\n'
    "from ai.budget_guard import current_tier\n\n\n"
    "def probe():\n"
    "    if current_tier() >= 2:\n"
    "        return None\n"
    "    return 1\n"
)

_OVERSIZE_LAMBDA_PY = '"""probe."""\n\n' + "".join(f"X{i} = {i}\n" for i in range(2400))

# Assembled: tests/test_absence_coverage_3294.py sweeps lambdas/ + mcp/ for any module
# whose AST reads the raw `channels_quiet` field — the presence signal's unlicensed
# category-level absence list — and refuses a reader with no disposition. The literal is
# split so a sweep of scripts/ can never mistake this spec for a consumer.
_RAW_QUIET_READER_PY = '"""probe."""\n\n\ndef probe(sig):\n    return sig.get(' + _lit('"channels_qu', 'iet"') + ")\n"

# Assembled: tests/test_direction_of_travel_ruling_3293.py sweeps lambdas/ + scripts/ +
# mcp/ for every module that reaches for the shared direction-of-travel ruling and is not
# named in its surface registry. `scripts/` is inside that sweep, so writing the module
# name verbatim here would make this harness a permanently-unregistered importer — the
# file would plant its own defect and never be able to revert it.
_UNREGISTERED_DIRECTION_SURFACE_PY = (
    '"""probe."""\n\n'
    "from web." + _lit("journey_", "direction") + " import classify_delta\n\n\n"
    "def probe(lost_lbs):\n"
    "    return classify_delta(lost_lbs)\n"
)

# #3336: a deploy/ apply script carrying an inline IAM policy document for a role that has a
# checked-in infra/iam/*.json twin — the exact shape of the 2026-08-30 incident, where the
# stale shell copy was the one that ran and widened the remediation role's trust for ~6 min.
# Planted UNTRACKED because the guard sweeps deploy/ on disk (rglob), not the index.
_IAM_TWIN_SH = (
    "#!/usr/bin/env bash\n"
    "# census probe 2999 (IAM twin)\n"
    'ROLE="github-actions-remediation-role"\n'
    "PERM=$(cat <<JSON\n"
    '{"Version":"2012-10-17","Statement":[{"Sid":"Bedrock","Effect":"Allow","Action":"bedrock:InvokeModel","Resource":"*"}]}\n'
    "JSON\n"
    ")\n"
    'aws iam put-role-policy --role-name "$ROLE" --policy-name remediation-permissions --policy-document "$PERM"\n'
)

# #3315: a workflow whose job installs `playwright boto3` and then runs a script whose
# capture path needs Pillow — the exact fresh-eyes.yml install line that shipped before
# #3315 (the sweep's own detector is what turned it up). Planted as a NEW workflow file
# because the runner refuses to overwrite a tracked one; the gate globs the directory,
# so an untracked file is in scope.
_DARK_FLAG_WORKFLOW_YML = (
    "name: census probe 2999 (dark flag)\n"
    "on: workflow_dispatch\n"
    "jobs:\n"
    "  probe:\n"
    "    runs-on: ubuntu-latest\n"
    "    steps:\n"
    "      - uses: actions/checkout@v7\n"
    "      - uses: ./.github/actions/setup-ci\n"
    "      - name: Install Playwright + Chromium + boto3 (the pre-#3315 fresh-eyes line)\n"
    "        run: |\n"
    "          PINS=$(python3 scripts/ci_pins.py playwright boto3)\n"
    "          python -m pip install $PINS\n"
    "          python -m playwright install --with-deps chromium\n"
    "      - name: Run discovery\n"
    "        run: python3 scripts/fresh_eyes_discovery.py\n"
)


# #3324: the nullable-aware check-drift rule (diff_shape() in
# deploy/capture_api_schemas.py) must still catch a GENUINE key removal on a hand-
# mutated baseline. Run against a captured FIXTURE, never the live site (this harness
# is offline) — the reference shape is copied from a REAL committed snapshot
# (tests/api_schemas/api_vitals.json) at plant time, not hand-typed, so the proof is
# against real captured data. `tests/test_api_schema_completeness.py` reads this probe
# path if (and only if) it exists; normally it does not, so the gate is a silent no-op
# — the plant is what gives it something to check.
def _drift_probe_plant() -> tuple[str, str]:
    ref_path = REPO_ROOT / "tests" / "api_schemas" / "api_vitals.json"
    reference_shape = json.loads(ref_path.read_text(encoding="utf-8"))["shape"]
    mutated_shape = copy.deepcopy(reference_shape)
    # One hand-removed key — the literal "removed a key" mutation the #3324 acceptance
    # box asks for. `rhr_bpm` is a plain numeric field, unrelated to the nullable rule
    # being proven correct elsewhere, so this proof cannot be mistaken for that one.
    del mutated_shape["keys"]["vitals"]["keys"]["rhr_bpm"]
    body = json.dumps({"reference_shape": reference_shape, "mutated_shape": mutated_shape}, indent=2, sort_keys=True) + "\n"
    return ("tests/fixtures/_census_probe_2999_api_schema_drift.json", body)


# #3503: a first-party module that sweeps CloudWatch alarms and omits `AlarmTypes`, so
# the API's metric-alarms-only default silently hides every composite. This is the exact
# shape the guard exists to catch — six real call sites carried it, and the #3390 fix had
# pinned only one file. Assembled, not written verbatim: the guard sweeps deploy/ and this
# module's own tracked text is not in that scope, but the plant path is.
_BLIND_ALARM_SWEEP_PY = (
    '"""Census probe (#3503) — a whole-estate alarm sweep that states no AlarmTypes."""\n\n'
    "import boto3\n\n\n"
    "def read_reds():\n"
    '    cw = boto3.client("cloudwatch", region_name="us-west-2")\n'
    '    return cw.describe_alarms(StateValue="ALARM", MaxRecords=100).get("MetricAlarms", [])\n'
)


# #3559: a capture door that builds its own `generated/` key instead of asking the seam.
# Assembled from fragments: the literal prefix is what the guard refuses, and this module
# is not in the guard's sweep scope (lambdas/) — but the plant path is.
_PUBLIC_PREFIX_DOOR_PY = (
    '"""Census probe (#3559) — a reader-input door minting a public-prefix key."""\n\n'
    "from web.site_api_capture_store import put_capture_record\n\n\n"
    "def handle(s3, bucket, record, body, qid):\n"
    '    s3_key = f"' + _lit("gener", "ated/board_", "questions/") + '{qid}.json"\n'
    '    return put_capture_record(s3, bucket, s3_key, record, body, door="board_question")\n'
)


# #3731: a new top-level docs/*.md page that is simultaneously (a) a wildly-wrong
# CloudWatch alarm-count CLAIM (`scripts/check_doc_facts.py`'s number-fact scan) and
# (b) missing from the wiki index + missing its status header
# (`scripts/check_doc_index.py`'s coverage/header scan) — one plant, two real scanners,
# both reached ONLY through `tests/repo_scan_cache.py`'s cache by every one of the four
# call sites below. The point of this spec family: `repo_scan_cache` gained a
# disk-backed, tree-state-keyed second layer (#3731) specifically so a scan is shared
# across pytest WORKER PROCESSES — the harness proves the other direction just as hard,
# that sharing never means STALENESS. Untracked (both scanners walk the filesystem, not
# `git ls-files`), so `track=False` is correct and faster.
_DOC_FACTS_INDEX_PROBE_MD = "# Probe (census #3731 plant)\n\nCloudWatch: 999999 alarms total.\n"

# Assembled: tests/test_email_sender_identity_3568.py AST-scans every module under
# lambdas/ for an EMAIL_SENDER default and checks its domain against the committed
# SES-verified set. A .invalid TLD can never be a real identity (RFC 2606).
_UNVERIFIED_SENDER_PY = "# probe\n" "import os\n" "\n" 'SENDER = os.environ.get("EMAIL_SENDER", "reader@census-probe-3568.invalid")\n'

_UNENROLLED_WRITING_LAMBDA_PY = (
    '"""A Lambda entrypoint that writes DynamoDB and that no CDK stack wires to a role."""\n'
    "\n"
    "import boto3\n"
    "\n"
    "table = boto3.resource('dynamodb').Table('life-platform')\n"
    "\n"
    "\n"
    "def lambda_handler(event, context):\n"
    "    table.put_item(Item={'pk': 'USER#matthew#SOURCE#census_probe', 'sk': 'DATE#2026-09-06'})\n"
    "    return {'ok': True}\n"
)


# Assembled: tests/test_judge_verdict_retry_3688.py sweeps lambdas/ mcp/ scripts/ deploy/
# cdk/ for any line that DECIDES on a truncated model reply, and THIS file is under
# scripts/ — writing the idiom whole here would make the mutations module itself an
# unregistered judge and red the guard with no plant at all. Same trap as _FIXED_OFFSET_PY
# above, one gate later.
_UNREGISTERED_JUDGE_PY = (
    '"""probe — a synthetic AI judge that calls a truncated verdict terminal."""\n\n\n'
    "def assess(resp):\n"
    "    if (resp." + _lit('get("stop_re', 'ason") or "") == "max_', 'tokens"') + ":\n"
    '        return "truncated"\n'
    "    return None\n"
)


# #3614: a NEW narrative door that hand-types its own phase line instead of obtaining it
# from ai_context. The census (tests/phase_prompt_census.py) keys on TWO structural facts
# — an AST dict literal in the Bedrock/Anthropic request shape, and a non-docstring prose
# string stating a day number / genesis / restart — so the plant must carry both or it
# proves nothing about the gate. It is deliberately NOT git-added: the census walks
# lambdas/ on disk, and an untracked module is exactly the shape a half-landed door has.
_HAND_TYPED_PHASE_DOOR_PY = (
    '"""probe — a synthetic narrative door that hand-types its own phase line."""\n\n\n'
    "def build_probe_prompt(day_number, start_date, payload):\n"
    "    return {\n"
    '        "model": "claude-haiku",\n'
    '        "max_tokens": 300,\n'
    '        "messages": [\n'
    "            {\n"
    '                "role": "user",\n'
    '                "content": f"Today is Day {day_number} of the experiment, restarted on {start_date}.",\n'
    "            }\n"
    "        ],\n"
    "    }\n"
)

MUTATION_SPECS: dict[str, MutationSpec] = {
    "structural::test_gsi_set_premerge_3609.py": MutationSpec(
        gate_id="structural::test_gsi_set_premerge_3609.py",
        target="tests/test_gsi_set_premerge_3609.py",
        detects=(
            "a hand-rolled boto3 query naming a THIRD, unsanctioned GSI (ADR-097's set is exactly "
            "{GSI1, GSI2}) — the shape a lambdas/ or mcp/ module could introduce without ever touching "
            "reading_keys.py's constants, which the AST-based GSI*_NAME scan alone would not see"
        ),
        plants=(("lambdas/coach/_census_probe_3609.py", _UNSANCTIONED_GSI_QUERY_PY),),
        track=False,  # the gate walks lambdas/+mcp/ on disk (os.walk), so an untracked module is in scope
    ),
    "structural::test_grounding_sets_3614.py": MutationSpec(
        gate_id="structural::test_grounding_sets_3614.py",
        target="tests/test_grounding_sets_3614.py",
        detects=(
            "a NEW prompt builder that states what day of the experiment it is in its own prose instead "
            "of obtaining it from ai_context.build_experiment_phase_context — the #1086 rule whose guard "
            "was a per-door test plus a hand-typed list of eight modules, so it could not fail on the "
            "door nobody added to it"
        ),
        plants=(("lambdas/web/_census_probe_3614.py", _HAND_TYPED_PHASE_DOOR_PY),),
        track=False,  # the census walks lambdas/ on disk (os.walk), so an untracked module is in scope
    ),
    "structural::test_judge_verdict_retry_3688.py": MutationSpec(
        gate_id="structural::test_judge_verdict_retry_3688.py",
        target="tests/test_judge_verdict_retry_3688.py",
        detects=(
            "a NEW AI-judge call site that records a truncated/unparseable verdict as terminal with no "
            "retry — the #3688 class, which cannot surface post-merge because `ai-unevaluated` is a "
            "DECLINE class in visual_qa_verdict.py, so the gate reds and the deploy is never reverted"
        ),
        plants=(("lambdas/operational/_census_probe_3688.py", _UNREGISTERED_JUDGE_PY),),
        track=False,  # the guard walks the filesystem (os.walk), not the git index
    ),
    "structural::test_role_family_write_scope.py": MutationSpec(
        gate_id="structural::test_role_family_write_scope.py",
        target="tests/test_role_family_write_scope.py",
        detects=(
            "a Lambda entrypoint that writes DynamoDB while no create_platform_lambda call maps it to a "
            "role — so nothing checks whether its write is granted, which is how #3563's two writes were "
            "denied for 28 and 49 days behind a FakeDdbTable that cannot deny a put_item"
        ),
        plants=(("lambdas/operational/_census_probe_3596_lambda.py", _UNENROLLED_WRITING_LAMBDA_PY),),
        track=False,  # the guard walks lambdas/ on disk (os.walk), so an untracked module is in scope
    ),
    "structural::test_email_sender_identity_3568.py": MutationSpec(
        gate_id="structural::test_email_sender_identity_3568.py",
        target="tests/test_email_sender_identity_3568.py",
        detects=(
            "a sender default on a domain SES has not verified for sending — the shape that let "
            "between_chronicle default to an identity that did not exist while every test stayed green (#3568)"
        ),
        plants=(("lambdas/common/_census_probe_3568.py", _UNVERIFIED_SENDER_PY),),
        track=False,  # the guard rglobs lambdas/ on disk, not the git index
    ),
    "structural::test_composite_alarm_lookup_3390.py": MutationSpec(
        gate_id="structural::test_composite_alarm_lookup_3390.py",
        target="tests/test_composite_alarm_lookup_3390.py",
        detects=(
            "a CloudWatch alarm sweep that omits AlarmTypes, so the API's metric-alarms-only "
            "default makes every composite invisible to it (#3390 fixed one file; #3503 the other five)"
        ),
        plants=(("deploy/_census_probe_3503.py", _BLIND_ALARM_SWEEP_PY),),
        track=False,  # the guard walks the filesystem (os.walk), not the git index
    ),
    "structural::test_no_conflict_markers.py": MutationSpec(
        gate_id="structural::test_no_conflict_markers.py",
        target="tests/test_no_conflict_markers.py",
        detects="an unresolved merge whose markers reached a tracked file (the #2200 incident)",
        plants=(("docs/_census_probe_2999.md", _CONFLICT_BLOCK),),
    ),
    "structural::test_root_clutter_guard.py": MutationSpec(
        gate_id="structural::test_root_clutter_guard.py",
        target="tests/test_root_clutter_guard.py",
        detects="a new, unlisted first-party top-level directory entering the git index (#1652 D1 ratchet)",
        plants=(("_census_probe_2999_dir/probe.txt", "probe\n"),),
    ),
    "structural::test_no_private_markers_3043.py": MutationSpec(
        gate_id="structural::test_no_private_markers_3043.py",
        target="tests/test_no_private_markers_3043.py",
        detects="a tracked file in a public repo declaring itself private (DIL-001)",
        plants=(("docs/_census_probe_2999.md", _PRIVATE_MARKER_DOC),),
    ),
    "structural::test_no_tool_attribution_3005.py": MutationSpec(
        gate_id="structural::test_no_tool_attribution_3005.py",
        target="tests/test_no_tool_attribution_3005.py",
        detects="a tracked instruction surface re-teaching the banned attribution trailer",
        plants=(("docs/_census_probe_2999.md", _ATTRIBUTION_DOC),),
    ),
    "structural::test_timezone_discipline.py": MutationSpec(
        gate_id="structural::test_timezone_discipline.py",
        target="tests/test_timezone_discipline.py",
        detects="fixed-offset Pacific math (PST pinned year-round — the 2026-06-12 DST bug class)",
        plants=(("lambdas/common/_census_probe_2999.py", _FIXED_OFFSET_PY),),
        track=False,
    ),
    "structural::test_time_invariant_helpers_1964.py": MutationSpec(
        gate_id="structural::test_time_invariant_helpers_1964.py",
        target="tests/test_time_invariant_helpers_1964.py",
        detects="a Pacific frame derived outside the canonical helper (#1964)",
        plants=(("lambdas/common/_census_probe_2999.py", _PACIFIC_FORK_PY),),
        track=False,
    ),
    "structural::test_pii_log_guard_2369.py": MutationSpec(
        gate_id="structural::test_pii_log_guard_2369.py",
        target="tests/test_pii_log_guard_2369.py",
        detects="a logging call interpolating a raw email address (#2369)",
        plants=(("lambdas/common/_census_probe_2999.py", _PII_LOG_PY),),
        track=False,
    ),
    "structural::test_handler_type_hints.py": MutationSpec(
        gate_id="structural::test_handler_type_hints.py",
        target="tests/test_handler_type_hints.py",
        detects="new untyped lambda_handler entry points pushing the count past its ratchet",
        plants=(("lambdas/common/_census_probe_2999.py", _UNTYPED_HANDLERS_PY),),
        track=False,
    ),
    "structural::test_xfail_hygiene.py": MutationSpec(
        gate_id="structural::test_xfail_hygiene.py",
        target="tests/test_xfail_hygiene.py",
        detects="a bare @pytest.mark.xfail that would silently absorb a real regression (#2375)",
        plants=(("tests/_census_probe_2999.py", _XFAIL_PY),),
        track=False,
    ),
    "structural::test_secret_references.py": MutationSpec(
        gate_id="structural::test_secret_references.py",
        target="tests/test_secret_references.py",
        detects=(
            "a Lambda naming a secret that exists in neither KNOWN_SECRETS nor DELETED_SECRETS (R13-F04), "
            'written in the canonical `SECRET_NAME = os.environ.get("SECRET_NAME", ...)` default form — '
            "the March-2026 wrong-default shape the guard's own docstring cites, promoted from DARK_CONTROLS "
            "by #3255"
        ),
        plants=(("lambdas/common/_census_probe_2999.py", _MASKED_ID_PY),),
        track=False,
    ),
    "structural::test_no_hardcoded_feature_tier.py": MutationSpec(
        gate_id="structural::test_no_hardcoded_feature_tier.py",
        target="tests/test_no_hardcoded_feature_tier.py",
        detects="a feature gated on a hardcoded numeric budget tier instead of budget_guard.allow (#1255)",
        plants=(("lambdas/common/_census_probe_2999.py", _HARDCODED_TIER_PY),),
        track=False,
    ),
    "structural::test_lambda_size_gate.py": MutationSpec(
        gate_id="structural::test_lambda_size_gate.py",
        target="tests/test_lambda_size_gate.py",
        detects="a new *_lambda.py god module over the 2000-line ceiling with no grandfather entry",
        plants=(("lambdas/common/_census_probe_2999_lambda.py", _OVERSIZE_LAMBDA_PY),),
        track=False,
    ),
    "structural::test_no_dead_intelligence_functions.py": MutationSpec(
        gate_id="structural::test_no_dead_intelligence_functions.py",
        target="tests/test_no_dead_intelligence_functions.py",
        detects="a shipping module calling one of the deleted intelligence symbols (#1123 dead-reference guard)",
        plants=(("lambdas/common/_census_probe_2999.py", _DEAD_SYMBOL_PY),),
        track=False,
    ),
    "structural::test_docstring_secret_ids_2653.py": MutationSpec(
        gate_id="structural::test_docstring_secret_ids_2653.py",
        target="tests/test_docstring_secret_ids_2653.py",
        detects="a Lambda docstring presenting a Secrets Manager id no CDK role policy grants (#2653)",
        plants=(("lambdas/common/_census_probe_2999.py", _DEAD_ID_DOCSTRING_PY),),
        track=False,
    ),
    "structural::test_site_orphans.py": MutationSpec(
        gate_id="structural::test_site_orphans.py",
        target="tests/test_site_orphans.py",
        detects="a site/ page reachable by URL but linked from nowhere and not declared unlisted",
        plants=(("site/_census_probe_2999/index.html", _ORPHAN_PAGE_HTML),),
        track=False,
    ),
    "structural::test_absence_coverage_3294.py": MutationSpec(
        gate_id="structural::test_absence_coverage_3294.py",
        target="tests/test_absence_coverage_3294.py",
        detects="a NEW consumer of the raw channels_quiet list with no disposition — the unwired-surface class that published two false absences (#3294)",
        plants=(("lambdas/common/_census_probe_2999.py", _RAW_QUIET_READER_PY),),
        track=False,
    ),
    "structural::test_ci_dark_flag_sweep_3315.py": MutationSpec(
        gate_id="structural::test_ci_dark_flag_sweep_3315.py",
        target="tests/test_ci_dark_flag_sweep_3315.py",
        detects=(
            "a CI job invoking a script whose code path needs a package the job never installs — "
            "#2938's `⚠ unavailable` + exit 0 class, one workflow file away from the sweep's waivers (#3315)"
        ),
        plants=((".github/workflows/_census_probe_2999.yml", _DARK_FLAG_WORKFLOW_YML),),
        track=False,
    ),
    "structural::test_direction_of_travel_ruling_3293.py": MutationSpec(
        gate_id="structural::test_direction_of_travel_ruling_3293.py",
        target="tests/test_direction_of_travel_ruling_3293.py",
        detects=(
            "a NEW surface reaching for the direction-of-travel ruling without joining the registry that "
            "watches it — the shape that left three of the family unfixed after #3285 (#3293)"
        ),
        plants=(("lambdas/web/_census_probe_2999.py", _UNREGISTERED_DIRECTION_SURFACE_PY),),
        track=False,
    ),
    "structural::test_iam_twin_free_3336.py": MutationSpec(
        gate_id="structural::test_iam_twin_free_3336.py",
        target="tests/test_iam_twin_free_3336.py",
        detects=(
            "a deploy/ script embedding an IAM policy document for a role whose canonical document is a "
            "checked-in infra/iam/*.json — the hand-maintained twin that ran stale on 2026-08-30 (#3336)"
        ),
        plants=(("deploy/_census_probe_2999.sh", _IAM_TWIN_SH),),
        track=False,
    ),
    "structural::test_api_schema_completeness.py": MutationSpec(
        gate_id="structural::test_api_schema_completeness.py",
        target="tests/test_api_schema_completeness.py",
        detects=(
            "a hand-mutated baseline shape (a real captured snapshot with one key removed) still reading as "
            "breaking drift under the #3324 nullable-aware rule — the acceptance box's own can-it-fail proof, "
            "run against a captured FIXTURE (a copy of tests/api_schemas/api_vitals.json's real shape), never "
            "the live site"
        ),
        plants=(_drift_probe_plant(),),
        track=False,
    ),
    # #3559: a reader-input capture door minting its own key under generated/* — the exact
    # SEC-1 shape (a prefix the bucket policy grants anonymous GetObject on, records that
    # carry a reader's email). The guard sweeps lambdas/ on disk for every
    # put_capture_record(...) call site and requires the key to come from
    # web.site_api_capture_store.capture_key(). Untracked plant, filesystem walk.
    "structural::test_reader_input_prefix_3559.py": MutationSpec(
        gate_id="structural::test_reader_input_prefix_3559.py",
        target="tests/test_reader_input_prefix_3559.py",
        detects="a reader-input door writing its moderation record under the anonymously readable generated/* prefix (#3559, SEC-1)",
        plants=(("lambdas/web/_census_probe_3559.py", _PUBLIC_PREFIX_DOOR_PY),),
        track=False,
    ),
    # #3731: `tests/repo_scan_cache.py` gained a disk-backed, tree-state-keyed cross-
    # PROCESS layer this PR. These four call sites — three real `run_repo_scan()`
    # readers of `scripts/check_doc_facts.py`/`check_doc_index.py`, plus the cache's
    # OWN test suite's one real (unfaked) call site, `test_g` — are the newly-discovered
    # `structural::` gates: `repo_scan_cache.py` now matches `premerge_derivation.py`'s
    # `_SWEEP_PATTERN` (it calls `os.walk` to fingerprint the tree) for the first time,
    # so every test file that imports it is newly classified as a tree-sweeping gate.
    # That reclassification is CORRECT — the cache genuinely sweeps the tree now — and
    # each of the four needed a real proof rather than sitting unproven.
    "structural::test_doc_facts_ops_1957.py": MutationSpec(
        gate_id="structural::test_doc_facts_ops_1957.py",
        target="tests/test_doc_facts_ops_1957.py",
        detects=(
            "a new docs/*.md page with a wildly-wrong CloudWatch alarm-count claim, read THROUGH "
            "tests/repo_scan_cache.py's disk-backed cache (#3731) rather than caught before it — proves the "
            "cache's tree-state key changes when the plant lands, so a real defect is never served stale"
        ),
        plants=(("docs/_census_probe_3731.md", _DOC_FACTS_INDEX_PROBE_MD),),
        track=False,
    ),
    "structural::test_doc_facts_ops_2003.py": MutationSpec(
        gate_id="structural::test_doc_facts_ops_2003.py",
        target="tests/test_doc_facts_ops_2003.py",
        detects=(
            "the same plant as test_doc_facts_ops_1957.py's gate, at the SECOND of three call sites that "
            "used to share one in-process memo and now also share the disk layer — the shape #3224 fixed "
            "in-process, #3731 fixed cross-process, and this spec proves the second layer still catches"
        ),
        plants=(("docs/_census_probe_3731.md", _DOC_FACTS_INDEX_PROBE_MD),),
        track=False,
    ),
    "structural::test_wiki_checkers.py": MutationSpec(
        gate_id="structural::test_wiki_checkers.py",
        target="tests/test_wiki_checkers.py",
        detects=(
            "the same plant, at the third and last plain-key call site of the family — the one #3224's own "
            "docstring named as the test that regressed to 21.59s when the cache's own fixture once cleared "
            "the shared table by mistake; this proves it still catches the defect it exists to share, not "
            "just that it is fast"
        ),
        plants=(("docs/_census_probe_3731.md", _DOC_FACTS_INDEX_PROBE_MD),),
        track=False,
    ),
    "structural::test_repo_scan_cache_3224.py": MutationSpec(
        gate_id="structural::test_repo_scan_cache_3224.py",
        target="tests/test_repo_scan_cache_3224.py",
        detects=(
            "the cache module's OWN test suite has exactly one call site that runs a REAL, unfaked scan "
            "against the real tree (`test_g`, of scripts/check_doc_index.py) — every other test in this file "
            "fakes subprocess.run. The same plant breaks check_doc_index.py's wiki-coverage/header scan too "
            "(missing from docs/README.md's index, no status header), so test_g reds through the identical "
            "disk-cache path the other three specs exercise via check_doc_facts.py"
        ),
        plants=(("docs/_census_probe_3731.md", _DOC_FACTS_INDEX_PROBE_MD),),
        track=False,
    ),
}


# The negative controls: plants that DO sit in a gate's declared scope and still leave it
# green. Each one is a measured blind spot, not a spare spec — `run_spec` is expected to
# return DARK, and `tests/test_gate_census_mutations_2999.py` fails if one starts passing
# (a silently-widened gate is as much a change of meaning as a silently-narrowed one).
DARK_CONTROLS: dict[str, MutationSpec] = {
    "structural::test_secret_references.py::assembled-id": MutationSpec(
        gate_id="structural::test_secret_references.py",
        target="tests/test_secret_references.py",
        detects=(
            "the SAME unknown secret name as the armed spec, assembled at runtime from two constants "
            '(`_PREFIX + "probe-..."`) instead of written as one literal. The scanner reads string '
            "CONSTANTS out of the AST, and neither half is a whole secret name, so a Lambda that builds "
            "its secret id by concatenation or f-string interpolation is audited by nothing. Measured "
            "2026-08-27, and it is the SUCCESSOR to the masked-line blind spot #3255 closed — that one is "
            "now the armed spec above."
        ),
        plants=(("lambdas/common/_census_probe_2999.py", _SPLIT_ID_PY),),
        track=False,
    ),
}


# ─────────────────────────────────────────────────────────────────────────────
# The recorded verdicts, in `gate_census.Proof`'s shape (gate_census constructs the
# frozen dataclass from these dicts — same import contract as SENTINEL_PROOFS).
#
# Every `observed` below is the harness's own transcript from the run of 2026-08-27,
# copied verbatim, not paraphrased. Re-derive the whole batch with:
#     python3 scripts/gate_census_mutations.py --run
# ─────────────────────────────────────────────────────────────────────────────

_PROVED_ON = "2026-08-27"


def _command(target: str) -> str:
    return f"python3 scripts/gate_census_mutations.py --run --gate {Path(target).name}"


def _proof(gate_id: str, observed: str, scope: str, proved_on: str = _PROVED_ON) -> dict[str, Any]:
    # `proved_on` is per record: a gate re-measured after the batch (because its
    # predicates changed) carries the date it was actually watched, not the batch's.
    spec = MUTATION_SPECS[gate_id]
    return {
        "gate_name": Path(spec.target).name,
        "command": _command(spec.target),
        "mutation": spec.detects
        + f" — planted as {', '.join(rel for rel, _ in spec.plants)}"
        + (", git-added (the gate reads the tracked set)" if spec.track else ", untracked (the gate walks the filesystem)"),
        "observed": observed,
        "scope": scope,
        "proved_on": proved_on,
    }


STRUCTURAL_PROOFS: dict[str, dict[str, Any]] = {
    "structural::test_gsi_set_premerge_3609.py": _proof(
        "structural::test_gsi_set_premerge_3609.py",
        "baseline: 7 passed in 4.54s | mutated: 1 failed, 6 passed in 5.24s :: "
        "test_every_indexname_literal_on_the_live_surface_is_sanctioned | reverted: 7 passed in 5.26s",
        "lambdas/ + mcp/ on disk (os.walk, .py only) for literal IndexName= references and "
        "reading_keys.py's GSI*_NAME constants, plus a text sweep of "
        "deploy/deploy_reading_gsis.sh's add_gsi call list — the only mechanism that can "
        "actually create a GSI on the out-of-CDK `life-platform` table (its own header says "
        "why: `dynamodb.Table.from_table_name` in core_stack.py is read-only). An UNTRACKED "
        "module is in scope (os.walk, not git ls-files). Two of the three legs (the literal "
        "scan, the deploy-script scan) are separately mutation-proven in-file by "
        "test_planted_indexname_literal_is_caught / test_planted_add_gsi_call_is_caught, "
        "run every collection; this harness run proves the THIRD leg end-to-end against the "
        "real tracked tree — an untracked lambdas/ module naming an unsanctioned GSI in a "
        "live boto3 call, which the in-file controls (which parse hand-typed source strings, "
        "not a planted file) do not reach. STILL INVISIBLE, stated rather than papered over: "
        "an IndexName built from a variable/f-string rather than a literal, and a GSI name "
        "reused for a table this gate does not know about.",
        proved_on="2026-09-20",
    ),
    "structural::test_grounding_sets_3614.py": _proof(
        "structural::test_grounding_sets_3614.py",
        "M1 (harness, ARMED 1/1) baseline: 27 passed in 15.14s | mutated: 3 failed, 24 passed in 16.59s :: test_every_prompt_builder_with_its_own_phase_prose_is_decided; test_the_census_finds_the_modules_it_is_supposed_to_find; test_planting_a_fourth_hand_typed_phase_line_reds_the_census | reverted: 27 passed in 14.43s. Three tests red on one plant is the census working in all three of its directions: the live verdict, the member/decision key-parity check, and the in-file control's own 'the real tree is still clean' tail. M2, the OTHER box, hand-run on the real registry 2026-09-18 and not mechanisable as a file plant because the mutation is a DECLARATION: flipping lambdas/web/site_api_ai_lambda.py::_handle_explain from fail_closed to keep_best in tests/grounding_wiring.py (diff against a pre-mutation copy: one line, FAIL_CLOSED -> KEEP_BEST) gave 2 failed, 25 passed -- test_the_public_keep_best_residual_is_pinned_by_name ('the public keep-best residual moved ... Extra items in the left set: _handle_explain') AND test_every_surface_carries_the_facets_and_the_tree_agrees ('declared keep_best, but _handle_explain BRANCHES on grounding_findings and drops/falls back -- the declaration and the call site disagree'). Reverted byte-for-byte, 27 passed. The same flip runs on every build against a deepcopy of the registry (test_flipping_one_public_surface_to_keep_best_reds_the_facets), plus its inverse, which is the assertion that matters most here: the AST derivation reads acts=False on 4 of the 32 surfaces, so it is not a constant-true detector.",
        "tests/test_grounding_sets_3614.py carries BOTH #3614 sets. The phase census walks lambdas/ on disk (os.walk, .py only), so an untracked door is in scope and tests/ deliberately is not -- this file and tests/phase_prompt_census.py both contain the literal words the scan looks for, and test_the_census_is_not_a_member_of_its_own_set MEASURES their non-membership rather than assuming it. Membership needs BOTH halves (a request-shaped dict literal AND non-docstring phase prose), which is what keeps a module that merely READS day_n/EXPERIMENT_START_DATE out: measured 3 members on 2026-09-18. STILL INVISIBLE, stated rather than papered over: a phase claim assembled from fragments at runtime, or one that reaches the prompt from S3/DDB rather than from a literal, is not prose this scan can see; and on the facet side the AST proves the DISPOSITION only -- it does not follow the findings value across a Lambda wire into the disposing function (coach_quality_gate) and has nothing to read at all for the two post-hoc auditors, which is why those two carry the auditor sentinel and a written reason instead of a call site.",
        proved_on="2026-09-18",
    ),
    "structural::test_judge_verdict_retry_3688.py": _proof(
        "structural::test_judge_verdict_retry_3688.py",
        "M1 (harness, ARMED 1/1) baseline: 32 passed | mutated: 1 failed, 31 passed :: test_the_judge_call_site_set_is_enumerated_from_source_and_every_member_is_covered | reverted: 32 passed. M2 the same probe under mcp/ and M2b a SUBSCRIPT-form probe under scripts/: 1 failed each (the scan reaches all five dirs, and the subscript form is the one the FIRST DRAFT of the pattern missed). M3/M3b negative controls \u2014 the identical idiom as a leading and as a trailing comment: 32 passed, no cry-wolf. M4b the covered site in tests/visual_ai_qa.py stops deciding on truncation at all: 3 failed \u2014 the Set test naming the file, plus two behavioural tests. All watched 2026-09-14 and restored.",
        "lambdas/ mcp/ scripts/ deploy/ cdk/ on disk (os.walk, .py only) plus tests/visual_ai_qa.py, tests/visual_qa.py and tests/visual_qa_verdict.py by name, so an UNTRACKED judge is in scope and the rest of tests/ deliberately is not \u2014 its stop-reason literals are FIXTURES implementing the wire, not decisions on it. THE PATTERN WAS WIDENED BY THIS MUTATION RUN and that is the record's most useful line: the first draft matched only the get-and-equality form, and mutation M4 \u2014 rewriting the covered site to the membership form, semantically identical code \u2014 went RED as a phantom new site while the real judge was still there. The rule now requires the two names on one line with a comparison between them and strips trailing comments first; re-measured over the whole scan surface it returns the SAME three sites with no new false positives, and M4 now correctly passes. STILL INVISIBLE, stated rather than papered over: a two-line form (bind the stop reason, compare it on the next line), a helper that returns it, and a parse failure reached without reading it at all \u2014 gaps, not passes, which is why the two covered sites ALSO carry behavioural tests. It judges SOURCE SHAPE, never the live gate: whether the next Visual QA (standalone) run actually retries is an observation no offline gate can make (#3688 closes on that run, not on this test).",
        proved_on="2026-09-14",
    ),
    "structural::test_role_family_write_scope.py": _proof(
        "structural::test_role_family_write_scope.py",
        "baseline: 18 passed | mutated: 1 failed, 17 passed :: test_every_ddb_writing_entrypoint_is_enrolled_in_the_family | reverted: 18 passed",
        "lambdas/ on disk (os.walk, .py only), so an UNTRACKED entrypoint is in scope, and "
        "cdk/stacks/*_stack.py + cdk/stacks/role_policies*.py by AST — the role<->module mapping is read "
        "from the create_platform_lambda construction site, never hand-listed. In scope: the entrypoint "
        "module a stack names, its DynamoDB write verbs, and any pk statically resolvable from a literal, "
        "an f-string or a local bound to one. OUT of scope, stated and asserted: 48 SHARED modules that "
        "write under whichever role imports them; a pk built from data (reported as unresolvable, never as "
        "covered); and whether the deployed role matches the checked-in document, which is the "
        "@integration live leg and skips loudly without credentials.",
        proved_on="2026-09-06",
    ),
    "structural::test_email_sender_identity_3568.py": _proof(
        "structural::test_email_sender_identity_3568.py",
        "baseline: 9 passed | mutated: 1 failed, 8 passed :: test_every_code_default_is_on_a_verified_domain | reverted: 9 passed",
        "lambdas/ on disk (.rglob, .py only) for code defaults and cdk/stacks/*.py for CDK literals, so an "
        "UNTRACKED sender is in scope and deploy/archive/ deliberately is not — its senders are dead code kept "
        'for history. It reads the AST for two shapes: `os.environ.get("EMAIL_SENDER", <default>)` and a bare '
        '`SENDER = "..."`; a module that builds its From address any other way (an f-string, a helper call, a '
        "value read from SSM at runtime) is invisible to it — those are gaps, not passes. It judges the SOURCE "
        "against a COMMITTED list of verified domains, never SES itself: whether an identity is still verified "
        "in the account is a live fact no offline gate can assert, so the list is re-derived by the "
        "list-email-identities command recorded in lambdas/common/email_identity.py. The reader-facing "
        "assertions additionally pin the From to the site domain, which is the half that would still red if "
        "every domain in the set were verified but reader mail drifted back to the personal one.",
        proved_on="2026-09-06",
    ),
    "structural::test_composite_alarm_lookup_3390.py": _proof(
        "structural::test_composite_alarm_lookup_3390.py",
        "baseline: 11 passed | mutated: 1 failed, 10 passed :: test_every_alarm_read_states_its_alarm_types | reverted: 11 passed",
        "remediation/ scripts/ lambdas/ deploy/ cdk/ mcp/ on disk (os.walk, .py only), so an UNTRACKED "
        "caller is in scope and `tests/` deliberately is not — its describe_alarms definitions are FAKES "
        "implementing the wire, not callers of it. The rule reads the AST: an alarm read counts as covered "
        "when `AlarmTypes` reaches the call, following a `**kw` spread into dict literals and "
        '`kw["AlarmTypes"] = ...` assignments in the same module. A caller that builds its kwargs '
        "somewhere this resolver cannot follow (a helper function, a dict returned by another call) is "
        "invisible to it — the resolver covers the six shapes the repo actually uses, and a new shape is a "
        "gap, not a pass. It judges the CALL, never the live response: whether AWS actually returns a "
        "composite is an API behaviour no offline gate can assert.",
        proved_on="2026-09-05",
    ),
    "structural::test_iam_twin_free_3336.py": _proof(
        "structural::test_iam_twin_free_3336.py",
        "baseline: 16 passed | mutated: 1 failed, 15 passed :: test_no_deploy_script_embeds_a_policy_document_for_a_governed_role | reverted: 16 passed",
        "deploy/ on disk (rglob, .sh + .py), so an UNTRACKED twin is in scope. A document counts only when "
        'it carries the `"Version": "2012-10-17"` literal AND a Statement AND an Effect AND names a role '
        "that has an infra/iam/<role>.*.json — a twin for an ungoverned Lambda exec role, a policy the "
        "script merely READS, or a document assembled from variables without the version literal is "
        "invisible. A twin outside deploy/ (scripts/, cdk/) is out of scope by design: the verifier's ROLES "
        "set is the governed set and deploy/ is the only apply surface.",
        proved_on="2026-08-31",
    ),
    "structural::test_no_conflict_markers.py": _proof(
        "structural::test_no_conflict_markers.py",
        "baseline: 6 passed | mutated: 1 failed, 5 passed :: test_no_unresolved_conflict_markers_in_tracked_files | reverted: 6 passed",
        "Tracked files ONLY, and 26 binary suffixes are skipped. `=======` counts solely on a line of "
        "its own and the other two markers require a trailing space, so a hand-mangled marker "
        "(`<<<<<<<HEAD`, no space) is invisible. An unresolved conflict in the WORKING TREE is out of "
        "scope by design — this guard exists to stop one reaching main, not to police a local rebase.",
    ),
    "structural::test_root_clutter_guard.py": _proof(
        "structural::test_root_clutter_guard.py",
        "baseline: 4 passed | mutated: 1 failed, 3 passed :: test_no_unlisted_top_level_dir | reverted: 4 passed",
        "Directories only, and only via a tracked file inside one — a new tracked FILE at the repo root "
        "is not covered by this gate at all. Subset semantics, deliberately (#1652): deleting a "
        "top-level dir never reds it, so a stale ALLOWLIST entry is a hygiene item, not a failure.",
    ),
    "structural::test_no_private_markers_3043.py": _proof(
        "structural::test_no_private_markers_3043.py",
        "baseline: 3 passed | mutated: 1 failed, 2 passed :: test_no_tracked_file_carries_private_marker | reverted: 3 passed",
        "Two header FORMS only (`**Status:**`/`**Privacy tier:**` bolded, or the same two unbolded at "
        "line start) and `PRIVATE` is case-sensitive. A file that IS owner-private but does not say so "
        "in that exact header shape is not detected — this gate catches the self-declaration, never the "
        "sensitivity. Tracked text suffixes only.",
    ),
    "structural::test_no_tool_attribution_3005.py": _proof(
        "structural::test_no_tool_attribution_3005.py",
        "baseline: 8 passed, 1 skipped | mutated: 1 failed, 7 passed, 1 skipped :: test_no_tracked_file_instructs_the_trailer | reverted: 8 passed, 1 skipped",
        "ALL THREE of the owner decision's banned forms since #3328 (it shipped matching one, recorded "
        "here as a scope gap on 2026-08-27): the co-author trailer, the session-link line, AND the "
        "generated-with PR footer / session link. `_MENTION` sweeps the tracked surface for any mention "
        "of the three; `_TRAILER` sweeps reachable history since the ban date for the actual forms — "
        "including the footer, because a bare `gh pr merge --squash` can copy a PR body into the squash "
        "commit; and a PR-body sweep reads `pull_request.body` from $GITHUB_EVENT_PATH on `pull_request` "
        "runs (both pr-checks.yml jobs) and SKIPS with a stated reason everywhere else, never a silent "
        "pass. One independent predicate proof per form lives in the gate itself; this census plant "
        "exercises form 1 on the tracked surface. Residual limits: a PR body EDITED after its last push "
        "is not re-read until the next push (`edited` is not a default pull_request activity), and the "
        "session link is pinned to `/code/session` so `claude.ai/code/artifact/…` contact-sheet links "
        "under config/portraits/ stay legal.",
        proved_on="2026-08-30",
    ),
    "structural::test_timezone_discipline.py": _proof(
        "structural::test_timezone_discipline.py",
        "baseline: 1 passed | mutated: 1 failed :: test_no_fixed_offset_or_naive_mixed_pacific_math | reverted: 1 passed",
        "Two regexes, and only for offsets of 7 or 8 hours — the DST-pinning constants. It is a "
        "line-level grep, so any line containing `tzinfo` or `.date()` is exempted wholesale by "
        "LINE_EXEMPT_SUBSTRINGS, and a fixed offset assembled over two lines is invisible. Scans "
        "lambdas/ mcp/ deploy/ scripts/ remediation/ — cdk/ and tests/ are not swept.",
    ),
    "structural::test_time_invariant_helpers_1964.py": _proof(
        "structural::test_time_invariant_helpers_1964.py",
        "baseline: 19 passed | mutated: 1 failed, 18 passed :: test_no_pacific_frame_derived_outside_the_canonical_helper | reverted: 19 passed",
        "SCAN_ROOTS is lambdas/ + mcp/ (what ships in a bundle) — a Pacific fork in deploy/, scripts/ or "
        "cdk/ is out of scope. A RESIDUE allowlist of already-known sites is carried and is checked for "
        "rot by a sibling test, so the ratchet tightens rather than absorbing.",
    ),
    "structural::test_pii_log_guard_2369.py": _proof(
        "structural::test_pii_log_guard_2369.py",
        "baseline: 8 passed | mutated: 1 failed, 7 passed :: test_no_raw_pii_in_logging_calls | reverted: 8 passed",
        "Detection is by IDENTIFIER NAME at the log call site (an interpolated `email`/`dob`/`phone`), "
        "so the same value carried in a differently-named variable logs clean. lambdas/ + mcp/ only.",
    ),
    "structural::test_handler_type_hints.py": _proof(
        "structural::test_handler_type_hints.py",
        "baseline: 2 passed | mutated: 1 failed, 1 passed :: test_untyped_handler_count_at_or_below_baseline | reverted: 2 passed",
        "A COUNT ratchet with TOLERANCE=2, not a per-file rule — it can only fail when the total crosses "
        "BASELINE_UNTYPED + TOLERANCE, so new untyped handlers are absorbed silently until it does. "
        "MEASURED 2026-08-27: 68 untyped against a baseline of 66 + tolerance 2, i.e. headroom exactly "
        "ZERO. That is why the plant reds today and why it would NOT have redded at any point while the "
        "tolerance was unspent — the same absorption the file's own 2026-07-08 comment records happening "
        "once already. The green here means 'the count has not grown', never 'handlers are typed'.",
    ),
    "structural::test_xfail_hygiene.py": _proof(
        "structural::test_xfail_hygiene.py",
        "baseline: 1 passed | mutated: 1 failed :: test_every_xfail_marker_is_strict_or_names_its_nondeterminism | reverted: 1 passed",
        "tests/ only, and it rules on the MARKER's shape (bare / no literal `strict=` / `strict=False` "
        "without the nondeterminism tag). It never asks whether a `strict=True` xfail is still failing "
        "for the reason it claims — that is pytest's job, not this gate's.",
    ),
    "structural::test_secret_references.py": _proof(
        "structural::test_secret_references.py",
        "baseline: 7 passed | mutated: 1 failed, 6 passed :: test_sr1_all_secret_references_are_known | reverted: 7 passed",
        "The plant is now the guard's own stated origin shape — the wrong-default line "
        '`SECRET_NAME = os.environ.get("SECRET_NAME", "life-platform/todoits")` — and it REDS, which it '
        "did not before #3255 (2026-08-27). Until then FALSE_POSITIVE_PATTERNS dropped any LINE "
        "containing `SECRET_NAME` (and five sibling identifiers), masking 38 secret-literal lines "
        "against 33 that reached SR1 and leaving four real ids audited by nothing (google-tts x2, "
        "hevy-write, ritual-token-secret x2, site-api-origin-secret — all four provisioned in AWS, all "
        "four already in the IAM-layer registry, so the drift was in this gate alone). Extraction is now "
        "`ast.Constant` full-match: 0 suppressed, 69 references audited. SCOPE, and the SUCCESSOR BLIND "
        "SPOT: only a WHOLE secret-name literal is a reference, so an id assembled by concatenation or "
        "f-string interpolation is invisible — measured DARK 2026-08-27 and carried as this module's "
        "`::assembled-id` control. Comments, docstring mentions and prose are out of scope by design "
        "(docstring ids are tests/test_docstring_secret_ids_2653.py's gate). SR3 is a residual invariant "
        "on the extractor, NOT a near-miss-prefix typo detector: the only near-miss in the tree is the "
        "`LifePlatform/AI` EMF namespace at 67 sites, so closing that would take the suppression list "
        "#3255 just removed. Scans lambdas/ + mcp/ + mcp_server.py only.",
    ),
    "structural::test_no_hardcoded_feature_tier.py": _proof(
        "structural::test_no_hardcoded_feature_tier.py",
        "baseline: 3 passed | mutated: 1 failed, 2 passed :: test_no_lambda_hardcodes_a_soft_feature_tier_comparison | reverted: 3 passed",
        "Only a comparison whose operand is a zero-arg `current_tier()` call, and only for SOFT bands "
        "(the hard-stop tier is read from budget_guard so the gate moves with it). A module that copies "
        "the tier into a local first, or reads the SSM parameter directly, is not this gate's shape. "
        "budget_guard.py and bedrock_client.py are allowlisted by design.",
    ),
    "structural::test_lambda_size_gate.py": _proof(
        "structural::test_lambda_size_gate.py",
        "baseline: 3 passed | mutated: 1 failed, 2 passed :: test_no_new_lambda_god_modules | reverted: 3 passed",
        "`*_lambda.py` filenames ONLY, over 2000 lines, outside GRANDFATHERED. A 5,000-line shared "
        "module that is not named `*_lambda.py` is invisible here — it is `tests/test_module_size_guard.py`'s "
        "1200-line ceiling that covers that case, and the two guards are not substitutes (both are named "
        "in the two-module-size-guard rule).",
    ),
    "structural::test_no_dead_intelligence_functions.py": _proof(
        "structural::test_no_dead_intelligence_functions.py",
        "baseline: 2 passed | mutated: 1 failed, 1 passed :: test_no_live_module_references_deleted_symbols | reverted: 2 passed",
        "A CLOSED hand-list of eight deleted symbol names — this gate catches references to those eight "
        "and nothing else; the ninth deletion is uncovered until someone adds it. Matching is by bare "
        "attribute/name, so an unrelated method that happens to share a name would false-positive. "
        "Carries no population floor: if the lambdas/+mcp/ walk ever returned nothing, both assertions "
        "would pass green (adjudicated a TRUE POSITIVE in this PR's `vacuous-empty` re-sample).",
    ),
    "structural::test_docstring_secret_ids_2653.py": _proof(
        "structural::test_docstring_secret_ids_2653.py",
        "baseline: 11 passed, 1 skipped | mutated: 1 failed, 10 passed, 1 skipped :: test_no_docstring_names_a_secret_no_role_grants | reverted: 11 passed, 1 skipped",
        "MODULE docstrings only (`ast.get_docstring` on the module node) — a stale secret id in a "
        "function or class docstring, in a comment, or in code is out of scope. The line must also read "
        "as secret-ish, and a disclaimer within 110 chars AFTER the id clears it. Truth set is the CDK "
        "role grants, not Secrets Manager, so an id that is granted but does not exist still passes.",
    ),
    "structural::test_site_orphans.py": _proof(
        "structural::test_site_orphans.py",
        "baseline: 3 passed | mutated: 1 failed, 2 passed :: test_every_page_is_linked_or_explicitly_unlisted | reverted: 3 passed",
        'Reachability is a TEXT search for the URL in site/ HTML hrefs plus `"/dir/"` literals in '
        "site/assets/js — a page linked only through a computed path is 'orphaned' to this gate, and a "
        "page linked only from a dead page still counts as linked (there is no transitive walk from the "
        "home page). site/legacy/** is excluded on purpose (#1237).",
    ),
    "structural::test_absence_coverage_3294.py": dict(
        _proof(
            "structural::test_absence_coverage_3294.py",
            "baseline: 20 passed | mutated: 1 failed, 19 passed :: "
            "TestCoverageEnumeration::test_every_reader_has_a_disposition | reverted: 20 passed",
            "The enumeration is keyed on the FIELD NAME `channels_quiet` as an AST string constant in "
            "lambdas/ + mcp/ — a consumer that receives the list through an intermediary variable or a "
            "**kwargs projection never names the field and is invisible to it. Absence claims built from "
            "OTHER raw fields (channel_detail arithmetic, per-source gap_days) are out of this gate's "
            "scope; the licensing check itself adjudicates only what flows through sourced_quiet. The "
            "wire-replay half of the file (the four-absences artifact, the lift-glyph labels) was "
            "separately watched failing behaviourally against pre-fix main 2026-08-29: all three wired "
            "surfaces published all four labels, `NOTHING has been logged` included.",
        ),
        proved_on="2026-08-29",
    ),
    "structural::test_ci_dark_flag_sweep_3315.py": dict(
        _proof(
            "structural::test_ci_dark_flag_sweep_3315.py",
            "baseline: 13 passed | mutated: 1 failed, 12 passed :: "
            "test_no_ci_step_reaches_a_dependency_its_job_never_installs | reverted: 13 passed",
            "The gate compares each job's DECLARED install set (ci_pins.py arguments, `pip install -r`/literal, "
            "`playwright install <browser>`; a job with no setup-python is modelled as nothing installed) against "
            "the transitive repo-local import closure of every script its steps reach — through `bash deploy/*.sh`, "
            "heredocs and `-c` one-liners included — so a reach behind a flag the job never passes is a waiver with a "
            "reason, keyed by job+script+dist and live-checked (a vanished reach reds as STALE WAIVER). The mutated run "
            "reds on the planted probe's Pillow reach; the same detector pointed at copies of origin/main's workflows "
            "(`--workflows-dir`) reported the 22 violations #3315 fixed. NOT covered: what pytest-collected tests import "
            "(test_deploy_critical_lane_imports_2758 owns module scope; a lazy import inside a test body is outside both); "
            "a dependency that is present while its IAM permission is absent (site-deploy's theme-river DynamoDB read "
            "fails AccessDenied with boto3 installed — a different class, named on the PR); runner-image tools "
            "(aws/gh/jq/node/curl) are assumed present. A script the resolver cannot see surfaces as UNRESOLVED, which "
            "is itself a violation, never a pass.",
        ),
        proved_on="2026-08-30",
    ),
    "structural::test_direction_of_travel_ruling_3293.py": dict(
        _proof(
            "structural::test_direction_of_travel_ruling_3293.py",
            "baseline: 33 passed | mutated: 1 failed, 32 passed :: "
            "test_the_registry_covers_every_module_that_imports_the_ruling | reverted: 33 passed",
            "SCOPED BY DESIGN, and the limit is stated in the guard file itself. The registry watches a "
            "hand-listed FIVE surfaces plus a staleness sweep for modules that name `journey_direction` "
            "in lambdas/ + scripts/ + mcp/. A brand-new surface that states a direction of travel WITHOUT "
            "touching the shared ruling — the exact shape of both #3293 defects — is invisible to it; "
            "catching that needs a direction-word lexicon, which is phrase-matching, and "
            "site_api_pulse.py already contains a CORRECT static 'up' next to a formatted number that "
            "such a scan would flag on day one. What this gate does cover is regression: any of the five "
            "ceasing to route through classify_delta. The behavioural half of the file (the recap card's "
            "three surfaces, the served /api/pulse payload) was separately watched failing against "
            "pre-fix main 2026-08-30: 24 failed / 9 passed, including the filed `direction: 'up'` with a "
            "null weigh-in and the `-5.2 lbs down` unfurl.",
        ),
        proved_on="2026-08-30",
    ),
    "structural::test_api_schema_completeness.py": _proof(
        "structural::test_api_schema_completeness.py",
        "baseline: 32 passed in 0.18s | mutated: 1 failed, 31 passed in 0.21s :: "
        "tests/test_api_schema_completeness.py::test_hand_mutated_baseline_reds_on_a_removed_key | "
        "reverted: 32 passed in 0.19s",
        "The proof runs offline against a captured FIXTURE (a copy of tests/api_schemas/api_vitals.json's "
        "real shape with one key hand-removed), never the live site — this suite has no network dependency "
        "by design. It covers exactly the #3324 nullable-aware `diff_shape()` rule: a genuine key removal "
        "still reads as breaking after the null|<type> absorption. NOT covered by this proof: the live "
        "`--check-drift` code path itself (the HTTP fetch, the sentinel leak scan, the exemptions-ledger "
        "merge) — those run only against the real site and are exercised by the unit tests in "
        "tests/test_api_schema_completeness.py's TestDiffShape/TestJsonShape classes and the "
        "scan_json_value_leaks tests, not by this mutation.",
        proved_on="2026-08-31",
    ),
    "structural::test_reader_input_prefix_3559.py": _proof(
        "structural::test_reader_input_prefix_3559.py",
        "baseline: 11 passed | mutated: 1 failed, 10 passed :: test_every_capture_door_in_lambdas_keys_through_the_seam | reverted: 11 passed",
        "lambdas/ on disk (os.walk, .py only), so an UNTRACKED door is in scope. The sweep keys on the literal call "
        "name `put_capture_record(` and resolves the key argument one hop: a `capture_key(...)` call, or a name bound "
        "to one in the same function body. A door that reaches the key through a helper the resolver cannot follow, "
        "or that writes reader input with a bare `put_object` instead of the capture-store seam, is invisible to "
        "THIS sweep (the e2e write-path test's `(c) S3 writes` assertion is the second net for the live doors). The "
        "public-read set is derived from deploy/bucket_policy.json, so the guard is only as current as that file — "
        "drift_sentinel.check_bucket_policy holds the live policy to it. It judges the KEY, never the object: whether "
        "an object already sitting under generated/ is readable is the owner's migration, not this gate's.",
        proved_on="2026-09-05",
    ),
    # #3731: newly-discovered gates (see the MUTATION_SPECS comment above these four).
    # `target` is the WHOLE FILE, matching every other record in this dict — `_proof()`
    # derives `gate_name` from `Path(spec.target).name`, and that has to equal the live
    # gate's bare filename or tests/test_gate_census_2578.py::
    # test_no_recorded_proof_is_stale_against_the_live_census reds on an "orphan proof"
    # (a first, narrower `::test_name` cut of these four records was caught by exactly
    # that check and replaced with this one — the census proving its own consistency
    # rule on its own author, same as #3231's fixture incident cited elsewhere in this
    # file). All four run 2026-09-19, `docs/_census_probe_3731.md` planted once per spec
    # (harness runs specs sequentially, reverting between each).
    "structural::test_doc_facts_ops_1957.py": _proof(
        "structural::test_doc_facts_ops_1957.py",
        "baseline: 28 passed in 62.24s (0:01:02) | mutated: 2 failed, 26 passed in 62.57s (0:01:02) :: "
        "tests/test_doc_facts_ops_1957.py::test_alarm_count_clean_on_real_docs; "
        "tests/test_doc_facts_ops_1957.py::test_gate_passes_on_the_repo | reverted: 28 passed in 12.20s",
        "Covers the whole file: 27 pre-existing tests over synthetic scratch fixtures (unaffected by the "
        "plant, still passing mutated) plus `test_gate_passes_on_the_repo`'s real-tree assertion, now read "
        "through `tests/repo_scan_cache.py`'s disk-backed cache instead of a bare subprocess.run. The plant "
        "ALSO reds `test_alarm_count_clean_on_real_docs` (a second, independent real-tree assertion in this "
        "file, not cache-mediated) — two tests failing on one plant is the file's OWN real-tree coverage "
        "working from two directions, not a scope leak. Does NOT cover the cache's OWN correctness in "
        "isolation (key composition, atomicity, the `disk_dir=None` isolation contract) — that is "
        "tests/test_repo_scan_cache_3224.py's job, proven separately below.",
        proved_on="2026-09-19",
    ),
    "structural::test_doc_facts_ops_2003.py": _proof(
        "structural::test_doc_facts_ops_2003.py",
        "baseline: 15 passed in 1.00s | mutated: 1 failed, 14 passed in 51.42s :: "
        "tests/test_doc_facts_ops_2003.py::test_gate_passes_on_the_repo | reverted: 15 passed in 0.98s",
        "Same scope as test_doc_facts_ops_1957.py's record above — this is the SECOND of the three "
        "plain-key call sites, run as a SEPARATE OS process from the first (the harness spawns one "
        "`python3 -m pytest` per spec). Its 1.00s baseline is the cross-process disk hit measured live: the "
        "first spec's baseline process had already written the clean-tree answer moments earlier, and this "
        "process — no Python object in common with that one — read it from disk instead of re-spawning. The "
        "mutated run pays the full ~51s: the plant changes `_tree_fingerprint()`'s value, so the pre-plant "
        "disk answer is never served stale.",
        proved_on="2026-09-19",
    ),
    "structural::test_wiki_checkers.py": _proof(
        "structural::test_wiki_checkers.py",
        "baseline: 46 passed in 82.20s (0:01:22) | mutated: 3 failed, 43 passed in 130.55s (0:02:10) :: "
        "tests/test_wiki_checkers.py::test_wiki_index_coverage_and_headers; "
        "tests/test_wiki_checkers.py::test_doc_facts_clean; "
        "tests/test_wiki_checkers.py::test_verified_advisory_is_warn_only | reverted: 46 passed in 31.53s",
        "Covers the whole file, including BOTH `run_repo_scan` call sites this file owns: the plain-key "
        "reader (`test_doc_facts_clean`, the third and last plain-key `check_doc_facts.py` reader after the "
        "two records above) AND the distinct-env advisory reader (`test_verified_advisory_is_warn_only`, "
        "CHECK_DOC_FACTS_TODAY=2036-01-01) — proving the disk cache's per-env key separation holds for a "
        "REAL plant, not just the synthetic env-override check in tests/test_repo_scan_cache_3224.py::test_b. "
        "`test_wiki_index_coverage_and_headers` also reds independently — the plant is simultaneously a "
        "`check_doc_index.py` coverage/header violation (docs/_census_probe_3731.md not in the wiki index, "
        "no status header), which that test asserts directly, uncached. Does not re-prove the other 43 "
        "tests in this file, none of which read the real tree.",
        proved_on="2026-09-19",
    ),
    "structural::test_repo_scan_cache_3224.py": _proof(
        "structural::test_repo_scan_cache_3224.py",
        "baseline: 17 passed in 3.30s | mutated: 1 failed, 16 passed in 2.34s :: "
        "tests/test_repo_scan_cache_3224.py::test_g_a_real_scan_runs_and_is_reused | reverted: 17 passed in 3.22s",
        "Covers the cache module's one real, unfaked call site (`test_g`, of scripts/check_doc_index.py) — "
        "every other test in this file fakes subprocess.run, by design, to keep the low-level hit/miss "
        "assertions exact (see new_cache()'s own docstring on why a real disk hit would corrupt them). Fast "
        "on both baseline and mutated because this file's autouse `_private_cache` fixture (`disk_dir=None`) "
        "keeps every test's table in-memory-only, so no disk I/O is in either measurement — the REAL scanner "
        "(check_doc_index.py) still ran and still caught the plant (missing wiki-index entry + missing "
        "status header), which is what test_g exists to prove. Does NOT cover the disk layer's cross-process "
        "sharing — that is exactly what the three records above, run as separate OS processes, prove instead.",
        proved_on="2026-09-19",
    ),
}


# ─────────────────────────────────────────────────────────────────────────────
# The runner
# ─────────────────────────────────────────────────────────────────────────────

GREEN, RED = "GREEN", "RED"


def _pytest(target: str, extra: tuple[str, ...] = ()) -> tuple[int, str]:
    """(exit code, the one-line pytest tally). The tally travels with the verdict so a
    recorded `observed` is a transcript, never a paraphrase."""
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", target, "-q", "--no-header", "-p", "no:cacheprovider", *extra],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    tally = ""
    for line in reversed((proc.stdout or "").splitlines()):
        if " passed" in line or " failed" in line or " error" in line:
            tally = line.strip()
            break
    failed = [ln.strip() for ln in (proc.stdout or "").splitlines() if ln.startswith("FAILED ")]
    if failed:
        tally = f"{tally} :: " + "; ".join(f.removeprefix("FAILED ").split(" - ")[0] for f in failed)
    return proc.returncode, tally


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True)


def _apply(spec: MutationSpec) -> None:
    for rel, body in spec.plants:
        path = REPO_ROOT / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        if spec.track:
            _git("add", "--", rel)


def _revert(spec: MutationSpec) -> None:
    for rel, _body in spec.plants:
        path = REPO_ROOT / rel
        if spec.track:
            _git("rm", "-f", "--cached", "--quiet", "--", rel)
        if path.exists():
            path.unlink()
        parent = path.parent
        # Only ever removes a directory the plant itself created.
        if parent != REPO_ROOT and parent.is_dir() and not any(parent.iterdir()):
            parent.rmdir()


def _dirty(spec: MutationSpec) -> list[str]:
    """Paths a spec is about to write that are not already clean — the precondition."""
    dirty = []
    for rel, _body in spec.plants:
        if (REPO_ROOT / rel).exists():
            dirty.append(rel)
        elif _git("ls-files", "--error-unmatch", "--", rel).returncode == 0:
            dirty.append(rel)
    return dirty


def run_spec(spec: MutationSpec) -> dict[str, Any]:
    """Baseline -> mutated -> reverted. ARMED only when GREEN, RED, GREEN."""
    collision = _dirty(spec)
    if collision:
        return {"gate_id": spec.gate_id, "verdict": "SKIPPED", "reason": f"plant path(s) already present: {collision}"}

    baseline, baseline_tally = _pytest(spec.target, spec.extra_args)
    if baseline != 0:
        return {
            "gate_id": spec.gate_id,
            "verdict": "INDETERMINATE",
            "reason": f"baseline is already RED (exit {baseline}): {baseline_tally}",
        }

    try:
        _apply(spec)
        mutated, mutated_tally = _pytest(spec.target, spec.extra_args)
    finally:
        _revert(spec)
    reverted, reverted_tally = _pytest(spec.target, spec.extra_args)

    if mutated == 0:
        verdict = "DARK"
        reason = "the plant did not red the target — a LEAD, not a cannot-fail verdict (re-check the plant's scope first)"
    elif reverted != 0:
        verdict = "INDETERMINATE"
        reason = f"the tree did not return GREEN after revert (exit {reverted}) — the RED cannot be attributed to the plant"
    else:
        verdict = "ARMED"
        reason = ""
    return {
        "gate_id": spec.gate_id,
        "target": spec.target,
        "verdict": verdict,
        "reason": reason,
        "baseline": baseline,
        "mutated": mutated,
        "reverted": reverted,
        "observed": f"baseline: {baseline_tally} | mutated: {mutated_tally} | reverted: {reverted_tally}",
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Run the generated can-it-fail mutations for census family 5 (#2999).")
    ap.add_argument("--run", action="store_true", help="execute the mutations (baseline -> mutated -> reverted)")
    ap.add_argument("--list", action="store_true", help="print the spec registry without running anything")
    ap.add_argument("--gate", action="append", help="restrict to gate id(s) or target filename(s)")
    args = ap.parse_args(argv)

    selected = list(MUTATION_SPECS.values())
    if args.gate:
        wanted = set(args.gate)
        selected = [s for s in selected if s.gate_id in wanted or Path(s.target).name in wanted]
        if not selected:
            print(f"no spec matches {sorted(wanted)}", file=sys.stderr)
            return 2

    if args.list or not args.run:
        for spec in selected:
            print(f"{spec.gate_id}\n    target  {spec.target}\n    detects {spec.detects}")
        print(f"\n{len(selected)} spec(s). Add --run to execute.")
        return 0

    def _emit(spec: MutationSpec, result: dict[str, Any]) -> None:
        line = f"{result['verdict']:<14} {spec.gate_id}"
        if "baseline" in result:
            line += f"   baseline={result['baseline']} mutated={result['mutated']} reverted={result['reverted']}"
        print(line, flush=True)
        if result.get("observed"):
            print(f"               {result['observed']}", flush=True)
        if result.get("reason"):
            print(f"               {result['reason']}", flush=True)

    results = []
    for spec in selected:
        result = run_spec(spec)
        results.append(result)
        _emit(spec, result)

    controls = []
    if not args.gate:
        print("\n-- measured blind spots (a plant INSIDE scope that must stay DARK) --", flush=True)
        for key, spec in DARK_CONTROLS.items():
            result = run_spec(spec)
            result["control"] = key
            controls.append(result)
            _emit(spec, result)

    armed = sum(1 for r in results if r["verdict"] == "ARMED")
    still_dark = sum(1 for r in controls if r["verdict"] == "DARK")
    print(f"\nARMED {armed} / {len(results)} run; blind spots still DARK {still_dark} / {len(controls)}")
    # Exit non-zero when any spec failed to demonstrate its gate: a harness that always
    # exits 0 is the class of instrument this epic exists to find.
    return 0 if armed == len(results) and still_dark == len(controls) else 1


if __name__ == "__main__":
    raise SystemExit(main())
