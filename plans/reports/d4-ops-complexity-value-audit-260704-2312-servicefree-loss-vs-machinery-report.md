# D4 — Ops-Complexity & Value Audit: service-free loss vs machinery

**Dimension:** D4 (ops-complexity & value) · **Mode:** READ-ONLY, nothing modified
**Date:** 2026-07-04 · **Trees:** fork `skill-concierge/` (0.12.0) vs vendored OG `vendor/skill-search/` (0.1.0)
**Central question:** Is the fork's added operational surface JUSTIFIED by measured value, or has it
traded the OG's drop-in, service-free simplicity for machinery whose payoff is unproven?

**Ruling up front: PARTIALLY justified.** Two of the fork's heavy additions are *earned* (a Qdrant
**server** the OG's own caveat admits the embedded store can't do concurrently; a multilingual embedder
that fixes a real EN-query→VN-skill miss). The rest — the per-turn **enforcement tax** (a second Docker
sidecar + a 715-line hook on every prompt) — is *unearned by its own numbers*: the live ledger measures
**10% offered-turn conversion / 90% dodge / 33% fallback** after all of it. Value is **MEASURED, and the
measurement is poor** on the only workload we have.

---

## 1. Install / deploy cost delta (OG vs fork)

### The OG (service-free default) — `vendor/skill-search/README.md:159-198`

| # | Step | Moving part it adds |
|---|------|---------------------|
| 1 | `pipx install skill-search-mcp` | one CLI, one Python env |
| 2 | `skill-search --reindex` | embedded on-disk Qdrant at `~/.cache/...` (no server) |
| 3 | `claude mcp add --transport stdio skill-search -- skill-search` | one stdio process, spawned on demand |
| 4 | install router skill (`curl` one `SKILL.md`) | one always-on skill |
| 5 | `skill-search-overrides` | edits `settings.local.json` (project scope) |

**Prerequisites:** Python + pipx. **No Docker. No server. No sidecar. No background container.**
One process, spawned by Claude Code, dies with the session. Embedded ONNX embedder downloads once, then
offline (README:161-163).

### The fork — `setup.sh`, `README.md:79-111`, `docs/caveats.md`

| # | Step (from `setup.sh`) | Moving part it adds | Evidence |
|---|------------------------|---------------------|----------|
| 1 | `git clone` + `./setup.sh` | — | README:84-88 |
| 2 | build **stable venv** outside the plugin cache, `pip install` the vendored engine **non-editable (copied in)** | a second engine copy that must be re-synced on every update | setup.sh:40-44 |
| 3 | run **Qdrant server** Docker container `skill-search-qdrant` (`--restart unless-stopped`, ports 6333/6334, host volume) | a persistent container that must be up every session | setup.sh:46-56 |
| 4 | build + run **warm embed-shim** Docker sidecar (`skill-concierge-embed-shim`, `127.0.0.1:6363`) | a *second* persistent container | setup.sh:58-72 |
| 5 | `--reindex` the multilingual index (+ multi-vector trigger layer) | — | setup.sh:74-83 |
| 6 | build the **`prompt_intent`** actionability-gate corpus from the transcript store | a third Qdrant collection the gate depends on | setup.sh:85-88 |
| 7 | `apply-overrides.py` → **global `~/.claude/settings.json`** (32-skill keep-on) | edits a global, backed-up file | setup.sh:90-91 |
| 8 | remove any user-scope `skill-search` MCP, **restart Claude Code** | de-dup step | setup.sh:97-100 |
| 9 | **re-run `setup.sh` after every plugin update** to refresh the stale venv engine | recurring deploy dependency (see §11 trap) | setup.sh:101, caveats §11 |
| — | each session: `docker start skill-search-qdrant skill-concierge-embed-shim` | two containers to keep alive | setup.sh:102-104 |

**Prerequisites:** Python 3.10–3.12 **and Docker/OrbStack** (README:67-77). Both containers are *hard*
requirements for the full-fidelity path; a Qdrant outage degrades to mandate-only (caveats §3), a shim
outage spikes latency and pushes the enforcer to fallback (caveats §9).

