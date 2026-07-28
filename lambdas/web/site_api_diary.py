"""site_api_diary.py — #1846: the consent-gated diary shelf on /story.

The video diary is the newest station of the causal loop's STORY arm and it had
zero surface on averagejoematt.com: the entries existed only as local studio files
and a Notion journal page. This module is the ONE read-only door that lets a diary
entry become visible to a reader — and it is built the same way every other
private→public boundary in this repo is built: **fail-closed, projection-by-
allowlist, withheld counted rather than hidden.**

GET /api/diary_shelf[?limit=]

WHAT DECIDES VISIBILITY (two independent, explicit consent grants)
─────────────────────────────────────────────────────────────────
1. **The card exists at all** iff the ENTRY carries an explicit owner consent
   marker — `diary_consent.resolve_consent(entry) != "private"` (the ADR-142 /
   #1574 entry-level tier, read from the Notion `public_reaction_consent`
   property). Absent, malformed, unknown, `"public_ok"`, an int ⇒ private ⇒ the
   entry is **invisible** (AC1: not a redacted-looking card, not a ghost row —
   it simply is not in the payload). The studio HOLD-list is the editorial gate;
   this endpoint only ever sees what cleared it.
2. **Which of his WORDS appear on that card** is decided per-line and separately,
   by `mark_journal_quote` (#1568, ADR-142): only lines Matthew explicitly marked
   publishable, stored frozen in the `SOURCE#journal_quotes` consent partition.
   This module never reads `raw_text`, `body_text`, `notes`, the mood text, or
   `enriched_notable_quote` — an unmarked line is structurally unreachable from
   this payload, exactly as in `diary_consent.public_context`.

A card can therefore exist with zero quotes (metadata + the laundered coarse
theme only). A marked line can never appear without its entry also being cleared
— the conservative composition of the two grants, since a card is a wider frame
than the line it holds.

SERVE-TIME RE-SCREENING (nothing is trusted because it was once approved)
─────────────────────────────────────────────────────────────────────────
Every verbatim line is re-screened on EVERY request, never just at mark time
(the #1804 lesson — a mark made before the taboo vocabulary widened would
otherwise serve forever):
  · `grounding == "verified"`            — the ADR-104 grounding invariant;
  · `coach_dossier.find_dossier_violations` — the WIDEST deterministic screen in
    the repo: `journal_quotes.find_mark_violations` (substances / real names /
    family specifics / private events / chronological age) ∪ the PRE-13 genotype
    patterns ∪ `broadcast_sensitivity_gate.find_pii` (email/phone/SSN/card);
  · `_public_decision_note`              — the #1569 all-or-nothing content
    filter: a line the runtime filter would alter AT ALL is withheld entire,
    never served mangled.
A line failing any screen is counted in `quotes_withheld`, not silently dropped.

HONEST NUMBERS (ADR-104)
────────────────────────
Absence is absence. `duration` is emitted only when the entry actually carries
`vocal_duration_s` (#1842, computed from the studio SRT) — never zeroed, never
estimated. A quiet week renders as quiet: no cards, no padding, no manufactured
"coming soon" rows. `withheld` reports how many diary entries exist but are not
published, so the shelf never implies the diary is only what you can see.

RESET-AWARE (AC3, ADR-077)
──────────────────────────
Deliberately NOT phase-filtered — like the journal it excerpts and the
`journal_quotes` channel it reuses (both cross-phase by owner decision), a
consented diary entry is a durable archive entry; it leaves this surface only by
an explicit unmark. Each card is stamped with the CYCLE it was recorded in and
its day number WITHIN that cycle (`site_api_data.CYCLE_GENESES`), so a reset
re-anchors the counting instead of orphaning or renumbering the archive.

ONE VISUAL SYSTEM (AC2)
───────────────────────
The card's day-mark is the canonical daily fingerprint — the very same
`web.fingerprint.build_mark` / `mark_to_svg` artifact the cockpit masthead, the
/data/wall/ field and the studio HUD render (#1379, one source of truth). It is
computed from that day's real metrics, so a thin day shows a thin mark and the
ember glow stays earned.

CLAIMS ON TAPE (#1841)
──────────────────────
`diary_claims` records are `visibility: "private"` by default and this endpoint
keeps them that way: only a claim explicitly marked `visibility == "public"` is
projected (field-by-field from an allowlist, never copied wholesale), and the
rest are reported as a COUNT — "he put N forecasts on the record that day; they
grade privately." No claim text crosses without its own marker.
"""

