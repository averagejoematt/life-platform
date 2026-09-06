"""tests/test_qa_check_edge_429.py — #2828: the nightly real-edge 429 observation.

Covers every outcome arm of qa_check_edge_429.checks() by monkeypatching the
module's own `_post_once` (the transport seam — no network), plus the two
lockstep pins that keep the probe honest without runtime imports:

  * MAX_PROBES == BOARD_RATE_LIMIT + 1, AST-read from site_api_ai_lambda.py's
    source (importing the web handler would run its AWS wiring; a hand-copied
    limit would silently drift — the lockstep idiom).
  * the charge-before-validation premise: _handle_board_ask's source performs
    the rate check before the question-length validation. If that ordering
    flips, the probe stops proving anything — this pin makes the flip loud at
    CI time instead of a mystery FAIL at 2am.

The mutation direction that matters (#2828 "no vacuous green"): all-400s must
be a RED, network failure must be YELLOW, and the tier-3 paused payload must
be ⏸ — three distinct outcomes, none of them a silent pass.
"""

import ast
import json
from pathlib import Path

import pytest
from operational import qa_check_edge_429
from operational.qa_check import CONTENT_TRUTH

_OK_429_HEADERS = {"Retry-After": "3600"}
_OK_429_BODY = json.dumps({"error": "Rate limit reached. Try again in an hour."})
_400_BODY = json.dumps({"error": "question too short"})
_PAUSED_BODY = json.dumps({"status": "paused", "message": "AI features are paused this month"})


def _run_with(monkeypatch, responses):
    """responses: list of (status, headers, body) tuples or Exception instances."""
    it = iter(responses)

    def fake_post(url):
        r = next(it)
        if isinstance(r, Exception):
            raise r
        return r

    monkeypatch.setattr(qa_check_edge_429, "_post_once", fake_post)
    out = qa_check_edge_429.checks()
    assert len(out) == 1
    return out[0]


def test_real_429_after_limit_is_pass(monkeypatch):
    seq = [(400, {}, _400_BODY)] * 3 + [(429, _OK_429_HEADERS, _OK_429_BODY)]
    c = _run_with(monkeypatch, seq)
    assert c.passed is True
    assert "429 observed after 4" in c.message
    assert c.partition == CONTENT_TRUTH


def test_all_400s_is_red_the_0814_signature(monkeypatch):
    seq = [(400, {}, _400_BODY)] * qa_check_edge_429.MAX_PROBES
    c = _run_with(monkeypatch, seq)
    assert c.passed is False
    assert "NOT observably enforced" in c.message


def test_429_missing_retry_after_is_red(monkeypatch):
    seq = [(429, {}, _OK_429_BODY)]
    c = _run_with(monkeypatch, seq)
    assert c.passed is False
    assert "shape wrong" in c.message


def test_network_failure_is_yellow_not_green_not_red(monkeypatch):
    seq = [(400, {}, _400_BODY), OSError("connection reset")]
    c = _run_with(monkeypatch, seq)
    assert c.passed is None
    assert c.paused is False
    assert "could not observe" in c.message


def test_5xx_is_yellow(monkeypatch):
    seq = [(502, {}, "bad gateway")]
    c = _run_with(monkeypatch, seq)
    assert c.passed is None
    assert "could not observe" in c.message


def test_budget_paused_payload_is_paused_glyph(monkeypatch):
    seq = [(200, {}, _PAUSED_BODY)]
    c = _run_with(monkeypatch, seq)
    assert c.passed is None
    assert c.paused is True
    assert "budget pause" in c.message


def test_200_nonpaused_on_short_question_is_red(monkeypatch):
    seq = [(200, {}, json.dumps({"answer": "hello!"}))]
    c = _run_with(monkeypatch, seq)
    assert c.passed is False
    assert "premise broken" in c.message


# ── lockstep pins (AST reads of the real source, no runtime import) ──────────

_WEB_SRC = Path(__file__).resolve().parents[1] / "lambdas" / "web" / "site_api_ai_lambda.py"


