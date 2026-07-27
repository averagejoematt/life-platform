"""coach_dossier.py — The Coach Dossier (#1387): "what this coach knows", rendered
VERBATIM from the COACH# partitions.

Verbatim rendering IS the design (ADR-104 in its purest form): the public dossier is a
deterministic projection of the memory records — commitments held (COMMITMENT#),
learnings (LEARNING#), relationship state (RELATIONSHIP#state), open docket positions
(ENSEMBLE#docket OPEN#). No LLM sits anywhere in the render path, so the dossier can
only show what the memory actually contains — which is exactly why it's trustworthy.
If it reads badly verbatim, the fix is better memory, not better prose.

Three hard rules, in order:

1. PRIVACY PASS FIRST (blocks launch — #1387 AC2). Every free-text field crosses
   `find_dossier_violations()` before it can enter a public entry. The vocabulary is
   REUSED, not forked: `journal_quotes.find_mark_violations` (which itself builds on
   `privacy_guard.VICE_KEYWORDS` / the banned real-name sets) already enforces the
   standing content absolutes — substances, real-person third parties, family
   specifics, private events, and chronological-age leakage (PhenoAge Option A:
   bio-age is public, chronological age NEVER). Two absolutes that vocabulary doesn't
   carry are added on top, both reused rather than forked: genotype strings (rs-ids,
   gene names, allele notation — PRE-13 / data-publication review) and PII — email /
   phone / SSN / card, via `broadcast_sensitivity_gate.find_pii`, the same
   deterministic offline detector the broadcast auto-publish gate is fail-closed on
   (#1800). A record that hits ANY category is
   WITHHELD WHOLESALE and counted — fail-closed, never partially rendered, never
   silently dropped (the public payload discloses the withheld count).
   NB the age patterns cannot distinguish biological from chronological age; a
   dossier line saying "age 52" is withheld either way. Fail-closed is the intended
   trade — bio-age has its own public surfaces.

2. ADR-141 §4: `channel=conversation` LEARNING# rows quote Matthew's verbatim
   check-in answers — Matthew-PRIVATE, never in a public dossier. Excluded with the
   established `(x.get("channel") or "data") == "conversation"` test BEFORE any
   projection, so `answer_quote`/`takeaway`/`question` are structurally unreachable
   (same guarantee diary_consent.conversation_reference gives the allude tier).
   These rows are "skipped", not "withheld" — their existence is already disclosed
   by the sanctioned /api/coach conversations block; the dossier neither renders
   nor counts them.

3. CORRECTIONS REUSE THE #1689 LEDGER (decision, documented here per the issue):
   a dossier correction/retraction is a `coach_corrections` CORRECTION# row with
   `item_ref.surface == "coach_dossier"` — NOT a parallel mechanism. The COACH#
   record itself is NEVER mutated: `action=retract` removes the record from the
   public projection (and the payload counts it — an auditable absence), while
   `action=correct` attaches a dated correction note alongside the original line.
   The write path lives in the private MCP tool (`audit_coach_dossier`); this
   module only APPLIES corrections at read time.

Every public entry is built KEY-BY-KEY from an allowlist (the diary_consent house
pattern) — no source field is ever copied through wholesale — and every entry carries
its date plus, where derivable, an evidence link (DESIGN_SYSTEM_V5: provenance under
every claim).

Pure module: no boto3, no I/O — hermetically unit-testable (tests/test_coach_dossier.py).
The DDB queries live in the callers (web/site_api_coach._dossier_block, the MCP tool).

v1.0.0 — 2026-07-26 (#1387)
"""

from __future__ import annotations

import re
from typing import Callable, Iterable, Optional

import broadcast_sensitivity_gate  # the house PII detector (#1673) — reused, not forked
import journal_quotes  # the house taboo gate (#1568/ADR-142) — reused, not forked

# The item_ref.surface marker that scopes a #1689 corrections-ledger row to the
# dossier. Shared between the read side (here) and the write side (the MCP tool).
CORRECTION_SURFACE = "coach_dossier"
CORRECTION_ACTIONS = ("retract", "correct")

