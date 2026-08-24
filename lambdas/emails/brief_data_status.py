"""brief_data_status.py — the daily brief's data-status surfaces (#2326).

The quiet notice for load-bearing behavioral sources, plus the WR-48 "Data
Status" banner renderer (extracted from daily_brief_lambda per the module-size
guard, #1665 — the brief may not grow, cohesive helpers live beside it).

#2326: a `behavioral: True` source never pages by design (#392) — but
MacroFactor went 45 days dark with the Dropbox poller perfectly healthy, and no
surface an operator reads said so: "never page" had quietly become "never
mention". The watch set and thresholds derive from the canonical registry
(behavioral + load-bearing, quiet_after_days = several multiples of the
canonical stale_hours) — a DISTINCT signal from infra staleness, never a
re-threshold of it. Decision + do-not-reclassify rationale recorded next to
source_registry.quiet_watch_sources().
"""

import os
from datetime import datetime

from boto3.dynamodb.conditions import Key
from experiment.phase_filter import with_phase_filter  # ADR-058
from ingestion import source_registry

QUIET_WATCH_SOURCES = source_registry.quiet_watch_sources()


def scan_quiet_behavioral_sources(table, today_d, user_id=None):
    """One dict per QUIET load-bearing behavioral source (#2326):
    {source, label, age_days|None, last_date?, quiet_after_days}.

    age_days None = no record on file at all. The read is CROSS-PHASE for the
    same reason scan_stale_sources' is (#2080): "is Matthew still logging" is a
    question about behavior, not the experiment generation, and a newest-first
    Limit:1 read with the phase filter attached goes blind after every reset.
    """
    user_id = user_id or os.environ.get("USER_ID", "matthew")
    quiet = []
    for src, cfg in sorted(QUIET_WATCH_SOURCES.items()):
        try:
            kwargs = with_phase_filter(
                {
                    "KeyConditionExpression": Key("pk").eq(f"USER#{user_id}#SOURCE#{src}") & Key("sk").begins_with("DATE#"),
                    "Limit": 1,
                    "ScanIndexForward": False,
                },
                include_pilot=True,  # cross-phase, per #2080
            )
            items = table.query(**kwargs).get("Items", [])
            if not items:
                quiet.append({"source": src, "label": cfg["label"], "age_days": None, "quiet_after_days": cfg["quiet_after_days"]})
                continue
            sk = items[0].get("sk", "")
            date_part = sk.split("DATE#", 1)[1][:10] if sk.startswith("DATE#") else ""
            last_d = datetime.strptime(date_part, "%Y-%m-%d").date()
            age = (today_d - last_d).days
            if age >= cfg["quiet_after_days"]:
                quiet.append(
                    {
                        "source": src,
                        "label": cfg["label"],
                        "age_days": age,
                        "last_date": last_d.isoformat(),
                        "quiet_after_days": cfg["quiet_after_days"],
                    }
                )
        except Exception:
            pass
    return quiet


def qualified_compute_outputs(records):
    """#3049 (DIL-024): the compute outputs this brief is reading that were built
    on stale/missing input.

    ``records`` is ``{label: record_or_None}`` — whatever the brief already
    fetched. A record with no ``input_status`` predates the contract and is
    skipped (silence is not a claim, in either direction); ``complete`` is
    likewise skipped because there is nothing to say. Returns
    ``[{label, status, note}]``, sorted, ready for the renderer below.

    Deliberately a DIFFERENT signal from ``scan_stale_sources``: that one asks
    "is a source stale right NOW, at brief time"; this one reports what the
    compute run observed when it ran, hours earlier. A connector that recovered
    in between makes the first say "fine" while the day's score is still built
    on the gap — which is precisely the blindness #3049 names.
    """
    from common.input_manifest import MANIFEST_COMPLETE, manifest_note

    out = []
    for label, rec in sorted((records or {}).items()):
        if not isinstance(rec, dict):
            continue
        status = rec.get("input_status")
        if not status or status == MANIFEST_COMPLETE:
            continue
        note = manifest_note(rec.get("input_manifest"))
        if not note:
            continue
        out.append({"label": label, "status": str(status), "note": note})
    return out


