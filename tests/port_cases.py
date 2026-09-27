"""The ONE case table for the port-derivation agreement tests (tests/test_port_agreement.py,
tests/test_ports.py) and the shared bash `_safe_port` probe. Every caller in the repo —
Python or bash — must land on the SAME answer for every one of these inputs; a caller that
doesn't derives a different port from the same setting than the others.

SCALAR_CASES: (raw, valid) pairs for a scalar port override (EMBED_SHIM_PORT,
SKILL_OWNER_QUERY_PORT, SKILL_OWNER_EMBED_PORT). `valid` is the parsed int the value must
produce, or `None` if every caller must fall back to its own default instead.

URL_CASES: (url, default_port, expected_url) triples for `skill_search.ports.safe_url` —
`expected_url` is the exact string every URL-deriving caller must produce from `url` when
substituting `default_port` on a missing/invalid port (6333 for the store, from every caller
that binds/queries the owner's Qdrant-compatible port).
"""

# A bare Python `int()` accepts leading/trailing whitespace, a leading sign, an underscore
# digit-group separator, and full-width Unicode decimal digits; a `re.match(...$)` (rather
# than `fullmatch`) also accepts a trailing "\n"; a bash `-le 65535` comparison with no
# length check also accepts "0065535"/"000007363" (7/9 digits, still numerically in range).
# Every one of these must be REJECTED (fall back to the caller's own default) by every
# caller, Python and bash alike.
SCALAR_CASES = (
    ("7363", 7363),
    ("07363", 7363),          # leading zero, still 5 chars — valid (matches int("07363"))
    ("65535", 65535),
    ("1", 1),
    ("0", None),              # in-range for a bare int(), but not a valid TCP port
    ("70000", None),          # out of range
    ("-5", None),             # a sign is not a digit
    ("notaport", None),
    ("", None),
    ("7363\n", None),         # `$` (not `fullmatch`) matches just before a trailing newline
    ("0065535", None),        # 7 digits — numerically 65535, but over the 5-char length cap
    ("000007363", None),      # 9 digits — same class
    (" 7363", None),          # bare int() strips whitespace
    ("7363 ", None),
    ("+7363", None),          # bare int() accepts a leading sign
    ("7_363", None),          # bare int() accepts an underscore digit-group separator
    ("７３６３", None),        # bare int() normalizes full-width Unicode digits
)

# default_port=6333 throughout — every URL-deriving caller in the repo binds/queries the
# owner's store port, whose well-known default is 6333.
URL_CASES = (
    ("http://127.0.0.1:7333", 6333, "http://127.0.0.1:7333"),      # valid — unchanged
    ("http://127.0.0.1:notaport", 6333, "http://127.0.0.1:6333"),
    ("http://127.0.0.1:70000", 6333, "http://127.0.0.1:6333"),
    ("http://127.0.0.1:-5", 6333, "http://127.0.0.1:6333"),
    ("http://127.0.0.1:", 6333, "http://127.0.0.1:6333"),
    ("http://127.0.0.1:0065535", 6333, "http://127.0.0.1:6333"),   # same length-cap rule
    # IPv6: a naive rebuild from `.hostname` drops the brackets ("http://::1:6333"),
    # which then fails to parse at all downstream.
    ("http://[::1]", 6333, "http://[::1]:6333"),
    ("http://[::1]:", 6333, "http://[::1]:6333"),
    ("http://[::1]:7333", 6333, "http://[::1]:7333"),               # valid — unchanged
    ("http://[::1]:notaport", 6333, "http://[::1]:6333"),
    # scheme-dependent no-port default: https keeps its OWN well-known 443 rather than
    # borrowing the http-side owner's default; a remote https store is never this plugin's
    # own owner, which never serves TLS.
    ("https://host", 6333, "https://host:443"),
    ("http://host", 6333, "http://host:6333"),
    ("https://host:8443", 6333, "https://host:8443"),                # valid https — unchanged
    ("", 6333, "http://localhost:6333"),                             # unset entirely
)
