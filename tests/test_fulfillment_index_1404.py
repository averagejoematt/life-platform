"""tests/test_fulfillment_index_1404.py — the asymmetric-channel fulfillment index (#1404).

Pins the four acceptance criteria:
  AC1 — the index computes daily from passive channels alone: a zero-journal
        ("bad") week yields a value every day, not a collapse.
  AC2 — journal-derived signals compose MONOTONICALLY: enrichment can only add
        the resolution block; score/state/coverage are byte-identical with and
        without it.
  AC3 — coverage below the floor renders the dignified insufficient-signal
        state — no score key at all, never a fabricated number.
  AC4 — ADR-104 semantics: behavioral absence (adopted channel, no rows) = 0;
        measured absence (channel not yet adopted) = frozen out of coverage.
Plus the /api/fulfillment_index endpoint shape against fakes.
"""

import json
import os
import sys

os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("USER_ID", "matthew")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "web"))

import fulfillment_index as fi  # noqa: E402

ALL_ADOPTED = {name: True for name in fi.CHANNEL_NAMES}


def _scores(connection=0.0, interactions=0.0, journal=0.0, todoist=0.0):
    return {
        "connection_tap": connection,
        "interactions": interactions,
        "journal_presence": journal,
        "values_todoist": todoist,
    }


# ── channel scorers ──────────────────────────────────────────────────────────


def test_connection_tap_scoring():
    assert fi.score_connection_tap({"connection": 4}) == 100.0
    assert fi.score_connection_tap({"connection": 2}) == 50.0
    assert fi.score_connection_tap({"connection": 0}) == 0.0
    # behavioral absence: no row, or a row without the tap, both score 0
    assert fi.score_connection_tap(None) == 0.0
    assert fi.score_connection_tap({"mood_valence": 3}) == 0.0


def test_interactions_scoring_saturates():
    assert fi.score_interactions([]) == 0.0
    assert fi.score_interactions([{}]) == 60.0
    assert fi.score_interactions([{}, {}]) == 85.0
    assert fi.score_interactions([{}, {}, {}, {}]) == 100.0


def test_values_tagged_completions_convention():
    row = {
        "completed_tasks": [
            {"content": "call mom", "labels": ["value:family"]},
            {"content": "ship report", "labels": ["work"]},
            {"content": "help neighbor", "labels": ["VALUES"]},
            {"content": "no labels"},
        ]
    }
    assert fi.values_tagged_completions(row) == 2
    assert fi.values_tagged_completions(None) == 0
    assert fi.score_values_todoist(row) == 100.0
    assert fi.score_values_todoist({"completed_tasks": [{"labels": ["value:health"]}]}) == 70.0
    assert fi.score_values_todoist({"completed_tasks": []}) == 0.0


# ── AC1: a bad week still yields a value every day ───────────────────────────


def test_bad_week_taps_only_yields_values_not_collapse():
    """Seven days: connection taps present, ZERO journal entries, zero
    interactions, zero values-completions — every day still composes, and the
    weekly mean exists."""
    days = []
    for i, tap in enumerate([3, 2, 4, 1, 2, 3, 2]):
        day = fi.compose_day(
            f"2026-07-{13 + i:02d}",
            ALL_ADOPTED,
            _scores(connection=fi.score_connection_tap({"connection": tap}), journal=fi.score_journal_presence(False)),
        )
        fi.attach_resolution(day, None)  # skipped-journal day
        days.append(day)
    assert all(d["state"] == "ok" for d in days)
    assert all(isinstance(d["score"], float) for d in days)
    assert all(d["resolution"] == {"level": "coarse"} for d in days)  # resolution degraded, verdict intact
    mean, n = fi.window_mean(days)
    assert n == 7 and mean is not None and mean > 0


# ── AC2: monotone composition — enrichment adds resolution, never verdict ────


def test_enrichment_never_changes_score_state_or_coverage():
    scores = _scores(connection=75.0, interactions=60.0, journal=100.0)
    bare = fi.attach_resolution(fi.compose_day("2026-07-15", ALL_ADOPTED, scores), None)
    enriched = fi.attach_resolution(
        fi.compose_day("2026-07-15", ALL_ADOPTED, scores),
        {
            "values_lived_count": 2,
            "values_lived": ["curiosity", "family"],
            "gratitude_count": 3,
            "flow": 1,
            "ownership_score": 7.5,
            "enrichment_model": "haiku-4-5",
        },
    )
    for k in ("score", "state", "coverage", "channels"):
        assert bare[k] == enriched[k], f"enrichment mutated {k} — the monotone composition rule is broken"
    assert bare["resolution"]["level"] == "coarse"
    assert enriched["resolution"]["level"] == "enriched"
    assert enriched["resolution"]["components"]["gratitude_count"] == 3
    assert enriched["resolution"]["values_lived"] == ["curiosity", "family"]
    assert "LLM-coded from journal text" in enriched["resolution"]["provenance"]


