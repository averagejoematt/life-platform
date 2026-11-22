"""content/story_editor.py — the Story Desk's editor: make the draft better, never make it say more (#6179).

Owner ruling 2026-11-22: "An editor should make the writing better; a verifier should establish that the result is
true. They have different jobs." Before this module the craft gate (``story_craft``) failed every desk-written week and
failing did not improve the draft: the writer got one corrective rewrite against a list of style findings, the residual
list became a ``craft_hold``, and the weeks piled up held.

This is the editor. It takes the writer's draft and the SAME evidence packet the writer had (``story_writers``'s
context: the desk's budget, the season ledger, the previous installment and the week's dossier) and returns a revised
draft aimed at what the 2026-11-21 editorial review found wrong with the published chapters: a list of readings in
place of one question followed through; the subject re-introduced from scratch every week; too many figures in a
paragraph; coach wins credited without asking whether a guess that nothing changes would have scored the same; the
"X is the story" and "not X, it's Y" tics; flattery; and, worst, an invented scene or interview.

What it may not do is add a claim. That is enforced in code, not asked for in a prompt: ``new_claims`` holds every
number, date word, name, quotation and scene/feeling/causal marker in a revision against the draft and the packet,
and a revision that carries anything neither holds is DISCARDED (the previous version goes forward). The pipeline
also discards a revision that adds a deterministic hard-gate finding the input did not have
(``story_pipeline._Gates.post_deterministic``). The hard gates themselves are not here: they run, unchanged, on
whatever text the editor hands back (``story_pipeline._write_post_edited``).

Bounded: at most ``MAX_ROUNDS`` model calls; then it stops and the best accepted version goes forward with the
editor's remaining notes attached as ADVISORY notes for the owner — never a blocker, and never a substitute for his
approval click.

Model: a different model from the writer (``story.editor`` route; the writer is ``story.writer``), spent under the
``chronicle`` budget feature (band 2, reader narrative). If the two routes ever resolve to the same model, the edit is
skipped rather than run as self-review. Elena's voice comes from ``content.elena_canon``; this module never restates it.

Switch: ``STORY_EDITOR`` (default ``off``). Off is today's pipeline exactly; nothing here runs.
"""

from __future__ import annotations

import json
import os
import re
from collections import Counter
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple

from ai.model_routing import model_for  # noqa: E402 — #4770: the one model registry

from content import elena_canon, story_checks, story_craft, story_writers

EDITOR_MODEL = model_for("story.editor")
BUDGET_FEATURE = "chronicle"  # band 2 (reader narrative), the same feature the weekly installment spends under
SWITCH_ENV = "STORY_EDITOR"
MAX_ROUNDS = 2  # the owner's bound: at most two editor calls a week, then the best version goes forward
EDITOR_MAX_TOKENS = 6000  # a 900-1,200-word body plus notes lands near 2,500 tokens; the ceiling is headroom
NOTES_MARKER = "=== EDITOR NOTES ==="
ADVISORY_PREFIX = "editor note (advisory): "
UNVERIFIED_PREFIX = "the editor's own remark (unverified): "
REVISED_NOTE = (
    "this draft was revised by the editor before the truth checks ran; the checks below ran on the revised text, "
    "and only your approval publishes it"
)


def enabled(environ: Optional[Dict[str, str]] = None) -> bool:
    """True only when the switch is explicitly on. Anything else — unset, ``off``, a typo — is today's pipeline."""
    env = os.environ if environ is None else environ
    return str(env.get(SWITCH_ENV, "off")).strip().lower() in ("on", "1", "true", "yes")


# ── the brief: what the editor is for ────────────────────────────────────────

