"""tests/test_v9_cutover_5534.py — the v9 cut-over's one-owner-per-path contract (#5534, epic #5529).

Two deploy paths write s3://matthew-life-platform/site/: the site/ tree (deploy/sync_site_to_s3.sh on
every site/** merge, deploy/rollback_site.sh on a red sweep) and the v9 build (www/dist through
deploy/www_preview_sync.sh). This file holds the pieces that make that safe, each as a test that can fail:

  1. the exclusion derivation — a v9-owned path planted under a COPY of site/ is covered by the exclude set
     the site sync passes to `aws s3 sync` (fnmatch, the CLI's own semantics), and a kept page beside it
     under the same prefix is NOT (exact paths, never a swallowing prefix);
  2. the sync and rollback scripts read that set, fail closed without it, and thread it through every
     sync that could reach a v9 key (the structural half: the script text, not S3);
  3. the collision rule — a v9 route landing on a kept site/ page outside REPLACED_ROUTES is refused;
  4. the committed artifacts (www/owned_paths.json, www/reach.json) are consistent with src/pages/ and
     with each other, and the switch defaults to off;
  5. the target resolution — a push deploys preview while the switch is off, root once it is on; a
     dispatch for root is REFUSED while it is off (a dispatch cannot launch ahead of the repo);
  6. the page registry derives the v9 rows from the manifest in BOTH switch states (none before, the
     replacements at `/` after), with the tiers and visual defs the sweeps need;
  7. the reference copies — six superseded pages kept under /reference/2026-11-01-*/ with the last live
     sha, noindex and a canonical pointing at their v9 successor; /start/ and /coaches/ noindex in place;
  8. the sitemap writer follows the switch; robots.txt lists both sitemaps and disallows /reference/;
  9. the workflow: one dispatch input, root-only sweeps + rollback jobs, every OIDC job on
     `ungated-deploy`, and the rollback restoring the PREVIOUS v9 build, never site/.

Mutation controls are inline where the property is "X must be refused" (a planted collision, a dropped
exclude, the switch forced on/off through the function arguments) — the gate is proven to be able to
fail on the same run that proves it passes.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys

import pytest
import yaml

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (REPO, os.path.join(REPO, "qa"), os.path.join(REPO, "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

import qa_manifest  # noqa: E402

from deploy import (
    www_deploy_target as target,  # noqa: E402
    www_owned_paths as owned,  # noqa: E402
)

OWNED = owned.load()
SYNC = open(os.path.join(REPO, "deploy", "sync_site_to_s3.sh"), encoding="utf-8").read()
ROLLBACK = open(os.path.join(REPO, "deploy", "rollback_site.sh"), encoding="utf-8").read()
WWW_SYNC = open(os.path.join(REPO, "deploy", "www_preview_sync.sh"), encoding="utf-8").read()
WORKFLOW = yaml.safe_load(open(os.path.join(REPO, ".github", "workflows", "web-preview-deploy.yml"), encoding="utf-8"))
WORKFLOW_TEXT = open(os.path.join(REPO, ".github", "workflows", "web-preview-deploy.yml"), encoding="utf-8").read()


# ── 1. the exclusion derivation, on a planted copy ───────────────────────────────────────────────
def _plant_site_copy(tmp_path):
    """A small copy of site/ with a v9-owned page planted beside a kept page under the same prefix."""
    site = tmp_path / "site"
    (site / "story" / "chronicle").mkdir(parents=True)
    (site / "story" / "chronicle" / "index.html").write_text("<html>kept v5 chronicle</html>", encoding="utf-8")
    (site / "story" / "week-06").mkdir(parents=True)
    (site / "story" / "week-06" / "index.html").write_text("<html>a v9 chapter, planted</html>", encoding="utf-8")
    (site / "story" / "index.html").write_text("<html>the v8 story page</html>", encoding="utf-8")
    (site / "index.html").write_text("<html>the v8 front page</html>", encoding="utf-8")
    (site / "404.html").write_text("<html>v5 404</html>", encoding="utf-8")
    (site / "assets" / "fonts" / "v9").mkdir(parents=True)
    (site / "assets" / "fonts" / "v9" / "archivo-latin.woff2").write_bytes(b"\0")
    (site / "assets" / "fonts" / "clean").mkdir(parents=True)
    (site / "assets" / "fonts" / "clean" / "geist-latin.woff2").write_bytes(b"\0")
    (site / "data" / "sleep").mkdir(parents=True)
    (site / "data" / "sleep" / "index.html").write_text("<html>kept v5 sleep readout</html>", encoding="utf-8")
    (site / "data" / "index.html").write_text("<html>the v5 data hub</html>", encoding="utf-8")
    return site


def _relpaths(root):
    out = []
    for dirpath, _d, files in os.walk(root):
        for f in files:
            out.append(os.path.relpath(os.path.join(dirpath, f), root).replace(os.sep, "/"))
    return sorted(out)


def test_planted_v9_path_is_excluded_and_the_kept_page_beside_it_is_not(tmp_path):
    site = _plant_site_copy(tmp_path)
    skipped = {rel for rel in _relpaths(site) if owned.is_excluded(rel, OWNED)}
    # the v9-owned paths (the planted chapter, the replaced pages, the 404, the v9 fonts) are skipped…
    assert {
        "index.html",
        "story/index.html",
        "story/week-06/index.html",
        "404.html",
        "data/index.html",
        "assets/fonts/v9/archivo-latin.woff2",
    } <= skipped
    # …and the kept pages under the SAME prefixes are synced as before (exact paths, not /story/* or /data/*)
    assert "story/chronicle/index.html" not in skipped
    assert "data/sleep/index.html" not in skipped
    assert "assets/fonts/clean/geist-latin.woff2" not in skipped


def test_sub_sync_patterns_are_rerooted(tmp_path):
    """The assets/ and data/ syncs run from a sub-directory, so their patterns are relative to it."""
    assert owned.exclude_patterns(OWNED, under="assets") == ["fonts/v9/*"]
    data = owned.exclude_patterns(OWNED, under="data")
    assert "index.html" in data and all(not p.startswith("data/") for p in data)
    assert owned.is_excluded("fonts/v9/archivo-latin.woff2", OWNED, under="assets")
    assert not owned.is_excluded("fonts/clean/geist-latin.woff2", OWNED, under="assets")


def test_exclusion_derivation_can_fail_control():
    """Control: drop `/story/week-06/` from the owned routes and the planted path is no longer covered."""
    mutated = json.loads(json.dumps(OWNED))
    mutated["routes"].remove("/story/week-06/")
    assert owned.is_excluded("story/week-06/index.html", OWNED)
    assert not owned.is_excluded("story/week-06/index.html", mutated)


def test_exclude_args_cli_matches_the_library():
    out = subprocess.run(
        [sys.executable, os.path.join(REPO, "deploy", "www_owned_paths.py"), "--exclude-args"], capture_output=True, text=True, check=True
    )
    toks = out.stdout.split()
    assert toks[::2] == ["--exclude"] * (len(toks) // 2)
    assert toks[1::2] == owned.exclude_patterns(OWNED)


# ── 2. the scripts read the set, fail closed, and thread it through every sync ──────────────────
def test_sync_script_derives_its_excludes_from_the_reader_and_fails_closed():
    assert "www_owned_paths.py" in SYNC and "--exclude-args" in SYNC
    assert re.search(
        r'if ! WWW_EX_RAW="\$\(python3 "\$_WWW_OWNED" --exclude-args\)"; then\n.*\n\s*exit 1', SYNC
    ), "no exclude set → no sync"
    # every `aws s3 sync` FROM the build tree carries the (re-rooted) owned excludes
    syncs = re.findall(r'aws s3 sync "\$(?:BUILD_DIR|SITE_DIR)(/[a-z]*/?)" [^\n]*\n(?:[^\n]*\\\n)*', SYNC)
    assert len(syncs) >= 7, syncs
    for block in re.finditer(r'aws s3 sync "\$(?:BUILD_DIR|SITE_DIR)(/[a-z]*/?)" (?:[^\n]*\\\n)*[^\n]*', SYNC):
        src, text = block.group(1), block.group(0)
        expected = {"/": "WWW_EXCLUDES", "/assets/": "WWW_EXCLUDES_ASSETS", "/data/": "WWW_EXCLUDES_DATA"}[src]
        assert f'${{{expected}[@]+"${{{expected}[@]}}"}}' in text, f"a sync from {src} runs without the owned excludes:\n{text}"
    # the excludes come AFTER the step's own include/exclude filters, so they take precedence (aws-cli: last match wins)
    html_step = re.search(r'--include "\*\.html" \\\n\s*\$\{WWW_EXCLUDES\[@\]', SYNC)
    assert html_step, "the HTML sync must apply the owned excludes after its --include"


def test_rollback_goes_through_the_same_excluding_sync():
    assert "bash deploy/sync_site_to_s3.sh" in ROLLBACK, "rollback_site.sh must re-run the canonical sync (which excludes)"
    assert "www_owned_paths.py --exclude-args" in ROLLBACK, "the dry run names the excluded set"
    assert "--restore-previous" in ROLLBACK and "never this script" in ROLLBACK


def test_site_deploy_fonts_sync_excludes_the_v9_fonts():
    text = open(os.path.join(REPO, ".github", "workflows", "site-deploy.yml"), encoding="utf-8").read()
    assert re.search(r'site/assets/fonts/" --exclude "v9/\*"', text), "the explicit fonts sync must skip assets/fonts/v9/ (v9-owned)"


# ── 3. the collision rule ────────────────────────────────────────────────────────────────────────
def test_live_dist_collision_rule_refuses_a_kept_page_and_passes_the_replaced_set(tmp_path):
    site = _plant_site_copy(tmp_path)
    routes = {"/", "/story/", "/data/", "/system/", "/system/ledger/"}
    assert owned.collisions(routes, {"404.html", "sitemap.xml"}, str(site)) == [], "the declared replaced set passes"
    # control: a v9 route that lands on a kept page is named — the planted site/story/week-06/ is exactly that
    bad = owned.collisions(routes | {"/data/sleep/", "/story/week-06/"}, set(), str(site))
    assert len(bad) == 2 and "/data/sleep/" in bad[0] and "/story/week-06/" in bad[1] and "REPLACED_ROUTES" in bad[0]
    (site / "robots.txt").write_text("x", encoding="utf-8")
    bad_file = owned.collisions(set(), {"robots.txt"}, str(site))
    assert bad_file and "robots.txt" in bad_file[0], "a kept root file the build would overwrite is named"


def test_check_dist_cli_passes_on_the_real_tree_when_a_dist_exists():
    dist = os.path.join(REPO, "www", "dist")
    if not os.path.isfile(os.path.join(dist, "index.html")):
        pytest.skip("www/dist not built in this checkout (CI's web-gate builds it)")
    r = subprocess.run(
        [sys.executable, os.path.join(REPO, "deploy", "www_owned_paths.py"), "--check-dist", dist], capture_output=True, text=True
    )
    assert r.returncode == 0, r.stderr


def test_replaced_set_is_exactly_the_destinations_the_plan_keeps_at_their_address():
    assert owned.REPLACED_ROUTES == {"/", "/story/", "/data/", "/privacy/"}
    assert owned.REPLACED_FILES == {"404.html", "sitemap.xml"}
    assert set(owned.SUPERSEDED) == owned.REPLACED_ROUTES | {"/start/", "/coaches/"}
    # every replaced route is one the build actually writes, and every one of them has a site/ page today
    for route in owned.REPLACED_ROUTES:
        assert route in OWNED["static_routes"], route
        rel = route.strip("/")
        assert os.path.isfile(os.path.join(REPO, "site", rel, "index.html") if rel else os.path.join(REPO, "site", "index.html"))


# ── 4. the committed artifacts ───────────────────────────────────────────────────────────────────
def test_owned_paths_json_is_consistent_with_src_pages_and_the_switch_is_on():
    pages = os.path.join(REPO, "www", "src", "pages")
    static, patterns = set(), set()
    for dirpath, _d, files in os.walk(pages):
        for f in files:
            if not f.endswith(".astro"):
                continue
            rel = os.path.relpath(os.path.join(dirpath, f), pages)[: -len(".astro")].replace(os.sep, "/")
            if rel == "404":
                continue
            route = "/" if rel == "index" else ("/" + rel[: -len("/index")] + "/" if rel.endswith("/index") else "/" + rel + "/")
            (patterns if "[" in route else static).add(re.sub(r"\[[^\]]+\]", "*", route))
    assert set(OWNED["static_routes"]) == static
    assert set(OWNED["route_patterns"]) == patterns
    assert set(OWNED["static_routes"]) <= set(OWNED["routes"])
    assert "404.html" in OWNED["files"] and {"sitemap.xml", "sitemap-index.xml", "sitemap-0.xml"} <= set(OWNED["files"])
    assert OWNED["prefixes"] == ["_astro/", "assets/fonts/v9/"]
    assert OWNED["base"] == "/"
    assert (
        OWNED["live_at_root"] is True
    ), "the owner's explicit go flipped `/` on 2026-11-01; un-launching is a deliberate PR, never a drift"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", OWNED["flipped_on"] or ""), OWNED["flipped_on"]
    assert OWNED["routes"] == sorted(OWNED["routes"]) and OWNED["files"] == sorted(OWNED["files"]), "deterministic: sorted"


def test_every_owned_route_is_a_static_route_or_matches_a_pattern():
    for route in OWNED["routes"]:
        ok = route in OWNED["static_routes"] or any(re.fullmatch(p.replace("*", "[^/]+"), route) for p in OWNED["route_patterns"])
        assert ok, f"{route} is written by no template"


# ── 5. the target resolution ─────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "event,requested,live,expected",
    [
        ("push", "", False, "preview"),
        ("push", "", True, "root"),
        ("workflow_dispatch", "preview", False, "preview"),
        ("workflow_dispatch", "", True, "preview"),
        ("workflow_dispatch", "root", True, "root"),
        ("workflow_dispatch", "root", False, None),  # REFUSED: a dispatch cannot launch ahead of the repo
        ("workflow_dispatch", "staging", True, None),
    ],
)
def test_target_resolution(event, requested, live, expected):
    got, reason = target.resolve(event, requested, live)
    assert got == expected, reason
    if expected is None and requested == "root":
        assert "REFUSED" in reason and "live_at_root" in reason


def test_target_cli_resolves_root_once_the_switch_is_on_and_still_refuses_it_while_off(tmp_path):
    from deploy import www_deploy_target as tgt

    # the pure rule, both states: a dispatch cannot launch ahead of the repo; a push follows the switch
    target, reason = tgt.resolve("workflow_dispatch", "root", live=False)
    assert target is None and "REFUSED" in reason
    assert tgt.resolve("push", "", live=False)[0] == tgt.PREVIEW
    assert tgt.resolve("push", "", live=True)[0] == tgt.ROOT
    assert tgt.resolve("workflow_dispatch", "preview", live=True)[0] == tgt.PREVIEW
    # the CLI against the committed switch (on since 2026-11-01)
    env = dict(os.environ, GITHUB_OUTPUT=str(tmp_path / "out1"))
    r = subprocess.run(
        [sys.executable, os.path.join(REPO, "deploy", "www_deploy_target.py"), "--event", "workflow_dispatch", "--input", "root"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert r.returncode == 0 and "live_at_root=true" in r.stdout and (tmp_path / "out1").read_text() == "target=root\n", r.stdout
    env = dict(os.environ, GITHUB_OUTPUT=str(tmp_path / "out2"))
    r = subprocess.run(
        [sys.executable, os.path.join(REPO, "deploy", "www_deploy_target.py"), "--event", "push"], capture_output=True, text=True, env=env
    )
    assert r.returncode == 0 and (tmp_path / "out2").read_text() == "target=root\n"


def test_www_sync_script_guards_the_root_sync_and_never_deletes(tmp_path):
    assert "--delete" not in WWW_SYNC
    assert "--live-at-root ||" in WWW_SYNC and "exit 4" in WWW_SYNC, "root sync must refuse while live_at_root is false"
    assert "--check-dist" in WWW_SYNC, "root sync must run the live collision check"
    assert "site/_v9_previous" in WWW_SYNC and "--restore-previous" in WWW_SYNC and "--record-previous" in WWW_SYNC
    # the restore's SOURCE is the previous v9 build, never the site/ tree or the repo
    restore = WWW_SYNC[WWW_SYNC.index('if [ "$MODE" = "restore" ]') : WWW_SYNC.index("# ── sync and record")]
    assert 'aws s3 sync "s3://$BUCKET/$PREVIOUS_PREFIX' in restore and "$SITE_DIR" not in restore and "git checkout" not in restore
    # a lane can rehearse every mode without credentials
    env = {k: v for k, v in os.environ.items() if not k.startswith("AWS_")}
    env.update({"AWS_ACCESS_KEY_ID": "", "AWS_SECRET_ACCESS_KEY": "", "AWS_PROFILE": ""})
    r = subprocess.run(
        ["bash", os.path.join(REPO, "deploy", "www_preview_sync.sh"), "--target", "root", "--restore-previous", "--print"],
        capture_output=True,
        text=True,
        env=env,
        cwd=REPO,
    )
    assert r.returncode == 0 and "s3://matthew-life-platform/site/_v9_previous" in r.stdout and "$ aws s3 sync" in r.stdout, (
        r.stdout + r.stderr
    )
    r = subprocess.run(
        ["bash", os.path.join(REPO, "deploy", "www_preview_sync.sh"), "--target", "root", "--dist", str(tmp_path / "no-such-dist")],
        capture_output=True,
        text=True,
        env=env,
        cwd=REPO,
    )
    # the switch is on (2026-11-01): the root sync passes the switch guard and stops at the next guard — the built
    # tree must exist — before any aws call; the off-state refusal (exit 4) is pinned in the script text above
    assert r.returncode == 3 and "dist dir not found" in r.stderr and "aws" not in r.stdout, r.stdout + r.stderr


# ── 6. the page registry derives the v9 rows ─────────────────────────────────────────────────────
def test_registry_describes_the_v9_pages_once_the_switch_is_on():
    v9 = [p for p in qa_manifest.MANIFEST if p.get("owner") == "www"]
    assert {p["path"] for p in v9} == set(OWNED["static_routes"]) | {"/404.html"}, "one row per static v9 route + the 404 object"
    assert qa_manifest._v9_rows(OWNED, live=False) == [], "switch off = no v9 rows (the v8 description returns)"
    assert (
        qa_manifest.PAGES_BY_PATH["/"]["owner"] == "www" and qa_manifest.PAGES_BY_PATH["/"]["js_modules"] == []
    ), "the v9 Start page is what / describes"
    assert qa_manifest.PAGES_BY_PATH["/privacy/"]["structural"]["marker"], "#1429's named surface stays in the structural sweep"


def test_registry_derives_the_v9_rows_once_the_switch_is_on():
    rows = qa_manifest._v9_rows(OWNED, live=True)
    by_path = {r["path"]: r for r in rows}
    assert set(by_path) == set(OWNED["static_routes"]) | {"/404.html"}
    assert {p for p, r in by_path.items() if r["tier"] == 1} == {"/", "/story/", "/data/", "/system/"}
    assert all(r["tier"] == 2 for p, r in by_path.items() if p not in {"/", "/story/", "/data/", "/system/", "/404.html"})
    assert all(r["owner"] == "www" for r in by_path.values())
    assert all(
        r["content_class"] == ("static" if p in qa_manifest._V9_STRUCTURAL else "live-data") for p, r in by_path.items() if p != "/404.html"
    ), "every v9 page is baked from the snapshot; #1429's named structural surface (/privacy/) keeps a marker"
    assert (
        by_path["/privacy/"]["structural"]["marker"]
        in open(os.path.join(REPO, "www", "src", "pages", "privacy", "index.astro"), encoding="utf-8").read()
    )
    assert all(r["visual"] and r["visual"]["wait_for"] == "main#main" for p, r in by_path.items() if p != "/404.html")
    import publish_snapshot as ps

    assert set(by_path["/"]["api_deps"]) == {v for k, v in ps.LIVE_ENDPOINTS.items() if k not in ps.OPTIONAL_ENDPOINTS}
    assert by_path["/404.html"]["structural"]["fetch_path"].startswith("/nonexistent")
    live = qa_manifest._build(rows)
    paths = [p["path"] for p in live]
    assert len(paths) == len(set(paths)), "the v9 rows REPLACE the site rows for the same path — no duplicates"
    live_by = {p["path"]: p for p in live}
    assert live_by["/"]["owner"] == "www" and live_by["/data/"]["owner"] == "www" and live_by["/404.html"]["owner"] == "www"
    assert (
        live_by["/start/"]["owner"] == "site" and live_by["/coaches/"]["owner"] == "site"
    ), "the twinless kit pages stay served from site/"
    assert live_by["/cockpit/"]["tier"] == 1, "the kept v5 doors keep their rows"


def test_registry_v9_rows_satisfy_the_manifest_well_formedness_rules():
    for p in qa_manifest._v9_rows(OWNED, live=True):
        assert p["path"].startswith("/") and p["tier"] in (1, 2, 3, 4)
        assert p["content_class"] in {"live-data", "narrative", "static", "utility", "generated"}
        assert isinstance(p["api_deps"], list) and isinstance(p["js_modules"], list)
        if p["tier"] in (1, 2):
            assert p["visual"], f"{p['path']}: a deploy-gating tier needs a visual def"


# ── 7. the reference copies ──────────────────────────────────────────────────────────────────────
def test_reference_copies_exist_with_sha_noindex_and_successor_canonical():
    for path, (slug, layout, successor) in owned.SUPERSEDED.items():
        f = os.path.join(REPO, "site", "reference", f"{owned.CUTOVER_DATE}-{slug}-{layout}", "index.html")
        assert os.path.isfile(f), f"{path}: no reference copy at {os.path.relpath(f, REPO)}"
        head = open(f, encoding="utf-8").read()[:6000]
        assert re.search(
            rf"<!-- reference copy of {re.escape(path)} at [0-9a-f]{{40}} \(the {layout} layout", head
        ), f"{path}: head comment"
        assert '<meta name="robots" content="noindex,nofollow">' in head, f"{path}: noindex"
        assert f'<link rel="canonical" href="https://averagejoematt.com{successor}">' in head, f"{path}: canonical → {successor}"
        # the copy renders from the served assets exactly as the original did
        assert "/assets/css/" in head, f"{path}: asset links left in place"


def test_twinless_kit_pages_are_served_noindex_and_canonical_to_their_successor():
    for path in ("/start/", "/coaches/"):
        f = os.path.join(REPO, "site", path.strip("/"), "index.html")
        head = open(f, encoding="utf-8").read()[:4000]
        assert 'name="robots" content="noindex' in head, f"{path} must be noindex (no v9 twin, served, not indexed)"
        assert f'<link rel="canonical" href="https://averagejoematt.com{owned.SUPERSEDED[path][2]}">' in head
        assert 'http-equiv="refresh"' not in head, "no redirects (ruling 2026-09-26)"


def test_reference_copy_script_is_dry_run_by_default_and_idempotent(tmp_path):
    r = subprocess.run([sys.executable, os.path.join(REPO, "scripts", "v9_reference_copies.py")], capture_output=True, text=True, cwd=REPO)
    assert r.returncode == 0 and "DRY RUN" in r.stdout and "nothing written" in r.stdout
    assert r.stdout.count("(exists, kept)") == len(owned.SUPERSEDED), r.stdout
    assert "already noindex" in r.stdout


def test_appendix_lists_the_reference_copies_in_their_own_group():
    import publish_snapshot as ps

    items = ps.build_appendix()["items"]
    ref = {it["path"] for it in items if it["group"] == ps.REFERENCE_GROUP}
    for path, (slug, layout, _s) in owned.SUPERSEDED.items():
        assert f"/reference/{owned.CUTOVER_DATE}-{slug}-{layout}/" in ref, path
    assert "/reference/2026-10-22-home-v5/" in ref, "the #4588 precedent copies are listed too"
    assert all(it["unlisted"] for it in items if it["group"] == ps.REFERENCE_GROUP)
    # a v9 row never lists itself as a kept page
    assert not [it for it in items if qa_manifest.PAGES_BY_PATH.get(it["path"], {}).get("owner") == "www"]


# ── 8. one writer per sitemap file; robots ───────────────────────────────────────────────────────
def test_sitemap_writer_follows_the_switch_and_skips_v9_rows(tmp_path, monkeypatch):
    import v4_build_sitemap as sm

    assert "sitemap-site.xml" in open(sm.__file__, encoding="utf-8").read()
    fake = tmp_path / "site"
    for slug in ("kept-page", "data"):
        (fake / slug).mkdir(parents=True)
        (fake / slug / "index.html").write_text("<html><head></head><body>page</body></html>", encoding="utf-8")
    monkeypatch.setattr(sm, "SITE", fake)
    monkeypatch.setattr(sm, "_page_registry", lambda: [{"path": "/kept-page/"}, {"path": "/data/", "owner": "www"}])
    urls = sm.registry_urls()
    assert urls == [f"{sm.BASE}/kept-page/"], "a page the v9 build owns is in the build's sitemap, never this one"
    assert sm.v9_owns_sitemap_xml() is True, "after the flip the build writes sitemap.xml; this generator writes sitemap-site.xml only"


def test_committed_sitemaps_and_robots():
    site = os.path.join(REPO, "site")
    assert os.path.isfile(os.path.join(site, "sitemap-site.xml")), "the kept pages' sitemap is a committed, deployed file"
    robots = open(os.path.join(site, "robots.txt"), encoding="utf-8").read()
    for line in (
        "Disallow: /next/",
        "Disallow: /reference/",
        "Disallow: /_v9_previous/",
        "Sitemap: https://averagejoematt.com/sitemap.xml",
        "Sitemap: https://averagejoematt.com/sitemap-site.xml",
    ):
        assert line in robots, line
    for name in ("sitemap.xml", "sitemap-site.xml"):
        text = open(os.path.join(site, name), encoding="utf-8").read()
        for noindexed in ("averagejoematt.com/reference/", "averagejoematt.com/start/</loc>", "averagejoematt.com/coaches/</loc>"):
            assert noindexed not in text, f"{name}: a noindex page is advertised ({noindexed})"


# ── 9. the workflow ──────────────────────────────────────────────────────────────────────────────
def test_workflow_has_one_target_input_and_root_only_sweeps_and_rollback():
    on = WORKFLOW.get("on") or WORKFLOW.get(True)
    inputs = on["workflow_dispatch"]["inputs"]
    assert set(inputs) == {"target"} and inputs["target"]["options"] == ["preview", "root"] and inputs["target"]["default"] == "preview"
    assert set(on["push"]["paths"]) >= {"www/**", "deploy/www_preview_sync.sh"}
    jobs = WORKFLOW["jobs"]
    assert set(jobs) == {"deploy", "smoke", "visual-qa", "record-previous", "rollback-v9-on-failure"}
    for name in ("smoke", "visual-qa", "record-previous", "rollback-v9-on-failure"):
        assert "needs.deploy.outputs.target == 'root'" in jobs[name]["if"], f"{name} must run for the root target only"
    assert "needs.smoke.result == 'failure' || needs.visual-qa.result == 'failure'" in jobs["rollback-v9-on-failure"]["if"]
    assert "needs.smoke.result == 'success' && needs.visual-qa.result == 'success'" in jobs["record-previous"]["if"]
    for name in ("deploy", "record-previous", "rollback-v9-on-failure"):
        assert jobs[name].get("environment") == "ungated-deploy", f"{name}: the deploy role trusts only environment subjects (#4257)"
    for name, job in jobs.items():
        assert isinstance(job.get("timeout-minutes"), int), f"{name}: every job declares a timeout"
    runs = [s["run"] for j in jobs.values() for s in j["steps"] if isinstance(s, dict) and s.get("run")]
    assert any("www_deploy_target.py" in r for r in runs) and any("www_build_target.sh" in r for r in runs)
    assert any("www_preview_sync.sh --target root --record-previous" in r for r in runs)
    assert any("www_root_rollback.sh" in r for r in runs)
    joined = "\n".join(runs)
    assert (
        "rollback_site.sh" not in joined and "sync_site_to_s3.sh" not in joined
    ), "the v9 workflow never runs the site/ sync or its rollback"
    assert "smoke_test_site.sh" in joined and "visual_qa.py --screenshot --ai-qa --ai-qa-max-tier 1" in joined
    assert "check_www_build.py --scan-only" in joined, "the build+scan step names the gate it runs (census-visible)"


def test_root_rollback_script_declines_on_an_unreachable_surface_and_restores_otherwise(tmp_path):
    script = os.path.join(REPO, "deploy", "www_root_rollback.sh")
    text = open(script, encoding="utf-8").read()
    assert "--restore-previous" in text and "rollback_site.sh" not in text
    out = tmp_path / "out"
    env = dict(
        os.environ,
        SITE_REACHABLE="false",
        QA_SURFACES="api",
        QA_SUMMARY="api red",
        GITHUB_OUTPUT=str(out),
        GITHUB_SHA="abc1234567",
        SNS_TOPIC_ARN="",
    )
    r = subprocess.run(["bash", script], capture_output=True, text=True, env=env, cwd=REPO)
    assert r.returncode == 0 and "DECLINED" in r.stdout and "declined=true" in out.read_text(), r.stdout + r.stderr


# premerge-gate: 5534: a structural sweep of deploy/sync_site_to_s3.sh, deploy/rollback_site.sh, .github/workflows/web-preview-deploy.yml and site/reference/ — a new sync step without the owned excludes, or a new superseded page without its copy, must red on the PR that adds it
