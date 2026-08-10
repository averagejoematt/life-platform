"""tests/test_experiment_surface_vice_screen_2240.py — #2240: the experiment-surface
never-public-vocabulary screen SET.

The issue named TWO unguarded doors (`handle_experiment_library` and
`_handle_experiment_detail` in ``lambdas/web/site_api_social.py``) and framed the
asymmetry correctly: the same module screens the challenge routes twice and screened
these not at all. The count was wrong. Deriving the set instead of hand-enumerating it
— the "guard the SET, not the instance" discipline this repo has now paid for ten times
— finds **nine** functions in ``lambdas/web/`` that read an experiment source (the
catalog JSON in S3, or the live experiments partition) AND lift an entry's ``name``/
``id`` into a public payload. All nine were unscreened before this change:

  1. site_api_social.handle_experiment_library   (GET /api/experiment_library)
  2. site_api_social._handle_experiment_detail   (GET /api/experiment_detail)
  3. site_api_social._valid_library_ids          (the vote allowlist derived from the
                                                  same catalog — a screened entry must
                                                  not be re-admitted as votable)
  4. site_api_data._experiment_catalog           (catalog overlay for /api/experiments)
  5. site_api_protocols.experiments              (GET /api/experiments, live runs)
  6. site_api_journey.timeline                   (GET /api/timeline)
  7. site_api_journey.journey_timeline           (GET /api/journey_timeline)
  8. site_api_ledger.discoveries                 (GET /api/discoveries)
  9. site_api_rollups.changes_since              (GET /api/changes_since)

``site_api_discovery.intelligence_summary`` reads the same partition but publishes only
a COUNT of active runs — no entry identity crosses the boundary — so it is deliberately
not a member, and the derivation below encodes that as a rule (source read AND identity
read), not as an exception list.

Structure:
  AC1  derivation — the member set is computed by AST walk, is non-vacuous (the probe
       finds real functions today), and every member calls ``_is_blocked_vice``.
  AC1b non-vacuity of AC1 itself — a synthetic unscreened member is injected into the
       derivation's input and MUST be reported. This is the mutation that defeats the
       "guard exists but guards nothing" failure mode: three privacy screens have
       shipped here whose full suite passed with the screen deleted.
  AC2  behavioural — a synthetic sentinel name/id is injected into the catalog and into
       a live experiment record, and each public response is asserted not to contain it.
       Each assertion was verified RED with its screen commented out (see the PR body).

Privacy note (public repo, permanent history): no real blocked term appears as a source
literal. Fixtures load the configured vocabulary from the ER-06 channel at test
time (the #2203/#2211/#2212 technique) and build a throwaway experiment name around it.
"""

from __future__ import annotations

import ast
import json
import os
import sys
from pathlib import Path

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")

from fakes import FakeDdbTable  # noqa: E402
from web import (  # noqa: E402
    site_api_common as common,
    site_api_data as data_mod,
    site_api_ledger as ledger_mod,
    site_api_protocols as protocols_mod,
    site_api_social as social,
)

ROOT = Path(_REPO)
WEB = ROOT / "lambdas" / "web"
USER_ID = os.environ["USER_ID"]

LIBRARY_KEY_FRAGMENT = "experiment_library.json"
EXPERIMENTS_PARTITION_SUFFIX = "experiments"


# ---------------------------------------------------------------------------
# Shared: the real blocked vocabulary, loaded at test time — never a literal.
# ---------------------------------------------------------------------------


def _cf() -> dict:
    from privacy import content_filter_channel

    cf = content_filter_channel.load(require=True)  # #2370: the ER-06 channel (neutral fixture vocab in the unit suite)
    return dict(cf)


def _pin_content_filter(monkeypatch) -> dict:
    """Pin ``common._content_filter_cache`` to the REAL config on disk so every
    ``_is_blocked_vice()`` call in every web module — they share this one
    module-level cache — resolves against the live vocabulary."""
    cf = _cf()
    monkeypatch.setattr(common, "_content_filter_cache", dict(cf))
    monkeypatch.setattr(common, "_content_filter_cache_at", None)
    return cf


