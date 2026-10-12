"""
tests/test_season_rebuild_batch_4777.py — the season rebuild adopts the Bedrock batch path (#4777, ADR-132 amended).

The rebuild's write chain is sequential (every call reads the one before it), so its one fan-out is the fact-read
sweep (``scripts/season_rebuild.py --recheck``): a fresh fact read of every staged post, dek and episode, sent through
``bedrock_batch.run_or_fallback``. Pinned here:

  * below the 100-record floor every read runs on-demand and the OUTPUT says so (box 3's fallback half);
  * at/above the floor one batch job is submitted, results map back by recordId, and a record the job did not answer
    re-runs on-demand (box 3's batch half — the S3/Bedrock calls are faked, nothing reaches AWS);
  * a batch reply goes through the SAME ``fact_findings`` gate as a real-time reply — an incomplete batch read is a
    finding, never a pass (box 4: a cheaper path skips no gate);
  * the split of ``fact_check`` into body + parse changed nothing for the live gate.

Run:  python3 -m pytest tests/test_season_rebuild_batch_4777.py -v
"""

import importlib.util
import json
import os
import sys
import types

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))

from ai import bedrock_batch as bb  # noqa: E402
from bundle_stubs import stub_bundled_module  # noqa: E402
from content import story_ledger, story_writers  # noqa: E402

_spec = importlib.util.spec_from_file_location("season_rebuild_4777", os.path.join(ROOT, "scripts", "season_rebuild.py"))
sr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sr)


def _stage(out, weeks):
    for n in weeks:
        files = {
            f"wk{n}_dossier.json": {"week": n, "window": {"start": "2026-09-06", "end": "2026-09-12"}},
            f"wk{n}_budget.json": {"top_line": f"Week {n} in one plain line."},
            f"wk{n}_ledger.json": story_ledger.empty_ledger(),
            f"wk{n}_episode.json": {"title": f"Ep {n}", "excerpt": "", "turns": [{"speaker": "elena", "line": f"Week {n}, briefly."}]},
        }
        for name, obj in files.items():
            with open(os.path.join(out, name), "w", encoding="utf-8") as fh:
                json.dump(obj, fh)
        with open(os.path.join(out, f"wk{n}_chronicle.md"), "w", encoding="utf-8") as fh:
            fh.write(f'"Title {n}"\n\n*Week {n} in one plain line.*\n\nThe body of week {n}.\n\n---\n*Week {n} of The Measured Life*')


def _reply(findings=(), stop="end_turn"):
    return {"stop_reason": stop, "content": [{"type": "text", "text": json.dumps({"findings": list(findings)})}], "usage": {}}


_FINDING = {"claim": "twelve calls", "problem": "sixteen were filed", "fix": "sixteen calls"}


def _tier(monkeypatch, n=0):
    stub = types.ModuleType("budget_guard")
    stub.current_tier = lambda: n
    stub_bundled_module(monkeypatch, "ai.budget_guard", stub)


def _load(out, name):
    with open(os.path.join(out, name), encoding="utf-8") as fh:
        return json.load(fh)


def test_below_the_floor_every_read_runs_on_demand_and_the_output_says_so(tmp_path, capsys):
    out = str(tmp_path)
    _stage(out, [0, 1])
    seen = []

    def realtime(model_input):
        seen.append(model_input)
        text = model_input["messages"][0]["content"]
        return _reply([_FINDING] if "The body of week 1." in text else [])

    rc = sr.recheck(out, [0, 1], realtime_fn=realtime)
    printed = capsys.readouterr().out
    assert rc == 1
    assert len(seen) == 6  # post + dek + episode for two weeks, all on-demand
    assert "mode=realtime" in printed and "ran on-demand" in printed and f"< {bb.MIN_RECORDS_PER_JOB}" in printed
    summary = _load(out, "recheck.json")
    assert summary["mode"] == "realtime" and summary["job_arn"] is None and summary["records"] == 6
    wk1 = _load(out, "wk1_recheck.json")
    assert len(wk1["findings"]["post"]) == 1 and wk1["findings"]["post"][0].startswith("post: fact: 'twelve calls'")
    assert wk1["batched"] == {"post": False, "dek": False, "episode": False}


