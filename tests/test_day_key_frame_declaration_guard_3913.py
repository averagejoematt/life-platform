"""tests/test_day_key_frame_declaration_guard_3913.py — #3913 box 3: guard the SET, not whoop.

WHAT #3973 LEFT AND WHY THIS FILE EXISTS
----------------------------------------
#3973 gave `whoop` its `day_key_frame: "utc"` facet and pinned the arithmetic that facet
drives (`tests/test_whoop_day_key_frame_3913.py`). Every assertion in that file names
`whoop`. So the SPECIMEN is guarded and the CLASS is not: the thing that made whoop a
seven-hour defect for months was not that anyone chose the wrong frame — it was that
`day_key_frame_for()` answers `"pacific"` for a source that declares nothing, so a writer
whose keys are measurably UTC looked identical, at every call site, to one that is
genuinely Pacific. Silence and a correct declaration are indistinguishable through the
accessor. That is the hole, and it is still open for the next source.

THE TWO LEGS
------------
**Leg 1 — declaration.** Derive, from the ingestion source itself, the modules that
produce a UTC calendar day, and require each one's source to carry an EXPLICIT
``day_key_frame`` KEY on its registry entry. `day_key_frame_for(s) == "utc"` cannot make
this claim: it is satisfied by a declaration AND by nothing at all resolving to the
default, which is exactly the ambiguity that hid whoop. Membership is decided by two
signatures, both read out of the AST:

    utc_window_literal      a Zulu-anchored fetch window (`f"{d}T00:00:00.000Z"`) — the
                            shape that turns a Pacific date LABEL into a UTC WINDOW, so
                            the frame follows the FETCH and never appears near a clock.
                            whoop. This is the one no reviewer found for months.
    astimezone_utc_then_day `.astimezone(timezone.utc).strftime("%Y-%m-%d")` — a reading's
                            own offset-aware instant re-framed to UTC before the day is
                            taken. health_auto_export (TD-19 Phase 2), and whoop's
                            reconciler.

Run over the whole `lambdas/ingestion/` package the scan finds exactly the two sources
that have been ruled on. That is a derivation, not a list: the UTC set falls out of the
code, and a third member arrives by being written rather than by being remembered.

**Leg 2 — anchoring.** A `DATE#` day key is a DAY. Turning one into an INSTANT means
choosing a midnight, and the error from choosing the wrong one is exactly the offset,
silently, forever. `common.pacific_time.anchor_day_key` is the one place that decision is
allowed to be made, because it is the one place that reads the facet. This leg derives
every function that hand-anchors a `%Y-%m-%d` day with a literal tzinfo AND then does
duration arithmetic on it, and requires each to be registered with a written reason for
why the frame cannot matter there.

That leg found a live one. `web/site_api_status.py::_comp_status` — the public status
page's per-source dot — anchored EVERY source at UTC midnight by hand, so its
`_hours_ago` ran 7h (PDT) / 8h (PST) high for the eleven Pacific-framed sources: the
identical defect #3257 fixed in `site_api_freshness` and #2817 in `freshness_checker`,
surviving in a third consumer because both of those fixes were applied to a remembered
list of two. It is fixed in this PR and is now absent from the derived set.

WHAT THIS GUARD HONESTLY CANNOT DO
----------------------------------
It cannot prove a frame is the RIGHT one — only measurement against the live partition can
(2,250 of 2,250 whoop straddling rows UTC-keyed, re-measured read-only 2026-09-21; the
number is in the `day_key_frame_consequence` on the registry entry). What it makes
impossible is the next one being SILENT.

Run:  python3 -m pytest tests/test_day_key_frame_declaration_guard_3913.py -v
"""

import ast
import os
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "lambdas"))
sys.path.insert(0, str(ROOT / "lambdas" / "web"))

for _k, _v in {
    "S3_BUCKET": "test-bucket",
    "TABLE_NAME": "life-platform",
    "USER_ID": "matthew",
    "AWS_DEFAULT_REGION": "us-west-2",
    "AWS_REGION": "us-west-2",
}.items():
    os.environ.setdefault(_k, _v)

from ingestion.source_registry import (  # noqa: E402
    DEFAULT_DAY_KEY_FRAME,
    SOURCE_REGISTRY,
    day_key_frame_consequence_for,
    day_key_frame_for,
    utc_day_key_source_ids,
)
from test_ingestion_day_key_derivation_3666 import DAY_KEY_WRITERS  # noqa: E402

pytestmark = pytest.mark.premerge

