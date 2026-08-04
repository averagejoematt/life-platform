"""tests/test_restart_media_podcast_1243.py — #1243: the reset pipeline must
re-anchor a kept prologue's read-aloud episode, not just the article.

Root cause (measured live 2026-08-03, see the PR body): restart_media_reset.py
resets/resurrects generated/panelcast/* and generated/podcast/debrief/* —
but chronicle_podcast_lambda.py owns a THIRD, separate podcast surface,
generated/podcast/episodes.json (the per-article "listen" feed, #1121), which
neither restart_media_reset.py nor any other reset sub-script ever touched.
Its own standing cron was independently retired 2026-07-02 ("SEASON-1 ZOMBIE
RETIRED", manual-invoke only since), so nothing regenerates that feed across a
genesis move — a kept prologue's audio silently keeps narrating its pre-reset
publish date forever (the exact #1243 evidence).

The fix wires chronicle-podcast into restart_site_copy_sync.py's existing
REGEN_LAMBDAS regen-invocation step (the same mechanism already used for
daily-brief/character-sheet-compute/site-stats-refresh/og-image-generator),
placed so it runs AFTER restart_leadin_pages has already rewritten
generated/journal/posts.json with the re-anchored dates — this test pins the
ordering assumption directly from build_sub_scripts, not by inspection.
"""

import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "deploy"))

import restart_pipeline as rp  # noqa: E402
import restart_site_copy_sync as rscs  # noqa: E402


def test_chronicle_podcast_is_a_regen_lambda():
    names = [fn for fn, _payload in rscs.REGEN_LAMBDAS]
    assert "chronicle-podcast" in names


def test_chronicle_podcast_payload_is_a_bare_invoke():
    """No dry_run/force flag needed: the lambda is idempotent by date-key
    (#1121) — a bare {} only renders episodes that don't already exist."""
    payload = dict(rscs.REGEN_LAMBDAS)["chronicle-podcast"]
    assert payload == {}


def test_leadin_pages_runs_before_site_copy_sync_in_the_pipeline():
    """The ordering this fix depends on: generated/journal/posts.json must
    already carry the re-anchored dates by the time REGEN_LAMBDAS fires."""
    sub_scripts = rp.build_sub_scripts(skip_chronicle=True, keep_chronicle=[], old_genesis="2026-01-01")
    names = [name for name, _cmd in sub_scripts]
    assert names.index("restart_leadin_pages") < names.index("restart_site_copy_sync")
