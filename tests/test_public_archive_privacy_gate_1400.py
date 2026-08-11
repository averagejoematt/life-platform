#!/usr/bin/env python3
"""tests/test_public_archive_privacy_gate_1400.py — the manifest test IS the
privacy gate (#1400).

The Permanence Contract publishes one nightly download containing "everything
already public". The dangerous word in that sentence is *everything*: a
convenience bundle is the ideal vehicle for an accident, because a single
mis-classified prefix turns a hundred separate un-linked objects into one
labelled tarball a stranger can grep.

So this file does not check a hand-written list of allowed files. It derives
the platform's real public surface from source — the CloudFront behaviours in
``cdk/stacks/web_stack.py`` and the route set in ``deploy/endpoint_registry.py``
— and fails when any of it is unclassified in
``lambdas/operational/public_archive_registry.py``. Add a public route without
deciding whether it belongs in the archive and the build goes red; add a
private artefact under a public prefix and the archive refuses it.

Non-vacuity is proved here, not assumed. The derivation helpers take their
source text as an argument, so each gate is exercised against a synthetic tree
containing a deliberate violation and asserted to catch it. Three privacy
screens have shipped in this repo whose full suite passed with the screen
deleted; that is what the ``*_catches_*`` tests exist to prevent.
"""

from __future__ import annotations

