#!/usr/bin/env python3
"""tests/test_role_family_write_scope.py — IAM parity as a ROLE FAMILY (#3596).

THE CLASS (forensic RCA 2026-09-05, class 3 — the real-wire half)
  `tests/test_freshness_checker_iam_parity.py` asks the parity question for exactly ONE
  checker and ONE grant. Nothing at PR time asked "did this Lambda gain a verb, or a pk its
  role cannot reach". A `FakeDdbTable` cannot deny a `put_item`, so two writes were denied
  every run for weeks behind green tests (#3563):

    * G-3   `chronicle-email-sender` calls `_record_email_send` -> `table.put_item(...)` on
            `USER#matthew#SOURCE#email_log#wednesday_chronicle`; `email_chronicle_sender()`
            grants GetItem/Query/UpdateItem and no PutItem. 3 sends, 3 swallowed
            AccessDeniedExceptions, and `/api/status` read "44d ago" for four weeks.
    * INT-1 `life-platform-freshness-checker` calls `put_item` on
            `USER#matthew#SOURCE#notion`; the PutItem grant's `dynamodb:LeadingKeys`
            condition allows `USER#matthew#SOURCE#apple_health` only. 155 denials in 14
            days, and the journal-dark dedup (#1480) has never once worked.

  Both writes are inside `try/except` blocks that log and continue, so the only symptom was
  silence. That is the whole point of this file: a denial that nothing can see.

WHAT IT DERIVES (nothing is hand-listed except the dated gap ledger)
  1. THE FAMILY. AST-read every `create_platform_lambda(...)` call in `cdk/stacks/*_stack.py`
     for its `function_name`, `source_file` and `custom_policies=rp.<name>()`. That is the
     role <-> module <-> live-function mapping, derived from the construction site.
  2. THE CODE SIDE. AST-read each owning module for DynamoDB write calls and, where the pk
     is statically resolvable (a literal, an f-string, or a local bound to one), the
     partition it writes.
  3. THE GRANT SIDE. Import `cdk/stacks/role_policies*.py` behind the same `aws_cdk` stub
     `test_freshness_checker_iam_parity.py` uses (no CDK install needed) and read each
     statement's actions and `dynamodb:LeadingKeys` values.
  4. THE ASSERTION. Every write verb is granted, and every resolvable pk is inside the
     allowlist of a statement that grants that verb. Gaps are compared to `KNOWN_GAPS` as a
     SET, in both directions.

WHY A DATED LEDGER AND NOT A RED SUITE
  This test is RED on main the day it lands — that is its positive control, and #3563 is the
  fix. A test that simply fails would red main for every other lane until an owner-run
  `cdk deploy` cleared it, so the two live gaps are recorded BY NAME, dated, with the exact
  change that clears each. The ratchet runs both ways: an unledgered gap fails
  (`test_no_write_scope_gap_is_unledgered`), and a ledger line whose gap is GONE also fails
  (`test_the_gap_ledger_has_no_stale_line`) — so #3563's fix cannot land without deleting
  its line, which is how "green after the fix" is enforced rather than hoped for.

STATED BLIND SPOTS (asserted below, not left to the reader)
  * Shared modules (`lambdas/common/rate_limiter.py`, `lambdas/coach/*`, ...) write through
    whichever role imports them; this file scopes to the entrypoint module a stack names.
    48 shared modules write DynamoDB and are deliberately out of scope.
  * A pk built from data (a loop variable, a dict lookup) is not statically resolvable; those
    sites are counted and reported, never silently treated as "covered".
  * The live leg (checked-in policy vs deployed policy) needs read-only AWS credentials. With
    none it SKIPS LOUDLY, naming what went unmeasured — it never passes quietly.

Run:  python3 -m pytest tests/test_role_family_write_scope.py -v
"""

from __future__ import annotations

import ast
import fnmatch
import glob
import os
import sys
import types
from dataclasses import dataclass

import pytest

# #416 / ADR-117: deploy-critical lane (IAM parity guard), same lane as its one-checker sibling.
pytestmark = pytest.mark.deploy_critical

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CDK_DIR = os.path.join(ROOT, "cdk")
CDK_STACKS = os.path.join(CDK_DIR, "stacks")

# The write verbs a role must name explicitly. `batch_writer()` issues BatchWriteItem, which
# PutItem does NOT imply — the distinction is exactly the kind a reviewer eyeballs past.
WRITE_CALLS = {
    "put_item": "dynamodb:PutItem",
    "update_item": "dynamodb:UpdateItem",
    "delete_item": "dynamodb:DeleteItem",
    "batch_writer": "dynamodb:BatchWriteItem",
}


