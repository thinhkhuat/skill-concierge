# Intermittent staging-dir failures in the installer kill tests: cause, fix, proof (2026-10-10, Asia/Saigon)

Raw output for everything below is in
`plans/261010-1859-proof-of-life-and-release-hardening/_RESEARCH_ARTIFACTS/flaky-staging/`.

## Verdict

This is a real defect in the installers, not test timing and not machine load. There were two separate races in the
export code, both fixed in `adapters/lib/sync.sh` (used by claude-code, codex and zcode) and in `_omp_export_to` in
`adapters/omp/install.sh`. The tests are unchanged in what they assert.

## Reproduction

- Unfixed code, file run solo 50 times (`base-summary.txt`, `base-N.txt`): 2 failures, runs 38 and 48. Both were
  `test_a_signal_killed_codex_export_...` with a `.skill-concierge-staging.*` dir left behind. The earlier debugger saw the
  zcode and omp siblings fail; the victim varies because all four share the code path.
- A second symptom appeared once the first was fixed (`fixed-summary.txt`, 4 failures in 50): `subprocess.TimeoutExpired`
  in the test's `proc.wait(30)`, meaning the installer was still alive 30 s after SIGTERM.

## Cause 1: the signal handler was registered after the directory existed

`mktemp -d` ran first and `trap ... EXIT INT TERM` on the next line. A SIGTERM landing between the two met bash's default
action, which kills the shell and strands the dir. The test sends its SIGTERM at the first instant the dir is visible on
disk, which is exactly that instant, so the test hit the window by design; a real Ctrl-C hits it more rarely, but the
window is real.

Deterministic proof: a `mktemp` shim that creates the dir and then sleeps 2 s keeps the signal inside the window. Two new
tests (`test_a_kill_right_after_mktemp_in_the_shared_export_...` and `..._in_the_omp_export_...`) failed on the unfixed
code, every time, and pass now.

Fix: `stage=""` and the handler are set before `mktemp`; the handler removes `$stage` only when it is non-empty. bash runs a
handler only between commands, so the `stage=$(mktemp ...)` assignment always completes first and the handler then sees the
real path.

## Cause 2: a SIGTERM during pipeline setup hangs bash while it holds a handler

`git archive HEAD | tar -x` is a two-process pipeline. When SIGTERM arrives while bash is forking it, bash is left waiting on
the first stage (`git`), which is blocked writing into a pipe whose read end bash itself still has open (fd 3), because the
second stage (`tar`) was never started. Nothing can proceed and the handler never runs. Process dump from the failing runs
(`hang-probe-3.txt`): `bash install.sh` alive, a child `git archive HEAD` in state S, no `tar` process, `lsof` showing bash
fd 3 and git fd 1 as the two ends of one full 64 KB pipe, and the staging dir still on disk.

The same hang appears in a stripped model with no installer code at all (`pipe-race.sh`, `pipe_race.py`): handler, then a
two-stage pipeline, SIGTERM at a random 0 to 30 ms offset. 8 of 400 hung under bash 5.3.20 and 10 of 400 under macOS
`/bin/bash` 3.2.57. So it is bash behaviour that the installer's structure exposes.

Fix: both export pipelines (the `git archive | tar` one and the non-git `tar | tar` one) now run inside a subshell,
`if ! ( a | b ); then`. The subshell has no handler, and the shell that has one only ever forks a single child. Exit status
and `pipefail` behaviour are unchanged. The same model with the subshell: 0 of 600 under 5.3 and 0 of 600 under 3.2
(`pipe-race-subshell.sh`).

## Machine load ruled out

- Load averages were 4 to 17 while the loops ran (`uptime` readings in the session; other sessions share the machine).
- The cause is demonstrated without load: the `mktemp` shim makes cause 1 fail every time, and the stripped model shows
  cause 2 with a plain `sleep 1`.
- After the fix the file passed 50 of 50 with a load average of 12.38 at the end of the loop (`fixed2-summary.txt`), a
  load higher than at the start of the failing baseline loop (4.62), and the hang probe went from 9 of 100 hangs to 0 of 100 (`hang-probe-3.txt` vs `hang-probe-after-fix.txt`).

## Changes

- `adapters/lib/sync.sh`, `adapters/omp/install.sh`: handler before `mktemp`; pipelines in subshells. Both stay bash 3.2
  compatible (nothing newer than plain `trap`, `[ -z ]`, `( )`). The whole staging file also passed with `/bin/bash`
  3.2.57 substituted for `bash` in the test PATH.
- `tests/test_installer_staging_cleanup.py`: the pinned handler line and the two pipeline lines updated in
  `_CLEANUP_LINES` (the four-installer identity test), plus the two new deterministic kill tests. No assertion loosened; no
  sleep, retry or skip added to any test (the 2 s in the `mktemp` shim is the injected fault, not a wait).

## Proof

- File solo, 50 consecutive runs: 50 passes, 0 failures (`fixed2-summary.txt`).
- Full suite, 2 runs: 1486 passed in 212.64 s and 1486 passed in 225.29 s (`full-1.txt`, `full-2.txt`).

## Not checked

- `adapters/claude-code/install.sh`, `adapters/codex/install.sh` and `adapters/zcode/install.sh` were not edited because
  they source `sync.sh`; the codex and zcode kill tests exercise them, claude-code's kill test is the pre-existing one.
- The hang mechanism is shown by process dumps and a minimal model, not by reading bash's source; the fix is proven by the
  model and the repeated runs, not by a code-level explanation.
- No other installer under `adapters/` (commandcode, dsh, cline, opencode) was audited for the same pipeline-under-handler
  pattern; `grep` shows only these two `trap` sites in `adapters/`.
