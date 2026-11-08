"""#5656 release (2026-11-07): a whole-history read of a public-variant partition follows every DynamoDB page.

Found in production: phase 1 roughly doubled each character_sheet record, one query page then ended at 2026-09-21, and
the old /api/timeline silently lost four level-ups. ``common.query_pages`` follows LastEvaluatedKey; the call sites
that needed it were found by a page-limited walk of every public route plus an AST sweep (private release evidence)."""

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lambdas"))

from common.query_pages import query_pages  # noqa: E402


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
