"""tests/test_coach_identity_drift_2757.py — #2757's derivation guard.

THE LIVE FAILURE. `/api/coach_analysis?domain=nutrition` served `coach_color
'#10b981'` (layne_norton's pre-roster-v2 color) while `/api/coaches` — registry-
derived — served `'#22c55e'`. `config/personas.json` agreed with the registry, not
with `/api/coach_analysis`. The cause: `lambdas/web/site_api_coach_narrative.py`,
`lambdas/coach/coach_observatory_renderer.py` and `lambdas/web/site_api_lambda.py`
(the `/api/coaching-dashboard` handler) each carried their OWN hand-typed
`{coach_id: {"title": ..., "color": ...}}` map — three copies of the same
vocabulary, silently forked from `config/personas.json` and from each other.
Mind coach's color happened to match everywhere, which is exactly why the drift
went unnoticed: it is per-coach, not all-or-nothing.

THE FIX (charter primitive 1 — a vocabulary owned in two places forks; one must
derive). `persona_registry.display_map()` already computed `title` (falling back
to `board_role`) and `color` per persona — it just wasn't being used for those
fields, because each of the three files re-typed its own copy on top of it. All
three now use `display_map()`'s title/color directly; nothing overrides them.
`site_api_lambda.py`'s `observatory_link` field survives as a small local ROUTING
map (which page a domain's card links to) — that's not persona identity, so it
does not belong in the registry.

THIS FILE (charter primitive 2 — guard the SET, not the instance):

  1. An AST shape scanner over every `.py` file under `lambdas/` for the exact
     defect shape — a dict literal keyed by a coach/persona id whose value is
     itself a literal dict carrying hard-coded string `"title"` AND `"color"`
     entries. This fires on a reintroduced copy ANYWHERE in the tree, not just
     the three named files, and is proven with mutation evidence (a planted copy
     of the actual retired `_style` dict is shown to trip it).
  2. Behavioral proof, invoking the real handlers (fixture must be the wire):
     `/api/coach_analysis`, `coach_observatory_renderer.COACH_DISPLAY`, and
     `/api/coaching-dashboard` (via `lambda_handler`, exercised exactly as
     `tests/test_route_metric_coverage_2876.py` already does — DynamoDB reads
     fail offline and are individually try/except-guarded, so the response is a
     real 200 built from the registry-derived roster) all serve identical
     title/color per coach, equal to `persona_registry.display_map()` — the
     issue's own repro (coach_analysis vs /api/coaches), reproduced in-repo.
"""

from __future__ import annotations

import ast
import json
import os
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "lambdas"))
sys.path.insert(0, str(_REPO))

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")

from coach import persona_registry  # noqa: E402

# The three files the issue named — kept as an explicit assertion target so a
# regression in any ONE of them reads as itself, on top of the tree-wide scan.
NAMED_FILES = (
    "lambdas/web/site_api_coach_narrative.py",
    "lambdas/coach/coach_observatory_renderer.py",
    "lambdas/web/site_api_lambda.py",
)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. AST shape guard — "guard the SET, not the instance"
# ═══════════════════════════════════════════════════════════════════════════════


def _persona_style_literal_offenders(pyfile: Path) -> list[tuple[str, int]]:
    """(persona_key, lineno) for every dict literal shaped like the #2757 defect:
    a string-constant key that names a coach/persona, mapped to a nested dict
    literal carrying hard-coded string `"title"` AND `"color"` entries.

    This is a SHAPE assertion, not a value comparison — a future hand-typed copy
    fails here even if its values happen to agree with the registry today (a
    copy-paste that starts correct and drifts tomorrow is the exact #2757 story).
    """
    tree = ast.parse(pyfile.read_text(encoding="utf-8"), filename=str(pyfile))
    offenders: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for k, v in zip(node.keys, node.values):
            if not (isinstance(k, ast.Constant) and isinstance(k.value, str)):
                continue
            if not isinstance(v, ast.Dict):
                continue
            literal_str_keys = {
                vk.value
                for vk, vv in zip(v.keys, v.values)
                if isinstance(vk, ast.Constant) and isinstance(vk.value, str) and isinstance(vv, ast.Constant) and isinstance(vv.value, str)
            }
            if {"title", "color"} <= literal_str_keys:
                offenders.append((k.value, node.lineno))
    return offenders


