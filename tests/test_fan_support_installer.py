import stat
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from py_modules import fan_support_installer as installer


class FanSupportInstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.base = root / "var-lib"
        self.service = root / "etc" / "legion-fan-support.service"
        self.proc = root / "proc-acpi-call"
        self.calls = []

    def tearDown(self):
        self.temp.cleanup()

    def install(self, runner, **kwargs):
        installer.install(
            base_dir=self.base, service_path=self.service, proc_path=self.proc,
            runner=runner, kernel_release="7.0.0-test", **kwargs)

    def test_bundled_sources_are_complete(self):
        for name in installer.SOURCE_FILES:
            self.assertTrue((installer.bundled_source_dir() / name).is_file(), name)

    def test_write_files_is_idempotent_and_executable(self):
        self.assertTrue(installer.write_files(None, self.base, self.service))
        self.assertFalse(installer.write_files(None, self.base, self.service))
        script = self.base / "load-module.sh"
        self.assertTrue(script.stat().st_mode & stat.S_IXUSR)
        for name in installer.SOURCE_FILES:
            self.assertEqual(
                (self.base / "src" / name).read_bytes(),
                (installer.bundled_source_dir() / name).read_bytes())

    def test_successful_install_runs_service_and_requires_proc_file(self):
        def runner(command, **_kwargs):
            self.calls.append(command)
            if command[:2] == ["systemctl", "restart"]:
                self.proc.touch()
            return SimpleNamespace(returncode=0, stdout="")
        self.install(runner)
        self.assertEqual(
            [c[:2] for c in self.calls],
            [["systemctl", "daemon-reload"], ["systemctl", "enable"], ["systemctl", "restart"]])

    def test_missing_headers_gives_actionable_error(self):
        def runner(command, **_kwargs):
            if command[0] == "journalctl":
                return SimpleNamespace(returncode=0, stdout="Kernel headers missing for 7.0.0-test")
            return SimpleNamespace(returncode=1 if command[1] == "restart" else 0, stdout="")
        with self.assertRaises(installer.FanSupportError) as raised:
            self.install(runner)
        self.assertIn("headers", str(raised.exception))

    def test_service_success_without_proc_file_is_a_failure(self):
        runner = lambda *_a, **_k: SimpleNamespace(returncode=0, stdout="")
        with self.assertRaises(installer.FanSupportError):
            self.install(runner)

    def test_missing_bundled_sources_are_reported(self):
        empty = Path(self.temp.name) / "empty"
        empty.mkdir()
        with self.assertRaises(installer.FanSupportError):
            installer.write_files(empty, self.base, self.service)


if __name__ == "__main__":
    unittest.main()
