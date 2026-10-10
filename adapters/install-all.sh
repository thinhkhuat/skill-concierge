#!/usr/bin/env bash
# skill-concierge — run every harness installer, then doctor, then the live smoke. The release
# step: commit, run this, push only when it ends green.
#
# Globs adapters/*/install.sh, so a new adapter is covered the day its installer lands; nothing
# here lists harnesses by name. Each installer runs to completion even when an earlier one fails
# (one broken harness must not leave the others on the old version). scripts/smoke.py then runs one
# real headless turn per harness; doctor only proves files exist. Arguments go to smoke.py (for
# example --accept-unproven zcode). The exit status is non-zero when any installer or any smoke row
# failed. Logs: $SC_INSTALL_LOG_DIR (default ~/.cache/skill-concierge/install-all).
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

python3 "$ROOT/scripts/smoke.py" "$@" || failed="$failed smoke"

if [ -n "$failed" ]; then
  echo "==> failed:$failed" >&2
  exit 1
fi
