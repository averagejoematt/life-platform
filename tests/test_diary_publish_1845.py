"""
tests/test_diary_publish_1845.py — the cut→entry→engagement loop + the Goodhart
guardrail (#1845, diary-360 story 5).

What these pin, in the order the story's ACs run:

  AC1  the publish-log format carries entry provenance (session slug + cut id + surface +
       URL), and the studio's markdown row and the platform's record AGREE — proven by a
       parse↔format round-trip and by a validation gate that refuses a row whose own cut
       filename disagrees with its surface column
  AC2  YouTube engagement is joinable to source entries — a publication row is looked up
       by the one identity ingestion holds (channel, post_id) and stamped onto the
       inbound post as `diary_*` provenance; `engagement_by_entry` rolls it up per entry
  AC3  THE GOODHART RULE, structurally: engagement may inform which CUT gets published;
       it may never inform which QUESTIONS get asked. Enforced three ways here —
       fail-closed purpose gate, an import-graph audit (no MCP tool / coach module may
       reach this module at all), and the prose rule present in the canonical content doc
       and referenced from the /vlog skill.

Offline: no AWS, no network, no clock dependence.
"""

import os
import re
import sys

os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")

import pytest  # noqa: E402

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "lambdas"))
sys.path.insert(0, os.path.join(_ROOT, "lambdas", "ingestion"))
sys.path.insert(0, os.path.join(_ROOT, "scripts"))

import diary_publish as dp  # noqa: E402

NOW = "2026-07-27T18:00:00+00:00"
NOTION_URL = "https://www.notion.so/Video-Diary-retro-2026-07-26-1f2e3d4c5b6a7988990a1b2c3d4e5f60"

LOG = """# PUBLISH_LOG.md

Append-only. One line per post: date · session · cut · surface · link · entry.

| date | session | cut | surface | link | entry |
|---|---|---|---|---|---|
| 2026-07-27 | 2026-07-26_retro_day-zero | 2026-07-26_day00_cut01_reel_more-day-ones.mp4 | reel | https://www.youtube.com/shorts/ZZZZZZZZZZZ | {notion} |
| 2026-07-27 | 2026-07-26_retro_day-zero | 2026-07-26_day00_retro_day-zero__full.mp4 | yt | https://www.youtube.com/watch?v=YYYYYYYYYYY | — |
""".format(
    notion=NOTION_URL
)

# The pre-#1845 five-column log — the file as it exists in the studio today.
LEGACY_LOG = """| date | session | cut | surface | link |
|---|---|---|---|---|
| 2026-07-27 | 2026-07-26_retro_day-zero | 2026-07-26_day00_cut01_reel_more-day-ones.mp4 | reel | https://youtu.be/ZZZZZZZZZZZ |
"""


def _row(**over):
    row = {
        "published_date": "2026-07-27",
        "session_slug": "2026-07-26_retro_day-zero",
        "cut_file": "2026-07-26_day00_cut01_reel_more-day-ones.mp4",
        "surface": "reel",
        "url": "https://www.youtube.com/shorts/ZZZZZZZZZZZ",
        "entry_ref": NOTION_URL,
    }
    row.update(over)
    return row


def _admitted(**over):
    ok, reason, normalized = dp.admit_publication(_row(**over))
    assert ok, reason
    return normalized


# ══════════════════════════════════════════════════════════════════════════════
# AC1 — the log format carries provenance, and both sides agree
# ══════════════════════════════════════════════════════════════════════════════


