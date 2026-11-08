"""#5656 release (2026-11-07): a whole-history read of a public-variant partition follows every DynamoDB page.

Found in production: phase 1 roughly doubled each character_sheet record, one query page then ended at 2026-09-21, and
the old /api/timeline silently lost four level-ups. ``common.query_pages`` follows LastEvaluatedKey; the guard below
fails any direct, unpaged, unlimited ``.query(`` whose key names one of the three partitions."""

import ast
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lambdas"))

from common.query_pages import query_pages  # noqa: E402

PARTS = ("character_sheet", "day_grade", "character_receipt")


class _Paged:
    """A table whose query returns ``page`` items at a time, like DynamoDB's 1 MB cap."""

    def __init__(self, n, page):
        self.items = [{"pk": "p", "sk": f"DATE#{i:03d}"} for i in range(n)]
        self.page, self.calls = page, 0

    def query(self, **kw):
        self.calls += 1
        start = 0
        if "ExclusiveStartKey" in kw:
            start = [i["sk"] for i in self.items].index(kw["ExclusiveStartKey"]["sk"]) + 1
        take = min(self.page, kw.get("Limit") or self.page)
        out = self.items[start : start + take]
        r = {"Items": out, "Count": len(out)}
        if start + take < len(self.items):
            r["LastEvaluatedKey"] = {"pk": "p", "sk": out[-1]["sk"]}
        return r


def test_query_pages_returns_every_page():
    t = _Paged(25, 7)
    got = query_pages(t, KeyConditionExpression="x")
    assert [i["sk"] for i in got["Items"]] == [i["sk"] for i in t.items] and got["Count"] == 25 and t.calls == 4


def test_mutation_control_one_query_truncates():
    assert len(_Paged(25, 7).query(KeyConditionExpression="x")["Items"]) == 7


def test_a_limit_still_caps_the_total_across_pages():
    got = query_pages(_Paged(25, 7), KeyConditionExpression="x", Limit=10)
    assert len(got["Items"]) == 10


def _unpaged_partition_queries():
    hits = []
    for p in sorted((ROOT / "lambdas").rglob("*.py")):
        src = p.read_text(encoding="utf-8")
        if not any(x in src for x in PARTS):
            continue
        tree = ast.parse(src)
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            fseg = ast.get_source_segment(src, fn) or ""
            if "LastEvaluatedKey" in fseg:
                continue
            for node in ast.walk(fn):
                if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "query"):
                    continue
                seg = ast.get_source_segment(src, node) or ""
                if "Limit" in seg:
                    continue  # a bounded read; its bound is its own contract
                names = set(re.findall(r"\b([a-z_][a-z0-9_]*)\b", seg))
                ctx = seg + "".join(ln for ln in fseg.splitlines() if any(re.match(rf"\s*{n}\s*=", ln) for n in names))
                if any(x in ctx for x in PARTS):
                    hits.append(f"{p.relative_to(ROOT)}:{node.lineno} {fn.name}")
    return hits


def test_no_unpaged_unlimited_query_on_a_public_variant_partition():
    assert _unpaged_partition_queries() == []


def test_mutation_control_the_guard_sees_a_direct_query(tmp_path, monkeypatch):
    src = 'def f(table):\n    pk = "USER#m#SOURCE#character_sheet"\n    return table.query(KeyConditionExpression=pk)\n'
    tree = ast.parse(src)
    call = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "query"][0]
    seg = ast.get_source_segment(src, call)
    names = set(re.findall(r"\b([a-z_][a-z0-9_]*)\b", seg))
    ctx = seg + "".join(ln for ln in src.splitlines() if any(re.match(rf"\s*{n}\s*=", ln) for n in names))
    assert "character_sheet" in ctx and "Limit" not in seg and "LastEvaluatedKey" not in src
