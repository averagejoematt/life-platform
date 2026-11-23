"""
between_chronicle_lambda.py — #398: the machine's between-chronicle note.

Confirmed subscribers received exactly one thing (the weekly Chronicle) while
the platform kept computing between-week findings that never reached the
inbox. This Lambda assembles a short "since the last installment" note PURELY
from already-computed records — ZERO new inference:

  - monthly what-changed deltas + newly-significant correlations
    (USER#…#SOURCE#what_changed / SNAPSHOT#current — the same record
    /api/what_changed serves, so every number matches the public API)
  - freshly graded predictions (COACH#… PREDICTION# status confirmed/refuted —
    the same records /api/predictions serves)
  - coach stance shifts (COACH#… STANCE#latest how_my_read_changed — the same
    text the coaching pages render)

Honesty rules:
  - Sends ONLY when there is real, previously-unsent content: the assembled
    digest is content-hashed and compared to the last-sent marker
    (SOURCE#email_digest / STATE#between_chronicle); an unchanged or empty
    period sends nothing — never padded filler.
  - No open tracking of any kind (no pixel, no per-link redirects) — the
    standing privacy tradeoff holds; the feature is judged on content.
  - Honors the platform-wide EXTERNAL_EMAILS_ENABLED kill switch.

#6244 (owner ruling 2026-11-23) — HELD, and repaired before it may resume.
  - THE HOLD. The note sends nothing to a subscriber until ``OWNER_RELEASE`` below is a complete owner release
    record (who, the day, and the representative render he reviewed). It ships as ``None``: merging or deploying
    this file sends nothing. A malformed record is a hold, never a release (fail closed). A dry run still renders,
    so the owner can review a representative email before he releases it.
  - THE RENDER. The note had been mailing the grader's raw JSON, four-decimal figures, correlations with no metric
    named and calls graded weeks earlier. ``curate`` now turns the wire records into reader sentences or drops them:
    every number at human precision with its unit; a correlation only with both measures named, its r, its number of
    days and the week it first held; every graded call, stance and correlation dated, and dropped when it is older than
    ``RECENCY_DAYS``; a graded call's reason only in reader words (``web.prediction_reason``), never the grader's
    working. Stored narrative passes the Site API's own narrative gate (``web.narrative_publication``, strict) on top
    of the call publication rule and the privacy scrub. ``build_email`` then refuses (raises) on any machine-format
    fragment left in the visible text (``machine_fragments``) — so a regression stops the send rather than reaching
    an inbox.
  - A QUIET WEEK IS VALID. The month's averages are context, not news: the note goes out only when there is at least
    one dated item (a graded call, a newly significant pair, a coach's changed read) inside the window.

Schedule: weekly, Sunday 10:00 Pacific (``config/schedules.json``; mid-gap between Wednesday chronicles).
"""

import hashlib
import html as _html
import json
import logging
import math
import os
import re
import time
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Optional

import boto3
from boto3.dynamodb.conditions import Key
from common import activity_publication  # owner rulings 2026-11-03/05: private metrics off public mail
from common.email_identity import CHRONICLE_SENDER  # #3568 — ONE sending vocabulary, gated against the SES-verified set
from common.journal_silence import reader_mail  # #5131: the one public-surface guard
from common.reader_email import head_meta, preheader_html, simple_content  # #6151 — the ONE reader envelope

try:
    from common.platform_logger import get_logger

    logger = get_logger("between-chronicle")
except ImportError:
    logger = logging.getLogger("between-chronicle")
    logger.setLevel(logging.INFO)

REGION = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
USER_ID = os.environ.get("USER_ID", "matthew")
SITE_URL = os.environ.get("SITE_URL", "https://averagejoematt.com")
SENDER = os.environ.get("EMAIL_SENDER", CHRONICLE_SENDER)
SEND_RATE_PER_SEC = float(os.environ.get("SEND_RATE_PER_SEC", "14.0"))
DECIDED_WINDOW_DAYS = int(os.environ.get("DECIDED_WINDOW_DAYS", "10"))
#: #6244: the one recency window. A graded call, a newly significant pair, a coach's changed read and the month's
#: averages are shown only when their own day falls inside the last RECENCY_DAYS days, and always with that day.
RECENCY_DAYS = DECIDED_WINDOW_DAYS
#: #6244: stored text longer than this is dropped whole, never cut mid-sentence.
MAX_TEXT_CHARS = 400

