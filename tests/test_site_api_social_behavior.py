"""tests/test_site_api_social_behavior.py — behavioral contracts for the social /
community serving surface, ``lambdas/web/site_api_social.py``.

This is the site's **public, unauthenticated, WRITE-capable** cluster: the only
place a stranger on the internet can put bytes into Matthew's platform. Thirty
endpoints, wired in ``web.site_api_lambda`` through ``ROUTES`` + ``_SIMPLE_ROUTES``:

    subscriber verification + count · nudges · reader findings · the experiment
    library / vote / follow / detail / suggest · the challenge catalog, live
    challenges, votes, follows and check-ins · the evening-ritual one-tap link ·
    predict-the-week · the board question capture · the social membrane
    (/api/broadcast, /api/social_context, /api/membrane) · the engagement ladder
    counts + replication self-cert · the anonymous cohort strip.

What is pinned here, and why each contract is load-bearing:

  * **The write door.** Every POST route is reachable by anyone. So each one is
    driven to its rate-limit, its allowlist, and its input-validation edge — and
    where the guard is conditional on a module import (``_RATE_LIMITER_READY``)
    the test MUTATES that flag and re-drives, because a guard that vanishes with
    its dependency is not a guard ("guard the SET, not the instance").
  * **Privacy.** The membrane's held set must stay unpublished; the cohort strip's
    k-anonymity floor is a HARD gate; reader-submitted text must not reach a public
    payload unmoderated; and where a sibling surface in this very file filters
    (``handle_challenge_catalog`` runs ``_is_blocked_vice`` + ``public:false``) the
    experiment library is checked against the SAME bar.
  * **ADR-104 honest numbers.** A DynamoDB outage must not publish a factual `0`
    subscribers / predictors / replicators; an undefined rate must not publish `0%`.
  * **ADR-105 rigor.** Every aggregate the cohort strip publishes ships its `n`,
    and every ladder rung ships the provenance of its own number.
  * **Envelope parity.** The quiet-platform payload must publish the keys the
    populated one does, or a front-end binding breaks on Day 1 of every cycle.
  * **ADR-058 phase filtering.** ``challenges`` and ``experiments`` are
    EXPERIMENT_SCOPED in ``experiment.phase_taxonomy``; the membrane's post
    partitions are RAW_TIMESERIES. Which handler must filter is DERIVED from that
    registry, never restated.
  * **Reader/writer field parity.** ``_broadcast_card`` reads field names off an
    ingested post row. The names it reads are checked against the names the three
    ingestion lambdas' ``transform()`` actually writes — both sides AST-derived
    from the source, so neither can be hand-typed wrong.

Everything runs offline: the module's ``table`` and ``boto3`` globals are replaced
with hand-rolled bounded fakes, the clock is a pinned ``datetime`` subclass, and no
``MagicMock`` appears anywhere near a paginated read.

Arithmetic expectations are hand-derived in the test body with the derivation shown
in a comment — never "whatever the code returned".
"""

from __future__ import annotations

import ast
import hmac
import inspect
import io
import json
import pathlib
import re
from datetime import datetime, timezone

import pytest
from experiment import phase_taxonomy
from ingestion.source_registry import SOURCE_REGISTRY
from web import site_api_common as sac, site_api_lambda as router, site_api_social as social

# ──────────────────────────────────────────────────────────────────────────────
# 0. Frozen clock
# ──────────────────────────────────────────────────────────────────────────────

# 2026-05-10 17:40Z == 10:40 Pacific on the same calendar day (PDT, UTC-7), so the
# UTC-keyed and PT-keyed handlers in this module agree on "today" and no test
# accidentally straddles a date boundary.
DEFAULT_NOW = datetime(2026, 5, 10, 17, 40, 0, tzinfo=timezone.utc)
_FROZEN = [DEFAULT_NOW]

TODAY = "2026-05-10"
# datetime(2026, 5, 10).isocalendar() == (2026, 19, 7) — a Sunday, ISO week 19.
CURRENT_WEEK = "2026-W19"


class _FrozenDatetime(datetime):
    """``datetime`` subclass with a pinned ``now()``.

    A subclass rather than a Mock because the code under test calls ``strptime``,
    ``isocalendar``, ``timedelta`` arithmetic and ``.date()`` on the same name.
    """

    @classmethod
    def now(cls, tz=None):
        if tz is None:
            return _FROZEN[0].replace(tzinfo=None)
        return _FROZEN[0].astimezone(tz)

    @classmethod
    def utcnow(cls):
        return _FROZEN[0].replace(tzinfo=None)


def freeze(dt: datetime) -> None:
    _FROZEN[0] = dt


# ──────────────────────────────────────────────────────────────────────────────
# 1. Hand-rolled bounded fakes
# ──────────────────────────────────────────────────────────────────────────────


class ConditionalCheckFailed(Exception):
    """The module detects the DDB conditional failure by substring-matching
    ``str(e)``, so the fake's message must carry the real exception name."""

    def __init__(self):
        super().__init__("An error occurred (ConditionalCheckFailedException) on put_item")


def _key_conditions(cond) -> dict:
    """Flatten a boto3 Key condition tree into a plain dict.

    Walks ``ConditionBase.get_expression()`` rather than string-matching, so the
    fake understands exactly the operators the handlers actually build
    (``eq`` / ``begins_with`` / ``between``, composed with ``&``).
    """
    out: dict = {"eq": {}, "begins": {}, "between": {}}

    def walk(node):
        expr = node.get_expression()
        op = expr["operator"]
        values = expr["values"]
        if op == "AND":
            for sub in values:
                walk(sub)
            return
        attr = values[0].name
        if op == "=":
            out["eq"][attr] = values[1]
        elif op == "begins_with":
            out["begins"][attr] = values[1]
        elif op == "BETWEEN":
            out["between"][attr] = (values[1], values[2])
        else:  # pragma: no cover — a new operator must be taught to the fake
            raise AssertionError(f"fake does not model key operator {op!r}")

    walk(cond)
    return out


def _split_commas(text: str) -> list:
    """Split on commas at paren depth 0 (``if_not_exists(#t, :ttl)`` stays whole)."""
    parts, depth, start = [], 0, 0
    for i, ch in enumerate(text):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append(text[start:i])
            start = i + 1
    parts.append(text[start:])
    return [p.strip() for p in parts if p.strip()]


def _bool_expr(text: str) -> bool:
    """Evaluate a boolean string of ``True``/``False``/``AND``/``OR``/parens.

    A tiny recursive-descent parser rather than ``eval``: the input is derived from
    a production expression string, and a test double must never execute one.
    """
    tokens = text.replace("(", " ( ").replace(")", " ) ").split()

    def parse_or(i):
        val, i = parse_and(i)
        while i < len(tokens) and tokens[i] == "OR":
            rhs, i = parse_and(i + 1)
            val = val or rhs
        return val, i

    def parse_and(i):
        val, i = parse_atom(i)
        while i < len(tokens) and tokens[i] == "AND":
            rhs, i = parse_atom(i + 1)
            val = val and rhs
        return val, i

    def parse_atom(i):
        if tokens[i] == "(":
            val, i = parse_or(i + 1)
            assert tokens[i] == ")", text
            return val, i + 1
        return tokens[i] == "True", i + 1

    return parse_or(0)[0]


def _eval_string_filter(expr: str, item: dict, names: dict, values: dict) -> bool:
    """Evaluate a DynamoDB string FilterExpression against one item.

    Models exactly the three forms this module builds: ``attribute_exists(X)``,
    ``attribute_not_exists(X)`` and ``X = :v``, joined with AND/OR. The phase
    filter's own expression is read out of ``with_phase_filter``'s output, so this
    fake can never drift from ADR-058's definition.
    """

    def resolve(tok: str) -> str:
        tok = tok.strip()
        return names.get(tok, tok)

    def fn_sub(m):
        present = item.get(resolve(m.group(2))) is not None
        want_present = m.group(1) == "attribute_exists"
        return "True" if present == want_present else "False"

    out = re.sub(r"(attribute_not_exists|attribute_exists)\(([^)]+)\)", fn_sub, expr)

    def cmp_sub(m):
        return "True" if item.get(resolve(m.group(1))) == values[m.group(2)] else "False"

    out = re.sub(r"(#?[\w.]+)\s*=\s*(:[\w]+)", cmp_sub, out)
    return _bool_expr(out)


class FakeSocialTable:
    """In-memory DynamoDB ``Table`` double for this module's write cluster.

    Deliberately NOT ``tests/fakes.py::FakeDdbTable``. Every write path here leans
    on semantics that generic fake does not model, and a stub that ignored them
    would make the tests vacuous:

      * real ``ConditionExpression="attribute_not_exists(pk)"`` evaluation — those
        conditional puts ARE the vote / follow / prediction / self-cert rate limit;
      * ``ADD``-style atomic counter increments with ``ReturnValues="UPDATED_NEW"``
        — the number that comes back is the number the reader is shown;
      * ``Select="COUNT"`` with a string ``FilterExpression`` — the subscriber count;
      * DynamoDB's real ordering, ``Limit`` applied BEFORE ``FilterExpression``, so
        a partition whose newest rows are pilot-phase really does return fewer rows.

    ``fail`` injects an exception into a named method so the fail-soft / fail-open
    branches can be driven; ``calls`` records everything for assertions.
    """

    def __init__(self, items=None, fail: set | None = None):
        self.store: dict = {}
        for it in items or []:
            self.store[(it["pk"], it["sk"])] = dict(it)
        self.fail = set(fail or ())
        self.queries: list = []
        self.puts: list = []
        self.updates: list = []
        self.gets: list = []

    # -- helpers ---------------------------------------------------------------
    def rows_in(self, pk: str) -> list:
        return [dict(v) for k, v in self.store.items() if k[0] == pk]

    def _boom(self, method: str):
        if method in self.fail:
            raise RuntimeError(f"ddb {method} unavailable")

    # -- reads -----------------------------------------------------------------
    def get_item(self, Key=None, **_kwargs):
        self.gets.append(Key)
        self._boom("get_item")
        item = self.store.get((Key["pk"], Key["sk"]))
        return {"Item": dict(item)} if item is not None else {}

    def query(self, **kwargs):
        self.queries.append(kwargs)
        self._boom("query")
        cond = _key_conditions(kwargs["KeyConditionExpression"])
        rows = []
        for (pk, sk), item in self.store.items():
            if cond["eq"].get("pk") not in (None, pk):
                continue
            if "sk" in cond["eq"] and cond["eq"]["sk"] != sk:
                continue
            if "sk" in cond["begins"] and not sk.startswith(cond["begins"]["sk"]):
                continue
            if "sk" in cond["between"]:
                lo, hi = cond["between"]["sk"]
                if not (lo <= sk <= hi):
                    continue
            rows.append(dict(item))
        rows.sort(key=lambda r: r["sk"], reverse=not kwargs.get("ScanIndexForward", True))
        # DynamoDB applies Limit BEFORE FilterExpression — modelled faithfully.
        if kwargs.get("Limit") is not None:
            rows = rows[: kwargs["Limit"]]
        fexpr = kwargs.get("FilterExpression")
        if isinstance(fexpr, str) and fexpr:
            names = kwargs.get("ExpressionAttributeNames") or {}
            values = kwargs.get("ExpressionAttributeValues") or {}
            rows = [r for r in rows if _eval_string_filter(fexpr, r, names, values)]
        if kwargs.get("Select") == "COUNT":
            return {"Count": len(rows), "Items": []}
        return {"Items": rows, "Count": len(rows)}

    # -- writes ----------------------------------------------------------------
    def put_item(self, Item=None, **kwargs):
        self.puts.append(dict(Item))
        self._boom("put_item")
        key = (Item["pk"], Item["sk"])
        if kwargs.get("ConditionExpression") == "attribute_not_exists(pk)" and key in self.store:
            raise ConditionalCheckFailed()
        self.store[key] = dict(Item)
        return {}

    def update_item(self, Key=None, UpdateExpression="", **kwargs):
        self.updates.append({"Key": Key, "UpdateExpression": UpdateExpression, **kwargs})
        self._boom("update_item")
        names = kwargs.get("ExpressionAttributeNames") or {}
        values = kwargs.get("ExpressionAttributeValues") or {}
        item = self.store.setdefault((Key["pk"], Key["sk"]), dict(Key))
        updated: dict = {}
        for verb, attr, rhs in _parse_update_expression(UpdateExpression):
            attr = names.get(attr, attr)
            if verb == "ADD":
                item[attr] = (item.get(attr) or 0) + values[rhs]
            elif rhs.startswith("if_not_exists("):
                inner_attr, token = (p.strip() for p in rhs[len("if_not_exists(") : -1].split(","))
                inner_attr = names.get(inner_attr, inner_attr)
                item[attr] = item.get(inner_attr, values[token])
            else:
                item[attr] = values[rhs]
            updated[attr] = item[attr]
        return {"Attributes": updated} if kwargs.get("ReturnValues") == "UPDATED_NEW" else {}


def _parse_update_expression(expr: str) -> list:
    """Parse the ``ADD a :x SET b = :y, c = if_not_exists(c, :z)`` forms this
    module (and ``common.rate_limiter``) writes, into (verb, attr, rhs) triples."""
    out: list = []
    for chunk in re.finditer(r"(ADD|SET)\s+(.*?)(?=\s+(?:ADD|SET)\s+|$)", expr):
        verb, body = chunk.group(1), chunk.group(2)
        for part in _split_commas(body):
            if verb == "ADD":
                attr, rhs = part.split()
            else:
                attr, rhs = (p.strip() for p in part.split("=", 1))
            out.append((verb, attr.strip(), rhs.strip()))
    return out


class FakeS3:
    """Bounded S3 client double keyed by object key. No network, no botocore."""

    def __init__(self, objects=None, get_error: Exception | None = None, put_error: Exception | None = None):
        self.objects = dict(objects or {})
        self.get_error = get_error
        self.put_error = put_error
        self.gets: list = []
        self.puts: list = []

    def get_object(self, Bucket=None, Key=None, **_kwargs):
        self.gets.append(Key)
        if self.get_error is not None:
            raise self.get_error
        if Key not in self.objects:
            raise RuntimeError(f"NoSuchKey: {Key}")
        return {"Body": io.BytesIO(json.dumps(self.objects[Key]).encode())}

    def put_object(self, Bucket=None, Key=None, Body=None, **_kwargs):
        self.puts.append((Key, Body))
        if self.put_error is not None:
            raise self.put_error
        self.objects[Key] = json.loads(Body)
        return {}


class FakeSecrets:
    def __init__(self, secrets=None, error: Exception | None = None):
        self.secrets = dict(secrets or {})
        self.error = error
        self.calls: list = []

    def get_secret_value(self, SecretId=None):
        self.calls.append(SecretId)
        if self.error is not None:
            raise self.error
        if SecretId not in self.secrets:
            raise RuntimeError(f"ResourceNotFoundException: {SecretId}")
        return {"SecretString": self.secrets[SecretId]}


class FakeBoto3:
    """Stands in for the ``boto3`` module in both site_api_social and
    site_api_common, so the real ``_load_s3_json`` runs against the fake bucket."""

    def __init__(self, s3: FakeS3, secrets: FakeSecrets):
        self._s3 = s3
        self._secrets = secrets

    def client(self, name, **_kwargs):
        if name == "s3":
            return self._s3
        if name == "secretsmanager":
            return self._secrets
        raise AssertionError(f"unexpected boto3 client {name!r} in an offline test")


# ──────────────────────────────────────────────────────────────────────────────
# 2. Fixtures — freeze the clocks, clear EVERY module-level cache
# ──────────────────────────────────────────────────────────────────────────────

SUBSCRIBER_SECRET = "s" * 64
RITUAL_SECRET = "r" * 64

CONTENT_FILTER = {
    "blocked_vices": ["No porn", "No marijuana"],
    "blocked_vice_keywords": ["porn", "marijuana", "weed"],
}


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    """Freeze both clocks and reset every warm-container global this module owns.

    These caches are real module state shared by every request a container serves;
    leaking one between tests would make a later test pass on a neighbour's data
    (and, for the catalog cache, is itself the subject of a test below).
    """
    freeze(DEFAULT_NOW)
    sac.set_request_id(None)
    monkeypatch.setattr(social, "datetime", _FrozenDatetime)
    monkeypatch.setattr(sac, "datetime", _FrozenDatetime)
    # Content filter pinned (loaded_at None == pinned, never TTL-expired) so
    # _is_blocked_vice is deterministic without an S3 round trip.
    monkeypatch.setattr(sac, "_content_filter_cache", CONTENT_FILTER)
    monkeypatch.setattr(sac, "_content_filter_cache_at", None)
    for name, value in (
        ("_token_secret_cache", None),
        ("_ritual_token_secret_cache", None),
        ("_challenges_cache", None),
        ("_challenges_cache_at", None),
        ("_challenge_catalog_cache", None),
        ("_library_ids_cache", (0.0, frozenset())),
        ("_cohort_config_cache", {}),
        ("_cohort_config_cache_ts", 0.0),
        ("_nudge_counts", {}),
        # #2237: the ONE in-memory fallback store, shared by every write door
        # (it replaced the per-endpoint `_nudge_rate_store` / `_finding_rate_store`).
        ("_FALLBACK_RATE_STORE", {}),
    ):
        monkeypatch.setattr(social, name, value)
    yield
    sac.set_request_id(None)
    freeze(DEFAULT_NOW)


def wire(monkeypatch, *, table=None, s3=None, secrets=None):
    """Install the fakes on both modules and return (table, s3, secrets)."""
    table = table if table is not None else FakeSocialTable()
    s3 = s3 if s3 is not None else FakeS3()
    secrets = (
        secrets
        if secrets is not None
        else FakeSecrets({social._SUBSCRIBER_TOKEN_SECRET_NAME: SUBSCRIBER_SECRET, social._RITUAL_TOKEN_SECRET_NAME: RITUAL_SECRET})
    )
    fake_boto = FakeBoto3(s3, secrets)
    monkeypatch.setattr(social, "table", table)
    monkeypatch.setattr(social, "boto3", fake_boto)
    monkeypatch.setattr(sac, "boto3", fake_boto)
    return table, s3, secrets


def post(body, ip="203.0.113.7", **event_extra) -> dict:
    return {"body": json.dumps(body) if not isinstance(body, str) else body, "headers": {"x-forwarded-for": ip}, **event_extra}


def get(params=None, ip="203.0.113.7") -> dict:
    return {"queryStringParameters": params or {}, "headers": {"x-forwarded-for": ip}}


def body_of(resp: dict) -> dict:
    return json.loads(resp["body"])


def ok_body(resp: dict) -> dict:
    assert resp["statusCode"] == 200, resp
    return json.loads(resp["body"])


# ──────────────────────────────────────────────────────────────────────────────
# 3. The endpoint SET — derived from the module, cross-checked against the router
# ──────────────────────────────────────────────────────────────────────────────


def _discover_endpoints() -> dict:
    """Every endpoint function this module defines, found structurally.

    Derived rather than enumerated: a 31st social endpoint joins every envelope
    contract below on the day it is written, instead of shipping untested.
    """
    out = {}
    for name, obj in vars(social).items():
        if not inspect.isfunction(obj) or obj.__module__ != social.__name__:
            continue
        if name.startswith("handle_") or name.startswith("_handle_"):
            out[name] = obj
    return out


ENDPOINTS = _discover_endpoints()


