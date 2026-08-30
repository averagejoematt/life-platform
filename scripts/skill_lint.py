#!/usr/bin/env python3
"""scripts/skill_lint.py — the contract gate for Claude Code skills and agents.

THE DEFECT CLASS
  The 23 skills that drive this platform were prose that nothing checked. An audit on
  2026-08-27 found, in a corpus nobody had ever linted:

    * 0 of 23 with YAML frontmatter — the model picking a skill saw a truncated first
      body line, and 7 files opened with an H1 slug echo ("# /journey-review — ...")
      rather than anything resembling "use when";
    * `qa.md` shelling `PAGES_BY_PATH['$PATH']` inside double quotes, so $PATH expanded
      to the system PATH and that mode raised KeyError on every invocation;
    * `accuracy-review.md`'s `full` mode instructing the session to run
      `scratchpad/.../wf_truth_audit.js` — a path with a literal ellipsis, resolving to
      nothing, present nowhere in the tree;
    * `sdlc-review.md` handing its grading lenses "~380 test files" against a real 964,
      and "~85 scripts" against 138 — anchors 2.5x off, used to grade "asset or drag";
    * three separate files routing won't-do items to "pointer issue #423", CLOSED;
    * `journey-review.md` — the ritual whose entire job is finding drift — auditing four
      of seven chat modes and hunting a string (`until #1478`) that no longer exists.

  Every one is silent. A skill with a dead reference does not raise; it misleads a
  session, which then improvises. That is the platform's signature failure shape (a
  thing that reports success without doing its job) applied to its own instructions.

THE SHAPE (charter primitives, applied to the corpus that had none of them)
  registry          scripts/skill_registry.py — enumerated from the filesystem, never
                    a hand-typed list, so a new skill is linted the moment it exists.
  contract          frontmatter well-formed; description written for SELECTION; paths
                    that resolve; no conditional pointer at a closed issue.
  ratchet           NO_CONTRACT_TEST is dated, counted and down-only.
  dead-man          the operating calendar's SET guard (scripts/operating_calendar.py).
  mutation proof    --self-test plants each defect and asserts this gate FAILS on it.
                    Per docs/CONVENTIONS.md §9 a gate never watched failing is not yet
                    a gate; #2578's own census counted ten libraries as gates on a
                    filename substring precisely because nobody made it fail.

NO THIRD-PARTY IMPORTS, DELIBERATELY
  Frontmatter is parsed by hand rather than with PyYAML. #3234: the reconcile job
  installs no packages, so `gate_census` raised ModuleNotFoundError, was swallowed to
  None, and the job reported `success` while leaving main drifted — twice. A gate that
  can be made dark by a missing dependency is a gate with an off switch nobody watches.
  This one runs anywhere Python does: CI, a git hook, a laptop.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _registry():
    spec = importlib.util.spec_from_file_location("_skill_registry", Path(__file__).resolve().parent / "skill_registry.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── The ratchet ───────────────────────────────────────────────────────────────
# Skills with no contract test anywhere in tests/. Dated, counted, DOWN-ONLY: adding a
# name here is a deliberate act with a date attached, and the count may never rise.
# 17 of 23 at adoption (2026-08-27) — the six that had one were exactly the six that had
# been rewritten after an incident.
# 2026-08-30 (#3250): six rows pruned — accuracy-review, craft-review, journey-review,
# platform-review, sdlc-review and site-review were folded into the one `/review` spine and no
# longer exist as skills. The ceiling drops with them (17 -> 10, the exact remaining count): a
# ratchet whose ceiling stays put while the corpus shrinks is headroom nobody voted for. The
# replacement, `review`, is NOT added here — it ships with a contract test.
NO_CONTRACT_TEST: dict[str, str] = {
    "cost-diligence": "2026-08-27",
    "daily-debrief": "2026-08-27",
    "design-implement": "2026-08-27",
    "design-sync": "2026-08-27",
    "frontier-plan": "2026-08-27",
    "interview": "2026-08-27",
    "open-checkin": "2026-08-27",
    "speak-to-coaches": "2026-08-27",
    "team-meeting": "2026-08-27",
    "uplevel": "2026-08-27",
}
RATCHET_CEILING = 10

MIN_DESCRIPTION = 80

#: Directories a referenced path must live under to be treated as a repo path worth
#: resolving. Anything else (a URL, an AWS ARN, an npm package) is not our business.
_REPO_PREFIXES = (
    "docs/",
    "scripts/",
    "tests/",
    "deploy/",
    "lambdas/",
    "mcp/",
    "site/",
    "config/",
    "cdk/",
    ".github/",
    ".claude/",
    "handovers/",
    "ci/",
    "model/",
    "remediation/",
)

#: A path carrying one of these is a TEMPLATE (`docs/reviews/REVIEW_<date>.md`) and is
#: resolved by pattern, not literally. Distinct from an ellipsis, which is a hole.
_TEMPLATE_MARKERS = ("<", ">", "{", "}", "*", "$", "|")

#: An elided path cannot be followed by anyone. `scratchpad/.../wf_truth_audit.js` is the
#: found instance; it was the central instruction of a review mode for two months.
_ELLIPSIS = ("...", "…")

#: Conditional pointers at an issue — the shapes the audit actually found stale. A bare
#: "#953" mention is usually a citation of history and is NOT flagged.
#: BLIND SPOT, STATED: a stale pointer phrased outside these shapes is not detected. The
#: check is deliberately narrow — a detector that under-reports costs a missed finding,
#: whereas a broad one would flag every historical citation and be turned off.
_POINTER_PATTERNS = [
    re.compile(r"pointer issue[^\n]{0,20}#(\d+)", re.I),
    re.compile(r"until\s+#(\d+)\s+ships", re.I),
    re.compile(r"when that (?:wiring|tool) lands\s*\(#(\d+)\)", re.I),
    re.compile(r"until that tool exists", re.I),
    re.compile(r"linked to epic\s+#(\d+)", re.I),
]


#: References that are CORRECTLY absent — the prose says so. wrap.md deleting a script
#: and keeping its epitaph is the behaviour to copy, not a defect to flag. Dated, and
#: each row must name why, so this list is reviewable rather than a silencer.
TOMBSTONED_REFS: dict[tuple[str, str], str] = {
    (
        ".claude/skills/wrap/SKILL.md",
        "scripts/check_story_labels.py",
    ): "2026-08-27: deleted by #2252, tombstoned in-file two lines below (#1872 absorbed its rule)",
    (
        ".claude/agents/issue-filer.md",
        ".github/ISSUE_TEMPLATE/",
    ): "2026-08-27: retired by #1324; the line exists to say re-adding one is a lint failure",
}


class Finding:
    def __init__(self, kind: str, target: str, message: str, line: int | None = None):
        self.kind, self.target, self.message, self.line = kind, target, message, line

    def __str__(self) -> str:
        where = f"{self.target}:{self.line}" if self.line else self.target
        return f"  [{self.kind}] {where}\n      {self.message}"


# ── Frontmatter (hand-parsed; see the module docstring for why) ────────────────
def parse_frontmatter(text: str) -> tuple[dict[str, str] | None, str]:
    """Return (fields, body). fields is None when there is no `---` block at all."""
    if not text.startswith("---\n"):
        return None, text
    end = text.find("\n---\n", 3)
    if end == -1:
        return None, text
    block, body = text[4 : end + 1], text[end + 5 :]
    fields: dict[str, str] = {}
    key = None
    for raw in block.splitlines():
        if not raw.strip():
            continue
        m = re.match(r"^([A-Za-z][A-Za-z0-9_-]*):\s*(.*)$", raw)
        if m and not raw.startswith((" ", "\t")):
            key = m.group(1)
            val = m.group(2).strip()
            # `>` / `|` open a folded or literal block scalar whose value is the INDENTED
            # lines beneath. Treating them as an empty value reported three agents as
            # having a 1-char description when each had a good one — a parser bug that
            # would have read as a real finding.
            fields[key] = "" if val in (">", "|", ">-", "|-") else _unquote(val)
        elif key is not None and raw.startswith((" ", "\t")):
            cont = raw.strip()
            if cont.startswith("- "):
                cont = cont[2:].strip()
                fields[key] = f"{fields[key]},{cont}" if fields[key] else cont
            else:
                fields[key] = f"{fields[key]} {cont}".strip()
    return fields, body


def _unquote(v: str) -> str:
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        return v[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return v


# ── Checks ────────────────────────────────────────────────────────────────────
def check_frontmatter(name: str, rel: str, fields: dict[str, str] | None, is_agent: bool) -> list[Finding]:
    out: list[Finding] = []
    if fields is None:
        return [Finding("frontmatter", rel, "no YAML frontmatter — the model sees a truncated first body line when choosing")]
    if fields.get("name") != name:
        out.append(Finding("frontmatter", rel, f"name is {fields.get('name')!r}, expected {name!r}"))
    desc = fields.get("description", "")
    if not desc:
        out.append(Finding("frontmatter", rel, "no description — nothing tells a session when to reach for this"))
    elif len(desc) < MIN_DESCRIPTION:
        out.append(Finding("frontmatter", rel, f"description is {len(desc)} chars, minimum {MIN_DESCRIPTION}"))
    elif desc.strip().lstrip("/").lower().startswith(name.lower()) and len(desc) < MIN_DESCRIPTION * 2:
        out.append(Finding("frontmatter", rel, "description restates the name — a slug echo does not help a model choose"))
    tools_key = "tools" if is_agent else "allowed-tools"
    if not fields.get(tools_key):
        out.append(Finding("frontmatter", rel, f"no {tools_key} — runs with unrestricted tool access"))
    return out


def check_references(rel: str, body: str) -> list[Finding]:
    """Every repo path named in backticks must resolve. Ellipsis paths never can.

    A `path:LINE` citation is checked for the LINE too. #2619's lesson: COACH_STANCE.md
    carried 18 of 27 file:line citations pointing at the wrong place while its `Verified`
    stamp was green, because the stamp compared DATES and nothing ever re-derived the
    anchors. A citation that survives only because nobody followed it is not a citation.
    """
    out: list[Finding] = []
    seen: set[str] = set()
    for lineno, line in enumerate(body.splitlines(), start=1):
        for tok in re.findall(r"`([^`\n]+)`", line):
            tok = tok.strip().split()[0].rstrip(".,;:)")
            if not tok.startswith(_REPO_PREFIXES):
                continue
            path, anchor = tok, None
            if "::" in path:  # a symbol reference: lambdas/coach/x.py::SYMBOL
                path, anchor = path.split("::", 1)
            m = re.match(r"^(.*?):(\d+)$", path)  # a line citation: docs/X.md:48
            target_line = int(m.group(2)) if m else None
            if m:
                path = m.group(1)
            key = f"{rel}|{tok}"
            if key in seen or (rel, path) in TOMBSTONED_REFS:
                continue
            if any(e in path for e in _ELLIPSIS):
                seen.add(key)
                out.append(Finding("dead-ref", rel, f"`{path}` contains an ellipsis — nobody can follow it", lineno))
                continue
            if any(mk in path for mk in _TEMPLATE_MARKERS):
                continue
            fp = ROOT / path
            if not fp.exists():
                seen.add(key)
                out.append(Finding("dead-ref", rel, f"`{path}` does not exist", lineno))
                continue
            if _is_gitignored(path):
                # Exists HERE and nowhere else. This is the local-pass/CI-fail split, and
                # it bit on 2026-08-27: design-implement pointed sessions at
                # `.claude/worktrees/`, which is gitignored, so the gate passed on a
                # machine carrying stale worktrees and failed in a clean checkout. Judging
                # by tracked-ness rather than by os.path.exists makes the verdict identical
                # everywhere — the property a gate needs before anyone can trust it.
                seen.add(key)
                out.append(
                    Finding("dead-ref", rel, f"`{path}` is gitignored — it exists only on this machine, never in a clean checkout", lineno)
                )
                continue
            if target_line is not None and fp.is_file():
                n = len(fp.read_text(encoding="utf-8", errors="replace").splitlines())
                if target_line > n:
                    seen.add(key)
                    out.append(Finding("dead-ref", rel, f"`{path}:{target_line}` cites past end of file ({n} lines)", lineno))
            if anchor and fp.is_file() and anchor not in fp.read_text(encoding="utf-8", errors="replace"):
                seen.add(key)
                out.append(Finding("dead-ref", rel, f"`{path}::{anchor}` — symbol not found in that file", lineno))
    return out


_IGNORE_CACHE: dict[str, bool] = {}


def _is_gitignored(path: str) -> bool:
    """True if git refuses to track `path` (so CI will never see it)."""
    if path in _IGNORE_CACHE:
        return _IGNORE_CACHE[path]
    try:
        r = subprocess.run(["git", "check-ignore", "-q", path], cwd=ROOT, capture_output=True, timeout=10)
        _IGNORE_CACHE[path] = r.returncode == 0
    except Exception:
        _IGNORE_CACHE[path] = False  # fail OPEN: a missing git must not invent findings
    return _IGNORE_CACHE[path]


def _issue_state(num: str, cache: dict[str, str | None]) -> str | None:
    if num in cache:
        return cache[num]
    try:
        r = subprocess.run(
            ["gh", "issue", "view", num, "--json", "state", "-q", ".state"],
            capture_output=True,
            text=True,
            timeout=20,
            cwd=ROOT,
        )
        cache[num] = r.stdout.strip() if r.returncode == 0 else None
    except Exception:
        cache[num] = None
    return cache[num]


def check_pointers(rel: str, body: str, cache: dict[str, str | None], online: bool) -> list[Finding]:
    out: list[Finding] = []
    for lineno, line in enumerate(body.splitlines(), start=1):
        for pat in _POINTER_PATTERNS:
            m = pat.search(line)
            if not m:
                continue
            if not m.groups():
                out.append(Finding("stale-pointer", rel, f"conditional on a tool that may now exist: {line.strip()[:90]}", lineno))
                continue
            num = m.group(1)
            if not online:
                continue
            if _issue_state(num, cache) == "CLOSED":
                out.append(Finding("stale-pointer", rel, f"live pointer at #{num}, which is CLOSED", lineno))
    return out


def has_contract_test(name: str) -> bool:
    """A contract test names this skill's prompt file, or resolves it BY NAME.

    Deliberately strict. A looser version — "any test that imports the registry and
    mentions the name" — counted `tests/test_operating_calendar_2832.py` as a contract
    test for five skills, because the cadence registry quotes their names. That test
    asserts the file EXISTS; it says nothing about what the skill must contain. Accepting
    it would have shrunk the ratchet by five without a single new assertion, which is
    laundering debt rather than paying it, and a ratchet that can be satisfied by a
    technicality is not a ratchet.

    So: reference the prompt path, or call `require_skill("<name>")` with the literal.
    """
    reg = _registry()
    p = reg.skill_path(name)
    if p is None:
        return False
    rel_path = reg.rel(p)
    calls = (f'require_skill("{name}")', f"require_skill('{name}')")
    for f in (ROOT / "tests").glob("*.py"):
        try:
            src = f.read_text(encoding="utf-8")
        except Exception:
            continue
        if rel_path in src or any(c in src for c in calls):
            return True
    return False


# ── Driver ────────────────────────────────────────────────────────────────────
def lint(online: bool = True) -> tuple[list[Finding], dict]:
    reg = _registry()
    findings: list[Finding] = []
    cache: dict[str, str | None] = {}

    for dupe in reg.duplicates():
        findings.append(Finding("shadow", dupe, "exists in BOTH .claude/skills/ and .claude/commands/ — one silently shadows the other"))

    reference_files = 0
    for name, path in reg.skills().items():
        rel = reg.rel(path)
        text = path.read_text(encoding="utf-8")
        fields, body = parse_frontmatter(text)
        findings += check_frontmatter(name, rel, fields, is_agent=False)
        findings += check_references(rel, body)
        findings += check_pointers(rel, body, cache, online)
        # Progressive-disclosure content is instruction too, and #3250 moved the bulk of the
        # review corpus into it: seven rubrics, carrying nearly every path citation and every
        # stale-pointer risk those files ever had. A lint whose scope stops at SKILL.md would
        # have kept reporting a clean corpus over exactly the text that decayed before —
        # the scope has to follow the content, or the gate quietly starts measuring nothing.
        # Frontmatter is deliberately NOT required here: a reference is loaded by name from
        # its skill, never selected by a model reading descriptions.
        for ref in reg.skill_references(name):
            if ref.suffix != ".md":
                continue
            reference_files += 1
            ref_rel = reg.rel(ref)
            ref_text = ref.read_text(encoding="utf-8")
            findings += check_references(ref_rel, ref_text)
            findings += check_pointers(ref_rel, ref_text, cache, online)

    for name, path in reg.agents().items():
        rel = reg.rel(path)
        text = path.read_text(encoding="utf-8")
        fields, body = parse_frontmatter(text)
        findings += check_frontmatter(name, rel, fields, is_agent=True)
        findings += check_references(rel, body)
        findings += check_pointers(rel, body, cache, online)

    # Ratchet: the exemption list may only shrink, and may not name a skill that is gone.
    missing = sorted(n for n in NO_CONTRACT_TEST if n not in reg.skills())
    for n in missing:
        findings.append(Finding("ratchet", n, "exempted from the contract-test ratchet but no such skill exists — prune the row"))
    escaped = sorted(n for n in NO_CONTRACT_TEST if has_contract_test(n))
    if len(NO_CONTRACT_TEST) > RATCHET_CEILING:
        findings.append(
            Finding(
                "ratchet",
                "NO_CONTRACT_TEST",
                f"{len(NO_CONTRACT_TEST)} entries exceeds the ceiling of {RATCHET_CEILING} — the ratchet only turns down",
            )
        )
    newly = sorted(n for n in reg.skills() if n not in NO_CONTRACT_TEST and not has_contract_test(n))
    for n in newly:
        findings.append(Finding("ratchet", n, "no contract test and not on the dated exemption list — add a test, or add a dated row"))

    stats = {
        "skills": len(reg.skills()),
        "references": reference_files,
        "agents": len(reg.agents()),
        "exempt": len(NO_CONTRACT_TEST),
        "ceiling": RATCHET_CEILING,
        "can_retire": escaped,
        "online": online,
    }
    return findings, stats


def main() -> int:
    ap = argparse.ArgumentParser(description="Lint the Claude Code skill/agent corpus.")
    ap.add_argument("--offline", action="store_true", help="skip the issue-state lookups (no gh)")
    ap.add_argument("--self-test", action="store_true", help="mutation proof: plant each defect, assert this gate fails")
    args = ap.parse_args()

    if args.self_test:
        return self_test()

    online = not args.offline and bool(_which_gh())
    if not args.offline and not online:
        print("  [skip] gh unavailable — issue-pointer checks did not run (this is a REDUCED lint, not a pass)")

    findings, stats = lint(online=online)
    print(
        f"skill-lint: {stats['skills']} skills ({stats['references']} reference files), "
        f"{stats['agents']} agents, {stats['exempt']}/{stats['ceiling']} on the contract-test ratchet"
    )
    if stats["can_retire"]:
        print(f"  [ratchet] these now HAVE a contract test and should be removed from NO_CONTRACT_TEST: {', '.join(stats['can_retire'])}")
    if not findings:
        print("✅ skill corpus clean.")
        return 0
    by_kind: dict[str, list[Finding]] = {}
    for f in findings:
        by_kind.setdefault(f.kind, []).append(f)
    for kind in sorted(by_kind):
        print(f"\n{kind} ({len(by_kind[kind])}):")
        for f in by_kind[kind]:
            print(f)
    print(f"\n❌ {len(findings)} finding(s) across the skill corpus.")
    return 1


def _which_gh() -> bool:
    try:
        return subprocess.run(["gh", "--version"], capture_output=True, timeout=10).returncode == 0
    except Exception:
        return False


def self_test() -> int:
    """Plant each defect this gate claims to catch and assert it actually fails.

    A negative control that cannot fail is indistinguishable from a passing one — the
    exact trap that inverted a live finding on 2026-08-27 (a CloudWatch query against a
    log group that did not exist returned 0 events and read as "latent"). So each case
    below asserts a POSITIVE (the planted defect is reported) and the suite ends with a
    control asserting the clean tree reports nothing.
    """
    import shutil
    import tempfile

    reg = _registry()
    cases = [
        ("no frontmatter", lambda t: t.split("---\n", 2)[2], "frontmatter"),
        ("stripped description", lambda t: re.sub(r"\ndescription: [^\n]*\n", "\n", t, count=1), "frontmatter"),
        ("stripped allowed-tools", lambda t: re.sub(r"\nallowed-tools: [^\n]*\n", "\n", t, count=1), "frontmatter"),
        ("dead reference", lambda t: t + "\n\nSee `docs/THIS_FILE_DOES_NOT_EXIST.md` for details.\n", "dead-ref"),
        ("ellipsis path", lambda t: t + "\n\nRun `scripts/.../ghost.py` first.\n", "dead-ref"),
    ]
    victim = reg.require_skill("qa")
    original = victim.read_text(encoding="utf-8")
    # A real on-disk backup, not just the in-memory copy: this mutates a TRACKED file,
    # and a hard kill between the mutation and the finally would otherwise leave it edited.
    fd, backup = tempfile.mkstemp(suffix=".skill-lint-backup.md")
    os.close(fd)
    shutil.copy2(victim, backup)
    failures = []
    try:
        for label, mutate, expect_kind in cases:
            victim.write_text(mutate(original), encoding="utf-8")
            findings, _ = lint(online=False)
            hit = [f for f in findings if f.kind == expect_kind and f.target.endswith("qa/SKILL.md")]
            status = "CAUGHT" if hit else "MISSED"
            print(f"  {status:7} {label}  ->  {expect_kind}")
            if not hit:
                failures.append(label)
        victim.write_text(original, encoding="utf-8")
        findings, _ = lint(online=False)
        residual = [f for f in findings if f.target.endswith("qa/SKILL.md")]
        print(f"  {'CLEAN' if not residual else 'DIRTY':7} positive control (unmutated qa reports nothing)")
        if residual:
            failures.append("positive control")
    finally:
        shutil.copy2(backup, victim)
        os.unlink(backup)

    # #3250: the scope now includes progressive-disclosure references, where the review corpus
    # actually lives. Scope that was never watched failing is scope nobody can trust — so plant
    # a dead reference in a real reference file and assert this gate reports it.
    refs = [r for name in reg.skills() for r in reg.skill_references(name) if r.suffix == ".md"]
    if not refs:
        print("  MISSED  reference-file scope  ->  no reference files exist to prove it on")
        failures.append("reference-file scope (no fixture)")
    else:
        ref_victim = refs[0]
        ref_original = ref_victim.read_text(encoding="utf-8")
        fd2, ref_backup = tempfile.mkstemp(suffix=".skill-lint-ref-backup.md")
        os.close(fd2)
        shutil.copy2(ref_victim, ref_backup)
        try:
            ref_victim.write_text(ref_original + "\n\nSee `docs/NO_SUCH_REFERENCE_DOC.md`.\n", encoding="utf-8")
            findings, _ = lint(online=False)
            hit = [f for f in findings if f.kind == "dead-ref" and f.target == reg.rel(ref_victim)]
            print(f"  {'CAUGHT' if hit else 'MISSED':7} dead reference in {reg.rel(ref_victim)}  ->  dead-ref")
            if not hit:
                failures.append("reference-file scope")
            ref_victim.write_text(ref_original, encoding="utf-8")
            findings, _ = lint(online=False)
            residual = [f for f in findings if f.target == reg.rel(ref_victim)]
            print(f"  {'CLEAN' if not residual else 'DIRTY':7} positive control (unmutated reference reports nothing)")
            if residual:
                failures.append("reference positive control")
        finally:
            shutil.copy2(ref_backup, ref_victim)
            os.unlink(ref_backup)
    if failures:
        print(f"\n❌ self-test: {len(failures)} case(s) the gate did NOT catch: {', '.join(failures)}")
        return 1
    print("\n✅ self-test: every planted defect was caught, and the clean tree is clean.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
