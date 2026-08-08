"""lambdas/web/site_api_thirdwall.py — the human voice on the record (/api/decisions, …).

Split out of ``site_api_coach.py`` (#1654 — god-module breakup). One seam: **what
Matthew said, and what the machine said back.** The weekly Field Notes (#2), the
logged decisions carrying an opt-in verbatim note (#1569, the widened Third Wall),
the consent-per-line journal pull-quotes (#1568, ADR-142), and the coach reactions
to things he said on tape or posted publicly (#1574/#1675 — the same wall with the
polarity inverted: the human leads, the coach reacts).

These four are one concern because they share the platform's strictest publishing
rule, and it lives here as ``_public_decision_note``: a VERBATIM human line is
**all-or-nothing**. If the serve-time content filter would alter it at all, the line
is withheld entirely rather than served mangled. Every surface in this module routes
its human-voice text through that one function; the machine-voice half beside it is
surgically scrubbed instead. Splitting them apart is how one of them quietly grows a
second, weaker screen.

The routed handler entrypoints stay in the ``site_api_coach`` facade as thin
delegators; the logic lives here. Handlers receive the facade's ``globals()`` as
``_g`` and read the monkeypatched/injectable state via ``_g["<name>"]``. This module
does NOT import the facade; no import cycle.
"""

import re

from boto3.dynamodb.conditions import Key
from experiment.phase_filter import singleton_visible, with_phase_filter  # ADR-058 / #946

from web.site_api_common import (
    PT,
    USER_PREFIX,
    _decimal_to_float,
    _ok,
    _scrub_blocked_terms,
    logger,
)


def handle_field_notes(event, *, _g):
    """GET /api/field_notes"""
    table = _g["table"]
    qs = event.get("queryStringParameters") or {}
    week_param = qs.get("week")
    fn_pk = f"{USER_PREFIX}field_notes"

    if week_param:
        # Single entry mode. #1085 (extends #946): field_notes are experiment-scoped —
        # list mode is phase-filtered but this get_item bypassed the filter, so a
        # ?week= request kept serving the WIPED cycle's note verbatim.
        item = table.get_item(Key={"pk": fn_pk, "sk": f"WEEK#{week_param}"}).get("Item")
        if not singleton_visible(item):
            return _ok({"entry": None, "week": week_param}, cache_seconds=300)
        item = _decimal_to_float(item)
        return _ok(
            {
                "entry": {
                    "week": item.get("week", week_param),
                    "week_label": item.get("week_label"),
                    "ai_present": item.get("ai_present", ""),
                    "ai_cautionary": item.get("ai_cautionary"),
                    "ai_affirming": item.get("ai_affirming"),
                    "ai_tone": item.get("ai_tone", "mixed"),
                    "ai_generated_at": item.get("ai_generated_at"),
                    "matthew_agreement": item.get("matthew_agreement"),
                    "matthew_logged_at": item.get("matthew_logged_at"),
                }
            },
            cache_seconds=300,
        )
    else:
        # List mode — return all weeks (most recent first)
        resp = table.query(
            **with_phase_filter(
                {  # ADR-058: hide pilot field notes
                    "KeyConditionExpression": Key("pk").eq(fn_pk),
                    "ScanIndexForward": False,
                    "Limit": 52,
                }
            )
        )
        items = _decimal_to_float(resp.get("Items", []))
        entries = [
            {
                "week": i.get("week", i.get("sk", "").replace("WEEK#", "")),
                # Genesis-anchored display label (Week N / Prologue) — the raw `week` is an
                # ISO calendar week (2026-W25) that read "w24/w25" on the site (#2). Producer
                # writes week_label; falls back to the ISO week until the backfill lands.
                "week_label": i.get("week_label"),
                "ai_tone": i.get("ai_tone", "mixed"),
                "ai_generated_at": i.get("ai_generated_at"),
                "has_matthew_response": bool(i.get("matthew_agreement")),
            }
            for i in items
        ]
        return _ok({"entries": entries, "count": len(entries)}, cache_seconds=300)