# ── the grant side ───────────────────────────────────────────────────────────────────────
def _role_policies_module():
    """Import role_policies behind an `aws_cdk` stub — the pattern of
    tests/test_iam_secrets_consistency.py and tests/test_freshness_checker_iam_parity.py.

    ONE difference, and it is load-bearing: those siblings' stub `PolicyStatement` swallows
    `conditions` into `**kwargs` and drops it, because neither of them reads a condition. This
    file's whole INT-1 leg IS a condition (`dynamodb:LeadingKeys`), so if a sibling's stub is
    already installed when this module imports, every LeadingKeys scope reads empty and the pk
    leg passes vacuously — measured 2026-09-06 as five failures in the full suite that did not
    reproduce standalone. So the stub is FORCED (not setdefault) and any cached role_policies*
    module is purged so it re-executes against it. Safe in the other direction: this stub is a
    strict superset — it keeps `sid`, `actions`, `resources` AND `conditions`, so a sibling that
    imports afterwards reads everything it did before.
    """

    class _PolicyStatement:
        def __init__(self, sid="", actions=None, resources=None, conditions=None, **kwargs):
            self.sid = sid
            self.actions = list(actions or [])
            self.resources = list(resources or [])
            self.conditions = dict(conditions or {})

    class _Effect:
        ALLOW = "Allow"
        DENY = "Deny"

    iam_stub = types.ModuleType("aws_cdk.aws_iam")
    iam_stub.PolicyStatement = _PolicyStatement
    iam_stub.Effect = _Effect
    cdk_stub = types.ModuleType("aws_cdk")
    cdk_stub.aws_iam = iam_stub
    for p in (CDK_DIR, CDK_STACKS):
        if p not in sys.path:
            sys.path.insert(0, p)

    def _is_role_policy_module(name: str) -> bool:
        return name == "role_policies" or name.startswith(("role_policies_", "stacks.role_policies"))

    # Swap, import, RESTORE. The stub is installed only for the duration of this import, and
    # every module it displaces goes back exactly as it was — including the REAL `aws_cdk`, which
    # is installed in this environment and which a later test may legitimately want. The imported
    # modules keep working afterwards because their own `iam` global still points at the stub
    # module object; only the sys.modules registry is handed back.
    saved = {name: sys.modules.get(name) for name in ("aws_cdk", "aws_cdk.aws_iam")}
    saved.update({name: mod for name, mod in list(sys.modules.items()) if _is_role_policy_module(name)})
    for name in list(sys.modules):
        if _is_role_policy_module(name):
            del sys.modules[name]
    sys.modules["aws_cdk"] = cdk_stub
    sys.modules["aws_cdk.aws_iam"] = iam_stub
    try:
        import role_policies as rp

        siblings = []
        for path in sorted(glob.glob(os.path.join(CDK_STACKS, "role_policies_*.py"))):
            name = os.path.splitext(os.path.basename(path))[0]
            try:
                siblings.append(__import__(name))
            except ImportError:  # pragma: no cover - every sibling imports cleanly today
                continue
    finally:
        for name in list(sys.modules):
            if _is_role_policy_module(name):
                del sys.modules[name]
        for name, mod in saved.items():
            if mod is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = mod

    assert getattr(rp.operational_freshness_checker()[1], "conditions", None), (
        "the imported role_policies built its statements with a stub that drops `conditions` — "
        "the LeadingKeys leg would pass vacuously. Fix the stub, never the assertion."
    )
    return rp, [rp, *siblings]


# The facade plus its siblings, globbed — never hand-listed (#2604's lesson: the next split must
# not make this go quietly blind). `operational_permanence()` lives in a sibling the facade does
# NOT re-export, and operational_stack.py imports it directly.
RP, ROLE_POLICY_MODULES = _role_policies_module()


def policy_statements(policy_fn: str):
    """The statements of one role, from whichever family member defines it."""
    for mod in ROLE_POLICY_MODULES:
        fn = getattr(mod, policy_fn, None)
        if callable(fn):
            return fn()
    raise AssertionError(f"rp.{policy_fn}() is defined by no member of the role_policies* family")


def policy_is_defined(policy_fn: str) -> bool:
    return any(callable(getattr(mod, policy_fn, None)) for mod in ROLE_POLICY_MODULES)


def granted_actions(statements) -> set:
    return {a for s in statements for a in getattr(s, "actions", [])}


def leading_keys_for(statements, action: str) -> list:
    """[[patterns], ...] — one list per statement granting `action`. An empty inner list means
    that statement grants the action with NO LeadingKeys condition, i.e. table-wide."""
    out = []
    for s in statements:
        if action not in getattr(s, "actions", []):
            continue
        keys: list = []
        for _op, kv in (getattr(s, "conditions", {}) or {}).items():
            for cond_key, cond_val in (kv or {}).items():
                if cond_key == "dynamodb:LeadingKeys":
                    keys.extend(cond_val if isinstance(cond_val, list) else [cond_val])
        out.append(keys)
    return out


