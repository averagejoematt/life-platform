"""tests/test_recall_publish_self_heal_2977.py — the #2977 class fix, pinned.

THE INCIDENT (third of its class: #2705 → #2858 → #2977). The 2026-08-21 chronicle
auto-publish sweep published the 2026-08-18 installment; the #1384 recall hook ran and
died on `bedrock:InvokeModel` AccessDenied — the chronicle-approve role still said
"no ai-keys, content was pre-generated" from before the hook existed. Fail-soft
swallowed it, the nightly qa-smoke FAILed `recall:corpus_freshness` for days into an
already-lit alarm, and the corpus kept answering "when did I feel like this before?"
from a hole. Each prior recurrence was closed by a hand-run backfill; this one closes
the class:

  ROOT CAUSE — the approve role's grants (bedrock, PutItem, generated/moments/) are
      asserted against the CDK source, so the docstring lie cannot silently return.
  SELF-HEAL — the nightly sensor that detects a published-but-missing installment now
      re-indexes it through the sanctioned path, mutation-proved by planting exactly
      the incident state (published row, empty corpus) and watching the row appear.
  LOUD — every FAILED return in recall_indexer logs INDEX_FAILED_TOKEN, and the CDK
      MetricFilter literal is its twin (the #2654 pattern), so the next AccessDenied
      pages instead of waiting for a nightly content check.
  HONEST — a heal that cannot fix keeps the check red; a heal that fixed reports a
      visible WARN, never a silent green (the publish path is still broken).

Hermetic — no AWS, no Bedrock, no network.

Run with:   python3 -m pytest tests/test_recall_publish_self_heal_2977.py -v
"""

import ast
import json
import os
import re
import sys

os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("EMAIL_RECIPIENT", "qa@example.com")
os.environ.setdefault("EMAIL_SENDER", "qa@example.com")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

from ai import recall_indexer as ri, semantic_recall as sr  # noqa: E402
from operational import recall_freshness_qa as rf  # noqa: E402
from operational.qa_check import CONTENT_TRUTH, Check  # noqa: E402

INDEXER_SRC = open(os.path.join(_REPO, "lambdas/ai/recall_indexer.py")).read()
ROLES_SRC = open(os.path.join(_REPO, "cdk/stacks/role_policies_email.py")).read()

# NB: the CDK side of this file is pinned against the WHOLE cdk/stacks tree (via
# tests/cdk_alarm_pins) and against the AST alarm census — never against monitoring_stack.py
# by name. These alarms were born in monitoring_stack.py and moved to the cohesive sibling
# monitoring_silence_alarms.py in this same PR (the #1665 guard's extract-don't-raise rule);
# a twin-pin that names one file survives such a move by going quietly dark on the file that
# no longer holds the thing — the "extract the RIGHT real source" defect (#2703).
#
# The AST alarm census (#795/#934, deploy/alarm_discovery.py) is the same discoverer the
# doc-sync gate and the count-vs-names parity test read. Asserting the two new alarm NAMES
# against it proves three things at once: the alarms exist, they are named as intended,
# and the census can RESOLVE them. That last one is not decoration — this PR's first pass
# wrote the loop as `for _id, _fn in ((...), (...))`, which the name resolver cannot bind
# through, so the census counted 2 alarms and 0 names and the parity gate reded.
sys.path.insert(0, os.path.join(_REPO, "deploy"))
import alarm_discovery  # noqa: E402
import cdk_alarm_pins  # noqa: E402

CHRONICLE_PK = "USER#matthew#SOURCE#chronicle"
# The incident's own dates: published 2026-08-18, plus an already-indexed neighbour.
MISSING, INDEXED_OK = "2026-08-18", "2026-08-16"
_NOW = "2026-08-23T00:00:00+00:00"


def _vec(text):
    return [float(len(text) % 7), 1.0, 0.0]


def _inst(date, *, status="published", body="a body", phase="experiment", cycle=14):
    return {
        "pk": CHRONICLE_PK,
        "sk": f"DATE#{date}",
        "date": date,
        "week_number": 1,
        "title": f"Installment {date}",
        "subtitle": "Of The Measured Life",
        "content_markdown": body,
        "status": status,
        "phase": phase,
        "cycle": cycle,
    }


