"""InputPlumber pointer routing and bounded, read-only gyro diagnostics."""
import json
from pathlib import Path
import re
import subprocess
import time

SERVICE = 'org.shadowblip.InputPlumber'
MANAGER = '/org/shadowblip/InputPlumber/Manager'
MANAGER_IFACE = 'org.shadowblip.InputManager'
COMPOSITE_IFACE = 'org.shadowblip.Input.CompositeDevice'
TARGET_IFACE = 'org.shadowblip.Input.Target'


class InputRouter:
    def __init__(self, runner=subprocess.run, sleeper=time.sleep,
                 boot_path=Path('/proc/sys/kernel/random/boot_id')):
        self.runner = runner
        self.sleep = sleeper
        self.boot_path = boot_path

    def _run(self, args):
        result = self.runner(args, capture_output=True, text=True, timeout=5,
                             env={'PATH': '/usr/sbin:/usr/bin'})
        if result.returncode:
            raise RuntimeError('InputPlumber did not accept the request')
        return result.stdout

    def property(self, path, interface, name):
        return json.loads(self._run(['busctl', '--json=short', 'get-property',
                                    SERVICE, path, interface, name]))['data']

    def call(self, path, interface, method, signature='', *args):
        command = ['busctl', '--json=short', 'call', SERVICE, path, interface, method]
        if signature:
            command += [signature, *args]
        output = self._run(command).strip()
        if not output:
            return None
        value = json.loads(output)['data']
        return value[0] if isinstance(value, list) and len(value) == 1 else value

    def identity(self):
        owner = json.loads(self._run(['busctl', '--json=short', 'call',
            'org.freedesktop.DBus', '/org/freedesktop/DBus', 'org.freedesktop.DBus',
            'GetNameOwner', 's', SERVICE]))['data'][0]
        return {'owner': owner, 'boot': self.boot_path.read_text().strip()}

    def composite(self):
        paths = self._run(['busctl', '--list', 'tree', SERVICE]).splitlines()
        for path in paths:
            if re.fullmatch(r'/org/shadowblip/InputPlumber/CompositeDevice\d+', path):
                if self.property(path, COMPOSITE_IFACE, 'Name') == 'Lenovo Legion Go':
                    return path
        raise RuntimeError('The original Legion Go controller was not found')

    def targets(self, composite):
        paths = self.property(composite, COMPOSITE_IFACE, 'TargetDevices')
        # Some releases retain stopped target paths in the composite property.
        # Count only objects still exported on D-Bus; do not reset the controller.
        live = set(self._run(['busctl', '--list', 'tree', SERVICE]).splitlines())
        result = {}
        for path in paths:
            if path not in live:
                continue
            try:
                result[path] = self.property(path, TARGET_IFACE, 'DeviceType')
            except RuntimeError:
                self.sleep(0.05)
                latest = set(self._run(['busctl', '--list', 'tree', SERVICE]).splitlines())
                if path in latest:
                    raise
        return result

    def status(self, snapshot=None):
        try:
            composite = self.composite()
            targets = self.targets(composite)
            capabilities = self.property(composite, COMPOSITE_IFACE, 'Capabilities')
            filtered = self.property(composite, COMPOSITE_IFACE, 'FilteredEvents')
            can_restore = bool(snapshot and snapshot.get('identity') == self.identity()
                               and targets.get(snapshot.get('target')) == 'touchpad')
            return {'success': True, 'controller_present': True,
                    'touchpad_detected': any(x.startswith('Touchpad:') and x.endswith(':Motion') for x in capabilities),
                    'direct_pointer': 'touchpad' in targets.values(),
                    'can_restore': can_restore,
                    'gyro': {name: {'available': 'Gyroscope:' + name in capabilities,
                                   'filtered_sources': sum('Gyroscope:' + name in values for values in filtered.values())}
                             for name in ('Center', 'Left', 'Right')},
                    'message': 'Direct pointer routing bypasses Steam Input touchpad translation.'}
        except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError):
            return {'success': False, 'controller_present': False,
                    'touchpad_detected': False, 'direct_pointer': False, 'can_restore': False,
                    'gyro': {}, 'message': 'InputPlumber controller information is unavailable.'}

    def repair(self, snapshot=None):
        created = None
        try:
            composite = self.composite()
            previous = self.targets(composite)
            if 'touchpad' in previous.values():
                return self.status(snapshot), snapshot
            supported = self.property(MANAGER, MANAGER_IFACE, 'SupportedTargetDeviceIds')
            if 'touchpad' not in supported:
                raise RuntimeError('This InputPlumber version has no native touchpad target')
            identity = self.identity()
            candidate = self.call(MANAGER, MANAGER_IFACE, 'CreateTargetDevice', 's', 'touchpad')
            if not isinstance(candidate, str) or not re.fullmatch(r'/org/shadowblip/InputPlumber/devices/target/touchpad\d+', candidate):
                raise RuntimeError('InputPlumber returned an unexpected target identifier')
            if candidate in previous:
                raise RuntimeError('InputPlumber returned an existing target')
            created = candidate
            self.call(MANAGER, MANAGER_IFACE, 'AttachTargetDevice', 'ss', created, composite)
            for _ in range(12):
                current = self.targets(composite)
                if current.get(created) == 'touchpad':
                    break
                self.sleep(0.1)
            else:
                raise RuntimeError('The pointer target was not attached')
            if any(current.get(path) != kind for path, kind in previous.items()):
                raise RuntimeError('Existing controller targets changed unexpectedly')
            saved = {'target': created, 'identity': identity}
            result = self.status(saved)
            result['message'] = 'Pointer route enabled. Move and tap the physical touchpad to test it.'
            return result, saved
        except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError):
            if created:
                try:
                    self.call(MANAGER, MANAGER_IFACE, 'StopTargetDevice', 's', created)
                except Exception:
                    pass
            result = self.status(snapshot)
            return {**result, 'success': False, 'message': 'Could not add the pointer route. Existing controller settings were retained.'}, snapshot

    def restore(self, snapshot):
        try:
            if not snapshot or snapshot.get('identity') != self.identity():
                raise RuntimeError('The saved route belongs to another InputPlumber session')
            composite = self.composite()
            before = self.targets(composite)
            target = snapshot.get('target')
            if before.get(target) != 'touchpad':
                raise RuntimeError('The plugin-owned touchpad route is no longer present')
            self.call(MANAGER, MANAGER_IFACE, 'StopTargetDevice', 's', target)
            for _ in range(12):
                after = self.targets(composite)
                if target not in after:
                    break
                self.sleep(0.1)
            else:
                raise RuntimeError('The added pointer route was not removed')
            if any(after.get(path) != kind for path, kind in before.items() if path != target):
                raise RuntimeError('Another target changed during removal')
            return self.status(), None
        except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError):
            return {'success': False, 'message': 'Could not restore this route safely. No unrelated target was stopped.'}, snapshot


