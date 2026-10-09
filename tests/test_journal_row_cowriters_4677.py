"""tests/test_journal_row_cowriters_4677.py — the guard over the SET of journal-row writers (#4677).

`lambdas/ingestion/journal_row_contract.py` declares every pipeline that merges attributes
onto a Notion journal row after ingestion, and the ingester carries exactly the declared
families across each rewrite. That is only as good as the declaration, so this file holds it
from four sides:

  1. the SET — every module that names the journal partition and issues a DynamoDB write is
     either a declared co-writer or listed below with the reason it does not write a
     journal row. A new writer cannot join the partition without a decision being made;
  2. the DERIVATION — each declared co-writer's real update expression is driven, and every
     attribute it writes must fall inside the families declared for it;
  3. the CARRY IS DERIVED — a family added to the declaration is carried by the ingester
     with no edit to the ingester (so it holds no list of its own);
  4. ONE DOOR — the ingester puts a journal row in exactly one function, which carries first.

Known limit of (1), stated rather than hidden: the sweep sees a module that NAMES the
partition. A writer handed a journal row's key by another module, never naming the
partition itself, is not seen here — which is why (2) drives the real writers.
"""

import ast
import importlib.util
import os
import re
import sys
from pathlib import Path

os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO / "lambdas") not in sys.path:
    sys.path.insert(0, str(_REPO / "lambdas"))

import ingestion.journal_row_contract as jrc  # noqa: E402
import ingestion.notion_lambda as nl  # noqa: E402

INGESTER = "lambdas/ingestion/notion_lambda.py"
SWEPT_ROOTS = ("lambdas", "mcp", "scripts", "deploy")

# A module "names the journal partition" when it spells the partition key, by literal or
# through one of the two prefix idioms the codebase uses.
_NAMES_PARTITION = re.compile(r"SOURCE#notion|PREFIX\s*\+\s*[\"']notion[\"']|PREFIX\}notion")
_ISSUES_WRITE = re.compile(r"\.(?:update_item|put_item|delete_item|batch_writer|batch_write_item|transact_write_items)\(")

# Modules that name the journal partition AND issue a write, but whose writes land somewhere
# else. Each reason says WHERE; it is the thing to re-check when the module changes.
NOT_A_JOURNAL_ROW_WRITER = {
    "lambdas/ai/conversation_enrichment.py": "reads journal text as a dedup corpus; its update_item targets check-in, habit-reflection and field-note rows",
    "lambdas/coach/coach_narrative_orchestrator.py": "reads journal signal; puts COACH#<id> brief rows",
    "lambdas/compute/adaptive_mode_lambda.py": "reads journal rows; puts adaptive_mode and engagement_state rows",
    "lambdas/compute/character_sheet_lambda.py": "reads journal rows; puts character_sheet rows and stamps challenges rows",
    "lambdas/compute/circadian_compliance_lambda.py": "reads journal rows; puts circadian rows",
    "lambdas/compute/daily_insight_compute_lambda.py": "reads journal rows; puts computed_insights and platform_memory rows",
    "lambdas/compute/daily_metrics_compute_lambda.py": "reads journal rows; puts computed_metrics, day_grade, habit_scores and ledger rows",
    "lambdas/emails/daily_brief_lambda.py": "reads journal rows; puts day_grade/habit_scores rows and updates computed_insights",
    "lambdas/emails/freshness_checker_lambda.py": "puts its own alert-state sentinel under the partition (a non-DATE# sort key), never a journal row",
    "lambdas/intelligence/field_notes_lambda.py": "reads journal rows; puts field_notes rows",
    "lambdas/intelligence/intelligence_common.py": "reads journal rows; its writes are action and insight ledger rows",
    "lambdas/intelligence/journal_analyzer_lambda.py": "reads journal rows; puts journal_analysis rows",
    "mcp/tools_journal.py": "reads journal rows; its writes target journal_quotes and diary_claims rows",
    "scripts/sync_diary_publications.py": "reads journal keys; puts publication rows it wholly owns",
    "deploy/backfill_recall_embeddings.py": "reads journal rows; puts recall-embedding rows",
    "deploy/restart_intelligence_wipe.py": "names the partition only to say it is kept; tombstones derived partitions",
}