class TestPublishLogFormat:
    def test_parses_the_six_column_log_into_provenance_fields(self):
        rows, problems = dp.parse_publish_log(LOG)
        assert problems == []
        assert len(rows) == 2
        first = rows[0]
        assert first["session_slug"] == "2026-07-26_retro_day-zero"
        assert first["cut_file"] == "2026-07-26_day00_cut01_reel_more-day-ones.mp4"
        assert first["surface"] == "reel"
        assert first["url"].endswith("ZZZZZZZZZZZ")
        assert first["entry_ref"] == NOTION_URL

    def test_legacy_five_column_log_still_parses_with_the_entry_simply_absent(self):
        """The studio's existing file must not become unreadable — the entry pointer is
        absent, not invented."""
        rows, problems = dp.parse_publish_log(LEGACY_LOG)
        assert problems == []
        assert len(rows) == 1
        assert rows[0]["cut_file"].startswith("2026-07-26_day00_cut01")
        assert rows[0].get("entry_ref") in (None, "")

    def test_parsing_is_header_driven_not_positional(self):
        """A reordered/extended studio table still reads correctly."""
        reordered = (
            "| cut | date | notes | surface | session | link |\n|---|---|---|---|---|---|\n"
            "| {cut} | 2026-07-27 | posted late | reel | {s} | {u} |\n".format(
                cut="2026-07-26_day00_cut01_reel_more-day-ones.mp4",
                s="2026-07-26_retro_day-zero",
                u="https://youtu.be/ZZZZZZZZZZZ",
            )
        )
        rows, problems = dp.parse_publish_log(reordered)
        assert problems == []
        assert rows[0]["surface"] == "reel"
        assert rows[0]["session_slug"] == "2026-07-26_retro_day-zero"

    def test_a_malformed_row_is_reported_not_silently_dropped(self):
        broken = LOG + "| 2026-07-28 | oops |\n"
        rows, problems = dp.parse_publish_log(broken)
        assert len(rows) == 2
        assert any("cells vs" in p for p in problems)

    def test_placeholder_cells_read_as_absent(self):
        rows, _ = dp.parse_publish_log(LOG)
        assert rows[1]["entry_ref"] == ""

    def test_linkified_cell_still_yields_a_usable_url(self):
        md = (
            "| date | session | cut | surface | link |\n|---|---|---|---|---|\n"
            "| 2026-07-27 | 2026-07-26_retro_day-zero | 2026-07-26_day00_cut01_reel_more-day-ones.mp4 | reel | [watch](https://youtu.be/ZZZZZZZZZZZ) |\n"
        )
        rows, _ = dp.parse_publish_log(md)
        assert rows[0]["url"] == "https://youtu.be/ZZZZZZZZZZZ"

    def test_round_trip_the_studio_row_and_the_platform_record_agree(self):
        """AC1, operationally: format(parse(x)) preserves every provenance field."""
        rows, _ = dp.parse_publish_log(LOG)
        for row in rows:
            normalized = dp.admit_publication(row)[2]
            emitted = dp.format_publish_log_row({**normalized, "entry_ref": row.get("entry_ref")})
            reparsed, problems = dp.parse_publish_log(dp.LOG_HEADER + "\n" + dp.LOG_DIVIDER + "\n" + emitted)
            assert problems == []
            again = dp.admit_publication(reparsed[0])[2]
            for field in ("published_date", "session_slug", "cut_id", "surface", "url", "entry_sk"):
                assert again[field] == normalized[field], field


class TestAdmissionGate:
    def test_a_conforming_row_is_admitted_with_the_full_provenance_chain(self):
        n = _admitted()
        assert n["cut_id"] == "2026-07-26_day00_cut01_reel_more-day-ones"
        assert n["cut_rank"] == 1
        assert n["cut_kind"] == "clip"
        assert n["day"] == 0
        assert n["entry_date"] == "2026-07-26"
        assert n["channel"] == "youtube"
        assert n["post_id"] == "ZZZZZZZZZZZ"

    def test_the_long_cut_is_admissible_and_marked_as_such(self):
        n = _admitted(cut_file="2026-07-26_day00_retro_day-zero__full.mp4", surface="yt")
        assert n["cut_kind"] == "full"
        assert n["cut_rank"] is None

    @pytest.mark.parametrize(
        "over,fragment",
        [
            ({"published_date": "27/07/2026"}, "YYYY-MM-DD"),
            ({"session_slug": ""}, "session is required"),
            ({"cut_file": ""}, "cut is required"),
            ({"surface": "tiktok"}, "surface"),
            ({"cut_file": "final_v3_REAL.mp4"}, "STUDIO.md"),
        ],
    )
    def test_refusals_name_the_cell_to_fix(self, over, fragment):
        ok, reason, normalized = dp.admit_publication(_row(**over))
        assert not ok and normalized is None
        assert fragment in reason

    def test_a_filename_that_disagrees_with_the_surface_column_is_refused(self):
        """The exact disagreement STUDIO.md §2b's naming rule exists to make impossible."""
        ok, reason, _ = dp.admit_publication(_row(surface="short"))
        assert not ok
        assert "surface" in reason and "wrong" in reason

    def test_a_cut_from_another_session_is_refused(self):
        ok, reason, _ = dp.admit_publication(_row(session_slug="2026-08-01_daily_something"))
        assert not ok
        assert "does not match session" in reason

    def test_a_missing_link_is_not_a_refusal_but_yields_no_joinable_row(self):
        n = _admitted(url="")
        assert n["post_id"] is None
        assert dp.build_publication_record(n, NOW) is None


