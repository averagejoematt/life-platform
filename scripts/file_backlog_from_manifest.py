#!/usr/bin/env python3
"""File a review backlog as GitHub issues from a spec JSON — the reusable ADR-099 filer.

The 2026-07 platform-review backlog (#337-#423) was filed by hand with the manifest
written afterward as the idempotency record. This script closes that automation gap:
it reads a spec (epics + scored stories), creates the issues via `gh`, and maintains
the manifest (spec key -> issue number) as it goes, so re-runs only create what's
missing. Three passes: epics, stories (each linked to its epic), then epic bodies
gain a task-list of their child stories.

Spec shape (see docs/reviews/DSR_BACKLOG_MANIFEST_2026-07.json's `spec` copy):
{
  "review": "...", "manifest_path": "docs/reviews/..._MANIFEST_....json",
  "milestones": {"Now": 1, "Next": 2, "Later": 3},
  "epic_labels": [...], "story_labels": [...],
  "epics":  [{"key", "title", "body"}],
  "stories": [{"key", "epic", "title", "labels", "milestone", "body"}]
}

Usage:
  python3 scripts/file_backlog_from_manifest.py SPEC.json --dry-run   # preview
  python3 scripts/file_backlog_from_manifest.py SPEC.json             # file
"""
import argparse
import json
import os
import subprocess
import sys


def sh(args, input_text=None):
    res = subprocess.run(args, capture_output=True, text=True, input=input_text)
    if res.returncode != 0:
        raise RuntimeError(f"{' '.join(args)} failed: {res.stderr.strip()}")
    return res.stdout.strip()


def load_manifest(path):
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {"epics": {}, "stories": {}}


def save_manifest(path, manifest):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")


def create_issue(title, body, labels, milestone=None, dry=False):
    if dry:
        print(f"  [dry-run] would create: {title}  labels={labels} milestone={milestone}")
        return 0
    args = ["gh", "issue", "create", "--title", title, "--body-file", "-"]
    for lb in labels:
        args += ["--label", lb]
    if milestone:
        args += ["--milestone", milestone]
    url = sh(args, input_text=body)
    return int(url.rstrip("/").rsplit("/", 1)[-1])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("spec")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    with open(args.spec) as f:
        spec = json.load(f)
    manifest_path = spec["manifest_path"]
    manifest = load_manifest(manifest_path)
    manifest.setdefault("review", spec.get("review"))
    dry = args.dry_run

    # Pass 1: epics
    for epic in spec["epics"]:
        if epic["key"] in manifest["epics"]:
            print(f"epic {epic['key']} exists as #{manifest['epics'][epic['key']]} — skip")
            continue
        num = create_issue(epic["title"], epic["body"], spec.get("epic_labels", []), dry=dry)
        print(f"epic {epic['key']} -> #{num}")
        if not dry:
            manifest["epics"][epic["key"]] = num
            save_manifest(manifest_path, manifest)

    # Pass 2: stories
    for story in spec["stories"]:
        if story["key"] in manifest["stories"]:
            print(f"story {story['key']} exists as #{manifest['stories'][story['key']]} — skip")
            continue
        epic_num = manifest["epics"].get(story["epic"])
        body = story["body"]
        if epic_num:
            body += f"\n\nEpic: #{epic_num}"
        labels = spec.get("story_labels", []) + story.get("labels", [])
        num = create_issue(story["title"], body, labels, milestone=story.get("milestone"), dry=dry)
        print(f"story {story['key']} ({story.get('milestone')}) -> #{num}")
        if not dry:
            manifest["stories"][story["key"]] = num
            save_manifest(manifest_path, manifest)

    # Pass 3: epic task lists
    if not dry:
        for epic in spec["epics"]:
            epic_num = manifest["epics"].get(epic["key"])
            if not epic_num:
                continue
            children = [(s["key"], manifest["stories"].get(s["key"])) for s in spec["stories"] if s["epic"] == epic["key"]]
            tasks = "\n".join(f"- [ ] #{n} ({k})" for k, n in children if n)
            body = epic["body"] + "\n\n## Stories\n" + tasks
            sh(["gh", "issue", "edit", str(epic_num), "--body-file", "-"], input_text=body)
            print(f"epic {epic['key']} #{epic_num}: task list of {len(children)} stories written")

    print(f"\nmanifest: {manifest_path} — {len(manifest['epics'])} epics, {len(manifest['stories'])} stories")


if __name__ == "__main__":
    sys.exit(main())
