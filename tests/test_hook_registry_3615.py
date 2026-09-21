"""#3615 box 1 — the hooks registry, its derivation guard, and the nightly liveness matrix.

WHAT WAS TRUE BEFORE THIS LANDED: `qa_smoke_lambda.check_predict_week_freshness()` was
the ONLY per-hook probe on the platform. Ask-the-board was seen by the 3x/week AI canary,
chronicle and podcast cadence by nothing, and the publication extension's five downstream
artifacts by five different one-offs. "Was the board door alive on Day 4?" had no answer.

Three guards, in the #3594 shape (guard the SET, not the specimen):

  DERIVATION — `site/**/*.js` is swept for POST targets. Every token found must be claimed
  by a `HOOK_REGISTRY` row, so a hook added to the site without a registry row REDS here
  instead of joining the set of things nobody probes.

  RATCHET — the hook and cell counts may only grow. Removing one is an explicit edit to
  the floors below, with a reason in the PR.

  BEHAVIOUR — a MISSING cell is a FAIL (not a warn, not a shrug), an honestly-absent cell
  needs a DECLARED, dated, owned contract that this run can TEST, and a cell the read
  budget never reached is a WARN — never a pass. Every functional test here fails against
  a tree where the leg does not exist.
"""

import fnmatch
import json
import os
import re
from datetime import date
from pathlib import Path

import pytest

# qa_smoke_lambda reads these at import time (conftest supplies fake AWS creds).
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("EMAIL_RECIPIENT", "qa@example.com")
os.environ.setdefault("EMAIL_SENDER", "qa@example.com")

from operational import hook_liveness_qa as hq, hook_registry as reg
from operational.census_probe import Fetched, ProbeBudget
from operational.qa_check import CONTENT_TRUTH, Check

REPO = Path(__file__).resolve().parent.parent

# ── the ratchets ─────────────────────────────────────────────────────────────
# Measured at landing (2026-09-21): 13 hooks / 21 cells, probed live at 18 HTTP + 3
# key-bounded AWS reads — inside #3615's ~36-read nightly budget.
HOOK_COUNT_FLOOR = 13
CELL_COUNT_FLOOR = 21


# ── the derivation sweep ─────────────────────────────────────────────────────
_FETCH = re.compile(r"""fetch\(\s*([`"'][^`"')]+[`"'])\s*,\s*\{(?P<opts>[^{}]*(\{[^{}]*\}[^{}]*)*)\}""", re.S)
_POSTJSON = re.compile(r"""postJSON\(\s*([`"'][^`"')]+[`"'])""")
_DATA_ENDPOINT = re.compile(r"""data-endpoint=["'](/api/[^"']+)["']""")
_METHOD_POST = re.compile(r"""method:\s*['"]POST['"]""")


def _normalize(literal: str) -> str:
    """`${API}/predict_week` → `*/predict_week`; a JS template hole becomes a glob."""
    return re.sub(r"\$\{[^}]*\}", "*", literal.strip("`\"'"))


def hook_claiming(endpoint: str):
    """The hook row that claims a scanned POST token, or None.

    Matching is fnmatch in BOTH directions so a registry token with a `*` claims a
    concrete scanned path and a scanned token with a `*` (a JS template hole, e.g.
    `${API}/predict_week`) is claimed by a concrete registry token — the two spellings of
    the same door. It lives here rather than in the registry because the derivation guard
    is its only caller, and a public def in `lambdas/` ships in ~104 Lambda zips (#781,
    tests/test_no_dead_shared_defs_3538.py).
    """
    for hook in reg.hooks():
        for declared in hook.post_endpoints:
            if declared == endpoint or fnmatch.fnmatch(endpoint, declared) or fnmatch.fnmatch(declared, endpoint):
                return hook
    return None


