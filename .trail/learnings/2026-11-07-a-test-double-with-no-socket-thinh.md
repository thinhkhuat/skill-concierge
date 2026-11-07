---
title: "A test double with no socket starves every pool, not just one test"
author: Thinh
date: 2026-11-07
branch: main
id: l-edd5488c
scope: repo
status: active
src: agent
touches:
  - vendor/skill-search/tests/test_owner_jev_relay.py
  - vendor/skill-search/skill_search/index_owner.py
---

## Decided
When a test double stands in for a connection that gets pooled, give it a real socket. In `vendor/skill-search/tests/test_owner_jev_relay.py` the `FakeConn` carried `sock = None`, and `_jev_alive` in `vendor/skill-search/skill_search/index_owner.py` returns False when the socket is None, because that is how a closed connection presents. So every fake was judged dead the moment it was taken out of the pool, and each reuse built a fresh connection.

That single field made five assertions wrong at once: connection reuse, reconnect-on-stale, no-reconnect-on-timeout, and the end-to-end reuse case. Each looked like an independent behavioural bug in the relay. The source was correct the whole time.

## Tried and ruled out
- Fixing the assertions one at a time as they surfaced. Rejected once the pattern showed: four different tests failing on the same underlying dead-double, and each fix merely revealed the next.
- Concluding the tests were stale duplicates and reverting the whole file. Considered seriously and restored once to confirm the baseline, but rejected as the endpoint: the main suite covers adjacent behaviour, not these eight cases, so deleting the coverage would have been the lazy green.
- Changing `_jev_alive` to treat a missing socket as alive. Rejected: that inverts the real safety check for the sake of a test.

## Watch out
A double that is wrong in a way the code treats as a legitimate state will fail in several places and look like several bugs. When three or four unrelated assertions in one file break together, suspect the fixture before the fourth fix.

The tell was `sock = None` appearing in the double's constructor while the code under test branches on exactly that value.

Also worth knowing: the pool is now a dict per destination, and its entries are `(connection, idle_since)` tuples. Fixtures written against the earlier single queue will patch a name that no longer exists and error at setup, which is how this surfaced.

In the code:
- `FakeConn.__init__` opens a real empty `socket.socket(AF_INET, SOCK_STREAM)`, so it reads as alive and never readable
- `close()` closes that socket
- the double's response object carries `will_close = False`, which the relay consults before returning a connection to the pool
- fixtures patch `_JEV_POOLS` (a dict keyed by destination) and push `(conn, time.time())`
- result: 9 passed, and the vendored suite went from 305 passed / 9 errors to 314 passed / 0 errors
