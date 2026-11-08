#!/usr/bin/env python3
"""scripts/publish_snapshot_coach_room.py — the Coaching Room's coach-profile data file (CR2), written ONLY for a dark build.

The owner's ruling of 2026-11-08 holds the Coaching Room NO-GO for publication; private implementation is allowed. So,
like CR1's calibration.json (scripts/publish_snapshot_calibration.py), this file exists only when ``WEB_ROOM=1``: with
the switch off the producer neither fetches it nor writes it, and the snapshot is byte-identical. The deploy workflow
never sets the switch.

What it carries — public Site API responses only, as served (already gated server-side by the narrative-publication
chokepoint, the claim-sourcing scrub and the dossier privacy filter), never recomputed:
  * ``/api/coach/<persona_id>`` for each public Coach object in the snapshot — the stance and its dated history, the
    latest read (the lead's daily read with its cited figures; a staff coach's newest output row), the dossier's asks
    (commitments) with the producer's own ``commitment_counts``, the dossier's open docket positions, the authored
    voice (tone, style, decision style, uncertainty style) and the coach's ``report_card`` record line;
  * ``/api/coach_docket`` — each standing disagreement's structure (sides, criterion, dates, stakes, verdict), filed
    under both coaches; and (CR3) once more as ``docket_entries``, each under a room id built from its open day and
    its two seats, with the API's own tally, disclosure and withheld messages (``unsourced`` / ``absent`` /
    ``concession_unsourced``);
  * ``/api/voice_fidelity`` — the self-measured blind voice test, platform line and per-coach line.

What it never carries, by design:
  * any id that spells out words the API withheld (a ``record_id`` / ``prediction_id`` slug is built from the text:
    ``COMMITMENT#commit_20261102_restore_protein_…``) — ids are dropped, never carried;
  * the voice spec's ``few_shot_example`` and its pattern lists (an authored sample read, not this coach's record —
    and the Mind coach's speaks of the journal);
  * the relationship / conversation counters, learnings, memoir and trait scores (not part of CR2's brief);
  * any string that names a private family (``PRIVATE_FAMILY``: the journal, State of Mind, the video diary) — a
    belt behind the server's gates: a hit empties the string (a text) or drops the element (a list item / a check).

"What Matt did" is NOT here: an advice link (``coach/advice_links.py``) is owner-asserted, evidence-only and served by
no public route, so every ask reads "not recorded" on the page; nothing is inferred from timing or correlation.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Callable, Iterable

COACH_PATH = "/api/coach/{}"
DOCKET_PATH = "/api/coach_docket"
FIDELITY_PATH = "/api/voice_fidelity"

ABSENT_COACH_ROOM = {
    "state": "absent",
    "absent_text": "The platform did not serve the coach profiles for this snapshot.",
    "source": [COACH_PATH.format("<id>"), DOCKET_PATH, FIDELITY_PATH],
    "fetched_at": None,
    "coaches": {},
    "voice_fidelity": None,
}

#: A private family named in a carried string (owner ruling 2026-11-03: journal activity, State of Mind and the video
#: diary are private on every public surface, including by inference). Fail-closed belt behind the server's gates.
PRIVATE_FAMILY = re.compile(
    r"journal|diar(?:y|ies)|state[\s_-]*of[\s_-]*mind|\bsom_|\bmood\b|video|vlog",
    re.IGNORECASE,
)

COUNT_KEYS = ("held", "kept", "broken", "pending", "unresolved", "ungradeable")


def _private(v: Any) -> bool:
    return isinstance(v, str) and bool(PRIVATE_FAMILY.search(v))


def _text(v: Any) -> str:
    """A served string, or "" — "" when absent, not a string, or naming a private family."""
    return v if isinstance(v, str) and not _private(v) else ""


def _texts(vs: Any) -> list[str]:
    return [t for t in (_text(v) for v in (vs or []) if isinstance(v, str)) if t]


def _day(v: Any) -> str | None:
    s = str(v or "")
    return s[:10] if re.match(r"^\d{4}-\d{2}-\d{2}", s) else None


def _instant(v: Any) -> str | None:
    s = str(v or "")
    return s if re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", s) else None


def _num(v: Any) -> float | int | None:
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _withheld(row: Any) -> str | None:
    """The API's OWN words for a withheld row — the narrative gate's `_publication.reason` or the claim-sourcing
    `unsourced.text` — when the row carries them; None otherwise (owner ruling 2026-11-06: most rows carry no marker)."""
    if not isinstance(row, dict):
        return None
    pub = row.get("_publication")
    if isinstance(pub, dict) and pub.get("state") == "withheld" and isinstance(pub.get("reason"), str):
        return pub["reason"]
    uns = row.get("unsourced")
    if isinstance(uns, dict) and isinstance(uns.get("text"), str) and uns["text"].strip():
        return _text(uns["text"]) or None
    return None


def _correction_note(n: Any) -> dict | None:
    """One served grade-correction note (``authoritative_grades.correction_note``), id dropped."""
    if not isinstance(n, dict):
        return None
    return {
        "original_status": n.get("original_status") if isinstance(n.get("original_status"), str) else None,
        "corrected_status": n.get("corrected_status") if isinstance(n.get("corrected_status"), str) else None,
        "corrected_at": _instant(n.get("corrected_at")),
        "explanation": _text(n.get("explanation")) or None,
    }


def _stance(s: Any) -> dict | None:
    if not isinstance(s, dict) or not s:
        return None
    stage = s.get("stage") if isinstance(s.get("stage"), dict) else {}
    rung = s.get("rung") if isinstance(s.get("rung"), dict) else {}
    return {
        "source": s.get("source") if isinstance(s.get("source"), str) else None,
        "as_of": _day(s.get("as_of")),
        "headline_read": _text(s.get("headline_read")),
        "how_my_read_changed": _text(s.get("how_my_read_changed")),
        "stage_label": _text(stage.get("label")),
        "stage_rationale": _text(stage.get("rationale")),
        "focused_on_now": _texts(s.get("focused_on_now")),
        "set_aside_for_now": _texts(s.get("set_aside_for_now")),
        "graduation_gate": _text(s.get("graduation_gate")),
        "summary_state": s.get("summary_state") if isinstance(s.get("summary_state"), str) else None,
        "summary_as_of": _instant(s.get("summary_as_of")),
        "summary_corrections": [c for c in (_correction_note(n) for n in s.get("summary_corrections") or []) if c],
        # the authored stage plan for the coach's current rung (config, not a read) and the ladder's stage names
        "rung": (
            {
                "headline": _text(rung.get("headline")),
                "read_of_him": _text(rung.get("read_of_him")),
                "cares_most": _texts(rung.get("cares_most")),
                "cares_less_right_now": _texts(rung.get("cares_less_right_now")),
                "plan": _text(rung.get("plan")),
            }
            if rung
            else None
        ),
        "ladder": [_text(r.get("headline")) for r in s.get("ladder") or [] if isinstance(r, dict) and _text(r.get("headline"))],
        "withheld_text": _withheld(s),
    }


def _history(rows: Any) -> list[dict]:
    out = []
    for r in rows or []:
        if not isinstance(r, dict) or not _day(r.get("as_of")):
            continue
        stage = r.get("stage") if isinstance(r.get("stage"), dict) else {}
        out.append(
            {
                "as_of": _day(r.get("as_of")),
                "headline_read": _text(r.get("headline_read")),
                "how_my_read_changed": _text(r.get("how_my_read_changed")),
                "stage_label": _text(stage.get("label")),
                "grade_corrections": [c for c in (_correction_note(n) for n in r.get("grade_corrections") or []) if c],
                "withheld_text": _withheld(r),
            }
        )
    return sorted(out, key=lambda r: r["as_of"], reverse=True)


def _latest_read(payload: dict) -> dict | None:
    """The lead: its daily read with the figures it cites. A staff coach: its newest served output row."""
    lead = payload.get("lead_daily")
    if isinstance(lead, dict) and (lead.get("generated_at") or lead.get("text") is not None):
        return {
            "kind": "lead_daily",
            "source": COACH_PATH.format(payload.get("persona_id")) + " · lead_daily",
            "text": _text(lead.get("text")),
            "generated_at": _instant(lead.get("generated_at")),
            "data_through": _day(lead.get("data_through")),
            "date": _day(lead.get("generated_at")),
            "cited": [
                {
                    "metric": _text(c.get("metric")),
                    "value": _text(str(c.get("value"))) if c.get("value") is not None else "",
                    "as_of": _day(c.get("as_of")),
                }
                for c in lead.get("cited") or []
                if isinstance(c, dict) and _text(c.get("metric"))
            ],
            "withheld_text": _withheld(lead),
        }
    rows = [r for r in payload.get("recent_outputs") or [] if isinstance(r, dict) and _day(r.get("date"))]
    if not rows:
        return None
    r = sorted(rows, key=lambda r: (str(r.get("date")), str(r.get("generated_at") or "")), reverse=True)[0]
    return {
        "kind": "output",
        "source": COACH_PATH.format(payload.get("persona_id")) + " · recent_outputs",
        "text": _text(r.get("summary")),
        "generated_at": _instant(r.get("generated_at")),
        "data_through": _day(r.get("data_through")),
        "date": _day(r.get("date")),
        "cited": [],
        "withheld_text": _withheld(r),
    }


def _asks(dossier: dict) -> dict:
    rows = []
    for c in dossier.get("commitments") or []:
        if not isinstance(c, dict) or not _day(c.get("date")):
            continue
        chk = c.get("check") if isinstance(c.get("check"), dict) else None
        check = None
        if chk and isinstance(chk.get("metric"), str) and not _private(chk.get("metric")) and not _private(chk.get("direction")):
            check = {"metric": chk["metric"], "direction": chk.get("direction") if isinstance(chk.get("direction"), str) else None}
        rows.append(
            {
                "date": _day(c.get("date")),
                "due_date": _day(c.get("due_date")),
                "status": c.get("status") if isinstance(c.get("status"), str) else None,
                "outcome": c.get("outcome") if isinstance(c.get("outcome"), str) else None,
                "outcome_date": _day(c.get("outcome_date")),
                "text": _text(c.get("text")),
                "outcome_notes": _text(c.get("outcome_notes")),
                "check": check,
                "withheld_text": _withheld(c),
            }
        )
    counts = dossier.get("commitment_counts") if isinstance(dossier.get("commitment_counts"), dict) else None
    return {
        "commitment_counts": {k: counts.get(k) for k in COUNT_KEYS if isinstance(counts.get(k), int)} if counts else None,
        "rows": rows,
        "degraded": bool(dossier.get("degraded")),
        "disclosure": _text(dossier.get("disclosure")) or None,
    }


def _positions(dossier: dict) -> list[dict]:
    out = []
    for p in dossier.get("docket_positions") or []:
        if not isinstance(p, dict) or not _day(p.get("date")):
            continue
        out.append(
            {
                "date": _day(p.get("date")),
                "topic": _text(p.get("topic")),
                "my_claim": _text(p.get("my_claim")),
                "versus": p.get("versus") if isinstance(p.get("versus"), str) else None,
                "criterion": _text(p.get("criterion")),
                "resolution_date": _day(p.get("resolution_date")),
            }
        )
    return out


def _voice(payload: dict) -> dict | None:
    ch = payload.get("character") if isinstance(payload.get("character"), dict) else {}
    cv = ch.get("voice") if isinstance(ch.get("voice"), dict) else {}
    v = payload.get("voice") if isinstance(payload.get("voice"), dict) else {}
    ds = v.get("decision_style") if isinstance(v.get("decision_style"), dict) else {}
    sv = v.get("structural_voice_rules") if isinstance(v.get("structural_voice_rules"), dict) else {}
    out = {
        "tone": _text(cv.get("tone")),
        "style": _text(cv.get("style")),
        "evidence_threshold": _text(ds.get("default_evidence_threshold")),
        "bold_claims": _text(ds.get("comfort_with_bold_claims")),
        "revision_style": _text(ds.get("revision_style")),
        "uncertainty_style": _text(sv.get("uncertainty_style")),
    }
    return out if any(out.values()) else None


def _record_card(payload: dict) -> dict | None:
    tr = ((payload.get("report_card") or {}).get("track_record")) if isinstance(payload.get("report_card"), dict) else None
    if not isinstance(tr, dict):
        return None
    rec = tr.get("record") if isinstance(tr.get("record"), dict) else {}
    comp = tr.get("comparison") if isinstance(tr.get("comparison"), dict) else {}
    return {
        "headline": _text(tr.get("headline")) or None,
        "right": _num(rec.get("confirmed")),
        "n": _num(rec.get("n")),
        "through": _day(rec.get("through")),
        "skill_sentence": _text((comp.get("skill") or {}).get("sentence")) or None if isinstance(comp.get("skill"), dict) else None,
        "records": comp.get("records") if isinstance(comp.get("records"), dict) else None,
        "caveat": _text(tr.get("caveat")) or None,
    }


def _docket_entry(d: dict) -> dict | None:
    a, b = d.get("coach_a"), d.get("coach_b")
    if not (isinstance(a, str) and isinstance(b, str)):
        return None
    crit = d.get("criterion") if isinstance(d.get("criterion"), dict) else {}
    verdict = d.get("verdict") if isinstance(d.get("verdict"), dict) else {}
    stakes = d.get("stakes") if isinstance(d.get("stakes"), dict) else {}
    sides = d.get("sides") if isinstance(d.get("sides"), dict) else {}
    claims = d.get("claims") if isinstance(d.get("claims"), dict) else {}
    metric = crit.get("metric") if isinstance(crit.get("metric"), str) and not _private(crit.get("metric")) else None
    return {
        "coach_a": a,
        "coach_b": b,
        "opened_date": _day(d.get("opened_date") or d.get("opened")),
        "resolution_date": _day(d.get("resolution_date")),
        "resolved_date": _day(d.get("resolved_date")),
        "topic": _text(d.get("topic")),
        "claims": {k: _text(claims.get(k)) for k in (a, b)},
        "criterion": {
            "description": _text(crit.get("description")),
            "metric": metric,
            "condition": crit.get("condition") if metric and isinstance(crit.get("condition"), str) else None,
            "threshold": _num(crit.get("threshold")) if metric else None,
        },
        "sides": {k: sides.get(k) if isinstance(sides.get(k), bool) else None for k in (a, b)},
        "stakes": {
            k: {"brier": _num((stakes.get(k) or {}).get("brier")), "brier_n": _num((stakes.get(k) or {}).get("brier_n"))}
            for k in (a, b)
            if isinstance(stakes.get(k), dict)
        },
        "winner": (
            verdict.get("winner")
            if isinstance(verdict.get("winner"), str)
            else d.get("winner") if isinstance(d.get("winner"), str) else None
        ),
        "outcome": verdict.get("outcome") if isinstance(verdict.get("outcome"), str) else None,
        "actual_value": _num(verdict.get("actual_value")) if metric else None,
        "concession": _text(d.get("concession")),
        # CR3: the API's OWN words for what it held back, carried as served: a side's claim held by the claim-sourcing
        # rule (`unsourced[coach].text`) or by a dark instrument on an open item (`absent[coach].reason`), and a held
        # concession (`concession_unsourced.text`). Never reconstructed: a missing key means the API said nothing.
        "withheld": {k: w for k in (a, b) if (w := _side_withheld(d, k))},
        "concession_withheld": _withheld({"unsourced": d.get("concession_unsourced")}),
        "loser": (
            verdict.get("loser") if isinstance(verdict.get("loser"), str) else d.get("loser") if isinstance(d.get("loser"), str) else None
        ),
        "holds": verdict.get("holds") if isinstance(verdict.get("holds"), bool) else None,
    }


def _side_withheld(d: dict, coach: str) -> str | None:
    """The API's own message for one side's held claim, or None (CR3)."""
    uns = d.get("unsourced") if isinstance(d.get("unsourced"), dict) else {}
    got = _withheld({"unsourced": uns.get(coach)})
    if got:
        return got
    absent = d.get("absent") if isinstance(d.get("absent"), dict) else {}
    side = absent.get(coach) if isinstance(absent.get(coach), dict) else {}
    return _text(side.get("reason")) or None


def docket_id(e: dict) -> str:
    """A docket entry's room id: its open day and its two seats. Never built from the topic, whose slug spells out words
    the API may withhold. Lower-case letters, digits and hyphens only."""
    raw = f"{e.get('opened_date') or 'undated'}-{e['coach_a']}-{e['coach_b']}"
    return re.sub(r"[^a-z0-9]+", "-", raw.lower()).strip("-")


def shape_coach(payload: Any) -> dict | None:
    """One coach's entry from its served `/api/coach/<id>` payload; None when the payload is not a coach page."""
    if not isinstance(payload, dict) or not isinstance(payload.get("persona_id"), str):
        return None
    dossier = payload.get("dossier") if isinstance(payload.get("dossier"), dict) else {}
    return {
        "persona_id": payload["persona_id"],
        "absent": bool(payload.get("absent")),
        "absent_reason": _text(payload.get("reason")) or None,
        "latest_read": _latest_read(payload),
        "stance": _stance(payload.get("stance")),
        "stance_history": _history(payload.get("stance_history")),
        "asks": _asks(dossier),
        "docket_positions": _positions(dossier),
        "docket": [],
        "voice": _voice(payload),
        "fidelity": None,
        "record_card": _record_card(payload),
        "disclosure": _text(payload.get("disclosure")) or None,
    }


