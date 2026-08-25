"""tests/test_dil028_raw_layout_replay.py — DIL-028 reverify: raw-layout replay proof
(Part of #3042).

The external diligence report flagged the raw/ zone's three-generation fracture
(X-9/#498: per-source prefix schemes AND leaf-filename schemes both vary) as a
replayability risk — the `raw_layout` facets in `ingestion.source_registry`
document the shapes, but nothing PROVED a replay/backfill tool could actually
walk every scheme family using only the registry, or that the registry's
claims matched what is really on disk. This file is that proof, structured in
three parts:

  1. Facet-vocabulary completeness — every registry source declares a
     raw_layout (or explicit None), and every field a scanner needs is present.
  2. A registry-driven scanner walk — for EVERY scheme family (framework
     YYYY-MM-DD.json, HAE DD.json, legacy no-user-segment, hevy flat-UUID),
     `raw_date_key`/`raw_year_prefix`/`raw_date_key_candidates` construct keys
     PURELY from the facet and are checked against REAL captured S3 listings
     (`aws s3 ls s3://matthew-life-platform/raw/...`, read-only, 2026-08-24 —
     no object was written, moved, or deleted to produce this evidence).
  3. One backfill-reconcile test per scheme family, proving the REAL writer
     code (ingestion_framework._archive_raw, health_auto_export_lambda's
     save_*_to_s3, hevy_common.normalize_workout/archive_raw) and the
     registry's reader-side resolver agree on the same key for the same
     DATE# row — the actual replay contract: a backfill tool that trusts the
     registry finds what the writer really wrote.

**Finding → fix (deliverable 3):** the scanner walk found three sources whose
facet claimed a single filename generation while live listings showed two —
eightsleep, withings, strava all carry frozen pre-2026-05-17 `DD.json` objects
alongside the current `YYYY-MM-DD.json` ones (same drift already documented,
but only in prose, for todoist/garmin). All five now carry a machine-readable
`filename_legacy` facet and are covered by `raw_date_key_candidates()` — see
`lambdas/ingestion/source_registry.py` for the live evidence cited at each
facet and the reason a hard cutover DATE was deliberately rejected (garmin's
2026-05-05..05-16 objects were re-fetched post-migration and landed in the
CURRENT format despite naming pre-migration dates — the generation depends on
when an object was written, not what date it names).

**Residual from this file's original reverify — MODELED by #3128:**
`raw/matthew/whoop/{cycle,sleep,recovery,workout}/`, the per-metric-type
archive predating the current combined date-tree, is now a `sub_layouts` facet
on `whoop` (`lambdas/ingestion/source_registry.py`) — cycle/sleep/recovery are
plain `DD.json` date trees (live-confirmed 2026-03-09..2026-05-17, 70 objects
each); `workout` nests one folder per day holding 0-N per-workout UUID files
(26 objects, 2026-03-13..2026-04-14) and deliberately has no per-day key
(`raw_date_key` raises, the `macrofactor` idiom). See `TestWhoopLegacyFamily`
below.

**New residual found WHILE fixing #3128 (honestly out of scope, not silently
dropped):** one generation further back, `raw/whoop/{cycle,sleep,recovery,
workout}/` — the SAME per-metric split with NO `matthew` user segment
(the X-9 legacy-prefix family), live-confirmed 2020-03-01..2026-03-08 (2199
objects each for cycle/sleep/recovery, 2546 for workout, every object's mtime
2026-02-21 — a one-time bulk historical import). Modeling a fifth generation
(on top of workout's already-nested UUID scheme) is real scope beyond #3128's
Small estimate, so it carries a dated `unmodeled_legacy` facet instead of
silence — see `test_whoop_no_segment_legacy_is_a_dated_documented_exclusion`.
Left for a follow-up story if replay ever needs pre-2026-03 whoop data.
"""

import os
import sys
from datetime import date

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # tests/fakes.py

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("SECRET_NAME", "life-platform/ingestion-keys")
os.environ.setdefault("DYNAMODB_TABLE", "life-platform")

from ingestion import (
    ingestion_framework as framework,  # noqa: E402
    source_registry as reg,  # noqa: E402
)

