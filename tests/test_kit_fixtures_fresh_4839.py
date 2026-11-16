"""#4839 — the committed kit page captures: fresh while live, locked once frozen (owner ruling 2026-11-13).

The kit page gate and the kit JS tests render committed captures of the site's routes
(tests/fixtures/kit_pages_4586/, written only by scripts/capture_kit_page_fixtures.py), and the edition
tests compose the edition's wire (tests/fixtures/edition_wire_4582/) captured in the same pass.

Until 2026-11-13 both had to be no more than 30 days old. The owner then froze them as historical evidence
(ADR-166: the v8 kit they describe was superseded by the v9 build and survives only at /next/v8/, noindex).
A frozen directory's ``_capture.json`` carries a ``frozen`` block — the day, the reason and a sha256 per file —
and the holds are now:

(1) a FROZEN directory is held to its lock: every file it names is present with that hash, and no file sits
    beside them unnamed, so the 10-18 evidence can neither drift nor be lost; the age rule does not apply;
(2) an UNFROZEN directory still meets the 30-day age rule against the real clock (the rule itself is proven on
    a frozen clock below, with no literal expectation passed through the live clock, #4848);
(3) the "Last recaptured" line in the script's docstring names the manifest's day;
(4) #4864: the edition wire names the SAME capture instant as the kit manifest, and one file per ``SOURCES``
    key of lambdas/web/site_api_edition.py sits beside it.

What keeps the LIVE API honest now is tests/test_live_contract_shapes_fresh.py (the shape baselines of every
route the v9 build reads, 30 days, recaptured by ritual ``live-contract-recapture``).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import capture_kit_page_fixtures as cap  # noqa: E402

MANIFEST = os.path.join(cap.FIXTURES_DIR, cap.MANIFEST)
WIRE_MANIFEST = os.path.join(cap.WIRE_DIR, cap.MANIFEST)
CAPTURE_DIRS = (cap.FIXTURES_DIR, cap.WIRE_DIR)


def _manifest(d: str) -> dict:
    with open(os.path.join(d, cap.MANIFEST), encoding="utf-8") as fh:
        return json.load(fh)


def _captured_at() -> str:
    return _manifest(cap.FIXTURES_DIR)["captured_at"]


def lock_problems(d: str) -> list:
    """Every way a frozen directory has left its lock (empty when it holds)."""
    lock = (_manifest(d).get("frozen") or {}).get("sha256") or {}
    on_disk = sorted(n for n in os.listdir(d) if n != cap.MANIFEST)
    problems = [f"{n}: not in the lock" for n in on_disk if n not in lock]
    for name, want in sorted(lock.items()):
        path = os.path.join(d, name)
        if not os.path.exists(path):
            problems.append(f"{name}: locked but missing")
            continue
        with open(path, "rb") as fh:
            if hashlib.sha256(fh.read()).hexdigest() != want:
                problems.append(f"{name}: changed since it was frozen")
    return problems


def test_the_age_rule_on_a_frozen_clock():
    taken = "2026-10-12T15:35:22Z"
    at = datetime(2026, 10, 12, 15, 35, 22, tzinfo=timezone.utc)
    assert cap.age_days(taken, at) == 0
    assert cap.age_days(taken, at + timedelta(days=29, hours=23)) < cap.MAX_AGE_DAYS
    assert cap.age_days(taken, at + timedelta(days=30, hours=1)) > cap.MAX_AGE_DAYS
    assert cap.MAX_AGE_DAYS == 30


def test_both_capture_directories_are_frozen_with_a_dated_reason():
    """The owner's 2026-11-13 ruling, as data: both sets are historical, each says so and why."""
    for d in CAPTURE_DIRS:
        frozen = _manifest(d).get("frozen")
        assert frozen, f"{os.path.relpath(d, ROOT)} has no frozen block"
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", frozen.get("on") or ""), "the freeze is dated"
        assert "ADR-166" in (frozen.get("why") or ""), "the freeze names its reason"
        assert frozen.get("sha256"), "the freeze locks its files"


