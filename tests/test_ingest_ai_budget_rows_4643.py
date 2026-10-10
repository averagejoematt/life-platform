"""tests/test_ingest_ai_budget_rows_4643.py — #4643 box 3: every ingest-path AI caller has a
budget-ledger row with a cutoff tier, and every enrichment function writes a health record.

THE SET (the issue's own `## Set`, re-derived here rather than hand-listed). The ingest path is
every module in ``lambdas/ingestion/`` plus every ``lambdas/`` module one of them imports
directly. A member is an AI CALLER when its source reaches Bedrock itself — a call to
``bedrock_client.invoke``/``invoke_with_retry``, ``retry_utils.call_anthropic*`` or
``structured_json.call_json`` — rather than only importing a module that does. The transport
modules (the chokepoint and its wrappers) are excluded by name: they spend on a caller's behalf
and the caller owns the gate.

Members on 2026-10-10 (6): journal_enrichment_lambda, social_enrichment_lambda,
broadcast_sensitivity_gate, training_notes_llm (the four #4643 named — none had a row), and
conversation_enrichment + coach_diary_reaction (already gated before #4643).

For each caller the contract is three facts, all checked by AST:
  1. it declares a module-level ``*BUDGET_FEATURE`` string constant;
  2. every such feature is a key of ``budget_guard._FEATURE_CUTOFF`` (a cutoff tier) AND of
     ``scripts/ai_budget_ledger.LEDGER`` (a budget row);
  3. it actually calls ``allow(...)`` — a declared feature nothing gates on is decoration.

A NEW ingest-path module that reaches Bedrock with none of these reds
``test_every_ingest_path_ai_caller_has_a_cutoff_and_a_ledger_row`` — the synthetic control
below proves the detector fires on exactly that shape.

The health half: each of the three enrichment functions writes ``INGEST_HEALTH#<HEALTH_SOURCE>``
through ``record_ingest_health`` on every run — success, a failed entry, and a raised handler —
pinned behaviourally with a recording stub.
"""

from __future__ import annotations

import ast
import importlib
import json
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
LAMBDAS = REPO / "lambdas"
sys.path.insert(0, str(LAMBDAS))
sys.path.insert(0, str(REPO / "scripts"))

import ai_budget_ledger  # noqa: E402
from ai import budget_guard  # noqa: E402

INGESTION_DIR = LAMBDAS / "ingestion"

# The spend path itself — a caller's Bedrock call routes THROUGH these, so the caller owns the
# gate. Adding a module here is a claim that it never decides to spend on its own.
TRANSPORT_MODULES = frozenset(
    {
        "ai.bedrock_client",
        "ai.budget_guard",
        "ai.structured_json",
        "ai.ai_calls",
        "ai.ai_transport",
        "common.retry_utils",
    }
)

_SPEND_CALLS = frozenset({"invoke", "invoke_with_retry", "call_anthropic", "call_anthropic_raw", "call_json"})


def _module_path(dotted: str) -> pathlib.Path | None:
    p = LAMBDAS / (dotted.replace(".", "/") + ".py")
    return p if p.is_file() else None


def _direct_imports(tree: ast.AST) -> set[str]:
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            if _module_path(node.module):
                out.add(node.module)
            for alias in node.names:
                if _module_path(f"{node.module}.{alias.name}"):
                    out.add(f"{node.module}.{alias.name}")
        elif isinstance(node, ast.Import):
            out.update(a.name for a in node.names if _module_path(a.name))
    return out


