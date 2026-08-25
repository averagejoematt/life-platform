"""
Field Notes Generate Lambda — BL-04 Phase 1

Weekly lab notebook entry generator. Gathers 7-day data across all domains,
calls Claude Sonnet for synthesis, writes AI-generated notes to DynamoDB.

Trigger: EventBridge cron — Sunday 10am PT (18:00 UTC)
Can be manually invoked with {"manual_week": "2026-W13"}.

DynamoDB:
  PK = USER#matthew#SOURCE#field_notes
  SK = WEEK#YYYY-WNN

v1.0.0 — 2026-03-31
"""

import json
import logging
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

import boto3
from boto3.dynamodb.conditions import Key

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
USER_ID = os.environ.get("USER_ID", "matthew")
USER_PREFIX = f"USER#{USER_ID}#SOURCE#"
FN_PK = f"{USER_PREFIX}field_notes"
AI_SECRET_NAME = os.environ.get("AI_SECRET_NAME", "life-platform/ai-keys")
AI_MODEL = os.environ.get("AI_MODEL", "claude-haiku-4-5-20251001")

dynamodb = boto3.resource("dynamodb", region_name="us-west-2")
table = dynamodb.Table(TABLE_NAME)

_api_key_cache = None


def _get_api_key():
    global _api_key_cache
    if _api_key_cache:
        return _api_key_cache
    sm = boto3.client("secretsmanager", region_name="us-west-2")
    resp = sm.get_secret_value(SecretId=AI_SECRET_NAME)
    secret = resp["SecretString"]
    try:
        parsed = json.loads(secret)
        _api_key_cache = parsed.get("anthropic_api_key", secret)
    except (json.JSONDecodeError, TypeError):
        _api_key_cache = secret
    return _api_key_cache


from common.numeric import decimals_to_float as _decimal_to_float  # noqa: E402,F401
from common.pacific_time import pacific_now  # #2811: THE Pacific day helper — DATE# keys are Pacific days


def get_iso_week(dt=None):
    if dt is None:
        # #2811: the ISO week of the PACIFIC calendar day — a UTC "now" after 4/5pm PT
        # rolls the week label a day early (and on Sunday evenings, a WEEK early).
        dt = pacific_now()
    year, week, _ = dt.isocalendar()
    return f"{year}-W{week:02d}"


def week_bounds(iso_week):
    year, week = int(iso_week[:4]), int(iso_week[6:])
    monday = datetime.fromisocalendar(year, week, 1)
    sunday = datetime.fromisocalendar(year, week, 7)
    return monday.strftime("%Y-%m-%d"), sunday.strftime("%Y-%m-%d")


def genesis_week_label(iso_week):
    """Genesis-anchored display label ('Week N' / 'Prologue') for an ISO week.

    The raw ISO calendar week (e.g. 2026-W25) rendered on the site as "w24/w25" — wrong:
    the experiment is genesis-anchored. Week 1 = the week containing EXPERIMENT_START_DATE;
    anything before is Prologue. Mirrors the chronicle's genesis week numbering.
    """
    try:
        from common.constants import EXPERIMENT_START_DATE

        genesis = datetime.strptime(EXPERIMENT_START_DATE, "%Y-%m-%d")
        monday = datetime.fromisocalendar(int(iso_week[:4]), int(iso_week[6:]), 1)
        g_monday = genesis - timedelta(days=genesis.weekday())  # Monday of the genesis week
        n = (monday - g_monday).days // 7 + 1
        return f"Week {n}" if n >= 1 else "Prologue"
    except Exception:  # noqa: BLE001
        return None


def _query_source(source, start_date, end_date):
    pk = f"{USER_PREFIX}{source}"
    resp = table.query(KeyConditionExpression=Key("pk").eq(pk) & Key("sk").between(f"DATE#{start_date}", f"DATE#{end_date}"))
    return _decimal_to_float(resp.get("Items", []))


_DAY_SK_RE = re.compile(r"^DATE#\d{4}-\d{2}-\d{2}$")


