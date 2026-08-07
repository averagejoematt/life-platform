"""behavior_logs.py — the #1699 ungrounded-behavioral gate + its availability derivations (#2056).

WHY IT IS ITS OWN MODULE
------------------------
Same two reasons `night_scope.py` gave one gate over (#1968), in the same order.

1. ENGINEERING_STANDARDS §2: `grounded_generation.py` sits at its 1,200-line ceiling and
   the module-size ratchet (#1665) is right to refuse the append. The gate moves here in
   full and `grounded_generation` re-exports it, so no caller's import changes.
2. This gate is the only one in the family whose INPUT is a lookup rather than the text —
   it needs a per-generation-date map of which behavior categories actually have a log.
   Deriving that map is real work with several honest shapes (a render payload, a stored
   presence signal, a domain snapshot's recency fields), and it belongs next to the gate
   that consumes it rather than smeared across nine callers. That is what #2056 is: the
   gate was armed on 1 of 15 grounding surfaces because 14 of them had nowhere to get the
   map from, and a guessed or empty map is WORSE than none — an empty set means "no logs
   today", so it flags every same-day behavioral claim on the surface.

THE COVERAGE CONTRACT (the #2056 change, and the reason more than one surface can arm)
--------------------------------------------------------------------------------------
Before this module, `available_logs` was a bare set and the gate read absence from it as
"no log exists". That is only sound when the caller can see EVERY category — the daily
brief's coach-v2 render can (it loads garmin, macrofactor, strava, journal), which is why
it was the one armed surface. Every other surface can honestly answer for SOME categories
and not others: the weekly narration's presence signal knows food/training/journal and has
never heard of steps; the integrator's per-domain snapshot knows its own domain only.

So availability is now two sets, not one — `LogAvailability(present, covered)`:

  * ``present``  — categories with a real log for the generation date.
  * ``covered``  — categories this caller can ANSWER for at all.

A category outside ``covered`` is UNKNOWN, and an unknown is never a finding. That is
ADR-104's behavioral-absence semantics applied to the gate's own input: absence of
evidence is not evidence of absence, and a gate that reports "ungrounded" when it simply
could not see is not a truth pass, it is noise that gets the gate switched off.

A plain iterable still means "full coverage" — the pre-#2056 contract, unchanged, so
coach-v2's armed behavior is bit-for-bit what it was.

THE DERIVATIONS (all pure — zero I/O, the caller owns every lookup)
------------------------------------------------------------------
`available_logs_from_presence` reads the stored engagement signal's ``channel_detail``
(the per-channel `last_log_date` `engagement_core.compute_presence` writes). It answers
by comparison, never by guess: a channel whose latest log IS the target date is present;
one whose latest log is strictly EARLIER had none that day; one whose latest log is LATER
is unknown, because the signal carries only the latest date and cannot say whether the
target day itself had one.

`available_logs_from_recency` reads the ``days_since_last_*`` fields a domain snapshot
already computed (`ai_expert_analyzer_lambda._recency_stats`). Zero means today.

Both return categories in `LOG_CATEGORIES` — the vocabulary the gate's claim patterns
speak. `steps`, `eating_window` and `fasting` are deliberately outside BOTH derivations:
steps come from a wearable that is not an engagement channel (and garmin is paused,
ADR-074), and no channel records an eating window at all. They stay uncovered rather than
being reported absent, which is exactly the distinction this module exists to make.
"""

import re
from typing import Iterable, NamedTuple, Optional, Union

# The log-category vocabulary. It is the contract between the claim patterns below and
# every caller's availability map — a category name that is not in here can never be
# `present`, and `tests/test_ungrounded_behavioral_gate.py` asserts the patterns and this
# tuple agree, so a new claim pattern cannot introduce a category no derivation knows.
LOG_CATEGORIES = ("eating_window", "fasting", "steps", "journal", "nutrition", "workout")


class LogAvailability(NamedTuple):
    """What a caller can honestly say about the generation date's behavior logs.

    ``present`` ⊆ ``covered``. A category in neither is UNKNOWN and is never flagged.
    Construct one with the derivations below, or directly when a caller has its own
    honest read; pass it to `ungrounded_behavioral_findings` / `grounding_findings`
    wherever a bare set used to go.
    """

    present: frozenset
    covered: frozenset

    @classmethod
    def full(cls, present: Iterable) -> "LogAvailability":
        """A caller that can see EVERY category — the pre-#2056 bare-set contract."""
        return cls(_norm(present), frozenset(LOG_CATEGORIES))

    @classmethod
    def none(cls) -> "LogAvailability":
        """Nothing answerable. Structurally identical to not arming the gate, and said
        out loud rather than by omission — a surface can hand this back on a bad read
        without the caller needing a branch."""
        return cls(frozenset(), frozenset())


