"""#2715 — a source paused by design must not turn the freshness verdict red.

Measured against the deployed `life-platform-mcp` Lambda on 2026-08-15, BEFORE the fix:

    get_freshness_status {"sources": ["garmin"]}
      -> {"status": "red", "stale_count": 1, "fresh_count": 0,
          "stale_sources": [{"source": "garmin", "last_date": "2026-06-15",
                             "age_days": 61, "status": "stale",
                             "source_state": "stale"}]}

garmin is paused by design — ADR-074, vendor anti-automation crackdown, no live
EventBridge rule. `source_registry`'s own facet comment states the required behaviour in
as many words:

    paused — intentionally off — shown as "paused", never counted stale

TWO CORRECT-LOOKING MECHANISMS THAT NEVER MET. `resolve_source_state` decided "paused"
from `source_state.DECLARED_PAUSED_SOURCES`, which is **deliberately empty** — and its own
comment says why:

    "Currently empty on purpose; garmin's pause is registry-driven
     (source_registry paused=True, ADR-074), not declared here."

So one module said "the registry holds this fact" and the other held it, and nothing read
both. Everything downstream of `resolve_source_state` therefore labelled a deliberately-off
source `stale`, and a single paused source was enough to push the whole verdict to `red`
(`max_age_stale > 14`). The one tool whose job is answering "are we OK?" answered red
permanently, for a condition nobody will ever fix — which is the fastest way to make the
answer go unread.

WHY THE BLAST RADIUS IS SMALL, checked caller by caller (the issue's fourth box):

  * `emails/freshness_checker_lambda.py` — already correct by another route. It builds
    from `checker_sources()`, which excludes paused sources entirely, so nothing paused
    ever reached SNS/CloudWatch. Unaffected.
  * `web/site_api_freshness.py` — already correct. The public board has an explicit
    `status: "paused"` bucket fed by `public_paused_sources()`. Unaffected.
  * `mcp/tools_labs.get_freshness_status` — THE defect. It asks `mcp_sources()`, which
    deliberately INCLUDES paused sources, and then relied on `resolve_source_state` to
    label them. Fixed here.
  * `intelligence/ai_expert_analyzer_lambda.py` — garmin flips `stale` → `paused`. Its
    only test is `_garmin_state == "live"` (step-source precedence), which is unchanged:
    both values are non-live, so Apple Health still supplies steps.
  * `operational/pipeline_health_check_lambda.py` — uses `is_paused`, which now returns
    True for garmin. Consequence, stated rather than discovered: garmin's boot probe is
    skipped and it leaves the alerting set. That is the same ruling — ADR-074 removed its
    cron, so there is no cron to be "stopped", and the module's own comment already gives
    this exact reasoning for declared-paused sources.
  * `mcp/tools_data.get_sources` — #2671 layered `qa_paused()` over the resolver precisely
    because the resolver could not answer. That layer is now redundant and is removed; the
    single truth source is the point of this issue.

FRESHNESS STILL WINS, and that is the property that keeps the label from becoming a
suppressor. A paused source producing fresh data reads `live` with no code change, so
re-enabling is visible immediately — the failure mode #496/C-3 hit with Strava, where a
stale pause declaration suppressed real-outage detection for weeks.
"""

from __future__ import annotations

import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")

import pytest  # noqa: E402
from common.pacific_time import pacific_today  # noqa: E402
from ingestion.source_registry import SOURCE_REGISTRY, mcp_sources  # noqa: E402
from ingestion.source_state import DECLARED_PAUSED_SOURCES, is_paused, resolve_source_state  # noqa: E402

from mcp import tools_labs  # noqa: E402

TODAY = "2026-08-15"


