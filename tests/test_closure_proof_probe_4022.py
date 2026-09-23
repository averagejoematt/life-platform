"""tests/test_closure_proof_probe_4022.py — close-on-first-live-output (#4022).

What is proven here, each against the REAL module it names (never a copy):

  1. The `## Proof probe` grammar (`lambdas/operational/proof_probe.py`) parses the shapes
     the backfill uses and rejects the malformed ones with a named error.
  2. The predicate: only an observed, non-degraded, TRUE reading may close. Planted
     negative controls — a false predicate, an absent field, a degraded read, a degraded
     value — each come back as something other than `true`.
  3. The closing comment the leg writes passes `scripts/closure_sweep.py::evaluate_issue`
     (detector A, whose `no-live-proof` code is armed BLOCK) — graded by the sweep itself.
     Mutation controls: dropping the instant, or the residual's home, reds the sweep.
  4. The nightly leg (`operational.closure_probe_qa`) against a fake GitHub + fake AWS:
     closes on a true block, audit line FIRST; never closes on false/absent/degraded/expired;
     degrades to a WARN (no write) without the credential; writes nothing off the schedule;
     aborts the close when the audit write fails.
  5. The leg merges nothing (AST: no merge call, no `/merge` URL).
  6. The registry (`scripts/closure_contract.py`) re-exports the ONE parser, and the
     hygiene linter's advisory derives from it.

Fully offline.
"""

from __future__ import annotations

import ast
import json
import pathlib
import sys
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "lambdas"))
sys.path.insert(0, str(REPO / "scripts"))

import closure_contract as cc  # noqa: E402
import closure_sweep as sweep  # noqa: E402
from operational import (
    closure_probe_qa as leg,  # noqa: E402
    proof_probe as pp,  # noqa: E402
)
from operational.qa_check import CONTENT_TRUTH, Check  # noqa: E402

# the leg takes its clock as `now=` — every call below passes this frozen instant
frozen_now = datetime(2026, 9, 27, 18, 31, 7, tzinfo=timezone.utc)
FAKE_TOKEN = "fake-token-for-tests"  # noqa: S105 — a test double, never a credential
SCHEDULED = {"source": "aws.events", "detail-type": "Scheduled Event"}


def _body(*lines: str, expires: str = "2026-10-18", residual: str | None = None) -> str:
    out = ["## Problem", "x", "", "## Proof probe"]
    out += [f"- probe: {ln}" for ln in lines]
    out.append(f"- expires: {expires}")
    if residual:
        out.append(f"- residual: {residual}")
    out += ["", "## Acceptance", "- [ ] y"]
    return "\n".join(out)


# ── 1. grammar ─────────────────────────────────────────────────────────────────────────
def test_parses_the_backfill_shapes():
    body = _body(
        "api_field `/api/calibration` `platform.strata.weekly_prescriptions.n` >= 1",
        "qa_check `data:coach_ensemble_phase_stamp_coverage` non_degraded",
        "api_field `/api/hypotheses` `hypotheses[*].test_spec.min_effect_provenance.source` exists",
        residual="#4059 carries the provenance-date boxes",
    )
    block = pp.parse_block(body)
    assert block is not None and block.valid, block and block.errors
    assert [p.kind for p in block.probes] == ["api_field", "qa_check", "api_field"]
    assert block.probes[0].predicate == "gte" and block.probes[0].value == "1"
    assert block.probes[1].predicate == "non_degraded" and block.probes[1].value is None
    assert block.expires == date(2026, 10, 18)
    assert block.residual.startswith("#4059")


def test_section_stops_at_the_next_heading():
    body = _body("qa_check `x:y` exists") + "\n\n## Later\n- probe: nonsense"
    block = pp.parse_block(body)
    assert block.valid and len(block.probes) == 1


def test_no_section_is_none_not_an_empty_block():
    assert pp.parse_block("## Problem\nnothing here") is None


