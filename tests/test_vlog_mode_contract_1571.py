"""tests/test_vlog_mode_contract_1571.py — the /vlog mode's contract (#1571, epic #1564).

The mode itself is prose (`.claude/commands/vlog.md`), so nothing compiles it and
nothing caught it drifting from the code it drives. Three couplings in that prose
are load-bearing and silently breakable:

  AC3 — the Notion Template literal. `notion_lambda.TEMPLATE_SK` keys the
        `video_diary` channel off an EXACT string. If the mode file and the
        ingestion map ever disagree, the transcript still lands but as an
        untemplated `journal` entry: no `video_diary` channel, so no diary
        shelf, no coach reaction, no claims ledger. #1840 records that exact
        class of drift shipping inert for weeks.
  AC3 — the expanded date key. A plain `"Date"` silently writes no date and the
        entry misdates to created_time (CHAT_MODES.md §"The one gotcha").
  AC2 — abort semantics. A skipped session writes NOTHING and is never framed
        as a failure (ADR-104). This is a sentence in prose with no other guard.

Plus the parity contract in `scripts/check_vlog_prompt_parity.py`: every rule in
its checklist must still be anchored in vlog.md, so the checklist cannot rot into
describing a mode that changed underneath it.

This is a repo-shape ratchet (it reads the tree, not behaviour) — hence its
registration in `tests/conftest.py::_PREMERGE_EXTRA_FILES`.
"""

import importlib.util
import os
import re
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for p in (os.path.join(ROOT, "lambdas"), os.path.join(ROOT, "lambdas", "ingestion"), ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

MODE_PATH = os.path.join(ROOT, ".claude", "commands", "vlog.md")
CHAT_MODES_PATH = os.path.join(ROOT, "docs", "coaching", "CHAT_MODES.md")


def _load(relpath: str, name: str):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, relpath))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _flat(text: str) -> str:
    """Collapse whitespace so a prose assertion survives the file's line wrapping."""
    return re.sub(r"\s+", " ", text)


@pytest.fixture(scope="module")
def mode_text() -> str:
    with open(MODE_PATH, encoding="utf-8") as fh:
        return fh.read()


@pytest.fixture(scope="module")
def parity():
    return _load("scripts/check_vlog_prompt_parity.py", "_vlog_parity_1571")


# ── AC3: the mode's Notion write matches the ingestion path ───────────────────


def test_template_literal_matches_ingestion_map(mode_text):
    """The Template value the mode writes must be a real TEMPLATE_SK key.

    Derived from the code, never hand-typed here: renaming the key in
    notion_lambda without updating the mode file reds this test.
    """
    import notion_lambda as nl

    video_keys = [k for k, v in nl.TEMPLATE_SK.items() if v == "video_diary"]
    assert video_keys == ["Video Diary"], f"expected exactly one Video Diary template key, got {video_keys}"

    literal = video_keys[0]
    assert f'"Template": "{literal}"' in mode_text, f"vlog.md must write the exact TEMPLATE_SK key {literal!r} in its Notion close"
    assert literal in nl.MULTI_PER_DAY, "multiple diary sessions per day must stay legal"


def test_expanded_date_key_is_used_and_the_plain_form_is_not(mode_text):
    assert '"date:Date:start"' in mode_text, "the expanded date key is load-bearing (CHAT_MODES.md §'The one gotcha')"
    assert not re.search(r'"Date"\s*:\s*"', mode_text), 'a plain "Date" key silently writes no date property'


def test_channel_provenance_is_stamped_by_the_engine_not_the_mode(mode_text):
    """`channel: video_diary` is derived at ingest, so the mode must not hand-set it."""
    import notion_lambda as nl

    item = {"template": "Video Diary"}
    fallback = {"Video Diary": "video_diary", "Solo Recording": "solo_recording"}
    assert fallback.get(item["template"]) == "video_diary"
    assert nl.TEMPLATE_SK["Video Diary"] == "video_diary"
    assert "never hand-set it" in _flat(mode_text), "vlog.md must keep saying the channel stamp is the ingestion path's job"