def _blocked_name(prefix: str) -> str:
    """A throwaway experiment display name built AROUND one real keyword at
    runtime — the keyword never appears as a literal in this file."""
    return f"{prefix} {_cf()['blocked_vice_keywords'][0]} protocol"


def _blocked_id(prefix: str) -> str:
    return _blocked_name(prefix).lower().replace(" ", "-")


# ===========================================================================
# AC1 — derive the member set.
# ===========================================================================


def _body_without_docstring(fn: ast.AST) -> list:
    """A function's statements minus its docstring — a docstring that MENTIONS
    the catalog file (``site_api_ledger._supplement_stack_match`` does) must not
    make the function a member of the serving set."""
    body = list(getattr(fn, "body", []))
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
        body = body[1:]
    return body


def _reads_experiment_source(stmts: list) -> bool:
    """True when the code reads the experiment catalog object in S3, or the live
    experiments DynamoDB partition (as a plain literal, an f-string whose trailing
    literal chunk is the source name, or a ``_query_source("experiments", ...)``)."""
    for stmt in stmts:
        for n in ast.walk(stmt):
            if isinstance(n, ast.Constant) and isinstance(n.value, str):
                if LIBRARY_KEY_FRAGMENT in n.value or f"SOURCE#{EXPERIMENTS_PARTITION_SUFFIX}" in n.value:
                    return True
            if isinstance(n, ast.JoinedStr):
                parts = [p.value for p in n.values if isinstance(p, ast.Constant) and isinstance(p.value, str)]
                if any(p == EXPERIMENTS_PARTITION_SUFFIX or p.endswith(f"SOURCE#{EXPERIMENTS_PARTITION_SUFFIX}") for p in parts):
                    return True
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_query_source":
                if n.args and isinstance(n.args[0], ast.Constant) and n.args[0].value == EXPERIMENTS_PARTITION_SUFFIX:
                    return True
    return False


def _lifts_entry_identity(stmts: list) -> bool:
    """True when the code pulls an entry's ``name`` or ``id`` off a record — the
    thing that turns a source read into a publication of an entry's identity.
    A count-only reader (site_api_discovery.intelligence_summary) has none."""
    for stmt in stmts:
        for n in ast.walk(stmt):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "get":
                if n.args and isinstance(n.args[0], ast.Constant) and n.args[0].value in ("name", "id"):
                    return True
    return False


def _calls_screen(stmts: list) -> bool:
    for stmt in stmts:
        for n in ast.walk(stmt):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_is_blocked_vice":
                return True
    return False


def _derive_members(sources: dict) -> dict:
    """{f"{module}::{func}": screened_bool} over ``{module_name: source_text}``.

    Taking the sources as a PARAMETER is what makes AC1b possible: the same
    derivation runs against the real tree and against a mutated copy."""
    members = {}
    for mod_name, src in sorted(sources.items()):
        tree = ast.parse(src, filename=mod_name)
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            stmts = _body_without_docstring(fn)
            if _reads_experiment_source(stmts) and _lifts_entry_identity(stmts):
                members[f"{mod_name}::{fn.name}"] = _calls_screen(stmts)
    return members


def _web_sources() -> dict:
    return {p.name: p.read_text(encoding="utf-8") for p in sorted(WEB.rglob("*.py"))}


EXPECTED_MEMBERS = {
    "site_api_data.py::_experiment_catalog",
    "site_api_journey.py::journey_timeline",
    "site_api_journey.py::timeline",
    "site_api_ledger.py::discoveries",
    "site_api_protocols.py::experiments",
    "site_api_rollups.py::changes_since",
    "site_api_social.py::_handle_experiment_detail",
    "site_api_social.py::_valid_library_ids",
    "site_api_social.py::handle_experiment_library",
}


def test_experiment_surface_set_is_derived_and_non_vacuous():
    """The probe must find the real serving surfaces today — otherwise the screen
    assertion below would pass by finding nothing, which is not a guard at all.
    The COUNT is the finding this issue exists to correct: the issue named 2, the
    derivation finds 9. A tenth surface added later reds here with no line numbers
    to chase; give it the screen, then add it to this pin."""
    members = _derive_members(_web_sources())
    assert set(members) == EXPECTED_MEMBERS, (
        "the derived experiment-serving set changed — a surface that reads an experiment "
        f"source and publishes an entry's identity was added or removed: {sorted(set(members) ^ EXPECTED_MEMBERS)}"
    )


