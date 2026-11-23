"""#6244 — the Weekly Signal's two display defects, pinned on the real builder (owner ruling 2026-11-23, Priority 4).

  * "Level 22.0 · None": the level is a whole number and the tier is shown only when it is a real word.
  * The stale, cut chapter preview: the section follows the newest PUBLISHED week of ``/api/chapters`` (a held,
    retired, skipped or pending week serves ``url: null`` and is never chosen), is dated, and quotes that chapter's
    served edition summary in full (the site's one-summary rule) — never the old re-joined excerpt ("flag..").

Each rule has a NEGATIVE CONTROL built from the shape the email carried before (synthetic values in the inventory's
shape): the acceptance check must reject it. Fixtures are synthetic and wire-typed (Decimal where DynamoDB/JSON
round-trips give one).
"""

import html as _html
import importlib
import io
import json
import os
import re
import sys
from decimal import Decimal

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "compute"))

wsl = importlib.import_module("weekly_signal_lambda")

SITE = "https://averagejoematt.com"
_SUMMARY = (
    "Between two Monday weigh-ins the scale fell 5.2 pounds and the platform's rate flag was lit. "
    "He lifted the heaviest weight of the experiment and wrote one sentence that disagrees with the flag."
)


def _chapters_doc(**over) -> dict:
    """An /api/chapters document in the served shape: a published week, a retired and a held week after it (url
    null), a pending week, and the editions list."""
    doc = {
        "genesis": "2026-09-06",
        "as_of": "2026-11-23",
        "weeks": [
            {
                "week": 9,
                "status": "published",
                "date": "2026-11-03",
                "title": "Earlier Chapter",
                "url": "/journal/posts/week-11/",
                "label": "Week 9",
                "published_at": "2026-11-06T18:00:00+00:00",
            },
            {
                "week": 10,
                "status": "published",
                "date": "2026-11-10",
                "title": "The Rate Flag",
                "url": "/journal/posts/week-12/",
                "label": "Week 10",
                "published_at": "2026-11-14T00:24:35+00:00",
            },
            {
                "week": 11,
                "status": "retired",
                "date": None,
                "title": None,
                "url": None,
                "label": None,
                "drafted_at": "2026-11-18T16:05:10+00:00",
            },
            {
                "week": 12,
                "status": "held",
                "date": None,
                "title": None,
                "url": None,
                "label": None,
                "drafted_at": "2026-11-25T16:05:10+00:00",
            },
            {"week": 13, "status": "pending", "date": None, "title": None, "url": None, "label": None},
        ],
        "editions": [
            {"chapter_id": "week-12", "edition": 2, "title": "The Rate Flag", "summary": _SUMMARY},
            {
                "chapter_id": "week-11",
                "edition": 2,
                "title": "Earlier Chapter",
                "summary": "An earlier chapter's own summary, long enough.",
            },
        ],
    }
    doc.update(over)
    return doc


def _text(html: str) -> str:
    """The words a reader sees: no style/head blocks, no tags, entities decoded."""
    t = re.sub(r"<(style|head)\b.*?</\1>", " ", html, flags=re.S | re.I)
    return " ".join(_html.unescape(re.sub(r"<[^>]+>", " ", t)).split())


def _acceptance_problems(html: str) -> list:
    """Every way a rendered Weekly Signal fails the owner's bar for these two sections ([] = acceptable)."""
    text = _text(html)
    problems = []
    if re.search(r"\bNone\b|\bnull\b|\bnan\b", text, flags=re.I):
        problems.append("a null word reached the reader")
    if re.search(r"Level \d+\.\d", text):
        problems.append("a level with a decimal point")
    if re.search(r"[A-Za-z]\.\.(?!\.)", text):
        problems.append("a summary that ends in a cut")
    if "Chronicle Preview" in text:
        problems.append("the undated 'Chronicle Preview' section")
    if "The Latest Chapter" in text and not re.search(
        r"published (?:January|February|March|April|May|June|July|August|September|October|November|December) \d{1,2}, \d{4}", text
    ):
        problems.append("a chapter section with no publication date")
    if re.search(r"[{}\[\]]", text):
        problems.append("a machine structure")
    if "Unsubscribe" not in text:
        problems.append("no unsubscribe link")
    return problems


def _email(stats=None, chapter=None):
    return wsl._build_email(stats or {}, chapter, None, 10, f"{SITE}/privacy/#unsubscribe", "Week 10")[1]


# ── the level ────────────────────────────────────────────────────────────────────────────────────────────────────


def test_character_words_on_wire_values():
    cases = [
        ({"level": Decimal("22.0"), "tier": None}, "Level 22"),
        ({"level": Decimal("26"), "tier": "Momentum"}, "Level 26 · Momentum"),
        ({"level": 22.0, "tier": "None"}, "Level 22"),
        ({"level": "22", "tier": "  "}, "Level 22"),
        ({"level": Decimal("21.6"), "tier": "null"}, "Level 22"),
        ({"level": None, "tier": "Momentum"}, None),
        ({"level": "?", "tier": "Momentum"}, None),
        ({"level": Decimal("NaN"), "tier": "Momentum"}, None),
        ({"level": True, "tier": "Momentum"}, None),
        ({}, None),
        (None, None),
    ]
    for char, want in cases:
        assert wsl.character_words(char) == want, char