def _norm(cats) -> frozenset:
    """Category tokens, lower-cased and stripped; anything outside the vocabulary drops.

    Dropping (rather than keeping) an unknown token matters: a stray token in `present`
    is harmless, but a stray token in `covered` would license a finding for a category no
    pattern can produce, so both sets are filtered through the one vocabulary.
    """
    return frozenset(c for c in (str(x).strip().lower() for x in (cats or ())) if c in LOG_CATEGORIES)


def as_availability(available_logs) -> Optional[LogAvailability]:
    """Normalize the gate's `available_logs` argument. None ⇒ None (caller opted out).

    A `LogAvailability` passes through; ANY other iterable is read as the pre-#2056
    full-coverage set, so every existing caller keeps its exact behavior.
    """
    if available_logs is None:
        return None
    if isinstance(available_logs, LogAvailability):
        return LogAvailability(_norm(available_logs.present), _norm(available_logs.covered))
    return LogAvailability.full(available_logs)


# ── Derivation 1: the stored presence signal (#914 engagement_core) ──────────
#
# `engagement_core.compute_presence` already writes, per MANUAL channel, the real
# `last_log_date` it observed. That is a per-date fact about actual log data, and every
# surface that renders a presence block has it in hand for free — which is what turns
# "no per-generation-date map at this layer" from a permanent exemption into a wiring
# job. The channel→category map is deliberately partial; see the module docstring.
PRESENCE_CHANNEL_CATEGORIES = {
    "macrofactor": "nutrition",  # the food channel (engagement_channel label "food")
    "hevy": "workout",  # the interactive training channel
    "notion": "journal",  # journal lives under notion (the registry's documented gotcha)
}


def available_logs_from_presence(signal, date_iso) -> LogAvailability:
    """`LogAvailability` for `date_iso` from an engagement_state STATE#current record.

    The signal must be at least as new as the date being asked about — a presence record
    computed BEFORE the target day cannot speak for it, so a stale read answers nothing
    rather than answering wrong.

    Per channel, using its `last_log_date`:
      * equal to `date_iso`            → present (covered)
      * earlier than `date_iso`        → absent  (covered) — the latest log predates the day
      * None, and `date_iso` is inside the signal's own observation window → absent (covered)
      * later than `date_iso`, or window unknown → UNKNOWN (not covered)

    The "later" case is the one that has to stay unknown: the record keeps only the most
    recent log date, so a channel that logged yesterday tells us nothing about whether it
    also logged the day before.
    """
    signal = signal if isinstance(signal, dict) else {}
    target = _iso(date_iso)
    signal_date = _iso(signal.get("date"))
    if not target or not signal_date or signal_date < target:
        return LogAvailability.none()
    window_start = _iso(signal.get("experiment_window_start"))
    detail = signal.get("channel_detail")
    detail = detail if isinstance(detail, dict) else {}

    present, covered = set(), set()
    for channel, category in PRESENCE_CHANNEL_CATEGORIES.items():
        entry = detail.get(channel)
        if not isinstance(entry, dict):
            continue  # the channel is not in this record at all — say nothing about it
        last = _iso(entry.get("last_log_date"))
        if last == target:
            present.add(category)
            covered.add(category)
        elif last is not None and last < target:
            covered.add(category)
        elif last is None and window_start is not None and window_start <= target:
            # Nothing logged anywhere in the observed window, and the target day is
            # inside it — that IS an answer, and the honest one is "no log".
            covered.add(category)
    return LogAvailability(_norm(present), _norm(covered))


# ── Derivation 2: a domain snapshot's recency fields ─────────────────────────
#
# The integrator's per-expert snapshots already carry `days_since_last_<thing>` computed
# from the DDB rows the render queried (ai_expert_analyzer_lambda._recency_stats). Zero
# means "logged on the reference day", which is precisely the availability question. The
# fields are per-domain, so coverage varies by expert — a nutrition snapshot answers for
# nutrition and stays silent about training. That IS the partial-coverage case.
RECENCY_FIELD_CATEGORIES = {
    "days_since_last_food_log": "nutrition",
    "days_since_last_journal": "journal",
    "days_since_last_lift": "workout",
}


