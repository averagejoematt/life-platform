"""#3293 — two more surfaces stated a direction of travel from a signed value.

THE TWO DEFECTS, READ OFF `main`
--------------------------------
1. ``lambdas/web/og_moments.py`` — the weekly-recap moment card::

       bits.append(f"{round(journey['lost_lbs'], 1)} lbs down")

   A STATIC direction word over a SIGNED value. ``lost_lbs`` is ``start − current``, so
   a gain is negative and the line published *"-5.2 lbs down"* — the identical double
   negative #3285 removed from the home share card, on a surface that is also shared
   externally. One string feeds three reader-facing places (the card's meta line, the
   shell's ``og:description``, and the page body), so all three carried it.

2. ``lambdas/web/site_api_pulse.py`` — the ``scale`` glyph::

       "direction": "down" if w_val and w_val < start_weight else "up"

   Two faults in one expression. No flat case: a delta of exactly zero asserted "up".
   And a falsy collapse: ``w_val`` of ``None`` (no weigh-in — the ordinary state on a
   day Matthew has not stepped on the scale) short-circuits the ``and`` and ALSO
   asserts "up". That is a direction claim with **no data behind it**, which is the
   ADR-104 violation — absence rendered as an assertion instead of as absence.

   The same module already did it correctly 100+ lines later, in the narrative's
   ``dir_word``: three-way, on an explicit ``is not None`` guard. So the fix is
   adoption, not design — and the point of routing BOTH through one function is that
   they can no longer be edited apart.

WHAT THESE TESTS DO
-------------------
Every case is driven through the REAL surface, not through the helper alone: the
og_moments tests sweep the moment and read the bytes that get written to S3, and the
pulse tests drive the routed ``/api/pulse`` handler and read the payload a reader gets.
A helper-only fixture is the #2703 class — a test on real code the running path never
reaches, which #3200 shipped verdict-closed and non-functional.

The mutations that were watched to FAIL before the fix are named on each test.
"""

import ast
import json
import os
import sys
from datetime import datetime, timezone

import pytest

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "scripts"))

from common.pacific_time import PACIFIC  # noqa: E402
from web import (
    og_moments as om,  # noqa: E402
    site_api_common as common,  # noqa: E402
    site_api_intelligence as intel,  # noqa: E402
    site_api_pulse as pulse_mod,  # noqa: E402
)
from web.journey_direction import DOWN, EVEN, UNKNOWN, UP, classify_delta  # noqa: E402

# ─────────────────────────────────────────────────────────────────────────────
# Surface 1 — og_moments: the weekly recap moment
# ─────────────────────────────────────────────────────────────────────────────


class _FakeImg:
    """Stands in for the Pillow card so this file needs no PIL (same posture as
    tests/test_og_moments.py — what is under test here is the WORDS, not pixels)."""

    def save(self, buf, **kw):
        buf.write(b"\x89PNG-fake")


class _FakeS3:
    def __init__(self):
        self.puts = {}

    def get_object(self, Bucket, Key):
        raise KeyError(Key)

    def put_object(self, Bucket, Key, Body, ContentType, CacheControl=None):
        self.puts[Key] = Body


def _recap(lost_lbs):
    """Sweep the weekly recap and return (card_meta_line, shell_html).

    `card_meta_line` is the third argument og_moments hands the card renderer — the
    meta line the PNG actually draws. `shell_html` carries both the `og:description`
    and the page body. Between them that is all three surfaces the issue names.
    """
    captured = {}

    def _fake_card(kicker, title, meta_line, footer_note):
        captured["meta"] = meta_line
        return _FakeImg()

    real_card = om.build_moment_card
    om.build_moment_card = _fake_card
    try:
        s3 = _FakeS3()
        out = om._sweep_week_recap(
            s3,
            {"journey": {"lost_lbs": lost_lbs}, "vitals": {"hrv_ms": 52}, "platform": {"days_in": 21, "tier0_streak": 3}},
        )
    finally:
        om.build_moment_card = real_card
    assert out, "the recap swept to nothing — the fixture no longer exercises the surface"
    return captured["meta"], s3.puts[f"generated/moments/week/{out['id']}/index.html"].decode()


def _all_three(lost_lbs):
    """The card meta line, the og:description and the page body as one tuple — the three
    places the issue's acceptance box names, each pulled from the real written artifact."""
    meta, shell = _recap(lost_lbs)
    desc = shell.split('og:description" content="', 1)[1].split('"', 1)[0]
    body = shell.split("<p>", 1)[1].split("</p>", 1)[0]
    return meta, desc, body


