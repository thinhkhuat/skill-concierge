# Two flaky tests: cause, fix, proof (2026-10-10, Asia/Saigon)

Raw output for everything below is in
`plans/261010-1859-proof-of-life-and-release-hardening/_RESEARCH_ARTIFACTS/flaky/` (file names are given in each section).

## Summary

Both failures are real defects, not machine load.

1. `test_a_pooled_connection_the_provider_closed_is_discarded_before_use` is a test race. The fake provider closes its
   socket in the handler thread after the reply is already on the wire, so the client can pool the connection and reuse
   it before the close happens. The test never waited for the close it claims to test. Fixed in the test.
2. `test_enforcer_setup_leaves_the_process_environment_alone` exposes a real bug in the code under test,
   `scripts/trigger_filter.py::_enforcer`. It recorded "timeouts already set" by `id(module)` in a module-level set.
   A freed module's `id` is reused by the next module, so a fresh enforcer module silently skipped the setup and kept
   its default `EMBED_TIMEOUT_S` (0.5) instead of 15.0. Fixed in the code: the flag now lives on the module object.

## 1. Relay test

Reproduction (unfixed code): the two files together failed in 5 of 30 runs (`pair-4`, `-16`, `-19`, `-27`, `-29`, listed
in `pair-summary.txt`). Every one is this test, at the `getresponse()` of a `_jev_relay` call (index_owner.py:761 in all five), i.e. on a reused pooled connection:

- `pair-16.txt`, `pair-19.txt`, `pair-29.txt`: `ConnectionResetError: [Errno 54] Connection reset by peer` raised in
  `conn.getresponse()` (`vendor/skill-search/skill_search/index_owner.py:761`).
- `pair-4.txt`, `pair-27.txt`: `http.client.RemoteDisconnected: Remote end closed connection without response`, same line.

Mechanism (read from source, `tests/test_owner_jev_relay.py` and `index_owner.py:691-731`):

- In `silent-close` mode the fake handler sends the reply, then sets `close_connection = True`. The socket is closed only
  after `do_POST` returns, in `shutdown_request`, in the server thread.
- The client reads the reply and pools the connection at once. The next `_jev_relay` calls `_jev_alive()`, a zero-timeout
  `select`. If the server thread has not closed yet, the socket looks alive, the request is written, and the server then
  closes with that request unread. The client gets a reset or an empty read. By the documented policy
  (`index_owner.py:681-684`) a request written in full is never re-sent, so the exception propagates. That policy is
  correct and is not changed.
- The scenario the test names ("a pooled connection the provider had already closed") only exists once the close has
  happened. The test did not guarantee that.

Evidence it is the gap and not load:

- With the close delayed by 50 ms (`slowclose_plugin.py`, `slowclose.sh`), the unfixed test failed 5 of 5
  (`slowclose-before-fix.txt`). With the wait added it passed 5 of 5 under the same delay (`slowclose-after-fix.txt`).
  A load-only cause would not turn into a deterministic failure from one added sleep inside the fake provider.
- Load averages while the loops ran were about 5 to 8 on a 14-core machine (`uptime`: 4.99 / 8.04 / 6.05 at the start,
  7.03 / 5.54 / 5.95 at the end). That is busy but not saturated. It widens a window that exists regardless, so
  "load" is the trigger of the race, not an alternative cause. Fixing the window removes the failure at any load.

Fix (`tests/test_owner_jev_relay.py`): the fake server records each finished close in a queue (`Fake.closed`, filled in
an overridden `shutdown_request`), and the test waits for it after every request before reusing the connection. The test
still asserts what it asserted (3 requests, 3 connections, each sent once), and the production code is untouched.

## 2. Trigger-filter test

Cause, in `scripts/trigger_filter.py` (before the fix):

```
_TIMEOUTS_SET = set()
...
if id(enf) not in _TIMEOUTS_SET: ...set 15.0...; _TIMEOUTS_SET.add(id(enf))
```

