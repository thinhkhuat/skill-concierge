# Skill Governance Layer — skill-search × skill-first Fusion

**Status:** P1 COMPLETE — warm embed shim + enforcer hook built · verified (90ms timeout, cosine parity 1.000000, fallback tested). Ledger + enforcer both ready. **HELD, owner-gated go-live** (old skill-first-nudge hook still in ~/.claude/settings.json; cached plugin has ledger only). Go-live = deregister old hook (backup first) → marketplace bump → full plugin install.
**Date:** 2026-06-26
**Owner context:** workbench; live global hook + Qdrant MCP deployment (see session memory [[skill-first-vs-skill-search-purpose]])

## Goal

Fuse the two mechanisms into ONE skill-governance layer over Claude Code's default
("dump every skill description + hope the model picks"):

- **skill-search** (MCP, semantic, Qdrant + mpnet-768) = **WHICH** skills — retrieval.
- **skill-first** (UserPromptSubmit hook) = **WHETHER** Claude uses skills — enforcement.

The two are orthogonal, not competing. The only real conflict is the hook's *rushed*
second job — lexically ranking + echoing skill names with a weaker engine and a
separate, drifting catalogue. **Phase 1 retires that:** the enforcer sources its
per-turn candidates from the SAME semantic index, then enforces use over them.

> Doorman/library: skill-search is the library; skill-first is the doorman who makes
> the model walk in every turn, hands it the few books that actually fit
> (semantically, not by spine-title), and won't let it leave a real task without
> having opened one.

## The crux (why this is not "delete score(), call Qdrant")

The hook fires on EVERY prompt from a COLD process and must stay fast (~71ms today,
stdlib-only — handoff-verified). Semantic retrieval = embed(query) + Qdrant search.
Qdrant search is ms; embedding the query needs the **mpnet-768** model, and
cold-loading it per prompt is **seconds-scale** — categorically over the per-turn
budget. The query MUST be embedded with the SAME model the index was built with
(`sentence-transformers/paraphrase-multilingual-mpnet-base-v2`) or vectors are
incomparable.

=> **Phase 1's real deliverable is a WARM embedding endpoint** serving that exact
model, that the cold hook can hit in ~tens of ms.

### Embedder-warmth decision (DECIDED: A + hard timeout→fallback — owner-approved 2026-06-26)
- **A (CHOSEN):** tiny persistent **fastembed-mpnet HTTP shim** on localhost,
  sidecar to the existing Qdrant container. Serves the SAME model → **current index
  stays valid, no rebuild.** One small long-lived service. Rationale: preserves the
  just-built index; B's only gain (daemon consolidation) isn't worth a full rebuild +
  parity re-validation.
- **B:** switch embedder to an **Ollama**-served multilingual model (Ollama is already
  a warm daemon). Cost: rebuild the index on that model + re-validate retrieval parity.
- **C (reject):** accept cold-load latency — a multi-second per-turn hook is unacceptable UX.

## Design (Phase 1)

1. **Warm embed endpoint** (approach A): persistent process holding mpnet; `POST {text}`
   → vector. Health-checkable. Auto-start (launchd or Docker sidecar next to Qdrant).
2. **Hook rewrite** (in `skill-concierge/hooks/` — this plugin; supersedes the old `hooks-dev/skill-first-nudge/` location):
   - Non-trivial prompt → POST query to embed endpoint → vector → Qdrant top-k →
     inject **enforcement mandate + semantic candidates** (name, desc, score).
   - **Retire** `score()` / `_tokens()` / `_fold()` / `_distinct_hits()` and the
     `library.json` ledger read. Keep: trivial-getaway gate (cheap fire/skip),
     fail-SILENT, additive-only, empty/slash suppression.
   - **Fallback (resilience + BUDGET ENFORCEMENT):** inject the existing **MANDATE-only**
     text (never silence, never crash) on ANY of: (a) embed endpoint unreachable,
     (b) Qdrant unreachable, (c) **embed call exceeds a hard client-side timeout (~120ms)**.
     (c) is the load-bearing add: "unreachable" checks miss an **up-but-slow** shim (GC pause,
     cold page, contention) that would otherwise silently tax every prompt with no trigger.
     The timeout is **client-enforced** (stdlib `urllib` socket timeout on the POST), so the
     hook returns within budget regardless of shim state — the ≲150ms budget is ENFORCED, not
     hoped. ~120ms leaves headroom for the Qdrant search + overhead on top; tunable constant.
