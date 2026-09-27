"""skill_search.ports — the ONE port-parsing grammar and the ONE place that reads
SKILL_QDRANT_URL, EMBED_SHIM_PORT, SKILL_OWNER_QUERY_PORT and SKILL_OWNER_EMBED_PORT from
an environment mapping.

THE GRAMMAR (deliberately narrower than `int()`): ASCII digits only ('0'-'9'), the WHOLE
string (`re.fullmatch`, not `match` + `$` — `$` also matches just before a final newline, so
a trailing "\n" would otherwise slip through), no leading/trailing whitespace, no sign, no
underscore digit-group separator, no full-width or other non-ASCII decimal digit, 1-5
characters (rejects "0065535" and "000007363" — Python's bare `int()` would accept both as
in-range integers), and the parsed integer must land in 1-65535. `int()` alone also strips
whitespace, accepts a leading sign, and normalizes any Unicode decimal digit, so a caller
built on a bare `int(raw)` would derive a DIFFERENT port than one built on this grammar (or
on bash's own `_safe_port`, which this module's rule mirrors: ASCII digits only, length
checked before the range check, converted in base 10 — `setup.sh` and `bin/skill-search-mcp`
implement that same rule natively in bash, since they run before this venv's `skill_search`
is importable).

This module is part of the vendored engine (`vendor/skill-search/skill_search/`) — it MUST
stay import-free of the rest of this repo to remain portable on its own. `index_owner.py` and
`server.py`, in the same package, import it directly (`from skill_search import ports`).
Every OTHER caller in this repo (doctor.py, the enforcer hook, and any script that derives a
port from one of the four env vars above) puts `vendor/skill-search` on `sys.path` first, then
does the same import — see AGENTS.md's "Runtime flags" / the port-agreement test suite for the
full caller list. `tests/test_port_env_guard.py` statically enforces that no OTHER file reads
one of those four names from an environment mapping — every reader goes through a function
here instead, so the grammar can never fork into a second copy again.
"""
from __future__ import annotations

import os
import re
from urllib.parse import urlsplit

__all__ = [
    "parse_port", "url_port", "safe_url",
    "embed_port", "query_port", "qdrant_url",
    "resolved_qdrant_url", "resolved_query_port", "resolved_embed_port",
]

# 1-5 ASCII digits, the whole string (fullmatch — no `$`-before-newline loophole).
_STRICT_PORT_RE = re.compile(r"[0-9]{1,5}")


def parse_port(raw, default):
    """`raw` must be 1-5 ASCII digit characters naming an integer in 1-65535; anything else
    (including `None`, `""`, or a value this grammar rejects) returns `default` unchanged.
    Never raises."""
    if raw is None or not _STRICT_PORT_RE.fullmatch(raw):
        return default
    port = int(raw)
    return port if 1 <= port <= 65535 else default


def _split_netloc(netloc):
    """(host, bracketed, raw_port) from a bare "host[:port]" or "[v6host][:port]" netloc —
    no userinfo support, since no URL this repo derives a port from ever carries one.
    `raw_port` is the UNPARSED port text (or `None` if the netloc names none); `bracketed`
    is True iff the host was written inside `[...]` (an IPv6 literal). Never raises."""
    if netloc.startswith("["):
        end = netloc.find("]")
        if end == -1:
            return netloc[1:], False, None
        host, rest = netloc[1:end], netloc[end + 1:]
        bracketed = True
    else:
        colon = netloc.find(":")
        if colon == -1:
            return netloc, False, None
        host, rest = netloc[:colon], netloc[colon:]
        bracketed = False
    raw_port = rest[1:] if rest.startswith(":") else None
    return host, bracketed, raw_port


def url_port(url, default):
    """The STRICT port named by `url`'s netloc (same grammar as `parse_port`). When `url`
    names no port, or one this grammar rejects, the fallback is the SAME one `safe_url`
    substitutes: 443 for an `https` URL, else `default` — so the port a caller derives and
    the URL another caller rebuilds can never disagree. It reads the netloc text itself
    rather than `urlsplit(...).port`, so the URL path and the scalar env-var path answer to
    one grammar. Never raises."""
    try:
        parsed = urlsplit(url or "")
    except ValueError:
        return default
    fallback = 443 if parsed.scheme == "https" else default
    _host, _bracketed, raw_port = _split_netloc(parsed.netloc)
    if raw_port is None:
        return fallback
    return parse_port(raw_port, fallback)


