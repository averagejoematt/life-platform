#!/usr/bin/env python3
"""scripts/phenoage_private.py — the owner's own Levine Phenotypic Age, computed privately (owner ruling 2026-11-14).

The public surface no longer carries this figure: the formula is linear in chronological age and its nine inputs are
public lab values, so the number at any precision gives the age away (tests/test_age_inversion.py). The precise
computation is kept HERE, for the owner, on the owner's machine:

    python3 scripts/phenoage_private.py            # the figure at the blood draw's date
    python3 scripts/phenoage_private.py --today    # the same markers at today's age

It reads the profile's birth date and the clinical record with the caller's own AWS credentials (read-only), prints
to this terminal and writes nothing. Never redirect its output into the repository, a public bucket, a prompt that
feeds published prose, or an issue: the figure it prints is the age.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--today", action="store_true", help="use today's age instead of the age at the draw")
    args = ap.parse_args()

    import boto3
    from web import site_api_biomarkers as B

    region = os.environ.get("AWS_REGION", "us-west-2")
    table = boto3.resource("dynamodb", region_name=region).Table(os.environ.get("TABLE_NAME", "life-platform"))
    prof = table.get_item(Key={"pk": "USER#matthew", "sk": "PROFILE#v1"}).get("Item") or {}
    dob = str(prof.get("date_of_birth") or "")[:10]
    if not dob:
        print("no date_of_birth in the profile — nothing computed", file=sys.stderr)
        return 2
    body = (
        boto3.client("s3", region_name=region)
        .get_object(Bucket=os.environ.get("S3_BUCKET", "matthew-life-platform"), Key="dashboard/matthew/clinical.json")["Body"]
        .read()
    )
    labs = json.loads(body).get("labs", {})
    by = {}
    for m in labs.get("biomarkers", []) or []:
        by.setdefault(str(m.get("name", "")).strip().lower(), m)

    def num(name):
        return float(str(by[name]["value"]).replace("<", "").replace(">", "").strip())

    wbc = num("wbc")
    vals = {
        "albumin_gL": num("albumin") * 10.0,
        "creatinine_umolL": num("creatinine") * 88.42,
        "glucose_mmolL": num("glucose") / 18.0182,
        "crp_mgdL": num("crp hs") / 10.0,
        "lymphocyte_pct": round(num("absolute lymphocytes") / (wbc * 1000.0) * 100.0, 1),
        "mcv_fL": num("mcv"),
        "rdw_pct": num("rdw"),
        "alp_UL": num("alkaline phosphatase"),
        "wbc_1000": wbc,
    }
    draw = str(labs.get("latest_draw_date") or "")[:10]
    at = datetime.now(timezone.utc).replace(tzinfo=None) if args.today or not draw else datetime.strptime(draw, "%Y-%m-%d")
    age = (at - datetime.strptime(dob, "%Y-%m-%d")).days / 365.25
    pheno = B._compute_phenoage(vals, age)
    if pheno is None:
        print("the formula could not be evaluated for these markers", file=sys.stderr)
        return 2
    print(f"PRIVATE — do not paste anywhere public.\nblood draw {draw or 'undated'} · computed at the age on {at:%Y-%m-%d}")
    print(f"phenotypic age {pheno:.1f} · chronological age {age:.1f} · difference {pheno - age:+.1f} years")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
