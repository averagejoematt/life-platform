"""
ai_review_pack_lambda.py — Weekly AI review-pack email (#1442, QA strategy D3).

The human editorial plane (plane 4 of the QA strategy, epic #1425). AI generations
are gate-checked at write time (ADR-104 grounding gate) and archived at generation
time (#1441 / D2 — `lambdas/qa_archive.py`), but nothing guaranteed a *human*
eyeball over the week's actual AI output — review was ad-hoc screenshot archaeology.

This Lambda curates ONE weekly email: for the trailing 7 days it reads the D2
archive (generated/qa_archive/text/ + .../screenshots/) and lays out every AI
generation — Chronicle, Board answers, Coach commentary, State of Matthew, Field
notes, Coach memoirs — as a scannable digest with an inline snippet and a link to
the full archived object. One email = a guaranteed weekly human read of every AI
surface.

Ranked + tagged (#1688, epic #1687 S1): each generation is numbered (a STABLE number
so Matthew can correct by #N and the correction compounds — #1689/#1690), stack-ranked
most-likely-wrong→least, and tagged with a checkable claim + an error-class. Ranking is
HYBRID (`lambdas/review_pack_ranker.py`): deterministic heuristics ALWAYS (baseline-
mismatch, ungrounded-behavioral-verb, claim-density, hedge-absence), PLUS a cheap Haiku
"critic" pass layered on ONLY when the budget tier ≤ 1 (the epic-locked per-feature
policy — gated directly on tier, not budget_guard's generic band; at tier ≥ 2 the
deterministic ranking stands and Bedrock is never called).

Design notes:
  * READ-ONLY over the archive. It curates already-generated, already-gate-passed
    text. It makes at most ONE cheap Haiku critic call per week, and ONLY at budget
    tier ≤ 1 — so it needs a bedrock:InvokeModel grant + a budget-tier SSM read
    (added to the ai-review-pack role in role_policies.py by #1688). At tier ≥ 2 it
    makes NO Bedrock call at all (the deterministic ranking is the zero-cost floor).
  * The archive is S3-private (generated/qa_archive/ is NOT routed by CloudFront —
    web_stack only forwards specific /generated sub-paths). So the "link" for each
    generation is an AWS S3 console deep-link (auth-gated), not a public URL — the
    honest, no-new-exposure choice for an internal operator email.
  * Screenshots are the daily visual-qa renders the D2 leg uploads. Per its own
    caveat these are daily-sweep captures (what a reader saw that day), not
    per-generation captures — the email says so.
  * Degrades gracefully: a surface that generated nothing is shown as an explicit
    "nothing this week" note; a totally-quiet week still sends (the weekly eyeball
    is the point). A single corrupt archived object is skipped and counted, never
    fatal — the editorial email is the priority.

Schedule: Sunday 18:00 UTC (fixed, no DST drift) — after the Sunday weekly-digest
(16:00 UTC), covering the week just ended.

Liveness: operator-email class (a missing Sunday issue is noticed by its reader),
dated-exempt in tests/test_heartbeat_completeness.py (#1455).
"""

import html
import logging
import os
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import boto3
import qa_archive

# #1691 (epic #1687): re-run the baseline-freshness gate over each archived
# coach_brief's TEXT so a stale-baseline/stale-phase brief surfaces a visible flag
# to the human reader — even for historical entries (re-running over the archived
# text, not trusting generation-time meta). Both shared modules ship in every
# bundle (#781); import fail-soft so the email never dies on a missing module.
try:
    import grounded_generation as _gg
    from constants import EXPERIMENT_BASELINE_WEIGHT_LBS, EXPERIMENT_START_DATE
except Exception:  # pragma: no cover — bundle-dependent; the flag simply degrades off
    _gg = None
    EXPERIMENT_BASELINE_WEIGHT_LBS = None
    EXPERIMENT_START_DATE = None

