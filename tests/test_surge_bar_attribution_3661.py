"""tests/test_surge_bar_attribution_3661.py — #3661: an engaged surge names the bar that minted it.

THE DEFECT
──────────
ADR-133's surge bar became DERIVED in #3510 (`max(900, ceil(mean + 3*SD))` over the trailing
eight weekly `UniqueVisitors7d` readings, re-derived on EVERY governor run). It has moved
three times since: 900 → 1188 → 1383 → 1355. Engagement is hysteretic — engage at `>= T`,
then hold until traffic falls below `0.8*T` — and nothing anywhere recorded WHICH bar had
engaged the state, so a surge minted under one threshold was silently inherited by a band
computed from a later one.

Live, from `/aws/lambda/life-platform-cost-governor` (not a reconstruction):

    2026-09-07T08:00:15Z  recent_uniques=1011 surge_active=True effective_ceiling=$252 surge_threshold=1188
    2026-09-08T00:00:15Z  recent_uniques=1218 surge_active=True effective_ceiling=$252 surge_threshold=1383
    ... 24 consecutive runs (2026-09-07T00:00:14Z … 09-14T16:00:17Z), all with 0.8*T <= u < T ...
    2026-09-14T16:00:17Z  recent_uniques=1218 surge_active=True effective_ceiling=$252 surge_threshold=1383
    2026-09-15T00:00:15Z  recent_uniques=905  surge_active=False effective_ceiling=$215 surge_threshold=1355

The state was engaged 2026-09-01T00:00:13Z under the then-constant 900 bar (SSM version 5). Every run in between ran the
platform at a $252 ceiling against the $215 base — +17%, and the same +17% on all three
tier bands (the tier-1 trip moves $157.67 → $184.80) — on the strength of a threshold that
no longer existed. A reading of 1011 could not have engaged the 1188 bar; a reading of 1218
could not have engaged 1383. That is the property #3661 restores: **the effective ceiling
in force is always one a current reading could have produced.**

WHAT EACH TEST OWNS
───────────────────
  A. the cross-bar rule itself, mutation-proved BOTH ways (a same-bar hold survives, a
     cross-bar hold does not) — the acceptance box's own wording
  B. the ADR ↔ code contract: the worked lines in ADR-133's hold-rule block are PARSED OUT
     OF `docs/DECISIONS.md` and executed. `docs/DECISIONS.md:4427` stated the inverted
     arithmetic for eight days and no doc gate could see it, because it was prose reasoning
     rather than a derived literal. Executing the prose is the only gate that could have.
  C. the SSM state encoding, including the legacy bare `true` every pre-#3661 write left
  D. the attribution reaching a human — the governor's log-line string and `/api/receipts`
  E. the identity `cost_governor_lambda` relies on: `_effective_ceiling(u, T, d.active)`
     agrees with `decide(...).active` for every case, so the two predicates cannot drift
"""

from __future__ import annotations