def _reaches_bedrock(tree: ast.AST) -> bool:
    """True when the module itself calls a spend function (bare or attribute form)."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            name = fn.id if isinstance(fn, ast.Name) else fn.attr if isinstance(fn, ast.Attribute) else None
            if name not in _SPEND_CALLS:
                continue
            # `bedrock_client.invoke(...)`, or a bare `invoke(...)` imported from the chokepoint.
            if name != "invoke" or isinstance(fn, ast.Attribute) and getattr(fn.value, "id", "") == "bedrock_client":
                return True
            if name == "invoke" and isinstance(fn, ast.Name) and _imports_name_from(tree, "ai.bedrock_client", "invoke"):
                return True
    return False


def _imports_name_from(tree: ast.AST, module: str, name: str) -> bool:
    return any(isinstance(n, ast.ImportFrom) and n.module == module and any(a.name == name for a in n.names) for n in ast.walk(tree))


def _declared_features(tree: ast.Module) -> list[str]:
    feats = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id.lstrip("_").endswith("BUDGET_FEATURE"):
                    feats.append(node.value.value)
    return feats


def _calls_allow(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            name = fn.id if isinstance(fn, ast.Name) else fn.attr if isinstance(fn, ast.Attribute) else ""
            if name == "allow" or name.endswith("_allow"):
                return True
    return False


def ingest_path_modules(ingestion_dir: pathlib.Path = INGESTION_DIR) -> dict[str, pathlib.Path]:
    """lambdas/ingestion/*.py plus every lambdas/ module they import directly."""
    mods: dict[str, pathlib.Path] = {}
    for p in sorted(ingestion_dir.glob("*.py")):
        mods[f"ingestion.{p.stem}"] = p
    for p in list(mods.values()):
        for dotted in _direct_imports(ast.parse(p.read_text(encoding="utf-8"))):
            mods.setdefault(dotted, _module_path(dotted))
    return mods


def ai_callers(mods: dict[str, pathlib.Path]) -> dict[str, pathlib.Path]:
    return {
        m: p
        for m, p in mods.items()
        if m not in TRANSPORT_MODULES and p is not None and _reaches_bedrock(ast.parse(p.read_text(encoding="utf-8")))
    }


def contract_failures(callers: dict[str, pathlib.Path], cutoff: dict, ledger: dict) -> list[str]:
    failures = []
    for mod, path in sorted(callers.items()):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        feats = _declared_features(tree)
        if not feats:
            failures.append(f"{mod}: reaches Bedrock but declares no module-level *BUDGET_FEATURE constant")
            continue
        for f in feats:
            if f not in cutoff:
                failures.append(f"{mod}: feature {f!r} has no cutoff tier in budget_guard._FEATURE_CUTOFF")
            if f not in ledger:
                failures.append(f"{mod}: feature {f!r} has no row in scripts/ai_budget_ledger.py LEDGER")
        if not _calls_allow(tree):
            failures.append(f"{mod}: declares {feats} but never calls budget_guard.allow — the row would gate nothing")
    return failures


# ── the gate ────────────────────────────────────────────────────────────────────


def test_the_ingest_path_ai_caller_set_is_what_the_issue_named():
    """Anchor the derivation: the four #4643 named are found, plus the two already-gated
    members. If this list grows, the contract test below is what decides whether the new
    member is covered — this assertion only proves the detector is looking at the real tree."""
    found = set(ai_callers(ingest_path_modules()))
    named = {
        "ingestion.journal_enrichment_lambda",
        "ingestion.social_enrichment_lambda",
        "privacy.broadcast_sensitivity_gate",
        "training.training_notes_llm",
    }
    assert named <= found, f"the derivation lost a #4643 member: {sorted(named - found)}"
    assert {"ai.conversation_enrichment", "coach.coach_diary_reaction"} <= found


def test_every_ingest_path_ai_caller_has_a_cutoff_and_a_ledger_row():
    failures = contract_failures(ai_callers(ingest_path_modules()), budget_guard._FEATURE_CUTOFF, ai_budget_ledger.LEDGER)
    assert not failures, "ingest-path AI callers without a budget row (#4643):\n  " + "\n  ".join(failures)


def test_a_new_ungated_ingest_ai_caller_is_flagged(tmp_path):
    """Synthetic control: a new ingestion module that calls Bedrock with no feature, and one
    whose feature is missing from the ladder, are both named."""
    ing = tmp_path / "ingestion"
    ing.mkdir()
    (ing / "new_source_lambda.py").write_text(
        "from ai import bedrock_client\n\ndef handler(e, c):\n    return bedrock_client.invoke({}, model_name='haiku')\n",
        encoding="utf-8",
    )
    (ing / "half_gated_lambda.py").write_text(
        "from ai import budget_guard\nfrom common.retry_utils import call_anthropic_raw\n"
        "BUDGET_FEATURE = 'brand_new_feature'\n\n"
        "def handler(e, c):\n    if budget_guard.allow(BUDGET_FEATURE):\n        call_anthropic_raw({})\n",
        encoding="utf-8",
    )
    callers = ai_callers({f"ingestion.{p.stem}": p for p in ing.glob("*.py")})
    assert set(callers) == {"ingestion.new_source_lambda", "ingestion.half_gated_lambda"}
    failures = contract_failures(callers, budget_guard._FEATURE_CUTOFF, ai_budget_ledger.LEDGER)
    joined = "\n".join(failures)
    assert "new_source_lambda: reaches Bedrock but declares no module-level *BUDGET_FEATURE" in joined
    assert "'brand_new_feature' has no cutoff tier" in joined
    assert "'brand_new_feature' has no row" in joined


def test_a_declared_feature_nothing_gates_on_is_flagged(tmp_path):
    p = tmp_path / "decorative_lambda.py"
    p.write_text(
        "from common.retry_utils import call_anthropic_raw\nBUDGET_FEATURE = 'journal_enrichment'\n\n"
        "def handler(e, c):\n    call_anthropic_raw({})\n",
        encoding="utf-8",
    )
    failures = contract_failures({"ingestion.decorative_lambda": p}, budget_guard._FEATURE_CUTOFF, ai_budget_ledger.LEDGER)
    assert failures and "never calls budget_guard.allow" in failures[0]


def test_ledger_stays_sound_with_the_ingest_rows():
    assert ai_budget_ledger.validate() == []


# ── health records: every enrichment function writes one on every run ───────────


class _Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, table, source, logger, *, attempted, succeeded, error_class="none"):
        self.calls.append({"source": source, "attempted": attempted, "succeeded": succeeded, "error_class": error_class})


class _FakeTable:
    def __init__(self, items=None):
        self.items = items or []
        self.updates = []

    def query(self, **kw):
        return {"Items": list(self.items)}

    def update_item(self, **kw):
        self.updates.append(kw)

    def get_item(self, **kw):
        return {}

    def put_item(self, **kw):
        pass


def _load(modname, monkeypatch, table):
    mod = importlib.import_module(modname)
    rec = _Recorder()
    monkeypatch.setattr(mod, "record_ingest_health", rec)
    monkeypatch.setattr(mod, "_INGEST_HEALTH_AVAILABLE", True)
    monkeypatch.setattr(mod, "table", table)
    return mod, rec


ENRICHMENT_MODULES = (
    ("ingestion.enrichment_lambda", "activity_enrichment"),
    ("ingestion.journal_enrichment_lambda", "journal_enrichment"),
    ("ingestion.social_enrichment_lambda", "social_enrichment"),
)


def test_every_enrichment_function_names_its_health_source():
    for modname, source in ENRICHMENT_MODULES:
        mod = importlib.import_module(modname)
        assert mod.HEALTH_SOURCE == source, modname


def test_activity_enrichment_records_health_on_success_and_on_a_raise(monkeypatch):
    mod, rec = _load("ingestion.enrichment_lambda", monkeypatch, _FakeTable())
    mod.lambda_handler({"start_date": "2026-10-01", "end_date": "2026-10-01"}, None)
    assert rec.calls == [{"source": "activity_enrichment", "attempted": True, "succeeded": True, "error_class": "none"}]

    def boom(*a, **k):
        raise TimeoutError("connection timed out")

    monkeypatch.setattr(mod, "enrich_date_range", boom)
    with pytest.raises(TimeoutError):
        mod.lambda_handler({}, None)
    assert rec.calls[-1] == {"source": "activity_enrichment", "attempted": True, "succeeded": False, "error_class": "transport"}


def test_activity_enrichment_a_malformed_row_fails_the_run(monkeypatch):
    mod, rec = _load("ingestion.enrichment_lambda", monkeypatch, _FakeTable())
    monkeypatch.setattr(mod, "enrich_date_range", lambda s, e: {"enriched": 0, "skipped": 0, "malformed": 1, "days_processed": 1})
    mod.lambda_handler({}, None)
    assert rec.calls == [{"source": "activity_enrichment", "attempted": True, "succeeded": False, "error_class": "parse"}]


_ENTRY = {
    "pk": "USER#matthew#SOURCE#notion",
    "sk": "DATE#2026-10-01#journal#morning",
    "date": "2026-10-01",
    "template": "Morning",
    "raw_text": " ".join(["word"] * 40),
}


def _journal(monkeypatch, *, allowed=True, haiku=None):
    mod, rec = _load("ingestion.journal_enrichment_lambda", monkeypatch, _FakeTable([dict(_ENTRY)]))
    monkeypatch.setattr(mod, "_ai_allowed", lambda: allowed)
    monkeypatch.setattr(mod, "call_haiku", haiku or (lambda *a: {"mood_score": 3, "themes": ["x"]}))
    monkeypatch.setattr(mod, "maybe_react_to_diary", lambda item, enr: {"reacted": False})
    monkeypatch.setattr(mod, "_write_flourishing_rows", lambda entries: 0)
    monkeypatch.setattr(mod, "_run_conversational", lambda *a: {})
    monkeypatch.setattr(mod, "_refresh_horizons_calibration", lambda: {})
    return mod, rec


def test_journal_enrichment_records_success(monkeypatch):
    mod, rec = _journal(monkeypatch)
    body = json.loads(mod.lambda_handler({"date": "2026-10-01"}, None)["body"])
    assert body["enriched"] == 1 and body["errors"] == 0
    assert rec.calls == [{"source": "journal_enrichment", "attempted": True, "succeeded": True, "error_class": "none"}]


def test_journal_enrichment_a_failed_entry_fails_the_run_with_its_class(monkeypatch):
    def throttled(*a):
        raise RuntimeError("ThrottlingException: rate limit")

    mod, rec = _journal(monkeypatch, haiku=throttled)
    body = json.loads(mod.lambda_handler({"date": "2026-10-01"}, None)["body"])
    assert body["errors"] == 1
    assert rec.calls == [{"source": "journal_enrichment", "attempted": True, "succeeded": False, "error_class": "throttle"}]


def test_journal_enrichment_budget_pause_skips_the_model_and_is_a_healthy_run(monkeypatch):
    def must_not_run(*a):
        raise AssertionError("the model was called while the tier paused journal_enrichment")

    mod, rec = _journal(monkeypatch, allowed=False, haiku=must_not_run)
    body = json.loads(mod.lambda_handler({"date": "2026-10-01"}, None)["body"])
    assert body["paused_by_budget"] == 1 and body["enriched"] == 0 and body["errors"] == 0
    assert rec.calls == [{"source": "journal_enrichment", "attempted": True, "succeeded": True, "error_class": "none"}]


def test_journal_enrichment_records_a_raised_handler(monkeypatch):
    mod, rec = _journal(monkeypatch)

    def boom(*a, **k):
        raise PermissionError("AccessDeniedException: 403 forbidden")

    monkeypatch.setattr(mod, "query_journal_entries", boom)
    with pytest.raises(PermissionError):
        mod.lambda_handler({"date": "2026-10-01"}, None)
    assert rec.calls == [{"source": "journal_enrichment", "attempted": True, "succeeded": False, "error_class": "auth"}]


_POST = {
    "pk": "USER#matthew#SOURCE#youtube",
    "sk": "DATE#2026-10-01#vid1",
    "post_id": "vid1",
    "date": "2026-10-01",
    "channel": "youtube",
    "origin": "human",
    "title": "Long run this morning felt strong after a full night of sleep and a good breakfast",
}


def _social(monkeypatch, *, allowed=True, haiku=None):
    mod, rec = _load("ingestion.social_enrichment_lambda", monkeypatch, _FakeTable([dict(_POST)]))
    monkeypatch.setattr(mod, "_ai_allowed", lambda: allowed)
    monkeypatch.setattr(mod, "call_haiku", haiku or (lambda *a: {"themes": ["running"], "sentiment": "positive"}))
    monkeypatch.setattr(mod, "maybe_react_to_post", lambda item, enrichment=None: {"reacted": False})
    return mod, rec


def test_social_enrichment_records_success(monkeypatch):
    mod, rec = _social(monkeypatch)
    body = json.loads(mod.lambda_handler({"date": "2026-10-01", "channels": ["youtube"]}, None)["body"])
    assert body["enriched"] == 1, body
    assert rec.calls == [{"source": "social_enrichment", "attempted": True, "succeeded": True, "error_class": "none"}]


def test_social_enrichment_a_failed_post_fails_the_run(monkeypatch):
    mod, rec = _social(monkeypatch, haiku=lambda *a: None)
    body = json.loads(mod.lambda_handler({"date": "2026-10-01", "channels": ["youtube"]}, None)["body"])
    assert body["errors"] == 1
    assert rec.calls == [{"source": "social_enrichment", "attempted": True, "succeeded": False, "error_class": "parse"}]


def test_social_enrichment_budget_pause_skips_the_model_and_is_a_healthy_run(monkeypatch):
    def must_not_run(*a):
        raise AssertionError("the model was called while the tier paused social_enrichment")

    mod, rec = _social(monkeypatch, allowed=False, haiku=must_not_run)
    body = json.loads(mod.lambda_handler({"date": "2026-10-01", "channels": ["youtube"]}, None)["body"])
    assert body["paused_by_budget"] == 1 and body["enriched"] == 0
    assert rec.calls == [{"source": "social_enrichment", "attempted": True, "succeeded": True, "error_class": "none"}]


def test_social_enrichment_healthcheck_probe_writes_no_record(monkeypatch):
    mod, rec = _social(monkeypatch)
    mod.lambda_handler({"healthcheck": True}, None)
    assert rec.calls == []


# ── training notes: the tail is gated before the cap and before any spend ───────


def test_training_notes_budget_pause_degrades_before_any_spend(monkeypatch):
    from training import training_notes as tn, training_notes_llm as tnl

    monkeypatch.setattr(tnl, "_ai_allowed", lambda: False)
    monkeypatch.setattr(tnl, "cache_get", lambda table, h: None)

    def no_spend(*a, **k):
        raise AssertionError("a paused tier reached the cap counter or the model")

    monkeypatch.setattr(tnl, "monthly_calls", no_spend)
    monkeypatch.setattr(tnl, "_haiku_call", no_spend)
    rec = tn.extract_signals("Level 9 for 20 then level 6 for 10, felt tired today", llm_fn=tnl.make_llm_fn(object(), lane="live"))
    assert rec["degraded"] is True
    assert rec["degraded_reason"].startswith("budget_paused:")
