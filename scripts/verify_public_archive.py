#!/usr/bin/env python3
"""Verify a downloaded public permanence archive (#1400).

Deliberately dependency-free and read-only, so it can be run by anyone, from a
mirror, long after this repository has stopped changing. Standard library only:
no requests, no boto3, no AWS credentials, no write of any kind.

What it checks:

  1. Every entry listed in the archive's own ``MANIFEST.json`` is present in
     the tarball, at the listed size, with the listed SHA-256.
  2. Nothing is in the tarball that the manifest does not list (apart from the
     manifest and README, which cannot list themselves).
  3. With ``--manifest-url``: the published manifest's ``archive.sha256``
     matches the bytes you actually downloaded — i.e. nobody swapped the file
     between the checksum and you.
  4. With ``--check-urls``: every archived entry is still reachable at its own
     public URL, which is the claim clause P3 makes — that the archive contains
     only bytes the public site already serves.

Usage:

    curl -sO https://averagejoematt.com/archive/latest.tar.gz
    python3 scripts/verify_public_archive.py --archive latest.tar.gz
    python3 scripts/verify_public_archive.py --archive latest.tar.gz \\
        --manifest-url https://averagejoematt.com/archive/manifest.json --check-urls

Exit code 0 = every requested check passed. Non-zero = a stated fact about the
archive is false, and the output says which one.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tarfile
import urllib.error
import urllib.request

DEFAULT_ORIGIN = "https://averagejoematt.com"
SELF_DESCRIBING = ("MANIFEST.json", "README.txt")
URL_CHECK_TIMEOUT = 20


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_archive(path: str) -> tuple[bytes, dict[str, bytes]]:
    """Return (raw archive bytes, {member-relative-name: content})."""
    with open(path, "rb") as fh:
        raw = fh.read()
    members: dict[str, bytes] = {}
    with tarfile.open(path, "r:gz") as tf:
        for info in tf.getmembers():
            if not info.isfile():
                continue
            _root, _sep, rel = info.name.partition("/")
            if not rel:
                continue
            extracted = tf.extractfile(info)
            if extracted is None:
                continue
            members[rel] = extracted.read()
    return raw, members


def public_url_for(member: str, origin: str) -> str | None:
    """Reverse the archive's member naming back to the public URL it came from.

    ``web/method/index.html`` -> ``<origin>/method/index.html``
    ``api/status__summary.json`` -> ``<origin>/api/status/summary``
    """
    if member.startswith("web/"):
        return origin + member[len("web") :]
    if member.startswith("api/") and member.endswith(".json"):
        slug = member[len("api/") : -len(".json")].replace("__", "/")
        return f"{origin}/api/{slug}"
    return None


def verify_contents(members: dict[str, bytes], manifest: dict) -> list[str]:
    problems: list[str] = []
    listed = {e["member"]: e for e in manifest.get("entries", [])}
    present = {k for k in members if k not in SELF_DESCRIBING}

    for name in sorted(set(listed) - present):
        problems.append(f"manifest lists {name}, which is not in the archive")
    for name in sorted(present - set(listed)):
        problems.append(f"archive contains {name}, which the manifest does not list")

    for name in sorted(set(listed) & present):
        body = members[name]
        entry = listed[name]
        if len(body) != entry.get("bytes"):
            problems.append(f"{name}: manifest says {entry.get('bytes')} bytes, archive has {len(body)}")
        actual = _sha256(body)
        if actual != entry.get("sha256"):
            problems.append(f"{name}: checksum mismatch (manifest {entry.get('sha256')}, actual {actual})")
    return problems


def verify_published_checksum(raw: bytes, manifest_url: str) -> list[str]:
    try:
        with urllib.request.urlopen(manifest_url, timeout=URL_CHECK_TIMEOUT) as resp:  # nosec B310 - operator-supplied https URL
            published = json.loads(resp.read())
    except (urllib.error.URLError, ValueError, OSError) as exc:
        return [f"could not read the published manifest at {manifest_url}: {exc}"]
    declared = (published.get("archive") or {}).get("sha256")
    actual = _sha256(raw)
    if declared != actual:
        return [
            "the published manifest does not describe the file you downloaded "
            f"(published {declared}, downloaded {actual}). If the archive was rebuilt "
            "between the two fetches this is expected — re-download both and retry."
        ]
    return []


def verify_urls(members: dict[str, bytes], origin: str, limit: int | None) -> list[str]:
    problems: list[str] = []
    names = sorted(n for n in members if n not in SELF_DESCRIBING)
    if limit:
        names = names[:limit]
    for name in names:
        url = public_url_for(name, origin)
        if url is None:
            problems.append(f"{name}: no public URL could be derived — an entry with no public origin should not be here")
            continue
        req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "verify-public-archive/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=URL_CHECK_TIMEOUT) as resp:  # nosec B310 - fixed public origin
                if int(resp.status or 0) >= 400:
                    problems.append(f"{name}: {url} returned {resp.status}")
        except urllib.error.HTTPError as exc:
            problems.append(f"{name}: {url} returned {exc.code}")
        except (urllib.error.URLError, OSError) as exc:
            problems.append(f"{name}: {url} unreachable ({exc})")
    return problems


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Verify a public permanence archive (read-only, stdlib only).")
    ap.add_argument("--archive", required=True, help="path to a downloaded latest.tar.gz")
    ap.add_argument("--manifest-url", help="also check the published manifest describes these exact bytes")
    ap.add_argument("--check-urls", action="store_true", help="HEAD every entry at its own public URL")
    ap.add_argument("--origin", default=DEFAULT_ORIGIN, help=f"public origin for --check-urls (default {DEFAULT_ORIGIN})")
    ap.add_argument("--url-sample", type=int, default=0, help="check only the first N URLs (0 = all)")
    args = ap.parse_args(argv)

    raw, members = read_archive(args.archive)
    if "MANIFEST.json" not in members:
        print("FAIL: the archive has no MANIFEST.json — nothing about it can be verified")
        return 2
    manifest = json.loads(members["MANIFEST.json"])

    problems = verify_contents(members, manifest)
    checks = ["contents"]

    if args.manifest_url:
        problems += verify_published_checksum(raw, args.manifest_url)
        checks.append("published-checksum")
    if args.check_urls:
        problems += verify_urls(members, args.origin, args.url_sample or None)
        checks.append("public-urls")

    print(f"archive:      {args.archive}")
    print(f"built:        {manifest.get('generated_at')}")
    print(f"terms:        v{manifest.get('terms_version')} (effective {manifest.get('terms_effective')})")
    print(f"entries:      {manifest.get('entry_count')}  ({manifest.get('uncompressed_bytes')} bytes uncompressed)")
    print(f"downloaded:   {len(raw)} bytes  sha256 {_sha256(raw)}")
    api = manifest.get("api") or {}
    print(f"api capture:  {api.get('routes_captured')}/{api.get('routes_declared')} routes")
    print(f"checks run:   {', '.join(checks)}")

    if problems:
        print(f"\nFAIL — {len(problems)} problem(s):")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("\nOK — every checked claim holds.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv[1:]))
