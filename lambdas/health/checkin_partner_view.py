"""health/checkin_partner_view.py — the ONE projection of the evening check-in a third party may read (#5125 R5).

THE RULING (owner, 2026-10-23, #5125 R5): "rebuild the weekly partner email on check-in data". The partner email's
old emotional inputs — the Notion journal's enriched mood / energy / stress, themes, avoidance and quotes — are dark
(nothing has landed this cycle), so the email described his week from nothing. The evening check-in (#5106: hunger,
stress, cravings 0-4 and one word, settled into ``health.checkin_intake_pairs`` ``DATE#<day>`` rows by #5211) is the
live self-report channel, and this module is how the partner email reads it.

THE PRIVACY SHAPE. Both check-in partitions are ``TIER_OWNER_ONLY`` (``privacy.field_tiers``): never a public surface,
never quoted into an AI narrative context. The owner's ruling is consent for ONE named recipient — the partner,
whose address is SSM-resolved and never in the repo — to see a COARSE weekly read. So this projection is the whole
carve-out, and it is narrow by construction:
  * it PROJECTS only ``sk, has_checkin, hunger, stress, cravings`` — never the day's intake (kcal, protein, meal
    time, the target), never the mood valence, and never the free ``word``;
  * it returns words and one count: how many evenings he answered, and for each rating a band (``low`` /
    ``moderate`` / ``high``) with the direction against the previous week — never a raw score, never a day;
  * below ``MIN_EVENINGS`` answered evenings a rating reads "too few check-ins to say" (ADR-104: an honest absence,
    never a pattern read off two evenings);
  * it is rendered DETERMINISTICALLY into the email (``partner_email_lambda.checkin_block_html``) and is never put in
    the model's prompt — the tier's "never quoted into an AI narrative" rule holds for the partner letter too.
``tests/test_partner_email_checkins_5125.py`` holds every line above; ``tests/test_evening_checkin_5106.py`` holds that
this is the only door from ``lambdas/emails/`` to either partition.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

SOURCE = "checkin_intake_pairs"  # the settled next-morning day rows (#5211)
PK = f"USER#matthew#SOURCE#{SOURCE}"
FIELDS = ("stress", "hunger", "cravings")
PROJECTION = "sk, has_checkin, hunger, stress, cravings"
MIN_EVENINGS = 3  # fewer answered evenings than this reads as "too few to say"
LOW_BELOW, HIGH_FROM = 1.5, 2.5  # bands on the 0-4 scale: [0, 1.5) low, [1.5, 2.5) moderate, [2.5, 4] high
SHIFT = 0.5  # a week-over-week move smaller than half a point is "about the same"
TOO_FEW = "too few check-ins to say"


def _num(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None


def band(mean: Optional[float]) -> Optional[str]:
    if mean is None:
        return None
    return "low" if mean < LOW_BELOW else ("moderate" if mean < HIGH_FROM else "high")


def _answered(rows: list) -> list:
    return [r for r in rows or [] if r.get("has_checkin") is True or any(_num(r.get(f)) is not None for f in FIELDS)]


def _mean(rows: list, field: str) -> Optional[float]:
    vals = [v for v in (_num(r.get(field)) for r in rows) if v is not None]
    return sum(vals) / len(vals) if vals else None


def summarize(rows: list, prior_rows: Optional[list] = None, days: int = 7) -> dict[str, Any]:
    """The partner's weekly read from one week's day rows (and last week's, for direction). Pure.

    Returns {"evenings": int, "days": int, "ratings": {field: {"band", "direction"}}, "sentence": str} — words and
    one count only. ``band``/``direction`` are None (and the sentence says so) below ``MIN_EVENINGS``."""
    week, prior = _answered(rows), _answered(prior_rows or [])
    out: dict[str, Any] = {"evenings": len(week), "days": days, "ratings": {}}
    for f in FIELDS:
        cell: dict[str, Optional[str]] = {"band": None, "direction": None}
        if len(week) >= MIN_EVENINGS:
            m = _mean(week, f)
            cell["band"] = band(m)
            pm = _mean(prior, f) if len(prior) >= MIN_EVENINGS else None
            if m is not None and pm is not None:
                cell["direction"] = (
                    "higher than last week"
                    if m - pm >= SHIFT
                    else ("lower than last week" if pm - m >= SHIFT else "about the same as last week")
                )
        out["ratings"][f] = cell
    out["sentence"] = sentence(out)
    return out


def sentence(view: Mapping[str, Any]) -> str:
    n, days = int(view.get("evenings") or 0), int(view.get("days") or 7)
    if n == 0:
        return "He did not answer the evening check-in this week."
    head = f"He answered {n} of {days} evening check-ins."
    if n < MIN_EVENINGS:
        return f"{head} That is {TOO_FEW} how his evenings went."
    parts = []
    for f in FIELDS:
        cell = (view.get("ratings") or {}).get(f) or {}
        if cell.get("band"):
            parts.append(f"{f} mostly {cell['band']}" + (f" ({cell['direction']})" if cell.get("direction") else ""))
    return head + (" " + "; ".join(parts).capitalize() + "." if parts else "")


def read_rows(table: Any, start: str, end: str) -> list:
    """The settled day rows for [start, end], projected to the check-in fields only. Raises on a read failure."""
    rows: list = []
    kwargs: dict[str, Any] = {
        "KeyConditionExpression": "pk = :pk AND sk BETWEEN :lo AND :hi",
        "ExpressionAttributeValues": {":pk": PK, ":lo": f"DATE#{start}", ":hi": f"DATE#{end}~"},
        "ProjectionExpression": PROJECTION,
    }
    while True:
        resp = table.query(**kwargs)
        rows.extend(resp.get("Items") or [])
        if "LastEvaluatedKey" not in resp:
            return rows
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


def week_view(table: Any, start: str, end: str, prior_start: str, prior_end: str) -> dict[str, Any]:
    """`summarize` over the stored rows. A read failure is an honest absence (``evenings`` None), never zero."""
    try:
        rows = read_rows(table, start, end)
        prior = read_rows(table, prior_start, prior_end)
    except Exception as e:  # noqa: BLE001 — the letter still goes; it says the read is unavailable
        return {
            "evenings": None,
            "days": 7,
            "ratings": {},
            "sentence": "His evening check-ins could not be read this week.",
            "error": type(e).__name__,
        }
    return summarize(rows, prior)
