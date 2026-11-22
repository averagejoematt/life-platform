"""content/chapter_corrections.py — dated public corrections to published chapters (#6177, owner rulings 2026-11-22 §3, §7).

THE RULINGS. §3: an unsupported or wrong statement in a published chapter gets "a dated public correction or visible
qualification through the established publication-correction process"; the original editions and the evidence behind
them are preserved. §7: "Do not present Margaret as an independent human editor. For existing historical corrections,
preserve their audit trail and clearly disclose the character's AI status. For future corrections, prefer a
transparent platform editorial signature with date, factual explanation and approval history."

THE RECORD. One DynamoDB item per correction, in the chronicle partition beside the chapter it corrects
(``USER#<id>#SOURCE#chronicle`` / ``CHAPTER_CORRECTION#<chapter_id>#<correction_id>``): the chapter id (the v9 id,
``week-NN``), the kind (``correction`` | ``qualification``), what the chapter published, what the record shows, an
evidence reference, and — once approved — the day it is dated, the platform's signature and the approval history. The
chronicle row, its body and the published pages are never touched: a correction is rendered BESIDE the chapter.

THE RULES THIS MODULE HOLDS (pure; the MCP tool is the only writer, the Site API the only public reader):
  * Public only after the owner's explicit approval, recorded ON the record (``approvals``). An unapproved record is
    never served, whatever else it says (``public_view``).
  * Append-only. A proposal is written once (conditional put); the approval appends to ``approvals`` and stamps
    ``dated_on`` + ``signature`` once (conditional update); no field of the statement is ever rewritten and nothing is
    deleted (the MCP role has no DeleteItem outside the meal partition). A later correction SUPERSEDES an earlier one
    by naming it; the earlier one is still served, marked superseded, so it is never silently removed.
  * The signature is the platform's (``PLATFORM_SIGNATURE``), computed here, never supplied. A record whose stored
    signature is anything else — a persona's name in particular — fails ``validate`` and is never served.
  * The October 2026 editor's notes signed "Margaret Calloway" stay exactly as published (their audit trail). Every
    surface that renders one carries ``PERSONA_DISCLOSURE``, the one plain line that says what she is.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Optional

USER_ID_DEFAULT = "matthew"
SK_PREFIX = "CHAPTER_CORRECTION#"
RECORD_TYPE = "chapter_correction"
KINDS = ("correction", "qualification")
PLATFORM_SIGNATURE = "Average Joe Matt editorial record"
APPROVER = "owner"
APPROVED_VIA = "MCP manage_chapter_corrections (owner-only)"
PROPOSED_VIA = "MCP manage_chapter_corrections"

#: The one plain line every surface that renders a Margaret-signed editor's note carries (www/src/lib/chapter_corrections.js
#: PERSONA_DISCLOSURE is pinned equal to it, tests/test_chapter_corrections_6177.py).
PERSONA_DISCLOSURE = "Margaret Calloway is an AI editorial persona of the platform, not a person."
#: The persona that signed the October 2026 editor's notes — matched to decide where the disclosure renders.
LEGACY_SIGNER = "Margaret Calloway"

CHAPTER_ID = re.compile(r"^week-\d{2}$")
CORRECTION_ID = re.compile(r"^[a-z0-9][a-z0-9-]{2,63}$")
ISO_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ISO_INSTANT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$")
MAX_STATEMENT = 700
MAX_EVIDENCE = 400
MAX_NOTE = 300
#: The fields of the statement — written once by the proposal, never updated.
STATEMENT_FIELDS = ("chapter_id", "correction_id", "kind", "published_said", "record_shows", "evidence", "supersedes")
#: What the public view serves (and the snapshot carries) for one correction — nothing else rides along.
PUBLIC_FIELDS = (
    "id",
    "chapter_id",
    "kind",
    "dated_on",
    "signature",
    "published_said",
    "record_shows",
    "evidence",
    "approvals",
    "supersedes",
    "superseded_by",
)
PUBLIC_APPROVAL_FIELDS = ("by", "on", "via")
_EDITORS_NOTE = re.compile(r"editor[’']s note", re.IGNORECASE)


class CorrectionError(ValueError):
    """A record that may not be written or served, with the reason."""


def pk(user_id: str = USER_ID_DEFAULT) -> str:
    return f"USER#{user_id}#SOURCE#chronicle"


def sk(chapter_id: str, correction_id: str) -> str:
    return f"{SK_PREFIX}{chapter_id}#{correction_id}"


def day_words(iso_day: str) -> str:
    """ "2026-11-22" -> "22 November 2026" (the site prints dates in words)."""
    from common.pacific_time import parse_day_key  # THE calendar-day parse (#3741, #3609)

    d = parse_day_key(iso_day)
    if d is None:
        raise CorrectionError(f"not a day: {iso_day!r}")
    return f"{d.day} {d.strftime('%B %Y')}"


def signature(kind: str, dated_on: str) -> str:
    """The platform's signature — the only one a new correction carries: "Correction, 22 November 2026 — Average Joe
    Matt editorial record". Never a person's or a persona's name."""
    if kind not in KINDS:
        raise CorrectionError(f"kind must be one of {KINDS}")
    if not ISO_DAY.match(str(dated_on or "")):
        raise CorrectionError("dated_on must be YYYY-MM-DD")
    return f"{kind.capitalize()}, {day_words(dated_on)} — {PLATFORM_SIGNATURE}"


