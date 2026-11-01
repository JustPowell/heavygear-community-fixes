#!/usr/bin/env bash
# restore.sh - put back a prefix saved by backup.sh.
#   ./restore.sh LABEL        newest backups/HeavyGear-LABEL-prefix-*.tar.zst
#   ./restore.sh FILE.tar.zst
# The current prefix is moved aside (prefix.before-restore-<time>), never deleted.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
project=$(dirname "$here")
games=${HG_HOME:-$HOME/Games/HeavyGear}
backups=${HG_BACKUPS:-$project/backups}
[ $# -eq 1 ] || { sed -n '2,5p' "$0"; exit 1; }
if [ -f "$1" ]; then tarball=$1
else tarball=$(ls -1 "$backups"/HeavyGear-"$1"-prefix-*.tar.zst 2>/dev/null | sort | tail -1 || true); fi
[ -n "$tarball" ] && [ -f "$tarball" ] || { echo "no backup for '$1' in $backups" >&2; exit 1; }
hg_running() { ps -eo stat=,comm= | awk 'tolower($2)=="hg.exe" && $1 !~ /^Z/ {f=1} END {exit !f}'; }
if hg_running; then echo "Heavy Gear is still running - quit it first." >&2; exit 1; fi
WINEPREFIX="$games/prefix" wineserver -k 2>/dev/null || true
echo "Checking $(basename "$tarball")..."
zstd -t -q "$tarball"
mkdir -p "$games"
if [ -e "$games/prefix" ]; then
  aside="$games/prefix.before-restore-$(date +%Y%m%d-%H%M%S)"
  mv "$games/prefix" "$aside"; echo "Current prefix moved to $aside"
fi
zstd -dc "$tarball" | tar -C "$games" -xf -
echo "Restored. Launch with $here/run-heavygear.sh"
