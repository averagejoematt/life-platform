"""tests/test_narrative_publication_gate.py — AI-written narrative reaches a public route only with a
known, private-free provenance (owner ruling 2026-11-03: "Replace [the keyword filter] with a
structured, source-aware publication policy ... fail closed when provenance is unknown, and add
regression tests covering paraphrased disclosures").

Every disclosure in these tests is SYNTHETIC — a sentence written for the test, never the owner's
words: "writing stays dark", "the notebook has gone quiet", "no entries this week". None names the
journal, so the #5131 keyword scrub (`common.journal_silence`) cannot see them; only provenance can.

THE SET, NOT THE INSTANCE. `tests/narrative_publication_route_walk.py` walks EVERY site-API GET
route (ROUTES + _SIMPLE_ROUTES + the inline `_dispatch_route` branches + every /api/coach/<id>,
/api/ai_analysis?expert=, /api/coach_analysis?domain=, /api/coach_timeline?coach_id=) against a
table whose narrative rows (OUTPUT#, STANCE#, COMMITMENT#, PREDICTION#, LEARNING#, THREAD#,
LEAD_DAILY#, MOVES#, EXPERT#*, the coach-thread rows, the docket, the ensemble digest, field notes,
state_of_matthew, challenges) all carry the disclosure under one provenance variant:

  (a) private     — a known record naming a private family  -> served on NO route;
  (b) unrecorded  — no record (every row before the ruling)  -> served on NO route;
  (c) public      — a known record of public families only   -> served (non-vacuity).

Negative control: `--ungated` (and the same walk run against origin/main 19b968279, recorded in the
PR: 30 leaking routes per variant) must leak — the code before this change served (a) and (b).
"""

from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lambdas"))

from common import narrative_provenance as NP  # noqa: E402

DISCLOSURE = "In this synthetic fixture the subject's writing stays dark, the notebook has gone quiet, and there were no entries this week."
PHRASES = ("writing stays dark", "the notebook has gone quiet", "no entries this week")


