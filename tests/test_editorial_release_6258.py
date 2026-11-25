"""test_editorial_release_6258.py — the editorial release (owner authorisation, review 14, 2026-11-24). Refs #6258.

What the owner authorised, held here:
  * "Park's Blind Spot, revisited" publishes exactly the approved text — ONE file bound to ONE SHA-256 (68406186…, with
    "Elena's bets. Elena lost her bet …" and Park's record named as "her coach page", owner decisions on PR #6263); the deploy-time check rebuilds the bytes from the built
    page with the Chronicle edition verifier's own pieces (scripts/www_editorial_checks.py, run by check_www_build.scan).
  * the homepage headline and first-person opening are his words, static, hashed — never a variable or a computation.
  * ONE RSS item for the feature (guid = its permanent address, pubDate = its actual first publication); every existing
    item byte-identical. No subscriber email: the feature is a committed file, and no sender reads it.
"""

# premerge-gate: walks lambdas/ for any reader of the editorial features (no subscriber sender may key on them)

import hashlib
import io
import json
import os
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "lambdas"))

import v4_build_rss  # noqa: E402
import www_editorial_checks as W  # noqa: E402

APPROVED_SHA256 = "68406186f91e76fe4b5faa08ed04ce584d20e7befc6ed13e4570a40ad717ed5b"
FEATURE_PATH = "/story/features/parks-blind-spot-revisited/"
HEADLINE = "I lost 115 pounds once. I regained it all, and more."
OPENING = (
    "I’m Matt. British, in Seattle. On 6 September 2026 I weighed 327.3 pounds and started again, by my own count "
    "‘the 15th or 16th reset in a few months’. This time a team of AI coaches is part of it. I can’t yet say whether the "
    "coaches are helping."
)


def _features():
    return json.loads((REPO / "www" / "src" / "features" / "features.json").read_text(encoding="utf-8"))["features"]


def test_the_feature_text_is_the_approved_bytes_and_one_pin_binds_it():
    (f,) = _features()
    raw = (REPO / "www" / "src" / "features" / f["text_file"]).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == APPROVED_SHA256
    assert f["sha256"] == APPROVED_SHA256
    assert not raw.endswith(b"\n"), "the approved bytes carry no trailing newline"
    text = raw.decode("utf-8")
    assert "- Elena's bets. Elena lost her bet that Thursday 1 October's recovery would come in below 60 (it read 62)" in text
    assert "My bets." not in text and "Matt's bets." not in text
    # owner decision 1A on PR #6263: the coach page is named in words and linked, never shown as its raw address
    assert "her record, on her coach page (direction calls" in text and "sleep_coach" not in text
    assert f["links"] == {"her coach page": "/system/coaches/sleep_coach/"}
    assert f["path"] == FEATURE_PATH and f["dated"] == "2026-11-24"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", f["first_published"])


def test_the_editorial_checks_catch_every_planted_failure():
    """The three build checks can fail: one changed character, a dropped block, a heading level, a renamed link, an added
    word, a wrong first-publication day; a straight apostrophe or markup in the owner's words; a disagreeing figure."""
    assert W.self_test() == []


def test_the_first_person_pins_are_the_authorised_words():
    assert W.FIRST_PERSON_SHA256["headline"] == hashlib.sha256(HEADLINE.encode("utf-8")).hexdigest()
    assert W.FIRST_PERSON_SHA256["opening"] == hashlib.sha256(OPENING.encode("utf-8")).hexdigest()
    page = (REPO / "www" / "src" / "pages" / "index.astro").read_text(encoding="utf-8")
    assert page.count(f'<p class="ed-opening" data-first-person>{OPENING}</p>') == 1, "the opening is static text in the page"
    assert page.count(f"<h1 data-first-person-headline>{HEADLINE}</h1>") == 1


def test_the_rebuild_uses_the_edition_verifiers_block_model():
    """The approved text's blocks, as content.chapter_editions models a published text, are exactly what the page
    rebuild yields from a faithful rendering — the verifier's comparison, not a second one."""
    from content import chapter_editions as CE

    (f,) = _features()
    text = (REPO / "www" / "src" / "features" / f["text_file"]).read_bytes().decode("utf-8")
    want = CE.prose_blocks(CE.render_html(text))
    assert len(want) == 54
    assert want[0] == "# Park's Blind Spot, revisited"


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()
        return False