import ast
import io
import json
import os
import sys
import tarfile
from datetime import datetime, timezone

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (os.path.join(ROOT, "lambdas"), os.path.join(ROOT, "deploy")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import endpoint_registry as er  # noqa: E402
import pii_surface_guard as guard  # noqa: E402
from operational import (
    public_archive as pa,  # noqa: E402
    public_archive_registry as reg,  # noqa: E402
)

WEB_STACK = os.path.join(ROOT, "cdk", "stacks", "web_stack.py")
SCHEMA_DIR = os.path.join(ROOT, "tests", "api_schemas")


# ── derivation helpers (parameterised, so the gates can be mutation-proved) ──
def generated_behaviours(source: str) -> set[str]:
    """Every CloudFront ``path_pattern`` routed to the generated origin.

    An AST walk rather than a regex: the behaviours are keyword arguments in a
    600-line list of constructor calls, and a regex over that would silently
    stop matching the first time someone reformats it.
    """
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        kw = {k.arg: k.value for k in node.keywords if k.arg}
        if "path_pattern" not in kw or "target_origin_id" not in kw:
            continue
        try:
            pattern = ast.literal_eval(kw["path_pattern"])
            origin = ast.literal_eval(kw["target_origin_id"])
        except (ValueError, TypeError):
            continue
        if origin == "S3GeneratedOrigin":
            found.add(pattern)
    return found


def unclassified_behaviours(source: str, classified: dict) -> set[str]:
    """The gate: behaviours the archive registry has never decided about."""
    return generated_behaviours(source) - set(classified)


def stale_classifications(source: str, classified: dict) -> set[str]:
    """The reverse ratchet: classifications for behaviours that no longer exist."""
    return set(classified) - generated_behaviours(source)


# ── Arm 1: the generated/ prefix ────────────────────────────────────────────
def test_every_generated_cloudfront_behaviour_is_classified():
    """A new public route may not enter the archive by default, nor evade it by
    accident. Every generated-origin behaviour must carry an explicit
    include/exclude verdict and a reason."""
    with open(WEB_STACK, encoding="utf-8") as fh:
        source = fh.read()
    missing = unclassified_behaviours(source, reg.GENERATED_ROUTES)
    assert not missing, (
        "CloudFront serves these generated-origin paths but the archive registry has no verdict for them.\n"
        "Classify each in lambdas/operational/public_archive_registry.py::GENERATED_ROUTES:\n"
        + "\n".join(f"  {p}" for p in sorted(missing))
    )
    stale = stale_classifications(source, reg.GENERATED_ROUTES)
    assert not stale, "these registry entries classify behaviours the distribution no longer has:\n" + "\n".join(
        f"  {p}" for p in sorted(stale)
    )


def test_classification_gate_catches_an_unclassified_behaviour():
    """Load-bearing: the derivation must actually flag a new public behaviour.
    Proven against a synthetic stack, not by trusting the walk."""
    synthetic = (
        "behaviors=[\n"
        "    Behavior(path_pattern='/public_stats.json', target_origin_id='S3GeneratedOrigin'),\n"
        "    Behavior(path_pattern='/private_ledger/*', target_origin_id='S3GeneratedOrigin'),\n"
        "    Behavior(path_pattern='/api/*', target_origin_id='LambdaApiOrigin'),\n"
        "]\n"
    )
    assert generated_behaviours(synthetic) == {"/public_stats.json", "/private_ledger/*"}
    assert unclassified_behaviours(synthetic, {"/public_stats.json": ("include", "x")}) == {"/private_ledger/*"}


def test_classification_gate_catches_a_stale_entry():
    """The reverse direction: a registry entry for a retired behaviour is also
    a failure — a stale verdict is a verdict nobody is checking."""
    synthetic = "Behavior(path_pattern='/public_stats.json', target_origin_id='S3GeneratedOrigin')\n"
    assert stale_classifications(synthetic, {"/public_stats.json": ("include", "x"), "/gone/*": ("include", "y")}) == {"/gone/*"}


def test_every_classification_carries_a_verdict_and_a_reason():
    for pattern, entry in reg.GENERATED_ROUTES.items():
        verdict, reason = entry
        assert verdict in (reg.INCLUDE, reg.EXCLUDE), f"{pattern}: bad verdict {verdict!r}"
        assert len(reason) >= 20, f"{pattern}: reason too thin to review — {reason!r}"


def test_unrouted_generated_prefixes_are_refused():
    """The whole ``generated/`` prefix is world-readable in S3, but only part of
    it is *published*. The archive must draw the line at published, not at
    readable — otherwise it repackages the QA capture and reader-submitted raw
    text into one convenient download."""
    samples = {
        "/qa_archive/": "generated/qa_archive/text/2026-08-01/board_ask--120000--abcd1234.json",
        "/board_questions/": "generated/board_questions/2026-06_6c3bdb8b8874.json",
        "/findings/": "generated/findings/2026-08-01_abc.json",
        "/coach_daily.json": "generated/coach_daily.json",
        "/coach_memoirs.json": "generated/coach_memoirs.json",
    }
    assert set(samples) == set(reg.UNROUTED_GENERATED_PREFIXES), "the sample keys must track the declared unrouted set"
    for label, key in sorted(samples.items()):
        assert not reg.admits_generated_key(key), f"{label}: {key} must never enter the public archive"


@pytest.mark.parametrize(
    "key",
    [
        "raw/matthew/whoop/2026/08/2026-08-01.json",
        "uploads/dexa-2026.pdf",
        "config/content_filter.json",
        "exports/2026-08-01/whoop.json",
        "deploys/site-api/latest.zip",
        "mcp-audit/2026-08-01.json",
        "remediation-log/automerge/2026-08-01.json",
        "panelcast-holds/wk1.mp3",
        "blog/archive/pilot/week-01.html",
        "dashboard/chronicle/posts/week-01.html",
    ],
)
def test_private_prefixes_never_enter(key):
    """Fail-closed across the bucket: anything outside the two published
    prefixes is refused by both arms, not merely absent from a listing."""
    assert not reg.admits_generated_key(key)
    assert not reg.admits_site_key(key)


def test_the_archive_never_contains_itself():
    assert not reg.admits_generated_key(reg.ARCHIVE_TARBALL_KEY)
    assert not reg.admits_generated_key(reg.ARCHIVE_MANIFEST_KEY)
    assert not reg.admits_generated_key(reg.ARCHIVE_CONTINUITY_KEY)
    assert not reg.admits_generated_key(reg.ARCHIVE_PREFIX + "final-2026-08-10.tar.gz")


def test_an_excluded_pattern_wins_over_an_including_one():
    """Order-independence: if any matching behaviour excludes a path, the path
    is out. A registry whose verdict depended on dict order would be a gate
    that changes meaning when someone alphabetises it."""
    verdict, _reason = reg.generated_decision("/assets/images/og-home.png")
    assert verdict == reg.EXCLUDE


# ── Arm 2: the site/ prefix ─────────────────────────────────────────────────
def test_admitted_site_suffixes_are_all_scanned_by_the_pii_guard():
    """The archive may only admit classes of file the site's own privacy
    scanner actually reads. Add ``.csv`` or ``.md`` to the archive without
    adding it to the scanner and this goes red — which is the point."""
    admitted = {s.lower() for s in reg.SITE_DOCUMENT_SUFFIXES}
    scanned = {s.lower() for s in guard._SCAN_EXT}
    assert admitted <= scanned, f"the archive would admit unscanned file classes: {sorted(admitted - scanned)}"


def test_site_presentation_layer_is_excluded():
    for key in (
        "site/assets/app.abcd1234.js",
        "site/assets/tokens.abcd1234.css",
        "site/assets/fonts/inter.woff2",
        "site/assets/images/hero.png",
        "site/favicon.ico",
    ):
        assert not reg.admits_site_key(key), key


def test_site_documents_are_admitted():
    for key in ("site/index.html", "site/method/index.html", "site/data/data_sources.json", "site/rss.xml", "site/robots.txt"):
        assert reg.admits_site_key(key), key


def test_legacy_tree_is_excluded_and_the_reason_is_declared():
    assert not reg.admits_site_key("site/legacy/index.html")
    assert "site/legacy/" in reg.SITE_EXCLUDED_PREFIXES
    assert len(reg.SITE_EXCLUDED_PREFIXES["site/legacy/"]) >= 40


# ── Arm 3: /api/* ───────────────────────────────────────────────────────────
def _write_path_exemptions() -> set[str]:
    with open(os.path.join(SCHEMA_DIR, "_exemptions.json"), encoding="utf-8") as fh:
        return set(json.load(fh))


def test_archived_routes_are_exactly_the_derived_read_surface():
    """Derived, not curated. The archive's route set must equal every route the
    site-api actually registers, minus the write paths already exempted by the
    endpoint privacy gate, minus the parameterised routes declared here with a
    reason. A new read endpoint joins the archive on the day it ships; a new
    write endpoint cannot join it at all."""
    discovered = set(er.discover_endpoint_paths())
    assert len(discovered) >= er.SANITY_FLOOR, "endpoint enumeration returned suspiciously few routes — refusing a vacuous comparison"
    expected = discovered - _write_path_exemptions() - set(reg.PARAMETERISED_ROUTES)
    actual = set(reg.ARCHIVE_ROUTES)
    assert actual == expected, (
        "archive route drift.\n"
        f"  missing from ARCHIVE_ROUTES: {sorted(expected - actual)}\n"
        f"  no longer a route:           {sorted(actual - expected)}"
    )


def test_parameterised_skips_are_real_routes_with_reasons():
    discovered = set(er.discover_endpoint_paths())
    for route, reason in reg.PARAMETERISED_ROUTES.items():
        assert route in discovered, f"{route} is declared parameterised but is not a route — stale entry"
        assert len(reason) >= 20, f"{route}: reason too thin to review"


def test_every_archived_route_is_already_under_the_endpoint_privacy_gate():
    """An endpoint may only be archived if its shape is already snapshotted and
    scanned by ``deploy/pii_surface_guard.py``'s endpoint arm. The archive
    inherits that gate rather than inventing a second, weaker one."""
    snapshotted = set()
    for name in os.listdir(SCHEMA_DIR):
        if not name.endswith(".json") or name == "_exemptions.json":
            continue
        with open(os.path.join(SCHEMA_DIR, name), encoding="utf-8") as fh:
            snapshotted.add(json.load(fh).get("path") or "")
    ungated = sorted(set(reg.ARCHIVE_ROUTES) - snapshotted)
    assert not ungated, "these routes would be archived without a scanned shape snapshot:\n" + "\n".join(f"  {r}" for r in ungated)


def test_api_arm_sends_no_credentials(monkeypatch):
    """The property that makes the API arm safe is that it is anonymous: it can
    only receive what an unauthenticated reader receives. Assert the request
    actually carries no auth, rather than trusting the docstring."""
    seen = {}

    class _Resp:
        status = 200

        def read(self):
            return b"{}"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def _fake_urlopen(req, timeout=None):
        seen["url"] = req.full_url
        seen["headers"] = {k.lower(): v for k, v in req.header_items()}
        return _Resp()

    monkeypatch.setattr(pa.urllib.request, "urlopen", _fake_urlopen)
    status, body = pa.default_fetch(reg.PUBLIC_ORIGIN + "/api/vitals")
    assert status == 200 and body == b"{}"
    assert seen["url"].startswith("https://")
    for banned in ("authorization", "cookie", "x-api-key", "x-subscriber-token"):
        assert banned not in seen["headers"], f"the archive fetcher sent a {banned} header"


# ── The manifest ────────────────────────────────────────────────────────────
class _FakeS3:
    def __init__(self, objects):
        self.objects = objects

    def list_objects_v2(self, Bucket, Prefix, ContinuationToken=None):  # noqa: N803 - boto3 kwarg names
        keys = sorted(k for k in self.objects if k.startswith(Prefix))
        return {"Contents": [{"Key": k, "Size": len(self.objects[k])} for k in keys], "IsTruncated": False}

    def get_object(self, Bucket, Key):  # noqa: N803
        return {"Body": io.BytesIO(self.objects[Key])}


_HOSTILE_BUCKET = {
    "generated/pulse.json": b'{"pulse":1}',
    "generated/journal/posts/week-01/index.html": b"<h1>week one</h1>",
    "generated/qa_archive/text/2026-08-01/board_ask--1.json": b'{"internal":"qa"}',
    "generated/board_questions/2026-06_abc.json": b'{"reader":"question"}',
    "generated/coach_daily.json": b'{"coach":"state"}',
    "generated/podcast/ep-2026-08-01.mp3": b"AUDIOAUDIO",
    "generated/archive/latest.tar.gz": b"PREVIOUS-ARCHIVE",
    "site/method/index.html": b"<h1>method</h1>",
    "site/assets/app.deadbeef.js": b"console.log(1)",
    "site/legacy/index.html": b"<h1>legacy</h1>",
    "raw/matthew/whoop/2026/08/2026-08-01.json": b'{"hrv":42}',
    "exports/2026-08-01/whoop.json": b'{"hrv":42}',
}


def _build(fetch_body=b'{"ok":true}'):
    return pa.build_archive(
        _FakeS3(dict(_HOSTILE_BUCKET)),
        "a-bucket",
        now=datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc),
        fetch=lambda url: (200, fetch_body),
        pause_seconds=0,
    )


