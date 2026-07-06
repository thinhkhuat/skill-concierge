#!/usr/bin/env python3
"""Resolve durable skill-concierge state paths — the SINGLE canonical home for anything that
must survive a /plugin update.

A plugin installs to a version-pinned cache dir (~/.claude/plugins/cache/<mp>/<plugin>/<version>/)
that `/plugin update` replaces wholesale — anything written inside the plugin is lost on the next
update (CLAUDE_PLUGIN_ROOT points at that ephemeral dir). So all durable state — config, the
allowlist, locks/stamps, the ledger — lives under ONE stable home the user owns:

    ~/.claude/skill-concierge/          (override with SKILL_CONCIERGE_HOME)

The keep-on allowlist is SEEDED there once from the plugin's shipped default (config/keep-on.json);
thereafter the user owns it and an update never clobbers their edits.

Env seams:
  SKILL_CONCIERGE_HOME    the canonical durable home (default ~/.claude/skill-concierge)
  SKILL_CONCIERGE_KEEPON  exact allowlist file — wins, never seeded (tests / advanced override)
"""
import os
import shutil
from pathlib import Path

HOME = Path(os.environ.get("SKILL_CONCIERGE_HOME", Path.home() / ".claude" / "skill-concierge"))


def keepon_path(plugin_root) -> Path:
    """Stable allowlist path, seeded from the shipped default on first use. An explicit
    SKILL_CONCIERGE_KEEPON override wins and is never seeded (the caller owns it)."""
    override = os.environ.get("SKILL_CONCIERGE_KEEPON")
    if override:
        return Path(override)
    stable = HOME / "keep-on.json"
    if not stable.exists():
        seed = Path(plugin_root) / "config" / "keep-on.json"
        if seed.exists():
            stable.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(seed, stable)          # seed once; never overwrite an existing edit
    return stable


def _selftest():
    import json
    import tempfile
    global HOME
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        os.environ["SKILL_CONCIERGE_KEEPON"] = str(td / "x.json")
        assert keepon_path(td) == td / "x.json"          # explicit override wins, no seeding
        del os.environ["SKILL_CONCIERGE_KEEPON"]
        HOME = td / "home"                                # seed-if-missing from shipped default
        (td / "config").mkdir()
        (td / "config" / "keep-on.json").write_text('{"keep_on": ["a"]}', encoding="utf-8")
        p = keepon_path(td)
        assert p == td / "home" / "keep-on.json" and p.exists(), p
        assert json.loads(p.read_text())["keep_on"] == ["a"], "must seed from the default"
        p.write_text('{"keep_on": ["a", "b"]}', encoding="utf-8")
        keepon_path(td)                                   # second call must NOT re-seed
        assert json.loads(p.read_text())["keep_on"] == ["a", "b"], "re-seeded over a user edit"
    print("selftest ok")


if __name__ == "__main__":
    _selftest()