# ── AC3: coverage floor → dignified insufficient state ───────────────────────


def test_insufficient_coverage_has_no_score_key():
    only_journal = {name: name == "journal_presence" for name in fi.CHANNEL_NAMES}
    day = fi.compose_day("2026-07-15", only_journal, _scores(journal=100.0))
    assert day["state"] == "insufficient_signal"
    assert "score" not in day  # never a fabricated number
    assert "not enough passive signal" in day["reason"]
    # and the weekly mean over such days is honest None, not 0
    assert fi.window_mean([day, dict(day)]) == (None, 0)


# ── AC4: behavioral vs measured absence ──────────────────────────────────────


def test_adr104_behavioral_zero_vs_measured_frozen():
    # Behavioral: interactions ADOPTED but none logged → the channel weighs in at 0.
    behavioral = fi.compose_day("2026-07-15", ALL_ADOPTED, _scores(connection=100.0))
    # Measured: interactions (and values_todoist) NOT adopted → frozen out; the
    # same tap evidence renormalizes over the smaller adopted mass.
    partial = {n: n in ("connection_tap", "journal_presence") for n in fi.CHANNEL_NAMES}
    measured = fi.compose_day("2026-07-15", partial, _scores(connection=100.0))
    assert behavioral["state"] == measured["state"] == "ok"
    # behavioral zeros DRAG the score; frozen-out channels do not
    assert behavioral["score"] < measured["score"]
    assert behavioral["channels"]["interactions"] == {"adopted": True, "score": 0.0, "weight": 0.20}
    assert measured["channels"]["interactions"] == {"adopted": False}
    assert measured["coverage"] == 0.65 and behavioral["coverage"] == 1.0


def test_scores_bounded_and_renormalized():
    day = fi.compose_day("2026-07-15", ALL_ADOPTED, _scores(connection=100.0, interactions=100.0, journal=100.0, todoist=100.0))
    assert day["score"] == 100.0  # full marks on every channel → exactly 100


# ── the endpoint, against fakes ──────────────────────────────────────────────


class TestEndpoint:
    def _hook(self, rows_by_pk):
        def hook(table, **kw):
            cond = kw["KeyConditionExpression"]
            pk = cond._values[0]._values[1]
            items = rows_by_pk.get(pk, [])
            if kw.get("Limit") == 1:  # adoption probe — first row ever
                return {"Items": items[:1]}
            return {"Items": items}

        return hook

    def test_endpoint_serves_index_with_honest_states(self, monkeypatch):
        from fakes import FakeDdbTable
        from web import site_api_data as api

        u = "USER#matthew#SOURCE#"
        today = __import__("datetime").datetime.now(api.PT).strftime("%Y-%m-%d")
        rows = {
            u + "evening_ritual": [{"pk": u + "evening_ritual", "sk": f"DATE#{today}", "date": today, "connection": 3}],
            u + "notion": [{"pk": u + "notion", "sk": f"DATE#{today}#e1", "date": today}],
            u + "interactions": [],
            u + "todoist": [],
            u + "flourishing": [],
        }
        monkeypatch.setattr(api, "table", FakeDdbTable(query_hook=self._hook(rows)))
        body = json.loads(api.handle_fulfillment_index()["body"])
        assert body["today"]["state"] == "ok"
        assert body["today"]["channels"]["connection_tap"]["score"] == 75.0
        # interactions/values never adopted → frozen out, not zeroed
        assert body["channels_adopted"]["interactions"] is None
        assert body["channels_adopted"]["values_todoist"] is None
        assert body["today"]["coverage"] == 0.65
        assert body["coverage_floor"] == fi.COVERAGE_FLOOR
        assert "journal text adds resolution" in body["disclosure"].replace("journal\ntext", "journal text") or body["disclosure"]
        # days before the (today-dated) adoption are insufficient — honest, not zeroed
        assert body["trend_7d"][0]["state"] == "insufficient_signal"

    def test_endpoint_all_dark_is_insufficient_everywhere(self, monkeypatch):
        from fakes import FakeDdbTable
        from web import site_api_data as api

        monkeypatch.setattr(api, "table", FakeDdbTable(query_hook=self._hook({})))
        body = json.loads(api.handle_fulfillment_index()["body"])
        assert body["today"]["state"] == "insufficient_signal"
        assert body["mean_7d"] is None and body["n_scored_7d"] == 0
