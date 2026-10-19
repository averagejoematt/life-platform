"""tests/test_training_charter_privacy_5087.py — the charter's public/private content filter (#5087, ADR-164).

# premerge-gate: a repo-shape ratchet — sweeps lambdas/web and lambdas/emails (the published surfaces) for a charter read that is not public_view(), and holds the tracked charter files to the no-private-value rule

THE RULE. The repo is public. The owner's body and appearance targets live only in the
owner-only twin (env / gitignored local / owner-private S3), never in a tracked file; and
no PUBLISHED surface shows a charter field outside `PUBLISHED_WHITELIST`, which carries no
May target (owner ruling 2026-10-18: "no May countdown or May target on the site").

Three legs, each over a SET, not an instance:
  (a) the tracked charter files carry no private key and no real private value;
  (b) the whitelist names no May-target or private path, every entry resolves, and
      `public_view()` carries none of them even when a twin IS loaded;
  (c) no module under lambdas/web/ or lambdas/emails/ reads the charter except through
      `public_view` — AST over imports and attribute reads, plus a text sweep for the
      private channel's names.

NOT SEEN, stated: a published surface that receives the merged charter as an ARGUMENT from
an unswept caller (mcp/, lambdas/coach) — the whitelist is the contract there, this guard
is the structural leg; and the S3 object itself, which no repo test reads.
"""

from __future__ import annotations

import ast
import json
import os
import pathlib
import subprocess
import sys
from typing import Any, List

import pytest

_REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "lambdas"))

from training import training_charter as tc  # noqa: E402


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """No live S3 probe and no laptop twin: the tracked files are the only inputs."""
    monkeypatch.delenv(tc.PRIVATE_ENV_VAR, raising=False)
    monkeypatch.setattr(tc, "_from_s3", lambda key: None)
    tc.reset_cache()
    yield
    tc.reset_cache()


PUBLIC = _REPO / "config" / "training_charter.json"
EXAMPLE = _REPO / "config" / tc.PRIVATE_EXAMPLE_BASENAME
PUBLISHED_TREES = ("lambdas/web", "lambdas/emails")
FORBIDDEN_READS = frozenset({"load_charter", "charter_value", "charter_version", "_load_private", "_load_public"})
PRIVATE_CHANNEL_TOKENS = (tc.PRIVATE_ENV_VAR, tc.PRIVATE_LOCAL_BASENAME, tc.PRIVATE_S3_KEY, "training_charter.private")


def _keys(node: Any, prefix: str = "") -> List[str]:
    out: List[str] = []
    if isinstance(node, dict):
        for k, v in node.items():
            path = f"{prefix}.{k}" if prefix else k
            out.append(path)
            out.extend(_keys(v, path))
    elif isinstance(node, list):
        for v in node:
            out.extend(_keys(v, prefix))
    return out


def _leaves(node: Any) -> List[Any]:
    if isinstance(node, dict):
        return [x for k, v in node.items() if k != "_README" for x in _leaves(v)]
    if isinstance(node, list):
        return [x for v in node for x in _leaves(v)]
    return [node]


def _private_key_set() -> set[str]:
    """The twin's top-level keys: the loader's constant UNION the example file's keys."""
    example = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    return set(tc.PRIVATE_KEYS) | {k for k in example if k != "_README"}


# ── (a) the tracked files ────────────────────────────────────────────────────────────────
def test_the_public_file_carries_no_private_key_anywhere():
    data = json.loads(PUBLIC.read_text(encoding="utf-8"))
    private = _private_key_set() | {"waist_in", "photo_pose", "weight_band_lb"}
    hits = [k for k in _keys(data) if k.rsplit(".", 1)[-1] in private]
    assert not hits, f"private keys in the PUBLIC charter: {hits}"


def test_the_example_twin_holds_placeholders_only():
    example = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    assert _private_key_set() <= set(example) | set(tc.PRIVATE_KEYS)
    real = [v for v in _leaves(example) if v not in (None, "", [], {})]
    assert not real, f"the example twin carries a real-looking value: {real}"


def test_the_local_twin_is_gitignored_and_untracked():
    ignore = (_REPO / ".gitignore").read_text(encoding="utf-8")
    assert f"config/{tc.PRIVATE_LOCAL_BASENAME}" in ignore
    tracked = subprocess.run(["git", "ls-files", "config"], cwd=_REPO, capture_output=True, text=True, check=True).stdout
    assert tc.PRIVATE_LOCAL_BASENAME not in tracked
    assert "config/training_charter.private.json" not in tracked


