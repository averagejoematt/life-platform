"""tests/test_reader_input_prefix_3559.py — reader input never lands on a public prefix (#3559, SEC-1).

THE DEFECT
----------
`/api/board_question` and `/api/submit_finding` wrote their moderation records — carrying
the reader's optional `email` and an `ip_hash` — under `generated/`, the prefix the bucket
policy's `PublicReadGenerated` statement grants anonymous `s3:GetObject` on (ADR-046: it is
the CloudFront-served OUTPUT prefix). The key was derivable from the public answers feed.
The owner redacted the five live objects in place on 2026-09-05; this is the structural
half, so the NEXT submission cannot land there.

WHAT IS GUARDED — the SET, not the instance
-------------------------------------------
  1. The public-read prefixes are DERIVED from `deploy/bucket_policy.json` (the file the
     drift sentinel holds the live policy to), never re-typed here.
  2. `web/site_api_capture_store.capture_key()` is the ONE place a reader-input key is
     minted, and every `put_capture_record(...)` call site under `lambdas/` (AST, tree
     sweep) obtains its key from it — a door that builds its own key literal reds this
     before merge (the file is in conftest's pre-merge lane).
  3. The minted prefix is not under any anonymously readable prefix, and is not in the
     `ProtectDataFromDeployScripts` Deny either (the owner must be able to purge a
     moderated record — reader PII is not raw data).
  4. The serve role's `S3FindingsWrite` grant covers exactly the minted prefixes and no
     longer grants PutObject under `generated/` for either door.
  5. The moderation script reads the queue through the same seam.
  6. The records still carry `email` / `ip_hash` — the reason the rule is load-bearing.

Each structural check has a must-fail control below (#3629: a guard arrives proven).
"""

from __future__ import annotations

import ast
import json
import os
import re
import sys
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent
_REPO = _TESTS.parent
if str(_REPO / "lambdas") not in sys.path:
    sys.path.insert(0, str(_REPO / "lambdas"))

from web import site_api_capture_store as store  # noqa: E402

BUCKET_POLICY = _REPO / "deploy" / "bucket_policy.json"
ENGAGE = _REPO / "lambdas" / "web" / "site_api_social_engage.py"
SERVE_ROLE = _REPO / "cdk" / "stacks" / "role_policies_serve.py"
PUBLISH_SCRIPT = _REPO / "scripts" / "publish_board_answer.py"
GOVERNANCE_DOC = _REPO / "docs" / "DATA_GOVERNANCE.md"

_ARN_PREFIX_RE = re.compile(r"arn:aws:s3:::[^/]+/(.+?)/\*$")


# ── 1. the public-read prefixes, derived from the bucket policy ──────────────
def public_read_prefixes(policy: dict) -> set[str]:
    """Every `<prefix>/` an anonymous principal may GetObject under, per the policy."""
    out: set[str] = set()
    for st in policy.get("Statement", []):
        if st.get("Effect") != "Allow":
            continue
        principal = st.get("Principal")
        if not (principal == "*" or (isinstance(principal, dict) and principal.get("AWS") == "*")):
            continue
        actions = st.get("Action") if isinstance(st.get("Action"), list) else [st.get("Action")]
        if not any(a in ("s3:GetObject", "s3:Get*", "s3:*") for a in actions):
            continue
        resources = st.get("Resource") if isinstance(st.get("Resource"), list) else [st.get("Resource")]
        for res in resources:
            m = _ARN_PREFIX_RE.match(str(res))
            if m:
                out.add(m.group(1) + "/")
    return out


def delete_protected_prefixes(policy: dict) -> set[str]:
    out: set[str] = set()
    for st in policy.get("Statement", []):
        if st.get("Effect") != "Deny":
            continue
        resources = st.get("Resource") if isinstance(st.get("Resource"), list) else [st.get("Resource")]
        for res in resources:
            m = _ARN_PREFIX_RE.match(str(res))
            if m:
                out.add(m.group(1) + "/")
    return out


def prefix_problems(key_prefix: str, public: set[str], protected: set[str]) -> list[str]:
    """THE rule, as one function so the controls run the exact code the assertions run."""
    problems = []
    for p in sorted(public):
        if key_prefix.startswith(p):
            problems.append(f"{key_prefix} sits under {p}, which the bucket policy grants anonymous GetObject on")
    for p in sorted(protected):
        if key_prefix.startswith(p):
            problems.append(f"{key_prefix} sits under {p}, a delete-protected prefix — the owner could never purge a moderated record")
    return problems


def _policy() -> dict:
    return json.loads(BUCKET_POLICY.read_text(encoding="utf-8"))


def test_the_bucket_policy_parse_is_not_vacuous():
    public = public_read_prefixes(_policy())
    assert "generated/" in public and "site/" in public, f"the parse must find the two known public prefixes; got {sorted(public)}"
    assert "uploads/" in delete_protected_prefixes(_policy())


