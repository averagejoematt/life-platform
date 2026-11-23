"""content/chapter_editions.py — second editions of published chapters, and the first edition's archival rendering (#6193).

THE RULING (owner, 2026-11-22 §3). "Build the second-edition mechanism once, using existing publication infrastructure."
The canonical chapter URL serves the approved latest edition; the original publication date is preserved and a separate
revision date is shown; an unredacted first edition containing subsequently restricted material is never restored to
public access — the original evidence is kept privately and immutably; a public historical edition, if one is offered, is
a privacy-safe historical rendering at ``/story/<chapter-path>/first-edition/`` with a clear note explaining its archival
status, and the note never describes the number, wording or identity of anything removed; no misleading RSS announcement
and no automatic subscriber resend.

THE SWITCH. ``LIVE`` below, committed ``False``. Off: ``/api/chapters`` never reads these rows and never carries the
``editions`` field (its response is byte-identical to the one before #6193), the snapshot exporter writes no
``chapter_editions.json``, so the v9 build writes no edition line and no ``first-edition`` page. Records can be proposed
and approved while it is off; nothing renders. Rollback = set it back to ``False`` (one line) and rebuild the site: the
canonical page serves the first edition again, from the chronicle row that was never changed.

THE RECORDS. In the chronicle partition beside the chapter, like its corrections (``content.chapter_corrections``), one
sk family ``CHAPTER_EDITION#<chapter_id>#…`` (``chapter_id`` = the v9 id, ``week-NN``):

  ``…#01``                the FIRST EDITION's private evidence pointer (``record_type: chapter_edition_original``),
                          written once by ``scripts/chronicle_edition_backup.py`` after it copied the chronicle row and
                          the chapter's published pages to a private, write-once backup prefix and read the copies back.
                          No text; keys and sha256s only. No edition is approved for a chapter without it.
  ``…#01#restore``        the RESTORE REHEARSAL of that backup (``record_type: chapter_edition_restore_check``), written
                          once by the same script after it read every backup object back, matched each to the sha256 the
                          pointer recorded, and rebuilt the row item exactly from its DynamoDB JSON (owner ruling
                          2026-11-22, rehearsal §6: "Verify the restore path, not merely the presence of backup files").
                          No edition is approved or served without it.
  ``…#NN`` (NN >= 02)     an EDITION (``record_type: chapter_edition``): its full text (the chronicle's markdown),
                          the first-published day, the corrections it carries, the proposal instant — and, once the owner
                          approves it, the approval history, ``revised_on`` and the platform's signature.
  ``…#01#archival#NN``    an ARCHIVAL RENDERING of the first edition (``record_type: chapter_edition_archival``): a
                          SEPARATELY proposed and separately approved text — never derived from the raw original — that
                          passes every publication gate. Off by default per chapter: without an approved one there is no
                          ``first-edition`` page for that chapter. An optional ``as_of`` day says when the text it renders
                          stood (a chapter rewritten after it was first published), so the fixed note never calls a later
                          rewrite "the first edition".
  ``…#anchor#<correction>`` an ANCHOR (``record_type: chapter_edition_anchor``): the owner-approved passage of the
                          archival text an approved correction concerns (its exact opening words). The archival page
                          prints that correction beside the passage instead of only above the text (rehearsal ruling §4:
                          "displayed beside or directly linked to the erroneous passage"). A separate record, so the
                          approved correction and the live corrections API are never changed; served only inside an
                          archival rendering whose text carries the passage exactly once.
  ``<target>#withdrawn``  a WITHDRAWAL (``record_type: chapter_edition_withdrawal``) of one approved edition or one
                          approved archival rendering: the owner's dated act, appended, never inferred. From then on that
                          record — and every earlier one of its kind for the chapter — never serves: the chapter serves its
                          first edition again (or a LATER approved edition), the other chapters are untouched, and a
                          re-approval is a new number.

THE PRESENTATION FIELDS (#6193 B4). An edition's text opens with its title in quotation marks, alone on its line, then
its summary as one italic line, then the body. The hash binds the WHOLE text. When the edition is served, the title line
is the page heading (it must equal the chapter's published title — an edition never retitles a chapter) and the summary
is the chapter's summary on every surface that shows one; neither is repeated in the body. ``verify_page`` proves each
approved word is deployed in its slot.

THE RULES THIS MODULE HOLDS (pure; ``mcp/tools_chapter_corrections.py`` is the only writer of ``…#NN`` and archival rows,
the backup script the only writer of ``…#01``, ``/api/chapters`` the only public reader):
  * ``approved`` is the owner's explicit act through his tool and is never inferred; an unapproved record is never served.
  * Append-only: a record is written once (``attribute_not_exists(sk)``), approved once (``size(approvals) = 0``), its
    text never updated, nothing deleted. A changed edition is a NEW edition number; a changed rendering a new NN.
  * The chronicle row, its journal page and the feed manifest are never touched: the first edition stays where it is, and
    its first-published date stays the date every feed already carries.
  * Every text that can reach a page passes ``gate_findings`` — the content filter, the private-call publication record
    (``web.narrative_publication.is_tainted`` over ``common.prediction_publication``'s withheld calls), the staged-encounter
    and reader-surface truth checks — at proposal, at approval AND at serve. A finding withholds it, fail-closed.
  * The signature and the edition line are the platform's, computed here, never supplied, never a persona's.
"""

from __future__ import annotations

import hashlib
import html
import re
from decimal import Decimal
from typing import Any, Callable, Iterable, Optional

from content import chapter_corrections as CC

#: THE switch (#6193). False = no edition and no archival page renders anywhere; the records may still be written.
# #6193 activation (owner ruling 2026-11-22): ON publishes nothing by itself; an edition is served only once approved by hash.
# ROLLBACK: set back to False and rebuild the site.
LIVE = True

