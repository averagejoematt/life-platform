#!/usr/bin/env python3
"""research_finding_verify.py — fetch ONE research-finding source on the laptop and print the source object
`manage_research_finding` accepts (#6208, epic #6206).

The MCP Lambda makes no network call, so verification happens here. The script FETCHES the record itself and
emits the whole object. You never type the title.

  * A PMID or DOI goes through the exercise library's resolvers (`scripts/library_evidence_review.py`, #5778,
    imported, not copied). PubMed E-utilities handles a PMID and Crossref handles a DOI. Title, first author and
    year are matched against what you claim. A retraction or a rejected publication type is refused. For a PMID
    the abstract is read from PubMed efetch; for a DOI, from Crossref when Crossref carries one.
  * A clinical guideline must be on an allow-listed official body's host
    (`config/evidence_source_allowlist.json` "guideline_hosts"). Its page `<title>` must carry the claimed title,
    and its meta description stands in for the abstract.

THE VERIFICATION BLOCK. Every printed source carries `verification`: resolver, resolved_title, first_author,
year, fetched_at, abstract_sha256 (when an abstract exists), the overlap result, and
`stamp = sha256(id_kind|id|resolved_title|fetched_at)[:16]`. The store recomputes the stamp and refuses a
mismatch. WHAT THE STAMP PROVES: the object came unedited from this script, so a title cannot be typed or edited
by hand afterwards. It does NOT prove the Lambda verified anything (there is no network call in the Lambda), and
a stamp is not a signature: someone who runs the hash by hand could forge one. It defends against a hand-pasted
title, not against deliberate forgery.

THE SUBJECT-OVERLAP TRIPWIRE. `--claim` takes the finding's question or claim text. The script prints the content
words that the claim and the title+abstract share (after stop-word removal), and the count. Below
`OVERLAP_MIN` it refuses to emit unless `--override "<reason>"` is given, and the reason is carried in the
verification block. This catches a real PMID attached to an unrelated claim. It is a tripwire for an unrelated
paper. It is not a check that the paper SUPPORTS the claim: that is `claim_supported_by` + `supports_note`, which
you assert as the reader.

    python3 scripts/research_finding_verify.py --pmid 12345678 --title "..." --authors "Surname AB" --year 2020 \\
        --design meta_analysis --review-depth abstract_only --claim "<the finding's question>" \\
        --supported-by abstract_read --supports-note "<what in it supports the finding, 20-400 chars>"
    python3 scripts/research_finding_verify.py --guideline-url https://www.nice.org.uk/guidance/ng000 --title "..." \\
        --design clinical_guideline --review-depth full_text --claim "..." --supported-by full_text_read --supports-note "..."

Exit 0 prints a JSON source object on stdout. Exit 1 prints the problems on stderr. Before anything is printed,
the object is run through `research.findings.validate_source`, so what is printed is what the tool accepts.
Read-only GETs; nothing is written anywhere.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Callable, Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
for _p in (_HERE, os.path.join(_ROOT, "lambdas")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import library_evidence_review as ler  # noqa: E402 — the existing resolvers, imported, never copied
from research import findings as rf  # noqa: E402

USER_AGENT = "life-platform-research-finding-verify/1.0 (scripts/research_finding_verify.py; read-only)"
EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pubmed&retmode=xml&id={pmid}"
#: Shared content words below which the script refuses to emit without --override (a tripwire, not a support check).
OVERLAP_MIN = 2
TextGet = Callable[[str], "tuple[int, str]"]
_TITLE_TAG = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_META_DESC = re.compile(r"<meta[^>]+name=[\"']description[\"'][^>]+content=[\"']([^\"']*)[\"']", re.IGNORECASE)
_ABSTRACT_TAG = re.compile(r"<AbstractText[^>]*>(.*?)</AbstractText>", re.IGNORECASE | re.DOTALL)
_WORD = re.compile(r"[a-z0-9]+")
STOP_WORDS = frozenset(
    "a about above after again against all also among an and any are as at be because been before being between both but "
    "by can could did do does doing during each effect effects few for from further had has have having how however if in "
    "into is it its itself may might more most no nor not of off on once only or other our out over own per same should so "
    "some such than that the their them then there these they this those through to too under until up upon use used using "
    "very via was we were what when where whether which while who whom why will with within without would versus vs does "
    "study studies trial trials review reviews analysis systematic meta randomized randomised controlled adults adult "
    "people patients participants evidence result results association associated among improve improves".split()
)


def guideline_hosts(allow: dict[str, Any]) -> tuple[str, ...]:
    return tuple((allow.get("guideline_hosts") or {}).get("hosts") or ())


def _host_in(host: str, domains) -> bool:
    return any(host == d or host.endswith("." + d) for d in domains)


def text_get(url: str, timeout: float = 20.0) -> tuple[int, str]:
    """GET one text page: PubMed efetch, or a guideline page on an allow-listed official body's host. Nothing else."""
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    if not url.startswith("https://") or not (host == "eutils.ncbi.nlm.nih.gov" or _host_in(host, guideline_hosts(ler.load_allowlist()))):
        raise ValueError(f"refusing to contact {host}: not PubMed E-utilities or an allow-listed guideline host")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310 — https, host allow-listed above
            return resp.status, resp.read(2_000_000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return 0, ""


def _clean(s: Any) -> str:
    return " ".join(html.unescape(ler._TAG_RE.sub(" ", str(s or ""))).split())


def content_words(text: str) -> set[str]:
    out = set()
    for w in _WORD.findall(_clean(text).lower()):
        if len(w) < 3 or w in STOP_WORDS or w.isdigit():
            continue
        out.add(w[:-1] if len(w) > 4 and w.endswith("s") and not w.endswith("ss") else w)  # crude plural fold
    return out


def subject_overlap(claim: str, title: str, abstract: str) -> list[str]:
    """The content words shared by the claim and the title+abstract. A tripwire for an unrelated paper, nothing more."""
    return sorted(content_words(claim) & content_words(f"{title} {abstract}"))


def _recording(http: ler.HttpGet, seen: dict[str, Any]) -> ler.HttpGet:
    """Wrap a resolver's HttpGet so the resolved record can be read back from what it fetched."""

    def get(url: str):
        status, body = http(url)
        seen[url] = body
        return status, body

    return get


def _crossref_message(seen: dict[str, Any]) -> dict[str, Any]:
    return next(((b or {}).get("message") or {} for u, b in seen.items() if "crossref" in u and b), {})


def _pubmed_record(seen: dict[str, Any], pmid: str) -> dict[str, Any]:
    return next((((b or {}).get("result") or {}).get(pmid) or {} for u, b in seen.items() if "esummary" in u and b), {})


def fetch_identifier(args: argparse.Namespace, http: ler.HttpGet, text: TextGet, allow: dict[str, Any]) -> tuple[Optional[dict], list[str]]:
    """A PMID or DOI, resolved through `library_evidence_review.verify_citation`; the record's own fields are kept."""
    claimed: dict[str, Any] = {"title": args.title, "authors": args.authors or "", "year": args.year or 0}
    if args.pmid:
        claimed["pmid"] = args.pmid
    if args.doi:
        claimed["doi"] = args.doi
    seen: dict[str, Any] = {}
    ver = ler.verify_citation(claimed, _recording(http, seen), allow)
    if ver["status"] != ler.VERIFIED:
        return None, [f"{ver['status']}: {p}" for p in ver.get("problems") or []] or [ver["status"]]
    if args.pmid:
        rec = _pubmed_record(seen, args.pmid)
        title, first = _clean(rec.get("title")), str(((rec.get("authors") or [{}])[0] or {}).get("name") or "")
        year = ler._year_prefix(rec.get("pubdate")) or ler._year_prefix(rec.get("epubdate"))
        status, xml = text(EFETCH_URL.format(pmid=args.pmid))
        abstract = _clean(" ".join(_ABSTRACT_TAG.findall(xml))) if status == 200 else ""
        out = {"id_kind": "pmid", "id": args.pmid, "resolver": "pubmed"}
    else:
        m = _crossref_message(seen)
        title = _clean((m.get("title") or [""])[0])
        authors = m.get("author") or []
        lead = next((a for a in authors if a.get("sequence") == "first"), authors[0] if authors else {})
        first = " ".join(x for x in (lead.get("family"), lead.get("given")) if x)
        years = ler._years_from_parts(m.get("issued"), m.get("published-print"), m.get("published-online"))
        year = min(years) if years else None
        abstract = _clean(m.get("abstract"))
        out = {"id_kind": "doi", "id": str(ver["doi"]).lower(), "resolver": "crossref"}
    out.update({"resolved_title": title, "first_author": first, "year": year, "abstract": abstract})
    if ver.get("pubtypes"):
        out["pubtypes"] = list(ver["pubtypes"])
    return out, []


def fetch_guideline(args: argparse.Namespace, text: TextGet, allow: dict[str, Any]) -> tuple[Optional[dict], list[str]]:
    """A guideline URL on an allow-listed host: the page must load and its <title> must carry the claimed title."""
    url = args.guideline_url
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    if not url.startswith("https://") or not _host_in(host, guideline_hosts(allow)):
        return None, [f"{host or url} is not an allow-listed guideline host ({', '.join(guideline_hosts(allow))})"]
    if _host_in(host, allow["denied_hosts"]):
        return None, [f"{host} is a denied host"]
    status, body = text(url)
    if status != 200 or not body:
        return None, [f"guideline page did not load (HTTP {status})"]
    m = _TITLE_TAG.search(body)
    live = _clean(m.group(1)) if m else ""
    claimed, got = ler.norm_title(args.title), ler.norm_title(live)
    if not got or not (ler.titles_match(args.title, live) or (claimed and claimed in got)):
        return None, [f"page title {live!r} does not carry the claimed title {args.title!r}"]
    d = _META_DESC.search(body)
    out = {"id_kind": "guideline_url", "id": url, "resolver": "guideline_page", "resolved_title": live}
    return {**out, "first_author": host, "year": None, "abstract": _clean(d.group(1)) if d else ""}, []


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run(
    argv: list[str], *, http: ler.HttpGet = ler.urllib_get, text: TextGet = text_get, now: Optional[Callable[[], str]] = None
) -> tuple[int, str]:
    """(exit code, output). The http/text fetchers and the clock are injected in tests; the real ones by default."""
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ident = ap.add_mutually_exclusive_group(required=True)
    ident.add_argument("--pmid")
    ident.add_argument("--doi")
    ident.add_argument("--guideline-url")
    ap.add_argument("--title", required=True, help="the title as you read it (matched against the record, never stored)")
    ap.add_argument("--authors", help="'Surname AB, ...' (PMID / DOI)")
    ap.add_argument("--year", type=int, help="publication year (PMID / DOI)")
    ap.add_argument("--design", required=True, choices=rf.DESIGNS)
    ap.add_argument("--review-depth", required=True, choices=rf.REVIEW_DEPTHS)
    ap.add_argument("--claim", required=True, help="the finding's question or claim (for the subject-overlap tripwire)")
    ap.add_argument("--supported-by", required=True, choices=rf.CLAIM_SUPPORT)
    ap.add_argument("--supports-note", required=True, help="what in the source supports the finding, in your words (20-400 chars)")
    ap.add_argument("--override", help="emit despite low subject overlap; the reason is carried in the verification block")
    args = ap.parse_args(argv)
    allow = ler.load_allowlist()
    if args.guideline_url:
        got, problems = fetch_guideline(args, text, allow)
    else:
        if not args.authors or not args.year:
            return 1, "a PMID or DOI is verified against its title, first author and year: pass --authors and --year"
        got, problems = fetch_identifier(args, http, text, allow)
    if not got:
        return 1, "NOT VERIFIED — " + "; ".join(problems)
    shared = subject_overlap(args.claim, got["resolved_title"], got["abstract"])
    report = f"subject overlap: {len(shared)} shared content word(s): {', '.join(shared) or '(none)'}"
    override = " ".join(str(args.override or "").split())
    if len(shared) < OVERLAP_MIN and not override:
        return 1, (
            f"NOT EMITTED — {report}. Below {OVERLAP_MIN}, the record may be an unrelated paper. Check the id; if it is right, "
            're-run with --override "<reason>". (This is a tripwire for an unrelated paper, not a check of support.)'
        )
    fetched_at = (now or _now)()
    verification: dict[str, Any] = {
        "resolver": got["resolver"],
        "resolved_title": got["resolved_title"],
        "first_author": got["first_author"],
        "year": got["year"],
        "fetched_at": fetched_at,
        "overlap_terms": shared,
        "overlap_count": len(shared),
        "stamp": rf.verification_stamp(got["id_kind"], got["id"], got["resolved_title"], fetched_at),
    }
    if got["abstract"]:
        verification["abstract_sha256"] = hashlib.sha256(got["abstract"].encode("utf-8")).hexdigest()
    if override and len(shared) < OVERLAP_MIN:
        verification["override_reason"] = override
    source: dict[str, Any] = {
        "id_kind": got["id_kind"],
        "id": got["id"],
        "design": args.design,
        "review_depth": args.review_depth,
        "resolved_title": got["resolved_title"],
        "verified_on": fetched_at[:10],
        "claim_supported_by": args.supported_by,
        "supports_note": args.supports_note,
        "verification": verification,
    }
    if got.get("pubtypes"):
        source["pubtypes"] = got["pubtypes"]
    try:
        source = rf.validate_source(source, today=fetched_at[:10])
    except rf.FindingError as e:
        return 1, f"NOT ACCEPTED — {e}"
    return 0, json.dumps(source, indent=1, ensure_ascii=False)


def main(argv: Optional[list[str]] = None) -> int:
    code, out = run(sys.argv[1:] if argv is None else argv)
    print(out, file=sys.stdout if code == 0 else sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main())
