"""Install the local build and run the explicitly requested device checks."""
from pathlib import Path
import os
import runpy
import time

if os.geteuid() != 0:
    raise SystemExit('Run through pkexec as the desktop user.')
directory = Path(__file__).resolve().parent
runpy.run_path(str(directory / 'install-local.py'), run_name='__main__')
time.sleep(3)
runpy.run_path(str(directory / 'check-device.py'), run_name='__main__')
