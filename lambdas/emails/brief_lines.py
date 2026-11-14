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
