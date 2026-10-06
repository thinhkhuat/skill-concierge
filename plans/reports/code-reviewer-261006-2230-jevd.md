# Code review: jevd (read-only)

Date: 2026-10-06 (Asia/Saigon). Repo: /Users/thinhkhuat/in-PROD/MY-WORKBENCH/jevd, branch main, HEAD 5d9935c.
Reviewer made no provider calls and no POST to the live service. Edits to the repo: none.

## Scope

- Files: src/jevd/{upstream,router,server,config,cli,__init__,__main__}.py, bin/jevd, tests/test_jevd.py,
  skill/jevd/SKILL.md, README.md (1419 lines total).
- Evidence gathered:
  - Offline suite: `/opt/homebrew/bin/python3 -m unittest discover -s tests -v` → `Ran 21 tests in 14.079s`, `OK`.
  - Live service: GET /health → `{"status": "ok", "version": "0.1.0", "providers": ["commandcode", "typesafe", "gateway"]}`; GET /status read.
  - `ls -l`: `~/.config/jevd/env` is `-rw-------`; config.toml, plist, calls.jsonl, serve.log are 644 (none hold keys).
  - Process: pid 71320, RSS 35328 KB, 0.0% CPU at 69 s uptime.
  - An offline scratch script (fake providers on 127.0.0.1, deleted afterwards) reproduced findings H1, H2, M1 and M3. Its output:
    ```
    1 ambiguous-drop: client calls=2, provider received 3 status 200 fell []
    2 text/plain + foreign Origin/Host: 200 provider calls 1
    3 slow connect: client status 502 [['a', 'Timeout']] -> provider still received 1 request(s) after the timeout
    4 pinned, budget 60s, provider needs 1s: 502 [['a', 'Timeout']]
    ```

## Overall assessment

The code is small, stdlib-only and mostly sound. Key handling in logs, headers and the call log is clean. The
caller-key rule holds. Loopback binding is enforced. Uninstall only removes links that resolve to jevd's own files.
Two real defects break stated invariants. First, the stale-connection resend can re-send a request the provider
already received (H1, reproduced). Second, "loopback-only, no client auth" does not stop a web page in the user's
browser from spending the keys (H2, server-side acceptance reproduced). The rest are billing waste, a budget feature
that cannot do what the docs say, failover gaps and doc drift.

## High

### H1. A request the provider may already have received is re-sent (double billing). Fact, reproduced.
- Location: `src/jevd/upstream.py:20-21` (STALE includes `RemoteDisconnected`, `BadStatusLine`, `ConnectionResetError`, `SSLEOFError`, `SSLZeroReturnError`), `upstream.py:107-116` (one try block covers both `conn.request` and `conn.getresponse`).
- Failure: a reused connection carries the full request. The provider reads it, starts the billed Jev call, and the connection then drops before the status line arrives (a backend restart, an LB or Cloudflare dropping mid-flight). `getresponse()` raises `RemoteDisconnected`, which is in STALE. `_exchange` therefore re-sends on a fresh connection, and the provider bills twice. The comment at `upstream.py:19` and the docstring at `:97-98` ("the request never reached the provider, so nothing was billed") are false for every error raised after the send. In the reproduction, 2 client calls produced 3 provider requests with `fell []`, so the double send was invisible.
- Fix: decide staleness *before* sending, and never re-send after the request bytes are out.
  1. Before reusing a pooled connection, discard it if its socket is readable (`select.select([conn.sock], [], [], 0)[0]`). That means the peer sent FIN or close_notify, the urllib3 `is_connection_dropped` approach. It catches the common idle-close case with zero risk.
  2. Allow the one re-send only for errors raised inside `conn.request(...)` (send phase: the body was not fully delivered). An error from `getresponse()`/`read()` goes to the caller as a failure, so the ladder moves on.
  3. Add a test: a fake provider that reads the request on a reused connection and then closes without answering. Assert `len(requests) == 2` for 2 calls.

