"""tests/test_story_dossier_4532.py — the week dossier's three contracts (#4532).

The fixture is a fake table holding rows in the REAL DynamoDB wire shape (field names,
``Decimal`` numbers, ``DATE#<d>#WORKOUT#<uuid>`` sub-record keys, each writer's own
``ingested_at`` format — the HAE webhook's ``webhook_ingested_at``), sampled read-only from
``life-platform`` on 2026-10-09. Values are synthetic except the MacroFactor landing stamp
2026-09-27T05:33:25Z, the batch the issue names.

The week is week 3 (2026-09-16 → 09-22) as the table stood on the Wednesday it was written:
MacroFactor covered through 09-19 (with 09-17 never logged), and the 09-20→26 batch had not
landed. ``_with_late_batch`` adds that batch, as a rebuild run today would see it.

  1. Contract: every key the writer prompts name is a dossier key, built from the wire.
  2. Plan facts: the dossier's targets are the plan root's; a dossier carrying the profile's
     1,800 kcal / 190 g fails the check (mutation control), and ``week_dossier`` refuses it.
  3. Watermark: a day after it renders as not-yet-exported in the writer's packet; a missing
     day before it does not; and nothing dated after the week's end enters the dossier.
"""

from __future__ import annotations

import json
import os
import re
import sys
from decimal import Decimal
from typing import Any, Dict, List

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

import pytest  # noqa: E402
from content import story_desk, story_dossier, story_ledger, story_writers  # noqa: E402

WEEK3 = next(w for w in story_dossier.season_weeks(through="2026-09-30") if w["week"] == 3)
LATE_BATCH_LANDED = "2026-09-27T05:33:25Z"  # MacroFactor's 09-20→26, in one batch (the issue's own example)
PROFILE_TARGETS = {"daily_calories_target": 1800, "daily_protein_min_g": 190}  # PROFILE#v1 — never the plan


# ── a fake table that answers the dossier's queries over wire-shaped rows ────


class FakeTable:
    def __init__(self, items: List[Dict[str, Any]]):
        self.items = items

    @staticmethod
    def _cond(cond, values) -> Any:
        """A predicate for a key condition: the string form query_range uses, or a boto3 Key condition."""
        if isinstance(cond, str):
            pk = values[":pk"]
            lo, hi = values[":s"], values[":e"]
            return lambda it: it["pk"] == pk and lo <= it["sk"] <= hi
        expr = cond.get_expression()
        op, vals = expr["operator"], expr["values"]
        if op == "AND":
            a, b = FakeTable._cond(vals[0], values), FakeTable._cond(vals[1], values)
            return lambda it: a(it) and b(it)
        name = vals[0].name
        if op == "=":
            return lambda it: it.get(name) == vals[1]
        if op == "begins_with":
            return lambda it: str(it.get(name, "")).startswith(vals[1])
        if op == "BETWEEN":
            return lambda it: vals[1] <= str(it.get(name, "")) <= vals[2]
        raise AssertionError(f"FakeTable: unsupported key operator {op}")

    def query(self, **kw):
        pred = self._cond(kw["KeyConditionExpression"], kw.get("ExpressionAttributeValues") or {})
        # the phase filter is honoured as the table would: every fixture row is phase=experiment
        items = sorted((it for it in self.items if pred(it)), key=lambda it: it["sk"], reverse=kw.get("ScanIndexForward") is False)
        return {"Items": [dict(it) for it in items]}


def _pk(source: str) -> str:
    return f"USER#matthew#SOURCE#{source}"


def _day(source: str, d: str, **fields) -> Dict[str, Any]:
    return {
        "pk": _pk(source),
        "sk": f"DATE#{d}",
        "date": d,
        "source": source,
        "phase": "experiment",
        "schema_version": Decimal("1"),
        **fields,
    }


def _dates(a: str, b: str) -> List[str]:
    return story_dossier._dates(a, b)


def _macrofactor(d: str, landed: str) -> Dict[str, Any]:
    return _day(
        "macrofactor",
        d,
        ingested_at=landed,
        entries_count=Decimal("14"),
        total_calories_kcal=Decimal("1486.2"),
        total_protein_g=Decimal("186.4"),
        total_fiber_g=Decimal("27.9"),
        food_log=[],
    )


