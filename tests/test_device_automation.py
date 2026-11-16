import asyncio
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

from py_modules import device_automation as automation
from py_modules import fan_presets
from py_modules import lighting_transactions as lighting


class Store:
    def __init__(self, value=None):
        self.value = deepcopy(value or {})
        self.writes = []

    def get(self):
        return deepcopy(self.value)

    def commit(self, values):
        self.writes.append(deepcopy(values))
        self.value.update(deepcopy(values))


class LightingHardware:
    def __init__(self):
        self.awake = True
        self.sleep = True
        self.rgb = {"indexes": ["green", "blue", "red"], "maximum": 255,
                    "brightness": 17, "intensity": [128, 254, 1], "limits": [255, 255, 255]}
        self.operations = []

    def awake_status(self):
        return {"success": True, "enabled": self.awake}

    def sleep_status(self):
        return {"success": True, "enabled": self.sleep}

    def set_awake(self, value):
        self.operations.append(("awake", value))
        self.awake = value
        return self.awake_status()

    def set_sleep(self, value):
        self.operations.append(("sleep", value))
        self.sleep = value
        return self.sleep_status()

    def capture(self):
        return deepcopy(self.rgb)

    def restore(self, value):
        self.operations.append(("rgb", deepcopy(value)))
        self.rgb = deepcopy(value)
        return {"success": True}

    def mode(self, store):
        return lighting.NightMode(store.get, store.commit, self.awake_status, self.set_awake,
                                  self.sleep_status, self.set_sleep, self.capture, self.restore)


class NightModeTests(unittest.TestCase):
    def setUp(self):
        self.store = Store()
        self.hardware = LightingHardware()
        self.mode = self.hardware.mode(self.store)

    def test_roundtrip_restores_exact_native_color_and_prior_led_states(self):
        self.hardware.awake = False
        original = {"awake": False, "sleep": True, "rgb": self.hardware.capture()}
        self.assertTrue(self.mode.set_enabled(True)["verified"])
        self.assertFalse(self.hardware.awake)
        self.assertFalse(self.hardware.sleep)
        self.assertEqual(self.hardware.rgb["brightness"], 0)
        self.assertEqual(self.store.value["nightMode"]["snapshot"], original)
        self.assertTrue(self.mode.set_enabled(False)["success"])
        self.assertFalse(self.hardware.awake)
        self.assertTrue(self.hardware.sleep)
        self.assertEqual(self.hardware.rgb, original["rgb"])
        self.assertIsNone(self.store.value["nightMode"]["snapshot"])

    def test_snapshot_is_persisted_before_first_hardware_change(self):
        original = self.hardware.set_awake
        def checked(value):
            self.assertTrue(self.store.value["nightMode"]["pending"])
            self.assertIsNotNone(self.store.value["nightMode"]["snapshot"])
            return original(value)
        self.mode.set_awake = checked
        self.assertTrue(self.mode.set_enabled(True)["success"])

    def test_failed_snapshot_commit_does_not_write_hardware(self):
        self.mode.commit = Mock(side_effect=OSError("private-storage-path"))
        result = self.mode.set_enabled(True)
        self.assertFalse(result["success"])
        self.assertEqual(self.hardware.operations, [])
        self.assertNotIn("private-storage", json.dumps(result))

    def test_partial_off_failure_rolls_back_all_lights(self):
        original = self.hardware.capture()
        self.mode.set_sleep = Mock(side_effect=[{"success": False}, {"success": True}])
        result = self.mode.set_enabled(True)
        self.assertFalse(result["success"])
        self.assertTrue(self.hardware.awake)
        self.assertTrue(self.hardware.sleep)
        self.assertEqual(self.hardware.rgb, original)
        self.assertFalse(self.store.value["nightMode"]["pending"])

    def test_incomplete_rollback_retains_recovery_snapshot(self):
        self.mode.set_sleep = Mock(return_value={"success": False})
        result = self.mode.set_enabled(True)
        self.assertFalse(result["success"])
        self.assertTrue(result["recoverable"])
        self.assertTrue(self.store.value["nightMode"]["pending"])

    def test_restart_reuses_original_snapshot_instead_of_capturing_dark_state(self):
        original = self.hardware.capture()
        self.assertTrue(self.mode.set_enabled(True)["success"])
        restarted = self.hardware.mode(self.store)
        self.assertTrue(restarted.startup()["success"])
        self.assertEqual(self.store.value["nightMode"]["snapshot"]["rgb"], original)
        self.assertTrue(restarted.set_enabled(False)["success"])
        self.assertEqual(self.hardware.rgb, original)

    def test_pending_restart_recovers_previous_state(self):
        original = self.mode._capture()
        self.store.value["nightMode"] = {"active": False, "pending": True, "snapshot": original}
        self.hardware.awake = False
        self.hardware.rgb["brightness"] = 0
        self.assertTrue(self.hardware.mode(self.store).startup()["success"])
        self.assertTrue(self.hardware.awake)
        self.assertEqual(self.hardware.capture(), original["rgb"])
        self.assertFalse(self.store.value["nightMode"]["pending"])

    def test_unavailable_interface_makes_no_changes(self):
        self.mode.sleep_status = Mock(return_value={"success": False})
        self.assertFalse(self.mode.set_enabled(True)["success"])
        self.assertEqual(self.hardware.operations, [])
        self.assertEqual(self.store.writes, [])

    def test_final_commit_failure_rolls_back_verified_hardware(self):
        original_rgb = self.hardware.capture()
        commit = self.store.commit
        calls = 0
        def fail_once(value):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("private-storage-path")
            commit(value)
        self.mode.commit = fail_once
        result = self.mode.set_enabled(True)
        self.assertFalse(result["success"])
        self.assertTrue(self.hardware.awake)
        self.assertTrue(self.hardware.sleep)
        self.assertEqual(self.hardware.rgb, original_rgb)
        self.assertFalse(self.store.value["nightMode"]["active"])
        self.assertFalse(self.store.value["nightMode"]["pending"])

    def test_corrupt_active_snapshot_is_not_replaced_or_applied(self):
        self.store.value["nightMode"] = {"active": True, "pending": False, "snapshot": {"awake": True}}
        result = self.mode.startup()
        self.assertFalse(result["success"])
        self.assertFalse(result["recoverable"])
        self.assertEqual(self.hardware.operations, [])

    def test_external_light_change_is_reported_without_forced_reapply(self):
        self.mode.set_enabled(True)
        operations = len(self.hardware.operations)
        self.hardware.awake = True
        status = self.mode.status()
        self.assertTrue(status["active"])
        self.assertFalse(status["verified"])
        self.assertEqual(len(self.hardware.operations), operations)