def test_the_discovered_endpoint_set_is_not_empty_so_no_contract_below_is_vacuous():
    assert len(ENDPOINTS) >= 25, sorted(ENDPOINTS)


@pytest.mark.parametrize("name", sorted(ENDPOINTS))
def test_every_social_endpoint_is_actually_wired_into_the_public_router(name):
    """A handler in this module that ``site_api_lambda`` never imports is dead code
    that still carries a write path — and, worse, is invisible to the route-level
    method allowlist. The check is against the router module's own namespace, so it
    covers both ``ROUTES`` and ``_SIMPLE_ROUTES`` without restating either."""
    assert getattr(router, name, None) is ENDPOINTS[name], f"{name} is not imported by web.site_api_lambda"


def _call(name, monkeypatch, **wire_kwargs):
    """Invoke an endpoint with a quiet platform, adapting to its arity."""
    wire(monkeypatch, **wire_kwargs)
    fn = ENDPOINTS[name]
    if len(inspect.signature(fn).parameters) == 0:
        return fn()
    return fn(get())


# ──────────────────────────────────────────────────────────────────────────────
# 4. HTTP envelope — what CloudFront and the browser see
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("name", sorted(ENDPOINTS))
def test_no_social_endpoint_500s_on_a_completely_quiet_platform(name, monkeypatch):
    """Day 1 of a cycle (and any S3 hiccup) is an empty platform. A 5xx here is what
    the site smoke test rolls the whole fleet back for; a 4xx is a legitimate
    "you didn't give me a valid request", but a 500 never is."""
    resp = _call(name, monkeypatch)
    assert resp["statusCode"] != 500, (name, resp)


@pytest.mark.parametrize("name", sorted(ENDPOINTS))
def test_every_social_endpoint_returns_a_json_object_the_browser_can_parse(name, monkeypatch):
    assert isinstance(body_of(_call(name, monkeypatch)), dict)


@pytest.mark.parametrize("name", sorted(ENDPOINTS))
def test_every_social_endpoint_ships_the_full_browser_security_header_set(name, monkeypatch):
    """Derived from CORS_HEADERS itself, so a NEW security header added there is
    enforced across all thirty endpoints on day one — including the ~15 that
    hand-roll their headers instead of going through ``_ok``."""
    headers = _call(name, monkeypatch)["headers"]
    for key, value in sac.CORS_HEADERS.items():
        assert headers.get(key) == value, f"{name} dropped {key}"


@pytest.mark.parametrize("name", sorted(ENDPOINTS))
def test_every_social_endpoint_sets_an_explicit_cache_control(name, monkeypatch):
    """These are CDN-fronted. An absent Cache-Control means CloudFront guesses —
    and on a WRITE endpoint a guess that caches is a correctness bug, not a
    performance one."""
    assert _call(name, monkeypatch)["headers"].get("Cache-Control"), name


def test_no_endpoint_hand_rolls_its_response_envelope(monkeypatch):
    """Fixed by #2221 (was an xfail on the two doors whose DEFAULT path hand-rolled
    it): 29 branches in this module built a bare
    ``{"statusCode": ..., "headers": {**CORS_HEADERS, ...}}`` dict, and every one of
    them dropped the ``x-request-id`` echo. This is the STRUCTURAL half of the fix —
    a dict display with a literal ``statusCode`` key is no longer expressible in the
    module, so a new door cannot reintroduce the class. ``_ok``/``_error``/
    ``_envelope`` — all three in ``site_api_common`` — are the only builders."""
    tree = ast.parse(pathlib.Path(inspect.getfile(social)).read_text())
    offenders = [
        n.lineno
        for n in ast.walk(tree)
        if isinstance(n, ast.Dict) and any(isinstance(k, ast.Constant) and k.value == "statusCode" for k in n.keys)
    ]
    assert offenders == [], f"hand-rolled response envelope(s) at line(s) {offenders}"
    # ...and the builder it must use really is the shared one, not a local re-spelling.
    assert social._envelope is sac._envelope


@pytest.mark.parametrize("name", sorted(ENDPOINTS))
def test_a_request_id_is_echoed_so_a_reader_complaint_reaches_a_log_line(name, monkeypatch):
    """``set_request_id`` is how "this page is wrong" is tied to a CloudWatch line.
    Every ``_ok``/``_error``/``_envelope`` response echoes it."""
    sac.set_request_id("req-social-123")
    resp = _call(name, monkeypatch)
    assert resp["headers"].get("x-request-id") == "req-social-123", name


# ──────────────────────────────────────────────────────────────────────────────
# 5. Subscriber verification — the token door
# ──────────────────────────────────────────────────────────────────────────────

CONFIRMED_EMAIL = "reader@example.com"


def _subscriber_row(email: str, status: str = "confirmed") -> dict:
    import hashlib

    return {
        "pk": "USER#matthew#SOURCE#subscribers",
        "sk": f"EMAIL#{hashlib.sha256(email.strip().lower().encode()).hexdigest()}",
        "status": status,
        "email": email,
    }


def _subscriber_table(*emails, status="confirmed") -> FakeSocialTable:
    return FakeSocialTable([_subscriber_row(e, status) for e in emails])


def test_a_confirmed_subscriber_is_handed_a_token_and_the_higher_question_limit(monkeypatch):
    wire(monkeypatch, table=_subscriber_table(CONFIRMED_EMAIL))
    body = ok_body(social._handle_verify_subscriber(get({"email": CONFIRMED_EMAIL})))
    assert body["limit"] == 20 and body["token"]


def test_the_subscriber_token_is_an_hmac_over_the_email_and_a_24_hour_expiry(monkeypatch):
    """Pinned end-to-end because this token is the ONLY thing standing between the
    5/hr anonymous ask limit and the 20/hr subscriber limit.

    NOTE (a real property of the module, not a test compromise): unlike every other
    timestamp here, `_generate_subscriber_token` reads `time.time()` directly rather
    than the module's `datetime`, so the frozen clock cannot reach it. The expiry is
    therefore asserted as an OFFSET from the real wall clock.
    """
    import base64
    import time as _time

    wire(monkeypatch, table=_subscriber_table(CONFIRMED_EMAIL))
    minted_at = int(_time.time())
    token = ok_body(social._handle_verify_subscriber(get({"email": CONFIRMED_EMAIL})))["token"]
    payload = base64.urlsafe_b64decode(token).decode()
    email, expires, sig = payload.rsplit(":", 2)
    # 86400s == 24h, the documented lifetime. A 2s tolerance covers the call itself.
    assert 86400 <= int(expires) - minted_at <= 86402
    assert email == CONFIRMED_EMAIL
    expected = hmac.new(SUBSCRIBER_SECRET.encode(), f"{email}:{expires}".encode(), digestmod="sha256").hexdigest()[:32]
    assert sig == expected


def test_the_token_signature_is_128_bits_of_the_hmac_not_the_whole_digest(monkeypatch):
    """32 hex chars == 128 bits. Pinned so a future "tidy-up" that shortens it
    further cannot silently weaken forgery resistance."""
    import base64

    wire(monkeypatch, table=_subscriber_table(CONFIRMED_EMAIL))
    token = ok_body(social._handle_verify_subscriber(get({"email": CONFIRMED_EMAIL})))["token"]
    assert len(base64.urlsafe_b64decode(token).decode().rsplit(":", 1)[1]) == 32


def test_an_email_that_is_only_pending_confirmation_gets_no_token(monkeypatch):
    """Double opt-in is the whole point: an unconfirmed address must not unlock the
    subscriber rate limit, or anyone can type any address and get it."""
    wire(monkeypatch, table=_subscriber_table(CONFIRMED_EMAIL, status="pending"))
    assert social._handle_verify_subscriber(get({"email": CONFIRMED_EMAIL}))["statusCode"] == 404


@pytest.mark.parametrize("email", ["", "not-an-email", "x" * 250 + "@y.com"])
def test_a_malformed_email_is_rejected_before_any_database_lookup(email, monkeypatch):
    table, _s3, _sec = wire(monkeypatch)
    assert social._handle_verify_subscriber(get({"email": email}))["statusCode"] == 400
    assert table.gets == [], "a malformed address must not cost a DDB read"


def test_a_database_outage_denies_the_token_rather_than_granting_it(monkeypatch):
    """Fail CLOSED: if the subscriber lookup can't run, nobody gets the elevated
    limit. Pinned because the except branch returns a bare False that is easy to
    invert during a refactor."""
    wire(monkeypatch, table=FakeSocialTable([_subscriber_row(CONFIRMED_EMAIL)], fail={"get_item"}))
    assert social._handle_verify_subscriber(get({"email": CONFIRMED_EMAIL}))["statusCode"] == 404


def test_the_verify_response_is_never_cached_by_the_cdn(monkeypatch):
    """A cached token response would hand one reader's token to the next."""
    wire(monkeypatch, table=_subscriber_table(CONFIRMED_EMAIL))
    resp = social._handle_verify_subscriber(get({"email": CONFIRMED_EMAIL}))
    assert resp["headers"]["Cache-Control"] == "no-store"


def test_a_missing_signing_secret_is_a_loud_failure_not_a_derivable_key(monkeypatch):
    """#106 removed the "derive the secret from the Anthropic key" fallback on
    purpose. Pinned so it cannot come back as a silent except-branch."""
    wire(monkeypatch, table=_subscriber_table(CONFIRMED_EMAIL), secrets=FakeSecrets({}))
    with pytest.raises(RuntimeError):
        social._handle_verify_subscriber(get({"email": CONFIRMED_EMAIL}))


def _drive_verify(n, *, email=lambda i: f"probe{i}@example.com", ip="203.0.113.7") -> list:
    """n consecutive verify lookups from one IP; returns the status codes in order."""
    return [social._handle_verify_subscriber(get({"email": email(i)}, ip=ip))["statusCode"] for i in range(n)]


def test_subscriber_lookups_from_one_ip_are_rate_limited_like_every_other_public_door(monkeypatch):
    """#2239. Was an unmetered oracle: 200 consecutive lookups from one IP each
    reached `_is_confirmed_subscriber` and therefore DynamoDB.

    The budget is hand-derived, not read back off the code: `VERIFY_SUBSCRIBER_RATE_LIMIT`
    lookups succeed and the very next one is refused, because `common.rate_limiter`
    admits while `count <= limit`.
    """
    table, _s3, _sec = wire(monkeypatch, table=_subscriber_table(CONFIRMED_EMAIL))
    limit = social.VERIFY_SUBSCRIBER_RATE_LIMIT
    statuses = _drive_verify(limit + 4)

    assert statuses[:limit] == [404] * limit, statuses
    assert statuses[limit:] == [429] * 4, statuses
    # The refused ones must be refused BEFORE the roster lookup, or the limiter
    # caps the leak but not the DDB spend it was also filed for.
    assert len(table.gets) == limit, f"a 429 still cost a subscriber read ({len(table.gets)} reads for {limit + 4} probes)"


def test_the_rate_limit_is_keyed_on_the_caller_not_on_the_address_being_probed(monkeypatch):
    """The whole point is enumeration. If the counter keyed on the email too, every
    new probe address would arrive with a fresh budget and the limit would police
    nothing — the exact `guard exists but guards nothing` shape."""
    wire(monkeypatch, table=_subscriber_table(CONFIRMED_EMAIL))
    limit = social.VERIFY_SUBSCRIBER_RATE_LIMIT
    # Every request uses a DIFFERENT address; one IP.
    assert _drive_verify(limit + 1)[-1] == 429
    # A different IP still gets its own budget — this is per-caller, not global.
    assert _drive_verify(1, ip="198.51.100.9")[0] == 404


def test_a_confirmed_and_an_unknown_address_are_metered_by_the_SAME_counter(monkeypatch):
    """Otherwise an attacker gets `limit` free hits/hr per outcome class, and the
    404 half — the half that answers `is this address a subscriber?` — would be the
    one with its own untouched budget."""
    wire(monkeypatch, table=_subscriber_table(CONFIRMED_EMAIL))
    limit = social.VERIFY_SUBSCRIBER_RATE_LIMIT
    # Spend the whole budget on the CONFIRMED address (200s), then probe a stranger.
    hits = _drive_verify(limit, email=lambda i: CONFIRMED_EMAIL)
    assert hits == [200] * limit, hits
    assert social._handle_verify_subscriber(get({"email": "someone-else@example.com"}))["statusCode"] == 429


def test_the_refusal_tells_the_caller_when_to_come_back_and_is_never_cached(monkeypatch):
    """A 429 cached by CloudFront would lock a whole NAT out for the TTL."""
    wire(monkeypatch, table=_subscriber_table(CONFIRMED_EMAIL))
    _drive_verify(social.VERIFY_SUBSCRIBER_RATE_LIMIT)
    resp = social._handle_verify_subscriber(get({"email": CONFIRMED_EMAIL}))
    assert resp["statusCode"] == 429
    assert resp["headers"]["Cache-Control"] == "no-store"
    assert int(resp["headers"]["Retry-After"]) > 0


def test_the_limiter_fails_CLOSED_when_dynamodb_cannot_meter(monkeypatch):
    """#2239: fail-open here would mean a DDB blip reopens the unmetered
    enumeration window. Nothing legitimate is lost — with DDB down
    `_is_confirmed_subscriber` returns False and the door 404s for everyone
    anyway, so the fail-open branch protects no working flow."""
    wire(monkeypatch, table=FakeSocialTable([_subscriber_row(CONFIRMED_EMAIL)], fail={"update_item"}))
    assert social._handle_verify_subscriber(get({"email": CONFIRMED_EMAIL}))["statusCode"] == 429


# The "shared limiter module went missing" arm is NOT re-stated here: this door
# now appears in the AST-derived `RATE_LIMITED_DOORS` set below, so the
# `_RATE_LIMITER_READY = False` mutation sweep (#2237) picks it up automatically.


# ── the 200-vs-404 distinction: REVIEWED and explicitly ACCEPTED (#2239) ───────


def test_the_membership_distinction_is_accepted_and_metered_rather_than_obscured(monkeypatch):
    """#2239 acceptance item 3. The status-code distinction was reviewed and kept.

    Reason, pinned here so a later "tidy-up" does not mistake obfuscation for a
    fix: the endpoint's contract is to mint a credential IFF the supplied address
    is confirmed, so ANY response carrying the token is a perfect oracle whatever
    its status code. Uniforming 200/404 moves the signal from `resp.status` to
    `"token" in body` — which the sole client (`site/legacy/ask/index.html`) already
    branches on — and buys nothing. Closing it for real means not answering
    synchronously at all (mail the token, so issuance requires proof of control of
    the address), which is a product change, not a patch.

    So this test asserts the two things that ARE true after #2239: the distinction
    is still observable, and it is no longer free.
    """
    wire(monkeypatch, table=_subscriber_table(CONFIRMED_EMAIL))
    member = social._handle_verify_subscriber(get({"email": CONFIRMED_EMAIL}))
    stranger = social._handle_verify_subscriber(get({"email": "someone-else@example.com"}))

    # Accepted: membership remains distinguishable...
    assert (member["statusCode"], stranger["statusCode"]) == (200, 404)
    assert "token" in body_of(member) and "token" not in body_of(stranger)
    # ...and BOTH answers came out of the one per-IP budget, which is the mitigation.
    remaining = social.VERIFY_SUBSCRIBER_RATE_LIMIT - 2
    assert _drive_verify(remaining + 1)[-1] == 429


# ── subscriber count ──────────────────────────────────────────────────────────


def test_the_public_subscriber_count_counts_only_confirmed_records(monkeypatch):
    """Hand-derived: three rows seeded, two confirmed and one pending, so the
    social-proof number on the homepage is 2 — not 3."""
    rows = [_subscriber_row("a@x.com"), _subscriber_row("b@x.com"), _subscriber_row("c@x.com", status="pending")]
    wire(monkeypatch, table=FakeSocialTable(rows))
    assert ok_body(social.handle_subscriber_count())["count"] == 2


def test_a_database_outage_reports_an_unknown_subscriber_count_not_a_factual_zero(monkeypatch):
    wire(monkeypatch, table=FakeSocialTable([_subscriber_row("a@x.com")], fail={"query"}))
    assert ok_body(social.handle_subscriber_count())["count"] is None


# ──────────────────────────────────────────────────────────────────────────────
# 6. Nudges + reader submissions — the anonymous write doors
# ──────────────────────────────────────────────────────────────────────────────


def test_a_nudge_category_outside_the_allowlist_is_rejected(monkeypatch):
    """The allowlist is derived from NUDGE_CATEGORIES itself, so a new category
    added there is automatically accepted here and only genuinely-unknown values
    are asserted rejected."""
    table, _s3, _sec = wire(monkeypatch)
    assert social._handle_nudge(post({"category": "definitely-not-a-category"}))["statusCode"] == 400
    assert table.updates == [], "a rejected category must not touch the rate-limit partition"


@pytest.mark.parametrize("category", sorted(social.NUDGE_CATEGORIES))
def test_every_declared_nudge_category_is_accepted_and_labelled(category, monkeypatch):
    wire(monkeypatch)
    body = ok_body(social._handle_nudge(post({"category": category})))
    assert body["category"] == category and body["label"] == social.NUDGE_LABELS[category]


def test_every_nudge_category_has_a_reader_facing_label(monkeypatch):
    """Derived set guard: a category added to NUDGE_CATEGORIES without a label
    would raise KeyError inside the 200 path — a 502 on a public POST."""
    assert social.NUDGE_CATEGORIES <= set(social.NUDGE_LABELS)


def test_a_second_nudge_in_the_same_category_from_the_same_ip_is_refused(monkeypatch):
    wire(monkeypatch)
    assert social._handle_nudge(post({"category": "watching"}))["statusCode"] == 200
    assert social._handle_nudge(post({"category": "watching"}))["statusCode"] == 429


def test_a_nudge_in_a_different_category_still_goes_through(monkeypatch):
    """Per-category budgets: reacting once must not consume every reaction."""
    wire(monkeypatch)
    social._handle_nudge(post({"category": "watching"}))
    assert social._handle_nudge(post({"category": "you_got_this"}))["statusCode"] == 200


def test_a_nudge_from_a_different_ip_is_independent(monkeypatch):
    wire(monkeypatch)
    social._handle_nudge(post({"category": "watching"}, ip="203.0.113.7"))
    assert social._handle_nudge(post({"category": "watching"}, ip="198.51.100.9"))["statusCode"] == 200


def test_the_client_cannot_forge_its_own_rate_limit_identity(monkeypatch):
    """`extract_client_ip` takes the LAST X-Forwarded-For hop — the one CloudFront
    appends. A client that prepends fake hops must still share one budget."""
    wire(monkeypatch)
    social._handle_nudge(post({"category": "watching"}, ip="1.1.1.1, 203.0.113.7"))
    resp = social._handle_nudge(post({"category": "watching"}, ip="2.2.2.2, 203.0.113.7"))
    assert resp["statusCode"] == 429


def test_a_malformed_json_body_is_a_client_error_not_a_crash(monkeypatch):
    wire(monkeypatch)
    assert social._handle_nudge(post("{not json"))["statusCode"] == 400


# ── submit_finding ────────────────────────────────────────────────────────────

GOOD_FINDING = {"metric_a": "sleep", "metric_b": "hrv", "finding": "They move together on rest days."}


def test_a_reader_finding_lands_in_the_moderation_queue_not_on_the_site(monkeypatch):
    """Findings are captured with status=pending. Nothing a stranger types is ever
    published without Matthew promoting it."""
    _t, s3, _sec = wire(monkeypatch)
    ok_body(social._handle_submit_finding(post(GOOD_FINDING)))
    key, raw = s3.puts[0]
    assert key.startswith("generated/findings/") and json.loads(raw)["status"] == "pending"