def shape(coaches: dict[str, Any], docket: Any, fidelity: Any, fetched_at: str | None = None) -> dict:
    """The data file from the served payloads. `coaches` maps persona id → its `/api/coach/<id>` payload (or None)."""
    entries = {}
    for pid, payload in coaches.items():
        e = shape_coach(payload)
        if e and e["persona_id"] == pid:
            entries[pid] = e
    if not entries:
        return dict(ABSENT_COACH_ROOM)
    docket_entries: list[dict] = []
    if isinstance(docket, dict):
        seen: set[str] = set()
        for status in ("open", "resolved"):
            for d in docket.get(status) or []:
                e = _docket_entry(d) if isinstance(d, dict) else None
                if not e:
                    continue
                e["status"] = status
                eid = docket_id(e)
                if eid in seen:  # the same seats opened twice on one day: the settle day tells them apart
                    eid = f"{eid}-{re.sub(r'[^0-9]+', '', e.get('resolution_date') or '') or len(seen)}"
                seen.add(eid)
                e["id"] = eid
                docket_entries.append(e)
                for side in (e["coach_a"], e["coach_b"]):
                    if side in entries:
                        entries[side]["docket"].append(e)
    vf = None
    if isinstance(fidelity, dict) and isinstance(fidelity.get("coaches"), list):
        for c in fidelity["coaches"]:
            if isinstance(c, dict) and c.get("coach_id") in entries:
                entries[c["coach_id"]]["fidelity"] = {
                    "n": _num(c.get("n")),
                    "correct": _num(c.get("correct")),
                    "accuracy_pct": _num(c.get("accuracy_pct")),
                    "distinguishability": c.get("distinguishability") if isinstance(c.get("distinguishability"), str) else None,
                }
        vf = {
            "n": _num(fidelity.get("n")),
            "correct": _num(fidelity.get("correct")),
            "accuracy_pct": _num(fidelity.get("accuracy_pct")),
            "chance_accuracy_pct": _num(fidelity.get("chance_accuracy_pct")),
            "candidate_pool_size": _num(fidelity.get("candidate_pool_size")),
            "verdict": fidelity.get("verdict") if isinstance(fidelity.get("verdict"), str) else None,
            "scope": _text(fidelity.get("scope")) or None,
            "run_month": fidelity.get("run_month") if isinstance(fidelity.get("run_month"), str) else None,
            "updated_at": _instant(fidelity.get("updated_at")),
            "disclosure": _text(fidelity.get("disclosure")) or None,
        }
    return {
        "state": "ok",
        "absent_text": None,
        "source": [COACH_PATH.format("<id>"), DOCKET_PATH, FIDELITY_PATH],
        "fetched_at": _instant(fetched_at),
        "coaches": entries,
        "voice_fidelity": vf,
        # CR3: the docket itself, one entry per disagreement (the same entries filed under each coach above), with the
        # API's own tally and disclosure. A privacy-held entry is neither served nor counted by the API (owner 2026-11-06).
        "docket_entries": docket_entries,
        "docket_counts": (
            {k: v for k, v in docket["counts"].items() if k in ("open", "resolved") and isinstance(v, int) and not isinstance(v, bool)}
            if isinstance(docket, dict) and isinstance(docket.get("counts"), dict)
            else None
        ),
        "docket_disclosure": (_text(docket.get("disclosure")) or None) if isinstance(docket, dict) else None,
    }


