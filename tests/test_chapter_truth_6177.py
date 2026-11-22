"""tests/test_chapter_truth_6177.py — how a published chapter was published, read off the record (#6177, owner ruling
2026-11-22 §6: "Fix any general byline claiming 'Published after Matthew approved it' where that is not supported by an
actual recorded approval").

The producer side of www/src/lib/chapter_truth.js (its own node tests: www/tests/chapter_truth.test.mjs):

  * ``publish_snapshot_chapters.publication_via`` — an ``approved_at`` instant inside the 48-hour sweep's two-minute slot
    (18:00 UTC before 2026-10-18, 11:00 Pacific after), before the sweep stopped publishing (#5884), is "rule"; any other
    instant is "approval"; an instant in the slot after the sweep stopped, a bare day, or nothing is None — the page then
    claims nothing.
  * ``served_dates`` / ``apply_chapter_dates`` carry it as ``published_via`` on a published week only, and both schema
    halves declare it.
  * the ONE switch (``CHAPTER_TRUTH_LIVE``) is read by Python as text, fail-closed, and the RSS channel line reads it:
    off = the line as it was, byte for byte.

Synthetic instants only.
"""

from __future__ import annotations

import os
import sys

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "scripts"))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

import publish_snapshot_chapters as PSC  # noqa: E402
import publish_snapshot_contract as CONTRACT  # noqa: E402
import www_launch_switch as SW  # noqa: E402

_CASES = [
    ("2026-09-04T18:00:44.191941+00:00", "rule"),  # the UTC slot (PDT): 11:00:44 Pacific
    ("2026-10-23T11:00:45-07:00", "rule"),  # the Pacific slot after 2026-10-18
    ("2026-11-06T19:01:10Z", "rule"),  # 11:01 PST — the Pacific slot in winter time
    ("2026-11-06T18:00:30Z", "rule"),  # 10:00 PST — the old UTC slot, still the sweep's
    ("2026-09-04T18:31:37Z", "approval"),  # half an hour past the slot: the approve click
    ("2026-10-10T04:29:30.949081+00:00", "approval"),  # evening Pacific
    ("2026-09-04T18:02:00Z", "approval"),  # the slot is two minutes, no more
    ("2026-11-20T19:00:40Z", None),  # in the slot, but after the sweep stopped publishing: cannot be told
    ("2026-11-20T00:24:35Z", "approval"),  # after the sweep stopped: an instant outside the slot is the click
    ("2026-09-04", None),  # a bare day has no time of day
    ("not a time", None),
    ("", None),
    (None, None),
]


def test_publication_via_reads_the_sweeps_slot():
    wrong = [(i, w, PSC.publication_via(i)) for i, w in _CASES if PSC.publication_via(i) != w]
    assert not wrong, wrong


def test_the_sweep_stopped_publishing_at_the_merge_of_5884():
    assert PSC.SWEEP_STOPPED_PUBLISHING.isoformat() == "2026-11-13T12:14:04-08:00"
    assert PSC.publication_via("2026-11-13T19:00:30Z") == "rule"  # 11:00 PST that day, before the merge
    assert PSC.publication_via("2026-11-14T19:00:30Z") is None


def _api():
    return {
        "weeks": [
            {
                "week": 1,
                "status": "published",
                "published_at": "2026-09-04T18:00:44Z",
                "covers_start": "2026-09-01",
                "covers_end": "2026-09-03",
            },
            {"week": 2, "status": "published", "published_at": "2026-09-12T02:10:00Z", "covers_start": None, "covers_end": None},
            {"week": 3, "status": "published", "published_at": None},
            {"week": 4, "status": "held", "published_at": "2026-09-25T18:00:44Z"},
        ]
    }


def test_served_dates_and_apply_carry_published_via_on_a_published_week_only():
    sd = PSC.served_dates(_api())
    assert sd[1]["published_via"] == "rule" and sd[1]["published_at"] == "2026-09-04"
    assert sd[2]["published_via"] == "approval" and sd[2]["published_at"] == "2026-09-11"  # Pacific day
    assert sd[3]["published_via"] is None and sd[3]["published_at"] is None
    assert 4 not in sd
    chapters = [{"week": n, "status": "published" if n < 4 else "held", "approved": None} for n in (1, 2, 3, 4)]
    PSC.apply_chapter_dates(chapters, _api())
    assert [c["published_via"] for c in chapters] == ["rule", "approval", None, None]
    for c in chapters:
        assert set(c) >= {"published_at", "published_via", "covers_start", "covers_end"}


def test_both_schema_halves_declare_published_via():
    assert CONTRACT.SCHEMA["chapter"]["published_via"] == ("enum:approval|rule", True)
    ts = open(os.path.join(_REPO, "www", "src", "content.config.ts"), encoding="utf-8").read()
    assert 'published_via: z.enum(["approval", "rule"]).nullable(),' in ts
    for v in ("approval", "rule", None):
        CONTRACT._check("enum:approval|rule", True, v, "x")
    with pytest.raises(CONTRACT.SchemaError):
        CONTRACT._check("enum:approval|rule", True, "owner", "x")


def test_the_switch_is_committed_off_and_reads_fail_closed(tmp_path):
    assert SW.read_flag(SW.CHAPTER_TRUTH_JS, "CHAPTER_TRUTH_LIVE") is False
    assert SW.chapter_truth_live() is False
    assert SW.chapter_truth_live(str(tmp_path / "missing.js")) is False
    on = tmp_path / "on.js"
    on.write_text("export const CHAPTER_TRUTH_LIVE = true;\n", encoding="utf-8")
    assert SW.chapter_truth_live(str(on)) is True
    twice = tmp_path / "twice.js"
    twice.write_text("export const CHAPTER_TRUTH_LIVE = true;\nexport const CHAPTER_TRUTH_LIVE = true;\n", encoding="utf-8")
    assert SW.chapter_truth_live(str(twice)) is False


def test_the_rss_channel_line_reads_the_switch_and_is_unchanged_while_off():
    import importlib.util

    spec = importlib.util.spec_from_file_location("v4_build_rss_6177_truth", os.path.join(_REPO, "scripts", "v4_build_rss.py"))
    rss = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rss)
    assert rss.channel_desc() == rss.DESC  # the committed switch is off
    assert rss.channel_desc(False) == rss.DESC
    on = rss.channel_desc(True)
    assert on == rss.DESC_TRUE and "approves each chapter before it publishes" not in on
    assert "48-hour rule he had authorised" in on and "Written by Elena Voss, an AI editorial persona" in on