**Delta:** ~4 stateless commands + 1 on-demand process → ~9 steps + **2 persistent Docker containers +
3 Qdrant collections + a global-settings edit + a re-run-on-every-update deploy dependency**. The OG's
headline selling point — *"the default tier is service-free … No Docker, no Ollama, no server"*
(README:161-163) — is gone. The fork is **service-heavy by default**; the service-free tier survives only
as a commented `ponytail:` note (setup.sh:7-9), not a supported path.

---

## 2. Ongoing maintenance surface the fork created

| Burden | What it costs the operator | Evidence |
|--------|----------------------------|----------|
| **16 ADRs** | governance process: accepted ADRs are immutable, changes must supersede | `docs/adr/` (0001–0016), README:322-324 |
| **doctor.py — 13 checks** | a whole diagnostic tool to keep the deployment coherent; itself a thing to maintain | `scripts/doctor.py:468-470` (13 `check_*`) |
| **`docs/caveats.md` — 11 landmines** | an operator must know 11 traps, several self-inflicted | caveats §1-§11 |
| **The §11 stale-engine trap** | after any engine-code update, `/plugin update` refreshes the *cache* but **not** the copied venv engine → MCP silently runs old code; must re-run `setup.sh`. A self-inflicted cost of choosing a non-editable copy (ADR-0004) | caveats §11, doctor.py:165-191 |
| **Dual-manifest version bump** | `plugin.json` + `marketplace.json` must be bumped *together* or the update is a silent no-op | caveats §7, README:324-325 |
| **`auto_reindex.py` self-heal** | a SessionStart hook exists *because* re-index-on-change was a chronic manual burden | caveats §6, ADR-0014 |
| **Two containers to babysit** | `docker ps` must show both `Up` each session; doctor `--fix` restarts them | caveats §3, §9 |
| **33% fallback rate observed** | the shim is failing its job (see §3) a third of the time — a live maintenance signal, not hypothetical | live ledger (§3 below) |
| **~4,000 LOC of scripts+hooks** | `scripts/*.py` = 3,042 LOC across 14 files; `hooks/scripts/*.py` = 974 LOC; `enforcer.py` alone = **715 lines** vs the OG's lean `server.py`+`skills_discovery.py`+`generate_overrides.py` | `wc -l` (measured this session) |

Net: the OG's maintenance story is *"reindex on change; it's incremental and cheap; drift is surfaced"*
(README:279-281) — one guard, self-announcing. The fork's is a 13-check doctor, an 11-item landmine doc,
a re-run-on-update ritual, a dual-manifest rule, and two containers — much of it machinery built to
*contain the complexity the fork itself introduced.*

---

## 3. Value proof — is the added layer's payoff MEASURED or roadmap-pending?

The fork's own `scripts/analyze.py` reads the live ledger. I **ran it this session** against the real log
(`~/.claude/skill-telemetry/logs/skill-invocation-ledger.log`, 1,541 events, 614 turn-windows). The enforcement
layer is not un-measured — it is measured, and the numbers are weak on this workload:

```
uptake            : 117/614  19%   (turn used a skill)
dodge             : 383/614  62%   (no skill, no search)
hit@k             : 33/81    41%   (used skill was in the offered set)
fallback rate     : 178/534  33%   (mandate-only: embed/qdrant down or slow)
offered-turn conv : 32/311   10%   (offered ≥1 skill → agent used one)
offered-turn dodge: 279/311  90%   (offered yet none used — the compliance gap)
```

Read that against what each organ *promises*:

- **Enforce** exists to kill the dodge. On turns where it *actually surfaced a skill*, the agent still
  ignored the offer **90% of the time** (`offered-turn dodge 279/311`). Conversion is **10%**. The whole
  per-turn tax — a second container + a 715-line hook on every `UserPromptSubmit` — buys a 1-in-10 take
  rate on this workload.
- **The warm-shim sidecar** exists to embed fast so the gate can fire. It **fell back to mandate-only on
  33% of offers** (`fallback 178/534`) — i.e. a third of the time the extra container isn't doing its job,
  which is exactly the caveats §9 failure mode, observed live.
