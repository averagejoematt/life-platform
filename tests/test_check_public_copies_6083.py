"""tests/test_check_public_copies_6083.py — the public-copies guard (#6083), proved on planted violations.

Every rule is shown catching the shape the 2026-11-15 incident had (an orphan page under the preview, a stale preview,
an archive older than the deploy, an archived age-derived figure, an archived call carrying words the live route
withholds, a sitemap URL with no page, an archive member the registry now refuses), and the end-to-end run goes
red → green when a planted orphan is removed. Offline: the bucket listing, every object, the archive and the live
routes are injected fakes; every string is synthetic.

The inventory is pinned as a SET against its sources: every resource deploy/bucket_policy.json lets an anonymous
principal read, and every S3 origin path in cdk/stacks/web_stack.py, must be classified by the guard — a new public
prefix that could hold a copy of the site cannot arrive unclassified.
"""

import ast
import io
import json
import os
import sys
import tarfile
from datetime import datetime, timedelta, timezone

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))

import check_public_copies as G  # noqa: E402

T0 = datetime(2026, 11, 16, 3, 47, tzinfo=timezone.utc)
OWNED = {
    "routes": ["/", "/story/", "/story/week-01/"],
    "files": ["sitemap-0.xml", "data/series/steps.json"],
    "prefixes": ["_astro/"],
    "static_routes": ["/", "/story/"],
    "route_patterns": ["/story/*/"],
}
PAGE = "<!doctype html><html><head><title>t</title></head><body><p>A synthetic page.</p></body></html>"


def obj(key, when=T0, body=PAGE):
    return {"Key": key, "LastModified": when, "Size": len(body), "_body": body}


def clean_bucket():
    old = T0 - timedelta(days=30)
    return [
        obj("site/index.html"),
        obj("site/story/index.html"),
        obj("site/story/week-01/index.html"),
        obj("site/data/series/steps.json", body="{}"),
        obj("site/_astro/app.css", body="a{}"),
        obj("site/sitemap-0.xml", body="<urlset><url><loc>https://averagejoematt.com/story/week-01/</loc></url></urlset>"),
        obj("site/method/index.html", old),  # a kept site/ page (in the fake repo site/ tree)
        obj("generated/journal/posts/week-01/index.html", old),
        obj("generated/archive/latest.tar.gz", T0, "x"),
    ]


@pytest.fixture
def site_dir(tmp_path):
    d = tmp_path / "repo-site"
    (d / "method").mkdir(parents=True)
    (d / "method" / "index.html").write_text(PAGE)
    return str(d)


@pytest.fixture
def snapshot(tmp_path):
    d = tmp_path / "snap"
    d.mkdir()
    (d / "own_words.json").write_text(json.dumps({"state": "ok", "quotes": []}))
    (d / "manifest.json").write_text(json.dumps({"mode": "live"}))
    return str(d)


def archive(members, built="2026-11-16T03:50:00Z"):
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w:gz") as tf:
        for name, body in {"MANIFEST.json": json.dumps({"generated_at": built}), **members}.items():
            data = body.encode() if isinstance(body, str) else body
            info = tarfile.TarInfo(f"public-archive-2026-11-16/{name}")
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return raw.getvalue()


def clean_archive(**extra):
    return archive({"web/story/week-01/index.html": PAGE, "web/journal/posts/week-01/index.html": PAGE, **extra})


def run(listing, blob, snapshot, site_dir, mode="check", now=T0 + timedelta(hours=1), live=None):
    bodies = {o["Key"]: o.get("_body", PAGE).encode() for o in listing}
    clean = [{k: v for k, v in o.items() if k != "_body"} for o in listing]
    live = live or {}
    violations, facts = G.evaluate(
        clean, blob, snapshot, mode, now, fetch_key=lambda k: bodies[k], live_get=lambda r: live.get(r, {}), owned=OWNED, site_dir=site_dir
    )
    return violations, facts


def rules(violations):
    return sorted({(c, r) for c, r, _d in violations})


# ── the clean case, and the end-to-end mutation ──────────────────────────────────────────────────────────────────────
def test_a_clean_estate_has_no_violation(snapshot, site_dir):
    v, facts = run(clean_bucket(), clean_archive(), snapshot, site_dir)
    assert v == [], v
    assert facts["counts"]["root"] >= 4 and facts["counts"]["legacy"] == 1


