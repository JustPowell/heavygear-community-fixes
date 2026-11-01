#!/usr/bin/env bash
# Build glidelog's glide2x.dll (needs clang, lld-link, llvm-dlltool; no Windows SDK).
set -e
cd "$(dirname "$0")"
python3 gen.py
llvm-dlltool -m i386 -d kernel32.def -l kernel32.lib -k
clang -target i686-pc-windows-msvc -O2 -ffreestanding -fno-builtin -fno-stack-protector -mno-sse -c glidelog.c -o glidelog.obj
lld-link /dll /nodefaultlib /entry:DllMain /def:glide2x.def /out:glide2x.dll /machine:x86 /safeseh:no glidelog.obj kernel32.lib
echo "built glide2x.dll"
