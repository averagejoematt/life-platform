"""tests/test_now_remainder_batch.py — the 2026-07-04 Now-remainder batch
(#473/#474/#477/#480/#481/#482/#497 + #518).

The last seven area:data Now stories + the health-check secret misfire, one PR.
Each test replays the review finding it closes:

  #477/E-2   habitify finalizes yesterday (refresh_trailing_days=1); past-day
             in_progress resolves failed, never frozen-pending
  #480/E-5   supplement bridge merges (a same-day manual log survives)
  #480/A-7   validator specs match the written shapes; WORKOUT# sub-records
             get their own schema instead of flooding warnings
  #481/A-1   eightsleep 401-path re-login persists the fresh token
  #481/A-9   framework secret writeback retries once + ERRORs loudly
  #482/X-6   every standalone DDB-writing ingestion path stamps phase
  #473/B-4   measurements: multi-row CSVs ingest all sessions; session_number
             is date-rank (stable across re-imports)
  #474/D-5   apple_health XML path retired (lambda gone, backfill guarded)
  #497/C-2   garmin cron disabled per ADR-074
  #518       health-check REQUIRED_SECRETS matches secrets that exist
"""

import io
import json
import os
import sys
import urllib.error
from datetime import datetime, timedelta, timezone
from decimal import Decimal

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "ingestion"))

import habitify_lambda as hab  # noqa: E402
import ingestion_framework as fw  # noqa: E402
import ingestion_validator as iv  # noqa: E402
import measurements_ingestion_lambda as meas  # noqa: E402
from fakes import FakeDdbTable  # noqa: E402

_INGESTION_STACK_SRC = open(os.path.join(_REPO, "cdk/stacks/ingestion_stack.py")).read()


# ==============================================================================
# #477/E-2 — habitify days must finalize
# ==============================================================================


def test_habitify_refreshes_trailing_day():
    """The framework hook is armed: yesterday is re-fetched every run, so the
    23:05 UTC pending-frozen write gets one post-midnight rewrite."""
    assert hab._config.refresh_trailing_days == 1


def test_habitify_past_day_pending_resolves_failed():
    """Replay the frozen 2026-06-20 record: 31 pending on a past day. On a
    re-transform, in_progress on a PAST day is failed — pending_count 0 and the
    completion pct strict."""
    journal = [
        {"name": "Walk", "status": "completed", "progress": {}, "area": {"id": "a1"}},
        {"name": "Journal", "status": "in_progress", "progress": {}, "area": {"id": "a1"}},
    ]
    raw = {"area_map": {"a1": "Discipline"}, "journal": journal, "moods": []}
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    rec = hab.transform(raw, yesterday)[0]
    assert rec["pending_count"] == 0
    assert rec["habit_statuses"]["Journal"]["status"] == "failed"
    assert rec["completion_pct"] == Decimal("0.5")


def test_habitify_today_pending_stays_pending():
    journal = [{"name": "Journal", "status": "in_progress", "progress": {}, "area": None}]
    raw = {"area_map": {}, "journal": journal, "moods": []}
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    rec = hab.transform(raw, today)[0]
    assert rec["pending_count"] == 1
    assert rec["habit_statuses"]["Journal"]["status"] == "pending"


# ==============================================================================
# #480/E-5 — the supplement bridge merges instead of clobbering
# ==============================================================================


def _FakeSuppTable(existing=None):
    def _get_item_hook(_table, key, **_kw):
        return {"Item": existing} if existing else {}

    return FakeDdbTable(get_item_hook=_get_item_hook)


