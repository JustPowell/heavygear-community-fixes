#!/bin/sh
# Linux build route: builds hgd3d9.dll with clang and lld-link (no CRT).
# HG_BACKEND=hg_backend_d3d9 (default, needs Wine headers) or hg_backend_null.
set -e
cd "$(dirname "$0")"
llvm-dlltool -m i386 -d kernel32.def -l k32.lib -k
llvm-dlltool -m i386 -d user32.def -l u32.lib -k
BACKEND="${HG_BACKEND:-hg_backend_d3d9}"
SRCS="hgd3d9 convert texcache capture null_backend rt"
LIBS="k32.lib u32.lib"
if [ "$BACKEND" = hg_backend_d3d9 ]; then
  if [ -n "${HG_WINE_INCLUDE:-}" ]; then
    python3 gen_d3d9_min.py --d3d9-include "$HG_WINE_INCLUDE"
  else
    python3 gen_d3d9_min.py
  fi
  python3 gen_shaders.py
  llvm-dlltool -m i386 -d d3d9.def -l d3d9.lib -k
  SRCS="$SRCS d3d9"; LIBS="$LIBS d3d9.lib"
fi
CFLAGS="--target=i686-pc-windows-msvc -std=c11 -Wall -Wextra -O2 -ffreestanding -fno-stack-protector -fno-builtin -DHG_BACKEND=$BACKEND"
for f in $SRCS; do clang $CFLAGS -c $f.c -o $f.obj; done
OBJS=""; for f in $SRCS; do OBJS="$OBJS $f.obj"; done
lld-link /dll /nodefaultlib /entry:DllMain /machine:x86 /out:hgd3d9.dll $OBJS $LIBS
rm -f *.obj k32.lib u32.lib d3d9.lib
echo "built $(pwd)/hgd3d9.dll"
