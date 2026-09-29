"""quality_gate_note.py — the N-06 corrective note REVISES the draft it judged (#4343).

`ai_calls._enforce_quality_gate` turns a failing report into one corrective note and hands
it to the caller's `regenerate_fn`. Until #4343 the note carried the findings but NOT the
draft, and every caller's `regenerate_fn` appends the note to the ORIGINAL generation
prompt — so the "rewrite" was a fresh sample of the whole section, not an edit. On the
2026-09-28 brief (request `15d734b8`) the judge PASSED four drafts (sleep 92, mind 92,
physical 94, labs 92); each failed only a deterministic reader check (one banned word, a
figure with no window). The fresh samples fixed those and wrote new faults the drafts did
not have — sleep's final added `autocorrelation` and `slow-wave`, physical's added
`autocorrelation`, explorer's added `slope` — and six coaches were held.

Two rules here:

  1. **Revise, don't resample.** When the draft is known, the note quotes it and says:
     change only what the lines name, keep every other sentence. A draft that failed on
     one word comes back with that word replaced, not with a new section.
  2. **The note never hands the rewrite a banned term the draft did not use.** Judge-
     authored prose (a cross-coach similarity reason, a free-text suggestion) quotes the
     OTHER coach's wording — the sleep draft's similarity flag read "Both use
     autocorrelation threshold language". Any READER RULES term (`reader_checks.
     READER_BANNED_TERMS`, the deterministic list) that appears in such a line but not in
     the draft is replaced with "(jargon)" before the line is written. A term the draft
     DID use stays quoted: that is the deterministic `banned_term` fix naming its target.

The header says "REVIEW FEEDBACK", not "QUALITY GATE FEEDBACK": `gate` is itself a READER
RULES term, and the old header put it into every rewrite prompt (physical's 09-28 final
carried `gate`).

Pure: no I/O, never raises on a malformed report (the same contract the note had inside
`ai_calls`).
"""

from __future__ import annotations

import re
from typing import Any, Optional

JARGON_PLACEHOLDER = "(jargon)"
REVISION_LOG_TAG = "QG_REVISION"
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")

_HEADER = "REVIEW FEEDBACK — your previous draft failed review. Fix these specific issues:"
_HEADER_REVISE = (
    "REVIEW FEEDBACK — your draft (quoted below) failed review. REVISE that draft: fix only what each line "
    "below names and keep every other sentence as written. Do not add new material, new terms or new figures."
)
_TAIL = "Rewrite the full response addressing all of the above. Do not mention this feedback in the output."
_TAIL_REVISE = "Return the full revised section, and nothing else. Do not mention this feedback in the output."


def _banned_patterns() -> tuple:
    try:
        from coach.reader_checks import _BANNED_RES

        return tuple(rx for rx, _plain in _BANNED_RES)
    except Exception:  # noqa: BLE001 — a missing checks module leaves the note unscrubbed, never broken
        return ()


def scrub(line: str, draft: Optional[str], patterns: Optional[tuple] = None) -> str:
    """Replace every READER RULES term in `line` that `draft` does not itself contain."""
    pats = _banned_patterns() if patterns is None else patterns
    out = str(line or "")
    for rx in pats:
        if draft and rx.search(draft):
            continue
        out = rx.sub(JARGON_PLACEHOLDER, out)
    return out


def correction_note(report: Any, draft: Optional[str] = None) -> str:
    """Build the corrective note from a failing gate report (and, when known, its draft)."""
    report = report if isinstance(report, dict) else {}
    pats = _banned_patterns()

    def _s(text: Any) -> str:
        return scrub(str(text or ""), draft, pats)

    body = []
    for v in report.get("anti_pattern_violations") or []:
        phrase = v.get("phrase") if isinstance(v, dict) else v
        if phrase:
            body.append(f'  - Remove/avoid the forbidden phrase: "{phrase}"')
    for v in report.get("decision_class_violations") or []:
        if isinstance(v, dict):
            body.append(
                f"  - You exceeded the evidence ceiling (expected max: {v.get('expected_max', 'observational')}); "
                f"offending text: \"{_s(v.get('excerpt', ''))}\""
            )
    for flag in report.get("cross_coach_similarity_flags") or []:
        if isinstance(flag, dict):
            body.append(f"  - Too similar to {flag.get('similar_to', 'another coach')}: {_s(flag.get('reason', ''))}")
    for v in report.get("cycle_boundary_violations") or []:  # #1973
        if isinstance(v, dict):
            body.append(
                f'  - Add explicit prior-cycle framing (e.g. "last cycle", "cycle N") around: '
                f"\"{_s(v.get('excerpt', ''))}\" — {_s(v.get('reason', ''))}"
            )
    for s in report.get("suggestions") or []:
        if s:
            body.append(f"  - {_s(s)}")
    if not body:
        body.append("  - Write a more distinctive, on-voice draft that matches your persona.")

    text = (draft or "").strip()
    if not text:
        return "\n".join([_HEADER, *body, _TAIL])
    return "\n".join([_HEADER_REVISE, *body, "", "YOUR DRAFT:", "<<<", text, ">>>", _TAIL_REVISE])


def log_revision(coach_id: str, draft: str, revised: str) -> float:
    """Log how much of the draft the rewrite kept verbatim — the live-proof read for rule 1
    (a revision keeps most sentences; a resample keeps ~none). Returns the share."""
    sents = [s.strip() for s in _SENTENCE_RE.split(draft or "") if len(s.strip()) > 20]
    share = (sum(1 for s in sents if s in (revised or "")) / len(sents)) if sents else 0.0
    print(f"[COACH-QUALITY-GATE:{coach_id}] {REVISION_LOG_TAG} kept={share:.2f} of {len(sents)} draft sentence(s)")
    return share
