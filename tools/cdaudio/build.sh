#!/usr/bin/env bash
# Build hgcd.dll (needs clang, lld-link, llvm-dlltool; no Windows SDK).
set -e
cd "$(dirname "$0")"
# LLVM's Windows installer does not add itself to PATH.
for d in "/c/Program Files/LLVM/bin" "/mnt/c/Program Files/LLVM/bin"; do
  [ -d "$d" ] && PATH="$d:$PATH"
done
llvm-dlltool -m i386 -d kernel32.def -l kernel32.lib -k
clang -target i686-pc-windows-msvc -O2 -ffreestanding -fno-builtin -fno-stack-protector -mno-sse -Wall -c hgcd.c -o hgcd.obj
# '-' flags, not '/': Git Bash would rewrite /dll etc. into paths.
lld-link -dll -nodefaultlib -entry:DllMain -def:exports.def -out:hgcd.dll -machine:x86 -safeseh:no hgcd.obj kernel32.lib
rm -f hgcd.obj kernel32.lib hgcd.lib
echo "built $(pwd)/hgcd.dll"
