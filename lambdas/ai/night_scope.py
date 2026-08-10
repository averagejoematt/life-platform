"""night_scope.py — the #1968 night-scope gate (epic #1890), split out of grounded_generation.

WHY IT IS ITS OWN MODULE
------------------------
Two reasons, and the second is the real one.

1. ENGINEERING_STANDARDS §2: `grounded_generation.py` sits at 1,179 of its 1,200-line
   ceiling, and this gate is ~260 lines. The module-size ratchet (#1665) is right to
   refuse the append.
2. It is the only gate in the family that is meaningful AFTER generation. Every other
   class in `grounding_findings` compares a draft against one snapshot of the facts
   taken while the model was writing; this one asks a question a serve-time caller can
   re-ask a week later ("does this figure still match the night it names?"). Giving it
   its own import surface is what lets the site API and the QA sweep use it without
   pulling in the whole generation harness.

WHAT IT CHECKS
--------------
Measured on 2026-07-27 (/fullreview, both verifiers): the whoop row's `sleep_end` was
14:22Z and the coach rendered at 14:02Z, so the packet was an earlier partial-night
revision of the SAME record — quality 86 / deep 17.6% / REM 30.3% against a final row of
83 / 24.2% / 22.0%. The hourly ingestion revised the night upward and nothing
regenerated. A canary asking "did the packet match canonical AT GENERATION TIME?" would
have PASSED. Meanwhile the integrator credited "a 7.5-hour sleep" with no night on it at
all — a figure no reader and no checker can reconcile against anything.

So: name the night (`unlabeled_night_figure`), and re-check the named night against what
is stored now (`night_value_mismatch`). Deterministic, zero-AI, no I/O — the caller owns
every lookup, which is what keeps it usable at serve time where Bedrock spend is not
available (ADR-063/125 budget tiers).

Frame: #1923's. Sleep/recovery/HRV/RHR are WAKE-DATE-KEYED, so the night behind a wake
date is `wake_date - 1`. `tests/test_night_scoped_vitals_1968.py` asserts this module,
`web.site_api_common` and `experiment.canonical_facts` all agree on that offset.
"""

import datetime as _dt
import re

# Sentence splitting and the modal guard mirror grounded_generation's #1699 gate — one
# regex each, deliberately restated rather than imported so this module stays standalone
# and the import graph stays one-way (grounded_generation imports THIS, never the
# reverse). `dates_in_text` is the one real dependency and is imported lazily below.
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
_MODAL_RE = re.compile(
    r"\b(could|should|would|can|will|might|may|must|need\s+to|want\s+to|try(?:ing)?\s+to|"
    r"let'?s|if\s+you|when\s+you|keep\s+(?:up|on|going)|make\s+sure|aim\s+to|remember\s+to)\b",
    re.IGNORECASE,
)
_MONTH_NAMES = "january|february|march|april|may|june|july|august|september|october|november|december"
_WEEKDAY_NAMES = "monday|tuesday|wednesday|thursday|friday|saturday|sunday"

# The two finding types this module emits, named once so `correction_prompt` can route
# them without restating the literals.
FINDING_TYPES = ("unlabeled_night_figure", "night_value_mismatch")


def _dates_in(sentence):
    """Full calendar dates in a sentence, ISO-normalized (lazy import — no cycle)."""
    try:
        from ai.grounded_generation import dates_in_text
    except ImportError:  # pragma: no cover — flat/layer bundle layout
        from grounded_generation import dates_in_text
    return dates_in_text(sentence)


NIGHT_OF_OFFSET_DAYS = 1


def night_of_for_wake_date(wake_date_iso):
    """The night a wake-date-keyed reading came from: `wake_date` minus one day (#1923).

    The lambdas/ai mirror of `web.site_api_common.night_of_for` — same offset, same
    "None rather than a guess" contract. It is duplicated rather than imported
    because this module is deliberately pure (no boto3), and importing the web
    package would drag the whole serve-path import graph into every AI bundle.
    `tests/test_night_scoped_vitals_1968.py` asserts the two agree, so the frame
    cannot fork the way the `_Nd` field families once did.
    """
    try:
        d = _dt.date.fromisoformat(str(wake_date_iso)[:10])
    except (TypeError, ValueError):
        return None
    return (d - _dt.timedelta(days=NIGHT_OF_OFFSET_DAYS)).isoformat()