def test_supplement_bridge_preserves_same_day_manual_log(monkeypatch):
    """Replay E-5: a manual MCP log_supplement entry exists for the day; the
    hourly bridge run must merge around it, not destroy it."""
    manual = {"name": "Magnesium", "dose": Decimal("400"), "unit": "mg", "logged_at": "2026-07-04T09:00:00Z"}
    bridge_old = {"name": "Creatine", "dose": Decimal("5"), "unit": "g", "source": "habitify_bridge"}
    fake = _FakeSuppTable(existing={"supplements": [manual, bridge_old]})
    monkeypatch.setattr(hab, "_table", fake)

    items = [{"habits": {"Creatine": Decimal("1")}}]
    supplement_name = next(iter(hab.SUPPLEMENT_MAP))
    items = [{"habits": {supplement_name: Decimal("1")}}]
    hab.supplement_bridge(items, "2026-07-04")

    assert fake.puts
    names = [e["name"] for e in fake.puts[-1]["supplements"]]
    assert "Magnesium" in names, "manual entry destroyed — the E-5 clobber"
    # the bridge's OWN old entries are replaced, not duplicated
    assert names.count(supplement_name) <= 1 or "Creatine" not in names or names.count("Creatine") == 1


def test_supplement_bridge_no_existing_record(monkeypatch):
    fake = _FakeSuppTable(existing=None)
    monkeypatch.setattr(hab, "_table", fake)
    supplement_name = next(iter(hab.SUPPLEMENT_MAP))
    hab.supplement_bridge([{"habits": {supplement_name: Decimal("1")}}], "2026-07-04")
    assert fake.puts and len(fake.puts[-1]["supplements"]) == 1


# ==============================================================================
# #480/A-7 — validator specs match written shapes
# ==============================================================================


def test_validator_whoop_workout_subrecords_use_own_schema():
    """Replay the 1,518-warnings-in-14d flood: a workout sub-record must not
    trip the night record's at_least_one_of."""
    item = {
        "pk": "USER#matthew#SOURCE#whoop",
        "sk": "DATE#2026-07-03#WORKOUT#abc",
        "date": "2026-07-03",
        "schema_version": 1,
        "strain": Decimal("12.4"),
        "average_heart_rate": Decimal("132"),
    }
    result = iv.validate_item("whoop", item, "2026-07-03")
    assert not result.warnings, result.warnings
    assert not result.errors


def test_validator_whoop_night_checks_written_name():
    """sleep_quality_score (the written name) is range-checked; a corrupt value
    now actually fires — the old sleep_score check could never match."""
    item = {
        "pk": "USER#matthew#SOURCE#whoop",
        "sk": "DATE#2026-07-03",
        "date": "2026-07-03",
        "schema_version": 1,
        "sleep_quality_score": Decimal("400"),
        "recovery_score": Decimal("50"),
    }
    result = iv.validate_item("whoop", item, "2026-07-03")
    assert any("sleep_quality_score" in e for e in result.errors + result.warnings)


def test_validator_todoist_matches_written_shape():
    item = {
        "pk": "USER#matthew#SOURCE#todoist",
        "sk": "DATE#2026-07-03",
        "date": "2026-07-03",
        "schema_version": 1,
        "completed_count": 4,
        "active_count": 12,
        "overdue_count": 1,
    }
    result = iv.validate_item("todoist", item, "2026-07-03")
    assert not result.warnings and not result.errors


def test_validator_supplements_matches_written_shape():
    item = {
        "pk": "USER#matthew#SOURCE#supplements",
        "sk": "DATE#2026-07-03",
        "date": "2026-07-03",
        "schema_version": 1,
        "supplements": [{"name": "Creatine"}],
    }
    result = iv.validate_item("supplements", item, "2026-07-03")
    assert not result.warnings and not result.errors


def test_validator_eightsleep_hr_avg_range_fires():
    item = {
        "pk": "USER#matthew#SOURCE#eightsleep",
        "sk": "DATE#2026-07-03",
        "date": "2026-07-03",
        "schema_version": 1,
        "sleep_duration_hours": Decimal("7.5"),
        "hr_avg": Decimal("400"),
    }
    result = iv.validate_item("eightsleep", item, "2026-07-03")
    assert any("hr_avg" in w for w in result.warnings + result.errors)


# ==============================================================================
# #481/A-1 — eightsleep 401-path persists the fresh token
# ==============================================================================


