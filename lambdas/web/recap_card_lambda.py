"""recap_card_lambda.py — Day N's card, rendered the morning after Day N (#3741).

THE CLOCK, AND WHY IT IS ONE DAY BEHIND

The owner asked whether being a day behind was acceptable and answered his own question:
*"i think it may be better sense that we are always one day behind, so 1130am PT is fine,
and i post it, but that was for yesterday?"*

It is not a compromise, it is the only honest clock. Day N is not a finished day until the
next morning: MacroFactor nutrition lands ~24h late, the night's Whoop sleep and recovery
arrive the following morning, and `computed_metrics` for Day N is written by the compute
cron on Day N+1. A card rendered the same evening would publish a nutrition figure missing
dinner and call it the day.

So: the 11:30 PT run renders the card for YESTERDAY, and the card says "Day N".

THE WEEKLY CARD IS DERIVED, NOT A SECOND CRON

Cycle 17's genesis (2026-09-06) is a SUNDAY, so the experiment week Days 1-7 runs Sun..Sat
and closes on a Saturday; its card renders the Sunday morning after. But the rule is
`day_n % 7 == 0` on the date being rendered, never a weekday — genesis moves every cycle
(seventeen so far), and a `SAT`/`SUN` literal would be correct until the next reset and
wrong silently after it.

THE ORDER OF OPERATIONS IS THE SAFETY PROPERTY

  facts → pick → GATE → render → store → deliver → record

The gate runs before the render and the render before the send, so a blocked term costs
CPU rather than reaching a public grid. The record is written whatever happened, including
"no signal" and "held" — a day with no card is a fact about the day, and next month the
only way to know why is this row.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import boto3
from common.constants import EXPERIMENT_START_DATE
from common.pacific_time import pacific_day_n, pacific_now

try:
    from common.platform_logger import get_logger

    logger = get_logger("recap-card-generator")
except ImportError:  # pragma: no cover — bundle-shape fallback
    logger = logging.getLogger("recap-card-generator")
    logger.setLevel(logging.INFO)

TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
S3_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")
RECAP_PREFIX = os.environ.get("RECAP_S3_PREFIX", "generated/recap/")
TELEGRAM_SECRET_ID = os.environ.get("TELEGRAM_SECRET_ID", "life-platform/telegram")
TELEGRAM_BOT_KEY = os.environ.get("TELEGRAM_BOT_KEY", "headcoach")
EMAIL_SENDER = os.environ.get("EMAIL_SENDER", "")
EMAIL_RECIPIENT = os.environ.get("EMAIL_RECIPIENT", "")

RECAP_SOURCE = "recap_cards"

_ddb = boto3.resource("dynamodb", region_name=os.environ.get("AWS_REGION", "us-west-2"))
_table = _ddb.Table(TABLE_NAME)
_s3 = boto3.client("s3", region_name=os.environ.get("AWS_REGION", "us-west-2"))


def _yesterday_pt() -> str:
    from datetime import timedelta

    return (pacific_now().date() - timedelta(days=1)).isoformat()


def _date_label(date: str) -> str:
    from datetime import date as _date

    try:
        return _date.fromisoformat(date).strftime("%a %-d %b")
    except ValueError:
        return date


def _telegram_secret() -> dict:
    from common.secret_cache import get_secret_json

    return get_secret_json(TELEGRAM_SECRET_ID, boto3.client("secretsmanager", region_name=os.environ.get("AWS_REGION", "us-west-2")))


def _existing(sk: str) -> dict | None:
    try:
        return _table.get_item(Key={"pk": f"USER#matthew#SOURCE#{RECAP_SOURCE}", "sk": sk}).get("Item")
    except Exception:  # noqa: BLE001
        return None


def _record(sk: str, payload: dict[str, Any]) -> None:
    """The row that makes 'a different card every day' provable, and 'no card' explicable."""
    from common.numeric import floats_to_decimal

    item = {"pk": f"USER#matthew#SOURCE#{RECAP_SOURCE}", "sk": sk, **payload}
    try:
        _table.put_item(Item=floats_to_decimal(item))
    except Exception as e:  # noqa: BLE001
        logger.error("recap record write failed for %s: %s: %s", sk, type(e).__name__, e)


def _week_totals(table, start: str, end: str) -> dict[str, Any]:
    """The week's own numbers, computed from its days — never hand-typed (the #3565 class)."""
    from content import recap_data

    from web import recap_layouts as RL

    days = recap_data._day_range(start, end)
    allf = [recap_data.day_facts(table, d, experiment_start=EXPERIMENT_START_DATE) for d in days]
    weighed = [x.weight_lb for x in allf if x.weight_lb is not None]
    pcts = [x.tier0_pct for x in allf if x.tier0_pct is not None]
    worst = min(((k, v) for x in allf for k, v in x.component_scores.items()), key=lambda kv: kv[1], default=None)
    totals: dict[str, Any] = {
        "sessions": sum(1 for x in allf if x.workouts),
        "sets": sum(sum(w.n_sets for w in x.workouts) for x in allf),
    }
    if len(weighed) >= 2:
        totals["weight_delta"] = round(weighed[-1] - weighed[0], 1)
    if pcts:
        totals["habit_pct"] = round(100 * sum(p if p <= 1 else p / 100 for p in pcts) / len(pcts))
    if worst:
        totals["misses"] = f"{RL._COMPONENT_NAMES.get(worst[0], worst[0])} — {worst[1]:.0f}/100 at its worst"
    return totals


