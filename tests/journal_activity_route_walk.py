#!/usr/bin/env python3
"""tests/journal_activity_route_walk.py — every public GET route, served from a table whose ONLY
difference between variants is the owner's PRIVATE journal activity (owner ruling 2026-11-03).
Run by `tests/test_journal_activity_privacy.py`, one fresh interpreter per variant, so no handler
cache carries one variant into another.

    python3 tests/journal_activity_route_walk.py --variant none|daily|gaps --now 2026-11-03T20:00:00+00:00

THE INFERENCE TEST. Journal activity is private "including structured data", and public aggregates
"cannot indirectly reveal journal activity through counts, denominators, percentages, trends or
comparisons". So vary ONLY the journal and compare EVERYTHING public: every route's response body
must be byte-identical across the three variants, and so must the whole set of them taken together
(a cross-endpoint inference — one route's count against another's denominator — needs some route to
move; if none moves, no combination can).

What varies, all SYNTHETIC (no real date, count or gap — the dates are relative to `--now`):
  * the journal partition (`SOURCE#notion`, `DATE#<d>#journal#<template>` rows) — none / every day /
    a few days;
  * the Morning Journal and Evening Journal habits on every Habitify row (by their real Habitify ids,
    already public in tests/fixtures/habitify/) — failed every day / completed every day / sometimes,
    with the ingest's own roll-ups (`by_group`, `total_completed`, `completion_pct`) recomputed the way
    the ingest writes them, so the stored aggregates DO carry the journal, as in production;
  * a synthetic in-app note on a journal habit (free text: private even on a public habit);
  * the journal-derived partitions: `journal_analysis`, `flourishing`;
  * the daily probe's journal rows (`notion`, `notion:enrichment`): healthy / healthy / failing;
  * the presence record — PRODUCED here by the real producer
    (`compute.adaptive_mode_lambda.compute_and_store_engagement`) from the varied rows, so the
    producer half of /api/presence is under test too;
  * the circadian record — PRODUCED here by the real producer
    (`compute.circadian_compliance_lambda`), whose morning-light and wind-down anchors read the
    synthetic journal text, so /api/circadian's journal-free block is under test too.

What is held fixed (and why): every public source's rows; the stored `character_sheet`,
`computed_metrics` and `habit_scores` rows. Their producers fold journal inputs into METHOD-1 scores; since
the owner ruling of 2026-11-05 public readers serve the character sheet's and day grade's PUBLIC variants
(`health.character_public`, `health.day_grade_public`), whose producer-side invariance — single days, the
replayed multi-day chain, the downstream aggregates — is `tests/test_character_public_variant.py`'s. This
walk pins the SERVE-time contract and the presence producer, and says so rather than claiming more.

The clock is frozen at `--now` (one instant for all three variants) by replacing `datetime.datetime`
before anything imports it, so a served age or a "generated_at" cannot differ between variants for a
reason that is not the journal. boto3, S3, HTTP and Bedrock are dead (the #4972 walk's wiring).
"""

from __future__ import annotations

import argparse
import datetime as _dtmod
import json
import os
import sys
import time as _time
from decimal import Decimal

# ── the frozen clock (before ANY import that binds `datetime`) ─────────────────────────────
_REAL_DT = _dtmod.datetime
FROZEN: _REAL_DT = _REAL_DT(2026, 11, 3, 20, 0, 0, tzinfo=_dtmod.timezone.utc)


class _FrozenDateTime(_REAL_DT):
    @classmethod
    def now(cls, tz=None):  # noqa: D102
        base = cls.fromtimestamp(FROZEN.timestamp(), tz=_dtmod.timezone.utc)
        return base.astimezone(tz) if tz is not None else cls.fromtimestamp(FROZEN.timestamp())

    @classmethod
    def utcnow(cls):  # noqa: D102
        return cls.fromtimestamp(FROZEN.timestamp(), tz=_dtmod.timezone.utc).replace(tzinfo=None)

    @classmethod
    def today(cls):  # noqa: D102
        return cls.now()


def _freeze(now_iso: str) -> None:
    global FROZEN
    FROZEN = _REAL_DT.fromisoformat(now_iso)
    _dtmod.datetime = _FrozenDateTime  # type: ignore[misc]
    _time.time = lambda: FROZEN.timestamp()  # type: ignore[assignment]


