"""clinical_facts.py — the owner clinical record as one compact coach-context block.

WHY THIS EXISTS (ADR-155 amendment, 2026-10-12)
  The owner ruled that his own clinical record — diagnoses and clinical events, the
  medications he is on, recent ECG recordings, the latest clinical lab panel and the
  standing guidance his clinicians gave — may enter the AI coaches' context, so no coach
  prescribes training, nutrition or recovery advice that a medical instruction already
  overrides. The record lives in its own owner-written partition,
  `USER#matthew#SOURCE#clinical`, written only by `scripts/load_clinical_record.py`
  from a file kept outside this (public) repo.

  Its tier is `TIER_INTERNAL` (`privacy.field_tiers.SOURCE_TIERS["clinical"]`): never
  on a public surface, safe inside owner-facing tooling and AI context. Two of the three
  callers produce text that can reach a public page (the daily brief's coach reads and
  the expert analyzer's observatory analyses). For those (`published=True`, the default)
  the block is GUARDRAILS ONLY (owner ruling, 2026-10-14): the neutrally-worded
  `GUIDANCE#current.public_rules` and nothing else — no diagnosis, medication, lab or
  ECG ever enters a prompt whose output can be published. No `public_rules` → "" (fail
  closed). The full record renders only for the owner's own channel (`published=False`,
  the owner's Telegram coach thread).

THE SORT-KEY FAMILIES (docs/SCHEMA.md)
  EVENT#<date>#<slug>              a diagnosis or clinical event (incl. a clinical ECG read)
  MED#<slug>                       a medication and its status
  ECG#<YYYY-MM-DDTHH:MM:SS>#<dev>  one consumer-device ECG recording
  LABS#<date>                      a clinical lab panel (`biomarkers`, the labs per-marker shape)
  HISTORY#<date>                   an intake history questionnaire (not rendered here)
  GUIDANCE#current                 the standing rules for coaches (`rules`, `public_rules`, `effective`, `review_after`)
  DOC#<date>#<slug>                an index row for one source document held in S3 (not rendered here)

FAIL-SOFT
  `clinical_context_block` never raises into a coach run: no rows, a failed read or a
  malformed row all return "" with a logged warning, and the coach runs as it did before
  the partition existed.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any, Iterable, Optional

logger = logging.getLogger(__name__)

CLINICAL_SOURCE = "clinical"
HEADER = "CLINICAL CONTEXT (owner record; medical instructions override coaching)"

# Bounds: the block rides every coach's prompt, so it is capped (~800 tokens). Over the
# cap, in-range lab values go first, then the oldest ECG recordings, then the oldest
# events — the guidance rules are never dropped (they are the point of the block).
MAX_CHARS = 3200
MAX_ECG = 8
MAX_IN_RANGE_LABS = 6
MAX_DETAIL_CHARS = 180
_MAX_PAGES = 10

# Medication statuses that are rendered. Anything else (stopped, declined, not started)
# is history, not a current constraint.
RENDERED_MED_STATUSES = ("active", "paused")
# Event statuses that mean the event no longer constrains anything.
_INACTIVE_EVENT_STATUSES = frozenset({"resolved", "inactive", "closed", "superseded"})
# Lab flags that mean "inside the reference range".
_IN_RANGE_FLAGS = frozenset({"", "normal", "n", "in_range", "in range", "ok"})
# The fields an EVENT row's one-line detail is drawn from, first present wins.
_DETAIL_FIELDS = ("interpretation", "presentation", "summary", "note", "detail")

PUBLIC_HEADER = "COACHING GUARDRAILS (owner instructions; they override your usual advice)"
PUBLISHED_NOTICE = (
    "Follow these guardrails silently. Your output may be read by others: do not mention, " "explain or speculate about why they exist."
)
PRIVATE_NOTICE = "Owner-only channel: you may refer to these facts directly when they bear on your advice."


def _num(value: Any) -> Any:
    """A DynamoDB Decimal as a plain int/float (integral values lose the trailing .0)."""
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _text(value: Any) -> str:
    return " ".join(str(_num(value)).split()) if value is not None else ""


def _clip(text: str, limit: int = 0) -> str:
    limit = limit or MAX_DETAIL_CHARS
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def fetch_clinical_rows(table, user_id: str = "matthew") -> Optional[list]:
    """Every row in the clinical partition (paginated), or None when the read failed."""
    pk = f"USER#{user_id}#SOURCE#{CLINICAL_SOURCE}"
    # The string form (not boto3's Key()): no boto3 import at render time, and the same
    # shape every other read in the coach fact packs uses.
    kwargs: dict = {"KeyConditionExpression": "pk = :pk", "ExpressionAttributeValues": {":pk": pk}}
    items: list = []
    for _page in range(_MAX_PAGES):
        resp = table.query(**kwargs)
        if not isinstance(resp, dict):
            return None
        items.extend(i for i in resp.get("Items") or [] if isinstance(i, dict))
        if not resp.get("LastEvaluatedKey"):
            return items
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    logger.warning("[clinical_facts] partition still paginating after %d pages — rendering what was read", _MAX_PAGES)
    return items


def _family(rows: Iterable[dict], prefix: str) -> list:
    return [r for r in rows if str(r.get("sk") or "").startswith(prefix)]


def _event_lines(rows: list) -> list:
    """Active events, newest first: `- <date> <title> [<status>] — <detail>`."""
    out = []
    events = sorted(_family(rows, "EVENT#"), key=lambda r: str(r.get("sk")), reverse=True)
    for r in events:
        status = _text(r.get("status")).lower()
        if status in _INACTIVE_EVENT_STATUSES:
            continue
        date = _text(r.get("date")) or str(r.get("sk")).split("#")[1]
        title = _text(r.get("title")) or _text(r.get("type")).replace("_", " ") or "clinical event"
        line = f"- {date} {title}"
        if status:
            line += f" [{status}]"
        detail = next((_text(r.get(f)) for f in _DETAIL_FIELDS if _text(r.get(f))), "")
        if detail:
            line += f" — {_clip(detail)}"
        out.append(line)
    return out


def _med_lines(rows: list) -> list:
    out = []
    for r in sorted(_family(rows, "MED#"), key=lambda r: str(r.get("sk"))):
        status = _text(r.get("status")).lower()
        if status not in RENDERED_MED_STATUSES:
            continue
        parts = [_text(r.get(k)) for k in ("name", "dose", "frequency") if _text(r.get(k))]
        if not parts:
            continue
        line = f"- {' '.join(parts)} [{status}]"
        note = _text(r.get("note")) or _text(r.get("adherence_note"))
        if note:
            line += f" — {_clip(note, 120)}"
        out.append(line)
    return out


def _ecg_lines(rows: list) -> list:
    """The most recent MAX_ECG recordings, NEWEST FIRST (so truncation pops from the end)."""
    ecgs = sorted(_family(rows, "ECG#"), key=lambda r: str(r.get("sk")), reverse=True)[:MAX_ECG]
    out = []
    for r in ecgs:
        parts = str(r.get("sk")).split("#")
        when = _text(r.get("recorded_at_local")) or (parts[1] if len(parts) > 1 else "")
        device = _text(r.get("device")) or (parts[2] if len(parts) > 2 else "device")
        line = f"- {when.replace('T', ' ')[:16]} {device}: {_text(r.get('verdict')) or 'no verdict'}"
        hr = _num(r.get("avg_hr_bpm"))
        if hr not in (None, ""):
            line += f", avg HR {hr} bpm"
        out.append(line)
    return out


def _marker_text(key: str, marker: dict) -> str:
    value = _text(marker.get("value"))
    unit = _text(marker.get("unit"))
    return f"{key.replace('_', ' ')} {value}{(' ' + unit) if unit else ''}".strip()


def _lab_lines(rows: list) -> tuple:
    """(heading, out-of-range lines, in-range lines) for the latest LABS# panel."""
    panels = sorted(_family(rows, "LABS#"), key=lambda r: str(r.get("sk")))
    if not panels:
        return "", [], []
    latest = panels[-1]
    markers = latest.get("biomarkers") if isinstance(latest.get("biomarkers"), dict) else {}
    date = _text(latest.get("collection_date")) or str(latest.get("sk")).split("#", 1)[1]
    flagged, in_range = [], []
    for key, marker in markers.items():
        if not isinstance(marker, dict):
            continue
        flag = _text(marker.get("flag")).lower()
        if flag in _IN_RANGE_FLAGS:
            in_range.append(f"- {_marker_text(key, marker)}")
        else:
            ref = _text(marker.get("ref_text"))
            flagged.append(f"- {_marker_text(key, marker)} ({flag.upper()}{'; ref ' + ref if ref else ''})")
    heading = f"LATEST CLINICAL LABS ({date}; {len(flagged)} of {len(flagged) + len(in_range)} markers out of range):"
    return heading, flagged, in_range[:MAX_IN_RANGE_LABS]


