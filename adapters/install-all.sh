#!/usr/bin/env bash
# skill-concierge — run every harness installer, then doctor. The release step after a push.
#
# Globs adapters/*/install.sh, so a new adapter is covered the day its installer lands; nothing
# here lists harnesses by name. Each installer runs to completion even when an earlier one fails
# (one broken harness must not leave the others on the old version); the exit status is non-zero
# when any installer failed. Logs: $SC_INSTALL_LOG_DIR (default ~/.cache/skill-concierge/install-all).
# Must parse and run under macOS's stock /bin/bash 3.2.
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG_DIR="${SC_INSTALL_LOG_DIR:-$HOME/.cache/skill-concierge/install-all}"
mkdir -p "$LOG_DIR"

failed=""
for installer in "$SCRIPT_DIR"/*/install.sh; do
  name="$(basename "$(dirname "$installer")")"
  log="$LOG_DIR/$name.log"
  if bash "$installer" >"$log" 2>&1; then
    echo "  [✓] $name"
  else
    echo "  [✗] $name (exit $?) — see $log"
    failed="$failed $name"
  fi
done

echo "==> doctor"
python3 "$ROOT/scripts/doctor.py" 2>&1 | grep -E 'integration|^status'

if [ -n "$failed" ]; then
  echo "==> installers failed:$failed" >&2
  exit 1
fi
