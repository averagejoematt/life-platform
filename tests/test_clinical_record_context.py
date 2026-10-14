"""tests/test_clinical_record_context.py — the owner clinical record (ADR-155 amendment, 2026-10-12).

Covers the three parts of the machinery:
  * `health.clinical_facts` — the renderer: fail-soft, Decimal-safe, capped, guidance verbatim,
    and the non-disclosure notice on published surfaces;
  * `scripts/load_clinical_record.py` — the JSON-to-sort-key mapping and Decimal conversion;
  * the three wiring points (daily-brief coach inputs, Telegram domain facts, the expert
    analyzer's shared system prompt), plus the grounding allow-list the coach input feeds.

EVERY FIXTURE HERE IS A PLACEHOLDER. The real record lives outside this public repo and no
clinical value may ever be committed — "Example condition A", "Example med 10 mg" and
"example_marker" are the only vocabulary this file uses.
"""

from __future__ import annotations

import json
import os
import sys
from decimal import Decimal

import pytest

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")

_HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(REPO, "lambdas"))
sys.path.insert(0, os.path.join(REPO, "scripts"))

import load_clinical_record as loader  # noqa: E402
from health import clinical_facts as cf  # noqa: E402

PK = "USER#matthew#SOURCE#clinical"

RULES = [
    "Example rule one: keep sessions easy until the example review.",
    "Example rule two: stop and seek care if example symptom B appears.",
]
PUBLIC_RULES = ["Example public rule: prescribe intensity by effort, not numbers."]


def _rows(n_ecg: int = 3) -> list:
    rows = [
        {
            "pk": PK,
            "sk": "EVENT#2026-01-05#example-condition-a",
            "type": "diagnosis",
            "date": "2026-01-05",
            "title": "Example condition A",
            "status": "active",
            "presentation": "Example presentation text.",
        },
        {"pk": PK, "sk": "EVENT#2025-06-01#example-old", "date": "2025-06-01", "title": "Example resolved event", "status": "resolved"},
        {"pk": PK, "sk": "MED#example-med", "name": "Example med", "dose": "10 mg", "frequency": "daily", "status": "active"},
        {"pk": PK, "sk": "MED#example-paused", "name": "Example paused med", "status": "paused"},
        {"pk": PK, "sk": "MED#example-not-started", "name": "Example declined med", "status": "not started"},
        {
            "pk": PK,
            "sk": "LABS#2026-01-05",
            "collection_date": "2026-01-05",
            "biomarkers": {
                "example_marker": {"value": Decimal("7.25"), "unit": "u/L", "ref_text": "1-5", "flag": "high", "category": "x"},
                "example_normal": {"value": Decimal("42"), "unit": "mg", "ref_text": "10-50", "flag": "normal", "category": "x"},
            },
        },
        {"pk": PK, "sk": "HISTORY#2026-01-06", "example_field": "example answer"},
        {
            "pk": PK,
            "sk": "GUIDANCE#current",
            "effective": "2026-01-05",
            "review_after": "2026-02-01",
            "rules": list(RULES),
            "public_rules": list(PUBLIC_RULES),
        },
    ]
    for i in range(n_ecg):
        rows.append(
            {
                "pk": PK,
                "sk": f"ECG#2026-01-{i + 1:02d}T08:00:00#example-device",
                "recorded_at_local": f"2026-01-{i + 1:02d}T08:00:00",
                "device": "example-device",
                "verdict": "Example verdict",
                "avg_hr_bpm": Decimal(60 + i),
            }
        )
    return rows


class _Table:
    """A paginating fake: hands the rows back in pages of `page`."""

    def __init__(self, rows=None, page: int = 4, raises: Exception | None = None):
        self.rows = rows or []
        self.page = page
        self.raises = raises
        self.calls: list = []

    def query(self, **kwargs):
        self.calls.append(kwargs)
        if self.raises:
            raise self.raises
        start = int((kwargs.get("ExclusiveStartKey") or {}).get("i", 0))
        out = {"Items": self.rows[start : start + self.page]}
        if start + self.page < len(self.rows):
            out["LastEvaluatedKey"] = {"i": start + self.page}
        return out


# ── the renderer ─────────────────────────────────────────────────────────────


