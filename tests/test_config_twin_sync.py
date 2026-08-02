"""#2019 — the bucket-root `config/` deploy path + drift check.

The incident: repo `config/` had no deploy path, so a merged correction never
reached S3 and `/api/supplements` served withdrawn citations for ~13h with CI
green throughout. These tests guard the two halves of the fix — that the twin
set is DERIVED (a new twin joins on its own) and that drift actually FIRES.
"""

import json
import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "deploy"))

import config_twin_registry as registry_mod  # noqa: E402
import config_twin_sync as sync_mod  # noqa: E402

# ─────────────────────────────────────────────────────────────────────────────
# Fixture repo — a miniature checkout the derivation runs against
# ─────────────────────────────────────────────────────────────────────────────


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


@pytest.fixture
def fake_repo(tmp_path):
    """A miniature repo: two config twins, one consumed, one runtime-written."""
    root = str(tmp_path)
    _write(os.path.join(root, "config", "widget_registry.json"), json.dumps({"widgets": []}))
    _write(os.path.join(root, "config", "runtime_state.json"), json.dumps({"live": True}))
    _write(os.path.join(root, "config", "README.md"), "# not a twin\n")
    _write(
        os.path.join(root, "lambdas", "web", "fake_api.py"),
        "import boto3\n"
        's3 = boto3.client("s3")\n'
        "def handler(event, ctx):\n"
        '    return s3.get_object(Bucket="b", Key="config/widget_registry.json")\n',
    )
    _write(
        os.path.join(root, "lambdas", "compute", "fake_writer.py"),
        "import boto3\n"
        's3 = boto3.client("s3")\n'
        'STATE_KEY = "config/runtime_state.json"\n'
        "def _put(key, body):\n"
        '    s3.put_object(Bucket="b", Key=key, Body=body)\n'
        "def run():\n"
        '    _put(STATE_KEY, b"{}")\n',
    )
    return root


# ─────────────────────────────────────────────────────────────────────────────
# The set is DERIVED, not enumerated
# ─────────────────────────────────────────────────────────────────────────────


def test_new_repo_twin_joins_the_set_automatically(fake_repo):
    """Acceptance: a NEWLY ADDED repo config twin joins the derived set with no
    edit to any list — guard the set, not the instance."""
    before = registry_mod.derive(fake_repo)
    assert "config/newly_added.json" not in before.by_key()

    _write(os.path.join(fake_repo, "config", "newly_added.json"), "{}")
    _write(
        os.path.join(fake_repo, "lambdas", "web", "new_consumer.py"),
        "import boto3\n" 's3 = boto3.client("s3")\n' "def go():\n" '    return s3.get_object(Bucket="b", Key="config/newly_added.json")\n',
    )

    after = registry_mod.derive(fake_repo).by_key()
    assert "config/newly_added.json" in after, "a new repo config twin must join the deploy path on its own"
    assert after["config/newly_added.json"].consumed


def test_runtime_written_key_is_excluded(fake_repo):
    """Syncing a Lambda-written key would clobber live state. The writer here is
    reached only through a helper (`_put(key, ...)`), the exact shape that hid
    `config/hevy_template_cache.json` from a naive scan."""
    reg = registry_mod.derive(fake_repo)
    assert "config/runtime_state.json" in reg.runtime_written
    assert "config/runtime_state.json" not in reg.by_key()


def test_docs_and_examples_are_not_twins(fake_repo):
    reg = registry_mod.derive(fake_repo)
    assert "config/README.md" not in reg.by_key()
    assert "config/README.md" in reg.excluded_not_twin


# ─────────────────────────────────────────────────────────────────────────────
# The real repo — regression anchors on the derivation itself
# ─────────────────────────────────────────────────────────────────────────────


def test_real_repo_derivation_covers_the_incident_files():
    reg = registry_mod.derive(REPO_ROOT)
    keys = reg.by_key()
    # The two objects that served stale content in the 2026-08-02 incident.
    assert "config/supplement_registry.json" in keys
    assert "config/experiment_library.json" in keys
    assert keys["config/supplement_registry.json"].consumed
    assert keys["config/experiment_library.json"].consumed


def test_real_repo_has_no_unresolvable_config_writers():
    """A `config/` write whose key we cannot resolve statically cannot be proven
    safe to sync over. Rather than guessing, the derivation reports it and this
    test reds — forcing a human to classify the new writer."""
    reg = registry_mod.derive(REPO_ROOT)
    assert reg.unresolved_writers == [], f"classify these config/ write sites: {reg.unresolved_writers}"


def test_real_repo_excludes_the_known_runtime_written_key():
    reg = registry_mod.derive(REPO_ROOT)
    assert "config/hevy_template_cache.json" in reg.runtime_written
    assert "config/hevy_template_cache.json" not in reg.by_key()


def test_bundled_config_is_not_an_s3_twin():
    """food_vocabulary.json ships INSIDE the Lambda zip; it has no S3 object and
    syncing one would create junk nothing reads."""
    reg = registry_mod.derive(REPO_ROOT)
    assert "config/food_vocabulary.json" in reg.bundled_into_lambda
    assert "config/food_vocabulary.json" not in reg.by_key()