def live_coach_room(get: Callable[[str], Any], persona_ids: Iterable[str], log: Callable[[str], None] = print) -> dict:
    """Fetch the public routes; a coach that fails is left out (its page then says so), a total failure is absent."""
    coaches: dict[str, Any] = {}
    fetched_at = None
    for pid in sorted(persona_ids):
        try:
            payload = get(COACH_PATH.format(pid))
            coaches[pid] = payload
            fetched_at = fetched_at or ((payload or {}).get("_meta") or {}).get("served_at")
        except Exception as exc:  # noqa: BLE001 — one coach's failure leaves that coach out, never a partial entry
            log(f"  coach profile {pid} unavailable ({exc}); left out of coach_room.json")
    docket = fidelity = None
    for path in (DOCKET_PATH, FIDELITY_PATH):
        try:
            got = get(path)
        except Exception as exc:  # noqa: BLE001
            log(f"  {path} unavailable ({exc}); that section of coach_room.json left empty")
            got = None
        if path == DOCKET_PATH:
            docket = got
        else:
            fidelity = got
    return shape(coaches, docket, fidelity, fetched_at)


def fixture_coach_room(fixtures_dir: str) -> dict:
    """The committed sample (content/fixtures/coach_room.json, already in data-file shape)."""
    path = os.path.join(fixtures_dir, "coach_room.json")
    if not os.path.exists(path):
        return dict(ABSENT_COACH_ROOM)
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _walk_strings(node: Any):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for v in node.values():
            yield from _walk_strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk_strings(v)


