"""The Windows back end: installs into a game folder, elevates per operation, starts HG.EXE directly."""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import backend
import disc2_media
import disc_image
import installer_core
import win_system
from backend import Backend, find_adjacent, has_game, search_roots
from hg_gui_common import get_game_path_from_registry, read_selected_renderer, run_elevated_config


IMAGE_TEMP_PREFIX = "hg-disc-"
_image_temps = set()             # the folders mount_disc_image made for an .iso from an .mds/.mdf


def is_disc_image(path):
    """A .iso, or either file of an Alcohol 120% .mds/.mdf pair."""
    return disc2_media.is_image(path) or disc_image.is_mds(path)


def mount_disc_image(path):
    """Mount a disc image. Returns (drive root, the .iso to dismount afterwards or None). An .mds/.mdf pair's data
    track is first written as an .iso in a new temporary folder (removed again by dismount_images)."""
    if not disc_image.is_mds(path):
        drive, mounted = disc2_media.mount_image(path)
        return drive, (path if mounted else None)
    temp = Path(tempfile.mkdtemp(prefix=IMAGE_TEMP_PREFIX))
    _image_temps.add(temp)
    try:
        with disc_image.MdsImage(path) as image:
            iso = image.write_iso(temp / "disc.iso")
        drive, _mounted = disc2_media.mount_image(iso)
    except BaseException:
        _image_temps.discard(temp)
        shutil.rmtree(temp, ignore_errors=True)
        raise
    return drive, str(iso)


def adjacent_image(*names):
    """A disc image beside the app with one of these names (checked when it is mounted), or ''."""
    return find_adjacent([root / name for root in search_roots() for name in names], Path.is_file)


def find_adjacent_disc1():
    """Disc 1 beside the app, or in a CD/DVD drive, else an image of it beside the app."""
    candidates = [path for root in search_roots() for path in (root / "HG-DISC-1", root / "disc1", root)]
    return (find_adjacent(candidates + disc2_media.cd_drives(),
                          lambda path: backend.passes(installer_core.find_disc1, path))
            or adjacent_image("HG-DISC-1.iso", "disc1.iso", "HG-DISC-1.mds", "disc1.mds"))


def find_disc2():
    """Disc 2 if it is in a drive right now, else a copy beside the app, else ''."""
    return disc2_media.detect_disc2() or find_adjacent(
        [path for root in search_roots() for path in (root / "HG-DISC-2", root / "disc2")],
        lambda path: backend.passes(disc2_media.find_disc2, path),
    ) or adjacent_image("HG-DISC-2.iso", "disc2.iso", "HG-DISC-2.mds", "disc2.mds")


def dismount_images(images):
    """Dismount the images this app mounted; one that will not go is left for Windows (Eject in Explorer)."""
    for image in images:
        try:
            disc2_media.dismount_image(image)
        except OSError:
            continue
        folder = Path(image).parent
        if folder in _image_temps:
            _image_temps.discard(folder)
            shutil.rmtree(folder, ignore_errors=True)


def check_image(value):
    """A disc image's contents are only looked into once it is mounted, at Install / Update."""
    if not Path(value).expanduser().is_file():
        raise FileNotFoundError("no disc image there.")
    if disc_image.is_mds(value):
        disc_image.MdsImage(value).close()           # both files there, and a readable descriptor


def disc_note(fixes):
    """What disc 2 is still needed for after a run with these fixes."""
    if "music" in fixes:
        return "Disc 2 is not needed to play."
    if "nodisc" in fixes:
        return (
            "The cutscenes no longer need disc 2. Mount it in the first CD/DVD drive for the music, "
            "or the game runs without music."
        )
    return "Mount disc 2 in the first CD/DVD drive before playing."


def check_glide_driver(value):
    """The resolved path of a usable glide2x.dll (32-bit). Raises FileNotFoundError/ValueError with a message."""
    path = Path(value).expanduser().resolve()
    if path.name.casefold() != installer_core.GLIDE_NAME or not path.is_file():
        raise FileNotFoundError("Choose a glide2x.dll (from nGlide or dgVoodoo2) for 3Dfx support.")
    installer_core.validate_x86_dll(path, "The Glide driver")
    if installer_core.GLIDE_PROXY_MARK in path.read_bytes():
        raise ValueError("that is the particle-fix proxy, not a Glide driver: choose nGlide's or dgVoodoo2's.")
    return path


