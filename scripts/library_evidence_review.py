#!/usr/bin/env python3
"""library_evidence_review.py — the exercise library's per-block evidence review (#5778).

Run once per training block from the training-review skill (`.claude/skills/training-review/SKILL.md` §7). No
schedule. It PROPOSES library changes; the owner accepts them by merging the PR it opens. It never merges, never
pushes to main and never edits the library in place without `--open-pr`.

WHAT IT DOES

  1. Re-verifies every citation already in `config/exercise_library.json` LIVE: the DOI through Crossref
     (`api.crossref.org/works/<doi>`), the PMID through PubMed E-utilities (`esummary`), each record's title, first
     author and year matched, the PMID's DOI cross-checked, a retraction / erratum / comment pubtype flagged. A
     citation that is gone (`not_found`) or retracted, and that alone backs a reviewed row (evidence above
     `none_reviewed`), becomes a proposed downgrade of that row's evidence to `none_reviewed` — its quality tier
     then falls back to the rubric's (#5857). A `mismatch` is reported for a `correct_citation`, never auto-downgraded. A
     network failure is `unreachable` and changes nothing.
  2. Reads `--proposals FILE`: the changes the reviewer wants (new citations, corrected citations, evidence changes,
     new expansion candidates), authored in the training-review session from the ALLOW-LISTED source set
     `config/evidence_source_allowlist.json` — peer-reviewed trials and meta-analyses by DOI/PMID, and papers
     surfaced by the named evidence-based reviewers listed there. No social media, no blogs, no bare URLs: a
     proposal citing one is rejected with the reason.
  3. Verifies every proposed citation live the same way before it can register. A citation that does not verify
     is rejected, and so is every evidence change and candidate that leaned on it — an unverifiable citation never
     raises evidence; the row stays `none_reviewed`. Evidence backing additionally needs a verified PMID,
     `abstract_read: true` and a study design the allowlist lets back that confidence (`may_back`); a one-band
     `adjust` off the rubric tier needs `rct_direct` (#5857). The QUALITY tier is never proposed: the rubric derives it.
  4. `--discover` searches PubMed for trials / meta-analyses published since the last review that mention a
     library target and hypertrophy. That list is READING, never a change: a human reads the abstract and writes a
     proposal. No model is used anywhere in this script, and nothing it finds bypasses step 3.

OUTPUTS

  dry-run (default)      prints the report and the library diff; writes NOTHING.
  --out DIR              also writes DIR/proposal.json (the full review) and DIR/library.diff.
  --open-pr --issue N    creates a locked lane worktree off origin/main (scripts/lane_worktree.py), applies the
                         accepted changes there (the library JSON + one ledger record in
                         deploy/exercise_library_reviews.json), commits the two paths through
                         deploy/agent_commit.sh --push (the lane branch) and opens a PR against main for the
                         owner. Never merges; refuses to push main.

    python3 scripts/library_evidence_review.py                                  # re-verify only
    python3 scripts/library_evidence_review.py --proposals p.json --out /tmp/r  # review a proposal file
    python3 scripts/library_evidence_review.py --discover --since 2026-06-01    # reading list
    python3 scripts/library_evidence_review.py --proposals p.json --open-pr --issue 5778

PROPOSAL FILE

    {"review_id": "block-2026-12", "proposals": [
      {"op": "add_citation", "citation_id": "smith2026_x",
       "citation": {"doi": "10...", "pmid": "4...", "title": "...", "authors": "Smith A, ...", "year": 2026,
                    "journal": "...", "study_design": "randomized_trial", "design": "free text",
                    "finding": "what the abstract says", "abstract_read": true},
       "found_via": {"kind": "pubmed"}},                       # or {"kind": "reviewer", "name": "Schoenfeld BJ"}
      {"op": "correct_citation", "citation_id": "<existing id>", "citation": {... the corrected record ...},
       "found_via": {"kind": "crossref"}},
      {"op": "set_evidence", "movement": "<library key>", "target": "<hypertrophy target>",
       "evidence_confidence": "rct_direct", "citations": ["smith2026_x"], "rationale": "...", "abstract_read": true,
       "adjust": {"bands": 1, "citation": "smith2026_x", "why": "grew the target more than <compared movement>"}},
      {"op": "add_candidate", "candidate": {<the curation module's _x(...) shape: key, title, template_id or
       template_note, target, family, length_bias, resistance_profile, stability, joint_stress, skill_complexity,
       equipment, hypertrophy?, gates?, curation_note?>}, "citations": ["smith2026_x"], "rationale": "..."}]}

Exit: 0 = done; 1 = an existing citation definitively failed re-verification (the report names it); 2 = usage.
"""

from __future__ import annotations

