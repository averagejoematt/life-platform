"""
Wednesday Chronicle Lambda — v1.1.0 (Board Centralization)
"The Measured Life" by Elena Voss
Fires Wednesday 7:00 AM PT (15:00 UTC via EventBridge).

Elena Voss, the series' AI narrator (content/elena_canon.py, #6155), writes the weekly installment —
through the Story Desk (content/story_pipeline.py) and, when the desk declines or fails, the legacy writer
(emails/chronicle_prompt.py), which then runs the desk's quote and ledger checks and holds the week (#6155).
The journal is not read (owner rulings 2026-11-03/05).

Each installment is:
  1. Emailed as a newsletter
  2. Published to the v4 journal (generated/journal/, /story/chronicle/)
  3. Stored in DynamoDB for continuity (last 4 installments fed to AI)

AI Model: Sonnet 4.5 (temperature 0.6 for creative voice)
Cost: ~$0.04/week (~$0.16/month)

#6155: Elena is rendered from content/elena_canon.py on every path; the S3 board config's Elena entry and its
        chronicle interviewees are no longer read by the prompt.
"""

import json
import logging
import os
import secrets as _secrets
from datetime import datetime, timedelta, timezone  # noqa: F401 — timezone is resolved via the _g seam (chronicle_personas:204)

import boto3
from common import digest_utils  # shared query_range implementations (#970)
from common.constants import EXPERIMENT_START_DATE  # ADR-058
from common.text_utils import truncate_at_word  # #1224: word-boundary excerpt truncation (no mid-word cut)
from privacy import privacy_guard  # deterministic real-name + vice gate (layer module)

# ADR-058 / #946: query paths get the phase filter via digest_utils (#970); the
# singleton reads that need `singleton_visible` directly now live in the split
# modules (chronicle_data, chronicle_personas), which import it themselves.

# OBS-1: Structured logger (wired below after optional imports)
_logger_std = logging.getLogger()
_logger_std.setLevel(logging.INFO)

REGION = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
S3_BUCKET = os.environ["S3_BUCKET"]
USER_ID = os.environ.get("USER_ID", "matthew")
RECIPIENT = os.environ["EMAIL_RECIPIENT"]
SENDER = os.environ["EMAIL_SENDER"]
# #548: Margaret Calloway's red pen — the Haiku model for her critique + revision
# calls (kept cheap and separate from Elena's Sonnet narrative voice, ADR-063 budget).
from ai.model_routing import model_for  # noqa: E402 — #4770: the one model registry

AI_MODEL_HAIKU = model_for("chronicle")

# FEAT-12: Preview-before-publish workflow.
# When PREVIEW_MODE=true (default), the Chronicle is stored as a draft in DynamoDB
# and a preview email is sent to RECIPIENT with Approve / Request Changes links.
# No content is published to S3 until Matthew approves via the chronicle-approve Lambda.
PREVIEW_MODE = os.environ.get("PREVIEW_MODE", "true").lower() == "true"
APPROVE_LAMBDA_URL = os.environ.get("APPROVE_LAMBDA_URL", "")  # Function URL of chronicle-approve

USER_PREFIX = f"USER#{USER_ID}#SOURCE#"

dynamodb = boto3.resource("dynamodb", region_name=REGION)
table = dynamodb.Table(TABLE_NAME)
ses = boto3.client("sesv2", region_name=REGION)
s3 = boto3.client("s3", region_name=REGION)
secrets = boto3.client("secretsmanager", region_name=REGION)

# Board of Directors config loader. Read by the split modules off this facade's
# globals (`_g["board_loader"]` — chronicle_prompt, chronicle_personas), which is
# why it is bound here and not imported at each use site: `_HAS_BOARD_LOADER` is
# part of the monkeypatch surface the tests drive.
try:
    from coach import board_loader  # noqa: F401 — facade state, consumed via the `_g` hand-off

    _HAS_BOARD_LOADER = True
except ImportError:
    _HAS_BOARD_LOADER = False

try:
    from content import insight_writer

    insight_writer.init(table, USER_ID)
    _HAS_INSIGHT_WRITER = True
except ImportError:
    _HAS_INSIGHT_WRITER = False

# #4865: AI-3's chronicle length ceilings, per writer (validate_ai_output's own default is 5,000).
AI3_LEGACY_MAX_CHARS = 5_000
AI3_DESK_MAX_CHARS = 9_000  # 1,200 words ≈ 7,200 chars + the dek + the footer, with headroom

# AI-3: Output validation
try:
    from ai.ai_output_validator import AIOutputType, validate_ai_output

    _HAS_AI_VALIDATOR = True
except ImportError:
    _HAS_AI_VALIDATOR = False

# BS-05: Confidence badge
from common.digest_utils import compute_confidence

_HAS_CONFIDENCE = True

# #405: the per-chronicle share kit (email-stack module — text/JSON only, no Pillow/AI).
try:
    from content import chronicle_share_kit

    _HAS_SHARE_KIT = True
except ImportError:
    _HAS_SHARE_KIT = False


# OBS-1: Structured logger
try:
    from common.platform_logger import get_logger

    logger = get_logger("wednesday-chronicle")
except ImportError:
    import logging as _log

    logger = _log.getLogger("wednesday-chronicle")
    logger.setLevel(_log.INFO)


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════


from common.digest_utils import d2f  # shared bundled helpers (#970)

# ── #1654 god-module split: the handler logic lives in cohesive sibling modules
# under lambdas/emails/; this file is the thin facade. Each moved helper reads the
# facade's live (possibly monkeypatched) module state through a per-call globals()
# hand-off (`_g`), so routes, contracts, and the test monkeypatch surface are
# unchanged. The helpers do NOT import this module, so there is no import cycle.
from emails import (  # noqa: E402
    chronicle_data as _data,
    chronicle_personas as _personas,
    chronicle_prompt as _prompt,
    chronicle_recap as _recap,
    chronicle_render as _render,
    chronicle_store as _store,
)


def query_range(source, start_date, end_date):
    """Batch query all records for a source in a date range, as a {date: record} dict.

    Shared paginated, phase-scoped implementation (digest_utils, #970).
    """
    return digest_utils.query_range(table, source, start_date, end_date, user_id=USER_ID)


def query_range_list(source, start_date, end_date):
    """Like query_range but returns a flat list, preserving duplicates (per-workout
    schemas like Hevy, #485). Shared paginated implementation (digest_utils, #970)."""
    return digest_utils.query_range_list(table, source, start_date, end_date, user_id=USER_ID)


def fetch_profile():
    from intelligence.intelligence_common import fetch_profile as _shared_fetch_profile

    return _shared_fetch_profile(table, USER_ID)


# #6155: the fallback is the legacy writer's ONE rendering — Elena from content.elena_canon, the roster from the coach
# registry. The old in-code copy carried personal details about the owner and its own Elena; both are gone.
_FALLBACK_ELENA_PROMPT_TEMPLATE = _prompt.LEGACY_PROMPT_TEMPLATE


def _fallback_elena_prompt():
    """The fallback prompt, materialized at call time (the vice enumeration comes from the ER-06 non-committed channel,
    #2370; fail-closed via _vice_terms_clause). Identical to the primary path's prompt by construction."""
    return _prompt.legacy_prompt()


def __getattr__(name):
    # Back-compat (PEP 562): tests and callers keep reading
    # `wednesday_chronicle_lambda._FALLBACK_ELENA_PROMPT` as a finished prompt.
    if name == "_FALLBACK_ELENA_PROMPT":
        return _fallback_elena_prompt()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# ══════════════════════════════════════════════════════════════════════════════
# FACADE DELEGATORS — thin wrappers over the split modules (#1654). Names/signatures
# are unchanged; each passes this module's globals() as `_g` where the moved helper
# reads facade state, so tests that monkeypatch this module still take effect.
# ══════════════════════════════════════════════════════════════════════════════


def gather_chronicle_data():
    return _data.gather_chronicle_data(_g=globals())


def build_calendar_facts(start, end, genesis=None):
    return _data.build_calendar_facts(start, end, genesis=genesis)


