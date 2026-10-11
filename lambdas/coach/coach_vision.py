"""coach_vision.py — the weekly coach-vision observation over the progress photos (#3759).

WHAT THIS IS

The read half of #3743. Every Monday the `coach-vision` Lambda hands the model this
week's progress-photo set and the prior one, asks for ONE qualitative observation and a
body-fat VISUAL ESTIMATE as a low–high band, and writes ONE owner-only record beside the
DEXA value and the tape trend the estimate was anchored against. Nothing here is public,
nothing here is a measurement, and no reader surface — not the site, not an email, not a
chronicle, not a coach narrative — reads the record (`tests/test_coach_vision_isolation_3759.py`
is what holds that; the only consumers are the owner's MCP tool and his own Telegram
coach thread).

WHY THE BAND, THE LABEL AND THE ANCHORS ARE ONE FIELD

A model's body-fat read from a photograph is a guess with wide uncertainty. ADR-105
requires uncertainty on every statistical claim and ADR-104 forbids a sentence that
sounds more certain than its source, so the estimate is stored as `low_pct`–`high_pct`
with the literal `ESTIMATE_LABEL` travelling ON the field, and the DEXA figure + the tape
trend it was shown ride in the same record. A consumer that reads the number reads the
label and the anchors with it; there is no way to pull `body_fat_pct` out of this record
as if a scale had said it.

WHAT IS DELIBERATELY NARROW

  * ONE call per week, ≤ `MAX_IMAGES` images, through `bedrock_client.invoke()` — the
    ADR-062 chokepoint — on the `coach_vision` route of `ai.model_routing` (the VISION
    tier). The image block built here is a registered site in
    `tests/test_shared_image_prepare_3079.py`: a camera JPEG from the raw zone, never a
    page capture off disk, never a second screenshot path.
  * The S3 keys are the ones the capture (#3758) wrote on the index row — never
    constructed here — and every key is checked against the registry's own
    `raw_layout.prefix` facet before a byte is read (ADR-154: read the facet, never
    build the key).
  * Budget-guarded as a READER-NARRATIVE surface: `coach_vision` sits in band 2 of
    `budget_guard._FEATURE_CUTOFF` (ADR-125), so it runs through internal-AI pauses and
    stops when the reader narrative stops. A paused week writes nothing and says so.
  * Grounded: the qualitative text crosses `grounded_generation.grounding_findings` with
    the numbers the model was shown as its only numeric vocabulary and the two set dates
    as its only dates. Fail-CLOSED on the text alone — a flagged observation is withheld,
    the band and the anchors stand (the eyeball-probe precedent, #2430).

Pure and injectable: no boto3 client is constructed here. The Lambda passes the table,
the S3 reader and the invoke function in, which is what makes every branch reachable in
a test with no network and no AWS.
"""

from __future__ import annotations

import base64
import json
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable, Optional

from ai.model_routing import model_for  # #4770: the one model registry
from common.pacific_time import parse_day_key

logger = logging.getLogger(__name__)

SOURCE = "coach_vision"
RECORD_PK = f"USER#matthew#SOURCE#{SOURCE}"
PHOTO_SOURCE = "progress_photos"
PHOTO_INDEX_PK = f"USER#matthew#SOURCE#{PHOTO_SOURCE}"
DEXA_PK = "USER#matthew#SOURCE#dexa"
MEASUREMENTS_PK = "USER#matthew#SOURCE#measurements"

#: The model route (`ai.model_routing.ROUTES`) and the budget feature (`budget_guard._FEATURE_CUTOFF`).
ROUTE = "coach_vision"
BUDGET_FEATURE = "coach_vision"

#: Travels ON the estimate field of every record. A consumer cannot read the band without it.
ESTIMATE_LABEL = "visual estimate, not a measurement"
DATA_CLASS = "visual_estimate"

POSES = ("front", "side", "back")
#: Two sets of three poses. A set with a missing pose sends fewer, never a placeholder.
MAX_IMAGES = 6
#: "This week's" set: the newest set captured within this many days of the run. Older
#: than that and there is no current set — the week is skipped, not back-filled.
CURRENT_SET_MAX_AGE_DAYS = 10
#: Tape sessions are 4–8 weeks apart (the registry's 60-day staleness); the trend reads
#: the two most recent sessions inside this window.
TAPE_WINDOW_DAYS = 120
#: The Telegram thread cites the newest record only while it is this fresh.
THREAD_MAX_AGE_DAYS = 21

