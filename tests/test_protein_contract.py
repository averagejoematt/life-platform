"""tests/test_protein_contract.py — one nutrition-target story on every door.

Two incidents, one contract.

2026-07-01: /data/nutrition hardcoded 190 and the front-end called it the "floor" while
the coaches graded against the real 170 floor — a reader crossing doors saw two truths
with the same word.

2026-10-01 (#4540): the fix for that pinned every door to the SAME profile keys and the
SAME defaults — and the profile row itself was wrong. `PROFILE#v1` held 1,800 kcal /
190 g while the sealed plan (`config/user_goals.json`) says 1,500 kcal and a 170 g
protein floor, so every reader of the row, and every literal default beside it, stated
targets the plan never set. The plan-facts gate could not see it: the figure was in the
prompt, so it was grounded.

The contract now: the plan's two nutrition figures are GENERATED into
`lambdas/common/constants.py` from the plan root, and every consumer under `lambdas/`
and `mcp/` reads them from there — never from the profile row, never from a literal.
The guard below holds the SET (an AST sweep of both trees), not the six sites the issue
happened to name.
"""

import ast
import json
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for _p in (os.path.join(ROOT, "lambdas"), os.path.join(ROOT, "deploy")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

_SERVER = os.path.join(ROOT, "lambdas", "web", "site_api_nutrition.py")
_SWEPT_TREES = ("lambdas", "mcp")

# The profile row's two target fields. A read of either — off anything profile-shaped, or
# with a numeric default off anything at all — is the pre-#4540 shape.
_PROFILE_TARGET_KEYS = {"calorie_target", "protein_target_g"}
# The two figures the row (and the literal defaults beside it) carried. Neither is a plan
# figure, so neither may sit next to a nutrition-target name again.
_STALE_TARGET_FIGURES = {1800, 190}
# What makes a name a nutrition TARGET name: a calorie/protein stem and a target/goal/floor
# word, either order (`cal_target`, `protein_g_target`, `CALORIE_TARGET`, `target_kcal`).
_TARGET_NAME_RE = re.compile(
    r"(?:cal|kcal|protein|prot|pro)[a-z0-9_]*(?:target|goal|floor)|(?:target|goal|floor)[a-z0-9_]*(?:cal|kcal|protein)", re.IGNORECASE
)


def _names_in(node):
    """Every identifier-like token under `node`: names, attributes, keyword args and short
    identifier-shaped strings (dict keys, `.get("…")` keys). Prose strings are not names."""
    out = []
    for n in ast.walk(node):
        if isinstance(n, ast.Name):
            out.append(n.id)
        elif isinstance(n, ast.Attribute):
            out.append(n.attr)
        elif isinstance(n, ast.keyword) and n.arg:
            out.append(n.arg)
        elif isinstance(n, ast.Constant) and isinstance(n.value, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,40}", n.value):
            out.append(n.value)
    return out


def _context(const, parents):
    """The smallest expression that gives a numeric literal its meaning: the call or keyword
    it is an argument of, the dict pair it is the value of, or its simple statement (for a
    compound statement, only the header expression the literal sits in)."""
    child, node = const, parents.get(const)
    while node is not None:
        if isinstance(node, (ast.Call, ast.keyword)):
            return [node]
        if isinstance(node, ast.Dict):
            if child in node.values:
                key = node.keys[node.values.index(child)]
                return [n for n in (key, child) if n is not None]
            return [child]
        if isinstance(node, ast.stmt):
            return [node] if not hasattr(node, "body") else [child]
        child, node = node, parents.get(node)
    return [const]


def target_literal_findings(src, path="<src>"):
    """Findings for one module's source. Two shapes:

    * a READ of a profile target field — `<profile-ish>.get("calorie_target" | "protein_target_g")`,
      or that `.get` off any receiver with a numeric default;
    * a STALE FIGURE — 1800 or 190 as a numeric literal whose context names a nutrition target.
    """
    tree = ast.parse(src)
    parents = {c: p for p in ast.walk(tree) for c in ast.iter_child_nodes(p)}
    found = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value in _PROFILE_TARGET_KEYS
        ):
            receiver = ast.unparse(node.func.value)
            default = node.args[1] if len(node.args) > 1 else None
            numeric_default = isinstance(default, ast.Constant) and isinstance(default.value, (int, float))
            if "prof" in receiver.lower() or numeric_default:
                found.append(f"{path}:{node.lineno}: reads the profile row's {node.args[0].value!r} ({ast.unparse(node)})")
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, (int, float))
            and not isinstance(node.value, bool)
            and node.value in _STALE_TARGET_FIGURES
        ):
            names = [n for ctx in _context(node, parents) for n in _names_in(ctx)]
            hit = next((n for n in names if _TARGET_NAME_RE.search(n)), None)
            if hit:
                found.append(f"{path}:{node.lineno}: literal {node.value!r} beside the nutrition-target name {hit!r}")
    return found


def _swept_modules():
    for tree in _SWEPT_TREES:
        for dirpath, dirnames, filenames in os.walk(os.path.join(ROOT, tree)):
            dirnames[:] = [d for d in dirnames if d != "__pycache__"]
            for name in sorted(filenames):
                if name.endswith(".py"):
                    yield os.path.join(dirpath, name)


