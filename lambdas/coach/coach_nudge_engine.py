"""coach_nudge_engine.py — "the coach who texts first" (#1382, Epic E / #1080).

The DETERMINISTIC core of proactive coach nudges: a coach reaches out FIRST at
a decision moment. Everything that decides WHETHER a nudge fires, ABOUT WHAT,
WHO sends it, and HOW IT IS GRADED lives here as pure functions over a
precomputed context dict — no I/O, no LLM anywhere in the decision path
(ADR-105: deterministic computation before any model involvement). The model
(Haiku, via the Bedrock chokepoint) only ever phrases a payload this module
has already assembled; the delivery/IO shell is
``lambdas/emails/coach_nudge_lambda.py``.

Triggers (each a pure fire/no-fire function over injected facts):
  * ``nutrition_log_gap``          — yesterday's MacroFactor day is still absent
    by 18:00 PT while a nutrition-domain experiment is active. (MacroFactor is
    a manual end-of-day upload, ~24h behind by design — so the honest same-day
    "no dinner log by 6pm" signal is *yesterday's upload never happened*: the
    decision moment is tonight's upload, and absence of yesterday by evening
    is a genuinely missed log, not pipeline lag. ADR-104.)
  * ``acwr_band_cross``            — the canonical EWMA ACWR (BS-09) moved into
    an ALERT band (caution / danger / detraining) since the previous reading.
  * ``verdict_resolving_tomorrow`` — a pending coach PREDICTION# reaches its
    evaluation window tomorrow.

Hard rails (AC2), all deterministic and all enforced BEFORE any model call:
  * ≤ 1 nudge per Pacific day — an atomic ledger row (conditional put by the
    shell) backs the pure `sent_today` check; one ATTEMPT per day, so a
    gate-blocked nudge is dropped silently, never retried into vagueness (AC4).
  * quiet hours — nudges only inside SEND_WINDOW (08:00–19:00 PT).
  * budget tier ≥ 2 silences the feature entirely (budget_guard, ADR-063).
  * SDT-safe framing — information, never command; skippable; NO loss-streak
    language. Enforced twice: in the phrasing prompt AND by the deterministic
    ``sdt_violations`` lint on the produced copy (prompt rules alone are not a
    structural guarantee).

Track record (AC3, ADR-104): every SENT nudge is stored VERBATIM in the
sending coach's COACH# partition (sk ``NUDGE#{date}#{uuid8}``) with a stated
prior that the targeted action appears within OUTCOME_WINDOW_MINUTES, and is
outcome-graded hit/miss by a deterministic probe — proactivity itself acquires
a Brier record, surfaced on the observatory card. A sent nudge with no graded
outcome is a bug (the grading pass runs on every scheduled invocation).

Store (single-table; same COACH# partition family as PREDICTION#/LEARNING#):
  pk = COACH#{coach_id}                 (compute convention, e.g. nutrition_coach)
  sk = NUDGE#{YYYY-MM-DD}#{uuid8}
plus one ledger partition for the atomic daily cap:
  pk = COACH#nudge_ledger   sk = DAY#{YYYY-MM-DD}
Both fall under the COACH#* prefix rule in phase_taxonomy (experiment_scoped).
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

# ── constants ────────────────────────────────────────────────────────────────

NUDGE_SK_PREFIX = "NUDGE#"
LEDGER_PK = "COACH#nudge_ledger"
LEDGER_SK_PREFIX = "DAY#"

STATUS_SENT = "sent"
STATUS_BLOCKED = "blocked"  # failed a gate — audit-logged, never delivered
# #3569: the day was reserved but the record could not be persisted. The shell's
# `_reserve_day` stamps the reservation `attempting`, and it MUST end at one of
# the three terminal statuses below — a row left at `attempting` is a silent
# loss, which is exactly how three float rejections sat undetected for 25 days
# while all four ledger days read "attempting" and zero NUDGE# rows existed.
STATUS_FAILED = "failed"
STATUS_ATTEMPTING = "attempting"
TERMINAL_STATUSES = (STATUS_SENT, STATUS_BLOCKED, STATUS_FAILED)
# The two statuses that assert "a nudge record was written": the ledger points at
# a NUDGE# item that must exist. `failed` deliberately does NOT — that row exists
# precisely because the record could not be written.
STATUSES_WITH_RECORD = (STATUS_SENT, STATUS_BLOCKED)

OUTCOME_PENDING = "pending"
OUTCOME_HIT = "hit"
OUTCOME_MISS = "miss"

CHANNEL = "email"  # the platform's existing delivery channel (see PR #1382)

# Quiet hours (AC2): nudges may only go out inside this Pacific-local window.
# End is chosen so the +2h grading deadline still lands inside the shell's
# hourly cron coverage year-round (PDT and PST).
SEND_WINDOW_START_HOUR_PT = 8  # inclusive — 08:00 PT
SEND_WINDOW_END_HOUR_PT = 19  # exclusive — 19:00 PT

# Budget rail (AC2): tier >= 2 silences the feature (see budget_guard
# _FEATURE_CUTOFF["coach_nudge"] = 2 — kept equal by tests).
BUDGET_SILENCE_TIER = 2

# The graded claim: "the targeted action appears within this many minutes".
OUTCOME_WINDOW_MINUTES = 120

# Trigger identifiers.
TRIGGER_NUTRITION_LOG_GAP = "nutrition_log_gap"
TRIGGER_ACWR_BAND_CROSS = "acwr_band_cross"
TRIGGER_VERDICT_TOMORROW = "verdict_resolving_tomorrow"

# Deterministic priority when several triggers fire on the same run: the most
# time-critical decision moment wins (training load safety > tonight's upload
# > tomorrow's verdict heads-up).
TRIGGER_PRIORITY = (
    TRIGGER_ACWR_BAND_CROSS,
    TRIGGER_NUTRITION_LOG_GAP,
    TRIGGER_VERDICT_TOMORROW,
)

# Stated priors that the targeted action appears within the outcome window —
# the "forecast" each nudge makes about itself, judged by the Brier record.
# Honest initial guesses (no history yet); the whole point of AC3 is that
# these numbers acquire a public track record instead of staying vibes.
TRIGGER_PRIORS = {
    TRIGGER_NUTRITION_LOG_GAP: 0.4,
    TRIGGER_ACWR_BAND_CROSS: 0.2,
    TRIGGER_VERDICT_TOMORROW: 0.2,
}

# The ACWR zones that constitute an alert band (mirrors BS-09 _classify_acwr:
# >1.5 danger, >1.3 caution, <0.8 detraining; 0.8-1.3 safe).
ACWR_ALERT_ZONES = frozenset({"danger", "caution", "detraining"})

# The hour (PT) after which yesterday's still-absent MacroFactor day counts as
# a missed upload rather than pipeline lag ("no dinner log by 6pm PT").
NUTRITION_GAP_HOUR_PT = 18

USER_ID = "matthew"

# ── SDT lint (AC2) ───────────────────────────────────────────────────────────
# Deterministic blocklist for controlling / loss-streak framing. Prompt rules
# request SDT-safe copy, but prompt rules are not structural guarantees — this
# lint is what actually blocks a violating draft (which is then dropped
# silently, AC4). Patterns are lowercase-matched.

SDT_BANNED_PATTERNS = (
    r"\bstreak\b",
    r"don'?t\s+break",
    r"don'?t\s+ruin",
    r"\byou\s+must\b",
    r"\byou\s+need\s+to\b",
    r"\byou\s+have\s+to\b",
    r"\byou\s+should\b",
    r"\bfail(?:ed|ure|ing)?\b",
    r"\bfalling\s+behind\b",
    r"\bno\s+excuses?\b",
    r"\bdisappoint(?:ed|ing)?\b",
    r"\blast\s+chance\b",
    r"\bor\s+else\b",
    r"\bslipping\b",
)


def sdt_violations(text: str) -> list:
    """The banned-framing patterns present in `text` (empty list = clean)."""
    low = (text or "").lower()
    return [p for p in SDT_BANNED_PATTERNS if re.search(p, low)]


# ── keys ─────────────────────────────────────────────────────────────────────


def nudge_pk(coach_id: str) -> str:
    """The sending coach's partition (compute convention: full id, e.g.
    'nutrition_coach' → COACH#nutrition_coach)."""
    return f"COACH#{coach_id}"


