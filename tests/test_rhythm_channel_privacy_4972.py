"""tests/test_rhythm_channel_privacy_4972.py — no `/api/*` route and no public reader can
reach the owner-only heart-rhythm event channel (#4972, owner ruling (c), 2026-10-17).

THE SET, NOT THE INSTANCE. Two independent legs, each proved able to fail:

  * the SWEEP — every `.py/.js/.html/.json/.md/.sh/.txt` under the serving, narrative and
    site trees is read; a mention of the channel's sort-key prefix, its producer module or
    ANY of its field names outside the written allowlist fails and names the file. A planted
    reader in a synthetic tree is caught (#2578 negative control).
  * the ROUTE WALK — `tests/rhythm_route_walk.py`, in a fresh interpreter, calls EVERY
    site-API GET route (ROUTES + _SIMPLE_ROUTES + the inline `_dispatch_route` branches,
    bare and with `source=clinical&field=…` parameters) against a table holding one channel
    row at its real key, with S3/HTTP/Bedrock dead, and asserts no response carries a field
    name, a sentinel value or the prefix. Mutation control: `--plant` re-binds `/api/vitals`
    to a reader that serves the clinical partition's rows — the walk must red.

A third, structural leg: every channel field is TIER_OWNER_ONLY, so the MCP row dumpers
strip it (`strip_map`) and `tests/privacy_tier_wiring.py` reds any new module that names one.

A fourth (#4972 part 2): the owner-only renderer `health/rhythm_owner.py` and the daily brief's doors to it
(`rhythm_lines`, `_brief_rhythm`) are named only by the brief's three owner-only files. Accepted limit: a
string-built importlib path names no token and is caught only at runtime (leg 2).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lambdas"))

from health.rhythm_channel import CHANNEL_FIELDS, PREFIX  # noqa: E402

TOKENS = tuple(CHANNEL_FIELDS) + (PREFIX, "rhythm_channel")
# `rhythm_channel` is matched as a module token, not inside this guard's own test-file names.
_TOKEN_RE = re.compile("|".join([re.escape(PREFIX)] + [rf"(?<![\w/]test_){re.escape(t)}\b" for t in CHANNEL_FIELDS + ("rhythm_channel",)]))

SWEPT_TREES = ("lambdas", "mcp", "site", "scripts", "deploy", "cdk")
_SUFFIXES = {".py", ".js", ".mjs", ".html", ".json", ".md", ".sh", ".txt"}
_SKIP_PARTS = {"__pycache__", "node_modules", "cdk.out", ".venv", "site-packages", "_bundle_staging", "_mcp_staging"}
# deploy/generated/** holds live-measured artifacts (the pk-family census) that name partitions
# by construction; they are readers of nothing.
_SKIP_RELATIVE = ("deploy/generated",)

# The ONLY files that may name the channel, each with its reason. A new entry is a review.
ALLOWED_MENTIONS = {
    "lambdas/health/rhythm_channel.py": "the producer (parse, de-duplicate, build the RHYTHM# rows)",
    "lambdas/health/clinical_facts.py": "the writer (put_channel_rows, RHYTHM#-only) — and the renderer that does NOT render it",
    "lambdas/ingestion/health_auto_export_lambda.py": "the webhook's event-dispatch block (counts only)",
    "lambdas/privacy/field_tiers.py": "the TIER_OWNER_ONLY declaration",
    "lambdas/health/rhythm_owner.py": "the owner-only renderer (reads neutral events via read_events; importer set held by tests/test_rhythm_owner_4972.py)",
}
# Trees where NO mention is acceptable under any allowlist: a reader surface or a narrative producer.
NEVER_TREES = (
    "lambdas/web",
    "lambdas/emails",
    "lambdas/content",
    "lambdas/intelligence",
    "lambdas/ai",
    "lambdas/coach",
    "site",
    "scripts/v4_",
)


def _files(root: Path):
    for top in SWEPT_TREES:
        base = root / top
        if not base.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in _SKIP_PARTS and not d.startswith(".")]
            for fn in filenames:
                p = Path(dirpath) / fn
                if p.suffix in _SUFFIXES:
                    yield p


def mentions(root: Path = ROOT) -> dict:
    """{repo-relative path: first matching line} for every file naming the channel."""
    found = {}
    for p in _files(root):
        rel = p.relative_to(root).as_posix()
        if rel.startswith(_SKIP_RELATIVE):
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if not any(t in text for t in TOKENS):
            continue
        for line in text.splitlines():
            if _TOKEN_RE.search(line):
                found[rel] = line.strip()[:120]
                break
    return found


def offenders(found: dict) -> dict:
    return {rel: line for rel, line in found.items() if rel not in ALLOWED_MENTIONS}


# ── leg 1: the sweep ──────────────────────────────────────────────────────────
def test_no_file_outside_the_allowlist_names_the_channel():
    bad = offenders(mentions())
    assert not bad, "the owner-only rhythm channel is named outside its producer/writer/declaration:\n" + "\n".join(
        f"  {rel}: {line}" for rel, line in sorted(bad.items())
    )


def test_no_reader_or_narrative_tree_names_it_at_all():
    hits = [rel for rel in mentions() if rel.startswith(NEVER_TREES)]
    assert hits == [], f"a reader/narrative tree names the owner-only rhythm channel: {hits}"


def test_every_allowlist_entry_is_load_bearing_and_the_sweep_reaches_its_trees():
    found = mentions()
    stale = sorted(rel for rel in ALLOWED_MENTIONS if rel not in found)
    assert stale == [], f"allowlist entries that no longer name the channel (decoration, not a rule): {stale}"
    swept = {p.relative_to(ROOT).as_posix() for p in _files(ROOT)}
    for known in ("lambdas/web/site_api_lambda.py", "lambdas/web/site_api_vitals.py", "mcp/registry.py", "site/index.html"):
        assert known in swept, f"sweep no longer covers {known}"


def test_the_sweep_catches_a_planted_reader(tmp_path):
    """The negative control, on a synthetic tree — never in the repo (#2578)."""
    (tmp_path / "lambdas" / "web").mkdir(parents=True)
    planted = tmp_path / "lambdas" / "web" / "site_api_sneaky.py"
    planted.write_text('def handle(row):\n    return {"ecg": row.get("rhythm_ecg_classification")}\n', encoding="utf-8")
    found = mentions(tmp_path)
    assert offenders(found) == {"lambdas/web/site_api_sneaky.py": found["lambdas/web/site_api_sneaky.py"]}


# ── leg 2: the route walk ─────────────────────────────────────────────────────
def _walk(*args) -> dict:
    proc = subprocess.run(
        [sys.executable, str(ROOT / "tests" / "rhythm_route_walk.py"), *args],
        capture_output=True,
        text=True,
        timeout=240,
        cwd=str(ROOT),
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_no_api_route_serves_a_channel_row():
    out = _walk()
    # Non-vacuity: the walk reached the router and the handlers really read the table.
    assert out["routes"] >= 100, out["routes"]
    assert out["answered"] >= out["routes"], out
    assert out["queries"] >= 300 and len(out["partitions_asked"]) >= 40, (out["queries"], out["partitions_asked"])
    assert out["unparsed_queries"] == 0, "a query the fixture table could not read — it would answer nothing, a blind spot"
    assert out["leaks"] == {}, f"routes serving the owner-only rhythm channel: {out['leaks']}"


def test_the_route_walk_catches_a_public_reader_that_serves_the_channel():
    """Mutation control: one real public route made to serve the clinical partition's rows."""
    out = _walk("--plant")
    assert "/api/vitals" in out["leaks"], out["leaks"]
    assert "RHYTHMSENTINELCLASS" in out["leaks"]["/api/vitals"]


def test_the_route_walk_catches_a_public_route_serving_the_rendered_section():
    """Mutation control for the renderer's output (#4972 part 2): no field name, sentinel or prefix in it — the
    walk sees it by the renderer's fixed strings, with real counts from the row dated by the walk's own clock."""
    out = _walk("--plant-renderer")
    hits = out["leaks"].get("/api/vitals", [])
    assert "rhythm notifications" in hits and "Questions about these records: discuss with your clinician." in hits, hits


# ── leg 3: the structure ──────────────────────────────────────────────────────
def test_every_channel_field_is_owner_only_and_stripped_by_the_row_dumpers():
    from privacy.field_tiers import FIELD_TIERS, TIER_OWNER_ONLY, strip_map

    assert all(FIELD_TIERS["clinical"].get(f) == TIER_OWNER_ONLY for f in CHANNEL_FIELDS)
    assert set(CHANNEL_FIELDS) <= set(strip_map()["clinical"])


# ── leg 4: the owner-only renderer's importer set (#4972 part 2) ──────────────
# `health/rhythm_owner.py` reads the channel back (as neutral events) and renders it for the owner. It names no
# channel token on its import line, so legs 1-2 cannot see who calls it: this leg holds every file naming the
# renderer — OR the brief's own doors to it (`rhythm_lines`, the helper in emails/brief_lines.py, and
# `_brief_rhythm`, the section renderer in content/html_builder.py) — to the owner surfaces below, across every
# source tree INCLUDING www/ (the v9 site build). A public route calling `brief_lines.rhythm_lines(...)` names a
# token and reds. ACCEPTED LIMIT: a module path built from strings (`importlib.import_module("health." + x)`) or a
# `getattr` by a computed name names no token; that shape is caught only at runtime (the route walk, leg 2, which
# answers every GET with a channel row dated inside the brief's window). Behaviour + the daily brief's email-only
# wiring + the prompt test: tests/test_rhythm_owner_4972.py.
# The token -> the files that may name it, each an owner-only surface. A new entry is a review — and feeding the
# renderer to a coach or any model is NOT on this list: the channel is TIER_OWNER_ONLY (never quoted into an AI
# narrative context) until the owner rules on the tier.
_BRIEF_DOORS = {
    "lambdas/emails/brief_lines.py": "the daily brief's owner-only section helper (the email to the owner alone)",
    "lambdas/emails/daily_brief_lambda.py": "computes the section (demo brief excluded) and hands it to build_html only",
    "lambdas/content/html_builder.py": "renders the section into the owner's email, escaped, inside S:rhythm markers",
}
PERMITTED_MENTIONS = {
    "rhythm_owner": {"lambdas/emails/brief_lines.py": _BRIEF_DOORS["lambdas/emails/brief_lines.py"]},
    "rhythm_lines": _BRIEF_DOORS,
    "_brief_rhythm": _BRIEF_DOORS,
}
# Non-vacuity: the live wiring each token must still have (a guard over a door nobody uses is decoration).
REQUIRED_MENTIONS = {
    ("lambdas/emails/brief_lines.py", "rhythm_owner"),
    ("lambdas/emails/daily_brief_lambda.py", "rhythm_lines"),
    ("lambdas/content/html_builder.py", "_brief_rhythm"),
}
# The renderer itself and its producer (whose docstring points at its one reader; it imports nothing from it).
_RENDERER_SELF = {"lambdas/health/rhythm_owner.py", "lambdas/health/rhythm_channel.py"}
_RENDERER_TREES = ("lambdas", "mcp", "scripts", "deploy", "cdk", "site", "www")
_RENDERER_SUFFIXES = {".py", ".js", ".mjs", ".ts", ".astro", ".html", ".json", ".md", ".sh", ".txt"}
_RENDERER_SKIP = {"__pycache__", "node_modules", "cdk.out", ".venv", "site-packages", "_bundle_staging", "_mcp_staging", "dist", ".astro"}


def renderer_importers(root: Path = ROOT) -> dict:
    """{repo-relative path: set of renderer/door tokens it names}."""
    out: dict = {}
    for top in _RENDERER_TREES:
        for dirpath, dirnames, filenames in os.walk(root / top):
            dirnames[:] = [d for d in dirnames if d not in _RENDERER_SKIP and not d.startswith(".")]
            for fn in filenames:
                p = Path(dirpath) / fn
                if p.suffix not in _RENDERER_SUFFIXES:
                    continue
                rel = p.relative_to(root).as_posix()
                if rel in _RENDERER_SELF:
                    continue
                try:
                    text = p.read_text(encoding="utf-8")
                except (UnicodeDecodeError, OSError):
                    continue
                hits = {t for t in PERMITTED_MENTIONS if t in text}
                if hits:
                    out[rel] = hits
    return out


def test_only_permitted_owner_surfaces_import_the_renderer():
    found = renderer_importers()
    bad = sorted((rel, t) for rel, toks in found.items() for t in toks if rel not in PERMITTED_MENTIONS[t])
    assert not bad, f"a non-owner surface names the rhythm renderer or one of the brief's doors to it: {bad}"
    have = {(rel, t) for rel, toks in found.items() for t in toks}
    assert REQUIRED_MENTIONS <= have, f"the daily brief no longer wires the rhythm section: {sorted(REQUIRED_MENTIONS - have)}"


def test_the_importer_sweep_catches_a_planted_public_reader(tmp_path):
    (tmp_path / "lambdas" / "web").mkdir(parents=True)
    (tmp_path / "lambdas" / "web" / "site_api_sneaky.py").write_text("from health import rhythm_owner\n", encoding="utf-8")
    (tmp_path / "www" / "src").mkdir(parents=True)
    (tmp_path / "www" / "src" / "page.astro").write_text("rhythm_owner.owner_lines\n", encoding="utf-8")
    assert set(renderer_importers(tmp_path)) == {"lambdas/web/site_api_sneaky.py", "www/src/page.astro"}


def test_the_sweep_catches_a_public_route_calling_the_brief_helper(tmp_path):
    """The indirect door: a public route that never names the renderer but calls the brief's helper."""
    (tmp_path / "lambdas" / "web").mkdir(parents=True)
    (tmp_path / "lambdas" / "web" / "site_api_indirect.py").write_text(
        "from emails import brief_lines\n\ndef handle(table):\n    return brief_lines.rhythm_lines(table, '2026-01-01', None)\n",
        encoding="utf-8",
    )
    (tmp_path / "lambdas" / "content").mkdir(parents=True)
    (tmp_path / "lambdas" / "content" / "site_writer.py").write_text("from content.html_builder import _brief_rhythm\n", encoding="utf-8")
    found = renderer_importers(tmp_path)
    assert set(found) == {"lambdas/web/site_api_indirect.py", "lambdas/content/site_writer.py"}, found


# premerge-gate: #4972: os.walk sweep of lambdas/ mcp/ site/ scripts/ deploy/ cdk/ (+ www/ for the renderer's importer set) + a route walk of every /api/* GET handler — no public reader reaches the owner-only rhythm channel
