"""tests/test_monday_compass_lambda.py — unit coverage for the Monday Compass
weekly-planning email lambda (#1658 coverage ratchet).

Everything here is offline and behavioral: no SES, no DDB, no Todoist HTTP, no
Bedrock. The module-level `ses`/`table`/`s3_client` handles are monkeypatched
per test, and every function that reads the wall clock gets a frozen
`datetime` (fixture dates + real `now()` is a time bomb — see
reference_golden_tests_wallclock).

What is pinned here (the module's own logic, not its collaborators'):
  - the DDB read helpers (pagination, phase filter, Decimal→float, ordering)
  - the Todoist client layer (request shaping, HTTP error translation, cursor
    pagination, project map, overdue/due de-duplication + normalization)
  - the pure shaping functions: pillar grouping, priority/due labels, week-state
    summary, week number, board-context selection
  - the prompt payload assembled for the model, and the email HTML wrapper's
    recovery-color thresholds
  - the handler's branches: no profile, AI failure fallback, AI-3 validator
    block, and the happy path (subject line, SES payload, status record, return
    body)

The presence-block injection contract is already pinned by
tests/test_presence_injection_emails.py — only its failure branch is added here.
"""

import io
import json
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal

os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("EMAIL_RECIPIENT", "matthew@example.com")
os.environ.setdefault("EMAIL_SENDER", "noreply@example.com")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "emails"))

import monday_compass_lambda as mc  # noqa: E402
import pytest  # noqa: E402
from common.constants import EXPERIMENT_BASELINE_WEIGHT_LBS  # noqa: E402
from fakes import FakeDdbTable  # noqa: E402

# Monday 2026-06-08 15:30 UTC — the cron's own firing slot (Mon 15:00 UTC).
_NOW = datetime(2026, 6, 8, 15, 30, tzinfo=timezone.utc)
TODAY = "2026-06-08"


class _FrozenDatetime(datetime):
    """datetime subclass with a fixed now(); strptime/strftime stay real."""

    @classmethod
    def now(cls, tz=None):
        return _NOW if tz is not None else _NOW.replace(tzinfo=None)


@pytest.fixture
def frozen_clock(monkeypatch):
    monkeypatch.setattr(mc, "datetime", _FrozenDatetime)
    return _NOW


# ═══════════════════════════════════════════════════════════════════════════
# Small hand-written doubles (never MagicMock — a non-terminating mock in a
# pagination loop has OOM'd this repo's CI runner before)
# ═══════════════════════════════════════════════════════════════════════════


class _PagedTable:
    """Serves a fixed list of query pages, then raises if over-consumed."""

    def __init__(self, pages):
        self.pages = list(pages)
        self.calls = []

    def query(self, **kwargs):
        self.calls.append(kwargs)
        if not self.pages:
            raise AssertionError("query() called more times than there are pages")
        return self.pages.pop(0)


class _FakeS3:
    def __init__(self, body=None, error=None):
        self.body = body
        self.error = error
        self.calls = []

    def get_object(self, Bucket=None, Key=None):
        self.calls.append((Bucket, Key))
        if self.error is not None:
            raise self.error
        return {"Body": io.BytesIO(self.body)}


class _FakeSes:
    def __init__(self):
        self.sent = []

    def send_email(self, **kwargs):
        self.sent.append(kwargs)
        return {"MessageId": "test-message-id"}


class _SeqTodoist:
    """Sequenced stand-in for `_todoist_request` — returns canned pages in
    order, then an empty terminal page (so a runaway loop can never spin)."""

    def __init__(self, pages, raise_on=None):
        self.pages = list(pages)
        self.raise_on = raise_on
        self.calls = []

    def __call__(self, method, path, payload=None, token=None):
        self.calls.append((method, path, token))
        if self.raise_on is not None and len(self.calls) >= self.raise_on:
            raise RuntimeError("todoist boom")
        if not self.pages:
            return {"results": [], "next_cursor": None}
        return self.pages.pop(0)


# ═══════════════════════════════════════════════════════════════════════════
# DDB read helpers
# ═══════════════════════════════════════════════════════════════════════════


class TestQuerySource:
    def test_paginates_converts_decimals_and_sorts_by_date(self, monkeypatch):
        fake = _PagedTable(
            [
                {"Items": [{"date": "2026-06-05", "day_grade": Decimal("82.5")}], "LastEvaluatedKey": {"pk": "x", "sk": "y"}},
                {"Items": [{"date": "2026-06-01", "day_grade": Decimal("70")}]},
            ]
        )
        monkeypatch.setattr(mc, "table", fake)

        items = mc.query_source("day_grade", "2026-06-01", "2026-06-08")

        assert [i["date"] for i in items] == ["2026-06-01", "2026-06-05"]
        assert items[1]["day_grade"] == 82.5
        assert isinstance(items[1]["day_grade"], float)
        assert len(fake.calls) == 2
        # page 2 must carry the continuation key; page 1 must not
        assert "ExclusiveStartKey" not in fake.calls[0]
        assert fake.calls[1]["ExclusiveStartKey"] == {"pk": "x", "sk": "y"}

    def test_applies_key_condition_and_phase_filter(self, monkeypatch):
        fake = _PagedTable([{"Items": []}])
        monkeypatch.setattr(mc, "table", fake)

        assert mc.query_source("whoop", "2026-06-01", "2026-06-08") == []

        kwargs = fake.calls[0]
        assert kwargs["ExpressionAttributeValues"][":pk"] == "USER#matthew#SOURCE#whoop"
        assert kwargs["ExpressionAttributeValues"][":s"] == "DATE#2026-06-01"
        assert kwargs["ExpressionAttributeValues"][":e"] == "DATE#2026-06-08"
        # ADR-058 default-deny: the phase filter is applied by with_phase_filter
        assert "#phase" in kwargs["FilterExpression"]


class TestQuerySourceLatest:
    def test_returns_newest_single_record_descending(self, monkeypatch):
        fake = _PagedTable([{"Items": [{"date": "2026-06-08", "readiness_score": Decimal("71")}]}])
        monkeypatch.setattr(mc, "table", fake)

        rec = mc.query_source_latest("computed_metrics")

        assert rec["readiness_score"] == 71.0
        assert fake.calls[0]["Limit"] == 1
        assert fake.calls[0]["ScanIndexForward"] is False

    def test_empty_partition_returns_empty_dict(self, monkeypatch):
        monkeypatch.setattr(mc, "table", _PagedTable([{"Items": []}]))
        assert mc.query_source_latest("computed_metrics") == {}