# ── (b) the whitelist and the view ───────────────────────────────────────────────────────
def test_the_whitelist_names_no_may_target_and_no_private_path():
    bad = [p for p in tc.PUBLISHED_WHITELIST if p.startswith(tc.NEVER_PUBLISHED)]
    assert not bad, f"May-target / private paths on the PUBLISHED whitelist: {bad}"
    private = _private_key_set()
    assert not [p for p in tc.PUBLISHED_WHITELIST if p.split(".")[0] in private]
    assert {"governing_goal", "target_picture", "appearance_brief"} <= set(tc.NEVER_PUBLISHED)
    assert tc.PUBLISHED_WHITELIST, "an empty whitelist publishes nothing and guards nothing"


def test_every_whitelist_entry_resolves_in_the_public_file():
    data = json.loads(PUBLIC.read_text(encoding="utf-8"))
    dead = [p for p in tc.PUBLISHED_WHITELIST if tc._get(data, p) is tc._MISSING]
    assert not dead, f"whitelist paths with no value in the public charter: {dead}"


def test_public_view_excludes_the_target_even_with_a_twin_loaded(monkeypatch):
    twin = {"target_picture": {"weight_band_lb": [1, 2], "waist_in": 3, "photo_pose": "x"}, "appearance_brief": "y"}
    monkeypatch.setenv(tc.PRIVATE_ENV_VAR, json.dumps(twin))
    tc.reset_cache()
    try:
        merged = tc.load_charter()
        assert merged["private_loaded"] and set(merged["private_keys"]) == {"target_picture", "appearance_brief"}
        view = tc.public_view()
        text = json.dumps(view)
        assert not set(view) & set(tc.NEVER_PUBLISHED), sorted(set(view) & set(tc.NEVER_PUBLISHED))
        assert "target_date" not in text and "2027-05" not in text and "rate_band" not in text
        for k in _private_key_set():
            assert k not in text
        assert view["steps"]["floor"] == 12000 and view["split"]["sequence"][0] == "Upper-heavy"
    finally:
        tc.reset_cache()


# ── (c) the published trees ──────────────────────────────────────────────────────────────
def _published_modules() -> List[pathlib.Path]:
    out: List[pathlib.Path] = []
    for tree in PUBLISHED_TREES:
        for root, _dirs, files in os.walk(_REPO / tree):
            out.extend(pathlib.Path(root) / f for f in files if f.endswith(".py"))
    return sorted(out)


def _charter_reads(path: pathlib.Path) -> List[str]:
    """Every read of the charter in a module that is not `public_view`: names imported from
    the loader, attributes read off it, and the private channel's own tokens."""
    text = path.read_text(encoding="utf-8")
    found: List[str] = []
    for tok in PRIVATE_CHANNEL_TOKENS:
        if tok in text:
            found.append(f"names the private channel: {tok}")
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return found + ["unparseable"]
    aliases: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.endswith("training_charter"):
            for a in node.names:
                if a.name in FORBIDDEN_READS or a.name == "*":
                    found.append(f"imports {a.name} from {node.module}")
        if isinstance(node, (ast.ImportFrom, ast.Import)):
            for a in node.names:
                if a.name.endswith("training_charter"):
                    aliases.add(a.asname or a.name.split(".")[-1])
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_READS:
            base = node.value
            if isinstance(base, ast.Name) and base.id in (aliases | {"training_charter", "tc"}):
                found.append(f"reads {base.id}.{node.attr}")
            elif isinstance(base, ast.Attribute) and base.attr == "training_charter":
                found.append(f"reads training.training_charter.{node.attr}")
    return found


def test_no_published_surface_reads_the_charter_except_through_public_view():
    offenders = {p.relative_to(_REPO).as_posix(): r for p in _published_modules() if (r := _charter_reads(p))}
    assert len(_published_modules()) >= 20, "the published trees are (almost) empty — a directory moved"
    assert not offenders, "published surfaces must read training_charter.public_view() only:\n" + "\n".join(
        f"  {k}: {'; '.join(v)}" for k, v in sorted(offenders.items())
    )


def test_the_read_detector_sees_each_forbidden_shape(tmp_path):
    """Positive controls for (c): each shape a leak could take is caught on a synthetic module."""
    shapes = {
        "from training.training_charter import load_charter\n": "imports load_charter",
        "from training import training_charter\nx = training_charter.charter_value('steps.floor')\n": "reads training_charter.charter_value",
        "import training.training_charter as chart\nx = chart.load_charter()\n": "reads chart.load_charter",
        "import training\nx = training.training_charter.charter_version()\n": "reads training.training_charter.charter_version",
        f"KEY = '{tc.PRIVATE_S3_KEY}'\n": "names the private channel",
        "from training.training_charter import public_view\nx = public_view()\n": None,
    }
    for i, (src, expect) in enumerate(shapes.items()):
        p = tmp_path / f"m{i}.py"
        p.write_text(src, encoding="utf-8")
        got = _charter_reads(p)
        if expect is None:
            assert not got, (src, got)
        else:
            assert any(expect in g for g in got), (src, got)