class NativeRgbSnapshotTests(unittest.TestCase):
    def test_exact_raw_values_restore_without_percentage_rounding(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            device = root / "go:rgb:joystick_rings"
            device.mkdir()
            for name, value in {"multi_index": "green blue red", "max_brightness": "255", "brightness": "17",
                                "multi_max_intensity": "255 255 255", "multi_intensity": "128 254 1", "trigger": "[none]"}.items():
                (device / name).write_text(value)
            snapshot = lighting.capture_rgb(root)
            off = deepcopy(snapshot)
            off["brightness"] = 0
            self.assertTrue(lighting.restore_rgb(off, root)["success"])
            self.assertTrue(lighting.restore_rgb(snapshot, root)["success"])
            self.assertEqual(lighting.capture_rgb(root), snapshot)

    def test_capability_change_prevents_any_restore_write(self):
        snapshot = LightingHardware().capture()
        changed = deepcopy(snapshot)
        changed["maximum"] = 100
        changed["brightness"] = 0
        writer = Mock()
        with patch.object(lighting, "capture_rgb", return_value=changed):
            result = lighting.restore_rgb(snapshot, writer=writer)
        self.assertFalse(result["success"])
        writer.assert_not_called()


class AutomationTests(unittest.TestCase):
    def setUp(self):
        slots, _ = fan_presets.initial_state({})
        self.store = Store({"fan": {"default": slots["1"]}, "customFanCurvesEnabled": True,
                            "bazziteFanProfiles": slots, "bazziteActiveFanProfile": "1",
                            "powerAutomation": {"enabled": True, "ac_slot": "2", "battery_slot": "1"}})
        self.sample = {"source": "ac", "capacity": 80, "energy_now": 100_000_000}
        self.apply = Mock(return_value=True)
        self.night = Mock()
        self.night.status.return_value = {"active": False, "success": True}
        self.runtime = automation.DeviceAutomation(self.store.get, self.store.commit, self.apply, Mock(), self.night,
                                                   battery_reader=lambda: deepcopy(self.sample))

    def test_startup_and_unchanged_power_do_not_override_manual_profile(self):
        self.runtime.power_transition()
        self.runtime.power_transition()
        self.store.value["bazziteActiveFanProfile"] = "3"
        self.runtime.power_transition()
        self.apply.assert_not_called()
        self.assertEqual(self.store.value["bazziteActiveFanProfile"], "3")

    def test_each_real_power_transition_selects_exactly_one_profile(self):
        self.runtime.power_transition()
        self.sample["source"] = "battery"
        self.assertTrue(self.runtime.power_transition()["applied"])
        self.runtime.power_transition()
        self.assertEqual(self.apply.call_count, 1)
        self.sample["source"] = "ac"
        self.assertTrue(self.runtime.power_transition()["applied"])
        self.assertEqual(self.apply.call_count, 2)
        self.assertEqual(self.store.value["bazziteActiveFanProfile"], "2")

    def test_custom_control_disabled_is_never_enabled_by_automation(self):
        self.store.value["customFanCurvesEnabled"] = False
        self.runtime.power_transition()
        self.sample["source"] = "battery"
        result = self.runtime.power_transition()
        self.assertFalse(result["applied"])
        self.apply.assert_not_called()
        self.assertFalse(self.store.value["customFanCurvesEnabled"])

    def test_automation_is_opt_in(self):
        self.store.value.pop("powerAutomation")
        self.runtime.power_transition()
        self.sample["source"] = "battery"
        self.runtime.power_transition()
        self.apply.assert_not_called()
        self.assertFalse(self.runtime.status()["config"]["enabled"])

    def test_saving_configuration_only_primes_current_source(self):
        result = self.runtime.configure({"enabled": True, "ac_slot": "3", "battery_slot": "2"})
        self.assertTrue(result["success"])
        self.runtime.power_transition()
        self.apply.assert_not_called()

    def test_hardware_failure_does_not_save_active_profile(self):
        self.apply.return_value = False
        self.runtime.power_transition()
        self.sample["source"] = "battery"
        self.assertFalse(self.runtime.power_transition()["success"])
        self.assertEqual(self.store.writes, [])

    def test_save_failure_rolls_back_previous_fan_profile(self):
        previous = deepcopy(self.store.value["fan"]["default"])
        self.runtime.commit = Mock(side_effect=OSError("private-storage-path"))
        result = self.runtime.apply_now()
        self.assertFalse(result["success"])
        self.assertEqual(self.apply.call_count, 2)
        self.assertEqual(self.apply.call_args.args[0], previous)
        self.assertNotIn("private-storage", json.dumps(result))

    def test_invalid_config_is_not_saved(self):
        self.assertFalse(self.runtime.configure({"enabled": "yes", "ac_slot": "4", "battery_slot": "1"})["success"])
        self.assertEqual(self.store.writes, [])


class SleepTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.store = Store()
        self.clock = 100.0
        self.wall = 1000
        self.boot = "same-boot"
        self.sample = {"source": "battery", "capacity": 80, "energy_now": 100_000_000}
        self.health = Mock(return_value={"checked_at": 4600, "controller_present": True, "fan_curve": "automatic",
                                        "awake_led": "verified", "sleep_led": "not_configured", "inputplumber": "active"})
        night = Mock()
        night.status.return_value = {"active": False}
        self.runtime = automation.DeviceAutomation(self.store.get, self.store.commit, Mock(), self.health, night,
            battery_reader=lambda: deepcopy(self.sample), clock=lambda: self.clock,
            wall_clock=lambda: self.wall, marker_reader=lambda: self.boot)

    async def test_real_prepare_and_resume_boundaries_compute_battery_loss(self):
        await self.runtime.handle_sleep_signal(True)
        self.clock += 3600
        self.wall += 3600
        self.sample.update(capacity=76, energy_now=98_000_000)
        await self.runtime.handle_sleep_signal(False)
        result = self.runtime.status()["last_sleep"]
        self.assertEqual(result["duration_seconds"], 3600)
        self.assertEqual(result["battery_loss_percentage"], 4)
        self.assertEqual(result["loss_per_hour"], 4)
        self.assertEqual(result["average_battery_drain_w"], 2)
        self.health.assert_called_once()
        self.assertFalse(self.store.value["resumeHealth"]["repairs_performed"])
        self.assertNotIn("same-boot", json.dumps(self.runtime.status()))

    async def test_duplicate_signals_do_not_replace_or_repeat_a_cycle(self):
        await self.runtime.handle_sleep_signal(True)
        self.clock += 50
        await self.runtime.handle_sleep_signal(True)
        self.assertEqual(self.store.value["sleepTelemetry"]["pending"]["boottime"], 100)
        await self.runtime.handle_sleep_signal(False)
        count = len(self.store.writes)
        await self.runtime.handle_sleep_signal(False)
        self.assertEqual(len(self.store.writes), count)

    async def test_reboot_never_becomes_a_sleep_loss_estimate(self):
        await self.runtime.handle_sleep_signal(True)
        self.boot = "other-boot"
        self.clock += 3600
        await self.runtime.handle_sleep_signal(False)
        self.assertIsNone(self.runtime.status()["last_sleep"])
        self.assertIn("matching sleep entry", self.runtime.sleep_error)

    async def test_resume_without_entry_does_not_invent_sleep(self):
        await self.runtime.handle_sleep_signal(False)
        self.assertIsNone(self.runtime.status()["last_sleep"])
        self.health.assert_called_once()

    async def test_charging_during_sleep_is_not_reported_as_battery_loss(self):
        await self.runtime.handle_sleep_signal(True)
        self.clock += 3600
        self.wall += 3600
        self.sample.update(capacity=90, energy_now=105_000_000)
        await self.runtime.handle_sleep_signal(False)
        last = self.runtime.status()["last_sleep"]
        self.assertEqual(last["battery_change_percentage"], 10)
        self.assertEqual(last["battery_loss_percentage"], 0)

    async def test_missing_battery_data_retains_duration_without_claiming_loss(self):
        self.sample.update(capacity=None, energy_now=None)
        await self.runtime.handle_sleep_signal(True)
        self.clock += 3600
        await self.runtime.handle_sleep_signal(False)
        last = self.runtime.status()["last_sleep"]
        self.assertEqual(last["duration_seconds"], 3600)
        self.assertIsNone(last["battery_loss_percentage"])

    async def test_unprotected_sleep_entry_never_claims_battery_loss(self):
        await self.runtime.handle_sleep_signal(True, protected=False)
        self.clock += 3600
        self.sample["capacity"] = 70
        await self.runtime.handle_sleep_signal(False)
        self.assertIsNone(self.runtime.status()["last_sleep"])

    async def test_exceeded_logind_delay_budget_invalidates_the_sample(self):
        original_commit = self.runtime.commit
        def delayed_commit(value):
            original_commit(value)
            self.clock += 2
        self.runtime.commit = delayed_commit
        await self.runtime.handle_sleep_signal(True, protected=True, deadline=101)
        self.assertFalse(self.store.value["sleepTelemetry"]["pending"]["reliable"])
        self.clock += 3600
        await self.runtime.handle_sleep_signal(False)
        self.assertIsNone(self.runtime.status()["last_sleep"])


class MonitorLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_monitor_process_is_terminated_on_plugin_unload(self):
        process = Mock()
        process.returncode = None
        process.stdout.readline = AsyncMock(side_effect=lambda: asyncio.Future())
        async def waiting_line():
            await asyncio.Future()
        process.stdout.readline = waiting_line
        process.terminate.side_effect = lambda: setattr(process, "returncode", 0)
        process.wait = AsyncMock(return_value=0)
        night = Mock()
        runtime = automation.DeviceAutomation(lambda: {}, Mock(), Mock(), Mock(), night,
            battery_reader=lambda: {"source": "ac", "capacity": 50})
        inhibitor = Mock()
        inhibitor.returncode = None
        inhibitor.stdout.readline = AsyncMock(return_value=b"READY 5000000\n")
        inhibitor.wait = AsyncMock(return_value=0)
        inhibitor.stdin.close.side_effect = lambda: setattr(inhibitor, "returncode", 0)
        async def create(*args, **_kwargs):
            return process if "dbus-monitor" in args else inhibitor
        with patch.object(asyncio, "create_subprocess_exec", create):
            task = asyncio.create_task(runtime.run())
            for _ in range(12):
                await asyncio.sleep(0)
            self.assertEqual(runtime.sleep_monitor, "active")
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        process.terminate.assert_called_once()
        inhibitor.stdin.close.assert_called_once()
        self.assertEqual(runtime.sleep_monitor, "stopped")

    async def test_inhibitor_failure_is_unavailable_without_a_password_prompt(self):
        runtime = automation.DeviceAutomation(lambda: {}, Mock(), Mock(), Mock(), Mock())
        factory = AsyncMock(side_effect=FileNotFoundError())
        with patch.object(asyncio, "create_subprocess_exec", factory):
            self.assertFalse(await runtime._acquire_inhibitor())
        self.assertEqual(runtime.sleep_measurement, "unavailable")
        args = factory.call_args.args
        self.assertIn("--mode=delay", args)
        self.assertIn("--no-ask-password", args)
        self.assertNotIn("--mode=block", args)

    async def test_inhibitor_release_runs_when_sampling_fails(self):
        runtime = automation.DeviceAutomation(lambda: {}, Mock(), Mock(), Mock(), Mock())
        process = Mock()
        process.returncode = None
        process.wait = AsyncMock(return_value=0)
        process.stdin.close.side_effect = lambda: setattr(process, "returncode", 0)
        runtime._inhibitor = process
        runtime.sleep_measurement = "protected"
        try:
            raise OSError("sample failed")
        except OSError:
            await runtime._release_inhibitor()
        process.stdin.close.assert_called_once()
        self.assertIsNone(runtime._inhibitor)


class SignalAndPowerTests(unittest.TestCase):
    def test_signal_parser_ignores_unrelated_booleans(self):
        parser = automation.SleepSignalParser()
        self.assertIsNone(parser.feed("   boolean true"))
        self.assertIsNone(parser.feed("signal time=1 path=/wrong; interface=org.freedesktop.login1.Manager; member=PrepareForSleep"))
        self.assertIsNone(parser.feed("   boolean true"))
        header = "signal time=1 sender=:1.2 -> destination=(null destination) serial=1 path=/org/freedesktop/login1; interface=org.freedesktop.login1.Manager; member=PrepareForSleep"
        self.assertIsNone(parser.feed(header))
        self.assertTrue(parser.feed("   boolean true"))
        parser.feed(header)
        self.assertFalse(parser.feed("   boolean false"))

    def test_power_source_uses_online_state_instead_of_capacity_guess(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for supply, files in {"BATT": {"type": "Battery", "status": "Not charging", "capacity": "80"},
                                  "ACAD": {"type": "Mains", "online": "1"}}.items():
                (root / supply).mkdir()
                for name, value in files.items():
                    (root / supply / name).write_text(value)
            self.assertEqual(automation.read_power_sample(root)["source"], "ac")
            (root / "ACAD/online").write_text("0")
            self.assertEqual(automation.read_power_sample(root)["source"], "battery")

    def test_full_speed_resume_check_does_not_compare_an_unused_curve(self):
        state = {"customFanCurvesEnabled": True, "fan": {"default": {"fullFanSpeedEnabled": True}}}
        call, read = Mock(return_value=True), Mock(return_value=1)
        result = automation.collect_resume_health(state, {"controller_present": True}, call, read, Mock(), Mock(), now=1)
        self.assertEqual(result["fan_curve"], "full_speed")
        self.assertEqual(call.call_args.args[0], r"\_SB.GZFD.WMAE")


if __name__ == "__main__":
    unittest.main()