EDITOR_BRIEF = """You are the line and structure editor of The Measured Life. The writer has drafted this week's installment
in Elena Voss's voice (her canon follows). Your job is to make the draft BETTER WRITING. You are not the fact-checker:
a separate verifier checks the result against the evidence after you, and code rejects any revision of yours that says
something the draft and the evidence packet do not already say.

WHAT A BETTER EDITION LOOKS LIKE:
- ONE QUESTION, FOLLOWED THROUGH. Find the single question this week's evidence can best speak to (usually the desk's
  lead) and make every paragraph serve it. Readings that do not bear on it move to a short passing clause or go. A list
  of readings is not a chapter.
- NO RE-INTRODUCTION. The reader has read last week. Do not open by re-explaining who he is or what the experiment is
  ("a man running a year-long experiment"). Do not re-introduce a coach's job title after their first appearance this
  season; use the surname.
- FEWER FIGURES. At most three figures in a paragraph; prefer one that matters. Cut figures, never add them.
- SET A COACH'S RIGHT CALL AGAINST THE OBVIOUS. When the draft credits a coach with a right call, check the packet: if it
  shows the reading on the day the call was made, say plainly whether simply repeating that reading (a guess that
  nothing changes) would also have landed. If the packet does not show it, do not claim skill either way.
- NO TICS. No "X is the story" / "the story is", no "it isn't X, it's Y" pivot, no triads for rhythm, no aphorism closers.
- NO FLATTERY of him or of the AI: no "deserves a moment", "earned", "meticulous", "impressive". Credit is one plain
  sentence.
- NOTHING INVENTED: no scene, sensory detail, interview, conversation ("when I reached him", "he paused"), feeling,
  motive or explanation the draft or the packet does not carry. Where the record does not say why, the chapter says so
  once and leaves the reason alone.
- KEEP what is true and already good: exact quotations stay exact and stay attributed; the title stays; the dates and
  figures you keep stay exactly as written.

HARD LIMITS (a revision that breaks one is thrown away and the previous version runs instead):
- Use only facts already in the draft or the evidence packet. Add no number, date, name, quotation, scene, feeling or
  cause. You may cut anything. You may reorder anything. You may rephrase anything that is not inside quotation marks.
- Keep the format: line 1 the title in double quotes (unchanged), a blank line, the body, then a line with --- and the
  same footer line the draft ends with.
- Do not write headers, bullet points, or any note to the reader about editing.

After the revised installment, write a line containing exactly {MARKER} and then up to five short "- " lines naming
what still weakens the piece that you could not fix without new facts (for the owner). If nothing, write "- none".""".replace(
    "{MARKER}", NOTES_MARKER
)


def system_prompt() -> str:
    """Byte-stable per canon version: the brief, Elena's canon (imported, never restated) and the series' fact and
    privacy rules the writer was given."""
    return EDITOR_BRIEF + "\n\nELENA'S CANON (the voice to hold):\n" + elena_canon.voice_block() + "\n\n" + story_writers.SEASON_BRIEF


# ── the deterministic notes the editor works from ────────────────────────────
#
# The craft gate's own findings (story_craft) become the editor's input, plus detectors for what the editorial review
# found in the published chapters. None of these ever blocks a week; they are notes.

_REINTRO = re.compile(
    r"\b(?:Matthew|he)\s+is\s+(?:a\s+man|the\s+subject|running|attempting)\b|\byear-long\b[^.]{0,80}\bexperiment\b|\bfully\s+instrumented\b",
    re.IGNORECASE,
)
_IS_THE_STORY = re.compile(
    r"\b(?:is|was|remains|is\s+still)\s+the\s+(?:real\s+)?story\b|\bthe\s+(?:real\s+)?story\s+(?:this\s+week\s+)?is\b", re.I
)
_FLATTERY = re.compile(
    r"\bdeserves?\s+(?:a\s+moment|credit|praise)\b|\bearned\b|\bmeticulous(?:ly)?\b|\bimpressive(?:ly)?\b|\bremarkabl[ey]\b|"
    r"\badmirabl[ey]\b|\bheroic\b|\bto\s+his\s+credit\b|\bcommendabl[ey]\b",
    re.IGNORECASE,
)
_SCENE = re.compile(
    r"\bwhen\s+I\s+(?:reached|spoke|talked|asked|caught|met)\b|\b(?:he|she|they)\s+paused\b|\btold\s+me\b|\bI\s+asked\s+(?:him|her|them)\b|"
    r"\bsaid\s+to\s+me\b|\bover\s+(?:coffee|the\s+phone)\b|\bin\s+(?:an|our)\s+interview\b|\bI\s+(?:watched|saw)\s+him\b",
    re.IGNORECASE,
)
_CREDIT = re.compile(
    r"\b(?:landed|fared\s+better|within\s+(?:tolerance|(?:the|her|his|their)\s+band)|got\s+it\s+right|was\s+right|were\s+right|"
    r"called\s+it|right\s+call|correct(?:ly)?)\b",
    re.IGNORECASE,
)
_NOTHING_CHANGES_RE = re.compile(
    r"\bnothing\s+chang|\bno-change\b|\bdid\s+nothing\b|\bsimply\s+repeat|\brepeat(?:ed|ing)?\s+(?:the\s+)?(?:last|that|the\s+day|"
    r"Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)|\bbaseline\b|\bguess\b",
    re.IGNORECASE,
)


