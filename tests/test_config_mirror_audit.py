"""#2057 — every live `config/` object a deployed module reads has an OWNER.

#2019 asserts repo twins. This audit asks the inverse question — of every object
that is live AND read, what asserts it? — so the writer classes the twin check
cannot see (runtime writes, out-of-band copies) stop being invisible.

The load-bearing tests here are the negative ones: a stale serving mirror must
FAIL, and the max-age it is judged against must come from the writer's own
declared window rather than a number chosen in the audit.
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone

import boto3
import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "deploy"))

import config_mirror_audit as audit_mod  # noqa: E402
import config_twin_registry as registry_mod  # noqa: E402

NOW = datetime(2026, 8, 3, 12, 0, 0, tzinfo=timezone.utc)


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


@pytest.fixture
def mirror_repo(tmp_path):
    """A repo with one of each owner class, all read by deployed code.

    * `config/widget_registry.json` — a plain repo twin.
    * `config/live_state.json` — written at runtime, with a declared 1h window,
      and read by the SERVING path (this is the class that must gate).
    * `seeds/imported_catalog.json` — a repo file outside `config/`.
    * `config/mystery.json` — nothing produces it.
    """
    root = str(tmp_path)
    _write(os.path.join(root, "config", "widget_registry.json"), json.dumps({"widgets": []}))
    _write(os.path.join(root, "seeds", "imported_catalog.json"), json.dumps({"items": []}))
    _write(
        os.path.join(root, "lambdas", "web", "fake_api.py"),
        "import boto3\n"
        's7 = boto3.client("s3")\n'
        "def handler(event, ctx):\n"
        '    s7.get_object(Bucket="b", Key="config/widget_registry.json")\n'
        '    s7.get_object(Bucket="b", Key="config/live_state.json")\n'
        '    s7.get_object(Bucket="b", Key="config/imported_catalog.json")\n'
        '    return s7.get_object(Bucket="b", Key="config/mystery.json")\n',
    )
    _write(
        os.path.join(root, "lambdas", "compute", "fake_writer.py"),
        "import boto3, os\n"
        's7 = boto3.client("s3")\n'
        'STATE_KEY = "config/live_state.json"\n'
        'CACHE_TTL_SECONDS = int(os.environ.get("CACHE_TTL", str(1 * 3600)))\n'
        "def run():\n"
        '    s7.put_object(Bucket="b", Key=STATE_KEY, Body=b"{}")\n',
    )
    return root


def _audit(root, ages, now=NOW):
    """Run the audit with {key: age_in_seconds}."""
    live = {key: now - timedelta(seconds=seconds) for key, seconds in ages.items()}
    registry = registry_mod.derive(root)
    return {f.key: f for f in audit_mod.audit(registry, live, root, now)}


# ─────────────────────────────────────────────────────────────────────────────
# The negative proof: a stale serving mirror FAILS, a fresh one passes
# ─────────────────────────────────────────────────────────────────────────────


def test_stale_serving_writer_mirror_fails(mirror_repo):
    """THE negative test — past the writer's declared window, on the serving path."""
    findings = _audit(mirror_repo, {"config/live_state.json": 4 * 3600})
    finding = findings["config/live_state.json"]

    assert finding.owner == audit_mod.OWNER_WRITER
    assert finding.serving is True
    assert finding.verdict == "fail"
    assert finding.max_age_seconds == 3600
    assert "STALE" in finding.detail


def test_fresh_serving_writer_mirror_passes(mirror_repo):
    """Restored inside the window, it clears — the other half of the proof."""
    findings = _audit(mirror_repo, {"config/live_state.json": 600})
    finding = findings["config/live_state.json"]

    assert finding.verdict == "ok"
    assert finding.age_seconds == 600
    assert "fresh" in finding.detail


def test_strict_summary_flips_with_the_mirror(mirror_repo):
    """End to end: the report the workflow gates on is clean, then is not."""
    registry = registry_mod.derive(mirror_repo)

    def report_for(age):
        live = {"config/live_state.json": NOW - timedelta(seconds=age)}
        return audit_mod.summarize(audit_mod.audit(registry, live, mirror_repo, NOW))

    assert report_for(600)["clean"] is True
    stale = report_for(4 * 3600)
    assert stale["clean"] is False
    assert stale["failures"] == ["config/live_state.json"]


# ─────────────────────────────────────────────────────────────────────────────
# The max-age comes from the WRITER, not from this module
# ─────────────────────────────────────────────────────────────────────────────