def test_mutation_an_orphan_reds_the_run_and_its_removal_greens_it(snapshot, site_dir):
    """The 2026-11-15 shape: pages on retired addresses, under the preview, that the newest preview build did not write."""
    bucket = clean_bucket() + [obj("site/next/v9/index.html"), obj("site/next/v9/story/week-01/index.html")]
    assert run(bucket, clean_archive(), snapshot, site_dir)[0] == []
    planted = bucket + [obj("site/next/v9/story/retired-address/index.html", T0 - timedelta(days=10))]
    v, facts = run(planted, clean_archive(), snapshot, site_dir)
    assert rules(v) == [("preview", "A")] and "retired-address" in v[0][2]
    assert facts["orphans"]["preview"] == ["site/next/v9/story/retired-address/index.html"]
    assert run(bucket, clean_archive(), snapshot, site_dir)[0] == []  # removed → green


def test_an_orphan_at_the_root_is_caught_and_a_kept_site_page_is_not(snapshot, site_dir):
    bucket = clean_bucket() + [obj("site/story/program-week-99/index.html", T0 - timedelta(days=4))]
    v, _ = run(bucket, clean_archive(), snapshot, site_dir)
    assert rules(v) == [("root", "A")]  # site/method/ is 30 days old too, but it is the repo's kept page


# ── rule B ────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_a_stale_preview_is_caught_and_an_empty_one_is_not(snapshot, site_dir):
    stale = T0 - timedelta(days=10)
    bucket = clean_bucket() + [obj("site/next/v9/index.html", stale), obj("site/next/v9/story/index.html", stale)]
    v, _ = run(bucket, clean_archive(), snapshot, site_dir)
    assert ("preview", "B") in rules(v)
    assert run(clean_bucket(), clean_archive(), snapshot, site_dir)[0] == []  # no preview at all: the default


def test_a_retired_location_must_hold_nothing(snapshot, site_dir):
    v, _ = run(clean_bucket() + [obj("site/_v9_previous/index.html")], clean_archive(), snapshot, site_dir)
    assert ("retired", "B") in rules(v)


def test_a_retired_legacy_location_must_hold_nothing_6115(snapshot, site_dir):
    """#6115: /chronicle/, /evidence/ and /now/ were audited page by page and emptied (redirected or quarantined). A page
    re-published there — by a restart's chronicle archive step, a stray sync — fails rule B; it is not a declared
    legacy location any more, so rules C and D are not the only thing between it and a reader."""
    assert G.LEGACY_LOCATIONS == {}, "a retained legacy location needs its own reason and an audit row (#6115)"
    for key in ("site/chronicle/archive/cycle-18/posts/week-00/index.html", "site/evidence/stack/index.html", "site/now/index.html"):
        v, _ = run(clean_bucket() + [obj(key, T0 - timedelta(days=1))], clean_archive(), snapshot, site_dir)
        assert rules(v) == [("retired", "B")] and key in v[0][2], (key, v)


def test_an_archive_older_than_the_deploy_fails_remediation_and_an_old_one_fails_check(snapshot, site_dir):
    before = clean_archive()  # built 03:50, after the 03:47 build
    assert run(clean_bucket(), before, snapshot, site_dir, mode="remediation")[0] == []
    older = archive({"web/story/week-01/index.html": PAGE}, built="2026-11-16T00:22:00Z")
    assert rules(run(clean_bucket(), older, snapshot, site_dir, mode="remediation")[0]) == [("archive", "B")]
    assert run(clean_bucket(), older, snapshot, site_dir, mode="check")[0] == []  # inside one nightly cycle
    late = T0 + timedelta(days=2)
    assert ("archive", "B") in rules(run(clean_bucket(), older, snapshot, site_dir, mode="check", now=late)[0])


# ── rule C ────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_an_archived_age_derived_figure_is_caught(snapshot, site_dir):
    blob = clean_archive(**{"api/phenoage.json": json.dumps({"phenoage": 41.0, "drivers": []})})
    v, _ = run(clean_bucket(), blob, snapshot, site_dir)
    assert rules(v) == [("archive", "C")] and "/api/phenoage" in v[0][2]
    blob = clean_archive(**{"api/phenoage.json": json.dumps({"phenoage": None, "drivers": []})})
    assert run(clean_bucket(), blob, snapshot, site_dir)[0] == []