_BELOW_FLOOR = re.compile(rf"craft: body is (\d+) words; the standard is {story_craft.CHRONICLE_WORDS[0]}-")


def _paras(body: str) -> List[str]:
    return [
        p.strip()
        for p in re.split(r"\n\s*\n", body or "")
        if p.strip() and not p.strip().startswith(("---", "*Week", "*Prologue", "*Editor"))
    ]


def review_notes(body: str, dossier: Dict[str, Any]) -> List[str]:
    """What the editorial review found in the published chapters, detected in one body. Pure; notes only."""
    out: List[str] = []
    paras = _paras(body)
    week = int(dossier.get("week") or 0)
    if week > 1 and _REINTRO.search(" ".join(paras[:2])):
        out.append("the opening re-introduces the subject or the experiment from scratch; the reader has read last week")
    for m in _IS_THE_STORY.finditer(body or ""):
        out.append(f"the 'is the story' device stands in for an argument: {m.group(0)!r}")
    n = len(story_craft._ANTITHESIS.findall(body or ""))
    if n:
        out.append(f"{n} 'not X, it's Y' construction(s): say the thing directly")
    for m in _FLATTERY.finditer(body or ""):
        out.append(f"flattery: {m.group(0)!r} — credit is one plain sentence")
    for m in _SCENE.finditer(body or ""):
        out.append(f"a scene or interview the record cannot hold: {m.group(0)!r} — cut it")
    surnames = {str(c.get("name") or "").split()[-1] for c in dossier.get("roster") or [] if c.get("name")}
    for i, p in enumerate(paras):
        if any(re.search(rf"\b{re.escape(s)}\b", p) for s in surnames if s) and _CREDIT.search(p) and not _NOTHING_CHANGES_RE.search(p):
            out.append(
                f"paragraph {i + 1} credits a coach's call without the 'nothing changes' comparison: if the packet shows the "
                "reading on the day the call was made, say whether simply repeating it would also have landed"
            )
    return out


def craft_notes(
    body: str, *, dossier: Dict[str, Any], weight_known: bool, previous: Dict[int, str], owner_lines: Iterable[str]
) -> List[str]:
    """The craft gate's findings on one body, as the editor's input (style only; the quote and callback checks are hard
    gates and stay in the verifier)."""
    week = int(dossier.get("week") or 0)
    found = story_craft.chronicle_findings(body, week=week, weight_known=weight_known) + story_craft.repeat_findings(
        body, previous, list(owner_lines)
    )
    # A short chapter with one question is acceptable (the review's own finding); a word floor would only ask an editor
    # who may not add facts to pad. The ceiling stays a note.
    return [f for f in found if not ((m := _BELOW_FLOOR.match(f)) and int(m.group(1)) < story_craft.CHRONICLE_WORDS[0])]


# ── the mechanical no-new-claims check ───────────────────────────────────────