# ── Genotype absolutes (the one category journal_quotes doesn't carry) ──────────
# PRE-13 / DATA_GOVERNANCE: no genotype strings on any public surface. Conservative
# by design (fail-closed): the surrounding vocabulary words are blocked too, since a
# sentence built around "homozygous"/"allele" is a genotype claim even without an
# rs-id. A false positive only withholds a dossier line, never mutates memory.
GENOTYPE_PATTERNS = (
    re.compile(r"\brs\d{3,}\b", re.IGNORECASE),  # dbSNP ids — rs429358 etc.
    re.compile(r"\b(?:APOE|APO-?E4?|MTHFR|COMT|FTO|CYP\d\w*)\b", re.IGNORECASE),
    re.compile(r"\b[eEε]\s?[234]\s?/\s?[eEε]\s?[234]\b"),  # allele pairs — e3/e4
    re.compile(r"ε\s?[234]\b"),  # bare epsilon allele
    re.compile(r"\b(?:genotype|allele|homozygous|heterozygous|polymorphism|snp)s?\b", re.IGNORECASE),
)


# The established ADR-141 provenance test — verbatim the expression the rest of the
# codebase uses (site_api_coach, chronicle_data, observatory renderer).
def is_conversation_channel(item: dict) -> bool:
    return (item.get("channel") or "data") == "conversation"


def find_dossier_violations(text) -> list:
    """Every content-absolute hit in `text` as (category, term). Empty list = clean.

    Three vocabularies, all REUSED rather than forked:
      * `journal_quotes.find_mark_violations` — substances / real names / family /
        private events / chronological age;
      * the genotype patterns above (PRE-13 — the one absolute that vocabulary lacks);
      * `broadcast_sensitivity_gate.find_pii` — email / phone / SSN / card (#1800).

    #1800: the PII leg was missing. The module claimed to enforce "the standing content
    absolutes", but a COACH# free-text field carrying a contact string (a
    commitment_natural, an outcome_notes, a docket claim, a RELATIONSHIP context_summary)
    crossed to the public coach page untouched — even though the repo already ships a
    deterministic, offline, fail-closed PII detector and DATA_GOVERNANCE.md classifies
    contact strings as never-Tier-0-public. `deploy/pii_surface_guard.py` covers only the
    static site/ surface, not this API payload. The module's own conservative reasoning
    ("a false positive only withholds a dossier line") applies identically here, so PII
    withholds wholesale exactly like a genotype hit.

    Unlike the mark gate, EMPTY text is clean here — an absent optional field is
    "nothing to render", not a violation.
    """
    if text is None or not str(text).strip():
        return []
    text = str(text)
    hits = [h for h in journal_quotes.find_mark_violations(text) if h[0] != "empty"]
    for pat in GENOTYPE_PATTERNS:
        m = pat.search(text)
        if m:
            hits.append(("genotype", m.group(0)))
    # The term is the PII KIND, never the matched string — a violations list is logged
    # and counted, and echoing the contact string into a log would defeat the point.
    hits.extend((broadcast_sensitivity_gate.CATEGORY_PII, kind) for kind in broadcast_sensitivity_gate.find_pii(text))
    return hits


def dossier_safe(*texts) -> bool:
    """True iff every given text field is clean (fail-closed on any hit)."""
    return not any(find_dossier_violations(t) for t in texts)


_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")


def _date_of(*candidates) -> Optional[str]:
    """First ISO-date-shaped candidate, trimmed to YYYY-MM-DD. None = unrenderable
    (AC1: every line carries its date — a dateless record cannot be a dossier line)."""
    for c in candidates:
        s = str(c or "").strip()
        if _ISO_DATE_RE.match(s):
            return s[:10]
    return None


# Each projector returns (entry_or_None, status) with status in:
#   "ok"       — entry is public-renderable
#   "withheld" — privacy filter hit; the record exists but its text may not cross
#   "skip"     — structurally not a dossier line (no date/text, wrong channel, other coach)
OK, WITHHELD, SKIP = "ok", "withheld", "skip"


