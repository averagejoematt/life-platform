"""horizons_calibration.py — the Horizons feedback loop (#1708, epic #1686 S4).

S1 (#1705) authors a weekly media pick, S2 (#1706) threads an optional follow-up into
the coach check-in queue, S3 (#1707) publishes the retrospective. This module closes
the loop: **Matthew's reaction to a pick calibrates the next pick.**

## Why this module exists (the scope finding, answered)

The #1708 scope comment was right that Horizons has no *learned* profile the way the
book recommender does (`reading_recommender` — curriculum phase, ratchet, genre
streak). Rather than invent one, the calibration target here is a **deterministic
reaction ledger** stored on the existing `READING#PROFILE / CURRENT` item under
``horizons``: per-category / per-format / per-rationale-tag counts of what Matthew
actually did with each pick, with **n on every claim** and an explicit ``unknown``
bucket where the signal is absent (ADR-104 behavioural-absence semantics, ADR-105's
n-gate). No LLM ever produces a number here — the only model-derived input is the
``enriched_sentiment`` the EXISTING journal-enrichment path already wrote onto the
reaction record (#1577), read as one tallied field among several, never as a verdict.

The curating coach reads this ledger before authoring the next pick (surfaced by
``mcp.tools_reading.tool_get_horizons`` and on ``curate_horizon``'s dry-run preview),
which is what "future picks calibrate" means concretely and honestly.

## Where the reaction comes from (no second pipeline, #1572)

A follow-up is a `CHECKIN#` row carrying ``generated_by="prescription_followup"`` +
``prescription_week``; the pick cross-references it (``follow_up.surfaced_checkin_sk``
/ ``surfaced_coach``). So the ledger is rebuilt by **GetItem-ing exactly the rows the
picks already point at** — bounded (≤ ``MAX_PICKS``), no scan, no new index, no new
partition. The refresh is a full recompute, so it is idempotent and self-healing.

## Privacy (owner note on #1708) — fail-closed, twice

1. **Nothing verbatim ever enters the ledger.** It stores counts, rates and coarse
   valence labels only — Matthew's words stay on the private `CHECKIN#` row.
2. **A reaction is not publishable.** ``is_publishable_reaction`` is the ONLY
   sanctioned door from a reaction to any public surface, and it is a positive match
   on BOTH an explicit owner consent tier (`diary_consent`, the existing
   ``public_reaction_consent`` idiom) AND a CLEARED `broadcast_sensitivity_gate`
   verdict (#1673 — the same gate the Social Membrane auto-publish path uses). An
   unstamped, unconsented, or held reaction is never publishable. Today nothing
   public calls it: `/api/horizons` builds its card from an explicit allowlist that
   contains no reaction field at all, so personal feedback is unpublishable BY
   CONSTRUCTION and the gate is the door for any future surface.

Pure at import: no boto3, no AWS. ``refresh()`` takes its table/store by injection,
so the whole ledger is unit-testable offline.
"""

from __future__ import annotations

from datetime import datetime, timezone

CALIBRATION_VERSION = "v1.0.0"

# The #1577 channel value stamped on an enriched reaction (see conversation_enrichment).
REACTION_CHANNEL = "prescription_reaction"
# The marker `coach_checkin.build_prescription_followup_item` writes on a follow-up row.
GENERATED_BY = "prescription_followup"

# The profile attribute this ledger lives under (READING#PROFILE / CURRENT).
PROFILE_FIELD = "horizons"

# A one-word "yeah" is an answer but not engagement. Same word floor as the
# conversational enrichment corpus (conversation_enrichment.MIN_TEXT_WORDS).
ENGAGED_MIN_WORDS = 8
# ~a year of weekly picks — the same bound the public feed uses.
MAX_PICKS = 52
RECENT_LIMIT = 12
# ADR-105: a per-bucket rate is only surfaced as *signal* at or above this n.
MIN_N_FOR_SIGNAL = 3

