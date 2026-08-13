"""tests/test_predict_week_genesis_seed_1952.py — #1952 regression pins.

The cycle-11 predict-the-week challenge was seeded by the Sunday 2026-07-26 prep
run, and deploy/build_genesis_predict_week.py stamped week_id from
datetime.now(PT).isocalendar() — the RUN-TIME week 2026-W30 — while the genesis
week (Day 1 = Mon 2026-07-27 .. Sun 2026-08-02) is ISO 2026-W31. The #1198
fail-closed guard in site_api_social._predict_subject (correct, unweakened) then
hid the flagship engagement hook for the entire opening week.

Pins:
  1. A pre-genesis prep run stamps the GENESIS week, not the wall-clock week
     (the acceptance regression guard — fails against the pre-#1952 seeder).
  2. The seeder never consults the wall clock at all.
  3. genesis_iso_week math, including the ISO year-boundary.
  4. build_challenge refuses a --genesis that disagrees with the freeze's own
     genesis, and refuses when no genesis is available anywhere.
  5. evaluate_predict_week_state — the restart-verify semantics: pre-genesis
     countdown dark is correct; during the genesis week active:true is REQUIRED
     (the exact cycle-11 dark-week state fails); after the genesis week the
     verifier stands down; an unreachable endpoint never earns a pass.
"""

import importlib.util
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "deploy"))


