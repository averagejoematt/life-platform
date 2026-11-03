#!/usr/bin/env python3
"""scripts/www_verbatim.py — the dates-in-words rule, quote-aware (#5609; owner ruling 2026-11-02).

A reader surface writes dates in words. ONE narrow exception: a coach's words, quoted verbatim, keep any
ISO date they carry. The exemption is keyed on markup alone —

    <q data-verbatim="coach" …>…</q>   or   <blockquote data-verbatim="coach" …>…</blockquote>

— holding text and <time datetime="X">X</time> only. Everything else on the page (authored copy,
headings, <title>, summaries, glosses, corrections) is still held to dates in words.

Structural rules (each a defect on its own, so the exemption cannot be widened by markup):
  * `data-verbatim` on any element other than <q>/<blockquote>, or with a value other than "coach";
  * a verbatim element holding any tag other than <time> (no nested quote, link, span or authored copy);
  * a <time> inside one whose text differs from its datetime (the quoted characters are never rewritten);
  * a verbatim element inside <h1>–<h6> or <title> (a heading is authored; a quote sits beneath it).
Snapshot rule (when the snapshot is given — the live scan): each verbatim element's text must be a coach
string the snapshot carries (a claim, a coach line, a call chip), whole or as a word-boundary clip of it.

Pure: no network, no clock. One rule, two callers — tests/web_preview_gate.py (rendered fixture build)
and scripts/check_www_build.py scan() (every build, the live root deploy included).
"""

from __future__ import annotations

import html as _html
import json
import os
import re

ISO_DATE = re.compile(r"\b20\d\d-\d\d-\d\d\b")
PUBLISHED_BODY = re.compile(r"<div data-published-body[^>]*>[\s\S]*?</div>\s*(?=</article>)", re.IGNORECASE)
VERBATIM = re.compile(r"<(q|blockquote)\b([^>]*?\bdata-verbatim=\"coach\"[^>]*)>([\s\S]*?)</\1\s*>", re.IGNORECASE)
ANY_VERBATIM_TAG = re.compile(r"<([a-z][a-z0-9-]*)\b[^>]*\bdata-verbatim(?:=\"([^\"]*)\")?[^>]*>", re.IGNORECASE)
INNER_TAG = re.compile(r"</?([a-z][a-z0-9-]*)\b[^>]*>", re.IGNORECASE)
TIME_EL = re.compile(r"<time\b[^>]*\bdatetime=\"([^\"]*)\"[^>]*>([\s\S]*?)</time>", re.IGNORECASE)
HEADING = re.compile(r"<(h[1-6]|title)\b[^>]*>([\s\S]*?)</\1\s*>", re.IGNORECASE)
TAG = re.compile(r"<[^>]+>")


def _norm(s: str) -> str:
    return " ".join(_html.unescape(s).split())


def strip_verbatim(html: str) -> str:
    """The page with every well-formed verbatim element's CONTENT removed (the element boundary is kept as a space)."""
    return VERBATIM.sub(" ", html)


def structural_issues(html: str, rel: str) -> list[str]:
    out = []
    for m in ANY_VERBATIM_TAG.finditer(html):
        tag, val = m.group(1).lower(), m.group(2)
        if tag not in ("q", "blockquote"):
            out.append(f"{rel}: data-verbatim on <{tag}> (only <q> or <blockquote> may carry a verbatim quotation)")
        elif val != "coach":
            out.append(f'{rel}: data-verbatim={val!r} (the one sanctioned value is "coach")')
    for m in VERBATIM.finditer(html):
        inner = m.group(3)
        bad = sorted({t.group(1).lower() for t in INNER_TAG.finditer(inner)} - {"time"})
        if bad:
            out.append(
                f"{rel}: a verbatim quotation holds <{'>, <'.join(bad)}> (text and <time> only): {_norm(TAG.sub(' ', inner))[:60]!r}"
            )
        for t in TIME_EL.finditer(inner):
            if t.group(1) != _norm(t.group(2)):
                out.append(
                    f"{rel}: <time datetime={t.group(1)!r}> inside a quotation reads {_norm(t.group(2))!r} — the quoted characters were rewritten"
                )
    for h in HEADING.finditer(html):
        if "data-verbatim" in h.group(2):
            out.append(f"{rel}: a verbatim quotation inside <{h.group(1).lower()}> (headings are authored; the quote sits beneath)")
    return out


