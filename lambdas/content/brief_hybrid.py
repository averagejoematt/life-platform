"""brief_hybrid.py — the Morning Brief's hybrid format, the two-week trial (#6175, owner ruling 2026-11-22 §2).

The hybrid puts a short block ABOVE the brief that is sent today:

  1. SIX STATUS LINES in fixed positions, every day: Body, Recovery, Training, Food, Habits, Waiting.
     A value that is not there says so ("unknown", "not arrived"); a line is never dropped.
  2. TODAY: one genuinely new decision, or exactly "Nothing new needs you today."
  3. RECOMMENDATIONS: each one labelled NEW or REPEAT (day n), with its evidence, a confidence stated
     in words with its basis, and the optional response link on the single recommendation.
  4. UNKNOWN: what the brief could not see.

Then a divider, and the full current brief below it. There is no authenticated owner page to link
to (the cockpit is public; /progress-photos is photos only), so the detail stays in the same email
in collapsed order — decision first, detail after — rather than behind a link to nothing.

Three rules this module exists to hold:

  * NEW means new. A recommendation is NEW only when nothing of the same action class was shown in
    the previous `RUN_GAP_DAYS` + 1 briefs' days. `first_seen` is the start of its current run, where a
    gap of up to `RUN_GAP_DAYS` days without it does not end the run. Yesterday's advice is never NEW.
  * Pending is not missing. When the food log's export has not arrived for the data day, every
    food-log or protein suggestion is held back (each was written from a log the platform has not
    received) and the Food line and the Unknown list say "export not arrived", never "not logged".
  * A provisional grade stays provisional. The subject names it so.

The confidence words are the platform's, not the model's: the AI guidance carries no calibrated
confidence (the insight writer stamps a fixed "medium"), so every AI suggestion reads "low", with
that reason. The readiness call is "low" because its weights were never checked against outcomes.

Pure module: no AWS, no clock, no I/O. `emails.brief_trial` gathers the inputs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from common.pacific_time import day_in_words, parse_day_key, shift_day_key

from content.brief_format import esc

# ── switch values (read by emails.brief_trial; documented here so the renderer and the reader agree) ──
SWITCH_OFF = "off"
SWITCH_HYBRID = "hybrid"  # render the hybrid block above the current brief, and record the send
SWITCH_MEASURE = "measure"  # current render, unchanged; record the send only (the comparison arm)
SWITCH_VALUES = (SWITCH_OFF, SWITCH_HYBRID, SWITCH_MEASURE)

NOTHING_NEW = "Nothing new needs you today."
RUN_GAP_DAYS = 2
READINESS_GAP_DAYS = 0
STATUS_LABELS = ("Body", "Recovery", "Training", "Food", "Habits", "Waiting")
FORMAT_VERSION = "hybrid-v1"

# ── action classes ───────────────────────────────────────────────────────────────────────────────
# A guidance sentence is reworded every day; its ACTION is not. Ordered: the first match wins, so a
# sentence about logging a meal to fix protein is a food-log ask, not a protein ask.
_ACTION_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "food_log",
        (
            r"\blog (a|one|your first|your next|the) meal",
            r"\bfood log",
            r"\bfood logger",
            r"\bopen (macrofactor|the food|your food)",
            r"\b(nutrition|food) (data|logging|logs?) (has been |have been |is |was |went )?(dark|missing|absent|quiet|unlogged)",
            r"\blogging (gap|went quiet)",
            r"\bunlogged\b",
            r"\bdays? (without|of missing) (a )?food",
            r"\bin macrofactor\b",
        ),
    ),
    ("protein", (r"\bprotein\b", r"\bshake\b")),
    ("intake", (r"\bkcal\b", r"\bcalori", r"\bnutrition score\b", r"\bTDEE\b", r"\bintake\b")),
    ("movement", (r"\bwalk\b", r"\bwalking\b", r"\bsteps?\b", r"\bmove(ment)?\b")),
    ("recovery_day", (r"\brecovery day\b", r"\brestoration\b", r"\bnot a push day\b", r"\beasy (day|zone 2)\b", r"\bdeload\b")),
    ("hydration", (r"\bhydrat", r"\bwater\b")),
    ("light", (r"\bdaylight\b", r"\bsunlight\b", r"\bstep outside\b")),
    ("supplement", (r"\bfish oil\b", r"\bomega-?3", r"\bsupplement")),
    ("journal", (r"\bjournal\b",)),
    ("sleep", (r"\bbedtime\b", r"\bwind[- ]down\b", r"\bsleep (earlier|by)\b")),
    ("weight_marker", (r"\b285\b", r"\bsleep threshold\b", r"\bmilestone\b")),
)
_CLASS_RES = tuple((name, tuple(re.compile(p, re.I) for p in pats)) for name, pats in _ACTION_PATTERNS)
FOOD_KEYS = frozenset({"food_log", "protein", "intake"})
# Observations, not asks: a distance-to-marker line is shown in the full detail, never as a recommendation.
OBSERVATION_KEYS = frozenset({"weight_marker"})
_WORD = re.compile(r"[a-z0-9]+")


def classify(text) -> str:
    """The action class of one guidance sentence. Unmatched text keys on its first six words, so an
    unclassified sentence repeated verbatim is still a REPEAT."""
    s = str(text or "")
    for name, res in _CLASS_RES:
        if any(r.search(s) for r in res):
            return name
    words = _WORD.findall(s.lower())
    return "other:" + "-".join(words[:6])


def readiness_key(colour) -> str | None:
    return ("readiness:" + str(colour)) if colour in ("green", "yellow", "red") else None


# ── NEW / REPEAT ─────────────────────────────────────────────────────────────────────────────────


def first_seen(key: str, data_day: str, history: dict, gap: int = RUN_GAP_DAYS) -> str:
    """The data day this key's current run began. `history` maps a PRIOR data day to the set of keys its
    brief showed. Walks back from `data_day`: the run continues while the key was shown again with at
    most `gap` days between showings (a long run keeps walking — that is the point of "day n"). The readiness
    call is computed every morning, so its run allows no gap (`READINESS_GAP_DAYS`)."""
    start = data_day
    cursor = data_day
    while True:
        hit = None
        for back in range(1, gap + 2):
            d = shift_day_key(cursor, -back)
            if key in (history.get(d) or ()):
                hit = d
                break
        if hit is None:
            return start
        start = cursor = hit


def day_number(first: str, data_day: str) -> int:
    a, b = parse_day_key(first), parse_day_key(data_day)
    if a is None or b is None:
        return 1
    return max(1, (b - a).days + 1)


@dataclass
class Rec:
    key: str
    text: str
    kind: str  # "coaching" (can be the day's decision) | "housekeeping" (data upkeep; never the decision)
    source: str  # "readiness" | "ai_guidance" | "food_export"
    evidence: str
    confidence: str  # one word: low / medium / high
    basis: str
    first_seen: str = ""
    day_n: int = 1

    @property
    def status(self) -> str:
        return "NEW" if self.day_n <= 1 else "REPEAT"

    @property
    def label(self) -> str:
        return "NEW" if self.day_n <= 1 else "REPEAT (day " + str(self.day_n) + ")"

    @property
    def rec_id(self) -> str:
        """Stable across the run: the day it was first shown + its action class."""
        return (self.first_seen or "") + "#" + self.key


@dataclass
class View:
    data_day: str
    status: list  # six (label, text) pairs, in STATUS_LABELS order
    recs: list
    decision: Rec | None
    unknown: list
    held_back: int = 0
    respond_url: str | None = None
    respond_rec: Rec | None = None
    notes: list = field(default_factory=list)


def label_recs(recs: list, data_day: str, history: dict) -> list:
    """Stamp first_seen / day_n on each rec (in place) and return them."""
    for r in recs:
        r.first_seen = first_seen(r.key, data_day, history, READINESS_GAP_DAYS if r.source == "readiness" else RUN_GAP_DAYS)
        r.day_n = day_number(r.first_seen, data_day)
    return recs


def pick_decision(recs: list) -> Rec | None:
    """The day's one decision: the first NEW coaching recommendation, or None ("Nothing new")."""
    return next((r for r in recs if r.kind == "coaching" and r.status == "NEW"), None)