def commitment_entry(item: dict):
    """Public projection of one COMMITMENT# record (coach_state_updater #532 shape)."""
    item = item or {}
    text = str(item.get("commitment_natural") or "").strip()
    date = _date_of(item.get("created_date"), item.get("created_at"))
    if not text or not date:
        return None, SKIP
    if not dossier_safe(text, item.get("outcome_notes")):
        return None, WITHHELD
    check = item.get("action_check") if isinstance(item.get("action_check"), dict) else None
    entry = {
        "kind": "commitment",
        "record_id": item.get("sk"),
        "date": date,
        "text": text,  # verbatim — the exact commitment the coach recorded
        "status": item.get("status") or "pending",
        "due_date": _date_of(item.get("due_date")),
        "outcome": item.get("outcome"),
        "outcome_date": _date_of(item.get("outcome_date")),
        "outcome_notes": (str(item.get("outcome_notes")).strip() if item.get("outcome_notes") else None),
        # The deterministic follow-through check, where one exists — the evidence
        # this commitment is graded against (metric + direction, evaluator-graded).
        "check": ({"metric": check.get("metric"), "direction": check.get("direction")} if check else None),
        "evidence_link": (f"/data/{_metric_domain(check.get('metric'))}/" if check and check.get("metric") else None),
    }
    return entry, OK


# Coarse metric→data-door mapping for commitment evidence links. Unknown metrics
# fall back to the data hub — a real link either way, never a fabricated deep link.
_METRIC_DOMAINS = {
    "sleep": "sleep",
    "hrv": "sleep",
    "recovery": "sleep",
    "training": "training",
    "strain": "training",
    "volume": "training",
    "zone2": "training",
    "steps": "training",
    "protein": "nutrition",
    "calories": "nutrition",
    "nutrition": "nutrition",
    "glucose": "glucose",
    "cgm": "glucose",
    "weight": "physical",
    "mood": "mind",
    "stress": "mind",
}


def _metric_domain(metric) -> str:
    m = str(metric or "").lower()
    for key, dom in _METRIC_DOMAINS.items():
        if key in m:
            return dom
    return ""


def learning_entry(item: dict, reason_translator: Optional[Callable] = None):
    """Public projection of one LEARNING# record (prediction-evaluator shape).

    ADR-141 §4: conversation-channel rows are skipped before anything is read from
    them. `reason_translator` lets the site layer apply its machine-spec→reader
    translation (_reader_reason) without this module importing web code.
    """
    item = item or {}
    if is_conversation_channel(item):
        return None, SKIP
    date = _date_of(item.get("date"), (str(item.get("sk") or "").replace("LEARNING#", "").split("#")[0]))
    if not date:
        return None, SKIP
    reason_raw = str(item.get("reason") or "").strip()
    reason = str(reason_translator(reason_raw) if reason_translator else reason_raw).strip()
    metric = str(item.get("metric") or "").strip()
    if not (reason or metric):
        return None, SKIP  # nothing verbatim to show — never pad a line into existence
    if not dossier_safe(reason, metric, item.get("condition")):
        return None, WITHHELD
    evidence = {}
    for k in ("prediction_id", "actual_value", "threshold", "condition"):
        if item.get(k) not in (None, "", "unknown"):
            evidence[k] = item.get(k)
    entry = {
        "kind": "learning",
        "record_id": item.get("sk"),
        "date": date,
        "status": item.get("status") or "",
        "metric": metric or None,
        "reason": reason or None,  # verbatim (modulo the documented reader translation)
        "evidence": evidence or None,
        # The graded call this learning came from lives on the public scorecard.
        "evidence_link": "/coaching/scorecard/" if evidence.get("prediction_id") else None,
    }
    return entry, OK


def relationship_entry(item: dict):
    """Public projection of RELATIONSHIP#state (#536 deterministic rapport writer)."""
    item = item or {}
    date = _date_of(item.get("updated_at"), item.get("last_interaction_date"), item.get("first_interaction_date"))
    if not date:
        return None, SKIP
    summary = str(item.get("context_summary") or "").strip()
    if not dossier_safe(summary):
        return None, WITHHELD
    try:
        rapport = round(float(item.get("rapport_level")), 3) if item.get("rapport_level") is not None else None
    except (TypeError, ValueError):
        rapport = None
    entry = {
        "kind": "relationship",
        # #1794: without a record_id, apply_corrections has nothing to match a
        # retraction against — RELATIONSHIP#state is a singleton, so the sk is
        # a fixed fallback when the source item lacks one (defensive only).
        "record_id": item.get("sk") or "RELATIONSHIP#state",
        "date": date,
        "journey_phase": item.get("journey_phase"),
        "rapport_level": rapport,
        "interaction_count": int(item.get("interaction_count") or 0),
        "tenure_days": int(item.get("tenure_days") or 0),
        "first_interaction_date": _date_of(item.get("first_interaction_date")),
        "last_interaction_date": _date_of(item.get("last_interaction_date")),
        "context_summary": summary or None,
    }
    return entry, OK


