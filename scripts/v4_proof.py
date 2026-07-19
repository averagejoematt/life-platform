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
            # dashboard responded but carries no readable content — fall through to
            # the snapshot; if THAT is empty too (the Day-1 window: post-genesis,
            # board's first read not computed yet, snapshot cleared by the reset
            # curation), return a dated awaiting-first-read marker so the page
            # still ships an honest static core instead of a blank crawler view
            # (found by #1528's live sweep — the missing block reds the
            # static-core smoke guard and auto-rolls-back the next deploy).
            snap = _snapshot().get("coaching_read", {})
            if snap:
                return snap
            return {"as_of": _today(), "source": "live-empty"}
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
    # No live content at all (dashboard empty-shaped or unreachable): snapshot,
    # else the same dated awaiting-first-read marker as above — a static_core:true
    # page must never build a blank crawler view (#1528).
    snap = _snapshot().get("coaching_read", {})
    if snap:
        return snap
    return {"as_of": _today(), "source": "live-empty"}


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
        # Day-1 / early-cycle window (found by #1528's live sweep): the experiment
        # is running but the board hasn't published its first read of this run yet
        # (coach computes land after Day 1's numbers exist). The honest static
        # core is that fact, dated — never a fabricated read, and never "" (a
        # blank crawler view that the static-core smoke guard rightly reds on a
        # static_core:true page, auto-rolling-back an otherwise healthy deploy).
        return (
            '<noscript><section class="proof-static dx-prose" aria-label="The coaching — awaiting the first read">'
            f'<p class="label">The coaching — as of {_esc(read.get("as_of", ""))}</p>'
            "<p>The cycle is under way, but the board hasn't published its first read of this run's data yet — "
            "each coach reads only this cycle's numbers, and the first take lands once the daily computes have "
            "something real to argue about.</p>"
            '<p>Meanwhile: <a href="/coaching/team/">who the coaches are</a> · '
            '<a href="/coaching/scorecard/">how their calls get graded</a>.</p>'
            "</section></noscript>"
        )
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


# ── #1395: the growth surface — static core + data-driven OG on Home + the doors ──
#
# The OG / no-JS / crawler view of Home, /data/, and /protocols/ was a blank shell
# (client-rendered), so every HN/Twitter/Slack unfurl and search snippet showed
# nothing (frontier review Epic G / trust-leak #10). This extends the #729/#730/#788/
# #804 proof machinery to those surfaces: a <noscript> static core carrying real,
# dated headline numbers, and per-page data-driven OG tags whose title/description
# carry a falsifiable number (never generic boilerplate). Every number comes from a
# published API the page already speaks to; nothing is fabricated (ADR-104/105), and
# every block carries an honest "as of" stamp so a stale crawl reads as
# honest-but-possibly-stale, never as fabricated live data.


def _meta_stamp(d) -> str:
    """The API payload's own `_meta.generated_at` date (YYYY-MM-DD), or ''."""
    try:
        return str(d.get("_meta", {}).get("generated_at", ""))[:10]
    except Exception:
        return ""


def _fmt_lbs(x) -> str:
    """Whole-pound display of a weight (315.6 -> '316'), '' if not a number."""
    if not isinstance(x, (int, float)):
        return ""
    return f"{int(round(float(x)))}"


def _long_date(iso: str) -> str:
    """'2026-07-19' -> 'Sunday, July 19' (falls back to the raw string)."""
    try:
        return datetime.date.fromisoformat(iso).strftime("%A, %B %-d")
    except Exception:
        return iso


# ── data loaders (each with the committed-snapshot fallback) ─────────────────


def load_journey() -> dict:
    """The weight-journey headline from /api/journey — Home's own JS dep (ADR-104).

    Keeps only what Home renders: the baseline/goal, day-of-experiment, pre-start
    state and the honest stamp. Pre-start (a staged future genesis, #949) the numbers
    are the baseline + countdown, never a wiped prior cycle's progress."""
    d = _fetch_json("/api/journey")
    j = d.get("journey") if isinstance(d, dict) else None
    if isinstance(j, dict) and (j.get("start_weight_lbs") is not None or j.get("start_date")):
        return {
            "start_weight": j.get("start_weight_lbs"),
            "goal_weight": j.get("goal_weight_lbs"),
            "current_weight": j.get("current_weight_lbs"),
            "lost_lbs": j.get("lost_lbs"),
            "day_n": j.get("day_n"),
            "pre_start": bool(j.get("pre_start")),
            "start_date": j.get("start_date") or j.get("started_date") or "",
            "as_of": _meta_stamp(d) or _today(),
            "source": "live",
        }
    return _snapshot().get("journey", {})