def test_numbers_section_renders_wire_stats_cleanly():
    stats = {
        "vitals": {
            "weight_lbs": Decimal("283.80000"),
            "weight_delta_7d": Decimal("-5.0"),
            "weight_delta_window_days": Decimal("7"),
            "sleep_hours_30d_avg": Decimal("7.7"),
            "sleep_hours_30d_n": Decimal("30"),
            "recovery_pct": Decimal("70"),
        },
        "character": {"level": Decimal("22.0"), "tier": None},
    }
    html = _email(stats)
    text = _text(html)
    assert "Level 22" in text and "283.8 lbs" in text and "(30n · 30d)" in text
    assert _acceptance_problems(html) == []


def test_a_level_that_is_not_a_number_drops_the_row():
    html = _email({"vitals": {}, "character": {"level": None, "tier": None}})
    assert "Character" not in html and "Level" not in html


# ── the chapter ──────────────────────────────────────────────────────────────────────────────────────────────────


def test_latest_published_chapter_follows_the_newest_published_week():
    ch = wsl.latest_published_chapter(_chapters_doc())
    assert ch == {
        "label": "Week 10",
        "title": "The Rate Flag",
        "url": "/story/week-12/",
        "published_on": "November 14, 2026",
        "summary": _SUMMARY,
    }


def test_a_held_retired_or_skipped_week_is_never_chosen():
    """Even a malformed served row: a non-published status never wins, whatever its week number or fields."""
    doc = _chapters_doc()
    doc["weeks"].append({"week": 14, "status": "retired", "title": "A Retired Draft", "url": "/journal/posts/week-16/", "label": "Week 14"})
    doc["weeks"].append({"week": 15, "status": "held", "title": "A Held Draft", "url": "/journal/posts/week-17/", "label": "Week 15"})
    doc["weeks"].append({"week": 16, "status": "skipped", "title": None, "url": None, "label": None})
    assert wsl.latest_published_chapter(doc)["title"] == "The Rate Flag"


def test_no_served_edition_means_no_summary_line():
    ch = wsl.latest_published_chapter(_chapters_doc(editions=[]))
    assert ch["summary"] is None and ch["title"] == "The Rate Flag"
    retitled = _chapters_doc(editions=[{"chapter_id": "week-12", "title": "Another Title", "summary": _SUMMARY}])
    assert wsl.latest_published_chapter(retitled)["summary"] is None  # an edition never retitles a chapter
    html = _email(chapter=ch)
    assert "The Rate Flag" in html and _acceptance_problems(html) == []


def test_no_published_week_or_no_document_omits_the_section():
    assert wsl.latest_published_chapter(None) is None
    assert wsl.latest_published_chapter({"weeks": [{"week": 3, "status": "pending", "url": None, "title": None}]}) is None
    assert "Latest Chapter" not in _email(chapter=None)


def test_rendered_chapter_section_passes_acceptance():
    html = _email(chapter=wsl.latest_published_chapter(_chapters_doc()))
    text = _text(html)
    assert "Week 10 · published November 14, 2026" in text
    assert _SUMMARY in text
    assert f'href="{SITE}/story/week-12/"' in html
    assert _acceptance_problems(html) == []


def test_negative_control_the_old_render_fails_acceptance():
    """The pre-#6244 sections, rebuilt from their own format strings: "Level {level} · {tier}" over the wire values,
    and the first manifest post's excerpt re-joined at ". " with a period appended (a summary ending in one reads "..")."""
    level, tier = Decimal("22.0"), None
    excerpt = _SUMMARY  # the manifest excerpt — the served summary, whole, ending in a period
    sentences = excerpt.split(". ")
    preview = ". ".join(sentences[:2]) + ("." if len(sentences) > 1 else "")
    old = (
        f"<p>Character</p><p>Level {level} · {tier}</p>"
        f"<p>Chronicle Preview</p><p>The Rate Flag</p><p>{preview}</p><a>Read more →</a><a>Unsubscribe</a>"
    )
    problems = " | ".join(_acceptance_problems(old))
    assert "null word" in problems
    assert "decimal point" in problems
    assert "Chronicle Preview" in problems
    assert "ends in a cut" in problems  # "...disagrees with the flag.."


def test_fetch_chapters_is_off_in_the_unit_suite_and_reads_the_public_route_when_on(monkeypatch):
    called = []
    monkeypatch.setattr(wsl.urllib.request, "urlopen", lambda *a, **k: called.append(a) or (_ for _ in ()).throw(AssertionError("off")))
    monkeypatch.setattr(wsl, "CHAPTERS_FETCH", "off")
    assert wsl._fetch_chapters() is None and called == []

    class _Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    seen = []

    def _open(req, timeout=None):
        seen.append((req.full_url, timeout))
        return _Resp(json.dumps(_chapters_doc()).encode())

    monkeypatch.setattr(wsl, "CHAPTERS_FETCH", "on")
    monkeypatch.setattr(wsl.urllib.request, "urlopen", _open)
    assert wsl._fetch_chapters()["weeks"][1]["title"] == "The Rate Flag"
    assert seen == [(f"{wsl.SITE_URL}/api/chapters", wsl.CHAPTERS_TIMEOUT_S)]

    monkeypatch.setattr(wsl.urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(OSError("down")))
    assert wsl._fetch_chapters() is None  # a failed read omits the section, never raises into the send