# The metric vocabulary. Each entry: the claim patterns (number in group "n"), the
# match tolerance, and the unit label used in the finding text. Tolerances are the
# published precision of the surfaces themselves, not guesses: /api/sleep_detail
# rounds hours to 0.1 and percentages to 0.1, so a 0.25h / 2.0-point band absorbs
# rounding and unit-conversion slop while still catching the measured incident
# (6.58h vs 8.9h; quality 86 vs 83; deep 17.6% vs 24.2%).
_NIGHT_METRICS: dict = {
    "sleep_hours": {
        "unit": "hours",
        # An hours-figure is only read as a SLEEP duration inside a sleep sentence.
        # Without this, "you rode 2.5 hours" in a training brief would be graded
        # against last night's sleep — the gate has to be narrower than the noun.
        "context": re.compile(r"\b(?:sleep|slept|asleep|night|nights|bed|in\s+bed|rem|deep)\b", re.IGNORECASE),
        "tolerance": 0.25,
        "patterns": (
            re.compile(r"\b(?P<n>\d+(?:\.\d+)?)[\s-]*(?:hours?|hrs?)\b(?:[^.!?]{0,20}?\b(?:of\s+)?sleep\b|\s+asleep\b)", re.IGNORECASE),
            re.compile(r"\bslept\b[^.!?]{0,15}?\b(?P<n>\d+(?:\.\d+)?)[\s-]*(?:hours?|hrs?)\b", re.IGNORECASE),
            re.compile(
                r"\b(?:duration|total|time\s+in\s+bed|asleep\s+for)\b\D{0,15}(?P<n>\d+(?:\.\d+)?)[\s-]*(?:hours?|hrs?|h)\b",
                re.IGNORECASE,
            ),
            re.compile(r"\b(?P<n>\d+(?:\.\d+)?)[\s-]*(?:hours?|hrs?)\b", re.IGNORECASE),
        ),
    },
    "sleep_efficiency_pct": {
        "unit": "%",
        "tolerance": 2.0,
        "patterns": (
            re.compile(r"\befficiency\b\D{0,12}(?P<n>\d+(?:\.\d+)?)\s*%?", re.IGNORECASE),
            re.compile(r"\b(?P<n>\d+(?:\.\d+)?)\s*%\s+(?:sleep\s+)?efficiency\b", re.IGNORECASE),
        ),
    },
    "recovery_pct": {
        "unit": "%",
        "tolerance": 2.0,
        "patterns": (
            re.compile(r"\brecovery\b\D{0,12}(?P<n>\d+(?:\.\d+)?)\s*%?", re.IGNORECASE),
            re.compile(r"\b(?P<n>\d+(?:\.\d+)?)\s*%\s+recovery\b", re.IGNORECASE),
        ),
    },
    "hrv_ms": {
        "unit": "ms",
        "tolerance": 2.0,
        "patterns": (
            re.compile(r"\bHRV\b\D{0,12}(?P<n>\d+(?:\.\d+)?)", re.IGNORECASE),
            re.compile(r"\b(?P<n>\d+(?:\.\d+)?)\s*ms\b[^.!?]{0,12}?\bHRV\b", re.IGNORECASE),
        ),
    },
    "rhr_bpm": {
        "unit": "bpm",
        "tolerance": 2.0,
        "patterns": (
            re.compile(r"\bresting\s+(?:heart\s+rate|HR)\b\D{0,12}(?P<n>\d+(?:\.\d+)?)", re.IGNORECASE),
            re.compile(r"\b(?P<n>\d+(?:\.\d+)?)\s*bpm\b[^.!?]{0,20}?\bresting\b", re.IGNORECASE),
        ),
    },
    "sleep_score": {
        "unit": "points",
        "tolerance": 2.0,
        "patterns": (
            re.compile(r"\bsleep\s+(?:score|quality)\b\D{0,12}(?P<n>\d+(?:\.\d+)?)", re.IGNORECASE),
            re.compile(r"\bquality\s+(?:score\s+)?(?:of|at)\s+(?P<n>\d+(?:\.\d+)?)", re.IGNORECASE),
        ),
    },
}