def resolve_and_validate(payload: dict, public: dict[str, list[dict]]) -> dict:
    """Keep only coaches that are public Coach objects in this snapshot; check the shape the room reads; refuse a file
    that names a private family anywhere (the producer's own belt, checked again on the whole file).

    Raises ValueError (the caller maps it to SchemaError) on a malformed ok payload."""
    if payload.get("state") != "ok":
        return payload
    coaches = payload.get("coaches")
    if not isinstance(coaches, dict):
        raise ValueError("coach_room.json: an ok file needs a coaches object")
    public_ids = {o["id"] for o in public.get("coach", [])}
    payload["coaches"] = {k: v for k, v in coaches.items() if k in public_ids}
    # CR3: a docket entry is kept only when BOTH seats are public coaches in this snapshot (the ledger's own rule for a
    # disagreement): a seat with no public page has no name to print. A file without the key (pre-CR3) reads as none.
    entries = payload.get("docket_entries", [])
    if not isinstance(entries, list):
        raise ValueError("coach_room.json: docket_entries must be a list")
    payload["docket_entries"] = [
        d
        for d in entries
        if isinstance(d, dict) and isinstance(d.get("id"), str) and d.get("coach_a") in public_ids and d.get("coach_b") in public_ids
    ]
    for pid, c in payload["coaches"].items():
        counts = (c.get("asks") or {}).get("commitment_counts")
        if counts is not None and not all(isinstance(counts.get(k), int) for k in counts):
            raise ValueError(f"coach_room.json: coaches[{pid}].asks.commitment_counts must be integers")
        if not isinstance(c.get("stance_history"), list):
            raise ValueError(f"coach_room.json: coaches[{pid}].stance_history must be a list")
    for s in _walk_strings(payload):
        if _private(s) and not s.startswith("/api/"):
            raise ValueError("coach_room.json: a carried string names a private family")
    return payload
