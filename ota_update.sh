#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' 'No community release channel is configured. Build this fork and use install.sh.' >&2
exit 1