def test_finding_html_is_stripped_before_it_is_stored(monkeypatch):
    _t, s3, _sec = wire(monkeypatch)
    social._handle_submit_finding(post({**GOOD_FINDING, "finding": "<script>alert(1)</script>they move together"}))
    assert "<script>" not in json.loads(s3.puts[0][1])["finding"]


@pytest.mark.parametrize(
    "field,cap",
    [("metric_a", 100), ("metric_b", 100), ("finding", 500), ("email", 254)],
)
def test_every_reader_supplied_finding_field_is_length_capped(field, cap, monkeypatch):
    """Unbounded reader text on a public POST is a DynamoDB/S3 cost and a render
    hazard. Each cap is pinned at the exact published boundary."""
    _t, s3, _sec = wire(monkeypatch)
    # The "@" is placed FIRST for the email case, so it survives truncation and the
    # field reaches the store rather than being rejected by the format check.
    overlong = ("a@" + "b" * (cap + 50)) if field == "email" else "a" * (cap + 50)
    social._handle_submit_finding(post({**GOOD_FINDING, field: overlong}))
    assert len(json.loads(s3.puts[0][1])[field]) <= cap


def test_a_finding_shorter_than_ten_characters_is_refused(monkeypatch):
    wire(monkeypatch)
    assert social._handle_submit_finding(post({**GOOD_FINDING, "finding": "short"}))["statusCode"] == 400


def test_a_retry_of_the_identical_finding_overwrites_rather_than_duplicating(monkeypatch):
    """The id is content-derived (ip + both metrics + text), so a network retry
    lands on the same S3 key instead of giving Matthew two things to triage."""
    _t, s3, _sec = wire(monkeypatch)
    first = ok_body(social._handle_submit_finding(post(GOOD_FINDING)))
    second = ok_body(social._handle_submit_finding(post(GOOD_FINDING)))
    assert first["finding_id"] == second["finding_id"]
    assert s3.puts[0][0] == s3.puts[1][0]


def test_the_fourth_finding_in_an_hour_from_one_ip_is_refused(monkeypatch):
    """FINDING_RATE_LIMIT is 3/hour; the limit is read from the constant so a
    policy change moves the test with it."""
    wire(monkeypatch)
    for i in range(social.FINDING_RATE_LIMIT):
        assert social._handle_submit_finding(post({**GOOD_FINDING, "finding": f"finding number {i} here"}))["statusCode"] == 200
    assert social._handle_submit_finding(post({**GOOD_FINDING, "finding": "one too many now"}))["statusCode"] == 429


def test_an_s3_outage_tells_the_reader_to_retry_instead_of_pretending_to_save(monkeypatch):
    wire(monkeypatch, s3=FakeS3(put_error=RuntimeError("s3 down")))
    assert social._handle_submit_finding(post(GOOD_FINDING))["statusCode"] == 503


def test_the_finding_door_rejects_blocked_vice_text_the_way_the_board_door_does(monkeypatch):
    wire(monkeypatch)
    assert social._handle_submit_finding(post({**GOOD_FINDING, "finding": "marijuana correlates with my sleep"}))["statusCode"] == 400


# ── board_question ────────────────────────────────────────────────────────────

GOOD_QUESTION = {"question": "How should I think about deload weeks?"}


def test_a_board_question_is_captured_pending_and_invokes_no_ai(monkeypatch):
    _t, s3, _sec = wire(monkeypatch)
    ok_body(social._handle_board_question(post(GOOD_QUESTION)))
    key, raw = s3.puts[0]
    assert key.startswith("generated/board_questions/") and json.loads(raw)["status"] == "pending"


def test_a_blocked_vice_question_is_refused_at_the_door(monkeypatch):
    _t, s3, _sec = wire(monkeypatch)
    assert social._handle_board_question(post({"question": "what about marijuana and recovery"}))["statusCode"] == 400
    assert s3.puts == [], "a rejected question must not reach the queue"


def test_a_readers_email_is_stored_privately_and_never_echoed_back(monkeypatch):
    """The reply address is PII. It goes to the private S3 record; the public
    response body must not contain it."""
    _t, s3, _sec = wire(monkeypatch)
    resp = social._handle_board_question(post({**GOOD_QUESTION, "email": "reader@example.com"}))
    assert json.loads(s3.puts[0][1])["email"] == "reader@example.com"
    assert "reader@example.com" not in resp["body"]


def test_the_fourth_board_question_in_an_hour_is_refused(monkeypatch):
    wire(monkeypatch)
    for i in range(social.BOARD_QUESTION_RATE_LIMIT):
        assert social._handle_board_question(post({"question": f"question number {i} for the board"}))["statusCode"] == 200
    assert social._handle_board_question(post({"question": "one question too many for now"}))["statusCode"] == 429


# ──────────────────────────────────────────────────────────────────────────────
# 7. The experiment library, votes, follows, detail
# ──────────────────────────────────────────────────────────────────────────────

LIBRARY_KEY = "site/config/experiment_library.json"

LIBRARY = {
    "version": "2.1.0",
    "pillars": {"sleep": {"label": "Sleep", "icon": "moon", "color": "#123456"}, "food": {"label": "Food", "icon": "plate"}},
    "pillar_order": ["food", "sleep"],
    "experiments": [
        {"id": "post-dinner-walk", "name": "Post-dinner walk", "pillar": "food"},
        {"id": "no-screens", "name": "No screens after 9", "pillar": "sleep"},
        {"id": "cold-plunge", "name": "Cold plunge", "pillar": "sleep"},
    ],
}


def _library_s3(library=None, extra=None) -> FakeS3:
    objects = {LIBRARY_KEY: library if library is not None else json.loads(json.dumps(LIBRARY))}
    objects.update(extra or {})
    return FakeS3(objects)


def test_the_experiment_library_groups_experiments_into_the_configured_pillar_order(monkeypatch):
    """`pillar_order` is the editorial order of the /protocols page; a group not
    named in it is appended rather than dropped."""
    wire(monkeypatch, s3=_library_s3())
    body = ok_body(social.handle_experiment_library())
    assert [p["id"] for p in body["pillars"]] == ["food", "sleep"]
    assert body["total_experiments"] == 3


def test_pillar_statistics_partition_every_experiment_exactly_once(monkeypatch):
    """active + completed + backlog must reconstruct total, or the pillar header
    shows counts that don't add up to the list beneath it."""
    wire(monkeypatch, s3=_library_s3())
    for pillar in ok_body(social.handle_experiment_library())["pillars"]:
        s = pillar["stats"]
        assert s["active"] + s["completed"] + s["backlog"] == s["total"] == len(pillar["experiments"])


def test_vote_counts_from_dynamodb_override_the_static_library_seed(monkeypatch):
    """Hand-derived: two library entries carry votes (7 and 2), the third none, so
    the page-level total is 7 + 2 + 0 = 9."""
    votes = [
        {"pk": "VOTES#experiment_library", "sk": "LIB#post-dinner-walk", "vote_count": 7},
        {"pk": "VOTES#experiment_library", "sk": "LIB#no-screens", "vote_count": 2},
    ]
    wire(monkeypatch, table=FakeSocialTable(votes), s3=_library_s3())
    body = ok_body(social.handle_experiment_library())
    by_id = {e["id"]: e for p in body["pillars"] for e in p["experiments"]}
    assert by_id["post-dinner-walk"]["votes"] == 7
    assert by_id["cold-plunge"]["votes"] == 0
    assert body["total_votes"] == 9


def test_an_active_run_lifts_its_library_entry_to_the_top_of_its_pillar(monkeypatch):
    """Within a pillar the sort key is (not active, -votes): an active run outranks
    a higher-voted backlog entry, because "running now" is the headline."""
    rows = [
        {"pk": "VOTES#experiment_library", "sk": "LIB#cold-plunge", "vote_count": 99},
        {
            "pk": "USER#matthew#SOURCE#experiments",
            "sk": "EXP#exp-1",
            "library_id": "no-screens",
            "status": "active",
            "start_date": "2026-05-08",
            "name": "No screens after 9",
        },
    ]
    wire(monkeypatch, table=FakeSocialTable(rows), s3=_library_s3())
    sleep = next(p for p in ok_body(social.handle_experiment_library())["pillars"] if p["id"] == "sleep")
    assert [e["id"] for e in sleep["experiments"]] == ["no-screens", "cold-plunge"]


def test_days_in_counts_the_start_day_as_day_one(monkeypatch):
    """Hand-derived against the frozen clock: start 2026-05-08, today 2026-05-10,
    difference 2 days, +1 for inclusive counting -> Day 3."""
    rows = [
        {
            "pk": "USER#matthew#SOURCE#experiments",
            "sk": "EXP#exp-1",
            "library_id": "no-screens",
            "status": "active",
            "start_date": "2026-05-08",
            "name": "No screens after 9",
        }
    ]
    wire(monkeypatch, table=FakeSocialTable(rows), s3=_library_s3())
    by_id = {e["id"]: e for p in ok_body(social.handle_experiment_library())["pillars"] for e in p["experiments"]}
    assert by_id["no-screens"]["days_in"] == 3


def test_an_experiment_matched_only_by_its_name_slug_still_shows_as_running(monkeypatch):
    """Older DDB experiments predate `library_id`; the slug fallback is what keeps
    them joined to the library card."""
    rows = [
        {
            "pk": "USER#matthew#SOURCE#experiments",
            "sk": "EXP#exp-9",
            "status": "active",
            "start_date": "2026-05-09",
            "name": "Post-dinner walk",
        }
    ]
    wire(monkeypatch, table=FakeSocialTable(rows), s3=_library_s3())
    by_id = {e["id"]: e for p in ok_body(social.handle_experiment_library())["pillars"] for e in p["experiments"]}
    assert by_id["post-dinner-walk"]["status"] == "active"


def test_a_pilot_phase_experiment_is_never_merged_into_the_public_library(monkeypatch):
    """ADR-058. `experiments` is EXPERIMENT_SCOPED in phase_taxonomy (asserted in
    the companion test below), so a pilot-tagged row must not reach a reader."""
    rows = [
        {
            "pk": "USER#matthew#SOURCE#experiments",
            "sk": "EXP#exp-pilot",
            "library_id": "cold-plunge",
            "status": "active",
            "start_date": "2026-05-01",
            "name": "Cold plunge",
            "phase": "pilot",
        }
    ]
    wire(monkeypatch, table=FakeSocialTable(rows), s3=_library_s3())
    by_id = {e["id"]: e for p in ok_body(social.handle_experiment_library())["pillars"] for e in p["experiments"]}
    assert by_id["cold-plunge"].get("status") != "active"


@pytest.mark.parametrize("source", ["experiments", "challenges"])
def test_the_partitions_this_module_phase_filters_are_the_ones_the_taxonomy_scopes(source):
    """The precondition for the ADR-058 tests: derived from phase_taxonomy itself,
    so a reclassification there is caught here rather than silently making the
    filter tests meaningless."""
    assert phase_taxonomy.SOURCE_CLASS.get(source) == "experiment_scoped"


def test_the_library_is_unavailable_rather_than_empty_when_s3_is_down(monkeypatch):
    """A 503 tells CloudFront and the reader "try again"; an empty 200 would be
    cached for 900s as "Matthew has no experiments"."""
    wire(monkeypatch, s3=FakeS3(get_error=RuntimeError("s3 down")))
    assert social.handle_experiment_library()["statusCode"] == 503


def test_a_vote_query_failure_degrades_to_zero_votes_without_losing_the_page(monkeypatch):
    """Votes are decoration; the library is the content. Fail-soft is right here —
    pinned so the non-fatal except cannot be tightened into a 503."""
    wire(monkeypatch, table=FakeSocialTable(fail={"query"}), s3=_library_s3())
    assert ok_body(social.handle_experiment_library())["total_experiments"] == 3


def test_the_experiment_library_filters_blocked_vice_entries_like_the_challenge_catalog_does(monkeypatch):
    """Fixed by #2240 (was xfail): the library surface now applies the same
    never-public-vocabulary screen the challenge routes at :1115/:1143 apply, on
    name AND id. The synthetic sentinel keeps a real blocked term out of this
    public repo's permanent history. The full derived surface SET — nine
    functions, not the two this test's original reason line named — is guarded in
    tests/test_experiment_surface_vice_screen_2240.py."""
    sentinel = _pin_synthetic_vice(monkeypatch)
    library = json.loads(json.dumps(LIBRARY))
    library["experiments"].append({"id": f"{sentinel}-taper", "name": f"{sentinel.title()} taper", "pillar": "sleep"})
    wire(monkeypatch, s3=_library_s3(library))
    ids = {e["id"] for p in ok_body(social.handle_experiment_library())["pillars"] for e in p["experiments"]}
    assert f"{sentinel}-taper" not in ids


def test_the_experiment_detail_route_404s_a_blocked_vice_entry(monkeypatch):
    """The sibling door #2240 closed at the same time: a screened id must 404
    rather than serve the entry (and must not distinguish itself from an absent id)."""
    sentinel = _pin_synthetic_vice(monkeypatch)
    library = json.loads(json.dumps(LIBRARY))
    library["experiments"].append({"id": f"{sentinel}-taper", "name": "Evening taper", "pillar": "sleep"})
    wire(monkeypatch, s3=_library_s3(library))
    resp = social._handle_experiment_detail({"queryStringParameters": {"id": f"{sentinel}-taper"}})
    assert resp["statusCode"] == 404
    # Only the caller's own id is echoed (the standard not-found message); none of
    # the entry's stored fields cross the boundary.
    assert "Evening taper" not in resp["body"]
    assert "pillar" not in resp["body"]


# ── experiment_vote ───────────────────────────────────────────────────────────


def test_a_vote_for_a_real_library_experiment_increments_the_public_counter(monkeypatch):
    table, _s3, _sec = wire(monkeypatch, s3=_library_s3())
    body = ok_body(social._handle_experiment_vote(post({"library_id": "post-dinner-walk"})))
    assert body == {"library_id": "post-dinner-walk", "new_count": 1}
    assert table.store[("VOTES#experiment_library", "LIB#post-dinner-walk")]["vote_count"] == 1


def test_a_second_vote_from_the_same_ip_within_a_day_is_refused(monkeypatch):
    table, _s3, _sec = wire(monkeypatch, s3=_library_s3())
    social._handle_experiment_vote(post({"library_id": "post-dinner-walk"}))
    resp = social._handle_experiment_vote(post({"library_id": "post-dinner-walk"}))
    assert resp["statusCode"] == 429
    assert table.store[("VOTES#experiment_library", "LIB#post-dinner-walk")]["vote_count"] == 1


def test_the_vote_dedup_row_expires_after_exactly_24_hours(monkeypatch):
    """The TTL is the whole rate limit — if it were absent the row would block the
    voter forever; if it were short the limit would be meaningless."""
    table, _s3, _sec = wire(monkeypatch, s3=_library_s3())
    social._handle_experiment_vote(post({"library_id": "post-dinner-walk"}))
    row = next(r for r in table.puts if str(r["sk"]).startswith("IP#"))
    assert row["ttl"] - row["voted_at"] == 86400


def test_voting_for_a_different_experiment_is_a_separate_budget(monkeypatch):
    wire(monkeypatch, s3=_library_s3())
    social._handle_experiment_vote(post({"library_id": "post-dinner-walk"}))
    assert social._handle_experiment_vote(post({"library_id": "no-screens"}))["statusCode"] == 200


def test_a_vote_for_an_id_that_is_not_in_the_library_is_rejected(monkeypatch):
    """Without the allowlist an attacker mints unbounded VOTES#experiment_library
    rows — a write amplification straight into Matthew's table."""
    table, _s3, _sec = wire(monkeypatch, s3=_library_s3())
    assert social._handle_experiment_vote(post({"library_id": "made-up-id"}))["statusCode"] == 400
    assert table.puts == []


def test_the_vote_allowlist_fails_closed_when_the_library_cannot_be_read(monkeypatch):
    """Fail CLOSED: an empty allowlist must 503, never "accept everything"."""
    table, _s3, _sec = wire(monkeypatch, s3=FakeS3(get_error=RuntimeError("s3 down")))
    assert social._handle_experiment_vote(post({"library_id": "post-dinner-walk"}))["statusCode"] == 503
    assert table.puts == []


def test_an_over_long_library_id_is_rejected_before_it_becomes_a_sort_key(monkeypatch):
    table, _s3, _sec = wire(monkeypatch, s3=_library_s3())
    assert social._handle_experiment_vote(post({"library_id": "x" * 81}))["statusCode"] == 400
    assert table.puts == []


def test_the_vote_allowlist_is_case_insensitive_because_the_id_is_lowercased(monkeypatch):
    wire(monkeypatch, s3=_library_s3())
    assert social._handle_experiment_vote(post({"library_id": "Post-Dinner-Walk"}))["statusCode"] == 200


# ── experiment_follow ─────────────────────────────────────────────────────────

FOLLOW = {"email": "reader@example.com", "library_id": "post-dinner-walk"}


def test_a_follow_records_interest_without_publishing_the_address(monkeypatch):
    table, _s3, _sec = wire(monkeypatch)
    resp = social._handle_experiment_follow(post(FOLLOW))
    assert ok_body(resp) == {"followed": True, "library_id": "post-dinner-walk"}
    assert "reader@example.com" not in resp["body"]
    assert table.store[("EXPERIMENT_FOLLOWS", "EMAIL#" + _hash16("reader@example.com") + "#EXP#post-dinner-walk")]["notified"] is False


def _hash16(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode()).hexdigest()[:16]


def test_following_the_same_experiment_twice_is_idempotent_not_an_error(monkeypatch):
    wire(monkeypatch)
    social._handle_experiment_follow(post(FOLLOW))
    assert ok_body(social._handle_experiment_follow(post(FOLLOW)))["already_following"] is True


@pytest.mark.parametrize("body", [{"email": "nope", "library_id": "x"}, {"email": "a@b.com", "library_id": ""}, {}])
def test_a_follow_with_a_bad_address_or_missing_id_is_rejected(body, monkeypatch):
    wire(monkeypatch)
    assert social._handle_experiment_follow(post(body))["statusCode"] == 400


def test_the_follow_limit_allows_the_ten_follows_it_advertises(monkeypatch):
    wire(monkeypatch)
    statuses = [social._handle_experiment_follow(post({**FOLLOW, "library_id": f"exp-{i}"}))["statusCode"] for i in range(10)]
    assert statuses.count(200) == 10, f"only {statuses.count(200)} of the advertised 10 follows were accepted"


def test_the_eleventh_follow_in_an_hour_is_refused(monkeypatch):
    """Whatever the exact boundary, the limiter must eventually fire — pinned so a
    refactor cannot remove it entirely."""
    wire(monkeypatch)
    statuses = [social._handle_experiment_follow(post({**FOLLOW, "library_id": f"exp-{i}"}))["statusCode"] for i in range(11)]
    assert 429 in statuses


# ── experiment_detail ─────────────────────────────────────────────────────────


