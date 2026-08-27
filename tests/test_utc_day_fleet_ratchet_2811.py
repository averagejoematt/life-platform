"""tests/test_utc_day_fleet_ratchet_2811.py — the FLEET half of the PT-day contract (#2811, epic #2798).

THE CONTRACT THIS GUARDS, STATED ONCE
─────────────────────────────────────
**The platform's day boundary is Pacific.** DynamoDB `DATE#{YYYY-MM-DD}` keys name
Pacific calendar days (`ingestion_framework.py`: "DATE# keys are Pacific calendar
days", truth audit 2026-07-10), the site renders Pacific end-to-end (#2506), and the
generation gates adjudicate Pacific days (#2675 — a UTC gate blessed the wrong day
every PT evening). `common.pacific_time` is the ONE place that frame is constructed
(#1964); `pacific_today()` / `pacific_now()` are how the rest of the fleet asks for it.

**EventBridge crons are UTC-fixed and that is unrelated.** A cron *schedule* is not a
data *day*. Most of the fleet's naive-UTC-day sites were invisible for exactly that
reason: the daily compute crons fire at 16:00–17:00 UTC, i.e. 09:00–10:00 PT, where
the UTC and Pacific calendar days agree — so the defect is *schedule-masked* and only
surfaces on a retry, a redrive, a manual invoke, or an interactive call after 17:00 PT.
Schedule-masked is not fixed; it is a latent wrong answer with a timer on it.

WHY A SECOND GUARD AND NOT MORE OF #2414
────────────────────────────────────────
`tests/test_pacific_today_guard_2414.py` holds a **zero** over a reader-shaped surface
(`lambdas/web/` + named reader-bound writers). Its acceptance is "no sites at all", and
that must stay true. This file guards a *different, larger* surface — the compute /
ingestion / coach / intelligence packages, plus `lambdas/emails/` and `mcp/` since
#2817 — under a **shrink-only ratchet**, so the class can be frozen fleet-wide before it
is fully drained. The AST predicates are IMPORTED from the #2414 module rather than
re-implemented: a forked matcher that drifts from the original is the exact failure this
epic keeps finding ("guard the SET, not the instance" — a second copy is a second
instance).

THE BOUNDARY, HONESTLY DRAWN — day semantics vs. an instant
───────────────────────────────────────────────────────────
Not every `datetime.utcnow()` is a day-boundary bug, and a guard that says otherwise
gets muted. This scan flags a site **only when a calendar DAY is derived** from a
UTC-anchored or naive clock — the value that then becomes a `DATE#` key, a query bound,
a `day_n`, an ISO-week label, or a generation date. Concretely:

  FLAGGED (day semantics)
    * `date.today()` / `datetime.today()` — a naive clock whose *return value is a day*.
    * `.date()` on a UTC/naive now (directly, through `timedelta` arithmetic, or through
      a same-file tainted intermediate).
    * `.strftime("%Y-%m-%d")` / an f-string `{...:%Y-%m-%d}` on a UTC/naive now — a
      date-ONLY format, i.e. one naming the day and carrying no clock time.
    * `.isocalendar()` on a UTC/naive now — an ISO-week label is a day-derived label.
    * `.isoformat()[:10]` / `str(...)[:10]` on a UTC/naive now — the slice idiom, which
      is a date-only rendering wearing an instant's clothes. (#2414 does not match this
      face; it is added here rather than there because it is a fleet idiom.)

  NOT FLAGGED (instants — deliberately out of scope)
    * `datetime.now(timezone.utc)` on its own, `.isoformat()`, `.timestamp()`, epoch and
      TTL arithmetic, and any `strftime` format carrying `%H`/`%M`/`%S`. A stored instant
      is frame-free; only its DAY rendering has a frame. Withings' HMAC nonce
      (`int(datetime.now().timestamp())`) is the canonical example: a naive clock, a real
      #1964-class smell, and *not* this class — flagging it would teach the reader to
      ignore this guard.
    * An explicit `.astimezone(...)` before the day rendering. A named frame choice is
      what this guard exists to force; having made one, you are done.
    * A site carrying `# utc-exempt(#NNNN): <reason>` on the line or up to three lines
      above — the written-down exemption. Genuinely-UTC computations live here.

THE RATCHET
───────────
`_UTC_DAY_RESIDUE` maps a repo-relative file to the MAXIMUM day-semantics sites it may
contain. It only ever shrinks (the `_ISO_IDIOM_RESIDUE` precedent, #1964): a file over
its number reds, a file absent from the map must be at zero, an entry naming a file that
no longer exists must be pruned, and an entry whose file has reached zero must be pruned
so the ratchet cannot silently license a regrowth back up to the old number.

**The map was empty when #2811 shipped, and that was a measurement, not an oversight.**
The 2026-08-25 epic audit measured 96 naive-UTC-day sites in `lambdas/` outside `web/`;
of those, 111 day-semantics sites fell in the first four packages, and #2811's sweep
converted all of them (4 took inline `utc-exempt(#2811)` markers instead — Habitify's UTC
deadline comparison, the Strava/Whoop reconcile windows, which bound UTC-epoch API
requests rather than DDB keys, and health_auto_export's `logger.set_date` correlation id,
which is a CloudWatch log dimension on a webhook that keys its records off the payload's
own dates, never off "today").

**#2817 added the two packages #2811 named as the follow-up**, and they arrived with the
entries #2811 predicted. Measured against `origin/main` @ `1812f01f8`:
`lambdas/emails/` 60 sites / 18 files → **0**, `mcp/` 89 sites / 24 files → **12**, all
12 in two files whose fix was blocked on a writer in an unguarded package.
Nothing in either package was ruled genuinely-UTC: unlike `lambdas/ingestion/`, neither
talks to a vendor whose day boundary is UTC, and the one `logger.set_date` there follows
the fleet's `pacific_today()` convention rather than #2811's instant-derived exception.

**#2798 paid those two entries off by bringing their PARTNERS onto the surface** —
`lambdas/reading/` (4 sites / 3 files), `lambdas/training/` (3 / 2) and
`lambdas/operational/` (21 / 12), measured against `origin/main` @ `d3d68d75f`. Each pair
converted on both sides in one change: `reading_store.log_session`'s session `date` with
`mcp/tools_reading._input_streak`, and the routine `target_date` WRITE KEY with
`hevy_routine_cron` / `hevy_restamp` / `exercise_history`. **One file was ruled
genuinely-UTC** — `cost_governor_lambda.py`, whose days are Cost Explorer / AWS Budgets
days (the "billing calendar" case named below) — and it carries five
`# utc-exempt(#2798)` markers with the reason written down.
`test_residue_is_exactly_the_measured_coordination_debt` pins the map (now empty again)
so appending an entry — or quietly widening one — has to argue with a test.

**A shape guard is not a pair guard.** Two of #2798's fixes are structurally invisible to
the matcher below (`reading_store`'s `date = now[:10]`, a cross-function taint; the MCP
adherence check's `start_time[:10]`, a vendor instant). The AGREEMENT half of the contract
lives in `tests/test_pt_day_pair_contracts_2798.py`, which drives both sides of both pairs
at one PT-evening instant. Both files are load-bearing; neither subsumes the other.

**#2811 CLOSED ITS OWN BOX, AND FIRST HAD TO FIX THE INSTRUMENT MEASURING IT.**
The last five packages joined here — `lambdas/health/` (8 day-semantics sites),
`lambdas/common/` (6), `lambdas/experiment/` (5), `lambdas/ai/` (3) and `lambdas/privacy/`
(11 files, already at ZERO) — which makes the scanned surface the whole deployed bundle
minus the two packages that owe #2414's stricter zero. Exactly ONE site was ruled
genuinely-UTC: `ai/grounding_gate_params.py`'s fail-soft degrade, which is not a calendar
choice at all but the handler for `common.pacific_time` being unimportable.

But the 22-site figure that scoped this slice was a FLOOR, not a ceiling. `_is_day_slice`
and every other predicate bottomed out in `_subtree_dirty`, which asked only "a literal
clock, or a tainted NAME?" — so a day derived from a CALL (`_now_iso()[:10]`, or
`now = now or _now_iso()` then `now[:10]`) was structurally unreachable, and all three
pre-existing planted-site proofs plant the SAME `datetime.now(timezone.utc).strftime(...)`
shape, so none of them could ever have caught it. #2798's own PR body named that blindness
in prose and shipped without closing it. Closing it (`_clock_returning_functions` /
`_is_clock_fn_call` in the #2414 module, per-scope in `_taint_index`) immediately found a
23rd site: `reading/reading_store.py`'s `or now[:10]` FALLBACK — live, in a package two
consecutive slices had certified at zero, on the very line whose comment describes the
frame it was violating. The instrument was the last thing anyone had audited.

**#2798's LAST BOX: THE MATCHER COULD NOT SEE `import datetime`.**
The 2026-08-27 audit probed `utc_day_semantics_sites` with the six ordinary ways to
derive a calendar day. FOUR fired. TWO did not — and both were the plain
`import datetime` module form, where the class sits one attribute deeper than
`_owner_name` looked (`datetime.datetime.utcnow().strftime("%Y-%m-%d")` and
`datetime.date.today()`). #2812 taught the matcher the `from datetime import date as
_date` alias and stopped there; the fully-qualified chain walked past this ratchet AND
#2414's stricter zero for two further slices, and every planted-site proof above uses a
`from datetime import ...` spelling, so none of them could have caught it — the exact
shape of the CALL-slice blindness one paragraph up, repeating.

It was found by a control that came back EMPTY and was nearly published as "the surface
is clean": a shape the matcher cannot see returns precisely what a clean tree returns.
The fix is in the #2414 module's `_import_aliases` / `_owner_name` (one implementation,
two consumers). `test_a_planted_fully_qualified_site_reds_the_guard` pins both shapes
against the real text of a scanned file, and the fleet + #2414 surfaces were re-measured
with the fix in place: still ZERO. No live site was hiding behind the blindness — the
ban that keeps the surface at zero simply could not see one of the two commonest ways to
break it, which is a ratchet-integrity defect rather than an outage.

The vendor-instant face (`w["start_time"][:10]`) is deliberately still OUT of reach, and
that is a measurement rather than an omission — see
`test_a_blanket_ten_char_slice_ban_would_be_unlivable_and_is_deliberately_not_the_rule`.
It belongs to the pair guard, not the shape guard.

Run:  python3 -m pytest tests/test_utc_day_fleet_ratchet_2811.py -v
"""