SK_PREFIX = "CHAPTER_EDITION#"
ORIGINAL_TYPE = "chapter_edition_original"
EDITION_TYPE = "chapter_edition"
ARCHIVAL_TYPE = "chapter_edition_archival"
PLATFORM_SIGNATURE = CC.PLATFORM_SIGNATURE
APPROVER = CC.APPROVER
PROPOSED_VIA = CC.PROPOSED_VIA
#: The private prefix the backup script writes the first edition's evidence under (never under site/ or generated/).
BACKUP_ROOT = "backups/chronicle-editions/"
PUBLIC_PREFIXES = ("site/", "generated/")
ORDINALS = {2: "Second", 3: "Third", 4: "Fourth", 5: "Fifth", 6: "Sixth", 7: "Seventh", 8: "Eighth", 9: "Ninth"}
MAX_TEXT = 40000
MIN_TEXT = 40
SHA256 = re.compile(r"^[0-9a-f]{64}$")
CHAPTER_ID = CC.CHAPTER_ID
ISO_DAY = CC.ISO_DAY
ISO_INSTANT = CC.ISO_INSTANT

#: What the public view serves for one chapter's edition — nothing else rides along (no proposal instant, no backup key).
PUBLIC_FIELDS = (
    "chapter_id",
    "edition",
    "title",
    "summary",
    "edition_line",
    "signature",
    "first_published",
    "revised_on",
    "approvals",
    "carries",
    "word_count",
    "text_sha256",
    "text",
    "body_html",
    "archival",
)
PUBLIC_ARCHIVAL_FIELDS = (
    "archival_id",
    "approved_on",
    "as_of",
    "title",
    "note",
    "signature",
    "text_sha256",
    "text",
    "body_html",
    "anchors",
)
ANCHOR_TYPE = "chapter_edition_anchor"
MIN_PASSAGE, MAX_PASSAGE = 12, 400
WITHDRAWAL_TYPE = "chapter_edition_withdrawal"
RESTORE_TYPE = "chapter_edition_restore_check"
WITHDRAWAL_KINDS = ("edition", "archival")

#: The ONLY things the chapter page may add to, or take from, an edition's prose (owner ruling 2026-11-22, final approval
#: §1: "the deployed texts match the approved hashes, except for explicitly permitted presentation metadata"). Every
#: one sits BETWEEN prose blocks or outside the body, never inside a sentence; ``verify_page`` removes exactly these and
#: then requires the page's prose blocks to equal the approved text's, block for block, word for word.
PERMITTED_PRESENTATION = (
    ("data-evidence", "an evidence figure or graded-call card placed between paragraphs (www/src/lib/evidence.js)"),
    ("data-record-as-published", "the dated coach-record note placed between paragraphs (www/src/lib/record_note.js)"),
    ("dek-duplicate", "a first signature line or first paragraph identical to the header dek, printed once in the header"),
    ("signature-class", "the `note` / `filed` class on an emphasised signature line (a class, not a word)"),
    (
        "correction-beside-passage",
        "on the archival page, an approved correction (the platform's signed block, data-correction) placed between paragraphs, "
        "directly after the paragraph that carries the passage its owner-approved anchor names",
    ),
    (
        "title-line",
        "the text's first line, the chapter's title in quotation marks, printed once as the page heading (h1) — never in the "
        "body; it must equal the chapter's published title (an edition never retitles a chapter)",
    ),
    (
        "edition-summary",
        "an edition's italic summary line (the block after its title line), printed once as the chapter's summary in the "
        "header — never in the body — and the same words wherever the chapter's summary is shown (the story index, Moments, "
        "the description and og metadata, the feed's item description; never a feed guid, date or new item)",
    ),
)
#: Outside the body, and so never compared: the edition line, the dates, the addresses, the corrections beside the text,
#: the approval metadata, the byline, the header and the walk.


class EditionError(ValueError):
    """A record that may not be written or served, with the reason."""


# ── keys ─────────────────────────────────────────────────────────────────────────────────────


def pk(user_id: str = CC.USER_ID_DEFAULT) -> str:
    return CC.pk(user_id)


def sk_original(chapter_id: str) -> str:
    return f"{SK_PREFIX}{chapter_id}#01"


def sk_restore(chapter_id: str) -> str:
    return f"{SK_PREFIX}{chapter_id}#01#restore"


def sk_edition(chapter_id: str, edition: int) -> str:
    return f"{SK_PREFIX}{chapter_id}#{int(edition):02d}"


def sk_archival(chapter_id: str, archival_id: int) -> str:
    return f"{SK_PREFIX}{chapter_id}#01#archival#{int(archival_id):02d}"


# ── words ────────────────────────────────────────────────────────────────────────────────────


def ordinal(edition: Any) -> str:
    if not isinstance(edition, int) or isinstance(edition, bool) or edition not in ORDINALS:
        raise EditionError(f"edition must be a whole number from 2 to {max(ORDINALS)} (the first edition is the published chapter)")
    return ORDINALS[edition]


def edition_line(edition: int, revised_on: str, first_published: str) -> str:
    """ "Second edition, revised 23 November 2026. First published 11 September 2026." — the line the chapter page prints."""
    return f"{ordinal(edition)} edition, revised {CC.day_words(revised_on)}. First published {CC.day_words(first_published)}."


def signature(edition: int, revised_on: str) -> str:
    """ "Second edition, revised 23 November 2026 — Average Joe Matt editorial record": the platform's, never a persona's."""
    return f"{ordinal(edition)} edition, revised {CC.day_words(revised_on)} — {PLATFORM_SIGNATURE}"


def archival_signature(approved_on: str) -> str:
    return f"Archival rendering, approved {CC.day_words(approved_on)} — {PLATFORM_SIGNATURE}"


#: The archival page's label and its short note — the owner's exact words (owner ruling 2026-11-22, final chronicle
#: publication §5); www/src/lib/chapter_editions.js ARCHIVAL_LABEL is pinned equal. The note says that limited removals
#: exist and never what was removed or how much.
ARCHIVAL_LABEL = "Historical edition — privacy-safe rendering"
ARCHIVAL_NOTE = (
    "This page preserves the historical edition with limited removals for privacy or source verification. "
    "The original version is retained privately."
)


def archival_dates(first_published: str, revised_on: str, as_of: Optional[str] = None) -> str:
    """The archival page's date line, from recorded dates only ("Keep the true historical date and edition identity"): the
    first edition and its first-publication day — or (``as_of``) the text as it stood on a later day — and the edition
    that superseded it."""
    if as_of:
        return (
            f"The text of this chapter as it stood on {CC.day_words(as_of)}; the chapter was first published "
            f"{CC.day_words(first_published)}. Superseded by the edition of {CC.day_words(revised_on)}."
        )
    return f"The first edition, first published {CC.day_words(first_published)}. Superseded by the edition of {CC.day_words(revised_on)}."