def test_every_experiment_surface_applies_the_screen():
    """Guard the SET: every derived member calls the never-public-vocabulary screen."""
    members = _derive_members(_web_sources())
    unscreened = sorted(k for k, screened in members.items() if not screened)
    assert not unscreened, f"experiment-serving surfaces with no content screen at all: {unscreened}"


def test_derivation_catches_a_synthetic_unscreened_surface():
    """AC1b — the mutation that proves AC1 is not vacuous.

    A synthetic module with the exact shape of the bug (reads the catalog object,
    lifts entry name/id into a payload, applies no screen) is fed to the SAME
    derivation. It must be derived as a member AND reported unscreened. If the
    probe were broken — a typo in the marker strings, a walk that never fires —
    this test goes green-by-emptiness elsewhere but RED here."""
    mutant = (
        "def _synthetic_leaky_surface(client):\n"
        '    """Docstring alone must not qualify a function."""\n'
        f'    obj = client.get_object(Bucket="b", Key="config/{LIBRARY_KEY_FRAGMENT}")\n'
        "    lib = json.loads(obj)\n"
        '    return [{"id": e.get("id"), "name": e.get("name", "")} for e in lib.get("experiments", [])]\n'
    )
    members = _derive_members({"synthetic_mutant.py": mutant})
    key = "synthetic_mutant.py::_synthetic_leaky_surface"
    assert key in members, "the derivation failed to classify a textbook unscreened experiment surface as a member"
    assert members[key] is False, "the derivation reported a screen on a function that has none"

    # ...and the same function WITH the screen must come back clean, so the
    # screened/unscreened distinction is real rather than always-False.
    fixed = mutant.replace(
        'for e in lib.get("experiments", [])',
        'for e in lib.get("experiments", []) if not _is_blocked_vice(e.get("name", ""))',
    )
    fixed_members = _derive_members({"synthetic_mutant.py": fixed})
    assert fixed_members[key] is True, "the derivation failed to see a screen that is present"


def test_count_only_reader_is_not_a_member():
    """The membership rule is source-read AND identity-lift, not source-read alone:
    a surface that publishes only how many runs are active carries no entry identity
    and must not be dragged in (it would be a screen with nothing to screen)."""
    counter = (
        "def _counts_only(table):\n"
        '    resp = table.query(KeyConditionExpression=Key("pk").eq(f"{USER_PREFIX}experiments"))\n'
        '    return {"active": sum(1 for it in resp["Items"] if it.get("status") == "active")}\n'
    )
    assert _derive_members({"synthetic_counter.py": counter}) == {}


# ===========================================================================
# AC2 — behavioural proof at the two doors the issue named, plus the two the
#       derivation added that publish the same identity most directly.
# ===========================================================================


class _FakeS3:
    """Minimal S3 client double serving one JSON body for any get_object."""

    def __init__(self, payload: dict):
        self._payload = payload

    def get_object(self, **_kwargs):
        class _Body:
            def __init__(self, raw):
                self._raw = raw

            def read(self):
                return self._raw

        return {"Body": _Body(json.dumps(self._payload).encode("utf-8"))}


class _FakeBoto3:
    def __init__(self, payload: dict):
        self._payload = payload

    def client(self, *_a, **_kw):
        return _FakeS3(self._payload)


def _library(entries: list) -> dict:
    return {"version": "test", "pillars": {"body": {"label": "Body", "icon": "circle"}}, "experiments": entries}


def _entry(eid: str, name: str) -> dict:
    return {"id": eid, "name": name, "pillar": "body", "status": "backlog", "hypothesis_template": "x for {duration} days"}


# ── site_api_social.handle_experiment_library — GET /api/experiment_library ──


