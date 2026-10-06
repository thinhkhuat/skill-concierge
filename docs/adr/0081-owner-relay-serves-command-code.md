# ADR-0081: the index owner's warm relay serves Command Code as well as TypeSafe

- **Status:** Accepted (2026-10-06, owner's order). Applies only when jevd is absent: ADR-0080 takes precedence
  when jevd answers `/ladder`.
- **Extends:** ADR-0061 and ADR-0070 (the owner's `POST /jev` relay), ADR-0079 (the `cc` tier).

## Context

The owner's order, verbatim: "have the concierge's current relay made for TypeSafe to include Command Code there
too, so users using concierge without jevd could benefit and enjoy the same mechanism with either provider". The
approved brief option was "Proceed as restated (Recommended)".

Until now only the TypeSafe tier used the index owner's relay (warm pooled connections). A `cc` tier (ADR-0079)
opened a fresh TLS connection every call. Facts measured 2026-10-06 (owner's brief): a connection that did only
TCP + TLS to Command Code was dropped within 15 s; after one keyless GET it was kept 180 s or more.

## Decision

1. **A fixed destination table, one path each.** `JEV_DESTS` in `vendor/skill-search/skill_search/index_owner.py:667`
   maps `ts` to `api.typesafe.ai` `/v1/systemone` and `cc` to `api.commandcode.ai` `/provider/v1/systemone`.
   `POST /jev` is TypeSafe, unchanged, so older hooks keep working. `POST /jev/cc` is Command Code
   (`index_owner.py:924`). The owner takes no URL from a request and holds no key; the caller's `Authorization` is
   forwarded and never stored.
2. **A path, not a header, picks the destination.** An owner that predates this ADR answers 404 on `/jev/cc`, and
   the hook then calls Command Code directly. So a Command Code key can never reach TypeSafe through an old owner.
3. **Per-destination pools, with a liveness check.** `_JEV_POOLS` holds one pool per destination. `_jev_alive`
   (`index_owner.py:691`) checks that a pooled connection is still open before it is reused; a connection idle
   longer than `JEV_KEEP_WARM_S` (180 s) is replaced.
4. **A request is re-sent only when writing it failed.** `_JEV_SEND_STALE` (`index_owner.py:683`) lists the errors
   that can only come from writing onto a connection the provider had closed. Only those, raised while sending on a
   pooled connection, re-send once on a new connection. An error after the whole request was written is never
   re-sent, because the provider may have run and billed it. The old relay re-sent then. Control run (owner's
   brief): old relay = 3 provider POSTs for 2 calls, new = 2.
5. **User-Agent `skill-concierge`** (`index_owner.py:670`), because Command Code's Cloudflare front refuses Python's
   default (error 1010).
6. **Keep-warm.** `_jev_warm_loop` (`index_owner.py:802`) ticks every 30 s. For each destination used in the last
   30 minutes (`JEV_WARM_FOR_S`) with no live pooled connection, it opens one and sends a GET with no key. The
   provider refuses it (401) and bills nothing, and keeps the connection. A destination never used is never
   contacted.
7. **The hook.** `JEV_CC_RELAY_URL` (`hooks/scripts/enforcer.py:1521`) is the owner's `/jev/cc`, set only when the
   owner address is loopback and `ENFORCER_JEV_CC_URL`'s host is `api.commandcode.ai`. `_jev_call` picks the relay
   per tier (`enforcer.py:2105`): TypeSafe tier to `/jev`, `cc` tier to `/jev/cc`. A 404 or a refused connection
   makes one direct call. A relay-reported upstream timeout is recorded as a timeout and not re-sent direct.
8. **Offline work never uses the relays.** `scripts/jev_client.py:65` sets both relay URLs to `None`.

Tests: `tests/test_owner_jev_relay.py` (9 tests).

## Consequences

- A user with the plugin and no jevd gets a warm connection to Command Code, as TypeSafe already had.
- The keep-warm costs one keyless GET whenever an active destination has no live pooled connection, which is at most
  about every 180 s. It sends no key and bills nothing (Command Code answers 401; owner's measurement).
- The relay no longer re-sends a request that may have been billed. This also changes TypeSafe's behaviour: fewer
  duplicate POSTs after a mid-flight reset.
- **Judgment call (labeled):** a fixed table of two destinations, not a general proxy. A third provider means a new
  entry and a new ADR, which keeps the owner from becoming an open relay.
- With jevd present none of this runs; jevd holds its own pools (ADR-0080).

## Revert

Remove the `cc` entry from `JEV_DESTS` (and the `/jev/cc` route follows it), or set the hook's relay off by pointing
`ENFORCER_JEV_CC_URL` away from `api.commandcode.ai`. The old-hook path is unaffected either way: `POST /jev` is
unchanged.
