"""Pre-launch content calendar (2026-07-11) — the reset re-dates a whole
declared pre-launch arc (chronicle prequels + podcast prequel) to genesis −
days_before offsets.

Pins:
  - PRELAUNCH_CALENDAR offset arithmetic (resolve_calendar) for a FIXED genesis
    (never wall-clock — the golden-tests-wallclock lesson);
  - the pointer-record repair (restart_leadin_repair) produces well-formed
    content_html/content_markdown and a fully vetted body;
  - the media resurrect builds the episodes.json entry schema the panel lambda
    writes (week/title/date/url/bytes/duration_sec/byline/excerpt/transcript_url);
  - restart_pipeline step ordering: chronicle handler → media reset → leadin pages;
  - restart_leadin_pages seq/label logic matches wednesday_chronicle_lambda._seq_for
    (post-#1090: 1 calendar lead-in + the genesis−1 pre-registration chapter →
    week-01/02, the next real publish continues at week-03);
  - the #1090 editorial curation: the retired lead-ins are OUT of the calendar,
    and curate_prelaunch_leadins retires exactly the uncurated pre-genesis
    records on the live table (never the prereg chapter, never post-genesis).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

GENESIS = "2026-07-12"  # pinned — cycle-5 genesis; tests must never read wall-clock


def _load(name: str):
    """Load a deploy/ script as a module (they self-manage sys.path at import)."""
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / "deploy" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod  # registered first so cross-imports share the instance
    spec.loader.exec_module(mod)
    return mod


handler = _load("restart_chronicle_handler")
media = _load("restart_media_reset")
repair = _load("restart_leadin_repair")
pipeline = _load("restart_pipeline")
leadin = _load("restart_leadin_pages")
curate = _load("curate_prelaunch_leadins")


# ── 1. Calendar offsets → dates ───────────────────────────────────────────────


def test_resolve_calendar_offset_arithmetic_synthetic():
    cal = [
        {"kind": "chronicle", "sk": "DATE#X", "days_before": 6},
        {"kind": "podcast", "asset": "wk0", "days_before": 2},
    ]
    out = handler.resolve_calendar("2026-07-12", cal)
    assert [e["date"] for e in out] == ["2026-07-06", "2026-07-10"]
    # month-boundary arithmetic
    assert handler.resolve_calendar("2026-08-03", cal)[0]["date"] == "2026-07-28"
    # pure function: input calendar not mutated
    assert "date" not in cal[0]


def test_real_calendar_shape_and_invariants():
    out = handler.resolve_calendar(GENESIS)
    assert len(out) >= 2, "the arc needs at least a chronicle + a podcast prequel"
    kinds = {e["kind"] for e in out}
    assert kinds <= {"chronicle", "podcast"}
    for e in out:
        assert e["days_before"] >= 1, "every prequel must be dated BEFORE genesis"
        assert e["date"] < GENESIS
        if e["kind"] == "chronicle":
            assert e["sk"].startswith("DATE#")
        else:
            assert e["asset"]
            assert e.get("title")
    # the declared arc plays in calendar order: dates strictly ascending
    dates = [e["date"] for e in out]
    assert dates == sorted(dates) and len(set(dates)) == len(dates)


def test_origin_leadins_backcompat_alias():
    assert handler.ORIGIN_LEAD_INS == [e["sk"] for e in handler.PRELAUNCH_CALENDAR if e["kind"] == "chronicle"]


# ── 2. Pointer-record repair ─────────────────────────────────────────────────


def _fixture_page() -> str:
    """A synthetic archived article page embedding every vet-target string
    (taken from the live registry so the fixture can't drift from the edits)."""
    edits = repair.REPAIRS["DATE#2026-02-28"]["vet_edits"]
    paragraphs = "\n\n".join(f"<p>{old}</p>" for _, old, _ in edits)
    return f"""<html><body>
<article class="post-body">
  <div class="prose">
    <p>The first thing you notice is the charging cables.</p>
{paragraphs}
<hr>
<p>All of this arrives each morning as <em>one email</em> with a <strong>day grade</strong>.</p>
<p class="signature"><em>Prologue — The Measured Life</em></p>
  </div>
</article>
<div class="prose">trailing duplicated shell — must NOT be extracted</div>
</body></html>"""


def test_pointer_record_detection():
    assert repair.is_pointer_record({"content_markdown": "See S3: blog/week-00.html", "content_html": "See S3: blog/week-00.html"})
    assert repair.is_pointer_record({"content_markdown": "", "content_html": ""})
    real = {"content_markdown": "x" * 500, "content_html": "y" * 500}
    assert not repair.is_pointer_record(real)


def test_repair_produces_wellformed_vetted_content():
    body = repair.extract_prose_body(_fixture_page())
    assert "trailing duplicated shell" not in body
    vetted, applied = repair.apply_vet_edits(body, repair.REPAIRS["DATE#2026-02-28"]["vet_edits"])
    assert len(applied) == len(repair.REPAIRS["DATE#2026-02-28"]["vet_edits"])
    repair.assert_vetted(vetted)  # no real names, no named vices, no months/seasons
    html, md, wc = repair.build_content_fields(repair.REPAIRS["DATE#2026-02-28"], vetted)
    # content_html shape matches the DATE#2026-02-22 record: h1 + byline + hr + prose
    assert html.startswith('<h1>The Measured Life — Prologue: "Before the Numbers"</h1>')
    assert '<p class="byline"><em>By Elena Voss | Seattle, WA</em></p>' in html
    # content_markdown shape: '# h1' + '*byline*' + '---' + prose
    assert md.startswith('# The Measured Life — Prologue: "Before the Numbers"')
    assert "*By Elena Voss | Seattle, WA*" in md
    assert "\n---\n" in md
    assert "*one email*" in md and "**day grade**" in md  # inline em/strong conversion
    assert "*Prologue — The Measured Life*" in md  # signature preserved as emphasis
    assert wc > 50
    # the fictional Board roster replaced the real public figures
    assert "Dr. Reyes" in md and "Attia" not in md
    # the leadin-pages renderer must strip the header it renders its own chrome for
    stripped = leadin.body_html_from_record({"content_html": html})
    assert not stripped.startswith("<h1>") and "byline" not in stripped[:100]


def test_vet_edit_must_match_exactly_once():
    with pytest.raises(RuntimeError, match="expected exactly 1"):
        repair.apply_vet_edits("<p>totally different body</p>", repair.REPAIRS["DATE#2026-02-28"]["vet_edits"])


def test_assert_vetted_catches_forbidden_tokens():
    for bad in ("a Tuesday in February", "modeled on Attia", "tracks alcohol intake"):
        with pytest.raises(RuntimeError, match="forbidden token"):
            repair.assert_vetted(f"<p>{bad}</p>")


def test_stats_line_is_date_agnostic():
    for r in repair.REPAIRS.values():
        repair.assert_vetted(r["stats_line"])  # e.g. no 'February 2026'


# ── 3. Podcast prequel resurrection ──────────────────────────────────────────


def test_prequel_episode_entry_schema_and_date():
    entry = next(e for e in handler.resolve_calendar(GENESIS) if e["kind"] == "podcast")
    wav_bytes = media.GEMINI_SAMPLE_RATE * 2 * 60 + 44  # exactly 60s of 16-bit mono PCM
    ep = media.build_prequel_episode(entry, wav_bytes)
    # schema EXACTLY matches the wk0 intro publisher in coach_panel_podcast_lambda
    assert set(ep) == {"week", "title", "date", "url", "bytes", "duration_sec", "byline", "excerpt", "transcript_url"}
    assert ep["week"] == 0
    assert ep["url"] == "/panelcast/wk0.wav"
    assert ep["transcript_url"] == "/panelcast/wk0.transcript.json"
    assert ep["duration_sec"] == 60
    assert ep["bytes"] == wav_bytes
    assert ep["date"] == entry["date"] and ep["date"] < GENESIS
    assert ep["title"] == entry["title"]


def test_prequel_prefers_compressed_mp3_when_archived():
    # #1018: episodes publish compressed; when the archive holds the .mp3, the
    # resurrect serves IT (never re-points readers at a 16 MB WAV) while the
    # duration still comes exactly from the WAV archived alongside.
    wav_bytes = media.GEMINI_SAMPLE_RATE * 2 * 60 + 44  # exactly 60s of PCM
    ep = media.build_prequel_episode({"asset": "wk0", "date": "2026-07-10", "title": "Prologue"}, wav_bytes=wav_bytes, mp3_bytes=600_000)
    assert ep["url"] == "/panelcast/wk0.mp3"
    assert ep["bytes"] == 600_000
    assert ep["duration_sec"] == 60  # lossless source, not a bitrate estimate
    assert 'type="audio/mpeg"' in media._panel_feed_with_items([ep])


def test_prequel_mp3_only_archive_estimates_duration():
    # a post-#1018 reset can archive an mp3 with no wav sibling (fail-open never
    # fired) -- the entry is still written, duration estimated at MP3_EST_KBPS
    sixty_sec_bytes = media.MP3_EST_KBPS * 1000 // 8 * 60
    ep = media.build_prequel_episode({"asset": "wk0", "date": "2026-07-10", "title": "Prologue"}, mp3_bytes=sixty_sec_bytes)
    assert ep["url"] == "/panelcast/wk0.mp3"
    assert ep["duration_sec"] == 60


def test_prequel_feed_carries_the_item():
    ep = media.build_prequel_episode({"asset": "wk0", "date": "2026-07-10", "title": "Prologue"}, 48044)
    feed = media._panel_feed_with_items([ep])
    assert "measured-life-panel-wk0" in feed
    assert 'type="audio/wav"' in feed
    assert "<itunes:episode>0</itunes:episode>" in feed
    assert feed.count("</channel>") == 1 and feed.strip().endswith("</rss>")
    # empty list degrades to the empty channel
    assert "measured-life-panel" not in media._panel_feed_with_items([])


def test_skip_reason_entries_are_not_resurrected():
    calls = []

    class _S3Stub:  # any S3 touch for a skipped entry is a bug
        def __getattr__(self, name):
            calls.append(name)
            raise AssertionError(f"S3 must not be touched for a skipped entry (called {name})")

    original = handler.PRELAUNCH_CALENDAR
    handler.PRELAUNCH_CALENDAR = [{"kind": "podcast", "asset": "wk0", "days_before": 2, "title": "T", "skip_reason": "vet failed"}]
    try:
        lines = media.resurrect_podcast_prequels(_S3Stub(), apply=False, now_iso="now", manual=[])
    finally:
        handler.PRELAUNCH_CALENDAR = original
    assert any("SKIP" in ln and "vet failed" in ln for ln in lines)
    assert not calls


# ── 4. Pipeline step ordering ─────────────────────────────────────────────────


def test_pipeline_orders_chronicle_then_media_then_leadin_pages():
    steps = [name for name, _ in pipeline.build_sub_scripts(False, [], "2026-06-08")]
    assert steps.index("restart_chronicle_handler") < steps.index("restart_media_reset") < steps.index("restart_leadin_pages")
    # the pages step must precede the rendered-surface work that follows the wipe
    assert steps.index("restart_leadin_pages") < steps.index("restart_site_copy_sync")
    assert steps.index("restart_leadin_pages") < steps.index("restart_docs_update")


def test_pipeline_leadin_pages_runs_even_when_chronicle_skipped():
    steps = dict(pipeline.build_sub_scripts(True, [], "2026-06-08"))
    assert "restart_chronicle_handler" not in steps
    assert steps["restart_leadin_pages"] == ["python3", "deploy/restart_leadin_pages.py", "--apply"]
    names = [name for name, _ in pipeline.build_sub_scripts(True, [], "2026-06-08")]
    assert names.index("restart_media_reset") < names.index("restart_leadin_pages")


def test_pipeline_keep_chronicle_passes_resurrect_override():
    steps = dict(pipeline.build_sub_scripts(False, ["DATE#2026-02-28"], "2026-06-08"))
    assert steps["restart_chronicle_handler"][-2:] == ["--resurrect-sk", "DATE#2026-02-28"]


def test_pipeline_passes_closing_cycle_to_ledger_reset():
    """#951: the SSM cycle bump fires right after the wipe (before the ledger reset),
    so the ledger reset must receive the CLOSING cycle explicitly - an SSM read
    inside it would stamp CYCLE_TOTALS# with the NEW cycle number (the off-by-one
    the 2026-07-11 reset wrote: cycle-4 closing totals archived as cycle=5)."""
    steps = dict(pipeline.build_sub_scripts(False, [], "2026-06-08", closing_cycle=4))
    assert steps["restart_ledger_reset"][-2:] == ["--closing-cycle", "4"]
    assert steps["restart_ledger_reset"][:3] == ["python3", "deploy/restart_ledger_reset.py", "--apply"]
    # legacy/standalone call shape (no cycle known) omits the flag
    steps_legacy = dict(pipeline.build_sub_scripts(False, [], "2026-06-08"))
    assert "--closing-cycle" not in steps_legacy["restart_ledger_reset"]


def test_run_step_strips_apply_in_dry_run(monkeypatch):
    seen = {}

    class _Proc:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        return _Proc()

    monkeypatch.setattr(pipeline.subprocess, "run", fake_run)
    pipeline.run_step("x", ["python3", "deploy/restart_leadin_pages.py", "--apply"], apply=False, log=[])
    assert "--apply" not in seen["cmd"]
    pipeline.run_step("x", ["python3", "deploy/restart_leadin_pages.py", "--apply"], apply=True, log=[])
    assert "--apply" in seen["cmd"]


# ── 5. Lead-in pages: seq/label parity with the next real publish ────────────


def test_leadin_seq_and_labels_continue_at_week_03(monkeypatch):
    monkeypatch.setattr(leadin, "EXPERIMENT_START_DATE", GENESIS)
    resolved = handler.resolve_calendar(GENESIS)
    pre_dates = [e["date"] for e in resolved if e["kind"] == "chronicle"]
    assert len(pre_dates) == 1, "#1090 curation: ONE calendar lead-in (Before the Numbers)"
    prereg_date = "2026-07-11"  # genesis − 1 — publish_genesis_preregistration.py's chapter
    first_publish = "2026-07-15"  # first post-genesis Wednesday
    all_dates = sorted(pre_dates + [prereg_date, first_publish])
    # the chronicle OPENS on the calendar lead-in, then the prereg chapter (#1090)…
    assert all_dates[0] == pre_dates[0]
    assert leadin.seq_for(pre_dates[0], all_dates, 0) == 1
    assert leadin.series_label(pre_dates[0], all_dates, 0) == "Prologue · Part I"
    assert leadin.seq_for(prereg_date, all_dates, 0) == 2
    assert leadin.series_label(prereg_date, all_dates, 0) == "Prologue · Part II"
    # …and the next real publish (wednesday_chronicle_lambda._seq_for uses the same
    # date-sorted index) continues at week-03, labelled Week 1.
    assert leadin.seq_for(first_publish, all_dates, 1) == 3
    assert leadin.series_label(first_publish, all_dates, 1) == "Week 1"


# ── 5b. #1090: the editorial curation of the pre-launch arc ──────────────────


def test_calendar_curation_1090_retired_the_two_entries():
    sks = [e["sk"] for e in handler.PRELAUNCH_CALENDAR if e["kind"] == "chronicle"]
    assert sks == ["DATE#2026-02-28"], "the chronicle opens with 'Before the Numbers' only"
    assert "DATE#2026-03-03" not in sks  # The Empty Journal — retired
    assert "DATE#2026-02-22" not in sks  # The Body Votes First — retired
    assert any("Before the Numbers" in e.get("label", "") for e in handler.PRELAUNCH_CALENDAR)


def test_retirement_plan_targets_only_uncurated_pre_genesis():
    visible = [
        {"sk": "DATE#2026-02-28", "date": "2026-07-06", "title": "Before the Numbers"},
        {"sk": "DATE#2026-03-03", "date": "2026-07-08", "title": "The Empty Journal"},
        {"sk": "DATE#2026-02-22", "date": "2026-07-09", "title": "The Body Votes First"},
        {"sk": "DATE#2026-07-11", "date": "2026-07-11", "title": "The Plan, On the Record", "pre_registration": True},
        {"sk": "DATE#2026-07-15", "date": "2026-07-15", "title": "Week 1"},
    ]
    plan = curate.retirement_plan(visible, GENESIS)
    assert [it["sk"] for it in plan] == ["DATE#2026-03-03", "DATE#2026-02-22"]


def test_retirement_plan_protects_prereg_by_sk_even_without_flag():
    visible = [{"sk": "DATE#2026-07-11", "date": "2026-07-11", "title": "The Plan, On the Record"}]
    assert curate.retirement_plan(visible, GENESIS) == []


def test_retirement_plan_never_touches_post_genesis():
    visible = [
        {"sk": "DATE#2026-07-12", "date": "2026-07-12", "title": "Day 1"},
        {"sk": "DATE#2026-07-16", "date": "2026-07-16", "title": "Week 1"},
    ]
    assert curate.retirement_plan(visible, GENESIS) == []


def test_retirement_plan_is_idempotent_after_curation():
    visible = [
        {"sk": "DATE#2026-02-28", "date": "2026-07-06", "title": "Before the Numbers"},
        {"sk": "DATE#2026-07-11", "date": "2026-07-11", "title": "The Plan, On the Record", "pre_registration": True},
    ]
    assert curate.retirement_plan(visible, GENESIS) == []


def test_build_retire_update_inverts_untombstone_and_redate():
    expr, names, values = curate.build_retire_update("DATE#2026-03-03", "NOW-ISO")
    assert values[":t"] is True and values[":ts"] == "NOW-ISO"
    assert values[":r"] == curate.TOMBSTONE_REASON
    assert values[":pilot"] == "pilot" and values[":h"] is True
    assert values[":d"] == "2026-03-03"  # date restored to the sk's original date
    assert names == {"#p": "phase", "#h": "hidden", "#d": "date"}
    assert "REMOVE redated_at, redated_from_sk" in expr


def test_orphan_week_pages_sweep_targets_only_stale_article_pages():
    keys = [
        "generated/journal/posts/week-01/index.html",
        "generated/journal/posts/week-02/index.html",
        "generated/journal/posts/week-03/index.html",
        "generated/journal/posts/week-04/index.html",
        "generated/journal/posts.json",  # the manifest is never swept
        "generated/journal/archive/pilot/posts/week-02/index.html",  # archived — different prefix, never listed/swept
    ]
    assert curate.orphan_week_pages(keys, 2) == [
        ("generated/journal/posts/week-03/index.html", 3),
        ("generated/journal/posts/week-04/index.html", 4),
    ]
    assert curate.orphan_week_pages(keys, 4) == []


# ── 6. #949: the pre-genesis dek is reframed on every rendered surface ────────
# The stored stats_line was authored mid-experiment ("… | Week 1 of The Measured
# Life") — rendered under the countdown banner it contradicted "begins tomorrow".
# display_stats_line reframes the RENDERED dek only (DDB untouched), and the
# Wednesday publish's manifest rebuild must derive the identical dek (render
# parity — otherwise the first Week-1 publish resurrects the raw line).

_DEK = "Weight: 301.0 lbs | Recovery range: 12–98% | HRV range: 14–53ms | Week 1 of The Measured Life"


def test_display_stats_line_reframes_pre_genesis_week_dek(monkeypatch):
    monkeypatch.setattr(leadin, "EXPERIMENT_START_DATE", GENESIS)
    out = leadin.display_stats_line(_DEK, "2026-07-09")
    assert "Week 1" not in out
    assert out.startswith("Weight: 301.0 lbs")  # the real measurements stay
    assert "before Day 1" in out and "Prologue" in out


def test_display_stats_line_respects_existing_prologue_framing(monkeypatch):
    monkeypatch.setattr(leadin, "EXPERIMENT_START_DATE", GENESIS)
    line = "Prologue | Before Day 1 | Seattle, WA"
    assert leadin.display_stats_line(line, "2026-07-06") == line  # no duplicate stamp


def test_display_stats_line_post_genesis_passes_through(monkeypatch):
    monkeypatch.setattr(leadin, "EXPERIMENT_START_DATE", GENESIS)
    line = "Weight: 296.4 lbs | Week 2 of The Measured Life"
    assert leadin.display_stats_line(line, GENESIS) == line
    assert leadin.display_stats_line(line, "2026-07-20") == line


def test_display_stats_line_parity_with_wednesday_lambda(monkeypatch):
    import os

    os.environ.setdefault("TABLE_NAME", "life-platform")
    os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
    os.environ.setdefault("EMAIL_RECIPIENT", "test@example.com")
    os.environ.setdefault("EMAIL_SENDER", "noreply@example.com")
    sys.path.insert(0, str(REPO_ROOT / "lambdas"))
    sys.path.insert(0, str(REPO_ROOT / "lambdas" / "emails"))
    import wednesday_chronicle_lambda as chron

    monkeypatch.setattr(chron, "EXPERIMENT_START_DATE", GENESIS)
    monkeypatch.setattr(leadin, "EXPERIMENT_START_DATE", GENESIS)
    cases = [
        (_DEK, "2026-07-09"),
        ("Prologue | Before Day 1 | Seattle, WA", "2026-07-06"),
        ("Week 2 | Seattle, WA | The Measured Life", "2026-07-08"),
        (_DEK, GENESIS),
        ("", "2026-07-09"),
    ]
    for line, d in cases:
        assert chron.display_stats_line(line, d) == leadin.display_stats_line(line, d), (line, d)
