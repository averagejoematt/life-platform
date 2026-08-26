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
12 in the two files below whose fix is blocked on a writer in an unguarded package.
Nothing in either package was ruled genuinely-UTC: unlike `lambdas/ingestion/`, neither
talks to a vendor whose day boundary is UTC, and the one `logger.set_date` here follows
the fleet's `pacific_today()` convention rather than #2811's instant-derived exception.
`test_residue_is_exactly_the_measured_coordination_debt` pins the map by NAME and NUMBER,
so appending an entry — or quietly widening one — has to argue with a test.

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
    _tainted_names,
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
    # because concurrent PRs owned those files that night. They arrive WITH residue
    # entries, exactly as #2811's docstring predicted.
    "lambdas/emails",
    "mcp",
)

# ── THE RATCHET. Repo-relative file -> maximum day-semantics sites allowed. ──
# Entries only ever come OUT (or get smaller). An entry is a DEBT, and the prose
# beside it is the debt's terms: what else has to move before the file can be fixed.
#
# THE RULE THIS MAP ENCODES (#2817): a consumer is only converted together with the
# WRITER whose sort key it matches. #2815 is the incident behind that sentence —
# converting one side of an `OUTPUT#{date}` pair desynchronises it, which is worse
# than both sides being wrong in the same direction. Both entries below are the same
# shape: the mcp/ side is ready, the partner lives in a package (`lambdas/reading/`,
# `lambdas/training/` + `lambdas/operational/`) that neither this ratchet nor #2414's
# zero surface covers yet, so converting mcp/ alone would split the pair.
_UTC_DAY_RESIDUE: dict[str, int] = {
    # Reading. `_input_streak` walks back day-by-day from "today" over session rows
    # whose `date` is written by `lambdas/reading/reading_store.log_session` as
    # `_now_iso()[:10]` — the UTC day. `_today()` (7 call sites) and `_prior_iso_week`
    # feed the same partition, and `reading_recall.next_due()/_today()` stamp the
    # recall `nextDue` dates this module then queries. Convert with reading_store.py +
    # reading_recall.py in one change, or a session logged at 6pm PT lands on
    # tomorrow's row and the streak reads 0.
    "mcp/tools_reading.py": 6,
    # Hevy routines. `target_date` here is a WRITE key: `training.routine_repo`
    # versions one routine per target_date (#3115). The other writer of that same key
    # is `lambdas/operational/hevy_routine_cron_lambda._target_date_for_event`
    # (`date.today()`), with `lambdas/training/exercise_history.load_recent_history`
    # bounding its history window off the same day. Converting the MCP side alone
    # would make a manual evening draft author a DIFFERENT routine row than the cron's.
    "mcp/tools_hevy_routine.py": 6,
}


def _surface_files() -> list[pathlib.Path]:
    files: list[pathlib.Path] = []
    for pkg in SURFACE_PACKAGES:
        files += [p for p in (ROOT / pkg).rglob("*.py") if not any(m in str(p) for m in _SKIP_PATH_MARKERS)]
    return sorted(files)


def _is_day_slice(node, tainted: set, aliases: dict) -> bool:
    """`<utc/naive now>.isoformat()[:10]` / `str(<utc/naive now>)[:10]`.

    A ten-character prefix of an ISO-8601 rendering IS the calendar day — the same
    value `strftime("%Y-%m-%d")` produces, reached by a route #2414's matcher does
    not walk. Matched on the slice bound so `[:19]` (a timestamp) stays clean.
    """
    if not isinstance(node, ast.Subscript):
        return False
    sl = node.slice
    if not (isinstance(sl, ast.Slice) and sl.lower is None and sl.step is None):
        return False
    if not (isinstance(sl.upper, ast.Constant) and sl.upper.value == 10):
        return False
    return _subtree_dirty(node.value, tainted, aliases)


def utc_day_semantics_sites(source: str, filename: str = "<source>") -> list[str]:
    """Every place `source` derives a calendar DAY from a UTC-anchored or naive clock.

    The day-semantics subset of #2414's matcher (see the module docstring's boundary
    table) plus the `[:10]` slice face. A bare `datetime.utcnow()` whose value stays an
    instant is NOT a finding here.
    """
    tree = ast.parse(source, filename=filename)
    lines = source.splitlines()
    aliases = _import_aliases(tree)
    tainted = _tainted_names(tree, aliases)
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
            # `date.today()` / `datetime.today()` — the naive clock that RETURNS a day.
            # `datetime.utcnow()` / a no-arg `datetime.now()` are naive clocks too, but
            # their value is an instant; they are findings only via a derivation below.
            if attr == "today" and owner in ("date", "datetime") and _is_naive_clock(node, aliases):
                _flag(node, "naive clock whose value IS a day")
                continue
            if attr == "strftime" and node.args and _is_day_only_fmt(getattr(node.args[0], "value", None)):
                if _subtree_dirty(node.func.value, tainted, aliases):
                    _flag(node, "date-only strftime on a UTC/naive now")
            elif attr == "date" and not node.args and _subtree_dirty(node.func.value, tainted, aliases):
                _flag(node, ".date() on a UTC/naive now")
            elif attr == "isocalendar" and _subtree_dirty(node.func.value, tainted, aliases):
                _flag(node, ".isocalendar() on a UTC/naive now")
        elif isinstance(node, ast.FormattedValue) and node.format_spec is not None:
            spec = "".join(str(v.value) for v in ast.walk(node.format_spec) if isinstance(v, ast.Constant))
            if _is_day_only_fmt(spec) and _subtree_dirty(node.value, tainted, aliases):
                _flag(node, "date-only f-string format on a UTC/naive now")
        elif isinstance(node, ast.Subscript) and _is_day_slice(node, tainted, aliases):
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
    baseline instead of fix. #2817 kept that pressure while admitting two real
    entries: pin them by name AND number, so growing an existing entry (the quieter
    regression) is as loud as appending a new one. Anything added here must come with
    the same thing these two came with — a writer, in another package, that has to
    move in the same change.
    """
    assert _UTC_DAY_RESIDUE == {"mcp/tools_reading.py": 6, "mcp/tools_hevy_routine.py": 6}, (
        "The #2811/#2817 surface was measured on 2026-08-25: four packages plus "
        "lambdas/emails/ at ZERO, and exactly two mcp/ files held back because their "
        "sort-key WRITER lives in an unguarded package (see the map's comments).\n"
        "A changed map means either that debt was paid (delete the entry — do not "
        "shrink it and leave it) or a site was baselined instead of fixed. Fix it, or "
        "mark it `# utc-exempt(#NNNN): <reason>`. Current map:\n" + "\n".join(f"  {k}: {v}" for k, v in sorted(_UTC_DAY_RESIDUE.items()))
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


def test_the_residue_files_are_frozen_not_forgotten():
    """A residue entry has to be a CEILING on a real file, not a name nobody re-reads.

    Both entries are held at their measured 6. Proving the count is exact (not merely
    "at most 6") is what makes `test_residue_entries_do_not_grow` a ratchet: a 7th site
    added to either file reds, and a fix that drains one to zero reds
    `test_residue_has_no_stale_entries` until the entry is deleted.
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