def build_data_packet(data):
    return _data.build_data_packet(data)


def _load_engagement_signal():
    return _data._load_engagement_signal(_g=globals())


def _build_elena_prompt_from_config():
    return _prompt._build_elena_prompt_from_config(_g=globals())


def call_anthropic(system_prompt, user_message, archive_text=None):
    return _prompt.call_anthropic(system_prompt, user_message, archive_text=archive_text)


def installment_grounding_findings(elena_prompt, user_message, text, archive_text=None):
    return _prompt.installment_grounding_findings(elena_prompt, user_message, text, archive_text=archive_text)


def build_recap(data, new_installment_md=None, new_meta=None):
    return _recap.build_recap(data, new_installment_md=new_installment_md, new_meta=new_meta, _g=globals())


def _write_recap(recap, date_str):
    return _recap._write_recap(recap, date_str, _g=globals())


_parse_recap_json = _recap._parse_recap_json


def markdown_to_html(md_text):
    return _render.markdown_to_html(md_text)


def parse_installment(raw_text):
    return _render.parse_installment(raw_text)


def build_email_html(title, stats_line, body_html, week_num, date_str, series_url):
    return _render.build_email_html(title, stats_line, body_html, week_num, date_str, series_url)


def journal_post_ref(date_str, all_installments, week_num):
    return _render.journal_post_ref(date_str, all_installments, week_num, _g=globals())


def display_stats_line(stats_line, date_str):
    return _render.display_stats_line(stats_line, date_str, _g=globals())


def publish_to_journal(title, stats_line, body_html, week_num, date_str, all_installments, write_to_s3=True):
    return _render.publish_to_journal(
        title, stats_line, body_html, week_num, date_str, all_installments, write_to_s3=write_to_s3, _g=globals()
    )


build_weekly_signal_data = _render.build_weekly_signal_data


def store_installment(*args, **kwargs):
    return _store.store_installment(*args, _g=globals(), **kwargs)


def _set_chronicle_pending(week_num, reason, display):
    return _store._set_chronicle_pending(week_num, reason, display, _g=globals())


def _send_preview_email(title, week_num, date_str, approval_token, email_html, kit_block="", desk_fallback="", craft=()):
    return _store._send_preview_email(
        title, week_num, date_str, approval_token, email_html, kit_block=kit_block, desk_fallback=desk_fallback, craft=craft, _g=globals()
    )


def _held_week(week_num, reason, display, body, status_code=500, dry_run=False):
    return _store.held_week(week_num, reason, display, body, status_code=status_code, dry_run=dry_run, _g=globals())


# ══════════════════════════════════════════════════════════════════════════════
# HANDLER
# ══════════════════════════════════════════════════════════════════════════════


def record_email_send(table, lambda_name):
    return _store.record_email_send(table, lambda_name, _g=globals())


# #2254 pagination cap — rationale at chronicle_store; kept here for its consumers.
_MAX_INSTALLMENT_PAGES = 25


def _existing_installment(date_str):
    return _store.existing_installment(date_str, _g=globals())


# ══════════════════════════════════════════════════════════════════════════════
# PERSONA LAYER (#1654) — Elena's notebook + state refresh and Margaret's red pen
# live in emails/chronicle_personas.py (everything that reads or writes a
# PERSONA#<slug> partition, plus the editorial pass built on it). These stay here
# as same-name, same-signature delegators so the handler, callers and the test
# monkeypatch surface are unchanged.
# ══════════════════════════════════════════════════════════════════════════════

_ELENA_PERSONA_PK = _personas._ELENA_PERSONA_PK
_MARGARET_PERSONA_PK = _personas._MARGARET_PERSONA_PK


def _elena_notebook_block(current_week):
    return _personas._elena_notebook_block(current_week, _g=globals())


def _invoke_elena_state_updater(date_str):
    return _personas._invoke_elena_state_updater(date_str, _g=globals())


def _due_callback_promises(week_num, limit=5):
    return _personas._due_callback_promises(week_num, limit=limit, _g=globals())


def _margaret_last_note_date():
    return _personas._margaret_last_note_date(_g=globals())


def _record_margaret_note(date_str, week_num, note):
    return _personas._record_margaret_note(date_str, week_num, note, _g=globals())


def _margaret_haiku_call(system, user):
    return _personas._margaret_haiku_call(system, user, _g=globals())


def _elena_revision_call(system, user, max_tokens):
    return _personas._elena_revision_call(system, user, max_tokens, _g=globals())


def _run_margaret_edit_pass(raw_installment, week_num, date_str, elena_prompt, allowed_numbers):
    return _personas._run_margaret_edit_pass(raw_installment, week_num, date_str, elena_prompt, allowed_numbers, _g=globals())


def _rehearsal_week_end(event):
    """#4535 past-week mode: the week-end date a REHEARSAL names, or None.

    ``{"dry_run": true, "week": N}`` resolves to the season's week N from the one
    calendar (``story_dossier.season_weeks`` — Week 1 runs genesis → the first Tuesday,
    then Wednesday → Tuesday), so the desk builds that window regardless of the run date.
    ``desk_week_end`` (an explicit date) wins when both are given. Dry runs only: a
    publishing run stores under today's window, so a past week can never be published
    over the current one by naming it."""
    if not event.get("dry_run"):
        return None
    if event.get("desk_week_end"):
        return event["desk_week_end"]
    week = event.get("week")
    if week is None or isinstance(week, bool):
        return None
    try:
        n = int(week)
    except (TypeError, ValueError):
        return None
    if n < 1:
        return None
    from content import story_dossier

    weeks = story_dossier.season_weeks()
    return weeks[n - 1]["end"] if n <= len(weeks) else None


