#!/bin/sh
# Resolution switcher for the hgd3d9 plugin: writes hgd3d9.res ("WIDTHxHEIGHT") into the game folder; the plugin reads it when the game starts
# and sizes the game window to it (4:3 sizes fill the window; wider ones get side bars). Restart the game after changing it.
#   res.sh                 pick from a menu
#   res.sh list            show the presets, marking the current one
#   res.sh set 1600x1200   a preset or any WIDTHxHEIGHT (also: 4k = 2880x2160, 1080p = 1920x1080)
#   res.sh off             remove it: the window keeps the size the game made
#   res.sh [..] [GAME_FOLDER]
set -e
game="${2:-${HG_GAME:-$HOME/Games/HeavyGear/prefix/drive_c/HeavyGear}}"
[ "$1" = set ] && game="${3:-${HG_GAME:-$HOME/Games/HeavyGear/prefix/drive_c/HeavyGear}}"
f="$game/hgd3d9.res"
presets="640x480 800x600 1024x768 1152x864 1280x960 1400x1050 1600x1200 1792x1344 1920x1440 2048x1536 2560x1920 2880x2160 3200x2400 1280x720 1920x1080 2560x1440 3840x2160"
cur=""; [ -f "$f" ] && cur=$(tr -d ' \r\n' < "$f")
show() {
  i=1
  for r in $presets; do
    case "$r" in 1280x720) echo "  -- wider than 4:3: the picture stays 4:3 with side bars --";; esac
    mark=" "; [ "$r" = "$cur" ] && mark="*"
    printf ' %s %2d  %s\n' "$mark" "$i" "$r"; i=$((i+1))
  done
  [ -n "$cur" ] && echo "current: $cur" || echo "current: not set (the game's own window size)"
}
set_res() {
  case "$1" in 4k) r=2880x2160;; 1080p) r=1920x1080;; 1440p) r=2560x1440;; *) r="$1";; esac
  case "$r" in *[!0-9x]*|""|x*|*x|*x*x*) echo "not a WIDTHxHEIGHT: $1"; exit 2;; esac
  rm -f "$game"/hgd3d9.res[0-9]*      # the old per-size marker files
  printf '%s\n' "$r" > "$f"; echo "set $r (restart the game)"
}
case "${1:-menu}" in
  list|status) show;;
  set) [ -n "$2" ] || { sed -n '2,8p' "$0"; exit 2; }; set_res "$2";;
  off) rm -f "$f" "$game"/hgd3d9.res[0-9]*; echo "off: the game's own window size";;
  menu)
    show; printf 'number, WIDTHxHEIGHT or "off": '; read -r a
    case "$a" in off) rm -f "$f" "$game"/hgd3d9.res[0-9]*; echo "off";; ""|q) ;;
      *[!0-9]*) set_res "$a";;
      *) i=1; for r in $presets; do [ "$i" = "$a" ] && { set_res "$r"; break; }; i=$((i+1)); done;;
    esac;;
  *) sed -n '2,8p' "$0"; exit 2;;
esac
