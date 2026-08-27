"""
tests/test_shared_image_prepare_3079.py — ONE screenshot -> vision-judge prepare path (#3079).

`scripts/fresh_eyes_discovery.py` carried its own `_image_block` that base64'd a
full-page capture straight off disk with no downscale of any kind. Two consequences,
both already-named defect classes:

  * #3067 — the model's OWN input pipeline resizes to its resolution tier, so a
    1440x17271 door arrives at ~9% scale and the judge grades the degraded input
    ("illegibly small text") rather than the page.
  * #2973 — an oversized payload can be rejected by Bedrock outright, and a page the
    oracle cannot evaluate must FAIL loudly, never silently read as clean.

The fix is not "add a resize to fresh-eyes" — that is how the class recurs. There is
now exactly ONE implementation, `visual_ai_qa._image_blocks`, and this file guards the
SET: a new copy anywhere in the repo reds the registry test below.

Two layers here, deliberately:
  1. THE WIRE — drive `fresh_eyes_discovery.vision_read` with a recording fake and
     assert what the JUDGE ACTUALLY RECEIVES. A resize helper that exists but is not
     reached is the #2578 trap; only the recorded Bedrock body settles it.
  2. THE SET — an AST census of every `{"type": "image", ...}` block construction in
     the repo, checked against a registry with a written reason per site.
"""

import ast
import base64
import os
import subprocess
import sys