### H2. Any web page open in the user's browser can make jevd spend the owner's keys. DNS rebinding can also read answers and /status. Server side: Fact, reproduced. Browser side: Inference.
- Location: `src/jevd/server.py:44-60` (no check of `Content-Type`, `Origin` or `Host`).
- Failure: a page sends `fetch("http://127.0.0.1:4377/v1/systemone", {method: "POST", mode: "no-cors", body: '{"state":"x","questions":{...}}'})`, or posts an `enctype=text/plain` form. That is a CORS "simple request", so no preflight runs. jevd parses the body whatever the Content-Type and forwards it to Command Code with the owner's key. The reproduction sent `Content-Type: text/plain` with `Origin: https://evil.example` and `Host: attacker.example:4377`; jevd answered 200 and called the provider. With DNS rebinding (an attacker hostname that resolves to 127.0.0.1), the page becomes same-origin and can read the answers and /status as well. Inference: how far current Chrome, Safari and Firefox block public-to-loopback requests varies by version; I did not check this live.
- Fix (keeps "no client auth"; about 6 lines in `do_POST`/`do_GET`):
  - Reject when an `Origin` header is present (native clients and curl do not send one).
  - Require `Content-Type: application/json` on POST, so browsers must preflight, and jevd never answers the preflight.
  - Require `Host` to be `127.0.0.1:<port>`, `localhost:<port>` or `[::1]:<port>`.

  Add tests for all three.

## Medium

### M1. A timed-out call can still be sent after the clock abandoned it (billed, answer discarded). Fact, reproduced.
- Location: `upstream.py:128-149` with `upstream.py:100-108`.
- Failure: the worker thread runs `pool.new(timeout)` and then `conn.request(...)`. Each socket operation gets the full `limit`, and `getaddrinfo` has no bound at all. On the lossy path jevd exists for, a slow connect or TLS handshake finishes after `t.join(limit)` has already raised CallTimeout. The worker then sends the request anyway: the provider bills it, and its answer is thrown away while the ladder bills the next rung. The same holds for the stale re-send branch (`:115`), which can open a fresh connection and send after the deadline.
- Fix: pass an absolute deadline (or a `threading.Event` set by `call()` on timeout) into `_exchange`. Immediately before each `conn.request`, if the deadline has passed or the event is set, close the connection or pool it, and return without sending. Add a test: patch `Pool.new` to sleep past the limit, then assert the fake provider received 0 requests.

### M2. jevd keeps calling providers after the client has gone. Clients are not told to send a budget.
- Location: `router.py:97-117` (no client-liveness check); SKILL.md lines 24-30 (no instruction to send `X-Jevd-Budget`).
- Failure: the default budget is 7.8 s. A caller with a shorter timeout, such as the skill-concierge router's 1.5 s per call and 3.0 s budget, hangs up while Command Code stalls. jevd still waits out 5.5 s and then bills TypeSafe for an answer nobody reads. The broken-pipe tracebacks already in `~/.local/state/jevd/serve.log` show clients disconnecting.
- Fix: in SKILL.md and README, tell every client to send `X-Jevd-Budget` equal to (or just under) its own timeout. Optionally, before each rung, check whether the client socket has hung up (`select` readable plus `recv(1, MSG_PEEK) == b""`), and stop with no further calls.

### M3. `X-Jevd-Budget` cannot lengthen any call, so the "up to 300 s" feature and the docs' advice do not work. Fact, reproduced.
- Location: `router.py:108` (`limit = min(p.timeout_s, left)`), `router.py:15` (`MAX_BUDGET_S = 300`); SKILL.md:29-30 ("offline batch work may raise it, up to 300 s"); SKILL.md:43 ("`Timeout` = slow provider (retry later or raise the budget)").
- Failure: each call is capped at its provider's `timeout_s`. A budget larger than the sum of the rungs' timeouts (5.5 + 1.5 + 2.0 = 9 s by default) changes nothing. A large batch request that needs 8 s on Command Code times out at 5.5 s on every attempt, whatever budget the caller sends. Reproduced: pinned, budget 60, provider needs 1 s, `timeout_s` 0.4 → `502 [['a', 'Timeout']]`.
- Fix (pick one): (a) let an explicit client budget raise the per-call limit when the request is pinned (`limit = left if pinned and client_budget else min(p.timeout_s, left)`); or (b) fix the docs: the budget only caps, and to allow longer calls you raise `timeout_s` in config.

