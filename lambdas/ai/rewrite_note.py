"""rewrite_note.py — the N-06 corrective note REVISES the draft it judged (#4343).

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

**Rule 1 needed a shape, not a sentence (the 2026-09-30 brief, request `3958f82a`).** With
the draft quoted and "keep every other sentence as written" in the note, the rewrite still
came back as a paraphrase of the whole section: `QG_REVISION kept=0.03 of 30` (physical),
`0.00 of 27` (labs), `0.00 of 26` (explorer). The callers' `regenerate_fn` re-runs the ORIGINAL
generation prompt with the note appended, and a model re-reading its whole brief writes the
section again; the retained finals kept the draft's paragraph plan and changed every
sentence, adding faults the drafts did not have (labs' final introduced "48 hours", a
fabricated number; physical's introduced "around 1,600" calories and "exceptional"). So a
caller that opts in (`ai_calls._enforce_quality_gate(..., revise=True)`) now asks for EDITS:
a JSON list of `{"find": <a sentence copied from the draft>, "replace": <its fix>}`, and
`apply_edits` applies them to the draft in code. A sentence no edit names is kept verbatim by
construction, not by request. A reply that is not an edit list is taken as a full rewrite (the
old behaviour); an edit list none of whose `find`s is in the draft changes nothing, so it is
returned empty and the caller keeps the prior draft.

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
_HEADER_EDITS = (
    "REVIEW FEEDBACK — your draft (quoted below) failed review. Do NOT rewrite it. Fix only what each line below "
    "names, as sentence edits. Every sentence you do not name is kept exactly as written. A replacement adds no new "
    "material, terms or figures; to fix a figure, remove it or use one already in your data."
)
_TAIL_EDITS = (
    'Return ONLY a JSON object: {"edits": [{"find": "<one sentence copied exactly from YOUR DRAFT>", '
    '"replace": "<the corrected sentence, or an empty string to delete it>"}]}. One edit per sentence you change. '
    "No other text."
)
_JSON_RE = re.compile(r"\{.*\}", re.S)


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


def correction_note(report: Any, draft: Optional[str] = None, edits: bool = False) -> str:
    """Build the corrective note from a failing gate report (and, when known, its draft).
    `edits=True` asks for a JSON edit list (see `apply_edits`) instead of the whole section."""
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
    if edits:
        return "\n".join([_HEADER_EDITS, *body, "", "YOUR DRAFT:", "<<<", text, ">>>", _TAIL_EDITS])
    return "\n".join([_HEADER_REVISE, *body, "", "YOUR DRAFT:", "<<<", text, ">>>", _TAIL_REVISE])


def parse_edits(response: Any) -> Optional[list]:
    """The `{"edits": [...]}` list in a reply, or None when the reply is not an edit list."""
    import json

    m = _JSON_RE.search(str(response or ""))
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
    except (ValueError, TypeError):
        return None
    raw = obj.get("edits") if isinstance(obj, dict) else None
    if not isinstance(raw, list):
        return None
    return [e for e in raw if isinstance(e, dict) and isinstance(e.get("find"), str) and isinstance(e.get("replace", ""), str)]


def apply_edits(draft: str, response: Any) -> str:
    """Apply a reply's sentence edits to `draft`. A reply that is not an edit list is returned
    as-is (a full rewrite); an edit list that changes nothing returns "" (keep the prior draft)."""
    found = parse_edits(response)
    if found is None:
        return str(response or "")
    out, applied = draft or "", 0
    for e in found:
        find, repl = e["find"].strip(), str(e.get("replace") or "").strip()
        if len(find) < 8 or find not in out:
            continue
        out, applied = out.replace(find, repl, 1), applied + 1
    if not applied:
        return ""
    out = re.sub(r"[ \t]{2,}", " ", out)
    out = re.sub(r" +([.,;:!?])", r"\1", out)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(line.strip() for line in out.split("\n"))).strip()


def log_revision(coach_id: str, draft: str, revised: str) -> float:
    """Log how much of the draft the rewrite kept verbatim — the live-proof read for rule 1
    (a revision keeps most sentences; a resample keeps ~none). Returns the share."""
    sents = [s.strip() for s in _SENTENCE_RE.split(draft or "") if len(s.strip()) > 20]
    share = (sum(1 for s in sents if s in (revised or "")) / len(sents)) if sents else 0.0
    print(f"[COACH-QUALITY-GATE:{coach_id}] {REVISION_LOG_TAG} kept={share:.2f} of {len(sents)} draft sentence(s)")
    return share
