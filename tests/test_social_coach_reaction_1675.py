"""tests/test_social_coach_reaction_1675.py — coach reactions to SOCIAL posts (#1675).

Epic #1668 (The Social Membrane). #1574/#1756 built the coach-reaction mechanism for
Video Diary entries; this story points that SAME mechanism at the social channel. The
story's first acceptance criterion is explicitly "no parallel reaction machinery", so a
large part of what is pinned here is *sameness*: one producer, one partition, one
endpoint, one render surface.

What is proven here, all offline (no Bedrock, no DynamoDB, no SSM):

  AC1  a cleared human post produces + stores a reaction through the #1574 producer —
       and there is exactly ONE producer/partition/serve path for both channels
  AC2  the gate: a platform-origin (S2) post and an un-cleared/held (S5) post get NO
       reaction, and neither reaches a generation call — the AC's named negative test
  AC3  the reaction is ADR-104 grounded (the quotable line is a literal substring of the
       post's own public text; nothing else about the post reaches the prompt) and it
       renders on the SAME lab-notes surface as the diary reactions
  AC4  the overlap with #1574 is resolved as a SHARED mechanism, not a divergence

Plus the operational contract the trigger depends on: ADR-125 band placement, the ADR-108
quality gate, the phase/cycle stamp (#2119), per-post sk uniqueness, idempotency, the IAM
grants (without which budget_guard fails OPEN to tier 0), and fail-open wiring.
"""

import ast
import os
import sys
import textwrap
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
import social_enrichment_lambda as sel  # noqa: E402
from privacy import (
    broadcast_sensitivity_gate as bsg,  # noqa: E402
    social_consent as sc,  # noqa: E402
    social_provenance as prov,  # noqa: E402
)

_POST_ID = "dQw4w9WgXcQ"
_TITLE = "Week 3 of the ruck streak."
_DESC = "Forty minutes with the pack this morning. Cold, but the legs held."


def _post(**over):
    """A landed, membrane-stamped, sensitivity-cleared YouTube post (#1669 shape)."""
    base = {
        "pk": "USER#matthew#SOURCE#youtube",
        "sk": f"DATE#2026-08-04#{_POST_ID}",
        "date": "2026-08-04",
        "channel": "youtube",
        "source": "youtube",
        "post_id": _POST_ID,
        "post_type": "video",
        "title": _TITLE,
        "description": _DESC,
        "url": "https://www.youtube.com/watch?v=" + _POST_ID,
        "origin": prov.ORIGIN_HUMAN,
        bsg.STATUS_ATTR: bsg.SENSITIVITY_CLEARED,
        "views": 1417,
    }
    base.update(over)
    return base


# This pass's Haiku output — training-flavoured, so the routing assertion can only pass
# if the FRESH enrichment (not an absent/stale route) is what routed it.
_ENRICHMENT = {
    "themes": ["consistency", "physical achievement"],
    "behaviors": ["rucked 40 minutes"],
    "entities": [],
    "exercise_context": "cold but steady",
    "sentiment": "positive",
}


def _injected(**over):
    """The producer's dependency-injected callables — no live AI, gate or budget call."""
    kw = {
        "lambda_client": MagicMock(),
        "budget_allow": lambda _f: True,
        "generate_fn": lambda s, u: "Three weeks is where a habit stops being a decision. Keep the pack by the door.",
        "ground_fn": lambda _label, draft, _allow: draft,
        "quality_gate_fn": lambda _lc, _cid, t, _b: (t, {"passed": True}),
    }
    kw.update(over)
    return kw


# ── AC2: the membrane gates — the named negative test ────────────────────────────


def test_platform_origin_post_gets_no_reaction():
    """S2 (#1670): a re-ingested platform echo is not Matthew's voice. Reacting to it
    would be the coaches reacting to the platform — the #1668 spanning-tree failure."""
    post = _post(origin=prov.ORIGIN_PLATFORM)
    assert sc.blocked_reason(post) == sc.REASON_PLATFORM_ORIGIN
    assert sc.public_context(post) is None

    table = MagicMock()
    generated = []
    out = cdr.maybe_react(post, table_=table, **_injected(generate_fn=lambda s, u: generated.append((s, u)) or "x"))
    assert out == {"reacted": False, "reason": "platform_origin"}
    assert generated == [], "a platform echo must never reach a generation call"
    table.put_item.assert_not_called()
    # the gate is free — it stops before even the idempotency read
    table.get_item.assert_not_called()


