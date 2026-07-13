"""panelcast_qa — the podcast QA gates (craft + continuity + LLM judge).

Extracted from coach_panel_podcast_lambda.py at the 2000-line god-module gate
(test_lambda_size_gate, #1122 pushed it over). Pure gate logic, no publish paths:
deterministic checks first (ADR-105), Haiku judge fail-closed (ADR-087/108).
"""

import json
import logging
import os
import re

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

MODEL = os.environ.get("AI_MODEL_HAIKU", "claude-haiku-4-5-20251001")
# #1180: the CRAFT items (read-aloud Turing test, humour/human texture, arc rhythm) are
# NARRATIVE judgment, not structure — ADR-049 puts that on the Sonnet tier, not Haiku. The
# structure/accuracy rubrics below stay on Haiku (MODEL); _craft_judge runs on this model.
CRAFT_MODEL = os.environ.get("AI_MODEL_SONNET", "claude-sonnet-4-6")

# ── QA rigor (automates the manual review loop, 2026-06-17) ───────────────────
# Two layers on top of the ER-03 + Compassion gates, both catching CRAFT/accuracy
# problems those deterministic safety gates can't see (monologue dumps, no tension,
# invented biography, abrupt flow). A generator that fails QA is RE-ROLLED up to
# _QA_MAX_ATTEMPTS times (generation is non-deterministic, so a re-roll usually
# fixes it); the best candidate is kept. See the 2026-06-17 handover.
_QA_MAX_ATTEMPTS = int(os.environ.get("PANEL_QA_MAX_ATTEMPTS", "3"))
_QA_MAX_WORDS_PER_TURN = 130  # a turn longer than this reads as a monologue, not dialogue
_QA_HOOK_MAX_WORDS = 180  # turn 0 is the cold-open hook — a solo turn by design, allowed to run longer
# #1171 calibration (measured 2026-07-12): the original bound allowed 3 same-speaker turns
# in a row while the Haiku judge's rubric failed every script containing exactly that
# pattern — the two graders disagreed on the line, so a deterministically-"clean" draft
# could never converge. The graders must agree: 2 is the bound, and the judge rubrics
# below state the SAME number (test-enforced in tests/test_panelcast_repair.py).
_QA_MAX_CONSECUTIVE = 2
# #1123 (intro path): after the ONE solo cold-open hook (turn 0), Episode 0 must strictly
# alternate — the series bible's episode0_arc calls the hook "ONE punchy solo turn", so a
# second same-speaker turn is a seam, not a monologue-tolerance question. The weekly show
# keeps the looser bound of 2 (two riffing beats in a row read fine mid-conversation); the
# trailer does not. Threaded through the SHARED primitives (structural_seams / _craft_check
# / repair_structure) as a param so the gate and the #1170 repair pass can never disagree
# on the bound they enforce (the #1176 invariant). Turn 0 keeps its OTHER exemptions — the
# longer hook word-cap below and the cold-open dangling-thread exemption.
_QA_MAX_CONSECUTIVE_INTRO = 1

# #1122: a turn that ASKS something (interrogative or an explicit challenge) must get a
# reply from the OTHER speaker in the very next turn. The observed wk0 defect: a gate
# dropped Eli's answer, leaving Elena's "convince me this isn't just a beautiful
# dashboard" followed by Elena's own "here's where I push back" — a conversational hole
# the 4-in-a-row check can't see (it's only 2 same-speaker turns).
_CHALLENGE_RE = re.compile(r"\b(convince me|push back|here'?s where|prove it)\b", re.IGNORECASE)
# Interrogative = the line ends on a question mark, allowing trailing quotes/brackets.
_INTERROGATIVE_RE = re.compile(r"\?[\"'”’)\]]*\s*$")


def _speaker_runs(turns: list) -> list:
    """Inclusive (start, end) spans of consecutive same-speaker turns, length >= 2.
    The ONE detection primitive behind both the craft check's floor-hog bound and the
    #1170 repair pass's seam list — gate and repair can never disagree on adjacency."""
    runs, start = [], 0
    for i in range(1, len(turns) + 1):
        if i == len(turns) or turns[i].get("speaker") != turns[i - 1].get("speaker"):
            if i - 1 > start:
                runs.append((start, i - 1))
            start = i
    return runs