# #1688 (epic #1687): the Hybrid ranker + tagger. Bundled (#781); import fail-soft so
# a missing module degrades the pack to the legacy flat rendering rather than dying.
try:
    import review_pack_ranker as _ranker
except Exception:  # pragma: no cover — bundle-dependent; ranking simply degrades off
    _ranker = None

logger = logging.getLogger()
logger.setLevel(logging.INFO)

REGION = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
BUCKET = os.environ.get("BUCKET_NAME", "matthew-life-platform")
RECIPIENT = os.environ.get("EMAIL_RECIPIENT", "lifeplatform@mattsusername.com")
SENDER = os.environ.get("EMAIL_SENDER", "lifeplatform@mattsusername.com")
WINDOW_DAYS = int(os.environ.get("REVIEW_WINDOW_DAYS", "7"))

# Surface render order + human labels. Keyed by the qa_archive surface ids
# (lambdas/qa_archive.SURFACES) so a new surface there shows up here the moment
# it archives — unknown surfaces fall through to a title-cased label.
SURFACE_ORDER = ("chronicle", "state_of_matthew", "coach_brief", "board_ask", "field_notes", "memoir")
SURFACE_LABELS = {
    "chronicle": "Chronicle",
    "state_of_matthew": "State of Matthew",
    "coach_brief": "Coach Commentary",
    "board_ask": "Board Answers",
    "field_notes": "Field Notes",
    "memoir": "Coach Memoirs",
}
SURFACE_ICONS = {
    "chronicle": "📖",
    "state_of_matthew": "🧭",
    "coach_brief": "🗣️",
    "board_ask": "🎓",
    "field_notes": "🔬",
    "memoir": "📓",
}

_SNIPPET_CHARS = 360


def week_dates(end=None):
    """The WINDOW_DAYS calendar dates (YYYY-MM-DD), oldest-first, ending today (UTC)."""
    end = end or datetime.now(timezone.utc).date()
    return [(end - timedelta(days=i)).isoformat() for i in range(WINDOW_DAYS - 1, -1, -1)]


def _console_url(key):
    """AWS S3 console deep-link to one archived object (auth-gated — the archive is
    S3-private, not CloudFront-routed)."""
    return f"https://{REGION}.console.aws.amazon.com/s3/object/{BUCKET}?region={REGION}&prefix={quote(key)}"


def gather_week(dates):
    """Read the archive for `dates`. Returns:
      by_surface: {surface: [entry_dict, ...]}  (entry = archived JSON doc + _key)
      screenshots_by_date: {date: [key, ...]}
      read_errors: int  (objects that listed but failed to read/parse — skipped)

    list_day() raises loudly on AWS errors (the review pack wants a failed week
    visible, not silently empty). Individual object reads are fail-soft so one bad
    object can never sink the whole editorial email.
    """
    by_surface = {}
    screenshots_by_date = {}
    read_errors = 0
    for d in dates:
        for key in qa_archive.list_day(d, kind="text"):
            try:
                entry = qa_archive.read_entry(key)
            except Exception as e:  # noqa: BLE001 — skip the corrupt object, keep the email
                read_errors += 1
                logger.warning(f"[ai-review-pack] unreadable archive object {key}: {e}")
                continue
            entry["_key"] = key
            by_surface.setdefault(entry.get("surface", "unknown"), []).append(entry)
        shots = qa_archive.list_day(d, kind="screenshots")
        if shots:
            screenshots_by_date[d] = shots
    # Newest-first within each surface for a natural reading order.
    for entries in by_surface.values():
        entries.sort(key=lambda e: e.get("archived_at", ""), reverse=True)
    return by_surface, screenshots_by_date, read_errors


def _label(surface):
    return SURFACE_LABELS.get(surface, surface.replace("_", " ").title())


def _snippet(text):
    text = (text or "").strip()
    if len(text) > _SNIPPET_CHARS:
        text = text[:_SNIPPET_CHARS].rstrip() + "…"
    return html.escape(text) or "<em>(empty)</em>"


