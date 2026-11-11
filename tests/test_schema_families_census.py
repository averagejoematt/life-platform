"""tests/test_schema_families_census.py — docs/SCHEMA.md cannot drift from the live table (#3514, DA-10).

THE DEFECT
  CLAUDE.md calls `docs/SCHEMA.md` "authoritative". On 2026-09-05 five live pk families had
  zero mentions in it. The same class was hand-closed on 2026-08-22 (#2810) and left no
  ratchet, so it reopened within two weeks — which is the actual finding: the problem was
  never the five families, it was that nothing could tell you there were five.

TWO LEGS, because neither alone is enough
  A. CODE-DERIVED (never stale, runs everywhere): every key in
     `phase_taxonomy.SOURCE_CLASS` must appear in SCHEMA.md. This catches a family the
     moment it is CLASSIFIED, which is before it has written a single row — the earliest
     possible point, and the one ADR-154's ordering asks for.
  B. LIVE-DERIVED (measured, refreshed at reset): every family in
     `deploy/generated/pk_family_census.json` must appear. CI has no DynamoDB credentials,
     so the live measurement is taken where credentials exist — the reset's Step [0], or
     `python3 deploy/write_pk_family_census.py` — committed as an artifact, and graded here.
     This catches a family that exists in the TABLE without a SOURCE_CLASS entry of its own
     (a top-level pk like `PULSE`, which leg A cannot see at all).

  Leg A can go wrong by the code lying about the table; leg B can go wrong by going stale.
  Together they bracket it: a new family has to evade a check that reads the code AND a
  check that read the table.

THE SNAPSHOT HAS A CEILING (#5524)
  Leg B was "refreshed at reset", and no reset will come (cycle 17 is terminal). The census
  was 49 days old and 15 families behind the table when #5524 measured it. It is now refreshed
  on the wrap's cadence — `scripts/wrap_gates.py`'s `pk-census` gather gate runs
  `deploy/write_pk_family_census.py --refresh-if-older-than-days 28`, which re-scans only when
  the artifact is 28+ days old and keeps the refresh only if this file's readers still pass —
  and `test_the_census_is_not_older_than_the_ceiling` below reds at 35 days, a week after the
  wrap would have refreshed it.

THE EXEMPTION REGISTRY IS EMPTY, AND THAT IS THE POINT
  Every family known to this repo is documented as of 2026-09-18. An exemption here is a
  written admission that a load-bearing partition is undocumented; it is not a place to
  put "not yet". If this dict grows, the reason column is the review.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "lambdas"))

from experiment import (
    phase_taxonomy as taxonomy,  # noqa: E402
    pk_census,  # noqa: E402
)

# #5524: the census snapshot's age ceiling. The wrap refreshes at 28 days; this reds at 35.
MAX_CENSUS_AGE_DAYS = 35

SCHEMA = REPO_ROOT / "docs" / "SCHEMA.md"
CENSUS = REPO_ROOT / "deploy" / "generated" / "pk_family_census.json"

# family/source -> the written reason it is undocumented. Keep it empty.
#
# Named to match none of `gate_census._REGISTRY_NAME`'s patterns, for the reason
# `gate_census_enforcement.NOT_APPLICABLE_REASONS` carries: a registry-shaped name in a
# test file is expanded entry-by-entry by the census's family-3 walk into one phantom
# verdict-less gate per row. This dict holds EXEMPTIONS FROM a gate, not gates.
UNDOCUMENTED_FAMILY_REASONS: dict[str, str] = {}


def _schema_text() -> str:
    return SCHEMA.read_text(encoding="utf-8")


def _mentioned(token: str, text: str) -> bool:
    """A word-boundary match, not a substring one.

    `token in text` reports `labs` as documented because `syllabus` contains it, and reports
    `PULSE` as MISSING when the search term is built as `PULSE#` but the pk is the bare
    string `PULSE`. Both of those were live mistakes while measuring this gap, in opposite
    directions — a false clean and a false red — which is why the matcher is pinned by a
    test of its own below."""
    return re.search(r"(?<![A-Za-z0-9_])" + re.escape(token) + r"(?![A-Za-z0-9_])", text) is not None


def _token_for(family: str) -> str:
    """The string SCHEMA.md would name this family by: a `SOURCE#<x>` family is written as
    `…SOURCE#<x>` (so `<x>` is the distinguishing part); a per-user `USER#<x>` family (#5524 —
    `pk_census.pk_family` keys `USER#<u>#<x>` by <x>) is written with its user, `USER#matthew#<x>`,
    the only user the table has partitions for; any other family IS its own pk."""
    if family.startswith("SOURCE#"):
        return family.split("SOURCE#", 1)[1]
    if family.startswith("USER#"):
        return f"USER#matthew#{family.split('#', 1)[1]}"
    return family


# ── the matcher itself ───────────────────────────────────────────────────────


def test_the_matcher_is_neither_a_substring_nor_a_suffix_match():
    """Pinned because both failure directions actually happened while measuring this gap."""
    assert _mentioned("labs", "the labs partition")
    assert not _mentioned("labs", "a syllabus of topics")  # substring false-positive
    assert _mentioned("PULSE", "| `PULSE` / `DATE#<d>` |")  # bare pk, no trailing '#'
    assert not _mentioned("nope", "| `PULSE` / `DATE#<d>` |")


# ── leg A: code-derived ──────────────────────────────────────────────────────


def test_every_classified_source_is_documented():
    text = _schema_text()
    missing = sorted(s for s in taxonomy.SOURCE_CLASS if not _mentioned(s, text) and s not in UNDOCUMENTED_FAMILY_REASONS)
    assert not missing, (
        f"{len(missing)} source(s) are classified in phase_taxonomy.SOURCE_CLASS and appear nowhere in "
        f"docs/SCHEMA.md, which CLAUDE.md calls authoritative: {missing}. Add a row to the matching "
        "key-family table, or register the exemption with the reason it is acceptable."
    )


def test_leg_a_is_not_vacuous():
    """A typo'd attribute or an emptied registry would make the assertion above trivially
    true. Grade the checker against a token that is definitely absent."""
    assert len(taxonomy.SOURCE_CLASS) > 50, f"SOURCE_CLASS looks wrong: {len(taxonomy.SOURCE_CLASS)} entries"
    assert not _mentioned("zzz_not_a_real_source", _schema_text())


# ── leg B: live-derived ──────────────────────────────────────────────────────


def test_the_census_artifact_exists_and_is_not_empty():
    assert CENSUS.exists(), (
        f"{CENSUS.relative_to(REPO_ROOT)} is missing — leg B has nothing to grade against. "
        "Refresh it with: python3 deploy/write_pk_family_census.py"
    )
    snap = json.loads(CENSUS.read_text(encoding="utf-8"))
    assert snap.get("families"), "the committed census has ZERO families — a vacuous artifact passes every check below"
    assert snap.get("generated_at"), "the census carries no generated_at, so a reader cannot tell how old the measurement is"
    assert int(snap.get("family_count") or 0) == len(snap["families"]), "family_count disagrees with the families it counts"


def test_every_live_family_is_documented():
    snap = json.loads(CENSUS.read_text(encoding="utf-8"))
    text = _schema_text()
    missing = sorted(f for f in snap["families"] if not _mentioned(_token_for(f), text) and f not in UNDOCUMENTED_FAMILY_REASONS)
    assert not missing, (
        f"{len(missing)} live pk family/families appear nowhere in docs/SCHEMA.md: {missing}. These are "
        f"partitions the table HOLDS (census taken {snap.get('generated_at')})."
    )


def test_every_live_family_classifies():
    """The census records the class it resolved to. A null there is an ADR-077 totality
    violation that would abort the next reset at Step [0] — surfaced here at PR time too,
    against the last measured census, rather than only when someone types a reset."""
    snap = json.loads(CENSUS.read_text(encoding="utf-8"))
    unresolved = sorted(f for f, v in snap["families"].items() if not v.get("class"))
    assert not unresolved, f"unclassified live families in the census: {unresolved}"


def test_the_census_families_still_classify_against_TODAYS_taxonomy():
    """The artifact records what classify() said WHEN IT WAS TAKEN. This re-runs the live
    classifier over each recorded representative, so removing a rule from phase_taxonomy
    reds here even though the stale artifact still claims a class."""
    snap = json.loads(CENSUS.read_text(encoding="utf-8"))
    broken = []
    for fam, v in sorted(snap["families"].items()):
        try:
            taxonomy.classify(v["rep_pk"], v.get("rep_sk", ""))
        except KeyError as e:
            broken.append(f"{fam} ({e})")
    assert not broken, f"families the CURRENT taxonomy can no longer classify: {broken}"


# ── #5524: the snapshot's age ────────────────────────────────────────────────


def census_age_days(snap: dict, today: date) -> int:
    """Whole days from the snapshot's `generated_at` (a UTC instant) to `today` (a UTC date)."""
    taken = datetime.fromisoformat(snap["generated_at"]).astimezone(timezone.utc).date()
    return (today - taken).days