class TestFetchProfile:
    def test_reads_the_canonical_profile_key(self, monkeypatch):
        fake = FakeDdbTable(rows=[{"pk": "USER#matthew", "sk": "PROFILE#v1", "goal_weight_lbs": Decimal("210")}])
        monkeypatch.setattr(mc, "table", fake)

        assert mc.fetch_profile()["goal_weight_lbs"] == 210.0

    def test_absent_profile_is_an_empty_dict(self, monkeypatch):
        monkeypatch.setattr(mc, "table", FakeDdbTable())
        assert mc.fetch_profile() == {}


class TestLoadProjectPillarMap:
    def test_uses_s3_config_when_present(self, monkeypatch):
        fake = _FakeS3(body=json.dumps({"Deep Work": "mind"}).encode("utf-8"))
        monkeypatch.setattr(mc, "s3_client", fake)

        assert mc.load_project_pillar_map() == {"Deep Work": "mind"}
        assert fake.calls == [(mc.S3_BUCKET, "config/project_pillar_map.json")]

    def test_falls_back_to_defaults_when_s3_read_fails(self, monkeypatch):
        monkeypatch.setattr(mc, "s3_client", _FakeS3(error=RuntimeError("NoSuchKey")))

        result = mc.load_project_pillar_map()

        assert result is mc._DEFAULT_PROJECT_PILLAR_MAP
        assert result["Nutrition"] == "nutrition"


# ═══════════════════════════════════════════════════════════════════════════
# Todoist client layer
# ═══════════════════════════════════════════════════════════════════════════


class TestTodoistRequest:
    def test_get_shapes_request_and_parses_body(self, monkeypatch):
        captured = {}

        class _Resp:
            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *a):
                return False

            def read(self_inner):
                return b'{"results": [{"id": 1}]}'

        def _fake_urlopen(req, timeout=None):
            captured["url"] = req.full_url
            captured["method"] = req.get_method()
            captured["auth"] = req.get_header("Authorization")
            captured["data"] = req.data
            captured["timeout"] = timeout
            return _Resp()

        monkeypatch.setattr(mc.urllib.request, "urlopen", _fake_urlopen)

        out = mc._todoist_request("GET", "/tasks", token="tok-123")

        assert out == {"results": [{"id": 1}]}
        assert captured["url"] == "https://api.todoist.com/api/v1/tasks"
        assert captured["method"] == "GET"
        assert captured["auth"] == "Bearer tok-123"
        assert captured["data"] is None
        assert captured["timeout"] == 15

    def test_empty_body_returns_empty_dict_and_post_sends_json(self, monkeypatch):
        captured = {}

        class _Resp:
            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *a):
                return False

            def read(self_inner):
                return b""

        def _fake_urlopen(req, timeout=None):
            captured["data"] = req.data
            captured["method"] = req.get_method()
            return _Resp()

        monkeypatch.setattr(mc.urllib.request, "urlopen", _fake_urlopen)

        assert mc._todoist_request("POST", "/tasks", payload={"content": "x"}, token="t") == {}
        assert json.loads(captured["data"]) == {"content": "x"}
        assert captured["method"] == "POST"

    def test_http_error_becomes_runtime_error_carrying_status_and_body(self, monkeypatch):
        def _fake_urlopen(req, timeout=None):
            raise mc.urllib.error.HTTPError("https://api.todoist.com/api/v1/tasks", 429, "Too Many", {}, io.BytesIO(b"rate limited"))

        monkeypatch.setattr(mc.urllib.request, "urlopen", _fake_urlopen)

        with pytest.raises(RuntimeError) as exc:
            mc._todoist_request("GET", "/tasks", token="t")

        assert "429" in str(exc.value)
        assert "rate limited" in str(exc.value)


class TestFetchTasksWithFilter:
    def test_follows_cursor_until_exhausted(self, monkeypatch):
        seq = _SeqTodoist(
            [
                {"results": [{"id": 1}, {"id": 2}], "next_cursor": "abc"},
                {"results": [{"id": 3}], "next_cursor": None},
            ]
        )
        monkeypatch.setattr(mc, "_todoist_request", seq)

        tasks = mc._fetch_tasks_with_filter("overdue", "tok", limit=50)

        assert [t["id"] for t in tasks] == [1, 2, 3]
        assert len(seq.calls) == 2
        assert "filter=overdue" in seq.calls[0][1] and "limit=50" in seq.calls[0][1]
        assert "cursor=abc" in seq.calls[1][1]
        assert "cursor" not in seq.calls[0][1]

    def test_bare_list_response_is_accepted(self, monkeypatch):
        monkeypatch.setattr(mc, "_todoist_request", _SeqTodoist([[{"id": 7}]]))
        assert mc._fetch_tasks_with_filter("today", "tok") == [{"id": 7}]

    def test_request_failure_returns_pages_gathered_so_far(self, monkeypatch):
        seq = _SeqTodoist([{"results": [{"id": 1}], "next_cursor": "next"}], raise_on=2)
        monkeypatch.setattr(mc, "_todoist_request", seq)

        assert mc._fetch_tasks_with_filter("overdue", "tok") == [{"id": 1}]
        assert len(seq.calls) == 2

    def test_unexpected_payload_shape_breaks_without_raising(self, monkeypatch):
        monkeypatch.setattr(mc, "_todoist_request", _SeqTodoist([{"items": {"not": "a list"}}]))
        assert mc._fetch_tasks_with_filter("overdue", "tok") == []


class TestFetchProjects:
    def test_builds_string_keyed_id_to_name_map(self, monkeypatch):
        monkeypatch.setattr(
            mc, "_todoist_request", _SeqTodoist([{"results": [{"id": 220, "name": "Health"}, {"id": "9", "name": "Work"}]}])
        )
        assert mc._fetch_projects("tok") == {"220": "Health", "9": "Work"}

    def test_failure_returns_empty_map(self, monkeypatch):
        monkeypatch.setattr(mc, "_todoist_request", _SeqTodoist([], raise_on=1))
        assert mc._fetch_projects("tok") == {}


class _FakeSecretsClient:
    """Hand-written stand-in for boto3 secretsmanager — get_secret_value only."""

    def __init__(self, secret_string=None, error=None):
        self.secret_string = secret_string
        self.error = error
        self.calls = []

    def get_secret_value(self, SecretId=None):
        self.calls.append(SecretId)
        if self.error is not None:
            raise self.error
        return {"SecretString": self.secret_string}