def test_max_age_follows_the_writers_declared_window(mirror_repo):
    """Re-declare the window in the writer; the audit's threshold must move.

    This is the freshness-window rule under test: the window encodes the
    WRITER's cadence, so an age that is stale under a 1h declaration must be
    fresh under a 6h one with no change to the audit.
    """
    before = _audit(mirror_repo, {"config/live_state.json": 4 * 3600})["config/live_state.json"]
    assert before.verdict == "fail" and before.max_age_seconds == 3600

    writer = os.path.join(mirror_repo, "lambdas", "compute", "fake_writer.py")
    with open(writer, encoding="utf-8") as handle:
        source = handle.read()
    _write(writer, source.replace("str(1 * 3600)", "str(6 * 3600)"))

    after = _audit(mirror_repo, {"config/live_state.json": 4 * 3600})["config/live_state.json"]
    assert after.max_age_seconds == 6 * 3600
    assert after.verdict == "ok"


def test_a_writer_with_no_declared_window_gets_no_freshness_assertion(mirror_repo):
    """No invented default — an undeclared window warns, it does not guess."""
    writer = os.path.join(mirror_repo, "lambdas", "compute", "fake_writer.py")
    with open(writer, encoding="utf-8") as handle:
        source = handle.read()
    _write(writer, source.replace("CACHE_TTL_SECONDS", "UNRELATED_NUMBER"))

    finding = _audit(mirror_repo, {"config/live_state.json": 900 * 24 * 3600})["config/live_state.json"]
    assert finding.max_age_seconds is None
    assert finding.verdict == "warn"


def test_static_int_folds_multiplication():
    """`24 * 3600` is how humans write a day, and literal_eval refuses it.

    Regression guard: without folding, every window written that way reads as
    "undeclared" and the freshness assertion silently never applies.
    """
    import ast

    assert audit_mod._static_int(ast.parse("int(os.environ.get('X', str(24 * 3600)))").body[0].value) == 86400
    assert audit_mod._static_int(ast.parse("900").body[0].value) == 900
    assert audit_mod._static_int(ast.parse("'not-a-number'").body[0].value) is None


# ─────────────────────────────────────────────────────────────────────────────
# Ownership classification
# ─────────────────────────────────────────────────────────────────────────────


def test_repo_twin_is_owned_and_not_freshness_checked(mirror_repo):
    """Byte equality (config_twin_sync) is strictly stronger than freshness."""
    finding = _audit(mirror_repo, {"config/widget_registry.json": 900 * 24 * 3600})["config/widget_registry.json"]
    assert finding.owner == audit_mod.OWNER_REPO_TWIN
    assert finding.verdict == "ok"
    assert finding.max_age_seconds is None


def test_a_repo_file_outside_config_is_a_weaker_owner(mirror_repo):
    """`seeds/` originals are traceable but nothing asserts the bytes match."""
    finding = _audit(mirror_repo, {"config/imported_catalog.json": 60})["config/imported_catalog.json"]
    assert finding.owner == audit_mod.OWNER_REPO_SOURCE
    assert finding.source == "seeds/imported_catalog.json"
    assert finding.verdict == "warn"


def test_unowned_serving_object_fails(mirror_repo):
    finding = _audit(mirror_repo, {"config/mystery.json": 60})["config/mystery.json"]
    assert finding.owner == audit_mod.OWNER_NONE
    assert finding.serving is True
    assert finding.verdict == "fail"


def test_objects_nothing_reads_are_not_audited(mirror_repo):
    """Ownership only matters where a reader is being told something."""
    findings = _audit(mirror_repo, {"config/nobody_reads_this.json": 900 * 24 * 3600})
    assert "config/nobody_reads_this.json" not in findings


def test_a_new_mirror_joins_the_audited_set_automatically(mirror_repo):
    """Derived, not enumerated — the acceptance criterion for the covered set."""
    baseline = _audit(mirror_repo, {"config/mystery.json": 60})
    assert "config/brand_new.json" not in baseline

    with open(os.path.join(mirror_repo, "lambdas", "web", "fake_api.py"), "a", encoding="utf-8") as handle:
        handle.write('\ndef more():\n    return s7.get_object(Bucket="b", Key="config/brand_new.json")\n')

    grown = _audit(mirror_repo, {"config/brand_new.json": 60})
    assert grown["config/brand_new.json"].owner == audit_mod.OWNER_NONE
    assert grown["config/brand_new.json"].verdict == "fail"


# ─────────────────────────────────────────────────────────────────────────────
# The real tree
# ─────────────────────────────────────────────────────────────────────────────