def available_logs_from_recency(data) -> LogAvailability:
    """`LogAvailability` from a snapshot's `days_since_last_*` fields.

    ``0`` ⇒ logged on the snapshot's reference day (present). Any positive number ⇒ the
    most recent log is older than that day (absent). ``None`` ⇒ the recency helper found
    nothing in its whole lookback window, which is also absent — the honest read of "no
    log in 30 days" is not "unknown". A field the snapshot does not carry is uncovered.
    """
    data = data if isinstance(data, dict) else {}
    present, covered = set(), set()
    for field, category in RECENCY_FIELD_CATEGORIES.items():
        if field not in data:
            continue
        days = data.get(field)
        if days is None:
            covered.add(category)
            continue
        try:
            n = int(float(days))
        except (TypeError, ValueError):
            continue  # unparseable → say nothing rather than guess
        covered.add(category)
        if n == 0:
            present.add(category)
    return LogAvailability(_norm(present), _norm(covered))


def _iso(value):
    """A 'YYYY-MM-DD' prefix, or None. Comparison is lexicographic and exact for ISO."""
    s = str(value or "")[:10]
    return s if len(s) == 10 and s[4] == "-" and s[7] == "-" else None


# ── Ungrounded-behavioral gate (#1699, epic #1687) ───────────────────────────
# A coach asserting a COMPLETED behavior about the generation day ("you maintained
# your eating window today", "you hit your steps", "you journaled today") when NO
# corresponding log exists for that day is an ungrounded behavioral claim — a
# hallucinated behavior the DATA-grounding gates cannot see (there is no number to
# check; the assertion is about an ACTION, not a figure). This is the
# `ungrounded-behavioral` error-class in coach_corrections.ERROR_CLASSES, and the
# mind coach's 2026-07-22 "you maintained your eating window today" (no log) is its
# canonical instance.
#
# The check is deterministic and log-aware: each behavioral claim maps to a LOG
# CATEGORY, and a same-day claim whose category is COVERED but ABSENT flags. The
# availability map is caller-supplied — the function does ZERO I/O and stays pure,
# exactly the #1691 discipline. The generation-date scoping is LOAD-BEARING: the map is
# a point-in-time read for TODAY, so only a claim tied to a same-day framing token
# ("today", "this morning", …) is checked; a past-tense reference to a prior period
# ("last week you hit your steps") is out of scope and never flags. A modal /
# conditional / future framing ("if you keep your window today", "try to hit your
# steps") is advice, not a completed-action claim, and is likewise skipped.

# Same-day framing — a claim is checked only when one of these appears in its sentence.
_UB_TODAY_RE = re.compile(
    r"\b(today|todays|this\s+morning|this\s+afternoon|this\s+evening|tonight|so\s+far\s+today|as\s+of\s+today|right\s+now)\b",
    re.IGNORECASE,
)
# Second-person — the claim must be about Matthew ("you"/"your"), never the coach itself.
# This is also why several grounding surfaces stay exempt from the class rather than
# arming it: on the reader-facing board and /api/ask, "you" is the READER, and on the
# inter-coach dialogue it is the other coach — neither is a claim about Matthew's logs.
_UB_SECOND_PERSON_RE = re.compile(r"\byou(?:r|'ve|'ll|'d)?\b", re.IGNORECASE)
# Modal / conditional / future markers that turn a behavioral verb into advice, not a
# claim of a completed action. Deliberately EXCLUDES a bare "to" (it would swallow the
# legitimate "stuck to your window today" completed-action verb form).
_UB_MODAL_RE = re.compile(
    r"\b(could|should|would|can|will|might|may|must|need\s+to|want\s+to|try(?:ing)?\s+to|"
    r"let'?s|if\s+you|when\s+you|keep\s+(?:up|on|going)|make\s+sure|aim\s+to|remember\s+to)\b",
    re.IGNORECASE,
)
_UB_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")

