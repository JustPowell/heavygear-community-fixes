#!/usr/bin/env bash
# setup-glide.sh - let Heavy Gear's 3Dfx (Voodoo / Glide) renderer run under Wine, with the particle fix.
#
#   ./setup-glide.sh            install
#   ./setup-glide.sh --no-fix   install, but leave the particle fix switched off (writes glidefix.cfg "nofix")
#   ./setup-glide.sh --remove   take it all out again (files are moved to C:\HeavyGear\_glide_removed)
#
# What ends up in the game folder (C:\HeavyGear):
#   glide2x.dll       our proxy (built here from tools/glidelog): fixes the black particle squares, then
#                     forwards every Glide call to the real driver
#   glide2x_real.dll  the real Glide driver: a wrapper that draws through Direct3D
# The real driver is, in this order:
#   1. the glide2x_real.dll already in the game folder (for example nGlide; left as it is),
#   2. HG_GLIDE_DRIVER=/path/to/glide2x.dll,
#   3. a Glide2x.dll already in the game folder (an older install of this script; it becomes glide2x_real.dll),
#   4. dgVoodoo2's Glide2x.dll from ../wrappers/dgVoodoo2_*.zip, plus DXVK's d3d11.dll and dxgi.dll from
#      ../wrappers/dxvk-*.tar.gz (use dgVoodoo 2.79.x, dege.freeweb.hu; newer releases crash under Wine).
# HG_GLIDE_PROXY=/path/glide2x.dll uses a prebuilt proxy; HG_WRAPPERS overrides the wrappers folder.
# Building the proxy needs clang, lld and llvm (the script says how to install them) and python3.
# Choose "3Dfx" in the game's options screen to use it.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
project=$(dirname "$here")
. "$here/distro.sh"
game="${HG_PREFIX:-$HOME/Games/HeavyGear/prefix}/drive_c/HeavyGear"
wrap="${HG_WRAPPERS:-$project/wrappers}"
removed="$game/_glide_removed"
# Wine treats file names case-insensitively, but the file system does not: find files whatever their case.
gfind() { find "$game" -maxdepth 1 -type f -iname "$1" -print; }

[ -d "$game" ] || { echo "no game in $game" >&2; exit 1; }

if [ "${1:-}" = "--remove" ]; then
    mkdir -p "$removed"
    for pat in 'glide2x.dll' 'glide2x_real.dll' 'glidefix.cfg' 'glidelog.txt' 'd3d11.dll' 'dxgi.dll' 'dgVoodoo.conf'; do
        while IFS= read -r f; do [ -n "$f" ] && mv --backup=numbered "$f" "$removed/"; done < <(gfind "$pat")
    done
    echo "Glide files moved to $removed (delete that folder if you like)."
    exit 0
fi
nofix=0; [ "${1:-}" = "--no-fix" ] && nofix=1

tmp=$(mktemp -d); trap 'rm -rf "$tmp" "$tmp.build.log"' EXIT
# --- 1. Build the proxy first, so a missing tool stops us before anything is touched ----------------
if [ -n "${HG_GLIDE_PROXY:-}" ]; then
    proxy="$HG_GLIDE_PROXY"
    [ -s "$proxy" ] || { echo "HG_GLIDE_PROXY=$proxy not found" >&2; exit 1; }
    echo "== Using the prebuilt proxy $proxy"
else
    for t in clang lld-link llvm-dlltool python3; do
        command -v "$t" >/dev/null 2>&1 || { echo "missing '$t' (needed to build the particle-fix proxy): $(pkg_hint glidebuild)" >&2; exit 1; }
    done
    echo "== Building the proxy (tools/glidelog)"
    "$project/tools/glidelog/build.sh" >"$tmp.build.log" 2>&1 || { cat "$tmp.build.log" >&2; echo "proxy build failed" >&2; exit 1; }
    proxy="$project/tools/glidelog/glide2x.dll"
    [ -s "$proxy" ] || { echo "proxy build failed" >&2; exit 1; }
fi

# --- 2. Make sure the real driver is in place as glide2x_real.dll ---------------------------------------
real="$game/glide2x_real.dll"
driver_note=""
is_proxy() { grep -aq 'glidelog attached' "$1" 2>/dev/null; }
if [ -f "$real" ]; then
    driver_note="kept the existing glide2x_real.dll"
