"""#2682 — an identical resubmission must not cost Matthew a second review.

`/api/experiment_suggest` built its sort key from a wall-clock timestamp:

    "sk": f"SUGGEST#{datetime.now(timezone.utc).isoformat()}"

so a double-click, a client retry or a flaky network wrote a SECOND moderation row for the
same submission. Both sibling capture doors already derive their id from the content —
`_handle_submit_finding` and `_handle_board_question` in `site_api_social_engage.py`, each
`sha256(f"{ip_hash}:{content}")[:12]` — and the bug bash verified live that they return the
same id twice for an identical body. This door was the outlier.

THE WRITE IS CONDITIONAL, NOT A PLAIN OVERWRITE, and the reason is the part a
key-derivation fix alone would have missed. Keying on content makes the retry hit the same
item; an unconditional `put_item` would then REPLACE it — resetting `created_at` and
stamping `status: "pending"` back over a moderation decision Matthew had already made. A
reader's double-click three days later would silently un-approve their own suggestion. So a
retry is a no-op on an existing row, and `test_a_retry_does_not_overwrite_a_moderated_row`
is the assertion that pins it.

The id is returned on both paths. A caller who cannot see the id cannot distinguish an
accepted retry from a new submission — the same opacity the issue is about, relocated.

The fourth acceptance box asks for one test covering the identical-retry case across all
three capture doors. It is here, derived: the two siblings' id derivations are read out of
their own source rather than restated, so a future door that keys on the clock is caught by
`test_no_capture_door_keys_its_identity_on_the_clock`.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import pathlib
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")

import pytest  # noqa: E402
from web import site_api_social as facade, site_api_social_experiments as mod  # noqa: E402

IDEA = "Try a two-week 10pm lights-out protocol and track HRV against the baseline."
SOURCE = "a reader on the cockpit page"


class _CCF(Exception):
    """Stand-in for botocore's ConditionalCheckFailedException — the handler matches on
    the name in `str(e)`, which is how every sibling in `lambdas/web/` detects it."""

    def __init__(self):
        super().__init__("An error occurred (ConditionalCheckFailedException) when calling PutItem")


class Table:
    """Implements the attribute_not_exists(sk) contract rather than recording the call.

    A mock that only records `put_item` would prove the ConditionExpression was SENT and
    nothing about what it does — and "the retry leaves the existing row alone" is a
    statement about the outcome, not about the argument.
    """

    def __init__(self):
        self.items: dict[tuple, dict] = {}
        self.puts: list[dict] = []

    def put_item(self, Item, ConditionExpression=None, **_kw):
        self.puts.append(Item)
        key = (Item["pk"], Item["sk"])
        if ConditionExpression == "attribute_not_exists(sk)" and key in self.items:
            raise _CCF()
        self.items[key] = dict(Item)
        return {}


@pytest.fixture
def table(monkeypatch):
    t = Table()
    monkeypatch.setattr(facade, "table", t)
    monkeypatch.setattr(facade, "_rate_check", lambda *a, **k: (True, 99, 0))
    monkeypatch.setattr(facade, "_is_blocked_vice", lambda _t: False)
    return t


def _post(idea=IDEA, source=SOURCE, ip="203.0.113.9"):
    event = {
        "body": json.dumps({"idea": idea, "source": source}),
        "headers": {"x-forwarded-for": ip},
        "requestContext": {"http": {"method": "POST", "sourceIp": ip}},
    }
    return mod._handle_experiment_suggest(event, _g=vars(facade))


def _body(resp):
    return json.loads(resp["body"])


# ── the defect ───────────────────────────────────────────────────────────────


def test_an_identical_resubmission_creates_exactly_one_row(table):
    first, second = _post(), _post()
    assert first["statusCode"] == 200 and second["statusCode"] == 200
    assert len(table.items) == 1, f"{len(table.items)} moderation rows for one suggestion"


def test_an_identical_resubmission_returns_the_same_id(table):
    """Acceptance box 2, and the thing that makes the fix observable to the caller."""
    first, second = _body(_post()), _body(_post())
    assert first["id"] == second["id"] and first["id"]
    assert first["duplicate"] is False and second["duplicate"] is True


def test_the_sort_key_is_derived_from_the_content(table):
    _post()
    sk = next(iter(table.items))[1]
    assert sk == f"SUGGEST#{_body(_post())['id']}"
    assert ":" not in sk and "T" not in sk.split("#", 1)[1], f"the key still looks like a timestamp: {sk}"


def test_a_retry_does_not_overwrite_a_moderated_row(table):
    """The reason the write is CONDITIONAL and not just re-keyed.

    Without the condition, the retry's put would replace the row — resetting created_at and
    stamping `pending` over Matthew's decision. A reader double-clicking three days later
    would silently un-approve their own suggestion.
    """
    _post()
    key = next(iter(table.items))
    table.items[key]["status"] = "approved"
    table.items[key]["created_at"] = "2026-08-01T00:00:00+00:00"

    _post()

    assert table.items[key]["status"] == "approved", "a retry un-approved a moderated suggestion"
    assert table.items[key]["created_at"] == "2026-08-01T00:00:00+00:00", "a retry reset the submission time"


# ── the controls ─────────────────────────────────────────────────────────────


def test_a_distinct_suggestion_still_creates_a_distinct_row(table):
    """Acceptance box 3. Idempotency that swallows a real second suggestion is worse."""
    _post()
    _post(idea="A completely different protocol: 30 minutes of morning daylight, 14 days.")
    assert len(table.items) == 2


def test_a_different_reader_submitting_the_same_idea_is_not_deduped(table):
    """The id includes the ip hash, exactly as both siblings do — two readers converging on
    the same idea is a signal, not a duplicate."""
    _post(ip="203.0.113.9")
    _post(ip="198.51.100.4")
    assert len(table.items) == 2


def test_the_id_matches_the_documented_derivation(table):
    """Hand-derived rather than read back from the code under test."""
    ip_hash = hashlib.sha256(b"203.0.113.9").hexdigest()[:16]
    expected = hashlib.sha256(f"{ip_hash}:{IDEA}:{SOURCE}".encode()).hexdigest()[:12]
    assert _body(_post())["id"] == expected


def test_validation_still_rejects_a_short_idea(table):
    resp = mod._handle_experiment_suggest(
        {"body": json.dumps({"idea": "too short"}), "headers": {}, "requestContext": {"http": {"sourceIp": "1.2.3.4"}}},
        _g=vars(facade),
    )
    assert resp["statusCode"] == 400
    assert table.items == {}


def test_a_storage_failure_is_still_a_500_not_a_silent_success(monkeypatch, table):
    """The condition check must not have swallowed genuine write failures."""

    def _boom(**_kw):
        raise RuntimeError("dynamodb is having a day")

    monkeypatch.setattr(table, "put_item", _boom)
    assert _post()["statusCode"] == 500


# ── the derived guard across all three capture doors (box 4) ─────────────────


CAPTURE_DOORS = [
    ("lambdas/web/site_api_social_experiments.py", "_handle_experiment_suggest"),
    ("lambdas/web/site_api_social_engage.py", "_handle_submit_finding"),
    ("lambdas/web/site_api_social_engage.py", "_handle_board_question"),
]


def _source_of(rel_path, func_name):
    tree = ast.parse((pathlib.Path(_REPO) / rel_path).read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == func_name:
            return ast.get_source_segment((pathlib.Path(_REPO) / rel_path).read_text(), node) or ""
    raise AssertionError(f"{func_name} not found in {rel_path}")


def test_the_capture_door_set_is_real():
    """Vacuity guard — a typo'd function name would make the sweep below pass on nothing."""
    for rel, fn in CAPTURE_DOORS:
        assert len(_source_of(rel, fn)) > 200, f"{fn} looks empty"


@pytest.mark.parametrize("rel,fn", CAPTURE_DOORS)
def test_every_capture_door_derives_its_identity_from_content(rel, fn):
    src = _source_of(rel, fn)
    assert "hashlib.sha256" in src, f"{fn} does not derive an id from its content"


@pytest.mark.parametrize("rel,fn", CAPTURE_DOORS)
def test_no_capture_door_keys_its_identity_on_the_clock(rel, fn):
    """The defect itself, stated as a rule the next door inherits.

    `datetime.now(...)` is fine for a `submitted_at` ATTRIBUTE — all three carry one. What
    must not happen is a clock reading inside the identity: the `sk`, the id, or the S3 key.
    """
    for line in _source_of(rel, fn).splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if "datetime.now" not in stripped:
            continue
        assert not any(
            marker in stripped for marker in ('"sk"', "'sk'", "_id =", "s3_key", "SUGGEST#", "Key=")
        ), f"{fn} builds an identity from the clock: {stripped}"
