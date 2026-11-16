from pathlib import Path
import tempfile
import unittest

from py_modules.controller_support import InputRouter, COMPOSITE_IFACE, MANAGER_IFACE, sample_tablet_gyro

COMPOSITE = '/org/shadowblip/InputPlumber/CompositeDevice0'
GAMEPAD = '/org/shadowblip/InputPlumber/devices/target/gamepad1'
MOUSE = '/org/shadowblip/InputPlumber/devices/target/mouse0'
TOUCHPAD = '/org/shadowblip/InputPlumber/devices/target/touchpad0'


class FakeRouter(InputRouter):
    def __init__(self):
        self.routes = {GAMEPAD: 'deck-uhid', MOUSE: 'mouse'}
        self.owner = {'owner': ':1.10', 'boot': 'test-boot'}
        self.calls = []
        self.fail_attach = False
        self.candidate = TOUCHPAD
        self.sleep = lambda _: None

    def composite(self):
        return COMPOSITE

    def identity(self):
        return self.owner.copy()

    def targets(self, _composite):
        return self.routes.copy()

    def property(self, _path, interface, name):
        if interface == MANAGER_IFACE:
            return ['touchpad', 'deck-uhid', 'mouse']
        if name == 'Capabilities':
            return ['Touchpad:RightPad:Touch:Motion', 'Gyroscope:Center']
        if name == 'FilteredEvents':
            return {'hidraw://test': ['Gyroscope:Left']}
        raise AssertionError((interface, name))

    def call(self, _path, _interface, method, _signature='', *args):
        self.calls.append((method, args))
        if method == 'CreateTargetDevice':
            return self.candidate
        if method == 'AttachTargetDevice':
            if self.fail_attach:
                raise RuntimeError('attachment refused')
            self.routes[args[0]] = 'touchpad'
        if method == 'StopTargetDevice':
            self.routes.pop(args[0], None)


class PointerRoutingTests(unittest.TestCase):
    def test_repair_preserves_gamepad_and_mouse_and_can_undo(self):
        router = FakeRouter()
        before = router.routes.copy()
        result, snapshot = router.repair()
        self.assertTrue(result['success'])
        self.assertTrue(result['direct_pointer'])
        for path, kind in before.items():
            self.assertEqual(router.routes[path], kind)
        restored, _ = router.restore(snapshot)
        self.assertTrue(restored['success'])
        self.assertEqual(router.routes, before)

    def test_failed_attach_removes_only_the_new_target(self):
        router = FakeRouter()
        router.fail_attach = True
        before = router.routes.copy()
        result, _ = router.repair()
        self.assertFalse(result['success'])
        self.assertEqual(router.routes, before)
        self.assertEqual(router.calls[-1], ('StopTargetDevice', (TOUCHPAD,)))

    def test_bad_target_response_never_stops_a_gamepad(self):
        router = FakeRouter()
        router.candidate = GAMEPAD
        result, _ = router.repair()
        self.assertFalse(result['success'])
        self.assertFalse(any(call[0] == 'StopTargetDevice' for call in router.calls))

    def test_changed_daemon_identity_blocks_stale_undo(self):
        router = FakeRouter()
        _, snapshot = router.repair()
        router.owner['owner'] = ':1.11'
        calls = len(router.calls)
        result, _ = router.restore(snapshot)
        self.assertFalse(result['success'])
        self.assertEqual(len(router.calls), calls)

    def test_existing_native_route_is_not_replaced(self):
        router = FakeRouter()
        router.routes[TOUCHPAD] = 'touchpad'
        result, snapshot = router.repair()
        self.assertTrue(result['success'])
        self.assertIsNone(snapshot)
        self.assertEqual(router.calls, [])

    def test_stale_stopped_target_path_is_ignored(self):
        router = InputRouter(sleeper=lambda _: None)
        router.property = lambda path, interface, name: [GAMEPAD, TOUCHPAD] if name == 'TargetDevices' else 'deck-uhid'
        router._run = lambda args: GAMEPAD + '\n'
        self.assertEqual(router.targets(COMPOSITE), {GAMEPAD:'deck-uhid'})

    def test_target_disappearing_between_tree_and_property_is_safe(self):
        router = InputRouter(sleeper=lambda _: None)
        def prop(path, interface, name):
            if name == 'TargetDevices': return [GAMEPAD, TOUCHPAD]
            if path == TOUCHPAD: raise RuntimeError('target stopped')
            return 'deck-uhid'
        router.property = prop
        outputs = iter([GAMEPAD + '\n' + TOUCHPAD + '\n', GAMEPAD + '\n'])
        router._run = lambda args: next(outputs)
        self.assertEqual(router.targets(COMPOSITE), {GAMEPAD:'deck-uhid'})

    def test_status_does_not_expose_device_or_profile_paths(self):
        result = FakeRouter().status()
        self.assertNotIn('/dev/', str(result))
        self.assertNotIn('/org/', str(result))
        self.assertTrue(result['touchpad_detected'])


class GyroSamplingTests(unittest.TestCase):
    def test_real_motion_is_distinct_from_stationary_readable_values(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            device = root / 'iio:device2'
            device.mkdir()
            (device / 'name').write_text('gyro_3d')
            (device / 'in_anglvel_scale').write_text('0.01')
            for axis in 'xyz':
                (device / ('in_anglvel_' + axis + '_raw')).write_text('0')
            now = [0.0]
            def wait(seconds):
                now[0] += seconds
            still = sample_tablet_gyro(root, 0.5, lambda: now[0], wait)
            self.assertTrue(still['success'])
            self.assertFalse(still['motion_detected'])
            now[0] = 0.0
            def move(seconds):
                wait(seconds)
                (device / 'in_anglvel_x_raw').write_text(str(int(now[0] * 100)))
            moving = sample_tablet_gyro(root, 0.5, lambda: now[0], move)
            self.assertTrue(moving['motion_detected'])
            self.assertNotIn(temporary, str(moving))

    def test_long_or_negative_tests_are_rejected(self):
        for duration in (-1, 0, 10):
            with self.assertRaises(ValueError):
                sample_tablet_gyro(duration=duration)
