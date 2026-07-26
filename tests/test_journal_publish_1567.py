"""#1567 — /journal-interview publish: interview → approved public essay.

The mode itself is a claude-workflow (`.claude/commands/journal-interview.md` step 6);
this file pins the code surface it depends on so the contract can't silently rot:

  - the generator carries + renders the ``provenance`` field (AC4: "composed from a
    <date> interview, approved by Matthew") and stays BYTE-IDENTICAL when the field
    is absent — pre-#1567 pages never regenerate;
  - the provenance line passes through the same fail-closed privacy gate as the body;
  - the content-policy scanner's scope covers exactly the files the flow creates
    (essay body fragments + blog.json) and does NOT allowlist them — the path-keyed
    exemption trap: content paths must never be exempted (AC2);
  - the command doc encodes the runtime approval gate unambiguously (AC1/AC3) and
    blog.json's _schema documents the provenance field.
"""

import json
import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "scripts"))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

import content_policy_scan as cps  # noqa: E402
import v4_build_journal as j  # noqa: E402

BLOG_PATH = os.path.join(_REPO, "site", "journal", "blog.json")
COMMAND_DOC = os.path.join(_REPO, ".claude", "commands", "journal-interview.md")

PROVENANCE = "composed from a 2026-07-25 interview, approved by Matthew"


def _first_post():
    with open(BLOG_PATH, encoding="utf-8") as f:
        return json.load(f)["posts"][0]


# ── AC4: provenance is carried + rendered ─────────────────────────────────────
def test_provenance_renders_in_the_receipts_register():
    post = dict(_first_post())
    post["provenance"] = PROVENANCE
    html = j.render(post)
    assert f'<div class="post-receipts">{PROVENANCE}</div>' in html


def test_provenance_is_html_escaped():
    post = dict(_first_post())
    post["provenance"] = 'composed from a <b>2026-07-25</b> "interview"'
    html = j.render(post)
    assert "<b>2026-07-25</b>" not in html
    assert "&lt;b&gt;2026-07-25&lt;/b&gt;" in html


def test_absent_provenance_emits_nothing_and_pages_stay_byte_identical():
    post = dict(_first_post())
    post.pop("provenance", None)
    html = j.render(post)
    assert "composed from a" not in html
    # no orphan receipts block between the article and the CTA
    assert "</article>\n  <aside" in html
    # the on-disk pre-#1567 page needs no regeneration → the template change is
    # byte-identical for entries without the field
    assert j.build(write=False, check=True) == 0


def test_provenance_passes_through_the_privacy_gate(monkeypatch):
    seen = []

    real = j.privacy_guard.assert_clean

    def spy(text, context=""):
        seen.append(context)
        return real(text, context=context)

    monkeypatch.setattr(j.privacy_guard, "assert_clean", spy)
    post = dict(_first_post())
    post["provenance"] = PROVENANCE
    j.render(post)
    assert any(c.endswith(".provenance") for c in seen)


# ── AC2: the scanner's scope covers the flow's new files, unexempted ──────────
def test_scanner_scope_covers_essay_fragments_and_blog_json():
    assert "site" in cps.SCAN_DIRS
    assert {".md", ".html", ".json"} <= cps.TEXT_EXTENSIONS
    # the path-keyed allowlist trap: content paths must never be exempted —
    # a scanner hit on an essay means rewrite-and-re-approve, not an allowlist entry
    assert not cps.is_allowlisted("site/journal/essays/some-new-essay/body.md")
    assert not cps.is_allowlisted("site/journal/essays/some-new-essay/body.html")
    assert not cps.is_allowlisted("site/journal/essays/some-new-essay/index.html")
    assert not cps.is_allowlisted("site/journal/blog.json")
    assert not any(a.startswith("site/journal/") for a in cps.ALLOWLIST_FILES)


# ── AC1/AC3: the command doc encodes the runtime rules unambiguously ──────────
def test_command_doc_encodes_the_publish_gate():
    doc = open(COMMAND_DOC, encoding="utf-8").read()
    # normalize wrapping + emphasis so the assertions pin MEANING, not line breaks
    norm = " ".join(doc.replace("**", "").replace("`", "").split())
    # the variant exists and the approval gate is stated as a runtime rule
    assert "publish variant" in norm
    assert "EXACT final text in-chat before any PR opens" in norm
    assert "byte-for-byte the text he approved" in norm
    # the no-approval fallback: private Notion draft, never published
    assert "No approval → no PR, nothing public, ever." in norm
    # AC1: grounding bar
    assert "ADR-104" in norm and "Nothing invented" in norm
    # AC2: privacy guardrails at composition time + the allowlist trap
    assert "ELENA_PREQUEL_BRIEF.md" in norm
    assert "content_policy_scan.py" in norm
    assert "NEVER add an essay path to the scanner's ALLOWLIST_FILES" in norm
    # AC4: the provenance line format
    assert '"provenance": "composed from a YYYY-MM-DD interview, approved by Matthew"' in norm


def test_blog_schema_documents_provenance():
    with open(BLOG_PATH, encoding="utf-8") as f:
        blog = json.load(f)
    assert "provenance?" in blog["_schema"]
    assert "approved by Matthew" in blog["_schema"]
