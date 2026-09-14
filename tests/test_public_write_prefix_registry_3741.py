"""tests/test_public_write_prefix_registry_3741.py — writing to a public prefix is a DECISION.

THE DEFECT, TWICE
-----------------
`deploy/bucket_policy.json`'s `PublicReadGenerated` statement grants `Principal: *`
`s3:GetObject` on `generated/*` — at the S3 origin, with or without CloudFront. Anything a
Lambda writes there is world-readable at a derivable key, immediately.

That is correct and deliberate for most of what lands there: OG share cards, the podcast
audio, the public Q&A archive. It has also now been wrong twice:

  * #3559 (2026-09-05) — `/api/board_question` and `/api/submit_finding` wrote moderation
    records carrying a reader's `email` and `ip_hash` to `generated/`. Moved to
    `reader_input/`; a guard was written that names those two doors.
  * #3741 (2026-09-14) — the daily recap card shipped to `generated/recap/`. Its own
    privacy test asserted there was no CloudFront route to it, which was true, and which
    was never the property that mattered. Verified live: anonymous GET returned 200 and
    the full card. Eight days plus the weekly, at keys derivable from a date, with the
    prefix named in a public repo.

Both fixes moved one writer. Neither could see the next writer arrive, because both named
instances. This file is the SET: every grant that writes under an anonymously-readable
prefix must be listed below with a reason, so the third case is a red on the PR that
introduces it rather than a live exposure someone stumbles on.

WHAT IS NOT CLAIMED
-------------------
This does not decide whether a prefix SHOULD be public — it forces someone to say which
they meant. A row here is a claim that the artifact is intended for anonymous readers.
"""

from __future__ import annotations

import ast
import json
import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
POLICY = REPO / "deploy" / "bucket_policy.json"
ROLE_FILES = sorted((REPO / "cdk" / "stacks").glob("role_policies*.py"))

#: Write grants that land under an anonymously-readable prefix ON PURPOSE. The value is
#: the reason the artifact is meant for strangers. Adding a row is the deliberate act.
PUBLIC_BY_INTENT: dict[str, str] = {
    "generated/*": "the broad serve grant for site-output producers (OG cards, public_stats, journal posts) — ADR-046's CloudFront-served output prefix",
    "generated/podcast/*": "the published podcast audio — anonymous readers ARE the feed's audience",
    "generated/podcast/debrief/*": "the debrief episodes of that same published feed",
    "generated/panelcast/*": "the published panelcast audio, same reasoning as the podcast feed",
    "generated/assets/images/editorial/*": "editorial images embedded in published posts — they load for every reader",
    "generated/coach_daily.json": "the coach surface the public site renders on every page load",
    "generated/coach_memoirs.json": "published coach memoirs, served to readers on the coaching pages",
    "generated/qa_archive/text/*": "the public Q&A archive — the answers are published deliberately",
    "generated/journal/*": "published journal posts — the writing the story pages serve to readers",
    "blog/*": "the blog tree, anonymously readable by its own PublicReadBlog grant for the same reason",
    "site/*": "the static site itself — PublicReadSite exists so browsers can fetch it",
    "site/journal/*": "published journal pages inside that same static site",
}

WRITE_FACETS = {"needs_s3_write", "extra_s3_write"}


def anonymously_readable_prefixes() -> list[str]:
    """Derived from the committed bucket policy — never retyped here (#3559's rule)."""
    doc = json.loads(POLICY.read_text())
    out: list[str] = []
    for st in doc.get("Statement", []):
        if st.get("Effect") != "Allow":
            continue
        if st.get("Principal") not in ("*", {"AWS": "*"}):
            continue
        res = st.get("Resource")
        for r in [res] if isinstance(res, str) else (res or []):
            _, _, tail = r.partition(":::")
            _, _, key = tail.partition("/")
            if key:
                out.append(key.rstrip("*"))
    return out


def declared_write_prefixes() -> dict[str, str]:
    """{prefix: "file:line"} for every string literal in a write-grant list."""
    found: dict[str, str] = {}
    for path in ROLE_FILES:
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.keyword) or node.arg not in WRITE_FACETS:
                continue
            if not isinstance(node.value, (ast.List, ast.Tuple)):
                continue
            for elt in node.value.elts:
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                    found.setdefault(elt.value, f"{path.name}:{elt.lineno}")
    return found


def _public_writes(prefixes: dict[str, str]) -> dict[str, str]:
    public = anonymously_readable_prefixes()
    return {p: where for p, where in prefixes.items() if any(p.startswith(pub) for pub in public)}


# ── the guard ─────────────────────────────────────────────────────────────────
def test_the_policy_parser_sees_the_public_prefixes():
    """NEGATIVE CONTROL — a parser returning [] would make every test below vacuous."""
    public = anonymously_readable_prefixes()
    assert "generated/" in public, f"the generated/ public grant is invisible to the parser: {public}"
    assert "site/" in public


def test_the_grant_scan_sees_the_write_facets():
    """NEGATIVE CONTROL — same reason, other side."""
    prefixes = declared_write_prefixes()
    assert len(prefixes) >= 15, f"only {len(prefixes)} write prefixes found — the AST scan has gone blind"
    assert "recap/*" in prefixes, "the recap card's own grant is not visible to this scan"


def test_every_public_write_is_declared_intentional():
    """THE RULE. A new grant under an anonymously-readable prefix reds until someone says
    it is meant for strangers."""
    undeclared = {p: w for p, w in _public_writes(declared_write_prefixes()).items() if p not in PUBLIC_BY_INTENT}
    assert not undeclared, (
        "write grant(s) land under an anonymously-readable prefix with no declared intent:\n  "
        + "\n  ".join(f"{p}  ({w})" for p, w in sorted(undeclared.items()))
        + "\n\nAnything written here is world-readable at a derivable key, with or without CloudFront "
        "(#3559, #3741). Either move the prefix off the public tree, or add it to PUBLIC_BY_INTENT "
        "with the reason strangers are meant to read it."
    )


def test_the_rule_catches_the_two_defects_it_was_written_for():
    """MUST-FAIL CONTROL, using the REAL historical prefixes rather than a synthetic one."""
    public = anonymously_readable_prefixes()
    for shipped in ("generated/recap/*", "generated/board_questions/*", "generated/findings/*"):
        assert any(shipped.startswith(p) for p in public), f"{shipped} is not seen as public — the rule is inert"
        assert shipped not in PUBLIC_BY_INTENT, f"{shipped} must never be declared intentional — it was the defect"


def test_the_registry_has_no_dead_rows():
    """Shrink-only hygiene: a declared prefix nothing grants any more is stale."""
    granted = set(declared_write_prefixes())
    dead = sorted(p for p in PUBLIC_BY_INTENT if p not in granted)
    assert not dead, "PUBLIC_BY_INTENT names prefix(es) no role grants any more — prune them:\n  " + "\n  ".join(dead)


def test_every_declared_row_states_a_reason():
    thin = sorted(p for p, why in PUBLIC_BY_INTENT.items() if len(why.strip()) < 30)
    assert not thin, f"declared public prefixes with no real reason: {thin}"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
