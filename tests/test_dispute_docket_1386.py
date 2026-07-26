"""tests/test_dispute_docket_1386.py — The Dispute Docket (#1386), offline.

No moto, no real AWS, no Bedrock (repo convention). The FakeTable evaluates the
real boto3 Key condition objects (pattern from test_coach_memoir_lambda.py) and
honors put_item's ConditionExpression — the throttle IS a conditional put, so it
must be genuinely exercised, not stubbed.

Acceptance criteria pinned here (one test class per AC):
  AC1  docket entries open ONLY on machine-checkable divergences (metric /
       threshold / date frozen at open); everything else stays narrative.
  AC2  resolution is deterministic on the criterion date; BOTH coaches'
       Brier/track records update; NO LLM anywhere in the verdict path
       (ADR-105 — proven by poisoning bedrock_client and running the resolver).
  AC3  the loser's COACH# memory records the concession VERBATIM and the
       stance grounding a future read reasons from cites it (grounding-gate:
       the concession's numbers enter the allow-list via the message itself).
  AC4  the public docket surface lists open positions with stakes + resolved
       history, losses in the SAME shape as wins; graceful-empty 200.
  AC5  the ≤1-dispute/week cap is retired; the replacement throttle is one
       open docket per coach-pair per topic (+ MAX_AIRINGS_PER_RUN cost bound).
"""

import os
import sys
from decimal import Decimal

os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "coach"))

import coach_prediction_evaluator as evaluator  # noqa: E402
import dispute_docket as dd  # noqa: E402
import pytest  # noqa: E402
from boto3.dynamodb.conditions import AttributeBase  # noqa: E402
from botocore.exceptions import ClientError  # noqa: E402

# ── FakeTable: evaluates real Key conditions + honors the conditional put ────


def _resolve(v, item):
    return item.get(v.name) if isinstance(v, AttributeBase) else v


def _eval_cond(cond, item) -> bool:
    op = cond.expression_operator
    vals = cond._values
    if op == "AND":
        return all(_eval_cond(c, item) for c in vals)
    attr = vals[0]
    name = attr.name if isinstance(attr, AttributeBase) else attr
    actual = item.get(name)
    if op == "=":
        return actual == _resolve(vals[1], item)
    if op == "begins_with":
        return isinstance(actual, str) and actual.startswith(_resolve(vals[1], item))
    raise NotImplementedError(f"unsupported operator {op!r}")


class FakeTable:
    def __init__(self):
        self.store = {}
        self.deleted = []

    def put_item(self, Item, ConditionExpression=None, **kw):
        key = (Item["pk"], Item["sk"])
        if ConditionExpression is not None and key in self.store:
            raise ClientError({"Error": {"Code": "ConditionalCheckFailedException"}}, "PutItem")
        self.store[key] = dict(Item)
        return {}

    def get_item(self, Key):
        it = self.store.get((Key["pk"], Key["sk"]))
        return {"Item": dict(it)} if it else {}

    def delete_item(self, Key):
        self.deleted.append((Key["pk"], Key["sk"]))
        self.store.pop((Key["pk"], Key["sk"]), None)
        return {}

    def update_item(self, **kw):
        return {}

    def query(self, **kw):
        cond = kw["KeyConditionExpression"]
        forward = kw.get("ScanIndexForward", True)
        matched = [dict(v) for v in self.store.values() if _eval_cond(cond, v)]
        matched.sort(key=lambda it: it.get("sk", ""), reverse=not forward)
        limit = kw.get("Limit")
        return {"Items": matched[:limit] if limit else matched}


@pytest.fixture()
def fake_table(monkeypatch):
    t = FakeTable()
    monkeypatch.setattr(dd, "table", t)
    return t


def _criterion(**over):
    base = {
        "metric": "weight_lbs_7day_avg",
        "condition": "lte",
        "threshold": 242.0,
        "resolution_days": 14,
        "sides": {"physical_coach": True, "training_coach": False},
    }
    base.update(over)
    return base


OPEN_DATE = "2026-07-20"


# ═════════════════════════════════════════════════════════════════════════════
# AC1 — only machine-checkable divergences enter the docket
# ═════════════════════════════════════════════════════════════════════════════


