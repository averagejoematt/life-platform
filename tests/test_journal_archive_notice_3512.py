"""tests/test_journal_archive_notice_3512.py — #3512: prior-cycle journal permalinks
carry an archive notice, and the checker that must go green says so.

THE DEFECT this file pins
-------------------------
On Day 0 of cycle 16, `/journal/posts/week-03/` served cycle 15's "The Plan, On the
Record" — "326.24 lbs at the start" — at HTTP 200 with no editor's note, while the
experiment ran on 324.64. week-04 and week-05 were the same. `qa-smoke-failures` sat
in ALARM on exactly one check, `reader_truth:frozen_artifacts`.

WHY THE ORACLE IS THE PRODUCTION CHECKER, NOT A LOCAL RULE
----------------------------------------------------------
The acceptance for this fix is not "the page looks right". It is
`lambdas/operational/weight_truth_qa.py::assess_frozen_artifact_weights` returning
no findings for the annotated page, through the SAME transformation the nightly
applies (`reader_truth_qa.html_to_text` over the fetched HTML). So these tests run
the real checker over the real injected banner. A local re-implementation of "does it
contain an editor's note" would pass while the live check still red — the #3200 class.

THE NEGATIVE CONTROL
--------------------
`test_stripping_the_notice_reds_the_checker` takes the exact HTML the mechanism
produces, removes ONLY the banner, and asserts the checker FAILS. Without it, a
fixture whose prose happened to cite no start weight would sail through both
directions and prove nothing (`reference_a_vacuous_negative_control`).
"""

from __future__ import annotations

