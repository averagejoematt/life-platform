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
wrong silently after it. The check itself lives in `pacific_time.week_close_day` (#3761)
so the progress-photo protocol's target capture day can never independently drift from
this card's own week boundary.

TWO CARDS A DAY

The owner's brief on 2026-09-19: *"two graphics per day, maybe day 1 is the high level
overview, highlights, insights, specifics, and the second image is a dual or three part
split screen summarizing what i actually worked out that day, what i ate that day if
available, and then any other sort of insights."* So the beat card is card 1 of 2 and the
`detail` layout is card 2 — stored at `{date}-detail.png`, delivered as a second photo
with its own caption, recorded on the same row. Card 2 is not a second beat: it is fixed
in shape and draws only the bands the day has, and a day with fewer than two bands has no
second card (which the record says).

THE ORDER OF OPERATIONS IS THE SAFETY PROPERTY

  facts → pick → GATE → render → QA → store → deliver → record

The QA step (`recap_qa`, 2026-09-19) audits the DRAWN frame — clipped text, overlaps,
undrawable glyphs, placeholder strings — and a hard finding holds that card the way the
privacy gate holds a blocked term: nothing stored, nothing sent, the finding on the row.

The gate runs before the render and the render before the send, so a blocked term costs
CPU rather than reaching a public grid. The record is written whatever happened, including
"no signal" and "held" — a day with no card is a fact about the day, and next month the
only way to know why is this row.
"""

from __future__ import annotations

import base64
import logging
import os
from typing import Any

import boto3
from common.constants import EXPERIMENT_START_DATE
from common.pacific_time import pacific_day_n, pacific_now, week_close_day

try:
    from common.platform_logger import get_logger

    logger = get_logger("recap-card-generator")
except ImportError:  # pragma: no cover — bundle-shape fallback
    logger = logging.getLogger("recap-card-generator")
    logger.setLevel(logging.INFO)

TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
S3_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")
#: The card's S3 home. NOT under `generated/` (#3741 follow-up): the bucket policy's
#: `PublicReadGenerated` statement grants anonymous `s3:GetObject` on `generated/*`, so a
#: card written there is world-readable at a fully derivable key the moment it renders —
#: which is exactly what shipped, and exactly the #3559 defect one prefix over. `recap/`
#: is anonymously unreadable AND outside `ProtectDataFromDeployScripts`, so a card can
#: also be purged; both halves are asserted in tests/test_recap_card_private_3741.py.
RECAP_PREFIX = os.environ.get("RECAP_S3_PREFIX", "recap/")
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


def _genesis_eve() -> str:
    """The one date that renders as Day 0 — the day before genesis, and no other.

    `pacific_day_n` clamps EVERY pre-genesis date to 0, which is right for a site that
    should never say "Day −3" and wrong for a card: a backfill for a random August date
    must not mint a starting-line card. Day 0 is exactly one calendar day.
    """
    from datetime import timedelta

    from common.pacific_time import parse_day_key

    g = parse_day_key(EXPERIMENT_START_DATE)
    return (g - timedelta(days=1)).isoformat() if g else ""


def _date_label(date: str) -> str:
    from common.pacific_time import parse_day_key

    d = parse_day_key(date)
    return d.strftime("%a %-d %b") if d else date


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


#: Cumulative-loss lines worth a stripe, in lb. Crossed once each per cycle.
MILESTONE_LB = (5, 10, 25, 50, 75, 100)
#: Day numbers worth a stripe (the week closes are the reckoning's job).
MILESTONE_DAYS = {30: "one month in", 60: "two months in", 90: "three months in", 100: "day 100", 180: "six months in", 365: "one year in"}


#: A volume best needs this many earlier sessions in the cycle before it is a milestone —
#: the third session of the experiment is trivially "the most moved so far".
PB_MIN_PRIOR_SESSIONS = 3


def _milestone(facts, weight_series, volume_best_before: float, prior_sessions: int = 0) -> str | None:
    """The line this day crossed, if any — from the platform's own series, never typed.

    Order is deliberate: a weight line beats a volume best beats a calendar day, because
    that is how postable they are. One stripe per card; the others still happened.
    """
    n = facts.day_n or 0
    if facts.weighed_today and facts.total_lost_lb is not None and facts.baseline_weight_lb is not None:
        prior = [facts.baseline_weight_lb - v for v in (weight_series or [])[:-1] if v is not None]
        best_before = max(prior, default=0.0)
        for line in MILESTONE_LB:
            if facts.total_lost_lb >= line > best_before:
                return f"first {line} lb"
    if facts.workouts and prior_sessions >= PB_MIN_PRIOR_SESSIONS:
        vol = max((float(w.volume_lbs or 0) for w in facts.workouts), default=0.0)
        if vol > 0 and vol > volume_best_before:
            return "most moved so far"
    if n in MILESTONE_DAYS:
        return MILESTONE_DAYS[n]
    return None


def _recent_beats(days: list[str]) -> list[tuple[str, str]]:
    """[(date, beat)] from the recap rows already written — what the last cards WERE."""
    out = []
    for d in days:
        row = _existing(f"DATE#{d}")
        if row and row.get("beat") and row.get("outcome") in ("sent", "rendered"):
            out.append((d, str(row["beat"])))
    return out


def _last_weigh_label(weight_series, date: str) -> str | None:
    """`Day 10` — the last day of the cycle with a weigh-in, from the series itself."""
    idx = [i for i, v in enumerate(weight_series or []) if v is not None]
    if not idx:
        return None
    return f"Day {idx[-1] + 1}"


def _weekdays(dates: list[str]) -> list[str]:
    from common.pacific_time import parse_day_key

    out = []
    for d in dates:
        p = parse_day_key(d)
        out.append(p.strftime("%a")[:2] if p else "")
    return out


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

    from web import recap_canvas, recap_layouts, recap_qa

    sk = f"DATE#{date}"

    # #3942: `dry_run` gates EVERY write, not only delivery. Before this, a "dry run" meant to
    # inspect a card republished three live `recap/` objects and moved the row's `rendered_at`
    # — a dry run is the thing you reach for BECAUSE you believe it cannot mutate. Under
    # dry_run nothing is put to S3 and no row is written; the returned record carries the
    # would-be keys marked `storage: "dry_run"` and the rendered bytes (base64) so the run is
    # still useful for inspection.
    def _rec(row_sk: str, payload: dict[str, Any]) -> None:
        if dry_run:
            return
        _record(row_sk, payload)

    def _store(key: str, body: bytes) -> None:
        if dry_run:
            return
        _s3.put_object(Bucket=S3_BUCKET, Key=key, Body=body, ContentType="image/png")

    if not force:
        prior = _existing(sk)
        if prior and (prior.get("delivered") or {}).get("telegram") in ("ok", "dry_run"):
            logger.info("recap for %s already delivered; skipping (pass force to re-send)", date)
            return {"status": "already_delivered", "date": date}

    facts = recap_data.day_facts(_table, date, experiment_start=EXPERIMENT_START_DATE)
    trailing = recap_data.trailing(_table, date, days=7, experiment_start=EXPERIMENT_START_DATE)
    weight_series, grade_series = recap_data.cycle_series(_table, EXPERIMENT_START_DATE, date)
    if not facts.weighed_today:
        facts.last_weigh_label = _last_weigh_label(weight_series[:-1], date)
    try:
        volume_best_before, prior_sessions = recap_data.cycle_volume_max(_table, EXPERIMENT_START_DATE, date)
    except Exception:  # noqa: BLE001
        volume_best_before, prior_sessions = 0.0, 0
    facts.milestone = _milestone(facts, weight_series, volume_best_before, prior_sessions)
    recent = _recent_beats([d.date for d in trailing if d.date != date][-3:])

    # The BEAT, not the biggest number. See recap_layouts.pick_beat.
    day0 = date == _genesis_eve()
    if day0:
        # The starting line. The eve's own numbers belong to the previous cycle and are
        # not drawn; the card is the baseline, the goal and what gets graded.
        facts.day_n = 0
        layout, why = "dayzero", "the eve of genesis — the starting line"
        # The eve's names are the PREVIOUS cycle's — its workouts, its missed habits, its
        # streaks — and the starting-line card draws none of them. They are cleared here
        # so the gate screens what the card says, not what the eve happened to hold: the
        # first render was held on a cycle-16 habit row the card never printed.
        facts.workouts, facts.missed_tier0, facts.vice_streaks, facts.journal_templates = [], [], {}, []
    else:
        layout, why = recap_layouts.pick_beat(facts, trailing, recent_beats=recent)
    day_label = f"Day {facts.day_n}" if facts.day_n is not None else ""
    base_extra = {"milestone": facts.milestone, "weighed_today": facts.weighed_today, "recent_beats": [b for _d, b in recent]}

    # The coach line is selected AFTER the beat and set onto the facts, because which
    # coach speaks depends on what the day's story turned out to be — a session card
    # wants the physical coach, a graded day wants the mind coach. `day_facts()` stays
    # unaware of beats on purpose; it assembles a day, it does not narrate one (#3749).
    if day0:
        facts.coach_line, facts.coach_line_source, coach_line_status = None, None, "skipped"
    else:
        facts.coach_line, facts.coach_line_source, coach_line_status = recap_data.coach_line(_table, date, layout)
        if facts.coach_line_source:
            # "COACH#physical_coach|OUTPUT#…" → "physical coach": the quote is attributed.
            facts.coach_label = facts.coach_line_source.split("|", 1)[0].removeprefix("COACH#").replace("_", " ")

    base: dict[str, Any] = {
        "date": date,
        "day_n": facts.day_n,
        "beat": layout,
        "beat_reason": why,
        "grade": facts.grade_letter,
        "absent_sources": facts.absent,
        "algo_version": recap_layouts.__name__ + "@3",
        # The OUTPUT# record the quote came from, so any line on any card is traceable to
        # the coach run that wrote it. None when the day had no reader-safe coach line —
        # recorded either way, because "no line" is a fact about the day worth keeping.
        "coach_line_source": facts.coach_line_source,
        # `ok` | `absent` | `unreadable`. Three outcomes that look identical on the card
        # and must not look identical here — see recap_data.coach_line (#3749/#3768).
        "coach_line_status": coach_line_status,
        "rendered_at": pacific_now().isoformat(),
        "dry_run": dry_run,
        # #3942: a would-be key and a written key must not read the same.
        "storage": "dry_run" if dry_run else "written",
        **base_extra,
    }

    if day0:
        caption = recap_layouts.dayzero_caption(facts)
        detail_plan: list = []
    else:
        caption = recap_layouts.caption_for_beat(layout, facts, day_label=day_label, date_label=_date_label(date))
        detail_plan = recap_layouts.detail_plan(facts, weight_series, grade_series)
    detail_caption = recap_layouts.detail_caption(facts, day_label=day_label) if len(detail_plan) >= recap_layouts.DETAIL_MIN_BANDS else ""
    base["detail_plan"] = [f"{b}:{n}" if n else b for b, n in detail_plan]

    # GATE BEFORE RENDER. A blocked term costs CPU, never a public frame. BOTH captions go
    # through the one call — the second card never gets its own, weaker, verdict.
    verdict = recap_gate.gate(
        recap_layouts.gate_strings(facts, caption, extra=(detail_caption,)),
        items=facts.item_labels(),
        free_text=facts.free_text(),
    )
    if not verdict.may_send:
        _rec(sk, {**base, "outcome": "held", "privacy": verdict.to_dict()})
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
            _rec(sk, {**base, "outcome": "no_signal", "error": f"{type(e2).__name__}: {e2}"})
            return {**base, "outcome": "no_signal"}

    # QA AFTER RENDER, BEFORE STORE. The frame is judged, not the inputs.
    qa1 = recap_qa.audit_image(img, margin=recap_layouts.M)
    base["qa"] = qa1.to_dict()
    if not qa1.may_store:
        _rec(sk, {**base, "outcome": "held_qa", "privacy": verdict.to_dict()})
        logger.warning("recap for %s held by render QA: %s", date, qa1.hard[:3])
        return {**base, "outcome": "held_qa"}

    png = recap_canvas.to_png_bytes(img)
    key = f"{RECAP_PREFIX}{date}.png"
    try:
        # No CacheControl and no CloudFront invalidation: this object is NOT served. There
        # is no /recap/* behaviour on the distribution, deliberately — the card is private
        # until he posts it (ADR-140 rule 5, human selection only).
        _store(key, png)
    except Exception as e:  # noqa: BLE001
        logger.error("recap put_object failed for %s: %s: %s", key, type(e).__name__, e)

    # Card 2 of 2: the detail. Same gate verdict, its own PNG, its own caption.
    detail_key = None
    detail_png = b""
    if detail_caption:
        try:
            dimg = recap_layouts.detail(facts, date_label=_date_label(date), weight_series=weight_series, grade_series=grade_series)
            qa2 = recap_qa.audit_image(dimg, margin=recap_layouts.M)
            base["qa_detail"] = qa2.to_dict()
            if not qa2.may_store:
                # Card 2 is held on its own; card 1 still ships. A second card that cannot be
                # drawn cleanly is a day with one card, and the row says why.
                raise RuntimeError(f"render QA held the detail card: {qa2.hard[:3]}")
            detail_png = recap_canvas.to_png_bytes(dimg)
            detail_key = f"{RECAP_PREFIX}{date}-detail.png"
            _store(detail_key, detail_png)
        except Exception as e:  # noqa: BLE001
            logger.warning("detail card could not render for %s: %s: %s", date, type(e).__name__, e)
            base["detail_error"] = f"{type(e).__name__}: {e}"
            detail_key = None
            detail_png = b""

    # The weekly card is derived from the daily run, not a second cron.
    weekly_key = None
    day_n = pacific_day_n(EXPERIMENT_START_DATE, date)
    if day_n and week_close_day(date, EXPERIMENT_START_DATE) == date:
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
                weekdays=_weekdays(recap_data._day_range(wk_start, date)),
            )
            qa3 = recap_qa.audit_image(wimg, margin=recap_layouts.M)
            if not qa3.may_store:
                raise RuntimeError(f"render QA held the weekly card: {qa3.hard[:3]}")
            weekly_key = f"{RECAP_PREFIX}week-{week_n:02d}.png"
            weekly_png = recap_canvas.to_png_bytes(wimg)
            _store(weekly_key, weekly_png)
            base["weekly"] = {"week": week_n, "s3_key": weekly_key, "totals": totals, "storage": base["storage"]}
            if dry_run:
                base["weekly"]["png_base64"] = base64.b64encode(weekly_png).decode("ascii")
        except Exception as e:  # noqa: BLE001
            logger.error("weekly card failed for %s: %s: %s", date, type(e).__name__, e)
            base["weekly"] = {"error": f"{type(e).__name__}: {e}"}

    delivered: dict[str, str] = {}
    delivered_detail: dict[str, str] = {}
    if deliver:
        ses = boto3.client("ses", region_name=os.environ.get("AWS_REGION", "us-west-2"))
        delivered = recap_deliver.deliver(
            png,
            caption,
            dry_run=dry_run,
            telegram_secret_getter=_telegram_secret,
            telegram_bot_key=TELEGRAM_BOT_KEY,
            ses_client=ses,
            sender=EMAIL_SENDER,
            recipient=EMAIL_RECIPIENT,
            subject=f"{day_label or date} — your card (1 of 2)" if detail_png else f"{day_label or date} — your card",
            filename=f"recap-{date}.png",
        )
        if detail_png:
            # The same fan-out, a second time: two photos on the phone, two attachments in
            # the inbox, in the order he posts them.
            delivered_detail = recap_deliver.deliver(
                detail_png,
                detail_caption,
                dry_run=dry_run,
                telegram_secret_getter=_telegram_secret,
                telegram_bot_key=TELEGRAM_BOT_KEY,
                ses_client=ses,
                sender=EMAIL_SENDER,
                recipient=EMAIL_RECIPIENT,
                subject=f"{day_label or date} — the detail (2 of 2)",
                filename=f"recap-{date}-detail.png",
            )

    record = {
        **base,
        "outcome": "sent" if deliver else "rendered",
        "s3_key": key,
        "detail_s3_key": detail_key,
        "privacy": verdict.to_dict(),
        "delivered": delivered,
        "delivered_detail": delivered_detail,
        "caption": caption,
        "detail_caption": detail_caption or None,
    }
    if dry_run:
        # The bytes ride in the result so a dry run is still an inspection, not a no-op.
        record["png_base64"] = base64.b64encode(png).decode("ascii")
        if detail_png:
            record["detail_png_base64"] = base64.b64encode(detail_png).decode("ascii")
    _rec(sk, record)
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