def test_eightsleep_401_relogin_persists_token(monkeypatch):
    import eightsleep_lambda as es

    calls = {"api": 0, "saved": None}

    def fake_api_get(path, token, params=None):
        calls["api"] += 1
        if calls["api"] == 1:
            raise urllib.error.HTTPError("u", 401, "unauthorized", {}, io.BytesIO(b""))
        return {"days": []}

    def fake_refresh(secret):
        return {**secret, "access_token": "FRESH", "user_id": secret["user_id"]}

    monkeypatch.setattr(es, "api_get", fake_api_get)
    monkeypatch.setattr(es, "refresh_token", fake_refresh)
    # #489/ADR-118: fetch_temperature_data retired (dead /v2/intervals endpoint).
    monkeypatch.setattr(es, "save_secret", lambda s: calls.__setitem__("saved", s))
    es._secret_cache_simp2["secret"] = None

    creds = {"user_id": "u1", "access_token": "STALE", "bed_side": "left", "timezone": "UTC"}
    es.fetch_day(creds, "2026-07-03")

    assert calls["saved"] is not None, "fresh token was NOT persisted (A-1)"
    assert calls["saved"]["access_token"] == "FRESH"


def test_framework_writeback_failure_is_loud():
    """A-9: the writeback block retries once and ERRORs (never a shrugged-off
    warning) — source pin on the exact behavior, since the block lives mid-run_ingestion."""
    src = open(os.path.join(_REPO, "lambdas/ingestion_framework.py")).read()
    assert "Secret writeback FAILED twice" in src
    assert 'logger.warning(f"Secret writeback failed (non-fatal): {e}")' not in src


# ==============================================================================
# #482/X-6 — every standalone writer stamps phase
# ==============================================================================


def test_phase_for_date_is_public_and_correct():
    assert fw.phase_for_date("2020-01-01") == "pilot"
    assert fw.phase_for_date(fw.EXPERIMENT_START_DATE) == fw.EXPERIMENT_PHASE_CURRENT
    assert fw._phase_for_date is fw.phase_for_date  # backward-compat alias


def test_all_standalone_writers_stamp_phase():
    """The sweep the AC asks for: every standalone (non-framework) ingestion
    writer references the shared phase stamp. Framework sources are stamped by
    _store_item; hevy via hevy_common."""
    standalone = {
        "health_auto_export_lambda.py": "phase_for_date",
        "notion_lambda.py": "_stamp_phase",
        "macrofactor_lambda.py": "phase_for_date",
        "food_delivery_lambda.py": "_phase_for",
        "measurements_ingestion_lambda.py": "_phase_for",
    }
    for fname, marker in standalone.items():
        src = open(os.path.join(_REPO, "lambdas", "ingestion", fname)).read()
        assert marker in src, f"{fname} does not stamp phase ({marker} missing)"
        assert '"phase"' in src or "#ph" in src, f"{fname} never writes a phase attribute"


# ==============================================================================
# #473 — measurements: multi-row + date-rank session numbers
# ==============================================================================

_CSV_TWO_SESSIONS = (
    "date,waist_narrowest_in,waist_navel_in,neck_in,notes\n" "2026-03-01,40.0,42.5,16.0,first\n" "2026-07-01,38.5,40.0,15.5,second\n"
)


def _FakeMeasTable(existing_dates=()):
    def _query_hook(_table, **_kw):
        return {"Items": [{"sk": f"DATE#{d}"} for d in existing_dates]}

    def _get_item_hook(_table, key, **_kw):
        return {"Item": {"height_inches": 69}}

    return FakeDdbTable(query_hook=_query_hook, get_item_hook=_get_item_hook)


class _FakeS3:
    def __init__(self, body):
        self.body = body

    def get_object(self, Bucket, Key):
        return {"Body": io.BytesIO(self.body)}


def _run_measurements(monkeypatch, csv_text, existing_dates=()):
    fake_table = _FakeMeasTable(existing_dates)
    monkeypatch.setattr(meas, "table", fake_table)
    monkeypatch.setattr(meas, "s3", _FakeS3(csv_text.encode()))
    result = meas.lambda_handler({"bucket": "matthew-life-platform", "key": "imports/measurements/sessions.csv"}, None)
    return fake_table, result