def archival_note(first_published: str, revised_on: str, as_of: Optional[str] = None) -> str:
    """The archival page's one fixed note: the owner's words, then the recorded dates (``archival_dates``). No proposal
    can carry a description of a removed passage onto the page — the note takes no free text from any record."""
    return f"{ARCHIVAL_NOTE} {archival_dates(first_published, revised_on, as_of)}"


def archive_path(chapter_id: str) -> str:
    """The archival rendering's address (owner ruling 2026-11-22 §3)."""
    return f"/story/{chapter_id}/first-edition/"


def references_archive(text: Any, chapter_id: str) -> bool:
    """#6193 B9: the text points a reader at the chapter's first-edition address (an approved edition note does)."""
    return bool(re.search(rf"/story/{re.escape(str(chapter_id))}/first-edition\b", str(text or "")))


# ── the presentation fields (#6193 B4) ───────────────────────────────────────────────────────

_HEAD = re.compile(r'\A["“](?P<title>[^"“”\n]{1,200})["”][ \t]*(?:\n[ \t]*){2,}')
_SUMMARY = re.compile(r"\A\*(?!\*)(?P<summary>[^*\n]{20,1200})\*[ \t]*(?:\n[ \t]*){2,}")


def title_key(title: Any) -> str:
    """A title as compared: curly quotes and apostrophes read straight, spaces collapsed."""
    t = str(title or "").replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    return " ".join(t.split())


def presentation(text: Any, *, edition: bool = True) -> dict:
    """``{"title", "summary", "body"}`` of a stored text: the title line (its words, unquoted), the summary line (its words,
    without the emphasis) and the body that follows them — the text itself is never changed, and the hash stays on all of
    it. An EDITION must open with both (``EditionError`` otherwise); an archival rendering may open with a title line and
    carries no summary of its own."""
    t = str(text or "").replace("\r\n", "\n").strip()
    title = summary = None
    m = _HEAD.match(t + "\n\n")
    if m:
        title = m.group("title").strip()
        t = t[m.end() :] if m.end() <= len(t) else ""
    if edition:
        s = _SUMMARY.match(t + "\n\n")
        if title is None or s is None:
            raise EditionError(
                'text: an edition opens with its title line ("<the chapter\'s title>" in quotation marks, alone on the line), '
                "then a blank line, then its summary as one italic line (*…*, 20 to 1,200 characters), then the body"
            )
        summary = " ".join(s.group("summary").split())
        t = t[s.end() :] if s.end() <= len(t) else ""
    body = t.strip()
    if len(body) < MIN_TEXT:
        raise EditionError(f"text: the body after the title and summary lines is required (at least {MIN_TEXT} characters)")
    if edition and compose_text(title, summary, body) != str(text or "").replace("\r\n", "\n").strip():
        raise EditionError(
            "text: an edition's head must be exactly '\"<title>\"', one blank line, '*<summary>*', one blank line, then the body "
            "(straight quotation marks, single spaces in the summary) — so the approved bytes can be rebuilt from the page"
        )
    return {"title": title, "summary": summary, "body": body}


def compose_text(title: Optional[str], summary: Optional[str], body: str) -> str:
    """THE deterministic inverse of ``presentation`` for an edition (owner ruling 2026-11-22, rehearsal §2: "Document the
    deterministic transformation and verify the resulting published content"): the approved text is EXACTLY
    ``"<title>"`` + blank line + ``*<summary>*`` + blank line + body. ``presentation`` refuses an edition whose text is not
    in this form, so ``compose_text(**presentation(t)) == t`` for every edition that can be stored, and the verifier
    rebuilds the approved bytes from the deployed heading, header summary and body and checks their SHA-256."""
    head = (f'"{title}"\n\n' if title is not None else "") + (f"*{summary}*\n\n" if summary is not None else "")
    return head + body


def title_problem(text: Any, published_title: Optional[str]) -> Optional[str]:
    """Why an edition may not be served under ``published_title`` — or None. An edition never retitles a chapter: its
    title line must equal the chapter's published title (curly and straight quotes alike)."""
    try:
        p = presentation(text)
    except EditionError as exc:
        return str(exc)
    if not published_title:
        return "the chapter's published title could not be read, so the title line cannot be checked"
    if " ".join(p["title"].split()) != " ".join(str(published_title).split()):
        return (
            f"the edition's title line {p['title']!r} is not the chapter's published title {published_title!r}, character for "
            "character; an edition cannot retitle a chapter — propose it with the published title as its first line"
        )
    return None


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def render_html(text: str) -> str:
    """The chronicle's own markdown renderer (``content.chronicle_markdown.markdown_to_html``, re-exported by ``emails.chronicle_render`` — the one the journal page and
    the mailed copy use), over the text with ``&`` and ``<`` escaped, so a stored edition can never inject markup."""
    from content.chronicle_markdown import markdown_to_html  # noqa: PLC0415 — the ONE copy chronicle_render re-exports

    return markdown_to_html(str(text).replace("&", "&amp;").replace("<", "&lt;"))


def word_count(text: str) -> int:
    return len(re.sub(r"[*>#_]", " ", str(text or "")).split())


# ── the gates ────────────────────────────────────────────────────────────────────────────────

#: #6199: a rendering-only or synthetic-fixture caller of the gates — there is no call record to check against.
PRIVATE_CALLS_NOT_WIRED: Any = object()


