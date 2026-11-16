"""Optional Legion Go lighting and privacy-preserving system diagnostics.

Sleep LED protocol reference:
https://github.com/hhd-dev/adjustor/blob/master/src/adjustor/core/lenovo.py
Native RGB interface reference:
https://docs.kernel.org/leds/leds-class-multicolor.html
"""

from pathlib import Path
import platform
import re
import subprocess


SLEEP_LED_METHOD = r"\_SB.GZFD.WMAF"
SLEEP_LED_SELECTOR = 0x24
SLEEP_LED_OFF = 0x01
SLEEP_LED_ON = 0x03
RGB_DEVICE_NAME = "go:rgb:joystick_rings"
RGB_ROOT = Path("/sys/class/leds")
RGB_CHANNELS = ("red", "green", "blue")
SERVICES = ("inputplumber", "powerstation", "steamos-manager", "legion-fan-support")


def sleep_led_status(call, read):
    """Read only the independently controlled suspend indicator state."""
    try:
        if not call(SLEEP_LED_METHOD, [0, 1, SLEEP_LED_SELECTOR], risky=False):
            raise ValueError("query failed")
        response = read()
        if (
            not isinstance(response, bytes)
            or len(response) != 2
            or response[1] not in (SLEEP_LED_OFF, SLEEP_LED_ON)
        ):
            raise ValueError("unsupported response")
        return {
            "success": True,
            "supported": True,
            "enabled": response[1] == SLEEP_LED_ON,
            "error": None,
        }
    except Exception:
        return {
            "success": False,
            "supported": False,
            "enabled": None,
            "error": "The firmware sleep LED interface is unavailable or returned an unsupported state.",
        }


def set_sleep_led(enabled, call, read):
    """Set suspend lighting and persist nothing unless firmware confirms it."""
    if type(enabled) is not bool:
        return {"success": False, "error": "Sleep LED state must be boolean."}
    current = sleep_led_status(call, read)
    if not current["supported"] or current["enabled"] == enabled:
        return current
    try:
        mode = SLEEP_LED_ON if enabled else SLEEP_LED_OFF
        if not call(SLEEP_LED_METHOD, [0, 2, bytes([SLEEP_LED_SELECTOR, 0, mode])]):
            raise ValueError("write failed")
        verified = sleep_led_status(call, read)
        if not verified["supported"] or verified["enabled"] != enabled:
            raise ValueError("verification failed")
        return verified
    except Exception:
        return {
            **current,
            "success": False,
            "error": "The firmware did not confirm the requested sleep LED state.",
        }


def _read_rgb(led_root):
    device = Path(led_root) / RGB_DEVICE_NAME
    indexes = (device / "multi_index").read_text(encoding="ascii").split()
    if len(indexes) != 3 or set(indexes) != set(RGB_CHANNELS):
        raise ValueError("unsupported channels")
    maximum = int((device / "max_brightness").read_text(encoding="ascii"))
    brightness = int((device / "brightness").read_text(encoding="ascii"))
    intensity = [int(x) for x in (device / "multi_intensity").read_text(encoding="ascii").split()]
    channel_limits = device / "multi_max_intensity"
    limits = (
        [int(x) for x in channel_limits.read_text(encoding="ascii").split()]
        if channel_limits.exists()
        else [maximum] * 3
    )
    if (
        maximum <= 0
        or not 0 <= brightness <= maximum
        or len(intensity) != 3
        or len(limits) != 3
        or any(limit <= 0 or not 0 <= value <= limit for value, limit in zip(intensity, limits))
    ):
        raise ValueError("invalid RGB capabilities")
    trigger_path = device / "trigger"
    trigger = "none"
    if trigger_path.exists():
        matches = re.findall(r"\[([^\]]+)\]", trigger_path.read_text(encoding="ascii"))
        if len(matches) != 1:
            raise ValueError("unknown trigger")
        trigger = matches[0]
    return device, indexes, maximum, brightness, intensity, limits, trigger


def rgb_status(led_root=RGB_ROOT):
    """Expose normalized channel values without device paths or serial numbers."""
    try:
        _, indexes, maximum, brightness, intensity, limits, trigger = _read_rgb(led_root)
        return {
            "success": True,
            "supported": True,
            "writable": trigger == "none",
            "brightness": round(brightness * 100 / maximum),
            "color": {
                name: round(value * 100 / limit)
                for name, value, limit in zip(indexes, intensity, limits)
            },
            "error": None if trigger == "none" else "An active LED trigger controls the rings. Manual changes are disabled.",
        }
    except (OSError, ValueError, UnicodeError):
        return {
            "success": False,
            "supported": False,
            "writable": False,
            "error": "The native joystick RGB interface is unavailable or unsupported.",
        }


def _write_value(path, value):
    path.write_text(value + "\n", encoding="ascii")


