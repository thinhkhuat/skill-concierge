/**
 * skill-concierge — Command Code colon-name skill bridge (mod adapter).
 *
 * Command Code validates a skill's frontmatter `name` strictly — lowercase letters, numbers and
 * single hyphens, at most 64 characters, and the skill's directory must carry the same name — and
 * SKIPS any skill that breaks a rule. A corpus that names itself with a colon (`ak:fix`, `ak:plan`,
 * `ck:copywriting`) therefore loads in Claude Code, which resolves `ak:fix` to the `ak-fix`
 * directory it already lives in, and never loads in Command Code at all: not in `/skills`, not in
 * the `/` menu, not in the model's skill catalogue, and `/skill-name` cannot reach it.
 *
 * This mod is the consumer half of the bridge. `scripts/cmd_skill_bridge.py` materializes a
 * normalized copy of every such skill — a legal `name:` matching its own directory, plus
 * colon-consistent references inside the body — into one shelf directory, and this mod hands that
 * shelf to Command Code with `cmd.addSkillsPath()`. Nothing else is needed: the shelf is an
 * ordinary directory of skills, so they load, autocomplete and auto-invoke like any other skill,
 * and the copy under the shelf's `/ak-fix` is reached by the same name the concierge's own menu
 * and ledger have always used for the original.
 *
 * Why a shelf and not an edit: the sources belong to their authors, and on a shared-shelf machine
 * `~/.commandcode/skills` is a symlink to `~/.claude/skills`, so a "fix in place" would rewrite
 * the Claude Code originals. Every source is hashed into the shelf manifest, and
 * `cmd_skill_bridge.py verify` proves none of them changed.
 *
 * Fail-open: a missing shelf, a read error or a re-entrant factory warning can never break a
 * session — the mod says so once, and Command Code starts without the bridged skills, exactly as
 * it did before this mod existed.
 */

import { existsSync, statSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

/** The shelf `cmd_skill_bridge.py build` writes and this mod registers. */
function shelfDir(): string {
  const fromEnv = process.env.SKILL_CONCIERGE_BRIDGE_SHELF;
  if (fromEnv && fromEnv.trim()) return fromEnv.trim();
  return join(homedir(), ".commandcode", "skill-concierge-bridge");
}

export default function (cmd: any): void {
  const shelf = shelfDir();
  try {
    if (!existsSync(shelf) || !statSync(shelf).isDirectory()) {
      cmd.ui?.notify?.(
        `skill-bridge: no shelf at ${shelf}, so skills whose frontmatter name uses a colon `
        + "(ak:fix, ck:copywriting) stay invisible to Command Code this session. Build it with "
        + `\`python3 scripts/cmd_skill_bridge.py build\` (set SKILL_CONCIERGE_BRIDGE_SHELF to use `
        + "another location).",
      );
      return;
    }
    // One registration, no hooks: the shelf is read once at discovery, and nothing about a turn
    // depends on this mod afterwards. Fail-open — a disposable we never use is still returned by
    // the host, and a host without addSkillsPath predates the mod API's skills seam.
    cmd.addSkillsPath?.(shelf);
  } catch {
    // fail-open: a bridge that cannot register must not stop the session from starting
  }
}
