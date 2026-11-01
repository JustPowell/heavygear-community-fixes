#!/usr/bin/env bash
# setup-heavygear-wine.sh - install Heavy Gear (Activision, 1997) into its own Wine prefix.
#
# What it does (nothing outside the prefix is touched):
#   1. creates a dedicated Wine prefix (default ~/Games/HeavyGear/prefix)
#   2. copies the pre-installed game from disc 1 (INSTALL/DATA) to C:\HeavyGear
#   3. maps disc 2 as drive D: of type CD-ROM  (the game requires D:\VIDEO\B51MOVIE.AVI
#      on the FIRST CD-ROM drive it finds)
#   4. installs the Indeo 5 video codec (ir50_32.dll, from the disc's own installer cab)
#      so the cutscenes play, plus the two game fonts
#   5. writes run-heavygear.sh next to this script
#
# Usage:  ./setup-heavygear-wine.sh [--prefix DIR] [--project DIR] [--controls action|sim]
#                                  [--disc1 DIR] [--disc2 DIR] [--codec FILE]
# --disc1/--disc2 default to HG-DISC-1/HG-DISC-2 in the project folder; --codec is a ready-made ir50_32.dll.
# Safe to re-run: existing files in C:\HeavyGear (saves, settings) are kept.
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
. "$here/distro.sh"
project="$(cd "$here/.." && pwd)"
prefix="${HOME}/Games/HeavyGear/prefix"
controls=ACTION
disc1_arg=""; disc2_arg=""; codec_arg=""

while [ $# -gt 0 ]; do
  case "$1" in
    --prefix)  prefix="$2"; shift 2 ;;
    --project) project="$(cd "$2" && pwd)"; shift 2 ;;
    --disc1)   disc1_arg="$2"; shift 2 ;;
    --disc2)   disc2_arg="$2"; shift 2 ;;
    --codec)   codec_arg="$2"; shift 2 ;;
    --controls) controls="$(echo "$2" | tr a-z A-Z)"; shift 2 ;;   # ACTION (default) or SIM
    -h|--help) sed -n '2,18p' "$0"; exit 0 ;;
    *) echo "unknown option $1" >&2; exit 1 ;;
  esac
done

disc1="${disc1_arg:-$project/HG-DISC-1}"
disc2="${disc2_arg:-$project/HG-DISC-2}"
codec="${codec_arg:-$here/files/ir50_32.dll}"
# A read-only script folder (a bundled app) can't cache the extracted codec there.
if [ -z "$codec_arg" ] && [ ! -w "$here" ]; then codec="$(mktemp -d)/ir50_32.dll"; fi

die() { echo "ERROR: $*" >&2; exit 1; }
[ -f "$disc1/INSTALL/DATA/HG.EXE" ]        || die "can't find $disc1/INSTALL/DATA/HG.EXE"
[ -f "$disc2/VIDEO/B51MOVIE.AVI" ]          || die "can't find $disc2/VIDEO/B51MOVIE.AVI"
command -v wine >/dev/null                  || die "wine is not installed: $(pkg_hint wine)"

export WINEPREFIX="$prefix"
export WINEDEBUG=-all
echo "== Wine: $(wine --version)"
echo "== Prefix: $WINEPREFIX"

if [ ! -f "$WINEPREFIX/system.reg" ]; then
  mkdir -p "$WINEPREFIX"
  echo "== Creating prefix (first run takes a minute)..."
  wineboot -i >/dev/null 2>&1 || true
  wineserver -w
fi

drive_c="$WINEPREFIX/drive_c"
game="$drive_c/HeavyGear"

# copy_missing SRC DST: copy what SRC has and DST doesn't, comparing names without regard to case. Disc 1 names
# files in upper case that the 1.2 patch writes in lower case (ANET2.DLL / anet2.dll, PLUGIN/DX5DRAW.DLL /
# dx5draw.dll, ...); a plain `cp -n` on a case-sensitive file system would put the old disc copy next to the
# patched one when this script runs over an installed game, and Wine may then load either.
copy_missing() {
  local src="$1" dst="$2" rel parent
  local -A have=()
  [ -d "$src" ] || die "can't find $src"
  while IFS= read -r -d '' rel; do have["${rel,,}"]="$rel"; done < <(cd "$dst" && find . -mindepth 1 -print0)
  while IFS= read -r -d '' rel; do
    [ -n "${have["${rel,,}"]:-}" ] && continue
    parent="$(dirname "$rel")"
    parent="${have["${parent,,}"]:-$parent}"                     # an existing folder spelled in another case
    if [ -d "$src/$rel" ]; then
      mkdir -p "$dst/$parent/$(basename "$rel")"; have["${rel,,}"]="$parent/$(basename "$rel")"
    else
      cp --no-preserve=mode,ownership "$src/$rel" "$dst/$parent/"
    fi
  done < <(cd "$src" && find . -mindepth 1 -print0)                 # find lists a folder before its contents
}

