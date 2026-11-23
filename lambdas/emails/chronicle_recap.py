"""lambdas/emails/chronicle_recap.py — Elena's serial "previously on" recap,
grounded only in published installments + the narrative arc, split out of
wednesday_chronicle_lambda.py (#1654). Facade state via the `_g` hand-off."""

from datetime import datetime, timezone

from common.constants import EXPERIMENT_START_DATE
from content import chapter_reads, elena_canon

# ══════════════════════════════════════════════════════════════════════════════
# "PREVIOUSLY ON" RECAP (backend serial phase 3) — Elena's cold-open catch-up
# ══════════════════════════════════════════════════════════════════════════════
#
# A recap is a serial-TV "previously on" — it lets a reader arriving months in
# orient fast. Built from ALREADY-PUBLISHED installments + the narrative arc only
# (never raw vitals), and committed to RECAP#latest only when a week is actually
# published — so it can never run ahead of the history it summarizes. Low-fabrication
# by construction; the deterministic date cross-check below is the strongest guard.

_RECAP_SYSTEM_PROMPT = elena_canon.identity_line() + """ \
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
}"""  # #6155: who is speaking comes from the one canon

# The raw-vital detector. A recap is narrative: the prompt allows a number ONLY when it
# appears verbatim in a provided installment, and this is the code that holds it to that.
#
# #5933: the first cut of this regex required a bare 2-3 digit run directly before an
# abbreviated unit, so "318.9 lbs" (a decimal) and "318 pounds" (a spelled unit) both
# walked through, and `where_we_are_now` was never scanned at all. Widening the pattern
# alone would have been wrong the other way — the recap legitimately quotes figures the
# installments printed — so a matched figure is now GROUNDED: it passes when the number
# appears in the installment text the model was shown, and is dropped when it does not.
import re as _re  # noqa: E402

_RECAP_NUM = r"(?<![\d.,])\d{1,3}(?:,\d{3})+(?:\.\d+)?|(?<![\d.,])\d+(?:\.\d+)?"
_RECAP_UNIT = r"bpm|ms|mg/?dl|lbs?|pounds?|kg|kilograms?|kcal|cal|calories?"
_RECAP_VITAL_RE = _re.compile(
    r"(?:" + _RECAP_NUM + r")[\s-]?(?:" + _RECAP_UNIT + r")\b"
    r"|\b(?:rhr|hrv|recovery|resting heart rate|resting hr|deep|rem)\b[^.\n]{0,14}?\b\d"
    r"|(?:" + _RECAP_NUM + r")\s?%",
    _re.IGNORECASE,
)
_RECAP_NUM_RE = _re.compile(_RECAP_NUM)


def _recap_numbers(text):
    """Every number token in ``text`` as a float set ("1,800" is 1800; "318.90" is 318.9)."""
    out = set()
    for m in _RECAP_NUM_RE.finditer(text or ""):
        try:
            out.add(float(m.group(0).replace(",", "")))
        except ValueError:
            continue
    return out


def _recap_raw_vital(text, grounded=None):
    """The first raw-vital span a recap text cites that is NOT grounded (the matched text), or None.

    ``grounded`` is the float set of numbers printed in the installment text the model was shown
    (`_recap_numbers`); a vital whose every number is in it is a quotation, not an invention. With
    no ``grounded`` set, every vital is reported — the pre-#5933 behaviour. #4865: the guard used to
    say only "cites a raw vital", which left a rejected recap undiagnosable from the log."""
    text = text or ""
    grounded = grounded or set()
    for m in _RECAP_VITAL_RE.finditer(text):
        # the numbers this vital span carries — a token that merely overlaps the span counts whole,
        # so the "recovery … 7" branch (which stops at the first digit) is judged on "76", not "7"
        nums = [float(n.group(0).replace(",", "")) for n in _RECAP_NUM_RE.finditer(text) if n.start() < m.end() and n.end() > m.start()]
        if not nums or any(n not in grounded for n in nums):
            return m.group(0)
    return None


def _recap_contains_raw_vitals(text, grounded=None):
    """True if the text cites a raw physiological number a recap must not invent."""
    return _recap_raw_vital(text, grounded) is not None


def _mask_titles(text, titles):
    """#4537: blank out verbatim installment titles before the raw-vital check. A title is reader-approved, audited text
    (the story-auditor passes it), so "76% on Day Two" quoted as a title is a name, not a vital. Only EXACT title strings
    from the installment list are masked, longest first; a figure anywhere else in the text still trips the guard."""
    out = text or ""
    for t in sorted({t for t in titles if t and len(t) > 2}, key=len, reverse=True):
        out = out.replace(t, " ")
    return out


