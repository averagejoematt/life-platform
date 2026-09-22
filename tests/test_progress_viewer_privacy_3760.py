"""tests/test_progress_viewer_privacy_3760.py — the viewer route stays unlinked and unserved.

WHY THIS IS A REPO-SHAPE GATE AND NOT A BEHAVIOUR TEST

`tests/test_progress_viewer_3760.py` proves the LOCK works. This file proves the door was
never put in a corridor. They are different failures with different lifetimes: a broken lock
is one bad commit, whereas a `/progress-photos/` entry that drifts into the sitemap, the RSS
feed, a nav partial or the QA page registry is a slow leak that every later change inherits.

The specific shapes it refuses, each one a thing that has actually happened on this repo to a
different surface:

  * **A private page under `site/`.** Every byte there is anonymously readable at the S3
    ORIGIN — CloudFront is not what makes it private. #3741 (the recap card under
    `generated/recap/`) is that exact assumption, held for eight days, verified live at 200.
  * **A link from a nav / sitemap / feed.** The URL is not the secret, but publishing it into
    a crawler's feed turns "nobody knows to try" into "everybody's index has a row".
  * **A QA-manifest entry.** A manifest row means "expect 200 anonymously". For this route
    that assertion is exactly backwards, so the route lives in `PRIVATE_ROUTES` instead —
    and this file is what makes that registry more than a comment.
  * **A grant that is wider than the read it exists for.** The viewer presigns; it must not
    be able to Put, Delete or List the prefix — and the PUBLIC site-api role must not be able
    to name `raw/` at all, which is #3757's ruling and the reason this is its own Lambda.

DERIVED, NOT HAND-LISTED: the site sweep is an `rglob` over the real tree, so a new page that
links the route is caught the day it lands. That sweep is why this file is registered in
`tests/conftest._PREMERGE_EXTRA_FILES` — a guard whose verdict depends only on the repo tree
has no business running after the merge.
"""

from __future__ import annotations

import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "lambdas"))
sys.path.insert(0, str(REPO / "tests"))

ROUTE = "/progress-photos"
PHOTO_PREFIX = "raw/matthew/progress_photos"


def _read(path: pathlib.Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


# ── the route is not published anywhere ───────────────────────────────────────
def test_no_site_file_mentions_the_route():
    """Every shipped byte under `site/`, swept — HTML, JS, CSS, JSON, XML, the manifest.

    An `rglob` rather than a list of the four files that matter today: the whole point is the
    FIFTH file nobody thought of (the "guard the SET, not the instance" rule).
    """
    site = REPO / "site"
    offenders = []
    for path in sorted(site.rglob("*")):
        if not path.is_file() or path.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".ico", ".woff", ".woff2", ".gz", ".mp3"):
            continue
        if ROUTE in _read(path):
            offenders.append(str(path.relative_to(REPO)))
    assert not offenders, (
        f"{ROUTE} is referenced by shipped site bytes: {offenders}. The viewer is owner-only "
        "(#3743, Tier 2) and must not be linked, listed or hinted at from the public site."
    )


def test_the_route_is_absent_from_the_sitemap_feeds_and_redirects_map():
    """Named explicitly as well as swept above, because these four are the ones a generator
    could rewrite without anyone opening them."""
    for rel in ("site/sitemap.xml", "site/rss.xml", "site/feed.xml", "redirects.map", "site/robots.txt"):
        path = REPO / rel
        if not path.exists():
            continue
        assert ROUTE not in _read(path), f"{rel} names {ROUTE}"


#: The one file under `scripts/` allowed to carry the route, and why. It is the census
#: PLANT — `MUTATION_SPECS["structural::test_progress_viewer_privacy_3760.py"]` writes a
#: `site/` page linking the route and asserts THIS file goes red on it, which is the only
#: evidence that the sweep above is wired to anything. Same shape (and same reason) as
#: `premerge_derivation._HELPER_EXCLUDED`: a module matches its own predicate because it
#: contains the predicate as a literal, not because it does the thing.
_PLANT_OWNER = "scripts/gate_census_mutations.py"


