#!/usr/bin/env python3
"""G6 probe — docs sweep completeness for the ADR-0045 tier-parity release (0.38.0)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
checks = [
    ("docs/adr/0045-catalog-tier-parity.md exists",
     (ROOT / "docs/adr/0045-catalog-tier-parity.md").is_file()),
    ("ADR-0031 carries the 0045 supersede note",
     "0045-catalog-tier-parity" in (ROOT / "docs/adr/0031-external-catalog-roots.md").read_text()),
    ("ADR-0032 carries the 0045 supersede note",
     "0045-catalog-tier-parity" in (ROOT / "docs/adr/0032-external-catalogs-first-class-annex.md").read_text()),
    ("ADR-0036 carries the 0045 supersede note",
     "0045-catalog-tier-parity" in (ROOT / "docs/adr/0036-dynamic-annex-sizing.md").read_text()),
    ("ADR-0043 carries the 0045 amend note",
     "0045-catalog-tier-parity" in (ROOT / "docs/adr/0043-catalog-flywheel-generation-and-bounded-parallel-workers.md").read_text()),
    ("ADR index lists 0045",
     "0045-catalog-tier-parity" in (ROOT / "docs/adr/README.md").read_text()),
    ("CLAUDE.md flags ENFORCER_EXTERNAL_OFFER",
     "ENFORCER_EXTERNAL_OFFER" in (ROOT / "CLAUDE.md").read_text()),
    ("AGENTS.md flags ENFORCER_EXTERNAL_OFFER",
     "ENFORCER_EXTERNAL_OFFER" in (ROOT / "AGENTS.md").read_text()),
    ("CHANGELOG has the 0.38.0 entry",
     "## [0.38.0] — 2026-08-28" in (ROOT / "CHANGELOG.md").read_text()),
    ("openwiki quickstart documents tier parity",
     "0045-catalog-tier-parity" in (ROOT / "openwiki/quickstart.md").read_text()),
    ("openwiki enforcement-gate documents the merged query",
     "0045-catalog-tier-parity" in (ROOT / "openwiki/architecture/enforcement-gate.md").read_text()),
    ("openwiki retrieval-engine updates the tier story",
     "0045-catalog-tier-parity" in (ROOT / "openwiki/architecture/retrieval-engine.md").read_text()),
    ("openwiki operations documents the all-scope default",
     "ADR-0045" in (ROOT / "openwiki/operations.md").read_text()),
    ("README documents tier parity",
     "0045-catalog-tier-parity" in (ROOT / "README.md").read_text()),
]
bad = [name for name, ok in checks if not ok]
for name, ok in checks:
    print(("  ok  " if ok else "  MISS") + " — " + name)
if bad:
    print("DOCS SWEEP FAIL:", len(bad))
    return_code = 1
else:
    print("DOCS SWEEP OK")
    return_code = 0
sys.exit(return_code)