def new_nudge_sk(date_str: str, uid: Optional[str] = None) -> str:
    return f"{NUDGE_SK_PREFIX}{date_str}#{uid or uuid.uuid4().hex[:8]}"


def ledger_sk(date_str: str) -> str:
    return f"{LEDGER_SK_PREFIX}{date_str}"


def _iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── trigger evaluation (AC1 — pure, no I/O, no LLM) ─────────────────────────
#
# ctx is a plain dict of precomputed live-data facts assembled by the shell:
#   now_pt                    aware datetime in America/Los_Angeles
#   yesterday_pt              "YYYY-MM-DD" (the expected-complete nutrition day)
#   nutrition_logged_yesterday  bool — macrofactor DATE#{yesterday_pt} exists
#   active_nutrition_experiments  [names] — status=="active", nutrition-domain tags
#   acwr_latest / acwr_previous   {date, acwr, zone} | None  (computed_metrics)
#   verdicts_resolving_tomorrow   [{coach_id, prediction_id, claim,
#                                   resolution_date, confidence}]


def evaluate_nutrition_log_gap(ctx: dict) -> Optional[dict]:
    """Fire iff: past NUTRITION_GAP_HOUR_PT, a nutrition experiment is active,
    and yesterday's nutrition day (the expected-complete day) never arrived."""
    now_pt = ctx.get("now_pt")
    experiments = ctx.get("active_nutrition_experiments") or []
    if now_pt is None or now_pt.hour < NUTRITION_GAP_HOUR_PT:
        return None
    if not experiments:
        return None
    if ctx.get("nutrition_logged_yesterday"):
        return None
    yesterday = ctx.get("yesterday_pt")
    if not yesterday:
        return None
    payload = {
        "missing_date": yesterday,
        "checked_hour_pt": now_pt.hour,
        "active_experiments": [str(n) for n in experiments][:3],
    }
    return {
        "trigger_type": TRIGGER_NUTRITION_LOG_GAP,
        "coach_id": "nutrition_coach",
        "payload": payload,
        "prior": TRIGGER_PRIORS[TRIGGER_NUTRITION_LOG_GAP],
        "probe": {
            "kind": "item_exists",
            "pk": f"USER#{USER_ID}#SOURCE#macrofactor",
            "sk": f"DATE#{yesterday}",
        },
        # What the copy may invite (information, not command — AC2): tonight's
        # upload is the decision moment.
        "invited_action": "log yesterday's food day (MacroFactor upload) if you want it in the experiment record",
    }