@pytest.mark.parametrize("d", CAPTURE_DIRS, ids=lambda d: os.path.basename(d))
def test_a_frozen_directory_holds_to_its_lock(d):
    if not _manifest(d).get("frozen"):
        pytest.skip("not frozen — the age rule below holds it instead")
    problems = lock_problems(d)
    assert not problems, f"{os.path.relpath(d, ROOT)} left its 2026-11-13 lock: {problems}"


def test_the_lock_check_reds_a_changed_a_missing_and_an_extra_file(tmp_path):
    """Negative control: the lock check is not vacuous."""
    (tmp_path / "a.json").write_text("{}\n")
    (tmp_path / "b.json").write_text("[]\n")
    lock = {n: hashlib.sha256((tmp_path / n).read_bytes()).hexdigest() for n in ("a.json", "b.json")}
    (tmp_path / cap.MANIFEST).write_text(json.dumps({"frozen": {"on": "2026-11-13", "why": "x", "sha256": lock}}))
    assert lock_problems(str(tmp_path)) == []
    (tmp_path / "a.json").write_text('{"x": 1}\n')
    (tmp_path / "b.json").unlink()
    (tmp_path / "c.json").write_text("{}\n")
    assert lock_problems(str(tmp_path)) == ["c.json: not in the lock", "a.json: changed since it was frozen", "b.json: locked but missing"]


def test_the_capture_script_refuses_to_write_a_frozen_directory(tmp_path):
    (tmp_path / cap.MANIFEST).write_text(json.dumps({"captured_at": "2026-10-18T07:15:07Z", "frozen": {"on": "2026-11-13"}}))
    with pytest.raises(SystemExit, match="FROZEN"):
        cap.write({"x.json": {}}, {"x.json": "/api/x"}, "2026-11-13T00:00:00Z", cap.BASE, str(tmp_path))
    with pytest.raises(SystemExit, match="FROZEN"):
        cap.write_wire({"x": {}}, {"x": "/api/x"}, "2026-11-13T00:00:00Z", cap.BASE, str(tmp_path))
    assert sorted(os.listdir(tmp_path)) == [cap.MANIFEST], "nothing was written"


def test_an_unfrozen_capture_is_not_older_than_thirty_days():
    live = [d for d in CAPTURE_DIRS if not _manifest(d).get("frozen")]
    for d in live:
        taken = _manifest(d)["captured_at"]
        age = cap.age_days(taken, datetime.now(timezone.utc))
        assert age <= cap.MAX_AGE_DAYS, (
            f"{os.path.relpath(d, ROOT)} was captured {taken}, {age:.0f} days ago (limit {cap.MAX_AGE_DAYS}). "
            "Re-run `python3 scripts/capture_kit_page_fixtures.py`, re-pin anything it reds, and update the "
            "'Last recaptured' line in the script's docstring."
        )


def test_the_docstring_date_is_the_manifests_date():
    said = re.search(r"Last recaptured: (\d{4}-\d{2}-\d{2})", cap.__doc__ or "")
    assert said, "scripts/capture_kit_page_fixtures.py has no 'Last recaptured: YYYY-MM-DD' line in its docstring"
    assert said.group(1) == _captured_at()[:10], f"docstring says {said.group(1)}, the manifest says {_captured_at()[:10]}"


def test_the_edition_wire_is_the_same_capture_as_the_kit_pages():
    """#4864: one capture date across both directories. The wire's own manifest names the kit manifest's instant,
    and one file per SOURCES key sits beside it (a source added without a recapture is a missing file)."""
    with open(WIRE_MANIFEST, encoding="utf-8") as fh:
        wire = json.load(fh)
    assert wire["captured_at"] == _captured_at(), "the wire and the kit pages were captured in different passes"
    sys.path.insert(0, os.path.join(ROOT, "lambdas"))
    from web import site_api_edition as ed

    assert set(wire["files"]) == set(ed.SOURCES), "the wire manifest names every edition source and nothing else"
    missing = [k for k in ed.SOURCES if not os.path.exists(os.path.join(cap.WIRE_DIR, f"{k}.json"))]
    assert not missing, f"wire files missing: {missing}"