def _swept_writers():
    found = set()
    for root in SWEPT_ROOTS:
        for path in (_REPO / root).rglob("*.py"):
            rel = path.relative_to(_REPO).as_posix()
            if "/archive/" in rel:
                continue
            text = path.read_text(encoding="utf-8")
            if _NAMES_PARTITION.search(text) and _ISSUES_WRITE.search(text):
                found.add(rel)
    return found


def test_every_module_that_writes_beside_the_journal_partition_is_declared_or_explained():
    swept = _swept_writers()
    declared = {w.module for w in jrc.JOURNAL_ROW_COWRITERS if w.module}
    accounted = declared | set(NOT_A_JOURNAL_ROW_WRITER) | {INGESTER}

    problems = []
    for module in sorted(swept - accounted):
        problems.append(
            f"{module} names the journal partition and issues a DynamoDB write, but is neither a declared co-writer "
            "(ingestion/journal_row_contract.py JOURNAL_ROW_COWRITERS — declare the attribute families it owns, or the "
            "next edit of a page in Notion erases them) nor explained in NOT_A_JOURNAL_ROW_WRITER"
        )
    for module in sorted(declared - swept):
        problems.append(f"{module} is a declared co-writer but no longer names the partition and issues a write — fix the declaration")
    for module in sorted(set(NOT_A_JOURNAL_ROW_WRITER) - swept):
        problems.append(f"{module} is explained in NOT_A_JOURNAL_ROW_WRITER but no longer matches the sweep — remove the stale entry")
    for module in sorted(declared & set(NOT_A_JOURNAL_ROW_WRITER)):
        problems.append(f"{module} is both a declared co-writer and explained away — it cannot be both")
    assert INGESTER in swept, "the sweep no longer finds the ingester itself — its detection has gone blind"
    assert not problems, "\n".join(problems)


def _enrichment_attributes_written():
    """Drive the real enricher write with every extraction field populated; return the
    attribute names in the update expression it issued."""
    import ingestion.journal_enrichment_lambda as jel

    captured = {}

    class Capture:
        def update_item(self, **kw):
            captured.update(kw)

    quote = "a synthetic sentence that states a cause"
    by_type = {"N": 3, "S": "synthetic", "BOOL": True, "L": ["synthetic"]}
    enrichment = {key: by_type[dtype] for key, (_attr, dtype) in jel.FIELD_MAPPING.items()}
    enrichment["causal_hints"] = [{"cause": "synthetic", "effect": "synthetic", "quote": quote}]
    real = jel.table
    jel.table = Capture()
    try:
        assert jel.apply_enrichment({"pk": nl.PK, "sk": "DATE#2026-09-20#journal#morning", "raw_text": quote}, enrichment)
    finally:
        jel.table = real
    written = set(captured["ExpressionAttributeNames"].values())
    # Every mapped attribute, whether or not this one drive happened to emit it.
    return written | {attr for attr, _dtype in jel.FIELD_MAPPING.values()}


def _vocal_attributes_written():
    """Drive the real backfill expression builder on metrics the real parser produced."""
    from health import vocal_metrics

    spec = importlib.util.spec_from_file_location("backfill_vocal_metrics_4677", _REPO / "scripts" / "backfill_vocal_metrics.py")
    bvm = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bvm)
    srt = "1\n00:00:00,000 --> 00:00:04,000\num one two three four\n\n2\n00:00:09,000 --> 00:00:13,000\nfive six seven eight\n"
    metrics = vocal_metrics.parse_srt(srt)
    assert metrics and metrics.get("mean_pause_s") is not None, "the synthetic SRT must produce every metric, pause included"
    kwargs = bvm.build_update_kwargs(nl.PK, "DATE#2026-09-20#journal#video_diary#0000000000aa", metrics, "2026-09-21T03:00:00+00:00")
    return set(kwargs["ExpressionAttributeNames"].values()) - {"pk"}


_DRIVERS = {
    "lambdas/ingestion/journal_enrichment_lambda.py": _enrichment_attributes_written,
    "scripts/backfill_vocal_metrics.py": _vocal_attributes_written,
}