# Reaction states (deterministic, from the stored check-in row).
STATE_NO_FOLLOWUP = "no_followup"
STATE_UNANSWERED = "unanswered"
STATE_SKIPPED = "skipped"
STATE_ANSWERED = "answered"

# Valence buckets. ``unknown`` is a first-class outcome — the reaction landed before
# the 6:30 AM enrichment pass ran, or the extraction produced nothing. Never a zero.
SENTIMENTS = ("positive", "neutral", "negative", "mixed")
VALENCE_UNKNOWN = "unknown"

_DIMENSIONS = ("by_category", "by_format", "by_rationale_tag")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── the pick's dimensions (what a future pick can be calibrated ON) ───────────


def _garden_index() -> dict:
    """{domain → category} and {outlet name → category} from the curation garden."""
    from reading import horizons_garden

    idx: dict = {}
    for entry in horizons_garden.GARDEN:
        cat = entry.get("category")
        if not cat:
            continue
        if entry.get("domain"):
            idx[str(entry["domain"]).lower()] = cat
        if entry.get("name"):
            idx[str(entry["name"]).strip().lower()] = cat
    return idx


def pick_category(pick: dict, index: dict | None = None) -> str:
    """The garden category a pick belongs to, matched on its URL host then its
    outlet name. A pick reached from OUTSIDE the garden (explicitly allowed for
    topical items) is honestly ``off-garden`` — never silently bucketed."""
    idx = _garden_index() if index is None else index
    url = str((pick or {}).get("url") or "").lower()
    host = url.split("//", 1)[-1].split("/", 1)[0].split("@")[-1].split(":")[0]
    host = host[4:] if host.startswith("www.") else host
    if host:
        for domain, cat in idx.items():
            if "." in domain and (host == domain or host.endswith("." + domain)):
                return cat
    name = str((pick or {}).get("source") or "").strip().lower()
    if name and name in idx:
        return idx[name]
    return "off-garden"


def pick_dimensions(pick: dict, index: dict | None = None) -> dict:
    """The three calibratable facets of a pick, each with an honest unknown label."""
    p = pick or {}
    return {
        "by_category": pick_category(p, index),
        "by_format": str(p.get("format") or "unspecified"),
        "by_rationale_tag": str(p.get("rationale_tag") or "unspecified"),
    }


# ── the reaction signal (deterministic; ADR-105 — no LLM verdict) ─────────────


def is_prescription_reaction(checkin: dict | None) -> bool:
    """True for a check-in row that exists to capture a reaction to a Horizons pick."""
    return bool(checkin) and str((checkin or {}).get("generated_by") or "") == GENERATED_BY


def reaction_signal(checkin: dict | None) -> dict:
    """Deterministic read of ONE reaction record. Never raises; never infers.

    ``valence`` is the enrichment path's ``enriched_sentiment`` when that pass has
    already run, else ``unknown`` — the absence of a coded sentiment is reported as
    absence (ADR-104), never as neutral.
    """
    it = checkin or {}
    if not it:
        return {"state": STATE_NO_FOLLOWUP, "engaged": None, "words": 0, "valence": VALENCE_UNKNOWN}

    answer = str(it.get("answer") or "").strip()
    status = str(it.get("status") or "").strip().lower()
    if status == "skipped" or (it.get("skipped") and not answer):
        state = STATE_SKIPPED
    elif status == "answered" and answer:
        state = STATE_ANSWERED
    else:
        state = STATE_UNANSWERED

    words = len(answer.split())
    sentiment = str(it.get("enriched_sentiment") or "").strip().lower()
    return {
        "state": state,
        "engaged": (words >= ENGAGED_MIN_WORDS) if state == STATE_ANSWERED else (False if state == STATE_SKIPPED else None),
        "words": words,
        "valence": sentiment if sentiment in SENTIMENTS else VALENCE_UNKNOWN,
    }