class TestFetchTodoistToken:
    """#2178: the real Secrets Manager fetch — was hardcoded to None, so
    gather_todoist_data never ran and two of six sections narrated a
    permanently-empty task load (ADR-104)."""

    def test_reads_the_life_platform_todoist_secret(self, monkeypatch):
        fake = _FakeSecretsClient(secret_string=json.dumps({"todoist_api_token": "tok-real"}))
        monkeypatch.setattr(mc, "secrets", fake)
        import common.secret_cache as secret_cache

        secret_cache.invalidate(mc.TODOIST_SECRET_NAME)

        assert mc._fetch_todoist_token() == "tok-real"
        assert fake.calls == [mc.TODOIST_SECRET_NAME]

    def test_falls_back_to_the_todoist_key(self, monkeypatch):
        import common.secret_cache as secret_cache

        secret_cache.invalidate(mc.TODOIST_SECRET_NAME)
        monkeypatch.setattr(mc, "secrets", _FakeSecretsClient(secret_string=json.dumps({"todoist": "tok-alt"})))

        assert mc._fetch_todoist_token() == "tok-alt"

    def test_missing_token_key_returns_none(self, monkeypatch):
        import common.secret_cache as secret_cache

        secret_cache.invalidate(mc.TODOIST_SECRET_NAME)
        monkeypatch.setattr(mc, "secrets", _FakeSecretsClient(secret_string=json.dumps({"other": "x"})))

        assert mc._fetch_todoist_token() is None

    def test_secrets_manager_failure_is_non_fatal(self, monkeypatch):
        import common.secret_cache as secret_cache

        secret_cache.invalidate(mc.TODOIST_SECRET_NAME)
        monkeypatch.setattr(mc, "secrets", _FakeSecretsClient(error=RuntimeError("secret deleted")))

        assert mc._fetch_todoist_token() is None


class TestGatherTodoistData:
    def test_normalizes_and_removes_overdue_from_due_this_week(self, monkeypatch):
        monkeypatch.setattr(mc, "_fetch_projects", lambda token: {"10": "Health"})

        due = [
            {"id": 1, "content": "Run 5k", "project_id": 10, "priority": 1, "due": {"date": "2026-06-10"}},
            {"id": 2, "content": "Old thing", "project_id": 10, "due": {"date": "2026-05-01"}},
        ]
        overdue = [{"id": 2, "content": "Old thing", "project_id": 10, "due": {"date": "2026-05-01"}}]

        def _fake_filter(filter_str, token, limit=200):
            return overdue if filter_str == "overdue" else due

        monkeypatch.setattr(mc, "_fetch_tasks_with_filter", _fake_filter)

        out = mc.gather_todoist_data("tok")

        assert out["total_due_this_week"] == 1
        assert out["total_overdue"] == 1
        assert [t["id"] for t in out["due_this_week"]] == ["1"]
        assert out["due_this_week"][0]["project_name"] == "Health"
        assert out["due_this_week"][0]["priority"] == 1
        assert out["project_map"] == {"10": "Health"}

    def test_missing_fields_get_normalized_defaults(self, monkeypatch):
        monkeypatch.setattr(mc, "_fetch_projects", lambda token: {})
        monkeypatch.setattr(mc, "_fetch_tasks_with_filter", lambda f, t, limit=200: [{"id": 5}] if f != "overdue" else [])

        task = mc.gather_todoist_data("tok")["due_this_week"][0]

        assert task["content"] == "Untitled"
        assert task["project_name"] == "Inbox"
        assert task["priority"] == 4
        assert task["labels"] == []
        assert task["due"] is None


# ═══════════════════════════════════════════════════════════════════════════
# Health-data gathering
# ═══════════════════════════════════════════════════════════════════════════


class TestGatherHealthData:
    def test_uses_a_seven_day_window_and_picks_latest_sheet(self, monkeypatch, frozen_clock):
        calls = []
        grades = [{"date": "2026-06-02", "day_grade": 70}, {"date": "2026-06-07", "day_grade": 88}]
        sheets = [{"date": "2026-06-06", "character_level": 3}, {"date": "2026-06-07", "character_level": 4}]

        def _fake_query_source(source, start, end):
            calls.append((source, start, end))
            return {
                "day_grade": grades,
                "character_sheet": sheets,
                "whoop": [{"date": TODAY, "recovery_score": 61}],
                "habit_scores": [{"date": "2026-06-07", "t0_total": 4, "t0_completed": 4}],
            }.get(source, [])

        monkeypatch.setattr(mc, "query_source", _fake_query_source)
        monkeypatch.setattr(mc, "query_source_latest", lambda s: {"readiness_score": 70})

        out = mc.gather_health_data()

        assert out["today_str"] == TODAY
        assert ("day_grade", "2026-06-01", TODAY) in calls
        # whoop is queried for today only, never the trailing window
        assert ("whoop", TODAY, TODAY) in calls
        assert out["character_sheet"]["character_level"] == 4  # newest of the window
        assert out["whoop_today"]["recovery_score"] == 61
        assert out["computed_metrics"] == {"readiness_score": 70}

    def test_absent_sources_degrade_to_empty_dicts(self, monkeypatch, frozen_clock):
        monkeypatch.setattr(mc, "query_source", lambda s, a, b: [])
        monkeypatch.setattr(mc, "query_source_latest", lambda s: {})

        out = mc.gather_health_data()

        assert out["character_sheet"] == {}
        assert out["whoop_today"] == {}
        assert out["day_grades"] == []


# ═══════════════════════════════════════════════════════════════════════════
# Pure shaping helpers
# ═══════════════════════════════════════════════════════════════════════════


