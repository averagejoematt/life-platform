"""tests/test_qa_check_outputs_behavior.py — behavioural contracts for
``lambdas/operational/qa_check_outputs.py`` (#1658 coverage tranche 5).

Measured 9.6% covered before this file (160 of 177 statements missing). This
module is the AWS-surface half of qa-smoke: five checks that decide, nightly,
whether the platform's stored outputs are honest. Three fleet auto-rollbacks
have fired off this sweep's verdicts, so the *partition* each check assigns
(DEPLOY_HEALTH vs CONTENT_TRUTH, #1921) is not a label — it is the switch that
decides whether a finding may revert 100 Lambdas. None of it was exercised.

Contracts pinned here:

  * **Partition assignment per check.** A content-truth finding must never
    arrive wearing the deploy-health partition, because ci-cd wires only the
    latter to rollback and reverting code cannot un-publish a stale number.
  * **The freshness windows are the writer's cadence, not a guess** (#2287's
    class): data.json has ONE writer, the 17:00 UTC daily brief, so 26h is
    green-at-25h / red-at-27h and both sides are pinned.
  * **Non-critical means warn, critical means fail** — on both the stale path
    and the exception path, for the same key.
  * **ADR-104 honest zeroes**: a null metric on an optional field is a WARN
    ("may not have synced"), a null on a required one is a FAIL, and neither is
    ever silently coerced to a passing 0.
  * **Genesis grace is a dated window, not a permanent softener** — the same
    three checks that soften on Day 1 go hard again from Day 2, and the
    softening is driven through the real ``common.constants`` /
    ``common.pacific_time`` seam rather than a flag the test invents.

No AWS and no network: ``qa_check_outputs.s3`` and ``boto3.client`` are
replaced with bounded fakes that record their calls.
"""

from __future__ import annotations

import os

# qa_check_outputs reads S3_BUCKET at import time (conftest supplies fake creds).
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("EMAIL_RECIPIENT", "qa@example.com")
os.environ.setdefault("EMAIL_SENDER", "qa@example.com")

import io  # noqa: E402
import json  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402

import pytest  # noqa: E402
from operational import qa_check_outputs as qco  # noqa: E402
from operational.qa_check import CONTENT_TRUTH, DEPLOY_HEALTH  # noqa: E402

NOW = datetime.now(timezone.utc)


def _by_name(checks):
    return {c.name: c for c in checks}


# ──────────────────────────────────────────────────────────────────────────────
# Fake S3
# ──────────────────────────────────────────────────────────────────────────────


class _FakeS3:
    def __init__(self, heads=None, objects=None, listing=None, raise_on=frozenset()):
        self.heads = heads or {}
        self.objects = objects or {}
        self.listing = listing or {}
        self.raise_on = raise_on
        self.head_calls: list[str] = []

    def head_object(self, Bucket, Key):
        self.head_calls.append(Key)
        if Key in self.raise_on or Key not in self.heads:
            raise RuntimeError(f"404 {Key}")
        return {"LastModified": self.heads[Key]}

    def get_object(self, Bucket, Key):
        if Key in self.raise_on or Key not in self.objects:
            raise RuntimeError(f"404 {Key}")
        return {"Body": io.BytesIO(self.objects[Key])}

    def get_paginator(self, op):
        listing = self.listing
        raise_on = self.raise_on

        class _P:
            def paginate(self, Bucket=None, Prefix="", **kw):
                if f"list:{Prefix}" in raise_on:
                    raise RuntimeError("AccessDenied")
                keys = [k for k in listing if k.startswith(Prefix)]
                # Two pages, to exercise the pagination loop.
                yield {"Contents": [{"Key": k} for k in keys[:1]]}
                yield {"Contents": [{"Key": k} for k in keys[1:]]}

        return _P()


@pytest.fixture()
def fake_s3(monkeypatch):
    def _install(**kw):
        s3 = _FakeS3(**kw)
        monkeypatch.setattr(qco, "s3", s3)
        return s3

    return _install


# ──────────────────────────────────────────────────────────────────────────────
# check_s3_freshness
# ──────────────────────────────────────────────────────────────────────────────

DASH = "dashboard/matthew/data.json"
CLIN = "dashboard/matthew/clinical.json"


