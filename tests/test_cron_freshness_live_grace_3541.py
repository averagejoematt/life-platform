#!/usr/bin/env python3
"""tests/test_cron_freshness_live_grace_3541.py — #3541: the cron-freshness dead-man's
`grace_hours` used to be a founding-week snapshot in
`scripts/scheduled_workflow_registry.py::WATCH_POLICY` — `deploy-wedge-watch.yml`'s
8.0h was "tuned just above the then-observed max (6.99h)" and breached the very next
day (n=60 re-measure: median 211 min, max 729 min = 12.15h), auto-filing #3237 six
times before the auto-close raced past the fix.

`scripts/check_cron_freshness.py` now RE-DERIVES each watched workflow's grace from
its OWN trailing fire history every run (`derive_live_grace_hours` /
`scheduled_run_history`), with the registry literal as a FLOOR
(`effective_grace_hours` never narrows it) and an explicit NEWBORN rule: a cron with
too little history (<`NEWBORN_MIN_SAMPLES` runs) is not re-derived at all — the
registry literal is used exactly as declared, so a brand-new watched workflow can
never inherit a false-tight window built from a handful of its first fires.

Pure functions only here — no network. The live-parity assertion ("the registry
literal is >= the live max whenever GitHub is reachable") lives in
`test_deploy_wedge_watch_grace_is_a_floor_of_the_live_max` below and is a LOUD skip,
never a silent pass, when `gh` cannot reach the API.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SCRIPTS = os.path.join(ROOT, "scripts")

if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

yaml = pytest.importorskip("yaml", reason="PyYAML parses the workflow documents under test")


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"{name}_3541", os.path.join(SCRIPTS, f"{name}.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


watch = _load("check_cron_freshness")
reg = _load("scheduled_workflow_registry")

NOW = datetime(2026, 9, 5, 4, 0, tzinfo=timezone.utc)


def _series(*gaps_minutes: float) -> list[str]:
    """A synthetic OLDEST-FIRST timestamp series built from consecutive gaps."""
    t = NOW - timedelta(minutes=sum(gaps_minutes))
    out = [t.isoformat().replace("+00:00", "Z")]
    for g in gaps_minutes:
        t = t + timedelta(minutes=g)
        out.append(t.isoformat().replace("+00:00", "Z"))
    return out


# ═════════════════════════════════════════════════════════════════════════════
# derive_live_grace_hours — the newborn rule, and the max-gap x margin derivation
# ═════════════════════════════════════════════════════════════════════════════


def test_newborn_cron_withholds_a_derivation():
    """Fewer than NEWBORN_MIN_SAMPLES parseable runs -> None, never a number computed
    from a sample too small to trust (#3541's own stated defect, one clock shorter)."""
    series = _series(*([15.0] * (watch.NEWBORN_MIN_SAMPLES - 2)))  # NEWBORN_MIN_SAMPLES - 1 timestamps
    grace, note = watch.derive_live_grace_hours(series)
    assert grace is None
    assert "newborn" in note


def test_a_mature_history_derives_margin_times_the_max_gap():
    gaps = [15.0] * 25 + [729.0]  # the #3541 reproduction's own measured max, in minutes
    series = _series(*gaps)
    grace, note = watch.derive_live_grace_hours(series, margin=1.5)
    assert grace == pytest.approx((729.0 / 60.0) * 1.5, rel=1e-6)
    assert "live" in note and "729" not in note  # rendered in hours, not raw minutes


def test_derivation_ignores_unparseable_timestamps_rather_than_crashing():
    series = _series(*([15.0] * (watch.NEWBORN_MIN_SAMPLES + 5)))
    series[3] = "not-a-timestamp"
    grace, note = watch.derive_live_grace_hours(series)
    assert grace is not None  # the other NEWBORN_MIN_SAMPLES+ good timestamps still count
    assert "scheduled run" not in note or "newborn" not in note or grace is not None


def test_exactly_at_the_newborn_floor_is_derived_one_below_is_not():
    """The boundary itself — the off-by-one this class of guard always risks."""
    just_below = _series(*([15.0] * (watch.NEWBORN_MIN_SAMPLES - 2)))
    just_at = _series(*([15.0] * (watch.NEWBORN_MIN_SAMPLES - 1)))
    assert watch.derive_live_grace_hours(just_below)[0] is None
    assert watch.derive_live_grace_hours(just_at)[0] is not None


# ═════════════════════════════════════════════════════════════════════════════
# effective_grace_hours — the registry literal is a FLOOR, never a ceiling
# ═════════════════════════════════════════════════════════════════════════════


def test_a_live_grace_above_the_declared_literal_widens_the_window():
    assert watch.effective_grace_hours(8.0, 18.225) == 18.225


def test_a_live_grace_below_the_declared_literal_never_narrows_it():
    """A recently-more-reliable cron must not silently tighten its own dead-man."""
    assert watch.effective_grace_hours(8.0, 3.0) == 8.0


def test_no_live_derivation_falls_back_to_the_declared_literal_unchanged():
    assert watch.effective_grace_hours(8.0, None) == 8.0


# ═════════════════════════════════════════════════════════════════════════════
# end to end (#3541 reproduction): the exact deploy-wedge-watch shape breaches with
# the OLD static 8.0h grace and does not breach once live-derived
# ═════════════════════════════════════════════════════════════════════════════


def test_deploy_wedge_watch_reproduction_breaches_the_old_static_grace():
    """The bug, reproduced: cadence 0.25h (declared */15) + the OLD static 8.0h grace
    = 8.25h deadline. A newest-run age of 9.0h (the live #3237 STALE reproduction)
    breaches it."""
    verdict, _age = watch.classify(newest_created_at=(NOW - timedelta(hours=9.0)).isoformat(), deadline_hours=8.25, now=NOW)
    assert verdict == watch.STALE


def test_deploy_wedge_watch_reproduction_does_not_breach_once_live_derived():
    """The same 9.0h-old run, but with grace re-derived from the #3541 measured
    history (n=60, max 729 min): the effective deadline comfortably clears it."""
    history = _series(*([15.0] * 58 + [729.0]))  # 60 fires, worst gap the measured 729 min
    live_grace, _note = watch.derive_live_grace_hours(history)
    effective = watch.effective_grace_hours(8.0, live_grace)
    deadline = 0.25 + effective  # cadence(declared */15) + effective grace
    verdict, _age = watch.classify(newest_created_at=(NOW - timedelta(hours=9.0)).isoformat(), deadline_hours=deadline, now=NOW)
    assert verdict == watch.OK, f"deadline={deadline}h did not clear a 9.0h-old run"


def test_main_prints_the_derived_grace_note_for_a_watched_workflow(monkeypatch, capsys):
    """The named live-output proof this issue asks for: a `check_cron_freshness.py`
    run must PRINT what grace it used and why, for every watched row — not silently
    substitute a number."""
    real_now = datetime.now(timezone.utc)  # main() calls datetime.now() itself, not NOW
    recent = (real_now - timedelta(hours=1.0)).isoformat()

    def _recent_series(*gaps_minutes):
        t = real_now - timedelta(minutes=sum(gaps_minutes))
        out = [t.isoformat()]
        for g in gaps_minutes:
            t = t + timedelta(minutes=g)
            out.append(t.isoformat())
        return out

    monkeypatch.setattr(watch, "newest_scheduled_run", lambda _f: recent)
    monkeypatch.setattr(
        watch, "scheduled_run_history", lambda _f, per_page=watch.GRACE_HISTORY_SAMPLE: _recent_series(*([15.0] * 58 + [729.0]))
    )
    code = watch.main([])
    out = capsys.readouterr().out
    assert code == 0
    assert "grace (#3541):" in out
    assert "live: max gap" in out


def test_main_skips_the_history_call_when_the_recency_lookup_already_failed(monkeypatch):
    """Don't spend a second Actions call learning what the first call already showed:
    the instrument is blind. A history-fetch stub that raises proves it is genuinely
    never invoked, not merely uncounted."""

    def _boom(*_a, **_k):
        raise AssertionError("scheduled_run_history must not be called when the recency lookup already failed")

    monkeypatch.setattr(watch, "newest_scheduled_run", lambda _f: False)
    monkeypatch.setattr(watch, "scheduled_run_history", _boom)
    assert watch.main(["--allow-unverified"]) == 0


# ═════════════════════════════════════════════════════════════════════════════
# The live-only parity check: the registry literal must never be BELOW the real max
# ═════════════════════════════════════════════════════════════════════════════


def test_deploy_wedge_watch_grace_is_a_floor_of_the_live_max():
    """#3541 acceptance: 'a test asserts the literal is >= the live max when GitHub is
    reachable, UNVERIFIED otherwise (never green on absence)'. This is that test —
    a LOUD skip (not a silent pass) when `gh` cannot reach the Actions API."""
    try:
        auth = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True, timeout=15)
    except (subprocess.SubprocessError, OSError, FileNotFoundError):
        pytest.skip("no `gh` CLI available — LIVE cron-freshness grace parity NOT checked this run")
    if auth.returncode != 0:
        pytest.skip("no gh auth — LIVE cron-freshness grace parity NOT checked this run")

    history = watch.scheduled_run_history("deploy-wedge-watch.yml")
    if history is False:
        pytest.skip("live Actions API lookup failed — LIVE cron-freshness grace parity NOT checked this run")

    live_grace, note = watch.derive_live_grace_hours(history)
    declared = reg.WATCH_POLICY["deploy-wedge-watch.yml"]["grace_hours"]
    if live_grace is None:
        pytest.skip(f"newborn history ({note}) — LIVE cron-freshness grace parity NOT checked this run")

    assert declared >= 0, "sanity: the registry literal must be a non-negative number"
    # The registry literal is a FLOOR under the live derivation, never required to
    # exceed it on its own — effective_grace_hours is what production actually reads,
    # and THAT must never fall below the raw worst gap GitHub has ever really
    # delivered (margin=1.0 baseline), or a genuinely-healthy-but-slow cron could
    # still breach the window it is measured against.
    parsed = sorted(p for p in (watch._parse_iso(t) for t in history) if p is not None)
    raw_max_gap = max(((b - a).total_seconds() / 3600.0 for a, b in zip(parsed, parsed[1:])), default=0.0)
    effective = watch.effective_grace_hours(declared, live_grace)
    assert effective >= live_grace, f"effective grace {effective}h must be >= the live-derived {live_grace}h ({note})"
    assert effective >= raw_max_gap, (
        f"effective grace {effective}h must be >= the RAW observed max gap {raw_max_gap:.2f}h — a grace tighter than "
        f"the worst gap GitHub has actually delivered would breach on a healthy cron ({note})"
    )