def gate_findings(
    text: Any, *, tainted: Optional[Callable[[str], bool]], private_calls: Any, filter_hits: Optional[Callable[[str], list]] = None
) -> list:
    """Every reason ``text`` may not reach a public page; ``[]`` = it may. Fail-closed on every unreadable input.

    * content filter — ``privacy.privacy_guard.find_violations`` (the chronicle's own publish gate; its vocabulary is
      off-repo and is never echoed here; the CALLER passes it as ``filter_hits`` — the Site API and the MCP tool pass the real one, only the build's
      synthetic fixture passes none-found — so this module never reaches the off-repo channel's AWS read itself);
    * private calls — ``tainted`` is ``web.narrative_publication.is_tainted`` (a SHINGLE-word run of a call the
      publication record withholds, ``common.prediction_publication``); ``None`` means no record could be opened;
    * truth — ``content.story_checks``: a staged encounter no source holds, a cycle/attempt count, off-record
      specifics, a cut reader-vocabulary term;
    * #6199 — ``content.private_call_check.findings``, THE publish-time check for a call or ask the publication policy
      classifies private (echo, id, described), injected like the two above so this module never reaches AWS:
      ``private_calls`` is required — ``lambda t: private_call_check.findings(t, calls)`` over the calls read at run time
      (``private_call_check.for_text``), None when they could not be read (refused, fail closed), or
      ``PRIVATE_CALLS_NOT_WIRED`` for a rendering-only or synthetic-fixture caller, each registered in
      tests/test_chapter_reads_withdrawn_6199.py. ``tainted`` above is a different policy (the narrative record's
      verbatim taint) and stays beside it.
    """
    from content import story_checks  # noqa: PLC0415

    if not isinstance(text, str) or not text.strip():
        return ["empty: no text"]
    out: list = []
    for f in story_checks.staged_encounter_findings(text):
        out.append(f"truth: {f}")
    for f in story_checks.reader_surface(text):
        out.append(f"truth: {f}")
    try:
        if filter_hits is None:  # the caller passes privacy_guard.find_violations; none given = nothing unchecked
            raise LookupError("no content-filter vocabulary was given")
        hits = filter_hits(text)
    except Exception as exc:  # noqa: BLE001 — no vocabulary = no publication (fail closed)
        out.append(f"content-filter: unavailable ({type(exc).__name__}) — nothing is published unchecked")
    else:
        kinds = sorted({k for k, _t in hits})
        if kinds:
            out.append(f"content-filter: {len(hits)} blocked term(s) of kind {', '.join(kinds)}")
    if tainted is None:
        out.append("private-call: the publication record could not be opened — nothing is published unchecked")
    else:
        try:
            if tainted(text) or any(tainted(p) for p in re.split(r"\n\s*\n", text) if p.strip()):
                out.append("private-call: the text carries the words of a call that is not public")
        except Exception as exc:  # noqa: BLE001
            out.append(f"private-call: the publication record could not be read ({type(exc).__name__}) — nothing is published unchecked")
    if private_calls is None:
        out.append("private call: the check could not read the calls the publication policy classifies, so nothing publishes")
    elif private_calls is not PRIVATE_CALLS_NOT_WIRED:
        try:
            out += list(private_calls(text))
        except Exception as exc:  # noqa: BLE001
            out.append(f"private call: the check could not run ({type(exc).__name__}) — nothing is published unchecked")
    return out


# ── the records ──────────────────────────────────────────────────────────────────────────────


def _text(value: Any) -> str:
    if not isinstance(value, str) or len(value.strip()) < MIN_TEXT:
        raise EditionError(f"text: the full chapter text is required (at least {MIN_TEXT} characters)")
    v = value.replace("\r\n", "\n").strip()
    if len(v) > MAX_TEXT:
        raise EditionError(f"text: at most {MAX_TEXT} characters")
    return v


def _int(value: Any) -> Optional[int]:
    """A whole number as stored (an int, or the Decimal DynamoDB reads it back as); anything else is None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    try:
        if isinstance(value, (float, Decimal)) and value == int(value):
            return int(value)
    except (ValueError, OverflowError, ArithmeticError):
        return None
    return None


def _chapter(chapter_id: Any) -> str:
    if not CHAPTER_ID.match(str(chapter_id or "")):
        raise EditionError("chapter_id must be the chapter's v9 id, week-NN")
    return str(chapter_id)


def _base(chapter_id: str, sk: str, record_type: str, user_id: str) -> dict:
    return {"pk": pk(user_id), "sk": sk, "record_type": record_type, "phase": "experiment", "chapter_id": chapter_id}


def new_edition(
    *,
    chapter_id: str,
    edition: int,
    text: str,
    first_published: str,
    proposed_at: str,
    carries: Iterable[str] = (),
    user_id: str = CC.USER_ID_DEFAULT,
) -> dict:
    """The item a proposal writes — unapproved, unsigned, no revision date. Raises ``EditionError``."""
    chapter_id = _chapter(chapter_id)
    ordinal(edition)
    if not ISO_DAY.match(str(first_published or "")):
        raise EditionError("first_published must be the chapter's original publication day, YYYY-MM-DD")
    if not ISO_INSTANT.match(str(proposed_at or "")):
        raise EditionError("proposed_at must be an ISO-8601 instant")
    carried = [str(c).strip() for c in (carries or [])]
    if any(not CC.CORRECTION_ID.match(c) for c in carried) or len(set(carried)) != len(carried):
        raise EditionError("carries: distinct correction ids of this chapter")
    body = _text(text)
    presentation(body)  # #6193 B4: the title line and the summary line open it, or it is refused
    item = _base(chapter_id, sk_edition(chapter_id, edition), EDITION_TYPE, user_id)
    item.update(
        edition=edition,
        text=body,
        text_sha256=text_sha256(body),
        first_published=str(first_published),
        carries=carried,
        proposed_at=proposed_at,
        proposed_via=PROPOSED_VIA,
        approvals=[],
        approved_at=None,
        revised_on=None,
        signature=None,
    )
    return item


def new_archival(
    *,
    chapter_id: str,
    archival_id: int,
    text: str,
    proposed_at: str,
    as_of: Optional[str] = None,
    user_id: str = CC.USER_ID_DEFAULT,
) -> dict:
    """An archival rendering of the first edition, unapproved. Its words are the proposal's — never read off the original.
    ``as_of``: the day the text it renders stood, when that is not the first edition (a later rewrite); None = the first edition."""
    chapter_id = _chapter(chapter_id)
    if not isinstance(archival_id, int) or isinstance(archival_id, bool) or not 1 <= archival_id <= 99:
        raise EditionError("archival_id must be a whole number from 1 to 99")
    if not ISO_INSTANT.match(str(proposed_at or "")):
        raise EditionError("proposed_at must be an ISO-8601 instant")
    if as_of is not None and not ISO_DAY.match(str(as_of)):
        raise EditionError("as_of must be the day the rendered text stood, YYYY-MM-DD (or omitted for the first edition)")
    body = _text(text)
    presentation(body, edition=False)
    item = _base(chapter_id, sk_archival(chapter_id, archival_id), ARCHIVAL_TYPE, user_id)
    item.update(
        as_of=as_of,
        archival_id=archival_id,
        text=body,
        text_sha256=text_sha256(body),
        proposed_at=proposed_at,
        proposed_via=PROPOSED_VIA,
        approvals=[],
        approved_at=None,
        approved_on=None,
    )
    return item


def original_record(
    *, chapter_id: str, row_sk: str, backup_prefix: str, objects: list, backed_up_at: str, user_id: str = CC.USER_ID_DEFAULT
) -> dict:
    """The first edition's private evidence pointer (``…#01``): where the write-once copies are, and their sha256s."""
    chapter_id = _chapter(chapter_id)
    if not str(row_sk or "").startswith("DATE#"):
        raise EditionError("row_sk must be the chronicle row's DATE# key")
    bp = str(backup_prefix or "")
    if not bp.startswith(BACKUP_ROOT) or not bp.endswith("/") or bp.startswith(PUBLIC_PREFIXES):
        raise EditionError(f"backup_prefix must be a private prefix under {BACKUP_ROOT}")
    if not ISO_INSTANT.match(str(backed_up_at or "")):
        raise EditionError("backed_up_at must be an ISO-8601 instant")
    clean = []
    for o in objects or []:
        if not isinstance(o, dict) or not str(o.get("backup_key") or "").startswith(bp) or not SHA256.match(str(o.get("sha256") or "")):
            raise EditionError("every backed-up object names its key under the prefix and its sha256")
        clean.append({"source": str(o.get("source") or ""), "backup_key": o["backup_key"], "sha256": o["sha256"]})
    if not any(o["source"].startswith("ddb:") for o in clean):
        raise EditionError("the chronicle row itself must be among the backed-up objects")
    item = _base(chapter_id, sk_original(chapter_id), ORIGINAL_TYPE, user_id)
    item.update(edition=1, row_sk=row_sk, backup_prefix=bp, objects=clean, backed_up_at=backed_up_at)
    return item


