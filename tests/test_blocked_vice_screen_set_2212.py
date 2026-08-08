"""tests/test_blocked_vice_screen_set_2212.py — #2212: the `_is_blocked_vice` screen SET
is unguarded across the habits/social/mind serving paths.

`_is_blocked_vice` (web.site_api_common) is called at every point that decides whether
a vice/habit name may reach a public response. The issue's own sweep hand-enumerated
6 call sites and found 4+ survived full-suite mutation with the screen deleted; this
suite instead DERIVES the set by an AST walk over lambdas/web/ (no hardcoded module
list — a new call site reds AC1 below automatically, the same shape PR #2210 used for
the food_delivery flag and #2211/#2230 used for a single function's screen set) and
found the true count is 11, not 6 — five more call sites the original sweep never
named: site_api_habits.py:87 (_absorb_reflection), site_api_social.py:1143 (challenge
catalog overlay) and :1691 (board_question, already covered — see below),
site_api_mind.py:182 and :300 (mind_overview's two vice surfaces).

Structure:
  AC1  guard the SET — every derived call site sits inside a real exclusion (an `if`
       whose body drops/rejects, or a comprehension filter), so a call site with no
       enclosing exclusion at all reds immediately, and a NEW call site added later
       (a 12th) reds the non-vacuous count pin below until it's given the same
       treatment.
  AC2  behavioral, mutation-provable coverage for every site that had none:
       site_api_habits.py:87/227/325/669, site_api_social.py:1115/1143,
       site_api_mind.py:182/300. Each was manually neutered (source line commented
       out), the specific test below run and shown RED, then restored and shown
       GREEN — see the PR body for the transcript (redacted).
  AC3  site_api_data.py:222 (_habits_from_habitify) and site_api_social.py:1691
       (_handle_board_question) already had behavioral coverage before this issue —
       tests/test_evidence_catalog.py and tests/test_reader_engagement.py respectively.
       Re-verified by the same neuter/restore process; no new test added for these two.
  AC3b #2238 added the 12th and 13th sites — the check-in `note` screen at the write
       door (`_handle_challenge_checkin`) and at the read door (`_screened_note`, reached
       from `handle_challenges` via `_public_checkins`). Both satisfy AC1 structurally;
       both are behaviourally mutation-proved in tests/test_site_api_social_behavior.py
       (which owns this module's handler fixtures), same disposition as AC3.
  AC4  site_api_habits.py:241 (vice_streaks' `latest_vs` map) is structurally guarded
       (AC1) but is a genuine EQUIVALENT MUTANT today: `latest_vs` is only ever used as
       `.get(vice_name, ...)` for `vice_name` drawn from `vice_history` — which line 227
       already filters — so a blocked key surviving *inside* `latest_vs` is never looked
       up and never reaches any response field. Removing :241 alone changes no observable
       output; only removing BOTH :227 and :241 together does. This is proven, not
       assumed — see the PR body's three-way mutation transcript for this pair.

Privacy note (public repo, permanent history): no real blocked term is ever written as a
source literal here. Every fixture loads the live vocabulary from
config/content_filter.json at test time (the #2203/#2230/#2211 technique) and builds a
throwaway habit/vice/challenge name around it; the literal never appears in this file's
text, only in values computed at runtime.
"""

from __future__ import annotations

import ast
import json
import os
import sys
from pathlib import Path

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")

from fakes import FakeDdbTable  # noqa: E402
from web import (
    site_api_common as common,  # noqa: E402
    site_api_habits as habits_mod,  # noqa: E402
    site_api_mind as mind_mod,  # noqa: E402
    site_api_social as social,  # noqa: E402
)

ROOT = Path(_REPO)
WEB = ROOT / "lambdas" / "web"
USER_ID = os.environ["USER_ID"]

# ---------------------------------------------------------------------------
# Shared: load the REAL blocked vocabulary at test time — never a source literal.
# ---------------------------------------------------------------------------


def _cf() -> dict:
    with open(ROOT / "config" / "content_filter.json", encoding="utf-8") as f:
        return json.load(f)


def _pin_content_filter(monkeypatch) -> dict:
    """Pin common._content_filter_cache to the REAL config on disk (not the
    hardcoded fallback, not a synthetic dict) so every _is_blocked_vice() call in
    every web module — they all share this one module-level cache — resolves
    against the live vocabulary. `_content_filter_cache_at=None` is the
    documented "pinned, never expires" test-injection convention."""
    cf = _cf()
    monkeypatch.setattr(common, "_content_filter_cache", dict(cf))
    monkeypatch.setattr(common, "_content_filter_cache_at", None)
    return cf