if __name__ == "__main__":
    _ap = argparse.ArgumentParser()
    _ap.add_argument("--variant", choices=("none", "daily", "gaps"), required=True)
    _ap.add_argument("--now", required=True)
    _ap.add_argument("--ungated", action="store_true", help="mutation control: the activity policy publishes everything")
    _ap.add_argument(
        "--axis",
        choices=("journal", "mind"),
        default="journal",
        help="which private activity varies: the journal (2026-11-03) or State of Mind + the video diary (2026-11-05)",
    )
    ARGS = _ap.parse_args()
    _freeze(ARGS.now)

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
os.environ.setdefault("CONTENT_FILTER_JSON", json.dumps({"blocked_vices": ["No fizzlewick"], "blocked_vice_keywords": ["fizzlewick"]}))

import rhythm_route_walk as rw  # noqa: E402 — sets the env + lambdas/ path; we reuse its dead clients + route list

MORNING = ("Morning Journal", "99A94E6D-3D82-4BE9-85EF-8858CB4BA340")
EVENING = ("Evening Journal", "A862488C-8219-48EB-AD1F-90CBFDC37788")
# Public habits: two the owner confirmed public by id, and three ordinary ones by id from the
# classification (tests/test_journal_activity_privacy.py reads them from the module, never a name).
FOOD = ("Food Journal", "DBACD2CF-F839-42B2-A698-D214140EE370")
WHOOP = ("Whoop Journal", "F5F5B8BB-62E8-4C74-9FD8-3C6E913F1DCD")
PRIVATE_NOTE = "SYNTHETIC-PRIVATE-NOTE wrote three pages this morning"


def _public_habits():
    try:
        from common import activity_publication as AP

        ids = sorted(AP.PUBLIC_HABIT_IDS)[:3]
    except ImportError:  # a checkout from before the ruling (the negative control on origin/main)
        ids = ["SYNTHETIC-ID-1", "SYNTHETIC-ID-2", "SYNTHETIC-ID-3"]
    return [(f"Synthetic Habit {i + 1}", hid, "Core" if i < 2 else "Optimize") for i, hid in enumerate(ids)] + [
        (FOOD[0], FOOD[1], "Optimize"),
        (WHOOP[0], WHOOP[1], "Optimize"),
    ]


def _journal_days(variant: str, days: list) -> set:
    if variant == "none":
        return set()
    if variant == "daily":
        return set(days)
    return {d for i, d in enumerate(days) if i % 5 in (1, 2)}