def _query_day_records(source, start_date, end_date):
    """Day-level records only. Some partitions carry sub-records under the same
    date prefix (whoop stores DATE#<day>#WORKOUT#<uuid> per workout), and counting
    them as days produced "20 nights of sleep in one week" — which the AI then
    publicly flagged as a tracking error in its own note (2026-W26)."""
    return [i for i in _query_source(source, start_date, end_date) if _DAY_SK_RE.match(str(i.get("sk", "")))]


def _latest_item(source):
    pk = f"{USER_PREFIX}{source}"
    resp = table.query(
        KeyConditionExpression=Key("pk").eq(pk),
        ScanIndexForward=False,
        Limit=1,
    )
    items = _decimal_to_float(resp.get("Items", []))
    return items[0] if items else None


def gather_week_data(start_date, end_date):
    """Gather data from all partitions for a given week."""
    data = {}

    # Sleep (Whoop)
    sleep_items = _query_day_records("whoop", start_date, end_date)
    if sleep_items:
        hrs = [i.get("sleep_duration_hours", 0) for i in sleep_items if i.get("sleep_duration_hours")]
        hrvs = [i.get("hrv", 0) for i in sleep_items if i.get("hrv")]
        data["sleep"] = {
            "nights": len(sleep_items),
            "avg_hours": round(sum(hrs) / len(hrs), 1) if hrs else None,
            # Unit in the key so the model can't guess "bpm" (HRV is milliseconds).
            "avg_hrv_ms": round(sum(hrvs) / len(hrvs), 1) if hrvs else None,
        }

    # Nutrition (MacroFactor)
    nutrition = _query_day_records("macrofactor", start_date, end_date)
    if nutrition:
        cals = [float(i["total_calories_kcal"]) for i in nutrition if i.get("total_calories_kcal")]
        protein = [float(i["total_protein_g"]) for i in nutrition if i.get("total_protein_g")]
        data["nutrition"] = {
            "days_tracked": len(nutrition),
            "avg_calories": round(sum(cals) / len(cals)) if cals else None,
            "avg_protein_g": round(sum(protein) / len(protein), 1) if protein else None,
        }

    # Training (Strava) — items are DAY rollups (activity_count, total_moving_time_seconds,
    # activities[]), not individual activities. Reading per-activity fields off the day
    # record produced "N sessions / 0 minutes", which the AI then publicly flagged as a
    # data-entry bug in the 2026-W26 note.
    day_records = _query_day_records("strava", start_date, end_date)
    if day_records:

        def _day_minutes(rec):
            total = rec.get("total_moving_time_seconds")
            if total is None:
                total = sum(float(a.get("moving_time_seconds") or a.get("elapsed_time_seconds") or 0) for a in rec.get("activities") or [])
            return float(total or 0) / 60

        data["training"] = {
            "sessions": sum(int(rec.get("activity_count") or len(rec.get("activities") or []) or 1) for rec in day_records),
            "total_minutes": round(sum(_day_minutes(rec) for rec in day_records)),
        }

    # Weight (Withings)
    weights = _query_day_records("withings", start_date, end_date)
    if weights:
        wt = [float(w.get("weight_lbs", 0)) for w in weights if w.get("weight_lbs")]
        if wt:
            data["weight"] = {
                "readings": len(wt),
                "start": wt[0],
                "end": wt[-1],
                "change": round(wt[-1] - wt[0], 1),
            }

    # Habits (habit_scores)
    # Truth audit 2026-07-10: habit_scores records have NO `completion_rate` field —
    # reading it always yielded [], so avg_completion was silently None and the model,
    # handed only days_scored=7, invented "you scored 6 of 7 days" over a week where
    # every completion was zero. Derive the real rate from the fields the records DO
    # carry (tier0_pct, or tier0_done/tier0_total) and state a zero week explicitly so
    # the prompt can never romance it.
    habits = _query_day_records("habit_scores", start_date, end_date)
    if habits:
        rates = []
        for h in habits:
            r = h.get("tier0_pct")
            if r is None and h.get("tier0_total"):
                try:
                    r = float(h.get("tier0_done", 0)) / float(h["tier0_total"]) * 100
                except (TypeError, ValueError, ZeroDivisionError):
                    r = None
            if r is not None:
                rates.append(float(r))
        days_with_any_completion = sum(1 for r in rates if r > 0)
        data["habits"] = {
            "days_scored": len(habits),
            "days_with_any_completion": days_with_any_completion,
            "avg_tier0_completion_pct": round(sum(rates) / len(rates)) if rates else None,
        }
        if rates and days_with_any_completion == 0:
            data["habits"][
                "note"
            ] = "zero habit completions recorded on every scored day this week — a full stall, not a partial week; do not report any completed days"

    # Journal (Notion)
    journal_pk = f"{USER_PREFIX}notion"
    j_resp = table.query(
        KeyConditionExpression=Key("pk").eq(journal_pk) & Key("sk").between(f"DATE#{start_date}#journal", f"DATE#{end_date}#journal#~"),
    )
    journal_items = _decimal_to_float(j_resp.get("Items", []))
    journal_items = [j for j in journal_items if "#journal#" in j.get("sk", "")]
    if journal_items:
        data["journal"] = {"entry_count": len(journal_items)}

    # Character sheet (latest)
    cs = _latest_item("character_sheet")
    if cs:
        data["character"] = {
            "level": cs.get("level"),
            "day_grade": cs.get("day_grade"),
        }

    # Mood (State of Mind) — daily aggregates (som_avg_valence / som_check_in_count)
    # land on the apple_health partition; DDB has no per-reading valence rows
    # (individual check-ins live in S3), so read the aggregate fields.
    mood_items = [m for m in _query_day_records("apple_health", start_date, end_date) if m.get("som_avg_valence") is not None]
    if mood_items:
        valences = [float(m["som_avg_valence"]) for m in mood_items]
        check_ins = sum(int(float(m.get("som_check_in_count", 1) or 1)) for m in mood_items)
        data["mood"] = {
            "readings": check_ins,
            "days_with_data": len(mood_items),
            "avg_valence": round(sum(valences) / len(valences), 2) if valences else None,
        }

    return data