def _handler_core(event: dict, context) -> dict:
    logger.info("Wednesday Chronicle v1.1.0 (Board Centralization) — The Measured Life — starting...")

    # Phase 3 bootstrap/regenerate: {"recap_only": true} builds + commits the
    # "previously on" recap from EXISTING published installments WITHOUT writing a new
    # chronicle week. Lets the first recap go live now (and supports regeneration)
    # without forcing an out-of-cadence installment.
    event = event or {}

    # #2221 (#2111 class): {"dry_run": true} rehearses the week — gather, packet, the
    # Sonnet call, the grounding/presence/AI-3/privacy gates and the render all run, and
    # NOTHING is written, published or mailed: no installment row, no journal/share-kit
    # S3 write, no pending marker, no recap commit, no Elena state invoke, no insight
    # row, no email_log row, no SES send. It is not free — the model call is the point,
    # so a rehearsal costs one Sonnet generation — but it is the only way to inspect a
    # week without mailing Matthew. Sibling email lambdas (between_chronicle,
    # chronicle_approve, coach_panel_podcast) accept the same flag; this one — the most
    # expensive of them — had no gate at all, so every manual invoke sent mail.
    _dry = bool(event.get("dry_run"))
    if _dry:
        logger.info("[dry_run] rehearsal invoke — the week will be built but never stored, published or mailed")

    # #4535 box 2: a rehearsal that NAMES a past week ({"dry_run": true, "week": N} / "desk_week_end") is built by the
    # desk from that week's window alone (story_pipeline.live_week reads only (table, week_end)). The legacy gather and
    # data packet below still run — they are the fallback writer's input and the continuity context — but they cover
    # the CURRENT window, so every log line and every output field that would otherwise carry the current window's
    # date or week is labelled or replaced, and the rehearsal never falls back to writing the current week.
    _rehearsal_end = _rehearsal_week_end(event)
    if _rehearsal_end:
        logger.info(
            f"[#4535] rehearsal names the week ending {_rehearsal_end} — the desk builds that window only; the legacy "
            "gather/packet below cover the CURRENT window and are never handed to the desk's writer"
        )

    # Phase 3 bootstrap/regenerate: {"recap_only": true} builds + commits the
    # "previously on" recap from EXISTING published installments WITHOUT writing a new
    # chronicle week. Lets the first recap go live now (and supports regeneration)
    # without forcing an out-of-cadence installment.
    if event.get("recap_only"):
        data = gather_chronicle_data()
        if not data:
            return {"statusCode": 500, "body": "Failed to gather data"}
        recap = build_recap(data, new_installment_md=None, new_meta=None)
        if not recap or not recap.get("as_of"):
            return {"statusCode": 200, "body": json.dumps({"status": "recap_skipped", "reason": "no published history or build failed"})}
        if _dry:
            return {
                "statusCode": 200,
                "body": json.dumps({"status": "dry_run_recap", "as_of": recap["as_of"], "beats": len(recap.get("recent_beats", []))}),
            }
        _write_recap(recap, recap["as_of"])
        return {
            "statusCode": 200,
            "body": json.dumps({"status": "recap_written", "as_of": recap["as_of"], "beats": len(recap.get("recent_beats", []))}),
        }

    # Budget guardrail: skip this week's chronicle when the budget guard pauses it
    # (weekly, non-essential, subscriber-facing) — no Bedrock spend, clean no-op.
    try:
        from ai.budget_guard import allow

        # Chronicle is weekly flagship content (~$1/wk of Bedrock) and the Friday Panel
        # podcast's ONLY input — so it must survive tier 1 and only pause at tier 2,
        # in lockstep with the Panel lambda's SKIP_TIER=2. The cutoff lives in exactly
        # one place — budget_guard._FEATURE_CUTOFF["chronicle"] (==2) — and allow()
        # reads it, so the tier band can be rebanded there without editing this lambda.
        if not allow("chronicle"):
            logger.info("Budget guard paused 'chronicle' — Wednesday chronicle skipped this week (no Bedrock spend)")
            return _held_week(
                None,
                "budget_tier",
                "This week's chronicle is paused — the platform's AI budget guard is protecting monthly spend. "
                "It resumes automatically once usage drops below the threshold.",
                "skipped: budget tier",
                status_code=200,
                dry_run=_dry,
            )
    except ImportError:
        pass

    if _rehearsal_end:
        logger.info("[#4535] legacy gather (current window — fallback-writer input only, not the rehearsed week):")
    data = gather_chronicle_data()
    if not data:
        return _held_week(
            None,
            "generation_error",
            "This week's chronicle didn't land — the platform couldn't assemble the week's data in time. "
            "Nothing was published or stored for this week; it retries on the next run.",
            "Failed to gather data",
            dry_run=_dry,
        )

    # ── #2254: generation-time idempotency ────────────────────────────────────
    # This gate sits BEFORE build_data_packet and the Sonnet call, so a retry, a
    # manual re-invoke or an EventBridge at-least-once redelivery on the same
    # Wednesday costs nothing and, crucially, cannot mint a second approval_token
    # over a draft already sitting in Matthew's inbox (which would silently kill
    # the approve link he was mailed) or overwrite a week he already approved.
    # `changes_requested` is NOT protected — that status is the documented signal
    # to regenerate. {"force": true} is the deliberate-regeneration escape hatch.
    # #2112 closed this class on the downstream sender; this is the generator's half.
    _target_date = (data.get("dates") or {}).get("end")
    _existing_status = None
    # A named-week rehearsal skips it: it writes nothing and mints no token, and the current window's row says
    # nothing about the week it rehearses (a published current week would otherwise refuse a week-4 rehearsal).
    if _target_date and not event.get("force") and not _rehearsal_end:
        _existing = _existing_installment(_target_date)
        _existing_status = (_existing or {}).get("status")
        if _existing_status in _store.PROTECTED_STATUSES:
            logger.info(
                f"[#2254] Week ending {_target_date} already exists with status={_existing_status} — "
                "no regeneration, no Bedrock spend, no email. Pass {'force': true} to regenerate."
            )
            return {
                "statusCode": 200,
                "body": json.dumps(
                    {
                        "status": "already_generated",
                        "date": _target_date,
                        "existing_status": _existing_status,
                        "week": int(_existing.get("week_number", 0) or 0) if _existing else None,
                    }
                ),
            }

    # Build narrative-ready data packet. #2177: build_data_packet is now guarded
    # against the two known partial-record shapes (a day_grades row missing
    # total_score, a macrofactor row missing total_protein_g) at the source —
    # this try/except is the caller-side backstop so a FUTURE unguarded field
    # degrades this week's chronicle (a visible, logged 500) instead of an
    # uncaught exception aborting the run silently.
    try:
        data_packet, week_num = build_data_packet(data)
    except Exception as e:
        logger.error(f"build_data_packet raised: {e}")
        return _held_week(
            None,
            "generation_error",
            "This week's chronicle didn't land — the platform couldn't turn the week's data into the "
            "packet the writer works from. Nothing was published or stored for this week.",
            f"Failed to build data packet: {e}",
            dry_run=_dry,
        )
    if _rehearsal_end:
        logger.info(
            f"[#4535] legacy data packet: {len(data_packet)} chars, current window Week {week_num} — "
            f"fallback-writer input only; the rehearsal's desk builds the week ending {_rehearsal_end}"
        )
    else:
        logger.info(f"Data packet: {len(data_packet)} chars, Week {week_num}")

    # Build user message with previous installments for continuity
    user_parts = [data_packet]

    # #914: the ONE shared presence block — when Matthew's own logging has gone
    # quiet, Elena must not write a normal week over an incomplete window. Same
    # engagement_core.presence_prompt_block every narrative surface injects; the
    # acknowledgment gate below enforces it at severity loud/alarm.
    _presence_sig = {}
    _presence_block_txt = ""
    try:
        from content.engagement_core import presence_prompt_block as _ppb

        _presence_sig = _load_engagement_signal()
        _presence_block_txt = _ppb(_presence_sig)
    except Exception as _pres_e:
        logger.warning(f"[#914] presence block skipped (non-fatal): {_pres_e}")
    if _presence_block_txt:
        user_parts.append("\n\n=== PRESENCE / QUIET STRETCH ===")
        user_parts.append(_presence_block_txt)

    # Editorial guidance — steer toward synthesis, not recounting
    user_parts.append("\n\n=== EDITORIAL GUIDANCE ===")
    user_parts.append("Remember: you are writing a STORY, not a weekly recap.")
    user_parts.append("DO NOT walk through the week day by day (Monday this, Tuesday that...).")
    user_parts.append("Instead: find the 2-3 THEMES that make this week interesting.")
    user_parts.append("Ask yourself: What's the headline? What would make a reader who found this series click 'next week'?")
    user_parts.append("Use the data as EVIDENCE for your narrative thesis, not as the structure of your piece.")
    user_parts.append("Compare to previous weeks where possible — is something changing? Getting harder? Breaking through?")
    user_parts.append("The best installments read like a chapter in a book, not a report card.")

    prev = data["prev_installments"]
    if prev:
        user_parts.append("\n\n=== YOUR PREVIOUS INSTALLMENTS (for continuity) ===")

        # B3: Thesis guardrails — extract recent titles/theses to prevent repetition
        recent_titles = [inst.get("title", "Untitled") for inst in prev]
        if recent_titles:
            user_parts.append("\n=== THESIS GUARDRAILS ===")
            user_parts.append("RECENT THESES (last 4 weeks — do NOT repeat these angles):")
            for t in recent_titles:
                user_parts.append(f'  - "{t}"')
            user_parts.append(
                "This week's thesis MUST be orthogonal to the above. Don't write about the same theme two weeks in a row, even if the data supports it. Find the new angle."
            )

        for inst in reversed(prev):  # oldest first
            wn = inst.get("week_number", "?")
            t = inst.get("title", "Untitled")
            md = inst.get("content_markdown", "")
            if md:
                # Truncate long previous installments to manage token budget
                if len(md) > 2000:
                    md = md[:2000] + "\n[...truncated...]"
                user_parts.append(f'\n--- Week {wn}: "{t}" ---\n{md}')

        # B3: Thread tracking — ask Elena to advance/resolve/complicate prior threads
        user_parts.append("\n=== CONTINUITY INSTRUCTIONS ===")
        user_parts.append(
            "Read the previous installments above. Identify 2-3 story threads that are still active (unresolved tensions, patterns mentioned, questions raised). Your job: advance, resolve, or complicate these threads. Don't ignore them, but don't force them either. If a thread has been mentioned for 3+ weeks without development, either close it or introduce new tension."
        )
    else:
        user_parts.append(
            "\n\nThis is the FIRST installment. Establish the story from the beginning. Who is Matthew? Why is he doing this? What are the stakes? Set the scene in Seattle. Introduce the platform, the data, the obsession. Make the reader want to come back next week."
        )

    # #537: Elena's persistent notebook — open threads, the promise ledger
    # (due callbacks are OBLIGATIONS), motifs, and her receipts-backed stance.
    notebook_block = _elena_notebook_block(week_num)
    if notebook_block:
        user_parts.append(notebook_block)

    user_message = "\n".join(user_parts)
    logger.info(f"Full prompt: {len(user_message)} chars")

    # Try config-driven prompt first, fall back to hardcoded
    elena_prompt = _build_elena_prompt_from_config()
    if elena_prompt:
        logger.info("Using config-driven Elena prompt")
    else:
        logger.info("Using fallback hardcoded Elena prompt")
        elena_prompt = _fallback_elena_prompt()

    # IC-16: Progressive context — narrative-relevant insight threads
    if _HAS_INSIGHT_WRITER:
        try:
            prev_ctx = insight_writer.build_insights_context(days=30, max_items=5, label="PLATFORM INSIGHTS (context for narrative)")
            if prev_ctx:
                # B3: Reframe Field Notes as a hypothesis Elena can agree/disagree with
                field_notes_framing = (
                    "\n=== FIELD NOTES (AI LAB NOTEBOOK) ===\n"
                    "The platform's AI lab notebook produced the following read on this week's data. "
                    "Treat this as a HYPOTHESIS, not gospel. Do you agree with the system's read? "
                    "Deepen it, contradict it, or find the nuance the structured analysis misses. "
                    "The best Chronicle installments emerge from the gap between what the algorithm sees "
                    "and what the journalist notices.\n\n"
                )
                user_message = field_notes_framing + prev_ctx + "\n\n" + user_message
        except Exception as e:
            logger.warning(f"IC-16 failed: {e}")

    # #1385: the ENTIRE multi-cycle installment archive, un-truncated, as a 1-hour
    # cached content block — the whole-life context Elena reasons over for long-range
    # callbacks. Fetched here (all cycles) rather than the inline 4-week/2000-char
    # window; fail-soft to the already-loaded prev_installments, then to "" (no block).
    # The SAME text feeds the grounding allow-list below so a real dated callback
    # passes while a fabricated one is still caught (#1242 / ADR-104).
    try:
        from experiment.phase_filter import with_phase_filter as _wpf
        from health import whole_life_context

        _archive_items = whole_life_context.fetch_full_installment_archive(
            table, f"USER#{USER_ID}#SOURCE#chronicle", d2f=d2f, phase_filter=_wpf
        )
        if not _archive_items:
            _archive_items = data.get("prev_installments") or []
        _archive_text = whole_life_context.format_full_archive(_archive_items)
        # #1829: log the REAL scope (count + cycles present), not a bare count — a run
        # whose archive collapsed to the current cycle must be visible here.
        _scope = whole_life_context.archive_scope(_archive_items)
        logger.info(
            f"[#1385] whole-life archive (phase-filtered, ADR-058 default-deny): {_scope['count']} installment(s), "
            f"cycles={_scope['cycles']}, unlabeled={_scope['unlabeled']}, {len(_archive_text)} chars (1h-cached block)"
        )
    except Exception as _arch_e:  # noqa: BLE001 — the archive is context, never load-bearing
        logger.warning(f"[#1385] archive build skipped (non-fatal): {_arch_e}")
        _archive_text = ""

    # #2669: a cache hit = a prior run finished the model pipeline and died in
    # the tail (08-05 went 3x that way) — reuse skips every model pass below.
    # ONLY into the void a crash left (`_existing_status is None`): a
    # changes_requested week's regeneration must be FRESH — reusing the cache
    # would re-store the exact text Matthew rejected. Rehearsals (#2221) and
    # force never touch it; rationale at chronicle_store.
    _cache_ok = not _dry and not event.get("force") and _target_date and _existing_status is None
    _cached = _store.read_raw_cache(_target_date, _g=globals()) if _cache_ok else None
    _skip_model_passes = _cached is not None
    if _cached is not None:  # the explicit narrow — mypy can't see through the bool
        raw_installment = _cached

    # #4535: the Story Desk writes the week (dossier → desk budget → post + episode → gates → dek). Its own gates
    # replace the legacy passes below — including the #914 presence gate, which forced a logging stall into the story
    # and so narrated MacroFactor export lag as silence. STORY_DESK=off restores the legacy writer.
    _desk, _fallback = None, ""  # #4914: _fallback = why the desk did not write the week (preview subject + banner)
    # the week end every output field carries (date, confidence, recap meta, share-kit label) — the desk's when it wrote
    _week_end = data["dates"]["end"]
    if _cached is None and os.environ.get("STORY_DESK", "on").lower() != "off" and _target_date:
        try:
            from content import story_pipeline

            # a rehearsal may name the week (#4535 proof): {"dry_run": true, "desk_week_end": "YYYY-MM-DD"}
            # or {"dry_run": true, "week": N} — the window is the season's week N, never today's.
            _desk_end = _rehearsal_week_end(event) or _target_date
            _desk = story_pipeline.live_week(table, _desk_end, log=logger.info)
            if _desk is None:
                logger.info(f"[#4535] story desk declined {_desk_end}: not a season week end — legacy writer")
        except Exception as _desk_e:  # noqa: BLE001 — the legacy writer is the fallback, never a dark week
            logger.error(f"[#4535] story desk failed — falling back to the legacy writer: {_desk_e}")
            _desk, _fallback = None, str(_desk_e) or type(_desk_e).__name__
        if _desk:
            raw_installment = _desk["raw_installment"]
            _skip_model_passes = True
            week_num = _desk["week"]
            _week_end = _desk_end
            logger.info(f"[#4535] story desk wrote week {week_num}: {_desk['title']!r} · findings {_desk['findings']}")

    # #4535 box 2: a named-week rehearsal never falls back to the legacy writer — that writer only knows the CURRENT
    # window, so its output would be the current week reported as the rehearsed one.
    if _rehearsal_end and not _desk:
        logger.error(f"[#4535] rehearsal of the week ending {_rehearsal_end}: the desk did not build it — no legacy fallback")
        return {
            "statusCode": 422,
            "body": json.dumps(
                {
                    "status": "rehearsal_not_built",
                    "week_end": _rehearsal_end,
                    "reason": "story desk declined or failed (STORY_DESK=off, not a season week end, or a desk error — see the log)",
                }
            ),
        }

    # Call Sonnet
    try:
        if not _skip_model_passes:
            logger.info("Calling Sonnet for Elena's installment (whole-life-context, 1h-cached archive)...")
            raw_installment = call_anthropic(elena_prompt, user_message, archive_text=_archive_text)
    except Exception as e:
        logger.error(f"Anthropic failed: {e}")
        return _held_week(
            week_num,
            "ai_error",
            f"Week {week_num}'s installment wasn't written — the model call failed. Nothing was published "
            "or stored for this week; the next run picks the story back up.",
            f"AI generation failed: {e}",
            dry_run=_dry,
        )

    logger.info(f"Installment received: {len(raw_installment)} chars, ~{len(raw_installment.split())} words")

    # #537 / ADR-104: the chronicle joins the grounded-generation gate. Every
    # number in the installment must exist somewhere in what Elena was given
    # (the data packet, prior installments, her notebook). Keep-best mode: one
    # corrective rewrite, kept only if strictly better — the weekly story is
    # human-reviewed (PREVIEW_MODE) + privacy-gated downstream, so a residual
    # finding degrades to the best draft instead of going dark.
    _allowed = None
    if _skip_model_passes:
        logger.info("[#2669] cached generation reused — grounding/Margaret/presence passes already ran on this text")
    else:
        try:
            from ai import grounded_generation as _gg

            # #1385: fold the whole-life archive into the allow-list source — Elena was
            # shown it, so its numbers/dates are grounded vocabulary, not fabrications.
            _allowed = _gg.allowed_numbers(elena_prompt, user_message, _archive_text)
            _draft_before_gate = raw_installment  # #812/#744: keep the pre-gate draft for retention
            _findings_fn = lambda t: installment_grounding_findings(elena_prompt, user_message, t, archive_text=_archive_text)  # noqa: E731
            _regen_fn = lambda corr: call_anthropic(elena_prompt, user_message + "\n\n" + corr, archive_text=_archive_text)  # noqa: E731
            raw_installment, _residual, _corrected = _gg.regen_once(raw_installment, _findings_fn, _regen_fn, surface="wednesday_chronicle")
            if _corrected:
                logger.info(f"[ADR-104] chronicle corrected once; residual findings: {len(_residual)}")
            elif _residual:
                logger.warning(f"[ADR-104] chronicle keeps {len(_residual)} residual grounding findings (best draft)")
            if (_corrected or _residual) and not _dry:
                # #812/#744: a fired chronicle gate is labeled eval data — retain the pair.
                # #2221: a rehearsal writes nothing, not even fail-soft eval data.
                try:
                    from experiment import eval_retention

                    eval_retention.retain(
                        "chronicle",
                        "flagged_corrected" if _corrected else "flagged_kept_best",
                        draft=_draft_before_gate,
                        final=raw_installment,
                        findings=_findings_fn(_draft_before_gate),  # the DRAFT's findings — they define a canary's expected checks
                        allowed=_allowed,
                        extra={"week_number": week_num},
                    )
                except Exception:  # noqa: BLE001 — retention is never load-bearing
                    pass
        except ImportError:
            pass  # gate module unavailable — serve as before
        except Exception as _gg_e:
            logger.warning(f"[ADR-104] chronicle grounding gate error (fail-open): {_gg_e}")

        # #548: Margaret Calloway's red pen — one critique + conditional revision
        # pass over Elena's grounded draft, before AI-3 validation / parsing / the
        # privacy gate (all of which still run on whatever text comes back here).
        raw_installment = _run_margaret_edit_pass(raw_installment, week_num, data["dates"]["end"], elena_prompt, _allowed)

        # #914: presence-acknowledgment gate (ADR-108 regenerate-or-hold). Runs AFTER
        # Margaret's edit so her rewrite can't strip the acknowledgment unnoticed. At
        # severity loud/alarm an installment that narrates a normal week over a real
        # logging stall is regenerated once, then HELD — no chronicle beats a dishonest
        # one. Deterministic anchor check, no LLM judge.
        try:
            from content.engagement_core import enforce_presence_acknowledgment as _epa, presence_ack_required as _par

            if _presence_sig and _par(_presence_sig) and raw_installment:
                raw_installment, _ack_finding = _epa(
                    raw_installment,
                    _presence_sig,
                    regenerate_fn=lambda note: call_anthropic(elena_prompt, user_message + "\n\n" + note, archive_text=_archive_text),
                )
                if _ack_finding:
                    logger.warning(f"[#914] chronicle presence-ack gate fired: {_ack_finding.get('detail')}")
                if raw_installment is None:
                    logger.error("[#914] chronicle HELD by presence-ack gate — not publishing this week")
                    return _held_week(
                        week_num,
                        "presence_hold",
                        f"Week {week_num}'s installment was written and then withheld — Matthew's own logging went "
                        "quiet during the window, and the draft narrated a normal week over an incomplete one. "
                        "No chronicle beats a dishonest one. Nothing was published or stored for this week.",
                        "[#914] Chronicle held: presence gap unacknowledged at severity loud/alarm",
                        dry_run=_dry,
                    )
        except ImportError:
            pass  # engagement_core unavailable — serve as before
        except Exception as _ack_e:
            logger.warning(f"[#914] presence-ack gate error (fail-open): {_ack_e}")

    # #2669: pipeline complete — persist NOW, before the render/mail tail can die.
    if not _dry and not _skip_model_passes and _target_date and raw_installment:
        _store.write_raw_cache(_target_date, week_num, raw_installment, _g=globals())

    # AI-3: Validate output before rendering
    if _HAS_AI_VALIDATOR and raw_installment:
        # #4865: the 5,000-char default is the legacy writer's ceiling; the Story Desk's post (900-1,200 words, then
        # the dek) runs ~6,500 chars by design, so measuring it against 5,000 warned on every desk week.
        _ai3_writer = "story_desk" if _desk else "legacy"
        _ai3_max = AI3_DESK_MAX_CHARS if _desk else AI3_LEGACY_MAX_CHARS
        _val = validate_ai_output(raw_installment, AIOutputType.CHRONICLE, min_length=200, max_length=_ai3_max)
        if _val.blocked:
            logger.error(f"[AI-3] Chronicle BLOCKED: {_val.block_reason}")
            return _held_week(
                week_num,
                "safety_hold",
                f"Week {week_num}'s installment was generated but withheld before publishing — it didn't clear "
                "the platform's automatic output check on the writing itself. No content was published or "
                "stored for this week.",
                f"[AI-3] Chronicle blocked: {_val.block_reason}",
                dry_run=_dry,
            )
        elif _val.warnings:
            logger.warning(f"[AI-3] Chronicle warnings (writer={_ai3_writer}, max_length={_ai3_max}): {_val.warnings}")

    # Parse the installment
    title, stats_line, body_md = parse_installment(raw_installment)

    # #1385 (AC4): validate the parsed installment envelope against the guaranteed
    # schema — a $0, no-AI rigor gate that turns the fragile stat-line parse into a
    # caught error instead of a silently mis-rendered stat line. Non-blocking (the
    # week is human-reviewed in PREVIEW_MODE + privacy-gated downstream); the
    # chokepoint (bedrock_client.structured_output_config) is ready to make the shape
    # model-guaranteed once deploy-time prose parity is confirmed (see PR POST-MERGE).
    try:
        from content import chronicle_schema

        if _desk:
            # #4865: the desk's header is its own (weight only); validate it against the desk's envelope.
            _envelope = chronicle_schema.desk_installment_from_stats(title, chronicle_schema.stats_fields(stats_line), body_md)
            _schema_errs = chronicle_schema.validate_installment(_envelope, chronicle_schema.DESK_INSTALLMENT_SCHEMA)
        else:
            _envelope = chronicle_schema.installment_from_stats(title, chronicle_schema.parse_stats_line(stats_line), body_md)
            _schema_errs = chronicle_schema.validate_installment(_envelope)
        if _schema_errs:
            logger.warning(f"[#1385] installment envelope failed schema validation (non-blocking): {_schema_errs}")
    except Exception as _sc_e:  # noqa: BLE001 — validation is a safety net, never load-bearing
        logger.warning(f"[#1385] installment schema validation error (non-fatal): {_sc_e}")

    # BS-05: Compute confidence badge based on total journey data depth.
    # Henning: LOW (<14d data), MEDIUM (14-49d), HIGH (≥50d + sig + effect).
    # Chronicle draws on full journey history — use days-since-start as n.
    # #2221 / ADR-104-105: the default is UNKNOWN, not MEDIUM. When the BS-05 module is
    # absent or compute_confidence raises, nothing about this week's evidence has been
    # measured — storing "MEDIUM" asserted a middling verdict over a journey length no
    # one looked at. An unmeasurable confidence must read as unmeasured. (The badge HTML
    # was already "" on this path, so no reader-facing pill is invented either.)
    _conf_level = "UNKNOWN"
    _conf_badge_html = ""
    _conf_reason = ""
    if _HAS_CONFIDENCE:
        try:
            _journey_start = data.get("profile", {}).get("journey_start_date", EXPERIMENT_START_DATE)
            _journey_days = (datetime.strptime(_week_end, "%Y-%m-%d") - datetime.strptime(_journey_start, "%Y-%m-%d")).days
            _conf = compute_confidence(days_of_data=_journey_days)
            _conf_level = _conf.get("level") or "UNKNOWN"
            _conf_badge_html = _conf.get("badge_html", "")
            _conf_reason = _conf.get("reason", "")
            logger.info(f"BS-05 confidence: {_conf_level} ({_conf_reason})")
        except Exception as _ce:
            logger.warning(f"BS-05 confidence compute failed (non-fatal): {_ce}")

    logger.info(f'Title: "{title}"')

    # Convert to HTML
    body_html = markdown_to_html(body_md)

    # #2221: ">" is the blockquote marker; the following space is optional in markdown
    # (markdown_to_html and scripts/v4_build_journal.py match the same way). Requiring
    # "> " left an interview written as ">Park said..." un-flagged, so the site's
    # interview filter silently missed the week.
    #
    # Detect Board interview — a blockquote counts UNLESS it's Margaret's editor's note
    # (#548), which is also rendered as a blockquote but isn't an interview.
    has_board = any(line.strip().startswith(">") and "editor's note" not in line.strip().lower() for line in body_md.split("\n"))

    # Collect all installments for index pages (including the new one)
    date_str = _week_end
    all_installments: list = []
    try:
        # ADR-058: phase=pilot hidden by default.
        from experiment.phase_filter import with_phase_filter

        # #2254: this list is what publish_to_journal REGENERATES generated/journal/posts.json
        # from — wholesale, not merged with the existing manifest — and it is also what
        # derives every post's week-NN sequence. A single DynamoDB Query response is
        # capped at 1 MB of items scanned BEFORE the phase FilterExpression is applied,
        # so an un-paginated read silently drops the oldest installments once the archive
        # outgrows one page: the manifest rewrite would delete those posts from the public
        # listing AND renumber the survivors' URLs. Loop on LastEvaluatedKey.
        _query_kwargs = with_phase_filter(
            {
                "KeyConditionExpression": "pk = :pk AND begins_with(sk, :prefix)",
                "ExpressionAttributeValues": {":pk": f"USER#{USER_ID}#SOURCE#chronicle", ":prefix": "DATE#"},
                "ScanIndexForward": False,
            }
        )
        _pages = 0
        while True:
            resp = table.query(**_query_kwargs)
            all_installments.extend(d2f(i) for i in resp.get("Items", []))
            _pages += 1
            _lek = resp.get("LastEvaluatedKey")
            if not _lek or _pages >= _MAX_INSTALLMENT_PAGES:
                if _lek:
                    logger.warning(f"[#2254] installment query stopped at the {_MAX_INSTALLMENT_PAGES}-page cap — manifest may be short")
                break
            _query_kwargs = dict(_query_kwargs, ExclusiveStartKey=_lek)
        logger.info(f"[chronicle] read {len(all_installments)} installments across {_pages} page(s)")
    except Exception as e:
        logger.warning(f"Failed to query all installments: {e}")
        # #1803: sk must be set so chronicle_render.publish_to_journal's sk-based
        # "is this the post being published right now" match (ac753774) can find
        # this synthesized placeholder — otherwise the freshly-fetched cover image
        # never lands in this post's posts.json manifest entry.
        all_installments = [{"title": title, "week_number": week_num, "date": date_str, "sk": f"DATE#{date_str}"}]

    # Ensure new installment is in the list (not yet stored at this point)
    if not any(i.get("date") == date_str for i in all_installments):
        all_installments.insert(
            0,
            {
                "title": title,
                "week_number": week_num,
                "date": date_str,
                # #1803: same sk-identity requirement as the exception-fallback above.
                "sk": f"DATE#{date_str}",
                "stats_line": stats_line,
                "word_count": len(raw_installment.split()),
                "content_markdown": truncate_at_word(raw_installment, 300),  # #1224: excerpt-source preview, word boundary
                "has_board_interview": has_board,
            },
        )

    # The email footer points readers at the live chronicle archive (the /blog/ path
    # was retired — it 404'd, #969). The per-post journal URL is returned by
    # publish_to_journal below; the "full series" link is the archive listing.
    series_url = "https://averagejoematt.com/story/chronicle/"

    # ── Privacy gate (fail-closed) — never publish OR store a leaking installment.
    # Prompt rules are the first line; this deterministic gate is the guarantee.
    # Catches the truth-audit class: a real public figure named as a coach/source,
    # or a vice/substance named outright. A violation HOLDS the whole installment.
    try:
        privacy_guard.assert_clean(f"{title}\n{stats_line}\n{raw_installment}", context=f"chronicle week {week_num}")
    except privacy_guard.PrivacyViolation as e:
        logger.error(f"[privacy] BLOCKED chronicle week {week_num} — {e}")
        # #803: this used to be a silent no-op — nothing was ever written anywhere, so
        # the reader-facing "come back weekly" promise broke with zero trace beyond a
        # CloudWatch log line. Record a non-content marker so the site can say Week
        # {week_num} was attempted and withheld, instead of the numbering just skipping
        # ahead unexplained next time a clean draft ships.
        _set_chronicle_pending(
            week_num,
            "privacy_hold",
            f"Week {week_num}'s installment was generated but withheld before publishing — it didn't clear "
            "the platform's automatic safety check that keeps real people's names and private details out "
            "of the public write-up. No content was published or stored for this week.",
        )
        return {
            "statusCode": 200,
            "body": json.dumps({"status": "privacy_hold", "week": week_num, "violations": [t for _, t in e.violations]}),
        }

    # ── Story door (#4538, fail-closed) — the ONE shared reader-surface check, at the one point every writer passes
    # (the desk, the legacy writer, a reused cache): no cycle/reset/attempt count in the title, the stat line or the
    # body, and no off-record specifics. The desk's writers already rewrite against it; this is what holds the week
    # when a rewrite did not clear it, or when the writer was not the desk. Craft (#4545, owner ruling "b"): a residual
    # story_craft finding never holds the week for readers; it routes the week to the preview (_preview), never auto-published.
    _held, _preview, _craft = _store.publish_holds(
        week_num, title, stats_line, raw_installment, _desk, _dry, PREVIEW_MODE, _g=globals(), date_str=_week_end
    )
    if _held:
        return _held

    # ── #405: the per-chronicle share kit — machine-made from ALREADY-PUBLISHED fields
    # only (title, honest stats line, an excerpt of the prose, the canonical post URL).
    # Text/JSON only (the honest-stats OG card is drawn by the daily og sweep via the
    # #595 engine). The kit passes the same privacy gate the installment just cleared.
    share_kit = None
    share_kit_json = None
    share_kit_block = ""
    if _HAS_SHARE_KIT:
        try:
            _seq, _label, _canon = journal_post_ref(date_str, all_installments, week_num)
            share_kit = chronicle_share_kit.build_kit(
                title=title,
                stats_line=stats_line,
                label=_label,
                date_str=date_str,
                canonical_url=_canon,
                excerpt_source=body_md,
                week_number=week_num,
            )
            # Defense-in-depth: the kit only recombines already-gated fields, but re-assert.
            privacy_guard.assert_clean(share_kit.get("caption", ""), context=f"share kit week {week_num}")
            share_kit_json = json.dumps(share_kit)
            share_kit_block = chronicle_share_kit.kit_email_block(share_kit)
        except privacy_guard.PrivacyViolation as e:
            logger.error(f"[privacy] share kit blocked week {week_num} — {e}")
            share_kit = share_kit_json = None
            share_kit_block = ""
        except Exception as e:
            logger.warning(f"[#405] share kit build failed (non-fatal): {e}")
            share_kit = share_kit_json = None
            share_kit_block = ""

    # ── Phase 3: build Elena's "previously on" recap (grounded in published history
    # + this week being published). Fail-soft: a recap failure never blocks the
    # chronicle. Committed to RECAP#latest at publish time (now if non-preview, at
    # approve if preview) so it never runs ahead of the history it summarizes.
    recap = build_recap(
        data,
        new_installment_md=raw_installment,
        new_meta={"date": date_str, "week_number": week_num, "title": title},
    )
    draft_recap_json = json.dumps(recap, default=str) if recap else None

    if _dry:
        # #2221: the rehearsal exit. Everything above this line is pure computation —
        # every write in this handler lives in the two branches below and in the
        # email_log row after them, and none of them run.
        return _store.dry_run_response(
            week_num, date_str, title, stats_line, raw_installment, _conf_level, has_board, share_kit, recap, _preview, _g=globals()
        )

    if _preview:
        # ── FEAT-12: Build all HTML artifacts without publishing ─────────────
        logger.info("FEAT-12: PREVIEW_MODE — building draft artifacts")

        try:
            journal_post_key, journal_post_html, journal_posts_json = publish_to_journal(
                title,
                stats_line,
                body_html,
                week_num,
                date_str,
                all_installments,
                write_to_s3=False,
            )
        except Exception as e:
            logger.warning(f"FEAT-12: Failed to build journal artifacts: {e}")
            journal_post_key = journal_post_html = journal_posts_json = None

        draft_email_html = build_email_html(title, stats_line, body_html, week_num, date_str, series_url)

        approval_token = _secrets.token_hex(32)
        _stored = store_installment(
            date_str,
            week_num,
            title,
            stats_line,
            raw_installment,
            body_html,
            [],
            has_board,
            confidence_level=_conf_level,
            confidence_badge_html=_conf_badge_html,
            status="draft",
            approval_token=approval_token,
            draft_journal_post_html=journal_post_html,
            draft_journal_post_key=journal_post_key,
            draft_journal_posts_json=journal_posts_json,
            draft_email_html=draft_email_html,
            draft_recap_json=draft_recap_json,
            draft_share_kit_json=share_kit_json,
            allow_overwrite=bool(event.get("force")),
        )

        if _stored:
            _attach_desk_artifacts(date_str, _desk, _craft)  # + desk_craft_json / publish_hold=craft_hold (#4545) | legacy_hold (#6155)

        # #2254: the conditional put refused (a protected row raced in between the
        # idempotency read and this write). The approval_token was never persisted, so
        # mailing its approve link would hand Matthew a button that 403s — and the
        # preview itself would be a second, different draft for a week he may have
        # already approved. Stop here instead.
        if not _stored:
            logger.warning(f"[#2254] Week {week_num} draft NOT stored (protected row exists) — preview email suppressed")
            return {
                "statusCode": 200,
                "body": json.dumps(
                    {"status": "already_generated", "date": date_str, "week": week_num, "detail": "conditional put refused"}
                ),
            }

        _send_preview_email(title, week_num, date_str, approval_token, draft_email_html, share_kit_block, _fallback, _craft)
        _store.mark_awaiting_approval(week_num, _g=globals())  # #5520: the door names the waiting draft

    else:
        # ── Standard flow: publish immediately ───────────────────────────────
        store_installment(
            date_str,
            week_num,
            title,
            stats_line,
            raw_installment,
            body_html,
            [],
            has_board,
            confidence_level=_conf_level,
            confidence_badge_html=_conf_badge_html,
            allow_overwrite=bool(event.get("force")),
        )

        # This path publishes immediately → commit the recap now (fail-soft).
        if recap:
            _write_recap(recap, date_str)

        # #537: published now → update Elena's memory now (fail-soft).
        _invoke_elena_state_updater(date_str)

        try:
            journal_url = publish_to_journal(title, stats_line, body_html, week_num, date_str, all_installments)
            logger.info(f"[journal] Published: {journal_url}")
        except Exception as e:
            logger.warning(f"[journal] publish_to_journal failed (non-fatal): {e}")

        # #1384 write-side: this path publishes without ever passing through
        # chronicle-approve, so it carries its own recall index call — otherwise a
        # directly-published week would be the one shape of week the corpus never sees.
        try:
            from ai import recall_indexer

            logger.info(
                "[recall] index %s: %s",
                date_str,
                recall_indexer.index_chronicle_installment(table, f"USER#{USER_ID}#SOURCE#chronicle", date_str),
            )
        except Exception as e:  # noqa: BLE001 — recall indexing is never load-bearing
            logger.warning(f"[recall] indexing failed (non-fatal): {e}")

        # #405: write the share kit to its stable generated location (immediate-publish path).
        if share_kit and share_kit_json:
            try:
                s3.put_object(
                    Bucket=S3_BUCKET,
                    Key=chronicle_share_kit.kit_s3_key(share_kit["canonical_url"]),
                    Body=share_kit_json.encode("utf-8"),
                    ContentType="application/json",
                    CacheControl="max-age=300",
                )
                logger.info("[#405] share kit written to %s", chronicle_share_kit.kit_s3_key(share_kit["canonical_url"]))
            except Exception as e:
                logger.warning(f"[#405] share kit S3 write failed (non-fatal): {e}")

        email_html = build_email_html(title, stats_line, body_html, week_num, date_str, series_url)
        if share_kit_block:
            email_html = email_html.replace("</body>", share_kit_block + "</body>", 1)
        subject = f'The Measured Life — Week {week_num}: "{title}"'
        ses.send_email(
            FromEmailAddress=SENDER,
            Destination={"ToAddresses": [RECIPIENT]},
            Content={
                "Simple": {
                    "Subject": {"Data": subject, "Charset": "UTF-8"},
                    "Body": {"Html": {"Data": email_html, "Charset": "UTF-8"}},
                }
            },
        )
        logger.info(f"Email sent: {subject}")

    # IC-15: Persist chronicle as narrative insight
    if _HAS_INSIGHT_WRITER:
        try:
            insight_writer.write_insight(
                digest_type="chronicle",
                insight_type="observation",
                text=f"Week {week_num}: {title}. {raw_installment[:600]}",
                pillars=insight_writer._extract_pillars_from_text(raw_installment[:500]),
                tags=["chronicle", "narrative", f"week_{week_num}"],
                confidence="high",
                actionable=False,
                date=data["dates"]["end"],
            )
            logger.info("IC-15: chronicle insight persisted")
        except Exception as e:
            logger.warning(f"IC-15 failed: {e}")

    # #2254: the status page's "Wednesday chronicle — last sent" reads nothing but the
    # PRESENCE of a row in email_log#wednesday_chronicle (site_api_status._last_sync
    # projects `sk` only, and _uptime_90d likewise), so a "preview_sent" status field on
    # the same partition would be invisible — the row itself IS the claim. In
    # PREVIEW_MODE nothing was sent to a reader: a draft was stored and an approval email
    # raised to Matthew. That belongs in its own partition. The real subscriber delivery
    # is logged by chronicle-email-sender when a send actually succeeds.
    record_email_send(table, "wednesday_chronicle_preview" if _preview else "wednesday_chronicle")
    if _preview:
        return {
            "statusCode": 200,
            "body": f"Chronicle Week {week_num} draft stored — preview email sent to {RECIPIENT}",
        }
    return {
        "statusCode": 200,
        "body": f'Chronicle Week {week_num} published: "{title}" ({len(raw_installment.split())} words)',
    }