# A relative frame is a night NAME only when the caller anchors it with a generation
# date. "last night" in a dated daily brief is perfectly reconcilable; the same words
# in an archived chronicle read a week later are not, which is why the anchor is the
# caller's to supply rather than something this function assumes.
_REL_LAST_NIGHT_RE = re.compile(
    r"\b(?:last\s+night|overnight|this\s+morning|last\s+night'?s|the\s+night\s+just\s+past)\b",
    re.IGNORECASE,
)
# A "no night at all" figure is the (a) defect. Any temporal token at all — a month
# name, a weekday, a bare ordinal — means the writer at least gestured at a night, and
# the fabricated-date/weekday gates own those. This gate stays on the unambiguous case.
_ANY_TEMPORAL_TOKEN_RE = re.compile(
    r"\b(?:" + _MONTH_NAMES + r"|" + _WEEKDAY_NAMES + r"|yesterday|tonight|" r"night\s+of|the\s+\d{1,2}(?:st|nd|rd|th))\b",
    re.IGNORECASE,
)


# A prescription is not a reading. "Aim for 8 hours tonight" states a TARGET, and the
# #1968 incident had a target-anchored figure in it (the integrator's unlabeled "7.5-hour
# sleep" is exactly the 7.5h target on /method/game/), so a gate that graded targets as
# readings would flag correct advice constantly and get switched off. The modal guard is
# shared with the #1699 behavioral gate — same reasoning, same words.
_NSV_TARGET_RE = re.compile(
    r"\b(?:target(?:ing)?|goal|aim(?:ing)?\s+for|shoot(?:ing)?\s+for|try\s+for|push\s+for|prescription|protocol\s+calls)\b",
    re.IGNORECASE,
)


def _night_named_in(sentence: str, generation_date_iso=None):
    """(night_iso, how) for a sentence, or (None, None) when it names no night.

    Precedence: an explicit full calendar date wins (it is unambiguous and survives
    archiving); a relative frame resolves only against a supplied generation date.
    A sentence naming two different full dates is deliberately treated as UNRESOLVED
    rather than guessed at — "the 4th was worse than the 5th" is a comparison, and
    picking one of them would invent an attribution.
    """
    dates = _dates_in(sentence)
    if len(dates) == 1:
        return sorted(dates)[0], "explicit_date"
    if dates:
        return None, "ambiguous"
    if generation_date_iso and _REL_LAST_NIGHT_RE.search(sentence):
        return night_of_for_wake_date(generation_date_iso), "relative_frame"
    return None, None


def night_scoped_vitals_findings(text: str, *, nightly_vitals, generation_date_iso: str = None) -> list:
    """Deterministic night-scope check for narrative vitals figures (#1968).

    Two finding classes, both zero-AI:

    - ``"unlabeled_night_figure"`` — a sleep/recovery/HRV/RHR figure that names no
      night and carries no temporal token at all ("credits a 7.5-hour sleep"). A
      reader cannot reconcile it and neither can a checker; it is unfalsifiable.
    - ``"night_value_mismatch"`` — a figure that DOES name its night (explicitly, or
      via a relative frame resolved against ``generation_date_iso``) and disagrees
      with that night's stored value beyond the metric's tolerance. This is the
      revision detector: run at serve time against today's stored vitals, it catches
      a figure that was correct when written and became wrong when the wearable
      finalized the record.

    ``nightly_vitals`` is REQUIRED and caller-supplied — ``{night_iso: {metric: value}}``
    keyed by NIGHT (use ``night_of_for_wake_date()`` to convert wake-date-keyed rows).
    Passing ``None`` returns ``[]``: the caller has opted out, the same contract
    ``available_logs`` (#1699) and ``evaluated_predictions`` (#1896) use. An empty dict
    still arms the unlabeled-figure class — "I hold no vitals" does not make an
    unlabeled figure reconcilable. The function does no I/O and stays pure.

    A named night that is ABSENT from ``nightly_vitals`` is not a finding: this gate
    does not adjudicate whether a date is legitimate (``fabricated_dates`` does), and
    silently flagging every night outside the caller's window would punish correct
    history. Unknown means unknown (ADR-104).
    """
    if nightly_vitals is None:
        return []
    by_night = {str(k)[:10]: (v or {}) for k, v in dict(nightly_vitals).items()}
    findings = []
    seen = set()
    for raw in _SENTENCE_SPLIT_RE.split((text or "").strip()):
        sent = raw.strip()
        if not sent:
            continue
        if _NSV_TARGET_RE.search(sent) or _MODAL_RE.search(sent):
            continue  # a target/advice sentence is not a claim about a measured night
        night, how = _night_named_in(sent, generation_date_iso)
        for metric, spec in _NIGHT_METRICS.items():
            ctx = spec.get("context")
            if ctx is not None and not ctx.search(sent):
                continue
            for rx in spec["patterns"]:
                m = rx.search(sent)
                if not m:
                    continue
                try:
                    claimed = round(float(m.group("n")), 4)
                except (TypeError, ValueError):
                    continue
                snippet = sent if len(sent) <= 140 else sent[:137].rstrip() + "…"
                if night is None:
                    key = ("unlabeled", metric, claimed)
                    if key in seen or _ANY_TEMPORAL_TOKEN_RE.search(sent):
                        break
                    seen.add(key)
                    findings.append(
                        {
                            "type": "unlabeled_night_figure",
                            "metric": metric,
                            "claimed": claimed,
                            "detail": (
                                f'the narrative states a {metric} figure of {claimed:g} {spec["unit"]} ("{snippet}") '
                                f"without naming the night it describes — a reader cannot reconcile it against "
                                f"any stored record"
                            ),
                        }
                    )
                    break
                stored = by_night.get(night, {}).get(metric)
                if stored is None:
                    break
                try:
                    stored_f = float(stored)
                except (TypeError, ValueError):
                    break
                if abs(claimed - stored_f) <= spec["tolerance"]:
                    break
                key = ("mismatch", metric, night, claimed)
                if key in seen:
                    break
                seen.add(key)
                findings.append(
                    {
                        "type": "night_value_mismatch",
                        "metric": metric,
                        "night": night,
                        "night_source": how,
                        "claimed": claimed,
                        "stored": round(stored_f, 4),
                        "tolerance": spec["tolerance"],
                        "detail": (
                            f'the narrative states {metric} {claimed:g} {spec["unit"]} for the night of {night} '
                            f'("{snippet}"), but the stored record for that night holds {stored_f:g} '
                            f'{spec["unit"]} — beyond the {spec["tolerance"]:g} {spec["unit"]} tolerance'
                        ),
                    }
                )
                break
    return findings


