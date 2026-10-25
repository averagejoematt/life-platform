"""#5220 — every Lambda that reaches the private charter twin loader holds the list grant its role needs.

The twin (`config/coaching/training_charter.private.json`) is OPTIONAL. S3 answers a missing key with 404 only when the
caller may `s3:ListBucket` the prefix; without it the answer is 403 AccessDenied, which `training_charter._from_s3` logs
at WARNING with the literal the `swallowed-permission-denial` alarm filters on -- on every cold start. #5226 granted the
list to the serve/email/compute roles; qa-smoke, coherence-sentinel, ai-quality-canary and site-api were missed.

Walks `create_platform_lambda(source_file=..., custom_policies=rp.<factory>())` in every `cdk/stacks/*_stack.py`, takes
each source's transitive import closure over `lambdas/`, and holds:
  A. a function that reaches `training_charter` AND whose role can GetObject the twin key must also carry the list;
  B. the four functions with a live logged denial (2026-10-24) carry BOTH the GetObject and the list.
Offline: reads repo files and builds policy statements only.
"""

from __future__ import annotations

import ast
import fnmatch
import sys
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "cdk"))

KEY_ARN = "arn:aws:s3:::matthew-life-platform/config/coaching/training_charter.private.json"
# Functions whose CloudWatch logs carried `training_charter.private.json not read (AccessDenied)` on 2026-10-24.
LOGGED_DENIAL = {
    "life-platform-qa-smoke": "operational_qa_smoke",
    "life-platform-coherence-sentinel": "operational_coherence_sentinel",
    "life-platform-ai-quality-canary": "operational_ai_quality_canary",
    "life-platform-site-api": "site_api",
}

MODS = {
    p.stem: p for pkg in sorted((ROOT / "lambdas").iterdir()) if pkg.is_dir() for p in pkg.glob("*.py")
}  # packages are one level (ADR-146)


@lru_cache(maxsize=None)
def _imports(stem: str) -> frozenset:
    out: set = set()
    for n in ast.walk(ast.parse(MODS[stem].read_text())):
        if isinstance(n, ast.Import):
            for a in n.names:
                out.update(a.name.split("."))
        elif isinstance(n, ast.ImportFrom):
            if n.module:
                out.update(n.module.split("."))
            out.update(a.name for a in n.names)
    return frozenset(x for x in out if x in MODS)


@lru_cache(maxsize=None)
def _closure(stem: str) -> frozenset:
    seen: set = set()
    todo = [stem]
    while todo:
        s = todo.pop()
        if s not in seen:
            seen.add(s)
            todo.extend(_imports(s))
    return frozenset(seen)


def _functions():
    """(function_name, source stem, factory name) for every zero-argument custom_policies factory call."""
    rows = []
    for sf in sorted((ROOT / "cdk" / "stacks").glob("*_stack.py")):
        for n in ast.walk(ast.parse(sf.read_text())):
            if not isinstance(n, ast.Call):
                continue
            kw = {k.arg: k.value for k in n.keywords if k.arg}
            cp = kw.get("custom_policies")
            if not (isinstance(kw.get("source_file"), ast.Constant) and isinstance(kw.get("function_name"), ast.Constant)):
                continue
            if isinstance(cp, ast.Call) and isinstance(cp.func, ast.Attribute) and not cp.args:
                rows.append((kw["function_name"].value, Path(kw["source_file"].value).stem, cp.func.attr))
    return rows


def _grants(factory: str):
    from stacks import role_policies as rp

    # `.sid/.actions/.resources` only: sibling tests install a stub PolicyStatement with exactly these (no to_statement_json)
    can_get = can_list = False
    for st in getattr(rp, factory)():
        acts, res = list(st.actions), [str(r) for r in st.resources]
        if any(a in ("s3:GetObject", "s3:*", "*") for a in acts) and any(fnmatch.fnmatch(KEY_ARN, r) for r in res):
            can_get = True
        if st.sid == "CharterTwinList" and "s3:ListBucket" in acts:
            can_list = True
    return can_get, can_list


def test_every_reading_role_that_can_get_the_twin_can_list_it():
    offenders = []
    seen = 0
    for fn, src, factory in _functions():
        if src in MODS and "training_charter" in _closure(src):
            seen += 1
            can_get, can_list = _grants(factory)
            if can_get and not can_list:
                offenders.append(f"{fn} ({factory})")
    assert seen > 20, "the walk found almost no charter readers -- the detector is broken"
    assert not offenders, "charter-reading roles with GetObject on the twin but no CharterTwinList (#5220): " + ", ".join(offenders)


def test_the_four_logged_denial_roles_carry_get_and_list():
    by_fn = {fn: (src, factory) for fn, src, factory in _functions()}
    missing = []
    for fn, factory in LOGGED_DENIAL.items():
        assert fn in by_fn, f"{fn} left the stacks -- retire it from LOGGED_DENIAL"
        assert by_fn[fn][1] == factory
        assert "training_charter" in _closure(by_fn[fn][0]), f"{fn} no longer reaches the loader -- retire it from LOGGED_DENIAL"
        if _grants(factory) != (True, True):
            missing.append(f"{fn}: get/list = {_grants(factory)}")
    assert not missing, "; ".join(missing)


def test_detector_can_fail(monkeypatch):
    """Mutation: strip the list from qa-smoke's factory and the first test's predicate flags it."""
    from stacks import role_policies as rp

    orig = rp.operational_qa_smoke
    monkeypatch.setattr(rp, "operational_qa_smoke", lambda: [s for s in orig() if s.sid != "CharterTwinList"])
    assert _grants("operational_qa_smoke") == (True, False)
