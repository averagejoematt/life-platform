"""ER-06 — PII-to-public-surface guarantee (offline, GATING).

Editorial guardrails + docs/DATA_GOVERNANCE.md are *policy*; this is the
structural test that the published static site can't leak them. Runs the same
scanner the deploy uses (deploy/pii_surface_guard.py) over the committed `site/`
tree and fails on any guarded string or PII class. Offline (no AWS) so CI gates.

The scanner runs again, fail-closed, inside `sync_site_to_s3.sh` before the S3
sync — this test is the CI half of the same gate.
"""

import json
import os
import subprocess
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "deploy"))
import pii_surface_guard as guard  # noqa: E402

_SITE = os.path.join(_ROOT, "site")


def test_live_site_is_clean():
    """The committed public surface must have no guarded strings or PII.
    If this fails, a real leak is about to (or did) ship — fix the artifact,
    do not weaken the guard."""
    res = guard.scan_site(_SITE)
    assert not res["violations"], "PII/guardrail violations on the public surface:\n" + "\n".join(
        f"  {f}: [{arm}] {detail}" for f, arm, detail in res["violations"]
    )


def test_blocked_vice_keyword_is_caught():
    """Load-bearing: a policy-blocked term in a published artifact must fail.
    The literal term is pulled from the policy file, not written here."""
    kw = guard._blocked_vice_keywords()[0]
    hits = guard.scan_text(f"A 30-day challenge about {kw} for good.", vice=[kw], literals=[])
    assert any(arm == "blocked-vice" for arm, _ in hits)


def test_structural_pii_is_caught():
    """Load-bearing: SSN-shaped numbers and foreign emails fail."""
    ssn = guard.scan_text("SSN 123-45-6789 on file.", vice=[], literals=[])
    assert any(arm == "pii-ssn" for arm, _ in ssn)
    email = guard.scan_text("Reach me at someone.personal@gmail.com anytime.", vice=[], literals=[])
    assert any(arm == "pii-email" for arm, _ in email)


def test_allowlisted_email_passes():
    """The site's own contact + placeholders must NOT trip the email arm."""
    ok = guard.scan_text("Contact security@mattsusername.com or type your@email.com.", vice=[], literals=[])
    assert not any(arm == "pii-email" for arm, _ in ok)


def test_literal_denylist_arm_when_provided():
    """When a personal denylist is supplied, a guarded literal fails — and the
    violation never echoes the literal back."""
    hits = guard.scan_text("An aside mentioning Acme Corp in passing.", vice=[], literals=["acme corp"])
    assert any(arm == "literal-denylist" for arm, _ in hits)
    assert all("acme" not in detail.lower() for _, detail in hits)


# ═══ Endpoint arm (#1945) — the /api/* surface, offline half ═══════════════════
#
# The static walk above never touched the ~130 live /api/* payloads (the #1943
# genome finding shipped through exactly that gap). These tests are the CI wiring
# for the guard's endpoint arm: same file, same job, gating.


def test_endpoint_arm_offline_scan_is_clean_and_covers_the_route_set():
    """The gate itself: every committed shape snapshot is key-tell clean, AND every
    AST-discovered route is either scanned or carries a reasoned exemption — an
    endpoint never scanned is a violation, not a silent pass (#1935 honesty class).
    A newly registered route with neither a snapshot nor an exemption fails HERE."""
    res = guard.scan_schema_snapshots()
    assert res["files"] >= 50, f"suspiciously few shape snapshots scanned ({res['files']}) — a vacuous scan is not a pass"
    assert not res["violations"], "PII tells (or unscanned routes) on the /api/* surface:\n" + "\n".join(
        f"  {w}: [{arm}] {detail}" for w, arm, detail in res["violations"]
    )


def test_endpoint_arm_coverage_check_fires_on_uncovered_routes(tmp_path):
    """Negative proof of the coverage direction: scanning a snapshot dir that
    covers almost nothing must report the real router's routes as
    endpoint-not-scanned — the check cannot go vacuous."""
    (tmp_path / "api_stub.json").write_text(json.dumps({"path": "/api/vitals", "shape": {"type": "object", "keys": {}}}))
    (tmp_path / "_exemptions.json").write_text("{}")
    res = guard.scan_schema_snapshots(snapshot_dir=str(tmp_path))
    not_scanned = [w for w, arm, _ in res["violations"] if arm == "endpoint-not-scanned"]
    assert len(not_scanned) > 50, "expected the uncovered real route set to red the offline arm"