# ── public seams for sibling gates (#2343) ───────────────────────────────────
#
# `coach.reading_date_fidelity` asks a DIFFERENT question of the same vocabulary
# ("did a derived summary keep the day its source gave a figure?"), and it must ask
# it with the same metric patterns and the same night-naming rules or the two gates
# drift apart. Exposing the three seams here — rather than letting the sibling reach
# for `_NIGHT_METRICS` — is what keeps a metric added above covered in both places
# for free (guard the SET, not the instance).


def night_named_in(sentence: str, generation_date_iso: str = None):
    """`(night_iso, how)` for a sentence, or `(None, None)` — see `_night_named_in`."""
    return _night_named_in(sentence, generation_date_iso)


def has_temporal_token(sentence: str) -> bool:
    """True when the sentence gestures at a day at all (month, weekday, 'yesterday', …)."""
    return bool(_ANY_TEMPORAL_TOKEN_RE.search(sentence or ""))


def vital_claims_in(text: str, *, skip_targets: bool = True):
    """`[(metric, value, sentence)]` — every vitals figure stated in `text`.

    The MODAL guard is deliberately NOT applied: it exists to stop the night gate
    grading advice as a claim, but "I can see your wearables data — Whoop shows 55%
    recovery" is a statement of a measured reading that happens to contain "can", and
    skipping it is exactly how #2343 stayed invisible. Callers that need the modal
    guard use `night_scoped_vitals_findings`, which still applies it.

    `skip_targets` drops target/prescription sentences (a target is not a reading —
    the #1968 reasoning verbatim). It is the right default for anything establishing
    what a text CLAIMS to have measured. #2343's summary side passes False: that check
    only adjudicates a figure whose value the SOURCE already dated as a reading, and
    the live sentence — "Whoop shows 55% recovery and HRV at 42 ms — but without meal
    logs, I can't assess whether your 190g protein target is …" — was dropped whole
    because of a protein target mentioned two clauses away from the vitals.
    """
    claims = []
    for raw in _SENTENCE_SPLIT_RE.split((text or "").strip()):
        sent = raw.strip()
        if not sent or (skip_targets and _NSV_TARGET_RE.search(sent)):
            continue
        for metric, spec in _NIGHT_METRICS.items():
            ctx = spec.get("context")
            if ctx is not None and not ctx.search(sent):
                continue
            # EVERY pattern is tried, not just the first that hits. The night gate stops
            # at the first match because it only needs one figure to adjudicate; a
            # fidelity check needs the real one. "Whoop shows 55% recovery and HRV at 42
            # ms" makes the leading `recovery\b\D{0,12}(\d+)` pattern read 42 (it reaches
            # past "and HRV at" to the next number) and the correct `55% recovery`
            # pattern never gets a turn. Collecting both costs nothing — a value the
            # source never dated is simply not adjudicated.
            for rx in spec["patterns"]:
                m = rx.search(sent)
                if not m:
                    continue
                try:
                    claim = (metric, round(float(m.group("n")), 4), sent)
                except (TypeError, ValueError):
                    continue
                if claim not in claims:
                    claims.append(claim)
    return claims


