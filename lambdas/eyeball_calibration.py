"""eyeball_calibration.py — the self-grading meal-photo exhibit (#1390, epic #1080).

A meal photo is sent to Haiku vision, which returns a macro **estimate** (calories,
protein, carbs, fat). That estimate is **never** nutrition data — it exists only to be
graded against the day Matthew actually logged in MacroFactor, so the platform can
publish an honest "how wrong is the AI at eyeballing food?" reliability chart rather than
launder a guess into the record (ADR-105's spirit — the platform publishes its own
model's error).

The isolation contract (AC#4 of #1390), made structural:

  * Estimates and their grades live in their OWN partition,
    `USER#matthew#SOURCE#eyeball_estimate` — never the nutrition partition. `write_estimate`
    / `write_grade` assert `pk == EYEBALL_PK` at runtime, so a caller physically cannot
    put an estimate anywhere else through this module.
  * This module never constructs, reads, or writes a nutrition partition key. The MacroFactor
    "truth" is passed IN to `grade_against_truth(...)` as a plain dict the *caller* read — the
    grader is a pure function that takes the numbers and returns error stats. The estimate
    values flow only estimate → grade → aggregate error; they never flow into any nutrition
    field. `tests/test_eyeball_isolation_1390.py` proves both directions statically (grep/AST:
    the eyeball literal appears in no nutrition write path, and this file names no nutrition pk)
    and at runtime (the write guard, and a reliability artifact that carries only aggregate
    error — never a raw macro value).

Budget (AC#5): the vision call routes through `bedrock_client.invoke()` (ADR-062) on the
Haiku tier and is gated by `budget_guard.allow("eyeball_estimate")` — an INTERNAL/self-grading
feature (band 1, pauses first). At ~1 photo/day the metered cost is ~$1/mo (see
`estimated_monthly_cost`).

Design mirrors `lambdas/coach_corrections.py`: a PURE item-builder + mockable
writer/reader taking a boto3 Table as the first arg (FakeDdbTable-testable), Decimal
before every write via the shared `numeric.floats_to_decimal` walker.

v1.0.0 — 2026-07-24 (#1390)
"""

from __future__ import annotations

import json
import statistics
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from numeric import floats_to_decimal

# ── The dedicated partition. NEVER the nutrition partition. ───────────────────
# Written as ONE full literal (not an f-string fragment) so an auditor — and the AST
# isolation guard in tests/test_eyeball_isolation_1390.py — sees the exact partition this
# module is scoped to; EYEBALL_SOURCE is derived from it so the two can never drift.
EYEBALL_PK = "USER#matthew#SOURCE#eyeball_estimate"
EYEBALL_SOURCE = EYEBALL_PK.rsplit("#", 1)[-1]  # "eyeball_estimate"
ESTIMATE_SK_PREFIX = "ESTIMATE#"
GRADE_SK_PREFIX = "GRADE#"

# The four macros estimated + graded. Each maps the platform's internal estimate key
# to the MacroFactor "truth" field name (see lambdas/ai_context.py — total_*).
MACROS = ("calories", "protein_g", "carbs_g", "fat_g")
_TRUTH_FIELD = {
    "calories": "total_calories_kcal",
    "protein_g": "total_protein_g",
    "carbs_g": "total_carbs_g",
    "fat_g": "total_fat_g",
}

# Below this many graded days the reliability chart shows an honest low-n state and
# reports NO summary error statistic (ADR-104/105 — no fabricated precision on thin n).
MIN_N_FOR_STATS = 5

_ID_LEN = 8
_HAIKU_MODEL = "claude-haiku-4-5-20251001"

# Vision prompt — asks ONLY for a macro estimate as strict JSON. It is explicitly told
# this is a calibration estimate, not a food log, so the model is never in a posture of
# "logging" the meal.
_VISION_PROMPT = (
    "You are a calibration probe, NOT a food logger. Estimate the macronutrients of the meal "
    "in this photo as best you can from what is visible. Your estimate will be graded against "
    "the user's own logged truth and never entered as data. Respond with ONLY a JSON object, no "
    'prose: {"calories": <kcal>, "protein_g": <g>, "carbs_g": <g>, "fat_g": <g>, '
    '"confidence": "low|medium|high", "note": "<one short phrase on what you saw>"}'
)


class EyeballIsolationError(AssertionError):
    """Raised when a write through this module targets any pk other than EYEBALL_PK —
    the runtime half of the AC#4 isolation guard."""


