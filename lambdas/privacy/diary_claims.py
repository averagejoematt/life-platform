"""
diary_claims.py — the on-tape claims ledger (#1841; story 1 of the diary-360 chain).

Video-diary entries are full of implicit forecasts — day zero alone carried "if I can
really get through the next 30, 60 days, then I normally at least coast on a lot of the
good habits" — and none of them entered the prediction machinery. The diary was a pipe
INTO enrichment, never a loop. This module is the deterministic half of closing it.

THE SPLIT (ADR-105 — deterministic computation before any LLM verdict)
──────────────────────────────────────────────────────────────────────
LLM PROPOSES   The /vlog interviewer — already in the session, so no extra Bedrock call
               and no new budget_guard feature (ADR-103: no machinery without rent) —
               nominates 0-3 candidate claims at the route-the-takeaways close and takes
               consent PER CLAIM, the same offer-never-assume contract as
               `mark_journal_quote`. Silence means no.
CODE ADMITS    `admit_claim()` below is the ONLY door into the ledger. It refuses
               anything not falsifiable by machinery that already exists: the metric must
               resolve through `measurable_metrics.METRIC_SOURCES`, the spec must be
               `machine` (numeric threshold + a condition `_evaluate_condition` grades) or
               `directional` (a direction the EWMA evaluator grades), and the grade-by
               date is FROZEN at admission. Prose, vibes and unresolvable metrics stay
               narrative — exactly as `dispute_docket.validate_criterion` refuses an
               unmeasurable dispute.

Nothing in this module grades. Admitted claims are written in the canonical `PREDICTION#`
record shape, and the existing daily `coach-prediction-evaluator` grades them with the
same code, the same status vocabulary and the same windows as every coach prediction —
one grader, no second opinion to drift.

GRADE-BY vs. THE MACHINE WINDOW (honest, not fudged)
────────────────────────────────────────────────────
`grade_by` is the claim's OWN stated deadline — the date the diary calls it back on tape.
The evaluator additionally floors every window at a domain minimum
(`coach_prediction_evaluator.DOMAIN_MIN_WINDOWS`, e.g. body_composition = 28d), so for a
short-horizon claim the machine verdict can still be `pending` when the deadline lands.
That is reported as such rather than papered over: the on-tape callback is about what he
said and when he said it would be settled; the machine verdict rides along when ready.
(Hoisting those domain tables into a pure shared module so `grade_by` could carry the true
floor is deliberate follow-up work, not silently assumed here.)

PRIVACY
───────
A claim is the subject's own words about himself. Records are private by default
(`visibility: "private"`); no public surface reads this partition — the public
`/api/predictions` and `/api/calibration` path reads `COACH#` partitions only. Publishing
an on-tape claim would need an explicit consent marker (`diary_consent.py`), which is
deliberately NOT wired here.

Pure — no boto3, no network, no clock of its own. The MCP tool does the I/O.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta

from experiment.measurable_metrics import infer_direction, metric_is_resolvable, metric_subdomain, normalize_metric_hint

# ── The store ────────────────────────────────────────────────────────────────────
# pk `USER#{user}#SOURCE#diary_claims`; sk `PREDICTION#{stated_date}#{slug}`.
#
# The sk prefix is `PREDICTION#` deliberately: these ARE prediction-store records (the
# same field set, the same status vocabulary), just claimed by the subject instead of a
# coach. That is what lets the existing evaluator grade them by adding one partition to
# its scan rather than growing a second grader. Date-prefixed so a descending query is
# newest-first, matching the coach store's convention.
SOURCE_NAME = "diary_claims"
SK_PREFIX = "PREDICTION#"

# The one channel this story admits. #1842+ may widen it (solo_recording, etc.); the
# stored `source` field is what later stories filter on, so widening costs one entry.
CLAIM_SOURCE_VIDEO_DIARY = "video_diary"
VALID_CLAIM_SOURCES = (CLAIM_SOURCE_VIDEO_DIARY,)

# ── Admission bounds ─────────────────────────────────────────────────────────────
MAX_CLAIMS_PER_SESSION = 3  # AC1: the closer offers 0-3, never more
MAX_CLAIM_CHARS = 400  # a claim is a sentence, not a monologue

# A diary claim is a life-scale forecast ("the next 30, 60 days"), so the ceiling is far
# wider than the docket's 90d. The floor is 14d because the evaluator floors most domains
# at 14-28d anyway — admitting a 3-day claim would guarantee a deadline the machine cannot
# meet, and a deadline the machine cannot meet is a promise the ledger cannot keep.
MIN_HORIZON_DAYS = 14
MAX_HORIZON_DAYS = 365

# The exact condition vocabulary `coach_prediction_evaluator._evaluate_condition` grades.
VALID_CONDITIONS = ("gt", "gte", "lt", "lte", "eq")
CONDITION_SYMBOL = {"gt": ">", "gte": ">=", "lt": "<", "lte": "<=", "eq": "="}

# Only these two spec types are falsifiable by the existing evaluator. `qualitative` is
# explicitly NOT admissible — the evaluator skips it, so admitting one would put a row in
# the ledger that can never be graded (the exact v7.15.0 "504 predictions, 100%
# inconclusive" failure `measurable_metrics` was created to end).
GRADABLE_SPEC_TYPES = ("machine", "directional")

STATUS_PENDING = "pending"

# Confidence word -> float, IDENTICAL to `coach_state_updater._parse_confidence`'s word
# map. `calibration_core.pairs_from_prediction_records` reads this field as a number, and
# a diary claim scored on a different scale than a coach prediction would silently corrupt
# any pooled Brier score. tests pin the parity.
CONFIDENCE_WORDS = {
    "very low": 0.1,
    "low": 0.2,
    "med": 0.5,
    "medium": 0.5,
    "unknown": 0.5,
    "high": 0.85,
    "very high": 0.95,
}
DEFAULT_CONFIDENCE = 0.5

# The video-diary entry sk (`notion_lambda.build_sk`): DATE#<date>#journal#video_diary#<stable>
# where <stable> is the last 12 hex of the de-hyphenated Notion page id (#476/E-6).
SOURCE_SK_RE = re.compile(r"^DATE#(\d{4}-\d{2}-\d{2})#journal#(video_diary)#([0-9a-zA-Z]{1,12})$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

SCHEMA_VERSION = 1


def claims_pk(user_id: str = "matthew") -> str:
    """The claims partition for a user."""
    return f"USER#{user_id}#SOURCE#{SOURCE_NAME}"


def slugify(text) -> str:
    """Stable, prose-free slug for the sort key.

    #1801's lesson (dispute_docket.open_sk): no LLM prose may reach a key uncontrolled.
    The claim text is the subject's, not an LLM's, but it is still free text — so the slug
    is truncated hard and salted with a content digest, which also makes the key the
    natural idempotency handle (re-logging the same claim on the same day is a no-op
    overwrite, never a duplicate row).
    """
    normalized = " ".join(str(text or "").split()).lower()
    slug = re.sub(r"[^a-z0-9]+", "-", normalized)[:48].strip("-")
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:8]
    return f"{slug}-{digest}" if slug else digest


def claim_sk(stated_date: str, claim_natural: str) -> str:
    """`PREDICTION#{stated_date}#{slug}` — THE identity of one claim."""
    return f"{SK_PREFIX}{stated_date}#{slugify(claim_natural)}"


def parse_confidence(raw) -> float:
    """Parse a stated confidence to a float, mirroring the coach store's parser."""
    if raw is None or raw == "":
        return DEFAULT_CONFIDENCE
    s = str(raw).strip().lower()
    if s in CONFIDENCE_WORDS:
        return CONFIDENCE_WORDS[s]
    try:
        has_pct = s.endswith("%")
        val = float(s.rstrip("%").strip())
        if has_pct:
            val = val / 100.0
        return max(0.0, min(1.0, val))
    except (ValueError, TypeError):
        return DEFAULT_CONFIDENCE


