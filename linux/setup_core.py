"""What the Linux install does, apart from the window: validate the choices, then run the steps."""

import os
from pathlib import Path

import hg_linux
import installer_core
from hg_common import find_disc1, find_game_folder, sha256_file

hgfix = installer_core.hgfix

PATCH_SCRIPT_VERSIONS = {"1.1": "1.1", "1.2": "1.2"}


def _file_ci(folder, *parts):
    """Case-insensitive path under folder (disc copies and patchers disagree about case)."""
    found = hgfix.find_file(str(folder), "/".join(parts))
    return Path(found) if found else None


def find_disc2(source):
    source = Path(source).expanduser()
    for candidate in (source, source / "HG-DISC-2"):
        if candidate.is_dir() and _file_ci(candidate, "VIDEO", "B51MOVIE.AVI"):
            return candidate.resolve()
    raise FileNotFoundError(
        f"Disc 2 was not found under '{source}'. Select the disc 2 folder (it has VIDEO/B51MOVIE.AVI)."
    )


def existing_game(prefix):
    """The game folder when the prefix already holds a complete install, else None."""
    try:
        return find_game_folder(hg_linux.game_folder(prefix))
    except FileNotFoundError:
        return None


def validate(config):
    """Check the choices before anything changes; returns the normalised config. Raises on a problem."""
    config = dict(config)
    prefix = Path(config["prefix"]).expanduser()
    if not str(config["prefix"]).strip():
        raise ValueError("Choose a Wine prefix folder.")
    game = existing_game(prefix)
    config["prefix"] = str(prefix)
    config["existing"] = game is not None
    version = hgfix.game_version(game) if game else "1.0"
    config["version"] = version

    if not game:
        config["disc1"] = str(find_disc1(config.get("disc1", "")))
        config["disc2"] = str(find_disc2(config.get("disc2", "")))
        if config["controls"] not in ("action", "sim", "wasd"):
            raise ValueError(f"Unknown control layout: {config['controls']}")
    elif config["controls"] not in ("keep existing", "wasd"):
        raise ValueError("Existing installations support Keep existing or WASD controls.")

    patches = []
    for number in ("1.1", "1.2"):
        entry = config.get("patches", {}).get(number)
        if not entry or version == "1.2":
            continue
        path = Path(entry).expanduser()
        if not path.is_file():
            raise FileNotFoundError(f"Browse to the official {number} patch executable.")
        expected = installer_core.PATCH_FILENAMES[number]
        if path.name.casefold() != expected:
            raise ValueError(f"Select the official patch named '{expected}'.")
        patches.append((number, str(path.resolve())))
    numbers = [number for number, _ in patches]
    if "1.1" in numbers:
        if version != "1.0":
            raise ValueError("Official 1.1 needs the clean 1.0 game from disc 1; this game is not 1.0.")
        config["disc1"] = str(find_disc1(config.get("disc1", "")))
    if "1.2" in numbers and "1.1" not in numbers and version == "1.0":
        raise ValueError("The official 1.2 update follows 1.1. Select both updates on a 1.0 game.")
    if numbers and "1.2" not in numbers and config["apply_fixes"]:
        raise ValueError(
            "This project's fixes support the disc version and official 1.2, not the intermediate "
            "1.1 update. Apply 1.2 too or uncheck community fixes."
        )
    config["patches"] = patches
    reaches_12 = version == "1.2" or "1.2" in numbers
    if config["install_renderer"] and not reaches_12:
        raise ValueError(
            "Direct3D 9 renderer requires the official 1.2 update. Select official 1.2, or choose an "
            "existing installation that is already at 1.2."
        )
    if config["install_glide"]:
        driver = config.get("glide_driver", "").strip()
        if driver and not Path(driver).expanduser().exists():
            raise FileNotFoundError(f"Glide driver not found: {driver}")
        config["glide_driver"] = driver
    return config


def check_dependencies(config):
    return hg_linux.check_dependencies(
        need_codec=not config["existing"],
        need_glide_build=config["install_glide"] and not hg_linux.glide_proxy(),
        need_renderer_build=config["install_renderer"] and not hg_linux.renderer_dll(),
    )


def missing_required(config):
    return [
        (label, hint)
        for label, found, required, hint in check_dependencies(config)
        if required and not found
    ]


def _tool_lines(on_line, text):
    for line in (text or "").splitlines():
        on_line(line)


def run_setup(config, on_line, on_start=None):
    """Run the whole setup in order. `config` comes from validate(). Output lines go to on_line.
    Returns the game folder."""
    prefix = config["prefix"]
    env = {"HG_PREFIX": prefix, "HG_BACKUPS": hg_linux.backups_dir()}
    game = hg_linux.game_folder(prefix)
    if hg_linux.hg_running():
        raise RuntimeError("Exit Heavy Gear before installing or updating.")

    def script(name, *args, extra=None):
        return hg_linux.run_script(name, args, {**env, **(extra or {})}, on_line, on_start)

    if not config["existing"]:
        on_line("== Creating the Wine prefix and installing the game")
        layout = "sim" if config["controls"] == "sim" else "action"
        script(
            "setup-heavygear-wine.sh",
            "--prefix", prefix, "--disc1", config["disc1"], "--disc2", config["disc2"],
            "--controls", layout,
        )
    game = find_game_folder(game)
    if config["controls"] == "wasd":
        on_line("== Installing the WASD controls")
        _tool_lines(on_line, installer_core.apply_controls(game, "wasd"))

    if config["patches"]:
        on_line("== Preparing for the official updates")
        _tool_lines(on_line, installer_core._run_tool(hgfix.main, [str(game), "--restore"]))
        backups = hg_linux.backups_dir()
        if config["version"] == "1.0" and not list(backups.glob("HeavyGear-1.0-prefix-*.tar.zst")):
            on_line("== Saving a 1.0 backup of the prefix (needed to undo the updates)")
            script("backup.sh", "1.0")
        numbers = [number for number, _ in config["patches"]]
        patch_env = {"HG_DISC1": config.get("disc1")}
        for number, path in config["patches"]:
            patch_env["HG_PATCH11" if number == "1.1" else "HG_PATCH12"] = path
        on_line("== Running the official patchers: click through each patcher window that opens")
        script("apply-patches.sh", "all" if len(numbers) == 2 else numbers[0], extra=patch_env)
        game = find_game_folder(game)
        if hgfix.game_version(game) != "1.2" and "1.2" in numbers:
            raise RuntimeError("The official 1.2 patcher finished, but the game files are not a 1.2 build.")

    if config["install_renderer"]:
        installer_core.require_official_12(game)
        on_line("== Installing the Direct3D 9 renderer")
        dll = hg_linux.renderer_dll() or hg_linux.build_renderer(on_line)
        on_line(installer_core.install_renderer(game, dll))
        on_line(installer_core.select_default_renderer(game))

    if config["apply_fixes"]:
        on_line("== Applying the community fixes")
        _tool_lines(
            on_line,
            installer_core.apply_fixes(
                game, config["menu_fps"], config["sim_fps"], config["fixes"], config["skipped"],
                platform="wine",
            ),
        )

    if config["install_glide"]:
        on_line("== Setting up 3Dfx (Glide) support")
        extra = {}
        proxy = hg_linux.glide_proxy()
        if proxy:
            extra["HG_GLIDE_PROXY"] = proxy
        driver = config.get("glide_driver")
        if driver:
            extra["HG_WRAPPERS" if Path(driver).expanduser().is_dir() else "HG_GLIDE_DRIVER"] = (
                Path(driver).expanduser()
            )
        script("setup-glide.sh", extra=extra)
    return game