def test_at_the_floor_one_batch_job_runs_and_results_map_back_by_record_id(tmp_path, monkeypatch, capsys):
    _tier(monkeypatch, 0)
    out = str(tmp_path)
    weeks = list(range(0, 34))  # 34 weeks × 3 reads = 102 records ≥ the floor
    _stage(out, weeks)
    submitted, cleaned = [], []

    def _submit(records, model_name, in_uri, out_uri, role_arn, job_name=None):
        submitted.append({"n": len(records), "in": in_uri, "out": out_uri, "model": model_name})
        return "arn:aws:bedrock:us-west-2:123:model-invocation-job/season42"

    ids = [f"wk{n}-{k}" for n in weeks for k in sr.RECHECK_KINDS]
    lines = []
    for rid in reversed(ids):  # Bedrock returns records unordered
        if rid == "wk5-episode":
            continue  # the job never answered this one → it must re-run on-demand
        if rid == "wk3-post":
            reply = _reply([_FINDING])
        elif rid == "wk7-dek":
            reply = _reply(stop="max_tokens")  # an incomplete batch read must stay a finding
        else:
            reply = _reply()
        lines.append(json.dumps({"recordId": rid, "modelInput": {}, "modelOutput": reply}))

    monkeypatch.setattr(bb, "submit_batch", _submit)
    monkeypatch.setattr(bb, "batch_role_arn", lambda: "arn:aws:iam::123:role/life-platform-bedrock-batch")
    monkeypatch.setattr(
        bb,
        "wait_for_batch",
        lambda arn, deadline, poll_interval=60.0: {"status": "Completed", "done": True, "succeeded": True, "message": ""},
    )
    monkeypatch.setattr(bb, "_read_output", lambda uri, key: bb.parse_output_jsonl("\n".join(lines)))
    monkeypatch.setattr(bb, "_cleanup", lambda i, o, log: cleaned.append(i))
    monkeypatch.setattr(bb, "_meter_batch_record", lambda usage, model_id: None)
    monkeypatch.setattr(bb, "_dev_cap_projected", lambda records, model_name: None)
    realtime_calls = []

    def realtime(model_input):
        realtime_calls.append(model_input)
        return _reply()

    rc = sr.recheck(out, weeks, realtime_fn=realtime)
    printed = capsys.readouterr().out
    assert rc == 1
    assert len(submitted) == 1 and submitted[0]["n"] == 102 and submitted[0]["model"] == story_writers.FACT_MODEL
    assert submitted[0]["in"].split("/", 3)[3].startswith(bb.BATCH_PREFIX)  # private staging, never generated/
    assert len(realtime_calls) == 1  # only the unanswered record
    assert cleaned  # staged prompts carry health data; they are deleted
    assert "mode=batch+realtime" in printed and "101 of 102 records answered by batch" in printed
    summary = _load(out, "recheck.json")
    assert summary["job_arn"].endswith("/season42") and summary["batch_records"] == 101 and summary["realtime_records"] == 1
    assert _load(out, "wk3_recheck.json")["findings"]["post"][0].startswith("post: fact: 'twelve calls'")
    assert _load(out, "wk7_recheck.json")["findings"]["dek"] == [
        "dek: fact-read: incomplete (stop_reason=max_tokens) — the installment is unverified"
    ]
    assert _load(out, "wk5_recheck.json")["batched"]["episode"] is False
    assert _load(out, "wk6_recheck.json")["batched"] == {"post": True, "dek": True, "episode": True}


def test_tier_three_never_submits_and_says_why(tmp_path, monkeypatch, capsys):
    _tier(monkeypatch, 3)
    out = str(tmp_path)
    weeks = list(range(0, 34))
    _stage(out, weeks)
    monkeypatch.setattr(bb, "submit_batch", lambda *a, **k: pytest.fail("submitted at tier 3"))
    sr.recheck(out, weeks, realtime_fn=lambda mi: _reply())
    assert "tier 3" in capsys.readouterr().out