def _parse_date(value):
    try:
        return datetime.strptime(str(value), "%Y-%m-%d")
    except (ValueError, TypeError):
        return None


def admit_claim(candidate, stated_date: str, source_sk: str):
    """The deterministic falsifiability gate — the ONLY door into the ledger.

    Returns `(ok: bool, reason: str, normalized: dict | None)`. Everything that fails
    here stays narrative in the Notion transcript; it CANNOT enter the ledger. The
    rejection `reason` is returned verbatim to the interviewer so the refusal can be said
    out loud on tape ("that one isn't gradable, and here's why") rather than swallowed.
    """
    if not isinstance(candidate, dict):
        return False, "no structured candidate — a claim must be an object", None

    # 1) Consent is explicit, per claim, never inferred (AC1 — the mark_journal_quote
    #    contract). Fail-closed: anything that is not exactly True is a refusal.
    if candidate.get("consent") is not True:
        return False, "refused: consent must be exactly true — Matthew consents to EACH claim on tape, and silence means no", None

    claim_natural = " ".join(str(candidate.get("claim") or candidate.get("claim_natural") or "").split())
    if not claim_natural:
        return False, "claim text is required — the ledger records what he actually said", None
    if len(claim_natural) > MAX_CLAIM_CHARS:
        return False, f"claim exceeds {MAX_CLAIM_CHARS} chars — a claim is a sentence, not a monologue", None

    # 2) The claim must point at the entry it came from (AC2), and that pointer must be a
    #    real video-diary sk for THIS session's date — a dangling pointer makes the
    #    on-tape callback unciteable.
    m = SOURCE_SK_RE.match(str(source_sk or ""))
    if not m:
        return False, f"source_sk {source_sk!r} is not a video-diary entry sk (DATE#<date>#journal#video_diary#<suffix>)", None
    if not DATE_RE.match(str(stated_date or "")):
        return False, f"stated_date {stated_date!r} is not YYYY-MM-DD", None
    if m.group(1) != stated_date:
        return False, f"source_sk date {m.group(1)} does not match the session date {stated_date}", None

    # 3) The metric must be resolvable by the evaluator's own machinery. Unresolvable
    #    metric -> the claim can never be graded, so it is never admitted.
    metric = normalize_metric_hint(candidate.get("metric"))
    if not metric or not metric_is_resolvable(metric):
        return False, f"metric {candidate.get('metric')!r} is not deterministically resolvable (measurable_metrics.METRIC_SOURCES)", None

    # 4) The horizon, frozen to one immutable grade-by date at admission.
    try:
        horizon_days = int(candidate.get("horizon_days"))
    except (TypeError, ValueError):
        return False, "horizon_days must be an integer number of days — a claim without a deadline is not falsifiable", None
    if horizon_days < MIN_HORIZON_DAYS or horizon_days > MAX_HORIZON_DAYS:
        return False, f"horizon {horizon_days}d outside [{MIN_HORIZON_DAYS}, {MAX_HORIZON_DAYS}]", None
    stated_dt = _parse_date(stated_date)
    if stated_dt is None:
        return False, f"stated_date {stated_date!r} unparseable", None
    grade_by = (stated_dt + timedelta(days=horizon_days)).strftime("%Y-%m-%d")

    # 5) Route to a gradable spec — machine if there is a real numeric threshold with a
    #    condition the evaluator grades, else directional if a direction can be resolved
    #    deterministically. Neither -> not falsifiable, refused.
    condition = str(candidate.get("condition") or "").strip().lower()
    raw_threshold = candidate.get("threshold")
    threshold = None
    if raw_threshold is not None and str(raw_threshold).strip() != "":
        try:
            threshold = float(raw_threshold)
        except (TypeError, ValueError):
            return False, f"threshold {raw_threshold!r} is not numeric", None

    if threshold is not None:
        if condition not in VALID_CONDITIONS:
            return False, f"condition {condition!r} not gradable with a threshold (need one of {VALID_CONDITIONS})", None
        spec = {
            "type": "machine",
            "metric": metric,
            "condition": condition,
            "threshold": threshold,
            "evaluation_window_days": horizon_days,
        }
        criterion = f"{metric} {CONDITION_SYMBOL[condition]} {threshold:g} by {grade_by}"
    else:
        direction = infer_direction(candidate.get("direction"), claim_natural)
        if not direction:
            return (
                False,
                "not falsifiable: no numeric threshold and no unambiguous direction — "
                "give a number to beat, or say plainly whether it goes up or down",
                None,
            )
        spec = {
            "type": "directional",
            "metric": metric,
            "condition": direction,
            # Directional specs carry NO threshold by construction (C-3/#813): a dead
            # threshold is what made 248/248 machine predictions ungradeable.
            "threshold": None,
            "evaluation_window_days": horizon_days,
        }
        criterion = f"{metric} trends {direction} by {grade_by}"

    normalized = {
        "claim_natural": claim_natural,
        "metric": metric,
        "subdomain": metric_subdomain(metric),
        "evaluation": spec,
        "criterion": criterion,
        "horizon_days": horizon_days,
        "grade_by": grade_by,
        "confidence": parse_confidence(candidate.get("confidence")),
        "confidence_stated": str(candidate.get("confidence") or "").strip().lower() or "unknown",
        "quote": " ".join(str(candidate.get("quote") or "").split()) or None,
    }
    return True, "", normalized


