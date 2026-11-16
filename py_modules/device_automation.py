"""Opt-in fan profile transitions and real logind suspend-boundary telemetry.

Only an AC/battery transition or an explicit Apply action can select a fan slot.
No controller-service restart, TDP override, or heuristic sleep-gap detection is used.
"""

import asyncio
from copy import deepcopy
import hashlib
import inspect
import os
from pathlib import Path
import re
import signal
import time

try:
    from . import fan_presets
except ImportError:
    import fan_presets


POWER_SUPPLY_ROOT = Path("/sys/class/power_supply")
SLEEP_MATCH = (
    "type='signal',sender='org.freedesktop.login1',path='/org/freedesktop/login1',"
    "interface='org.freedesktop.login1.Manager',member='PrepareForSleep'"
)
POWER_TYPES = {"Mains", "USB", "USB_C", "USB_PD", "USB_DCP", "USB_CDP", "USB_ACA"}
SUMMARY_FIELDS = (
    "started_at", "ended_at", "duration_seconds", "battery_before", "battery_after",
    "battery_change_percentage", "battery_loss_percentage", "loss_per_hour",
    "energy_change_wh", "average_battery_drain_w",
)
HEALTH_STATES = {"verified", "different", "unavailable", "automatic", "not_configured", "recovery_required", "full_speed"}
INHIBITOR_HELPER = """import subprocess, sys
try:
    result = subprocess.run(['busctl', '--system', 'get-property', 'org.freedesktop.login1',
        '/org/freedesktop/login1', 'org.freedesktop.login1.Manager', 'InhibitDelayMaxUSec'],
        capture_output=True, text=True, timeout=2, check=True)
    parts = result.stdout.split()
    if len(parts) != 2 or parts[0] != 't' or not parts[1].isdigit() or int(parts[1]) <= 0:
        raise ValueError('invalid delay limit')
    print('READY ' + parts[1], flush=True)
    sys.stdin.buffer.read()
except Exception:
    sys.exit(1)
"""


def _text(path):
    try:
        return path.read_text(encoding="ascii").strip()
    except (OSError, UnicodeError):
        return ""


def _integer(path, maximum=None):
    try:
        value = int(_text(path))
        return value if value >= 0 and (maximum is None or value <= maximum) else None
    except ValueError:
        return None


def read_power_sample(root=POWER_SUPPLY_ROOT):
    root = Path(root)
    batteries = []
    external = []
    for supply in sorted(root.glob("*")):
        kind = _text(supply / "type")
        if kind == "Battery":
            batteries.append(supply)
        elif kind in POWER_TYPES:
            value = _integer(supply / "online", 1)
            if value is not None:
                external.append(value)
    battery = batteries[0] if batteries else None
    if any(external):
        source = "ac"
    elif external and battery:
        source = "battery"
    elif battery and _text(battery / "status") == "Discharging":
        source = "battery"
    elif battery and _text(battery / "status") == "Charging":
        source = "ac"
    else:
        source = "unknown"
    return {
        "source": source,
        "capacity": _integer(battery / "capacity", 100) if battery else None,
        "energy_now": _integer(battery / "energy_now") if battery else None,
    }


def boottime():
    # Unlike CLOCK_MONOTONIC, CLOCK_BOOTTIME includes time spent suspended.
    return time.clock_gettime(time.CLOCK_BOOTTIME)


def boot_marker(path=Path("/proc/sys/kernel/random/boot_id")):
    value = _text(path)
    return hashlib.sha256(value.encode("ascii")).hexdigest() if value else None


def validate_config(config):
    if (
        not isinstance(config, dict) or type(config.get("enabled")) is not bool
        or config.get("ac_slot") not in fan_presets.SLOTS
        or config.get("battery_slot") not in fan_presets.SLOTS
    ):
        raise ValueError("Choose one of the three profiles for AC and battery power.")
    return {"enabled": config["enabled"], "ac_slot": config["ac_slot"], "battery_slot": config["battery_slot"]}


