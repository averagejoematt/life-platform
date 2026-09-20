"""tests/test_hevy_recreate_template_3770.py — deploy/hevy_recreate_template.py (#3770).

Dry-run (the default) must make NO network call and only print the planned POST body.
`--apply` is exercised against an injected fake client — no real Hevy credentials, no
real network — pinning: the explicit muscle_group in the create body, that the id
resolver SKIPS the retired old id even when the live catalogue returns it first (the
duplicate-title collision the retire-and-recreate plan creates on purpose), and that a
mismatched primary_muscle_group on readback raises loudly instead of silently
"succeeding".
"""

import json
import os
import sys
from pathlib import Path

os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")

import pytest  # noqa: E402

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "deploy"))
sys.path.insert(0, str(_REPO / "lambdas"))

import hevy_recreate_template as hrt  # noqa: E402

OLD_ID = hrt.OLD_TEMPLATE_ID
NEW_ID = "a1b2c3d4-0000-0000-0000-000000000099"


def _normalize_title(t):
    from training.hevy_template_index import normalize_title

    return normalize_title(t)


# ── planned_body / dry-run ─────────────────────────────────────────────────────


def test_planned_body_states_the_muscle_group_explicitly():
    body = hrt.planned_body()
    assert body["exercise"]["title"] == hrt.NEW_TITLE
    assert body["exercise"]["muscle_group"] == "calves"


def test_dry_run_makes_no_network_call_and_reports_the_plan(monkeypatch):
    """A dry run must never import/touch training.hevy_write_client."""
    calls = {"n": 0}

    def _boom(*a, **k):
        calls["n"] += 1
        raise AssertionError("dry-run must not call the Hevy client")

    import training.hevy_write_client as wc

    monkeypatch.setattr(wc, "create_template", _boom)
    monkeypatch.setattr(wc, "list_templates", _boom)
    monkeypatch.setattr(wc, "get_template", _boom)

    result = hrt.run(apply=False)
    assert result["dry_run"] is True
    assert result["planned_create_body"] == hrt.planned_body()
    assert result["old_template_id"] == OLD_ID
    assert calls["n"] == 0


# ── find_new_id: the retired-id-skip the recreate flow depends on ────────────


def test_find_new_id_skips_the_retired_old_id_even_when_returned_first():
    def lister(page=1, page_size=100):
        if page > 1:
            return {"exercise_templates": []}
        return {"exercise_templates": [{"id": OLD_ID, "title": hrt.NEW_TITLE}, {"id": NEW_ID, "title": hrt.NEW_TITLE}]}

    got = hrt.find_new_id(lister, hrt.NEW_TITLE, {OLD_ID}, _normalize_title)
    assert got == NEW_ID


def test_mutation_control_find_new_id_resolves_old_id_with_empty_retired_set():
    def lister(page=1, page_size=100):
        if page > 1:
            return {"exercise_templates": []}
        return {"exercise_templates": [{"id": OLD_ID, "title": hrt.NEW_TITLE}]}

    got = hrt.find_new_id(lister, hrt.NEW_TITLE, set(), _normalize_title)
    assert got == OLD_ID


def test_find_new_id_returns_none_when_only_the_retired_id_matches():
    def lister(page=1, page_size=100):
        if page > 1:
            return {"exercise_templates": []}
        return {"exercise_templates": [{"id": OLD_ID, "title": hrt.NEW_TITLE}]}

    assert hrt.find_new_id(lister, hrt.NEW_TITLE, {OLD_ID}, _normalize_title) is None


# ── run(apply=True) against a fully-injected fake client ──────────────────────


class _FakeClient:
    """Fakes training.hevy_write_client's surface: create/list/get + the shape
    `training.hevy_template_index.rebuild` needs for its lister argument."""

    def __init__(self, primary_muscle_group="calves"):
        self.created = []
        self.primary_muscle_group = primary_muscle_group
        self._templates = [{"id": OLD_ID, "title": hrt.NEW_TITLE}]  # old one is already live

    def create_template(self, body):
        self.created.append(body)
        self._templates.append({"id": NEW_ID, "title": hrt.NEW_TITLE})
        return {}

    def list_templates(self, page=1, page_size=100):
        if page > 1:
            return {"exercise_templates": []}
        return {"exercise_templates": list(self._templates)}

    def get_template(self, template_id):
        return {"id": template_id, "title": hrt.NEW_TITLE, "primary_muscle_group": self.primary_muscle_group, "type": "weight_reps"}


def test_run_apply_creates_verifies_and_rebuilds(monkeypatch):
    fake = _FakeClient(primary_muscle_group="calves")

    import training.hevy_template_cache as cache
    import training.hevy_write_client as wc

    monkeypatch.setattr(wc, "create_template", fake.create_template)
    monkeypatch.setattr(wc, "list_templates", fake.list_templates)
    monkeypatch.setattr(wc, "get_template", fake.get_template)

    written = {}
    monkeypatch.setattr(cache, "_write_s3_json", lambda key, payload: written.update({key: payload}))
    monkeypatch.setattr(cache, "_read_s3_json", lambda key: (_ for _ in ()).throw(FileNotFoundError()))

    result = hrt.run(apply=True)

    assert fake.created == [hrt.planned_body()]
    assert result["new_template_id"] == NEW_ID
    assert result["new_template_id"] != OLD_ID
    assert result["primary_muscle_group"] == "calves"
    assert result["index_rebuild"]["written"] is True
    # The rebuilt index must never carry the retired id under this title.
    from training.hevy_template_index import INDEX_KEY, normalize_title

    published = written[INDEX_KEY]["templates"][normalize_title(hrt.NEW_TITLE)]
    assert published["id"] == NEW_ID


def test_run_apply_raises_loudly_on_a_still_wrong_muscle_group(monkeypatch):
    fake = _FakeClient(primary_muscle_group="shoulders")  # the create silently mis-set again

    import training.hevy_write_client as wc

    monkeypatch.setattr(wc, "create_template", fake.create_template)
    monkeypatch.setattr(wc, "list_templates", fake.list_templates)
    monkeypatch.setattr(wc, "get_template", fake.get_template)

    with pytest.raises(RuntimeError, match="shoulders"):
        hrt.run(apply=True)


def test_main_prints_json_report(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["hevy_recreate_template.py"])
    hrt.main()
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert parsed["dry_run"] is True