@pytest.mark.parametrize(
    "line, fragment",
    [
        ("bogus_kind `x` exists", "unknown probe kind"),
        ("api_field `/site/page` exists", "starting `/api/`"),
        ("api_field `/api/x` `a.b` >= many", "numeric"),
        ("api_field `/api/x` equals", "needs a value"),
        ("api_field `/api/x` exists 3", "takes no value"),
        ("ddb_key `USER#matthew#SOURCE#x` exists", "`<pk> | <sk>`"),
        ("ci_job `ci-cd.yml` equals success", "`<workflow file> :: <job name>`"),
        ("api_field /api/x exists", "unparseable probe line"),
    ],
)
def test_malformed_probe_lines_are_named(line, fragment):
    block = pp.parse_block(_body(line))
    assert block is not None and not block.valid
    assert any(fragment in e for e in block.errors), block.errors


def test_missing_expires_and_unhomed_residual_are_invalid():
    no_exp = "## Proof probe\n- probe: qa_check `a:b` exists\n"
    assert any("expires" in e for e in pp.parse_block(no_exp).errors)
    unhomed = pp.parse_block(_body("qa_check `a:b` exists", residual="some follow-up remains"))
    assert not unhomed.valid and any("home" in e for e in unhomed.errors)


def test_expiry_is_strictly_after_the_date():
    block = pp.parse_block(_body("qa_check `a:b` exists", expires="2026-09-27"))
    assert not pp.is_expired(block, date(2026, 9, 27))
    assert pp.is_expired(block, date(2026, 9, 28))


# ── 2. the predicate, with planted negative controls ───────────────────────────────────
def _probe(line: str) -> pp.Probe:
    p, err = pp.parse_probe_line(f"- probe: {line}")
    assert err is None, err
    return p


GTE = "api_field `/api/calibration` `platform.strata.weekly_prescriptions.n` >= 1"


def test_true_reading_is_true():
    doc = {"platform": {"strata": {"weekly_prescriptions": {"n": 1}}}}
    assert pp.evaluate(_probe(GTE), pp.Reading(doc=doc, found=True)).verdict == pp.VERDICT_TRUE


def test_negative_control_false_predicate_does_not_fire():
    doc = {"platform": {"strata": {"weekly_prescriptions": {"n": 0}}}}
    assert pp.evaluate(_probe(GTE), pp.Reading(doc=doc, found=True)).verdict == pp.VERDICT_FALSE


def test_negative_control_absent_field_does_not_fire():
    doc = {"platform": {"strata": {"coaches": {"n": 19}}}}
    assert pp.evaluate(_probe(GTE), pp.Reading(doc=doc, found=True)).verdict == pp.VERDICT_ABSENT
    assert pp.evaluate(_probe(GTE), pp.Reading(found=False)).verdict == pp.VERDICT_ABSENT
    null = {"platform": {"strata": {"weekly_prescriptions": {"n": None}}}}
    assert pp.evaluate(_probe(GTE), pp.Reading(doc=null, found=True)).verdict == pp.VERDICT_ABSENT


def test_negative_control_degraded_read_does_not_fire():
    assert pp.evaluate(_probe(GTE), pp.Reading(error="HTTP 503")).verdict == pp.VERDICT_DEGRADED


def test_negative_control_degraded_document_does_not_fire():
    doc = {"status": "degraded", "platform": {"strata": {"weekly_prescriptions": {"n": 4}}}}
    assert pp.evaluate(_probe(GTE), pp.Reading(doc=doc, found=True)).verdict == pp.VERDICT_DEGRADED


@pytest.mark.parametrize("status, verdict", [("ok", "true"), ("warn", "degraded"), ("fail", "degraded"), ("paused", "degraded")])
def test_non_degraded_on_a_qa_check_status(status, verdict):
    p = _probe("qa_check `data:x` non_degraded")
    assert pp.evaluate(p, pp.Reading(doc=status, found=True)).verdict == verdict