- **Retrieve** (hit@k) is a mediocre **41%** — when a skill was both offered and used, it was the right
  one 41% of the time. (Not directly comparable to the OG's 0.67 recall@1, which was measured on a valid
  labelled set the fork admits it never re-ran — caveats §1, handover "no valid benchmark exists.")
- The per-skill rows show the noise: `agentmemory:session-history` offered **33× taken 0×**, `review-docs`
  24×/0, `skill-search` 20×/0, `hooks-audit` 20×/0. The menu is repeatedly pushing skills nobody takes.

**Caveat on the caveat (fair reading):** this is a *single-operator dev-workbench* workload — heavy on
meta/skill-concierge-development turns, conversational turns, and agentmemory chatter, not the "hundreds
of production skills, real task" scenario the approach is designed for. So 10% partly reflects *workload
mismatch*, not only *layer failure*. But that cuts toward the ruling, not away: **the fork pays the fixed
per-turn cost on every workload, and on the only workload with data the benefit is near-zero.**

**The form-vs-behavior gap the fork itself found** (`0.11.0`, README:279-283; CHANGELOG:69): a 5-day
transcript analysis showed high *token-form* compliance but far lower *behavioral* compliance. The
literal figures now read `n%` placeholders in-repo, but the finding is the fork's own: the agent *says*
the mandate and *doesn't act* on it. The remaining "open question" (README:294-300) concedes the
longitudinal lift on the hardest behavior *"still needs a post-0.11.0 workload window to accrue"* —
**i.e. the strongest value claim is explicitly roadmap-pending, by the fork's own admission.**

Verdict on value proof: **the retrieval swap is plausibly earned but unbenchmarked; the enforcement layer
is measured and currently under-delivering; the decisive longitudinal proof is pending.**

---

## 4. The tail-scale premise — for whom does the fork clear?

The OG is explicit (README:19-22, 285-286): the approach *"pays off once you have a lot of skills —
roughly hundreds. With only a handful … you don't need the extra round-trip. Overkill at a handful."*
That calculus governs the **Retrieve** half: retrieval's benefit **scales with skill count** (context
reclaimed grows with the catalogue), while its cost is a fixed per-turn round-trip.

The fork stacks **Enforce** on top — and Enforce's cost/benefit does **not** follow the same curve:

- **Enforce's cost is fixed per turn**, independent of skill count: every `UserPromptSubmit` pays the
  embed-shim round-trip + the actionability gate + the mandate injection (README:234-248). More skills
  don't make the hook cheaper.
- **Enforce's benefit is a behavioral nudge**, capped by the model's willingness to obey — and the plan
  itself names the ceiling: *"Soft-enforcement ceiling: relevant candidates raise compliance but can't
  guarantee"* (`docs/plan.md:199`). The live 90% offered-turn dodge is that ceiling, observed.

So the fork does **not** improve the OG's tail-scale calculus — it **adds a fixed cost on top of it**.
Where the OG says "overkill at a handful, worth it at hundreds," the fork's honest version is: *retrieval
still needs hundreds of skills to clear; enforcement adds a flat per-turn tax that clears only if the
behavioral lift is real — and the one workload we can measure puts that lift at ~10% conversion / 33%
shim-fallback.*

**For whom does it actually clear today?** A single operator with hundreds of skills who (a) values the
concurrent-session Qdrant server, (b) is on the multilingual (EN↔VN) use case the embedder swap fixes,
and (c) is willing to run the enforcement layer as an *instrumented experiment* whose payoff is not yet
proven. That is the author's own machine — and the README frames the project as pre-1.0, "first real
evidence," longitudinal-proof-pending. It does **not** clear for a drop-in user who wanted the OG's
service-free simplicity.

---

## Cost / benefit ledger — earned vs unearned

