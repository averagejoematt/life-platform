"""tests/test_mcp_tools_hevy_behavior.py — behavioural contracts for
``mcp/tools_hevy.py`` (#1658 coverage tranche 5).

Measured 11% covered before this file: every line of the legacy-aggregate
bridge, the uid synthesis, the projection and both public tools were
un-exercised. That matters because this module is what answers "what did I
lift" in Claude Desktop, and the *bridge* half of it invents identifiers that
nothing else in the repo validates.

What is pinned here:

  * **Unit conversion is one direction and one factor.** Legacy aggregates
    store ``weight_lbs``; the module publishes ``total_volume_kg``. The factor
    is the exact lbs→kg 0.45359237, applied per set, and a set missing either
    weight or reps contributes nothing rather than a fabricated 0 (ADR-104).
  * **uid synthesis is stable and content-addressed** — same content, same
    uid, across processes; different start_time or title, different uid. That
    property is the whole dedupe story in §3.4 of the SPEC, and it is asserted
    on the real function, not a re-implementation.
  * **Dedupe is by workout_uid across BOTH read paths** — a per-workout record
    and a legacy expansion that collide on uid yield one row, and the
    per-workout record wins because it is read first.
  * **A source that raises is not a source that returns nothing silently
    wrong** — ``tool_get_workouts`` swallows per-source errors by design, so
    the surviving source's rows must still be complete.
  * **Ordering and the count/total split** — ``count`` is the length of the
    truncated page, ``total`` the full match count; a caller that reads
    ``count`` as "how many workouts happened" is reading a page size.

Arithmetic expectations are hand-derived in the test body with the derivation
shown, never "whatever the code returned". No AWS, no network: the two DDB
entry points (``query_source_range`` and ``table``) are replaced with bounded
fakes.
"""

from __future__ import annotations

import os

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")  # mcp.config requires these at import
os.environ.setdefault("USER_ID", "matthew")

from datetime import timedelta  # noqa: E402

import pytest  # noqa: E402
from common.pacific_time import pacific_now  # noqa: E402  # #2817: expectation in the module's own frame

from mcp import tools_hevy as th  # noqa: E402

LBS_TO_KG = 0.45359237


# ──────────────────────────────────────────────────────────────────────────────
# Fakes
# ──────────────────────────────────────────────────────────────────────────────


def _fake_range(by_source: dict[str, list[dict]], raises: set[str] = frozenset()):
    """Return a stand-in for core.query_source_range backed by a dict."""
    calls: list[tuple] = []

    def _q(source, start_date, end_date, include_pilot=False):
        calls.append((source, start_date, end_date, include_pilot))
        if source in raises:
            raise RuntimeError(f"DDB blew up for {source}")
        return list(by_source.get(source, []))

    _q.calls = calls  # type: ignore[attr-defined]
    return _q


def _per_workout(uid="hevy:w1", d="2026-08-05", **over):
    item = {
        "workout_uid": uid,
        "source": "hevy",
        "source_workout_id": uid.split(":", 1)[-1],
        "date": d,
        "title": "Push A",
        "start_time": f"{d}T17:00:00Z",
        "end_time": f"{d}T18:02:00Z",
        "duration_sec": 3720,
        "exercise_count": 4,
        "set_count": 14,
        "total_volume_kg": 4212.5,
        "original_unit": "kg",
        "adherence": {"status": "ad_hoc"},
        "exercises": [{"name": "Bench", "sets": [{"reps": 8}]}],
        "description": "felt strong",
        "raw_ref": "raw/hevy/w1.json",
    }
    item.update(over)
    return item


LEGACY_AGGREGATE = {
    "date": "2026-07-02",
    "workouts": [
        {
            "title": "  Legacy Pull  ",
            "start_time": " 2026-07-02T15:00:00Z ",
            "end_time": "2026-07-02T16:00:00Z",
            "duration_minutes": 62.5,
            "exercises": [
                {"name": "Row", "sets": [{"weight_lbs": 100, "reps": 10}, {"weight_lbs": 50, "reps": 5}]},
                # A set with no reps and a set with a non-numeric weight must
                # contribute 0 volume but still COUNT as a performed set.
                {"name": "Curl", "sets": [{"weight_lbs": 30}, {"weight_lbs": "heavy", "reps": 8}]},
            ],
        }
    ],
}


