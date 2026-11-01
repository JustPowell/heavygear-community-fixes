#!/usr/bin/env bash
# run-heavygear.sh - launch Heavy Gear under Wine.
#
# By default the game runs inside gamescope (if installed), which scales its 640x480 screen
# to fill your monitor instead of leaving it tiny in the top-left corner.
#
# Environment options:
#   HG_PREFIX=DIR        Wine prefix (default ~/Games/HeavyGear/prefix)
#   HG_GAMESCOPE=0       don't use gamescope
#   HG_VDESKTOP=0        inside gamescope, don't wrap the game in a Wine virtual desktop
#   HG_RES=640x480       resolution the game sees inside gamescope (default 640x480, or the
#                        size in the game folder's hgd3d9.res: see "Direct3D 9 renderer at a higher resolution" below)
#   HG_SCALE=integer     gamescope scaling: integer (crisp, default), fit, stretch, fill (fit with hgd3d9.res)
#   HG_FILTER=nearest    gamescope filter: nearest (default), linear, fsr, nis, pixel (linear with hgd3d9.res)
#   HG_FPS=30            cap what gamescope displays (game speed is fixed by patcher/hgfix.py)
#   HG_WINDOW=1280x960   inside gamescope: show the game in a window of this size, not full screen
#   HG_DESKTOP=1024x768  no gamescope: run in a Wine virtual-desktop window of this size
#   HG_DGVOODOO=1        use dgVoodoo2 DLLs placed in C:\HeavyGear
#   HG_DEBUG=video       extra logging for video playback problems
#   HG_DEBUG=<channels>  any WINEDEBUG channel list
#   HG_DISC2=DIR         folder holding disc 2 when the real disc isn't mounted (default HG-DISC-2 in the project)
#   HG_WATCH=0          don't watch for HG.EXE exiting (Wine may linger after a crash)
# With the 'borderless' fix (patcher/hgfix.py) the game makes its own borderless full-screen window and scales itself:
# gamescope is not used, and there is no virtual desktop unless HG_DESKTOP asks for one. EmulateModeset is set only
# when DLLFILE.INI selects DX5DRAW (it switches to 640x480 itself), so Wine scales its missions. With 3DFXGEAR under
# nGlide, nGlide is told to render at the desktop's resolution in 4:3 (NGLIDE_RESOLUTION=1, NGLIDE_ASPECT=1, unless
# already set); with another Glide driver (dgVoodoo2) emulated modes are used as for DX5DRAW.
# Ctrl+C in the terminal stops the game and Wine.
# Wine's messages go to ~/Games/HeavyGear/heavygear.log (next to the prefix), not the terminal.
set -u
here="$(cd "$(dirname "$0")" && pwd)"
. "$here/distro.sh"
project="$(cd "$here/.." && pwd)"
export WINEPREFIX="${HG_PREFIX:-$HOME/Games/HeavyGear/prefix}"
game="$WINEPREFIX/drive_c/HeavyGear"
dos="$WINEPREFIX/dosdevices"
[ -f "$game/HG.EXE" ] || { echo "Heavy Gear isn't installed in $WINEPREFIX - run setup-heavygear-wine.sh first" >&2; exit 1; }
log="$(dirname "$WINEPREFIX")/heavygear.log"
# Some tools export this (Claude Code does); Wine then won't look for HG.EXE in the game folder and
# shows an empty desktop.
unset NoDefaultCurrentDirectoryInExePath
if [ -n "${HG_WINDOW:-}" ] && ! [[ "$HG_WINDOW" =~ ^[1-9][0-9]*x[1-9][0-9]*$ ]]; then
  echo "HG_WINDOW must be WIDTHxHEIGHT, e.g. 1280x960 (got '$HG_WINDOW')" >&2; exit 1
fi
case "${HG_DEBUG:-}" in
  "")    export WINEDEBUG="err+all,fixme-all" ;;
  video) export WINEDEBUG="err+all,fixme-all,warn+quartz,warn+strmbase,+msvideo,warn+gstreamer,warn+ir50_32,warn+amstream,warn+ddraw" ;;
  *)     export WINEDEBUG="$HG_DEBUG" ;;
esac

# --- Drive D: = disc 2 ------------------------------------------------------------
# The music on disc 2 is CD audio, which only exists on the real disc. If disc 2 is in a
# drive, point D: at it so music works; otherwise fall back to the copied folder.
disc_mnt=""; disc_dev=""
while read -r src tgt; do
  tgt="$(printf '%b' "$tgt")"; src="$(printf '%b' "$src")"
  if [ -n "$(find "$tgt" -maxdepth 2 -iname 'b51movie.avi' -print -quit 2>/dev/null)" ]; then
    disc_mnt="$tgt"; disc_dev="$src"; break
  fi
done < <(findmnt -rn -o SOURCE,TARGET -t iso9660,udf 2>/dev/null)

if [ -n "$disc_mnt" ]; then
  echo "Heavy Gear disc 2 found in $disc_dev - using it as D: (CD music enabled)"
  ln -sfn "$disc_mnt" "$dos/d:"
  ln -sfn "$disc_dev" "$dos/d::"