def handle_diary_reactions(event, *, _g):
    """GET /api/diary_reactions — coach reactions to things Matthew said (#1574/#1675).

    The lab-notes counterpart of the field-note Third Wall, with the polarity
    inverted: the HUMAN is the primary voice and the coach REACTS. Read-only. Only
    reactions the producer stored are returned; the source record itself never lands
    here — the producer (coach_diary_reaction) has already reduced it to a leak-proof
    public context (theme + optional cleared quote) before anything was persisted, so
    this endpoint serves stored fields verbatim.

    #1675: the same partition now also carries reactions to Matthew's PUBLIC social
    posts (the S2 origin membrane + the S5 sensitivity gate cleared them before any
    reaction was produced). ``kind`` tells the two apart — a private recording he
    cleared a sliver of, vs. a post he published himself — and a social row also
    carries the post's own public ``post_url``. One partition, one endpoint, one
    surface: no second reaction pipeline (the story's first acceptance criterion).

    Absent → empty list (AC3: the site renders nothing, no empty shell). Phase-filtered
    (ADR-058) so a wiped cycle's reactions don't resurface. Optional ?date= single mode,
    else list (most recent first, ?limit= default 20 / max 50).
    """
    _public_decision_note = _g["_public_decision_note"]
    table = _g["table"]
    qs = event.get("queryStringParameters") or {}
    dr_pk = f"{USER_PREFIX}diary_reactions"

    def _shape(i):
        out = {
            "date": i.get("entry_date") or str(i.get("sk", "")).replace("DATE#", "").split("#")[0],
            "channel": i.get("channel", "video_diary"),
            # #1675: which side of the membrane the human half came from. Legacy rows
            # (written before the social channel existed) carry no kind and are diary.
            "kind": i.get("kind") or "diary",
            # #1675: the per-record id segment of the sk. The front-end builds its list
            # id from date+channel; without this, two same-day posts on one channel
            # produce the SAME id and the second is unreachable — the render-layer twin
            # of the sk collision #1756 fixed in storage.
            "uid": i.get("entry_uid") or "",
            "coach_id": i.get("coach_id"),
            "coach_name": i.get("coach_name"),
            "tone": i.get("tone", "reflective"),
            "theme": i.get("theme"),
            "tier": i.get("tier"),
            # The coach's reaction — the MACHINE voice. Surgically scrubbed (defensive;
            # it is platform-generated text, and its private-content boundary was already
            # enforced at generation by diary_consent).
            "reaction": _scrub_blocked_terms(str(i.get("reaction") or "")),
            "generated_at": i.get("generated_at"),
        }
        # The single owner-cleared verbatim line (quote tier only) — the consented sliver
        # of the HUMAN voice. All-or-nothing content screen (same as _public_decision_note):
        # if scrubbing would alter it at all, drop it rather than serve a mangled quote.
        q = i.get("quote")
        if q:
            note = _public_decision_note(q)
            if note:
                out["quote"] = note
        # #1675 (social only): the public post's own URL, so "he posted" is a real link
        # rather than a claim. Re-validated here as https — the serve layer never trusts
        # a stored string it is about to put in an href.
        url = str(i.get("post_url") or "").strip()
        if url.startswith("https://") and " " not in url:
            out["post_url"] = url
        return out

    date_param = qs.get("date")
    if date_param:
        resp = table.query(
            **with_phase_filter(
                {
                    "KeyConditionExpression": Key("pk").eq(dr_pk) & Key("sk").begins_with(f"DATE#{date_param}"),
                    "ScanIndexForward": False,
                    "Limit": 5,
                }
            )
        )
        items = [i for i in _decimal_to_float(resp.get("Items", [])) if singleton_visible(i)]
        if not items:
            return _ok({"reaction": None, "date": date_param}, cache_seconds=300)
        return _ok({"reaction": _shape(items[0]), "date": date_param}, cache_seconds=300)

    try:
        limit = max(1, min(50, int(qs.get("limit", 20))))
    except (TypeError, ValueError):
        limit = 20
    try:
        resp = table.query(
            **with_phase_filter(
                {
                    "KeyConditionExpression": Key("pk").eq(dr_pk) & Key("sk").begins_with("DATE#"),
                    "ScanIndexForward": False,
                    "Limit": 100,
                }
            )
        )
        items = [i for i in _decimal_to_float(resp.get("Items", [])) if singleton_visible(i)]
    except Exception as e:  # pragma: no cover — a query hiccup serves shaped-empty
        logger.warning(f"[diary_reactions] query failed: {e}")
        items = []
    reactions = [_shape(i) for i in items][:limit]
    return _ok({"reactions": reactions, "count": len(reactions)}, cache_seconds=300)