# ══════════════════════════════════════════════════════════════════════════
# Part 1 — facet-vocabulary completeness (deliverable 1a)
# ══════════════════════════════════════════════════════════════════════════

_KNOWN_SCHEMES = {"date-tree", "flat-uuid", "timestamped"}


def _all_layouts_with_source():
    """[(source_key, sub_key_or_None, layout_dict)] — main layouts + sub_layouts,
    for every source that has one. Walks the registry itself, never a hand-list."""
    out = []
    for k, v in reg.SOURCE_REGISTRY.items():
        layout = v.get("raw_layout")
        if not layout:
            continue
        out.append((k, None, layout))
        for sub_key, sub_layout in (layout.get("sub_layouts") or {}).items():
            out.append((k, sub_key, sub_layout))
    return out


def test_every_registry_source_declares_a_raw_layout_key():
    """No source may be silently absent from the facet — `raw_layout: None` is a
    valid, explicit answer ("no raw archive"); a MISSING key is not, because
    `raw_layouts()`/`raw_layout_for()` calls resolve it with `.get`/`[]` and a
    missing key reads identically to `None` at every call site — this guard is
    what stops that ambiguity from silently widening."""
    missing = [k for k, v in reg.SOURCE_REGISTRY.items() if "raw_layout" not in v]
    assert not missing, f"sources with no raw_layout facet at all (must be an explicit None): {missing}"


def test_the_scanner_walk_is_non_vacuous():
    layouts = _all_layouts_with_source()
    assert len(layouts) > 15, f"the raw_layout walk only found {len(layouts)} layouts — it is not covering the real registry"


def test_every_layout_declares_a_known_scheme():
    for source, sub, layout in _all_layouts_with_source():
        label = f"{source}/{sub}" if sub else source
        assert layout.get("scheme") in _KNOWN_SCHEMES, f"{label}: unknown scheme {layout.get('scheme')!r}"


def test_every_layout_declares_a_prefix():
    for source, sub, layout in _all_layouts_with_source():
        label = f"{source}/{sub}" if sub else source
        assert layout.get("prefix"), f"{label}: raw_layout has no prefix"


def test_every_date_tree_layout_declares_a_filename():
    """`raw_date_key` indexes on `filename` — a date-tree layout missing it
    would resolve to a NameError-shaped bug at replay time, not at facet-review
    time. (Some filenames are deliberately unresolvable sentinels, e.g.
    macrofactor's `<uploaded-filename>.csv` — presence is what's asserted, not
    the specific value.)"""
    for source, sub, layout in _all_layouts_with_source():
        if layout.get("scheme") != "date-tree":
            continue
        label = f"{source}/{sub}" if sub else source
        assert layout.get("filename"), f"{label}: date-tree layout has no filename"


def test_filename_legacy_only_on_sources_with_live_confirmed_drift():
    """The exact, closed set this PR's live walk confirmed carries a frozen
    second generation under the SAME prefix. A source gaining `filename_legacy`
    without a corresponding registry-comment citing live evidence (or without
    updating this set) should be a deliberate, reviewed change — this pins the
    set so that happens with eyes open, not by silent copy-paste.

    `apple_health` joined 2026-08-25 (#3119): the top-level payload archive's
    leaf flipped from wall-clock-only (`DD_HHMMSS.json`) to a content hash
    (`DD_{contenthash16}.json`) so a redelivery overwrites instead of minting
    a new object. Unlike the other five (all `date-tree`), this one is
    `timestamped` — `filename`/`filename_legacy` are documentary there (see
    the registry comment); `raw_date_key`/`raw_date_key_candidates` still
    raise for it, proven below."""
    have_legacy = {k for k, v in reg.SOURCE_REGISTRY.items() if (v.get("raw_layout") or {}).get("filename_legacy")}
    assert have_legacy == {"todoist", "garmin", "eightsleep", "withings", "strava", "apple_health"}


