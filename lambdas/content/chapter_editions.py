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
  ``…#NN`` (NN >= 02)     an EDITION (``record_type: chapter_edition``): its full text (the chronicle's markdown),
                          the first-published day, the corrections it carries, the proposal instant — and, once the owner
                          approves it, the approval history, ``revised_on`` and the platform's signature.
  ``…#01#archival#NN``    an ARCHIVAL RENDERING of the first edition (``record_type: chapter_edition_archival``): a
                          SEPARATELY proposed and separately approved text — never derived from the raw original — that
                          passes every publication gate. Off by default per chapter: without an approved one there is no
                          ``first-edition`` page for that chapter.

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
PUBLIC_ARCHIVAL_FIELDS = ("archival_id", "approved_on", "note", "signature", "text_sha256", "text", "body_html")

#: The ONLY things the chapter page may add to, or take from, an edition's prose (owner ruling 2026-11-22, final approval
#: §1: "the deployed texts match the approved hashes, except for explicitly permitted presentation metadata"). Every
#: one sits BETWEEN prose blocks or outside the body, never inside a sentence; ``verify_page`` removes exactly these and
#: then requires the page's prose blocks to equal the approved text's, block for block, word for word.
PERMITTED_PRESENTATION = (
    ("data-evidence", "an evidence figure or graded-call card placed between paragraphs (www/src/lib/evidence.js)"),
    ("data-record-as-published", "the dated coach-record note placed between paragraphs (www/src/lib/record_note.js)"),
    ("dek-duplicate", "a first signature line or first paragraph identical to the header dek, printed once in the header"),
    ("signature-class", "the `note` / `filed` class on an emphasised signature line (a class, not a word)"),
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


def archival_note(first_published: str, revised_on: str) -> str:
    """The archival page's one note. It says what the page is and where the current text is — and nothing about what the
    rendering leaves out: no count, no wording, no identity (owner ruling 2026-11-22 §3). One fixed sentence set, so no
    proposal can carry a description of a removed passage onto the page."""
    return (
        f"This is an archival rendering of the chapter's first edition, first published {CC.day_words(first_published)}. "
        "It is kept for the historical record and is not the current text. It was prepared for public reading and may not "
        f"reproduce the first edition in full. The current edition, revised {CC.day_words(revised_on)}, is at the chapter's own address."
    )


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


def new_archival(*, chapter_id: str, archival_id: int, text: str, proposed_at: str, user_id: str = CC.USER_ID_DEFAULT) -> dict:
    """An archival rendering of the first edition, unapproved. Its words are the proposal's — never read off the original."""
    chapter_id = _chapter(chapter_id)
    if not isinstance(archival_id, int) or isinstance(archival_id, bool) or not 1 <= archival_id <= 99:
        raise EditionError("archival_id must be a whole number from 1 to 99")
    if not ISO_INSTANT.match(str(proposed_at or "")):
        raise EditionError("proposed_at must be an ISO-8601 instant")
    body = _text(text)
    item = _base(chapter_id, sk_archival(chapter_id, archival_id), ARCHIVAL_TYPE, user_id)
    item.update(
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
    _approved(item)
    if not ISO_DAY.match(str(item.get("approved_on") or "")):
        raise EditionError("an approved rendering carries the day it was approved")
    return {**item, "archival_id": n}


def _public_approvals(item: dict) -> list:
    return [{"by": a["by"], "on": a.get("on") or str(a["at"])[:10], "via": a.get("via") or CC.APPROVED_VIA} for a in item["approvals"]]


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
    edition or rendering that any gate refuses; a rendering for a chapter with no served edition."""
    say = log or (lambda _m: None)
    originals: dict = {}
    editions: dict = {}
    archivals: dict = {}
    for it in items or []:
        if not isinstance(it, dict) or not str(it.get("sk") or "").startswith(SK_PREFIX):
            continue
        kind = it.get("record_type")
        try:
            if kind == ORIGINAL_TYPE:
                originals[it["chapter_id"]] = validate_original(it)
            elif kind == EDITION_TYPE:
                if not it.get("approvals"):
                    continue
                e = validate_edition(it)
                editions.setdefault(e["chapter_id"], []).append(e)
            elif kind == ARCHIVAL_TYPE:
                if not it.get("approvals"):
                    continue
                a = validate_archival(it)
                archivals.setdefault(a["chapter_id"], []).append(a)
        except (EditionError, KeyError, TypeError, ValueError) as exc:
            say(f"[chapter-editions] {it.get('sk')} withheld: {exc}")
    out = []
    for cid in sorted(editions):
        original = originals.get(cid)
        if original is None:
            say(f"[chapter-editions] {cid}: no first-edition evidence record — every edition withheld")
            continue
        served = None
        for e in sorted(editions[cid], key=lambda e: e["edition"], reverse=True):
            if str(original["backed_up_at"]) > str(e.get("approved_at") or ""):
                say(f"[chapter-editions] {e['sk']} withheld: approved before the first edition was backed up")
                continue
            findings = gate_findings(e["text"], tainted=tainted, private_calls=private_calls, filter_hits=filter_hits)
            if findings:
                say(f"[chapter-editions] {e['sk']} withheld by the publication gates: {len(findings)} finding(s)")
                continue
            served = e
            break
        if served is None:
            continue
        archival = None
        for a in sorted(archivals.get(cid, []), key=lambda a: a["archival_id"], reverse=True):
            findings = gate_findings(a["text"], tainted=tainted, private_calls=private_calls, filter_hits=filter_hits)
            if findings:
                say(f"[chapter-editions] {a['sk']} withheld by the publication gates: {len(findings)} finding(s)")
                continue
            archival = {
                "archival_id": a["archival_id"],
                "approved_on": a["approved_on"],
                "note": archival_note(served["first_published"], served["revised_on"]),
                "signature": archival_signature(a["approved_on"]),
                "text_sha256": a["text_sha256"],
                "text": a["text"],
                "body_html": render_html(a["text"]),
            }
            break
        out.append(
            {
                "chapter_id": cid,
                "edition": served["edition"],
                "edition_line": edition_line(served["edition"], served["revised_on"], served["first_published"]),
                "signature": served["signature"],
                "first_published": served["first_published"],
                "revised_on": served["revised_on"],
                "approvals": _public_approvals(served),
                "carries": list(served.get("carries") or []),
                "word_count": word_count(served["text"]),
                "text_sha256": served["text_sha256"],
                "text": served["text"],
                "body_html": render_html(served["text"]),
                "archival": archival,
            }
        )
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
    for marker in ("data-evidence", "data-record-as-published"):
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


def verify_page(page_html: str, text: str, sha256: str, dek: Optional[str] = None) -> list:
    """Problems with a deployed chapter page against the approved edition; ``[]`` = its prose IS the approved bytes.

    The text must hash to ``sha256``; the page's ``data-published-body`` must exist; after removing only the
    ``PERMITTED_PRESENTATION`` set, its prose blocks must equal the approved text's rendered blocks exactly — save the
    one permitted drop of a first block identical to the header dek."""
    problems = []
    if text_sha256(str(text or "").replace("\r\n", "\n").strip()) != sha256:
        problems.append("the served edition text does not hash to the approved SHA-256")
    m = re.search(
        r"<div data-published-body>([\s\S]*?)</div>\s*(?:<p class=\"muted\"[^>]*data-numbering-note|</article>|<div style=\"margin-top:48px\" id=\"days\")",
        page_html or "",
    )
    if not m:
        return problems + ["the page carries no published body"]
    want = prose_blocks(render_html(text))
    got = prose_blocks(m.group(1))
    if dek and want and got != want and want[0] == _norm(dek) and got == want[1:]:
        return problems  # the one permitted drop: the dek, printed once in the header
    if got != want:
        first = next((i for i, (a, b) in enumerate(zip(got, want)) if a != b), min(len(got), len(want)))
        problems.append(
            f"the page's prose differs from the approved text at block {first + 1} ({len(got)} blocks served, {len(want)} approved)"
        )
    return problems
