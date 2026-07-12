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

# ── QA rigor (automates the manual review loop, 2026-06-17) ───────────────────
# Two layers on top of the ER-03 + Compassion gates, both catching CRAFT/accuracy
# problems those deterministic safety gates can't see (monologue dumps, no tension,
# invented biography, abrupt flow). A generator that fails QA is RE-ROLLED up to
# _QA_MAX_ATTEMPTS times (generation is non-deterministic, so a re-roll usually
# fixes it); the best candidate is kept. See the 2026-06-17 handover.
_QA_MAX_ATTEMPTS = int(os.environ.get("PANEL_QA_MAX_ATTEMPTS", "3"))
_QA_MAX_WORDS_PER_TURN = 130  # a turn longer than this reads as a monologue, not dialogue
_QA_HOOK_MAX_WORDS = 180  # turn 0 is the cold-open hook — a solo turn by design, allowed to run longer
_QA_MAX_CONSECUTIVE = 3  # 4+ turns from one speaker is a floor-hog; 3 short turns reads fine (calibrated 2026-06-17)

# #1122: a turn that ASKS something (interrogative or an explicit challenge) must get a
# reply from the OTHER speaker in the very next turn. The observed wk0 defect: a gate
# dropped Eli's answer, leaving Elena's "convince me this isn't just a beautiful
# dashboard" followed by Elena's own "here's where I push back" — a conversational hole
# the 4-in-a-row check can't see (it's only 2 same-speaker turns).
_CHALLENGE_RE = re.compile(r"\b(convince me|push back|here'?s where|prove it)\b", re.IGNORECASE)
# Interrogative = the line ends on a question mark, allowing trailing quotes/brackets.
_INTERROGATIVE_RE = re.compile(r"\?[\"'”’)\]]*\s*$")


def _continuity_check(turns: list) -> list:
    """Deterministic conversational-continuity gate (#1122; deterministic-before-LLM, ADR-105).
    Flags any turn that is interrogative (ends '?') or an explicit challenge whose NEXT turn
    is the SAME speaker — i.e. the reply is missing, the tell of a dropped turn. Runs on the
    post-drop script (the gates can delete turns and leave exactly this hole). Turn 0 is
    exempt: the solo cold-open hook closes on a rhetorical question by design, and the fixed
    Elena cold-open may be prepended in front of her own hook. The final turn is never
    flagged — closing on the series' open question is the intended ending."""
    fails = []
    for i in range(1, len(turns) - 1):
        spk = turns[i].get("speaker")
        if spk != turns[i + 1].get("speaker"):
            continue
        line = (turns[i].get("line") or "").strip()
        if _INTERROGATIVE_RE.search(line):
            what = "asks a question"
        elif _CHALLENGE_RE.search(line):
            what = "issues a challenge"
        else:
            continue
        fails.append(f"dangling thread: turn {i} ({spk}) {what} but the reply is missing — turn {i + 1} is {spk} again")
    return fails


def _craft_check(turns: list) -> list:
    """Deterministic, zero-cost craft gate. Returns a list of failure reasons (empty = pass).
    Catches exactly the pacing problems an LLM judge is unreliable at: monologue dumps and
    one speaker holding the floor too long. Calibrated 2026-06-17: 4+ consecutive turns is the
    real floor-hog (3 short turns reads fine), and turn 0 is the intentional solo cold-open hook
    (a longer ceiling, not the dialogue cap)."""
    fails = []
    run = 1
    for i in range(1, len(turns)):
        run = run + 1 if turns[i].get("speaker") == turns[i - 1].get("speaker") else 1
        if run > _QA_MAX_CONSECUTIVE:
            fails.append(f"{turns[i].get('speaker')} speaks {run} turns in a row (max {_QA_MAX_CONSECUTIVE}) — break it up")
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


_INTRO_RUBRIC = (
    "The two speakers are ELENA VOSS (the host — an embedded journalist) and DR. ELI MARSH (the guest — the "
    "Principal Investigator who built the platform). MATT is the third-person SUBJECT of the experiment; he is NOT "
    "in the room and does NOT speak. These three are ESTABLISHED show personas — never treat Elena or Eli as invented.\n"
    "1. Opens on a genuine HOOK in turn 0, not a flat self-introduction.\n"
    "2. After the opening, it's a real two-person conversation (no long stretch of one person talking).\n"
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
    "missing. (Coverage is NOT required — only flag a thread the script opens and abandons.)"
)


_WEEKLY_RUBRIC = (
    "Two speakers: ELENA VOSS (host, embedded journalist) and the GUEST COACH (an AI coach, named in the script). "
    "MATT is the third-person SUBJECT of the experiment — he is NOT in the room and does NOT speak. Elena and the "
    "coaches are ESTABLISHED show personas (never flag them as invented). Judge it as a real podcast a human would "
    "believe is human-made and would recommend to a friend:\n"
    "1. READ-ALOUD TURING TEST: read aloud, it must sound human-written. Flag any AI tell — 'in this episode', "
    "narrating the format or naming segments, tidy three-item lists, 'not just X, it's Y' symmetry, over-explaining, "
    "hedge throat-clearing, or a neat summary bow at the end.\n"
    "2. GUEST INTRODUCTION: the guest is introduced for the audience early (who they are + what they work on), UNLESS "
    "they were the guest in the immediately previous episode. A guest who just starts talking with no introduction FAILS.\n"
    "3. NO DANGLING THREAD: every question Elena asks is actually answered in the next turn; no topic the SCRIPT itself "
    "raises is then dropped; no abrupt unbridged jump; never two same-speaker turns where a reply is clearly missing. "
    "(Coverage is NOT required — do NOT flag a ground-truth fact that simply goes unmentioned; only flag a thread the "
    "script opens and abandons.)\n"
    "4. REAL HOOK: turn 0 earns attention — not a flat 'welcome to the show'.\n"
    "5. GENUINE FRICTION: at least one real disagreement or tension, not constant agreement.\n"
    "6. GROUNDED: every specific claim, number, or event about MATT traces to the GROUND TRUTH. No invented scenes, "
    "times of day, or sensory detail (e.g. a '5 AM protein shake'). Flag anything not in the ground truth.\n"
    "7. NO BODY WEIGHT IN THE SCRIPT: no body-weight figure appears in the spoken lines, numeric or spelled-out "
    "(e.g. 'nine pounds'). Body weight in the GROUND TRUTH is fine and expected — only flag it if it is SPOKEN in the script.\n"
    "8. HUMOUR & HUMAN INTEREST: at least one genuinely warm or dryly funny human beat — not dry data recitation."
)


def _qa_gate(turns: list, rubric: str, ground_truth: str = "") -> list:
    """Combined craft (deterministic) + LLM-judge gate. Returns all failure reasons (empty = clean)."""
    return _craft_check(turns) + _qa_review(turns, rubric, ground_truth)[1]
