"""tests/test_paging_alarms_1333.py — ADR-143: the paging P1 set is named, tiny, wired.

Static-analysis guards (no CDK install / no AWS), mirroring
tests/test_serve_throttles_alarms.py: AST-parse the stack sources and assert
the ADR-143 posture holds in code:

  1. The dedicated topic exists in CoreStack (life-platform-paging) — never
     the alerts topic.
  2. The paged P1 set is exactly the ADR's named set and stays <= 5.
  3. Each paging alarm in monitoring_stack routes to the paging topic; the
     paged canary legs in operational_stack pass page=True and the helper
     actually attaches the paging action on that flag.
  4. The out-of-band wire script exists and reads the sanctioned SecureString
     (the phone number itself must never appear in the repo).

Growing the paged set is an ADR-143 amendment: change the ADR first, then
this registry.
"""

import ast
import os
import re

_STACKS = os.path.join(os.path.dirname(__file__), "..", "cdk", "stacks")
_DEPLOY = os.path.join(os.path.dirname(__file__), "..", "deploy")

# The canonical paged P1 set (ADR-143). ≤5, forever — see the ADR's revisit triggers.
PAGED_P1_SET = {
    "paging-budget-tier-3",
    "paging-pipeline-dead",
    "life-platform-canary-ddb-failure",
    "life-platform-canary-s3-failure",
}


def _src(name):
    with open(os.path.join(_STACKS, name)) as f:
        return f.read()


def _alarm_calls(tree):
    """All cloudwatch.Alarm(...) calls keyed by their alarm_name literal."""
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "Alarm":
            for kw in node.keywords:
                if kw.arg == "alarm_name" and isinstance(kw.value, ast.Constant):
                    out[kw.value.value] = node
    return out


def test_set_is_at_most_five():
    assert len(PAGED_P1_SET) <= 5, "ADR-143: the paged set must stay <=5 — amend the ADR before growing it"


def test_core_stack_creates_dedicated_paging_topic():
    src = _src("core_stack.py")
    assert 'topic_name="life-platform-paging"' in src, "ADR-143: CoreStack must create the dedicated paging topic"


def test_monitoring_paging_alarms_exist_with_adr_thresholds():
    tree = ast.parse(_src("monitoring_stack.py"))
    alarms = _alarm_calls(tree)
    for name in ("paging-budget-tier-3", "paging-pipeline-dead"):
        assert name in alarms, f"ADR-143 paged alarm missing from monitoring_stack: {name}"
    tier3 = next(kw.value.value for kw in alarms["paging-budget-tier-3"].keywords if kw.arg == "threshold")
    assert tier3 == 3, "paging-budget-tier-3 must fire at the ADR-063 HARD cutoff (tier 3), not tier 2"
    dead = next(kw.value.value for kw in alarms["paging-pipeline-dead"].keywords if kw.arg == "threshold")
    assert dead >= 8, "paging-pipeline-dead pages on the total-failure class (>=8 stale sources), not one flaky source"


def test_monitoring_paging_alarms_route_to_paging_topic():
    src = _src("monitoring_stack.py")
    assert 'sns.Topic.from_topic_arn(self, "PagingTopic", PAGING_TOPIC_ARN)' in src
    for var in ("paging_budget_tier3", "paging_pipeline_dead"):
        assert re.search(rf"{var}\.add_alarm_action\(cw_actions\.SnsAction\(paging\)\)", src), f"{var} must route to the paging topic"
    # The dedicated-topic rule: no paging alarm may ride the alerts topic.
    assert "life-platform-paging" in src or "PAGING_TOPIC_ARN" in src


def test_operational_canary_outage_legs_page():
    src = _src("operational_stack.py")
    tree = ast.parse(src)
    paged, unpaged = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_canary_alarm":
            aname = node.args[1].value
            flags = {kw.arg: getattr(kw.value, "value", None) for kw in node.keywords}
            (paged if flags.get("page") else unpaged).add(aname)
    assert {
        "life-platform-canary-ddb-failure",
        "life-platform-canary-s3-failure",
    } <= paged, "the two outage canary legs must page (ADR-143)"
    assert "life-platform-canary-mcp-failure" in unpaged, "MCP canary is not a reader outage — digest only"
    # The helper must actually honour the flag with the paging topic.
    assert re.search(r"if page:\s*\n\s*a\.add_alarm_action\(cw_actions\.SnsAction\(local_paging_topic\)\)", src)


def test_paged_set_matches_wired_reality():
    """The registry above == the union of what the two stacks actually page."""
    mon = ast.parse(_src("monitoring_stack.py"))
    wired = {n for n in _alarm_calls(mon) if n.startswith("paging-")}
    op = ast.parse(_src("operational_stack.py"))
    for node in ast.walk(op):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_canary_alarm":
            if any(kw.arg == "page" and getattr(kw.value, "value", None) for kw in node.keywords):
                wired.add(node.args[1].value)
    assert wired == PAGED_P1_SET, f"paged wiring drifted from the ADR-143 registry: {wired ^ PAGED_P1_SET}"


def test_wire_script_reads_securestring_never_a_literal_number():
    path = os.path.join(_DEPLOY, "wire_paging_phone.sh")
    assert os.path.exists(path), "deploy/wire_paging_phone.sh is the sanctioned subscription path (ADR-143)"
    with open(path) as f:
        script = f.read()
    assert "/life-platform/paging-phone" in script and "--with-decryption" in script
    assert "life-platform-paging" in script
    assert not re.search(r"\+1\d{7,}", script), "a literal phone number must never enter the repo"
