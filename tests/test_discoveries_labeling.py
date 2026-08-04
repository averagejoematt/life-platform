"""tests/test_discoveries_labeling.py — #1089: carried protocols are not discoveries.

The "active hypotheses" on /protocols/discoveries/ are ongoing supplement
protocols from config/experiment_library.json (status=="active") — cross_phase
by design (ADR-077), deliberately carried across cycle resets and active since
Feb 2026. Pre-start (and any time) they must not read as findings of an
experiment that hasn't produced any (ADR-104). These tests pin:

  1. the API payload marks each entry carried_over / ongoing_protocol with its
     active_since date (so the front-end has the honest semantics to render);
  2. non-active library entries never reach the payload; an S3 read failure
     degrades to an honest empty list, not a crash;
  3. the rendering JS labels the section "Ongoing protocols — carried across
     cycles" (never "Hypotheses under test") and carries the no-current-cycle-
     discoveries line for the pre-start/early-cycle window.

NO wipe/taxonomy change — presentation only (the issue's acceptance criteria).
"""

import json
import os
import sys

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "web"))

from web import site_api_data as sad  # noqa: E402

_LIBRARY = {
    "experiments": [
        {
            "id": "tongkat-ali-recovery",
            "name": "Tongkat Ali — Recovery Optimization",
            "status": "active",
            "description": "Standing supplement protocol.",
            "hypothesis_template": "Tongkat Ali improves recovery over {duration} days",
            "protocol_template": "400mg daily",
            "pillar": "recovery",
            "evidence_tier": "moderate",
            "metrics_measurable": ["hrv"],
            "suggested_duration_days": 60,
            "promoted_date": "2026-02-09",
        },
        {
            "id": "sauna-hrv",
            "name": "Sauna — HRV",
            "status": "completed",
            "promoted_date": "2026-03-01",
        },
    ]
}


class _FakeBody:
    def __init__(self, payload):
        self._raw = json.dumps(payload).encode()

    def read(self):
        return self._raw


class _FakeS3:
    def __init__(self, payload=None, err=None, supp_payload=None, supp_err=None):
        self._payload = payload
        self._err = err
        # #1984: discoveries() now also reads config/supplement_registry.json to
        # cross-check supplements-pillar active entries. Default: an empty-but-valid
        # registry (no groups) so pre-#1984 fixtures — which use pillar != "supplements"
        # and never exercise the match — keep behaving exactly as before.
        self._supp_payload = supp_payload if supp_payload is not None else {"groups": {}}
        self._supp_err = supp_err

    def get_object(self, Bucket=None, Key=None):
        if self._err:
            raise self._err
        if Key == "config/experiment_library.json":
            return {"Body": _FakeBody(self._payload)}
        if Key == "config/supplement_registry.json":
            if self._supp_err:
                raise self._supp_err
            return {"Body": _FakeBody(self._supp_payload)}
        raise AssertionError(f"unexpected S3 key: {Key}")


class _FakeBoto3:
    def __init__(self, s3):
        self._s3 = s3

    def client(self, *a, **k):
        return self._s3


class _EmptyTable:
    """Insights + correlations partitions empty — isolates the library branch."""

    def query(self, **kwargs):
        return {"Items": []}


def _body(resp):
    return json.loads(resp["body"]) if isinstance(resp.get("body"), str) else resp["body"]


def _mount(monkeypatch, s3):
    monkeypatch.setattr(sad, "boto3", _FakeBoto3(s3))
    monkeypatch.setattr(sad, "table", _EmptyTable())


def test_active_entries_marked_as_carried_protocols(monkeypatch):
    _mount(monkeypatch, _FakeS3(_LIBRARY))
    body = _body(sad.handle_discoveries())
    hyp = body["active_hypotheses"]
    assert len(hyp) == 1
    h = hyp[0]
    assert h["name"] == "Tongkat Ali — Recovery Optimization"
    # #1089: the carried-not-discovered semantics ride in the payload.
    assert h["carried_over"] is True
    assert h["protocol_kind"] == "ongoing_protocol"
    assert h["active_since"] == "2026-02-09"
    # The {duration} token still gets substituted (pre-existing fix, kept).
    assert "{duration}" not in h["hypothesis"]
    assert "60" in h["hypothesis"]


def test_non_active_entries_excluded(monkeypatch):
    _mount(monkeypatch, _FakeS3(_LIBRARY))
    body = _body(sad.handle_discoveries())
    names = [h["name"] for h in body["active_hypotheses"]]
    assert "Sauna — HRV" not in names


def test_missing_promoted_date_is_honest_null(monkeypatch):
    lib = {"experiments": [{"id": "x", "name": "X", "status": "active", "promoted_date": ""}]}
    _mount(monkeypatch, _FakeS3(lib))
    body = _body(sad.handle_discoveries())
    assert body["active_hypotheses"][0]["active_since"] is None