def restore_record(*, original: dict, verified_at: str, user_id: str = CC.USER_ID_DEFAULT) -> dict:
    """The restore rehearsal's record: every object of ``original`` (the ``…#01`` pointer) read back equal and the row
    rebuilt exactly. The script writes it only after all of that passed — it is the record that it passed."""
    o = validate_original(original)
    if not ISO_INSTANT.match(str(verified_at or "")) or str(verified_at) < str(o["backed_up_at"]):
        raise EditionError("verified_at must be an instant at or after the backup")
    item = _base(o["chapter_id"], sk_restore(o["chapter_id"]), RESTORE_TYPE, user_id)
    item.update(
        backup_prefix=o["backup_prefix"],
        objects=[{"backup_key": x["backup_key"], "sha256": x["sha256"]} for x in o["objects"]],
        row_rebuilt=True,
        verified_at=verified_at,
    )
    return item


def validate_restore(item: Any, original: dict) -> dict:
    """The restore record matches THIS backup, object for object, and says the row was rebuilt. Raises ``EditionError``."""
    if not isinstance(item, dict) or item.get("record_type") != RESTORE_TYPE:
        raise EditionError("no restore rehearsal is recorded for the first edition's backup")
    want = sorted((x["backup_key"], x["sha256"]) for x in original.get("objects") or [])
    got = sorted((str(x.get("backup_key")), str(x.get("sha256"))) for x in item.get("objects") or [] if isinstance(x, dict))
    if item.get("sk") != sk_restore(original["chapter_id"]) or item.get("backup_prefix") != original.get("backup_prefix") or got != want:
        raise EditionError("the restore rehearsal is not of this backup")
    if item.get("row_rebuilt") is not True or str(item.get("verified_at") or "") < str(original.get("backed_up_at") or ""):
        raise EditionError("the restore rehearsal did not rebuild the row after the backup")
    return item


def approval(*, at: str, dated_on: str, sha256: str, note: str = "") -> dict:
    """The approval entry the owner's approve call appends (the corrections' shape: who, when, through what) — bound to
    the SHA-256 of the exact text he approved (final approval §1)."""
    if not SHA256.match(str(sha256 or "")):
        raise EditionError("an approval names the SHA-256 of the exact text approved")
    return {**CC.approval(at=at, dated_on=dated_on, note=note), "sha256": sha256}


def _approved(item: dict) -> list:
    approvals = item.get("approvals")
    if not isinstance(approvals, list) or not approvals:
        raise EditionError("not approved: no approval is recorded on it")
    for a in approvals:
        if not isinstance(a, dict) or a.get("by") != APPROVER or not ISO_INSTANT.match(str(a.get("at") or "")):
            raise EditionError("an approval must be the owner's, with its instant")
        if a.get("sha256") != item.get("text_sha256"):
            raise EditionError("the approval is bound to a different text (its SHA-256 is not this record's)")
    return approvals


def validate_original(item: Any) -> dict:
    if not isinstance(item, dict) or item.get("record_type") != ORIGINAL_TYPE:
        raise EditionError("not a first-edition evidence record")
    original_record(
        chapter_id=item.get("chapter_id"),
        row_sk=item.get("row_sk"),
        backup_prefix=item.get("backup_prefix"),
        objects=item.get("objects"),
        backed_up_at=item.get("backed_up_at"),
    )
    if item.get("sk") != sk_original(item["chapter_id"]):
        raise EditionError("ids do not match the record's key")
    return item


def validate_edition(item: Any) -> dict:
    """An approved edition, checked whole before it is served (the gates are run separately). Raises ``EditionError``."""
    if not isinstance(item, dict) or item.get("record_type") != EDITION_TYPE:
        raise EditionError("not a chapter edition record")
    cid = _chapter(item.get("chapter_id"))
    edition = _int(item.get("edition"))  # DynamoDB reads a number back as a Decimal
    ordinal(edition)
    if item.get("sk") != sk_edition(cid, edition):
        raise EditionError("ids do not match the record's key")
    body = _text(item.get("text"))
    if item.get("text_sha256") != text_sha256(body):
        raise EditionError("the text does not match the sha256 recorded at proposal")
    presentation(body)
    if not ISO_DAY.match(str(item.get("first_published") or "")):
        raise EditionError("no first-published day")
    _approved(item)
    revised = str(item.get("revised_on") or "")
    if not ISO_DAY.match(revised):
        raise EditionError("an approved edition carries the day it was revised")
    if revised < str(item["first_published"]):
        raise EditionError("revised before it was first published")
    if item.get("signature") != signature(edition, revised):
        raise EditionError(f"signature must be the platform's ({signature(edition, revised)!r})")
    for name in CC.persona_names():
        if name in str(item.get("signature")):
            raise EditionError(f"signed with a persona name ({name})")
    return {**item, "edition": edition}