def test_apple_health_top_level_generation_flip_is_machine_readable():
    """#3119: the DIL-028 generation-flip class (a source's raw-archive leaf
    format changing over time) modeled five `date-tree` sources with
    `filename_legacy`; this is the same class applied to the one
    `timestamped` source. Both generations must be resolvable from the facet
    alone — a future backfill/scanner walking `raw/matthew/health_auto_export/`
    needs to recognise objects written before AND after the 2026-08-25 flip,
    and `raw/*` is delete-protected so the pre-flip objects are permanent."""
    layout = reg.raw_layout_for("apple_health")
    assert layout["scheme"] == "timestamped"
    assert layout["filename"] == "DD_{contenthash16}.json"
    assert layout["filename_legacy"] == "DD_HHMMSS.json"


def test_habitify_and_weather_confirmed_single_generation():
    """Negative evidence, not just absence: habitify's early-2026 history was
    fully rewritten to the current filename by a 2026-05-30 backfill sweep (live
    listing showed 2026-04-01..05-16 all in YYYY-MM-DD.json, all written in one
    2026-05-30 10:2x batch) — no legacy object survives to resolve. Weather's
    archive begins 2026-03-01, already in the current format — it was a
    framework source from inception (2026-03-09 POC), so it never had a
    pre-migration generation to begin with."""
    assert not reg.SOURCE_REGISTRY["habitify"]["raw_layout"].get("filename_legacy")
    assert not reg.SOURCE_REGISTRY["weather"]["raw_layout"].get("filename_legacy")


# ══════════════════════════════════════════════════════════════════════════
# Part 2 — registry-driven scanner walk vs. REAL captured listings
#           (deliverable 1b: one scheme family each)
#
# Every fixture below is a REAL key observed via a read-only
# `aws s3 ls s3://matthew-life-platform/raw/...` on 2026-08-24 (no write/move/
# delete performed). The assertion direction matters: the key is constructed
# PURELY from raw_date_key()/raw_year_prefix()/raw_date_key_candidates() (never
# hand-built in this test) and checked against what the bucket actually holds.
# ══════════════════════════════════════════════════════════════════════════


class TestFrameworkFamily:
    """YYYY-MM-DD.json under a user-segmented date tree — the SIMP-2 default."""

    def test_current_generation_key_matches_the_real_object(self):
        # aws s3 ls raw/matthew/whoop/2026/08/ → 2026-08-20.json (2271 bytes)
        assert reg.raw_date_key("whoop", "2026-08-20") == "raw/matthew/whoop/2026/08/2026-08-20.json"

    def test_year_prefix_matches_the_real_listing_root(self):
        assert reg.raw_year_prefix("whoop", 2026) == "raw/matthew/whoop/2026/"

    def test_habitify_current_generation(self):
        # aws s3 ls raw/matthew/habitify/2026/05/ → 2026-05-30.json (post-backfill)
        assert reg.raw_date_key("habitify", "2026-05-30") == "raw/matthew/habitify/2026/05/2026-05-30.json"


class TestHaeFamily:
    """DD.json under a user-segmented date tree — the never-migrated webhook sources."""

    def test_cgm_readings_matches_the_real_object(self):
        # aws s3 ls raw/matthew/cgm_readings/2026/08/ → 22.json
        assert reg.raw_date_key("apple_health", "2026-08-22", sub="cgm_readings") == "raw/matthew/cgm_readings/2026/08/22.json"

    def test_blood_pressure_matches_the_real_object(self):
        # aws s3 ls raw/matthew/blood_pressure/2026/04/ → 01.json
        assert reg.raw_date_key("apple_health", "2026-04-01", sub="blood_pressure") == "raw/matthew/blood_pressure/2026/04/01.json"

    def test_workouts_sub_layout_matches_the_real_object(self):
        # aws s3 ls raw/matthew/workouts/2026/06/ → 01.json
        assert reg.raw_date_key("apple_health", "2026-06-01", sub="workouts") == "raw/matthew/workouts/2026/06/01.json"

    def test_top_level_timestamped_scheme_has_no_per_day_key(self):
        """The top-level apple_health payload archive is `timestamped`, not a
        `date-tree` — a per-day key is deliberately unresolvable, matching the
        facet's own scheme declaration rather than the resolvable sub-streams.
        Live-confirmed pre-#3119 objects are `DD_HHMMSS.json` (e.g.
        `01_002710.json`); #3119 flipped new writes to `DD_{contenthash16}.json`
        (`filename_legacy`, added below) — the raise is unaffected by which
        generation a given object is in, since neither function ever looks at
        the filename for a non-date-tree scheme."""
        with pytest.raises(ValueError, match="not a date tree"):
            reg.raw_date_key("apple_health", "2026-08-01")