def get_prior_notes(current_week, count=4):
    """Get prior weeks' field notes for context."""
    year, week_num = int(current_week[:4]), int(current_week[6:])
    prior_weeks = []
    for i in range(1, count + 1):
        dt = datetime.fromisocalendar(year, week_num, 1) - timedelta(weeks=i)
        pw = get_iso_week(dt)
        prior_weeks.append(pw)

    # #1969 (#946 class): field_notes is EXPERIMENT_SCOPED and the restart wipe
    # tombstones it in place — an unguarded get_item would seed the fresh cycle's
    # prompt with the wiped cycle's notes (the exact prior-analysis leak class).
    from experiment.phase_filter import singleton_visible

    notes = []
    for pw in prior_weeks:
        resp = table.get_item(Key={"pk": FN_PK, "sk": f"WEEK#{pw}"})
        item = _decimal_to_float(resp.get("Item"))
        if singleton_visible(item) and item.get("ai_present"):
            notes.append(
                {
                    "week": pw,
                    "present": item.get("ai_present", ""),
                    "tone": item.get("ai_tone", ""),
                }
            )
    return notes


def build_prompt(iso_week, data, prior_notes):
    start, end = week_bounds(iso_week)

    data_section = json.dumps(data, indent=2, default=str)

    prior_section = ""
    if prior_notes:
        prior_section = "\n\nPrior weeks' notes for context:\n"
        for n in prior_notes:
            prior_section += f"\n--- {n['week']} (tone: {n['tone']}) ---\n{n['present'][:500]}\n"

    return f"""You are the AI health advisor for Matthew's personal health platform (averagejoematt.com).
You are writing the weekly Field Notes — a lab notebook entry that synthesizes all data from the week.

This is week {iso_week} ({start} to {end}).

Here is all the data collected this week:
{data_section}
{prior_section}

Write three distinct sections. Respond with ONLY a JSON object (no other text):

{{
  "ai_present": "2-3 paragraphs. What happened this week. Be specific — reference actual numbers. This is the 'present signal' section. Honest, direct, no cheerleading. If data is sparse, say so.",
  "ai_cautionary": "1-2 paragraphs. What concerns you. Patterns that deserve attention. If nothing concerning, write about what to watch for. Optional — omit this field if genuinely nothing to flag.",
  "ai_affirming": "1-2 paragraphs. What's going well. Bright spots in the data. Don't force positivity — only affirm what the data actually supports. Optional — omit if nothing stands out.",
  "ai_tone": "one of: affirming, cautionary, urgent, mixed"
}}

Requirements:
- Write in first person as the platform's AI advisor
- Be honest and direct — Matthew chose radical transparency
- Reference specific numbers from the data
- UNITS: HRV is in milliseconds (ms), never bpm. Heart rate is in bpm. Never swap them.
- Do NOT use bullet points — flowing prose only
- If a data domain has no entries, acknowledge the gap briefly
- Tone should match the data: don't be affirming when the data is concerning"""


