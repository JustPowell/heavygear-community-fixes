#!/usr/bin/env bash
# apply-patches.sh - install the official Heavy Gear 1.1 and 1.2 patches into the Wine prefix.
#
#   ./apply-patches.sh            1.1 then 1.2
#   ./apply-patches.sh 1.1        only 1.1
#   ./apply-patches.sh 1.2        only 1.2 (on top of whatever is installed)
#
# Expects  ../patches/hgp187d/hgp187d.exe  (1.1, RTPatch, internal version 1.87)
#          ../patches/hgpatc12/HGPATC12.EXE (1.2)
# and a 1.0 backup in ../backups (make one with ./backup.sh 1.0; ./restore.sh 1.0 undoes everything).
#
# The patchers are delta patches: they only apply to byte-exact 1.0 files, so the
# frame-limiter / display-mode changes in HGSHELL.DLL / HGSIM.DLL are removed first.
# They find the game through the registry, which our file-copy install never wrote,
# so the keys the original installer would have made are added here.
# HG_DISC1, HG_PATCH11, HG_PATCH12, HG_BACKUPS override those folders; HG_HGFIX is a command that replaces
# "python3 patcher/hgfix.py" (the GUI restores the fixes itself first).
# Each patcher opens its own window: click through it (Proceed / Next / OK).
set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd)
project=$(dirname "$here")
export WINEPREFIX="${HG_PREFIX:-$HOME/Games/HeavyGear/prefix}"
export WINEDEBUG=${WINEDEBUG:--all}
game="$WINEPREFIX/drive_c/HeavyGear"
disc="${HG_DISC1:-$project/HG-DISC-1}/INSTALL/DATA"
p11="${HG_PATCH11:-$project/patches/hgp187d/hgp187d.exe}"
p12="${HG_PATCH12:-$project/patches/hgpatc12/HGPATC12.EXE}"
backups="${HG_BACKUPS:-$project/backups}"
which="${1:-all}"

die() { echo "error: $*" >&2; exit 1; }
md5() { md5sum "$1" | cut -d' ' -f1; }
# The patchers write files in lowercase (hgshell.dll); Wine doesn't care, Linux does.
gfile() { find "$game" -maxdepth 1 -iname "$1" -print -quit; }
gmd5() { local p; p=$(gfile "$1"); if [ -n "$p" ]; then md5 "$p"; else echo missing; fi; }
fix_case() {
    local f p
    for f in HG.EXE HGSHELL.DLL HGSIM.DLL; do
        p=$(gfile "$f")
        if [ -n "$p" ] && [ "$(basename "$p")" != "$f" ]; then mv "$p" "$game/$f"; fi
    done
}
step() { echo; echo "== $*"; }

command -v wine >/dev/null || die "wine not found"
[ -n "$(gfile HG.EXE)" ] || die "no game in $game"
hg_running() { ps -eo stat=,comm= | awk 'tolower($2)=="hg.exe" && $1 !~ /^Z/ {f=1} END {exit !f}'; }
hg_running && die "Heavy Gear is running - quit it first (or: WINEPREFIX=$WINEPREFIX wineserver -k)"
ls "$backups"/HeavyGear-1.0-prefix-*.tar.zst >/dev/null 2>&1 \
    || die "no 1.0 backup in $backups - make one first: $here/backup.sh 1.0"
case "$which" in all|1.1) [ -f "$p11" ] || die "missing $p11";; esac
case "$which" in all|1.2) [ -f "$p12" ] || die "missing $p12";; esac

reg32() { wine reg add "$@" /f /reg:32 >/dev/null; }
version_keys() {
    wine reg query 'HKLM\Software\Activision\Heavy Gear' /reg:32 2>/dev/null \
        | tr -d '\r' | sed -n 's/.*\\Heavy Gear\\//p' | tr '\n' ' '
}

if [ "$which" != 1.2 ]; then
    step "Removing our DLL changes (patchers need the exact 1.0 files)"
    if [ -f "$game/HGSHELL.DLL.orig" ] || [ -f "$game/HGSIM.DLL.orig" ]; then
        if [ -n "${HG_HGFIX:-}" ]; then $HG_HGFIX "$game" --restore; else python3 "$project/patcher/hgfix.py" "$game" --restore; fi
    fi
    rm -f "$game/HG.EXE.orig"
    for f in HG.EXE HGSHELL.DLL HGSIM.DLL; do
        [ "$(gmd5 "$f")" = "$(md5 "$disc/$f")" ] \
            || die "$f is not the 1.0 file from disc 1 - restore with linux/restore.sh 1.0 first"
        echo "   $f = 1.0 original"
    done
fi

step "Registering the install the way the original installer does"
wineserver -k 2>/dev/null || true
reg32 'HKLM\Software\Activision\Heavy Gear' /v EXE /t REG_SZ /d HG.EXE
reg32 'HKLM\Software\Activision\Heavy Gear' /v FTP /t REG_SZ /d HGEARW95
[ -n "$(version_keys)" ] || reg32 'HKLM\Software\Activision\Heavy Gear\1.00'
reg32 'HKLM\Software\Microsoft\Windows\CurrentVersion\App Paths\HG.EXE' /ve /t REG_SZ /d 'C:\HeavyGear\HG.EXE'
reg32 'HKLM\Software\Microsoft\Windows\CurrentVersion\App Paths\HG.EXE' /v Path /t REG_SZ /d 'C:\HeavyGear'
for exe in hgp187d.exe HGPATC12.EXE; do
    wine reg add "HKCU\\Software\\Wine\\AppDefaults\\$exe" /v Version /t REG_SZ /d win98 /f >/dev/null
done
echo "   versions registered: $(version_keys)"

run_patch() {  # name exe
    local before; before=$(gmd5 HGSHELL.DLL)
    step "Running the $1 patcher - click through its window (if it starts the game afterwards, just quit it)"
    ( cd "$(dirname "$2")" && wine "$(basename "$2")" ) || true
    wineserver -w 2>/dev/null || true
    fix_case
    [ -n "$(gfile HGSHELL.DLL)" ] || die "HGSHELL.DLL is missing after the $1 patch - restore with linux/restore.sh 1.0"
    if [ "$(gmd5 HGSHELL.DLL)" = "$before" ]; then
        die "$1 patch didn't change HGSHELL.DLL (cancelled, or it failed). Game folder: $game"
    fi
    echo "   $1 applied. Registered versions now: $(version_keys)"
}

fix_case
case "$which" in all|1.1) run_patch 1.1 "$p11";; esac
case "$which" in all|1.2) run_patch 1.2 "$p12";; esac

step "Recording checksums"
mkdir -p "$backups"
( cd "$game" && find . -maxdepth 1 -type f \( -iname '*.dll' -o -iname '*.exe' -o -iname '*.ini' \) -print0 \
    | sort -z | xargs -0 md5sum ) > "$backups/checksums-patched.md5"
( cd "$game/PLUGIN" 2>/dev/null && md5sum *.DLL *.dll 2>/dev/null ) >> "$backups/checksums-patched.md5" || true
echo "   $backups/checksums-patched.md5"

cat <<EOF

Done. The official patches are installed. Now re-apply the fixes (they detect v1.2):
   python3 $project/patcher/hgfix.py "$game"
WASD controls are untouched. To go back to 1.0:  $here/restore.sh 1.0
EOF