def render_for_date(date: str, *, deliver: bool = True, force: bool = False, dry_run: bool = False) -> dict[str, Any]:
    """Render (and optionally send) the card for one PT date. Returns the picker record."""
    from content import recap_data, recap_deliver, recap_gate

    from web import recap_canvas, recap_layouts

    sk = f"DATE#{date}"
    if not force:
        prior = _existing(sk)
        if prior and (prior.get("delivered") or {}).get("telegram") in ("ok", "dry_run"):
            logger.info("recap for %s already delivered; skipping (pass force to re-send)", date)
            return {"status": "already_delivered", "date": date}

    facts = recap_data.day_facts(_table, date, experiment_start=EXPERIMENT_START_DATE)
    trailing = recap_data.trailing(_table, date, days=7, experiment_start=EXPERIMENT_START_DATE)
    weight_series, grade_series = recap_data.cycle_series(_table, EXPERIMENT_START_DATE, date)

    # The BEAT, not the biggest number. See recap_layouts.pick_beat.
    layout, why = recap_layouts.pick_beat(facts, trailing)
    day_label = f"Day {facts.day_n}" if facts.day_n else ""

    base: dict[str, Any] = {
        "date": date,
        "day_n": facts.day_n,
        "beat": layout,
        "beat_reason": why,
        "grade": facts.grade_letter,
        "absent_sources": facts.absent,
        "algo_version": recap_layouts.__name__ + "@2",
        "rendered_at": pacific_now().isoformat(),
        "dry_run": dry_run,
    }

    caption = recap_layouts.caption_for_beat(layout, facts, day_label=day_label, date_label=_date_label(date))

    # GATE BEFORE RENDER. A blocked term costs CPU, never a public frame.
    verdict = recap_gate.gate(recap_layouts.gate_strings(facts, caption), items=facts.item_labels())
    if not verdict.may_send:
        _record(sk, {**base, "outcome": "held", "privacy": verdict.to_dict()})
        logger.warning("recap for %s held by the privacy gate: %s", date, verdict.reason)
        return {**base, "outcome": "held"}

    try:
        img = recap_layouts.render_beat(layout, facts, date_label=_date_label(date), weight_series=weight_series, grade_series=grade_series)
    except Exception as e:  # noqa: BLE001
        # A layout that cannot be drawn honestly for this day falls back to the scorecard,
        # which needs the least. If THAT cannot draw either, the day has no card — which is
        # a fact about the day, not a failure of the run.
        logger.warning("beat %s could not render for %s (%s); falling back to scorecard", layout, date, type(e).__name__)
        try:
            img = recap_layouts.scorecard(facts, date_label=_date_label(date))
            base["beat"] = layout = "scorecard"
            base["beat_reason"] = f"fell back from {layout} — {type(e).__name__}"
        except Exception as e2:  # noqa: BLE001
            _record(sk, {**base, "outcome": "no_signal", "error": f"{type(e2).__name__}: {e2}"})
            return {**base, "outcome": "no_signal"}

    png = recap_canvas.to_png_bytes(img)
    key = f"{RECAP_PREFIX}{date}.png"
    try:
        # No CacheControl and no CloudFront invalidation: this object is NOT served. There
        # is no /recap/* behaviour on the distribution, deliberately — the card is private
        # until he posts it (ADR-140 rule 5, human selection only).
        _s3.put_object(Bucket=S3_BUCKET, Key=key, Body=png, ContentType="image/png")
    except Exception as e:  # noqa: BLE001
        logger.error("recap put_object failed for %s: %s: %s", key, type(e).__name__, e)

    # The weekly card is derived from the daily run, not a second cron.
    weekly_key = None
    day_n = pacific_day_n(EXPERIMENT_START_DATE, date)
    if day_n and day_n % 7 == 0:
        try:
            week_n = day_n // 7
            wk_start = recap_data._day_range(EXPERIMENT_START_DATE, date)[-7]
            totals = _week_totals(_table, wk_start, date)
            wimg = recap_layouts.reckoning(
                facts,
                week_n=week_n,
                date_label=f"week {week_n} · {_date_label(wk_start)} – {_date_label(date)}",
                weight_series=weight_series,
                grade_series=grade_series[-7:],
                totals=totals,
            )
            weekly_key = f"{RECAP_PREFIX}week-{week_n:02d}.png"
            _s3.put_object(Bucket=S3_BUCKET, Key=weekly_key, Body=recap_canvas.to_png_bytes(wimg), ContentType="image/png")
            base["weekly"] = {"week": week_n, "s3_key": weekly_key, "totals": totals}
        except Exception as e:  # noqa: BLE001
            logger.error("weekly card failed for %s: %s: %s", date, type(e).__name__, e)
            base["weekly"] = {"error": f"{type(e).__name__}: {e}"}

    delivered: dict[str, str] = {}
    if deliver:
        delivered = recap_deliver.deliver(
            png,
            caption,
            dry_run=dry_run,
            telegram_secret_getter=_telegram_secret,
            telegram_bot_key=TELEGRAM_BOT_KEY,
            ses_client=boto3.client("ses", region_name=os.environ.get("AWS_REGION", "us-west-2")),
            sender=EMAIL_SENDER,
            recipient=EMAIL_RECIPIENT,
            subject=f"{day_label or date} — your card",
            filename=f"recap-{date}.png",
        )

    record = {
        **base,
        "outcome": "sent" if deliver else "rendered",
        "s3_key": key,
        "privacy": verdict.to_dict(),
        "delivered": delivered,
        "caption": caption,
    }
    _record(sk, record)
    return record


def lambda_handler(event: dict | None, context: Any) -> dict:
    """Scheduled at 11:30 PT for YESTERDAY; `date` / `deliver` / `force` for a backfill."""
    event = event or {}
    date = event.get("date") or _yesterday_pt()

    try:
        deliver = bool(event.get("deliver", True))
        force = bool(event.get("force", False))

        from common.dry_run import is_dry_run

        dry_run = is_dry_run(event)

        out = render_for_date(date, deliver=deliver, force=force, dry_run=dry_run)

        return {"statusCode": 200, "body": out}
    except Exception as e:  # noqa: BLE001
        # I4: an uncaught exception in an async Lambda is silence — the schedule fires,
        # nothing arrives, and nothing says why. A structured error still reaches the DLQ
        # digest and the logs name the day that failed.
        logger.exception("recap card failed for %s: %s: %s", date, type(e).__name__, e)
        return {"statusCode": 500, "body": {"date": date, "error": f"{type(e).__name__}: {e}"}}
