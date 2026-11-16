"""Verified power LED protocol and controller-emulator compatibility checks.

Protocol reference: hhd-dev/adjustor core/lenovo.py get/set_power_light.
Selectors and byte values are firmware protocol facts; this implementation is independent.
"""
import subprocess

POWER_LIGHT_METHOD = r'\_SB.GZFD.WMAF'
ACTIVE_SELECTOR = 0x04
LED_OFF = 0x01
LED_ON = 0x02

def led_status(call, read):
    try:
        if not call(POWER_LIGHT_METHOD, [0, 1, ACTIVE_SELECTOR], risky=False):
            raise RuntimeError('Power LED query failed')
        response = read()
        if not isinstance(response, bytes) or len(response) != 2 or response[1] not in (LED_OFF, LED_ON):
            raise RuntimeError(f'Unsupported power LED response: {response!r}')
        return dict(success=True, supported=True, enabled=response[1] == LED_ON,
                    backend='lenovo-wmi-active-led', error=None)
    except Exception as error:
        return dict(success=False, supported=False, enabled=None, backend=None, error=str(error))

def set_led(enabled, call, read):
    if type(enabled) is not bool:
        return dict(success=False, error='Power LED value must be boolean')
    current = led_status(call, read)
    if not current['supported'] or current['enabled'] == enabled:
        return current
    if not call(POWER_LIGHT_METHOD, [0, 2, bytes([ACTIVE_SELECTOR, 0, LED_ON if enabled else LED_OFF])]):
        return {**current, 'success':False, 'error':'Power LED write failed'}
    verified = led_status(call, read)
    if not verified['supported'] or verified['enabled'] != enabled:
        return {**verified, 'success':False, 'error':'Firmware did not confirm the requested power LED state'}
    return verified

def controller_status(runner=subprocess.run):
    try:
        result = runner(['systemctl','is-active','inputplumber.service','hhd.service'],
                        capture_output=True,text=True,timeout=3,
                        env={'PATH':'/usr/sbin:/usr/bin'})
        if 'active' in result.stdout.splitlines():
            return dict(supported=False, error='InputPlumber/HHD manages the controller. Use Steam Input for back buttons and gyro; firmware remaps are disabled to avoid conflicts.')
        if result.returncode not in (0,3,4):
            raise RuntimeError('Could not determine controller service state')
        return dict(supported=True,error=None)
    except Exception as error:
        return dict(supported=False,error=f'Controller compatibility check failed: {error}')