def test_the_block_renders_every_family_from_a_paginated_read():
    table = _Table(_rows())
    block = cf.clinical_context_block(table, published=False)
    assert len(table.calls) > 1, "the fixture must exercise pagination"
    assert all(c["ExpressionAttributeValues"][":pk"] == PK for c in table.calls), "the read is scoped to the clinical partition"
    assert block.startswith(cf.HEADER)
    assert "Example condition A" in block and "[active]" in block and "Example presentation text." in block
    assert "Example resolved event" not in block, "a resolved event is history, not a constraint"
    assert "Example med 10 mg daily [active]" in block
    assert "Example paused med [paused]" in block
    assert "Example declined med" not in block
    assert "example marker 7.25 u/L (HIGH; ref 1-5)" in block
    assert "1 of 2 markers out of range" in block
    assert "avg HR 62 bpm" in block  # Decimal rendered as a plain int
    assert "example_field" not in block and "example answer" not in block, "HISTORY# is stored, not rendered"


def test_guidance_is_rendered_verbatim_and_first():
    block = cf.clinical_context_block(_Table(_rows()), published=False)
    for rule in RULES:
        assert f"- {rule}" in block
    assert block.index(RULES[0]) < block.index("Example condition A"), "the clinicians' rules lead the block"
    assert "effective 2026-01-05, review after 2026-02-01" in block


def test_published_surfaces_get_the_guardrails_only():
    published = cf.clinical_context_block(_Table(_rows()))
    private = cf.clinical_context_block(_Table(_rows()), published=False)
    assert published.startswith(cf.PUBLIC_HEADER) and cf.PUBLISHED_NOTICE in published
    assert f"- {PUBLIC_RULES[0]}" in published
    for leaked in (cf.HEADER, "Example condition A", "Example med", "7.25", "example-device", RULES[0], RULES[1], "effective"):
        assert leaked not in published, f"a published prompt carried record detail: {leaked!r}"
    assert cf.PRIVATE_NOTICE in private and cf.PUBLISHED_NOTICE not in private


def test_published_without_public_rules_is_empty_fail_closed():
    rows = [r for r in _rows() if r["sk"] != "GUIDANCE#current"]
    rows.append({"pk": PK, "sk": "GUIDANCE#current", "rules": list(RULES)})
    assert cf.render_clinical_block(rows) == ""
    assert "Example condition A" in cf.render_clinical_block(rows, published=False)


def test_ecgs_are_newest_first_and_capped():
    block = cf.clinical_context_block(_Table(_rows(n_ecg=12), page=50), published=False)
    ecg_lines = [ln for ln in block.splitlines() if "example-device:" in ln]
    assert len(ecg_lines) == cf.MAX_ECG
    assert ecg_lines[0].startswith("- 2026-01-12 08:00"), ecg_lines[0]
    assert not any("2026-01-01 08:00" in ln for ln in ecg_lines), "the oldest recording is past the cap"


def test_an_empty_partition_is_an_empty_string():
    assert cf.clinical_context_block(_Table([])) == ""
    assert cf.clinical_context_block(None) == ""


def test_a_failed_read_is_an_empty_string_never_a_raise(caplog):
    with caplog.at_level("WARNING"):
        assert cf.clinical_context_block(_Table(raises=RuntimeError("throttled"))) == ""
    assert "clinical context unavailable" in caplog.text


def test_a_non_dict_response_is_an_empty_string():
    class _Weird:
        def query(self, **_kw):
            return "not a response"

    assert cf.clinical_context_block(_Weird()) == ""


def test_truncation_drops_oldest_ecgs_and_keeps_every_guidance_rule():
    rows = _rows(n_ecg=8)
    full = cf.render_clinical_block(rows, published=False, max_chars=100_000)
    cap = len(full) - 80
    cut = cf.render_clinical_block(_rows(n_ecg=8), published=False, max_chars=cap)
    assert len(cut) <= cap
    for rule in RULES:
        assert rule in cut
    assert "example normal" not in cut, "in-range lab values go first"
    assert "2026-01-08 08:00" in cut, "the newest recording survives"
    # Driven far below the guidance size, the block still never exceeds the cap.
    assert len(cf.render_clinical_block(_rows(), published=False, max_chars=200)) <= 200
    assert len(cf.render_clinical_block(_rows(), max_chars=60)) <= 60


# ── the loader ───────────────────────────────────────────────────────────────