def _fresh_today() -> str:
    """tool_get_freshness_status ages rows against the REAL wall clock (no injectable
    seam), so a "fresh" fixture row must move with the calendar — a pinned "2026-08-15"
    here aged past whoop's staleness threshold two days after this file was written and
    redded main at the cycle-14 reset. Sampled at CALL time (not a module global) so a
    run crossing a day boundary between collection and execution can't desync (#2223).
    The resolve_source_state tests keep pinned dates because they pass their own `today`.

    PACIFIC, not UTC (#2798). The handler ages rows against `pacific_now().date()`
    (`mcp/tools_labs.py`), so a UTC "today" here builds a row dated TOMORROW in the
    handler's frame for the seven hours between 17:00 PT and midnight — the #3222
    fixture-frame class, and the #3206 shape (a time-dependent assertion that is only
    true outside its own window). It sat here invisible because the fully-qualified
    `import datetime` spelling below was a blind spot in the shared matcher until #2798
    closed it."""
    return pacific_today()


REGISTRY_PAUSED = sorted(k for k, v in SOURCE_REGISTRY.items() if v.get("paused"))


# ── the two mechanisms, and the fact they now meet ───────────────────────────


def test_the_registry_marks_something_paused_and_the_declared_set_is_empty():
    """Vacuity guard AND the shape of the bug: both halves were true, separately."""
    assert REGISTRY_PAUSED, "no registry-paused source — every assertion below would be vacuous"
    assert "garmin" in REGISTRY_PAUSED, "precondition: garmin is paused by ADR-074"
    assert DECLARED_PAUSED_SOURCES == set(), "precondition: the declared set is empty on purpose"


@pytest.mark.parametrize("source", REGISTRY_PAUSED)
def test_every_registry_paused_source_resolves_paused_when_not_fresh(source):
    """Derived over the whole facet, not just garmin — a second pause is covered on day one."""
    assert is_paused(source) is True
    assert resolve_source_state(source, "2026-06-15", TODAY) == "paused"


def test_a_live_source_is_unaffected():
    """The control. A fix that calls everything paused would suppress every real outage."""
    assert is_paused("whoop") is False
    assert resolve_source_state("whoop", "2026-06-15", TODAY) == "stale"


def test_freshness_still_wins_over_the_paused_label():
    """#496/C-3: a stale pause declaration once suppressed real-outage detection for weeks.
    A paused source producing again must read `live` with no code change."""
    assert resolve_source_state("garmin", TODAY, TODAY) == "live"


def test_a_rate_limit_marker_still_outranks_the_paused_label():
    """The documented precedence is unchanged — only the source of the paused fact moved."""
    assert resolve_source_state("garmin", "2026-06-15", TODAY, rate_limited=True) == "rate_limited"


def test_an_unreadable_registry_does_not_invent_a_pause(monkeypatch):
    """Fail-soft in the safe direction: calling a source paused when we cannot confirm it
    would suppress a real outage, which is the error that actually costs something."""
    import ingestion.source_state as st

    monkeypatch.setattr(st, "_registry_paused", lambda: (_ for _ in ()).throw(RuntimeError("registry down")))
    with pytest.raises(RuntimeError):
        st._registry_paused()
    # …and the real helper swallows it rather than propagating:
    monkeypatch.undo()
    monkeypatch.setattr("ingestion.source_registry.SOURCE_REGISTRY", {}, raising=True)
    assert st._registry_paused() == set()
    assert st.resolve_source_state("garmin", "2026-06-15", TODAY) == "stale", "no registry ⇒ no pause ⇒ honest stale"


# ── the verdict the issue is actually about ──────────────────────────────────


class _Table:
    """Only garmin has data, and it is 61 days old — the live shape on 2026-08-15."""

    def __init__(self, rows):
        self.rows = rows

    def query(self, **kwargs):
        expr = kwargs["KeyConditionExpression"].get_expression()
        pk = expr["values"][0].get_expression()["values"][1]
        src = pk.rsplit("#", 1)[-1]
        return {"Items": self.rows.get(src, [])}

    def get_item(self, **_kwargs):
        return {}