import argparse
import copy
import datetime as _dt
import difflib
import html
import json
import os
import re
import subprocess
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Optional

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (os.path.join(REPO_ROOT, "lambdas"), os.path.join(REPO_ROOT, "deploy"), _HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import exercise_library_reviews as reviews  # noqa: E402
from training import (
    exercise_library as xl,  # noqa: E402
    quality_rubric,  # noqa: E402
)

ALLOWLIST_REL = os.path.join("config", "evidence_source_allowlist.json")
LIBRARY_REL = os.path.join("config", "exercise_library.json")
LEDGER_REL = os.path.join("deploy", "exercise_library_reviews.json")

CROSSREF_URL = "https://api.crossref.org/works/{doi}"
ESUMMARY_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?db=pubmed&retmode=json&id={ids}"
ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&retmode=json&retmax={n}&datetype=pdat&mindate={since}&maxdate=3000&term={term}"
USER_AGENT = "life-platform-library-evidence-review/1.0 (scripts/library_evidence_review.py; read-only)"
TITLE_MATCH = 0.90  # difflib ratio on the normalized titles
DISCOVER_PER_TARGET = 8

VERIFIED = "verified"
MISMATCH = "mismatch"
NOT_FOUND = "not_found"
UNREACHABLE = "unreachable"
REJECTED = "rejected"
DEFINITIVE_FAILURES = (NOT_FOUND, REJECTED)  # an existing citation in one of these states may be auto-downgraded

_URL_RE = re.compile(r"https?://([^/\s\"'<>]+)", re.I)
_DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$")
_PMID_RE = re.compile(r"^\d{6,9}$")
_TAG_RE = re.compile(r"<[^>]+>")

# HttpGet: url -> (status, parsed JSON or None). Status 0 = no response (network failure). Injected in tests.
HttpGet = Callable[[str], "tuple[int, Optional[dict[str, Any]]]"]


# ── HTTP (read-only GETs to Crossref and NCBI; nothing else is ever contacted) ────────────────────────────────────────


def urllib_get(url: str, timeout: float = 20.0) -> tuple[int, Optional[dict[str, Any]]]:
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    if host not in ("api.crossref.org", "eutils.ncbi.nlm.nih.gov"):
        raise ValueError(f"refusing to contact {host}: only Crossref and NCBI E-utilities are verification sources")
    if host == "eutils.ncbi.nlm.nih.gov":
        time.sleep(0.4)  # NCBI's keyless limit is 3 requests / second
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310 — https host allow-listed above
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return 0, None


# ── normalization ───────────────────────────────────────────────────────────────────────────────────────────────


def _fold(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")


def norm_title(t: str) -> str:
    t = _fold(html.unescape(_TAG_RE.sub("", str(t or "")))).lower()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", t).split())


def titles_match(a: str, b: str) -> bool:
    na, nb = norm_title(a), norm_title(b)
    return bool(na) and (na == nb or difflib.SequenceMatcher(None, na, nb).ratio() >= TITLE_MATCH)


def first_author_surname(authors: str) -> str:
    """'Maeo S, Wu Y, ...' -> 'maeo'; 'Androulakis-Korakakis P' -> 'androulakis korakakis'."""
    first = str(authors or "").split(",")[0].strip()
    parts = first.split()
    if len(parts) > 1 and re.fullmatch(r"[A-Z]{1,4}", parts[-1]):
        parts = parts[:-1]
    return norm_title(" ".join(parts))


def _years_from_parts(*blocks: Any) -> set[int]:
    out: set[int] = set()
    for b in blocks:
        try:
            out.add(int((b or {})["date-parts"][0][0]))
        except (KeyError, IndexError, TypeError, ValueError):
            continue
    return out


def _year_prefix(s: Any) -> Optional[int]:
    m = re.match(r"^(\d{4})", str(s or ""))
    return int(m.group(1)) if m else None


# ── the allowlist ───────────────────────────────────────────────────────────────────────────────────────────────


def load_allowlist(root: str = REPO_ROOT) -> dict[str, Any]:
    with open(os.path.join(root, ALLOWLIST_REL), encoding="utf-8") as f:
        return json.load(f)


def _host_ok(host: str, allow: dict[str, Any]) -> Optional[str]:
    host = host.lower().split(":")[0]
    for d in allow["denied_hosts"]:
        if host == d or host.endswith("." + d):
            return f"source host {host} is social media / a blog — never an allow-listed source"
    if host not in allow["allowed_hosts"]:
        return f"source host {host} is not allow-listed (cite a DOI or PMID, not a URL)"
    return None


def _strings(node: Any):
    if isinstance(node, dict):
        for v in node.values():
            yield from _strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from _strings(v)
    elif isinstance(node, str):
        yield node


def source_problems(citation: dict[str, Any], found_via: dict[str, Any], allow: dict[str, Any]) -> list[str]:
    """Why this citation is NOT from the allow-listed source set (empty = admissible to verify). Static: no network."""
    probs: list[str] = []
    kind = str((found_via or {}).get("kind") or "")
    if kind not in allow["channels"]:
        probs.append(f"channel {kind or '<none>'!r} is not allow-listed (allowed: {', '.join(sorted(allow['channels']))})")
    if kind == "reviewer" and (found_via or {}).get("name") not in allow["reviewers"]["names"]:
        probs.append(f"reviewer {found_via.get('name')!r} is not a named evidence-based reviewer in the allowlist")
    for s in list(_strings(citation)) + list(_strings(found_via)):
        for host in _URL_RE.findall(s):
            p = _host_ok(host, allow)
            if p and p not in probs:
                probs.append(p)
    doi, pmid = str(citation.get("doi") or ""), str(citation.get("pmid") or "")
    if not doi and not pmid:
        probs.append("no DOI or PMID — a peer-reviewed record is identified by one")
    if doi and not _DOI_RE.match(doi):
        probs.append(f"DOI {doi!r} is malformed")
    if pmid and not _PMID_RE.match(pmid):
        probs.append(f"PMID {pmid!r} is malformed")
    design = citation.get("study_design")
    if design not in allow["designs"]:
        probs.append(f"study_design {design!r} is not an allow-listed design ({', '.join(allow['designs'])})")
    for k in ("title", "authors", "year", "journal", "finding"):
        if not citation.get(k):
            probs.append(f"missing {k}")
    return probs


# ── live verification ───────────────────────────────────────────────────────────────────────────────────────────


def verify_doi(doi: str, claimed: dict[str, Any], http: HttpGet, allow: dict[str, Any]) -> dict[str, Any]:
    status, body = http(CROSSREF_URL.format(doi=urllib.parse.quote(doi, safe="/")))
    if status == 0 or status >= 500:
        return {"status": UNREACHABLE, "problems": [f"Crossref unreachable for {doi} (HTTP {status})"]}
    if status == 404 or not body or "message" not in body:
        return {"status": NOT_FOUND, "problems": [f"DOI {doi} does not resolve in Crossref (HTTP {status})"]}
    m = body["message"]
    probs: list[str] = []
    title = (m.get("title") or [""])[0]
    if not titles_match(title, claimed.get("title", "")):
        probs.append(f"Crossref title {title!r} does not match")
    authors = m.get("author") or []
    first = next((a for a in authors if a.get("sequence") == "first"), authors[0] if authors else {})
    if norm_title(first.get("family", "")) != first_author_surname(claimed.get("authors", "")):
        probs.append(f"Crossref first author {first.get('family')!r} does not match")
    years = _years_from_parts(m.get("issued"), m.get("published-print"), m.get("published-online"), m.get("published"))
    if int(claimed.get("year") or 0) not in years:
        probs.append(f"year {claimed.get('year')} not among Crossref's {sorted(years)}")
    if m.get("type") not in allow["crossref_types"]:
        return {"status": REJECTED, "problems": [f"Crossref type {m.get('type')!r} is not a peer-reviewed journal article"]}
    if any((u.get("update-type") or "").lower() == "retraction" for u in m.get("update-to") or []):
        return {"status": REJECTED, "problems": [f"DOI {doi} is a retraction notice"]}
    return {"status": MISMATCH if probs else VERIFIED, "problems": probs, "crossref_type": m.get("type")}


def verify_pmid(pmid: str, claimed: dict[str, Any], http: HttpGet, allow: dict[str, Any]) -> dict[str, Any]:
    status, body = http(ESUMMARY_URL.format(ids=pmid))
    if status == 0 or status >= 500:
        return {"status": UNREACHABLE, "problems": [f"PubMed unreachable for PMID {pmid} (HTTP {status})"]}
    rec = ((body or {}).get("result") or {}).get(pmid)
    if status != 200 or not rec or rec.get("error"):
        return {"status": NOT_FOUND, "problems": [f"PMID {pmid} does not resolve in PubMed"]}
    probs: list[str] = []
    if not titles_match(rec.get("title", ""), claimed.get("title", "")):
        probs.append(f"PubMed title {rec.get('title')!r} does not match")
    first = ((rec.get("authors") or [{}])[0].get("name") or "").strip()
    if first_author_surname(first) != first_author_surname(claimed.get("authors", "")):
        probs.append(f"PubMed first author {first!r} does not match")
    years = {y for y in (_year_prefix(rec.get("pubdate")), _year_prefix(rec.get("epubdate"))) if y}
    if int(claimed.get("year") or 0) not in years:
        probs.append(f"year {claimed.get('year')} not among PubMed's {sorted(years)}")
    pub_doi = next((a.get("value") for a in rec.get("articleids") or [] if a.get("idtype") == "doi"), None)
    if claimed.get("doi") and pub_doi and pub_doi.lower() != str(claimed["doi"]).lower():
        probs.append(f"PubMed's DOI {pub_doi} is not the claimed {claimed['doi']}")
    pubtypes = list(rec.get("pubtype") or [])
    bad = sorted(set(pubtypes) & set(allow["rejected_pubtypes"]))
    out = {"pubtypes": pubtypes, "pubmed_doi": pub_doi, "authors": [a.get("name") for a in rec.get("authors") or []]}
    if bad:
        return {**out, "status": REJECTED, "problems": [f"PubMed pubtype {', '.join(bad)}"]}
    return {**out, "status": MISMATCH if probs else VERIFIED, "problems": probs}


def verify_citation(claimed: dict[str, Any], http: HttpGet, allow: dict[str, Any]) -> dict[str, Any]:
    """Every identifier the record carries, resolved live. Overall status is the worst of the parts."""
    parts: dict[str, dict[str, Any]] = {}
    pmid = str(claimed.get("pmid") or "")
    doi = str(claimed.get("doi") or "")
    if pmid:
        parts["pmid"] = verify_pmid(pmid, claimed, http, allow)
        if not doi and parts["pmid"].get("pubmed_doi"):
            doi = parts["pmid"]["pubmed_doi"]  # a PMID-only proposal registers the DOI PubMed itself names
    if doi:
        parts["doi"] = verify_doi(doi, claimed, http, allow)
    order = (REJECTED, NOT_FOUND, MISMATCH, UNREACHABLE, VERIFIED)
    status = min((p["status"] for p in parts.values()), key=order.index) if parts else NOT_FOUND
    return {
        "status": status,
        "doi": doi or None,
        "doi_verified": parts.get("doi", {}).get("status") == VERIFIED,
        "pmid_verified": parts.get("pmid", {}).get("status") == VERIFIED,
        "pubtypes": parts.get("pmid", {}).get("pubtypes", []),
        "pubmed_authors": parts.get("pmid", {}).get("authors", []),
        "problems": [p for part in parts.values() for p in part.get("problems", [])],
    }


def confidence_it_may_back(citation: dict[str, Any], ver: dict[str, Any], allow: dict[str, Any]) -> list[str]:
    """The evidence confidences a REGISTERED citation may back: none unless the PMID verified and the abstract was read."""
    req = allow["evidence_backing_requires"]
    if ver.get("status") != VERIFIED or not ver.get("pmid_verified"):
        return []
    if req.get("abstract_read") and citation.get("abstract_read") is not True:
        return []
    return list(allow["designs"].get(citation.get("study_design"), {}).get("may_back") or [])


def _existing_design(c: dict[str, Any]) -> str:
    """The allowlist design an already-registered citation's free-text `design` describes (no study_design field)."""
    d = str(c.get("study_design") or c.get("design") or "").lower()
    if c.get("study_design"):
        return c["study_design"]
    if "meta-analysis" in d:
        return "meta_analysis"
    if "systematic review" in d:
        return "systematic_review"
    if re.search(r"\brct\b|randomi[sz]ed", d):
        return "randomized_trial"
    return "controlled_trial"


# ── the review ──────────────────────────────────────────────────────────────────────────────────────────────────


def reverify_existing(lib: dict[str, Any], http: HttpGet, allow: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {cid: verify_citation(c, http, allow) for cid, c in lib["citations"].items()}


def _registered_record(cid: str, c: dict[str, Any], ver: dict[str, Any], found_via: dict[str, Any], review_id: str, today: str) -> dict:
    via = "Crossref + PubMed" if ver["pmid_verified"] and ver["doi_verified"] else ("PubMed" if ver["pmid_verified"] else "Crossref")
    rec = {
        "title": c["title"],
        "authors": c["authors"],
        "year": int(c["year"]),
        "journal": c["journal"],
        "doi": ver["doi"],
        "pmid": str(c["pmid"]) if c.get("pmid") else None,
        "design": c.get("design") or c["study_design"].replace("_", " "),
        "study_design": c["study_design"],
        "finding": c["finding"],
        "verified_on": f"{via}, {today}",
        "found_via": found_via["kind"] + (f": {found_via['name']}" if found_via.get("name") else ""),
        "evidence_review": review_id,
    }
    if not ver["pmid_verified"]:
        rec["finding"] = c["finding"] + " (DOI-only record: registered, backs no evidence)"
    return rec


def review(
    lib: dict[str, Any],
    proposals: dict[str, Any],
    allow: dict[str, Any],
    http: HttpGet,
    today: str,
    reverified: Optional[dict[str, dict[str, Any]]] = None,
) -> dict[str, Any]:
    """Decide every proposal. Pure over `lib` (never mutated); all network goes through `http`."""
    review_id = str(proposals.get("review_id") or f"evidence-review-{today}")
    reverified = reverified if reverified is not None else {}
    accepted: dict[str, Any] = {"citations": {}, "evidence_changes": [], "candidates": []}
    rejected: list[dict[str, Any]] = []
    backing: dict[str, list[str]] = {}  # citation id -> evidence confidences it may back in THIS review
    ops = list(proposals.get("proposals") or [])

    # existing citations: may back what their design allows if they re-verified with a PMID this run
    for cid, c in lib["citations"].items():
        ver = reverified.get(cid)
        if ver and ver["status"] == VERIFIED and ver["pmid_verified"]:
            backing[cid] = list(allow["designs"].get(_existing_design(c), {}).get("may_back") or [])

    for op in [o for o in ops if o.get("op") in ("add_citation", "correct_citation")]:
        cid = str(op.get("citation_id") or "")
        c = dict(op.get("citation") or {})
        fv = dict(op.get("found_via") or {})
        why = source_problems(c, fv, allow)
        if not re.fullmatch(r"[a-z0-9_]{3,64}", cid):
            why.append(f"citation_id {cid!r} must be snake_case")
        if op["op"] == "add_citation" and cid in lib["citations"]:
            why.append(f"{cid} is already registered — use correct_citation")
        if op["op"] == "correct_citation" and cid not in lib["citations"]:
            why.append(f"{cid} is not registered — nothing to correct")
        ver: dict[str, Any] = {}
        if not why:
            ver = verify_citation(c, http, allow)
            if ver["status"] != VERIFIED:
                why.append(f"did not verify live ({ver['status']}): " + "; ".join(ver["problems"]))
            elif not ver["doi"]:
                why.append("verified, but no DOI exists for it — the library registers a citation by DOI")
            elif c.get("study_design") in ("narrative_review", "position_stand"):
                names = {first_author_surname(a) for a in ver.get("pubmed_authors") or []} or {
                    first_author_surname(a) for a in str(c.get("authors", "")).split(",")
                }
                listed = {first_author_surname(n) for n in allow["reviewers"]["names"]}
                if not names & listed:
                    why.append(f"a {c['study_design']} is admitted only when an author is a named reviewer in the allowlist")
        if why:
            rejected.append({"op": op["op"], "id": cid, "reasons": why})
            continue
        accepted["citations"][cid] = _registered_record(cid, c, ver, fv, review_id, today)
        backing[cid] = confidence_it_may_back(c, ver, allow)

    registered = set(lib["citations"]) | set(accepted["citations"])
    for op in [o for o in ops if o.get("op") == "set_evidence"]:
        why = _evidence_problems(op, lib, registered, backing)
        if why:
            rejected.append({"op": "set_evidence", "id": f"{op.get('movement')}:{op.get('target')}", "reasons": why})
            continue
        accepted["evidence_changes"].append(_evidence_change(op, review_id, today))

    for op in [o for o in ops if o.get("op") == "add_candidate"]:
        x = copy.deepcopy(op.get("candidate") or {})
        why = _candidate_problems(op, x, lib, registered, backing)
        if why:
            rejected.append({"op": "add_candidate", "id": x.get("key"), "reasons": why})
            continue
        x["curation_note"] = (x.get("curation_note") + "; " if x.get("curation_note") else "") + (
            f"evidence review {review_id} ({today}): " + str(op.get("rationale") or "") + f" [{', '.join(op['citations'])}]"
        )
        x["hypertrophy"] = [reviews.evidence_row(_row_with_review_date(r, today)) for r in x.get("hypertrophy") or []]
        accepted["candidates"].append(x)

    for op in ops:
        if op.get("op") not in ("add_citation", "correct_citation", "set_evidence", "add_candidate"):
            rejected.append({"op": str(op.get("op")), "id": None, "reasons": ["unknown op"]})

    return {
        "review_id": review_id,
        "date": today,
        "accepted": accepted,
        "rejected": rejected,
    }


def _row_with_review_date(r: dict[str, Any], today: str) -> dict[str, Any]:
    r = dict(r)
    r.setdefault("evidence_confidence", "none_reviewed")
    r["last_reviewed"] = today if r["evidence_confidence"] != "none_reviewed" or r.get("citations") else "unreviewed"
    return r


def _backing_problems(confidence: str, cites: list[str], registered: set[str], backing: dict[str, list[str]]) -> list[str]:
    why = [f"citation {c} is not registered (or was rejected in this review)" for c in cites if c not in registered]
    if confidence != "none_reviewed" and not why and not any(confidence in backing.get(c, []) for c in cites):
        why.append(
            f"no cited reference may back evidence {confidence}: it needs a citation that verified live with a PMID this run, "
            "abstract_read, and a study design the allowlist lets back that confidence — the row stays none_reviewed"
        )
    return why


def _adjust_problems(op: dict[str, Any], confidence: Any, cites: list[str]) -> list[str]:
    """A one-band move off the rubric tier (#5857): only a direct trial, only +/-1, citing one of the op's citations."""
    adj = op.get("adjust")
    if adj is None:
        return []
    row = {"evidence_confidence": confidence, "citations": cites, "evidence_adjustment": adj}
    return [f"adjust: {w}" for w in quality_rubric.adjustment_problems(row)]


def _evidence_problems(op: dict[str, Any], lib: dict[str, Any], registered: set[str], backing: dict[str, list[str]]) -> list[str]:
    why: list[str] = []
    mv = lib["movements"].get(op.get("movement"))
    confidence = op.get("evidence_confidence")
    cites = list(op.get("citations") or [])
    if mv is None:
        why.append(f"movement {op.get('movement')!r} is not in the library")
    if "tier" in op:
        why.append("the quality tier is derived by the rubric (#5857), never proposed — propose evidence_confidence / adjust")
    if confidence not in xl.EVIDENCE_CONFIDENCE:
        why.append(f"evidence_confidence {confidence!r} not in {xl.EVIDENCE_CONFIDENCE}")
    if not op.get("target"):
        why.append("no target")
    if not cites:
        why.append("every proposed change carries its citation")
    if not op.get("rationale"):
        why.append("no rationale")
    if confidence != "none_reviewed" and op.get("abstract_read") is not True:
        why.append("a reviewed evidence change needs abstract_read: true")
    return why + _adjust_problems(op, confidence, cites) + _backing_problems(str(confidence), cites, registered, backing)


def _evidence_change(op: dict[str, Any], review_id: str, today: str) -> dict[str, Any]:
    out = {
        "movement": op["movement"],
        "target": op["target"],
        "evidence_confidence": op["evidence_confidence"],
        "citations": list(op["citations"]),
        "last_reviewed": today,
        "note": f"evidence review {review_id}: {op['rationale']}",
    }
    if op.get("adjust"):
        out["evidence_adjustment"] = {k: op["adjust"][k] for k in ("bands", "citation", "why")}
    return out


def _candidate_problems(op: dict[str, Any], x: dict[str, Any], lib: dict[str, Any], registered: set[str], backing: dict) -> list[str]:
    why: list[str] = []
    key = x.get("key")
    if not key or not re.fullmatch(r"[a-z0-9_]{3,64}", str(key)):
        why.append(f"candidate key {key!r} must be snake_case")
    elif key in lib["movements"]:
        why.append(f"{key} is already in the library")
    if not x.get("title"):
        why.append("no title")
    tid = x.get("template_id")
    if tid and any(str(e.get("template_id") or "").upper() == str(tid).upper() for e in lib["movements"].values()):
        why.append(f"template {tid} is already a library movement")
    if not tid and not x.get("template_note"):
        why.append("template_id null needs a template_note")
    if not op.get("citations"):
        why.append("every proposed change carries its citation")
    if not op.get("rationale"):
        why.append("no rationale")
    why += [p for p in _backing_problems("none_reviewed", list(op.get("citations") or []), registered, backing)]
    for r in x.get("hypertrophy") or []:
        conf = str(r.get("evidence_confidence") or "none_reviewed")
        if "tier" in r:
            why.append("a candidate row's quality tier is derived by the rubric (#5857), never proposed")
        why += _backing_problems(conf, list(r.get("citations") or []), registered, backing)
        why += _adjust_problems({"adjust": r.get("evidence_adjustment")}, conf, list(r.get("citations") or []))
        if conf != "none_reviewed" and op.get("abstract_read") is not True:
            why.append("a reviewed evidence row needs abstract_read: true")
    for k in ("source", "history", "fallbacks", "availability"):
        if k in x:
            why.append(f"`{k}` is derived by the builder, never proposed")
    return why


def auto_downgrades(lib: dict[str, Any], reverified: dict[str, dict[str, Any]], review_id: str, today: str) -> list[dict[str, Any]]:
    """Reviewed rows whose EVERY citation definitively failed re-verification -> `none_reviewed` (any evidence band
    dropped; the quality tier falls back to the rubric's). A mismatch or an unreachable registry never downgrades (the
    first is a correction to propose, the second is the network)."""
    out = []
    for key, e in lib["movements"].items():
        for r in e.get("hypertrophy") or []:
            cites = r.get("citations") or []
            reviewed = r.get("evidence_confidence") not in (None, "none_reviewed")
            if reviewed and cites and all((reverified.get(c) or {}).get("status") in DEFINITIVE_FAILURES for c in cites):
                why = "; ".join(f"{c}: {reverified[c]['status']}" for c in cites)
                out.append(
                    {
                        "movement": key,
                        "target": r["target"],
                        "evidence_confidence": "none_reviewed",
                        "citations": [],
                        "last_reviewed": "unreviewed",
                        "note": f"evidence review {review_id} ({today}): downgraded — its citation no longer verifies ({why})",
                    }
                )
    return out


# ── applying a review (the same functions the builder uses) ─────────────────────────────────────────────────────


def _builder():
    import build_exercise_library as b  # deploy/ — imports the curation and the lambda rules; no AWS at import

    return b


def _bump_patch(v: str) -> str:
    a, b_, c = (int(x) for x in str(v).split("."))
    return f"{a}.{b_}.{c + 1}"


def apply_review(lib: dict[str, Any], decided: dict[str, Any]) -> dict[str, Any]:
    """A NEW library dict with the accepted changes applied; the input is untouched. Raises ValueError when the result
    fails the library's own schema check (the PR is never opened on an invalid library)."""
    b = _builder()
    out = copy.deepcopy(lib)
    acc = decided["accepted"]
    out["citations"] = {**out["citations"], **copy.deepcopy(acc["citations"])}
    mv = out["movements"]
    for x in acc["candidates"]:
        tid = str(x.get("template_id") or "").upper()
        base = b.derive(tid, x["title"], {"primary_muscle": (x.get("target") or {}).get("primary")})
        e = b._merge(base, x)
        e.update({"source": "expansion", "template_id": x.get("template_id")})
        e = b._merge(e, b.cur.CURATED.get(tid) or {}) if tid else e
        gates = list(x.get("gates") or []) + list((b.cur.CURATED.get(tid) or {}).get("gates") or [])
        gates = list(dict.fromkeys(gates + b.auto_gates(e)))
        e["gates"] = [g for g in gates if g in b.cur.GATES and b.cur.GATES[g].get("applies_to") != "all"]
        e.setdefault("not_for_you_now", None)
        e["job"], e["pattern"] = b.job_and_pattern(e)  # rubric v2 scores by job (#5857)
        mv[x["key"]] = e
    missing = reviews.apply_evidence_changes(mv, acc["evidence_changes"])
    if missing:
        raise ValueError(f"evidence change for a movement not in the library: {missing}")
    reviews.finalize_tiers(mv)  # the quality tier re-derived from the rubric (+ at most one recorded band, #5857)
    if acc["candidates"]:
        last = (out.get("_provenance") or {}).get("history_through") or "1970-01-01"
        used_eq = sorted({x for e in mv.values() for x in e["equipment"]})
        inventory, cutoff = b.home_gym_inventory(mv, {"last": last}, used_eq)
        out["gym_inventory"]["items"] = inventory
        for e in mv.values():
            e["availability"] = {xl.LOCATION_ID: b.movement_availability(e, inventory, cutoff)}
        fidx = xl.fallback_index(out)
        for key, e in mv.items():
            e["fallbacks"] = [{"movement_id": k, "reason": r} for k, r in xl.fallback_candidates(out, key, fidx)[: b.MAX_FALLBACKS]]
        for key in list(mv):
            mv[key] = b._ordered(mv[key])
    prov = out.setdefault("_provenance", {})
    prov["movements"] = len(mv)
    prov["by_source"] = dict(sorted(_count(e["source"] for e in mv.values()).items()))
    tiers = _count(r["tier"] for e in mv.values() for r in e["hypertrophy"])
    conf = _count(r["evidence_confidence"] for e in mv.values() for r in e["hypertrophy"])
    prov["hypertrophy_rows_by_tier"] = {t: tiers.get(t, 0) for t in quality_rubric.QUALITY_TIERS}
    prov["hypertrophy_rows_by_evidence_confidence"] = {c: conf.get(c, 0) for c in quality_rubric.EVIDENCE_CONFIDENCE}
    n = len(acc["citations"]), len(acc["evidence_changes"]), len(acc["candidates"])
    out["version"] = _bump_patch(out["version"])
    out["change_log"] = list(out["change_log"]) + [
        {
            "version": out["version"],
            "date": decided["date"],
            "by": f"evidence review {decided['review_id']} (scripts/library_evidence_review.py, #5778; accepted by the owner's merge)",
            "what": f"{n[0]} citation(s) registered or corrected, {n[1]} evidence change(s), {n[2]} new candidate(s); every "
            "citation verified live (Crossref DOI / PubMed PMID) on the review date.",
        }
    ]
    errors = xl.validate(out)
    if errors:
        raise ValueError(f"{len(errors)} schema errors after applying the review (first: {errors[0]})")
    return out


def _count(it) -> dict[str, int]:
    out: dict[str, int] = {}
    for x in it:
        out[x] = out.get(x, 0) + 1
    return out


def ledger_record(decided: dict[str, Any]) -> dict[str, Any]:
    acc = decided["accepted"]
    return {
        "review_id": decided["review_id"],
        "date": decided["date"],
        "citations": acc["citations"],
        "evidence_changes": acc["evidence_changes"],
        "candidates": acc["candidates"],
    }


def has_changes(decided: dict[str, Any]) -> bool:
    acc = decided["accepted"]
    return bool(acc["citations"] or acc["evidence_changes"] or acc["candidates"])


def _dump(obj: Any) -> str:
    return json.dumps(obj, indent=1, ensure_ascii=False) + "\n"


def library_diff(before: dict[str, Any], after: dict[str, Any], ledger_before: dict[str, Any], ledger_after: dict[str, Any]) -> str:
    d1 = difflib.unified_diff(_dump(before).splitlines(True), _dump(after).splitlines(True), "a/" + LIBRARY_REL, "b/" + LIBRARY_REL)
    d2 = difflib.unified_diff(
        _dump(ledger_before).splitlines(True), _dump(ledger_after).splitlines(True), "a/" + LEDGER_REL, "b/" + LEDGER_REL
    )
    return "".join(d1) + "".join(d2)


# ── discovery: a READING list, never a change ───────────────────────────────────────────────────────────────────


def discover(lib: dict[str, Any], since: str, http: HttpGet, per_target: int = DISCOVER_PER_TARGET) -> list[dict[str, Any]]:
    """PubMed trials / meta-analyses since `since` naming a library primary target and hypertrophy. Deterministic
    query terms built from the library's own targets; excludes PMIDs already registered."""
    known = {str(c.get("pmid")) for c in lib["citations"].values() if c.get("pmid")}
    targets = sorted({(e.get("target") or {}).get("primary") for e in lib["movements"].values()} - {None, "unknown", "other", "cardio"})
    found: dict[str, str] = {}
    for t in targets:
        words = t.replace("_", " ")
        term = (
            f'("{words}"[tiab]) AND (hypertrophy[tiab] OR "muscle thickness"[tiab] OR "muscle volume"[tiab] OR '
            f'"cross-sectional area"[tiab]) AND ("resistance training"[tiab] OR "strength training"[tiab]) AND '
            "(randomized controlled trial[pt] OR clinical trial[pt] OR meta-analysis[pt] OR systematic review[pt])"
        )
        url = ESEARCH_URL.format(n=per_target, since=since.replace("-", "/"), term=urllib.parse.quote(term))
        status, body = http(url)
        for pmid in ((body or {}).get("esearchresult") or {}).get("idlist") or [] if status == 200 else []:
            if pmid not in known:
                found.setdefault(pmid, t)
    if not found:
        return []
    status, body = http(ESUMMARY_URL.format(ids=",".join(sorted(found))))
    res = (body or {}).get("result") or {} if status == 200 else {}
    out = []
    for pmid in sorted(found):
        r = res.get(pmid) or {}
        out.append(
            {
                "pmid": pmid,
                "target": found[pmid],
                "title": r.get("title"),
                "first_author": ((r.get("authors") or [{}])[0]).get("name"),
                "year": _year_prefix(r.get("pubdate")),
                "journal": r.get("fulljournalname"),
                "pubtypes": r.get("pubtype") or [],
                "doi": next((a.get("value") for a in r.get("articleids") or [] if a.get("idtype") == "doi"), None),
                "status": "to_read — read the abstract, then propose (or not) in a proposal file",
            }
        )
    return out


# ── the PR (never merges; never pushes main) ────────────────────────────────────────────────────────────────────

Runner = Callable[..., "subprocess.CompletedProcess[str]"]
PROTECTED_BRANCHES = ("main", "master", "HEAD")


def _run(runner: Runner, args: list[str], cwd: str, stdin: Optional[str] = None) -> str:
    if args[:2] == ["gh", "pr"] and len(args) > 2 and args[2] == "merge":
        raise SystemExit("refusing: this script never merges")
    if args[0] == "git" and args[1:2] == ["push"] and any(a.split(":")[-1] in PROTECTED_BRANCHES or a.endswith("/main") for a in args[2:]):
        raise SystemExit(f"refusing to push a protected branch: {args}")
    cp = runner(args, cwd=cwd, input=stdin, capture_output=True, text=True)
    if cp.returncode != 0:
        raise SystemExit(f"{' '.join(args[:3])} failed: {(cp.stderr or cp.stdout).strip()}")
    return (cp.stdout or "").strip()


def pr_body(decided: dict[str, Any], issue: int, downgrades: list[dict[str, Any]], reverified: dict[str, dict[str, Any]]) -> str:
    acc = decided["accepted"]
    lines = [
        f"Per-block evidence review `{decided['review_id']}` ({decided['date']}), proposed by `scripts/library_evidence_review.py`.",
        "",
        "The owner accepts these changes by merging; the script never merges. Every citation below resolved LIVE on the review "
        "date (Crossref DOI and/or PubMed PMID, title + first author + year matched) and came from the allow-listed source set "
        "(`config/evidence_source_allowlist.json`).",
        "",
        "## Citations",
    ]
    lines += [
        f"- `{cid}` — {c['authors'].split(',')[0]} {c['year']}, doi:{c['doi']}, pmid:{c['pmid']} ({c['verified_on']})"
        for cid, c in acc["citations"].items()
    ] or ["- none"]
    lines += ["", "## Evidence changes (the quality tier is re-derived by the rubric, #5857)"]
    lines += [
        f"- `{t['movement']}` / {t['target']} -> **{t['evidence_confidence']}**"
        + (f" (moves {t['evidence_adjustment']['bands']:+d} band)" if t.get("evidence_adjustment") else "")
        + f" [{', '.join(t['citations']) or 'no citation'}] — {t['note']}"
        for t in acc["evidence_changes"]
    ] or ["- none"]
    lines += ["", "## New candidates"]
    lines += [f"- `{x['key']}` — {x['title']}" for x in acc["candidates"]] or ["- none"]
    lines += ["", "## Rejected proposals"]
    lines += [f"- {r['op']} `{r['id']}`: {'; '.join(r['reasons'])}" for r in decided["rejected"]] or ["- none"]
    lines += ["", "## Existing citations re-verified"]
    lines += [f"- `{cid}`: {v['status']}" + (f" — {'; '.join(v['problems'])}" if v["problems"] else "") for cid, v in reverified.items()]
    if downgrades:
        lines += [
            "",
            f"{len(downgrades)} row(s) above were auto-downgraded to none_reviewed because every citation behind them is gone or retracted.",
        ]
    lines += [
        "",
        "## Post-merge",
        "No deploy: the library is a repo-generated config read only by the selection engine. A later "
        "`deploy/build_exercise_library.py --write` re-applies this review from `deploy/exercise_library_reviews.json`.",
        "",
        "**Closure class:** product — a library content change the owner reviews in the diff.",
        "",
        f"Refs #{issue}",
    ]
    return "\n".join(lines) + "\n"


def open_pr(
    decided: dict[str, Any],
    issue: int,
    reverified: dict[str, dict[str, Any]],
    downgrades: list[dict[str, Any]],
    runner: Runner = subprocess.run,
    make_lane: Optional[Callable[[int, str], str]] = None,
    out: Callable[[str], None] = print,
) -> str:
    """Lane worktree off origin/main -> apply -> commit (deploy/agent_commit.sh) -> push the lane branch -> `gh pr create`. Returns the PR
    URL. Never merges; never pushes main."""
    if make_lane is None:
        import lane_worktree

        def make_lane(n: int, slug: str) -> str:
            return str(lane_worktree.new_lane(n, slug))

    slug = "library-evidence-review-" + re.sub(r"[^a-z0-9]+", "-", decided["review_id"].lower()).strip("-")
    lane = make_lane(issue, slug)
    branch = _run(runner, ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=lane)
    if branch in PROTECTED_BRANCHES:
        raise SystemExit(f"refusing: the lane is on {branch}")
    with open(os.path.join(lane, LIBRARY_REL), encoding="utf-8") as f:
        lib = json.load(f)
    ledger = reviews.load_ledger(os.path.join(lane, LEDGER_REL))
    new_lib = apply_review(lib, decided)
    ledger["reviews"] = list(ledger["reviews"]) + [ledger_record(decided)]
    with open(os.path.join(lane, LIBRARY_REL), "w", encoding="utf-8") as f:
        f.write(_dump(new_lib))
    with open(os.path.join(lane, LEDGER_REL), "w", encoding="utf-8") as f:
        f.write(_dump(ledger))
    title = f"feat(training): exercise library evidence review {decided['review_id']} (Refs #{issue})"
    # agent_commit.sh --push is the repo's ONE landing path (#3528): on a lane branch it commits the named paths and
    # pushes that branch; it would gate a push to main, which this lane never is (checked above).
    _run(runner, ["bash", "deploy/agent_commit.sh", "--push", title, LIBRARY_REL, LEDGER_REL], cwd=lane)
    local = _run(runner, ["git", "rev-parse", "HEAD"], cwd=lane)
    remote = _run(runner, ["git", "ls-remote", "origin", f"refs/heads/{branch}"], cwd=lane).split()[:1]
    if remote != [local]:
        raise SystemExit(f"push did not land: origin/{branch} is {remote}, local HEAD is {local}")
    url = _run(
        runner,
        ["gh", "pr", "create", "--base", "main", "--head", branch, "--title", title, "--body-file", "-"],
        cwd=lane,
        stdin=pr_body(decided, issue, downgrades, reverified),
    )
    out(f"PR opened for the owner (not merged): {url}")
    out(f"lane {lane} stays locked; release it after the merge: python3 scripts/lane_worktree.py release {issue}")
    return url


# ── CLI ─────────────────────────────────────────────────────────────────────────────────────────────────────────


def _last_review_date(ledger: dict[str, Any]) -> str:
    dates = [r.get("date") for r in ledger.get("reviews") or [] if r.get("date")]
    if dates:
        return max(dates)
    import exercise_library_curation as cur

    return cur.REVIEWED_ON


def run(
    argv: Optional[list[str]] = None,
    http: HttpGet = urllib_get,
    root: str = REPO_ROOT,
    out=print,
    runner: Runner = subprocess.run,
    make_lane=None,
) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--proposals", help="proposal JSON (see the module docstring)")
    ap.add_argument("--review-id")
    ap.add_argument("--discover", action="store_true", help="PubMed reading list since --since (never a change)")
    ap.add_argument("--since", help="YYYY-MM-DD for --discover (default: the last review date)")
    ap.add_argument("--out", help="write proposal.json + library.diff into this directory (keep it OUTSIDE the repo)")
    ap.add_argument("--open-pr", action="store_true", help="open the PR for the owner (never merges)")
    ap.add_argument("--issue", type=int, help="the issue the PR refs (required with --open-pr)")
    ap.add_argument("--today", help="review date YYYY-MM-DD (default: today, UTC)")
    args = ap.parse_args(argv)
    if args.open_pr and not args.issue:
        out("--open-pr needs --issue N (the PR says Refs #N)")
        return 2

    today = args.today or _dt.datetime.now(_dt.timezone.utc).date().isoformat()
    allow = load_allowlist(root)
    with open(os.path.join(root, LIBRARY_REL), encoding="utf-8") as f:
        lib = json.load(f)
    ledger = reviews.load_ledger(os.path.join(root, LEDGER_REL))
    proposals: dict[str, Any] = {"proposals": []}
    if args.proposals:
        with open(args.proposals, encoding="utf-8") as f:
            proposals = json.load(f)
    if args.review_id:
        proposals["review_id"] = args.review_id

    reverified = reverify_existing(lib, http, allow)
    decided = review(lib, proposals, allow, http, today, reverified)
    downgrades = auto_downgrades(lib, reverified, decided["review_id"], today)
    proposed = {(t["movement"], t["target"]) for t in decided["accepted"]["evidence_changes"]}
    decided["accepted"]["evidence_changes"] += [d for d in downgrades if (d["movement"], d["target"]) not in proposed]
    if args.discover:
        decided["literature_to_read"] = discover(lib, args.since or _last_review_date(ledger), http)
    decided["reverification"] = reverified

    failed = {c: v for c, v in reverified.items() if v["status"] != VERIFIED}
    out(f"re-verified {len(reverified)} existing citations: {len(reverified) - len(failed)} verified")
    for c, v in failed.items():
        out(f"  {c}: {v['status']} — {'; '.join(v['problems'])}")
    acc = decided["accepted"]
    out(
        f"accepted: {len(acc['citations'])} citation(s), {len(acc['evidence_changes'])} evidence change(s) "
        f"({len(downgrades)} auto-downgrade), {len(acc['candidates'])} candidate(s); rejected: {len(decided['rejected'])}"
    )
    for r in decided["rejected"]:
        out(f"  REJECTED {r['op']} {r['id']}: {'; '.join(r['reasons'])}")
    for item in decided.get("literature_to_read") or []:
        out(f"  to read: PMID {item['pmid']} ({item['target']}) {item['title']}")

    diff = ""
    if has_changes(decided):
        new_ledger = copy.deepcopy(ledger)
        new_ledger["reviews"] = list(new_ledger["reviews"]) + [ledger_record(decided)]
        diff = library_diff(lib, apply_review(lib, decided), ledger, new_ledger)
        out(diff)
    if args.out:
        os.makedirs(args.out, exist_ok=True)
        with open(os.path.join(args.out, "proposal.json"), "w", encoding="utf-8") as f:
            f.write(_dump(decided))
        with open(os.path.join(args.out, "library.diff"), "w", encoding="utf-8") as f:
            f.write(diff)
        out(f"wrote {os.path.join(args.out, 'proposal.json')} and library.diff")
    if args.open_pr:
        if not has_changes(decided):
            out("nothing accepted — no PR")
        else:
            open_pr(decided, args.issue, reverified, downgrades, runner=runner, make_lane=make_lane, out=out)
    elif not args.out:
        out("dry-run — nothing written (pass --out DIR for the proposal file, --open-pr --issue N for the PR)")
    return 1 if any(v["status"] in DEFINITIVE_FAILURES for v in reverified.values()) else 0


if __name__ == "__main__":
    raise SystemExit(run())