def _board_rate_limit_from_source():
    tree = ast.parse(_WEB_SRC.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == "BOARD_RATE_LIMIT":
                    return ast.literal_eval(node.value)
        if isinstance(node, ast.AnnAssign):  # the #2638 AnnAssign blindness class
            if isinstance(node.target, ast.Name) and node.target.id == "BOARD_RATE_LIMIT" and node.value is not None:
                return ast.literal_eval(node.value)
    raise AssertionError("BOARD_RATE_LIMIT not found in site_api_ai_lambda.py")


def test_max_probes_lockstep_with_board_rate_limit():
    assert qa_check_edge_429.MAX_PROBES == _board_rate_limit_from_source() + 1, (
        "MAX_PROBES must be BOARD_RATE_LIMIT + 1 — the probe needs exactly enough "
        "requests to observe one real 429; update qa_check_edge_429.MAX_PROBES with the limit"
    )


#: The call that charges the probe's ONE token on the way in. #3560 extracted the
#: DDB/in-memory limiter out of `_handle_board_ask` into this helper so the opening
#: turn and the follow-up turn charge the same counter at the same point in their
#: orders — which also means a pin naming `_ddb_rate_check` here now finds the
#: FAN-OUT charge further down the function and silently measures the wrong pair.
_ENTRY_CHARGE = "_board_rate_charge"


def test_charge_before_validation_premise_holds():
    """_handle_board_ask must hit the ENTRY rate charge BEFORE the length validation —
    the ordering that makes a $0 probe possible (#1439's original analysis). Source-order
    pin: the `_board_rate_charge(` call site must appear before the question-length
    rejection inside the same function body.

    #3560 note: the hazard gate and the budget pause now run ahead of the charge (the
    gate is a $0 offline regex and a person describing an emergency must not be metered
    into silence). Neither disturbs this probe — "hi" is benign, and the paused arm is
    the module's own ⏸ outcome."""
    src = _WEB_SRC.read_text()
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_handle_board_ask")
    rate_line = None
    length_line = None
    for node in ast.walk(fn):
        if isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", "")) == _ENTRY_CHARGE:
            rate_line = rate_line or node.lineno
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and "too short" in node.value.lower():
            length_line = length_line or node.lineno
    assert rate_line is not None, f"{_ENTRY_CHARGE}() call not found in _handle_board_ask — the entry charge was renamed or removed"
    assert length_line is not None, "length validation not found in _handle_board_ask"
    assert rate_line < length_line, (
        "charge-before-validation ordering flipped in _handle_board_ask — the edge-429 "
        "probe premise is broken; re-design the probe before shipping this change"
    )


def test_the_entry_charge_helper_actually_charges_the_board_ask_counter():
    """Non-vacuity for the pin above: naming a helper is only a premise if the helper
    is the thing that spends the token. A `_board_rate_charge` that had stopped calling
    the limiter would leave the pin green and the probe dead."""
    src = _WEB_SRC.read_text()
    tree = ast.parse(src)
    fn = next((n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == _ENTRY_CHARGE), None)
    assert fn is not None, f"{_ENTRY_CHARGE} was renamed or removed"
    body = ast.unparse(fn)
    assert "_ddb_rate_check(" in body, f"{_ENTRY_CHARGE} no longer calls the DDB limiter"
    assert "endpoint='board_ask'" in body or '"board_ask"' in body, f"{_ENTRY_CHARGE} no longer charges the board_ask counter"
    assert "_board_rate_store" in body, f"{_ENTRY_CHARGE} lost the in-memory fallback the fail-open lane uses"


def test_pause_detector_tolerates_garbage():
    assert qa_check_edge_429._is_paused_body("not json") is False
    assert qa_check_edge_429._is_paused_body(json.dumps({"status": "paused"})) is True
    assert qa_check_edge_429._is_paused_body(json.dumps({"answer": "x"})) is False


@pytest.mark.parametrize("arm", ["pass", "red"])
def test_probe_stops_at_first_terminal_outcome(monkeypatch, arm):
    """The probe must never keep charging the counter after a verdict exists."""
    calls = []

    def fake_post(url):
        calls.append(1)
        if arm == "pass":
            return (429, _OK_429_HEADERS, _OK_429_BODY)
        return (200, {}, json.dumps({"answer": "x"}))

    monkeypatch.setattr(qa_check_edge_429, "_post_once", fake_post)
    qa_check_edge_429.checks()
    assert len(calls) == 1