# ── #6244: the owner's hold ─────────────────────────────────────────────────────────────────────────────────────────
#: None = HELD. The owner releases the note by committing a record here after reviewing a representative render:
#:   {"by": "owner", "released_on": "YYYY-MM-DD", "reviewed_render": "<what he reviewed: the private evidence file>"}
#: Anything else (None, a missing field, a malformed day, another decider) holds. A release is a reviewed, diffable
#: commit — the same rule as common.outbound_trial — so no runtime read can fail open into a send.
OWNER_RELEASE: Optional[dict] = None
#: The log token a held run writes (one line a week while held, so the hold is visible in the logs).
HELD_TOKEN = "BETWEEN-CHRONICLE-HELD"  # noqa: S105 — a log token, not a credential
#: The log token a refused render writes — the final machine-fragment check found something curation missed.
RENDER_REFUSED_TOKEN = "BETWEEN-CHRONICLE-RENDER-REFUSED"  # noqa: S105 — a log token, not a credential
_DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def release_problems(release: Any) -> list:
    """Why ``release`` does not release the note ([] = released). ``None`` is the shipped hold."""
    if release is None:
        return ["held: no owner release recorded (#6244)"]
    if not isinstance(release, dict):
        return ["held: the release is not a record"]
    problems = []
    if release.get("by") != "owner":
        problems.append("held: a release must be the owner's (by='owner')")
    day = str(release.get("released_on") or "")
    if not _DAY_RE.match(day) or _parse_day(day) is None:
        problems.append("held: released_on must be a YYYY-MM-DD day")
    if not str(release.get("reviewed_render") or "").strip():
        problems.append("held: reviewed_render must name the render the owner reviewed")
    return problems


def is_released(release: Any = None) -> bool:
    """True only for a complete owner release record (``OWNER_RELEASE`` when no record is passed)."""
    return not release_problems(OWNER_RELEASE if release is None else release)


USER_PREFIX = f"USER#{USER_ID}#SOURCE#"
SUBSCRIBERS_PK = f"{USER_PREFIX}subscribers"
MARKER_PK = f"{USER_PREFIX}email_digest"
MARKER_SK = "STATE#between_chronicle"

# The coach roster — derived from the canonical persona registry, never re-typed
# (#2334; guard: tests/test_coach_roster_set_guard_2334.py). Same import its
# sibling chronicle_data.py already uses.
from coach.persona_registry import OPERATIONAL_COACH_IDS

COACH_IDS = list(OPERATIONAL_COACH_IDS)

dynamodb = boto3.resource("dynamodb", region_name=REGION)
table = dynamodb.Table(TABLE_NAME)
ses = boto3.client("sesv2", region_name=REGION)


from common import send_ledger  # #3113 / DIL-025: the durable replay guard
from common.digest_utils import d2f as _d2f  # shared bundled helpers (#970)
from common.pacific_time import pacific_now  # #2817: THE Pacific frame — DATE#/day keys name Pacific calendar days
from common.unsubscribe_token import unsub_url_or_fallback  # #3044 — signed unsub link, never plaintext email
from experiment.phase_filter import singleton_visible, with_phase_filter  # ADR-058 / #946 / #1200: restart tombstones

# #2654: the log token monitoring keys a MetricFilter + alarm on. The literal in
# cdk/stacks/monitoring_stack.py must match this constant EXACTLY — pinned by
# tests/test_between_chronicle_scrub_2654.py, so the two cannot drift apart silently.
SCRUB_FAILED_TOKEN = "BETWEEN-CHRONICLE-SCRUB-FAILED-CLOSED"  # noqa: S105 — a log token, not a credential


def _scrub(text: str) -> str:
    """Fail-CLOSED privacy scrub (#2654) — defense-in-depth on anything narrative.

    A scrub that cannot run (vocabulary channel down, guard defect) must abort
    the send, not return the input unchanged: a privacy screen that fails open
    guards nothing. The raise is what stops the outbound loop — build_email is
    called OUTSIDE the per-recipient try in lambda_handler, so no recipient
    receives text this function did not scrub. The token line is the alarm's
    signal; nothing leaked when it fires, but the digest went dark and silence
    must not be the only tell (#2503 class)."""
    try:
        from privacy import privacy_guard

        out, _n = privacy_guard.scrub(str(text))
        return out
    except Exception as exc:
        logger.error(
            "[%s] privacy scrub failed (%s: %s) — aborting the send; no unscrubbed text goes out",
            SCRUB_FAILED_TOKEN,
            type(exc).__name__,
            str(exc)[:300],
        )
        raise


# ── Gather (already-computed records only — the same ones the public APIs serve) ──