import ast
import pathlib

# The #2414 matcher's predicates, imported rather than forked. Private names on
# purpose: they are that module's internals and this file is a second consumer of
# the SAME implementation, which is the whole point — a copy would drift.
from test_pacific_today_guard_2414 import (
    _EXEMPT_MARKER,
    _import_aliases,
    _is_day_only_fmt,
    _is_naive_clock,
    _owner_name,
    _subtree_dirty,
    _taint_index,
)

ROOT = pathlib.Path(__file__).resolve().parent.parent

_SKIP_PATH_MARKERS = ("__pycache__", "_staging", "cdk.out", "layer-build")

# The scanned surface: whole packages, globbed off the filesystem — never a hand-list.
# lambdas/web/ and lambdas/content/ are deliberately absent: they belong to #2414's
# ZERO surface and holding them here too would let this ratchet's (looser) contract
# be mistaken for theirs.
SURFACE_PACKAGES = (
    "lambdas/compute",
    "lambdas/ingestion",
    "lambdas/coach",
    "lambdas/intelligence",
    # #2817 — the named follow-up. `lambdas/emails/` (60 day-semantics sites in 18
    # files) and `mcp/` (89 in 24) were the two packages #2811 deliberately left out
    # because concurrent PRs owned those files that night. They arrived WITH residue
    # entries, exactly as #2811's docstring predicted.
    "lambdas/emails",
    "mcp",
    # #2798 — the PARTNER packages, joined here because they are the other half of the
    # two pairs #2817 held back. `lambdas/reading/` (4 sites) owns the session/recall day
    # `mcp/tools_reading.py` reads; `lambdas/training/` (3) + `lambdas/operational/` (21)
    # co-author the routine `target_date` WRITE KEY with `mcp/tools_hevy_routine.py`.
    # Adding them is what let `_UTC_DAY_RESIDUE` go back to empty.
    "lambdas/reading",
    "lambdas/training",
    "lambdas/operational",
    # #2811's own closing slice — the LAST five packages of the deployed tree
    # outside #2414's stricter zero surface. `lambdas/health/` (8 sites),
    # `lambdas/common/` (6), `lambdas/experiment/` (5), `lambdas/ai/` (3) and
    # `lambdas/privacy/` (11 files, ALREADY at zero — it joins clean, which is
    # worth having under the ratchet precisely so it stays that way).
    # With these, `lambdas/` ex-`web/`+`content/` is fully scanned: the surface is
    # now the whole deployed bundle minus the two packages that owe a stricter zero.
    "lambdas/health",
    "lambdas/common",
    "lambdas/experiment",
    "lambdas/ai",
    "lambdas/privacy",
)

# ── THE RATCHET. Repo-relative file -> maximum day-semantics sites allowed. ──
# Entries only ever come OUT (or get smaller). An entry is a DEBT, and the prose
# beside it is the debt's terms: what else has to move before the file can be fixed.
#
# THE MAP IS EMPTY AGAIN, AND THAT IS THE POINT OF #2798.
# It was empty when #2811 shipped. #2817 admitted exactly two entries — `mcp/tools_
# reading.py` and `mcp/tools_hevy_routine.py` — and neither was a budget: each named a
# WRITER, in a package outside the scanned surface, that had to move in the same change
# or the pair would split (the #2815 incident, stated as a data structure). #2798 is that
# same change: it brings `lambdas/reading/`, `lambdas/training/` and `lambdas/operational/`
# onto the surface and converts each pair on BOTH sides at once, so the debt is PAID and
# the entries are DELETED rather than shrunk. `test_residue_has_no_stale_entries` is what
# forces the deletion; `test_residue_is_exactly_the_measured_coordination_debt` is what
# stops the next slice from re-opening the map without a named, two-sided blocker.
_UTC_DAY_RESIDUE: dict[str, int] = {}


def _surface_files() -> list[pathlib.Path]:
    files: list[pathlib.Path] = []
    for pkg in SURFACE_PACKAGES:
        files += [p for p in (ROOT / pkg).rglob("*.py") if not any(m in str(p) for m in _SKIP_PATH_MARKERS)]
    return sorted(files)