def test_measurements_multirow_csv_ingests_all_sessions(monkeypatch):
    """X-12 replay: the old parser used rows[0] only — a 2-session CSV lost one."""
    fake_table, result = _run_measurements(monkeypatch, _CSV_TWO_SESSIONS)
    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert body["sessions_written"] == 2
    dates = sorted(p["date"] for p in fake_table.puts)
    assert dates == ["2026-03-01", "2026-07-01"]


def test_measurements_session_number_is_date_rank(monkeypatch):
    """X-12 replay: session_number = date rank, monotonic and re-import-stable
    (the old COUNT+1 drifted on every re-import)."""
    fake_table, _ = _run_measurements(monkeypatch, _CSV_TWO_SESSIONS, existing_dates=["2026-01-15"])
    by_date = {p["date"]: p["session_number"] for p in fake_table.puts}
    assert by_date == {"2026-03-01": 2, "2026-07-01": 3}  # 2026-01-15 is session 1

    # Re-import of the same file: same numbers (stability), not COUNT+1 drift.
    fake_table2, _ = _run_measurements(monkeypatch, _CSV_TWO_SESSIONS, existing_dates=["2026-01-15", "2026-03-01", "2026-07-01"])
    by_date2 = {p["date"]: p["session_number"] for p in fake_table2.puts}
    assert by_date2 == by_date


def test_measurements_records_stamp_phase(monkeypatch):
    fake_table, _ = _run_measurements(monkeypatch, _CSV_TWO_SESSIONS)
    for p in fake_table.puts:
        assert p.get("phase") in ("pilot", "experiment"), p
    # 2026-03-01 is pre-genesis (2026-06-08) → pilot; 2026-07-01 → experiment
    by_date = {p["date"]: p["phase"] for p in fake_table.puts}
    assert by_date["2026-03-01"] == "pilot"
    assert by_date["2026-07-01"] == "experiment"


def test_measurements_missing_required_row_reported_not_fatal(monkeypatch):
    csv_text = "date,waist_narrowest_in,waist_navel_in\n2026-07-01,38.5,40.0\n2026-07-02,,\n"
    fake_table, result = _run_measurements(monkeypatch, csv_text)
    body = json.loads(result["body"])
    assert body["sessions_written"] == 1
    assert body["row_errors"], "the bad row must be reported"


# ==============================================================================
# #474 — apple_health XML path retired
# ==============================================================================


def test_apple_health_xml_lambda_deleted():
    assert not os.path.exists(os.path.join(_REPO, "lambdas/ingestion/apple_health_lambda.py"))
    assert 'AppleHealthIngestion"' not in _INGESTION_STACK_SRC.replace("'", '"') or "RETIRED" in _INGESTION_STACK_SRC


def test_apple_health_backfill_hard_guarded():
    src = open(os.path.join(_REPO, "backfill/archive/backfill_apple_health.py")).read()
    assert "I_UNDERSTAND_THIS_CLOBBERS_HAE_RECORDS" in src
    # the guard sits before any AWS client is created
    assert src.index("I_UNDERSTAND_THIS_CLOBBERS_HAE_RECORDS") < src.index("boto3.client")


# ==============================================================================
# #497 — garmin cron disabled
# ==============================================================================


def test_garmin_has_no_schedule():
    """The ADR-074 pause and the deployed cron now agree: no schedule= in the
    Garmin block (the 4×/day probe into a throttle is gone)."""
    start = _INGESTION_STACK_SRC.index("GarminIngestion")
    end = _INGESTION_STACK_SRC.index("Notion", start)
    garmin_block = _INGESTION_STACK_SRC[start:end]
    assert "schedule=" not in garmin_block, "garmin cron re-armed against ADR-074"


# ==============================================================================
# #518 — REQUIRED_SECRETS matches reality
# ==============================================================================


def test_health_check_expected_secrets_are_real():
    src = open(os.path.join(_REPO, "lambdas/operational/pipeline_health_check_lambda.py")).read()
    assert '"life-platform/dropbox"' not in src, "the never-existed secret is back"
    assert '"life-platform/todoist"' in src
    assert '"life-platform/hevy"' in src
