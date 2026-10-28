"""og_moments.py — #404: permalinked shareable artifacts for the meaningful moments.

The platform already produces exactly the moments a reader might share — the
weekly recap, a board answer to a reader's question, a graded prediction — but
they died inside client-side renders with no URL. This module (run by the
daily og-image-generator after the standard page cards) gives each moment:

  - a STABLE permalink shell:  generated/moments/{type}/{id}/index.html
    (static HTML with the moment's real content baked in + per-moment OG meta,
    served at /moments/{type}/{id}/ via CloudFront's generated origin)
  - its OWN share card:        generated/moments/assets/{type}-{id}.png
  - an index the front-end share buttons read: generated/moments/index.json

Honesty guardrails: cards and shells render only computed or already-published
values — the recap from public_stats.json, answers from the moderated public
feed, predictions from the public /api/predictions payload (fetched over HTTP
like any reader would see it). An empty moment gets no card and no shell.
Everything is idempotent — re-sweeping overwrites with identical content.
"""

import hashlib
import html
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone

from common.journal_silence import public_body  # #5131: the one public-surface guard
from common.pacific_time import PACIFIC as PT  # #2414: reader-facing dates anchor in the Pacific day

from web.journey_direction import DOWN, EVEN, UNKNOWN, UP, classify_delta  # #3293: the ONE ruling on the sign of the journey delta

S3_BUCKET = "matthew-life-platform"
SITE_BASE = "https://averagejoematt.com"
MOMENTS_PREFIX = "generated/moments/"


# ── #5421: the incremental, time-boxed sweep ────────────────────────────────
#
# Every sweep used to re-render and re-PUT every moment on every run — ~60 obituary cards,
# ~20 graded predictions, the chronicle cards and ~90 retirement redirects, ~40 s of a
# 60 s Lambda whose page-card render needs ~15 s. Nearly all of it wrote bytes identical
# to the day before. The plan below makes a moment's card + shell a pure function of a
# DIGEST of its inputs: a moment whose digest matches the previous run's (carried in the
# index, read back over the public viewer path — the role holds no GetObject or ListBucket
# on this prefix) is not re-rendered, and the sweep stops starting new work once the
# invocation is within ``SWEEP_RESERVE_MS`` of its timeout, leaving the rest for the next
# run (their digests are simply not recorded, so they are retried). Without a readable
# previous index every digest is "new" and the sweep does exactly what it did before.

SWEEP_RESERVE_MS = 8000  # left for the fingerprint, the index put and the coach-card sweep

RENDER, SKIP, DEFER = "render", "skip", "defer"


def _source_salt():
    """A digest of the code that DRAWS a moment — a change to any of these re-renders
    every moment once; a moment never keeps bytes the current code would not write."""
    here = os.path.dirname(os.path.abspath(__file__))
    paths = [os.path.abspath(__file__), os.path.join(here, "card_engine.py"), os.path.join(here, "og_image_lambda.py")]
    guard = sys.modules.get("common.journal_silence")
    if guard is not None and getattr(guard, "__file__", None):
        paths.append(guard.__file__)  # the public-surface guard shapes every shell body (#5131)
    h = hashlib.sha256()
    for src in paths:
        try:
            with open(src, "rb") as fh:
                h.update(fh.read())
        except OSError:
            return None  # cannot prove what drew the bytes -> never claim a moment is current
    return h.hexdigest()[:16]