def _is_day_slice(node, tainted: set, aliases: dict, clock_fns: frozenset = frozenset()) -> bool:
    """`<utc/naive now>.isoformat()[:10]` / `str(<utc/naive now>)[:10]` / `_now_iso()[:10]`.

    A ten-character prefix of an ISO-8601 rendering IS the calendar day — the same
    value `strftime("%Y-%m-%d")` produces, reached by a route #2414's matcher does
    not walk. Matched on the slice bound so `[:19]` (a timestamp) stays clean.

    The `clock_fns` arm is #2811's second pass: `_now_iso()[:10]` and
    `now = now or _now_iso()` → `now[:10]` are the shapes #2798 had to find BY HAND
    because a slice of a CALL is never tainted by a name-based matcher.
    """
    if not isinstance(node, ast.Subscript):
        return False
    sl = node.slice
    if not (isinstance(sl, ast.Slice) and sl.lower is None and sl.step is None):
        return False
    if not (isinstance(sl.upper, ast.Constant) and sl.upper.value == 10):
        return False
    return _subtree_dirty(node.value, tainted, aliases, clock_fns)


def utc_day_semantics_sites(source: str, filename: str = "<source>") -> list[str]:
    """Every place `source` derives a calendar DAY from a UTC-anchored or naive clock.

    The day-semantics subset of #2414's matcher (see the module docstring's boundary
    table) plus the `[:10]` slice face. A bare `datetime.utcnow()` whose value stays an
    instant is NOT a finding here.
    """
    tree = ast.parse(source, filename=filename)
    lines = source.splitlines()
    aliases = _import_aliases(tree)
    clock_fns, tainted_at = _taint_index(tree, aliases)
    findings: list[str] = []

    def _exempt(lineno: int) -> bool:
        for ln in range(max(1, lineno - 3), lineno + 1):
            if ln <= len(lines) and _EXEMPT_MARKER in lines[ln - 1]:
                return True
        return False

    def _flag(node, why: str) -> None:
        if not _exempt(node.lineno):
            findings.append(f"{filename}:{node.lineno}: {ast.unparse(node)}  [{why}]")

    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            attr = node.func.attr
            owner = _owner_name(node.func.value, aliases)
            tainted = tainted_at(node)
            # `date.today()` / `datetime.today()` — the naive clock that RETURNS a day.
            # `datetime.utcnow()` / a no-arg `datetime.now()` are naive clocks too, but
            # their value is an instant; they are findings only via a derivation below.
            if attr == "today" and owner in ("date", "datetime") and _is_naive_clock(node, aliases):
                _flag(node, "naive clock whose value IS a day")
                continue
            if attr == "strftime" and node.args and _is_day_only_fmt(getattr(node.args[0], "value", None)):
                if _subtree_dirty(node.func.value, tainted, aliases, clock_fns):
                    _flag(node, "date-only strftime on a UTC/naive now")
            elif attr == "date" and not node.args and _subtree_dirty(node.func.value, tainted, aliases, clock_fns):
                _flag(node, ".date() on a UTC/naive now")
            elif attr == "isocalendar" and _subtree_dirty(node.func.value, tainted, aliases, clock_fns):
                _flag(node, ".isocalendar() on a UTC/naive now")
        elif isinstance(node, ast.FormattedValue) and node.format_spec is not None:
            spec = "".join(str(v.value) for v in ast.walk(node.format_spec) if isinstance(v, ast.Constant))
            if _is_day_only_fmt(spec) and _subtree_dirty(node.value, tainted_at(node), aliases, clock_fns):
                _flag(node, "date-only f-string format on a UTC/naive now")
        elif isinstance(node, ast.Subscript) and _is_day_slice(node, tainted_at(node), aliases, clock_fns):
            _flag(node, "[:10] day slice of a UTC/naive now")
    return findings


def _measure() -> dict[str, int]:
    """Repo-relative file -> day-semantics site count, for every file with any."""
    counts: dict[str, int] = {}
    for path in _surface_files():
        rel = str(path.relative_to(ROOT))
        hits = utc_day_semantics_sites(path.read_text(encoding="utf-8"), filename=rel)
        if hits:
            counts[rel] = len(hits)
    return counts


# ── the surface itself ───────────────────────────────────────────────────────


def test_surface_is_derived_and_covers_every_scoped_package():
    """A glob that silently matches nothing is the classic dead-guard failure, and a
    package quietly dropping out of the tuple is how a ratchet stops ratcheting."""
    rels = {str(p.relative_to(ROOT)) for p in _surface_files()}
    assert len(rels) >= 100, f"suspiciously small fleet surface: {len(rels)} files"
    for pkg in SURFACE_PACKAGES:
        assert (ROOT / pkg).is_dir(), f"scanned package missing on disk: {pkg}"
        assert any(r.startswith(pkg + "/") for r in rels), f"glob matched nothing under {pkg}"
    # Spot-check the carriers these issues actually swept, one per package.
    for expected in (
        "lambdas/compute/hypothesis_engine_lambda.py",
        "lambdas/ingestion/enrichment_lambda.py",
        "lambdas/coach/coach_domain_facts.py",
        "lambdas/intelligence/intelligence_common.py",
        "lambdas/emails/freshness_checker_lambda.py",  # #2817 — 9 sites, the heaviest single file
        "mcp/tools_lifestyle.py",  # #2817 — 15 sites, the heaviest mcp file
        "lambdas/reading/reading_store.py",  # #2798 — the session-`date` writer of pair 1
        "lambdas/training/exercise_history.py",  # #2798 — bounds its window off the routine day
        "lambdas/operational/hevy_routine_cron_lambda.py",  # #2798 — the other author of `target_date`
        "lambdas/health/character_engine.py",  # #2811 close — 3 sites, the heaviest of the five
        "lambdas/common/qa_archive.py",  # #2811 close — the archive DAY partition
        "lambdas/experiment/eyeball_calibration.py",  # #2811 close — 4 sites, an ESTIMATE#/GRADE# write key
        "lambdas/ai/grounding_gate_params.py",  # #2811 close — the one ruled exemption
        "lambdas/privacy/diary_publish.py",  # #2811 close — the package that joined already clean
    ):
        assert expected in rels, f"derived surface lost {expected}"


# ── the ratchet ──────────────────────────────────────────────────────────────


def test_no_new_utc_day_site_outside_the_residue():
    """A file absent from `_UTC_DAY_RESIDUE` must derive no day from a UTC/naive clock."""
    counts = _measure()
    offenders = []
    for rel, n in sorted(counts.items()):
        if rel not in _UTC_DAY_RESIDUE:
            hits = utc_day_semantics_sites((ROOT / rel).read_text(encoding="utf-8"), filename=rel)
            offenders.extend(hits)
    assert not offenders, (
        "A calendar DAY derived from a UTC/naive clock in a package whose days are "
        "PACIFIC (DATE# keys, gates, and the site all name the Pacific day — #2798/#2811).\n"
        "Fix it with `from common.pacific_time import pacific_today, pacific_now`, or — if the "
        "computation is genuinely UTC (a vendor's day boundary, a UTC-epoch API window, a "
        "billing calendar) — write the reason down as `# utc-exempt(#NNNN): <reason>` on or "
        "within three lines above the site:\n" + "\n".join(offenders)
    )


