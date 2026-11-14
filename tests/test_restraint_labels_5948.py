"""tests/test_restraint_labels_5948.py — a restraint habit outside the two nameable categories never
reaches a public payload by name (#5948; docs/DATA_GOVERNANCE.md, "Editorial guardrails").

THE DEFECT. Public pages said the restraint habits were "named privately" while `/api/vice_streaks`
and `/api/habits` (`per_habit`) served every label with its streak. The rule had been "fixed" once
before — by one renderer, on one page (2026-06-23) — which left the labels on the wire and three more
payloads serving them. So this file tests the PAYLOAD, and the SET of payloads:

  1. the policy itself (`common.restraint_publication`): two categories, exact names, fail closed;
  2. the two endpoints the issue names, handler-level, on fixture rows that hold nameable and
     non-nameable restraint habits — nothing of a non-nameable one is anywhere in the serialized
     response — each with a MUST-FAIL control (the same assertion goes red when a label is let back);
  3. every public GET route, walked in a fresh interpreter against a table planted with synthetic
     restraint habits (`tests/restraint_route_walk.py`): no route serves a canary's name, slug or
     tracker id, and the `--ungated` control shows the walk finds them the moment the policy lets go;
  4. the public static config, and the governance sentence the policy's two categories come from.

Every restraint name here is SYNTHETIC ("Restraint A", "Restraint Canary Alpha") except the two the
governance doc allows to be named. No real non-nameable label is written in this file, and none may be.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lambdas"))
sys.path.insert(0, str(ROOT / "tests"))

for _k, _v in (
    ("TABLE_NAME", "life-platform"),
    ("AWS_REGION", "us-west-2"),
    ("AWS_DEFAULT_REGION", "us-west-2"),
    ("S3_BUCKET", "matthew-life-platform"),
    ("USER_ID", "matthew"),
):
    os.environ.setdefault(_k, _v)

from common import (  # noqa: E402
    activity_publication as AP,
    restraint_publication as RP,
)
from fakes import FakeDdbTable  # noqa: E402
from web import (  # noqa: E402
    site_api_common as common,
    site_api_habits as habits_mod,
    site_api_mind as mind_mod,
    site_api_protocols as protocols_mod,
)

USER = os.environ["USER_ID"]
ALCOHOL, TAKEOUT = "No alcohol", "No solo takeout"  # the two nameable habits (alcohol, food delivery)
UNNAMED = ("Restraint A", "Restraint B", "Restraint C")  # synthetic: categories nobody has ruled nameable
ORDINARY = "Read 20 min"  # not a restraint habit at all
_PUBLIC_IDS = sorted(AP.PUBLIC_HABIT_IDS)  # classified-public tracker ids (an unclassified habit is omitted upstream)


def _leaks(body, names=UNNAMED, ids=()) -> list:
    """Every forbidden token found ANYWHERE in a serialized response: a habit's name, its hyphen and
    underscore slugs, and its tracker id — case-insensitive, over the whole JSON text (keys included)."""
    blob = json.dumps(body, default=str).lower()
    toks = [t for n in names for t in (n.lower(), n.lower().replace(" ", "-"), n.lower().replace(" ", "_"))]
    toks += [str(i).lower() for i in ids]
    return sorted({t for t in toks if t in blob})


def _clean_filter(monkeypatch) -> None:
    """The content filter with an empty vocabulary: nothing is a never-public category here, so every
    restraint habit below is one the restraint policy — not the content filter — has to decide."""
    monkeypatch.setattr(common, "_content_filter_cache", {"blocked_vices": [], "blocked_vice_keywords": []})
    monkeypatch.setattr(common, "_content_filter_cache_at", None)


# ── 1. the policy ──────────────────────────────────────────────────────────────────────────


def test_exactly_the_two_governance_categories_are_nameable():
    assert sorted(set(RP.NAMED_CATEGORIES.values())) == ["alcohol", "food_delivery"]
    assert len(RP.NAMED_CATEGORIES) == 2, "a third nameable habit is an owner ruling plus a DATA_GOVERNANCE edit, not a refactor"
    assert RP.category(ALCOHOL) == "alcohol" and RP.category(TAKEOUT) == "food_delivery"


def test_the_policy_and_the_governance_doc_name_the_same_two_categories():
    """The must-agree pair: the doc is the rule, the module is its only enforcement. Widening the doc
    without the module (or the reverse) reds here, on the PR that does it."""
    doc = (ROOT / "docs" / "DATA_GOVERNANCE.md").read_text(encoding="utf-8")
    m = re.search(r"\*\*Vices:\*\* only (.+?) categories are ever named publicly", doc)
    assert m, "the Vices guardrail sentence moved or was reworded — re-point this test at it, do not delete it"
    in_doc = {c.strip().strip("*").replace("-", "_") for c in re.split(r",|\band\b", m.group(1)) if c.strip()}
    assert in_doc == set(RP.NAMED_CATEGORIES.values()), (in_doc, RP.NAMED_CATEGORIES)
    assert "aggregate-only" in doc[m.end() : m.end() + 200]
    assert "restraint_publication" in doc, "the guardrail no longer points at the module that enforces it"


@pytest.mark.parametrize(
    "name",
    [
        "Restraint A",
        "No alcohol on weekdays",  # a word inside a longer name is not the name
        "alcohol",
        "No takeout",
        "",
        None,
        "A habit added tomorrow",
    ],
)
def test_anything_that_is_not_an_exact_nameable_name_is_aggregate_only(name):
    assert RP.category(name) is None and not RP.may_name(name)


def test_a_nameable_name_matches_whatever_its_case_or_spacing():
    assert RP.may_name("NO ALCOHOL") and RP.may_name("  no   solo  takeout ")


def test_a_restraint_habit_is_recognised_by_any_one_of_its_three_signals():
    assert RP.is_restraint({"group": "Vice"}) and RP.is_restraint({"group": "vice"})
    assert RP.is_restraint(None, {"vice": True}) and RP.is_restraint({"group": "Core"}, {"group": "Vice"})
    assert not RP.is_restraint({"group": "Core"}, {"tier": 0})
    got = RP.restraint_names({"A": {"group": "Vice"}, "B": {"group": "Core"}}, {"C": {"vice": True}, "D": {}}, {"E": 3})
    assert got == {"A", "C", "E"}


def test_an_unknown_restraint_set_serves_only_nameable_names():
    """Fail closed: when the set of restraint habits could not be read, nothing but a nameable name is
    served — an ordinary habit is over-hidden rather than a restraint habit let through."""
    assert RP.nameable_names([ORDINARY, ALCOHOL, UNNAMED[0], TAKEOUT], None) == [ALCOHOL, TAKEOUT]
    assert RP.nameable_names([ORDINARY, ALCOHOL, UNNAMED[0]], {UNNAMED[0]}) == [ORDINARY, ALCOHOL]
    assert RP.load_restraint_names(None, "USER#x#SOURCE#", "x") is None


def test_a_failed_read_is_unknown_not_empty():
    class _Broken:
        def query(self, **_kw):
            raise RuntimeError("throttled")

    assert RP.load_restraint_names(_Broken(), f"USER#{USER}#SOURCE#", USER) is None


def test_the_unlabelled_shapes_carry_no_name():
    rows = [
        {"name": ALCOHOL, "current_streak": 9, "best_streak": 12, "relapses_90d": 1, "holding": True},
        {"name": UNNAMED[0], "current_streak": 30, "best_streak": 41, "relapses_90d": 2, "holding": True},
        {"name": UNNAMED[1], "current_streak": 0, "best_streak": 5, "relapses_90d": 4, "holding": False},
    ]
    out = RP.streak_portfolio(rows)
    assert [r["name"] for r in out["named"]] == [ALCOHOL] and out["named"][0]["category"] == "alcohol"
    assert out["unnamed"] == {"tracked": 2, "held": 1, "longest_streak": 30, "best_streak": 41, "relapses_90d": 6}
    assert RP.streak_portfolio([])["unnamed"] == {"tracked": 0, "held": 0, "longest_streak": 0, "best_streak": 0, "relapses_90d": 0}
    nameless = RP.nameless_streaks({UNNAMED[0]: 3, ALCOHOL: 9, UNNAMED[1]: 0})
    assert nameless == [
        {"current_streak": 9, "holding": True},
        {"current_streak": 3, "holding": True},
        {"current_streak": 0, "holding": False},
    ]
    agg = RP.adherence_aggregate([{"scheduled": 10, "completed": 7}, {"scheduled": 10, "completed": 8}])
    assert agg == {"count": 2, "scheduled_days": 20, "completed_days": 15, "adherence_pct": 75}
    assert RP.adherence_aggregate([])["adherence_pct"] is None
    assert not _leaks([out["unnamed"], nameless, agg])


# ── 2a. /api/vice_streaks ──────────────────────────────────────────────────────────────────


def _habit_scores_rows() -> list:
    """Three days of habit_scores: both nameable habits and three synthetic non-nameable ones."""
    streaks = [
        {ALCOHOL: 10, TAKEOUT: 0, UNNAMED[0]: 20, UNNAMED[1]: 3, UNNAMED[2]: 0},
        {ALCOHOL: 11, TAKEOUT: 1, UNNAMED[0]: 21, UNNAMED[1]: 0, UNNAMED[2]: 0},
        {ALCOHOL: 12, TAKEOUT: 2, UNNAMED[0]: 22, UNNAMED[1]: 1, UNNAMED[2]: 0},
    ]
    return [
        {
            "pk": f"USER#{USER}#SOURCE#habit_scores",
            "sk": f"DATE#2026-06-0{i + 1}",
            "date": f"2026-06-0{i + 1}",
            "vice_streaks": vs,
            "vices_held": sum(1 for v in vs.values() if v),
            "vices_total": len(vs),
            "missed_tier0": [UNNAMED[2]],
        }
        for i, vs in enumerate(streaks)
    ]


def _vice_streaks_body() -> dict:
    g = {"table": FakeDdbTable(rows=_habit_scores_rows()), "_experiment_date": lambda days_back=30: "2020-01-01"}
    return json.loads(habits_mod.vice_streaks(_g=g)["body"])


def test_vice_streaks_serves_the_non_nameable_habits_as_one_unlabelled_aggregate(monkeypatch):
    _clean_filter(monkeypatch)
    body = _vice_streaks_body()
    assert _leaks(body) == [], "a non-nameable restraint habit is identifiable in /api/vice_streaks"
    assert {v["name"]: v["category"] for v in body["vices"]} == {ALCOHOL: "alcohol", TAKEOUT: "food_delivery"}
    assert set(body["vices"][0]) == {"name", "category", "current_streak", "best_streak", "relapses_90d", "holding"}
    # Aggregate, not anonymised rows: one object of sums and maxima, the same keys whatever it holds.
    assert body["unnamed"] == {"tracked": 3, "held": 2, "longest_streak": 22, "best_streak": 22, "relapses_90d": 1}
    assert all(isinstance(v, int) for v in body["unnamed"].values())
    assert body["total_tracked"] == 5 and body["total_held"] == 4
    assert set(body) - {"_meta"} == {"as_of_date", "vices", "unnamed", "total_held", "total_tracked"}


def test_vice_streaks_with_nothing_tracked_keeps_the_same_keys(monkeypatch):
    _clean_filter(monkeypatch)
    g = {"table": FakeDdbTable(rows=[]), "_experiment_date": lambda days_back=30: "2020-01-01"}
    body = json.loads(habits_mod.vice_streaks(_g=g)["body"])
    assert body["vices"] == [] and body["unnamed"]["tracked"] == 0 and body["total_tracked"] == 0


def test_must_fail_control_vice_streaks_goes_red_when_a_label_is_reintroduced(monkeypatch):
    """The control: let ONE synthetic label back through the policy and the assertion above fails. A
    test that stays green here would be a green light wired to nothing."""
    _clean_filter(monkeypatch)
    monkeypatch.setitem(RP.NAMED_CATEGORIES, UNNAMED[0].lower(), "reintroduced")
    body = _vice_streaks_body()
    assert _leaks(body) == [UNNAMED[0].lower()]
    with pytest.raises(AssertionError):
        assert _leaks(body) == [], "a non-nameable restraint habit is identifiable in /api/vice_streaks"


# ── 2b. /api/habits (per_habit) ────────────────────────────────────────────────────────────


def _cond_strings(cond, out):
    for v in getattr(cond, "_values", ()) or ():
        if isinstance(v, str):
            out.append(v)
        else:
            _cond_strings(v, out)
    return out


def _table(rows_by_suffix: dict, profile: dict | None = None) -> FakeDdbTable:
    """A table whose query() answers by the partition asked for, and whose get_item serves the profile."""

    def hook(_table, **kwargs):
        strings = _cond_strings(kwargs.get("KeyConditionExpression"), [])
        pk = next((s for s in strings if s.startswith("USER#")), "")
        for suffix, rows in rows_by_suffix.items():
            if pk.endswith(suffix):
                rows = list(rows)
                if kwargs.get("ScanIndexForward") is False:
                    rows.reverse()
                return {"Items": rows[: kwargs["Limit"]] if kwargs.get("Limit") else rows}
        return {"Items": []}

    store = [{"pk": f"USER#{USER}", "sk": "PROFILE#v1", **profile}] if profile is not None else []
    return FakeDdbTable(query_hook=hook, store_items=store)


# name -> (tracker group, in vice_streaks, registry flag): each non-nameable habit is a restraint by a
# DIFFERENT signal, so the handler is tested on the union and not on one of its members.
_HABITS = {
    ORDINARY: ("Mind", False, False),
    ALCOHOL: ("Vice", True, False),
    TAKEOUT: ("Vice", True, False),
    UNNAMED[0]: ("Vice", False, False),  # the tracker group alone
    UNNAMED[1]: ("Core", True, False),  # a stored streak key alone
    UNNAMED[2]: ("Optimize", False, True),  # the owner's registry flag alone
}
_IDS = dict(zip(_HABITS, _PUBLIC_IDS))
_UNNAMED_IDS = [_IDS[n] for n in UNNAMED]


def _habit_rows() -> dict:
    days = ["2026-06-01", "2026-06-02", "2026-06-03", "2026-06-04"]
    habitify, scores = [], []
    for i, d in enumerate(days):
        statuses = {
            name: {
                "status": "completed" if (i + k) % 4 else "failed",
                "group": group,
                "scheduled_today": True,
                "periodicity": "daily",
                "habit_id": _IDS[name],
                "notes": [f"private note about {name}"],
            }
            for k, (name, (group, _s, _f)) in enumerate(_HABITS.items())
        }
        done = [n for n, s in statuses.items() if s["status"] == "completed"]
        habitify.append(
            {
                "pk": f"USER#{USER}#SOURCE#habitify",
                "sk": f"DATE#{d}",
                "date": d,
                "habit_statuses": statuses,
                "by_group": {"Vice": {"completed": 2, "possible": 3, "habits_done": done}},
                "habits": {n: 1 if n in done else 0 for n in statuses},
            }
        )
        scores.append(
            {
                "pk": f"USER#{USER}#SOURCE#habit_scores",
                "sk": f"DATE#{d}",
                "date": d,
                "tier0_done": 1,
                "tier0_total": 1,
                "vice_streaks": {n: i + 1 for n, sig in _HABITS.items() if sig[1]},
                "missed_tier0": [UNNAMED[0]],
            }
        )
    return {"habitify": habitify, "habit_scores": scores}


def _registry() -> dict:
    return {"habit_registry": {n: {"status": "active", "tier": 2, "vice": True} for n, sig in _HABITS.items() if sig[2]}}


def _habits_body() -> dict:
    g = {"table": _table(_habit_rows(), _registry()), "_experiment_date": lambda days_back=30: "2020-01-01"}
    return json.loads(habits_mod.habits(_g=g)["body"])


def test_habits_per_habit_lists_no_non_nameable_restraint_habit(monkeypatch):
    _clean_filter(monkeypatch)
    body = _habits_body()
    assert _leaks(body, ids=_UNNAMED_IDS) == [], "a non-nameable restraint habit is identifiable in /api/habits"
    assert {h["name"] for h in body["per_habit"]} == {ORDINARY, ALCOHOL, TAKEOUT}
    # All three were counted — one per signal — into one figure with no row, strip or note of its own.
    agg = body["restraints_unnamed"]
    assert set(agg) == {"count", "scheduled_days", "completed_days", "adherence_pct"}
    assert agg["count"] == 3 and agg["scheduled_days"] == 12 and 0 < agg["completed_days"] < 12
    assert agg["adherence_pct"] == round(agg["completed_days"] / 12 * 100)
    # The group share is an aggregate and stays: the restraint group's rate is public, its members' names are not.
    assert "Vice" in body["history"][-1]["groups"]


def test_must_fail_control_habits_goes_red_when_a_label_is_reintroduced(monkeypatch):
    _clean_filter(monkeypatch)
    monkeypatch.setitem(RP.NAMED_CATEGORIES, UNNAMED[1].lower(), "reintroduced")
    body = _habits_body()
    assert UNNAMED[1] in {h["name"] for h in body["per_habit"]}
    assert _leaks(body, ids=_UNNAMED_IDS) == [UNNAMED[1].lower()]
    with pytest.raises(AssertionError):
        assert _leaks(body, ids=_UNNAMED_IDS) == [], "a non-nameable restraint habit is identifiable in /api/habits"


# ── 2c. the same class, on the other payloads that carried the labels ──────────────────────


def test_habit_registry_counts_the_non_nameable_habits_and_lists_none(monkeypatch):
    _clean_filter(monkeypatch)
    rows = _habit_rows()
    listed = [{"name": n, "group": g, "frequency": "daily", "scheduled_today": True} for n, (g, _s, _f) in _HABITS.items()]
    g = {"table": _table(rows, _registry()), "_habits_from_habitify": lambda: [dict(h) for h in listed]}
    body = json.loads(habits_mod.habit_registry(_g=g)["body"])
    assert _leaks(body, ids=_UNNAMED_IDS) == []
    assert {h["name"] for h in body["habits"]} == {ORDINARY, ALCOHOL, TAKEOUT} and body["count"] == 3
    assert body["restraints_unnamed"] == {"count": 3, "by_group": {"Core": 1, "Optimize": 1, "Vice": 1}}
    assert set(body["groups"]) == {"Mind", "Vice", "Core", "Optimize"}  # a group of unnamed habits only still shows


def test_habit_registry_is_not_served_when_the_restraint_set_cannot_be_read(monkeypatch):
    """Fail closed: with the registry flag and streak keys unreadable the list cannot be classified, so the
    route answers 500 rather than serve a list it could not screen."""
    _clean_filter(monkeypatch)
    monkeypatch.setattr(RP, "load_restraint_names", lambda *_a, **_k: None)
    g = {"table": _table(_habit_rows(), _registry()), "_habits_from_habitify": lambda: [{"name": UNNAMED[2], "group": "Optimize"}]}
    resp = habits_mod.habit_registry(_g=g)
    assert resp["statusCode"] == 500 and _leaks(resp) == []


def test_mind_overview_rows_are_nameless_and_the_timeline_has_no_name_keyed_map(monkeypatch):
    _clean_filter(monkeypatch)
    g = {
        "table": _table({"habit_scores": _habit_scores_rows()}),
        "_query_source": lambda *_a, **_k: [],
        "_experiment_date": lambda days_back=30: "2020-01-01",
    }
    body = json.loads(mind_mod.mind_overview(_g=g)["body"])
    assert _leaks(body, names=UNNAMED + (ALCOHOL, TAKEOUT)) == [], "the Mind page names no restraint habit at all"
    assert body["vice_streaks"] and all(set(r) == {"current_streak", "holding"} for r in body["vice_streaks"])
    assert [r["current_streak"] for r in body["vice_streaks"]] == sorted((r["current_streak"] for r in body["vice_streaks"]), reverse=True)
    assert len(body["vice_streaks"]) == 5
    for day in body["vice_timeline"]:
        assert set(day) == {"date", "held", "total"}


def test_a_configs_habit_names_are_screened_on_both_routes(monkeypatch):
    _clean_filter(monkeypatch)
    names = [ORDINARY, ALCOHOL, *UNNAMED, TAKEOUT]
    monkeypatch.setattr(protocols_mod, "_domains_cache", {"domains": [{"id": "discipline", "habit_names": list(names)}]})
    rows = _habit_rows()
    rows["protocols"] = [{"pk": f"USER#{USER}#SOURCE#protocols", "sk": "PROTOCOL#x", "id": "x", "related_habits": list(names)}]
    table = _table(rows, _registry())
    dom = json.loads(protocols_mod.domains(_g={"table": table})["body"])
    pro = json.loads(protocols_mod.protocols(_g={"table": table})["body"])
    assert _leaks([dom, pro]) == []
    assert dom["domains"][0]["habit_names"] == [ORDINARY, ALCOHOL, TAKEOUT]
    assert pro["protocols"][0]["related_habits"] == [ORDINARY, ALCOHOL, TAKEOUT]
    # No table (the restraint set is unknown): served closed, and flagged so it is not cached for the hour.
    closed = protocols_mod.domains()
    assert json.loads(closed["body"])["domains"][0]["habit_names"] == [ALCOHOL, TAKEOUT]
    assert "max-age=300" in json.dumps(closed["headers"])


# ── 3. every public route ──────────────────────────────────────────────────────────────────


def _walk(*args) -> dict:
    proc = subprocess.run(
        [sys.executable, str(ROOT / "tests" / "restraint_route_walk.py"), *args],
        capture_output=True,
        text=True,
        timeout=300,
        cwd=str(ROOT),
    )
    assert proc.returncode == 0, proc.stderr[-3000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


@pytest.fixture(scope="module")
def walk() -> dict:
    return _walk()


@pytest.fixture(scope="module")
def ungated() -> dict:
    return _walk("--ungated")


# The routes that read a restraint habit's name through the policy. The ungated control must find the
# canaries on exactly these; a route added to (or dropped from) the set is a decision made in this file.
GOVERNED = {"/api/vice_streaks", "/api/habits", "/api/habit_registry", "/api/domains", "/api/protocols"}


def test_the_walk_reaches_every_route(walk):
    assert walk["routes"] >= 140 and walk["answered"] >= walk["routes"] - 3, (walk["routes"], walk["answered"])
    assert walk["raised"] == {}, walk["raised"]
    assert walk["unparsed_queries"] == 0, "a query the fake table could not read is a blind spot"


def test_no_public_route_serves_a_non_nameable_restraint_habit(walk):
    assert walk["leaks"] == {}, "public routes that identify a restraint habit outside the nameable categories"


def test_the_walk_is_not_vacuous(walk):
    """The canaries really are in front of the handlers: each is COUNTED where counts are served, the two
    nameable habits are served by name, and each of the four restraint signals put a canary in the count."""
    b = walk["bodies"]
    vs = b["/api/vice_streaks"]
    assert {v["name"] for v in vs["vices"]} == {ALCOHOL, TAKEOUT}
    assert vs["unnamed"]["tracked"] == 2 and vs["total_tracked"] == 4
    habits = b["/api/habits"]
    assert {ALCOHOL, TAKEOUT} <= {h["name"] for h in habits["per_habit"]}
    assert habits["restraints_unnamed"]["count"] == 4 and habits["restraints_unnamed"]["scheduled_days"] > 0
    assert b["/api/habit_registry"]["restraints_unnamed"]["count"] == 4
    assert len(b["/api/mind_overview"]["vice_streaks"]) == 4
    assert b["/api/domains"]["domains"][0]["habit_names"] == ["Synthetic Habit 1", ALCOHOL, TAKEOUT]
    assert b["/api/protocols"]["protocols"][0]["related_habits"] == ["Synthetic Habit 1", ALCOHOL, TAKEOUT]


def test_must_fail_control_the_walk_finds_the_canaries_when_the_policy_lets_go(ungated):
    """The control for the whole walk: with the policy naming every restraint habit, the same walk on the
    same table reports the canaries — on every route the policy governs, and on no other."""
    assert set(ungated["leaks"]) == GOVERNED, sorted(set(ungated["leaks"]) ^ GOVERNED)
    assert all(ungated["leaks"][r] for r in GOVERNED)


# ── 4. the static config, and the renderer's copy ──────────────────────────────────────────


def test_the_public_restraint_domain_names_only_nameable_habits():
    """`site/config/domains.json` is fetched as a file as well as through /api/domains, so the route's
    screen does not cover it: the domain that groups the restraint habits lists only nameable ones."""
    cfg = json.loads((ROOT / "site" / "config" / "domains.json").read_text(encoding="utf-8"))
    discipline = next(d for d in cfg["domains"] if d["id"] == "discipline")
    assert discipline["habit_names"], "the restraint domain lost its habit list — this test is not exercising anything"
    assert [n for n in discipline["habit_names"] if not RP.may_name(n)] == []


def test_the_vices_renderer_has_no_per_habit_name_to_print_for_the_aggregate():
    """Not the fix (the fix is the payload) — a pin that the renderer reads the aggregate, and that the
    page's copy says what the payload does."""
    js = (ROOT / "site" / "assets" / "js" / "evidence_sleep.js").read_text(encoding="utf-8")
    card = js[js.index("export function vicesUnnamedCard") : js.index("export function renderVices")]
    assert "u.tracked" in card and ".name" not in card.replace("vice-name", "")
    assert "d.unnamed" in js[js.index("export function renderVices") :]
    assert 'note("Shown honestly — held and broken both. Named privately.")' not in js