def _members(tarball: bytes) -> set[str]:
    with tarfile.open(fileobj=io.BytesIO(tarball)) as tf:
        return {m.name.split("/", 1)[1] for m in tf.getmembers()}


def test_built_archive_contains_only_admitted_bytes():
    """End-to-end over a bucket seeded with every hostile case at once."""
    built = _build()
    members = _members(built["tarball"])
    assert "web/pulse.json" in members
    assert "web/journal/posts/week-01/index.html" in members
    assert "web/method/index.html" in members
    forbidden = [
        "web/qa_archive/text/2026-08-01/board_ask--1.json",
        "web/board_questions/2026-06_abc.json",
        "web/coach_daily.json",
        "web/podcast/ep-2026-08-01.mp3",
        "web/archive/latest.tar.gz",
        "web/assets/app.deadbeef.js",
        "web/legacy/index.html",
    ]
    leaked = [m for m in forbidden if m in members]
    assert not leaked, f"the archive admitted material it must refuse: {leaked}"
    assert not any("raw/" in m or "exports/" in m for m in members)


def test_manifest_lists_every_member_with_a_verifiable_checksum():
    """Every entry's SHA-256 must recompute from the tarball. A manifest whose
    numbers cannot be reproduced is decoration."""
    built = _build()
    manifest = built["manifest"]
    with tarfile.open(fileobj=io.BytesIO(built["tarball"])) as tf:
        actual = {}
        for member in tf.getmembers():
            name = member.name.split("/", 1)[1]
            extracted = tf.extractfile(member)
            assert extracted is not None
            actual[name] = extracted.read()
    listed = {e["member"] for e in manifest["entries"]}
    assert listed == set(actual) - {"MANIFEST.json", "README.txt"}
    for entry in manifest["entries"]:
        assert entry["bytes"] == len(actual[entry["member"]])
        assert entry["sha256"] == pa._sha256(actual[entry["member"]])
    assert manifest["archive"]["sha256"] == pa._sha256(built["tarball"])
    assert manifest["archive"]["bytes"] == len(built["tarball"])


