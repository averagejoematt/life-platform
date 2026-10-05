"""tests/test_notion_reconcile_siblings_4631.py — #4631.

Two ways the Notion journal ingestion destroyed data it held the only processed copy of:

  1. The per-day reconcile deleted every stored row of a (date, template) that the run did
     not write. A run can reach an old date with ONE page in hand — a page edited today, or
     a page created today and dated back — so the date's other rows were deleted as orphans.
     A page the validator refused dropped out of the written set the same way.
  2. A page moving from a legacy positional key to its stable page-id key lost its
     enrichment: the carry read the NEW key (no row there yet) and the old row was deleted.

Every test drives the real handler against an in-memory table and an in-memory Notion that
answers the real query filter, with pages in the API's wire shape. All content is synthetic.
"""

import os

os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")

from datetime import datetime, timedelta, timezone  # noqa: E402
from decimal import Decimal  # noqa: E402

import ingestion.notion_lambda as nl  # noqa: E402
import pytest  # noqa: E402

OLD = "2026-08-10"  # far outside the scheduled two-day window
NOW = datetime(2026, 10, 4, 9, 0, tzinfo=timezone.utc)  # 02:00 PT on 2026-10-04
BODY = "synthetic fixture body"


def _pid(n):
    return f"00000000-0000-4000-8000-{n:012x}"


def _page(n, date=OLD, created=None, edited=None, dated=True):
    """One journal page as the Notion database query returns it (no Template → "journal")."""
    created = created or f"{date}T18:00:00.000Z"
    props = {"Name": {"id": "title", "type": "title", "title": [{"type": "text", "plain_text": f"fixture {n}"}]}}
    if dated:
        props["Date"] = {"id": "d", "type": "date", "date": {"start": date, "end": None, "time_zone": None}}
    return {
        "object": "page",
        "id": _pid(n),
        "created_time": created,
        "last_edited_time": edited or created,
        "archived": False,
        "properties": props,
    }


class FakeNotion:
    """Answers POST /databases/<id>/query by evaluating the filter the Lambda sends."""

    def __init__(self, pages):
        self.pages = list(pages)
        self.queries = 0
        self.fail_after = None  # fail every query after the Nth

    @staticmethod
    def _match(page, clause):
        if "or" in clause:
            return any(FakeNotion._match(page, c) for c in clause["or"])
        if "and" in clause:
            return all(FakeNotion._match(page, c) for c in clause["and"])
        if "property" in clause:
            value = ((page["properties"].get(clause["property"]) or {}).get("date") or {}).get("start", "")[:10]
            cond = clause["date"]
        else:
            value = page[clause["timestamp"]][:10]
            cond = clause[clause["timestamp"]]
        if not value:
            return False
        if "on_or_after" in cond:
            return value >= cond["on_or_after"]
        return value <= cond["on_or_before"]

    def post(self, endpoint, api_key, body=None):
        self.queries += 1
        if self.fail_after is not None and self.queries > self.fail_after:
            raise RuntimeError("notion unavailable")
        flt = (body or {}).get("filter")
        hits = [p for p in self.pages if not p.get("archived") and (flt is None or self._match(p, flt))]
        return {"results": hits, "has_more": False, "next_cursor": None}

    def get(self, endpoint, api_key):
        return {"results": [{"type": "paragraph", "paragraph": {"rich_text": [{"plain_text": BODY}]}}], "has_more": False}


class FakeTable:
    """The slice of the DynamoDB Table API the ingester uses, over a dict keyed by sk."""

    def __init__(self, rows=()):
        self.rows = {r["sk"]: dict(r) for r in rows}
        self.deleted = []

    def query(self, **kw):
        prefix = kw["KeyConditionExpression"]._values[1]._values[1]
        items = [dict(r) for sk, r in sorted(self.rows.items()) if sk.startswith(prefix)]
        wanted = [f.strip() for f in kw.get("ProjectionExpression", "").split(",") if f.strip()]
        if wanted:
            items = [{k: v for k, v in it.items() if k in wanted} for it in items]
        return {"Items": items}

    def get_item(self, Key, **kw):
        row = self.rows.get(Key["sk"])
        return {"Item": dict(row)} if row else {}

    def put_item(self, Item):
        self.rows[Item["sk"]] = dict(Item)

    def delete_item(self, Key):
        self.deleted.append(Key["sk"])
        self.rows.pop(Key["sk"], None)