def _walk(*args) -> dict:
    proc = subprocess.run(
        [sys.executable, str(ROOT / "tests" / "narrative_publication_route_walk.py"), *args],
        capture_output=True,
        text=True,
        timeout=300,
        cwd=str(ROOT),
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


@pytest.fixture(scope="module")
def walks() -> dict:
    return {v: _walk("--variant", v) for v in ("private", "unrecorded", "public")}


# ── the route walk ───────────────────────────────────────────────────────────────────────────


def test_the_walk_reaches_the_router(walks):
    for v, out in walks.items():
        assert out["routes"] >= 150 and out["answered"] >= out["routes"] - 5, (v, out["routes"], out["answered"])
        assert out["raised"] == {}, (v, out["raised"])
        assert out["unparsed_queries"] == 0, "a query the gate could not read — a blind spot"


@pytest.mark.parametrize("variant", ["private", "unrecorded"])
def test_private_or_unrecorded_narrative_is_served_on_no_public_route(walks, variant):
    out = walks[variant]
    assert out["leaks"] == {}, f"routes serving a {variant}-provenance disclosure: {out['leaks']}"
    assert out["seen"] == {}, out["seen"]


def test_public_provenance_narrative_is_served(walks):
    """Non-vacuity: the same rows with a public record ARE served — on the named surfaces."""
    seen = walks["public"]["seen"]
    assert walks["public"]["leaks"] == {}, walks["public"]["leaks"]  # the record itself never reaches the wire
    for route in (
        "/api/coaching-dashboard",
        "/api/coach_moves?date=2026-11-02",
        "/api/edition",
        "/api/weekly_priority",
        "/api/coach_team",
        "/api/predictions",
        "/api/ledger_export",
        "/api/coach/mind_coach",
        "/api/coach/eli_marsh",
        "/api/coach_docket",
    ):
        assert route in seen, (route, sorted(seen))
    assert len(seen) >= 25, sorted(seen)
    dash = walks["public"]["dashboard"]
    assert dash["moves_lines"] >= 1 and dash["withheld_slots"] == 0 and dash["header"] is None


@pytest.mark.parametrize("variant", ["private", "unrecorded"])
def test_the_dashboard_serves_a_neutral_withheld_state(walks, variant):
    """The two live exposures (moves.lines[].text, coaches[].position_summary) read withheld, with
    the same neutral reason everywhere — never a word of the text or its sources, and (owner ruling
    2026-11-05) never a COUNT of what was withheld: no `_meta.withheld`, no count header."""
    dash = walks[variant]["dashboard"]
    assert set(dash["position_summaries"]) == {""}, dash
    # Owner ruling 2026-11-06: emptied slots carry no `_withheld` marker and the moves day no `withheld` state.
    assert dash["withheld_slots"] == 0 and len(dash["position_summaries"]) >= 7
    assert dash["moves_lines"] == 0 and dash["moves_withheld"] is False
    assert dash["meta_withheld"] is None and dash["header"] is None
    assert "journal" not in NP.PUBLIC_WITHHELD_REASON.lower() and "private" not in NP.PUBLIC_WITHHELD_REASON.lower()


@pytest.mark.parametrize("variant", ["private", "unrecorded"])
def test_withholding_words_never_changes_a_public_number(walks, variant):
    """ADR-104: the graded record's counts, lengths, rates and scores are identical with and
    without the gate (the predictions' class counts read the sentence, so a read-side blank
    would have moved them)."""
    narrative_only = (".recent_outputs", ".stance", ".lead_daily", ".daily", ".memoir")  # words, not the record

    def record(rows):
        return [r for r in rows if not str(r[0]).startswith(narrative_only)]

    gated = walks[variant]["numbers"]
    ungated = _walk("--variant", variant, "--ungated")["numbers"]
    assert set(gated) == set(ungated) and len(gated) >= 8, (sorted(gated), sorted(ungated))
    for route in gated:
        assert record(gated[route]) == record(ungated[route]), route
        assert len(record(gated[route])) >= 3, route  # non-vacuous: the route served a record


@pytest.mark.parametrize("variant", ["private", "unrecorded"])
def test_negative_control_the_ungated_code_leaks(variant):
    """Unwrap the chokepoint (the shape of the code before the ruling): the walk must red. The
    #5131 scrub is still on that path — and catches none of the paraphrases."""
    leaks = _walk("--variant", variant, "--ungated")["leaks"]
    assert len(leaks) >= 20, leaks
    assert "/api/coaching-dashboard" in leaks and "/api/coach_moves?date=2026-11-02" in leaks, sorted(leaks)


def test_the_keyword_scrub_alone_cannot_see_the_paraphrases():
    from common import journal_silence

    assert not journal_silence.mentions_journal_silence(DISCLOSURE)
    for p in PHRASES:
        assert not journal_silence.mentions_journal_silence(p)


# ── the policy ───────────────────────────────────────────────────────────────────────────────


def _rec(*families, v=1):
    return {"v": v, "families": list(families), "producer": "test"}


@pytest.mark.parametrize(
    "row, expected",
    [
        ({}, NP.R_UNRECORDED),
        ({"provenance": None}, NP.R_UNRECORDED),
        ({"provenance": "whoop"}, NP.R_UNRECORDED),
        ({"provenance": _rec()}, NP.R_UNRECORDED),
        ({"provenance": _rec("whoop", v=2)}, NP.R_MALFORMED),
        ({"provenance": {"v": "x", "families": ["whoop"]}}, NP.R_MALFORMED),
        ({"provenance": _rec("whoop", "journal_presence")}, NP.R_PRIVATE),
        ({"provenance": _rec("whoop", "notion")}, NP.R_PRIVATE),
        ({"provenance": _rec("whoop", "a_family_nobody_classified")}, NP.R_UNKNOWN),
        ({"provenance": _rec("whoop", NP.UNRECORDED)}, NP.R_UNKNOWN),
        ({"provenance": _rec("whoop", "withings", "persona")}, NP.ELIGIBLE),
    ],
)
def test_eligibility_fails_closed(row, expected):
    ok, reason = NP.eligibility(row)
    assert reason == expected and ok is (expected == NP.ELIGIBLE)


def test_an_unrecorded_input_is_contagious():
    """Text written from a stored narrative inherits it: an input with no record withholds the output."""
    rec = NP.stamp(["whoop"], producer="t", upstream=[{"provenance": _rec("withings")}, {}])
    assert set(rec["families"]) == {"whoop", "withings", NP.UNRECORDED}
    assert not NP.is_publishable(rec)
    assert NP.is_publishable(NP.stamp(["whoop"], producer="t", upstream=[{"provenance": _rec("withings")}]))
    assert not NP.is_publishable(NP.stamp(["whoop"], producer="t", upstream=[{"provenance": _rec("mood_read")}]))


def test_every_owner_only_source_is_classified():
    """A new SOURCE_TIERS partition cannot default into public narrative: it must be classified
    here (and an unclassified family is withheld anyway)."""
    from privacy.field_tiers import SOURCE_TIERS

    missing = sorted(set(SOURCE_TIERS) - set(NP.SOURCE_FAMILIES))
    assert not missing, f"classify these in common.narrative_provenance.SOURCE_FAMILIES: {missing}"


def test_the_journal_and_everything_journal_grade_is_private():
    from privacy.field_tiers import SOURCE_TIERS, TIER_PUBLIC

    for fam in ("notion", "journal", "journal_presence", "journal_analysis", "journal_quotes", "mood_read", "clinical", "owner_thread"):
        assert NP.classify(fam) == NP.PRIVATE, fam
    # Every owner-only partition is private unless a deliberate projection is named public here.
    projected = {"macrofactor", "hevy", "strava", "supplements", "sick_days", "reading", "cgm_readings"}
    for source, tier in SOURCE_TIERS.items():
        if tier != TIER_PUBLIC and source not in projected and NP.classify(source) != NP.PUBLIC:
            assert NP.classify(source) == NP.PRIVATE, source
    assert {s for s, t in SOURCE_TIERS.items() if t != TIER_PUBLIC and NP.classify(s) == NP.PUBLIC} <= projected | {
        "labs",
        "dexa",
        "measurements",
    }
    assert NP.families_from_fields(["journal.days_since"]) == ["journal_presence"]


# ── the chokepoint ───────────────────────────────────────────────────────────────────────────


class _FakeTable:
    def __init__(self, items):
        self.items = items
        self.last = None

    def query(self, **kw):
        self.last = kw
        return {"Items": [dict(i) for i in self.items]}

    def get_item(self, **kw):
        self.last = kw
        return {"Item": dict(self.items[0])}

    def scan(self, **kw):
        self.last = kw
        return {"Items": [dict(i) for i in self.items]}

    def put_item(self, **kw):
        return {"put": kw}


def _gate():
    from web import narrative_publication

    return narrative_publication


def test_a_withheld_row_keeps_structure_and_loses_every_word():
    G = _gate()
    G.begin_request()
    row = {
        "pk": "COACH#mind_coach",
        "sk": "OUTPUT#2026-11-02#daily",
        "public_summary": DISCLOSURE,
        "status": "pending",
        "move": "reply",
        "coach_id": "mind_coach",
        "created_at": "2026-11-02T12:00:00+00:00",
        "confidence": 0.6,
        "themes": ["notebook"],
        "state": "dark days",
        "lines": [{"coach_id": "sleep_coach", "move": "reply", "text": DISCLOSURE}],
        "provenance": _rec("journal_presence"),
    }
    out = G.gate_item(row)
    blob = json.dumps(out)
    assert not any(p in blob for p in PHRASES) and "notebook" not in blob and "dark" not in blob
    assert "provenance" not in out and "journal_presence" not in blob
    assert out["status"] == "pending" and out["move"] == "reply" and out["coach_id"] == "mind_coach" and out["confidence"] == 0.6
    assert out["created_at"] == row["created_at"] and out["lines"][0]["coach_id"] == "sleep_coach"
    assert out[G.PUBLICATION_KEY] == {"state": "withheld", "reason": NP.PUBLIC_WITHHELD_REASON}
    assert G.withheld_count() == 1
    assert row["public_summary"] == DISCLOSURE  # the stored row is never changed


def test_a_graded_record_row_is_carried_and_withheld_at_the_wire():
    """A withheld PREDICTION# row reaches the handler unchanged (its class and counts compute
    exactly) and every copy of its words — whole, clipped, figure-masked — is emptied at the wire."""
    G = _gate()
    G.begin_request()
    claim = "If the fixture subject's writing stays dark through Friday, the notebook has gone quiet for 12 days."
    row = {"pk": "COACH#mind_coach", "sk": "PREDICTION#2026-11-02#p9", "claim_natural": claim, "status": "refuted"}
    assert G.gate_item(dict(row)) == row
    assert G.is_tainted(claim) and G.is_tainted("the notebook has gone quiet for [n] days") and G.is_tainted(claim[:40])
    assert not G.is_tainted("Deep sleep rose above 1.5 hours on four nights.")
    body = {"calls": [{"claim": claim, "n": 3, "called": f"She said: {claim[:60]}"}], "_meta": {}}
    resp = G.annotate({"statusCode": 200, "headers": {}, "body": json.dumps(body)})
    out = json.loads(resp["body"])
    # The object keeps its place and its number; its words read like no words — never marked (owner ruling 2026-11-06).
    assert out["calls"] == [{"claim": "", "n": 3, "called": ""}]
    blank = G.annotate(
        {"statusCode": 200, "headers": {}, "body": json.dumps({"calls": [{"claim": "", "n": 3, "called": ""}], "_meta": {}})}
    )
    assert json.loads(blank["body"]) == out, "a withheld object must read exactly like an object with no words"
    assert out["_meta"] == {} and resp["headers"] == {}  # owner ruling 2026-11-05: no withheld count on the wire
    strict = G.gate_item(dict(row), strict=True)
    assert strict["claim_natural"] == "" and strict["status"] == "refuted"


def test_non_narrative_partitions_pass_untouched():
    G = _gate()
    t = G.wrap(_FakeTable([{"pk": "USER#matthew#SOURCE#whoop", "sk": "DATE#2026-11-02", "note": "a free text field"}]))
    out = t.query(KeyConditionExpression="pk = :p", ExpressionAttributeValues={":p": "USER#matthew#SOURCE#whoop"})
    assert out["Items"][0]["note"] == "a free text field"


def test_a_projection_cannot_hide_the_provenance_from_the_gate():
    G = _gate()
    item = {"pk": "COACH#sleep_coach", "sk": "PREDICTION#x", "claim_natural": "Deep sleep rises.", "provenance": _rec("whoop")}
    fake = _FakeTable([item])
    t = G.wrap(fake)
    from tests.call_publication_fixtures import registered  # owner ruling 2026-11-05: a reviewed-public synthetic call

    with registered([item]):
        out = t.query(
            KeyConditionExpression="pk = :p",
            ExpressionAttributeValues={":p": "COACH#sleep_coach"},
            ProjectionExpression="#a",
            ExpressionAttributeNames={"#a": "claim_natural"},
        )
    assert "provenance" in fake.last["ProjectionExpression"] or "#npg_provenance" in fake.last["ProjectionExpression"]
    assert fake.last["ExpressionAttributeNames"]["#npg_provenance"] == "provenance"
    assert out["Items"][0]["claim_natural"] == "Deep sleep rises." and "provenance" not in out["Items"][0]


def test_the_bare_user_partition_is_gated_per_row():
    G = _gate()
    rows = [
        {"pk": "USER#matthew", "sk": "SOURCE#coach_thread#mind#2026-11-02", "position_summary": DISCLOSURE},
        {"pk": "USER#matthew", "sk": "PROFILE#v1", "display": "a profile string"},
    ]
    out = G.wrap(_FakeTable(rows)).query(KeyConditionExpression="pk = :p", ExpressionAttributeValues={":p": "USER#matthew"})["Items"]
    assert out[0]["position_summary"] == "" and out[1]["display"] == "a profile string"


def test_get_item_and_scan_are_gated_and_writes_delegate():
    G = _gate()
    row = {"pk": "USER#matthew#SOURCE#ai_analysis", "sk": "EXPERT#integrator", "analysis": DISCLOSURE}
    t = G.wrap(_FakeTable([row]))
    assert t.get_item(Key={"pk": row["pk"], "sk": row["sk"]})["Item"]["analysis"] == ""
    assert t.scan()["Items"][0]["analysis"] == ""
    assert t.put_item(Item=row) == {"put": {"Item": row}}
    assert G.wrap(t) is t


def test_a_generated_document_is_gated_by_its_own_record():
    G = _gate()
    assert G.gate_document({"text": DISCLOSURE})["text"] == ""
    assert G.gate_document({"text": "Deep sleep held.", "provenance": _rec("whoop")}) == {"text": "Deep sleep held."}


def test_annotate_serves_no_withheld_count_and_logs_it(caplog):
    """Owner ruling 2026-11-05: "Remove _meta.withheld counts from public responses." The response is
    byte-identical whether this request withheld zero, one or three private rows (vary ONLY the private
    rows); the counts go to the server log. Mutation control: a tainted STRING in the body is still
    emptied, so annotate is live, and the log line does carry the number."""
    import logging

    G = _gate()
    resp_in = {"statusCode": 200, "headers": {}, "body": json.dumps({"a": 1, "_meta": {}})}
    outs = []
    for n in (0, 1, 3):
        G.begin_request()
        for i in range(n):
            G.gate_item({"pk": "COACH#x", "sk": f"OUTPUT#{i}", "text": DISCLOSURE})
        with caplog.at_level(logging.INFO, logger="site_api"):
            caplog.clear()
            outs.append(json.dumps(G.annotate(dict(resp_in)), sort_keys=True))
        if n:
            assert f"narrative_rows={n}" in caplog.text
    assert len(set(outs)) == 1, outs
    assert "withheld" not in outs[0] and "x-narrative-withheld" not in outs[0]
    G.begin_request()
    G.gate_item({"pk": "COACH#mind_coach", "sk": "PREDICTION#2026-11-02#p1", "claim_natural": DISCLOSURE, "status": "refuted"})
    tainted = G.annotate({"statusCode": 200, "headers": {}, "body": json.dumps({"t": DISCLOSURE, "_meta": {}})})
    assert json.loads(tainted["body"])["t"] == "" and "withheld" not in json.loads(tainted["body"])["_meta"]


# ── installation guards: every public table handle is behind the chokepoint ───────────────────

# A lambdas/web module that builds its OWN DynamoDB Table and is not wrapped must be named here
# with the reason it reads no AI-written narrative. A new unwrapped handle fails this test.
UNWRAPPED_TABLE_EXEMPT = {
    "email_subscriber_lambda.py": "subscriber records only",
    "subscriber_onboarding_lambda.py": "subscriber records only",
    "site_stats_refresh_lambda.py": "public stats counters (strava, subscribers) only",
    "ask_retrieval.py": "recall embeddings + the owner-approved chronicle only; given the wrapped table when the AI Lambda passes it",
}


def test_every_web_table_handle_is_wrapped():
    offenders = []
    for path in sorted((ROOT / "lambdas" / "web").glob("*.py")):
        src = path.read_text(encoding="utf-8")
        for m in re.finditer(r"^.*\.Table\(.*$", src, flags=re.MULTILINE):
            line = m.group(0)
            if "narrative_publication.wrap(" in line or line.lstrip().startswith("#"):
                continue
            if path.name in UNWRAPPED_TABLE_EXEMPT:
                continue
            offenders.append(f"{path.name}: {line.strip()}")
    assert not offenders, f"an unwrapped DynamoDB table in a public Lambda: {offenders}"


def test_the_public_lambdas_install_the_gate():
    for rel, needle in (
        ("lambdas/web/site_api_common.py", "table = narrative_publication.wrap(dynamodb.Table(TABLE_NAME))"),
        ("lambdas/web/site_api_ai_lambda.py", "table = narrative_publication.wrap(dynamodb.Table(TABLE_NAME), strict=True)"),
        ("lambdas/web/recap_card_lambda.py", "_table = narrative_publication.wrap(_ddb.Table(TABLE_NAME), strict=True)"),
    ):
        assert needle in (ROOT / rel).read_text(encoding="utf-8"), rel
    handler = (ROOT / "lambdas/web/site_api_lambda.py").read_text(encoding="utf-8")
    assert "narrative_publication.begin_request()" in handler
    assert "return guard_api_response(narrative_publication.annotate(result), logger)" in handler


def test_generated_coach_artifacts_are_gated_where_read():
    """An S3 artifact is outside the table chokepoint: every web function that loads a
    generated/coach_* document must pass it through gate_document."""
    offenders = []
    for path in sorted((ROOT / "lambdas" / "web").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            body = ast.get_source_segment(path.read_text(encoding="utf-8"), fn) or ""
            if re.search(r"[\"']generated/coach_", body) and "gate_document" not in body:
                offenders.append(f"{path.name}:{fn.name}")
    assert not offenders, offenders


# ── producers stamp provenance ───────────────────────────────────────────────────────────────


def test_the_lead_read_is_stamped_from_its_cited_facts():
    from coach import lead_daily_read

    cited = [
        {"metric": "hrv", "value": "50", "as_of": "2026-11-02", "source_field": "whoop.hrv"},
        {"metric": "weight", "value": "250.0", "as_of": "2026-11-02", "source_field": "withings.weight_lbs"},
        {"metric": "met", "value": "yes", "as_of": "2026-11-02", "source_field": "macrofactor.total_protein_g vs profile.protein_floor_g"},
    ]
    rec = lead_daily_read.provenance_for(cited)
    assert set(rec["families"]) == {"whoop", "withings", "macrofactor", "experiments", "persona"}
    assert NP.is_publishable(rec)


def test_a_moves_day_built_with_journal_facts_is_private():
    from coach import coach_moves

    sheet = {"facts": [{"key": "journal.days_since", "value": "3", "source": "/api/character pillars[mind].absence"}], "absent": []}
    ok, reason = NP.eligibility(coach_moves.provenance_for(sheet, {}))
    assert (ok, reason) == (False, NP.R_PRIVATE)


def test_a_moves_day_whose_context_positions_are_unrecorded_is_withheld():
    from coach import coach_moves

    sheet = {"facts": [{"key": "withings.weight_lbs", "value": "250"}], "absent": []}
    inputs = {"positions": {"sleep_coach": {"text": "x", "as_of": "2026-11-02"}}, "graded": [], "yesterday": []}
    assert NP.eligibility(coach_moves.provenance_for(sheet, inputs))[1] == NP.R_UNKNOWN
    inputs["positions"]["sleep_coach"]["provenance"] = _rec("whoop")
    assert NP.is_publishable(coach_moves.provenance_for(sheet, inputs))


# premerge-gate: owner ruling 2026-11-03: a route walk of every /api/* GET handler — no public route serves AI narrative whose provenance is private or unrecorded (synthetic paraphrased disclosures), and the ungated code leaks
