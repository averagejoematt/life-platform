#!/usr/bin/env python3
"""scripts/chronicle_revision_apply.py — apply a publication revision manifest to the chronicle's stores.

WHY (owner ruling 2026-11-05). Published chronicle installments and everything derived from them
(the journal post pages, the reading manifest, the RSS copies, the share kits, the v9 chapter and
Day pages, the story list, the recap, the recall snippets, the legacy archive copies) carried
statements the owner has since ruled private. A natural run rewrites none of them: a published
installment is stored once and copied many times. This script applies a REVISION MANIFEST — a
private JSON file built outside the repo that names, for every passage, every object it sits in
and the exact text to put in its place — and keeps the originals privately.

THE MANIFEST IS THE ONLY SOURCE OF TEXT. This file holds no chronicle text. Everything it writes
comes from the manifest given on the command line, and the manifest never enters the repo.

MODES
  (default) dry-run   read every target (read-only), check that each `find` still occurs exactly
                      `count` times, and print the plan — object, edits, replacements. Nothing is
                      written. --offline skips AWS entirely and prints the plan from the manifest.
  --apply             preflight as above; if ANY target no longer matches, refuse (exit 3) before
                      the first write. Otherwise, per target:
                        * S3 object: copy the original bytes to <backup_prefix>s3/<key>, then write
                          the revised body with the object's own ContentType / CacheControl /
                          Metadata;
                        * DynamoDB item: write the whole original item (DynamoDB JSON, lossless) to
                          <backup_prefix>ddb/<pk>/<sk>.json, then UPDATE only the changed top-level
                          attributes — conditional on each still holding its original value — and
                          append a publication revision record to the item's `revisions` list:
                          {at, reason, backup_ref, fields}. The record carries no text;
                      then a revision log (key, sha256 before/after, counts — no text) is written to
                      <backup_prefix>revision_log/<stamp>.json and CloudFront is invalidated for
                      every public path touched (--no-invalidate to skip).
  --verify            re-fetch every public URL the manifest lists and fail (exit 1) if any listed
                      original phrase is still served. A URL marked `pending_owner_decision` (a page
                      that embeds audio the owner has not ruled on) reports HELD, not FAIL, unless
                      --strict.

SAFETY
  * The backup prefix must not be under a public prefix (`site/`, `generated/`) — refused otherwise.
  * An object with a Content-Encoding (compressed bytes) is refused: the edit is text-level.
  * Every `find` must occur exactly `count` times in the current object/attribute; a mismatch means
    the object changed since the manifest was built — rebuild the manifest, never guess.
  * The `revisions` field is written only to DynamoDB rows. No public route serialises it
    (tests/test_chronicle_revision_apply.py pins that: the chapter route projects named fields,
    the recap route and the publisher read named fields, and nothing in lambdas/web reads it).

    python3 scripts/chronicle_revision_apply.py --manifest <private>/chronicle_revision_manifest.json
    python3 scripts/chronicle_revision_apply.py --manifest <...> --apply
    python3 scripts/chronicle_revision_apply.py --manifest <...> --verify

Exit codes: 0 ok · 1 verify failed · 2 bad manifest · 3 preflight mismatch (nothing written).
The --apply run is an S3 + DynamoDB + CloudFront write: owner-attended (CLAUDE.md, the ask list).
"""

from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import html
import json
import re
import sys
import urllib.error
import urllib.request
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

SCHEMA = "chronicle-revision/v1"
PUBLIC_PREFIXES = ("site/", "generated/")
REVISIONS_ATTR = "revisions"
USER_AGENT = "Mozilla/5.0 (chronicle-revision-verify)"


class ManifestError(Exception):
    """The manifest is malformed or unsafe — nothing is read or written."""


class Mismatch(Exception):
    """A target no longer carries the text the manifest expects — nothing is written."""


# ── manifest ──────────────────────────────────────────────────────────────────────────────