# ── the family: the construction site is the mapping ─────────────────────────────────────
@dataclass(frozen=True)
class Enrolment:
    stack: str
    function_name: str
    source_file: str
    policy_fn: str


def _kw_str(keywords: dict, name: str):
    node = keywords.get(name)
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def derive_role_family(stack_glob: str | None = None) -> list:
    """Every `create_platform_lambda(...)` in the CDK stacks, as (function, module, policy)."""
    rows: list = []
    for path in sorted(glob.glob(stack_glob or os.path.join(CDK_STACKS, "*_stack.py"))):
        with open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read(), filename=path)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "create_platform_lambda"):
                continue
            kw = {k.arg: k.value for k in node.keywords if k.arg}
            policy = kw.get("custom_policies")
            policy_fn = None
            if isinstance(policy, ast.Call):
                f = policy.func
                policy_fn = f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else None)
            fn, src = _kw_str(kw, "function_name"), _kw_str(kw, "source_file")
            if fn and src and policy_fn:
                rows.append(Enrolment(os.path.basename(path), fn, src, policy_fn))
    return rows


ROLE_FAMILY = derive_role_family()
ENROLLED_MODULES = {e.source_file for e in ROLE_FAMILY}


# ── the code side ────────────────────────────────────────────────────────────────────────
def _string_bindings(tree: ast.AST) -> dict:
    """{name: resolved string} for simple `NAME = "..."` / f-string assignments. A name bound
    twice to different values resolves to None — an ambiguous binding is not evidence."""
    bindings: dict = {}
    conflicting: set = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            value = resolve_string(node.value, bindings)
            if name in bindings and bindings[name] != value:
                conflicting.add(name)
            bindings[name] = value
    for name in conflicting:
        bindings[name] = None
    return bindings


def resolve_string(node, bindings: dict):
    """A literal, an f-string (unresolvable interpolations become `*`), a `+` of those, or a
    name bound to one. None when nothing can be said."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return bindings.get(node.id)
    if isinstance(node, ast.JoinedStr):
        out = ""
        for part in node.values:
            if isinstance(part, ast.Constant):
                out += str(part.value)
            elif isinstance(part, ast.FormattedValue):
                inner = resolve_string(part.value, bindings)
                out += inner if inner is not None else "*"
            else:
                out += "*"
        return out
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = resolve_string(node.left, bindings), resolve_string(node.right, bindings)
        return left + right if left is not None and right is not None else None
    return None


def _pk_of(call: ast.Call, bindings: dict):
    for kw in call.keywords:
        if kw.arg in ("Item", "Key") and isinstance(kw.value, ast.Dict):
            for key, value in zip(kw.value.keys, kw.value.values):
                if isinstance(key, ast.Constant) and key.value == "pk":
                    return resolve_string(value, bindings)
    return None


def write_sites(source: str) -> list:
    """[(verb, pk_or_None, lineno)] for every DynamoDB write call in a module."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    bindings = _string_bindings(tree)
    sites = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in WRITE_CALLS:
            sites.append((WRITE_CALLS[node.func.attr], _pk_of(node, bindings), node.lineno))
    return sorted(set(sites), key=lambda t: t[2])


def _pk_covered(pk: str, patterns: list) -> bool:
    """Both directions, because either side may carry the `*` an unresolved interpolation left:
    `USER#*#SOURCE#notion` vs `USER#matthew#SOURCE#apple_health` is a MISS in both."""
    return any(fnmatch.fnmatch(pk, p) or fnmatch.fnmatch(pk, p + "*") or fnmatch.fnmatch(p, pk) for p in patterns)


@dataclass(frozen=True)
class Gap:
    key: str
    function_name: str
    source_file: str
    policy_fn: str
    detail: str


def find_gaps(family=None) -> list:
    """Every write a role cannot make. Pure over the derived family."""
    gaps: list = []
    for e in family if family is not None else ROLE_FAMILY:
        path = os.path.join(ROOT, e.source_file)
        if not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8") as fh:
            sites = write_sites(fh.read())
        if not sites:
            continue
        statements = policy_statements(e.policy_fn)
        granted = granted_actions(statements)
        for verb, pk, lineno in sites:
            if verb not in granted and "dynamodb:*" not in granted:
                gaps.append(
                    Gap(
                        f"{e.function_name}::verb::{verb}",
                        e.function_name,
                        e.source_file,
                        e.policy_fn,
                        f"{e.source_file}:{lineno} calls {verb.split(':')[1]} and {e.policy_fn}() grants "
                        f"{sorted(a for a in granted if a.startswith('dynamodb:')) or 'no DynamoDB action'}",
                    )
                )
                continue
            if pk is None:
                continue
            scopes = leading_keys_for(statements, verb)
            if not scopes or not all(scopes):
                continue  # at least one granting statement is table-wide: the pk is reachable
            patterns = sorted({p for scope in scopes for p in scope})
            if not _pk_covered(pk, patterns):
                gaps.append(
                    Gap(
                        f"{e.function_name}::pk::{verb}::{pk}",
                        e.function_name,
                        e.source_file,
                        e.policy_fn,
                        f"{e.source_file}:{lineno} writes pk {pk!r} but {e.policy_fn}()'s {verb} grant is scoped by "
                        f"dynamodb:LeadingKeys to {patterns}",
                    )
                )
    return sorted(gaps, key=lambda g: g.key)