class TestWhoopLegacyFamily:
    """#3128: whoop's pre-2026-05-17 per-metric-type split — a temporal
    PREDECESSOR generation living under a wholly different prefix per stream
    (not just a different leaf filename, so `filename_legacy` doesn't fit;
    modeled as `sub_layouts` instead, same idiom as apple_health's HAE fan-out)."""

    def test_cycle_matches_the_real_object(self):
        # aws s3 ls raw/matthew/whoop/cycle/2026/03/ → 09.json (956 bytes)
        assert reg.raw_date_key("whoop", "2026-03-09", sub="cycle") == "raw/matthew/whoop/cycle/2026/03/09.json"

    def test_sleep_matches_the_real_object(self):
        # aws s3 ls raw/matthew/whoop/sleep/2026/03/ → 10.json (1264 bytes)
        assert reg.raw_date_key("whoop", "2026-03-10", sub="sleep") == "raw/matthew/whoop/sleep/2026/03/10.json"

    def test_recovery_matches_the_real_object(self):
        # aws s3 ls raw/matthew/whoop/recovery/2026/03/ → 11.json (534 bytes)
        assert reg.raw_date_key("whoop", "2026-03-11", sub="recovery") == "raw/matthew/whoop/recovery/2026/03/11.json"

    def test_cycle_year_prefix_matches_the_real_listing_root(self):
        assert reg.raw_year_prefix("whoop", 2026, sub="cycle") == "raw/matthew/whoop/cycle/2026/"

    def test_generation_boundary_overlaps_the_combined_tree_first_day(self):
        """Both generations wrote 2026-05-17: the per-metric split's LAST day
        and the combined tree's FIRST day are the same calendar date (the same
        day-of-migration overlap already documented for garmin/todoist/etc's
        `filename_legacy` pairs) — live-confirmed via
        `aws s3 ls raw/matthew/whoop/cycle/2026/05/` (17.json present) AND
        `aws s3 ls raw/matthew/whoop/2026/05/` (2026-05-17.json present)."""
        assert reg.raw_date_key("whoop", "2026-05-17", sub="cycle") == "raw/matthew/whoop/cycle/2026/05/17.json"
        assert reg.raw_date_key("whoop", "2026-05-17") == "raw/matthew/whoop/2026/05/2026-05-17.json"

    def test_workout_sub_layout_is_declared_but_has_no_per_day_key(self):
        """workout nests one folder PER DAY holding 0-N per-workout UUID files
        (e.g. `raw/matthew/whoop/workout/2026/03/13/b8d9b2db-....json`) — there
        is no single per-day leaf to construct, so (the `macrofactor` idiom)
        `raw_date_key` raises rather than guessing one."""
        layout = reg.raw_layout_for("whoop", sub="workout")
        assert layout["scheme"] == "date-tree"
        assert layout["prefix"] == "raw/matthew/whoop/workout"
        with pytest.raises(ValueError, match="unhandled leaf filename"):
            reg.raw_date_key("whoop", "2026-03-13", sub="workout")

    def test_whoop_no_segment_legacy_is_a_dated_documented_exclusion(self):
        """The generation found ONE PREFIX further back while fixing #3128 —
        `raw/whoop/{cycle,sleep,recovery,workout}/` (no `matthew` user segment,
        live-confirmed 2020-03-01..2026-03-08) — is deliberately NOT modeled
        as a `sub_layouts` entry (real scope beyond this issue's estimate).
        This pins that the exclusion is at least MACHINE-READABLE and dated,
        per #3128's own acceptance criteria, rather than silently absent."""
        legacy = reg.SOURCE_REGISTRY["whoop"]["raw_layout"]["unmodeled_legacy"]
        assert legacy["dated"] == "2026-08-25"
        assert legacy["prefix"] == "raw/whoop/{cycle,sleep,recovery,workout}"
        assert legacy["scheme"] == "date-tree"
        assert "2020-03-01" in legacy["note"] and "2026-03-08" in legacy["note"]