class TestPublicationRecord:
    def test_record_shape_and_keys(self):
        rec = dp.build_publication_record(_admitted(), NOW)
        assert rec["pk"] == "DIARY_PUBLISH#youtube"
        assert rec["sk"] == "POST#ZZZZZZZZZZZ"
        assert rec["record_type"] == "diary_publication"
        assert rec["session_slug"] and rec["cut_id"] and rec["surface"] and rec["url"]
        assert rec["entry_sk"] == "DATE#2026-07-26#journal#video_diary#1b2c3d4e5f60"
        assert rec["entry_pk"] == "USER#matthew#SOURCE#notion"

    def test_entry_sk_matches_notion_lambdas_own_key_builder(self):
        """The pointer must be the entry's REAL sk — derived with notion_lambda's rule,
        not an approximation, or the join silently attaches to nothing."""
        import notion_lambda as nl

        page_id = "1f2e3d4c-5b6a-7988-990a-1b2c3d4e5f60"
        assert dp.entry_sk_from_notion(page_id, "2026-07-26") == nl.build_sk("2026-07-26", "Video Diary", page_id)

    def test_no_entry_reference_means_no_entry_sk_never_a_guess(self):
        n = _admitted(entry_ref="")
        assert n["entry_sk"] is None
        assert "entry_sk" not in dp.build_publication_record(n, NOW)

    def test_absent_values_are_omitted_not_nulled(self):
        rec = dp.build_publication_record(_admitted(cut_file="2026-07-26_day00_retro_day-zero__full.mp4", surface="yt"), NOW)
        assert "cut_rank" not in rec  # a long cut has no rank — absent, not 0 (ADR-104)
        assert all(v is not None for v in rec.values())

    def test_the_ledger_never_carries_tape_content(self):
        """Provenance is pointers. The words stay in Notion under their consent tier."""
        rec = dp.build_publication_record(_admitted(), NOW)
        assert not {"transcript", "quote", "description", "caption", "body"} & set(rec)

    def test_numbers_are_ints_not_floats(self):
        """boto3 rejects float; the only numerics here are counts."""
        rec = dp.build_publication_record(_admitted(), NOW)
        assert isinstance(rec["cut_rank"], int) and isinstance(rec["day"], int)
        assert not any(isinstance(v, float) for v in rec.values())


class TestPostRefParsing:
    @pytest.mark.parametrize(
        "url,post_id",
        [
            ("https://www.youtube.com/watch?v=ABC123xyz_-", "ABC123xyz_-"),
            ("https://youtu.be/ABC123xyz_-", "ABC123xyz_-"),
            ("https://www.youtube.com/shorts/ABC123xyz_-", "ABC123xyz_-"),
            ("https://www.youtube.com/watch?feature=share&v=ABC123xyz_-", "ABC123xyz_-"),
        ],
    )
    def test_youtube_urls_resolve_to_the_video_id(self, url, post_id):
        assert dp.parse_post_ref(url) == ("youtube", post_id)

    @pytest.mark.parametrize("url", ["", "https://www.instagram.com/reel/abc123/", "not a url"])
    def test_unrecognised_links_yield_no_key_rather_than_a_fabricated_one(self, url):
        assert dp.parse_post_ref(url) == (None, None)


# ══════════════════════════════════════════════════════════════════════════════
# AC2 — engagement joins back to the entry
# ══════════════════════════════════════════════════════════════════════════════


class _FakeTable:
    def __init__(self, items=None, raises=False):
        self.items = {(i["pk"], i["sk"]): i for i in (items or [])}
        self.raises = raises

    def get_item(self, Key=None, **_kw):  # noqa: N803 — boto3's parameter name
        if self.raises:
            raise RuntimeError("ddb down")
        item = self.items.get((Key["pk"], Key["sk"]))
        return {"Item": item} if item else {}


