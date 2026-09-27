"""scripts/port_grammar.py — the ONE port-parsing grammar every Python caller that derives
a TCP port from SKILL_QDRANT_URL, EMBED_SHIM_PORT, or their SKILL_OWNER_* overrides uses.

THE GRAMMAR (deliberately narrower than `int()`): ASCII digits only ('0'-'9'), no leading or
trailing whitespace, no sign, no underscore digit-group separator, no full-width or other
non-ASCII decimal digit — and the parsed integer must be 1-65535. Python's `int()` alone
accepts " 7363", "7363 ", "+7363", "7_363" and full-width "７３６３" (it explicitly strips
whitespace, accepts a leading sign, and — since PEP 515 covers only *source* literals but
CPython's runtime int() conversion independently normalizes any Unicode decimal digit —
also normalizes those digit forms). A caller that used a bare `int(raw)` therefore accepted
a value another caller (bash's `_safe_port`, or `urlsplit().port`, which is already this
strict for a URL's port component) would reject, so the two callers derived DIFFERENT ports
from the SAME env var and could never agree.

vendor/skill-search/skill_search/index_owner.py is vendored (it must stay import-free of
this repo's own code to remain portable on its own), so it MIRRORS this exact grammar
inline instead of importing it — see vendor/skill-search/VENDORED.md. Every OTHER caller
(doctor.py, the enforcer hook, and any script that parses one of these three env vars)
imports this module instead of re-implementing the grammar.
"""
import re
from urllib.parse import urlsplit

_STRICT_PORT_RE = re.compile(r"^[0-9]{1,5}$")


def parse_port(raw, default):
    """`raw` must be 1-5 ASCII digit characters ('0'-'9' only — no sign, no whitespace, no
    '_', no full-width digits) naming an integer in 1-65535; anything else, including
    `None` or an empty string, returns `default` unchanged. Never raises."""
    if raw is None or not _STRICT_PORT_RE.match(raw):
        return default
    port = int(raw)
    return port if 1 <= port <= 65535 else default


def safe_url(url, default_port, default_host="localhost", default_scheme="http"):
    """Returns `url` unchanged if `urlsplit` can read a port from it in 1-65535; otherwise
    returns the SAME scheme and host (falling back to `default_scheme`/`default_host` only
    when `url` names none) with `default_port` substituted for the port. This exists
    because a URL with an unparseable port (`urlsplit` raises `ValueError`, matching this
    module's own grammar for the port component) OR with no port at all (`.port` is `None`)
    both need the SAME well-known default — passing a `None`-port URL straight to
    `http.client`/`urllib` silently connects on port 80 (the browser default), not this
    plugin's well-known port. Never raises."""
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        parsed = urlsplit("")
        port = None
    if port is not None and 1 <= port <= 65535:
        return url
    scheme = parsed.scheme or default_scheme
    host = parsed.hostname or default_host
    return f"{scheme}://{host}:{default_port}"
