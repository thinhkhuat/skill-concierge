# D1 (CORRECTED RE-AUDIT) — MISSED-NOVELTY — did the fork DROP / disable / degrade anything good from skill-search 0.1.0?

**Dimension:** D1 · **Date:** 2026-07-05 · **Constraint:** READ-ONLY (nothing modified) · **Author:** D1 auditor (re-verified first-hand, both trees)
**Trees:** fork = `/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge/` · OG = `…/skill-concierge/vendor/skill-search/` (= current upstream 0.1.0, per corrected baseline).

## Does the data correction change D1? NO — and I confirmed it.
D1 is **config-independent**: every finding rests on file reads (source, setup, `.mcp.json`, docs, tests), **not** on any invocation-ledger rate (fallback / conversion / dodge / hit@k). The 0018 corrected baseline's whole fix is about how ledger rates were epoch-pooled — that touches D2/D4, not one line of D1. I re-ran every load-bearing `grep`/`sed` against both trees this pass; **all nine prior verdicts hold unchanged.** My prior D1 finding still stands, explicitly.

## Evidence table (re-verified this pass)

| # | OG feature / novelty | Status | Evidence (file:line, re-checked) | Severity |
|---|---|---|---|---|
| 1a | **Service-free tier CAPABILITY** (embedded on-disk Qdrant + fastembed, no Docker) | **KEPT** (engine) | `vendor/…/server.py:65` `QDRANT_URL=os.environ.get("SKILL_QDRANT_URL")` → server mode only if set; `:98-105` embedded `QdrantClient(path=…)` when unset; `:100` "Default is EMBEDDED (local file, no server/Docker)"; fastembed default `:71-74` + lazy-load `:172-178`. Setup escape note `setup.sh:7-9`. | KEEP |
| 1b | **Service-free as the DEFAULT / portable happy-path** | **DIVERGED → Docker hard-required** | `.mcp.json:6` hardcodes `SKILL_QDRANT_URL=http://localhost:6333`; `setup.sh:47-48` unconditional `exit 1` on missing docker / dead daemon; `setup.sh:58-72` step 2b embed shim **also** needs Docker; the `setup.sh:7-9` "skip step 2" note has **no `--service-free` flag** — script hard-exits first. | **MODERATE** (portability regression, recoverable by hand-editing `.mcp.json` + skipping `setup.sh`) |
| 2 | **`search_skills` on-disk-drift `warning`** (loud-failure guard) | **KEPT** | `server.py:459-461` still computes `_staleness_warning()` and sets `out["warning"]`; helper intact `:150-162`; comment `:458` "Surface index drift in-band so dark/stale skills don't fail silently." Test round-trip `tests/test_indexing.py`. | KEEP |
| 3 | **`health` dark/stale reporting + non-zero exit** (cron/CI-safe) | **KEPT** | `server.py:496-548` `_health()`: `dark` `:519`, `stale` `:520`, dim-mismatch guard `:531-537`; CLI `--health` **`sys.exit(0 if status=="ok" else 1)` `:578`**. | KEEP |
| 4 | **Token-savings PROOF** (`measure_tokens.py`, tiktoken BPE) | **KEPT + RE-GROUNDED** on fork's universe | Tool present `vendor/…/scripts/measure_tokens.py` (1,983 B); `setup.sh:44` installs `tiktoken`. Fork re-ran on its own index: `docs/skill-search-deployment-readme.md:49` (tiktoken cl100k, **507 skills**), `:64-65` **net ~35,687 tok/turn (~17.8%)**, re-measure recipe `:192-195`. | KEEP+ (stronger than OG's author-set of 117) |
| 5 | **24-query labeled recall eval** (`eval/labeled_queries.jsonl`, `run_eval.py`) | **DIVERGED** — OG eval retired as wrong-universe; replacement **built, not shipped as a clean number** | OG files still on disk: `vendor/…/eval/labeled_queries.jsonl`, `run_eval.py`. Fork replacement: `scripts/precision_eval.py` (495-way recall + precision gate), `eval/scenarios/*.json` (14 files), `eval/thresholds.json`. BUT `precision_eval.py:34` needs `claude_skills_shadow` collection and **no clean recall@k is published in any doc**. | **MODERATE** (no valid quality bar currently *shipped*, though harness exists) |
| 6 | **Tail-scale caveat** ("hundreds worth it, handful overkill") | **KEPT** — relocated to docs | `docs/skill-search-deployment-readme.md:44` "squarely the tail-scale case." | KEEP |
| 7 | **"Two pieces useless apart"** framing | **KEPT** — relocated to docs | `docs/skill-search-deployment-readme.md:80`. | KEEP |
| 8 | **Prompt-cache rebuttal** ("isn't it cached? — billing win ≠ context-window win") | **DROPPED** | OG had the whole section `vendor/…/README.md:111-137` ("But isn't the skill listing prompt-cached?", `:119` "caching is a **billing** optimization, not a **context-window** one"). Fork grep across `README.md`+`docs/*.md`: only **incidental** cache mentions (`caveats.md`, `…-trial-setup-…:42-43` about override rebuild) — **the objection-rebuttal section is absent**. | **MINOR** (rhetorical defense lost, not a capability) |
| 9 | **Offline unit tests** (discovery/parsing/namespacing/dedup, staleness guards) | **KEPT + EXPANDED** | Re-counted this pass: `vendor/…/tests/` = **30 test fns** (`test_cli.py`×4, `test_discovery.py`×13, `test_indexing.py`×8, `test_overrides.py`×5). Fork ADDED body-trigger/multivector coverage in `test_indexing.py`. | KEEP+ |

