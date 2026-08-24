# ADR-0037: Borrowed-manifest freshness — health from a non-project cwd

| | |
|---|---|
| **Status** | Accepted |
| **Date** | 2026-08-24 |
| **Supersedes** | none |
| **Amends** | ADR-0028 (per-root manifest keying) and ADR-0035 (whose pinned cwd surfaced the gap) |

## Context

The index freshness manifest is keyed per project root — `index_meta-<md5(cwd/.claude/skills)[:8]>`
— because the disk *signature* it stores is cwd-scoped (ADR-0028): one shared file would make every
session with a different project report a false "disk changed since last index".

ADR-0035 pins the Codex MCP server's cwd to the plugin cache so its relative command resolves.
That cwd is not a project, so the server derives a **phantom manifest key nothing ever writes**.
The second live Codex revalidation measured the consequence (its defect D2): `health()` reported
`degraded — no index manifest; never indexed` forever, and every `search_skills` reply carried
`"index manifest missing — run reindex()"` — against a shared collection that was demonstrably
fresh (the same session's SessionStart auto-reindex had written the repo-root manifest five
seconds after the session opened). Worse, obeying the warning from Codex would have reindexed
under the phantom root. Permanent wolf-crying trains operators to ignore real staleness — the
exact failure mode doctor's own history warns about.

## Decision

**When the server's own manifest key has no file, borrow the newest *other* root's manifest for
freshness — and only freshness.** Chosen by the operator over three alternatives (pin a stable
key in the Codex descriptor via a new env seam — needs the env-parity contract loosened and a new
cross-file sync; suppress the warning only from plugin-cache cwds — honest but blind; document
and leave — keeps the wolf-crying).

- `_newest_foreign_manifest()` scans the meta dir, skips the server's own path, and returns the
  manifest with the greatest `indexed_at`. Fail-open to None.
- `_staleness_warning()`: own manifest missing but a foreign one exists → **no warning**. For a
  machine-global collection, "has anything on this machine indexed recently" is the honest
  freshness question when the per-root answer does not exist — and the SessionStart auto-reindex
  keeps some manifest fresh on every active machine. Genuinely no manifest anywhere → the old
  "never indexed" warning stands.
- `health()`: same fallback — `indexed_at` from the borrowed manifest, `freshness_from: <root
  key>` published as data, status stays healthy. **`stale` stays `None`**: the borrowed
  signature belongs to another cwd, so per-root staleness is UNKNOWABLE from here, not false —
  the same None-vs-False distinction the engine-drift leg already draws.

**Claude-side visible change, accepted with eyes open:** a brand-new project root now shows
inherited freshness instead of "never indexed" until its first reindex. That window is one
SessionStart long — the auto-reindex fires immediately — and the per-root staleness comparison
(the thing the per-root key exists for) is untouched wherever an own manifest exists.

## Validation

- Three vendored tests: newest-foreign selection (and the wolf-cry going silent), a genuinely
  manifest-less machine still degrading, and the own manifest always outranking foreign ones.
- Live, under the exact failing condition (engine imported with cwd = the Codex 0.26.1 plugin
  cache): phantom key `index_meta-0194b3cc` absent → borrowed `964df33f` (the very manifest the
  revalidation report root-caused as the real fresh one, written by the Codex session's own
  SessionStart hook), `_staleness_warning()` → `None`.
- Full engine suite green (79 tests).
