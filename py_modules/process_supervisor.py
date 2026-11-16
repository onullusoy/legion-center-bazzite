"""Execute a reader with a Linux parent-death signal, without preexec_fn."""
import ctypes
import os
import signal
import sys


def execute(parent_pid, command):
    if not command or os.getppid() != parent_pid:
        return 1
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(1, signal.SIGTERM, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "Could not register parent-death signal")
    # Close the race between observing the parent and registering the signal.
    if os.getppid() != parent_pid:
        return 1
    os.execvp(command[0], command)


if __name__ == "__main__":
    raise SystemExit(execute(int(sys.argv[1]), sys.argv[2:]))