# --- 1. game files ---------------------------------------------------------
echo "== Copying game files to C:\\HeavyGear"
mkdir -p "$game"
copy_missing "$disc1/INSTALL/DATA" "$game"
# The original installer copies one control scheme (DATA\ACTION or DATA\SIM: INPUTW.MAP and
# the *.CCT files) into the game folder. Without INPUTW.MAP missions fail with SYSERR_NOPREFS.
# The multi-language pressing has a set per language (ACTIONE/F/I/S, SIME/...): the English one is the same.
[ -f "$disc1/INSTALL/DATA/$controls/INPUTW.MAP" ] || [ ! -f "$disc1/INSTALL/DATA/${controls}E/INPUTW.MAP" ] \
  || controls="${controls}E"
[ -f "$disc1/INSTALL/DATA/$controls/INPUTW.MAP" ] \
  || { echo "Disc 1 has no $controls control scheme (INSTALL/DATA/$controls/INPUTW.MAP)." >&2; exit 1; }
echo "== Installing the $controls control scheme"
copy_missing "$disc1/INSTALL/DATA/$controls" "$game"
# keep the manual/help handy inside the game folder too
[ -d "$disc1/HELP" ] && mkdir -p "$game/HELP" && copy_missing "$disc1/HELP" "$game/HELP"
chmod -R u+rwX "$game"

# --- 2. disc 2 as CD-ROM drive D: -------------------------------------------
echo "== Mapping disc 2 as CD-ROM drive D:"
dos="$WINEPREFIX/dosdevices"
for l in d e f g h; do
  # the game uses the first CD-ROM drive; make sure no other CD drive sorts before D:
  if [ "$l" != d ] && [ -L "$dos/$l:" ]; then
    t="$(wine reg query 'HKLM\Software\Wine\Drives' /v "$l:" 2>/dev/null | tr -d '\r' | awk '/REG_SZ/{print $3}')" || true
    [ "$t" = cdrom ] && echo "   note: $l: is also a CD-ROM drive (after D:, so that's fine)"
  fi
done
rm -f "$dos/d:" "$dos/d::"
ln -s "$disc2" "$dos/d:"
wine reg add 'HKLM\Software\Wine\Drives' /v 'd:' /t REG_SZ /d cdrom /f >/dev/null

# --- 3. Indeo 5 codec + fonts -------------------------------------------------
# The codec ships inside disc 1's installer cab (INSTALL/DATA1.CAB, Root\Ir50_32.dll).
# Pull it out with unshield (see pkg_hint unshield).
if [ ! -f "$codec" ] && command -v unshield >/dev/null && [ -f "$disc1/INSTALL/DATA1.CAB" ]; then
  echo "== Extracting the Indeo 5 codec from disc 1's installer cab"
  tmpcab="$(mktemp -d)"
  unshield -d "$tmpcab" x "$disc1/INSTALL/DATA1.CAB" >/dev/null 2>&1 || true
  found="$(find "$tmpcab" -iname 'ir50_32.dll' -print -quit)"
  if [ -n "$found" ]; then mkdir -p "$(dirname "$codec")"; cp "$found" "$codec"; fi
  rm -rf "$tmpcab"
fi
if [ -f "$codec" ]; then
  echo "== Installing Indeo 5 codec (ir50_32.dll) for the cutscenes"
  if [ -d "$drive_c/windows/syswow64" ]; then sysdir="$drive_c/windows/syswow64"; regview=/reg:32
  else sysdir="$drive_c/windows/system32"; regview=; fi
  cp "$codec" "$sysdir/ir50_32.dll"
  wine reg add 'HKLM\Software\Microsoft\Windows NT\CurrentVersion\Drivers32' \
       /v vidc.iv50 /t REG_SZ /d ir50_32.dll /f $regview >/dev/null
  # Wine's own video decoders should not grab IV50 first
  wine reg add 'HKCU\Software\Wine\DllOverrides' /v ir50_32 /t REG_SZ /d native,builtin /f >/dev/null
else
  echo "   (skipping codec: install unshield ($(pkg_hint unshield)) and re-run this script, or put ir50_32.dll in"
  echo "    $(dirname "$codec")/ - without it the cutscenes may not play)"
fi
echo "== Installing game fonts"
mkdir -p "$drive_c/windows/Fonts"
cp "$disc1"/INSTALL/*.TTF "$drive_c/windows/Fonts/" 2>/dev/null || true

# --- 4. per-app settings --------------------------------------------------------
# HG.EXE runs with Wine's default Windows version. (Earlier versions of this script reported Windows 98; under a 9x
# version Wine's DirectDraw clipper offsets a child window twice, which breaks the 'borderless' fix's scaled movies.
# run-heavygear.sh removes that setting from older installs.)

chmod +x "$here/run-heavygear.sh" 2>/dev/null || true

echo
echo "Done. Start the game with:"
echo "   $here/run-heavygear.sh"
echo "Game folder (saves, loose-file mods):  $game"