def _rows(variant: str) -> list:
    from datetime import timedelta

    from common.pacific_time import PACIFIC

    today = FROZEN.astimezone(PACIFIC).date()
    days = [(today - timedelta(days=i)).isoformat() for i in range(21, -1, -1)]  # 22 days, oldest first
    jdays = _journal_days(variant, days)
    U = "USER#matthew"

    def P(src):
        return f"{U}#SOURCE#{src}"

    rows: list = []
    pub = _public_habits()
    for i, d in enumerate(days):
        statuses = {}
        for k, (name, hid, group) in enumerate(pub):
            done = (i + k) % 3 != 0
            statuses[name] = {
                "status": "completed" if done else "failed",
                "habit_id": hid,
                "group": group,
                "scheduled_today": True,
                "periodicity": "daily",
                "current_value": Decimal("1") if done else Decimal("0"),
                "target_value": Decimal("1"),
            }
        for name, hid in (MORNING, EVENING):
            done = d in jdays and not (variant == "gaps" and name == EVENING[0] and i % 2)
            st = {
                "status": "completed" if done else "failed",
                "habit_id": hid,
                "group": "Optimize",
                "scheduled_today": True,
                "periodicity": "daily",
                "current_value": Decimal("1") if done else Decimal("0"),
                "target_value": Decimal("1"),
            }
            if done:
                st["completed_at"] = f"{d}T14:00:00.000Z"
                st["notes"] = [PRIVATE_NOTE]
                st["notes_at"] = [f"{d}T14:00:00.000Z"]
                st["note_channel"] = "habitify_note"
            statuses[name] = st
        # The ingest's roll-ups over EVERY habit (journal included), exactly as it stores them.
        by_group: dict = {}
        for name, st in statuses.items():
            g = by_group.setdefault(st["group"], {"completed": 0, "possible": 0, "habits_done": []})
            g["possible"] += 1
            if st["status"] == "completed":
                g["completed"] += 1
                g["habits_done"].append(name)
        for g in by_group.values():
            g["pct"] = Decimal(str(round(g["completed"] / g["possible"], 4)))
        total_done = sum(g["completed"] for g in by_group.values())
        total_possible = sum(g["possible"] for g in by_group.values())
        rows.append(
            {
                "pk": P("habitify"),
                "sk": f"DATE#{d}",
                "date": d,
                "habit_statuses": statuses,
                "by_group": by_group,
                "total_completed": Decimal(total_done),
                "total_possible": Decimal(total_possible),
                "completion_pct": Decimal(str(round(total_done / total_possible, 4))),
                "habits": {n: Decimal("1") if s["status"] == "completed" else Decimal("0") for n, s in statuses.items()},
            }
        )
        # Held fixed (see the module docstring): the stored habit score, metrics and character rows.
        rows.append(
            {
                "pk": P("habit_scores"),
                "sk": f"DATE#{d}",
                "date": d,
                "scoring_method": "core_set_v1",
                "tier0_done": Decimal(2 + i % 2),
                "tier0_total": Decimal(3),
                "tier1_done": Decimal(4),
                "tier1_total": Decimal(8),
                "t0_perfect_streak": Decimal(i % 2),
                "core_pct": Decimal("0.7"),
                "vice_streaks": {"Synthetic Vice": Decimal(i)},
                "vices_held": Decimal(1),
                "vices_total": Decimal(1),
            }
        )
        rows.append(
            {
                "pk": P("computed_metrics"),
                "sk": f"DATE#{d}",
                "date": d,
                "component_scores": {"movement": Decimal("70"), "nutrition": Decimal("60"), "sleep_quality": Decimal("80")},
                "day_grade_score": Decimal("71"),
                "day_grade_letter": "B-",
            }
        )
        # Days 5-9 are a public-logging gap (no food, no weigh-in): a journal entry inside it must not
        # end a public "silent" run or change a survival/engagement count.
        gap = 5 <= i <= 9
        if not gap:
            rows.append(
                {
                    "pk": P("macrofactor"),
                    "sk": f"DATE#{d}",
                    "date": d,
                    "total_calories_kcal": Decimal("2100"),
                    "total_protein_g": Decimal("160"),
                }
            )
        if i % 2 == 0 and not gap:
            rows.append({"pk": P("withings"), "sk": f"DATE#{d}", "date": d, "weight_lbs": Decimal(str(250 - i * 0.1))})
        if i % 3 == 0:
            rows.append({"pk": P("hevy"), "sk": f"DATE#{d}#WORKOUT#w{i}", "date": d, "title": "Synthetic Session"})
        rows.append({"pk": P("whoop"), "sk": f"DATE#{d}", "date": d, "recovery_score": Decimal("60"), "hrv": Decimal("50")})
        rows.append({"pk": P("evening_ritual"), "sk": f"DATE#{d}", "date": d, "connection": Decimal(i % 5)})
        if i % 4 == 0:
            rows.append({"pk": P("interactions"), "sk": f"DATE#{d}#i{i}", "date": d, "depth": "meaningful"})
        rows.append(
            {
                "pk": P("todoist"),
                "sk": f"DATE#{d}",
                "date": d,
                "completed_tasks": [{"content": "synthetic", "labels": ["values"] if i % 2 else []}],
            }
        )
        # ── the PRIVATE journal and everything derived from it ──
        if d in jdays:
            for tmpl in ("morning",) if (variant == "gaps" and i % 2) else ("morning", "evening"):
                rows.append(
                    {
                        "pk": P("notion"),
                        "sk": f"DATE#{d}#journal#{tmpl}",
                        "date": d,
                        "template": tmpl,
                        "word_count": Decimal("300"),
                        # Synthetic words that trip the circadian anchors read from the journal
                        # (morning light, the evening wind-down), so the circadian producer below
                        # sees journal-dependent inputs. Never real text.
                        "raw_text": "synthetic sunlight walk" if tmpl == "morning" else "synthetic scrolling",
                    }
                )
            rows.append(
                {
                    "pk": P("journal_analysis"),
                    "sk": f"DATE#{d}",
                    "date": d,
                    "themes": ["work"],
                    "dominant_theme": "work",
                    "sentiment_score": Decimal("0.3"),
                    "word_count": Decimal("300"),
                    "energy_level": "high",
                }
            )
            rows.append({"pk": P("journal"), "sk": f"DATE#{d}", "date": d, "mood_valence": Decimal("0.4")})
            rows.append(
                {
                    "pk": P("flourishing"),
                    "sk": f"DATE#{d}",
                    "date": d,
                    "values_lived_count": Decimal("2"),
                    "values_lived": ["courage"],
                    "enrichment_model": "synthetic",
                }
            )
    rows.append(
        {
            "pk": P("character_sheet"),
            "sk": f"DATE#{days[-2]}",
            "date": days[-2],
            "character_level": Decimal("5"),
            "pillar_mind": {"level": Decimal("4"), "raw_score": Decimal("50"), "tier": "Foundation", "drivers": {"top": ["vice_control"]}},
            # Owner ruling 2026-11-05: public readers serve the record's public variant (held fixed here like the
            # rest of the row; the variant's own invariance is tests/test_character_public_variant.py's).
            "public": {
                "public_method_version": "character-public-v1",
                "origin": "recomputed",
                "character_level": Decimal("5"),
                "pillar_mind": {
                    "level": Decimal("4"),
                    "raw_score": Decimal("50"),
                    "tier": "Foundation",
                    "drivers": {"top": ["vice_control"]},
                },
            },
            "input_manifest": {
                "status": "partial" if variant == "gaps" else "complete",
                "complete": variant != "gaps",
                "as_of_day": days[-1],
                "degraded": ["notion"] if variant == "gaps" else [],
                "unobserved": [],
                "sources": {
                    "whoop": {"status": "fresh", "latest_day": days[-1], "age_hours": Decimal("3"), "stale_after_hours": Decimal("48")},
                    "notion": {
                        "status": "stale" if variant == "gaps" else "fresh",
                        "latest_day": (max(jdays) if jdays else None),
                        "age_hours": Decimal("400") if variant == "gaps" else Decimal("3"),
                        "stale_after_hours": Decimal("336"),
                    },
                },
            },
        }
    )
    probes = [("whoop-data-ingestion", "whoop", True), ("habitify-data-ingestion", "habitify", True)]
    probes += [("notion-journal-ingestion", "notion", variant != "gaps"), ("journal-enrichment", "notion:enrichment", variant != "gaps")]
    results = [{"function_name": f, "display_name": f, "source_id": s, "healthy": h} for f, s, h in probes]
    rows.append(
        {
            "pk": P("health_check"),
            "sk": f"DATE#{days[-1]}",
            "date": days[-1],
            "checked_at": FROZEN.isoformat(),
            "passed": Decimal(sum(1 for r in results if r["healthy"])),
            "failed": Decimal(sum(1 for r in results if not r["healthy"])),
            "total": Decimal(len(results)),
            "results": json.dumps(results),
            "failures": json.dumps([r for r in results if not r["healthy"]]),
        }
    )
    rows.append({"pk": U, "sk": "PROFILE#v1", "habit_registry": {}})
    return rows