class TestTheJoin:
    def test_lookup_then_stamp_produces_the_diary_provenance_fields(self):
        rec = dp.build_publication_record(_admitted(), NOW)
        table = _FakeTable([rec])
        stamp = dp.publication_stamp(dp.lookup_publication(table, "youtube", "ZZZZZZZZZZZ"))
        assert stamp["diary_session_slug"] == "2026-07-26_retro_day-zero"
        assert stamp["diary_cut_id"] == "2026-07-26_day00_cut01_reel_more-day-ones"
        assert stamp["diary_surface"] == "reel"
        assert stamp["diary_entry_sk"].startswith("DATE#2026-07-26#journal#video_diary#")
        assert set(stamp) <= set(dp.STAMP_FIELDS)

    def test_an_unpublished_post_stamps_nothing(self):
        assert dp.publication_stamp(dp.lookup_publication(_FakeTable([]), "youtube", "NOPE")) == {}

    def test_lookup_fails_open(self):
        assert dp.lookup_publication(_FakeTable(raises=True), "youtube", "ZZZZZZZZZZZ") is None
        assert dp.lookup_publication(None, "youtube", "ZZZZZZZZZZZ") is None

    def test_youtube_ingestion_stamps_the_provenance_onto_the_inbound_record(self, monkeypatch):
        """The loop closed end to end, offline: a published cut's inbound post carries the
        session, the cut and the source entry."""
        import youtube_lambda as yt

        rec = dp.build_publication_record(_admitted(), NOW)
        table = _FakeTable([rec])
        raw = {
            "date": "2026-07-27",
            "channel_id": "UCtest",
            "entries": [
                {"video_id": "ZZZZZZZZZZZ", "title": "more day ones", "url": "https://youtu.be/ZZZZZZZZZZZ", "published": "", "views": 42},
                {"video_id": "QQQQQQQQQQQ", "title": "someone else's clip", "url": "https://youtu.be/QQQQQQQQQQQ", "published": ""},
            ],
        }
        # monkeypatch (not assignment): these are module globals another test module in
        # the same session imports — a permanent stub here reds a neighbouring suite.
        monkeypatch.setattr(yt, "_archive_post_raw", lambda entry, date_str: None)
        monkeypatch.setattr(yt, "_ledger_table", lambda: table)
        monkeypatch.setattr(yt, "_sensitivity_for", lambda entry: {})
        records = yt.transform(raw, "2026-07-27")

        published = [r for r in records if r["post_id"] == "ZZZZZZZZZZZ"][0]
        assert published["diary_session_slug"] == "2026-07-26_retro_day-zero"
        assert published["diary_cut_id"] == "2026-07-26_day00_cut01_reel_more-day-ones"
        assert published["diary_entry_sk"].startswith("DATE#2026-07-26#journal#video_diary#")
        assert published["views"] == 42  # the engagement now hangs off a diary entry

        other = [r for r in records if r["post_id"] == "QQQQQQQQQQQ"][0]
        assert not any(k.startswith("diary_") for k in other)

    def test_engagement_rolls_up_per_entry_with_n_and_honest_absence(self):
        pub_a = dp.build_publication_record(_admitted(), NOW)
        pub_b = dp.build_publication_record(
            _admitted(cut_file="2026-07-26_day00_cut02_short_the-wall.mp4", surface="short", url="https://youtu.be/WWWWWWWWWWW"),
            NOW,
        )
        posts = [
            {"channel": "youtube", "post_id": "ZZZZZZZZZZZ", "views": 1234},
            {"channel": "youtube", "post_id": "WWWWWWWWWWW"},  # the feed reported no statistics
            {"channel": "youtube", "post_id": "UNRELATED", "views": 99999},
        ]
        out = dp.engagement_by_entry([pub_a, pub_b], posts, purpose="cut_selection")
        assert out["n_entries"] == 1
        entry = out["entries"][0]
        assert entry["n_published"] == 2
        assert entry["n_measured"] == 1
        assert entry["views_total"] == 1234  # the unmeasured cut contributes nothing
        assert [c["views"] for c in entry["cuts"]] == [1234, None]  # absent, NOT zero
        assert "n=1 of 2" in entry["caveat"]
        assert "not comparable across surfaces" in entry["caveat"]

    def test_no_publications_means_no_entries_not_a_zero(self):
        out = dp.engagement_by_entry([], [{"channel": "youtube", "post_id": "X", "views": 5}], purpose="ops_report")
        assert out["entries"] == [] and out["n_entries"] == 0