def evaluate_acwr_band_cross(ctx: dict) -> Optional[dict]:
    """Fire iff the canonical ACWR zone changed since the previous reading AND
    the new zone is an alert band. Crossing back INTO safe never nudges — a
    recovery is not a decision moment, and nudging it would be noise."""
    latest = ctx.get("acwr_latest") or {}
    previous = ctx.get("acwr_previous") or {}
    zone = latest.get("zone")
    prev_zone = previous.get("zone")
    if not zone or not prev_zone:
        return None
    if zone == prev_zone:
        return None
    if zone not in ACWR_ALERT_ZONES:
        return None
    payload = {
        "date": latest.get("date"),
        "acwr": latest.get("acwr"),
        "zone": zone,
        "previous_zone": prev_zone,
    }
    return {
        "trigger_type": TRIGGER_ACWR_BAND_CROSS,
        "coach_id": "training_coach",
        "payload": payload,
        "prior": TRIGGER_PRIORS[TRIGGER_ACWR_BAND_CROSS],
        "probe": _decisions_probe(),
        "invited_action": "make a call on today's training and log it as a decision if you make one",
    }


def evaluate_verdict_resolving_tomorrow(ctx: dict) -> Optional[dict]:
    """Fire iff at least one pending prediction's evaluation window completes
    tomorrow. Deterministic pick when several: lexicographically smallest
    prediction_id (stable across runs)."""
    verdicts = ctx.get("verdicts_resolving_tomorrow") or []
    if not verdicts:
        return None
    chosen = sorted(verdicts, key=lambda v: str(v.get("prediction_id") or ""))[0]
    payload = {
        "prediction_id": chosen.get("prediction_id"),
        "claim": str(chosen.get("claim") or "")[:300],
        "resolution_date": chosen.get("resolution_date"),
        "stated_confidence": chosen.get("confidence"),
    }
    return {
        "trigger_type": TRIGGER_VERDICT_TOMORROW,
        "coach_id": chosen.get("coach_id") or "explorer_coach",
        "payload": payload,
        "prior": TRIGGER_PRIORS[TRIGGER_VERDICT_TOMORROW],
        "probe": _decisions_probe(),
        "invited_action": "log your own expected outcome as a decision before the verdict lands, if you feel like calling it",
    }