# ── the fake table: the partition, the sort-key condition, order, Limit and COUNT honoured ─────


def _sk_cond(kce, eav):
    """(op, a, b) for the sort-key condition of a query, or None."""
    import re

    if isinstance(kce, str):
        m = re.search(r"\bsk\s+BETWEEN\s+(:\w+)\s+AND\s+(:\w+)", kce, re.I)
        if m:
            return ("between", (eav or {}).get(m.group(1)), (eav or {}).get(m.group(2)))
        m = re.search(r"begins_with\(\s*sk\s*,\s*(:\w+)\s*\)", kce)
        if m:
            return ("prefix", (eav or {}).get(m.group(1)), None)
        m = re.search(r"\bsk\s*(=|<=|>=|<|>)\s*(:\w+)", kce)
        if m:
            return (m.group(1), (eav or {}).get(m.group(2)), None)
        return None
    get_expr = getattr(kce, "get_expression", None)
    if get_expr is None:
        return None
    expr = get_expr()
    op, values = expr.get("operator"), list(expr.get("values") or ())
    if op == "AND":
        for v in values:
            got = _sk_cond(v, eav)
            if got is not None:
                return got
        return None
    if values and getattr(values[0], "name", None) == "sk":
        if op == "BETWEEN":
            return ("between", values[1], values[2])
        if op == "begins_with":
            return ("prefix", values[1], None)
        if op in ("=", "<=", ">=", "<", ">"):
            return (op, values[1], None)
    return None


