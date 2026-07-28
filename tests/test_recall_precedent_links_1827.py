"""test_recall_precedent_links_1827.py — every precedent link a coach may cite opens.

#1827: `deploy/backfill_recall_embeddings.py` stored each chronicle precedent's reader
link as `/chronicle/week-{week_number}/` — a slug that does not exist on the live site
(installments publish at `/journal/posts/week-NN/`, `chronicle_render.journal_post_ref`;
no redirect covers the old form). All 17 live recall rows carried it,
`semantic_recall.render_precedent_line` appended it to every precedent line, and
`ai_calls` injects that block into the coach system prompt under "Cite ONLY a date +
link shown above" — so the ONLY citable references resolved to 404. The
precedent-citation gate validates against the same list, so nothing downstream caught
it. Aggravator: the form was also NON-UNIQUE across cycles (`/chronicle/week-0/`
appeared 6 times).

Two halves, pinned separately because they fail independently:
  WRITE — the backfill derives the link from the PUBLISHED post ordering, byte-identical
          to what `chronicle_render` actually publishes (parity test, not a restatement),
          and emits NO link for an installment that isn't published.
  READ  — `semantic_recall` refuses to render the dead form even if a legacy row still
          carries it, so the live rows stop injecting 404s before the backfill re-runs.

Hermetic — no AWS, no Bedrock, no network.

Run with:   python3 -m pytest tests/test_recall_precedent_links_1827.py -v
"""

import importlib.util
import os
import sys

os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "emails"))

import chronicle_render as cr  # noqa: E402
import semantic_recall as sr  # noqa: E402
from common.constants import EXPERIMENT_START_DATE  # noqa: E402