def _public_decision_note(text):
    """#1569: screen a VERBATIM decision note for public serving.

    Same runtime content filter (marijuana/porn etc.) the CI content-policy scan
    enforces. A verbatim quote is all-or-nothing: if the filter would alter it at all
    (a blocked term excised, or the refuse-whole sentinel), the note is withheld
    ENTIRELY — a decision whose note doesn't cleanly survive simply isn't shown."""
    if not text or not str(text).strip():
        return None
    raw = str(text).strip()
    scrubbed = _scrub_blocked_terms(raw)
    if not scrubbed or re.sub(r"\s+", " ", scrubbed).strip() != re.sub(r"\s+", " ", raw).strip():
        return None
    return scrubbed.strip()


def handle_decisions(event, *, _g):
    """GET /api/decisions — the widened Third Wall for logged decisions (#1569).

    Renders `log_decision` rationale that Matthew chose to publish: ONLY decisions
    carrying an opt-in verbatim `note` ("his call, in his words") are returned, each
    dated, with the platform's recommendation as the machine voice beside it. A
    decision with no note is private and never appears (AC3: absent renders nothing —
    no nag). Phase-filtered (ADR-058) so a wiped cycle's decisions don't resurface.
    Content-filtered at serve time (the same term list the CI scan enforces).

    Read-only. Optional ?limit= (default 20, max 50).
    """
    _public_decision_note = _g["_public_decision_note"]
    table = _g["table"]
    qs = event.get("queryStringParameters") or {}
    try:
        limit = max(1, min(50, int(qs.get("limit", 20))))
    except (TypeError, ValueError):
        limit = 20

    dec_pk = f"{USER_PREFIX}decisions"
    try:
        resp = table.query(
            **with_phase_filter(
                {  # ADR-058: hide pilot/other-cycle decisions
                    "KeyConditionExpression": Key("pk").eq(dec_pk) & Key("sk").begins_with("DECISION#"),
                    "ScanIndexForward": False,
                    "Limit": 100,
                }
            )
        )
        items = _decimal_to_float(resp.get("Items", []))
    except Exception as e:  # pragma: no cover - defensive; a query hiccup serves shaped-empty
        logger.warning(f"[decisions] query failed: {e}")
        items = []

    entries = []
    for i in items:
        note = _public_decision_note(i.get("note"))
        if not note:
            continue  # opt-in: no publishable note = not shown
        followed = i.get("followed")
        entries.append(
            {
                "date": i.get("date"),
                # The platform's recommendation — the MACHINE voice half of the wall.
                # Surgically scrubbed (defensive; it's platform text, not a sacred
                # verbatim quote, so a stray term is excised rather than blanking it).
                "decision": _scrub_blocked_terms(str(i.get("decision") or "")),
                "source": i.get("source"),
                "followed": followed,
                "override_reason": (_scrub_blocked_terms(str(i.get("override_reason"))) if i.get("override_reason") else None),
                # The HUMAN voice — Matthew's verbatim, dated note.
                "note": note,
                "note_at": i.get("note_at"),
                "pillars": i.get("pillars", []),
            }
        )
        if len(entries) >= limit:
            break

    return _ok({"decisions": entries, "count": len(entries)}, cache_seconds=300)


