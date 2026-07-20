"""tests/test_e2e_write_paths.py — E2E regression coverage for the interactive write paths (#1438).

The only reader-facing WRITE features on averagejoematt.com — experiment/challenge vote,
follow, challenge check-in, subscribe/confirm/unsubscribe, board_question, submit_finding,
predict_week, nudge — previously had zero end-to-end coverage: unit tests called handlers
directly with stubbed internals, so a routing regression, a rate-limiter wiring break, or
a storage-shape drift was invisible until a reader hit it.

These tests drive each path END TO END through the REAL entry points:

    Function-URL event → web.site_api_lambda.lambda_handler (routing + envelope
    validation + method gate) → the real handler → the real rate_limiter module →
    stored effect → READBACK through the corresponding public GET endpoint.

against a faithful in-memory harness:
  * `E2ETable` — a mini DynamoDB engine that actually evaluates the ConditionExpression /
    UpdateExpression / KeyConditionExpression / FilterExpression grammar these paths use
    (attribute_not_exists puts, ADD counters, if_not_exists TTLs, REMOVE, string + boto3
    condition objects) — so the real `rate_limiter.check_rate_limit` and the real dedup
    rows run unmodified, not monkeypatched away.
  * `FakeS3Client` / `FakeSes` — keyed object store + send recorder.
  * Frozen clock — every `datetime.now()` / `time.time()` these modules consume is pinned
    to one instant, so rate buckets and the predict-week ISO week can never straddle a
    window boundary mid-test (no wall-clock time bombs).

Isolation (ADR-104 — test data never masquerades as real): NOTHING here touches live AWS
(conftest fakes credentials process-wide; every boto3 surface is replaced). Zero live
writes, zero real per-IP rate-limit quota consumed. Belt-and-braces, every identifier is
still unmistakably test-tagged (`e2e-test-*`, RFC-5737 TEST-NET IPs, `.e2e-invalid` mail
domain), and `test_writes_stay_inside_sanctioned_partitions` runs the full sweep and then
proves the written partition set stays inside the SEC-01 LeadingKeys allowlist parsed
from the live role policy — i.e. no write path can silently reach a data partition the
public role isn't scoped to.

Rate limiting: exercised deterministically through the real DynamoDB-backed limiter
against the harness table (the 429s below are the real code path, not stubs). The
subscribe 60/5min budget is proven by pre-seeding its atomic counter at the limit —
never by issuing 60 requests against anything real.

Gating posture (#1438 acceptance criterion 4): this file is part of the standard offline
unit suite — CI job `test` runs it on EVERY push (pre-deploy lane; a failure reds main
and fires notify-failure). It is deliberately NOT marked `deploy_critical`: per
docs/CONVENTIONS.md §4a that lane is reserved for deploy-artifact/wiring contracts, and
product-behavior regression coverage is explicitly excluded from it.
"""

from __future__ import annotations

import copy
import io
import json
import re
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

# ── Frozen clock ──────────────────────────────────────────────────────────────
# One instant for the whole harness: mid-week, mid-hour, mid-5-minute-bucket, so
# no rate-limit window or ISO-week boundary can be straddled between two calls.

_FROZEN_DT = datetime(2026, 7, 15, 12, 34, 56, tzinfo=timezone.utc)
_FROZEN_EPOCH = int(_FROZEN_DT.timestamp())


class _FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return _FROZEN_DT.astimezone(tz) if tz else _FROZEN_DT.replace(tzinfo=None)


# ── Condition-expression evaluation (string grammar) ─────────────────────────


def _resolve_name(token: str, names: dict) -> str:
    token = token.strip()
    return names.get(token, token) if token.startswith("#") else token


def _strip_outer_parens(expr: str) -> str:
    expr = expr.strip()
    while expr.startswith("(") and expr.endswith(")"):
        depth, wraps_all = 0, True
        for i, ch in enumerate(expr):
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0 and i != len(expr) - 1:
                    wraps_all = False
                    break
        if not wraps_all:
            break
        expr = expr[1:-1].strip()
    return expr


