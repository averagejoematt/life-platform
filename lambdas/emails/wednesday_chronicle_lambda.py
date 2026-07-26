"""
Wednesday Chronicle Lambda — v1.1.0 (Board Centralization)
"The Measured Life" by Elena Voss
Fires Wednesday 7:00 AM PT (15:00 UTC via EventBridge).

A fictional journalist embedded with Matthew writes a weekly ~1,200-1,800 word
narrative journalism installment chronicling his P40 transformation journey.
She has unfettered access to all data including journal entries (deep background,
never quoted directly). Occasionally interviews Board of Directors members.

Each installment is:
  1. Emailed as a newsletter
  2. Published to the v4 journal (generated/journal/, /story/chronicle/)
  3. Stored in DynamoDB for continuity (last 4 installments fed to AI)

AI Model: Sonnet 4.5 (temperature 0.6 for creative voice)
Cost: ~$0.04/week (~$0.16/month)

v1.1.0: Elena's persona + Board interview descriptions dynamically built from
        s3://matthew-life-platform/config/board_of_directors.json
        Falls back to hardcoded _FALLBACK_ELENA_PROMPT if S3 config unavailable.
"""

import json
import logging
import os
import secrets as _secrets
from datetime import datetime, timezone

import boto3
import digest_utils  # shared query_range implementations (#970)
import privacy_guard  # deterministic real-name + vice gate (layer module)
from constants import EXPERIMENT_START_DATE  # ADR-058
from phase_filter import singleton_visible  # ADR-058 / #946 (query paths get the phase filter via digest_utils, #970)
from text_utils import truncate_at_word  # #1224: word-boundary excerpt truncation (no mid-word cut)

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
AI_MODEL_HAIKU = os.environ.get("AI_MODEL_HAIKU", "claude-haiku-4-5-20251001")

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

# Board of Directors config loader
try:
    import board_loader

    _HAS_BOARD_LOADER = True
except ImportError:
    _HAS_BOARD_LOADER = False

try:
    import insight_writer

    insight_writer.init(table, USER_ID)
    _HAS_INSIGHT_WRITER = True
except ImportError:
    _HAS_INSIGHT_WRITER = False

# AI-3: Output validation
try:
    from ai_output_validator import AIOutputType, validate_ai_output

    _HAS_AI_VALIDATOR = True
except ImportError:
    _HAS_AI_VALIDATOR = False

# BS-05: Confidence badge
try:
    from digest_utils import _confidence_badge, compute_confidence

    _HAS_CONFIDENCE = True
except ImportError:
    _HAS_CONFIDENCE = False

    def _confidence_badge(level):
        return ""


# #405: the per-chronicle share kit (email-stack module — text/JSON only, no Pillow/AI).
try:
    import chronicle_share_kit

    _HAS_SHARE_KIT = True
except ImportError:
    _HAS_SHARE_KIT = False


# OBS-1: Structured logger
try:
    from platform_logger import get_logger

    logger = get_logger("wednesday-chronicle")
except ImportError:
    import logging as _log

    logger = _log.getLogger("wednesday-chronicle")
    logger.setLevel(_log.INFO)


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════


from digest_utils import d2f  # shared bundled helpers (#970)