def test_held_post_gets_no_reaction():
    """S5 (#1673): a post Matthew has NOT let auto-publish must not get a public coach
    reaction — that would route around his own hold."""
    post = _post(**{bsg.STATUS_ATTR: bsg.SENSITIVITY_HELD, bsg.REASON_ATTR: "flagged: pii"})
    assert sc.blocked_reason(post) == sc.REASON_HELD

    table = MagicMock()
    generated = []
    out = cdr.maybe_react(post, table_=table, **_injected(generate_fn=lambda s, u: generated.append(1) or "x"))
    assert out == {"reacted": False, "reason": "held"}
    assert generated == []
    table.put_item.assert_not_called()


def test_unstamped_post_is_held_fail_closed():
    """The gate is a POSITIVE match on 'cleared' — an un-classified/legacy row is NOT
    cleared. (Unlike the origin membrane, where an unstamped row is human.)"""
    post = _post()
    post.pop(bsg.STATUS_ATTR)
    assert sc.blocked_reason(post) == sc.REASON_HELD
    assert sc.public_context(post) is None


def test_cleared_human_post_is_reactable():
    post = _post()
    assert sc.blocked_reason(post) is None
    assert sc.is_reactable(post) is True


# ── AC3: ADR-104 grounding + the leak-proof allowlist ────────────────────────────


def test_quote_is_a_literal_substring_of_the_post_text():
    ctx = sc.public_context(_post())
    assert ctx["quote"] == _TITLE
    assert ctx["quote"] in sc.post_text(_post())
    assert ctx["tier"] == "quote"


def test_overlong_line_is_never_truncated_into_a_quote():
    """Truncating would break the literal-substring invariant, so a too-long candidate
    is rejected outright and the reaction falls back to allude strength."""
    long_line = "x" * (sc.MAX_QUOTE_CHARS + 5)
    ctx = sc.public_context(_post(title=long_line, description=long_line))
    assert "quote" not in ctx
    assert ctx["tier"] == "allude"


def test_context_is_an_allowlist_not_a_filtered_record():
    """Engagement counts, enrichment internals and the raw record must be structurally
    unreachable from the generation brief — a coach cannot cite a number it was never
    given (ADR-104)."""
    ctx = sc.public_context(_post(enriched_themes=["consistency"], secret_field="do not leak"))
    assert set(ctx) <= {"kind", "tier", "theme", "channel", "date", "quote", "url"}
    blob = " ".join(str(v) for v in ctx.values())
    assert "1417" not in blob and "do not leak" not in blob


def test_prompt_carries_only_the_public_context():
    ctx = sc.public_context(_post())
    system, user = cdr.build_reaction_prompt("training_coach", ctx)
    assert _TITLE in user  # the one cleared line
    assert _DESC not in user and _DESC not in system  # nothing else from the post
    assert "1417" not in user and "1417" not in system  # no engagement numbers
    assert "posted publicly" in system  # the SOCIAL frame, not the diary frame
    assert "No numbers, no metrics" in system


def test_theme_uses_the_shared_laundered_vocabulary():
    """Same 8-way public theme vocabulary as every other allude surface — imported from
    diary_consent, not a second social-only vocabulary."""
    from privacy.diary_consent import _THEME_CATEGORIES

    allowed = {c for c, _ in _THEME_CATEGORIES} | {"other"}
    assert sc.public_context(_post(enriched_themes=["training", "workout"]))["theme"] in allowed
    assert sc.public_context(_post(enriched_themes=["training"]))["theme"] == "health_body"


def test_post_url_must_be_https():
    assert sc.public_context(_post())["url"].startswith("https://")
    assert "url" not in sc.public_context(_post(url="javascript:alert(1)"))
    assert "url" not in sc.public_context(_post(url="http://insecure.example/x"))


