"""tests/test_story_desk_unlisted.py — #4537: an UNLISTED chronicle installment keeps its page URL
but leaves the reading list and the Prologue part numbering, identically in BOTH manifest
builders (the Wednesday publisher and deploy/restart_leadin_pages). A builder that re-lists it
would undo the season's curation on the next live Wednesday publish.
"""

import json
import os
import sys

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("EMAIL_RECIPIENT", "test@example.com")
os.environ.setdefault("EMAIL_SENDER", "noreply@example.com")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "emails"))
sys.path.insert(0, os.path.join(_REPO, "deploy"))

from datetime import datetime, timedelta  # noqa: E402

import restart_leadin_pages as rlp  # noqa: E402
import wednesday_chronicle_lambda as chron  # noqa: E402

_G = chron.EXPERIMENT_START_DATE


def _d(days):
    return (datetime.strptime(_G, "%Y-%m-%d") + timedelta(days=days)).strftime("%Y-%m-%d")


def _inst(title, date, sk, unlisted=False):
    it = {
        "title": title,
        "week_number": 0,
        "date": date,
        "sk": sk,
        "stats_line": "",
        "word_count": 100,
        "content_markdown": "body",
        "phase": "experiment",
    }
    if unlisted:
        it["unlisted"] = True
    return it


PART_I = _inst("Before the Numbers", _d(-6), f"DATE#{_d(-200)}")
OLD = _inst("The Night Before Everything", _d(-1), f"DATE#{_d(-50)}", unlisted=True)
PLAN = _inst("The Plan, On the Record", _d(-1), f"DATE#{_d(-1)}")
WK1 = {**_inst("Week one", _d(2), f"DATE#{_d(2)}"), "week_number": 1}
ALL = [PART_I, OLD, PLAN, WK1]


class _NoS3:
    def get_object(self, *a, **k):
        raise RuntimeError("offline")


def _wednesday_manifest(monkeypatch):
    from content import editorial_image

    monkeypatch.setattr(chron, "s3", _NoS3())
    monkeypatch.setattr(editorial_image, "enabled", lambda: False)
    _k, _h, js = chron.publish_to_journal(
        title=WK1["title"], stats_line="", body_html="<p>b</p>", week_num=1, date_str=WK1["date"], all_installments=ALL, write_to_s3=False
    )
    return json.loads(js)["posts"]


def _leadin_manifest(monkeypatch):
    captured = {}

    class _T:
        def query(self, **kw):
            return {"Items": ALL}

    class _R:
        def Table(self, name):
            return _T()

    monkeypatch.setattr(rlp.boto3, "resource", lambda *a, **k: _R())
    monkeypatch.setattr(rlp.boto3, "client", lambda *a, **k: None)
    real_dumps = rlp.json.dumps

    def spy(obj, *a, **k):
        if isinstance(obj, dict) and "posts" in obj:
            captured["posts"] = obj["posts"]
        return real_dumps(obj, *a, **k)

    monkeypatch.setattr(rlp.json, "dumps", spy)
    rlp.run(apply=False)
    return captured["posts"]


def test_unlisted_leaves_the_list_but_keeps_every_url(monkeypatch):
    for posts in (_wednesday_manifest(monkeypatch), _leadin_manifest(monkeypatch)):
        titles = [p["title"] for p in posts]
        assert "The Night Before Everything" not in titles
        urls = {p["title"]: p["url"] for p in posts}
        # URL slots are sequenced over ALL visible records: the unlisted page still holds week-02
        assert urls["Before the Numbers"] == "/journal/posts/week-01/"
        assert urls["The Plan, On the Record"] == "/journal/posts/week-03/"
        assert urls["Week one"] == "/journal/posts/week-04/"
        labels = {p["title"]: p["label"] for p in posts}
        assert labels["Before the Numbers"] == "Prologue · Part I"
        assert labels["The Plan, On the Record"] == "Prologue · Part II"  # no gap where the unlisted part was


def test_both_builders_agree(monkeypatch):
    a = [(p["title"], p["url"], p["label"]) for p in _wednesday_manifest(monkeypatch)]
    b = [(p["title"], p["url"], p["label"]) for p in _leadin_manifest(monkeypatch)]
    assert a == b


def test_mutation_control_listed_again_reappears(monkeypatch):
    OLD.pop("unlisted")
    try:
        assert "The Night Before Everything" in [p["title"] for p in _wednesday_manifest(monkeypatch)]
        assert "The Night Before Everything" in [p["title"] for p in _leadin_manifest(monkeypatch)]
    finally:
        OLD["unlisted"] = True


def test_a_row_without_a_phase_is_rendered_like_the_wednesday_publisher_reads_it():
    """#4537 incident: weeks 1-4 carry no `phase`; the strict filter dropped them and published a 2-post list."""
    import inspect

    src = inspect.getsource(rlp.fetch_visible_installments)
    assert "attribute_not_exists(#phase)" in src