def validate_archival(item: Any) -> dict:
    if not isinstance(item, dict) or item.get("record_type") != ARCHIVAL_TYPE:
        raise EditionError("not an archival rendering record")
    cid = _chapter(item.get("chapter_id"))
    n = _int(item.get("archival_id")) or 0
    if item.get("sk") != sk_archival(cid, n):
        raise EditionError("ids do not match the record's key")
    body = _text(item.get("text"))
    if item.get("text_sha256") != text_sha256(body):
        raise EditionError("the text does not match the sha256 recorded at proposal")
    presentation(body, edition=False)
    _approved(item)
    if not ISO_DAY.match(str(item.get("approved_on") or "")):
        raise EditionError("an approved rendering carries the day it was approved")
    if item.get("as_of") is not None and not ISO_DAY.match(str(item.get("as_of"))):
        raise EditionError("as_of must be a day, YYYY-MM-DD")
    return {**item, "archival_id": n}


# ── withdrawal (#6193 B7): one approved edition or rendering, by the owner's dated act ───────────


def sk_withdrawal(chapter_id: str, kind: str, number: int) -> str:
    target = sk_edition(chapter_id, number) if kind == "edition" else sk_archival(chapter_id, number)
    return f"{target}#withdrawn"


def new_withdrawal(
    *, chapter_id: str, kind: str, number: Any, at: str, dated_on: str, note: str = "", user_id: str = CC.USER_ID_DEFAULT
) -> dict:
    """The record the owner's withdraw call appends: written once, dated, his — never inferred. Raises ``EditionError``."""
    chapter_id = _chapter(chapter_id)
    if kind not in WITHDRAWAL_KINDS:
        raise EditionError(f"kind must be one of {WITHDRAWAL_KINDS}")
    n = _int(number)
    if kind == "edition":
        ordinal(n)
    elif n is None or not 1 <= n <= 99:
        raise EditionError("archival_id must be a whole number from 1 to 99")
    try:
        entry = CC.approval(at=at, dated_on=dated_on, note=note)
    except CC.CorrectionError as exc:
        raise EditionError(str(exc)) from exc
    item = _base(chapter_id, sk_withdrawal(chapter_id, kind, n), WITHDRAWAL_TYPE, user_id)
    item.update(kind=kind, number=n, withdrawn_at=at, withdrawn_on=dated_on, approvals=[entry])
    return item


def validate_withdrawal(item: Any) -> dict:
    if not isinstance(item, dict) or item.get("record_type") != WITHDRAWAL_TYPE:
        raise EditionError("not a withdrawal record")
    cid, kind, n = _chapter(item.get("chapter_id")), item.get("kind"), _int(item.get("number"))
    if kind not in WITHDRAWAL_KINDS or n is None or item.get("sk") != sk_withdrawal(cid, kind, n):
        raise EditionError("ids do not match the record's key")
    a = item.get("approvals")
    if not isinstance(a, list) or not a or any(not isinstance(x, dict) or x.get("by") != APPROVER for x in a):
        raise EditionError("a withdrawal is the owner's act, with his entry")
    if not ISO_DAY.match(str(item.get("withdrawn_on") or "")):
        raise EditionError("a withdrawal carries its day")
    return {**item, "number": n}


def withdrawals(items: Iterable[Any], log=None) -> dict:
    """``{(kind, chapter_id): (highest number withdrawn, its day)}`` from the valid withdrawal records."""
    out: dict = {}
    for it in items or []:
        if not isinstance(it, dict) or it.get("record_type") != WITHDRAWAL_TYPE:
            continue
        try:
            w = validate_withdrawal(it)
        except (EditionError, KeyError, TypeError, ValueError) as exc:
            (log or (lambda _m: None))(f"[chapter-editions] {it.get('sk')} ignored: {exc}")
            continue
        key = (w["kind"], w["chapter_id"])
        if w["number"] > out.get(key, (0, ""))[0]:
            out[key] = (w["number"], w["withdrawn_on"])
    return out


def public_withdrawals(items: Iterable[Any]) -> list:
    """What the public may know of a withdrawal: the chapter, what was withdrawn and the day. Never the note."""
    return [
        {"chapter_id": cid, "kind": kind, "number": n, "withdrawn_on": day}
        for (kind, cid), (n, day) in sorted(withdrawals(items).items(), key=lambda kv: (kv[0][1], kv[0][0]))
    ]


def _public_approvals(item: dict) -> list:
    return [{"by": a["by"], "on": a.get("on") or str(a["at"])[:10], "via": a.get("via") or CC.APPROVED_VIA} for a in item["approvals"]]


# ── anchors (rehearsal ruling §4): a correction beside the passage it concerns ────────────────


def sk_anchor(chapter_id: str, correction_id: str) -> str:
    return f"{SK_PREFIX}{chapter_id}#anchor#{correction_id}"


def _passage(value: Any) -> str:
    v = " ".join(str(value or "").split())
    if not MIN_PASSAGE <= len(v) <= MAX_PASSAGE or "<" in v:
        raise EditionError(f"passage: the exact opening words of the passage, {MIN_PASSAGE} to {MAX_PASSAGE} characters, no markup")
    return v


def new_anchor(*, chapter_id: str, correction_id: str, passage: str, proposed_at: str, user_id: str = CC.USER_ID_DEFAULT) -> dict:
    """An anchor, unapproved: which passage of the chapter's archival text an approved correction concerns."""
    chapter_id = _chapter(chapter_id)
    if not CC.CORRECTION_ID.match(str(correction_id or "")):
        raise EditionError("correction_id must be an approved correction's id")
    if not ISO_INSTANT.match(str(proposed_at or "")):
        raise EditionError("proposed_at must be an ISO-8601 instant")
    item = _base(chapter_id, sk_anchor(chapter_id, correction_id), ANCHOR_TYPE, user_id)
    item.update(correction_id=correction_id, passage=_passage(passage), proposed_at=proposed_at, proposed_via=PROPOSED_VIA, approvals=[])
    return item


