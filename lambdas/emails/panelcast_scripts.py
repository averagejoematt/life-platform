"""Panelcast script builders — the two large Sonnet prompt-builders for The Measured Life.

Extracted from ``coach_panel_podcast_lambda.py`` (#1182, prep for #1180 — the craft layer
needs headroom) to keep that lambda under the ADR-080 god-module gate (2000 lines,
``tests/test_lambda_size_gate.py``). This is a pure move — same prompts, same output, same
behavior. The lambda keeps thin wrappers (``_build_intro_script`` / ``_build_weekly_script``)
that inject its clients + helpers through a ``deps`` dict, mirroring ``podcast_script_v2`` (#547).

Episode 0 is EVERGREEN (#1182): ``_run_intro`` always passes ``zeitgeist=[]`` so the resurrected
prologue never carries stale dated headlines. The builder still accepts a ``zeitgeist`` list so
the weekly path (which DOES pass real headlines) shares this code unchanged.

``deps`` keys consumed here:
    invoke         — bedrock_client.invoke(body, model_name=...)
    logger         — module logger
    intro_guest    — () -> dict, the Episode-0 guest persona
    episode_angle  — (week) -> str, the rotating weekly entry-point lens
    extract_json   — tolerant JSON parser
    zeitgeist      — the panelcast_zeitgeist module (zeitgeist_prompt_block)
    intro_model    — Sonnet model id for Episode 0
    writer_model   — Sonnet model id for the weekly episode
"""

import json
import re

try:  # bundle stages lambdas/ at the zip root; tests add lambdas/emails/ to sys.path
    from emails.panelcast_qa import _QA_MAX_WORDS_PER_TURN
except ImportError:
    from panelcast_qa import _QA_MAX_WORDS_PER_TURN

from ai_context import build_experiment_phase_context, format_experiment_phase_context  # #1086: mandatory phase block

# Shared writer directive — make the SCRIPT genuinely conversational so the voice has
# something human to perform (Gemini reads what's written; banter must be on the page).
CONVO_DIRECTIVE = (
    "Write it like two people who actually like each other talking — NOT alternating monologues. Use genuine back-and-forth: "
    "short interjections and reactions ('Mm.', 'Right.', 'Wait—', 'Exactly.', 'Honestly?'), one person occasionally finishing "
    "or gently cutting into the other's thought, a trailing-off, a little dry humor, a beat of real curiosity. Vary turn length "
    "hard — some turns are one word, some are a paragraph. No bracketed stage directions (no '[laughs]'); put the warmth in the words."
)


