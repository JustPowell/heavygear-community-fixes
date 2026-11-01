#!/bin/sh
# Builds hgd3d9.dll and the smoke program, runs it under a throwaway Wine prefix and checks the saved frame.
# HG_SMOKE_CONTROL="name ..." sets the control files to create (default: hgd3d9.dump hgd3d9.window).
# Needs the D3D9 build (Wine headers for the generator), clang, lld-link, wine, python3 with Pillow.
set -e
here="$(cd "$(dirname "$0")/.." && pwd)"
cd "$here"
./build.sh >/dev/null
tmp="${TMPDIR:-/tmp}/hgsmoke.$$"; mkdir -p "$tmp"
printf 'LIBRARY user32.dll\nEXPORTS\nCreateWindowExA@48\nSetActiveWindow@4\nPeekMessageA@20\nDispatchMessageA@4\n' > "$tmp/u.def"
llvm-dlltool -m i386 -d "$tmp/u.def" -l "$tmp/u32.lib" -k
printf 'LIBRARY kernel32.dll\nEXPORTS\nLoadLibraryA@4\nGetProcAddress@8\nExitProcess@4\nSleep@4\nGetStdHandle@4\nWriteFile@20\n' > "$tmp/k.def"
llvm-dlltool -m i386 -d "$tmp/k.def" -l "$tmp/k32.lib" -k
clang --target=i686-pc-windows-msvc -O1 -ffreestanding -fno-builtin -fno-stack-protector -c test/wine_smoke.c -o "$tmp/smoke.obj"
lld-link /subsystem:windows /entry:mainCRTStartup /nodefaultlib /machine:x86 /out:"$tmp/smoke.exe" "$tmp/smoke.obj" "$tmp/k32.lib" "$tmp/u32.lib" >/dev/null
cp hgd3d9.dll "$tmp/"
for c in ${HG_SMOKE_CONTROL:-hgd3d9.dump hgd3d9.window}; do touch "$tmp/$c"; done
(cd "$tmp" && WINEPREFIX="$tmp/pfx" WINEDEBUG=-all timeout 120 wine smoke.exe 2>&1 | grep -v radv; cat hgd3d9.log 2>/dev/null)
echo "temp dir: $tmp"
