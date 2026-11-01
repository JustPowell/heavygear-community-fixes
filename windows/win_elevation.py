"""Run one operation in an elevated copy of this program (UAC) and bring the result back.

The request travels on the elevated process's command line, so there is no file a
lower-privileged process could rewrite between the UAC prompt and the elevated read. The
result comes back over a private, authenticated connection (a named pipe on Windows) whose
key only the two processes know.
"""

import base64
import ctypes
import json
import multiprocessing
import os
import secrets
import subprocess
import sys
import tempfile
import threading
import traceback
from multiprocessing.connection import Client, Listener
from pathlib import Path

ELEVATED_FLAG = "--elevated-op"
MAX_RESULT_BYTES = 1 << 20
ERROR_CANCELLED = 1223


def encode_request(config, address, key):
    request = {"config": config, "address": address, "key": key.hex()}
    return base64.urlsafe_b64encode(json.dumps(request).encode("utf-8")).decode("ascii")


def decode_request(encoded):
    request = json.loads(base64.urlsafe_b64decode(encoded.encode("ascii")))
    return request["config"], request["address"], bytes.fromhex(request["key"])


def elevated_entry(encoded, run):
    """Entry point of the elevated process: run the operation and report to the parent."""
    config, address, key = decode_request(encoded)
    try:
        result = {"output": run(config)}
    except Exception as exc:
        message = str(exc) or exc.__class__.__name__
        # Name where it failed: an elevated failure has no console, so a bare "[WinError 5]"
        # would otherwise say nothing about which step was refused.
        if not isinstance(exc, (RuntimeError, ValueError, FileNotFoundError, FileExistsError)):
            frame = traceback.extract_tb(exc.__traceback__)[-1]
            message += f" (in {frame.name}, {Path(frame.filename).name}:{frame.lineno}: {frame.line})"
        result = {"error": message}
    try:
        with Client(address, authkey=key) as connection:
            connection.send_bytes(json.dumps(result).encode("utf-8"))
    except (OSError, EOFError):
        pass
    return 1 if "error" in result else 0


class ResultChannel:
    """Parent side of the connection the elevated process reports through."""

    def __init__(self, address=None):
        self.key = secrets.token_bytes(32)
        if address is None:
            token = secrets.token_hex(8)
            if os.name == "nt":
                address = rf"\\.\pipe\hgfix-{token}"
            else:
                address = os.path.join(tempfile.mkdtemp(prefix="hgfix-"), "result.sock")
        self.address = address
        self.result = None
        self._stop = False
        self._listener = Listener(address, authkey=self.key)
        self._thread = threading.Thread(target=self._accept, daemon=True)
        self._thread.start()

    def _accept(self):
        while self.result is None and not self._stop:
            try:
                with self._listener.accept() as connection:
                    data = connection.recv_bytes(MAX_RESULT_BYTES)
                self.result = json.loads(data.decode("utf-8"))
            except multiprocessing.AuthenticationError:
                continue  # wrong key: ignore the stranger and keep waiting for the real client
            except (OSError, EOFError, ValueError):
                if self._stop:
                    return

    def finish(self):
        """Call once the elevated process has exited; returns its result dict or None."""
        self._thread.join(0.5)
        if self._thread.is_alive():
            self._stop = True
            try:  # wake the blocked accept() so the thread can end
                Client(self.address, authkey=self.key).close()
            except (OSError, EOFError, multiprocessing.AuthenticationError):
                pass
            self._thread.join(5)
        try:
            self._listener.close()
        except OSError:
            pass
        return self.result


class _ShellExecuteInfo(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_ulong),
        ("fMask", ctypes.c_ulong),
        ("hwnd", ctypes.c_void_p),
        ("lpVerb", ctypes.c_wchar_p),
        ("lpFile", ctypes.c_wchar_p),
        ("lpParameters", ctypes.c_wchar_p),
        ("lpDirectory", ctypes.c_wchar_p),
        ("nShow", ctypes.c_int),
        ("hInstApp", ctypes.c_void_p),
        ("lpIDList", ctypes.c_void_p),
        ("lpClass", ctypes.c_wchar_p),
        ("hkeyClass", ctypes.c_void_p),
        ("dwHotKey", ctypes.c_ulong),
        ("hIconOrMonitor", ctypes.c_void_p),
        ("hProcess", ctypes.c_void_p),
    ]


def _self_command(encoded):
    if getattr(sys, "frozen", False):
        return sys.executable, [f"{ELEVATED_FLAG}={encoded}"]
    script = Path(sys.argv[0]).resolve()  # whichever app started this operation
    return sys.executable, [str(script), f"{ELEVATED_FLAG}={encoded}"]


def _runas_and_wait(encoded):
    """Start this program elevated (UAC prompt), wait for it, return its exit code."""
    if os.name != "nt":
        raise OSError("Administrator elevation is only supported on Windows.")
    executable, parameters = _self_command(encoded)
    info = _ShellExecuteInfo()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = 0x00000040  # SEE_MASK_NOCLOSEPROCESS
    info.lpVerb = "runas"
    info.lpFile = executable
    info.lpParameters = subprocess.list2cmdline(parameters)
    info.lpDirectory = str(Path(executable).parent)
    info.nShow = 0
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    shell_execute = shell32.ShellExecuteExW
    shell_execute.argtypes = [ctypes.POINTER(_ShellExecuteInfo)]
    shell_execute.restype = ctypes.c_int
    wait_for_single_object = kernel32.WaitForSingleObject
    wait_for_single_object.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    wait_for_single_object.restype = ctypes.c_ulong
    get_exit_code = kernel32.GetExitCodeProcess
    get_exit_code.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
    get_exit_code.restype = ctypes.c_int
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [ctypes.c_void_p]
    close_handle.restype = ctypes.c_int
    if not shell_execute(ctypes.byref(info)):
        error = ctypes.get_last_error()
        if error == ERROR_CANCELLED:
            raise PermissionError("Administrator approval was cancelled.")
        raise OSError(error, "Windows could not start the elevated operation.")
    try:
        if wait_for_single_object(info.hProcess, 0xFFFFFFFF) != 0:
            raise OSError(ctypes.get_last_error(), "Waiting for the elevated operation failed.")
        exit_code = ctypes.c_ulong()
        if not get_exit_code(info.hProcess, ctypes.byref(exit_code)):
            raise OSError(ctypes.get_last_error(), "Could not read the operation's exit code.")
        return exit_code.value
    finally:
        close_handle(info.hProcess)


def run_elevated(config, launch=_runas_and_wait, address=None):
    """Run `config` through installer_core.run_privileged_operation as administrator.

    `launch(encoded_request)` starts the elevated process, blocks until it exits and returns
    its exit code; it is a parameter so tests can run the child in-process.
    """
    channel = ResultChannel(address)
    exit_code = None
    try:
        exit_code = launch(encode_request(config, channel.address, channel.key))
    finally:
        result = channel.finish()
    if exit_code:
        raise RuntimeError(
            (result or {}).get("error")
            or f"The elevated operation failed (exit code {exit_code})."
        )
    if result is None:
        raise RuntimeError("The elevated operation finished without reporting a result.")
    if "error" in result:
        raise RuntimeError(result["error"])
    return result.get("output", "")
