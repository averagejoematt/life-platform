#!/usr/bin/env python3
"""
v4_proof.py — build-time static "proof" blocks for the JS-shell surfaces (#729/#730).

The scorecard (/coaching/scorecard/) and chronicle (/story/chronicle/) pages are
pure client-rendered app shells: to a crawler, an LLM answer engine, or a no-JS
skeptic they are empty ("··/100", no post list). The platform's whole thesis —
falsifiable, graded, public N=1 science — is therefore invisible to anyone who
skims (R21 Finding 2).

This bakes the current key numbers + the honest empty-state sentence + the dated
chronicle post list into the SERVED HTML at build time (the committed-static-site
generation step — the same "generate then serve" pattern as the OG images and
public_stats.json). The blocks live inside <noscript>, so:
  - `curl … | grep` and non-JS crawlers/LLM scrapers read them straight out of the
    served HTML (the #730 acceptance test),
  - a no-JS browser renders them (#729: the honest sentence is carried in no-JS HTML),
  - a JS browser gets the rich interactive view instead (JS enhances, never
    duplicates — the noscript is inert once scripts run).

Every block carries an honest "as of" stamp: the staleness IS the integrity
(ADR-104 behavioral-absence semantics, ADR-105 uncertainty-on-every-claim). Nothing
is ever fabricated — if neither the live API nor the committed snapshot has a value,
the block is simply omitted and the JS view still renders.

Data sources (each with a committed-snapshot fallback so an offline/CI build still
bakes last-known-good numbers rather than blanks):
  - scorecard: GET /api/predictions        (overall confirmed/refuted/pending/decided)
  - chronicle: GET /journal/posts.json      (the dated weekly post list)
  - fallback:  scripts/proof_snapshot.json
"""
from __future__ import annotations

import datetime
import json
import urllib.request
from pathlib import Path

SITE = "https://averagejoematt.com"
SNAPSHOT = Path(__file__).resolve().parent / "proof_snapshot.json"


def _today() -> str:
    return datetime.date.today().isoformat()


def _fetch_json(path: str, timeout: int = 8):
    """GET {SITE}{path} as JSON, or None on any failure (offline CI, API down)."""
    try:
        req = urllib.request.Request(
            f"{SITE}{path}",
            headers={"accept": "application/json", "user-agent": "v4-proof-build"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 — fixed trusted host
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return None


def _snapshot() -> dict:
    try:
        return json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _esc(s) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


# ── data loaders ─────────────────────────────────────────────────────────────


def load_scorecard() -> dict:
    """Overall prediction scorecard from the live API, else the committed snapshot."""
    d = _fetch_json("/api/predictions?limit=1")
    if isinstance(d, dict) and isinstance(d.get("overall"), dict):
        o = d["overall"]
        snap = _snapshot().get("scorecard", {})
        return {
            "total": int(o.get("total", 0)),
            "confirmed": int(o.get("confirmed", 0)),
            "refuted": int(o.get("refuted", 0)),
            "decided": int(o.get("decided", 0)),
            "pending": int(o.get("pending", 0)),
            "inconclusive": int(o.get("inconclusive", 0)),
            "accuracy_pct": o.get("accuracy_pct"),
            # live-since is not on the API; carry it from the snapshot (experiment genesis).
            "evaluator_live_since": snap.get("evaluator_live_since", ""),
            "as_of": _today(),
            "source": "live",
        }
    return _snapshot().get("scorecard", {})


def load_chronicle() -> list:
    """Dated chronicle post list from /journal/posts.json, else the committed snapshot."""
    d = _fetch_json("/journal/posts.json")
    posts = d.get("posts") if isinstance(d, dict) else (d if isinstance(d, list) else None)
    if posts:
        out = [
            {
                "date": p.get("date", ""),
                "title": p.get("title", ""),
                "url": p.get("url", "") or "/story/chronicle/",
                "label": p.get("label", ""),
            }
            for p in posts
            if p.get("title")
        ]
        out.sort(key=lambda p: p.get("date", ""), reverse=True)
        return out
    return _snapshot().get("chronicle", [])


# ── render helpers (return "" rather than fabricate on missing data) ─────────


def scorecard_block_html(sc: dict) -> str:
    """The scorecard honest empty-state (#729) / static summary (#730).

    Zero graded -> the ADR-104 behavioral-absence sentence ('evaluator live since
    X; N pending; 0 graded yet'). Once the evaluator resolves its first window the
    copy flips automatically to the hit-rate at the next build.
    """
    if not sc:
        return ""
    decided = int(sc.get("decided", 0))
    pending = int(sc.get("pending", 0))
    total = int(sc.get("total", 0))
    as_of = sc.get("as_of", "")
    live_since = sc.get("evaluator_live_since", "")

    if decided > 0:
        acc = sc.get("accuracy_pct")
        headline = f"{decided} graded · {acc:.0f}% hit-rate" if isinstance(acc, (int, float)) else f"{decided} graded"
        sentence = f"{decided} predictions graded, {pending} still open, {total} tracked in total."
    else:
        headline = "0 graded yet"
        since = f"Evaluator live since {_esc(live_since)}. " if live_since else "Evaluator live. "
        sentence = (
            f"{since}{pending} predictions pending; 0 graded yet — the deterministic evaluator "
            f"resolves each prediction against the data when its evaluation window elapses."
        )

    return (
        '<noscript><section class="proof-static dx-prose" aria-label="Scorecard summary">'
        f'<p class="label">The board\'s falsifiable track record — as of {_esc(as_of)}</p>'
        f"<p><strong>{_esc(headline)}</strong></p>"
        f"<p>{sentence}</p>"
        "</section></noscript>"
    )


def chronicle_list_html(posts: list, limit: int = 20) -> str:
    """A dated, crawlable chronicle post list (#730). Newest first."""
    if not posts:
        return ""
    rows = []
    for p in posts[:limit]:
        date = _esc(p.get("date", ""))
        title = _esc(p.get("title", ""))
        url = _esc(p.get("url", "") or "/story/chronicle/")
        label = p.get("label", "")
        suffix = f" · {_esc(label)}" if label else ""
        rows.append(f'<li><a href="{url}"><time datetime="{date}">{date}</time> — {title}</a>{suffix}</li>')
    return (
        '<noscript><section class="proof-static dx-prose" aria-label="Chronicle posts">'
        f'<p class="label">The weekly chronicle — {len(posts)} posts, newest first (as of {_esc(_today())})</p>'
        f'<ul>{"".join(rows)}</ul>'
        "</section></noscript>"
    )
