"""tests/test_intake_privacy_contract.py — the #1405 privacy hard gate.

The private intake ledger is Matthew-private ONLY (MCP + daily brief). This
contract pins the boundary in BOTH directions so it is non-vacuous:

Presence (reds on a tree where the feature is missing):
  * the ledger exists — phase-taxonomy registration, ritual metric, MCP tools,
    and the write path routes to the private partition.

Absence (reds on a tree where the ledger leaks):
  * no site/ file, no lambdas/web module (beyond the sanctioned write routing),
    and no generated-public-artifact writer references the ledger identifiers;
  * the public wellbeing read structurally cannot serve an intake field even if
    one is maliciously present on the evening_ritual record.
"""

import json
import os
import pathlib
import sys

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "lambdas"))
sys.path.insert(0, str(_REPO / "lambdas" / "web"))
sys.path.insert(0, str(_REPO))

# The ledger's identifiers — the strings whose appearance on a public surface
# IS the leak. (Generic lifestyle content elsewhere may mention the substance
# class; these identifiers are unique to the private ledger.)
LEDGER_TOKENS = ("private_intake", "intake_count", "intake_response")


# ── presence: the ledger exists and routes privately ──────────────────────────


def test_ledger_is_registered_everywhere_private():
    from phase_taxonomy import RAW_TIMESERIES, SOURCE_CLASS
    from ritual_link import PRIVATE_RITUAL_METRICS, RITUAL_METRICS

    assert SOURCE_CLASS.get("private_intake") == RAW_TIMESERIES
    assert "intake_count" in RITUAL_METRICS
    assert "intake_count" in PRIVATE_RITUAL_METRICS

    from mcp.registry import TOOLS

    assert "log_evening_intake" in TOOLS
    assert "get_intake_response" in TOOLS


def test_write_path_routes_private_metric_away_from_public_partition():
    # Structural: the routing constant exists and the social module consumes it.
    src = (_REPO / "lambdas" / "web" / "site_api_social.py").read_text()
    assert "PRIVATE_RITUAL_METRICS" in src and "private_intake" in src


# ── absence: the identifiers never reach a public surface ─────────────────────


def _files(root, exts):
    for p in root.rglob("*"):
        if p.is_file() and p.suffix in exts:
            yield p


def test_site_tree_never_names_the_ledger():
    site = _REPO / "site"
    hits = []
    for p in _files(site, {".html", ".js", ".css", ".json", ".xml", ".txt"}):
        text = p.read_text(errors="ignore")
        for tok in LEDGER_TOKENS:
            if tok in text:
                hits.append(f"{p.relative_to(_REPO)}: {tok}")
    assert not hits, f"ledger identifiers leaked into site/: {hits}"


def test_web_modules_never_read_or_serve_the_ledger():
    web = _REPO / "lambdas" / "web"
    hits = []
    for p in sorted(web.glob("*.py")):
        text = p.read_text(errors="ignore")
        if p.name == "site_api_social.py":
            # The ONE sanctioned reference: routing the signed tap WRITE to the
            # private partition. It must not import the analysis module, and no
            # LINE naming the partition may be read-shaped (query/eq/get_item) —
            # the inline literal exists only so the orphan gate sees the write.
            assert "intake_response" not in text, "web write path must not import the analysis module"
            for line in text.splitlines():
                if "private_intake" in line:
                    assert not any(tok in line for tok in ("eq(", ".query", "get_item")), f"read-shaped private_intake line: {line.strip()}"
            continue
        for tok in LEDGER_TOKENS:
            if tok in text:
                hits.append(f"{p.name}: {tok}")
    assert not hits, f"ledger identifiers leaked into lambdas/web/: {hits}"


def test_generated_artifact_writers_never_name_the_ledger():
    writers = [
        _REPO / "lambdas" / "site_writer.py",
        _REPO / "lambdas" / "web" / "og_image_lambda.py",
        _REPO / "lambdas" / "web" / "site_stats_refresh_lambda.py",
    ]
    hits = []
    for p in writers:
        text = p.read_text(errors="ignore")
        for tok in LEDGER_TOKENS:
            if tok in text:
                hits.append(f"{p.name}: {tok}")
    assert not hits, f"ledger identifiers leaked into generated-artifact writers: {hits}"


def test_public_wellbeing_read_structurally_drops_intake_fields(monkeypatch):
    """Even a maliciously-planted intake_count on the evening_ritual record must
    not survive into the public payload — the read whitelists its two scalars."""
    from web import site_api_data as sad

    class _T:
        def query(self, **kw):
            return {
                "Items": [
                    {
                        "pk": "USER#matthew#SOURCE#evening_ritual",
                        "sk": "DATE#2026-07-01",
                        "date": "2026-07-01",
                        "connection": 3,
                        "mood_valence": 2,
                        "intake_count": 4,  # planted — must never be served
                    }
                ]
            }

    monkeypatch.setattr(sad, "table", _T())
    resp = sad.handle_fulfillment_ritual()
    body = json.loads(resp["body"]) if isinstance(resp.get("body"), str) else resp["body"]
    assert "intake" not in json.dumps(body)
