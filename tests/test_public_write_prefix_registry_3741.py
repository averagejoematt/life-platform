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
    "generated/assets/images/*": (
        "the OG share cards (`og_image()`, WR-17) — a share card's whole purpose is to be fetched by a "
        "stranger's social client from a link preview, so anonymous read is the feature. Surfaced on "
        "2026-09-14 when #3758 taught this scan to read bare PolicyStatements: the grant had been live and "
        "undeclared since WR-17, correct all along and never once reviewed as a public-write decision."
    ),
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


#: S3 actions that put bytes somewhere. `s3:*` counts: a wildcard over a public prefix is
#: the widest possible version of the defect this file exists for.
_S3_WRITE_ACTIONS = ("s3:PutObject", "s3:PutObjectAcl", "s3:DeleteObject", "s3:*")


def _bucket_relative(node) -> str | None:
    """The key part of a resource expression, for the two spellings the roles use.

    `f"{BUCKET_ARN}/generated/foo/*"` is an f-string whose first piece is the bucket and
    whose second is a literal key; a plain string resource is handled too. Anything more
    dynamic than that returns None and is reported by its own test below, because a
    resource this scan cannot read is a resource it cannot police.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        _, sep, tail = node.value.partition(":::")
        if not sep:
            return None
        _, _, key = tail.partition("/")
        return key or None
    if isinstance(node, ast.JoinedStr):
        text = ""
        for part in node.values:
            if isinstance(part, ast.Constant) and isinstance(part.value, str):
                text += part.value
            else:
                text += "\x00"  # an interpolation — the bucket arn, or a region/account
        _, _, key = text.partition("/")
        return key if key and "\x00" not in key else None
    return None


def _raw_statement_write_prefixes() -> dict[str, str]:
    """Write prefixes granted by a hand-written `iam.PolicyStatement`, not a facet.

    THE BLIND SPOT THIS CLOSES (#3758). Until now this file scanned only the
    `needs_s3_write` / `extra_s3_write` keyword arguments of the role FACTORY helpers,
    because every S3 write in the estate went through one. The telegram worker's
    progress-photo grant is the first written as a bare `PolicyStatement`, and it went
    straight past the scan — the grant was invisible, and would have stayed invisible
    if its prefix had been `generated/` instead of `raw/`.

    That is the same failure this whole file is about, one level up: #3559 and #3741 each
    guarded the WRITERS they knew about, and this guarded the SPELLING it knew about.
    A rule that only sees one way of saying a thing is a rule with a bypass, and the
    bypass is always found by accident.
    """
    found: dict[str, str] = {}
    for path in ROLE_FILES:
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
            if name != "PolicyStatement":
                continue
            kw = {k.arg: k.value for k in node.keywords if k.arg}
            actions = kw.get("actions")
            if not isinstance(actions, (ast.List, ast.Tuple)):
                continue
            literals = [e.value for e in actions.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
            if not any(a in _S3_WRITE_ACTIONS for a in literals):
                continue
            resources = kw.get("resources")
            for elt in getattr(resources, "elts", []):
                key = _bucket_relative(elt)
                if key:
                    found.setdefault(key, f"{path.name}:{elt.lineno}")
    return found


def declared_write_prefixes() -> dict[str, str]:
    """{prefix: "file:line"} for every write prefix, in EITHER spelling."""
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
    for prefix, where in _raw_statement_write_prefixes().items():
        found.setdefault(prefix, where)
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


def test_the_grant_scan_sees_a_bare_policy_statement_too(tmp_path):
    """NEGATIVE CONTROL for the #3758 blind spot, on a synthetic role file.

    The live assertion below it names a real grant; this one proves the parser would
    catch the dangerous version — a bare `PolicyStatement` writing under `generated/` —
    which by construction does not exist in the repo and so cannot be asserted live.
    """
    fake = tmp_path / "role_policies_fake.py"
    fake.write_text(
        "import x as iam\n"
        "BUCKET_ARN = 'arn:aws:s3:::b'\n"
        "def r():\n"
        "    return [iam.PolicyStatement(sid='S', actions=['s3:PutObject'],\n"
        '        resources=[f"{BUCKET_ARN}/generated/sneaky/*"])]\n'
    )
    global ROLE_FILES
    saved, ROLE_FILES = ROLE_FILES, [fake]
    try:
        found = declared_write_prefixes()
    finally:
        ROLE_FILES = saved
    assert "generated/sneaky/*" in found, "a bare PolicyStatement write is invisible to the scan"
    assert _public_writes(found), "and therefore would not be judged against PUBLIC_BY_INTENT"


def test_the_bare_statement_written_for_3758_is_actually_seen():
    """The live half: the first real grant in that spelling is in the scan's output."""
    found = declared_write_prefixes()
    assert "raw/matthew/progress_photos/*" in found, (
        "the telegram worker's progress-photo write grant is invisible to this scan — " "the blind spot #3758 closed has reopened"
    )
    assert not _public_writes(
        {"raw/matthew/progress_photos/*": found["raw/matthew/progress_photos/*"]}
    ), "progress photos are Tier-2 owner-only; a public read grant over that prefix is an incident, not a config change"


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