def test_s3_freshness_green_inside_the_daily_writers_window(fake_s3):
    fake_s3(heads={DASH: NOW - timedelta(hours=25), CLIN: NOW - timedelta(hours=1)})
    checks = _by_name(qco.check_s3_freshness())
    assert checks[f"S3:{DASH}"].passed is True
    assert "25.0h ago" in checks[f"S3:{DASH}"].message


def test_s3_freshness_reds_only_once_the_daily_writer_actually_missed_a_cycle(fake_s3):
    """26h is the window because data.json's ONLY writer is the 17:00 UTC daily
    brief — a 4h window was stale-by-design for ~20h a day and rolled back 98
    functions on 2026-07-27."""
    fake_s3(heads={DASH: NOW - timedelta(hours=27), CLIN: NOW})
    checks = _by_name(qco.check_s3_freshness())
    c = checks[f"S3:{DASH}"]
    assert c.passed is False
    assert "STALE" in c.message and "max 26h" in c.message


def test_s3_freshness_downgrades_the_non_critical_file_to_a_warn(fake_s3):
    fake_s3(heads={DASH: NOW, CLIN: NOW - timedelta(hours=48)})
    c = _by_name(qco.check_s3_freshness())[f"S3:{CLIN}"]
    assert c.passed is None, "clinical.json is non-critical: yellow, never a rollback-eligible red"
    assert "non-critical" in c.message


def test_s3_freshness_error_path_respects_the_same_criticality_split(fake_s3):
    fake_s3(heads={}, raise_on={DASH, CLIN})
    checks = _by_name(qco.check_s3_freshness())
    assert checks[f"S3:{DASH}"].passed is False and "error:" in checks[f"S3:{DASH}"].message
    assert checks[f"S3:{CLIN}"].passed is None and "non-critical" in checks[f"S3:{CLIN}"].message


def test_s3_freshness_reports_the_dormant_buddy_surface_as_paused_not_failed(fake_s3):
    fake_s3(heads={DASH: NOW, CLIN: NOW})
    c = _by_name(qco.check_s3_freshness())["S3:buddy/data.json"]
    assert c.paused is True and c.passed is True, "a deliberately-dormant surface is visible but never a fault"


def test_s3_freshness_checks_are_all_content_truth(fake_s3):
    fake_s3(heads={DASH: NOW, CLIN: NOW})
    assert {c.partition for c in qco.check_s3_freshness()} == {
        CONTENT_TRUTH
    }, "#1921: reverting a deploy cannot make a stale artifact fresh — these must never be rollback-eligible"


# ──────────────────────────────────────────────────────────────────────────────
# check_score_sanity
# ──────────────────────────────────────────────────────────────────────────────


def _dashboard(**over):
    doc = {
        "date": qco._yesterday_str(),
        "readiness": {"score": 62},
        "sleep": {"score": 78},
        "weight": {"current": 318.4},
        "hrv": {"value": 44},
        "glucose": {"avg": 96},
        "day_grade": {"letter": "B", "score": 84, "components": {"hydration": 72}},
        "character_sheet": {"level": 7, "tier": "discipline", "xp": 12345},
    }
    doc.update(over)
    return doc


@pytest.fixture()
def dashboard_s3(fake_s3):
    def _install(doc, **kw):
        return fake_s3(objects={DASH: json.dumps(doc).encode()}, **kw)

    return _install


@pytest.fixture()
def no_grace(monkeypatch):
    """Force the post-genesis (strict) frame: genesis well in the past."""
    from common import constants, pacific_time

    monkeypatch.setattr(constants, "EXPERIMENT_START_DATE", "2026-01-01", raising=False)
    monkeypatch.setattr(pacific_time, "pacific_today", lambda: "2026-08-08")
    return None


@pytest.fixture()
def in_grace(monkeypatch):
    """Force the pre-start / Day-1 frame."""
    from common import constants, pacific_time

    monkeypatch.setattr(constants, "EXPERIMENT_START_DATE", "2026-08-08", raising=False)
    monkeypatch.setattr(pacific_time, "pacific_today", lambda: "2026-08-08")
    return None


