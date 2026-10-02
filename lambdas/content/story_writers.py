"""content/story_writers.py — Elena's post and the Panel episode, written from one story budget (#4535, #4536).

Both writers take the same three inputs — the week's dossier (every number they may use),
the desk's story budget (what the week's story is), and the season ledger (what the series
has already told) — plus the previous installment, so a returning reader is picked up where
they left off and a cold reader is oriented in a sentence. The blog and the show then report
one week from two angles: Elena's long-form feature, and Elena hosting the coach the desk
chose for the week.

Each writer returns (text-or-turns, stop_reason); ``story_checks`` decides whether it stages.
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

from ai.model_defaults import NARRATIVE_MODEL as WRITER_MODEL  # noqa: E402 — the one narrative default (#4275)

from content import story_craft, story_ledger

CHRONICLE_MAX_TOKENS = 7000  # ~1,100-1,500 words lands near 2,500 tokens; the ceiling is headroom, never the target
EPISODE_MAX_TOKENS = 8000

CHRONICLE_FOOTER = r"\*Week \d+ of The Measured Life\*|\*Prologue — The Measured Life\*"

SEASON_RULES = """THE SEASON. This is one installment of a continuous series that follows a year-long experiment week by week.
A reader may arrive at any installment cold, or may have read every one. Serve both:
- Orient the cold reader in a sentence or two, early and naturally — who he is, where the experiment stands
  (the day number, the direction of travel) — without re-telling the whole story.
- Reward the returning reader: pick up the open threads by name, pay off what last week set up, and let
  resolved threads close with a line. Never restate last week's thesis as if it were new.
- Write as a reporter seeing this for the first time, week by week. Do not know the future: nothing after this
  week's last date exists yet.
- Follow the story budget: its lead leads, its secondary stories support, its omissions stay out, its tone holds.
  The budget is the desk's call; your job is to make it read like a human wrote it with all the data in front of them.

FACTS (absolute):
- Every figure you print must be in the dossier. Round honestly (56.8 can be "nearly 57"). Never compute a new
  number the dossier does not carry (no differences, no estimates such as maintenance calories) — that holds for
  numbers written as words too.
- Counts are facts too: when you say how many (predictions, coaches, instruments, sessions, days), use the
  dossier's count. Put quotation marks only around the fictional team's spoken words — never around a document,
  a plan, or "people".
- The coaches, like Elena, are AI personas — characters with domains and track records. Say so when you
  introduce them to a cold reader.
- Never mention the machinery behind this series: no "desk", "dossier", "budget", "ledger", "flagged". Report what
  the data shows and what the team said, as a journalist would.
- Plan targets are the dossier's "targets_from_plan" (the sealed plan). Use no other target.
- The training sessions are programmed by the coaching team; describe volume as the programme being executed.
- A date listed under not_yet_exported is not yet exported — say so plainly if it matters, never call it silence.
- Recovery, HRV and resting heart rate describe the night before; workouts and meals describe the day.
- Correlation is not cause. Say "alongside", "in the same week", "while" — not "because", "led to", "thanks to".
- Uncertainty is part of the reporting: a single night is a single night; a week of data is a week.

PRIVACY (absolute):
- No cycle, reset, restart or attempt counts, ever. The frame is THE experiment and the day.
- Never name a vice or substance. The journal is off the record: its weather may inform you, its words and its
  specifics may not (no job details, no third parties, no family members, no partner).
- No real-world experts, authors or public figures. Only the fictional team appears.
- No genome identifiers."""

ELENA_VOICE = """You are Elena Voss, the embedded journalist writing "The Measured Life", a weekly long-form chronicle of one
man's year-long health experiment. You are an AI narrator — a character written from Matthew's data — and you have
said so plainly in the prologue; you never claim a career, byline or employer outside this series.

VOICE: literary, observant, wry, compassionate without being soft. Third person; Matthew is your subject. A
long-form magazine feature writer: concrete details, specific moments, show don't tell. You explain wearables and
scores in half a sentence the first time, for a reader who knows nothing about them.