class TestGroupTasksByPillar:
    PMAP = {"_comment": "ignored metadata key", "Health": "movement", "Sleep": "sleep", "Inbox": "consistency"}

    def test_exact_match_is_case_insensitive(self):
        groups = mc._group_tasks_by_pillar([{"project_name": "health"}], self.PMAP)
        assert list(groups) == ["movement"]

    def test_partial_match_when_no_exact_match(self):
        groups = mc._group_tasks_by_pillar([{"project_name": "Deep Sleep Routine"}], self.PMAP)
        assert list(groups) == ["sleep"]

    def test_unmapped_project_falls_back_to_general(self):
        groups = mc._group_tasks_by_pillar([{"project_name": "Taxes"}], self.PMAP)
        assert list(groups) == ["general"]

    def test_underscore_prefixed_config_keys_are_never_matched(self):
        # "_comment" is metadata, not a project — a project literally named
        # "_comment" must fall through to general, not inherit its value.
        groups = mc._group_tasks_by_pillar([{"project_name": "_comment"}], self.PMAP)
        assert list(groups) == ["general"]

    def test_missing_project_name_defaults_to_inbox(self):
        groups = mc._group_tasks_by_pillar([{"content": "no project"}], self.PMAP)
        assert list(groups) == ["consistency"]

    def test_tasks_accumulate_per_pillar(self):
        tasks = [{"project_name": "Health"}, {"project_name": "Health"}, {"project_name": "Sleep"}]
        groups = mc._group_tasks_by_pillar(tasks, self.PMAP)
        assert len(groups["movement"]) == 2
        assert len(groups["sleep"]) == 1


class TestPriorityLabel:
    def test_known_priorities(self):
        assert mc._priority_label(1) == "🔴 P1"
        assert mc._priority_label(2) == "🟠 P2"
        assert mc._priority_label(3) == "🟡 P3"

    def test_p4_and_unknown_render_nothing(self):
        assert mc._priority_label(4) == ""
        assert mc._priority_label(9) == ""
        assert mc._priority_label(None) == ""


class TestDueLabel:
    def test_today_and_tomorrow(self, frozen_clock):
        assert mc._due_label({"date": TODAY}) == "· due today"
        assert mc._due_label({"date": "2026-06-09"}) == "· due tomorrow"

    def test_past_due_counts_days(self, frozen_clock):
        assert mc._due_label({"date": "2026-06-05"}) == "· 3d overdue"

    def test_later_this_week_shows_weekday(self, frozen_clock):
        assert mc._due_label({"date": "2026-06-11"}) == "· Thu"

    def test_string_due_with_timestamp_is_truncated_to_date(self, frozen_clock):
        assert mc._due_label("2026-06-09T17:00:00") == "· due tomorrow"

    def test_missing_or_unparseable_due_renders_nothing(self, frozen_clock):
        assert mc._due_label(None) == ""
        assert mc._due_label({"date": ""}) == ""
        assert mc._due_label({"date": "not-a-date"}) == ""


class TestComputeWeekNum:
    def test_genesis_day_is_week_one(self, frozen_clock):
        assert mc._compute_week_num({"journey_start_date": TODAY}) == 1

    def test_seventh_day_is_still_week_one(self, frozen_clock):
        assert mc._compute_week_num({"journey_start_date": "2026-06-01"}) == 1

    def test_eighth_day_rolls_to_week_two(self, frozen_clock):
        assert mc._compute_week_num({"journey_start_date": "2026-05-31"}) == 2

    def test_unparseable_start_date_degrades_to_week_one(self, frozen_clock):
        assert mc._compute_week_num({"journey_start_date": "someday"}) == 1


class TestBuildWeekStateSummary:
    def _health(self, **over):
        base = {
            "computed_metrics": {"hrv_yesterday": 58, "readiness_score": 72, "tsb": -4.5, "tsb_load_basis": {"proxy_share": 0.8}},
            "whoop_today": {"recovery_score": 61, "hrv_rmssd_ms": 44},
            "character_sheet": {
                "character_level": 6,
                "character_tier": "Momentum",
                "pillar_sleep": {"raw_score": 41.44},
                "pillar_movement": {"raw_score": 72.0},
                "pillar_nutrition": {"raw_score": 55.0},
                "pillar_mind": {},
            },
            "day_grades": [{"day_grade": 80}, {"day_grade": 85}, {"day_grade": None}],
        }
        base.update(over)
        return base

    def test_reads_metrics_pillars_and_grades(self, frozen_clock):
        state = mc.build_week_state_summary(self._health(), {"journey_start_date": "2026-06-01"})

        assert state["recovery"] == 61.0
        assert state["hrv"] == 58.0  # computed_metrics wins over the whoop field
        assert state["readiness"] == 72.0
        assert state["tsb"] == -4.5
        assert state["tsb_basis_note"] == " (duration-proxy basis)"
        assert state["char_level"] == 6
        assert state["char_tier"] == "Momentum"
        # None grades are dropped, not counted as zeros
        assert state["last_week_avg_grade"] == 82.5
        assert state["pillar_scores"] == {"sleep": 41.4, "movement": 72.0, "nutrition": 55.0}
        assert state["weakest_pillar"] == "sleep"
        assert state["week_num"] == 1

    def test_hrv_falls_back_to_whoop_when_metrics_lack_it(self, frozen_clock):
        health = self._health(computed_metrics={})
        assert mc.build_week_state_summary(health, {})["hrv"] == 44.0

    def test_profile_overrides_weight_anchors(self, frozen_clock):
        state = mc.build_week_state_summary(self._health(), {"journey_start_weight_lbs": 331.0, "goal_weight_lbs": 210})
        assert state["start_weight"] == 331.0
        assert state["goal_weight"] == 210

    def test_empty_platform_yields_honest_nulls_not_zeros(self, frozen_clock):
        state = mc.build_week_state_summary(
            {"computed_metrics": {}, "whoop_today": {}, "character_sheet": {}, "day_grades": []},
            {},
        )
        assert state["recovery"] is None
        assert state["hrv"] is None
        assert state["last_week_avg_grade"] is None
        assert state["pillar_scores"] == {}
        assert state["weakest_pillar"] is None
        assert state["char_level"] == 1
        assert state["char_tier"] == "Foundation"
        assert state["start_weight"] == EXPERIMENT_BASELINE_WEIGHT_LBS
        assert state["tsb_basis_note"] == ""


# ═══════════════════════════════════════════════════════════════════════════
# Board Pro Tips selection
# ═══════════════════════════════════════════════════════════════════════════


class _FakeBoardLoader:
    def __init__(self, config):
        self.config = config
        self.calls = []

    def load_board(self, s3_client, bucket):
        self.calls.append(bucket)
        return self.config


_BOARD_CONFIG = {
    "members": {
        "rodriguez": {
            "name": "Dr. Elena Rodriguez",
            "title": "Behavioral Scientist",
            "domains": ["habits", "willpower", "design", "extra"],
        },
        "park": {"name": "Dr. Park", "title": "Sleep", "domains": ["sleep"], "voice": {"catchphrase": "Protect the window."}},
        "chen": {"name": "Coach Chen", "title": "Training", "domains": ["training"]},
        "the_chair": {"name": "The Chair", "title": "Platform Intelligence", "domains": ["leverage"]},
        "webb": {"name": "Dr. Webb", "title": "Nutrition", "domains": ["food"], "active": False},
    }
}


