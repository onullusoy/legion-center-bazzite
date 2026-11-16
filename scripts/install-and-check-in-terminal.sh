#!/usr/bin/env bash
set -u
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
pkexec /usr/bin/python3 "$script_dir/install-and-check.py"
result=$?
printf 'Installation and device check exit status: %s\n' "$result"
read -r -p 'Press Enter to close: ' reply
