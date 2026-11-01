# Windows

* The app itself is in `app/` (shared with Linux; `app/backend_windows.py` is the Windows part). Its
  Windows build is `HeavyGearFixes.exe` (`app/heavygear.py`), one one-file program that installs or
  updates the game from the user's own disc/files, runs official patches, applies the community fixes,
  installs the bundled Direct3D 9 renderer and the optional Indeo/fonts, and then is the everyday
  launcher (frame rate, fixes, renderer choice and resolution, play). It remembers its choices in
  `%LOCALAPPDATA%\HeavyGearFixes\launcher.json`.
* Shared code the app uses: `hg_gui_common.py` (renderer helpers, registry lookup, elevation call),
  `installer_core.py` (copy the game, run patches, the operations the app requests), `win_elevation.py` (UAC relaunch; the request travels on the elevated command line
  and the result returns over an authenticated pipe, so no temp file can be swapped),
  `win_system.py` (registry, Indeo codec and fonts; additive, validated before any change, undone on
  failure), `launcher_settings.py`, and `hg_common.py`.
  Run the tests with `python -m unittest discover -s windows -p "test_*.py"`.
  `app/heavygear.py --self-test` builds every page off-screen (skipped without Tk/a display), so a
  startup crash fails the build and the Windows CI job instead of reaching users.
  If the app is cancelled at the UAC prompt it reports "Administrator approval was cancelled" and
  can simply be run again.
* `setup-heavygear.ps1`: installs the game files from `HG-DISC-1` to a user-writable folder.
  Pass `-ExistingInstall -GamePath <folder>` to validate and reuse a retail install without
  replacing its files or controls; use `-Controls wasd` to install the updated WASD layout.
  Optional system-wide Indeo 5 codec and font installation is available with
  `-InstallSystemComponents` (run elevated; requires `unshield` on `PATH` or an extracted
  `ir50_32.dll` with `-CodecPath`).
* `apply-patches.ps1`: runs the supplied official 1.1/1.2 patchers and applies this repository's
  fixes afterwards (run elevated; the official patchers show their own windows). Installs the
  Direct3D 9 renderer only after the official 1.2 patch completes.
* `install-renderer.ps1`: installs a built `3dfx_hgd3d9.dll` into the game's `PLUGIN` folder.
  Download it from the `heavygear-renderer-windows` artifact of the `windows-exe` Actions run;
  tagged releases include it inside `HeavyGearFixes.exe`.
* `build-renderer.ps1`: builds the x86 Direct3D 9 renderer natively on Windows using LLVM,
  Python 3, and Windows SDK/DirectX SDK headers.
* `build-exe.ps1 [-Target app|tools|all]`: builds `HeavyGearFixes.exe` (and the developer tools
  `hgfix.exe` / `hg_controls.exe`); the `windows-exe` workflow attaches the app to tagged releases.

Installation and setup: [docs/windows.md](../docs/windows.md).