def condition_values(cond):
    """Every literal string inside a boto3 KeyConditionExpression, recursively —
    dispatch on the actual key, never on repr() (see test_recall_freshness_qa)."""
    out = []
    try:
        values = cond.get_expression()["values"]
    except Exception:  # noqa: BLE001 — a plain value, not a condition
        return [cond] if isinstance(cond, str) else []
    for v in values:
        if isinstance(v, str):
            out.append(v)
        else:
            out.extend(condition_values(v))
    return out


class FakeTable:
    """One chronicle partition + one recall partition, dispatched on the query key —
    so a row the heal writes is VISIBLE to the corpus re-read, like the real table."""

    def __init__(self, installments=(), recall_rows=()):
        self.installments = list(installments)
        self.rows = {r["sk"]: r for r in recall_rows}
        self.puts = []

    def query(self, **kwargs):
        vals = condition_values(kwargs.get("KeyConditionExpression"))
        if sr.RECALL_PK in vals:
            return {"Items": list(self.rows.values())}
        return {"Items": list(self.installments)}

    def get_item(self, Key):  # noqa: N803 — boto3's parameter name
        item = self.rows.get(Key["sk"])
        return {"Item": item} if item else {}

    def put_item(self, Item):  # noqa: N803 — boto3's parameter name
        self.puts.append(Item)
        self.rows[Item["sk"]] = Item


def _real_indexer(table, pk, date):
    """The sanctioned path with only the Bedrock call stubbed out."""
    return ri.index_chronicle_installment(table, pk, date, embed=_vec, now=_NOW)


def _indexed_row(date, inst):
    """A corpus row as the real writer would have left it (built via the real path)."""
    t = FakeTable([inst])
    assert _real_indexer(t, CHRONICLE_PK, date) == ri.INDEXED
    return t.rows[sr.sk_for(sr.KIND_CHRONICLE, date)]


# ── SELF-HEAL: the mutation proof (the incident state, planted) ─────────────
def test_a_published_installment_missing_from_the_corpus_is_reindexed_by_the_sweep():
    """THE issue's acceptance box: plant exactly the live 2026-08-23 state — the
    2026-08-18 installment published, absent from the corpus — and the nightly check
    itself closes the hole through the sanctioned indexing path."""
    inst_ok = _inst(INDEXED_OK)
    table = FakeTable([inst_ok, _inst(MISSING)], recall_rows=[_indexed_row(INDEXED_OK, inst_ok)])

    (c,) = rf.checks(table, CHRONICLE_PK, Check, CONTENT_TRUTH, indexer=_real_indexer)

    row = table.rows.get(sr.sk_for(sr.KIND_CHRONICLE, MISSING))
    assert row is not None, "the missing installment must be re-indexed by the check itself"
    assert row["doc_date"] == MISSING
    assert (row["artifact_pk"], row["artifact_sk"]) == (CHRONICLE_PK, f"DATE#{MISSING}")
    # Repaired is reported as a visible WARN, never a silent green: the corpus is fixed
    # but the publish path that failed to write it is still broken.
    assert c.passed is None and not c.chronic
    assert "self-healed" in c.message and MISSING in c.message


def test_a_heal_that_cannot_fix_keeps_the_check_red_and_says_it_tried():
    """Self-heal must never green the sensor without the corpus actually changing —
    a role gap or Bedrock outage leaves the hole, and the check keeps naming it."""
    table = FakeTable([_inst(MISSING)])

    (c,) = rf.checks(table, CHRONICLE_PK, Check, CONTENT_TRUTH, indexer=lambda *a: ri.FAILED)

    assert c.passed is False
    assert MISSING in c.message
    assert "Self-heal attempted" in c.message and ri.FAILED in c.message


def test_a_complete_corpus_never_invokes_the_indexer():
    """No gap, no spend: the heal path must be unreachable when the corpus is whole."""
    inst = _inst(INDEXED_OK)
    table = FakeTable([inst], recall_rows=[_indexed_row(INDEXED_OK, inst)])

    def _never(*a):
        raise AssertionError("self-heal ran with nothing to heal")

    (c,) = rf.checks(table, CHRONICLE_PK, Check, CONTENT_TRUTH, indexer=_never)
    assert c.passed is True


def test_a_budget_paused_tier_does_not_heal(monkeypatch):
    """Band 2 (ADR-125): the corpus is SUPPOSED to stop advancing — a paused tier
    reports ⏸ and spends nothing, exactly as before #2977."""
    import ai.budget_guard as bg

    monkeypatch.setattr(bg, "allow", lambda feature: False)

    def _never(*a):
        raise AssertionError("self-heal ran at a paused tier")

    (c,) = rf.checks(FakeTable([_inst(MISSING)]), CHRONICLE_PK, Check, CONTENT_TRUTH, indexer=_never)
    assert c.paused is True