def test_residue_entries_do_not_grow():
    """A baselined file may shrink, never grow past its number."""
    counts = _measure()
    grown = [
        f"{rel}: {counts.get(rel, 0)} sites > baseline {cap}" for rel, cap in sorted(_UTC_DAY_RESIDUE.items()) if counts.get(rel, 0) > cap
    ]
    assert not grown, "The #2811 residue is shrink-only — these files grew:\n" + "\n".join(grown)


def test_residue_has_no_stale_entries():
    """Prune-on-nonexistence AND prune-on-clean (#1964's rule, plus the hole it left).

    An entry for a deleted file is dead weight; an entry for a file that has reached
    zero is worse — it licenses a silent regrowth all the way back to the old number,
    which is exactly the failure the numeric ratchet exists to prevent.
    """
    counts = _measure()
    missing = sorted(rel for rel in _UTC_DAY_RESIDUE if not (ROOT / rel).exists())
    assert not missing, "_UTC_DAY_RESIDUE names files that no longer exist — prune them:\n" + "\n".join(missing)
    drained = sorted(rel for rel in _UTC_DAY_RESIDUE if counts.get(rel, 0) == 0)
    assert not drained, "_UTC_DAY_RESIDUE names files that are now CLEAN — prune them so they cannot regrow:\n" + "\n".join(drained)


def test_residue_is_exactly_the_measured_coordination_debt():
    """The map is not a budget — it is a NAMED debt with a named blocker each.

    #2811 took its four packages to zero and pinned the empty map so nobody could
    baseline instead of fix. #2817 admitted exactly two entries, each naming a WRITER in
    an unguarded package that had to move in the same change. #2798 made that change: the
    partner packages are on the surface, both pairs converted on both sides, and the two
    entries are DELETED rather than shrunk — the only honest way an entry leaves.

    Empty is therefore the assertion again. Anything added back must come with what those
    two came with: a specific writer, in another package, that has to move with it. A bare
    number with no partner named is a baseline, and this test exists to say so out loud.
    """
    assert _UTC_DAY_RESIDUE == {}, (
        "The #2811/#2817/#2798 surface is FOURTEEN packages at ZERO: compute, ingestion, "
        "coach, intelligence, emails, mcp, reading, training, operational, health, "
        "common, experiment, ai and privacy — i.e. the whole deployed bundle except "
        "lambdas/web/ + lambdas/content/, which owe #2414's stricter zero.\n"
        "A non-empty map means either a new two-sided coordination debt (name the writer, "
        "the package it lives in, and why it cannot move in this change) or a site that "
        "was baselined instead of fixed. Fix it, or mark it "
        "`# utc-exempt(#NNNN): <reason>`. Current map:\n" + "\n".join(f"  {k}: {v}" for k, v in sorted(_UTC_DAY_RESIDUE.items()))
    )


def test_no_utc_day_site_survives_in_the_2817_packages_outside_the_residue():
    """#2817's own acceptance, stated as its own failure message.

    `test_no_new_utc_day_site_outside_the_residue` covers this, but it reports for six
    packages at once. This one says the sentence a future reader needs: the email fleet
    and the MCP tool surface are at zero, and the only two files that are not are the
    two whose writer is elsewhere.
    """
    counts = _measure()
    offenders = sorted(rel for rel in counts if rel.startswith(("lambdas/emails/", "mcp/")) and rel not in _UTC_DAY_RESIDUE)
    assert not offenders, (
        "lambdas/emails/ and mcp/ were swept to the Pacific frame by #2817 (60 + 89 "
        "sites; the email fleet writes `email_log#…` `DATE#` rows that "
        "lambdas/web/site_api_status.py reads on the PACIFIC day, and the MCP tools are "
        "used interactively in PT evenings, when a UTC 'today' selects tomorrow's empty "
        "day). These files regrew a UTC day:\n" + "\n".join(offenders)
    )


def test_no_utc_day_site_survives_in_the_2798_partner_packages():
    """#2798's own acceptance: the two mcp/ residue entries' PARTNER packages.

    Says the sentence a future reader needs, in one place. `lambdas/reading/` writes the
    session `date` and the recall `nextDue` that `mcp/tools_reading.py` reads back;
    `lambdas/operational/` (the hevy routine cron + the overnight re-stamp) and
    `lambdas/training/` (`exercise_history`, `training_notes`) co-author and bound the
    routine `target_date` that `mcp/tools_hevy_routine.py` also writes. `target_date` is
    a WRITE KEY — `routine_repo` derives `routine_id` from it (#3115) — so these packages
    and their mcp/ partners are ONE frame or the key space forks.
    """
    counts = _measure()
    partners = ("lambdas/reading/", "lambdas/training/", "lambdas/operational/")
    offenders = sorted(rel for rel in counts if rel.startswith(partners) and rel not in _UTC_DAY_RESIDUE)
    assert not offenders, (
        "The #2798 partner packages were swept to the Pacific frame (4 + 3 + 21 sites, "
        "with the cost-governor's billing-calendar reads ruled genuinely-UTC and marked). "
        "These files regrew a UTC day — check whether the mcp/ side agrees before you "
        "fix one of them alone:\n" + "\n".join(offenders)
    )


def test_the_exempt_valve_is_actually_in_use_and_reasoned():
    """The three genuinely-UTC sites this issue ruled on must keep their written reason.

    An exemption marker with no prose next to it is how a valve becomes a mute button.
    """
    for rel, needle in (
        ("lambdas/ingestion/habitify_lambda.py", "vendor-frame comparison"),
        ("lambdas/ingestion/strava_lambda.py", "vendor-frame API window bound"),
        ("lambdas/ingestion/whoop_lambda.py", "utc-exempt(#2811)"),
        ("lambdas/ingestion/health_auto_export_lambda.py", "a log correlation id, not a DATE# key"),
    ):
        src = (ROOT / rel).read_text(encoding="utf-8")
        assert "utc-exempt(#2811)" in src, f"{rel} lost its #2811 exemption marker"
        assert needle in src, f"{rel}'s #2811 exemption lost its stated reason"


def test_the_billing_calendar_exemption_is_the_only_2798_one_and_is_reasoned():
    """#2798 ruled exactly ONE file genuinely-UTC, and the ruling has to keep its reason.

    `cost_governor_lambda.py` is the "billing calendar" case this module's docstring names:
    its days are Cost Explorer / AWS Budgets days, which are UTC, and the dated ADR-133
    ceiling window reverts as the AWS budget month rolls. Asking CE for a Pacific window
    would query a calendar AWS does not bill in. Everything else in the three packages
    converted, so a SECOND `#2798` marker appearing anywhere is a new ruling that owes
    the reader an argument — this test makes it show up in a diff.
    """
    rel = "lambdas/operational/cost_governor_lambda.py"
    src = (ROOT / rel).read_text(encoding="utf-8")
    assert "utc-exempt(#2798)" in src, f"{rel} lost its #2798 billing-calendar exemption marker"
    assert "billing calendar" in src.lower(), f"{rel}'s #2798 exemption lost its stated reason"

    marked = sorted(str(p.relative_to(ROOT)) for p in _surface_files() if "utc-exempt(#2798)" in p.read_text(encoding="utf-8"))
    assert marked == [rel], (
        "#2798's exemption ruling was: exactly one genuinely-UTC file (the billing "
        "calendar). A new `# utc-exempt(#2798)` site is a NEW ruling — give it its own "
        "issue number so the reason is attributable. Currently marked:\n" + "\n".join(marked)
    )