def test_real_repo_classifies_the_user_scoped_mirrors_as_aliases():
    """The two mirrors #2057 was filed about are now owned, not invisible."""
    registry = registry_mod.derive(REPO_ROOT)
    live = {
        "config/character_sheet.json": NOW,
        "config/matthew/character_sheet.json": NOW,
        "config/matthew/board_of_directors.json": NOW,
        "config/board_of_directors.json": NOW,
    }
    findings = {f.key: f for f in audit_mod.audit(registry, live, REPO_ROOT, NOW)}

    sheet = findings["config/matthew/character_sheet.json"]
    assert sheet.owner == audit_mod.OWNER_ALIAS
    assert sheet.source == "config/character_sheet.json"
    assert sheet.serving is True
    assert sheet.verdict == "ok"
    assert findings["config/matthew/board_of_directors.json"].owner == audit_mod.OWNER_ALIAS


def test_real_repo_derives_the_hevy_cache_window_from_its_writer():
    """The one genuine runtime-written mirror, judged by its OWN declared TTL.

    It is deliberately not a gating failure: the cache is written on a miss, not
    on a schedule, and no `lambdas/web/` module reads it — so a cron-shaped
    freshness gate over it would be a permanent false alarm.
    """
    registry = registry_mod.derive(REPO_ROOT)
    live = {"config/hevy_template_cache.json": NOW - timedelta(days=42)}
    finding = next(f for f in audit_mod.audit(registry, live, REPO_ROOT, NOW) if f.key == "config/hevy_template_cache.json")

    assert finding.owner == audit_mod.OWNER_WRITER
    assert finding.max_age_seconds == 24 * 3600
    assert "hevy_template_cache.py:TTL_SECONDS" in finding.detail
    assert finding.serving is False
    assert finding.verdict == "warn"


def test_real_repo_has_no_unowned_serving_mirror():
    """The gate as it stands on main — green, and not green vacuously."""
    registry = registry_mod.derive(REPO_ROOT)
    live = {t.key: NOW for t in registry.twins}
    live.update({key: NOW for key in ("config/matthew/character_sheet.json", "config/matthew/board_of_directors.json")})
    findings = audit_mod.audit(registry, live, REPO_ROOT, NOW)

    assert len(findings) > 20, "audit found almost nothing — it would pass vacuously"
    assert [f.key for f in findings if f.verdict == "fail"] == []


# ─────────────────────────────────────────────────────────────────────────────
# #2789 — an empty live listing must FAIL, not pass vacuously
# ─────────────────────────────────────────────────────────────────────────────


def test_population_floor_is_derived_from_the_tracked_twin_set(mirror_repo):
    """Never hand-typed — it tracks the registry's own twin count."""
    registry = registry_mod.derive(mirror_repo)
    assert audit_mod.population_floor(registry) == len(registry.twins) == 1


def test_build_report_fails_loud_on_an_empty_listing(mirror_repo):
    """THE regression for #2789: zero live objects must not summarize clean.

    Before the fix, `audit()` over an empty `live` dict returns zero findings
    (nothing to iterate), and `summarize([])` sets `clean: not [] == True` —
    an audit that checked nothing reports itself as a clean mirror. That is
    exactly the vacuous-empty class #2639 flagged live.
    """
    registry = registry_mod.derive(mirror_repo)
    report = audit_mod.build_report(registry, {}, mirror_repo, NOW)

    assert report["clean"] is False
    assert report["population_floor_error"]
    assert report["population_floor"] == 1


def test_build_report_runs_the_normal_audit_once_the_floor_is_met(mirror_repo):
    """The floor gates only a broken listing — a real (if partial) one still audits."""
    registry = registry_mod.derive(mirror_repo)
    live = {"config/widget_registry.json": NOW}
    report = audit_mod.build_report(registry, live, mirror_repo, NOW)

    assert "population_floor_error" not in report
    assert report["audited"] == 1
    assert report["clean"] is True


def test_real_repo_population_floor_reds_an_empty_listing():
    """Same proof against the real repo's registry, not just the fixture."""
    registry = registry_mod.derive(REPO_ROOT)
    report = audit_mod.build_report(registry, {}, REPO_ROOT, NOW)

    assert report["clean"] is False
    assert report["population_floor"] > 20


