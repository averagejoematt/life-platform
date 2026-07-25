"""lambdas/emails/chronicle_recap.py — Elena's serial "previously on" recap,
grounded only in published installments + the narrative arc, split out of
wednesday_chronicle_lambda.py (#1654). Facade state via the `_g` hand-off."""

import json
from datetime import datetime, timezone

from constants import EXPERIMENT_START_DATE

# ══════════════════════════════════════════════════════════════════════════════
# "PREVIOUSLY ON" RECAP (backend serial phase 3) — Elena's cold-open catch-up
# ══════════════════════════════════════════════════════════════════════════════
#
# A recap is a serial-TV "previously on" — it lets a reader arriving months in
# orient fast. Built from ALREADY-PUBLISHED installments + the narrative arc only
# (never raw vitals), and committed to RECAP#latest only when a week is actually
# published — so it can never run ahead of the history it summarizes. Low-fabrication
# by construction; the deterministic date cross-check below is the strongest guard.

_RECAP_SYSTEM_PROMPT = """You are Elena Voss, the embedded journalist narrating "The Measured Life." \
Write a short "previously on" recap — a serial cold-open that catches a reader up on the story so far.

GROUND TRUTH — you may ONLY reference what appears in the PUBLISHED INSTALLMENTS and NARRATIVE ARC provided below:
- If an event, week, or turning point is not in that source material, it did not happen. NEVER invent one.
- Each recap "beat" MUST cite a real date and week drawn from the installment list provided — do not invent dates.
- NO numbers unless they appear verbatim in a provided installment. Never state a weight, HRV, sleep, recovery, \
calorie, or percentage that you compute or estimate yourself — this is a narrative recap, not a data readout.
- If fewer than 2 published installments exist, return only a one-or-two-sentence story_so_far and an empty \
recent_beats list — do not pad.
- Write in Elena's voice: present-tense, propulsive, a touch wry. This is the cold-open of a show, not a summary memo.

Return ONLY valid JSON, no markdown, no preamble:
{
  "story_so_far": "one tight ~100-word paragraph: the arc up to now, in my voice",
  "recent_beats": [
    {"week": <int>, "date": "YYYY-MM-DD", "beat": "one sentence — what happened that week"}
  ],
  "where_we_are_now": "1-2 sentences on the present state of the experiment",
  "threads_to_watch": ["an unresolved tension going forward", "another"]
}"""

# Minimal raw-vital detector — this module isn't on the coach summarizer's path, so
# we replicate a small regex here (mirrors coach_history_summarizer._RAW_VITAL_RE).
import re as _re  # noqa: E402

_RECAP_VITAL_RE = _re.compile(
    r"\b\d{2,3}\s?(?:bpm|ms|mg/?dl|lbs?|kg|kcal|cal)\b"
    r"|\b(?:rhr|hrv|recovery|resting heart rate|resting hr|deep|rem)\b[^.\n]{0,14}?\b\d"
    r"|\b\d{1,3}(?:\.\d+)?\s?%",
    _re.IGNORECASE,
)


def _recap_contains_raw_vitals(text):
    """True if the text cites a raw physiological number a recap must not invent."""
    return bool(_RECAP_VITAL_RE.search(text or ""))


def _published_installments(data):
    """Published installments only, newest-first — the recap's grounding spine.
    A draft that hasn't cleared the approve gate is NOT yet part of the public story."""
    out = []
    for inst in data.get("prev_installments", []) or []:
        if (inst.get("status") or "published") == "published":
            out.append(inst)
    out.sort(key=lambda i: i.get("date", ""), reverse=True)
    return out