class Log:
    def __init__(self):
        self.lines = []

    def _add(self, msg, *a, **k):
        self.lines.append(str(msg))

    info = warning = error = _add

    def decisions(self):
        return [ln for ln in self.lines if "reconcile decision" in ln]


def _stable_row(n, date=OLD, **extra):
    return {
        "pk": nl.PK,
        "sk": nl.build_sk(date, "journal", _pid(n)),
        "date": date,
        "notion_page_id": _pid(n),
        "raw_text": "stored",
        **extra,
    }


def _legacy_row(seq, n, date=OLD, **extra):
    return {"pk": nl.PK, "sk": f"DATE#{date}#journal#journal#{seq}", "date": date, "notion_page_id": _pid(n), "raw_text": "stored", **extra}


@pytest.fixture
def run(monkeypatch):
    """run(pages, rows, event={}) → (table, notion, log) after one handler invocation."""

    def _run(pages, rows, event=None, before=None):
        table, notion, log = FakeTable(rows), FakeNotion(pages), Log()
        monkeypatch.setattr(nl, "table", table)
        monkeypatch.setattr(nl, "logger", log)
        monkeypatch.setattr(nl, "notion_post", notion.post)
        monkeypatch.setattr(nl, "notion_get", notion.get)
        monkeypatch.setattr(nl, "get_secrets", lambda: ("fixture-key", "fixture-db"))
        monkeypatch.setattr(nl, "pacific_now", lambda: NOW - timedelta(hours=7))
        monkeypatch.setattr(nl, "pacific_today", lambda: "2026-10-04")
        monkeypatch.setattr(nl, "_archive_page_raw", lambda *a, **k: None)
        monkeypatch.setattr(nl, "_HAS_AUTH_BREAKER", False)
        monkeypatch.setattr(nl, "_INGEST_HEALTH_AVAILABLE", False)
        if before:
            before(table, notion)
        resp = nl.lambda_handler(event or {}, None)
        assert resp["statusCode"] == 200
        return table, notion, log

    return _run


def _journal_sks(table, date=OLD):
    return sorted(sk for sk in table.rows if sk.startswith(f"DATE#{date}#journal#journal#"))


# ── Defect 1: the reconcile and same-day siblings ─────────────────────────────


def test_one_edited_page_among_n_siblings_on_an_old_date_leaves_n_rows(run):
    """Four entries on an old date; one is edited today. The run fetches that one page only.
    All four entries must still be stored afterwards — on either key generation. (One test
    over both generations, reporting every offender, rather than one gate per parameter.)"""
    n = 4
    problems = []
    for keys in ("stable", "legacy"):
        pages = [_page(i) for i in range(1, n + 1)]
        pages[1]["last_edited_time"] = "2026-10-04T08:00:00.000Z"
        rows = [_stable_row(i) if keys == "stable" else _legacy_row(i, i) for i in range(1, n + 1)]

        table, _, _ = run(pages, rows)

        # On legacy keys the edited page's OWN old row is replaced by its stable row — no sibling goes.
        allowed = [] if keys == "stable" else [f"DATE#{OLD}#journal#journal#2"]
        if table.deleted != allowed:
            problems.append(f"{keys}: {len(table.deleted)} row(s) deleted, {len(allowed)} allowed")
        if len(_journal_sks(table)) != n:
            problems.append(f"{keys}: {len(_journal_sks(table))} rows stored after the run, {n} before")
        if {r["notion_page_id"] for r in table.rows.values()} != {_pid(i) for i in range(1, n + 1)}:
            problems.append(f"{keys}: an entry was lost")
    assert not problems, problems


