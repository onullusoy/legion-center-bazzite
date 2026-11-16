"""Explicit development checks for verified lighting and pointer routing.

Run as the desktop user through pkexec. The plugin is stopped while ACPI is
queried to avoid competing users of the shared acpi_call response buffer.
"""
from copy import deepcopy
import hashlib
import json
import logging
import os
from pathlib import Path
import pwd
import stat
import subprocess
import sys
import tempfile
import time
import types


class JsonSettings:
    def __init__(self, path):
        self.path = path

    def read(self):
        return json.loads(self.path.read_text())

    def merge(self, update):
        value = self.read()
        value.update(deepcopy(update))
        info = self.path.stat()
        with tempfile.NamedTemporaryFile(mode='w', dir=self.path.parent, prefix='.device-check-', delete=False) as stream:
            json.dump(value, stream, indent=2)
            stream.write('\n')
            temporary = Path(stream.name)
        try:
            os.chmod(temporary, stat.S_IMODE(info.st_mode))
            os.chown(temporary, info.st_uid, info.st_gid)
            temporary.replace(self.path)
        finally:
            temporary.unlink(missing_ok=True)


def main():
    if os.geteuid() != 0:
        raise SystemExit('Run this explicit device check through pkexec.')
    uid = os.environ.get('PKEXEC_UID') or os.environ.get('SUDO_UID')
    if uid is None or int(uid) == 0:
        raise SystemExit('The desktop user could not be determined.')
    home = Path(pwd.getpwuid(int(uid)).pw_dir)
    plugin = home / 'homebrew/plugins/LegionCenter'
    state = JsonSettings(home / 'homebrew/settings/LegionCenter/settings.json')
    source = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(plugin / 'py_modules'))
    sys.modules['decky'] = types.SimpleNamespace(logger=logging.getLogger('legion-device-check'))
    import community_features, controller_support, device_automation, device_features
    import legion_space, lighting_transactions

    report = {'version': json.loads((plugin / 'package.json').read_text())['version']}
    subprocess.run(['systemctl', 'stop', 'plugin_loader.service'], check=True)
    before = state.read()
    try:
        awake_get = lambda: device_features.led_status(legion_space._acpi_call, legion_space._acpi_read)
        awake_set = lambda enabled: device_features.set_led(enabled, legion_space._acpi_call, legion_space._acpi_read)
        sleep_get = lambda: community_features.sleep_led_status(legion_space._acpi_call, legion_space._acpi_read)
        sleep_set = lambda enabled: community_features.set_sleep_led(enabled, legion_space._acpi_call, legion_space._acpi_read)
        rgb_before = lighting_transactions.capture_rgb()
        awake_before, sleep_before = awake_get(), sleep_get()
        report['awake_led_readable'] = awake_before['success']
        report['sleep_led_readable'] = sleep_before['success']
        rgb = community_features.rgb_status()
        try:
            changed = community_features.set_rgb(rgb['brightness'], rgb['color'])
            report['rgb_apply_verified'] = changed['success']
        finally:
            report['rgb_exact_restore_verified'] = lighting_transactions.restore_rgb(rgb_before)['success']
        night = lighting_transactions.NightMode(state.read, state.merge, awake_get, awake_set, sleep_get, sleep_set)
        previous_night = before.get('nightMode') or {}
        if previous_night.get('active') or previous_night.get('pending'):
            report['night_mode_roundtrip'] = 'Skipped to preserve an existing night-mode transaction'
        else:
            try:
                enabled = night.set_enabled(True)
                report['night_mode_off_state_verified'] = bool(enabled['success'] and enabled['verified'])
            finally:
                restored = night.set_enabled(False)
                report['night_mode_restore_verified'] = bool(restored['success'] and not restored['active'])
            report['lighting_preserved'] = (
                lighting_transactions.capture_rgb() == rgb_before
                and awake_get().get('enabled') == awake_before.get('enabled')
                and sleep_get().get('enabled') == sleep_before.get('enabled')
            )
        router = controller_support.InputRouter()
        original_targets = router.targets(router.composite())
        route, snapshot = router.repair(state.read().get('directTouchpadRoute'))
        report['touchpad_pointer_enabled'] = bool(route['success'] and route.get('direct_pointer'))
        report['existing_controller_targets_preserved'] = all(
            router.targets(router.composite()).get(path) == kind for path, kind in original_targets.items())
        if route['success']:
            try:
                state.merge({'directTouchpadRoute': snapshot})
            except Exception:
                if snapshot:
                    router.restore(snapshot)
                raise
        report['gyro_test'] = controller_support.sample_tablet_gyro(duration=0.5)
        diagnostics = community_features.diagnostics()
        health = device_automation.collect_resume_health(state.read(), diagnostics,
            legion_space._acpi_call, legion_space._acpi_read, awake_get, sleep_get)
        state.merge({'resumeHealth': health})
        report['read_only_health_check'] = health
        after = state.read()
        protected = ('fan', 'customFanCurvesEnabled', 'fanPerGameProfilesEnabled',
                     'bazziteFanProfiles', 'bazziteActiveFanProfile', 'controller',
                     'controllerRemappingEnabled', 'powerLedEnabled', 'sleepLedEnabled', 'chargeLimitEnabled')
        report['existing_preferences_preserved'] = all(before.get(key) == after.get(key) for key in protected)
        report['installed_frontend_matches_build'] = (
            hashlib.sha256((plugin / 'dist/index.js').read_bytes()).digest()
            == hashlib.sha256((source / 'dist/index.js').read_bytes()).digest())
    except Exception as error:
        report['check_error'] = type(error).__name__
        raise
    finally:
        destination = Path('/var/lib/legion-center-bazzite')
        destination.mkdir(parents=True, exist_ok=True)
        (destination / 'latest-device-check.json').write_text(json.dumps(report, indent=2) + '\n')
        subprocess.run(['systemctl', 'start', 'plugin_loader.service'], check=True)
        print(json.dumps(report, indent=2))
    time.sleep(3)


if __name__ == '__main__':
    main()