# nGlide's settings (HKCU, one set for every game it runs), as nglide_config.exe saves them: text values.
NGLIDE_KEY = r"Software\Zeus Software\nGlide2"
# "Screen resolution: By desktop" and "Aspect ratio: Aspect correction"
NGLIDE_BORDERLESS = {"Resolution": "1", "Aspect": "1"}


def uses_nglide_borderless(game):
    """The 'borderless' fix with 3DFXGEAR on nGlide: then nGlide must render at the desktop's resolution in 4:3, or it
    draws the game's 640x480 small in a corner of the full-screen window. The same rule as linux/run-heavygear.sh.
    A file that can't be read counts as no."""
    try:
        shell = installer_core.hgfix.find_file(str(game), "HGSHELL.DLL")
        if not shell or b".hgbdr" not in Path(shell).read_bytes():          # the section the 'borderless' fix adds
            return False
        if read_selected_renderer(game).casefold() != "3dfxgear.dll":
            return False
        drivers = [Path(game) / installer_core.GLIDE_NAME, Path(game) / installer_core.GLIDE_REAL_NAME,
                   installer_core.find_glide_driver()]
        return any(path and path.is_file() and b"NGLIDE_RESOLUTION" in path.read_bytes() for path in drivers)
    except OSError:
        return False


def set_nglide_for_borderless(game):
    """Save nGlide's desktop-resolution, 4:3 settings when uses_nglide_borderless(game), so the game looks the same
    started from here or from HG.EXE. Returns a line for the log, or None when nothing changed."""
    try:
        import winreg
    except ImportError:            # not Windows
        return None
    if not uses_nglide_borderless(game):
        return None
    changed = []
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, NGLIDE_KEY, 0, winreg.KEY_READ | winreg.KEY_WRITE) as key:
        for name, value in NGLIDE_BORDERLESS.items():
            try:
                current = winreg.QueryValueEx(key, name)[0]
            except OSError:
                current = None
            if str(current) != value:
                winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
                changed.append(name)
    if not changed:
        return None
    return ("nGlide set to render at the desktop's resolution in 4:3 for the borderless window "
            "(nGlide's own settings: they apply to every game it runs).")


def disc2_plan(game, selected_fixes, apply_fixes, disc2_path, music_folder, image=""):
    """What the disc 2 section asks for: (disc 2 to copy the cutscenes from, drive or .mds image to rip the music
    from, folder of ripped tracks). `image`: the disc image disc2_path is the mounted drive of. An .iso has no
    CD-audio tracks to rip (though, mounted, it looks like a CD drive); an .mds/.mdf has them. An image not mounted
    yet is taken as disc 2 until it is. Raises ValueError/FileNotFoundError with a message for the player."""
    music = "music" in selected_fixes
    nodisc = music or "nodisc" in selected_fixes
    if not nodisc:
        return None, None, None
    if not apply_fixes:
        raise ValueError(
            "Playing without disc 2 is part of this project's fixes: tick \"Apply this project's "
            "fixes\" as well."
        )
    text = disc2_media.drive_root(disc2_path)
    have_videos = bool(installer_core.hgfix.find_file(str(game), "VIDEO/B51MOVIE.AVI"))
    disc2 = None
    image = image or (text if is_disc_image(text) else "")
    if text and is_disc_image(text):
        disc2 = text                      # not mounted yet (the window's requirements line)
    elif text:
        try:
            disc2 = str(disc2_media.find_disc2(text))
        except FileNotFoundError:
            if not have_videos:           # the cutscenes are still needed, so the path must be disc 2
                raise
    elif not have_videos:
        raise ValueError("Select disc 2 (or a folder copy of it) to copy the cutscenes from.")
    rip_drive = folder = None
    if music:
        folder = music_folder.strip() or None
        if folder:
            if not Path(folder).is_dir():
                raise FileNotFoundError("The folder of ripped tracks does not exist.")
        elif image and disc_image.is_mds(image):
            rip_drive = image                  # its audio tracks, read from the .mdf
        elif text and not image and disc2_media.is_cd_drive(text):
            rip_drive = text
        else:
            music_dir = installer_core.hgfix.find_file(str(game), "MUSIC")
            has_tracks = music_dir and any(item.lower().startswith("track") for item in os.listdir(music_dir))
            if not has_tracks:
                raise ValueError(
                    "To get the music, put disc 2 in the drive and select it, or choose a folder of "
                    "ripped TRACKnn files." + (" An .iso image holds no music tracks." if image else "")
                )
    return disc2, rip_drive, folder


