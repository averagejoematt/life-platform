"""reading_date_fidelity.py — day-correspondence for DERIVED coach summaries (#2343).

THE INCIDENT
------------
On 2026-08-08 the nutrition coach's card on `/api/coaching-dashboard` published
"Whoop shows 55% recovery and HRV at 42 ms" while `/api/vitals` served 31% / 32 ms
for the same `as_of_date`. Every hypothesis about *fabrication* was wrong: 55 / 42
are 2026-08-07's real Whoop readings, exact on both metrics. The DAY was wrong, not
the values — which is why a grounded-generation check asking "does this number
appear in the fact set" structurally cannot catch it (ADR-104 day-correspondence,
not existence).

THE PATH THE VITAL TOOK — and why the existing gates all passed
---------------------------------------------------------------
1. `computed_metrics` is written for the PREVIOUS day (daily-metrics-compute runs
   16:40 UTC and stores yesterday's completed day), while `/api/vitals` resolves the
   whoop partition directly. The coach fact block is therefore structurally ~1 day
   behind the cockpit — permanently, not occasionally.
2. `ai_calls.py` injects that record through `grounded_generation.authoritative_facts_block`
   into the SHARED system prompt every persona receives. That is how a single-day
   Whoop reading reached the NUTRITION persona, whose own fact block queries
   macrofactor only and emits no Whoop field on either branch — the vital never came
   from the persona's fact block at all.
3. The #1968 seam worked: the block's `night_scope.night_label_line` named the night,
   and the generated NARRATIVE said "Whoop caught 55% recovery on the night of
   2026-08-06, HRV at 42 ms, resting HR at 53 bpm". Correct, dated, checkable.
4. The published card is NOT that narrative. `coach_state_updater` asks an LLM for an
   `observatory_summary` — a condensation written AFTER every grounding gate has run —
   and the site API serves it in the `position_summary` slot. The condensation dropped
   the night label and re-framed the reading in the present tense: "Whoop shows 55%
   recovery and HRV at 42 ms".

So a grounded artifact was condensed into an ungrounded one, and nothing looked at the
condensation. This module is the missing check, and it deliberately compares the
DERIVED text against its OWN SOURCE rather than against a fact snapshot: the source
already carries the truth of which day each figure belongs to, so the question
"did the condensation keep the day?" needs no lookup, no clock and no I/O.

WHY NOT JUST RE-RUN THE #1968 GATE ON THE SUMMARY
--------------------------------------------------
`night_scope.night_scoped_vitals_findings` skips any sentence matching its modal
guard, and the published sentence opens "I can see your wearables data …" — "can" is
in that guard, so the sentence is skipped wholesale. Widening the modal guard would
change behaviour for every existing caller of the narrative gate; this check needs no
such change, because a figure the SOURCE dated is unambiguously a measured reading.
The residual (a narrative that states an undated reading inside a modal sentence) is
recorded in the PR for #2343 rather than silently absorbed here.

Pure — no boto3, no clock, no network. The metric vocabulary is imported from
`ai.night_scope`, never restated, so a metric added there is covered here for free.
"""

from ai import night_scope as _ns

# The two finding types this module emits, named once so callers can route them.
FINDING_TYPES = ("dropped_reading_date", "reading_date_mismatch")


def _claim_key(metric, value):
    """A figure's identity across two texts: the metric and the value as written."""
    return (metric, round(float(value), 4))


def _dated_claims(text, generation_date_iso=None):
    """`{(metric, value): night_iso}` for every vitals figure the text DATES."""
    dated = {}
    for metric, value, sentence in _ns.vital_claims_in(text):
        night, _how = _ns.night_named_in(sentence, generation_date_iso)
        if night:
            dated.setdefault(_claim_key(metric, value), night)
    return dated


