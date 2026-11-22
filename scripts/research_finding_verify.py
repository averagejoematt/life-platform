#!/usr/bin/env python3
"""research_finding_verify.py — verify ONE research-finding source on the laptop and print the object
`manage_research_finding` accepts (#6208, epic #6206).

The MCP Lambda makes no network call: a source reaches the findings store already verified. This script is
where that happens. It reuses the exercise library's resolvers (`scripts/library_evidence_review.py`, #5778) —
PubMed E-utilities for a PMID, Crossref for a DOI, title + first author + year matched, a retraction or a
rejected publication type refused — and adds the one thing they do not cover: a clinical guideline on an
allow-listed official body's host (`config/evidence_source_allowlist.json` "guideline_hosts"), whose page title
must match the claimed title. Read-only GETs; nothing is written anywhere.

    python3 scripts/research_finding_verify.py --pmid 12345678 --title "..." --authors "Surname AB" --year 2020 \\
        --design meta_analysis --review-depth abstract_only
    python3 scripts/research_finding_verify.py --doi 10.1000/xyz --title "..." --authors "Surname AB" --year 2021 \\
        --design randomized_trial --review-depth full_text
    python3 scripts/research_finding_verify.py --guideline-url https://www.nice.org.uk/guidance/ng000 \\
        --title "..." --design clinical_guideline --review-depth full_text

Exit 0 and a JSON source object on stdout when verified; exit 1 and the problems on stderr otherwise. The
printed object is run through `research.findings.validate_source` before it is printed, so what it prints is
what the tool accepts. `--review-depth` is YOUR statement of what you read: full_text only if you read it all.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from typing import Any, Callable, Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
for _p in (_HERE, os.path.join(_ROOT, "lambdas")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import library_evidence_review as ler  # noqa: E402 — the existing resolvers, imported, never copied
from research import findings as rf  # noqa: E402

USER_AGENT = "life-platform-research-finding-verify/1.0 (scripts/research_finding_verify.py; read-only)"
PageGet = Callable[[str], "tuple[int, str]"]
_TITLE_TAG = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)


def guideline_hosts(allow: dict[str, Any]) -> tuple[str, ...]:
    return tuple((allow.get("guideline_hosts") or {}).get("hosts") or ())


def _host_in(host: str, domains) -> bool:
    return any(host == d or host.endswith("." + d) for d in domains)


def page_get(url: str, timeout: float = 20.0) -> tuple[int, str]:
    """GET one guideline page. Refuses any host that is not an allow-listed official body."""
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    allow = ler.load_allowlist()
    if not url.startswith("https://") or not _host_in(host, guideline_hosts(allow)):
        raise ValueError(f"refusing to contact {host}: not an allow-listed guideline host")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310 — https, host allow-listed above
            return resp.status, resp.read(2_000_000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return 0, ""


def _recording(http: ler.HttpGet, seen: dict[str, Any]) -> ler.HttpGet:
    """Wrap a resolver's HttpGet so the resolved record's title can be read back from what it fetched."""

    def get(url: str):
        status, body = http(url)
        seen[url] = body
        return status, body

    return get


def _resolved_title(seen: dict[str, Any], pmid: str, doi: str) -> str:
    for url, body in seen.items():
        if not body:
            continue
        if "crossref" in url and doi and (body.get("message") or {}).get("title"):
            return str(body["message"]["title"][0])
        rec = ((body.get("result") or {}).get(pmid) or {}) if pmid else {}
        if rec.get("title"):
            return str(rec["title"])
    return ""


def verify_identifier(args: argparse.Namespace, http: ler.HttpGet, allow: dict[str, Any]) -> tuple[Optional[dict[str, Any]], list[str]]:
    """A PMID or DOI, through `library_evidence_review.verify_citation`. (resolved fields, problems)."""
    claimed = {"title": args.title, "authors": args.authors or "", "year": args.year or 0}
    if args.pmid:
        claimed["pmid"] = args.pmid
    if args.doi:
        claimed["doi"] = args.doi
    seen: dict[str, Any] = {}
    ver = ler.verify_citation(claimed, _recording(http, seen), allow)
    if ver["status"] != ler.VERIFIED:
        return None, [f"{ver['status']}: {p}" for p in ver.get("problems") or []] or [ver["status"]]
    title = " ".join(html.unescape(ler._TAG_RE.sub("", _resolved_title(seen, args.pmid or "", ver.get("doi") or ""))).split())
    out: dict[str, Any] = {"id_kind": "pmid" if args.pmid else "doi", "id": args.pmid or ver["doi"], "resolved_title": title}
    if ver.get("pubtypes"):
        out["pubtypes"] = list(ver["pubtypes"])
    return out, []


def verify_guideline(args: argparse.Namespace, page: PageGet, allow: dict[str, Any]) -> tuple[Optional[dict[str, Any]], list[str]]:
    """A guideline URL on an allow-listed host: the page must load and its <title> must carry the claimed title."""
    url = args.guideline_url
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    if not url.startswith("https://") or not _host_in(host, guideline_hosts(allow)):
        return None, [f"{host or url} is not an allow-listed guideline host ({', '.join(guideline_hosts(allow))})"]
    if _host_in(host, allow["denied_hosts"]):
        return None, [f"{host} is a denied host"]
    status, body = page(url)
    if status != 200 or not body:
        return None, [f"guideline page did not load (HTTP {status})"]
    m = _TITLE_TAG.search(body)
    live = " ".join(html.unescape(m.group(1)).split()) if m else ""
    claimed, got = ler.norm_title(args.title), ler.norm_title(live)
    if not got or not (ler.titles_match(args.title, live) or (claimed and claimed in got)):
        return None, [f"page title {live!r} does not carry the claimed title {args.title!r}"]
    return {"id_kind": "guideline_url", "id": url, "resolved_title": live}, []


def run(argv: list[str], *, http: ler.HttpGet = ler.urllib_get, page: PageGet = page_get, today: Optional[str] = None) -> tuple[int, str]:
    """(exit code, output). Injected http/page in tests; the real resolvers by default."""
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ident = ap.add_mutually_exclusive_group(required=True)
    ident.add_argument("--pmid")
    ident.add_argument("--doi")
    ident.add_argument("--guideline-url")
    ap.add_argument("--title", required=True, help="the title as you read it")
    ap.add_argument("--authors", help="'Surname AB, ...' (PMID / DOI)")
    ap.add_argument("--year", type=int, help="publication year (PMID / DOI)")
    ap.add_argument("--design", required=True, choices=rf.DESIGNS)
    ap.add_argument("--review-depth", required=True, choices=rf.REVIEW_DEPTHS)
    args = ap.parse_args(argv)
    allow = ler.load_allowlist()
    if args.guideline_url:
        resolved, problems = verify_guideline(args, page, allow)
    else:
        if not args.authors or not args.year:
            return 1, "a PMID or DOI is verified against its title, first author and year: pass --authors and --year"
        resolved, problems = verify_identifier(args, http, allow)
    if not resolved:
        return 1, "NOT VERIFIED — " + "; ".join(problems)
    source = {**resolved, "design": args.design, "review_depth": args.review_depth, "verified_on": today or date.today().isoformat()}
    try:
        source = rf.validate_source(source, today=source["verified_on"])
    except rf.FindingError as e:
        return 1, f"NOT ACCEPTED — {e}"
    return 0, json.dumps(source, indent=1, ensure_ascii=False)


def main(argv: Optional[list[str]] = None) -> int:
    code, out = run(sys.argv[1:] if argv is None else argv)
    print(out, file=sys.stdout if code == 0 else sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main())