def test_s3_failure_degrades_to_empty_list(monkeypatch):
    _mount(monkeypatch, _FakeS3(err=RuntimeError("s3 down")))
    body = _body(sad.handle_discoveries())
    assert body["active_hypotheses"] == []


# ── #1984: supplements-pillar entries are cross-checked against the stack registry ──

_SUPP_LIBRARY = {
    "experiments": [
        {
            "id": "tongkat-ali-recovery",
            "name": "Tongkat Ali — Recovery Optimization",
            "status": "active",
            "pillar": "supplements",
            "promoted_date": "2026-02-09",
        },
        {
            "id": "creatine-strength",
            "name": "Creatine Monohydrate — Strength",
            "status": "active",
            "pillar": "supplements",
            "promoted_date": "2026-02-14",
        },
    ]
}

_SUPP_REGISTRY = {"groups": {"muscle": {"items": [{"key": "creatine", "name": "Creatine Monohydrate"}]}}}


def test_supplements_entry_confirmed_in_stack_keeps_ongoing_protocol(monkeypatch):
    _mount(monkeypatch, _FakeS3(_SUPP_LIBRARY, supp_payload=_SUPP_REGISTRY))
    body = _body(sad.handle_discoveries())
    by_id = {h["name"]: h for h in body["active_hypotheses"]}
    assert by_id["Creatine Monohydrate — Strength"]["protocol_kind"] == "ongoing_protocol"


def test_supplements_entry_absent_from_stack_is_unconfirmed(monkeypatch):
    _mount(monkeypatch, _FakeS3(_SUPP_LIBRARY, supp_payload=_SUPP_REGISTRY))
    body = _body(sad.handle_discoveries())
    by_id = {h["name"]: h for h in body["active_hypotheses"]}
    # Tongkat Ali has no matching entry in the stack registry above — it must not
    # keep the "ongoing_protocol" / under-continuous-measurement framing.
    assert by_id["Tongkat Ali — Recovery Optimization"]["protocol_kind"] == "unconfirmed_protocol"


def test_supplements_entry_paused_in_stack_is_unconfirmed(monkeypatch):
    registry = {"groups": {"muscle": {"items": [{"key": "creatine", "name": "Creatine Monohydrate", "paused": True}]}}}
    _mount(monkeypatch, _FakeS3(_SUPP_LIBRARY, supp_payload=registry))
    body = _body(sad.handle_discoveries())
    by_id = {h["name"]: h for h in body["active_hypotheses"]}
    # A paused registry entry does not count as a live, matching stack item.
    assert by_id["Creatine Monohydrate — Strength"]["protocol_kind"] == "unconfirmed_protocol"


def test_supplement_registry_read_failure_fails_closed_to_unconfirmed(monkeypatch):
    # The library itself still reads fine; only the registry cross-check fails.
    _mount(monkeypatch, _FakeS3(_SUPP_LIBRARY, supp_err=RuntimeError("registry s3 down")))
    body = _body(sad.handle_discoveries())
    by_id = {h["name"]: h for h in body["active_hypotheses"]}
    # Both entries present (the library read did not fail) but neither can be
    # confirmed against a registry that failed to load — fail closed, never a
    # false "confirmed" claim.
    assert by_id["Creatine Monohydrate — Strength"]["protocol_kind"] == "unconfirmed_protocol"
    assert by_id["Tongkat Ali — Recovery Optimization"]["protocol_kind"] == "unconfirmed_protocol"


def test_non_supplements_pillar_entry_unaffected_by_registry(monkeypatch):
    # The original fixture's single entry is pillar="recovery" — the registry
    # cross-check must never touch non-supplements pillars.
    _mount(monkeypatch, _FakeS3(_LIBRARY, supp_payload={"groups": {}}))
    body = _body(sad.handle_discoveries())
    assert body["active_hypotheses"][0]["protocol_kind"] == "ongoing_protocol"


# ── Front-end contract: the rendering JS carries the honest framing ──────────

_JS = open(os.path.join(_REPO, "site", "assets", "js", "evidence_discovery.js")).read()


def test_js_labels_section_as_carried_protocols():
    assert "Ongoing protocols — carried across cycles" in _JS
    assert "carried across cycles" in _JS
    assert "active since" in _JS
    # The old framing — library protocols presented as current hypotheses — is gone.
    assert "Hypotheses under test" not in _JS


def test_js_states_no_current_cycle_discoveries():
    # Pre-start/early-cycle honesty (ADR-104): with no findings, the section
    # explicitly says no current-cycle discoveries exist yet.
    assert "No discoveries from this cycle yet" in _JS
