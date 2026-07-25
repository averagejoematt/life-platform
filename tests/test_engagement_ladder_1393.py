"""tests/test_engagement_ladder_1393.py — the Engagement Ladder (#1393, epic #1366).

Proves the four acceptance criteria against the actual code (offline, fakes only):

  AC1  ladder state derives from the existing subscriber token + localStorage; no new
       auth/identity, no new PII stored server-side.
  AC2  the predict-week participation surface is information-only — no loss framing.
  AC3  Replicator wires to a self-cert; Contributor to verified published findings.
  AC4  public rung counts carry .provenance and are derived from data, never hand-
       maintained.
"""

import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

from web import site_api_social as social  # noqa: E402

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_JS = os.path.join(_REPO, "site", "assets", "js", "engagement_ladder.js")


def _event(body="{}"):
    return {
        "body": body,
        "headers": {"x-forwarded-for": "9.9.9.9"},
        "requestContext": {"http": {"sourceIp": "9.9.9.9"}},
    }


class _FakeTable:
    def __init__(self, sub_count=0, pred_items=None, repl_item=None):
        self.sub_count = sub_count
        self.pred_items = pred_items or []
        self.repl_item = repl_item
        self.puts = []
        self.updates = []
        self.put_should_fail = False

    def query(self, **kw):
        if kw.get("Select") == "COUNT":
            return {"Count": self.sub_count}
        return {"Items": self.pred_items}

    def get_item(self, **kw):
        return {"Item": self.repl_item} if self.repl_item else {}

    def put_item(self, **kw):
        self.puts.append(kw)
        if self.put_should_fail:
            raise Exception("ConditionalCheckFailedException")
        return {}

    def update_item(self, **kw):
        self.updates.append(kw)
        return {}


def _body(resp):
    assert resp["statusCode"] == 200, resp
    return json.loads(resp["body"])


# ── AC4: public counts + provenance, derived from data ────────────────────────────


def test_ladder_counts_shape_and_provenance(monkeypatch):
    ft = _FakeTable(
        sub_count=42,
        pred_items=[
            {"sk": "PRED#aaaa#2026-W30#weight"},
            {"sk": "PRED#aaaa#2026-W31#weight"},  # same person, different week
            {"sk": "PRED#bbbb#2026-W31#weight"},
        ],
        repl_item={"cert_count": 3},
    )
    monkeypatch.setattr(social, "table", ft)
    monkeypatch.setattr(social, "_load_s3_json", lambda k, n: {})
    d = _body(social.handle_ladder_counts())

    assert d["order"] == ["reader", "subscriber", "predictor", "replicator", "contributor"]
    rungs = d["rungs"]
    assert set(rungs) == set(d["order"])

    # every rung carries a provenance block with source/method/note
    for k, r in rungs.items():
        assert set(("source", "method", "note")) <= set(r["provenance"]), k

    # reader = the anonymous, uncounted base
    assert rungs["reader"]["count"] is None and rungs["reader"]["countable"] is False
    assert rungs["reader"]["provenance"]["source"] == "none"

    # counts are DERIVED FROM DATA (not hand-maintained): each countable rung names a
    # concrete data source and reflects the fake's data.
    assert rungs["subscriber"]["count"] == 42
    assert rungs["predictor"]["count"] == 2  # two DISTINCT ip_hashes
    assert rungs["replicator"]["count"] == 3
    for k in ("subscriber", "predictor", "replicator", "contributor"):
        assert rungs[k]["countable"] is True
        assert isinstance(rungs[k]["count"], int)
        assert rungs[k]["provenance"]["source"] not in ("", "none")


def test_predictor_count_is_distinct_participants(monkeypatch):
    ft = _FakeTable(pred_items=[{"sk": f"PRED#cccc#2026-W{w}#weight"} for w in range(30, 40)])
    monkeypatch.setattr(social, "table", ft)
    monkeypatch.setattr(social, "_load_s3_json", lambda k, n: {})
    d = _body(social.handle_ladder_counts())
    assert d["rungs"]["predictor"]["count"] == 1  # ten predictions, ONE person


# ── AC3 + no-new-PII: Replicator self-cert ────────────────────────────────────────