def test_no_utc_day_site_survives_in_the_2811_closing_packages():
    """#2811's own acceptance, said in one sentence for the next reader.

    `lambdas/health/` (8 sites), `lambdas/common/` (6), `lambdas/experiment/` (5),
    `lambdas/ai/` (3) and `lambdas/privacy/` (0 — it joined clean) are the LAST
    packages of the deployed tree outside #2414's stricter zero. With them the
    scanned surface is `lambdas/` ex-`web/`+`content/`, plus `mcp/`: every module
    that ships in the bundle is now under one of the two guards.

    The heavy ones are all defaults rather than direct reads, which is why they
    outlived four earlier slices: `data.get("date", <utc today>)`,
    `ref_dt or <utc now>`, `now or <utc now>`. A default argument is still a clock.
    """
    counts = _measure()
    closing = ("lambdas/health/", "lambdas/common/", "lambdas/experiment/", "lambdas/ai/", "lambdas/privacy/")
    offenders = sorted(rel for rel in counts if rel.startswith(closing) and rel not in _UTC_DAY_RESIDUE)
    assert not offenders, (
        "The #2811 closing packages were swept to the Pacific frame (8 + 6 + 5 + 3 + 0 "
        "sites), with the grounding gate's fail-soft degrade the only ruled exemption. "
        "These files regrew a UTC day:\n" + "\n".join(offenders)
    )


def test_the_grounding_gate_degrade_path_is_the_only_2811_closing_exemption():
    """#2811's closing slice ruled exactly ONE site genuinely-UTC, and it is not a
    frame choice at all — it is the handler for the frame module being unavailable.

    `ai/grounding_gate_params.py` tries `common.pacific_time.pacific_today()` first
    and falls back to the naive clock only when that import raises. "Use
    pacific_time" is therefore not a remedy on this branch: it is the branch that
    runs when that call is what failed. The gate must never take a narrative
    surface down (#1691), so it degrades rather than raising.

    The test pins three things a future edit could quietly break: the marker, its
    stated reason, that the PACIFIC path is still attempted FIRST — and that this
    is still the only `#2811` exemption in the five closing packages, so a second
    ruling has to arrive in a diff with its own argument.
    """
    rel = "lambdas/ai/grounding_gate_params.py"
    src = (ROOT / rel).read_text(encoding="utf-8")
    assert "utc-exempt(#2811)" in src, f"{rel} lost its #2811 fail-soft exemption marker"
    assert "fail-soft degrade" in src, f"{rel}'s #2811 exemption lost its stated reason"
    assert "pacific_today" in src, f"{rel} must still TRY the Pacific frame before degrading — that is the reason"
    assert src.index("pacific_today") < src.index("utc-exempt(#2811)"), "the Pacific attempt must come BEFORE the degrade"

    closing = ("lambdas/health/", "lambdas/common/", "lambdas/experiment/", "lambdas/ai/", "lambdas/privacy/")
    marked = sorted(
        str(p.relative_to(ROOT))
        for p in _surface_files()
        if str(p.relative_to(ROOT)).startswith(closing) and "utc-exempt(#2811)" in p.read_text(encoding="utf-8")
    )
    assert marked == [rel], (
        "#2811's closing ruling was: exactly one genuinely-UTC site in the five "
        "packages, and it is a fail-soft degrade rather than a calendar. A new "
        "`# utc-exempt(#2811)` site here is a NEW ruling — give it its own issue "
        "number so the reason is attributable. Currently marked:\n" + "\n".join(marked)
    )


# ── mutation proofs: every matcher must FIRE, and the ratchet must refuse growth ──


def test_fires_on_the_day_faces():
    for src, why in (
        ('today = datetime.now(timezone.utc).strftime("%Y-%m-%d")\n', "day strftime"),
        ("d = datetime.now(tz=timezone.utc).date()\n", ".date()"),
        ('start = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")\n', "timedelta window"),
        ("now = datetime.now(timezone.utc)\nday = now.date()\n", "two-statement taint"),
        ("iso = datetime.now(timezone.utc).isocalendar()\n", "isocalendar"),
        ('label = f"as of {datetime.now(timezone.utc):%Y-%m-%d}"\n', "f-string day"),
        ("x = date.today()\n", "naive date.today()"),
        ("x = datetime.today()\n", "naive datetime.today()"),
        ("from datetime import date as _date\nx = _date.today()\n", "aliased naive today"),
        ("day = datetime.utcnow().isoformat()[:10]\n", "[:10] slice"),
        ("day = datetime.now(timezone.utc).isoformat()[:10]\n", "[:10] slice on utc now"),
    ):
        assert len(utc_day_semantics_sites(src)) == 1, f"matcher missed the {why} face"


def test_does_not_fire_on_instants_or_a_named_frame():
    """The judgment half. Over-flagging instants is how a guard gets muted, so the
    boundary is a test, not a docstring promise."""
    for src in (
        "stamp = datetime.now(timezone.utc).isoformat()\n",
        "epoch = int(datetime.now(timezone.utc).timestamp())\n",
        "nonce = int(datetime.now().timestamp())\n",  # withings' HMAC nonce — #1964's class, not this one
        'ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")\n',
        "ttl = int((datetime.now(timezone.utc) + timedelta(days=8)).timestamp())\n",
        "head = datetime.now(timezone.utc).isoformat()[:19]\n",  # a timestamp prefix, not a day
        "raw = datetime.now(timezone.utc)\n",
        'day = datetime.now(timezone.utc).astimezone(PT).strftime("%Y-%m-%d")\n',
        "from common.pacific_time import pacific_today, pacific_now\nday = pacific_today()\nd = pacific_now().date()\n",
    ):
        assert utc_day_semantics_sites(src) == [], f"false positive on an instant: {src!r}"


def test_exempt_marker_suppresses_and_is_load_bearing():
    marked = (
        "# utc-exempt(#2811): a vendor's UTC day boundary, not a DATE# key\n"
        'today_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d")\n'
    )
    assert utc_day_semantics_sites(marked) == []
    assert len(utc_day_semantics_sites(marked.splitlines()[1] + "\n")) == 1


def test_a_planted_site_in_a_real_scoped_file_would_red_the_guard():
    """THE mutation proof the ratchet turns on: plant the defect in the actual source of
    a file that is NOT in the residue, and prove `test_no_new_utc_day_site_outside_the_residue`
    would fail. Run against the real file's text so a surface/exclusion mistake shows up
    here rather than in production."""
    rel = "lambdas/compute/hypothesis_engine_lambda.py"
    assert rel not in _UTC_DAY_RESIDUE
    src = (ROOT / rel).read_text(encoding="utf-8")
    assert utc_day_semantics_sites(src, filename=rel) == [], "precondition: the file is clean today"
    planted = src + '\n\n_PLANTED = datetime.now(timezone.utc).strftime("%Y-%m-%d")\n'
    assert len(utc_day_semantics_sites(planted, filename=rel)) == 1


