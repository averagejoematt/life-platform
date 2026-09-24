"""
training_notes_llm.py — bounded Haiku tail for the training-notes extractor.

The semantic signals a regex can't get (rpe_caveat, nuanced limiter/form, sentiment
shading) come from the cheapest capable model, bounded exactly like the meal namer:
non-empty notes only (the writer already skips blanks), constrained JSON out, a
hash-cache so an unchanged note never re-extracts, and a monthly call cap with a
fail-safe to deterministic-only (the caller's extract_signals catches any exception
here and sets degraded:true — Invariant 4, never drop a note).

The Bedrock endpoint is isolated in `_haiku_call` so the future model swap touches one
function. `table` is injected for the cache + cap so this stays unit-testable.

EVERY degrade path names itself (#3699). Before this, three fail-soft sites shared one
outcome and no cause: the caller's `except` set `degraded: true` with no reason, and BOTH
parse failures here returned `[]` with no exception at all — so a truncated or unparseable
extraction was recorded as a SUCCESSFUL one that simply found nothing (`used_llm=True`,
`degraded=False`, `extracted_by="hybrid"`). That made `degraded` an undercount and
`extractor_dark` a floor rather than the number. Now each site raises an `ExtractionDegraded`
subclass carrying a stable `degrade_code`, the caller persists it as `degraded_reason` on the
record, and the reason survives log retention.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from common.numeric import decimals_to_float, floats_to_decimal

logger = logging.getLogger(__name__)

HAIKU_MODEL = "claude-haiku-4-5-20251001"

# MAX_TOKENS is DERIVED from a measurement, not chosen as a round number (#3699; the
# #3678/#3403 class — a budget set from a stale observation and never re-derived). 256 was
# a guess written the day this shipped, and until then a breach of it was INVISIBLE: the cap
# truncates, `_parse_signals` returned [] and nothing said the output had been cut off.
#
# RE-DERIVED 2026-09-19 (#3817 box 5, #3828 box 2) because the taxonomy grew — which is the
# first clause of the `re_derive_when` facet below, and the honest trigger here. The OTHER
# clause ("TruncatedResponse is ever observed live") has still NOT fired: zero records in the
# live partition carry `degraded_reason` starting `truncated` (whole-partition scan, n=40 head
# records, 2026-09-19). Stated precisely, because 12 of those 40 are `degraded: true` with NO
# reason field at all (written before #3699 existed): what is measured is that no truncation
# has ever been RECORDED, not that none ever happened on the 12 that could not say. The cap is
# being raised because the output can now get bigger, not because anything was cut off.
#
# Two channels, because neither alone covers the corpus:
#   * METERED — LifePlatform/AI::AnthropicOutputTokens{LambdaFunction=hevy-backfill}, the
#     per-function metric, which is this extractor alone (it is the only AI call that Lambda
#     makes). 2026-09-14 → 2026-09-19: n=21 billed calls, sum 2,001, max 161. Useful but
#     PARTIAL: it only exists for calls made after #3768 restored the Bedrock grant, and the
#     minute-bucket aggregation hides the per-sample distribution (15 of the 21 land in ONE
#     60s bucket).
#   * CORPUS PROXY — the serialized `signals` array of every stored record (n=40, DDB scan of
#     USER#matthew#SOURCE#training_notes#EXERCISE#*, 2026-09-19), converted to tokens at the
#     ratio measured where the two channels are 1:1: the 15 records extracted on 2026-09-14
#     hold 3,676 chars against those calls' 1,444 output tokens = 2.546 chars/token. The proxy
#     is CONSERVATIVE in the direction that matters — stored signals UNDERCOUNT the model's own
#     array wherever deterministic precedence dropped an overlapping element, so a given char
#     count maps to more tokens, not fewer.
MAX_TOKENS_DERIVATION = {
    "metric": (
        "LifePlatform/AI::AnthropicOutputTokens{LambdaFunction=hevy-backfill} (n=21 metered calls, max 161) "
        "cross-checked against the serialized-signals corpus proxy (n=40 stored records) at 2.546 chars/token"
    ),
    "window": "2026-09-14 → 2026-09-19 metered; the whole live note partition read 2026-09-19",
    "n": 40,
    "metered_n": 21,
    "min": 1,
    "p50": 79,
    "p90": 159,
    "p95": 168,
    "p99": 192,
    "max": 207,
    "growth_head_room_tokens": 58,
    "projected_post_change_max": 265,
    "rule": (
        "2x the greater of the measured max (207) and the projected post-change max "
        "(207 + one calibration element at the measured per-signal max of 148 chars = 58 tok -> 265), "
        "rounded up to the next 128-token step"
    ),
    "re_derive_when": "the taxonomy grows, the summary word budget changes, or TruncatedResponse is ever observed live",
}
# The change this re-derivation is for (#3817) adds ONE class to the model's allowed set
# (`calibration`); the per-block progression split and the readiness join key are both
# deterministic and cost the model nothing. So the growth is bounded at one extra array
# element, sized at the measured per-signal MAXIMUM (148 chars = 58 tok), not its mean.
# 2 x 265 = 530 -> 640. max_tokens is a CEILING, not a charge — billing is on tokens actually
# emitted — so the headroom costs $0 until it is used, while a breach degrades LOUDLY.
MAX_TOKENS = 640

# ── The monthly CALL cap, per lane (#4151) ────────────────────────────────────
# 300 was written the day this layer shipped (2026-06-21, #187 — "monthly cap ~300" in
# ADR-094) with no measurement behind it. It is now DERIVED, and it is charged PER LANE:
#
#   * `live` — the on-ingest hook in hevy-backfill, one call per NEW note text.
#   * `bulk` — every sweep: `reextract_days`, `deploy/backfill_training_notes.py`.
#
# The split is the fix for #4151's specimen: the attended historical backfill of 2026-09-19
# spent ~277 of September's 301 calls on notes from 2021-2023, and from that instant every
# new session the owner logged degraded to deterministic-only (`cap_exceeded` on 25 of 28
# sessions in the 14-day health window). A sweep can no longer starve the live path.
#
# The OTHER half of the specimen was the hash cache (see `cache_put`): it never held a
# non-empty extraction, so each of the corpus's 566 noted sessions was billed although they
# carry only 111 distinct note texts. With the cache working, a full-corpus pass costs at
# most the distinct-note count, and that is what the bulk number below is sized on.
MONTHLY_CAP_DERIVATION = {
    "metric": (
        "noted exercise-sessions per month (SOURCE#hevy, non-empty exercise notes) for the live lane; "
        "distinct note_hash over every head record in USER#matthew#SOURCE#training_notes#EXERCISE#* for the bulk lane; "
        "per-call cost from LifePlatform/AI::EstimatedCostUSD{LambdaFunction=hevy-backfill}"
    ),
    "window": "SOURCE#hevy 2025-09-01 → 2026-09-23; the whole note partition + the metric 2026-09-01 → 2026-09-23, read 2026-09-23",
    "live_monthly_noted_sessions": {"2025-10": 1, "2026-06": 21, "2026-09 (to the 23rd)": 30},
    "live_projected_peak_month": 39,
    "bulk_corpus_head_records": 566,
    "bulk_corpus_distinct_notes": 111,
    "cost_per_call_usd": {"n": 24, "mean": 0.00066, "max": 0.00101},
    "rule": (
        "each lane: at least 2x its measured demand, rounded up to the next 100. live: 2 x 39 = 78, "
        "and the 2026-06-21 value of 300 already clears it by 7.7x, so it is RETAINED rather than cut (an edited "
        "note mints a new hash and a new call, and that edit rate has never been measured). bulk: 2 x 111 = 222 -> 300. "
        "Worst case both lanes at cap = 600 x $0.00101 = $0.61/month"
    ),
    "re_derive_when": "a live month exceeds 150 noted sessions, the distinct-note corpus exceeds 150, or cap_exceeded is recorded on either lane",
}
DEFAULT_MONTHLY_CAP = 300  # per lane — see MONTHLY_CAP_DERIVATION
LANES = ("live", "bulk")

_CACHE_PK = "USER#matthew#SOURCE#training_notes#CACHE"
_USAGE_PK = "USER#matthew#SOURCE#training_notes#USAGE"

_SYSTEM = (
    "You extract structured training signals from one freeform note a lifter wrote on a single "
    "exercise. Return ONLY a compact JSON array; each element {class, summary, value?, confidence}. "
    "class MUST be one of the allowed classes. summary <= 12 words. confidence 0-1. Emit a class "
    "only if the note clearly supports it; [] if nothing semantic. Never invent numbers. "
    "pain_discomfort ONLY for joint/tendon/bad pain (NOT normal muscle burn/soreness). "
    # #3817: the class is new and its whole point is the distinction the model has to make.
    'calibration ONLY for what a level/load MEANS for this athlete in general ("L9-10 is easy '
    'for my weight") — never for how one session went, which is progression.'
)


class ExtractionDegraded(Exception):
    """The Haiku tail produced no usable signals, and says WHY (#3699).

    `degrade_code` is the stable machine token the record carries in `degraded_reason`
    (`training_notes.DEGRADE_CODES`); the message is the human detail. NEVER put the note
    text (or the model's response, which is derived from it) in the message — the reason
    rides a WARNING log line and raw notes are owner-private (ADR-104 / Tier-2).
    """

    degrade_code = "llm_error"


class CapExceeded(ExtractionDegraded):
    """Monthly Haiku call cap reached — caller degrades to deterministic-only."""

    degrade_code = "cap_exceeded"


class TruncatedResponse(ExtractionDegraded):
    """Bedrock stopped at `max_tokens` — the JSON array is cut off mid-array.

    Read from `stop_reason`, which Bedrock supplies, never inferred from the text: a
    truncated array that happens to end on a `]` would parse and look complete.
    """

    degrade_code = "truncated"


class UnparseableResponse(ExtractionDegraded):
    """The response carried no well-formed in-taxonomy JSON array."""

    degrade_code = "unparseable"


def _haiku_call(note_text: str, taxonomy) -> list:
    """The single Bedrock chokepoint for this feature. Returns a list of raw signals."""
    from ai.bedrock_client import invoke

    allowed = ", ".join(sorted(taxonomy))
    body = {
        "model": HAIKU_MODEL,
        "max_tokens": MAX_TOKENS,
        "system": f"{_SYSTEM}\nAllowed classes: {allowed}.",
        "messages": [{"role": "user", "content": f"Note: {note_text}\nReturn the JSON array."}],
    }
    resp = invoke(body, model_name=HAIKU_MODEL)
    text = "".join(part.get("text", "") for part in resp.get("content", []) if part.get("type") == "text").strip()
    # #3699: truncation is read from Bedrock's own stop_reason BEFORE the parse. A response
    # cut off at the cap is billed in full and yields a partial array; parsing it (or failing
    # to) and calling the result "no signals" is the silent undercount this issue is about.
    # #3828: this is the 4th member of #3688's judge Set and it deliberately does NOT retry.
    # The cap and the note text are both fixed, so a truncation here is DETERMINISTIC — a retry
    # loop would bill N times for N identical failures. The right response is the `re_derive_when`
    # facet above: re-derive MAX_TOKENS against the observed output distribution. That was done on
    # 2026-09-19 (384 -> 640) when #3817 grew the taxonomy — see MAX_TOKENS_DERIVATION. It stays a
    # residual rather than becoming covered, because the re-derivation is the remedy and the retry
    # is not; registered in tests/test_judge_verdict_retry_3688.py::_RESIDUAL so the Set guard
    # stays honest.
    if (resp.get("stop_reason") or "") == "max_tokens":
        out_tok = (resp.get("usage") or {}).get("output_tokens")
        raise TruncatedResponse(f"stop_reason=max_tokens at max_tokens={MAX_TOKENS} (output_tokens={out_tok}, {len(text)} chars of text)")
    return _parse_signals(text, taxonomy)


def _parse_signals(text: str, taxonomy) -> list:
    """Parse the model's JSON array defensively; keep only well-formed in-taxonomy signals.

    RAISES `UnparseableResponse` where it used to `return []` (#3699). An empty list is a
    CLAIM — "the model read this note and found nothing semantic" — and returning it for a
    response that could not be read at all made a broken extraction indistinguishable from
    a quiet one. Only a response that genuinely parsed to `[]` still returns `[]`.

    Messages carry lengths and parser positions, never the response text (it is derived from
    the owner-private note).
    """
    if not text:
        raise UnparseableResponse("empty response — no text content block")
    # Tolerate a fenced block or leading prose: grab the first [...] span.
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1 or end < start:
        raise UnparseableResponse(f"no JSON array span in a {len(text)}-char response")
    span = text[start : end + 1]  # noqa: E203
    try:
        arr = json.loads(span)
    except (ValueError, TypeError) as e:
        raise UnparseableResponse(f"json.loads failed on a {len(span)}-char span: {type(e).__name__}: {e}") from e
    out = []
    for s in arr if isinstance(arr, list) else []:
        if not isinstance(s, dict):
            continue
        cls = s.get("class")
        if cls not in taxonomy:
            continue
        try:
            conf = float(s.get("confidence", 0.5))
        except (ValueError, TypeError):
            conf = 0.5
        sig = {"class": cls, "summary": str(s.get("summary", ""))[:120], "confidence": max(0.0, min(1.0, conf))}
        if s.get("value") is not None:
            sig["value"] = s["value"]
        out.append(sig)
    # The fourth site, not in #3699's Set of three: the array parsed but EVERY element was
    # dropped (off-taxonomy class, or not a dict at all). "0 of N kept" is a schema
    # violation, not a quiet note, and returning [] here would rebuild the same undercount
    # one layer down. A genuinely empty array (`[]`) never reaches this branch.
    if not out and isinstance(arr, list) and arr:
        raise UnparseableResponse(f"{len(arr)} element(s) returned, 0 in taxonomy or well-formed")
    return out


# ── Hash-cache + monthly cap (table injected) ──
def _month(now=None):
    return (now or datetime.now(timezone.utc)).strftime("%Y-%m")


def usage_sk(now=None, lane: str = "live") -> str:
    """The per-lane monthly counter key (#4151): `MONTH#YYYY-MM#<lane>`.

    Rows keyed plain `MONTH#YYYY-MM` were written before the split, when one counter was
    charged by BOTH lanes. They are history, left as they are: the 301 in `MONTH#2026-09`
    cannot be divided between the lanes after the fact (the Lambda metric accounts for 24;
    the rest were the attended backfill, which is unmetered). Nothing reads them now.
    """
    if lane not in LANES:
        raise ValueError(f"unknown training-notes cap lane {lane!r} (expected one of {LANES})")
    return f"MONTH#{_month(now)}#{lane}"


def cache_get(table, note_hash: str):
    try:
        r = table.get_item(Key={"pk": _CACHE_PK, "sk": f"HASH#{note_hash}"})
        it = r.get("Item")
        # #4151: stored as Decimal (see cache_put). Hand back the same float shape a model
        # call returns, so a cache hit and a fresh extraction are indistinguishable downstream.
        return decimals_to_float(it.get("signals")) if it else None
    except Exception:
        return None


def cache_put(table, note_hash: str, signals: list):
    """Best-effort — but never SILENT again (#4151).

    `signals` carries float `confidence` values, and boto3 rejects a float with
    `TypeError: Float types are not supported`. The write used to hand them over raw under a
    bare `except: pass`, so from 2026-06-21 to #4151 the cache never held a single non-empty
    extraction: all 19 live CACHE rows had 0 signals. Every repeat of a note was billed
    again, and that is how one bulk pass spent a month's cap on 111 distinct notes.
    """
    try:
        table.put_item(Item={"pk": _CACHE_PK, "sk": f"HASH#{note_hash}", "signals": floats_to_decimal(signals), "at": _month()})
    except Exception as e:  # noqa: BLE001 — the cache must never break an extraction
        logger.warning("training-notes hash-cache write failed (the next identical note re-bills): %s: %s", type(e).__name__, e)


def monthly_calls(table, now=None, lane: str = "live") -> int:
    try:
        r = table.get_item(Key={"pk": _USAGE_PK, "sk": usage_sk(now, lane)})
        it = r.get("Item")
        return int(it.get("calls", 0)) if it else 0
    except ValueError:
        raise
    except Exception:
        return 0


def _bump_calls(table, now=None, lane: str = "live"):
    try:
        table.update_item(
            Key={"pk": _USAGE_PK, "sk": usage_sk(now, lane)},
            UpdateExpression="SET calls = if_not_exists(calls, :z) + :one",
            ExpressionAttributeValues={":z": 0, ":one": 1},
        )
    except Exception:
        pass


def make_llm_fn(table, monthly_cap: int = DEFAULT_MONTHLY_CAP, lane: str = "live"):
    """Build the llm_fn passed to training_notes.extract_signals: hash-cached + capped.

    `lane` names the monthly counter this closure charges (#4151): `live` for the on-ingest
    hook, `bulk` for any sweep. The lanes never share a counter, so a sweep cannot spend the
    live path's month.

    Returns a closure (note_text, taxonomy) -> list[signal]. On a cache hit it returns
    the cached signals with no model call and no cap consumption. On a cap breach it
    raises CapExceeded (→ the caller degrades, deterministic-only). The future Bedrock
    swap only touches _haiku_call.
    """

    usage_sk(lane=lane)  # validate the lane at build time, not on the first uncached note

    def _fn(note_text, taxonomy):
        from training.training_notes import note_hash as _nh

        h = _nh(note_text)
        cached = cache_get(table, h)
        if cached is not None:
            return cached
        if monthly_calls(table, lane=lane) >= monthly_cap:
            raise CapExceeded(f"training-notes Haiku monthly cap {monthly_cap} reached ({lane} lane)")
        try:
            signals = _haiku_call(note_text, taxonomy)
        except ExtractionDegraded:
            # The model answered and was billed in full; only the OUTPUT was unusable. The
            # counter is evidence of attempts (#3699 read the missing July/August rows as
            # proof the tail was down), so a billed call must count even when it degrades.
            # A CapExceeded raises above this, before any spend, and is deliberately outside.
            _bump_calls(table, lane=lane)
            raise
        _bump_calls(table, lane=lane)
        # A degrade is never cached: the old code wrote the silent [] into the hash cache, so
        # one bad response impoverished that note for as long as its text was unchanged.
        cache_put(table, h, signals)
        return signals

    return _fn