def test_a_page_created_today_and_dated_to_an_old_day_leaves_n_plus_one_rows(run):
    n = 3
    pages = [_page(i) for i in range(1, n + 1)] + [_page(9, created="2026-10-04T08:00:00.000Z")]
    rows = [_legacy_row(i, i) for i in range(1, n + 1)]

    table, _, _ = run(pages, rows)

    assert table.deleted == []
    assert len(_journal_sks(table)) == n + 1


def test_a_validation_skipped_page_deletes_nothing(run, monkeypatch):
    """Both pages of a date are fetched; the validator refuses one. Its stored row — and
    every other row — stays, and the refused page is not written over."""
    import ingestion.ingestion_validator as iv

    real = iv.validate_item

    class _Refused:
        should_skip_ddb, errors, warnings = True, ["synthetic refusal"], []

    monkeypatch.setattr(
        iv, "validate_item", lambda src, item, d="": _Refused() if item["notion_page_id"] == _pid(2) else real(src, item, d)
    )
    today = "2026-10-04"
    pages = [_page(i, date=today, created="2026-10-04T08:00:00.000Z") for i in (1, 2)]
    refused_row = f"DATE#{today}#journal#journal#1"
    rows = [_stable_row(1, date=today), _legacy_row(1, 2, date=today)]

    table, _, _ = run(pages, rows)

    assert table.deleted == []
    assert len(_journal_sks(table, today)) == 2
    assert table.rows[refused_row]["raw_text"] == "stored"


# ── Defect 2: a re-keyed entry keeps its enrichment ───────────────────────────


def test_a_rekeyed_entry_carries_its_enrichment_from_the_legacy_key_to_the_stable_key(run):
    enrichment = {
        "enriched_mood": Decimal("4"),
        "enriched_themes": ["synthetic theme"],
        "enriched_at": "2026-08-11T14:35:00+00:00",
        "enriched_schema_version": Decimal("2"),
        "defense_enriched_at": "2026-08-11T14:36:00+00:00",
    }
    pages = [_page(1, edited="2026-10-04T08:00:00.000Z"), _page(2)]
    rows = [_legacy_row(1, 1, **enrichment), _legacy_row(2, 2, enriched_mood=Decimal("2"))]

    table, _, _ = run(pages, rows)

    stable = table.rows[nl.build_sk(OLD, "journal", _pid(1))]
    for key, val in enrichment.items():
        assert stable.get(key) == val, f"{key} did not follow the entry to its stable key"
    assert BODY in stable["raw_text"], "the fresh vendor text is what is stored"
    # The page's own legacy row is gone (one row per page); the sibling's row is untouched.
    assert table.deleted == [f"DATE#{OLD}#journal#journal#1"]
    assert table.rows[f"DATE#{OLD}#journal#journal#2"]["enriched_mood"] == Decimal("2")


def test_a_legacy_row_that_cannot_be_read_is_not_removed(run):
    """If the legacy row's enrichment could not be read it was not carried — so the row stays."""

    def _break_legacy_reads(table, notion):
        real = table.get_item

        def get_item(Key, **kw):
            if Key["sk"].endswith("#1"):
                raise RuntimeError("throttled")
            return real(Key, **kw)

        table.get_item = get_item

    pages = [_page(1, edited="2026-10-04T08:00:00.000Z")]
    table, _, _ = run(pages, [_legacy_row(1, 1, enriched_mood=Decimal("4"))], before=_break_legacy_reads)

    assert table.deleted == []
    assert table.rows[f"DATE#{OLD}#journal#journal#1"]["enriched_mood"] == Decimal("4")


# ── What the reconcile may still remove, and when it may not ──────────────────


def test_a_page_notion_no_longer_holds_is_removed_once_the_whole_date_view_confirms_it(run):
    """#476's intent survives: a sibling is edited, and the whole-date re-query shows page 3
    is gone from Notion. That row, and only that row, is removed."""
    pages = [_page(1, edited="2026-10-04T08:00:00.000Z"), _page(2)]
    rows = [_stable_row(1), _stable_row(2), _stable_row(3)]

    table, notion, log = run(pages, rows)

    assert table.deleted == [nl.build_sk(OLD, "journal", _pid(3))]
    assert notion.queries == 2, "one fetch, one whole-date re-query"
    assert (
        "vendor_absent_removed=1" in log.decisions()[0] and "rows_before=3" in log.decisions()[0] and "rows_after=2" in log.decisions()[0]
    )