def _published_installments(data):
    """Published installments only, newest-first — the recap's grounding spine.
    A draft that hasn't cleared the approve gate is NOT yet part of the public story."""
    out = []
    for inst in data.get("prev_installments", []) or []:
        # #4537: an unlisted installment (a superseded earlier-launch lead-in) is off the reading list and off the recap;
        # #6199 G1: so is a withdrawn, tombstoned or unpublished one — the one predicate every writer-side read uses
        if chapter_reads.writer_may_read(inst):
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
        titles = [i.get("title") for i in published] + [(new_meta or {}).get("title")]
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
        # #5933: the numbers a recap may quote — the installment PROSE the model is shown (the same 1,200-char
        # slice), plus the arc text. Not the titles (masked separately, #4537) and not the header dates/week
        # numbers this block synthesises, which would ground "24%" off "2026-06-24".
        grounding_prose = []
        for inst in ordered:
            wn = inst.get("week_number", "?")
            t = inst.get("title", "Untitled")
            d = inst.get("date", "?")
            md = (inst.get("content_markdown") or "")[:1200]
            grounding_prose.append(md)
            src.append(f'\n--- Week {wn} ({d}): "{t}" ---\n{md}')

        arc = data.get("narrative_arc")
        if arc:
            phase = arc.get("current_phase") or arc.get("phase")
            note = arc.get("note") or arc.get("summary") or ""
            if phase or note:
                src.append(f"\n=== NARRATIVE ARC ===\nphase: {phase}\n{note}")
                grounding_prose.append(str(note))
        exp_arc = data.get("experiment_arc")
        if exp_arc and exp_arc.get("throughline"):
            src.append(f"\n=== EXPERIMENT THROUGHLINE ===\n{exp_arc.get('throughline')}")
            grounding_prose.append(str(exp_arc.get("throughline")))
        grounded = _recap_numbers("\n".join(grounding_prose))

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
            # Guard 2 — strip beats that smuggle a raw vital the installments never printed.
            if _recap_contains_raw_vitals(_mask_titles(b.get("beat", ""), titles), grounded):
                logger.info("[recap] dropping beat with raw vital: %s", b.get("beat"))
                continue
            beats.append({"week": _as_int(b.get("week")), "date": b.get("date"), "beat": (b.get("beat") or "").strip()})
        beats = beats[:4]

        story = (recap.get("story_so_far") or "").strip()
        # Guard 3 — the headline paragraph must not invent vitals either.
        _story_vital = _recap_raw_vital(_mask_titles(story, titles), grounded)
        if _story_vital:
            logger.warning("[recap] story_so_far cites a raw vital (%r) — skipping recap", _story_vital)
            return None

        # Guard 3b (#5933) — the same rule for the two fields guards 2 and 3 never read. `where_we_are_now` is
        # dropped (blanked) when it cites a figure the installments never printed; a thread that does is removed.
        where_now = (recap.get("where_we_are_now") or "").strip()
        _now_vital = _recap_raw_vital(_mask_titles(where_now, titles), grounded)
        if _now_vital:
            logger.warning("[recap] where_we_are_now cites an ungrounded figure (%r) — dropping the field", _now_vital)
            where_now = ""
        threads = []
        for t in recap.get("threads_to_watch") or []:
            t = str(t).strip()
            _thread_vital = _recap_raw_vital(_mask_titles(t, titles), grounded)
            if _thread_vital:
                logger.info("[recap] dropping thread with an ungrounded figure (%r)", _thread_vital)
                continue
            threads.append(t)

        as_of = new_meta.get("date") if (new_meta and new_meta.get("date")) else (published[0].get("date") if published else None)
        as_of_week = (
            new_meta.get("week_number")
            if (new_meta and new_meta.get("week_number") is not None)
            else (published[0].get("week_number") if published else None)
        )

        out = {
            "story_so_far": story,
            "recent_beats": beats,
            "where_we_are_now": where_now,
            "threads_to_watch": threads[:3],
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

        # Guard 4b — the story door (#4538): the same reader-surface check the chronicle and the Panel face. A recap
        # that counts cycles/resets/attempts, or carries off-record specifics, is dropped — every reader-visible field.
        from content import story_checks

        door = story_checks.reader_surface(
            "\n".join([story, out["where_we_are_now"], *(b["beat"] for b in beats), *out["threads_to_watch"]])
        )
        if door:
            logger.error("[recap] story-door findings — dropping recap: %s", door)
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
    """Parse the recap LLM output in the one door (#4276): a dict, else None.

    Schema-less on purpose: `call_anthropic` here is the chronicle's text seam (prompt in,
    text out), which carries no `output_config`; the fence-tolerant parse is
    `ai.structured_json.parse_json_text`."""
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        return None
    from ai.structured_json import parse_json_text

    parsed = parse_json_text(raw)
    return parsed if isinstance(parsed, dict) else None


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
