"""tests/fakes.py — shared in-memory DynamoDB test double (#824, R22-MOD-02).

Before this file, 29+ test files each hand-rolled a near-identical fake
DynamoDB table stub (query/put_item/update_item, sometimes get_item) with
copy-pasted structure and small per-test variation. This module extracts the
one shape almost all of them actually needed:

  - a `.rows` list that `query()` serves regardless of kwargs (the dominant
    pattern — most callers never filter on the fake, they just want canned
    data back), optionally sliced by `Limit`;
  - a `.store` dict keyed by (pk, sk) backing `get_item`/`put_item`/
    `delete_item`, seeded from `rows` at construction;
  - `.puts` / `.updates` / `.deletes` / `.query_calls` call logs for
    assertions (`assert fake.updates[0][...] == ...`, `len(fake.puts)`, etc.);
  - optional `query_hook` / `get_item_hook` / `put_item_hook` /
    `update_item_hook` callables for the genuinely bespoke per-test behaviour
    (sequenced responses, pk-dispatch, conditional-check emulation, injected
    failures) that doesn't fit the generic shape — see each hook's call
    signature below.

Not every hand-rolled fake fit this shape cleanly. A few evaluate real boto3
`Key()`/`Attr()` condition trees against a store (a genuine mini query
engine, not a stub) — `tests/reading_fakes.py` and
`tests/test_coach_memoir_lambda.py::FakeTable` — and one composes a
dict-store with a `batch_writer()` context manager plus pk-filtered query
where the copy-vs-reference semantics of returned items are load-bearing for
the code under test (`tests/test_food_delivery_reimport_479.py::FakeTable`).
Those are intentionally left as their own classes rather than forced into a
shape that doesn't match their actual behavior — see #824's PR description
for the full list.
"""

from __future__ import annotations

from typing import Any, Callable, Optional


class FakeDdbTable:
    """In-memory stand-in for a boto3 DynamoDB `Table` resource.

    Two ways to seed it:
      - `FakeDdbTable(rows=[...])` — the "canned rows" flavor: `query()`
        returns `{"Items": list(self.rows)}` regardless of kwargs (the
        overwhelming majority of hand-rolled fakes did exactly this).
      - `FakeDdbTable(rows=[...], filter_by_pk=True)` — `query()` instead
        filters `self.store.values()` by `ExpressionAttributeValues[":pk"]`
        matching `pk_field`, for the handful of callers that actually query a
        single partition.

    `put_item`/`get_item`/`delete_item` always operate against the
    (pk, sk)-keyed `self.store` (seeded from `rows` at construction unless
    `seed_store=False`), so both flavors can mix freely.

    Pass `query_hook(table, **kwargs)`, `get_item_hook(table, key, **kwargs)`,
    `put_item_hook(table, item, **kwargs)`, or `update_item_hook(table, **kwargs)`
    to override the corresponding method's return/side-effect entirely — the
    call is still logged in `.query_calls`/`.puts`/`.updates` first. This is
    the escape hatch for per-test variation (sequenced responses, pk-dispatch
    on a boto3 Key condition, injected failures, conditional-check emulation)
    that doesn't fit the generic shape without forcing a bad fit.
    """

    def __init__(
        self,
        rows: Optional[list] = None,
        *,
        pk_field: str = "pk",
        sk_field: str = "sk",
        filter_by_pk: bool = False,
        seed_store: bool = True,
        store_items: Optional[list] = None,
        query_hook: Optional[Callable[..., dict]] = None,
        get_item_hook: Optional[Callable[..., dict]] = None,
        put_item_hook: Optional[Callable[..., None]] = None,
        update_item_hook: Optional[Callable[..., dict]] = None,
    ):
        self.rows = list(rows) if rows is not None else []
        self.pk_field = pk_field
        self.sk_field = sk_field
        self.filter_by_pk = filter_by_pk

        self.puts: list = []
        self.updates: list = []
        self.deletes: list = []
        self.query_calls: list = []

        self._query_hook = query_hook
        self._get_item_hook = get_item_hook
        self._put_item_hook = put_item_hook
        self._update_item_hook = update_item_hook

        self.store: dict = {}
        # `store_items` seeds get_item/put_item's keyed store independently of
        # `rows` (what query() serves) — for the cases where the two differ,
        # e.g. query() always answers "no rows" while get_item must still find
        # a specific pre-seeded record.
        seed_source = store_items if store_items is not None else (self.rows if seed_store else [])
        if seed_source:
            for item in seed_source:
                self._seed(item)

    # -- key helpers ------------------------------------------------------
    def _key_of(self, mapping: dict) -> tuple:
        return (mapping.get(self.pk_field), mapping.get(self.sk_field))

    def _seed(self, item: dict) -> None:
        self.store[self._key_of(item)] = item

    # -- writes -------------------------------------------------------------
    def put_item(self, Item: Optional[dict] = None, **kwargs) -> dict:
        item = Item if Item is not None else kwargs.get("Item")
        self.puts.append(item)
        if self._put_item_hook is not None:
            self._put_item_hook(self, item, **kwargs)
        else:
            self._seed(item)
        return {}

    def update_item(self, **kwargs) -> dict:
        self.updates.append(kwargs)
        if self._update_item_hook is not None:
            return self._update_item_hook(self, **kwargs)
        return {}

    def delete_item(self, Key: Optional[dict] = None, **kwargs) -> dict:
        key = Key if Key is not None else kwargs.get("Key")
        self.deletes.append(key)
        self.store.pop(self._key_of(key), None)
        return {}

    def batch_writer(self):
        return _FakeBatchWriter(self)

    # -- reads ----------------------------------------------------------------
    def get_item(self, Key: Optional[dict] = None, **kwargs) -> dict:
        key = Key if Key is not None else kwargs
        if self._get_item_hook is not None:
            return self._get_item_hook(self, key, **kwargs)
        item = self.store.get(self._key_of(key))
        return {"Item": item} if item is not None else {}

    def query(self, **kwargs) -> dict:
        self.query_calls.append(kwargs)
        if self._query_hook is not None:
            return self._query_hook(self, **kwargs)
        items: list = list(self.rows)
        if self.filter_by_pk:
            eav = kwargs.get("ExpressionAttributeValues") or {}
            pk = eav.get(":pk")
            if pk is not None:
                items = [i for i in self.store.values() if i.get(self.pk_field) == pk]
        limit = kwargs.get("Limit")
        if limit is not None:
            items = items[:limit]
        return {"Items": items}