class SweepPlan:
    """What the previous run already published, and how long this one has left.

    ``previous_index`` is the parsed ``generated/moments/index.json`` of the last run (or
    ``None``); ``time_left`` is a callable returning the invocation's remaining
    milliseconds (``context.get_remaining_time_in_millis``) or ``None`` for unbounded;
    ``force`` ignores the previous digests and re-renders everything."""

    def __init__(self, previous_index=None, time_left=None, force=False, reserve_ms=SWEEP_RESERVE_MS):
        self.previous_index = previous_index
        self.time_left = time_left
        self.reserve_ms = reserve_ms
        self.force = bool(force)
        usable = previous_index if (previous_index and not self.force) else {}
        self.prior = {str(k): str(v) for k, v in (usable.get("digests") or {}).items()}
        self.prior_retired = {str(i) for i in (usable.get("wrong_retired") or [])}
        self.salt = _source_salt()
        self.digests = {}  # key -> digest of every moment known current after this run
        self.counts = {RENDER: 0, SKIP: 0, DEFER: 0}

    def out_of_time(self):
        if self.time_left is None:
            return False
        try:
            return self.time_left() < self.reserve_ms
        except Exception:
            return False

    def digest(self, payload):
        blob = json.dumps(payload, sort_keys=True, default=str)
        return hashlib.sha256(f"{self.salt}|{blob}".encode("utf-8")).hexdigest()[:20]

    def decide(self, key, payload):
        """``(status, digest)`` for one moment: SKIP when the last run published exactly this,
        DEFER when the invocation is out of time (and the moment is not already current),
        RENDER otherwise. A SKIP/DEFER'd moment keeps its digest so the next run still knows."""
        digest = self.digest(payload)
        if self.salt is not None and self.prior.get(key) == digest:
            self.digests[key] = digest
            self.counts[SKIP] += 1
            return SKIP, digest
        if self.out_of_time():
            if key in self.prior:
                self.digests[key] = self.prior[key]  # the older render still serves; retried next run
            self.counts[DEFER] += 1
            return DEFER, digest
        return RENDER, digest

    def rendered(self, key, digest):
        self.digests[key] = digest
        self.counts[RENDER] += 1

    def exists(self, key):
        """True when a previous run published this moment (so a DEFER'd one is still served)."""
        return key in self.prior

    def summary(self):
        return f"rendered={self.counts[RENDER]} unchanged={self.counts[SKIP]} deferred={self.counts[DEFER]}"


# ── The card (Pillow, reusing the daily generator's design system) ──────────


def _wrap(text, width=34, max_lines=4):
    words = str(text).split()
    lines, cur = [], ""
    for w in words:
        if len(cur) + len(w) + 1 > width and cur:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1][: width - 1] + "…"
    return lines


def build_moment_card(kicker, title, meta_line, footer_note):
    """One generic 1200×630 moment card: kicker · wrapped title · meta · footer."""
    from web import og_image_lambda as og

    img, draw = og._base_image()
    og._draw_header(draw, kicker)
    y = 130
    for line in _wrap(title, width=30, max_lines=4):
        draw.text((48, y), line.upper(), fill=og.TEXT, font=og._font(og.FONT_DISPLAY, 58))
        y += 66
    if meta_line:
        draw.text((48, y + 18), meta_line[:110], fill=og.MUTED, font=og._font(og.FONT_MONO, 14))
    draw.text((48, og.H - 30), footer_note[:80], fill=og.FAINT, font=og._font(og.FONT_MONO, 11))
    draw.text((og.W - 48, og.H - 30), "averagejoematt.com", fill=og.FAINT, font=og._font(og.FONT_MONO, 11), anchor="ra")
    return img


# ── The permalink shell ──────────────────────────────────────────────────────