def _meta_line(entry):
    """A compact, human-friendly context line per surface, from the archived meta."""
    surface = entry.get("surface")
    meta = entry.get("meta") or {}
    variant = entry.get("variant")
    bits = []
    if surface == "board_ask":
        if meta.get("question"):
            bits.append("Q: " + str(meta["question"]))
        if meta.get("grounded") is not None:
            bits.append("grounded" if meta.get("grounded") else "ungrounded")
    elif surface == "chronicle":
        if meta.get("title"):
            bits.append(str(meta["title"]))
        if meta.get("week_number") is not None:
            bits.append(f"week {meta['week_number']}")
        if meta.get("status"):
            bits.append(str(meta["status"]))
    elif surface == "state_of_matthew":
        bits.append("narrated" if meta.get("narrated") else "fallback (not AI-narrated)")
        if meta.get("model"):
            bits.append(str(meta["model"]))
    elif surface == "coach_brief":
        if meta.get("output_type"):
            bits.append(str(meta["output_type"]))
    elif surface == "memoir":
        if meta.get("quarter"):
            bits.append(f"quarter {meta['quarter']}")
    elif surface == "field_notes":
        if meta.get("week"):
            bits.append(f"week {meta['week']}")
    if variant:
        bits.insert(0, str(variant))
    return html.escape(" · ".join(str(b) for b in bits))


def _freshness_findings_for(entry):
    """#1691: re-run the baseline-freshness gate over a coach_brief entry's archived
    TEXT (not the generation-time meta) so historical stale-baseline/stale-phase
    briefs surface too. Returns [] for non-coach_brief entries, a missing bundle
    module, or no findings. Fail-soft — a bad entry never breaks the email."""
    if _gg is None or entry.get("surface") != "coach_brief":
        return []
    meta = entry.get("meta") or {}
    gen_date = meta.get("generation_date") or entry.get("date")
    if not gen_date:
        return []
    try:
        return _gg.baseline_freshness_findings(
            entry.get("text") or "",
            generation_date_iso=gen_date,
            baseline_lbs=EXPERIMENT_BASELINE_WEIGHT_LBS,
            start_date_iso=EXPERIMENT_START_DATE,
        )
    except Exception as e:  # pragma: no cover — advisory flag must never break the pack
        logger.warning(f"[ai_review_pack] freshness re-check failed for {entry.get('_key')}: {e}")
        return []


def _freshness_flag_html(entry):
    findings = _freshness_findings_for(entry)
    if not findings:
        return ""
    details = "; ".join(str(f.get("detail", f.get("type", ""))) for f in findings)
    return (
        '<div style="color:#fca5a5;background:#3a1216;border:1px solid #7f1d1d;border-radius:6px;'
        'font-size:12px;padding:6px 8px;margin:2px 0 8px;">'
        f"&#9888;&#65039; baseline-freshness: {html.escape(details)}</div>"
    )


# #1688: per-error-class chip colors. Keyed by coach_corrections.ERROR_CLASSES values.
_ERROR_CLASS_COLORS = {
    "stale-baseline": ("#fca5a5", "#3a1216", "#7f1d1d"),
    "ungrounded-behavioral": ("#fdba74", "#3a2410", "#7c2d12"),
    "cross-coach-inconsistency": ("#c4b5fd", "#231a3a", "#5b21b6"),
    "framing": ("#fcd34d", "#332a10", "#78350f"),
    "checkable-metric": ("#93c5fd", "#111f3a", "#1e3a8a"),
    "hedged-safe": ("#86efac", "#0f2a1a", "#14532d"),
    "defense-held": ("#86efac", "#0f2a1a", "#14532d"),
    "other": ("#9ca3af", "#1f2430", "#374151"),
}