def site_post_endpoints() -> dict:
    """{endpoint token: {files}} — every POST target the SITE reaches, swept from source."""
    found: dict = {}
    for path in sorted((REPO / "site").rglob("*.js")):
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in _FETCH.finditer(text):
            if _METHOD_POST.search(match.group("opts")):
                found.setdefault(_normalize(match.group(1)), set()).add(path.name)
        for match in _POSTJSON.finditer(text):
            found.setdefault(_normalize(match.group(1)), set()).add(path.name)
        for match in _DATA_ENDPOINT.finditer(text):
            found.setdefault(_normalize(match.group(1)), set()).add(path.name)
    return found


def test_the_sweep_finds_the_known_reader_hooks():
    """The derivation itself must not silently stop finding anything (a guard that sweeps
    an empty set passes forever — #2934's class)."""
    found = site_post_endpoints()
    assert len(found) >= 10, f"the POST sweep found only {len(found)} endpoints — the scanner has gone blind"
    assert "/api/ask" in found and "/api/board_ask" in found


def test_every_site_post_endpoint_is_claimed_by_a_hook_row():
    unclaimed = {ep: sorted(files) for ep, files in site_post_endpoints().items() if hook_claiming(ep) is None}
    assert not unclaimed, (
        "these reader POST doors exist in site/ with no HOOK_REGISTRY row, so nothing probes them nightly: "
        f"{unclaimed} — add a Hook row (lambdas/operational/hook_registry.py) with its artifacts"
    )


def test_registry_only_grows():
    assert len(reg.hooks()) >= HOOK_COUNT_FLOOR, "a hook was removed — edit the floor deliberately, with a reason"
    assert len(reg.cells()) >= CELL_COUNT_FLOOR, "a matrix cell was removed — edit the floor deliberately, with a reason"


def test_hook_and_cell_ids_are_unique():
    hook_ids = [h.id for h in reg.hooks()]
    cell_ids = [f"{h.id}/{a.id}" for h, a in reg.cells()]
    assert len(set(hook_ids)) == len(hook_ids)
    assert len(set(cell_ids)) == len(cell_ids)


def test_every_cell_declares_a_probe_kind_the_evaluator_knows():
    for hook, artifact in reg.cells():
        assert artifact.kind in reg.PROBE_KINDS, f"{hook.id}/{artifact.id} has unknown probe kind {artifact.kind!r}"
        assert artifact.locator, f"{hook.id}/{artifact.id} has no locator"
        if artifact.kind in (reg.DDB_ROW, reg.DDB_WINDOW):
            assert "|" in artifact.locator, f"{hook.id}/{artifact.id} needs a 'pk|sk' locator"


def test_every_hook_has_at_least_one_artifact_and_a_why():
    for hook in reg.hooks():
        assert hook.artifacts, f"{hook.id} has no artifact — a hook nobody probes is the thing this registry ends"
        assert len(hook.why) > 20, f"{hook.id} does not say what a reader loses when it is dark"


def test_every_declared_absence_is_dated_owned_and_testable():
    declared = [(h, a) for h, a in reg.cells() if a.absence is not None]
    assert declared, "no absence contracts at all — the podcast feed alone should carry one"
    for hook, artifact in declared:
        absence = artifact.absence
        assert absence.contract in reg.ABSENCE_CONTRACTS, f"{hook.id}/{artifact.id}: unknown contract {absence.contract!r}"
        assert len(absence.reason) > 30, f"{hook.id}/{artifact.id}: an absence with no stated reason is not honest"
        date.fromisoformat(absence.declared_on)  # raises on a bad/missing date
        assert absence.issue.startswith("#"), f"{hook.id}/{artifact.id}: an absence needs an owning issue"


def test_the_empty_podcast_feed_is_declared_not_silently_tolerated():
    """#3615 box 5 is RESIDUAL, so the census must report the dark feed every night."""
    cell = next(a for h, a in reg.cells() if h.id == "podcast")
    assert cell.absence is not None and cell.absence.contract == "declared_dark"
    assert "#3615" in cell.absence.issue


