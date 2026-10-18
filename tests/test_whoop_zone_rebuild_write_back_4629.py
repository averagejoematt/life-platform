"""#4629 box 1 — the write-back mode of scripts/whoop_zone_rebuild_4629.py, on a stubbed table + archive (no AWS).

Pins: a differing row is updated with the recomputed Decimals; a null-score row's fabricated zeros are
REMOVED (never rewritten as 0); an unchanged row and a row with no archived record are never written;
dry-run and apply print the same plan hash; non-zone fields are untouched; mutation control below.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from decimal import Decimal

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))
for _k, _v in {"AWS_DEFAULT_REGION": "us-west-2", "TABLE_NAME": "life-platform", "S3_BUCKET": "b", "USER_ID": "matthew"}.items():
    os.environ.setdefault(_k, _v)

_spec = importlib.util.spec_from_file_location("whoop_zone_4629", os.path.join(ROOT, "scripts", "whoop_zone_rebuild_4629.py"))
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)

PK = "USER#matthew#SOURCE#whoop"
ZEROS = {f"zone_{i}_minutes": Decimal("0") for i in range(6)}
DAY = "2026-10-02"


def _payload(*records):
    return {"fetched_at": "x", "raw": {"workouts": {"records": list(records)}}}


def _durations(**ms):
    names = ["zero", "one", "two", "three", "four", "five"]
    return {"score": {"zone_durations": {f"zone_{n}_milli": ms.get(n, 0) for n in names}}}


ARCHIVE = {
    DAY: _payload(
        {"id": "diff", **_durations(two=600_000, three=90_000)},
        {"id": "nullscore", "score": None},
        {"id": "same", **_durations(one=60_000)},
    ),
    "2026-10-03": None,
}


def _stored():
    same = {f"zone_{i}_minutes": Decimal("1.0") if i == 1 else Decimal("0.0") for i in range(6)}
    return [
        {"pk": PK, "sk": f"DATE#{DAY}#WORKOUT#diff", "sport_name": "walking", **ZEROS},
        {"pk": PK, "sk": f"DATE#{DAY}#WORKOUT#nullscore", "sport_name": "x", **ZEROS},
        {"pk": PK, "sk": f"DATE#{DAY}#WORKOUT#same", **same},
        {"pk": PK, "sk": f"DATE#{DAY}#WORKOUT#ghost", **ZEROS},
        {"pk": PK, "sk": f"DATE#{DAY}", "strain": Decimal("9")},
    ]


class StubTable:
    def __init__(self, items):
        self.items = {i["sk"]: dict(i) for i in items}
        self.updates = []

    def query(self, **kw):
        return {"Items": [dict(v) for v in self.items.values()]}

    def update_item(self, Key, UpdateExpression, ConditionExpression, ExpressionAttributeValues=None):
        assert Key["pk"] == PK and ConditionExpression == "attribute_exists(sk)"
        self.updates.append(Key["sk"])
        it = self.items[Key["sk"]]
        values = ExpressionAttributeValues or {}
        assert all(isinstance(v, Decimal) for v in values.values())
        set_part, _, rem_part = UpdateExpression.partition("REMOVE")
        for clause in set_part.replace("SET", "").split(","):
            if clause.strip():
                k, v = (x.strip() for x in clause.split("="))
                it[k] = values[v]
        for k in (x.strip() for x in rem_part.split(",")):
            if k:
                it.pop(k, None)


class StubS3:
    class exceptions:
        class NoSuchKey(Exception):
            pass


def _run(monkeypatch, tmp_path, capsys, flag, archive=ARCHIVE):
    table = StubTable(_stored())
    monkeypatch.setattr(mod, "_read_archive", lambda s3, bucket, days: archive)
    report = tmp_path / "r.json"
    rc = mod.main(["--start", DAY, "--end", "2026-10-03", flag, "--report", str(report)], table=table, s3=StubS3())
    assert rc == 0
    return table, json.loads(report.read_text()), capsys.readouterr().out


def test_apply_updates_differing_and_removes_null_score_zeros(monkeypatch, tmp_path, capsys):
    table, rep, out = _run(monkeypatch, tmp_path, capsys, "--apply")
    assert (rep["rows_updated"], rep["rows_zeros_removed"], rep["rows_unchanged"], rep["rows_unresolved"]) == (1, 1, 1, 1)
    d = table.items[f"DATE#{DAY}#WORKOUT#diff"]
    assert d["zone_2_minutes"] == Decimal("10.0") and d["zone_3_minutes"] == Decimal("1.5") and d["sport_name"] == "walking"
    assert isinstance(d["zone_2_minutes"], Decimal)
    n = table.items[f"DATE#{DAY}#WORKOUT#nullscore"]
    assert not any(k in n for k in mod._ZONE_FIELDS) and n["sport_name"] == "x"
    assert sorted(table.updates) == sorted([f"DATE#{DAY}#WORKOUT#diff", f"DATE#{DAY}#WORKOUT#nullscore"])
    assert table.items[f"DATE#{DAY}#WORKOUT#ghost"] == _stored()[3]
    assert table.items[f"DATE#{DAY}"] == _stored()[4]


def test_dry_run_writes_nothing_and_hash_matches_apply(monkeypatch, tmp_path, capsys):
    table, dry, out = _run(monkeypatch, tmp_path, capsys, "--dry-run")
    assert table.updates == [] and dry["dry_run"] is True and "ZONES sk=" in out
    _, applied, _ = _run(monkeypatch, tmp_path, capsys, "--apply")
    assert dry["plan_sha256"] == applied["plan_sha256"] and len(dry["plan_sha256"]) == 64


def test_mutation_control_zero_instead_of_remove_is_caught(monkeypatch, tmp_path, capsys):
    """If the null-score row were rewritten to 0s instead of REMOVEd, the zone fields would exist: prove the pin sees it."""
    real = mod.zone_minutes_from_score
    monkeypatch.setattr(mod, "zone_minutes_from_score", lambda score: real(score) or {k: Decimal("0") for k in mod._ZONE_FIELDS})
    table, rep, _ = _run(monkeypatch, tmp_path, capsys, "--apply")
    n = table.items[f"DATE#{DAY}#WORKOUT#nullscore"]
    assert any(k in n for k in mod._ZONE_FIELDS)  # the mutated writer leaves zeros; the real test above asserts none


def test_counts_only_mode_unchanged(monkeypatch, capsys):
    monkeypatch.setattr(mod, "_read_archive", lambda s3, bucket, days: ARCHIVE)
    assert mod.main(["--start", DAY, "--end", "2026-10-03"], s3=StubS3()) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["write_mode"] == "none" and "plan_sha256" not in out and out["workout_records"] == 3
