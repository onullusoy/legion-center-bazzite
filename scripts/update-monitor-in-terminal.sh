#!/usr/bin/env bash
set -u
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
pkexec /usr/bin/python3 "$script_dir/update-monitor-lifecycle.py"
result=$?
printf 'Monitor lifecycle update exit status: %s\n' "$result"
read -r -p 'Press Enter to close: ' reply