def test_an_archived_call_with_words_the_live_route_withholds_is_caught(snapshot, site_dir):
    archived = {
        "calls": [{"id": "c1", "claim": "a synthetic call worded in full", "verdict": "hit"}, {"id": "c2", "claim": "kept words here too"}]
    }
    live = {"/api/calls": {"calls": [{"id": "c1", "claim": None, "verdict": "hit"}, {"id": "c2", "claim": "kept words here too"}]}}
    v, facts = run(clean_bucket(), clean_archive(**{"api/calls.json": json.dumps(archived)}), snapshot, site_dir, live=live)
    assert rules(v) == [("archive", "C")] and "calls[id=c1].claim" in v[0][2] and "synthetic" not in v[0][2]
    assert facts["api_compared"] == 1
    live["/api/calls"]["calls"][0]["claim"] = "a synthetic call worded in full"
    assert run(clean_bucket(), clean_archive(**{"api/calls.json": json.dumps(archived)}), snapshot, site_dir, live=live)[0] == []


def test_records_sharing_an_id_are_skipped_never_guessed():
    archived = [{"id": "x", "t": "one two three"}, {"id": "x", "t": "four five six"}]
    assert G.withheld_words(archived, [{"id": "x", "t": ""}]) == []


# ── rule C's declared time-varying fields (#6223) ─────────────────────────────────────────────────────────────────────
def _status(comment, description="a synthetic component description"):
    return {"groups": [{"id": "compute", "components": [{"id": "sheet", "description": description, "comment": comment}]}]}


def _api_run(route, archived, live_doc, snapshot, site_dir):
    member = "api/" + route[len("/api/") :].replace("/", "__") + ".json"
    return run(clean_bucket(), clean_archive(**{member: json.dumps(archived)}), snapshot, site_dir, live={route: live_doc})


def test_a_status_comment_that_cleared_is_not_a_withholding_and_a_withheld_narrative_string_still_is_6223(snapshot, site_dir):
    """The 2026-11-23 failure: the archive caught a status sentence the board has since cleared to null. Nothing was
    withheld. Beside it, in the same run, a call's words the live route withholds are still a violation."""
    archived = _status("Last computed: 2d ago and runs daily")
    v, facts = _api_run("/api/status", archived, _status(None), snapshot, site_dir)
    assert v == [] and facts["api_volatile_null"] == 1
    assert "1 declared time-varying status field(s)" in G.report(v, facts, "check")
    calls = {"calls": [{"id": "c1", "claim": "a synthetic call worded in full"}]}
    blob = clean_archive(**{"api/status.json": json.dumps(archived), "api/calls.json": json.dumps(calls)})
    live = {"/api/status": _status(None), "/api/calls": {"calls": [{"id": "c1", "claim": None}]}}
    v, _ = run(clean_bucket(), blob, snapshot, site_dir, live=live)
    assert [(c, r) for c, r, _d in v] == [("archive", "C")] and "/api/calls" in v[0][2] and "calls[id=c1].claim" in v[0][2]


def test_a_status_string_the_gate_emptied_and_every_undeclared_status_field_still_red_6223(snapshot, site_dir):
    """Only JSON null on the declared field is excused. "" is what the publication gate leaves behind
    (narrative_publication.scrub_payload), and the status code never writes it — so "" stays a violation, as does any
    other string of the same route going empty."""
    archived = _status("Last computed: 2d ago and runs daily")
    v, facts = _api_run("/api/status", archived, _status(""), snapshot, site_dir)
    assert rules(v) == [("archive", "C")] and "components[id=sheet].comment" in v[0][2] and facts["api_volatile_null"] == 0
    v, _ = _api_run("/api/status", archived, _status("Last computed: 2d ago and runs daily", description=None), snapshot, site_dir)
    assert rules(v) == [("archive", "C")] and "components[id=sheet].description" in v[0][2]
    src = open(os.path.join(REPO, "lambdas", "web", "site_api_status.py"), encoding="utf-8").read()
    for form in ('comment = ""', '"comment": ""', "comment = ''", "\"comment\": ''"):
        assert form not in src, f"the status code must clear a comment to None, never to an empty string ({form!r})"


