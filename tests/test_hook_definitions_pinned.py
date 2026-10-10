"""Codex runs a plugin hook only while its definition matches the hash the user trusted
(~/.codex/config.toml [hooks.state]). Changing a hook's command, matcher or timeout makes Codex skip
it silently until the user trusts it again: 0.59.0 raised the enforcer timeout from 5 to 10 s and
Codex stopped running the enforcer, with doctor still green. This test makes every such change a
deliberate one."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Update only together with a CHANGELOG line telling Codex users to open Codex and trust the
# changed skill-concierge hooks again.
PINNED = "d09a751eacf2348257978b908db60e059bf1772abf3c3ed3356623ec143272ed"


def test_hook_definitions_change_only_with_a_codex_re_trust_note():
    hooks = json.loads((ROOT / "hooks" / "hooks.json").read_text())["hooks"]
    canon = [(ev, g.get("matcher", ""), h.get("type"), h.get("command"), h.get("timeout"))
             for ev, groups in sorted(hooks.items()) for g in groups for h in g.get("hooks", [])]
    digest = hashlib.sha256(json.dumps(canon).encode()).hexdigest()
    assert digest == PINNED, (
        "hooks/hooks.json hook definitions changed. Codex will skip every changed hook until the user "
        "trusts it again. Add a CHANGELOG line saying so, then set PINNED to " + digest)
