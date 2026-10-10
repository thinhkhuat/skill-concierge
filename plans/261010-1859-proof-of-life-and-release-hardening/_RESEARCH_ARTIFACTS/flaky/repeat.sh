#!/bin/bash
# usage (from worktree root): repeat.sh   -- the flaky test body 40x in one process, gc before each
D=plans/261010-1859-proof-of-life-and-release-hardening/_RESEARCH_ARTIFACTS/flaky
export PYTHONPATH="$PWD/$D:$PWD/tests"
python3 -m pytest -q -p no:cacheprovider -p gc_plugin "$D/test_repeat_envtest.py" 2>&1 | grep -E "^(FAILED|E  )|passed|failed" | sort | uniq -c