def _gated(item: Any, pk: str) -> Optional[dict]:
    """#6244: a stored narrative row through the Site API's own publication decision (strict: a mail has no wire half).
    None when the row is withheld or the gate cannot decide — fail closed, the row never reaches reader mail."""
    try:
        from web import narrative_publication

        gated = narrative_publication.gate_item(item, pk, strict=True)
        if narrative_publication.is_withheld(gated):
            return None
        return gated if isinstance(gated, dict) else None
    except Exception as e:  # noqa: BLE001 — a gate that cannot run withholds
        logger.warning("publication gate unavailable for %s (%s) — row withheld", pk, type(e).__name__)
        return None


def gather_digest() -> dict:
    """Assemble the between-chronicle content. Every value is read verbatim
    from a record a public endpoint already serves. ``curate`` decides what of it a reader sees."""
    digest: dict[str, Any] = {"deltas": [], "unlocked": [], "decided": [], "stance_shifts": []}

    # 1. Monthly motion — the /api/what_changed record.
    try:
        wc = _d2f(table.get_item(Key={"pk": f"{USER_PREFIX}what_changed", "sk": "SNAPSHOT#current"}).get("Item") or {})
        if not wc.get("honest_null"):
            digest["deltas"] = (wc.get("deltas") or [])[:6]
            # #6244: the window the averages cover — a figure is shown only with its window dated.
            digest["window_start"] = wc.get("window_start")
            digest["window_end"] = wc.get("window_end")
            # Owner rulings 2026-11-03/05/11: the same public projection /api/what_changed serves.
            unlocked = wc.get("newly_unlocked") or []
            records = activity_publication.unlocked_baseline_records(
                table, with_phase_filter({"KeyConditionExpression": Key("pk").eq(f"{USER_PREFIX}weekly_correlations")}), unlocked
            )
            digest["unlocked"] = activity_publication.public_newly_unlocked(unlocked, records, wc.get("window_end"))[:4]
    except Exception as e:
        logger.warning("what_changed read skipped: %s", e)

    # 2. Freshly graded predictions — the /api/predictions records. Owner ruling 2026-11-05: through the call
    # publication rule, as every public read is — a private call never reaches reader mail, and the newest 30 are
    # the newest 30 ELIGIBLE calls (web.call_publication keeps `Limit` a count of what is served).
    from web import call_publication, prediction_reason

    cutoff = (pacific_now() - timedelta(days=DECIDED_WINDOW_DAYS)).strftime("%Y-%m-%d")
    lookup = call_publication.make_lookup(table)
    for cid in COACH_IDS:
        try:
            resp = call_publication.query(
                table,
                {
                    "KeyConditionExpression": "pk = :pk AND begins_with(sk, :s)",
                    "ExpressionAttributeValues": {":pk": f"COACH#{cid}", ":s": "PREDICTION#"},
                    "ScanIndexForward": False,
                    "Limit": 30,
                },
                f"COACH#{cid}",
                lookup,
            )
            for raw in resp.get("Items", []):
                if (raw or {}).get("status") not in ("confirmed", "refuted"):
                    continue
                gated = _gated(raw, f"COACH#{cid}")  # #6244: the Site API's narrative gate, as /api/predictions applies it
                if gated is None:
                    continue
                rec = _d2f(gated)
                # #6244: the day the call was GRADED. The record keeps it as `outcome_date`; the old read looked only at
                # `evaluated_at`, which the grader does not write, so every call read as undated and none was ever too old.
                decided_at = str(
                    rec.get("outcome_date") or rec.get("evaluated_at") or (rec.get("evaluation") or {}).get("evaluated_at") or ""
                )[:10]
                if not decided_at or decided_at < cutoff:
                    continue  # undated, or graded before the window — never shown as news
                reason, _ = prediction_reason.reason_words(rec)  # #4220: reader words, never the grader's JSON
                digest["decided"].append(
                    {
                        "coach": cid.replace("_coach", "").replace("_", " "),
                        "claim": str(rec.get("claim_natural") or ""),
                        "status": rec["status"],
                        "reason": reason,
                        "decided_at": decided_at,
                    }
                )
        except Exception as e:
            logger.warning("predictions read skipped for %s: %s", cid, e)

    # 3. Stance shifts — the coaching pages' STANCE#latest "how my read changed".
    for cid in COACH_IDS:
        try:
            raw_st = table.get_item(Key={"pk": f"COACH#{cid}", "sk": "STANCE#latest"}).get("Item") or {}
            gated_st = _gated(raw_st, f"COACH#{cid}") if raw_st else None
            st = _d2f(gated_st or {})
            shift = str(st.get("how_my_read_changed") or "").strip()
            if shift:
                digest["stance_shifts"].append(
                    {
                        "coach": cid.replace("_coach", "").replace("_", " "),
                        "shift": shift,
                        "stage": str((st.get("stage") or {}).get("label", "") if isinstance(st.get("stage"), dict) else ""),
                        "as_of": str(st.get("as_of") or st.get("generated_at") or "")[:10],
                    }
                )
        except Exception as e:
            logger.warning("stance read skipped for %s: %s", cid, e)

    # 4. #537: Elena's editorial read — she signs this email, so her one-line
    # stance (PERSONA#elena STANCE#latest, receipts-gated) frames it. Garnish,
    # never content: it doesn't count toward has_real_content.
    try:
        _st_raw = table.get_item(Key={"pk": "PERSONA#elena", "sk": "STANCE#latest"}).get("Item") or {}
        st = _d2f(_st_raw)
        # #1200: a reset tombstones PERSONA#elena STANCE#latest — never sign a new-cycle
        # email with a wiped cycle's stance. singleton_visible reads the raw item (tombstone/phase).
        if st.get("headline_stance") and not st.get("grounding_flag") and singleton_visible(_st_raw):
            digest["elena_note"] = str(st["headline_stance"])
            digest["elena_as_of"] = str(st.get("as_of") or st.get("updated_at") or st.get("generated_at") or "")[:10]
    except Exception as e:
        logger.warning("elena stance read skipped: %s", e)

    return digest