import pytest

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_TESTS_DIR)
for _p in (_TESTS_DIR, os.path.join(_ROOT, "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import fresh_eyes_discovery as fed  # noqa: E402
import visual_ai_qa  # noqa: E402

_EMPTY_VERDICT = '{"findings": []}'


def _tall_png(tmp_path, w, h, name="capture.png"):
    """A real (not header-faked) PNG — the tiler crops actual pixels."""
    from PIL import Image

    shot = tmp_path / name
    Image.new("RGB", (w, h), "white").save(shot)
    return shot


def _recording_bedrock(calls, text=_EMPTY_VERDICT):
    def invoke(body, model_name=None):
        calls.append(body)
        return {"content": [{"type": "text", "text": text}]}

    return type("B", (), {"invoke": staticmethod(invoke)})()


def _image_blocks_of(body):
    return [b for b in body["messages"][0]["content"] if b.get("type") == "image"]


def _sent_dims(body):
    """(w, h) of every image block the judge received, in order."""
    return [visual_ai_qa._png_dims(base64.b64decode(b["source"]["data"])) for b in _image_blocks_of(body)]


# ── layer 1: the wire — what the judge actually receives ─────────────────────


def test_ultra_tall_discovery_capture_reaches_the_judge_tiled_and_legible(tmp_path):
    """The acceptance test, on the real wire: vision_read -> _image_blocks -> the
    Bedrock body a fake records. Mutation-proof — restore the old raw base64
    `_image_block` and this reds three times over (one block; that block below the
    legibility floor; the payload byte-identical to the file on disk)."""
    pytest.importorskip("PIL")
    shot = _tall_png(tmp_path, 1440, 9000)

    calls = []
    out = fed.vision_read(_recording_bedrock(calls), "Home", "/", str(shot), "page")

    assert out == [], "the fake verdict carries no findings"
    assert len(calls) == 1, "exactly one vision call per capture"
    body = calls[0]

    sent = _sent_dims(body)
    assert len(sent) > 1, "a 9000px capture must reach the judge tiled, not as one illegible image"
    for w, h in sent:
        assert (
            visual_ai_qa._model_scale(w, h) >= visual_ai_qa._MIN_LEGIBLE_SCALE
        ), f"tile {w}x{h} reaches the judge at scale {visual_ai_qa._model_scale(w, h):.2f} — below the 11px floor"

    raw = base64.b64encode(shot.read_bytes()).decode()
    assert all(b["source"]["data"] != raw for b in _image_blocks_of(body)), "the judge must not receive the undownscaled capture"


def test_discovery_tiles_cover_the_whole_page_not_just_the_top(tmp_path):
    """'Cap it to above-the-fold' would fix the verdict by hiding most of the page.
    Full-width slices, overlapping, spanning the whole height."""
    pytest.importorskip("PIL")
    shot = _tall_png(tmp_path, 1440, 9000)
    calls = []
    fed.vision_read(_recording_bedrock(calls), "Home", "/", str(shot), "page")

    sent = _sent_dims(calls[0])
    assert all(w == 1440 for w, _ in sent), "tiles are full-width slices — never cropped horizontally"
    assert sum(h for _, h in sent) > 9000, "tiles must cover the page and overlap, not sample it"


def test_discovery_prompt_still_trails_the_images(tmp_path):
    """The prompt is the LAST content block — tiling inserts labels before it, and a
    prompt buried mid-run of images is a silently different question."""
    pytest.importorskip("PIL")
    shot = _tall_png(tmp_path, 1440, 9000)
    calls = []
    fed.vision_read(_recording_bedrock(calls), "Home", "/", str(shot), "page")

    content = calls[0]["messages"][0]["content"]
    assert content[-1]["type"] == "text"
    assert "reddit_newcomer" in content[-1]["text"], "the last block is the fresh-eyes audience prompt"


def test_normal_height_discovery_capture_is_unchanged_and_costs_nothing_extra(tmp_path):
    """Cost guard: a page inside the legibility bound goes as ONE image whose bytes
    are byte-identical to the pre-#3079 payload. Sharing the path must not make the
    common case more expensive."""
    pytest.importorskip("PIL")
    shot = _tall_png(tmp_path, 1440, 1200, name="short.png")
    calls = []
    fed.vision_read(_recording_bedrock(calls), "Cockpit", "/cockpit/", str(shot), "page")

    content = calls[0]["messages"][0]["content"]
    assert [b["type"] for b in content] == ["image", "text"], "an in-bound page gains no tile labels"
    assert base64.b64decode(content[0]["source"]["data"]) == shot.read_bytes()


def test_unpreparable_capture_is_named_and_never_a_silent_clean_read(tmp_path):
    """#2973 on the discovery pass: a capture the judge cannot be handed is recorded
    as UNREAD, printed, and makes NO Bedrock call — it must never look like a door
    that was inspected and found fine."""
    bad = tmp_path / "not-a-png.png"
    bad.write_bytes(b"\x00" * 4096)  # over vision_read's 256-byte zero-crop filter

    fed.UNREAD_PAGES.clear()
    calls = []
    out = fed.vision_read(_recording_bedrock(calls), "Data", "/data/", str(bad), "page")

    assert out == []
    assert calls == [], "no vision call may be made on a capture that could not be prepared"
    assert len(fed.UNREAD_PAGES) == 1
    assert "Data (page)" in fed.UNREAD_PAGES[0]
    assert "not a valid PNG" in fed.UNREAD_PAGES[0]
    fed.UNREAD_PAGES.clear()


# ── layer 2: guard the SET — one prepare path, by AST census ─────────────────

# Every sanctioned site that constructs a Bedrock/Anthropic `{"type": "image"}`
# content block, keyed (repo-relative path, enclosing function), with the reason it
# is allowed to exist. A site absent from this map reds — which is the point: the
# #3079 defect was a SECOND copy of the screenshot->judge path, added without anyone
# having to decide it was a good idea.
SANCTIONED_IMAGE_BLOCK_SITES = {
    ("tests/visual_ai_qa.py", "_png_block"): (
        "THE screenshot -> vision-judge prepare path. Owns the #2973 Bedrock reject "
        "guard and the #3067 model-resize tiling; visual_ai_qa, visual_qa's --ai-qa "
        "sweep and scripts/fresh_eyes_discovery.py all route through it (#3079)."
    ),
    ("lambdas/experiment/eyeball_calibration.py", "estimate_from_photo"): (
        "NOT a screenshot path and not a second copy: it forwards a caller-supplied "
        "base64 meal photo (#1390), never reads a page capture off disk, and ships "
        "inside a Lambda bundle that cannot import tests/. Camera photos are nowhere "
        "near the 8000px reject limit or the #3067 tall-page legibility bound. "
        "Registered deliberately, not exempted by accident."
    ),
}

_SCAN_DIRS = ("lambdas", "tests", "scripts", "mcp", "deploy", "cdk")
_SKIP_PARTS = {"__pycache__", "node_modules", "cdk.out", ".venv", "site-packages"}


def _is_untracked_build_dir(path):
    """True for a directory git will not track — local build output, not source.

    `_SKIP_PARTS` is a NAME list, which is an instance guard: `cdk/_bundle_staging/` and
    `cdk/_mcp_staging/` are gitignored staging copies produced by any local deploy, and
    neither is on it, so this sweep reported two phantom unregistered sites on every
    machine that had ever run a deploy — while passing in CI, which has no staging dirs.
    A test that fails only locally trains people to ignore it. Structural instead of
    name-matched: ask git whether the directory is content at all.
    """
    try:
        return subprocess.run(["git", "check-ignore", "-q", path], cwd=_ROOT, capture_output=True, timeout=10).returncode == 0
    except Exception:
        return False  # fail OPEN: a missing git must not silently shrink the sweep


def _python_files(root=_ROOT):
    for top in _SCAN_DIRS:
        for dirpath, dirnames, filenames in os.walk(os.path.join(root, top)):
            dirnames[:] = [
                d
                for d in dirnames
                if d not in _SKIP_PARTS and not d.startswith(".") and not _is_untracked_build_dir(os.path.join(dirpath, d))
            ]
            for fn in filenames:
                if fn.endswith(".py"):
                    yield os.path.join(dirpath, fn)


def _is_image_block_dict(node):
    """True for a dict literal carrying `"type": "image"` — the wire shape itself,
    matched structurally. A name-based rule ('any function called _image_block')
    would miss the next copy the moment it is called something else."""
    if not isinstance(node, ast.Dict):
        return False
    for k, v in zip(node.keys, node.values):
        if isinstance(k, ast.Constant) and k.value == "type" and isinstance(v, ast.Constant) and v.value == "image":
            return True
    return False


def _census(root=_ROOT):
    """{(relpath, enclosing function or '<module>')} for every image-block literal."""
    found = set()
    for path in _python_files(root):
        with open(path, encoding="utf-8") as f:
            src = f.read()
        if '"type": "image"' not in src and "'type': 'image'" not in src:
            continue  # cheap prefilter only — the AST below is the authority
        tree = ast.parse(src, filename=path)
        funcs = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        rel = os.path.relpath(path, root)
        for node in ast.walk(tree):
            if not _is_image_block_dict(node):
                continue
            enclosing = [f for f in funcs if f.lineno <= node.lineno <= (f.end_lineno or f.lineno)]
            # innermost wins — a nested helper is its own site
            name = max(enclosing, key=lambda f: f.lineno).name if enclosing else "<module>"
            found.add((rel, name))
    return found


def test_exactly_one_screenshot_to_judge_image_block_implementation():
    """Guard the SET (#3079's third acceptance clause). A third copy — or a move of
    an existing one — reds here and has to be argued into the registry above."""
    found = _census()
    unregistered = found - set(SANCTIONED_IMAGE_BLOCK_SITES)
    assert not unregistered, (
        "unregistered Bedrock image-block construction site(s): "
        + ", ".join(f"{p}::{n}" for p, n in sorted(unregistered))
        + " — route screenshots through visual_ai_qa._image_blocks (#3067/#2973/#3079), or register the "
        "site in SANCTIONED_IMAGE_BLOCK_SITES with a written reason."
    )
    missing = set(SANCTIONED_IMAGE_BLOCK_SITES) - found
    assert not missing, "registry entr(ies) with no matching code — the guard is measuring nothing: " + ", ".join(
        f"{p}::{n}" for p, n in sorted(missing)
    )


def test_the_census_actually_detects_a_new_copy(tmp_path):
    """The negative control, made to FAIL for real. A guard that cannot fail is the
    #2578 class — so plant a fresh copy and prove the census names it.

    The probe lives in a synthetic tree under tmp_path, NOT in the repo. Writing it
    into the real `scripts/` would have been a stronger-looking proof and a worse
    test: this file now runs in the pre-merge lane alongside a dozen other tree
    sweeps (test_root_clutter_guard, test_gate_census_2578, test_leak_token_sweep),
    and any hard exit that skips the cleanup — a lane timeout, a kill — leaves an
    untracked stray that reds one of THOSE, somewhere else, on someone else's PR.
    Coverage of the real tree is asserted separately below, where it costs nothing.
    """
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "sneaky.py").write_text(
        "def _sneaky_copy(path):\n"
        "    import base64\n"
        "    with open(path, 'rb') as fh:\n"
        "        b64 = base64.b64encode(fh.read()).decode()\n"
        '    return {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b64}}\n',
        encoding="utf-8",
    )
    found = _census(root=str(tmp_path))
    assert ("scripts/sneaky.py", "_sneaky_copy") in found, "the census must see a newly added copy"
    assert found - set(SANCTIONED_IMAGE_BLOCK_SITES), "an unregistered copy must be reported, not tolerated"


def test_the_census_sweep_actually_reaches_every_directory_it_claims(tmp_path):
    """The other half of the control: a detector that works on a synthetic tree is
    worthless if the real sweep never walks the directories a copy would land in.
    Pin one known file per scanned top-level dir — an os.walk that silently stopped
    covering `scripts/` (where the #3079 copy actually lived) reds here."""
    swept = {os.path.relpath(p, _ROOT) for p in _python_files()}
    for known in (
        "scripts/fresh_eyes_discovery.py",
        "tests/visual_ai_qa.py",
        "lambdas/experiment/eyeball_calibration.py",
        "mcp/registry.py",
        "deploy/sync_doc_metadata.py",
        "cdk/stacks/operational_stack.py",
    ):
        assert known in swept, f"the census sweep never reaches {known} — a copy hidden there would be invisible"

    # and the guard's real-tree verdict has no residue of the synthetic probe above
    assert not (_census() - set(SANCTIONED_IMAGE_BLOCK_SITES))


def test_fresh_eyes_has_no_private_image_block_left():
    """The specific regression: scripts/fresh_eyes_discovery.py must not base64 a
    capture itself. It delegates, and the delegate is the shared path."""
    with open(os.path.join(_ROOT, "scripts", "fresh_eyes_discovery.py"), encoding="utf-8") as f:
        source = f.read()
    tree = ast.parse(source)
    assert not any(_is_image_block_dict(n) for n in ast.walk(tree)), "fresh_eyes_discovery must not build image blocks itself"
    assert not hasattr(fed, "_image_block"), "the private single-image copy is gone, not merely unused"

    # the delegation is real, not a re-implementation that happens to share a name
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_image_blocks")
    assert "visual_ai_qa._image_blocks" in (ast.get_source_segment(source, fn) or "")