def set_rgb(brightness, color, led_root=RGB_ROOT, writer=_write_value):
    """Write the native RGB attributes once, verify them, and roll back on failure.

    Only this explicit operation writes to the LED. No poller, startup restore,
    trigger change, or controller-service restart competes with other RGB tools.
    """
    if (
        type(brightness) is not int
        or not 0 <= brightness <= 100
        or not isinstance(color, dict)
        or set(color) != set(RGB_CHANNELS)
        or any(type(value) is not int or not 0 <= value <= 100 for value in color.values())
    ):
        return {"success": False, "error": "Brightness and each RGB channel must be integers from 0 to 100."}
    current = rgb_status(led_root)
    if not current.get("supported") or not current.get("writable"):
        return {**current, "success": False}
    try:
        device, indexes, maximum, old_brightness, old_intensity, limits, _ = _read_rgb(led_root)
    except (OSError, ValueError, UnicodeError):
        return {"success": False, "error": "Could not read the current RGB state."}
    desired_brightness = round(brightness * maximum / 100)
    desired_intensity = [round(color[name] * limit / 100) for name, limit in zip(indexes, limits)]
    try:
        writer(device / "multi_intensity", " ".join(map(str, desired_intensity)))
        writer(device / "brightness", str(desired_brightness))
        _, _, _, actual_brightness, actual_intensity, _, trigger = _read_rgb(led_root)
        if actual_brightness != desired_brightness or actual_intensity != desired_intensity or trigger != "none":
            raise ValueError("verification failed")
        return rgb_status(led_root)
    except (OSError, ValueError, UnicodeError):
        try:
            writer(device / "multi_intensity", " ".join(map(str, old_intensity)))
            writer(device / "brightness", str(old_brightness))
            restored = _read_rgb(led_root)
            if restored[3] != old_brightness or restored[4] != old_intensity:
                raise ValueError("rollback verification failed")
        except (OSError, ValueError, UnicodeError):
            return {"success": False, "error": "RGB verification failed, and the previous state could not be restored. Check the device before retrying."}
        return {**current, "success": False, "error": "RGB verification failed. The previous state was restored."}


def _read_text(path):
    try:
        return path.read_text(encoding="ascii").strip()
    except (OSError, UnicodeError):
        return ""


def diagnostics(sys_root=Path("/sys"), proc_root=Path("/proc"), etc_root=Path("/etc"), runner=subprocess.run):
    """Collect an explicit allowlist; never return raw logs, paths, or HID identities."""
    sys_root, proc_root, etc_root = map(Path, (sys_root, proc_root, etc_root))
    product = _read_text(sys_root / "class/dmi/id/product_name")
    model = {"83E1": "Legion Go 8APU1", "83N0": "Legion Go 2", "83N1": "Legion Go 2"}.get(product, "Unrecognized model")
    bios = _read_text(sys_root / "class/dmi/id/bios_version")
    if not re.fullmatch(r"N[A-Z0-9]*CN[0-9]+WW", bios):
        bios = "Unavailable"
    release = platform.release()
    if not re.fullmatch(r"[0-9][A-Za-z0-9._+-]{0,100}", release):
        release = "Unavailable"
    os_release = {}
    for line in _read_text(etc_root / "os-release").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            value = value.strip('"')
            if key in ("ID", "VERSION_ID") and re.fullmatch(r"[A-Za-z0-9._-]{1,40}", value):
                os_release[key] = value
    services = {name: "unknown" for name in SERVICES}
    try:
        result = runner(
            ["systemctl", "is-active", *[name + ".service" for name in SERVICES]],
            capture_output=True, text=True, timeout=5, env={"PATH": "/usr/sbin:/usr/bin"},
        )
        values = result.stdout.splitlines()
        if len(values) == len(SERVICES):
            for name, state in zip(SERVICES, values):
                if state in ("active", "inactive", "failed", "activating", "deactivating", "unknown"):
                    services[name] = state
    except (OSError, subprocess.SubprocessError):
        pass
    versions = {}
    try:
        result = runner(
            ["rpm", "--query", "--queryformat", "%{NAME} %{VERSION}-%{RELEASE}\n",
             "inputplumber", "powerstation", "steamos-manager-powerstation"],
            capture_output=True, text=True, timeout=5, env={"PATH": "/usr/sbin:/usr/bin"},
        )
        for line in result.stdout.splitlines():
            match = re.fullmatch(r"(inputplumber|powerstation|steamos-manager-powerstation) ([0-9][A-Za-z0-9._+~^-]{0,100})", line)
            if match:
                versions[match[1]] = match[2]
    except (OSError, subprocess.SubprocessError):
        pass
    controller_present = False
    for event in (sys_root / "class/hidraw").glob("hidraw*/device/uevent"):
        if re.search(r"^HID_ID=0003:000017EF:000061(?:8[2-5]|E[B-E])$", _read_text(event), re.MULTILINE | re.IGNORECASE):
            controller_present = True
            break
    gyro_count = sum(
        1 for name in (sys_root / "bus/iio/devices").glob("iio:device*/name")
        if "gyro" in _read_text(name).lower()
    )
    modules = _read_text(proc_root / "modules")
    return {
        "model": model,
        "bios": bios,
        "kernel": release,
        "os": os_release.get("ID", "Unavailable"),
        "os_version": os_release.get("VERSION_ID", "Unavailable"),
        "services": services,
        "versions": versions,
        "fan_interface": (proc_root / "acpi/call").exists(),
        "fan_module_loaded": any(line.split() and line.split()[0] == "acpi_call" for line in modules.splitlines()),
        "controller_present": controller_present,
        "gyro_devices": gyro_count,
        "rgb_supported": rgb_status(sys_root / "class/leds")["supported"],
    }
