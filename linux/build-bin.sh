#!/usr/bin/env bash
# build-bin.sh - build the Heavy Gear app for Linux as a one-file binary with PyInstaller.
#   linux/build-bin.sh
# Needs Python 3 with Tk (python3-tk). Output goes to dist/. Build on the oldest distribution you want
# to support (the release workflow uses Ubuntu 22.04): the binary needs at least that glibc.
# Bundles dist/3dfx_hgd3d9.dll and dist/glide2x.dll when they exist, so users don't need clang.
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -c "import tkinter" 2>/dev/null || { echo "Tk is missing: $(. linux/distro.sh; pkg_hint tk)" >&2; exit 1; }
# Pinned so release builds are reproducible; bump deliberately after testing a build.
python3 -m pip install --quiet pyinstaller==6.22.3
args=(--onefile --clean --paths app --paths patcher --paths windows --paths linux --add-data "mods:mods")
for script in linux/*.sh; do args+=(--add-data "$script:linux"); done
for dll in 3dfx_hgd3d9.dll glide2x.dll; do [ -s "dist/$dll" ] && args+=(--add-data "dist/$dll:."); done
name="HeavyGear-linux-$(uname -m)"
python3 -m PyInstaller "${args[@]}" --name "$name" app/heavygear.py
"dist/$name" --self-test
echo "Built: dist/$name"