def test_nothing_is_removed_when_the_whole_date_view_fails(run):
    pages = [_page(1, edited="2026-10-04T08:00:00.000Z")]
    rows = [_stable_row(1), _stable_row(3)]

    def _fail_requery(table, notion):
        notion.fail_after = 1

    table, _, log = run(pages, rows, before=_fail_requery)

    assert table.deleted == []
    assert "requery=failed:RuntimeError" in log.decisions()[0]


def test_nothing_is_removed_when_the_whole_date_view_omits_a_page_the_run_just_fetched(monkeypatch):
    """A re-query that does not even contain the page in hand is not a view of the date."""
    table = FakeTable([_stable_row(1), _stable_row(3)])
    monkeypatch.setattr(nl, "table", table)
    monkeypatch.setattr(nl, "logger", Log())
    sk1 = nl.build_sk(OLD, "journal", _pid(1))

    out = nl._reconcile_deleted(
        OLD, "journal", {sk1}, stored_rows=table.query(**_q())["Items"], fetched_page_ids={_pid(1)}, vendor_page_ids=lambda d: set()
    )

    assert table.deleted == [] and out["requery"] == "inconsistent"


def test_without_a_whole_date_view_nothing_unwritten_is_removed(monkeypatch):
    """write_entries called with no vendor lookup (any caller but the handler) cannot prove
    a page is gone, so it deletes nothing — and a row with no page id is never deleted."""
    orphan = {"pk": nl.PK, "sk": f"DATE#{OLD}#journal#journal#7", "date": OLD, "raw_text": "stored"}
    table = FakeTable([_stable_row(3), orphan])
    monkeypatch.setattr(nl, "table", table)
    monkeypatch.setattr(nl, "logger", Log())
    item = {"date": OLD, "source": "notion", "template": "journal", "notion_page_id": _pid(1), "raw_text": "fresh"}

    assert nl.write_entries({OLD: [("journal", item)]}) == 1
    assert table.deleted == [] and len(_journal_sks(table)) == 3

    nl.write_entries({OLD: [("journal", dict(item))]}, vendor_page_ids=lambda d: {_pid(1)})
    assert table.deleted == [nl.build_sk(OLD, "journal", _pid(3))], "the id-less row stays; only the vendor-absent page goes"


def _q():
    from boto3.dynamodb.conditions import Key

    return {
        "KeyConditionExpression": Key("pk").eq(nl.PK) & Key("sk").begins_with(f"DATE#{OLD}#journal#journal#"),
        "ProjectionExpression": "sk, notion_page_id",
    }


# ── The decision line: counts only ────────────────────────────────────────────


def test_the_reconcile_decision_line_carries_counts_and_no_key_page_id_or_text(run):
    n = 4
    pages = [_page(i) for i in range(1, n + 1)]
    pages[0]["last_edited_time"] = "2026-10-04T08:00:00.000Z"
    rows = [_legacy_row(i, i, enriched_mood=Decimal("3")) for i in range(1, n + 1)]

    table, _, log = run(pages, rows)

    decisions = log.decisions()
    assert len(decisions) == 1
    line = decisions[0]
    assert f"date={OLD}" in line and "template=journal" in line
    assert f"rows_before={n}" in line and f"rows_after={n}" in line, line
    assert "rekeyed_removed=1" in line and "vendor_absent_removed=0" in line and f"kept_unwritten={n - 1}" in line
    forbidden = (
        [BODY, "fixture", "stored", "DATE#", "#journal#"]
        + [_pid(i) for i in range(1, n + 1)]
        + [_pid(i).replace("-", "")[-12:] for i in range(1, n + 1)]
    )
    assert not [f for f in forbidden if f in line], "the decision line must carry counts only"
