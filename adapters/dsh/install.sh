#!/usr/bin/env bash
# skill-concierge — DSH (DeepSeek Harness) installer / sync / repair (ADR-0050).
#
# DSH integrates skill-concierge through its Cordis composition system: the
# skill-search MCP server is registered as a Cordis plugin row, and the
# per-turn enforcement rides the agent-preset composition (agent.cordis.yml).
# DSH has no plugin marketplace for skill-concierge (it is not a registered
# DSH Cordis plugin), so this installer wires the dev path into the DSH
# profile via the cordis.patch.yml extension mechanism.
#
# What the installer does (idempotent, verified):
#   1. Read the SSOT version from $ROOT/.claude-plugin/plugin.json
#   2. Ensure the DSH profile (desktop or tui) has the skill-search MCP server
#      registered via cordis.patch.yml (the user patch layer)
#   3. Ensure each profile loads the skill-concierge enforcement plugin
#      (adapters/dsh/skill-concierge.dsh.ts: doctrine + per-turn enforcer +
#      the ADR-0059 exclusion echo) through the same patch layer (ADR-0059)
#   4. Verify wiring: MCP server reachable, enforcer script present
#
# DSH surfaces:
#   - Desktop: ~/.ohdsh/profiles/desktop/ (Oh-DSH Desktop, Electron)
#   - TUI:     ~/.ohdsh/profiles/tui/ (CLI/TUI)
#   - Legacy:  ~/.dsh/ (if DSH_HOME points elsewhere)
#
# Usage:
#   ./adapters/dsh/install.sh [--root <path>]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --root)
      ROOT="$(cd "$2" && pwd)"
      shift 2
      ;;
    *)
      echo "Unknown option: $1" >&2
      echo "usage: $0 [--root <path>]" >&2
      exit 1
      ;;
  esac
done

echo "==> skill-concierge → DSH sync (from: $ROOT)"

# ── 1. SSOT version ──────────────────────────────────────────────────────────
VERSION="$(python3 -c "import json;print(json.load(open('$ROOT/.claude-plugin/plugin.json'))['version'])")"
echo "    SSOT version: $VERSION"

# ── 2. Resolve DSH profile directories ──────────────────────────────────────
# DSH_HOME from env, else ~/.ohdsh (preferred, Oh-DSH Desktop), else ~/.dsh.
DSH_HOME="${SKILL_DSH_HOME:-${DSH_HOME:-}}"
if [ -z "$DSH_HOME" ]; then
  if [ -d "$HOME/.ohdsh" ]; then
    DSH_HOME="$HOME/.ohdsh"
  else
    DSH_HOME="$HOME/.dsh"
  fi
fi
echo "    DSH home: $DSH_HOME"

# Detect which profiles are active
DESKTOP_PROFILE="$DSH_HOME/profiles/desktop"
TUI_PROFILE="$DSH_HOME/profiles/tui"
PROFILES=""
for p in "$DESKTOP_PROFILE" "$TUI_PROFILE"; do
  if [ -f "$p/cordis.yml" ]; then
    PROFILES="$PROFILES $p"
  fi
done

if [ -z "$PROFILES" ]; then
  echo "  [!] No DSH profiles found (no cordis.yml under $DSH_HOME/profiles/)" >&2
  echo "      Expected at least one of: $DESKTOP_PROFILE $TUI_PROFILE" >&2
  exit 1
fi
echo "    Active profiles:$(for p in $PROFILES; do echo -n " $p"; done)"
echo ""

# ── Validator: DSH's own parse rules for a user patch layer ─────────────────
# DSH's js-yaml with DSH's schema (JSON_SCHEMA + the `!!js` scalar), a top-level
# array, every entry a mapping (dsh-app-boot parsePatchList). Returns 0 = loadable,
# 1 = not loadable, 2 = cannot check here (no dsh/node) — the caller decides.
JS_YAML="$(dirname "$(dirname "$(readlink -f "$(command -v dsh 2>/dev/null || echo /nonexistent)")")")/node_modules/js-yaml"
validate_patch() {
  [ -d "$JS_YAML" ] && command -v node >/dev/null 2>&1 || return 2
  node -e '
    const y = require(process.argv[1]);
    const js = new y.Type("tag:yaml.org,2002:js", { kind: "scalar",
      resolve: (d) => typeof d === "string", construct: (d) => ({ __jsExpr: d }) });
    const d = y.load(require("fs").readFileSync(process.argv[2], "utf8"), { schema: y.JSON_SCHEMA.extend(js) });
    if (!Array.isArray(d) || !d.every((e) => e && typeof e === "object" && !Array.isArray(e))) process.exit(1);
  ' "$JS_YAML" "$1" >/dev/null 2>&1 || return 1
}

# ── 3. Write skill-search MCP server to each profile's cordis.patch.yml ──
# Built into `<patch>.new`, validated, and only then swapped in (the previous file is
# kept as a timestamped backup). A result DSH could not load never replaces the original.
for PROFILE in $PROFILES; do
  echo "==> Configuring: $PROFILE"

  python3 - "$PROFILE" "$ROOT" "$VERSION" <<'PYEOF'