elif [ -n "${HG_GLIDE_DRIVER:-}" ]; then
    [ -f "$HG_GLIDE_DRIVER" ] || { echo "HG_GLIDE_DRIVER=$HG_GLIDE_DRIVER not found" >&2; exit 1; }
    cp -f "$HG_GLIDE_DRIVER" "$real"; driver_note="HG_GLIDE_DRIVER ($(basename "$HG_GLIDE_DRIVER"))"
else
    old=$(gfind 'glide2x.dll' | head -1 || true)
    if [ -n "$old" ] && ! is_proxy "$old"; then
        mv -f "$old" "$real"; driver_note="the Glide2x.dll that was already installed"
    else
        dgv=${HG_DGVOODOO_ZIP:-}
        [ -n "$dgv" ] || dgv=$(ls -1 "$wrap"/dgVoodoo2_7[0-9]*.zip 2>/dev/null | grep -v '_dbg\|_dev' | sort -V | tail -1 || true)
        [ -n "$dgv" ] || dgv=$(ls -1 "$wrap"/dgVoodoo2_*.zip 2>/dev/null | grep -v '_dbg\|_dev' | sort -V | tail -1 || true)
        dxvk=$(ls -1 "$wrap"/dxvk-[0-9]*.tar.gz 2>/dev/null | sort -V | tail -1 || true)
        [ -n "$dgv" ]  || { echo "no Glide driver found. Put dgVoodoo2_*.zip (github.com/dege-diosg/dgVoodoo2/releases) in $wrap," >&2
                            echo "or set HG_GLIDE_DRIVER=/path/to/glide2x.dll (for example nGlide's)." >&2; exit 1; }
        [ -n "$dxvk" ] || { echo "put dxvk-*.tar.gz (github.com/doitsujin/dxvk/releases) in $wrap" >&2; exit 1; }
        unzip -q -o "$dgv" '3Dfx/x86/Glide2x.dll' dgVoodoo.conf -d "$tmp"
        tar -xzf "$dxvk" -C "$tmp" --wildcards '*/x32/d3d11.dll' '*/x32/dxgi.dll'
        cp -f "$tmp/3Dfx/x86/Glide2x.dll" "$real"
        cp -f "$tmp"/dxvk-*/x32/d3d11.dll "$tmp"/dxvk-*/x32/dxgi.dll "$game/"
        # dgVoodoo.conf: defaults (Voodoo 2, 2 TMUs x 4 MB, 640x480 as the game asks) minus the watermarks.
        tr -d '\r' < "$tmp/dgVoodoo.conf" | sed -E \
            -e 's/^(3DfxWatermark[[:space:]]*=).*/\1 false/' \
            -e 's/^(dgVoodooWatermark[[:space:]]*=).*/\1 false/' \
            -e 's/^(3DfxSplashScreen[[:space:]]*=).*/\1 false/' \
            | sed 's/$/\r/' > "$game/dgVoodoo.conf"
        driver_note="dgVoodoo2 $(basename "$dgv") + DXVK $(basename "$dxvk")"
    fi
fi

# --- 3. Put the proxy in place. Any other glide2x.dll (even in another letter case) is moved aside, not deleted. -----
while IFS= read -r f; do
    [ -n "$f" ] || continue
    if is_proxy "$f"; then [ "$f" = "$game/glide2x.dll" ] || rm -f "$f"
    else mkdir -p "$removed"; mv --backup=numbered "$f" "$removed/$(basename "$f")"; fi
done < <(gfind 'glide2x.dll')
cp -f "$proxy" "$game/glide2x.dll"
if [ "$nofix" = 1 ]; then echo "nofix" > "$game/glidefix.cfg"; else rm -f "$game/glidefix.cfg"; fi

echo "Installed into $game:"
echo "  glide2x.dll       particle-fix proxy$([ "$nofix" = 1 ] && echo ' (fix switched OFF)')"
echo "  glide2x_real.dll  $driver_note"
echo "Start the game with run-heavygear.sh and pick 3Dfx in the options screen."
echo "(A file named glidelog.txt in the game folder turns call logging on: tens of MB per mission. Delete it for normal play.)"