GAPS = find_gaps()


# ══════════════════════════════════════════════════════════════════════════════════════════
# THE DATED GAP LEDGER (charter primitive 3). Shrink-only: a line comes OUT when its fix
# lands, and `test_the_gap_ledger_has_no_stale_line` is what forces the deletion.
# ══════════════════════════════════════════════════════════════════════════════════════════
KNOWN_GAPS = {
    "chronicle-email-sender::verb::dynamodb:PutItem": (
        "2026-09-05 (#3563, finding G-3) — `_record_email_send`'s status write has been denied on every send "
        "since 2026-08-08; /api/status read the Wednesday chronicle as '44d ago' while three issues shipped. "
        "CLEARS WHEN: email_chronicle_sender() gains dynamodb:PutItem on the email_log partition AND "
        "`bash deploy/cdk_deploy.sh LifePlatformEmail` runs. Delete this line in that PR."
    ),
    "life-platform-freshness-checker::pk::dynamodb:PutItem::USER#*#SOURCE#notion": (
        "2026-09-05 (#3563, finding INT-1) — the #1480 journal-dark dedup writes ALERTSTATE on the notion "
        "partition while DynamoDBWriteApHealthSentinels' LeadingKeys allows apple_health only; 155 denials in "
        "14 days and every run re-opens the episode. CLEARS WHEN: the LeadingKeys allowlist gains "
        "USER#matthew#SOURCE#notion AND `bash deploy/cdk_deploy.sh LifePlatformOperational` runs."
    ),
    "food-delivery-ingestion::verb::dynamodb:BatchWriteItem": (
        "2026-09-05 (#3596, derived — NOT field-verified) — food_delivery_lambda.py:161 writes through "
        "`table.batch_writer()`, which issues BatchWriteItem; food_delivery_ingestion() grants "
        "PutItem/GetItem/Query only, and PutItem does not imply BatchWriteItem. The Lambda is S3-triggered on "
        "uploads/food_delivery/, so it may not have run since the grant was written — this is a LEAD for the "
        "#3563 fix lane to confirm against CloudWatch before changing IAM, not a measured incident."
    ),
}


# ══════════════════════════════════════════════════════════════════════════════════════════
# 1. THE DERIVATION IS NON-VACUOUS (a guard that extracted nothing passes everything)
# ══════════════════════════════════════════════════════════════════════════════════════════


def test_the_role_family_is_derived_and_substantial():
    assert len(ROLE_FAMILY) >= 100, f"only {len(ROLE_FAMILY)} create_platform_lambda sites resolved — extraction is broken"
    assert {"life-platform-qa-smoke", "chronicle-email-sender", "life-platform-freshness-checker"} <= {e.function_name for e in ROLE_FAMILY}
    for e in ROLE_FAMILY:
        assert policy_is_defined(
            e.policy_fn
        ), f"{e.stack} wires {e.function_name} to {e.policy_fn}(), which no role_policies* member defines"


def test_the_write_extractor_reads_the_two_incident_modules():
    """Non-vacuity where it counts: if these two extractions ever return nothing, every
    assertion below passes for free — the #2578 failure mode one level up."""
    with open(os.path.join(ROOT, "lambdas/emails/chronicle_email_sender_lambda.py"), encoding="utf-8") as fh:
        sender = write_sites(fh.read())
    assert any(verb == "dynamodb:PutItem" and (pk or "").endswith("email_log#wednesday_chronicle") for verb, pk, _ln in sender)
    with open(os.path.join(ROOT, "lambdas/emails/freshness_checker_lambda.py"), encoding="utf-8") as fh:
        checker = write_sites(fh.read())
    assert any(verb == "dynamodb:PutItem" and (pk or "").endswith("SOURCE#notion") for verb, pk, _ln in checker)


