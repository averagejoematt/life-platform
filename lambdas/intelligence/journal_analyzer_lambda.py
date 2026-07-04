"""
Journal Analyzer Lambda — Phase 2 deterministic aggregator (#506).

v1 called Haiku per entry to re-classify themes/sentiment — a lower-fidelity
duplicate of extraction pass 1 (journal_enrichment_lambda, schema v2). v2 deletes
that AI call entirely: every output is now a pure aggregation over the enriched
fields the entries already carry (`enriched_themes`, `enriched_sentiment`,
`enriched_mood/energy`, `enriched_entities`, `enriched_behaviors`,
`enriched_causal_hints` — the last with write-time-grounded verbatim quotes).

Outputs (PK = USER#matthew#SOURCE#journal_analysis):
  SK DATE#YYYY-MM-DD            — per-day theme/sentiment row for /api/journal_analysis,
                                  derived deterministically (no one_line_summary: J-8
                                  resolved by dropping the field at the writer)
  SK ENTITY_REGISTRY#current    — per entity: type, mentions, first/last seen,
                                  sentiment counts (counts, never padded trends)
  SK BEHAVIOR_REGISTRY#current  — per behavior: mentions, valence counts, first/last
                                  seen, habitify_match (the free-text side of #422)
  SK HYPO_CANDIDATE#{slug}      — one per distinct cause→effect pair, carrying the
                                  verbatim quotes as provenance; cause/effect mapped
                                  to the hypothesis engine's SPEC_METRICS vocabulary;
                                  status = testable | needs_instrumentation

The hypothesis engine reads testable candidates as generation seeds; unmappable
ones stay visible as "needs instrumentation". Registries are honest-when-sparse:
counts and n's only, and an empty cycle writes empty registries, never placeholders.

Trigger: EventBridge cron — nightly at 3am PT (10:00 UTC). Idempotent overwrite.
"""

import json
import logging
import os
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
USER_ID = os.environ.get("USER_ID", "matthew")
USER_PREFIX = f"USER#{USER_ID}#SOURCE#"
CACHE_PK = f"{USER_PREFIX}journal_analysis"

# J-5 (#505): word floor shared with journal_enrichment_lambda — kept in lockstep
# deliberately (both skip entries too short to yield real signal).
MIN_TEXT_WORDS = 20
WINDOW_DAYS = 180
MAX_QUOTES_PER_CANDIDATE = 5
MAX_REGISTRY_ENTRIES = 100

dynamodb = boto3.resource("dynamodb", region_name="us-west-2")
table = dynamodb.Table(TABLE_NAME)

# J-8 (#504): cache writes must carry a phase attribute — an unstamped record
# passes with_phase_filter forever and survives experiment resets untagged.
from constants import EXPERIMENT_PHASE_CURRENT  # noqa: E402
from numeric import decimals_to_float as _decimal_to_float  # noqa: E402

# ── Deterministic vocabularies ────────────────────────────────────────────────

# Theme-tag → public dominant_theme category. Ordered; first hit wins. This
# replaces the Haiku classification: pass-1 already produced the theme tags,
# categorising them is a lookup, not an inference.
_THEME_CATEGORIES = [
    ("anxiety_stress", ("stress", "anxiet", "worry", "overwhelm", "fear", "pressure", "uncertain")),
    ("health_body", ("health", "fitness", "sleep", "food", "weight", "body", "training", "workout", "diet", "energy")),
    ("relationships", ("family", "friend", "partner", "relationship", "social", "love", "kids", "marriage")),
    ("work_ambition", ("work", "career", "project", "productiv", "leader", "achieve", "business", "job")),
    ("gratitude", ("gratitude", "grateful", "thankful", "appreciat")),
    ("personal_growth", ("growth", "habit", "identity", "progress", "goal", "improve", "discipline", "learning")),
    ("reflection", ("reflect", "philosoph", "existential", "meaning", "past", "memory")),
]