def _dangling_pairs(turns: list) -> list:
    """(index, what) for each turn that is interrogative (ends '?') or an explicit challenge
    whose NEXT turn is the SAME speaker — i.e. the reply is missing (#1122). Turn 0 is
    exempt: the solo cold-open hook closes on a rhetorical question by design, and the fixed
    Elena cold-open may be prepended in front of her own hook. The final turn is never
    flagged — closing on the series' open question is the intended ending."""
    out = []
    for i in range(1, len(turns) - 1):
        if turns[i].get("speaker") != turns[i + 1].get("speaker"):
            continue
        line = (turns[i].get("line") or "").strip()
        if _INTERROGATIVE_RE.search(line):
            out.append((i, "asks a question"))
        elif _CHALLENGE_RE.search(line):
            out.append((i, "issues a challenge"))
    return out


def _continuity_check(turns: list) -> list:
    """Deterministic conversational-continuity gate (#1122; deterministic-before-LLM, ADR-105).
    Runs on the post-drop script (the gates can delete turns and leave exactly this hole).
    Detection lives in _dangling_pairs, shared with the #1170 repair pass."""
    return [
        f"dangling thread: turn {i} ({turns[i].get('speaker')}) {what} but the reply is missing — turn {i + 1} is "
        f"{turns[i].get('speaker')} again"
        for i, what in _dangling_pairs(turns)
    ]


def structural_seams(turns: list, max_consecutive: int = _QA_MAX_CONSECUTIVE) -> list:
    """#1170: the same-speaker adjacency spans the deterministic gate flags — the repair
    pass's work list, as inclusive (start, end) index spans. A run is a seam if it is longer
    than `max_consecutive` (the craft floor-hog bound — weekly 2, intro 1 per #1123) or
    contains a dangling thread (the continuity check). Built from the gate's own primitives,
    never a parallel detection; the same `max_consecutive` is threaded into _craft_check and
    repair_structure so the gate and the repair pass enforce the identical bound."""
    dangling = {i for i, _ in _dangling_pairs(turns)}
    return [(s, e) for s, e in _speaker_runs(turns) if (e - s + 1) > max_consecutive or any(s <= i <= e for i in dangling)]


def _craft_check(turns: list, max_consecutive: int = _QA_MAX_CONSECUTIVE) -> list:
    """Deterministic, zero-cost craft gate. Returns a list of failure reasons (empty = pass).
    Catches exactly the pacing problems an LLM judge is unreliable at: monologue dumps and
    one speaker holding the floor too long (bound: `max_consecutive` — weekly 2, intro 1 per
    #1123 — aligned with the judge rubric per #1171). Turn 0 is the intentional solo cold-open
    hook (a longer word ceiling, not the dialogue cap)."""
    fails = []
    for s, e in _speaker_runs(turns):
        run = e - s + 1
        if run > max_consecutive:
            fails.append(f"{turns[e].get('speaker')} speaks {run} turns in a row (max {max_consecutive}) — break it up")
            break
    for i, t in enumerate(turns):
        wc = len((t.get("line") or "").split())
        cap = _QA_HOOK_MAX_WORDS if i == 0 else _QA_MAX_WORDS_PER_TURN
        if wc > cap:
            label = "cold-open hook" if i == 0 else "monologue"
            fails.append(f"turn {i} is a {wc}-word {label} (max {cap}) — make it conversational")
    fails.extend(_continuity_check(turns))
    return fails


