#!/bin/bash
# usage (from worktree root): slowclose.sh <runs> <pytest target>
D=plans/261010-1859-proof-of-life-and-release-hardening/_RESEARCH_ARTIFACTS/flaky
export PYTHONPATH="$PWD/$D"
for i in $(seq 1 "$1"); do
  python3 -m pytest -q -p no:cacheprovider -p slowclose_plugin "$2" 2>&1 | tail -1
done