def test_the_heal_is_spend_bounded():
    """One nightly run pays for at most _MAX_HEAL embeds, and the check still names
    the backlog it left."""
    calls = []

    def _counting(table, pk, date):
        calls.append(date)
        return ri.FAILED

    dates = [f"2026-0{m}-01" for m in range(1, 10)]
    rf.self_heal(FakeTable(), CHRONICLE_PK, dates, indexer=_counting)
    assert len(calls) == rf._MAX_HEAL


# ── LOUD: the token and its CDK twin (#2654 pattern) ────────────────────────
def test_every_failed_return_site_logs_the_token():
    """Fail-soft stays; silent does not. Each `return FAILED` in recall_indexer must
    sit under a logger.error that carries INDEX_FAILED_TOKEN — counted from source so
    a new failure site cannot ship quiet."""
    failed_returns = len(re.findall(r"return FAILED\b", INDEXER_SRC))
    token_logs = len(re.findall(r"logger\.error\([^)]*INDEX_FAILED_TOKEN", INDEXER_SRC))
    assert failed_returns >= 3, "the three known failure sites went missing — did FAILED get renamed?"
    assert token_logs == failed_returns, (
        f"{failed_returns} `return FAILED` site(s) but {token_logs} token log(s) — a FAILED return that does not log "
        "INDEX_FAILED_TOKEN is invisible to the recall-index-failed alarms (#2977)"
    )


def test_metric_filter_token_twin():
    """The CDK filter token and the lambda constant may not drift apart (#2654 pattern).

    Both directions bite: change the CDK token and INDEX_FAILED_TOKEN leaves the set;
    change the lambda constant and it never entered it. Either way the alarm would be
    watching a string nothing logs — the fail-soft path silent again, which is the whole
    incident."""
    tokens = cdk_alarm_pins.filter_tokens_for("recall-index-failed")
    assert tokens, "no CDK stack wires a recall-index-failed-* alarm to a literal filter token"
    assert tokens == {ri.INDEX_FAILED_TOKEN}, f"CDK filter token(s) {sorted(tokens)} != lambda INDEX_FAILED_TOKEN {ri.INDEX_FAILED_TOKEN!r}"


# The Lambda handlers that live in qa/repair rather than on a publish path. Their recall
# calls CAN log the token, but a metric filter there would be redundant noise, not signal:
# a self-heal that fails already keeps `recall:corpus_freshness` FAILing into the
# qa-smoke-failures alarm, and the check's own message names each attempt's status.
# Named here with a reason rather than left to fall out of the derivation by accident.
_NON_PUBLISH_RECALL_CALLERS = {
    "life-platform-qa-smoke": "the #2977 self-heal — its failures surface as the check's own FAIL + qa-smoke-failures",
}


def _deployed_lambdas_calling_the_recall_hook():
    """DERIVED, never hand-listed: {function_name} for every deployed Lambda whose own
    handler source calls `index_chronicle_installment`.

    Registry = ci/lambda_map.json (source file → deployed function name); predicate = the
    actual call site. The CDK cannot use this derivation (deploy/alarm_discovery resolves
    alarm names statically, so a non-literal loop would count alarms it cannot name), so
    the coverage claim is derived HERE instead — which is the better half anyway: a third
    publish path that grows a recall hook reds this test on the PR that adds it.
    """
    entries = json.loads(open(os.path.join(_REPO, "ci", "lambda_map.json"), encoding="utf-8").read())["lambdas"]
    out = {}
    for src_rel, meta in entries.items():
        path = os.path.join(_REPO, src_rel)
        if not os.path.exists(path):
            continue
        if "index_chronicle_installment" in open(path, encoding="utf-8").read():
            out[meta["function"]] = src_rel
    return out