import json, os, sys
from pathlib import Path

profile_dir, root, version = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
patch_file = profile_dir / "cordis.patch.yml"

# Read existing patch or start fresh. The file is a top-level YAML ARRAY (DSH's
# loader rejects anything else); a pristine profile holds the empty flow list `[]`,
# which must go once block items follow it — `[]` then `- id:` is not YAML, and
# DSH's js-yaml refuses the whole user layer (fixed in 0.49.0; earlier installs
# appended after it and left both profiles unparseable).
patch_lines = []
if patch_file.exists():
    # only the top-level empty list: column 0, optionally commented — never an operator's
    # indented `[]` value
    patch_lines = [ln for ln in patch_file.read_text(encoding="utf-8").splitlines()
                   if not (ln[:1] not in (" ", "\t") and ln.split("#", 1)[0].strip() == "[]")]

# Every entry is an INSERT patch. DSH's patch layer is id-targeted: a bare
# `- id: x` only overrides an EXISTING entry x, and a new id is warned
# "patch: entry x not found" and skipped (dsh-app-boot applyEntryPatches). Adding
# a plugin takes `- insert: [ {id, name, config} ]` — before 0.49.0 all three
# entries below were bare, so none of them ever loaded.
# ── Entry 1: skill-search MCP server ──────────────────────────────────────
MCP_SERVER_ENTRY = f"""# skill-concierge skill-search MCP server (ADR-0050, v{version})
- insert:
    - id: skill-concierge
      name: '@deepseek-ai/dsh-mcp-client'
      config:
        serverName: skill-search
        transport: stdio
        command: /bin/bash
        args: ["{root}/bin/skill-search-mcp"]
        env:
          SKILL_QDRANT_URL: http://localhost:6333
          SKILL_EMBED_BACKEND: fastembed
          SKILL_EMBED_MODEL: sentence-transformers/paraphrase-multilingual-mpnet-base-v2
          SKILL_TOP_K: "6"
          SKILL_LLM_TRIGGERS: "1"
          TRIGGERS_MAX: "16"
          SKILL_TRIGGERS: "{Path.home() / '.claude' / 'skill-concierge' / 'triggers.json'}"
          SKILL_CONCIERGE_HARNESS: dsh
          SKILL_DSH_ROOTS: "1"
"""

# ── Entry 2: unlazy DSH stop hook ─────────────────────────────────────────
UNLAZY_ENTRY = f"""# unlazy stop-hook (DSH), v2.1.0
- insert:
    - id: unlazy-stop
      name: '{root}/adapters/dsh/unlazy-dsh-stop.dsh.ts'
      config: {{}}
"""

# ── Entry 3: the skill-concierge enforcement plugin (ADR-0050 §5, wired by ADR-0059) ──
ENFORCER_ENTRY = f"""# skill-concierge enforcement plugin (ADR-0059, v{version})
- insert:
    - id: skill-concierge-enforcer
      name: '{root}/adapters/dsh/skill-concierge.dsh.ts'
      config: {{}}
"""

MCP_MARKER = "# skill-concierge skill-search MCP server (ADR-0050"
ENFORCER_MARKER = "# skill-concierge enforcement plugin (ADR-0059"
UNLAZY_MARKER = "# unlazy stop-hook (DSH)"
existing = "\n".join(patch_lines)

def _replace_block(existing_text: str, marker: str, new_block: str) -> str:
    """Replace a marker-led block with a fresh entry. The block is the marker
    comment line plus the one `- id:` list item and its indented tail. Everything
    from the marker to the next top-level line or EOF is replaced."""
    lines = existing_text.split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        if lines[i].startswith(marker):
            out.append(new_block.rstrip())
            i += 1
            while i < len(lines) and not lines[i].strip():      # blank lines before our item
                i += 1
            if i < len(lines) and lines[i].startswith("- "):
                i += 1
                # our item's indented tail; an operator comment or top-level line ends it
                while i < len(lines) and lines[i][:1].isspace() and not lines[i].lstrip().startswith("#"):
                    i += 1
        else:
            out.append(lines[i])
            i += 1
    return "\n".join(out)

def _append_block(existing_text: str, new_block: str) -> str:
    """Append a new entry to a YAML list patch. Handles pristine `[]` and
    populated lists."""
    if existing_text.strip() == "":
        return new_block.rstrip()
    return (existing_text.rstrip() + "\n" + new_block.rstrip()
            if not existing_text.endswith("\n")
            else existing_text.rstrip("\n") + "\n" + new_block.rstrip())

# Handle MCP entry
if MCP_MARKER in existing:
    patch_text = _replace_block(existing, MCP_MARKER, MCP_SERVER_ENTRY)
else:
    patch_text = _append_block(existing, MCP_SERVER_ENTRY)

# Handle unlazy entry (on the result of the MCP step)
if UNLAZY_MARKER in patch_text:
    patch_text = _replace_block(patch_text, UNLAZY_MARKER, UNLAZY_ENTRY)