def test_realtime_flag_never_submits(tmp_path, monkeypatch, capsys):
    _tier(monkeypatch, 0)
    out = str(tmp_path)
    weeks = list(range(0, 34))
    _stage(out, weeks)
    monkeypatch.setattr(bb, "submit_batch", lambda *a, **k: pytest.fail("submitted under --realtime"))
    assert sr.recheck(out, weeks, force_realtime=True, realtime_fn=lambda mi: _reply()) == 0
    assert "real-time requested by the caller" in capsys.readouterr().out


def test_cli_recheck_runs_the_sweep_on_demand(tmp_path, monkeypatch, capsys):
    from ai import bedrock_client

    out = str(tmp_path)
    _stage(out, [2])
    calls = []
    monkeypatch.setattr(bedrock_client, "invoke_with_retry", lambda body, model=None: calls.append(model) or _reply())
    assert sr.main(["--recheck", "2", "--out", out]) == 0
    assert calls == [story_writers.FACT_MODEL] * 3
    assert "ran on-demand" in capsys.readouterr().out


def test_nothing_staged_is_an_error_not_a_pass(tmp_path):
    assert sr.recheck(str(tmp_path), [0, 1], realtime_fn=lambda mi: pytest.fail("no read without a staged week")) == 2


def test_a_batched_read_asks_what_the_live_gate_asks():
    body = story_writers.fact_check_body("text", {"week": 1}, context={"a": 1})
    rec = bb.build_jsonl_record("wk1-post", body, story_writers.FACT_MODEL)
    expected = {k: v for k, v in body.items() if k != "model"}
    expected["anthropic_version"] = "bedrock-2023-05-31"
    assert rec["modelInput"] == expected


def test_fact_check_still_parses_through_fact_findings():
    sent = []
    got = story_writers.fact_check("text", {"week": 1}, invoke=lambda body, model: sent.append(body) or _reply([_FINDING]))
    assert got == ["fact: 'twelve calls' — sixteen were filed → sixteen calls"]
    assert sent[0] == story_writers.fact_check_body("text", {"week": 1})
    assert story_writers.fact_check("t", {}, invoke=lambda b, m: {"stop_reason": "end_turn", "content": []}) == [
        "fact-read: unparseable — the installment is unverified"
    ]


def test_a_read_that_raises_is_a_finding_and_the_paid_reads_are_still_written(tmp_path, capsys):
    out = str(tmp_path)
    _stage(out, [0, 1])
    calls = []

    def realtime(model_input):
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("ThrottlingException after retries")
        return _reply()

    rc = sr.recheck(out, [0, 1], realtime_fn=realtime)
    printed = capsys.readouterr().out
    assert rc == 1, "a failed read is never a clean pass"
    assert len(calls) == 6, "one failure does not stop the other reads"
    summary = _load(out, "recheck.json")
    assert summary["read_errors"] == 1 and summary["findings"] == 1
    wk0 = _load(out, "wk0_recheck.json")
    assert wk0["findings"]["dek"] == ["dek: read failed — RuntimeError: ThrottlingException after retries"]
    assert os.path.exists(os.path.join(out, "wk1_recheck.json"))
    assert "1 read(s) failed" in printed


def test_a_budget_stop_skips_the_remaining_reads_and_says_so(tmp_path):
    out = str(tmp_path)
    _stage(out, [0, 1])
    calls = []

    class BudgetExceeded(RuntimeError):
        pass

    class DevSessionBudgetExceeded(BudgetExceeded):
        pass

    def realtime(model_input):
        calls.append(1)
        if len(calls) == 3:
            raise DevSessionBudgetExceeded("dev cap $5 reached")
        return _reply()

    assert sr.recheck(out, [0, 1], realtime_fn=realtime) == 1
    assert len(calls) == 3, "no read is attempted after a budget stop"
    summary = _load(out, "recheck.json")
    assert summary["read_errors"] == 4 and summary["records"] == 6
    wk1 = _load(out, "wk1_recheck.json")
    assert all(
        v[0].startswith(f"{k}: read failed — not read — the sweep stopped after DevSessionBudgetExceeded")
        for k, v in wk1["findings"].items()
    )