def load_manifest(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        m = json.load(f)
    validate(m)
    return m


def validate(m: dict) -> None:
    if not isinstance(m, dict) or m.get("schema") != SCHEMA:
        raise ManifestError(f"schema must be {SCHEMA!r}")
    for k in ("bucket", "table", "backup_prefix", "reason", "passages"):
        if not m.get(k):
            raise ManifestError(f"manifest is missing {k!r}")
    bp = str(m["backup_prefix"])
    if not bp.endswith("/") or bp.startswith(PUBLIC_PREFIXES) or bp.startswith("/"):
        raise ManifestError(f"backup_prefix {bp!r} must be a private prefix ending in '/' (never under {PUBLIC_PREFIXES})")
    for p in m["passages"]:
        for loc in p.get("locations", []):
            store = loc.get("store")
            if store == "s3":
                if not loc.get("key") or "find" not in loc or "replace" not in loc:
                    raise ManifestError(f"passage {p.get('id')}: s3 location needs key/find/replace")
                if str(loc["key"]).startswith(bp):
                    raise ManifestError(f"passage {p.get('id')}: a target sits under the backup prefix")
            elif store == "ddb":
                if not loc.get("pk") or not loc.get("sk") or not isinstance(loc.get("path"), list) or not loc["path"]:
                    raise ManifestError(f"passage {p.get('id')}: ddb location needs pk/sk/path")
                if loc.get("op", "replace") == "replace" and ("find" not in loc or "replace" not in loc):
                    raise ManifestError(f"passage {p.get('id')}: ddb replace needs find/replace")
                if loc.get("op") == "remove_list_item" and "expect" not in loc:
                    raise ManifestError(f"passage {p.get('id')}: remove_list_item needs expect")
                if loc["path"][0] == REVISIONS_ATTR:
                    raise ManifestError("the revisions attribute is written by this script, never edited")
            else:
                raise ManifestError(f"passage {p.get('id')}: unknown store {store!r}")
            if loc.get("find") == "":
                raise ManifestError(f"passage {p.get('id')}: empty find")


def plan(m: dict) -> Tuple["OrderedDict[str, list]", "OrderedDict[Tuple[str, str], list]"]:
    """(s3 edits by key, ddb edits by (pk, sk)), each in manifest order, tagged with their passage id."""
    s3: "OrderedDict[str, list]" = OrderedDict()
    ddb: "OrderedDict[Tuple[str, str], list]" = OrderedDict()
    for p in m["passages"]:
        for loc in p.get("locations", []):
            e = dict(loc, passage=p.get("id"))
            if loc["store"] == "s3":
                s3.setdefault(loc["key"], []).append(e)
            else:
                ddb.setdefault((loc["pk"], loc["sk"]), []).append(e)
    return s3, ddb


# ── pure text edits ───────────────────────────────────────────────────────────────────────


def apply_text(text: str, edits: List[dict], where: str) -> Tuple[str, int]:
    """Every edit's `find` must occur exactly `count` times (default 1), checked against the text as
    the previous edits left it. Returns (new_text, replacements)."""
    n = 0
    for e in edits:
        want = int(e.get("count", 1))
        have = text.count(e["find"])
        if have != want:
            raise Mismatch(f"{where}: passage {e.get('passage')} expects {want} occurrence(s), found {have}")
        text = text.replace(e["find"], e["replace"])
        n += want
    return text, n


def _get_path(node: Any, path: List[Any]) -> Any:
    for k in path:
        node = node[k]
    return node


def _set_path(node: Any, path: List[Any], value: Any) -> None:
    for k in path[:-1]:
        node = node[k]
    node[path[-1]] = value


def apply_item(item: dict, edits: List[dict], where: str) -> Tuple[dict, List[str], int]:
    """(new_item, changed top-level attributes, replacements). List-item removals run after the text
    edits, highest index first, each checked against its expected original."""
    new = copy.deepcopy(item)
    changed: List[str] = []
    n = 0
    removals = []
    for e in edits:
        path = list(e["path"])
        if e.get("op") == "remove_list_item":
            removals.append(e)
            continue
        try:
            cur = _get_path(new, path)
        except (KeyError, IndexError, TypeError):
            raise Mismatch(f"{where}: passage {e.get('passage')} path {path} is missing")
        if not isinstance(cur, str):
            raise Mismatch(f"{where}: passage {e.get('passage')} path {path} is not text")
        out, k = apply_text(cur, [e], f"{where}.{'.'.join(map(str, path))}")
        _set_path(new, path, out)
        n += k
        if path[0] not in changed:
            changed.append(path[0])
    for e in sorted(removals, key=lambda x: list(x["path"])[-1], reverse=True):
        path = list(e["path"])
        try:
            parent = _get_path(new, path[:-1])
            cur = parent[path[-1]]
        except (KeyError, IndexError, TypeError):
            raise Mismatch(f"{where}: passage {e.get('passage')} list item {path} is missing")
        if not isinstance(parent, list) or cur != e["expect"]:
            raise Mismatch(f"{where}: passage {e.get('passage')} list item {path} no longer holds the expected text")
        del parent[path[-1]]
        n += 1
        if path[0] not in changed:
            changed.append(path[0])
    return new, changed, n


# ── backups ───────────────────────────────────────────────────────────────────────────────


def _safe(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._=-]+", "_", s)


def ddb_backup_key(prefix: str, pk: str, sk: str) -> str:
    return f"{prefix}ddb/{_safe(pk)}/{_safe(sk)}.json"


def s3_backup_key(prefix: str, key: str) -> str:
    return f"{prefix}s3/{key}"


def ddb_json(item: dict) -> str:
    """The item as DynamoDB JSON (lossless: numbers stay strings, sets stay sets, binary is base64)."""
    from boto3.dynamodb.types import TypeSerializer

    ser = TypeSerializer()

    def fix(v):
        if isinstance(v, dict):
            return {k: fix(x) for k, x in v.items()}
        if isinstance(v, list):
            return [fix(x) for x in v]
        if isinstance(v, (bytes, bytearray)):
            return base64.b64encode(bytes(v)).decode("ascii")
        if hasattr(v, "value") and isinstance(getattr(v, "value"), (bytes, bytearray)):  # boto3 Binary
            return base64.b64encode(bytes(v.value)).decode("ascii")
        return v

    return json.dumps({"Item": fix({k: ser.serialize(v) for k, v in item.items()})}, ensure_ascii=False, sort_keys=True)


def revision_record(reason: str, backup_ref: str, fields: List[str], now: str) -> dict:
    return {"at": now, "reason": reason, "backup_ref": backup_ref, "fields": list(fields)}


# ── public paths ──────────────────────────────────────────────────────────────────────────


def invalidation_paths(s3_edits: Dict[str, list]) -> List[str]:
    out = []
    for key, edits in s3_edits.items():
        p = next((e.get("public_path") for e in edits if e.get("public_path")), None)
        if not p:
            continue
        out.append(p)
        if p.endswith("/"):
            out.append(p + "index.html")
    return sorted(set(out))


# ── run ───────────────────────────────────────────────────────────────────────────────────


def preflight(m: dict, s3, table) -> Tuple[list, list]:
    """Read every target and compute its revision. Raises Mismatch on the first stale target."""
    s3_edits, ddb_edits = plan(m)
    s3_out, ddb_out = [], []
    for key, edits in s3_edits.items():
        obj = s3.get_object(Bucket=m["bucket"], Key=key)
        if obj.get("ContentEncoding"):
            raise Mismatch(f"s3:{key}: has Content-Encoding {obj['ContentEncoding']!r}; a text edit would corrupt it")
        raw = obj["Body"].read()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            raise Mismatch(f"s3:{key}: not UTF-8 text")
        new, n = apply_text(text, edits, f"s3:{key}")
        s3_out.append({"key": key, "raw": raw, "new": new.encode("utf-8"), "n": n, "edits": edits, "head": obj})
    for (pk, sk), edits in ddb_edits.items():
        item = table.get_item(Key={"pk": pk, "sk": sk}, ConsistentRead=True).get("Item")
        if not item:
            raise Mismatch(f"ddb:{sk}: item is missing")
        new, changed, n = apply_item(item, edits, f"ddb:{sk}")
        ddb_out.append({"pk": pk, "sk": sk, "old": item, "new": new, "changed": changed, "n": n, "edits": edits})
    return s3_out, ddb_out


def apply(m: dict, s3, table, cf=None, *, invalidate: bool = True, now: Optional[str] = None, log: Callable = print) -> dict:
    now = now or datetime.now(timezone.utc).isoformat()
    stamp = datetime.fromisoformat(now.replace("Z", "+00:00")).astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    s3_out, ddb_out = preflight(m, s3, table)  # raises before any write
    bucket, prefix, reason = m["bucket"], m["backup_prefix"], m["reason"]
    rlog = {"reason": reason, "at": now, "s3": [], "ddb": []}
    for t in s3_out:
        bkey = s3_backup_key(prefix, t["key"])
        head = t["head"]
        s3.put_object(
            Bucket=bucket,
            Key=bkey,
            Body=t["raw"],
            ContentType=head.get("ContentType") or "application/octet-stream",
            Metadata={"source-key": t["key"]},
        )
        kw = {"Bucket": bucket, "Key": t["key"], "Body": t["new"], "ContentType": head.get("ContentType") or "application/octet-stream"}
        if head.get("CacheControl"):
            kw["CacheControl"] = head["CacheControl"]
        if head.get("Metadata"):
            kw["Metadata"] = head["Metadata"]
        s3.put_object(**kw)
        rlog["s3"].append(
            {
                "key": t["key"],
                "backup": bkey,
                "replacements": t["n"],
                "sha256_before": hashlib.sha256(t["raw"]).hexdigest(),
                "sha256_after": hashlib.sha256(t["new"]).hexdigest(),
            }
        )
        log(f"S3   {t['key']}: {t['n']} replacement(s); original -> s3://{bucket}/{bkey}")
    for t in ddb_out:
        bkey = ddb_backup_key(prefix, t["pk"], t["sk"])
        s3.put_object(Bucket=bucket, Key=bkey, Body=ddb_json(t["old"]).encode("utf-8"), ContentType="application/json")
        rec = revision_record(reason, f"s3://{bucket}/{bkey}", t["changed"], now)
        names, values, sets, conds = {"#rev": REVISIONS_ATTR}, {":rev": [rec], ":empty": []}, [], []
        for i, attr in enumerate(t["changed"]):
            names[f"#a{i}"] = attr
            values[f":n{i}"] = t["new"][attr] if attr in t["new"] else None
            values[f":o{i}"] = t["old"][attr]
            sets.append(f"#a{i} = :n{i}")
            conds.append(f"#a{i} = :o{i}")
        try:
            table.update_item(
                Key={"pk": t["pk"], "sk": t["sk"]},
                UpdateExpression="SET " + ", ".join(sets + ["#rev = list_append(if_not_exists(#rev, :empty), :rev)"]),
                ConditionExpression=" AND ".join(conds),
                ExpressionAttributeNames=names,
                ExpressionAttributeValues=values,
            )
        except Exception as e:  # noqa: BLE001 — a row changed between preflight and write: stop, say what was done
            log(
                f"STOPPED at ddb:{t['sk']} ({type(e).__name__}); {len(rlog['s3'])} S3 object(s) and {len(rlog['ddb'])} item(s) already revised"
            )
            s3.put_object(
                Bucket=bucket,
                Key=f"{prefix}revision_log/{stamp}.partial.json",
                Body=json.dumps(rlog, indent=1).encode("utf-8"),
                ContentType="application/json",
            )
            raise Mismatch(f"ddb:{t['sk']}: changed between preflight and write ({e})") from e
        rlog["ddb"].append({"pk": t["pk"], "sk": t["sk"], "fields": t["changed"], "replacements": t["n"], "backup": bkey})
        log(f"DDB  {t['sk']}: {t['n']} replacement(s) in {', '.join(t['changed'])}; original -> s3://{bucket}/{bkey}")
    log_key = f"{prefix}revision_log/{stamp}.json"
    s3.put_object(Bucket=bucket, Key=log_key, Body=json.dumps(rlog, indent=1).encode("utf-8"), ContentType="application/json")
    log(f"revision log -> s3://{bucket}/{log_key}")
    paths = invalidation_paths(plan(m)[0])
    if invalidate and paths and cf is not None:
        inv = cf.create_invalidation(
            DistributionId=m.get("distribution"),
            InvalidationBatch={"Paths": {"Quantity": len(paths), "Items": paths}, "CallerReference": f"chronicle-revision-{stamp}"},
        )
        log(f"invalidation {inv['Invalidation']['Id']} for {len(paths)} path(s)")
    rlog["invalidated"] = paths if (invalidate and cf is not None) else []
    return rlog


# ── verify ────────────────────────────────────────────────────────────────────────────────


def served_forms(body: str) -> List[str]:
    """The ways a phrase can sit in a served body: as served, as rendered text, as decoded JSON text."""
    rendered = html.unescape(re.sub(r"<[^>]+>", " ", body))
    inline = html.unescape(re.sub(r"<[^>]+>", "", body))  # markup inside a phrase (<em>, <a>) must not hide it
    decoded = re.sub(r"\\u([0-9a-fA-F]{4})", lambda mm: chr(int(mm.group(1), 16)), body).replace('\\"', '"').replace("\\n", " ")
    return [re.sub(r"\s+", " ", x) for x in (body, rendered, inline, html.unescape(decoded))]


def _norm_phrase(p: str) -> str:
    """Whitespace-collapsed, typographic apostrophe folded, case-folded: a sentence-initial capital must not hide it."""
    return re.sub(r"\s+", " ", p).replace("’", "'").casefold()


def verify(m: dict, fetch: Callable[[str], str], *, strict: bool = False, log: Callable = print) -> int:
    fails = held = ok = 0
    for v in m.get("verify", []):
        url, phrases = v["url"], v.get("phrases") or []
        try:
            body = fetch(url)
        except Exception as e:  # noqa: BLE001 — a fetch failure is reported, never read as clean
            log(f"ERROR {url}: {e}")
            fails += 1
            continue
        forms = [f.replace("’", "'").casefold() for f in served_forms(body)]
        still = [p for p in phrases if any(_norm_phrase(p) in f for f in forms)]
        if not still:
            ok += 1
            continue
        # A page pending an owner decision may keep ONLY the phrases its undecided audio speaks (held_phrases);
        # any other remaining phrase is a failed revision, decision or not.
        waiting = set(v.get("held_phrases") or []) if v.get("pending_owner_decision") else set()
        unexpected = [p for p in still if p not in waiting]
        if not unexpected and not strict:
            held += 1
            log(f"HELD  {url}: {len(still)} phrase(s) remain until owner decision {v['pending_owner_decision']}")
            continue
        fails += 1
        log(f"FAIL  {url}: {len(unexpected) if not strict else len(still)} original phrase(s) still served")
    log(f"verify: {ok} clean, {held} held, {fails} failing of {len(m.get('verify', []))} URL(s)")
    return 1 if fails else 0


def http_fetch(url: str, timeout: float = 30.0) -> str:
    sep = "&" if "?" in url else "?"
    req = urllib.request.Request(
        url + sep + "rev=" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S"), headers={"User-Agent": USER_AGENT}
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 — https URLs from the manifest
        return r.read().decode("utf-8", "replace")


# ── CLI ───────────────────────────────────────────────────────────────────────────────────


def print_plan(m: dict, log: Callable = print) -> None:
    s3_edits, ddb_edits = plan(m)
    for key, edits in s3_edits.items():
        log(
            f"S3   {key}: {len(edits)} edit(s), {sum(int(e.get('count', 1)) for e in edits)} replacement(s) [{', '.join(sorted({e['passage'] for e in edits}))}]"
        )
    for (pk, sk), edits in ddb_edits.items():
        log(f"DDB  {sk}: {len(edits)} edit(s) [{', '.join(sorted({e['passage'] for e in edits}))}]")
    log(f"plan: {len(m['passages'])} passage(s), {len(s3_edits)} S3 object(s), {len(ddb_edits)} DynamoDB item(s)")
    for a in m.get("audio", []):
        log(f"AUDIO {a.get('id')}: {a.get('recommendation')} — not applied by this script (owner decision)")
    for step in m.get("regeneration", []):
        log(f"REGEN {step}")


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifest", required=True, help="the private revision manifest (JSON)")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="back up, write, record and invalidate (owner-attended)")
    mode.add_argument("--verify", action="store_true", help="re-fetch the public URLs and fail if an original phrase is served")
    ap.add_argument("--offline", action="store_true", help="dry-run without any AWS read")
    ap.add_argument("--no-invalidate", action="store_true", help="skip the CloudFront invalidation on --apply")
    ap.add_argument("--strict", action="store_true", help="--verify: a page pending an owner decision fails too")
    args = ap.parse_args(argv)
    try:
        m = load_manifest(args.manifest)
    except (ManifestError, OSError, json.JSONDecodeError) as e:
        print(f"BAD MANIFEST — {e}")
        return 2
    if args.verify:
        return verify(m, http_fetch, strict=args.strict)
    print_plan(m)
    if args.offline and not args.apply:
        print("dry-run (offline): nothing read, nothing written.")
        return 0
    import boto3

    s3 = boto3.client("s3", region_name=m.get("region", "us-west-2"))
    table = boto3.resource("dynamodb", region_name=m.get("region", "us-west-2")).Table(m["table"])
    try:
        if not args.apply:
            s3_out, ddb_out = preflight(m, s3, table)
            print(f"preflight: {len(s3_out)} S3 object(s) and {len(ddb_out)} DynamoDB item(s) match the manifest")
            print("dry-run: nothing written. Re-run with --apply to back up, write, record and invalidate.")
            return 0
        cf = None if args.no_invalidate else boto3.client("cloudfront")
        apply(m, s3, table, cf, invalidate=not args.no_invalidate)
    except Mismatch as e:
        print(f"REFUSED — {e} (nothing written)")
        return 3
    print("applied. Run the regeneration steps above, then --verify.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