def build_data_status_banner_html(stale, quiet, compute_partial=None):
    """The WR-48 "Data Status" banner + the #2326 "Quiet inputs" notice + the
    #3049 "Computed on partial input" notice, as one HTML string ("" when there
    is nothing to say). Pure — testable without SES.

    Honesty split (ADR-104): a load-bearing behavioral source that has crossed
    its quiet threshold is re-homed OUT of the amber "stale" list (which reads
    as breakage) into a calm block that states the absence — nothing is broken,
    there is simply nothing to ingest, and nothing pages.

    ``compute_partial`` (from ``qualified_compute_outputs``) is the third,
    distinct block: not "a source is stale" but "the number below was computed
    without it". Rendered even when the stale list is empty, because the whole
    point is that these two can disagree.
    """
    quiet_keys = {q["source"] for q in quiet}
    stale = [s for s in stale if s["source"] not in quiet_keys]
    html_parts = []
    if stale:
        _row_parts = []
        for _s in stale:
            _src_name = _s["source"]
            _age = _s.get("age_days")
            if _age is None:
                _detail = "no data"
            else:
                _last = _s.get("last_date", "?")
                _detail = f"last update {_last} ({_age}d ago)"
            _row_parts.append(f'<li style="margin:2px 0">{_src_name} — {_detail}</li>')
        _banner_rows = "".join(_row_parts)
        html_parts.append(
            '<div style="background:#fef3c7;border-left:4px solid #f59e0b;padding:14px 18px;'
            'margin:0 0 16px;font-family:-apple-system,sans-serif;font-size:13px;color:#78350f">'
            f'<strong style="color:#92400e">⚠️ Data Status — {len(stale)} source{"s" if len(stale) > 1 else ""} stale</strong>'
            f'<ul style="margin:6px 0 0;padding-left:18px;color:#78350f">{_banner_rows}</ul>'
            '<div style="margin-top:8px;font-size:11px;color:#92400e">'
            "The intelligence below is based on the data we have. "
            "Stale sources can pull the day grade down without reflecting your actual behavior."
            "</div></div>"
        )
    if quiet:
        _q_parts = []
        for _q in quiet:
            if _q["age_days"] is None:
                _detail = "no record on file"
            else:
                _detail = f"nothing logged since {_q['last_date']} ({_q['age_days']} days)"
            _q_parts.append(f'<li style="margin:2px 0">{_q["label"]} — {_detail} ' f'(notice line: {_q["quiet_after_days"]}d)</li>')
        html_parts.append(
            '<div style="background:#eef2ff;border-left:4px solid #6366f1;padding:14px 18px;'
            'margin:0 0 16px;font-family:-apple-system,sans-serif;font-size:13px;color:#312e81">'
            f'<strong style="color:#4338ca">Quiet inputs — {len(quiet)} load-bearing source{"s" if len(quiet) > 1 else ""} '
            "with nothing to ingest</strong>"
            f'<ul style="margin:6px 0 0;padding-left:18px;color:#312e81">{"".join(_q_parts)}</ul>'
            '<div style="margin-top:8px;font-size:11px;color:#4338ca">'
            "These only produce data when you log, weigh in, or train — the pipes are not broken "
            "and nothing is paging. This is a note about absence, not an outage (#2326)."
            "</div></div>"
        )
    if compute_partial:
        _c_parts = []
        for _c in compute_partial:
            _c_parts.append(f'<li style="margin:2px 0"><strong>{_c["label"]}</strong> ({_c["status"]}) — {_c["note"]}</li>')
        html_parts.append(
            '<div style="background:#fef2f2;border-left:4px solid #ef4444;padding:14px 18px;'
            'margin:0 0 16px;font-family:-apple-system,sans-serif;font-size:13px;color:#7f1d1d">'
            f'<strong style="color:#991b1b">Computed on partial input — {len(compute_partial)} '
            f'output{"s" if len(compute_partial) > 1 else ""} qualified</strong>'
            f'<ul style="margin:6px 0 0;padding-left:18px;color:#7f1d1d">{"".join(_c_parts)}</ul>'
            '<div style="margin-top:8px;font-size:11px;color:#991b1b">'
            "These are the compute run's OWN record of what it could see when it ran (#3049). "
            "A source that has recovered since does not un-qualify the numbers below — they were "
            "computed without it."
            "</div></div>"
        )
    return "".join(html_parts)
