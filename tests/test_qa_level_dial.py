"""tests/test_qa_level_dial.py — #1452: the QA-depth dial (SSM /life-platform/qa-level).

One knob (full | standard | lean | off) trades QA depth against spend without
editing workflows under pressure — the /life-platform/remediation-mode kill-switch
shape. Contract pinned here:

  1. The two NON-gating QA workflows (visual-qa.yml standalone daily, the weekly
     webkit-mobile-qa.yml advisory) read the dial via `aws ssm get-parameter` and
     FAIL OPEN to `standard` when the param is unreadable/invalid — stated in the
     run log, never a silent default.
  2. The deploy-gating QA can NEVER be disabled by the dial (#1452 AC): the gating
     workflows (ci-cd.yml, site-deploy.yml, the PR gates v4-gate.yml /
     surface-drift.yml) must not reference the parameter at all — structural
     exemption, not a runtime branch.
  3. Dial state surfaces in the weekly green report (E3 — traffic_digest_lambda's
     Monday ops email): fail-soft read, honest "not collected" on error, an
     explicit warn/bad tone when the dial is lean/off so a dialed-down estate is
     never mistaken for a fully-swept green week.
  4. The traffic-digest Lambda role (CDK-owned, role_policies.py) is granted the
     qa-level ssm:GetParameter read — text-pinned (importing role_policies needs
     aws_cdk, a deploy-env dep the unit lane doesn't install; the layer-dep
     collection-red class, memory: reference_test_layer_dep_import_collection_red).

Workflow guards proven RED against the pre-#1452 workflows (no dial read) and the
pre-#1452 green report (no qa_level section) before the implementation landed.
"""

import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
_WF = os.path.join(_REPO, ".github", "workflows")

sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "operational"))

import traffic_digest_lambda as td  # noqa: E402

PARAM = "/life-platform/qa-level"
DIAL_READERS = ("visual-qa.yml", "webkit-mobile-qa.yml")
DIAL_EXEMPT = ("ci-cd.yml", "site-deploy.yml", "v4-gate.yml", "surface-drift.yml")


def _wf_text(name):
    path = os.path.join(_WF, name)
    assert os.path.exists(path), f"{name} missing"
    with open(path, encoding="utf-8") as f:
        return f.read()


# ── 1. the non-gating QA workflows read the dial, fail-open standard ─────────


def test_standalone_qa_workflows_read_the_dial():
    for name in DIAL_READERS:
        text = _wf_text(name)
        assert PARAM in text, f"{name} never reads the QA-depth dial (#1452)"
        assert "ssm get-parameter" in text, f"{name} references the param but never reads it via aws ssm get-parameter"


def test_dial_read_fails_open_to_standard_with_a_log_line():
    for name in DIAL_READERS:
        text = _wf_text(name)
        step = re.search(r"- name:[^\n]*qa-level.*?(?=\n      - name:|\Z)", text, flags=re.S | re.I)
        assert step, f"{name}: no named dial-read step"
        body = step.group(0)
        assert "LEVEL=standard" in body, f"{name}: unreadable dial must fail open to standard"
        assert "fail-open" in body, f"{name}: the fail-open default must be stated in the run log, not silent"
        for level in ("full", "standard", "lean", "off"):
            assert level in body, f"{name}: dial value {level!r} unhandled"


def test_off_and_lean_scale_the_standalone_sweeps():
    # visual-qa.yml: off skips the sweep; lean drops the AI + reader-truth layers
    text = _wf_text("visual-qa.yml")
    assert re.search(r"if:.*!=\s*'off'", text), "visual-qa.yml: no step is conditioned off the dial's off state"
    assert "lean" in text and "reader_truth_flag" in text, "visual-qa.yml: lean must strip the paid/AI layers via computed flags"
    # webkit weekly: only standard/full run the sweep
    wtext = _wf_text("webkit-mobile-qa.yml")
    assert re.search(r"if:.*dial\.outputs\.level", wtext), "webkit-mobile-qa.yml: sweep not conditioned on the dial"


# ── 2. the deploy gate can never be disabled by the dial ─────────────────────


def test_gating_workflows_are_structurally_exempt_from_the_dial():
    for name in DIAL_EXEMPT:
        text = _wf_text(name)
        assert PARAM not in text and "qa-level" not in text, (
            f"{name} references the QA-depth dial — deploy-gating/PR-gating QA must be structurally exempt (#1452 AC: "
            "the deploy gate can never be disabled by the dial)"
        )


# ── 3. dial state in the weekly green report (E3) ────────────────────────────


def test_green_report_renders_the_dial_state():
    html = td.build_green_report_html({"window_days": 7, "qa_level": {"level": "standard"}})
    assert "qa depth dial" in html.lower()
    assert "standard" in html


def test_green_report_dial_off_and_lean_are_loud():
    html_off = td.build_green_report_html({"window_days": 7, "qa_level": {"level": "off"}})
    assert "#b42318" in html_off, "dial=off must render in the bad tone — a dark QA estate can't look green"
    html_lean = td.build_green_report_html({"window_days": 7, "qa_level": {"level": "lean"}})
    assert "#9a6700" in html_lean, "dial=lean must render in the warn tone"


def test_green_report_dial_absent_or_error_is_honest():
    for shape in (
        {"window_days": 7},
        {"window_days": 7, "qa_level": None},
        {"window_days": 7, "qa_level": {"error": "SSM read failed (boom)"}},
    ):
        html = td.build_green_report_html(shape)  # must not raise
        assert "Weekly green report" in html
    html = td.build_green_report_html({"window_days": 7, "qa_level": {"error": "SSM read failed (boom)"}})
    assert "not collected" in html


def test_green_report_unset_param_reads_as_standard_default():
    """An account where the param was never created is level standard by
    definition (fail-open) — the report says so instead of an error."""
    html = td.build_green_report_html({"window_days": 7, "qa_level": {"level": "standard", "note": "param unset — fail-open default"}})
    assert "param unset" in html


def test_collect_green_report_is_fail_soft_on_the_dial(monkeypatch):
    class _Boom:
        def __getattr__(self, _):
            raise RuntimeError("no aws here")

    monkeypatch.setattr(td.boto3, "client", lambda *a, **k: _Boom())
    report = td.collect_green_report()
    assert "qa_level" in report, "collect_green_report never gathers the dial state (#1452 E3)"
    assert report["qa_level"].get("error") or report["qa_level"].get("level"), "dial section must be a reading or an honest error"


# ── 4. the IAM read is codified (text-pinned; R8-ST6 applies to the PR) ──────


def test_traffic_digest_role_grants_the_qa_level_read():
    path = os.path.join(_REPO, "cdk", "stacks", "role_policies.py")
    with open(path, encoding="utf-8") as f:
        text = f.read()
    m = re.search(r"def operational_traffic_digest.*?(?=\ndef )", text, flags=re.S)
    assert m, "operational_traffic_digest() missing from role_policies.py"
    assert "parameter/life-platform/qa-level" in m.group(
        0
    ), "traffic-digest role lacks the ssm:GetParameter grant on /life-platform/qa-level (#1452)"
