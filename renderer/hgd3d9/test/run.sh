#!/bin/sh
# Native unit tests for convert.c (no Wine), then the generated D3D9 header checks.
set -e
cd "$(dirname "$0")"
clang -std=c11 -Wall -Wextra -Wpedantic -O1 -fsanitize=address,undefined -I.. test_convert.c ../convert.c -o test_convert
./test_convert
rm -f test_convert
clang -std=gnu11 -Wall -Wextra -O1 -fsanitize=address,undefined -I.. test_texcache.c ../texcache.c ../convert.c -o test_texcache
./test_texcache
rm -f test_texcache

# The generated D3D9 header: slot numbers against the documented values, then a compile for the Windows target.
cd ..
./gen_d3d9_min.py --check
./gen_d3d9_min.py
clang --target=i686-pc-windows-msvc -std=c11 -Wall -Wextra -ffreestanding -fsyntax-only test/d3d9_min_check.c
echo "d3d9_min.h compiles for i686-pc-windows-msvc"