def pick_respond(recs: list, decision: Rec | None) -> Rec | None:
    """The single recommendation that carries the optional response link: the decision, else the
    longest-standing coaching repeat (the one most worth an explicit answer)."""
    if decision is not None:
        return decision
    coaching = [r for r in recs if r.kind == "coaching"]
    return max(coaching, key=lambda r: r.day_n) if coaching else None


# ── the recommendations, from the brief's own inputs ─────────────────────────────────────────────

_READINESS_CALL = {
    "red": "Easy day: walk, stretch or easy Zone 2 only.",
    "yellow": "Moderate day: Zone 2 or moderate strength.",
    "green": "Ready: hard training or high-focus work is fine.",
}
_READINESS_BASIS = "A fixed-weight score (recovery, sleep, HRV trend, training balance), never checked against how your sessions went."
_AI_BASIS = "One AI coach's reading of one day's data; it carries no calibrated confidence and was never checked against outcomes."


def readiness_rec(colour, score, recent_scores: list, morning_day: str) -> Rec | None:
    """The readiness call as a recommendation. `recent_scores` = the scores of the run's mornings,
    oldest first, ending with this one (for the evidence line)."""
    key = readiness_key(colour)
    if key is None:
        return None
    if score is None:
        evidence = "Readiness " + str(colour) + " for the morning of " + day_in_words(morning_day) + "."
    else:
        evidence = "Readiness " + str(score) + " (" + str(colour) + ") for the morning of " + day_in_words(morning_day) + "."
    if len(recent_scores) > 1:
        evidence += " Recent mornings: " + ", ".join(str(s) for s in recent_scores) + "."
    return Rec(
        key=key,
        text=_READINESS_CALL[colour],
        kind="coaching",
        source="readiness",
        evidence=evidence,
        confidence="low",
        basis=_READINESS_BASIS,
    )