def digest_hash(digest: dict) -> str:
    return hashlib.sha256(json.dumps(digest, sort_keys=True, default=str).encode()).hexdigest()


def has_real_content(digest: dict) -> bool:
    """#6244: a dated item inside the window — a graded call, a newly significant pair or a coach's changed read. The
    month's averages are context and never send the note on their own (a rolling average moves every week)."""
    return bool(digest.get("unlocked") or digest.get("decided") or digest.get("stance_shifts"))


# ── #6244: curation — wire records in, reader sentences out (or nothing) ─────────────────────────────────────────


def _parse_day(value: Any) -> Optional[date]:
    try:
        return datetime.strptime(str(value or "")[:10], "%Y-%m-%d").date() if _DAY_RE.match(str(value or "")[:10]) else None
    except ValueError:
        return None


def _today() -> str:
    """The Pacific day this run is for (one seam, so a test pins the clock rather than reading it)."""
    return pacific_now().date().isoformat()


def _in_window(day: Any, today: str) -> Optional[date]:
    """The day, when it is a real day inside the last RECENCY_DAYS days up to today; else None."""
    d, t = _parse_day(day), _parse_day(today)
    if d is None or t is None or d > t or (t - d).days > RECENCY_DAYS:
        return None
    return d


def _day_words(d: date) -> str:
    return f"{d.strftime('%B')} {d.day}"