class _FakeBatchWriter:
    """Minimal `Table.batch_writer()` context manager double."""

    def __init__(self, table: FakeDdbTable):
        self._table = table

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def put_item(self, Item: dict) -> None:
        self._table.put_item(Item=Item)


# ── reusable hook factories for the recurring "board session" shape ──────────
# (tests/test_board_followup_sessions.py + tests/test_untrusted_reader_delimiter.py
# both hand-rolled a near-identical class around this exact update semantics —
# bump followup_count, append the new turn to threads[pid], optionally enforce
# the per-session follow-up cap + IP binding via ConditionalCheckFailedException.)


def json_safe_put_hook(table: FakeDdbTable, item: dict, **_kwargs) -> None:
    """put_item_hook: round-trip the item through JSON (Decimal/date -> str)
    before storing, matching what a real DDB write effectively does to the
    types callers see back out."""
    import json

    table.store[table._key_of(item)] = json.loads(json.dumps(item, default=str))


def make_session_update_hook(enforce_cap: bool = True) -> Callable[..., dict]:
    """update_item_hook factory for the BOARDSESS# follow-up shape.

    With `enforce_cap=True` (test_board_followup_sessions.py's behavior): a
    missing session, an exhausted follow-up cap, or an IP mismatch each raise
    ConditionalCheckFailedException. With `enforce_cap=False`
    (test_untrusted_reader_delimiter.py's behavior): only a missing session
    raises; the cap/IP aren't checked.
    """

    def _hook(table: FakeDdbTable, Key, ExpressionAttributeValues, ExpressionAttributeNames=None, **_kwargs) -> dict:
        item = table.store.get(table._key_of(Key))
        if item is None:
            raise Exception("ConditionalCheckFailedException")
        if enforce_cap:
            cap = float(ExpressionAttributeValues[":cap"])
            ip = ExpressionAttributeValues[":ip"]
            if float(item.get("followup_count", 0)) >= cap or item.get("ip_hash") != ip:
                raise Exception("ConditionalCheckFailedException")
        item["followup_count"] = float(item.get("followup_count", 0)) + 1
        pid = (ExpressionAttributeNames or {}).get("#pid")
        if pid:
            item.setdefault("threads", {}).setdefault(pid, [])
            item["threads"][pid].extend(ExpressionAttributeValues[":turn"])
        return {}

    return _hook


def raise_hook(*_args: Any, **_kwargs: Any):
    """A query_hook/get_item_hook that always raises — for pinning fail-open
    or fail-soft behavior against a simulated DDB outage."""
    raise RuntimeError("ddb down")