def _split_top_bool(expr: str, op: str) -> list:
    """Split on top-level ' OP ' occurrences (outside parentheses)."""
    token = f" {op} "
    parts, depth, i, last = [], 0, 0, 0
    upper = expr.upper()
    while i < len(expr):
        ch = expr[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif depth == 0 and upper.startswith(token, i):
            parts.append(expr[last:i])
            i += len(token)
            last = i
            continue
        i += 1
    parts.append(expr[last:])
    return [p.strip() for p in parts if p.strip()]


def _eval_str_condition(expr: str, item: dict, names: dict, values: dict) -> bool:
    """Evaluate the string condition grammar the write paths use: `a = :v`,
    attribute_exists / attribute_not_exists, parenthesized AND/OR."""
    expr = _strip_outer_parens(expr)
    parts = _split_top_bool(expr, "OR")
    if len(parts) > 1:
        return any(_eval_str_condition(p, item, names, values) for p in parts)
    parts = _split_top_bool(expr, "AND")
    if len(parts) > 1:
        return all(_eval_str_condition(p, item, names, values) for p in parts)
    m = re.fullmatch(r"attribute_not_exists\(\s*([#\w.]+)\s*\)", expr)
    if m:
        return _resolve_name(m.group(1), names) not in item
    m = re.fullmatch(r"attribute_exists\(\s*([#\w.]+)\s*\)", expr)
    if m:
        return _resolve_name(m.group(1), names) in item
    m = re.fullmatch(r"([#\w.]+)\s*=\s*(:\w+)", expr)
    if m:
        return item.get(_resolve_name(m.group(1), names)) == values[m.group(2)]
    raise NotImplementedError(f"E2ETable: unsupported string condition {expr!r}")


def _eval_obj_condition(cond, item) -> bool:
    """Evaluate a boto3 conditions object (Key/Attr trees) against an item."""
    from boto3.dynamodb.conditions import AttributeBase

    def resolve(v):
        return item.get(v.name) if isinstance(v, AttributeBase) else v

    op = cond.expression_operator
    vals = cond._values
    if op == "AND":
        return all(_eval_obj_condition(c, item) for c in vals)
    if op == "OR":
        return any(_eval_obj_condition(c, item) for c in vals)
    attr = vals[0]
    name = attr.name if isinstance(attr, AttributeBase) else attr
    actual = item.get(name)
    if op == "=":
        return actual == resolve(vals[1])
    if op == "begins_with":
        return isinstance(actual, str) and actual.startswith(resolve(vals[1]))
    if op == "BETWEEN":
        return actual is not None and resolve(vals[1]) <= actual <= resolve(vals[2])
    if op in ("<", "<=", ">", ">="):
        other = resolve(vals[1])
        if actual is None:
            return False
        return {"<": actual < other, "<=": actual <= other, ">": actual > other, ">=": actual >= other}[op]
    raise NotImplementedError(f"E2ETable: unsupported condition operator {op!r}")


def _eval_condition(cond, item: dict, names: dict, values: dict) -> bool:
    if isinstance(cond, str):
        return _eval_str_condition(cond, item, names, values)
    return _eval_obj_condition(cond, item)


# ── UpdateExpression application ──────────────────────────────────────────────

_IF_NOT_EXISTS = re.compile(r"if_not_exists\(\s*([#\w.]+)\s*,\s*(:\w+)\s*\)")


def _split_top_commas(s: str) -> list:
    parts, depth, cur = [], 0, []
    for ch in s:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    parts.append("".join(cur))
    return [p.strip() for p in parts if p.strip()]


def _apply_update_expression(item: dict, expr: str, names: dict, values: dict) -> None:
    """Apply the ADD / SET / REMOVE grammar the write paths use (incl. if_not_exists)."""
    tokens = re.split(r"\b(ADD|SET|REMOVE)\b", f" {expr} ")
    clauses = dict(zip(tokens[1::2], tokens[2::2]))
    for assign in _split_top_commas(clauses.get("SET", "")):
        target, rhs = (part.strip() for part in assign.split("=", 1))
        tname = _resolve_name(target, names)
        m = _IF_NOT_EXISTS.fullmatch(rhs)
        if m:
            base = _resolve_name(m.group(1), names)
            item[tname] = item[base] if base in item else values[m.group(2)]
        elif rhs.startswith(":"):
            item[tname] = copy.deepcopy(values[rhs])
        else:
            raise NotImplementedError(f"E2ETable: unsupported SET rhs {rhs!r}")
    for pair in _split_top_commas(clauses.get("ADD", "")):
        target, val = pair.split()
        tname = _resolve_name(target, names)
        item[tname] = item.get(tname, 0) + values[val]
    for target in _split_top_commas(clauses.get("REMOVE", "")):
        item.pop(_resolve_name(target, names), None)


# ── The fakes ─────────────────────────────────────────────────────────────────


class E2ETable:
    """Mini DynamoDB engine faithful to the write paths' actual call grammar."""

    def __init__(self):
        self.store: dict = {}  # (pk, sk) -> item
        self.written_pks: list = []  # every pk a HANDLER wrote (seeds excluded)

    def seed(self, item: dict) -> None:
        """Test-setup write — stored but NOT logged as a handler write."""
        self.store[(item["pk"], item["sk"])] = copy.deepcopy(item)

    def put_item(self, Item=None, ConditionExpression=None, **_kw):
        key = (Item["pk"], Item["sk"])
        if ConditionExpression is not None and "attribute_not_exists" in str(ConditionExpression) and key in self.store:
            raise Exception("ConditionalCheckFailedException: the conditional request failed")
        self.store[key] = copy.deepcopy(Item)
        self.written_pks.append(Item["pk"])
        return {}

    def get_item(self, Key=None, **_kw):
        item = self.store.get((Key["pk"], Key["sk"]))
        return {"Item": copy.deepcopy(item)} if item is not None else {}

    def update_item(self, Key=None, UpdateExpression=None, ExpressionAttributeNames=None, ExpressionAttributeValues=None, **_kw):
        key = (Key["pk"], Key["sk"])
        item = self.store.setdefault(key, {"pk": Key["pk"], "sk": Key["sk"]})
        _apply_update_expression(item, UpdateExpression, ExpressionAttributeNames or {}, ExpressionAttributeValues or {})
        self.written_pks.append(Key["pk"])
        return {"Attributes": copy.deepcopy(item)}

    def query(
        self,
        KeyConditionExpression=None,
        FilterExpression=None,
        ExpressionAttributeNames=None,
        ExpressionAttributeValues=None,
        ScanIndexForward=True,
        Limit=None,
        Select=None,
        **_kw,
    ):
        names = ExpressionAttributeNames or {}
        values = ExpressionAttributeValues or {}
        items = [copy.deepcopy(v) for v in self.store.values() if _eval_condition(KeyConditionExpression, v, names, values)]
        if FilterExpression is not None:
            items = [it for it in items if _eval_condition(FilterExpression, it, names, values)]
        items.sort(key=lambda it: it.get("sk", ""), reverse=not ScanIndexForward)
        if Limit is not None:
            items = items[:Limit]
        count = len(items)
        if Select == "COUNT":
            items = []
        return {"Items": items, "Count": count}


class FakeS3Client:
    def __init__(self):
        self.objects: dict = {}  # key -> bytes
        self.put_keys: list = []  # every key a HANDLER wrote (seeds excluded)

    def seed_json(self, key: str, payload: dict) -> None:
        self.objects[key] = json.dumps(payload).encode()

    def get_object(self, Bucket=None, Key=None, **_kw):
        if Key not in self.objects:
            raise Exception(f"NoSuchKey: {Key}")
        return {"Body": io.BytesIO(self.objects[Key])}

    def put_object(self, Bucket=None, Key=None, Body=None, **_kw):
        self.objects[Key] = Body.encode() if isinstance(Body, str) else Body
        self.put_keys.append(Key)
        return {}


class FakeSes:
    def __init__(self):
        self.sent: list = []

    def send_email(self, **kwargs):
        self.sent.append(kwargs)
        return {"MessageId": "e2e-test-message"}


# ── Test-tagged identity constants (ADR-104: unmistakably test data) ──────────

IP_A = "203.0.113.61"  # RFC 5737 TEST-NET-3 — never a real reader
IP_B = "203.0.113.62"
IP_C = "203.0.113.63"
LIB_ID = "e2e-test-experiment"
CATALOG_ID = "e2e-test-challenge"
LIVE_CHALLENGE_ID = "e2e-test-challenge_2026-07-13"
SUB_EMAIL = "e2e-test-subscriber@harness.e2e-invalid"


# ── Harness ───────────────────────────────────────────────────────────────────


class Harness:
    def __init__(self, monkeypatch):
        import boto3 as _boto3
        import rate_limiter
        from web import email_subscriber_lambda as sub, site_api_lambda as api, site_api_social as social

        self.api, self.social, self.sub = api, social, sub
        self.table = E2ETable()
        self.s3 = FakeS3Client()
        self.ses = FakeSes()

        assert social._RATE_LIMITER_READY, "rate_limiter must import — E2E exercises the REAL DDB-backed limiter"

        monkeypatch.setattr(social, "table", self.table)
        monkeypatch.setattr(sub, "table", self.table)
        monkeypatch.setattr(sub, "ses", self.ses)
        # Every runtime boto3.client(...) in these paths asks for "s3" — patch the one
        # shared factory so site_api_social, site_api_common._load_s3_json, and the
        # lambda_handler all see the same keyed object store.
        monkeypatch.setattr(_boto3, "client", self._client_factory)
        # Freeze every clock these modules consume (see module docstring).
        monkeypatch.setattr(social, "datetime", _FrozenDatetime)
        monkeypatch.setattr(sub, "datetime", _FrozenDatetime)
        monkeypatch.setattr(rate_limiter, "time", SimpleNamespace(time=lambda: _FROZEN_EPOCH))
        # Reset module caches so each test sees exactly its own seeded config.
        monkeypatch.setattr(social, "_challenge_catalog_cache", None)
        monkeypatch.setattr(social, "_challenges_cache", None)
        monkeypatch.setattr(social, "_library_ids_cache", (0.0, frozenset()))
        monkeypatch.setattr(social, "_nudge_counts", {})
        monkeypatch.setattr(social, "_nudge_rate_store", {})
        monkeypatch.setattr(social, "_finding_rate_store", {})

        self.week_id = social._current_iso_week()  # derived from the frozen clock
        self._seed_configs()

    def _client_factory(self, service, **_kw):
        if service == "s3":
            return self.s3
        raise RuntimeError(f"E2E harness: unexpected boto3 client {service!r}")

    def _seed_configs(self):
        library = {
            "pillars": {"recovery": {"label": "Recovery", "icon": "moon"}},
            "experiments": [{"id": LIB_ID, "name": "E2E Test Experiment", "pillar": "recovery", "status": "proposed"}],
        }
        catalog = {
            "challenges": [
                {"id": CATALOG_ID, "name": "E2E Test Challenge", "public": True, "status": "available"},
                {"id": "e2e-private-challenge", "name": "E2E Private", "public": False},
            ]
        }
        self.s3.seed_json("site/config/experiment_library.json", library)
        self.s3.seed_json("site/config/challenges_catalog.json", catalog)
        self.s3.seed_json("config/challenges_catalog.json", catalog)  # /api/challenges overlay reads the root-config copy
        self.s3.seed_json(
            "site/config/current_challenge.json",
            {"week_id": self.week_id, "predict_metrics": [{"key": "weight", "label": "scale weight"}], "result": None},
        )

    def seed_live_challenge(self):
        self.table.seed(
            {
                "pk": "USER#matthew#SOURCE#challenges",
                "sk": f"CHALLENGE#{LIVE_CHALLENGE_ID}",
                "name": "E2E Test Challenge",
                "status": "active",
                "duration_days": 7,
                "daily_checkins": [],
            }
        )

    # -- invocation --------------------------------------------------------

    @staticmethod
    def event(path, method="POST", body=None, ip=IP_A, qs=None):
        return {
            "rawPath": path,
            "requestContext": {"http": {"method": method, "sourceIp": ip}},
            "headers": {"x-forwarded-for": ip},
            "queryStringParameters": qs,
            "body": json.dumps(body) if body is not None else None,
        }

    def call(self, path, method="POST", body=None, ip=IP_A, qs=None):
        """Full site-api round trip through the real lambda_handler (routing included)."""
        resp = self.api.lambda_handler(self.event(path, method, body, ip, qs), None)
        return resp["statusCode"], json.loads(resp["body"]) if resp.get("body") else {}

    def call_subscriber(self, method="POST", body=None, ip=IP_A, qs=None):
        resp = self.sub.lambda_handler(self.event("/api/subscribe", method, body, ip, qs), None)
        return resp


@pytest.fixture()
def wp(monkeypatch):
    return Harness(monkeypatch)


# ══════════════════════════════════════════════════════════════════════════════
# experiment_vote — POST → counter row → readback via GET /api/experiment_detail
# ══════════════════════════════════════════════════════════════════════════════


def test_experiment_vote_roundtrip_dedup_and_validation(wp):
    status, body = wp.call("/api/experiment_vote", body={"library_id": LIB_ID}, ip=IP_A)
    assert (status, body["new_count"]) == (200, 1)

    # Readback through the public GET surface — the stored effect a reader sees.
    status, detail = wp.call("/api/experiment_detail", method="GET", qs={"id": LIB_ID})
    assert status == 200
    assert detail["votes"] == 1

    # Same IP re-vote inside 24h → the real dedup row 429s.
    status, body = wp.call("/api/experiment_vote", body={"library_id": LIB_ID}, ip=IP_A)
    assert status == 429

    # A different reader still lands.
    status, body = wp.call("/api/experiment_vote", body={"library_id": LIB_ID}, ip=IP_B)
    assert (status, body["new_count"]) == (200, 2)

    # Anti-pollution: an id that isn't in the library mints nothing.
    status, _ = wp.call("/api/experiment_vote", body={"library_id": "e2e-not-in-library"}, ip=IP_C)
    assert status == 400
    assert ("VOTES#experiment_library", "LIB#e2e-not-in-library") not in wp.table.store

    # The dedup rows key on a hashed IP — the raw address is never stored.
    assert all(IP_A not in sk and IP_B not in sk for (_pk, sk) in wp.table.store)


# ══════════════════════════════════════════════════════════════════════════════
# challenge_vote — POST → counter row → readback via GET /api/challenge_catalog
# ══════════════════════════════════════════════════════════════════════════════


def test_challenge_vote_roundtrip_and_private_rejection(wp):
    status, body = wp.call("/api/challenge_vote", body={"catalog_id": CATALOG_ID}, ip=IP_A)
    assert (status, body["new_count"]) == (200, 1)

    status, catalog = wp.call("/api/challenge_catalog", method="GET")
    assert status == 200
    votes = {ch["id"]: ch["votes"] for ch in catalog["challenges"]}
    assert votes[CATALOG_ID] == 1
    assert "e2e-private-challenge" not in votes  # public:false never surfaces

    status, _ = wp.call("/api/challenge_vote", body={"catalog_id": CATALOG_ID}, ip=IP_A)
    assert status == 429  # dedup row

    status, _ = wp.call("/api/challenge_vote", body={"catalog_id": "e2e-private-challenge"}, ip=IP_B)
    assert status == 404  # private challenges are not voteable

    status, _ = wp.call("/api/challenge_vote", body={"catalog_id": "e2e-unknown"}, ip=IP_B)
    assert status == 404


# ══════════════════════════════════════════════════════════════════════════════
# experiment_follow / challenge_follow — POST → follow row + real per-IP budget
# ══════════════════════════════════════════════════════════════════════════════


def test_experiment_follow_roundtrip_idempotency_and_rate_limit(wp):
    email = "e2e-test-follower@harness.e2e-invalid"
    status, body = wp.call("/api/experiment_follow", body={"email": email, "library_id": LIB_ID}, ip=IP_A)
    assert (status, body.get("followed")) == (200, True)

    # Stored effect: exactly one EXPERIMENT_FOLLOWS row, keyed on the email HASH.
    rows = [(sk, it) for (pk, sk), it in wp.table.store.items() if pk == "EXPERIMENT_FOLLOWS"]
    assert len(rows) == 1
    sk, item = rows[0]
    assert email not in sk and item["email"] == email and item["library_id"] == LIB_ID and item["notified"] is False

    # Readback: the follow shows up in the public follower_count.
    status, detail = wp.call("/api/experiment_detail", method="GET", qs={"id": LIB_ID})
    assert (status, detail["follower_count"]) == (200, 1)

    # Same email again → idempotent already_following, no duplicate row.
    status, body = wp.call("/api/experiment_follow", body={"email": email, "library_id": LIB_ID}, ip=IP_A)
    assert (status, body.get("already_following")) == (200, True)
    assert sum(1 for (pk, _sk) in wp.table.store if pk == "EXPERIMENT_FOLLOWS") == 1

    # Per-IP budget (10/h counter; the request that reaches count=10 is refused):
    # requests 1+2 above consumed 2, so 7 more distinct emails pass, the next 429s.
    for i in range(7):
        status, _ = wp.call("/api/experiment_follow", body={"email": f"e2e-test-f{i}@harness.e2e-invalid", "library_id": LIB_ID}, ip=IP_A)
        assert status == 200
    status, _ = wp.call("/api/experiment_follow", body={"email": "e2e-test-f7@harness.e2e-invalid", "library_id": LIB_ID}, ip=IP_A)
    assert status == 429


def test_challenge_follow_roundtrip(wp):
    email = "e2e-test-chfollow@harness.e2e-invalid"
    status, body = wp.call("/api/challenge_follow", body={"email": email, "catalog_id": CATALOG_ID}, ip=IP_A)
    assert (status, body.get("followed")) == (200, True)
    rows = [(sk, it) for (pk, sk), it in wp.table.store.items() if pk == "CHALLENGE_FOLLOWS"]
    assert len(rows) == 1 and rows[0][1]["catalog_id"] == CATALOG_ID and email not in rows[0][0]

    status, body = wp.call("/api/challenge_follow", body={"email": email, "catalog_id": CATALOG_ID}, ip=IP_A)
    assert (status, body.get("already_following")) == (200, True)

    status, _ = wp.call("/api/challenge_follow", body={"email": "not-an-email", "catalog_id": CATALOG_ID}, ip=IP_B)
    assert status == 400


# ══════════════════════════════════════════════════════════════════════════════
# challenge_checkin — POST → daily_checkins mutation → readback via /api/challenges
# ══════════════════════════════════════════════════════════════════════════════


def test_challenge_checkin_roundtrip_idempotency_and_daily_limit(wp):
    wp.seed_live_challenge()
    date = "2026-07-15"

    status, body = wp.call("/api/challenge_checkin", body={"challenge_id": LIVE_CHALLENGE_ID, "completed": True, "date": date}, ip=IP_A)
    assert status == 200
    assert body["checked_in"] is True and body["total_checkins"] == 1

    # Readback through the public GET: the active challenge now shows progress.
    status, data = wp.call("/api/challenges", method="GET")
    assert status == 200
    live = [c for c in data["challenges"] if c.get("origin") == "live" and c["challenge_id"] == LIVE_CHALLENGE_ID]
    assert len(live) == 1
    assert live[0]["progress"]["checkin_days"] == 1 and live[0]["progress"]["completed_days"] == 1

    # Same IP, same challenge, same day → the REAL 1/day DDB rate limit 429s.
    status, _ = wp.call("/api/challenge_checkin", body={"challenge_id": LIVE_CHALLENGE_ID, "completed": True, "date": date}, ip=IP_A)
    assert status == 429

    # A retry from another IP for the SAME date replaces rather than duplicates
    # (per-date idempotency: completion_pct must not inflate).
    status, body = wp.call("/api/challenge_checkin", body={"challenge_id": LIVE_CHALLENGE_ID, "completed": False, "date": date}, ip=IP_B)
    assert (status, body["total_checkins"]) == (200, 1)
    stored = wp.table.store[("USER#matthew#SOURCE#challenges", f"CHALLENGE#{LIVE_CHALLENGE_ID}")]
    assert [c["date"] for c in stored["daily_checkins"]] == [date]
    assert stored["daily_checkins"][0]["completed"] is False  # replaced with the newest value

    # Unknown challenge → 404, nothing minted.
    status, _ = wp.call("/api/challenge_checkin", body={"challenge_id": "e2e-ghost", "completed": True}, ip=IP_C)
    assert status == 404


# ══════════════════════════════════════════════════════════════════════════════
# experiment_suggest — POST → pending moderated row (no public readback by design)
# ══════════════════════════════════════════════════════════════════════════════


def test_experiment_suggest_stored_pending_and_rate_limited(wp):
    idea = "e2e-test suggestion: does a post-dinner walk change overnight HRV?"
    status, body = wp.call("/api/experiment_suggest", body={"idea": idea, "source": "e2e-test"}, ip=IP_A)
    assert (status, body["status"]) == (200, "received")

    # Stored effect: a pending, reader-attributed row in the moderation partition.
    # (Deliberately NO public GET reads this partition — suggestions are moderated;
    # the stored shape IS the contract.)
    rows = [it for (pk, _sk), it in wp.table.store.items() if pk == "USER#matthew#SOURCE#experiment_suggestions"]
    assert len(rows) == 1
    assert rows[0]["idea"] == idea and rows[0]["status"] == "pending" and rows[0]["submitted_by"] == "reader"

    status, _ = wp.call("/api/experiment_suggest", body={"idea": "too short"}, ip=IP_A)
    assert status == 400

    # Real limiter: 3/h per IP — the two 200-or-400 calls above consumed 2 budget
    # slots (the limiter increments before validation), so one more passes, then 429.
    status, _ = wp.call("/api/experiment_suggest", body={"idea": idea + " (variant three for the budget)"}, ip=IP_A)
    assert status == 200
    status, _ = wp.call("/api/experiment_suggest", body={"idea": idea + " (variant four for the budget)"}, ip=IP_A)
    assert status == 429


# ══════════════════════════════════════════════════════════════════════════════
# predict_week — POST → tally counters → readback via GET /api/predict_week
# ══════════════════════════════════════════════════════════════════════════════


def test_predict_week_roundtrip_dedup_and_window_guards(wp):
    week = wp.week_id
    status, body = wp.call("/api/predict_week", body={"week_id": week, "metric": "weight", "choice": "down"}, ip=IP_A)
    assert status == 200
    assert body["tallies"]["down"] == 1

    status, _ = wp.call("/api/predict_week", body={"week_id": week, "metric": "weight", "choice": "up"}, ip=IP_A)
    assert status == 429  # one prediction per IP per week per metric

    status, _ = wp.call("/api/predict_week", body={"week_id": week, "metric": "weight", "choice": "up"}, ip=IP_B)
    assert status == 200

    # Readback: the public GET tally reflects both readers.
    status, tally = wp.call("/api/predict_week", method="GET")
    assert status == 200
    assert tally["active"] is True and tally["week_id"] == week
    assert tally["tallies"]["weight"] == {"up": 1, "down": 1, "flat": 0}

    # Window/domain guards.
    assert wp.call("/api/predict_week", body={"week_id": "2026-W01", "metric": "weight", "choice": "up"}, ip=IP_C)[0] == 409
    assert wp.call("/api/predict_week", body={"week_id": week, "metric": "e2e-ghost", "choice": "up"}, ip=IP_C)[0] == 404
    assert wp.call("/api/predict_week", body={"week_id": week, "metric": "weight", "choice": "sideways"}, ip=IP_C)[0] == 400


# ══════════════════════════════════════════════════════════════════════════════
# board_question / submit_finding — POST → pending S3 capture (moderated queue)
# ══════════════════════════════════════════════════════════════════════════════


def test_board_question_stored_pending_hashed_and_rate_limited(wp):
    q = "e2e-test question: is my sleep actually improving month over month?"
    status, body = wp.call("/api/board_question", body={"question": q, "email": SUB_EMAIL}, ip=IP_A)
    assert (status, body["success"]) == (200, True)

    keys = [k for k in wp.s3.put_keys if k.startswith("generated/board_questions/")]
    assert len(keys) == 1
    stored = json.loads(wp.s3.objects[keys[0]])
    assert stored["status"] == "pending" and stored["question"] == q
    assert IP_A not in stored["ip_hash"]  # hashed, never raw
    assert SUB_EMAIL not in json.dumps(body)  # email captured privately, never echoed

    assert wp.call("/api/board_question", body={"question": "short"}, ip=IP_A)[0] == 400

    # Real limiter: 3/h — two consumed above, one more passes, the fourth 429s.
    assert wp.call("/api/board_question", body={"question": q + " (budget variant)"}, ip=IP_A)[0] == 200
    assert wp.call("/api/board_question", body={"question": q + " (budget variant two)"}, ip=IP_A)[0] == 429


def test_submit_finding_stored_content_stable_and_rate_limited(wp):
    body_payload = {"metric_a": "sleep", "metric_b": "hrv", "finding": "e2e-test finding: more sleep tracks higher hrv over time"}
    status, first = wp.call("/api/submit_finding", body=body_payload, ip=IP_A)
    assert (status, first["success"]) == (200, True)

    keys = [k for k in wp.s3.put_keys if k.startswith("generated/findings/")]
    assert len(keys) == 1
    stored = json.loads(wp.s3.objects[keys[0]])
    assert stored["status"] == "pending" and IP_A not in stored["ip_hash"]

    # A network retry of the identical submission overwrites the SAME object
    # (content-stable id) — no duplicate pending finding to triage.
    status, second = wp.call("/api/submit_finding", body=body_payload, ip=IP_A)
    assert status == 200 and second["finding_id"] == first["finding_id"]
    assert len({k for k in wp.s3.put_keys if k.startswith("generated/findings/")}) == 1

    # Real limiter: 3/h — third passes, fourth 429s.
    assert wp.call("/api/submit_finding", body=dict(body_payload, finding="e2e-test finding variant three here"), ip=IP_A)[0] == 200
    assert wp.call("/api/submit_finding", body=dict(body_payload, finding="e2e-test finding variant four here"), ip=IP_A)[0] == 429


# ══════════════════════════════════════════════════════════════════════════════
# nudge — POST → per-category per-IP budget (the stored effect IS the rate row)
# ══════════════════════════════════════════════════════════════════════════════


def test_nudge_per_category_budget_and_validation(wp):
    status, body = wp.call("/api/nudge", body={"category": "back_on_it"}, ip=IP_A)
    assert (status, body["success"]) == (200, True)
    assert body["category"] == "back_on_it"

    # Second tap, same category, same IP → the real 1/h/category budget 429s...
    assert wp.call("/api/nudge", body={"category": "back_on_it"}, ip=IP_A)[0] == 429
    # ...but a different category has its own budget, and so does another reader.
    assert wp.call("/api/nudge", body={"category": "you_got_this"}, ip=IP_A)[0] == 200
    assert wp.call("/api/nudge", body={"category": "back_on_it"}, ip=IP_B)[0] == 200

    assert wp.call("/api/nudge", body={"category": "e2e-not-a-category"}, ip=IP_C)[0] == 400
    # Routing contract: nudge is POST-only through the real dispatch table.
    assert wp.call("/api/nudge", method="GET", ip=IP_C)[0] == 405


# ══════════════════════════════════════════════════════════════════════════════
# subscribe → confirm → unsubscribe (email_subscriber_lambda, full lifecycle)
# ══════════════════════════════════════════════════════════════════════════════


def test_subscribe_confirm_unsubscribe_lifecycle(wp):
    import hashlib

    resp = wp.call_subscriber(body={"email": SUB_EMAIL})
    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["status"] == "pending_confirmation"

    email_hash = hashlib.sha256(SUB_EMAIL.encode()).hexdigest()
    record = wp.table.store[("USER#matthew#SOURCE#subscribers", f"EMAIL#{email_hash}")]
    assert record["status"] == "pending_confirmation"
    token = record["confirm_token"]
    assert len(token) == 64

    # The confirmation email carries the token link (fake SES — nothing sent).
    assert len(wp.ses.sent) == 1
    html = wp.ses.sent[0]["Content"]["Simple"]["Body"]["Html"]["Data"]
    assert token in html

    # Confirm via the emailed token → 302 to the confirmed page + status flip.
    resp = wp.call_subscriber(method="GET", qs={"action": "confirm", "token": token, "h": email_hash[:16]})
    assert resp["statusCode"] == 302 and "confirmed=true" in resp["headers"]["Location"]
    record = wp.table.store[("USER#matthew#SOURCE#subscribers", f"EMAIL#{email_hash}")]
    assert record["status"] == "confirmed" and "confirm_token" not in record
    assert len(wp.ses.sent) == 2  # welcome email

    # Unsubscribe → non-destructive status flip (#1350: the row is RETAINED).
    resp = wp.call_subscriber(method="GET", qs={"action": "unsubscribe", "email": SUB_EMAIL})
    assert resp["statusCode"] == 302 and "unsubscribed=true" in resp["headers"]["Location"]
    record = wp.table.store[("USER#matthew#SOURCE#subscribers", f"EMAIL#{email_hash}")]
    assert record["status"] == "unsubscribed" and record["unsubbed_at"]

    # A bogus token never confirms.
    resp = wp.call_subscriber(method="GET", qs={"action": "confirm", "token": "0" * 64, "h": email_hash[:16]})
    assert resp["statusCode"] == 302 and "error=invalid_token" in resp["headers"]["Location"]


def test_subscribe_blocked_domain_is_silently_dropped(wp):
    resp = wp.call_subscriber(body={"email": "e2e-test@mailinator.com"})
    assert resp["statusCode"] == 200  # deliberately indistinguishable from success
    assert not any(pk == "USER#matthew#SOURCE#subscribers" for (pk, _sk) in wp.table.store)
    assert wp.ses.sent == []


def test_subscribe_rate_limit_via_preseeded_counter(wp):
    """The 60/5min/IP budget, proven WITHOUT issuing 60 requests: pre-seed the
    real atomic counter at the limit and show the next request trips 429 through
    the real read-modify path."""
    import hashlib

    ip_hash = hashlib.sha256(IP_C.encode()).hexdigest()[:16]
    bucket = _FROZEN_EPOCH // 300
    wp.table.seed({"pk": "SUBSCRIBE#rate_limit", "sk": f"IP#{ip_hash}#BUCKET#{bucket}", "req_count": 60})

    resp = wp.call_subscriber(body={"email": SUB_EMAIL}, ip=IP_C)
    assert resp["statusCode"] == 429
    # And the same request from an unthrottled IP still lands.
    assert wp.call_subscriber(body={"email": SUB_EMAIL}, ip=IP_B)["statusCode"] == 200


# ══════════════════════════════════════════════════════════════════════════════
# Isolation gate — the full sweep touches ONLY sanctioned interactive partitions
# ══════════════════════════════════════════════════════════════════════════════


def test_writes_stay_inside_sanctioned_partitions(wp):
    """#1438 acceptance criterion 2, made structural: run every write path, then
    prove (a) each site-api pk it wrote is covered by the SEC-01 LeadingKeys
    allowlist parsed from the LIVE role policy (so these writes are exactly what
    the public role could do in prod — nothing more), and (b) no write escaped
    into a real data partition (the only USER#… partitions touched are the three
    sanctioned interactive ones), and (c) S3 writes stay in the two moderated
    generated/ prefixes."""
    from fnmatch import fnmatch

    from test_site_api_write_scope import _site_api_leadingkeys

    wp.seed_live_challenge()
    assert wp.call("/api/experiment_vote", body={"library_id": LIB_ID}, ip=IP_A)[0] == 200
    assert wp.call("/api/challenge_vote", body={"catalog_id": CATALOG_ID}, ip=IP_A)[0] == 200
    assert wp.call("/api/experiment_follow", body={"email": SUB_EMAIL, "library_id": LIB_ID}, ip=IP_A)[0] == 200
    assert wp.call("/api/challenge_follow", body={"email": SUB_EMAIL, "catalog_id": CATALOG_ID}, ip=IP_A)[0] == 200
    assert wp.call("/api/challenge_checkin", body={"challenge_id": LIVE_CHALLENGE_ID, "completed": True}, ip=IP_A)[0] == 200
    assert wp.call("/api/experiment_suggest", body={"idea": "e2e-test sweep suggestion payload"}, ip=IP_A)[0] == 200
    assert wp.call("/api/predict_week", body={"week_id": wp.week_id, "metric": "weight", "choice": "flat"}, ip=IP_A)[0] == 200
    assert wp.call("/api/nudge", body={"category": "watching"}, ip=IP_A)[0] == 200
    assert wp.call("/api/board_question", body={"question": "e2e-test sweep board question payload"}, ip=IP_A)[0] == 200
    assert wp.call("/api/submit_finding", body={"metric_a": "a", "metric_b": "b", "finding": "e2e-test sweep finding"}, ip=IP_A)[0] == 200

    site_api_pks = set(wp.table.written_pks)

    # (a) Every site-api write is inside the role's LeadingKeys scope.
    patterns = _site_api_leadingkeys()
    uncovered = sorted(pk for pk in site_api_pks if not any(fnmatch(pk, p) for p in patterns))
    assert not uncovered, f"E2E write escaped the SEC-01 LeadingKeys allowlist: {uncovered}"

    # The subscriber lambda (own role) — run its lifecycle too, then check (b)+(c).
    assert wp.call_subscriber(body={"email": SUB_EMAIL})["statusCode"] == 200
    subscriber_pks = set(wp.table.written_pks) - site_api_pks
    assert subscriber_pks <= {"USER#matthew#SOURCE#subscribers", "SUBSCRIBE#rate_limit"}

    # (b) No stray keys: the only USER#… partitions ANY write path touched are the
    # three sanctioned interactive ones — reader/experiment data partitions
    # (whoop, nutrition, chronicle, …) are untouchable from this surface.
    sanctioned_user_partitions = {
        "USER#matthew#SOURCE#challenges",
        "USER#matthew#SOURCE#experiment_suggestions",
        "USER#matthew#SOURCE#subscribers",
    }
    user_pks = {pk for pk in wp.table.written_pks if pk.startswith("USER#")}
    assert user_pks <= sanctioned_user_partitions, f"write path escaped into a data partition: {user_pks - sanctioned_user_partitions}"

    # (c) S3 writes: only the two moderated capture prefixes.
    assert all(k.startswith(("generated/findings/", "generated/board_questions/")) for k in wp.s3.put_keys), wp.s3.put_keys
