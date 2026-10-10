"""content/story_craft.py — the craft standard the Story Desk writes to (#4545).

Earned by the 2026-10-01 red team: a Reddit growth strategist, a narrative-podcast producer,
a long-form features editor, a simulated eight-reader panel and a research pass on serialized
N=1 stories all read the first rebuilt season. Two of eight simulated readers finished it; half
stopped inside the prologue. The causes converged:

  * the subject never spoke — every protagonist was a coach or a metric;
  * every installment opened on a date and a wearable score, and buried the real hooks (a
    23-day training streak, the AI coaches being graded and losing in public, the earlier
    305→190 run and the regain) past the fifth paragraph;
  * four to eight figures per spoken minute (listeners hold about four);
  * the same tics every week ("The question is whether…", "For a reader arriving here cold",
    "not X — it's Y", "I'll say upfront");
  * cross-week callbacks that contradicted the installment they recalled.

This module holds the standard as data and as checks. The writers are told the rules; the checks
hold them to the rules; the scoreboard is rendered by code so its numbers are never the model's.
Pure functions: no boto3, no model calls.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional

# ── the rules, as the writers are told them ──────────────────────────────────

CHRONICLE_BRIEF = """THE CRAFT STANDARD (what makes strangers read the next one):
- TOP LINE FIRST. The first paragraph tells a stranger, in plain words, how he is and what is at stake this week — the
  day number and the scale's direction in the first two sentences. Never open on a date or a wearable reading; open on
  something he did, chose, said, or a moment with stakes.
- HIS VOICE. When the dossier carries "owner_voice" answers, the week turns on them: quote at most two short lines,
  exactly as written, and build the scene around what he did and why. When it carries none, do not narrate the absence.
  Never speculate about his motives or inner state; inner life comes only from his own words.
- ONE THESIS, THREE STAKES. Lead with the budget's lead. Advance the season throughline it names. End on a dated,
  concrete unknown (a thing that will be true or false by a named day), never on "the question is whether".
- NUMBERS. At most three figures in any paragraph. Give a week as its mean, its range or its one outlier — never a
  day-by-day series. No slopes, standard deviations or decimals beyond one place. The scoreboard carries the rest.
- QUOTES ARE EXACT. Quotation marks and blockquotes go ONLY around words that appear verbatim in the dossier — a
  coach's latest_public_summary or latest_key_recommendation, a prediction's claim, or his own owner_voice answer.
  Anything else is paraphrase, unquoted ("Webb's read was that dinner carries too much of the day").
- COACHES ARE CHARACTERS. A coach quote must disagree, admit an error, change its mind, or ask something of him — it
  never restates numbers the prose already gave. Introduce each coach once per season by role; after that, surname.
  The AI premise is stated once per installment at most, in a clause, never a paragraph.
- WHAT A COACH ASKED LAST WEEK GETS FOLLOWED UP: did it happen? Say so.
- LENGTH. 900-1,200 words of body. Cut recaps: the dek above the piece orients the cold reader, the body does not.
- BANNED: "The question is whether", "For a reader arriving here cold" and variants, "It held before, until it didn't"-style
  aphorism closers, more than ONE "not X — it's Y" construction, "genuinely", "the gap between X and Y" as a closer,
  "architecture" for anything but software, the words "ledger", "desk", "dossier", "budget"."""

EPISODE_BRIEF = """THE CRAFT STANDARD FOR THE EAR (what keeps a commuter past minute one):
- COLD OPEN: one moment and one contrast, under 60 words, no thresholds explained. Then a welcome under 50 words.
- THE GUEST IS ON THE HOT SEAT. Read their graded record aloud in a sentence; they answer for it. The coach whose
  record or ask is the week's story is the guest.
- RECURRING SEGMENTS, in this order after the lead: "The call I got wrong" (the guest's worst graded miss, their own
  words, under 120 words) and "What we don't know yet" (one open question, said plainly). Score last week's bet near
  the top with the real number; Elena and the guest each take a side on the new bet, and the guest owns it by name.