def test_the_volatile_allowlist_holds_operational_fields_only_6223(snapshot, site_dir, monkeypatch):
    """Guard the set: the exception cannot reach a route that carries anyone's words. Every archived route outside
    OPERATIONAL_ROUTES is shown still red on the exact archived/live pair the status route is excused for, and a
    declaration outside the operational routes is ignored by the code and refused here."""
    from operational import public_archive_registry as reg

    words = ("chapter", "coach", "call", "predict", "ledger", "journal", "diary", "narrat", "story", "note", "word", "quote")
    leaves = {"claim", "text", "body", "summary", "narrative", "quote", "note", "reason", "title", "excerpt", "statement", "short"}
    assert set(G.OPERATIONAL_ROUTES) == {"/api/status"}, (
        "a new operational route is a privacy decision: show its handler serves system state only (no row's words), " "then pin it here"
    )
    assert set(G.OPERATIONAL_ROUTES) <= set(reg.ARCHIVE_ROUTES)
    for route in G.OPERATIONAL_ROUTES:
        assert not [w for w in words if w in route], route
    for (route, shape), why in G.VOLATILE_FIELDS.items():
        assert route in G.OPERATIONAL_ROUTES, f"{route} is not an operational route — its fields cannot be declared volatile"
        assert shape.rsplit(".", 1)[-1] not in leaves and "=" not in shape and len(why.split()) >= 8, (route, shape)
    archived, live_doc = _status("Last computed: 2d ago and runs daily"), _status(None)
    not_red = []
    for route in sorted(set(reg.ARCHIVE_ROUTES) - set(G.OPERATIONAL_ROUTES)):
        assert G.volatile_fields(route) == frozenset()
        if G.withheld_words(archived, live_doc, volatile=G.volatile_fields(route)) != ["groups[id=compute].components[id=sheet].comment"]:
            not_red.append(route)
    assert not_red == [], f"routes where a string served null is no longer a violation: {not_red}"
    # a declaration on a words-bearing route does nothing: the code reads VOLATILE_FIELDS only through OPERATIONAL_ROUTES
    monkeypatch.setitem(G.VOLATILE_FIELDS, ("/api/ledger_export", "items[].simple_guess.text"), "a planted entry, eight words or more long")
    ledger = {"items": [{"item_id": "sleep:1", "simple_guess": {"text": "a synthetic guess sentence here"}}]}
    v, _ = _api_run("/api/ledger_export", ledger, {"items": [{"item_id": "sleep:1", "simple_guess": {"text": None}}]}, snapshot, site_dir)
    assert rules(v) == [("archive", "C")] and "items[item_id=sleep:1].simple_guess.text" in v[0][2]


def test_a_field_shape_keeps_the_field_and_drops_only_the_record_selectors_6223():
    assert G.field_shape("groups[id=compute].components[id=apple_health:glucose].comment") == "groups[].components[].comment"
    assert G.field_shape("items[item_id=sleep:1].simple_guess.text") == "items[].simple_guess.text"
    assert G.field_shape("comment") == "comment"


def test_a_sentinel_on_a_preview_page_is_caught(snapshot, site_dir):
    bucket = clean_bucket() + [obj("site/next/v9/index.html", body=PAGE.replace("synthetic", "DO-NOT-PUBLISH"))]
    v, _ = run(bucket, clean_archive(), snapshot, site_dir)
    assert rules(v) == [("preview", "C")]


def test_the_archive_may_not_carry_what_the_registry_now_refuses_or_what_is_no_longer_served(snapshot, site_dir):
    v, _ = run(clean_bucket(), clean_archive(**{"web/next/v9/index.html": PAGE}), snapshot, site_dir)
    assert rules(v) == [("archive", "A")] and "now refuses" in v[0][2]
    v, _ = run(clean_bucket(), clean_archive(**{"web/story/withdrawn/index.html": PAGE}), snapshot, site_dir)
    assert rules(v) == [("archive", "A")] and "no longer served" in v[0][2]


# ── rule D and the location check ─────────────────────────────────────────────────────────────────────────────────────
def test_a_sitemap_url_with_no_page_is_caught(snapshot, site_dir):
    bucket = [o for o in clean_bucket() if o["Key"] != "site/sitemap-0.xml"] + [
        obj("site/sitemap-0.xml", body="<urlset><url><loc>https://averagejoematt.com/story/retired/</loc></url></urlset>")
    ]
    v, _ = run(bucket, clean_archive(), snapshot, site_dir)
    assert rules(v) == [("root", "D")] and "no object serves it" in v[0][2]


def test_a_sitemap_url_served_only_by_an_orphan_is_caught(snapshot, site_dir):
    bucket = [o for o in clean_bucket() if o["Key"] != "site/sitemap-0.xml"] + [
        obj("site/story/retired/index.html", T0 - timedelta(days=3)),
        obj("site/sitemap-0.xml", body="<urlset><url><loc>https://averagejoematt.com/story/retired/</loc></url></urlset>"),
    ]
    v, _ = run(bucket, clean_archive(), snapshot, site_dir)
    assert [d for c, r, d in v if r == "D" and "served only by an orphan" in d], v


def test_a_new_undeclared_location_holding_documents_is_caught(snapshot, site_dir):
    v, _ = run(clean_bucket() + [obj("site/_v10_copy/index.html", T0 - timedelta(days=1))], clean_archive(), snapshot, site_dir)
    assert ("legacy", "location") in rules(v)