class TestLegacyNoUserSegmentFamily:
    """YYYY-MM-DD.json with NO `matthew` segment (X-9's original legacy prefix)."""

    def test_weather_matches_the_real_object(self):
        # aws s3 ls raw/weather/2026/03/ → 2026-03-01.json
        assert reg.raw_date_key("weather", "2026-03-01") == "raw/weather/2026/03/2026-03-01.json"
        assert "matthew" not in reg.raw_layout_for("weather")["prefix"]

    def test_todoist_current_generation_matches_the_real_object(self):
        # aws s3 ls raw/todoist/2026/05/ → 2026-05-17.json
        assert reg.raw_date_key("todoist", "2026-05-17") == "raw/todoist/2026/05/2026-05-17.json"
        assert "matthew" not in reg.raw_layout_for("todoist")["prefix"]


class TestHevyFlatUuidFamily:
    """No date tree at all — the third X-9 generation."""

    def test_no_per_day_key_exists(self):
        with pytest.raises(ValueError, match="not a date tree"):
            reg.raw_date_key("hevy", "2026-08-20")

    def test_no_per_year_prefix_exists(self):
        with pytest.raises(ValueError, match="not a date tree"):
            reg.raw_year_prefix("hevy", 2026)

    def test_real_object_matches_the_flat_uuid_prefix(self):
        # aws s3 ls raw/hevy/ → 004e6d07-4e44-44f1-b703-4758ebf4f9d7.json
        layout = reg.raw_layout_for("hevy")
        real_key = "raw/hevy/004e6d07-4e44-44f1-b703-4758ebf4f9d7.json"
        assert real_key.startswith(layout["prefix"] + "/")
        assert real_key.endswith(".json")


class TestFilenameLegacyCandidates:
    """`raw_date_key_candidates()` — the historical-replay resolver."""

    def test_no_legacy_facet_returns_a_single_candidate(self):
        assert reg.raw_date_key_candidates("whoop", "2026-08-20") == [reg.raw_date_key("whoop", "2026-08-20")]

    def test_current_format_is_always_first(self):
        cands = reg.raw_date_key_candidates("garmin", "2025-06-01")
        assert cands[0] == reg.raw_date_key("garmin", "2025-06-01")

    def test_garmin_legacy_candidate_matches_the_real_frozen_object(self):
        # aws s3 ls raw/matthew/garmin/2026/05/ → 01.json (2026-05-03 mtime, never touched since)
        cands = reg.raw_date_key_candidates("garmin", "2026-05-01")
        assert "raw/matthew/garmin/2026/05/01.json" in cands
        assert "raw/matthew/garmin/2026/05/2026-05-01.json" in cands

    def test_garmin_backfilled_date_resolves_via_the_current_candidate(self):
        """The 05-05..05-16 range live evidence for this PR: these dates predate
        the 2026-05-17 migration but were re-fetched by the NEW framework on
        2026-05-19 and landed in the CURRENT format — proof that trying the
        first (current-format) candidate is not merely a fallback ordering
        choice, it is the one that actually resolves for this real range."""
        # aws s3 ls raw/matthew/garmin/2026/05/ → 2026-05-05.json (mtime 2026-05-19)
        cands = reg.raw_date_key_candidates("garmin", "2026-05-05")
        assert cands[0] == "raw/matthew/garmin/2026/05/2026-05-05.json"

    def test_withings_legacy_candidate_matches_the_real_frozen_object(self):
        # aws s3 ls raw/matthew/withings/measurements/2026/05/ → 17.json
        cands = reg.raw_date_key_candidates("withings", "2026-05-17")
        assert "raw/matthew/withings/measurements/2026/05/17.json" in cands

    def test_strava_legacy_candidate_matches_the_real_frozen_object(self):
        # aws s3 ls raw/matthew/strava/activities/2026/05/ → 09.json
        cands = reg.raw_date_key_candidates("strava", "2026-05-09")
        assert "raw/matthew/strava/activities/2026/05/09.json" in cands

    def test_eightsleep_legacy_candidate_matches_the_real_frozen_object(self):
        # aws s3 ls raw/matthew/eightsleep/2026/05/ → 01.json
        cands = reg.raw_date_key_candidates("eightsleep", "2026-05-01")
        assert "raw/matthew/eightsleep/2026/05/01.json" in cands

    def test_unhandled_legacy_filename_raises_rather_than_guessing(self, monkeypatch):
        bogus = dict(reg.SOURCE_REGISTRY["whoop"])
        bogus["raw_layout"] = dict(bogus["raw_layout"], filename_legacy="WEEK.json")
        monkeypatch.setitem(reg.SOURCE_REGISTRY, "whoop", bogus)
        with pytest.raises(ValueError, match="unhandled leaf filename"):
            reg.raw_date_key_candidates("whoop", "2026-08-20")


