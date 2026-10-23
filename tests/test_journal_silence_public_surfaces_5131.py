"""tests/test_journal_silence_public_surfaces_5131.py — the journal's silence on EVERY public surface (#5131).

THE CLASS
---------
`common.journal_silence` was applied by two PRODUCERS (the Story Desk and the daily coach-moves gate). A
producer-side refusal cannot reach a row it never wrote: the coach line refused since #4583 was still served on
2026-10-23 by `/api/edition` and `/api/coaching-dashboard`, read back from the row stored before the gate
existed, and a coach's open action on the dashboard carried the same class from a third producer no gate read.
So the guard now sits on the SURFACES, and this file is the contract over them.

THE SET IS DERIVED FROM CODE, NEVER HAND-ENUMERATED
---------------------------------------------------
Three reader-facing writer families, each derived by an AST walk:

  * API — every Lambda exposed through a Function URL in `cdk/stacks/*.py` (`<fn>.add_function_url(...)`,
    resolved to its `source_file=` / `handler=` module).
  * generated/ — every module under `lambdas/` that makes an S3 write call AND names a `generated/...` key.
  * mail — every module under `lambdas/` that calls an SES send method or the shared send helpers.

Each derived member must be classified in the registry below: `GUARDED` (its source calls the family's guard,
and the guard's behaviour is proved here) or an exemption carrying a one-line reason (owner-only mail, binary
images, fixed transactional copy...). A NEW member that is in neither fails `test_every_derived_surface_is_classified`
by name, and a classified module that left the set fails as stale — the acceptance's "the test fails when a new
public surface is added without being listed".

Every API route is then exercised through the REAL handler: `deploy/endpoint_registry.py`'s AST-derived route set
(the same set the schema-completeness gate reads), each dispatched to a stub that returns a journal-silence
payload, and the response read back off the wire.

No private journal content appears here — the fixture lines are synthetic.
"""

# premerge-gate: #5131: AST sweep of lambdas/ + cdk/stacks/ — the derived public-surface writer set must be fully classified and guarded
from __future__ import annotations

