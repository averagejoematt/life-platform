"""tests/test_pre_genesis_reader_absence_3522.py — the API half of the #3522/#3523/#3524
Day-1 reader sweep: a zero that was never measured must not leave the handler as a zero.

ADR-104. Four reader surfaces were found on 2026-09-05 (Day 1 of cycle 16) rendering a
pre-start or empty state as though it were data. Two of them are API defects — the front
end could not have fixed either, because by the time the payload arrives the fabricated
zero is indistinguishable from a measured one:

  #3522  /api/character  — `_zeroed_pre_experiment` built seven pillars whose only keys
         were [emoji, level, name, raw_score, tier, xp_delta], every raw_score 0. The
         renderers' held branches (#747 `not_instrumented`, ADR-134 `coverage_hold`) were
         therefore unreachable, so /data/character showed seven "0/100 · 0 xp" rows, an
         all-zero radar, and "The bottlenecks right now: Sleep (0/100 …) and Movement
         (0/100 …)" — a ranking of a seven-way tie among numbers nobody measured. The
         handler's own comment already said this payload is ALSO served the morning after
         every reset, which is the window #931 never framed.

  #3523  /api/weekly_physical_summary — `_experiment_date(7)` clamps the query window's
         lower bound to EXPERIMENT_START, so a calendar day before genesis is never
         asked about; the handler then built its 7-day array unconditionally and stamped
         `total_active_minutes: round(0)` on days it had no data for, beside `steps: None`.
         One absence, two encodings, in the same row.

Plus a structural guard on site/index.html for #3524's leaked static placeholder — the
generator (scripts/v4_build_home_proof.py) owns only the sentinel-delimited noscript
block and the OG tags, so the dial and the stat row are hand-authored and nothing else
was watching them.

All offline. Genesis dates derive from now(PT) — no wall-clock time bombs.
"""

import json
import os
import re
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

from web import (  # noqa: E402
    site_api_character as char,
    site_api_common as common,
    site_api_observatory as obs,
    site_api_vitals as vitals,  # the routed facade for /api/character (site_api_character holds the logic)
)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PILLARS = ["sleep", "movement", "nutrition", "metabolic", "mind", "relationships", "consistency"]


def _today_pt():
    return datetime.now(common.PT).date()


def _iso(d):
    return d.strftime("%Y-%m-%d")


def _body(resp):
    assert resp["statusCode"] == 200, resp
    return json.loads(resp["body"])


# ── #3522 · the zeroed character sheet ────────────────────────────────────────


class _EmptyTable:
    """No experiment-phase character sheet exists — the state on Day 1 before the
    first nightly compute, and pre-start."""

    def query(self, **kwargs):
        return {"Items": []}


def _character(monkeypatch, genesis_iso):
    for mod in (common, char, vitals):
        monkeypatch.setattr(mod, "EXPERIMENT_START", genesis_iso, raising=False)
    monkeypatch.setattr(vitals, "table", _EmptyTable(), raising=False)
    return _body(vitals.handle_character())


def test_zeroed_sheet_carries_the_absence_flags_pre_start(monkeypatch):
    """Pre-start (a staged future genesis): every pillar is held, not scored."""
    b = _character(monkeypatch, _iso(_today_pt() + timedelta(days=2)))
    assert b["pre_start"] is True
    assert [p["name"] for p in b["pillars"]] == PILLARS
    for p in b["pillars"]:
        assert p["coverage_hold"] is True, p
        assert p["data_coverage"] == 0.0, p
        # #747's flag is what the radar, the rows and the cockpit all key off. It means
        # exactly this state: zero weighted components carried any value today.
        assert p["not_instrumented"] is True, p
        assert p["not_instrumented_note"], "the reason must be the TRUE one, not 'no sensor'"
        assert "no sheet yet" in p["not_instrumented_note"].lower()


def test_zeroed_sheet_carries_the_absence_flags_the_morning_after_a_reset(monkeypatch):
    """The window the handler's own comment names and #931 never framed: genesis is in
    the PAST (pre_start is False, the countdown is over), the phase filter hides every
    pilot sheet, and the first experiment-phase sheet has not computed yet."""
    b = _character(monkeypatch, _iso(_today_pt()))
    assert b.get("pre_start") is False, "Day 1 is not pre-start — this is the harder case"
    assert b["character"]["pre_experiment"] is True
    for p in b["pillars"]:
        assert p["coverage_hold"] is True, p
        assert p["data_coverage"] == 0.0, p
        assert p["not_instrumented"] is True, p