@pytest.mark.parametrize("arm", ["name", "id"])
def test_experiment_library_excludes_a_screened_catalog_entry(monkeypatch, arm):
    """The issue's first door. Both arms: a term can live only in the id while the
    display name is benign (ER-06), which a name-only screen would miss."""
    _pin_content_filter(monkeypatch)
    bad_name = _blocked_name("Cut") if arm == "name" else "Evening walk"
    bad_id = _blocked_id("cut") if arm == "id" else "evening-walk-x"
    library = _library([_entry("clean-entry", "Morning sunlight"), _entry(bad_id, bad_name)])
    monkeypatch.setattr(social, "boto3", _FakeBoto3(library))
    monkeypatch.setattr(social, "table", FakeDdbTable(rows=[]))

    body = json.loads(social.handle_experiment_library()["body"])
    served = [e for p in body["pillars"] for e in p["experiments"]]
    assert {e["id"] for e in served} == {"clean-entry"}, f"screened entry reached /api/experiment_library: {served}"
    assert bad_name not in json.dumps(body)
    assert bad_id not in json.dumps(body)
    assert body["total_experiments"] == 1, "the screened entry must not survive even as a count"


def test_experiment_library_excludes_a_screened_live_record(monkeypatch):
    """The live DDB overlay is the second door into the same payload — the issue
    called this out explicitly as the future-leak path."""
    _pin_content_filter(monkeypatch)
    blocked = _blocked_name("Quit")
    library = _library([_entry("clean-entry", "Morning sunlight")])
    monkeypatch.setattr(social, "boto3", _FakeBoto3(library))
    monkeypatch.setattr(
        social,
        "table",
        FakeDdbTable(
            rows=[
                {
                    "pk": f"USER#{USER_ID}#SOURCE#experiments",
                    "sk": "EXP#live-1",
                    "name": blocked,
                    "status": "active",
                    "start_date": "2026-06-01",
                    "library_id": "clean-entry",
                }
            ]
        ),
    )
    body = json.loads(social.handle_experiment_library()["body"])
    served = [e for p in body["pillars"] for e in p["experiments"]]
    assert served and served[0]["id"] == "clean-entry"
    assert served[0].get("status") != "active", "a screened live record must not colour a published catalog entry"
    assert blocked not in json.dumps(body)


# ── site_api_social._handle_experiment_detail — GET /api/experiment_detail ──


@pytest.mark.parametrize("arm", ["name", "id"])
def test_experiment_detail_returns_404_for_a_screened_entry(monkeypatch, arm):
    """The issue's second door, and its explicit acceptance criterion: 404, not the
    raw entry — and the same 404 text an absent id gets, so the response can't
    confirm the entry exists."""
    _pin_content_filter(monkeypatch)
    bad_id = _blocked_id("cut") if arm == "id" else "evening-walk-x"
    bad_name = "Evening walk" if arm == "id" else _blocked_name("Cut")
    library = _library([_entry(bad_id, bad_name)])
    monkeypatch.setattr(social, "boto3", _FakeBoto3(library))
    monkeypatch.setattr(social, "table", FakeDdbTable(rows=[]))

    resp = social._handle_experiment_detail({"queryStringParameters": {"id": bad_id}})
    assert resp["statusCode"] == 404, f"screened entry served from /api/experiment_detail: {resp}"
    assert bad_name not in resp["body"]

    missing = social._handle_experiment_detail({"queryStringParameters": {"id": "no-such-entry"}})
    assert json.loads(resp["body"]).get("error") == json.loads(missing["body"]).get("error").replace("no-such-entry", bad_id)


def test_experiment_detail_serves_a_clean_entry(monkeypatch):
    """Sanity companion: the screen doesn't 404 legitimate experiments."""
    _pin_content_filter(monkeypatch)
    library = _library([_entry("morning-sunlight", "Morning sunlight")])
    monkeypatch.setattr(social, "boto3", _FakeBoto3(library))
    monkeypatch.setattr(social, "table", FakeDdbTable(rows=[]))
    resp = social._handle_experiment_detail({"queryStringParameters": {"id": "morning-sunlight"}})
    assert resp["statusCode"] == 200
    assert "Morning sunlight" in resp["body"]


