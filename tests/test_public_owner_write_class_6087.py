"""tests/test_public_owner_write_class_6087.py — no Site API door reachable without the owner token
writes an owner partition (`USER#matthew#SOURCE#*`), outside a short named allow-list (#6087).

The specimen: `POST /api/challenge_checkin` read-modified-wrote `USER#matthew#SOURCE#challenges`, so an
anonymous caller could replace the owner's own check-in. The CLASS is "a public door that writes into an
owner partition", and it is guarded on two legs, because either alone has a blind spot:

  CODE  Every function in the Site API handler family (`lambdas/web/site_api*.py` — where every route body
        lives) that contains a DynamoDB write AND names an owner partition (a `#SOURCE#<name>` pk-form or a
        `USER_PREFIX` join, in its body or through a module-level constant) must either verify an owner token
        in that same function (a call to `verify_*token`) or be on ALLOWED_PUBLIC_OWNER_WRITES with a reason.
        The pk-form detector is the one tests/test_site_partition_orphans.py already uses.
  IAM   The Site API role's DynamoDB write LeadingKeys may name an owner partition only if a gated function
        writes it or it is an allow-listed queue. IAM is the boundary a code path cannot route around: a
        library writer reached from a handler (which the code leg cannot see) is still AccessDenied.

The route table (`site_api_lambda._SIMPLE_ROUTES`) keeps the allow-list honest: every entry must be a
routed POST handler that really writes the partition it names. Both legs carry a planted-violation
control (the pre-#6087 handler shape, run through the same detector) so neither can pass by going blind.
"""

from __future__ import annotations

import ast
import os
import re
import sys
from fnmatch import fnmatch
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "lambdas" / "web"
for _p in (str(ROOT / "lambdas"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
for _k, _v in (("TABLE_NAME", "life-platform"), ("AWS_REGION", "us-west-2"), ("AWS_DEFAULT_REGION", "us-west-2"), ("USER_ID", "matthew")):
    os.environ.setdefault(_k, _v)

from test_site_api_write_scope import _site_api_leadingkeys  # noqa: E402
from test_site_partition_orphans import _pkform_tokens  # noqa: E402

OWNER_PK_PREFIX = "USER#matthew#SOURCE#"
WRITE_CALLS = frozenset({"put_item", "update_item", "delete_item", "batch_write_item", "transact_write_items", "batch_writer"})
_GATE_CALL = re.compile(r"^verify_\w*token$")

# (module file, function) -> (the owner partitions it writes, why a public caller may write them).
# Short on purpose. Both are PENDING QUEUES no engine reads: nothing in the owner's experiment record,
# grading or narrative consumes them, so a reader row there cannot alter an owner observation. Moving them
# out of `USER#matthew#SOURCE#*` is a follow-up (the #6087 Set's other two members), not this fix.
ALLOWED_PUBLIC_OWNER_WRITES = {
    ("site_api_social_experiments.py", "_handle_experiment_suggest"): (
        {"experiment_suggestions"},
        "reader experiment ideas, conditional put, status 'pending' — a moderation queue with no consumer",
    ),
    ("site_api_social_engage.py", "_handle_page_feedback"): (
        {"reader_feedback"},
        "the two-question page-feedback door (#4182) — a queue the owner reads by hand; no engine consumes it",
    ),
}


def _module_owner_constants(tree: ast.Module) -> dict:
    """Module-level names bound to an owner pk-form, e.g. `SUBSCRIBERS_PK = f"USER#{USER_ID}#SOURCE#subscribers"`."""
    out = {}
    for node in tree.body:
        targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
        value = getattr(node, "value", None)
        if value is None:
            continue
        tokens = _pkform_tokens(value)
        for t in targets:
            if isinstance(t, ast.Name) and tokens:
                out[t.id] = tokens
    return out


def _body_without_docstring(fn) -> list:
    body = fn.body
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
        return body[1:]
    return body


def _call_name(call: ast.Call) -> str:
    f = call.func
    return f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""


def owner_writing_functions(source: str) -> dict:
    """{function name: (owner partitions named, owner-token gated?)} for every function that WRITES and names
    an owner partition. Pure over source text, so the planted controls run through the very same code."""
    tree = ast.parse(source)
    constants = _module_owner_constants(tree)
    out = {}
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call)]
        if not any(isinstance(c.func, ast.Attribute) and c.func.attr in WRITE_CALLS for c in calls):
            continue
        tokens: set = set()
        for stmt in _body_without_docstring(fn):
            tokens |= _pkform_tokens(stmt)
            for n in ast.walk(stmt):
                if isinstance(n, ast.Name) and n.id in constants:
                    tokens |= constants[n.id]
        if tokens:
            out[fn.name] = (tokens, any(_GATE_CALL.match(_call_name(c)) for c in calls))
    return out


def _family() -> list:
    return sorted(WEB.glob("site_api*.py"))


def _census() -> dict:
    """{(file, function): (partitions, gated)} over the real handler family."""
    out = {}
    for path in _family():
        for name, val in owner_writing_functions(path.read_text(encoding="utf-8")).items():
            out[(path.name, name)] = val
    return out


def _violations(census: dict, allowed: dict) -> list:
    bad = []
    for key, (parts, gated) in sorted(census.items()):
        if gated:
            continue
        allowed_parts = allowed.get(key, (set(), ""))[0]
        if not parts <= allowed_parts:
            bad.append(f"{key[0]}::{key[1]} writes {sorted(parts - allowed_parts)} with no owner-token check")
    return bad