def test_score_sanity_all_green_on_a_healthy_dashboard(dashboard_s3, no_grace):
    dashboard_s3(_dashboard())
    checks = qco.check_score_sanity()
    reds = [c.name for c in checks if c.passed is False]
    assert reds == [], f"a healthy dashboard must be all-green, got reds: {reds}"
    assert {c.partition for c in checks} == {CONTENT_TRUTH}


def test_score_sanity_reports_an_unreadable_dashboard_as_one_parse_failure(fake_s3):
    fake_s3(objects={}, raise_on={DASH})
    (c,) = qco.check_score_sanity()
    assert c.name == "dashboard:parse" and c.passed is False
    assert "Cannot load" in c.message


def test_score_sanity_reds_a_stale_date(dashboard_s3, no_grace):
    dashboard_s3(_dashboard(date="2020-01-01"))
    c = _by_name(qco.check_score_sanity())["dashboard:date"]
    assert c.passed is False and "Stale date" in c.message


def test_score_sanity_reds_a_missing_date(dashboard_s3, no_grace):
    dashboard_s3(_dashboard(date=""))
    c = _by_name(qco.check_score_sanity())["dashboard:date"]
    assert c.passed is False and "missing" in c.message


def test_score_sanity_a_future_date_is_a_red_after_genesis_but_a_warn_inside_the_grace(dashboard_s3, no_grace, monkeypatch):
    ahead = (datetime.now(timezone.utc) + timedelta(days=3)).strftime("%Y-%m-%d")
    dashboard_s3(_dashboard(date=ahead))
    assert _by_name(qco.check_score_sanity())["dashboard:date"].passed is False

    from common import constants, pacific_time

    monkeypatch.setattr(constants, "EXPERIMENT_START_DATE", "2026-08-08", raising=False)
    monkeypatch.setattr(pacific_time, "pacific_today", lambda: "2026-08-08")
    dashboard_s3(_dashboard(date=ahead))
    c = _by_name(qco.check_score_sanity())["dashboard:date"]
    assert c.passed is None and "self-heals" in c.message


@pytest.mark.parametrize(
    "field,payload,name",
    [
        ("readiness", {"score": None}, "value:readiness"),
        ("sleep", {"score": None}, "value:sleep"),
        ("hrv", {"value": None}, "value:hrv"),
        ("glucose", {"avg": None}, "value:glucose"),
    ],
)
def test_score_sanity_optional_nulls_warn_rather_than_fabricate_a_zero(dashboard_s3, no_grace, field, payload, name):
    """ADR-104: a metric the sensor did not report is absent. Yellow, not a
    passing 0 and not a red."""
    dashboard_s3(_dashboard(**{field: payload}))
    c = _by_name(qco.check_score_sanity())[name]
    assert c.passed is None
    assert "null" in c.message and "may not have synced" in c.message


def test_score_sanity_weight_null_is_a_red_after_genesis_and_a_warn_inside_the_grace(dashboard_s3, no_grace, in_grace, monkeypatch):
    from common import constants, pacific_time

    # strict frame first
    monkeypatch.setattr(constants, "EXPERIMENT_START_DATE", "2026-01-01", raising=False)
    monkeypatch.setattr(pacific_time, "pacific_today", lambda: "2026-08-08")
    dashboard_s3(_dashboard(weight={"current": None}))
    assert _by_name(qco.check_score_sanity())["value:weight"].passed is False

    # pre-genesis: no Withings weigh-in yet IS the honest state
    monkeypatch.setattr(constants, "EXPERIMENT_START_DATE", "2026-08-08", raising=False)
    dashboard_s3(_dashboard(weight={"current": None}))
    assert _by_name(qco.check_score_sanity())["value:weight"].passed is None


@pytest.mark.parametrize(
    "field,payload,name",
    [
        ("readiness", {"score": 140}, "value:readiness"),
        ("weight", {"current": 40}, "value:weight"),
        ("hrv", {"value": 900}, "value:hrv"),
        ("glucose", {"avg": 5.4}, "value:glucose"),  # mmol/L leaking into an mg/dL field
    ],
)
def test_score_sanity_reds_values_outside_their_plausible_range(dashboard_s3, no_grace, field, payload, name):
    dashboard_s3(_dashboard(**{field: payload}))
    c = _by_name(qco.check_score_sanity())[name]
    assert c.passed is False and "outside plausible range" in c.message