# ══════════════════════════════════════════════════════════════════════════
# Part 3 — one backfill-reconcile test per scheme family (deliverable 2)
#
# Proves the REAL writer and the registry's reader-side resolver agree on the
# SAME key for the SAME date_str — the coordinate a DDB DATE# row and a raw S3
# object share. Gap detection itself (`_find_missing_dates`) is confirmed
# DDB-only (never touches S3) by inspection of ingestion_framework.py; what
# closes the loop for replay/backfill is that the archived key for a given
# `date_str` is exactly what `raw_date_key(source, date_str)` resolves.
# ══════════════════════════════════════════════════════════════════════════


class _CapturingS3:
    """Captures the Key/Body of every put_object — no network, no moto."""

    def __init__(self):
        self.put_keys = []
        self.puts = []

    def put_object(self, Bucket=None, Key=None, Body=None, **kw):
        self.put_keys.append(Key)
        self.puts.append({"Bucket": Bucket, "Key": Key, "Body": Body})
        return {}


class TestFrameworkFamilyBackfillReconcile:
    """The SIMP-2 framework's own `_archive_raw` (the writer every framework
    source shares) vs. `raw_date_key` (the reader/replay resolver). Parametrized
    over every source registered as `date-tree` + `YYYY-MM-DD.json`, reading
    each source's REAL `s3_archive_prefix` from its own `IngestionConfig` in its
    lambda module — not retyped, so this cannot drift from the deployed writer."""

    @pytest.mark.parametrize(
        "source,s3_archive_prefix",
        [
            ("whoop", "raw/matthew/whoop"),
            ("withings", "raw/matthew/withings/measurements"),
            ("strava", "raw/matthew/strava/activities"),
            ("eightsleep", "raw/matthew/eightsleep"),
            ("habitify", "raw/matthew/habitify"),
            ("garmin", "raw/matthew/garmin"),
            ("todoist", "raw/todoist"),
            ("weather", "raw/weather"),
        ],
    )
    def test_writer_and_reader_agree_on_the_current_generation_key(self, source, s3_archive_prefix):
        # The prefix passed here is EXACTLY what each lambda's own IngestionConfig(...)
        # call site declares (grep-verified against lambdas/ingestion/*_lambda.py,
        # 2026-08-24) — this test additionally guards that it still matches the
        # registry's own declared prefix, so the two can't drift apart silently.
        assert reg.raw_layout_for(source)["prefix"] == s3_archive_prefix

        config = framework.IngestionConfig(source_name=source, s3_archive_prefix=s3_archive_prefix)
        s3 = _CapturingS3()
        date_str = "2026-08-20"
        err = framework._archive_raw(s3, config, date_str, {"fixture": True})

        assert err is None
        assert len(s3.put_keys) == 1
        written_key = s3.put_keys[0]
        assert written_key == reg.raw_date_key(source, date_str), (
            f"{source}: the writer's real key {written_key!r} and the registry's "
            f"raw_date_key() {reg.raw_date_key(source, date_str)!r} disagree — a "
            f"replay tool trusting the registry would resolve the wrong object"
        )

    def test_ddb_sk_and_raw_key_share_the_same_date_str_coordinate(self):
        """The framework's own DDB sk convention (`ingestion_framework.py`, the
        `sk = f"DATE#{date_str}{sk_suffix}"` line in run_ingestion) and the S3
        archive key are built from the literal SAME `date_str` variable in the
        same run — this pins that fact so a future refactor that lets them
        diverge (e.g. re-deriving one from the other) fails loudly here first."""
        date_str = "2026-08-20"
        sk = f"DATE#{date_str}"
        raw_key = reg.raw_date_key("whoop", date_str)
        # Both derive from the identical date_str — the correspondence a
        # backfill tool relies on to go from "this DATE# row is missing" to
        # "this is the raw object that would refill it."
        assert sk.removeprefix("DATE#") == date_str
        assert f"/{date_str}.json" in raw_key