import re
from datetime import datetime

import diary_consent
import journal_quotes as jq
from boto3.dynamodb.conditions import Key
from coach.coach_dossier import find_dossier_violations

from web.fingerprint import build_mark, mark_to_svg
from web.site_api_coach import _public_decision_note
from web.site_api_common import (
    USER_PREFIX,
    _decimal_to_float,
    _ok,
    logger,
    table,
)
from web.site_api_fingerprint import _metrics_index

# The capture channels that are DIARY entries (#1572/#1573). A typed journal entry
# (channel="journal") is never a diary card, whatever its consent marker says.
DIARY_CHANNELS = ("video_diary", "solo_recording")
CHANNEL_LABEL = {"video_diary": "video diary", "solo_recording": "solo recording"}

# `DATE#YYYY-MM-DD#journal#<channel>#<stable-suffix>` (docs/SCHEMA.md, notion source).
_ENTRY_SK_RE = re.compile(r"^DATE#(\d{4}-\d{2}-\d{2})#journal#(" + "|".join(DIARY_CHANNELS) + r")#")

_MARK_PX = 56  # the shelf card's day-mark size (geometry is size-independent)
_PAGE_LIMIT = 200
_MAX_PAGES = 6  # ≤1200 journal rows scanned — the whole archive, with a hard ceiling
_DEFAULT_LIMIT = 24
_MAX_LIMIT = 60

PUBLIC_LABEL = "the diary, where he cleared it"
SHELF_NOTE = (
    "Nothing here publishes by default. An entry appears only when Matthew marked that entry "
    "publishable, and his words appear only where he marked that exact line. Everything else "
    "stays in the studio — counted below, never shown."
)

# The ONLY fields of a diary_claims record that may cross to a reader, and only
# when the record itself carries visibility == "public". Built key-by-key, never
# copied-and-filtered, so a schema growth cannot ride along (the
# diary_consent.conversation_reference pattern).
CLAIM_PUBLIC_FIELDS = ("claim_id", "claim_natural", "metric", "grade_by", "status", "confidence")


def _cycle_for(date_str, genesis_pairs):
    """(cycle, day_number) for a date — reset-aware (AC3).

    `genesis_pairs` is the ascending [(cycle, genesis)] list. The date belongs to
    the LAST cycle whose genesis is on or before it; `day_number` is 1-indexed
    within that cycle. A pre-genesis date (older than cycle 1) belongs to no
    cycle: (None, None) — reported honestly rather than clamped to "Day 1".
    """
    match = None
    for cycle, genesis in genesis_pairs:
        if genesis <= date_str:
            match = (cycle, genesis)
        else:
            break
    if not match:
        return None, None
    cycle, genesis = match
    try:
        delta = (datetime.strptime(date_str, "%Y-%m-%d") - datetime.strptime(genesis, "%Y-%m-%d")).days
    except (TypeError, ValueError):  # pragma: no cover — sk regex already pinned the format
        return cycle, None
    return cycle, delta + 1


def _duration(entry):
    """The session length, or None. ADR-104: emitted ONLY from a real measurement
    (`vocal_duration_s`, #1842 — deterministic SRT arithmetic). An entry with no
    SRT has no duration; it is omitted, never rendered as 0:00 or estimated from
    the word count."""
    raw = entry.get("vocal_duration_s")
    if raw in (None, ""):
        return None
    try:
        seconds = int(round(float(raw)))
    except (TypeError, ValueError):
        return None
    if seconds <= 0:
        return None
    minutes, rem = divmod(seconds, 60)
    return {"seconds": seconds, "label": f"{minutes}:{rem:02d}"}


