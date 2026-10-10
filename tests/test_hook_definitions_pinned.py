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
PINNED = "617d5230db2807997f924ed49a6b48e2a717383f50b9fa534c41e9a1a1d093af"


def test_hook_definitions_change_only_with_a_codex_re_trust_note():
    hooks = json.loads((ROOT / "hooks" / "hooks.json").read_text())["hooks"]
    # The whole hooks block: a moved group changes Codex's trust key (event:group:index) and any new
    # field (async, statusMessage) changes the definition, so nothing is left out of the digest.
    digest = hashlib.sha256(json.dumps(hooks, sort_keys=True).encode()).hexdigest()
    assert digest == PINNED, (
        "hooks/hooks.json hook definitions changed. Codex will skip every changed hook until the user "
        "trusts it again. Add a CHANGELOG line saying so, then set PINNED to " + digest)
