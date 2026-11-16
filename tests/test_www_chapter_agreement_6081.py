"""#6081 — one number, one window and one publication date for a chapter on every page that names it.

`scripts/check_www_build.py::chapter_agreement` reads the built pages (the front page, /story/, each chapter page,
/story/so-far/, /story/moments/) and compares what each prints for a chapter against the chapter page. The fixture build
is graded by `check_www_build.py` itself (scan → chapter_agreement); this test is its planted-mismatch control: a clean
synthetic dist passes, and every inconsistency the 2026-11-15 audit found on the live site, planted back, is caught.
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))

from check_www_build import chapter_agreement  # noqa: E402

CHAPTER = (
    '<section data-chapter="week-12" data-status="published"><span data-ch-no>10</span><div><span>Week 10</span><span>·</span>'
    "<span data-ch-window>Days 60–66 · 4 to 10 November</span><span>·</span><span data-published>published 13 November 2026</span></div></section>"
)
HOME = (
    '<div class="ch-lead" data-chapter="week-12" data-status="published"><span data-ch-no>10</span>'
    "<span data-ch-window>Days 60–66 · 4–10 Nov</span><span data-published>Published 13 November 2026</span></div>"
    '<span data-next-chapter="11">Next chapter · 11</span><a href="/story/">All <span data-ch-count>7 chapters and a prologue</span> →</a>'
    "<p><span data-ch-count>Seven chapters and a prologue</span> so far</p>"
)
STORY = (
    '<p class="label">Story · <span data-ch-count>7 chapters and a prologue</span> published</p>'
    '<a href="/story/program-week-11/" data-chapter="program-week-11" data-status="pending"><span data-ch-no>11</span><span data-ch-window>program week 15–21 Nov</span></a>'
    '<a href="/story/week-12/" data-chapter="week-12" data-status="published"><span data-ch-no>10</span><span><b>The Rate Flag</b></span>'
    '<span class="ch-strip"><svg viewBox="0 0 2 2"><path d="M0 0"></path><line x1="0"/></svg></span>'
    "<span data-ch-window>Days 60–66 · 4–10 Nov</span><span>program week 8–14 Nov: 293.2 → 288.5 lb</span><span data-published>Published 13 November 2026</span></a>"
    '<div data-chapter="program-week-08" data-status="held"><span data-ch-no>08</span><span data-ch-window>program week 25–31 Oct</span></div>'
)
SO_FAR = (
    "<p><span data-ch-count>7 chapters and a prologue</span> on this timeline</p>"
    '<li data-chapter="week-12"><span data-ch-no>10</span><span class="label">Week 10 · program week 8 to 14 November 2026</span>'
    "<span><span data-ch-window>Days 60–66 · 4 to 10 November</span> · <span data-published>Published 13 November 2026</span> · read the chapter →</span></li>"
)
MOMENTS = (
    '<li data-chapter="week-12"><p class="label"><span data-ch-week>Week 10</span> · <span data-ch-window>Days 60–66 · 4 to 10 November</span> · '
    "<span data-published>Published 13 November 2026</span></p></li>"
)


def _dist(root, **over):
    pages = {
        "index.html": HOME,
        "story/index.html": STORY,
        "story/week-12/index.html": CHAPTER,
        "story/so-far/index.html": SO_FAR,
        "story/moments/index.html": MOMENTS,
    }
    pages.update({k.replace("__", "/"): v for k, v in over.items()})
    for rel, body in pages.items():
        if body is None:
            continue
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"<!doctype html><html><body>{body}</body></html>", encoding="utf-8")
    return str(root)


def test_chapter_agreement_passes_one_name_and_reds_every_planted_mismatch(tmp_path):
    clean = chapter_agreement(_dist(tmp_path / "clean"))
    assert clean == [], clean

    # each planted mismatch is one the live site carried on 2026-11-15 (the issue's items 1, 4, 5, 7, 8) or a mark gone
    planted = {
        # 4: so-far printed the DATA date as "Published"
        "so-far data date": (
            {"story__so-far__index.html": SO_FAR.replace("Published 13 November", "Published 10 November")},
            "story/so-far/index.html: week-12 published",
        ),
        # 1: so-far printed the program week where the chapter page prints the covered days
        "so-far program week": (
            {"story__so-far__index.html": SO_FAR.replace("Days 60–66 · 4 to 10 November", "8 to 14 November")},
            "story/so-far/index.html: week-12 ch-window",
        ),
        # 4: moments printed the last covered day in the publication slot
        "moments last day": (
            {"story__moments__index.html": MOMENTS.replace("Published 13 November 2026", "10 November 2026")},
            "story/moments/index.html: week-12 published",
        ),
        "story number": ({"story__index.html": STORY.replace("<span data-ch-no>10</span>", "<span data-ch-no>12</span>")}, "numbered '12'"),
        "moments week": ({"story__moments__index.html": MOMENTS.replace(">Week 10<", ">Week 9<")}, "numbered '09'"),
        "home window": ({"index.html": HOME.replace("4–10 Nov", "8–14 Nov")}, "index.html: week-12 ch-window"),
        # 5: the prologue counted as a chapter in one place and not in another
        "count": ({"index.html": HOME.replace("Seven chapters and a prologue", "Eight chapters")}, "counted 2 ways"),
        # 7: the next chapter numbered latest + 1 while /story/ lists another week unpublished
        "next chapter": ({"index.html": HOME.replace('data-next-chapter="11"', 'data-next-chapter="12"')}, "next chapter is numbered 12"),
        # 8: a held row linking to another chapter's address
        "held link": (
            {
                "story__index.html": STORY.replace(
                    '<div data-chapter="program-week-08" data-status="held">',
                    '<a href="/story/week-08/" data-chapter="program-week-08" data-status="held">',
                ).replace("25–31 Oct</span></div>", "25–31 Oct</span></a>")
            },
            "another chapter's address",
        ),
        "not on so-far": (
            {"story__so-far__index.html": "<p>timeline</p>"},
            "story/so-far/index.html: the published chapter week-12 is not named",
        ),
        "no marks": ({"story__index.html": "<p>chapters</p>"}, "names no chapter"),
        "page unmarked": ({"story__week-12__index.html": "<h1>The Rate Flag</h1>"}, "its page carries no chapter marks"),
    }
    missed = []
    for name, (over, expect) in planted.items():
        got = chapter_agreement(_dist(tmp_path / name.replace(" ", "-"), **over))
        if not any(expect in line for line in got):
            missed.append(f"{name}: expected {expect!r}, got {got}")
    assert not missed, "\n".join(missed)