def build_intro_script(bible: dict, zeitgeist: list | None, deps: dict) -> list:
    """Episode 0 as a two-person interview, driven by the series bible.
    `zeitgeist` (#1178): optional real headlines — an OPTIONAL TOPICAL COLOR
    block in the prompt, omitted entirely when the list is empty. Episode 0 is
    evergreen (#1182), so the intro path always passes an empty list."""
    invoke = deps["invoke"]
    logger = deps["logger"]

    g = deps["intro_guest"]()
    ch = bible.get("characters", {})
    sc = bible.get("site_concepts", {})
    arc = "\n".join(f"  {i + 1}. {step}" for i, step in enumerate(bible.get("episode0_arc", [])))
    guards = "\n".join(f"  - {x}" for x in bible.get("guardrails", []))
    site = "\n".join(f"  - {k.title()}: {v}" for k, v in sc.items())

    system = (
        f'You are the head writer for "{bible.get("show_name", "The Measured Life")}", a narrative podcast. Write EPISODE 0: a '
        "warm, intriguing, genuinely human two-person interview that introduces the show to a COMPLETE STRANGER (someone who has "
        "never heard of Matt) and makes them want to follow the series. Energy of a great narrative-podcast trailer: hook fast, "
        "raise a real and slightly philosophical question, be honest rather than hypey, leave them wanting episode one. "
        f"HOST is Elena Voss; GUEST is {g['name']}, {g['role']}. A REAL conversation — Elena asks what a curious skeptic would ask "
        "and reacts; the guest answers like a person, warm and plain-spoken with the occasional vivid line. They build on each "
        "other, vary turn length, and use a little wry humor.\n\n"
        f"{CONVO_DIRECTIVE}\n\n"
        f"THE BIG QUESTION (the emotional hook — land it, don't rush past it):\n{bible.get('thesis', '')}\n\n"
        f"WHAT'S ACTUALLY BEING MEASURED:\n{bible.get('what_we_measure', '')}\n\n"
        f"TONE: {bible.get('tone', '')}\n\n"
        f"FOLLOW THIS ARC, IN ORDER:\n{arc}\n\n"
        "NON-NEGOTIABLE REQUIREMENTS:\n"
        "  - OPEN ON A HOOK, not an introduction. Elena's very first line is a genuine grab — the universal tension at the "
        "heart of this: a capable person who already KNOWS how to do it, has done it, and watches it slip anyway. Land that "
        'before anything administrative. Her first line must still include "I\'m Elena Voss" and who she is, woven INTO the '
        "hook (not a flat 'My name is...'). She speaks first, alone, before the guest.\n"
        "  - REAL TENSION, not mutual agreement. Eli must NAME THE RISK HIMSELF, unprompted, in his own words — say out loud "
        "that this could curdle into over-optimization theater, quantifying a life instead of living it — BEFORE Elena raises "
        "it; he's a scientist who states the failure mode plainly, then says why he still thinks it's worth doing. If Eli never "
        "names that risk in his own voice, the episode is rejected. Elena pushes "
        "harder, not softer ('that's the thing I'm most worried about', 'convince me this isn't just a beautiful dashboard'). "
        "At least one real point of friction where they don't fully agree — and the disagreement must PLAY OUT across several "
        "turns: positions argued, countered, and genuinely moved, not asserted in one line and dropped. "
        "Warm, but no sales pitch and no easy consensus.\n"
        "  - PACING (this is a trailer, every second earns its place): get into genuine back-and-forth FAST. After Elena's "
        "opening hook, the turns STRICTLY ALTERNATE — NEVER write two consecutive turns for the same speaker, no exceptions; "
        "when a point needs more room, the other person cuts in, reacts, or asks, and it continues in the reply. Cut filler. Favour short, vivid, QUOTABLE lines someone would screenshot over long paragraphs. "  # noqa: E501
        f"HARD CAP: every turn is AT MOST {_QA_MAX_WORDS_PER_TURN} words — a deterministic gate rejects the whole script for a "
        "single longer turn. When an explanation wants more room, split it into an exchange: the other person reacts or asks, "
        "and it continues in the reply. Never a lecture.\n"
        "  - NO DANGLING THREADS (deterministically checked): any turn that ends on a question, or issues a challenge "
        "('convince me...', 'here's where I push back'), MUST be answered by the OTHER speaker in the very next turn. Never "
        "follow a question with the same speaker talking again; never raise a thread and then move on without it being answered. "
        "The answer must be SUBSTANTIVE — it engages the question's actual content before any new topic opens; a deflection, "
        "a joke, or a one-line acknowledgment that pivots away counts as dropping the thread.\n"
        "  - Before the harder material, Elena must establish WHO Matt is and why a complete STRANGER should care about him — an "
        "ordinary, technical, curious person who has done this before and genuinely succeeded (the high). Meet the person and the "
        "stakes FIRST.\n"
        "  - THEN his honest story, IN THIS episode, told as a SMOOTH continuation (NEVER an abrupt topic jump — Elena bridges "
        "into it): he's consistent until something disrupts the routine and the old habits return; the weight was the symptom, "
        "not the problem; and 'can a system catch what willpower alone misses?'. Do NOT defer it to a future episode. Do NOT "
        "invent specific events, losses, deaths, illnesses, relocations, or dates — use only the character note and keep it to "
        "the general pattern.\n"
        "  - EVERY topic shift is BRIDGED — and the shift is VOICED BY THE OTHER SPEAKER: the person who did NOT just finish "
        "the point reacts or asks their way into the new ground; the same speaker never closes one topic and opens the next. "
        "This especially includes the reveal of the eight-coach AI team: it must surface from something Elena or Eli JUST said "
        "(a question, a doubt, a concrete example), never appear from nowhere as the next agenda item.\n"
        "  - Elena must mention that she writes a WEEKLY chronicle and that this podcast runs alongside it.\n"
        "  - The platform doors (Cockpit / Story / Evidence / Sources / Character) must be WOVEN INTO THE DIALOGUE one at a "
        "time, each surfacing naturally from something Eli or Elena just said — NEVER delivered as one listed tour or a single "
        "monologue. If a door doesn't come up organically, drop it rather than force a list.\n"
        "  - CLOSE on the series' standing open question — the bet this whole show is settling, that every future episode "
        f"moves the needle on: {bible.get('series_question', bible.get('thesis', ''))} Frame it as the reason to come back. "
        "The final exchange must LAND that tension — unresolved, a little uncomfortable, the itch that brings a listener "
        "back — not a tidy reassurance, a mutual pat on the back, or a summary bow.\n"
        "  - THE RULES ABOVE ARE FLOORS, NOT THE SHOW. The show is two people a total stranger wants to keep listening "
        "to: give Elena and Eli real personality — at least two genuinely warm or dryly funny beats, an aside or "
        "callback, a direct address to the listener, a moment of small talk that earns its place, lines worth quoting. "
        "Read it aloud in your head: if it sounds like a compliant briefing instead of a conversation with texture and "
        "charm, rewrite it. Never trade personality for compliance — deliver both.\n\n"
        f"HARD GUARDRAILS (breaking any of these ruins the episode):\n{guards}\n\n"
        'OUTPUT: ONLY a JSON array of turns [{"speaker":"elena"|"eli","line":"..."}], 20–28 turns. '
        "No preamble, no stage directions, no JSON fences."
    )
    zg = deps["zeitgeist"].zeitgeist_prompt_block(zeitgeist or [])
    user = (
        f"ELENA (host): {ch.get('elena', '')}\n\n"
        f"MATTHEW (the subject — NEVER a weight or body number): {ch.get('matthew', '')}\n\n"
        f"ELI (guest): {ch.get('eli', '')}\nHis philosophy: {g['philosophy']}\nHis expertise: {', '.join(g['expertise'])}\n\n"
        f"WHAT A LISTENER CAN EXPLORE (weave these in naturally, do NOT list them robotically):\n{site}\n\n"
        + (f"{zg}\n\n" if zg else "")
        + "Write Episode 0 now."
    )
    body = {"model": deps["intro_model"], "max_tokens": 4000, "system": system, "messages": [{"role": "user", "content": user}]}
    resp = invoke(body, model_name=deps["intro_model"])
    text = "".join(p.get("text", "") for p in (resp.get("content") or []) if isinstance(p, dict)).strip()
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    try:
        turns = json.loads(text)
    except Exception as e:
        logger.warning("[panel] intro JSON parse failed — %s", e)
        return []
    return turns if isinstance(turns, list) else []