# Each pattern pairs a "verb + activity" behavioral assertion with the LOG CATEGORY
# that would substantiate it. Kept tight (verb near its activity noun) to hold down
# false positives; the modal guard above drops advice framings. Category vocabulary is
# LOG_CATEGORIES — the contract with the caller's availability map.
_UB_CLAIM_PATTERNS = [
    # eating / fasting window adherence
    (
        "eating_window",
        re.compile(
            r"\b(?:maintained|kept|held|stuck\s+(?:to|with)|hit|nailed|closed|sustained|followed)\b"
            r"[^.]{0,40}?\b(?:eating|fasting|feeding)\s+window\b",
            re.IGNORECASE,
        ),
    ),
    (
        "fasting",
        re.compile(
            r"\b(?:maintained|kept|held|completed|finished|nailed|hit)\b" r"[^.]{0,30}?\b(?:\d+\s*[- ]?hour\s+)?fast(?:ed|ing)?\b",
            re.IGNORECASE,
        ),
    ),
    # step target
    (
        "steps",
        re.compile(
            r"\b(?:hit|nailed|crushed|logged|reached|racked\s+up|got|smashed|closed)\b" r"[^.]{0,30}?\bsteps?\b",
            re.IGNORECASE,
        ),
    ),
    # journaling
    ("journal", re.compile(r"\bjournal(?:ed|led|ing)\b", re.IGNORECASE)),
    (
        "journal",
        re.compile(r"\b(?:wrote|filled\s+out|completed|logged|finished)\b[^.]{0,25}?\bjournal\b", re.IGNORECASE),
    ),
    # nutrition logging / calorie or macro adherence
    (
        "nutrition",
        re.compile(
            r"\b(?:logged|tracked|recorded)\b[^.]{0,25}?\b(?:meal|meals|food|nutrition|macros?|calories?|protein)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "nutrition",
        re.compile(
            r"\b(?:stayed|came\s+in|landed)\s+under\b[^.]{0,30}?\b(?:calorie|calories|deficit|target|budget|maintenance)\b",
            re.IGNORECASE,
        ),
    ),
    # workout / training completion
    (
        "workout",
        re.compile(
            r"\b(?:completed|finished|crushed|logged|did|nailed|knocked\s+out)\b"
            r"[^.]{0,30}?\b(?:workout|training\s+session|lift(?:ing)?|strength\s+session|gym\s+session)\b",
            re.IGNORECASE,
        ),
    ),
]


def ungrounded_behavioral_findings(text: str, *, available_logs: Union[Iterable, LogAvailability, None]) -> list:
    """Deterministic, zero-AI ungrounded-behavioral check for coach output (#1699).

    Flags a same-day COMPLETED-behavior assertion whose supporting LOG CATEGORY is
    covered by the caller's availability map and absent from it — "you maintained your
    eating window today" with no eating-window record, "you hit your steps today" with no
    step log. Each finding is the shared ``{"type": ..., "detail": ...}`` shape (type
    ``"ungrounded_behavioral"``, plus ``category`` and ``claim``) so it composes with
    grounding_findings() / correction_prompt().

    `available_logs` is REQUIRED and caller-supplied. Two accepted shapes:

      * a set/iterable of category tokens — FULL coverage (the pre-#2056 contract): an
        empty set means "no logs today", so every same-day behavioral claim flags;
      * a `LogAvailability` — declared partial coverage (#2056): only categories in
        ``covered`` can flag, and an uncovered one is unknown, never a finding.

    Passing ``None`` returns [] (the caller opted out). The function does no I/O and
    stays pure — the caller owns the availability lookup.

    Scoping (all three must hold for a sentence to be checked): it addresses Matthew
    ("you"/"your"), it carries a same-day framing token ("today"/"this morning"/…),
    and it is NOT modal/conditional/future (advice is not a completed-action claim).
    """
    text = text or ""
    avail = as_availability(available_logs)
    if avail is None:
        return []
    findings = []
    seen = set()
    for raw in _UB_SENTENCE_SPLIT_RE.split(text.strip()):
        sent = raw.strip()
        if not sent:
            continue
        if not _UB_SECOND_PERSON_RE.search(sent):
            continue
        if not _UB_TODAY_RE.search(sent):  # only same-day claims are checkable against today's logs
            continue
        if _UB_MODAL_RE.search(sent):  # advice / conditional / future — not a completed action
            continue
        for category, rx in _UB_CLAIM_PATTERNS:
            m = rx.search(sent)
            if not m:
                continue
            if category not in avail.covered:  # the caller cannot see this category → unknown, not absent
                continue
            if category in avail.present:  # a real log substantiates it → grounded, no finding
                continue
            key = (category, m.group(0).lower())
            if key in seen:
                continue
            seen.add(key)
            snippet = sent if len(sent) <= 140 else sent[:137].rstrip() + "…"
            findings.append(
                {
                    "type": "ungrounded_behavioral",
                    "category": category,
                    "claim": m.group(0).strip(),
                    "detail": (
                        f'the narrative asserts a same-day "{category}" behavior ("{snippet}"), '
                        f"but no {category} log exists for the generation date"
                    ),
                }
            )
    return findings