def load_data_sources() -> dict:
    """The data door's headline from /api/source_freshness (the pipeline's own feed).

    Returns the source count, the fresh count, and the list of source labels — all
    real, all crawlable. `fresh` counts only status=='fresh' (behavioral-stale and
    paused are honestly NOT counted as fresh, ADR-104)."""
    d = _fetch_json("/api/source_freshness")
    sources = d.get("sources") if isinstance(d, dict) else None
    if isinstance(sources, list) and sources:
        labels = [str(s.get("label") or s.get("id") or "").strip() for s in sources]
        labels = [x for x in labels if x]
        fresh = sum(1 for s in sources if s.get("status") == "fresh")
        return {
            "total": len(sources),
            "fresh": fresh,
            "labels": labels,
            "as_of": _meta_stamp(d) or _today(),
            "source": "live",
        }
    return _snapshot().get("data_sources", {})


def load_protocols() -> dict:
    """The protocols door's headline from /api/experiments (the library feed).

    Returns the experiment-library total and how many are `available` to run now —
    the falsifiable "levers" count the door is about. A library with zero entries is
    reported honestly as zero (never omitted into a blank)."""
    d = _fetch_json("/api/experiments")
    exps = d.get("experiments") if isinstance(d, dict) else None
    if isinstance(exps, list):
        available = sum(1 for e in exps if e.get("status") == "available")
        return {
            "total": len(exps),
            "available": available,
            "as_of": _meta_stamp(d) or _today(),
            "source": "live",
        }
    return _snapshot().get("protocols", {})


# ── render helpers (return "" rather than fabricate on missing data) ─────────

_DOORS_TAIL = (
    "The live view (today's numbers, the AI board's read, the interactive charts) needs "
    'JavaScript. The doors: <a href="/cockpit/">the cockpit</a> · <a href="/data/">the data</a> · '
    '<a href="/coaching/">the coaching</a> · <a href="/protocols/">the protocols</a> · '
    '<a href="/story/">the story</a>.'
)


def home_block_html(journey: dict, char: dict) -> str:
    """Home's static core (#1395): the mission in real numbers — baseline → goal, the
    day-of-experiment (or the countdown pre-start), and the live character level —
    baked into `/`'s served HTML as <noscript>, so a crawler / LLM / no-JS visitor
    reads the actual experiment, not the blank cinematic shell.

    Numbers come from /api/journey (Home's own dep) + /api/character; a missing value
    is dropped, never faked (ADR-104). No data at all -> "" and Home ships unchanged."""
    journey = journey or {}
    sw = _fmt_lbs(journey.get("start_weight"))
    gw = _fmt_lbs(journey.get("goal_weight"))
    as_of = journey.get("as_of", "") or _today()
    if not sw and not gw:
        return ""

    lines = [
        '<noscript><section class="proof-static dx-prose" aria-label="The experiment, in numbers">',
        f'<p class="label">An honest documentary of an ordinary life, rebuilt with AI — as of {_esc(as_of)}</p>',
    ]
    climb = ""
    if sw and gw:
        climb = f" — a {int(sw) - int(gw)} lb climb"
    if journey.get("pre_start") and journey.get("start_date"):
        when = _long_date(journey["start_date"])
        lines.append(
            f"<p><strong>The experiment begins {_esc(when)}.</strong> Baseline {_esc(sw)} lb, goal "
            f"{_esc(gw)} lb{_esc(climb)} — measured every day and published either way.</p>"
        )
    else:
        day_n = journey.get("day_n")
        lost = _fmt_lbs(journey.get("lost_lbs"))
        cur = _fmt_lbs(journey.get("current_weight"))
        day_txt = f"Day {int(day_n)}. " if isinstance(day_n, (int, float)) else ""
        if cur and lost:
            prog = f"{_esc(day_txt)}From {_esc(sw)} lb toward {_esc(gw)} lb — {_esc(cur)} lb now, {_esc(lost)} lb down."
        else:
            prog = f"{_esc(day_txt)}From {_esc(sw)} lb toward {_esc(gw)} lb{_esc(climb)} — measured every day, published either way."
        lines.append(f"<p><strong>{prog}</strong></p>")

    level = (char or {}).get("level")
    if level is not None:
        tier = (char or {}).get("tier", "")
        tier_txt = f" · {_esc(tier)}" if tier else ""
        lines.append(
            f"<p>Character level {int(level)}{tier_txt} — a 1–100 read of the whole day across seven "
            "pillars (sleep, movement, nutrition, metabolic, mind, relationships, consistency), each "
            "scored from real wearable &amp; lab data.</p>"
        )
    lines.append(f"<p>{_DOORS_TAIL}</p>")
    lines.append("</section></noscript>")
    return "".join(lines)