def test_zeroed_sheet_never_stamps_a_future_as_of(monkeypatch):
    """#948's clamp, re-pinned: the added keys must not have disturbed it."""
    b = _character(monkeypatch, _iso(_today_pt() + timedelta(days=2)))
    assert b["character"]["as_of_date"] == _iso(_today_pt())


def test_zeroed_sheet_negative_control(monkeypatch):
    """The pre-fix payload, reproduced from the same handler by stripping the flags:
    it is indistinguishable from a real sheet in which every pillar scored zero. That
    is the whole defect, and it is what the assertions above must be able to catch."""
    b = _character(monkeypatch, _iso(_today_pt()))
    stripped = [
        {k: v for k, v in p.items() if k not in ("coverage_hold", "data_coverage", "not_instrumented", "not_instrumented_note")}
        for p in b["pillars"]
    ]
    assert sorted(stripped[0]) == ["absent_behaviors", "emoji", "level", "name", "raw_score", "score_delta", "tier", "xp_debt", "xp_delta"]
    for p in stripped:
        assert p["raw_score"] == 0
        assert not p.get("not_instrumented"), "control: nothing in the stripped shape says these zeros were never measured"


def test_a_real_sheet_is_untouched(monkeypatch):
    """Positive control: a computed sheet still reports its real scores and its real
    (absent) hold flags — this guard must not make every pillar look held."""

    class _Table:
        def query(self, **kwargs):
            rec = {"sk": f"DATE#{_iso(_today_pt())}", "character_level": 3, "character_tier": "Foundation", "character_xp": 240}
            for i, p in enumerate(PILLARS):
                rec[f"pillar_{p}"] = {
                    "level": 3,
                    "raw_score": 40 + i * 5,
                    "tier": "Foundation",
                    "xp_delta": 1,
                    "data_coverage": 1.0,
                    "coverage_hold": False,
                }
            return {"Items": [rec]}

    for mod in (common, char, vitals):
        monkeypatch.setattr(mod, "EXPERIMENT_START", _iso(_today_pt() - timedelta(days=30)), raising=False)
    monkeypatch.setattr(vitals, "table", _Table(), raising=False)
    b = _body(vitals.handle_character())
    assert [p["raw_score"] for p in b["pillars"]] == [40, 45, 50, 55, 60, 65, 70]
    for p in b["pillars"]:
        assert p["not_instrumented"] is False
        assert p["coverage_hold"] is False


# ── #3523 · the pre-genesis training week ─────────────────────────────────────


def _weekly(monkeypatch, genesis_iso, items_by_source=None):
    items = items_by_source or {}
    for mod in (common, obs):
        monkeypatch.setattr(mod, "EXPERIMENT_START", genesis_iso, raising=False)
    monkeypatch.setattr(obs, "_query_source", lambda source, s, e, **kw: list(items.get(source, [])), raising=False)
    return _body(obs.handle_weekly_physical_summary())


def test_weekly_summary_pre_genesis_days_are_absent_not_zero(monkeypatch):
    """Genesis TODAY (the live 2026-09-05 state): six of the seven rows fall before it."""
    genesis = _iso(_today_pt())
    b = _weekly(monkeypatch, genesis)
    days = b["days"]
    assert len(days) == 7
    pre = [d for d in days if d["date"] < genesis]
    assert len(pre) == 6, "six calendar days precede a genesis of today"
    for d in pre:
        assert d["pre_genesis"] is True, d
        # The defect, verbatim: `steps: None, total_active_minutes: 0` — one absence
        # encoded two ways, so the table read "Sat — 0 · Sun — 0 · …".
        assert d["total_active_minutes"] is None, d
        assert d["steps"] is None, d
        assert d["activities"] == []
    today_row = [d for d in days if d["date"] == genesis][0]
    assert today_row["pre_genesis"] is False
    assert today_row["total_active_minutes"] == 0, "an in-window quiet day is a MEASURED zero and stays one"