def persona_names() -> frozenset:
    """Every named persona of the platform: the legacy editor, the narrator, every coach (retired ones too). None of
    them may sign a correction."""
    names = {LEGACY_SIGNER}
    try:
        from content.elena_canon import NAME as narrator

        names.add(narrator)
    except Exception:  # noqa: BLE001 — the narrator's name is also pinned literally below
        pass
    names.add("Elena Voss")
    try:
        from coach.persona_registry import short_id_names

        names.update(short_id_names(include_retired=True).values())
    except Exception:  # noqa: BLE001 — the coach registry is a repo file; the two narrators stay refused regardless
        pass
    return frozenset(n for n in names if isinstance(n, str) and n.strip())


def names_legacy_persona(text: Any) -> bool:
    """True when a rendered text carries a note signed by the legacy persona (so the disclosure must render beside it)."""
    return isinstance(text, str) and LEGACY_SIGNER in text


def _text(value: Any, field: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CorrectionError(f"{field}: a non-empty sentence is required")
    v = " ".join(value.split())
    if len(v) > limit:
        raise CorrectionError(f"{field}: at most {limit} characters")
    if _EDITORS_NOTE.search(v):
        raise CorrectionError(f"{field}: a correction is not an editor's note — the platform signs it, no persona does")
    return v


def _no_persona_signoff(value: str, field: str) -> None:
    """A statement may NAME a coach ("Lisa Park's call…"); it may not be signed by one ("— Margaret Calloway")."""
    for name in persona_names():
        if re.search(rf"(?:[—–-]\s*|^\s*){re.escape(name)}\s*:?\s*$", value) or re.match(rf"^\s*{re.escape(name)}\s*:", value):
            raise CorrectionError(f"{field}: signed by a persona ({name}); a correction carries the platform's signature only")


def new_proposal(
    *,
    chapter_id: str,
    correction_id: str,
    kind: str,
    published_said: str,
    record_shows: str,
    evidence: str,
    proposed_at: str,
    supersedes: Optional[str] = None,
    user_id: str = USER_ID_DEFAULT,
) -> dict:
    """The item a proposal writes — unapproved, unsigned, undated. Raises ``CorrectionError`` on anything malformed."""
    if not CHAPTER_ID.match(str(chapter_id or "")):
        raise CorrectionError("chapter_id must be the chapter's v9 id, week-NN")
    if not CORRECTION_ID.match(str(correction_id or "")):
        raise CorrectionError("correction_id: 3-64 characters, lowercase letters, digits and hyphens")
    if kind not in KINDS:
        raise CorrectionError(f"kind must be one of {KINDS}")
    if supersedes is not None and not CORRECTION_ID.match(str(supersedes)):
        raise CorrectionError("supersedes must name an existing correction_id")
    if supersedes == correction_id:
        raise CorrectionError("a correction cannot supersede itself")
    if not ISO_INSTANT.match(str(proposed_at or "")):
        raise CorrectionError("proposed_at must be an ISO-8601 instant")
    item: dict[str, Any] = {
        "pk": pk(user_id),
        "sk": sk(chapter_id, correction_id),
        "record_type": RECORD_TYPE,
        "phase": "experiment",  # every chronicle reader filters on phase; never leave it unset (#4537)
        "chapter_id": chapter_id,
        "correction_id": correction_id,
        "kind": kind,
        "published_said": _text(published_said, "published_said", MAX_STATEMENT),
        "record_shows": _text(record_shows, "record_shows", MAX_STATEMENT),
        "evidence": _text(evidence, "evidence", MAX_EVIDENCE),
        "supersedes": supersedes,
        "proposed_at": proposed_at,
        "proposed_via": PROPOSED_VIA,
        "approvals": [],
        "approved_at": None,
        "dated_on": None,
        "signature": None,
    }
    for f in ("published_said", "record_shows", "evidence"):
        _no_persona_signoff(item[f], f)
    return item


def approval(*, at: str, dated_on: str, note: str = "") -> dict:
    """The approval entry the owner's approve call appends — who, when, through what."""
    if not ISO_INSTANT.match(str(at or "")):
        raise CorrectionError("approval at must be an ISO-8601 instant")
    if not ISO_DAY.match(str(dated_on or "")):
        raise CorrectionError("dated_on must be YYYY-MM-DD")
    note = " ".join(str(note or "").split())
    if len(note) > MAX_NOTE:
        raise CorrectionError(f"note: at most {MAX_NOTE} characters")
    return {"by": APPROVER, "at": at, "on": dated_on, "via": APPROVED_VIA, "note": note}


def validate(item: Any) -> dict:
    """An approved record, checked whole before it is served. Raises ``CorrectionError``."""
    if not isinstance(item, dict) or item.get("record_type") != RECORD_TYPE:
        raise CorrectionError("not a chapter correction record")
    cid, corr = str(item.get("chapter_id") or ""), str(item.get("correction_id") or "")
    if not CHAPTER_ID.match(cid) or not CORRECTION_ID.match(corr) or item.get("sk") != sk(cid, corr):
        raise CorrectionError("ids do not match the record's key")
    if item.get("kind") not in KINDS:
        raise CorrectionError("unknown kind")
    for f, limit in (("published_said", MAX_STATEMENT), ("record_shows", MAX_STATEMENT), ("evidence", MAX_EVIDENCE)):
        _no_persona_signoff(_text(item.get(f), f, limit), f)
    approvals = item.get("approvals")
    if not isinstance(approvals, list) or not approvals:
        raise CorrectionError("not approved: no approval is recorded on it")
    for a in approvals:
        if not isinstance(a, dict) or a.get("by") != APPROVER or not ISO_INSTANT.match(str(a.get("at") or "")):
            raise CorrectionError("an approval must be the owner's, with its instant")
    dated_on = str(item.get("dated_on") or "")
    if not ISO_DAY.match(dated_on):
        raise CorrectionError("an approved correction carries the day it is dated")
    expected = signature(item["kind"], dated_on)
    if item.get("signature") != expected:
        raise CorrectionError(f"signature must be the platform's ({expected!r}), got {item.get('signature')!r}")
    for name in persona_names():
        if name in str(item.get("signature") or ""):
            raise CorrectionError(f"signed with a persona name ({name})")
    sup = item.get("supersedes")
    if sup is not None and (not CORRECTION_ID.match(str(sup)) or sup == corr):
        raise CorrectionError("supersedes must name another correction")
    return item


def _public(item: dict) -> dict:
    return {
        "id": item["correction_id"],
        "chapter_id": item["chapter_id"],
        "kind": item["kind"],
        "dated_on": item["dated_on"],
        "signature": item["signature"],
        "published_said": " ".join(item["published_said"].split()),
        "record_shows": " ".join(item["record_shows"].split()),
        "evidence": " ".join(item["evidence"].split()),
        "approvals": [
            {"by": a["by"], "on": a.get("on") or str(a["at"])[:10], "via": a.get("via") or APPROVED_VIA} for a in item["approvals"]
        ],
        "supersedes": item.get("supersedes"),
        "superseded_by": None,
    }


def public_view(items: Iterable[Any], log=None) -> list:
    """Every APPROVED correction, as the public may read it, oldest first per chapter. An unapproved or malformed record
    is left out (and logged); an approved record superseded by another APPROVED record of the same chapter stays in the
    list with ``superseded_by`` set — superseded, never removed."""
    approved: list = []
    for it in items or []:
        if not isinstance(it, dict) or not str(it.get("sk") or "").startswith(SK_PREFIX):
            continue
        try:
            approved.append(_public(validate(it)))
        except CorrectionError as exc:
            if it.get("approvals"):  # an approved record that fails the checks is a defect worth a log line
                if log:
                    log(f"[chapter-corrections] {it.get('sk')} withheld: {exc}")
    by_id = {(c["chapter_id"], c["id"]): c for c in approved}
    for c in sorted(approved, key=lambda c: (c["dated_on"], c["id"])):
        if c["supersedes"] and (c["chapter_id"], c["supersedes"]) in by_id:
            by_id[(c["chapter_id"], c["supersedes"])]["superseded_by"] = c["id"]
    return sorted(approved, key=lambda c: (c["chapter_id"], c["dated_on"], c["id"]))


def summary_line(c: dict) -> str:
    """One correction in one plain paragraph — the feed description and any plain-text surface."""
    return f"{c['signature']}. What was published: {c['published_said']} What the record shows: {c['record_shows']}"