# ── Estimate: build + write ───────────────────────────────────────────────────
def build_estimate_item(
    macros: dict[str, Any],
    *,
    image_ref: Optional[str] = None,
    model: str = _HAIKU_MODEL,
    confidence: Optional[str] = None,
    note: Optional[str] = None,
    now: Optional[datetime] = None,
    estimate_id: Optional[str] = None,
) -> dict:
    """PURE: build the DDB item for one vision estimate. No AWS. Decimal-safe.

    `macros` carries the model's per-macro estimate (keys in MACROS). Values are cast to
    Decimal via the shared walker (#1207) before any write. The item is stamped with an
    explicit `data_class: "estimate"` and `never_nutrition: True` marker — a self-describing
    record that it is a graded probe, never nutrition data.
    """
    now = now or datetime.now(timezone.utc)
    estimate_id = estimate_id or uuid.uuid4().hex[:_ID_LEN]
    date_str = now.strftime("%Y-%m-%d")
    est = {m: macros.get(m) for m in MACROS}

    item: dict[str, Any] = {
        "pk": EYEBALL_PK,
        "sk": f"{ESTIMATE_SK_PREFIX}{date_str}#{estimate_id}",
        "estimate_id": estimate_id,
        "date": date_str,
        "estimate": floats_to_decimal(est),
        "model": model,
        "data_class": "estimate",  # not a food log — a graded probe (ADR-105)
        "never_nutrition": True,
        "created_at": now.isoformat(),
    }
    if confidence not in (None, ""):
        item["confidence"] = str(confidence)
    if note not in (None, ""):
        item["note"] = str(note)
    if image_ref not in (None, ""):
        item["image_ref"] = str(image_ref)
    return item


def _assert_eyeball_partition(item: dict) -> None:
    if item.get("pk") != EYEBALL_PK:
        raise EyeballIsolationError(f"eyeball_calibration may only write pk={EYEBALL_PK!r}; refused pk={item.get('pk')!r}")


def write_estimate(table, item: dict) -> str:
    """Put one estimate item. Guards that pk is the eyeball partition (a mis-targeted
    write raises rather than silently landing an estimate in another partition). Returns
    the sk."""
    _assert_eyeball_partition(item)
    table.put_item(Item=item)
    return item["sk"]


# ── Vision inference (budget-gated, Bedrock chokepoint) ───────────────────────
def estimate_from_photo(
    image_b64: str,
    *,
    media_type: str = "image/jpeg",
    invoke_fn=None,
    now: Optional[datetime] = None,
) -> dict:
    """Run the Haiku vision estimate for one meal photo, budget-tier-gated (AC#5).

    Returns one of:
      {"status": "paused", "reason": ...}                 — budget guard blocked it
      {"status": "error", "reason": ...}                  — inference/parse failure
      {"status": "ok", "macros": {...}, "confidence": .., "note": .., "model": ..}

    `invoke_fn` defaults to `bedrock_client.invoke` (ADR-062 chokepoint) but is injectable
    for tests so no AWS/Bedrock is touched offline. Isolation: this returns a plain estimate
    dict — it does NOT write anything and knows nothing about DynamoDB; storage is the
    caller's separate, guarded step via `write_estimate`.
    """
    try:
        import budget_guard

        if not budget_guard.allow("eyeball_estimate"):
            return {"status": "paused", "reason": "budget tier — eyeball calibration paused (internal/self-grading feature)"}
    except ImportError:
        pass  # fail-open: never break on a guard-import blip

    if invoke_fn is None:
        from bedrock_client import invoke as invoke_fn  # lazy so offline tests need no boto3

    body = {
        "max_tokens": 300,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": image_b64}},
                    {"type": "text", "text": _VISION_PROMPT},
                ],
            }
        ],
    }
    try:
        resp = invoke_fn(body, model_name=_HAIKU_MODEL)
        text = _first_text(resp)
        parsed = _parse_macro_json(text)
    except Exception as e:  # noqa: BLE001 — any inference/parse failure degrades to a soft error
        return {"status": "error", "reason": str(e)}

    if parsed is None:
        return {"status": "error", "reason": "vision response did not contain a parseable macro JSON object"}

    macros = {m: parsed.get(m) for m in MACROS}
    return {
        "status": "ok",
        "macros": macros,
        "confidence": parsed.get("confidence"),
        "note": parsed.get("note"),
        "model": _HAIKU_MODEL,
    }


