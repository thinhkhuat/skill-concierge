#!/bin/bash
# minimal model of the installer's export: a handler on EXIT/INT/TERM, then a two-stage pipeline
# whose first stage is slow (stands in for `git archive HEAD | tar -x`).
d=$(mktemp -d); stage=""
trap '[ -z "$stage" ] || rm -rf "$stage"; exit 1' EXIT INT TERM
stage="$d/stg"; mkdir "$stage"
if ! ( sleep 1; head -c 200000 /dev/zero ) | tar -tf - >/dev/null 2>&1 ; then :; fi