def test_a_planted_site_reds_the_guard_in_the_2817_packages_too():
    """The #2817 half of the mutation proof, run against the REAL text of one
    `lambdas/emails/` module and one `mcp/` module.

    Widening `SURFACE_PACKAGES` is the whole change on the guard side, and a widened
    glob that quietly matches nothing (wrong dir name, a `_SKIP_PATH_MARKERS`
    collision, a package that is not importable from `tests/`) reports green forever.
    Planting the defect in the actual file proves the new surface is live, not just
    declared.
    """
    for rel in ("lambdas/emails/freshness_checker_lambda.py", "mcp/tools_habits.py"):
        assert rel not in _UTC_DAY_RESIDUE
        assert rel in {str(p.relative_to(ROOT)) for p in _surface_files()}, f"{rel} is not on the scanned surface"
        src = (ROOT / rel).read_text(encoding="utf-8")
        assert utc_day_semantics_sites(src, filename=rel) == [], f"precondition: {rel} is clean today"
        planted = src + '\n\n_PLANTED = datetime.now(timezone.utc).strftime("%Y-%m-%d")\n'
        assert len(utc_day_semantics_sites(planted, filename=rel)) == 1, f"the guard would not fire on {rel}"


def test_a_planted_site_reds_the_guard_in_the_2798_packages_too():
    """The #2798 half of the mutation proof — one REAL file per newly-added package.

    Widening `SURFACE_PACKAGES` is the whole change on the guard side, and a widened glob
    that quietly matches nothing (wrong dir name, a `_SKIP_PATH_MARKERS` collision, a
    package that is not importable from `tests/`) reports green forever. Planting the
    defect in the actual file proves the new surface is live, not merely declared — and
    doing it per-package means dropping ONE of the three from the tuple cannot pass.
    """
    surface = {str(p.relative_to(ROOT)) for p in _surface_files()}
    for rel in (
        "lambdas/reading/reading_store.py",
        "lambdas/training/exercise_history.py",
        "lambdas/operational/hevy_routine_cron_lambda.py",
    ):
        assert rel not in _UTC_DAY_RESIDUE
        assert rel in surface, f"{rel} is not on the scanned surface"
        src = (ROOT / rel).read_text(encoding="utf-8")
        assert utc_day_semantics_sites(src, filename=rel) == [], f"precondition: {rel} is clean today"
        planted = src + '\n\n_PLANTED = datetime.now(timezone.utc).strftime("%Y-%m-%d")\n'
        assert len(utc_day_semantics_sites(planted, filename=rel)) == 1, f"the guard would not fire on {rel}"


def test_a_day_slice_of_a_CALL_fires_the_matcher_blindness_proof():
    """THE PROOF THE CLOSING SLICE TURNS ON. Read this before trusting a green run.

    Session D's audit of this file found that `_is_day_slice` bottoms out in
    `_subtree_dirty`, which only ever asked "does this subtree contain a literal
    clock, or a tainted NAME?". A `[:10]` slice of a CALL satisfies neither, so it
    was structurally unreachable — and all three planted-site proofs below plant the
    same `datetime.now(timezone.utc).strftime(...)` shape, so none of them could
    have caught it. The 22 sites this slice was scoped against were a FLOOR.

    Every case here returns 0 findings against the pre-#2811 matcher and 1 after it,
    which is the difference between a guard and a decoration. The middle case is not
    hypothetical: it is `reading/reading_store.log_session`, which survived #2817 AND
    #2798 with both slices reporting `lambdas/reading/` at zero.
    """
    for src, why in (
        ("def _now_iso():\n    return datetime.now(timezone.utc).isoformat()\nday = _now_iso()[:10]\n", "inline call slice"),
        (
            "def _now_iso():\n"
            "    return datetime.now(timezone.utc).isoformat()\n\n\n"
            "def log(now=None):\n"
            "    now = now or _now_iso()\n"
            "    return now[:10]\n",
            "the reading_store shape: bound, then sliced",
        ),
        (
            "class C:\n"
            "    def _stamp(self):\n"
            "        return datetime.now(timezone.utc).isoformat()\n\n"
            "    def day(self):\n"
            "        return self._stamp()[:10]\n",
            "self.<helper>() slice",
        ),
    ):
        assert len(utc_day_semantics_sites(src)) == 1, f"matcher still blind to the {why} face"


def test_the_call_taint_does_not_flag_a_stored_DATE_key_in_another_scope():
    """The blindness fix's own judgment test, drawn from the live tree.

    `lambdas/compute/episode_detect_lambda.py` has `build_episode_record` binding
    `item = {..., "computed_at": _now_iso()}` and a separate `_sk_date(item)` that
    slices the stored `DATE#` sort key off its own PARAMETER. A file-wide taint
    (the first implementation tried here) flags that second function — correct code,
    on a DATE# key that is ALREADY a Pacific day. Measured, it also flagged
    `datetime.strptime(...)` parses and plain list truncations across the fleet.

    So the helper-call taint is scoped to the function that bound it. This test is
    what stops a future "simplification" back to the file-wide form, and it runs
    against the real module rather than a sketch of it.
    """
    rel = "lambdas/compute/episode_detect_lambda.py"
    src = (ROOT / rel).read_text(encoding="utf-8")
    assert "_now_iso()" in src and "_sk_date" in src, f"{rel} no longer carries the shape this test is about"
    assert utc_day_semantics_sites(src, filename=rel) == [], (
        "helper-call taint leaked across function scopes — a `DATE#` key normalisation "
        "in one function is being read as a clock because ANOTHER function stamps a "
        "record with one. An over-firing guard gets muted; keep the taint scoped."
    )


def test_a_blanket_ten_char_slice_ban_would_be_unlivable_and_is_deliberately_not_the_rule():
    """WHY THE SLICE FACE STILL NEEDS A CLOCK, stated as a measurement.

    The obvious "fix" for the vendor-instant blind spot (`w["start_time"][:10]`) is
    to flag EVERY `[:10]` slice and let the exemption valve absorb the rest. It is
    not viable, and the number is the argument: the scanned surface carries well
    over a hundred `[:10]` slices, and the overwhelming majority are
    `sk.replace("DATE#", "")[:10]` normalisations of a key that is ALREADY a Pacific
    day, or plain list truncations (`failed_ids[:10]`). A rule needing a hundred
    exemptions is a rule nobody reads.

    So the slice face keeps requiring a provable clock, and the vendor-instant class
    stays OUT of this shape guard's reach ON PURPOSE. That class is caught by
    `tests/test_pt_day_pair_contracts_2798.py`, which drives a writer and its reader
    at one PT-evening instant — a shape guard is not a pair guard (#2798), and this
    test exists so the next author does not "fix" the shape guard into uselessness
    trying to make it into one.
    """
    import ast as _ast

    total, list_like = 0, 0
    for path in _surface_files():
        try:
            tree = _ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover — the tree parses today
            continue
        for node in _ast.walk(tree):
            if not (isinstance(node, _ast.Subscript) and isinstance(node.slice, _ast.Slice)):
                continue
            sl = node.slice
            if sl.lower is None and sl.step is None and isinstance(sl.upper, _ast.Constant) and sl.upper.value == 10:
                total += 1
                if "DATE#" in _ast.unparse(node):
                    list_like += 1
    assert total >= 100, f"only {total} `[:10]` slices found — re-check the claim before trusting the rule below"
    assert list_like >= 20, f"only {list_like} of {total} slices are DATE#-key normalisations — the ratio argument needs re-measuring"
    assert len(_measure()) == 0, "and with the clock requirement in place the whole surface is still at zero"


