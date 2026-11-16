"""Install and repair the ``acpi_call`` kernel module that fan control needs.

The plugin ships the unmodified ``acpi_call`` sources (``defaults/acpi_call``).
This module copies them to ``/var/lib/legion-fan-support``, installs a small
systemd service that builds the module for the running kernel when it is
missing (so kernel updates are handled at boot), and loads it.

Nothing here touches the read-only system image: only ``/var`` and ``/etc``
are written. Every step is idempotent so it can be used for both first
install and repair.
"""

from pathlib import Path
import os
import platform
import shutil
import subprocess
from typing import Callable, Optional

BASE_DIR = Path("/var/lib/legion-fan-support")
SERVICE_NAME = "legion-fan-support.service"
SERVICE_PATH = Path("/etc/systemd/system") / SERVICE_NAME
PROC_PATH = Path("/proc/acpi/call")
SOURCE_FILES = ("acpi_call.c", "Makefile", "VERSION", "LICENSE")

LOAD_SCRIPT = """#!/bin/bash
set -euo pipefail
base=/var/lib/legion-fan-support
kernel=$(uname -r)
test -e /proc/acpi/call && exit 0
if ! /usr/sbin/modprobe acpi_call 2>/dev/null; then
    build="$base/build/$kernel"
    if ! test -f "$build/acpi_call.ko"; then
        test -d "/lib/modules/$kernel/build" || {
            echo "Kernel headers missing for $kernel; fan control unavailable" >&2
            exit 1
        }
        mkdir -p "$build"
        cp "$base/src/"{acpi_call.c,Makefile,VERSION} "$build/"
        make -C "$build" -j2
    fi
    /usr/sbin/restorecon "$build/acpi_call.ko" 2>/dev/null || true
    /usr/sbin/insmod "$build/acpi_call.ko"
fi
test -e /proc/acpi/call
chmod 0600 /proc/acpi/call
"""

SERVICE_UNIT = """[Unit]
Description=Legion Go ACPI fan-control module for the current kernel
After=local-fs.target
Before=plugin_loader.service
ConditionPathExists=/var/lib/legion-fan-support/src/acpi_call.c

[Service]
Type=oneshot
ExecStart=/usr/bin/bash /var/lib/legion-fan-support/load-module.sh
RemainAfterExit=yes
TimeoutStartSec=180

[Install]
WantedBy=multi-user.target
"""


class FanSupportError(RuntimeError):
    """Raised with a message that is safe to show to the user."""


def bundled_source_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "defaults" / "acpi_call"


def _env():
    return {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin"}


def secure_boot_enabled(runner: Callable = subprocess.run) -> bool:
    try:
        result = runner(
            ["mokutil", "--sb-state"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=_env(),
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return "SecureBoot enabled" in (result.stdout or "")


def _write_if_changed(path: Path, data: bytes, mode: int) -> bool:
    if path.is_file() and path.read_bytes() == data:
        os.chmod(path, mode)
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(data)
    os.chmod(temporary, mode)
    os.replace(temporary, path)
    return True


def write_files(
    source_dir: Optional[Path] = None,
    base_dir: Path = BASE_DIR,
    service_path: Path = SERVICE_PATH,
) -> bool:
    """Copy the module sources, loader script and unit. Returns True if the unit changed."""
    source_dir = Path(source_dir) if source_dir else bundled_source_dir()
    missing = [name for name in SOURCE_FILES if not (source_dir / name).is_file()]
    if missing:
        raise FanSupportError("Bundled acpi_call sources are missing: " + ", ".join(missing))
    for name in SOURCE_FILES:
        _write_if_changed(base_dir / "src" / name, (source_dir / name).read_bytes(), 0o644)
    _write_if_changed(base_dir / "load-module.sh", LOAD_SCRIPT.encode(), 0o755)
    return _write_if_changed(service_path, SERVICE_UNIT.encode(), 0o644)


def _run(runner, command, timeout):
    try:
        return runner(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=_env(),
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as error:
        raise FanSupportError("Building the fan module timed out") from error
    except OSError as error:
        raise FanSupportError(f"Could not run {command[0]}: {error}") from error


def _failure_message(output: str, kernel: str, runner) -> str:
    text = (output or "").lower()
    if "kernel headers missing" in text or ("/lib/modules" in text and "no such file" in text):
        return (
            f"Kernel headers for {kernel} are missing. Update Bazzite and reboot, "
            "then try again."
        )
    if "make: not found" in text or "gcc: not found" in text or "command not found" in text:
        return "A compiler (gcc/make) is missing, so the fan module cannot be built."
    if "required key not available" in text or "key was rejected" in text:
        return "Secure Boot rejected the unsigned fan module. Disable Secure Boot or enroll a key."
    if secure_boot_enabled(runner):
        return "Secure Boot is enabled and may block the unsigned fan module."
    return "Building or loading the fan module failed. See the Decky plugin log for details."


def install(
    source_dir: Optional[Path] = None,
    base_dir: Path = BASE_DIR,
    service_path: Path = SERVICE_PATH,
    proc_path: Path = PROC_PATH,
    runner: Callable = subprocess.run,
    kernel_release: Optional[str] = None,
    logger=None,
) -> None:
    """Install (or repair) fan support and verify ``/proc/acpi/call`` exists."""
    kernel = kernel_release or platform.release()
    if shutil.which("systemctl") is None and runner is subprocess.run:
        raise FanSupportError("systemd is required to install fan support")
    write_files(source_dir, base_dir, service_path)
    _run(runner, ["systemctl", "daemon-reload"], 30)
    _run(runner, ["systemctl", "enable", SERVICE_NAME], 30)
    result = _run(runner, ["systemctl", "restart", SERVICE_NAME], 200)
    if logger is not None and result.stdout:
        logger.info(f"fan support service output: {result.stdout.strip()[-800:]}")
    if result.returncode != 0 or not proc_path.exists():
        journal = _run(
            runner, ["journalctl", "-u", SERVICE_NAME, "-n", "30", "--no-pager"], 15
        )
        raise FanSupportError(_failure_message((journal.stdout or "") + (result.stdout or ""), kernel, runner))
