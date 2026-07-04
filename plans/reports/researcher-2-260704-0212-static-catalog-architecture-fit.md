# Architecture Fit: static YAML catalog vs. skill-concierge

**Researcher-2 · angle: ARCHITECTURE FIT · 2026-07-04**

## Verdict

**CONTRADICT** as-dropped. `scripts/generate_catalogs.py` re-introduces the exact
"dump the whole grouped catalog" pattern skill-concierge was built to replace, and it
opens a **second discovery path** parallel to the code's declared single source of truth.
A static catalog is only **neutral-if-repurposed** under two conditions it fails today.
**Integration point into the live pipeline: NONE** (without a regression).

The argument below holds **even if the script were fully wired** — it does not rest on the
script being orphaned/untracked (that is provenance, Task #1's lane; used here only as
supporting color).

---

## 1. The design thesis (direct quotes)

skill-concierge exists to *kill* the full-catalog dump:

- `README.md:8-10` — "Where the default dumps every skill description into context every
  turn and hopes the model picks one, skill-concierge replaces *hope* with
  **retrieve-precisely + enforce-use + measure**."
- `README.md:33-36` — "Claude Code's default skill discovery injects **every** installed
  skill's description into the context window on **every** turn... As a catalogue grows
  past a few dozen skills, that approach burns context and quietly degrades: the model
  skims, misses the fitting skill, or 'wings it'."
- Three organs, `README.md:49` — **Retrieve** = "semantic search over the skill catalogue
  (Qdrant + multilingual embeddings)". The unit of delivery is a *ranked few by meaning*,
  not a grouped inventory.

The runtime enforces "few, not all" explicitly. The per-turn mandate
(`hooks/scripts/enforcer.py:242-248`, repeated `:357-359`):

> "Shown skills are a PREVIEW of ~500, not all."
> "Preview for this task (NOT the full ~500 shelf):"

So the core thesis your team-lead named is confirmed verbatim: **semantic retrieval
REPLACES dumping a static catalog into context, because the ~500-skill shelf is too big to
scan.**

## 2. How discovery actually works today — one live path, no YAML

- Skills are found by a **live filesystem glob** over `SKILL.md` files, parsed at index
  time. `vendor/skill-search/skill_search/skills_discovery.py:24-32` (the `SKILL_DIRS` +
  `PLUGIN_GLOB` globs) and `:96-103` (`discover_skill_paths()` — `glob.glob(.../ "*" /
  "SKILL.md")`). Frontmatter parsed: `name`, `description`, `when_to_use`, body capped to
  4000 chars (`:60-93`).
- This module declares itself the **only** discovery path, and warns precisely against a
  second one: `skills_discovery.py:5-16` — "Single source of truth for 'what skills exist'...
  If the two walked different sets (they used to), you could index a skill you never freed...
  **silent budget leaks. Keep this the ONLY place skill discovery lives.**"
- The reindex consumes that live glob **directly**, never a file:
  `vendor/skill-search/skill_search/server.py:56` imports `discover_skills,
  discover_skill_paths`; `:328` `skills = discover_skills()`; also `:113/:454/:488`.
- Runtime presentation is a semantic **top-k preview**, not a catalog dump:
  `enforcer.py:65` `TOP_K = 5`; `_retrieve()` `:311-328` pulls top-k from Qdrant per turn.
  SessionStart (`hooks/scripts/doctrine.py`) injects a **doctrine**, not an inventory.

## 3. Does skill-concierge produce or consume ANY static catalog today? — No

- No `SKILLS.yaml` / `COMMANDS.yaml` exists on disk (`fd` → empty).
- Nothing reads a YAML catalog. The only static config files are **curated subsets**, the
  opposite of a full dump: `config/keep-on.json` is a "Curated always-on allowlist" of ~32
  named skills (`config/keep-on.json:1-4`); `config/keep-off.json` is a suppression list.
  skill-concierge's static files are *deliberately partial policy*, never inventories.
- `scripts/generate_catalogs.py` is inert: its inputs (`commands_data.yaml`,
  `skills_data.yaml`, and the `scan_skills.py` / `scan_commands.py` / `win_compat`
  producers it references at `:33,:40,:87,:18-25`) **do not exist in the repo** (`fd` →
  empty). It cannot run. It is also untracked (`git status` → `?? scripts/generate_catalogs.py`)
  and branded for a different project ("ClaudeKit Engineer", `:57,:103`). Provenance only —
  the architecture verdict below does not depend on it.

## 4. Why it CONTRADICTS — three points that survive the script being fixed

Assume the scanners existed and the script ran perfectly. It still fails fit:

**(a) A pre-generated, category-grouped full dump IS the rejected pattern.** The catalog
groups *every* skill under hardcoded buckets (`generate_catalogs.py:107-118`:
`ai-ml / frontend / backend / …`) with a `total_skills` count. That is a static
"everything, grouped" artifact — structurally the same object as the default's
"inject every description," which `README.md:33-36` names as the thing that "burns context
and quietly degrades." Grouping by hardcoded **category** also contradicts the
retrieve-by-**meaning** thesis (`README.md:49`).

**(b) It is a second discovery path — the exact failure the SSOT warns against.** A
separately-scanned `skills_data.yaml` walks the skill universe independently of
`discover_skills()`. `skills_discovery.py:5-16` says keep discovery in ONE place or get
"silent budget leaks"; a parallel YAML generalizes that drift risk. Whatever the catalog
says will diverge from the live Qdrant index the moment a `SKILL.md` changes — and the
index self-heals on its own (`hooks/scripts/auto_reindex.py`), so the YAML is guaranteed to
fall behind.

**(c) The COMMANDS half is out of scope entirely.** `generate_catalogs.py:38-80` emits a
COMMANDS catalog. skill-concierge **excludes** slash-commands *by design*: ADR-0001 /
`README.md:53-58` — "Built-in / user-only slash-commands ... are **excluded by design** —
they aren't `SKILL.md` files, cost no model context, and **the model can't fire them**."
So this half doesn't merely contradict the retrieval thesis; it produces an inventory of a
class that sits **outside skill-concierge's problem space**.

Decompose the script and the two halves fail for *different* reasons — worth stating
plainly: **SKILLS.yaml** directly contradicts (static grouped dump of the exact universe
the engine indexes semantically); **COMMANDS.yaml** is domain-foreign (a class the model
can't invoke).

## 5. The neutral-if-repurposed carve-out (bounded, so it reads decisive)

A static catalog is architecture-neutral **only if both** hold:

1. It sources from `discover_skills()` (the SSOT) — not a parallel `*_data.yaml` scan; and
2. It is **never injected per-turn** — a pure offline/human snapshot, regenerated on
   demand, that the runtime never reads.

Even then its value is thin: skill-concierge already answers "what/how-many skills" via the
engine's `health` tool and `discover_skill_paths()` (`server.py:113` lists them), so a
human inventory is redundant and — because it drifts — *worse* than querying the live index.

`generate_catalogs.py` fails **both** conditions (parallel `*_data.yaml` source; grouped
full artifact intended for "consumption by Claude", per its own docstring `:4`). So for the
dropped script specifically, the carve-out does not apply — it lands on CONTRADICT.

## 6. Where could such a catalog plug into the existing pipeline? — Nowhere without regression

- **As a reindex input?** No. Reindex calls `discover_skills()` directly
  (`server.py:56,:328`) off the live filesystem. Feeding it a static YAML would be
  *strictly worse* (staleness) and require rewiring the declared SSOT.
- **As the per-turn context?** No — that is precisely the dump the enforcer's
  "PREVIEW of ~500, not all" (`enforcer.py:244-248`) exists to prevent.
- **As curation config?** No — curation is already **curated subsets**
  (`keep-on.json` / `keep-off.json`), not full catalogs.
- **As an offline human doc?** Only under §5's two conditions, which this script violates;
  and even a clean version is redundant with `health` + drifts from the live index.

**Concrete answer: NONE.** Every candidate insertion point is either already served by the
live-index path or is the anti-pattern the design rejects.

---

## Evidence index (load-bearing `file:line`)

- Thesis: `README.md:8-10, 33-36, 49`
- "Few not all" runtime: `hooks/scripts/enforcer.py:65, 244-248, 311-328, 357-359`
- Single discovery path / SSOT warning: `vendor/skill-search/skill_search/skills_discovery.py:5-16, 24-32, 96-103`
- Reindex reads the glob, not YAML: `vendor/skill-search/skill_search/server.py:56, 113, 328`
- Slash-commands excluded by design: ADR-0001 / `README.md:53-58`
- Curated-subset config (not full dumps): `config/keep-on.json:1-4`
- The dropped script's dump structure + missing inputs + foreign branding:
  `scripts/generate_catalogs.py:4, 18-25, 33, 57, 103, 107-118`; untracked (`git status`);
  inputs absent (`fd`).

## Unresolved / honest status

- I did not read the ADR-0001 file body directly (quoted via its faithful `README.md:53-58`
  summary). If the report needs the ADR's own wording, that file is `docs/adr/0001-index-model-invocable-skills-only.md`.
- Provenance of the script (who dropped it, from which repo) is **Task #1's** lane; I used
  only its on-disk shape and `?? untracked` status as supporting color, not as the spine of
  the fit verdict.
