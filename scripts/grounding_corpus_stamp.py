#!/usr/bin/env python3
"""scripts/grounding_corpus_stamp.py — the content-hash seal on the adversarial grounding corpus (#3614).

WHY A SEAL
----------
`tests/grounding_corpus/*.json` holds one fixture per sentence the platform was caught
fabricating, each with the gate class that must FAIL it and a matched positive control
that must PASS. The corpus is the record of what the gates are graded against, so it
follows the pre-registration's rule (#1378, `deploy/genesis_prereg_stamp.py`): every
fixture is content-addressed by a committed `.sha256.json` sibling, and the seal
REFUSES to launder an edit — a specimen that stops failing its gate is fixed by fixing
the GATE (or honestly flipping the fixture's `status` in the diff), never by quietly
rewording the sentence.

What the seal permits vs. refuses:
  * ADD a fixture              -> `stamp` records it; the count only grows.
  * EDIT an existing fixture   -> `stamp` REFUSES (the hash changed) unless `--amend <id>`
                                  names it, so the edit is a stated decision in the diff.
  * DELETE a fixture           -> `stamp` REFUSES; the corpus is grow-only.

    python3 scripts/grounding_corpus_stamp.py verify        # exit 1 on any drift (the CI check)
    python3 scripts/grounding_corpus_stamp.py stamp         # after adding a fixture
    python3 scripts/grounding_corpus_stamp.py stamp --amend <fixture id>

Pure stdlib. `verify_corpus()` is importable by tests/test_grounding_corpus_3614.py.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CORPUS_DIR = REPO_ROOT / "tests" / "grounding_corpus"
STAMP_PATH = CORPUS_DIR / "corpus.sha256.json"
STAMP_NAME = STAMP_PATH.name


def fixture_paths(corpus_dir: Path = CORPUS_DIR) -> list[Path]:
    return sorted(p for p in corpus_dir.glob("*.json") if p.name != STAMP_NAME)


def file_hashes(corpus_dir: Path = CORPUS_DIR) -> dict[str, str]:
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in fixture_paths(corpus_dir)}


def corpus_sha256(hashes: dict[str, str]) -> str:
    """One hash over the sorted (name, sha) pairs — the corpus's identity as a SET."""
    blob = "\n".join(f"{name} {sha}" for name, sha in sorted(hashes.items()))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def load_stamp(stamp_path: Path = STAMP_PATH) -> dict | None:
    if not stamp_path.exists():
        return None
    return json.loads(stamp_path.read_text(encoding="utf-8"))


def verify_corpus(corpus_dir: Path = CORPUS_DIR, stamp_path: Path | None = None) -> list[str]:
    """Every drift between the fixtures on disk and the committed seal. Empty = sealed."""
    stamp_path = stamp_path or (corpus_dir / STAMP_NAME)
    stamp = load_stamp(stamp_path)
    if stamp is None:
        return [f"no seal at {stamp_path} — run `python3 scripts/grounding_corpus_stamp.py stamp`"]
    live = file_hashes(corpus_dir)
    sealed = stamp.get("files") or {}
    problems = []
    for name in sorted(set(sealed) - set(live)):
        problems.append(f"DELETED fixture {name} — the corpus is grow-only; restore it")
    for name in sorted(set(live) - set(sealed)):
        problems.append(f"UNSEALED fixture {name} — run `stamp` to seal it")
    for name in sorted(set(live) & set(sealed)):
        if live[name] != sealed[name]:
            problems.append(
                f"EDITED fixture {name} — sealed {sealed[name][:12]}…, on disk {live[name][:12]}… (fix the gate or `stamp --amend`)"
            )
    if not problems and stamp.get("corpus_sha256") != corpus_sha256(live):
        problems.append("corpus_sha256 in the seal does not match the sealed files — the seal itself was hand-edited")
    if not problems and int(stamp.get("count", -1)) != len(live):
        problems.append(f"seal count {stamp.get('count')} != {len(live)} fixtures on disk")
    return problems


def write_stamp(
    corpus_dir: Path = CORPUS_DIR, stamp_path: Path | None = None, amend: tuple[str, ...] = (), now: datetime | None = None
) -> dict:
    stamp_path = stamp_path or (corpus_dir / STAMP_NAME)
    live = file_hashes(corpus_dir)
    existing = load_stamp(stamp_path) or {}
    sealed = existing.get("files") or {}
    amended = {f"{a}.json" if not a.endswith(".json") else a for a in amend}
    deleted = sorted(set(sealed) - set(live))
    if deleted:
        raise SystemExit(f"REFUSED: fixture(s) deleted since the seal — the corpus is grow-only: {deleted}")
    edited = sorted(n for n in set(live) & set(sealed) if live[n] != sealed[n] and n not in amended)
    if edited:
        raise SystemExit(f"REFUSED: fixture(s) edited since the seal — an edit is laundering unless named with --amend: {edited}")
    unknown_amend = sorted(a for a in amended if a not in live)
    if unknown_amend:
        raise SystemExit(f"--amend names fixture(s) that do not exist: {unknown_amend}")
    stamped_at = (now or datetime.now(timezone.utc)).isoformat()
    statuses = {}
    for p in fixture_paths(corpus_dir):
        try:
            statuses[p.name] = json.loads(p.read_text(encoding="utf-8")).get("status")
        except (ValueError, OSError):
            statuses[p.name] = None
    stamp = {
        "artifact": "tests/grounding_corpus/*.json",
        "algorithm": "sha256",
        "count": len(live),
        "caught": sum(1 for s in statuses.values() if s == "caught"),
        "open": sum(1 for s in statuses.values() if s == "open"),
        "files": dict(sorted(live.items())),
        "corpus_sha256": corpus_sha256(live),
        "first_stamped_at": existing.get("first_stamped_at") or stamped_at,
        "stamped_at": stamped_at,
        "amended": sorted(amended) if amended else [],
        "verify": "python3 scripts/grounding_corpus_stamp.py verify",
    }
    stamp_path.write_text(json.dumps(stamp, indent=2) + "\n", encoding="utf-8")
    return stamp


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Seal / verify the adversarial grounding corpus (#3614).")
    ap.add_argument("command", choices=("verify", "stamp"))
    ap.add_argument("--amend", action="append", default=[], metavar="ID", help="fixture id whose EDIT is a stated decision")
    args = ap.parse_args(argv)
    if args.command == "verify":
        problems = verify_corpus()
        if problems:
            print("GROUNDING CORPUS SEAL BROKEN:\n  " + "\n  ".join(problems))
            return 1
        stamp = load_stamp() or {}
        print(
            f"sealed: {stamp.get('count')} fixture(s) ({stamp.get('caught')} caught, {stamp.get('open')} open) · corpus {str(stamp.get('corpus_sha256'))[:16]}…"
        )
        return 0
    stamp = write_stamp(amend=tuple(args.amend))
    print(
        f"STAMPED {stamp['count']} fixture(s) ({stamp['caught']} caught, {stamp['open']} open) → {STAMP_PATH.relative_to(REPO_ROOT)}\n  corpus {stamp['corpus_sha256']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