def test_manifest_checksum_is_not_vacuous():
    """Mutation proof: change one byte of the archive and the published
    checksum must stop matching."""
    built = _build()
    mutated = built["tarball"][:-1] + bytes([built["tarball"][-1] ^ 0xFF])
    assert pa._sha256(mutated) != built["manifest"]["archive"]["sha256"]


def test_manifest_publishes_what_was_left_out():
    """An archive that quietly omits things is a worse promise than one that
    says what it omits (ADR-104)."""
    excluded = _build()["manifest"]["excluded"]
    whats = {x["what"] for x in excluded}
    for expected in ("/podcast/*", "/panelcast/*", "/qa_archive/", "/coach_daily.json", "/legacy/"):
        assert expected in whats, f"{expected} is excluded but the manifest does not say so"
    for item in excluded:
        assert len(item["why"]) >= 20, f"{item['what']}: exclusion reason too thin to review"


def test_manifest_carries_no_infrastructure_detail():
    """The issue's rigor note: no internal hostnames or infra detail rides out
    on the published artefacts. The manifest names public URL paths only — no
    bucket, no account, no ARN, no S3 key."""
    blob = json.dumps(_build()["manifest"])
    for needle in ("matthew-life-platform", "arn:aws", ".amazonaws.com", "s3://", "generated/", "AKIA"):
        assert needle not in blob, f"the published manifest leaks {needle!r}"