def test_the_grant_side_reads_real_statements():
    sender = granted_actions(RP.email_chronicle_sender())
    assert "dynamodb:UpdateItem" in sender and "dynamodb:PutItem" not in sender, sorted(sender)
    scopes = leading_keys_for(RP.operational_freshness_checker(), "dynamodb:PutItem")
    assert scopes == [["USER#matthew#SOURCE#apple_health"]], scopes


# ══════════════════════════════════════════════════════════════════════════════════════════
# 2. THE ASSERTION, BOTH DIRECTIONS
# ══════════════════════════════════════════════════════════════════════════════════════════


def test_no_write_scope_gap_is_unledgered():
    """A Lambda that gains a DynamoDB verb, or a pk its role cannot reach, is red HERE — on the
    PR that adds it — instead of silently AccessDenied-ing behind a FakeDdbTable for a month."""
    unledgered = [g for g in GAPS if g.key not in KNOWN_GAPS]
    assert not unledgered, (
        "IAM write-scope parity FAIL — this write will AccessDenied at runtime:\n"
        + "\n".join(f"  {g.key}\n      {g.detail}" for g in unledgered)
        + (
            "\n\nFix the GRANT in cdk/stacks/role_policies*.py (then the owner CDK-deploys the stack). "
            "If the write is genuinely unreachable, add a dated line to KNOWN_GAPS saying why and what clears it."
        )
    )


def test_the_gap_ledger_has_no_stale_line():
    """The ratchet. When #3563's grant lands, its gap disappears and this test names the line to
    delete — so 'green after the fix' is enforced, not hoped for."""
    live = {g.key for g in GAPS}
    stale = sorted(k for k in KNOWN_GAPS if k not in live)
    assert not stale, "these KNOWN_GAPS lines no longer describe a live gap — delete them in the PR that fixed them:\n" + "\n".join(
        f"  {k}" for k in stale
    )


def test_the_two_incidents_3563_measured_are_the_ledger_today():
    """The positive control on the real repo: both #3563 findings are present, by name, RIGHT
    NOW. If this list ever shrinks by itself, the extractor went blind rather than the bug
    getting fixed — the stale-line test above is what distinguishes the two."""
    keys = {g.key for g in GAPS}
    assert "chronicle-email-sender::verb::dynamodb:PutItem" in keys, "G-3's denied PutItem vanished from the derivation"
    assert "life-platform-freshness-checker::pk::dynamodb:PutItem::USER#*#SOURCE#notion" in keys, "INT-1's pk gap vanished"


def test_every_ledger_line_is_dated_and_says_what_clears_it():
    for key, reason in KNOWN_GAPS.items():
        assert reason.strip()[:4].isdigit() and reason.strip()[4] == "-", f"{key}: undated ledger line"
        assert len(reason) >= 120, f"{key}: a reason this short is a label, not a disposition"
        assert "CLEARS WHEN" in reason or "NOT field-verified" in reason, f"{key}: says nothing about what clears it"


# ══════════════════════════════════════════════════════════════════════════════════════════
# 3. ENROLMENT — a writing Lambda that no stack maps to a role
# ══════════════════════════════════════════════════════════════════════════════════════════

# The ONE module with a `lambda_handler` that writes DynamoDB and is not a stack's
# `source_file`. Each entry is a decision, not a silence.
UNENROLLED_WRITERS = {
    "lambdas/coach/coach_diary_reaction.py": (
        "not a deployed entrypoint despite defining lambda_handler — it is imported as a library by "
        "journal_enrichment_lambda.py and social_enrichment_lambda.py (`from coach.coach_diary_reaction import "
        "maybe_react`), so its writes run under those two roles and are covered by their rows above."
    ),
}


def _lambda_sources() -> list:
    """Every .py under lambdas/ ON DISK (os.walk, not the git index): an UNTRACKED module a
    branch is about to add is exactly the case this guard has to see before the merge."""
    found = []
    for dirpath, dirnames, filenames in os.walk(os.path.join(ROOT, "lambdas")):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for name in filenames:
            if name.endswith(".py"):
                found.append(os.path.join(dirpath, name))
    return sorted(found)


def _entrypoint_writers() -> list:
    out = []
    for path in _lambda_sources():
        rel = os.path.relpath(path, ROOT)
        with open(path, encoding="utf-8") as fh:
            source = fh.read()
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        if not any(isinstance(n, ast.FunctionDef) and n.name == "lambda_handler" for n in tree.body):
            continue
        if write_sites(source):
            out.append(rel)
    return out


def test_every_ddb_writing_entrypoint_is_enrolled_in_the_family():
    writers = _entrypoint_writers()
    assert len(writers) >= 40, f"only {len(writers)} writing entrypoints found — the scan is broken"
    missing = sorted(set(writers) - ENROLLED_MODULES - set(UNENROLLED_WRITERS))
    assert not missing, (
        f"{missing} define lambda_handler and write DynamoDB but no cdk/stacks/*_stack.py "
        "create_platform_lambda call names them as `source_file` with `custom_policies=` — so no role's write "
        "scope covers them and this file cannot check them. Wire the stack, or add a reason to UNENROLLED_WRITERS."
    )