| Addition | Cost | Earned? | Why |
|----------|------|---------|-----|
| **Qdrant *server*** (container) | 1 persistent container, Docker prereq | **EARNED** | OG's own caveat: *"Embedded Qdrant locks its dir to one process"* (README:282-284). Concurrent Claude sessions genuinely need the server. Real need the embedded store can't meet. |
| **Multilingual embedder** (mpnet-768) | larger model, re-index | **EARNED (functional)** | Fixes real EN-query→VN-skill misses (handover, VENDORED.md). A capability, not ceremony — though unbenchmarked on this index (caveats §1). |
| **Stable venv (non-editable copy)** | §11 stale-engine trap, re-run setup on every update, engine-freshness doctor check | **PARTIALLY earned** | Surviving cache-wipes is a real goal (ADR-0004), but the *non-editable copy* choice self-inflicts §11; an editable install off the deployed source would remove the whole stale-engine class. Cost is self-created. |
| **Per-turn enforcement layer** (enforcer.py 715 LOC + embed-shim sidecar + prompt_intent gate) | 2nd container, per-turn latency budget, 33% observed fallback, §9 landmine, 715-line hook | **UNEARNED (by its own numbers)** | Live ledger: 10% offered-turn conversion, 90% dodge, 33% shim fallback. Fixed cost, near-zero measured benefit on this workload; decisive proof self-declared pending. |
| **prompt_intent actionability corpus** | 3rd Qdrant collection, rebuild step, doctor check, fails-open when thin | **UNEARNED / unproven** | Adds a suppression gate whose contribution to the 10% conversion is un-isolated; fails-open silently (caveats, doctor.py:317-337). |
| **Default-inert graveyard** (per-skill tau, deterministic routes, dominance collapse, keep-off `[]`, enrich_index) | shipped, wired, tested, OFF; doctor checks reference them | **UNEARNED** | Dead weight carried in the deploy surface for zero live effect (handover D2 overlap). |
| **16 ADRs / 11 caveats / dual-manifest rule / doctor-13** | governance + docs overhead | **MIXED** | Legitimate for a real product; but a large share exists to *manage complexity the fork itself introduced* (§11, §7, §3, §9 are all self-inflicted). |

---

## Ruling

**PARTIALLY justified.** The service-heavy turn is earned *only* for the concurrent-session Qdrant server
and the multilingual embedder — genuine needs the OG's embedded/EN-only defaults can't meet, and the OG's
own caveats concede the first. Everything the fork layered on *top* of retrieval — the per-turn
enforcement tax and its second container, the prompt_intent gate, the inert graveyard, and the
self-inflicted §11/§7 maintenance rituals — is **not paid for by measured value.** The fork traded the
OG's drop-in, service-free, one-process simplicity for two persistent containers and ~4,000 LOC of
governance machinery, and its own live telemetry scores that machinery at **10% conversion / 90% dodge /
33% fallback.** Value is **MEASURED, not roadmap-only — and the measurement is currently negative-to-flat**;
the one claim that could redeem it (longitudinal behavioral lift) is, by the fork's own README, still
pending.

**Single heaviest unearned cost:** the **per-turn enforcement tax** — the warm-embed-shim Docker sidecar
plus the 715-line `enforcer.py` hook firing on every `UserPromptSubmit` — a whole second service and the
project's largest single module, whose own ledger measures a **10% take rate, 90% dodge, and 33%
self-fallback.** It is the biggest addition, the biggest operational liability (caveats §9), and the one
with the weakest measured return.

---

### Unresolved
- The 10% conversion conflates *layer under-performance* with *dev-workbench workload mismatch*; only a
  production-skill workload window (the fork's own "open question") can separate them.
- `hit@k 41%` has no valid baseline — the OG's 0.67 recall@1 was never re-run on this excluded-universe
  index (caveats §1), so the retrieval swap's real quality is asserted, not proven (overlaps D3).
- Container naming drift: setup.sh names the shim `skill-concierge-embed-shim`; caveats §9 calls it
  `skill-search-embed-shim` — cosmetic, but a doctor/ops-doc mismatch worth a one-line fix.

**Status:** DONE
**Summary:** Fork replaced the OG's service-free one-process install with 2 persistent containers + ~4,000
LOC of governance; earned only the Qdrant server + multilingual embedder, and its own live ledger scores
the added enforcement layer at 10% conversion / 90% dodge / 33% fallback.
**Ruling:** PARTIALLY justified — heaviest unearned cost = the per-turn enforcement tax (embed-shim
sidecar + 715-line enforcer.py) with a measured 10% take rate.
