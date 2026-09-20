"""tests/test_hevy_template_retirement_3770.py — #3770: a retired Hevy template id must
never be what a title lookup resolves TO, even when the live catalogue holds a
title-identical replacement (the recreated "Calf Press on Leg Press Machine" template
deliberately shares its predecessor's title).

Covers the three places a title resolves to an id:
  - mcp/hevy_resolution.py::_index_fuzzy            (cached-index token-subset match)
  - mcp/hevy_resolution.py::_live_template_id_by_title / _LiveWalk (live catalogue walk)
  - lambdas/training/hevy_template_index.py::build_payload (the index PRODUCER — a
    retired id must never even be published into config/hevy_template_index.json)

Each test's mutation control clears RETIRED_TEMPLATE_IDS and shows the old id
resolves again — proving the retirement check, not incidental dict ordering, is
what changed the outcome.
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))
sys.path.insert(0, str(_REPO / "lambdas"))

from training import hevy_template_index as hti  # noqa: E402

import mcp.hevy_resolution as res  # noqa: E402

OLD_ID = "70b39605-52c0-4b79-855c-e26ea10440da"
NEW_ID = "a1b2c3d4-0000-0000-0000-000000000001"
TITLE = "Calf Press on Leg Press Machine"


# ── mcp/hevy_resolution.py::_index_fuzzy (cached index) ───────────────────────


def test_index_fuzzy_skips_a_retired_id(monkeypatch):
    index = {
        res._normalize_title(TITLE): {"id": OLD_ID, "title": TITLE},
    }
    monkeypatch.setattr(res, "_template_index", lambda *a, **k: index)
    assert res._index_fuzzy("Calf Press Leg Press Machine") is None  # only candidate is retired


def test_index_fuzzy_resolves_the_live_replacement_when_both_present(monkeypatch):
    # Two entries can't both key the same normalized title in a real dict, but the
    # resolver must still refuse the retired id if it were ever the sole candidate,
    # and pick the live one when it is present under its own normalized key too.
    index = {
        res._normalize_title(TITLE): {"id": NEW_ID, "title": TITLE},
    }
    monkeypatch.setattr(res, "_template_index", lambda *a, **k: index)
    assert res._index_fuzzy("Calf Press Leg Press Machine") == NEW_ID


def test_mutation_control_index_fuzzy_resolves_old_id_when_not_retired(monkeypatch):
    index = {
        res._normalize_title(TITLE): {"id": OLD_ID, "title": TITLE},
    }
    monkeypatch.setattr(res, "_template_index", lambda *a, **k: index)
    monkeypatch.setattr(res, "is_retired_template", lambda template_id: False)
    assert res._index_fuzzy("Calf Press Leg Press Machine") == OLD_ID


# ── mcp/hevy_resolution.py::_live_template_id_by_title / _LiveWalk ────────────


def _lister_with(items):
    def _list(page=1, page_size=100):
        if page > 1:
            return {"exercise_templates": []}
        return {"exercise_templates": items}

    return _list


def test_live_walk_skips_a_retired_id():
    walk = res._LiveWalk(_lister_with([{"id": OLD_ID, "title": TITLE}]))
    assert walk.id_for(TITLE) is None


def test_live_walk_resolves_the_new_id_over_a_duplicate_retired_title():
    # Both templates really do exist live with the same title; page order should not
    # matter — the retired one must never win.
    walk = res._LiveWalk(_lister_with([{"id": OLD_ID, "title": TITLE}, {"id": NEW_ID, "title": TITLE}]))
    assert walk.id_for(TITLE) == NEW_ID


def test_mutation_control_live_walk_resolves_old_id_when_not_retired(monkeypatch):
    monkeypatch.setattr(res, "is_retired_template", lambda template_id: False)
    walk = res._LiveWalk(_lister_with([{"id": OLD_ID, "title": TITLE}]))
    assert walk.id_for(TITLE) == OLD_ID


def test_live_template_id_by_title_skips_retired():
    # Patch the client the function imports internally.
    import training.hevy_write_client as wc

    orig = wc.list_templates
    try:
        wc.list_templates = _lister_with([{"id": OLD_ID, "title": TITLE}])
        assert res._live_template_id_by_title(TITLE) is None
        wc.list_templates = _lister_with([{"id": OLD_ID, "title": TITLE}, {"id": NEW_ID, "title": TITLE}])
        assert res._live_template_id_by_title(TITLE) == NEW_ID
    finally:
        wc.list_templates = orig


# ── lambdas/training/hevy_template_index.py::build_payload (the producer) ────


def test_build_payload_never_publishes_a_retired_id():
    payload = hti.build_payload([{"id": OLD_ID, "title": TITLE}])
    assert payload["templates"] == {}
    assert payload["count"] == 0


def test_build_payload_publishes_the_live_replacement_not_the_retired_predecessor():
    payload = hti.build_payload([{"id": OLD_ID, "title": TITLE}, {"id": NEW_ID, "title": TITLE}])
    key = hti.normalize_title(TITLE)
    assert payload["templates"][key]["id"] == NEW_ID
    assert payload["count"] == 1


def test_mutation_control_build_payload_publishes_old_id_when_not_retired(monkeypatch):
    monkeypatch.setattr(hti, "is_retired_template", lambda template_id: False)
    payload = hti.build_payload([{"id": OLD_ID, "title": TITLE}])
    key = hti.normalize_title(TITLE)
    assert payload["templates"][key]["id"] == OLD_ID