def test_the_shared_module_blind_spot_is_stated_and_measured():
    """48 shared modules write DynamoDB under whichever role imports them. Out of scope by
    design; recorded so the next reader knows this file's reach rather than assuming it."""
    shared = []
    for path in _lambda_sources():
        rel = os.path.relpath(path, ROOT)
        if rel in ENROLLED_MODULES:
            continue
        with open(path, encoding="utf-8") as fh:
            if write_sites(fh.read()):
                shared.append(rel)
    assert len(shared) > 20, "the shared-writer population vanished — re-derive this blind spot rather than deleting it"


# ══════════════════════════════════════════════════════════════════════════════════════════
# 4. MUTATION PROOFS — every leg made to fail on purpose, on synthetic input
# ══════════════════════════════════════════════════════════════════════════════════════════


class _Stmt:
    def __init__(self, sid, actions, conditions=None):
        self.sid = sid
        self.actions = list(actions)
        self.resources = ["arn:aws:dynamodb:::table/x"]
        self.conditions = conditions or {}


def _scoped(patterns):
    return {"ForAllValues:StringEquals": {"dynamodb:LeadingKeys": list(patterns)}}


def _synthetic(tmp_path, source: str, policy_name: str, statements):
    """A one-module family whose policy function is monkeypatched onto RP."""
    module = tmp_path / "probe_lambda.py"
    module.write_text(source, encoding="utf-8")
    rel = os.path.relpath(str(module), ROOT)
    setattr(RP, policy_name, lambda: statements)
    return [Enrolment("probe_stack.py", "probe-fn", rel, policy_name)]


def test_MUTATION_a_planted_ungranted_put_item_reds_by_name(tmp_path):
    fam = _synthetic(
        tmp_path,
        "def lambda_handler(e, c):\n    table.put_item(Item={'pk': 'USER#matthew#SOURCE#probe', 'sk': 'X'})\n",
        "_probe_verb_3596",
        [_Stmt("DynamoDB", ["dynamodb:GetItem", "dynamodb:Query"])],
    )
    (gap,) = find_gaps(fam)
    assert gap.key == "probe-fn::verb::dynamodb:PutItem"
    assert "probe-fn" in gap.function_name and "PutItem" in gap.detail
    fam2 = _synthetic(
        tmp_path,
        "def lambda_handler(e, c):\n    table.put_item(Item={'pk': 'USER#matthew#SOURCE#probe', 'sk': 'X'})\n",
        "_probe_verb_ok_3596",
        [_Stmt("DynamoDB", ["dynamodb:PutItem"])],
    )
    assert find_gaps(fam2) == [], "the same module with the grant present must be clean (negative control)"


def test_MUTATION_a_pk_outside_the_leadingkeys_allowlist_reds_and_names_the_pk(tmp_path):
    """The acceptance's own case: plant a write on a pk outside a role's allowlist."""
    source = "USER = 'matthew'\n_pk = f'USER#{USER}#SOURCE#planted'\n\ndef lambda_handler(e, c):\n    table.put_item(Item={'pk': _pk})\n"
    fam = _synthetic(tmp_path, source, "_probe_pk_3596", [_Stmt("W", ["dynamodb:PutItem"], _scoped(["USER#matthew#SOURCE#apple_health"]))])
    (gap,) = find_gaps(fam)
    assert gap.key.endswith("USER#matthew#SOURCE#planted"), gap.key
    assert "probe-fn" in gap.function_name and "LeadingKeys" in gap.detail
    fam_ok = _synthetic(tmp_path, source, "_probe_pk_ok_3596", [_Stmt("W", ["dynamodb:PutItem"], _scoped(["USER#matthew#SOURCE#planted"]))])
    assert find_gaps(fam_ok) == [], "the same write inside the allowlist must be clean (negative control)"


def test_MUTATION_a_table_wide_grant_is_not_a_pk_gap(tmp_path):
    """A second statement granting the same verb with no condition makes the pk reachable —
    a false red here would be an instrument nobody could keep green."""
    source = "def lambda_handler(e, c):\n    table.put_item(Item={'pk': 'ANY#thing'})\n"
    fam = _synthetic(
        tmp_path,
        source,
        "_probe_wide_3596",
        [_Stmt("Scoped", ["dynamodb:PutItem"], _scoped(["USER#matthew#SOURCE#x"])), _Stmt("Wide", ["dynamodb:PutItem"])],
    )
    assert find_gaps(fam) == []