def _feed(monkeypatch, tmp_path, name, with_features):
    posts = {
        "posts": [
            {"date": "2026-11-10", "title": "The Rate Flag", "url": "/journal/posts/week-12/", "excerpt": "One week."},
            {"date": "2026-10-06", "title": "Park's Blind Spot", "url": "/journal/posts/week-08/", "excerpt": "After 23 days."},
        ]
    }
    chapters = {"weeks": [{"url": "/journal/posts/week-12/", "published_at": "2026-11-13T18:00:00Z"}]}
    monkeypatch.setattr(
        v4_build_rss, "urlopen", lambda url, timeout=0: _Resp(json.dumps(chapters if "api/chapters" in url else posts).encode())
    )
    monkeypatch.setattr(v4_build_rss, "_freshness_check", lambda posts: None)
    monkeypatch.setattr(v4_build_rss, "_blog_posts", lambda: [])
    monkeypatch.setattr(v4_build_rss, "build_broadcast_feed", lambda: 0)
    monkeypatch.setattr(v4_build_rss, "build_wrong_feed", lambda: 0)
    if not with_features:
        monkeypatch.setattr(v4_build_rss, "_feature_posts", lambda: [])
    monkeypatch.setattr(v4_build_rss, "OUT", tmp_path / f"{name}.xml")
    monkeypatch.setattr(v4_build_rss, "OUT_ALIAS", tmp_path / f"{name}-alias.xml")
    assert v4_build_rss.main() == 0
    return (tmp_path / f"{name}.xml").read_text(encoding="utf-8")


def _items(xml):
    return re.findall(r"    <item>\n[\s\S]*?</item>", xml)


def test_the_feed_gains_exactly_one_item_and_no_existing_item_changes(monkeypatch, tmp_path):
    before = _items(_feed(monkeypatch, tmp_path, "before", False))
    monkeypatch.undo()
    after = _items(_feed(monkeypatch, tmp_path, "after", True))
    added = [i for i in after if i not in before]
    assert [i for i in before if i not in after] == [], "an existing item changed"
    assert len(added) == 1 and len(after) == len(before) + 1
    (f,) = _features()
    item = added[0]
    assert f'<guid isPermaLink="true">https://averagejoematt.com{FEATURE_PATH}</guid>' in item
    assert f"<pubDate>{v4_build_rss.rfc822(f['first_published'])}</pubDate>" in item
    assert "<title>Park&#x27;s Blind Spot, revisited</title>" in item or "<title>Park's Blind Spot, revisited</title>" in item


def test_a_feature_whose_text_does_not_match_its_pin_is_left_out_of_the_feed(monkeypatch, tmp_path):
    d = tmp_path / "features"
    d.mkdir()
    (d / "t.txt").write_text("# T\n\nA dateline\n\nA summary.\n\nBy someone.", encoding="utf-8")
    (d / "features.json").write_text(
        json.dumps(
            {
                "features": [
                    {"id": "t", "path": "/story/features/t/", "text_file": "t.txt", "sha256": "0" * 64, "first_published": "2026-11-25"}
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(v4_build_rss, "FEATURES_JSON", d / "features.json")
    assert v4_build_rss._feature_posts() == []


def test_no_subscriber_sender_reads_the_features():
    """The chronicle sender keys on SOURCE#chronicle rows (chronicle_email_sender_lambda); a feature is a committed file
    and the static build, and creates no row. Nothing under lambdas/ reads it, so publishing it sends no email."""
    hits = []
    for root, _dirs, files in os.walk(REPO / "lambdas"):
        for name in files:
            if name.endswith(".py"):
                text = Path(root, name).read_text(encoding="utf-8", errors="replace")
                if "story/features" in text or "features.json" in text:
                    hits.append(os.path.relpath(os.path.join(root, name), REPO))
    assert hits == []
    sender = (REPO / "lambdas" / "emails" / "chronicle_email_sender_lambda.py").read_text(encoding="utf-8")
    assert 'CHRONICLE_PK = f"USER#{USER_ID}#SOURCE#chronicle"' in sender


def test_a_built_dist_passes_the_editorial_checks():
    dist = REPO / "www" / "dist"
    if not (dist / "index.html").exists():
        pytest.skip("no built dist (the web gate builds one and runs the same checks through check_www_build.scan)")
    assert W.feature_fingerprint(str(dist)) == []
    assert W.first_person_pin(str(dist)) == []
    assert W.progress_agreement(str(dist)) == []
