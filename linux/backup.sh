#!/usr/bin/env bash
# backup.sh - save the whole Heavy Gear Wine prefix (game, saves, settings) to backups/.
#   ./backup.sh [LABEL]        e.g. ./backup.sh 1.0   ->  backups/HeavyGear-1.0-prefix-<date>.tar.zst
# Restore with ./restore.sh LABEL.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
project=$(dirname "$here")
games=${HG_HOME:-$HOME/Games/HeavyGear}
label=${1:-backup}
command -v zstd >/dev/null || { echo "zstd is needed" >&2; exit 1; }
[ -d "$games/prefix" ] || { echo "no prefix in $games" >&2; exit 1; }
hg_running() { ps -eo stat=,comm= | awk 'tolower($2)=="hg.exe" && $1 !~ /^Z/ {f=1} END {exit !f}'; }
if hg_running; then echo "Heavy Gear is still running - quit it first." >&2; exit 1; fi
WINEPREFIX="$games/prefix" wineserver -w 2>/dev/null || true
backups=${HG_BACKUPS:-$project/backups}
mkdir -p "$backups"
out="$backups/HeavyGear-$label-prefix-$(date +%Y%m%d-%H%M%S).tar.zst"
tar -C "$games" -cf - prefix | zstd -q -T0 -o "$out"
( cd "$games/prefix/drive_c/HeavyGear" && find . -maxdepth 2 -type f \( -iname '*.dll' -o -iname '*.exe' \) \
    -print0 | sort -z | xargs -0 md5sum ) > "$backups/checksums-$label.md5"
echo "Saved $out ($(du -h "$out" | cut -f1))"