3. **Catalogue unification:** single source = the MCP's `discover_skills()` / Qdrant
   index. `library.json` retired → kills the 585-vs-508-vs-512 drift.
4. **Skill-invocation ledger (lightweight, COMPOUNDING — build FIRST).** Append-only
   event ledger + one analyzer, no DB. Every event tagged by `ev`:
   - **offer** (UPS hook, at injection): `{t, sid, ev:offer, band, offered:[[name,score]…], fallback, q:<prompt≤120c>}`.
   - **manual** (UPS hook, when the user typed a `/skill` — it currently early-returns on
     `/`; add a log line before returning): `{t, sid, ev:manual, name}`. Captures the
     owner's hand-invocations **independent of** whether PostToolUse fires for user slashes.
   - **auto / search** (PostToolUse on the `Skill` tool and on
     `mcp__skill-search__search_skills`): `{t, sid, ev:auto|search, name}` — Claude's
     autonomous uptake.
   - **Tagging keeps the metric honest:** `auto` = the doorman worked; `manual` = the
     owner drove it. Never let `manual` inflate the hook-effectiveness number.
   - **Analyzer** (`analyze.py`): segment by `sid` + offer boundaries → **offer rate**,
     **uptake rate** (offered → `auto` fired), **hit@k** (auto-invoked ∈ offered set),
     search-call rate, **dodge rate** (substantive offered turn, nothing fired),
     fallback rate; PLUS per-skill rollups (auto freq, manual freq, breadth,
     offered-but-never-taken) feeding always-on curation.
   - **Storage = compounding, never discarded.** ONE append-only
     `skill-invocation-ledger.log` (JSONL content) in a logman-detectable `logs/` dir:
     `~/.claude/skill-telemetry/logs/`. NO self-rotation, NO cap, NO deletion. Prompt
     truncated ≤120c (not hashed).
   - **Downstream owner = logman** (github.com/thinhkhuat/logman): auto-detects
     `logs/*.log`, archives into compressed snapshots. ⚠ **logman default
     `RETENTION_DAYS=90` DELETES old archives** — for this ledger it MUST run
     `RETENTION_DAYS=0` (unlimited), or the compounding data is lost after 90 days.
     logman wiring is a LATER step; the `.log`/`logs/` shape makes it drop-in.
   - **Build FIRST**, run on the CURRENT lexical hook to bank a **BASELINE** → fusion lift
     measured before/after, not asserted.
   - Caveat: verify the exact `Skill`/slash PostToolUse event shape at build — the UPS-hook
     `manual` capture is the robust fallback if user slashes don't fire PostToolUse.

## What the ledger decides (data-backed, not by reasoning)

1. **Did the fusion work?** uptake↑ / dodge↓ before-vs-after the rewrite; the P2
   "build teeth?" call fires off the real **dodge rate**, not a hunch.
2. **Always-on membership, precisely.** Per-skill evidence replaces judgment:
   - **Promote → always-on:** high auto+manual frequency × cross-session breadth
     (skills the owner keeps invoking BY HAND = strongest signal).
   - **Demote → name-only:** in the always-on set but ~never invoked = paying
     description tax for nothing.
   Recomputes the Tier-1/2/3 always-on list from data, on a cadence — not a one-off guess.

## Phases

- **P1 — Fusion (this plan):** (0) **telemetry first** (offer + uptake logging +
  analyzer) → bank a current-hook baseline; then warm embedder + hook rewrite +
  fallback + retire lexical/ledger. Dogfood on real transcripts, then install.