else
  echo "Disc 2 not in a drive - using the copied folder as D: (no CD music)"
  ln -sfn "${HG_DISC2:-$project/HG-DISC-2}" "$dos/d:"
  rm -f "$dos/d::"
fi

if [ -n "${HG_DGVOODOO:-}" ]; then
  export WINEDLLOVERRIDES="ddraw,d3dimm,glide,glide2x,glide3x=n,b;${WINEDLLOVERRIDES:-}"
fi
# 3Dfx renderer (setup-glide.sh): dgVoodoo's Glide driver draws through Direct3D 11, which runs
# best on DXVK's d3d11/dxgi placed in the game folder. Prefer those copies when they're there.
if [ -n "$(find "$game" -maxdepth 1 -type f -iname glide2x.dll -print -quit)" ] && [ -f "$game/d3d11.dll" ]; then
  export WINEDLLOVERRIDES="d3d11,dxgi=n,b;${WINEDLLOVERRIDES:-}"
  export DXVK_LOG_PATH="${DXVK_LOG_PATH:-$(dirname "$WINEPREFIX")}"
fi

# hgd3d9 (renderer/hgd3d9) plus a native DXVK d3d9.dll makes the cutscenes after a mission play blank (renderer/hgd3d9/OPTIONS.md).
if [ -f "$game/PLUGIN/3dfx_hgd3d9.dll" ] && [ -f "$game/d3d9.dll" ]; then
  echo "Note: $game/d3d9.dll (DXVK) makes cutscenes after missions blank with the hgd3d9 renderer; rename it (d3d9.dll.dxvk) to use Wine's own Direct3D 9." >&2
fi

cd "$game" || exit 1
echo "Wine log: $log"
{ echo "=== $(date) WINEDEBUG=$WINEDEBUG"; wine --version; } > "$log" 2>&1

# Shut Wine down when we're done or interrupted, so nothing lingers and the terminal comes back.
gpid=""
cleanup() { wineserver -k >/dev/null 2>&1; [ -n "$gpid" ] && kill "$gpid" 2>/dev/null; }
trap 'echo; echo "Stopping Heavy Gear..."; cleanup; exit 130' INT TERM HUP
trap cleanup EXIT

# run_game CMD...: start the Wine command, wait until HG.EXE has started and then exited
# (normally or by crashing), then stop Wine. Left alone, Wine's desktop/explorer and any crash
# dialog keep running after the game dies, so gamescope and this script would never return.
run_game() {
  "$@" &
  local wpid=$! i
  for i in $(seq 60); do pgrep -x -i 'hg.exe' >/dev/null && break; sleep 0.5; done
  while pgrep -x -i 'hg.exe' >/dev/null; do sleep 1; done
  sleep 1
  wineserver -k >/dev/null 2>&1
  kill "$wpid" 2>/dev/null
  wait "$wpid" 2>/dev/null
}
export -f run_game

# Direct3D 9 renderer at a higher resolution (an hgd3d9.res in the game folder): gamescope's game size follows it,
# and the game runs without a Wine virtual desktop, with Wine emulating the shell's 640x480 display mode
# (EmulateModeset, for HG.EXE only) by scaling it up. The 640x480 menus and the high-resolution missions then
# both fill the screen. Needs the hgfix.py fixes 'display' and 'moviebg' (Wine defaults).
hdres=""
resfile="$(find "$game" -maxdepth 1 -type f -iname hgd3d9.res -print -quit)"
if [ -n "$resfile" ] && [ -z "${HG_RES:-}" ]; then
  r="$(tr -d '\r\n ' < "$resfile")"
  # the same limits the renderer applies (renderer/hgd3d9/hgd3d9.c); it ignores anything else
  if [[ "$r" =~ ^([1-9][0-9]{2,3})x([1-9][0-9]{2,3})$ ]] && (( BASH_REMATCH[1] >= 320 && BASH_REMATCH[1] <= 7680 &&
                                                              BASH_REMATCH[2] >= 240 && BASH_REMATCH[2] <= 4320 )); then
    hdres="$r"
  fi
fi
# The 'borderless' fix adds a section named .hgbdr to HGSHELL.DLL.
borderless=""
shell="$(find "$game" -maxdepth 1 -type f -iname hgshell.dll -print -quit)"
[ -n "$shell" ] && LC_ALL=C grep -q -a -F '.hgbdr' "$shell" && borderless=1
[ -n "$borderless" ] && hdres=""
appkey='HKCU\Software\Wine\AppDefaults\HG.EXE\X11 Driver'
# Older setups made HG.EXE report Windows 98. Under a 9x version Wine's DirectDraw clipper offsets a child window's
# region twice: with the 'borderless' fix the scaled movie window is clipped and its frames fail to draw.
wine reg delete 'HKCU\Software\Wine\AppDefaults\HG.EXE' /v Version /f >/dev/null 2>&1
renderer="$({ tr -d '\r\n "' < "$game/DLLFILE.INI"; } 2>/dev/null | tr 'A-Z' 'a-z')"
# nGlide: the Glide driver in the game folder (or behind the particle-fix proxy), or the one it installs system-wide
nglide="$(find "$game" "$WINEPREFIX/drive_c/windows/syswow64" -maxdepth 1 -type f \
            \( -iname glide2x.dll -o -iname glide2x_real.dll \) -exec env LC_ALL=C grep -l -a -F NGLIDE_RESOLUTION {} + \
            2>/dev/null)"
