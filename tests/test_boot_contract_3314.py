"""tests/test_boot_contract_3314.py — the boot contract (#3314, epic #2842).

Defect class owned: the boot-from-prose drift the charter exists to kill. A session or
routine that derives the architecture from CLAUDE.md prose re-creates every hand-typed
count the #2844 guard retired. The contract says what a boot reads FROM THE MODEL
(scripts/boot_brief.py::BOOT_CONTRACT) and this file pins that the contract is real:

  * registry ↔ model — every contract path resolves in the committed model;
  * derivation guard — the rendered brief's numbers ARE the model's, never restated;
  * the boot is a consumer — the SessionStart hook renders the brief, and settings.json
    registers that hook (a contract nobody boots through is prose with a test);
  * it can fail — a mutated model changes the brief; a self-inconsistent model renders
    STALE (the dead-man a hand-edit trips);
  * prose may not disagree — CLAUDE.md's hand-stated copies of a boot fact match the
    model or are absent.

Plus the #3314 facet pins on the model itself: the alarm plane equals the #795
inventory (+ composites) with routing traced, the privacy plane matches field_tiers.py,
and the schedules plane matches the lambdas plane.

Run:  python3 -m pytest tests/test_boot_contract_3314.py -v
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import pathlib
import re
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import boot_brief as bb  # noqa: E402

MODEL = bb.load_model()
NOW = dt.datetime(2026, 8, 31, 15, 30, tzinfo=dt.timezone.utc)


def _load_by_path(rel: str, name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


# ── registry ↔ model ──────────────────────────────────────────────────────────


def test_every_contract_fact_resolves_in_the_committed_model():
    for fact in bb.BOOT_CONTRACT:
        if fact.path.startswith("derived:"):
            continue
        bb.resolve(MODEL, fact.path)  # KeyError = the contract names a fact the model does not carry


def test_contract_keys_are_unique_and_explained():
    keys = [f.key for f in bb.BOOT_CONTRACT]
    assert len(keys) == len(set(keys))
    assert all(len(f.why) > 15 for f in bb.BOOT_CONTRACT), "a boot fact without a why is a number nobody needs"


# ── derivation guard: the brief IS the model ─────────────────────────────────


def test_brief_numbers_equal_the_model_counts():
    lines = "\n".join(bb.render_lines(MODEL, NOW))
    counts = MODEL["meta"]["counts"]
    assert f"{counts['lambdas']} lambdas" in lines
    assert f"{counts['alarms']} ·" in lines
    assert f"{counts['partitions']} partitions" in lines
    assert f"{counts['edges']} edges" in lines
    assert f"{counts['mcp_tools']} MCP tools" in lines
    for routing, n in counts["alarms_by_routing"].items():
        assert f"{routing} {n}" in lines
    assert MODEL["privacy"]["consent"]["adr"] in lines


def test_facts_json_carries_every_contract_key():
    f = bb.facts(MODEL, NOW)
    for fact in bb.BOOT_CONTRACT:
        assert fact.key in f
    assert f["_consistency"] == [], f"the committed model is not self-consistent: {f['_consistency']}"


def test_next_runs_are_clock_ordered_after_now():
    runs = bb.next_runs(MODEL, NOW, n=3)
    assert len(runs) == 3
    assert all(r["utc"] > "15:30" for r in runs), runs
    assert runs == sorted(runs, key=lambda r: (r["utc"], r["lambda"]))
    # wraps past midnight: at 23:59 the next run is the earliest of the day
    late = bb.next_runs(MODEL, NOW.replace(hour=23, minute=59), n=1)[0]
    assert late["utc"] == min(r["utc"] for r in MODEL["schedules"] if r.get("utc"))


# ── the boot is a consumer ───────────────────────────────────────────────────


def test_session_start_hook_renders_the_brief():
    hook = (ROOT / "scripts" / "hooks" / "session_preflight.py").read_text(encoding="utf-8")
    assert "boot_brief.py" in hook and "render_lines" in hook, "the SessionStart hook no longer consumes the model"
    settings = json.loads((ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))
    commands = [h["command"] for entry in settings["hooks"]["SessionStart"] for h in entry["hooks"]]
    assert any("session_preflight.py" in c for c in commands), "session_preflight.py is not the registered SessionStart hook"


def test_hook_prints_model_lines_end_to_end():
    env = dict(os.environ, CLAUDE_HOOK_INERT="1")
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "hooks" / "session_preflight.py")],
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
        cwd=ROOT,
    )
    assert proc.returncode == 0, proc.stderr
    assert "  model       CONSISTENT" in proc.stdout, proc.stdout
    assert f"{MODEL['meta']['counts']['lambdas']} lambdas" in proc.stdout
    assert "UNVERIFIED (boot brief failed" not in proc.stdout


def test_cli_json_and_text_forms_run():
    for extra in ([], ["--json"]):
        proc = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "boot_brief.py"), *extra], capture_output=True, text=True, timeout=60, cwd=ROOT
        )
        assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["lambdas"] == MODEL["meta"]["counts"]["lambdas"]


# ── it can fail ──────────────────────────────────────────────────────────────


def test_mutation_a_changed_count_changes_the_brief():
    mutated = json.loads(json.dumps(MODEL))
    mutated["meta"]["counts"]["lambdas"] += 1
    assert bb.render_lines(mutated, NOW) != bb.render_lines(MODEL, NOW)


def test_dead_man_an_inconsistent_model_renders_stale():
    mutated = json.loads(json.dumps(MODEL))
    mutated["meta"]["counts"]["alarms"] -= 1  # a hand-edit to the summary, planes untouched
    problems = bb.consistency(mutated)
    assert problems and "meta.counts.alarms" in problems[0]
    lines = bb.render_lines(mutated, NOW)
    assert lines[0].startswith("  model       STALE"), lines[0]
    assert "generate_platform_model.py" in lines[0]


def test_dead_man_a_non_model_file_is_named_not_rendered():
    assert bb.consistency({"lambdas": {}}) == ["meta.counts missing — not a generated model"]


def test_hook_survives_a_missing_model(tmp_path, monkeypatch):
    """The hook must degrade to an explicit UNVERIFIED line, never crash or go blank."""
    hook_src = (ROOT / "scripts" / "hooks" / "session_preflight.py").read_text(encoding="utf-8")
    assert "UNVERIFIED (boot brief failed" in hook_src
    with pytest.raises(FileNotFoundError):
        bb.load_model(tmp_path / "absent.json")


# ── prose may not disagree ───────────────────────────────────────────────────


def test_claude_md_hand_stated_boot_facts_agree_with_the_model():
    """CLAUDE.md may point at the model; where it still states a boot fact's number, the
    number must be the model's. Drift here is fixed by deleting the number (preferred) or
    regenerating — never by editing the model."""
    text = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    counts = MODEL["meta"]["counts"]
    claims = {
        "lambdas": re.findall(r"~?(\d+) Lambdas\b", text),
        "mcp_tools": re.findall(r"~?(\d+) tools across", text),
    }
    for key, found in claims.items():
        for n in found:
            assert int(n) == counts[key], f"CLAUDE.md states {n} for {key}; the model says {counts[key]} — delete the number or regenerate"


def test_charter_points_the_boot_at_the_model():
    charter = (ROOT / "docs" / "CHARTER.md").read_text(encoding="utf-8")
    assert "boot_brief.py" in charter, "the charter's Session boot bullet must name the boot brief"
    assert "platform_model.json" in charter


# ── the CLAUDE.md shrink-only ratchet (#4271 box 4) ──────────────────────────
# CLAUDE.md is the boot input every session pays for. Measured as bytes // 4 (the
# issue's `wc -c`/4 — bytes, not characters, and no tokenizer, so CI stays offline and
# deterministic). The ceiling only moves DOWN: test 1 stops growth, test 2 forces every
# shrink to be banked in the same diff (the UNPROVEN_CEILING_HIGH_WATER shape). Stack
# concurrent edits like BASELINE_TOTAL_GATES and re-measure at merge, never by arithmetic.
# Demote when: CLAUDE.md sits at or below the 3,500-token target for 30 days — the
# ratchet becomes a flat cap and test 2 is deleted.
# 7081 (2026-10-01, fd20ad99f, 28,326 B) -> 3497 (2026-10-01, boxes 1-3 on 1b3177f8b, 13,990 B).
CLAUDE_MD_TOKEN_CEILING = 3497  # Target 3500 (#4271) — met. Down-only.
CLAUDE_MD_TOKEN_SLACK = 100  # ~400 B a PR may shrink by before it must lower the ceiling
# Box 3 landed: the status block is the convention paragraph plus ONE pointer line, which
# `/wrap` step (b) rewrites in place (date only). Its pre-box-3 byte cap is retired.
_STATUS_HEADING = "## Session status"
_STATUS_POINTER = re.compile(r"^\*\*Status:\*\* see handovers/HANDOVER_LATEST\.md \(Verified \d{4}-\d{2}-\d{2}\)$")


def _claude_md_bytes() -> bytes:
    return (ROOT / "CLAUDE.md").read_bytes()


def _largest_sections(raw: bytes, n: int = 3) -> list[tuple[str, int]]:
    sections: dict[str, int] = {}
    current = "(preamble)"
    for line in raw.decode("utf-8").splitlines(keepends=True):
        if line.startswith("## "):
            current = line.strip()
        sections[current] = sections.get(current, 0) + len(line.encode("utf-8"))
    return sorted(sections.items(), key=lambda kv: -kv[1])[:n]


def _status_block(raw: bytes) -> str:
    text = raw.decode("utf-8")
    at = text.find("\n" + _STATUS_HEADING)
    assert at >= 0, f"CLAUDE.md has no `{_STATUS_HEADING}` heading — the wrap convention's block is gone"
    return text[at + 1 :]


def test_claude_md_does_not_grow_past_its_token_ceiling():
    raw = _claude_md_bytes()
    tokens = len(raw) // 4
    over = len(raw) - CLAUDE_MD_TOKEN_CEILING * 4
    assert tokens <= CLAUDE_MD_TOKEN_CEILING, (
        f"CLAUDE.md is {tokens} tokens ({len(raw)} B), {over} B over the down-only ceiling "
        f"{CLAUDE_MD_TOKEN_CEILING} (#4271). Largest sections: {_largest_sections(raw)} — "
        "move history into its ADR or a pointer; never raise the ceiling."
    )


def test_claude_md_token_ceiling_is_banked_after_a_shrink():
    tokens = len(_claude_md_bytes()) // 4
    assert CLAUDE_MD_TOKEN_CEILING - tokens <= CLAUDE_MD_TOKEN_SLACK, (
        f"CLAUDE.md shrank to {tokens} tokens but CLAUDE_MD_TOKEN_CEILING is still "
        f"{CLAUDE_MD_TOKEN_CEILING} — lower it to {tokens} in this diff so the shrink is banked (#4271)."
    )


def test_claude_md_status_block_holds_its_shape():
    """The status block is the convention paragraph plus exactly one pointer line, last in
    the file — the session narrative lives in handovers/HANDOVER_LATEST.md (#4271 box 3)."""
    block = _status_block(_claude_md_bytes())
    pointers = [ln for ln in block.splitlines() if ln.startswith("**Status:**")]
    last = block.rstrip("\n").splitlines()[-1]
    assert len(pointers) == 1 and _STATUS_POINTER.match(last), (
        f"the CLAUDE.md status block must end in exactly one line matching {_STATUS_POINTER.pattern} — "
        f"found {pointers!r}, last line {last[:120]!r}; `/wrap` (b) rewrites that line's date, never a paragraph (#4271)."
    )
    paragraphs = [p for p in block.split("\n\n") if p.strip()]
    assert len(paragraphs) <= 3, (
        f"the status block has {len(paragraphs)} paragraphs (heading + convention + pointer is the shape) — "
        "a session paragraph crept back in; it belongs in handovers/HANDOVER_LATEST.md (#4271)."
    )


# ── the #3314 facets on the model itself ─────────────────────────────────────


def test_alarm_plane_is_the_795_inventory_plus_composites():
    ad = _load_by_path("deploy/alarm_discovery.py", "_ad_for_test")
    inventory = ad._auto_discover_alarm_names()
    assert inventory is not None and len(inventory) >= 100
    modeled = set(MODEL["alarms"])
    assert inventory <= modeled, f"inventory names missing from the model: {sorted(inventory - modeled)}"
    composites = {n for n, a in MODEL["alarms"].items() if a["kind"] == "composite"}
    assert modeled - inventory == composites, "the model may exceed the inventory ONLY by composite alarms"
    assert len(MODEL["alarms"]) == ad._auto_discover_alarm_count() + len(composites)


def test_alarm_routing_known_truths():
    a = MODEL["alarms"]
    assert a["life-platform-canary-ddb-failure"]["routing"] == "digest+paging"  # _canary_alarm(page=True)
    assert a["life-platform-canary-ddb-failure"]["via"] == "factory:_canary_alarm"
    # #3505: the spend ceiling routes THROUGH the genesis composite pair now (the same
    # shape #2116 gave the platform token total), so the raw alarm carries no routing of
    # its own and the paging half is the `-urgent` composite.
    assert a["ai-daily-spend-high"]["routing"] == "via-composite"
    assert set(a["ai-daily-spend-high"]["composites"]) == {"ai-daily-spend-high-urgent", "ai-daily-spend-high-genesis-window"}
    assert a["ai-daily-spend-high-urgent"]["routing"] == "urgent"
    assert a["ai-daily-spend-high-genesis-window"]["routing"] == "digest"
    assert a["ingest-liveness-heartbeat"]["routing"] == "digest"  # _heartbeat_alarm → digest
    assert a["email-subscriber-errors"]["via"] == "helper:add_web_alarms"
    assert a["ai-tokens-platform-daily-total"]["routing"] == "via-composite"
    assert set(a["ai-tokens-platform-daily-total"]["composites"]) == {
        "ai-tokens-platform-daily-total-urgent",
        "ai-tokens-platform-daily-total-genesis-window",
    }
    assert a["ai-tokens-platform-daily-total-urgent"]["routing"] == "urgent"
    assert a["ingest-auth-unhealthy-dropbox"]["via"] == "factory:_alarm"  # a loop-templated name, expanded
    unresolved = sorted(n for n, r in a.items() if r["routing"] == "unresolved")
    assert not unresolved, f"routing regressed to unresolved for: {unresolved}"


def test_stack_helper_names_are_unique():
    """The routing tracer resolves a helper by bare name; a collision would route one
    stack's alarms by another's helper — pinned so the assumption cannot rot silently."""
    import ast

    import platform_model_alarms as pma  # scripts/ is on sys.path above

    seen: dict[str, str] = {}
    for stack, tree in pma._stack_trees().items():
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and pma._is_alarm_factory(node):
                assert (
                    node.name not in seen or seen[node.name] == stack
                ), f"alarm factory {node.name} defined in {seen[node.name]} and {stack}"
                seen[node.name] = stack


def test_privacy_plane_matches_field_tiers():
    ft = _load_by_path("lambdas/privacy/field_tiers.py", "_ft_for_test")
    priv = MODEL["privacy"]
    names = {0: "public", 1: "internal", 2: "owner_only", 3: "owner_published"}
    assert priv["sources"] == {s: names[t] for s, t in ft.SOURCE_TIERS.items()}
    assert priv["fields"] == {s: {f: names[t] for f, t in fs.items()} for s, fs in ft.FIELD_TIERS.items()}
    assert priv["consent"] == {"adr": ft.OWNER_CONSENT_ADR, "date": ft.OWNER_CONSENT_DATE}
    assert MODEL["partitions"]["labs"]["privacy_tier"] == "owner_published"
    assert MODEL["partitions"]["genome"]["privacy_tier"] == "owner_only"
    assert "vascular_age" in MODEL["partitions"]["withings"]["owner_only_fields"]
    assert MODEL["partitions"]["whoop"]["privacy_tier"] == "public"  # unlisted = public by omission


def test_schedules_plane_matches_the_lambdas_plane():
    expected = sum(len(rec["schedules"]) for rec in MODEL["lambdas"].values())
    assert len(MODEL["schedules"]) == expected == MODEL["meta"]["counts"]["schedules"]
    fixed = [r for r in MODEL["schedules"] if r["utc"]]
    assert all(re.fullmatch(r"\d{2}:\d{2}", r["utc"]) for r in fixed)
    daily_brief = [r for r in MODEL["schedules"] if r["lambda"] == "daily-brief"]
    assert daily_brief and daily_brief[0]["utc"] == "17:00"  # the 17:00 UTC brief CLAUDE.md describes