def guidance_recs(guidance_items: list, data_day: str, food_pending: bool) -> tuple[list, int]:
    """(recs, held_back) from today's AI guidance items (the TL;DR excluded — it summarises, it does
    not ask). One rec per action class (the first sentence of a class wins). When the food export is
    pending, food-log and protein suggestions are HELD BACK and counted, never shown as asks."""
    out, seen, held = [], set(), 0
    for item in guidance_items or []:
        text = str(item or "").strip()
        if not text:
            continue
        key = classify(text)
        if key in OBSERVATION_KEYS:
            continue
        if food_pending and key in FOOD_KEYS:
            held += 1
            continue
        if key in seen:
            continue
        seen.add(key)
        out.append(
            Rec(
                key=key,
                text=text,
                kind="coaching",
                source="ai_guidance",
                evidence="The coach's reading of " + day_in_words(data_day, weekday=False) + ", in its own words.",
                confidence="low",
                basis=_AI_BASIS,
            )
        )
    return out, held


def export_rec(data_day: str, last_arrival_day: str | None) -> Rec:
    last = ("The last export arrived " + day_in_words(last_arrival_day) + ".") if last_arrival_day else "No export date is on record."
    return Rec(
        key="food_export",
        text="If you logged food on " + day_in_words(data_day) + ", export MacroFactor; if you did not, nothing to do.",
        kind="housekeeping",
        source="food_export",
        evidence="No food row for " + day_in_words(data_day) + " has arrived. " + last,
        confidence="high",
        basis="High that the data is missing; unknown whether you logged. Food reaches the platform only by a manual export.",
    )


# ── the six status lines ─────────────────────────────────────────────────────────────────────────


def _num(v, nd=1):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return round(f, nd)


def _fmt(v, nd=1, thousands=False) -> str:
    if nd == 0:
        return f"{int(round(float(v))):,}" if thousands else str(int(round(float(v))))
    return f"{float(v):,.{nd}f}" if thousands else f"{float(v):.{nd}f}"