CRAFT:
- Open on one specific, real moment from the dossier (a session, a morning's number, a meal, a walk) — never a
  summary, never "This week".
- One thesis per installment, taken from the budget's lead. Synthesis, not a day-by-day walk-through.
- The coaches are characters with track records. When the budget features a coach, give them a few lines in
  blockquotes (> ) that say something you could not — a call they made, what they now think, where they disagree.
- Numbers illuminate; they never catalogue. Two or three telling figures beat ten.
- No "It isn't X — it's Y" pivots, no triads for rhythm, no one-line punchline paragraphs more than once, no
  transformation clichés, no emoji, no headers, no bullet points.
- Close with something unresolved: a question the next week will answer, or a callback."""

EPISODE_VOICE = """You write the script for "The Measured Life — The Panel", a weekly two-voice podcast that reports the same
week as the chronicle. ELENA VOSS (an AI journalist, the host) talks with ONE coach from the team — the guest the
desk chose — about what the week's data showed. Two people with all the numbers in front of them, talking like
colleagues: warm, specific, sometimes disagreeing, never a lecture.

SHOW SHAPE (1,250-1,450 spoken words, about 9 minutes):
1. Cold open — Elena, one vivid real moment from the week, two or three sentences.
2. Welcome — Elena names the show, the day number of the experiment, and the guest (name and what they cover).
   One or two sentences of "previously" for a cold listener.
3. Last week's bet — score it honestly with the numbers ("none" in the budget means skip this segment).
4. The lead story — a real conversation: the guest brings their read, Elena pushes on it.
5. The guest's own record — a call they made that was graded (right or wrong), and what they make of it now.
   Coaches who were wrong say so plainly; that is how they earn trust.
6. The secondary story — shorter.
7. The new bet — Elena states it as the desk set it, as a checkable claim about the coming week.
8. Close — one line that leaves the next week open, then "I'm Elena Voss. This has been The Measured Life."

SPOKEN-WORD RULES (the episode is held at render if it breaks these):
- No body-weight figures with units — no "pounds", "lbs" or "kg" next to a number. Talk about the scale's
  direction and its pace against the plan instead.
- No family members, partner, grief or loss words.
- No report-card tone ("you failed", "fell short", "disappointing", "no excuse").
- No causal phrasing: never "caused", "led to", "resulted in", "thanks to", "because of the/his", "is why".
- Write numbers the way people say them ("about seventy-eight percent" or "78 percent", "fifty-one milliseconds").
- Speaker ids: "elena" for Elena; "coach" for the guest. Every line is one turn, 1-4 sentences."""

_TURN = {
    "type": "object",
    "properties": {"speaker": {"type": "string", "enum": ["elena", "coach"]}, "line": {"type": "string"}},
    "required": ["speaker", "line"],
    "additionalProperties": False,
}
EPISODE_SCHEMA = {
    "type": "object",
    "properties": {"title": {"type": "string"}, "excerpt": {"type": "string"}, "turns": {"type": "array", "items": _TURN}},
    "required": ["title", "excerpt", "turns"],
    "additionalProperties": False,
}


def _invoke(body: Dict[str, Any], invoke: Optional[Callable[..., Dict[str, Any]]]) -> Dict[str, Any]:
    if invoke is None:
        from ai import bedrock_client

        return bedrock_client.invoke_with_retry(body, WRITER_MODEL)
    return invoke(body, WRITER_MODEL)


def _text(resp: Dict[str, Any]) -> str:
    return "".join(b.get("text", "") for b in resp.get("content", []) if b.get("type") == "text").strip()


def _context(dossier: Dict[str, Any], budget: Dict[str, Any], ledger: Dict[str, Any], week: int, previous: Optional[str]) -> str:
    view = story_ledger.ledger_for_prompt(ledger, week)
    prev = f"THE PREVIOUS INSTALLMENT (for continuity — do not repeat it):\n{previous}\n\n" if previous else ""
    return (
        f"STORY BUDGET (the desk's call for week {week}):\n{json.dumps(budget, indent=1)}\n\n"
        f"SEASON LEDGER:\n{json.dumps(view, indent=1, default=str)}\n\n"
        f"{prev}"
        f"WEEK {week} DOSSIER (the only figures you may use):\n{json.dumps(dossier, indent=1, default=str)}"
    )


def write_chronicle(
    dossier: Dict[str, Any],
    budget: Dict[str, Any],
    ledger: Dict[str, Any],
    *,
    week: int,
    previous: Optional[str] = None,
    fix: Optional[List[str]] = None,
    prior_draft: Optional[str] = None,
    invoke: Optional[Callable[..., Dict[str, Any]]] = None,
) -> Tuple[str, Optional[str]]:
    """(markdown, stop_reason). The markdown is: the title on line 1, a blank line, the body, then
    ``---`` and the week footer. ``fix`` + ``prior_draft`` turn the call into a corrective rewrite."""
    footer = "*Prologue — The Measured Life*" if week == 0 else f"*Week {week} of The Measured Life*"
    fmt = (
        "FORMAT: line 1 is the title in double quotes (your editorial choice). Line 2 blank. Then the body, "
        f"900-1,200 words of clean prose. Then a line with --- and finally the line {footer}"
    )
    messages = [{"role": "user", "content": _context(dossier, budget, ledger, week, previous) + "\n\n" + fmt}]
    if fix and prior_draft:
        messages += [
            {"role": "assistant", "content": prior_draft},
            {
                "role": "user",
                "content": "The desk's checks found these problems. Rewrite the whole installment fixing every one, changing nothing else that works:\n- "
                + "\n- ".join(fix),
            },
        ]
    resp = _invoke(
        {
            "system": ELENA_VOICE + "\n\n" + SEASON_RULES + "\n\n" + story_craft.CHRONICLE_RULES + "\n\n" + story_craft.owner_voice_rules(),
            "messages": messages,
            "max_tokens": CHRONICLE_MAX_TOKENS,
            "temperature": 0.7,
        },
        invoke,
    )
    return _text(resp), resp.get("stop_reason")


def split_title(markdown: str) -> Tuple[str, str]:
    """('Title', body) from the writer's format."""
    lines = (markdown or "").strip().splitlines()
    if not lines:
        return "", ""
    title = lines[0].strip().strip('"“”').strip()
    return title, "\n".join(lines[1:]).strip()


def write_episode(
    dossier: Dict[str, Any],
    budget: Dict[str, Any],
    ledger: Dict[str, Any],
    *,
    week: int,
    chronicle: str,
    previous_episode: Optional[str] = None,
    guest: Optional[Dict[str, Any]] = None,
    fix: Optional[List[str]] = None,
    prior: Optional[Dict[str, Any]] = None,
    invoke: Optional[Callable[..., Dict[str, Any]]] = None,
) -> Tuple[Dict[str, Any], Optional[str]]:
    """({title, excerpt, turns}, stop_reason) for the week's episode."""
    g = guest or {}
    guest_line = f"THE GUEST: {g.get('name')} — {g.get('title')}. Lens: {g.get('lens')}. {g.get('bio')} Pronouns: {g.get('pronouns')}."
    ctx = _context(dossier, budget, ledger, week, previous_episode)
    user = f"{guest_line}\n\nTHIS WEEK'S CHRONICLE (Elena's post — the show reports the same week, in conversation, without reading it out):\n{chronicle}\n\n{ctx}"
    messages: List[Dict[str, Any]] = [{"role": "user", "content": user}]
    if fix and prior:
        messages += [
            {"role": "assistant", "content": json.dumps(prior)},
            {"role": "user", "content": "The checks found these problems. Return the whole corrected script:\n- " + "\n- ".join(fix)},
        ]
    body: Dict[str, Any] = {
        "system": EPISODE_VOICE + "\n\n" + SEASON_RULES + "\n\n" + story_craft.EPISODE_RULES + "\n\n" + story_craft.owner_voice_rules(),
        "messages": messages,
        "max_tokens": EPISODE_MAX_TOKENS,
        "temperature": 0.7,
    }
    body["output_config"] = {"format": {"type": "json_schema", "schema": EPISODE_SCHEMA}}
    resp = _invoke(body, invoke)
    text = _text(resp)
    try:
        ep = json.loads(text)
        ep["turns"] = story_craft.clean_turns(ep.get("turns", []))
        return ep, resp.get("stop_reason")
    except ValueError:
        return {"title": "", "excerpt": "", "turns": []}, resp.get("stop_reason") or "unparseable"


# ── the spoken-word gate (mirrors the Panel renderer's fail-closed checks) ───

_BODY_NUM_RE = re.compile(r"\b\d{2,3}(?:\.\d+)?\s?(?:lb|lbs|pound|pounds|kg|kilo|kilos|kilograms)\b", re.I)
_GRIEF_RE = re.compile(
    r"\b(?:grief|grieving|died|passed away|funeral|cancer|terminal|hospice|"
    r"my (?:mom|mum|dad|mother|father|parent|parents|wife|husband|girlfriend|boyfriend|partner|brother|sister|son|daughter|family))\b",
    re.I,
)
_FAMILY_RE = re.compile(r"\b(?:girlfriend|boyfriend|partner|wife|husband|mother|father|mom|dad|sister|brother)\b", re.I)
_REPORTCARD_RE = re.compile(
    r"\b(?:you should have|you failed|you only managed|disappoint\w*|need to do better|not good enough|fell short|slacked|lazy|no excuse|let yourself down)\b",
    re.I,
)
_CAUSAL_RE = re.compile(
    r"\b(?:caused|because of (?:the|his|her|your)|led to|resulted in|made (?:him|her|them|you) |thanks to|is why (?:his|her|the|your))\b",
    re.I,
)


def spoken_word_findings(turns: List[Dict[str, Any]], body_weights: Optional[List[float]] = None) -> List[str]:
    """The renderer's checks, run before staging so a script is never written only to be held.
    ``body_weights`` are the dossier's weigh-ins: a spoken body weight is a body number with or without its unit."""
    findings: List[str] = []
    bw = {f"{w:g}" for w in (body_weights or [])} | {str(int(round(w))) for w in (body_weights or [])}
    if not turns:
        return ["episode: no turns"]
    for i, t in enumerate(turns):
        line = str(t.get("line") or "")
        for name, rx in (
            ("body-number", _BODY_NUM_RE),
            ("grief/family", _GRIEF_RE),
            ("family", _FAMILY_RE),
            ("report-card tone", _REPORTCARD_RE),
            ("causal phrasing", _CAUSAL_RE),
        ):
            m = rx.search(line)
            if m:
                findings.append(f"turn {i} ({t.get('speaker')}): {name}: {m.group(0)!r}")
        for num in re.findall(r"\b\d{3}(?:\.\d+)?\b", line):
            if num in bw:
                findings.append(
                    f"turn {i} ({t.get('speaker')}): body-number: {num!r} is a weigh-in — talk about direction and pace, not the figure"
                )
    if turns[0].get("speaker") != "elena":
        findings.append("episode: the cold open belongs to Elena")
    if "this has been the measured life" not in str(turns[-1].get("line", "")).lower():
        findings.append("episode: the sign-off line is missing from the last turn")
    return findings


def episode_text(ep: Dict[str, Any]) -> str:
    return "\n\n".join(f"{t['speaker'].upper()}: {t['line']}" for t in ep.get("turns", []))


# ── the fact desk (Margaret Calloway's read, structured) ─────────────────────
#
# The regex gates catch shapes (a count, a cut-off ending, a figure not in the dossier). They cannot
# catch a wrong COUNT written in words ("twelve calls" when sixteen were filed), a misattributed
# prediction, a self-reference that breaks the timeline, or an invented quote. A human desk catches
# those with a fact-checker; this is that read — every factual claim held against the dossier.

FACT_MODEL = WRITER_MODEL
_FINDING = {
    "type": "object",
    "properties": {"claim": {"type": "string"}, "problem": {"type": "string"}, "fix": {"type": "string"}},
    "required": ["claim", "problem", "fix"],
    "additionalProperties": False,
}
FACT_SCHEMA = {
    "type": "object",
    "properties": {"findings": {"type": "array", "items": _FINDING}},
    "required": ["findings"],
    "additionalProperties": False,
}

FACT_RUBRIC = """You are Margaret Calloway, the series editor, doing the fact read on one installment before it runs.
Hold EVERY factual statement in the text against the dossier. Report only real problems:
- a count, figure, date, name, title or attribution the dossier contradicts or does not support (counts written as words too);
- a prediction attributed to the wrong person, or a person said to have done something the dossier does not show;
- a statement about the future the installment's date cannot know, or a timeline that does not hold (e.g. a prologue
  referring to "the prologue" as something past);
- invented detail presented as fact: an attributed quote from a document or a third party, a reaction from "people",
  a scene, a device, a habit the dossier does not carry. (Quotes from the fictional coaches are the series' form and
  are fine when what they say is consistent with their dossier record.)
- anything that breaks the privacy rules: a cycle/reset/attempt count, a vice, a family member or partner, journal specifics.
Ordinary common knowledge is not invented detail: how a named device is worn or works, what a named metric means,
what a plan term means. Do not report style. Do not report rounding that stays honest. Do not report a statement you checked and found
correct — return ONLY claims that must change. If the installment is clean, return an empty list.
For each finding give the exact claim, the problem, and the corrected wording."""


def fact_check(
    text: str, dossier: Dict[str, Any], *, context: Optional[Dict[str, Any]] = None, invoke: Optional[Callable[..., Dict[str, Any]]] = None
) -> List[str]:
    """Findings (as gate strings) from the fact read. An unreadable reply is itself a finding — never a pass.
    ``context`` carries the series' own record the dossier does not: last week's open bet, this week's new
    bet and the previous titles — facts of the SERIES, which an installment may state."""
    ctx = f"SERIES RECORD (facts of the series itself — bets made on air, previous titles):\n{json.dumps(context or {}, indent=1, default=str)}\n\n"
    body = {
        "system": FACT_RUBRIC,
        "messages": [{"role": "user", "content": f"DOSSIER:\n{json.dumps(dossier, indent=1, default=str)}\n\n{ctx}INSTALLMENT:\n{text}"}],
        "max_tokens": 8000,
        "temperature": 0,
        "output_config": {"format": {"type": "json_schema", "schema": FACT_SCHEMA}},
    }
    if invoke is None:
        from ai import bedrock_client

        resp = bedrock_client.invoke_with_retry(body, FACT_MODEL)
    else:
        resp = invoke(body, FACT_MODEL)
    if resp.get("stop_reason") != "end_turn":
        return [f"fact-read: incomplete (stop_reason={resp.get('stop_reason')}) — the installment is unverified"]
    try:
        found = json.loads(_text(resp)).get("findings", [])
    except ValueError:
        return ["fact-read: unparseable — the installment is unverified"]
    _noop = re.compile(
        r"(?i)\bno (?:change|error|issue|correction)s? (?:is )?(?:needed|found|here|required|necessary)\b|\bskipping\b|\bthis is accurate\b"
    )
    real = [f for f in found if not _noop.search(f"{f.get('problem', '')} {f.get('fix', '')}")]
    return [f"fact: {f['claim']!r} — {f['problem']} → {f['fix']}" for f in real]