def _attach_desk_artifacts(date_str, desk, legacy_findings=()):
    """#4535/#4536: the desk's budget, episode script and the ledger this week leaves ride on the chronicle row — the
    Panel renders the episode from it, and the approve path commits the ledger on publish.

    #4545 (owner ruling "b"): the residual craft verdict rides along as ``desk_craft_json``; when it is non-empty the row
    also carries ``publish_hold = "craft_hold"`` -- approval metadata the 48 h sweep refuses (content/autopublish_audit),
    never a reader-facing marker. Only the owner's approve click publishes that draft.

    #6155: no desk (the legacy writer drafted the week) -> the legacy door's findings ride on the row instead."""
    if desk is None:
        return _store.attach_legacy_audit(date_str, legacy_findings, _g=globals())
    try:
        craft = list(desk.get("craft_findings") or [])
        values = {
            ":b": json.dumps(desk["budget"], default=str),
            ":e": json.dumps(desk["episode"], default=str),
            ":l": json.dumps(desk["ledger"], default=str),
            ":f": json.dumps(desk["findings"], default=str),
            ":c": json.dumps(craft, default=str),
            ":ph": "experiment",
        }
        expr = "SET desk_budget_json = :b, desk_episode_json = :e, desk_ledger_json = :l, desk_findings_json = :f, desk_craft_json = :c"
        if desk.get("editor") is not None:  # #6179 (STORY_EDITOR=on only): what the editor did, round by round, and its cost
            values[":ed"] = json.dumps(desk["editor"], default=str)
            expr += ", desk_editor_json = :ed"
        expr += ", #p = if_not_exists(#p, :ph)"
        if craft:
            values[":h"] = "craft_hold"
            expr += ", publish_hold = :h"
        else:
            expr += " REMOVE publish_hold"  # a forced re-run that cleared the craft gate must not inherit the old hold
        table.update_item(
            Key={"pk": f"USER#{USER_ID}#SOURCE#chronicle", "sk": f"DATE#{date_str}"},
            UpdateExpression=expr,
            ExpressionAttributeNames={"#p": "phase"},
            ExpressionAttributeValues=values,
        )
    except Exception as e:  # noqa: BLE001 — the post still publishes; the Panel falls back to its own writer
        logger.error(f"[#4535] could not attach desk artifacts to {date_str}: {e}")


