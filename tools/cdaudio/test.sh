#!/usr/bin/env bash
# Build and run selftest.exe against hgcd.dll (Windows only: it plays two short test tones). Needs the same tools as
# build.sh, and python for the test tones.
set -e
cd "$(dirname "$0")"
for d in "/c/Program Files/LLVM/bin" "/mnt/c/Program Files/LLVM/bin"; do
  [ -d "$d" ] && PATH="$d:$PATH"
done
[ -f hgcd.dll ] || ./build.sh
t=$(mktemp -d)
llvm-dlltool -m i386 -d selftest.def -l "$t/k32.lib" -k
clang -target i686-pc-windows-msvc -O1 -ffreestanding -fno-builtin -fno-stack-protector -mno-sse -Wall -c selftest.c -o "$t/selftest.obj"
lld-link -nodefaultlib -subsystem:console -entry:mainCRTStartup -out:"$t/selftest.exe" -machine:x86 -safeseh:no "$t/selftest.obj" "$t/k32.lib"
cp hgcd.dll "$t/"
mkdir "$t/MUSIC" "$t/VIDEO"
: > "$t/VIDEO/B51MOVIE.AVI"       # makes the proxy keep the working folder at the game folder
PY=$(command -v py || command -v python3 || command -v python)
"$PY" - "$t/MUSIC" <<'P'
import math, struct, sys, wave
for track, step in ((2, 0.05), (3, 0.08)):
    with wave.open(f"{sys.argv[1]}/TRACK{track:02d}.WAV", "wb") as f:
        f.setnchannels(2); f.setsampwidth(2); f.setframerate(22050)
        f.writeframes(b"".join(struct.pack("<hh", *(int(1500 * math.sin(i * step)),) * 2) for i in range(22050 * 2)))
P
: > "$t/hgcd.log"
rc=0; (cd "$t" && HGCD_MUSIC="$t/MUSIC" ./selftest.exe) || rc=$?
echo "--- hgcd.log"; cat "$t/hgcd.log"; rm -rf "$t"; exit $rc
