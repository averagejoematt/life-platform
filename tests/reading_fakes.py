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


class ConditionalCheckFailedException(Exception):
    """What boto3 raises when a conditional put is refused.

    Named to match the real exception CLASS name, because that is what production
    code inspects (`"ConditionalCheckFailed" in type(e).__name__`) — a fake that
    raised a generically-named error would let a broken duplicate-detection branch
    pass its own test. #3114/#3115.
    """


def _eval_condition(expr: str, item: dict | None, values: dict) -> bool:
    """Evaluate the ConditionExpression subset this repo's conditional puts use.

    Supported: `attribute_not_exists(x)`, `attribute_exists(x)`, `x = :v`, `x < :v`,
    joined by AND/OR (OR binds loosest, matching the expressions in use — none of
    them parenthesise). Anything else raises rather than silently passing: a fake
    that answers True to an expression it did not understand is how a dedup guard
    gets "tested" without ever being exercised.
    """

    def _atom(tok: str) -> bool:
        tok = tok.strip()
        if tok.startswith("attribute_not_exists(") and tok.endswith(")"):
            return item is None or tok[len("attribute_not_exists(") : -1].strip() not in item
        if tok.startswith("attribute_exists(") and tok.endswith(")"):
            return item is not None and tok[len("attribute_exists(") : -1].strip() in item
        for op in (" = ", " < ", " > ", " <= ", " >= "):
            if op in tok:
                name, placeholder = (p.strip() for p in tok.split(op, 1))
                if item is None or name not in item:
                    return False
                actual, expected = item[name], values[placeholder]
                return {
                    " = ": lambda: actual == expected,
                    " < ": lambda: actual < expected,
                    " > ": lambda: actual > expected,
                    " <= ": lambda: actual <= expected,
                    " >= ": lambda: actual >= expected,
                }[op]()
        raise NotImplementedError(f"FakeTable: unsupported condition atom {tok!r}")

    return any(all(_atom(a) for a in clause.split(" AND ")) for clause in expr.split(" OR "))


class FakeTable:
    INDEXES = {"GSI1": ("GSI1PK", "GSI1SK"), "GSI2": ("GSI2PK", "GSI2SK")}

    def __init__(self):
        self.store: dict[tuple, dict] = {}
        self.put_calls: list[dict] = []

    def put_item(self, Item, ConditionExpression=None, ExpressionAttributeValues=None, **_kw):
        self.put_calls.append(dict(Item))
        if ConditionExpression is not None:
            current = self.store.get((Item["pk"], Item["sk"]))
            if not _eval_condition(ConditionExpression, current, ExpressionAttributeValues or {}):
                raise ConditionalCheckFailedException(f"condition {ConditionExpression!r} failed")
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