def _send_story_questions(event):
    """#4546: Monday — the week's gap questions by email, Reply-To the SES inbound address. Never blocks anything."""
    import datetime as _dtm

    from common import outbound_trial
    from common.pacific_time import pacific_today

    # #6176 item 4 (outbound trial, #6174): no reply to these has been stored since February, so they pause until the
    # reply path is proven. Nothing else reads the generated questions (only the reply parser does), so generation
    # pauses too: no dossier read, no model call, no marker. story_season_qa reads the same switch.
    if outbound_trial.is_on(outbound_trial.STORY_QUESTIONS_PAUSED):
        rec = outbound_trial.suppressed(outbound_trial.STORY_QUESTIONS_PAUSED, "wednesday-chronicle#StoryQuestionsMonday", log=logger.info)
        return {"statusCode": 200, "body": json.dumps({"status": "suppressed", **rec})}
    from content import story_dossier, story_ledger, story_questions

    today = _dtm.datetime.strptime(pacific_today(), "%Y-%m-%d").date()  # pacific_today() is a YYYY-MM-DD string
    upcoming = story_dossier.week_containing(today.isoformat())  # #4539: the one definition the dead-man shares
    if upcoming is None:
        return {"statusCode": 200, "body": json.dumps({"status": "no_week"})}
    n = upcoming["week"]
    marker = {"pk": f"USER#{USER_ID}#SOURCE#chronicle", "sk": f"STORYQ#W{n:03d}"}
    if not event.get("force") and table.get_item(Key=marker).get("Item"):
        return {"statusCode": 200, "body": json.dumps({"status": "already_sent", "week": n})}
    so_far = {**upcoming, "end": min(upcoming["end"], (today - timedelta(days=1)).isoformat())}
    dossier, _ = story_dossier.week_dossier(table, so_far)
    ledger = story_ledger.latest_visible(table, f"USER#{USER_ID}#SOURCE#chronicle", upcoming["end"])
    escalated = story_questions.escalated_questions(ledger)  # #4546: a coach ask carried CARRIED_MAX_WEEKS weeks goes to him first
    questions = story_questions.compose(escalated, story_questions.generate(dossier, story_ledger.ledger_for_prompt(ledger, n)))
    if event.get("dry_run"):
        return {
            "statusCode": 200,
            "body": json.dumps({"status": "dry_run", "week": n, "questions": questions, "escalated": len(escalated)}),
        }
    resp = story_questions.send(ses, week=n, questions=questions, to=RECIPIENT, sender=SENDER)
    logger.info(
        f"[#4546] story questions sent for week {n}: {len(questions)} question(s), {len(escalated)} escalated ask(s), {resp.get('MessageId', '')}"
    )
    from experiment.phase_taxonomy import experiment_stamp_for

    table.put_item(
        Item={
            **marker,
            "questions_json": json.dumps(questions),
            "sent_at": datetime.now(timezone.utc).isoformat(),
            "message_id": resp.get("MessageId", ""),
            **experiment_stamp_for(marker["pk"], marker["sk"]),  # #3599: the class-gated write-time stamp
        }
    )
    return {"statusCode": 200, "body": json.dumps({"status": "sent", "week": n, "questions": len(questions)})}