- **P2 — Deferred (NOT now):** read the **dodge rate** from the evidence loop; if soft
  enforcement still leaks, add a **hard gate** (Stop/PostToolUse skill-worthiness check)
  — the classifier. Model-judgment-first per owner direction; build teeth only when the
  logged data shows the need.

## Acceptance (P1)

- [ ] Per-turn hook latency within budget with the warm endpoint (measure; target ≲150ms).
- [ ] Hard client-side embed timeout (~120ms) enforced: a deliberately-slowed shim falls
      through to mandate-only and the turn still completes ≲150ms (verified with an injected delay).
- [ ] Hook injects SEMANTIC top-k — verified by an EN query surfacing a VN-described
      skill the old lexical scorer missed (the "janky UI on mobile" → `responsive-design`
      class of query).
- [ ] Embed endpoint / Qdrant DOWN → mandate-only fallback fires (no silence, no crash).
- [ ] `library.json` no longer read; one catalogue; counts reconcile to the index.
- [ ] Safety contract intact: fail-silent, never-blocks, empty/slash suppressed.
- [ ] Ledger logs offer + manual + auto + search events (tagged by `ev`); manual
      `/skill` invocations captured distinctly from auto.
- [ ] Analyzer prints offer / uptake / hit@k / dodge / fallback + per-skill rollups.
- [ ] Ledger is ONE append-only `.log`, compounding — never self-rotated/capped/deleted;
      logman-detectable; documented to run logman with `RETENTION_DAYS=0`.
- [ ] Baseline captured on the CURRENT lexical hook before the fusion lands
      (so before/after is comparable).

## Rollout (matches how the originals were built)

Dev local-first in `skill-concierge/` (this plugin) → self-test + `code-reviewer`/`tester`
subagents → owner review → take live via EITHER (a) registering hooks in
`~/.claude/settings.json` (fast baseline) OR (b) full plugin install (marketplace add +
`/plugin install`, uses `hooks.json` as-is). Back up settings before either. Component-building
Rule A: never write the install path without an explicit per-step OK.

## Build log

**2026-06-26 — P1 fusion complete: warm embed shim + enforcer hook (HELD, owner-gated go-live).**
- **Warm embed shim:** `scripts/embed_server.py` (stdlib http.server, mpnet-768 in memory; POST /embed, GET /health); `bin/embed-shim` (host launcher); Dockerfile + .dockerignore (Docker sidecar next to skill-search-qdrant container, 127.0.0.1:6363); `setup.sh` builds/runs the sidecar. Parity verified: cosine 1.000000 vs index-build path (EN + VN). **Timeout calibration:** design nominal ~120ms breached cold-start budget (~50ms python) with co-equal ≲150ms per-turn; measured p95 3.75x headroom → set ENFORCER_EMBED_TIMEOUT=90ms (env-overridable, client-side hard timeout via urllib socket). Verified: deliberately-slowed shim falls through to mandate-only, turn ≲150ms.
- **Vendor lock:** `vendor/skill-search/pyproject.toml` fastembed pinned ==0.8.0 (was >=0.3). Version 0.5.1 switches mean→CLS pooling, silently corrupts retrieval. The live index built on 0.8.0 — pinning guarantees rebuild-free reproduction.
- **Enforcer hook:** `hooks/scripts/enforcer.py` (UserPromptSubmit); embeds prompt via shim (90ms timeout), Qdrant top-k via raw urllib, injects mandate + semantic candidates (name, desc, score). Retire `score()`/`_tokens()`/`_fold()`/`_distinct_hits()` + `library.json` read. Keep: fail-silent/additive/never-blocks, empty/slash suppression. Fallback on embed-down/timeout/qdrant-down → mandate-only (tagged telemetry). Cheap pre-gate (empty/slash/≤2-word).
- **Registry:** `hooks/hooks.json` registers enforcer.py alongside ledger.py (not yet installed; settings.json registration or full plugin install pending). Ledger and enforcer both registered, both fire.
- **Telemetry:** `scripts/analyze.py` repointed off library.json → Qdrant index (stdlib scroll). Reports hit@k + fallback rate + bands from `offer` events. ledger.py logs stripped q so offer↔turn join works.
- Status: DONE (design + code + verification); owner-gated go-live. Old lexical hook (skill-first-nudge.py) still registered in ~/.claude/settings.json; cached plugin (0.1.0/0.1.1/0.1.2) still has ledger.py only. No double-injection today. Go-live = deregister old hook (backup first) THEN marketplace bump + full plugin install.