def test_every_publish_path_that_indexes_has_its_own_alarm():
    """The approve sweep (the incident's path) AND direct-publish each get their OWN
    named alarm — a fix scoped to one log group would leave the other publish site dark.

    The covered SET is derived from the lambda registry, not typed here, so this cannot
    go stale the way the grant it is guarding did (#2977's root cause was exactly a
    hand-maintained list that stopped following the code). Asserted against the AST alarm
    census, which additionally proves the names are statically RESOLVABLE — the first pass
    of this PR created 2 alarms the census could count but not name."""
    callers = _deployed_lambdas_calling_the_recall_hook()
    assert callers, "no deployed Lambda appears to call the recall hook — the derivation broke, not the platform"
    names = alarm_discovery._auto_discover_alarm_names()
    assert names is not None, "alarm-name discovery bailed — a stack file failed to parse"

    expected = {fn for fn in callers if fn not in _NON_PUBLISH_RECALL_CALLERS}
    assert expected >= {
        "chronicle-approve",
        "wednesday-chronicle",
    }, f"the two known publish paths went missing from the derivation: {callers}"
    missing = sorted(fn for fn in expected if f"recall-index-failed-{fn}" not in names)
    assert not missing, (
        f"deployed Lambda(s) call the publish-time recall hook with no recall-index-failed alarm: {missing}\n"
        "Add one in cdk/stacks/monitoring_silence_alarms.py, or classify it in "
        "_NON_PUBLISH_RECALL_CALLERS with a reason (#2977)."
    )


def test_the_alarm_census_still_agrees_with_itself():
    """#3061's parity invariant, re-asserted at this PR's own seam: one canonical NAME per
    counted alarm. The recall alarms are created in a loop inside an extracted sibling
    module — the exact two shapes (loop binding, cross-file helper) where the counter and
    the name resolver have historically disagreed."""
    count = alarm_discovery._auto_discover_alarm_count()
    names = alarm_discovery._auto_discover_alarm_names()
    assert count is not None and names is not None
    assert len(names) == count, f"alarm name set ({len(names)}) diverged from the count ({count})"


def test_every_extracted_alarm_sibling_is_actually_wired():
    """A sibling module's alarms only exist if a Stack CALLS it. Guard the SET.

    Found by mutation while writing this PR, and it is a genuine hole the extraction
    pattern opens: comment out `add_silence_alarms(self, digest)` in monitoring_stack.py
    and every token twin-pin above still passes (they read the sibling's source) AND the
    AST alarm census still counts 4 (it walks the sibling's body, not the call graph) —
    so four alarms would silently stop being synthesized while every gate stayed green.
    That is the same defect class as the alarms this PR is about: a thing that fails by
    not existing, invisibly.

    Scoped to the SET rather than to `add_silence_alarms` alone (there are five of these
    siblings today and the shape is the sanctioned answer to the #1665 size guard, so
    there will be more): every top-level `add_*` function defined in a non-`*_stack.py`
    module under cdk/stacks must be called from at least one `*_stack.py`.
    """
    stacks_dir = os.path.join(_REPO, "cdk", "stacks")
    files = [f for f in sorted(os.listdir(stacks_dir)) if f.endswith(".py")]
    sibling_adders, stack_calls = {}, set()
    for fname in files:
        tree = ast.parse(open(os.path.join(stacks_dir, fname), encoding="utf-8").read(), filename=fname)
        if not fname.endswith("_stack.py"):
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("add_"):
                    sibling_adders[node.name] = fname
        else:
            stack_calls |= {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}

    assert "add_silence_alarms" in sibling_adders, "the #2977 silence-alarm sibling vanished"
    unwired = {name: mod for name, mod in sibling_adders.items() if name not in stack_calls}
    assert not unwired, f"defined in a cdk/stacks sibling but never called from any *_stack.py: {unwired}"


# ── ROOT CAUSE: the approve role's grants, pinned against the CDK source ────
def _approve_role_src():
    body = ROLES_SRC.split("def email_chronicle_approve", 1)[1]
    return body.split("\ndef ", 1)[0]


def test_the_approve_role_can_embed_and_write_the_corpus():
    """The incident: three publish-time side-effects whose grants never followed the
    code. Asserted on the role function's own source so the split-file refactor class
    (#2604/#2611) cannot silently drop them again."""
    src = _approve_role_src()
    assert "_bedrock_statement()" in src, "recall hook embeds via Titan — bedrock:InvokeModel grant (#2977)"
    assert "dynamodb:PutItem" in src, "recall row + recap commit are put_item writes (#2977)"
    assert "generated/moments/" in src, "the #405 share kit lands under generated/moments/ (#2977)"
    assert "budget-tier" in src, "budget_guard must be able to read the tier or it fails open (#2977)"


def test_the_stale_no_ai_claim_is_gone():
    assert "No ai-keys" not in _approve_role_src()