def build_recap(data, new_installment_md=None, new_meta=None, *, _g):
    """Build Elena's 'previously on' recap, grounded ONLY in published installments +
    the narrative arc. Returns a recap dict (plain ints/strings, JSON-safe) or None on
    any failure — a recap must NEVER abort the chronicle run.

    new_installment_md / new_meta ({date, week_number, title}) describe the week being
    published in THIS run (allowed in the grounding + the date cross-check); pass None
    in recap_only/bootstrap mode to recap the published-so-far history.
    """
    call_anthropic = _g["call_anthropic"]
    privacy_guard = _g["privacy_guard"]
    logger = _g["logger"]
    try:
        published = _published_installments(data)

        # The set of dates a beat may legitimately cite — published history plus, when
        # generating alongside a new week, that week (it is being published in this run).
        allowed = {i.get("date") for i in published if i.get("date")}
        if new_meta and new_meta.get("date"):
            allowed.add(new_meta["date"])

        # Grounding source block — prose summaries only.
        src = ["=== PUBLISHED INSTALLMENTS (oldest first) ==="]
        ordered = list(reversed(published))
        if new_meta and new_installment_md:
            ordered.append(
                {
                    "week_number": new_meta.get("week_number"),
                    "title": new_meta.get("title"),
                    "date": new_meta.get("date"),
                    "content_markdown": new_installment_md,
                }
            )
        for inst in ordered:
            wn = inst.get("week_number", "?")
            t = inst.get("title", "Untitled")
            d = inst.get("date", "?")
            md = (inst.get("content_markdown") or "")[:1200]
            src.append(f'\n--- Week {wn} ({d}): "{t}" ---\n{md}')

        arc = data.get("narrative_arc")
        if arc:
            phase = arc.get("current_phase") or arc.get("phase")
            note = arc.get("note") or arc.get("summary") or ""
            if phase or note:
                src.append(f"\n=== NARRATIVE ARC ===\nphase: {phase}\n{note}")
        exp_arc = data.get("experiment_arc")
        if exp_arc and exp_arc.get("throughline"):
            src.append(f"\n=== EXPERIMENT THROUGHLINE ===\n{exp_arc.get('throughline')}")

        if not allowed:
            logger.info("[recap] no published installments — skipping recap")
            return None

        raw = call_anthropic(_RECAP_SYSTEM_PROMPT, "\n".join(src))
        recap = _parse_recap_json(raw)
        if not recap:
            logger.warning("[recap] could not parse recap JSON — skipping")
            return None

        # Guard 1 — deterministic date cross-check: drop any beat whose date is not a
        # real published-installment date (never trust an LLM-emitted date).
        beats = []
        for b in recap.get("recent_beats") or []:
            if not isinstance(b, dict):
                continue
            if b.get("date") not in allowed:
                logger.info("[recap] dropping beat with non-published date %s", b.get("date"))
                continue
            # Guard 2 — strip beats that smuggle a raw vital.
            if _recap_contains_raw_vitals(b.get("beat", "")):
                logger.info("[recap] dropping beat with raw vital: %s", b.get("beat"))
                continue
            beats.append({"week": _as_int(b.get("week")), "date": b.get("date"), "beat": (b.get("beat") or "").strip()})
        beats = beats[:4]

        story = (recap.get("story_so_far") or "").strip()
        # Guard 3 — the headline paragraph must not invent vitals either.
        if _recap_contains_raw_vitals(story):
            logger.warning("[recap] story_so_far cites a raw vital — skipping recap")
            return None

        as_of = new_meta.get("date") if (new_meta and new_meta.get("date")) else (published[0].get("date") if published else None)
        as_of_week = (
            new_meta.get("week_number")
            if (new_meta and new_meta.get("week_number") is not None)
            else (published[0].get("week_number") if published else None)
        )

        out = {
            "story_so_far": story,
            "recent_beats": beats,
            "where_we_are_now": (recap.get("where_we_are_now") or "").strip(),
            "threads_to_watch": [str(t).strip() for t in (recap.get("threads_to_watch") or [])][:3],
            "as_of": as_of,
            "as_of_week": _as_int(as_of_week),
            "experiment_day": _chronicle_day_n(as_of),  # powers the read-time stale guard
            "grounded_in": {"installments": sorted([d for d in allowed if d], reverse=True)[:12], "arc": bool(arc)},
            "author": "Elena Voss",
        }

        # Guard 4 — privacy gate (fail-closed): never persist a recap naming a real
        # public figure or a vice. A violation drops the recap; the chronicle is unaffected.
        try:
            privacy_guard.assert_clean(
                story + "\n" + out["where_we_are_now"] + "\n" + " ".join(b["beat"] for b in beats),
                context="chronicle recap",
            )
        except privacy_guard.PrivacyViolation as e:
            logger.error("[recap] privacy violation — dropping recap: %s", e)
            return None

        # Guard 5 — thin history: with <2 published installments, keep only the
        # one-line story_so_far (the prompt is told this, but enforce it too).
        if len(allowed) < 2:
            out["recent_beats"] = []
            out["threads_to_watch"] = []

        return out
    except Exception as e:  # fail-soft — a recap error never aborts the chronicle
        logger.warning("[recap] build_recap failed (non-fatal): %s", e)
        return None


def _as_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _parse_recap_json(raw):
    """Parse the recap LLM output: bare JSON, or fenced ```json … ```."""
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        return None
    txt = raw.strip()
    try:
        return json.loads(txt)
    except json.JSONDecodeError:
        pass
    if "```json" in txt:
        start = txt.find("```json") + 7
        end = txt.find("```", start)
        if end > start:
            try:
                return json.loads(txt[start:end].strip())
            except json.JSONDecodeError:
                return None
    return None


def _write_recap(recap, date_str, *, _g):
    """Persist a recap to RECAP#latest (pointer) + RECAP#{date} (history), under the
    chronicle partition — already EXPERIMENT_SCOPED + wiped on reset (no taxonomy change)."""
    USER_ID = _g["USER_ID"]
    table = _g["table"]
    logger = _g["logger"]
    if not recap:
        return
    pk = f"USER#{USER_ID}#SOURCE#chronicle"
    base = dict(recap)
    base["pk"] = pk
    base["source"] = "chronicle_recap"
    base["experiment_day"] = _chronicle_day_n(date_str)
    base["generated_at"] = datetime.now(timezone.utc).isoformat()
    base["status"] = "published"
    for sk in (f"RECAP#{date_str}", "RECAP#latest"):
        item = dict(base)
        item["sk"] = sk
        table.put_item(Item=item)
    logger.info("[recap] wrote RECAP#latest + RECAP#%s", date_str)


def _chronicle_day_n(date_str):
    """1-indexed experiment day for the recap's as_of date — powers the read-time
    stale guard (a pre-reset record surviving a genesis re-anchor is withheld)."""
    try:
        start = datetime.strptime(EXPERIMENT_START_DATE, "%Y-%m-%d").date()
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
        return max(1, (d - start).days + 1)
    except Exception:
        return None
