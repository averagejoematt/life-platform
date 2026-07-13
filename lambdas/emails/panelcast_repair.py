"""panelcast_repair — the podcast no-touch contract's mechanics (#1170/#1171/#1172, ADR-135).

Prompt rules empirically cannot guarantee structural output properties: 0/15 wk0
regenerations cleared the #1122 gate on 2026-07-12, with same-speaker seams written by
the model itself under an explicit STRICT-ALTERNATION ban. So structure is enforced
deterministically, in three layers:

  • repair_structure (#1170) — detect same-speaker adjacency seams with the gate's OWN
    detection (panelcast_qa.structural_seams) and run ONE targeted generation per seam
    that restructures just the local context into alternating turns (merge where it
    flows; split into an exchange where a merge would breach the word cap). The
    repaired script then goes back through the FULL unchanged gate (deterministic +
    judge) — this module never bypasses, weakens, or pre-clears any check; a failed or
    invalid repair simply keeps the original span for the gate to hold.
  • revise_intro / revise_weekly (#1171) — the convergent-revision step: the judge's
    exact failure items fed back to the writer (the mechanism behind both live weekly
    episodes), ≤ MAX_REVISIONS per generation instead of blind re-rolls.
  • ledger_entry / log_ledger / send_exhaustion_email (#1172) — the bounded-escalation
    floor: every attempt's verdicts go into a per-run ledger (stable CloudWatch prefix
    "[panel] qa-ledger" so convergence is measurable across weeks); on budget
    exhaustion the run publishes NOTHING and ONE needs-human email carries the ledger.

Pure mechanics with injected clients (bedrock invoke, sesv2) — no module-level AWS
state, so the lambda stays the single owner of its boto3 clients and tests run offline.
"""

import json
import os

try:
    from emails.panelcast_qa import _QA_HOOK_MAX_WORDS, _QA_MAX_CONSECUTIVE, _QA_MAX_WORDS_PER_TURN, structural_seams
except ImportError:  # bundle stages lambdas/ at the zip root
    from panelcast_qa import _QA_HOOK_MAX_WORDS, _QA_MAX_CONSECUTIVE, _QA_MAX_WORDS_PER_TURN, structural_seams

# #1172: the fixed attempt budget — panelcast_qa._QA_MAX_ATTEMPTS generations, each with
# up to MAX_REVISIONS judge-feedback revisions. Exhaustion escalates; never a silent miss.
MAX_REVISIONS = int(os.environ.get("PANEL_QA_MAX_REVISIONS", "2"))
# Repair spend bound: ONE generation per seam, at most this many seams per generation
# attempt (a healthy post-#1168 draft has 0–2 seams; more than this means re-write, and
# the gate + revision loop already own that path).
MAX_SEAM_REPAIRS = int(os.environ.get("PANELCAST_MAX_SEAM_REPAIRS", "4"))


# #1123: the Episode-0 cold-open name lock. INTRO_COLD_OPEN (owned by the lambda) names
# Elena AND states the whole hook; when the model's turn 0 already IS a hook and merely
# failed to name her, prepending the full cold-open reads doubled and creates an Elena+Elena
# t0/t1 seam. The cheap fix prefixes ONLY this one name sentence onto her own hook instead.
INTRO_NAME_SENTENCE = "I'm Elena Voss, the journalist living inside this experiment."
_ELENA_NAME_MARKERS = ("i'm elena", "i am elena", "elena voss")


def name_the_opener(turns, host_speaker, cold_open):
    """#1123: Episode 0's turn 0 must name the host. Cheap fix — when the host speaks first
    with a real hook but never names herself, prefix ONLY INTRO_NAME_SENTENCE onto her OWN
    hook so turn 0 stays a single solo hook (no host+host t0/t1 seam, no doubled hook a full
    `cold_open` prepend would create). Fall back to prepending `cold_open` as a new turn 0
    only when the opener is NOT the host's, or naming in place would breach the hook word cap;
    under the strict-alternation intro bound the repair pass then merges any seam that leaves."""
    if not turns:
        return turns
    line = turns[0].get("line", "")
    if any(m in line.lower() for m in _ELENA_NAME_MARKERS):
        return turns
    prefixed = f"{INTRO_NAME_SENTENCE} {line}"
    if turns[0].get("speaker") == host_speaker and len(prefixed.split()) <= _QA_HOOK_MAX_WORDS:
        turns[0]["line"] = prefixed
    else:
        turns.insert(0, {"speaker": host_speaker, "line": cold_open})
    return turns


