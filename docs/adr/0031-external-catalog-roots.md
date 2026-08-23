# ADR-0031 — External catalog roots (multi-catalog retrieval without import)

Status: Accepted + implemented (2026-08-23). Plan:
`plans/260823-2036-multi-catalog-roots/plan.md`; evidence at foot.

Relates to: ADR-0028 (scope field + query-side visibility filter — this adds a scope
class), ADR-0025 (operator-owned durable home under `~/.claude/skill-concierge/` —
same config pattern), ADR-0030 (operator-owned overlay files — same ownership idiom),
ADR-0016 (body-derived triggers — externals get them), ADR-0026 (flywheel — explicitly
deferred for externals, not dropped).
Source: owner-driven design session 2026-08-23 (grilling interview, 11 decisions);
mechanics grounded by a read-only engine scout the same session.

## Context

Claude Code — like most harnesses — supports one canonical global skill catalog, and
skill-concierge inherited that: discovery roots are **hardcoded** to
`~/.claude/skills` + `$CWD/.claude/skills` (`skills_discovery.py:29-40`) plus the
installed-plugin cache glob. The owner maintains third-party skill collections outside
those roots (first target: `/Users/thinhkhuat/env-DEV/antigravity-awesome-skills/skills`,
**1,599 skills with SKILL.md**) and wants them retrievable **without importing** —
importing would put every skill into Claude Code's per-turn context (even name-only),
which is exactly the cost the concierge exists to avoid.

Mechanics that shape the design (scout, 2026-08-23):

- ADR-0028's filter is query-side on a `scope` payload field
  (`server.py:574-581`); reindex **prunes points whose scope is not visible**, so a new
  root class needs a new scope value wired into `visible_scopes()`.
- Skill identity is the directory name with first-writer-wins collision handling
  (`skills_discovery.py:401`); 23 antigravity names already collide with
  `~/.claude/skills` — un-namespaced externals would be silently swallowed.
- `get_skill` resolves bodies via the absolute `path` stored in the Qdrant payload
  (`server.py:731-750`) — read-inline consumption of a non-installed skill already
  works with zero new code.
- Staleness is content-hashed through `discover_skills()` itself (`server.py:141-158`)
  — new roots join the auto-reindex watch for free, at a per-call re-parse cost that
  must be measured at ~2k skills.

## Decision

Eleven owner decisions, recorded verbatim from the design interview:

1. **Catalog = local directory root only (v1).** Any configured dir whose children
   contain `SKILL.md` (one level deep, matching existing discovery). No git remotes,
   no marketplace manifests — the owner manages clones with git.
2. **Config home:** `~/.claude/skill-concierge/catalog-roots.json`, operator-owned
   durable home (ADR-0025/0030 pattern). Shape: `{alias: {path, include?, exclude?}}`.
   Absent file = byte-identical behavior (no env flag; absence IS the off-switch).
3. **Identity: alias-namespaced.** Every catalog skill indexes as `<alias>:<name>`
   (e.g. `antigravity:seo`), mirroring the plugin namespace convention. Collisions with
   installed names become a non-event.
4. **Scope class `catalog:<alias>`,** added to point payloads at index time and to
   `visible_scopes()` — machine-wide visibility (like `personal`), per-project opt-in
   rejected as config surface for a need not yet hit.
5. **Exposure: search-only tier (v1).** Catalog skills are retrievable via explicit
   `search_skills` / find-skills escalation only — **never** ranked into the per-turn
   enforcer preview. Rationale: 1,599 uncurated skills would dilute the curated shelf,
   shift every gate metric, and grant SKILL-FIRST's near-mandate force to unvetted
   third-party text. Preview eligibility is a possible later phase, measured first.
6. **Results UX: merged ranking + provenance marker.** One ranked list, MAX-pool fusion
   intact; external rows carry `external: <alias>` + the read-inline consumption note,
   and DROP the `/command` field (nothing is installed to invoke). No artificial tiers
   inside the result list. (Implementation note: the row does NOT carry an absolute
   path — a skill's best-scoring point is often a trigger point whose payload has no
   `path`, and `get_skill(name)` resolves the path server-side anyway. See decisions
   log D6.)
7. **Consumption: both paths.** Read-inline is automatic (`get_skill` returns the body
   from the payload path). **Promotion** is an explicit operator act: symlink
   `<catalog>/<skill>` → `~/.claude/skills/<bare-name>`; refuse on collision with a
   clear message. Copy rejected (silent divergence from upstream on every pull);
   alias-named install dirs rejected (pollutes slash-command names).
