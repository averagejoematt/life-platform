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
  - cockpit:   GET /api/character           (the live level + tier + pillar scores — #788)
  - coaching:  GET /api/coaching-dashboard   (the board's read — weekly priority + each coach's read — #804)
  - fallback:  scripts/proof_snapshot.json
"""
from __future__ import annotations

import datetime
import json
import re
import urllib.request
from pathlib import Path

SITE = "https://averagejoematt.com"
SNAPSHOT = Path(__file__).resolve().parent / "proof_snapshot.json"
CONSTANTS_PY = Path(__file__).resolve().parent.parent / "lambdas" / "constants.py"


def _today() -> str:
    return datetime.date.today().isoformat()


def _experiment_start() -> str:
    """The genesis date from lambdas/constants.py (text-parsed, no lambda imports).

    The restart pipeline regenerates constants.py, so a staged FUTURE genesis is
    visible to the site builders at build time — the #949 mechanism: pre-start,
    the proof blocks bake the countdown truth, never the wiped prior cycle's read.
    """
    try:
        m = re.search(r"EXPERIMENT_START_DATE\s*=\s*[\"'](\d{4}-\d{2}-\d{2})[\"']", CONSTANTS_PY.read_text(encoding="utf-8"))
        return m.group(1) if m else ""
    except Exception:
        return ""


def pre_start_date() -> str:
    """The staged genesis date iff it's still in the future ('' once Day 1 exists)."""
    start = _experiment_start()
    return start if start and _today() < start else ""


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


# Cockpit pillar → domain grouping — MIRRORS assets/js/cockpit.js (Constitution §6).
# Body and Mind are averaged rollups; Consistency is a standalone band.
COCKPIT_BODY = ("movement", "nutrition", "sleep", "metabolic")
COCKPIT_MIND = ("mind", "relationships")
PILLAR_LABELS = {
    "movement": "Movement",
    "nutrition": "Nutrition",
    "sleep": "Sleep",
    "metabolic": "Metabolic",
    "mind": "Mind",
    "relationships": "Relationships",
    "consistency": "Consistency",
}


def load_character() -> dict:
    """Today's character level + pillar scores from the live API, else the snapshot.

    /api/character returns {character:{level,tier,as_of_date,...}, pillars:[{name,
    raw_score,tier}]} — the SAME body the cockpit's own JS renders (via /api/snapshot).
    We keep only what that view shows; nothing is fabricated (ADR-104).
    """
    d = _fetch_json("/api/character")
    char = d.get("character") if isinstance(d, dict) else None
    if isinstance(char, dict) and char.get("level") is not None:
        pillars = {}
        for p in d.get("pillars", []) or []:
            name = p.get("name")
            score = p.get("raw_score")
            if name and isinstance(score, (int, float)):
                pillars[name] = {"raw_score": float(score), "tier": p.get("tier", "")}
        return {
            "level": _js_round(float(char["level"])),
            "tier": char.get("tier", ""),
            "as_of": char.get("as_of_date", "") or _today(),
            "pillars": pillars,
            "source": "live",
        }
    return _snapshot().get("cockpit", {})


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


def load_coaching_read() -> dict:
    """The board's live read from /api/coaching-dashboard, else the committed snapshot.

    /api/coaching-dashboard is the SAME body the coaching page's default "read" view
    renders (coaching.js::renderReadToday). We keep only what that view shows: the
    integrator's weekly priority (text + coach_name) and each coach's own read
    (position_summary). A coach with an empty position_summary is dropped — never a
    fabricated read (ADR-104 behavioral-absence). If the live API is unreachable we
    fall back to the last-known-good snapshot so an offline/CI build still bakes real
    coach voices rather than a blank shell.

    #949 pre-start: with a staged future genesis the dashboard's stored read (and the
    committed snapshot) narrate the WIPED prior cycle — the honest bake is the
    countdown, so the loader short-circuits to a pre_start marker and never fetches.
    """
    pre = pre_start_date()
    if pre:
        return {"pre_start": True, "start_date": pre, "as_of": _today(), "source": "pre-start"}
    d = _fetch_json("/api/coaching-dashboard")
    if isinstance(d, dict) and (d.get("weekly_priority") or d.get("coaches")):
        wp = d.get("weekly_priority") or {}
        coaches = []
        for c in d.get("coaches", []) or []:
            summary = str(c.get("position_summary") or "").strip()
            if not summary:
                continue  # honest absence — a coach with no live read is omitted
            coaches.append(
                {
                    "name": c.get("name", ""),
                    "title": c.get("title", ""),
                    "coach_id": c.get("coach_id", ""),
                    "position_summary": summary,
                }
            )
        text = str(wp.get("text") or "").strip()
        if not text and not coaches:
            # dashboard responded but carries no readable content — fall through to snapshot
            return _snapshot().get("coaching_read", {})
        # honest stamp: prefer the priority's own generation date, else the payload's
        generated = str(wp.get("generated_at") or d.get("_meta", {}).get("generated_at") or "")
        return {
            "weekly_priority": {
                "text": text,
                "coach_name": str(wp.get("coach_name") or "").strip(),
            },
            "coaches": coaches,
            "as_of": generated[:10] or _today(),
            "source": "live",
        }
    return _snapshot().get("coaching_read", {})


def load_chronicle_pending() -> dict:
    """The chronicle's own 'pending installment' marker (#803), mirroring the Panel
    podcast's `episodes.json` pending marker. wednesday_chronicle_lambda writes this
    onto /journal/posts.json when a week's draft is generated and then withheld
    (budget guard, privacy gate) rather than published, so a stale-looking chronicle
    can say why instead of going silent. Cleared automatically the next time a week
    actually publishes (publish_to_journal never writes a `pending` key)."""
    d = _fetch_json("/journal/posts.json")
    pending = d.get("pending") if isinstance(d, dict) else None
    return pending if isinstance(pending, dict) else {}


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


_WEEK_LABEL_RE = re.compile(r"^Week (\d+)$")


def _week_gap_note(posts: list) -> str:
    """Honest acknowledgement of a break in the "Week N" serial (#803, ADR-104
    behavioral-absence semantics): if published posts jump e.g. Week 1 -> Week 3, say
    so instead of leaving a reader to wonder what happened to Week 2. Prologue entries
    aren't numbered weeks and are excluded from the sequence. Never invents a specific
    cause — returns "" when there's no gap or too few numbered weeks to judge one."""
    weeks = set()
    for p in posts:
        m = _WEEK_LABEL_RE.match(p.get("label", "") or "")
        if m:
            weeks.add(int(m.group(1)))
    if len(weeks) < 2:
        return ""
    lo, hi = min(weeks), max(weeks)
    missing = [n for n in range(lo, hi + 1) if n not in weeks]
    if not missing:
        return ""
    names = ", ".join(f"Week {n}" for n in missing)
    plural = "s" if len(missing) > 1 else ""
    return (
        f"<p>{_esc(names)} — no installment{plural} ran. A draft can be written and then withheld before "
        "publishing (for example, if it doesn't clear the platform's privacy safety check); the numbering "
        "moves on rather than being silently renumbered.</p>"
    )


def chronicle_list_html(posts: list, limit: int = 20, pending: dict | None = None) -> str:
    """A dated, crawlable chronicle post list (#730). Newest first. #803 adds two honest
    disclosures on top: a currently-withheld week (`pending`, from load_chronicle_pending)
    and any break in the "Week N" numbering found in `posts` itself."""
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
    pending_note = f"<p>{_esc(pending['display'])}</p>" if pending and pending.get("display") else ""
    gap_note = _week_gap_note(posts)
    return (
        '<noscript><section class="proof-static dx-prose" aria-label="Chronicle posts">'
        f'<p class="label">The weekly chronicle — {len(posts)} posts, newest first (as of {_esc(_today())})</p>'
        f"{pending_note}{gap_note}"
        f'<ul>{"".join(rows)}</ul>'
        "</section></noscript>"
    )


def _js_round(x) -> int:
    """Math.round semantics (half-up) for non-negative scores — Python's round()
    is banker's (round(32.5)=32) and would drift from what cockpit.js renders."""
    return int(float(x) + 0.5)


def _rollup(pillars: dict, keys: tuple):
    """Average the raw pillar scores for a domain — the same rollup cockpit.js does."""
    vals = [pillars[k]["raw_score"] for k in keys if k in pillars and isinstance(pillars[k].get("raw_score"), (int, float))]
    if not vals:
        return None
    return _js_round(sum(vals) / len(vals))


def cockpit_block_html(ch: dict) -> str:
    """The cockpit's static proof (#788): the character level + tier, the Body/Mind
    rollups, each pillar score, and the honest "as of" stamp — baked into /cockpit/'s
    served HTML as <noscript>, the same #729/#730 treatment the scorecard and
    chronicle got.

    Only values the page's own JS view renders (from /api/character — the same body
    /api/snapshot carries) are baked; a missing pillar is omitted, never a
    fabricated 0 (ADR-104/105). No data at all -> "" and the shell ships unchanged.
    """
    if not ch or ch.get("level") is None:
        return ""
    level = int(ch["level"])
    tier = ch.get("tier", "")
    as_of = ch.get("as_of", "")
    pillars = ch.get("pillars", {}) or {}

    head = f"Character level {level}"
    if tier:
        head += f" · {_esc(tier)}"
    lines = [
        '<noscript><section class="proof-static dx-prose" aria-label="Cockpit summary">',
        f'<p class="label">The cockpit — one life, measured live · as of {_esc(as_of)}</p>',
        f"<p><strong>{head}</strong> — a 1–100 score of the whole day: seven pillars, each from real data, rolled into one.</p>",
    ]

    body_roll = _rollup(pillars, COCKPIT_BODY)
    mind_roll = _rollup(pillars, COCKPIT_MIND)
    consistency = pillars.get("consistency", {}).get("raw_score")
    rolls = []
    if body_roll is not None:
        rolls.append(f"Body {body_roll}")
    if mind_roll is not None:
        rolls.append(f"Mind {mind_roll}")
    if isinstance(consistency, (int, float)):
        rolls.append(f"Consistency {_js_round(consistency)}")
    if rolls:
        lines.append(f'<p>{" · ".join(rolls)}</p>')

    rows = []
    for key in (*COCKPIT_BODY, *COCKPIT_MIND):
        p = pillars.get(key)
        if not p or not isinstance(p.get("raw_score"), (int, float)):
            continue  # honest absence — the pillar row is omitted, never a fake 0
        tier_txt = f" · {_esc(p['tier'])}" if p.get("tier") else ""
        rows.append(f"<li>{_esc(PILLAR_LABELS.get(key, key))} {_js_round(p['raw_score'])}{tier_txt}</li>")
    if rows:
        lines.append(f'<ul>{"".join(rows)}</ul>')

    lines.append(
        "<p>The live view (today's board read, trends, time travel) needs JavaScript. "
        'What a level means: <a href="/method/character/">the method</a>.</p>'
    )
    lines.append("</section></noscript>")
    return "".join(lines)


def coaching_read_block_html(read: dict) -> str:
    """The coaching page's static proof (#804 · R22-UX-02): the board's read — the
    integrator's weekly priority + each named coach's own read — baked into
    /coaching/'s served HTML as <noscript>, the same #729/#730/#788 treatment.

    /coaching/ is the platform's core differentiator ("watch AI coaches argue about
    your data") yet shipped as a pure JS shell — only genesisStamp resolved without
    JS, so a crawler / LLM / no-JS visitor / the first seconds before scripts load saw
    an empty page. This bakes the ACTUAL coach voices the "read" view renders.

    Only content the page's own JS shows is baked (from /api/coaching-dashboard — the
    same body renderReadToday reads); a coach with no live read is omitted, never a
    fabricated read (ADR-104/105). No data at all -> "" and the shell ships unchanged.
    """
    if not read:
        return ""
    # #949 pre-start: the honest static proof is the countdown — a dated "the board
    # convenes with Day 1" line, never the prior cycle's board read (only
    # /data/cycles/ may acknowledge earlier attempts). Deliberately avoids the
    # "board's read" header + roster/blockquote markup so the no-JS state is
    # unambiguous to readers and to the committed-HTML tests alike.
    if read.get("pre_start"):
        start = read.get("start_date", "")
        try:
            start_disp = datetime.date.fromisoformat(start).strftime("%A, %B %-d")
        except Exception:
            start_disp = start
        return (
            '<noscript><section class="proof-static dx-prose" aria-label="The coaching — pre-start">'
            f'<p class="label">The coaching — pre-start · as of {_esc(read.get("as_of", ""))}</p>'
            f"<p>The experiment begins <strong>{_esc(start_disp)}</strong>, with the first baseline weigh-in. "
            "The AI coaching board reads only this run's data — its first take lands here once Day 1's numbers exist.</p>"
            '<p>Meanwhile: <a href="/coaching/team/">who the coaches are</a> · '
            '<a href="/coaching/scorecard/">how their calls get graded</a>.</p>'
            "</section></noscript>"
        )
    wp = read.get("weekly_priority") or {}
    priority = str(wp.get("text") or "").strip()
    coaches = read.get("coaches") or []
    if not priority and not coaches:
        return ""
    as_of = read.get("as_of", "")

    lines = [
        '<noscript><section class="proof-static dx-prose" aria-label="The board\'s read">',
        f'<p class="label">The board\'s read on the data — as of {_esc(as_of)}</p>',
    ]
    if priority:
        coach_name = str(wp.get("coach_name") or "").strip()
        who = f" · {_esc(coach_name)}" if coach_name else ""
        # #1115: labeled at its true altitude — this is the integrator's WEEKLY
        # call (the Week lens's read), never presented as today's line.
        lines.append(f'<p class="label">The week\'s call{who}</p>')
        lines.append(f"<blockquote>{_esc(priority)}</blockquote>")
    if coaches:
        lines.append('<p class="label">Each coach\'s read</p>')
        rows = []
        for c in coaches:
            name = _esc(c.get("name", "") or c.get("coach_id", ""))
            title = c.get("title", "")
            who = f"{name}" + (f" · {_esc(title)}" if title else "")
            rows.append(f"<li><strong>{who}</strong> — {_esc(c['position_summary'])}</li>")
        lines.append(f'<ul>{"".join(rows)}</ul>')
    lines.append(
        "<p>The live board (today's read, the disagreements, each coach on top of the "
        'actual numbers) needs JavaScript. <a href="/coaching/by-coach/">By coach</a> · '
        '<a href="/coaching/team/">who they are</a>.</p>'
    )
    lines.append("</section></noscript>")
    return "".join(lines)
