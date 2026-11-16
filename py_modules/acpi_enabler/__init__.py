#!/usr/bin/env python3

'''
    MIT License

    Copyright (c) 2026 InnoVision Games

    Permission is hereby granted, free of charge, to any person obtaining a copy
    of this software and associated documentation files (the "Software"), to deal
    in the Software without restriction, including without limitation the rights
    to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
    copies of the Software, and to permit persons to whom the Software is
    furnished to do so, subject to the following conditions:

    The above copyright notice and this permission notice shall be included in all
    copies or substantial portions of the Software.

    THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
    IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
    FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
    AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
    LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
    OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
    SOFTWARE.

    file: acpi_enabler/__init__.py

    Re-exports AcpiEnabler so `from acpi_enabler import AcpiEnabler` (as
    used by steam_os_utils.py) keeps working unchanged now that this is a
    package directory (acpi_enabler/, holding acpi_enabler.py) instead of
    a single flat module -- matching the nvidia_usb_image_builder/
    package's own layout/rationale.
'''

"""Package init: re-exports AcpiEnabler as the package's public API."""

from pathlib import Path


def _is_steamos():
    try:
        for line in Path('/etc/os-release').read_text().splitlines():
            if line.startswith('ID=') and line[3:].strip('"\'').lower() == 'steamos':
                return True
    except OSError:
        pass
    return False


if Path('/etc/systemd/system/legion-fan-support.service').exists() or not _is_steamos():
    try:
        import fan_support_installer
    except ImportError:
        from .. import fan_support_installer

    class AcpiEnabler:
        """Bazzite and other non-SteamOS systems: build the bundled acpi_call module."""
        ACPI_CALL_CONF_PATH = Path('/etc/systemd/system/legion-fan-support.service')

        def __init__(self, **kwargs):
            pass

        def enable(self):
            try:
                fan_support_installer.install()
            except fan_support_installer.FanSupportError as error:
                raise RuntimeError(str(error)) from error

        def disable(self):
            raise RuntimeError('Use Enable Custom Fan Curves to return to firmware control')
else:
    from .acpi_enabler import AcpiEnabler

__all__ = ['AcpiEnabler']