### M4. A misconfigured or retired rung stops the ladder instead of failing over. Inference about provider status codes; UNVERIFIED.
- Location: `router.py:16` (`CLIENT_ERRORS = {400, 404, 413, 422}`), `router.py:113-114`.
- Failure: a provider whose `base_url` does not serve `/systemone`, or which no longer knows the configured `model` id, plausibly answers 404, 400 or 422. jevd returns that response as "the request itself is wrong" and never tries the next rung. A config or model-id problem on rung 1 takes down every ladder request. That breaks "the next provider runs only after an error". I did not check which status each provider returns for an unknown model; no provider calls were allowed.
- Fix: drop 404 from CLIENT_ERRORS. On the fixed `/systemone` path, a 404 means the provider route or model is missing, not a bad request. For 400 and 422, consider falling through when the error body names the model, or document the risk. Add a test where a 404 rung falls through.

### M5. Startup warming blocks the accept loop.
- Location: `server.py:89-95` with `router.py:64` (`self.warmer.step()` runs synchronously before `serve_forever` starts); `upstream.py:46` (`connect()` includes an unbounded `getaddrinfo`).
- Failure: at login or after a KeepAlive restart, on a flaky network, the synchronous step opens up to 3 TLS connections one after another, each bounded only per operation (up to `min(timeout_s, 10)`), with DNS unbounded. Meanwhile the socket is bound but not accepting. Clients queue in the backlog and short-timeout callers fail. `jevd install`'s 10 s health loop (`cli.py:250-257`) can report "service did not answer" on a slow network.
- Fix: start `serve_forever` first. Move the initial `step()` into `Warmer.run()` before the wait loop.

## Low