def body_line(s: dict) -> str:
    w = _num(s.get("weight_lbs"))
    if w is None:
        return "unknown: no weigh-in on record"
    out = _fmt(w) + " lb"
    if s.get("weight_day"):
        out += " (" + day_in_words(s["weight_day"], weekday=False) + ")"
    rate = _num(s.get("weekly_rate_lbs"), 2)
    if rate is not None:
        out += " · " + ("+" if rate > 0 else "−" if rate < 0 else "") + _fmt(abs(rate)) + " lb/wk"
        lo, hi = _num(s.get("rate_ci_low"), 2), _num(s.get("rate_ci_high"), 2)
        if lo is not None and hi is not None:
            out += " (range " + _signed(lo) + " to " + _signed(hi) + ")"
        if s.get("rate_provisional"):
            out += ", provisional"
    return out


def _signed(v) -> str:
    return ("−" if v < 0 else "+" if v > 0 else "") + _fmt(abs(v))


def recovery_line(s: dict) -> str:
    parts = []
    if s.get("rebaselining"):
        parts.append("readiness re-baselining (no colour drawn from heart-rate numbers)")
    elif s.get("readiness_score") is not None:
        parts.append("readiness " + str(s["readiness_score"]) + " " + str(s.get("readiness_colour") or ""))
    rec = _num(s.get("recovery"), 0)
    if rec is not None:
        parts.append("recovery " + _fmt(rec, 0))
    hrv = _num(s.get("hrv"))
    if hrv is not None:
        h = "HRV " + _fmt(hrv)
        h30 = _num(s.get("hrv_30d"))
        if h30 is not None:
            h += " (30-day " + _fmt(h30) + ")"
        parts.append(h)
    sl = _num(s.get("sleep_hours"))
    if sl is not None:
        parts.append("sleep " + _fmt(sl) + " h")
    if not parts:
        return "unknown: no recovery data for the morning of " + day_in_words(s.get("morning_day") or "")
    tail = "morning of " + day_in_words(s.get("morning_day") or "", weekday=True)
    tail += (
        "; this morning scored " + _fmt(s["today_recovery"], 0) if s.get("today_recovery") is not None else "; this morning not scored yet"
    )
    return " · ".join(parts) + " — " + tail


def training_line(s: dict) -> str:
    day = day_in_words(s.get("data_day") or "", weekday=False)
    n = s.get("sessions")
    if n is None:
        out = day + ": unknown (no training data read)"
    elif n == 0:
        out = day + ": no session recorded"
    else:
        out = day + ": " + str(n) + " session" + ("" if n == 1 else "s") + ", " + _fmt(s.get("minutes") or 0, 0) + " min"
        sports = s.get("by_sport") or {}
        if sports:
            out += " (" + ", ".join(k.replace("_", " ") + " " + _fmt(v, 0) for k, v in sports.items()) + ")"
    acwr = _num(s.get("acwr"), 2)
    if acwr is not None:
        out += " · load ratio " + _fmt(acwr, 2)
    return out


def food_line(s: dict) -> str:
    day = day_in_words(s.get("data_day") or "", weekday=False)
    kcal = _num(s.get("kcal"), 0)
    if kcal is not None:
        out = day + ": " + _fmt(kcal, 0, thousands=True) + " kcal"
        p = _num(s.get("protein_g"), 0)
        if p is not None:
            out += " / " + _fmt(p, 0) + " g protein"
        return out
    arrival = s.get("arrival")
    last = s.get("last_arrival_day")
    if arrival == "not_arrived":
        out = day + ": export not arrived — pending data, not a missed log"
        if last:
            out += " (last export " + day_in_words(last, weekday=False) + ")"
        return out
    if arrival == "arrived":
        return day + ": not logged (an export has arrived since and has no " + day + " row)"
    return day + ": unknown (export status not read)"