class TestAC1MachineCheckableGate:
    def test_valid_criterion_normalizes_and_freezes_the_date(self):
        ok, reason, norm = dd.validate_criterion(_criterion(), "physical_coach", "training_coach", OPEN_DATE)
        assert ok, reason
        assert norm["metric"] == "weight_lbs_7day_avg"
        assert norm["threshold"] == 242.0
        # resolution_days → ONE immutable ISO date, frozen at open
        assert norm["resolution_date"] == "2026-08-03"

    def test_explicit_resolution_date_is_honored(self):
        ok, _, norm = dd.validate_criterion(
            _criterion(resolution_date="2026-08-10", resolution_days=None), "physical_coach", "training_coach", OPEN_DATE
        )
        assert ok
        assert norm["resolution_date"] == "2026-08-10"

    @pytest.mark.parametrize(
        "broken, why",
        [
            (None, "no structured criterion at all"),
            ("weight goes down", "criterion is prose, not structure"),
            (_criterion(metric="vibes_index"), "metric outside the evaluator's source map"),
            (_criterion(condition="trends_down"), "condition the evaluator cannot grade"),
            (_criterion(threshold="lower"), "non-numeric threshold"),
            (_criterion(resolution_days=None), "no date and no day count — nothing frozen"),
            (_criterion(resolution_days=1), "horizon below the minimum"),
            (_criterion(resolution_days=400), "horizon beyond the maximum"),
            (_criterion(sides={"physical_coach": True, "training_coach": True}), "same side — no divergence"),
            (_criterion(sides={"physical_coach": True}), "sides don't name both coaches"),
            (_criterion(sides={"physical_coach": True, "sleep_coach": False}), "sides name the wrong coach"),
        ],
    )
    def test_non_resolvable_disagreements_cannot_enter(self, broken, why):
        ok, reason, norm = dd.validate_criterion(broken, "physical_coach", "training_coach", OPEN_DATE)
        assert not ok, f"should have been rejected: {why}"
        assert norm is None
        assert reason

    def test_narrative_disagreement_stays_out_of_the_docket(self, fake_table):
        result = dd.open_from_disagreements(
            [
                {
                    "topic": "whether motivation is the limiter",
                    "coaches": ["mind_coach", "training_coach"],
                    "positions": {"mind_coach": "it is", "training_coach": "it is not"},
                    "resolution_criterion": None,  # not machine-checkable
                }
            ],
            OPEN_DATE,
        )
        assert result["opened"] == []
        assert len(result["skipped"]) == 1
        assert not any(pk == dd.DOCKET_PK for pk, _ in fake_table.store)

    def test_template_placeholder_coach_ids_are_dropped_not_docketed(self, fake_table):
        # #1797: coach_ensemble_digest's own output-schema spec shows placeholder
        # ids ("coach_a"/"coach_b") as its example — a model echoing the template
        # must not be able to open a real docket between coaches that don't exist.
        result = dd.open_from_disagreements(
            [
                {
                    "topic": "placeholder echo",
                    "coaches": ["coach_a", "coach_b"],
                    "positions": {"coach_a": "x", "coach_b": "y"},
                    "resolution_criterion": _criterion(sides={"coach_a": True, "coach_b": False}),
                }
            ],
            OPEN_DATE,
        )
        assert result["opened"] == []
        assert len(result["skipped"]) == 1
        assert "non-member" in result["skipped"][0]["reason"]
        assert not any(pk == dd.DOCKET_PK for pk, _ in fake_table.store)

    def test_display_name_coach_id_is_dropped_not_docketed(self, fake_table):
        # A bare/display name ("Sleep Coach") instead of the canonical id is the
        # same failure class — membership, not just placeholder-echo, is the gate.
        result = dd.open_from_disagreements(
            [
                {
                    "topic": "display name echo",
                    "coaches": ["Sleep Coach", "training_coach"],
                    "positions": {"Sleep Coach": "x", "training_coach": "y"},
                    "resolution_criterion": _criterion(sides={"Sleep Coach": True, "training_coach": False}),
                }
            ],
            OPEN_DATE,
        )
        assert result["opened"] == []
        assert len(result["skipped"]) == 1
        assert not any(pk == dd.DOCKET_PK for pk, _ in fake_table.store)

    def test_checkable_divergence_opens_with_frozen_stakes(self, fake_table):
        result = dd.open_from_disagreements(
            [
                {
                    "topic": "Weight trajectory through early August",
                    "coaches": ["physical_coach", "training_coach"],
                    "positions": {
                        "physical_coach": "The 7-day average breaks 242 by Aug 3.",
                        "training_coach": "It stalls above 242 without more volume.",
                    },
                    "resolution_criterion": _criterion(),
                    "sk": "ACTIVE#weight-trajectory",
                }
            ],
            OPEN_DATE,
        )
        assert len(result["opened"]) == 1
        (key,) = [k for k in fake_table.store if k[0] == dd.DOCKET_PK]
        item = fake_table.store[key]
        assert item["sk"].startswith("OPEN#")
        assert item["resolution_date"] == "2026-08-03"  # frozen
        assert item["claims"]["physical_coach"].startswith("The 7-day average")
        # each side's stake is present: domain Brier (None honest pre-grading) + confidence
        for cid in ("physical_coach", "training_coach"):
            stake = item["stakes"][cid]
            assert "brier" in stake and "confidence" in stake and stake["subdomain"] == "weight"