MAX_TOKENS = 700

#: The owner-facing field set (`select_fields`). Everything else on the row is plumbing.
OWNER_FIELDS = (
    "as_of",
    "set_dates",
    "qualitative",
    "qualitative_withheld_reason",
    "deltas",
    "body_fat_estimate",
    "anchors",
    "model_id",
    "created_at",
)
DEFAULT_FIELDS = ("as_of", "set_dates", "qualitative", "body_fat_estimate", "anchors", "model_id")

#: Strict output shape — `ai.structured_json.call_json` carries it as `output_config`.
OBSERVATION_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "required": ["qualitative", "deltas", "body_fat_low_pct", "body_fat_high_pct", "confidence"],
    "properties": {
        "qualitative": {"type": "string", "description": "2-4 sentences on what changed visually between the two sets."},
        "deltas": {"type": "array", "items": {"type": "string"}, "description": "Short phrases, one visual change each."},
        "body_fat_low_pct": {"type": "number"},
        "body_fat_high_pct": {"type": "number"},
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
    },
}

_PROMPT = (
    "You are a coach looking at progress photos for a comparison, NOT a measuring instrument. "
    "You are shown up to two sets of front/side/back photos: this week's set and the prior set, each labelled "
    "with its date. Describe what changed visually between the sets in 2-4 plain sentences (posture, "
    "definition, where fullness or leanness moved), then list each change as a short phrase. "
    "Give a body-fat VISUAL ESTIMATE for THIS WEEK's set as a low-high percentage band wide enough to be honest; "
    "it will be stored labelled 'visual estimate, not a measurement' beside the anchors below, which you may use to "
    "calibrate but must not restate as your own finding. Cite no number the anchors do not contain other than your "
    "own band, cite no calendar date except the two set dates, make no claim about diet, training or sleep, and "
    "offer no praise. If only one set is present, say that the comparison is not available and describe the set."
)


# ── sets: grouping the index rows the capture wrote ───────────────────────────
def _row_date(row: dict) -> str:
    d = str(row.get("date") or "")
    if not d:
        sk = str(row.get("sk") or "")
        d = sk.replace("DATE#", "").split("#")[0]
    return d


def group_sets(rows: list) -> list:
    """One set per capture WEEK where the row carries `week_n`, per DATE where it does not.

    The same grouping the private viewer renders (#3760), so the set the coach saw is the
    column he sees. `as_of` is the newest capture date in the set; a retake on a later day
    replaces the earlier pose. Rows with no `s3_key` or an unknown pose are skipped — a set
    is only what was actually stored.
    """
    by_col: dict = {}
    for row in rows or []:
        date = _row_date(row)
        pose = str(row.get("pose") or "")
        key = str(row.get("s3_key") or "")
        if not date or pose not in POSES or not key:
            continue
        week = row.get("week_n")
        try:
            week = int(week) if week is not None else None
        except (TypeError, ValueError):
            week = None
        slot = by_col.setdefault(f"w{week}" if week else f"d{date}", {"week_n": week, "as_of": date, "poses": {}, "sha256": {}})
        slot["as_of"] = max(slot["as_of"], date)
        prior = slot["poses"].get(pose)
        if not prior or date >= prior["date"]:
            slot["poses"][pose] = {"date": date, "key": key}
            if row.get("sha256"):
                slot["sha256"][pose] = str(row.get("sha256"))
    return sorted(by_col.values(), key=lambda s: str(s["as_of"]))