_SHELL = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title} — averagejoematt</title>
  <meta name="description" content="{desc}">
  <link rel="canonical" href="{canonical}">
  <meta property="og:type" content="article">
  <meta property="og:title" content="{title}">
  <meta property="og:description" content="{desc}">
  <meta property="og:image" content="{image}">
  <meta property="og:url" content="{canonical}">
  <meta name="twitter:card" content="summary_large_image">
  <style>
    body {{ margin:0; background:#080c0a; color:#ECE3D2; font:16px/1.55 Georgia, serif;
           display:grid; place-items:center; min-height:100vh; padding:24px; box-sizing:border-box; }}
    main {{ max-width:640px; }}
    .k {{ font:11px/1.4 ui-monospace, monospace; letter-spacing:.08em; text-transform:uppercase; color:#8aaa90; }}
    h1 {{ font-size:1.6rem; line-height:1.25; margin:.4em 0; }}
    .meta {{ font:12px/1.4 ui-monospace, monospace; color:#857B68; }}
    .body p {{ color:#cfc6b4; }}
    .who {{ color:#8aaa90; font:12px ui-monospace, monospace; display:block; margin-top:1em; }}
    a {{ color:#8aaa90; }}
  </style>
</head>
<body>
  <main>
    <p class="k">{kicker}</p>
    <h1>{title}</h1>
    <p class="meta">{meta}</p>
    <div class="body">{body_html}</div>
    <p class="meta"><a href="{live_url}">see it live on the site →</a> · single-subject (N=1) experiment — correlative, never causal</p>
  </main>
</body>
</html>
"""


def _shell_html(kicker, title, desc, meta, body_html, moment_path, image_path, live_url):
    e = html.escape
    return _SHELL.format(
        kicker=e(kicker),
        title=e(title),
        desc=e(desc[:200]),
        meta=e(meta),
        body_html=body_html,  # caller escapes its pieces
        canonical=f"{SITE_BASE}{moment_path}",
        image=f"{SITE_BASE}{image_path}",
        live_url=e(live_url),
    )


def _put(s3, key, body, content_type, cache="max-age=3600"):
    s3.put_object(Bucket=S3_BUCKET, Key=key, Body=public_body(body, content_type), ContentType=content_type, CacheControl=cache)


def _put_moment(s3, mtype, mid, card_img, shell):
    import io

    img_key = f"{MOMENTS_PREFIX}assets/{mtype}-{mid}.png"
    buf = io.BytesIO()
    card_img.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    _put(s3, img_key, buf.read(), "image/png", cache="max-age=86400")
    _put(s3, f"{MOMENTS_PREFIX}{mtype}/{mid}/index.html", shell.encode("utf-8"), "text/html; charset=utf-8")
    return f"/moments/{mtype}/{mid}/"


# ── The three moment classes ─────────────────────────────────────────────────


def _weight_bit(lost_lbs):
    """#3293 — the weekly recap's weight clause, direction from the shared ruling.

    This line used to be ``f"{round(journey['lost_lbs'], 1)} lbs down"``: a STATIC
    direction word over a SIGNED value. ``lost_lbs`` is ``start − current``, so a gain
    is negative and the card published *"-5.2 lbs down"* — the identical double
    negative #3285 removed from the home share card, on a surface that is also shared
    externally (the recap card's meta line, its ``og:description`` and its page body all
    render this same string).

    The direction now comes from ``web.journey_direction.classify_delta`` — the one
    ruling the home card's caption/colour and the home ``og:description`` already use —
    so no two shared artifacts can point opposite ways about the same number.

    Returns a LIST so the caller can splice zero or one bit in: an absent, non-numeric
    or non-finite delta contributes NOTHING rather than a guessed direction (ADR-104).
    One decimal, matching the display the caller had.
    """
    direction, magnitude = classify_delta(lost_lbs, decimals=1)
    if direction == UNKNOWN or magnitude is None:
        return []
    if direction == EVEN:
        return ["weight even"]
    return [f"{magnitude} lbs {DOWN if direction == DOWN else UP}"]


def _sweep_week_recap(s3, stats):
    """The weekly recap — refreshed daily under the ISO-week permalink."""
    journey = stats.get("journey") or {}
    vitals = stats.get("vitals") or {}
    platform = stats.get("platform") or {}
    if not (journey or vitals):
        return None  # empty moment → no card, no shell
    iso = datetime.now(PT).isocalendar()  # #2414: the week id is the reader's Pacific week
    wid = f"{iso.year}-W{iso.week:02d}"
    bits = []
    bits.extend(_weight_bit(journey.get("lost_lbs")))
    if vitals.get("hrv_ms") is not None:
        bits.append(f"HRV {round(vitals['hrv_ms'])} ms")
    if platform.get("tier0_streak") is not None:
        bits.append(f"streak {int(platform['tier0_streak'])}d")
    if platform.get("days_in") is not None:
        bits.append(f"day {int(platform['days_in'])}")
    meta = " · ".join(bits)
    title = f"The week so far — {wid}"
    card = build_moment_card("the weekly recap", title, meta, f"live numbers as of {datetime.now(PT):%Y-%m-%d}")
    body = f"<p>{html.escape(meta)}</p><p>The full instruments — sparklines, deltas, and the honest gaps — live on the cockpit's week view.</p>"
    shell = _shell_html(
        "the weekly recap",
        title,
        f"One measured life, week {wid}: {meta}",
        f"refreshed daily · {wid}",
        body,
        f"/moments/week/{wid}/",
        f"/moments/assets/week-{wid}.png",
        f"{SITE_BASE}/cockpit/",
    )
    url = _put_moment(s3, "week", wid, card, shell)
    return {"current": url, "id": wid}


def _sweep_board_answers(s3, plan=None):
    """Every published (moderated) reader Q&A gets its own permalink."""
    try:
        feed = json.loads(s3.get_object(Bucket=S3_BUCKET, Key="generated/board_answers/answers.json")["Body"].read())
    except Exception:
        return {}
    out = {}
    for a in feed.get("answers") or []:
        mid = str(a.get("id", "")).strip()
        question = (a.get("question") or "").strip()
        if not mid or not question:
            continue
        answered = a.get("answered_at", "")
        responses = a.get("responses") or ([{"name": "The board", "text": a["answer"]}] if a.get("answer") else [])
        if not responses:
            continue  # a question without an answer is not a moment yet
        meta = f"asked {a.get('asked_at', '?')} · answered {answered} · {len(responses)} voice{'s' if len(responses) != 1 else ''}"
        plan_key = f"qa/{mid}"
        verdict, digest = plan.decide(plan_key, [question, meta, answered, responses]) if plan else (RENDER, None)
        if verdict != RENDER:
            if verdict == SKIP or plan.exists(plan_key):
                out[mid] = f"/moments/qa/{mid}/"
            continue
        card = build_moment_card("a reader asked — the board answered", question, meta, f"answered {answered}")
        body = "".join(
            f"<span class='who'>{html.escape(str(r.get('name', 'The board')))}</span><p>{html.escape(str(r.get('text', '')))}</p>"
            for r in responses
        )
        shell = _shell_html(
            "a reader asked — the board answered",
            question,
            (responses[0].get("text") or "")[:200],
            meta,
            body,
            f"/moments/qa/{mid}/",
            f"/moments/assets/qa-{mid}.png",
            f"{SITE_BASE}/coaching/qa/#{mid}",
        )
        out[mid] = _put_moment(s3, "qa", mid, card, shell)
        if plan:
            plan.rendered(plan_key, digest)
    return out


def _prediction_key(p):
    """The composite the front-end can rebuild without hashing: coach|date|text head."""
    return f"{p.get('coach_id', '')}|{p.get('date', '')}|{str(p.get('text', ''))[:60]}"


def _sweep_predictions(s3, plan=None):
    """Graded calls (confirmed/refuted) — fetched from the PUBLIC scorecard API
    so the moment can never say more than the site already publishes."""
    try:
        req = urllib.request.Request(f"{SITE_BASE}/api/predictions", headers={"accept": "application/json"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if isinstance(data.get("data"), dict):
            data = data["data"]
    except Exception as e:
        print(f"[moments] predictions fetch skipped: {e}")
        return []
    out = []
    for p in data.get("predictions") or []:
        if p.get("status") not in ("confirmed", "refuted"):
            continue
        text = (p.get("text") or "").strip()
        if not text:
            continue
        mid = hashlib.sha256(_prediction_key(p).encode()).hexdigest()[:12]
        verdict = "CALLED IT" if p["status"] == "confirmed" else "GOT IT WRONG"
        coach = p.get("coach_name", "A coach")
        meta = f"{coach} · {p.get('date', '')} · {verdict}"
        notes = (p.get("outcome_notes") or "").strip()
        plan_key = f"prediction/{mid}"
        action, digest = plan.decide(plan_key, [text, meta, p["status"], notes]) if plan else (RENDER, None)
        if action != RENDER:
            if action == SKIP or plan.exists(plan_key):
                out.append({"key": _prediction_key(p), "status": p["status"], "url": f"/moments/prediction/{mid}/"})
            continue
        card = build_moment_card(f"a graded prediction — {verdict.lower()}", text, meta, "every call is graded in public")
        body = (
            f"<p><strong>{html.escape(verdict)}</strong> — {html.escape(coach)}'s call, made {html.escape(str(p.get('date', '')))}.</p>"
            + (f"<p>{html.escape(notes)}</p>" if notes else "")
        )
        shell = _shell_html(
            "a graded prediction",
            text,
            f"{verdict} — {coach}'s call. {notes[:140]}",
            meta,
            body,
            f"/moments/prediction/{mid}/",
            f"/moments/assets/prediction-{mid}.png",
            f"{SITE_BASE}/coaching/scorecard/",
        )
        url = _put_moment(s3, "prediction", mid, card, shell)
        if plan:
            plan.rendered(plan_key, digest)
        out.append({"key": _prediction_key(p), "status": p["status"], "url": url})
    return out


# ── #4404: retiring an obituary whose record left /api/wrong ────────────────
#
# The sweep used to only ADD: an obituary that left the feed (the 20 re-graded 08-10
# docket obituaries #4216 tombstoned, six earlier ones) kept a public shell and card that
# still answered 200. Retirement is a WEBSITE REDIRECT written with the one S3 action the
# og-image-generator role holds (``s3:PutObject`` on ``generated/moments/*`` —
# ``cdk/stacks/role_policies_operational.py::operational_og_image_generator``; it has no
# DeleteObject, no ListBucket and no GetObject on this prefix). CloudFront's
# S3GeneratedOrigin is the S3 WEBSITE endpoint, which answers an object carrying
# ``x-amz-website-redirect-location`` with a 301, so the retired permalink lands on the
# live feed and the retired card on the site's default card. Re-sweeping writes the same
# redirect again (idempotent), and an id that comes back to the feed is re-published by
# the ordinary put above it, which replaces the redirect object — reversible by
# construction.
#
# Without ListBucket the sweep cannot see what it published before, so the set of
# published ids travels in the index it already writes (``wrong_published``, read back
# over the public viewer path on the next run). The ids below were published BEFORE that
# ledger existed and had already left /api/wrong when this landed — measured 2026-09-29
# 03:0xZ from ``aws s3api list-objects-v2 --prefix generated/moments/wrong/`` (58
# shells) against /api/wrong (32 obituaries): 26 shells with no live record.
_WRONG_PUBLISHED_BEFORE_LEDGER = frozenset(
    {
        # the 08-10 calorie docket, re-graded daily 09-07..09-26 (#4216) — written 2026-09-27
        "083335eb9bfb",
        "0cd229d2e84d",
        "16158919edec",
        "1785b8755064",
        "29cedc543062",
        "2ff9fb8af9bd",
        "44ed81df0500",
        "498689084147",
        "4c4d595911e7",
        "54ac38a33e05",
        "566d479b73c3",
        "838142063466",
        "89d11f92b6e2",
        "9fa395f01e74",
        "a25d1f933993",
        "aa98dbbed1dd",
        "af8379b7b19a",
        "b48f0f27eebc",
        "b5fa99579144",
        "e9be568575a3",
        # earlier obituaries last written 2026-08-31 that the feed no longer serves
        "06d946009470",
        "2783a79ac934",
        "3bcf4f94460a",
        "3bed4057f444",
        "4493f1d453e5",
        "a436a5df6237",
    }
)
RETIRED_WRONG_SHELL_TARGET = "/method/wrong/"  # the live feed the obituary belonged to
RETIRED_WRONG_CARD_TARGET = "/assets/images/og-home.png"  # the feed page's own og:image


def fetch_previous_index():
    """The index the previous run wrote, read over the PUBLIC viewer path (the role holds
    no GetObject on ``generated/moments/index.json``); ``None`` when it cannot be read."""
    try:
        req = urllib.request.Request(f"{SITE_BASE}/moments/index.json", headers={"accept": "application/json"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            index = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"[moments] previous moments index unreadable ({e}); retirement uses the seed ledger only")
        return None
    return index if isinstance(index, dict) else None


_UNREAD = object()  # "fetch it yourself" — distinct from None, which means "already tried, unreadable"


def _previous_wrong_ledger(index=_UNREAD):
    """The ids the previous run published, read from the index it wrote.

    ``index`` is the already-fetched previous index (the sweep reads it once); omitted, it
    is fetched here (``None`` = already tried, unreadable). Returns ``None`` when the index cannot be read, so the caller can say
    so rather than silently treating "unknown" as "none"."""
    if index is _UNREAD:
        index = fetch_previous_index()
    if index is None:
        return None
    ids = {str(i) for i in (index.get("wrong_published") or []) if str(i).strip()}
    ids |= {str(i) for i in (index.get("wrong") or {}) if str(i).strip()}
    return ids


def _put_redirect(s3, key, target):
    s3.put_object(
        Bucket=S3_BUCKET,
        Key=key,
        Body=b"",
        ContentType="text/html; charset=utf-8",
        CacheControl="max-age=300",
        WebsiteRedirectLocation=target,
    )


def _retire_wrong(s3, live_ids, previous_ids, already_retired=frozenset()):
    """#4404: redirect every published obituary shell + card whose id left /api/wrong.

    ``live_ids`` is EVERY id the feed served this run (``None`` when the fetch failed).
    Returns ``(published, retired)`` — the ledger the index carries forward, and the ids
    retired this run. Never touches a live id; retires nothing on a failed or empty feed
    (an empty list is likelier a degraded read than every record leaving at once)."""
    known = set(_WRONG_PUBLISHED_BEFORE_LEDGER) | set(previous_ids or ())
    if not live_ids:
        why = "feed fetch failed" if live_ids is None else "feed served no obituaries"
        print(f"[moments] wrong-feed retirement held: {why}; retired 0 page(s)")
        return sorted(known | set(live_ids or ())), []
    retired = sorted(known - set(live_ids))
    # #5421: an id the previous run already retired and that is still not live keeps the
    # redirect it was given; re-writing ~90 identical pairs every day cost ~5 s of the budget.
    for oid in (i for i in retired if i not in already_retired):
        _put_redirect(s3, f"{MOMENTS_PREFIX}wrong/{oid}/index.html", RETIRED_WRONG_SHELL_TARGET)
        _put_redirect(s3, f"{MOMENTS_PREFIX}assets/wrong-{oid}.png", RETIRED_WRONG_CARD_TARGET)
    fresh = len([i for i in retired if i not in already_retired])
    print(f"[moments] retired {len(retired)} wrong-feed page(s) + card(s) whose record left /api/wrong ({fresh} written this run)")
    return sorted(known | set(live_ids)), retired


def _fetch_wrong_feed():
    """The public /api/wrong payload, or ``None`` when it cannot be read."""
    try:
        req = urllib.request.Request(f"{SITE_BASE}/api/wrong", headers={"accept": "application/json"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if isinstance(data.get("data"), dict):
            data = data["data"]
    except Exception as e:
        print(f"[moments] wrong feed fetch skipped: {e}")
        return None
    return data


def _sweep_wrong(s3, plan=None):
    """#1377 (The Wrong Feed): one shareable obituary per GRADED failure — fetched from
    the PUBLIC /api/wrong payload so a card can never say more than the site publishes.

    The obituary id / permalink / og_image are read straight off the payload (the API
    already computed the stable slug), so the permalink shell, the OG card, and the
    front-end card all agree by construction. Sourced only from deterministic verdicts —
    never AI-asserted wrongness. Idempotent; an empty feed writes nothing.

    #4404: returns ``(out, ledger)`` — ``ledger`` is ``{"published": [...], "retired":
    [...]}`` from ``_retire_wrong``, which the index carries so the next run knows every
    id it ever published."""
    already_retired = plan.prior_retired if plan else frozenset()
    previous = _previous_wrong_ledger(plan.previous_index) if plan else _previous_wrong_ledger()
    data = _fetch_wrong_feed()
    if data is None:
        published, retired = _retire_wrong(s3, None, previous, already_retired)
        return {}, {"published": published, "retired": retired}
    obituaries = data.get("obituaries") or []
    live_ids = {str(o.get("id", "")).strip() for o in obituaries} - {""}
    out = {}
    for o in obituaries:
        oid = str(o.get("id", "")).strip()
        believed = (o.get("believed") or "").strip()
        if not oid or not believed:
            continue
        date = str(o.get("date") or "").strip()
        coach = str(o.get("coach") or "the board").strip()
        meta = f"{coach} · {date} · REFUTED"
        number = (o.get("number") or "").strip()
        changed = (o.get("what_changed") or "").strip()
        plan_key = f"wrong/{oid}"
        action, digest = plan.decide(plan_key, [believed, meta, number, changed]) if plan else (RENDER, None)
        if action != RENDER:
            if action == SKIP or plan.exists(plan_key):
                out[oid] = f"/moments/wrong/{oid}/"
            continue
        card = build_moment_card("a graded failure — the AI was wrong", believed, meta, "graded by the evaluator, not asserted")
        body = (
            f"<p><strong>We believed:</strong> {html.escape(believed)}</p>"
            + (f"<p><strong>The number that killed it:</strong> {html.escape(number)}</p>" if number else "")
            + (f"<p><strong>What changed:</strong> {html.escape(changed)}</p>" if changed else "")
        )
        shell = _shell_html(
            "a graded failure — the AI was wrong",
            believed,
            f"REFUTED — {coach}'s call, graded against the data. {number}"[:200],
            meta,
            body,
            f"/moments/wrong/{oid}/",
            f"/moments/assets/wrong-{oid}.png",
            f"{SITE_BASE}/method/wrong/#obit-{oid}",
        )
        out[oid] = _put_moment(s3, "wrong", oid, card, shell)
        if plan:
            plan.rendered(plan_key, digest)
    print(f"[moments] swept {len(out)} wrong-feed obituary card(s)")
    published, retired = _retire_wrong(s3, live_ids, previous, already_retired)
    return out, {"published": published, "retired": retired}


def _post_slug(url):
    """/journal/posts/week-05/ -> week-05 (the stable per-post card slug)."""
    return (str(url or "").strip("/").split("/") or ["post"])[-1] or "post"


def _sweep_chronicles(s3, plan=None):
    """#405 (via the #595 engine): a per-chronicle honest-stats share card, drawn from
    generated/journal/posts.json — already-published values only (title, series label,
    the honest stats line). One 1200×630 card per post at /moments/assets/chronicle-*.png.

    The honest-stats line IS the creative — a week graded 57 with a broken streak is the
    point, never sanitized. Cards render through card_engine's `chronicle` type so they
    share the one brand template. Empty/malformed posts produce no card. Fail-soft: any
    error here never blocks the daily page cards or the other moment classes.
    """
    try:
        raw = s3.get_object(Bucket=S3_BUCKET, Key="generated/journal/posts.json")["Body"].read()
        posts = (json.loads(raw) or {}).get("posts", []) or []
    except Exception as e:
        print(f"[moments] chronicle sweep skipped (no posts.json): {e}")
        return []

    from web import card_engine

    out = {}
    for p in posts:
        url = (p.get("url") or "").strip()
        title = (p.get("title") or "").strip()
        if not url or not title:
            continue
        slug = _post_slug(url)
        plan_key = f"chronicle/{slug}"
        action, digest = (
            plan.decide(plan_key, [title, p.get("label") or "", (p.get("stats_line") or "").strip(), p.get("date") or ""])
            if plan
            else (RENDER, None)
        )
        if action != RENDER:
            if action == SKIP or plan.exists(plan_key):
                out[url] = f"/moments/assets/chronicle-{slug}.png"
            continue
        card = card_engine.render(
            "chronicle",
            {
                "title": title,
                "label": p.get("label") or "",
                "stats_line": (p.get("stats_line") or "").strip(),
                "date": p.get("date") or "",
            },
        )
        import io

        img_key = f"{MOMENTS_PREFIX}assets/chronicle-{slug}.png"
        buf = io.BytesIO()
        card.save(buf, format="PNG", optimize=True)
        buf.seek(0)
        _put(s3, img_key, buf.read(), "image/png", cache="max-age=86400")
        if plan:
            plan.rendered(plan_key, digest)
        out[url] = f"/moments/assets/chronicle-{slug}.png"
    print(f"[moments] swept {len(out)} chronicle card(s)")
    return out


def _current_attempt():
    """Which experiment attempt today belongs to — the highest key in the same
    CYCLE_GENESES registry /api/wall renders from. Imported lazily and fail-soft: an
    unavailable attempt number omits ", attempt N" from the caption, which is honest.
    Guessing one would not be."""
    try:
        from web.site_api_data import CYCLE_GENESES

        return max(CYCLE_GENESES) if CYCLE_GENESES else None
    except Exception as e:  # pragma: no cover — import-environment guard
        print(f"[moments] fingerprint attempt number unavailable ({e}); caption omits it")
        return None


def _fingerprint_metrics(stats):
    """Indirection over the Pillow-carrying og module (mirrors `build_moment_card`), so
    the sweep's contract — dating, captioning, the syndicatable flag — is testable
    without PIL installed."""
    from web import og_image_lambda as og

    return og.fingerprint_metrics(stats)


def _fingerprint_card(stats):
    """The unchanged #1379 card, drawn by the same function the page card uses."""
    from web import og_image_lambda as og

    return og.build_fingerprint(stats)


def _sweep_fingerprint(s3, stats):
    """#1402: the day's Daily Fingerprint, dated and made postable.

    The card itself is unchanged — `og_image_lambda.build_fingerprint` draws it, exactly
    as it does for /assets/images/og-fingerprint.png. What this adds is permanence and a
    caption: the page card is overwritten every day, so a share of it silently starts
    pointing at a different day's mark. Here it gets a dated permalink and a dated PNG
    that never move, plus the deterministic provenance caption from
    `content.fingerprint_broadcast`.

    A warming-up day (too few signals to earn the glow) still gets both artifacts — the
    sparse mark IS the honest render and the archive should have no holes — but comes
    back flagged `syndicatable: false` so no poster offers it (#1629 non-negotiable 11).

    Posting stays a human act: nothing here posts, and the payload's
    `automated_syndication` field records that ADR-140 rule 5 forbids an automated
    surface from doing so. Fail-soft, like every other class: an error here never blocks
    the daily page cards.
    """
    try:
        from content import fingerprint_broadcast as fb

        from web.fingerprint import SIGNAL_COUNT, build_mark

        today = datetime.now(PT).strftime("%Y-%m-%d")  # #2414: the mark's day must agree with the cockpit (PT)
        mark = build_mark(today, _fingerprint_metrics(stats))
        payload = fb.build_broadcast(
            date_str=today,
            mark=mark,
            stats=stats,
            total_signals=SIGNAL_COUNT,
            attempt=_current_attempt(),
            generated_at=datetime.now(timezone.utc).isoformat(),
        )

        shell = _shell_html(
            "the daily fingerprint",
            f"The mark for {today}",
            f"A deterministic mark of {today} — {payload['signals_reported']} of {payload['signals_tracked']} tracked signals reported.",
            f"day mark · {today}",
            fb.shell_body_html(payload),
            payload["permalink"],
            payload["card_url"],
            f"{SITE_BASE}/data/wall/",
        )
        url = _put_moment(s3, "fingerprint", today, _fingerprint_card(stats), shell)
        if url != payload["permalink"]:  # pragma: no cover — key/URL contract guard
            print(f"[moments] fingerprint permalink mismatch: put {url} vs payload {payload['permalink']}")
        print(
            f"[moments] fingerprint {today}: {payload['signals_reported']}/{payload['signals_tracked']} signals, syndicatable={payload['syndicatable']}"
        )
        return payload
    except Exception as e:
        print(f"[moments] fingerprint sweep skipped: {e}")
        return None


def sweep_moments(s3, stats, time_left=None, force=False):
    """Run all moment classes; write the index the share buttons read.

    #5421: incremental and time-boxed — see ``SweepPlan``. ``time_left`` is the invocation's
    ``context.get_remaining_time_in_millis`` (``None`` = unbounded), ``force`` re-renders
    every moment regardless of the previous run's digests."""
    plan = SweepPlan(fetch_previous_index(), time_left=time_left, force=force)
    wrong, wrong_ledger = _sweep_wrong(s3, plan)  # #1377 — the graded-failure obituary feed (+ #4404 retirement)
    index = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "week": _sweep_week_recap(s3, stats),
        "qa": _sweep_board_answers(s3, plan),
        "predictions": _sweep_predictions(s3, plan),
        "chronicles": _sweep_chronicles(s3, plan),
        "wrong": wrong,
        "wrong_published": wrong_ledger["published"],  # #4404 — every id ever published; the next run's retirement input
        "wrong_retired": wrong_ledger["retired"],  # #4404 — ids whose shell + card now redirect
        "fingerprint": _sweep_fingerprint(s3, stats),  # #1402 — the day's dated mark + caption
        "digests": plan.digests,  # #5421 — moment key -> digest of what was last published; the next run's skip input
    }
    print(f"[moments] incremental sweep: {plan.summary()}")
    _put(s3, f"{MOMENTS_PREFIX}index.json", json.dumps(index).encode("utf-8"), "application/json", cache="max-age=300")
    n = (1 if index["week"] else 0) + len(index["qa"]) + len(index["predictions"]) + len(index["chronicles"]) + len(index["wrong"])
    n += 1 if index["fingerprint"] else 0
    print(
        f"[moments] swept {n} moment(s): week={bool(index['week'])} qa={len(index['qa'])} "
        f"predictions={len(index['predictions'])} chronicles={len(index['chronicles'])} wrong={len(index['wrong'])} "
        f"fingerprint={bool(index['fingerprint'])}"
    )
    return index