def test_each_declared_cowriter_writes_only_inside_the_families_declared_for_it():
    problems = []
    for writer in jrc.JOURNAL_ROW_COWRITERS:
        if writer.module is None:
            continue
        driver = _DRIVERS.get(writer.module)
        if driver is None:
            problems.append(f"{writer.name}: declared with no driver in _DRIVERS — add one that exercises its real write")
            continue
        written = driver()
        if not written:
            problems.append(f"{writer.name}: the driver captured no attributes")
        outside = sorted(a for a in written if not a.startswith(writer.families))
        if outside:
            problems.append(
                f"{writer.name} writes {outside} outside its declared families {writer.families} — a re-ingest would erase them"
            )
        unused = sorted(f for f in writer.families if not any(a.startswith(f) for a in written))
        if unused:
            problems.append(f"{writer.name} declares families it never writes: {unused}")
    assert not problems, "\n".join(problems)


def test_the_vocal_backfill_writes_all_seven_named_attributes():
    """The seven names in docs/SCHEMA.md — if the backfill grows an eighth outside `vocal_`,
    the test above reds; if it renames one, this does."""
    assert _vocal_attributes_written() == {
        "vocal_wpm",
        "vocal_mean_pause_s",
        "vocal_pauses_per_min",
        "vocal_fillers_per_min",
        "vocal_duration_s",
        "vocal_word_count",
        "vocal_metrics_computed_at",
    }


def test_a_newly_declared_family_is_carried_with_no_change_to_the_ingester(monkeypatch):
    """The carried set is the declaration. Declare a new co-writer and the ingester carries
    its attributes on both write paths — it holds no list of its own to forget."""

    class Table:
        def __init__(self):
            self.rows = {}

        def query(self, **kw):
            return {"Items": [{"sk": sk, "notion_page_id": r.get("notion_page_id")} for sk, r in self.rows.items()]}

        def get_item(self, Key, **kw):
            row = self.rows.get(Key["sk"])
            return {"Item": dict(row)} if row else {}

        def put_item(self, Item):
            self.rows[Item["sk"]] = dict(Item)

        def delete_item(self, Key):
            self.rows.pop(Key["sk"], None)

    newcomer = jrc.CoWriter(name="synthetic", module=None, families=("zz4677_",), recomputed_by="nothing")
    monkeypatch.setattr(jrc, "JOURNAL_ROW_COWRITERS", jrc.JOURNAL_ROW_COWRITERS + (newcomer,))
    day, page = "2026-09-20", "00000000-0000-4000-8000-0000000000bb"
    for template in ("Video Diary", "Morning"):
        table = Table()
        monkeypatch.setattr(nl, "table", table)
        sk = nl.build_sk(day, template, page)
        table.rows[sk] = {"pk": nl.PK, "sk": sk, "notion_page_id": page, "zz4677_score": 7, "undeclared_attr": 1}
        nl.write_entries({day: [(template, {"date": day, "source": "notion", "notion_page_id": page, "raw_text": "synthetic"})]})
        assert table.rows[sk].get("zz4677_score") == 7, f"{template}: a declared family was not carried"
        assert "undeclared_attr" not in table.rows[sk], f"{template}: an undeclared attribute was carried"


def test_the_ingester_puts_a_journal_row_through_one_door_that_carries_first():
    tree = ast.parse((_REPO / INGESTER).read_text(encoding="utf-8"))
    puts = {}
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.FunctionDef):
            continue
        calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call)]
        names = [(c.func.attr if isinstance(c.func, ast.Attribute) else getattr(c.func, "id", ""), c.lineno) for c in calls]
        if any(name == "put_item" for name, _ in names):
            puts[fn.name] = sorted(names, key=lambda pair: pair[1])
    assert set(puts) == {
        "_store_row"
    }, f"put_item is called in {sorted(puts)}; a journal row must be put only in _store_row, which carries the co-writers' attributes first"
    order = [name for name, _line in puts["_store_row"]]
    assert "preserve_enrichment" in order and "_carry_from_rekeyed" in order, "_store_row no longer carries before it writes"
    assert max(order.index("preserve_enrichment"), order.index("_carry_from_rekeyed")) < order.index(
        "put_item"
    ), "_store_row puts the row before it has carried the co-writers' attributes"
    # No private list: the ingester's carry must come from the contract.
    source = (_REPO / INGESTER).read_text(encoding="utf-8")
    assert "carry_coowned" in source and "_CARRIED_PREFIXES" not in source