def _first_text(resp: dict) -> str:
    for block in resp.get("content", []) or []:
        if isinstance(block, dict) and block.get("type") == "text":
            return block.get("text", "") or ""
    return ""


def _parse_macro_json(text: str) -> Optional[dict]:
    """Extract the first JSON object from the model text. Returns None if none parses."""
    if not text:
        return None
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        obj = json.loads(text[start : end + 1])
    except (json.JSONDecodeError, ValueError):
        return None
    return obj if isinstance(obj, dict) else None


# ── Grading (pure; truth is passed in, never read from a nutrition partition) ──
def grade_against_truth(estimate_macros: dict[str, Any], truth: Optional[dict]) -> dict:
    """PURE: grade one estimate against the MacroFactor `truth` dict for that day.

    `truth` is the logged-day dict the CALLER read (keys like `total_calories_kcal`) — this
    module never touches the nutrition partition itself, which is what keeps the estimate
    values structurally unable to flow the other way.

    Returns a grade dict with per-macro signed error, absolute error, and percent error.
    If truth is absent or a macro's truth value is missing/zero, that macro grades as
    `null` (honest-absence, ADR-104) — an estimate is NEVER credited or laundered into a
    number when there is nothing to grade it against. `status` is "graded" only if at least
    one macro could be graded, else "ungraded".
    """
    per_macro: dict[str, Any] = {}
    graded_any = False
    for m in MACROS:
        est = _num(estimate_macros.get(m))
        tv = _num((truth or {}).get(_TRUTH_FIELD[m]))
        if est is None or tv is None or tv == 0:
            per_macro[m] = None  # nothing honest to say
            continue
        signed = est - tv
        per_macro[m] = {
            "estimate": est,
            "truth": tv,
            "signed_error": signed,
            "abs_error": abs(signed),
            "pct_error": (signed / tv) * 100.0,
        }
        graded_any = True
    return {"status": "graded" if graded_any else "ungraded", "macros": per_macro}


def build_grade_item(
    estimate_id: str,
    grade: dict,
    *,
    date: Optional[str] = None,
    now: Optional[datetime] = None,
) -> dict:
    """PURE: build the DDB item for one grade, in the eyeball partition. Decimal-safe."""
    now = now or datetime.now(timezone.utc)
    date_str = date or now.strftime("%Y-%m-%d")
    item: dict[str, Any] = {
        "pk": EYEBALL_PK,
        "sk": f"{GRADE_SK_PREFIX}{date_str}#{estimate_id}",
        "estimate_id": estimate_id,
        "date": date_str,
        "grade": floats_to_decimal(grade),
        "data_class": "grade",
        "never_nutrition": True,
        "graded_at": now.isoformat(),
    }
    return item


def write_grade(table, item: dict) -> str:
    """Put one grade item, guarded to the eyeball partition. Returns the sk."""
    _assert_eyeball_partition(item)
    table.put_item(Item=item)
    return item["sk"]