# ═════════════════════════════════════════════════════════════════════════════
# AC2 — deterministic resolution; both track records update; NO LLM (ADR-105)
# ═════════════════════════════════════════════════════════════════════════════


def _open_docket_item(resolution_date="2026-08-03"):
    return {
        "pk": dd.DOCKET_PK,
        "sk": "OPEN#physical_coach__training_coach#weight-trajectory",
        "record_type": "dispute_docket",
        "status": "open",
        "topic": "Weight trajectory through early August",
        "topic_slug": "weight-trajectory",
        "coach_a": "physical_coach",
        "coach_b": "training_coach",
        "claims": {
            "physical_coach": "The 7-day average breaks 242 by Aug 3.",
            "training_coach": "It stalls above 242 without more volume.",
        },
        "criterion": {
            "metric": "weight_lbs_7day_avg",
            "condition": "lte",
            "threshold": 242.0,
            "description": "weight_lbs_7day_avg <= 242 on 2026-08-03",
        },
        "sides": {"physical_coach": True, "training_coach": False},
        "resolution_date": resolution_date,
        "opened_date": OPEN_DATE,
        "opened_at": "2026-07-20T18:00:00+00:00",
        "stakes": {
            "physical_coach": {"brier": 0.18, "brier_n": 11, "confidence": 0.7, "subdomain": "weight"},
            "training_coach": {"brier": 0.31, "brier_n": 9, "confidence": 0.55, "subdomain": "weight"},
        },
        "subdomain": "weight",
    }


class _PoisonedBedrock:
    def invoke(self, *a, **k):  # pragma: no cover - reaching this IS the failure
        raise AssertionError("LLM invoked inside the docket verdict path (ADR-105 violation)")

    def __getattr__(self, name):
        raise AssertionError(f"bedrock_client.{name} touched inside the verdict path (ADR-105 violation)")


@pytest.fixture()
def resolved_run(fake_table, monkeypatch):
    """Seed one due docket, poison the LLM, resolve deterministically."""
    fake_table.put_item(Item=_open_docket_item())
    confidence_updates = []
    monkeypatch.setattr(evaluator, "_resolve_metric_value", lambda metric, cache, end: 241.2)
    monkeypatch.setattr(evaluator, "_update_bayesian_confidence", lambda cid, sub, kind: confidence_updates.append((cid, sub, kind)))
    monkeypatch.setitem(sys.modules, "bedrock_client", _PoisonedBedrock())
    summary = dd.resolve_due("2026-08-03")
    return fake_table, summary, confidence_updates