def test_MUTATION_an_undecidable_pk_is_never_reported_as_covered_or_as_a_gap(tmp_path):
    source = "def lambda_handler(e, c):\n    for row in rows:\n        table.put_item(Item={'pk': row['pk']})\n"
    fam = _synthetic(tmp_path, source, "_probe_dyn_3596", [_Stmt("W", ["dynamodb:PutItem"], _scoped(["USER#matthew#SOURCE#x"]))])
    assert find_gaps(fam) == []
    with open(os.path.join(str(tmp_path), "probe_lambda.py"), encoding="utf-8") as fh:
        assert write_sites(fh.read()) == [("dynamodb:PutItem", None, 3)], "the site is still SEEN, with pk=None"


def test_MUTATION_the_ledger_legs_red_on_synthetic_sets():
    """Both directions of the ratchet, as pure set decisions — no repo state involved."""
    live = {"a::verb::dynamodb:PutItem"}
    ledger = {"b::verb::dynamodb:PutItem": "..."}
    assert sorted(live - set(ledger)) == ["a::verb::dynamodb:PutItem"], "an unledgered gap must be visible"
    assert sorted(set(ledger) - live) == ["b::verb::dynamodb:PutItem"], "a stale ledger line must be visible"


def test_MUTATION_the_enrolment_leg_reds_on_a_planted_unmapped_writer():
    planted = sorted({"lambdas/planted/probe_lambda.py"} - ENROLLED_MODULES - set(UNENROLLED_WRITERS))
    assert planted == ["lambdas/planted/probe_lambda.py"]


# ══════════════════════════════════════════════════════════════════════════════════════════
# 5. THE LIVE LEG — is the checked-in document the DEPLOYED one? (read-only, skips LOUDLY)
# ══════════════════════════════════════════════════════════════════════════════════════════

# The roles whose deployed state is in question right now. Scoped rather than family-wide:
# 103 roles would be ~400 IAM calls in a lane that is supposed to be fast, and the question
# "did the merge reach production" is only open where a policy recently changed.
LIVE_PARITY_WATCH = (
    ("life-platform-qa-smoke", "operational_qa_smoke", "#3573 added ai-canary-log/* to the S3List prefix condition"),
    ("chronicle-email-sender", "email_chronicle_sender", "#3563's PutItem grant lands here"),
    ("life-platform-freshness-checker", "operational_freshness_checker", "#3563's notion LeadingKeys lands here"),
)


def compare_to_live(statements, live_by_sid: dict, label: str = "") -> list:
    """Pure: which checked-in statements are NOT present on the deployed role.

    Statements CDK adds on its own (logs, X-Ray, the DLQ) are out of scope — the question is
    whether every statement THIS REPO declares is deployed, not whether live is minimal."""
    drift = []
    for statement in statements:
        deployed = live_by_sid.get(statement.sid)
        if not deployed:
            drift.append(f"{label}sid {statement.sid!r} is in role_policies and NOT on the live role")
            continue
        actions: set = set()
        resources: set = set()
        conditions: dict = {}
        for d in deployed:
            a, r = d.get("Action"), d.get("Resource")
            actions |= set(a if isinstance(a, list) else [a])
            resources |= set(r if isinstance(r, list) else [r])
            conditions.update(d.get("Condition") or {})
        missing_actions = sorted(set(statement.actions) - actions)
        missing_resources = sorted(set(statement.resources) - resources)
        if missing_actions or missing_resources or conditions != (statement.conditions or {}):
            drift.append(
                f"{label}sid={statement.sid}: actions missing live={missing_actions} "
                f"resources missing live={missing_resources} condition_live={conditions} condition_repo={statement.conditions}"
            )
    return drift


def test_MUTATION_the_live_comparison_reds_on_a_planted_undeployed_grant():
    """The must-fail control for the live leg, with no network: take the REAL qa-smoke S3List
    statement, remove `ai-canary-log/*` from the deployed copy — the exact #3573 state before
    `cdk deploy LifePlatformOperational` — and the comparison must name it."""
    (s3list,) = [st for st in policy_statements("operational_qa_smoke") if st.sid == "S3List"]
    prefixes = s3list.conditions["StringLike"]["s3:prefix"]
    assert "ai-canary-log/*" in prefixes, "#3573's prefix left the checked-in document — re-derive this control"
    predeploy = {
        "S3List": [
            {
                "Sid": "S3List",
                "Action": list(s3list.actions),
                "Resource": list(s3list.resources),
                "Condition": {"StringLike": {"s3:prefix": [p for p in prefixes if p != "ai-canary-log/*"]}},
            }
        ]
    }
    (hit,) = compare_to_live([s3list], predeploy, "qa-smoke ")
    assert "S3List" in hit and "ai-canary-log/*" in hit and "condition_repo" in hit
    ok = {"S3List": [{"Sid": "S3List", "Action": list(s3list.actions), "Resource": list(s3list.resources), "Condition": s3list.conditions}]}
    assert compare_to_live([s3list], ok, "qa-smoke ") == [], "negative control: the deployed document must read clean"
    assert compare_to_live([s3list], {}, "qa-smoke ") == ["qa-smoke sid 'S3List' is in role_policies and NOT on the live role"]


