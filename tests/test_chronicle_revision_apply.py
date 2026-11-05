"""tests/test_chronicle_revision_apply.py — the generic publication-revision applier (owner ruling 2026-11-05).

Every fixture here is synthetic: the real manifest names private text and lives outside the repo. The fakes
stand in for S3 / DynamoDB / CloudFront / HTTP with the same call shapes boto3 and urllib use, so the
script's own code paths run end to end without AWS.
"""

from __future__ import annotations

import copy
import io
import json
import os
import sys
from decimal import Decimal

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "scripts"))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

import chronicle_revision_apply as cra  # noqa: E402

PK = "USER#test#SOURCE#chronicle"
PREFIX = "backups/chronicle-revisions/2099-01-01/"


class FakeS3:
    def __init__(self, objects):
        self.objects = {k: dict(v) for k, v in objects.items()}
        self.puts = []

    def get_object(self, Bucket, Key):
        o = self.objects[Key]
        return {
            "Body": io.BytesIO(o["Body"]),
            "ContentType": o.get("ContentType"),
            "CacheControl": o.get("CacheControl"),
            "Metadata": o.get("Metadata", {}),
            **({"ContentEncoding": o["ContentEncoding"]} if o.get("ContentEncoding") else {}),
        }

    def put_object(self, **kw):
        self.puts.append(kw)
        self.objects[kw["Key"]] = {k: v for k, v in kw.items() if k not in ("Bucket", "Key")}


class ConditionFailed(Exception):
    pass


class FakeTable:
    """get_item + an update_item that evaluates the script's SET / AND-of-equalities shape."""

    def __init__(self, items):
        self.items = {(i["pk"], i["sk"]): copy.deepcopy(i) for i in items}
        self.updates = []

    def get_item(self, Key, ConsistentRead=False):
        it = self.items.get((Key["pk"], Key["sk"]))
        return {"Item": copy.deepcopy(it)} if it else {}

    def update_item(self, Key, UpdateExpression, ConditionExpression, ExpressionAttributeNames, ExpressionAttributeValues):
        self.updates.append(locals())
        it = self.items[(Key["pk"], Key["sk"])]
        names, vals = ExpressionAttributeNames, ExpressionAttributeValues
        for cond in ConditionExpression.split(" AND "):
            a, v = [x.strip() for x in cond.split("=")]
            if it.get(names[a]) != vals[v]:
                raise ConditionFailed(cond)
        for clause in UpdateExpression[len("SET ") :].split(", #"):
            clause = clause if clause.startswith("#") else "#" + clause
            a, expr = [x.strip() for x in clause.split("=", 1)]
            if expr.startswith("list_append"):
                it[names[a]] = list(it.get(names[a]) or []) + list(vals[":rev"])
            else:
                it[names[a]] = vals[expr]


class FakeCF:
    def __init__(self):
        self.calls = []

    def create_invalidation(self, **kw):
        self.calls.append(kw)
        return {"Invalidation": {"Id": "I-TEST"}}


def _manifest(**over):
    m = {
        "schema": cra.SCHEMA,
        "reason": "privacy revision (owner ruling 2026-11-05)",
        "bucket": "test-bucket",
        "region": "us-west-2",
        "table": "test-table",
        "distribution": "DIST",
        "backup_prefix": PREFIX,
        "passages": [
            {
                "id": "p1",
                "locations": [
                    {
                        "store": "s3",
                        "key": "generated/journal/posts/week-01/index.html",
                        "public_path": "/journal/posts/week-01/",
                        "find": "<p>SYNTH-ORIGINAL sentence.</p>",
                        "replace": "",
                        "count": 1,
                    },
                    {
                        "store": "ddb",
                        "pk": PK,
                        "sk": "DATE#2099-01-01",
                        "path": ["content_markdown"],
                        "op": "replace",
                        "find": " SYNTH-ORIGINAL sentence.",
                        "replace": "",
                        "count": 1,
                    },
                ],
            },
            {
                "id": "p2",
                "locations": [
                    {
                        "store": "s3",
                        "key": "site/rss.xml",
                        "public_path": "/rss.xml",
                        "find": "SYNTH-TITLE",
                        "replace": "Revised Title",
                        "count": 2,
                    },
                    {
                        "store": "ddb",
                        "pk": PK,
                        "sk": "RECAP#latest",
                        "path": ["threads_to_watch", 1],
                        "op": "remove_list_item",
                        "expect": "SYNTH-THREAD",
                    },
                    {
                        "store": "ddb",
                        "pk": PK,
                        "sk": "RECAP#latest",
                        "path": ["recent_beats", 0, "beat"],
                        "op": "replace",
                        "find": " SYNTH-BEAT",
                        "replace": "",
                        "count": 1,
                    },
                ],
            },
        ],
        "verify": [
            {"url": "https://example.test/journal/posts/week-01/", "phrases": ["SYNTH-ORIGINAL"], "pending_owner_decision": None},
            {
                "url": "https://example.test/story/week-01/",
                "phrases": ["SYNTH-AUDIO", "SYNTH-CHAPTER"],
                "held_phrases": ["SYNTH-AUDIO"],
                "pending_owner_decision": "audio-x",
            },
        ],
        "audio": [{"id": "audio-x", "recommendation": "HOLD"}],
        "regeneration": ["step one"],
    }
    m.update(over)
    return m