# ──────────────────────────────────────────────────────────────────────────────
# uid synthesis
# ──────────────────────────────────────────────────────────────────────────────


def test_content_uid_is_stable_and_content_addressed():
    a = th._content_uid("macrofactor_export", "2026-07-02", "Legacy Pull", "2026-07-02T15:00:00Z")
    b = th._content_uid("macrofactor_export", "2026-07-02", "Legacy Pull", "2026-07-02T15:00:00Z")
    assert a == b, "same content must produce the same uid — this IS the dedupe key"
    assert a.startswith("mf:")
    assert len(a) == len("mf:") + 16, "16 hex chars of sha256, per the docstring"

    # Any component change must move the uid.
    for changed in (
        th._content_uid("macrofactor_export", "2026-07-03", "Legacy Pull", "2026-07-02T15:00:00Z"),
        th._content_uid("macrofactor_export", "2026-07-02", "Legacy Push", "2026-07-02T15:00:00Z"),
        th._content_uid("macrofactor_export", "2026-07-02", "Legacy Pull", "2026-07-02T15:30:00Z"),
        th._content_uid("hevy", "2026-07-02", "Legacy Pull", "2026-07-02T15:00:00Z"),
    ):
        assert changed != a


def test_content_uid_strips_surrounding_whitespace_so_export_padding_does_not_fork_the_id():
    padded = th._content_uid("macrofactor_export", "2026-07-02", "  Legacy Pull  ", " 2026-07-02T15:00:00Z ")
    clean = th._content_uid("macrofactor_export", "2026-07-02", "Legacy Pull", "2026-07-02T15:00:00Z")
    assert padded == clean


def test_content_uid_tolerates_none_title_and_start_time():
    assert th._content_uid("macrofactor_export", "2026-07-02", None, None).startswith("mf:")


# ──────────────────────────────────────────────────────────────────────────────
# per-workout detection + projection
# ──────────────────────────────────────────────────────────────────────────────


def test_is_per_workout_record_keys_off_source_workout_id_only():
    assert th._is_per_workout_record({"source_workout_id": "abc"}) is True
    assert th._is_per_workout_record({"source_workout_id": ""}) is False
    assert th._is_per_workout_record({"workout_uid": "hevy:abc"}) is False, "a uid alone is not the new schema"
    assert th._is_per_workout_record({}) is False


def test_slim_workout_omits_set_detail_unless_asked():
    slim = th._slim_workout(_per_workout())
    assert "exercises" not in slim and "description" not in slim and "raw_ref" not in slim
    assert slim["total_volume_kg"] == 4212.5
    assert slim["adherence"] == {"status": "ad_hoc"}

    full = th._slim_workout(_per_workout(), include_sets=True)
    assert full["exercises"] == [{"name": "Bench", "sets": [{"reps": 8}]}]
    assert full["description"] == "felt strong"
    assert full["raw_ref"] == "raw/hevy/w1.json"


def test_slim_workout_reports_absent_adherence_as_none_not_zero():
    """ADR-104: a pre-#412 workout has no plan to grade against. None, never 0."""
    slim = th._slim_workout(_per_workout(adherence=None))
    assert slim["adherence"] is None
    assert "adherence" in slim, "the key must be present so callers can tell absent from missing"


# ──────────────────────────────────────────────────────────────────────────────
# legacy expansion
# ──────────────────────────────────────────────────────────────────────────────