def build_claim_record(normalized, stated_date: str, source_sk: str, now_iso: str, user_id: str = "matthew") -> dict:
    """The DDB item for ONE admitted claim, in the canonical PREDICTION# record shape.

    Only code-admitted values reach this function — `admit_claim` has already refused
    everything that is not gradable. Absent values are OMITTED rather than written as
    null (ADR-104 honest absence): `outcome`/`outcome_date`/`outcome_notes` appear only
    once the evaluator has actually decided something.
    """
    sk = claim_sk(stated_date, normalized["claim_natural"])
    claim_id = sk[len(SK_PREFIX) :]
    record = {
        "pk": claims_pk(user_id),
        "sk": sk,
        # `prediction_id` is the field every prediction surface projects; `claim_id` is
        # the same value under the diary's own name.
        "prediction_id": claim_id,
        "claim_id": claim_id,
        "record_type": "diary_claim",
        # The claimant is the subject, NOT a coach. Kept deliberately empty-string for
        # `coach_id` so the evaluator's `if bayesian_update and coach_id` guard skips the
        # coach Bayesian/LEARNING# side effects — a subject's claim must never move a
        # coach's calibration.
        "coach_id": "",
        "claimant": user_id,
        "source": CLAIM_SOURCE_VIDEO_DIARY,  # AC2
        "source_pk": f"USER#{user_id}#SOURCE#notion",
        "source_sk": source_sk,  # AC2 — the entry pointer
        "created_date": stated_date,  # the evaluator's window anchor
        "stated_date": stated_date,
        "claim_natural": normalized["claim_natural"],
        "criterion": normalized["criterion"],
        "metric": normalized["metric"],
        "subdomain": normalized["subdomain"],
        "evaluation": normalized["evaluation"],
        "horizon_days": normalized["horizon_days"],
        "grade_by": normalized["grade_by"],  # AC2 — frozen at admission
        "confidence": normalized["confidence"],
        "confidence_stated": normalized["confidence_stated"],
        "status": STATUS_PENDING,
        "consent": True,
        "consent_at": now_iso,
        # Private by default. No public surface reads this partition; publishing would
        # need an explicit consent marker (diary_consent.py), not wired in this story.
        "visibility": "private",
        "schema_version": SCHEMA_VERSION,
        "created_at": now_iso,
    }
    if normalized.get("quote"):
        record["quote"] = normalized["quote"]
    return record