# ─────────────────────────────────────────────────────────────────────────────
# The drift check FIRES — the negative test
# ─────────────────────────────────────────────────────────────────────────────


class _FakeS3:
    """Minimal S3 double. `objects` maps key -> bytes; a missing key raises."""

    def __init__(self, objects):
        self.objects = objects
        self.puts = []

    def get_object(self, Bucket, Key):  # noqa: N803 — boto3 kwarg casing
        if Key not in self.objects:
            raise self._no_such_key()
        return {"Body": _Body(self.objects[Key])}

    def put_object(self, **kwargs):
        self.puts.append(kwargs)
        self.objects[kwargs["Key"]] = kwargs["Body"]

    @staticmethod
    def _no_such_key():
        class NoSuchKey(Exception):
            pass

        return NoSuchKey("the key does not exist")


class _Body:
    def __init__(self, data):
        self._data = data

    def read(self):
        return self._data


def _twins(fake_repo):
    return [t for t in registry_mod.derive(fake_repo).twins if t.consumed]


def test_drift_check_is_clean_when_s3_matches_the_repo(fake_repo):
    twins = _twins(fake_repo)
    assert twins, "fixture should derive at least one consumed twin"
    s3 = _FakeS3({t.key: open(t.repo_path, "rb").read() for t in twins})

    report = sync_mod.run_check(twins, s3)
    assert report["clean"] is True
    assert report["drifted"] == []


def test_drift_check_fires_on_a_stale_s3_object(fake_repo):
    """THE negative test: stale one twin in S3, watch the check go red.

    This is the exact incident shape — repo corrected, S3 still holding the
    pre-merge bytes — which previously printed green everywhere."""
    twins = _twins(fake_repo)
    s3 = _FakeS3({t.key: open(t.repo_path, "rb").read() for t in twins})

    stale_key = "config/widget_registry.json"
    s3.objects[stale_key] = json.dumps({"widgets": ["withdrawn-citation"]}).encode()

    report = sync_mod.run_check(twins, s3)
    assert report["clean"] is False
    assert stale_key in report["drifted"]
    # It is read by lambdas/web/ → flagged as actively serving, the FAIL class.
    assert stale_key in report["serving_drift"]
    result = next(r for r in report["results"] if r["key"] == stale_key)
    assert result["status"] == sync_mod.STATUS_DRIFT
    assert result["local_sha256"] != result["s3_sha256"]


def test_drift_check_reports_a_never_deployed_twin_as_missing(fake_repo):
    twins = _twins(fake_repo)
    s3 = _FakeS3({})  # nothing has ever been deployed

    report = sync_mod.run_check(twins, s3)
    assert report["clean"] is False
    assert all(r["status"] == sync_mod.STATUS_MISSING for r in report["results"])


# ─────────────────────────────────────────────────────────────────────────────
# --apply uploads explicit files only, and never a prefix operation
# ─────────────────────────────────────────────────────────────────────────────


def test_apply_uploads_only_the_drifted_twin(fake_repo):
    twins = _twins(fake_repo)
    s3 = _FakeS3({t.key: open(t.repo_path, "rb").read() for t in twins})
    stale_key = "config/widget_registry.json"
    s3.objects[stale_key] = b'{"stale": true}'

    report = sync_mod.run_check(twins, s3)
    actions = sync_mod.apply_sync(report, twins, s3)

    assert actions["uploaded"] == [stale_key]
    assert actions["failed"] == []
    assert [p["Key"] for p in s3.puts] == [stale_key], "explicit files only — never a prefix sync"
    # And the object now matches the repo, so a re-check is clean.
    assert sync_mod.run_check(twins, s3)["clean"] is True


def test_apply_invalidates_and_recycles_when_the_serving_path_changed(fake_repo):
    twins = _twins(fake_repo)
    s3 = _FakeS3({t.key: open(t.repo_path, "rb").read() for t in twins})
    s3.objects["config/widget_registry.json"] = b'{"stale": true}'

    calls = {}

    class _CF:
        def create_invalidation(self, **kwargs):
            calls["invalidation"] = kwargs
            return {"Invalidation": {"Id": "I123"}}

    class _Lambda:
        def update_function_configuration(self, **kwargs):
            calls["recycle"] = kwargs
            return {}

    report = sync_mod.run_check(twins, s3)
    actions = sync_mod.apply_sync(report, twins, s3, cloudfront=_CF(), lambda_client=_Lambda())

    assert actions["invalidated"] == "I123"
    assert calls["invalidation"]["InvalidationBatch"]["Paths"]["Items"] == ["/api/*"]
    # Recycle must be description-only — never code, env, role or handler.
    assert set(calls["recycle"]) == {"FunctionName", "Description"}
    assert actions["recycled"] == sync_mod.SITE_API_FUNCTION


def test_apply_is_a_noop_when_nothing_drifted(fake_repo):
    twins = _twins(fake_repo)
    s3 = _FakeS3({t.key: open(t.repo_path, "rb").read() for t in twins})

    report = sync_mod.run_check(twins, s3)
    actions = sync_mod.apply_sync(report, twins, s3)

    assert actions["uploaded"] == []
    assert s3.puts == []