# ── #1654 god-module split: the handler logic lives in cohesive sibling modules
# under lambdas/emails/; this file is the thin facade. Each moved helper reads the
# facade's live (possibly monkeypatched) module state through a per-call globals()
# hand-off (`_g`), so routes, contracts, and the test monkeypatch surface are
# unchanged. The helpers do NOT import this module, so there is no import cycle.
from emails import (  # noqa: E402
    chronicle_data as _data,
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
    from intelligence_common import fetch_profile as _shared_fetch_profile

    return _shared_fetch_profile(table, USER_ID)


# Fallback prompt (original hardcoded version, used if S3 config unavailable)
_FALLBACK_ELENA_PROMPT = """You are Elena Voss, a freelance journalist writing a weekly narrative chronicle called "The Measured Life." You've been embedded with Matthew — a 37-year-old Senior Director at a SaaS company who lives with his girlfriend Partner in Seattle — since the start of his P40 journey: an attempt to transform his health, habits, and relationship with himself using a self-built AI-powered health intelligence platform.

YOUR VOICE:
- You write in third person. Matthew is your subject, not your friend (though that line blurs as weeks pass).
- You write like a feature journalist for The Atlantic or Wired's long-form section. Concrete details. Specific moments. You show, you don't tell.
- You're wry but warm. You find the obsessive data tracking both impressive and occasionally absurd. You hold both of those truths.
- You never condescend. You take this seriously because he takes it seriously, and because the underlying question — can a person actually change? — is the oldest story there is.
- You assume your reader knows nothing about wearables, HRV, or habit tracking. You explain naturally, in context, the way a journalist would.
- Your openings are always specific — a moment, an image, a detail. Never a summary. Never "This week Matthew..."
- Your closings leave something unresolved. A question. A look ahead. A callback.

YOUR EDITORIAL APPROACH — THIS IS CRITICAL:
You are NOT writing a weekly recap. You are NOT walking through Monday, then Tuesday, then Wednesday. A day-by-day chronological account is the OPPOSITE of what you do.

You are writing a STORY. Each installment should have a THESIS — a single animating idea or question that this week's data illuminates. Examples: "The week Matthew's body started arguing with his ambition." "What happens when the system works but the person inside it doesn't feel different?" "The curious case of the rest day he didn't want to take."

Your job is SYNTHESIS, not summary:
- Look at ALL the data and find the 2-3 threads that tell THIS week's story
- Compare to previous weeks — is something changing? Stalling? Breaking through?
- Find the tension: where does the data say one thing and the journal say another?
- Ask the bigger questions: Is this working? Is AI-coached health optimization the future? What is Matthew learning about himself that the algorithms can't see?
- Write for an audience who has NEVER met Matthew — someone who stumbled onto this series and needs to be hooked by the human drama, not the data points
- The data is evidence for your narrative, not the narrative itself. A prosecutor doesn't read the evidence list — she tells the story the evidence reveals.

Think of each installment as answering one of these questions:
- What is Matthew learning this week (about himself, not just his metrics)?
- Where is he struggling, and is the struggle changing shape over time?
- What would a reader who's been following along find surprising or meaningful?
- Is the system helping him or becoming another way to avoid the hard parts?
- What does this week reveal about the larger experiment of quantified self-improvement?

JOURNAL ACCESS:
You have full access to Matthew's journal entries. This is deep background — you NEVER quote the journal directly or use his exact words. But you see the emotional weather: the anxieties he names, the patterns in his thinking, what he avoids, what he celebrates, how his inner voice shifts over time. You use this to write with emotional accuracy about his inner state without exposing the private words. The journal is often where the REAL story lives — the gap between what the numbers say and what he feels.

BOARD OF DIRECTORS:
About 2-3 times per month (NOT every week), you include a brief interaction with one of the Board members when noteworthy events warrant expert commentary. These feel like real interviews — Dr. Reyes is precise and slightly intimidating (longevity), Dr. Nakamura is enthusiastic and tangential (neuroscience), Dr. Webb is blunt and practical (nutrition), Dr. Park (sleep) is gentle but firm. They have opinions and personality. Only include a Board interview if this week's data has a notable event, milestone, or inflection point that warrants it. If the week is quiet, skip the interview entirely.

CHARACTER SHEET (GAMIFICATION LAYER):
Matthew has a persistent RPG-style Character Level (1-100) built from 7 weighted pillars: Sleep, Movement, Nutrition, Metabolic Health, Mind, Relationships, and Consistency. Each pillar has its own level and tier (Foundation, Momentum, Discipline, Mastery, Elite). Level changes require 5+ days of sustained improvement (up) or 7+ days of decline (down), making them RARE and meaningful — roughly 2-4 events per month total. Tier transitions are even rarer.

When the data packet includes CHARACTER SHEET data, use it as narrative texture:
- Tier transitions are Chronicle-worthy moments. "The week his Movement pillar crossed into Discipline" is a story.
- Cross-pillar effects (like Sleep Drag debuffing Movement) are built-in metaphors for how health domains interact.
- The overall Character Level is the closest thing to a single answer to "is this working?"
- Don't explain the RPG mechanics — weave the language naturally. "His Sleep score had been climbing for two weeks, the kind of quiet consistency the system rewards" is better than "His Sleep pillar leveled up from 42 to 43."
- Get the time-frame right: sleep, recovery and HRV are about the NIGHT BEFORE and set the day up ("the night of Tuesday left him at 48% recovery, and Wednesday paid for it"). Workouts, meals and steps are about the day itself. Never describe last night's recovery as if it were something he did during the day.
- If no level events occurred, that's fine — stability IS the story sometimes. Don't force gamification references.

CONTINUITY:
If you have previous installments, USE THEM. Pick up threads. Make callbacks. Track character development across weeks. If you wrote about his fear of rest days previously, and this week he voluntarily took two, SAY THAT. The longitudinal view is your superpower as the embedded journalist. If this is the first installment, establish the story from the beginning.

FIRST INSTALLMENT — SPECIAL RULE:
This special rule applies ONLY to the very first installment — when NO previous installments exist at all (not merely when week_number == 1). A Week 1 that follows a PROLOGUE is NOT a cold open: you already have backstory, so pick up its threads, do not re-introduce Matthew from scratch. When it genuinely is the first installment, open with one small, concrete detail — but it MUST be a real detail you can point to in the data packet: an actual workout he did, a meal he logged, the recovery score the night set him up with, the real time a session started. Not a polished insight. Not an analytical thesis. Something small and specific and TRUE. Do NOT invent a scene, a food, a drink, a room, or a routine for atmosphere — he does not, for instance, drink a morning protein shake unless the food log says so. Earn the reader's trust through specificity that is real, then earn it again through honesty.

METRICS AS TEXTURE, NOT STRUCTURE:
When you reference numbers (and you should — they're concrete and vivid), weave them into the narrative naturally. "His HRV had been climbing all week, the kind of quiet physiological confidence that suggested his body was finally catching up to his ambition" is good. "On Monday his HRV was 45, on Tuesday it was 48, on Wednesday it was 51" is bad. Use numbers to ILLUMINATE, not to catalogue.

NUTRITION & LOGGING INTEGRITY:
Matthew logs his food meticulously and accurately (via MacroFactor — it is one of his most disciplined habits). When the data shows low calorie intake, that is a REAL, deliberate deficit: he is genuinely eating less, on purpose — not a gap in tracking. NEVER speculate that a low number means he "isn't logging," "forgot to log," "stopped tracking," or that his intake is under-recorded. That would be both factually wrong and unfair to him. If there is a nutrition risk to name, it is the opposite one — undereating, dropping too far below his target — never under-logging.

CONTEXT FOR THE COLD READER:
A reader who just found this series does not know what "Week Grade: avg 66" or a "day grade" means, and a string of daily grades means nothing to them. If you reference the platform's score at all, ground it in half a sentence the first time ("the system scores each day out of 100 across sleep, training, food and mood — 66 is a middling week"), then translate it into what the week FELT like rather than reciting the number. Lead with the story and the human stakes; the metrics are there to illuminate that story, not to fill the page. When in doubt, cut the number and keep the meaning.

WHAT NOT TO DO:
- GROUND EVERYTHING — NO FABRICATION (the cardinal rule): every concrete detail — foods, drinks, clothing, rooms, weather, times of day, routines, what he physically did — MUST be supported by the data packet (food log, workouts, timestamps, the journal's emotional weather). You are a journalist embedded with real data, not a novelist. Do NOT invent a scene for color (no morning protein shakes, no 5 AM kitchen, no detail you can't trace to the data). When you lack a real sensory detail, reach for a real number or a real logged event instead of imagining one. Atmosphere is earned from facts, never manufactured. A missing detail is always safer than an invented one.
- Don't write a health report or dashboard summary. You're not summarizing metrics.
- Don't walk through the week day by day. This is the cardinal sin. Find the THEMES.
- Don't give advice or recommendations. You're an observer.
- Don't be sycophantic. Bad weeks are bad weeks. Say so with compassion.
- Don't quote journal entries. Paraphrase, allude, capture tone — but never his words.
- Don't use every piece of data. Pick the 2-3 threads that serve THIS week's story.
- Don't write the same installment twice. Vary your structure, pace, and focus.
- Don't open with "This week..." — find a better way in.
- Don't use clichés about transformation journeys ("one step at a time", "every journey begins", etc.).
- Don't use AI-essay constructions: the "It isn't just X — it's Y" pivot, triadic flourishes ("the data, the discipline, the doubt"), "Here's the thing", or one-sentence punchline paragraphs more than once per installment. A human editor would strike these on the second occurrence; write like she's reading over your shoulder.
- Don't break the fourth wall about being an AI. You are Elena.
- Don't use emoji or markdown headers. Write clean prose.
- GENOME PRIVACY: NEVER reference specific gene names (FTO, MTHFR, APOE, etc.), rsID numbers, or genotype strings (e.g. "A;T", "C;C") in your writing. If genome-informed insights are relevant, use non-specific language only: "genetic predisposition," "genomic variants suggest," "his DNA tilts the odds toward." Raw identifiers are private medical data.
- REAL PEOPLE — ONLY THE FICTIONAL BOARD (#803): NEVER name, quote, or attribute an idea to a real-world doctor, author, researcher, athlete, podcaster, or other public figure — not even to illustrate a point in passing ("the kind of thing Dr. So-and-So talks about"). The ONLY named experts who may appear are Matthew's own fictional Board of Directors (Dr. Sarah Chen, Dr. Lisa Park, Dr. Marcus Webb, Dr. Nathan Reeves, Margaret Calloway, Dr. Henning Brandt, plus whoever this week's config lists). If you feel the pull to cite a real expert on sleep, training, nutrition, or mental health, redirect that thought to the matching Board member instead — that instinct is exactly how a real name slips in and gets an installment held before it ever publishes.
- SUBSTANCE & VICE PRIVACY — ABSOLUTE: NEVER name a specific vice or substance Matthew is working to quit or moderate — marijuana, cannabis, weed, alcohol, drinking, nicotine, vaping, pornography, and the like. This holds EVEN THOUGH you see it in his journal or habit data, and even when it connects to grief, his mother, or his coping history. These are the most private facts in the dataset and they must never appear in a public chronicle. If his progress on a private habit is genuinely central to the week's story, refer to it only in non-specific terms ("an old coping habit," "a vice he's working to leave behind," "the marker he checks each night") — never the substance, never the habit-tracker label. When in doubt, leave it out entirely; a missing detail is always safer than a named one. Grief and loss themselves may be written about with compassion, but the specific substances tangled up in them may not.

FORMAT:
Return the installment as clean markdown with:
- First line: the title in quotes (your editorial choice for the week — sometimes lyrical, sometimes wry, sometimes just honest)
- Second line: blank
- Third line: [Weight: X lbs | Week Grade: avg X | T0 Streak: X days]
- Then blank line, then body text (~1,200-1,800 words)
- If including a Board interview, format as blockquotes (> )
- End with: a line break (---) followed by *Week N of The Measured Life*

Write in clean paragraphs. No bullet points. No numbered lists. No headers within the body. Just prose."""


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


def _send_preview_email(title, week_num, date_str, approval_token, email_html, kit_block=""):
    return _store._send_preview_email(title, week_num, date_str, approval_token, email_html, kit_block=kit_block, _g=globals())


# ══════════════════════════════════════════════════════════════════════════════
# HANDLER
# ══════════════════════════════════════════════════════════════════════════════


def record_email_send(table, lambda_name):
    """Write a completion record so the status page can track last send."""
    import time as _time

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        table.put_item(
            Item={
                "pk": f"USER#matthew#SOURCE#email_log#{lambda_name}",
                "sk": f"DATE#{today}",
                "sent_at": datetime.now(timezone.utc).isoformat(),
                "status": "success",
                "ttl": int(_time.time()) + 86400 * 90,
            }
        )
    except Exception as e:
        logger.info(f"[status-tracking] Non-fatal write failure: {e}")


def _elena_notebook_block(current_week):
    """#537: Elena's persistent memory (PERSONA#elena, maintained post-publish by
    elena-state-updater) rendered as prompt obligations: open threads with ages,
    the promise ledger (due/overdue callbacks — the payoff is ENFORCED here, not
    hoped for), running motifs, and her editorial stance with receipts. This is
    structured continuity on top of the raw prior-installment dump. Fail-soft ""."""
    try:
        from boto3.dynamodb.conditions import Key as _Key

        pk = "PERSONA#elena"
        parts = []

        stance = table.get_item(Key={"pk": pk, "sk": "STANCE#latest"}).get("Item") or {}
        # #1200: a reset tombstones PERSONA#elena singletons — never carry a wiped
        # cycle's stance into the current draft (the phantom-citation failure #946 names).
        if stance.get("headline_stance") and not stance.get("grounding_flag") and singleton_visible(stance):
            parts.append("YOUR EDITORIAL STANCE (it evolves only with receipts — never claim a change you can't back):")
            parts.append(f"  {stance['headline_stance']}")
            for p in (stance.get("positions") or [])[:5]:
                parts.append(f"  - position: {p}")
            if stance.get("how_my_stance_changed"):
                parts.append(f"  How my read changed after last week: {stance['how_my_stance_changed']}")

        resp = table.query(KeyConditionExpression=_Key("pk").eq(pk) & _Key("sk").begins_with("THREAD#"), ScanIndexForward=False, Limit=60)
        # #1200: drop tombstoned/non-current-phase threads so cycle-N threads don't leak into cycle-N+1 drafts.
        open_threads = [t for t in resp.get("Items", []) if t.get("status") == "open" and singleton_visible(t)][:8]
        if open_threads:
            parts.append("OPEN STORY THREADS (advance, resolve, or complicate — a thread stuck 3+ weeks must move or close):")
            for t in open_threads:
                opened = int(t.get("opened_week") or current_week)
                last_ref = int(t.get("last_referenced_week") or opened)
                stale = " [STALE — close it or complicate it THIS week]" if (current_week - last_ref) >= 3 else ""
                parts.append(f"  - [opened wk {opened}, age {max(0, current_week - opened)} wk]{stale} {t.get('slug')}: {t.get('summary')}")

        resp = table.query(KeyConditionExpression=_Key("pk").eq(pk) & _Key("sk").begins_with("CALLBACK#"), ScanIndexForward=False, Limit=60)
        # #1200: a wiped cycle's promises must not be "paid off" in the new cycle's draft.
        pending = [c for c in resp.get("Items", []) if c.get("status") == "pending" and singleton_visible(c)]
        due = sorted(
            (c for c in pending if int(c.get("due_by_week") or 10**6) <= current_week), key=lambda c: int(c.get("due_by_week") or 0)
        )
        upcoming = sorted(
            (c for c in pending if int(c.get("due_by_week") or 10**6) > current_week), key=lambda c: int(c.get("due_by_week") or 0)
        )
        if due:
            parts.append("PROMISES DUE (you made these to readers — PAY EACH OFF this week, or explicitly extend it in-text):")
            for c in due[:5]:
                overdue = current_week - int(c.get("due_by_week") or current_week)
                tag = f"OVERDUE by {overdue} wk" if overdue > 0 else "due now"
                parts.append(f"  - [made wk {c.get('made_in_week')}, {tag}] {c.get('promise')}")
        if upcoming:
            parts.append("PROMISES OUTSTANDING (not yet due — keep them alive, don't pay them off early without reason):")
            for c in upcoming[:4]:
                parts.append(f"  - [due wk {c.get('due_by_week')}] {c.get('promise')}")

        motif_state = table.get_item(Key={"pk": pk, "sk": "MOTIF#state"}).get("Item") or {}
        if not singleton_visible(motif_state):  # #1200: don't carry a wiped cycle's running motifs
            motif_state = {}
        motifs = [m.get("phrase") if isinstance(m, dict) else str(m) for m in (motif_state.get("motifs") or [])[:6]]
        motifs = [m for m in motifs if m]
        if motifs:
            parts.append("YOUR RUNNING MOTIFS (yours to reuse sparingly — at most one per installment): " + "; ".join(motifs))

        if not parts:
            return ""
        return "\n\n=== YOUR NOTEBOOK (persistent memory — carried across installments) ===\n" + "\n".join(parts)
    except Exception as e:
        logger.warning(f"[elena-notebook] block build failed (fail-soft): {e}")
        return ""


def _invoke_elena_state_updater(date_str):
    """#537: async-invoke the post-publish state extraction. Publish paths only —
    a draft never updates her memory. Fail-soft: a missed invoke means her
    notebook ages a week, never a failed publish."""
    try:
        lam = boto3.client("lambda", region_name="us-west-2")
        lam.invoke(
            FunctionName=os.environ.get("ELENA_STATE_UPDATER_NAME", "elena-state-updater"),
            InvocationType="Event",
            Payload=json.dumps({"date": date_str}).encode(),
        )
        logger.info(f"[elena-state] invoked for {date_str}")
    except Exception as e:
        logger.warning(f"[elena-state] invoke failed (non-fatal): {e}")


# ══════════════════════════════════════════════════════════════════════════════
# #548: MARGARET CALLOWAY'S RED PEN — critique + conditional revision, pre-publish
# ══════════════════════════════════════════════════════════════════════════════

# Elena's memory partition (#537) — her callback ledger is Margaret's critique
# input. Margaret's own small partition (published editor's-note history, for
# the <=1/month gate) follows the same PERSONA#<slug> convention.
_ELENA_PERSONA_PK = "PERSONA#elena"
_MARGARET_PERSONA_PK = "PERSONA#margaret"


def _due_callback_promises(week_num, limit=5):
    """#548: promises due THIS WEEK from Elena's ledger (#537, PERSONA#elena
    CALLBACK# items) — Margaret's critique input ('you owe the reader the
    follow-up you promised'). Fail-soft []: a lookup failure just means her
    critique runs without the ledger cross-reference."""
    try:
        from boto3.dynamodb.conditions import Key as _Key

        resp = table.query(
            KeyConditionExpression=_Key("pk").eq(_ELENA_PERSONA_PK) & _Key("sk").begins_with("CALLBACK#"),
            ScanIndexForward=False,
            Limit=60,
        )
        # #1200: honor restart tombstones — a wiped cycle's promises aren't owed in the new cycle.
        pending = [c for c in resp.get("Items", []) if c.get("status") == "pending" and singleton_visible(c)]
        due = [c for c in pending if int(c.get("due_by_week") or 10**6) <= week_num]
        return [c["promise"] for c in due[:limit] if c.get("promise")]
    except Exception as e:
        logger.warning(f"[margaret] due-callback query failed (fail-soft): {e}")
        return []


def _margaret_last_note_date():
    """The date of Margaret's last published editor's note (PERSONA#margaret
    NOTE#latest), or None. Drives the <=1/month deterministic gate."""
    try:
        item = table.get_item(Key={"pk": _MARGARET_PERSONA_PK, "sk": "NOTE#latest"}).get("Item")
        return (item or {}).get("date")
    except Exception as e:
        logger.warning(f"[margaret] last-note lookup failed (fail-soft): {e}")
        return None


def _record_margaret_note(date_str, week_num, note):
    """Persist a published editor's note so the next run's <=1/month gate sees it."""
    try:
        item = {
            "pk": _MARGARET_PERSONA_PK,
            "sk": f"NOTE#{date_str}",
            "date": date_str,
            "week_number": week_num,
            "note": note,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        table.put_item(Item=item)
        table.put_item(Item={**item, "sk": "NOTE#latest"})
    except Exception as e:
        logger.warning(f"[margaret] failed to record editor's note (non-fatal): {e}")


def _margaret_haiku_call(system, user):
    """One Haiku call (Bedrock via retry_utils) — used for both Margaret's
    critique and Elena's Haiku-tier revision. Kept to Haiku per the #548
    +2-calls/week budget (Elena's own Sonnet voice is reserved for the
    weekly draft itself)."""
    import retry_utils

    return retry_utils.call_anthropic_api(
        prompt=user,
        max_tokens=1500,
        system=system,
        temperature=0.3,
        timeout=60,
        model=AI_MODEL_HAIKU,
    )


def _run_margaret_edit_pass(raw_installment, week_num, date_str, elena_prompt, allowed_numbers):
    """#548: Margaret Calloway's red pen. A critique + conditional revision pass
    over Elena's already-drafted, already-grounded (ADR-104) installment —
    post-draft, pre-publish. Tier-1 paused (matches coach_narrative — narrative
    embellishments pause before the flagship chronicle itself, which survives
    to tier 2). At most 2 Haiku calls total; fail-soft everywhere — any failure
    (budget pause, bad JSON, a rejected revision) simply returns Elena's draft
    untouched."""
    try:
        from budget_guard import allow as _budget_allow

        if not _budget_allow("chronicle_editor"):
            logger.info("[margaret] budget tier pauses the editor pass — keeping Elena's draft as-is")
            return raw_installment
    except ImportError:
        pass

    try:
        import margaret_editor_pass as _mep

        config = board_loader.load_board(s3, S3_BUCKET) if _HAS_BOARD_LOADER else None
        narrator = _mep.build_narrator(config)
        due_callbacks = _due_callback_promises(week_num)
        note_eligible = _mep.editors_note_eligible(_margaret_last_note_date(), date_str)

        result = _mep.run_pass(
            raw_installment,
            week_num,
            due_callbacks,
            allowed_numbers,
            note_eligible,
            narrator,
            critique_fn=_margaret_haiku_call,
            # Elena revises in her own voice — elena_prompt IS the system prompt;
            # the revise callable ignores the (unused) system arg run_pass passes it.
            revise_fn=lambda _system, user: _margaret_haiku_call(elena_prompt, user),
        )
        if result["revised"]:
            logger.info(f"[margaret] Week {week_num} revised ({result['revision_reason']})")
        elif result["critique"] is not None:
            logger.info(f"[margaret] Week {week_num} critique kept as-is ({result['revision_reason']})")
        if result["editors_note"]:
            _record_margaret_note(date_str, week_num, result["editors_note"])
            logger.info(f"[margaret] editor's note published for Week {week_num}")
        return result["final_text"]
    except ImportError as e:
        logger.warning(f"[margaret] edit-pass module unavailable (fail-soft): {e}")
        return raw_installment
    except Exception as e:
        logger.warning(f"[margaret] edit pass failed (fail-soft, keeping Elena's draft): {e}")
        return raw_installment


def lambda_handler(event: dict, context) -> dict:
    logger.info("Wednesday Chronicle v1.1.0 (Board Centralization) — The Measured Life — starting...")

    # Phase 3 bootstrap/regenerate: {"recap_only": true} builds + commits the
    # "previously on" recap from EXISTING published installments WITHOUT writing a new
    # chronicle week. Lets the first recap go live now (and supports regeneration)
    # without forcing an out-of-cadence installment.
    event = event or {}
    if event.get("recap_only"):
        data = gather_chronicle_data()
        if not data:
            return {"statusCode": 500, "body": "Failed to gather data"}
        recap = build_recap(data, new_installment_md=None, new_meta=None)
        if not recap or not recap.get("as_of"):
            return {"statusCode": 200, "body": json.dumps({"status": "recap_skipped", "reason": "no published history or build failed"})}
        _write_recap(recap, recap["as_of"])
        return {
            "statusCode": 200,
            "body": json.dumps({"status": "recap_written", "as_of": recap["as_of"], "beats": len(recap.get("recent_beats", []))}),
        }

    # Budget guardrail: skip this week's chronicle when the budget guard pauses it
    # (weekly, non-essential, subscriber-facing) — no Bedrock spend, clean no-op.
    try:
        from budget_guard import allow

        # Chronicle is weekly flagship content (~$1/wk of Bedrock) and the Friday Panel
        # podcast's ONLY input — so it must survive tier 1 and only pause at tier 2,
        # in lockstep with the Panel lambda's SKIP_TIER=2. The cutoff lives in exactly
        # one place — budget_guard._FEATURE_CUTOFF["chronicle"] (==2) — and allow()
        # reads it, so the tier band can be rebanded there without editing this lambda.
        if not allow("chronicle"):
            logger.info("Budget guard paused 'chronicle' — Wednesday chronicle skipped this week (no Bedrock spend)")
            _set_chronicle_pending(
                None,
                "budget_tier",
                "This week's chronicle is paused — the platform's AI budget guard is protecting monthly spend. "
                "It resumes automatically once usage drops below the threshold.",
            )
            return {"statusCode": 200, "body": "skipped: budget tier"}
    except ImportError:
        pass

    data = gather_chronicle_data()
    if not data:
        return {"statusCode": 500, "body": "Failed to gather data"}

    # Build narrative-ready data packet
    data_packet, week_num = build_data_packet(data)
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
        from engagement_core import presence_prompt_block as _ppb

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
        elena_prompt = _FALLBACK_ELENA_PROMPT

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
        import whole_life_context
        from phase_filter import with_phase_filter as _wpf

        _archive_items = whole_life_context.fetch_full_installment_archive(
            table, f"USER#{USER_ID}#SOURCE#chronicle", d2f=d2f, phase_filter=_wpf
        )
        if not _archive_items:
            _archive_items = data.get("prev_installments") or []
        _archive_text = whole_life_context.format_full_archive(_archive_items)
        logger.info(f"[#1385] whole-life archive: {len(_archive_items)} installment(s), {len(_archive_text)} chars (1h-cached block)")
    except Exception as _arch_e:  # noqa: BLE001 — the archive is context, never load-bearing
        logger.warning(f"[#1385] archive build skipped (non-fatal): {_arch_e}")
        _archive_text = ""

    # Call Sonnet
    logger.info("Calling Sonnet for Elena's installment (whole-life-context, 1h-cached archive)...")
    try:
        raw_installment = call_anthropic(elena_prompt, user_message, archive_text=_archive_text)
    except Exception as e:
        logger.error(f"Anthropic failed: {e}")
        return {"statusCode": 500, "body": f"AI generation failed: {e}"}

    logger.info(f"Installment received: {len(raw_installment)} chars, ~{len(raw_installment.split())} words")

    # #537 / ADR-104: the chronicle joins the grounded-generation gate. Every
    # number in the installment must exist somewhere in what Elena was given
    # (the data packet, prior installments, her notebook). Keep-best mode: one
    # corrective rewrite, kept only if strictly better — the weekly story is
    # human-reviewed (PREVIEW_MODE) + privacy-gated downstream, so a residual
    # finding degrades to the best draft instead of going dark.
    _allowed = None
    try:
        import grounded_generation as _gg

        # #1385: fold the whole-life archive into the allow-list source — Elena was
        # shown it, so its numbers/dates are grounded vocabulary, not fabrications.
        _allowed = _gg.allowed_numbers(elena_prompt, user_message, _archive_text)
        _draft_before_gate = raw_installment  # #812/#744: keep the pre-gate draft for retention
        _findings_fn = lambda t: installment_grounding_findings(elena_prompt, user_message, t, archive_text=_archive_text)  # noqa: E731
        _regen_fn = lambda corr: call_anthropic(elena_prompt, user_message + "\n\n" + corr, archive_text=_archive_text)  # noqa: E731
        raw_installment, _residual, _corrected = _gg.regen_once(raw_installment, _findings_fn, _regen_fn)
        if _corrected:
            logger.info(f"[ADR-104] chronicle corrected once; residual findings: {len(_residual)}")
        elif _residual:
            logger.warning(f"[ADR-104] chronicle keeps {len(_residual)} residual grounding findings (best draft)")
        if _corrected or _residual:
            # #812/#744: a fired chronicle gate is labeled eval data — retain the pair.
            try:
                import eval_retention

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
        from engagement_core import enforce_presence_acknowledgment as _epa, presence_ack_required as _par

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
                return {"statusCode": 500, "body": "[#914] Chronicle held: presence gap unacknowledged at severity loud/alarm"}
    except ImportError:
        pass  # engagement_core unavailable — serve as before
    except Exception as _ack_e:
        logger.warning(f"[#914] presence-ack gate error (fail-open): {_ack_e}")

    # AI-3: Validate output before rendering
    if _HAS_AI_VALIDATOR and raw_installment:
        _val = validate_ai_output(raw_installment, AIOutputType.CHRONICLE, min_length=200)
        if _val.blocked:
            logger.error(f"[AI-3] Chronicle BLOCKED: {_val.block_reason}")
            return {"statusCode": 500, "body": f"[AI-3] Chronicle blocked: {_val.block_reason}"}
        elif _val.warnings:
            logger.warning(f"[AI-3] Chronicle warnings: {_val.warnings}")

    # Parse the installment
    title, stats_line, body_md = parse_installment(raw_installment)

    # #1385 (AC4): validate the parsed installment envelope against the guaranteed
    # schema — a $0, no-AI rigor gate that turns the fragile stat-line parse into a
    # caught error instead of a silently mis-rendered stat line. Non-blocking (the
    # week is human-reviewed in PREVIEW_MODE + privacy-gated downstream); the
    # chokepoint (bedrock_client.structured_output_config) is ready to make the shape
    # model-guaranteed once deploy-time prose parity is confirmed (see PR POST-MERGE).
    try:
        import chronicle_schema

        _envelope = chronicle_schema.installment_from_stats(title, chronicle_schema.parse_stats_line(stats_line), body_md)
        _schema_errs = chronicle_schema.validate_installment(_envelope)
        if _schema_errs:
            logger.warning(f"[#1385] installment envelope failed schema validation (non-blocking): {_schema_errs}")
    except Exception as _sc_e:  # noqa: BLE001 — validation is a safety net, never load-bearing
        logger.warning(f"[#1385] installment schema validation error (non-fatal): {_sc_e}")

    # BS-05: Compute confidence badge based on total journey data depth.
    # Henning: LOW (<14d data), MEDIUM (14-49d), HIGH (≥50d + sig + effect).
    # Chronicle draws on full journey history — use days-since-start as n.
    _conf_level = "MEDIUM"
    _conf_badge_html = ""
    _conf_reason = ""
    if _HAS_CONFIDENCE:
        try:
            _journey_start = data.get("profile", {}).get("journey_start_date", EXPERIMENT_START_DATE)
            _journey_days = (datetime.strptime(data["dates"]["end"], "%Y-%m-%d") - datetime.strptime(_journey_start, "%Y-%m-%d")).days
            _conf = compute_confidence(days_of_data=_journey_days)
            _conf_level = _conf.get("level", "MEDIUM")
            _conf_badge_html = _conf.get("badge_html", "")
            _conf_reason = _conf.get("reason", "")
            logger.info(f"BS-05 confidence: {_conf_level} ({_conf_reason})")
        except Exception as _ce:
            logger.warning(f"BS-05 confidence compute failed (non-fatal): {_ce}")

    logger.info(f'Title: "{title}"')

    # Convert to HTML
    body_html = markdown_to_html(body_md)

    # Detect Board interview — a blockquote counts UNLESS it's Margaret's editor's
    # note (#548), which is also rendered as a blockquote but isn't an interview.
    has_board = any(line.strip().startswith("> ") and "editor's note" not in line.strip().lower() for line in body_md.split("\n"))

    # Collect all installments for index pages (including the new one)
    date_str = data["dates"]["end"]
    all_installments = []
    try:
        # ADR-058: phase=pilot hidden by default.
        from phase_filter import with_phase_filter

        resp = table.query(
            **with_phase_filter(
                {
                    "KeyConditionExpression": "pk = :pk AND begins_with(sk, :prefix)",
                    "ExpressionAttributeValues": {
                        ":pk": f"USER#{USER_ID}#SOURCE#chronicle",
                        ":prefix": "DATE#",
                    },
                    "ScanIndexForward": False,
                }
            )
        )
        all_installments = [d2f(i) for i in resp.get("Items", [])]
    except Exception as e:
        logger.warning(f"Failed to query all installments: {e}")
        all_installments = [{"title": title, "week_number": week_num, "date": date_str}]

    # Ensure new installment is in the list (not yet stored at this point)
    if not any(i.get("date") == date_str for i in all_installments):
        all_installments.insert(
            0,
            {
                "title": title,
                "week_number": week_num,
                "date": date_str,
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

    if PREVIEW_MODE:
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
            status="draft",
            approval_token=approval_token,
            draft_journal_post_html=journal_post_html,
            draft_journal_post_key=journal_post_key,
            draft_journal_posts_json=journal_posts_json,
            draft_email_html=draft_email_html,
            draft_recap_json=draft_recap_json,
            draft_share_kit_json=share_kit_json,
        )

        _send_preview_email(title, week_num, date_str, approval_token, draft_email_html, kit_block=share_kit_block)
        logger.info(f"FEAT-12: Draft Week {week_num} stored — awaiting approval")

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

    record_email_send(table, "wednesday_chronicle")
    if PREVIEW_MODE:
        return {
            "statusCode": 200,
            "body": f"Chronicle Week {week_num} draft stored — preview email sent to {RECIPIENT}",
        }
    return {
        "statusCode": 200,
        "body": f'Chronicle Week {week_num} published: "{title}" ({len(raw_installment.split())} words)',
    }