def test_star_fans_out_to_any_element():
    p = _probe("api_field `/api/hypotheses` `hypotheses[*].test_spec.min_effect_provenance.source` exists")
    old = {"hypotheses": [{"test_spec": {"min_effect": 0.1}}]}
    assert pp.evaluate(p, pp.Reading(doc=old, found=True)).verdict == pp.VERDICT_ABSENT
    new = {"hypotheses": [{"test_spec": {}}, {"test_spec": {"min_effect_provenance": {"source": "derived"}}}]}
    assert pp.evaluate(p, pp.Reading(doc=new, found=True)).verdict == pp.VERDICT_TRUE


def test_equals_and_decimal_values():
    p = _probe("ddb_key `USER#matthew#SOURCE#x | DATE#2026-09-27` `count` equals 3")
    assert pp.evaluate(p, pp.Reading(doc={"count": Decimal("3")}, found=True)).verdict == pp.VERDICT_TRUE
    assert pp.evaluate(p, pp.Reading(doc={"count": Decimal("2")}, found=True)).verdict == pp.VERDICT_FALSE


def test_block_is_and_over_its_probes():
    t = pp.Evaluation(_probe("qa_check `a:b` exists"), pp.VERDICT_TRUE, "ok", "")
    f = pp.Evaluation(_probe("qa_check `a:c` exists"), pp.VERDICT_FALSE, "x", "")
    assert pp.block_verdict([t, t]) == pp.VERDICT_TRUE
    assert pp.block_verdict([t, f]) == pp.VERDICT_FALSE
    assert pp.block_verdict([]) != pp.VERDICT_TRUE


def test_private_values_are_never_rendered():
    p = _probe("ddb_key `USER#matthew#SOURCE#withings | DATE#2026-09-27` `weight_lbs` >= 1")
    e = pp.Evaluation(p, pp.VERDICT_TRUE, Decimal("301.4"), "")
    assert "301.4" not in pp.render_observed(e)
    assert "301.4" not in pp.closing_comment([e], frozen_now)


# ── 3. the closing comment, graded by the REAL closure sweep ───────────────────────────
def _closed_issue(comment: str, labels=("closure:live-proof", "type:story")) -> sweep.Issue:
    posted = frozen_now
    return sweep.Issue(
        number=3712,
        title="t",
        closed_at=posted + timedelta(seconds=2),
        state_reason="COMPLETED",
        labels=tuple(labels),
        comments=[(posted, "averagejoematt", comment)],
        author="averagejoematt",
    )


def _true_evals():
    p = _probe(GTE)
    return [pp.Evaluation(p, pp.VERDICT_TRUE, 1, "predicate held")]


def test_closing_comment_passes_closure_sweep_by_construction():
    comment = pp.closing_comment(_true_evals(), frozen_now)
    assert sweep.evaluate_issue(_closed_issue(comment)) == []
    assert cc.names_live_proof(comment) and cc.has_verdict(comment) and cc.verdict_kind(comment) == "realized"


def test_declared_residual_with_a_carrier_also_passes():
    comment = pp.closing_comment(_true_evals(), frozen_now, residual="#4059 carries the provenance-date boxes (a follow-up)")
    assert sweep.evaluate_issue(_closed_issue(comment)) == []


def test_mutation_dropping_the_instant_reds_no_live_proof():
    comment = pp.closing_comment(_true_evals(), frozen_now).replace(frozen_now.strftime("%Y-%m-%dT%H:%M:%SZ"), "tonight")
    codes = {f.code for f in sweep.evaluate_issue(_closed_issue(comment))}
    assert "no-live-proof" in codes


def test_mutation_dropping_the_verdict_reds_no_outcome_verdict():
    comment = "\n".join(ln for ln in pp.closing_comment(_true_evals(), frozen_now).splitlines() if not ln.startswith("**Outcome:**"))
    codes = {f.code for f in sweep.evaluate_issue(_closed_issue(comment))}
    assert "no-outcome-verdict" in codes