def _invoke_text(invoke, model: str, system: str, user: str, max_tokens: int) -> str:
    body = {"model": model, "max_tokens": max_tokens, "system": system, "messages": [{"role": "user", "content": user}]}
    resp = invoke(body, model_name=model)
    return "".join(p.get("text", "") for p in (resp.get("content") or []) if isinstance(p, dict)).strip()


def _replacement_ok(rep, before_spk, after_spk, speakers, line_ok) -> bool:
    """Deterministic sanity on a seam repair: right shape, known speakers, alternating
    internally AND against both boundary turns, every line within the dialogue word cap
    and past the caller's per-line checks (ER-03/safety/Day-Zero). This is NOT the gate
    — just "is this splice coherent"; the full unchanged gate still judges the whole
    repaired script afterward."""
    if not isinstance(rep, list) or not rep:
        return False
    prev = before_spk
    for t in rep:
        if not isinstance(t, dict):
            return False
        spk = t.get("speaker")
        line = (t.get("line") or "").strip()
        if spk not in speakers or not line or spk == prev:
            return False
        if len(line.split()) > _QA_MAX_WORDS_PER_TURN:
            return False
        if line_ok is not None and not line_ok(line):
            return False
        prev = spk
    return after_spk is None or rep[-1].get("speaker") != after_spk


def _repair_seam(turns, s, e, speakers, invoke, model, extract_json, line_ok):
    """ONE targeted repair generation for the seam turns[s..e]: the model sees ONLY the
    offending span + up to 2 surrounding turns each side, and returns replacement turns
    that alternate. Returns the validated replacement list, or None (keep the original
    span — the gate downstream holds it)."""
    lo, hi, e1 = max(0, s - 2), min(len(turns), e + 3), e + 1
    before, span, after = turns[lo:s], turns[s:e1], turns[e1:hi]
    system = (
        "You are a dialogue-script surgeon. A two-person podcast script has a structural defect: several CONSECUTIVE "
        "turns belong to the SAME speaker. Restructure ONLY the marked span into genuinely ALTERNATING turns between "
        "the two speakers, preserving the span's content, its order of ideas, and each speaker's voice. Merge material "
        f"where it flows; where a merged turn would exceed {_QA_MAX_WORDS_PER_TURN} words, split it into an exchange "
        "instead — the other speaker briefly reacts or asks, and the thought continues in the reply. Invent NO new "
        "facts, numbers, or events; any inserted reaction must be content-free connective tissue ('Right.', 'Go on.', "
        "a pointed question about what was just said). Hard rules: never two consecutive turns from the same speaker; "
        "the FIRST replacement turn must not share a speaker with the turn BEFORE the span; the LAST must not share a "
        f"speaker with the turn AFTER the span; every turn is at most {_QA_MAX_WORDS_PER_TURN} words. "
        'Output ONLY the JSON array that replaces the marked span: [{"speaker":"...","line":"..."}]. '
        "No prose, no fences."
    )
    user = json.dumps(
        {
            "the_two_speakers": sorted(speakers),
            "context_before_span (do NOT return these)": before,
            "SPAN_TO_RESTRUCTURE (return the replacement for exactly this)": span,
            "context_after_span (do NOT return these)": after,
        },
        ensure_ascii=False,
    )
    rep = extract_json(_invoke_text(invoke, model, system, user, 1500))
    before_spk = turns[s - 1].get("speaker") if s > 0 else None
    after_spk = turns[e + 1].get("speaker") if e + 1 < len(turns) else None
    return rep if _replacement_ok(rep, before_spk, after_spk, speakers, line_ok) else None