class TestAC2DeterministicResolution:
    def test_verdict_on_the_criterion_date_with_no_llm(self, resolved_run):
        _t, summary, _c = resolved_run  # the poisoned bedrock_client never raised
        assert len(summary["resolved"]) == 1
        verdict = summary["resolved"][0]
        assert verdict["winner"] == "physical_coach"  # 241.2 <= 242 — the 'holds' side
        assert verdict["loser"] == "training_coach"
        assert verdict["actual_value"] == 241.2

    def test_not_due_dockets_are_untouched(self, fake_table, monkeypatch):
        fake_table.put_item(Item=_open_docket_item(resolution_date="2026-08-03"))
        monkeypatch.setattr(evaluator, "_resolve_metric_value", lambda *a: 241.2)
        summary = dd.resolve_due("2026-08-01")  # before the frozen date
        assert summary["resolved"] == [] and summary["voided"] == []
        assert any(sk.startswith("OPEN#") for _pk, sk in fake_table.store)

    def test_both_coaches_track_records_update(self, resolved_run):
        table, _s, confidence_updates = resolved_run
        # LEARNING# rows: winner confirmed, loser refuted — the public
        # _track_record and the stance grounding both read exactly these.
        win = [v for (pk, sk), v in table.store.items() if pk == "COACH#physical_coach" and sk.startswith("LEARNING#")]
        loss = [v for (pk, sk), v in table.store.items() if pk == "COACH#training_coach" and sk.startswith("LEARNING#")]
        assert win and win[0]["status"] == "confirmed" and win[0]["channel"] == "data"
        assert loss and loss[0]["status"] == "refuted" and loss[0]["record_type"] == "docket_concession"
        # resolved PREDICTION# rows feed the Brier scoreboard (calibration_core)
        import calibration_core

        for cid, outcome in (("physical_coach", 1), ("training_coach", 0)):
            preds = [v for (pk, sk), v in table.store.items() if pk == f"COACH#{cid}" and sk.startswith("PREDICTION#docket-")]
            assert len(preds) == 1
            pairs = calibration_core.pairs_from_prediction_records(preds)
            assert len(pairs) == 1 and pairs[0][1] == outcome
        # Bayesian confidence: the evaluator's own update path, both coaches
        assert ("physical_coach", "weight", "success") in confidence_updates
        assert ("training_coach", "weight", "failure") in confidence_updates

    def test_docket_moves_open_to_resolved(self, resolved_run):
        table, _s, _c = resolved_run
        assert ("ENSEMBLE#docket", "OPEN#physical_coach__training_coach#weight-trajectory") in table.deleted
        resolved = [v for (pk, sk), v in table.store.items() if pk == dd.DOCKET_PK and sk.startswith("RESOLVED#")]
        assert len(resolved) == 1
        assert resolved[0]["winner"] == "physical_coach"
        assert resolved[0]["concession"]  # the loss ships WITH the entry — no burying

    def test_no_data_waits_then_voids_honestly(self, fake_table, monkeypatch):
        fake_table.put_item(Item=_open_docket_item(resolution_date="2026-08-03"))
        monkeypatch.setattr(evaluator, "_resolve_metric_value", lambda *a: None)
        called = []
        monkeypatch.setattr(evaluator, "_update_bayesian_confidence", lambda *a: called.append(a))
        # inside the grace window: still open, nobody graded
        summary = dd.resolve_due("2026-08-05")
        assert summary["waiting_for_data"] and not summary["voided"] and not called
        # grace exhausted: an honest void — still no track-record mutation
        summary = dd.resolve_due("2026-08-11")
        assert len(summary["voided"]) == 1 and not called
        voided = [v for (pk, sk), v in fake_table.store.items() if sk.startswith("RESOLVED#")]
        assert voided[0]["verdict"]["outcome"] == "void_no_data"

    def test_verdict_module_never_imports_an_llm(self):
        src = open(os.path.join(_REPO, "lambdas", "dispute_docket.py")).read()
        for forbidden in ("bedrock_client", "ai_calls", "invoke_model", "anthropic"):
            assert forbidden not in src, f"dispute_docket.py references {forbidden!r} — the verdict path must stay LLM-free"


# ═════════════════════════════════════════════════════════════════════════════
# AC3 — the concession is memory, and future reads must cite it
# ═════════════════════════════════════════════════════════════════════════════


