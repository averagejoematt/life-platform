"""#4641: the runs/day figure reproduces from cdk/stacks + the registry by one command."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import ingestion_runs_per_day as rpd  # noqa: E402

CUTS = {
    "notion-journal-ingestion": 3,
    "youtube-social-ingestion": 2,
    "bluesky-social-ingestion": 2,
    "mastodon-social-ingestion": 2,
    "dropbox-poll": 12,
    "withings-data-ingestion": 4,
    "eightsleep-data-ingestion": 4,
}


def test_cut_sources_run_at_the_new_cadence():
    rows = {r["function"]: r for r in rpd.table()}
    assert {k: rows[k]["own"] for k in CUTS} == CUTS


def test_site_stats_refresh_invocations_are_counted():
    rows = {r["function"]: r for r in rpd.table()}
    for fn in ("whoop-data-ingestion", "withings-data-ingestion", "habitify-data-ingestion"):
        assert rows[fn]["via_site_stats_refresh"] == 4
    assert rows["withings-data-ingestion"]["total"] == 8


def test_expression_parser():
    assert rpd.runs_per_day_expr("rate(30 minutes)") == 48
    assert rpd.runs_per_day_expr("rate(2 hours)") == 12
    assert rpd.runs_per_day_expr("cron(5 * * * ? *)") == 24
    assert rpd.runs_per_day_expr("cron(0 14,2 * * ? *)") == 2