def test_footage_is_a_pointer_never_content(mode_text):
    """A video diary is the most sensitive surface here: the entry holds a pointer only."""
    assert "Footage:" in mode_text
    assert "never in git while the repo is public" in _flat(mode_text), "the studio kit's private-S3 home must stay stated in the mode file"
    assert "s3://matthew-life-platform/config/studio/" in mode_text


# ── AC2: absence semantics ────────────────────────────────────────────────────


def test_aborted_session_writes_nothing_and_is_not_a_failure(mode_text):
    assert "Aborted/skipped session writes NOTHING" in mode_text
    assert "no stub page" in mode_text
    assert "never framed as a failure" in mode_text
    assert "ADR-104" in mode_text


# ── AC1: the format library, and the parity checklist that can't rot ──────────


def test_every_format_in_the_table_has_a_row(mode_text, parity):
    formats = parity.formats_in_mode(mode_text)
    assert set(formats) == {"daily", "weekly", "debrief", "retro", "team", "vent", "micro"}, formats


def test_arguments_line_offers_every_non_default_format(mode_text, parity):
    """`/vlog <format>` must accept what the table documents — derived, not hand-listed."""
    args_line = next(line for line in mode_text.splitlines() if line.startswith("Optional format pick:"))
    for fmt in parity.formats_in_mode(mode_text):
        if fmt == "micro":
            continue  # proposed by the day-number curve, not picked by hand
        assert f"`{fmt}`" in args_line, f"format {fmt!r} is in the table but not offered as an argument"


def test_parity_checklist_anchors_all_still_exist(mode_text, parity):
    """Each checklist rule must still be anchored in vlog.md.

    This is what stops `check_vlog_prompt_parity.py` from silently describing a
    mode that changed: reword a rule upstream and the anchor stops matching here
    before the checker starts reporting a phantom.
    """
    stale = [(rule, anchor) for rule, anchor, _kw, _why in parity.CHECKLIST if anchor not in mode_text]
    assert not stale, f"parity checklist anchors no longer in vlog.md: {stale}"


def test_parity_checker_detects_a_stripped_prompt(mode_text, parity):
    """Mutation-proof: the checker must actually fail on a condensation that lost rules."""
    good = mode_text  # the mode file trivially contains every rule and format
    assert parity.check(mode_text, good)["ok"] is True

    stripped = "let's do a vlog. ask me a question."
    report = parity.check(mode_text, stripped)
    assert report["ok"] is False
    assert report["rules_missing"], "a prompt with none of the rules must report missing rules"
    assert "micro" in report["formats_missing"]


# ── Registration: the mode is discoverable where the modes are listed ─────────


def test_mode_is_registered_in_chat_modes(mode_text):
    with open(CHAT_MODES_PATH, encoding="utf-8") as fh:
        doc = fh.read()
    assert ".claude/commands/vlog.md" in doc, "the mode must appear in the CHAT_MODES.md mode table"
    assert "manage_diary_claims" in doc, "the on-tape-claims row of the route-the-takeaways contract"


def test_chat_modes_heading_counts_the_modes_it_lists():
    """The section heading is a count, and counts drift as modes are added."""
    with open(CHAT_MODES_PATH, encoding="utf-8") as fh:
        doc = fh.read()
    listed = re.findall(r"`\.claude/commands/([a-z-]+)\.md`", doc.split("## The modes", 1)[1].split("\n\n", 2)[1])
    heading = re.search(r"^# The (\w+) chat modes", doc, re.MULTILINE)
    assert heading, "the chat-modes section heading is missing"
    words = {"four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9}
    assert words.get(heading.group(1)) == len(
        set(listed)
    ), f"heading says {heading.group(1)!r} but the table lists {len(set(listed))} modes: {sorted(set(listed))}"