def test_manifest_reports_a_partial_api_capture_honestly():
    """A thin archive must read as thin. When routes fail, the manifest says
    how many of how many were captured and names the failures."""
    calls = {"n": 0}

    def _flaky(url):
        calls["n"] += 1
        if calls["n"] % 2 == 0:
            raise TimeoutError("slow")
        return 200, b'{"ok":true}'

    built = pa.build_archive(
        _FakeS3(dict(_HOSTILE_BUCKET)),
        "a-bucket",
        now=datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc),
        fetch=_flaky,
        pause_seconds=0,
    )
    api = built["manifest"]["api"]
    assert api["routes_declared"] == len(reg.ARCHIVE_ROUTES)
    assert 0 < api["routes_captured"] < api["routes_declared"]
    assert len(api["failures"]) == api["routes_declared"] - api["routes_captured"]
    assert all("error" in f and "path" in f for f in api["failures"])


def test_runaway_build_is_refused_rather_than_published():
    """A ceiling, not a target. If an admission rule ever changes shape, the
    run must fail loudly instead of shipping a 200 MB nightly download."""
    fat = {"generated/pulse.json": b"x" * (pa.MAX_UNCOMPRESSED_BYTES + 1)}
    with pytest.raises(RuntimeError, match="ceiling"):
        pa.build_archive(_FakeS3(fat), "a-bucket", fetch=lambda url: (200, b"{}"), pause_seconds=0)