def _match(sk: str, cond) -> bool:
    if cond is None:
        return True
    op, a, b = cond
    if op == "between":
        return str(a) <= sk <= str(b)
    if op == "prefix":
        return sk.startswith(str(a))
    return {"=": sk == str(a), "<=": sk <= str(a), ">=": sk >= str(a), "<": sk < str(a), ">": sk > str(a)}[op]


def _exists_field(fexpr):
    """The attribute name of a bare `Attr(name).exists()` filter, else None."""
    get_expr = getattr(fexpr, "get_expression", None)
    if get_expr is None:
        return None
    expr = get_expr()
    if expr.get("operator") == "attribute_exists" and expr.get("values"):
        return getattr(expr["values"][0], "name", None)
    return None


class JournalTable(rw.RhythmTable):
    rows: list = []

    def _rows(self, pk=None, sk=None):
        out = [json.loads(json.dumps(r, default=str), parse_float=Decimal) for r in self.rows]
        if pk is not None:
            out = [r for r in out if r["pk"] == pk]
        if sk is not None:
            out = [r for r in out if r["sk"] == sk]
        return out

    def query(self, KeyConditionExpression=None, ExpressionAttributeValues=None, ExpressionAttributeNames=None, IndexName=None, **kw):
        rw.STATS["queries"] += 1
        if IndexName:
            return {"Items": [], "Count": 0}
        pk = rw._requested_pk(KeyConditionExpression, ExpressionAttributeValues, ExpressionAttributeNames)
        if pk is None:
            rw.STATS["unparsed_queries"] += 1
            return {"Items": [], "Count": 0}
        cond = _sk_cond(KeyConditionExpression, ExpressionAttributeValues)
        items = sorted((r for r in self._rows(pk) if _match(str(r["sk"]), cond)), key=lambda r: str(r["sk"]))
        # `Attr(field).exists()` is honoured (the status board tracks a shared partition's sub-stream by
        # it); every other filter — the phase filter — is ignored, as before.
        must_have = _exists_field(kw.get("FilterExpression"))
        if must_have:
            items = [r for r in items if must_have in r]
        if kw.get("ScanIndexForward") is False:
            items.reverse()
        if kw.get("Limit"):
            items = items[: int(kw["Limit"])]
        if kw.get("Select") == "COUNT":
            return {"Count": len(items)}
        return {"Items": items, "Count": len(items)}

    def put_item(self, Item=None, **_kw):
        item = json.loads(json.dumps(Item, default=str), parse_float=Decimal)
        type(self).rows = [r for r in self.rows if not (r["pk"] == item["pk"] and r["sk"] == item["sk"])] + [item]
        return {}


def _ungate() -> None:
    """The mutation control: every source, habit and field classified public — the policy's absence.
    Patched before any serializer imports the policy, so module-level derivations see it too."""
    from common import activity_publication as AP

    AP.source_is_public = lambda _s: True
    AP.source_class = lambda _s: AP.PUBLIC
    AP.is_private_activity_source = lambda _s: False
    AP.habit_is_public = lambda *_a, **_k: True
    AP.public_status_fields = lambda st: dict(st or {})
    # 2026-11-05: the field-level and derived-metric halves of the policy.
    AP.field_is_public = lambda *_a: True
    AP.public_hae_datatypes = lambda rows: rows
    AP.correlation_pair_is_public = lambda _p: True
    AP.public_correlations = lambda c, alpha=0.05: c
    AP.hypothesis_is_public = lambda _h: True
    AP.public_component_scores = lambda sc: dict(sc or {})


# ── the State-of-Mind + video-diary axis (owner rulings 2026-11-05) ───────────────────────────
#
# What varies on `--axis mind`, all SYNTHETIC (relative dates, invented values): the How We Feel
# daily aggregates on the apple_health rows (every som_* field the ingest writes) and a
# `state_of_mind` partition row; the HAE per-datatype liveness sentinel's State-of-Mind row; the
# daily-metrics `diary_sessions` count; unconsented video-diary rows in the journal partition; and,
# produced by the REAL producer (compute.weekly_correlation_compute_lambda) from a series whose
# private metrics vary, the weekly correlation record and the what-changed snapshot; plus a
# hypothesis (and its calibration row) on the diary-day metric. Everything public is held fixed:
# the apple_health steps/water, the public correlation metrics, a public hypothesis. On this axis the
# journal is held at the "gaps" pattern; on the journal axis these rows are held at "gaps".


