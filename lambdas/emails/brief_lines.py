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
# Owner rulings 2026-11-15: the Morning Brief, the Evening nudge and the weekly Nutrition Review arrive as their own
# emails. "Protein this morning", "Habits to settle", "A note from <coach>" and the lifting-day "Steps today" note stopped
# sending and became these compact sections. Each is rendered with NO model call (the coach note's copy was phrased and
# gated by coach-nudge when it was produced; the brief only reads it), so it renders at every budget tier (ADR-125). Each
# is read-only (a dry-run brief writes nothing) and fail-soft on its own: a section with no data, or whose read fails,
# is omitted and the brief still sends. Owner-only: the sections reach `html_builder.build_html` and nothing else
# (never `data`, a prompt, a generated file or a log line), and a demo brief omits them.

FOLDED = "folded_into_brief"  # the ledger status of a note the Morning Brief carries instead of an email


def _protein_section(table, now_pt, user):
    """The breakfast protein note — computed here, because the coach-nudge pass's first in-window tick (10:10 PT) runs
    after the 10:00 brief."""
    from emails import protein_nudge_runner

    text = protein_nudge_runner.brief_line(table, now_pt, user)
    return {"key": "protein", "title": "Protein this morning", "lines": [text]} if text else None


def _coach_note_section(table, now_pt, user):
    """The coach's note(s) folded since the previous brief: ledger rows settled FOLDED whose `sent_at` falls in the 24 h
    before this brief. The note is phrased by Haiku and gated when coach-nudge produces it (08:10-18:10 PT ticks), so
    most land after that day's brief; the window shows each one exactly once, on the next brief. Copy and coach name
    ride the ledger row — one query, no model call here."""
    from datetime import timedelta

    from coach import coach_nudge_engine as engine
    from common.pacific_time import parse_iso_utc

    today = now_pt.date()
    lo, hi = engine.ledger_sk((today - timedelta(days=1)).isoformat()), engine.ledger_sk(today.isoformat())
    rows = (
        table.query(
            KeyConditionExpression="pk = :pk AND sk BETWEEN :s AND :e",
            ExpressionAttributeValues={":pk": engine.LEDGER_PK, ":s": lo, ":e": hi},
        ).get("Items")
        or []
    )
    lines = []
    for row in rows:
        at = parse_iso_utc(row.get("sent_at"))
        if row.get("status") != FOLDED or not row.get("brief_text") or at is None or not now_pt - timedelta(hours=24) <= at < now_pt:
            continue
        lines.append(str(row.get("coach_name") or "Your coach") + ": " + str(row["brief_text"]))
    return {"key": "coach_note", "title": "A note from your coach", "lines": lines} if lines else None


def _steps_note_section(table, now_pt, user):
    """Last evening's lifting-day steps note (its 19:00-20:00 PT window runs after that day's brief), read from the
    ledger row the steps pass settled FOLDED."""
    from datetime import timedelta

    from emails import steps_nudge_runner

    text = steps_nudge_runner.folded_note(table, (now_pt.date() - timedelta(days=1)).isoformat(), FOLDED)
    return {"key": "steps_note", "title": "Steps, last evening", "lines": [text]} if text else None


def _habits_section(table, now_pt, user):
    """The Saturday skipped-habits queue (habit names: owner-only, this email body alone)."""
    from emails import habit_skip_review_lambda

    return habit_skip_review_lambda.brief_section(table, now_pt.date().isoformat(), user)


FOLDED_SECTIONS = (_coach_note_section, _protein_section, _steps_note_section, _habits_section)


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