def test_a_gain_renders_as_a_gain_on_all_three_recap_surfaces():
    """THE MUST-FAIL CASE for surface 1. Mutation watched to fail before the fix:
    restoring `f"{round(journey['lost_lbs'], 1)} lbs down"` makes every assertion here
    red, because the card, the unfurl and the page all read "-5.2 lbs down"."""
    for text in _all_three(-5.2):
        assert "5.2 lbs up" in text, text
        assert "down" not in text, f"a weight GAIN published as down: {text!r}"
        assert "-5.2" not in text, f"double negative back on a shared artifact: {text!r}"


def test_a_loss_still_renders_as_a_loss():
    """The direction that was already right must stay right — a fix that inverted the
    sign would satisfy the gain test alone."""
    for text in _all_three(13.4):
        assert "13.4 lbs down" in text, text
        assert " up" not in text, text


def test_a_zero_delta_claims_neither_direction():
    """A delta of exactly zero is not movement. Neither "down" nor "up" may appear."""
    for text in _all_three(0.0):
        assert "weight even" in text, text
        assert "lbs down" not in text and "lbs up" not in text, text


def test_a_sub_display_delta_is_even_not_a_direction():
    """0.04 lb renders as "0.0" at one decimal. Ruling on the RAW value would print
    "0.0 lbs down" — the caption disagreeing with its own number, which is the property
    the shared ruling exists to guarantee (it rounds BEFORE the sign test)."""
    for text in _all_three(-0.04):
        assert "weight even" in text, text
        assert "up" not in text and "down" not in text, text


@pytest.mark.parametrize("absent", [None, "", "5.2", [], float("nan"), float("inf"), True])
def test_an_unreadable_delta_contributes_no_clause_at_all(absent):
    """ADR-104: absence is an answer. The recap simply omits the weight bit — it never
    guesses a direction, and it no longer raises (the old `round()` on a string did)."""
    for text in _all_three(absent):
        assert "lbs down" not in text and "lbs up" not in text and "weight even" not in text, text
        assert "HRV 52 ms" in text, "the rest of the recap must still render"


def test_the_recap_clause_comes_from_the_shared_ruling_not_a_local_copy():
    """The helper's output is `classify_delta`'s answer, verbatim — not a second
    implementation that happens to agree on the four cases above."""
    for v in (-5.2, -0.4, 0.0, 0.4, 13.4, None, "x"):
        direction, magnitude = classify_delta(v, decimals=1)
        got = om._weight_bit(v)
        if direction == UNKNOWN:
            assert got == []
        elif direction == EVEN:
            assert got == ["weight even"]
        else:
            assert got == [f"{magnitude} lbs {direction}"], (v, got)


# ─────────────────────────────────────────────────────────────────────────────
# Surface 2 — site_api_pulse: the scale glyph and the narrative
# ─────────────────────────────────────────────────────────────────────────────

_WITHINGS_PK = "USER#matthew#SOURCE#withings"
START_WEIGHT = 315.0
NOW = datetime(2026, 8, 27, 19, 0, tzinfo=timezone.utc)  # 12:00 PDT — UTC-today == PT-today
TODAY_PT = NOW.astimezone(PACIFIC).strftime("%Y-%m-%d")


def test_the_ruling_refuses_to_name_a_direction_without_a_weight():
    """The unit form of the filed defect. Every one of these returned "up" on `main`."""
    for w in (None, 0, 0.0, "", "heavy", [], float("nan"), float("inf"), True, False):
        assert pulse_mod.weight_direction(w, START_WEIGHT) == (UNKNOWN, None), w


def test_the_ruling_is_three_way_and_signed_correctly():
    assert pulse_mod.weight_direction(300.0, START_WEIGHT) == (DOWN, 15.0)  # lighter than start
    assert pulse_mod.weight_direction(320.0, START_WEIGHT) == (UP, 5.0)  # heavier than start
    assert pulse_mod.weight_direction(315.0, START_WEIGHT) == (EVEN, 0.0)  # the case that asserted "up"


def test_the_pulse_ruling_defers_to_the_shared_one_including_the_sign_flip():
    """`classify_delta` rules on `lost_lbs` (start − current); this module's own delta
    runs the other way. The conversion must live in exactly one place, and it must be
    the right way round — an inverted wrapper would still be three-way and still be a
    lie. Checked against the shared ruling across the sign."""
    for w in (280.0, 314.9, 315.0, 315.1, 350.0):
        assert pulse_mod.weight_direction(w, START_WEIGHT) == classify_delta(START_WEIGHT - w, 1), w