# ── Reliability artifact (pure; the public chart's data) ──────────────────────
def build_reliability_artifact(grades: list[dict], *, min_n: int = MIN_N_FOR_STATS, as_of: Optional[str] = None) -> dict:
    """PURE: aggregate graded estimates into the public reliability artifact.

    Emits, per macro: n, mean absolute percent error (MAPE), median absolute percent error,
    bias (mean signed percent error), and a simple recent-vs-earlier trend of MAPE. Honest
    states (ADR-104/105):
      * n == 0  → `state: "empty"`, no statistics at all.
      * n < min_n → `state: "low_n"`, per-macro `sufficient: false`, statistics WITHHELD
        (reported as null) — a handful of photos cannot support a precision claim.
      * n >= min_n → `state: "reported"`, statistics present with n attached.

    The artifact carries ONLY aggregate error stats — never a raw macro estimate or truth
    value — so nothing in it can be mistaken for, or re-ingested as, nutrition data.
    """
    # Collect per-macro pct-error series in chronological order (grades pre-sorted by sk/date).
    series: dict[str, list[float]] = {m: [] for m in MACROS}
    graded_dates: set[str] = set()
    for g in grades:
        macros = ((g.get("grade") or {}).get("macros")) or {}
        date = g.get("date")
        any_here = False
        for m in MACROS:
            cell = macros.get(m)
            pe = _num((cell or {}).get("pct_error")) if isinstance(cell, dict) else None
            if pe is not None:
                series[m].append(pe)
                any_here = True
        if any_here and date:
            graded_dates.add(str(date))

    n_days = len(graded_dates)
    artifact: dict[str, Any] = {
        "source": EYEBALL_SOURCE,
        "as_of": as_of or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "n_days": n_days,
        "min_n": min_n,
        "macros": {},
        "disclaimer": (
            "These are the AI's meal-photo macro ESTIMATES graded against the day's logged "
            "MacroFactor truth. Estimates are never entered as nutrition data — they exist only "
            "to be graded here (ADR-105)."
        ),
    }

    if n_days == 0:
        artifact["state"] = "empty"
        for m in MACROS:
            artifact["macros"][m] = {"n": 0, "sufficient": False, "mape_pct": None, "median_abs_pct": None, "bias_pct": None}
        return artifact

    artifact["state"] = "reported" if n_days >= min_n else "low_n"
    for m in MACROS:
        vals = series[m]
        n = len(vals)
        sufficient = n >= min_n
        if sufficient:
            abs_vals = [abs(v) for v in vals]
            stats = {
                "n": n,
                "sufficient": True,
                "mape_pct": _round(statistics.fmean(abs_vals), 1),
                "median_abs_pct": _round(statistics.median(abs_vals), 1),
                "bias_pct": _round(statistics.fmean(vals), 1),
                "trend": _trend(abs_vals),
            }
        else:
            # Honest low-n: keep the count, withhold every statistic.
            stats = {"n": n, "sufficient": False, "mape_pct": None, "median_abs_pct": None, "bias_pct": None}
        artifact["macros"][m] = stats
    return artifact


def _trend(abs_vals: list[float]) -> Optional[dict]:
    """Recent-half vs earlier-half mean absolute percent error. None if too short to split
    meaningfully (< 4 points) — no trend claim on a couple of readings."""
    if len(abs_vals) < 4:
        return None
    mid = len(abs_vals) // 2
    earlier = statistics.fmean(abs_vals[:mid])
    recent = statistics.fmean(abs_vals[mid:])
    direction = "improving" if recent < earlier else ("worsening" if recent > earlier else "flat")
    return {"earlier_mape_pct": _round(earlier, 1), "recent_mape_pct": _round(recent, 1), "direction": direction}


# ── Reads (partition query + client-side filter, no GSI) ──────────────────────
def _query_partition(table, sk_prefix: str) -> list[dict]:
    from boto3.dynamodb.conditions import Key

    items: list[dict] = []
    kwargs = {"KeyConditionExpression": Key("pk").eq(EYEBALL_PK) & Key("sk").begins_with(sk_prefix)}
    while True:
        resp = table.query(**kwargs)
        items.extend(resp.get("Items", []))
        lek = resp.get("LastEvaluatedKey")
        if not lek:
            break
        kwargs["ExclusiveStartKey"] = lek
    return items


def list_estimates(table) -> list[dict]:
    """All estimate items, oldest-first (sk carries the date)."""
    return sorted(_query_partition(table, ESTIMATE_SK_PREFIX), key=lambda i: i.get("sk", ""))


def list_grades(table) -> list[dict]:
    """All grade items, oldest-first."""
    return sorted(_query_partition(table, GRADE_SK_PREFIX), key=lambda i: i.get("sk", ""))


# ── Cost (AC#5 — measured, recorded in the PR) ────────────────────────────────
def estimated_monthly_cost(photos_per_day: float = 1.0) -> dict:
    """Estimate monthly Bedrock spend for the eyeball probe using the SAME pricing table
    the platform meters with (`bedrock_client.estimate_cost_usd`). A meal photo at Bedrock's
    Claude image tiling is ~1,600 input tokens; the prompt adds ~120; the JSON reply is ~90
    output tokens. Pure — unit-testable, no AWS."""
    from bedrock_client import estimate_cost_usd, resolve_model_id

    per_call_usage = {"input_tokens": 1600 + 120, "output_tokens": 90}
    model_id = resolve_model_id(_HAIKU_MODEL)
    per_call = estimate_cost_usd(per_call_usage, model_id)
    monthly = per_call * photos_per_day * 30.0
    return {"per_call_usd": round(per_call, 6), "photos_per_day": photos_per_day, "monthly_usd": round(monthly, 4), "model": model_id}


# ── small numeric helpers ─────────────────────────────────────────────────────
def _num(v: Any) -> Optional[float]:
    if isinstance(v, bool) or v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _round(v: float, places: int) -> float:
    return round(v, places)