def test_score_sanity_day_grade_absent_is_expected_only_for_a_pre_genesis_day(dashboard_s3, no_grace, monkeypatch):
    from common import constants

    monkeypatch.setattr(qco, "EXPERIMENT_START_DATE", "2026-08-01", raising=False)
    monkeypatch.setattr(constants, "EXPERIMENT_START_DATE", "2026-01-01", raising=False)

    # A day BEFORE genesis legitimately has no grade.
    dashboard_s3(_dashboard(date="2026-07-20", day_grade={}))
    c = _by_name(qco.check_score_sanity())["score:day_grade"]
    assert c.passed is True and "pre-genesis" in c.message

    # A day after genesis with no grade is a real red.
    dashboard_s3(_dashboard(day_grade={}))
    c = _by_name(qco.check_score_sanity())["score:day_grade"]
    assert c.passed is False and "Day grade missing" in c.message


def test_score_sanity_hydration_bands(dashboard_s3, no_grace):
    dashboard_s3(_dashboard(day_grade={"letter": "B", "score": 84, "components": {}}))
    c = _by_name(qco.check_score_sanity())["score:hydration"]
    assert c.passed is None and "didn't sync" in c.message

    dashboard_s3(_dashboard(day_grade={"letter": "B", "score": 84, "components": {"hydration": 12}}))
    c = _by_name(qco.check_score_sanity())["score:hydration"]
    assert c.passed is None and "low" in c.message

    dashboard_s3(_dashboard(day_grade={"letter": "B", "score": 84, "components": {"hydration": 30}}))
    assert _by_name(qco.check_score_sanity())["score:hydration"].passed is True


def test_score_sanity_character_sheet_absent_reds_after_genesis_warns_inside_grace(dashboard_s3, no_grace, monkeypatch):
    dashboard_s3(_dashboard(character_sheet={}))
    c = _by_name(qco.check_score_sanity())["character_sheet"]
    assert c.passed is False and "Character sheet missing" in c.message

    from common import constants

    monkeypatch.setattr(constants, "EXPERIMENT_START_DATE", "2026-08-08", raising=False)
    dashboard_s3(_dashboard(character_sheet={}))
    c = _by_name(qco.check_score_sanity())["character_sheet"]
    assert c.passed is None and "wiped at reset" in c.message