def validate_anchor(item: Any) -> dict:
    if not isinstance(item, dict) or item.get("record_type") != ANCHOR_TYPE:
        raise EditionError("not an anchor record")
    cid = _chapter(item.get("chapter_id"))
    if item.get("sk") != sk_anchor(cid, str(item.get("correction_id"))):
        raise EditionError("ids do not match the record's key")
    _passage(item.get("passage"))
    a = item.get("approvals")
    if not isinstance(a, list) or not a or any(not isinstance(x, dict) or x.get("by") != APPROVER for x in a):
        raise EditionError("not approved: an anchor is placed only on the owner's approval")
    return item


def _words(text: str) -> str:
    t = str(text or "").replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    return " ".join(t.split())


def placed_anchors(anchors: Iterable[dict], body_text: str) -> list:
    """The anchors whose passage the rendered archival body carries EXACTLY once (a missing or repeated passage could
    put a correction beside the wrong words: it is left at the top of the page instead)."""
    plain = _words(plain_text(render_html(body_text)))
    out = []
    for a in sorted(anchors, key=lambda a: str(a.get("correction_id"))):
        if plain.count(_words(a["passage"])) == 1:
            out.append({"correction_id": a["correction_id"], "passage": " ".join(str(a["passage"]).split())})
    return out


def _archival_out(a: dict, served: dict, anchors: Iterable[dict] = ()) -> dict:
    p = presentation(a["text"], edition=False)
    return {
        "archival_id": a["archival_id"],
        "approved_on": a["approved_on"],
        "as_of": a.get("as_of"),
        "title": p["title"],
        "note": archival_note(served["first_published"], served["revised_on"], a.get("as_of")),
        "signature": archival_signature(a["approved_on"]),
        "text_sha256": a["text_sha256"],
        "text": a["text"],
        "body_html": render_html(p["body"]),
        "anchors": placed_anchors(anchors, p["body"]),
    }


def _edition_out(served: dict, archival: Optional[dict], anchors: Iterable[dict] = ()) -> dict:
    p = presentation(served["text"])
    return {
        "chapter_id": served["chapter_id"],
        "edition": served["edition"],
        "title": p["title"],
        "summary": p["summary"],
        "edition_line": edition_line(served["edition"], served["revised_on"], served["first_published"]),
        "signature": served["signature"],
        "first_published": served["first_published"],
        "revised_on": served["revised_on"],
        "approvals": _public_approvals(served),
        "carries": list(served.get("carries") or []),
        "word_count": word_count(served["text"]),
        "text_sha256": served["text_sha256"],
        "text": served["text"],
        "body_html": render_html(p["body"]),
        "archival": None if archival is None else _archival_out(archival, served, anchors),
    }


def _sorted_records(items: Iterable[Any], say: Callable[[str], None]) -> tuple:
    originals: dict = {}
    editions: dict = {}
    archivals: dict = {}
    restores: dict = {}
    anchors: dict = {}
    for it in items or []:
        if not isinstance(it, dict) or not str(it.get("sk") or "").startswith(SK_PREFIX):
            continue
        kind = it.get("record_type")
        try:
            if kind == RESTORE_TYPE:
                restores[it.get("chapter_id")] = it
            elif kind == ORIGINAL_TYPE:
                originals[it["chapter_id"]] = validate_original(it)
            elif kind == EDITION_TYPE and it.get("approvals"):
                e = validate_edition(it)
                editions.setdefault(e["chapter_id"], []).append(e)
            elif kind == ARCHIVAL_TYPE and it.get("approvals"):
                a = validate_archival(it)
                archivals.setdefault(a["chapter_id"], []).append(a)
            elif kind == ANCHOR_TYPE and it.get("approvals"):
                x = validate_anchor(it)
                anchors.setdefault(x["chapter_id"], []).append(x)
        except (EditionError, KeyError, TypeError, ValueError) as exc:
            say(f"[chapter-editions] {it.get('sk')} withheld: {exc}")
    for cid, original in list(originals.items()):
        try:
            originals[cid] = {**original, "_restore_verified_at": validate_restore(restores.get(cid), original)["verified_at"]}
        except (EditionError, KeyError, TypeError) as exc:
            say(f"[chapter-editions] {cid}: {exc} — every edition withheld")
            del originals[cid]
    return originals, editions, archivals, anchors


def public_view(
    items: Iterable[Any],
    *,
    tainted: Optional[Callable[[str], bool]],
    private_calls: Any,
    filter_hits: Optional[Callable[[str], list]] = None,
    log=None,
) -> list:
    """Per chapter, the LATEST approved edition that passes every gate — with its approved archival rendering, if one
    passes too — as the public may read it. Withheld (and logged), fail-closed: an unapproved or malformed record; an
    edition whose chapter has no first-edition evidence record, or whose evidence was recorded after its approval; an
    edition or rendering that any gate refuses; a rendering for a chapter with no served edition. #6193 B7: a WITHDRAWN
    edition or rendering never serves, nor does any earlier one of its kind for that chapter (withdrawing a successor never
    revives what it replaced). B9: an edition whose text points at its first-edition address is held while no archival
    rendering of that chapter is served (the address would be a dead link); a rendering whose ``as_of`` is not between the
    chapter's first publication and the edition's revision is held."""
    say = log or (lambda _m: None)
    item_list = list(items or [])
    originals, editions, archivals, anchors = _sorted_records(item_list, say)
    gone = withdrawals(item_list, say)
    gate = lambda t: gate_findings(t, tainted=tainted, private_calls=private_calls, filter_hits=filter_hits)  # noqa: E731
    out = []
    for cid in sorted(editions):
        original = originals.get(cid)
        if original is None:
            say(f"[chapter-editions] {cid}: no first-edition evidence record with a passed restore rehearsal — every edition withheld")
            continue
        floor_a = gone.get(("archival", cid), (0, ""))[0]
        renderings = []
        for a in sorted(archivals.get(cid, []), key=lambda a: a["archival_id"], reverse=True):
            if a["archival_id"] <= floor_a:
                say(f"[chapter-editions] {a['sk']} withheld: withdrawn by the owner")
            elif gate(a["text"]):
                say(f"[chapter-editions] {a['sk']} withheld by the publication gates")
            else:
                renderings.append(a)
        floor_e = gone.get(("edition", cid), (0, ""))[0]
        for e in sorted(editions[cid], key=lambda e: e["edition"], reverse=True):
            if e["edition"] <= floor_e:
                say(f"[chapter-editions] {e['sk']} withheld: withdrawn by the owner (the chapter serves its first edition)")
                continue
            if max(str(original["backed_up_at"]), str(original["_restore_verified_at"])) > str(e.get("approved_at") or ""):
                say(f"[chapter-editions] {e['sk']} withheld: approved before the first edition was backed up and its restore rehearsed")
                continue
            findings = gate(e["text"])
            if findings:
                say(f"[chapter-editions] {e['sk']} withheld by the publication gates: {len(findings)} finding(s)")
                continue
            fits = [a for a in renderings if not a.get("as_of") or e["first_published"] <= str(a["as_of"]) <= e["revised_on"]]
            if len(fits) < len(renderings):
                say(f"[chapter-editions] {cid}: an archival rendering's as_of is outside the first publication and this revision — held")
            if not fits and references_archive(e["text"], cid):
                say(f"[chapter-editions] {e['sk']} held: its text points at {archive_path(cid)} and no archival rendering is served")
                continue
            out.append(_edition_out(e, fits[0] if fits else None, anchors.get(cid, [])))
            break
    return out