def _coach_forms(coach_id: str) -> set:
    """Both id spellings a docket row might carry ('sleep' and 'sleep_coach')."""
    cid = str(coach_id or "").strip()
    bare = cid[: -len("_coach")] if cid.endswith("_coach") else cid
    return {cid, bare, f"{bare}_coach"} - {""}


def docket_entry(item: dict, coach_id: str):
    """Public projection of one OPEN# dispute-docket row (#1386 shape), from this
    coach's side. Rows not involving the coach are skipped."""
    item = item or {}
    forms = _coach_forms(coach_id)
    a, b = item.get("coach_a"), item.get("coach_b")
    if a in forms:
        me, other = a, b
    elif b in forms:
        me, other = b, a
    else:
        return None, SKIP
    date = _date_of(item.get("opened_date"))
    claim = str((item.get("claims") or {}).get(me) or "").strip()
    if not date or not claim:
        return None, SKIP
    criterion = item.get("criterion") or {}
    if not dossier_safe(claim, item.get("topic"), criterion.get("description")):
        return None, WITHHELD
    entry = {
        "kind": "docket_position",
        "record_id": item.get("sk"),
        "date": date,
        "topic": item.get("topic"),
        "my_claim": claim,  # verbatim — the claim frozen at open
        "versus": other,
        "criterion": criterion.get("description"),
        "resolution_date": _date_of(item.get("resolution_date")),
        # The docket surface renders both sides + stakes; that page is the evidence.
        "evidence_link": "/coaching/read/",
    }
    return entry, OK


# ── Corrections (the #1689 ledger, applied at read time) ────────────────────────


def dossier_corrections(ledger_rows: Iterable[dict], coach_id: str) -> list:
    """Filter #1689 corrections-ledger rows down to THIS coach's dossier corrections.

    A dossier correction is item_ref.surface == "coach_dossier" with a matching
    coach and an action in CORRECTION_ACTIONS. Returns
    [{record_sk, action, date, note}], newest first (ledger sk order).
    """
    forms = _coach_forms(coach_id)
    out = []
    for row in ledger_rows or []:
        ref = row.get("item_ref") or {}
        if ref.get("surface") != CORRECTION_SURFACE:
            continue
        if ref.get("coach") not in forms:
            continue
        action = ref.get("action")
        if action not in CORRECTION_ACTIONS or not ref.get("record_sk"):
            continue
        out.append(
            {
                "record_sk": ref.get("record_sk"),
                "action": action,
                "date": _date_of(str(row.get("sk") or "").replace("CORRECTION#", "").split("#")[0], row.get("created_at")),
                "note": str(row.get("correction_text") or "").strip(),
            }
        )
    out.sort(key=lambda c: c.get("date") or "", reverse=True)
    return out


def apply_corrections(entries: list, corrections: list):
    """Apply dossier corrections to a list of public entries (pure — inputs unmutated).

    retract → the entry is removed from the public projection (counted, so the
              payload can disclose the auditable absence).
    correct → a dated correction note is attached UNDER the original line (the
              memory stays visible; the correction is the annotation — never an
              in-place edit). A note that itself fails the privacy filter is
              attached date-only with the note withheld (fail-closed all the way).

    Returns (kept_entries, retracted_count).
    """
    by_sk: dict = {}
    for c in corrections or []:
        by_sk.setdefault(c.get("record_sk"), []).append(c)
    kept, retracted = [], 0
    for e in entries or []:
        cs = by_sk.get(e.get("record_id")) or []
        if any(c.get("action") == "retract" for c in cs):
            retracted += 1
            continue
        notes = []
        for c in cs:
            if c.get("action") != "correct":
                continue
            note_ok = dossier_safe(c.get("note"))
            notes.append({"date": c.get("date"), "note": c.get("note") if note_ok else None, "note_withheld": not note_ok})
        if notes:
            e = {**e, "corrections": notes}
        kept.append(e)
    return kept, retracted


def commitment_counts(entries: list) -> dict:
    """Deterministic status tally over the PUBLIC commitment entries — the honest
    zero-state numbers ('has held 0 commitments this cycle') come from here."""
    counts = {"held": 0, "kept": 0, "broken": 0, "pending": 0, "unresolved": 0}
    for e in entries or []:
        counts["held"] += 1
        st = str(e.get("status") or "pending")
        counts[st if st in counts else "pending"] += 1
    return counts
