"""rhythm_channel.py — the owner-only heart-rhythm event channel (#4972, epic #4967).

WHAT IT IS
  Three Health Auto Export (HAE) event types become rows in the owner clinical partition
  (`USER#matthew#SOURCE#clinical`, `health/clinical_facts.py`), under ONE sort-key prefix:

    RHYTHM#ECG#<YYYY-MM-DDTHH:MM:SS>#<device-slug>    one ECG recording
    RHYTHM#HRNOTIF#<YYYY-MM-DDTHH:MM:SS>#<kind>       one heart-rate notification
                                                      (high / low / irregular / hypertension / unknown)
    RHYTHM#MEDLOG#<YYYY-MM-DDTHH:MM:SS>#<name-hash>   one medication-log entry

  The timestamp is the event's own local wall-clock time (HAE sends it with its offset),
  the same form the loader's `ECG#` family uses. The medication key carries a short hash
  of the name, never the name: a key is not field-stripped by any dumper.

WHO MAY READ IT (owner ruling (c), 2026-10-17: heart-rhythm data is owner-only)
  Every field this module writes is declared `TIER_OWNER_ONLY` in
  `privacy.field_tiers.FIELD_TIERS["clinical"]`, and the `RHYTHM#` prefix is deliberately
  NOT one of the families `clinical_facts.render_clinical_block` renders — the coach fact
  pack is #4977's scope, not this one. No `/api/*` route and no public reader may name the
  prefix or a field (`tests/test_rhythm_channel_privacy_4972.py`, sweep + route walk).

ABSENCE (docs/NEW_SIGNAL_PLAYBOOK.md, day 1)
  No event = no row. Nothing here writes to the `apple_health` day row, so a day row never
  carries a 0 for any of these. Inside a row, a value the vendor sent as 0 or omitted
  (an average heart rate of 0, a notification with no reading) is OMITTED, never 0.

ECG DE-DUPLICATION
  One row per instant + device. A re-delivered recording finds its own key (the put is
  conditional, so the first write is never clobbered) — and a recording within
  `SAME_RECORDING_SECONDS` of an ECG the partition already holds (the loader's `ECG#`
  rows, or a `RHYTHM#ECG#` row under another device spelling) is the same recording,
  stored once. Withings holds its own ECG result on its day row (`afib_result`); a
  Withings-sourced ECG mirrored through Apple Health within the tolerance of one of that
  row's measurement timestamps is already stored there and is skipped. A WATCH ECG on a
  day Withings also recorded one is a different recording: two rows, never merged, and
  this row carries `cross_device_same_day: true`.

PAYLOAD SHAPES
  From the HAE vendor documentation (JSON export, version 2) — not yet captured live (no
  ECG / notification / medication payload has reached the webhook as of 2026-10-18,
  #4968). The parsers accept the documented keys and their snake_case spellings, and an
  entry they cannot read is counted as `skipped`, never guessed.
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Iterable, Optional

logger = logging.getLogger(__name__)

PREFIX = "RHYTHM#"
ECG_PREFIX = PREFIX + "ECG#"
NOTIF_PREFIX = PREFIX + "HRNOTIF#"
MEDLOG_PREFIX = PREFIX + "MEDLOG#"
CHANNEL = "rhythm"
INGESTED_BY = "health-auto-export"
SCHEMA_VERSION = 1
SAME_RECORDING_SECONDS = 60

# The payload keys each event type arrives under (vendor-documented camelCase first).
ECG_KEYS = ("ecg", "ECG", "electrocardiogram", "electrocardiograms")
NOTIF_KEYS = ("heartRateNotifications", "heart_rate_notifications", "heartRateNotification")
MED_KEYS = ("medications", "Medications", "medication")

NOTIFICATION_KINDS = ("high", "low", "irregular", "hypertension")

# Every field this module writes that carries channel content — the owner-only vocabulary.
# `privacy.field_tiers.FIELD_TIERS["clinical"]` declares each one TIER_OWNER_ONLY; the
# privacy test reads this tuple, so a new field cannot be added without being tiered.
ECG_FIELDS = ("rhythm_ecg_classification", "rhythm_ecg_avg_hr_bpm", "rhythm_ecg_sample_start", "rhythm_ecg_device", "cross_device_same_day")
NOTIF_FIELDS = (
    "rhythm_notification_kind",
    "rhythm_notification_kind_inferred",
    "rhythm_notification_at",
    "rhythm_notification_bpm",
    "rhythm_notification_threshold_bpm",
    "rhythm_notification_device",
)
MED_FIELDS = ("rhythm_med_name", "rhythm_med_dose_text", "rhythm_med_at", "rhythm_med_status")
CHANNEL_FIELDS = ECG_FIELDS + NOTIF_FIELDS + MED_FIELDS

_TS_FORMATS = ("%Y-%m-%d %H:%M:%S %z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z")


def parse_instant(value: Any) -> Optional[datetime]:
    """An HAE timestamp ("2026-10-17 08:12:03 -0700") as an aware datetime, or None."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+0000")
    for fmt in _TS_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _local_key(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def _slug(text: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-") or "unknown-device"


def _positive(value: Any) -> Optional[Decimal]:
    """A strictly positive number as Decimal; 0, negatives, junk and None are absence."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    if num != num or num <= 0:  # NaN or non-positive
        return None
    return Decimal(str(round(num, 1)))


def _entries(data: Any, keys: Iterable[str]) -> list:
    if not isinstance(data, dict):
        return []
    for key in keys:
        value = data.get(key)
        if isinstance(value, list):
            return [e for e in value if isinstance(e, dict)]
    return []


def _base(sk: str, kind: str, dt: datetime, now_iso: str) -> dict:
    return {
        "sk": sk,
        "source": "clinical",
        "channel": CHANNEL,
        "event_kind": kind,
        "event_date": dt.strftime("%Y-%m-%d"),
        "ingested_by": INGESTED_BY,
        "schema_version": SCHEMA_VERSION,
        "updated_at": now_iso,
    }


# ── Parsers (pure) ────────────────────────────────────────────────────────────


def parse_ecgs(data: Any, now_iso: str) -> tuple[list, int]:
    """(rows, skipped) for the payload's ECG recordings."""
    rows, skipped = [], 0
    for e in _entries(data, ECG_KEYS):
        dt = parse_instant(e.get("start") or e.get("startDate") or e.get("date"))
        classification = str(e.get("classification") or "").strip()
        if dt is None or not classification:
            skipped += 1
            continue
        device = str(e.get("source") or e.get("device") or "").strip()
        row = _base(f"{ECG_PREFIX}{_local_key(dt)}#{_slug(device)}", "ecg", dt, now_iso)
        row["rhythm_ecg_classification"] = classification
        row["rhythm_ecg_sample_start"] = dt.isoformat()
        if device:
            row["rhythm_ecg_device"] = device
        hr = _positive(e.get("averageHeartRate", e.get("average_heart_rate")))
        if hr is not None:
            row["rhythm_ecg_avg_hr_bpm"] = hr
        rows.append(row)
    return rows, skipped


def _hr_values(entry: dict) -> list:
    out = []
    for r in entry.get("heartRate") or entry.get("heart_rate") or []:
        if isinstance(r, dict):
            v = _positive(r.get("hr", r.get("qty")))
            if v is not None:
                out.append(v)
    return out


def _notification_kind(entry: dict, threshold: Optional[Decimal], values: list) -> tuple[str, bool]:
    """(kind, inferred). A kind the payload names wins; otherwise it is inferred from shape."""
    for key in ("type", "kind", "notificationType", "name", "category"):
        named = str(entry.get(key) or "").lower()
        for kind in NOTIFICATION_KINDS:
            if kind in named:
                return kind, False
    if threshold is not None and values:
        if max(values) >= threshold:
            return "high", True
        if min(values) <= threshold:
            return "low", True
    if entry.get("heartRateVariation") or entry.get("heart_rate_variation"):
        return "irregular", True
    return "unknown", True


def parse_notifications(data: Any, now_iso: str) -> tuple[list, int]:
    rows, skipped = [], 0
    for e in _entries(data, NOTIF_KEYS):
        dt = parse_instant(e.get("start") or e.get("date") or e.get("startDate"))
        if dt is None:
            skipped += 1
            continue
        threshold = _positive(e.get("threshold"))
        values = _hr_values(e)
        kind, inferred = _notification_kind(e, threshold, values)
        row = _base(f"{NOTIF_PREFIX}{_local_key(dt)}#{kind}", "hr_notification", dt, now_iso)
        row["rhythm_notification_kind"] = kind
        row["rhythm_notification_kind_inferred"] = inferred
        row["rhythm_notification_at"] = dt.isoformat()
        if threshold is not None:
            row["rhythm_notification_threshold_bpm"] = threshold
        if values:
            row["rhythm_notification_bpm"] = min(values) if kind == "low" else max(values)
        device = str(e.get("source") or e.get("device") or "").strip()
        if device:
            row["rhythm_notification_device"] = device
        rows.append(row)
    return rows, skipped


def _dose_text(entry: dict) -> str:
    dose = entry.get("dosage", entry.get("dose"))
    unit = entry.get("unit") or entry.get("form") or ""
    if dose in (None, ""):
        return str(unit).strip()
    if isinstance(dose, float) and dose.is_integer():
        dose = int(dose)
    return f"{dose} {unit}".strip()


def parse_medications(data: Any, now_iso: str) -> tuple[list, int]:
    rows, skipped = [], 0
    for e in _entries(data, MED_KEYS):
        name = str(e.get("nickname") or e.get("displayText") or e.get("name") or "").strip()
        dt = parse_instant(e.get("start") or e.get("date") or e.get("scheduledDate") or e.get("startDate"))
        if dt is None or not name:
            skipped += 1
            continue
        digest = hashlib.sha256(name.lower().encode("utf-8")).hexdigest()[:10]
        row = _base(f"{MEDLOG_PREFIX}{_local_key(dt)}#{digest}", "medication_log", dt, now_iso)
        row["rhythm_med_name"] = name
        row["rhythm_med_at"] = dt.isoformat()
        dose = _dose_text(e)
        if dose:
            row["rhythm_med_dose_text"] = dose
        status = str(e.get("status") or "").strip().lower()
        if status:
            row["rhythm_med_status"] = status
        rows.append(row)
    return rows, skipped


# ── ECG de-duplication (reads) ────────────────────────────────────────────────


def _is_apple(device: str) -> bool:
    d = device.lower()
    return "watch" in d or "apple" in d or "iphone" in d


def _query_prefix(table, pk: str, prefix: str) -> list:
    resp = table.query(
        KeyConditionExpression="pk = :pk AND begins_with(sk, :p)",
        ExpressionAttributeValues={":pk": pk, ":p": prefix},
    )
    return [i for i in (resp or {}).get("Items") or [] if isinstance(i, dict)]


def _local_dt_of_sk(sk: str, family_prefix: str) -> Optional[datetime]:
    rest = sk[len(family_prefix) :]
    try:
        return datetime.strptime(rest[:19], "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return None


def ecg_verdicts(table, rows: list, user_id: str = "matthew") -> tuple[list, int]:
    """(rows to write, duplicates) — applies the same-recording and cross-device rules.

    Reads only: the day's existing ECG rows in the clinical partition and the Withings day
    row (the `withings` partition is a per-day singleton written by withings_lambda; this
    read is a key lookup for one attribute, not a generation path).
    """
    pk = f"USER#{user_id}#SOURCE#clinical"
    keep, dupes = [], 0
    for row in rows:
        local = datetime.strptime(row["sk"][len(ECG_PREFIX) :][:19], "%Y-%m-%dT%H:%M:%S")
        day = row["event_date"]
        existing = []
        for family in ("ECG#", ECG_PREFIX):
            for item in _query_prefix(table, pk, family + day):
                when = _local_dt_of_sk(str(item.get("sk") or ""), family)
                if when is not None:
                    existing.append(when)
        if any(abs((when - local).total_seconds()) <= SAME_RECORDING_SECONDS for when in existing):
            dupes += 1
            continue
        withings = (table.get_item(Key={"pk": f"USER#{user_id}#SOURCE#withings", "sk": f"DATE#{day}"}) or {}).get("Item") or {}
        if "afib_result" in withings:
            device = str(row.get("rhythm_ecg_device") or "")
            if device and not _is_apple(device):
                at_utc = datetime.fromisoformat(row["rhythm_ecg_sample_start"]).astimezone(timezone.utc).timestamp()
                stamps = [g.get("timestamp") for g in withings.get("measurement_group_attribs") or [] if isinstance(g, dict)]
                if any(_positive(s) is not None and abs(float(s) - at_utc) <= SAME_RECORDING_SECONDS for s in stamps):
                    dupes += 1
                    continue
            row["cross_device_same_day"] = True
        keep.append(row)
    return keep, dupes


# ── The entry point the webhook calls ─────────────────────────────────────────


def has_channel_payload(data: Any) -> bool:
    return bool(_entries(data, ECG_KEYS) or _entries(data, NOTIF_KEYS) or _entries(data, MED_KEYS))


def ingest(table, data: Any, *, user_id: str = "matthew", now_iso: Optional[str] = None) -> dict:
    """Parse, de-duplicate and write the payload's channel events. Returns COUNTS only —
    the caller logs this dict, so it must never carry a value."""
    from health import clinical_facts

    now_iso = now_iso or datetime.now(timezone.utc).isoformat()
    ecg_rows, ecg_skipped = parse_ecgs(data, now_iso)
    notif_rows, notif_skipped = parse_notifications(data, now_iso)
    med_rows, med_skipped = parse_medications(data, now_iso)
    ecg_rows, ecg_dupes = ecg_verdicts(table, ecg_rows, user_id) if ecg_rows else ([], 0)
    written, dupes = clinical_facts.put_channel_rows(table, ecg_rows + notif_rows + med_rows, user_id=user_id)
    return {
        "ecg_parsed": len(ecg_rows) + ecg_dupes,
        "notifications_parsed": len(notif_rows),
        "medication_log_parsed": len(med_rows),
        "written": written,
        "duplicates": dupes + ecg_dupes,
        "skipped": ecg_skipped + notif_skipped + med_skipped,
        "cross_device_same_day": sum(1 for r in ecg_rows if r.get("cross_device_same_day")),
    }


def webhook_ingest(table, data: Any, *, user_id: str = "matthew") -> dict:
    """The Health Auto Export webhook's one call (#4972). The three event types are their own
    HAE data types, so a delivery without them returns {} untouched; with them, `ingest`
    writes the RHYTHM# rows and the COUNTS come back (the webhook logs and returns them). A
    failure is logged at ERROR by exception class only — never a value — and never sinks the
    rest of the delivery."""
    if not has_channel_payload(data):
        return {}
    try:
        result = ingest(table, data, user_id=user_id)
        logger.info("rhythm_channel %s", result)
        return result
    except Exception as e:  # noqa: BLE001 — one data type never sinks the webhook
        logger.error("rhythm_channel_error: %s", type(e).__name__)
        return {"error": type(e).__name__}