else:
    patch_text = _append_block(patch_text, UNLAZY_ENTRY)

# Handle the enforcement plugin entry
if ENFORCER_MARKER in patch_text:
    patch_text = _replace_block(patch_text, ENFORCER_MARKER, ENFORCER_ENTRY)
else:
    patch_text = _append_block(patch_text, ENFORCER_ENTRY)

(patch_file.parent / (patch_file.name + ".new")).write_text(patch_text + "\n", encoding="utf-8")
PYEOF
  PATCH="$PROFILE/cordis.patch.yml"
  NEW="$PATCH.new"
  set +e; validate_patch "$NEW"; rc=$?; set -e
  if [ "$rc" = 1 ]; then
    rm -f "$NEW"
    echo "  !! $PATCH: the updated patch layer would not load in DSH — original kept untouched." >&2
    echo "     Usually an operator entry written in flow style ([...]); convert it to block style and re-run." >&2
    PATCH_FAILED=true
  else
    [ "$rc" = 2 ] && echo "    (DSH's js-yaml not found — parse check skipped)"
    if [ -f "$PATCH" ] && cmp -s "$NEW" "$PATCH"; then
      rm -f "$NEW"
      echo "  [✓] cordis.patch.yml already current (v$VERSION)"
    else
      [ -f "$PATCH" ] && cp -p "$PATCH" "$PATCH.bak-skillconcierge-$(date +%Y%m%d-%H%M%S)"
      mv "$NEW" "$PATCH"
      echo "  [✓] Updated cordis.patch.yml: skill-search MCP + unlazy stop-hook + enforcement plugin (v$VERSION)"
    fi
  fi

done

# ── 4. Enforce exec bits on the launcher ─────────────────────────────────────
chmod +x "$ROOT/bin/"* "$ROOT/setup.sh" \
         "$ROOT/adapters/dsh/install.sh" 2>/dev/null || true
echo "    bin/ + installer exec bits ensured"

# ── 5. Verify ────────────────────────────────────────────────────────────────
echo "==> verify:"
VERIFY_OK=true

# 5a. MCP launcher resolvable
MCP_LAUNCHER="$ROOT/bin/skill-search-mcp"
if [ -f "$MCP_LAUNCHER" ] && [ -x "$MCP_LAUNCHER" ]; then
  echo "    MCP launcher executable: yes ($MCP_LAUNCHER)"
else
  echo "    !! MCP launcher not found/executable at $MCP_LAUNCHER" >&2
  VERIFY_OK=false
fi

# 5b. Enforcer script present
if [ -f "$ROOT/hooks/scripts/enforcer.py" ]; then
  echo "    enforcer script present: yes"
else
  echo "    !! enforcer script not found at $ROOT/hooks/scripts/enforcer.py" >&2
  VERIFY_OK=false
fi

# 5c. Profile patch files contain the MCP entry
for PROFILE in $PROFILES; do
  PATCH="$PROFILE/cordis.patch.yml"
  if [ -f "$PATCH" ] && grep -q "skill-search" "$PATCH" 2>/dev/null; then
    echo "    Profile $PROFILE: skill-search MCP entry present"
  else
    echo "    !! Profile $PROFILE: skill-search MCP entry missing" >&2
    VERIFY_OK=false
  fi
done

# 5c'. Each patch file loads under DSH's own parse rules (validate_patch above).
for PROFILE in $PROFILES; do
  PATCH="$PROFILE/cordis.patch.yml"
  set +e; validate_patch "$PATCH"; rc=$?; set -e
  case "$rc" in
    0) echo "    Profile $PROFILE: cordis.patch.yml loads (DSH js-yaml + DSH schema, array of mappings)" ;;
    2) echo "    (DSH's js-yaml not found — patch-file parse check skipped)" ;;
    *) echo "    !! Profile $PROFILE: cordis.patch.yml would NOT load in DSH" >&2; VERIFY_OK=false ;;
  esac
done
if ${PATCH_FAILED:-false}; then VERIFY_OK=false; fi

# 5d. Doctor's DSH row (WARN-only, surface but don't fail)
# Only doctor's DSH row (a full doctor run takes ~20 s and checks everything else too).
python3 -c 'import importlib.util as u, sys
s = u.spec_from_file_location("doctor", sys.argv[1]); d = u.module_from_spec(s); s.loader.exec_module(d)
r = d.check_dsh(); print("  [" + ("✓" if r["status"] == d.OK else "!") + "] DSH integration  " + r["detail"])' \
  "$ROOT/scripts/doctor.py" 2>/dev/null || echo "    (doctor DSH row unavailable — run: python3 scripts/doctor.py)"

if $VERIFY_OK; then
  echo "    verify: OK"
else
  echo "    verify: FAILED — see lines above" >&2
  exit 1
fi

echo "==> Done. Restart DSH (or reload the agent preset) to load the skill-search MCP server."
echo "    Then confirm: MCP tools list mcp__skill-search__search_skills and mcp__skill-search__get_skill."