def confidence(n: int) -> str:
    """Honest confidence label for a count (ADR-105 — n travels with every claim)."""
    n = int(n or 0)
    if n <= 0:
        return "none"
    if n < MIN_N_FOR_SIGNAL:
        return "very-low"
    if n < 6:
        return "low"
    if n < 12:
        return "medium"
    return "high"


# ── the ledger ───────────────────────────────────────────────────────────────


def _empty_bucket() -> dict:
    return {
        "picks": 0,
        "followed_up": 0,
        "answered": 0,
        "skipped": 0,
        "unanswered": 0,
        "engaged": 0,
        "sentiment": {s: 0 for s in SENTIMENTS + (VALENCE_UNKNOWN,)},
    }


def _tally(bucket: dict, signal: dict) -> None:
    bucket["picks"] += 1
    state = signal["state"]
    if state == STATE_NO_FOLLOWUP:
        return
    bucket["followed_up"] += 1
    if state == STATE_ANSWERED:
        bucket["answered"] += 1
        if signal["engaged"]:
            bucket["engaged"] += 1
        bucket["sentiment"][signal["valence"]] += 1
    elif state == STATE_SKIPPED:
        bucket["skipped"] += 1
    else:
        bucket["unanswered"] += 1


def _finalize(bucket: dict) -> dict:
    """Attach the derived rates. A rate over n=0 is None (no data), never 0.0."""
    n = bucket["followed_up"]
    bucket["n"] = n
    bucket["engagement_rate"] = round(bucket["engaged"] / n, 3) if n else None
    bucket["answer_rate"] = round(bucket["answered"] / n, 3) if n else None
    bucket["confidence"] = confidence(n)
    return bucket


def _ranked(buckets: dict, dimension: str) -> list:
    """Buckets that clear the n-gate, most-engaging first — the only thing this
    module presents as *signal*. Below MIN_N_FOR_SIGNAL a bucket is data, not a
    preference, and is deliberately absent from this list."""
    rows = [
        {"dimension": dimension, "key": key, "engagement_rate": b["engagement_rate"], "n": b["n"]}
        for key, b in buckets.items()
        if b["n"] >= MIN_N_FOR_SIGNAL and b["engagement_rate"] is not None
    ]
    rows.sort(key=lambda r: (-r["engagement_rate"], -r["n"], r["key"]))
    return rows


def build_calibration(pairs, *, now: str | None = None) -> dict:
    """The full ledger from ``[(pick, checkin_or_None), ...]`` (newest pick first).

    Pure + deterministic: same inputs → same output. Contains NO verbatim text from
    any reaction — counts, rates and coarse valence labels only.
    """
    index = _garden_index()
    dims: dict = {d: {} for d in _DIMENSIONS}
    totals = _empty_bucket()
    recent: list = []

    for pick, checkin in pairs or []:
        signal = reaction_signal(checkin if is_prescription_reaction(checkin) else None)
        _tally(totals, signal)
        for dimension, key in pick_dimensions(pick, index).items():
            _tally(dims[dimension].setdefault(key, _empty_bucket()), signal)
        if len(recent) < RECENT_LIMIT:
            recent.append(
                {
                    "week": (pick or {}).get("week"),
                    "format": (pick or {}).get("format"),
                    "rationale_tag": (pick or {}).get("rationale_tag"),
                    "category": pick_category(pick or {}, index),
                    "state": signal["state"],
                    "engaged": signal["engaged"],
                    "valence": signal["valence"],
                }
            )

    for dimension in _DIMENSIONS:
        for bucket in dims[dimension].values():
            _finalize(bucket)
    _finalize(totals)

    signal_rows: list = []
    for dimension in _DIMENSIONS:
        signal_rows.extend(_ranked(dims[dimension], dimension))

    n_react = totals["answered"]
    return {
        "version": CALIBRATION_VERSION,
        "method": "deterministic_counts",  # ADR-105: no LLM produces any number here
        "generated_at": now or _now_iso(),
        "n_picks": totals["picks"],
        "n_followups": totals["followed_up"],
        "n_reactions": n_react,
        "n_skipped": totals["skipped"],
        "n_unanswered": totals["unanswered"],
        "confidence": confidence(n_react),
        "totals": totals,
        "by_category": dims["by_category"],
        "by_format": dims["by_format"],
        "by_rationale_tag": dims["by_rationale_tag"],
        "signal": {"min_n": MIN_N_FOR_SIGNAL, "ranked": signal_rows},
        "recent": recent,
        "note": (
            "No reaction has landed yet — pick the next one on judgement, not on this ledger."
            if n_react == 0
            else f"{n_react} reaction(s) across {totals['picks']} pick(s); rates below n={MIN_N_FOR_SIGNAL} are data, not preference."
        ),
    }


