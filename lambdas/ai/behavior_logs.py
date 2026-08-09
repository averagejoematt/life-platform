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

import datetime
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

    ``last_dates`` (#2382) carries the THIRD fact the two sets cannot express. Sets
    answer "was there a log on the generation date?"; they cannot tell "he logged and
    then STOPPED four days ago" apart from "he has never logged in this window at all".
    That distinction is a different sentence — the first is a transition that happened,
    the second is an absence with no event in it — and the platform narrated the wrong
    one on six live coach cards (#2382). It is stored as a frozenset of
    ``(category, iso_or_None)`` pairs so the tuple stays hashable and comparable:

      * a pair ``(cat, "YYYY-MM-DD")`` — the real last log date this caller observed;
      * a pair ``(cat, None)``        — KNOWN to have no log anywhere in the observed
        window (the never-logged case), which is an answer, not an absence of one;
      * no pair at all                — unknown, and unknown never licenses a claim.

    Read it through `last_date()` / `knows_last_date()`, never by indexing the raw set.
    """

    present: frozenset
    covered: frozenset
    last_dates: frozenset = frozenset()

    @classmethod
    def full(cls, present: Iterable, last_dates=None) -> "LogAvailability":
        """A caller that can see EVERY category — the pre-#2056 bare-set contract."""
        return cls(_norm(present), frozenset(LOG_CATEGORIES), _norm_dates(last_dates))

    @classmethod
    def none(cls) -> "LogAvailability":
        """Nothing answerable. Structurally identical to not arming the gate, and said
        out loud rather than by omission — a surface can hand this back on a bad read
        without the caller needing a branch."""
        return cls(frozenset(), frozenset(), frozenset())

    def knows_last_date(self, category) -> bool:
        """True when this caller can answer "when was the last <category> log?" at all.

        False is UNKNOWN — the #2056 semantics applied to dates. It is deliberately
        distinct from `last_date(category) is None`, which is the KNOWN never-logged
        answer; collapsing the two is the exact bug #2382 is about.
        """
        cat = str(category or "").strip().lower()
        return any(c == cat for c, _ in self.last_dates)

    def last_date(self, category) -> Optional[str]:
        """The observed last-log ISO date for `category`; None when never logged in the
        window OR when unknown. Always pair it with `knows_last_date()`."""
        cat = str(category or "").strip().lower()
        for c, d in self.last_dates:
            if c == cat:
                return d
        return None


def _norm(cats) -> frozenset:
    """Category tokens, lower-cased and stripped; anything outside the vocabulary drops.

    Dropping (rather than keeping) an unknown token matters: a stray token in `present`
    is harmless, but a stray token in `covered` would license a finding for a category no
    pattern can produce, so both sets are filtered through the one vocabulary.
    """
    return frozenset(c for c in (str(x).strip().lower() for x in (cats or ())) if c in LOG_CATEGORIES)


def _norm_dates(pairs) -> frozenset:
    """`(category, iso_or_None)` pairs, filtered through the one vocabulary.

    Same discipline as `_norm`: a token outside LOG_CATEGORIES drops, and an
    unparseable date degrades to *unknown* (the pair drops) rather than to the
    never-logged answer — guessing "never" from junk would manufacture the very
    certainty this field exists to withhold.
    """
    if isinstance(pairs, dict):
        pairs = pairs.items()
    out: dict[str, str | None] = {}
    for item in pairs or ():
        try:
            cat, value = item
        except (TypeError, ValueError):
            continue
        cat = str(cat or "").strip().lower()
        if cat not in LOG_CATEGORIES:
            continue
        if value is None:
            out[cat] = None
            continue
        iso = _iso(value)
        if iso is not None:
            out[cat] = iso
    return frozenset(out.items())


def as_availability(available_logs) -> Optional[LogAvailability]:
    """Normalize the gate's `available_logs` argument. None ⇒ None (caller opted out).

    A `LogAvailability` passes through; ANY other iterable is read as the pre-#2056
    full-coverage set, so every existing caller keeps its exact behavior.
    """
    if available_logs is None:
        return None
    if isinstance(available_logs, LogAvailability):
        return LogAvailability(
            _norm(available_logs.present),
            _norm(available_logs.covered),
            _norm_dates(available_logs.last_dates),
        )
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
    dates: dict[str, str | None] = {}
    for channel, category in PRESENCE_CHANNEL_CATEGORIES.items():
        entry = detail.get(channel)
        if not isinstance(entry, dict):
            continue  # the channel is not in this record at all — say nothing about it
        last = _iso(entry.get("last_log_date"))
        if last == target:
            present.add(category)
            covered.add(category)
            dates[category] = last
        elif last is not None and last < target:
            covered.add(category)
            dates[category] = last
        elif last is None and window_start is not None and window_start <= target:
            # Nothing logged anywhere in the observed window, and the target day is
            # inside it — that IS an answer, and the honest one is "no log". #2382:
            # record it as the KNOWN never-logged date (None), not as unknown — the
            # absence-transition derivation needs to tell those two apart.
            covered.add(category)
            dates[category] = None
        elif last is not None:
            # `last` is LATER than the target day. The set answer stays unknown (the
            # record cannot say whether the target day itself had a log), but the last
            # log DATE is still a fact this record knows, and it is the fact that
            # licenses — or refuses — a "stopped N days ago" framing.
            dates[category] = last
    return LogAvailability(_norm(present), _norm(covered), _norm_dates(dates))


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


def available_logs_from_recency(data, reference_date=None) -> LogAvailability:
    """`LogAvailability` from a snapshot's `days_since_last_*` fields.

    ``0`` ⇒ logged on the snapshot's reference day (present). Any positive number ⇒ the
    most recent log is older than that day (absent). ``None`` ⇒ the recency helper found
    nothing in its whole lookback window, which is also absent — the honest read of "no
    log in 30 days" is not "unknown". A field the snapshot does not carry is uncovered.

    ``reference_date`` (#2382, optional) is the ISO day the counts are measured FROM. Give
    it and the derivation can turn ``days_since`` back into the real last-log DATE, which
    is what licenses a "stopped N days ago" framing downstream. Withhold it and the dates
    simply stay unknown — the counts and coverage are byte-identical either way, so no
    existing caller changes behaviour by not passing it.
    """
    data = data if isinstance(data, dict) else {}
    ref = _iso(reference_date)
    present, covered = set(), set()
    dates: dict[str, str | None] = {}
    for field, category in RECENCY_FIELD_CATEGORIES.items():
        if field not in data:
            continue
        days = data.get(field)
        if days is None:
            covered.add(category)
            # Nothing anywhere in the lookback: a KNOWN absence of a last-log date.
            dates[category] = None
            continue
        try:
            n = int(float(days))
        except (TypeError, ValueError):
            continue  # unparseable → say nothing rather than guess
        covered.add(category)
        if n == 0:
            present.add(category)
        if ref is not None and n >= 0:
            dates[category] = _shift_days(ref, -n)
    return LogAvailability(_norm(present), _norm(covered), _norm_dates(dates))


def _iso(value):
    """A 'YYYY-MM-DD' prefix, or None. Comparison is lexicographic and exact for ISO."""
    s = str(value or "")[:10]
    return s if len(s) == 10 and s[4] == "-" and s[7] == "-" else None


def _date(value):
    """A real `datetime.date` from an ISO prefix, or None. Never raises."""
    iso = _iso(value)
    if iso is None:
        return None
    try:
        return datetime.date.fromisoformat(iso)
    except ValueError:
        return None


def _shift_days(iso, delta):
    d = _date(iso)
    return (d + datetime.timedelta(days=delta)).isoformat() if d is not None else None


def _days_between(earlier, later):
    a, b = _date(earlier), _date(later)
    return (b - a).days if a is not None and b is not None else None


# ── The absence-transition derivation (#2382) ────────────────────────────────
#
# THE DEFECT CLASS. Six of the eight public coach cards narrated the genesis-clamped
# food-log gap as an event: "your food logs paused four days ago", "dark since around
# August 2nd". No pause happened — MacroFactor had already been quiet ~39 days AT
# genesis, and `gap_days=4` was the #955 clamp measuring the CYCLE WINDOW, handed down
# alongside `last_food_log_date=None`. "Never logged in this window" and "logged, then
# stopped four days ago" were the same shape downstream, so the only thing standing
# between the platform and a fabricated transition was prompt text. #2394 fixed the
# prompt text. Prompt rules cannot guarantee structure (0/15 vs. the podcast gate), so
# this is the structural half: the transition is DERIVED IN CODE from dates, before any
# model sees anything (ADR-105 — deterministic computation before any LLM verdict), and
# `never_logged` is a kind that cannot carry a day-count no matter what the caller does
# with it.
#
# The four kinds are exhaustive and mutually exclusive:
#   logged        — a log exists ON the reference day. There is no absence to narrate.
#   paused        — a real last-log date EARLIER than the reference day, INSIDE the
#                   observed window. This is the one and only licensed transition.
#   never_logged  — the window is known and contains no log at all. An absence with no
#                   event in it: sayable as "nothing logged yet", never as "stopped".
#   unknown       — this caller cannot answer. Never licenses, and never flags either
#                   (ADR-104: absence of evidence is not evidence of absence).
TRANSITION_LOGGED = "logged"
TRANSITION_PAUSED = "paused"
TRANSITION_NEVER_LOGGED = "never_logged"
TRANSITION_UNKNOWN = "unknown"
ABSENCE_TRANSITION_KINDS = (TRANSITION_LOGGED, TRANSITION_PAUSED, TRANSITION_NEVER_LOGGED, TRANSITION_UNKNOWN)


class AbsenceTransition(NamedTuple):
    """The deterministic narrative INPUT for "what happened to this log channel?".

    This is the object a prompt/renderer is meant to consume instead of re-deriving the
    story from a raw `gap_days`. `days_since_last_log` is None for every kind except
    `paused` BY CONSTRUCTION — there is no code path that attaches a day-count to a
    never-logged channel, which is what makes the false transition unsayable rather than
    merely discouraged.
    """

    category: str
    kind: str
    last_log_date: Optional[str]
    days_since_last_log: Optional[int]
    window_start: Optional[str]

    @property
    def licenses_transition(self) -> bool:
        """True ⇔ "paused / stopped / went quiet N days ago" is a TRUE thing to say."""
        return self.kind == TRANSITION_PAUSED

    def narrative_input(self) -> str:
        """One deterministic sentence of ground truth. No model involved, no adjectives —
        this is the fact a narrative surface is allowed to dress, not invent."""
        if self.kind == TRANSITION_LOGGED:
            return f"{self.category}: logged on the reference day ({self.last_log_date})."
        if self.kind == TRANSITION_PAUSED:
            return (
                f"{self.category}: last logged {self.last_log_date}, {self.days_since_last_log} "
                f"days before the reference day — a real in-window gap."
            )
        if self.kind == TRANSITION_NEVER_LOGGED:
            window = f" (window opened {self.window_start})" if self.window_start else ""
            return (
                f"{self.category}: nothing logged at any point in this window{window} — "
                f"there is no last log date and NO transition happened; do not date one."
            )
        return f"{self.category}: no answer available — say nothing about it."


def absence_transition(availability, category, reference_date, window_start=None) -> AbsenceTransition:
    """Derive the absence transition for one category. Pure, total, never raises.

    Reads `LogAvailability.last_dates` — the dates, not the sets. A caller whose
    availability carries no date for the category gets `unknown`, which is the only
    honest answer and is exactly what the pre-#2382 shape could never say.
    """
    cat = str(category or "").strip().lower()
    avail = as_availability(availability)
    ref = _iso(reference_date)
    win = _iso(window_start)
    if avail is None or cat not in LOG_CATEGORIES or not avail.knows_last_date(cat):
        return AbsenceTransition(cat, TRANSITION_UNKNOWN, None, None, win)
    last = avail.last_date(cat)
    if last is None:
        # KNOWN never-logged. Note what is NOT here: no day-count. The window's age is a
        # fact about the WINDOW, and attaching it to the channel is how "39 days quiet"
        # became "paused four days ago". This branch needs no reference day — "nothing
        # anywhere in the window" is a window-scoped fact, true of every day inside it.
        return AbsenceTransition(cat, TRANSITION_NEVER_LOGGED, None, None, win)
    if ref is None:
        # A real last-log date exists but there is no day to place it against, so the
        # gap cannot be computed. Unknown, not paused — a transition asserted without a
        # measured gap is exactly the thing this module refuses to license.
        return AbsenceTransition(cat, TRANSITION_UNKNOWN, None, None, win)
    if last >= ref:
        return AbsenceTransition(cat, TRANSITION_LOGGED, last, 0, win)
    gap = _days_between(last, ref)
    if gap is None:
        return AbsenceTransition(cat, TRANSITION_UNKNOWN, None, None, win)
    return AbsenceTransition(cat, TRANSITION_PAUSED, last, gap, win)


def absence_transitions(availability, reference_date, window_start=None) -> dict:
    """`absence_transition` for every category the availability can answer for."""
    avail = as_availability(availability)
    if avail is None:
        return {}
    return {c: absence_transition(avail, c, reference_date, window_start) for c in LOG_CATEGORIES if avail.knows_last_date(c)}


def transition_from_presence_signal(signal, category="nutrition") -> AbsenceTransition:
    """The engagement-signal shortcut — the surface where #2382 actually fired.

    `engagement_core.compute_presence` writes, per channel, the real `last_log_date` it
    observed plus the `experiment_window_start` the #955 clamp anchors on. That is
    everything the derivation needs, so a presence-rendering surface never has to hand-
    branch on `last_food_log_date is None` again: it asks for the transition and gets a
    kind it cannot misread.

    Unlike `available_logs_from_presence`, a missing `experiment_window_start` does NOT
    demote a null `last_log_date` to unknown here, and the asymmetry is deliberate. That
    function answers "was there a log ON DAY X", which genuinely needs the window to
    contain X. This one answers "what is the last log date this record observed", and
    ``None`` is the record's own answer to that — an unknown window makes the absence
    harder to describe, never easier to narrate as a transition.
    """
    signal = signal if isinstance(signal, dict) else {}
    ref = _iso(signal.get("date"))
    win = _iso(signal.get("experiment_window_start"))
    detail = signal.get("channel_detail")
    detail = detail if isinstance(detail, dict) else {}
    cat = str(category or "").strip().lower()

    dates = {}
    for channel, mapped in PRESENCE_CHANNEL_CATEGORIES.items():
        entry = detail.get(channel)
        if not isinstance(entry, dict):
            continue
        if "last_log_date" not in entry:
            continue  # the record does not carry the fact at all → genuinely unknown
        last = _iso(entry.get("last_log_date"))
        dates[mapped] = last  # None here IS the answer: nothing in the observed window
    # The top-level food fields are the clamped pair the coach cards actually read. They
    # agree with channel_detail["macrofactor"] by construction; read them too so a signal
    # that carries only the flat shape still derives rather than falling to unknown.
    if "nutrition" not in dates and "last_food_log_date" in signal:
        dates["nutrition"] = _iso(signal.get("last_food_log_date"))
    avail = LogAvailability(frozenset(), frozenset(), _norm_dates(dates))
    return absence_transition(avail, cat, ref, win)


# ── The guard: a transition framing must be licensed by a real date ──────────
#
# The derivation above makes the false input unbuildable. This guard is the second half:
# it reads generated TEXT and refuses a paused/stopped/went-quiet framing about a channel
# whose transition kind is `never_logged`. `unknown` never flags — same #2056 semantics as
# the behavioral gate, and for the same reason: a gate that fires when it merely could not
# see is noise, and noise is how gates get switched off.
_AT_TRANSITION_RE = re.compile(
    r"\b(?:"
    r"paused|stopped|halted|ceased|"
    r"(?:went|gone|fell|falling|drifted|slipped)\s+(?:quiet|silent|dark|off)|"
    r"(?:been|be)\s+(?:quiet|silent|dark)\s+(?:since|for)|"
    r"(?:dark|quiet|silent)\s+since|"
    r"(?:since|for)\s+(?:the\s+)?(?:last\s+)?\S{1,12}\s+days?|"
    r"days?\s+since\s+(?:you|he|his|matthew)\b|"
    r"last\s+log(?:ged)?\s+(?:was\s+)?(?:on\s+)?\d{4}-\d{2}-\d{2}|"
    r"(?:trailed|tapered|tailed)\s+off|"
    r"stopped\s+logging|"
    r"broke\s+the\s+streak"
    r")\b",
    re.IGNORECASE,
)
# Which words in a sentence make it ABOUT a given log category. Deliberately narrow: the
# guard only speaks for channels a presence signal actually tracks.
_AT_CATEGORY_TERMS = {
    "nutrition": re.compile(r"\b(?:food|meal|meals|nutrition|macros?|calories?|eating|logging|logs?)\b", re.IGNORECASE),
    "workout": re.compile(r"\b(?:workout|workouts|lift(?:s|ing)?|training|gym|session)\b", re.IGNORECASE),
    "journal": re.compile(r"\b(?:journal(?:s|ing|ed)?|writing|entries)\b", re.IGNORECASE),
}
_AT_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def absence_transition_findings(text: str, *, transitions) -> list:
    """Flag a transition framing that no real date licenses (#2382).

    `transitions` is what `absence_transitions()` / `transition_from_presence_signal()`
    return — a category→`AbsenceTransition` map (a single `AbsenceTransition` is accepted
    too). A sentence that frames a stop/pause/went-quiet event about a category whose kind
    is `never_logged` is a fabricated transition and becomes a
    ``{"type": "fabricated_absence_transition", ...}`` finding in the shared shape, so it
    composes with grounding_findings() / correction_prompt().

    Only `never_logged` flags. `paused` is a true transition, `logged` has no absence to
    narrate, and `unknown` is a category this caller cannot speak for — flagging any of
    those three would be the gate guessing.
    """
    text = text or ""
    if isinstance(transitions, AbsenceTransition):
        transitions = {transitions.category: transitions}
    if not isinstance(transitions, dict):
        return []
    unlicensed = {
        c: t
        for c, t in transitions.items()
        if isinstance(t, AbsenceTransition) and t.kind == TRANSITION_NEVER_LOGGED and c in _AT_CATEGORY_TERMS
    }
    if not unlicensed:
        return []

    findings, seen = [], set()
    for raw in _AT_SENTENCE_SPLIT_RE.split(text.strip()):
        sent = raw.strip()
        if not sent:
            continue
        m = _AT_TRANSITION_RE.search(sent)
        if not m:
            continue
        for category, tr in unlicensed.items():
            if not _AT_CATEGORY_TERMS[category].search(sent):
                continue
            key = (category, m.group(0).lower())
            if key in seen:
                continue
            seen.add(key)
            snippet = sent if len(sent) <= 140 else sent[:137].rstrip() + "…"
            findings.append(
                {
                    "type": "fabricated_absence_transition",
                    "category": category,
                    "claim": m.group(0).strip(),
                    "detail": (
                        f'the narrative dates a "{category}" logging transition ("{snippet}"), but nothing was '
                        f"logged at any point in this window — there is no last log date, so no stop, pause or "
                        f"went-quiet event happened for it to describe"
                    ),
                }
            )
    return findings


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