def _qa_review(turns: list, rubric: str, ground_truth: str = "") -> tuple:
    """LLM craft+accuracy judge (Haiku, cheap). Returns (ok, [reasons]). FAIL-CLOSED
    (#1122, ADR-087/108 posture): a judge/infra error returns a failure reason so the
    episode HOLDs instead of publishing unreviewed — judge failure means silence, not a
    broken episode. (Was fail-open pre-#1122; the wk0 prologue shipped with a
    conversational hole partly because nothing hard-blocked on QA.)"""
    import bedrock_client

    script = "\n".join(f"{t.get('speaker')}: {t.get('line')}" for t in turns)
    system = (
        "You are a ruthless podcast script editor doing QA on a draft. Judge ONLY the rubric below. "
        'Reply with STRICT JSON: {"pass": true|false, "fails": ["short reason", ...]}. No prose, no fences. '
        "Be strict but fair — flag a rubric item only on a clear miss.\n\nRUBRIC:\n" + rubric
    )
    user = (f"GROUND TRUTH (the only facts allowed about the subject):\n{ground_truth}\n\n" if ground_truth else "") + f"SCRIPT:\n{script}"
    try:
        body = {"model": MODEL, "max_tokens": 500, "system": system, "messages": [{"role": "user", "content": user}]}
        resp = bedrock_client.invoke(body, model_name=MODEL)
        text = "".join(p.get("text", "") for p in (resp.get("content") or []) if isinstance(p, dict)).strip()
        text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
        verdict = json.loads(text)
        if verdict.get("pass"):
            return True, []
        return False, [str(r) for r in (verdict.get("fails") or ["failed QA rubric"])][:6]
    except Exception as e:
        logger.warning("[panel] QA judge unavailable — failing CLOSED (hold, don't publish): %s", e)
        return False, [f"qa-judge-error (fail-closed): {e}"]


# NB (#1171/#1123): each rubric states its consecutive-turns bound from the constant —
# the weekly rubric from _QA_MAX_CONSECUTIVE (2), the intro rubric from
# _QA_MAX_CONSECUTIVE_INTRO (1, strict alternation after the solo hook) — so the judge is
# instructed to fail exactly what the deterministic check fails; a calibration test asserts
# each constant and its rubric text agree (tests/test_panelcast_repair.py).
_INTRO_RUBRIC = (
    "The two speakers are ELENA VOSS (the host — an embedded journalist) and DR. ELI MARSH (the guest — the head "
    "coach MATT cast to lead the coaching staff; MATT himself designed and built the experiment and the platform). "
    "MATT is the third-person SUBJECT of the experiment; he is NOT "
    "in the room and does NOT speak. These three are ESTABLISHED show personas — never treat Elena or Eli as invented.\n"
    "1. Opens on a genuine HOOK in turn 0 — ONE punchy solo turn, not a flat self-introduction.\n"
    "2. After the opening hook the speakers STRICTLY ALTERNATE — two consecutive turns from the same speaker fails this "
    f"item (more than {_QA_MAX_CONSECUTIVE_INTRO} consecutive turn from one speaker fails). The hook is a single solo "
    "turn; from the second turn on it is a real two-person back-and-forth, never a stretch of one person talking.\n"
    "3. At least one point of GENUINE friction/disagreement — Eli is not just agreeing with Elena throughout.\n"
    "4. Dr. Eli Marsh (the PI) names the over-optimization / 'measuring a life instead of living it' RISK himself, in his own words.\n"
    "5. No abrupt, unbridged topic jumps.\n"
    "6. Closes on the series' standing open question (does the tech genuinely make a life better, or theater).\n"
    "7. ACCURACY — applies ONLY to MATT (the subject): the script must not assert any specific life event, loss, "
    "death, illness, relocation, city, or date about MATT that isn't in the GROUND TRUTH. Do NOT flag the names, "
    "titles, or roles of Elena Voss or Dr. Eli Marsh — they are real show personas, not inventions. Only invented "
    "facts about MATT fail this item.\n"
    "8. NO DANGLING THREAD: every question or challenge one speaker raises is actually answered in the next turn; "
    "no topic the SCRIPT itself raises is then dropped; never two same-speaker turns where a reply is clearly "
    "missing. (Coverage is NOT required — only flag a thread the script opens and abandons.)\n"
    "9. AUTHORSHIP & METHOD accuracy: fails if the script implies anyone other than MATT designed, built, or runs "
    "the experiment or the platform (Eli was CAST by Matt to lead the coaching staff — he is not its author or "
    "Matt's boss), or that Matt merely follows a single daily instruction / 'one next move' — Matt runs many "
    "parallel protocols (experiments, challenges, habit trials, supplements) and makes his own calls; the coaches "
    "advise, predict, and get publicly scored.\n"
    # #1180: the CRAFT items (Turing test, humour/texture, arc rhythm) moved to the Sonnet
    # _craft_judge (_INTRO_CRAFT_RUBRIC below) — this Haiku rubric is now structure/accuracy only.
)


