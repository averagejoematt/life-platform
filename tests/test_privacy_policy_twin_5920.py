#!/usr/bin/env python3
"""The maintained privacy policy is served at its own address, and that copy cannot drift (#5920).

``site/privacy/index.html`` is the policy's one editable source (a replaced destination since the 1 November
cut-over: kept in the repo, excluded from the site sync). ``scripts/v9_privacy_policy_twin.py`` derives its twin,
``www/src/privacy/policy.json``, which ``www/src/pages/privacy/policy/index.astro`` renders at ``/privacy/policy/``.

Pinned here:
  * the committed twin is exactly what the generator produces from the source today (a policy edit that is not
    regenerated never reaches the served page silently);
  * the twin carries every permanence clause (P9 included — the clause the frozen 1 November copy lacks), the live
    archive panel, and section 06's browser-storage disclosure in the same words as the v9 summary page;
  * the v9 pages say which copy is current and link the archive; the summary page links the current policy;
  * the QA manifest's policy checks (#2574) run against the served page;
  * the generator refuses a source that would put a script on a v9 page (CSP: script-src 'self').
"""

from __future__ import annotations

import json
import os
import re
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for extra in (os.path.join(ROOT, "scripts"), os.path.join(ROOT, "lambdas"), ROOT):
    if extra not in sys.path:
        sys.path.insert(0, extra)

import v9_privacy_policy_twin as twin  # noqa: E402
from operational import permanence_terms as terms  # noqa: E402

POLICY_PAGE = os.path.join(ROOT, "www", "src", "pages", "privacy", "policy", "index.astro")
SUMMARY_PAGE = os.path.join(ROOT, "www", "src", "pages", "privacy", "index.astro")
ARCHIVE = "/reference/2026-11-01-privacy-v5/"
BROWSER_DATE = "The date is not sent to the site or used for advertising or analytics."


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


@pytest.fixture(scope="module")
def committed() -> dict:
    return json.loads(_read(twin.TWIN))


def test_the_committed_twin_is_what_the_generator_produces():
    """If this fails, run: ``python3 scripts/v9_privacy_policy_twin.py``."""
    assert _read(twin.TWIN) == twin.build(), "www/src/privacy/policy.json has drifted from site/privacy/index.html — regenerate it"


def test_the_twin_carries_every_permanence_clause(committed: dict):
    rendered = set(re.findall(r'id="clause-(P\d+)"', committed["body"]))
    assert rendered == {c["id"] for c in terms.CLAUSES}
    assert "P9" in rendered  # the clause added on 4 November, missing from the frozen 1 November copy


def test_the_twin_carries_the_live_archive_panel(committed: dict):
    assert 'id="perm-live"' in committed["body"] and 'data-perm="built"' in committed["body"]
    assert 'class="perm-clauses"' in committed["body"]  # the QA visual check counts these


def test_section_06_and_the_summary_page_disclose_the_browser_date_alike(committed: dict):
    section = committed["body"].split("cookies and tracking", 1)[1].split('class="policy-section"', 1)[0]
    assert "stores the date of your last visit in your browser" in section and BROWSER_DATE in section
    summary = re.sub(r"\s+", " ", _read(SUMMARY_PAGE))
    assert "stores the date of your last visit in your browser" in summary and BROWSER_DATE in summary


def test_the_last_changed_date_is_in_words(committed: dict):
    assert re.fullmatch(r"(\d{1,2} )?[A-Z][a-z]+ \d{4}", committed["updated"]), committed["updated"]


def test_the_policy_page_says_which_copy_is_current_and_links_the_archive():
    page = _read(POLICY_PAGE)
    assert 'import policy from "../../../privacy/policy.json"' in page and "set:html={policy.body}" in page
    assert "This is the current policy, last changed on {policy.updated}" in page
    assert f'href="{ARCHIVE}"' in page
    assert 'import "../../../islands/permanence.js"' in page


def test_the_summary_page_links_the_current_policy_and_the_archive():
    page = _read(SUMMARY_PAGE)
    assert 'href={href("/privacy/policy/")}' in page
    assert f'href="{ARCHIVE}"' in page


def test_the_qa_manifest_checks_the_policy_where_it_is_served():
    import qa.qa_manifest as qm

    owned = {"live_at_root": True, "static_routes": ["/privacy/", "/privacy/policy/"], "route_patterns": [], "routes": []}
    rows = {r["path"]: r for r in qm._v9_rows(owned, live=True)}
    row = rows["/privacy/policy/"]
    assert row["structural"] == {"marker": "data-policy-current"}
    assert {"/archive/manifest.json", "/archive/continuity.json"} <= set(row["api_deps"])
    selectors = {c["selector"] for c in row["visual"]["checks"]}
    assert {".perm-clause", "#perm-live .pl-grid dd"} <= selectors
    assert ".perm-clause" not in {c["selector"] for c in rows["/privacy/"]["visual"]["checks"]}  # the summary has no clauses


def test_the_generator_refuses_a_script_in_the_policy_body(tmp_path):
    src = _read(twin.SOURCE).replace(twin.BODY_END, "<script>alert(1)</script>\n    " + twin.BODY_END, 1)
    planted = tmp_path / "index.html"
    planted.write_text(src, encoding="utf-8")
    with pytest.raises(ValueError, match="script"):
        twin.build(str(planted))


def test_the_generator_refuses_an_undated_policy(tmp_path):
    src = re.sub(r"last updated · [^<]+", "last updated · recently", _read(twin.SOURCE), count=1)
    planted = tmp_path / "index.html"
    planted.write_text(src, encoding="utf-8")
    with pytest.raises(ValueError, match="date in words"):
        twin.build(str(planted))