def data_block_html(summary: dict) -> str:
    """The data door's static core (#1395): the real source roster + fresh count baked
    into `/data/`'s served HTML as <noscript>. Every source label is real (from
    /api/source_freshness); nothing is invented."""
    summary = summary or {}
    total = summary.get("total")
    if not isinstance(total, int) or total <= 0:
        return ""
    fresh = summary.get("fresh", 0)
    as_of = summary.get("as_of", "") or _today()
    labels = summary.get("labels") or []
    roster = ""
    if labels:
        roster = "<ul>" + "".join(f"<li>{_esc(x)}</li>" for x in labels) + "</ul>"
    return (
        '<noscript><section class="proof-static dx-prose" aria-label="The data, in numbers">'
        f'<p class="label">The data — every source the platform reads · as of {_esc(as_of)}</p>'
        f"<p><strong>{int(total)} sources on the board, {int(fresh)} fresh right now.</strong> "
        "The body and the mind — wearables, labs, glucose, journals — read daily, live and over time.</p>"
        f"{roster}"
        "<p>The live trends, the cross-source signals, and the flagged-when-thin caveats need "
        'JavaScript. Start on <a href="/data/">the data</a>.</p>'
        "</section></noscript>"
    )


def protocols_block_html(summary: dict) -> str:
    """The protocols door's static core (#1395): the experiment-library count baked into
    `/protocols/`'s served HTML as <noscript>. Counts come from /api/experiments."""
    summary = summary or {}
    total = summary.get("total")
    if not isinstance(total, int):
        return ""
    available = summary.get("available", 0)
    as_of = summary.get("as_of", "") or _today()
    return (
        '<noscript><section class="proof-static dx-prose" aria-label="The protocols, in numbers">'
        f'<p class="label">The protocols — the levers, and whether they moved · as of {_esc(as_of)}</p>'
        f"<p><strong>{int(total)} experiments in the library, {int(available)} ready to run now.</strong> "
        "Supplements, timed protocols, and challenges — each one changes an input to move the data, "
        "graded on whether it actually did.</p>"
        "<p>The live protocol state and the discoveries they chase need JavaScript. "
        'Start on <a href="/protocols/">the protocols</a>.</p>'
        "</section></noscript>"
    )


# ── per-page data-driven OG tags (a dated, falsifiable number, never boilerplate) ──
#
# Each door maps to the closest EXISTING og-image card (the og-image lambda draws 14
# daily cards; #1395 reuses them, it does not extend the lambda). Where no bespoke
# card exists (data, coaching) the generic og-home card is the honest closest — noted
# as a follow-up gap in the PR, not faked with a mislabeled card.


def _og_tags(url: str, title: str, desc: str, card: str) -> dict:
    """The full data-driven OG/Twitter set for a page (property/name -> content)."""
    img = f"{SITE}/assets/images/{card}"
    return {
        ("property", "og:type"): "website",
        ("property", "og:site_name"): "averagejoematt",
        ("property", "og:url"): url,
        ("property", "og:title"): title,
        ("property", "og:description"): desc,
        ("property", "og:image"): img,
        ("name", "twitter:card"): "summary_large_image",
        ("name", "twitter:title"): title,
        ("name", "twitter:description"): desc,
    }


def home_og(journey: dict, char: dict) -> dict:
    """Home's data-driven OG: baseline → goal + the countdown/day + level."""
    journey = journey or {}
    sw = _fmt_lbs(journey.get("start_weight")) or "316"
    gw = _fmt_lbs(journey.get("goal_weight")) or "185"
    as_of = journey.get("as_of", "") or _today()
    title = f"averagejoematt — {sw} lb → {gw} lb, measured in public"
    if journey.get("pre_start") and journey.get("start_date"):
        desc = (
            f"The experiment begins {_long_date(journey['start_date'])}: baseline {sw} lb, goal {gw} lb, "
            f"every number published either way. As of {as_of}."
        )
    else:
        day_n = journey.get("day_n")
        lost = _fmt_lbs(journey.get("lost_lbs"))
        day_txt = f"Day {int(day_n)}: " if isinstance(day_n, (int, float)) else ""
        gained = f"{lost} lb down. " if lost else ""
        desc = f"{day_txt}{sw} lb toward {gw} lb — {gained}Every number published either way. As of {as_of}."
    level = (char or {}).get("level")
    if level is not None:
        desc += f" Character level {int(level)}."
    return _og_tags(f"{SITE}/", title, desc, "og-home.png")


def cockpit_og(char: dict) -> dict:
    """Cockpit's data-driven OG: the live character level + tier."""
    char = char or {}
    level = char.get("level")
    tier = char.get("tier", "")
    as_of = char.get("as_of", "") or _today()
    if level is not None:
        lvl = f"level {int(level)}" + (f" · {tier}" if tier else "")
        title = f"The Cockpit — character {lvl}"
        desc = (
            f"Am I winning, and what's the one thing right now? The daily instrument: seven pillars "
            f"scored from real data. Character {lvl} as of {as_of}."
        )
    else:
        title = "The Cockpit — the daily instrument"
        desc = "Am I winning, and what's the one thing right now? Seven pillars scored from real data, daily."
    return _og_tags(f"{SITE}/cockpit/", title, desc, "og-character.png")


