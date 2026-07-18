"""Regression guard for the experiment library dedup (#1247).

The public experiment catalog (`config/experiment_library.json`, mirrored byte-for-byte
to `site/config/experiment_library.json`) was padded to 71 entries by undeduplicated bulk
expansions that introduced near-duplicate pairs — the same pre-registered design under two
ids. A catalog whose credibility rests on each entry being a distinct design cannot carry
copy-paste twins.

#1247 merged the four cited pairs, keeping the better-specified / better-cited variant of
each and dropping the sparse bulk-expansion twin:

    magnesium-before-bed   (kept)  vs  magnesium-sleep       (dropped)
    no-alcohol-30-days     (kept)  vs  eliminate-alcohol-30d (dropped)
    sauna-2x-week          (kept)  vs  sauna-2x-week-6wk     (dropped)
    gratitude-log          (kept)  vs  gratitude-journal     (dropped)

These tests are deliberately non-vacuous: run against the *pre-fix* catalog (both members
of every pair present) `test_merged_pairs_do_not_coexist` and `test_removed_ids_absent`
raise. See the module docstring proof in the PR description.
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ROOT_COPY = ROOT / "config" / "experiment_library.json"
SITE_COPY = ROOT / "site" / "config" / "experiment_library.json"

# The four merged pairs: (kept_id, dropped_id). Exactly one of each pair may survive.
MERGED_PAIRS = [
    ("magnesium-before-bed", "magnesium-sleep"),
    ("no-alcohol-30-days", "eliminate-alcohol-30d"),
    ("sauna-2x-week", "sauna-2x-week-6wk"),
    ("gratitude-log", "gratitude-journal"),
]
REMOVED_IDS = {dropped for _, dropped in MERGED_PAIRS}
KEPT_IDS = {kept for kept, _ in MERGED_PAIRS}


def _load(path):
    return json.loads(path.read_text())


def _ids(catalog):
    return [e["id"] for e in catalog["experiments"]]


def _suffix_slug(experiment_id):
    """Collapse duration / variant suffix tokens so `sauna-2x-week` and
    `sauna-2x-week-6wk` map to the same key. A general dupe tripwire for future
    "-6wk" / "-30d" style expansions."""
    s = experiment_id
    s = re.sub(r"-(\d+)?(wk|weeks|week|d|days|day|mo|months|month)$", "", s)
    s = re.sub(r"-\d+$", "", s)
    return s


def suffix_slug_collisions(catalog):
    seen = {}
    for eid in _ids(catalog):
        seen.setdefault(_suffix_slug(eid), []).append(eid)
    return {k: v for k, v in seen.items() if len(v) > 1}


def coexisting_pairs(catalog):
    present = set(_ids(catalog))
    return [(a, b) for a, b in MERGED_PAIRS if a in present and b in present]


def test_both_copies_are_valid_json_and_identical():
    root_text = ROOT_COPY.read_text()
    site_text = SITE_COPY.read_text()
    # Both must parse.
    json.loads(root_text)
    json.loads(site_text)
    # And be byte-identical (the reset-purges-site-config trap: they must stay in sync).
    assert root_text == site_text, "root and site experiment_library.json copies diverged"


def test_removed_ids_absent():
    for path in (ROOT_COPY, SITE_COPY):
        present = set(_ids(_load(path)))
        leaked = REMOVED_IDS & present
        assert not leaked, f"{path.name}: dropped duplicate ids reappeared: {sorted(leaked)}"


def test_kept_ids_present():
    present = set(_ids(_load(ROOT_COPY)))
    missing = KEPT_IDS - present
    assert not missing, f"kept variant of a merged pair is missing: {sorted(missing)}"


def test_merged_pairs_do_not_coexist():
    both = coexisting_pairs(_load(ROOT_COPY))
    assert not both, f"near-duplicate pairs both still present (copy-paste inflation): {both}"


def test_no_suffix_variant_slug_collisions():
    collisions = suffix_slug_collisions(_load(ROOT_COPY))
    assert not collisions, f"duration/variant-suffix duplicate ids: {collisions}"


def test_ids_are_unique():
    ids = _ids(_load(ROOT_COPY))
    dupes = {i for i in ids if ids.count(i) > 1}
    assert not dupes, f"exact-duplicate ids in catalog: {sorted(dupes)}"