# Cause/effect phrase → SPEC_METRICS name (hypothesis_engine_lambda's vocabulary).
# Ordered; first hit wins. A phrase with no hit is honest "needs instrumentation" —
# the platform does not pretend it can test what it doesn't measure.
METRIC_KEYWORDS = [
    ("deep sleep", "deep_sleep_hrs"),
    ("rem", "rem_hrs"),
    ("sleep", "total_sleep_hrs"),
    ("recovery", "recovery"),
    ("hrv", "hrv"),
    ("resting heart", "rhr"),
    ("mood", "mood"),
    ("stress", "journal_stress"),
    ("energy", "energy"),
    ("tired", "energy"),
    ("fatigue", "energy"),
    ("weight", "weight_lbs"),
    ("protein", "protein_g"),
    ("carb", "carbs_g"),
    ("calorie", "calories"),
    ("overate", "calories"),
    ("overeat", "calories"),
    ("glucose", "glucose_avg"),
    ("blood sugar", "glucose_avg"),
    ("steps", "steps"),
    ("walk", "steps"),
    ("meditat", "mindful_min"),
    ("mindful", "mindful_min"),
    ("zone 2", "zone2_min"),
    ("workout", "workout"),
    ("train", "workout"),
    ("gym", "workout"),
    ("lift", "workout"),
    ("exercise", "workout"),
]


def map_phrase_to_metric(phrase):
    """Deterministic phrase → tracked-metric mapping. None = needs instrumentation."""
    p = (phrase or "").lower()
    for kw, metric in METRIC_KEYWORDS:
        if kw in p:
            return metric
    return None


def _norm(s):
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def slugify(cause, effect):
    """Stable slug for a cause→effect pair (the HYPO_CANDIDATE sk)."""
    raw = f"{_norm(cause)}--{_norm(effect)}"
    return re.sub(r"[^a-z0-9-]+", "-", raw).strip("-")[:80]


def categorize_themes(themes):
    """Theme tags → the public 8-way dominant_theme category."""
    for tag in themes or []:
        t = _norm(str(tag))
        for category, keywords in _THEME_CATEGORIES:
            if any(k in t for k in keywords):
                return category
    return "other"


def derive_daily_row(entry, date_str):
    """The per-day cache row, derived purely from pass-1 enrichment.

    Returns None when the entry carries no v2 enrichment (nothing to derive from —
    the old Haiku row, if any, is left in place rather than overwritten with less).
    No one_line_summary: J-8 resolved at the writer, not just the reader."""
    themes = entry.get("enriched_themes") or []
    sentiment = _norm(entry.get("enriched_sentiment"))
    mood = entry.get("enriched_mood")
    energy = entry.get("enriched_energy")
    if not themes and not sentiment and mood is None:
        return None

    if mood is not None:
        score = round((float(mood) - 5.0) / 5.0, 2)  # 0-10 → -1..1
    else:
        score = {"positive": 0.5, "negative": -0.5}.get(sentiment, 0.0)
    if score >= 0.5:
        label = "very_positive" if score >= 0.7 else "positive"
    elif score <= -0.5:
        label = "very_negative" if score <= -0.7 else "negative"
    elif score > 0.1:
        label = "positive"
    elif score < -0.1:
        label = "negative"
    else:
        label = "neutral"

    content = entry.get("body_text") or entry.get("raw_text") or ""
    row = {
        "pk": CACHE_PK,
        "sk": f"DATE#{date_str}",
        "date": date_str,
        "dominant_theme": categorize_themes(themes),
        "themes": [str(t) for t in themes][:5],
        "sentiment_score": str(score),
        "sentiment_label": label,
        "word_count": len(content.split()),
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
        "model": "deterministic-v2",
        "analyzer_version": 2,
        "phase": EXPERIMENT_PHASE_CURRENT,
        "ttl": int((datetime.now(timezone.utc) + timedelta(days=180)).timestamp()),
    }
    if energy is not None:
        row["energy_level"] = "high" if float(energy) >= 7 else ("medium" if float(energy) >= 4 else "low")
    return row