def data_og(summary: dict) -> dict:
    """The data door's data-driven OG: the live source count + fresh count."""
    summary = summary or {}
    total = summary.get("total")
    as_of = summary.get("as_of", "") or _today()
    if isinstance(total, int) and total > 0:
        fresh = int(summary.get("fresh", 0))
        title = f"The Data — {total} sources, {fresh} fresh"
        desc = (
            f"Every source the platform reads: {total} tracked, {fresh} fresh as of {as_of}. "
            "The body and the mind, live and over time — correlative, read-only, flagged when thin."
        )
    else:
        title = "The Data — every source the platform reads"
        desc = "The body and the mind, live and over time — correlative, read-only, flagged when thin."
    # No bespoke og-data card exists; og-home (the platform overview) is the honest closest.
    return _og_tags(f"{SITE}/data/", title, desc, "og-home.png")


def protocols_og(summary: dict) -> dict:
    """The protocols door's data-driven OG: the experiment-library count."""
    summary = summary or {}
    total = summary.get("total")
    as_of = summary.get("as_of", "") or _today()
    if isinstance(total, int):
        available = int(summary.get("available", 0))
        title = f"The Protocols — {total} experiments in the library"
        desc = (
            f"{total} experiments, {available} ready to run, as of {as_of}. The levers that move the "
            "data — supplements, protocols, challenges — graded on whether they actually did."
        )
    else:
        title = "The Protocols — the levers you pull"
        desc = "Supplements, experiments, and challenges — what gets changed to move the data, and whether it moved."
    return _og_tags(f"{SITE}/protocols/", title, desc, "og-experiments.png")


def coaching_og(read: dict) -> dict:
    """The coaching door's data-driven OG: the pre-start convene date, else the live read stamp."""
    read = read or {}
    as_of = read.get("as_of", "") or _today()
    if read.get("pre_start") and read.get("start_date"):
        title = f"The Coaching — the AI board convenes {_long_date(read['start_date'])}"
        desc = (
            f"A board of named AI coaches reads the data and argues about it. Its first read lands "
            f"once Day 1's numbers exist ({_long_date(read['start_date'])}). As of {as_of}."
        )
    else:
        title = "The Coaching — the AI board's live read"
        desc = (
            "What the AI board is saying about the data right now — the read, by coach, the "
            f"disagreements, and the weekly lab notes. As of {as_of}."
        )
    # No bespoke og-coaching card exists; og-home is the honest closest.
    return _og_tags(f"{SITE}/coaching/", title, desc, "og-home.png")


def story_og(posts: list) -> dict:
    """The story door's data-driven OG: the count of published dispatches."""
    n = len([p for p in (posts or []) if p.get("title")])
    if n > 0:
        title = f"The Story — {n} dispatches published"
        desc = (
            f"The chronicle, the journal, and the timeline — {n} weekly dispatches so far, newest "
            f"first (as of {_today()}). The writing and the why behind the experiment."
        )
    else:
        title = "The Story — the writing and the why"
        desc = "The chronicle, the journal, the timeline, and the context behind the experiment."
    return _og_tags(f"{SITE}/story/", title, desc, "og-chronicle.png")


# ── OG applier for the hand-authored pages (Home, Cockpit) ────────────────────
# The generator-built doors (data/protocols/coaching/story) receive their OG tags
# straight into the head template. Home + Cockpit are hand-authored shells; this
# upgrades their <head> in place — replacing an existing tag's content or inserting
# the tag after the description meta — idempotently, so re-runs converge.

_DESC_ANCHOR = re.compile(r'(<meta name="description"[^>]*>)')


def apply_og(html: str, og: dict) -> str:
    """Set every (kind, key)->value in `og` on `html`'s <head>, in place. Idempotent."""
    for (kind, key), value in og.items():
        attr = "property" if kind == "property" else "name"
        pat = re.compile(rf'(<meta {attr}="{re.escape(key)}" content=")[^"]*(")')
        tag = f'<meta {attr}="{key}" content="{_esc(value)}">'
        if pat.search(html):
            html = pat.sub(lambda m: m.group(1) + _esc(value) + m.group(2), html, count=1)
        else:
            m = _DESC_ANCHOR.search(html)
            if m:
                html = html[: m.end()] + "\n  " + tag + html[m.end() :]
            else:  # no description meta — fall back to just after <head>
                html = html.replace("<head>", "<head>\n  " + tag, 1)
    return html