def test_experiment_detail_joins_the_library_entry_with_its_runs_votes_and_followers(monkeypatch):
    rows = [
        {"pk": "VOTES#experiment_library", "sk": "LIB#post-dinner-walk", "vote_count": 4},
        {"pk": "EXPERIMENT_FOLLOWS", "sk": "EMAIL#aaa#EXP#post-dinner-walk", "library_id": "post-dinner-walk"},
        {
            "pk": "USER#matthew#SOURCE#experiments",
            "sk": "EXP#exp-1",
            "library_id": "post-dinner-walk",
            "status": "completed",
            "start_date": "2026-04-01",
            "end_date": "2026-04-15",
            "name": "Post-dinner walk",
        },
    ]
    wire(monkeypatch, table=FakeSocialTable(rows), s3=_library_s3())
    body = ok_body(social._handle_experiment_detail(get({"id": "post-dinner-walk"})))
    assert body["votes"] == 4
    assert body["follower_count"] == 1
    assert body["total_runs"] == 1 and body["completed_runs_count"] == 1
    # 2026-04-01 -> 2026-04-15 is 14 whole days.
    assert body["runs"][0]["days"] == 14


def test_an_experiment_still_running_measures_its_length_against_today(monkeypatch):
    """Hand-derived: start 2026-05-01, frozen today 2026-05-10 -> 9 days so far."""
    rows = [
        {
            "pk": "USER#matthew#SOURCE#experiments",
            "sk": "EXP#exp-1",
            "library_id": "post-dinner-walk",
            "status": "active",
            "start_date": "2026-05-01",
            "name": "Post-dinner walk",
        }
    ]
    wire(monkeypatch, table=FakeSocialTable(rows), s3=_library_s3())
    body = ok_body(social._handle_experiment_detail(get({"id": "post-dinner-walk"})))
    assert body["runs"][0]["days"] == 9
    assert body["active_run"]["experiment_id"] == "exp-1"


def test_an_unknown_experiment_id_is_a_404_not_a_fabricated_empty_card(monkeypatch):
    wire(monkeypatch, s3=_library_s3())
    assert social._handle_experiment_detail(get({"id": "does-not-exist"}))["statusCode"] == 404


def test_experiment_detail_requires_an_id(monkeypatch):
    wire(monkeypatch, s3=_library_s3())
    assert social._handle_experiment_detail(get({}))["statusCode"] == 400


def test_a_pilot_run_is_hidden_from_the_public_experiment_detail_page(monkeypatch):
    """ADR-058 again — the detail page is the one that publishes outcomes, grades
    and reflections, so a leaked pilot row here is the loudest kind."""
    rows = [
        {
            "pk": "USER#matthew#SOURCE#experiments",
            "sk": "EXP#exp-pilot",
            "library_id": "post-dinner-walk",
            "status": "completed",
            "start_date": "2026-04-01",
            "end_date": "2026-04-10",
            "name": "Post-dinner walk",
            "phase": "pilot",
            "outcome": "pilot-only outcome text",
        }
    ]
    wire(monkeypatch, table=FakeSocialTable(rows), s3=_library_s3())
    body = ok_body(social._handle_experiment_detail(get({"id": "post-dinner-walk"})))
    assert body["runs"] == [] and "pilot-only outcome text" not in json.dumps(body)


def test_the_library_and_the_detail_page_agree_on_what_counts_as_a_completed_run(monkeypatch):
    rows = [
        {
            "pk": "USER#matthew#SOURCE#experiments",
            "sk": "EXP#exp-1",
            "library_id": "post-dinner-walk",
            "status": "failed",
            "start_date": "2026-04-01",
            "end_date": "2026-04-10",
            "name": "Post-dinner walk",
        }
    ]
    wire(monkeypatch, table=FakeSocialTable(rows), s3=_library_s3())
    detail = ok_body(social._handle_experiment_detail(get({"id": "post-dinner-walk"})))
    library = ok_body(social.handle_experiment_library())
    food = next(p for p in library["pillars"] if p["id"] == "food")
    assert detail["completed_runs_count"] == food["stats"]["completed"]


# ──────────────────────────────────────────────────────────────────────────────
# 8. Challenges — the catalog, the live overlay, votes, follows, check-ins
# ──────────────────────────────────────────────────────────────────────────────

CATALOG_SITE_KEY = "site/config/challenges_catalog.json"
CATALOG_ROOT_KEY = "config/challenges_catalog.json"

CATALOG = {
    "challenges": [
        {"id": "cold-shower-finish", "name": "Cold shower finish", "status": "available", "category": "recovery", "duration_days": 7},
        {"id": "no-screens-9pm", "name": "No screens after 9", "status": "backlog", "category": "sleep", "duration_days": 14},
        {"id": "no-marijuana", "name": "No marijuana", "status": "available", "category": "vice"},
        {"id": "private-one", "name": "Private one", "status": "available", "public": False},
    ]
}


def _catalog_s3(catalog=None, both=True) -> FakeS3:
    catalog = catalog if catalog is not None else json.loads(json.dumps(CATALOG))
    objects = {CATALOG_SITE_KEY: catalog}
    if both:
        objects[CATALOG_ROOT_KEY] = catalog
    return FakeS3(objects)


def test_the_challenge_catalog_hides_entries_marked_private(monkeypatch):
    wire(monkeypatch, s3=_catalog_s3())
    ids = {c["id"] for c in ok_body(social.handle_challenge_catalog())["challenges"]}
    assert "private-one" not in ids


def test_the_challenge_catalog_merges_vote_counts_and_totals_them(monkeypatch):
    """Hand-derived: 5 votes on one public entry, 3 on another, 0 elsewhere -> 8.
    The private entry's votes must not be counted into the public total."""
    rows = [
        {"pk": "VOTES#challenges", "sk": "CH#cold-shower-finish", "vote_count": 5},
        {"pk": "VOTES#challenges", "sk": "CH#no-screens-9pm", "vote_count": 3},
        {"pk": "VOTES#challenges", "sk": "CH#private-one", "vote_count": 100},
    ]
    wire(monkeypatch, table=FakeSocialTable(rows), s3=_catalog_s3())
    body = ok_body(social.handle_challenge_catalog())
    assert body["total_votes"] == 8


def test_the_live_challenge_list_filters_blocked_vices_by_id_and_by_name(monkeypatch):
    """ER-06: a blocked keyword often lives only in the id while the display name
    is benign, so BOTH are checked. Pinned in both directions."""
    catalog = {
        "challenges": [
            {"id": "no-marijuana", "name": "Something benign", "status": "available"},
            {"id": "benign-id", "name": "No weed week", "status": "available"},
            {"id": "cold-shower-finish", "name": "Cold shower finish", "status": "available"},
        ]
    }
    wire(monkeypatch, s3=_catalog_s3(catalog))
    ids = {c["id"] for c in ok_body(social.handle_challenges())["challenges"]}
    assert ids == {"cold-shower-finish"}


def test_a_live_challenge_hides_the_catalog_entry_it_came_from(monkeypatch):
    """One card per challenge — the live row wins, so the reader never sees the
    same challenge listed twice with different statuses."""
    rows = [
        {
            "pk": "USER#matthew#SOURCE#challenges",
            "sk": "CHALLENGE#cold-shower-finish_2026-05-04",
            "name": "Cold shower finish",
            "status": "active",
            "duration_days": 7,
        }
    ]
    wire(monkeypatch, table=FakeSocialTable(rows), s3=_catalog_s3())
    body = ok_body(social.handle_challenges())
    cold = [c for c in body["challenges"] if c["id"] == "cold-shower-finish"]
    assert len(cold) == 1 and cold[0]["origin"] == "live"


def test_the_catalog_is_always_overlaid_so_a_reset_never_empties_the_page(monkeypatch):
    """A cycle reset wipes the live `challenges` partition. The catalog overlay is
    what keeps /protocols from going blank on Day 1."""
    wire(monkeypatch, s3=_catalog_s3())
    body = ok_body(social.handle_challenges())
    assert body["count"] > 0 and body["source"] == "catalog+live"


def test_the_challenge_summary_counts_add_up_to_the_list_it_describes(monkeypatch):
    rows = [
        {
            "pk": "USER#matthew#SOURCE#challenges",
            "sk": "CHALLENGE#live-one",
            "name": "Live one",
            "status": "active",
            "duration_days": 7,
            "daily_checkins": [{"date": "2026-05-08", "completed": True}, {"date": "2026-05-09", "completed": False}],
        }
    ]
    wire(monkeypatch, table=FakeSocialTable(rows), s3=_catalog_s3())
    body = ok_body(social.handle_challenges())
    s = body["summary"]
    assert s["total"] == body["count"]
    assert s["active"] + s["available"] + s["backlog"] + s["completed"] == s["total"]


def test_active_challenge_progress_is_derived_from_the_checkins_it_has(monkeypatch):
    """Hand-derived: 2 check-ins of a 7-day challenge, 1 of them completed.
    completion_pct = round(2/7*100) = 29; success_rate = round(1/2*100) = 50."""
    rows = [
        {
            "pk": "USER#matthew#SOURCE#challenges",
            "sk": "CHALLENGE#live-one",
            "name": "Live one",
            "status": "active",
            "duration_days": 7,
            "daily_checkins": [{"date": "2026-05-08", "completed": True}, {"date": "2026-05-09", "completed": False}],
        }
    ]
    wire(monkeypatch, table=FakeSocialTable(rows), s3=_catalog_s3())
    live = next(c for c in ok_body(social.handle_challenges())["challenges"] if c["id"] == "live-one")
    assert live["progress"] == {"checkin_days": 2, "completed_days": 1, "duration_days": 7, "completion_pct": 29, "success_rate": 50}


def test_a_pilot_phase_challenge_is_hidden_from_the_public_list(monkeypatch):
    rows = [
        {
            "pk": "USER#matthew#SOURCE#challenges",
            "sk": "CHALLENGE#pilot-one",
            "name": "Pilot one",
            "status": "active",
            "phase": "pilot",
        }
    ]
    wire(monkeypatch, table=FakeSocialTable(rows), s3=_catalog_s3())
    assert not [c for c in ok_body(social.handle_challenges())["challenges"] if c["id"] == "pilot-one"]


def test_a_challenge_with_no_checkins_yet_reports_an_unknown_success_rate_not_zero_percent(monkeypatch):
    rows = [
        {
            "pk": "USER#matthew#SOURCE#challenges",
            "sk": "CHALLENGE#fresh",
            "name": "Fresh",
            "status": "active",
            "duration_days": 7,
        }
    ]
    wire(monkeypatch, table=FakeSocialTable(rows), s3=_catalog_s3())
    live = next(c for c in ok_body(social.handle_challenges())["challenges"] if c["id"] == "fresh")
    assert live["progress"]["success_rate"] is None


def test_challenge_completion_percent_never_exceeds_one_hundred(monkeypatch):
    rows = [
        {
            "pk": "USER#matthew#SOURCE#challenges",
            "sk": "CHALLENGE#overrun",
            "name": "Overrun",
            "status": "active",
            "duration_days": 7,
            "daily_checkins": [{"date": f"2026-05-{d:02d}", "completed": True} for d in range(1, 11)],
        }
    ]
    wire(monkeypatch, table=FakeSocialTable(rows), s3=_catalog_s3())
    live = next(c for c in ok_body(social.handle_challenges())["challenges"] if c["id"] == "overrun")
    assert live["progress"]["completion_pct"] <= 100


def test_the_two_challenge_endpoints_read_the_two_mirrored_catalog_copies(monkeypatch):
    """A documented, guarded split (`deploy/config_mirror_audit.py`,
    tests/test_config_site_mirror_parity.py): `/api/challenge_catalog` reads
    `site/config/...` and `/api/challenges` reads the bucket-root `config/...`
    mirror. Pinned here because it means a mirror drift shows up as two endpoints
    on the same page disagreeing — which is the symptom to recognise."""
    s3 = _catalog_s3()
    wire(monkeypatch, s3=s3)
    social.handle_challenge_catalog()
    social.handle_challenges()
    assert CATALOG_SITE_KEY in s3.gets and CATALOG_ROOT_KEY in s3.gets


# ── challenge_vote / challenge_follow ─────────────────────────────────────────


def test_a_challenge_vote_increments_the_public_counter(monkeypatch):
    table, _s3, _sec = wire(monkeypatch, s3=_catalog_s3())
    assert ok_body(social._handle_challenge_vote(post({"catalog_id": "cold-shower-finish"}))) == {
        "catalog_id": "cold-shower-finish",
        "new_count": 1,
    }
    assert table.store[("VOTES#challenges", "CH#cold-shower-finish")]["vote_count"] == 1


def test_a_vote_for_a_private_challenge_is_refused(monkeypatch):
    """The allowlist is built from PUBLIC catalog entries only, so a reader cannot
    even confirm a private challenge exists by voting for its id."""
    table, _s3, _sec = wire(monkeypatch, s3=_catalog_s3())
    assert social._handle_challenge_vote(post({"catalog_id": "private-one"}))["statusCode"] == 404
    assert table.puts == []


def test_the_challenge_vote_allowlist_fails_closed_when_the_catalog_is_unavailable(monkeypatch):
    table, _s3, _sec = wire(monkeypatch, s3=FakeS3(get_error=RuntimeError("s3 down")))
    assert social._handle_challenge_vote(post({"catalog_id": "cold-shower-finish"}))["statusCode"] == 503
    assert table.puts == []


def test_a_repeat_challenge_vote_within_24_hours_is_refused(monkeypatch):
    wire(monkeypatch, s3=_catalog_s3())
    social._handle_challenge_vote(post({"catalog_id": "cold-shower-finish"}))
    assert social._handle_challenge_vote(post({"catalog_id": "cold-shower-finish"}))["statusCode"] == 429


def test_a_challenge_follow_is_stored_and_deduped(monkeypatch):
    wire(monkeypatch)
    first = ok_body(social._handle_challenge_follow(post({"email": "r@x.com", "catalog_id": "cold-shower-finish"})))
    second = ok_body(social._handle_challenge_follow(post({"email": "r@x.com", "catalog_id": "cold-shower-finish"})))
    assert first["followed"] is True and second["already_following"] is True


# ── challenge_checkin ─────────────────────────────────────────────────────────


def _active_challenge_table(checkins=None, duration=7) -> FakeSocialTable:
    return FakeSocialTable(
        [
            {
                "pk": "USER#matthew#SOURCE#challenges",
                "sk": "CHALLENGE#cold-shower-finish",
                "name": "Cold shower finish",
                "status": "active",
                "duration_days": duration,
                **({"daily_checkins": checkins} if checkins is not None else {}),
            }
        ]
    )


def test_a_checkin_on_an_active_challenge_is_recorded_with_todays_date(monkeypatch):
    table, _s3, _sec = wire(monkeypatch, table=_active_challenge_table())
    body = ok_body(social._handle_challenge_checkin(post({"challenge_id": "cold-shower-finish", "completed": True})))
    assert body["date"] == TODAY and body["total_checkins"] == 1
    stored = table.store[("USER#matthew#SOURCE#challenges", "CHALLENGE#cold-shower-finish")]["daily_checkins"]
    assert stored[0]["source"] == "website"


def test_a_checkin_replaces_the_same_days_earlier_entry_instead_of_appending(monkeypatch):
    """A double-tap or a network retry must not inflate completion_pct — the
    dedup is on `date`, and the last write wins."""
    table, _s3, _sec = wire(monkeypatch, table=_active_challenge_table(checkins=[{"date": TODAY, "completed": False}]))
    body = ok_body(social._handle_challenge_checkin(post({"challenge_id": "cold-shower-finish", "completed": True})))
    stored = table.store[("USER#matthew#SOURCE#challenges", "CHALLENGE#cold-shower-finish")]["daily_checkins"]
    assert body["total_checkins"] == 1 and len(stored) == 1 and stored[0]["completed"] is True


def test_checkin_completion_percent_is_checkins_over_duration(monkeypatch):
    """Hand-derived: 2 prior check-ins plus today's = 3 of a 10-day challenge ->
    round(3/10*100) = 30."""
    wire(
        monkeypatch,
        table=_active_challenge_table(checkins=[{"date": "2026-05-08"}, {"date": "2026-05-09"}], duration=10),
    )
    body = ok_body(social._handle_challenge_checkin(post({"challenge_id": "cold-shower-finish", "completed": True})))
    assert body["total_checkins"] == 3 and body["completion_pct"] == 30


def test_a_checkin_for_an_unknown_challenge_is_a_404(monkeypatch):
    wire(monkeypatch)
    assert social._handle_challenge_checkin(post({"challenge_id": "nope", "completed": True}))["statusCode"] == 404


def test_a_checkin_for_a_challenge_that_is_not_active_is_refused(monkeypatch):
    table = FakeSocialTable([{"pk": "USER#matthew#SOURCE#challenges", "sk": "CHALLENGE#done", "name": "Done", "status": "completed"}])
    wire(monkeypatch, table=table)
    assert social._handle_challenge_checkin(post({"challenge_id": "done", "completed": True}))["statusCode"] == 400


def test_a_checkin_missing_the_completed_flag_is_rejected(monkeypatch):
    """`completed is None` — not falsiness — so an explicit `false` still counts."""
    wire(monkeypatch, table=_active_challenge_table())
    assert social._handle_challenge_checkin(post({"challenge_id": "cold-shower-finish"}))["statusCode"] == 400
    assert social._handle_challenge_checkin(post({"challenge_id": "cold-shower-finish", "completed": False}))["statusCode"] == 200


def test_a_second_checkin_for_the_same_challenge_from_one_ip_in_a_day_is_refused(monkeypatch):
    wire(monkeypatch, table=_active_challenge_table())
    social._handle_challenge_checkin(post({"challenge_id": "cold-shower-finish", "completed": True}))
    resp = social._handle_challenge_checkin(post({"challenge_id": "cold-shower-finish", "completed": True}))
    assert resp["statusCode"] == 429


def test_a_checkin_date_that_is_not_a_calendar_date_is_rejected(monkeypatch):
    wire(monkeypatch, table=_active_challenge_table())
    resp = social._handle_challenge_checkin(post({"challenge_id": "cold-shower-finish", "completed": True, "date": "not-a-date"}))
    assert resp["statusCode"] == 400


# ── #2238: the check-in `note` — the module's only reader free text that reaches
#    a public payload. FIXED: HTML-stripped + vice-screened at the write door AND
#    re-screened on the read door (rows stored before the fix are still in the
#    table and no backfill rewrites Matthew's own challenge records).


SENTINEL_VICE = "zzsyntheticvice"


def _pin_synthetic_vice(monkeypatch) -> str:
    """Replace the pinned content filter with a SYNTHETIC vocabulary.

    Repo convention (#2203/#2230/#2253, public repo + permanent edit history): no
    real blocked term is ever a source literal in a test. `_is_blocked_vice` is a
    case-folded substring match over `blocked_vice_keywords`, so a synthetic
    keyword drives the identical code path a real one would.
    """
    monkeypatch.setattr(sac, "_content_filter_cache", {"blocked_vices": [], "blocked_vice_keywords": [SENTINEL_VICE]})
    monkeypatch.setattr(sac, "_content_filter_cache_at", None)
    return SENTINEL_VICE


def _published_challenges(monkeypatch) -> str:
    """The public GET /api/challenges body, catalog overlay emptied so only the
    live row (with its check-ins) is under test."""
    monkeypatch.setattr(social, "_challenges_cache", {"challenges": []})
    monkeypatch.setattr(social, "_challenges_cache_at", None)
    return json.dumps(ok_body(social.handle_challenges()))