def _all_lambda_modules() -> list[Path]:
    return sorted((_REPO / "lambdas").rglob("*.py"))


def test_scan_set_is_not_empty():
    """An empty scan set would validate nothing while reporting green (#1908/#1920
    shape)."""
    modules = _all_lambda_modules()
    assert len(modules) >= 50, f"only {len(modules)} modules discovered — the scan collapsed"
    names = {str(p.relative_to(_REPO)) for p in modules}
    for f in NAMED_FILES:
        assert f in names, f"{f} left the scan set — the guard no longer covers its own incident"


@pytest.mark.parametrize("pyfile", _all_lambda_modules(), ids=lambda p: str(p.relative_to(_REPO)))
def test_no_lambda_module_hardcodes_a_persona_title_color_map(pyfile):
    """Tree-wide: no `.py` file under lambdas/ carries a hand-typed
    `{persona_id: {"title": ..., "color": ...}}` map — the vocabulary is owned by
    `persona_registry.display_map()` and every consumer must derive."""
    offenders = _persona_style_literal_offenders(pyfile)
    assert not offenders, (
        f"{pyfile.relative_to(_REPO)}: hard-coded persona title/color literal(s) at "
        f"{offenders} — derive from coach.persona_registry.display_map() instead (#2757)"
    )


def test_guard_catches_the_actual_retired_shape():
    """Mutation evidence: the EXACT dict this PR deleted from
    site_api_coach_narrative.py must trip the scanner, proving it is not a guard on
    nothing."""
    retired_style_src = """
_style = {
    "sleep_coach": {"title": "Sleep & Circadian Rhythm Specialist", "color": "#818cf8"},
    "nutrition_coach": {"title": "Evidence-Based Nutrition", "color": "#10b981"},
}
"""
    tree = ast.parse(retired_style_src)
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for k, v in zip(node.keys, node.values):
            if not (isinstance(k, ast.Constant) and isinstance(k.value, str)):
                continue
            if not isinstance(v, ast.Dict):
                continue
            literal_str_keys = {
                vk.value
                for vk, vv in zip(v.keys, v.values)
                if isinstance(vk, ast.Constant) and isinstance(vk.value, str) and isinstance(vv, ast.Constant) and isinstance(vv.value, str)
            }
            if {"title", "color"} <= literal_str_keys:
                offenders.append((k.value, node.lineno))
    # Both entries live in the same outer dict literal, so both report that
    # literal's own opening line (2) — the node the AST attributes them to.
    assert offenders == [
        ("sleep_coach", 2),
        ("nutrition_coach", 2),
    ], f"the guard's own detector did not fire on the exact retired shape: {offenders}"


def test_guard_does_not_flag_the_fixed_shape():
    """Negative control: a routing-only map (site_api_lambda.py's surviving
    `_cd_observatory_link`) and a plain string->string map must NOT trip the
    scanner — it targets nested title+color dicts specifically."""
    fine_src = """
_cd_observatory_link = {
    "sleep": "/sleep/",
    "nutrition": "/nutrition/",
}
_cd_names = {"sleep_coach": {"name": "Dr. Lisa Park", "initials": "LP"}}
"""
    tree = ast.parse(fine_src)
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for k, v in zip(node.keys, node.values):
            if not (isinstance(k, ast.Constant) and isinstance(k.value, str)):
                continue
            if not isinstance(v, ast.Dict):
                continue
            literal_str_keys = {
                vk.value
                for vk, vv in zip(v.keys, v.values)
                if isinstance(vk, ast.Constant) and isinstance(vk.value, str) and isinstance(vv, ast.Constant) and isinstance(vv.value, str)
            }
            if {"title", "color"} <= literal_str_keys:
                offenders.append((k.value, node.lineno))
    assert offenders == [], f"a routing-only / identity-free map falsely tripped the guard: {offenders}"


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Behavioral proof — the real handlers, invoked, agree with the registry
# ═══════════════════════════════════════════════════════════════════════════════