def _call_notes_model(prompt, api_key):
    """One model call → parsed field-notes JSON (shared by first pass + regen)."""
    req_body = json.dumps(
        {
            "model": AI_MODEL,
            "max_tokens": 2000,
            "messages": [{"role": "user", "content": prompt}],
        }
    )
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=req_body.encode(),
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
    )
    # Phase 3.4 (2026-05-16): retry via retry_utils (4 attempts, 5/15/45s).
    from common.retry_utils import call_anthropic_raw

    result = call_anthropic_raw(req, timeout=60)
    text = "".join(b["text"] for b in result.get("content", []) if b.get("type") == "text").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    return json.loads(text)


_NOTE_FIELDS = ("ai_present", "ai_cautionary", "ai_affirming")


def note_contradiction_hits(analysis, metrics_record):
    """SS-10 deterministic core: the contradiction hits for one generated note
    against one computed_metrics record — exactly the composition the live
    `_grounding_contradictions` applies (build_canonical_facts → the shared TIGHT
    guard over the three note fields). Extracted (#812) so the golden-surface
    eval harness replays fixtures through the ACTUAL gate path. Raises loudly on
    import/shape problems — the live caller wraps it fail-soft."""
    try:
        from intelligence.grounding_guard import hard_canonical_contradictions
    except ImportError:  # pragma: no cover — flat sys.path (tests / bundle root)
        from grounding_guard import hard_canonical_contradictions

    from experiment.canonical_facts import observed_facts

    # #2113: the AS-MEASURED view, not the publication view. This detector asks "does
    # the note contradict the record it was written from?", which the cycle boundary
    # has no bearing on — a note claiming 25% against a record holding 55% is wrong in
    # any cycle. Using build_canonical_facts here would make the detector go DARK for
    # the days after each reset, when its facts are withheld. `observed_facts` also
    # carries no provenance keys, so the old hardcoded `as_of` filter goes with it.
    facts = observed_facts(metrics_record)
    hits = []
    for f in _NOTE_FIELDS:
        hits.extend(hard_canonical_contradictions(analysis.get(f) or "", facts))
    return hits