def test_a_checkin_note_containing_markup_is_html_stripped_before_storage(monkeypatch):
    """Kills the write-door sanitise (`note = _sanitise_note(...)`). The two sibling
    capture doors in this file have run this exact `re.sub` since they shipped."""
    table, _s3, _sec = wire(monkeypatch, table=_active_challenge_table())
    resp = social._handle_challenge_checkin(
        post({"challenge_id": "cold-shower-finish", "completed": True, "note": "<script>alert(1)</script>felt strong"})
    )
    assert resp["statusCode"] == 200
    stored = table.store[("USER#matthew#SOURCE#challenges", "CHALLENGE#cold-shower-finish")]["daily_checkins"]
    assert "<script>" not in stored[0]["note"] and "felt strong" in stored[0]["note"]


def test_a_checkin_note_carrying_blocked_vocabulary_is_refused_at_the_door(monkeypatch):
    """Kills the write-door `if _is_blocked_vice(note): return _error(400, ...)` —
    the `_handle_board_question`:1691 precedent, applied to the one free-text field
    that was missing it."""
    blocked = _pin_synthetic_vice(monkeypatch)
    table, _s3, _sec = wire(monkeypatch, table=_active_challenge_table())
    resp = social._handle_challenge_checkin(post({"challenge_id": "cold-shower-finish", "completed": True, "note": f"day 3 {blocked}"}))
    assert resp["statusCode"] == 400
    stored = table.store[("USER#matthew#SOURCE#challenges", "CHALLENGE#cold-shower-finish")].get("daily_checkins")
    assert not stored, "a refused check-in must not have been written at all"


def test_a_plain_text_checkin_note_still_round_trips(monkeypatch):
    """The happy path the AC protects: an ordinary note is untouched by either screen."""
    _pin_synthetic_vice(monkeypatch)
    wire(monkeypatch, table=_active_challenge_table())
    assert (
        social._handle_challenge_checkin(post({"challenge_id": "cold-shower-finish", "completed": True, "note": "30 seconds cold"}))[
            "statusCode"
        ]
        == 200
    )
    assert "30 seconds cold" in _published_challenges(monkeypatch)


def test_a_reader_supplied_checkin_note_is_not_published_raw_on_the_public_challenge_route(monkeypatch):
    """End-to-end, the shape the discovering agent drove: POST a note carrying both
    markup and blocked vocabulary, then read the public route."""
    blocked = _pin_synthetic_vice(monkeypatch)
    wire(monkeypatch, table=_active_challenge_table())
    social._handle_challenge_checkin(
        post({"challenge_id": "cold-shower-finish", "completed": True, "note": f"<script>alert(1)</script>{blocked}"})
    )
    published = _published_challenges(monkeypatch)
    assert "<script>" not in published and blocked not in published


def test_a_note_stored_before_the_screen_landed_is_still_withheld_from_the_public_route(monkeypatch):
    """Kills the READ-side screen (`_public_checkins` in `handle_challenges`).

    The write door only protects notes submitted from now on. Rows already in
    `USER#matthew#SOURCE#challenges` — written while the door was open — are
    published by `handle_challenges` on every request, so the screen has to run on
    the way out too. Fixture writes the row directly, bypassing the write door.
    """
    blocked = _pin_synthetic_vice(monkeypatch)
    legacy = [{"date": TODAY, "completed": True, "note": f"<b>bold</b> {blocked} and some prose"}]
    wire(monkeypatch, table=_active_challenge_table(checkins=legacy))
    published = _published_challenges(monkeypatch)
    assert blocked not in published, "a pre-existing blocked note is still published on /api/challenges"
    assert "<b>" not in published, "a pre-existing markup note is still published on /api/challenges"


def test_screening_a_stored_note_does_not_drop_the_checkin_day_itself(monkeypatch):
    """The withheld thing is the stranger's text, not Matthew's progress: the
    check-in day survives and the completion arithmetic is unchanged."""
    blocked = _pin_synthetic_vice(monkeypatch)
    legacy = [{"date": "2026-05-09", "completed": True, "note": blocked}, {"date": TODAY, "completed": True}]
    wire(monkeypatch, table=_active_challenge_table(checkins=legacy))
    live = json.loads(_published_challenges(monkeypatch))["challenges"][0]
    assert live["progress"] == {
        "checkin_days": 2,
        "completed_days": 2,
        "duration_days": 7,
        "completion_pct": 29,  # round(2/7*100) == 29
        "success_rate": 100,
    }
    assert [c.get("note") for c in live["daily_checkins"]] == [None, None]


# ──────────────────────────────────────────────────────────────────────────────
# 9. The rate-limit guard SET — mutation-proved, not taken on trust
# ──────────────────────────────────────────────────────────────────────────────


def _functions_reading_the_rate_limiter_flag() -> set:
    """Every function in the module that reads `_RATE_LIMITER_READY` directly.

    AST-derived, never hand-listed. `_RATE_LIMITER_READY` is set False by an import
    guard at module load (:73-76), so every function that branches on it for itself
    is a function that can forget its fallback — which is precisely how #2237
    happened: five of the seven doors that open-coded the flag either had no `else`
    at all or an `else` that granted the write unconditionally.

    #2237 collapsed the module to a single reader, `_rate_check`. The invariant is
    now structural: a new write door CANNOT open-code the flag and CANNOT forget a
    fallback, because there is exactly one fallback and one place to reach it.
    """
    tree = ast.parse(pathlib.Path(inspect.getfile(social)).read_text())
    parents = {c: p for p in ast.walk(tree) for c in ast.iter_child_nodes(p)}
    readers = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Name) and node.id == "_RATE_LIMITER_READY" and isinstance(node.ctx, ast.Load)):
            continue
        cur = node
        while cur in parents:
            cur = parents[cur]
            if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):
                readers.add(cur.name)
                break
        else:
            readers.add("<module>")  # the import guard's own assignment site
    return readers


def test_the_rate_limiter_flag_is_read_in_exactly_one_function():
    """#2237's structural fix, pinned. If this reds because a handler started
    branching on the flag itself, that handler needs `_rate_check`, not an `else`."""
    assert _functions_reading_the_rate_limiter_flag() == {"_rate_check"}, sorted(_functions_reading_the_rate_limiter_flag())


def _handlers_using_the_rate_chokepoint() -> set:
    """Every handler that calls `_rate_check` — the derived set of rate-limited
    public write doors. A new door joins the mutation sweep below automatically."""
    tree = ast.parse(pathlib.Path(inspect.getfile(social)).read_text())
    users = set()
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.FunctionDef):
            continue
        for node in ast.walk(fn):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_rate_check":
                users.add(fn.name)
    return users


RATE_LIMITED_DOORS = _handlers_using_the_rate_chokepoint()


def test_the_rate_limited_write_door_set_is_discoverable():
    assert len(RATE_LIMITED_DOORS) >= 7, sorted(RATE_LIMITED_DOORS)


_FLAG_DRIVERS = {
    "_handle_challenge_checkin": lambda: post({"challenge_id": "cold-shower-finish", "completed": True}),
    "_handle_experiment_suggest": lambda: post({"idea": "try a longer deload week please"}),
    "_handle_cohort_submit": lambda: post({"value": 55}),
    "_handle_ritual_log": lambda: get(_signed_ritual_params()),
    "_handle_board_question": lambda: post({"question": "what should i read about zone 2"}),
    "_handle_nudge": lambda: post({"category": "watching"}),
    "_handle_submit_finding": lambda: post(GOOD_FINDING),
    # #2239 — a GET, not a POST, but it goes through the same chokepoint and so
    # joins the derived sweep automatically. Driven with an address that is NOT on
    # the roster: the 404 branch is the one an enumerator actually uses.
    "_handle_verify_subscriber": lambda: get({"email": "probe@example.com"}),
}


def test_every_rate_limited_door_has_a_driver_registered():
    """The derived-SET guard's own guard: a new write door must be given a driver
    here or the mutation sweep below would silently skip it."""
    assert RATE_LIMITED_DOORS <= set(_FLAG_DRIVERS), sorted(RATE_LIMITED_DOORS - set(_FLAG_DRIVERS))


@pytest.mark.parametrize("name", sorted(RATE_LIMITED_DOORS))
def test_a_write_endpoint_still_limits_when_the_shared_rate_limiter_is_unavailable(name, monkeypatch):
    """#2237, mutation-proved. Simulate the import failure (`_RATE_LIMITER_READY`
    False — exactly what the module-load `except` sets) and drive 40 anonymous
    writes at each derived door. Every one must refuse the excess.

    Against pre-#2237 code this reds on five of the seven doors with 40x200.
    """
    monkeypatch.setattr(social, "_RATE_LIMITER_READY", False)
    wire(monkeypatch, table=_active_challenge_table(), s3=_cohort_and_challenge_s3())
    statuses = {ENDPOINTS[name](_FLAG_DRIVERS[name]())["statusCode"] for _ in range(40)}
    assert 429 in statuses, f"{name} accepted 40 anonymous writes with no limit"


@pytest.mark.parametrize("name", sorted(RATE_LIMITED_DOORS))
def test_the_same_write_endpoint_does_limit_while_the_shared_limiter_is_present(name, monkeypatch):
    """The control arm: with the shared limiter present every door refuses the
    excess too, so the test above measures the FALLBACK and not the limiter."""
    wire(monkeypatch, table=_active_challenge_table(), s3=_cohort_and_challenge_s3())
    statuses = {ENDPOINTS[name](_FLAG_DRIVERS[name]())["statusCode"] for _ in range(40)}
    assert 429 in statuses


def test_the_degraded_limiter_refuses_rather_than_admits_once_its_store_is_full(monkeypatch):
    """The in-memory fallback is per-container, so it can only be a bound if it is
    itself bounded. At capacity it FAILS CLOSED — the distributed flood ends in
    429s, not in an unmetered write path plus an ever-growing dict."""
    monkeypatch.setattr(social, "_RATE_LIMITER_READY", False)
    monkeypatch.setattr(social, "_FALLBACK_STORE_MAX_KEYS", 2)
    wire(monkeypatch, table=_active_challenge_table())
    # Two distinct IPs fill the store; a third finds it full and is refused.
    for ip in ("198.51.100.1", "198.51.100.2"):
        assert social._handle_challenge_checkin(post({"challenge_id": "cold-shower-finish", "completed": True}, ip=ip))["statusCode"] == 200
    third = social._handle_challenge_checkin(post({"challenge_id": "cold-shower-finish", "completed": True}, ip="198.51.100.3"))
    assert third["statusCode"] == 429


def _post_endpoints() -> dict:
    """Every POST endpoint of this module, DERIVED from the router's own method
    allowlist (`site_api_lambda._SIMPLE_ROUTES`) rather than hand-listed."""
    out = {}
    for path, (methods, fn) in router._SIMPLE_ROUTES.items():
        if methods and "POST" in methods and getattr(fn, "__module__", "") == social.__name__:
            out[fn.__name__] = (path, fn)
    return out


POST_ENDPOINTS = _post_endpoints()


def test_the_post_endpoint_set_is_derived_and_non_empty():
    assert len(POST_ENDPOINTS) >= 10, sorted(POST_ENDPOINTS)


@pytest.mark.parametrize("name", sorted(POST_ENDPOINTS))
def test_a_malformed_body_on_any_public_post_door_is_a_client_error_not_a_server_error(name, monkeypatch):
    """Garbage bytes arrive at a public POST every day. Each door must answer 4xx —
    a 500 both misleads the reader and pollutes the 5xx alarm this Lambda is
    watched by.

    Fixed by #2221 (was an xfail on `_handle_experiment_suggest`, the module's only
    POST handler with no dedicated `except` around `json.loads`)."""
    wire(monkeypatch, table=_active_challenge_table(), s3=_cohort_and_challenge_s3())
    assert POST_ENDPOINTS[name][1](post("{not valid json"))["statusCode"] != 500


@pytest.mark.parametrize("name", sorted(POST_ENDPOINTS))
def test_no_public_post_door_raises_when_dynamodb_refuses_every_write(name, monkeypatch):
    """A DDB outage must surface as a status code, not as an unhandled exception —
    an exception out of the handler becomes a 502 at the Function URL, which is
    what the smoke test rolls the fleet back for."""
    table = _active_challenge_table()
    table.fail = {"put_item", "update_item"}
    wire(monkeypatch, table=table, s3=_cohort_and_challenge_s3())
    resp = POST_ENDPOINTS[name][1](_FLAG_DRIVERS.get(name, lambda: post({}))())
    assert isinstance(resp.get("statusCode"), int)
    assert isinstance(json.loads(resp["body"]), dict)


def _write_failing_table(items=None) -> FakeSocialTable:
    """A table whose reads work but whose persisting write fails — the shape of a
    throttled or partially-degraded DynamoDB, which is what actually happens."""
    table = _active_challenge_table() if items is None else FakeSocialTable(items)
    table.fail = {"update_item"}
    return table


def test_a_vote_whose_counter_increment_fails_is_reported_as_failed_not_as_recorded(monkeypatch):
    """The dedup row is written first, so a failed increment leaves the voter
    consumed. Telling them "voted!" anyway would show a count that never moved."""
    wire(monkeypatch, table=_write_failing_table([]), s3=_library_s3())
    assert social._handle_experiment_vote(post({"library_id": "post-dinner-walk"}))["statusCode"] == 500


def test_a_ritual_tap_that_cannot_be_persisted_reports_failure(monkeypatch):
    """The tap comes from an email client with no retry UI — a false "logged!"
    would silently lose the day's reading."""
    wire(monkeypatch, table=_write_failing_table([]))
    assert social._handle_ritual_log(get(_signed_ritual_params()))["statusCode"] == 500


def test_a_self_cert_whose_counter_increment_fails_reports_failure(monkeypatch):
    wire(monkeypatch, table=_write_failing_table([]))
    assert social._handle_replicate_certify(post({}))["statusCode"] == 500


def test_a_cohort_submission_that_cannot_be_persisted_reports_failure(monkeypatch):
    table = FakeSocialTable([], fail={"put_item"})
    wire(monkeypatch, table=table, s3=_cohort_s3())
    assert social._handle_cohort_submit(post({"value": 55}))["statusCode"] == 500


def test_a_follow_that_cannot_be_persisted_reports_failure(monkeypatch):
    table = FakeSocialTable([], fail={"put_item"})
    wire(monkeypatch, table=table)
    assert social._handle_experiment_follow(post(FOLLOW))["statusCode"] == 500
    assert social._handle_challenge_follow(post({"email": "r@x.com", "catalog_id": "c1"}))["statusCode"] == 500


def test_a_checkin_that_cannot_be_read_or_written_reports_a_database_error(monkeypatch):
    wire(monkeypatch, table=_write_failing_table())
    assert social._handle_challenge_checkin(post({"challenge_id": "cold-shower-finish", "completed": True}))["statusCode"] == 500
    table = _active_challenge_table()
    table.fail = {"get_item"}
    wire(monkeypatch, table=table)
    assert social._handle_challenge_checkin(post({"challenge_id": "cold-shower-finish", "completed": True}))["statusCode"] == 500


def test_the_live_challenge_query_failing_leaves_the_catalog_page_standing(monkeypatch):
    """Fail-soft, catalog-only: /protocols must survive a DDB blip with its
    pipeline intact rather than going blank."""
    wire(monkeypatch, table=FakeSocialTable(fail={"query"}), s3=_catalog_s3())
    assert ok_body(social.handle_challenges())["count"] > 0


def test_a_live_challenge_in_an_unrecognised_state_is_not_shown(monkeypatch):
    """The public status set is active/completed/failed (#2424). Anything else —
    a draft, an abandoned row, a schema experiment — stays private."""
    rows = [
        {"pk": "USER#matthew#SOURCE#challenges", "sk": "CHALLENGE#draft", "name": "Draft", "status": "draft"},
        {"pk": "USER#matthew#SOURCE#challenges", "sk": "CHALLENGE#real", "name": "Real", "status": "completed"},
    ]
    wire(monkeypatch, table=FakeSocialTable(rows), s3=_catalog_s3({"challenges": []}))
    assert [c["id"] for c in ok_body(social.handle_challenges())["challenges"]] == ["real"]


def test_an_unreviewed_candidate_challenge_never_reaches_the_public_payload(monkeypatch):
    """#2424: challenge_generator writes LLM-authored rows with status='candidate';
    they are owner-only (MCP) until Matthew activates one. A candidate row in the
    table is absent from GET /api/challenges — name AND description — while an
    activated sibling still serves."""
    rows = [
        {
            "pk": "USER#matthew#SOURCE#challenges",
            "sk": "CHALLENGE#llm-idea_2026-08-09",
            "name": "LLM idea",
            "description": "unreviewed model copy",
            "status": "candidate",
        },
        {
            "pk": "USER#matthew#SOURCE#challenges",
            "sk": "CHALLENGE#approved-one",
            "name": "Approved one",
            "status": "active",
            "duration_days": 7,
        },
    ]
    wire(monkeypatch, table=FakeSocialTable(rows), s3=_catalog_s3({"challenges": []}))
    body = ok_body(social.handle_challenges())
    assert [c["id"] for c in body["challenges"]] == ["approved-one"]
    assert "llm-idea" not in json.dumps(body) and "unreviewed model copy" not in json.dumps(body)


def test_a_dated_live_challenge_id_is_normalised_back_to_its_catalog_id(monkeypatch):
    """Live rows are keyed `CHALLENGE#{id}_{YYYY-MM-DD}`; the trailing date is
    stripped so the live row and its catalog entry are recognisably the same
    challenge (that dedup is what the overlay relies on)."""
    rows = [
        {
            "pk": "USER#matthew#SOURCE#challenges",
            "sk": "CHALLENGE#cold-shower-finish_2026-05-04",
            "name": "Cold shower finish",
            "status": "completed",
        }
    ]
    wire(monkeypatch, table=FakeSocialTable(rows), s3=_catalog_s3())
    live = next(c for c in ok_body(social.handle_challenges())["challenges"] if c["origin"] == "live")
    assert live["id"] == "cold-shower-finish" and live["challenge_id"] == "cold-shower-finish_2026-05-04"


def test_a_library_partition_row_that_is_not_an_experiment_is_ignored(monkeypatch):
    """The experiments partition also holds non-`EXP#` bookkeeping rows; treating
    one as an experiment would mint a phantom status on a library card."""
    rows = [{"pk": "USER#matthew#SOURCE#experiments", "sk": "META#index", "name": "Post-dinner walk", "status": "active"}]
    wire(monkeypatch, table=FakeSocialTable(rows), s3=_library_s3())
    by_id = {e["id"]: e for p in ok_body(social.handle_experiment_library())["pillars"] for e in p["experiments"]}
    assert by_id["post-dinner-walk"].get("status") != "active"


def test_a_pillar_missing_from_the_configured_order_is_appended_not_dropped(monkeypatch):
    """An experiment whose pillar the config forgot must still reach the page."""
    library = json.loads(json.dumps(LIBRARY))
    library["experiments"].append({"id": "orphan", "name": "Orphan", "pillar": "mind"})
    wire(monkeypatch, s3=_library_s3(library))
    ids = [p["id"] for p in ok_body(social.handle_experiment_library())["pillars"]]
    assert ids[:2] == ["food", "sleep"] and "mind" in ids


def test_an_experiment_with_no_pillar_falls_into_a_named_other_group(monkeypatch):
    library = {"experiments": [{"id": "loose", "name": "Loose"}]}
    wire(monkeypatch, s3=_library_s3(library))
    pillars = ok_body(social.handle_experiment_library())["pillars"]
    assert [p["id"] for p in pillars] == ["other"] and pillars[0]["label"] == "Other"


