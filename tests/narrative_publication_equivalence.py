#!/usr/bin/env python3
"""tests/narrative_publication_equivalence.py — the #5645 publication gate, held decision-for-decision and
byte-for-byte to its pre-speed-up self (``tests/narrative_publication_reference.py``) over a corpus.

    python3 tests/narrative_publication_equivalence.py                       # fixtures + synthetic adversarial rows
    python3 tests/narrative_publication_equivalence.py --rows-pickle PATH    # + a local, read-only dump of live rows
    python3 tests/narrative_publication_equivalence.py --mutate wordy5       # negative control: must report diffs

Every row passes, in order and twice over (the second pass is the memoised path), through the live gate and
the reference with the allowlist scope off and on: ``gate_item`` (lenient and strict), ``gate_document``,
the per-request counts, the container's taint sets (compared after every row), and — after each pass —
``is_tainted`` on every free-text string and clipped/masked/padded variants of it, and ``scrub_payload`` on
every raw and gated row. Outputs are compared as a type-tagged canonical form (a list is not a tuple, a
Decimal is not a float, dict key ORDER counts), exceptions by type and message. Prints one JSON document;
a diff names only its location (row index, pk, sk, check), never the text. Run in a fresh interpreter by
``tests/test_narrative_publication_gate_equivalence.py``: the fixture modules patch boto3 and the clock.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
from decimal import Decimal

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(ROOT, "lambdas"))
os.environ.setdefault("CONTENT_FILTER_JSON", json.dumps({"blocked_vices": ["No fizzlewick"], "blocked_vice_keywords": ["fizzlewick"]}))

from common import narrative_allowlist as NA  # noqa: E402
from narrative_publication_reference import Reference  # noqa: E402
from web import narrative_publication as G  # noqa: E402


# ── canonical form ───────────────────────────────────────────────────────────────────────────
def canon(x):
    if isinstance(x, dict):
        return ["dict", [[canon(k), canon(v)] for k, v in x.items()]]
    if isinstance(x, list):
        return ["list", [canon(v) for v in x]]
    if isinstance(x, tuple):
        return ["tuple", [canon(v) for v in x]]
    if isinstance(x, (set, frozenset)):
        return [type(x).__name__, sorted(json.dumps(canon(v)) for v in x)]
    return [type(x).__name__, repr(x)]


def _call(fn, *a, **k):
    try:
        return json.dumps(canon(fn(*a, **k)))
    except Exception as e:  # noqa: BLE001 — an exception is an outcome; both sides must raise the same one
        return json.dumps(["raised", type(e).__name__, str(e)])


# ── the corpus ───────────────────────────────────────────────────────────────────────────────
def fixture_rows() -> list:
    rows: list = []
    import narrative_publication_route_walk as nw

    for variant in ("private", "unrecorded", "public"):
        rows += nw._rows(variant)
    import call_publication_route_walk as cw

    rows += cw.public_rows() + cw.private_rows(3)
    import rhythm_route_walk as rw

    rows += [dict(r) for r in rw.FIXTURE_ROWS]
    return rows


SENTENCES = (
    "In this synthetic fixture the subject's writing stays dark, the notebook has gone quiet, and there were no entries this week.",
    "If the fixture subject's writing stays dark through Friday, the notebook has gone quiet for 12 days.",
    "Deep sleep rose above 1.5 hours on four nights while HRV held near 48 ms.",
    "the notebook has gone quiet for [n] days",
    "12 34 56 78 90 11 22",
    "a b c d e f g h i j",
    "one two",
    "three word line",
    "five short words in all",
    "exactly six words in this line",
    "seven words here make one full run",
    "Unicode — café naïve résumé déjà vu coöperate façade",
    "tabs\tand no-break spaces between the quiet notebook words today",
    "Weight 1,234.5 lbs then 1.234,5 kg then 12.5.6 and [n] [N] masked figures twice",
)
LONG = " ".join(
    random.Random(5728).choice(("quiet", "notebook", "writing", "dark", "the", "a", "12", "entries", "week", "sleep", "[n]"))
    for _ in range(500)
)

PROVENANCE_VARIANTS = (
    "absent",
    None,
    "journal",
    ["journal"],
    {"v": 1, "families": ["whoop", "withings"]},
    {"v": 1, "families": ["journal"]},
    {"v": 1, "families": ["whoop", "journal_presence"]},
    {"v": 1, "families": [" journal "]},
    {"v": 1, "families": ["JOURNAL"]},
    {"v": 1, "families": ("notion",)},
    {"v": 1, "families": {"clinical", "whoop"}},
    {"v": 1, "families": "journal"},
    {"v": 1, "families": [["journal"]]},
    {"v": 1, "families": [None, "whoop"]},
    {"v": 1, "families": ["", "whoop"]},
    {"v": 1, "families": []},
    {"v": 1, "families": [1]},
    {"v": 1, "families": ["unrecorded"]},
    {"v": 1, "families": ["no_such_family"]},
    {"v": 1},
    {"families": ["whoop"]},
    {"v": "1", "families": ["whoop"]},
    {"v": 1.0, "families": ["whoop"]},
    {"v": Decimal("1"), "families": ["whoop", "persona"]},
    {"v": Decimal("1.5"), "families": ["whoop"]},
    {"v": True, "families": ["whoop"]},
    {"v": 2, "families": ["whoop"]},
    {"v": None, "families": ["whoop"]},
    {"v": "x", "families": ["whoop"]},
    {"v": 1, "families": ["whoop"], "nested": {"families": ["journal"]}},
)
KEYS = (
    ("COACH#mind_coach", "PREDICTION#2026-11-02#p1"),
    ("COACH#sleep_coach", "COMMITMENT#2026-11-02#c1"),
    ("COACH#sleep_coach", "LEARNING#2026-11-02#l1"),
    ("COACH#sleep_coach", "CALIB#2026-11-02"),
    ("ENSEMBLE#docket", "OPEN#bet-1"),
    ("ENSEMBLE#docket", "RESOLVED#bet-1"),
    ("COACH#mind_coach", "OUTPUT#2026-11-02#daily"),
    ("COACH#mind_coach", "CORRECTION#2026-11-02#x"),
    ("PERSONA#elena", "STANCE#latest"),
    ("USER#matthew#SOURCE#insights", "DATE#2026-11-02"),
    ("USER#matthew#SOURCE#ai_analysis", "EXPERT#integrator"),
    ("USER#matthew", "SOURCE#coach_thread#mind#2026-11-02"),
    ("USER#matthew", "PROFILE#v1"),
    ("USER#matthew#SOURCE#whoop", "DATE#2026-11-02"),
    ("COACH#mind_coach", None),
    ("COACH#mind_coach", ""),
)


def _payload(rng: random.Random, i: int) -> dict:
    s = lambda: rng.choice(SENTENCES + (LONG,))  # noqa: E731
    shapes = (
        {"claim_natural": s(), "status": "refuted", "confidence": Decimal("0.6"), "metric": "hrv"},
        {"text": s(), "lines": [{"coach_id": "sleep_coach", "move": "reply", "text": s()}], "silent": ["mind_coach", "sleep_coach"]},
        {"summary": s(), "themes": ["sleep", "notebook"], "tags": {"quiet", "dark"}, "coach_ids": ("a_coach", "b_coach")},
        {
            "deep": {"a": [{"b": ({"c": s()},)}], "evaluation": {"method": s()}, "baseline": s()},
            "evaluation": {"note": s()},
            "baseline": [s()],
            "explanation": s(),
            "method": s(),
            "quality_flags": [s()],
        },
        {"label": "notebook", "topic": "quiet", "state": "dark days", "created_at": "2026-11-02T12:00:00+00:00", "n": 3, "ok": True},
        {
            1: s(),
            "none": None,
            "raw": b"bytes value",
            "f": 1.5,
            "dec": Decimal("12.50"),
            "empty": "",
            "ws": " ",
            "mixed": [s(), 3, None, [s()]],
        },
        {"provenance_note": s(), "families": ["journal"], "v": 1},  # a row that IS its own record (no provenance key)
        {"what_i_learned": s(), "open_questions": [s(), s()], "focused_on_now": ["one", "two words"], "replies_to": None},
    )
    return dict(shapes[i % len(shapes)])


def synthetic_rows() -> list:
    rng = random.Random(5728)
    rows: list = []
    i = 0
    for prov in PROVENANCE_VARIANTS:
        for pk, sk in KEYS:
            for _ in range(2):
                row = {"pk": pk}
                if sk is not None:
                    row["sk"] = sk
                row.update(_payload(rng, i))
                if prov != "absent":
                    row["provenance"] = prov
                rows.append(row)
                i += 1
    # odd envelopes: no pk (the hint decides), a non-str pk, non-dict items, an approved-key row whose words differ
    for pk, sk in KEYS[:6]:
        rows.append({"sk": sk or "", "claim_natural": SENTENCES[1], "_hint": pk})
    rows += [{"pk": 7, "sk": "PREDICTION#x", "text": SENTENCES[0]}, ["not", "a", "dict"], "a string item", None, 12]
    for (pk, sk), entry in list(NA.INDEX.items())[:4]:
        rows.append({"pk": pk, "sk": sk, entry.field: SENTENCES[0], "cited": []})
    # the same words under a skipped key in one row and a tainted key in the next (the memo is per text, not per key)
    rows.append({"pk": "COACH#mind_coach", "sk": "PREDICTION#2026-11-03#p2", "baseline": SENTENCES[2]})
    rows.append({"pk": "COACH#mind_coach", "sk": "PREDICTION#2026-11-03#p3", "claim_natural": SENTENCES[2]})
    return rows


# ── the walk ─────────────────────────────────────────────────────────────────────────────────
def _probes(text: str) -> list:
    words = text.split()
    return [
        text,
        text[:40],
        text[: len(text) // 2],
        " ".join(words[-6:]),
        "She said: " + text + " (later)",
        "".join("[n]" if c.isdigit() else c for c in text),
        text.upper(),
    ]


def _prose(rows: list) -> list:
    ref = Reference()
    seen, out = set(), []
    for r in rows:
        if isinstance(r, dict):
            for t in ref._prose_strings({k: v for k, v in r.items()}):
                if t not in seen:
                    seen.add(t)
                    out.append(t)
    return out


class _Diffs:
    def __init__(self) -> None:
        self.n = 0
        self.first: list = []

    def check(self, a: str, b: str, where: dict) -> None:
        if a != b:
            self.n += 1
            if len(self.first) < 20:
                self.first.append(where)


def _where(i, row, check, mode):
    if isinstance(row, dict):
        return {"i": i, "pk": str(row.get("pk"))[:60], "sk": str(row.get("sk"))[:60], "check": check, "mode": mode}
    return {"i": i, "check": check, "mode": mode}


def walk(rows: list, *, passes: int = 2, taint_every: int = 1) -> dict:
    diffs = _Diffs()
    calls = probes_n = 0
    prose = _prose(rows)
    probes = [p for t in prose for p in _probes(t)]
    saved_switch = NA.CR2_PUBLIC
    try:
        for mode in ("scope_off", "scope_on"):
            # Mode 1 resets through the API; mode 2 clears the sets directly, as any caller holding them could —
            # the memo must follow either way.
            if mode == "scope_off":
                G.reset_taint()
            else:
                G._TAINT_EXACT.clear()
                G._TAINT_SHINGLES.clear()
            NA.CR2_PUBLIC = mode == "scope_on"
            ref = Reference()
            G.begin_request()
            with NA.serving(NA.SCOPE_CR2 if mode == "scope_on" else "none"):
                for p in range(passes):
                    for i, row in enumerate(rows):
                        hint = row.get("_hint") if isinstance(row, dict) else None
                        item = {k: v for k, v in row.items() if k != "_hint"} if isinstance(row, dict) else row
                        for strict in (False, True):
                            diffs.check(
                                _call(G.gate_item, item, hint, strict=strict),
                                _call(ref.gate_item, item, hint, strict=strict),
                                _where(i, row, f"gate_item strict={strict} pass={p}", mode),
                            )
                            calls += 1
                        diffs.check(
                            _call(G.gate_document, item), _call(ref.gate_document, item), _where(i, row, f"gate_document pass={p}", mode)
                        )
                        calls += 1
                        diffs.check(json.dumps(G._STATE), json.dumps(ref.state), _where(i, row, f"counts pass={p}", mode))
                        if i % taint_every == 0 or i == len(rows) - 1:
                            same = G._TAINT_EXACT == ref.taint_exact and G._TAINT_SHINGLES == ref.taint_shingles
                            diffs.check(str(same), "True", _where(i, row, f"taint sets pass={p}", mode))
                    for j, t in enumerate(probes):
                        diffs.check(
                            str(G.is_tainted(t)), str(ref.is_tainted(t)), {"probe": j, "check": f"is_tainted pass={p}", "mode": mode}
                        )
                        probes_n += 1
                    shaper = Reference()  # builds the gated shapes to scrub without touching either side's counts
                    for i, row in enumerate(rows):
                        item = {k: v for k, v in row.items() if k != "_hint"} if isinstance(row, dict) else row
                        for label, node in (("raw", item), ("gated", shaper.gate_item(item, strict=True))):
                            if isinstance(node, (dict, list, str)):
                                diffs.check(
                                    _call(G.scrub_payload, node),
                                    _call(ref.scrub_payload, node),
                                    _where(i, row, f"scrub {label} pass={p}", mode),
                                )
                    diffs.check(json.dumps(G._STATE), json.dumps(ref.state), {"check": f"counts after scrub pass={p}", "mode": mode})
    finally:
        NA.CR2_PUBLIC = saved_switch
    return {
        "rows": len(rows),
        "gate_calls": calls,
        "probes": probes_n,
        "taint_exact": len(G._TAINT_EXACT),
        "taint_shingles": len(G._TAINT_SHINGLES),
        "diffs": diffs.n,
        "first_diffs": diffs.first,
    }


def _mutate(name: str) -> None:
    """Negative controls: each is a plausible wrong speed-up; the walk must catch every one."""
    if name == "wordy5":  # a stricter "worth matching" threshold — fewer shingles, a weaker wire half
        real = G._taint_text

        def _taint_text(text):
            words = G._norm_words(text)
            if len(words) >= G.EXACT_MIN_WORDS:
                G._TAINT_EXACT.add(hash(words))
            for i in range(len(words) - G.SHINGLE + 1):
                gram = words[i : i + G.SHINGLE]
                if sum(1 for w in gram if len(w) >= 3 and not w.isdigit()) >= 5:
                    G._TAINT_SHINGLES.add(hash(gram))

        assert real is not None
        G._taint_text = _taint_text
    elif name == "stale_memo":  # a memo that outlives a cleared taint set
        G._TAINT_SEEN = type("_Sticky", (set,), {"clear": lambda self: None})()
    elif name == "no_mask":  # "[n]" no longer normalised like a figure
        G._MASKED_FIGURE = __import__("re").compile(r"(?!x)x")
    else:
        raise SystemExit(f"unknown mutation {name}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows-pickle", help="a local, read-only dump of live rows (never committed)")
    ap.add_argument("--no-fixtures", action="store_true")
    ap.add_argument("--mutate")
    ap.add_argument("--taint-every", type=int, default=1)
    args = ap.parse_args()
    if args.mutate:
        _mutate(args.mutate)
    rows: list = []
    sizes = {}
    if not args.no_fixtures:
        f, s = fixture_rows(), synthetic_rows()
        sizes.update(fixture_rows=len(f), synthetic_rows=len(s))
        rows += f + s
    if args.rows_pickle:
        import pickle

        with open(args.rows_pickle, "rb") as fh:
            live = pickle.load(fh)  # noqa: S301 — the operator's own dump, read locally
        sizes["live_rows"] = len(live)
        rows += live
    out = walk(rows, taint_every=args.taint_every)
    out.update(sizes)
    print(json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    main()