def test_tarball_is_deterministic():
    """Same inputs, same bytes — so a reader mirroring two nights can tell
    whether anything actually changed."""
    first = _build()["tarball"]
    second = _build()["tarball"]
    assert first == second


def test_an_unreadable_object_is_counted_not_swallowed():
    class _Flaky(_FakeS3):
        def get_object(self, Bucket, Key):  # noqa: N803
            if Key == "site/method/index.html":
                raise RuntimeError("s3 hiccup")
            return super().get_object(Bucket=Bucket, Key=Key)

    built = pa.build_archive(
        _Flaky(dict(_HOSTILE_BUCKET)),
        "a-bucket",
        now=datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc),
        fetch=lambda url: (200, b"{}"),
        pause_seconds=0,
    )
    assert built["manifest"]["sources"]["objects_unreadable"] == 1
    assert "web/method/index.html" not in _members(built["tarball"])


# ── the reader's own verifier ───────────────────────────────────────────────
# scripts/verify_public_archive.py is the mechanism behind clause P4's "you do
# not have to trust the description; you can check it". If it cannot actually
# catch a tampered archive, that clause is decoration — so it is exercised here
# against a real build and against a deliberately corrupted one.
_VERIFY = os.path.join(ROOT, "scripts")
if _VERIFY not in sys.path:
    sys.path.insert(0, _VERIFY)
import verify_public_archive as verify  # noqa: E402


def _write_archive(tmp_path, tarball: bytes) -> str:
    path = os.path.join(str(tmp_path), "latest.tar.gz")
    with open(path, "wb") as fh:
        fh.write(tarball)
    return path


def test_the_public_verifier_passes_a_real_archive(tmp_path, capsys):
    built = _build()
    code = verify.main(["--archive", _write_archive(tmp_path, built["tarball"])])
    out = capsys.readouterr().out
    assert code == 0, out
    assert "OK — every checked claim holds." in out
    assert str(built["manifest"]["entry_count"]) in out


def test_the_public_verifier_catches_a_tampered_member(tmp_path, capsys):
    """Mutation proof on the reader's own tool: rebuild the tarball with one
    file's bytes swapped and leave the manifest alone. The verifier must name
    the file rather than shrug."""
    built = _build()
    with tarfile.open(fileobj=io.BytesIO(built["tarball"])) as tf:
        members = {}
        for info in tf.getmembers():
            extracted = tf.extractfile(info)
            assert extracted is not None
            members[info.name.split("/", 1)[1]] = extracted.read()
    members["web/pulse.json"] = b'{"pulse":999}'
    tampered = pa.build_tarball(members, built["root"], 0)

    code = verify.main(["--archive", _write_archive(tmp_path, tampered)])
    out = capsys.readouterr().out
    assert code == 1
    assert "checksum mismatch" in out
    assert "web/pulse.json" in out


def test_the_public_verifier_catches_a_smuggled_extra_file(tmp_path, capsys):
    """An unlisted member is the shape a leak would take: something in the
    tarball the manifest never mentions."""
    built = _build()
    with tarfile.open(fileobj=io.BytesIO(built["tarball"])) as tf:
        members = {}
        for info in tf.getmembers():
            extracted = tf.extractfile(info)
            assert extracted is not None
            members[info.name.split("/", 1)[1]] = extracted.read()
    members["web/secret.json"] = b'{"not":"listed"}'
    smuggled = pa.build_tarball(members, built["root"], 0)

    code = verify.main(["--archive", _write_archive(tmp_path, smuggled)])
    out = capsys.readouterr().out
    assert code == 1
    assert "which the manifest does not list" in out
    assert "web/secret.json" in out


def test_the_verifier_maps_members_back_to_public_urls():
    """Every entry must be reachable at a public URL — that is clause P3's
    claim. The reverse mapping is what makes `--check-urls` able to test it."""
    origin = "https://example.test"
    assert verify.public_url_for("web/method/index.html", origin) == "https://example.test/method/index.html"
    assert verify.public_url_for("api/vitals.json", origin) == "https://example.test/api/vitals"
    assert verify.public_url_for("api/status__summary.json", origin) == "https://example.test/api/status/summary"
    assert verify.public_url_for("something/else.bin", origin) is None