def safe_url(url, default_port, default_host="localhost", default_scheme="http"):
    """Returns `url` unchanged if it already names a port this grammar accepts; otherwise
    returns the SAME scheme and host (falling back to `default_scheme`/`default_host` only
    when `url` names none) with a fallback port substituted: `default_port` for `http` (or
    any scheme other than `https`), or the universal `443` for `https` — a remote store over
    TLS is never this plugin's own owner, which never serves TLS, so an `https` URL with no
    usable port keeps its OWN well-known default rather than borrowing the owner's.
    IPv6 hosts keep their brackets on rebuild. Never raises."""
    try:
        parsed = urlsplit(url or "")
    except ValueError:
        parsed = urlsplit("")
    scheme = parsed.scheme or default_scheme
    host, bracketed, raw_port = _split_netloc(parsed.netloc)
    port = parse_port(raw_port, None) if raw_port is not None else None
    if port is not None:
        return url
    host = host or default_host
    if ":" in host:            # an IPv6 literal that lost its brackets somewhere upstream
        bracketed = True
    fallback_port = 443 if scheme == "https" else default_port
    if bracketed:
        return f"{scheme}://[{host}]:{fallback_port}"
    return f"{scheme}://{host}:{fallback_port}"


# ---------------------------------------------------------------------------
# Env-owning wrappers. These are the ONLY functions in the repo that read
# SKILL_QDRANT_URL / EMBED_SHIM_PORT / SKILL_OWNER_QUERY_PORT / SKILL_OWNER_EMBED_PORT
# from an environment mapping — every caller passes/derives no such literal itself; it
# calls one of these instead (`tests/test_port_env_guard.py` enforces this statically).
# `env` defaults to `os.environ`; pass an already-merged dict (e.g. doctor.py's .mcp.json
# + process-env overlay) when a caller needs a different source.
# ---------------------------------------------------------------------------

def embed_port(env=None, default=6363):
    """SKILL_OWNER_EMBED_PORT, else EMBED_SHIM_PORT, else `default` — the embed port every
    caller (the owner, doctor, the enforcer, the MCP launcher, setup.sh) derives."""
    env = os.environ if env is None else env
    raw = env.get("SKILL_OWNER_EMBED_PORT") or env.get("EMBED_SHIM_PORT")
    return parse_port(raw, default) if raw else default


def query_port(env=None, default=6333):
    """SKILL_OWNER_QUERY_PORT, else SKILL_QDRANT_URL's port, else `default` — the store
    port every caller derives."""
    env = os.environ if env is None else env
    override = env.get("SKILL_OWNER_QUERY_PORT")
    if override:
        return parse_port(override, default)
    return url_port(env.get("SKILL_QDRANT_URL"), default)


def qdrant_url(env=None, default_port=6333, default_host="localhost", default_scheme="http"):
    """SKILL_QDRANT_URL, normalized through `safe_url` against `default_port`."""
    env = os.environ if env is None else env
    return safe_url(env.get("SKILL_QDRANT_URL") or "", default_port, default_host, default_scheme)


def resolved_qdrant_url(env=None, default_port=6333, default_host="localhost", default_scheme="http"):
    """(url, notice) — `notice` is `None` unless the configured SKILL_QDRANT_URL needed a
    fallback, in which case it names the bad raw value and the url substituted, for a
    caller to print (with its own "skill-concierge <component>: " prefix)."""
    env = os.environ if env is None else env
    raw = env.get("SKILL_QDRANT_URL")
    url = safe_url(raw or "", default_port, default_host, default_scheme)
    if raw and url != raw:
        return url, f"SKILL_QDRANT_URL={raw!r} has no usable port; using {url!r}"
    return url, None


def resolved_query_port(env=None, default=6333):
    """(port, notice) — the same derivation as `query_port`, plus a notice naming which env
    var held the bad value, for a caller that wants to log the fallback (the index owner)."""
    env = os.environ if env is None else env
    override = env.get("SKILL_OWNER_QUERY_PORT")
    if override:
        port = parse_port(override, None)
        if port is not None:
            return port, None
        return default, (f"SKILL_OWNER_QUERY_PORT={override!r} is not a valid port "
                          f"(1-65535, ASCII digits only); using {default}")
    raw_url = env.get("SKILL_QDRANT_URL")
    if raw_url:
        port = url_port(raw_url, None)
        if port is not None:
            return port, None
        return default, f"SKILL_QDRANT_URL={raw_url!r} has no usable port; using {default}"
    return default, None


def resolved_embed_port(env=None, default=6363):
    """(port, notice) — the same derivation as `embed_port`, plus a notice naming which env
    var held the bad value."""
    env = os.environ if env is None else env
    override, src = env.get("SKILL_OWNER_EMBED_PORT"), "SKILL_OWNER_EMBED_PORT"
    if not override:
        override, src = env.get("EMBED_SHIM_PORT"), "EMBED_SHIM_PORT"
    if not override:
        return default, None
    port = parse_port(override, None)
    if port is not None:
        return port, None
    return default, f"{src}={override!r} is not a valid port (1-65535, ASCII digits only); using {default}"