def test_expand_legacy_aggregate_converts_lbs_to_kg_per_set():
    (w,) = th._expand_legacy_aggregate(LEGACY_AGGREGATE, "macrofactor_export")

    # Hand-derived: 100 lbs x 10 reps = 1000 lb-reps; 50 x 5 = 250 lb-reps.
    # The Curl sets contribute nothing (one has no reps, one has a
    # non-numeric weight) but both still count as performed sets.
    expected_kg = round((100 * 10 + 50 * 5) * LBS_TO_KG, 2)
    assert expected_kg == 566.99  # 1250 * 0.45359237 = 566.99046...
    assert w["total_volume_kg"] == expected_kg
    assert w["set_count"] == 4, "all four sets happened; only two carry volume"
    assert w["exercise_count"] == 2
    assert w["original_unit"] == "lbs"
    assert w["_legacy_aggregate"] is True


def test_expand_legacy_aggregate_converts_duration_minutes_to_seconds():
    (w,) = th._expand_legacy_aggregate(LEGACY_AGGREGATE, "macrofactor_export")
    assert w["duration_sec"] == 3750  # 62.5 min * 60


def test_expand_legacy_aggregate_leaves_duration_none_when_unparseable():
    src = {"date": "2026-07-02", "workouts": [{"title": "T", "duration_minutes": "about an hour"}]}
    (w,) = th._expand_legacy_aggregate(src, "macrofactor_export")
    assert w["duration_sec"] is None, "an unparseable duration is absent, not 0 (ADR-104)"
    assert w["set_count"] == 0
    assert w["total_volume_kg"] == 0.0


def test_expand_legacy_aggregate_skips_non_dict_entries_and_empty_partitions():
    assert th._expand_legacy_aggregate({}, "macrofactor_export") == []
    assert th._expand_legacy_aggregate({"date": "2026-07-02", "workouts": None}, "macrofactor_export") == []
    assert th._expand_legacy_aggregate({"date": "2026-07-02", "workouts": ["oops", 3]}, "macrofactor_export") == []


def test_expand_legacy_aggregate_labels_the_source_it_was_asked_for():
    (w,) = th._expand_legacy_aggregate(LEGACY_AGGREGATE, "macrofactor_export")
    assert w["source"] == "macrofactor_export"
    assert w["workout_uid"].startswith("mf:")
    assert w["source_workout_id"] == w["workout_uid"].split(":", 1)[-1]


# ──────────────────────────────────────────────────────────────────────────────
# tool_get_workouts
# ──────────────────────────────────────────────────────────────────────────────


@pytest.fixture()
def patched_range(monkeypatch):
    def _install(by_source, raises=frozenset()):
        q = _fake_range(by_source, raises)
        monkeypatch.setattr(th, "query_source_range", q)
        return q

    return _install


def test_get_workouts_defaults_to_a_30_day_window_ending_today(patched_range):
    patched_range({})
    out = th.tool_get_workouts({})
    today = (
        pacific_now().date()
    )  # #2817: tools_hevy keys days in the Pacific frame; date.today() is runner-local and reds on UTC runners 17:00-24:00 PT
    assert out["end_date"] == today.isoformat()
    assert out["start_date"] == (today - timedelta(days=30)).isoformat()
    assert out["source_filter"] is None


def test_get_workouts_queries_every_workout_source_when_unfiltered(patched_range):
    q = patched_range({})
    th.tool_get_workouts({"start_date": "2026-07-01", "end_date": "2026-08-01"})
    queried = [c[0] for c in q.calls]
    assert set(queried) == set(th._WORKOUT_SOURCES) | set(th._LEGACY_AGGREGATE_SOURCES)


def test_get_workouts_filter_restricts_both_the_native_and_the_legacy_read(patched_range):
    q = patched_range({})
    th.tool_get_workouts({"source": "  HEVY  ", "start_date": "2026-07-01", "end_date": "2026-08-01"})
    queried = [c[0] for c in q.calls]
    assert queried == ["hevy"], "a hevy filter must not fan out to the macrofactor legacy partition"


