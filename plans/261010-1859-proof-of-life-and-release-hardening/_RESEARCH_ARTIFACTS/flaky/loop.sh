#!/bin/bash
# usage: loop.sh <label> <count> <pytest args...>   (run from the worktree root)
L="$1"; N="$2"; shift 2
D=plans/261010-1859-proof-of-life-and-release-hardening/_RESEARCH_ARTIFACTS/flaky
for i in $(seq 1 "$N"); do
  python3 -m pytest -q -p no:cacheprovider "$@" > "$D/$L-$i.txt" 2>&1 || echo "FAIL $L-$i" >> "$D/$L-summary.txt"
done
echo "done $N" >> "$D/$L-summary.txt"