def _blocked_keyword() -> str:
    """One real keyword from blocked_vice_keywords, loaded live — a substring
    match against this string alone is enough to trip _is_blocked_vice."""
    cf = _cf()
    return cf["blocked_vice_keywords"][0]


def _name_with_blocked_keyword(prefix: str) -> str:
    """A throwaway habit/vice/challenge display name built AROUND the real
    keyword at runtime — the keyword never appears as a literal in this file."""
    return f"{prefix} {_blocked_keyword()} tracker"


# ===========================================================================
# AC1 — guard the SET: AST-derived call sites, each structurally effective.
# ===========================================================================


def _parse(path: Path):
    try:
        return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (SyntaxError, UnicodeDecodeError):
        return None


def _build_parents(tree: ast.AST) -> dict:
    parents: dict = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent
    return parents


def _enclosing_function_name(node: ast.AST, parents: dict) -> str:
    cur = node
    while cur in parents:
        cur = parents[cur]
        if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return cur.name
    return "<module>"


def _is_structurally_guarded(call: ast.Call, parents: dict) -> bool:
    """Climb from the Call node to its nearest enclosing exclusion construct:
    either an `ast.If` whose test IS this call (directly, or via a BoolOp
    combining it with a sibling check — `a or b`) and whose body's first
    statement is continue/return/raise, or an `ast.comprehension` whose `ifs`
    list contains this call (a comprehension filter is exclusionary by
    construction — there is no "guard that does nothing" shape for one)."""
    cur: ast.AST = call
    while cur in parents:
        parent = parents[cur]
        if isinstance(parent, ast.comprehension) and cur in parent.ifs:
            return True
        if isinstance(parent, ast.If) and parent.test is cur:
            body0 = parent.body[0] if parent.body else None
            return isinstance(body0, (ast.Continue, ast.Return, ast.Raise))
        if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return False
        cur = parent
    return False