# ── rule E (#6148) ────────────────────────────────────────────────────────────────────────────────────────────────────
def test_a_full_page_at_a_retired_legacy_installment_reds_the_run_and_the_stub_does_not_6148(snapshot, site_dir):
    """End to end through evaluate(): a served full page at a retired slug, and its archived copy, fail rule E; the
    stub at the same address does not. Filler text only."""
    key = "site/legacy/chronicle/posts/week-00/index.html"
    full = "<!doctype html><html><body>" + "<p>Planted filler for a retired slug.</p>" * 30 + "</body></html>"
    with open(G.RETIRED_INSTALLMENT_STUB, encoding="utf-8") as fh:
        stub = fh.read()
    blob = clean_archive(**{"web/legacy/chronicle/posts/week-00/index.html": full})
    v, _ = run(clean_bucket() + [obj(key, body=full)], blob, snapshot, site_dir)
    assert {("legacy", "E"), ("archive", "E")} <= set(rules(v)), v
    v, _ = run(clean_bucket() + [obj(key, body=stub)], clean_archive(), snapshot, site_dir)
    assert not [d for _c, r, d in v if r == "E"], v


# ── the inventory, pinned as a set against its sources ───────────────────────────────────────────────────────────────
def test_every_anonymously_readable_resource_is_classified():
    with open(os.path.join(REPO, "deploy", "bucket_policy.json"), encoding="utf-8") as fh:
        policy = json.load(fh)
    public = set()
    for st in policy["Statement"]:
        actions = st["Action"] if isinstance(st["Action"], list) else [st["Action"]]
        if st["Effect"] == "Allow" and st.get("Principal") == "*" and "s3:GetObject" in actions:
            res = st["Resource"] if isinstance(st["Resource"], list) else [st["Resource"]]
            public |= {r.split(":::matthew-life-platform/", 1)[1] for r in res}
    assert public == set(G.PUBLIC_RESOURCES), (
        f"unclassified public resource(s): {sorted(public - set(G.PUBLIC_RESOURCES))}; "
        f"classified but no longer public: {sorted(set(G.PUBLIC_RESOURCES) - public)}"
    )
    for prefix in G.PRIVATE:
        assert not any(p.startswith(prefix) for p in public), f"{prefix} is listed private but the bucket policy publishes it"


def test_every_s3_origin_path_is_classified():
    tree = ast.parse(open(os.path.join(REPO, "cdk", "stacks", "web_stack.py"), encoding="utf-8").read())
    paths = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for kw in node.keywords:
                if kw.arg == "origin_path" and isinstance(kw.value, ast.Constant):
                    paths.add(kw.value.value)
            if getattr(node.func, "id", None) == "_s3_origin" and node.args and isinstance(node.args[0], ast.Constant):
                paths.add(node.args[0].value)
    assert paths and paths == set(G.ORIGIN_PATHS), f"origin paths {sorted(paths)} vs classified {sorted(G.ORIGIN_PATHS)}"


def test_a_transient_read_failure_is_retried_and_a_persistent_one_is_still_named(tmp_path):
    """Measured on production 2026-11-16: two consecutive runs each lost one read in ~1,570 to a transient error and
    aborted. A read that fails once is tried again; a key a reader persistently cannot fetch is still reported."""
    import urllib.error

    calls: dict[str, int] = {}

    def flaky(key):
        calls[key] = calls.get(key, 0) + 1
        if key == "site/gone/index.html" or (key == "site/b/index.html" and calls[key] == 1):
            raise urllib.error.URLError("reset")
        return b"<html></html>"

    keys = ["site/a/index.html", "site/b/index.html", "site/gone/index.html"]
    failed = G.download(keys, str(tmp_path), "site/", flaky, pause=0)
    assert failed == ["site/gone/index.html"]
    assert calls == {"site/a/index.html": 1, "site/b/index.html": 2, "site/gone/index.html": 1 + G.DOWNLOAD_RETRIES}
    assert (tmp_path / "b" / "index.html").read_bytes() == b"<html></html>" and not (tmp_path / "gone").exists()


def test_the_guard_writes_nothing_and_runs_no_remediation():
    src = open(os.path.join(REPO, "scripts", "check_public_copies.py"), encoding="utf-8").read()
    for verb in ("put_object", "delete_object", "copy_object", "create_invalidation(", "lambda_client", ".invoke("):
        assert verb not in src, f"the guard must stay read-only; found {verb!r}"