FAKE_RECORD = {
    "schema": "example",
    "prepared": "2026-01-07",
    "events": [
        {"sk": "EVENT#2026-01-05#example-condition-a", "type": "diagnosis", "date": "2026-01-05", "title": "Example condition A"},
        {"type": "ecg_12lead", "date": "2026-01-05", "title": "Example ECG read", "source_file": "example_ecg.pdf"},
    ],
    "medications": [
        {"sk": "MED#example_med", "name": "Example med", "dose": "10 mg", "status": "active"},
        {"name": "Example Other Med", "status": "paused"},
    ],
    "labs_example_panel": {
        "collection_date": "2026-01-05",
        "biomarkers": {"example_marker": {"value": 7.25, "unit": "u/L", "ref_text": "1-5", "flag": "high", "category": "x"}},
    },
    "ecg_recordings": [
        {
            "recorded_at_local": "2026-01-04T21:10:05",
            "device": "Example Device",
            "verdict": "Example",
            "avg_hr_bpm": 61,
            "source_file": "rec1.pdf",
        }
    ],
    "patient_history_2026_01_06": {"example_field": "example answer", "nested": {"score": 1.5}},
    "coach_guidance": {"effective": "2026-01-05", "review_after": "2026-02-01", "rules": list(RULES)},
    "documents": [
        {"file": "example_ecg.pdf", "kind": "example"},
        {"file": "rec1.pdf", "kind": "example"},
        {"file": "unmatched.pdf", "kind": "example"},
    ],
}


def test_the_loader_maps_every_family_to_its_sort_key():
    items = loader.build_items(json.loads(json.dumps(FAKE_RECORD)), now="2026-01-07T00:00:00+00:00")
    assert [i["sk"] for i in items] == [
        "EVENT#2026-01-05#example-condition-a",
        "EVENT#2026-01-05#example-ecg-read",
        "MED#example_med",
        "MED#example-other-med",
        "ECG#2026-01-04T21:10:05#example-device",
        "LABS#2026-01-05",
        "HISTORY#2026-01-06",
        "GUIDANCE#current",
    ]
    for it in items:
        assert it["pk"] == PK and it["source"] == "clinical" and it["schema_version"] == 1
        assert it["updated_at"] == "2026-01-07T00:00:00+00:00"


def test_the_loader_converts_floats_to_decimal_recursively():
    items = {i["sk"]: i for i in loader.build_items(json.loads(json.dumps(FAKE_RECORD)))}
    assert items["LABS#2026-01-05"]["biomarkers"]["example_marker"]["value"] == Decimal("7.25")
    assert isinstance(items["LABS#2026-01-05"]["biomarkers"]["example_marker"]["value"], Decimal)
    assert items["HISTORY#2026-01-06"]["nested"]["score"] == Decimal("1.5")
    assert items["ECG#2026-01-04T21:10:05#example-device"]["avg_hr_bpm"] == 61

    def no_floats(v):
        if isinstance(v, float):
            return False
        if isinstance(v, dict):
            return all(no_floats(x) for x in v.values())
        if isinstance(v, list):
            return all(no_floats(x) for x in v)
        return True

    assert all(no_floats(i) for i in items.values())


def test_the_loader_plans_uploads_and_links_s3_keys_by_source_file(tmp_path):
    record = json.loads(json.dumps(FAKE_RECORD))
    items = loader.build_items(record)
    plan = loader.plan_uploads(record, items, str(tmp_path))
    keys = [k for _local, k, _m in plan]
    assert keys == [
        "raw/matthew/clinical/2026-01-05/example_ecg.pdf",  # dated by the matched EVENT
        "raw/matthew/clinical/2026-01-04/rec1.pdf",  # dated by the matched ECG
        "raw/matthew/clinical/2026-01-07/unmatched.pdf",  # no match: the file's `prepared` date
    ]
    by_sk = {i["sk"]: i for i in items}
    assert by_sk["EVENT#2026-01-05#example-ecg-read"]["s3_key"] == keys[0]
    assert by_sk["ECG#2026-01-04T21:10:05#example-device"]["s3_key"] == keys[1]


