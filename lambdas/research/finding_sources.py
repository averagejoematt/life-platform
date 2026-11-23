"""research/finding_sources.py — what a source of the research findings store is, and the check that admits one (#6208).

Split out of `research.findings` (the store's registry, which re-exports every public name here) under the
module-size ceiling. Pure: no I/O, no network, no clock.

IDENTITY, NOT SUPPORT. A verified source means the identifier resolves to this record and the object came unedited
from `scripts/research_finding_verify.py` (its stamp is recomputed here). It does NOT show that the source supports
the finding: that is the reader's own assertion (`claim_supported_by`, `supports_note`).

The host / design / pubtype vocabularies are COPIES of `config/evidence_source_allowlist.json` because config/ is not
staged in the Lambda bundle (`common.repo_config`); the test holds them EQUAL to that file.
"""

from __future__ import annotations

import hashlib
import re
import urllib.parse
from typing import Any

from common.pacific_time import parse_day_key

from research.finding_risk import FindingError

ID_KINDS: tuple[str, ...] = ("pmid", "doi", "guideline_url")


REVIEW_DEPTHS: tuple[str, ...] = ("abstract_only", "full_text")


FULL_TEXT = "full_text"


#: `config/evidence_source_allowlist.json` "designs" keys, plus a clinical guideline (a finding may rest on one).
DESIGNS: tuple[str, ...] = (
    "randomized_trial",
    "controlled_trial",
    "meta_analysis",
    "systematic_review",
    "narrative_review",
    "position_stand",
    "clinical_guideline",
)


#: Copies of the allowlist's lists (held equal by the test). A guideline URL must be on an official body's host.
GUIDELINE_HOSTS: tuple[str, ...] = ("nice.org.uk", "who.int", "heart.org", "ahajournals.org", "escardio.org", "acsm.org")


DENIED_HOSTS: tuple[str, ...] = (
    "twitter.com",
    "x.com",
    "instagram.com",
    "facebook.com",
    "tiktok.com",
    "youtube.com",
    "youtu.be",
    "reddit.com",
    "threads.net",
    "linkedin.com",
    "medium.com",
    "substack.com",
    "blogspot.com",
    "wordpress.com",
    "tumblr.com",
    "patreon.com",
    "strongerbyscience.com",
    "t-nation.com",
)


REJECTED_PUBTYPES: tuple[str, ...] = (
    "Retracted Publication",
    "Retraction of Publication",
    "Published Erratum",
    "Comment",
    "Editorial",
    "Letter",
    "News",
    "Preprint",
)


TEXT_MAX = 1000


_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


_PMID = re.compile(r"^[1-9]\d{0,8}$")


_DOI = re.compile(r"^10\.\d{4,9}/\S+$")


_URL = re.compile(r"https?://([^/\s\"'<>]+)", re.IGNORECASE)


_SOURCE_KEYS = frozenset(
    {
        "id_kind",
        "id",
        "design",
        "review_depth",
        "resolved_title",
        "verified_on",
        "pubtypes",
        "claim_supported_by",
        "supports_note",
        "verification",
    }
)


#: How the recorder says the source supports the finding — asserted by a reader, never implied by a resolving id.
CLAIM_SUPPORT: tuple[str, ...] = ("abstract_read", "full_text_read")


SUPPORTS_NOTE_MIN, SUPPORTS_NOTE_MAX = 20, 400


#: The resolvers `scripts/research_finding_verify.py` fetches from, named in its verification block.
RESOLVERS: tuple[str, ...] = ("pubmed", "crossref", "guideline_page")


_VERIFICATION_KEYS = frozenset(
    {
        "resolver",
        "resolved_title",
        "first_author",
        "year",
        "fetched_at",
        "abstract_sha256",
        "stamp",
        "subject_overlap",
    }
)


_STAMP = re.compile(r"^[0-9a-f]{16}$")


_SHA256 = re.compile(r"^[0-9a-f]{64}$")


_INSTANT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")