def _days() -> list:
    from datetime import timedelta

    from common.pacific_time import PACIFIC

    today = FROZEN.astimezone(PACIFIC).date()
    return [(today - timedelta(days=i)).isoformat() for i in range(21, -1, -1)]


def _mind_days(variant: str, days: list) -> set:
    if variant == "none":
        return set()
    if variant == "daily":
        return set(days)
    return {d for i, d in enumerate(days) if i % 4 in (0, 3)}


def _mind_rows(variant: str) -> list:
    days = _days()
    mdays = _mind_days(variant, days)
    U = "USER#matthew"
    rows: list = []
    for i, d in enumerate(days):
        ah = {
            "pk": f"{U}#SOURCE#apple_health",
            "sk": f"DATE#{d}",
            "date": d,
            "steps": Decimal(str(7000 + 37 * i)),
            "water_intake_ml": Decimal("2000"),
            "mindful_minutes": Decimal("5"),
            "webhook_ingested_at": f"{d}T15:00:00+00:00",
        }
        if d in mdays:
            ah.update(
                {
                    "som_avg_valence": Decimal(str(round(0.1 * (i % 7) - 0.3, 2))),
                    "som_min_valence": Decimal("-0.5"),
                    "som_max_valence": Decimal("0.6"),
                    "som_check_in_count": Decimal(1 + i % 3),
                    "som_mood_count": Decimal(1),
                    "som_emotion_count": Decimal(i % 3),
                    "som_top_labels": "Synthetic, Labels",
                    "som_top_associations": "Synthetic Association",
                }
            )
            rows.append(
                {
                    "pk": f"{U}#SOURCE#state_of_mind",
                    "sk": f"DATE#{d}",
                    "date": d,
                    "valence": Decimal("0.2"),
                    "som_avg_valence": Decimal("3"),
                }
            )
            # an unconsented video-diary session (no consent marker): private journal activity
            rows.append(
                {
                    "pk": f"{U}#SOURCE#notion",
                    "sk": f"DATE#{d}#journal#video_diary#s{i}",
                    "date": d,
                    "channel": "video_diary",
                    "template": "Video Diary",
                    "raw_text": "synthetic diary words",
                }
            )
        rows.append(ah)
    som_last = max(mdays) if mdays else None
    rows.append(
        {
            "pk": f"{U}#SOURCE#apple_health",
            "sk": "DATATYPE_LIVENESS",
            "datatypes": [
                {
                    "key": "steps",
                    "label": "Steps / activity",
                    "last_seen": days[-1],
                    "age_days": Decimal("0"),
                    "dark": False,
                    "stale_days": Decimal("2"),
                    "manual": False,
                },
                {
                    "key": "water",
                    "label": "Water",
                    "last_seen": days[-1],
                    "age_days": Decimal("0"),
                    "dark": False,
                    "stale_days": Decimal("3"),
                    "manual": True,
                },
                {
                    "key": "state_of_mind",
                    "label": "State of Mind",
                    "last_seen": som_last,
                    "age_days": Decimal(str(len(days) - 1 - days.index(som_last))) if som_last else None,
                    "dark": som_last is None,
                    "stale_days": Decimal("14"),
                    "manual": True,
                },
            ],
        }
    )
    n_diary = sum(1 for d in days if d in mdays)
    spec_diary = {
        "condition_metric": "diary_day",
        "outcome_metric": "habit_pct",
        "condition_op": ">=",
        "condition_threshold": Decimal("1"),
        "lag_days": Decimal("0"),
        "direction": "higher",
        "min_effect": Decimal("0.05"),
    }
    spec_public = {
        "condition_metric": "hrv",
        "outcome_metric": "recovery",
        "condition_op": "median_split",
        "lag_days": Decimal("1"),
        "direction": "higher",
        "min_effect": Decimal("0.05"),
    }
    for hid, spec, n_cond in (("hyp_synthetic_diary", spec_diary, n_diary), ("hyp_synthetic_public", spec_public, 11)):
        rows.append(
            {
                "pk": f"{U}#SOURCE#hypotheses",
                "sk": f"HYPOTHESIS#{hid}",
                "hypothesis_id": hid,
                "status": "pending" if hid.endswith("public") else ("archived" if n_cond else "pending"),
                "confidence": "low",
                "created_at": f"{days[0]}T12:00:00+00:00",
                "test_spec": spec,
                "deterministic_verdict": "inconclusive",
                "n_condition": Decimal(n_cond),
                "n_comparison": Decimal(len(days) - n_cond),
                "days_observed": Decimal(len(days)),
            }
        )
        rows.append(
            {
                "pk": f"{U}#SOURCE#calibration",
                "sk": f"CALIB#{days[-3]}#{hid}",
                "record_type": "hypothesis_resolution",
                "hypothesis_id": hid,
                "stated_confidence": "medium",
                "outcome": "confirmed" if (hid.endswith("public") or n_cond) else "refuted",
                "test_spec": spec,
                "n_condition": Decimal(n_cond),
                "resolved_at": f"{days[-3]}T12:00:00+00:00",
                "pre_registered_at": f"{days[0]}T12:00:00+00:00",
            }
        )
    return rows