def _install_board(monkeypatch, config=_BOARD_CONFIG):
    loader = _FakeBoardLoader(config)
    monkeypatch.setattr(mc, "_HAS_BOARD_LOADER", True)
    monkeypatch.setattr(mc, "board_loader", loader, raising=False)
    return loader


class TestBoardContext:
    def test_weakest_pillar_picks_its_specialist_alongside_rodriguez(self, monkeypatch):
        _install_board(monkeypatch)
        out = mc._build_board_context_for_compass({"weakest_pillar": "sleep", "recovery": 70}, {"total_overdue": 3})

        assert "Dr. Elena Rodriguez" in out
        assert "Dr. Park" in out
        assert 'Principle: "Protect the window."' in out
        # domains are truncated to three
        assert "habits, willpower, design" in out and "extra" not in out
        assert "Coach Chen" not in out

    def test_low_recovery_adds_the_sleep_specialist(self, monkeypatch):
        _install_board(monkeypatch)
        out = mc._build_board_context_for_compass({"weakest_pillar": "movement", "recovery": 42}, {"total_overdue": 0})
        assert "Coach Chen" in out  # movement specialist
        assert "Dr. Park" in out  # added because recovery < 50

    def test_low_recovery_when_sleep_is_already_weakest_adds_training(self, monkeypatch):
        _install_board(monkeypatch)
        out = mc._build_board_context_for_compass({"weakest_pillar": "sleep", "recovery": 20}, {"total_overdue": 0})
        assert "Dr. Park" in out and "Coach Chen" in out

    def test_big_backlog_with_healthy_recovery_adds_the_chair(self, monkeypatch):
        _install_board(monkeypatch)
        out = mc._build_board_context_for_compass({"weakest_pillar": "movement", "recovery": 80}, {"total_overdue": 21})
        assert "The Chair" in out

    def test_inactive_members_are_skipped_and_empty_selection_falls_back(self, monkeypatch):
        _install_board(monkeypatch, {"members": {"webb": _BOARD_CONFIG["members"]["webb"]}})
        out = mc._build_board_context_for_compass({"weakest_pillar": "nutrition", "recovery": 70}, {"total_overdue": 0})
        assert "Dr. Webb" not in out
        # #2384: the fallback names the LIVE mind coach, not the phantom "Dr. Elena Rodriguez"
        assert "Dr. Nathan Reeves (Mind & Behaviour Coach)" in out  # the fallback text

    def test_missing_board_config_uses_fallback(self, monkeypatch):
        _install_board(monkeypatch, None)
        out = mc._build_board_context_for_compass({"weakest_pillar": "mind"}, {})
        assert "The Chair (Platform Intelligence)" in out
        assert "mind pillar" in out

    def test_loader_absent_uses_fallback(self, monkeypatch):
        monkeypatch.setattr(mc, "_HAS_BOARD_LOADER", False)
        assert "Dr. Nathan Reeves" in mc._build_board_context_for_compass({"weakest_pillar": "sleep"}, {})


# ═══════════════════════════════════════════════════════════════════════════
# Prompt payload
# ═══════════════════════════════════════════════════════════════════════════


def _task(content, project, priority=4, due=None):
    return {"id": content, "content": content, "project_name": project, "priority": priority, "due": due}


