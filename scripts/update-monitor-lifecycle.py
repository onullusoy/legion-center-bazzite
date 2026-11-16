"""Install the monitor lifecycle fix and remove only this plugin's orphan readers."""
import json
import os
from pathlib import Path
import pwd
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone


def monitor_processes(group, match):
    matches = []
    for process in Path('/proc').glob('[0-9]*'):
        try:
            parts = (process / 'cmdline').read_bytes().rstrip(b'\0').split(b'\0')
            args = [part.decode() for part in parts]
            if not args or Path(args[0]).name != 'dbus-monitor' or args[1:] != ['--system', '--monitor', match]:
                continue
            groups = [line.split(':', 2)[-1] for line in (process / 'cgroup').read_text().splitlines()]
            if group not in groups:
                continue
            status = dict(line.split(':', 1) for line in (process / 'status').read_text().splitlines() if ':' in line)
            if int(status['Uid'].split()[0]) == 0:
                matches.append((int(process.name), int(status['PPid'].strip())))
        except (OSError, ValueError, KeyError, UnicodeError):
            continue
    return matches


def main():
    if os.geteuid() != 0:
        raise SystemExit('Run through pkexec as the desktop user.')
    uid = os.environ.get('PKEXEC_UID') or os.environ.get('SUDO_UID')
    if uid is None or int(uid) == 0:
        raise SystemExit('The desktop user could not be determined.')
    home = Path(pwd.getpwuid(int(uid)).pw_dir)
    plugin = home / 'homebrew/plugins/LegionCenter'
    source = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(source / 'py_modules'))
    import device_automation
    files = ('device_automation.py', 'process_supervisor.py')
    if not all((source / 'py_modules' / name).is_file() for name in files):
        raise SystemExit('The complete lifecycle patch is not available.')
    group = subprocess.check_output(['systemctl', 'show', 'plugin_loader.service', '-p', 'ControlGroup', '--value'], text=True).strip()
    if not group:
        raise SystemExit('The Decky service cgroup could not be identified.')
    subprocess.run(['systemctl', 'stop', 'plugin_loader.service'], check=True)
    cleaned = 0
    try:
        backup = Path('/var/lib/legion-center-bazzite/backups') / ('monitor-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
        backup.mkdir(parents=True)
        for name in files:
            if (plugin / 'py_modules' / name).exists():
                shutil.copy2(plugin / 'py_modules' / name, backup / name)
            shutil.copyfile(source / 'py_modules' / name, plugin / 'py_modules' / name)
            os.chmod(plugin / 'py_modules' / name, 0o644)
        time.sleep(0.2)
        for pid, parent in monitor_processes(group, device_automation.SLEEP_MATCH):
            if parent != 1:
                continue
            try:
                descriptor = os.pidfd_open(pid)
                try:
                    signal.pidfd_send_signal(descriptor, signal.SIGTERM)
                    cleaned += 1
                finally:
                    os.close(descriptor)
            except ProcessLookupError:
                pass
    finally:
        subprocess.run(['systemctl', 'start', 'plugin_loader.service'], check=True)
    time.sleep(4)
    first = len(monitor_processes(group, device_automation.SLEEP_MATCH))
    try:
        subprocess.run(['systemctl', 'stop', 'plugin_loader.service'], check=True)
        time.sleep(0.5)
        stopped = len(monitor_processes(group, device_automation.SLEEP_MATCH))
    finally:
        subprocess.run(['systemctl', 'start', 'plugin_loader.service'], check=True)
    time.sleep(4)
    after = len(monitor_processes(group, device_automation.SLEEP_MATCH))
    report = {'old_orphan_monitors_removed': cleaned, 'running_before_restart': first,
              'remaining_after_stop': stopped, 'running_after_restart': after,
              'passed': first == 1 and stopped == 0 and after == 1}
    (Path('/var/lib/legion-center-bazzite') / 'monitor-lifecycle-check.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    if not report['passed']:
        raise SystemExit('Monitor lifecycle validation failed.')


if __name__ == '__main__':
    main()
