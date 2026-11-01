#!/usr/bin/env bash
# deploy/www_root_snapshot.sh — a restorable snapshot of the production root pages the v9 build would
# replace, and a NON-destructive rollback rehearsal (owner ask 2026-11-01, #5534, epic #5529).
#
#   capture [--print]        copy every production object at a v9-owned path (www/owned_paths.json: the
#                            static routes' index.html + the files) from s3://$BUCKET/site/ to
#                            s3://$BUCKET/backups/root-snapshots/<UTC stamp>/, and write manifest.json
#                            there (key, ETag, size per object; the absent ones named). Reads site/,
#                            writes only under backups/ — outside the served prefix.
#   verify <stamp>           head every manifest key in the snapshot AND live: the snapshot is intact
#                            (ETags match the manifest) and live is reported changed/unchanged per key.
#   rehearse <stamp>         restore the snapshot into s3://$BUCKET/backups/root-restore-rehearsal/<stamp>/
#                            and compare ETags against the manifest — the restore mechanics, proven,
#                            without touching site/. Never writes under site/.
#   restore <stamp> --apply [--print]
#                            THE ROLLBACK: copy the snapshot back over site/ and invalidate /*.
#                            Refused without --apply (exit 2). --print shows every command and runs none.
#   list                     the snapshots on record.
#
# Every copy is a server-side S3 copy (aws s3 cp --copy-props default): a single-part object keeps its
# ETag, which is what makes the ETag comparisons below a proof and not a hope.
set -euo pipefail
BUCKET="${BUCKET:-matthew-life-platform}"
SITE="site"
SNAPS="backups/root-snapshots"
REHEARSAL="backups/root-restore-rehearsal"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OWNED="${OWNED_PATHS:-$REPO/www/owned_paths.json}"

usage() { sed -n '2,24p' "$0" >&2; exit 3; }
MODE="${1:-}"; shift || true
STAMP=""; APPLY=0; PRINT=0
for a in "$@"; do case "$a" in --apply) APPLY=1 ;; --print) PRINT=1 ;; -*) echo "unknown flag $a" >&2; usage ;; *) STAMP="$a" ;; esac; done

keys() {  # the production keys the v9 build owns, one per line (the prefixes _astro/ and assets/fonts/v9/ do not exist in production)
  python3 - "$OWNED" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
out = []
for r in d.get("static_routes") or []:
    out.append((r.strip("/") + "/index.html").lstrip("/") if r != "/" else "index.html")
out += [f for f in d.get("files") or [] if isinstance(f, str)]
print("\n".join(dict.fromkeys(out)))
PY
}
run() { if [ "$PRINT" = 1 ]; then echo "  \$ $*"; else "$@"; fi; }
head_etag() {  # ETag SIZE or "ABSENT"
  aws s3api head-object --bucket "$BUCKET" --key "$1" --query '[ETag,ContentLength]' --output text 2>/dev/null | tr -d '"' || echo "ABSENT"
}