def test_a_planted_site_reds_the_guard_in_the_2811_closing_packages_too():
    """The closing slice's half of the mutation proof — one REAL file per new package.

    Widening `SURFACE_PACKAGES` is the whole change on the guard side, and a widened
    glob that quietly matches nothing reports green forever. Per-package means
    dropping ONE of the five from the tuple cannot pass — including
    `lambdas/privacy/`, which joined at zero and would otherwise be the easiest
    package in the repo to lose without anyone noticing.

    Two shapes are planted, not one: the classic `strftime` face (which every
    earlier proof used) and the `[:10]`-slice-of-a-CALL face this slice added. A
    proof that only plants shapes the matcher already caught is how the blindness
    survived four slices in the first place.
    """
    surface = {str(p.relative_to(ROOT)) for p in _surface_files()}
    for rel in (
        "lambdas/health/weight_trend.py",
        "lambdas/common/quarter_utils.py",
        "lambdas/experiment/effect_fitter.py",
        "lambdas/ai/platform_memory.py",
        "lambdas/privacy/diary_publish.py",
    ):
        assert rel not in _UTC_DAY_RESIDUE
        assert rel in surface, f"{rel} is not on the scanned surface"
        src = (ROOT / rel).read_text(encoding="utf-8")
        assert utc_day_semantics_sites(src, filename=rel) == [], f"precondition: {rel} is clean today"
        strftime_planted = src + '\n\n_PLANTED = datetime.now(timezone.utc).strftime("%Y-%m-%d")\n'
        assert len(utc_day_semantics_sites(strftime_planted, filename=rel)) == 1, f"the guard would not fire on {rel}"
        call_planted = (
            src + "\n\ndef _planted_now():\n    return datetime.now(timezone.utc).isoformat()\n\n\n_PLANTED = _planted_now()[:10]\n"
        )
        assert len(utc_day_semantics_sites(call_planted, filename=rel)) == 1, f"the CALL-slice face would not fire on {rel}"


def test_a_planted_fully_qualified_site_reds_the_guard():
    """#2798's LAST BOX — the mutation proof for the two shapes this ratchet could not see.

    THE MEASUREMENT, 2026-08-27. `utc_day_semantics_sites` was probed with the six
    ordinary ways to derive a calendar day. Four fired. The two that did not were both
    the plain `import datetime` module form:

        A  import datetime  ->  datetime.datetime.utcnow().strftime('%Y-%m-%d')   BLIND
        D  import datetime  ->  datetime.date.today()                             BLIND

    Every planted-site proof above plants a `from datetime import ...` spelling, so none
    of them could have caught it — the same way all three pre-#2811 proofs planted the
    same `strftime` shape and missed the CALL-slice face. The fix is in `_import_aliases`
    / `_owner_name` in the #2414 module (one implementation, two consumers, per this
    file's header): plain `Import` of the module is recorded, and the fully-qualified
    `<module>.date` / `<module>.datetime` receiver resolves to its class.

    Planted in the REAL text of a scanned file rather than a snippet, so the assertion
    is about what the ratchet would do to `main`, not about what a matcher does to a
    sketch. Before the fix every case here returned 0 — a green run on a planted defect,
    which is what a decoration looks like.

    `import datetime as _dt` is the house spelling for this form (five files in the
    scanned packages), so it is planted as well as the bare `import datetime`.
    """
    rel = "lambdas/compute/hypothesis_engine_lambda.py"
    assert rel not in _UTC_DAY_RESIDUE
    assert rel in {str(p.relative_to(ROOT)) for p in _surface_files()}, f"{rel} is not on the scanned surface"
    src = (ROOT / rel).read_text(encoding="utf-8")
    assert utc_day_semantics_sites(src, filename=rel) == [], "precondition: the file is clean today"
    for tail, why in (
        ("\n\nimport datetime\n_PLANTED = datetime.datetime.utcnow().strftime('%Y-%m-%d')\n", "shape A, bare module name"),
        ("\n\nimport datetime\n_PLANTED = datetime.date.today()\n", "shape D, bare module name"),
        ("\n\nimport datetime as _dt\n_PLANTED = _dt.datetime.utcnow().strftime('%Y-%m-%d')\n", "shape A, the house alias"),
        ("\n\nimport datetime as _dt\n_PLANTED = _dt.date.today()\n", "shape D, the house alias"),
    ):
        assert len(utc_day_semantics_sites(src + tail, filename=rel)) == 1, (
            f"the ratchet would NOT red on a planted {why} — the fully-qualified `import datetime` "
            "form is invisible again. A day derivation the matcher cannot see returns exactly what "
            "a clean tree returns, so this file's zero would be a claim rather than a measurement."
        )


def test_the_residue_files_are_frozen_not_forgotten():
    """A residue entry has to be a CEILING on a real file, not a name nobody re-reads.

    Vacuous while the map is empty (#2798 paid both entries off), and deliberately kept:
    the moment anyone re-opens the map this is what makes it a ratchet rather than a
    budget — the count must be EXACT, so one more site reds `test_residue_entries_do_not_
    grow` and a drained file reds `test_residue_has_no_stale_entries` until it is pruned.
    The arithmetic itself stays exercised while the map is empty by
    `test_the_ratchet_refuses_growth_and_stale_entries`, which drives it synthetically.
    """
    counts = _measure()
    for rel, cap in _UTC_DAY_RESIDUE.items():
        assert (ROOT / rel).exists(), f"{rel} left the tree — prune its entry"
        assert (
            counts.get(rel, 0) == cap
        ), f"{rel} measures {counts.get(rel, 0)} sites, entry says {cap} — re-measure, do not adjust the entry to fit"


def test_the_ratchet_refuses_growth_and_stale_entries():
    """The residue's own arithmetic, driven with synthetic maps — the machinery has to
    be provable while the real map is empty, or an empty map means an unexercised gate."""
    counts = {"lambdas/x.py": 3}
    # growth
    assert [r for r, cap in {"lambdas/x.py": 2}.items() if counts.get(r, 0) > cap] == ["lambdas/x.py"]
    # at the number: allowed
    assert [r for r, cap in {"lambdas/x.py": 3}.items() if counts.get(r, 0) > cap] == []
    # drained to zero: the entry must be pruned
    assert [r for r in {"lambdas/y.py": 4} if {}.get(r, 0) == 0] == ["lambdas/y.py"]