# ══════════════════════════════════════════════════════════════════════════════
# AC3 — THE GOODHART GUARDRAIL (the point of the story)
# ══════════════════════════════════════════════════════════════════════════════


class TestGoodhartGuardrail:
    def test_the_allowed_and_forbidden_sets_are_disjoint_and_documented(self):
        assert not set(dp.ENGAGEMENT_MAY_INFORM) & set(dp.ENGAGEMENT_MUST_NEVER_INFORM)
        assert all(v.strip() for v in dp.ENGAGEMENT_MAY_INFORM.values())
        assert all(v.strip() for v in dp.ENGAGEMENT_MUST_NEVER_INFORM.values())
        # The two that matter most, named explicitly rather than implied.
        assert "cut_selection" in dp.ENGAGEMENT_MAY_INFORM
        assert {"question_selection", "interview_priming", "capture_protocol"} <= set(dp.ENGAGEMENT_MUST_NEVER_INFORM)

    @pytest.mark.parametrize("purpose", sorted(dp.ENGAGEMENT_MAY_INFORM))
    def test_output_side_purposes_are_allowed(self, purpose):
        assert dp.assert_engagement_purpose(purpose) == purpose

    @pytest.mark.parametrize("purpose", sorted(dp.ENGAGEMENT_MUST_NEVER_INFORM))
    def test_input_side_purposes_are_refused_with_the_reason(self, purpose):
        with pytest.raises(dp.GoodhartViolation) as excinfo:
            dp.assert_engagement_purpose(purpose)
        assert "may pick cuts" in str(excinfo.value)

    @pytest.mark.parametrize("purpose", ["", None, "analytics", "because I said so", "CUT SELECTION "])
    def test_unknown_purposes_fail_closed(self, purpose):
        """A new use must be argued for and added — never assumed benign. (The trailing
        variant proves normalization, so a legitimate purpose is not refused on spacing.)"""
        if str(purpose or "").strip().lower() in dp.ENGAGEMENT_MAY_INFORM:
            assert dp.assert_engagement_purpose(purpose)
            return
        with pytest.raises(dp.GoodhartViolation):
            dp.assert_engagement_purpose(purpose)

    def test_engagement_cannot_be_read_at_all_for_an_interview_purpose(self):
        pub = dp.build_publication_record(_admitted(), NOW)
        posts = [{"channel": "youtube", "post_id": "ZZZZZZZZZZZ", "views": 1234}]
        for purpose in dp.ENGAGEMENT_MUST_NEVER_INFORM:
            with pytest.raises(dp.GoodhartViolation):
                dp.engagement_by_entry([pub], posts, purpose=purpose)

    def test_there_is_no_unguarded_engagement_reader(self):
        """`purpose` is keyword-only and required — no positional slip, no default."""
        import inspect

        sig = inspect.signature(dp.engagement_by_entry)
        param = sig.parameters["purpose"]
        assert param.kind is inspect.Parameter.KEYWORD_ONLY
        assert param.default is inspect.Parameter.empty
        with pytest.raises(TypeError):
            dp.engagement_by_entry([], [])

    def test_no_interview_surface_can_reach_this_module(self):
        """The structural half of the rule: the interviewer's context comes from MCP tools
        and coach modules, so "engagement can never prime the interview" is enforceable by
        import graph. A future PR that wires one in fails HERE, in CI, rather than winning
        the argument quietly."""
        offenders = []
        for root in (os.path.join(_ROOT, "mcp"), os.path.join(_ROOT, "lambdas", "coach")):
            for dirpath, _dirs, files in os.walk(root):
                for name in files:
                    if not name.endswith(".py"):
                        continue
                    path = os.path.join(dirpath, name)
                    with open(path, encoding="utf-8") as fh:
                        src = fh.read()
                    if re.search(r"^\s*(from\s+diary_publish\s+import|import\s+diary_publish)", src, re.MULTILINE):
                        offenders.append(os.path.relpath(path, _ROOT))
        assert offenders == [], (
            f"{offenders} import diary_publish. Engagement data must never reach the interview or coach "
            "surfaces (#1845). If a genuinely output-side need exists, it belongs in the studio/publish "
            "path, not in a tool the interviewer can call."
        )

    def test_the_rule_is_written_down_in_the_canonical_content_doc(self):
        with open(os.path.join(_ROOT, "docs", "content", "DIARY_STUDIO_KIT.md"), encoding="utf-8") as fh:
            doc = fh.read()
        assert "## The Goodhart rule" in doc
        assert "MAY inform" in doc and "MUST NEVER" in doc
        # The explicit may/may-not lists the AC asks for, keyed to the code's own sets.
        for purpose in dp.ENGAGEMENT_MAY_INFORM:
            assert purpose in doc, f"{purpose} missing from the may-inform list"
        for purpose in dp.ENGAGEMENT_MUST_NEVER_INFORM:
            assert purpose in doc, f"{purpose} missing from the must-never list"

    def test_the_vlog_skill_references_the_rule(self):
        with open(os.path.join(_ROOT, ".claude", "commands", "vlog.md"), encoding="utf-8") as fh:
            skill = fh.read()
        assert "docs/content/DIARY_STUDIO_KIT.md" in skill
        assert "Goodhart" in skill
        assert "engagement-blind" in skill.lower()