class FakeTable:
    """Answers table.query() from {pk: [items]}, honouring the Key("sk").between range,
    ScanIndexForward and Limit — the same shape tests/test_vitals_today_frame_3287.py
    drives the handler with."""

    def __init__(self, by_pk=None):
        self.by_pk = by_pk or {}

    @staticmethod
    def _find_pk(cond):
        vals = getattr(cond, "_values", None)
        if vals is None:
            return None
        for v in vals:
            got = FakeTable._find_pk(v) if hasattr(v, "_values") else (v if isinstance(v, str) else None)
            if isinstance(got, str) and got.startswith("USER#"):
                return got
        return None

    @staticmethod
    def _find_sk_range(cond):
        vals = getattr(cond, "_values", None)
        if vals is None:
            return None
        key = vals[0] if vals else None
        if getattr(key, "name", None) == "sk" and getattr(cond, "expression_operator", None) == "BETWEEN" and len(vals) == 3:
            return (vals[1], vals[2])
        for v in vals:
            if hasattr(v, "_values"):
                found = FakeTable._find_sk_range(v)
                if found:
                    return found
        return None

    def query(self, **kwargs):
        cond = kwargs.get("KeyConditionExpression")
        pk = self._find_pk(cond) if cond is not None else None
        sk_range = self._find_sk_range(cond) if cond is not None else None
        items = list(self.by_pk.get(pk, []))
        if sk_range:
            lo, hi = sk_range
            items = [i for i in items if lo <= str(i.get("sk", "")) <= hi]
        if kwargs.get("ScanIndexForward") is False:
            items = sorted(items, key=lambda i: str(i.get("sk", "")), reverse=True)
        limit = kwargs.get("Limit")
        return {"Items": items[:limit] if limit else items}

    def get_item(self, **kwargs):
        return {}


def _frozen(at):
    return type(
        "_At",
        (datetime,),
        {"_at": at, "now": classmethod(lambda cls, tz=None: cls._at.astimezone(tz) if tz else cls._at.replace(tzinfo=None))},
    )


def _pulse(monkeypatch, weight_lbs, day=None):
    """Drive the routed /api/pulse handler with one withings weigh-in (or none)."""
    from web import vitals_resolver

    day = day or TODAY_PT
    row = {"pk": _WITHINGS_PK, "sk": f"DATE#{day}", "date": day, "weight_lbs": weight_lbs} if weight_lbs is not None else None
    monkeypatch.setattr(pulse_mod, "datetime", _frozen(NOW))
    monkeypatch.setattr(vitals_resolver, "datetime", _frozen(NOW))
    monkeypatch.setattr(intel, "table", FakeTable({_WITHINGS_PK: [row] if row else []}))
    monkeypatch.setattr(intel, "_latest_item", lambda src, *a, **k: row if src == "withings" else None)
    monkeypatch.setattr(intel, "_get_profile", lambda: {"journey_start_weight_lbs": START_WEIGHT})
    monkeypatch.setattr(common, "EXPERIMENT_START", "2026-08-17")
    monkeypatch.setattr(intel, "EXPERIMENT_START", "2026-08-17")
    return json.loads(intel.handle_pulse()["body"])["pulse"]


def _narrative(p):
    return " ".join(p.get("narrative") or []) if isinstance(p.get("narrative"), list) else str(p.get("narrative") or "")


def test_an_absent_weigh_in_asserts_no_direction_on_the_wire(monkeypatch):
    """THE MUST-FAIL CASE for surface 2, on the served payload. On `main` this returned
    `direction: "up"` beside `value: null, delta: null` — a direction claim with nothing
    behind it. Mutation watched to fail before the fix: restoring the one-line
    `"down" if w_val and w_val < start_weight else "up"`."""
    scale = _pulse(monkeypatch, None)["glyphs"]["scale"]
    assert scale["value"] is None and scale["delta"] is None, "the fixture is not exercising the absent case"
    assert scale["direction"] is None, f"a direction published with no weigh-in behind it: {scale['direction']!r}"


def test_an_absent_weigh_in_leaves_the_narrative_silent_on_weight(monkeypatch):
    p = _pulse(monkeypatch, None)
    text = _narrative(p)
    assert "from start" not in text, text
    assert " lbs " not in text, text


def test_a_zero_delta_is_flat_not_up(monkeypatch):
    """A reader standing at exactly the start weight was told he had gone "up"."""
    p = _pulse(monkeypatch, START_WEIGHT)
    assert p["glyphs"]["scale"]["direction"] == EVEN
    assert p["glyphs"]["scale"]["delta"] == 0.0
    assert "flat 0.0 from start" in _narrative(p), _narrative(p)


