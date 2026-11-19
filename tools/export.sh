#!/usr/bin/env bash
# Export the Gramps tree twice:
#   gramps-db/full/family-tree.gramps  complete local copy (git-ignored; used by `make report`)
#   tree/family-tree.{gramps,ged}      PUBLIC copy, committed: people tagged
#                                      "anonymous" are anonymized (tools/anonymize.py)
# Usage: tools/export.sh ["Tree Name"]
set -euo pipefail

TREE="${1:-${GRAMPS_TREE:-Family Tree}}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="${PY:-uv run --quiet --project $ROOT python}"
OUT="$ROOT/tree"
FULL="$ROOT/gramps-db/full"
mkdir -p "$OUT" "$FULL"

if pgrep -x gramps >/dev/null || pgrep -f 'gramps/grampsapp|/usr/bin/gramps' >/dev/null; then
  echo "Gramps is running — close it first (the CLI can't open a locked tree)." >&2
  exit 1
fi

tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
quiet() { "$@" 2>&1 | grep -vE '^Gtk-|xapp-gtk3|^Opened successfully|^Exporting|^Importing|^[0-9%A-Za-z ]*Cleaning up\.$' || true; }
strip_header() { sed -i -E 's|<created date="[0-9-]+" |<created |' "$1"; }

# 1. Full export of the real tree
quiet gramps -O "$TREE" -e "$tmp/full.gramps" -f gramps
[[ -s "$tmp/full.gramps" ]] || { echo "Export failed for tree '$TREE'" >&2; exit 1; }
gzip -dc "$tmp/full.gramps" > "$FULL/family-tree.gramps"
strip_header "$FULL/family-tree.gramps"

# 2. Public copy: import into a throwaway Gramps home, anonymize, export
export GRAMPSHOME="$tmp/home"
quiet gramps -C Public -i "$tmp/full.gramps"
$PY "$ROOT/tools/anonymize.py" Public
quiet gramps -O Public -e "$tmp/pub.gramps" -f gramps
quiet gramps -O Public -e "$tmp/pub.ged" -f ged
[[ -s "$tmp/pub.gramps" && -s "$tmp/pub.ged" ]] || { echo "Public export failed" >&2; exit 1; }
gzip -dc "$tmp/pub.gramps" > "$OUT/family-tree.gramps"
strip_header "$OUT/family-tree.gramps"
grep -vE '^1 DATE |^2 TIME |^1 FILE ' "$tmp/pub.ged" > "$OUT/family-tree.ged"

echo "Exported '$TREE' -> gramps-db/full/ (private) and tree/ (public, anonymized)"
git -C "$ROOT" --no-pager diff --stat -- tree/ || true
