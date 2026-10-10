#!/bin/bash
# usage: loop.sh PREFIX N  -- runs the staging file solo N times, one output file per run
d="$(cd "$(dirname "$0")" && pwd)"; cd "$d/../../../.."
p=$1; n=$2; : > "$d/$p-summary.txt"
for i in $(seq 1 $n); do
  python3 -m pytest -q -p no:cacheprovider tests/test_installer_staging_cleanup.py > "$d/$p-$i.txt" 2>&1
  echo "$i rc=$?" >> "$d/$p-summary.txt"
done
echo "failures: $(grep -vc 'rc=0' "$d/$p-summary.txt")" >> "$d/$p-summary.txt"