import os
import sys

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (_REPO, os.path.join(_REPO, "deploy"), os.path.join(_REPO, "lambdas")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import journal_archive_notice as jan  # noqa: E402
from operational import reader_truth_qa, weight_truth_qa  # noqa: E402

# The shape of the live cycle-15 article, reduced to what matters: the article shell
# the injector anchors on, and the superseded start-weight claim in two of the exact
# forms the live page uses (the stats line and "on the morning of Day 1").
SUPERSEDED = 326.24
BASELINE = 324.64
GENESIS = "2026-09-05"
CYCLE = 16

ARTICLE_HTML = """<!DOCTYPE html>
<html lang="en"><head><title>The Plan, On the Record</title>
<style>.post-header { padding:1rem; }</style></head>
<body class="dx-page">
<main id="post">
<div class="post-wrap">
  <div class="post-header">
    <h1 class="post-header__title">&ldquo;The Plan, On the Record&rdquo;</h1>
    <div class="post-header__stats">326.24 lbs at the start &middot; 185 lbs the target</div>
  </div>
  <article class="post-body"><div class="prose">
    <p><strong>The destination.</strong> 326.24 pounds on the morning of Day 1. 185 pounds twelve months later.</p>
  </div></article>
</div>
</main>
</body></html>
"""

TOMBSTONE_JSON = '{"tombstone": true, "tombstoned_at": "2026-07-11T04:50:48Z", "archived_to": "x"}'


def _surfaces(html):
    """The qa-smoke shape, built the way the nightly builds it: fetched HTML run
    through the SAME html_to_text the reader-truth fetch uses."""
    return [{"name": "Prologue III", "path": "/journal/posts/week-03/", "prose": reader_truth_qa.html_to_text(html)}]


def _notice():
    return jan.build_archive_notice(CYCLE, GENESIS, BASELINE)


def _annotated():
    html, outcome = jan.inject_archive_notice(ARTICLE_HTML, _notice())
    assert outcome == "injected"
    return html


# ── 1. The oracle: positive AND negative control over the real checker ───────────


def test_the_unannotated_article_reds_the_live_checker():
    """Positive control for the DEFECT — this is the live 2026-09-03 alarm, offline."""
    findings = weight_truth_qa.assess_frozen_artifact_weights(_surfaces(ARTICLE_HTML), BASELINE)
    assert len(findings) == 1, findings
    assert findings[0]["category"] == "superseded_weight_unannotated"
    assert "326.24" in findings[0]["detail"]


def test_the_annotated_article_clears_the_live_checker():
    assert weight_truth_qa.assess_frozen_artifact_weights(_surfaces(_annotated()), BASELINE) == []


def test_stripping_the_notice_reds_the_checker():
    """THE NEGATIVE CONTROL. Same bytes, banner removed — the check must fail. If it
    did not, the green above would be a property of the fixture, not of the fix."""
    stripped = jan.strip_archive_notice(_annotated())
    assert not jan.has_archive_notice(stripped)
    findings = weight_truth_qa.assess_frozen_artifact_weights(_surfaces(stripped), BASELINE)
    assert len(findings) == 1, "stripping the archive notice must red the frozen-artifact check"


def test_the_notice_survives_html_to_text_as_one_marker():
    """html_to_text joins separate text nodes with newlines, so a marker split across
    tags would be invisible to `is_annotated`. Assert the whole marker sits in one
    node, and that the checker's OWN predicate — not a local copy — sees it."""
    prose = reader_truth_qa.html_to_text(_annotated())
    assert weight_truth_qa.is_annotated(prose)
    assert any("editor's note" in line.lower() for line in prose.splitlines())


def test_the_notice_names_the_governing_figures():
    """A marker that satisfies a regex without reconciling anything would be the
    #1924 class. The banner must name the baseline, the genesis and the attempt."""
    prose = reader_truth_qa.html_to_text(_annotated())
    assert str(BASELINE) in prose
    assert "September 5, 2026" in prose
    assert f"attempt {CYCLE}" in prose


def test_the_original_prose_is_untouched():
    """A frozen artifact is never rewritten (ADR-104). The historical figure stays."""
    annotated = _annotated()
    assert "326.24 lbs at the start" in annotated
    assert "326.24 pounds on the morning of Day 1" in annotated
    assert jan.strip_archive_notice(annotated) == ARTICLE_HTML


# ── 2. Injection mechanics ───────────────────────────────────────────────────────


def test_the_notice_lands_above_the_headline():
    annotated = _annotated()
    assert annotated.index(jan.NOTICE_ATTR) < annotated.index('<div class="post-header"')


def test_injection_is_idempotent_for_the_same_stamp():
    once = _annotated()
    twice, outcome = jan.inject_archive_notice(once, _notice())
    assert outcome == "current"
    assert twice == once
    assert once.count(jan.NOTICE_ATTR) == 1


def test_a_stale_notice_is_REPLACED_not_skipped():
    """The trap a plain has-notice/skip would fall into: the NEXT reset moves the
    baseline again, the old banner keeps quoting the previous one, and `is_annotated`
    stays True — a silently wrong page behind a green check. The stamp forces the
    replacement."""
    old = jan.inject_archive_notice(ARTICLE_HTML, jan.build_archive_notice(15, "2026-09-01", 326.24))[0]
    assert "326.24 lbs. Read what" in old  # the old banner asserted the OLD baseline
    new, outcome = jan.inject_archive_notice(old, _notice())
    assert outcome == "replaced"
    assert new.count(jan.NOTICE_ATTR) == 1
    assert "now runs on a starting weight of 324.64 lbs" in new
    assert "now runs on a starting weight of 326.24 lbs" not in new
    # and the replacement still clears the checker against the NEW baseline
    assert weight_truth_qa.assess_frozen_artifact_weights(_surfaces(new), BASELINE) == []


def test_body_only_shell_still_gets_a_notice():
    html, outcome = jan.inject_archive_notice("<html><body><p>326.24 lbs at the start</p></body></html>", _notice())
    assert outcome == "injected" and jan.has_archive_notice(html)


def test_a_shell_with_no_anchor_is_left_alone():
    html, outcome = jan.inject_archive_notice("no anchors here", _notice())
    assert outcome == "no-anchor" and html == "no anchors here"


def test_raw_json_tombstones_are_not_article_html():
    """week-00/week-06/week-minus-1 still serve the 2026-07-10 raw-JSON tombstone at
    200. They carry no prose to annotate — the sweep must report and skip them, not
    inject a banner into a JSON body."""
    assert jan.is_article_html(ARTICLE_HTML)
    assert not jan.is_article_html(TOMBSTONE_JSON)
    assert not jan.is_article_html("")


# ── 3. Orphan selection + the dest-key collision fix ─────────────────────────────


def test_slugs_in_manifest_reads_the_live_shape():
    manifest = {
        "posts": [
            {"url": "/journal/posts/week-02/", "title": "The Night Before Everything"},
            {"url": "/journal/posts/week-01/", "title": "Before the Numbers"},
            {"title": "malformed, no url"},
        ]
    }
    assert jan.slugs_in_manifest(manifest) == {"week-01", "week-02"}
    assert jan.slugs_in_manifest(None) == set()
    assert jan.slugs_in_manifest({}) == set()


@pytest.mark.parametrize(
    "key,slug",
    [
        ("generated/journal/posts/week-03/index.html", "week-03"),
        ("generated/journal/posts/week-minus-1/index.html", "week-minus-1"),
        ("generated/journal/posts/week-100/index.html", "week-100"),
    ],
)
def test_week_key_re_matches_every_slug_shape_the_journal_has_written(key, slug):
    assert jan.WEEK_KEY_RE.match(key).group(1) == slug


def test_the_manifest_and_the_template_are_never_swept():
    for key in ("generated/journal/posts.json", "generated/journal/posts/TEMPLATE.html"):
        assert jan.WEEK_KEY_RE.match(key) is None


def test_the_archive_prefix_carries_the_cycle():
    """THE ROOT CAUSE. `generated/journal/archive/pilot/posts/` had no cycle segment,
    so `week-03` collided with the 2026-07-10 cycle-4 archival on every reset since —
    `archive_one` returned "already archived" and did nothing. The prefix must differ
    per cycle, and must NEVER fall back onto the constant one."""
    assert jan.archive_prefix_for(16, GENESIS) == "generated/journal/archive/cycle-16/posts/"
    assert jan.archive_prefix_for(15, "2026-09-01") == "generated/journal/archive/cycle-15/posts/"
    assert jan.archive_prefix_for(16, GENESIS) != jan.archive_prefix_for(15, "2026-09-01")
    # no cycle (SSM unreadable) still keys uniquely — never on archive/pilot/posts/
    fallback = jan.archive_prefix_for(None, GENESIS)
    assert fallback == "generated/journal/archive/genesis-2026-09-05/posts/"
    assert "pilot" not in fallback


# ── 4. The sweep over a fake S3 ──────────────────────────────────────────────────

from botocore.exceptions import ClientError  # noqa: E402

FRESH_HTML = ARTICLE_HTML.replace("326.24", "324.64")

MANIFEST = '{"posts": [{"url": "/journal/posts/week-01/"}, {"url": "/journal/posts/week-02/"}]}'


class _Body:
    def __init__(self, data):
        self._data = data if isinstance(data, bytes) else data.encode("utf-8")

    def read(self, n=None):
        return self._data if n is None else self._data[:n]


class _Pager:
    def __init__(self, objects):
        self._objects = objects

    def paginate(self, Bucket=None, Prefix=""):
        return [{"Contents": [{"Key": k} for k in sorted(self._objects) if k.startswith(Prefix)]}]


class FakeS3:
    """Only the five calls the sweep makes. head_object raises a real ClientError so
    the 404 branch is exercised rather than stubbed around."""

    def __init__(self, objects):
        self.objects = dict(objects)
        self.puts = {}
        self.copies = []

    def get_paginator(self, op):
        return _Pager(self.objects)

    def get_object(self, Bucket, Key):
        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        return {"Body": _Body(self.objects[Key])}

    def head_object(self, Bucket, Key):
        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "404"}}, "HeadObject")
        return {"ContentLength": len(self.objects[Key])}

    def put_object(self, Bucket, Key, Body, **kw):
        self.puts[Key] = Body.decode("utf-8") if isinstance(Body, bytes) else Body
        self.objects[Key] = self.puts[Key]
        return {}

    def copy_object(self, **kw):
        self.copies.append(kw)
        self.objects[kw["Key"]] = self.objects.get(kw["CopySource"]["Key"], "")
        return {}