def test_no_consumer_reads_the_profile_targets_or_retypes_them():
    """THE SET guard (#4540): nothing under lambdas/ or mcp/ reads the profile row's
    calorie/protein target, and no 1800 / 190 literal sits beside a nutrition-target name.
    One test over the whole tree — every offender is reported, not the first."""
    found, swept = [], 0
    for path in _swept_modules():
        swept += 1
        with open(path, encoding="utf-8") as fh:
            found += target_literal_findings(fh.read(), os.path.relpath(path, ROOT))
    assert swept > 300, f"the sweep walked only {swept} modules — the tree moved or the walk broke"
    assert not found, (
        "nutrition targets come from common.constants (PLAN_DAILY_CALORIES_TARGET / PLAN_DAILY_PROTEIN_MIN_G), "
        "generated from the plan root — not the profile row, not a literal:\n  " + "\n  ".join(found)
    )


def test_the_guard_sees_every_shape_it_exists_for():
    """Fixture-level proof the detector can fail: each line is a shape that shipped."""
    shapes = {
        'cal_target = profile.get("calorie_target", 1800)': 2,  # the read AND the literal default
        "packet.append(f\"Targets: {profile.get('calorie_target', 1800)} cal\")": 2,  # inside an f-string (chronicle_data)
        'protein_g_target = float(profile.get("protein_target_g", 190))': 2,
        'x = (profile or {}).get("protein_target_g", PROTEIN_TARGET_G)': 1,  # a named fallback is still a profile read
        'pro = p.get("protein_target_g", 190)': 2,  # receiver not named profile — the numeric default gives it away
        "fact = f\"target {int(facts.get('protein_g_target') or 190)} g\"": 1,
        "cal_target = 1800  # overridden by profile in caller": 1,
        "_PROTEIN_TARGET_FALLBACK_G = 190.0": 1,
        "CALORIE_TARGET = 1800": 1,
        'row = {"calorie_target": 1800}': 1,
        "render(calorie_target=1800)": 1,
        "if cal_target == 1800:\n    pass": 1,
    }
    for src, n in shapes.items():
        got = target_literal_findings(src)
        assert len(got) == n, f"{src!r}: expected {n} finding(s), got {got}"
    clean = [
        "from common.constants import PLAN_DAILY_CALORIES_TARGET\ncal_target = PLAN_DAILY_CALORIES_TARGET",
        'calorie_target = args.get("calorie_target")',  # an MCP tool's own override argument
        'label = m.get("calorie_target")',  # a derived metrics dict, not the profile row
        "setTimeout = 1800\nweight_lbs = 190",  # the figures alone are not a nutrition target
        'note = "the profile once said 1,800 kcal / 190 g protein target"',  # prose is not a literal
    ]
    for src in clean:
        assert target_literal_findings(src) == [], src


def test_generated_constants_are_the_plan_root():
    """The bundle's two figures ARE the plan's: equal to `plan_facts` over the plan root,
    and byte-identical to what the generator renders (a hand edit of either side fails)."""
    import sync_constants_from_config as gen
    from common import constants
    from experiment import plan_facts

    with open(os.path.join(ROOT, "config", "user_goals.json"), encoding="utf-8") as fh:
        goals = json.load(fh)
    facts = plan_facts.plan_facts_from_goals(goals)
    assert constants.PLAN_DAILY_CALORIES_TARGET == facts["daily_calories_target"]
    assert constants.PLAN_DAILY_PROTEIN_MIN_G == facts["daily_protein_min_g"]
    with open(os.path.join(ROOT, "lambdas", "common", "constants.py"), encoding="utf-8") as fh:
        assert fh.read() == gen.render(goals), "constants.py drifted — python3 deploy/sync_constants_from_config.py --apply"


def test_producer_and_serving_layer_tell_one_protein_story():
    """canonical_facts' producer and the nutrition door both carry the plan's floor on
    BOTH protein lines — the plan states one line, so neither may invent a second."""
    import importlib

    from common import constants

    scoring = importlib.import_module("health.scoring_engine")
    _, details = scoring.score_nutrition(
        {"macrofactor": {"total_protein_g": constants.PLAN_DAILY_PROTEIN_MIN_G}}, {"protein_target_g": 190}
    )
    assert details["protein_target"] == constants.PLAN_DAILY_PROTEIN_MIN_G
    assert details["protein_score"] == 100, "a day AT the plan's floor has met the plan"
    with open(os.path.join(ROOT, "lambdas", "compute", "daily_metrics_compute_lambda.py"), encoding="utf-8") as fh:
        producer = fh.read()
    assert "protein_g_target = float(PLAN_DAILY_PROTEIN_MIN_G)" in producer
    assert "protein_g_floor = float(PLAN_DAILY_PROTEIN_MIN_G)" in producer
    with open(_SERVER, encoding="utf-8") as fh:
        assert "protein_target = protein_floor = float(PLAN_DAILY_PROTEIN_MIN_G)" in fh.read()


def test_floor_served_as_its_own_field():
    with open(_SERVER, encoding="utf-8") as f:
        src = f.read()
    for field in ('"protein_floor_g"', '"protein_floor_hit_pct"'):
        assert field in src, f"nutrition_overview must serve {field}"