def _decisions_probe() -> dict:
    return {
        "kind": "decision_logged_within",
        "pk": f"USER#{USER_ID}#SOURCE#decisions",
        "sk_prefix": "DECISION#",
        "window_minutes": OUTCOME_WINDOW_MINUTES,
    }


_EVALUATORS = {
    TRIGGER_NUTRITION_LOG_GAP: evaluate_nutrition_log_gap,
    TRIGGER_ACWR_BAND_CROSS: evaluate_acwr_band_cross,
    TRIGGER_VERDICT_TOMORROW: evaluate_verdict_resolving_tomorrow,
}


def evaluate_triggers(ctx: dict) -> list:
    """All firings, in deterministic TRIGGER_PRIORITY order."""
    firings = []
    for trigger_type in TRIGGER_PRIORITY:
        firing = _EVALUATORS[trigger_type](ctx)
        if firing:
            firings.append(firing)
    return firings


# ── hard rails (AC2 — pure) ──────────────────────────────────────────────────


def within_send_window(now_pt) -> bool:
    return SEND_WINDOW_START_HOUR_PT <= now_pt.hour < SEND_WINDOW_END_HOUR_PT


def apply_rails(firings: list, *, budget_tier: int, sent_today: bool, now_pt) -> tuple:
    """(chosen_firing | None, reason). Rails in fixed order — the reason string
    is the audit trail for a silent day."""
    if budget_tier >= BUDGET_SILENCE_TIER:
        return None, f"budget_tier_{budget_tier}"
    if not within_send_window(now_pt):
        return None, "quiet_hours"
    if sent_today:
        return None, "daily_cap"
    if not firings:
        return None, "no_trigger"
    return firings[0], "ok"


# ── outcome grading (AC3 — pure over probe results) ─────────────────────────