def test_the_census_is_not_older_than_the_ceiling():
    """A snapshot grading a world that moved is the failure leg B exists to prevent."""
    snap = json.loads(CENSUS.read_text(encoding="utf-8"))
    # utc-exempt(#5524): `generated_at` is a UTC instant stamped by the scan, so the age
    # is taken in the frame that named it (the #3257 rule the 3669 census test follows).
    age = census_age_days(snap, datetime.now(timezone.utc).date())
    assert age >= 0, f"census generated_at {snap['generated_at']} is in the future — the artifact was hand-edited"
    assert age <= MAX_CENSUS_AGE_DAYS, (
        f"the pk-family census is {age} days old (generated {snap['generated_at']}, ceiling {MAX_CENSUS_AGE_DAYS}d). "
        "The wrap's `pk-census` gate refreshes it at 28 days; run it by hand (read-only scan, writes one file): "
        "python3 deploy/write_pk_family_census.py"
    )


def test_the_age_ceiling_reds_on_a_stale_snapshot():
    """Must-fail control, clock pinned: 36 days old is red, 35 is not."""
    snap = {"generated_at": "2026-09-22T03:45:37.645533+00:00"}
    assert census_age_days(snap, date(2026, 10, 28)) == 36 > MAX_CENSUS_AGE_DAYS
    assert census_age_days(snap, date(2026, 10, 27)) == 35 <= MAX_CENSUS_AGE_DAYS