def _tag_chip_html(error_class):
    fg, bg, border = _ERROR_CLASS_COLORS.get(error_class, _ERROR_CLASS_COLORS["other"])
    return (
        f'<span style="display:inline-block;font-size:11px;font-weight:600;color:{fg};background:{bg};'
        f'border:1px solid {border};border-radius:10px;padding:1px 8px;">{html.escape(error_class)}</span>'
    )


def _flags_html(analysis):
    """#1688: render the deterministic findings (baseline/genesis/behavioral/cross-coach)
    as one advisory block — folds in the #1691 baseline-freshness flag. [] → ""."""
    if not analysis:
        return ""
    rows = []
    for f in analysis.get("baseline", []):
        rows.append("&#9888;&#65039; baseline-freshness: " + html.escape(str(f.get("detail", f.get("type", "")))))
    for f in analysis.get("genesis", []):
        rows.append("&#9888;&#65039; genesis-mismatch: " + html.escape(str(f.get("detail", ""))))
    for f in analysis.get("behavioral", []):
        rows.append("&#9888;&#65039; ungrounded-behavioral: " + html.escape(str(f.get("detail", ""))))
    for f in analysis.get("cross_coach", []):
        rows.append("&#9888;&#65039; cross-coach: " + html.escape(str(f.get("detail", ""))))
    if not rows:
        return ""
    inner = "<br>".join(rows)
    return (
        '<div style="color:#fca5a5;background:#3a1216;border:1px solid #7f1d1d;border-radius:6px;'
        f'font-size:12px;padding:6px 8px;margin:2px 0 8px;">{inner}</div>'
    )


def _claim_html(analysis):
    if not analysis or not analysis.get("checkable_claim"):
        return ""
    return (
        '<div style="color:#cbd5e1;font-size:12px;margin:2px 0 6px;">'
        f'<span style="color:#6b7280;">checkable claim:</span> {html.escape(analysis["checkable_claim"])}</div>'
    )


def _entry_card(entry, num=None, analysis=None):
    when = entry.get("archived_at", "")[:16].replace("T", " ")
    meta_line = _meta_line(entry)
    meta_html = f'<div style="color:#9ca3af;font-size:12px;margin:2px 0 8px;">{meta_line}</div>' if meta_line else ""
    # #1688: prefer the analysis-driven flags/claim/tag; fall back to the legacy #1691
    # freshness flag when no analysis was computed (ranker missing → graceful degrade).
    if analysis is not None:
        flags_html = _flags_html(analysis)
        claim_html = _claim_html(analysis)
        tag_html = _tag_chip_html(analysis.get("error_class", "other"))
    else:
        flags_html = _freshness_flag_html(entry)
        claim_html = ""
        tag_html = ""
    num_badge = f'<span style="color:#f59e0b;font-weight:700;">#{num}</span> ' if num is not None else ""
    return f"""
      <div style="background:#12162e;border:1px solid #2a2d4a;border-radius:8px;padding:12px 14px;margin-bottom:10px;">
        <div style="display:flex;justify-content:space-between;align-items:center;font-size:11px;color:#6b7280;margin-bottom:4px;">
          <span>{num_badge}{html.escape(when)} UTC</span>
          <span>{tag_html} <a href="{_console_url(entry['_key'])}" style="color:#6366f1;text-decoration:none;">open in S3 &rsaquo;</a></span>
        </div>
        {meta_html}
        {claim_html}
        {flags_html}
        <div style="color:#d1d5db;font-size:13px;line-height:1.5;white-space:pre-wrap;">{_snippet(entry.get('text'))}</div>
      </div>"""