# ══════════════════════════════════════════════════════════════════════════════
# #2817 — THE ANCHOR FACE. A day string parsed back into the WRONG frame.
#
# THE BLIND SPOT, MEASURED. Every face above bottoms out in `_subtree_dirty`, which
# asks "is there a CLOCK in this subtree?". `datetime.strptime(day_str, "%Y-%m-%d")`
# is not a clock — it is the INVERSE of one — so the shape
#
#     datetime.strptime(<a DATE# day>, "%Y-%m-%d").replace(tzinfo=timezone.utc)
#
# is structurally unreachable by all of them. That matters because `DATE#` keys name
# PACIFIC days: anchoring one at UTC midnight puts the day's start 7h/8h before the
# day began, and any arithmetic against an INSTANT then carries that error.
#
# #2817 found it in `freshness_checker_lambda.py`, in the staleness math its own
# acceptance box names, in a package BOTH matchers had certified at zero — the #2811
# lesson repeating exactly ("a certification true of the matcher and false of the
# code"). #3196's sweep had moved `now` to `pacific_now()` and left the other operand
# in UTC, so the frame mismatch was introduced BY the fix for the frame mismatch.
# `tests/test_pt_evening_email_frame_2817.py` drives the behaviour at a PT evening.
#
# WHY THIS IS A SCOPED RESIDUE AND NOT A FLEET BAN — the #2811 `[:10]` precedent.
# Measured across `lambdas/` + `mcp/`: 16 sites carry this shape, and the MAJORITY are
# correct. Three spellings are legitimately frame-free:
#   * an RSS `pubDate` render (`...replace(tzinfo=utc).strftime("%a, %d %b %Y 15:00:00 GMT")`)
#     — the tzinfo never reaches arithmetic; only Y/M/D/weekday pass through;
#   * `.date()` on both operands before subtracting (`site_api_status`, and this
#     module's own `compute_datatype_liveness`) — the tzinfo cannot survive `.date()`;
#   * a vendor's UTC-epoch API window bound (`strava`, `withings`, `todoist`).
# A ban would need ~10 exemptions out of 16. A rule needing that many exemptions is a
# rule nobody reads (#2811 declined the blanket `[:10]` ban on the same arithmetic),
# so the face is frozen where #2817 ruled every site — `lambdas/emails/` — and the
# rest is reported as a known blind spot rather than silently called clean.
# ══════════════════════════════════════════════════════════════════════════════

# Repo-relative file -> the day-anchor sites RULED genuinely frame-free by #2817.
# Shrink-only, like `_UTC_DAY_RESIDUE`, and every entry carries its ruling.
_EMAILS_DAY_ANCHOR_RULINGS: dict[str, int] = {
    # `_rfc822()` — an RSS pubDate whose output hardcodes its own clock time
    # ("%a, %d %b %Y 15:00:00 GMT"). The tzinfo is a no-op: nothing but the date
    # components and the weekday name survive into the string.
    "lambdas/emails/chronicle_podcast_lambda.py": 1,
    "lambdas/emails/daily_debrief_lambda.py": 1,
    # :362 is the same `_rfc822` no-op. :1323 is `_hold_age_days`, which slices the
    # UTC DAY off a UTC instant and subtracts it from a UTC now — both sides one
    # frame, and the result is a DURATION (hold age in days vs HOLD_RETRY_HOURS),
    # never a Pacific day selection. It quantises to midnight, which shortens the
    # human review window by up to a day; that is a precision nit, not this class.
    "lambdas/emails/coach_panel_podcast_lambda.py": 2,
    # `write_anomaly_record` anchors the record's own day only to derive a 90-day
    # TTL epoch. An expiry is not a day selection and no reader compares it to a
    # Pacific day; a 7h shift on a 90-day investigative TTL is immaterial.
    "lambdas/emails/anomaly_detector_lambda.py": 1,
}


def _day_string_anchored_in_utc(source: str, filename: str = "<source>") -> list[str]:
    """`datetime.strptime(<x>, "%Y-%m-%d").replace(tzinfo=timezone.utc)` — a day string
    parsed back into UTC. Day-only format on purpose: a `%H`-carrying format is
    parsing a real instant, where a UTC anchor is the honest reading."""
    findings: list[str] = []
    lines = source.splitlines()
    for node in ast.walk(ast.parse(source, filename=filename)):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "replace"):
            continue
        tz = next((kw.value for kw in node.keywords if kw.arg == "tzinfo"), None)
        if tz is None or ast.unparse(tz) not in ("timezone.utc", "utc", "dt_timezone.utc"):
            continue
        inner = node.func.value
        if not (isinstance(inner, ast.Call) and isinstance(inner.func, ast.Attribute) and inner.func.attr == "strptime"):
            continue
        if not (len(inner.args) > 1 and isinstance(inner.args[1], ast.Constant) and _is_day_only_fmt(inner.args[1].value)):
            continue
        if any(_EXEMPT_MARKER in lines[ln - 1] for ln in range(max(1, node.lineno - 3), node.lineno + 1) if ln <= len(lines)):
            continue
        findings.append(f"{filename}:{node.lineno}: {ast.unparse(node)}")
    return findings


def _measure_email_day_anchors() -> dict[str, int]:
    counts: dict[str, int] = {}
    for path in sorted((ROOT / "lambdas" / "emails").rglob("*.py")):
        if any(m in str(path) for m in _SKIP_PATH_MARKERS):
            continue
        rel = str(path.relative_to(ROOT))
        hits = _day_string_anchored_in_utc(path.read_text(encoding="utf-8"), filename=rel)
        if hits:
            counts[rel] = len(hits)
    return counts


def test_the_freshness_checker_anchors_its_day_in_the_frame_that_names_it():
    """#2817's fix, pinned at the shape level. The behaviour is pinned separately in
    `tests/test_pt_evening_email_frame_2817.py`; this is the cheap structural half, so
    a revert shows up even if the behavioural suite is skipped."""
    rel = "lambdas/emails/freshness_checker_lambda.py"
    src = (ROOT / rel).read_text(encoding="utf-8")
    assert _day_string_anchored_in_utc(src, filename=rel) == [], (
        "freshness_checker parsed a `DATE#` day (a PACIFIC calendar day) back into UTC and "
        "compared it against `pacific_now()`, inflating every age by the Pacific offset. "
        "Use `.replace(tzinfo=PACIFIC)`, or reduce BOTH operands to `.date()`."
    )
    assert "tzinfo=PACIFIC" in src, f"{rel} lost the Pacific anchor #2817 gave it"


def test_the_email_day_anchor_rulings_are_exact_and_shrink_only():
    """Every remaining site in `lambdas/emails/` was READ and RULED, and the count is
    exact — so a new one reds here instead of hiding among the legitimate ones, and a
    file that drops to zero must be pruned rather than left licensing a regrowth."""
    counts = _measure_email_day_anchors()
    assert counts == _EMAILS_DAY_ANCHOR_RULINGS, (
        "The #2817 day-anchor rulings for lambdas/emails/ no longer match the tree.\n"
        "A NEW site needs a ruling written beside it (is the frame reached by arithmetic, "
        "or is it a no-op render / a same-frame duration?); a REMOVED one needs its entry "
        "pruned.\n"
        f"measured: {counts}\n  ruled: {_EMAILS_DAY_ANCHOR_RULINGS}"
    )


def test_the_anchor_face_fires_on_a_planted_site_in_a_real_email_module():
    """The mutation proof. Planted in the REAL text of the file #2817 fixed, so a
    matcher that silently stopped matching cannot report green forever."""
    rel = "lambdas/emails/freshness_checker_lambda.py"
    src = (ROOT / rel).read_text(encoding="utf-8")
    planted = src + '\n\n_PLANTED = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc)\n'
    assert len(_day_string_anchored_in_utc(planted, filename=rel)) == 1, "the anchor face would not fire on a reintroduced site"


def test_the_anchor_face_leaves_instants_and_named_frames_alone():
    """The judgment half — an over-firing guard gets muted. A `%H`-carrying format is a
    real instant (a UTC anchor is honest there), and the Pacific anchor is the fix."""
    for src in (
        'x = datetime.strptime(s, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)\n',
        'x = datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=PACIFIC)\n',
        'x = datetime.strptime(s, "%Y-%m-%d").date()\n',
        '# utc-exempt(#2817): a vendor UTC-epoch window bound\nx = datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)\n',
    ):
        assert _day_string_anchored_in_utc(src) == [], f"false positive: {src!r}"