INGESTION = ROOT / "lambdas" / "ingestion"
RUNTIME_ROOTS = (ROOT / "lambdas", ROOT / "mcp")

UTC_WINDOW_LITERAL = "utc_window_literal"
ASTIMEZONE_UTC_THEN_DAY = "astimezone_utc_then_day"


# ─────────────────────────────────────────────────────────────────────────────
# LEG 1 — the scan
# ─────────────────────────────────────────────────────────────────────────────
def utc_day_signatures(path: pathlib.Path) -> list:
    """Signatures in one module that produce a UTC calendar DAY.

    Docstrings are excluded by node identity, not by a regex on the text: this very file
    and `whoop_lambda`'s own module docstring both quote `T00:00:00.000Z` while describing
    the defect, and a guard that fires on its own explanation is a guard people delete.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = {id(n.value) for n in ast.walk(tree) if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)}
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
            # A Zulu suffix, not merely a `+00:00` one. habitify sends
            # `f"{d}T00:00:00+00:00"` to a vendor that reads only the date part and returns
            # byte-identical payloads for `-07:00` — an offset that is IGNORED is not a
            # frame, and treating it as one would mint a false member on a source whose
            # keys are measurably Pacific.
            if "T00:00:00" in node.value and node.value.rstrip().endswith("Z"):
                found.add(UTC_WINDOW_LITERAL)
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "strftime"
            and any(isinstance(a, ast.Constant) and a.value == "%Y-%m-%d" for a in node.args)
        ):
            inner = node.func.value
            if (
                isinstance(inner, ast.Call)
                and isinstance(inner.func, ast.Attribute)
                and inner.func.attr == "astimezone"
                and "utc" in ast.unparse(inner).lower()
            ):
                found.add(ASTIMEZONE_UTC_THEN_DAY)
    return sorted(found)


def utc_day_writers(package: pathlib.Path = INGESTION) -> dict:
    """{module filename: [signature, …]} over an ingestion package."""
    out = {}
    for path in sorted(package.glob("*.py")):
        sigs = utc_day_signatures(path)
        if sigs:
            out[path.name] = sigs
    return out


def undeclared_utc_sources(registry=None) -> list:
    """The verdict of leg 1: UTC-day writers whose source does not DECLARE a frame.

    Takes the registry as an argument so the control below can remove a facet without
    monkeypatching a module global — a control that cannot reach the code under test is
    the #3913 defect in test form.
    """
    reg = SOURCE_REGISTRY if registry is None else registry
    bad = []
    for module in sorted(utc_day_writers()):
        source = (DAY_KEY_WRITERS.get(module) or {}).get("source")
        if not source:
            bad.append(f"{module}: derives a UTC day but is tied to no source in DAY_KEY_WRITERS")
            continue
        entry = reg.get(source) or {}
        if "day_key_frame" not in entry:
            bad.append(
                f"{source} ({module}): derives its DATE# day in UTC {utc_day_writers()[module]} but its "
                f"SOURCE_REGISTRY entry carries no explicit day_key_frame — it silently reads as the "
                f"{DEFAULT_DAY_KEY_FRAME!r} default, which is how whoop understated its own staleness by 7h "
                f"for months (#3913). Measure the straddling rows in BOTH frames, then declare the facet."
            )
    return bad


def test_every_utc_day_writer_declares_the_frame_explicitly_on_its_registry_entry():
    """LEG 1. Not `day_key_frame_for(s) == 'utc'` — that passes for silence too."""
    assert not undeclared_utc_sources(), "\n".join(undeclared_utc_sources())


def test_the_declared_set_matches_what_the_ingestion_code_actually_does():
    """The two records, reconciled in both directions. A source declaring `utc` whose code
    shows no UTC-day signature is a claim nothing backs; a module showing one whose source
    is not in the derived set is the silence this file exists for."""
    from_code = {(DAY_KEY_WRITERS[m] or {}).get("source") for m in utc_day_writers()}
    assert from_code == utc_day_key_source_ids(), (
        f"the ingestion code derives a UTC day for {sorted(from_code)} but the registry's UTC set is "
        f"{sorted(utc_day_key_source_ids())} — one of the two records is wrong, and the one to trust is the "
        "one you can measure on the live partition."
    )


def test_the_derived_utc_writer_set_is_exactly_the_two_ruled_on():
    """The ratchet. A third member is not a bug in this test — it is a source that needs
    its own measurement, its own consequence note and its own consumer sweep."""
    assert set(utc_day_writers()) == {"health_auto_export_lambda.py", "whoop_lambda.py"}, (
        f"the UTC-day-deriving ingestion set changed: {sorted(utc_day_writers())}. Both current members are "
        "RULED ON — apple_health keeps UTC (#3677, 2,508 rows, no backfill), whoop IS UTC by measurement "
        "(#3913, 2,250 of 2,250 straddling rows). Adding or removing one is a ruling, not an edit."
    )


def test_whoop_is_in_the_set_by_the_signature_no_reviewer_found():
    """Naming the hard one. HAE converts to UTC in the handler, in plain sight. whoop
    converts nothing — `fetch_day` turns a Pacific date LABEL into a UTC WINDOW and files
    the result under that label, so the frame follows the FETCH. That signature is why
    this is a scan and not a code review."""
    assert UTC_WINDOW_LITERAL in utc_day_writers()["whoop_lambda.py"]
    assert UTC_WINDOW_LITERAL not in utc_day_writers().get("health_auto_export_lambda.py", [])
    assert day_key_frame_for("whoop") == "utc"
    assert "day_key_frame" in SOURCE_REGISTRY["whoop"], "the facet must be DECLARED, not inherited"
    assert len(day_key_frame_consequence_for("whoop")) >= 80


# ── LEG 1 CONTROLS ───────────────────────────────────────────────────────────


def test_the_guard_reds_when_whoops_facet_is_removed():
    """THE PLANTED-MISSING-FACET CONTROL, and the whole point of the file.

    Take the facet away and leave everything else — the code still derives a UTC day, the
    accessor still answers (`"pacific"`, cheerfully), nothing raises. That state is the
    pre-#3913 tree, and it must be loud."""
    mutated = {k: (dict(v) if k == "whoop" else v) for k, v in SOURCE_REGISTRY.items()}
    del mutated["whoop"]["day_key_frame"]

    failures = undeclared_utc_sources(registry=mutated)
    assert failures, "removing whoop's day_key_frame changed nothing — this guard is inert"
    assert any("whoop" in f for f in failures)
    assert len(failures) == 1, f"the control must red on whoop alone, not smear: {failures}"
    assert not undeclared_utc_sources(), "the real registry must still be clean after the control"


