"""#3681 — a site-deploy generation step must name WHY it failed, and a permission
denial must never be reported as "offline?".

WHAT WENT WRONG. Every content-generation step in `deploy/sync_site_to_s3.sh` was
`python3 .../v4_build_X.py || echo "  ⚠️  X build skipped (offline?) — keeping existing …"`.
`|| echo` converts every non-zero exit to exit 0. On 2026-09-07 the theme-river step
printed that line over a `dynamodb:Query` **AccessDenied** — the CI deploy role had never
held the grant, so the live build had never once succeeded — and the deploy went green
while `https://averagejoematt.com/data/theme_river.json` shipped `{"state": "empty"}`.

TWO HALVES, AND THE SECOND IS THE ONE THAT MATTERS.

1. **Derived enumeration (the SET, not the specimen).** The issue's own Set section says
   the guard must enumerate from the script rather than hard-code the river.
   `generation_steps()` below parses `deploy/sync_site_to_s3.sh` and returns every
   `python3 .../scripts/*.py` invocation in the generation block. Each must be either a
   BARE invocation (fails the sync under `set -e`) or a `run_site_generator` call (fails
   the sync unless it can NAME a benign cause). A reintroduced `|| echo` on any of them —
   including a generator that does not exist yet — reds this file. There is no member
   list in this module; adding a fifteenth step needs no edit here.

2. **The classifier, on the wire.** `classify_generator_failure` is driven with the
   VERBATIM captured output in `tests/fixtures/generator_step/real_failure_output_3681.json`
   — including the exact AccessDeniedException traceback from run 34144388209 — through
   real `bash`, not a Python reimplementation of the `case` patterns. The positive control
   is the load-bearing one: **that traceback must FAIL the step today**, and the word
   "offline" must not appear anywhere in what the operator is shown.

Deliberately NOT swept: this file reads two named paths. It contains no tree walk, so it
does not enter `tests/premerge_derivation.py`'s structural family — it is a contract test
on one script, not a repo-shape ratchet.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SYNC_SCRIPT = ROOT / "deploy" / "sync_site_to_s3.sh"
STEP_LIB = ROOT / "deploy" / "lib" / "generator_step.sh"
WIRE = json.loads((ROOT / "tests" / "fixtures" / "generator_step" / "real_failure_output_3681.json").read_text(encoding="utf-8"))

pytestmark = pytest.mark.deploy_critical

#: A generation step: `python3 "$(dirname "$0")/../scripts/<name>.py" [args]`.
_STEP = re.compile(r'python3\s+"\$\(dirname\s+"\$0"\)/\.\./scripts/([A-Za-z0-9_]+\.py)"(.*)$')
#: The retired idiom. Matched on the two halves independently so neither a reworded
#: message nor a differently-spaced `||` slips past.
_SWALLOW = re.compile(r"\|\|\s*(echo|true|:)\b")


def _script_lines() -> list[str]:
    return SYNC_SCRIPT.read_text(encoding="utf-8").splitlines()


def generation_steps() -> list[dict]:
    """Every generator invocation in the sync script, classified by its guard shape.

    Derived from the file. `wrapper` is the `run_site_generator` line when the step is
    wrapped (the continuation line directly above it), else None.
    """
    lines = _script_lines()
    steps: list[dict] = []
    for i, raw in enumerate(lines):
        line = raw.strip()
        if line.startswith("#"):
            continue
        m = _STEP.search(line)
        if not m:
            continue
        wrapper = None
        prev = lines[i - 1].strip() if i > 0 else ""
        if prev.startswith("run_site_generator ") and prev.endswith("\\"):
            wrapper = prev
        steps.append(
            {
                "script": m.group(1),
                "args": m.group(2).strip(),
                "line_no": i + 1,
                "line": line,
                "wrapper": wrapper,
                "shape": "wrapped" if wrapper else "bare",
            }
        )
    return steps


# ── half 1: the set, derived from the script ────────────────────────────────────


def test_the_script_still_has_generation_steps_to_guard():
    """A derivation that silently returns zero members is the #3220 shape — the guard
    would go green by finding nothing. Pin a floor well under the live count (14 at
    #3681) so a refactor that moves the block out of this file reds instead of passing."""
    steps = generation_steps()
    assert len(steps) >= 10, f"only {len(steps)} generation steps parsed out of {SYNC_SCRIPT} — the derivation is broken, not the script"
    assert any(
        s["script"] == "v4_build_theme_river.py" for s in steps
    ), "the #3681 specimen is no longer in the enumerated set — re-read the derivation before deleting this"


def test_no_generation_step_swallows_its_exit_status():
    """THE RULE. Every enumerated step is bare (fails under `set -e`) or wrapped in
    `run_site_generator` (fails unless it can name a benign cause). `|| echo` / `|| true`
    on a generation step is the defect and may not come back — on ANY member, including
    one added after this test was written."""
    offenders = [f"{SYNC_SCRIPT.name}:{s['line_no']} {s['script']} — {s['line']}" for s in generation_steps() if _SWALLOW.search(s["line"])]
    assert not offenders, "a site generator swallows its exit status again (#3681):\n  " + "\n  ".join(offenders)


def test_every_generation_step_has_a_named_shape():
    steps = generation_steps()
    unknown = [s for s in steps if s["shape"] not in {"wrapped", "bare"}]
    assert not unknown, unknown
    wrapped = [s for s in steps if s["shape"] == "wrapped"]
    assert wrapped, "no step goes through run_site_generator — the classifier is wired to nothing"


def test_wrapped_steps_declare_a_label_and_the_artifact_they_would_keep():
    """ "(offline?)" was uninformative twice over: wrong cause, and it never said which
    artifact shipped stale. A wrapper call must carry both strings."""
    bad = []
    for s in generation_steps():
        if s["shape"] != "wrapped":
            continue
        quoted = re.findall(r'"([^"]*)"', s["wrapper"])
        if len(quoted) < 2 or not all(q.strip() for q in quoted[:2]):
            bad.append(f"{SYNC_SCRIPT.name}:{s['line_no']} {s['script']} — {s['wrapper']}")
    assert not bad, "run_site_generator needs a non-empty <label> and <artifact>:\n  " + "\n  ".join(bad)


def test_no_generation_step_prints_offline_as_a_diagnosis():
    """The literal the issue is named for. Comments may discuss it (this fix is a story
    about it); an executable generation line may not print it."""
    offenders = [
        f"{SYNC_SCRIPT.name}:{s['line_no']} {s['line']}"
        for s in generation_steps()
        if "offline?" in s["line"] or "offline?" in (s["wrapper"] or "")
    ]
    assert not offenders, "a generation step still diagnoses '(offline?)':\n  " + "\n  ".join(offenders)


def test_the_sync_script_sources_the_classifier():
    text = SYNC_SCRIPT.read_text(encoding="utf-8")
    assert (
        "lib/generator_step.sh" in text
    ), "sync_site_to_s3.sh no longer sources deploy/lib/generator_step.sh — run_site_generator would be an unbound command"
    assert STEP_LIB.is_file()


# ── half 2: the classifier, against real captured output ────────────────────────


def _bash(snippet: str, env_overrides: dict | None = None) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    # These tests run BOTH locally and in GitHub Actions; strictness is a function of the
    # environment, so every case sets it explicitly instead of inheriting the runner's.
    env.pop("GITHUB_ACTIONS", None)
    env.pop("SITE_GENERATORS_STRICT", None)
    env.update(env_overrides or {})
    return subprocess.run(
        ["bash", "-c", f'set -uo pipefail; . "{STEP_LIB}"\n{snippet}'],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(ROOT),
    )


@pytest.mark.parametrize("key", sorted(k for k in WIRE if not k.startswith("_")))
def test_classifier_reads_real_captured_output(key):
    sample = WIRE[key]
    payload = sample["text"]
    # Driven by ARGUMENT, not by a heredoc or a pipe: the fixture text contains newlines,
    # quotes and backslashes, and any of those getting re-parsed by a shell would make the
    # test assert against something other than what the platform printed.
    proc = subprocess.run(
        ["bash", "-c", f'. "{STEP_LIB}"; classify_generator_failure "$1"', "_", payload],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert (
        proc.stdout.strip() == sample["expected_cause"]
    ), f"{key} ({sample['source']}) classified {proc.stdout.strip()!r}, expected {sample['expected_cause']!r}"


def test_the_real_accessdenied_fails_the_step_today():
    """POSITIVE CONTROL — the exact traceback from run 34144388209, the one the deploy
    printed "(offline?)" over. It must FAIL."""
    denial = WIRE["denied_dynamodb_query"]["text"]
    proc = _bash(
        'run_site_generator "theme river" "site/data/theme_river.json" bash -c \'printf "%s\\n" "$0" >&2; exit 1\' "$DENIAL"',
        {"DENIAL": denial},
    )
    combined = proc.stdout + proc.stderr
    assert proc.returncode != 0, f"the AccessDenied still exits 0 — the swallow is back:\n{combined}"
    assert "CAUSE: denied" in combined, combined
    assert "offline" not in combined.lower(), f"a permission denial was reported as offline:\n{combined}"
    assert "dynamodb:Query" in combined, "the generator's own output must still reach the operator"


def test_the_real_accessdenied_fails_even_outside_ci():
    """An attended `bash deploy/sync_site_to_s3.sh` from a laptop is a deploy too. The
    denied cause is not in the degradable set, so the local run fails identically."""
    denial = WIRE["denied_s3_list"]["text"]
    proc = _bash(
        'run_site_generator "data_sources" "site/data/data_sources.json" bash -c \'printf "%s\\n" "$0" >&2; exit 3\' "$DENIAL"',
        {"DENIAL": denial},
    )
    assert proc.returncode != 0
    assert "CAUSE: denied" in proc.stdout + proc.stderr


def test_a_real_connectivity_failure_degrades_locally_and_says_why():
    """NEGATIVE CONTROL — the one thing "(offline?)" was ever right about still degrades
    on a laptop, and now names the cause instead of guessing it."""
    text = WIRE["offline_endpoint"]["text"]
    proc = _bash(
        'run_site_generator "theme river" "site/data/theme_river.json" bash -c \'printf "%s\\n" "$0" >&2; exit 1\' "$T"', {"T": text}
    )
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 0, combined
    assert "CAUSE: offline" in combined, combined
    assert "site/data/theme_river.json" in combined, "a degrade must say which artifact shipped stale"


def test_the_same_connectivity_failure_fails_in_ci():
    """A deploy is not green when it shipped a stale artifact it was asked to regenerate
    (the issue's Outcome). In CI there is no degradable cause at all."""
    text = WIRE["offline_endpoint"]["text"]
    proc = _bash(
        'run_site_generator "theme river" "site/data/theme_river.json" bash -c \'printf "%s\\n" "$0" >&2; exit 1\' "$T"',
        {"T": text, "GITHUB_ACTIONS": "true"},
    )
    assert proc.returncode != 0, proc.stdout + proc.stderr
    assert "STRICT" in proc.stdout + proc.stderr


def test_strict_can_be_requested_locally():
    text = WIRE["no_credentials"]["text"]
    lenient = _bash('run_site_generator "rss" "site/rss.xml" bash -c \'printf "%s\\n" "$0" >&2; exit 1\' "$T"', {"T": text})
    strict = _bash(
        'run_site_generator "rss" "site/rss.xml" bash -c \'printf "%s\\n" "$0" >&2; exit 1\' "$T"',
        {"T": text, "SITE_GENERATORS_STRICT": "1"},
    )
    assert lenient.returncode == 0 and strict.returncode != 0


def test_an_unrecognised_failure_is_treated_as_real():
    """The default is FAIL. A generator bug that matches nothing benign must not be
    quietly absorbed — that is how the 13 non-AWS members would have gone dark."""
    text = WIRE["unclassified_bug"]["text"]
    proc = _bash('run_site_generator "rss" "site/rss.xml" bash -c \'printf "%s\\n" "$0" >&2; exit 1\' "$T"', {"T": text})
    combined = proc.stdout + proc.stderr
    assert proc.returncode != 0, combined
    assert "CAUSE: unclassified" in combined
    assert "KeyError" in combined, "the generator's own traceback must still be shown"


def test_a_successful_generator_is_transparent():
    proc = _bash('run_site_generator "rss" "site/rss.xml" bash -c \'echo "site/rss.xml: wrote 12 items"\'')
    assert proc.returncode == 0, proc.stderr
    assert "wrote 12 items" in proc.stdout
    assert "skipped" not in proc.stdout and "FAILED" not in proc.stdout


def test_the_degradable_set_is_exactly_the_two_causes_a_deploy_cannot_fix():
    """A ratchet on the allowlist. Widening it is a posture change — `denied` or
    `unclassified` appearing here would restore the defect wholesale, in one token."""
    proc = subprocess.run(["bash", "-c", f'. "{STEP_LIB}"; echo "$SITE_GENERATOR_DEGRADABLE_CAUSES"'], capture_output=True, text=True)
    assert set(proc.stdout.split()) == {"offline", "no-credentials"}, proc.stdout


# ── the grant, pinned to the step that consumes it ──────────────────────────────


def test_the_deploy_role_grants_the_query_the_theme_river_step_needs():
    """The other half of #3681. `scripts/v4_build_theme_river.py --live` Queries the
    notion journal partition; the CI deploy role held `DescribeTable` and
    `DescribeContinuousBackups` and NOT `Query`, from the day the step was wired, so the
    live build could never succeed — a permanent structural failure, not an intermittent
    one. Pinned against the checked-in document (the source of truth for live IAM,
    infra/iam/README.md) so the grant cannot be quietly dropped by a future narrowing pass.

    The first assert keeps the pin from outliving the code it guards: if the theme-river
    step stops reading DynamoDB, delete this test rather than keeping the grant.

    NOTE: repo-vs-LIVE parity is NOT this test's job — `tests/test_grant_enumeration_drift.py`
    asks the account, and carries this change in `_PENDING_PERMISSIONS_APPLY` until the
    attended `put-role-policy` runs.
    """
    river = (ROOT / "scripts" / "v4_build_theme_river.py").read_text(encoding="utf-8")
    assert "import boto3" in river and "--live" in river, "v4_build_theme_river.py no longer reads DynamoDB — delete this pin (#3681)"
    assert any(
        s["script"] == "v4_build_theme_river.py" and "--live" in s["args"] for s in generation_steps()
    ), "the sync script no longer runs the theme-river build with --live — delete this pin (#3681)"

    doc = json.loads((ROOT / "infra" / "iam" / "github-actions-deploy-role.permissions.json").read_text(encoding="utf-8"))
    ddb = [s for s in doc["Statement"] if s.get("Sid") == "DynamoDB"]
    assert len(ddb) == 1, ddb
    actions = ddb[0]["Action"]
    actions = actions if isinstance(actions, list) else [actions]
    assert "dynamodb:Query" in actions, (
        "the CI deploy role no longer grants dynamodb:Query — sync_site_to_s3.sh's theme-river "
        "step AccessDenies on every site deploy and /data/theme_river.json ships stale (#3681)"
    )
    assert (
        ddb[0]["Resource"] == "arn:aws:dynamodb:us-west-2:205930651321:table/life-platform"
    ), "the Query grant must stay table-scoped — no index, no wildcard"
    assert not [a for a in actions if a.endswith(("PutItem", "UpdateItem", "DeleteItem", "BatchWriteItem", "Scan"))], (
        "the deploy role's DynamoDB grant must stay READ-ONLY and Query-shaped; a write or a Scan "
        "here is a different decision than #3681 made"
    )


def test_the_deploy_role_can_decrypt_the_table_cmk_but_only_through_dynamodb():
    """#3681, the SECOND hidden denial — a Query grant alone is not a readable table.

    The `life-platform` table is encrypted with a customer-managed CMK
    (`444438d1-…`, "Life Platform DynamoDB encryption — health data at rest"). DynamoDB
    decrypts on the CALLER's behalf, so `dynamodb:Query` without `kms:Decrypt` on that key
    is an AccessDenied the first grant could not reveal: the Query denial masked it, and
    the site deploy failed a second time on a permission nobody had seen.

    The grant is deliberately NOT unconditional. `kms:ViaService` pins it to DynamoDB, so
    the deploy role can decrypt only as a side effect of a read it is already allowed to
    make — it can never call `kms:Decrypt` against the health-data key directly. That
    condition is the whole reason this is a separate statement from the plain-`DescribeKey`
    `KMS` Sid rather than one more action on it; asserting it here is what keeps a future
    narrowing-or-widening pass from collapsing the two.
    """
    doc = json.loads((ROOT / "infra" / "iam" / "github-actions-deploy-role.permissions.json").read_text(encoding="utf-8"))
    key_arn = "arn:aws:kms:us-west-2:205930651321:key/444438d1-a5e0-43b8-9391-3cd2d70dde4d"

    def _as_list(v):
        return v if isinstance(v, list) else [v]

    decrypt = [s for s in doc["Statement"] if s.get("Effect") == "Allow" and "kms:Decrypt" in _as_list(s.get("Action"))]
    assert len(decrypt) == 1, f"expected exactly one kms:Decrypt statement on the deploy role, got {len(decrypt)}"
    stmt = decrypt[0]
    assert _as_list(stmt["Resource"]) == [key_arn], "the Decrypt grant must name the one health-data CMK — no wildcard, no alias"
    via = stmt.get("Condition", {}).get("StringEquals", {}).get("kms:ViaService")
    assert via == "dynamodb.us-west-2.amazonaws.com", (
        "the deploy role's kms:Decrypt must stay conditioned on kms:ViaService=dynamodb.us-west-2.amazonaws.com. "
        "Without it CI holds direct decrypt on the health-data key, which is a bigger decision than #3681 made."
    )
    assert not [a for a in _as_list(stmt["Action"]) if a not in ("kms:Decrypt",)], (
        "this statement exists for the DynamoDB read path only — kms:Encrypt/GenerateDataKey/re-encrypt " "belong to a different decision"
    )