_WEEKLY_RUBRIC = (
    "Two speakers: ELENA VOSS (host, embedded journalist) and the GUEST COACH (an AI coach, named in the script). "
    "MATT is the third-person SUBJECT of the experiment — he is NOT in the room and does NOT speak. Elena and the "
    "coaches are ESTABLISHED show personas (never flag them as invented). Judge it as a real podcast a human would "
    "believe is human-made and would recommend to a friend. (#1180: the CRAFT items — Turing test, "
    "humour/texture, arc rhythm — moved to the Sonnet _craft_judge; this Haiku rubric is structure/accuracy only.)\n"
    "1. GUEST INTRODUCTION: the guest is introduced for the audience early (who they are + what they work on), UNLESS "
    "they were the guest in the immediately previous episode. A guest who just starts talking with no introduction FAILS.\n"
    "2. NO DANGLING THREAD: every question Elena asks is actually answered in the next turn; no topic the SCRIPT itself "
    "raises is then dropped; no abrupt unbridged jump; never two same-speaker turns where a reply is clearly missing; more "
    f"than {_QA_MAX_CONSECUTIVE} consecutive turns from one speaker fails this item. "
    "(Coverage is NOT required — do NOT flag a ground-truth fact that simply goes unmentioned; only flag a thread the "
    "script opens and abandons.)\n"
    "3. REAL HOOK: turn 0 earns attention — not a flat 'welcome to the show'.\n"
    "4. GENUINE FRICTION: at least one real disagreement or tension, not constant agreement.\n"
    "5. GROUNDED: every specific claim, number, or event about MATT traces to the GROUND TRUTH. No invented scenes, "
    "times of day, or sensory detail (e.g. a '5 AM protein shake'). Flag anything not in the ground truth.\n"
    "6. NO BODY WEIGHT IN THE SCRIPT: no body-weight figure appears in the spoken lines, numeric or spelled-out "
    "(e.g. 'nine pounds'). Body weight in the GROUND TRUTH is fine and expected — only flag it if it is SPOKEN in the script."
)


# ── #1180: the CRAFT rubrics (the taste bar) — judged on the Sonnet tier ──────
# The Haiku judge PASSED the humour item on a flat, factually-clean wk0 candidate: the
# taste bar was too lenient to mean anything. These three items — read-aloud Turing test,
# humour/human texture, and the NEW arc-rhythm item — are narrative judgment (ADR-049), so
# they move to a Sonnet judge that must QUOTE the beats it credits (a judge that has to cite
# evidence can't wave compliance through). Shared header + one arc item, phrased per path.
_CRAFT_ARC_ITEM = (
    "ARC RHYTHM: the episode has the emotional rhythm of a real show, not a flat Q&A — a cold-open hook, "
    "a warm human beat before it gets heavy, a deepening, a lighter 'laugh valve' before the heaviest beat, "
    "and a close on tension rather than a tidy bow. FAIL a one-note arc, or more than ~3 heavy exchanges in a "
    "row with no lighter beat to let the listener breathe."
)
_CRAFT_TURING_ITEM = (
    "READ-ALOUD TURING TEST: read aloud, it must sound human-written. Flag any AI tell — 'in this episode', "
    "narrating the format or naming segments, tidy three-item lists, 'not just X, it's Y' symmetry, over-explaining, "
    "hedge throat-clearing, or a neat summary bow at the end."
)
_INTRO_CRAFT_RUBRIC = (
    "This is EPISODE 0 (the trailer) of a narrative podcast — host ELENA VOSS and guest DR. ELI MARSH. Judge ONLY "
    "the show-craft; structure and accuracy are judged elsewhere.\n"
    "1. " + _CRAFT_TURING_ITEM + "\n"
    "2. HUMOUR & HUMAN TEXTURE: this must feel like a show a stranger would keep listening to, not a briefing — at "
    "least two genuinely warm or dryly funny beats, plus human texture (an aside or callback, direct address to the "
    "listener, a moment of small talk that earns its place, a quotable line). A script that is merely compliant and "
    "information-dense — personality-free — FAILS this item.\n"
    "3. " + _CRAFT_ARC_ITEM
)
_WEEKLY_CRAFT_RUBRIC = (
    "This is a WEEKLY episode of a narrative podcast — host ELENA VOSS and a guest AI coach. Judge ONLY the "
    "show-craft; structure and accuracy are judged elsewhere.\n"
    "1. " + _CRAFT_TURING_ITEM + "\n"
    "2. HUMOUR & HUMAN INTEREST: at least two genuinely warm or dryly funny human beats plus real texture (an aside, "
    "a callback, a quotable line) — a show a stranger would keep listening to, never dry data recitation. A "
    "personality-free, information-dense script FAILS this item.\n"
    "3. " + _CRAFT_ARC_ITEM
)