def _load(module_name: str, rel_path: str):
    if module_name in sys.modules:
        return sys.modules[module_name]
    spec = importlib.util.spec_from_file_location(module_name, REPO_ROOT / rel_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


bgpw = _load("build_genesis_predict_week", "deploy/build_genesis_predict_week.py")

GENESIS = "2026-07-27"  # cycle-11 Day 1, a Monday — ISO week 2026-W31
PT = ZoneInfo("America/Los_Angeles")


def _frozen(genesis=GENESIS):
    return {
        "genesis": genesis,
        "hypotheses": [
            {"test_spec": {"condition_metric": "calories", "condition_threshold": 2100, "outcome_metric": "recovery"}},
            {"test_spec": {"condition_metric": "steps", "condition_threshold": 6000, "outcome_metric": "recovery"}},
        ],
    }


def _stamp():
    return {
        "sha256": "a" * 64,
        "public_artifact_url": f"https://averagejoematt.com/experiments/prereg/genesis-{GENESIS}.json",
    }


# ── 1. the acceptance regression guard ──────────────────────────────────────


class _SundayPrepRunClock:
    """Stand-in for the module's wall clock, pinned to the real cycle-11 prep
    run: Sunday 2026-07-26 09:00 PT — ISO week 2026-W30, one week BEFORE the
    genesis week. The pre-#1952 seeder stamped this week onto the challenge."""

    @staticmethod
    def now(tz=None):
        return datetime(2026, 7, 26, 9, 0, tzinfo=PT)


def test_sunday_prep_run_stamps_the_genesis_week(monkeypatch):
    # raising=False: the fixed seeder no longer imports datetime at all — the
    # patch only bites if the module still owns a wall clock (the pre-fix code).
    monkeypatch.setattr(bgpw, "datetime", _SundayPrepRunClock, raising=False)
    try:
        ch = bgpw.build_challenge(_frozen(), _stamp(), genesis=GENESIS)
    except TypeError:
        # pre-#1952 signature: build_challenge(frozen, stamp, now=None)
        ch = bgpw.build_challenge(_frozen(), _stamp())
    assert ch["week_id"] == "2026-W31", (
        f"a Sunday 2026-07-26 prep run must stamp the GENESIS week 2026-W31, got {ch['week_id']!r} — "
        "the #1198 fail-closed guard would hide the challenge for the whole opening week (#1952)"
    )


# ── 2. no wall clock, ever ──────────────────────────────────────────────────


class _NoWallClock:
    @staticmethod
    def now(tz=None):
        raise AssertionError("the seeder consulted the wall clock — week_id must derive from the genesis date only (#1952)")


def test_seeder_never_consults_the_wall_clock(monkeypatch):
    monkeypatch.setattr(bgpw, "datetime", _NoWallClock, raising=False)
    ch = bgpw.build_challenge(_frozen(), _stamp(), genesis=GENESIS)
    assert ch["week_id"] == "2026-W31"


def test_module_source_has_no_now_call():
    src = (REPO_ROOT / "deploy" / "build_genesis_predict_week.py").read_text()
    assert ".now(" not in src, "build_genesis_predict_week.py must not read the wall clock (#1952)"


# ── 3. genesis_iso_week math ────────────────────────────────────────────────


@pytest.mark.parametrize(
    "genesis,expected",
    [
        ("2026-07-27", "2026-W31"),  # cycle-11 Day 1 (Monday)
        ("2026-08-02", "2026-W31"),  # a Sunday genesis stays in the same ISO week
        ("2026-08-03", "2026-W32"),  # the following Monday
        ("2027-01-01", "2026-W53"),  # ISO year boundary: Fri 2027-01-01 belongs to 2026-W53
        ("2027-01-04", "2027-W01"),  # first ISO week of 2027
    ],
)
def test_genesis_iso_week(genesis, expected):
    assert bgpw.genesis_iso_week(genesis) == expected


# ── 4. refusal guards ───────────────────────────────────────────────────────


def test_refuses_genesis_disagreeing_with_the_freeze():
    with pytest.raises(SystemExit, match="disagrees"):
        bgpw.build_challenge(_frozen(genesis="2026-07-27"), _stamp(), genesis="2026-08-03")


def test_refuses_when_no_genesis_anywhere():
    frozen = _frozen()
    frozen.pop("genesis")
    with pytest.raises(SystemExit, match="[Nn]o genesis"):
        bgpw.build_challenge(frozen, _stamp())


def test_explicit_genesis_matching_the_freeze_is_accepted():
    ch = bgpw.build_challenge(_frozen(), _stamp(), genesis=GENESIS)
    assert ch["week_id"] == "2026-W31"
    assert ch["prereg_sha256"] == "a" * 64


# ── 5. restart-verify semantics ─────────────────────────────────────────────


@pytest.mark.parametrize(
    "today,active,expect_ok",
    [
        (date(2026, 7, 26), False, True),  # pre-genesis countdown: dark is correct
        (date(2026, 7, 26), True, True),  # pre-genesis + live: noted, not the verifier's business
        (date(2026, 7, 27), True, True),  # Day 1, live — healthy
        (date(2026, 7, 27), False, False),  # Day 1 dark — the cycle-11 regression
        (date(2026, 8, 1), False, False),  # Day 6 dark — the exact state the delta review found
        (date(2026, 8, 2), True, True),  # Sunday Day 7 still inside 2026-W31
        (date(2026, 8, 3), False, True),  # genesis week over: weekly re-seed is out of scope
        (date(2026, 7, 28), None, False),  # unreachable endpoint never earns a pass
        (date(2026, 8, 3), None, False),  # unreachable fails even outside the genesis week
    ],
)
def test_evaluate_predict_week_state(today, active, expect_ok):
    ok, detail = bgpw.evaluate_predict_week_state(GENESIS, today, active)
    assert ok is expect_ok, f"today={today} active={active}: {detail}"


def test_evaluate_detail_names_the_regression_when_dark_in_genesis_week():
    ok, detail = bgpw.evaluate_predict_week_state(GENESIS, date(2026, 7, 29), False)
    assert not ok
    assert "1952" in detail and "2026-W31" in detail


# ── 6. --if-frozen: the reset-hook posture (#2612) ──────────────────────────
#
# Cycle 13 went dark for its whole genesis week because restart_pipeline step 2d
# DELETES site/config/current_challenge.json on every --apply while re-seeding it
# was an attended printed next-step. The re-seed is now post-verify hook (d), and
# it carries --if-frozen so a reset whose pre-registration has not been re-landed
# SKIPS loudly (exit 0) instead of aborting the pipeline's final hooks. The
# degradation must be exactly that: skip on a precondition failure, never on
# anything else, and never a silent one.


def _run_main(monkeypatch, argv, frozen_path=None, stamp=None):
    """Drive main() with argv, optionally repointing the freeze at a temp path."""
    monkeypatch.setattr(sys, "argv", ["build_genesis_predict_week.py"] + argv)
    if frozen_path is not None:
        monkeypatch.setattr(bgpw.genesis_prereg_stamp, "FROZEN_PATH", frozen_path)
    monkeypatch.setattr(bgpw.genesis_prereg_stamp, "require_valid_stamp", lambda frozen=None: (stamp or _stamp()))
    return bgpw.main()


def test_if_frozen_skips_loudly_when_no_freeze_exists(monkeypatch, tmp_path, capsys):
    rc = _run_main(monkeypatch, ["--if-frozen", "--apply"], frozen_path=tmp_path / "absent.json")
    out = capsys.readouterr().out
    assert rc == 0, "a missing freeze must not abort the reset's last hooks"
    assert "SKIP (--if-frozen)" in out and "no frozen pre-registration" in out
    assert "build_genesis_predict_week.py --apply" in out, "a skip that does not name its remedy is a silent skip"


def test_if_frozen_skips_when_the_freeze_covers_a_DIFFERENT_genesis(monkeypatch, tmp_path, capsys):
    # The live reset shape: the outgoing cycle's freeze is still on disk when the
    # incoming genesis is seeded. build_challenge refuses the mismatch; --if-frozen
    # must turn that refusal into a skip, not an abort.
    import json

    p = tmp_path / "frozen.json"
    p.write_text(json.dumps(_frozen(genesis="2026-07-27")))
    monkeypatch.setattr(sys, "argv", ["x", "--genesis", "2026-08-10", "--if-frozen", "--apply"])
    monkeypatch.setattr(bgpw.genesis_prereg_stamp, "FROZEN_PATH", p)
    monkeypatch.setattr(bgpw.genesis_prereg_stamp, "require_valid_stamp", lambda frozen=None: _stamp())
    rc = bgpw.main()
    out = capsys.readouterr().out
    assert rc == 0
    assert "SKIP (--if-frozen)" in out and "2026-07-27" in out


def test_WITHOUT_if_frozen_a_missing_freeze_still_hard_aborts(monkeypatch, tmp_path):
    # Mutation-proof on the degradation itself: the attended path is unchanged, so
    # a hand-run seed can never silently produce nothing.
    with pytest.raises(SystemExit):
        _run_main(monkeypatch, ["--apply"], frozen_path=tmp_path / "absent.json")


def test_if_frozen_still_seeds_when_the_freeze_is_good(monkeypatch, tmp_path, capsys):
    # The flag must not become a blanket "do nothing": with a valid freeze the
    # payload is built and the upload path is reached.
    import json

    p = tmp_path / "frozen.json"
    p.write_text(json.dumps(_frozen(genesis="2026-08-10")))
    wrote = {}

    class _S3:
        def put_object(self, **kw):
            wrote.update(kw)

    monkeypatch.setattr(sys, "argv", ["x", "--genesis", "2026-08-10", "--if-frozen", "--apply"])
    monkeypatch.setattr(bgpw.genesis_prereg_stamp, "FROZEN_PATH", p)
    monkeypatch.setattr(bgpw.genesis_prereg_stamp, "require_valid_stamp", lambda frozen=None: _stamp())
    import boto3

    monkeypatch.setattr(boto3, "client", lambda *a, **k: _S3())
    rc = bgpw.main()
    assert rc == 0
    assert wrote["Key"] == bgpw.CHALLENGE_KEY
    payload = json.loads(wrote["Body"].decode())
    assert payload["week_id"] == "2026-W33", "genesis 2026-08-10 is ISO week 2026-W33"
    assert payload["predict_metrics"], "a seeded subject with no metrics is still a dark widget"
    assert "SKIP" not in capsys.readouterr().out