_UNMEASURED = (
    "LIVE IAM PARITY UNMEASURED — the checked-in policy documents were NOT compared to the deployed roles "
    f"{[w[0] for w in LIVE_PARITY_WATCH]}. This is a SKIP, never a pass: run it with read-only credentials via "
    "`python3 -m pytest tests/test_role_family_write_scope.py -m integration -q`."
)


def _loud_skip(reason: str):
    """A skip nobody has to go looking for: the reason is on stdout AND on the skip line."""
    print(f"{_UNMEASURED}\n  because: {reason}")
    pytest.skip(f"{_UNMEASURED} because: {reason}")


def _aws_or_skip():
    try:
        import boto3
        from botocore.session import get_session
    except ImportError:  # pragma: no cover - boto3 is a repo dependency
        _loud_skip("boto3 is not importable in this environment")
    if os.environ.get("AWS_ACCESS_KEY_ID") == "testing":
        # tests/conftest.py forces hermetic fake credentials at import time for the whole unit
        # suite; only the `integration` marker restores the real ones (its own fixture, #2370's
        # neighbour). Without that marker this leg CANNOT reach AWS, and saying so is the point.
        _loud_skip("tests/conftest.py's hermetic fake AWS credentials are in force (the unit-lane default)")
    if get_session().get_credentials() is None:
        _loud_skip("no AWS credentials are configured (CI's unit lane has none by design)")
    return boto3


def test_the_live_parity_leg_states_what_it_did_not_measure(capsys):
    """Always runs, in every lane. The live leg below is `@pytest.mark.integration` — the repo's
    own convention for a test that needs real AWS (pytest.ini; conftest restores the real
    credentials only for that marker) — so in the unit lane it is DESELECTED, which is quieter
    than a skip. This companion is what keeps the open question on the transcript."""
    assert LIVE_PARITY_WATCH, "the live watch list is empty — the leg would be vacuously green"
    for function_name, policy_fn, why in LIVE_PARITY_WATCH:
        assert policy_is_defined(policy_fn) and len(why) > 20
        assert any(e.function_name == function_name for e in ROLE_FAMILY), f"{function_name} is not in the derived family"
    print(_UNMEASURED)
    assert "UNMEASURED" in capsys.readouterr().out


@pytest.mark.integration
def test_live_role_policies_match_the_checked_in_documents():
    """Read-only: lambda:GetFunctionConfiguration -> iam:ListRolePolicies -> iam:GetRolePolicy.

    A merged policy edit is not a deployed one. #3573 merged `ai-canary-log/*` into the qa-smoke
    S3List condition and the grant only becomes real on `bash deploy/cdk_deploy.sh
    LifePlatformOperational`; this leg is what says which side of that the estate is on.
    The comparison itself is `compare_to_live` above, which is mutation-proved offline."""
    boto3 = _aws_or_skip()
    from botocore.exceptions import BotoCoreError, ClientError

    lam = boto3.client("lambda", region_name="us-west-2")
    iam = boto3.client("iam")
    drift = []
    for function_name, policy_fn, why in LIVE_PARITY_WATCH:
        try:
            role_arn = lam.get_function_configuration(FunctionName=function_name)["Role"]
            role_name = role_arn.rsplit("/", 1)[-1]
            policy_names = iam.list_role_policies(RoleName=role_name)["PolicyNames"]
            documents = [iam.get_role_policy(RoleName=role_name, PolicyName=n)["PolicyDocument"] for n in policy_names]
        except (ClientError, BotoCoreError) as exc:
            # An auth/permission failure is "could not look", which is never a pass and never a
            # drift claim either — the same fail-open-but-LOUD shape the closure sweep uses.
            _loud_skip(f"reading {function_name}'s role failed: {type(exc).__name__} {str(exc)[:160]}")
        live: dict = {}
        for document in documents:
            for statement in document.get("Statement", []):
                if statement.get("Sid"):
                    live.setdefault(statement["Sid"], []).append(statement)
        drift += [f"{d} ({why})" for d in compare_to_live(policy_statements(policy_fn), live, f"{function_name} ")]
    assert not drift, "the deployed role does not carry the checked-in document — a merge is not a deploy:\n" + "\n".join(
        f"  {d}" for d in drift
    )
