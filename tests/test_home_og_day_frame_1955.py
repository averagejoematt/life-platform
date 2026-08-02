"""#1955 — the share card and the site agree on the experiment's day, in PT.

Live repro (2026-08-02T02:36Z, i.e. the PT *evening* of 08-01): the home
og:description said "Day 6 … As of 2026-08-02" — day_n from the PT journey
payload, as_of from the generator-local/UTC clock — while /api/vitals'
window_disclosure (post-#1936, PT-anchored) said Day 6. Two dates, one claim.

These tests FREEZE both clocks at an evening-PT instant (2026-08-02T01:40Z =
2026-08-01 18:40 PDT — inside the 5pm-midnight PT window where UTC has already
rolled to tomorrow) and assert the og:description's day number, its "As of"
date, and the vitals window_disclosure all agree on the PACIFIC day.

No wall-clock leaks (golden-test discipline): the cycle start is a FIXTURE
("2026-07-27" — frozen instant = Day 6), monkeypatched into site_api_vitals,
and every now() both code paths can reach is frozen — stdlib
``datetime.date.today`` (the generator-local clock that produced the bug),
``common.pacific_time.pacific_now`` (the shared PT frame), and the
datetime class inside site_api_vitals.

Negative proof: against the pre-#1955 scripts/v4_proof.py these tests fail on
"As of 2026-08-02" — the exact live artifact.
"""

import datetime as _dt
import json
import re
import sys
from datetime import timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lambdas"))

import v4_proof  # noqa: E402
from common import pacific_time  # noqa: E402
from web import site_api_vitals as vitals  # noqa: E402

# The frozen instant: UTC has rolled to 08-02; Pacific is still the evening of 08-01.
FROZEN_UTC = _dt.datetime(2026, 8, 2, 1, 40, tzinfo=timezone.utc)
START = "2026-07-27"  # fixture genesis: the frozen instant is PT Day 6, UTC "Day 7"
PT_DAY = "2026-08-01"
EXPECTED_DAY_N = 6


class _FrozenDate(_dt.date):
    """date whose today() is the GENERATOR-LOCAL (CI/UTC) calendar day."""

    @classmethod
    def today(cls):
        return cls(2026, 8, 2)


class _FrozenDateTime(_dt.datetime):
    """datetime whose now() is the frozen instant (tz-aware when tz given)."""

    @classmethod
    def now(cls, tz=None):
        if tz is None:
            return cls(2026, 8, 2, 1, 40)
        f = FROZEN_UTC.astimezone(tz)
        return cls(f.year, f.month, f.day, f.hour, f.minute, f.second, f.microsecond, tzinfo=f.tzinfo)


def _freeze(monkeypatch):
    # The generator-local clock (datetime.date.today() — CI builds run in UTC).
    monkeypatch.setattr(_dt, "date", _FrozenDate)
    # The shared Pacific frame (pacific_today/pacific_day_n resolve through this).
    monkeypatch.setattr(pacific_time, "pacific_now", lambda: FROZEN_UTC.astimezone(pacific_time.PACIFIC))
    # The vitals module's own datetime class (its PT anchor + ISO stamps).
    monkeypatch.setattr(vitals, "datetime", _FrozenDateTime)
    # Hermetic genesis: the assertion must not move on the next cycle reset.
    monkeypatch.setattr(vitals, "EXPERIMENT_START", START)


def _journey(as_of="", day_n=EXPECTED_DAY_N):
    return {
        "start_weight": 321.4,
        "goal_weight": 185,
        "current_weight": 317.1,
        "lost_lbs": 4.3,
        "day_n": day_n,
        "pre_start": False,
        "start_date": START,
        "as_of": as_of,
        "source": "live",
    }


def _og_desc(journey):
    tags = v4_proof.home_og(journey, {"level": 1})
    return tags[("property", "og:description")]


def _day_and_as_of(desc):
    day = re.search(r"Day (\d+)", desc)
    as_of = re.search(r"As of (\d{4}-\d{2}-\d{2})", desc)
    assert day and as_of, f"og:description missing day/as-of: {desc!r}"
    return int(day.group(1)), as_of.group(1)