def _day(value: Any, name: str) -> str:
    v = str(value or "").strip()
    if not _DAY.match(v) or parse_day_key(v) is None:
        raise FindingError(f"{name} must be a real YYYY-MM-DD day")
    return v


def _text(value: Any, name: str, lo: int, hi: int) -> str:
    t = str(value or "").strip()
    if len(t) < lo or len(t) > hi:
        raise FindingError(f"{name} must be {lo}-{hi} characters")
    return t


def _host_matches(host: str, domains: tuple[str, ...]) -> bool:
    return any(host == d or host.endswith("." + d) for d in domains)


def _denied_hosts_in(*texts: Any) -> list[str]:
    hosts = []
    for t in texts:
        for h in _URL.findall(str(t or "")):
            h = h.lower().split(":")[0]
            if _host_matches(h, DENIED_HOSTS):
                hosts.append(h)
    return hosts


def source_key(src: dict[str, Any]) -> str:
    return f"{src.get('id_kind')}:{src.get('id')}"


def verification_stamp(id_kind: str, ident: str, resolved_title: str, fetched_at: str) -> str:
    """The stamp `scripts/research_finding_verify.py` writes and this module recomputes. It proves the four fields
    came unedited from the script's own fetch — it does NOT mean the Lambda verified anything (the Lambda makes no
    network call). A title typed or edited by hand after the fact no longer matches its stamp and is refused."""
    return hashlib.sha256(f"{id_kind}|{ident}|{resolved_title}|{fetched_at}".encode("utf-8")).hexdigest()[:16]


def _verification(v: Any, kind: str, ident: str, title: str) -> dict[str, Any]:
    if not isinstance(v, dict):
        raise FindingError(
            f"source {kind}:{ident} has no verification block — run scripts/research_finding_verify.py and paste what it prints"
        )
    extra = sorted(set(v) - _VERIFICATION_KEYS)
    if extra:
        raise FindingError(f"unknown verification fields {extra}")
    if v.get("resolver") not in RESOLVERS:
        raise FindingError(f"verification.resolver must be one of {list(RESOLVERS)}")
    fetched_at = str(v.get("fetched_at") or "")
    if not _INSTANT.match(fetched_at):
        raise FindingError("verification.fetched_at must be a UTC instant (YYYY-MM-DDTHH:MM:SSZ)")
    if v.get("resolved_title") != title:
        raise FindingError("the source's resolved_title is not the title the verifier fetched — it was edited after verification")
    if not _STAMP.match(str(v.get("stamp") or "")) or v["stamp"] != verification_stamp(kind, ident, title, fetched_at):
        raise FindingError(
            f"source {kind}:{ident}: the verification stamp does not match its id, title and fetch time — the object was edited "
            "after scripts/research_finding_verify.py printed it (re-run the script)"
        )
    if v.get("abstract_sha256") is not None and not _SHA256.match(str(v["abstract_sha256"])):
        raise FindingError("verification.abstract_sha256 must be a sha256 hex digest")
    year = v.get("year")
    if year is not None and (not isinstance(year, int) or isinstance(year, bool)):
        raise FindingError("verification.year must be an integer or null")
    overlap = v.get("subject_overlap")
    if overlap is not None and not isinstance(overlap, dict):
        raise FindingError("verification.subject_overlap must be an object")  # ADVISORY: its `low` flag never refuses
    out = {k: v[k] for k in sorted(_VERIFICATION_KEYS) if k in v and v[k] is not None}
    out["first_author"] = str(v.get("first_author") or "")
    return out