def sample_tablet_gyro(root=Path('/sys/bus/iio/devices'), duration=3.0,
                       clock=time.monotonic, sleeper=time.sleep):
    """Sample exposed IIO values without grabbing devices or changing filters."""
    if not 0 < duration <= 5:
        raise ValueError('Gyro tests must be bounded to five seconds')
    devices = []
    for device in Path(root).glob('iio:device*'):
        try:
            if 'gyro' not in (device / 'name').read_text().lower():
                continue
            paths = [device / ('in_anglvel_' + axis + '_raw') for axis in 'xyz']
            scale = float((device / 'in_anglvel_scale').read_text())
            if not all(path.is_file() for path in paths) or scale <= 0:
                continue
            devices.append((paths, scale))
        except (OSError, ValueError):
            continue
    samples = [[] for _ in devices]
    deadline = clock() + duration
    while devices and clock() < deadline:
        for index, (paths, scale) in enumerate(devices):
            try:
                samples[index].append(tuple(float(path.read_text()) * scale for path in paths))
            except (OSError, ValueError):
                continue
        sleeper(0.15)
    count = sum(len(values) for values in samples)
    span = max((max(max(sample[a] for sample in values) - min(sample[a] for sample in values)
                    for a in range(3)) for values in samples if values), default=0.0)
    return {'success': count > 0, 'samples': count, 'motion_detected': span > 0.02,
            'source': 'Tablet IIO gyro',
            'message': ('Motion detected in tablet gyro data.' if span > 0.02 else
                        'No motion detected. Move the device during the test; zero data is not proof of a failed sensor.') if count else
                       'No readable tablet gyro stream is exposed. Controller gyro routing is reported separately.'}