class SleepSignalParser:
    """Accept only the boolean argument of the filtered login1 signal."""

    def __init__(self):
        self.pending = False
        self.timestamp = None

    def feed(self, line):
        if line.startswith("signal "):
            self.pending = (
                "path=/org/freedesktop/login1;" in line
                and "interface=org.freedesktop.login1.Manager;" in line
                and "member=PrepareForSleep" in line
                and not re.search(r"member=PrepareForSleep\w", line)
            )
            timestamp = re.search(r"\btime=([0-9]+(?:\.[0-9]+)?)\s", line)
            self.timestamp = float(timestamp[1]) if self.pending and timestamp else None
            return None
        if self.pending:
            match = re.fullmatch(r"\s*boolean (true|false)\s*", line)
            if match:
                self.pending = False
                return match[1] == "true"
            if line.strip():
                self.pending = False
        return None


def sleep_summary(pending, sample, now, ended_at, marker):
    if (
        not isinstance(pending, dict) or pending.get("reliable") is not True
        or marker is None or pending.get("boot_marker") != marker
        or not isinstance(pending.get("boottime"), (float, int))
        or type(pending.get("started_at")) is not int
    ):
        raise ValueError("There is no matching sleep entry for this boot.")
    duration = now - pending["boottime"]
    if not 0 < duration < 366 * 24 * 3600:
        raise ValueError("The sleep duration is unavailable.")
    before = pending.get("battery", {}).get("capacity")
    after = sample.get("capacity")
    valid_capacity = all(type(value) is int and 0 <= value <= 100 for value in (before, after))
    change = after - before if valid_capacity else None
    loss = max(0, -change) if change is not None else None
    energy_before = pending.get("battery", {}).get("energy_now")
    energy_after = sample.get("energy_now")
    valid_energy = all(type(value) is int and value >= 0 for value in (energy_before, energy_after))
    energy_change = (energy_after - energy_before) / 1_000_000 if valid_energy else None
    return {
        "started_at": pending["started_at"], "ended_at": ended_at,
        "duration_seconds": round(duration, 1),
        "battery_before": before if valid_capacity else None,
        "battery_after": after if valid_capacity else None,
        "battery_change_percentage": change, "battery_loss_percentage": loss,
        "loss_per_hour": round(loss * 3600 / duration, 2) if loss is not None and duration >= 60 else None,
        "energy_change_wh": round(energy_change, 4) if energy_change is not None else None,
        "average_battery_drain_w": round(-energy_change * 3600 / duration, 3) if energy_change is not None and duration >= 60 else None,
    }


def public_summary(value):
    if not isinstance(value, dict):
        return None
    return {key: value.get(key) if type(value.get(key)) in (int, float) else None for key in SUMMARY_FIELDS}


def public_health(value):
    if not isinstance(value, dict):
        return None
    return {
        "checked_at": value.get("checked_at") if type(value.get("checked_at")) is int else None,
        "controller_present": value.get("controller_present") if type(value.get("controller_present")) is bool else None,
        **{key: value.get(key) if value.get(key) in HEALTH_STATES else "unavailable"
           for key in ("fan_curve", "awake_led", "sleep_led")},
        "inputplumber": value.get("inputplumber") if value.get("inputplumber") in ("active", "inactive", "failed", "unknown") else "unknown",
        "repairs_performed": False,
    }