def test_mutation_unhomed_residual_reds_the_sweep():
    comment = pp.closing_comment(_true_evals(), frozen_now, residual="a follow-up is deferred")
    codes = {f.code for f in sweep.evaluate_issue(_closed_issue(comment))}
    assert "unhomed-residual" in codes


# ── 4. the nightly leg, end to end against fakes ───────────────────────────────────────
class FakeGitHub(leg.GitHub):
    def __init__(self, issues, token=FAKE_TOKEN):
        super().__init__(token=token)
        self._issues = issues
        self.calls = []

    def open_labelled_issues(self):
        self.calls.append(("list",))
        return self._issues

    def comment(self, number, body):
        self.calls.append(("comment", number, body))
        return 201

    def close(self, number):
        self.calls.append(("close", number))
        return 200

    def latest_job_conclusion(self, workflow, job):
        return pp.Reading(doc="success", found=True, note="run 1")


class FakeS3:
    def __init__(self, fail=False):
        self.fail = fail
        self.puts = []

    def put_object(self, **kw):
        if self.fail:
            raise RuntimeError("put denied")
        self.puts.append(kw)

    def get_object(self, **kw):
        raise KeyError(kw)


class FakeResp:
    def __init__(self, doc, status=200):
        self._raw = json.dumps(doc).encode()
        self.status = status

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _opener(doc):
    def op(req, timeout=None):
        return FakeResp(doc)

    return op


def _issue(n, body, labels=("closure:live-proof",)):
    return {"number": n, "body": body, "labels": [{"name": x} for x in labels]}


def _run(issues, *, doc=None, event=SCHEDULED, token=FAKE_TOKEN, s3=None, checks=(), dry_run=False):
    gh = FakeGitHub(issues, token=token)
    s3 = s3 or FakeS3()
    out = leg.check_closure_proof_probes(
        list(checks),
        table=None,
        s3=s3,
        bucket="b",
        Check=Check,
        partition=CONTENT_TRUTH,
        site_base_url="https://example.invalid",
        event=event,
        dry_run=dry_run,
        github=gh,
        cloudwatch_factory=lambda: None,
        now=frozen_now,
        http_opener=_opener(doc if doc is not None else {}),
    )
    return out, gh, s3


TRUE_DOC = {"platform": {"strata": {"weekly_prescriptions": {"n": 1}}}}


def test_leg_closes_on_a_true_block_audit_first():
    out, gh, s3 = _run([_issue(3712, _body(GTE))], doc=TRUE_DOC)
    (c,) = out
    assert c.passed is True, c.message
    assert [k[0] for k in gh.calls] == ["list", "comment", "close"]
    assert len(s3.puts) == 1 and s3.puts[0]["Key"].startswith("remediation-log/closure-probe/2026/09/27/")
    audit = json.loads(s3.puts[0]["Body"])
    assert audit["issue"] == 3712 and audit["action"] == "close"
    comment = gh.calls[1][2]
    assert sweep.evaluate_issue(_closed_issue(comment)) == []
    assert "2026-09-27T18:31:07Z" in comment and "#3712" in c.message


@pytest.mark.parametrize(
    "doc",
    [
        {"platform": {"strata": {"weekly_prescriptions": {"n": 0}}}},  # false predicate
        {"platform": {"strata": {}}},  # absent field
        {"status": "degraded", "platform": {"strata": {"weekly_prescriptions": {"n": 3}}}},  # degraded document
    ],
)
def test_leg_never_closes_on_a_non_true_reading(doc):
    out, gh, s3 = _run([_issue(3712, _body(GTE))], doc=doc)
    assert [k[0] for k in gh.calls] == ["list"] and not s3.puts
    assert out[0].passed is True  # pending is a normal night, not a warn


def test_leg_never_closes_on_a_failed_read():
    def boom(req, timeout=None):
        raise OSError("network down")

    gh = FakeGitHub([_issue(3712, _body(GTE))])
    s3 = FakeS3()
    (c,) = leg.check_closure_proof_probes(
        [],
        None,
        s3,
        "b",
        Check,
        CONTENT_TRUTH,
        site_base_url="https://x.invalid",
        event=SCHEDULED,
        github=gh,
        now=frozen_now,
        http_opener=boom,
    )
    assert [k[0] for k in gh.calls] == ["list"] and not s3.puts
    assert "degraded" in c.message or "pending 1" in c.message