def test_no_generator_or_build_script_emits_the_route():
    """`site/**` is generator output (CLAUDE.md §site shells). A page can be clean in the tree
    and still grow the link on the next build if a builder writes it."""
    offenders = []
    for path in sorted((REPO / "scripts").rglob("*.py")):
        rel = str(path.relative_to(REPO))
        if rel == _PLANT_OWNER:
            continue
        if ROUTE in _read(path):
            offenders.append(rel)
    assert not offenders, f"a site generator emits {ROUTE}: {offenders}"


def test_the_plant_owner_still_carries_the_plant():
    """The exclusion above is only safe while it is excluding what it claims to exclude.

    If the mutation spec is ever deleted or renamed, this exclusion becomes a blind spot in
    the sweep rather than a documented exception — so the exception is itself asserted.
    """
    plant = _read(REPO / _PLANT_OWNER)
    assert plant, f"{_PLANT_OWNER} is gone — delete the exclusion, or this sweep has a hole"
    assert "test_progress_viewer_privacy_3760.py" in plant, (
        f"{_PLANT_OWNER} no longer carries this gate's mutation spec, so the exclusion is now " "just a file the sweep does not read"
    )


# ── the QA registries know it is private ──────────────────────────────────────
def test_the_route_is_registered_private_and_never_expects_a_200():
    import qa_manifest

    assert f"{ROUTE}/" in qa_manifest.PRIVATE_ROUTES, f"{ROUTE}/ must carry a PRIVATE_ROUTES row with its reason"
    codes, reason = qa_manifest.PRIVATE_ROUTES[f"{ROUTE}/"]
    assert "200" not in codes, "a private route may never list 200 as an acceptable anonymous status"
    assert len(reason) > 40, "a PRIVATE_ROUTES row states WHY — an empty reason is a row nobody can review"


def test_the_route_is_not_a_qa_manifest_page():
    """A manifest entry means 'expect 200 anonymously' and would put the page in the visual
    sweep, the leak scan and the smoke's page block. All three would be asserting the opposite
    of the property this route has."""
    import qa_manifest

    paths = {p["path"] for p in qa_manifest.MANIFEST}
    assert ROUTE not in paths and f"{ROUTE}/" not in paths
    assert not any(str(p.get("path", "")).startswith(ROUTE) for p in qa_manifest.visual_pages())


def test_the_smoke_suite_sweeps_the_private_registry():
    """The registry is only worth having if something reads it against the live site."""
    smoke = _read(REPO / "deploy" / "smoke_test_site.sh")
    assert "--emit private" in smoke, "deploy/smoke_test_site.sh does not sweep PRIVATE_ROUTES"
    assert "check_private" in smoke


# ── the edge + the grants ─────────────────────────────────────────────────────
def test_the_cloudfront_behaviour_exists_and_does_not_cache():
    web_stack = _read(REPO / "cdk" / "stacks" / "web_stack.py")
    assert f'path_pattern="{ROUTE}*"' in web_stack, f"no CloudFront behaviour routes {ROUTE}*"
    block = web_stack.split(f'path_pattern="{ROUTE}*"', 1)[1][:900]
    assert 'target_origin_id="ProgressViewerOrigin"' in block, "the private viewer must not share the site-api origin"
    assert '_api_pol["private_no_cache"]' in block, "the private viewer must not share /api/*'s 300s cache policy"
    assert '_api_pol["origin_private"]' in block, "the session cookie + the one-time token must reach the origin"


def test_the_cookie_name_is_the_same_string_in_the_lambda_and_at_the_edge():
    """CloudFront strips `Set-Cookie` on a behaviour whose cache policy forwards no cookies, so
    a mismatch here breaks the link exchange with a 302 into a 401 and no log line anywhere
    saying a cookie was dropped. The literal is duplicated (CDK synth has no `lambdas/` on its
    path); this assertion is the derivation guard that stands in for the import."""
    from privacy import progress_access

    policies = _read(REPO / "cdk" / "stacks" / "web_cloudfront_policies.py")
    assert f'PROGRESS_COOKIE_NAME = "{progress_access.COOKIE_NAME}"' in policies


