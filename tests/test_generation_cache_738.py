"""
#738 / ADR-126 — hash-and-reuse for coach generation briefs.

Pins the two contracts that matter:
  1. STABILITY: identical semantic inputs fingerprint identically even when pure
     bookkeeping (timestamps, `_`-prefixed keys) differs run-to-run — so reuse can
     actually trigger on a quiet day.
  2. THE HONESTY INVARIANT: any semantic change — a vitals number, a stance edit,
     even a staleness day-count ticking up — changes the fingerprint, so reuse can
     never serve stale-but-claiming-fresh output.

Plus the fail-soft DDB helpers (a broken table degrades to "regenerate", never raises).
"""

import os
import sys
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

from common import generation_cache as gc  # noqa: E402

# ── fingerprint stability ─────────────────────────────────────────────────────


def test_dict_key_order_does_not_change_fingerprint():
    a = {"recovery": 62, "hrv": 48, "weight": 214.2}
    b = {"weight": 214.2, "hrv": 48, "recovery": 62}
    assert gc.brief_fingerprint(a) == gc.brief_fingerprint(b)


def test_bookkeeping_keys_are_ignored():
    """Two briefs identical in substance but stamped at different times/runs must
    fingerprint the same — otherwise reuse never triggers."""
    monday = {"stance": "focus on sleep", "gap_days": 0, "_generated_at": "2026-07-06", "as_of": "2026-07-06T04:00:00"}
    tuesday = {"stance": "focus on sleep", "gap_days": 0, "_generated_at": "2026-07-07", "as_of": "2026-07-07T04:00:00"}
    assert gc.brief_fingerprint(monday) == gc.brief_fingerprint(tuesday)


def test_underscore_and_volatile_stripped_at_any_depth():
    nested = {"outer": {"real": 1, "_fallback": True, "created_at": "x", "inner": {"v": 2, "run_id": "abc"}}}
    clean = {"outer": {"real": 1, "inner": {"v": 2}}}
    assert gc.brief_fingerprint(nested) == gc.brief_fingerprint(clean)


def test_decimal_and_native_number_fingerprint_equal():
    """DDB reads come back as Decimal; the same value from a fresh compute is a
    float/int. They must not spuriously bust the cache."""
    assert gc.brief_fingerprint({"weight": Decimal("214.2")}) == gc.brief_fingerprint({"weight": 214.2})


# ── the honesty invariant: semantic change MUST bust the fingerprint ───────────


def test_changed_number_busts_fingerprint():
    assert gc.brief_fingerprint({"recovery": 62}) != gc.brief_fingerprint({"recovery": 63})


def test_staleness_day_count_ticking_busts_fingerprint():
    """The explicit honesty guard from the issue: a staleness counter advancing is
    a real change and must force a fresh generation."""
    day3 = {"engagement_signal": {"gap_days": 3, "last_food_log_date": "2026-07-03"}}
    day4 = {"engagement_signal": {"gap_days": 4, "last_food_log_date": "2026-07-03"}}
    assert gc.brief_fingerprint(day3) != gc.brief_fingerprint(day4)


def test_stance_edit_busts_fingerprint():
    a = gc.brief_fingerprint({"current_stance": "watching HRV recover"})
    b = gc.brief_fingerprint({"current_stance": "shifting focus to protein"})
    assert a != b


def test_new_list_item_busts_fingerprint():
    assert gc.brief_fingerprint({"open_threads": ["sleep"]}) != gc.brief_fingerprint({"open_threads": ["sleep", "protein"]})


def test_all_parts_participate_in_the_hash():
    """system_prompt + user_message are hashed together; a change in EITHER busts it."""
    base = gc.brief_fingerprint("SYS voice rules", "USER brief A")
    assert base != gc.brief_fingerprint("SYS voice rules CHANGED", "USER brief A")
    assert base != gc.brief_fingerprint("SYS voice rules", "USER brief B")