class TestHomeOgPtFrame:
    def test_day_n_and_as_of_come_from_the_same_pt_day(self, monkeypatch):
        """The live bug: empty payload as_of falls back to the generator clock.

        Pre-fix this produced "Day 6 … As of 2026-08-02" (UTC tomorrow); the pair
        must instead both read the PACIFIC day of the frozen instant.
        """
        _freeze(monkeypatch)
        day_n, as_of = _day_and_as_of(_og_desc(_journey(as_of="")))
        assert as_of == PT_DAY
        assert day_n == EXPECTED_DAY_N
        # Definitional coherence: the day number IS the PT day-index of the stamp.
        assert day_n == pacific_time.pacific_day_n(START, on_date=as_of)

    def test_meta_stamp_utc_instant_lands_on_the_pt_day(self, monkeypatch):
        """The API path: _meta.generated_at is a UTC instant; slicing [:10] took
        the UTC day. load_journey -> home_og must stamp the PACIFIC day."""
        _freeze(monkeypatch)
        payload = {
            "journey": {
                "start_weight_lbs": 321.4,
                "goal_weight_lbs": 185,
                "current_weight_lbs": 317.1,
                "lost_lbs": 4.3,
                "day_n": EXPECTED_DAY_N,
                "start_date": START,
            },
            "_meta": {"generated_at": FROZEN_UTC.isoformat()},
        }
        monkeypatch.setattr(v4_proof, "_fetch_json", lambda *_a, **_k: payload)
        day_n, as_of = _day_and_as_of(_og_desc(v4_proof.load_journey()))
        assert as_of == PT_DAY
        assert day_n == EXPECTED_DAY_N

    def test_og_noscript_and_vitals_disclosure_agree(self, monkeypatch):
        """The three public surfaces — og:description, the home <noscript> block,
        and /api/vitals' window_disclosure — state the SAME day number at the
        frozen evening-PT instant, and the og stamp is that day's date."""
        _freeze(monkeypatch)

        # /api/vitals, network-free (same mock set as test_vitals_frame).
        monkeypatch.setattr(vitals, "_query_source", lambda *_a, **_k: [])
        monkeypatch.setattr(vitals, "_latest_item", lambda *_a, **_k: {})
        monkeypatch.setattr(
            vitals.vitals_resolver,
            "resolve_vitals",
            lambda *_a, **_k: {
                "recovery_pct": None,
                "recovery_status": None,
                "hrv_ms": None,
                "rhr_bpm": None,
                "recovery_as_of": None,
                "sleep_hours": None,
                "sleep_as_of": None,
                "steps": None,
                "steps_source": None,
                "steps_as_of": None,
            },
        )
        resp = vitals.handle_vitals()
        assert resp["statusCode"] == 200
        disclosure = json.loads(resp["body"])["vitals"]["window_disclosure"]
        m = re.search(r"Today is Day (\d+)", disclosure)
        assert m, f"no day claim in disclosure: {disclosure!r}"
        vitals_day = int(m.group(1))

        og_day, og_as_of = _day_and_as_of(_og_desc(_journey(as_of="")))

        noscript = v4_proof.home_block_html(_journey(as_of=""), {"level": 1})
        n = re.search(r"Day (\d+)\.", noscript)
        assert n, f"no day claim in noscript block: {noscript!r}"

        assert vitals_day == og_day == int(n.group(1)) == EXPECTED_DAY_N
        assert og_as_of == PT_DAY

    def test_stale_payload_day_n_is_recomputed_from_the_stamp(self, monkeypatch):
        """A wrong/stale payload day_n cannot leak into the card: day_n is the PT
        day-index OF the as_of date, not whatever the payload happened to say."""
        _freeze(monkeypatch)
        day_n, as_of = _day_and_as_of(_og_desc(_journey(as_of=PT_DAY, day_n=99)))
        assert day_n == EXPECTED_DAY_N
        assert as_of == PT_DAY


class TestPacificDayN:
    def test_day_one_is_the_start_date(self):
        assert pacific_time.pacific_day_n(START, on_date=START) == 1

    def test_pre_start_clamps_to_zero(self):
        assert pacific_time.pacific_day_n(START, on_date="2026-07-20") == 0

    def test_unparseable_dates_return_zero(self):
        assert pacific_time.pacific_day_n("", on_date=PT_DAY) == 0
        assert pacific_time.pacific_day_n(START, on_date="not-a-date") == 0

    def test_default_on_date_is_pacific_today(self, monkeypatch):
        monkeypatch.setattr(pacific_time, "pacific_now", lambda: FROZEN_UTC.astimezone(pacific_time.PACIFIC))
        assert pacific_time.pacific_day_n(START) == EXPECTED_DAY_N
