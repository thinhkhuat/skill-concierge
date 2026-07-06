# ADR-0024 — Staleness detector fingerprints content, not mtime

Status: Accepted (2026-07-06)
Relates to: [ADR-0013](0013-doctor-engine-freshness-check.md) (doctor freshness), [ADR-0014](0014-sessionstart-index-self-heal.md) (SessionStart self-heal), [ADR-0016](0016-body-derived-trigger-points.md) (content-hash incremental reindex).

## Context

`doctor`'s "Retrieval health" chronically reported `disk changed since last index — run reindex()` →
`status: FAIL`, and every `search_skills` warned the same, across sessions — cleared only briefly by a
manual reindex, then returning. Root cause (proven by a live repro): the detector and reindex used **two
different signals**.

- **Detector** — `server.py:_disk_signature` fingerprinted `(path, mtime)` over `discover_skill_paths()`,
  recomputed live on every `search_skills` and `health`.
- **Reindex skip** — `build_index` re-embeds a skill only when its `_content_hash(_skill_text(s))` changes.

Any event that moves a file's **mtime without changing its bytes** — `/plugin update` re-materializing the
version-pinned cache dirs, a re-clone, a `touch`, a formatting-only save — trips the detector permanently,
while reindex correctly re-embeds nothing (`embedded: 0`). A reindex "clears" it only because
`_write_manifest` overwrites the stored mtime snapshot — a symptom-fix, not a fix. Compounded by two
drivers: `PLUGIN_GLOB` scans **all** cached plugin versions (measured **852 paths vs 530 deduped skills**),
so each `/plugin update` adds new version dirs → a signature change on content-identical skills; and the
30-minute self-heal throttle leaves staleness windows.

## Decision

Align the detector to the **same signal reindex skips on**. `_disk_signature` now fingerprints **content** —
a hash over `(deduped skill name, _content_hash(_skill_text(s)))` from `discover_skills()` — instead of
`(path, mtime)`. A mtime-only change no longer moves the signature, and the multi-cached-version path churn
collapses to the deduped set that is actually indexed. Real drift (a new / edited / removed skill) still
moves the content signature, so the self-heal and doctor still detect genuine staleness.

## Evidence

- Signal mismatch was never reconciled: the mtime signature landed in `73ea518` (2026-06-26); the
  content-hash skip in `5d8c43b` (2026-06-30).
- Live repro (pre-fix): `touch` a SKILL.md (content md5 identical) → `health` flips to
  `stale: True, ['disk changed since last index']` with **zero** dark/stale points; `--reindex` re-embeds
  nothing (`embedded: 0`) yet clears it (manifest rewrite) — confirming mtime was the sole false trigger.
- Post-fix: unit test `test_disk_signature_is_content_not_mtime` (mtime-touch → NOT stale; content-change →
  stale); vendor suite **38 passed**.

## Consequences

- **Positive:** the entire false-stale recurrence class disappears; doctor `status: OK` holds across
  mtime-only churn; no more "run reindex()" noise on every search.
- **Cost:** `_disk_signature` now reads+parses each SKILL.md (~530) via `discover_skills` instead of
  stat-only. It runs only on `search_skills`/`health` — the per-prompt enforcer path does NOT go through it
  — and those are infrequent + OS-cache-warmed, so the tax is small.
- **Deploy:** requires a re-copy into the stable venv + a reindex (the reindex rewrites the manifest
  signature into the new content format). The now-unused `discover_skill_paths` import was removed.

## Open / to measure

- If `search_skills` latency ever measures as a problem, cache the signature in-process and recompute only
  when a cheap count/mtime tripwire moves (a content re-check only on drift). Deferred — not worth the extra
  code until measured.