class TestAC3ConcessionMemory:
    def test_concession_recorded_verbatim_on_the_losers_partition(self, resolved_run):
        table, summary, _c = resolved_run
        loss = [v for (pk, sk), v in table.store.items() if pk == "COACH#training_coach" and sk.startswith("LEARNING#")][0]
        resolved_entry = [v for (pk, sk), v in table.store.items() if str(sk).startswith("RESOLVED#")][0]
        # VERBATIM: the docket's concession and the memory row are byte-identical
        assert loss["concession"] == resolved_entry["concession"]
        assert 'My recorded claim: "It stalls above 242 without more volume."' in loss["concession"]
        assert "CONCESSION (2026-08-03)" in loss["concession"]
        # data-derived, never ADR-141 conversation-private
        assert loss["channel"] == "data"

    def test_stance_grounding_carries_the_concession_and_the_citation_rule(self, resolved_run):
        table, _s, _c = resolved_run
        import coach_history_summarizer as chs

        loss_rows = [v for (pk, sk), v in table.store.items() if pk == "COACH#training_coach" and sk.startswith("LEARNING#")]
        track = chs._summarize_track_record(loss_rows, [])
        # the concession is a standing, citable evidence class — verbatim
        standing = track["standing_concessions"]
        assert standing["count"] == 1
        assert standing["recent"][0]["concession"] == loss_rows[0]["concession"]
        # ...and it counts as a refuted verdict in the same tally (skin in the game)
        assert track["refuted"] == 1
        message = chs._build_stance_message("training_coach", {"summary": ""}, track, None)
        import json

        # a read touching the topic sees the concession VERBATIM (the grounding
        # block is JSON-embedded, so compare in its JSON-escaped form)
        assert json.dumps(loss_rows[0]["concession"])[1:-1] in message
        assert "MUST cite the concession" in message  # and is instructed to cite, not relitigate

    def test_grounding_gate_allows_citing_the_concessions_numbers(self, resolved_run):
        """The ADR-104 gate builds its allow-list from the stance grounding
        message — because the concession is IN the message, a stance that cites
        its numbers (242, 241.2) is grounded; an invented number still isn't."""
        table, _s, _c = resolved_run
        import coach_history_summarizer as chs
        from grounded_generation import allowed_numbers, grounding_findings

        loss_rows = [v for (pk, sk), v in table.store.items() if pk == "COACH#training_coach" and sk.startswith("LEARNING#")]
        track = chs._summarize_track_record(loss_rows, [])
        message = chs._build_stance_message("training_coach", {"summary": ""}, track, None)
        allowed = allowed_numbers(message)
        citing = "I conceded the weight dispute: the 7-day average came in at 241.2 against my 242 line."
        assert grounding_findings(citing, allowed=allowed) == []
        invented = "The 7-day average came in at 217.4."
        assert grounding_findings(invented, allowed=allowed) != []


# ═════════════════════════════════════════════════════════════════════════════
# AC4 — the public surface: stakes visible, losses with the same dignity
# ═════════════════════════════════════════════════════════════════════════════