def test_every_built_member_has_a_derivable_public_url():
    """Set-level: if a member cannot be mapped back to a public URL, the
    archive is carrying something whose publicness nobody can check."""
    built = _build()
    unmappable = [
        m for m in _members(built["tarball"]) if m not in verify.SELF_DESCRIBING and verify.public_url_for(m, "https://x") is None
    ]
    assert not unmappable, f"members with no public URL: {unmappable}"


def test_the_in_tar_manifest_carries_the_continuity_state():
    """Someone who only ever has the file — a mirror, years later — should still
    be able to see what state the contract was in when it was made."""
    built = pa.build_archive(
        _FakeS3(dict(_HOSTILE_BUCKET)),
        "a-bucket",
        now=datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc),
        fetch=lambda url: (200, b"{}"),
        pause_seconds=0,
        continuity={"state": "active", "days_silent": 1, "frozen": False},
    )
    with tarfile.open(fileobj=io.BytesIO(built["tarball"])) as tf:
        inner = tf.extractfile([m for m in tf.getmembers() if m.name.endswith("MANIFEST.json")][0])
        assert inner is not None
        manifest = json.load(inner)
    assert manifest["continuity"] == {"state": "active", "days_silent": 1, "frozen": False}


def test_the_readme_verification_recipe_actually_runs(tmp_path):
    """Clause P4 says a reader can check the archive without trusting it. The
    README ships the whole procedure as a runnable snippet, so this executes
    that snippet — lifted out of the generated README, not re-typed here — and
    asserts it reports the real file count and no mismatches."""
    import subprocess  # noqa: PLC0415 - test-only

    built = _build()
    archive_path = os.path.join(str(tmp_path), "latest.tar.gz")
    with open(archive_path, "wb") as fh:
        fh.write(built["tarball"])
    with tarfile.open(archive_path) as tf:
        root = tf.getnames()[0].split("/")[0]
        readme_member = tf.extractfile(f"{root}/README.txt")
        assert readme_member is not None
        readme = readme_member.read().decode()

    assert "python3 - <<'EOF'" in readme, "the README no longer ships a verification recipe"
    body = readme.split("python3 - <<'EOF'")[1].split("EOF")[0]
    recipe = "\n".join(line[4:] if line.startswith("    ") else line for line in body.splitlines())

    run = subprocess.run([sys.executable, "-c", recipe], cwd=str(tmp_path), capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    assert f"files: {built['manifest']['entry_count']}" in run.stdout
    assert "mismatched: none" in run.stdout


def test_the_readme_recipe_reports_a_tampered_file(tmp_path):
    """Mutation proof on the recipe itself: corrupt one member and the snippet
    a reader is handed must name it."""
    import subprocess  # noqa: PLC0415 - test-only

    built = _build()
    with tarfile.open(fileobj=io.BytesIO(built["tarball"])) as tf:
        root = tf.getnames()[0].split("/")[0]
        members = {}
        for info in tf.getmembers():
            extracted = tf.extractfile(info)
            assert extracted is not None
            members[info.name.split("/", 1)[1]] = extracted.read()
        readme = members["README.txt"].decode()
    members["web/pulse.json"] = b'{"tampered":true}'
    archive_path = os.path.join(str(tmp_path), "latest.tar.gz")
    with open(archive_path, "wb") as fh:
        fh.write(pa.build_tarball(members, root, 0))

    body = readme.split("python3 - <<'EOF'")[1].split("EOF")[0]
    recipe = "\n".join(line[4:] if line.startswith("    ") else line for line in body.splitlines())
    run = subprocess.run([sys.executable, "-c", recipe], cwd=str(tmp_path), capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    assert "web/pulse.json" in run.stdout
    assert "mismatched: none" not in run.stdout