class TestBuildUserMessage:
    PMAP = {"Health": "movement", "Nutrition": "nutrition", "Inbox": "consistency"}

    @pytest.fixture(autouse=True)
    def _no_insight_writer(self, monkeypatch):
        monkeypatch.setattr(mc, "_HAS_INSIGHT_WRITER", False)

    def _week_state(self, **over):
        base = {
            "week_num": 3,
            "start_weight": 331.0,
            "goal_weight": 210,
            "char_level": 6,
            "char_tier": "Momentum",
            "recovery": 61.0,
            "hrv": 58.0,
            "readiness": 72.0,
            "tsb": -4.5,
            "tsb_basis_note": " (duration-proxy basis)",
            "pillar_scores": {"movement": 72.0, "sleep": 41.4},
            "weakest_pillar": "sleep",
            "last_week_avg_grade": 82.5,
        }
        base.update(over)
        return base

    def test_journey_context_is_returned_and_embedded(self, frozen_clock):
        payload, journey = mc.build_user_message(self._week_state(), {}, {}, {}, self.PMAP, "BOARD CTX")

        assert journey == "Week 3 of transformation journey (331.0→210 lbs). Character Level 6 (Momentum). Today is Monday June 8, 2026."
        assert journey in payload
        assert "BOARD CTX" in payload

    def test_readiness_and_pillar_blocks_render_weakest_first(self, frozen_clock):
        payload, _ = mc.build_user_message(self._week_state(), {}, {}, {}, self.PMAP, "")

        assert "Recovery: 61.0%" in payload
        assert "TSB (training stress balance): -4.5 (duration-proxy basis)" in payload
        assert "😴 Sleep: 41/100" in payload
        assert "🏃 Movement: 72/100" in payload
        assert payload.index("Sleep: 41/100") < payload.index("Movement: 72/100")
        assert "Weakest pillar this week: Sleep" in payload

    def test_tasks_group_by_pillar_with_labels_and_overflow(self, frozen_clock):
        due = [_task(f"Task {i}", "Health") for i in range(9)]
        due.append(_task("Meal prep", "Nutrition", priority=1, due={"date": TODAY}))
        todoist = {"due_this_week": due, "overdue": [], "total_due_this_week": 10, "total_overdue": 0}

        payload, _ = mc.build_user_message(self._week_state(), todoist, {}, {}, self.PMAP, "")

        assert "TASKS DUE THIS WEEK: 10 tasks" in payload
        assert "🏃 MOVEMENT (9 tasks):" in payload
        assert "    ... +1 more" in payload  # 9 tasks, max 8 rendered
        assert "    - Meal prep 🔴 P1 · due today [Nutrition]" in payload
        assert "None — clean slate" in payload

    def test_overdue_block_caps_at_five_per_pillar(self, frozen_clock):
        overdue = [_task(f"Old {i}", "Nutrition") for i in range(6)]
        todoist = {"due_this_week": [], "overdue": overdue, "total_due_this_week": 0, "total_overdue": 6}

        payload, _ = mc.build_user_message(self._week_state(), todoist, {}, {}, self.PMAP, "")

        assert "OVERDUE: 6 tasks" in payload
        assert "🥗 NUTRITION (6 overdue):" in payload
        assert "    ... +1 more" in payload
        assert "No tasks due this week" in payload

    def test_unavailable_todoist_data_states_absence_not_a_fake_zero(self, frozen_clock):
        """#2178 / ADR-104: `available=False` must produce an honest 'the fetch
        didn't happen' statement, never the same '0 tasks' / 'clean slate' text
        used for a genuinely empty-but-fetched result."""
        todoist = {
            "due_this_week": [],
            "overdue": [],
            "total_due_this_week": 0,
            "total_overdue": 0,
            "available": False,
        }

        payload, _ = mc.build_user_message(self._week_state(), todoist, {}, {}, self.PMAP, "")

        assert "TASKS DUE THIS WEEK: UNAVAILABLE" in payload
        assert "OVERDUE: UNAVAILABLE" in payload
        assert "Todoist could not be reached this week" in payload
        assert "0 tasks" not in payload
        assert "None — clean slate" not in payload
        assert "No tasks due this week" not in payload

    def test_habit_and_grade_lines_are_computed_from_records(self, frozen_clock):
        health = {
            "habit_scores_7d": [
                {"t0_total": 4, "t0_completed": 2},
                {"t0_total": 0, "t0_completed": 0},  # uninstrumented day is skipped, not a zero
                {"t0_total": 5, "t0_completed": 5},
            ],
            "day_grades": [
                {"date": "2026-06-06", "day_grade": 80, "grade_label": "Solid"},
                {"date": "2026-06-07", "day_grade": 88.4, "grade_label": "Strong"},
                {"date": "2026-06-08", "day_grade": None, "grade_label": "n/a"},
            ],
        }
        payload, _ = mc.build_user_message(self._week_state(), {}, health, {}, self.PMAP, "")

        assert "T0 habit compliance last 7 days: avg 75% (daily: 50%, 100%)" in payload
        assert "Last 7 day grades: 06-06 80 (Solid), 06-07 88 (Strong)" in payload

    def test_recent_insights_are_appended_when_the_writer_is_bundled(self, monkeypatch, frozen_clock):
        class _Writer:
            def __init__(self):
                self.kwargs = None

            def build_insights_context(self, **kwargs):
                self.kwargs = kwargs
                return "RECENT PLATFORM INSIGHTS: sleep debt is compounding"

        writer = _Writer()
        monkeypatch.setattr(mc, "_HAS_INSIGHT_WRITER", True)
        monkeypatch.setattr(mc, "insight_writer", writer, raising=False)

        payload, _ = mc.build_user_message(self._week_state(), {}, {}, {}, self.PMAP, "")

        assert "sleep debt is compounding" in payload
        assert writer.kwargs["days"] == 7 and writer.kwargs["max_items"] == 3

    def test_insight_lookup_failure_is_non_fatal(self, monkeypatch, frozen_clock):
        class _Boom:
            def build_insights_context(self, **kwargs):
                raise RuntimeError("ddb down")

        monkeypatch.setattr(mc, "_HAS_INSIGHT_WRITER", True)
        monkeypatch.setattr(mc, "insight_writer", _Boom(), raising=False)

        payload, _ = mc.build_user_message(self._week_state(), {}, {}, {}, self.PMAP, "")

        assert "== END BRIEFING ==" in payload

    def test_empty_platform_states_absence_explicitly(self, frozen_clock):
        payload, _ = mc.build_user_message(
            self._week_state(pillar_scores={}, weakest_pillar=None, last_week_avg_grade=None),
            {},
            {},
            {},
            self.PMAP,
            "",
        )
        assert "No pillar data yet" in payload
        assert "No grade data" in payload
        assert "No habit data" in payload
        assert "Weakest pillar this week: " in payload


# ═══════════════════════════════════════════════════════════════════════════
# Email HTML wrapper
# ═══════════════════════════════════════════════════════════════════════════


class TestBuildEmailHtml:
    def _state(self, recovery):
        return {"char_level": 6, "char_tier": "Momentum", "recovery": recovery, "week_num": 3}

    def test_header_renders_date_level_and_week(self):
        html = mc.build_email_html("<p>AI</p>", self._state(61.0), TODAY)
        assert "LIFE PLATFORM · WEEK 3" in html
        assert "June 8, 2026" in html
        assert ">6<" in html and "Momentum" in html
        assert "<p>AI</p>" in html
        assert "The Monday Compass · Life Platform · Weekly Planning Edition" in html
        assert "not medical advice" in html

    def test_recovery_color_thresholds_at_the_exact_boundaries(self):
        assert "#4ade80" in mc.build_email_html("", self._state(67), TODAY)
        assert "#fb923c" in mc.build_email_html("", self._state(66.9), TODAY)
        assert "#fb923c" in mc.build_email_html("", self._state(34), TODAY)
        assert "#f87171" in mc.build_email_html("", self._state(33.9), TODAY)

    def test_recovery_is_rounded_for_display(self):
        assert "61%" in mc.build_email_html("", self._state(61.4), TODAY)

    def test_zero_recovery_renders_as_zero_not_a_dash(self):
        html = mc.build_email_html("", self._state(0), TODAY)
        assert "0%" in html
        assert "#f87171" in html

    def test_missing_recovery_renders_an_em_dash(self):
        assert "—" in mc.build_email_html("", self._state(None), TODAY)

    def test_unparseable_date_passes_through_verbatim(self):
        assert "not-a-date" in mc.build_email_html("", self._state(50), "not-a-date")


# ═══════════════════════════════════════════════════════════════════════════
# AI call + presence block + send record
# ═══════════════════════════════════════════════════════════════════════════


class TestCallAnthropic:
    def test_delegates_with_planning_temperature_and_timeout(self, monkeypatch):
        import common.retry_utils as ru

        captured = {}

        def _fake(prompt=None, max_tokens=None, system=None, temperature=None, timeout=None, cache_system=True):
            captured.update(
                prompt=prompt, max_tokens=max_tokens, system=system, temperature=temperature, timeout=timeout, cache_system=cache_system
            )
            return "<div>compass</div>"

        monkeypatch.setattr(ru, "call_anthropic_api", _fake)

        assert mc.call_anthropic("SYS", "USER", max_tokens=1234) == "<div>compass</div>"
        # #2888: `cache_system=False` is part of the contract, not an incidental kwarg —
        # monday-compass makes ONE Bedrock call per weekly run, so a cache_control block
        # here is a pure write premium against a read that can never happen.
        assert captured == {
            "prompt": "USER",
            "max_tokens": 1234,
            "system": "SYS",
            "temperature": 0.4,
            "timeout": 120,
            "cache_system": False,
        }