def _registry_style(coach_id: str) -> tuple[str, str]:
    d = persona_registry.display_map(include=("operational", "retired")).get(coach_id) or {}
    return d.get("title", ""), d.get("color", "")


def test_registry_display_map_is_the_source_of_the_repro_values():
    """Pins the exact live drift the issue reported has actually been closed AT
    THE SOURCE: the registry (which /api/coaches always read) carries the fixed
    values, not the stale pre-roster-v2 ones."""
    title, color = _registry_style("nutrition_coach")
    assert color == "#22c55e", f"nutrition_coach registry color drifted from the issue's stated fix value: {color}"
    assert color != "#10b981", "nutrition_coach registry color regressed to the retired layne_norton palette value"
    _, sleep_color = _registry_style("sleep_coach")
    assert sleep_color == "#8b5cf6"
    assert sleep_color != "#818cf8"


def test_coach_observatory_renderer_derives_from_the_registry():
    import coach_observatory_renderer as cobs

    for coach_id in persona_registry.OPERATIONAL_COACH_IDS + ["training_coach"]:
        expected_title, expected_color = _registry_style(coach_id)
        got = cobs.COACH_DISPLAY.get(coach_id, {})
        assert got.get("title") == expected_title, f"{coach_id}: observatory title drifted from the registry"
        assert got.get("color") == expected_color, f"{coach_id}: observatory color drifted from the registry"


def _fake_query_first_call_only(item):
    """table.query stub: the first call (the OUTPUT# lookup) returns `item`; every
    later call (threads/ensemble/computation/learning, each individually
    try/except-wrapped in handle_coach_analysis) raises, exercising the fail-soft
    fallback for those secondary reads. Same shape as tests/test_coaches_api.py's
    helper of the same name — a real OUTPUT# record is required to reach the
    coach_color/coach_title fields at all (an empty read short-circuits to a
    shaped-empty response with no style fields, before the drift this issue fixed
    would even be observable)."""
    calls = {"n": 0}

    def _query(**kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"Items": [item]}
        raise RuntimeError("offline test — no secondary reads")

    return _query


def _out_item(coach_id: str) -> dict:
    return {
        "pk": f"COACH#{coach_id}",
        "sk": "OUTPUT#2026-08-19",
        "content": "the analysis text",
        "generated_at": "2026-08-19T14:00:00Z",
    }


def test_coach_analysis_endpoint_matches_the_registry_not_the_stale_palette(monkeypatch):
    """The issue's own repro, reproduced in-repo: /api/coach_analysis must serve
    the SAME color the registry (and therefore /api/coaches) serves."""
    from web import site_api_coach as api

    for domain, coach_id in (("nutrition", "nutrition_coach"), ("sleep", "sleep_coach")):
        monkeypatch.setattr(api.table, "query", _fake_query_first_call_only(_out_item(coach_id)))
        monkeypatch.setattr(api.table, "get_item", lambda Key: {})
        resp = api.handle_coach_analysis({"queryStringParameters": {"domain": domain}})
        assert resp["statusCode"] == 200, resp
        body = json.loads(resp["body"])
        expected_title, expected_color = _registry_style(coach_id)
        assert body["coach_color"] == expected_color, f"{domain}: coach_analysis color has drifted from the registry again"
        assert body["coach_title"] == expected_title, f"{domain}: coach_analysis title has drifted from the registry again"

    # The exact repro values named in #2757.
    monkeypatch.setattr(api.table, "query", _fake_query_first_call_only(_out_item("nutrition_coach")))
    monkeypatch.setattr(api.table, "get_item", lambda Key: {})
    resp = api.handle_coach_analysis({"queryStringParameters": {"domain": "nutrition"}})
    body = json.loads(resp["body"])
    assert body["coach_color"] == "#22c55e"
    assert body["coach_color"] != "#10b981"


