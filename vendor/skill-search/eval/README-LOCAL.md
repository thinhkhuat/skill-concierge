# ⚠ LOCAL NOTE — `labeled_queries.jsonl` measures the WRONG universe here

**Do not trust `run_eval.py`'s recall@k on this deployment.** It is a harness smoke-test, not
a quality bar.

`labeled_queries.jsonl` is the **upstream author's** label set. Its expected answers target
skills that are **not in this index**:

- the author's plugins — `gsd-*`, `superpowers:*`, `claude-mem:*`, `chrome-devtools-mcp:*`
- **built-in slash-commands** — `loop`, `schedule`, `verify`, `run`, `code-review`,
  `update-config`, `keybindings-help`

This engine **deliberately** indexes only model-invocable `SKILL.md` skills
(see `docs/adr/0001-index-model-invocable-skills-only.md`). Those labels can therefore never
be retrieved here, so recall@k comes out near-zero — measuring a universe this engine
excludes by design, **not** retrieval quality.

## To get a real number

Relabel with ground truth drawn **only** from the indexed catalogue:

1. Confirm membership via `search_skills` / `get_skill` (use **namespaced** ids — `ck:worktree`,
   not `worktree`).
2. Rewrite each `{query, expect[]}` so `expect[]` lists only in-index skills.
3. Rerun `run_eval.py <your-relabeled.jsonl>`.

Until then: `run_eval.py` answers *"does the embed→search pipeline run?"* — nothing more.

Full context: `docs/caveats.md` §1, `docs/adr/0001-index-model-invocable-skills-only.md`.