# ── AC1 + AC4: ONE mechanism — the shared producer, partition and surface ────────


def test_end_to_end_cleared_post_stores_a_reaction_in_the_diary_reactions_partition():
    table = MagicMock()
    table.get_item.return_value = {}
    view = sel.post_with_enrichment(_post(), _ENRICHMENT)
    out = cdr.maybe_react(view, table_=table, **_injected())

    assert out["reacted"] is True and out["reason"] == "stored"
    item = table.put_item.call_args.kwargs["Item"]
    # THE point of the story: the same partition #1574 writes to, so the same
    # /api/diary_reactions query and the same lab-notes render pick it up for free.
    assert item["pk"] == cdr.DIARY_REACTIONS_PK
    assert item["sk"] == f"DATE#2026-08-04#youtube#{_POST_ID}"
    assert item["kind"] == "social"
    assert item["coach_id"] == "training_coach"  # routed by the enricher's own route
    assert item["quote"] == _TITLE
    assert item["post_url"].startswith("https://")
    assert item["phase"], "#2119: every COACH#/reaction writer stamps phase"


def test_routing_reuses_the_enrichers_own_deterministic_route():
    """Not a second router: social_signals already computed and persisted the route."""
    training = sel.post_with_enrichment(_post(), _ENRICHMENT)
    assert training["enriched_coach_route"] == "training"
    assert cdr.route_coach(training) == "training_coach"

    reflective = sel.post_with_enrichment(_post(), {"themes": ["gratitude"], "sentiment": "positive"})
    assert cdr.route_coach(reflective) == "mind_coach"


def test_reaction_kind_dispatch():
    assert cdr.reaction_kind(_post()) == cdr.KIND_SOCIAL
    assert cdr.reaction_kind({"channel": "video_diary"}) == cdr.KIND_DIARY
    assert cdr.reaction_kind({"channel": "journal"}) is None
    assert cdr.reaction_kind({}) is None


def test_two_same_day_posts_on_one_channel_keep_separate_rows():
    """The #1756 collision, on the social channel: without a per-post uid the second
    post of the day would overwrite the first."""
    a = cdr.reaction_sk("2026-08-04", "youtube", cdr.entry_uid(_post()))
    b = cdr.reaction_sk("2026-08-04", "youtube", cdr.entry_uid(_post(post_id="OTHERvid123")))
    assert a != b and a.endswith(_POST_ID)


def test_uid_is_sanitised_to_the_sk_safe_alphabet():
    assert cdr.entry_uid(_post(post_id="ab#cd/ef gh")) == "abcdefgh"
    assert cdr.entry_uid(_post(post_id="x" * 90)) == "x" * 48


def test_a_diary_entry_still_routes_through_the_diary_gate():
    """The shared mechanism must not have loosened the diary side: an unmarked entry is
    still private, and it does not accidentally take the social path."""
    entry = {"channel": "video_diary", "date": "2026-08-04", "raw_text": "private words"}
    assert cdr.public_context_for(entry) is None
    assert cdr.maybe_react(entry, table_=MagicMock(), **_injected()) == {"reacted": False, "reason": "private"}


def test_one_producer_and_one_serve_path_exist():
    """AC4, mechanically: no parallel reaction machinery was introduced."""
    import glob

    producers = [p for p in glob.glob(os.path.join(_REPO, "lambdas", "coach", "*reaction*.py"))]
    assert [os.path.basename(p) for p in producers] == ["coach_diary_reaction.py"]
    api = open(os.path.join(_REPO, "lambdas", "web", "site_api_lambda.py"), encoding="utf-8").read()
    assert api.count("/api/diary_reactions") == 1
    assert "social_reactions" not in api, "a second reactions endpoint would be the divergence AC4 forbids"


# ── the ADR-125 band + the ADR-108 gate + budget pause ───────────────────────────


def test_budget_feature_is_reader_narrative_band_2():
    from ai import budget_guard

    assert cdr.budget_feature(cdr.KIND_SOCIAL) == "coach_social_reaction"
    assert budget_guard._FEATURE_CUTOFF["coach_social_reaction"] == 2
    # same audience as the diary reaction ⇒ same band (ADR-125 orders by audience)
    assert budget_guard._FEATURE_CUTOFF["coach_diary_reaction"] == 2


