#!/bin/bash
# usage (from worktree root): gcrun.sh <runs> <pytest target...>
D=plans/261010-1859-proof-of-life-and-release-hardening/_RESEARCH_ARTIFACTS/flaky
export PYTHONPATH="$PWD/$D"
n="$1"; shift
for i in $(seq 1 "$n"); do
  python3 -m pytest -q -p no:cacheprovider -p gc_plugin "$@" 2>&1 | grep -E "^(FAILED|E  )|passed|failed"
done