class TestPresenceBlock:
    def test_ddb_failure_is_non_fatal_and_yields_no_block(self, monkeypatch):
        class _Boom:
            def get_item(self, **kwargs):
                raise RuntimeError("ddb down")

        monkeypatch.setattr(mc, "table", _Boom())
        assert mc._presence_block() == ""


class TestRecordEmailSend:
    def test_writes_a_dated_success_row_with_ttl(self, monkeypatch, frozen_clock):
        fake = FakeDdbTable()
        mc.record_email_send(fake, "monday_compass", "week:2026-W34")

        assert len(fake.puts) == 1
        item = fake.puts[0]
        assert item["pk"] == "USER#matthew#SOURCE#email_log#monday_compass"
        assert item["sk"] == f"DATE#{TODAY}"
        assert item["status"] == "success"
        assert item["ttl"] > 0

    def test_write_failure_never_propagates(self, monkeypatch, frozen_clock):
        class _Boom:
            def put_item(self, **kwargs):
                raise RuntimeError("throttled")

        mc.record_email_send(_Boom(), "monday_compass", "week:2026-W34")  # must not raise


# ═══════════════════════════════════════════════════════════════════════════
# Handler
# ═══════════════════════════════════════════════════════════════════════════


class _ValidationResult:
    def __init__(self, blocked=False, block_reason="", warnings=None, safe_fallback=None):
        self.blocked = blocked
        self.block_reason = block_reason
        self.warnings = warnings or []
        self.safe_fallback = safe_fallback