def test_experiment_detail_drops_a_screened_live_run(monkeypatch):
    """A screened LIVE record must not join a clean entry's run history."""
    _pin_content_filter(monkeypatch)
    blocked = _blocked_name("Quit")
    library = _library([_entry("morning-sunlight", "Morning sunlight")])
    monkeypatch.setattr(social, "boto3", _FakeBoto3(library))
    monkeypatch.setattr(
        social,
        "table",
        FakeDdbTable(
            rows=[
                {
                    "pk": f"USER#{USER_ID}#SOURCE#experiments",
                    "sk": "EXP#live-2",
                    "name": blocked,
                    "status": "completed",
                    "start_date": "2026-05-01",
                    "end_date": "2026-05-20",
                    "library_id": "morning-sunlight",
                }
            ]
        ),
    )
    body = json.loads(social._handle_experiment_detail({"queryStringParameters": {"id": "morning-sunlight"}})["body"])
    assert body["runs"] == [], f"screened live run reached /api/experiment_detail: {body['runs']}"
    assert blocked not in json.dumps(body)


# ── site_api_social._valid_library_ids — the vote allowlist ────────────────


def test_vote_allowlist_excludes_a_screened_entry(monkeypatch):
    """A screened entry is not votable either — otherwise the write door re-admits
    what every read door drops, and mints DDB rows keyed by the screened id."""
    _pin_content_filter(monkeypatch)
    bad_id = _blocked_id("cut")
    monkeypatch.setattr(social, "boto3", _FakeBoto3(_library([_entry("clean-entry", "Morning sunlight"), _entry(bad_id, "Evening walk")])))
    monkeypatch.setattr(social, "_library_ids_cache", (0.0, frozenset()))
    assert social._valid_library_ids() == frozenset({"clean-entry"})


# ── site_api_protocols.experiments — GET /api/experiments (live runs) ──────


def test_experiments_endpoint_excludes_a_screened_live_run(monkeypatch):
    """Derived member #5 — a surface the issue never named, publishing live run
    names and ids straight to a public endpoint."""
    _pin_content_filter(monkeypatch)
    blocked = _blocked_name("Quit")
    table = FakeDdbTable(
        rows=[
            {
                "pk": f"USER#{USER_ID}#SOURCE#experiments",
                "sk": "EXP#clean-run",
                "name": "Morning sunlight",
                "status": "active",
                "start_date": "2026-06-01",
            },
            {
                "pk": f"USER#{USER_ID}#SOURCE#experiments",
                "sk": "EXP#blocked-run",
                "name": blocked,
                "status": "active",
                "start_date": "2026-06-01",
            },
        ]
    )
    _g = {"table": table, "_experiment_catalog": lambda ids, names: []}
    body = json.loads(protocols_mod.experiments(_g=_g)["body"])
    assert {e["name"] for e in body["experiments"]} == {"Morning sunlight"}, body["experiments"]
    assert blocked not in json.dumps(body)


# ── site_api_data._experiment_catalog — the catalog overlay for /api/experiments ──


def test_experiment_catalog_overlay_excludes_a_screened_entry(monkeypatch):
    """Derived member #4 — the same catalog file, a different module, no screen."""
    _pin_content_filter(monkeypatch)
    bad_id = _blocked_id("cut")
    monkeypatch.setattr(
        data_mod, "boto3", _FakeBoto3(_library([_entry("clean-entry", "Morning sunlight"), _entry(bad_id, "Evening walk")]))
    )
    out = data_mod._experiment_catalog(set(), set())
    assert {e["id"] for e in out} == {"clean-entry"}, out


# ── site_api_ledger.discoveries — GET /api/discoveries active hypotheses ──


def test_discoveries_active_hypotheses_exclude_a_screened_entry(monkeypatch):
    """Derived member #8 — publishes the catalog entry's name as an active hypothesis."""
    _pin_content_filter(monkeypatch)
    blocked = _blocked_name("Cut")
    lib = _library([_entry("clean-entry", "Morning sunlight"), _entry("blocked-entry", blocked)])
    for e in lib["experiments"]:
        e["status"] = "active"
    _g = {"boto3": _FakeBoto3(lib), "table": FakeDdbTable(rows=[])}
    body = json.loads(ledger_mod.discoveries(_g=_g)["body"])
    names = {h["name"] for h in body["active_hypotheses"]}
    assert names == {"Morning sunlight"}, names
    assert blocked not in json.dumps(body)