# ── #5524: the refresh cadence (the wrap's pk-census gate) ──────────────────


def _writer(monkeypatch, tmp_path, generated_at):
    sys.path.insert(0, str(REPO_ROOT / "deploy"))
    import write_pk_family_census as w

    art = tmp_path / "pk_family_census.json"
    art.write_text(json.dumps({"generated_at": generated_at, "families": {"SOURCE#whoop": {}}}), encoding="utf-8")
    monkeypatch.setattr(w, "ARTIFACT", art)
    return w, art


class _Proc:
    def __init__(self, rc):
        self.returncode, self.stdout = rc, "1 failed" if rc else "ok"


def _fresh_snap():
    return {"generated_at": "2026-11-10T00:00:00+00:00", "family_count": 2, "families": {"SOURCE#whoop": {}, "SOURCE#new": {}}}


def test_refresh_is_a_no_op_while_the_artifact_is_young(monkeypatch, tmp_path):
    w, _ = _writer(monkeypatch, tmp_path, datetime.now(timezone.utc).isoformat())

    def no_scan():
        raise AssertionError("a fresh artifact must not be scanned")

    assert w.refresh_if_stale(28, scan=no_scan) == 0


def test_a_stale_refresh_is_kept_when_every_reader_passes(monkeypatch, tmp_path):
    w, art = _writer(monkeypatch, tmp_path, "2026-01-01T00:00:00+00:00")
    assert w.refresh_if_stale(28, scan=_fresh_snap, run=lambda *a, **k: _Proc(0)) == 0
    assert "SOURCE#new" in json.loads(art.read_text(encoding="utf-8"))["families"]