def pick_sets(sets: list, today: str, max_age_days: int = CURRENT_SET_MAX_AGE_DAYS) -> tuple:
    """(current, prior) — this week's set and the one before it, or (None, None).

    `current` is the newest set captured on or before `today` and within `max_age_days`
    of it. A set older than that is not this week's — the run writes nothing rather than
    re-observing a stale set under a new date. `prior` is the newest set before `current`,
    however old: the comparison across a long gap is still the comparison he took the
    photos for.
    """
    t = parse_day_key(today)
    if t is None:
        return None, None
    eligible = []
    for s in sets:
        d = parse_day_key(s["as_of"])
        if d is None or d > t:
            continue
        eligible.append(s)
    if not eligible:
        return None, None
    current = eligible[-1]
    cd = parse_day_key(current["as_of"])
    if cd is None or (t - cd).days > max_age_days:
        return None, None
    before = [s for s in eligible if s["as_of"] < current["as_of"]]
    prior = before[-1] if before else None
    return current, prior


def record_sk(as_of: str) -> str:
    return f"DATE#{as_of}"


def photo_prefix() -> str:
    """The registry's own `raw_layout.prefix` facet for the photos — read, never typed."""
    from ingestion.source_registry import SOURCE_REGISTRY

    return str(SOURCE_REGISTRY[PHOTO_SOURCE]["raw_layout"]["prefix"])


def key_is_under_prefix(key: str, prefix: str) -> bool:
    """A key the index row names must sit under the registry prefix, or it is not read.

    The index is written by one module (#3758) under one prefix; a row pointing anywhere
    else is corruption or an attack, and either way it is not a progress photo.
    """
    return bool(key) and key.startswith(prefix.rstrip("/") + "/") and ".." not in key


# ── anchors: the DEXA and the tape the estimate is shown ──────────────────────
def _num(v: Any) -> Optional[float]:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float, Decimal)):
        return float(v)
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def nearest_dexa(dexa_items: list, as_of: str) -> Optional[dict]:
    """The DEXA scan nearest in time to the photo date, with its body-fat percent.

    Nearest, not latest: a scan three weeks AFTER a back-dated Day-1 set is a better anchor
    for that set than one taken a year before it. Returns None when there is no scan with a
    body-fat figure — an absent anchor is reported as absent, never borrowed.
    """
    target = parse_day_key(as_of)
    best = None
    for item in dexa_items or []:
        scan_date = str(item.get("scan_date") or _row_date(item))
        bc = item.get("body_composition") or {}
        pct = _num(bc.get("body_fat_pct")) if isinstance(bc, dict) else None
        if pct is None:
            pct = _num(item.get("body_fat_pct"))
        d = parse_day_key(scan_date)
        if pct is None or d is None or target is None:
            continue
        gap = abs((target - d).days)
        if best is None or gap < best[0]:
            best = (gap, {"scan_date": scan_date, "body_fat_pct": round(pct, 1), "days_from_set": (target - d).days})
    return best[1] if best else None


def tape_trend(measurement_items: list, as_of: str) -> Optional[dict]:
    """The two most recent tape sessions on or before the photo date, and the waist delta.

    `waist_navel_in` is the one circumference that tracks body fat for a lean-down; the
    chest rides along for context. A single session is reported with no delta — a trend
    needs two points and this says so rather than inventing one.
    """
    sessions = []
    for item in measurement_items or []:
        date = str(item.get("date") or _row_date(item))
        waist = _num(item.get("waist_navel_in"))
        if not date or waist is None or date > as_of:
            continue
        entry = {"session_date": date, "waist_navel_in": round(waist, 2)}
        chest = _num(item.get("chest_in"))
        if chest is not None:
            entry["chest_in"] = round(chest, 2)
        sessions.append(entry)
    if not sessions:
        return None
    sessions.sort(key=lambda s: str(s["session_date"]))
    latest = sessions[-1]
    out: dict = {"latest": latest}
    if len(sessions) >= 2:
        previous = sessions[-2]
        out["previous"] = previous
        out["waist_delta_in"] = round(latest["waist_navel_in"] - previous["waist_navel_in"], 2)
    return out