def habits_line(s: dict) -> str:
    total = s.get("habits_total")
    if not total:
        return "unknown: no essentials scored"
    out = "essentials " + str(s.get("habits_done") or 0) + "/" + str(total)
    missed = s.get("habits_missed") or []
    if missed:
        out += " (missed: " + ", ".join(str(m) for m in missed[:4]) + ("…" if len(missed) > 4 else "") + ")"
    if s.get("streak") is not None:
        out += " · streak " + str(s["streak"])
    g = s.get("grade_score")
    if g is not None:
        out += " · day grade " + str(g) + " (" + str(s.get("grade_letter") or "—") + ")"
        if s.get("grade_provisional"):
            out += " PROVISIONAL — food log not in"
    return out


def waiting_line(s: dict) -> str:
    items = s.get("waiting") or []
    if not items:
        return "nothing waiting on you"
    return str(len(items)) + ": " + "; ".join(str(i) for i in items)


def status_lines(s: dict) -> list:
    return [
        ("Body", body_line(s)),
        ("Recovery", recovery_line(s)),
        ("Training", training_line(s)),
        ("Food", food_line(s)),
        ("Habits", habits_line(s)),
        ("Waiting", waiting_line(s)),
    ]


# ── render ───────────────────────────────────────────────────────────────────────────────────────


def subject(view: View, today_short: str, grade_score, grade_letter, grade_provisional: bool, readiness_colour) -> str:
    """Keeps the `Morning Brief | <day>` prefix (filters and the send ledger key on nothing else here)."""
    lead = "1 new decision" if view.decision else "Nothing new"
    parts = ["Morning Brief", today_short, lead]
    if grade_score is not None:
        parts.append("Grade " + str(grade_score) + " (" + str(grade_letter) + (", provisional" if grade_provisional else "") + ")")
    emoji = {"green": "🟢", "yellow": "🟡", "red": "🔴"}.get(readiness_colour, "⚪")
    return " | ".join(parts) + " | " + emoji


def _rec_lines(r: Rec) -> list:
    return [
        r.text + " — " + r.label,
        "Evidence: " + r.evidence,
        "Confidence: " + r.confidence + ". " + r.basis,
    ]


def render_text(view: View) -> str:
    """The plain-text form of the hybrid block (also what the word count measures)."""
    out = ["STATUS"]
    w = max(len(k) for k in STATUS_LABELS)
    out += [k.ljust(w) + "  " + v for k, v in view.status]
    out += ["", "TODAY"]
    if view.decision:
        out += _rec_lines(view.decision)
    else:
        out.append(NOTHING_NEW)
    rest = [r for r in view.recs if r is not view.decision]
    if rest:
        out += ["", "Recommendations"]
        for r in rest:
            out += ["• " + _rec_lines(r)[0]] + ["  " + x for x in _rec_lines(r)[1:]]
    if view.held_back:
        out += ["", _held_back_sentence(view.held_back)]
    if view.unknown:
        out += ["", "Unknown"] + ["• " + u for u in view.unknown]
    if view.respond_url and view.respond_rec is not None:
        out += ["", "Your answer on “" + view.respond_rec.text + "” (optional): " + view.respond_url]
    out += ["", "———", "Full detail: the complete brief, below."]
    return "\n".join(out)


def _held_back_sentence(n: int) -> str:
    return (
        str(n)
        + " food suggestion"
        + ("" if n == 1 else "s")
        + " held back: "
        + ("it was" if n == 1 else "they were")
        + " written from a food log that has not arrived yet."
    )


_S = {
    "wrap": "background:#0b1220;padding:18px 24px;border-bottom:3px solid #334155;font-family:-apple-system,Segoe UI,sans-serif;",
    "h": "color:#94a3b8;font-size:10px;font-weight:700;letter-spacing:1px;margin:14px 0 6px;",
    "row": "color:#e2e8f0;font-size:13px;margin:2px 0;line-height:1.4;",
    "key": "color:#64748b;display:inline-block;width:72px;font-size:12px;",
    "decision": "color:#f8fafc;font-size:15px;font-weight:700;margin:4px 0;",
    "small": "color:#94a3b8;font-size:12px;margin:2px 0 0;line-height:1.4;",
    "rec": "color:#e2e8f0;font-size:13px;margin:8px 0 0;line-height:1.4;",
    "tag": "font-size:10px;font-weight:700;padding:1px 6px;border-radius:3px;margin-left:6px;",
    "btn": "display:inline-block;background:#1e293b;color:#e2e8f0;border:1px solid #475569;border-radius:6px;padding:6px 12px;"
    "font-size:12px;text-decoration:none;margin-top:6px;",
    "divider": "color:#64748b;font-size:11px;text-align:center;margin:16px 0 0;letter-spacing:1px;",
}