def validate_source(src: Any, *, today: str) -> dict[str, Any]:
    """One verified source, normalized. Refused, with the reason, unless it is identified, verified and allow-listed."""
    if not isinstance(src, dict):
        raise FindingError("a source must be an object (run scripts/research_finding_verify.py and paste what it prints)")
    extra = sorted(set(src) - _SOURCE_KEYS)
    if extra:
        raise FindingError(f"unknown source fields {extra}; a source carries {sorted(_SOURCE_KEYS)}")
    kind = src.get("id_kind")
    if kind not in ID_KINDS:
        raise FindingError(f"source id_kind must be one of {list(ID_KINDS)}")
    ident = str(src.get("id") or "").strip()
    if kind == "pmid" and not _PMID.match(ident):
        raise FindingError(f"PMID {ident!r} is malformed")
    if kind == "doi":
        ident = ident.lower()
        if not _DOI.match(ident):
            raise FindingError(f"DOI {ident!r} is malformed (10.<registrant>/<suffix>)")
    if kind == "guideline_url":
        parsed = urllib.parse.urlparse(ident)
        host = (parsed.hostname or "").lower()
        if parsed.scheme != "https" or not host:
            raise FindingError("a guideline_url must be an https URL")
        if _host_matches(host, DENIED_HOSTS):
            raise FindingError(f"source host {host} is social media / a blog — never a source")
        if not _host_matches(host, GUIDELINE_HOSTS):
            raise FindingError(f"guideline host {host} is not an allow-listed official body ({', '.join(GUIDELINE_HOSTS)})")
    if src.get("design") not in DESIGNS:
        raise FindingError(f"source design must be one of {list(DESIGNS)}")
    if src.get("review_depth") not in REVIEW_DEPTHS:
        raise FindingError(f"source review_depth must be one of {list(REVIEW_DEPTHS)}")
    title = str(src.get("resolved_title") or "")
    if not title.strip() or not str(src.get("verified_on") or "").strip():
        raise FindingError(
            f"source {kind}:{ident} is unverified — it needs resolved_title and verified_on from scripts/research_finding_verify.py"
        )
    if title != " ".join(title.split()) or len(title) > TEXT_MAX:
        raise FindingError("resolved_title must be exactly as the verifier printed it (single-spaced, at most 1000 characters)")
    verified_on = _day(src.get("verified_on"), "source verified_on")
    if verified_on > today:
        raise FindingError("source verified_on cannot be in the future")
    verification = _verification(src.get("verification"), kind, ident, title)
    if verification["fetched_at"][:10] != verified_on:
        raise FindingError("verified_on must be the day of verification.fetched_at")
    supported_by = src.get("claim_supported_by")
    if supported_by not in CLAIM_SUPPORT:
        raise FindingError(f"claim_supported_by must be one of {list(CLAIM_SUPPORT)} — say how you know the source supports the finding")
    if supported_by == "full_text_read" and src.get("review_depth") != FULL_TEXT:
        raise FindingError("claim_supported_by full_text_read needs review_depth full_text")
    note = _text(src.get("supports_note"), "supports_note", SUPPORTS_NOTE_MIN, SUPPORTS_NOTE_MAX)
    pubtypes = src.get("pubtypes") or []
    if not isinstance(pubtypes, list):
        raise FindingError("source pubtypes must be a list")
    bad = sorted(set(map(str, pubtypes)) & set(REJECTED_PUBTYPES))
    if bad:
        raise FindingError(f"source {kind}:{ident} is a rejected publication type: {', '.join(bad)}")
    denied = _denied_hosts_in(ident, title, note)
    if denied:
        raise FindingError(f"source names a denied host: {', '.join(sorted(set(denied)))}")
    out: dict[str, Any] = {
        "id_kind": kind,
        "id": ident,
        "design": src["design"],
        "review_depth": src["review_depth"],
        "resolved_title": title,
        "verified_on": verified_on,
        "claim_supported_by": supported_by,
        "supports_note": note,
        "verification": verification,
    }
    if pubtypes:
        out["pubtypes"] = [str(p) for p in pubtypes]
    return out


def _is_source_ref(ref: str) -> bool:
    kind, _, ident = ref.partition(":")
    if kind == "pmid":
        return bool(_PMID.match(ident))
    if kind == "doi":
        return bool(_DOI.match(ident.lower()))
    if kind == "guideline_url":
        host = (urllib.parse.urlparse(ident).hostname or "").lower()
        return ident.startswith("https://") and _host_matches(host, GUIDELINE_HOSTS)
    return False