def _iter_blocked_vice_call_sites():
    """Yield (path, enclosing_function_name, lineno) for every *source line*
    that calls _is_blocked_vice in lambdas/web/ — derived by AST walk, not a
    hardcoded module/line list. Two calls on the same line (the "check name AND
    id" shape at site_api_social.py:1115/:1143) count as ONE call site, matching
    how the issue itself counted them."""
    sites: dict = {}  # (path, lineno) -> (path, func_name, lineno, [call_nodes])
    for path in sorted(WEB.rglob("*.py")):
        tree = _parse(path)
        if tree is None:
            continue
        parents = _build_parents(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not (isinstance(node.func, ast.Name) and node.func.id == "_is_blocked_vice"):
                continue
            key = (path, node.lineno)
            func_name = _enclosing_function_name(node, parents)
            sites.setdefault(key, (path, func_name, node.lineno, parents, []))[4].append(node)
    return sites


def test_blocked_vice_call_sites_derivation_is_non_vacuous():
    """The AST probe must find real call sites today, at exactly the files this
    issue's investigation covers — otherwise AC2 below would pass by finding
    nothing, which is not a guard at all. The COUNT was the finding this issue
    exists to correct: the original sweep named 6, the derivation found 11.

    Raised 11 -> 13 by #2238, deliberately and with the same bar: that issue added
    the check-in `note` screen at BOTH ends of the module's only reader-free-text
    path — `_handle_challenge_checkin` (the write door, rejects) and `_screened_note`
    (the read door, called from `handle_challenges` via `_public_checkins`, withholds).
    Both are structurally guarded (AC1 below) and both are behaviourally
    mutation-proved in tests/test_site_api_social_behavior.py, which owns the
    handler-level fixtures for this module — the AC3 disposition this file already
    uses for sites covered elsewhere.
    """
    sites = _iter_blocked_vice_call_sites()
    found_files = {p.name for (p, _ln) in sites}
    assert found_files == {
        "site_api_data.py",
        "site_api_habits.py",
        "site_api_journey.py",
        "site_api_ledger.py",
        "site_api_mind.py",
        "site_api_protocols.py",
        "site_api_rollups.py",
        "site_api_social.py",
    }, f"expected _is_blocked_vice call sites in exactly these 8 modules, got {found_files}"
    assert len(sites) == 24, (
        f"expected 24 distinct _is_blocked_vice call sites (11 from #2212 + 2 from #2238 + 11 from #2240), "
        f"got {len(sites)} — a call site was added or removed; update this pin AND give the changed "
        f"site the same mutation-proof treatment as the rest of this file"
    )


def test_every_blocked_vice_call_site_is_structurally_guarded():
    """Guard the SET, not the instance (#2212's own framing): every call site
    _is_blocked_vice has TODAY must sit inside a real exclusion construct. A
    13th/14th call site with no guard at all — the shape this issue actually
    found 4 times — reds here with no hardcoded list to update."""
    sites = _iter_blocked_vice_call_sites()
    assert sites, "derivation found no _is_blocked_vice call sites in lambdas/web/ — the probe is broken"

    unguarded = []
    for (path, lineno), (_p, func_name, _ln, parents, calls) in sites.items():
        if not any(_is_structurally_guarded(c, parents) for c in calls):
            unguarded.append(f"{path.relative_to(ROOT)}::{func_name} (line {lineno})")

    assert not unguarded, (
        "the following _is_blocked_vice call sites have no enclosing exclusion "
        f"(if/continue, if/return, or comprehension filter): {unguarded}"
    )


# ===========================================================================
# AC2 — behavioral, mutation-provable coverage for the sites that had none.
# ===========================================================================

# ── site_api_habits.py:87 — _absorb_reflection ───────────────────────────────


def test_absorb_reflection_drops_a_blocked_habit_name(monkeypatch):
    _pin_content_filter(monkeypatch)
    blocked = _name_with_blocked_keyword("Reflection for")
    store: dict = {}
    habits_mod._absorb_reflection(store, {"habit": blocked, "trigger": "x", "date": "2026-01-01"})
    assert blocked not in store, "_absorb_reflection must not create a causality entry for a blocked habit name"


def test_absorb_reflection_keeps_a_clean_habit_name(monkeypatch):
    """Sanity companion: the screen doesn't also eat legitimate habits."""
    _pin_content_filter(monkeypatch)
    store: dict = {}
    habits_mod._absorb_reflection(store, {"habit": "Morning sunlight", "trigger": "x", "date": "2026-01-01"})
    assert "Morning sunlight" in store


# ── site_api_habits.py:227/241 — vice_streaks (/api/vice_streaks — NO prior
#    behavioral test existed at all, per the issue) ──────────────────────────


def _vice_streaks_g(items):
    table = FakeDdbTable(rows=items)
    return {"table": table, "_experiment_date": lambda days_back=30: "2020-01-01"}


def test_vice_streaks_excludes_a_blocked_vice_name(monkeypatch):
    """Kills :227 (the vice_history builder). Removing ONLY :227 makes the
    blocked name appear in `vices` regardless of :241 (see AC4 above and the
    PR body's three-way transcript)."""
    _pin_content_filter(monkeypatch)
    blocked = _name_with_blocked_keyword("Quit")
    items = [
        {
            "pk": f"USER#{USER_ID}#SOURCE#habit_scores",
            "sk": "DATE#2026-06-01",
            "date": "2026-06-01",
            "vice_streaks": {"Alcohol-free": 5, blocked: 3},
        }
    ]
    resp = habits_mod.vice_streaks(_g=_vice_streaks_g(items))
    body = json.loads(resp["body"])
    names = {v["name"] for v in body["vices"]}
    assert names == {"Alcohol-free"}, f"blocked vice name leaked into /api/vice_streaks: {names}"
    assert body["total_tracked"] == 1


def test_vice_streaks_keeps_a_clean_vice_name(monkeypatch):
    _pin_content_filter(monkeypatch)
    items = [
        {
            "pk": f"USER#{USER_ID}#SOURCE#habit_scores",
            "sk": "DATE#2026-06-01",
            "date": "2026-06-01",
            "vice_streaks": {"Alcohol-free": 5},
        }
    ]
    resp = habits_mod.vice_streaks(_g=_vice_streaks_g(items))
    body = json.loads(resp["body"])
    assert {v["name"] for v in body["vices"]} == {"Alcohol-free"}


# ── site_api_habits.py:325 — habits() per-habit aggregation (/api/habits) ────


def _cond_strings(cond, out):
    for v in getattr(cond, "_values", ()) or ():
        if isinstance(v, str):
            out.append(v)
        else:
            _cond_strings(v, out)
    return out


def _pk_dispatch_table(rows_by_suffix: dict):
    """A FakeDdbTable whose query() dispatches on the pk's SOURCE suffix — so
    the habitify-partition fixture can't leak into the habit_scores/
    computed_metrics/habit_causality queries the same handler also issues."""

    def hook(table, **kwargs):
        strings = _cond_strings(kwargs.get("KeyConditionExpression"), [])
        pk = next((s for s in strings if s.startswith("USER#")), "")
        for suffix, rows in rows_by_suffix.items():
            if pk.endswith(suffix):
                return {"Items": rows}
        return {"Items": []}

    return FakeDdbTable(query_hook=hook)


def test_habits_endpoint_drops_a_blocked_habit_from_per_habit(monkeypatch):
    """Kills :325. No prior test exercised the habitify-sourced aggregation
    with a blocked name present at all."""
    _pin_content_filter(monkeypatch)
    blocked = _name_with_blocked_keyword("Avoid")
    table = _pk_dispatch_table(
        {
            "habitify": [
                {
                    "pk": f"USER#{USER_ID}#SOURCE#habitify",
                    "sk": "DATE#2026-06-01",
                    "date": "2026-06-01",
                    "habit_statuses": {
                        "Read 20 min": {"status": "completed", "group": "Mind", "scheduled_today": True},
                        blocked: {"status": "completed", "group": "Discipline", "scheduled_today": True},
                    },
                }
            ],
        }
    )
    _g = {"table": table, "_experiment_date": lambda days_back=30: "2020-01-01"}
    body = json.loads(habits_mod.habits(_g=_g)["body"])
    names = {h["name"] for h in body["per_habit"]}
    assert names == {"Read 20 min"}, f"blocked habit name leaked into /api/habits per_habit: {names}"


# ── site_api_habits.py:669 — habit_registry PROFILE fallback (/api/habit_registry) ──


def test_habit_registry_profile_fallback_drops_a_blocked_name(monkeypatch):
    """Kills :669. The primary Habitify-sourced path (:222 in site_api_data.py)
    already had coverage (test_evidence_catalog.py); the legacy PROFILE#v1
    fallback — taken whenever Habitify has no rows, e.g. right after a reset —
    did not."""
    _pin_content_filter(monkeypatch)
    blocked = _name_with_blocked_keyword("No")
    table = FakeDdbTable(
        rows=[
            {
                "pk": f"USER#{USER_ID}",
                "sk": "PROFILE#v1",
                "habit_registry": {
                    "Cold plunge": {"group": "Recovery"},
                    blocked: {"group": "Discipline"},
                },
            }
        ]
    )
    _g = {"table": table, "_habits_from_habitify": lambda: []}
    body = json.loads(habits_mod.habit_registry(_g=_g)["body"])
    names = {h["name"] for h in body["habits"]}
    assert names == {"Cold plunge"}, f"blocked habit name leaked into /api/habit_registry PROFILE fallback: {names}"
    assert body["source"] == "profile"


# ── site_api_social.py:1115 — /api/challenges live-run overlay ──────────────


def test_challenges_live_run_excludes_a_blocked_name(monkeypatch):
    """Kills :1115 on the `name` arm. Zero prior test exercised handle_challenges
    with ANY blocked-vice fixture — only a route→handler binding test existed."""
    _pin_content_filter(monkeypatch)
    blocked = _name_with_blocked_keyword("Cut")
    monkeypatch.setattr(
        social,
        "table",
        FakeDdbTable(
            rows=[
                {
                    "pk": f"USER#{USER_ID}#SOURCE#challenges",
                    "sk": "CHALLENGE#test-live-1",
                    "status": "active",
                    "name": blocked,
                    "duration_days": 7,
                    "daily_checkins": [],
                }
            ]
        ),
    )
    monkeypatch.setattr(social, "_challenges_cache", {"challenges": []})
    monkeypatch.setattr(social, "_challenges_cache_at", None)
    body = json.loads(social.handle_challenges()["body"])
    names = {c["name"] for c in body["challenges"]}
    assert blocked not in names, f"blocked challenge name leaked into /api/challenges (live): {names}"


def test_challenges_live_run_excludes_a_blocked_id(monkeypatch):
    """Kills :1115 on the `id` arm specifically (ER-06: a keyword can live only
    in the entry id while the display name is benign)."""
    _pin_content_filter(monkeypatch)
    blocked_id = _name_with_blocked_keyword("cut").lower().replace(" ", "-")
    monkeypatch.setattr(
        social,
        "table",
        FakeDdbTable(
            rows=[
                {
                    "pk": f"USER#{USER_ID}#SOURCE#challenges",
                    "sk": f"CHALLENGE#{blocked_id}",
                    "status": "active",
                    "name": "Discipline streak",
                    "duration_days": 7,
                    "daily_checkins": [],
                }
            ]
        ),
    )
    monkeypatch.setattr(social, "_challenges_cache", {"challenges": []})
    monkeypatch.setattr(social, "_challenges_cache_at", None)
    body = json.loads(social.handle_challenges()["body"])
    ids = {c["id"] for c in body["challenges"]}
    assert blocked_id not in ids, f"blocked challenge id leaked into /api/challenges (live): {ids}"


# ── site_api_social.py:1143 — /api/challenges catalog overlay ───────────────
# The 6th call site the issue's own sweep flagged as untested — but at the
# WRONG line: :1115 (live) already sits next to :1143 (catalog) in the same
# handler; the issue named only :1115. Both are covered here.


def test_challenges_catalog_excludes_a_blocked_name(monkeypatch):
    """Kills :1143 on the `name` arm."""
    _pin_content_filter(monkeypatch)
    blocked = _name_with_blocked_keyword("Skip")
    monkeypatch.setattr(social, "table", FakeDdbTable(rows=[]))
    monkeypatch.setattr(
        social,
        "_challenges_cache",
        {
            "challenges": [
                {"id": "clean-1", "name": "Cold exposure", "status": "available"},
                {"id": "blocked-1", "name": blocked, "status": "available"},
            ]
        },
    )
    monkeypatch.setattr(social, "_challenges_cache_at", None)
    body = json.loads(social.handle_challenges()["body"])
    names = {c["name"] for c in body["challenges"]}
    assert blocked not in names, f"blocked challenge name leaked into /api/challenges (catalog): {names}"
    assert "Cold exposure" in names


def test_challenges_catalog_excludes_a_blocked_id(monkeypatch):
    """Kills :1143 on the `id` arm."""
    _pin_content_filter(monkeypatch)
    blocked_id = _name_with_blocked_keyword("skip").lower().replace(" ", "-")
    monkeypatch.setattr(social, "table", FakeDdbTable(rows=[]))
    monkeypatch.setattr(
        social,
        "_challenges_cache",
        {
            "challenges": [
                {"id": "clean-2", "name": "Cold exposure", "status": "available"},
                {"id": blocked_id, "name": "Discipline streak", "status": "available"},
            ]
        },
    )
    monkeypatch.setattr(social, "_challenges_cache_at", None)
    body = json.loads(social.handle_challenges()["body"])
    ids = {c["id"] for c in body["challenges"]}
    assert blocked_id not in ids, f"blocked challenge id leaked into /api/challenges (catalog): {ids}"


# ── site_api_mind.py:182/:300 — /api/mind_overview (NO prior test existed AT ALL) ──


def _mind_overview_g(hs_item):
    def hook(table, **kwargs):
        strings = _cond_strings(kwargs.get("KeyConditionExpression"), [])
        pk = next((s for s in strings if s.startswith("USER#")), "")
        if pk.endswith("habit_scores"):
            limit = kwargs.get("Limit")
            items = [hs_item]
            return {"Items": items[:limit] if limit else items}
        return {"Items": []}

    table = FakeDdbTable(query_hook=hook)
    return {
        "table": table,
        "_query_source": lambda source, start, end, *a, **kw: [],
        "_experiment_date": lambda days_back=30: "2020-01-01",
    }


def test_mind_overview_vice_streaks_excludes_a_blocked_vice(monkeypatch):
    """Kills :182."""
    _pin_content_filter(monkeypatch)
    blocked = _name_with_blocked_keyword("Habit:")
    hs_item = {
        "pk": f"USER#{USER_ID}#SOURCE#habit_scores",
        "sk": "DATE#2026-06-01",
        "date": "2026-06-01",
        "vice_streaks": {"Screen-free evenings": 4, blocked: 2},
        "vices_held": 2,
        "vices_total": 2,
    }
    body = json.loads(mind_mod.mind_overview(_g=_mind_overview_g(hs_item))["body"])
    names = {v["name"] for v in body["vice_streaks"]}
    assert names == {"Screen-free evenings"}, f"blocked vice name leaked into /api/mind_overview vice_streaks: {names}"


def test_mind_overview_vice_timeline_excludes_a_blocked_vice(monkeypatch):
    """Kills :300."""
    _pin_content_filter(monkeypatch)
    blocked = _name_with_blocked_keyword("Habit:")
    hs_item = {
        "pk": f"USER#{USER_ID}#SOURCE#habit_scores",
        "sk": "DATE#2026-06-01",
        "date": "2026-06-01",
        "vice_streaks": {"Screen-free evenings": 4, blocked: 2},
        "vices_held": 2,
        "vices_total": 2,
    }
    body = json.loads(mind_mod.mind_overview(_g=_mind_overview_g(hs_item))["body"])
    assert body["vice_timeline"], "fixture produced no vice_timeline day — test is not exercising the code under test"
    for day in body["vice_timeline"]:
        assert blocked not in day.get("streaks", {}), f"blocked vice name leaked into /api/mind_overview vice_timeline: {day}"