@pytest.mark.parametrize("bad_email", ["no-at-sign", "x" * 260])
def test_an_invalid_reply_address_is_refused_on_both_capture_doors(bad_email, monkeypatch):
    _t, s3, _sec = wire(monkeypatch)
    assert social._handle_submit_finding(post({**GOOD_FINDING, "email": bad_email}))["statusCode"] == 400
    assert social._handle_board_question(post({**GOOD_QUESTION, "email": bad_email}))["statusCode"] == 400
    assert s3.puts == []


def test_the_predictor_count_pages_through_every_dedup_row(monkeypatch):
    """The dedup partition is paginated; stopping at the first page would
    under-report the Predictor rung. Hand-derived: three distinct ip_hashes spread
    over two pages -> 3."""
    rows = [{"pk": "VOTES#rate_limit", "sk": f"PRED#ip{i}#2026-W19#weight", "voted_at": 1} for i in range(3)]
    table = FakeSocialTable(rows)
    real_query = table.query

    def paged_query(**kwargs):
        """Hand-rolled two-page response — bounded by construction, never a Mock:
        the first call returns one row plus a LastEvaluatedKey, the follow-up
        returns the rest and no key, so the loop terminates in exactly two passes."""
        resp = real_query(**kwargs)
        if "ExclusiveStartKey" not in kwargs:
            return {"Items": resp["Items"][:1], "LastEvaluatedKey": {"pk": "VOTES#rate_limit", "sk": resp["Items"][0]["sk"]}}
        return {"Items": resp["Items"][1:]}

    table.query = paged_query
    wire(monkeypatch, table=table)
    assert ok_body(social.handle_ladder_counts())["rungs"]["predictor"]["count"] == 3


def test_a_non_numeric_matthew_value_hides_his_dot_rather_than_crashing_the_strip(monkeypatch):
    """The weekly config is hand-edited. A typo in `matthew_value` must cost the
    dot, not the whole distribution."""
    wire(monkeypatch, table=FakeSocialTable(_cohort_rows(44, 50, 56, 62, 80)), s3=_cohort_s3({**COHORT_CFG, "matthew_value": "fifty-two"}))
    body = ok_body(social.handle_cohort_strip())
    assert body["matthew_value"] is None and body["matthew_percentile"] is None and body["n"] == 5


def test_the_nudge_door_still_limits_when_the_shared_rate_limiter_is_unavailable(monkeypatch):
    """`_handle_nudge` was one of only two doors with a working fallback before
    #2237; it is the shape every door now shares — degraded, never disabled."""
    monkeypatch.setattr(social, "_RATE_LIMITER_READY", False)
    wire(monkeypatch)
    assert social._handle_nudge(post({"category": "watching"}))["statusCode"] == 200
    assert social._handle_nudge(post({"category": "watching"}))["statusCode"] == 429


def test_the_finding_door_still_limits_when_the_shared_rate_limiter_is_unavailable(monkeypatch):
    monkeypatch.setattr(social, "_RATE_LIMITER_READY", False)
    wire(monkeypatch)
    for i in range(social.FINDING_RATE_LIMIT):
        assert social._handle_submit_finding(post({**GOOD_FINDING, "finding": f"a finding number {i}"}))["statusCode"] == 200
    assert social._handle_submit_finding(post({**GOOD_FINDING, "finding": "one too many again"}))["statusCode"] == 429


def test_the_board_question_door_is_metered_when_the_shared_rate_limiter_is_unavailable(monkeypatch):
    """#2237's FIFTH door — the one the issue described as already having an
    in-memory fallback. It did not: its `else` branch read
    `allowed, remaining = True, BOARD_QUESTION_RATE_LIMIT` — an unconditional
    allow, i.e. an unmetered S3 write path whenever the shared limiter was
    unavailable. It now shares the module chokepoint, so the documented
    3-per-IP-per-hour bar holds in the degraded mode too."""
    monkeypatch.setattr(social, "_RATE_LIMITER_READY", False)
    wire(monkeypatch)
    statuses = [social._handle_board_question(post({"question": f"a question number {i} for you"}))["statusCode"] for i in range(6)]
    assert statuses == [200] * social.BOARD_QUESTION_RATE_LIMIT + [429] * (6 - social.BOARD_QUESTION_RATE_LIMIT)


def test_no_429_is_built_outside_the_one_metered_refusal_builder():
    """Guard the SET, not the instance. #2221's finding was that
    `_emit_rate_limit_metric` existed but only 3 of the module's 13 refusal paths
    called it. Emitting inside `_rate_limited` fixes today's ten; this makes a
    NEW unmetered 429 unexpressible — the literal `429` may appear only in that
    builder's own signature-free body and in the `_rate_limited` call sites."""
    tree = ast.parse(pathlib.Path(inspect.getfile(social)).read_text())
    builder = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_rate_limited")
    exempt = {id(n) for n in ast.walk(builder)}
    offenders = [n.lineno for n in ast.walk(tree) if isinstance(n, ast.Constant) and n.value == 429 and id(n) not in exempt]
    assert offenders == [], f"a 429 built outside _rate_limited at line(s) {offenders}"


def test_the_metered_refusal_builder_covers_every_public_write_door():
    """...and the set it covers is DERIVED: every `_rate_limited(...)` call site is
    counted, so a door that drops its refusal shows up as a shrinking number."""
    tree = ast.parse(pathlib.Path(inspect.getfile(social)).read_text())
    endpoints = {
        n.args[0].value
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_rate_limited" and n.args
    }
    assert len(endpoints) >= 13, sorted(endpoints)
    assert {"nudge", "submit_finding", "board_question", "verify_subscriber", "cohort_submit"} <= endpoints


def test_every_rate_limited_refusal_emits_the_abuse_metric(monkeypatch):
    """Fixed by #2221 (was xfail).

    CORRECTION to the marker this replaces: it said "only TWO of the module's ten
    429 paths call it". There are THIRTEEN 429 paths, not ten (it omitted
    `verify_subscriber` and `predict_week`), and THREE already emitted —
    `verify_subscriber` had been given one by #2239 after the marker was written.
    The gap was 10 of 13 (~77%), not 8 of 10 (~80%)."""
    emitted: list = []
    monkeypatch.setattr(social, "_emit_rate_limit_metric", lambda endpoint: emitted.append(endpoint))
    wire(monkeypatch)
    social._handle_nudge(post({"category": "watching"}))
    assert social._handle_nudge(post({"category": "watching"}))["statusCode"] == 429
    assert emitted == ["nudge"]


# ──────────────────────────────────────────────────────────────────────────────
# 10. The evening-ritual one-tap link (#769, ADR-124)
# ──────────────────────────────────────────────────────────────────────────────


def _signed_ritual_params(date_str=TODAY, metric="connection", value=3, secret=RITUAL_SECRET) -> dict:
    from content.ritual_link import sign_ritual_token

    return {"date": date_str, "metric": metric, "value": str(value), "token": sign_ritual_token(secret, date_str, metric, value)}


def test_a_correctly_signed_tap_is_written_to_the_days_ritual_record(monkeypatch):
    table, _s3, _sec = wire(monkeypatch)
    body = ok_body(social._handle_ritual_log(get(_signed_ritual_params())))
    assert {k: v for k, v in body.items() if k != "_meta"} == {"logged": True, "date": TODAY, "metric": "connection", "value": 3}
    assert table.store[("USER#matthew#SOURCE#evening_ritual", f"DATE#{TODAY}")]["connection"] == 3


def test_a_tap_with_a_forged_value_is_rejected_because_the_value_is_signed(monkeypatch):
    """The (date, metric, value) triple IS the payload, so bumping `value` in the
    URL invalidates the signature — no separate auth scheme needed."""
    table, _s3, _sec = wire(monkeypatch)
    params = {**_signed_ritual_params(value=1), "value": "4"}
    assert social._handle_ritual_log(get(params))["statusCode"] == 403
    assert table.updates == []


def test_a_tap_signed_with_the_wrong_secret_is_rejected(monkeypatch):
    wire(monkeypatch)
    assert social._handle_ritual_log(get(_signed_ritual_params(secret="w" * 64)))["statusCode"] == 403


def test_the_ritual_token_is_compared_in_constant_time(monkeypatch):
    """Signed-link verification must not leak the expected digest through timing.
    Asserted structurally against `content.ritual_link.verify_ritual_token`'s own
    source, which is the one comparison the handler delegates to."""
    from content import ritual_link

    assert "compare_digest" in inspect.getsource(ritual_link.verify_ritual_token)


@pytest.mark.parametrize("metric", ["connection", "mood_valence", "felt_time", "intake_count"])
def test_every_declared_ritual_metric_is_accepted(metric, monkeypatch):
    """The metric allowlist is RITUAL_METRICS itself; a sample across all four
    destination partitions so the routing table below cannot be half-tested."""
    wire(monkeypatch)
    assert social._handle_ritual_log(get(_signed_ritual_params(metric=metric)))["statusCode"] == 200


def test_a_metric_outside_the_allowlist_is_rejected_before_any_signature_work(monkeypatch):
    table, _s3, _sec = wire(monkeypatch)
    assert social._handle_ritual_log(get({"date": TODAY, "metric": "weight", "value": "3", "token": "x" * 32}))["statusCode"] == 400
    assert table.updates == []


@pytest.mark.parametrize("value", ["-1", "5", "abc", "", "3.5"])
def test_a_ritual_value_outside_zero_to_four_or_not_an_integer_is_rejected(value, monkeypatch):
    wire(monkeypatch)
    params = {**_signed_ritual_params(), "value": value}
    assert social._handle_ritual_log(get(params))["statusCode"] == 400


def test_the_private_intake_metric_lands_in_its_own_partition_never_the_public_aggregate(monkeypatch):
    """#1405, and the load-bearing privacy invariant of this endpoint: the public
    wellbeing aggregate reads `evening_ritual`, so a private-class metric that
    landed there would be structurally readable by /api/fulfillment_ritual."""
    table, _s3, _sec = wire(monkeypatch)
    social._handle_ritual_log(get(_signed_ritual_params(metric="intake_count")))
    assert ("USER#matthew#SOURCE#private_intake", f"DATE#{TODAY}") in table.store
    assert ("USER#matthew#SOURCE#evening_ritual", f"DATE#{TODAY}") not in table.store


@pytest.mark.parametrize(
    "metric,partition",
    [
        ("connection", "evening_ritual"),
        ("mood_valence", "evening_ritual"),
        ("intake_count", "private_intake"),
        ("felt_vitality", "felt_probe"),
        ("felt_time", "time_affluence"),
    ],
)
def test_each_ritual_metric_is_routed_to_the_partition_its_registry_declares(metric, partition, monkeypatch):
    """The routing table is a four-way nested conditional; each arm is pinned so a
    reordering cannot silently send a weekly probe into the daily aggregate."""
    table, _s3, _sec = wire(monkeypatch)
    social._handle_ritual_log(get(_signed_ritual_params(metric=metric)))
    assert (f"USER#matthew#SOURCE#{partition}", f"DATE#{TODAY}") in table.store


def test_two_metrics_on_the_same_day_do_not_disturb_each_other(monkeypatch):
    table, _s3, _sec = wire(monkeypatch)
    social._handle_ritual_log(get(_signed_ritual_params(metric="connection", value=4)))
    social._handle_ritual_log(get(_signed_ritual_params(metric="mood_valence", value=2)))
    row = table.store[("USER#matthew#SOURCE#evening_ritual", f"DATE#{TODAY}")]
    assert row["connection"] == 4 and row["mood_valence"] == 2


def test_a_re_tap_overwrites_rather_than_appending(monkeypatch):
    """Last-tap-wins is the documented idempotency contract — Matthew changing his
    mind from the same email must not create a second reading."""
    table, _s3, _sec = wire(monkeypatch)
    social._handle_ritual_log(get(_signed_ritual_params(value=1)))
    social._handle_ritual_log(get(_signed_ritual_params(value=4)))
    assert table.store[("USER#matthew#SOURCE#evening_ritual", f"DATE#{TODAY}")]["connection"] == 4


@pytest.mark.parametrize("date_str", ["2026-05-11", "2026-05-02", "not-a-date"])
def test_a_tap_outside_the_seven_day_window_is_rejected(date_str, monkeypatch):
    """Defense in depth beyond the signature: future dates and anything older than
    a week are refused. 2026-05-02 is 8 days before the frozen today."""
    wire(monkeypatch)
    assert social._handle_ritual_log(get(_signed_ritual_params(date_str=date_str)))["statusCode"] == 400


def test_a_tap_exactly_seven_days_old_is_still_accepted(monkeypatch):
    """Boundary pinned on the inside: 2026-05-03 is exactly 7 days back."""
    wire(monkeypatch)
    assert social._handle_ritual_log(get(_signed_ritual_params(date_str="2026-05-03")))["statusCode"] == 200


def test_an_unavailable_signing_secret_degrades_to_503_rather_than_500(monkeypatch):
    """A 503 is retryable and tells the reader the truth; an unhandled RuntimeError
    would be a 502 at the Function URL."""
    wire(monkeypatch, secrets=FakeSecrets({}))
    assert social._handle_ritual_log(get(_signed_ritual_params()))["statusCode"] == 503


# ──────────────────────────────────────────────────────────────────────────────
# 11. Experiment suggestions — the least-guarded write door
# ──────────────────────────────────────────────────────────────────────────────


def test_a_reader_suggestion_is_stored_pending_and_marked_as_reader_submitted(monkeypatch):
    table, _s3, _sec = wire(monkeypatch)
    assert ok_body(social._handle_experiment_suggest(post({"idea": "try a 10-day creatine loading phase"}))) == {"status": "received"}
    stored = table.puts[0]
    assert stored["status"] == "pending" and stored["submitted_by"] == "reader"


def test_a_suggestion_shorter_than_ten_characters_is_refused(monkeypatch):
    wire(monkeypatch)
    assert social._handle_experiment_suggest(post({"idea": "short"}))["statusCode"] == 400


def test_the_fourth_suggestion_in_an_hour_from_one_ip_is_refused(monkeypatch):
    wire(monkeypatch)
    for i in range(3):
        assert social._handle_experiment_suggest(post({"idea": f"idea number {i} worth trying"}))["statusCode"] == 200
    assert social._handle_experiment_suggest(post({"idea": "one suggestion too many"}))["statusCode"] == 429


def test_a_suggestion_is_length_capped_like_every_other_reader_text_field(monkeypatch):
    table, _s3, _sec = wire(monkeypatch)
    social._handle_experiment_suggest(post({"idea": "x" * 50_000, "source": "y" * 50_000}))
    assert len(table.puts[0]["idea"]) <= 500 and len(table.puts[0]["source"]) <= 500


def test_a_suggestion_is_html_stripped_like_every_other_reader_text_field(monkeypatch):
    table, _s3, _sec = wire(monkeypatch)
    social._handle_experiment_suggest(post({"idea": "<script>alert(1)</script>please try zone 2"}))
    assert "<script>" not in table.puts[0]["idea"]


@pytest.mark.parametrize("body", ["", json.dumps({"idea": 12345})])
def test_a_malformed_suggestion_body_is_a_client_error_not_a_server_error(body, monkeypatch):
    wire(monkeypatch)
    assert social._handle_experiment_suggest(post(body))["statusCode"] == 400


def test_the_suggestion_response_is_explicitly_uncacheable_like_every_other_write(monkeypatch):
    wire(monkeypatch)
    resp = social._handle_experiment_suggest(post({"idea": "try a longer deload week"}))
    assert resp["headers"].get("Cache-Control") == "no-store"


# ──────────────────────────────────────────────────────────────────────────────
# 12. Predict the week
# ──────────────────────────────────────────────────────────────────────────────

CURRENT_CHALLENGE_KEY = "site/config/current_challenge.json"


def _predict_s3(week_id=CURRENT_WEEK, result=None, metrics=None) -> FakeS3:
    return FakeS3(
        {
            CURRENT_CHALLENGE_KEY: {
                "week_id": week_id,
                "predict_metrics": metrics if metrics is not None else [{"key": "weight", "label": "Weight"}],
                **({"result": result} if result is not None else {}),
            }
        }
    )


def test_the_current_iso_week_id_uses_the_iso_year_not_the_calendar_year(monkeypatch):
    """The classic `%Y-W%V` bug splits one ISO week across two buckets at a year
    boundary. `isocalendar()[0]` IS the ISO year, so this is correct — pinned with
    a date where the two disagree: 2024-12-30 is a Monday in ISO week 2025-W01,
    while `strftime('%Y-W%V')` would call it '2024-W01'."""
    freeze(datetime(2024, 12, 30, 20, 0, 0, tzinfo=timezone.utc))
    assert social._current_iso_week() == "2025-W01"
    assert datetime(2024, 12, 30).strftime("%Y-W%V") == "2024-W01"


def test_the_prediction_widget_is_inactive_when_no_subject_is_configured(monkeypatch):
    wire(monkeypatch, s3=FakeS3())
    assert ok_body(social.handle_predict_week_tally(get())) == {
        **{k: v for k, v in ok_body(social.handle_predict_week_tally(get())).items() if k == "_meta"},
        "active": False,
    }


def test_a_stale_prediction_week_fails_closed_rather_than_soliciting_dead_votes(monkeypatch):
    """#1198: current_challenge.json is a MANUAL weekly artifact. If a Monday
    passes without a re-seed, serving it would collect predictions into a bucket
    that can never be revealed."""
    wire(monkeypatch, s3=_predict_s3(week_id="2026-W02"))
    assert ok_body(social.handle_predict_week_tally(get()))["active"] is False
    assert social._handle_predict_week(post({"week_id": "2026-W02", "metric": "weight", "choice": "up"}))["statusCode"] == 404


def test_a_prediction_is_tallied_against_this_weeks_metric(monkeypatch):
    wire(monkeypatch, s3=_predict_s3())
    body = ok_body(social._handle_predict_week(post({"week_id": CURRENT_WEEK, "metric": "weight", "choice": "up"})))
    assert body["tallies"] == {"up": 1, "down": 0, "flat": 0}


def test_the_reader_consensus_reports_every_choice_including_the_ones_nobody_picked(monkeypatch):
    """A tally missing its zero-count keys would make a stacked bar collapse. Hand-
    derived: three predictions from three IPs — two `up`, one `down`, zero `flat`."""
    table, _s3, _sec = wire(monkeypatch, s3=_predict_s3())
    for ip, choice in (("1.1.1.1", "up"), ("2.2.2.2", "up"), ("3.3.3.3", "down")):
        social._handle_predict_week(post({"week_id": CURRENT_WEEK, "metric": "weight", "choice": choice}, ip=ip))
    tallies = ok_body(social.handle_predict_week_tally(get()))["tallies"]["weight"]
    assert tallies == {"up": 2, "down": 1, "flat": 0}


def test_a_second_prediction_on_the_same_metric_from_one_ip_is_refused(monkeypatch):
    wire(monkeypatch, s3=_predict_s3())
    social._handle_predict_week(post({"week_id": CURRENT_WEEK, "metric": "weight", "choice": "up"}))
    resp = social._handle_predict_week(post({"week_id": CURRENT_WEEK, "metric": "weight", "choice": "down"}))
    assert resp["statusCode"] == 429