# ══════════════════════════════════════════════════════════════════════════════
# Platform norms
# ══════════════════════════════════════════════════════════════════════════════


class TestPlatformNorms:
    def test_the_ledger_is_classified_system_state(self):
        """Publication is historical fact, not run intelligence — it survives a reset, and
        an unclassified pk family would block every future reset at the census preflight."""
        from experiment import phase_taxonomy as pt

        assert pt.classify("DIARY_PUBLISH#youtube", "POST#ZZZZZZZZZZZ") == pt.SYSTEM_STATE

    def test_the_ledger_is_a_separate_partition_from_the_broadcast_membrane(self):
        """A diary cut is Matthew on camera, published by hand — NOT a platform-authored
        syndication echo. Conflating the two would exclude his own voice from his own feed."""
        import social_provenance as prov

        assert dp.PUBLISH_PK_PREFIX != "BROADCAST_ORIGIN#"
        assert prov.broadcast_ledger_key("youtube", "Z")["pk"] != dp.publish_key("youtube", "Z")["pk"]
        assert prov.broadcast_ledger_key("youtube", "Z")["sk"] == dp.publish_key("youtube", "Z")["sk"]  # same join id

    def test_the_module_makes_no_ai_call_and_needs_no_budget_feature(self):
        """Pure by import graph: no AWS, no Bedrock, no budget_guard feature to register.
        Provenance and a join are arithmetic — an LLM has nothing to add and would only
        introduce a call this story does not need (ADR-103/105)."""
        import ast

        with open(os.path.join(_ROOT, "lambdas", "diary_publish.py"), encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        assert imported == {"re", "__future__"}, imported
        for forbidden in ("bedrock_client", "invoke_model", "ai_calls", "boto3", "budget_guard"):
            assert forbidden not in imported

    def test_the_sync_script_is_dry_run_by_default_and_needs_no_aws(self, tmp_path, capsys):
        import sync_diary_publications as sync

        log = tmp_path / "PUBLISH_LOG.md"
        log.write_text(LOG, encoding="utf-8")
        assert sync.main([str(log)]) == 0
        out = capsys.readouterr().out
        assert "DRY-RUN" in out
        assert "dry-run — pass --apply to write" in out

    def test_the_sync_script_reports_refusals_rather_than_dropping_them(self, tmp_path, capsys):
        import sync_diary_publications as sync

        log = tmp_path / "PUBLISH_LOG.md"
        log.write_text(LOG + "| 2026-07-27 | s | final_v3.mp4 | reel | https://youtu.be/AAAAAAAAAAA | — |\n", encoding="utf-8")
        assert sync.main([str(log)]) == 0
        assert "REFUSE" in capsys.readouterr().out

    def test_an_empty_log_is_a_normal_state(self, tmp_path, capsys):
        import sync_diary_publications as sync

        log = tmp_path / "PUBLISH_LOG.md"
        log.write_text("| date | session | cut | surface | link | entry |\n|---|---|---|---|---|---|\n", encoding="utf-8")
        assert sync.main([str(log)]) == 0
        assert "nothing has been posted yet" in capsys.readouterr().out
