"""The getaway leg runs end to end through main(): no semantic fit -> an authorized skip.

v0.65.0's removal of the per-skill floor left this leg reading a deleted name, so every
low-fit turn the Jev router does not take (any Vietnamese prompt, for one) crashed the hook
with NameError and injected nothing. No test drove main() into this branch until this one.
"""
import io
import json

from test_foreign_scope_completeness import _groups, mods  # noqa: F401  (pytest fixture)


def test_low_fit_turn_takes_the_getaway_skip(mods, monkeypatch):
    _sd, enf = mods
    monkeypatch.setattr(enf, "RUNNING_HARNESS", "claude")
    monkeypatch.setattr(enf, "FOREIGN_SCOPES", enf._foreign_scopes())
    monkeypatch.setattr(enf, "INVOCABLE_PLUGIN_IDS", set())
    monkeypatch.setattr(enf, "_embed", lambda text: [0.1])
    low = enf.GETAWAY_FLOOR - 0.2
    monkeypatch.setattr(enf, "_post_json", lambda url, payload, timeout: _groups(
        [(f"inst-{k}", low - k / 100, "personal") for k in range(enf.TOP_K)]))
    injected, logged = [], []
    monkeypatch.setattr(enf, "_inject", injected.append)
    monkeypatch.setattr(enf, "_append_offer", lambda *a, **k: logged.append(a))
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(
        {"hook_event_name": "UserPromptSubmit", "session_id": "t-getaway",
         "prompt": "cảm ơn bạn nhiều nhé, hôm nay trời đẹp quá"})))
    assert enf.main() == 0
    assert logged and logged[-1][1] == "getaway"
    assert injected and injected[-1].startswith("SKILL-CHECK:")