# ── DDB helpers (fake table) ──────────────────────────────────────────────────


class _FakeTable:
    def __init__(self):
        self.store = {}
        self.updates = []

    def get_item(self, Key):
        item = self.store.get((Key["pk"], Key["sk"]))
        return {"Item": item} if item else {}

    def put_item(self, Item):
        self.store[(Item["pk"], Item["sk"])] = Item

    def update_item(self, Key, UpdateExpression, ExpressionAttributeValues):
        self.updates.append((Key, ExpressionAttributeValues))


class _BrokenTable:
    def get_item(self, **_):
        raise RuntimeError("ddb down")

    def put_item(self, **_):
        raise RuntimeError("ddb down")

    def update_item(self, **_):
        raise RuntimeError("ddb down")


def test_record_reuse_bumps_bookkeeping():
    t = _FakeTable()
    gc.record_reuse(t, "sleep_coach", "daily_brief_sleep", "2026-07-07")
    assert len(t.updates) == 1
    key, vals = t.updates[0]
    assert key["sk"] == gc.cache_sk("sleep_coach", "daily_brief_sleep")
    assert vals[":d"] == "2026-07-07" and vals[":one"] == 1


def test_store_shape_resets_unchanged_clock():
    t = _FakeTable()
    gc.store_entry(t, "sleep_coach", "daily_brief_sleep", "fp", "text", "2026-07-06")
    item = t.store[(gc.CACHE_PK, gc.cache_sk("sleep_coach", "daily_brief_sleep"))]
    assert item["first_generated"] == "2026-07-06"
    assert item["reuse_count"] == 0
    assert item["brief_hash"] == "fp"


# ── #2889: pass STRUCTURE, not rendered prose ─────────────────────────────────
#
# THE MEASURED DEFECT. `canonicalize()` strips bookkeeping by dict KEY. The only
# production call site hashed `system_prompt` + `user_message_full` — rendered
# strings with `json.dumps(brief)` baked in — so every volatile key rode straight
# into the digest and the whole `_VOLATILE_KEYS` mechanism was a no-op. Live
# evidence on 2026-08-22, ~2 months after ADR-126 landed: `GenerationSkippedUnchanged`
# had never been emitted (zero metric variants), and all 8 rows of
# USER#matthew#SOURCE#coach_gen_cache carried `reuse_count = 0` with
# `first_generated == last_generated` — every row written on a miss, none ever reused.


def _brief(generation_date="2026-08-22", weight=321.0):
    return {
        "generation_date": generation_date,
        "as_of": generation_date + "T17:00:00Z",
        "decision_class_ceiling": "observational",
        "current_stance": {"focus": "protein adherence", "as_of": generation_date},
        "vitals": {"weight_lbs": weight},
    }


def test_a_new_day_alone_does_not_bust_a_structured_fingerprint():
    """The whole point of _VOLATILE_KEYS, finally reachable."""
    a = gc.brief_fingerprint({"brief": _brief("2026-08-22")})
    b = gc.brief_fingerprint({"brief": _brief("2026-08-23")})
    assert a == b


def test_the_regression_reproduced_rendered_prose_busts_on_the_date_alone():
    """The pre-fix shape, pinned so nobody reintroduces it believing it equivalent."""
    import json as _json

    a = gc.brief_fingerprint(f"GENERATION BRIEF:\n{_json.dumps(_brief('2026-08-22'), indent=2)}")
    b = gc.brief_fingerprint(f"GENERATION BRIEF:\n{_json.dumps(_brief('2026-08-23'), indent=2)}")
    assert a != b, "rendered prose must still bust — this is the defect, documented, not fixed in place"


def test_a_real_semantic_change_still_busts_the_structured_fingerprint():
    """The honesty invariant is NOT weakened: only keys the design already declared
    volatile are stripped. A number moving still forces a fresh generation."""
    a = gc.brief_fingerprint({"brief": _brief(weight=321.0)})
    b = gc.brief_fingerprint({"brief": _brief(weight=319.4)})
    assert a != b


