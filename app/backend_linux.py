"""The Linux back end: the game lives in a Wine prefix and the shell scripts in linux/ do the work."""

import sys
from pathlib import Path

import backend
import hg_linux
import installer_core
import setup_core
from backend import Backend, find_adjacent, passes, search_roots, validate_resolution

hgfix = backend.hgfix


def app_command():
    """The command line that starts this app, for the applications menu."""
    parts = [sys.executable] if backend.frozen() else [sys.executable, str(backend.HERE / "heavygear.py")]
    return " ".join(f'"{part}"' if " " in part else part for part in parts)


class LinuxBackend(Backend):
    name = "linux"
    platform = "wine"
    can_stop = True
    location_label = "Wine prefix (the game goes in drive_c/HeavyGear)"
    location_title = "Choose the Wine prefix folder"
    patch_note = "A prefix backup is made first, and each patcher opens its own window to click through."
    install_sections = ("disc2_folder", "glide")
    play_sections = ("display",)
    extra_pages = ("tools",)
    scale_choices = hg_linux.SCALE_CHOICES      # gamescope's options on the Play page
    filter_choices = hg_linux.FILTER_CHOICES
    settings_extra = ("prefix", "disc1", "disc2", "glide_driver", "gamescope", "scale", "filter",
                      "virtual_desktop", "gamescope_resolution")

    def __init__(self):
        self.process = None
        self.stopping = False

    # --- settings and the game ---------------------------------------------------------------
    def initial_choices(self, saved):
        choices = super().initial_choices(saved)
        wrappers = backend.HERE.parent / "wrappers"
        choices.update(
            disc1=saved.get("disc1") or find_adjacent(
                [root / "HG-DISC-1" for root in search_roots()], lambda path: passes(installer_core.find_disc1, path)),
            disc2=saved.get("disc2") or find_adjacent(
                [root / "HG-DISC-2" for root in search_roots()], lambda path: passes(setup_core.find_disc2, path)),
            install_glide=False,
            glide_driver=saved.get("glide_driver") or (str(wrappers) if wrappers.is_dir() else ""),
            gamescope=saved.get("gamescope", "1") != "0",
            scale=saved.get("scale", "integer"),
            filter=saved.get("filter", "nearest"),
            gamescope_resolution=saved.get("gamescope_resolution", ""),
            virtual_desktop=saved.get("virtual_desktop", ""),
        )
        return choices

    def settings_to_save(self, choices):
        return {
            **super().settings_to_save(choices),
            "prefix": choices["location"].strip(),
            "gamescope": "1" if choices["gamescope"] else "0",
        }

    def game_folder(self, location):
        return hg_linux.game_folder(str(location).strip() or ".")

    def find_game(self, saved=None):
        saved = self.load_settings() if saved is None else saved
        for prefix in (saved.get("prefix"), str(hg_linux.default_prefix())):
            if prefix and setup_core.existing_game(prefix):
                return prefix
        return None

    def default_location(self, saved):
        return self.find_game(saved) or saved.get("prefix") or str(hg_linux.default_prefix())

    def path_checks(self):
        def driver(value):
            if not Path(value).expanduser().exists():
                raise FileNotFoundError(f"Glide driver not found: {value}")

        return {**super().path_checks(), "disc2": setup_core.find_disc2, "glide_driver": driver}

    def missing_programs(self, choices):
        return [
            f"Missing: {label}. Install: {hint}"
            for label, found, _required, hint in hg_linux.check_dependencies(
                need_codec=setup_core.existing_game(choices["location"].strip() or ".") is None,
                need_glide_build=choices.get("install_glide") and not hg_linux.glide_proxy(),
                need_renderer_build=choices.get("install_renderer") and not hg_linux.renderer_dll(),
            )
            if not found
        ]

    # --- running scripts -----------------------------------------------------------------------
    def _tracked(self, on_process):
        """An on_start callback that remembers the process for stop()."""
        def started(process):
            self.process = process
            if on_process:
                on_process(process)
        return started

    def _run(self, name, args=(), env=None, report=None, on_process=None):
        try:
            return hg_linux.run_script(name, args, env, report, self._tracked(on_process))
        finally:
            self.process = None

    def stop(self):
        self.stopping = self.process is not None
        hg_linux.stop(self.process)

    # --- install -------------------------------------------------------------------------------
    def validate_install(self, choices):
        prefix = choices["location"].strip()
        if not prefix:
            raise ValueError("Choose a Wine prefix folder.")
        game = setup_core.existing_game(prefix)
        install_renderer = choices["install_renderer"]
        reaches_12 = choices["apply12"] or (game is not None and hgfix.game_version(str(game)) == "1.2")
        if install_renderer and not reaches_12 and not choices["renderer_touched"]:
            install_renderer = False   # only the default was on: this run doesn't reach 1.2
        patches = {}
        for version, key in (("1.1", "11"), ("1.2", "12")):
            if choices[f"apply{key}"]:
                patches[version] = choices[f"patch{key}"].strip()
        selected, skipped = backend.fix_lists(choices["fixes"])
        config = setup_core.validate({
            "prefix": prefix,
            "disc1": choices["disc1"].strip(),
            "disc2": choices["disc2"].strip(),
            "controls": choices["controls"],
            "patches": patches,
            "apply_fixes": choices["apply_fixes"],
            "install_renderer": install_renderer,
            "install_glide": choices["install_glide"],
            "glide_driver": choices["glide_driver"],
            "menu_fps": float(choices["menu_fps"]),
            "sim_fps": float(choices["sim_fps"]),
            "fixes": selected,
            "skipped": skipped,
        })
        missing = setup_core.missing_required(config)
        if missing:
            raise RuntimeError(
                "Install the missing programs first:\n\n"
                + "\n".join(f"{label}: {hint}" for label, hint in missing)
            )
        return config

    def run_install(self, config, report, on_process=None):
        try:
            game = setup_core.run_setup(config, report, self._tracked(on_process))
        finally:
            self.process = None
        return "Put disc 2 in your drive for the music.", game

    # --- play ----------------------------------------------------------------------------------
    def _launch_settings(self, choices):
        disc2 = choices["disc2"].strip()
        return {
            "prefix": choices["location"].strip(),
            # A remembered folder that is no longer disc 2 is marked on the page and not used.
            "disc2": disc2 if disc2 and passes(setup_core.find_disc2, disc2) else "",
            "gamescope": choices["gamescope"],
            "scale": choices["scale"],
            "filter": choices["filter"],
            "gamescope_resolution": validate_resolution(choices["gamescope_resolution"])
            if choices["gamescope"] else "",
            "virtual_desktop": validate_resolution(choices["virtual_desktop"]),
        }

    def plan_apply(self, choices):
        plan = super().plan_apply(choices)
        if hg_linux.hg_running():
            raise RuntimeError("Exit Heavy Gear before applying changes.")
        plan["launch"] = self._launch_settings(choices)
        return plan

    def plan_play(self, choices):
        return {**super().plan_play(choices), "launch": self._launch_settings(choices)}

    def apply(self, plan, report):
        game = plan["game"]
        report(backend.apply_fixes(game, plan, self.platform))
        for filename, value in plan["renderer_settings"].items():
            target = hgfix.find_file(str(game), filename)
            installer_core.write_setting(Path(target) if target else game / filename, value)

    def play(self, plan, report, on_process=None):
        self.stopping = False
        try:
            self._run("run-heavygear.sh", env=hg_linux.launch_environment(plan["launch"]), report=report,
                      on_process=on_process)
        except RuntimeError:
            if not self.stopping:      # a game the player stopped is not an error
                raise
            report("Heavy Gear was stopped.")
            return
        report("Heavy Gear exited.")

    # --- tools ---------------------------------------------------------------------------------
    def backups_dir(self):
        return hg_linux.backups_dir()

    def _script_env(self, location):
        prefix = location.strip()
        return {
            "HG_HOME": hg_linux.HOME_DIR if prefix == str(hg_linux.default_prefix()) else Path(prefix).parent,
            "HG_BACKUPS": hg_linux.backups_dir(),
        }

    def backup(self, location, report, on_process=None):
        self._run("backup.sh", ["manual"], self._script_env(location), report, on_process)
        report("Backup finished.")

    def restore(self, archive, location, report, on_process=None):
        self._run("restore.sh", [archive], self._script_env(location), report, on_process)
        report("Restored.")

    def add_menu_entry(self):
        return hg_linux.install_desktop_entry(app_command())