def build_entity_registry(dated_entries):
    """ENTITY_REGISTRY#current body: per entity — type, mentions, first/last seen,
    sentiment counts. Counts only; no trends (honest-when-sparse)."""
    reg = {}
    for date_str, entry in dated_entries:
        for ent in entry.get("enriched_entities") or []:
            if not isinstance(ent, dict) or not ent.get("name"):
                continue
            key = _norm(str(ent["name"]))
            slot = reg.setdefault(
                key,
                {
                    "name": str(ent["name"]),
                    "types": Counter(),
                    "mentions": 0,
                    "first_seen": date_str,
                    "last_seen": date_str,
                    "sentiment_counts": Counter(),
                },
            )
            slot["mentions"] += 1
            slot["first_seen"] = min(slot["first_seen"], date_str)
            slot["last_seen"] = max(slot["last_seen"], date_str)
            if ent.get("type"):
                slot["types"][_norm(str(ent["type"]))] += 1
            if ent.get("sentiment"):
                slot["sentiment_counts"][_norm(str(ent["sentiment"]))] += 1
    out = []
    for slot in sorted(reg.values(), key=lambda s: (-s["mentions"], s["name"])):
        out.append(
            {
                "name": slot["name"],
                "type": slot["types"].most_common(1)[0][0] if slot["types"] else None,
                "mentions": slot["mentions"],
                "first_seen": slot["first_seen"],
                "last_seen": slot["last_seen"],
                "sentiment_counts": dict(slot["sentiment_counts"]),
            }
        )
    return out[:MAX_REGISTRY_ENTRIES]


def match_habit(behavior, habit_names):
    """Deterministic behavior → habitify-name join: exact normalized containment
    either way, or full token-subset. Returns the habit name or None."""
    b = _norm(behavior)
    if not b:
        return None
    b_tokens = set(b.split())
    for habit in sorted(habit_names):
        h = _norm(habit)
        if not h:
            continue
        h_tokens = set(h.split())
        if h in b or b in h or (h_tokens and h_tokens <= b_tokens) or (b_tokens and b_tokens <= h_tokens):
            return habit
    return None


def build_behavior_registry(dated_entries, habit_names):
    """BEHAVIOR_REGISTRY#current body: per behavior — mentions, valence counts,
    first/last seen, habitify_match (the free-text side of #422)."""
    reg = {}
    for date_str, entry in dated_entries:
        for beh in entry.get("enriched_behaviors") or []:
            if not isinstance(beh, dict) or not beh.get("behavior"):
                continue
            key = _norm(str(beh["behavior"]))
            slot = reg.setdefault(
                key,
                {
                    "behavior": str(beh["behavior"]),
                    "mentions": 0,
                    "valence_counts": Counter(),
                    "times_of_day": Counter(),
                    "first_seen": date_str,
                    "last_seen": date_str,
                },
            )
            slot["mentions"] += 1
            slot["first_seen"] = min(slot["first_seen"], date_str)
            slot["last_seen"] = max(slot["last_seen"], date_str)
            if beh.get("valence"):
                slot["valence_counts"][_norm(str(beh["valence"]))] += 1
            if beh.get("time_of_day"):
                slot["times_of_day"][_norm(str(beh["time_of_day"]))] += 1
    out = []
    for slot in sorted(reg.values(), key=lambda s: (-s["mentions"], s["behavior"])):
        out.append(
            {
                "behavior": slot["behavior"],
                "mentions": slot["mentions"],
                "valence_counts": dict(slot["valence_counts"]),
                "times_of_day": dict(slot["times_of_day"]),
                "first_seen": slot["first_seen"],
                "last_seen": slot["last_seen"],
                "habitify_match": match_habit(slot["behavior"], habit_names),
            }
        )
    return out[:MAX_REGISTRY_ENTRIES]


def build_hypo_candidates(dated_entries):
    """One candidate per distinct cause→effect pair, verbatim quotes as provenance.

    testable = both sides map into the hypothesis engine's metric vocabulary;
    otherwise needs_instrumentation — surfaced, never silently dropped."""
    cands = {}
    for date_str, entry in dated_entries:
        for hint in entry.get("enriched_causal_hints") or []:
            if not isinstance(hint, dict) or not hint.get("cause") or not hint.get("effect"):
                continue
            slug = slugify(hint["cause"], hint["effect"])
            if not slug:
                continue
            slot = cands.setdefault(
                slug,
                {
                    "slug": slug,
                    "cause": str(hint["cause"]),
                    "effect": str(hint["effect"]),
                    "quotes": [],
                    "mentions": 0,
                    "first_seen": date_str,
                    "last_seen": date_str,
                },
            )
            slot["mentions"] += 1
            slot["first_seen"] = min(slot["first_seen"], date_str)
            slot["last_seen"] = max(slot["last_seen"], date_str)
            quote = str(hint.get("quote") or "").strip()
            if quote and len(slot["quotes"]) < MAX_QUOTES_PER_CANDIDATE and quote not in [q["quote"] for q in slot["quotes"]]:
                slot["quotes"].append({"date": date_str, "quote": quote})
    out = []
    for slot in cands.values():
        cause_metric = map_phrase_to_metric(slot["cause"])
        effect_metric = map_phrase_to_metric(slot["effect"])
        slot["cause_metric"] = cause_metric
        slot["effect_metric"] = effect_metric
        slot["status"] = "testable" if (cause_metric and effect_metric and cause_metric != effect_metric) else "needs_instrumentation"
        out.append(slot)
    out.sort(key=lambda s: (-s["mentions"], s["slug"]))
    return out