def test_endpoint_arm_fires_on_a_planted_genetic_tell():
    """Regression guard (#1945 AC4): a payload carrying the #1943 leak class must
    red — both as a value tell and as a key tell."""
    payload = json.dumps({"snps": [{"rsid": "rs429358", "genotype": "C/T", "note": "heterozygous"}]})
    arms = {arm for arm, _ in guard.scan_endpoint_payload(payload, vice=[], literals=[])}
    assert "pii-genetic" in arms, "value-level genetic tell (rsID/genotype) must fire"
    assert "pii-genetic-key" in arms, "key-level genetic tell (rsid field) must fire"


def test_endpoint_arm_fires_on_a_planted_birth_year_field():
    """PhenoAge Option A: bio-age is public, chronological age NEVER. A payload
    that starts carrying a birth-year/DOB field must red."""
    hits = guard.scan_endpoint_payload(json.dumps({"profile": {"birth_year": 1985}}), vice=[], literals=[])
    assert any(arm == "pii-age-key" for arm, _ in hits)
    hits = guard.scan_endpoint_payload('{"bio": "date of birth: 1985-03-02"}', vice=[], literals=[])
    assert any(arm == "pii-age" for arm, _ in hits)


def test_endpoint_arm_allows_aggregate_genetic_counts_and_public_age_scores():
    """The sanctioned shapes must NOT trip: aggregate SNP counts (facts about the
    analysis, #1943) and the public fitness/bio-age scores (Option A keeps those)."""
    ok = json.dumps({"genome": {"total_snps": 111, "snp_count": 8}, "vitals": {"fitness_age": 44, "bio_age": 39.2, "phenoage": 39.2}})
    hits = [
        h for h in guard.scan_endpoint_payload(ok, vice=[], literals=[]) if h[0].startswith("pii-genetic") or h[0].startswith("pii-age")
    ]
    assert hits == [], f"sanctioned aggregate/public-age shapes must pass, got {hits}"


def test_card_arm_ignores_float_mantissas_but_still_catches_a_card():
    """#1945 field finding: /api/character_receipt's xp_delta float carries 16
    consecutive mantissa digits — a number's tail, not a card. The tightened
    regex must skip it while a bare 16-digit number still fires."""
    clean = guard.scan_text('{"xp_delta": 1.5714285714285714}', vice=[], literals=[])
    assert not any(arm == "pii-card" for arm, _ in clean)
    dirty = guard.scan_text("card 4111111111111111 on file", vice=[], literals=[])
    assert any(arm == "pii-card" for arm, _ in dirty)


def test_card_arm_ignores_doi_suffixes_but_not_a_card_beside_one():
    """#1983: publisher DOI suffixes can be exactly 16 digits (Sage's
    10.1177/0265407512453827). A DOI is a citation, and citations are the point of
    the experiment library — but the masking is syntactic (`10.NNNN/` required), so
    a real card sitting in the same document still fires."""
    doi = '{"source_url": "https://doi.org/10.1177/0265407512453827"}'
    assert not any(arm == "pii-card" for arm, _ in guard.scan_text(doi, vice=[], literals=[]))
    both = doi + " card 4111111111111111 on file"
    assert any(arm == "pii-card" for arm, _ in guard.scan_text(both, vice=[], literals=[]))
    # A bare 16-digit run that merely LOOKS DOI-adjacent is not masked.
    assert any(arm == "pii-card" for arm, _ in guard.scan_text("doi 0265407512453827", vice=[], literals=[]))


def test_live_arm_unreachable_endpoint_is_a_violation_never_a_pass():
    """#1935: an endpoint the arm planned to scan but could not read must land as
    an endpoint-not-scanned violation — fail-closed, no silent pass tally."""
    res = guard.scan_endpoints("https://unit-test.invalid", fetcher=lambda p: (None, None, "connection refused (unit stub)"))
    assert res["scanned"] == []
    assert res["violations"], "an unreadable surface must red, not pass"
    assert all(arm == "endpoint-not-scanned" for _, arm, _ in res["violations"])


def test_live_arm_fires_on_a_planted_payload_and_never_fetches_post_only_routes():
    """Two properties through one stubbed sweep: (a) a planted tell in a fetched
    payload reds; (b) POST-only routes — derived from the router's own AST method
    sets, not a hand-list — are never fetched (the /api/cohort_submit 405 class)."""
    fetched = []

    def stub_fetch(fetch_path):
        fetched.append(fetch_path)
        return 200, {"user": {"birth_year": 1985}, "snp": "rs429358"}, None

    res = guard.scan_endpoints("https://unit-test.invalid", fetcher=stub_fetch)
    arms = {arm for _, arm, _ in res["violations"]}
    assert "pii-age-key" in arms and "pii-genetic" in arms
    post_only_skips = [p for p, cat in res["skipped"].items() if "AST-derived" in cat]
    assert "/api/cohort_submit" in post_only_skips and "/api/replicate_certify" in post_only_skips
    assert not (set(post_only_skips) & {f.split("?")[0] for f in fetched}), "a POST-only route must never be probed"