def test_get_workouts_filter_on_the_legacy_label_still_reaches_the_bridge(patched_range):
    q = patched_range({"macrofactor_workouts": [LEGACY_AGGREGATE]})
    out = th.tool_get_workouts({"source": "macrofactor_export", "start_date": "2026-07-01", "end_date": "2026-08-01"})
    assert [c[0] for c in q.calls] == ["macrofactor_export", "macrofactor_workouts"]
    assert out["total"] == 1
    assert out["workouts"][0]["_legacy_aggregate"] is True


def test_get_workouts_drops_old_daily_aggregates_from_the_native_partitions(patched_range):
    """A hevy row with no source_workout_id is the pre-2026-05-25 daily
    aggregate; the native path must not publish it as a workout."""
    patched_range({"hevy": [_per_workout(), {"date": "2026-05-01", "total_sets": 20}]})
    out = th.tool_get_workouts({"start_date": "2026-04-01", "end_date": "2026-08-08"})
    assert out["total"] == 1
    assert out["workouts"][0]["workout_uid"] == "hevy:w1"


def test_get_workouts_dedupes_by_uid_across_sources(patched_range):
    dup = _per_workout(uid="hevy:w1")
    patched_range({"hevy": [dup, dict(dup)], "macrofactor_export": [dup]})
    out = th.tool_get_workouts({"start_date": "2026-04-01", "end_date": "2026-08-08"})
    assert out["total"] == 1


def test_get_workouts_sorts_newest_first_by_date_then_start_time(patched_range):
    rows = [
        _per_workout(uid="hevy:a", d="2026-08-01"),
        _per_workout(uid="hevy:b", d="2026-08-05", start_time="2026-08-05T06:00:00Z"),
        _per_workout(uid="hevy:c", d="2026-08-05", start_time="2026-08-05T19:00:00Z"),
    ]
    patched_range({"hevy": rows})
    out = th.tool_get_workouts({"start_date": "2026-07-01", "end_date": "2026-08-08"})
    assert [w["workout_uid"] for w in out["workouts"]] == ["hevy:c", "hevy:b", "hevy:a"]


def test_get_workouts_count_is_the_page_and_total_is_the_match(patched_range):
    rows = [_per_workout(uid=f"hevy:{i}", d=f"2026-08-0{i}") for i in range(1, 6)]
    patched_range({"hevy": rows})
    out = th.tool_get_workouts({"start_date": "2026-07-01", "end_date": "2026-08-08", "limit": 2})
    assert out["count"] == 2
    assert out["total"] == 5
    assert len(out["workouts"]) == 2


def test_get_workouts_survives_one_source_erroring(patched_range):
    patched_range(
        {"hevy": [_per_workout()], "macrofactor_export": [_per_workout(uid="macrofactor_export:z")]}, raises={"macrofactor_export"}
    )
    out = th.tool_get_workouts({"start_date": "2026-07-01", "end_date": "2026-08-08"})
    assert out["total"] == 1
    assert out["workouts"][0]["workout_uid"] == "hevy:w1"


@pytest.mark.parametrize(
    "raw,expected_pilot",
    [
        (True, True),
        (False, False),
        ("false", False),
        ("FALSE", False),
        ("0", False),
        ("no", False),
        ("true", True),
        ("yes", True),
    ],
)
def test_get_workouts_include_pilot_string_coercion(patched_range, raw, expected_pilot):
    q = patched_range({})
    th.tool_get_workouts({"start_date": "2026-07-01", "end_date": "2026-08-01", "include_pilot": raw})
    assert all(c[3] is expected_pilot for c in q.calls)


def test_get_workouts_defaults_include_pilot_true_per_its_docstring(patched_range):
    q = patched_range({})
    th.tool_get_workouts({"start_date": "2026-07-01", "end_date": "2026-08-01"})
    assert all(c[3] is True for c in q.calls)


# ──────────────────────────────────────────────────────────────────────────────
# tool_get_workout_detail
# ──────────────────────────────────────────────────────────────────────────────