- FRICTION. The guest disagrees with Elena or another coach at least once. Elena pushes with short follow-ups
  ("You can prescribe it. Will you?"). At least three interruptions or quick reactions ("Wait — fifteen sets over?").
- EAR NUMBERS. At most three figures in a turn and about twenty-five in the episode. Round for the ear ("about 140
  grams", "the twenty-fifth"). No slopes or standard deviations. Gloss every statistic ("the best he's scored").
- SENTENCES. Median about 14 words, none over 25. Elena's turns under 80 words.
- HIS VOICE: when "owner_voice" answers exist, Elena reads one short line of his exactly ("He wrote back: '…'").
- 1,250-1,450 spoken words. End on a dated unknown, then the sign-off.
- BANNED: "I'll say upfront", "actual read", "I don't want to dismiss", "Wrong, and I want to be", "as the team has set
  it", "Let's move to the secondary story", "The question is whether"."""

# ── checks ───────────────────────────────────────────────────────────────────

_BANNED = [
    r"\bthe question is whether\b",
    r"\bfor a (?:cold )?reader arriving\b",
    r"\bfor a reader (?:who is )?arriving here\b",
    r"\bI'll say (?:this )?upfront\b",
    r"\bactual read\b",
    r"\bI don't want to dismiss\b",
    r"\bwrong, and I want to be\b",
    r"\bas the team has set it\b",
    r"\blet's move to the secondary story\b",
    r"\bgenuinely\b",
    r"\bepistemological\b",
    r"\b(?:delve|tapestry|testament to)\b",
]
_BANNED_RE = [re.compile(p, re.IGNORECASE) for p in _BANNED]
# "not X — it's Y" / "isn't X; it's Y" / "not X. It's Y" — the corrective antithesis readers flag first
_ANTITHESIS = re.compile(
    r"\b(?:(?:is|was|are|were)\s+(?:not|no longer|never)|isn't|wasn't|aren't|weren't)\b[^.!?\n]{1,90}?(?:—|;|\.|,)\s*(?:it|that|this|he|they)(?:'s|\s+is|\s+was|\s+are)\b",
    re.IGNORECASE,
)
_NUM = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?(?![\w])")
_CALENDAR = re.compile(
    r"\b(?:Day|Week|Month)\s+\d+\b|\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2}(?:st|nd|rd|th)?\b|\b\d{1,2}:\d{2}\b|\b20\d\d\b",
    re.IGNORECASE,
)
_OPENING_BAD = re.compile(
    r"^\s*(?:On the morning of|On (?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)|September|October|\w+ \d{1,2}(?:st|nd|rd|th)?,? 20\d\d)",
    re.IGNORECASE,
)

# The scale's direction, said any way a stranger would read it: a figure in pounds, "pounds"/"lb" spelled out, the scale
# itself, or a weigh-in. The opening must carry one when the week has a weigh-in to report.
_WEIGHT_WORD = re.compile(r"\b(?:pounds?|lbs?|scale|weigh(?:s|ed|-in|-ins|ing)?|lighter|heavier)\b", re.IGNORECASE)
# What a stranger cannot read in five seconds: device names and wearable / statistics jargon. The top line above the
# piece is plain English; the scoreboard and the body carry the instruments.
_JARGON = re.compile(
    r"\b(?:WHOOP|Withings|Eight\s+Sleep|Garmin|Oura|Apple\s+Watch|MacroFactor|Hevy|Strava|HRV|RHR|VO2(?:\s*max)?|"
    r"heart[- ]rate variability|strain score|recovery score|sleep score|z-?scores?|standard deviations?|slopes?|kcal|TDEE)\b",
    re.IGNORECASE,
)
# The podcast's two recurring segments, named on air so a returning listener hears the show's shape (#4545).
SEGMENTS = (
    ("the call I got wrong", re.compile(r"\bthe call I got wrong\b", re.IGNORECASE)),
    ("what we don't know yet", re.compile(r"\bwhat we (?:don['’]t|do not) know yet\b", re.IGNORECASE)),
)

TOP_LINE_MAX_WORDS = 45
TOP_LINE_MAX_SENTENCES = 2
CHRONICLE_WORDS = (850, 1300)
EPISODE_WORDS = (1150, 1550)
MAX_FIGURES_PER_PARAGRAPH = 3
MAX_FIGURES_PER_TURN = 3
MAX_FIGURES_PER_EPISODE = 30
MAX_ANTITHESES = 1


def figures(text: str) -> int:
    """Figures a reader has to hold — calendar references (Day 24, September 25th, 2026, 5:12) excluded."""
    return len(_NUM.findall(_CALENDAR.sub(" ", text or "")))


def banned(text: str) -> List[str]:
    out = []
    for rx in _BANNED_RE:
        for m in rx.finditer(text or ""):
            out.append(f"craft: banned phrase {m.group(0)!r}")
    n = len(_ANTITHESIS.findall(text or ""))
    if n > MAX_ANTITHESES:
        out.append(f"craft: {n} 'not X — it's Y' constructions (max {MAX_ANTITHESES}) — the tic readers flag first as AI")
    return out


def chronicle_findings(body: str, *, week: int, weight_known: bool = False) -> List[str]:
    """Craft findings for one chronicle body (title line already removed; footer may remain).

    ``weight_known``: the week has a weigh-in, so the opening must also say which way the scale went (the brief's
    "the day number and the scale's direction in the first two sentences")."""
    out = banned(body)
    paras = [
        p.strip()
        for p in re.split(r"\n\s*\n", body or "")
        if p.strip() and not p.strip().startswith(("---", "*Week", "*Prologue", "*Editor"))
    ]
    words = sum(len(p.split()) for p in paras)
    lo, hi = CHRONICLE_WORDS
    if not lo <= words <= hi:
        out.append(f"craft: body is {words} words; the standard is {lo}-{hi}")
    for i, p in enumerate(paras):
        if p.startswith(">"):
            continue
        n = figures(p)
        if n > MAX_FIGURES_PER_PARAGRAPH:
            out.append(f"craft: paragraph {i + 1} carries {n} figures (max {MAX_FIGURES_PER_PARAGRAPH}): {p[:90]!r}")
    if week > 0 and paras:
        if _OPENING_BAD.search(paras[0]):
            out.append(f"craft: opens on a date or a wearable reading: {paras[0][:90]!r} — open on what he did, chose or said")
        first_two = " ".join(re.split(r"(?<=[.!?])\s+", " ".join(paras[:2]))[:3])
        if not re.search(r"\bDay\s+\d+\b|\bday\s+\w+\b", first_two, re.IGNORECASE):
            out.append("craft: the opening does not tell a stranger which day of the experiment this is")
        if weight_known and not _WEIGHT_WORD.search(first_two):
            out.append("craft: the opening does not say which way the scale went — the weight belongs in the first two sentences")
    return out


def top_line_findings(top_line: str) -> List[str]:
    """The dek's plain-English top line: two short sentences a stranger reads in five seconds — no device names, no
    wearable or statistics jargon, no more figures than a paragraph may carry."""
    s = (top_line or "").strip()
    if not s:
        return []
    out: List[str] = []
    for m in _JARGON.finditer(s):
        out.append(f"top line: {m.group(0)!r} is jargon a stranger cannot read — say it in plain words")
    sentences = [x for x in re.split(r"(?<=[.!?])\s+", s) if x.strip()]
    if len(sentences) > TOP_LINE_MAX_SENTENCES:
        out.append(f"top line: {len(sentences)} sentences (max {TOP_LINE_MAX_SENTENCES})")
    words = len(s.split())
    if words > TOP_LINE_MAX_WORDS:
        out.append(f"top line: {words} words (max {TOP_LINE_MAX_WORDS}) — a stranger reads it in five seconds")
    n = figures(s)
    if n > MAX_FIGURES_PER_PARAGRAPH:
        out.append(f"top line: {n} figures (max {MAX_FIGURES_PER_PARAGRAPH}) — the scoreboard carries the rest")
    return out


def segment_findings(turns: List[Dict[str, Any]]) -> List[str]:
    """The recurring segments, named aloud and in the brief's order ("The call I got wrong" before "What we don't know yet")."""
    lines = [str(t.get("line") or "") for t in turns]
    at: Dict[str, Optional[int]] = {}
    for name, rx in SEGMENTS:
        at[name] = next((i for i, line in enumerate(lines) if rx.search(line)), None)
    out = [f"craft: the episode never names the segment {name!r}" for name, i in at.items() if i is None]
    first, second = (name for name, _rx in SEGMENTS)
    if at[first] is not None and at[second] is not None and at[first] > at[second]:
        out.append(f"craft: {second!r} runs before {first!r} — the segments go in that order")
    return out


def episode_findings(turns: List[Dict[str, Any]], *, segments: bool = False) -> List[str]:
    """Craft findings for one episode's turns. ``segments``: hold it to the recurring segments (a numbered week)."""
    out: List[str] = segment_findings(turns) if segments else []
    text = " ".join(str(t.get("line") or "") for t in turns)
    out += banned(text)
    words = len(text.split())
    lo, hi = EPISODE_WORDS
    if not lo <= words <= hi:
        out.append(f"craft: episode is {words} spoken words; the standard is {lo}-{hi}")
    total = 0
    for i, t in enumerate(turns):
        n = figures(str(t.get("line") or ""))
        total += n
        if n > MAX_FIGURES_PER_TURN:
            out.append(f"craft: turn {i} carries {n} figures (max {MAX_FIGURES_PER_TURN}): {str(t.get('line'))[:80]!r}")
        if t.get("speaker") == "elena" and len(str(t.get("line") or "").split()) > 110:
            out.append(f"craft: Elena's turn {i} runs {len(str(t.get('line')).split())} words (aim under 80)")
    if total > MAX_FIGURES_PER_EPISODE:
        out.append(f"craft: {total} figures across the episode (max {MAX_FIGURES_PER_EPISODE}) — round, gloss, or move to the post")
    if turns and len(str(turns[0].get("line") or "").split()) > 70:
        out.append("craft: the cold open runs past 70 words")
    return out


def callback_findings(text: str, previous: Dict[int, str]) -> List[str]:
    """A sentence that recalls an earlier week ('Week 1', 'last week') must not carry a figure that week never said.
    ``previous`` maps week number → that installment's text (post + episode)."""
    out: List[str] = []
    if not previous:
        return out
    last = max(previous)
    for sent in re.split(r"(?<=[.!?])\s+", text or ""):
        refs = [int(m) for m in re.findall(r"\bWeek\s+(\d+)\b", sent)]
        if re.search(r"\blast week\b", sent, re.IGNORECASE):
            refs.append(last)
        for wk in {r for r in refs if r in previous}:
            for num in _NUM.findall(_CALENDAR.sub(" ", sent)):
                if num.replace(",", "") not in previous[wk].replace(",", ""):
                    out.append(f"callback: {num!r} in a sentence recalling Week {wk} does not appear in Week {wk}: {sent[:110]!r}")
    return out


# ── the scoreboard (rendered by code, never by the model) ────────────────────


def scoreboard(dossier: Dict[str, Any], ledger: Dict[str, Any]) -> Dict[str, Any]:
    """The facts a returning reader checks first, computed from the dossier and the series record."""
    w = dossier.get("weight") or {}
    t = dossier.get("training") or {}
    p = dossier.get("predictions") or {}
    bets = [b for b in ledger.get("bets", []) if b.get("result") in ("right", "wrong")]
    rec = p.get("record_to_date_by_coach") or {}
    board = sorted(
        ((name, r.get("right", 0), r.get("wrong", 0)) for name, r in rec.items() if r.get("right", 0) + r.get("wrong", 0)),
        key=lambda x: (-(x[1] / max(1, x[1] + x[2])), -x[1]),
    )
    return {
        "day": ((dossier.get("window") or {}).get("experiment_days") or "").split(" to ")[-1],
        "weight_from": (w.get("first_weigh_in") or {}).get("lbs"),
        "weight_now": (w.get("week_end") or {}).get("lbs"),
        "lost_total": abs(w["total_change_lbs"]) if w.get("total_change_lbs") is not None else None,
        "to_next_waypoint": w.get("lbs_to_next_waypoint"),
        "next_waypoint": (w.get("next_plan_waypoint") or {}).get("lbs"),
        "training_streak_days": t.get("consecutive_training_days_through_week_end"),
        "bets_right": sum(1 for b in bets if b["result"] == "right"),
        "bets_wrong": sum(1 for b in bets if b["result"] == "wrong"),
        "coach_board": [{"coach": n.replace("Dr. ", ""), "right": r, "wrong": wr} for n, r, wr in board],
    }


def scoreboard_line(sb: Dict[str, Any]) -> str:
    """One line a stranger can read in five seconds — the dek's second line."""
    parts = []
    if sb.get("day"):
        parts.append(sb["day"])
    if sb.get("weight_from") and sb.get("weight_now"):
        if sb["weight_from"] == sb["weight_now"]:
            parts.append(f"{sb['weight_now']:g} lb at the first weigh-in")
        else:
            parts.append(f"{sb['weight_from']:g} → {sb['weight_now']:g} lb")
    if sb.get("training_streak_days"):
        parts.append(f"{sb['training_streak_days']} straight training days")
    if sb.get("bets_right") or sb.get("bets_wrong"):
        parts.append(f"on-air bets {sb['bets_right']}–{sb['bets_wrong']}")
    if sb.get("coach_board"):
        parts.append("coaches: " + ", ".join(f"{c['coach'].split()[-1]} {c['right']}–{c['wrong']}" for c in sb["coach_board"][:4]))
    return " · ".join(parts)


# ── the spoken word (what the TTS engine actually receives) ──────────────────


def tts_clean(line: str) -> str:
    """Normalise a script line for the voice engine: no stray backslashes, tabs or mid-sentence line breaks
    (four of five first-season scripts carried them), spaced em-dashes, one space between words."""
    # a lone backslash is the model's mangled em-dash (" \\ " where " — " was meant) — restore the dash, never drop it
    s = re.sub(r"\s+\\\s+", " — ", line or "").replace("\\", " ").replace("\t", " ")
    s = re.sub(r"\s*\n\s*", " ", s)
    s = re.sub(r"\s*—\s*", " — ", s)
    s = re.sub(r"\s{2,}", " ", s)
    return s.strip()


def clean_turns(turns: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [{**t, "line": tts_clean(str(t.get("line") or ""))} for t in turns]


def owner_voice_rules() -> str:
    return (
        "OWNER VOICE: answers he sent by replying to the week's questions. Quote at most two short lines exactly; never "
        "alter, extend or paraphrase them into quotes; quote the 'quotable' form when present (spelling fixed, words his); "
        "never comment on how he typed; never quote anything he marked off the record; never infer feelings he did not state."
    )


def season_spine() -> Dict[str, Any]:
    """The season's standing question and its live throughlines — the editor's frame, carried by the ledger."""
    return {
        "season_question": "He lost 115 pounds once and it came back. Is this the year it doesn't?",
        "throughlines": [
            {"id": "the_streak", "question": "Will he take a rest day before his body takes one for him?"},
            {"id": "sensor_vs_self", "question": "Do the instruments and the man agree about how he is?"},
            {"id": "the_machines_scoreboard", "question": "Whose model of him is right — and which coach changes their mind?"},
        ],
    }


def first_sentence(text: str) -> Optional[str]:
    m = re.split(r"(?<=[.!?])\s+", (text or "").strip(), maxsplit=1)
    return m[0] if m else None


# ── the quote gate ───────────────────────────────────────────────────────────
#
# The 2026-10-01 fact audit found at least ten chronicle quotes attributed to coaches that are in none of their
# stored outputs. In the written chronicle a quotation mark is a claim: these were the words. So quotation marks
# and blockquotes go only around exact text the platform holds — a coach's stored summary or recommendation, the
# sealed predictions, or the owner's own reply. Everything else is paraphrase, unquoted. (The Panel's spoken guest
# is the show's disclosed form and is exempt.)

_QUOTED = re.compile(r"[“\"]([^”\"]{25,600})[”\"]")


def _norm(s: str) -> str:
    s = (s or "").replace("’", "'").replace("‘", "'").replace("—", "-").replace("–", "-")
    return " ".join(re.sub(r"[^a-z0-9%' -]+", " ", s.lower()).split())


def quote_corpus(dossier: Dict[str, Any]) -> str:
    """Every string the platform holds that may legitimately be quoted."""
    parts: List[str] = []
    for c in dossier.get("coaches_this_week") or []:
        parts += [str(c.get("latest_public_summary") or ""), str(c.get("latest_key_recommendation") or "")]
    for a in (dossier.get("owner_voice") or {}).get("answers", []) or []:
        if not a.get("off_record"):
            parts += [str(a.get("answer") or ""), str(a.get("quotable") or "")]
    preds = dossier.get("predictions") or {}
    for p in preds.get("pre_registered", []) or []:
        parts.append(str(p.get("claim") or ""))
    for g in preds.get("graded_this_week", []) or []:
        parts.append(str(g.get("claim") or ""))
    plan = dossier.get("plan") or {}
    parts.append(str(plan.get("plan_note") or ""))
    return _norm(" \n ".join(parts)) or ""


def quote_findings(body: str, corpus: str) -> List[str]:
    """Quoted spans and blockquotes in a chronicle body that are not exact text the platform holds."""
    out: List[str] = []
    spans: List[str] = []
    for para in re.split(r"\n\s*\n", body or ""):
        p = para.strip()
        if p.startswith(">"):
            spans.append(" ".join(line.lstrip("> ").strip() for line in p.splitlines()).strip().strip('"“”'))
    spans += [
        m.group(1) for m in _QUOTED.finditer(body or "") if not (body or "")[max(0, m.start() - 3) : m.start()].strip().startswith(">")
    ]
    for span in spans:
        for sent in re.split(r"(?<=[.!?])\s+", span):
            # an ellipsis marks a cut: each fragment must still be exact
            frags = [_norm(f).strip(" -") for f in re.split(r"\s*(?:…|\.\.\.)\s*", sent)]
            frags = [f for f in frags if len(f.split()) >= 4]
            if not frags or sum(len(f.split()) for f in frags) < 6:
                continue
            if any(f not in corpus for f in frags):
                out.append(f"quote: not exact words the platform holds — paraphrase it without quotation marks: {sent[:110]!r}")
    return out


def repeat_findings(text: str, previous: Dict[int, str], owner_lines: Iterable[str] = (), n: int = 7) -> List[str]:
    """Lines a returning reader or listener has already heard (the producer's re-score: two coaches sharing whole sentences
    across episodes; the same owner quote in two weeks). Any n-word run from an earlier installment, and any of his quoted
    lines already used in one, is a finding."""
    out: List[str] = []
    if not previous:
        return out

    def grams(s: str) -> set:
        w = re.findall(r"[a-z0-9']+", (s or "").lower())
        return {" ".join(w[i : i + n]) for i in range(len(w) - n + 1)}

    mine = grams(text)
    for wk, prev in sorted(previous.items()):
        shared = sorted(mine & grams(prev))
        if shared:
            out.append(f"repeat: {len(shared)} {n}-word run(s) already used in Week {wk}, e.g. {shared[0]!r} — say it new or cut it")
    for line in owner_lines:
        frag = " ".join(re.findall(r"[a-z0-9']+", (line or "").lower())[:8])
        if frag and frag in _norm(text) and any(frag in _norm(p) for p in previous.values()):
            out.append(f"repeat: his line {frag!r}… was already quoted in an earlier installment — use a different line or paraphrase")
    return out