def test_leg_and_semantics_one_false_probe_blocks_the_close():
    body = _body(GTE, "qa_check `data:x` non_degraded")
    warn = Check("data:x", "X", CONTENT_TRUTH).warn("w")
    out, gh, s3 = _run([_issue(4040, body)], doc=TRUE_DOC, checks=[warn])
    assert [k[0] for k in gh.calls] == ["list"] and not s3.puts


def test_leg_reads_this_runs_qa_check():
    ok = Check("data:coach_ensemble_phase_stamp_coverage", "Phase Stamping", CONTENT_TRUTH).ok("fine")
    body = _body("qa_check `data:coach_ensemble_phase_stamp_coverage` non_degraded", residual="#4059 carries the rest")
    out, gh, s3 = _run([_issue(4040, body)], checks=[ok])
    assert [k[0] for k in gh.calls] == ["list", "comment", "close"]
    assert "#4059" in gh.calls[1][2]


def test_expired_probe_is_a_needs_human_warn_not_a_close():
    out, gh, s3 = _run([_issue(3712, _body(GTE, expires="2026-09-01"))], doc=TRUE_DOC)
    (c,) = out
    assert c.passed is None and "needs a human" in c.message and "#3712" in c.message
    assert [k[0] for k in gh.calls] == ["list"] and not s3.puts


def test_no_credential_degrades_to_a_warn_with_no_write():
    out, gh, s3 = _run([_issue(3712, _body(GTE))], doc=TRUE_DOC, token=None)
    (c,) = out
    assert c.passed is None and "no write credential" in c.message
    assert [k[0] for k in gh.calls] == ["list"] and not s3.puts


def test_unset_env_var_never_attempts_the_secret_read(monkeypatch):
    monkeypatch.delenv(leg.TOKEN_SECRET_ENV, raising=False)

    def factory():
        raise AssertionError("secret client must not be built when the env var is unset")

    assert leg.load_token(factory) is None


def test_off_schedule_invokes_run_nothing():
    for event in ({}, {"synthetic_fail": True}, None):
        out, gh, s3 = _run([_issue(3712, _body(GTE))], doc=TRUE_DOC, event=event)
        assert out == [] and gh.calls == [] and not s3.puts


def test_report_invoke_and_dry_run_evaluate_but_never_write():
    out, gh, s3 = _run([_issue(3712, _body(GTE))], doc=TRUE_DOC, event={"closure_probe": "report"})
    assert out[0].passed is True and [k[0] for k in gh.calls] == ["list"] and not s3.puts
    out, gh, s3 = _run([_issue(3712, _body(GTE))], doc=TRUE_DOC, dry_run=True)
    assert [k[0] for k in gh.calls] == ["list"] and not s3.puts


def test_failed_audit_aborts_the_close():
    out, gh, s3 = _run([_issue(3712, _body(GTE))], doc=TRUE_DOC, s3=FakeS3(fail=True))
    (c,) = out
    assert c.passed is None and "audit write failed" in c.message
    assert [k[0] for k in gh.calls] == ["list"]


def test_unlistable_github_is_a_warn_never_a_pass():
    class Down(FakeGitHub):
        def open_labelled_issues(self):
            raise RuntimeError("GitHub issue list returned HTTP 403")

    (c,) = leg.check_closure_proof_probes(
        [], None, FakeS3(), "b", Check, CONTENT_TRUTH, site_base_url="x", event=SCHEDULED, github=Down([]), now=frozen_now
    )
    assert c.passed is None and "could not look" in c.message