def is_gradable_record(record) -> bool:
    """True when a stored row carries a spec the evaluator can actually grade."""
    spec = (record or {}).get("evaluation") or {}
    return spec.get("type") in GRADABLE_SPEC_TYPES


def due_for_grading(records, today_str: str):
    """Claims whose stated deadline has landed — the /vlog step-0 callback list (AC3).

    Returns rows sorted oldest-deadline-first (the most overdue gets called back first),
    each annotated with `days_overdue` and the CURRENT machine status. A row is included
    when `grade_by <= today` and it has not yet been called back on tape, whether or not
    the machine has decided — a deadline reached with the verdict still pending is itself
    worth saying out loud, and hiding it would let a claim quietly outlive its own date.
    """
    today_dt = _parse_date(today_str)
    if today_dt is None:
        return []
    due = []
    for rec in records or []:
        grade_by = rec.get("grade_by")
        grade_dt = _parse_date(grade_by)
        if grade_dt is None or grade_dt > today_dt:
            continue
        if rec.get("called_back_at"):
            continue  # already worked on tape — don't re-litigate it every session
        due.append(
            {
                "claim_id": rec.get("claim_id") or rec.get("prediction_id"),
                "sk": rec.get("sk"),
                "stated_date": rec.get("stated_date") or rec.get("created_date"),
                "claim": rec.get("claim_natural", ""),
                "quote": rec.get("quote"),
                "criterion": rec.get("criterion", ""),
                "metric": rec.get("metric"),
                "grade_by": grade_by,
                "days_overdue": (today_dt - grade_dt).days,
                "status": rec.get("status", STATUS_PENDING),
                "outcome": rec.get("outcome"),
                "outcome_date": rec.get("outcome_date"),
                "source_sk": rec.get("source_sk"),
                "machine_verdict": (
                    "decided" if rec.get("status") in ("confirmed", "refuted", "inconclusive", "expired") else "still pending"
                ),
            }
        )
    due.sort(key=lambda c: (c["grade_by"] or "", c["claim_id"] or ""))
    return due


def track_record(records):
    """Deterministic hit rate over graded claims, with n and the correlative caveat.

    ADR-105: every statistical claim carries its n. `hit_rate_pct` is returned as None —
    not 0, not a guess — until at least one claim has actually been decided, because a
    hit rate over zero graded claims is not a small number, it is an absent one (ADR-104).
    """
    counts = {"pending": 0, "confirmed": 0, "refuted": 0, "inconclusive": 0, "expired": 0}
    for rec in records or []:
        status = rec.get("status", STATUS_PENDING)
        counts[status] = counts.get(status, 0) + 1
    decided = counts.get("confirmed", 0) + counts.get("refuted", 0)
    hit_rate = round(100.0 * counts.get("confirmed", 0) / decided, 1) if decided else None
    return {
        "n_total": sum(counts.values()),
        "n_decided": decided,
        "counts": counts,
        "hit_rate_pct": hit_rate,
        "interpretation": (
            "Correlative, not causal: a confirmed claim means the metric moved as he said it would, "
            "not that saying it caused the move. Graded by the same deterministic evaluator as every "
            "coach prediction (ADR-105)."
        ),
        "n_caveat": (
            f"n={decided} decided claim(s)" + ("" if decided >= 5 else " — too few to read as a rate; report the individual verdicts")
        ),
    }
