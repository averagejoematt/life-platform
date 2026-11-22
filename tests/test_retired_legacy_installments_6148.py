"""tests/test_retired_legacy_installments_6148.py — the retired legacy chronicle installments stay retired (#6148).

Three legacy chronicle installments answered 200 until their quarantine on 2026-11-22, and site/ syncs legacy/ with no
exclusion, so a full page committed at a retired slug is re-published by the next site deploy. Two halves:

  * the repo half: every committed site/legacy/chronicle/posts/*/index.html is byte-identical to the one "no longer
    available" stub, and nothing in the legacy chronicle links or excerpts a retired slug;
  * the guard half: scripts/check_public_copies.py rule E reds on a planted full page — served, archived or committed —
    and stays green on the stub.

Fixture pages are invented filler; no sentence of a retired page appears here (the repo is public).
"""

# premerge-gate: 6148: a glob of the committed site/legacy/chronicle/posts/*/index.html tree — a full page at a retired slug must red BEFORE the merge, because the site deploy on merge re-publishes it.

import glob
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))

import check_public_copies as G  # noqa: E402

POSTS = os.path.join(REPO, "site", "legacy", "chronicle", "posts")
QUARANTINED = ("interview", "issue-05", "week-00")
FILLER = "<!doctype html><html><body>" + "<p>Invented filler paragraph for a planted page.</p>" * 40 + "</body></html>"


def _stub() -> bytes:
    with open(G.RETIRED_INSTALLMENT_STUB, "rb") as fh:
        return fh.read()


# ── the repo half ─────────────────────────────────────────────────────────────────────────────────────────────────────
def test_every_committed_legacy_installment_is_the_stub():
    stub = _stub()
    assert b"no longer available" in stub and len(stub) < 1024
    pages = sorted(glob.glob(os.path.join(POSTS, "*", "index.html")))
    assert pages, "the legacy chronicle posts tree is missing"
    offenders = []
    for path in pages:
        with open(path, "rb") as fh:
            if fh.read() != stub:
                offenders.append(os.path.relpath(path, REPO))
    assert offenders == [], f"a retired legacy installment must be the stub byte for byte: {offenders}"


def test_every_committed_installment_slug_is_declared_retired():
    on_disk = {os.path.basename(os.path.dirname(p)) for p in glob.glob(os.path.join(POSTS, "*", "index.html"))}
    assert on_disk <= set(G.RETIRED_INSTALLMENTS), sorted(on_disk - set(G.RETIRED_INSTALLMENTS))
    assert set(QUARANTINED) <= set(G.RETIRED_INSTALLMENTS)


def test_the_legacy_chronicle_no_longer_links_or_excerpts_the_quarantined_slugs():
    legacy = os.path.join(REPO, "site", "legacy", "chronicle")
    offenders = []
    for rel in ("posts.json", "index.html", "archive/index.html", "sample/index.html", "posts/TEMPLATE.html"):
        path = os.path.join(legacy, rel)
        if not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        offenders += [f"{rel} -> {slug}" for slug in QUARANTINED if f"/posts/{slug}/" in text]
    assert offenders == [], offenders
    with open(os.path.join(legacy, "posts.json"), encoding="utf-8") as fh:
        urls = {p.get("url") for p in json.load(fh)["posts"]}
    assert not {f"/chronicle/posts/{s}/" for s in QUARANTINED} & urls


def test_the_real_tree_passes_rule_e():
    assert G.retired_installment_issues([], None) == []


# ── the guard half: rule E on planted full pages ─────────────────────────────────────────────────────────────────────
def _tree(tmp_path, body: str):
    d = tmp_path / "site"
    for slug in G.RETIRED_INSTALLMENTS:
        (d / "legacy" / "chronicle" / "posts" / slug).mkdir(parents=True)
        (d / "legacy" / "chronicle" / "posts" / slug / "index.html").write_bytes(_stub())
    (d / "legacy" / "chronicle" / "posts" / "week-00" / "index.html").write_text(body)
    return str(d)


def test_rule_e_reds_on_a_committed_full_page_and_greens_on_the_stub(tmp_path):
    v = G.retired_installment_issues([], None, _tree(tmp_path / "a", FILLER))
    assert [(c, r) for c, r, _d in v] == [("legacy", "E")] and "week-00" in v[0][2] and "committed" in v[0][2]
    assert "filler" not in v[0][2].lower()  # sizes only: a page's words never reach the public CI log
    assert G.retired_installment_issues([], None, _tree(tmp_path / "b", _stub().decode())) == []


def test_rule_e_reds_on_a_served_full_page_and_not_on_a_served_stub():
    key = "site/legacy/chronicle/posts/interview/index.html"
    v = G.retired_installment_issues([{"Key": key, "Size": len(FILLER)}], None, None)
    assert [(c, r) for c, r, _d in v] == [("legacy", "E")] and "served" in v[0][2]
    assert G.retired_installment_issues([{"Key": key, "Size": len(_stub())}], None, None) == []


def test_rule_e_reds_on_an_archived_full_page():
    v = G.retired_installment_issues([], {"web/legacy/chronicle/posts/issue-05/index.html": FILLER.encode()}, None)
    assert [(c, r) for c, r, _d in v] == [("archive", "E")]
    assert G.retired_installment_issues([], {"web/legacy/chronicle/posts/issue-05/index.html": _stub()}, None) == []