def test_no_probe_and_invalid_probe_issues_are_reported_not_touched():
    issues = [_issue(3671, "## Problem\nno probe"), _issue(4055, "## Proof probe\n- probe: nope\n")]
    out, gh, s3 = _run(issues, doc=TRUE_DOC)
    assert out[0].passed is True and "no probe 1" in out[0].message and "invalid 1" in out[0].message
    assert [k[0] for k in gh.calls] == ["list"]


def test_the_leg_never_raises():
    class Explode(FakeGitHub):
        def open_labelled_issues(self):
            return [None]  # an unexpected payload shape

    (c,) = leg.check_closure_proof_probes(
        [], None, FakeS3(), "b", Check, CONTENT_TRUTH, site_base_url="x", event=SCHEDULED, github=Explode([]), now=frozen_now
    )
    assert c.passed is None


# ── 5. it merges nothing ───────────────────────────────────────────────────────────────
def test_the_leg_has_no_merge_path():
    src = (REPO / "lambdas" / "operational" / "closure_probe_qa.py").read_text()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
            assert "merge" not in name.lower(), name
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            assert "/merge" not in node.value and "pulls/" not in node.value, node.value
        if isinstance(node, ast.JoinedStr):
            text = "".join(v.value for v in node.values if isinstance(v, ast.Constant) and isinstance(v.value, str))
            assert "/merge" not in text and "pulls/" not in text, text


def test_github_writes_are_only_comment_and_close():
    src = (REPO / "lambdas" / "operational" / "closure_probe_qa.py").read_text()
    methods = {
        node.args[0].value
        for node in ast.walk(ast.parse(src))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "_req"
        and node.args
        and isinstance(node.args[0], ast.Constant)
    }
    assert methods == {"GET", "POST", "PATCH"}


# ── 6. one parser, re-exported ─────────────────────────────────────────────────────────
def test_closure_contract_reexports_the_one_parser():
    assert cc.PROOF_PROBE.__file__ == pp.__file__
    assert pp.INSTRUMENT_LABEL == cc.INSTRUMENT_LABEL
    body = _body(GTE)
    assert cc.parse_proof_probe(body).valid and pp.parse_block(body).valid


def test_hygiene_advisory_derives_from_the_registry():
    import check_backlog_hygiene as h

    def ctx(body, labels):
        return {"number": 1, "labels": list(labels), "body": body}

    assert h.rule_proof_probe(ctx("## Problem", ["closure:live-proof"]))[0].severity == h.ADVISORY
    assert h.rule_proof_probe(ctx(_body(GTE), ["closure:live-proof"])) == []
    assert h.rule_proof_probe(ctx("## Problem", ["closure:live-proof", "closure:rehearsal-proof"])) == []
    assert h.rule_proof_probe(ctx("## Problem", ["type:story"])) == []
    assert h.rule_proof_probe in h.PER_ISSUE_RULES


def test_qa_smoke_wires_the_leg_after_every_check_step():
    """The leg must run AFTER check_steps() so a `qa_check` probe reads this run's results."""
    src = (REPO / "lambdas" / "operational" / "qa_smoke_lambda.py").read_text()
    handler = src[src.index("def lambda_handler") :]
    assert handler.index("check_steps()") < handler.index("closure_probe_qa.check_closure_proof_probes(")
    assert "all_checks, table, s3, S3_BUCKET" in handler


def test_the_nightly_rule_delivers_eventbridges_own_event():
    """The leg keys its writes on `source == "aws.events"`. That holds only while qa-smoke's
    schedule sends EventBridge's OWN event — a `schedule_input` constant would silently turn
    the leg off (it returns no Check off-schedule). Read from the CDK source, not assumed."""
    src = (REPO / "cdk" / "stacks" / "operational_stack.py").read_text()
    start = src.index('function_name="life-platform-qa-smoke"')
    block = src[start : src.index("create_platform_lambda(", start)]
    assert 'schedule="cron(30 18 ? * * *)"' in block
    assert "schedule_input" not in block
    assert leg.is_scheduled({"source": "aws.events", "detail-type": "Scheduled Event"})