def test_a_day_count_that_is_semantic_still_busts():
    """gap_days is NOT in _VOLATILE_KEYS and must not become so: a brief that says
    'it has been 4 days' may never be reused on day 5. This is the design ceiling on
    the achievable skip rate, asserted rather than assumed."""
    a = gc.brief_fingerprint({"brief": {**_brief(), "engagement_signal": {"gap_days": 4}}})
    b = gc.brief_fingerprint({"brief": {**_brief(), "engagement_signal": {"gap_days": 5}}})
    assert a != b


def test_part_fingerprints_are_per_part_and_stable():
    parts = {"brief": _brief(), "corrections": "", "trends": {"weight": {"direction": "down"}}}
    fps = gc.part_fingerprints(parts)
    assert set(fps) == set(parts)
    assert fps == gc.part_fingerprints(parts)
    assert fps["brief"] != fps["trends"]


def test_changed_parts_names_only_what_changed():
    old = gc.part_fingerprints({"brief": _brief(), "corrections": ""})
    new = gc.part_fingerprints({"brief": _brief(weight=300.0), "corrections": ""})
    assert gc.changed_parts(old, new) == ["brief"]


def test_changed_parts_marks_an_unknown_part_rather_than_calling_it_unchanged():
    """An entry written before per-part digests existed must not read as a match —
    an unknown is reported, never silently counted as equal."""
    old = gc.part_fingerprints({"brief": _brief()})
    new = gc.part_fingerprints({"brief": _brief(), "corrections": "new block"})
    assert gc.changed_parts(old, new) == ["?corrections"]


def test_changed_parts_on_a_legacy_entry_says_so():
    assert gc.changed_parts({}, {"brief": "abc"}) == ["<no part digests stored>"]


def test_store_entry_persists_part_hashes_when_given():
    t = _FakeTable()
    parts = {"brief": _brief()}
    assert gc.store_entry(t, "sleep_coach", "daily_brief_sleep", "fp", "text", "2026-08-22", parts=parts)
    stored = t.store[(gc.CACHE_PK, gc.cache_sk("sleep_coach", "daily_brief_sleep"))]
    assert stored["part_hashes"] == gc.part_fingerprints(parts)


def test_store_entry_without_part_hashes_is_unchanged():
    """Additive: the pre-#2889 shape still stores, with no empty key left behind."""
    t = _FakeTable()
    assert gc.store_entry(t, "sleep_coach", "daily_brief_sleep", "fp", "text", "2026-08-22")
    stored = t.store[(gc.CACHE_PK, gc.cache_sk("sleep_coach", "daily_brief_sleep"))]
    assert "part_hashes" not in stored


def test_the_call_site_fingerprints_structure_not_the_rendered_message():
    """AST call-site pin (#2564's idiom). The unit tests above prove the helpers
    behave; only this proves PRODUCTION uses them that way. Without it the module
    could be perfect while the one caller keeps hashing prose — which is precisely
    the state #2889 found, live, for two months behind a green suite.

    #3107 moved the production call site from `ai_calls.py` into
    `coach/coach_brief_input_gate.py` (the gate is now two gates, and `ai_calls` was
    at its module-size ceiling). The scan follows the code and covers BOTH files —
    a guard that keeps scanning the file the logic left is the vacuous-pass class
    this assertion exists to prevent, so an empty result across both still fails."""
    import ast
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1] / "lambdas"
    sources = [root / "ai" / "ai_calls.py", root / "coach" / "coach_brief_input_gate.py"]
    fingerprinting = {"brief_fingerprint", "check_reuse_or_explain", "brief_parts", "part_fingerprints", "upstream_parts"}
    calls = []
    for src in sources:
        tree = ast.parse(src.read_text(encoding="utf-8"))
        calls += [
            n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "attr", getattr(n.func, "id", None)) in fingerprinting
        ]
    assert calls, "no generation-cache fingerprint call site found in the coach-brief path — the scan is vacuous, not clean"
    assert any(getattr(c.func, "attr", getattr(c.func, "id", None)) == "check_reuse_or_explain" for c in calls), (
        "production must go through check_reuse_or_explain — it is the seam that keeps the parts named "
        "in generation_cache and logs the miss reason (#2889)"
    )
    for call in calls:
        for arg in list(call.args) + [kw.value for kw in call.keywords]:
            assert not isinstance(arg, ast.JoinedStr), "an f-string part defeats canonicalize (#2889)"
            assert not (isinstance(arg, ast.Name) and arg.id.endswith("message_full")), (
                "the rendered prompt is being fingerprinted again — canonicalize strips by dict KEY, "
                "so a rendered part carries generation_date into the digest and the cache can never hit (#2889)"
            )