def _note_grounding_findings(analysis, prompt):
    """#2426 — the standard ``grounding_findings`` chokepoint for the field note.

    Replaces the weaker single-check gate (hard_canonical_contradictions against one
    computed_metrics row, fail-soft to "served unchecked"). The allow-list is the
    PROMPT — literally what the model was given (the week's computed data section +
    prior-note excerpts), the horizons/analyzer discipline — so a number or calendar
    date the inputs never contained cannot ship, whether or not the metrics row
    exists. ``**cycle_gate_params()`` arms the #1691/#1897 cycle anchors.

    The canonical-facts contradiction check is KEPT, via ``note_contradiction_hits``
    (the #812 extraction the golden-surface eval harness replays fixtures through);
    it stays best-effort — a missing metrics row degrades to allow-list-only gating,
    it no longer waves the note through entirely.

    Fail-closed at the top level: if the gate machinery itself is unavailable or
    raises, a synthetic finding is returned and the caller HOLDS — a broken gate
    withholds, it never waves reader text through (the horizons/#2395 posture).
    """
    try:
        from ai.grounded_generation import allowed_dates, allowed_numbers, grounding_findings
        from ai.grounding_gate_params import cycle_gate_params

        text = "\n\n".join(str(analysis.get(f) or "") for f in _NOTE_FIELDS)
        findings = list(
            grounding_findings(
                text,
                allowed=allowed_numbers(prompt),
                allowed_dates=allowed_dates(prompt),
                **cycle_gate_params(),
            )
        )
    except Exception as e:  # noqa: BLE001 — a broken gate holds; it never waves text through
        return [{"type": "gate_error", "detail": f"grounding gate unavailable ({type(e).__name__}) — note held, never served ungated"}]

    try:
        resp = table.query(
            KeyConditionExpression=Key("pk").eq("USER#matthew#SOURCE#computed_metrics"),
            ScanIndexForward=False,
            Limit=1,
        )
        items = resp.get("Items", [])
        if items:
            for h in note_contradiction_hits(analysis, items[0]):
                findings.append({"type": "contradiction", **h})
    except Exception as e:  # noqa: BLE001 — facts check stays best-effort; the allow-list classes above still gate
        logger.info(f"[grounding] canonical-facts check unavailable ({type(e).__name__}) — allow-list gating only")
    return findings


