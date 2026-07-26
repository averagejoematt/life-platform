"""tests/test_diary_reaction_trigger_1756.py — the diary-reaction PRODUCTION TRIGGER (#1756).

#1574 shipped the producer, the fail-closed consent gate, `/api/diary_reactions` and the
lab-notes render — but nothing ever CALLED the producer, so the endpoint rendered nothing.
This file pins the wiring that closes that loop, at the journal-enrichment boundary
(Option A: inline in the record-enrichment pipeline, no second pipeline, no new Lambda).

What is proven here, all offline (no Bedrock, no DynamoDB, no SSM):

  AC1  a consented Video-Diary entry, on enrichment, produces + stores a reaction — and
       the reaction is routed on the themes THIS pass just extracted, not the stale record
  AC2  an unmarked/private entry never reaches a generation call from the enrichment loop
  AC3  the trigger is fail-OPEN — a reaction blow-up never fails the enrichment run
  AC5  budget tiering is intact end-to-end (a paused tier stores nothing)

The IAM contract the trigger depends on is pinned in test_role_policies_diary_trigger below
(budget-tier + experiment-cycle SSM read, coach-quality-gate invoke) — without those grants
budget_guard fails OPEN to tier 0 and the tier-2 pause is silently defeated.
"""

import os
import sys
import types
from unittest.mock import MagicMock

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "coach"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "ingestion"))

import coach_diary_reaction as cdr  # noqa: E402
import journal_enrichment_lambda as jel  # noqa: E402

_PAGE = "1f2e3d4c-5b6a-7980-1234-abcdef012345"
_UID = _PAGE.replace("-", "")[-12:]
_SECRET_BODY = "Relapsed after the fight with Dana. Smoked, then porn until 3am. The debt terrifies me."


def _item(**over):
    """A landed Video-Diary journal record, pre-enrichment (notion_lambda shape)."""
    base = {
        "pk": "USER#matthew#SOURCE#notion",
        "sk": f"DATE#2026-07-25#journal#video_diary#{_UID}",
        "date": "2026-07-25",
        "template": "Video Diary",
        "channel": "video_diary",
        "notion_page_id": _PAGE,
        "raw_text": _SECRET_BODY,
        "public_reaction_consent": "allude",
    }
    base.update(over)
    return base


# This pass's Haiku output — deliberately body/health-flavoured so the routing
# assertion can only pass if the FRESH enrichment (not the stale record) is used.
_ENRICHMENT = {
    "sentiment": "negative",
    "themes": ["training", "sleep quality"],
    "mood_score": 2,
}


# ── the merged view: the trigger routes on THIS pass's enrichment ────────────────


def test_entry_with_enrichment_merges_the_fresh_haiku_fields():
    """apply_enrichment writes with update_item and does not mutate the item, so the
    trigger must be handed the merged view or it routes on a stale/absent theme."""
    view = jel.entry_with_enrichment(_item(), _ENRICHMENT)
    assert view["enriched_themes"] == ["training", "sleep quality"]
    assert view["enriched_sentiment"] == "negative"
    assert view["raw_text"] == _SECRET_BODY  # the record's own fields survive
    assert "enriched_themes" not in _item()  # the source item is untouched


def test_routing_uses_the_fresh_enrichment():
    view = jel.entry_with_enrichment(_item(), _ENRICHMENT)
    assert cdr.route_coach(view) == "physical_coach"  # body/health themes → physical
    assert cdr.route_coach(_item()) == "mind_coach"  # the stale record would route Mind


# ── AC1: a consented diary entry produces + stores a reaction ────────────────────


def _patched_trigger(monkeypatch, result):
    """Replace the producer's maybe_react with a recorder, imported the way the
    enrichment lambda imports it (from the `coach` package inside the bundle)."""
    calls = []

    def _fake(entry, **kwargs):
        calls.append((entry, kwargs))
        if isinstance(result, Exception):
            raise result
        return result

    mod = types.ModuleType("coach.coach_diary_reaction")
    mod.maybe_react = _fake
    monkeypatch.setitem(sys.modules, "coach.coach_diary_reaction", mod)
    return calls