def test_budget_paused_stores_nothing():
    table = MagicMock()
    table.get_item.return_value = {}
    asked = []
    out = cdr.maybe_react(
        _post(),
        table_=table,
        **_injected(budget_allow=lambda f: asked.append(f) or False, generate_fn=lambda s, u: 1 / 0),
    )
    assert out == {"reacted": False, "reason": "no_reaction"}
    assert asked == ["coach_social_reaction"]
    table.put_item.assert_not_called()


def test_quality_gate_hold_publishes_nothing():
    """ADR-108: a sub-threshold draft is HELD, never published — and held with
    max_regenerations=0, so the one-call-max promise survives."""
    table = MagicMock()
    table.get_item.return_value = {}
    out = cdr.maybe_react(_post(), table_=table, **_injected(quality_gate_fn=lambda *_a: (None, {"passed": False})))
    assert out == {"reacted": False, "reason": "no_reaction"}
    table.put_item.assert_not_called()


def test_exactly_one_generation_call_on_the_happy_path():
    calls = []
    table = MagicMock()
    table.get_item.return_value = {}
    cdr.maybe_react(_post(), table_=table, **_injected(generate_fn=lambda s, u: calls.append(1) or "A good week."))
    assert len(calls) == 1


def test_idempotent_once_a_reaction_exists():
    table = MagicMock()
    table.get_item.return_value = {"Item": {"pk": cdr.DIARY_REACTIONS_PK, "sk": "x"}}
    out = cdr.maybe_react(_post(), table_=table, **_injected(generate_fn=lambda s, u: 1 / 0))
    assert out == {"reacted": False, "reason": "exists"}
    table.put_item.assert_not_called()


# ── the trigger: inline in the social-enrichment pass, fail-open ─────────────────


def _patched_trigger(monkeypatch, result):
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
    calls = _patched_trigger(monkeypatch, {"reacted": True, "sk": "DATE#…", "coach_id": "training_coach"})
    out = sel.maybe_react_to_post(_post(), _ENRICHMENT)
    assert out["reacted"] is True
    ((entry, kwargs),) = calls
    assert entry["enriched_coach_route"] == "training"
    assert entry["enriched_themes"] == ["consistency", "physical achievement"]
    assert kwargs["table_"] is sel.table  # one table handle, the enrichment lambda's own


def test_trigger_is_fail_open(monkeypatch):
    _patched_trigger(monkeypatch, RuntimeError("bedrock down"))
    out = sel.maybe_react_to_post(_post(), _ENRICHMENT)
    assert out["reacted"] is False and out["reason"] == "error"


def test_already_enriched_view_does_not_reroute_to_mind():
    """post_with_enrichment(item, None) must NOT recompute the route from an empty dict
    — that would silently re-route every re-swept post to the Mind coach."""
    stored = _post(enriched_at="2026-08-04T14:00:00+00:00", enriched_coach_route="training", enriched_themes=["consistency"])
    view = sel.post_with_enrichment(stored, None)
    assert view["enriched_coach_route"] == "training"
    assert cdr.route_coach(view) == "training_coach"


def test_handler_loop_calls_the_trigger_on_both_paths():
    src = open(os.path.join(_REPO, "lambdas", "ingestion", "social_enrichment_lambda.py"), encoding="utf-8").read()
    assert "_tally(reactions, maybe_react_to_post(item, enrichment))" in src, "the trigger must run after a fresh enrichment"
    # …and on the already-enriched path: the S5 verdict can flip to cleared after
    # enrichment, and a paused/held reaction must get another chance without --force.
    assert "_tally(reactions, maybe_react_to_post(item))" in src
    assert '"reactions": reactions' in src, "the run summary must report what the trigger did"


def test_post_text_has_exactly_one_definition():
    """The reaction's quote-grounding and the enricher's causal-hint grounding must
    check against byte-identical text (#1675) — two definitions would let a string
    ground against one and not the other."""
    from content import social_signals

    assert sel.post_text(_post()) == social_signals.post_text(_post()) == sc.post_text(_post())
    assert sel.post_text(_post()) == f"{_TITLE}\n{_DESC}"