def _ranked_digest_section(ranking):
    """#1688 (AC4): the stack-ranked digest — every generation, most-likely-wrong → least,
    each with its STABLE number, provenance, error-class tag, checkable claim, and flags.
    This is the headline of the uplifted pack. Empty ranking → "" (quiet week degrades)."""
    ranked = (ranking or {}).get("ranked") or []
    if not ranked:
        return ""
    critic_note = (
        ' <span style="color:#22c55e;">· Haiku critic layered on</span>'
        if ranking.get("critic_ran")
        else f' <span style="color:#6b7280;">· deterministic only (budget tier {ranking.get("tier")})</span>'
    )
    rows = []
    for n, entry, analysis in ranked:
        surface = entry.get("surface", "unknown")
        provenance_bits = [_label(surface)]
        if entry.get("variant"):
            provenance_bits.append(str(entry["variant"]))
        provenance_bits.append(entry.get("date", ""))
        grounded = (entry.get("meta") or {}).get("grounded")
        if grounded is not None:
            provenance_bits.append("grounded" if grounded else "ungrounded")
        provenance = html.escape(" · ".join(str(b) for b in provenance_bits if b))
        claim = html.escape(analysis.get("checkable_claim") or "(no checkable claim extracted)")
        crit = analysis.get("critic")
        score_bits = f'score {analysis.get("score")}' + (f" (critic {crit})" if crit is not None else "")
        rows.append(
            f"""
      <div style="background:#12162e;border:1px solid #2a2d4a;border-radius:8px;padding:10px 12px;margin-bottom:8px;">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">
          <span style="font-size:13px;font-weight:700;color:#f59e0b;">#{n}</span>
          <span>{_tag_chip_html(analysis.get("error_class", "other"))} <span style="color:#6b7280;font-size:11px;">{html.escape(score_bits)}</span></span>
        </div>
        <div style="color:#9ca3af;font-size:11px;margin-bottom:4px;">{provenance} · <a href="{_console_url(entry['_key'])}" style="color:#6366f1;text-decoration:none;">open in S3 &rsaquo;</a></div>
        <div style="color:#d1d5db;font-size:12px;line-height:1.45;">{claim}</div>
        {_flags_html(analysis)}
      </div>"""
        )
    return f"""
    <div style="margin-bottom:26px;">
      <div style="font-size:14px;font-weight:700;color:#ffffff;border-bottom:1px solid #2a2d4a;padding-bottom:6px;margin-bottom:10px;">
        🎯 Stack-ranked · most-likely-wrong first <span style="color:#6b7280;font-weight:400;font-size:12px;">({len(ranked)})</span>{critic_note}
      </div>
      <div style="color:#6b7280;font-size:11px;margin-bottom:8px;">Correct any item by its number (#N) — the number is stable for the week. Corrections compound (epic #1687).</div>
      {"".join(rows)}
    </div>"""


def _surface_section(surface, entries, nmap=None):
    icon = SURFACE_ICONS.get(surface, "•")
    label = _label(surface)
    if not entries:
        body = '<div style="color:#6b7280;font-size:12px;font-style:italic;padding:6px 0;">Nothing generated this week.</div>'
    else:
        nmap = nmap or {}
        cards = []
        for e in entries:
            num, analysis = nmap.get(e.get("_key"), (None, None))
            cards.append(_entry_card(e, num=num, analysis=analysis))
        body = "".join(cards)
    return f"""
    <div style="margin-bottom:26px;">
      <div style="font-size:14px;font-weight:700;color:#ffffff;border-bottom:1px solid #2a2d4a;padding-bottom:6px;margin-bottom:10px;">
        {icon} {html.escape(label)} <span style="color:#6b7280;font-weight:400;font-size:12px;">({len(entries)})</span>
      </div>
      {body}
    </div>"""


