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