case "$MODE" in
  capture)
    STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
    DEST="$SNAPS/$STAMP"
    echo "www_root_snapshot: capture → s3://$BUCKET/$DEST/  (reads $SITE/, writes only under backups/)"
    manifest="$(mktemp)"; echo "{\"stamp\": \"$STAMP\", \"bucket\": \"$BUCKET\", \"source_prefix\": \"$SITE/\", \"objects\": [" > "$manifest"
    n=0; absent=()
    while IFS= read -r key; do
      [ -n "$key" ] || continue
      info="$(head_etag "$SITE/$key")"
      if [ "$info" = "ABSENT" ]; then absent+=("$key"); echo "  – $key (absent in production — nothing to snapshot)"; continue; fi
      etag="${info%%	*}"; size="${info##*	}"
      run aws s3 cp "s3://$BUCKET/$SITE/$key" "s3://$BUCKET/$DEST/$key" --only-show-errors
      [ "$n" -gt 0 ] && echo "," >> "$manifest"
      printf '  {"key": "%s", "etag": "%s", "size": %s}' "$key" "$etag" "$size" >> "$manifest"; n=$((n+1))
      echo "  ✓ $key  ($size bytes, $etag)"
    done < <(keys)
    printf '\n], "absent": [%s], "captured_at": "%s"}\n' "$(printf '"%s",' "${absent[@]}" | sed 's/,$//')" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$manifest"
    if [ "$PRINT" = 1 ]; then echo "  \$ aws s3 cp <manifest> s3://$BUCKET/$DEST/manifest.json"; cat "$manifest"; else aws s3 cp "$manifest" "s3://$BUCKET/$DEST/manifest.json" --only-show-errors; fi
    echo "www_root_snapshot: $n object(s) captured, ${#absent[@]} absent · stamp $STAMP"
    ;;
  verify|rehearse|restore)
    [ -n "$STAMP" ] || { echo "www_root_snapshot: $MODE needs a <stamp>" >&2; exit 3; }
    SRC="$SNAPS/$STAMP"
    if [ "$MODE" = restore ] && [ "$APPLY" != 1 ]; then
      echo "www_root_snapshot: REFUSED — restore writes over $SITE/; pass --apply (owner-authorised) to run it" >&2; exit 2
    fi
    if [ "$MODE" = restore ] && [ "$PRINT" = 1 ]; then
      echo "www_root_snapshot: restore $STAMP → s3://$BUCKET/$SITE/ — PRINT ONLY, nothing runs"
      echo "  \$ aws s3 sync s3://$BUCKET/$SRC/ s3://$BUCKET/$SITE/ --exclude manifest.json --only-show-errors   # no delete; snapshot keys only"
      echo "  \$ DIST_ID=\$(aws cloudformation describe-stacks --region us-east-1 --stack-name LifePlatformWeb --query \"Stacks[0].Outputs[?OutputKey=='AmjDistributionId'].OutputValue\" --output text)"
      echo "  \$ aws cloudfront create-invalidation --distribution-id \$DIST_ID --paths '/*'"
      exit 0
    fi
    manifest="$(aws s3 cp "s3://$BUCKET/$SRC/manifest.json" - 2>/dev/null)" || { echo "www_root_snapshot: no manifest at s3://$BUCKET/$SRC/" >&2; exit 4; }
    if [ "$MODE" = rehearse ]; then
      DEST="$REHEARSAL/$STAMP"
      echo "www_root_snapshot: rehearse $STAMP → s3://$BUCKET/$DEST/  (the restore mechanics, against a scratch prefix; $SITE/ untouched)"
      aws s3 sync "s3://$BUCKET/$SRC/" "s3://$BUCKET/$DEST/" --exclude manifest.json --only-show-errors
    fi
    bad=0; changed=0; total=0
    while IFS=$'\t' read -r key etag; do
      [ -n "$key" ] || continue; total=$((total+1))
      snap="$(head_etag "$SRC/$key")"; snap="${snap%%	*}"
      [ "$snap" = "$etag" ] || { echo "  ✗ snapshot $key: ETag $snap ≠ manifest $etag"; bad=$((bad+1)); }
      if [ "$MODE" = rehearse ]; then
        got="$(head_etag "$REHEARSAL/$STAMP/$key")"; got="${got%%	*}"
        [ "$got" = "$etag" ] && echo "  ✓ restored (rehearsal) $key" || { echo "  ✗ rehearsal $key: ETag $got ≠ $etag"; bad=$((bad+1)); }
      else
        live="$(head_etag "$SITE/$key")"; live="${live%%	*}"
        if [ "$live" = "$etag" ]; then echo "  ✓ $key  live unchanged since capture"; else echo "  ~ $key  live CHANGED since capture (live $live)"; changed=$((changed+1)); fi
      fi
    done < <(mf="$(mktemp)"; printf '%s' "$manifest" > "$mf"; python3 -c 'import json,sys; m=json.load(open(sys.argv[1])); [print(o["key"] + "\t" + o["etag"]) for o in m["objects"]]' "$mf"; rm -f "$mf")
    if [ "$MODE" = restore ]; then
      echo "www_root_snapshot: RESTORE $STAMP → s3://$BUCKET/$SITE/"
      aws s3 sync "s3://$BUCKET/$SRC/" "s3://$BUCKET/$SITE/" --exclude manifest.json --only-show-errors
      DIST_ID=$(aws cloudformation describe-stacks --region us-east-1 --stack-name LifePlatformWeb --query "Stacks[0].Outputs[?OutputKey=='AmjDistributionId'].OutputValue" --output text)
      aws cloudfront create-invalidation --distribution-id "$DIST_ID" --paths '/*' --query Invalidation.Id --output text
    fi
    echo "www_root_snapshot: $MODE $STAMP — $total object(s), $bad problem(s)$( [ "$MODE" = verify ] && echo ", $changed changed live since capture" )"
    [ "$bad" = 0 ]
    ;;
  list) aws s3 ls "s3://$BUCKET/$SNAPS/" ;;
  *) usage ;;
esac