def _wire_rows(late_batch: bool) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    # MacroFactor: two batches before the window, 09-17 never logged, nothing past 09-19 on 09-23
    for d in _dates("2026-09-06", "2026-09-12"):
        rows.append(_macrofactor(d, "2026-09-13T04:12:08Z"))
    for d in _dates("2026-09-13", "2026-09-19"):
        if d != "2026-09-17":
            rows.append(_macrofactor(d, "2026-09-20T04:12:08Z"))
    if late_batch:
        for d in _dates("2026-09-20", "2026-09-26"):
            rows.append(_macrofactor(d, LATE_BATCH_LANDED))
    # Withings: weigh-ins (an event source), ingested the night after
    for d, lbs in (("2026-09-06", "327.3"), ("2026-09-13", "321.8"), ("2026-09-20", "318.6"), ("2026-09-22", "317.9")):
        rows.append(
            _day(
                "withings",
                d,
                weight_lbs=Decimal(lbs),
                weight_kg=Decimal(lbs) / Decimal("2.20462"),
                ingested_at=f"{d}T05:05:44.586088+00:00",
                measurement_time_utc=f"{d}T14:02:11Z",
                captured_at=f"{d}T14:02:11Z",
                measurement_timestamp=Decimal("1758000000"),
            )
        )
    if late_batch:
        rows.append(_day("withings", "2026-09-25", weight_lbs=Decimal("316.4"), ingested_at="2026-09-26T05:05:44.586088+00:00"))
    # Whoop: a day row every morning + a workout sub-record
    for d in _dates("2026-09-06", "2026-09-22") + (_dates("2026-09-23", "2026-09-26") if late_batch else []):
        rows.append(
            _day(
                "whoop",
                d,
                recovery_score=Decimal("64"),
                hrv=Decimal("41.2"),
                resting_heart_rate=Decimal("58"),
                sleep_duration_hours=Decimal("7.31"),
                strain=Decimal("11.4"),
                ingested_at=f"{d}T14:00:34.808956+00:00",
            )
        )
    rows.append(
        {
            **_day("whoop", "2026-09-18"),
            "sk": "DATE#2026-09-18#WORKOUT#1b37dd71-d651-4c78-bd37-60b36d4d6de9",
            "workout_id": "1b37dd71-d651-4c78-bd37-60b36d4d6de9",
            "sport_name": "walking",
            "start_time": "2026-09-18T15:00:00.000Z",
            "end_time": "2026-09-18T15:42:00.000Z",
            "average_heart_rate": Decimal("104"),
            "max_heart_rate": Decimal("121"),
            "strain": Decimal("6.1"),
            "ingested_at": "2026-09-19T04:00:34.899296+00:00",
        }
    )
    # Hevy: programmed sessions as DATE#<d>#WORKOUT#<uuid> sub-records
    for i, d in enumerate(("2026-09-14", "2026-09-16", "2026-09-17", "2026-09-19", "2026-09-21")):
        rows.append(
            {
                **_day("hevy", d),
                "sk": f"DATE#{d}#WORKOUT#fb535f38-df8a-4396-a38d-01{i:010d}",
                "title": ("Push A", "Pull A", "Legs A", "Push B", "Pull B")[i],
                "hevy_routine_id": f"routine-{i}",
                "start_time": f"{d}T15:00:00+00:00",
                "end_time": f"{d}T16:05:00+00:00",
                "duration_sec": Decimal("3900"),
                "set_count": Decimal("22"),
                "total_volume_kg": Decimal("8123.4"),
                "adherence": {
                    "status": "matched",
                    "overall_pct": Decimal("100"),
                    "as_prescribed": {"verdict": "as_prescribed", "reasons": []},
                },
                "ingested_at": f"{d}T22:00:05.920173+00:00",
                "exercises": [],
            }
        )
    # Strava: a walk
    rows.append(
        _day(
            "strava",
            "2026-09-20",
            activities=[{"sport_type": "Walk", "distance_miles": Decimal("2.1"), "moving_time_seconds": Decimal("2460")}],
            activity_count=Decimal("1"),
            ingested_at="2026-09-21T05:10:13.218735+00:00",
        )
    )
    # Habitify + the computed habit scores + day grades + Apple Health (webhook stamp)
    for d in _dates("2026-09-06", "2026-09-22"):
        rows.append(
            _day(
                "habitify",
                d,
                habit_statuses={"Walk": {"status": "completed", "group": "Movement", "scheduled_today": True}},
                completion_pct=Decimal("0.8"),
                ingested_at=f"{d}T20:05:49.788403+00:00",
            )
        )
        rows.append(
            _day(
                "habit_scores",
                d,
                tier0_pct=Decimal("0.857"),
                tier0_total=Decimal("7"),
                missed_tier0=["Walk"],
                vices_held=Decimal("3"),
                vices_total=Decimal("3"),
            )
        )
        rows.append(_day("day_grade", d, total_score=Decimal("78")))
        rows.append(_day("apple_health", d, steps=Decimal("6120"), webhook_ingested_at=f"{d}T23:55:00+00:00"))
    return rows