def _diary_rows():
    """Every diary-channel row in the notion partition, newest first.

    Cross-phase by design (AC3) — no phase filter, so a consented entry survives a
    reset exactly as its marked quotes do. Bounded by `_MAX_PAGES` so a pathological
    partition can never turn one request into an unbounded scan."""
    pk = f"{USER_PREFIX}notion"
    rows, start_key = [], None
    for _ in range(_MAX_PAGES):
        kwargs = {
            "KeyConditionExpression": Key("pk").eq(pk) & Key("sk").begins_with("DATE#"),
            "ScanIndexForward": False,
            "Limit": _PAGE_LIMIT,
        }
        if start_key:
            kwargs["ExclusiveStartKey"] = start_key
        resp = table.query(**kwargs)
        rows.extend(resp.get("Items", []))
        start_key = resp.get("LastEvaluatedKey")
        if not start_key:
            break
    return _decimal_to_float(rows)


def _quotes_by_day():
    """{(date, channel): [screened quote dicts]} plus {(date, channel): withheld_count}.

    Reads the CONSENT partition (`SOURCE#journal_quotes`), never the journal. Each
    line is re-screened here on every serve — see the module docstring."""
    pk = f"{USER_PREFIX}journal_quotes"
    try:
        resp = table.query(
            KeyConditionExpression=Key("pk").eq(pk) & Key("sk").begins_with(jq.SK_PREFIX),
            ScanIndexForward=False,
            Limit=300,
        )
        items = _decimal_to_float(resp.get("Items", []))
    except Exception as e:  # pragma: no cover — a query hiccup serves a shelf with no quotes
        logger.warning(f"[diary_shelf] journal_quotes query failed: {e}")
        items = []

    served, withheld = {}, {}
    for item in items:
        channel = item.get("channel") if item.get("channel") in jq.CHANNELS else "journal"
        if channel not in DIARY_CHANNELS:
            continue  # a typed-journal line belongs on /story/journal/, not the shelf
        key = (str(item.get("date") or ""), channel)
        if not key[0]:
            continue
        text = item.get("quote")
        # 1. the ADR-104 grounding invariant — a mark made before ingestion landed
        #    is honestly `pending_ingestion` and stays withheld until re-verified.
        # 2. the widest deterministic content screen in the repo (journal_quotes'
        #    full taboo vocabulary + genotype + PII), re-run against TODAY's
        #    vocabulary, not the one in force at mark time (#1804).
        # 3. the #1569 all-or-nothing runtime filter — mangled is worse than absent.
        screened = None
        if item.get("grounding") == "verified" and not find_dossier_violations(text):
            screened = _public_decision_note(text)
        if not screened:
            withheld[key] = withheld.get(key, 0) + 1
            continue
        shaped = jq.shape_public(item)
        shaped["quote"] = screened
        served.setdefault(key, []).append(shaped)
    return served, withheld


def _claims_by_entry():
    """{source_sk: {"public": [...], "count": n}} from the on-tape claims ledger (#1841).

    Claims are `visibility: "private"` by default and stay that way: only an
    explicitly public-marked claim is projected, field-by-field from
    `CLAIM_PUBLIC_FIELDS`. The count of the rest is disclosed — a reader learns
    that forecasts were made, never what they were."""
    pk = f"{USER_PREFIX}diary_claims"
    try:
        resp = table.query(
            KeyConditionExpression=Key("pk").eq(pk) & Key("sk").begins_with("PREDICTION#"),
            ScanIndexForward=False,
            Limit=200,
        )
        items = _decimal_to_float(resp.get("Items", []))
    except Exception as e:  # pragma: no cover — absent ledger ⇒ no claim counts
        logger.warning(f"[diary_shelf] diary_claims query failed: {e}")
        items = []

    out = {}
    for item in items:
        sk = str(item.get("source_sk") or "")
        if not sk:
            continue
        bucket = out.setdefault(sk, {"public": [], "count": 0})
        bucket["count"] += 1
        if str(item.get("visibility") or "").strip().lower() != "public":
            continue
        claim = {}
        for field in CLAIM_PUBLIC_FIELDS:
            value = item.get(field)
            if value not in (None, ""):
                claim[field] = value
        text = claim.get("claim_natural")
        if text:
            screened = _public_decision_note(text) if not find_dossier_violations(text) else None
            if not screened:
                claim.pop("claim_natural", None)
            else:
                claim["claim_natural"] = screened
        if claim:
            bucket["public"].append(claim)
    return out


