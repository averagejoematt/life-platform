"""tests/test_coach_vision_isolation_3759.py — no public or narrative consumer reads the
coach-vision record (#3759, epic #3743; the fourth acceptance box).

THE SET, NOT THE INSTANCE. The record `USER#matthew#SOURCE#coach_vision` carries a sentence
about his body and a body-fat band that is an estimate, not a measurement. Its sanctioned
consumers are exactly two: the owner's MCP tool and his own Telegram coach thread. This
guard sweeps the tree for every mention of the partition's tokens and holds the mention set
to a written allowlist — so a site endpoint, an email, a chronicle, a coach narrative or a
site generator that starts reading it reds here, by construction, before it can serve a
word of it.

Three legs:
  * the SWEEP — every `.py`/`.js`/`.html`/`.json` under the serving, narrative and site trees
    is read; a token hit outside the allowlist fails and names the file;
  * the ALLOWLIST is proved load-bearing and not blanket — every entry still carries the
    token (a stale entry is decoration), and a planted reader in a serving tree is caught
    by the same function run over a synthetic root (the #2578 negative control);
  * the STRUCTURE — the site API's `ROUTES` serve no coach-vision path, the privacy tier and
    the taxonomy class are declared, and the producing role is the only compute role that
    names the photo prefix.
"""

from __future__ import annotations

import ast
import inspect
import os
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lambdas"))

TOKENS = ("coach_vision", "SOURCE#coach_vision")
# A negative lookbehind keeps the sweep off its own test-file names (`test_coach_vision_*.py`),
# which the census proof records cite by gate id; the partition token is what is guarded.
_TOKEN_RE = re.compile(r"(?<!test_)coach_vision")

# Where a reader surface would have to live to serve the record. Swept whole.
SWEPT_TREES = ("lambdas", "mcp", "site", "scripts", "deploy", "cdk")
_SUFFIXES = {".py", ".js", ".mjs", ".html", ".json", ".md", ".sh", ".txt"}
_SKIP_PARTS = {"__pycache__", "node_modules", "cdk.out", ".venv", "site-packages", "_bundle_staging", "_mcp_staging"}
# deploy/generated/** holds live-measured artifacts (the pk-family census, refreshed at reset — #3514)
# that will name every partition by construction; they are readers of nothing.
_SKIP_RELATIVE = ("deploy/generated",)

# The ONLY files that may name the partition, each with the reason. A new entry is a review.
ALLOWED_MENTIONS = {
    "lambdas/coach/coach_vision.py": "the producer module (pure)",
    "lambdas/coach/coach_vision_lambda.py": "the producer Lambda",
    "lambdas/coach/telegram_worker_lambda.py": "consumer 2 of 2 — the owner's own Telegram coach thread (facts addendum)",
    "mcp/tools_coach_vision.py": "consumer 1 of 2 — the owner's field-selective MCP tool",
    "mcp/registry.py": "the MCP wiring table (import + TOOLS entry)",
    "mcp/layer_status.py": "the derived-layer registry the MCP tool honours (#3769)",
    "lambdas/privacy/field_tiers.py": "the Tier-2 declaration",
    "lambdas/experiment/phase_taxonomy.py": "the CROSS_PHASE class",
    "lambdas/ai/budget_guard.py": "the band-2 cutoff",
    "lambdas/ai/model_routing.py": "the VISION-tier route",
    "scripts/ai_budget_ledger.py": "the per-feature budget row",
    "cdk/stacks/compute_stack.py": "the schedule + the absence alarm",
    "cdk/stacks/role_policies_compute.py": "the producing role (LeadingKeys-scoped write)",
    "cdk/stacks/role_policies.py": "the policy facade re-export",
    "scripts/gate_census_mutations.py": "the census harness's mutation plant for THIS gate",
}

# Trees where NO mention is acceptable under any allowlist: a reader surface or a narrative
# producer. Listed explicitly so the assertion names the class, not just the file.
NEVER_TREES = ("lambdas/web", "lambdas/emails", "lambdas/content", "lambdas/intelligence", "site", "scripts/v4_")


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
    """{repo-relative path: first matching line} for every file naming the partition."""
    found = {}
    for p in _files(root):
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if "coach_vision" not in text or p.relative_to(root).as_posix().startswith(_SKIP_RELATIVE):
            continue
        for line in text.splitlines():
            if _TOKEN_RE.search(line):
                found[p.relative_to(root).as_posix()] = line.strip()[:120]
                break
    return found


def offenders(found: dict) -> dict:
    return {rel: line for rel, line in found.items() if rel not in ALLOWED_MENTIONS}


# ── the sweep ─────────────────────────────────────────────────────────────────
def test_no_file_outside_the_allowlist_names_the_partition():
    bad = offenders(mentions())
    assert (
        not bad
    ), "coach-vision record named outside its two consumers + plumbing — a new reader must be argued into ALLOWED_MENTIONS:\n" + "\n".join(
        f"  {rel}: {line}" for rel, line in sorted(bad.items())
    )