8. **Ingestion: wholesale + optional globs.** A root indexes everything by default;
   per-root `include`/`exclude` globs exist from day one. Hand-curating 1,599 entries
   is the drudgery the semantic index replaces; the search-only tier contains blast
   radius.
9. **Trust: provenance marking only.** The owner cloned the repo deliberately;
   search-only tier limits exposure. First-use confirm gates and injection scanners
   rejected (friction / unproven value).
10. **Enrichment: embeddings + body-derived triggers (ADR-0016) now. Flywheel
    utterances (ADR-0026) DEFERRED to a future phase — explicitly not ruled out.**
    1,599 × LLM calls for search-only citizens is not day-one cost.
11. **Doctrine + telemetry: both.** `skill-first.md` gains the external consumption
    path (`USING: <alias>:<name>` = pull body via `get_skill`, follow inline — the
    Skill tool cannot invoke it). The ledger gains an `external-take` event class so
    adoption is measurable from day one, epoch-scoped per the AGENTS.md guardrail.

## Consequences

- Index grows ~5x (365 ≈ 6k points → ~+25-30k points): one-time embed cost at first
  index, and `_disk_signature()`'s full re-parse per staleness check must be measured
  at ~2k skills (the in-code "ponytail" cache is the named remedy if it bites).
- A promoted skill exists twice (personal bare name + catalog alias name) with
  identical content; dedup rule: the personal copy wins, the catalog twin is
  suppressed at discovery (a symlink into `~/.claude/skills` resolves to the same
  SKILL.md — suppression keyed on resolved realpath).
- Engine changes are unavoidable (discovery is engine-side): vendored-patch discipline
  applies (`VENDORED.md` entry, env forwarding through `auto_reindex.py` for any new
  flag — the ADR-0026 gap class is the known trap).
- Removing a root (or the whole config) prunes its `catalog:<alias>` points at the
  next reindex via the existing scope-visibility prune — teardown needs no new
  mechanism.
- A dangling alias rename orphans promoted symlinks (they point into the old clone
  path); promotion tooling should surface broken symlinks, doctor check is the
  recorded upgrade if it bites.
- New epoch for retrieval metrics the day this ships; never pool across it.
- **Latent trap (validator B9):** `_point_changed` (`server.py`) re-embeds only when
  `(content_hash, scope)` differs. Adding `tier: external` to points was safe because
  every catalog point is a NEW scope (forced re-embed), but a FUTURE payload-only field
  added to already-indexed points would silently not re-upsert. The next payload
  addition must either bump content or force a rebuild.

## Evidence

Implemented + verified 2026-08-23 (autonomous run; decision log
`plans/reports/decisions-260823-2036-multi-catalog-autonomous-run.md`, D1–D9):

- **Engine tests:** `tests/test_discovery.py` gains 6 catalog cases (validation,
  absent/malformed fail-open, namespacing+scope+globs, include globs, installed-name-wins
  + promoted-twin suppression, visible_scopes) — full engine suite **73 passed** in the
  stable venv. `enforcer.py --selftest` case 10 pins the `must_not tier=external`
  request shape. `analyze.py --selftest` and `catalogs.py --selftest` green.
- **Live retrieval** (post-reindex: 1,975 skills / 18,908 points, +13,413 embedded):
  `search_skills("active directory attack techniques audit")` →
  `antigravity:active-directory-attacks` (0.79) marked `external: antigravity`, with the
  `get_skill` note and no `command` field; `get_skill` pulled a 9,830-byte SKILL.md.
- **Search-only tier live:** the same antigravity-dominant query through the per-turn
  enforcer injected a normal offer with **zero** `antigravity:` entries.
- **Exclusions live:** next-skills sidecar and settings.json `skillOverrides` each hold
  **0** catalog keys (372 installed overrides unchanged).
- **Telemetry live:** a `get_skill` PostToolUse event logs an `ev:"get_skill"` ledger row;
  `analyze.py` reports `deep pulls: 1  external takes: 1`. Crash-safe on empty ledger +
  absent catalog config.
- **doctor:** `External catalogs` check green (`antigravity: 1603 skills`); overall WARN
  is the pre-existing engine build-drift only (live servers on the pre-deploy build;
  clears at Claude Code restart).
- **Latency:** `_disk_signature()` = 894ms at 1,975 skills (infrequent path only; cache
  deferred — see plan Phase 5).
