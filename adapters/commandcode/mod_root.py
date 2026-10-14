"""The installed Command Code mod's root line, shared by install.sh and scripts/doctor.py.

install.sh copies skill-concierge.mod.ts to ~/.commandcode/mods/, where the copy's own location
says nothing about the checkout. So the copy carries the checkout path in one line,
`const INSTALLED_ROOT = "<root>";`, which the repo file holds empty. Both the installer (to write
and verify the copy) and doctor (to judge a copy as current and its root as reachable) go through
this module, so they cannot disagree about what a correct copy is. Stdlib only; runs on Python 3.9.
"""
import json
import re

PLACEHOLDER = 'const INSTALLED_ROOT = "";'
_ROOT_LINE = re.compile(r'^const INSTALLED_ROOT = (".*");$', re.MULTILINE)


def render(source, root):
    """The mod as installed from `root`: the placeholder line carries `root` as a JS string.

    Raises ValueError unless the source holds the empty placeholder exactly once, so a reworded
    line fails the install instead of shipping a copy that cannot find its root."""
    count = source.count(PLACEHOLDER)
    if count != 1:
        raise ValueError(f"mod source must hold {PLACEHOLDER!r} exactly once, found {count}")
    # JSON string syntax is valid JS string syntax: quotes, backslashes and non-ASCII stay exact.
    return source.replace(PLACEHOLDER, f"const INSTALLED_ROOT = {json.dumps(str(root))};")


def baked_root(text):
    """The root an installed copy carries; "" for the unrendered repo file; None without the line."""
    m = _ROOT_LINE.search(text)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except ValueError:
        return None