# ── the probe budget ─────────────────────────────────────────────────────────
def test_probe_budget_fetches_each_url_once():
    calls = []

    def opener(url, timeout):
        calls.append(url)
        return 200, "{}"

    budget = ProbeBudget(opener=opener)
    budget.get("https://x/a")
    budget.get("https://x/a")
    assert calls == ["https://x/a"]


def test_a_spent_budget_defers_rather_than_pretending():
    clock = {"t": 0.0}

    def opener(url, timeout):  # pragma: no cover — must never be reached
        raise AssertionError("a spent budget must not issue requests")

    budget = ProbeBudget(total_seconds=10.0, opener=opener, clock=lambda: clock["t"])
    clock["t"] = 11.0
    result = budget.get("https://x/a")
    assert result.deferred and not result.ok and "budget" in result.error


# ── the leg ──────────────────────────────────────────────────────────────────
class _FakeTable:
    def __init__(self, items=None, query_items=None):
        self.items = items or {}
        self.query_items = query_items or []
        self.puts = []

    def get_item(self, Key):
        item = self.items.get((Key["pk"], Key["sk"]))
        return {"Item": item} if item else {}

    def query(self, **kwargs):
        return {"Items": list(self.query_items)}

    def put_item(self, Item):
        self.puts.append(Item)


class _FakeS3:
    def __init__(self, bodies=None):
        self.bodies = bodies or {}

    def get_object(self, Bucket, Key):
        if Key not in self.bodies:
            raise KeyError(f"NoSuchKey {Key}")
        return {"Body": _Body(self.bodies[Key])}


class _Body:
    def __init__(self, text):
        self.text = text

    def read(self):
        return self.text.encode()


_TODAY = date(2026, 9, 20)


def _frozen_pt_now():
    """The handler's clock, FROZEN to an instant derived from `_TODAY` (#2376): every
    fixture date here is relative to that day, so this file cannot go red at a UTC
    midnight the way #2354's did."""

    class _N:
        @staticmethod
        def date():
            return _TODAY

    return _N()


_MANIFEST = json.dumps({"posts": [{"date": "2026-09-15", "sequence": 5, "label": "Week 2", "url": "/journal/posts/week-05/"}]})


def _opener_factory(overrides=None):
    overrides = overrides or {}

    def opener(url, timeout):
        for needle, response in overrides.items():
            if needle in url:
                return response
        if url.endswith("/journal/posts.json"):
            return 200, _MANIFEST
        if "/api/predict_week" in url:
            return 200, json.dumps({"active": True, "week_id": "2026-W38"})
        if url.endswith("/podcast/feed.xml"):
            return 200, "<rss><channel><item>one</item></channel></rss>"
        if "/journal/posts/" in url:
            return 200, "<html>installment</html>"
        return 405, json.dumps({"error": "Use POST method"})

    return opener


def _ctx(overrides=None, ddb_items=None, query_items=None, s3_bodies=None):
    table = _FakeTable(
        items=(
            ddb_items
            if ddb_items is not None
            else {("USER#matthew#SOURCE#chronicle", "RECAP#latest"): {"generated_at": "2026-09-18T18:00:00+00:00"}}
        ),
        query_items=(
            query_items
            if query_items is not None
            else [{"sk": "SUB#a@b.c", "confirmed_at": "2026-09-10T00:00:00+00:00", "onboarding_sent_at": "2026-09-12T00:00:00+00:00"}]
        ),
    )
    s3 = _FakeS3(
        s3_bodies if s3_bodies is not None else {"generated/moments/share-kits/week-05/kit.json": json.dumps({"caption": "a caption"})}
    )
    budget = ProbeBudget(opener=_opener_factory(overrides))
    return table, s3, budget


def test_a_clean_night_is_green_and_names_the_cycle_day():
    table, s3, budget = _ctx()
    checks = hq.check_hook_liveness(table, s3, "bucket", Check, CONTENT_TRUTH, _frozen_pt_now, site_base_url="https://site", budget=budget)
    assert len(checks) == 1
    assert checks[0].passed is True, checks[0].message
    assert "cells alive" in checks[0].message


