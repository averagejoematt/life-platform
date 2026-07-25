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
import urllib.request
from datetime import datetime, timezone

S3_BUCKET = "matthew-life-platform"
SITE_BASE = "https://averagejoematt.com"
MOMENTS_PREFIX = "generated/moments/"


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
    s3.put_object(Bucket=S3_BUCKET, Key=key, Body=body, ContentType=content_type, CacheControl=cache)


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


def _sweep_week_recap(s3, stats):
    """The weekly recap — refreshed daily under the ISO-week permalink."""
    journey = stats.get("journey") or {}
    vitals = stats.get("vitals") or {}
    platform = stats.get("platform") or {}
    if not (journey or vitals):
        return None  # empty moment → no card, no shell
    iso = datetime.now(timezone.utc).isocalendar()
    wid = f"{iso.year}-W{iso.week:02d}"
    bits = []
    if journey.get("lost_lbs") is not None:
        bits.append(f"{round(journey['lost_lbs'], 1)} lbs down")
    if vitals.get("hrv_ms") is not None:
        bits.append(f"HRV {round(vitals['hrv_ms'])} ms")
    if platform.get("tier0_streak") is not None:
        bits.append(f"streak {int(platform['tier0_streak'])}d")
    if platform.get("days_in") is not None:
        bits.append(f"day {int(platform['days_in'])}")
    meta = " · ".join(bits)
    title = f"The week so far — {wid}"
    card = build_moment_card("the weekly recap", title, meta, f"live numbers as of {datetime.now(timezone.utc):%Y-%m-%d}")
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


def _sweep_board_answers(s3):
    """Every published (moderated) reader Q&A gets its own permalink."""
    try:
        feed = json.loads(s3.get_object(Bucket=S3_BUCKET, Key="generated/board_answers/answers.json")["Body"].read())
    except Exception:
        return {}
    out = {}
    for a in feed.get("answers", []):
        mid = str(a.get("id", "")).strip()
        question = (a.get("question") or "").strip()
        if not mid or not question:
            continue
        answered = a.get("answered_at", "")
        responses = a.get("responses") or ([{"name": "The board", "text": a["answer"]}] if a.get("answer") else [])
        if not responses:
            continue  # a question without an answer is not a moment yet
        meta = f"asked {a.get('asked_at', '?')} · answered {answered} · {len(responses)} voice{'s' if len(responses) != 1 else ''}"
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
    return out


def _prediction_key(p):
    """The composite the front-end can rebuild without hashing: coach|date|text head."""
    return f"{p.get('coach_id', '')}|{p.get('date', '')}|{str(p.get('text', ''))[:60]}"


def _sweep_predictions(s3):
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
    for p in data.get("predictions", []):
        if p.get("status") not in ("confirmed", "refuted"):
            continue
        text = (p.get("text") or "").strip()
        if not text:
            continue
        mid = hashlib.sha256(_prediction_key(p).encode()).hexdigest()[:12]
        verdict = "CALLED IT" if p["status"] == "confirmed" else "GOT IT WRONG"
        coach = p.get("coach_name", "A coach")
        meta = f"{coach} · {p.get('date', '')} · {verdict}"
        card = build_moment_card(f"a graded prediction — {verdict.lower()}", text, meta, "every call is graded in public")
        notes = (p.get("outcome_notes") or "").strip()
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
        out.append({"key": _prediction_key(p), "status": p["status"], "url": url})
    return out


def _sweep_wrong(s3):
    """#1377 (The Wrong Feed): one shareable obituary per GRADED failure — fetched from
    the PUBLIC /api/wrong payload so a card can never say more than the site publishes.

    The obituary id / permalink / og_image are read straight off the payload (the API
    already computed the stable slug), so the permalink shell, the OG card, and the
    front-end card all agree by construction. Sourced only from deterministic verdicts —
    never AI-asserted wrongness. Idempotent; an empty feed writes nothing."""
    try:
        req = urllib.request.Request(f"{SITE_BASE}/api/wrong", headers={"accept": "application/json"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if isinstance(data.get("data"), dict):
            data = data["data"]
    except Exception as e:
        print(f"[moments] wrong feed fetch skipped: {e}")
        return {}
    out = {}
    for o in data.get("obituaries", []):
        oid = str(o.get("id", "")).strip()
        believed = (o.get("believed") or "").strip()
        if not oid or not believed:
            continue
        date = str(o.get("date") or "").strip()
        coach = str(o.get("coach") or "the board").strip()
        meta = f"{coach} · {date} · REFUTED"
        card = build_moment_card("a graded failure — the AI was wrong", believed, meta, "graded by the evaluator, not asserted")
        number = (o.get("number") or "").strip()
        changed = (o.get("what_changed") or "").strip()
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
    print(f"[moments] swept {len(out)} wrong-feed obituary card(s)")
    return out


def _post_slug(url):
    """/journal/posts/week-05/ -> week-05 (the stable per-post card slug)."""
    return (str(url or "").strip("/").split("/") or ["post"])[-1] or "post"


def _sweep_chronicles(s3):
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
        out[url] = f"/moments/assets/chronicle-{slug}.png"
    print(f"[moments] swept {len(out)} chronicle card(s)")
    return out


def sweep_moments(s3, stats):
    """Run all moment classes; write the index the share buttons read."""
    index = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "week": _sweep_week_recap(s3, stats),
        "qa": _sweep_board_answers(s3),
        "predictions": _sweep_predictions(s3),
        "chronicles": _sweep_chronicles(s3),
        "wrong": _sweep_wrong(s3),  # #1377 — the graded-failure obituary feed
    }
    _put(s3, f"{MOMENTS_PREFIX}index.json", json.dumps(index).encode("utf-8"), "application/json", cache="max-age=300")
    n = (1 if index["week"] else 0) + len(index["qa"]) + len(index["predictions"]) + len(index["chronicles"]) + len(index["wrong"])
    print(
        f"[moments] swept {n} moment(s): week={bool(index['week'])} qa={len(index['qa'])} "
        f"predictions={len(index['predictions'])} chronicles={len(index['chronicles'])} wrong={len(index['wrong'])}"
    )
    return index