def _number(value: Any) -> Optional[float]:
    """A finite float from a wire value (Decimal, int, float or a numeric string); None otherwise."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        f = float(value) if not isinstance(value, Decimal) else float(value)
    except (TypeError, ValueError, ArithmeticError):
        return None
    return f if math.isfinite(f) else None


#: How each what_changed unit reads (decimal places, words). A unit not listed is not rendered (fail closed).
_UNIT_FORMAT = {
    "%": (0, "{v}%"),
    "ms": (0, "{v} ms"),
    "bpm": (0, "{v} bpm"),
    "h": (1, "{v} hours"),
    "/day": (0, "{v} a day"),
    "g": (0, "{v} g"),
    "lbs": (1, "{v} lb"),
    "lb": (1, "{v} lb"),
    "kcal": (0, "{v} kcal"),
}


def _fmt(value: float, places: int) -> str:
    return f"{value:,.{places}f}"


def _clean_text(text: Any) -> Optional[str]:
    """Stored words a reader may see: whole (never cut), at most MAX_TEXT_CHARS, and with no machine fragment."""
    t = " ".join(str(text or "").split())
    if not t or len(t) > MAX_TEXT_CHARS or machine_fragments(t):
        return None
    return t


#: Reader words for the measures a correlation pair can name (weekly_correlation_compute's metric keys). A pair naming
#: a measure not listed here is not shown — a correlation is never printed without both of its measures named.
CORRELATION_WORDS = {
    "hrv": "heart-rate variability",
    "recovery_score": "morning recovery score",
    "sleep_duration": "sleep time",
    "sleep_score": "sleep score",
    "resting_hr": "resting heart rate",
    "strain": "strain",
    "training_kj": "training load",
    "training_mins": "training minutes",
    "protein_g": "protein eaten",
    "calories": "calories eaten",
    "carbs_g": "carbohydrate eaten",
    "fat_g": "fat eaten",
    "steps": "daily steps",
    "readiness": "readiness score",
}
_STRENGTHS = ("weak", "moderate", "strong", "very strong")


def _delta_lines(deltas: Any) -> list:
    out = []
    for d in deltas or []:
        if not isinstance(d, dict):
            continue
        fmt = _UNIT_FORMAT.get(str(d.get("unit") or "").strip())
        label = _clean_text(d.get("label"))
        cur, prior = _number(d.get("this_month_avg")), _number(d.get("prior_month_avg"))
        if fmt is None or label is None or cur is None or prior is None:
            continue
        places, words = fmt
        cur_r, prior_r = round(cur, places), round(prior, places)
        if cur_r == prior_r:
            continue  # no motion a reader can see at this precision
        move = "up" if cur_r > prior_r else "down"
        out.append(f"{label}: {words.format(v=_fmt(cur_r, places))}, {move} from {words.format(v=_fmt(prior_r, places))}")
    return out


def _unlocked_lines(unlocked: Any, today: str) -> list:
    out = []
    for u in unlocked or []:
        if not isinstance(u, dict):
            continue
        a, b = CORRELATION_WORDS.get(str(u.get("metric_a") or "")), CORRELATION_WORDS.get(str(u.get("metric_b") or ""))
        r, n = _number(u.get("r")), _number(u.get("n"))
        seen = _in_window(u.get("first_seen"), today)
        if not (a and b and r is not None and -1 <= r <= 1 and n is not None and n >= 3 and seen):
            continue
        strength = str(u.get("interpretation") or "").strip().lower()
        if strength not in _STRENGTHS:
            strength = "weak" if abs(r) < 0.3 else "moderate" if abs(r) < 0.5 else "strong"
        together = "rose and fell together" if r > 0 else "moved in opposite directions"
        out.append(
            f"{a[:1].upper() + a[1:]} and {b} {together}: a {strength} correlation (r = {r:.2f} across {int(n)} days), "
            f"first significant in the week ending {_day_words(seen)}. A correlation, not evidence that one causes the other."
        )
    return out


def curate(digest: dict, today: Optional[str] = None) -> dict:
    """The reader version of a gathered digest — pure. Every item is a finished sentence (or set of fields) a reader
    can read, dated, inside the window, at human precision; everything else is dropped. Idempotent on its own output."""
    if isinstance(digest, dict) and digest.get("curated"):
        return digest
    today = today or _today()
    d = digest if isinstance(digest, dict) else {}
    out: dict[str, Any] = {"curated": True, "today": today, "deltas": [], "delta_window": None}

    start, end = _parse_day(d.get("window_start")), _in_window(d.get("window_end"), today)
    if start is not None and end is not None and start <= end:
        lines = _delta_lines(d.get("deltas"))
        if lines:
            out["deltas"] = lines
            days = (end - start).days + 1
            out["delta_window"] = f"Daily averages for {_day_words(start)} to {_day_words(end)}, against the {days} days before."

    out["unlocked"] = _unlocked_lines(d.get("unlocked"), today)

    decided = []
    for p in d.get("decided") or []:
        if not isinstance(p, dict) or p.get("status") not in ("confirmed", "refuted"):
            continue
        on = _in_window(p.get("decided_at"), today)
        claim = _clean_text(p.get("claim"))
        coach = _clean_text(p.get("coach"))
        if on is None or claim is None or coach is None:
            continue
        decided.append(
            {
                "status": p["status"],
                "coach": coach,
                "claim": claim,
                "reason": _clean_text(p.get("reason")),  # reader words or nothing — never the grader's working
                "on": _day_words(on),
                "_day": on.isoformat(),
            }
        )
    decided.sort(key=lambda x: x["_day"], reverse=True)
    out["decided"] = [{k: v for k, v in x.items() if k != "_day"} for x in decided[:6]]

    shifts = []
    for s in d.get("stance_shifts") or []:
        if not isinstance(s, dict):
            continue
        on = _in_window(s.get("as_of"), today)
        shift, coach = _clean_text(s.get("shift")), _clean_text(s.get("coach"))
        if on is None or shift is None or coach is None:
            continue
        shifts.append({"coach": coach, "stage": _clean_text(s.get("stage")) or "", "shift": shift, "on": _day_words(on)})
    out["stance_shifts"] = shifts[:4]

    elena_on = _in_window(d.get("elena_as_of"), today)
    note = _clean_text(d.get("elena_note")) if elena_on else None
    out["elena_note"] = note
    out["elena_on"] = _day_words(elena_on) if note and elena_on else None
    return out


# ── #6244: the final check — no machine-format fragment reaches a reader ─────────────────────────────────────────

#: (name, pattern) — every pattern is a shape a person never writes in a sentence to a reader. The privacy scrub's own
#: "[redacted]" marker is removed before the check (it is the scrub's reader-facing word, not a structure).
MACHINE_PATTERNS = (
    ("structure", re.compile(r"[{}\[\]]")),
    ("null_word", re.compile(r"\b(?:None|null|NULL|NaN|nan|Infinity|undefined)\b")),
    # more than one decimal place — except a correlation's r, which is read to two ("r = 0.36")
    ("precision", re.compile(r"(?<![\d.])(?<!r = )(?<!r = -)\d+\.\d{2,}")),
    ("identifier", re.compile(r"\b[a-z0-9]+_[a-z0-9_]+\b")),
    ("assignment", re.compile(r"\b[a-z_][a-z0-9_]*=")),
    ("iso_day", re.compile(r"\b\d{4}-\d{2}-\d{2}")),
    ("escape", re.compile(r"\\u[0-9a-fA-F]{4}|\\n|\\\"")),
    ("decimal_repr", re.compile(r"Decimal\(")),
    ("pipe", re.compile(r"\|")),
)


def machine_fragments(text: Any) -> list:
    """Every machine-format fragment in ``text`` as ``"<name>: <match>"`` ([] = clean)."""
    t = str(text or "").replace("[redacted]", "")
    found = []
    for name, pat in MACHINE_PATTERNS:
        m = pat.search(t)
        if m:
            found.append(f"{name}: {m.group(0)!r}")
    return found


def visible_text(html_doc: str) -> str:
    """The words a reader sees in an HTML email: no tags, no style blocks, entities decoded."""
    t = re.sub(r"<(style|script|head)\b.*?</\1>", " ", str(html_doc or ""), flags=re.S | re.I)
    t = re.sub(r"</?(?:span|strong|em|b|i|a)\b[^>]*>", "", t, flags=re.I)  # inline: no word break
    t = re.sub(r"<[^>]+>", " ", t)
    return " ".join(_html.unescape(t).split())


class RenderRefused(RuntimeError):
    """The rendered note still carries a machine-format fragment — nothing is sent."""


# ── Build (plain HTML, no tracking pixel, no per-link redirects) ─────────────


#: #6151: this note's own muted green, kept for the footer — 7.56:1 on #0b0f0d (the old #5a7565 was 3.83:1).
FOOTER_TEXT = "#8aaa90"


def _safe(text: Any) -> str:
    """Scrubbed (fail closed, #2654), then escaped: stored text is data, never markup."""
    return _html.escape(_scrub(text), quote=False)


def build_email(digest: dict, sub_email: str, today: Optional[str] = None) -> tuple:
    """(subject, html) for one subscriber. The digest is curated here when it is not already (``curate`` is
    idempotent), and the finished text is checked: a machine-format fragment raises ``RenderRefused``."""
    c = curate(digest, today)
    unsub = unsub_url_or_fallback(sub_email, SITE_URL)  # #3044
    parts = [
        # #6151: a whole document (it was a bare <div>) so the dark colour scheme is declared, plus a preheader
        f'<!DOCTYPE html><html><head>{head_meta()}</head><body style="margin:0;padding:0;background:#0b0f0d;">',
        preheader_html("Since the last installment: what the machine found between chronicles."),
        '<div style="background:#0b0f0d;color:#e8f0e8;font-family:Georgia,serif;padding:28px;max-width:640px;margin:auto;">',
        '<p style="font-family:monospace;font-size:11px;letter-spacing:.08em;color:#8aaa90;text-transform:uppercase;">since the last installment · what the machine found</p>',
    ]
    # #537: Elena signs this email — her current editorial read opens it (dated, #6244).
    if c.get("elena_note"):
        parts.append(f'<p style="margin:14px 0 4px;font-size:14px;font-style:italic;color:#cfd8cf;">{_safe(c["elena_note"])}</p>')
        parts.append(
            f'<p style="margin:0 0 10px;font-family:monospace;font-size:11px;color:#8aaa90;">— Elena, where I stood on {_safe(c["elena_on"])}</p>'
        )
    if c["decided"]:
        parts.append('<h2 style="font-size:18px;margin:18px 0 6px;">Calls that were graded</h2>')
        for p in c["decided"]:
            verdict = "Called it" if p["status"] == "confirmed" else "Missed"
            parts.append(
                f'<p style="margin:6px 0;font-size:14px;color:#cfd8cf;"><strong>{verdict}</strong> — '
                f'the {_safe(p["coach"])} coach said “{_safe(p["claim"])}” '
                f'<span style="color:#8aaa90;">(graded {_safe(p["on"])})</span>'
                + (f'<br><span style="color:#8aaa90;">{_safe(p["reason"])}.</span>' if p.get("reason") else "")
                + "</p>"
            )
    if c["unlocked"]:
        parts.append('<h2 style="font-size:18px;margin:18px 0 6px;">Newly significant</h2>')
        for line in c["unlocked"]:
            parts.append(f'<p style="margin:4px 0;font-size:14px;color:#cfd8cf;">{_safe(line)}</p>')
    if c["stance_shifts"]:
        parts.append('<h2 style="font-size:18px;margin:18px 0 6px;">Coaches who changed their read</h2>')
        for s in c["stance_shifts"]:
            parts.append(
                f'<p style="margin:6px 0;font-size:14px;color:#cfd8cf;"><strong>The {_safe(s["coach"])} coach</strong>'
                + (f' <span style="color:#8aaa90;">({_safe(s["stage"])})</span>' if s["stage"] else "")
                + f' <span style="color:#8aaa90;">on {_safe(s["on"])}</span>: {_safe(s["shift"])}</p>'
            )
    if c["deltas"] and c["delta_window"]:
        parts.append('<h2 style="font-size:18px;margin:18px 0 6px;">The month in averages</h2>')
        parts.append(f'<p style="margin:2px 0 6px;font-size:13px;color:#8aaa90;">{_safe(c["delta_window"])}</p>')
        for line in c["deltas"]:
            parts.append(f'<p style="margin:4px 0;font-size:14px;color:#cfd8cf;">{_safe(line)}</p>')
    parts.append(
        f'<p style="margin-top:22px;font-size:13px;color:#8aaa90;">Every figure above comes from the records the public site serves, '
        f"rounded for reading. Single-subject experiment (N=1) — patterns, never proof. "
        f'<a href="{SITE_URL}/cockpit/" style="color:#8aaa90;">The live cockpit →</a></p>'
        f'<p style="margin-top:14px;font-family:monospace;font-size:11px;color:{FOOTER_TEXT};">No open tracking on this email. '
        f'<a href="{unsub}" style="color:{FOOTER_TEXT};">unsubscribe</a></p></div></body></html>'
    )
    n_bits = len(c["decided"]) + len(c["unlocked"]) + len(c["stance_shifts"])
    subject = f"Between chronicles: {n_bits} thing{'s' if n_bits != 1 else ''} the machine found"
    html_doc = "".join(parts)
    problems = machine_fragments(subject) + machine_fragments(visible_text(html_doc))
    if problems:
        logger.error(
            "[%s] the rendered note carries machine fragments (%s) — nothing is sent", RENDER_REFUSED_TOKEN, "; ".join(problems)[:300]
        )
        raise RenderRefused("; ".join(problems))
    return subject, html_doc


# ── Send ─────────────────────────────────────────────────────────────────────


def _get_confirmed_subscribers() -> list:
    confirmed: list[dict[str, Any]] = []
    kwargs = {
        "KeyConditionExpression": "pk = :pk",
        "FilterExpression": "#s = :confirmed",
        "ExpressionAttributeNames": {"#s": "status"},
        "ExpressionAttributeValues": {":pk": SUBSCRIBERS_PK, ":confirmed": "confirmed"},
    }
    while True:
        resp = table.query(**kwargs)
        confirmed.extend(_d2f(i) for i in resp.get("Items", []))
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    return confirmed


#: The `email_log#` partition this sender's completion rows live in (#3113).
#: This sender had NO email_log row at all before #3113 — the content-hash
#: marker below is a "has this content changed" check, not a send record.
LEDGER_NAME = "between_chronicle"


def _period_key() -> str:
    """WHICH note this is — `week:YYYY-Www` (#3113).

    Deliberately NOT the content hash, even though one is already computed
    here: the digest is assembled from live records (freshly graded
    predictions, stance shifts), so a redrive hours later can hash *differently*
    for the same letter and the existing marker check sails straight through.
    The note is weekly (Sunday 17:00 UTC); one per ISO week is the invariant
    that survives that drift.
    """
    return f"week:{send_ledger.iso_week_key(pacific_now().date())}"


def lambda_handler(event: dict, context) -> dict:
    event = event or {}

    # DIL-025 / #3113 replay guard. The marker write below lands AFTER the whole
    # subscriber fan-out, so "mailed 300 people, then crashed" left no record at
    # all and a redrive re-mailed the list. Dry runs put nothing on the wire.
    period_key = _period_key()
    if send_ledger.should_skip_replay(
        table, LEDGER_NAME, period_key, dry_run=bool(event.get("dry_run")), event=event, user_id=USER_ID, logger=logger
    ):
        logger.warning("[DIL-025] between-chronicle note for %s already sent — refusing to send it twice", period_key)
        return {"statusCode": 200, "sent": 0, "skipped": "replay_guard", "period_key": period_key}

    today = _today()
    digest = curate(gather_digest(), today)  # #6244: the reader version — dated, in-window, human precision, or dropped
    h = digest_hash({k: v for k, v in digest.items() if k != "today"})

    if not has_real_content(digest):
        logger.info("no real content this period — sending nothing (honest silence)")
        return {"statusCode": 200, "sent": 0, "skipped": "empty_period"}

    try:
        marker = _d2f(table.get_item(Key={"pk": MARKER_PK, "sk": MARKER_SK}).get("Item") or {})
    except Exception:
        marker = {}
    if marker.get("content_hash") == h:
        logger.info("digest unchanged since last send — sending nothing")
        return {"statusCode": 200, "sent": 0, "skipped": "unchanged"}

    if event.get("dry_run"):
        # A dry run renders the real email (the owner reviews this before any release) and sends nothing.
        subject, html = build_email(digest, "preview@example.com", today)
        return {
            "statusCode": 200,
            "dry_run": True,
            "subject": subject,
            "digest": digest,
            "html_bytes": len(html),
            "held": not is_released(),
        }

    # #6244: the owner's hold — before the kill switch, the subscriber read and every send. Fail closed.
    problems = release_problems(OWNER_RELEASE)
    if problems:
        logger.warning("[%s] between-chronicle note held — nothing sent (%s)", HELD_TOKEN, "; ".join(problems))
        return {"statusCode": 200, "sent": 0, "skipped": "held", "held_because": problems}

    if os.environ.get("EXTERNAL_EMAILS_ENABLED", "true").lower() != "true":
        logger.info("[kill-switch] EXTERNAL_EMAILS_ENABLED=false — skipping subscriber send")
        return {"statusCode": 200, "sent": 0, "skipped": "external_emails_disabled"}

    # Render once BEFORE the fan-out, so a refused render (RenderRefused) stops the run before any subscriber is mailed.
    build_email(digest, "preview@example.com", today)

    subs = _get_confirmed_subscribers()
    if not subs:
        logger.info("no confirmed subscribers — no-op")
        return {"statusCode": 200, "sent": 0, "skipped": "no_subscribers"}

    rate_delay = 1.0 / max(SEND_RATE_PER_SEC, 0.1)
    sent = failed = 0
    for i, sub in enumerate(subs):
        email = (sub.get("email") or "").strip()
        if not email:
            continue
        subject, html = build_email(digest, email, today)
        try:
            ses.send_email(
                FromEmailAddress=SENDER,
                Destination={"ToAddresses": [email]},
                # #6151: text part derived from the scrubbed HTML + List-Unsubscribe headers
                Content=simple_content(reader_mail(subject), html=reader_mail(html), unsub_url=unsub_url_or_fallback(email, SITE_URL)),
            )
            sent += 1
            if sent == 1:
                # DIL-025: mail is on the wire NOW. Record before the remaining
                # ~N sends and before the marker write at the end of the fan-out.
                send_ledger.record_sent(table, LEDGER_NAME, period_key, user_id=USER_ID, logger=logger)
        except Exception as exc:
            failed += 1
            logger.error("send failed to %s…: %s", email[:6], exc)
        if i < len(subs) - 1:
            time.sleep(rate_delay)

    try:
        table.put_item(
            Item={
                "pk": MARKER_PK,
                "sk": MARKER_SK,
                "content_hash": h,
                "sent_at": datetime.now(timezone.utc).isoformat(),
                "sent_count": sent,
            }
        )
    except Exception as e:
        logger.warning("marker write failed (next run may resend): %s", e)

    logger.info("between-chronicle note sent: %d ok, %d failed", sent, failed)
    return {"statusCode": 200, "sent": sent, "failed": failed}
