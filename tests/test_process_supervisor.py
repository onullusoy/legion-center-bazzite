import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest

HELPER = Path(__file__).resolve().parents[1] / 'py_modules/process_supervisor.py'


class ProcessSupervisorTests(unittest.TestCase):
    def test_rejects_wrong_parent(self):
        result = subprocess.run([sys.executable, str(HELPER), '-1', '/usr/bin/true'])
        self.assertEqual(result.returncode, 1)

    def test_executes_reader(self):
        result = subprocess.run([sys.executable, str(HELPER), str(os.getpid()), '/usr/bin/printf', 'ready'], capture_output=True)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b'ready')

    def test_reader_exits_when_parent_dies(self):
        with tempfile.TemporaryDirectory() as folder:
            marker = Path(folder) / 'ready'
            reader = 'import pathlib,time; pathlib.Path(__import__("sys").argv[1]).write_text("ready"); time.sleep(30)'
            parent_code = 'import os,subprocess,sys,time; p=subprocess.Popen([sys.executable,sys.argv[1],str(os.getpid()),sys.executable,"-c",sys.argv[2],sys.argv[3]]); print(p.pid,flush=True); time.sleep(30)'
            parent = subprocess.Popen([sys.executable, '-c', parent_code, str(HELPER), reader, str(marker)], stdout=subprocess.PIPE, text=True)
            child = int(parent.stdout.readline())
            try:
                deadline = time.monotonic() + 5
                while not marker.exists() and time.monotonic() < deadline:
                    time.sleep(.02)
                self.assertTrue(marker.exists())
                parent.terminate()
                parent.wait(timeout=5)
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    stat = Path(f'/proc/{child}/stat')
                    if not stat.exists() or stat.read_text().split(') ', 1)[1].startswith('Z'):
                        break
                    time.sleep(.02)
                else:
                    self.fail('Reader survived parent termination')
            finally:
                if parent.poll() is None:
                    parent.kill()
                    parent.wait()
                parent.stdout.close()
                try:
                    os.kill(child, signal.SIGTERM)
                except ProcessLookupError:
                    pass