def test_trigger_is_called_with_the_enriched_view_and_the_shared_table(monkeypatch):
    calls = _patched_trigger(monkeypatch, {"reacted": True, "sk": f"DATE#2026-07-25#video_diary#{_UID}", "coach_id": "physical_coach"})
    out = jel.maybe_react_to_diary(_item(), _ENRICHMENT)
    assert out["reacted"] is True
    ((entry, kwargs),) = calls
    assert entry["enriched_themes"] == ["training", "sleep quality"]
    assert entry["channel"] == "video_diary"
    assert kwargs["table_"] is jel.table  # one table handle, the enrichment lambda's own


def test_end_to_end_consented_entry_stores_a_reaction():
    """No patching of the producer: the real maybe_react runs with injected AI/gate/
    budget callables, and a row lands under the diary_reactions partition."""
    table = MagicMock()
    table.get_item.return_value = {}
    out = cdr.maybe_react(
        jel.entry_with_enrichment(_item(), _ENRICHMENT),
        table_=table,
        lambda_client=MagicMock(),
        budget_allow=lambda f: True,
        generate_fn=lambda s, u: "You pressed record on a hard night. That is the work.",
        ground_fn=lambda label, draft, allow: draft,
        quality_gate_fn=lambda _lc, _cid, text, _b: (text, {"passed": True}),
    )
    assert out["reacted"] is True
    item = table.put_item.call_args.kwargs["Item"]
    assert item["pk"] == "USER#matthew#SOURCE#diary_reactions"
    assert item["sk"] == f"DATE#2026-07-25#video_diary#{_UID}"
    assert item["coach_id"] == "physical_coach"
    assert item["tier"] == "allude" and "quote" not in item
    # the private body never rides along into the stored (publicly served) row
    blob = " ".join(str(v) for v in item.values()).lower()
    for canary in ("dana", "smoked", "porn", "3am", "debt", "relapsed"):
        assert canary not in blob


# ── AC2 / AC5: nothing is spent on an unmarked entry or a paused tier ────────────


def test_unmarked_entry_costs_nothing_through_the_enrichment_path():
    gen = MagicMock()
    table = MagicMock()
    table.get_item.return_value = {}
    out = cdr.maybe_react(
        jel.entry_with_enrichment(_item(public_reaction_consent=None), _ENRICHMENT),
        table_=table,
        lambda_client=MagicMock(),
        budget_allow=lambda f: True,
        generate_fn=gen,
        ground_fn=lambda label, draft, allow: draft,
        quality_gate_fn=lambda _lc, _cid, t, _b: (t, {}),
    )
    assert out == {"reacted": False, "reason": "private"}
    gen.assert_not_called()
    table.get_item.assert_not_called()
    table.put_item.assert_not_called()


def test_budget_pause_is_honoured_through_the_enrichment_path():
    gen = MagicMock()
    table = MagicMock()
    table.get_item.return_value = {}
    out = cdr.maybe_react(
        jel.entry_with_enrichment(_item(), _ENRICHMENT),
        table_=table,
        lambda_client=MagicMock(),
        budget_allow=lambda f: f != cdr.BUDGET_FEATURE,  # exactly this feature paused
        generate_fn=gen,
        ground_fn=lambda label, draft, allow: draft,
        quality_gate_fn=lambda _lc, _cid, t, _b: (t, {}),
    )
    assert out == {"reacted": False, "reason": "no_reaction"}
    gen.assert_not_called()
    table.put_item.assert_not_called()


# ── AC3: fail-open — the enrichment run survives any reaction failure ────────────


def test_enrichment_survives_a_trigger_explosion(monkeypatch):
    _patched_trigger(monkeypatch, RuntimeError("bedrock on fire"))
    out = jel.maybe_react_to_diary(_item(), _ENRICHMENT)  # must NOT raise
    assert out["reacted"] is False and out["reason"] == "error"


def test_enrichment_survives_a_missing_producer_module(monkeypatch):
    """Belt-and-braces: even an ImportError (bundle path surprise) is swallowed."""
    monkeypatch.setitem(sys.modules, "coach.coach_diary_reaction", None)
    out = jel.maybe_react_to_diary(_item(), _ENRICHMENT)
    assert out["reacted"] is False and out["reason"] == "error"


# ── the trigger is actually wired into the per-entry loop ───────────────────────


