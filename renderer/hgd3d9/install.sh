#!/bin/sh
# Builds hgd3d9.dll and installs it into the game's PLUGIN folder as 3dfx_hgd3d9.dll. The file name has to contain "3dfx": the sim
# only takes its hardware-renderer paths (particles, alpha palettes) for a plugin whose path contains 3DFX or POWERVR
# (docs/research/renderer-interface.md section 9).   install.sh [GAME_FOLDER]
set -e
here="$(cd "$(dirname "$0")" && pwd)"
game="${1:-${HG_GAME:-$HOME/Games/HeavyGear/prefix/drive_c/HeavyGear}}"
"$here/build.sh" >/dev/null
cp "$here/hgd3d9.dll" "$game/PLUGIN/3dfx_hgd3d9.dll"
# The renderer was called hgrender before: take the old DLL out of the plugin list, keep its resolution and selection
# (same as windows/installer_core.py).
for old_name in "hgrender.dll" "3dfx_hgrender.dll"; do
    if [ -f "$game/PLUGIN/$old_name" ]; then
        mkdir -p "$game/hgd3d9-runs"
        mv "$game/PLUGIN/$old_name" "$game/hgd3d9-runs/$old_name.$(date +%Y%m%d-%H%M%S).bak"
        echo "moved the old PLUGIN/$old_name out of the plugin list"
    fi
done
[ -f "$game/hgrender.res" ] && [ ! -f "$game/hgd3d9.res" ] && mv "$game/hgrender.res" "$game/hgd3d9.res" && echo "hgrender.res is now hgd3d9.res"
ini="$(find "$game" -maxdepth 1 -type f -iname dllfile.ini -print -quit)"
if [ -n "$ini" ] && tr -d '"\r\n' < "$ini" | grep -qix '3dfx_hgrender\.dll\|hgrender\.dll'; then
    printf '3dfx_hgd3d9.dll\r\n' > "$ini"; echo "selected 3dfx_hgd3d9.dll in place of the old name"
fi
echo "installed $game/PLUGIN/3dfx_hgd3d9.dll"