def test_the_prediction_dedup_row_expires_after_the_eight_day_window(monkeypatch):
    """The 8-day TTL is what makes the published Predictor rung provenance ("the
    active window only") true — see the ladder tests below."""
    table, _s3, _sec = wire(monkeypatch, s3=_predict_s3())
    social._handle_predict_week(post({"week_id": CURRENT_WEEK, "metric": "weight", "choice": "up"}))
    row = next(r for r in table.puts if str(r["sk"]).startswith("PRED#"))
    assert row["ttl"] - row["voted_at"] == 8 * 86400


def test_a_prediction_for_a_closed_window_is_refused_with_a_conflict(monkeypatch):
    wire(monkeypatch, s3=_predict_s3())
    assert social._handle_predict_week(post({"week_id": "2026-W01", "metric": "weight", "choice": "up"}))["statusCode"] == 409


@pytest.mark.parametrize(
    "body,status",
    [
        ({"week_id": CURRENT_WEEK, "metric": "not-a-metric", "choice": "up"}, 404),
        ({"week_id": CURRENT_WEEK, "metric": "weight", "choice": "sideways"}, 400),
    ],
)
def test_a_prediction_outside_the_configured_metrics_or_choices_is_refused(body, status, monkeypatch):
    table, _s3, _sec = wire(monkeypatch, s3=_predict_s3())
    assert social._handle_predict_week(post(body))["statusCode"] == status
    assert table.puts == [], "a rejected prediction must not mint a dedup row"


def test_the_actual_outcome_is_published_alongside_the_consensus_once_matthew_sets_it(monkeypatch):
    """ "readers said UP 64% · it actually went DOWN" is the whole point of the
    widget — the graded outcome must ride in the same payload."""
    wire(monkeypatch, s3=_predict_s3(result={"weight": "down"}))
    assert ok_body(social.handle_predict_week_tally(get()))["result"] == {"weight": "down"}


def test_an_unknown_metric_on_the_tally_read_is_a_404_not_a_silent_empty_chart(monkeypatch):
    wire(monkeypatch, s3=_predict_s3())
    assert social.handle_predict_week_tally(get({"metric": "nope"}))["statusCode"] == 404


# ──────────────────────────────────────────────────────────────────────────────
# 13. The social membrane — broadcast, contextual embeds, the dashboard
# ──────────────────────────────────────────────────────────────────────────────


def _post_row(source, date_str, post_id, *, origin="human", cleared=True, **fields) -> dict:
    row = {
        "pk": f"USER#matthew#SOURCE#{source}",
        "sk": f"DATE#{date_str}#{post_id}",
        "channel": source,
        "post_id": post_id,
        "date": date_str,
        "origin": origin,
        "url": f"https://{source}.example/{post_id}",
        **fields,
    }
    if cleared:
        row[social.SENSITIVITY_STATUS_ATTR] = social.SENSITIVITY_CLEARED
    return row


def test_a_cleared_human_post_reaches_the_broadcast_feed(monkeypatch):
    wire(monkeypatch, table=FakeSocialTable([_post_row("youtube", "2026-05-09", "v1", title="A video")]))
    body = ok_body(social.handle_broadcast())
    assert body["total"] == 1 and body["items"][0]["caption"] == "A video"


def test_a_platform_echo_is_never_republished_as_matthews_voice(monkeypatch):
    """The membrane's whole reason to exist (#1670): the platform's own outbound
    post, re-ingested, must not be re-displayed as Matthew speaking."""
    wire(monkeypatch, table=FakeSocialTable([_post_row("youtube", "2026-05-09", "v1", origin="platform", title="Echo")]))
    assert ok_body(social.handle_broadcast())["total"] == 0


@pytest.mark.parametrize("status", [None, "pending", "flagged", "clear"])
def test_a_post_the_sensitivity_gate_has_not_cleared_is_withheld(status, monkeypatch):
    """FAIL CLOSED. Note `"clear"` is included deliberately: the publishable verdict
    is the literal `"cleared"`, and a near-miss must not publish."""
    row = _post_row("youtube", "2026-05-09", "v1", cleared=False, title="Held")
    if status is not None:
        row[social.SENSITIVITY_STATUS_ATTR] = status
    wire(monkeypatch, table=FakeSocialTable([row]))
    assert ok_body(social.handle_broadcast())["total"] == 0


def test_the_broadcast_feed_is_newest_first_across_all_channels(monkeypatch):
    rows = [
        _post_row("youtube", "2026-05-01", "old", title="Old"),
        _post_row("bluesky", "2026-05-09", "new", title="New"),
        _post_row("mastodon", "2026-05-05", "mid", title="Mid"),
    ]
    wire(monkeypatch, table=FakeSocialTable(rows))
    assert [c["id"] for c in ok_body(social.handle_broadcast())["items"]] == ["new", "mid", "old"]


def test_the_broadcast_feed_is_capped_so_it_stays_a_highlight_not_an_archive(monkeypatch):
    rows = [_post_row("youtube", "2026-05-01", f"v{i:03d}", title=f"Video {i}") for i in range(social._BROADCAST_LIMIT + 10)]
    wire(monkeypatch, table=FakeSocialTable(rows))
    assert ok_body(social.handle_broadcast())["total"] == social._BROADCAST_LIMIT


def test_one_broken_channel_never_takes_down_the_whole_feed(monkeypatch):
    """Fail-soft per source. Driven with a table that raises on every query, so the
    feed degrades to empty rather than 500-ing."""
    wire(monkeypatch, table=FakeSocialTable(fail={"query"}))
    assert ok_body(social.handle_broadcast())["total"] == 0


def test_the_broadcast_card_links_out_rather_than_embedding(monkeypatch):
    """A FACADE by design (#1672) — no third-party iframe, so no CSP change. The
    permalink is a local anchor and the link_out is the third-party URL."""
    wire(monkeypatch, table=FakeSocialTable([_post_row("youtube", "2026-05-09", "v1", title="A video")]))
    card = ok_body(social.handle_broadcast())["items"][0]
    assert card["permalink"] == "/story/broadcast/#v1"
    assert card["link_out"] == "https://youtube.example/v1"


def test_the_broadcast_empty_state_publishes_the_same_keys_as_the_populated_one(monkeypatch):
    """A front-end binding written against real posts must survive the (current)
    all-dormant state — a set difference between two live payloads, not a list."""
    wire(monkeypatch)
    empty = set(ok_body(social.handle_broadcast())) - {"_meta"}
    wire(monkeypatch, table=FakeSocialTable([_post_row("youtube", "2026-05-09", "v1", title="A video")]))
    populated = set(ok_body(social.handle_broadcast())) - {"_meta"}
    assert not (populated - empty)


# ── the reader/writer field-name contract ─────────────────────────────────────


def _card_read_keys() -> set:
    """The literal field names `_broadcast_card` reads off a post row, AST-derived
    from the handler's own source."""
    src = inspect.getsource(social._broadcast_card)
    tree = ast.parse(src.lstrip())
    keys = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            keys.add(node.args[0].value)
    return keys


_INGEST_LAMBDAS = {"youtube": "youtube_lambda.py", "bluesky": "bluesky_lambda.py", "mastodon": "mastodon_lambda.py"}
# `sk` is minted by the shared ingestion framework from `sk_suffix`, not by the
# per-source transform, so it is not expected in a writer's record literal.
_FRAMEWORK_SUPPLIED = {"sk"}


def _writer_record_keys(filename: str) -> set:
    """Every literal key the named ingestion lambda's `transform()` writes — both
    the `record = {...}` display and any `record[...] = ...` assignment."""
    path = pathlib.Path(inspect.getfile(social)).parents[1] / "ingestion" / filename
    tree = ast.parse(path.read_text())
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "transform")
    keys = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Dict):
            keys.update(k.value for k in node.keys if isinstance(k, ast.Constant) and isinstance(k.value, str))
        if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
            keys.add(node.slice.value)
    return keys


def test_the_field_name_scan_finds_both_sides_so_the_parity_test_is_not_vacuous():
    assert _card_read_keys() >= {"title", "description", "thumbnail_url", "url", "post_id"}
    assert _writer_record_keys("youtube_lambda.py") >= {"title", "description", "thumbnail_url"}


@pytest.mark.parametrize("channel", sorted(_INGEST_LAMBDAS))
def test_every_field_the_broadcast_card_reads_is_a_field_that_channel_actually_writes(channel):
    """Both sides AST-derived from the shipped source, so neither the reader's nor
    the writer's field list can be hand-typed wrong in this test.

    Fixed by #2221 (was xfail for bluesky + mastodon, which wrote the post body as
    `text` and no title/description/thumbnail_url at all, so every microblog post
    rendered as a blank card). Fixed in the WRITERS, not the reader: the card stays
    channel-agnostic and each transform normalises into the one shape."""
    read = _card_read_keys() - _FRAMEWORK_SUPPLIED
    written = _writer_record_keys(_INGEST_LAMBDAS[channel])
    assert not (read - written), f"{channel} never writes {sorted(read - written)}"


def test_a_bluesky_post_renders_its_own_text_as_the_card_caption(monkeypatch):
    """The behavioural companion to the AST parity test. It used to pin the blank
    card as observable output; #2221 fixed it, so it now pins the fixed output.

    CORRECTION to the marker this replaces: it proposed the card read
    `thumbnail_url or embed_url`. A Bluesky `embed_url` is
    `record.embed.external.uri` — the target of an external LINK card, not an image
    (`ingestion/bluesky_lambda._parse_entries`) — and both front-end renderers put
    `thumbnail_url` straight into `<img src>` (site/assets/js/dispatches.js:437,
    evidence_shared.js:221). That fix would have shipped a broken image on every
    Bluesky post carrying a link. The thumbnail stays empty; only the text is
    normalised."""
    row = _post_row(
        "bluesky",
        "2026-05-09",
        "b1",
        text="A real post body",
        title="A real post body",
        description="A real post body",
        embed_url="https://example.com/an-article",
    )
    wire(monkeypatch, table=FakeSocialTable([row]))
    card = ok_body(social.handle_broadcast())["items"][0]
    assert (card["caption"], card["excerpt"]) == ("A real post body", "A real post body")
    assert card["thumbnail_url"] == "", "an external-link uri is not an image and must not reach <img src>"


@pytest.mark.parametrize("channel", ["bluesky", "mastodon"])
def test_the_microblog_transforms_derive_the_card_fields_from_the_post_text(channel):
    """The parity test above only proves the KEYS are declared. This proves the
    values are real: `title`/`description` must read the post's own text, and
    `thumbnail_url` must NOT be `embed_url` (see the correction above)."""
    path = pathlib.Path(inspect.getfile(social)).parents[1] / "ingestion" / _INGEST_LAMBDAS[channel]
    tree = ast.parse(path.read_text())
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "transform")
    assigned = {}
    for node in ast.walk(fn):
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if isinstance(k, ast.Constant) and isinstance(k.value, str):
                    assigned[k.value] = ast.unparse(v)
    assert "text" in assigned["title"] and "text" in assigned["description"], assigned
    assert "embed_url" not in assigned["thumbnail_url"], assigned["thumbnail_url"]


def test_the_membrane_post_partitions_are_raw_timeseries_so_no_phase_filter_is_owed():
    """ADR-058 in the other direction: filtering a RAW_TIMESERIES partition would
    hide real history after a reset. Derived from phase_taxonomy, so a
    reclassification of these sources fails here first."""
    for source in social._BROADCAST_SOURCES:
        assert phase_taxonomy.SOURCE_CLASS.get(source) == "raw_timeseries", source


# ── contextual embeds ─────────────────────────────────────────────────────────


def test_a_contextual_embed_route_outside_the_allowlist_is_rejected(monkeypatch):
    wire(monkeypatch)
    assert social._handle_social_context(get({"route": "nutrition"}))["statusCode"] == 400
    assert social._handle_social_context(get({}))["statusCode"] == 400


def test_only_enriched_posts_are_eligible_for_a_contextual_surface(monkeypatch):
    """An unenriched post has no content signal, so the classifier's "mind" default
    would silently misroute it. It stays in the general feed until enrichment."""
    rows = [
        _post_row("youtube", "2026-05-09", "v1", title="Squat session", enriched_coach_route="training"),
        _post_row("youtube", "2026-05-08", "v2", title="Also training", enriched_coach_route="training", enriched_at="2026-05-08T12:00:00"),
    ]
    wire(monkeypatch, table=FakeSocialTable(rows))
    assert [c["id"] for c in ok_body(social._handle_social_context(get({"route": "training"})))["items"]] == ["v2"]


def test_a_contextual_embed_uses_the_same_membrane_gate_as_the_broadcast_feed(monkeypatch):
    """One query, one predicate: a held post must not reappear via the sidebar."""
    row = _post_row(
        "youtube", "2026-05-09", "v1", cleared=False, title="Held", enriched_coach_route="training", enriched_at="2026-05-09T00:00:00"
    )
    wire(monkeypatch, table=FakeSocialTable([row]))
    assert ok_body(social._handle_social_context(get({"route": "training"})))["total"] == 0


def test_the_contextual_sidebar_is_capped_to_a_highlight(monkeypatch):
    rows = [
        _post_row("youtube", "2026-05-01", f"v{i:03d}", title="T", enriched_coach_route="training", enriched_at="2026-05-01T00:00:00")
        for i in range(social._CONTEXT_LIMIT + 5)
    ]
    wire(monkeypatch, table=FakeSocialTable(rows))
    assert ok_body(social._handle_social_context(get({"route": "training"})))["total"] == social._CONTEXT_LIMIT


# ── the membrane dashboard ────────────────────────────────────────────────────


def test_the_membrane_reports_a_dormant_inbound_channel_as_dormant_not_empty(monkeypatch):
    """ADR-104's exact distinction: the absence of a PIPE is not the absence of
    posting. `live` is derived from the source registry's own `active_api` facet,
    so this asserts against the registry rather than restating today's state."""
    wire(monkeypatch)
    body = ok_body(social.handle_membrane())
    for channel in body["inbound"]["channels"]:
        expected = bool((SOURCE_REGISTRY.get(channel["channel"]) or {}).get("active_api"))
        assert channel["live"] is expected
        assert channel["state"] == ("live" if expected else "dormant")


def test_the_membrane_counts_platform_echoes_it_kept_out(monkeypatch):
    """Hand-derived: three ingested rows — one cleared human post, one platform
    echo, one held human post. visible = 1, echoes_excluded = 1."""
    rows = [
        _post_row("youtube", "2026-05-09", "v1", title="Real"),
        _post_row("youtube", "2026-05-08", "v2", title="Echo", origin="platform"),
        _post_row("youtube", "2026-05-07", "v3", title="Held", cleared=False),
    ]
    wire(monkeypatch, table=FakeSocialTable(rows))
    body = ok_body(social.handle_membrane())
    assert body["inbound"]["visible"] == 1
    assert body["membrane"]["echoes_excluded"] == 1


def test_the_membrane_never_publishes_the_held_set_or_a_raw_ingested_total(monkeypatch):
    """The load-bearing privacy invariant: publishing "1 held" would disclose that
    flagged material exists, which is the one thing a fail-closed gate is for. A
    raw total would make it derivable by subtraction, so neither may appear."""
    rows = [
        _post_row("youtube", "2026-05-09", "v1", title="Real"),
        _post_row("youtube", "2026-05-07", "v3", title="Held secret content", cleared=False),
        _post_row("youtube", "2026-05-06", "v4", title="Also held", cleared=False),
    ]
    wire(monkeypatch, table=FakeSocialTable(rows))
    payload = ok_body(social.handle_membrane())
    blob = json.dumps(payload)
    assert "held" not in blob.lower()
    assert "Held secret content" not in blob
    # visible(1) + echoes(0) must not reconstruct the raw partition size (3).
    assert "total" not in payload["inbound"]


def test_the_membrane_publishes_no_engagement_or_vanity_metric(monkeypatch):
    """#1402's no-gloss ethos: every figure is a count of records the platform
    itself wrote. Followers/likes/reach/impressions are structurally absent."""
    rows = [_post_row("youtube", "2026-05-09", "v1", title="Real", views=9999, like_count=42)]
    wire(monkeypatch, table=FakeSocialTable(rows))
    blob = json.dumps(ok_body(social.handle_membrane())).lower()
    for banned in ("follower", "likes", "like_count", "reach", "impression", "views"):
        assert banned not in blob


def test_the_outbound_ledger_reports_what_the_platform_itself_posted(monkeypatch):
    rows = [
        {
            "pk": "BROADCAST_ORIGIN#bluesky",
            "sk": "POST#p1",
            "channel": "bluesky",
            "url": "https://b/1",
            "recorded_at": "2026-05-09T10:00:00",
        },
        {"pk": "BROADCAST_ORIGIN#x", "sk": "POST#p2", "channel": "x", "url": "https://x/2", "recorded_at": "2026-05-08T10:00:00"},
    ]
    wire(monkeypatch, table=FakeSocialTable(rows))
    body = ok_body(social.handle_membrane())
    assert body["outbound"]["state"] == "recording" and body["outbound"]["total"] == 2
    assert [p["id"] for p in body["outbound"]["posts"]] == ["p1", "p2"]  # newest recorded_at first


def test_an_outbound_record_carries_provenance_only_never_post_content(monkeypatch):
    rows = [
        {
            "pk": "BROADCAST_ORIGIN#bluesky",
            "sk": "POST#p1",
            "channel": "bluesky",
            "url": "https://b/1",
            "recorded_at": "2026-05-09T10:00:00",
            "text": "the private draft body",
        }
    ]
    wire(monkeypatch, table=FakeSocialTable(rows))
    assert "the private draft body" not in json.dumps(ok_body(social.handle_membrane()))


def test_the_membrane_empty_state_publishes_the_same_keys_as_the_populated_one(monkeypatch):
    """Today every partition is empty, so the EMPTY payload is the only one a
    reader has ever seen — the populated shape must not add keys the page never
    learned to render (and vice versa)."""

    def keys(payload):
        return {(k, tuple(sorted(v))) if isinstance(v, dict) else (k, ()) for k, v in payload.items() if k != "_meta"}

    wire(monkeypatch)
    empty = keys(ok_body(social.handle_membrane()))
    rows = [
        _post_row("youtube", "2026-05-09", "v1", title="Real"),
        {"pk": "BROADCAST_ORIGIN#x", "sk": "POST#p2", "channel": "x", "url": "https://x/2", "recorded_at": "2026-05-08T10:00:00"},
    ]
    wire(monkeypatch, table=FakeSocialTable(rows))
    assert keys(ok_body(social.handle_membrane())) == empty


def test_the_membranes_inbound_view_cannot_disagree_with_the_broadcast_feed(monkeypatch):
    """Same query, same predicate, by construction — asserted end-to-end so a
    future second gate can't drift the dashboard away from /story/broadcast/."""
    rows = [
        _post_row("youtube", "2026-05-09", "v1", title="Real"),
        _post_row("youtube", "2026-05-08", "v2", title="Echo", origin="platform"),
        _post_row("bluesky", "2026-05-07", "b1", text="Held", cleared=False),
    ]
    wire(monkeypatch, table=FakeSocialTable(rows))
    feed = {c["id"] for c in ok_body(social.handle_broadcast())["items"]}
    dash = {c["id"] for c in ok_body(social.handle_membrane())["inbound"]["items"]}
    assert feed == dash == {"v1"}


# ──────────────────────────────────────────────────────────────────────────────
# 14. The engagement ladder
# ──────────────────────────────────────────────────────────────────────────────

PUBLISHED_INDEX_KEY = "generated/findings/_published_index.json"