def _guidance_lines(rows: list, field: str = "rules") -> list:
    rows_g = [r for r in rows if str(r.get("sk")) == "GUIDANCE#current"]
    if not rows_g:
        return []
    g = rows_g[0]
    rules = [str(x) for x in (g.get(field) or []) if str(x).strip()]
    if not rules:
        return []
    window_parts = []
    if g.get("effective"):
        window_parts.append(f"effective {_text(g.get('effective'))}")
    if g.get("review_after"):
        window_parts.append(f"review after {_text(g.get('review_after'))}")
    window = ", ".join(window_parts)
    head = "STANDING GUIDANCE FOR COACHES" + (f" ({window})" if window else "") + ":"
    return [head] + [f"- {rule}" for rule in rules]


def render_clinical_block(rows: Optional[list], *, published: bool = True, max_chars: int = MAX_CHARS) -> str:
    """The block for a set of partition rows (pure; the unit-tested core)."""
    if not rows:
        return ""
    if published:
        # Guardrails only: the neutral public_rules, never the record itself.
        public = _guidance_lines(rows, "public_rules")
        if not public:
            return ""
        text = "\n\n".join([PUBLIC_HEADER, PUBLISHED_NOTICE, "\n".join(public[1:])])
        return text if len(text) <= max_chars else text[: max_chars - 1].rstrip() + "…"
    guidance = _guidance_lines(rows)
    events = _event_lines(rows)
    meds = _med_lines(rows)
    ecgs = _ecg_lines(rows)
    lab_head, lab_flagged, lab_in_range = _lab_lines(rows)
    if not (guidance or events or meds or ecgs or lab_head):
        return ""

    def assemble() -> str:
        sections = [HEADER, PRIVATE_NOTICE]
        if guidance:
            sections.append("\n".join(guidance))
        if events:
            sections.append("ACTIVE DIAGNOSES / CLINICAL EVENTS:\n" + "\n".join(events))
        if meds:
            sections.append("MEDICATIONS (active / paused):\n" + "\n".join(meds))
        if lab_head:
            body = lab_flagged + ((["in range:"] + lab_in_range) if lab_in_range else [])
            sections.append(lab_head + ("\n" + "\n".join(body) if body else ""))
        if ecgs:
            sections.append(f"RECENT ECG RECORDINGS (newest first, {len(ecgs)} shown):\n" + "\n".join(ecgs))
        return "\n\n".join(sections)

    text = assemble()
    # Truncation: in-range lab values, then ECGs oldest-first (the oldest is at the end of
    # the list), then events oldest-first. Guidance is never dropped here.
    for pool in (lab_in_range, ecgs, events):
        while len(text) > max_chars and pool:
            pool.pop()
            text = assemble()
    if len(text) > max_chars:
        text = text[: max_chars - 1].rstrip() + "…"
    return text


def clinical_context_block(table, *, published: bool = True, user_id: str = "matthew") -> str:
    """THE entry point: the owner clinical record as a prompt block, or "" (fail-soft).

    `published=True` (the default — fail closed) renders the guardrails only, for a coach
    whose output can reach a public page; only the owner's own channel passes False.
    """
    if table is None:
        return ""
    try:
        rows = fetch_clinical_rows(table, user_id)
        if rows is None:
            logger.warning("[clinical_facts] clinical partition read returned no response — block omitted")
            return ""
        return render_clinical_block(rows, published=published)
    except Exception as e:  # noqa: BLE001 — a coach run is never load-bearing on this read
        logger.warning("[clinical_facts] clinical context unavailable (block omitted): %s", e)
        return ""