def repair_structure(
    turns, speakers, invoke, model, extract_json, logger, line_ok=None, max_repairs=MAX_SEAM_REPAIRS, max_consecutive=_QA_MAX_CONSECUTIVE
):
    """#1170: deterministic seam detection + ONE targeted repair generation per seam.
    Returns (turns, seams_found, seams_repaired). A failed/invalid repair keeps the
    ORIGINAL span, and the result must still clear the full unchanged gate downstream —
    repair can only help, never bypass. Seams are spliced last-to-first so earlier
    indices never shift; zero-cost (no model call) when the script already alternates.
    `max_consecutive` is the SAME bound the gate's _craft_check enforces (weekly 2, intro 1
    per #1123) — passed straight into structural_seams so repair and gate never disagree."""
    seams = structural_seams(turns, max_consecutive)
    if not seams:
        return turns, 0, 0
    if len(seams) > max_repairs:
        logger.info("[panel] repair: %d seams found, repairing the first %d (spend bound)", len(seams), max_repairs)
    out, repaired = list(turns), 0
    for s, e in reversed(seams[:max_repairs]):
        try:
            rep = _repair_seam(out, s, e, set(speakers), invoke, model, extract_json, line_ok)
        except Exception as ex:  # noqa: BLE001 — a repair error must never kill the run; the gate judges the original
            logger.warning("[panel] repair: seam (%d,%d) generation failed — keeping original: %s", s, e, ex)
            rep = None
        if rep:
            end = e + 1
            out[s:end] = rep
            repaired += 1
    logger.info("[panel] repair: %d seam(s) found, %d repaired", len(seams), repaired)
    return out, len(seams), repaired


def revise_intro(turns, fails, invoke, model, extract_json, logger):
    """#1171: the weekly targeted-revision mechanism, ported to the intro path — the
    judge's exact failure items go back to the writer for a fixed FULL script instead of
    a blind re-roll. Returns the revised raw turns (speaker "elena"|"eli") or [] — the
    caller re-gates them through the SAME intro line gates as a fresh generation."""
    script_text = "\n".join(f"{t.get('speaker')}: {t.get('line')}" for t in turns)
    system = (
        'You are the head writer revising a draft of "The Measured Life" Episode 0 — host ELENA VOSS (embedded '
        "journalist), guest DR. ELI MARSH (the Principal Investigator); MATT is the third-person subject and never "
        "speaks. Fix EVERY issue listed below and keep everything that already works. Invent nothing about Matt (no "
        "events, losses, dates, numbers, or any weight); turns STRICTLY ALTERNATE — never two consecutive turns from "
        "the same speaker; every question or challenge is answered substantively by the OTHER speaker in the very "
        f"next turn; every turn is at most {_QA_MAX_WORDS_PER_TURN} words. Return ONLY the full fixed script as a "
        'JSON array: [{"speaker":"elena"|"eli","line":"..."}], 20-28 turns. No prose, no fences.'
    )
    user = (
        "ISSUES TO FIX (every one):\n- "
        + "\n- ".join(str(f) for f in fails)
        + f"\n\nDRAFT TO REVISE:\n{script_text}\n\nReturn the fixed JSON now."
    )
    try:
        parsed = extract_json(_invoke_text(invoke, model, system, user, 4000))
        return parsed if isinstance(parsed, list) else []
    except Exception as e:
        logger.warning("[panel] intro revision failed — %s", e)
        return []


def revise_weekly(turns, fails, guest_name, show_name, invoke, model, extract_json, logger):
    """Self-correction on the weekly path (moved from the lambda at the ADR-080 size
    gate): hand the writer its own draft + the QA judge's exact failures and ask for a
    fixed full script (same JSON shape). This is the loop that lets the show reach the
    read-aloud bar on its own before falling back to a human HOLD."""
    script_text = "\n".join(f"{t.get('speaker')}: {t.get('line')}" for t in turns)
    system = (
        f'You are the head writer revising a draft of "{show_name}". Fix EVERY issue '
        "listed below and keep everything that already works. THE BAR: the transcript must read as a real, human-made "
        "podcast — no AI tells. Stay grounded (invent nothing — no facts, scenes, times of day, or numbers not already "
        f"present); keep the guest as {guest_name}; introduce a guest the audience hasn't met; every question gets "
        "an answer in the next turn; never two consecutive turns from the same speaker; no body weight (numeric or "
        "spelled-out). Return ONLY the same JSON shape: "
        '{"turns":[{"speaker":"elena"|"coach","line":"..."}],"open_bet":"...","last_bet_result":{"outcome":"won"|"lost"|"open"|"none"},'
        '"pull_quote":"..."}. 14-22 turns. No fences.'
    )
    user = (
        "ISSUES TO FIX (every one):\n- "
        + "\n- ".join(str(f) for f in fails)
        + f"\n\nDRAFT TO REVISE:\n{script_text}\n\nReturn the fixed JSON now."
    )
    try:
        parsed = extract_json(_invoke_text(invoke, model, system, user, 3500))
        return parsed if isinstance(parsed, dict) and parsed.get("turns") else {}
    except Exception as e:
        logger.warning("[panel] weekly revision failed — %s", e)
        return {}


