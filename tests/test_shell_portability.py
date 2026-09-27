"""Every shipped shell script parses under macOS's stock /bin/bash (3.2).

The test suite and most gates run the bash first on PATH, which is often a newer Homebrew
build. Bash 3.2 is stricter about quotes inside `$( ... )` (an apostrophe in an embedded
heredoc's comment breaks the parse), and a user without Homebrew bash runs these scripts
with it.
"""
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
STOCK_BASH = Path("/bin/bash")
SCRIPTS = [ROOT / "setup.sh", ROOT / "bin" / "skill-search-mcp",
           *sorted((ROOT / "adapters").glob("*/install.sh"))]


@pytest.mark.skipif(not STOCK_BASH.exists(), reason="no /bin/bash on this host")
@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: str(p.relative_to(ROOT)))
def test_parses_under_stock_bash(script):
    r = subprocess.run([str(STOCK_BASH), "-n", str(script)],
                       capture_output=True, text=True, timeout=30, check=False)
    assert r.returncode == 0, r.stderr