class TestLambdaHandler:
    @pytest.fixture
    def wired(self, monkeypatch, frozen_clock):
        """Handler wired to in-memory doubles — no SES, DDB, S3, or Bedrock."""
        ses = _FakeSes()
        table = FakeDdbTable()
        monkeypatch.setattr(mc, "ses", ses)
        monkeypatch.setattr(mc, "table", table)
        monkeypatch.setattr(mc, "_HAS_INSIGHT_WRITER", False)
        monkeypatch.setattr(mc, "_HAS_AI_VALIDATOR", False)
        monkeypatch.setattr(mc, "_HAS_BOARD_LOADER", False)
        monkeypatch.setattr(mc, "fetch_profile", lambda: {"journey_start_date": "2026-06-01", "goal_weight_lbs": 210})
        monkeypatch.setattr(mc, "load_project_pillar_map", lambda: {"Health": "movement"})
        monkeypatch.setattr(
            mc,
            "gather_health_data",
            lambda: {
                "day_grades": [{"date": "2026-06-07", "day_grade": 88, "grade_label": "Strong"}],
                "computed_metrics": {"readiness_score": 72},
                "character_sheet": {"character_level": 6, "character_tier": "Momentum", "pillar_sleep": {"raw_score": 41.0}},
                "whoop_today": {"recovery_score": 61},
                "habit_scores_7d": [],
                "today_str": TODAY,
            },
        )
        monkeypatch.setattr(mc, "call_anthropic", lambda system, user, max_tokens=3500: "<div>SECTION ONE</div>")
        # #2178: the real Secrets-Manager-backed fetch, wired to a live token by
        # default so the happy path exercises the fixed (non-stubbed) behavior.
        monkeypatch.setattr(mc, "_fetch_todoist_token", lambda: "tok-wired")
        monkeypatch.setattr(
            mc,
            "gather_todoist_data",
            lambda token: {
                "due_this_week": [{"id": "1", "content": "Ship it", "project_id": "1", "project_name": "Health"}],
                "overdue": [{"id": "2", "content": "Old thing", "project_id": "1", "project_name": "Health"}],
                "total_due_this_week": 1,
                "total_overdue": 1,
                "project_map": {},
            },
        )
        return ses, table

    def test_missing_profile_aborts_before_sending(self, monkeypatch, wired):
        ses, _ = wired
        monkeypatch.setattr(mc, "fetch_profile", lambda: {})

        out = mc.lambda_handler({}, None)

        assert out["statusCode"] == 500
        assert out["body"] == "No profile"
        assert ses.sent == []

    def test_happy_path_sends_and_records(self, wired):
        ses, table = wired

        out = mc.lambda_handler({}, None)

        assert out["statusCode"] == 200
        body = json.loads(out["body"])
        assert body["email"] == "🧭 Monday Compass · Jun 8 · Week 1"
        assert body["week_num"] == 1
        assert body["char_level"] == 6
        # #2178: the real Todoist fetch is wired (see `wired` fixture) and ran —
        # these are no longer a permanently-empty stub (ADR-104).
        assert body["tasks_due_this_week"] == 1
        assert body["overdue"] == 1

        assert len(ses.sent) == 1
        sent = ses.sent[0]
        assert sent["FromEmailAddress"] == mc.SENDER
        assert sent["Destination"] == {"ToAddresses": [mc.RECIPIENT]}
        assert sent["Content"]["Simple"]["Subject"]["Data"] == body["email"]
        html = sent["Content"]["Simple"]["Body"]["Html"]["Data"]
        assert "SECTION ONE" in html
        assert "🧭 The Monday Compass" in html

        # the status-page completion record is written after the send
        assert table.puts[0]["pk"] == "USER#matthew#SOURCE#email_log#monday_compass"

    def test_gather_todoist_data_is_called_with_the_real_fetched_token(self, monkeypatch, wired):
        """#2178 acceptance: a regression test confirming lambda_handler calls
        gather_todoist_data with a real (non-None) token under normal conditions."""
        ses, _ = wired
        monkeypatch.setattr(mc, "_fetch_todoist_token", lambda: "tok-real-secret-value")

        captured_tokens = []

        def _spy(token):
            captured_tokens.append(token)
            return {"due_this_week": [], "overdue": [], "total_due_this_week": 0, "total_overdue": 0}

        monkeypatch.setattr(mc, "gather_todoist_data", _spy)

        mc.lambda_handler({}, None)

        assert captured_tokens == ["tok-real-secret-value"]
        assert captured_tokens[0] is not None
        assert len(ses.sent) == 1

    def test_no_token_skips_the_fetch_and_renders_honest_unavailable_state(self, monkeypatch, wired):
        """#2178 acceptance: when Todoist genuinely can't be reached, the prompt
        must state the absence rather than presenting '0 due, 0 overdue' as a
        true reading (ADR-104)."""
        ses, _ = wired
        monkeypatch.setattr(mc, "_fetch_todoist_token", lambda: None)

        def _boom_if_called(token):
            raise AssertionError("gather_todoist_data must not run without a token")

        monkeypatch.setattr(mc, "gather_todoist_data", _boom_if_called)

        captured = {}

        def _capture(system, user, max_tokens=3500):
            captured["user"] = user
            return "<div>SECTION ONE</div>"

        monkeypatch.setattr(mc, "call_anthropic", _capture)

        out = mc.lambda_handler({}, None)

        assert out["statusCode"] == 200
        body = json.loads(out["body"])
        assert body["tasks_due_this_week"] == 0
        assert body["overdue"] == 0
        assert "TASKS DUE THIS WEEK: UNAVAILABLE" in captured["user"]
        assert "OVERDUE: UNAVAILABLE" in captured["user"]
        assert "Todoist could not be reached" in captured["user"]
        # never a fabricated true-zero reading
        assert "0 tasks" not in captured["user"]
        assert "None — clean slate" not in captured["user"]
        assert len(ses.sent) == 1

    def test_todoist_gather_failure_is_non_fatal_and_marked_unavailable(self, monkeypatch, wired):
        """The existing non-fatal except (line ~855 pre-fix) must still protect
        the rest of the email when Todoist is reachable-token-wise but the fetch
        itself blows up — AND the resulting state must be honest, not a fake zero."""
        ses, _ = wired
        monkeypatch.setattr(mc, "_fetch_todoist_token", lambda: "tok-wired")

        def _boom(token):
            raise RuntimeError("todoist 500")

        monkeypatch.setattr(mc, "gather_todoist_data", _boom)

        captured = {}

        def _capture(system, user, max_tokens=3500):
            captured["user"] = user
            return "<div>SECTION ONE</div>"

        monkeypatch.setattr(mc, "call_anthropic", _capture)

        out = mc.lambda_handler({}, None)

        assert out["statusCode"] == 200
        body = json.loads(out["body"])
        assert body["tasks_due_this_week"] == 0
        assert body["overdue"] == 0
        assert "TASKS DUE THIS WEEK: UNAVAILABLE" in captured["user"]
        assert len(ses.sent) == 1

    def test_ai_failure_still_sends_a_degraded_email(self, monkeypatch, wired):
        ses, _ = wired

        def _boom(system, user, max_tokens=3500):
            raise RuntimeError("bedrock throttled")

        monkeypatch.setattr(mc, "call_anthropic", _boom)

        out = mc.lambda_handler({}, None)

        assert out["statusCode"] == 200
        html = ses.sent[0]["Content"]["Simple"]["Body"]["Html"]["Data"]
        assert "Monday Compass AI unavailable this week" in html

    def test_blocked_ai_output_is_replaced_by_the_safe_fallback(self, monkeypatch, wired):
        ses, _ = wired
        monkeypatch.setattr(mc, "_HAS_AI_VALIDATOR", True)
        monkeypatch.setattr(mc, "AIOutputType", type("_T", (), {"WEEKLY_DIGEST": "weekly_digest"}), raising=False)
        monkeypatch.setattr(
            mc,
            "validate_ai_output",
            lambda content, kind: _ValidationResult(blocked=True, block_reason="pii", safe_fallback="<div>SAFE FALLBACK</div>"),
            raising=False,
        )

        mc.lambda_handler({}, None)

        html = ses.sent[0]["Content"]["Simple"]["Body"]["Html"]["Data"]
        assert "SAFE FALLBACK" in html
        assert "SECTION ONE" not in html

    def test_unparseable_today_str_degrades_the_subject_gracefully(self, monkeypatch, wired):
        ses, _ = wired
        monkeypatch.setattr(mc, "gather_health_data", lambda: {"today_str": "n/a", "day_grades": [], "computed_metrics": {}})

        out = mc.lambda_handler({}, None)

        assert json.loads(out["body"])["email"] == "🧭 Monday Compass · n/a · Week 1"
        assert "n/a" in ses.sent[0]["Content"]["Simple"]["Body"]["Html"]["Data"]

    def test_successful_send_files_a_platform_insight(self, monkeypatch, wired):
        class _Writer:
            def __init__(self):
                self.kwargs = None

            def build_insights_context(self, **kwargs):
                return ""

            def write_insight(self, **kwargs):
                self.kwargs = kwargs

        writer = _Writer()
        monkeypatch.setattr(mc, "_HAS_INSIGHT_WRITER", True)
        monkeypatch.setattr(mc, "insight_writer", writer, raising=False)

        mc.lambda_handler({}, None)

        assert writer.kwargs["digest_type"] == "monday_compass"
        assert writer.kwargs["date"] == TODAY
        assert writer.kwargs["pillars"] == ["sleep"]
        assert "SECTION ONE" in writer.kwargs["text"]
        assert writer.kwargs["actionable"] is True

    def test_insight_write_failure_never_fails_the_send(self, monkeypatch, wired):
        ses, _ = wired

        class _Boom:
            def build_insights_context(self, **kwargs):
                return ""

            def write_insight(self, **kwargs):
                raise RuntimeError("ddb down")

        monkeypatch.setattr(mc, "_HAS_INSIGHT_WRITER", True)
        monkeypatch.setattr(mc, "insight_writer", _Boom(), raising=False)

        assert mc.lambda_handler({}, None)["statusCode"] == 200
        assert len(ses.sent) == 1

    def test_validator_warnings_do_not_replace_the_content(self, monkeypatch, wired):
        ses, _ = wired
        monkeypatch.setattr(mc, "_HAS_AI_VALIDATOR", True)
        monkeypatch.setattr(mc, "AIOutputType", type("_T", (), {"WEEKLY_DIGEST": "weekly_digest"}), raising=False)
        monkeypatch.setattr(
            mc,
            "validate_ai_output",
            lambda content, kind: _ValidationResult(warnings=["tone"]),
            raising=False,
        )

        mc.lambda_handler({}, None)

        assert "SECTION ONE" in ses.sent[0]["Content"]["Simple"]["Body"]["Html"]["Data"]