def _screenshots_section(screenshots_by_date):
    total = sum(len(v) for v in screenshots_by_date.values())
    if not total:
        inner = '<div style="color:#6b7280;font-size:12px;font-style:italic;">No page screenshots archived this week.</div>'
    else:
        rows = []
        for d in sorted(screenshots_by_date):
            keys = screenshots_by_date[d]
            links = " · ".join(
                f'<a href="{_console_url(k)}" style="color:#6366f1;text-decoration:none;">{html.escape(k.rsplit("/", 1)[-1])}</a>'
                for k in sorted(keys)
            )
            rows.append(
                f'<div style="font-size:12px;color:#9ca3af;margin-bottom:6px;"><span style="color:#d1d5db;">{d}</span> — {links}</div>'
            )
        inner = "".join(rows)
    return f"""
    <div style="margin-bottom:26px;">
      <div style="font-size:14px;font-weight:700;color:#ffffff;border-bottom:1px solid #2a2d4a;padding-bottom:6px;margin-bottom:10px;">
        🖼️ Page screenshots <span style="color:#6b7280;font-weight:400;font-size:12px;">({total})</span>
      </div>
      <div style="color:#6b7280;font-size:11px;margin-bottom:8px;">Daily visual-QA renders of the AI pages — what a reader saw that day (not per-generation captures).</div>
      {inner}
    </div>"""


def compute_ranking(by_surface, *, tier_reader=None, invoke_fn=None):
    """#1688: HYBRID rank the week's pack (deterministic heuristics + tier-gated Haiku
    critic). Returns the ranker's result dict, or None if the ranker module is missing
    (graceful degrade to the legacy flat rendering). This is where the LIVE tier gate +
    Bedrock call happen — `build_html` never triggers them (it renders a passed-in or
    deterministic-only ranking), so unit tests stay offline."""
    if _ranker is None:
        return None
    return _ranker.rank_pack(
        by_surface,
        baseline_lbs=EXPERIMENT_BASELINE_WEIGHT_LBS,
        start_date_iso=EXPERIMENT_START_DATE,
        surface_order=SURFACE_ORDER,
        tier_reader=tier_reader,
        invoke_fn=invoke_fn,
    )


def _nmap_from_ranking(ranking):
    """{_key: (number, analysis)} so the per-surface cards can show each item's stable
    number + tag + flags."""
    if not ranking:
        return {}
    analyses = ranking.get("analyses") or {}
    return {entry.get("_key"): (n, analyses.get(n)) for n, entry in ranking.get("numbered", [])}


def build_html(dates, by_surface, screenshots_by_date, read_errors, ranking=None):
    total = sum(len(v) for v in by_surface.values())
    active_surfaces = sum(1 for s in SURFACE_ORDER if by_surface.get(s))
    start_label = _fmt_date(dates[0])
    end_label = _fmt_date(dates[-1])

    # No live ranking supplied (unit tests / degraded path): compute a DETERMINISTIC-ONLY
    # ranking — the tier_reader is pinned above the critic ceiling so no Bedrock call and
    # no SSM read ever fire from build_html. _run() supplies the real, tier-gated ranking.
    if ranking is None:
        ranking = compute_ranking(by_surface, tier_reader=lambda: 99)

    nmap = _nmap_from_ranking(ranking)
    sections = _ranked_digest_section(ranking)
    sections += "".join(_surface_section(s, by_surface.get(s, []), nmap=nmap) for s in SURFACE_ORDER)
    # Any archived surface not in our known order still gets shown (fail-open).
    for s in sorted(set(by_surface) - set(SURFACE_ORDER)):
        sections += _surface_section(s, by_surface[s], nmap=nmap)
    sections += _screenshots_section(screenshots_by_date)

    err_html = ""
    if read_errors:
        err_html = (
            f'<div style="color:#fb923c;font-size:12px;margin-top:6px;">'
            f"⚠️ {read_errors} archived object(s) could not be read and were skipped — check CloudWatch.</div>"
        )

    return f"""<div style="max-width:640px;margin:0 auto;background:#1a1a2e;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;padding:22px;color:#e0e0e0;">
  <div style="text-align:center;margin-bottom:24px;">
    <div style="font-size:11px;letter-spacing:2px;color:#6366f1;font-weight:600;margin-bottom:4px;">LIFE PLATFORM · EDITORIAL REVIEW</div>
    <div style="font-size:23px;font-weight:700;color:#ffffff;">🗂️ Weekly AI Review Pack</div>
    <div style="color:#9ca3af;font-size:13px;margin-top:4px;">{start_label} – {end_label}</div>
    <div style="margin-top:10px;font-size:12px;color:#9ca3af;">
      <span style="color:#f59e0b;font-weight:700;">{total}</span> generation(s) across
      <span style="color:#f59e0b;font-weight:700;">{active_surfaces}</span> surface(s)
    </div>
    {err_html}
  </div>
  <div style="color:#9ca3af;font-size:12px;line-height:1.5;margin-bottom:20px;">
    The week's AI output, gate-passed and archived at generation time. Scan each surface;
    open any object in S3 for the full text. This is the human editorial pass over every AI surface.
  </div>
  {sections}
  <div style="text-align:center;padding:16px 0;border-top:1px solid #2a2d4a;margin-top:12px;">
    <div style="color:#6b7280;font-size:11px;">Weekly AI Review Pack · Life Platform · QA editorial plane (#1442)</div>
  </div>
</div>"""