_NUM = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?(?![\w])")
_WORD_NUMS = {
    w: i
    for i, w in enumerate(
        "zero _ two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen "
        "eighteen nineteen twenty".split()
    )
    if w != "_"
}
_WORD_NUMS.update({"thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90, "hundred": 100})
_WORD_NUM_RE = re.compile(r"\b(" + "|".join(sorted(_WORD_NUMS, key=len, reverse=True)) + r")\b", re.IGNORECASE)
_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_MONTHS = (
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
)
_DATE_WORD_RE = re.compile(r"\b(" + "|".join(_WEEKDAYS + _MONTHS) + r")\b", re.IGNORECASE)
_ISO = re.compile(r"\b20\d\d-(\d\d)-\d\d\b")
_CAP = re.compile(r"\b[A-Z][A-Za-z’'\-]*[A-Za-z]\b|\b[A-Z]\b")
# The quote spans a revision may carry: double quotes and blockquote paragraphs (story_craft's own shapes).
_QUOTED = re.compile(r"[“\"]([^”\"\n]{3,600})[”\"]")
# Function words and connectives that legitimately start a sentence; a capital there is grammar, not a name.
_COMMON = frozenset("""a an the and but or nor so yet for if then than when while where whether which who whom whose what why how that
    this these those there here it its it's he his him she her they them their we our you your i one none nothing
    no not neither either both each every all any some most more less few many much other another such same only even
    still just also too again once twice instead meanwhile however though although because since until unless after
    before during across against between through over under above below beside without within around about along
    toward towards from into onto upon with by at on in of to as like near far now today tonight later earlier first
    second third last next half whatever whichever wherever whenever is was are were be been being has had have do does
    did can could will would shall should may might must let lets set put take took give gave say said says call called
    read reads see seen saw look looks keep kept leave left come came go went goes make made bring brought hold held
    tells told ask asked asks four five six seven eight nine ten two three yes perhaps maybe nobody somebody someone
    anyone everyone everything something anything nowhere somewhere""".split())
# Words that must not appear in a revision unless the draft or the packet already carries them: the shapes of an
# invented scene, an inferred feeling and an explanation (a motive the record does not hold).
_FEELINGS = re.compile(
    r"\b(?:felt|feels?|feeling|frustrat\w*|proud|pride|worr\w+|anxious|anxiety|reliev\w+|happ(?:y|ier|iness)|disappoint\w*|"
    r"excit\w+|nervous|determin\w+|hopeful|afraid|scared|guilt\w*|ashamed|tired|exhausted|elated|motivat\w+)\b",
    re.IGNORECASE,
)
_CAUSAL = re.compile(
    r"\b(?:because|caused|led\s+to|thanks\s+to|resulted\s+in|due\s+to|which\s+is\s+why|that\s+is\s+why|so\s+that|in\s+order\s+to)\b",
    re.IGNORECASE,
)


def _fmt(x: float) -> str:
    return str(int(x)) if float(x).is_integer() else f"{x:.10g}"


def _numbers(text: str) -> List[Tuple[str, float]]:
    out = []
    for m in _NUM.finditer(text or ""):
        whole = m.group(1).replace(",", "")
        out.append((m.group(0), float(f"{whole}.{m.group(2)}") if m.group(2) else float(whole)))
    return out


def _number_set(text: str) -> Set[str]:
    vals = {_fmt(v) for _raw, v in _numbers(text)}
    vals |= {_fmt(_WORD_NUMS[m.group(1).lower()]) for m in _WORD_NUM_RE.finditer(text or "")}
    return vals


def _source_vocab(source: str) -> Tuple[Set[str], Set[str], Set[str]]:
    """(lower-case words, case-sensitive words, date words) the draft + packet carry. Month names are added for every
    ISO date in the packet, so "6 November" is grounded by a "2026-11-06" the dossier holds."""
    lower = set(re.findall(r"[a-z0-9’']+", (source or "").lower()))
    cased = set(re.findall(r"[A-Za-z][A-Za-z’'\-]*", source or ""))
    dates = {m.group(1).lower() for m in _DATE_WORD_RE.finditer(source or "")}
    for m in _ISO.finditer(source or ""):
        dates.add(_MONTHS[int(m.group(1)) - 1])
    return lower, cased, dates


def _sentences(text: str) -> List[str]:
    return [x for x in re.split(r"(?<=[.!?])\s+|\n\s*\n", text or "") if x.strip()]


def _sentence_initial(text: str, start: int) -> bool:
    before = (text[:start] or "").rstrip(" \t\"“‘'*_(>")
    return not before or before[-1] in ".!?:;\n—–-"


def _quote_spans(text: str) -> List[str]:
    spans = [m.group(1) for m in _QUOTED.finditer(text or "")]
    for para in re.split(r"\n\s*\n", text or ""):
        p = para.strip()
        if p.startswith(">"):
            spans.append(" ".join(line.lstrip("> ").strip() for line in p.splitlines()).strip().strip('"“”'))
    return [s for s in spans if len(s.split()) >= 2]


def new_claims(revision: str, draft: str, packet_text: str, allowed: Optional[Set[str]] = None) -> List[str]:
    """Every way ``revision`` says something neither ``draft`` nor the packet carries. Empty = nothing new; any item
    discards the revision. Pure and deterministic.

    ``allowed`` is the packet's own number renderings (``story_checks.allowed_numbers``: values, their roundings and the
    magnitude of a signed delta). Checked: numbers (digits and number words), weekday and month names, capitalised names,
    quoted and blockquoted words, and the scene / feeling / causal markers an invented explanation needs."""
    source = f"{draft}\n{packet_text}\n{elena_canon.NAME}\n{elena_canon.SERIES}"
    out: List[str] = []
    in_draft = _number_set(draft)
    in_packet = _number_set(packet_text) | set(allowed or ())
    for sent in _sentences(revision):
        baseline = bool(_NOTHING_CHANGES_RE.search(sent))
        found = [(raw, _fmt(v)) for raw, v in _numbers(sent)] + [
            (m.group(0), _fmt(_WORD_NUMS[m.group(1).lower()])) for m in _WORD_NUM_RE.finditer(sent)
        ]
        for raw, val in found:
            if val in in_draft:
                continue
            if val not in in_packet:
                out.append(f"number {raw!r} is in neither the draft nor the evidence packet")
            elif not baseline:
                # The first dry run (2026-11-22) took a "23" that the packet carried in another meaning and made it a
                # claim the draft never made ("23 straight days of training"). A figure the draft did not print comes in
                # from the packet ONLY inside the one comparison the editor is asked to add: what a guess that nothing
                # changes would have scored.
                out.append(
                    f"number {raw!r} is not in the draft; the editor brings a packet figure in only inside a 'nothing "
                    f"changes' comparison: {sent[:100]!r}"
                )
    lower, cased, dates = _source_vocab(source)
    for m in _DATE_WORD_RE.finditer(revision or ""):
        if m.group(1).lower() not in dates:
            out.append(f"date word {m.group(0)!r} is in neither the draft nor the evidence packet")
    seen: Set[str] = set()
    for m in _CAP.finditer(revision or ""):
        tok = re.sub(r"[’']s$", "", m.group(0))
        if tok in seen or tok in cased or tok.lower() in _MONTHS + _WEEKDAYS:
            continue
        seen.add(tok)
        if _sentence_initial(revision, m.start()) and (tok.lower() in _COMMON or tok.lower() in lower):
            continue
        out.append(f"name {tok!r} is in neither the draft nor the evidence packet")
    norm_source = story_craft._norm(source)
    for span in _quote_spans(revision):
        if story_craft._norm(span) not in norm_source:
            out.append(f"quotation {span[:80]!r} is not words the draft or the evidence packet holds")
    for label, rx in (("scene/interview", _SCENE), ("feeling", _FEELINGS)):
        for m in rx.finditer(revision or ""):
            word = m.group(0).lower()
            if word not in (draft or "").lower() and word not in (packet_text or "").lower():
                out.append(f"{label} {m.group(0)!r} is in neither the draft nor the evidence packet")
    if len(_CAUSAL.findall(revision or "")) > len(_CAUSAL.findall(draft or "")):
        out.append("the revision adds a causal connective ('because', 'led to', …): an explanation the draft did not make")
    return list(dict.fromkeys(out))


# ── one edit call ────────────────────────────────────────────────────────────


def edit_body(system: str, packet: str, draft: str, notes: List[str], rejected: Optional[List[str]] = None) -> Dict[str, Any]:
    """The Messages body for one edit round. The packet is the cached prefix (identical across a week's rounds, so the
    second round inside the five-minute TTL reads it); the draft and the notes are the volatile tail."""
    from ai import prompt_cache

    tail = (
        "THE WRITER'S DRAFT:\n"
        + draft
        + "\n\nWHAT THE CHECKS NOTICED (style notes for you, not facts):\n- "
        + "\n- ".join(notes or ["none"])
    )
    if rejected:
        tail += (
            "\n\nYOUR LAST REVISION WAS THROWN AWAY because it said things the draft and the packet do not:\n- "
            + "\n- ".join(rejected[:12])
            + "\nRevise the draft again without adding any of them."
        )
    tail += "\n\nReturn the revised installment, then the notes line, as the brief says."
    content = prompt_cache.cached_prefix_blocks("EVIDENCE PACKET (the only facts that exist):\n" + packet, tail)
    return {"system": system, "messages": [{"role": "user", "content": content}], "max_tokens": EDITOR_MAX_TOKENS, "temperature": 0.3}


def parse_reply(text: str) -> Tuple[str, List[str]]:
    """(revised installment, the editor's remaining notes)."""
    body, _sep, tail = (text or "").partition(NOTES_MARKER)
    notes = [ln.strip()[2:].strip() for ln in tail.splitlines() if ln.strip().startswith("- ")]
    return body.strip(), [n for n in notes if n and n.lower() != "none"]


# A finding's sentence excerpt is a repr()'d span of 25+ characters; a short quoted token (a number, a phrase) is the
# problem itself and stays in the key.
_EXCERPT = re.compile(r"(?<=: )(?:\"[^\"]{25,}(?:\"|$)|'[^']{25,}(?:'|$)|“[^”]{25,}(?:”|$))")


def finding_key(finding: str) -> str:
    """A hard-gate finding without the sentence excerpt it quotes, so the same problem in a reworded sentence is the
    same problem ("callback: '60' … does not appear in Week 4: <sentence>" keys on everything before the sentence)."""
    return _EXCERPT.sub("…", str(finding or "")).strip()


def added_findings(revision: List[str], before: List[str]) -> List[str]:
    """The revision's hard findings its input did not carry, counted by key: one more of a kind is one more problem."""
    left = Counter(finding_key(f) for f in before)
    out = []
    for f in revision:
        k = finding_key(f)
        if left[k] > 0:
            left[k] -= 1
        else:
            out.append(f)
    return out


def _keep_title(revision: str, draft: str) -> str:
    """The title is a ledger fact (the season's titles); the editor cannot change it."""
    title, _ = story_writers.split_title(draft)
    _rt, rbody = story_writers.split_title(revision)
    return f'"{title}"\n\n{rbody}'


def _usage_cost(resp: Dict[str, Any], model: str) -> float:
    try:
        from ai import bedrock_client

        return bedrock_client.estimate_cost_usd(resp.get("usage") or {}, bedrock_client.resolve_model_id(model))
    except Exception:  # noqa: BLE001 — a cost estimate is a report, never a gate
        return 0.0


def revise(
    draft: str,
    *,
    packet: str,
    allowed: Set[str],
    notes_for: Callable[[str], List[str]],
    hard_check: Callable[[str], List[str]],
    invoke: Optional[Callable[[Dict[str, Any], str], Dict[str, Any]]] = None,
    allow_spend: Optional[Callable[[], bool]] = None,
    editor_model: Optional[str] = None,
    writer_model: Optional[str] = None,
    log: Callable[[str], None] = print,
) -> Dict[str, Any]:
    """The draft through at most ``MAX_ROUNDS`` editor calls. Returns ``{"text", "accepted", "rounds", "advisory",
    "model", "cost_usd"}`` — ``text`` is the best version (the draft itself when no revision was accepted).

    ``notes_for(body)`` gives the deterministic notes for a body; ``hard_check(md)`` the deterministic hard-gate
    findings for a full installment. A revision is accepted only when ``new_claims`` is empty AND it adds no hard-gate
    finding its input did not carry. Nothing here can block a week: every outcome is a text plus advisory notes."""
    model = editor_model or EDITOR_MODEL
    record: Dict[str, Any] = {"text": draft, "accepted": 0, "rounds": [], "advisory": [], "model": model, "cost_usd": 0.0}
    if model == (writer_model or story_writers.WRITER_MODEL):
        record["advisory"].append(f"editor skipped: the editor would run on the writer's own model ({model}), which is self-review")
        log(f"[editor] skipped — editor and writer both resolve to {model}")
        return record
    if allow_spend is None:

        def allow_spend() -> bool:
            from ai import budget_guard

            return budget_guard.allow(BUDGET_FEATURE)

    if not allow_spend():
        record["advisory"].append("editor skipped: the budget tier pauses the chronicle feature; the writer's draft went forward")
        log("[editor] skipped — budget tier pauses the chronicle feature")
        return record
    if invoke is None:
        from ai import bedrock_client

        invoke = bedrock_client.invoke_with_retry
    system = system_prompt()
    current = draft
    current_hard = hard_check(current)
    rejected: List[str] = []
    last_notes: List[str] = []
    for rnd in range(1, MAX_ROUNDS + 1):
        _t, body = story_writers.split_title(current)
        notes = notes_for(body)
        if rnd > 1 and not notes and not rejected:
            break  # the accepted revision leaves nothing for a second round
        try:
            resp = invoke(edit_body(system, packet, current, notes, rejected), model)
        except Exception as e:  # noqa: BLE001 — an editor that cannot run leaves the draft as it was
            record["rounds"].append({"round": rnd, "outcome": "error", "why": f"{type(e).__name__}: {str(e)[:200]}"})
            record["advisory"].append(f"editor round {rnd} could not run ({type(e).__name__}); the previous version went forward")
            break
        record["cost_usd"] += _usage_cost(resp, model)
        text = story_writers._text(resp)
        revision, editor_notes = parse_reply(text)
        if resp.get("stop_reason") != "end_turn" or not revision:
            record["rounds"].append(
                {"round": rnd, "outcome": "discarded", "why": [f"incomplete reply (stop_reason={resp.get('stop_reason')})"]}
            )
            rejected = ["the reply was cut off or empty; return the whole installment"]
            continue
        revision = _keep_title(revision, current)
        claims = new_claims(revision, draft, packet, allowed)
        added_hard = added_findings(hard_check(revision), current_hard)
        why = claims + [f"adds a hard-gate finding the input did not have: {f}" for f in added_hard]
        if why:
            record["rounds"].append({"round": rnd, "outcome": "discarded", "why": why, "notes_in": notes})
            log(f"[editor] round {rnd} revision discarded: {why[:6]}")
            rejected = why
            continue
        record["rounds"].append({"round": rnd, "outcome": "accepted", "notes_in": notes, "editor_notes": editor_notes})
        current, current_hard, rejected, last_notes = revision, hard_check(revision), [], editor_notes
        record["accepted"] += 1
        log(f"[editor] round {rnd} revision accepted ({len(notes)} note(s) in, {len(editor_notes)} left by the editor)")
    record["text"] = current
    _t, final_body = story_writers.split_title(current)
    residual = notes_for(final_body)
    discarded = [r for r in record["rounds"] if r["outcome"] == "discarded"]
    # The editor's own remarks are a model's description of its work: the first dry run showed them claiming edits it
    # had not made, so they reach the owner labelled as unverified, after the deterministic notes.
    record["advisory"] += residual + [UNVERIFIED_PREFIX + n for n in last_notes]
    if discarded and not record["accepted"]:
        record["advisory"].append(
            f"every editor revision ({len(discarded)}) was discarded for adding something the record does not hold; "
            "the writer's draft went forward unedited"
        )
    record["cost_usd"] = round(record["cost_usd"], 4)
    return record


def advisory_lines(record: Optional[Dict[str, Any]]) -> List[str]:
    """The record's notes as the strings the draft row carries (``desk_craft_json``): never empty when the editor ran,
    so a revised week always waits for the owner's eye in the preview, whatever PREVIEW_MODE says."""
    if not record:
        return []
    lines = [REVISED_NOTE if record.get("accepted") else "the editor ran but no revision was accepted; this is the writer's draft"]
    lines += list(dict.fromkeys(str(x) for x in record.get("advisory") or []))
    return [ADVISORY_PREFIX + x for x in lines]


def summary(record: Optional[Dict[str, Any]]) -> str:
    """One JSON string for the row (``desk_editor_json``): what the editor did, round by round, and what it cost."""
    return json.dumps(record or {}, default=str)


def packet_for(dossier: Dict[str, Any], budget: Dict[str, Any], ledger: Dict[str, Any], week: int, previous: Optional[str]) -> str:
    """The same evidence the writer was given, byte for byte (``story_writers.evidence_packet``)."""
    return story_writers.evidence_packet(dossier, budget, ledger, week, previous)


def packet_numbers(dossier: Dict[str, Any], budget: Dict[str, Any], ledger: Dict[str, Any]) -> Set[str]:
    """Every rendering of every figure the packet carries — the number half of the no-new-claims check."""
    return story_checks.allowed_numbers(dossier, budget, ledger)