class TestAC4PublicSurface:
    @pytest.fixture()
    def api(self, monkeypatch):
        sys.path.insert(0, os.path.join(_REPO, "lambdas", "web"))
        from web import site_api_coach as sac

        t = FakeTable()
        monkeypatch.setattr(sac, "table", t)
        return sac, t

    @staticmethod
    def _body(resp):
        import json

        assert resp["statusCode"] == 200
        return json.loads(resp["body"])

    def test_graceful_empty_before_the_first_docket(self, api):
        sac, _t = api
        body = self._body(sac.handle_coach_docket({}))
        assert body["open"] == [] and body["resolved"] == []
        assert body["counts"] == {"open": 0, "resolved": 0}

    def test_open_positions_render_with_stakes(self, api, fake_table, monkeypatch):
        sac, t = api
        t.put_item(Item=_open_docket_item())
        body = self._body(sac.handle_coach_docket({}))
        assert body["counts"]["open"] == 1
        entry = body["open"][0]
        assert entry["stakes"]["physical_coach"]["brier"] == 0.18
        assert entry["stakes"]["training_coach"]["brier"] == 0.31
        assert entry["resolution_date"] == "2026-08-03"
        assert entry["claims"]["training_coach"]

    def test_docket_privacy_violation_is_withheld_wholesale_and_counted(self, api):
        # #1795: the same standing content-absolute filter the coach dossier
        # applies to `find_dossier_violations` — reused here, not forked — must
        # withhold an entry whose claim trips it. Genotype pattern reused
        # verbatim from tests/test_coach_dossier.py's own seeded-violation
        # vocabulary (PRE-13 / DATA_GOVERNANCE: no genotype strings publicly).
        import json

        sac, t = api
        item = _open_docket_item()
        item["claims"]["physical_coach"] = "the rs429358 variant explains the lipid response"
        t.put_item(Item=item)
        body = self._body(sac.handle_coach_docket({}))
        assert body["open"] == []
        assert body["counts"]["open"] == 0
        assert body["withheld"] == 1
        assert "rs429358" not in json.dumps(body)

    def test_docket_resolved_concession_violation_is_withheld_and_counted(self, api):
        # Same fail-closed floor on the RESOLVED side — a violating concession
        # (also LLM/coach-authored verbatim text) must not slip through just
        # because it's on the winner/loser branch instead of the open claim.
        import json

        sac, t = api
        item = _open_docket_item()
        item.update(
            {
                "pk": dd.DOCKET_PK,
                "sk": "RESOLVED#2026-08-03#physical_coach__training_coach#weight-trajectory",
                "status": "resolved",
                "winner": "physical_coach",
                "loser": "training_coach",
                "resolved_date": "2026-08-03",
                "verdict": {"winner": "physical_coach", "loser": "training_coach", "actual_value": 241.2},
                "concession": "CONCESSION — the rs429358 variant explains the lipid response",
            }
        )
        t.put_item(Item=item)
        body = self._body(sac.handle_coach_docket({}))
        assert body["resolved"] == []
        assert body["withheld"] == 1
        assert "rs429358" not in json.dumps(body)

    def test_lost_disputes_render_in_the_same_shape_as_wins(self, api, monkeypatch):
        sac, t = api
        # resolve a seeded docket for real, then read the public surface
        monkeypatch.setattr(dd, "table", t)
        t.put_item(Item=_open_docket_item())
        monkeypatch.setattr(evaluator, "_resolve_metric_value", lambda *a: 241.2)
        monkeypatch.setattr(evaluator, "_update_bayesian_confidence", lambda *a: None)
        dd.resolve_due("2026-08-03")
        body = self._body(sac.handle_coach_docket({}))
        assert body["counts"] == {"open": 0, "resolved": 1}
        entry = body["resolved"][0]
        # winner AND loser named side by side; the concession ships in the payload
        assert entry["winner"] == "physical_coach" and entry["loser"] == "training_coach"
        assert entry["concession"] and "CONCESSION" in entry["concession"]
        # the losing side's claim + stake render from the SAME fields as the winner's
        assert set(entry["claims"]) == {"physical_coach", "training_coach"}
        assert set(entry["stakes"]) == {"physical_coach", "training_coach"}

    def test_route_registered_end_to_end(self):
        from web import site_api_lambda as L

        assert "handle_coach_docket" in dir(L)


# ═════════════════════════════════════════════════════════════════════════════
# AC5 — the weekly cap is gone; the throttle is structural
# ═════════════════════════════════════════════════════════════════════════════