@pytest.mark.parametrize("door", sorted(store.CAPTURE_DOORS))
def test_every_door_mints_a_private_purgeable_key(door):
    policy = _policy()
    key = store.capture_key(door, "abc123")
    assert key.startswith(store.READER_INPUT_PREFIX) and key.endswith("/abc123.json")
    assert prefix_problems(store.capture_prefix(door), public_read_prefixes(policy), delete_protected_prefixes(policy)) == []


def test_the_rule_reds_on_the_old_location_and_on_a_widened_policy():
    """Must-fail controls: the pre-#3559 key, and a policy that makes reader_input/ public."""
    policy = _policy()
    public, protected = public_read_prefixes(policy), delete_protected_prefixes(policy)
    for door, legacy in store.LEGACY_CAPTURE_PREFIXES.items():
        assert prefix_problems(legacy, public, protected), f"the old {legacy} must be refused — that is the whole finding"
    widened = json.loads(json.dumps(policy))
    widened["Statement"].append(
        {
            "Sid": "Probe",
            "Effect": "Allow",
            "Principal": "*",
            "Action": "s3:GetObject",
            "Resource": "arn:aws:s3:::matthew-life-platform/reader_input/*",
        }
    )
    assert prefix_problems(store.capture_prefix("board_question"), public_read_prefixes(widened), protected)
    assert prefix_problems("uploads/reader/", public, protected), "a delete-protected prefix is refused too (the issue's first suggestion)"


# ── 2. every put_capture_record call site keys through capture_key ───────────
def capture_call_sites(source: str) -> list[tuple[int, str]]:
    """(lineno, resolution) for every `put_capture_record(...)` call. Resolution is
    'capture_key' when the key argument is a `capture_key(...)` call, or a name bound
    from one in the same function body; otherwise the offending expression."""
    tree = ast.parse(source)
    out: list[tuple[int, str]] = []

    def bindings(fn: ast.AST) -> dict[str, ast.expr]:
        bound: dict[str, ast.expr] = {}
        for node in ast.walk(fn):
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                bound[node.targets[0].id] = node.value
        return bound

    def is_capture_key_call(expr: ast.expr) -> bool:
        if not isinstance(expr, ast.Call):
            return False
        fn = expr.func
        name = fn.id if isinstance(fn, ast.Name) else (fn.attr if isinstance(fn, ast.Attribute) else None)
        return name == "capture_key"

    for fn in [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))] + [tree]:
        bound = bindings(fn) if not isinstance(fn, ast.Module) else {}
        for node in ast.walk(fn):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            name = f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else None)
            if name != "put_capture_record":
                continue
            key_expr = None
            if len(node.args) >= 3:
                key_expr = node.args[2]
            for kw in node.keywords:
                if kw.arg == "key":
                    key_expr = kw.value
            if key_expr is None:
                out.append((node.lineno, "<no key argument>"))
                continue
            if isinstance(key_expr, ast.Name) and key_expr.id in bound:
                key_expr = bound[key_expr.id]
            out.append((node.lineno, "capture_key" if is_capture_key_call(key_expr) else ast.unparse(key_expr)))
    # a nested function is visited once via its own def AND once via the module walk;
    # keep the per-function resolution (which sees the local bindings) and dedupe on line
    seen: dict[int, str] = {}
    for lineno, res in out:
        if lineno not in seen or res == "capture_key":
            seen[lineno] = res
    return sorted(seen.items())


def violations_in_source(source: str) -> list[tuple[int, str]]:
    return [(ln, res) for ln, res in capture_call_sites(source) if res != "capture_key"]


def _lambda_sources():
    for base, dirs, files in os.walk(_REPO / "lambdas"):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for name in sorted(files):
            if name.endswith(".py"):
                path = Path(base) / name
                yield path.relative_to(_REPO).as_posix(), path.read_text(encoding="utf-8")


def test_every_capture_door_in_lambdas_keys_through_the_seam():
    sites, violations = 0, []
    for rel, src in _lambda_sources():
        if "put_capture_record(" not in src or rel.endswith("site_api_capture_store.py"):
            continue
        found = capture_call_sites(src)
        sites += len(found)
        violations += [(rel, ln, res) for ln, res in found if res != "capture_key"]
    assert sites >= len(
        store.CAPTURE_DOORS
    ), f"the sweep found {sites} capture call site(s); the two doors should be there — has the sweep gone blind?"
    assert not violations, "reader-input key(s) minted outside web.site_api_capture_store.capture_key():\n  " + "\n  ".join(
        f"{rel}:{ln} -> {res}" for rel, ln, res in violations
    )


def test_the_call_site_check_reds_on_a_literal_and_on_an_fstring():
    """Must-fail controls: the pre-#3559 shape (a bound f-string) and a bare literal."""
    old_shape = (
        "def h(event):\n"
        '    s3_key = f"generated/findings/{finding_id}.json"\n'
        '    put_capture_record(s3, bucket, s3_key, record, body, door="submit_finding")\n'
    )
    literal = 'put_capture_record(s3, bucket, "generated/board_questions/x.json", record, body, door="board_question")\n'
    good = 'def h(event):\n    s3_key = capture_key("submit_finding", fid)\n    put_capture_record(s3, bucket, s3_key, record, body, door="submit_finding")\n'
    assert len(violations_in_source(old_shape)) == 1 and "generated/findings" in violations_in_source(old_shape)[0][1]
    assert len(violations_in_source(literal)) == 1
    assert violations_in_source(good) == [] and len(capture_call_sites(good)) == 1