## Cross-cutting read (unchanged)
- **Engine integrity high.** Every loud-failure guard (drift warning, dark/stale health, dim-mismatch, non-zero exit) survived the multivector + body-trigger patches untouched and stays test-covered. **No BROKEN verdicts.**
- **All real losses sit at the packaging + persuasion layer**, not the retrieval core: (a) portable service-free *default* → Docker-gated (biggest regression), (b) cache rebuttal gone, (c) recall number unpublished despite an existing harness.
- **Two things got better:** token-proof now measured on the actual 507-skill index (17.8% window reclaimed); unit suite grew to cover the fork's own patches.

## Unresolved / flags
- **Service-free recoverability:** architecturally recoverable (engine supports embedded), but `setup.sh` has no `--service-free` path — hard-exits on no-Docker. ~10-line setup.sh fix if portability matters, not a rewrite.
- **precision_eval as a real bar:** depends on a `claude_skills_shadow` enrichment collection + authored scenarios; not run here (read-only, needs live Qdrant). Whether it yields a trustworthy recall@k → **D3's territory**, still UNVERIFIED.
- **Vendored source not literally pristine 0.1.0:** `vendor/…/pyproject.toml` fastembed pin comment references "the live mpnet index" — flag for whoever re-vendors (minor).

---
Status: DONE (prior D1 finding re-confirmed; data correction does not touch this dimension)
Summary: All 9 D1 verdicts hold on re-verification — engine novelties (drift warning, dark/stale health, token proof, 30 unit tests) KEPT (two strengthened); real losses are deployment-layer (service-free default → Docker-required) and doc-layer (cache rebuttal dropped, no shipped recall number). No BROKEN verdicts.
Top 3: (1) Service-free DEFAULT lost — `.mcp.json:6` + `setup.sh:47-48` hard-require Docker, no skip flag [MODERATE, recoverable]. (2) OG 24-query recall eval retired as wrong-universe, replaced by an unshipped `precision_eval.py` (needs shadow collection) → no valid recall number currently published [MODERATE]. (3) Prompt-cache rebuttal (OG README:111-137) DROPPED from all fork docs [MINOR honesty loss].