# ── I/O ───────────────────────────────────────────────────────────────────────


def _to_decimal(obj):
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: _to_decimal(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_decimal(v) for v in obj]
    return obj


def _put(item):
    table.put_item(Item=_to_decimal({k: v for k, v in item.items() if v is not None}))


def fetch_habit_names():
    """Keys of the latest habitify row's habits dict — the behavior-join target."""
    try:
        resp = table.query(
            KeyConditionExpression=Key("pk").eq(f"{USER_PREFIX}habitify"),
            ScanIndexForward=False,
            Limit=1,
        )
        items = resp.get("Items", [])
        if not items:
            return set()
        names = set((items[0].get("habits") or {}).keys())
        names |= set((items[0].get("habit_statuses") or {}).keys())
        return names
    except Exception as e:
        logger.warning(f"habitify names unavailable (join degrades to None): {e}")
        return set()


def lambda_handler(event, context):
    try:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        start_date = (datetime.now(timezone.utc) - timedelta(days=WINDOW_DAYS)).strftime("%Y-%m-%d")

        # ADR-058: registry aggregation is cycle-honest — pilot rows stay hidden.
        from phase_filter import with_phase_filter

        kwargs = {
            "KeyConditionExpression": Key("pk").eq(f"{USER_PREFIX}notion")
            & Key("sk").between(f"DATE#{start_date}#journal", f"DATE#{today}#journal#~"),
        }
        entries = []
        while True:
            resp = table.query(**with_phase_filter(dict(kwargs)))
            entries.extend(_decimal_to_float(resp.get("Items", [])))
            if "LastEvaluatedKey" not in resp:
                break
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
        entries = [e for e in entries if "#journal#" in e.get("sk", "")]

        dated = []
        daily_written = 0
        skipped_unenriched = 0
        for entry in entries:
            parts = entry.get("sk", "").split("#")
            if len(parts) < 2:
                continue
            date_str = parts[1]
            dated.append((date_str, entry))
            row = derive_daily_row(entry, date_str)
            if row is None:
                skipped_unenriched += 1
                continue
            _put(row)
            daily_written += 1

        habit_names = fetch_habit_names()
        entities = build_entity_registry(dated)
        behaviors = build_behavior_registry(dated, habit_names)
        candidates = build_hypo_candidates(dated)

        now_iso = datetime.now(timezone.utc).isoformat()
        common = {
            "pk": CACHE_PK,
            "built_at": now_iso,
            "analyzer_version": 2,
            "phase": EXPERIMENT_PHASE_CURRENT,
            "n_entries_scanned": len(entries),
        }
        _put({**common, "sk": "ENTITY_REGISTRY#current", "entities": entities, "n_entities": len(entities)})
        _put(
            {
                **common,
                "sk": "BEHAVIOR_REGISTRY#current",
                "behaviors": behaviors,
                "n_behaviors": len(behaviors),
                "n_habitify_matched": sum(1 for b in behaviors if b["habitify_match"]),
            }
        )
        for cand in candidates:
            _put({**common, "sk": f"HYPO_CANDIDATE#{cand['slug']}", **cand})

        result = {
            "entries_found": len(entries),
            "daily_rows_written": daily_written,
            "skipped_unenriched": skipped_unenriched,
            "entities": len(entities),
            "behaviors": len(behaviors),
            "behaviors_habitify_matched": sum(1 for b in behaviors if b["habitify_match"]),
            "hypo_candidates": len(candidates),
            "testable": sum(1 for c in candidates if c["status"] == "testable"),
            "needs_instrumentation": sum(1 for c in candidates if c["status"] == "needs_instrumentation"),
            "date_range": {"start": start_date, "end": today},
        }
        logger.info(f"Journal aggregation complete: {json.dumps(result)}")
        return {"statusCode": 200, "body": json.dumps(result)}
    except Exception as e:
        logger.error(f"Handler failed: {e}")
        raise
