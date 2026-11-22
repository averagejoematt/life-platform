#!/usr/bin/env python3
"""scripts/public_forecast_dry_run.py — what the platform's forecast rule would register now (#6156), writing nothing.

Reads LIVE public data over HTTPS from the Site API (``/api/series`` — the values any reader sees; no credentials, no
AWS client is created) and prints each forecast the rule would file today: the claim, the rule and its version, the
lineage (URL, window, the route's ``as_of``, n and the SHA-256 of the values), the frozen tolerance, the "nothing
changes" guess's value fixed at filing, the evaluation rule, and the reader window — checked by running the REAL
reader-call functions (``web.reader_call_rules``: ``call_kind``, ``open_until``, ``question``) on the row.

    python3 scripts/public_forecast_dry_run.py              # today (Pacific), human-readable
    python3 scripts/public_forecast_dry_run.py --json       # the full rows, JSON
    python3 scripts/public_forecast_dry_run.py --today 2026-11-23   # rehearse a filing day (data ends the day before)

Both switches are ignored (a dry run never files), and nothing is written anywhere.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

from coach import prediction_windows, public_forecast as F  # noqa: E402
from web import reader_call_rules as R  # noqa: E402
from web.prediction_reason import metric_unit, metric_words  # noqa: E402


class _NoTable:
    """A dry run is handed this, so any write attempt raises instead of reaching anything."""

    def __getattr__(self, name):
        raise RuntimeError(f"dry run: table.{name} is not available")


def reader_check(row: dict) -> dict:
    """The reader-call door's own verdict on the row, from the real functions."""
    spec, made = row["evaluation"], row["created_date"]
    eff = prediction_windows.effective_window_days(spec, row.get("subdomain", ""))
    due = prediction_windows.due_date(made, spec, row.get("subdomain", ""))
    last = R.open_until(spec, made, eff, due)
    unit = metric_unit(spec.get("metric"))
    return {
        "kind": R.call_kind(spec),
        "question": R.question(spec, metric_words(spec.get("metric")), made, eff, unit),
        "open_until": last,
        "open_days": (F._days_between(made, last) + 1) if last else 0,
        "result_due": due,
        "choices": [c["label"] for c in R.choices(spec, unit)],
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--today", help="the filing day to rehearse (YYYY-MM-DD); default: today, Pacific")
    ap.add_argument("--json", action="store_true", help="print the full rows as JSON")
    args = ap.parse_args(argv)
    if args.today is None:
        from common.pacific_time import pacific_today

        args.today = pacific_today()
    out = F.run(_NoTable(), today=args.today, persist=False)
    if out.get("status") != "ok":
        print(json.dumps(out, indent=2, default=str))
        return 1
    rows = out.get("forecasts") or []
    if args.json:
        print(json.dumps({"run": {k: v for k, v in out.items() if k != "forecasts"}, "forecasts": rows}, indent=2, default=str))
        return 0
    print(f"filing day {out['filed_on']} (cycle {out['cycle']}); outcomes: " + json.dumps(out["results"]))
    for row in rows:
        lin, base, sw, spec, model = row["lineage"], row["baseline_at_filing"], row["submission_window"], row["evaluation"], row["model"]
        chk = reader_check(row)
        print()
        print(f"  {row['author_words']} - {row['prediction_id']}")
        print(f"    prediction : {row['claim_natural']}")
        print(
            f"    model      : {model['id']} v{model['version']} ({model['kind']}: {model['words']}); prompt_version: {model['prompt_version']}"
        )
        print(
            f"    target     : {spec['metric']} on {spec['target_date']}: {spec['threshold']:g} (forecast) vs {spec['baseline_value']:g} (no change)"
        )
        print(f"    scoring    : {spec['scoring']} v{spec['scoring_version']} (frozen at filing) - {row['scoring']['words']}")
        print(f"    evaluation : {row['evaluation_rule']}")
        print(f"    baseline   : {base['words']} - {base['guess']} (fixed at filing; the {base['rule']} rule, its own record)")
        print(f"    lineage    : GET {lin['url']}")
        print(
            f"                 served as_of {lin['served_as_of']}, source {lin['source_id']}, window {lin['window']['from']}..{lin['window']['to']}"
        )
        print(f"                 n={lin['n']} readings, first {lin['readings'][0]}, last {lin['readings'][-1]}, sha256 {lin['sha256']}")
        print(f"    created_at : {row['created_at']} (append-only write; immutable)")
        print(f"    window     : opens {sw['opens']}, reader calls close end of {sw['closes']}, result due {sw['result_due']}")
        print(f"    reader door: kind={chk['kind']} open_until={chk['open_until']} ({chk['open_days']} days open) due={chk['result_due']}")
        print(f"                 {chk['question']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