def test_brief_parts_names_every_part_here_not_at_the_call_site():
    """The part NAMES are a property of this module, so a caller cannot quietly drop
    one — dropping a part narrows the fingerprint, the direction that could serve
    stale output as fresh."""
    p = gc.brief_parts("sys", {"a": 1}, {"b": 2}, {"c": 3}, "inv", "corr")
    assert set(p) == {"system_prompt", "brief", "domain_data", "trends", "data_inventory", "corrections"}
    assert p["system_prompt"] == "sys" and p["corrections"] == "corr"


def test_check_reuse_or_explain_returns_the_hit_and_never_logs_a_miss(capsys):
    t = _FakeTable()
    parts = gc.brief_parts("sys", _brief(), {}, {}, "inv", "")
    fp = gc.brief_fingerprint(parts)
    gc.store_entry(t, "sleep_coach", "daily_brief_sleep", fp, "the text", "2026-08-22", parts=parts)
    got_fp, out, since = gc.check_reuse_or_explain(t, "sleep_coach", "daily_brief_sleep", parts)
    assert (got_fp, out, since) == (fp, "the text", "2026-08-22")
    assert "GEN-CACHE-MISS" not in capsys.readouterr().out


def test_check_reuse_or_explain_names_the_changed_part_on_a_miss(capsys):
    t = _FakeTable()
    old = gc.brief_parts("sys", _brief(weight=321.0), {}, {}, "inv", "")
    gc.store_entry(t, "sleep_coach", "daily_brief_sleep", gc.brief_fingerprint(old), "text", "2026-08-22", parts=old)
    new = gc.brief_parts("sys", _brief(weight=300.0), {}, {}, "inv", "")
    _fp, out, _since = gc.check_reuse_or_explain(t, "sleep_coach", "daily_brief_sleep", new)
    assert out is None
    line = capsys.readouterr().out
    assert "GEN-CACHE-MISS" in line and "parts changed: brief" in line


def test_check_reuse_or_explain_hits_when_only_the_day_moved(capsys):
    """End to end, through the real entry point: the whole point of #2889."""
    t = _FakeTable()
    monday = gc.brief_parts("sys", _brief("2026-08-22"), {}, {}, "inv", "")
    gc.store_entry(t, "c", "o", gc.brief_fingerprint(monday), "text", "2026-08-22", parts=monday)
    tuesday = gc.brief_parts("sys", _brief("2026-08-23"), {}, {}, "inv", "")
    _fp, out, since = gc.check_reuse_or_explain(t, "c", "o", tuesday)
    assert out == "text" and since == "2026-08-22"


def test_check_reuse_or_explain_is_fail_soft_on_a_broken_table(capsys):
    parts = gc.brief_parts("sys", _brief(), {}, {}, "inv", "")
    fp, out, since = gc.check_reuse_or_explain(_BrokenTable(), "c", "o", parts)
    assert out is None and since is None and fp == gc.brief_fingerprint(parts)