import ast
import functools
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LAMBDAS = ROOT / "lambdas"
CDK_STACKS = ROOT / "cdk" / "stacks"
for _p in (str(LAMBDAS), str(ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")

from common import journal_silence as J  # noqa: E402

GUARDED = "guarded"

# Synthetic — never a real line, never a real count.
LEAK = "The numbers held. Still, the journal has gone quiet for weeks, and that is the real story. Protein is fine."
CLEAN = "The numbers held. Protein is fine."

# ── The registry: every derived member, classified ────────────────────────────────────────────────────────

API_SURFACES = {
    "web/site_api_lambda.py": GUARDED,
    "web/site_api_ai_lambda.py": GUARDED,
    "web/email_subscriber_lambda.py": "fixed transactional copy (subscribe / confirm / unsubscribe) — composes no coach or AI text",
    "web/og_image_lambda.py": "answers with PNG/WebP share cards; their text inputs are the guarded generated/ artifacts",
    "web/progress_viewer_lambda.py": "owner-only: the HMAC-cookie private photo viewer, not a reader surface",
    "web/telegram_webhook_lambda.py": "the owner's private Telegram chat webhook — answers Telegram, never a reader",
    "emails/chronicle_approve_lambda.py": "owner-only signed approval link; what it PUBLISHES is guarded in the generated/ family",
}

GENERATED_WRITERS = {
    "compute/coach_memoir_lambda.py": GUARDED,
    "content/output_writers.py": GUARDED,
    "content/site_writer.py": GUARDED,
    "emails/chronicle_approve_lambda.py": GUARDED,
    "emails/chronicle_podcast_lambda.py": GUARDED,  # feed + index, and the narration script before TTS
    "emails/chronicle_render.py": GUARDED,
    "emails/chronicle_store.py": GUARDED,
    "emails/coach_panel_podcast_lambda.py": GUARDED,  # feed + transcripts, and every spoken line before TTS
    "emails/daily_debrief_lambda.py": GUARDED,  # feed + index, and the spoken script before TTS
    "web/og_moments.py": GUARDED,
    "web/site_stats_refresh_lambda.py": GUARDED,
    "ai/bedrock_batch.py": "batch-inference staging; refuses every public prefix (PUBLIC_PREFIXES) by construction",
    "common/qa_archive.py": "the QA archive copies surfaces ALREADY served (each guarded at its writer); no CloudFront behaviour",
    "content/editorial_image.py": "writes images only",
    "reading/cover_pipeline_lambda.py": "writes book-cover images only",
    "web/og_coach_cards.py": "writes PNG/WebP coach cards only",
    "web/og_image_lambda.py": "writes PNG/WebP share cards only",
    "web/site_api_capture_store.py": "the moderation queue of reader SUBMISSIONS (no CloudFront behaviour) — a reader's words, not platform copy",
}

MAIL_SENDERS = {
    # reader mail — people who are not Matthew
    "compute/weekly_signal_lambda.py": GUARDED,
    "emails/between_chronicle_lambda.py": GUARDED,
    "emails/chronicle_email_sender_lambda.py": GUARDED,
    "emails/coach_panel_podcast_lambda.py": GUARDED,  # the subscriber episode notice (its owner notices are owner mail)
    "emails/milestone_digest_lambda.py": GUARDED,  # the friends-and-family list
    "emails/partner_email_lambda.py": GUARDED,  # the partner address
    "web/subscriber_onboarding_lambda.py": GUARDED,
    "web/email_subscriber_lambda.py": "fixed transactional copy (confirmation / welcome) — composes no coach or AI text",
    "coach/named_human_contact.py": "carries NO health data at all — render_email's stricter no-health-data body contract refuses first",
    "operational/permanence_lambda.py": "continuity-contact notice: a fixed template naming the archive URLs, no coach or AI text",
    # owner mail — one recipient, Matthew (EMAIL_RECIPIENT); the owner's channel is not a reader surface
    "content/recap_deliver.py": "owner mail (EMAIL_RECIPIENT)",
    "content/story_questions.py": "owner mail (wednesday_chronicle passes RECIPIENT)",
    "emails/ai_review_pack_lambda.py": "owner mail",
    "emails/anomaly_detector_lambda.py": "owner mail",
    "emails/chronicle_store.py": "owner mail (the chronicle preview)",
    "emails/coach_nudge_lambda.py": "owner mail",
    "emails/daily_brief_lambda.py": "owner mail",
    "emails/evening_nudge_lambda.py": "owner mail",
    "emails/habit_skip_review_lambda.py": "owner mail",
    "emails/insight_email_parser_lambda.py": "owner mail (a reply to the owner's own inbound insight mail)",
    "emails/monday_compass_lambda.py": "owner mail",
    "emails/monthly_digest_lambda.py": "owner mail",
    "emails/nutrition_review_lambda.py": "owner mail",
    "emails/panelcast_repair.py": "owner mail (the exhaustion escalation)",
    "emails/wednesday_chronicle_lambda.py": "owner mail (preview + story questions to RECIPIENT)",
    "emails/weekly_digest_lambda.py": "owner mail",
    "emails/weekly_plate_lambda.py": "owner mail",
    "operational/alert_digest_lambda.py": "ops mail to the owner",
    "operational/canary_lambda.py": "ops mail to the owner",
    "operational/dlq_consumer_lambda.py": "ops mail to the owner",
    "operational/qa_smoke_lambda.py": "ops mail to the owner",
    "operational/traffic_digest_lambda.py": "ops mail to the owner",
}

# The family's guard: a GUARDED member's source must call one of these.
GUARD_FOR_FAMILY = {
    "api": frozenset({"guard_api_response"}),
    "generated": frozenset({"public_body", "scrub_document", "scrub_payload", "spoken_turns"}),
    "mail": frozenset({"reader_mail"}),
}

# ── Derivations (each parameterised by root so the synthetic-tree tests can prove they see a new member) ─────

S3_WRITE_METHODS = frozenset({"put_object", "upload_fileobj", "upload_file", "copy_object"})
SES_SEND_CALLS = frozenset({"send_email", "send_raw_email", "send_templated_email", "guarded_send_email", "guarded_send_raw_email"})


def _call_name(node: ast.Call) -> str:
    f = node.func
    return f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else ""


@functools.lru_cache(maxsize=None)
def _modules(root: Path) -> tuple:
    """(rel, call names, names a `generated/...` key) per module — one parse per file, shared by every walk."""
    out = []
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover — a broken file is another gate's problem
            continue
        calls, refs, gen = set(), set(), False
        for n in ast.walk(tree):
            if isinstance(n, ast.Call):
                calls.add(_call_name(n))
            elif isinstance(n, ast.Attribute):  # `map(journal_silence.reader_mail, ...)` applies the guard without calling it here
                refs.add(n.attr)
            elif isinstance(n, ast.Name):
                refs.add(n.id)
            elif isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value.startswith("generated/"):
                gen = True
        out.append((path.relative_to(root).as_posix(), frozenset(calls), frozenset(refs | calls), gen))
    return tuple(out)


def derive_generated_writers(root: Path = LAMBDAS) -> set:
    return {rel for rel, calls, _refs, gen in _modules(root) if gen and calls & S3_WRITE_METHODS}


def derive_mail_senders(root: Path = LAMBDAS) -> set:
    # common/send_guard.py is the shared helper itself, not a sender
    return {rel for rel, calls, _refs, _gen in _modules(root) if calls & SES_SEND_CALLS and rel != "common/send_guard.py"}


def _handler_module(kws: dict, lambdas_root: Path) -> str | None:
    sf = kws.get("source_file")
    if isinstance(sf, ast.Constant) and isinstance(sf.value, str) and sf.value.startswith("lambdas/"):
        return sf.value[len("lambdas/") :]
    handler = kws.get("handler")
    if isinstance(handler, ast.Constant) and isinstance(handler.value, str):
        leaf = handler.value.rsplit(".", 1)[0].split(".")[-1] + ".py"
        hits = sorted(p.relative_to(lambdas_root).as_posix() for p in lambdas_root.rglob(leaf))
        return hits[0] if len(hits) == 1 else None
    return None


def derive_api_lambdas(cdk_root: Path = CDK_STACKS, lambdas_root: Path = LAMBDAS) -> dict:
    """{module rel path: 'stack.py:line'} for every Lambda a cdk stack exposes through `add_function_url`.
    An exposed function whose module cannot be resolved is returned under `?<var>` so it fails classification."""
    found = {}
    for path in sorted(cdk_root.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        defs = {}
        for n in ast.walk(tree):
            if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call):
                for t in n.targets:
                    name = t.id if isinstance(t, ast.Name) else t.attr if isinstance(t, ast.Attribute) else None
                    if name:
                        defs[name] = {kw.arg: kw.value for kw in n.value.keywords if kw.arg}
        for n in ast.walk(tree):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "add_function_url":
                owner = n.func.value
                var = owner.id if isinstance(owner, ast.Name) else owner.attr if isinstance(owner, ast.Attribute) else "?"
                module = _handler_module(defs.get(var, {}), lambdas_root)
                found[module or f"?{var}"] = f"{path.name}:{n.lineno}"
    return found


def _calls_any(rel: str, names: frozenset) -> bool:
    return any(r == rel and refs & names for r, _calls, refs, _gen in _modules(LAMBDAS))


FAMILIES = {
    "api": (API_SURFACES, lambda: set(derive_api_lambdas())),
    "generated": (GENERATED_WRITERS, derive_generated_writers),
    "mail": (MAIL_SENDERS, derive_mail_senders),
}


# ── The contract over the set ──────────────────────────────────────────────────────────────────────────────


def test_every_derived_surface_is_classified():
    """THE gate. Every derived reader-facing writer is classified, and no classification is stale. Reports
    every offender across all three families in one failure."""
    offenders = []
    for family, (registry, derive) in FAMILIES.items():
        derived = derive()
        assert (
            len(derived) >= {"api": 5, "generated": 12, "mail": 25}[family]
        ), f"{family}: derivation found only {len(derived)} — broken walk"
        for rel in sorted(derived - set(registry)):
            offenders.append(
                f"{family}: NEW public writer {rel} is unclassified — guard it ({sorted(GUARD_FOR_FAMILY[family])}) or exempt it with a reason"
            )
        for rel in sorted(set(registry) - derived):
            offenders.append(f"{family}: {rel} is classified but no longer derived — remove the stale entry")
        for rel, verdict in sorted(registry.items()):
            if verdict == GUARDED:
                if (LAMBDAS / rel).exists() and not _calls_any(rel, GUARD_FOR_FAMILY[family]):
                    offenders.append(f"{family}: {rel} is GUARDED but never calls {sorted(GUARD_FOR_FAMILY[family])}")
            elif not (isinstance(verdict, str) and verdict.strip()):
                offenders.append(f"{family}: {rel} is exempt without a reason")
    assert not offenders, "\n".join(offenders)


def test_the_derivations_see_a_new_member(tmp_path):
    """Non-vacuity: a synthetic tree with an unlisted generated/ writer, an unlisted reader sender and an
    unlisted Function URL is derived as three new members — so the gate above cannot pass on a blind walk."""
    lam = tmp_path / "lambdas" / "web"
    lam.mkdir(parents=True)
    (lam / "new_page_lambda.py").write_text(
        'def lambda_handler(e, c):\n    s3.put_object(Key="generated/new.json", Body="{}")\n    ses.send_email(Destination={})\n'
    )
    stacks = tmp_path / "cdk"
    stacks.mkdir()
    (stacks / "x_stack.py").write_text(
        'fn = create_platform_lambda(self, source_file="lambdas/web/new_page_lambda.py")\nurl = fn.add_function_url(auth_type=None)\n'
    )
    root = tmp_path / "lambdas"
    assert derive_generated_writers(root) == {"web/new_page_lambda.py"}
    assert derive_mail_senders(root) == {"web/new_page_lambda.py"}
    assert derive_api_lambdas(stacks, root) == {"web/new_page_lambda.py": "x_stack.py:2"}
    for registry in (API_SURFACES, GENERATED_WRITERS, MAIL_SENDERS):
        assert "web/new_page_lambda.py" not in registry


# ── The guard's behaviour ──────────────────────────────────────────────────────────────────────────────────


def test_a_list_card_is_dropped_and_standalone_prose_loses_only_the_sentence():
    payload = {"lines": [{"coach": "A", "text": LEAK}, {"coach": "B", "text": CLEAN}], "answer": LEAK, "journal_entries": 3}
    scrubbed, hits = J.scrub_payload(payload)
    assert hits == 2
    assert scrubbed["lines"] == [{"coach": "B", "text": CLEAN}], "a quoted coach line is withheld whole, never cut"
    assert scrubbed["answer"] == CLEAN
    assert scrubbed["journal_entries"] == 3, "keys and non-text values are not reader copy"


def test_documents_lose_the_sentence_and_never_cut_a_tag():
    html = f"<article><p>{LEAK}</p><p>Sleep held at 7.5 hours.</p></article>"
    out = J.scrub_document(html)
    assert not J.mentions_journal_silence(out)
    assert out == f"<article><p>{CLEAN}</p><p>Sleep held at 7.5 hours.</p></article>"
    assert J.scrub_document("The diary has been blank") == ""


def test_public_body_is_a_no_op_on_clean_and_binary_bodies():
    clean = json.dumps({"a": CLEAN}).encode("utf-8")
    assert J.public_body(clean, "application/json") is clean
    png = b"\x89PNG\r\n\x1a\n\x00\xff journal has gone quiet"
    assert J.public_body(png, "image/png") is png
    out = J.public_body(json.dumps({"items": [LEAK, CLEAN]}).encode("utf-8"), "application/json")
    assert isinstance(out, bytes) and json.loads(out) == {"items": [CLEAN]}
    assert (
        J.public_body(f"<item><description>{LEAK}</description></item>", "application/rss+xml")
        == f"<item><description>{CLEAN}</description></item>"
    )


def test_reader_mail_and_the_coach_public_slots_refuse_it():
    from coach import audience_guard

    assert not J.mentions_journal_silence(J.reader_mail(f"<p>{LEAK}</p>"))
    turns = [{"speaker": "a", "line": LEAK}, {"speaker": "b", "line": "The diary has been blank."}]
    assert J.spoken_turns(turns) == [{"speaker": "a", "line": CLEAN}], "a podcast turn is scrubbed BEFORE TTS; an emptied turn is dropped"
    assert audience_guard.reader_safe(LEAK) is None
    assert audience_guard.public_items([LEAK, CLEAN]) == [CLEAN]
    assert audience_guard.public_read({"public_summary": LEAK}) is None
    assert audience_guard.reader_safe(CLEAN) == CLEAN


# ── Every route of the public API Lambdas, through the real handler ───────────────────────────────────────


def _event(path: str, method: str = "GET") -> dict:
    return {
        "rawPath": path,
        "requestContext": {"http": {"method": method, "sourceIp": "203.0.113.9"}},
        "queryStringParameters": {},
        "headers": {},
    }


def _leaky_response() -> dict:
    body = {"moves": {"lines": [{"coach": "A", "text": LEAK}]}, "open_actions": [{"text": LEAK}], "read": LEAK}
    return {"statusCode": 200, "headers": {"Content-Type": "application/json"}, "body": json.dumps(body)}


def test_every_site_api_route_serves_no_journal_silence(monkeypatch):
    """Each route in the AST-derived registry, dispatched to a stub that answers with the incident's shapes (a
    coach line, an open action, a standalone read), comes back off the real `lambda_handler` clean — with the
    withheld count on the wire. One test, every offender reported."""
    from web import site_api_lambda as L

    from deploy.endpoint_registry import discover_endpoint_paths

    paths = sorted(discover_endpoint_paths())
    assert len(paths) >= 100, f"endpoint registry derived only {len(paths)} routes"
    monkeypatch.setattr(L, "SITE_API_ORIGIN_SECRET", "", raising=False)
    monkeypatch.setattr(L, "_dispatch_route", lambda event, path, method: _leaky_response())
    leaked = []
    for path in paths:
        if path == "/api/healthz":  # answered above the dispatch with a fixed, text-free health document
            continue
        resp = L.lambda_handler(_event(path), None)
        if J.mentions_journal_silence(resp.get("body")) or resp["headers"].get(J.WITHHELD_HEADER) != "3":
            leaked.append(path)
    assert not leaked, f"{len(leaked)} route(s) served journal silence: {leaked[:20]}"


def test_every_ai_answer_door_serves_no_journal_silence(monkeypatch):
    from web import site_api_ai_lambda as ai

    monkeypatch.setattr(ai, "SITE_API_ORIGIN_SECRET", "", raising=False)
    leaked = []
    for path, handler in (("/api/ask", "_handle_ask"), ("/api/board_ask", "_handle_board_ask"), ("/api/explain", "_handle_explain")):
        monkeypatch.setattr(ai, handler, lambda event: _leaky_response())
        resp = ai.lambda_handler(_event(path, "POST"), None)
        if J.mentions_journal_silence(resp["body"]) or json.loads(resp["body"]).get("read") != CLEAN:
            leaked.append(path)
    assert not leaked, f"AI door(s) served journal silence: {leaked}"


def test_mutation_control_a_dead_pattern_lets_the_leak_through(monkeypatch):
    """The guard reads the ONE pattern at call time: disarm it and the incident's payload passes untouched —
    the proof the route test above can fail."""
    from web import site_api_lambda as L

    monkeypatch.setattr(L, "SITE_API_ORIGIN_SECRET", "", raising=False)
    monkeypatch.setattr(L, "_dispatch_route", lambda event, path, method: _leaky_response())
    assert not J.mentions_journal_silence(L.lambda_handler(_event("/api/edition"), None)["body"])
    real = J.JOURNAL_SILENCE
    monkeypatch.setattr(J, "JOURNAL_SILENCE", re.compile(r"(?!x)x"))
    resp = L.lambda_handler(_event("/api/edition"), None)
    assert real.search(resp["body"]), "with the pattern disarmed the leak must reach the wire"