def iso_issues(html: str, rel: str) -> list[str]:
    """ISO dates OUTSIDE published bodies and verbatim quotations — the dates-in-words rule."""
    text = TAG.sub(" ", strip_verbatim(PUBLISHED_BODY.sub(" ", html)))
    hits = list(dict.fromkeys(ISO_DATE.findall(text)))
    return [f"{rel}: an ISO date outside a verbatim quotation (dates are written in words): {', '.join(hits[:5])}"] if hits else []


def verbatim_strings(snapshot_dir: str) -> set[str]:
    """Every coach string the snapshot publishes verbatim — the set a page's quotations must come from."""
    out: set[str] = set()

    def load(name):
        try:
            with open(os.path.join(snapshot_dir, name), encoding="utf-8") as fh:
                d = json.load(fh)
        except (OSError, ValueError):
            return []
        return d if isinstance(d, list) else d.get("items", []) if isinstance(d, dict) else []

    held: set[str] = set()  # a withheld claim's chip carries the hold's own sentence: authored copy, never a quotation
    for p in load("predictions.json"):
        if p.get("claim_withheld"):
            held.add(p.get("id"))
        elif p.get("claim"):
            out.add(_norm(p["claim"]))
    for d in load("disagreements.json"):
        out.update(_norm(d[k]) for k in ("claim_a", "claim_b") if d.get(k))
    for d in load("days.json"):
        out.update(_norm(x["text"]) for x in d.get("coach_lines") or [] if x.get("text"))
        for key, field in (("calls_settled", "claim_short"), ("calls_open", "text")):
            out.update(_norm(x[field]).rstrip("…") for x in d.get(key) or [] if x.get(field) and x.get("prediction_id") not in held)
    for e in load("editions.json"):
        lines = ((((e.get("blocks") or {}).get("coach_lines") or {}).get("data")) or {}).get("lines") or []
        out.update(_norm(x["text"]) for x in lines if isinstance(x, dict) and x.get("text"))
    return out


def provenance_issues(html: str, rel: str, allowed: set[str]) -> list[str]:
    out = []
    for m in VERBATIM.finditer(html):
        said = _norm(TAG.sub("", m.group(3)))
        if said and not any(a == said or a.startswith(said) for a in allowed):
            out.append(f"{rel}: a verbatim quotation the snapshot never carried (authored copy cannot borrow the exemption): {said[:60]!r}")
    return out


def page_issues(html: str, rel: str, allowed: set[str] | None = None) -> list[str]:
    issues = structural_issues(html, rel) + iso_issues(html, rel)
    if allowed is not None:
        issues += provenance_issues(html, rel, allowed)
    return issues


# ── self-test: the rule must be able to fail (CHARTER §paved roads) — pure, runs on every scan ────────────
_QUOTE = "Recovery will soften to roughly 59% tomorrow (from 73% on 2026-09-12)."


def self_test() -> list[str]:
    """Planted cases → the verdict each must get. Returns the cases the rule got WRONG ([] = it can fail and pass)."""
    allowed = {_QUOTE}
    timed = _QUOTE.replace("2026-09-12", '<time datetime="2026-09-12">2026-09-12</time>')
    q = f'<q data-verbatim="coach">{timed}</q>'
    cases = (
        ("an ISO date in authored copy", "<p>Planted on 2031-01-02.</p>", True),
        ("an ISO date in a correction", '<p class="correction" role="note">Correction: planted on 2031-01-03.</p>', True),
        ("an ISO date in <title>", "<title>Planted 2031-01-05</title>", True),
        ("a quote inside a heading", f"<h1>{q}</h1>", True),
        ("a borrowed exemption", '<q data-verbatim="coach">Authored words on 2031-01-04.</q>', True),
        ("a <span> inside a quote", f'<q data-verbatim="coach"><span>{_QUOTE}</span></q>', True),
        ("a rewritten <time>", '<q data-verbatim="coach">from 73% on <time datetime="2026-09-12">12 September</time></q>', True),
        ("data-verbatim on a <span>", f'<span data-verbatim="coach">{_QUOTE}</span>', True),
        ("the gloss repeating the ISO form", f'{q}<span class="gloss" data-quote-gloss> [2026-09-12]</span>', True),
        ("the sanctioned quotation", f"<p>Amara Patel: {q}</p>", False),
        ("the sanctioned quotation, clipped", '<q data-verbatim="coach">Recovery will soften to roughly 59%</q>…', False),
    )
    return [name for name, html, must_fail in cases if bool(page_issues(html, "self-test", allowed)) != must_fail]