def _stores():
    s3 = FakeS3(
        {
            "generated/journal/posts/week-01/index.html": {
                "Body": "<h1>SYNTH-TITLE</h1>\n<p>Kept.</p>\n<p>SYNTH-ORIGINAL sentence.</p>\n".encode("utf-8"),
                "ContentType": "text/html; charset=utf-8",
                "CacheControl": "max-age=300",
                "Metadata": {"build": "x"},
            },
            "site/rss.xml": {
                "Body": "<title>SYNTH-TITLE</title><title>SYNTH-TITLE</title>".encode("utf-8"),
                "ContentType": "application/xml",
            },
        }
    )
    table = FakeTable(
        [
            {
                "pk": PK,
                "sk": "DATE#2099-01-01",
                "content_markdown": "Kept. SYNTH-ORIGINAL sentence.",
                "word_count": Decimal("2"),
                "status": "published",
            },
            {
                "pk": PK,
                "sk": "RECAP#latest",
                "threads_to_watch": ["kept", "SYNTH-THREAD"],
                "recent_beats": [{"beat": "A beat. SYNTH-BEAT", "week": "1"}],
            },
        ]
    )
    return s3, table


# ── validation ──────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("prefix", ["site/backups/", "generated/x/", "backups/no-slash", "/abs/"])
def test_a_public_or_malformed_backup_prefix_is_refused(prefix):
    with pytest.raises(cra.ManifestError):
        cra.validate(_manifest(backup_prefix=prefix))


def test_a_manifest_of_another_schema_or_editing_revisions_is_refused():
    with pytest.raises(cra.ManifestError):
        cra.validate(_manifest(schema="other"))
    m = _manifest()
    m["passages"][0]["locations"][1]["path"] = ["revisions"]
    with pytest.raises(cra.ManifestError):
        cra.validate(m)
    m = _manifest()
    m["passages"][0]["locations"][0]["find"] = ""
    with pytest.raises(cra.ManifestError):
        cra.validate(m)


# ── preflight refuses before any write ──────────────────────────────────────────────────


def test_a_target_that_no_longer_matches_refuses_the_whole_run_and_writes_nothing():
    s3, table = _stores()
    s3.objects["site/rss.xml"]["Body"] = b"<title>SYNTH-TITLE</title>"  # one occurrence, the manifest expects two
    with pytest.raises(cra.Mismatch):
        cra.apply(_manifest(), s3, table, FakeCF(), now="2099-01-01T00:00:00+00:00", log=lambda *_: None)
    assert s3.puts == [] and table.updates == []


def test_a_compressed_object_is_refused():
    s3, table = _stores()
    s3.objects["site/rss.xml"]["ContentEncoding"] = "gzip"
    with pytest.raises(cra.Mismatch):
        cra.preflight(_manifest(), s3, table)


def test_a_list_item_that_changed_is_refused():
    s3, table = _stores()
    table.items[(PK, "RECAP#latest")]["threads_to_watch"] = ["kept", "something else"]
    with pytest.raises(cra.Mismatch):
        cra.preflight(_manifest(), s3, table)


# ── apply ───────────────────────────────────────────────────────────────────────────────