def _bucket():
    return {
        "generated/journal/posts.json": MANIFEST,
        "generated/journal/posts/TEMPLATE.html": "<html><body>template</body></html>",
        "generated/journal/posts/week-01/index.html": FRESH_HTML,
        "generated/journal/posts/week-03/index.html": ARTICLE_HTML,
        "generated/journal/posts/week-06/index.html": TOMBSTONE_JSON,
    }


def test_sweep_annotates_only_the_orphans_when_reading_the_manifest():
    s3 = FakeS3(_bucket())
    stats = jan.sweep_journal_permalinks(
        s3, cycle=CYCLE, genesis=GENESIS, baseline_lbs=BASELINE, apply=True, now_iso="NOW", log=lambda *a: None
    )
    assert stats["kept_live"] == 1  # week-01 is published by the manifest
    assert stats["not_html"] == 1  # week-06 is the raw-JSON tombstone
    assert stats["annotated"] == 1 and stats["archived"] == 1
    assert stats["touched_paths"] == ["/journal/posts/week-03/"]
    # the live page now carries the notice and keeps its original figure
    live = s3.objects["generated/journal/posts/week-03/index.html"]
    assert jan.has_archive_notice(live) and "326.24 lbs at the start" in live
    # the pristine copy landed under the CYCLE-keyed prefix, notice stripped
    pristine = s3.objects["generated/journal/archive/cycle-16/posts/week-03/index.html"]
    assert pristine == ARTICLE_HTML and not jan.has_archive_notice(pristine)
    # untouched: the manifest-published page and the raw tombstone
    assert s3.objects["generated/journal/posts/week-01/index.html"] == FRESH_HTML
    assert s3.objects["generated/journal/posts/week-06/index.html"] == TOMBSTONE_JSON
    # and the live surface now clears the production checker
    assert weight_truth_qa.assess_frozen_artifact_weights(_surfaces(live), BASELINE) == []