if [ -n "$borderless" ] && [ "$renderer" = 3dfxgear.dll ] && [ -n "$nglide" ]; then
  # nGlide's own settings ("Screen resolution: By desktop", "Aspect ratio: Aspect correction"). Left at 640x480 it
  # draws in a corner of the full-screen window; through emulated modes it leaves a black box until an alt-tab.
  echo "Borderless full screen with 3DFXGEAR: nGlide renders at the desktop's resolution, 4:3"
  export NGLIDE_RESOLUTION="${NGLIDE_RESOLUTION:-1}" NGLIDE_ASPECT="${NGLIDE_ASPECT:-1}"
  wine reg delete "$appkey" /v EmulateModeset /f >/dev/null 2>&1
elif [ -n "$borderless" ] && { [ "$renderer" = dx5draw.dll ] || [ "$renderer" = 3dfxgear.dll ]; }; then
  echo "Borderless full screen with $renderer: Wine scales its 640x480 missions (emulated display modes)"
  wine reg add "$appkey" /v EmulateModeset /t REG_SZ /d y /f >/dev/null 2>&1
elif [ -n "$borderless" ]; then
  echo "Borderless full screen: the game scales itself (no gamescope, no emulated display modes)"
  wine reg delete "$appkey" /v EmulateModeset /f >/dev/null 2>&1
elif [ -n "$hdres" ]; then
  echo "Direct3D 9 renderer at $hdres (hgd3d9.res): no virtual desktop, Wine scales the 640x480 menus"
  wine reg add "$appkey" /v EmulateModeset /t REG_SZ /d y /f >/dev/null 2>&1
else
  wine reg delete "$appkey" /v EmulateModeset /f >/dev/null 2>&1
fi
# Let that Wine session end before the game starts: the game would otherwise join it, and its helper
# processes belong to this display, not gamescope's (X errors: the game quits during start-up).
wineserver -w

if [ -z "$borderless" ] && [ "${HG_GAMESCOPE:-1}" != 0 ] && [ -z "${HG_DESKTOP:-}" ] && command -v gamescope >/dev/null; then
  res="${HG_RES:-${hdres:-640x480}}"
  if [ -n "$hdres" ]; then scale="${HG_SCALE:-fit}"; filter="${HG_FILTER:-linear}"; vdesk="${HG_VDESKTOP:-0}"
  else scale="${HG_SCALE:-integer}"; filter="${HG_FILTER:-nearest}"; vdesk="${HG_VDESKTOP:-1}"; fi
  gs=(gamescope -w "${res%x*}" -h "${res#*x}" -S "$scale" -F "$filter")
  if [ -n "${HG_WINDOW:-}" ]; then gs+=(-W "${HG_WINDOW%x*}" -H "${HG_WINDOW#*x}"); else gs+=(-f); fi
  [ -n "${HG_FPS:-}" ] && gs+=(-r "$HG_FPS")
  # Run inside a Wine virtual desktop of the same size, so the game, its separate movie
  # window and any message boxes all share one screen that gamescope scales as a whole.
  # (Without it, cutscenes play in a window gamescope keeps hidden: black screen with sound.)
  if [ "$vdesk" != 0 ]; then
    cmd=(wine explorer "/desktop=HeavyGear,$res" HG.EXE "$@")
  else
    cmd=(wine HG.EXE "$@")
  fi
  # Run in the background and wait: bash only reacts to Ctrl+C between commands.
  if [ "${HG_WATCH:-1}" != 0 ]; then
    "${gs[@]}" -- bash -c 'run_game "$@"' run_game "${cmd[@]}" 2>>"$log" &
  else
    "${gs[@]}" -- "${cmd[@]}" 2>>"$log" &
  fi
  gpid=$!
  wait "$gpid"
  exit 0
fi

if [ -z "$borderless" ] && [ "${HG_GAMESCOPE:-1}" != 0 ] && [ -z "${HG_DESKTOP:-}" ]; then
  echo "Tip: install gamescope ($(pkg_hint gamescope)) so the game fills the screen."
fi
[ -n "${HG_WINDOW:-}" ] && echo "Note: HG_WINDOW only applies inside gamescope; use HG_DESKTOP=WIDTHxHEIGHT for a plain Wine window."
if [ -n "${HG_DESKTOP:-}" ]; then
  run_game wine explorer "/desktop=HeavyGear,$HG_DESKTOP" HG.EXE "$@" 2>>"$log" &
else
  run_game wine HG.EXE "$@" 2>>"$log" &
fi
gpid=$!
wait "$gpid"