def test_the_guard_reds_when_apple_healths_facet_is_removed():
    """The same control on the other member — a guard written around one specimen is the
    shape #3913 is fixing."""
    mutated = {k: (dict(v) if k == "apple_health" else v) for k, v in SOURCE_REGISTRY.items()}
    del mutated["apple_health"]["day_key_frame"]
    failures = undeclared_utc_sources(registry=mutated)
    assert len(failures) == 1 and "apple_health" in failures[0], failures


def test_the_scan_fires_on_a_planted_utc_window_writer(tmp_path):
    """The instrument, tested. `test_the_derived_utc_writer_set_is_exactly_the_two_ruled_on`
    proves the scan runs on the REAL package and finds real members; this proves it would
    see a new one."""
    pkg = tmp_path / "ingestion"
    pkg.mkdir()
    (pkg / "planted_lambda.py").write_text(
        '"""A planted source. The docstring says T00:00:00.000Z and must not count."""\n'
        "def fetch_day(d):\n"
        '    return {"start": f"{d}T00:00:00.000Z", "end": f"{d}T23:59:59.999Z"}\n',
        encoding="utf-8",
    )
    assert utc_day_writers(pkg) == {"planted_lambda.py": [UTC_WINDOW_LITERAL]}


def test_the_scan_fires_on_a_planted_astimezone_utc_day(tmp_path):
    pkg = tmp_path / "ingestion"
    pkg.mkdir()
    (pkg / "planted_lambda.py").write_text(
        "def day_of(dt):\n    return dt.astimezone(timezone.utc).strftime('%Y-%m-%d')\n",
        encoding="utf-8",
    )
    assert utc_day_writers(pkg) == {"planted_lambda.py": [ASTIMEZONE_UTC_THEN_DAY]}


def test_the_scan_does_not_fire_on_a_vendor_ignored_plus_zero_offset(tmp_path):
    """THE NEGATIVE CONTROL, and it is a live shape, not a hypothetical: habitify sends
    `f"{d}T00:00:00+00:00"` to an endpoint that reads only the date part and returns
    byte-identical payloads for `-07:00`. Its keys are measurably Pacific. A scan that
    flagged it would put a false `utc` declaration on a correct source — the same class of
    damage in the opposite direction."""
    pkg = tmp_path / "ingestion"
    pkg.mkdir()
    (pkg / "planted_lambda.py").write_text('URL = f"?from={d}T00:00:00+00:00"\n', encoding="utf-8")
    assert utc_day_writers(pkg) == {}
    assert "habitify_lambda.py" not in utc_day_writers()
    assert day_key_frame_for("habitify") == "pacific"


