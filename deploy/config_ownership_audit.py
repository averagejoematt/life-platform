#!/usr/bin/env python3
"""config_ownership_audit.py — ONE registry of who owns every `config/` object (#3785).

WHAT THIS FILE IS
─────────────────
Before it, "is the repo copy of `config/x.json` the authority, or a stale print of
something a Lambda regenerates?" was answered by CONVENTION — by reading the file and
guessing from its shape. That convention failed on 2026-09-14 and kept failing for two
more days: `config/hevy_template_index.json` is rebuilt daily at 13:40Z by
`lambdas/training/hevy_template_index.py` and published to
`s3://matthew-life-platform/config/hevy_template_index.json`, and the repo ALSO carried
a June-1 copy of it — 789 templates against the live 820. Pushing the repo copy silently
reverted `draft_custom`'s title resolution to the June catalogue.

So every `config/` subject gets a RULING here, in one table, with the evidence that
earned it. A subject nobody can rule confidently gets `unknown` and says what was
checked — never a guess, because a guess in this table is indistinguishable from a
ruling and would re-arm exactly the gun this file exists to unload.

THE CLASSES, AND THE ONE PROPERTY THAT MATTERS
──────────────────────────────────────────────
The question every caller actually asks is *"may I push the repo copy of this to S3?"*,
so the classes are cut on the authority, not on how the bytes were made:

``runtime_generated``  A deployed Lambda writes this object to S3 on a schedule. **S3 is
                       the authority.** The repo must carry NO copy (see `stale-twin`
                       below) and no path may upload one. Repair = re-run the producer.
``repo_generated``     A repo-side script writes the file INTO THE TREE and it is
                       committed (`scripts/strava_type_census.py` and its
                       `_provenance.generated_by` stamp). The repo copy is the authority;
                       uploading it is a publish, exactly like a hand-owned file.
``hand_owned``         A human edits it in the repo. The repo copy is the authority.
``unknown``            Could not be ruled. Treated as NOT uploadable — fail closed, then
                       come back with evidence. This is a lead, not a verdict.

`uploadable()` is the single predicate the deploy path reads. `config_twin_registry`
drops every non-uploadable key from the twin set, so `config_twin_sync.py --apply`
cannot push one even by accident, and the sync refuses again at the upload call as a
second, independent stop.

THE WRITER OF THE 2026-09-14 CLOBBER WAS NOT AN AD-HOC COMMAND
───────────────────────────────────────────────────────────────
The issue assumed a hand `aws s3 cp` (its grep for the literal
`s3://matthew-life-platform/config` found no repo script, which is true and misleading —
`config_twin_sync` builds the key from a derived registry and calls `put_object`, so no
such literal exists to find). Measured instead against the run log, three for three:

    clobber 2026-09-14T16:43:13Z   site-deploy run 34870173215 started 16:41:38Z
    clobber 2026-09-14T18:13:46Z   site-deploy run 34879316544 started 18:11:45Z
    clobber 2026-09-15T17:47:58Z   site-deploy run 35003307196 started 17:46:03Z

and the third one's own log, to the second:

    2026-09-15T17:47:57.9Z  config twin drift — s3://…/config/ (41 derived twins)
    2026-09-15T17:47:57.9Z    🔴 DRIFT    config/hevy_template_index.json
    2026-09-15T17:47:57.9Z    uploaded: 2

`site-deploy.yml`'s "Sync bucket-root config/ twins (#2019)" step ran
`config_twin_sync.py --apply --strict`, the index was in the derived twin set, and it was
uploaded. The two site deploys that did NOT clobber (09-15 19:20Z, 09-16 06:29Z) are the
control: live was ALREADY the repo bytes then, so there was no drift to "fix". The
clobber was the sanctioned deploy path doing precisely what it was told, which is why no
amount of care with `aws s3 cp` would have prevented the next one.

WHAT IS DERIVED AND WHAT IS RULED
─────────────────────────────────
Rulings are written down, because "hand-owned" is a statement about intent that no static
analysis can make. Everything that CAN be derived is derived and cross-checked against
the table, so the two can never drift apart quietly:

  * `config_provenance_audit.declared_generated()` — a module that declares a `config/`
    key AND stamps `_built_at`. Every key it finds must be ruled `runtime_generated`
    here, so a NEW generated artifact reds this audit until someone rules it. That is
    the SET guard; the index is only the specimen.
  * Every `runtime_generated` ruling must name a producer `path.py:CONST` that still
    exists and still names the key — a producer deleted or repointed reds instead of
    silently leaving the table correct-looking.
  * Every `config/**.json` ON DISK must be ruled. The universe is the filesystem, not
    `git ls-files`: an untracked file in `config/` is loadable by `aws s3 cp` too.

Read-only. No AWS calls at all — this file grades the REPO. The live object's own
freshness is `deploy/config_provenance_audit.py`'s job (it reads `_built_at` against the
clock); the two are deliberately separate checks with separate blind spots.

    python3 deploy/config_ownership_audit.py            # the table + findings
    python3 deploy/config_ownership_audit.py --strict   # …and exit 1 on a finding
    python3 deploy/config_ownership_audit.py --json
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import sys
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config_provenance_audit import declared_generated  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = "config"

RUNTIME_GENERATED = "runtime_generated"
REPO_GENERATED = "repo_generated"
HAND_OWNED = "hand_owned"
UNKNOWN = "unknown"

# The repo copy may be pushed to S3 for these two classes and only these two.
UPLOADABLE_CLASSES = frozenset({REPO_GENERATED, HAND_OWNED})

_ICON = {RUNTIME_GENERATED: "🤖", REPO_GENERATED: "🛠", HAND_OWNED: "✍️", UNKNOWN: "❓"}


@dataclass(frozen=True)
class Ruling:
    """One subject's ownership ruling and the evidence that earned it.

    `subject` is repo-relative. A trailing `/` makes it a DIRECTORY ruling covering every
    JSON beneath it — used only where the whole tree shares one authority and one reason
    (the coach corpus, the portrait corpus), never as a catch-all.
    """

    subject: str
    owner: str
    evidence: str
    producer: str = ""  # "path.py:CONST" — REQUIRED for runtime_generated, else ""

    @property
    def is_dir_rule(self) -> bool:
        return self.subject.endswith("/")

    @property
    def uploadable(self) -> bool:
        return self.owner in UPLOADABLE_CLASSES


# ─────────────────────────────────────────────────────────────────────────────
# THE REGISTRY. Every `config/` subject, ruled, with what was checked.
# ─────────────────────────────────────────────────────────────────────────────

RULINGS: tuple[Ruling, ...] = (
    # ── runtime_generated: S3 is the authority, the repo must hold no copy ──
    Ruling(
        "config/hevy_template_index.json",
        RUNTIME_GENERATED,
        "#3764's producer walks the live Hevy catalogue and publishes the index daily at 13:40Z "
        "(cdk/stacks/ingestion_stack.py's HevyTemplateIndexRebuild rule); the payload carries _built_at/_sha256 "
        "and the June-1 committed copy carried neither. The repo twin was DELETED by #3785 — it was 789 templates "
        "against a live 820 and site-deploy's twin sync uploaded it three times.",
        producer="lambdas/training/hevy_template_index.py:INDEX_KEY",
    ),
    Ruling(
        "config/hevy_template_cache.json",
        RUNTIME_GENERATED,
        "S3-only: written at runtime by hevy_template_cache.py (put_object with a module-level key, which is why "
        "config_twin_registry's AST writer scan already excluded it) and never committed. Ruled here so the "
        "'no committed twin' invariant covers it the day someone commits one.",
        producer="lambdas/training/hevy_template_cache.py:CACHE_KEY",
    ),
    # ── repo_generated: a repo-side script writes the file into the tree ──
    Ruling(
        "config/strava_activity_type_census.json",
        REPO_GENERATED,
        "Its own `_provenance.generated_by` names scripts/strava_type_census.py, which writes CENSUS_PATH under the "
        "repo's config/ dir (line 34) — the tree is the output, not a print of an S3 object. Uploading it is a publish.",
    ),
    # ── hand_owned: a human edits the repo copy; it is the authority ──
    Ruling(
        "config/action_detection_rules.json",
        HAND_OWNED,
        "Hand-authored rule list read by lambdas/intelligence/intelligence_common.py. No writer in lambdas/mcp "
        "(config_twin_registry's AST scan) and no repo-side generator; last touched by a feature commit, 2026-04-07.",
    ),
    Ruling(
        "config/board_of_directors.json",
        HAND_OWNED,
        "The coach roster — hand-curated prose/palette, read by 14 modules and by scripts/render_portraits.py. "
        "No writer anywhere; edits arrive as reviewed commits (last: the WCAG palette pass, 2026-08-21).",
    ),
    Ruling(
        "config/challenges_catalog.json",
        HAND_OWNED,
        "Hand-curated challenge copy served by lambdas/web/site_api_social_challenges.py. No writer in lambdas/mcp, "
        "no repo-side generator; votes/state live in DynamoDB, not in this file.",
    ),
    Ruling(
        "config/character_sheet.json",
        HAND_OWNED,
        "The hand-designed game rulebook. deploy/restart_pipeline.py REWRITES FIELDS IN THE TREE at each experiment "
        "reset (CHAR_SHEET, line 146) and the result is committed — an operator edit to the authority, not a print "
        "of an S3 object. Uploading it is a publish (it also has a per-user alias key, see config_twin_registry).",
    ),
    Ruling(
        "config/content_filter.example.json",
        HAND_OWNED,
        "A committed TEMPLATE (`_README`: ER-06 vocabulary TEMPLATE). The real vocabulary is off-repo since #2503 "
        "and arrives by env/S3; this file is documentation and is excluded from the twin set by *.example.json.",
    ),
    Ruling(
        "config/cost_of_ownership.json",
        HAND_OWNED,
        'Says so itself: `_description` = "The hand-maintained half of stack.json\'s …". Read by '
        "scripts/v4_build_stack_manifest.py; nothing writes it.",
    ),
    Ruling(
        "config/experiment_library.json",
        HAND_OWNED,
        "Hand-curated experiment + citation corpus (the 2026-08-05 citation sweep edited it by hand). Read by six "
        "modules; no writer in lambdas/mcp and no repo-side generator.",
    ),
    Ruling(
        "config/food_vocabulary.json",
        HAND_OWNED,
        "Hand-authored token/alias vocabulary, STAGED INTO THE LAMBDA BUNDLE by deploy/build_bundle.py (so it has no "
        "S3 twin at all) and read by lambdas/health/meal_grouper.py. Nothing writes it.",
    ),
    Ruling(
        "config/ledger.json",
        HAND_OWNED,
        "Hand-authored accountability-ledger settings/causes read by lambdas/web/site_api_ledger.py. The ledger's "
        "TOTALS live in DynamoDB; this file is the static config half and nothing writes it.",
    ),
    Ruling(
        "config/movement_catalog.json",
        HAND_OWNED,
        "The generator's curated movement pool (its `_comment` says so; ADR-069 draws the line against the generated "
        "hevy_template_index). Read by five modules, written by none — verified with the AST writer scan and by "
        "grep for a repo-side writer; RUNBOOK §Hevy lists it as one of the four hand-owned `aws s3 cp` files.",
    ),
    Ruling(
        "config/personas.json",
        HAND_OWNED,
        "Hand-authored canonical persona registry, bundled into the Lambda zip by build_bundle.py and read by ~20 "
        "modules. Nothing writes it.",
    ),
    Ruling(
        "config/pii_denylist.example.json",
        HAND_OWNED,
        "A committed TEMPLATE (`_README`: ER-06 personal denylist TEMPLATE); the live denylist is off-repo. Excluded "
        "from the twin set by *.example.json.",
    ),
    Ruling(
        "config/podcast_series_bible.json",
        HAND_OWNED,
        "Hand-authored creative spine read by lambdas/emails/coach_panel_podcast_lambda.py. No writer.",
    ),
    Ruling(
        "config/podcast_watchlist.json",
        HAND_OWNED,
        "Hand-authored watchlist + extraction prompt, last edited 2026-03-26. No live reader in lambdas/mcp today "
        "and no writer anywhere — unconsumed, not generated.",
    ),
    Ruling(
        "config/project_pillar_map.json",
        HAND_OWNED,
        "Hand-maintained Todoist-project → pillar map with a hand `_last_verified` stamp (2026-03-08), read by "
        "lambdas/emails/monday_compass_lambda.py. Nothing writes it.",
    ),
    Ruling(
        "config/supplement_metadata.json",
        HAND_OWNED,
        "Hand-authored supplement reference. NO reader and NO writer found anywhere in the tree (grepped "
        "scripts/deploy/lambdas/mcp) — an orphan, which is a tidiness question and not an ownership one: nothing "
        "regenerates it, so the repo copy is the only authority there is.",
    ),
    Ruling(
        "config/supplement_registry.json",
        HAND_OWNED,
        "Hand-maintained stack registry (its `updated_at` is edited with the groups it describes) read by "
        "site_api_ledger/site_api_common and scripts/v4_build_stack_manifest.py. No writer in lambdas/mcp, no "
        "repo-side generator.",
    ),
    Ruling(
        "config/training_landmarks.json",
        HAND_OWNED,
        "Hand-authored per-muscle volume landmarks (`_authors`: the Personal Board) read by routine_generator. "
        "Nothing writes it; RUNBOOK §Hevy lists it as hand-owned.",
    ),
    Ruling(
        "config/training_phases.json",
        HAND_OWNED,
        "Hand-authored phase ladder; `current`/`current_started` are re-anchored by hand at each cycle (the "
        "2026-09-07 genesis edit). Read by routine_title/site_api_data; no writer.",
    ),
    Ruling(
        "config/training_week.json",
        HAND_OWNED,
        "Hand-authored schedule shape + session bounds read by routine_generator and mcp/tools_hevy_routine.py. "
        "Nothing writes it; RUNBOOK §Hevy lists it as hand-owned.",
    ),
    Ruling(
        "config/user_goals.json",
        HAND_OWNED,
        "Hand-authored mission/targets. Like character_sheet.json, deploy/restart_pipeline.py rewrites FIELDS in the "
        "tree at each reset (USER_GOALS, line 145) and the result is committed — the repo stays the authority, and "
        "deploy/sync_constants_from_config.py reads it to generate constants (the opposite direction).",
    ),
    Ruling(
        "config/vacation_fund.json",
        HAND_OWNED,
        "Hand-authored rate/start-date config read by lambdas/content/vacation_fund.py; the accrued total is computed "
        "from Strava at read time, not stored here. No writer.",
    ),
    # ── directory rulings: whole corpora with one authority and one reason ──
    Ruling(
        "config/coaches/",
        HAND_OWNED,
        "The coach prompt/stance corpus (ADR-153). Hand-authored, reviewed per file, bundled into the Lambda zip by "
        "build_bundle.py, and read by ai_calls/coach_quality_gate. No writer in lambdas/mcp; tuning_log.json is a "
        "hand-appended record of owner tuning decisions, not a machine log.",
    ),
    Ruling(
        "config/computation/",
        HAND_OWNED,
        "EWMA params + seasonal adjustments for coach_computation_engine — hand-set constants with no writer. "
        "(If a fitter ever starts publishing these, it becomes runtime_generated and this audit reds until ruled.)",
    ),
    Ruling(
        "config/narrative/",
        HAND_OWNED,
        "Hand-authored arc definitions. No reader in lambdas/mcp today and no writer anywhere.",
    ),
    Ruling(
        "config/portraits/",
        HAND_OWNED,
        "Per-coach portrait briefs under ADR-106 — AI may sketch, only Matthew approves, and the approved brief is "
        "committed. Read by scripts/render_portraits.py; nothing writes them.",
    ),
)


# ─────────────────────────────────────────────────────────────────────────────
# Lookup
# ─────────────────────────────────────────────────────────────────────────────


def _assigns_key(src: str, const: str, key: str) -> bool:
    """Does `src` ASSIGN `const` a value containing the string literal `key`?

    An AST read, not a substring one, and the difference is the whole point. The first
    draft of this check was `key in src and const in src`, and the M2 mutation (repoint
    INDEX_KEY at another object) left it GREEN — because the producer's module docstring
    names the key on line 5, so the text still matched while the code no longer wrote it.
    That is the shape #3856's enrolment ratchet was caught by four days earlier, and it
    reappeared here in a file written by someone who had just read that write-up.

    `os.environ.get("X", "config/y.json")` counts: the literal is the default the module
    ships with, which is what the ruling is about.
    """
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        targets = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            continue
        if not any(isinstance(t, ast.Name) and t.id == const for t in targets):
            continue
        if node.value is not None and any(isinstance(n, ast.Constant) and n.value == key for n in ast.walk(node.value)):
            return True
    return False


def _by_subject() -> dict[str, Ruling]:
    return {r.subject: r for r in RULINGS}


def ruling_for(rel_path: str) -> Ruling | None:
    """The ruling covering `config/x/y.json`: the exact entry, else the longest dir rule."""
    rel = rel_path.replace(os.sep, "/")
    exact = _by_subject().get(rel)
    if exact is not None:
        return exact
    best: Ruling | None = None
    for ruling in RULINGS:
        if ruling.is_dir_rule and rel.startswith(ruling.subject):
            if best is None or len(ruling.subject) > len(best.subject):
                best = ruling
    return best


def owner_of(rel_path: str) -> str:
    """Ownership class for a repo path / S3 key. An UNRULED subject is `unknown`."""
    ruling = ruling_for(rel_path)
    return ruling.owner if ruling else UNKNOWN


def uploadable(rel_path: str) -> bool:
    """May the repo copy of this subject be pushed to S3? Fail closed on `unknown`.

    This is the predicate `config_twin_registry` and `config_twin_sync` read. It is
    deliberately a total function over any path: a subject nobody has ruled is not
    uploadable, so a new generated artifact is safe on the day it appears rather than on
    the day someone remembers to classify it.
    """
    return owner_of(rel_path) in UPLOADABLE_CLASSES


def config_json_files(repo_root: str = REPO_ROOT) -> list[str]:
    """Every `config/**.json` ON DISK, repo-relative. The filesystem is the universe here.

    Not `git ls-files`: an untracked `config/*.json` is just as loadable by a hand
    `aws s3 cp` as a tracked one, and the point of this audit is what can be fired.
    """
    base = os.path.join(repo_root, CONFIG_DIR)
    out: list[str] = []
    for dirpath, _dirs, files in os.walk(base):
        if "__pycache__" in dirpath:
            continue
        for name in sorted(files):
            if name.endswith(".json"):
                full = os.path.join(dirpath, name)
                out.append(os.path.relpath(full, repo_root).replace(os.sep, "/"))
    return sorted(out)


# ─────────────────────────────────────────────────────────────────────────────
# The audit
# ─────────────────────────────────────────────────────────────────────────────


def findings(repo_root: str = REPO_ROOT) -> list[dict[str, str]]:
    """Everything wrong with the registry or the tree it describes.

    Severity `fail` exits 1 under --strict; `warn` is printed and does not. An `unknown`
    ruling is a warn BY DESIGN — it is already fail-closed for uploads, and making it
    fatal would push the next author to guess a class rather than write down what they
    could not determine.
    """
    out: list[dict[str, str]] = []
    on_disk = config_json_files(repo_root)

    # Vacuity guard. An empty walk is a broken derivation, never a clean tree.
    if not on_disk:
        out.append(
            {
                "severity": "fail",
                "code": "vacuous-walk",
                "subject": os.path.join(repo_root, CONFIG_DIR),
                "detail": "no config/**.json found on disk — the walk is broken; refusing to report a green over an empty set",
            }
        )
        return out

    # 1. Every file on disk is ruled.
    for rel in on_disk:
        if ruling_for(rel) is None:
            out.append(
                {
                    "severity": "fail",
                    "code": "unruled-file",
                    "subject": rel,
                    "detail": "no ruling in RULINGS — classify it (generated vs hand-owned) with the evidence you checked, "
                    "or rule it `unknown` and say what you checked. Until then it is not uploadable.",
                }
            )
        elif owner_of(rel) == UNKNOWN:
            out.append(
                {
                    "severity": "warn",
                    "code": "unknown-owner",
                    "subject": rel,
                    "detail": "ruled `unknown` — not uploadable until someone rules it",
                }
            )

    # 2. A runtime_generated subject must carry NO committed twin. THE INCIDENT.
    for ruling in RULINGS:
        if ruling.owner != RUNTIME_GENERATED or ruling.is_dir_rule:
            continue
        if os.path.exists(os.path.join(repo_root, ruling.subject.replace("/", os.sep))):
            out.append(
                {
                    "severity": "fail",
                    "code": "stale-twin",
                    "subject": ruling.subject,
                    "detail": f"{ruling.subject} is written to S3 by {ruling.producer or 'a producer'} — a repo copy is a stale "
                    "print of live state and any path that uploads it is a silent revert (#3785). Delete the repo copy; "
                    "repair the live object by re-running its producer.",
                }
            )

    # 3. Every runtime_generated ruling names a producer that still exists and still
    #    names the key. A repointed or deleted producer must red, not leave a
    #    correct-looking table behind.
    for ruling in RULINGS:
        if ruling.owner != RUNTIME_GENERATED:
            continue
        module, _, const = ruling.producer.partition(":")
        path = os.path.join(repo_root, module.replace("/", os.sep)) if module else ""
        if not module or not const or not os.path.isfile(path):
            out.append(
                {
                    "severity": "fail",
                    "code": "producer-missing",
                    "subject": ruling.subject,
                    "detail": f"runtime_generated ruling names producer {ruling.producer!r}, which is not a file in this tree",
                }
            )
            continue
        src = open(path, encoding="utf-8").read()
        if not _assigns_key(src, const, ruling.subject):
            out.append(
                {
                    "severity": "fail",
                    "code": "producer-stale",
                    "subject": ruling.subject,
                    "detail": f"{module} no longer names both {const} and {ruling.subject} — either the producer moved (update "
                    "the ruling) or it stopped writing this key (re-rule it)",
                }
            )

    # 4. THE SET GUARD. Every key the producer scan derives as generated must be ruled
    #    runtime_generated here, so the NEXT generated artifact enrols itself into this
    #    audit instead of waiting for someone to notice it.
    derived = declared_generated(repo_root)
    if not derived:
        out.append(
            {
                "severity": "fail",
                "code": "vacuous-derivation",
                "subject": "config_provenance_audit.declared_generated",
                "detail": "the producer scan returned NOTHING — it found no module declaring a config/ key and stamping "
                "_built_at. That is a broken derivation, not an empty generated set; refusing to grade the table against it.",
            }
        )
    for key, producer in sorted(derived.items()):
        if owner_of(key) != RUNTIME_GENERATED:
            out.append(
                {
                    "severity": "fail",
                    "code": "unruled-producer",
                    "subject": key,
                    "detail": f"{producer} declares this key and stamps _built_at — it is generated — but the registry rules it "
                    f"{owner_of(key)!r}. Rule it runtime_generated, and make sure no repo twin ships with it.",
                }
            )

    # 5. A ruling whose subject is neither on disk nor a derived generated key is dead
    #    weight; prune it rather than leave a table describing a tree that moved.
    disk = set(on_disk)
    for ruling in RULINGS:
        if ruling.is_dir_rule:
            if not any(rel.startswith(ruling.subject) for rel in disk):
                out.append(
                    {
                        "severity": "fail",
                        "code": "stale-ruling",
                        "subject": ruling.subject,
                        "detail": "directory rule covers nothing on disk — prune it",
                    }
                )
            continue
        if ruling.subject in disk or ruling.owner == RUNTIME_GENERATED:
            continue  # runtime_generated subjects are S3-only ON PURPOSE (rule 2)
        out.append(
            {
                "severity": "fail",
                "code": "stale-ruling",
                "subject": ruling.subject,
                "detail": "ruling names a file that is not on disk — prune it or restore the file",
            }
        )

    return out


def table(repo_root: str = REPO_ROOT) -> list[dict[str, str]]:
    """The rendered registry: one row per `config/**.json` on disk, plus the S3-only
    generated keys (which have no row on disk BECAUSE they are generated)."""
    rows: list[dict[str, str]] = []
    for rel in config_json_files(repo_root):
        ruling = ruling_for(rel)
        rows.append(
            {
                "subject": rel,
                "owner": ruling.owner if ruling else UNKNOWN,
                "ruled_by": ruling.subject if ruling else "",
                "uploadable": "yes" if uploadable(rel) else "NO",
                "on_disk": "yes",
            }
        )
    for ruling in RULINGS:
        if ruling.owner == RUNTIME_GENERATED and not ruling.is_dir_rule:
            rows.append(
                {
                    "subject": ruling.subject,
                    "owner": ruling.owner,
                    "ruled_by": ruling.subject,
                    "uploadable": "NO",
                    "on_disk": (
                        "no (S3 only — correct)" if not os.path.exists(os.path.join(repo_root, ruling.subject)) else "YES (stale twin!)"
                    ),
                }
            )
    return sorted(rows, key=lambda r: r["subject"])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="config/ ownership registry + audit (#3785)")
    ap.add_argument("--strict", action="store_true", help="exit 1 on any `fail` finding")
    ap.add_argument("--json", action="store_true", help="machine-readable report")
    ap.add_argument("--repo", default=REPO_ROOT)
    args = ap.parse_args(argv)

    rows = table(args.repo)
    found = findings(args.repo)

    if args.json:
        print(json.dumps({"table": rows, "findings": found}, indent=2))
    else:
        print(f"config/ ownership registry — {len(rows)} subjects ({len(RULINGS)} rulings)")
        for row in rows:
            icon = _ICON.get(row["owner"], "?")
            note = "" if row["on_disk"] == "yes" else f"   [{row['on_disk']}]"
            print(f"  {icon} {row['owner']:<18} upload={row['uploadable']:<3} {row['subject']}{note}")
        print()
        if not found:
            print("🟢 every config/ subject is ruled, every generated artifact carries no committed twin")
        for f in found:
            print(f"  {'🔴' if f['severity'] == 'fail' else '🟡'} {f['code']}: {f['subject']}\n      {f['detail']}")

    fails = [f for f in found if f["severity"] == "fail"]
    return 1 if (args.strict and fails) else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