# ── the refresh (bounded reads: exactly the rows the picks point at) ──────────


def _checkin_pk(coach_id: str) -> str:
    from coach_checkin import checkin_pk

    return checkin_pk(coach_id)


def _get_checkin(table, coach_id: str, sk: str) -> dict | None:
    try:
        return (table.get_item(Key={"pk": _checkin_pk(coach_id), "sk": sk}) or {}).get("Item")
    except Exception:  # noqa: BLE001 — a missing reaction is "no data", never a failure
        return None


def collect_pairs(table, picks) -> list:
    """``[(pick, checkin_or_None)]`` — one bounded GetItem per pick that actually
    surfaced a follow-up (S2 cross-references it on the pick). No scan, no GSI."""
    pairs = []
    for pick in picks or []:
        follow_up = (pick or {}).get("follow_up") or {}
        sk = follow_up.get("surfaced_checkin_sk")
        coach = follow_up.get("surfaced_coach")
        pairs.append((pick, _get_checkin(table, coach, sk) if (sk and coach) else None))
    return pairs


def refresh(table, *, store=None, now: str | None = None) -> dict:
    """Recompute the ledger from stored reactions and write it onto the reading
    profile. Full recompute ⇒ idempotent and self-healing (a reaction enriched
    later simply lands on the next refresh). Returns the ledger."""
    if store is None:
        from reading import reading_store as store  # lazy: keeps this module AWS-free at import

    picks = store.horizon_picks(limit=MAX_PICKS)
    calibration = build_calibration(collect_pairs(table, picks), now=now)
    store.put_horizons_calibration(calibration)
    return calibration


# ── the ONE door to a public surface (fail-closed, #1673 + diary_consent) ─────


def sensitivity_attrs_for_reaction(answer: str) -> dict:
    """The #1673 verdict attributes to stamp next to a stored reaction.

    Deterministic layer only (privacy_guard vices/real-names + PII) with no
    off-topic classifier wired, so the verdict is HELD unless something explicitly
    clears it — the fail-closed posture of the Social Membrane auto-publish path.
    Fail-soft: if the gate module is unavailable the caller simply stamps nothing,
    which is *also* not publishable (``is_publishable_reaction`` is a positive match).
    """
    import broadcast_sensitivity_gate as gate

    return gate.classify_and_stamp(answer or "")


def is_publishable_reaction(checkin: dict | None) -> bool:
    """Fail-closed: True only when Matthew explicitly consented to public surfacing
    AND the #1673 gate CLEARED the stored verdict. Missing consent, missing stamp,
    a held verdict, or an unimportable gate all resolve to False.

    This is the only sanctioned route from a private reaction to a public surface.
    Nothing public calls it today — `/api/horizons` carries no reaction field at all.
    """
    it = checkin or {}
    if not is_prescription_reaction(it):
        return False
    try:
        import broadcast_sensitivity_gate as gate
        import diary_consent
    except ImportError:  # pragma: no cover — bundled modules; absence is fail-closed
        return False
    consent = str(it.get(diary_consent.CONSENT_FIELD) or "").strip().lower()
    if consent not in (diary_consent.TIER_QUOTE, diary_consent.TIER_ALLUDE):
        return False
    return bool(gate.is_cleared(it))
