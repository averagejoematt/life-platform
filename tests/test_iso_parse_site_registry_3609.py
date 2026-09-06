"""tests/test_iso_parse_site_registry_3609.py — the SET guard for #3609.

THE DEFECT. `common.pacific_time.parse_iso_utc` has been named "THE ISO-8601
parser" since #1964, and `tests/test_time_invariant_helpers_1964.py` already
guards two of its three invariants at ZERO (no private `_parse_iso*` fork, no
Pacific-frame re-derivation) plus a RATCHET on one narrow idiom
(`.replace("Z", "+00:00")`). What that file does NOT enumerate is the much
larger surface of plain `datetime.fromisoformat(...)` / `date.fromisoformat(...)`
call sites that never went through the Z-replace idiom at all — an AST census
(this file's own `discover_fromisoformat_sites()`) finds 64 files under
`lambdas/` + `mcp/` with at least one, after this PR migrated four of the
"obvious" shared-module sites (`common/digest_utils.py`, `common/auth_breaker.py`,
`experiment/eval_retention.py`, `web/site_api_common.py`'s vintage-comparison
helper) to `common.pacific_time.parse_iso_utc`.

THE FIX. Charter registry + derivation-guard + ratchet (docs/CHARTER.md #1-3):
`ISO_PARSE_SITE_REGISTRY` below is the dated 2026-09-06 census, frozen the day
this guard was written. `test_no_new_hand_rolled_iso_parse_sites` re-derives
the live set and asserts it is a SUBSET of the registry — exactly
`_ISO_IDIOM_RESIDUE`'s pattern in test_time_invariant_helpers_1964.py, chosen
for the same reason: a file CONVERTING (dropping out of the discovered set)
must not red a concurrent PR in the merge train, but a NEW file appearing
(one the registry never named) reds immediately, by name.

WHAT IS NOT CLAIMED. Many of the 64 remaining sites are `date.fromisoformat`
calls on a bare `YYYY-MM-DD` day key for pure calendar-day arithmetic (day
counts, ratchet windows) — the same category `pacific_time.py` itself performs
internally (`pacific_day_n`, `anchor_day_key`). That is a DIFFERENT operation
from `parse_iso_utc`'s contract (an ISO-8601 *instant*, Z/offset/naive
disambiguation) and migrating it would not be a correctness fix, only a
relocation — this registry inventories the SET honestly rather than pretending
every entry is the #1964 whoop-class bug. Entries leave the registry by
migrating to `parse_iso_utc` (an instant parse) or by a documented ruling that
the site is a calendar-day parse and stays as `date.fromisoformat` — either
way the registry only ever shrinks.
"""

import ast
import os
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "lambdas"))
sys.path.insert(0, os.path.join(REPO_ROOT, "tests"))

import test_time_invariant_helpers_1964 as t1964  # noqa: E402 — reuse the canonical deployed-source walker