def collect_resume_health(saved, diagnostics, call, read, awake_status, sleep_status, now=None):
    """Read firmware and connection state without attempting repairs."""
    fan_state = "automatic" if not saved.get("customFanCurvesEnabled") else "unavailable"
    if saved.get("customFanCurvesEnabled"):
        try:
            expected = (saved.get("fan") or {}).get("default") or {}
            if expected.get("fullFanSpeedEnabled") is True:
                if call(r"\_SB.GZFD.WMAE", [0, 0x11, (0x04020000).to_bytes(4, "little")], risky=False):
                    value = read()
                    fan_state = "full_speed" if value == 1 else "different" if value == 0 else "unavailable"
            elif call(r"\_SB.GZFD.WMAB", [0, 5, bytes(4)], risky=False):
                raw = read()
                if isinstance(raw, bytes) and len(raw) == 88:
                    actual = [int.from_bytes(raw[i:i + 4], "little") for i in range(4, 44, 4)]
                    fan_state = "verified" if actual == [expected.get(str(t)) for t in range(10, 101, 10)] else "different"
        except Exception:
            fan_state = "unavailable"
    night = saved.get("nightMode") or {}
    lights = {}
    for key, preference, getter in (("awake_led", "powerLedEnabled", awake_status), ("sleep_led", "sleepLedEnabled", sleep_status)):
        if night.get("pending"):
            lights[key] = "recovery_required"
            continue
        expected = False if night.get("active") else saved.get(preference)
        if type(expected) is not bool:
            lights[key] = "not_configured"
            continue
        try:
            current = getter()
            lights[key] = ("verified" if current.get("enabled") == expected else "different") if current.get("success") else "unavailable"
        except Exception:
            lights[key] = "unavailable"
    return {
        "checked_at": int(time.time() if now is None else now),
        "controller_present": bool(diagnostics.get("controller_present")),
        "fan_curve": fan_state, **lights,
        "inputplumber": (diagnostics.get("services") or {}).get("inputplumber", "unknown"),
        "repairs_performed": False,
    }


