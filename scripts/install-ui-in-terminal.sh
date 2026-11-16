#!/usr/bin/env bash
set -u
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
pkexec /usr/bin/python3 "$script_dir/install-ui.py"
result=$?
printf 'UI installation exit status: %s\n' "$result"
read -r -p 'Press Enter to close: ' reply