def test_handler_loop_calls_the_trigger_after_a_successful_enrichment():
    src = open(os.path.join(_REPO, "lambdas", "ingestion", "journal_enrichment_lambda.py"), encoding="utf-8").read()
    body = src.split("def lambda_handler", 1)[1]
    assert "maybe_react_to_diary(item, enrichment)" in body, "the trigger must be called from the per-entry loop"
    assert '"diary_reactions": diary_reactions' in body, "the run summary must report what the trigger did"
    # …and on the already-enriched path too: consent can be granted AFTER enrichment,
    # and a paused/held reaction must get another chance without a force run.
    assert "maybe_react_to_diary(item, {})" in body, "an already-enriched entry must still be offered to the trigger"


def test_already_enriched_entry_still_reaches_the_trigger():
    """The consent-later / budget-paused / shipped-after-enrichment case. The stored
    record already carries enriched_*, so the empty enrichment view is the record itself."""
    stored = _item(enriched_at="2026-07-25T14:00:00+00:00", enriched_themes=["training"], enriched_sentiment="negative")
    view = jel.entry_with_enrichment(stored, {})
    assert view["enriched_themes"] == ["training"]

    table = MagicMock()
    table.get_item.return_value = {}  # no reaction stored yet
    out = cdr.maybe_react(
        view,
        table_=table,
        lambda_client=MagicMock(),
        budget_allow=lambda f: True,
        generate_fn=lambda s, u: "Good to hear you back on the mic.",
        ground_fn=lambda label, draft, allow: draft,
        quality_gate_fn=lambda _lc, _cid, t, _b: (t, {"passed": True}),
    )
    assert out["reacted"] is True
    assert table.put_item.call_args.kwargs["Item"]["sk"] == f"DATE#2026-07-25#video_diary#{_UID}"


# ── the IAM contract the trigger depends on (R8-ST6: user-NAMED grants) ─────────


def test_role_policies_diary_trigger():
    sys.path.insert(0, os.path.join(_REPO, "cdk"))
    sys.path.insert(0, os.path.join(_REPO, "cdk", "stacks"))

    class _PolicyStatement:
        def __init__(self, sid="", actions=None, resources=None, **kw):
            self.sid, self.actions, self.resources = sid, list(actions or []), list(resources or [])

    iam_stub = types.ModuleType("aws_cdk.aws_iam")
    iam_stub.PolicyStatement = _PolicyStatement
    cdk_stub = types.ModuleType("aws_cdk")
    cdk_stub.aws_iam = iam_stub
    sys.modules.setdefault("aws_cdk", cdk_stub)
    sys.modules.setdefault("aws_cdk.aws_iam", iam_stub)

    import role_policies as rp

    stmts = rp.ingestion_journal_enrichment()
    granted = {(a, r) for s in stmts for a in s.actions for r in s.resources}

    # budget_guard.allow() must be able to READ the tier — without this it fails OPEN
    # to tier 0 and the tier-2 reader-narrative pause is silently defeated (AC5).
    assert any(a == "ssm:GetParameter" and r.endswith("parameter/life-platform/budget-tier") for a, r in granted)
    # the ADR-077/#1233 cycle stamp on each stored reaction
    assert any(a == "ssm:GetParameter" and r.endswith("parameter/life-platform/experiment-cycle") for a, r in granted)
    # the ADR-108 quality gate is a SYNC lambda invoke, scoped to that one function
    assert ("lambda:InvokeFunction", f"arn:aws:lambda:{rp.REGION}:{rp.ACCT}:function:coach-quality-gate") in granted
    # least-privilege: no wildcard lambda invoke crept in
    assert not any(a == "lambda:InvokeFunction" and r.endswith(":function:*") for a, r in granted)


def test_diary_reactions_partition_is_registered_and_wiped():
    """A new EXPERIMENT_SCOPED partition must be in the taxonomy AND the restart wipe
    (the wipe's coverage assertion refuses to run otherwise — a silent zero-write reset)."""
    import importlib.util

    import phase_taxonomy as pt

    assert pt.classify("USER#matthew#SOURCE#diary_reactions", "DATE#2026-07-25#video_diary#abc") == pt.EXPERIMENT_SCOPED

    spec = importlib.util.spec_from_file_location("_wipe_1756", os.path.join(_REPO, "deploy", "restart_intelligence_wipe.py"))
    wipe = importlib.util.module_from_spec(spec)
    sys.modules["_wipe_1756"] = wipe
    spec.loader.exec_module(wipe)
    assert "diary_reactions" in {src for src, _mode, _extra in wipe.PARTITIONS}