def test_the_reader_rung_is_honestly_uncounted_rather_than_given_a_fake_number(monkeypatch):
    """The base rung is anonymous by design. ADR-104: publish the absence and say
    why, never a fabricated audience size."""
    wire(monkeypatch)
    reader = ok_body(social.handle_ladder_counts())["rungs"]["reader"]
    assert reader["count"] is None and reader["countable"] is False
    assert "not counted" in reader["provenance"]["method"]


def test_every_ladder_rung_ships_the_provenance_of_its_own_number(monkeypatch):
    """ADR-105: a published count without its source and method is an assertion,
    not evidence. Derived over the rung set rather than named one at a time."""
    wire(monkeypatch)
    body = ok_body(social.handle_ladder_counts())
    assert set(body["order"]) == set(body["rungs"])
    for name, rung in body["rungs"].items():
        assert set(rung["provenance"]) >= {"source", "method"}, name
        assert rung["provenance"]["method"], name


def test_the_ladder_counts_are_each_derived_from_their_own_system_of_record(monkeypatch):
    """Hand-derived: 2 confirmed subscribers, 2 distinct predictor IPs (one of whom
    predicted twice, on two metrics), a replicator counter of 3, and 2 published
    findings of which 1 opted into credit."""
    rows = [
        _subscriber_row("a@x.com"),
        _subscriber_row("b@x.com"),
        _subscriber_row("c@x.com", status="pending"),
        {"pk": "VOTES#rate_limit", "sk": "PRED#aaaaaaaa#2026-W19#weight", "voted_at": 1},
        {"pk": "VOTES#rate_limit", "sk": "PRED#aaaaaaaa#2026-W19#sleep", "voted_at": 1},
        {"pk": "VOTES#rate_limit", "sk": "PRED#bbbbbbbb#2026-W19#weight", "voted_at": 1},
        {"pk": "VOTES#ladder_replicator", "sk": "COUNT", "cert_count": 3},
    ]
    index = {"published": [{"id": "f1", "credit_opt_in": True, "credit_name": "Dana"}, {"id": "f2", "credit_opt_in": False}]}
    wire(monkeypatch, table=FakeSocialTable(rows), s3=FakeS3({PUBLISHED_INDEX_KEY: index}))
    rungs = ok_body(social.handle_ladder_counts())["rungs"]
    assert rungs["subscriber"]["count"] == 2
    assert rungs["predictor"]["count"] == 2
    assert rungs["replicator"]["count"] == 3
    assert rungs["contributor"]["count"] == 2
    assert rungs["contributor"]["credited"] == ["Dana"]


def test_a_contributor_who_did_not_opt_into_credit_is_counted_but_never_named(monkeypatch):
    index = {"published": [{"id": "f2", "credit_opt_in": False, "credit_name": "Should Not Appear"}]}
    wire(monkeypatch, s3=FakeS3({PUBLISHED_INDEX_KEY: index}))
    body = ok_body(social.handle_ladder_counts())
    assert body["rungs"]["contributor"]["count"] == 1
    assert "Should Not Appear" not in json.dumps(body)


def test_the_predictor_provenance_admits_it_only_covers_the_active_window(monkeypatch):
    """The PRED# dedup rows carry an 8-day TTL, so the count is NOT all-time. The
    provenance note is what makes the published number honest."""
    wire(monkeypatch)
    note = ok_body(social.handle_ladder_counts())["rungs"]["predictor"]["provenance"]["note"]
    assert "8-day" in note or "active window" in note


def test_a_database_outage_makes_the_ladder_counts_unknown_not_zero(monkeypatch):
    wire(monkeypatch, table=FakeSocialTable([_subscriber_row("a@x.com")], fail={"query", "get_item"}))
    rungs = ok_body(social.handle_ladder_counts())["rungs"]
    assert rungs["subscriber"]["count"] is None
    assert rungs["predictor"]["count"] is None
    assert rungs["replicator"]["count"] is None


def test_an_absent_published_findings_index_is_an_honest_zero(monkeypatch):
    """The distinction the test above is about: nothing published yet IS genuinely
    zero contributors, and must read as 0 rather than being hidden."""
    wire(monkeypatch, s3=FakeS3())
    assert ok_body(social.handle_ladder_counts())["rungs"]["contributor"]["count"] == 0


# ── replicate_certify ─────────────────────────────────────────────────────────


def test_a_replication_self_cert_bumps_the_public_replicator_count(monkeypatch):
    table, _s3, _sec = wire(monkeypatch)
    assert ok_body(social._handle_replicate_certify(post({})))["counted"] is True
    assert table.store[("VOTES#ladder_replicator", "COUNT")]["cert_count"] == 1


def test_a_second_self_cert_from_the_same_source_is_idempotent_not_double_counted(monkeypatch):
    table, _s3, _sec = wire(monkeypatch)
    social._handle_replicate_certify(post({}))
    second = ok_body(social._handle_replicate_certify(post({})))
    assert second["certified"] is True and second["counted"] is False
    assert table.store[("VOTES#ladder_replicator", "COUNT")]["cert_count"] == 1


def test_the_self_cert_dedup_row_never_expires(monkeypatch):
    """#1825: the published provenance promises a one-time-ever cert with no window
    qualifier. A TTL here would let the same source re-certify every 8 days and
    inflate a counter that no reset ever corrects (VOTES# is SYSTEM_STATE)."""
    table, _s3, _sec = wire(monkeypatch)
    social._handle_replicate_certify(post({}))
    row = next(r for r in table.puts if str(r["sk"]).startswith("REPL#"))
    assert "ttl" not in row


def test_the_self_cert_stores_no_personal_identifier(monkeypatch):
    """Only an ip_hash — already the site's dedup primitive — and an aggregate."""
    table, _s3, _sec = wire(monkeypatch)
    social._handle_replicate_certify(post({}, ip="203.0.113.7"))
    row = next(r for r in table.puts if str(r["sk"]).startswith("REPL#"))
    assert "203.0.113.7" not in json.dumps(row, default=str)
    assert set(row) == {"pk", "sk", "voted_at"}


# ──────────────────────────────────────────────────────────────────────────────
# 15. The cohort strip — anonymous distribution with a hard k-anonymity floor
# ──────────────────────────────────────────────────────────────────────────────

COHORT_KEY = "site/config/cohort_week.json"
COHORT_CFG = {
    "metric_id": "resting_heart_rate",
    "label": "Resting heart rate",
    "unit": "bpm",
    "week": CURRENT_WEEK,
    "matthew_value": 52,
    "axis_min": 40,
    "axis_max": 90,
    "lower_is_better": True,
}


def _cohort_s3(cfg=None) -> FakeS3:
    return FakeS3({COHORT_KEY: cfg if cfg is not None else dict(COHORT_CFG)})


def _cohort_and_challenge_s3() -> FakeS3:
    """One bucket carrying every config the flag-mutation drivers need."""
    return FakeS3({COHORT_KEY: dict(COHORT_CFG), CATALOG_SITE_KEY: json.loads(json.dumps(CATALOG))})


def _cohort_rows(*values) -> list:
    pk = social._cohort_partition(COHORT_CFG["metric_id"], COHORT_CFG["week"])
    return [{"pk": pk, "sk": f"SUBMIT#ip{i:02d}", "value": v} for i, v in enumerate(values)]


def test_the_cohort_partition_is_never_a_user_source_partition():
    """The structural privacy invariant: Matthew's stats pipelines only ever query
    `USER#…#SOURCE#…`, so pooled reader numbers must live somewhere they cannot
    reach. Asserted against the one minting helper."""
    pk = social._cohort_partition("resting_heart_rate", CURRENT_WEEK)
    assert pk.startswith(social.COHORT_PK_PREFIX) and "USER#" not in pk


def test_a_reader_number_is_recorded_once_per_participant_per_week(monkeypatch):
    table, _s3, _sec = wire(monkeypatch, s3=_cohort_s3())
    assert ok_body(social._handle_cohort_submit(post({"value": 55})))["week"] == CURRENT_WEEK
    row = table.puts[0]
    assert row["pk"].startswith("COHORT#") and row["sk"].startswith("SUBMIT#")


def test_the_submission_response_never_echoes_n_or_anyone_elses_number(monkeypatch):
    """Echoing n below the k-floor would defeat the gate on the read side."""
    wire(monkeypatch, table=FakeSocialTable(_cohort_rows(50, 51, 52)), s3=_cohort_s3())
    body = ok_body(social._handle_cohort_submit(post({"value": 55})))
    assert set(body) - {"_meta"} == {"submitted", "metric_id", "week"}


def test_a_second_submission_from_the_same_ip_in_the_same_week_is_refused(monkeypatch):
    wire(monkeypatch, s3=_cohort_s3())
    social._handle_cohort_submit(post({"value": 55}))
    assert social._handle_cohort_submit(post({"value": 56}))["statusCode"] == 429


def test_a_submission_with_no_active_cohort_week_is_a_404_not_a_stray_write(monkeypatch):
    table, _s3, _sec = wire(monkeypatch, s3=FakeS3())
    assert social._handle_cohort_submit(post({"value": 55}))["statusCode"] == 404
    assert table.puts == []


@pytest.mark.parametrize("value", [None, True, "abc", float("nan"), float("inf"), 39, 91])
def test_a_value_that_is_not_a_finite_in_range_number_is_refused(value, monkeypatch):
    """Every coercion edge that could 500 the route or poison the histogram:
    missing, boolean (a Python int!), non-numeric, NaN, infinity, and both sides of
    the configured axis (40..90)."""
    table, _s3, _sec = wire(monkeypatch, s3=_cohort_s3())
    body = json.dumps({"value": value}) if value == value and value not in (float("inf"),) else '{"value": %s}' % json.dumps(str(value))
    resp = social._handle_cohort_submit(post(body))
    assert resp["statusCode"] == 400, (value, resp)
    assert table.puts == []


def test_the_axis_boundaries_themselves_are_accepted(monkeypatch):
    """Inclusive on both ends — a reader whose real number is the axis minimum must
    not be told it's invalid."""
    for value in (40, 90):
        wire(monkeypatch, s3=_cohort_s3())
        assert social._handle_cohort_submit(post({"value": value}))["statusCode"] == 200


def test_a_malformed_cohort_config_deactivates_the_strip_rather_than_faking_one(monkeypatch):
    """An inverted or non-numeric axis is not a metric. Fail closed: the strip
    self-hides rather than rendering a chart over a nonsense scale."""
    for bad in ({**COHORT_CFG, "axis_min": 90, "axis_max": 40}, {**COHORT_CFG, "axis_max": "wide"}, {"week": CURRENT_WEEK}):
        wire(monkeypatch, s3=_cohort_s3(bad))
        assert ok_body(social.handle_cohort_strip())["active"] is False


def test_the_cohort_strip_publishes_nothing_below_the_k_anonymity_floor(monkeypatch):
    """A HARD gate, not copy: with n below the floor there is no histogram, no
    quartiles and no min/max — nothing from which one participant's number could be
    reconstructed."""
    wire(monkeypatch, table=FakeSocialTable(_cohort_rows(44, 50, 56, 62)), s3=_cohort_s3())
    body = ok_body(social.handle_cohort_strip())
    assert body["visible"] is False and body["n"] == 4
    for leaky in ("bins", "min", "max", "median", "p25", "p75"):
        assert leaky not in body


def test_the_k_anonymity_floor_is_exactly_five(monkeypatch):
    """Pinned on both sides so an off-by-one cannot quietly publish a 4-person
    distribution. The floor value itself is read from COHORT_K_FLOOR."""
    floor = social.COHORT_K_FLOOR
    below = [50 + i for i in range(floor - 1)]
    at = [50 + i for i in range(floor)]
    wire(monkeypatch, table=FakeSocialTable(_cohort_rows(*below)), s3=_cohort_s3())
    assert ok_body(social.handle_cohort_strip())["visible"] is False
    wire(monkeypatch, table=FakeSocialTable(_cohort_rows(*at)), s3=_cohort_s3())
    assert ok_body(social.handle_cohort_strip())["visible"] is True


def test_the_cohort_distribution_is_aggregates_only_never_individual_submissions(monkeypatch):
    wire(monkeypatch, table=FakeSocialTable(_cohort_rows(44, 50, 56, 62, 80)), s3=_cohort_s3())
    blob = json.dumps(ok_body(social.handle_cohort_strip()))
    assert "SUBMIT#" not in blob and "ip_hash" not in blob and "logged_at" not in blob


def test_the_cohort_quartiles_and_histogram_are_the_arithmetic_they_claim(monkeypatch):
    """Hand-derived over values [44, 50, 56, 62, 80] on a 40..90 axis with 12 bins:

    bin index = int((v - 40) / 50 * 12)
      44 -> int(0.96) = 0 · 50 -> int(2.4) = 2 · 56 -> int(3.84) = 3
      62 -> int(5.28) = 5 · 80 -> int(9.6)  = 9
    -> bins = [1,0,1,1,0,1,0,0,0,1,0,0]

    linear-interpolated percentiles with n = 5, k = (n-1)*p:
      p25: k = 1.0 -> values[1] = 50
      p50: k = 2.0 -> values[2] = 56
      p75: k = 3.0 -> values[3] = 62
    """
    wire(monkeypatch, table=FakeSocialTable(_cohort_rows(44, 50, 56, 62, 80)), s3=_cohort_s3())
    body = ok_body(social.handle_cohort_strip())
    assert body["bins"] == [1, 0, 1, 1, 0, 1, 0, 0, 0, 1, 0, 0]
    assert sum(body["bins"]) == body["n"] == 5
    assert (body["min"], body["p25"], body["median"], body["p75"], body["max"]) == (44, 50, 56, 62, 80)


def test_matthews_percentile_is_his_rank_among_the_pool_not_his_row(monkeypatch):
    """Hand-derived: his value is 52; two of the five pooled numbers (44, 50) are
    below it, so round(2/5*100) = 40th percentile. His own submission is never in
    the pool — it comes from the weekly config."""
    wire(monkeypatch, table=FakeSocialTable(_cohort_rows(44, 50, 56, 62, 80)), s3=_cohort_s3())
    assert ok_body(social.handle_cohort_strip())["matthew_percentile"] == 40


def test_every_published_cohort_aggregate_ships_its_sample_size(monkeypatch):
    """ADR-105: the n rides beside the number, on both sides of the k-gate, so a
    reader always knows how many people the strip describes."""
    for values in (_cohort_rows(50, 51), _cohort_rows(44, 50, 56, 62, 80)):
        wire(monkeypatch, table=FakeSocialTable(values), s3=_cohort_s3())
        assert ok_body(social.handle_cohort_strip())["n"] == len(values)


def test_a_submission_outside_the_configured_axis_is_excluded_from_the_distribution(monkeypatch):
    """Defence in depth on the read side: a row written under a previous week's
    axis must not distort this week's histogram."""
    rows = _cohort_rows(44, 50, 56, 62, 80) + _cohort_rows(9999)[:1]
    rows[-1]["sk"] = "SUBMIT#stray"
    wire(monkeypatch, table=FakeSocialTable(rows), s3=_cohort_s3())
    assert ok_body(social.handle_cohort_strip())["n"] == 5


def test_the_cohort_strip_reports_a_database_error_rather_than_an_empty_distribution(monkeypatch):
    """An empty 200 here would render "n=0, waiting for participants" over a pool
    that may be full — a wrong number, not a missing one."""
    wire(monkeypatch, table=FakeSocialTable(fail={"query"}), s3=_cohort_s3())
    assert social.handle_cohort_strip()["statusCode"] == 500


def test_the_cohort_config_miss_is_not_cached_so_a_new_week_appears_on_its_own(monkeypatch):
    """#1821: caching the MISS pinned a warm container on "no cohort week" until
    recycle, and at week rollover let containers disagree about which partition to
    write. Pinned here as the corrected behaviour."""
    s3 = FakeS3()
    wire(monkeypatch, s3=s3)
    assert ok_body(social.handle_cohort_strip())["active"] is False
    s3.objects[COHORT_KEY] = dict(COHORT_CFG)
    assert ok_body(social.handle_cohort_strip())["active"] is True


# ──────────────────────────────────────────────────────────────────────────────
# 16. Warm-container config caches
# ──────────────────────────────────────────────────────────────────────────────


def test_the_live_challenge_catalog_cache_retries_a_failed_load(monkeypatch):
    """`handle_challenges` guards its cache with `config_cache_valid`, so a
    transient S3 error doesn't pin the container. The contrast with
    `handle_challenge_catalog` (below) is the finding."""
    s3 = FakeS3()
    wire(monkeypatch, s3=s3)
    assert ok_body(social.handle_challenges())["count"] == 0
    s3.objects[CATALOG_ROOT_KEY] = json.loads(json.dumps(CATALOG))
    monkeypatch.setattr(social, "_challenges_cache", None)
    monkeypatch.setattr(social, "_challenges_cache_at", None)
    assert ok_body(social.handle_challenges())["count"] > 0


def test_a_transient_s3_failure_does_not_permanently_empty_the_challenge_catalog(monkeypatch):
    """Fixed by #2221 (was xfail). `_load_s3_json` returns `{}` on ANY failure and
    `{}` is not None, so the old `if _challenge_catalog_cache is None:` guard pinned
    a warm container on an empty catalog for its whole life after one S3 blip —
    /api/challenge_catalog served no challenges and /api/challenge_vote 503'd."""
    s3 = FakeS3()
    wire(monkeypatch, s3=s3)
    assert ok_body(social.handle_challenge_catalog())["challenges"] == []
    s3.objects[CATALOG_SITE_KEY] = json.loads(json.dumps(CATALOG))
    assert ok_body(social.handle_challenge_catalog())["challenges"], "the empty catalog was cached forever"


def test_a_corrected_challenge_catalog_starts_serving_without_a_container_recycle(monkeypatch):
    """Fixed by #2221 (was xfail): the catalog read now carries a `config_cache_valid`
    expiry stamp like its sibling `_challenges_cache` (#2019), so a published
    correction — including one that flips an entry to `public: false` — starts
    serving on its own instead of waiting for a Lambda recycle.

    The TTL is driven to 0 rather than the cache being reset by hand: with the old
    `is None` guard, expiring the TTL changes nothing and this still fails. Resetting
    the module global instead would pass either way."""
    monkeypatch.setattr(sac, "CONFIG_CACHE_TTL_SECONDS", 0)
    s3 = _catalog_s3()
    wire(monkeypatch, s3=s3)
    assert "cold-shower-finish" in {c["id"] for c in ok_body(social.handle_challenge_catalog())["challenges"]}
    # The operator publishes a correction that withdraws the entry.
    s3.objects[CATALOG_SITE_KEY] = {"challenges": [{"id": "cold-shower-finish", "name": "Cold shower finish", "public": False}]}
    assert "cold-shower-finish" not in {c["id"] for c in ok_body(social.handle_challenge_catalog())["challenges"]}


def test_the_current_challenge_banner_is_absent_rather_than_a_fake_day_zero(monkeypatch):
    """ADR-104: the old "Check back soon" placeholder leaked to the UI as a real
    day-0-of-7 challenge. Absence is `None`, and it is edge-cached at the #2289
    class floor (300s — this door is unmetered by design, so even the empty state
    must be absorbable by CloudFront; a new Monday challenge appears within 5 min)."""
    wire(monkeypatch, s3=FakeS3())
    resp = social.handle_current_challenge()
    assert ok_body(resp)["current_challenge"] is None
    assert resp["headers"]["Cache-Control"] == "public, max-age=300, s-maxage=300"
