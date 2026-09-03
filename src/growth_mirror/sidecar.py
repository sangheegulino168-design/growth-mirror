from __future__ import annotations

import argparse
import ctypes
import os
from pathlib import Path
import threading
import traceback


def default_data_directory() -> Path:
    """Return a per-user writable directory without requiring extra packages."""

    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "GrowthMirror"
    return Path.home() / ".growth-mirror"


def configure_runtime() -> Path:
    """Create the data directory and select its database unless explicitly overridden."""

    configured_path = os.environ.get("GROWTH_MIRROR_DB_PATH")
    database_path = (
        Path(configured_path)
        if configured_path
        else default_data_directory() / "growth_mirror.db"
    )
    database_path.parent.mkdir(parents=True, exist_ok=True)
    os.environ["GROWTH_MIRROR_DB_PATH"] = str(database_path)
    return database_path


def _exit_when_windows_parent_exits(parent_pid: int) -> None:
    """Tie a PyInstaller child process to the desktop process lifecycle."""

    synchronize = 0x00100000
    infinite = 0xFFFFFFFF
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]

    handle = kernel32.OpenProcess(synchronize, False, parent_pid)
    if not handle:
        # The desktop process already exited before the sidecar finished loading.
        os._exit(0)
    try:
        kernel32.WaitForSingleObject(handle, infinite)
    finally:
        kernel32.CloseHandle(handle)
    os._exit(0)


def start_parent_watchdog(parent_pid: int | None) -> None:
    if parent_pid is None or os.name != "nt":
        return
    threading.Thread(
        target=_exit_when_windows_parent_exits,
        args=(parent_pid,),
        name="growth-mirror-parent-watchdog",
        daemon=True,
    ).start()


def main() -> None:
    # Importing here keeps the cognitive core usable without API dependencies.
    import uvicorn

    from growth_mirror.api import create_configured_app

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--parent-pid", type=int)
    arguments, _ = parser.parse_known_args()

    database_path = configure_runtime()
    start_parent_watchdog(arguments.parent_pid)
    try:
        uvicorn.run(
            create_configured_app(),
            host="127.0.0.1",
            port=8765,
            log_config=None,
            access_log=False,
        )
    except Exception:
        # Windowed executables do not have a console. Keep one local diagnostic
        # file so startup failures remain explainable to the user and developer.
        (database_path.parent / "sidecar-error.log").write_text(
            traceback.format_exc(), encoding="utf-8"
        )
        raise


if __name__ == "__main__":
    main()