# ── the CODE leg ──────────────────────────────────────────────────────────────


def test_no_public_site_api_door_writes_an_owner_partition():
    bad = _violations(_census(), ALLOWED_PUBLIC_OWNER_WRITES)
    assert not bad, (
        "A Site API function reachable without the owner token writes an owner partition (#6087). Store reader "
        "input in a reader partition (see common/challenge_checkins.py), gate the write on an owner token, or — "
        "only for a queue no engine reads — add it to ALLOWED_PUBLIC_OWNER_WRITES with a reason:\n  " + "\n  ".join(bad)
    )


def test_the_census_is_not_vacuous():
    """The detector must see today's real owner writes — the two gated doors and the two allow-listed queues —
    or the guard above would pass by finding nothing."""
    census = _census()
    assert census.get(("site_api_social_note.py", "_handle_morning_note"), (None, None))[1] is True
    assert census.get(("site_api_social_engage.py", "_handle_ritual_log"), (None, None))[1] is True
    for key, (parts, _why) in ALLOWED_PUBLIC_OWNER_WRITES.items():
        assert key in census, f"allow-list entry {key} no longer writes an owner partition — prune it"
        assert census[key][0] == parts and census[key][1] is False, (key, census[key])


def test_every_allow_listed_door_is_a_routed_post_handler():
    """The route table half: an allow-list entry names a door the public can actually reach."""
    from web import site_api_lambda as router

    routed = {getattr(fn, "__name__", ""): methods for _path, (methods, fn) in router._SIMPLE_ROUTES.items()}
    for (_file, fn), (_parts, why) in ALLOWED_PUBLIC_OWNER_WRITES.items():
        assert why.strip(), f"{fn}: an allow-list entry needs its reason"
        assert "POST" in (routed.get(fn) or set()), f"{fn} is not a routed POST handler — prune the allow-list entry"
    assert "POST" in routed.get("_handle_challenge_checkin", set()), "the #6087 specimen door must stay in the sweep's view"


# ── the IAM leg ───────────────────────────────────────────────────────────────


def _iam_violations(patterns: set, census: dict, allowed: dict) -> list:
    permitted = {OWNER_PK_PREFIX + p for (_k, (parts, gated)) in census.items() if gated for p in parts}
    permitted |= {OWNER_PK_PREFIX + p for (parts, _why) in allowed.values() for p in parts}
    owner_like = [p for p in patterns if fnmatch(OWNER_PK_PREFIX + "x", p) or p.startswith("USER#")]
    return sorted(p for p in owner_like if p not in permitted)


def test_the_site_api_role_writes_no_owner_partition_a_public_door_could_reach():
    bad = _iam_violations(_site_api_leadingkeys(), _census(), ALLOWED_PUBLIC_OWNER_WRITES)
    assert not bad, f"site-api LeadingKeys grant owner partitions no gated door or allow-listed queue writes: {bad}"


# ── planted-violation controls (each runs the REAL detector) ──────────────────

_PRE_6087_SHAPE = '''
def _handle_challenge_checkin(event, *, _g):
    """POST door."""
    table = _g["table"]
    challenges_pk = f"USER#{USER_ID}#SOURCE#challenges"
    item = table.get_item(Key={"pk": challenges_pk, "sk": "CHALLENGE#x"}).get("Item")
    table.update_item(Key={"pk": challenges_pk, "sk": "CHALLENGE#x"}, UpdateExpression="SET daily_checkins = :cl")
'''

_CONSTANT_SHAPE = """
OWNER_PK = f"USER#{USER_ID}#SOURCE#challenges"

def _door(event, *, _g):
    _g["table"].put_item(Item={"pk": OWNER_PK, "sk": "x"})
"""

_GATED_SHAPE = """
def _door(event, *, _g):
    if not verify_owner_token(secret, day, token):
        return None
    _g["table"].put_item(Item={"pk": f"{USER_PREFIX}challenges", "sk": "x"})
"""


def test_control_the_pre_6087_handler_is_caught():
    census = {("planted.py", k): v for k, v in owner_writing_functions(_PRE_6087_SHAPE).items()}
    assert census == {("planted.py", "_handle_challenge_checkin"): ({"challenges"}, False)}
    assert _violations(census, ALLOWED_PUBLIC_OWNER_WRITES), "the pre-#6087 shape must red the code leg"


def test_control_a_pk_hoisted_to_a_module_constant_is_still_caught():
    census = {("planted.py", k): v for k, v in owner_writing_functions(_CONSTANT_SHAPE).items()}
    assert _violations(census, ALLOWED_PUBLIC_OWNER_WRITES), census


def test_control_an_owner_token_gate_clears_the_same_write():
    census = {("planted.py", k): v for k, v in owner_writing_functions(_GATED_SHAPE).items()}
    assert census == {("planted.py", "_door"): ({"challenges"}, True)} and not _violations(census, {})


def test_control_the_iam_leg_catches_the_old_grant():
    old = _site_api_leadingkeys() | {"USER#matthew#SOURCE#challenges"}
    assert _iam_violations(old, _census(), ALLOWED_PUBLIC_OWNER_WRITES) == ["USER#matthew#SOURCE#challenges"]
    assert _iam_violations({"USER#*"}, _census(), ALLOWED_PUBLIC_OWNER_WRITES) == ["USER#*"]


# premerge-gate: structural gate that sweeps lambdas/web/site_api*.py and the CDK role family (#2372)