def _fmt_date(d):
    try:
        return datetime.strptime(d, "%Y-%m-%d").strftime("%b %-d")
    except Exception:
        return d


def record_email_send(table, lambda_name):
    """Write a completion record so the status page can track the last send."""
    import time as _time

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        table.put_item(
            Item={
                "pk": f"USER#matthew#SOURCE#email_log#{lambda_name}",
                "sk": f"DATE#{today}",
                "sent_at": datetime.now(timezone.utc).isoformat(),
                "status": "success",
                "ttl": int(_time.time()) + 86400 * 90,
            }
        )
    except Exception as e:
        logger.info(f"[ai-review-pack] status-tracking write failed (non-fatal): {e}")


def lambda_handler(event, context):
    try:
        return _run(event, context)
    except Exception as e:
        logger.error("Weekly AI Review Pack failed: %s", e)
        raise


def _run(event, context):
    logger.info("Weekly AI Review Pack starting...")
    dates = week_dates()
    by_surface, screenshots_by_date, read_errors = gather_week(dates)
    total = sum(len(v) for v in by_surface.values())
    logger.info(
        f"[ai-review-pack] {total} generations, {sum(len(v) for v in screenshots_by_date.values())} screenshots, {read_errors} read errors over {dates[0]}..{dates[-1]}"
    )

    # #1688: HYBRID ranking — deterministic heuristics always; the Haiku critic layers on
    # ONLY at budget tier ≤ 1 (the tier gate lives in review_pack_ranker.rank_pack, read
    # from budget_guard.current_tier). Fail-soft: a ranker/Bedrock error degrades to the
    # legacy flat rendering, never a lost editorial email.
    ranking = None
    try:
        ranking = compute_ranking(by_surface)
        if ranking is not None:
            logger.info(
                f"[ai-review-pack] ranked {len(ranking.get('numbered', []))} items; critic_ran={ranking.get('critic_ran')} tier={ranking.get('tier')}"
            )
    except Exception as e:  # pragma: no cover — ranking is advisory; never sink the email
        logger.warning(f"[ai-review-pack] ranking failed (non-fatal, legacy render): {e}")
        ranking = None

    html_body = build_html(dates, by_surface, screenshots_by_date, read_errors, ranking=ranking)
    subject = f"🗂️ Weekly AI Review Pack · {_fmt_date(dates[0])}–{_fmt_date(dates[-1])} · {total} generation(s)"

    ses = boto3.client("sesv2", region_name=REGION)
    ses.send_email(
        FromEmailAddress=SENDER,
        Destination={"ToAddresses": [RECIPIENT]},
        Content={
            "Simple": {
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": {"Html": {"Data": html_body, "Charset": "UTF-8"}},
            }
        },
    )
    logger.info(f"Sent: {subject}")

    table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE_NAME)
    record_email_send(table, "ai-review-pack")
    return {
        "statusCode": 200,
        "body": f"{total} generations across {sum(1 for s in by_surface if by_surface[s])} surfaces; {read_errors} read errors",
    }