def test_weekly_summary_future_genesis_has_no_numeric_zero(monkeypatch):
    """Pre-start: `_experiment_date(7)` is after today, so nothing was queried at all."""
    b = _weekly(monkeypatch, _iso(_today_pt() + timedelta(days=2)))
    assert all(d["pre_genesis"] for d in b["days"])
    assert all(d["total_active_minutes"] is None for d in b["days"])
    assert not [d for d in b["days"] if d["total_active_minutes"] == 0], "no row may carry a numeric 0 before genesis"


def test_weekly_summary_positive_control_real_activity(monkeypatch):
    """An in-window Strava activity still yields its real minutes — the absence rule
    must not blank the data it exists to protect."""
    genesis = _iso(_today_pt() - timedelta(days=30))
    today = _iso(_today_pt())
    items = {"strava": [{"date": today, "activities": [{"activity_id": "1", "sport_type": "Walk", "duration_minutes": 47}]}]}
    b = _weekly(monkeypatch, genesis, items)
    row = [d for d in b["days"] if d["date"] == today][0]
    assert row["pre_genesis"] is False
    assert row["total_active_minutes"] == 47
    assert row["activities"] == [{"type": "Walk", "minutes": 47}]
    # And every other in-window day keeps its honest measured zero.
    assert [d["total_active_minutes"] for d in b["days"]] == [0, 0, 0, 0, 0, 0, 47]


def test_weekly_summary_pre_genesis_drops_a_stray_in_window_record(monkeypatch):
    """Defence in depth: even if a source somehow returns a record dated before genesis
    (a phase-filter miss), the row still reads as absence — the day is outside the
    experiment, so its contents are not this cycle's data."""
    genesis = _iso(_today_pt())
    stray = _iso(_today_pt() - timedelta(days=3))
    items = {"strava": [{"date": stray, "activities": [{"activity_id": "9", "sport_type": "Ride", "duration_minutes": 60}]}]}
    b = _weekly(monkeypatch, genesis, items)
    row = [d for d in b["days"] if d["date"] == stray][0]
    assert row["total_active_minutes"] is None
    assert row["activities"] == []


# ── #3524 · the home shell's own placeholders ─────────────────────────────────

HOME = os.path.join(REPO, "site", "index.html")


def test_home_dial_eyebrow_is_bound():
    """The eyebrow shipped as a static `<span class="label">day</span>` that no branch
    ever wrote, so launch eve rendered DAY / 1 / DAY TO GO. It must carry a binding —
    otherwise story.js's dialCopy() has nothing to write to and the guard in
    tests/js/home_dial_and_figures_3524.test.mjs passes while the page still lies."""
    html = open(HOME, encoding="utf-8").read()
    dial = re.search(r'<div class="dial-center">(.*?)</div>', html, re.S)
    assert dial, "the dial hub must still exist"
    assert 'data-bind="dayEyebrow"' in dial.group(1), "the eyebrow is unbound — the #3524 defect"
    for b in ("dayEyebrow", "dayNum", "dayCap"):
        assert f'data-bind="{b}"' in dial.group(1), f"all three hub glyphs are bound; {b} is not"


def test_home_stat_row_uses_one_placeholder_glyph():
    """Three figures, three different pre-JS shimmer glyphs ("··" / "···" / "··%") —
    and because renderNumbers left one of them unwritten, the odd one out survived into
    the rendered page next to two "—"s. One glyph, and story.js writes all three."""
    html = open(HOME, encoding="utf-8").read()
    row = re.search(r'<div class="numbers" data-bind="numbers">(.*?)</div>\s*<p class="beat-note"', html, re.S)
    assert row, "the numbers beat must still exist"
    markup = re.sub(r"<!--.*?-->", "", row.group(1), flags=re.S)  # the comments discuss the old glyphs
    glyphs = re.findall(r'data-bind="(lost|current|progress)"[^>]*>([^<]*)<', markup)
    assert sorted(g[0] for g in glyphs) == ["current", "lost", "progress"]
    assert len({g[1] for g in glyphs}) == 1, f"one shimmer glyph across the row, found {glyphs}"
    assert "\u00b7\u00b7\u00b7" not in markup, "the leaked three-dot placeholder is gone"