def anchors_block(dexa: Optional[dict], tape: Optional[dict]) -> str:
    """The anchor text the model is shown — the whole of its legitimate numeric vocabulary."""
    lines = []
    if dexa:
        lines.append(f"Nearest DEXA scan ({dexa['scan_date']}): body fat {dexa['body_fat_pct']}% (a measurement).")
    else:
        lines.append("No DEXA scan on record — there is no measured body-fat anchor.")
    if tape:
        lat = tape["latest"]
        line = f"Tape, latest session {lat['session_date']}: waist at navel {lat['waist_navel_in']} in"
        if "previous" in tape:
            prev = tape["previous"]
            line += f"; previous session {prev['session_date']}: {prev['waist_navel_in']} in (change {tape['waist_delta_in']:+} in)"
        lines.append(line + ".")
    else:
        lines.append("No tape session on record — there is no tape trend to anchor against.")
    return "ANCHORS (measurements the estimate is shown — not yours to restate):\n" + "\n".join(lines)


# ── the request ───────────────────────────────────────────────────────────────
def image_block(data: bytes, media_type: str = "image/jpeg") -> dict:
    """ONE camera JPEG as an Anthropic image content block.

    Registered in `tests/test_shared_image_prepare_3079.py`: not a screenshot path and not
    a second copy of the screenshot prepare — a phone photo is nowhere near the 8000px
    reject bound, and the tiling that path owns would be wrong for a body comparison.
    """
    return {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": base64.b64encode(data).decode("ascii")}}


def build_content(current: dict, prior: Optional[dict], loader: Callable[[str], bytes], anchors_text: str) -> tuple:
    """The user-turn content: labelled images for each set, the anchors, the ask.

    Returns `(content, sent)` where `sent` maps `current`/`prior` → {pose: key} for the
    images that were actually read, so the record names exactly what the model saw.
    """
    content: list = []
    sent: dict = {"current": {}, "prior": {}}
    n = 0
    for label, s in (("THIS WEEK's set", current), ("PRIOR set", prior)):
        if not s:
            continue
        slot = "current" if s is current else "prior"
        content.append({"type": "text", "text": f"{label}, captured {s['as_of']}:"})
        for pose in POSES:
            ref = s["poses"].get(pose)
            if not ref or n >= MAX_IMAGES:
                continue
            try:
                data = loader(ref["key"])
            except Exception as e:  # noqa: BLE001 — one unreadable object drops one image, never the run
                logger.warning("[coach_vision] photo unreadable (%s): %s", type(e).__name__, ref["key"])
                continue
            content.append({"type": "text", "text": f"{pose} ({ref['date']}):"})
            content.append(image_block(data))
            sent[slot][pose] = ref["key"]
            n += 1
    content.append({"type": "text", "text": anchors_text})
    content.append({"type": "text", "text": _PROMPT})
    return content, sent


def build_body(content: list, model: str, max_tokens: int = MAX_TOKENS) -> dict:
    return {"model": model, "max_tokens": max_tokens, "messages": [{"role": "user", "content": content}]}


# ── grounding: the one free-text field crosses the chokepoint ─────────────────
def _grounded_text(text: Optional[str], shown: dict, set_dates: dict, *, now: Optional[datetime] = None) -> tuple:
    """`(text_or_None, reason)` — the qualitative observation after the ADR-104 gate.

    The numeric allow-list is literally what the model was shown plus its own band; the
    only legitimate dates are the two set dates (#1242). Freshness arms the cycle anchors
    (#1691/#1897) so a "Day N" framing smuggled into a photo comparison is checkable here.
    Fail-closed on the TEXT only: a flagged observation is withheld with its reason and the
    band + anchors stand, because dropping the whole record over a phrase would delete the
    week's comparison.
    """
    if not (text or "").strip():
        return None, "model returned no observation"
    from ai import grounded_generation
    from common.constants import EXPERIMENT_START_DATE

    findings = grounded_generation.grounding_findings(
        str(text),
        allowed=grounded_generation.allowed_numbers(shown),
        allowed_dates=grounded_generation.allowed_dates(set_dates),
        generation_date_iso=(now or datetime.now(timezone.utc)).strftime("%Y-%m-%d"),
        start_date_iso=EXPERIMENT_START_DATE,
    )
    if findings:
        kinds = sorted({str(f.get("type") or f.get("kind") or "finding") for f in findings if isinstance(f, dict)}) or ["finding"]
        return None, "withheld by the grounding gate: " + ", ".join(kinds)
    return str(text), ""


# ── the observation ───────────────────────────────────────────────────────────
def observe(
    current: dict,
    prior: Optional[dict],
    anchors: dict,
    *,
    loader: Callable[[str], bytes],
    invoke_fn: Optional[Callable[..., dict]] = None,
    allow_fn: Optional[Callable[[str], bool]] = None,
    model: Optional[str] = None,
    now: Optional[datetime] = None,
) -> dict:
    """ONE vision call for one week, budget-gated and schema-shaped.

    Returns one of:
      {"status": "paused", "reason": ...}   — the budget guard stood it down (nothing billed)
      {"status": "error", "reason": ...}    — inference/shape failure (nothing fabricated)
      {"status": "ok", "observation": {...}, "sent": {...}, "model": ...}
    Writes nothing and constructs no client: storage is the caller's separate step.
    """
    if allow_fn is None:
        try:
            from ai import budget_guard

            allow_fn = budget_guard.allow
        except ImportError:  # fail-open on a guard-import blip, like every other caller
            allow_fn = lambda _f: True  # noqa: E731
    if not allow_fn(BUDGET_FEATURE):
        return {"status": "paused", "reason": "budget tier — coach vision paused with the reader-narrative band (ADR-125)"}

    if invoke_fn is None:
        from ai.bedrock_client import invoke as _invoke  # lazy so offline tests need no boto3

        invoke_fn = _invoke
    send: Callable[..., dict] = invoke_fn
    model = model or model_for("coach_vision")  # == ROUTE; the literal is what the #4770 caller census reads
    anchors_text = anchors_block(anchors.get("dexa"), anchors.get("tape_trend"))
    content, sent = build_content(current, prior, loader, anchors_text)
    if not sent["current"]:
        return {"status": "error", "reason": "no readable photo in this week's set"}

    from ai.structured_json import call_json, decode_error, schema_findings

    body = build_body(content, model)
    try:
        parsed = call_json(lambda b: send(b, model_name=model), body, schema=OBSERVATION_SCHEMA, label="coach_vision")
    except Exception as e:  # noqa: BLE001 — any inference failure degrades to a soft error
        return {"status": "error", "reason": f"{type(e).__name__}: {e}"}
    if not isinstance(parsed, dict):
        return {"status": "error", "reason": decode_error(parsed)}
    problems = schema_findings(parsed, OBSERVATION_SCHEMA)
    if problems:
        return {"status": "error", "reason": "observation off-schema: " + "; ".join(problems[:3])}
    low, high = _num(parsed.get("body_fat_low_pct")), _num(parsed.get("body_fat_high_pct"))
    if low is None or high is None or not (0 < low <= high < 70):
        return {"status": "error", "reason": f"implausible band {low}-{high}"}

    set_dates = {"current": current["as_of"], "prior": prior["as_of"] if prior else None}
    # The set dates ride in `shown` as well as in the date allow-list: the number gate reads
    # the digits of a cited date ("the 2026-09-28 set" → 28) and must find them legitimate.
    shown = {"anchors": anchors, "band": [low, high], "anchors_text": anchors_text, "set_dates": set_dates}
    text, reason = _grounded_text(parsed.get("qualitative"), shown, set_dates, now=now)
    observation = {
        "qualitative": text,
        "qualitative_withheld_reason": reason or None,
        "deltas": [str(d) for d in (parsed.get("deltas") or []) if str(d).strip()][:8],
        "body_fat_low_pct": round(low, 1),
        "body_fat_high_pct": round(high, 1),
        "confidence": str(parsed.get("confidence") or "low"),
    }
    return {"status": "ok", "observation": observation, "sent": sent, "model": model}


def build_record(current: dict, prior: Optional[dict], anchors: dict, result: dict, *, created_at: Optional[str] = None) -> dict:
    """PURE: the owner-only DDB item for one week's observation. Floats; the writer casts."""
    obs = result["observation"]
    return {
        "pk": RECORD_PK,
        "sk": record_sk(current["as_of"]),
        "source": SOURCE,
        "data_class": DATA_CLASS,
        "as_of": current["as_of"],
        "set_dates": {"current": current["as_of"], "prior": prior["as_of"] if prior else None},
        "photo_keys": result["sent"],
        "qualitative": obs["qualitative"],
        "qualitative_withheld_reason": obs["qualitative_withheld_reason"],
        "deltas": obs["deltas"],
        "body_fat_estimate": {
            "low_pct": obs["body_fat_low_pct"],
            "high_pct": obs["body_fat_high_pct"],
            "label": ESTIMATE_LABEL,
            "confidence": obs["confidence"],
        },
        "anchors": {"dexa": anchors.get("dexa"), "tape_trend": anchors.get("tape_trend")},
        "model_id": result["model"],
        "created_at": created_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


# ── consumers: field-selective, owner-only ────────────────────────────────────
def select_fields(record: dict, fields: Optional[list] = None) -> dict:
    """The owner-facing projection. Unknown field names are ignored; the estimate always
    carries its label because the label is part of the field, not a sibling of it."""
    wanted = [f for f in (fields or DEFAULT_FIELDS) if f in OWNER_FIELDS] or list(DEFAULT_FIELDS)
    return {f: record.get(f) for f in wanted}


def thread_lines(record: Optional[dict], today: str, max_age_days: int = THREAD_MAX_AGE_DAYS) -> list:
    """The lines the owner's Telegram coach thread may cite — label and anchors inline.

    Empty when there is no record or it is older than `max_age_days`: a stale observation
    quoted as current is the ADR-104 defect in a chat bubble.
    """
    if not record:
        return []
    as_of, t = parse_day_key(str(record.get("as_of") or "")), parse_day_key(today)
    if as_of is None or t is None or (t - as_of).days > max_age_days or as_of > t:
        return []
    est = record.get("body_fat_estimate") or {}
    low, high = _num(est.get("low_pct")), _num(est.get("high_pct"))
    sets = record.get("set_dates") or {}
    head = f"Progress photos, coach-vision read of the {record.get('as_of')} set"
    head += f" against the {sets['prior']} set" if sets.get("prior") else " (no prior set to compare)"
    lines = [head + ":"]
    if record.get("qualitative"):
        lines.append(str(record["qualitative"]))
    else:
        lines.append("The written observation was withheld by the grounding gate; only the band and the anchors stand.")
    if low is not None and high is not None:
        lines.append(f"Body fat {low:g}-{high:g}% — {ESTIMATE_LABEL} (confidence {est.get('confidence', 'low')}).")
    anchors = record.get("anchors") or {}
    dexa = anchors.get("dexa") or {}
    if dexa.get("body_fat_pct") is not None:
        lines.append(f"Anchored to the DEXA of {dexa.get('scan_date')}: {_num(dexa['body_fat_pct']):g}% measured.")
    tape = anchors.get("tape_trend") or {}
    lat = tape.get("latest") or {}
    if lat.get("waist_navel_in") is not None:
        line = f"Tape {lat.get('session_date')}: waist {_num(lat['waist_navel_in']):g} in"
        if tape.get("waist_delta_in") is not None:
            line += f" ({_num(tape['waist_delta_in']):+g} in on the prior session)"
        lines.append(line + ".")
    return lines


def latest_record(table) -> Optional[dict]:
    """The newest observation row, or None. Read-only; one Query on the owner partition."""
    resp = table.query(
        KeyConditionExpression="pk = :pk AND begins_with(sk, :pfx)",
        ExpressionAttributeValues={":pk": RECORD_PK, ":pfx": "DATE#"},
        ScanIndexForward=False,
        Limit=1,
    )
    items = resp.get("Items") or []
    return items[0] if items else None


def thread_block(table, today: Optional[str]) -> str:
    """The Telegram facts addendum, or "" — fail-soft, like the domain pack it rides beside."""
    if not today:
        return ""
    try:
        rec = latest_record(table)
    except Exception as e:  # noqa: BLE001 — a read that fails leaves the coach without the pack, not without a voice
        logger.warning("[coach_vision] thread read failed: %s", type(e).__name__)
        return ""
    lines = thread_lines(rec, today)
    return ("COACH VISION (owner-only; the band is an estimate, never a measurement):\n" + "\n".join(lines)) if lines else ""


def as_json_safe(obj: Any) -> Any:
    """Decimal → float for a record read back from DynamoDB."""
    return json.loads(json.dumps(obj, default=lambda v: float(v) if isinstance(v, Decimal) else str(v)))