def test_a_dropped_door_is_a_FAIL_naming_the_cell():
    """The #3615 rule: a MISSING cell is a red, not a shrug."""
    table, s3, budget = _ctx(overrides={"/api/board_ask": (404, '{"error": "Not found"}')})
    check = hq.check_hook_liveness(table, s3, "bucket", Check, CONTENT_TRUTH, _frozen_pt_now, site_base_url="https://site", budget=budget)[
        0
    ]
    assert check.passed is False
    assert "board_ask/door_ask" in check.message and "MISSING" in check.message


def test_a_missing_share_kit_is_a_FAIL():
    table, s3, budget = _ctx(s3_bodies={})
    check = hq.check_hook_liveness(table, s3, "bucket", Check, CONTENT_TRUTH, _frozen_pt_now, site_base_url="https://site", budget=budget)[
        0
    ]
    assert check.passed is False and "chronicle/share_kit" in check.message


def test_a_tombstoned_recap_latest_is_a_FAIL():
    table, s3, budget = _ctx(
        ddb_items={("USER#matthew#SOURCE#chronicle", "RECAP#latest"): {"generated_at": "2026-09-18", "tombstone": True}}
    )
    check = hq.check_hook_liveness(table, s3, "bucket", Check, CONTENT_TRUTH, _frozen_pt_now, site_base_url="https://site", budget=budget)[
        0
    ]
    assert check.passed is False and "recap_latest" in check.message


def test_an_empty_podcast_feed_is_honestly_absent_not_a_fail():
    table, s3, budget = _ctx(overrides={"/podcast/feed.xml": (200, "<rss><channel></channel></rss>")})
    check = hq.check_hook_liveness(table, s3, "bucket", Check, CONTENT_TRUTH, _frozen_pt_now, site_base_url="https://site", budget=budget)[
        0
    ]
    assert check.passed is True
    assert "podcast/feed_items" in check.message  # visible every night, never silent


def test_no_confirmed_subscriber_makes_the_onboarding_cell_honestly_absent():
    table, s3, budget = _ctx(query_items=[])
    check = hq.check_hook_liveness(table, s3, "bucket", Check, CONTENT_TRUTH, _frozen_pt_now, site_base_url="https://site", budget=budget)[
        0
    ]
    assert check.passed is True and "chronicle/onboarding_email" in check.message


def test_a_confirmed_subscriber_with_no_bridge_email_is_a_FAIL():
    table, s3, budget = _ctx(query_items=[{"sk": "SUB#a@b.c", "confirmed_at": "2026-09-10T00:00:00+00:00"}])
    check = hq.check_hook_liveness(table, s3, "bucket", Check, CONTENT_TRUTH, _frozen_pt_now, site_base_url="https://site", budget=budget)[
        0
    ]
    assert check.passed is False and "onboarding_email" in check.message


def test_predict_week_dark_inside_a_live_cycle_is_a_FAIL(monkeypatch):
    monkeypatch.setattr(hq, "_cycle_day", lambda today: 15)
    table, s3, budget = _ctx(overrides={"/api/predict_week": (200, json.dumps({"active": False}))})
    check = hq.check_hook_liveness(table, s3, "bucket", Check, CONTENT_TRUTH, _frozen_pt_now, site_base_url="https://site", budget=budget)[
        0
    ]
    assert check.passed is False and "predict_week/live_subject" in check.message


def test_predict_week_dark_with_no_live_cycle_is_honestly_absent(monkeypatch):
    monkeypatch.setattr(hq, "_cycle_day", lambda today: None)
    table, s3, budget = _ctx(overrides={"/api/predict_week": (200, json.dumps({"active": False}))})
    check = hq.check_hook_liveness(table, s3, "bucket", Check, CONTENT_TRUTH, _frozen_pt_now, site_base_url="https://site", budget=budget)[
        0
    ]
    assert check.passed is True and "no live cycle" in check.message