def test_sweep_writes_nothing_on_dry_run():
    s3 = FakeS3(_bucket())
    stats = jan.sweep_journal_permalinks(
        s3, cycle=CYCLE, genesis=GENESIS, baseline_lbs=BASELINE, apply=False, now_iso="NOW", log=lambda *a: None
    )
    assert stats["annotated"] == 1 and s3.puts == {} and s3.copies == []


def test_sweep_is_idempotent_across_reruns():
    s3 = FakeS3(_bucket())
    kw = dict(cycle=CYCLE, genesis=GENESIS, baseline_lbs=BASELINE, apply=True, now_iso="NOW", log=lambda *a: None)
    jan.sweep_journal_permalinks(s3, **kw)
    second = jan.sweep_journal_permalinks(s3, **kw)
    assert second["annotated"] == 0 and second["already_current"] == 1 and second["archived"] == 0


def test_sweep_with_empty_keep_slugs_annotates_every_live_page():
    """The reset's mode — every live week page belongs to the closing cycle."""
    s3 = FakeS3(_bucket())
    stats = jan.sweep_journal_permalinks(
        s3, cycle=CYCLE, genesis=GENESIS, baseline_lbs=BASELINE, keep_slugs=frozenset(), apply=True, now_iso="NOW", log=lambda *a: None
    )
    assert stats["kept_live"] == 0
    assert stats["annotated"] == 2  # week-01 AND week-03; week-06 has no prose
    assert jan.has_archive_notice(s3.objects["generated/journal/posts/week-01/index.html"])