def _dashboard_event() -> dict:
    return {
        "rawPath": "/api/coaching-dashboard",
        "requestContext": {"http": {"method": "GET", "sourceIp": "203.0.113.9"}},
        "queryStringParameters": {},
        "headers": {},
    }


def test_coaching_dashboard_coaches_match_the_registry():
    """`/api/coaching-dashboard` (site_api_lambda.py, the third historically-
    divergent map) must also derive title/color from the registry, and must keep
    serving `observatory_link` (a routing fact, not identity) for each domain."""
    from web import site_api_lambda as L

    resp = L.lambda_handler(_dashboard_event(), None)
    assert resp["statusCode"] == 200, resp
    body = json.loads(resp["body"])
    coaches = {c["coach_id"]: c for c in body["coaches"]}
    assert set(coaches) == set(persona_registry.OPERATIONAL_SHORT_IDS)
    for short_id, entry in coaches.items():
        coach_id = f"{short_id}_coach"
        expected_title, expected_color = _registry_style(coach_id)
        assert entry["title"] == expected_title, f"{short_id}: dashboard title has drifted from the registry"
        assert entry["color"] == expected_color, f"{short_id}: dashboard color has drifted from the registry"
        assert entry["observatory_link"] == f"/{short_id}/", f"{short_id}: observatory_link routing broke"

    assert coaches["nutrition"]["color"] == "#22c55e"
    assert coaches["nutrition"]["color"] != "#10b981"


def test_the_three_surfaces_agree_with_each_other_not_just_with_the_registry(monkeypatch):
    """The issue's actual complaint: the SAME coach must render the SAME color on
    every live page — not merely that each independently matches the registry
    (which could still disagree with each other under a bug in the shared
    helper). Cross-checks all three surfaces pairwise."""
    import coach_observatory_renderer as cobs
    from web import site_api_coach as api, site_api_lambda as L

    dash_resp = L.lambda_handler(_dashboard_event(), None)
    dash_coaches = {c["coach_id"]: c for c in json.loads(dash_resp["body"])["coaches"]}

    for domain, coach_id, short_id in (
        ("nutrition", "nutrition_coach", "nutrition"),
        ("sleep", "sleep_coach", "sleep"),
        ("mind", "mind_coach", "mind"),
        ("physical", "physical_coach", "physical"),
        ("glucose", "glucose_coach", "glucose"),
        ("labs", "labs_coach", "labs"),
        ("explorer", "explorer_coach", "explorer"),
    ):
        monkeypatch.setattr(api.table, "query", _fake_query_first_call_only(_out_item(coach_id)))
        monkeypatch.setattr(api.table, "get_item", lambda Key: {})
        analysis_resp = api.handle_coach_analysis({"queryStringParameters": {"domain": domain}})
        analysis_body = json.loads(analysis_resp["body"])
        obs = cobs.COACH_DISPLAY[coach_id]
        dash = dash_coaches[short_id]

        assert analysis_body["coach_color"] == obs["color"] == dash["color"], (
            f"{coach_id}: color disagrees across surfaces — "
            f"coach_analysis={analysis_body['coach_color']!r} observatory={obs['color']!r} dashboard={dash['color']!r}"
        )
        assert analysis_body["coach_title"] == obs["title"] == dash["title"], (
            f"{coach_id}: title disagrees across surfaces — "
            f"coach_analysis={analysis_body['coach_title']!r} observatory={obs['title']!r} dashboard={dash['title']!r}"
        )
