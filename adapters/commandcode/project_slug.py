"""Print the name of Command Code's per-project dir (~/.commandcode/projects/<slug>) for a path.

Command Code slugs the session's physical cwd with @sindresorhus/slugify and its defaults
(Command Code 1.82: getProjectDirName, localMcpConfigPath). This ports that library's rules for
ASCII paths. A path it slugs differently (non-ASCII letters it transliterates) names a dir that does
not exist, and install.sh then skips the project-local override. Stdlib only; runs on Python 3.9.

usage: python3 project_slug.py <path>
"""
import os
import re
import sys


def slug(path):
    s = path.replace("&", " and ")
    s = re.sub(r"([A-Z]{2,})([0-9]+)", r"\1 \2", s)          # decamelize, the library's four steps
    s = re.sub(r"([a-z0-9]+)([A-Z]{2,})", r"\1 \2", s)
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", s)
    s = re.sub(r"([A-Z]+)([A-Z][a-rt-z0-9]+)", r"\1 \2", s)
    s = re.sub(r"([a-zA-Z0-9]+)'([ts])(\s|$)", r"\1\2\3", s.lower())   # contractions: root's -> roots
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


if __name__ == "__main__":
    print(slug(os.path.realpath(sys.argv[1])))