class TestAC5ThrottleReplacesWeeklyCap:
    def test_one_open_docket_per_pair_per_topic(self, fake_table):
        ok, _, norm = dd.validate_criterion(_criterion(), "physical_coach", "training_coach", OPEN_DATE)
        assert ok
        first = dd.open_docket("Weight trajectory", "physical_coach", "training_coach", {}, norm, OPEN_DATE)
        assert first["opened"]
        second = dd.open_docket("Weight trajectory", "training_coach", "physical_coach", {}, norm, OPEN_DATE)
        assert not second["opened"] and "throttled" in second["reason"]
        # a DIFFERENT topic for the same pair is NOT throttled
        third = dd.open_docket("Protein floor", "physical_coach", "training_coach", {}, norm, OPEN_DATE)
        assert third["opened"]

    def test_weekly_cap_is_retired_in_the_dialogue_lambda(self, monkeypatch):
        import inter_coach_dialogue_lambda as icd

        # the literal weekly-cap short-circuit is gone from the source
        src = open(os.path.join(_REPO, "lambdas", "coach", "inter_coach_dialogue_lambda.py")).read()
        assert "already_aired" not in src
        assert icd.MAX_AIRINGS_PER_RUN >= 2  # more than one dispute can air

        # behaviorally: two qualifying topics both air in ONE run, even though a
        # THREAD# for this week already exists (the old cap would have skipped).
        t = FakeTable()
        this_week = icd.iso_week()
        t.put_item(Item={"pk": icd.DISPUTE_PK, "sk": f"THREAD#{this_week}#already-there", "week": this_week})
        for slug in ("topic-a", "topic-b", "topic-c"):
            t.put_item(
                Item={
                    "pk": icd.DISAGREEMENTS_PK,
                    "sk": f"ACTIVE#{slug}",
                    "topic": slug,
                    "coaches": ["sleep_coach", "training_coach"],
                    "positions": {"sleep_coach": "yes", "training_coach": "no"},
                    "cycle_count": 3,
                }
            )
        monkeypatch.setattr(icd, "table", t)
        monkeypatch.setattr(icd, "load_influence_weights", lambda: {})
        import budget_guard

        monkeypatch.setattr(budget_guard, "current_tier", lambda: 0)
        aired = []
        monkeypatch.setattr(icd, "_air_one", lambda pick, week: aired.append(pick["topic"]["sk"]) or {"sk": pick["topic"]["sk"]})
        result = icd.lambda_handler({}, None)
        assert result.get("skipped") is None
        # the cost bound (not the calendar) is the only ceiling on airings
        assert len(aired) == icd.MAX_AIRINGS_PER_RUN
        assert len(set(aired)) == len(aired)  # distinct topics, no double-air


# ── registry hygiene: the new partition is classified + wiped ─────────────────


class TestPartitionRegistry:
    def test_docket_partition_is_experiment_scoped(self):
        import phase_taxonomy as taxonomy

        assert taxonomy.classify("ENSEMBLE#docket", "OPEN#a__b#topic") == taxonomy.EXPERIMENT_SCOPED

    def test_docket_subdomains_map_to_evaluator_domains(self):
        # every subdomain the docket can stamp must be one the evaluator's
        # window/confidence machinery understands (silent 'training' fallback
        # is the #813 bug class this pins against)
        for metric, sub in dd._METRIC_SUBDOMAIN.items():
            assert sub in evaluator.SUBDOMAIN_TO_DOMAIN, f"{metric} → {sub} missing from SUBDOMAIN_TO_DOMAIN"


# ═════════════════════════════════════════════════════════════════════════════
# ADR-077 (#1788): a tombstoned CONFIDENCE# row must never be frozen into a stake
# ═════════════════════════════════════════════════════════════════════════════


class TestConfidenceAtOpenTombstoneGuard:
    """774631fb closed this hole on the two CONFIDENCE# WRITE paths; this pins the
    same guard on dispute_docket's READ (get_item bypasses query-level phase
    filters entirely, so a wiped prior-cycle mean would otherwise freeze into the
    public docket stake at open)."""

    def test_tombstoned_row_falls_back_to_uninformed_prior(self, fake_table):
        fake_table.put_item(
            Item={
                "pk": "COACH#sleep_coach",
                "sk": "CONFIDENCE#sleep_quality",
                "mean_confidence": Decimal("0.91"),  # a wiped prior-cycle mean
                "tombstone": True,
                "tombstoned_reason": "experiment_restart_2026-07-27",
            }
        )
        assert dd._confidence_at_open("sleep_coach", "sleep_quality") == 0.5

    def test_current_cycle_row_is_used_normally(self, fake_table):
        fake_table.put_item(Item={"pk": "COACH#sleep_coach", "sk": "CONFIDENCE#sleep_quality", "mean_confidence": Decimal("0.82")})
        assert dd._confidence_at_open("sleep_coach", "sleep_quality") == 0.82

    def test_absent_row_is_the_uninformed_prior(self, fake_table):
        assert dd._confidence_at_open("sleep_coach", "never_written") == 0.5

    def test_stake_built_at_open_never_carries_a_tombstoned_mean(self, fake_table):
        """End-to-end through build_stake — the exact call site open_docket uses."""
        fake_table.put_item(
            Item={"pk": "COACH#physical_coach", "sk": "CONFIDENCE#weight", "mean_confidence": Decimal("0.99"), "tombstone": True}
        )
        stake = dd.build_stake("physical_coach", "weight")
        assert stake["confidence"] == 0.5