def test_main_exits_nonzero_on_an_empty_live_listing(monkeypatch):
    """End-to-end mutation proof: a real (empty) ListObjectsV2 response must
    fail the CLI run, not exit 0.

    The fake client's response is shaped like the actual boto3 wire body for
    zero objects — `Contents` omitted, `IsTruncated` present — not an
    idealized `{}`, per the fixture-must-be-the-wire discipline. Only
    `boto3.client` is patched; `main()` drives the real repo's registry and
    the real `_live_objects` pagination loop against this fake.
    """

    class _EmptyS3Client:
        def list_objects_v2(self, **kwargs):
            assert kwargs["Bucket"] == audit_mod.S3_BUCKET
            assert kwargs["Prefix"] == registry_mod.S3_CONFIG_PREFIX
            return {"IsTruncated": False}  # no "Contents" key == zero objects, wire-shaped

    monkeypatch.setattr(boto3, "client", lambda *a, **k: _EmptyS3Client())
    monkeypatch.setattr(sys, "argv", ["config_mirror_audit.py", "--strict"])

    assert audit_mod.main() == 1


def test_main_exits_nonzero_on_empty_listing_even_without_strict(monkeypatch):
    """A broken listing fails loud regardless of --strict — it never got to audit anything."""

    class _EmptyS3Client:
        def list_objects_v2(self, **kwargs):
            return {"IsTruncated": False}

    monkeypatch.setattr(boto3, "client", lambda *a, **k: _EmptyS3Client())
    monkeypatch.setattr(sys, "argv", ["config_mirror_audit.py"])

    assert audit_mod.main() == 1


# ─────────────────────────────────────────────────────────────────────────────
# #2789 — the AST walk must see AnnAssign TTLs, not just plain Assign
# ─────────────────────────────────────────────────────────────────────────────


def test_writer_max_age_finds_an_annotated_ttl_constant(mirror_repo):
    """`TTL_SECONDS: int = 900` is an ast.AnnAssign, not an ast.Assign.

    Before the fix, `writer_max_age`'s walk matched only `ast.Assign`, so an
    annotated TTL constant read as "no window declared" — silently
    downgrading the stale-serving FAIL class to a warn for any writer that
    happens to type-annotate its constant.
    """
    writer = os.path.join(mirror_repo, "lambdas", "compute", "fake_writer.py")
    with open(writer, encoding="utf-8") as handle:
        source = handle.read()
    _write(
        writer,
        source.replace(
            'CACHE_TTL_SECONDS = int(os.environ.get("CACHE_TTL", str(1 * 3600)))',
            'CACHE_TTL_SECONDS: int = int(os.environ.get("CACHE_TTL", str(1 * 3600)))',
        ),
    )

    seconds, declared_by = audit_mod.writer_max_age(mirror_repo, ("lambdas/compute/fake_writer.py",))
    assert seconds == 3600
    assert declared_by == "lambdas/compute/fake_writer.py:CACHE_TTL_SECONDS"


def test_annassign_ttl_flows_through_the_full_audit_and_still_gates(mirror_repo):
    """Not just the AST helper in isolation — the annotated form still fails stale/serving."""
    writer = os.path.join(mirror_repo, "lambdas", "compute", "fake_writer.py")
    with open(writer, encoding="utf-8") as handle:
        source = handle.read()
    _write(
        writer,
        source.replace(
            'CACHE_TTL_SECONDS = int(os.environ.get("CACHE_TTL", str(1 * 3600)))',
            'CACHE_TTL_SECONDS: int = int(os.environ.get("CACHE_TTL", str(1 * 3600)))',
        ),
    )

    findings = _audit(mirror_repo, {"config/live_state.json": 4 * 3600})
    finding = findings["config/live_state.json"]

    assert finding.max_age_seconds == 3600
    assert finding.verdict == "fail"
    assert "STALE" in finding.detail


def test_annassign_with_no_value_is_ignored_not_crashed_on(mirror_repo):
    """`TTL_SECONDS: int` (annotation only, no value) must not raise.

    A bare annotation is a legal forward-declaration in Python; the walk has
    to skip it exactly like an unmatched name, not choke on `node.value` being
    `None`.
    """
    writer = os.path.join(mirror_repo, "lambdas", "compute", "fake_writer.py")
    with open(writer, encoding="utf-8") as handle:
        source = handle.read()
    _write(writer, source + "\nTTL_SECONDS_FORWARD_DECL: int\n")

    seconds, declared_by = audit_mod.writer_max_age(mirror_repo, ("lambdas/compute/fake_writer.py",))
    assert seconds == 3600  # the real CACHE_TTL_SECONDS assign, unaffected
    assert declared_by == "lambdas/compute/fake_writer.py:CACHE_TTL_SECONDS"