def build_weekly_script(beats: dict, bible: dict, deps: dict) -> dict:
    """Sonnet writes the Elena + guest-coach episode in the bet/Split/scoreboard format."""
    invoke = deps["invoke"]
    logger = deps["logger"]

    guest = beats.get("guest") or {}
    fmt = bible.get("weekly_format", {})
    others = [c for c in beats.get("coach_reads", []) if c["id"] != guest.get("id")][:3]
    split_material = "\n".join(f"- {c['name']}: {c['summary']}" for c in others)
    system = (
        f'You are the head writer for "{bible.get("show_name", "The Measured Life")}". Write a WEEKLY episode: a warm, honest, '
        f"genuinely interesting two-person conversation. HOST: Elena Voss. GUEST: {guest.get('name', 'a coach')}. "
        f"FORMAT (follow it):\n{json.dumps(fmt.get('segments', []))}\nSign-off line: {fmt.get('sign_off', '')}\n\n"
        f"SELECTION/TONE: {json.dumps(bible.get('selection_rubric', {}))}\nTONE: {bible.get('tone', '')}\n\n"
        "HARD RULES: correlative only (never causal); use ONLY numbers present in the material; hedge anything on a small sample; "
        "process over outcome — never a report-card or judgmental tone; handle a hard week with compassion; never open a line with 'Matt'. "
        "This is a forward-looking PERFORMANCE & HEALTH review, NOT a grief or personal-history piece. NEVER mention or allude to: "
        "a death, grief, a funeral, cancer, or any named family member (mother/father/sister/brother/girlfriend/wife/etc.); any specific "
        "vice or substance (marijuana, alcohol, nicotine, pornography — not even non-specifically as 'his vices' or 'private habits'); "
        "or any body weight at all — numeric OR spelled-out ('nine pounds' is just as forbidden as '305 lbs'). Stay on training, sleep, recovery, habits, the deficit's effects, the bet, and the week's effort. "  # noqa: E501
        "THE BAR (this is the whole point): the TRANSCRIPT must pass for a real, human-made podcast — if a person read it aloud, "
        "nobody could tell it was AI-written. Earn a real hook in the first two lines, real human interest, genuine dry humor, and "
        "something a listener actually learns and would text to a friend. NO AI TELLS: never say 'in this episode' or 'today we're "
        "diving into'; never narrate the format or name the segments; no tidy three-item lists; no 'not just X, it's Y' symmetry; no "
        "over-explaining or throat-clearing; no neat bow at the end. Think a sharp, warm two-person show people actually subscribe to. "
        "GROUNDING (non-negotiable): every line must come from the real material below — the coaches' reads and the week's data. Do NOT "
        "invent scenes, settings, times of day, anecdotes, or sensory detail (no '5 AM protein shake', no 'lukewarm shake', nothing that "
        "isn't in the material). If it isn't in the data, it didn't happen. The chronicle is background only — never quote it or lift its "
        "literary scene-setting as fact. GUEST INTRO & CONTINUITY: ALWAYS introduce this week's guest for the audience early — their name and "  # noqa: E501
        "what they actually work on — UNLESS they were the guest in the immediately previous episode (then acknowledge the returning thread "  # noqa: E501
        "instead). Listeners may have never met this coach; a new voice must never just start talking with no introduction. EVERY question "
        "Elena asks must get a real answer in the very next turn — never raise a question and move on, never leave a thread dangling. "
        f"{CONVO_DIRECTIVE} "
        'OUTPUT ONLY JSON: {"turns":[{"speaker":"elena"|"coach","line":"..."}], "open_bet":"<the one new falsifiable bet for next week>", '
        '"last_bet_result":{"outcome":"won"|"lost"|"open"|"none"}, '
        '"pull_quote":"<one shareable line>", '
        '"episode_title":"<a SHORT episode title: 2–5 words, a hook — NOT a sentence, NO \'Week N\', NO ending punctuation>"}. 14–22 turns. No fences.'  # noqa: E501
    )
    _chron = beats.get("chronicle", "")
    _chron_block = (
        f"CHRONICLE (the human week):\n{_chron[:3500]}\n\n"
        if _chron
        else "NO CHRONICLE THIS WEEK — review the week from the coaches' reads below and the week's data; do not reference or imply a chronicle exists.\n\n"  # noqa: E501
    )
    # #914: a real logging stall is the week's context, not a detail to skip.
    _presence_block = f"{beats['presence_note']}\n\n" if beats.get("presence_note") else ""
    # #1086: the mandatory experiment-phase block — computed here if a caller
    # hands beats without one, so no path can build this prompt phase-blind.
    _phase_block = beats.get("phase_block") or format_experiment_phase_context(build_experiment_phase_context(None, beats.get("date")))
    # #1178: optional topical color — real headlines, at most 1-2 light quips, never load-bearing.
    _zg = deps["zeitgeist"].zeitgeist_prompt_block(beats.get("zeitgeist") or [])
    user = (
        f"WEEK {beats.get('week')}: {beats.get('title')}.\n\n{_phase_block}\n\n{_chron_block}{_presence_block}"
        f"GUEST COACH {guest.get('name')} — recent read: {guest.get('summary', '')}\nThemes: {', '.join(guest.get('themes', []))}\n\n"
        f"OTHER COACHES (for THE SPLIT — find a genuine disagreement):\n{split_material}\n\n"
        f"LAST WEEK'S OPEN BET (score it in RECEIPTS, honestly): {beats.get('last_open_bet') or '(none — this is the first weekly)'}\n\n"
        f"GUEST CONTINUITY: last week's guest was {beats.get('prev_guest') or '(none — first weekly with a coach guest; the only prior episode was the intro)'}. "  # noqa: E501
        f"THIS week's guest is {guest.get('name')}. If that's a change, introduce {guest.get('name')} properly for the audience "
        f"(who they are + what they work on, drawn from their read/themes above) before getting into it.\n\n"
        f"RECENT TOPICS (avoid repeating): {beats.get('recent_topics')}\n\n"
        # SS-09: rotate the entry-point lens so the show doesn't feel formulaic by ep 26.
        # Keep the bet/Split/scoreboard format — change only what the episode LEADS with.
        f"THIS WEEK'S ANGLE (keep the format, but lead with THIS lens so the show stays fresh): {deps['episode_angle'](beats.get('week'))}\n\n"  # noqa: E501
        + (f"{_zg}\n\n" if _zg else "")
        + "Write the JSON now."
    )
    body = {"model": deps["writer_model"], "max_tokens": 3500, "system": system, "messages": [{"role": "user", "content": user}]}
    resp = invoke(body, model_name=deps["writer_model"])
    text = "".join(p.get("text", "") for p in (resp.get("content") or []) if isinstance(p, dict)).strip()
    parsed = deps["extract_json"](text)
    if not isinstance(parsed, dict):
        logger.warning("[panel] weekly script parse failed")
        return {}
    return parsed
