"""Install a locally built community plugin without modifying kernel support."""
from datetime import datetime, timezone
import os
from pathlib import Path
import pwd
import shutil
import subprocess
import sys
import tempfile


def main():
    source = Path(__file__).resolve().parents[1]
    if not (source / 'dist/index.js').is_file():
        raise SystemExit('Build the plugin first: pnpm install --frozen-lockfile && pnpm run build')
    if os.geteuid() != 0:
        os.execvp('pkexec', ['pkexec', sys.executable, str(Path(__file__).resolve())])
    uid = os.environ.get('PKEXEC_UID') or os.environ.get('SUDO_UID')
    if uid is None or int(uid) == 0:
        raise SystemExit('Run install.sh as your desktop user so its Decky installation can be located.')
    home = Path(pwd.getpwuid(int(uid)).pw_dir)
    target = home / 'homebrew/plugins/LegionCenter'
    if not target.parent.is_dir():
        raise SystemExit('Decky Loader was not found for the desktop user.')
    backup_root = Path('/var/lib/legion-center-bazzite/backups')
    backup_root.mkdir(parents=True, exist_ok=True)
    backup = backup_root / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    was_active = subprocess.run(['systemctl', 'is-active', '--quiet', 'plugin_loader.service']).returncode == 0
    with tempfile.TemporaryDirectory(prefix='.legion-center-', dir=target.parent) as temporary:
        staged = Path(temporary) / 'LegionCenter'
        staged.mkdir()
        for name in ('LICENSE', 'README.md', 'THIRD_PARTY_NOTICES.md', 'main.py', 'package.json', 'plugin.json', 'requirements.txt'):
            shutil.copy2(source / name, staged / name)
        for name in ('assets', 'defaults', 'dist', 'py_modules'):
            shutil.copytree(source / name, staged / name, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        if was_active:
            subprocess.run(['systemctl', 'stop', 'plugin_loader.service'], check=True)
        try:
            previous = Path(temporary) / 'previous'
            if target.exists():
                backup.mkdir()
                shutil.copytree(target, backup / 'LegionCenter')
                target.rename(previous)
            staged.rename(target)
        except BaseException:
            if previous.exists() and not target.exists():
                previous.rename(target)
            raise
        finally:
            if was_active:
                subprocess.run(['systemctl', 'start', 'plugin_loader.service'], check=True)
    print('Community plugin installed. Existing Decky settings were preserved.')
    print('Kernel module installation is separate; check Fan support before using custom curves.')


if __name__ == '__main__':
    main()