def test_an_unread_cell_is_a_WARN_never_a_pass():
    clock = {"t": 0.0}
    table, s3, _ = _ctx()
    budget = ProbeBudget(total_seconds=1.0, opener=_opener_factory(), clock=lambda: clock["t"])
    clock["t"] = 99.0
    check = hq.check_hook_liveness(table, s3, "bucket", Check, CONTENT_TRUTH, _frozen_pt_now, site_base_url="https://site", budget=budget)[
        0
    ]
    assert check.passed is None, "a budget-starved census must warn, never report green"
    assert "NOT OBSERVED" in check.message


def test_the_matrix_row_is_stored_with_its_cycle_day(monkeypatch):
    monkeypatch.setattr(hq, "_cycle_day", lambda today: 15)
    table, s3, budget = _ctx()
    hq.check_hook_liveness(table, s3, "bucket", Check, CONTENT_TRUTH, _frozen_pt_now, site_base_url="https://site", budget=budget)
    assert len(table.puts) == 1
    row = table.puts[0]
    assert row["pk"] == hq.MATRIX_PK and row["sk"] == "DATE#2026-09-20" and row["cycle_day"] == 15
    cells = json.loads(row["cells_json"])
    assert len(cells) == len(reg.cells())
    assert {c["verdict"] for c in cells} <= set(reg.VERDICTS)


def test_a_failed_row_write_never_reds_a_clean_census():
    class _Exploding(_FakeTable):
        def put_item(self, Item):
            raise RuntimeError("AccessDeniedException")

    table = _Exploding(
        items={("USER#matthew#SOURCE#chronicle", "RECAP#latest"): {"generated_at": "2026-09-18T18:00:00+00:00"}},
        query_items=[{"sk": "SUB#a", "confirmed_at": "2026-09-10", "onboarding_sent_at": "2026-09-12"}],
    )
    s3 = _FakeS3({"generated/moments/share-kits/week-05/kit.json": json.dumps({"caption": "c"})})
    budget = ProbeBudget(opener=_opener_factory())
    check = hq.check_hook_liveness(table, s3, "bucket", Check, CONTENT_TRUTH, _frozen_pt_now, site_base_url="https://site", budget=budget)[
        0
    ]
    assert check.passed is True


def test_the_leg_is_wired_into_the_nightly_sweep():
    import qa_smoke_lambda  # noqa: F401 — imported for the check_steps surface

    labels = [label for label, _fn in qa_smoke_lambda.check_steps()]
    assert "hook_liveness_matrix" in labels, "the census must ride qa-smoke's EXISTING invocation (#3615)"


@pytest.mark.parametrize("status", [404, 500, 502])
def test_only_a_mounted_door_counts_as_alive(status):
    table, s3, budget = _ctx(overrides={"/api/subscribe": (status, "")})
    check = hq.check_hook_liveness(table, s3, "bucket", Check, CONTENT_TRUTH, _frozen_pt_now, site_base_url="https://site", budget=budget)[
        0
    ]
    assert check.passed is False and "subscribe/door" in check.message


def test_a_transport_error_is_not_evidence_against_a_door():
    """A network blip must not manufacture a red — it is an unread cell, reported as one."""

    def opener(url, timeout):
        if "/api/explain" in url:
            raise OSError("connection reset")
        return _opener_factory()(url, timeout)

    table, s3, _ = _ctx()
    budget = ProbeBudget(opener=opener)
    check = hq.check_hook_liveness(table, s3, "bucket", Check, CONTENT_TRUTH, _frozen_pt_now, site_base_url="https://site", budget=budget)[
        0
    ]
    assert check.passed is None and "explain/door" in check.message


def test_fetched_json_never_raises_on_garbage():
    assert Fetched("u", status=200, body="not json").json() is None