def test_a_gain_and_a_loss_are_named_correctly_on_the_wire(monkeypatch):
    gain = _pulse(monkeypatch, START_WEIGHT + 5.0)
    loss = _pulse(monkeypatch, START_WEIGHT - 8.0)
    assert gain["glyphs"]["scale"]["direction"] == UP and gain["glyphs"]["scale"]["delta"] == 5.0
    assert loss["glyphs"]["scale"]["direction"] == DOWN and loss["glyphs"]["scale"]["delta"] == -8.0
    assert "up 5.0 from start" in _narrative(gain), _narrative(gain)
    assert "down 8.0 from start" in _narrative(loss), _narrative(loss)


@pytest.mark.parametrize("w", [None, START_WEIGHT - 8.0, START_WEIGHT - 0.04, START_WEIGHT, START_WEIGHT + 0.04, START_WEIGHT + 5.0])
def test_the_glyph_and_the_narrative_can_no_longer_disagree(monkeypatch, w):
    """The property the whole fix is for. Across the sign — including the two sub-display
    deltas that round to zero and the absent case — the glyph's `direction` and the
    narrative's word are the SAME ruling. Before the fix a 315.0 lb reading produced
    `direction: "up"` in the same payload as "flat 0.0 from start"."""
    p = _pulse(monkeypatch, w)
    text = _narrative(p)
    glyph = p["glyphs"]["scale"]["direction"]
    if glyph is None:
        assert "from start" not in text
        return
    assert glyph in {DOWN, UP, EVEN}
    expected_word = pulse_mod._NARRATIVE_DIR_WORD[glyph]
    assert f"{expected_word} " in text, (glyph, text)
    for other in set(pulse_mod._NARRATIVE_DIR_WORD.values()) - {expected_word}:
        assert f"— {other} " not in text, (glyph, other, text)


def test_the_delta_and_the_direction_never_contradict_each_other(monkeypatch):
    """A signed `delta` beside a direction word is the whole bug shape. Read them against
    each other in one payload, the way the page renders them."""
    for w in (START_WEIGHT - 8.0, START_WEIGHT, START_WEIGHT + 5.0):
        scale = _pulse(monkeypatch, w)["glyphs"]["scale"]
        d, direction = scale["delta"], scale["direction"]
        assert (d < 0) == (direction == DOWN), (d, direction)
        assert (d > 0) == (direction == UP), (d, direction)
        assert (d == 0) == (direction == EVEN), (d, direction)


# ─────────────────────────────────────────────────────────────────────────────
# The guard — a SCOPED registry, and why it is scoped
# ─────────────────────────────────────────────────────────────────────────────
#
# THE LIMIT, STATED IN FILE (the issue's acceptance box explicitly offers this fork).
#
# The guard we would rather have is "fail if ANY new surface states a direction without
# going through the ruling". Every implementation of that reduces to scanning the repo
# for a direction LEXICON — "up", "down", "gained", "improving" — next to a formatted
# value. That is phrase-matching, and every phrase-matched member of the #2959/#3003/
# #3199 family has failed in the field.
#
# It is not a hypothetical here. `site_api_pulse.py` already contains
#
#     f"Weight up {_wt_d:.1f} lbs from yesterday. Likely water retention …"
#
# which is a static direction word immediately after a formatted signed number — and it
# is CORRECT, because it is only reached under `if _wt_d > 3`. A lexicon scan flags it on
# day one, in the very file it is meant to guard. Tuning the lexicon until that one case
# passes is how these guards become decorative.
#
# So the guard is structural but SCOPED: an enumerated registry of the surfaces that
# state a direction of travel about the weight journey, each verified by AST to reach
# `classify_delta` from its own entry point. It cannot discover a sixth surface. What it
# CAN do is fail the moment one of these five stops routing through the ruling — which is
# how #3293 happened (#3285 fixed two of the family and left three), and it makes the
# registry the visible place a new surface has to be added.

_RULING = "classify_delta"
_RULING_MODULE = "journey_direction"

# (repo-relative module, entry point a reader-facing artifact is built by).
# ADJUDICATED OUT, recorded so a later sweep does not reopen them (from the issue):
# `og_image_lambda.py`'s "TIER-0 STREAK" and `card_engine.py`'s "LEVEL · <tier>" paint a
# static success colour over counts that CANNOT go negative, under captions that are not
# directional. There is no sign for them to disagree with.
_DIRECTION_SURFACES = [
    ("lambdas/web/og_image_lambda.py", "build_home"),  # #3285 — the home share card's delta tile
    ("scripts/v4_proof.py", "home_og"),  # #3285 — the home og:description
    ("scripts/v4_proof.py", "home_block_html"),  # #3285 — the no-JS home proof block
    ("lambdas/web/og_moments.py", "_sweep_week_recap"),  # #3293 — the weekly recap moment
    ("lambdas/web/site_api_pulse.py", "pulse"),  # #3293 — the scale glyph + the daily narrative
]


