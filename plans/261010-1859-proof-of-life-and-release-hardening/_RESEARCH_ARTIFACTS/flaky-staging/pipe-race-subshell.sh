#!/bin/bash
# same as pipe-race.sh, but the pipeline runs inside a subshell, so the shell that holds the
# handler never forks a two-process pipeline.
d=$(mktemp -d); stage=""
trap '[ -z "$stage" ] || rm -rf "$stage"; exit 1' EXIT INT TERM
stage="$d/stg"; mkdir "$stage"
if ! ( ( sleep 1; head -c 200000 /dev/zero ) | tar -tf - >/dev/null 2>&1 ) ; then :; fi