**2026-06-26 — Ledger slice (P1 step 0) — built, HELD local (not installed).**
- Files: `hooks/scripts/ledger.py` (UPS `turn`/`manual` + PostToolUse `auto`/`search`; fail-silent, additive-only, stdlib), `hooks/hooks.json` (plugin wrapper; UPS + PostToolUse matcher `Skill|mcp__skill-search__search_skills`), `scripts/analyze.py` (uptake/search/dodge + per-skill rollups).
- Event shape grounded in official `hooks.md`: PostToolUse carries `tool_name`/`tool_input`/`session_id`; Skill→`tool_name:"Skill"`; UPS→`prompt`. The Skill `tool_input` field is undocumented → capture `input_keys` (no assumption; learn the real field from live data).
- `code-reviewer`: contract met (fail-silent/additive/compounding/no-assumption); 2 metric should-fixes applied → **H1** manual split real-skill vs built-in via the live catalogue (NOT a log-time denylist); **H2** empty-prompt skip + `turn`-denominator caveat. `tester`: 13/13 pass. Re-verified green. Reports: `plans/reports/{code-review,test}-260626-ledger-slice.md`.
- Carried forward: **hit@k** pending `offer` events from the enforcer hook; manual split uses interim `library.json` (unify to Qdrant per Design §3); open Q — do subagent `Skill` calls share the parent `session_id` (could inflate uptake)? verify at install.
- HELD: hooks not registered (owner choice). Go-live later via settings.json registration (fast) or full plugin install. Baseline gathering starts only once live.

**2026-06-26 — Vendored the skill-search engine (self-contained / portable migration).**
- `vendor/skill-search/` ← upstream source: `skill_search/{server,skills_discovery,generate_overrides,__init__}.py` + `tests/` + `eval/{run_eval.py,labeled_queries.jsonl}` + `scripts/measure_tokens.py` + `pyproject.toml` + `README.md` + `LICENSE`. MIT + attribution preserved; `vendor/skill-search/VENDORED.md` records upstream + the local customization layer. Engine `py_compile`-verified intact.
- Router skill → `skills/skill-search/SKILL.md`; ops docs → `docs/` (deployment-readme + trial-setup report).
- Portable-vs-runtime: source is in-tree; Python deps + Qdrant + model + index + `settings.json` overrides are reproduced by the setup layer (next slice), not embedded.
- NEXT (reproduction layer slice): `.mcp.json` (run vendored server via a plugin-local `vendor/.venv`; env = `SKILL_QDRANT_URL` + fastembed mpnet); a setup script (venv+deps → Qdrant container → build index → apply overrides); an override-policy applier writing `settings.json` keep-ons (NOT upstream `skill-search-overrides`, which reverts them). Found bonus: `eval/labeled_queries.jsonl` exists → wires the deferred recall@k eval.