def test_no_reader_or_narrative_tree_names_it_at_all():
    hits = [rel for rel in mentions() if rel.startswith(NEVER_TREES)]
    assert hits == [], f"a reader/narrative tree names the owner-only record: {hits}"


def test_every_allowlist_entry_is_load_bearing():
    found = mentions()
    stale = sorted(rel for rel in ALLOWED_MENTIONS if rel not in found and (ROOT / rel).exists())
    assert stale == [], f"allowlist entries that no longer name the partition (decoration, not a rule): {stale}"


def test_the_sweep_actually_reaches_the_trees_it_claims():
    swept = {p.relative_to(ROOT).as_posix() for p in _files(ROOT)}
    for known in (
        "lambdas/web/site_api_lambda.py",
        "lambdas/emails/daily_brief_lambda.py",
        "mcp/registry.py",
        "site/index.html",
        "scripts/v4_build_data_sources.py",
    ):
        assert known in swept, f"sweep no longer covers {known}"


def test_the_sweep_catches_a_planted_reader(tmp_path):
    """The negative control, on a synthetic tree — never in the repo (#2578)."""
    (tmp_path / "lambdas" / "web").mkdir(parents=True)
    (tmp_path / "lambdas" / "web" / "site_api_sneaky.py").write_text(
        'def handle():\n    return table.query(KeyConditionExpression="pk = :pk", ExpressionAttributeValues={":pk": "USER#matthew#SOURCE#coach_vision"})\n',
        encoding="utf-8",
    )
    found = mentions(tmp_path)
    assert "lambdas/web/site_api_sneaky.py" in found
    assert offenders(found) == {"lambdas/web/site_api_sneaky.py": found["lambdas/web/site_api_sneaky.py"]}


# ── the structure ─────────────────────────────────────────────────────────────
def test_the_site_api_serves_no_coach_vision_route():
    src = (ROOT / "lambdas" / "web" / "site_api_lambda.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    routes = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "ROUTES" for t in node.targets):
            routes = [k.value for k in getattr(node.value, "keys", []) if isinstance(k, ast.Constant)]
    assert routes, "ROUTES not found — the sweep is measuring nothing"
    assert not [r for r in routes if "vision" in r], routes


def test_the_tier_the_class_and_the_band_are_declared():
    from ai import budget_guard
    from experiment import phase_taxonomy
    from privacy.field_tiers import SOURCE_TIERS, TIER_OWNER_ONLY

    assert SOURCE_TIERS["coach_vision"] == TIER_OWNER_ONLY
    assert phase_taxonomy.SOURCE_CLASS["coach_vision"] == phase_taxonomy.CROSS_PHASE
    assert budget_guard._FEATURE_CUTOFF["coach_vision"] == 2


def test_the_write_grant_is_scoped_to_the_one_partition_and_the_read_to_the_photo_prefix():
    sys.path.insert(0, str(ROOT / "cdk"))
    from stacks import role_policies_compute as rpc

    stmts = rpc.compute_coach_vision()
    writes = [s for s in stmts if any(a.startswith("dynamodb:Put") or a.startswith("dynamodb:Update") for a in s.actions)]
    assert len(writes) == 1
    assert writes[0].actions == ["dynamodb:PutItem"]
    # The conditions are read from the SOURCE: the shared CDK stub (tests/grant_enumeration.py)
    # keeps sid/actions/resources only, so an object-level read would be vacuous under it.
    src = inspect.getsource(rpc.compute_coach_vision)
    assert src.count("dynamodb:LeadingKeys") == 1
    assert '"dynamodb:LeadingKeys": ["USER#matthew#SOURCE#coach_vision"]' in src
    assert src.index("dynamodb:PutItem") < src.index("dynamodb:LeadingKeys") < src.index("s3:GetObject")
    s3_reads = [s for s in stmts if "s3:GetObject" in s.actions]
    assert len(s3_reads) == 1 and all(r.endswith("/raw/matthew/progress_photos/*") for r in s3_reads[0].resources)
    assert not [s for s in stmts if any(a.startswith("s3:Put") or a.startswith("s3:Delete") or a == "s3:ListBucket" for a in s.actions)]


@pytest.mark.parametrize(
    "rel", ["lambdas/web/site_api_lambda.py", "lambdas/coach/coach_narrative_orchestrator.py", "lambdas/ai/ai_calls.py"]
)
def test_the_named_reader_and_narrative_entry_points_do_not_name_it(rel):
    text = (ROOT / rel).read_text(encoding="utf-8")
    for token in TOKENS:
        assert token not in text, f"{rel} names {token!r}"


# premerge-gate: #3759: os.walk sweep of lambdas/ mcp/ site/ scripts/ deploy/ cdk/ — no public or narrative consumer names the owner-only coach-vision record
