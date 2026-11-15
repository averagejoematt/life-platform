"""brief_lines.py — fail-soft one-line readouts for the daily brief, extracted from daily_brief_lambda (#5056).

Each returns the line, or None — a failure here must never block the brief."""

from __future__ import annotations


def budget_headroom(logger):
    """#822: the one-line budget headroom readout (the cost governor's persisted projection breakdown)."""
    try:
        from ai import budget_guard

        return budget_guard.format_headroom_line(budget_guard.read_breakdown()) or None
    except Exception as err:
        logger.warning("budget headroom line failed (non-fatal): " + str(err))
        return None


def steps_line(table, date, logger):
    """#5056: the day's steps floor/target line (owner-only)."""
    try:
        from emails import steps_nudge_runner

        return steps_nudge_runner.brief_line(table, date)
    except Exception as err:
        logger.warning("steps line failed (non-fatal): " + str(err))
        return None


def rhythm_lines(table, date, logger):
    """#4972: the owner-only heart-rhythm section (health.rhythm_owner) — data lines, n and window on every count.
    `date` is the brief's DATA day (yesterday), so the window never holds a partial day; a failed read is one
    "could not be read" line (rhythm_owner.brief_section). Only an import failure here returns None.

    The email goes to the owner alone; the lines reach `html_builder.build_html` and nothing else (never `data`,
    an AI prompt, a generated file or a log line — tests/test_rhythm_owner_4972.py). None = render nothing."""
    try:
        from health import rhythm_owner

        return rhythm_owner.brief_section(table, date) or None
    except Exception as err:
        logger.warning("rhythm lines failed (non-fatal): " + type(err).__name__)
        return None


# ── #5821: the owner's folded emails ─────────────────────────────────────────────────────────────────────────────
# Owner ruling 2026-11-15: only the Morning Brief and the Evening nudge arrive as their own emails. "Protein this
# morning", "Nutrition Review" and "Habits to settle" stopped sending and became these compact sections. Each is
# deterministic (no model call — it renders at every budget tier, ADR-125), read-only (a dry-run brief writes
# nothing), and fail-soft on its own: a section with no data, or whose read fails, is omitted and the brief still
# sends. Owner-only: the sections reach `html_builder.build_html` and nothing else (never `data`, a prompt, a
# generated file or a log line), and a demo brief omits them.


def _protein_section(table, now_pt, user):
    """The breakfast protein note — computed here, because the coach-nudge pass's first in-window tick (10:10 PT) runs
    after the 10:00 brief."""
    from emails import protein_nudge_runner

    text = protein_nudge_runner.brief_line(table, now_pt, user)
    return {"key": "protein", "title": "Protein this morning", "lines": [text]} if text else None


def _nutrition_review_section(table, now_pt, user):
    """The weekly nutrition review, read off its stored summary row, the morning AFTER it ran.

    nutrition-review fires Saturday 10:00 PT — the brief's own minute — so the Saturday brief cannot count on the row
    existing. Rendering only when the row's `generated_at` (Pacific) is the day before the brief's day is stateless,
    never races, and never shows one review twice. Rows from before #5821 carry no `brief_headline`; their averages
    make the line (an absent average says so, never 0 — ADR-104)."""
    from datetime import timedelta

    from common.digest_utils import d2f
    from common.pacific_time import PACIFIC, parse_iso_utc
    from experiment.phase_filter import with_phase_filter

    q = {
        "KeyConditionExpression": "pk = :pk",
        "ExpressionAttributeValues": {":pk": f"USER#{user}#SOURCE#nutrition_review"},
        "ScanIndexForward": False,
        "Limit": 1,
    }
    items = table.query(**with_phase_filter(q)).get("Items") or []
    if not items:
        return None
    row = d2f(items[0])
    generated = parse_iso_utc(row.get("generated_at"))
    if generated is None or generated.astimezone(PACIFIC).date() != now_pt.date() - timedelta(days=1):
        return None
    headline = row.get("brief_headline")
    if not headline:
        cal, pro = row.get("avg_calories"), row.get("avg_protein_g")
        cal_part = f"{int(cal)} kcal" if cal is not None else "calories not logged"
        pro_part = f"{int(pro)}g protein" if pro is not None else "protein not logged"
        headline = f"Week ending {row.get('date')} - {cal_part} - {pro_part} (daily averages)"
    lines = [headline] + ([row["brief_excerpt"]] if row.get("brief_excerpt") else [])
    return {"key": "nutrition_review", "title": "Nutrition review", "lines": lines}


def _habits_section(table, now_pt, user):
    """The Saturday skipped-habits queue (habit names: owner-only, this email body alone)."""
    from emails import habit_skip_review_lambda

    return habit_skip_review_lambda.brief_section(table, now_pt.date().isoformat(), user)


FOLDED_SECTIONS = (_protein_section, _nutrition_review_section, _habits_section)


def folded_sections(table, now_pt, logger, user="matthew"):
    """#5821: [{key, title, lines}] for each folded email that has something to say this morning; [] when none."""
    out = []
    for build in FOLDED_SECTIONS:
        try:
            section = build(table, now_pt, user)
        except Exception as err:
            logger.warning("folded section " + build.__name__ + " failed (non-fatal): " + type(err).__name__)
            continue
        if section and section.get("lines"):
            out.append(section)
    return out