# ─────────────────────────────────────────────────────────────────────────────
# LEG 2 — the anchoring sites
# ─────────────────────────────────────────────────────────────────────────────
#
# Functions allowed to turn a `%Y-%m-%d` day into an instant with a LITERAL tzinfo and then
# do duration arithmetic on it. Every entry is a claim that the value being anchored is NOT
# a source `DATE#` key, so no registry facet governs it. Anything else must go through
# `common.pacific_time.anchor_day_key`.
FRAME_BLIND_ANCHOR_SITES = {
    "lambdas/operational/nudge_ledger_qa.py::_stamped_age_hours": (
        "Anchors a NUDGE-ledger sk (LEDGER_SK_PREFIX), not a source DATE# key — no source owns it and no "
        "day_key_frame facet governs it. The Pacific end-of-day anchor is deliberate and documented at the "
        "site: the ledger is written by a Pacific-scheduled job, and anchoring at the day's LAST instant "
        "understates the age, so the fallback can only delay a red and never manufacture one."
    ),
    "lambdas/emails/coach_panel_podcast_lambda.py::_hold_age_days": (
        "Anchors an episode HOLD stamp (`first_held_at`/`held_at`), a platform-written UTC instant truncated "
        "to its date — not a source DATE# key. The result is divided by 86400 into whole days, so a 7h "
        "anchor difference cannot change the decision it feeds (a hold retried after N days)."
    ),
}


def _own_body(fn):
    """Nodes belonging to `fn` ITSELF, not to a function nested inside it.

    `ast.walk` does not stop at a nested `def`, and that is not a detail here: the status
    page's `status()` is a 600-line handler with `_comp_status` defined inside it, so a
    naive walk attributes the inner function's arithmetic to the outer one and the site
    can never be cleared — the guard would go on reporting a defect after it was fixed,
    which is the fastest way to teach a reader to ignore it.
    """
    nested = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)
    out = []
    stack = [c for c in ast.iter_child_nodes(fn) if not isinstance(c, nested)]
    while stack:
        node = stack.pop()
        out.append(node)
        for child in ast.iter_child_nodes(node):
            if isinstance(child, nested):
                continue
            stack.append(child)
    return out


def hand_anchored_age_sites(roots=RUNTIME_ROOTS) -> dict:
    """{'<relpath>::<func>': [line, …]} — functions that build an aware instant from a
    `%Y-%m-%d` day with a literal tzinfo AND call `.total_seconds()` in the same function.

    The `.total_seconds()` conjunct is what keeps this honest. Roughly twenty sites in
    `lambdas/` attach a tzinfo to a parsed day and then immediately take `.date()` — whole-
    day arithmetic, where the tzinfo is discarded and the frame provably cannot matter.
    Flagging those would bury the two sites where the frame IS load-bearing, and a guard
    whose output is mostly noise stops being read (#3666's own lesson about per-site
    exemptions, applied to the guard instead of the code).
    """
    out = {}
    for root in roots:
        for path in sorted(root.rglob("*.py")):
            try:
                rel = path.relative_to(ROOT).as_posix()
            except ValueError:
                rel = path.name  # a planted tree outside the checkout (the control below)
            if rel == "lambdas/common/pacific_time.py":
                continue  # THE anchor itself — the one place the choice is made, from the facet
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover - the syntax gate owns this
                continue
            for fn in ast.walk(tree):
                if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                nodes = _own_body(fn)
                anchors = [n for n in nodes if _is_literal_day_anchor(n)]
                durations = [
                    n for n in nodes if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "total_seconds"
                ]
                if anchors and durations:
                    out[f"{rel}::{fn.name}"] = sorted(n.lineno for n in anchors)
    return out


def _is_literal_day_anchor(node) -> bool:
    """`datetime.strptime(<x>, "%Y-%m-%d").replace(..., tzinfo=<literal>)`."""
    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "replace"):
        return False
    if not any(kw.arg == "tzinfo" for kw in node.keywords):
        return False
    inner = node.func.value
    return (
        isinstance(inner, ast.Call)
        and isinstance(inner.func, ast.Attribute)
        and inner.func.attr == "strptime"
        and any(isinstance(a, ast.Constant) and a.value == "%Y-%m-%d" for a in inner.args)
    )