def prepare_music(config, game, report):
    """Make the music available to hgfix. Returns (folder for hgfix to copy from or None, temp folder to delete
    afterwards or None). Ripping goes straight into the game's MUSIC folder when that is writable."""
    if config["music_folder"]:
        return config["music_folder"], None
    if not config["rip_drive"]:
        return None, None
    target = Path(game) / "MUSIC"
    temp = None
    try:
        target.mkdir(parents=True, exist_ok=True)
        probe = target / ".write-test"
        probe.write_bytes(b"")
        probe.unlink()
    except OSError:
        temp = tempfile.mkdtemp(prefix="hg-music-")
        target = Path(temp)
    try:
        opener = disc_image.MdsImage if disc_image.is_mds(config["rip_drive"]) else disc2_media.CdromDrive
        disc2_media.rip_audio(config["rip_drive"], target, report, opener=opener)
    except BaseException:
        if temp:
            shutil.rmtree(temp, ignore_errors=True)
        raise
    return (str(target) if temp else None), temp


class WindowsBackend(Backend):
    name = "windows"
    platform = "windows"
    can_stop = False
    location_label = "Game folder"
    location_title = "Choose the Heavy Gear game folder"
    patch_note = "Windows asks for administrator approval to run them."
    install_sections = ("cutscenes", "disc2_copy", "glide_copy")
    settings_extra = ("glide_driver",)
    disc_images = True

    # --- settings and the game ---------------------------------------------------------------
    def initial_choices(self, saved):
        choices = super().initial_choices(saved)
        codec = next((root / win_system.CODEC_NAME for root in search_roots()
                      if (root / win_system.CODEC_NAME).is_file()), None)
        choices.update(
            disc1=find_adjacent_disc1(),
            disc2=find_disc2(),
            install_media=not win_system.indeo_installed(),   # on until Windows has it: the cutscenes need it
            codec_path=str(codec) if codec else "",
            music_folder="",
            install_glide=False,
            glide_driver=saved.get("glide_driver") or str(installer_core.find_glide_driver() or ""),
        )
        return choices

    def indeo_installed(self):
        return win_system.indeo_installed()

    def game_folder(self, location):
        return Path(str(location).strip() or ".").expanduser()

    def find_game(self, saved=None):
        saved = self.load_settings() if saved is None else saved
        for candidate in (saved.get("game_path"), get_game_path_from_registry()):
            if candidate and has_game(Path(candidate).expanduser()):
                return str(candidate)
        return None

    def default_location(self, saved):
        return self.find_game(saved) or saved.get("game_path") or str(Path.home() / "Games" / "HeavyGear")

    def path_checks(self):
        def music(value):
            if not Path(value).expanduser().is_dir():
                raise FileNotFoundError("The folder of ripped tracks does not exist.")

        def codec(value):
            path = Path(value).expanduser()
            if path.name.casefold() != win_system.CODEC_NAME or not path.is_file():
                raise ValueError("Choose an extracted ir50_32.dll file for Indeo support.")

        def disc1(value):
            (check_image if is_disc_image(value) else installer_core.find_disc1)(value)

        def disc2(value):
            if is_disc_image(value):
                check_image(value)
            else:
                disc2_media.find_disc2(disc2_media.drive_root(value))

        return {
            **super().path_checks(),
            "disc1": disc1,
            "disc2": disc2,
            "codec_path": codec,
            "music_folder": music,
            "glide_driver": check_glide_driver,
        }

    def describe_error(self, exc):
        message = super().describe_error(exc)
        if isinstance(exc, PermissionError):
            message += (
                "\n\nWindows denied access to the target file. Close Heavy Gear and verify "
                "that the game folder allows writes. The app clears DLLFILE.INI's "
                "read-only attribute automatically, but it cannot override a file lock or "
                "a denying folder permission."
            )
        return message

    def missing_programs(self, choices):
        """What disc 2 the chosen fixes still need, phrased the way Install / Update refuses it."""
        lines = super().missing_programs(choices)
        selected, _ = backend.fix_lists(choices["fixes"])
        try:
            disc2_plan(Path(choices["location"]), selected, choices["apply_fixes"],
                       choices["disc2"], choices["music_folder"])
        except (ValueError, FileNotFoundError) as exc:
            lines.append(str(exc))
        return lines

    # --- install -------------------------------------------------------------------------------
    def validate_install(self, choices):
        """Disc images are mounted first (and their drives used from then on); they are dismounted again when the
        install ends (run_install) or when a check here refuses it."""
        choices, images = dict(choices), []
        disc2_image = choices["disc2"].strip() if is_disc_image(choices["disc2"]) else ""
        try:
            for key in ("disc1", "disc2"):
                if is_disc_image(choices[key]):
                    drive, mounted = mount_disc_image(choices[key].strip())
                    if mounted:
                        images.append(mounted)
                    choices[key] = drive
            config = self._validate_install(choices, disc2_image)
        except BaseException:
            dismount_images(images)
            raise
        config["mounted_images"] = images
        return config

    def cancel_install(self, config):
        dismount_images(config.get("mounted_images", ()))

    def _validate_install(self, choices, disc2_image):
        if not choices["location"].strip():
            raise ValueError("Choose an install folder.")
        game = Path(choices["location"]).expanduser().resolve()
        existing = has_game(game)
        source = choices["disc1"].strip()
        controls = choices["controls"]
        if existing:
            installer_core.find_game_folder(game)
            if controls not in ("keep existing", "wasd"):
                raise ValueError("Existing installations support Keep existing or WASD controls.")
        else:
            installer_core.find_disc1(source)
            if controls not in ("action", "sim", "wasd"):
                raise ValueError(f"Unknown control layout: {controls}")
        # An install already at official 1.2 needs no updates; don't demand patch files for them.
        already_12 = existing and installer_core.hgfix.game_version(str(game)) == "1.2"
        patches = []
        for version, key in (("1.1", "11"), ("1.2", "12")):
            patch = choices[f"patch{key}"].strip()
            if choices[f"apply{key}"] and not already_12:
                if not patch or not Path(patch).is_file():
                    raise FileNotFoundError(f"Browse to the official {version} patch executable.")
                expected_name = installer_core.PATCH_FILENAMES[version]
                if Path(patch).name.casefold() != expected_name:
                    raise ValueError(f"Select the official patch named '{expected_name}'.")
                resolved = Path(patch).resolve()
                # The hash travels with the request; the elevated side refuses a changed file.
                patches.append((version, str(resolved), installer_core.sha256_file(resolved)))
        versions = [patch[0] for patch in patches]
        if "1.1" in versions and not source:
            raise ValueError("Select disc 1 to verify a clean game before applying official 1.1.")
        if "1.1" in versions:
            installer_core.find_disc1(source)
        install_renderer = choices["install_renderer"]
        if install_renderer and not choices["apply12"] and not already_12:
            if choices["renderer_touched"]:
                raise ValueError(
                    "Direct3D 9 renderer requires the official 1.2 update. Select official 1.2, or choose "
                    "an existing installation that is already at 1.2."
                )
            install_renderer = False   # only the default was on: this run doesn't reach 1.2
        if choices["apply12"] and not choices["apply11"] and not existing:
            raise ValueError("The official 1.2 update follows 1.1. On a new install, select both updates.")
        if "1.1" in versions and "1.2" not in versions and choices["apply_fixes"]:
            raise ValueError(
                "This project's fixes support the disc version and official 1.2, not the "
                "intermediate 1.1 update. Apply 1.2 too or uncheck community fixes."
            )
        codec_path = choices["codec_path"].strip() or None
        if choices["install_media"]:
            if not source:      # the fonts come from disc 1 even when an extracted codec is chosen
                raise ValueError("Cutscene support (Indeo 5 and the game fonts) needs disc 1: select the disc 1 "
                                 "drive or folder, or untick \"Install Indeo 5 and the game fonts\".")
            installer_core.find_disc1(source)
            with tempfile.TemporaryDirectory(prefix="hg-indeo-") as workdir:
                win_system.resolve_indeo_codec(codec_path, source, workdir)
        glide_driver = None
        if choices["install_glide"]:
            if not choices["glide_driver"].strip():
                raise FileNotFoundError("Browse to a glide2x.dll (install nGlide first) to set up 3Dfx support.")
            glide_driver = str(check_glide_driver(choices["glide_driver"].strip()))
        selected, skipped = backend.fix_lists(choices["fixes"])
        disc2, rip_drive, music_folder = disc2_plan(
            game, selected, choices["apply_fixes"], choices["disc2"], choices["music_folder"], disc2_image
        )
        return {
            "disc2": disc2,
            "rip_drive": rip_drive,
            "music_folder": music_folder,
            "game": str(game),
            "source": source,
            "existing": existing,
            "controls": controls,
            "patches": patches,
            "apply_fixes": choices["apply_fixes"],
            "install_renderer": install_renderer,
            "install_media": choices["install_media"],
            "codec_path": codec_path,
            "glide_driver": glide_driver,
            "menu_fps": float(choices["menu_fps"]),
            "sim_fps": float(choices["sim_fps"]),
            "fixes": selected,
            "skipped": skipped,
        }

    def run_install(self, config, report, on_process=None):
        temp_music = None
        try:
            report("Copying or validating the game files...")
            try:
                game = installer_core.install_game(
                    config["source"], config["game"], config["controls"], config["existing"]
                )
            except PermissionError:
                report("Windows requires administrator approval to install into that folder.")
                game = Path(run_elevated_config({
                    "operation": "install",
                    "source": config["source"],
                    "game": config["game"],
                    "controls": config["controls"],
                    "existing": config["existing"],
                }))
            report(f"Game files are ready in: {game}")
            if config["rip_drive"] or config["music_folder"]:
                report("Preparing the music from disc 2...")
                config["music_from"], temp_music = prepare_music(config, game, report)
                report("The music is ready.")
            if config["patches"]:
                report("Official patchers require administrator approval; Windows will show a UAC prompt.")
                report("Waiting for the official patchers and administrator approval...")
                output = run_elevated_config({
                    "operation": "official",
                    "game": str(game),
                    "disc1": config["source"] or None,
                    "patches": config["patches"],
                    "apply_fixes": config["apply_fixes"],
                    "install_renderer": config["install_renderer"],
                    "install_media": config["install_media"],
                    "source": config["source"],
                    "codec_path": config["codec_path"],
                    "glide_driver": config["glide_driver"],
                    "menu_fps": config["menu_fps"],
                    "sim_fps": config["sim_fps"],
                    "fixes": config["fixes"],
                    "skipped": config["skipped"],
                    "disc2": config["disc2"],
                    "music_from": config.get("music_from"),
                })
            else:
                project_config = {"operation": "project", **config}
                try:
                    if config["install_media"]:
                        report("Cutscene support changes Windows system components; Windows will show a UAC prompt.")
                        output = run_elevated_config(project_config)
                    else:
                        report("Applying community fixes and renderer...")
                        output = installer_core.run_privileged_operation(project_config)
                except PermissionError:
                    report("Windows requires administrator approval to modify this game folder.")
                    output = run_elevated_config(project_config)
            if output:
                report(output)
        finally:
            if temp_music:
                shutil.rmtree(temp_music, ignore_errors=True)
            dismount_images(config.get("mounted_images", ()))
        return disc_note(config["fixes"]), game

    # --- play ----------------------------------------------------------------------------------
    def plan_apply(self, choices):
        plan = super().plan_apply(choices)
        renderer = plan["renderer_settings"].get("DLLFILE.INI", "")
        listed = [name.casefold() for name in installer_core.listed_renderers(plan["game"])]
        if renderer and renderer.casefold() != installer_core.SOFTWARE_RENDERER and renderer.casefold() not in listed:
            # The game would not list it, and puts its own Graphics Type back at the next mission.
            if renderer.casefold() == "3dfxgear.dll":
                raise ValueError("3Dfx needs a Glide driver. Install nGlide and tick \"Set up 3Dfx\" on the "
                                 "Install & update page, or choose another renderer.")
            raise ValueError(f"The game does not offer {renderer} in its Graphics Type list. Choose another renderer.")
        return plan

    def apply(self, plan, report):
        """Apply fixes and renderer settings, asking for administrator rights if needed."""
        game, fixes = plan["game"], plan["fixes"]
        try:
            report(backend.apply_fixes(game, plan, self.platform))
        except PermissionError:
            selected, skipped = backend.fix_lists(fixes)
            report(run_elevated_config({
                "operation": "fixes",
                "game": str(game),
                "menu_fps": float(plan["menu_fps"]),
                "sim_fps": float(plan["sim_fps"]),
                "fixes": selected,
                "skipped": skipped,
            }))
        try:
            for filename, value in plan["renderer_settings"].items():
                installer_core.write_setting(game / filename, value)
            renderer = plan["renderer_settings"].get("DLLFILE.INI")
            note = installer_core.select_graphics_type(game, renderer) if renderer else None
            if note:
                report(note)
        except PermissionError:
            report(run_elevated_config({
                "operation": "settings",
                "game": str(game),
                "settings": plan["renderer_settings"],
            }))
        note = set_nglide_for_borderless(game)      # after DLLFILE.INI, which it reads
        if note:
            report(note)

    def play(self, plan, report, on_process=None):
        game = plan["game"]
        subprocess.Popen([str(game / "HG.EXE")], cwd=game)
        report("Heavy Gear started.")