@pytest.fixture
def no_network(monkeypatch):
    """The sealed pre-registration is fetched over HTTPS; the dossier quotes {} when it cannot verify one."""
    monkeypatch.setattr(story_dossier, "load_prereg", lambda: {})
    story_dossier._PLAN_FACTS_CACHE.clear()
    yield
    story_dossier._PLAN_FACTS_CACHE.clear()


def _build(late_batch: bool = False):
    return story_dossier.week_dossier(FakeTable(_wire_rows(late_batch)), dict(WEEK3))


# ── 1. contract: the writer prompts name only dossier keys ──────────────────

_SNAKE = re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b")


def _keys(node: Any, out: set) -> set:
    if isinstance(node, dict):
        for k, v in node.items():
            out.add(str(k))
            _keys(v, out)
    elif isinstance(node, list):
        for v in node:
            _keys(v, out)
    return out


def _schema_vocab(node: Any, out: set) -> set:
    """Every property name and enum value of the desk's budget schema — the budget's words, not the dossier's."""
    if isinstance(node, dict):
        out |= set((node.get("properties") or {}).keys())
        out |= {str(e) for e in node.get("enum") or []}
        for v in node.values():
            _schema_vocab(v, out)
    elif isinstance(node, list):
        for v in node:
            _schema_vocab(v, out)
    return out


def test_every_key_the_writer_prompts_name_is_a_dossier_key(no_network):
    dossier, _ = _build()
    dossier_keys = _keys(dossier, set())
    other = _schema_vocab(story_desk.BUDGET_SCHEMA, set()) | _keys(story_ledger.ledger_for_prompt(story_ledger.empty_ledger(), 3), set())
    other.add("snake_case")  # the rubric's description of a thread id's format, not a key
    prompts = {
        "story_writers.SEASON_BRIEF": story_writers.SEASON_BRIEF,
        "story_writers.ELENA_VOICE": story_writers.ELENA_VOICE,
        "story_writers.EPISODE_VOICE": story_writers.EPISODE_VOICE,
        "story_desk.RUBRIC": story_desk.RUBRIC,
    }
    named: Dict[str, set] = {name: set(_SNAKE.findall(text)) for name, text in prompts.items()}
    dangling = sorted(
        f"{name}: {tok}"
        for name, toks in named.items()
        for tok in toks
        if tok not in other and not any(k == tok or k.startswith(tok + "_") for k in dossier_keys)
    )
    assert not dangling, f"the writer prompts name keys the wire-built dossier does not carry: {dangling}"
    # and the prompts' load-bearing dossier keys really are named (the contract has teeth in both directions)
    all_named = set().union(*named.values())
    for key in ("targets_from_plan", "not_yet_exported", "owner_voice"):
        assert key in all_named, f"no writer prompt names {key!r} any more"
    assert {"targets_from_plan", "not_yet_exported_dates", "owner_voice", "export_watermarks", "roster"} <= dossier_keys


def test_the_contract_fails_when_a_dossier_key_is_renamed(no_network):
    """Mutation control for the contract: rename targets_from_plan and the prompt's key dangles."""
    dossier, _ = _build()
    dossier["nutrition"]["plan_targets"] = dossier["nutrition"].pop("targets_from_plan")
    keys = _keys(dossier, set())
    assert not any(k == "targets_from_plan" or k.startswith("targets_from_plan_") for k in keys)
    assert "targets_from_plan" in _SNAKE.findall(story_writers.SEASON_BRIEF)


# ── 2. plan facts: the plan root's targets, never the profile's ─────────────


def test_the_dossier_carries_the_plan_roots_targets(no_network):
    from experiment.plan_facts import load_plan_facts

    facts = load_plan_facts()
    dossier, _ = _build()
    t = dossier["nutrition"]["targets_from_plan"]
    assert (t["calories_kcal"], t["protein_floor_g"]) == (facts["daily_calories_target"], facts["daily_protein_min_g"])
    assert (t["calories_kcal"], t["protein_floor_g"]) != (1800, 190)
    assert story_dossier.plan_facts_findings(dossier, facts) == []
    # the 186 g day is AT the plan's 170 g floor, not "4 g short" of the profile's 190
    assert dossier["nutrition"]["days_protein_at_or_over_floor"] == dossier["nutrition"]["days_logged"]


def test_a_dossier_built_with_the_profiles_1800_190_fails_the_plan_facts_check(no_network, monkeypatch):
    """Mutation control (the acceptance box): the PROFILE#v1 figures in place of the plan's.
    ``week_dossier`` refuses to hand the packet on."""
    real_load_plan = story_dossier.load_plan
    monkeypatch.setattr(story_dossier, "load_plan", lambda f=None: {**real_load_plan(f), **PROFILE_TARGETS})
    with pytest.raises(ValueError, match="not the plan's") as exc:
        _build()
    assert "1800" in str(exc.value) and "190" in str(exc.value)