@pytest.fixture
def freshness(monkeypatch):
    def _install(rows):
        t = _Table(rows)
        monkeypatch.setattr(tools_labs, "table", t)
        return t

    return _install


def _row(src, date):
    return [{"pk": f"USER#matthew#SOURCE#{src}", "sk": f"DATE#{date}", "date": date}]


def test_a_paused_source_alone_does_not_turn_the_verdict_red(freshness):
    """The issue's headline, reproduced through the tool rather than asserted about it."""
    freshness({"garmin": _row("garmin", "2026-06-15")})
    out = tools_labs.tool_get_freshness_status({"sources": ["garmin"]})
    assert out["status"] != "red", out
    assert out["stale_count"] == 0, "a source that is off by design is not a staleness finding"
    assert out["paused_count"] == 1


def test_the_paused_source_is_still_reported(freshness):
    """The failure this must not become: the source disappearing (see `_unreadable`)."""
    freshness({"garmin": _row("garmin", "2026-06-15")})
    out = tools_labs.tool_get_freshness_status({"sources": ["garmin"]})
    row = out["paused_sources"][0]
    assert row["source"] == "garmin"
    assert row["status"] == "paused" and row["source_state"] == "paused"
    assert row["last_date"] == "2026-06-15" and row["age_days"] > 0, "the age is still on the record"
    assert not any(s["source"] == "garmin" for s in out["stale_sources"]), "paused is not the needs-attention bucket"


def test_a_genuinely_stale_source_still_reds_the_verdict(freshness):
    """The control that matters most: this fix must not be able to hide a real outage."""
    freshness({"whoop": _row("whoop", "2026-06-15")})
    out = tools_labs.tool_get_freshness_status({"sources": ["whoop"]})
    assert out["stale_count"] == 1
    assert out["status"] == "red", out["status"]


def test_a_paused_source_beside_a_stale_one_does_not_inflate_the_count(freshness):
    """Three stale sources trip `red` regardless of age — a paused one must not be the third."""
    freshness({"garmin": _row("garmin", "2026-06-15"), "whoop": _row("whoop", _fresh_today())})
    out = tools_labs.tool_get_freshness_status({"sources": ["garmin", "whoop"]})
    assert out["stale_count"] == 0 and out["paused_count"] == 1 and out["fresh_count"] == 1
    assert out["status"] == "green"


def test_a_paused_source_producing_again_is_counted_as_fresh(freshness):
    """No code change required to notice a re-enable — the property that stops the label
    from becoming a permanent suppressor."""
    freshness({"garmin": _row("garmin", _fresh_today())})
    out = tools_labs.tool_get_freshness_status({"sources": ["garmin"]})
    assert out["paused_count"] == 0 and out["fresh_count"] == 1
    assert out["fresh_sources"][0]["source_state"] == "live"


def test_the_context_string_explains_the_new_count(freshness):
    """A count nobody can interpret is a count nobody reads."""
    freshness({"garmin": _row("garmin", "2026-06-15")})
    out = tools_labs.tool_get_freshness_status({"sources": ["garmin"]})
    assert "paused_count" in out["context"] and "never counted stale" in out["context"]


# ── the caller sweep the issue asks for (box 4) ──────────────────────────────


def test_get_sources_no_longer_needs_its_own_paused_layer():
    """#2671 layered qa_paused() over the resolver because the resolver could not answer.
    A single truth source is the point of this issue, so the layer is gone."""
    import inspect

    from mcp import tools_data

    src = inspect.getsource(tools_data.tool_get_sources)
    assert "qa_paused" not in src, "the #2671 workaround should have been removed with the root fix"


def test_the_mcp_source_view_still_includes_paused_sources():
    """`mcp_sources()` deliberately includes paused — that is WHY this tool had to label
    them, and removing them instead would have hidden the source rather than fixed it."""
    assert "garmin" in mcp_sources()