def test_score_sanity_grace_derivation_never_breaks_the_sweep(dashboard_s3, monkeypatch):
    """The `except: _genesis_grace = False` arm — a broken constants import must
    make the sweep STRICTER, never crash it."""
    from common import pacific_time

    monkeypatch.setattr(pacific_time, "pacific_today", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    dashboard_s3(_dashboard(character_sheet={}))
    c = _by_name(qco.check_score_sanity())["character_sheet"]
    assert c.passed is False, "an unresolvable genesis must fall back to the strict frame"


@pytest.mark.xfail(
    strict=True,
    reason=(
        "DEFECT: a dashboard whose `day_grade` key is present but null crashes "
        "the whole score-sanity sweep. Lines 146-147 read it defensively as "
        "`(data.get('day_grade') or {})`, but line 148 reads "
        "`data.get('day_grade', {}).get('components')` — the default only "
        "applies to a MISSING key, so an explicit null raises "
        "AttributeError: 'NoneType' object has no attribute 'get'. Because "
        "qa_smoke_lambda accumulates `all_checks += check_score_sanity()` inside "
        "one try, that single bad field aborts every remaining check in the "
        "nightly sweep rather than reporting one red. Correct behaviour: the "
        "same `or {}` guard the two adjacent lines already use, degrading to the "
        "'Hydration null' warn. Reported by #1658 coverage tranche 5; not fixed here."
    ),
)
def test_defect_score_sanity_survives_a_null_day_grade(dashboard_s3, no_grace):
    dashboard_s3(_dashboard(day_grade=None))
    c = _by_name(qco.check_score_sanity())["score:hydration"]
    assert c.passed is None and "didn't sync" in c.message


# ──────────────────────────────────────────────────────────────────────────────
# check_blog_links
# ──────────────────────────────────────────────────────────────────────────────

INDEX_KEY = "blog/index.html"


def test_blog_links_all_resolve(fake_s3):
    # Historical slug shape, per redirects.map: /journal/posts/week-04/ …
    html = b'<a href="week-04.html">one</a><a href="week-05.html">two</a>'
    fake_s3(objects={INDEX_KEY: html}, listing={INDEX_KEY: 1, "blog/week-04.html": 1, "blog/week-05.html": 1})
    (c,) = qco.check_blog_links()
    assert c.passed is True and "All 2 blog post link(s) resolve" in c.message


def test_blog_links_reds_and_names_every_broken_link(fake_s3):
    html = b'<a href="week-04.html">one</a><a href="week-99.html">gone</a>'
    fake_s3(objects={INDEX_KEY: html}, listing={INDEX_KEY: 1, "blog/week-04.html": 1})
    (c,) = qco.check_blog_links()
    assert c.passed is False
    assert "1 broken link(s): week-99.html" in c.message


def test_blog_links_regex_cannot_see_a_hyphenated_slug(fake_s3):
    """Census note, not a live defect: the link regex is
    ``href="(week-[\\w.]+\\.html)"`` and ``[\\w.]`` excludes ``-``, so a
    date-style slug such as ``week-2026-01.html`` is invisible to the check
    (reported as "no links" rather than checked). The retired corpus used
    ``week-NN``/``week-YYYY.MM.DD`` shapes, both of which DO match, so nothing
    was ever silently unchecked in production — but a revived blog that dates
    its slugs with hyphens would get a green from an empty sweep."""
    fake_s3(objects={INDEX_KEY: b'<a href="week-2026-01.html">one</a>'}, listing={INDEX_KEY: 1})
    (c,) = qco.check_blog_links()
    assert c.passed is None and "No week-*.html links found" in c.message

    # The dotted historical form is seen.
    fake_s3(objects={INDEX_KEY: b'<a href="week-2026.03.08.html">one</a>'}, listing={INDEX_KEY: 1, "blog/week-2026.03.08.html": 1})
    (c,) = qco.check_blog_links()
    assert c.passed is True


def test_blog_links_missing_index_is_non_critical(fake_s3):
    fake_s3(objects={})
    (c,) = qco.check_blog_links()
    assert c.name == "blog:index" and c.passed is None and "non-critical" in c.message


def test_blog_links_unlistable_bucket_is_a_hard_fail(fake_s3):
    fake_s3(objects={INDEX_KEY: b'<a href="week-1.html">x</a>'}, raise_on={"list:blog/"})
    (c,) = qco.check_blog_links()
    assert c.name == "blog:list" and c.passed is False


def test_blog_links_an_index_with_no_week_links_warns(fake_s3):
    fake_s3(objects={INDEX_KEY: b"<p>coming soon</p>"}, listing={INDEX_KEY: 1})
    (c,) = qco.check_blog_links()
    assert c.passed is None and "No week-*.html links" in c.message


def test_census_check_blog_links_is_no_longer_wired_into_the_sweep():
    """#1658 census note: qa_smoke_lambda imports check_blog_links but its run
    list appends a hand-built PAUSED Check for blog:links instead of calling it
    (blog moved to /story/ in v4). The coverage above therefore exercises an
    orphan. Recorded so a future reader does not mistake it for a live gate."""
    import pathlib
    import re

    src = (pathlib.Path(__file__).resolve().parents[1] / "lambdas" / "operational" / "qa_smoke_lambda.py").read_text(encoding="utf-8")
    assert not re.search(r"check_blog_links\(\)", src), "check_blog_links is live again — delete this census note"
    assert "check_blog_links," in src, "the import is gone too — the orphan was cleaned up; delete this test"


# ──────────────────────────────────────────────────────────────────────────────
# check_lambda_secrets
# ──────────────────────────────────────────────────────────────────────────────


class _FakeAwsClient:
    def __init__(self, pages, boom=False):
        self._pages = pages
        self._boom = boom

    def get_paginator(self, op):
        pages, boom = self._pages, self._boom

        class _P:
            def paginate(self, **kw):
                if boom:
                    raise RuntimeError("AccessDenied")
                yield from pages

        return _P()


@pytest.fixture()
def fake_aws(monkeypatch):
    def _install(secrets_pages, lambda_pages, secrets_boom=False, lambda_boom=False):
        def _client(name, region_name=None):
            if name == "secretsmanager":
                return _FakeAwsClient(secrets_pages, secrets_boom)
            if name == "lambda":
                return _FakeAwsClient(lambda_pages, lambda_boom)
            raise AssertionError(f"unexpected client {name}")

        monkeypatch.setattr(qco.boto3, "client", _client)

    return _install


def _fn(name, secret=None):
    env = {"Variables": {"SECRET_NAME": secret}} if secret else {}
    return {"FunctionName": name, "Environment": env}


def test_lambda_secrets_green_when_every_reference_resolves(fake_aws):
    fake_aws(
        [{"SecretList": [{"Name": "life-platform/whoop", "DeletedDate": None}, {"Name": "life-platform/withings", "DeletedDate": None}]}],
        [{"Functions": [_fn("whoop-data-ingestion", "life-platform/whoop"), _fn("no-secret-fn")]}],
    )
    (c,) = qco.check_lambda_secrets()
    assert c.passed is True
    assert "2 secrets in inventory" in c.message
    assert c.partition == DEPLOY_HEALTH, "#1921: a broken secret reference IS the deploy's fault and IS rollback-eligible"


def test_lambda_secrets_reds_a_reference_to_a_deleted_secret(fake_aws):
    fake_aws(
        [{"SecretList": [{"Name": "life-platform/whoop", "DeletedDate": "2026-08-01"}]}],
        [{"Functions": [_fn("whoop-data-ingestion", "life-platform/whoop")]}],
    )
    (c,) = qco.check_lambda_secrets()
    assert c.passed is False
    assert "whoop-data-ingestion → life-platform/whoop" in c.message


def test_lambda_secrets_reds_a_reference_to_a_secret_that_never_existed(fake_aws):
    fake_aws([{"SecretList": []}], [{"Functions": [_fn("a", "life-platform/typo"), _fn("b", "life-platform/typo2")]}])
    (c,) = qco.check_lambda_secrets()
    assert c.passed is False and "2 stale SECRET_NAME(s)" in c.message


def test_lambda_secrets_reports_an_inventory_failure_separately_from_a_sweep_failure(fake_aws):
    fake_aws([], [], secrets_boom=True)
    (c,) = qco.check_lambda_secrets()
    assert c.name == "secrets:inventory" and c.passed is False

    fake_aws([{"SecretList": []}], [], lambda_boom=True)
    (c,) = qco.check_lambda_secrets()
    assert c.name == "secrets:sweep" and c.passed is False


# ──────────────────────────────────────────────────────────────────────────────
# check_avatar_assets
# ──────────────────────────────────────────────────────────────────────────────

_ALL_SPRITES = {
    f"dashboard/avatar/base/{t}-frame{f}.png": 1 for t in ("foundation", "momentum", "discipline", "mastery", "elite") for f in (1, 2, 3)
}


def test_avatar_assets_green_when_all_fifteen_sprites_exist(fake_s3):
    fake_s3(listing=dict(_ALL_SPRITES))
    (c,) = qco.check_avatar_assets()
    assert c.passed is True and "All 15 avatar sprites present" in c.message
    assert c.partition == CONTENT_TRUTH


def test_avatar_assets_names_the_missing_sprites(fake_s3):
    partial = dict(_ALL_SPRITES)
    del partial["dashboard/avatar/base/elite-frame3.png"]
    fake_s3(listing=partial)
    (c,) = qco.check_avatar_assets()
    assert c.passed is False
    assert "Missing 1/15 sprites: elite-frame3.png" in c.message


def test_avatar_assets_missing_list_permission_is_non_critical(fake_s3):
    fake_s3(listing={}, raise_on={"list:dashboard/avatar/base/"})
    (c,) = qco.check_avatar_assets()
    assert c.passed is None and "non-critical" in c.message


# ──────────────────────────────────────────────────────────────────────────────
# _yesterday_str
# ──────────────────────────────────────────────────────────────────────────────


def test_yesterday_str_is_derived_from_the_one_pacific_frame(monkeypatch):
    """#1964: the module must read the DST-aware Pacific clock, not a UTC
    subtraction — the data is keyed by the Pacific day."""
    from common import pacific_time

    monkeypatch.setattr(pacific_time, "pacific_now", lambda: datetime(2026, 8, 8, 0, 30, tzinfo=timezone.utc))
    assert qco._yesterday_str() == "2026-08-07"