def test_guard_genetic_vocabulary_covers_the_platform_definition():
    """One definition of 'genetic identifier' for the platform: the guard's tell
    regexes must keep matching the canonical probe set that
    lambdas/web/site_api_vitals._GENETIC_TEXT_RE and
    tests/test_public_genetic_privacy_absolute._GENETIC_KEY_RE encode — drift here
    means the arms silently diverged from the labs/genome absolutes."""
    for probe in ("genotype", "rs429358", "allele"):
        assert guard._GENETIC_VALUE_RE.search(probe), f"value tell must match {probe!r}"
    for key in ("rsid", "genotype", "snp_id", "allele", "gene", "genes", "gene_name", "rs123"):
        assert guard._GENETIC_KEY_RE.search(key), f"key tell must match key {key!r}"
    for key in ("total_snps", "snp_count", "n_snps"):
        assert key in guard._GENETIC_AGGREGATE_KEYS
    for benign in ("generated_at", "genesis", "risk_summary", "hours", "first_seen"):
        assert not guard._GENETIC_KEY_RE.search(benign), f"benign key {benign!r} must not trip the genetic arm"
    for benign in ("fitness_age", "bio_age", "phenoage", "average", "message_age_seconds"):
        assert not guard._CHRON_AGE_KEY_RE.search(benign), f"benign key {benign!r} must not trip the age arm"


def test_denylist_is_not_committed_in_cleartext():
    """The repo is PUBLIC: the personal denylist must never be tracked by git.
    Only a values-free example template may be committed."""
    tracked = subprocess.run(
        ["git", "ls-files", "config/pii_denylist.local.json"], cwd=_ROOT, capture_output=True, text=True
    ).stdout.strip()
    assert tracked == "", "config/pii_denylist.local.json must be gitignored, never committed"
    example = os.path.join(_ROOT, "config", "pii_denylist.example.json")
    assert os.path.exists(example), "ship a values-free config/pii_denylist.example.json template"
    with open(example) as f:
        terms = [t for t in json.load(f).get("terms", []) if not t.startswith("<")]
    assert terms == [], "the example denylist must contain no real values (placeholders only)"


# ═══ Repo-hygiene arm (#2370) — tracked JSON is itself a public surface ═════════
#
# The repo is PUBLIC, so a tracked config/seed JSON that carries a blocked-category
# keyword IS the leak (the denylist inversion #2370 scrubbed). The unit suite runs
# on the NEUTRAL fixture vocabulary conftest injects; the real-vocabulary scans
# below re-resolve the channel (pre-conftest CI secret value, local file, or S3)
# and SKIP VISIBLY when no source exists — they run armed in ci-lint (secret) and
# on owner machines (content_filter.local.json), plus fail-closed at deploy time
# (sync_site_to_s3.sh --require-vice).

import conftest as _conftest  # noqa: E402 — REAL_CONTENT_FILTER_ENV preserved pre-injection
import pytest  # noqa: E402


def _real_channel_vocab(monkeypatch):
    """Resolve the REAL vocabulary (not the neutral fixture): restore the
    pre-conftest env value, else fall through to local file / S3. Returns [] when
    no real source exists (caller skips visibly)."""
    sys.path.insert(0, os.path.join(_ROOT, "lambdas"))
    from privacy import content_filter_channel

    if _conftest.REAL_CONTENT_FILTER_ENV:
        monkeypatch.setenv("CONTENT_FILTER_JSON", _conftest.REAL_CONTENT_FILTER_ENV)
    else:
        monkeypatch.delenv("CONTENT_FILTER_JSON", raising=False)
    content_filter_channel.reset_cache()
    try:
        return content_filter_channel.blocked_keywords(require=False)
    finally:
        pass


@pytest.fixture
def _restore_channel_cache():
    yield
    sys.path.insert(0, os.path.join(_ROOT, "lambdas"))
    from privacy import content_filter_channel

    content_filter_channel.reset_cache()


def test_tracked_json_surface_is_clean_with_real_vocabulary(monkeypatch, _restore_channel_cache):
    """The gate itself (#2370 AC): no git-tracked JSON file carries a
    blocked-category keyword. Runs with the REAL vocabulary when a channel source
    exists; otherwise skips visibly (armed in ci-lint via the secret)."""
    vocab = _real_channel_vocab(monkeypatch)
    if not vocab:
        pytest.skip("no real content-filter channel source — armed in ci-lint (secret) / locally (local.json)")
    res = guard.scan_tracked_json(vocab=vocab)
    assert res["vice_arm"] == "on"
    assert res["files"] > 100, f"suspiciously few tracked JSON files scanned ({res['files']})"
    assert not res["violations"], "tracked JSON carries blocked-category keyword(s):\n" + "\n".join(
        f"  {f}: [{arm}] {detail}" for f, arm, detail in res["violations"]
    )