# ── the IAM contract the trigger depends on (R8-ST6: user-NAMED grants) ──────────


def test_role_policies_social_reaction_trigger():
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

    granted = {(a, r) for s in rp.ingestion_social_enrichment() for a in s.actions for r in s.resources}

    # budget_guard.allow() must be able to READ the tier — without this it fails OPEN to
    # tier 0 and the band-2 reader-narrative pause is silently defeated.
    assert any(a == "ssm:GetParameter" and r.endswith("parameter/life-platform/budget-tier") for a, r in granted)
    # the ADR-077/#1233 cycle stamp on each stored reaction
    assert any(a == "ssm:GetParameter" and r.endswith("parameter/life-platform/experiment-cycle") for a, r in granted)
    # the ADR-108 quality gate is a SYNC lambda invoke, scoped to that one function
    assert ("lambda:InvokeFunction", f"arn:aws:lambda:{rp.REGION}:{rp.ACCT}:function:coach-quality-gate") in granted
    # G1: an AI-calling role emits per-feature cost metrics at the chokepoint
    assert ("cloudwatch:PutMetricData", "*") in granted
    # least-privilege: no wildcard lambda invoke crept in
    assert not any(a == "lambda:InvokeFunction" and r.endswith(":function:*") for a, r in granted)


def test_serve_shape_and_render_agree_on_the_field_names():
    """The classic silent drift: the serve layer renames a field and the reader keeps
    reading the old one, so the surface goes quietly blank. Pin the three #1675 fields
    across the boundary (coaching.js has no exports, so this is a source-level pair)."""
    # #1654 split site_api_coach.py into a facade + siblings: `handler_source` follows
    # the facade's thin delegator to the module that actually owns the body, so this
    # pair keeps reading the real serve shape instead of a three-line delegator.
    from site_api_family import handler_source

    shape = handler_source("site_api_coach", "handle_diary_reactions")
    assert shape, "handle_diary_reactions resolved to an empty body — the AST walk went inert"
    js = open(os.path.join(_REPO, "site", "assets", "js", "coaching.js"), encoding="utf-8").read()

    # The EMITTED key names, not "the name appears somewhere in the body" — a substring
    # scan could not tell `"kind": …` (what the reader gets) from `i.get("kind")` (what
    # storage is called), so renaming the response key alone left the guard green. That
    # rename IS the drift this test is named for, so the assertion is made against the
    # payload keys: dict-literal keys plus `out["…"] = …` assignments.
    tree = ast.parse(textwrap.dedent(shape))
    emitted = {k.value for d in ast.walk(tree) for k in getattr(d, "keys", []) if isinstance(k, ast.Constant) and isinstance(k.value, str)}
    emitted |= {
        n.slice.value
        for n in ast.walk(tree)
        if isinstance(n, ast.Subscript)
        and isinstance(n.ctx, ast.Store)
        and isinstance(n.slice, ast.Constant)
        and isinstance(n.slice.value, str)
    }
    assert emitted, "no response keys discovered — the AST scan went inert"

    for field in ("kind", "uid", "post_url"):
        assert field in emitted, f"the serve shape must emit {field}"
        assert f"r.{field}" in js or f"x.{field}" in js, f"the render must read {field}"
    # the list id must carry the per-record uid, or two same-day posts on one channel
    # collapse to one addressable entry (the render-layer twin of the #1756 sk collision)
    assert '"~" + r.uid' in js
    # …and it must NOT use '#', which selectEntry writes straight into location.hash
    assert '"#" + r.uid' not in js


def test_social_reactions_reuse_the_registered_partition():
    """No new phase-taxonomy registration was needed — sharing the partition means the
    reset semantics are shared too (and the wipe's coverage assertion still holds)."""
    from experiment import phase_taxonomy as pt

    assert pt.classify(cdr.DIARY_REACTIONS_PK, f"DATE#2026-08-04#youtube#{_POST_ID}") == pt.EXPERIMENT_SCOPED
