"""#3625 — `build_bundle.zip_dir` is byte-reproducible: the same staged tree zips to the same bytes,
whatever the files' mtimes, and a one-byte source change changes the hash (the positive control).

Mutation control: restore `zf.write(full, arcname)` in `zip_dir` → the mtime-shifted rebuild below
hashes differently and `test_the_same_tree_zips_to_identical_bytes` reds."""

from __future__ import annotations

import hashlib
import importlib.util
import os
import time
import zipfile

REPO = os.path.join(os.path.dirname(__file__), "..")


def _bb():
    spec = importlib.util.spec_from_file_location("build_bundle_3625", os.path.join(REPO, "deploy", "build_bundle.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _tree(root: str) -> None:
    os.makedirs(os.path.join(root, "pkg", "__pycache__"), exist_ok=True)
    with open(os.path.join(root, "pkg", "a.py"), "w") as fh:
        fh.write("X = 1\n")
    with open(os.path.join(root, "pkg", "b.py"), "w") as fh:
        fh.write("Y = 2\n")
    with open(os.path.join(root, "pkg", "__pycache__", "a.cpython-312.pyc"), "wb") as fh:
        fh.write(b"\x00pyc")
    with open(os.path.join(root, "pkg", "stale.pyc"), "wb") as fh:
        fh.write(b"\x00pyc")


def _sha(path: str) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def test_the_same_tree_zips_to_identical_bytes(tmp_path):
    bb = _bb()
    src = str(tmp_path / "stage")
    _tree(src)
    first = bb.zip_dir(src, str(tmp_path / "one.zip"))
    # shift every mtime by a day — a fresh checkout or a copytree does exactly this
    later = time.time() + 86400
    for root, _d, files in os.walk(src):
        for f in files:
            os.utime(os.path.join(root, f), (later, later))
    second = bb.zip_dir(src, str(tmp_path / "two.zip"))
    assert _sha(first) == _sha(second), "the zip's bytes depend on something other than the tree's bytes"


def test_a_one_byte_source_change_changes_the_hash(tmp_path):
    bb = _bb()
    src = str(tmp_path / "stage")
    _tree(src)
    before = _sha(bb.zip_dir(src, str(tmp_path / "one.zip")))
    with open(os.path.join(src, "pkg", "a.py"), "w") as fh:
        fh.write("X = 2\n")
    after = _sha(bb.zip_dir(src, str(tmp_path / "two.zip")))
    assert before != after, "a source change must change the artifact — or the reproducibility test is vacuous"


def test_entries_are_sorted_dated_1980_and_carry_no_bytecode(tmp_path):
    bb = _bb()
    src = str(tmp_path / "stage")
    _tree(src)
    with zipfile.ZipFile(bb.zip_dir(src, str(tmp_path / "one.zip"))) as zf:
        names = zf.namelist()
        assert names == sorted(names)
        assert not any("__pycache__" in n or n.endswith(".pyc") for n in names), names
        assert {zi.date_time for zi in zf.infolist()} == {bb.ZIP_ENTRY_DATE_TIME}
        assert {zi.external_attr for zi in zf.infolist()} == {bb.ZIP_ENTRY_EXTERNAL_ATTR}
        assert zf.read("pkg/a.py") == b"X = 1\n"