def test_replicate_certify_writes_aggregate_and_stores_no_pii(monkeypatch):
    ft = _FakeTable()
    monkeypatch.setattr(social, "table", ft)
    d = _body(social._handle_replicate_certify(_event()))
    assert d["certified"] is True and d["counted"] is True

    # dedup row on the shared VOTES#rate_limit partition, REPL# prefixed, ip_hash only
    assert len(ft.puts) == 1
    item = ft.puts[0]["Item"]
    assert item["pk"] == "VOTES#rate_limit" and item["sk"].startswith("REPL#")
    assert "ttl" in item
    # NO PII: no email / identity / raw ip in the stored row
    assert set(item) <= {"pk", "sk", "voted_at", "ttl"}
    assert "9.9.9.9" not in item["sk"]  # the raw IP is hashed, never stored

    # aggregate counter bumped on the VOTES#ladder_replicator partition
    assert len(ft.updates) == 1
    assert ft.updates[0]["Key"]["pk"] == "VOTES#ladder_replicator"


def test_replicate_certify_is_idempotent_per_source(monkeypatch):
    ft = _FakeTable()
    ft.put_should_fail = True  # dedup row already exists (ConditionalCheckFailed)
    monkeypatch.setattr(social, "table", ft)
    d = _body(social._handle_replicate_certify(_event()))
    assert d["certified"] is True and d["counted"] is False
    assert len(ft.updates) == 0  # a re-cert must NOT double-count


# ── AC3: Contributor wires to verified published findings, opt-in credit only ─────


def test_contributor_count_from_published_index_optin_credit_only(monkeypatch):
    index = {
        "published": [
            {"id": "abc", "credit_opt_in": True, "credit_name": "Dana R."},
            {"id": "def", "credit_opt_in": False, "credit_name": "should-not-appear"},
            {"id": "ghi"},  # no credit at all
        ]
    }
    ft = _FakeTable()
    monkeypatch.setattr(social, "table", ft)
    monkeypatch.setattr(social, "_load_s3_json", lambda k, n: index)
    d = _body(social.handle_ladder_counts())
    contrib = d["rungs"]["contributor"]
    assert contrib["count"] == 3  # every verified+published finding counts
    assert contrib["credited"] == ["Dana R."]  # ONLY the opt-in name is surfaced
    assert "should-not-appear" not in contrib["credited"]


def test_contributor_defaults_to_zero_when_nothing_published(monkeypatch):
    ft = _FakeTable()
    monkeypatch.setattr(social, "table", ft)
    monkeypatch.setattr(social, "_load_s3_json", lambda k, n: {})
    d = _body(social.handle_ladder_counts())
    assert d["rungs"]["contributor"]["count"] == 0
    assert d["rungs"]["contributor"]["credited"] == []


# ── AC1 + AC2: the client derives its rung from the EXISTING token + localStorage,
#    and the participation surface is information-only (no loss framing) ───────────


def test_ladder_js_reads_existing_token_and_localstorage_only():
    src = open(_JS, encoding="utf-8").read()
    # AC1: uses the EXISTING subscriber token + the cockpit's predict localStorage keys
    assert "lp_sub_token" in src, "must read the existing subscriber HMAC token"
    assert "ajm-predict-" in src, "must read the cockpit's predict-the-week localStorage keys"
    # no new auth/identity system: the only network calls are the read + the self-cert
    assert "verify_subscriber" not in src, "must NOT build a new auth/verify flow"
    # only the two sanctioned endpoints are called
    fetched = set(re.findall(r"\$\{API\}/([a-z_]+)", src))
    assert fetched <= {"ladder_counts", "replicate_certify"}, fetched


def test_ladder_js_participation_copy_is_sdt_safe():
    """AC2: information only — never loss-framed, no decay/penalty language."""
    src = open(_JS, encoding="utf-8").read().lower()
    banned = [
        "lose your",
        "you'll lose",
        "streak broken",
        "broke your",
        "don't break",
        "at risk",
        "expires",
        "penalty",
        "keep your streak",
        "act now",
        "hurry",
    ]
    hits = [b for b in banned if b in src]
    assert not hits, f"loss-framed / pressure copy found in engagement_ladder.js: {hits}"