def test_get_workout_detail_rejects_missing_and_malformed_uids():
    assert th.tool_get_workout_detail({})["error"] == "workout_uid required"
    assert th.tool_get_workout_detail({"workout_uid": "   "})["error"] == "workout_uid required"
    assert "invalid workout_uid" in th.tool_get_workout_detail({"workout_uid": "abc123"})["error"]
    assert "unknown source" in th.tool_get_workout_detail({"workout_uid": "strava:abc"})["error"]


def test_get_workout_detail_returns_full_set_detail_for_a_known_uid(patched_range):
    patched_range({"hevy": [_per_workout(uid="hevy:w1")]})
    out = th.tool_get_workout_detail({"workout_uid": "HEVY:w1"})
    assert "workout" in out
    assert out["workout"]["exercises"] == [{"name": "Bench", "sets": [{"reps": 8}]}]


def test_get_workout_detail_looks_back_five_years_and_includes_pilot(patched_range):
    q = patched_range({})
    th.tool_get_workout_detail({"workout_uid": "hevy:nope"})
    source, start, end, include_pilot = q.calls[0]
    assert source == "hevy"
    assert include_pilot is True, "history predates genesis; detail must not hide it"
    today = (
        pacific_now().date()
    )  # #2817: tools_hevy keys days in the Pacific frame; date.today() is runner-local and reds on UTC runners 17:00-24:00 PT
    assert end == today.isoformat()
    assert start == (today - timedelta(days=5 * 365)).isoformat()


def test_get_workout_detail_reports_not_found_rather_than_an_empty_workout(patched_range):
    patched_range({"hevy": [_per_workout(uid="hevy:other")]})
    out = th.tool_get_workout_detail({"workout_uid": "hevy:w1"})
    assert out == {"error": "workout not found for uid 'hevy:w1'"}


def test_legacy_uid_from_get_workouts_round_trips_through_get_workout_detail(patched_range):
    """#2304: a uid this module MINTS must round-trip through its own detail
    lookup. Asserted as a property over the uids ``tool_get_workouts``
    actually returns — never a hand-typed uid string."""
    patched_range({"macrofactor_workouts": [LEGACY_AGGREGATE]})
    listed = th.tool_get_workouts({"source": "macrofactor_export", "start_date": "2026-07-01", "end_date": "2026-08-01"})
    assert listed["workouts"], "precondition: the legacy bridge listed at least one workout"

    for row in listed["workouts"]:
        uid = row["workout_uid"]
        detail = th.tool_get_workout_detail({"workout_uid": uid})
        assert "error" not in detail, detail
        assert detail["workout"]["workout_uid"] == uid
        # The sets the list tool advertised are the sets detail returns.
        assert detail["workout"]["exercises"] == row["exercises"]


def test_legacy_uid_detail_reports_not_found_for_an_unminted_legacy_hash(patched_range):
    patched_range({"macrofactor_workouts": [LEGACY_AGGREGATE]})
    out = th.tool_get_workout_detail({"workout_uid": "mf:0000000000000000"})
    assert out == {"error": "workout not found for uid 'mf:0000000000000000'"}


# ──────────────────────────────────────────────────────────────────────────────
# dead-code census (#1658 tranche 5) — resolved by #2304
# ──────────────────────────────────────────────────────────────────────────────


def test_dead_code_census_resolved_orphan_helper_and_phantom_tool_are_gone():
    """#1658 census recorded two facts: ``_latest_per_workout_record`` had no
    caller anywhere, and the module docstring advertised a third tool
    (``get_workout_source_status``) that does not exist. #2304 resolved both
    by deletion; this pins that neither quietly returns half-way (an orphan
    helper or a docstring promising an unshipped tool)."""
    assert not hasattr(th, "_latest_per_workout_record"), "orphan helper is back — give it a caller or delete it again"
    assert not hasattr(th, "tool_get_workout_source_status"), "third tool now exists — update this census and the docstring"
    assert "get_workout_source_status" not in (th.__doc__ or ""), "docstring re-advertises a tool that does not exist"