def _tag(r: Rec) -> str:
    colour = "#22c55e" if r.status == "NEW" else "#f59e0b"
    return '<span style="' + _S["tag"] + "color:" + colour + ";border:1px solid " + colour + ';">' + esc(r.label) + "</span>"


def _rec_html(r: Rec, style: str) -> str:
    return (
        '<p style="' + style + '">' + esc(r.text) + _tag(r) + "</p>"
        '<p style="' + _S["small"] + '">Evidence: ' + esc(r.evidence) + "</p>"
        '<p style="' + _S["small"] + '">Confidence: ' + esc(r.confidence) + ". " + esc(r.basis) + "</p>"
    )


def render_html(view: View) -> str:
    """The hybrid block, as one self-contained <div> placed directly after <body>."""
    out = '<!-- S:hybrid_brief --><div style="' + _S["wrap"] + '">'
    out += '<p style="' + _S["h"] + 'margin-top:0;">STATUS</p>'
    for k, v in view.status:
        out += '<p style="' + _S["row"] + '"><span style="' + _S["key"] + '">' + esc(k) + "</span>" + esc(v) + "</p>"
    out += '<p style="' + _S["h"] + '">TODAY</p>'
    if view.decision:
        out += _rec_html(view.decision, _S["decision"])
    else:
        out += '<p style="' + _S["decision"] + '">' + esc(NOTHING_NEW) + "</p>"
    rest = [r for r in view.recs if r is not view.decision]
    if rest:
        out += '<p style="' + _S["h"] + '">RECOMMENDATIONS</p>'
        for r in rest:
            out += _rec_html(r, _S["rec"])
    if view.held_back:
        out += '<p style="' + _S["small"] + 'margin-top:8px;">' + esc(_held_back_sentence(view.held_back)) + "</p>"
    if view.unknown:
        out += '<p style="' + _S["h"] + '">UNKNOWN</p>'
        for u in view.unknown:
            out += '<p style="' + _S["small"] + '">• ' + esc(u) + "</p>"
    if view.respond_url and view.respond_rec is not None:
        out += (
            '<p style="'
            + _S["small"]
            + 'margin-top:12px;">Optional: tell the platform what you did with “'
            + esc(view.respond_rec.text)
            + "”. The link opens a page where you choose; opening it records nothing.</p>"
            '<a style="' + _S["btn"] + '" href="' + esc(view.respond_url) + '">Answer: done / not doing it / still deciding</a>'
        )
    out += '<p style="' + _S["divider"] + '">——— FULL DETAIL: THE COMPLETE BRIEF ———</p>'
    return out + "</div><!-- /S:hybrid_brief -->"


def inject(full_html: str, block: str) -> str:
    """The hybrid block directly after the <body> tag (above the data-status banner and the brief)."""
    m = re.search(r"<body[^>]*>", full_html, flags=re.I)
    if not m:
        return block + full_html
    return full_html[: m.end()] + block + full_html[m.end() :]


def html_to_words(html: str) -> int:
    """Visible-word count of an HTML email (tags, comments, style and script removed)."""
    s = re.sub(r"<!--.*?-->", " ", html or "", flags=re.S)
    s = re.sub(r"<(style|script)[^>]*>.*?</\1>", " ", s, flags=re.S | re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"&[a-z#0-9]+;", " ", s, flags=re.I)
    return len(s.split())


def word_count(text: str) -> int:
    return len((text or "").split())