def ledger_entry(attempt, revision, deterministic, judge, repaired_seams=0, punched=None, citations=None) -> dict:
    """One row of the per-attempt verdict ledger (#1171) — compact and transcript-free,
    so it can ride the hold record and the escalation email verbatim. #1180: full gate-pass
    rows also record whether the Sonnet punch-up was applied (``punched`` true/false) and the
    craft judge's quoted evidence (``citations``); rows that never reach the craft layer
    (no-candidate / editor-hold / dropped-turns) omit both."""
    entry = {
        "attempt": attempt,
        "revision": revision,
        "deterministic": [str(f)[:160] for f in (deterministic or [])][:8],
        "judge": [str(f)[:160] for f in (judge or [])][:8],
        "repaired_seams": repaired_seams,
    }
    if punched is not None:
        entry["punched"] = bool(punched)
    if citations is not None:
        entry["citations"] = [str(c)[:200] for c in citations][:4]
    return entry


def log_ledger(logger, path: str, week, ledger: list) -> None:
    """Emit the run's verdict ledger as ONE stable-prefix CloudWatch line so convergence
    is measurable across weeks: filter on '[panel] qa-ledger'. Fail-open telemetry."""
    try:
        logger.info("[panel] qa-ledger %s", json.dumps({"path": path, "week": week, "attempts": ledger}, ensure_ascii=False))
    except Exception:  # noqa: BLE001 — telemetry must never change the pipeline's decision
        pass


def send_exhaustion_email(ses, sender, recipient, week, path, ledger, logger, hold_uri="") -> dict:
    """#1172: the needs-human escalation — ONE email when the attempt budget is
    exhausted. The episode HOLDs and NOTHING publishes (that decision is made by the
    caller before this is invoked); this email only summarizes the per-attempt failure
    modes from the ledger, never raw transcripts. Fail-open: a mail hiccup must never
    change the publish-nothing outcome. Skips cleanly when no notification address is
    configured (offline/test environments)."""
    attempts = len({e.get("attempt") for e in ledger}) or 1
    if not recipient:
        logger.warning("[panel] exhaustion escalation: no EMAIL_RECIPIENT configured — email skipped (the HOLD stands)")
        return {"sent": 0, "skipped": "no recipient"}
    subject = f"Panelcast HOLD — {path} episode wk{week} failed the gate after {attempts} attempts"
    lines = [
        f"The {path} panelcast run for wk{week} exhausted its attempt budget "
        f"({attempts} generation(s) x up to {MAX_REVISIONS} targeted revisions each) without clearing the QA gate.",
        "Nothing was published. The draft is HELD for human review (the gate stays fail-closed, ADR-135).",
        "",
        "Per-attempt verdict ledger:",
    ]
    for e in ledger:
        lines.append(f"  attempt {e.get('attempt')} · revision {e.get('revision')} · repaired seams: {e.get('repaired_seams', 0)}")
        lines.append(f"    deterministic: {'; '.join(e.get('deterministic') or []) or 'clean'}")
        lines.append(f"    judge: {'; '.join(e.get('judge') or []) or 'clean'}")
    if hold_uri:
        lines += ["", f"Hold draft (full transcript + ledger): {hold_uri}"]
    try:
        ses.send_email(
            FromEmailAddress=sender,
            Destination={"ToAddresses": [recipient]},
            Content={
                "Simple": {
                    "Subject": {"Data": subject[:120], "Charset": "UTF-8"},
                    "Body": {"Text": {"Data": "\n".join(lines), "Charset": "UTF-8"}},
                }
            },
        )
        logger.info("[panel] exhaustion escalation email sent (%s wk%s, %d attempts)", path, week, attempts)
        return {"sent": 1}
    except Exception as e:  # noqa: BLE001 — fail-open; the HOLD itself already alerted via SNS
        logger.warning("[panel] exhaustion escalation email failed (fail-open) — %s", e)
        return {"sent": 0, "error": str(e)[:200]}
