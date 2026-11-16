"""Update a compatible installed Bazzite frontend while retaining its backend."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import pwd
import shutil
import subprocess
import tempfile
import time


def main():
    if os.geteuid() != 0:
        raise SystemExit('Run with pkexec from the desktop session.')
    uid = os.environ.get('PKEXEC_UID') or os.environ.get('SUDO_UID')
    if uid is None or int(uid) == 0:
        raise SystemExit('The desktop user could not be determined.')
    source = Path(__file__).resolve().parents[1]
    home = Path(pwd.getpwuid(int(uid)).pw_dir)
    plugin = home / 'homebrew/plugins/LegionCenter'
    settings = home / 'homebrew/settings/LegionCenter/settings.json'
    if not (plugin / 'py_modules/fan_presets.py').exists():
        raise SystemExit('This UI update requires the existing Bazzite profile backend.')
    before = json.loads(settings.read_text())
    backup = Path('/var/lib/legion-center-bazzite/backups') / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup.mkdir(parents=True)
    files = ('package.json', 'plugin.json', 'README.md')
    subprocess.run(['systemctl', 'stop', 'plugin_loader.service'], check=True)
    try:
        shutil.copytree(plugin / 'dist', backup / 'dist')
        for name in files:
            shutil.copy2(plugin / name, backup / name)
        shutil.copy2(settings, backup / 'settings.json')
        with tempfile.TemporaryDirectory(prefix='.frontend-', dir=plugin) as temporary:
            staged = Path(temporary) / 'dist'
            previous = Path(temporary) / 'previous'
            shutil.copytree(source / 'dist', staged)
            (plugin / 'dist').rename(previous)
            try:
                staged.rename(plugin / 'dist')
            except BaseException:
                previous.rename(plugin / 'dist')
                raise
        for name in files:
            shutil.copyfile(source / name, plugin / name)
            os.chmod(plugin / name, 0o644)
    except BaseException:
        if (backup / 'dist').exists():
            shutil.copytree(backup / 'dist', plugin / 'dist', dirs_exist_ok=True)
        for name in files:
            if (backup / name).exists():
                shutil.copy2(backup / name, plugin / name)
        raise
    finally:
        subprocess.run(['systemctl', 'start', 'plugin_loader.service'], check=True)
    time.sleep(6)
    after = json.loads(settings.read_text())
    result = {
        'installed': True,
        'version': json.loads((plugin / 'package.json').read_text())['version'],
        'frontend_sha256': hashlib.sha256((plugin / 'dist/index.js').read_bytes()).hexdigest(),
        'source_sha256': hashlib.sha256((source / 'dist/index.js').read_bytes()).hexdigest(),
        'profiles_preserved': before.get('fan') == after.get('fan') and before.get('bazziteFanProfiles') == after.get('bazziteFanProfiles'),
        'custom_control_preference_preserved': before.get('customFanCurvesEnabled') == after.get('customFanCurvesEnabled'),
        'backend_unchanged': True,
    }
    report_dir = Path('/var/lib/legion-center-bazzite')
    (report_dir / 'ui-install-status.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
    if not result['profiles_preserved'] or not result['custom_control_preference_preserved']:
        raise SystemExit('Installation completed, but a settings verification failed.')


if __name__ == '__main__':
    main()