def _with_mind(rows: list, variant: str) -> list:
    """The held-fixed computed_metrics rows, with the day's diary-session count varied (0 = an honest
    no-session day, as the producer writes it)."""
    mdays = _mind_days(variant, _days())
    for r in rows:
        if str(r.get("pk", "")).endswith("#SOURCE#computed_metrics"):
            r["diary_sessions"] = Decimal(1 if r.get("date") in mdays else 0)
            r["component_scores"] = dict(r.get("component_scores") or {}, journal=Decimal("100" if r.get("date") in mdays else "0"))
    return rows


def _corr_series(variant: str) -> dict:
    """A daily series for the weekly correlation producer: the public metrics fixed (a few pairs near
    the FDR bar, so a family change would show), the three private metrics varying."""
    days = _days()
    mdays = _mind_days(variant, days)
    series = {}
    for i, d in enumerate(days):
        wave = ((i * 7) % 11) / 10.0
        m = {
            "hrv": 40 + 2.0 * i + 3 * wave,
            "recovery_score": 50 + 1.5 * i + 8 * wave,
            "sleep_duration": 7 + wave,
            "sleep_score": 70 + 6 * wave,
            "resting_hr": 60 - 0.2 * i + 2 * wave,
            "strain": 10 + 3 * ((i * 5) % 7) / 7.0,
            "tsb": float((i * 3) % 9 - 4),
            "training_kj": 800 + 90 * ((i * 4) % 6),
            "training_mins": 40 + 7 * ((i * 2) % 5),
            "calories": 2100 + 40 * ((i * 3) % 7),
            "protein_g": 150 + 5 * ((i * 5) % 6),
            "carbs_g": 200 + 9 * ((i * 2) % 7),
            "fat_g": 70.0,
            "steps": 7000 + 37 * i,
            "day_grade": 70 + 2 * wave + 0.4 * i,
            "readiness": 60 + 5 * wave,
            "tier0_streak": float(i % 4),
            "habit_pct": 0.6 + 0.02 * ((i * 3) % 9),
            "glucose_cv": 20 + ((i * 5) % 8),
            "diary_sessions": 1.0 if d in mdays else 0.0,
            "mood_valence": (0.05 * i - 0.4) if d in mdays else None,
            "values_lived_count": float(i % 3) if d in mdays else None,
        }
        series[d] = m
    return series


def _produce_correlations(raw, variant: str) -> None:
    from compute import weekly_correlation_compute_lambda as WC

    WC.table = raw
    days = _days()
    corrs = WC.compute_correlations(_corr_series(variant))
    WC.store_correlations("2026-W45", corrs, days[0], days[-1], FROZEN.isoformat())
    unlocked, first = WC.diff_newly_unlocked(corrs, {}, days[-1])
    WC.store_what_changed("2026-W45", [], unlocked, first, days[-1], FROZEN.isoformat())