def test_every_document_gets_a_dynamodb_index_row(tmp_path):
    (tmp_path / "rec1.pdf").write_bytes(b"example bytes")
    record = json.loads(json.dumps(FAKE_RECORD))
    record["documents"].append({"file": "shot one.png", "kind": "example_screenshot", "date": "2026-01-03", "path": str(tmp_path)})
    items = loader.build_items(record)
    loader.plan_uploads(record, items, str(tmp_path))
    docs = {i["sk"]: i for i in items if i["sk"].startswith("DOC#")}
    assert sorted(docs) == [
        "DOC#2026-01-03#shot-one",  # its own `date` wins
        "DOC#2026-01-04#rec1",
        "DOC#2026-01-05#example-ecg",
        "DOC#2026-01-07#unmatched",
    ]
    rec = docs["DOC#2026-01-04#rec1"]
    assert rec["s3_key"] == "raw/matthew/clinical/2026-01-04/rec1.pdf" and rec["content_type"] == "application/pdf"
    assert rec["bytes"] == 13 and len(rec["sha256"]) == 64 and rec["pk"] == PK
    assert docs["DOC#2026-01-03#shot-one"]["content_type"] == "image/png" and "path" not in docs["DOC#2026-01-03#shot-one"]
    assert "sha256" not in docs["DOC#2026-01-07#unmatched"], "a missing file is indexed without a hash"