# ── 5. The reset path emits the banner for the closing cycle's posts ─────────────


class _FakeTable:
    def __init__(self):
        self.updates = []

    def update_item(self, **kw):
        self.updates.append(kw)


class _FakeResource:
    def __init__(self, table):
        self._table = table

    def Table(self, name):
        return self._table


def test_the_reset_path_emits_the_archive_notice(tmp_path, monkeypatch):
    """THE BY-CONSTRUCTION LEG. Runs restart_chronicle_handler.main() --apply against
    a fake bucket and asserts the closing cycle's live article comes out of the reset
    carrying the banner, archived under a cycle-keyed prefix. A one-time repair that
    left the next reset to recreate the orphan would fail here.
    """
    import restart_chronicle_handler as handler

    s3 = FakeS3(_bucket())
    table = _FakeTable()

    def _client(service, **kw):
        if service == "s3":
            return s3
        if service == "ssm":
            return _FakeSSM(CYCLE)
        raise AssertionError(f"unexpected client {service}")

    monkeypatch.setattr(handler.boto3, "client", _client)
    monkeypatch.setattr(handler.boto3, "resource", lambda *a, **k: _FakeResource(table))
    monkeypatch.setattr(handler, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(handler, "EXPERIMENT_START_DATE", GENESIS)
    monkeypatch.setattr(handler, "EXPERIMENT_BASELINE_WEIGHT_LBS", BASELINE)
    monkeypatch.setattr(sys, "argv", ["restart_chronicle_handler.py", "--apply"])

    handler.main()

    live = s3.objects["generated/journal/posts/week-03/index.html"]
    assert jan.has_archive_notice(live), "the reset must annotate the closing cycle's live permalink"
    assert "326.24 lbs at the start" in live, "a frozen artifact is never rewritten"
    assert weight_truth_qa.assess_frozen_artifact_weights(_surfaces(live), BASELINE) == []
    assert "generated/journal/archive/cycle-16/posts/week-03/index.html" in s3.objects

    report = (tmp_path / "docs" / "restart" / "_chronicle_report.txt").read_text(encoding="utf-8")
    assert "journal_notices_written = 2" in report  # week-01 + week-03; week-06 has no prose
    assert "journal_pages_no_prose = 1" in report


class _FakeSSM:
    def __init__(self, cycle):
        self._cycle = cycle

    def get_parameter(self, Name):
        return {"Parameter": {"Value": str(self._cycle)}}


def test_the_journal_prefix_can_never_return_to_the_colliding_list():
    """The regression guard for the root cause. While the journal prefix sat in
    CHRONICLE_PREFIXES its archive destination was the constant
    `generated/journal/archive/pilot/posts/`, which collided with the 2026-07-10
    archival and made `archive_one` a silent no-op — AND its tombstone-overwrite
    wrote raw JSON over a public permalink. Both are why it now has its own step."""
    import restart_chronicle_handler as handler

    prefixes = [p for p, _a, _i in handler.CHRONICLE_PREFIXES]
    assert "generated/journal/posts/" not in prefixes
    assert not any("journal" in a for _p, a, _i in handler.CHRONICLE_PREFIXES)


def test_a_css_rule_named_post_header_is_not_the_anchor():
    """The live shell carries `.post-header { ... }` inside a <style> block ~40 lines
    ABOVE the body. An anchor loose enough to match it would inject the banner into
    the stylesheet, where html_to_text strips it and the checker stays red."""
    html = '<html><head><style>.post-header { padding:1rem; }</style></head><body>\n<div class="post-header">x</div>\n</body></html>'
    out, outcome = jan.inject_archive_notice(html, _notice())
    assert outcome == "injected"
    assert out.index(jan.NOTICE_ATTR) > out.index("</style>")
    assert reader_truth_qa.html_to_text(out).lower().count("editor's note") == 1