def handle_journal_quotes(event, *, _g):
    """GET /api/journal_quotes — consent-per-line verbatim journal pull-quotes (#1568, ADR-142).

    "From the journal, in his words." Serves ONLY lines Matthew explicitly marked
    publishable through the mark_journal_quote MCP tool (the per-line consent
    channel; the taboo gate already ran fail-closed at mark time). An unmarked
    journal line can never appear here — this endpoint reads the consent
    partition (SOURCE#journal_quotes), never the journal itself. The chronicle's
    never-quote rule is untouched.

    Each quote is dated, labeled, and carries a receipts link to that day's data
    (/cockpit/?date=). `featured` is the AT-MOST-ONE line home may show this ISO
    week (AC2's volume cap — deterministic: first-marked line whose entry date
    falls in the current PT week; stable for the whole week). Absent → honest
    empty ({"quotes": [], "featured": null}) so the render stays dormant.

    Deliberately NOT phase-filtered: like the journal it excerpts (cross-phase by
    owner decision 2026-06-06), a consented quote is a durable archive entry —
    it leaves this surface only by explicit unmark. Verbatim text is screened
    all-or-nothing at serve time (_public_decision_note — the #1569 rule): a
    quote the content filter would alter at all is withheld, never mangled.
    """
    _public_decision_note = _g["_public_decision_note"]
    datetime = _g["datetime"]
    table = _g["table"]
    from content import journal_quotes as jq

    qs = event.get("queryStringParameters") or {}
    try:
        limit = max(1, min(50, int(qs.get("limit", 20))))
    except (TypeError, ValueError):
        limit = 20

    jq_pk = f"{USER_PREFIX}journal_quotes"
    try:
        resp = table.query(
            KeyConditionExpression=Key("pk").eq(jq_pk) & Key("sk").begins_with("QUOTE#"),
            ScanIndexForward=False,
            Limit=100,
        )
        items = _decimal_to_float(resp.get("Items", []))
    except Exception as e:  # pragma: no cover - defensive; a query hiccup serves shaped-empty
        logger.warning(f"[journal_quotes] query failed: {e}")
        items = []

    quotes = []
    for i in items:
        # ADR-104 hardening (2026-07-26 review): only grounding="verified" serves.
        # A mark made before the day's Notion ingestion lands is recorded honestly
        # as pending_ingestion — it is WITHHELD here until the mark_journal_quote
        # tool's list action re-verifies it against the ingested entry. Fail-closed:
        # an absent/unknown grounding value never serves either.
        if i.get("grounding") != "verified":
            continue
        # #1804: re-run the FULL taboo gate against the CURRENT vocabulary on every
        # serve — guard_version is stamped at mark time but nothing enforced it
        # retroactively, so a mark made before the taboo vocabulary widened (e.g.
        # the beverage-noun family / edible additions) would otherwise keep
        # serving forever even after the gate would refuse to mark it today.
        # Fail-closed, same pattern as the grounding check above: withhold, never
        # mangle. jq.find_mark_violations is the FULL vocabulary (privacy_guard's
        # vice/real-name set plus substance_extra/family/private-event/age) —
        # strictly wider than _public_decision_note's narrower scrub below.
        if jq.find_mark_violations(i.get("quote")):
            continue
        screened = _public_decision_note(i.get("quote"))
        if not screened:
            continue  # all-or-nothing: a quote that wouldn't survive intact isn't shown
        shaped = jq.shape_public(i)
        shaped["quote"] = screened
        quotes.append(shaped)

    featured = jq.featured_for_week(quotes, datetime.now(PT).date())
    return _ok(
        {
            "quotes": quotes[:limit],
            "count": len(quotes[:limit]),
            "featured": featured,
            "label": jq.PUBLIC_LABEL,
        },
        cache_seconds=300,
    )