# ── 3. the serve role grant follows the seam ─────────────────────────────────
def _joined(expr: ast.expr) -> str:
    """Render an f-string/constant resource with `{BUCKET_ARN}` kept symbolic."""
    if isinstance(expr, ast.Constant):
        return str(expr.value)
    if isinstance(expr, ast.JoinedStr):
        parts = []
        for v in expr.values:
            if isinstance(v, ast.Constant):
                parts.append(str(v.value))
            elif isinstance(v, ast.FormattedValue):
                parts.append("{" + ast.unparse(v.value) + "}")
        return "".join(parts)
    return ast.unparse(expr)


def findings_write_resources(source: str) -> tuple[list[str], list[str]]:
    """(actions, resources) of the `S3FindingsWrite` PolicyStatement in a role-policy module."""
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        kw = {k.arg: k.value for k in node.keywords if k.arg}
        sid = kw.get("sid")
        if not (isinstance(sid, ast.Constant) and sid.value == "S3FindingsWrite"):
            continue
        actions = [_joined(e) for e in getattr(kw.get("actions"), "elts", [])]
        resources = [_joined(e) for e in getattr(kw.get("resources"), "elts", [])]
        return actions, resources
    return [], []


def test_the_serve_role_grants_put_on_exactly_the_minted_prefixes():
    actions, resources = findings_write_resources(SERVE_ROLE.read_text(encoding="utf-8"))
    assert actions == ["s3:PutObject"], f"S3FindingsWrite must be a PutObject-only grant; got {actions}"
    expected = {f"{{BUCKET_ARN}}/{store.capture_prefix(door)}*" for door in store.CAPTURE_DOORS}
    assert set(resources) == expected, f"the grant must be exactly the seam's prefixes: {sorted(expected)}; got {resources}"
    for door, legacy in store.LEGACY_CAPTURE_PREFIXES.items():
        assert not any(legacy in r for r in resources), f"a residual PutObject on {legacy} is the next leak's seam"


def test_the_role_check_reds_on_the_old_grant():
    old = (
        'iam.PolicyStatement(sid="S3FindingsWrite", actions=["s3:PutObject"], '
        'resources=[f"{BUCKET_ARN}/generated/findings/*", f"{BUCKET_ARN}/generated/board_questions/*"])\n'
    )
    actions, resources = findings_write_resources(old)
    assert actions == ["s3:PutObject"] and "{BUCKET_ARN}/generated/findings/*" in resources
    assert set(resources) != {f"{{BUCKET_ARN}}/{store.capture_prefix(d)}*" for d in store.CAPTURE_DOORS}


# ── 4. the readers: the moderation script lists through the seam ─────────────
def test_the_moderation_script_reads_the_queue_through_the_seam():
    tree = ast.parse(PUBLISH_SCRIPT.read_text(encoding="utf-8"))
    assigned = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            assigned[node.targets[0].id] = node.value
    q = assigned.get("QUEUE_PREFIX")
    assert (
        isinstance(q, ast.Call) and getattr(q.func, "id", "") == "capture_prefix"
    ), "QUEUE_PREFIX must be capture_prefix(...), never a literal"
    assert [ast.literal_eval(a) for a in q.args] == ["board_question"]
    legacy = assigned.get("LEGACY_QUEUE_PREFIX")
    assert isinstance(
        legacy, ast.Subscript
    ), "the legacy prefix must be read from LEGACY_CAPTURE_PREFIXES so the pre-move objects stay listed"
    src = PUBLISH_SCRIPT.read_text(encoding="utf-8")
    assert "LEGACY_QUEUE_PREFIX, True" in src, "the listing must walk the legacy prefix too until the owner moves the objects"
    assert "_put_json(queue_key, rec)" in src, "answered-marking writes back to the key it read, never a re-minted key"


# ── 5. the records still carry the fields that make the rule load-bearing ────
def test_both_door_records_carry_email_and_ip_hash():
    tree = ast.parse(ENGAGE.read_text(encoding="utf-8"))
    pii_records = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            keys = {k.value for k in node.keys if isinstance(k, ast.Constant)}
            if {"email", "ip_hash", "status"} <= keys:
                pii_records += 1
    assert pii_records >= len(
        store.CAPTURE_DOORS
    ), "the door records no longer carry email/ip_hash — if that is deliberate, the prefix rule's stated reason changes; say so here"


# ── 6. the governance doc names the prefix ───────────────────────────────────
def test_data_governance_names_the_reader_input_prefix():
    text = GOVERNANCE_DOC.read_text(encoding="utf-8")
    assert f"`{store.READER_INPUT_PREFIX}`" in text, "docs/DATA_GOVERNANCE.md needs the reader_input/ row (#3559 acceptance)"
    assert "#3559" in text