def generate_field_notes(iso_week):
    start, end = week_bounds(iso_week)
    logger.info(f"Generating field notes for {iso_week} ({start} to {end})")

    # Check if already exists. #1969 (#946 class): a TOMBSTONED row is a prior
    # cycle's archive, treated as absent — the fresh cycle regenerates its own
    # note for the week instead of being suppressed by wiped content (the public
    # read is phase-filtered, so suppression would leave the week blank all cycle).
    from experiment.phase_filter import singleton_visible

    existing = table.get_item(Key={"pk": FN_PK, "sk": f"WEEK#{iso_week}"}).get("Item")
    if singleton_visible(existing) and existing.get("ai_generated_at"):
        logger.info(f"Field notes for {iso_week} already exist, skipping")
        return {"status": "already_exists", "week": iso_week}

    data = gather_week_data(start, end)
    prior_notes = get_prior_notes(iso_week)
    prompt = build_prompt(iso_week, data, prior_notes)

    api_key = _get_api_key()
    analysis = _call_notes_model(prompt, api_key)

    # #2426 (was SS-10): the field note is the public Third Wall — a fabricated
    # number/date, a stale-cycle framing, or a canonical-facts contradiction must
    # not ship as written. One strict regeneration with the findings named, kept
    # only if it strictly improves (the analyzer's proven keep-if-improved pattern
    # — never regress to a worse draft, never loop chasing stochastic output) —
    # and if the best draft STILL carries findings, the note is HELD: nothing is
    # written, so /api/field_notes never serves failed text (regenerate-once-
    # then-hold, the ADR-151/#2395 posture).
    findings = _note_grounding_findings(analysis, prompt)
    if findings:
        detail = "; ".join(str(f.get("detail", "")) for f in findings[:3])
        _draft_note = {f: analysis.get(f) for f in _NOTE_FIELDS}  # #812/#744: pre-rewrite note for retention
        logger.info(f"[grounding] {len(findings)} finding(s) in {iso_week}: {detail} — one corrective rewrite")
        fix_prompt = (
            prompt
            + "\n\nCORRECTION REQUIRED — your previous draft was not grounded in the week's "
            + f"data: {detail}. Rewrite the full JSON response. Never state a number or date "
            + "that is not in the data above; when unsure, describe the pattern without one."
        )
        try:
            retry = _call_notes_model(fix_prompt, api_key)
            retry_findings = _note_grounding_findings(retry, prompt)
            if len(retry_findings) < len(findings):
                logger.info(f"[grounding] rewrite kept ({len(findings)} → {len(retry_findings)})")
                analysis, findings = retry, retry_findings
            else:
                logger.warning(f"[grounding] rewrite not better ({len(findings)} → {len(retry_findings)}) — keeping the original")
        except Exception as e:  # noqa: BLE001 — regen is best-effort; a failed rewrite falls through to the HOLD below
            logger.warning(f"[grounding] rewrite failed ({type(e).__name__})")
        try:  # #812/#744: a fired note gate is labeled eval data — retain the pair (fail-soft)
            from experiment import eval_retention

            eval_retention.retain(
                "field_notes",
                # empty findings here implies the rewrite was kept and cleared them; anything else holds below
                "flagged_corrected" if not findings else "flagged_held",
                draft=json.dumps(_draft_note),
                final=json.dumps({f: analysis.get(f) for f in _NOTE_FIELDS}),
                findings=[{"type": str(f.get("type", "finding")), "detail": str(f.get("detail", ""))} for f in findings[:10]],
                extra={"week": iso_week, "n_findings": len(findings)},
            )
        except Exception:  # noqa: BLE001 — retention is never load-bearing
            pass
        if findings:
            # HOLD — the one rewrite did not clear the findings. No write: the reader
            # surface reads the WEEK# row, so an absent row is an absent note, never
            # failed text. A later manual invoke can regenerate the week.
            logger.warning(f"[grounding] HELD {iso_week}: {len(findings)} finding(s) after the one rewrite — {detail}")
            return {"status": "held", "week": iso_week, "findings": len(findings)}

    now = datetime.now(timezone.utc).isoformat()

    item = {
        "pk": FN_PK,
        "sk": f"WEEK#{iso_week}",
        "week": iso_week,
        "week_label": genesis_week_label(iso_week),  # genesis-anchored display label (#2)
        "ai_present": analysis.get("ai_present", ""),
        "ai_tone": analysis.get("ai_tone", "mixed"),
        "ai_generated_at": now,
    }
    if analysis.get("ai_cautionary"):
        item["ai_cautionary"] = analysis["ai_cautionary"]
    if analysis.get("ai_affirming"):
        item["ai_affirming"] = analysis["ai_affirming"]

    table.put_item(Item=item)
    logger.info(f"Wrote field notes for {iso_week}: {len(item.get('ai_present', ''))} chars")

    # #1441: generation-time archive — the published note fields exactly as the
    # WEEK# record carries them (the reader-facing surface renders these), to
    # generated/qa_archive/. Fail-soft inside the module.
    try:
        from common import qa_archive

        note_fields = {k: item[k] for k in ("ai_present", "ai_tone", "ai_cautionary", "ai_affirming") if item.get(k)}
        qa_archive.archive_text("field_notes", json.dumps(note_fields), meta={"week": iso_week})
    except Exception as qa_e:  # noqa: BLE001 — the archive is never load-bearing
        logger.warning(f"[field_notes] qa_archive failed (non-fatal): {qa_e}")

    return {"status": "ok", "week": iso_week, "chars": len(item.get("ai_present", ""))}


def lambda_handler(event: dict, context) -> dict:
    manual_week = event.get("manual_week")
    if manual_week:
        iso_week = manual_week
    else:
        # Default: generate for the week that just ended (previous week)
        last_sunday = datetime.now(timezone.utc) - timedelta(days=1)
        iso_week = get_iso_week(last_sunday)

    try:
        result = generate_field_notes(iso_week)
        return {"statusCode": 200, "body": json.dumps(result)}
    except Exception as e:
        logger.error(f"Failed to generate field notes for {iso_week}: {e}")
        return {"statusCode": 500, "body": json.dumps({"error": str(e), "week": iso_week})}