def test_the_plan_facts_check_names_every_profile_figure_it_finds(no_network):
    from experiment.plan_facts import load_plan_facts

    facts = load_plan_facts()
    dossier, _ = _build()
    dossier["plan"].update(PROFILE_TARGETS)
    dossier["nutrition"]["targets_from_plan"].update({"calories_kcal": 1800, "protein_floor_g": 190})
    paths = {f.split(" is ")[0] for f in story_dossier.plan_facts_findings(dossier, facts)}
    assert paths == {
        "dossier plan.daily_calories_target",
        "dossier plan.daily_protein_min_g",
        "dossier nutrition.targets_from_plan.calories_kcal",
        "dossier nutrition.targets_from_plan.protein_floor_g",
    }


def test_an_unreadable_plan_root_disarms_rather_than_guesses():
    assert story_dossier.plan_facts_findings({"nutrition": {"targets_from_plan": {"calories_kcal": 1800}}}, None) == []


# ── 3. watermarks: export lag is not absence, and the window is the window ──


def test_a_day_after_the_watermark_renders_as_not_yet_exported_in_the_packet(no_network):
    dossier, nye_sources = _build(late_batch=False)
    n = dossier["nutrition"]
    assert n["export_watermark"] == {"last_covered_date": "2026-09-19", "last_batch_landed": "2026-09-20T04:12"}
    assert n["not_yet_exported_dates"] == ["2026-09-20", "2026-09-21", "2026-09-22"]
    # 09-17 is BEFORE the watermark: the batch that covers it landed without it — a real gap, not lag
    assert n["missing_but_exported_dates"] == ["2026-09-17"]
    assert "macrofactor" in nye_sources
    wm = dossier["export_watermarks"]["macrofactor"]
    assert wm["kind"] == "daily" and wm["not_yet_exported_dates"] == ["2026-09-20", "2026-09-21", "2026-09-22"]
    # the packet the writer is handed (the same _context both writers build)
    packet = story_writers._context(dossier, {}, story_ledger.empty_ledger(), 3, None)
    assert "nutrition for 2026-09-20, 2026-09-21, 2026-09-22 is not yet exported" in packet
    blob = json.loads(packet.split("WEEK 3 DOSSIER (the only figures you may use):\n", 1)[1])
    assert blob["nutrition"]["not_yet_exported_dates"] == ["2026-09-20", "2026-09-21", "2026-09-22"]
    assert "2026-09-17" not in blob["nutrition"]["not_yet_exported_dates"]


def test_once_the_late_batch_lands_the_same_days_are_covered(no_network):
    dossier, nye_sources = _build(late_batch=True)
    n = dossier["nutrition"]
    assert n["not_yet_exported_dates"] == []
    assert n["export_watermark"] == {"last_covered_date": "2026-09-22", "last_batch_landed": LATE_BATCH_LANDED[:16]}
    assert "macrofactor" not in nye_sources
    assert not any("not yet exported" in c for c in dossier["data_caveats"])


def test_every_daily_source_has_a_watermark_and_event_sources_never_claim_lag(no_network):
    dossier, _ = _build()
    wms = dossier["export_watermarks"]
    assert set(wms) == set(story_dossier.WATERMARK_SOURCES)
    assert wms["apple_health"]["last_batch_landed"] == "2026-09-22T23:55"  # the webhook's own stamp field
    assert wms["hevy"]["last_covered_date"] == "2026-09-21"  # read from the WORKOUT sub-records
    for s, kind in story_dossier.WATERMARK_SOURCES.items():
        assert ("not_yet_exported_dates" in wms[s]) == (kind == "daily"), s


_ISO_DATE = re.compile(r"\b(20\d\d-\d\d-\d\d)")


def _dated_after(node: Any, end: str, path: str = "") -> List[str]:
    out: List[str] = []
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "last_batch_landed":  # a landing timestamp, not a fact about the week (documented)
                continue
            out += [f"{path}.{k} (key)"] if _ISO_DATE.match(str(k)) and str(k)[:10] > end else []
            out += _dated_after(v, end, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            out += _dated_after(v, end, f"{path}[{i}]")
    elif isinstance(node, str):
        out += [f"{path} = {node!r}" for m in _ISO_DATE.finditer(node) if m.group(1) > end]
    return out


def test_no_fact_dated_after_the_weeks_end_enters_the_dossier(no_network):
    """Rebuilt today, week 3 must not borrow the 09-23→26 rows the table now holds."""
    dossier, _ = _build(late_batch=True)
    leaks = _dated_after(dossier, WEEK3["end"])
    assert not leaks, f"facts dated after {WEEK3['end']}: {leaks}"
    assert dossier["export_watermarks"]["withings"]["last_covered_date"] == "2026-09-22"
    assert dossier["weight"]["week_end"]["date"] == "2026-09-22"