- **L1. Key precedence differs from the stated spec, and doctor checks the wrong environment.** `config.py:169-173` reads the process environment *before* jevd's key file. The owner's requirement is "jevd's own owner-only key file first". Under launchd, a stale `launchctl setenv CMD_API_KEY ...` would silently override the file. Separately, `cli.py:147-150` reports "key from environment" using the *CLI's* shell environment, not the service's, so doctor can say OK while the service logs `NoKey`. Fix: file first in `key_for` (or document the deviation), and have doctor read `"key"` from `/status`.
- **L2. A persistent start error becomes a crash loop.** `cli.py:229` sets `KeepAlive: true` and `ThrottleInterval 10`. An env file with loose permissions (`server.py:86-87`), a bad config, or a taken port makes `serve` exit 1 and respawn every 10 s forever: a Python start each time, plus a log line in an unrotated `serve.log`. This works against the "near-zero idle" goal. Fix: `KeepAlive: {"SuccessfulExit": false}` and exit 0 on config or permission errors (doctor reports them), or accept the loop and rotate `serve.log`.
- **L3. Client disconnects put tracebacks in serve.log, which is never rotated.** The default `handle_error` prints a full traceback for every `BrokenPipeError` (seen in the live log, on `/health`). Fix: catch `BrokenPipeError`/`ConnectionResetError` in `Handler._send`, or override `Server.handle_error`.
- **L4. Unexpected exception types escape `route()`.** `router.py:109-112` catches only `TimeoutError`, `OSError` and `HTTPException`. A `ValueError` from `http.client.putheader` (a key containing CR/LF, possible from a process-env key in `jevd ask --direct`) gets past it. `putheader` puts the whole header value in the message: `raise ValueError('Invalid header value %r' % (values[i],))`. So the full `Bearer <key>` lands on stderr (the agent's transcript) or in serve.log, and the client gets no response and no call-log row. Fix: catch `Exception` per rung and record only `type(e).__name__`; reject keys containing whitespace or control characters when they load.
- **L5. The env-file write is not atomic.** `cli.py:190-195` opens with `O_TRUNC` and writes in place. A crash in between destroys keys that exist only in the file. A pre-existing 644 file also holds the new keys at 644 until the `chmod`. Fix: write a 0600 temp file in the same directory, then `os.replace`.
- **L6. The server handler has no socket timeout and leaves bodies unread.** `server.py:16-60`: `Handler.timeout` is None, so every idle keep-alive client connection pins a thread forever. The early returns at `:45-46` (404) and `:49-50` (oversize) leave the body unread on a kept-alive HTTP/1.1 connection, and the next "request" is parsed from body bytes. Fix: `timeout = 60` on Handler; `self.close_connection = True` on every early-error return.
- **L7. Config accepts `::1` but the server cannot bind it.** `config.py:103-109` accepts it, while `ThreadingHTTPServer.address_family` is `AF_INET` (value `2`, checked), so `host = "::1"` crash-loops under launchd. Fix: refuse non-IPv4 hosts or set `address_family` from the host.
- **L8. A `NaN` budget is accepted.** `server.py:55` and `router.py:89`: `X-Jevd-Budget: nan` passes `float()`, disables the whole-request cap (the per-call limits still apply), and writes a non-standard `NaN` into calls.jsonl. Fix: `if not math.isfinite(b): 400`.
- **L9. Dead code.** `upstream.py:67-70` `newest_idle_age` (never called) and `Pool.size` (`upstream.py:33`, stored, never read). `tests/test_jevd.py:82` pops `JEVD_TEST_KEY_A/B`, which no test uses (phantom setup).
- **L10. The idle wakeup rate is higher than needed.** `server.py:94` `serve_forever()` uses the default `poll_interval=0.5`, which wakes the process twice a second, besides the warmer's 30 s tick. Measured idle CPU is small (README claims 0.01 s/60 s; I did not re-measure it). `serve_forever(poll_interval=5)` cuts the wakeups tenfold at the cost of up to 5 s shutdown latency.
- **L11. The harness skill roots are hard-coded** (`cli.py:23-26`, 11 paths). The owner's cross-harness rule asks for paths read through env or config seams. A `[install] skill_roots` config key, or an env override, would satisfy it. This is judgment, not a defect.

## Docs vs code

- README.md:37 says the skill is linked into `~/.claude/skills`, `~/.codex/skills` and `~/.agents/skills`. The code links into 11 roots (`cli.py:23-26`), and all 11 links exist on this machine.
- README.md:111 says "about 25 MB resident after start-up". The live process showed 35328 KB RSS at 69 s uptime after 8 requests. That is not a contradiction (start-up versus after use), but the doc understates it.
- SKILL.md:43 explains `NoTime` as "budget too small for that provider's `timeout_s`". The code skips a rung only when less than `min(timeout_s, 1.0)` s remain (`router.py:104`), so a 5.5 s rung still starts with 1.1 s left. The same row's "raise the budget" advice does not work (M3).
- With the default budget of 7.8 s, the third rung (gateway) never runs after a Command Code timeout: 7.8 − 5.5 − 1.5 = 0.8 s < 1.0 s → `NoTime`. It runs only when earlier rungs fail fast. The README presents it as the third rung without this caveat.
- README.md:87-88 and SKILL.md:60-61 present OpenRouter and OpenCode Zen as serving `<base_url>/systemone`. UNVERIFIED: I made no network calls. If those endpoints do not exist, M4 makes the ladder stop at them.
- SKILL.md:21 ("Give it any non-empty key if it insists on one; jevd uses its own") is true only when jevd has a key for that provider. If jevd has none and the request is pinned, the dummy key is forwarded upstream (by design: the caller-key fallback).
- `jevd install` overwrites a hand-edited env-file key with the shell's value whenever the two differ (`cli.py:184-187`). SKILL.md:54-55 tells agents to run `install` after editing the key file, which can silently revert the edit. Document this, or only add keys missing from the file.

## Tests: would they catch broken logic?

They do catch: removal of the stale re-send, the ladder order, the 400 stop, the clock cut, the budget cap, the caller key being forwarded to an unpinned rung, connection reuse, and warmer warm/cold behaviour.

They do not catch:
- a re-send after the provider received the request (H1; it is live today);
- a send after the clock gave up (M1);
- `len(requests) == 1` after a timeout (no slow-path test counts requests, so adding `TimeoutError` to STALE would pass);
- a late worker returning a clean connection to the pool, or closing a dirty one;
- the `X-Jevd-Budget` and `X-Jevd-Provider` headers through HTTP;
- non-JSON Content-Type, Origin or Host (H2);
- CallLog rotation;
- install, uninstall and link ownership, the launcher, doctor.

The highest-risk filesystem code (`cmd_install`/`cmd_uninstall`) has zero coverage. The suite takes 14 s, mostly `ThreadingHTTPServer.shutdown` 0.5 s polls and the deliberate stalls. It makes no network calls beyond 127.0.0.1 and reads no real keys (`Router(env_file=...)` is injected).

## Checked and clean

- Keys never appear in the call log (`router.py:123-124`), in `X-Jevd-*` headers, in 502 bodies (exception type names only, `router.py:112`) or in /status (a boolean only).
- A caller's key goes only to the single pinned provider, and only when jevd has no key for it (`router.py:99-100`; tested).
- Server bind: a non-loopback host is refused at load (`config.py:144-145`). Plain http is allowed only to a loopback provider (`config.py:120`).
- The env file is created 0600, and the service refuses to start if it is group- or world-readable.
- Uninstall (`cli.py:260-268`) removes a link only when it resolves to `bin/jevd` or `skill/jevd`, or when it is the label's own plist path. It never follows a link into a target, and `_link` leaves foreign files alone. One gap, low: after the repo moves, the old dangling links are left behind (they resolve to the old path).
- Launcher (`bin/jevd`): it follows relative symlinks, honours `JEVD_PYTHON` (an absolute Homebrew path in the plist), falls back to `/opt/homebrew/bin/python3`, and rejects the 3.9 system python through the version probe. `-P` blocks cwd import hijacking. It works under launchd's minimal PATH.
- Pool and Warmer concurrency: LIFO queue operations are thread-safe. A drain in `drop_older_than` can make a concurrent `get()` open one extra connection (harmless). `opened +=` is racy, but it is only a counter.
- No over-engineering of note beyond L9 and L11. The code is proportionate to the requirements.

## Recommended actions (priority order)

1. H1: pre-send liveness check plus re-send only on send-phase errors, with a test.
2. H2: Origin, Host and Content-Type checks, with tests.
3. M1: a deadline/abandon check before `conn.request`, with a test.
4. M3 + M2: decide what the budget means; fix SKILL.md (clients send their own timeout as `X-Jevd-Budget`).
5. M4: 404 falls through.
6. M5: move the first warm step into the warmer thread.
7. L1-L8 as convenient; fix the doc drift listed above.

## Metrics

- Type coverage: n/a (no type checker in the repo; annotations are partial).
- Tests: 21/21 pass offline. Line coverage was not measured (no coverage tool run).
- Lint: none configured; none run.

## Not checked

- Real provider behaviour: status codes for an unknown model, whether OpenRouter and OpenCode Zen serve `/systemone`, keep-alive idle limits. No network calls were allowed.
- Current browser policy on public-to-loopback requests (H2's browser side).
- Idle CPU over time (README's 0.01 s/60 s figure was not re-measured).
- The contents of `~/.config/jevd/env`, by instruction.

## Unresolved questions

1. H2 conflicts with nothing in the owner's "no client auth" requirement, since header checks are not auth. Confirm that rejecting browser-shaped requests is acceptable (no browser client is expected).
2. M3: should a pinned request's explicit budget lengthen the call (code change), or should the docs say the budget only caps (doc change)?
3. L1: is env-before-file precedence intended (for foreground runs), or should the file win, as the requirement states?

Status: DONE_WITH_CONCERNS
Summary: Two high-severity defects, both reproduced offline. The stale-connection logic re-sends requests the provider already received (double billing), and the loopback service accepts browser-shaped cross-origin requests that spend the owner's keys. Five medium issues (late sends after timeout, budget semantics, failover on 404, startup blocking, client-gone billing) and doc drift. 21/21 offline tests pass but cover none of these paths.