def test_apply_backs_up_byte_for_byte_writes_the_revision_and_records_it():
    s3, table = _stores()
    originals = {k: v["Body"] for k, v in s3.objects.items()}
    cf = FakeCF()
    out = cra.apply(_manifest(), s3, table, cf, now="2099-01-01T12:00:00+00:00", log=lambda *_: None)

    # S3: originals byte-for-byte under the private prefix, revised bodies with their own headers
    for key, body in originals.items():
        assert s3.objects[PREFIX + "s3/" + key]["Body"] == body
    post = s3.objects["generated/journal/posts/week-01/index.html"]
    assert post["Body"] == "<h1>SYNTH-TITLE</h1>\n<p>Kept.</p>\n\n".encode("utf-8")
    assert post["ContentType"] == "text/html; charset=utf-8" and post["CacheControl"] == "max-age=300"
    assert post["Metadata"] == {"build": "x"}
    assert s3.objects["site/rss.xml"]["Body"] == b"<title>Revised Title</title><title>Revised Title</title>"

    # DynamoDB: only the changed attributes, conditional on their originals, plus the revision record
    row = table.items[(PK, "DATE#2099-01-01")]
    assert row["content_markdown"] == "Kept."
    assert row["word_count"] == Decimal("2") and row["status"] == "published"
    (rev,) = row["revisions"]
    assert rev["reason"] == "privacy revision (owner ruling 2026-11-05)"
    assert rev["at"] == "2099-01-01T12:00:00+00:00" and rev["fields"] == ["content_markdown"]
    assert rev["backup_ref"] == f"s3://test-bucket/{PREFIX}ddb/USER_test_SOURCE_chronicle/DATE_2099-01-01.json"
    recap = table.items[(PK, "RECAP#latest")]
    assert recap["threads_to_watch"] == ["kept"] and recap["recent_beats"] == [{"beat": "A beat.", "week": "1"}]
    assert sorted(recap["revisions"][0]["fields"]) == ["recent_beats", "threads_to_watch"]

    # the DynamoDB backup is the whole original item, lossless
    backup = json.loads(s3.objects[PREFIX + "ddb/USER_test_SOURCE_chronicle/DATE_2099-01-01.json"]["Body"])
    assert backup["Item"]["content_markdown"] == {"S": "Kept. SYNTH-ORIGINAL sentence."}
    assert backup["Item"]["word_count"] == {"N": "2"}

    # the revision log carries hashes and counts, never text
    log_key = next(k for k in s3.objects if k.startswith(PREFIX + "revision_log/"))
    log = s3.objects[log_key]["Body"].decode("utf-8")
    assert "SYNTH" not in log and log_key.endswith("20990101T120000Z.json")
    assert {r["key"] for r in out["s3"]} == set(originals)

    # CloudFront: every public path touched, the directory form and its index
    (inv,) = cf.calls
    assert inv["InvalidationBatch"]["Paths"]["Items"] == ["/journal/posts/week-01/", "/journal/posts/week-01/index.html", "/rss.xml"]


def test_a_second_apply_refuses_because_the_originals_are_gone():
    s3, table = _stores()
    cra.apply(_manifest(), s3, table, None, invalidate=False, now="2099-01-01T12:00:00+00:00", log=lambda *_: None)
    with pytest.raises(cra.Mismatch):
        cra.apply(_manifest(), s3, table, None, invalidate=False, now="2099-01-02T12:00:00+00:00", log=lambda *_: None)


def test_a_row_that_changes_between_preflight_and_write_stops_with_a_partial_log():
    s3, table = _stores()
    real = table.update_item

    def racing(**kw):
        table.items[(PK, "DATE#2099-01-01")]["content_markdown"] = "edited by someone else"
        return real(**kw)

    table.update_item = racing
    with pytest.raises(cra.Mismatch):
        cra.apply(_manifest(), s3, table, None, invalidate=False, now="2099-01-01T12:00:00+00:00", log=lambda *_: None)
    assert any(k.endswith(".partial.json") for k in s3.objects)


# ── verify ──────────────────────────────────────────────────────────────────────────────


def _fetch(pages):
    return lambda url: pages[url]


def test_verify_passes_when_no_original_phrase_is_served_and_holds_pending_pages():
    pages = {"https://example.test/journal/posts/week-01/": "<p>Kept.</p>", "https://example.test/story/week-01/": "SYNTH-AUDIO"}
    assert cra.verify(_manifest(), _fetch(pages), log=lambda *_: None) == 0
    assert cra.verify(_manifest(), _fetch(pages), strict=True, log=lambda *_: None) == 1


def test_a_pending_page_still_fails_on_a_phrase_its_audio_does_not_speak():
    """HELD covers only the phrases the undecided audio speaks; a chapter phrase left behind is a failed revision."""
    pages = {
        "https://example.test/journal/posts/week-01/": "<p>Kept.</p>",
        "https://example.test/story/week-01/": "SYNTH-AUDIO SYNTH-CHAPTER",
    }
    assert cra.verify(_manifest(), _fetch(pages), log=lambda *_: None) == 1