def _load_backfill():
    """Import the deploy script by path (it is not an importable package)."""
    path = os.path.join(_REPO, "deploy", "backfill_recall_embeddings.py")
    spec = importlib.util.spec_from_file_location("backfill_recall_embeddings", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


bf = _load_backfill()

# Genesis-relative dates so the fixture never rots against a re-anchored experiment.
_G = EXPERIMENT_START_DATE


def _inst(date, *, week_number, phase="experiment", tombstone=False, sk=None):
    item = {
        "pk": "USER#matthew#SOURCE#chronicle",
        "sk": sk or f"DATE#{date}",
        "date": date,
        "week_number": week_number,
        "title": f"Week {week_number}",
        "subtitle": "",
        "content_markdown": f"body for {date}",
        "phase": phase,
    }
    if tombstone:
        item["tombstone"] = True
    return item


# ── WRITE: the backfill link == the URL the publisher actually writes ────────
def test_backfill_link_matches_the_published_post_url():
    """Parity with `chronicle_render.journal_post_ref` — the ONE definition of where an
    installment lives. If the publisher's slug scheme changes, this fails."""
    installments = [
        _inst("2026-07-08", week_number=1),
        _inst("2026-07-15", week_number=2),
        _inst("2026-07-22", week_number=3),
    ]
    links = bf.published_post_links(installments)
    for inst in installments:
        _seq, _label, canonical = cr.journal_post_ref(
            inst["date"], installments, inst["week_number"], _g={"EXPERIMENT_START_DATE": _G}, sk=inst["sk"]
        )
        assert links[(inst["date"], inst["sk"])] == canonical.replace("https://averagejoematt.com", "")


def test_backfill_no_longer_emits_the_dead_chronicle_slug():
    """The exact defect: `/chronicle/week-N/` must not appear for ANY installment."""
    installments = [_inst("2026-07-08", week_number=1), _inst("2026-07-15", week_number=2)]
    for link in bf.published_post_links(installments).values():
        assert not link.startswith("/chronicle/week-")
        assert link.startswith("/journal/posts/week-")


def test_same_date_installments_get_distinct_links():
    """The aggravator: two installments sharing a date (the genesis−1 lead-in + the
    prereg chapter) must not collide on one page — (date, sk) keys them apart."""
    a = _inst("2026-07-26", week_number=0, sk="DATE#2026-07-26")
    b = _inst("2026-07-26", week_number=0, sk="DATE#2026-07-26#prereg")
    links = bf.published_post_links([a, b])
    assert len(set(links.values())) == 2


def test_unpublished_installments_get_no_link_at_all():
    """A wiped prior-cycle installment stays in the corpus (cross-cycle recall is the
    point) but has no reader page — so it gets NO link, never another week's URL."""
    published = _inst("2026-07-22", week_number=3)
    wiped = _inst("2026-03-04", week_number=9, phase="pilot")
    tombstoned = _inst("2026-04-01", week_number=12, tombstone=True)
    links = bf.published_post_links([published, wiped, tombstoned])
    assert list(links) == [(published["date"], published["sk"])]
    assert links[(published["date"], published["sk"])] == "/journal/posts/week-01/"


def test_gather_chronicle_attaches_published_links_only():
    class _T:
        def query(self, **_kw):
            return {"Items": [_inst("2026-07-22", week_number=3), _inst("2026-03-04", week_number=9, phase="pilot")]}

    by_date = {d["date"]: d for d in bf.gather_chronicle(_T())}
    assert by_date["2026-07-22"]["link"] == "/journal/posts/week-01/"
    assert by_date["2026-03-04"]["link"] == ""  # in the corpus, cited by date alone


# ── WRITE: a stale link is repaired without paying to re-embed ───────────────
def test_metadata_refresh_repairs_a_live_dead_link_without_re_embedding():
    """The live rows' text is unchanged, so `text_sha` idempotency would skip them
    forever. Drift detection turns that skip into a free link/cycle repair."""
    existing = {"text_sha": "abc", "link": "/chronicle/week-0/", "cycle": 10}
    drift = bf.metadata_drift(existing, {"link": "/journal/posts/week-03/", "cycle": 11})
    assert drift == {"link": "/journal/posts/week-03/", "cycle": 11}
    assert (
        bf.metadata_drift(
            {"text_sha": "abc", "link": "/journal/posts/week-03/", "cycle": 11}, {"link": "/journal/posts/week-03/", "cycle": 11}
        )
        == {}
    )


def test_metadata_refresh_removes_a_cycle_that_no_longer_exists():
    """A source record with no cycle stamp REMOVES the attribute — so the renderer makes
    no cycle claim, rather than a stale one (ADR-104)."""
    drift = bf.metadata_drift(
        {"text_sha": "abc", "link": "/journal/posts/week-03/", "cycle": 10}, {"link": "/journal/posts/week-03/", "cycle": None}
    )
    assert drift == {"cycle": None}

    updates = []

    class _T:
        def update_item(self, **kwargs):
            updates.append(kwargs)

    bf.refresh_metadata(_T(), "DOC#chronicle#2026-07-22", drift)
    assert "REMOVE" in updates[0]["UpdateExpression"]
    assert "ExpressionAttributeValues" not in updates[0]


# ── READ: a legacy dead link can never render ────────────────────────────────
def test_safe_link_drops_the_dead_form_and_keeps_real_ones():
    assert sr.safe_link("/chronicle/week-0/") == ""
    assert sr.safe_link("/chronicle/week-12") == ""
    assert sr.safe_link("/journal/posts/week-03/") == "/journal/posts/week-03/"
    assert sr.safe_link("/story/chronicle/") == "/story/chronicle/"
    assert sr.safe_link("/coaching/") == "/coaching/"
    assert sr.safe_link(None) == ""


def test_a_legacy_row_injects_no_dead_link_into_the_coach_prompt():
    """End-to-end over the LIVE row shape: corpus → rank → block. The prompt gets the
    date (true) and no URL (honest) instead of a 404."""
    legacy_row = {
        "pk": sr.RECALL_PK,
        "sk": sr.sk_for(sr.KIND_CHRONICLE, "2026-02-28"),
        "kind": sr.KIND_CHRONICLE,
        "doc_date": "2026-02-28",
        "emb": sr.encode_vector([1.0, 0.0]),
        "cycle": 10,
        "link": "/chronicle/week-0/",
        "artifact_pk": "USER#matthew#SOURCE#chronicle",
        "artifact_sk": "DATE#2026-02-28",
    }

    class _T:
        def query(self, **_kw):
            return {"Items": [legacy_row]}

    corpus = sr.load_corpus(_T())
    assert corpus[0]["link"] == ""
    block = sr.recall_block(sr.rank_precedents([1.0, 0.0], corpus))
    assert "2026-02-28" in block
    assert "/chronicle/week-" not in block


def test_render_line_drops_a_dead_link_even_if_handed_one_directly():
    line = sr.render_precedent_line({"date": "2026-02-28", "similarity": 0.91, "cycle": 10, "link": "/chronicle/week-0/"})
    assert "/chronicle/week-" not in line
    assert "2026-02-28" in line and "cycle 10" in line
    live = sr.render_precedent_line({"date": "2026-07-22", "similarity": 0.88, "cycle": 11, "link": "/journal/posts/week-03/"})
    assert live.endswith("/journal/posts/week-03/")


def test_recall_card_link_is_never_the_dead_form():
    card = sr.recall_card([{"date": "2026-02-28", "similarity": 0.91, "cycle": 10, "link": "/chronicle/week-0/", "kind": "chronicle"}])
    assert card["link"] == ""