def plain_text(body_html: str) -> str:
    """A served body's words, for the snapshot's re-check (tags dropped, entities read)."""
    return html.unescape(re.sub(r"<[^>]+>", " ", str(body_html or "")))


# ── verification of a deployed page against the approved bytes (final approval §1) ──────────────


def _norm(text: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", str(text or ""))).split())


def prose_blocks(body_html: str) -> list:
    """The prose of a rendered body, block by block (each ``<p>`` / ``<blockquote>``), words normalised. A block inside a
    permitted presentation element (``data-evidence``, ``data-record-as-published``) is not prose and is dropped."""
    h = str(body_html or "")
    for marker in ("data-evidence", "data-record-as-published", "data-correction"):
        while True:
            m = re.search(r"<(figure|aside|p)\b[^>]*\b" + marker + r"\b[^>]*>", h)
            if not m:
                break
            tag = m.group(1)
            depth, i = 0, m.start()
            for t in re.finditer(r"<(/?)" + tag + r"\b[^>]*>", h[m.start() :]):
                depth += -1 if t.group(1) else 1
                if depth == 0:
                    i = m.start() + t.end()
                    break
            else:
                i = len(h)
            h = h[: m.start()] + h[i:]
    return [b for b in (_norm(x) for x in re.findall(r"<(?:p|blockquote)\b[^>]*>([\s\S]*?)</(?:p|blockquote)>", h)) if b]


def _published_body(page_html: str) -> Optional[str]:
    m = re.search(
        r"<div data-published-body>([\s\S]*?)</div>\s*(?:<p class=\"muted\"[^>]*data-numbering-note|</article>|<div style=\"margin-top:48px\" id=\"days\")",
        page_html or "",
    )
    return m.group(1) if m else None


def verify_page(page_html: str, text: str, sha256: str, dek: Optional[str] = None, h1: Optional[str] = None) -> list:
    """Problems with a deployed chapter page against the approved edition; ``[]`` = every approved word is deployed, each
    in its slot. The text must hash to ``sha256``; its title line must be the page heading (``h1``) and its summary line
    the header summary (``dek``) — ``PERMITTED_PRESENTATION`` title-line and edition-summary; the page's
    ``data-published-body``, after removing only the permitted presentation, must equal the BODY's rendered prose block
    for block (save the one permitted drop of a first block identical to the header dek)."""
    problems = []
    if text_sha256(str(text or "").replace("\r\n", "\n").strip()) != sha256:
        problems.append("the served edition text does not hash to the approved SHA-256")
    try:
        p = presentation(_text(text))
    except EditionError as exc:
        return problems + [f"the approved text cannot be presented ({exc})"]
    # the documented transformation, run backwards on what is DEPLOYED: the heading and the header summary as the page
    # prints them, the body as approved — rebuilt, it must hash to the approved SHA-256 (rehearsal ruling §2)
    rebuilt = compose_text(_norm(h1) if h1 is not None else "", _norm(dek) if dek is not None else "", p["body"])
    if text_sha256(rebuilt) != sha256:
        if h1 is None or _norm(h1) != p["title"]:
            problems.append(f"the page heading {h1!r} is not the text's title line {p['title']!r}")
        if dek is None or _norm(dek) != p["summary"]:
            problems.append("the header summary is not the edition's summary line, word for word")
        problems.append("the approved text rebuilt from the deployed heading, summary and body does not hash to the approved SHA-256")
    body = _published_body(page_html)
    if body is None:
        return problems + ["the page carries no published body"]
    problems += _blocks_problems(prose_blocks(body), prose_blocks(render_html(p["body"])), dek)
    return problems


def _blocks_problems(got: list, want: list, dek: Optional[str]) -> list:
    if dek and want and got != want and want[0] == _norm(dek) and got == want[1:]:
        return []  # the one permitted drop: the dek, printed once in the header
    if got == want:
        return []
    first = next((i for i, (a, b) in enumerate(zip(got, want)) if a != b), min(len(got), len(want)))
    return [f"the page's prose differs from the approved text at block {first + 1} ({len(got)} blocks served, {len(want)} approved)"]


def verify_archival_page(page_html: str, text: str, h1: Optional[str] = None) -> list:
    """The archival page against its approved rendering: a title line (if the text has one) is the page heading, and the
    body is the rest of the text, block for block."""
    try:
        p = presentation(_text(text), edition=False)
    except EditionError as exc:
        return [f"the approved rendering cannot be presented ({exc})"]
    problems = []
    if p["title"] and (h1 is None or _norm(h1) != " ".join(p["title"].split())):
        problems.append(f"the page heading {h1!r} is not the rendering's title line {p['title']!r}")
    m = re.search(r"<div data-archival-body>\s*<div data-published-body>([\s\S]*?)</div>\s*</div>", page_html or "")
    if not m:
        return problems + ["the page carries no archival body"]
    return problems + _blocks_problems(prose_blocks(m.group(1)), prose_blocks(render_html(p["body"])), None)