The enforcer module is loaded by `jev_client.load_enforcer()`, and tests (and `env`) reset `jev_client._ENF`, so modules
are created and dropped repeatedly. A module is a reference cycle, so the cycle collector frees it at a moment that
depends on allocation history. CPython then hands the freed address to the next allocation of that size. When the new
module lands on an address already in `_TIMEOUTS_SET`, `_enforcer()` skips the setup, and the test's
`mods[0].EMBED_TIMEOUT_S == 15.0` fails with 0.5. The failure depends on collector timing, hence "once in a full run,
passes alone".

Evidence:

- `idreuse_probe.py` against the unfixed code: load, drop, collect, load again, 40 times, 19 of 40 fresh modules were
  skipped, each with `EMBED_TIMEOUT_S=0.5` and `id` already in the set (`idreuse_probe-output.txt`, tail of the run).
  After the fix: 40 of 40 applied (`idreuse_probe-after-fix.txt`).
- A new regression test, `test_enforcer_setup_reaches_every_new_module_even_when_a_freed_one_had_its_address`, frees a
  stub module and loads another, 200 times. Unfixed it fails deterministically (`regression-before-fix.txt`:
  `At index 0 diff: 0.5 != 15.0`); fixed it passes.
- Machine load is ruled out for this test because it has no timing, I/O or sockets: it is a pure in-process function of
  object lifetimes.

Fix (`scripts/trigger_filter.py`): `_TIMEOUTS_SET` removed; the "already set" flag is an attribute on the module
object (`enf._offline_timeouts_set`), still under `_TIMEOUT_LOCK`. Behavior otherwise unchanged (an explicit
`ENFORCER_*_TIMEOUT` still wins; nothing is written to `os.environ`).

What I could not do: reproduce the failure of the original test itself at pytest level. 20 solo runs of the file, 5 runs
with the collector forced before every test and at tiny thresholds, and 40 in-process repeats all passed
(`base-tf-*`, `gc-before-fix.txt`, `repeat-before-fix.txt`), and the failing assertion text of the 2026-10-10 failure was
not available to me. The link between that one observed failure and the id reuse is therefore an inference
(a defect with exactly that symptom, proven present, and no other mechanism found), not an observed trace. The one
other mechanism I considered, a stray thread's `SKILL_CONCIERGE_LOG` set/restore overlapping `before = dict(os.environ)`,
needs a leaked thread calling `load_enforcer`; I found none.

## Proof after the fix

| Run | Result |
|---|---|
| Two files together, unfixed (this session) | 5 failures in 30 runs |
| Full suite, unfixed | 1 failure (the relay test) in 3 runs (`base-full-*`) |
| Two files together, fixed | 20 of 20 pass, 44 tests each (43 + the new regression test) (`fixed-pair-*`) |
| Full suite, fixed, batch 1 | 2 of 3 pass; run 3 failed on an unrelated test (below) (`fixed-full-*`) |
| Full suite, fixed, batch 2 | 3 of 3 pass, 1484 tests each (`fixed2-full-*`) |

So 5 of 6 fixed full-suite runs were green and the sixth failed only on the unrelated test below. Neither of the two
target tests failed in any post-fix run.

## Found, not fixed (out of the file list I may touch)

`tests/test_installer_staging_cleanup.py::test_a_signal_killed_zcode_export_leaves_no_staging_dir_behind` failed once in
`fixed-full-3.txt` (a leftover `.skill-concierge-staging.*` directory after the SIGTERM). A solo loop of that file failed
1 in 25 (`staging-25.txt`; that time the `omp` sibling of the same test shape). It is a third intermittent failure, in the
signal-kill installer tests (`_kill_during_export`, lines 300-320 of that file, and the installers' signal handling). It
is independent of my change, and I did not diagnose it further. No installer test refused to run for an uncommitted
version in my runs.

## Not checked

- Windows and Linux timing: the relay race is the same logic anywhere, but I ran macOS only.
- No version bump, CHANGELOG or doc change: the change is a test fix and a private-helper bug fix, no user-visible behavior.

## Unresolved questions

- The original assertion text of the `test_trigger_filter` failure (see inference above).
- Whether to take the installer staging flake as its own task.