def test_the_viewer_has_its_own_role_and_the_public_one_is_untouched():
    """#3757's ruling, kept: no `site_api*` role may name `raw/`. The viewer has its own.

    This is the reason the viewer is a separate Lambda at all. If a later refactor folds it
    back into the site-api to save a function, this is the test that says why not.
    """
    role = _read(REPO / "cdk" / "stacks" / "role_policies_serve.py")
    assert "def progress_viewer(" in role, "the viewer must have its own role, not a widened site_api()"
    site_api = role[role.index("def site_api(") : role.index("def progress_viewer(")]
    assert "raw/" not in site_api, "the public read path must not name the raw tree (#3757)"


def test_the_viewer_role_may_read_the_photos_and_nothing_more():
    role = _read(REPO / "cdk" / "stacks" / "role_policies_serve.py")
    viewer = role[role.index("def progress_viewer(") : role.index("def site_api_ai(")]
    assert f"{PHOTO_PREFIX}/*" in viewer, "the viewer cannot presign what it cannot GetObject"
    photo_stmt = viewer[viewer.index('sid="S3ProgressPhotoRead"') :][:400]
    assert '"s3:GetObject"' in photo_stmt
    for forbidden in ("s3:PutObject", "s3:DeleteObject", "s3:ListBucket", "s3:*"):
        assert forbidden not in photo_stmt, f"the viewer's grant includes {forbidden} — it presigns reads, nothing else"
    # The one write it may make, and the only one.
    assert '"PROGRESS_LINK#*"' in viewer
    assert '"dynamodb:PutItem"' in viewer and '"dynamodb:UpdateItem"' not in viewer and '"dynamodb:DeleteItem"' not in viewer


def test_exactly_two_roles_read_the_signing_secret():
    from privacy import progress_access

    role = _read(REPO / "cdk" / "stacks" / "role_policies_serve.py")
    assert role.count(f'_secret_arn("{progress_access.DEFAULT_SECRET_NAME}")') == 2, (
        "the signing secret must be granted to exactly two roles — progress_viewer (verify) "
        "and telegram_worker (mint). A third reader is a new decision, not a detail."
    )


def test_the_viewer_lambda_is_deploy_registered_where_it_actually_runs():
    """us-east-1, in LifePlatformWeb. A missing `region` field is the #test_lambda_map_regions
    bug shape: deploy_lambda.sh would update a us-west-2 twin that does not exist."""
    entry = json.loads(_read(REPO / "ci" / "lambda_map.json"))["lambdas"]["lambdas/web/progress_viewer_lambda.py"]
    assert entry["function"] == "progress-viewer"
    assert entry["region"] == "us-east-1"
    assert entry["stack"] == "LifePlatformWeb"


def test_the_photo_prefix_is_not_anonymously_readable():
    """`raw/` must never join `site/`, `blog/` or `generated/` in the public-read statements —
    the presigned-URL design is pointless if the object is readable without one."""
    policy = json.loads(_read(REPO / "deploy" / "bucket_policy.json"))
    for stmt in policy.get("Statement", []):
        if stmt.get("Effect") != "Allow" or stmt.get("Principal") != "*":
            continue
        resources = stmt.get("Resource")
        for res in [resources] if isinstance(resources, str) else (resources or []):
            assert "/raw/" not in str(res), f"a public-read statement covers raw/: {stmt.get('Sid')}"


# ── the privacy ruling still says what the code does ──────────────────────────
def test_the_governance_row_still_describes_this_viewer():
    gov = _read(REPO / "docs" / "DATA_GOVERNANCE.md")
    row = [line for line in gov.splitlines() if "progress_photos" in line]
    assert row, "the progress_photos retention row is gone — #3757 put it there before the first object existed"
    text = "\n".join(row)
    assert "#3760" in text, "the retention row must name the viewer that reads the prefix"
    assert ROUTE in text, "the retention row must name the route, so the privacy ruling and the code agree"


def test_the_tier_is_still_owner_only():
    from privacy.field_tiers import TIER_OWNER_ONLY, source_tier_of

    assert source_tier_of("progress_photos") == TIER_OWNER_ONLY
