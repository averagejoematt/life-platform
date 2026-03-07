#!/usr/bin/env python3
"""
validate_links.py — Blog S3 Link Validator

Checks that every post linked from blog/index.html actually exists in S3.
Also validates that every blog post in S3 is linked from the index (no orphans).

Usage:
  python3 tests/validate_links.py            # check links + orphans
  python3 tests/validate_links.py --fix      # print aws s3 commands to remove orphans
  python3 tests/validate_links.py --verbose  # show all links (including passing)
"""

import argparse
import re
import sys
import boto3

GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
RESET  = "\033[0m"
BOLD   = "\033[1m"
DIM    = "\033[2m"

REGION   = "us-west-2"
S3_BUCKET = "matthew-life-platform"
BLOG_PREFIX = "blog/"
INDEX_KEY   = "blog/index.html"

s3 = boto3.client("s3", region_name=REGION)


def fetch_index():
    resp = s3.get_object(Bucket=S3_BUCKET, Key=INDEX_KEY)
    return resp["Body"].read().decode("utf-8")


def list_blog_posts():
    """Return set of S3 keys for all week-*.html posts in blog/."""
    paginator = s3.get_paginator("list_objects_v2")
    keys = set()
    for page in paginator.paginate(Bucket=S3_BUCKET, Prefix=BLOG_PREFIX):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            fname = key.replace(BLOG_PREFIX, "")
            if fname.startswith("week-") and fname.endswith(".html"):
                keys.add(fname)
    return keys


def extract_linked(html):
    """Return set of filenames linked from the index."""
    return set(re.findall(r'href="(week-[\w.\-]+\.html)"', html))


def main():
    parser = argparse.ArgumentParser(description="Blog S3 link validator")
    parser.add_argument("--fix",     action="store_true", help="Print aws s3 rm commands for orphaned posts")
    parser.add_argument("--verbose", action="store_true", help="Show all links, not just broken ones")
    args = parser.parse_args()

    print(f"\n{BOLD}Blog Link Validator{RESET} — {BLOG_PREFIX} on s3://{S3_BUCKET}\n")

    # Fetch data
    try:
        html = fetch_index()
    except Exception as e:
        print(f"{RED}✗ Cannot fetch {INDEX_KEY}: {e}{RESET}")
        sys.exit(1)

    try:
        existing = list_blog_posts()
    except Exception as e:
        print(f"{RED}✗ Cannot list blog posts in S3: {e}{RESET}")
        sys.exit(1)

    linked = extract_linked(html)

    print(f"  {DIM}Index links found: {len(linked)}{RESET}")
    print(f"  {DIM}S3 posts found:    {len(existing)}{RESET}\n")

    # --- Check 1: linked but missing from S3
    missing = sorted(f for f in linked if f not in existing)
    print(f"{BOLD}Linked → S3 (broken links){RESET}")
    if not missing:
        print(f"  {GREEN}✓ All {len(linked)} linked posts exist in S3{RESET}")
    else:
        for f in missing:
            print(f"  {RED}✗ MISSING: {f} — linked in index but not in S3{RESET}")

    print()

    # --- Check 2: in S3 but not linked (orphans)
    orphans = sorted(f for f in existing if f not in linked)
    print(f"{BOLD}S3 → Index (orphaned posts){RESET}")
    if not orphans:
        print(f"  {GREEN}✓ No orphaned posts — all S3 posts are linked{RESET}")
    else:
        for f in orphans:
            print(f"  {YELLOW}⚠ ORPHAN: {f} — in S3 but not linked from index{RESET}")

    # --- Verbose: list all passing links
    if args.verbose:
        print()
        print(f"{BOLD}All linked posts{RESET}")
        for f in sorted(linked):
            status = f"{GREEN}✓{RESET}" if f in existing else f"{RED}✗{RESET}"
            print(f"  {status} {f}")

    # --- Fix mode
    if args.fix and orphans:
        print()
        print(f"{BOLD}To remove orphans:{RESET}")
        for f in orphans:
            print(f"  aws s3 rm s3://{S3_BUCKET}/{BLOG_PREFIX}{f}")

    print()

    # Exit code
    if missing:
        print(f"{RED}{BOLD}RESULT: {len(missing)} broken link(s){RESET}")
        sys.exit(1)
    elif orphans:
        print(f"{YELLOW}{BOLD}RESULT: No broken links, {len(orphans)} orphaned post(s) (warnings only){RESET}")
    else:
        print(f"{GREEN}{BOLD}RESULT: All clear ✓{RESET}")


if __name__ == "__main__":
    main()
