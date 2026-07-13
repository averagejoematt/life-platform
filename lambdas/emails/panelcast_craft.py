"""panelcast_craft — the podcast punch-up pass (the "script doctor", #1180, epic #1082).

Matthew's verdict on the factually-clean wk0 candidate: "if I showed this to a random
person it'd feel quite boring, AI generated — no humour, didn't have the arc of a true
podcast episode." The gate could prove a script was CLEAN; it could not make it a SHOW.
This module adds the missing craft layer, mirroring real production (writer, then
punch-up):

  After a draft clears the DETERMINISTIC checks (and any #1170 seam repair), ONE
  narrative-tier (Sonnet) pass is prompted ONLY to add humour, warmth, texture, quotable
  lines, and rhythm — never to change what happens. HARD LOCKS are enforced
  deterministically after the pass (``_locks_ok``): identical turn count, identical
  speaker order, no factual claim or number added/removed, every turn still under its word
  cap, every line still passing the caller's per-line gate. On ANY lock violation — or a
  parse/model error, or a deterministic regression the optional ``craft_check`` catches —
  the ORIGINAL un-punched draft is returned unchanged (``punched=False``). A punch-up
  problem NEVER fails the run. The punched script then re-enters the FULL gate (deterministic
  craft + Haiku structure/accuracy judge + the Sonnet ``_craft_judge``) exactly like a
  #1171 revision, and the per-attempt ledger records ``punched`` true/false.

Pure mechanics with an injected bedrock invoke — no module-level AWS state, so the lambda
stays the single owner of its boto3 clients and tests run fully offline.
"""

import json
import os
import re

try:  # bundle stages lambdas/ at the zip root; tests add lambdas/emails/ to sys.path
    from emails.panelcast_qa import _QA_HOOK_MAX_WORDS, _QA_MAX_WORDS_PER_TURN
except ImportError:
    from panelcast_qa import _QA_HOOK_MAX_WORDS, _QA_MAX_WORDS_PER_TURN

# Narrative tier (ADR-049): the script doctor is a creative rewrite → Sonnet, env-overridable.
PUNCH_UP_MODEL = os.environ.get("AI_MODEL_SONNET", "claude-sonnet-4-6")

# Any run of digits is a "number" for the lock — the punch-up must not add or drop one.
_NUM_RE = re.compile(r"\d+")

PUNCH_UP_SYSTEM = (
    "You are a comedy-and-warmth script doctor doing a punch-up pass on a FINISHED two-person "
    "podcast script. An editor has already locked the structure and the facts; your ONE job is to "
    "make it funnier, warmer, and more human WITHOUT changing what happens. Go turn by turn and, "
    "where a line is flat, rewrite it IN PLACE — sharpen it into dry humour, warmth, a vivid image, "
    "a quotable turn of phrase, a beat of real personality or rhythm. Leave a line untouched if it "
    "already sings. You are polishing the VOICE, never the content.\n"
    "ABSOLUTE LOCKS (break one and your entire pass is discarded): keep EXACTLY the same number of "
    "turns in EXACTLY the same order; never add, remove, reorder, split, or merge a turn; never "
    "change who speaks a turn; introduce NO new fact, name, event, or number and remove none — every "
    "number and factual claim already in a line must survive; keep every turn under its word cap "
    "(you are polishing, not expanding).\n"
    "OUTPUT: ONLY the JSON array of the SAME turns in the SAME order, lines rewritten in place: "
    '[{"speaker":"...","line":"..."}]. No preamble, no fences.'
)


def _numbers(turns) -> list:
    """The sorted multiset of numeric tokens across every line — the deterministic proxy for
    'no number added or removed'. Locks require this list to be IDENTICAL before vs after."""
    nums = []
    for t in turns or []:
        nums += _NUM_RE.findall(t.get("line") or "")
    return sorted(nums)


def _locks_ok(draft, punched, line_ok=None) -> bool:
    """The HARD LOCKS, enforced deterministically AFTER the punch-up pass. True only when
    ``punched`` is a line-for-line rewrite of ``draft``: identical turn count and speaker
    order, every line non-empty and under its word cap (turn 0 keeps the longer cold-open
    ceiling), the number multiset unchanged, and each line still passing the caller's
    per-line gate (ER-03 / safety / Day-Zero). This does NOT prove facts unchanged on its
    own — the punched script re-enters the FULL gate afterward, which owns grounding."""
    if not isinstance(punched, list) or len(punched) != len(draft):
        return False
    for i, (d, p) in enumerate(zip(draft, punched)):
        if not isinstance(p, dict) or p.get("speaker") != d.get("speaker"):
            return False
        line = (p.get("line") or "").strip()
        if not line:
            return False
        cap = _QA_HOOK_MAX_WORDS if i == 0 else _QA_MAX_WORDS_PER_TURN
        if len(line.split()) > cap:
            return False
        if line_ok is not None and not line_ok(line):
            return False
    return _numbers(draft) == _numbers(punched)


def punch_up_script(turns, invoke, model, extract_json, logger, line_ok=None, craft_check=None):
    """#1180: ONE Sonnet punch-up pass over a deterministically-clean draft. Returns
    ``(out_turns, punched_bool)``. The pass may only rewrite lines in place for
    humour/warmth/texture/rhythm; ``_locks_ok`` is enforced afterward and on ANY lock
    violation — or a parse/model error, or (when ``craft_check`` is given) a deterministic
    regression the punch introduced — the ORIGINAL draft is returned unchanged with
    ``punched=False``. A punch-up problem never fails the run; the worst case is a no-op."""
    if not turns:
        return turns, False
    user = "SCRIPT TO PUNCH UP (rewrite lines in place — same turns, same order, same speakers):\n" + json.dumps(turns, ensure_ascii=False)
    body = {"model": model, "max_tokens": 4000, "system": PUNCH_UP_SYSTEM, "messages": [{"role": "user", "content": user}]}
    try:
        resp = invoke(body, model_name=model)
        text = "".join(p.get("text", "") for p in (resp.get("content") or []) if isinstance(p, dict)).strip()
        rep = extract_json(text)
    except Exception as e:  # noqa: BLE001 — a punch-up problem must never fail the run
        logger.warning("[panel] punch-up unavailable — keeping the draft: %s", e)
        return turns, False
    if not _locks_ok(turns, rep, line_ok):
        logger.info("[panel] punch-up rejected (lock violation) — keeping the un-punched draft")
        return turns, False
    if craft_check is not None and craft_check(rep):
        logger.info("[panel] punch-up introduced a deterministic regression — keeping the un-punched draft")
        return turns, False
    logger.info("[panel] punch-up applied (%d turns rewritten in place)", len(rep))
    return rep, True