**2026-06-26 — Reproduction layer built, HELD local (not run).**
- `.mcp.json` registers the vendored `skill-search` MCP (run via plugin-local `vendor/.venv`; env = Qdrant URL + fastembed mpnet = single source of truth for the embedder).
- `setup.sh` (idempotent): Python 3.10–3.12 pick → venv + editable install → Qdrant container (daemon-prechecked) → `--reindex` build → `apply-overrides.py`. Model/URL read FROM `.mcp.json` so the built index can't diverge from the live MCP.
- `scripts/apply-overrides.py`: curated name-only overrides → `settings.json` (NOT settings.local.json); **atomic** (temp + `os.replace`), backs up first, preserves other keys, refuses empty/invalid keep-on, UTF-8.
- `config/keep-on.json`: snapshot of the live 31-skill keep-on policy.
- `code-reviewer` (DONE_WITH_CONCERNS) + `tester` (7/8) → all applied: **B1** atomic write (blocker), backup collision (pid stamp), **S3** keep-on validation + router-dark warn, **S4** model-from-`.mcp.json`, **S5** Python-version pick, **S1** go-live de-dup note (`claude mcp remove skill-search -s user`), **S2** setup-before-enable note, docker-daemon precheck, `--reindex`. Re-verified green. Reports: `plans/reports/{code-review,test}-260626-reproduction-layer.md`.
- HELD (Rule A): `setup.sh` NOT executed; live `settings.json` / MCP registration untouched. Go-live = run `setup.sh` → `claude mcp remove skill-search -s user` → restart Claude Code.

**2026-06-26 — Published + MCP brought online + docs/ADR set.**
- Published → github.com/thinhkhuat/skill-concierge. Versions 0.1.0 → 0.1.1 (MCP launcher + stable venv fix) → 0.1.2 (router keep-on). MCP verified connected (`search_skills` answers); engine healthy (509 indexed, dim 768). See `CHANGELOG.md`.
- **Decision rationale extracted into `docs/adr/` (0001–0006)** + a loud `docs/caveats.md` (landmines) — so the design intent stops living only in code comments.
- **Correction (session finding):** ran the vendored `eval/labeled_queries.jsonl` and got recall@k ≈ 0.08 — then proved it **invalid here**: its ground truth targets skills NOT in this index (upstream plugins + built-in commands), which ADR-0001 excludes by design. recall@k says nothing about retrieval quality on this deployment. This **un-decides** ADR-0002's "retire the lexical scorer" — it was never evidence-backed. A real eval needs ground truth from the indexed catalogue only. Captured in ADR-0001/0002, `caveats.md` §1, `eval/README-LOCAL.md`, and memory [[skill-search-indexes-model-invocable-only]].

**2026-06-26 — 0.2.0: maintenance skills (`setup` + `doctor`).**
- `skills/setup/SKILL.md` → `skill-concierge:setup`: wraps the idempotent `setup.sh` bootstrap + verifies. `skills/doctor/SKILL.md` → `skill-concierge:doctor` + `scripts/doctor.py`: pure-stdlib deployment healthcheck (venv / MCP wiring / Qdrant / overrides / ledger), **delegates** retrieval health to the engine's `skill-search --health`; `--fix` does only safe/fast repairs (docker start + readiness poll → reindex → re-apply overrides). Heavy bootstrap stays in `setup.sh`.
- Both skills declare `name:`=dir (proven registration pattern, 158/159 cache skills) with single-line descriptions (engine parses frontmatter by regex, not YAML). Versions bumped 0.1.2 → **0.2.0** (plugin.json + marketplace.json). Rationale → **ADR-0007**.
- Verified: `py_compile` + `doctor.py --selftest` green; live `doctor.py` ran end-to-end (correctly flagged stale-index + duplicate-MCP). HELD per Rule A — written in workbench source, NOT installed; live slash registration unverified until reinstall.

## Risks / open

- Warm service = a new always-on dependency (like Qdrant). Mitigated by the
  mandate-only fallback (outage degrades, never breaks).
- Embedder-warmth A/B gates the infra shape — A unless owner prefers B's
  single-daemon consolidation.
- Soft-enforcement ceiling: relevant candidates raise compliance but can't guarantee
  it; P2 teeth deferred by design — measure first.
- Override-generator landmine: `generate_overrides.py` targets `settings.local.json` with a
  2-item keep-on default → a rerun would nuke the curated always-on set. Guard before any
  override regen. **Now documented in ADR-0005 + `caveats.md` §2.**
