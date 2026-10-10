"""A run on another ledger never rewrites the live ledger-derived digests. On 2026-10-10 smoke runs
pointed SKILL_CONCIERGE_LOG at empty temp folders; auto_promote then rebuilt the live proven.json and
external-takes.json from an empty ledger and emptied the 🔥 badges and external-take counts."""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import smoke  # noqa: E402


def test_auto_promote_on_another_ledger_leaves_the_live_digests_untouched(tmp_path):
    home = tmp_path / "home"
    live = home / ".claude" / "skill-concierge"
    (live / "logs").mkdir(parents=True)
    (live / "proven.json").write_text(json.dumps({"proven": ["kept"]}))
    (live / "external-takes.json").write_text(json.dumps({"x:kept": 3}))
    temp_logs = tmp_path / "smoke" / "logs"
    temp_logs.mkdir(parents=True)
    env = dict(os.environ, HOME=str(home), SKILL_CONCIERGE_LOG=str(temp_logs), AUTO_PROMOTE_THROTTLE_S="0",
               CLAUDE_PLUGIN_ROOT=str(ROOT))
    for k in ("SKILL_CONCIERGE_PROVEN", "SKILL_CONCIERGE_TAKES_DIGEST", "SKILL_CONCIERGE_CATALOG_ROOTS"):
        env.pop(k, None)
    subprocess.run([sys.executable, str(ROOT / "hooks" / "scripts" / "auto_promote.py")], env=env, check=True,
                   timeout=60)
    assert json.loads((live / "proven.json").read_text()) == {"proven": ["kept"]}
    assert json.loads((live / "external-takes.json").read_text()) == {"x:kept": 3}
    assert (temp_logs.parent / "proven.json").exists()          # written beside the ledger it read


def test_each_smoke_run_starts_with_every_self_heal_throttled(tmp_path, monkeypatch):
    monkeypatch.setattr(smoke.tempfile, "tempdir", str(tmp_path))
    work = smoke._workdir("claude")
    scripts = sorted(p.name for p in (ROOT / "hooks" / "scripts").glob("auto_*.py"))
    assert len(scripts) == len(smoke.SELF_HEAL_STAMPS), scripts      # a new self-heal script needs its stamp
    for stamp in smoke.SELF_HEAL_STAMPS:
        assert (work / "logs" / stamp).is_file(), stamp