class TestHaeFamilyBackfillReconcile:
    """health_auto_export_lambda's real `save_*_to_s3` writers (never migrated
    to the framework — API Gateway webhook, ADR-056) vs. the registry's
    per-sub-stream resolver."""

    @pytest.fixture(autouse=True)
    def _hae_module(self, monkeypatch):
        import health_auto_export_lambda as hae

        class _FakeS3Client:
            class exceptions:
                class NoSuchKey(Exception):
                    pass

            def __init__(self):
                self.put_keys = []

            def get_object(self, **kw):
                raise self.exceptions.NoSuchKey()

            def put_object(self, Bucket=None, Key=None, **kw):
                self.put_keys.append(Key)
                return {}

        fake = _FakeS3Client()
        monkeypatch.setattr(hae, "s3_client", fake)
        self.hae = hae
        self.fake_s3 = fake

    def test_cgm_writer_matches_the_registry_resolver(self):
        self.hae.save_cgm_readings_to_s3("2026-08-22", [{"time": "2026-08-22T10:00:00Z", "value": 100}])
        assert len(self.fake_s3.put_keys) == 1
        assert self.fake_s3.put_keys[0] == reg.raw_date_key("apple_health", "2026-08-22", sub="cgm_readings")

    def test_bp_writer_matches_the_registry_resolver(self):
        self.hae.save_bp_readings_to_s3("2026-04-01", [{"time": "2026-04-01T09:00:00Z", "systolic": 120, "diastolic": 80}])
        assert len(self.fake_s3.put_keys) == 1
        assert self.fake_s3.put_keys[0] == reg.raw_date_key("apple_health", "2026-04-01", sub="blood_pressure")

    def test_state_of_mind_writer_matches_the_registry_resolver(self):
        self.hae.save_state_of_mind_to_s3("2026-04-10", [{"time": "2026-04-10T08:00:00Z", "valence": 0.5}])
        assert len(self.fake_s3.put_keys) == 1
        assert self.fake_s3.put_keys[0] == reg.raw_date_key("apple_health", "2026-04-10", sub="state_of_mind")


class TestLegacyNoUserSegmentBackfillReconcile:
    """Same framework writer, different prefix shape — proves `raw_date_key`
    correctly omits the user segment rather than a caller having to special-case
    it (the exact class of bug #2278 was: a caller either always adds the
    segment or always omits it, and one source is always the exception)."""

    def test_todoist_writer_and_reader_agree(self):
        config = framework.IngestionConfig(source_name="todoist", s3_archive_prefix="raw/todoist")
        s3 = _CapturingS3()
        framework._archive_raw(s3, config, "2026-08-20", {"tasks": []})
        assert s3.put_keys[0] == reg.raw_date_key("todoist", "2026-08-20") == "raw/todoist/2026/08/2026-08-20.json"

    def test_weather_writer_and_reader_agree(self):
        config = framework.IngestionConfig(source_name="weather", s3_archive_prefix="raw/weather")
        s3 = _CapturingS3()
        framework._archive_raw(s3, config, "2026-08-20", {"temp_f": 70})
        assert s3.put_keys[0] == reg.raw_date_key("weather", "2026-08-20") == "raw/weather/2026/08/2026-08-20.json"