@pytest.mark.parametrize(
    "served",
    [
        "<p>SYNTH-ORIGINAL sentence.</p>",  # as written
        '{"excerpt": "x \\u2014 SYNTH-ORIGINAL"}',  # JSON-escaped neighbourhood
        "<p>SYNTH&#45;ORIGINAL</p>",  # an entity inside the phrase
        "<p>SYNTH-<em>ORIGINAL</em></p>",  # markup inside the phrase
        "<p>synth-original, lower-cased</p>",  # case does not hide it
    ],
)
def test_verify_fails_when_an_original_phrase_is_still_served_in_any_form(served):
    pages = {"https://example.test/journal/posts/week-01/": served, "https://example.test/story/week-01/": ""}
    assert cra.verify(_manifest(), _fetch(pages), log=lambda *_: None) == 1


def test_verify_counts_a_fetch_failure_as_a_failure():
    def boom(url):
        raise OSError("down")

    assert cra.verify(_manifest(), boom, log=lambda *_: None) == 1


# ── CLI ─────────────────────────────────────────────────────────────────────────────────


def test_the_cli_dry_runs_offline_and_rejects_a_bad_manifest(tmp_path, capsys):
    good = tmp_path / "m.json"
    good.write_text(json.dumps(_manifest()))
    assert cra.main(["--manifest", str(good), "--offline"]) == 0
    out = capsys.readouterr().out
    assert "plan: 2 passage(s), 2 S3 object(s), 2 DynamoDB item(s)" in out and "nothing read, nothing written" in out
    assert "SYNTH" not in out  # the plan names objects and passage ids, never their text
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(_manifest(backup_prefix="site/x/")))
    assert cra.main(["--manifest", str(bad), "--offline"]) == 2


# ── the revision record is never served ─────────────────────────────────────────────────

# The readers of chronicle rows that feed a public surface (routes, publishers, the snapshot, the recall
# index). Named explicitly: a new reader of the chronicle partition should be added here when it lands.
CHRONICLE_ROW_READERS = (
    "lambdas/web/site_api_chapters.py",
    "lambdas/web/site_api_coach_narrative.py",
    "lambdas/web/site_api_lambda.py",
    "lambdas/web/ask_retrieval.py",
    "lambdas/web/og_moments.py",
    "lambdas/web/card_engine.py",
    "lambdas/emails/chronicle_render.py",
    "lambdas/emails/chronicle_approve_lambda.py",
    "lambdas/emails/chronicle_store.py",
    "lambdas/content/chronicle_share_kit.py",
    "lambdas/content/site_writer.py",
    "lambdas/ai/recall_indexer.py",
    "lambdas/ai/semantic_recall.py",  # the recall rows' reader (a revised snippet row gets the record too)
    "deploy/restart_leadin_pages.py",
    "scripts/publish_snapshot.py",
)


def test_no_public_reader_of_chronicle_rows_reads_the_revisions_field():
    for rel in CHRONICLE_ROW_READERS:
        src = open(os.path.join(_REPO, rel), encoding="utf-8").read()
        assert '"revisions"' not in src and "'revisions'" not in src and ".revisions" not in src, rel


def test_the_chapters_route_projects_named_fields_only():
    from web import site_api_chapters

    assert cra.REVISIONS_ATTR not in site_api_chapters.ROW_PROJECTION


def test_the_recap_route_does_not_serialise_the_revision_record(monkeypatch):
    from web import site_api_coach_narrative as nar

    item = {
        "pk": "USER#matthew#SOURCE#chronicle",
        "sk": "RECAP#latest",
        "story_so_far": "s",
        "recent_beats": [],
        "threads_to_watch": [],
        "as_of": "2026-10-13",
        "revisions": [{"at": "x", "reason": "privacy revision", "backup_ref": "s3://b/backups/k", "fields": ["threads_to_watch"]}],
    }

    class T:
        def get_item(self, Key, **_):
            return {"Item": dict(item)}

    g = {"table": T(), "_current_day_n": lambda: 99, "_regeneration_paused": lambda _f: False}
    resp = nar.handle_recap(_g=g)
    body = resp["body"] if isinstance(resp, dict) else str(resp)
    assert "revisions" not in str(body) and "backup_ref" not in str(body) and "backups/" not in str(body)
    assert "story_so_far" in str(body)


def test_the_apply_script_carries_no_chronicle_text():
    """The script is generic: every string it writes comes from the manifest. A long prose literal here would
    mean private text leaked into the public repo."""
    import ast

    tree = ast.parse(open(os.path.join(_REPO, "scripts", "chronicle_revision_apply.py"), encoding="utf-8").read())
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                docstrings.add(id(first.value))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
            assert len(node.value) < 160, node.value[:60]