import importlib
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
for _p in (_REPO / "lambdas", _REPO / "lambdas" / "web"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")


@pytest.fixture(scope="module")
def surge():
    return importlib.import_module("operational.cost_governor_surge")


@pytest.fixture(scope="module")
def gov():
    return importlib.import_module("operational.cost_governor_lambda")


# The bars the derivation actually produced, in order, and the reading live at each.
# Kept as data because the whole finding is about a bar that MOVES.
_LIVE_BARS = ((900, None), (1188, 1011), (1383, 1218), (1355, 905))


# ── A. the cross-bar rule, both directions ───────────────────────────────────────────────
def test_a_same_bar_hysteresis_hold_survives(surge):
    """The band is not being removed. A state minted at 1188 and still measured inside
    0.8*1188 = 950.4 stays ON — that is hysteresis doing its designed job (suppressing
    oscillation around a STABLE bar), and #3510's five-flips-in-seven-weeks is what
    removing it would restore."""
    d = surge.decide(1011, 1188, prev_surge_active=True, prev_engaged_bar=1188)
    assert d.active is True
    assert d.held_by == "hysteresis"
    assert d.engaged_at_bar == 1188
    assert d.rebar_from is None


def test_a_cross_bar_hysteresis_hold_does_not(surge):
    """The mutation the acceptance box asks for: the SAME reading and the SAME bar, with
    only the MINTING bar changed, must decide the other way. 1011 is inside 0.8*1188 but
    was never able to cross 1188, so a state minted at 900 is re-decided from OFF."""
    d = surge.decide(1011, 1188, prev_surge_active=True, prev_engaged_bar=900)
    assert d.active is False, "a surge minted by the retired 900 bar was inherited by the 1188 band"
    assert d.rebar_from == 900
    assert d.engaged_at_bar is None


def test_a_cross_bar_re_decision_can_also_re_engage(surge):
    """Re-decision is not a disengage shortcut. A reading that clears the NEW bar stays on
    and is re-attributed to it — otherwise the rule would be a one-way ratchet that
    tightened on every derivation regardless of traffic."""
    d = surge.decide(1400, 1383, prev_surge_active=True, prev_engaged_bar=900)
    assert d.active is True
    assert d.held_by == "bar"
    assert d.engaged_at_bar == 1383, "the state must be re-attributed to the bar that now holds it"
    assert d.rebar_from == 900


def test_a_unattributed_state_is_re_decided_never_inherited(surge):
    """Every value written before #3661 is a bare `true` with no bar. `held by hysteresis`
    is a CLAIM about which bar engaged the state; a state that cannot support that claim
    must not get the looser ceiling. Fails toward the base ceiling, matching
    `_effective_ceiling`'s own 'fails closed to the base ceiling, never the surge one'."""
    assert surge.SURGE_UNATTRIBUTED_IS_CROSS_BAR is True
    d = surge.decide(1011, 1188, prev_surge_active=True, prev_engaged_bar=None)
    assert d.active is False
    assert d.rebar_from is None, "there is no retired bar to name — the state never recorded one"


def test_a_the_engage_from_off_rule_is_untouched(surge):
    """The band must never become a second, lower entry. From OFF, only the bar engages."""
    assert surge.decide(1011, 1188, prev_surge_active=False).active is False
    assert surge.decide(1188, 1188, prev_surge_active=False).active is True
    assert surge.decide(1188, 1188, prev_surge_active=False).engaged_at_bar == 1188


def test_a_a_missing_reading_never_engages_or_holds(surge):
    """A transient CloudWatch failure must not mint or sustain a raised ceiling."""
    assert surge.decide(None, 1188, prev_surge_active=False).active is False
    assert surge.decide(None, 1188, prev_surge_active=True, prev_engaged_bar=1188).active is False


def test_a_the_live_september_run_would_have_disengaged(surge):
    """The finding replayed against the real logged series. Every one of the runs between
    2026-09-07 and 2026-09-14 held a $252 ceiling on a bar that no longer existed; under
    the rule all of them decide OFF."""
    held_cross_bar = [(u, bar) for bar, u in _LIVE_BARS if u is not None and 0.8 * bar <= u < bar]
    assert held_cross_bar, "the live specimen readings must still sit inside their own bands"
    for u, bar in held_cross_bar:
        assert surge.decide(u, bar, prev_surge_active=True, prev_engaged_bar=900).active is False
        # ...and the same reading under its OWN bar is a legitimate hold, unchanged.
        assert surge.decide(u, bar, prev_surge_active=True, prev_engaged_bar=bar).active is True


# ── B. the ADR ↔ code contract ───────────────────────────────────────────────────────────
_WORKED = re.compile(
    r"^worked:\s*u=(?P<u>\d+)\s+T=(?P<t>\d+)\s+engaged_at_bar=(?P<bar>\d+)\s*->\s*surge\s+(?P<state>ON|OFF)\s+ceiling\s+\$(?P<ceiling>\d+)\s*$",
    re.MULTILINE,
)
_RETIRED_INVERSION = "so hysteresis does **not** hold it"


def _adr_text() -> str:
    return (_REPO / "docs" / "DECISIONS.md").read_text(encoding="utf-8")


def test_b_the_adr_worked_examples_execute_through_the_code(surge, gov):
    """ADR-133's stated hold rule and `cost_governor_surge.decide` agree in BOTH directions,
    because the ADR's own arithmetic is run rather than read. This is the gate the inverted
    note escaped: `check_doc_facts` sees derived literals, and that paragraph was reasoning.

    Ceilings are asserted against the module constants rather than `_active_ceilings()` on
    purpose — the latter is calendar-scoped (`_TEMP_CEILING_WINDOW`), and a date-flaky
    contract test is how the #3510 note survived unchallenged in the first place."""
    cases = list(_WORKED.finditer(_adr_text()))
    assert len(cases) >= 6, f"ADR-133's hold-rule block lost its worked lines (found {len(cases)})"
    for m in cases:
        u, t, bar = int(m["u"]), int(m["t"]), int(m["bar"])
        expected_on = m["state"] == "ON"
        d = surge.decide(u, t, prev_surge_active=True, prev_engaged_bar=bar)
        assert d.active is expected_on, f"ADR line {m.group(0)!r} disagrees with decide() -> {d.active}"
        stated = float(m["ceiling"])
        actual = gov.SURGE_CEILING_USD if expected_on else gov.MONTHLY_CEILING
        assert stated == actual, f"ADR line {m.group(0)!r} states ${stated:.0f}; the code's constant is ${actual:.0f}"


def test_b_both_the_hold_and_the_engage_direction_are_stated(surge):
    """Both halves of the rule must appear as worked cases, or the block could assert one
    direction and leave the other free to invert again."""
    text = _adr_text()
    states = {m["state"] for m in _WORKED.finditer(text)}
    assert states == {"ON", "OFF"}, f"the ADR's worked block only exercises {states}"
    assert f"{surge.SURGE_DISENGAGE_RATIO} * T" in text, "the ADR must state the hold ratio the code uses"


def test_b_the_retired_inverted_claim_is_not_restated_as_current(surge):
    """The 2026-09-06 note said `1011 < 0.8*1188 = 950.4 is false — so hysteresis does not
    hold it`. It is quoted in the correction as history; it must not stand as a claim."""
    text = _adr_text()
    assert _RETIRED_INVERSION not in text, "ADR-133 still asserts the inverted hysteresis arithmetic"
    assert surge.engaged(1011, 1188, prev_surge_active=True) is True, "the code's actual behaviour moved"


# ── C. the persisted state ───────────────────────────────────────────────────────────────
@pytest.mark.parametrize("active,bar", [(True, 900), (True, 1188), (True, 1383), (False, None), (True, None)])
def test_c_surge_state_round_trips(surge, active, bar):
    assert surge.decode_surge_state(surge.encode_surge_state(active, bar)) == (active, bar if active else None)


def test_c_the_legacy_bare_value_decodes_as_engaged_with_no_bar(surge):
    """Every write before #3661 was a bare `true`/`false`. The read must not throw, and
    must not invent an attribution."""
    assert surge.decode_surge_state("true") == (True, None)
    assert surge.decode_surge_state("false") == (False, None)
    assert surge.decode_surge_state(None) == (False, None)
    assert surge.decode_surge_state("true@not-a-number") == (True, None)


def test_c_the_governor_reads_and_writes_the_bar_through_ssm(gov, monkeypatch):
    """Fixture must be the wire: the encoding above is only real if the governor's own
    SSM helpers use it."""
    written = {}

    class _SSM:
        class exceptions:
            class ParameterNotFound(Exception):
                pass

        def get_parameter(self, Name):
            return {"Parameter": {"Value": written.get(Name, "false")}}

        def put_parameter(self, Name, Value, **kw):
            written[Name] = Value

    monkeypatch.setattr(gov, "_ssm", _SSM())
    gov._write_surge_active(True, 1188)
    assert written[gov.SSM_SURGE_PARAM] == "true@1188"
    assert gov._read_surge_state() == (True, 1188)
    gov._write_surge_active(False, None)
    assert written[gov.SSM_SURGE_PARAM] == "false"
    assert gov._read_surge_state() == (False, None)


# ── D. the attribution a human reads ─────────────────────────────────────────────────────
def test_d_the_note_names_the_band_the_bar_and_the_minting_bar(surge):
    note = surge.held_by_note(surge.decide(1011, 1188, True, 1188), 1011)
    assert note == "hysteresis (band 950.4, bar 1188, engaged_at_bar=1188)"
    assert surge.held_by_note(surge.decide(1400, 1383, False), 1400) == "bar (1400 >= 1383, engaged_at_bar=1383)"


def test_d_a_cross_bar_disengage_says_why(surge):
    """A ceiling that drops $252 → $215 with no traffic change would otherwise read as an
    unexplained tightening — the class the corrected ADR note exists to prevent."""
    note = surge.held_by_note(surge.decide(1011, 1188, True, 900), 1011)
    assert "900->1188" in note and "1011 < 1188" in note


def test_d_the_receipt_serves_the_attribution(monkeypatch):
    """`/api/receipts` — the public surface. `surge_active: true` alone cannot tell a
    reader whether the reading cleared the bar or is merely inside the band below it, and
    the difference is 17% of the ceiling."""
    from web import site_api_intelligence as sai

    breakdown = {
        "tier": 0,
        "mtd": 48.48,
        "projected": 93.94,
        "ceiling": 252.0,
        "surge_active": True,
        "recent_uniques": 1218,
        "surge_threshold": 1383,
        "surge_held_by": "hysteresis (band 1106.4, bar 1383, engaged_at_bar=1383)",
        "surge_engaged_at_bar": 1383,
        "ai_daily": 1.82,
        "non_ai_daily": 1.46,
        "computed_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
    }

    class _SSM:
        class exceptions:
            class ParameterNotFound(Exception):
                pass

        def get_parameter(self, Name):
            if Name.endswith("budget-tier"):
                return {"Parameter": {"Value": "0"}}
            return {"Parameter": {"Value": json.dumps(breakdown)}}

    class _CW:
        def get_metric_statistics(self, **kw):
            return {"Datapoints": []}

        def list_metrics(self, **kw):
            return {"Metrics": []}

    monkeypatch.setattr(sai.boto3, "client", lambda svc, **kw: _CW() if svc == "cloudwatch" else _SSM())
    payload = json.loads(sai.handle_receipts()["body"])
    assert payload["surge_held_by"] == breakdown["surge_held_by"]
    assert payload["surge_engaged_at_bar"] == 1383


def test_d_an_old_breakdown_serves_null_not_a_manufactured_bar(monkeypatch):
    """Between the governor deploy and its next 8h run the breakdown carries neither field.
    A reader must see 'unknown', never an invented `bar`."""
    from web import site_api_intelligence as sai

    breakdown = {
        "tier": 0,
        "mtd": 48.48,
        "projected": 93.94,
        "ceiling": 252.0,
        "surge_active": True,
        "recent_uniques": 1218,
        "surge_threshold": 1383,
        "ai_daily": 1.8,
        "non_ai_daily": 1.4,
        "computed_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
    }

    class _SSM:
        class exceptions:
            class ParameterNotFound(Exception):
                pass

        def get_parameter(self, Name):
            if Name.endswith("budget-tier"):
                return {"Parameter": {"Value": "0"}}
            return {"Parameter": {"Value": json.dumps(breakdown)}}

    class _CW:
        def get_metric_statistics(self, **kw):
            return {"Datapoints": []}

        def list_metrics(self, **kw):
            return {"Metrics": []}

    monkeypatch.setattr(sai.boto3, "client", lambda svc, **kw: _CW() if svc == "cloudwatch" else _SSM())
    payload = json.loads(sai.handle_receipts()["body"])
    assert payload["surge_held_by"] is None
    assert payload["surge_engaged_at_bar"] is None


def test_d_the_breakdown_payload_carries_both_fields(gov, monkeypatch):
    written = {}

    class _SSM:
        class exceptions:
            class ParameterNotFound(Exception):
                pass

        def put_parameter(self, Name, Value, **kw):
            written[Name] = Value

    monkeypatch.setattr(gov, "_ssm", _SSM())
    gov._write_breakdown(
        0,
        48.48,
        93.94,
        1.82,
        1.46,
        datetime(2026, 9, 14, 16, tzinfo=timezone.utc),
        252.0,
        True,
        1218,
        surge_threshold=1383,
        surge_held_by="hysteresis (band 1106.4, bar 1383, engaged_at_bar=1383)",
        surge_engaged_at_bar=1383,
    )
    payload = json.loads(written["/life-platform/budget-breakdown"])
    assert payload["surge_engaged_at_bar"] == 1383
    assert payload["surge_held_by"].startswith("hysteresis (band 1106.4")


# ── E. the identity the handler relies on ────────────────────────────────────────────────
@pytest.mark.parametrize("u", [None, 0, 905, 1011, 1106, 1188, 1218, 1383, 1400])
@pytest.mark.parametrize("prev,minted", [(False, None), (True, 900), (True, 1188), (True, None)])
def test_e_effective_ceiling_agrees_with_decide(gov, surge, monkeypatch, u, prev, minted):
    """`handler()` computes the decision with `decide(...)` and then passes `surge.active`
    into `_effective_ceiling` as the prior. That is only safe because the two predicates
    agree by construction; this pins the identity rather than leaving it to a comment."""
    monkeypatch.setattr(gov, "_active_ceilings", lambda: (gov.MONTHLY_CEILING, gov.SURGE_CEILING_USD))
    d = surge.decide(u, 1188, prev, minted)
    ceiling, active = gov._effective_ceiling(u, 1188, d.active)
    assert active is d.active
    assert ceiling == (gov.SURGE_CEILING_USD if d.active else gov.MONTHLY_CEILING)


# ── F. the handler's persistence of a re-attribution that is NOT an edge ──────────────────
def _handler_fakes(gov, monkeypatch, surge_param_value, uniques, baseline):
    """Drive `lambda_handler` with every AWS client faked, returning the SSM writes."""
    written = {gov.SSM_SURGE_PARAM: surge_param_value}
    puts = []

    class _SSM:
        class exceptions:
            class ParameterNotFound(Exception):
                pass

        def get_parameter(self, Name):
            if Name not in written:
                raise _SSM.exceptions.ParameterNotFound()
            return {"Parameter": {"Value": written[Name]}}

        def put_parameter(self, Name, Value, **kw):
            written[Name] = Value
            puts.append((Name, Value))

    monkeypatch.setattr(gov, "_ssm", _SSM())
    monkeypatch.setattr(gov, "OBSERVE_MODE", False)
    monkeypatch.setattr(gov, "_recent_unique_visitors", lambda now: uniques)
    monkeypatch.setattr(gov, "_weekly_uniques_baseline", lambda now: baseline)
    monkeypatch.setattr(gov, "_surge_flips_30d", lambda now: 0)
    monkeypatch.setattr(gov, "_emit_surge_flip", lambda: None)
    monkeypatch.setattr(gov, "_emit_surge_flip_gauge", lambda n: None)
    monkeypatch.setattr(gov, "_emit_metrics", lambda *a, **k: None)
    monkeypatch.setattr(gov, "_emit_token_alarm_window_gauge", lambda: None)
    monkeypatch.setattr(gov, "_alert", lambda *a, **k: None)
    monkeypatch.setattr(gov, "_alert_surge", lambda *a, **k: None)
    monkeypatch.setattr(gov, "_non_ai_daily_series", lambda *a, **k: [])
    monkeypatch.setattr(gov, "_ai_cost", lambda *a, **k: 1.0)
    monkeypatch.setattr(gov, "_self_reported_cost_by_class", lambda *a, **k: {})
    monkeypatch.setattr(gov, "_self_reported_cost_mtd", lambda *a, **k: 0.0)
    # The episodic-premise reporter is left REAL (it is pure over the datapoints it is
    # handed) and fed an empty CloudWatch — faking it out was how this harness first
    # produced a green run against a `_write_breakdown` it never actually reached.
    monkeypatch.setattr(
        gov,
        "_cw",
        type(
            "_CW",
            (),
            {
                "get_metric_data": staticmethod(lambda **k: {"MetricDataResults": []}),
                "get_metric_statistics": staticmethod(lambda **k: {"Datapoints": []}),
                "put_metric_data": staticmethod(lambda **k: None),
            },
        )(),
    )
    return written, puts


def test_f_a_re_attribution_without_an_edge_is_still_persisted(gov, monkeypatch):
    """The trap inside the fix: surge stays ON across a bar move because the reading clears
    the NEW bar. There is no engage/disengage edge, so the pre-#3661 write site never fires
    — and SSM would keep naming a retired bar forever, re-deciding against it every run."""
    baseline = [900, 900, 900, 900, 900, 900, 900, 900]  # zero SD -> the bar is the 900 floor
    written, puts = _handler_fakes(gov, monkeypatch, "true@1188", uniques=1000, baseline=baseline)
    gov.lambda_handler({}, None)
    assert written[gov.SSM_SURGE_PARAM] == "true@900", f"re-attribution not persisted (writes: {puts})"


def test_f_a_same_bar_hold_writes_nothing(gov, monkeypatch):
    """The counter-case, so the test above cannot pass by writing on every run."""
    baseline = [900, 900, 900, 900, 900, 900, 900, 900]
    written, puts = _handler_fakes(gov, monkeypatch, "true@900", uniques=800, baseline=baseline)
    gov.lambda_handler({}, None)
    assert written[gov.SSM_SURGE_PARAM] == "true@900"
    assert not [p for p in puts if p[0] == gov.SSM_SURGE_PARAM], f"a stable hold rewrote the state: {puts}"