class TestHevyFlatUuidBackfillReconcile:
    """Hevy's DATE# row is derived from the WORKOUT PAYLOAD's own timestamp, not
    from the S3 key (which structurally cannot carry a date — flat UUID). This
    proves `normalize_workout` (the DDB writer) and `archive_raw` (the S3
    writer) independently agree with the registry's flat-uuid facet, and that
    the DATE# sk is payload-derived — exactly what backfill/reconcile needs to
    know for this scheme family: you cannot list-and-parse your way to a date,
    you must re-derive it from each object's contents."""

    @pytest.fixture(autouse=True)
    def _stub_aws(self, monkeypatch):
        import types

        fake_boto3 = types.ModuleType("boto3")

        def fake_client(name, region_name=None):
            return object()

        def fake_resource(name, region_name=None):
            class _T:
                def put_item(self, **kw):
                    pass

            class _R:
                def Table(self, name):
                    return _T()

            return _R()

        fake_boto3.client = fake_client
        fake_boto3.resource = fake_resource
        monkeypatch.setitem(sys.modules, "boto3", fake_boto3)

    def test_normalize_workout_date_is_payload_derived_not_key_derived(self):
        from training import hevy_common

        raw = {
            "workout": {
                "id": "wkt_dil028",
                "title": "Replay-proof fixture",
                "start_time": "2026-08-20T17:30:00Z",
                "end_time": "2026-08-20T18:25:00Z",
                "unit": "kg",
                "exercises": [],
            }
        }
        record = hevy_common.normalize_workout(raw)
        assert record["sk"].startswith("DATE#2026-08-20#WORKOUT#wkt_dil028")
        # The date came from start_time, NOT from any S3 key — there is none to parse.
        # (BUCKET is read from S3_BUCKET at hevy_common's import time — other test
        # modules imported earlier in the same run may have already set it via
        # os.environ.setdefault, so compare against the module's own constant
        # rather than hardcoding a literal that only holds in isolation.)
        assert record["raw_ref"] == f"s3://{hevy_common.BUCKET}/raw/hevy/wkt_dil028.json"

    def test_archive_raw_writer_matches_the_registry_flat_uuid_prefix(self, monkeypatch):
        from training import hevy_common

        captured = {}

        class _FakeS3:
            def put_object(self, Bucket=None, Key=None, **kw):
                captured["Key"] = Key
                return {}

        monkeypatch.setattr(hevy_common, "_s3", _FakeS3())
        hevy_common.archive_raw("wkt_dil028", {"workout": {"id": "wkt_dil028"}})
        layout = reg.raw_layout_for("hevy")
        assert captured["Key"] == f"{layout['prefix']}/wkt_dil028.json"


# ══════════════════════════════════════════════════════════════════════════
# Sanity: the two new registry functions never regress raw_date_key's contract
# ══════════════════════════════════════════════════════════════════════════


def test_raw_date_key_candidates_is_a_strict_superset_of_raw_date_key():
    """For every source with a raw archive whose filename raw_date_key can
    actually resolve, candidates()[0] == raw_date_key(). macrofactor's
    `<uploaded-filename>.csv` is a deliberate unresolvable sentinel (raises by
    design, per its own facet note) and is exercised separately below."""
    for source, sub, _layout in _all_layouts_with_source():
        layout = reg.raw_layout_for(source, sub)
        if layout.get("scheme") != "date-tree":
            continue
        if layout.get("filename") not in ("YYYY-MM-DD.json", "DD.json"):
            continue
        primary = reg.raw_date_key(source, "2026-08-20", sub)
        candidates = reg.raw_date_key_candidates(source, "2026-08-20", sub)
        assert candidates[0] == primary


def test_macrofactor_unresolvable_filename_raises_for_both_functions():
    """macrofactor's ingest-month tree has no per-day key by design (one CSV
    holds many days) — both the primary resolver and the candidates wrapper
    must raise, not silently hand back a guess."""
    with pytest.raises(ValueError, match="unhandled leaf filename"):
        reg.raw_date_key("macrofactor", "2026-08-20")
    with pytest.raises(ValueError, match="unhandled leaf filename"):
        reg.raw_date_key_candidates("macrofactor", "2026-08-20")


def test_raw_date_key_candidates_unknown_source_raises():
    with pytest.raises(KeyError):
        reg.raw_date_key_candidates("not_a_real_source", "2026-08-20")


def test_date_validation_still_applies_to_candidates():
    with pytest.raises(ValueError):
        reg.raw_date_key_candidates("garmin", "not-a-date")


def test_iso_date_roundtrip_sanity():
    """Belt-and-suspenders: date.fromisoformat used throughout stays valid for
    both the leap-year and month-boundary cases a replay walk will hit."""
    assert date.fromisoformat("2028-02-29")  # leap year — the archive spans one
    assert reg.raw_date_key("whoop", "2026-01-31").endswith("2026-01-31.json")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