def _wire(variant: str, ungated: bool = False, axis: str = "journal"):
    import urllib.request

    import boto3

    if ungated:
        _ungate()

    journal_variant, mind_variant = (variant, "gaps") if axis == "journal" else ("gaps", variant)
    JournalTable.rows = _with_mind(_rows(journal_variant), mind_variant) + _mind_rows(mind_variant)
    raw = JournalTable()
    boto3.client = lambda *a, **k: rw._DeadClient()  # type: ignore[assignment]

    class _Res:
        def Table(self, _name):  # noqa: N802 — boto3's spelling
            return raw

    boto3.resource = lambda *a, **k: _Res()  # type: ignore[assignment]
    urllib.request.urlopen = lambda *a, **k: (_ for _ in ()).throw(rw._Dead("http disabled"))  # type: ignore[assignment]

    # The presence record, produced by the real producer from the varied rows.
    from compute import adaptive_mode_lambda as AM

    AM.table = raw
    AM.compute_and_store_engagement()

    # The circadian record, produced by the real producer: two of its anchors read the journal, and
    # /api/circadian must serve only the journal-free block (owner ruling 2026-11-03).
    from common.pacific_time import PACIFIC
    from compute import circadian_compliance_lambda as CC

    CC.table = raw
    CC.store_circadian_score(CC.compute_circadian_score(FROZEN.astimezone(PACIFIC).date().isoformat()))

    # The weekly correlation record + the what-changed snapshot, produced by the real producer.
    _produce_correlations(raw, mind_variant)

    from web import site_api_lambda as L

    for mod_name, mod in list(sys.modules.items()):
        if mod is None or not mod_name.startswith(("web.", "common.", "intelligence.", "health.", "ai.", "coach.", "content.")):
            continue
        for attr in ("table", "_table", "TABLE", "ddb_table"):
            cur = getattr(mod, attr, None)
            if hasattr(cur, "query") and not isinstance(cur, type) and type(cur).__name__ != "PublicationTable" and cur is not raw:
                setattr(mod, attr, raw)
        for attr in ("s3", "s3_client", "_s3", "S3", "bedrock", "_bedrock", "cloudwatch", "cw"):
            if attr in vars(mod) and not isinstance(vars(mod)[attr], type):
                setattr(mod, attr, rw._DeadClient())
    try:
        from ai import bedrock_client

        bedrock_client.invoke = lambda *a, **k: (_ for _ in ()).throw(rw._Dead("bedrock disabled"))
    except ImportError:
        pass
    return L


EXTRA_REQUESTS = (
    ("/api/observatory_week", {"domain": "mind"}),
    ("/api/observatory_week", {"domain": "physical"}),
)
VOLATILE_KEYS = ("request_id",)


def _normalise(node):
    if isinstance(node, dict):
        return {k: _normalise(v) for k, v in sorted(node.items()) if k not in VOLATILE_KEYS}
    if isinstance(node, list):
        return [_normalise(v) for v in node]
    return node


def walk(variant: str, ungated: bool = False, axis: str = "journal") -> dict:
    L = _wire(variant, ungated, axis)
    out = {"variant": variant, "routes": 0, "answered": 0, "raised": {}, "bodies": {}}
    reqs = [(p, {}) for p in rw.route_paths(L)] + list(EXTRA_REQUESTS)
    for path, qs in reqs:
        out["routes"] += 1
        key = path + ("?" + "&".join(f"{k}={v}" for k, v in qs.items()) if qs else "")
        event = {
            "rawPath": path,
            "path": path,
            "httpMethod": "GET",
            "requestContext": {"http": {"method": "GET"}},
            "headers": {},
            "queryStringParameters": dict(qs),
        }
        try:
            resp = L._dispatch_route(event, path, "GET")
            if resp is None and callable(L.ROUTES.get(path)):
                resp = L.ROUTES[path]()
        except Exception as e:  # noqa: BLE001 — a handler that raises served nothing
            out["raised"][key] = type(e).__name__
            continue
        if not isinstance(resp, dict):
            continue
        out["answered"] += 1
        body = resp.get("body")
        try:
            parsed = json.loads(body) if isinstance(body, str) else body
        except ValueError:
            parsed = body
        out["bodies"][key] = json.dumps({"status": resp.get("statusCode"), "body": _normalise(parsed)}, sort_keys=True, default=str)
    out["unparsed_queries"] = rw.STATS["unparsed_queries"]
    return out


if __name__ == "__main__":
    import io
    import logging

    logging.disable(logging.CRITICAL)
    _real_stdout = sys.stdout
    sys.stdout = io.StringIO()  # handlers print; keep stdout for the one JSON line
    try:
        result = walk(ARGS.variant, ARGS.ungated, ARGS.axis)
    finally:
        sys.stdout = _real_stdout
    print(json.dumps(result))