def handle_diary_shelf(event):
    """GET /api/diary_shelf — the consent-gated diary shelf (#1846).

    Read-only. Optional `?limit=` (default 24, max 60). Serves shaped-empty
    (`{"entries": [], "count": 0, "withheld": N}`) whenever nothing is cleared —
    the shelf then renders as quiet, which is the honest state of a quiet week.
    """
    qs = event.get("queryStringParameters") or {}
    try:
        limit = max(1, min(_MAX_LIMIT, int(qs.get("limit", _DEFAULT_LIMIT))))
    except (TypeError, ValueError):
        limit = _DEFAULT_LIMIT

    try:
        rows = _diary_rows()
    except Exception as e:  # pragma: no cover — defensive; a query hiccup serves shaped-empty
        logger.warning(f"[diary_shelf] notion query failed: {e}")
        rows = []

    # Split first, so `withheld` counts EVERY diary entry that exists and did not
    # clear — the number is the point (AC1's "invisible, not redacted-looking" is
    # about the card, not about pretending the entry never happened).
    cleared, withheld_entries = [], 0
    for item in rows:
        m = _ENTRY_SK_RE.match(str(item.get("sk") or ""))
        if not m:
            continue
        if diary_consent.resolve_consent(item) == diary_consent.TIER_PRIVATE:
            withheld_entries += 1
            continue
        cleared.append((m.group(1), m.group(2), item))

    if not cleared:
        return _ok(
            {
                "shelf": {
                    "entries": [],
                    "count": 0,
                    "withheld": withheld_entries,
                    "label": PUBLIC_LABEL,
                    "note": SHELF_NOTE,
                }
            },
            cache_seconds=300,
        )

    cleared = cleared[:limit]
    quotes_by_day, quotes_withheld = _quotes_by_day()
    claims_by_entry = _claims_by_entry()

    # One batched metrics read across the shelf's real date span, so every card's
    # day-mark is the canonical fingerprint seeded by that day's actual numbers.
    dates = [d for d, _c, _i in cleared]
    try:
        metrics_index = _metrics_index(min(dates), max(dates))
    except Exception as e:  # pragma: no cover — marks degrade to honest "warming up"
        logger.warning(f"[diary_shelf] metrics index failed: {e}")
        metrics_index = {}

    from web.site_api_data import CYCLE_GENESES  # imported late so tests can patch it

    genesis_pairs = sorted(CYCLE_GENESES.items(), key=lambda kv: kv[1])

    entries = []
    for date_str, channel, item in cleared:
        cycle, day_number = _cycle_for(date_str, genesis_pairs)
        mark = build_mark(date_str, metrics_index.get(date_str, {}))
        claims = claims_by_entry.get(str(item.get("sk") or ""), {"public": [], "count": 0})
        key = (date_str, channel)
        card = {
            "date": date_str,
            "cycle": cycle,
            "day_number": day_number,
            "channel": channel,
            "format": CHANNEL_LABEL[channel],
            # The exposure tier this entry actually cleared — "quote" or "allude".
            # A private entry never reaches here.
            "tier": diary_consent.resolve_consent(item),
            # The coarse 8-way laundered theme — the ONLY theme signal that may
            # reach a public surface (never a raw enrichment tag).
            "theme": diary_consent.public_theme(item),
            "day_mark": {
                "svg": mark_to_svg(mark, size=_MARK_PX),
                "warming_up": mark["warming_up"],
                "earned": mark["earned_score"],
            },
            "quotes": quotes_by_day.get(key, []),
            "quotes_withheld": quotes_withheld.get(key, 0),
            "claims": claims["public"],
            "claims_on_record": claims["count"],
        }
        duration = _duration(item)
        if duration:  # ADR-104: absent stays absent
            card["duration"] = duration
        entries.append(card)

    return _ok(
        {
            "shelf": {
                "entries": entries,
                "count": len(entries),
                "withheld": withheld_entries,
                "label": PUBLIC_LABEL,
                "note": SHELF_NOTE,
            }
        },
        cache_seconds=300,
    )
