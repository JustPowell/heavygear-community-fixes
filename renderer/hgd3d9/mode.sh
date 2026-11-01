#!/bin/sh
# Switches the game folder between playing with our renderer alone and recording a comparison run.
#   mode.sh live      our renderer alone, in the game's window (what you see is ours; nothing else is loaded)
#   mode.sh tee       the real 3Dfx plugin runs too and every 30th frame (and each effect frame) is compared; ours draws in a second window
#                     at x=660 (HG_RES=1320x520 with linux/run-heavygear.sh makes room), the game's window shows 3Dfx; records hgd3d9.cap
#   mode.sh livecap   as live, but also recording hgd3d9.cap (and our own pictures hgcap_NNNN.bmp): for reproducing a problem you only see in live play
#   mode.sh status
# Select the "Direct3D 9 renderer" entry (3dfx_hgd3d9.dll) in the shell's renderer list in both modes.   mode.sh [live|tee|status] [GAME_FOLDER]
set -e
game="${2:-${HG_GAME:-$HOME/Games/HeavyGear/prefix/drive_c/HeavyGear}}"
case "${1:-status}" in
  live) rm -f "$game/hgd3d9.tee" "$game/hgd3d9.window" "$game/hgd3d9.capture"; echo "live: our renderer alone in the game's window";;
  livecap) rm -f "$game/hgd3d9.tee" "$game/hgd3d9.window"; touch "$game/hgd3d9.capture"; echo "livecap: our renderer alone in the game's window, recording hgd3d9.cap";;
  tee)  touch "$game/hgd3d9.tee" "$game/hgd3d9.window" "$game/hgd3d9.capture"; echo "tee: 3Dfx in the game's window, ours in a second window at x=660 (use HG_RES=1320x520), recording hgd3d9.cap";;
  status) ;;
  *) sed -n '2,10p' "$0"; exit 2;;
esac
for f in tee window capture; do [ -f "$game/hgd3d9.$f" ] && echo "  hgd3d9.$f: on" || echo "  hgd3d9.$f: off"; done