def dropped_reading_date_findings(summary, *, source_text, generation_date_iso=None):
    """Deterministic day-correspondence check for a derived coach summary (#2343).

    Returns ``[{type, metric, claimed, ...}]`` — empty means the condensation kept
    every reading's day. Two classes:

    - ``"dropped_reading_date"`` — the SOURCE narrative states this exact figure and
      names the day it belongs to; the SUMMARY states the same figure with no day at
      all. That is the measured incident: a dated 2026-08-06 reading republished as a
      bare present-tense "Whoop shows 55% recovery" next to a cockpit serving 31%.
    - ``"reading_date_mismatch"`` — the summary names a DIFFERENT day than the source
      did for the same figure. Rarer, strictly worse (it asserts a wrong day rather
      than omitting one), and free to detect once the map above exists.

    A figure the source did not date is not adjudicated here: this check owns
    condensation fidelity only, and the narrative's own honesty is the #1968 gate's
    job. Unknown means unknown (ADR-104) — a guard must not invent an authority it
    does not have.
    """
    if not summary or not source_text:
        return []
    dated = _dated_claims(source_text, generation_date_iso)
    if not dated:
        return []
    findings = []
    seen = set()
    # skip_targets=False on the summary side only: every figure adjudicated below is one
    # the SOURCE already dated as a measured reading, so value-identity is the
    # discriminator and a target mentioned elsewhere in the sentence must not shield it
    # (the live card's vitals clause sat in the same sentence as "your 190g protein
    # target"). A restated target that reuses the number carries a temporal token in
    # practice ("aim for 7.5 hours tonight") and is filtered below.
    for metric, value, sentence in _ns.vital_claims_in(summary, skip_targets=False):
        key = _claim_key(metric, value)
        source_night = dated.get(key)
        if source_night is None:
            continue
        night, _how = _ns.night_named_in(sentence, generation_date_iso)
        snippet = sentence if len(sentence) <= 140 else sentence[:137].rstrip() + "…"
        if night is None:
            # Any temporal token at all means the writer gestured at a day; the
            # fabricated-date / weekday gates own those. Stay on the unambiguous case.
            if _ns.has_temporal_token(sentence):
                continue
            dedup = ("dropped", key)
            if dedup in seen:
                continue
            seen.add(dedup)
            findings.append(
                {
                    "type": "dropped_reading_date",
                    "metric": metric,
                    "claimed": key[1],
                    "source_night": source_night,
                    "detail": (
                        f"the summary states {metric} {key[1]:g} with no day on it "
                        f'("{snippet}"), but the narrative it was condensed from dates that exact '
                        f"reading to the night of {source_night} — a reader sees it as today's"
                    ),
                }
            )
        elif night != source_night:
            dedup = ("mismatch", key, night)
            if dedup in seen:
                continue
            seen.add(dedup)
            findings.append(
                {
                    "type": "reading_date_mismatch",
                    "metric": metric,
                    "claimed": key[1],
                    "source_night": source_night,
                    "summary_night": night,
                    "detail": (
                        f"the summary dates {metric} {key[1]:g} to {night} "
                        f'("{snippet}"), but the narrative dates that reading to {source_night}'
                    ),
                }
            )
    return findings


def summary_keeps_reading_dates(summary, *, source_text, generation_date_iso=None):
    """``(summary_or_None, rejected, findings)`` — the caller-facing seam.

    Mirrors `voice_register_guard.sanitize_summary` deliberately: on a finding the
    summary is REJECTED to ``None`` and both write paths fall back to the source text
    they already fall back to today. That fallback is the honest one here — the source
    narrative is the artifact that carries the day — so the guard needs no new read
    path and cannot leave a card blank.
    """
    findings = dropped_reading_date_findings(summary, source_text=source_text, generation_date_iso=generation_date_iso)
    if findings:
        return None, True, findings
    return summary, False, []


def guard_derived_summary(summary, source_text, field, coach_id=None, logger=None):
    """The whole write-path seam in one call: `summary` or `None`, with the warning logged.

    Both derived-summary writers (`coach_state_updater._write_output_record` for
    `observatory_summary`, `intelligence_common.extract_thread_from_narrative` for
    `position_summary`) apply this. It lives HERE rather than being restated at each
    call site so the two cannot drift, and so the two host modules — both at their
    #1665 size baseline — take three lines each instead of twenty.
    """
    if not summary:
        return summary
    cleaned, rejected, findings = summary_keeps_reading_dates(summary, source_text=source_text)
    if rejected and logger is not None:
        logger.warning("%s rejected for %s (#2343 reading-date fidelity) — %s", field, coach_id, [f["detail"] for f in findings][:3])
    return cleaned


# The item-8 extraction-prompt rider, kept beside the deterministic check it backstops.
# A prompt asking nicely is not a guarantee (ADR-105) — the guard above is the guarantee —
# but without the rider the model loses the day on most renders and the card falls back to
# a truncated narrative every time, which is honest and worse.
SUMMARY_DAY_CORRESPONDENCE_RULE = (
    "DAY CORRESPONDENCE (#2343): if the output dates a recovery, HRV, resting-HR or sleep figure to a specific "
    "night or date, the condensed version MUST keep that night or date attached to the figure. Never turn "
    "'Whoop caught 55% recovery on the night of 2026-08-06' into 'Whoop shows 55% recovery' — the card sits "
    "beside a cockpit publishing today's reading, so an undated figure reads as today's. Drop the figure "
    "entirely rather than drop its day. "
)