# ── caller helpers: the ways a night map / a night label gets built ──────────


def nightly_vitals_from_facts(facts) -> dict:
    """`{night: {metric: value}}` from a `canonical_facts` dict — the zero-I/O arming.

    Any surface already grounded on canonical facts can arm the gate with this and no
    new lookup: the facts carry `night_of` (#1968) plus the three observed vitals. The
    map deliberately holds NO sleep duration — that record has none — which is exactly
    right: an unlabeled duration figure still trips the label class, and only figures
    the facts can actually adjudicate are compared.

    Returns `{}` when there is no night to key on, which the gate treats as "arm the
    label class, adjudicate nothing" rather than as an opt-out.
    """
    facts = facts or {}
    night = facts.get("night_of")
    if not night:
        return {}
    vals = {k: facts.get(k) for k in ("recovery_pct", "hrv_ms", "rhr_bpm") if facts.get(k) is not None}
    return {night: vals}


def nightly_vitals_from_narrative(text, generation_date_iso=None) -> dict:
    """`{night: {metric: value}}` from a narrative's OWN DATED claims (#2418).

    `nightly_vitals_from_facts` arms a GENERATOR against the fact snapshot it was
    handed. A gate on a text that was CONDENSED from an already-gated narrative has a
    different and better authority available: the source narrative itself. It passed
    its own #1968 gate, and it carries the night each figure belongs to — so grading
    the condensation against it asks exactly the right question ("did the shorter text
    keep the reading and its night?") with no lookup, no clock and no I/O.

    A figure the source never dated contributes nothing to the map. That is the honest
    behaviour and not a gap: the `unlabeled_night_figure` class still asks the
    condensation to name a night, and this helper refuses to invent an adjudicating
    authority the source did not have (ADR-104 — unknown means unknown).

    Only the FIRST dated value per (night, metric) is kept: a narrative that walks a
    week night by night states many recovery figures, and the map's job is to answer
    "what does the source say this night's value was", not to merge them.
    """
    night_map: dict = {}
    for metric, value, sentence in vital_claims_in(text):
        night, _how = night_named_in(sentence, generation_date_iso)
        if night:
            night_map.setdefault(night, {}).setdefault(metric, value)
    return night_map


def night_label_line(facts) -> str:
    """The AUTHORITATIVE-FACTS line naming the night the vitals describe, or "".

    Rendered ONLY when a night-scoped vital actually survives into the fact set: a night
    label above an empty vitals set would be a scope for nothing, and pre-genesis facts
    are withheld on purpose (#2113) — labeling withheld values would undo that.
    """
    facts = facts or {}
    if facts.get("facts_are_pre_genesis"):
        return ""
    night = facts.get("night_of") or night_of_for_wake_date(facts.get("as_of"))
    if not night or not any(facts.get(k) is not None for k in ("recovery_pct", "hrv_ms", "rhr_bpm")):
        return ""
    return (
        f"  - THE NIGHT THESE DESCRIBE: {night}. The recovery, HRV and resting-HR figures below are "
        f"the readings from the night of {night} (recorded against the morning of {facts.get('as_of')}). "
        f'When you cite ANY of them, name that night — "on the night of {night}" — never a bare '
        f'"your recovery" or "last night" with no date. A figure that does not say which night it '
        f"belongs to cannot be checked by a reader or by the grounding gate."
    )


def correction_line(finding) -> str:
    """The corrective instruction for one #1968 finding (used by `correction_prompt`)."""
    if finding.get("type") == "night_value_mismatch":
        return (
            f"{finding['detail']}. Use {finding['stored']:g} for the night of {finding['night']}, or "
            f"describe it qualitatively — never carry a figure the stored record has since revised."
        )
    return (
        f"{finding['detail']}. Name the night explicitly (\"the night of <date>\") or drop the figure — "
        f"a sleep, recovery, HRV or resting-HR number that does not say which night it belongs to "
        f"cannot be checked by anyone."
    )