def _craft_judge(turns: list, rubric: str, model: str = None) -> tuple:
    """#1180: the narrative-tier (Sonnet) TASTE judge for the craft items — read-aloud Turing
    test, humour/human texture, arc rhythm (ADR-049: this IS narrative judgment, not
    structure). Returns (ok, [reasons], [cited_beats]). The response schema REQUIRES quoted
    evidence: the judge must cite the two funniest / most-human lines it credits, and if it
    cannot find two that would make a stranger smile or feel something it FAILS the humour
    item. A judge that must cite evidence can't wave compliance through. FAIL-CLOSED
    (ADR-087/108): a judge/infra error returns a failure so the episode HOLDs, matching the
    Haiku judge's posture. Reuses the bedrock_client.invoke + budget-guard path exactly."""
    import bedrock_client

    m = model or CRAFT_MODEL
    script = "\n".join(f"{t.get('speaker')}: {t.get('line')}" for t in turns)
    system = (
        "You are a sharp, warm podcast producer judging ONLY the CRAFT of a two-person script — is this a show a "
        "stranger would actually keep listening to, or a compliant, AI-flavoured briefing? Structure and accuracy are "
        "judged elsewhere; do NOT comment on them. Judge only the rubric below.\n"
        'Reply with STRICT JSON: {"pass": true|false, "fails": ["short reason", ...], '
        '"cited_beats": ["<verbatim line from the script>", "..."]}. No prose, no fences. '
        "You MUST quote, verbatim, the two funniest or most human lines you credit; each cited beat must be an exact "
        "substring of a line in the script. If you cannot find two lines that would make a stranger smile or feel "
        "something, FAIL the humour item and say so in fails.\n\nRUBRIC:\n" + rubric
    )
    try:
        body = {"model": m, "max_tokens": 700, "system": system, "messages": [{"role": "user", "content": f"SCRIPT:\n{script}"}]}
        resp = bedrock_client.invoke(body, model_name=m)
        text = "".join(p.get("text", "") for p in (resp.get("content") or []) if isinstance(p, dict)).strip()
        text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
        verdict = json.loads(text)
        cited = [str(c) for c in (verdict.get("cited_beats") or [])][:4]
        if verdict.get("pass"):
            return True, [], cited
        return False, [str(r) for r in (verdict.get("fails") or ["failed craft rubric"])][:6], cited
    except Exception as e:
        logger.warning("[panel] craft judge unavailable — failing CLOSED (hold, don't publish): %s", e)
        return False, [f"craft-judge-error (fail-closed): {e}"], []


def _qa_gate(turns: list, rubric: str, ground_truth: str = "", max_consecutive: int = _QA_MAX_CONSECUTIVE) -> list:
    """Combined craft (deterministic) + LLM-judge gate. Returns all failure reasons (empty = clean).
    `max_consecutive` threads the floor-hog bound (weekly 2, intro 1 per #1123) into _craft_check."""
    return _craft_check(turns, max_consecutive) + _qa_review(turns, rubric, ground_truth)[1]
