"""tests/ci_shard.py — #4252: split the post-merge parallel coverage pass across runners.

ci-test.yml's Unit Tests used to run the whole suite on ONE 4-core runner: a parallel
pass (`-m "not serial"`, ~985s) then a serial pass (`-m serial`, ~290s). That job was
the long pole of every push to main (18.5-23.6 min against the #4252 box-4 bar of 20).
The parallel pass now runs as N matrix legs, each collecting only ITS share of the test
FILES; the serial pass runs as one more leg beside them; a final job combines the
coverage data and grades the floor once over the union.

The split is by FILE, not by test, because the pass runs `--dist loadfile` (a module's
tests share module-scoped fixtures and cached scans on one worker) — splitting a file
across runners would pay for those twice.

The partition is exact by construction: `shard_of` maps every file name to exactly one
shard in 1..N, so N legs over the same `tests/` tree see disjoint file sets whose union
is the whole tree. `tests/test_ci_test_shards_4252.py` holds that, and holds the
workflow's matrix to the same N.

Assignment is by a stable hash (crc32 of the file name) rather than by position in a
sorted list, so adding or deleting one test file moves no OTHER file between shards.

Unset (or empty) `CI_TEST_SHARD` = no sharding, which is every run except those legs.
A set but malformed value raises, so a typo cannot quietly run nothing or everything.
"""

from __future__ import annotations

import os
import zlib

SHARD_ENV = "CI_TEST_SHARD"


def parse_spec(spec: str) -> tuple[int, int] | None:
    """'K/N' -> (K, N). '' -> None (not sharded). Anything else raises ValueError."""
    spec = (spec or "").strip()
    if not spec:
        return None
    parts = spec.split("/")
    if len(parts) != 2 or not all(p.strip().isdigit() for p in parts):
        raise ValueError(f"{SHARD_ENV}={spec!r} is not K/N")
    k, n = int(parts[0]), int(parts[1])
    if n < 1 or not 1 <= k <= n:
        raise ValueError(f"{SHARD_ENV}={spec!r}: K must be in 1..N and N >= 1")
    return k, n


def is_test_module(name: str) -> bool:
    """pytest's default `python_files` (pytest.ini sets none): test_*.py and *_test.py."""
    return name.endswith(".py") and (name.startswith("test_") or name.endswith("_test.py"))


def shard_of(name: str, total: int) -> int:
    """The 1-based shard a test file belongs to among `total`."""
    return zlib.crc32(name.encode("utf-8")) % total + 1


def excluded(path: str, spec: str) -> bool:
    """True when `path` is a test module that belongs to a DIFFERENT shard than `spec`.

    Non-test paths (directories, conftest.py, helpers, fixtures) are never excluded.
    """
    parsed = parse_spec(spec)
    if parsed is None:
        return False
    name = os.path.basename(str(path))
    if not is_test_module(name):
        return False
    k, n = parsed
    return shard_of(name, n) != k