def test_the_dry_run_prints_keys_and_field_names_never_values(tmp_path, capsys):
    path = tmp_path / "record.json"
    path.write_text(json.dumps(FAKE_RECORD))
    assert loader.main([str(path), "--docs-dir", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "LABS#2026-01-05" in out and "biomarkers" in out and "DRY RUN" in out
    for value in ("Example condition A", "Example med", "7.25", "example answer", RULES[0], "u/L"):
        assert value not in out, f"the dry run leaked a value: {value!r}"


def test_the_loader_refuses_a_duplicate_sort_key():
    record = {"medications": [{"name": "Example med"}, {"name": "Example  med"}]}
    with pytest.raises(ValueError, match="duplicate sort key"):
        loader.build_items(record)


def test_the_loader_round_trips_into_the_renderer():
    items = loader.build_items(json.loads(json.dumps(FAKE_RECORD)))
    block = cf.render_clinical_block(items, published=False)
    assert "Example condition A" in block and "example marker 7.25" in block and RULES[1] in block


# ── wiring A: every daily-brief coach's input ────────────────────────────────


def test_every_daily_brief_coach_input_carries_the_clinical_lines(monkeypatch):
    from coach import coach_input_facts as ci

    seen = {}

    def fake_block(table, *, published=True, user_id="matthew"):
        seen["published"] = published
        return "CLINICAL CONTEXT\n- Example med 10 mg [active]\n- example marker 7.25"

    monkeypatch.setattr(ci._cf, "clinical_context_block", fake_block)
    ci._run.clear()
    try:
        data = {"date": "2026-01-06", "macrofactor_window": []}
        for coach in ("sleep_coach", "nutrition_coach", "mind_coach"):
            out = ci.coach_inputs(coach, {"hrv": 50}, data)
            assert out["clinical_context"] == ["CLINICAL CONTEXT", "- Example med 10 mg [active]", "- example marker 7.25"], coach
        assert seen["published"] is True, "coach reads can reach a public page — the block must be the non-disclosure form"
        # The input is what the grounding allow-list is derived from (ai_calls' user_message).
        from ai import grounded_generation as gg

        assert 7.25 in gg.allowed_numbers(json.dumps(out, default=str))
    finally:
        ci._run.clear()


def test_no_clinical_record_means_no_key_not_a_placeholder(monkeypatch):
    from coach import coach_input_facts as ci

    monkeypatch.setattr(ci._cf, "clinical_context_block", lambda table, **kw: "")
    ci._run.clear()
    try:
        out = ci.coach_inputs("sleep_coach", {"hrv": 50}, {"date": "2026-01-06", "macrofactor_window": []})
        assert "clinical_context" not in out
    finally:
        ci._run.clear()


# ── wiring B: the owner's Telegram coach thread ──────────────────────────────


def test_the_chat_domain_block_carries_the_private_form(monkeypatch):
    from coach import coach_domain_facts as cdf

    seen = {}

    def fake_block(table, *, published=True, user_id="matthew"):
        seen["published"] = published
        return "CLINICAL CONTEXT\n- Example med 10 mg [active]"

    monkeypatch.setattr(cf, "clinical_context_block", fake_block)
    block = cdf.domain_facts_block("sleep_coach", _Table([]), today="2026-01-06")
    assert "CLINICAL CONTEXT\n- Example med 10 mg [active]" in block
    assert seen["published"] is False, "domain_facts_block feeds only the owner's own Telegram thread"


# ── wiring C: the expert analyzer's shared system prompt ─────────────────────


def test_the_expert_shared_prompt_carries_the_published_form(monkeypatch):
    sys.path.insert(0, os.path.join(REPO, "lambdas", "intelligence"))
    import ai_expert_analyzer_lambda as az

    seen = {}

    def fake_block(table, *, published=True, user_id="matthew"):
        seen["published"] = published
        return "CLINICAL CONTEXT\n- example marker 7.25"

    monkeypatch.setattr(cf, "clinical_context_block", fake_block)
    monkeypatch.setattr(az, "_HAS_INTELLIGENCE_COMMON", False)
    monkeypatch.setattr(az, "_load_canonical_facts", lambda: {})
    monkeypatch.setattr(az, "_presence_block", lambda: "")
    prompt = az._build_shared_system_prompt()
    assert "CLINICAL CONTEXT\n- example marker 7.25" in prompt
    assert seen["published"] is True, "observatory analyses are published — the block must be the non-disclosure form"


def test_the_expert_shared_prompt_is_unchanged_without_a_record(monkeypatch):
    sys.path.insert(0, os.path.join(REPO, "lambdas", "intelligence"))
    import ai_expert_analyzer_lambda as az

    monkeypatch.setattr(cf, "clinical_context_block", lambda table, **kw: "")
    monkeypatch.setattr(az, "_HAS_INTELLIGENCE_COMMON", False)
    monkeypatch.setattr(az, "_load_canonical_facts", lambda: {})
    monkeypatch.setattr(az, "_presence_block", lambda: "")
    assert "CLINICAL CONTEXT" not in az._build_shared_system_prompt()


# ── registration ─────────────────────────────────────────────────────────────


def test_the_partition_is_registered_everywhere_before_its_first_row():
    from experiment import phase_taxonomy
    from ingestion import source_registry as reg
    from privacy import field_tiers

    assert field_tiers.source_tier_of("clinical") == field_tiers.TIER_INTERNAL
    assert not field_tiers.is_publishable(field_tiers.source_tier_of("clinical"))
    assert phase_taxonomy.SOURCE_CLASS["clinical"] == phase_taxonomy.CROSS_PHASE
    assert "clinical" in reg.EXTRA_QUERYABLE_PARTITIONS
    assert "raw/matthew/clinical" in reg.NON_INGESTION_RAW_PREFIXES
    assert loader.RAW_PREFIX == "raw/matthew/clinical" and loader.PK == PK


def test_the_census_disposition_follow_up_is_armed():
    """#3669: a live `SOURCE#` partition needs a registry entry, a platform-written class or a
    dated `UNREGISTERED_PARTITIONS` reason — and an exemption for a partition the census cannot
    see is itself a red. So the exemption lands with the first census that sees the partition
    (after the owner's first `--apply`), and this test says so on whichever side of that line
    the repo stands (the #4036 precedent)."""
    from ingestion import source_registry as reg

    with open(os.path.join(REPO, "deploy", "generated", "pk_family_census.json"), encoding="utf-8") as fh:
        census = json.load(fh)
    if "SOURCE#clinical" in census.get("families", {}):
        assert "clinical" in reg.UNREGISTERED_PARTITIONS, (
            "SOURCE#clinical is now live in the census: add the dated UNREGISTERED_PARTITIONS entry "
            "(owner-written via scripts/load_clinical_record.py; no lambda writes it; ADR-155 amendment)."
        )
    else:
        assert "clinical" not in reg.UNREGISTERED_PARTITIONS, "an exemption for a partition the census cannot see is fiction"


def test_the_analyzer_helper_is_fail_soft(monkeypatch):
    from intelligence import analyzer_grounding as ag

    def boom(table, **kw):
        raise RuntimeError("example failure")

    monkeypatch.setattr(cf, "clinical_context_block", boom)
    assert ag.clinical_parts(object()) == []
    monkeypatch.setattr(cf, "clinical_context_block", lambda table, **kw: "CLINICAL CONTEXT")
    assert ag.clinical_parts(object()) == ["CLINICAL CONTEXT"]