#: #4584: the Tuesday question's send-once marker, beside Monday's ``STORYQ#W<n>`` in the chronicle partition. A
#: suffix, not a new prefix, so story_season_qa's Monday check (an EXACT sk match) never reads it as Monday's send.
TUESDAY_MARKER_SUFFIX = "#TUE"


def _send_tuesday_question(event):
    """#4584: Tuesday evening PT — ONE fixed question by email, on the Story Desk's channel and routing token, so his
    reply lands verbatim in the owner-words store (and the week's STORYQA row) before Wednesday's edition. No model
    call, no dossier read. Never blocks anything; sends once per week (the marker), ``force`` re-sends."""
    import datetime as _dtm

    from common import outbound_trial
    from common.pacific_time import pacific_today
    from content import story_dossier, story_questions

    if outbound_trial.is_on(outbound_trial.STORY_QUESTIONS_PAUSED):  # #6176 item 4 / #6174 — see _send_story_questions
        rec = outbound_trial.suppressed(
            outbound_trial.STORY_QUESTIONS_PAUSED, "wednesday-chronicle#OwnerWordsQuestionTuesday", log=logger.info
        )
        return {"statusCode": 200, "body": json.dumps({"status": "suppressed", **rec})}

    today = _dtm.datetime.strptime(pacific_today(), "%Y-%m-%d").date()
    week = story_dossier.week_containing(today.isoformat())
    if week is None:
        return {"statusCode": 200, "body": json.dumps({"status": "no_week"})}
    n = week["week"]
    marker = {"pk": f"USER#{USER_ID}#SOURCE#chronicle", "sk": f"STORYQ#W{n:03d}{TUESDAY_MARKER_SUFFIX}"}
    if not event.get("force") and table.get_item(Key=marker).get("Item"):
        return {"statusCode": 200, "body": json.dumps({"status": "already_sent", "week": n})}
    question = story_questions.tuesday_question(n)
    if event.get("dry_run"):
        return {"statusCode": 200, "body": json.dumps({"status": "dry_run", "week": n, "question": question})}
    resp = story_questions.send_tuesday(ses, week=n, question=question, to=RECIPIENT, sender=SENDER)
    logger.info(f"[#4584] owner-words question sent for week {n}: {resp.get('MessageId', '')}")  # #6176: the send's count line
    from experiment.phase_taxonomy import experiment_stamp_for

    table.put_item(
        Item={
            **marker,
            "questions_json": json.dumps([question]),
            "sent_at": datetime.now(timezone.utc).isoformat(),
            "message_id": resp.get("MessageId", ""),
            **experiment_stamp_for(marker["pk"], marker["sk"]),  # #3599: the class-gated write-time stamp
        }
    )
    return {"statusCode": 200, "body": json.dumps({"status": "sent", "week": n, "questions": 1})}


def lambda_handler(event: dict, context) -> dict:
    """#2669: timeout-watchdog wrapper (common.timeout_watchdog) — _handler_core is the real flow."""
    from common.timeout_watchdog import arm, disarm

    timer = arm(
        context,
        metric_name="ChronicleTimeoutImminent",
        detail="the run dies mid-tail; if a '[#2669] generation cached' line appears above, the retry is free",
    )
    try:
        if isinstance(event, dict) and event.get("story_questions"):
            return _send_story_questions(event)  # #4546: Monday's optional questions — never touches the week's chronicle
        if isinstance(event, dict) and event.get("tuesday_question"):
            return _send_tuesday_question(event)  # #4584: Tuesday's one question — never touches the week's chronicle
        return _handler_core(event, context)
    finally:
        disarm(timer)
