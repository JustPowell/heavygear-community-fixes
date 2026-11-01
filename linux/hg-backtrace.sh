#!/usr/bin/env bash
# hg-backtrace.sh - run this from a second terminal while Heavy Gear is frozen.
# It asks Wine's debugger where every thread of the game is, and saves the result to
# ~/Games/HeavyGear/backtrace.txt (the game keeps running; nothing is changed).
export WINEPREFIX="${HG_PREFIX:-$HOME/Games/HeavyGear/prefix}"
out="$(dirname "$WINEPREFIX")/backtrace.txt"
export WINEDEBUG=-all
{
  echo "=== $(date)"
  echo "--- processes"
  winedbg --command "info proc"
  echo "--- threads"
  winedbg --command "info thread"
  echo "--- backtraces"
  winedbg --command "bt all"
} > "$out" 2>&1
echo "Saved $out ($(wc -l < "$out") lines)"