def test_no_unregistered_site_hand_anchors_a_day_key_for_an_age():
    """LEG 2. This is what caught `site_api_status._comp_status`, months after #3257 and
    #2817 each fixed 'the two consumers'."""
    unregistered = sorted(set(hand_anchored_age_sites()) - set(FRAME_BLIND_ANCHOR_SITES))
    assert not unregistered, (
        "These functions turn a YYYY-MM-DD day into an instant with a hardcoded tzinfo and then measure a "
        "duration from it. If the day is a source `DATE#` key, use common.pacific_time.anchor_day_key so the "
        "frame comes from the registry facet (#3257/#3913 — the error is exactly the 7h/8h offset, every "
        "time, silently). If it is not a source key, register it in FRAME_BLIND_ANCHOR_SITES with the "
        "reason:\n  " + "\n  ".join(unregistered)
    )


def test_the_frame_blind_registry_has_no_stale_entries():
    """An exemption for a site that no longer exists licences a silent regrowth."""
    stale = sorted(set(FRAME_BLIND_ANCHOR_SITES) - set(hand_anchored_age_sites()))
    assert not stale, "FRAME_BLIND_ANCHOR_SITES names sites that no longer hand-anchor — prune them:\n  " + "\n  ".join(stale)


def test_every_frame_blind_exemption_states_why_the_frame_cannot_matter():
    for site, reason in sorted(FRAME_BLIND_ANCHOR_SITES.items()):
        assert len(reason) >= 120, f"{site}: an exemption is a claim; write the reason ({len(reason)} chars)"


def test_the_leg_two_scan_would_see_a_planted_site(tmp_path):
    """The instrument, tested — and with the false-positive shape planted alongside, since
    the scan's value is entirely in the discrimination."""
    pkg = tmp_path / "lambdas"
    pkg.mkdir()
    (pkg / "planted.py").write_text(
        "def age_hours(day, now):\n"
        '    last = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc)\n'
        "    return (now - last).total_seconds() / 3600\n"
        "\n"
        "def days_dark(day, now):\n"
        '    last = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc)\n'
        "    return (now.date() - last.date()).days\n",
        encoding="utf-8",
    )
    seen = hand_anchored_age_sites(roots=(pkg,))
    names = {k.split("::")[1] for k in seen}
    assert names == {"age_hours"}, f"expected only the duration site, got {names}"


def test_the_status_page_is_no_longer_one_of_them():
    """The live find, pinned by absence so it cannot regrow. Named explicitly because the
    derived-set assertion above would also pass if the whole scan broke."""
    assert not [k for k in hand_anchored_age_sites() if "site_api_status" in k]
    src = (ROOT / "lambdas" / "web" / "site_api_status.py").read_text(encoding="utf-8")
    assert "anchor_day_key(last_date_str" in src


# ─────────────────────────────────────────────────────────────────────────────
# The behaviour the leg-2 fix actually changes
# ─────────────────────────────────────────────────────────────────────────────
def test_the_status_pages_source_age_now_comes_from_the_facet():
    """Per-source, from the registry — not one frame swept over twelve sources, which is
    the mistake in both directions (#3257 swept UTC, #2817 swept Pacific)."""
    from datetime import datetime, timedelta, timezone

    from common.pacific_time import anchor_day_key

    day = "2026-09-21"
    now = datetime(2026, 9, 22, 4, 0, tzinfo=timezone.utc)

    def hours(source):
        return (now - anchor_day_key(day, source)).total_seconds() / 3600

    assert hours("whoop") == 28.0, "a UTC-named day must be anchored at UTC midnight"
    assert hours("apple_health") == 28.0
    assert hours("eightsleep") == 21.0, "a Pacific-named day must be anchored at Pacific midnight"
    assert round(hours("eightsleep") - hours("whoop"), 1) == -7.0, "the frames must differ by the offset, or this proves nothing"
    assert anchor_day_key(day, "whoop").utcoffset() == timedelta(0)
    assert anchor_day_key(day, "eightsleep").utcoffset() == timedelta(hours=-7)


def test_the_status_page_day_bucket_is_unaffected_by_the_fix():
    """Blast radius, stated as a test. `_comp_status` also derives `days_ago` from
    `last_dt.date()`, and attaching a tzinfo never shifts a date — so green/yellow/red,
    which is driven by `effective_days`, is bit-identical after the change. Only
    `_hours_ago` (read in one branch, at >=3 days stale) moves."""
    from common.pacific_time import anchor_day_key

    for source in ("whoop", "apple_health", "eightsleep", "withings", "strava", "garmin", "hevy"):
        for day in ("2026-01-01", "2026-06-08", "2026-09-21", "2026-12-15"):
            assert anchor_day_key(day, source).date().isoformat() == day