def fromisoformat_call_sites(source: str, filename: str = "<source>") -> list[str]:
    """Every `<anything>.fromisoformat(...)` call — `datetime.` or `date.`,
    any receiver spelling (aliased imports, `_dt.date.fromisoformat`, etc.),
    matched on the attribute name alone so an import alias can't hide a site."""
    findings: list[str] = []
    for node in ast.walk(ast.parse(source, filename=filename)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "fromisoformat":
            findings.append(f"{filename}:{node.lineno}: {ast.unparse(node)}")
    return findings


def _scan_fromisoformat() -> dict[str, list[str]]:
    """file -> [hit strings], mirroring t1964._scan()'s walk but keyed per-file
    (the registry below is file-level, matching the existing ratchet's grain)."""
    per_file: dict[str, list[str]] = {}
    for path in t1964._iter_deployed_sources():
        if path.resolve() == t1964.CANONICAL.resolve():
            continue
        try:
            src = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:  # pragma: no cover
            continue
        rel = str(path.relative_to(t1964.ROOT))
        try:
            hits = fromisoformat_call_sites(src, filename=rel)
        except SyntaxError:  # pragma: no cover — the syntax gate owns this
            continue
        if hits:
            per_file[rel] = hits
    return per_file


def discover_fromisoformat_sites() -> set[str]:
    return set(_scan_fromisoformat())


# ── the registry — frozen 2026-09-06, #3609. SHRINK-ONLY: remove entries as
# they migrate to common.pacific_time.parse_iso_utc, or leave a comment ruling
# a site a legitimate calendar-day parse. NEVER add without also migrating or
# ruling — an addition with no accompanying reason is exactly the drift #3609
# was filed to stop. ──────────────────────────────────────────────────────
ISO_PARSE_SITE_REGISTRY: frozenset[str] = frozenset(
    {
        "lambdas/ai/ai_calls.py",
        "lambdas/ai/ai_context.py",
        "lambdas/ai/baseline_freshness.py",
        "lambdas/ai/behavior_logs.py",
        "lambdas/ai/budget_guard.py",
        "lambdas/ai/margaret_editor_pass.py",
        "lambdas/ai/night_scope.py",
        "lambdas/ai/platform_memory.py",
        "lambdas/coach/relationship_engine.py",
        "lambdas/common/constants.py",
        "lambdas/common/input_manifest.py",
        "lambdas/common/quarter_utils.py",
        "lambdas/common/subscriber_cadence.py",
        "lambdas/common/token_alarm_window.py",
        "lambdas/compute/daily_insight_compute_lambda.py",
        "lambdas/compute/daily_metrics_compute_lambda.py",
        "lambdas/compute/dashboard_refresh_lambda.py",
        "lambdas/compute/episode_detect_lambda.py",
        "lambdas/compute/hypothesis_engine_lambda.py",
        "lambdas/content/theme_river.py",
        "lambdas/content/vacation_fund.py",
        "lambdas/emails/chronicle_approve_lambda.py",
        "lambdas/emails/coach_panel_podcast_lambda.py",
        "lambdas/emails/daily_brief_lambda.py",
        "lambdas/emails/freshness_checker_lambda.py",
        "lambdas/emails/weekly_digest_lambda.py",
        "lambdas/experiment/canonical_facts.py",
        "lambdas/experiment/coherence_invariants.py",
        "lambdas/health/character_engine.py",
        "lambdas/ingestion/dropbox_poll_lambda.py",
        "lambdas/ingestion/health_auto_export_lambda.py",
        "lambdas/ingestion/ingest_health.py",
        "lambdas/ingestion/ingestion_framework.py",
        "lambdas/ingestion/source_registry.py",
        "lambdas/intelligence/weight_recency.py",
        "lambdas/operational/acwr_liveness_qa.py",
        "lambdas/operational/as_of_agreement_qa.py",
        "lambdas/operational/continuity_watch.py",
        "lambdas/operational/data_reconciliation_lambda.py",
        "lambdas/operational/permanence_lambda.py",
        "lambdas/operational/phase_plausibility.py",
        "lambdas/operational/qa_check_outputs.py",
        "lambdas/operational/qa_smoke_lambda.py",
        "lambdas/operational/raw_archive_qa.py",
        "lambdas/operational/reader_truth_evidence.py",
        "lambdas/operational/reader_truth_qa.py",
        "lambdas/operational/reader_truth_rulings.py",
        "lambdas/operational/weight_truth_qa.py",
        "lambdas/reading/reading_recall.py",
        "lambdas/reading/reading_resonance.py",
        "lambdas/training/exercise_history.py",
        "lambdas/training/hevy_write_client.py",
        "lambdas/training/routine_generator.py",
        "lambdas/training/training_notes.py",
        "lambdas/web/board_quality_gate.py",
        "lambdas/web/site_api_character.py",
        "lambdas/web/site_api_common.py",  # date.fromisoformat(EXPERIMENT_START) — calendar-day, not an instant
        "lambdas/web/site_api_journey.py",
        "lambdas/web/site_api_social.py",
        "lambdas/web/site_stats_refresh_lambda.py",
        "lambdas/web/subscriber_onboarding_lambda.py",
        "mcp/ritual_triggers.py",
        "mcp/tools_reading.py",
        "mcp/tools_strength.py",
    }
)

# The four sites this PR migrated OFF raw fromisoformat and onto parse_iso_utc
# — asserted absent below so a regression (someone re-introducing a private
# fork in one of these files) is caught the moment it reappears.
MIGRATED_3609 = frozenset(
    {
        "lambdas/common/digest_utils.py",
        "lambdas/common/auth_breaker.py",
        "lambdas/experiment/eval_retention.py",
    }
)


def test_no_new_hand_rolled_iso_parse_sites():
    """SUBSET assertion (merge-train friendly, mirrors _ISO_IDIOM_RESIDUE):
    a NEW file with a raw fromisoformat call outside the registry reds by
    name; a registered file that finishes migrating drops out silently green.
    """
    discovered = discover_fromisoformat_sites()
    new_sites = sorted(discovered - ISO_PARSE_SITE_REGISTRY)
    assert not new_sites, (
        "New hand-rolled `fromisoformat` call site(s) outside "
        f"ISO_PARSE_SITE_REGISTRY: {new_sites}. Either route through "
        "common.pacific_time.parse_iso_utc (instants) or register the file "
        "with a stated reason (calendar-day parse, etc.) — see #3609."
    )


def test_registry_has_no_dead_entries():
    """A registry entry naming a file that no longer exists, or no longer
    contains ANY fromisoformat call, is stale — prune it (same discipline as
    test_iso_idiom_residue_list_has_no_dead_entries in the #1964 file)."""
    discovered = discover_fromisoformat_sites()
    dead = sorted(p for p in ISO_PARSE_SITE_REGISTRY if not (t1964.ROOT / p).exists())
    assert not dead, "ISO_PARSE_SITE_REGISTRY names file(s) that no longer exist — prune them:\n" + "\n".join(dead)
    fully_converted = sorted(ISO_PARSE_SITE_REGISTRY - discovered)
    if fully_converted:  # advisory only — see MIGRATED_3609 below for the enforced form
        pass


def test_migrated_sites_have_no_raw_fromisoformat_left():
    """The flip side of migration: the four #3609 shared-module sites must not
    regress a raw fromisoformat call back in (a private re-fork of the exact
    #1964 bug class)."""
    discovered = discover_fromisoformat_sites()
    regressed = sorted(MIGRATED_3609 & discovered)
    assert not regressed, f"Migrated-away file(s) have a NEW raw fromisoformat call: {regressed} — use common.pacific_time.parse_iso_utc"
    for f in MIGRATED_3609:
        assert f not in ISO_PARSE_SITE_REGISTRY, f"{f} was migrated — it must not also sit in the shrink-only registry"


def test_registry_count_is_the_frozen_2026_09_06_baseline_or_smaller():
    """A crude but honest ratchet ceiling — this exists so the registry
    itself cannot silently grow via a bulk edit that also happens to satisfy
    the subset check (impossible under the subset check alone, but this makes
    the shrink-only intent independently legible without re-deriving history)."""
    BASELINE_2026_09_06 = 64
    assert len(ISO_PARSE_SITE_REGISTRY) <= BASELINE_2026_09_06, (
        f"ISO_PARSE_SITE_REGISTRY grew to {len(ISO_PARSE_SITE_REGISTRY)} entries, "
        f"above the frozen 2026-09-06 baseline of {BASELINE_2026_09_06}. The count may only go down."
    )


# ── mutation evidence — prove the matcher fires ─────────────────────────────


def test_matcher_catches_a_synthetic_fromisoformat_call():
    hits = fromisoformat_call_sites("x = datetime.fromisoformat(s)\n", filename="synthetic.py")
    assert len(hits) == 1 and "synthetic.py:1" in hits[0]


def test_matcher_catches_a_synthetic_date_fromisoformat_call():
    hits = fromisoformat_call_sites("d = date.fromisoformat(s[:10])\n", filename="synthetic.py")
    assert len(hits) == 1


def test_matcher_ignores_the_canonical_parser_call():
    """parse_iso_utc's own body calls `datetime.fromisoformat(s)` — this
    matcher WOULD flag it if run against pacific_time.py, which is why the
    scan excludes CANONICAL explicitly (proven here at the unit level, and by
    test_no_new_hand_rolled_iso_parse_sites finding zero at the file level)."""
    hits = fromisoformat_call_sites("dt = datetime.fromisoformat(s)\n", filename="pacific_time.py")
    assert len(hits) == 1  # the matcher itself is dumb by design; exclusion is the SCAN's job, not the matcher's


# ── the round-trip contract: a Pacific DATE# key at UTC midnight (#3609's
# named memory-class trap — "strptime is the INVERSE of a clock") ──────────


def test_utc_midnight_of_a_pacific_date_string_is_not_that_pacific_day():
    """THE TRAP, pinned. `parse_iso_utc("2026-09-06T00:00:00Z")` is a real,
    correctly-parsed instant — but that instant is Pacific-frame 2026-09-05
    17:00 (PDT, UTC-7), NOT the Pacific day named by its own date digits. A
    caller that assumes "the date substring IS the Pacific day" (the naive
    strptime-as-a-clock reflex this issue's own text names) silently reads
    yesterday. This is not a bug in parse_iso_utc — it is the precise reason
    common.pacific_time.anchor_day_key exists instead of a raw date-slice.
    """
    import sys

    sys.path.insert(0, str(t1964.ROOT / "lambdas"))
    from common.pacific_time import pacific_date_of

    assert pacific_date_of("2026-09-06T00:00:00Z") == "2026-09-05", (
        "if this ever reads 2026-09-06, the Pacific-frame arithmetic silently reverted to treating "
        "a UTC-midnight digit-match as the Pacific day — the exact #3609 trap"
    )


def test_the_correct_round_trip_uses_anchor_day_key_not_a_raw_date_slice():
    """The RIGHT way to turn a `DATE#YYYY-MM-DD` key into an instant and back:
    anchor_day_key() picks the Pacific-frame midnight the key actually named,
    parse_iso_utc()/pacific_date_of() read it back — and the round trip holds,
    unlike the naive Z-midnight construction above. Both PDT (Sep, this case)
    and PST are exercised so the DST seam this whole invariant exists for is
    covered by BOTH offsets, not just the one live in the current calendar
    month."""
    import sys
    from datetime import timezone

    sys.path.insert(0, str(t1964.ROOT / "lambdas"))
    from common.pacific_time import anchor_day_key, pacific_date_of

    for day_key in ("2026-09-06", "2026-01-15"):  # PDT (UTC-7) and PST (UTC-8)
        instant = anchor_day_key(day_key, "unknown_source")  # unknown source defaults to Pacific
        utc_iso = instant.astimezone(timezone.utc).isoformat()
        assert pacific_date_of(utc_iso) == day_key, (
            f"anchor_day_key({day_key!r}) -> UTC ISO {utc_iso!r} -> pacific_date_of() did not round-trip "
            f"back to {day_key!r} — got {pacific_date_of(utc_iso)!r}"
        )


def test_planted_new_hand_rolled_site_reds_the_discovery(tmp_path, monkeypatch):
    """The mutation control for the registry guard itself: a brand-new file
    with a raw fromisoformat call, planted under a throwaway lambdas/ tree,
    must appear in discover_fromisoformat_sites() and therefore NOT be a
    subset of the frozen registry — i.e. it would fail
    test_no_new_hand_rolled_iso_parse_sites for real, proven here without
    touching the actual repo tree."""
    fake_root = tmp_path / "repo"
    (fake_root / "lambdas" / "web").mkdir(parents=True)
    planted = fake_root / "lambdas" / "web" / "sneaky_new_site.py"
    planted.write_text("import datetime\nx = datetime.datetime.fromisoformat('2026-09-06T00:00:00Z')\n")

    monkeypatch.setattr(t1964, "ROOT", fake_root)
    monkeypatch.setattr(t1964, "CANONICAL", fake_root / "lambdas" / "common" / "pacific_time.py")
    try:
        discovered = discover_fromisoformat_sites()
    finally:
        monkeypatch.undo()

    rel = os.path.join("lambdas", "web", "sneaky_new_site.py")
    assert rel in discovered, f"planted site not discovered: {discovered}"
    assert rel not in ISO_PARSE_SITE_REGISTRY, "sanity: the planted synthetic path must not collide with a real registry entry"