class DeviceAutomation:
    def __init__(self, get_settings, commit, fan_apply, health_reader, night,
                 battery_reader=read_power_sample, clock=boottime,
                 wall_clock=time.time, marker_reader=boot_marker):
        self.get_settings, self.commit = get_settings, commit
        self.fan_apply, self.health_reader, self.night = fan_apply, health_reader, night
        self.battery_reader, self.clock = battery_reader, clock
        self.wall_clock, self.marker_reader = wall_clock, marker_reader
        self.last_power_source = None
        self.last_transition = None
        self.error = None
        self.sleep_error = None
        self.sleep_monitor = "starting"
        self.sleep_measurement = "starting"
        self._last_sleep_signal = None
        self._process = None
        self._inhibitor = None
        self._inhibit_delay_seconds = None
        self._children = []
        self.running = False

    def config(self):
        value = self.get_settings().get("powerAutomation")
        if value is None:
            return {"enabled": False, "ac_slot": "2", "battery_slot": "1"}
        return validate_config(value)

    def status(self):
        state = self.get_settings()
        if self._inhibitor is not None and self._inhibitor.returncode is not None:
            self.sleep_measurement = "unavailable"
        try:
            config = self.config()
        except ValueError:
            config = {"enabled": False, "ac_slot": "2", "battery_slot": "1"}
            self.error = "The saved power automation configuration is invalid. Automation is not running."
        telemetry = state.get("sleepTelemetry") or {}
        active_slot = state.get("bazziteActiveFanProfile", "1")
        return {
            "success": True, "config": config,
            "source": self.battery_reader().get("source", "unknown"),
            "custom_fan_enabled": state.get("customFanCurvesEnabled") is True,
            "active_slot": active_slot if active_slot in fan_presets.SLOTS else None,
            "last_transition": deepcopy(self.last_transition), "error": self.error,
            "sleep_monitor": self.sleep_monitor, "sleep_measurement": self.sleep_measurement, "sleep_error": self.sleep_error,
            "last_sleep": public_summary(telemetry.get("last")),
            "sleep_history": [public_summary(item) for item in telemetry.get("history", [])[-10:] if isinstance(item, dict)],
            "resume_health": public_health(state.get("resumeHealth")),
            "night": self.night.status(),
        }

    def configure(self, config):
        try:
            normalized = validate_config(config)
            self.commit({"powerAutomation": normalized})
            self.last_power_source = self.battery_reader().get("source")
            self.error = None
            self.last_transition = {"success": True, "reason": "Configuration saved. The next AC/battery transition will select its profile."}
            return self.status()
        except Exception:
            return {"success": False, "error": "The power automation configuration could not be saved."}

    def _apply_source(self, source):
        try:
            state = self.get_settings()
            config = self.config()
            if not config["enabled"]:
                return {"success": True, "applied": False, "reason": "Power profile automation is disabled."}
            if state.get("customFanCurvesEnabled") is not True:
                return {"success": True, "applied": False, "reason": "Custom fan control is off; the automatic fan preference was preserved."}
            if source not in ("ac", "battery"):
                raise ValueError("Power source is unavailable")
            slots, previous_slot = fan_presets.initial_state(state)
            slot = config["ac_slot"] if source == "ac" else config["battery_slot"]
            profile = deepcopy(slots[slot])
            previous = deepcopy((state.get("fan") or {}).get("default") or slots[previous_slot])
            if not self.fan_apply(profile):
                raise ValueError("Fan profile verification failed")
            try:
                self.commit({"fan": {"default": profile}, "fanPerGameProfilesEnabled": False,
                             "bazziteActiveFanProfile": slot, "bazziteFanProfiles": slots})
            except Exception:
                restored = self.fan_apply(previous)
                return {"success": False, "applied": False, "error": "The selected profile could not be saved; the previous curve was restored." if restored else "The selected profile could not be saved and restoring the previous curve failed. Check fan support."}
            return {"success": True, "applied": True, "slot": slot, "source": source}
        except Exception:
            return {"success": False, "applied": False, "error": "The power-selected fan profile could not be verified. No profile setting was saved."}

    def apply_now(self):
        result = self._apply_source(self.battery_reader().get("source"))
        self.last_transition = result
        self.error = result.get("error")
        return {**self.status(), "success": result["success"]}

    def power_transition(self, sample=None):
        source = (sample if sample is not None else self.battery_reader()).get("source")
        if source not in ("ac", "battery"):
            return {"success": False, "applied": False, "reason": "Power source is unavailable."}
        previous = self.last_power_source
        self.last_power_source = source
        if previous is None or previous == source:
            return {"success": True, "applied": False, "reason": "Waiting for an AC/battery transition."}
        result = self._apply_source(source)
        self.last_transition = result
        self.error = result.get("error")
        return result

    async def handle_sleep_signal(self, preparing, protected=True, deadline=None, resume_gate=None):
        if type(preparing) is not bool or preparing == self._last_sleep_signal:
            return
        self._last_sleep_signal = preparing
        telemetry = deepcopy(self.get_settings().get("sleepTelemetry") or {})
        self.sleep_error = None
        try:
            if preparing:
                marker = self.marker_reader()
                if marker is None:
                    raise ValueError("Boot marker unavailable")
                telemetry["pending"] = {
                    "boot_marker": marker, "boottime": self.clock(),
                    "started_at": int(self.wall_clock()), "battery": self.battery_reader(),
                    "reliable": protected is True,
                }
            else:
                try:
                    summary = sleep_summary(telemetry.get("pending"), self.battery_reader(),
                                            self.clock(), int(self.wall_clock()), self.marker_reader())
                    telemetry["last"] = summary
                    telemetry["history"] = [*telemetry.get("history", [])[-9:], summary]
                except (ValueError, TypeError, KeyError):
                    self.sleep_error = "A resume boundary was observed without a matching sleep entry. No battery-loss estimate was created."
                telemetry["pending"] = None
            self.commit({"sleepTelemetry": telemetry})
            if preparing and deadline is not None and self.clock() >= deadline:
                telemetry["pending"]["reliable"] = False
                self.commit({"sleepTelemetry": telemetry})
                self.sleep_error = "The sleep sample exceeded logind's delay budget. No battery-loss estimate will be created."
            elif preparing and not protected:
                self.sleep_error = "A protected sleep-entry sample was unavailable. No battery-loss estimate will be created."
        except Exception:
            self.sleep_error = "The sleep boundary could not be recorded. No battery-loss estimate is available for this cycle."
        if not preparing:
            if resume_gate is not None:
                await resume_gate()
            try:
                health = self.health_reader()
                if inspect.isawaitable(health):
                    health = await health
                self.commit({"resumeHealth": public_health(health)})
            except Exception:
                self.sleep_error = "Resume diagnostics could not be read or saved. No automatic repair was attempted."

    async def _power_loop(self):
        while self.running:
            try:
                self.power_transition()
            except Exception:
                self.error = "Power state could not be read; automation did not change a profile."
            await asyncio.sleep(2)

    async def _sleep_loop(self):
        while self.running:
            try:
                self._process = await asyncio.create_subprocess_exec(
                    "/usr/bin/python3", str(Path(__file__).with_name("process_supervisor.py")), str(os.getpid()),
                    "dbus-monitor", "--system", "--monitor", SLEEP_MATCH,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
                    env={"PATH": "/usr/sbin:/usr/bin"},
                )
                await self._acquire_inhibitor()
                self.sleep_monitor = "active"
                parser = SleepSignalParser()
                while self.running:
                    line = await self._process.stdout.readline()
                    if not line:
                        break
                    signal = parser.feed(line.decode("utf-8", errors="replace").rstrip("\n"))
                    if signal is not None:
                        if signal:
                            protected = self._inhibitor is not None and self._inhibitor.returncode is None and self.sleep_measurement == "protected"
                            age = max(0, self.wall_clock() - parser.timestamp) if parser.timestamp is not None else None
                            remaining = self._inhibit_delay_seconds - age if protected and age is not None else None
                            protected = protected and remaining is not None and remaining > 0
                            deadline = self.clock() + remaining if protected else None
                            try:
                                await self.handle_sleep_signal(True, protected=protected, deadline=deadline)
                            finally:
                                # Release even if sampling or settings persistence fails.
                                await self._release_inhibitor()
                        else:
                            await self.handle_sleep_signal(False, resume_gate=self._acquire_inhibitor)
                await self._process.wait()
            except (OSError, ValueError):
                pass
            finally:
                await self._release_inhibitor()
                if self._process is not None and self._process.returncode is None:
                    self._process.terminate()
                    await self._process.wait()
                self._process = None
            if self.running:
                self.sleep_monitor = "unavailable"
                await asyncio.sleep(15)

    async def _acquire_inhibitor(self):
        if self._inhibitor is not None and self._inhibitor.returncode is None:
            return True
        await self._release_inhibitor()
        try:
            self._inhibitor = await asyncio.create_subprocess_exec(
                "systemd-inhibit", "--no-ask-password", "--what=sleep", "--mode=delay",
                "--who=Legion Decky", "--why=Record battery state at sleep entry",
                "/usr/bin/python3", "-u", "-c", INHIBITOR_HELPER,
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL, start_new_session=True,
                env={"PATH": "/usr/sbin:/usr/bin"},
            )
            ready = await asyncio.wait_for(self._inhibitor.stdout.readline(), timeout=3)
            match = re.fullmatch(rb"READY ([0-9]+)\n", ready)
            if not match or self._inhibitor.returncode is not None or int(match[1]) <= 0:
                raise ValueError("The sleep delay lock was not confirmed")
            self._inhibit_delay_seconds = int(match[1]) / 1_000_000
            self.sleep_measurement = "protected"
            return True
        except asyncio.CancelledError:
            await self._release_inhibitor()
            raise
        except (OSError, ValueError, asyncio.TimeoutError):
            await self._release_inhibitor()
            self.sleep_measurement = "unavailable"
            return False

    async def _release_inhibitor(self):
        process, self._inhibitor = self._inhibitor, None
        self._inhibit_delay_seconds = None
        if process is not None:
            if process.stdin is not None:
                process.stdin.close()
            try:
                await asyncio.wait_for(process.wait(), timeout=1.5)
            except asyncio.TimeoutError:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    await asyncio.wait_for(process.wait(), timeout=0.5)
                except asyncio.TimeoutError:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    await process.wait()
        if self.sleep_measurement == "protected":
            self.sleep_measurement = "released"

    async def run(self):
        self.running = True
        self._children = [asyncio.create_task(self._power_loop()), asyncio.create_task(self._sleep_loop())]
        try:
            await asyncio.gather(*self._children)
        finally:
            self.running = False
            for task in self._children:
                task.cancel()
            await asyncio.gather(*self._children, return_exceptions=True)
            if self._process is not None and self._process.returncode is None:
                self._process.terminate()
                await self._process.wait()
            await self._release_inhibitor()
            self.sleep_monitor = "stopped"
            self.sleep_measurement = "stopped"