def test_live_site_is_vice_clean_with_real_vocabulary(monkeypatch, _restore_channel_cache):
    """The committed site/ tree scanned against the REAL vocabulary (the neutral
    fixture scan in test_live_site_is_clean covers the structural arms)."""
    vocab = _real_channel_vocab(monkeypatch)
    if not vocab:
        pytest.skip("no real content-filter channel source — armed in ci-lint (secret) / locally (local.json)")
    res = guard.scan_site(_SITE)
    vice_hits = [v for v in res["violations"] if v[1] == "blocked-vice"]
    assert res["vice_arm"] == "on"
    assert not vice_hits, f"{len(vice_hits)} blocked-category hit(s) on the committed site tree (terms masked)"


def test_tracked_arm_fires_on_a_seeded_violation(tmp_path):
    """Mutation proof (#2370 AC: 'a screen whose suite passes with the screen
    deleted guards nothing'): seed a JSON file with a (neutral) vocabulary term
    and prove the arm actually fires — and that the violation never echoes the
    term back (public CI logs)."""
    dirty = tmp_path / "seed.json"
    dirty.write_text(json.dumps({"habit": "No fizzlewick"}))
    clean = tmp_path / "clean.json"
    clean.write_text(json.dumps({"habit": "No sugar"}))
    vocab = ["fizzlewick", "zzq"]

    res = guard.scan_tracked_json(files=[str(dirty)], vocab=vocab)
    assert res["violations"], "the repo-hygiene arm did not fire on a seeded violation — the screen guards nothing"
    for _f, arm, detail in res["violations"]:
        assert arm == "tracked-blocked-vice"
        assert "fizzlewick" not in detail.lower(), "violation output must never echo the term"

    res_clean = guard.scan_tracked_json(files=[str(clean)], vocab=vocab)
    assert res_clean["violations"] == [], "the arm fired on a clean file — false positive"


def test_tracked_arm_catches_zero_width_and_spaced_obfuscation(tmp_path):
    """The obfuscation classes the runtime scrub defends against must not slip
    a tracked file past the repo-hygiene arm either: zero-width-split and
    punctuation-split long terms are caught on the normalized pass."""
    zwsp = tmp_path / "zwsp.json"
    # ensure_ascii=False keeps the REAL zero-width char in the file (the escaped
    # \\u form is a different, out-of-scope obfuscation — a human pasting a term
    # into a config produces the raw char).
    zwsp.write_text(json.dumps({"note": "about fizz​lewick today"}, ensure_ascii=False), encoding="utf-8")
    spaced = tmp_path / "spaced.json"
    spaced.write_text(json.dumps({"note": "f-i-z-z-l-e-w-i-c-k is the topic"}))
    for seeded in (zwsp, spaced):
        res = guard.scan_tracked_json(files=[str(seeded)], vocab=["fizzlewick"])
        assert res["violations"], f"obfuscated seeded term not caught in {seeded.name}"


def test_tracked_arm_skips_visibly_without_vocabulary():
    """No vocabulary → the arm reports itself SKIPPED (never an empty-vocabulary
    'pass' — #2203 class)."""
    res = guard.scan_tracked_json(files=["does-not-matter.json"], vocab=[])
    assert res["vice_arm"] == "skipped"
    assert res["violations"] == []


def test_site_scan_requires_vice_arm_on_the_deploy_path(monkeypatch, _restore_channel_cache):
    """--require-vice fail-closed proof: with NO channel source, the deploy-path
    form raises instead of shipping with the vice arm dark."""
    sys.path.insert(0, os.path.join(_ROOT, "lambdas"))
    from privacy import content_filter_channel

    monkeypatch.delenv("CONTENT_FILTER_JSON", raising=False)
    monkeypatch.setattr(content_filter_channel, "_from_local_file", lambda: None)
    monkeypatch.setattr(content_filter_channel, "_from_s3_boto", lambda bucket: None)
    monkeypatch.setattr(content_filter_channel, "_from_s3_cli", lambda bucket: None)
    content_filter_channel.reset_cache()
    with pytest.raises(content_filter_channel.ContentFilterUnavailable):
        guard.scan_site(_SITE, require_vice=True)
    # The permissive form reports the arm skipped instead (offline CI posture).
    res = guard.scan_site(_SITE, require_vice=False)
    assert res["vice_arm"] == "skipped"