def grade_due(sent_at_iso: str, now_utc: datetime) -> bool:
    """True once the outcome window has fully elapsed — only then may a nudge
    be graded (a hit inside the window is a hit whenever we look; a miss can
    only be declared after the window closes)."""
    sent = datetime.strptime(sent_at_iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return now_utc >= sent + timedelta(minutes=OUTCOME_WINDOW_MINUTES)


def probe_key_range(sent_at_iso: str, probe: dict) -> tuple:
    """(sk_lo, sk_hi) for a timestamp-keyed probe: DECISION# sks embed a UTC
    ISO timestamp, so 'a decision logged within the window' is a pure key
    range. Lower bound omits the Z suffix so same-second items (which carry
    milliseconds) sort inside the range; upper bound appends '~'."""
    sent = datetime.strptime(sent_at_iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    deadline = sent + timedelta(minutes=int(probe.get("window_minutes") or OUTCOME_WINDOW_MINUTES))
    prefix = probe["sk_prefix"]
    lo = f"{prefix}{sent.strftime('%Y-%m-%dT%H:%M:%S')}"
    hi = f"{prefix}{deadline.strftime('%Y-%m-%dT%H:%M:%S')}~"
    return lo, hi


def grade_outcome(action_seen: bool) -> str:
    return OUTCOME_HIT if action_seen else OUTCOME_MISS


def brier_for(prior: float, outcome: str) -> float:
    """Per-nudge Brier contribution: (p - o)^2, o ∈ {0, 1}."""
    o = 1.0 if outcome == OUTCOME_HIT else 0.0
    return round((float(prior) - o) ** 2, 4)


def graded_pairs(nudge_items: list) -> list:
    """[(prior, binary_outcome)] over graded SENT nudges — the calibration
    pairs behind the proactivity Brier. Blocked/pending nudges never enter."""
    pairs = []
    for it in nudge_items or []:
        if it.get("status") != STATUS_SENT:
            continue
        outcome = it.get("outcome")
        if outcome not in (OUTCOME_HIT, OUTCOME_MISS):
            continue
        try:
            prior = float(it.get("prior"))
        except (TypeError, ValueError):
            continue
        pairs.append((prior, 1 if outcome == OUTCOME_HIT else 0))
    return pairs


def proactivity_summary(nudge_items: list) -> Optional[dict]:
    """The observatory card's proactivity block: counts + hit rate + Brier
    over a window of NUDGE# items. None when there is nothing to show."""
    items = list(nudge_items or [])
    if not items:
        return None
    sent = [it for it in items if it.get("status") == STATUS_SENT]
    blocked = sum(1 for it in items if it.get("status") == STATUS_BLOCKED)
    hits = sum(1 for it in sent if it.get("outcome") == OUTCOME_HIT)
    misses = sum(1 for it in sent if it.get("outcome") == OUTCOME_MISS)
    pending = sum(1 for it in sent if it.get("outcome") == OUTCOME_PENDING)
    pairs = graded_pairs(sent)
    graded = len(pairs)
    summary = {
        "nudges": len(items),
        "sent": len(sent),
        "blocked": blocked,
        "hit": hits,
        "miss": misses,
        "pending": pending,
        "graded": graded,
        "hit_rate_pct": round(100.0 * hits / graded, 1) if graded else None,
        "brier": round(sum((p - o) ** 2 for p, o in pairs) / graded, 4) if graded else None,
        "outcome_window_minutes": OUTCOME_WINDOW_MINUTES,
    }
    last = max((it.get("sent_at") or "" for it in sent), default="")
    if last:
        summary["last_nudge_at"] = last
    return summary


# ── phrasing prompt (the model ONLY phrases; it never decides) ───────────────


def build_phrasing_prompt(coach_name: str, firing: dict) -> tuple:
    """(system, user) for the Haiku phrasing call. The user message contains
    ONLY the precomputed trigger payload — the model's entire job is one short,
    SDT-safe message over those facts. Every number/date in the copy must come
    from the payload (enforced downstream by the grounding gate)."""
    system = (
        f"You are {coach_name}, one of the AI coaches on Matthew's personal health platform. "
        "A deterministic trigger has already decided that a short proactive note is worth sending "
        "right now — your ONLY job is to phrase it. You do not decide whether to send or what it "
        "is about.\n\n"
        "NON-NEGOTIABLE RULES (SDT-safe framing — psychology panel):\n"
        "1. INFORMATION, never command. State what the data shows and what the decision moment is. "
        "Never tell Matthew what he must/should/needs to do.\n"
        "2. Explicitly skippable — make clear that doing nothing is a completely fine choice.\n"
        "3. NO loss-streak language: never mention streaks, breaking chains, failure, falling "
        "behind, or disappointment.\n"
        "4. Use ONLY the facts in the trigger payload. Do not invent numbers, dates, or events "
        "(honest-numbers rule, ADR-104).\n"
        "5. Two or three sentences, conversational, in your own voice. No greetings boilerplate, "
        "no sign-off.\n"
    )
    user = (
        "Trigger payload (the ONLY facts you may use):\n"
        f"- trigger: {firing['trigger_type']}\n"
        f"- facts: {firing['payload']}\n"
        f"- the optional action this opens up: {firing['invited_action']}\n\n"
        "Write the note."
    )
    return system, user


# ── record builders ──────────────────────────────────────────────────────────


def build_nudge_item(
    firing: dict,
    copy_text: str,
    status: str,
    *,
    date_pt: str,
    now_utc: datetime,
    uid: Optional[str] = None,
    gate_findings: Optional[list] = None,
    cycle: Optional[int] = None,
) -> dict:
    """The verbatim COACH#-partition nudge record (ADR-104: stored exactly as
    produced, graded later). Numeric prior is kept as str for Decimal-safe DDB
    writes by the shell."""
    item = {
        "pk": nudge_pk(firing["coach_id"]),
        "sk": new_nudge_sk(date_pt, uid),
        "record_type": "coach_nudge",
        "coach_id": firing["coach_id"],
        "trigger_type": firing["trigger_type"],
        "trigger_payload": firing["payload"],
        "invited_action": firing["invited_action"],
        "copy": copy_text,  # verbatim — ADR-104
        "status": status,
        "channel": CHANNEL,
        "prior": str(firing["prior"]),
        "probe": firing["probe"],
        "sent_at": _iso_z(now_utc),
    }
    if status == STATUS_SENT:
        item["outcome"] = OUTCOME_PENDING
    if gate_findings:
        item["gate_findings"] = [str(f)[:300] for f in gate_findings][:10]
    if cycle is not None:
        item["cycle"] = int(cycle)
    return item


def build_ledger_item(date_pt: str, nudge_item: dict) -> dict:
    """The atomic daily-cap row (conditional-put by the shell). Points at the
    coach-partition record so the grading pass can find ungraded nudges
    without scanning all eight coach partitions."""
    return {
        "pk": LEDGER_PK,
        "sk": ledger_sk(date_pt),
        "record_type": "coach_nudge_ledger",
        "status": nudge_item["status"],
        "trigger_type": nudge_item["trigger_type"],
        "coach_id": nudge_item["coach_id"],
        "nudge_pk": nudge_item["pk"],
        "nudge_sk": nudge_item["sk"],
        "sent_at": nudge_item["sent_at"],
        "graded": nudge_item["status"] != STATUS_SENT,  # only sent nudges need grading
    }


def build_reservation_item(date_pt: str, firing: dict, now_utc: datetime) -> dict:
    """The `attempting` reservation row the shell conditional-puts BEFORE any
    model call (the daily cap).

    #3569 added `attempted_at`: the reservation used to carry no timestamp at
    all, so a row stuck at `attempting` could not even be aged — the dead-man in
    `lambdas/operational/nudge_ledger_qa.py` had to fall back to the day the sk
    names. Pre-#3569 rows still take that fallback; every new one is exact.
    """
    return {
        "pk": LEDGER_PK,
        "sk": ledger_sk(date_pt),
        "record_type": "coach_nudge_ledger",
        "status": STATUS_ATTEMPTING,
        "trigger_type": firing["trigger_type"],
        "coach_id": firing["coach_id"],
        "attempted_at": _iso_z(now_utc),
        "graded": True,  # flipped to False only once a nudge is actually SENT
    }


def build_failed_ledger_item(date_pt: str, nudge_item: dict, error: str, now_utc: datetime) -> dict:
    """#3569 — the ledger row a FAILED record write leaves behind.

    Before this, a `_finalize` crash left the reservation at `status=attempting`
    forever: the Pacific day stayed consumed (`graded=True`), the failure was
    invisible to every reader of the ledger, and three float rejections
    (2026-08-06/08-07/08-30) sat undetected for 25 days. A write that cannot
    land now says so, in the ledger, with the exception attached.
    """
    return {
        "pk": LEDGER_PK,
        "sk": ledger_sk(date_pt),
        "record_type": "coach_nudge_ledger",
        "status": STATUS_FAILED,
        "trigger_type": nudge_item.get("trigger_type"),
        "coach_id": nudge_item.get("coach_id"),
        "nudge_pk": nudge_item.get("pk"),
        "nudge_sk": nudge_item.get("sk"),
        "attempted_at": _iso_z(now_utc),
        "error": str(error)[:500],
        "graded": True,  # nothing to grade — the record never landed
    }


def mark_send_failed(nudge_item: dict, error: str) -> dict:
    """#3569 — downgrade an already-persisted STATUS_SENT record after the SES
    send failed.

    The durable write now precedes the irreversible send, so a send failure has
    to CORRECT the record it already wrote rather than orphan it. Same pk/sk, so
    the shell's second `_finalize` overwrites both rows in place, and the
    resulting record is byte-identical to the one the old (send-first) order
    wrote on its SES-error path.
    """
    item = dict(nudge_item)
    item["status"] = STATUS_BLOCKED
    item.pop("outcome", None)  # a nudge that never left is not awaiting an outcome
    item["gate_findings"] = [f"ses_error:{error}"[:300]]
    return item
