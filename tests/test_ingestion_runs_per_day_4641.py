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


def test_facet_claim_parser():
    c = rpd.claimed_runs_per_day
    assert c("OAuth API pull, 4x daily") == 4
    assert c("API pull, hourly (24h)") == 24
    assert c("OAuth API pull, hourly, 18 hours a day") == 18
    assert c("Dropbox API poll every 2 hours (MacroFactor CSV transport)") == 12
    assert c("Manual entry via MCP") is None


def test_live_tree_has_no_mismatch():
    assert rpd.mismatches(rpd.table()) == []
    assert rpd.main() == 0


def test_wrong_facet_is_a_mismatch_and_exits_nonzero(monkeypatch):
    """Mutation control: a facet that disagrees with the schedule is printed and fails the command."""
    real = rpd.registry_facets()
    src, _ = real["dropbox-poll"]
    monkeypatch.setattr(rpd, "registry_facets", lambda: {**real, "dropbox-poll": (src, "Dropbox API poll every 30 minutes")})
    bad = rpd.mismatches(rpd.table())
    assert len(bad) == 1 and "dropbox-poll" in bad[0] and "48/day" in bad[0]
    assert rpd.main() == 1


def test_broken_join_loses_the_comparison(monkeypatch):
    """The join is load-bearing: with it empty every source is unchecked, so assert the live join
    really covers the cadence-bearing sources (a silently empty join would pass a mismatch gate)."""
    rows = {r["function"]: r for r in rpd.table()}
    checked = [fn for fn, r in rows.items() if r["claimed"] is not None]
    assert len(checked) >= 13, checked
    for fn in ("dropbox-poll", "notion-journal-ingestion", "withings-data-ingestion"):
        assert fn in checked