def _reaches(tree, entry, target, depth=6):
    """True if `entry` reaches a call to `target` through module-local calls.

    Deliberately intra-module: a surface that hands its direction off to another module
    has moved the claim, and the registry should name that module too."""
    calls = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names = set()
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call):
                    fn = sub.func
                    names.add(fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", None))
            calls[node.name] = names - {None}
    seen, frontier = set(), {entry}
    for _ in range(depth):
        if not frontier:
            break
        if any(target in calls.get(name, set()) for name in frontier):
            return True
        seen |= frontier
        frontier = {n for name in frontier for n in calls.get(name, set())} & set(calls) - seen
    return False


@pytest.mark.parametrize("rel,entry", _DIRECTION_SURFACES, ids=[f"{r.rsplit('/', 1)[-1]}:{e}" for r, e in _DIRECTION_SURFACES])
def test_every_registered_direction_surface_routes_through_the_ruling(rel, entry):
    """Mutation watched to fail before the fix: with `main`'s og_moments and
    site_api_pulse in place, the two #3293 rows here fail and the three #3285 rows pass —
    which is exactly the state the issue describes."""
    path = os.path.join(_REPO, rel)
    tree = ast.parse(open(path, encoding="utf-8").read())
    assert any(
        isinstance(n, ast.ImportFrom) and n.module == "web.journey_direction" for n in ast.walk(tree)
    ), f"{rel} states a direction of travel without importing the shared ruling"
    assert _reaches(tree, entry, _RULING), f"{rel}:{entry} no longer reaches {_RULING}() — it is ruling on the sign itself again"


def test_the_guard_can_fail():
    """POSITIVE CONTROL. A registry check that cannot fail is not a guard (#3220). Run
    the same AST predicate against a module that legitimately does NOT route through the
    ruling, and against the pre-fix expression itself."""
    tree = ast.parse(open(os.path.join(_REPO, "lambdas", "web", "site_api_common.py"), encoding="utf-8").read())
    assert not any(isinstance(n, ast.ImportFrom) and n.module == "web.journey_direction" for n in ast.walk(tree))
    pre_fix = ast.parse('def pulse():\n    d = "down" if w and w < s else "up"\n')
    assert not _reaches(pre_fix, "pulse", _RULING), "the predicate passes the exact code #3293 was filed about"
    post_fix = ast.parse("def pulse():\n    d = weight_direction(w, s)\ndef weight_direction(a, b):\n    return classify_delta(b - a)\n")
    assert _reaches(post_fix, "pulse", _RULING), "the predicate cannot see a one-hop route to the ruling"


def test_the_registry_covers_every_module_that_imports_the_ruling():
    """The registry going stale is the failure mode a registry has. If a module imports
    the ruling and is not listed above, it is a direction-of-travel surface no row is
    watching — add it (with its entry point) rather than deleting this test.

    AST, not text: a module that merely NAMES the ruling in a comment or a docstring is
    not a surface, and a textual sweep would drag every such mention into the registry
    (`scripts/gate_census_mutations.py`, which plants this gate's own mutation, is
    exactly that case). The limit is the mirror image — a module that reaches the ruling
    through `importlib` rather than an import statement is invisible here. No consumer
    does that today, and the five registered rows are checked for the call itself.
    """
    listed = {rel for rel, _ in _DIRECTION_SURFACES}
    importers = set()
    for root in ("lambdas", "scripts", "mcp"):
        for dirpath, _dirs, files in os.walk(os.path.join(_REPO, root)):
            for f in files:
                if not f.endswith(".py"):
                    continue
                rel = os.path.relpath(os.path.join(dirpath, f), _REPO)
                if rel.endswith(_RULING_MODULE + ".py"):
                    continue
                try:
                    tree = ast.parse(open(os.path.join(dirpath, f), encoding="utf-8").read())
                except SyntaxError:
                    continue
                for n in ast.walk(tree):
                    named = [n.module] if isinstance(n, ast.ImportFrom) else [a.name for a in n.names] if isinstance(n, ast.Import) else []
                    if any(str(m or "").split(".")[-1] == _RULING_MODULE for m in named):
                        importers.add(rel)
                        break
    assert importers <= listed, f"unregistered direction-of-travel surfaces: {sorted(importers - listed)}"
