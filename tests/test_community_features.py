import ast
import json
from pathlib import Path
import subprocess
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

from py_modules import community_features as features


class SleepLedTests(unittest.TestCase):
    def test_sleep_indicator_uses_its_own_selector_and_second_byte(self):
        call = Mock(return_value=True)
        result = features.sleep_led_status(call, Mock(return_value=b"\x01\x03"))
        self.assertTrue(result["enabled"])
        call.assert_called_once_with(r"\_SB.GZFD.WMAF", [0, 1, 0x24], risky=False)

    def test_turn_off_is_verified_and_does_not_change_awake_selector(self):
        call = Mock(return_value=True)
        read = Mock(side_effect=[b"\x01\x03", b"\x01\x01"])
        result = features.set_sleep_led(False, call, read)
        self.assertTrue(result["success"])
        self.assertFalse(result["enabled"])
        self.assertEqual(call.call_args_list[1].args[1], [0, 2, b"\x24\x00\x01"])

    def test_unknown_state_is_not_misreported_as_disabled(self):
        call = Mock(return_value=True)
        result = features.set_sleep_led(False, call, Mock(return_value=b"\x00\x00"))
        self.assertFalse(result["supported"])
        self.assertIsNone(result["enabled"])
        self.assertEqual(call.call_count, 1)

    def test_mismatched_readback_reports_failure(self):
        result = features.set_sleep_led(False, Mock(return_value=True), Mock(return_value=b"\x01\x03"))
        self.assertFalse(result["success"])
        self.assertTrue(result["enabled"])

    def test_invalid_value_never_reaches_firmware(self):
        call = Mock()
        self.assertFalse(features.set_sleep_led(1, call, Mock())["success"])
        call.assert_not_called()


class SleepEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def run_endpoint(self, result):
        tree = ast.parse((Path(__file__).parents[1] / "main.py").read_text())
        plugin = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Plugin")
        endpoint = next(node for node in plugin.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "set_sleep_led")
        settings = Mock()
        backend = Mock()
        backend.set_sleep_led.return_value = result
        scope = {"community_features": backend, "settings": settings, "legion_space": Mock()}
        exec(compile(ast.Module(body=[endpoint], type_ignores=[]), "<sleep-endpoint>", "exec"), scope)
        instance = Mock()
        instance._night_mode_blocks_lighting.return_value = False
        response = await scope["set_sleep_led"](instance, False)
        return response, settings

    async def test_unverified_preference_is_not_saved(self):
        response, settings = await self.run_endpoint({"success": False, "enabled": True})
        self.assertFalse(response["success"])
        settings.set_setting.assert_not_called()

    async def test_verified_preference_is_saved(self):
        response, settings = await self.run_endpoint({"success": True, "enabled": False})
        self.assertTrue(response["success"])
        settings.set_setting.assert_called_once_with("sleepLedEnabled", False)


class RgbTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.device = self.root / features.RGB_DEVICE_NAME
        self.device.mkdir()
        for name, value in {
            "multi_index": "green blue red", "max_brightness": "100",
            "brightness": "21", "multi_intensity": "90 100 1",
            "multi_max_intensity": "100 100 100", "trigger": "[none] disk-activity",
        }.items():
            (self.device / name).write_text(value)

    def tearDown(self):
        self.temp.cleanup()

    def test_status_respects_kernel_channel_order(self):
        status = features.rgb_status(self.root)
        self.assertEqual(status["color"], {"red": 1, "green": 90, "blue": 100})
        self.assertEqual(status["brightness"], 21)
        self.assertNotIn(str(self.root), json.dumps(status))

    def test_explicit_write_and_readback_use_native_order(self):
        result = features.set_rgb(65, {"red": 100, "green": 25, "blue": 0}, self.root)
        self.assertTrue(result["success"])
        self.assertEqual((self.device / "multi_intensity").read_text().strip(), "25 0 100")
        self.assertEqual((self.device / "brightness").read_text().strip(), "65")

    def test_rgb_uses_each_channels_advertised_scale(self):
        (self.device / "multi_max_intensity").write_text("200 100 50")
        result = features.set_rgb(50, {"red": 100, "green": 50, "blue": 25}, self.root)
        self.assertTrue(result["success"])
        self.assertEqual((self.device / "multi_intensity").read_text().strip(), "100 25 50")

    def test_active_trigger_is_not_disabled_or_overridden(self):
        (self.device / "trigger").write_text("none [BATT-charging]")
        writer = Mock()
        result = features.set_rgb(0, {"red": 0, "green": 0, "blue": 0}, self.root, writer)
        self.assertFalse(result["success"])
        self.assertFalse(result["writable"])
        writer.assert_not_called()
        self.assertEqual((self.device / "trigger").read_text(), "none [BATT-charging]")

    def test_invalid_inputs_never_write(self):
        writer = Mock()
        for brightness, color in [(True, {"red": 0, "green": 0, "blue": 0}),
                                  (101, {"red": 0, "green": 0, "blue": 0}),
                                  (50, {"red": 100, "green": 0}),
                                  (50, {"red": 100, "green": -1, "blue": 0})]:
            with self.subTest(brightness=brightness, color=color):
                self.assertFalse(features.set_rgb(brightness, color, self.root, writer)["success"])
        writer.assert_not_called()

    def test_partial_write_failure_restores_previous_state(self):
        failed = False
        def writer(path, value):
            nonlocal failed
            if path.name == "brightness" and not failed:
                failed = True
                raise PermissionError("private-home-path/forbidden")
            path.write_text(value)
        result = features.set_rgb(70, {"red": 100, "green": 0, "blue": 0}, self.root, writer)
        self.assertFalse(result["success"])
        self.assertIn("restored", result["error"])
        self.assertEqual((self.device / "brightness").read_text(), "21")
        self.assertEqual((self.device / "multi_intensity").read_text(), "90 100 1")
        self.assertNotIn("private-home", json.dumps(result))

    def test_mismatched_readback_is_not_reported_as_success(self):
        def writer(path, value):
            if path.name == "multi_intensity" and value == "0 0 100":
                path.write_text("0 0 50")
            else:
                path.write_text(value)
        result = features.set_rgb(30, {"red": 100, "green": 0, "blue": 0}, self.root, writer)
        self.assertFalse(result["success"])
        self.assertEqual((self.device / "multi_intensity").read_text(), "90 100 1")


class DiagnosticsTests(unittest.TestCase):
    def test_allowlist_excludes_machine_identities_and_raw_command_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            def add(name, value):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(value)
            add("sys/class/dmi/id/product_name", "83E1")
            add("sys/class/dmi/id/bios_version", "N3CN39WW")
            add("sys/class/dmi/id/product_serial", "private-device-serial")
            add("sys/class/hidraw/hidraw1/device/uevent", "HID_ID=0003:000017EF:000061EB\nHID_UNIQ=private-controller-serial")
            add("sys/bus/iio/devices/iio:device0/name", "gyro_3d")
            add("proc/modules", "acpi_call 4096 0 - Live 0\n")
            add("proc/acpi/call", "")
            add("etc/os-release", 'ID=bazzite\nVERSION_ID=45\nHOME_URL=private-user-home\n')
            runner = Mock(return_value=types.SimpleNamespace(stdout="active\nactive\nactive\ninactive\n"))
            with patch.object(features.platform, "release", return_value="7.3.4-test"):
                result = features.diagnostics(root / "sys", root / "proc", root / "etc", runner)
            self.assertTrue(result["controller_present"])
            self.assertTrue(result["fan_interface"])
            self.assertTrue(result["fan_module_loaded"])
            self.assertEqual(result["gyro_devices"], 1)
            self.assertEqual(result["services"]["inputplumber"], "active")
            self.assertNotIn("private", json.dumps(result))
            self.assertNotIn(str(root), json.dumps(result))

    def test_command_failure_is_unknown_without_leaking_exception(self):
        with tempfile.TemporaryDirectory() as temporary:
            runner = Mock(side_effect=subprocess.TimeoutExpired("private-command", 5))
            result = features.diagnostics(Path(temporary), Path(temporary), Path(temporary), runner)
            self.assertTrue(all(value == "unknown" for value in result["services"].values()))
            self.assertNotIn("private-command", json.dumps(result))

    def test_package_versions_are_allowlisted(self):
        with tempfile.TemporaryDirectory() as temporary:
            runner = Mock(side_effect=[
                types.SimpleNamespace(stdout="active\nactive\nactive\ninactive\n"),
                types.SimpleNamespace(stdout="inputplumber 0.84.0-4.fc45\npowerstation 0.10.2-1.fc45\nother-package private-data\nprivate-home-path/secret\n"),
            ])
            result = features.diagnostics(Path(temporary), Path(temporary), Path(temporary), runner)
            self.assertEqual(result["versions"], {"inputplumber": "0.84.0-4.fc45", "powerstation": "0.10.2-1.fc45"})
            self.assertNotIn("private", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
