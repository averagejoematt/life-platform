"""Shared in-memory fakes for the reading-domain tests.

No moto (repo convention). FakeTable is a real query engine — it EVALUATES the
boto3 Key condition objects (eq / begins_with / between / lte / AND) against an
in-memory store, including IndexName GSI queries with SPARSE semantics (items
lacking the index pk attribute don't participate). This lets the access-pattern
tests prove the real query shapes, not stubbed returns.
"""

from __future__ import annotations

from boto3.dynamodb.conditions import AttributeBase


def _resolve(v, item):
    return item.get(v.name) if isinstance(v, AttributeBase) else v


def _eval(cond, item) -> bool:
    op = cond.expression_operator
    vals = cond._values
    if op == "AND":
        return all(_eval(c, item) for c in vals)
    if op == "OR":
        return any(_eval(c, item) for c in vals)
    attr = vals[0]
    name = attr.name if isinstance(attr, AttributeBase) else attr
    actual = item.get(name)
    if op == "=":
        return actual == _resolve(vals[1], item)
    if op == "<=":
        return actual is not None and actual <= _resolve(vals[1], item)
    if op == "<":
        return actual is not None and actual < _resolve(vals[1], item)
    if op == ">=":
        return actual is not None and actual >= _resolve(vals[1], item)
    if op == ">":
        return actual is not None and actual > _resolve(vals[1], item)
    if op == "BETWEEN":
        lo, hi = _resolve(vals[1], item), _resolve(vals[2], item)
        return actual is not None and lo <= actual <= hi
    if op == "begins_with":
        return isinstance(actual, str) and actual.startswith(_resolve(vals[1], item))
    raise NotImplementedError(f"FakeTable: unsupported operator {op!r}")


class FakeTable:
    INDEXES = {"GSI1": ("GSI1PK", "GSI1SK"), "GSI2": ("GSI2PK", "GSI2SK")}

    def __init__(self):
        self.store: dict[tuple, dict] = {}

    def put_item(self, Item):
        self.store[(Item["pk"], Item["sk"])] = dict(Item)

    def get_item(self, Key):
        it = self.store.get((Key["pk"], Key["sk"]))
        return {"Item": dict(it)} if it else {}

    def query(self, **kw):
        cond = kw["KeyConditionExpression"]
        index = kw.get("IndexName")
        forward = kw.get("ScanIndexForward", True)
        items = [dict(v) for v in self.store.values()]
        if index:
            pk_attr, sk_attr = self.INDEXES[index]
            items = [it for it in items if pk_attr in it]  # SPARSE: must project into the index
            sort_attr = sk_attr
        else:
            sort_attr = "sk"
        matched = [it for it in items if _eval(cond, it)]
        matched.sort(key=lambda it: it.get(sort_attr, ""), reverse=not forward)
        return {"Items": matched}


class FakeS3:
    def __init__(self):
        self.puts: list[dict] = []

    def put_object(self, **kw):
        self.puts.append(kw)
        return {"ETag": "fake"}