def test_a_stale_refresh_that_reds_a_reader_is_rolled_back_and_reds(monkeypatch, tmp_path):
    """The must-fail control for the cadence: a refresh that would red main is never kept."""
    w, art = _writer(monkeypatch, tmp_path, "2026-01-01T00:00:00+00:00")
    before = art.read_bytes()
    assert w.refresh_if_stale(28, scan=_fresh_snap, run=lambda *a, **k: _Proc(1)) == 1
    assert art.read_bytes() == before, "a refresh the readers reject must restore the previous bytes"


def test_no_credentials_is_unverified_not_a_crash(monkeypatch, tmp_path, capsys):
    w, _ = _writer(monkeypatch, tmp_path, "2026-01-01T00:00:00+00:00")

    class NoCredentialsError(Exception):
        pass

    NoCredentialsError.__module__ = "botocore.exceptions"

    def boom():
        raise NoCredentialsError("Unable to locate credentials")

    assert w.refresh_if_stale(28, scan=boom) == 0
    assert "UNVERIFIED" in capsys.readouterr().out


def test_the_reader_derivation_is_not_vacuous():
    sys.path.insert(0, str(REPO_ROOT / "deploy"))
    import write_pk_family_census as w

    readers = w.census_reader_tests()
    assert "tests/test_schema_families_census.py" in readers and len(readers) >= 5, readers


# ── #5524: every per-user partition is its own family ───────────────────────


def test_pk_family_keys_a_per_user_partition_by_its_own_segment():
    assert pk_census.pk_family("USER#matthew#MCP_IDEMPOTENCY") == "USER#MCP_IDEMPOTENCY"
    assert pk_census.pk_family("USER#matthew#MEMORY") == "USER#MEMORY"
    assert pk_census.pk_family("USER#matthew#ROUTINE#v12") == "USER#ROUTINE"
    assert pk_census.pk_family("USER#matthew") == "USER"
    assert pk_census.pk_family("USER#system") == "USER"
    assert pk_census.pk_family("USER#matthew#SOURCE#whoop") == "SOURCE#whoop"
    assert pk_census.pk_family("COACH#sleep_coach") == "COACH"


class _FakeTable:
    def __init__(self, items):
        self.items = items

    def scan(self, **_kwargs):
        return {"Items": list(self.items)}


def test_a_new_per_user_partition_is_unresolved_not_hidden_behind_routine():
    """The must-fail fixture for (a). A ROUTINE# row is scanned FIRST — under the old keying it
    was the one representative of family 'USER', so the unclassified partition behind it was
    never classified. Each per-user partition must now surface as its own family."""
    table = _FakeTable(
        [
            {"pk": "USER#matthew#ROUTINE#v1", "sk": "IR"},
            {"pk": "USER#matthew#NOT_A_REAL_PARTITION_5524", "sk": "X"},
            {"pk": "USER#matthew#MCP_IDEMPOTENCY", "sk": "create_todoist_task#abc"},
        ]
    )
    unresolved, count = pk_census.unresolved_families(table)
    assert count == 3
    assert [u[0] for u in unresolved] == ["USER#NOT_A_REAL_PARTITION_5524"], unresolved


def test_mcp_idempotency_is_classified_and_documented():
    assert taxonomy.classify("USER#matthew#MCP_IDEMPOTENCY", "create_todoist_task#abc") == taxonomy.SYSTEM_STATE
    assert _mentioned(_token_for("USER#MCP_IDEMPOTENCY"), _schema_text())


def test_the_exemption_registry_is_documented_when_used():
    for fam, reason in UNDOCUMENTED_FAMILY_REASONS.items():
        assert isinstance(reason, str) and len(reason) >= 25, f"{fam}: an exemption needs a real written reason, got {reason!r}"


# premerge-gate: 3514: grades docs/SCHEMA.md against the committed pk-family census, which deploy/write_pk_family_census.py regenerates — a PR that lands a refreshed artifact must red on that PR, not on whoever pushes next (#2975).
