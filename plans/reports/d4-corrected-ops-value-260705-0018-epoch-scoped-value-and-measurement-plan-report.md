# D4 (CORRECTED) — Ops-Complexity & Value: epoch-scoped value + measurement plan

**Dimension:** D4 (ops-complexity & value) · **Mode:** READ-ONLY, nothing modified
**Date:** 2026-07-05 · **Trees:** fork `skill-concierge/` (v0.12.0) vs vendored OG `vendor/skill-search/` (0.1.0)
**Supersedes:** the value sections of `d4-ops-complexity-value-audit-260704-2312-servicefree-loss-vs-machinery-report.md`.
The prior "enforcement is net-negative / 10% conversion / 90% dodge" verdict was **epoch-pooled + subagent-contaminated → WITHDRAWN.**

**Ruling up front:** The ops-cost delta is **real and large** (Part A, static, unchanged). On value, the honest
verdict is **INSUFFICIENT DATA** — the whole current-epoch window is self-referential skill-concierge dev traffic,
so the enforcement layer's payoff is **UNMEASURED**, neither proven nor disproven. Of the added ops surface, the
**Qdrant server and the multilingual embedder are earned regardless of any value data**; the **per-turn enforcement
layer (enforcer.py + embed-shim sidecar + prompt_intent gate) is justified only by a value that is currently unmeasured.**

---

## PART A — OPS COST (config-independent, static)

### A.1 Install / deploy delta

**OG — service-free default** (`vendor/skill-search/README.md:161-180`)

| # | Step | Moving part | Evidence |
|---|------|-------------|----------|
| 1 | `pipx install skill-search-mcp` | one CLI, one Python env | README:166 |
| 2 | `skill-search --reindex` | embedded on-disk Qdrant (`~/.cache/…`, **no server**) | README:169 |
| 3 | `claude mcp add --transport stdio skill-search -- skill-search` | one stdio process, spawned on demand, dies with session | README:172 |
| 4 | install router skill (one `SKILL.md`) | one always-on skill | README:197 |
| 5 | `skill-search-overrides` | edits `settings.local.json` (project scope) | README:180 |

**Prereqs:** Python + pipx. **No Docker, no server, no sidecar, no background container.** Headline claim:
*"The default tier is service-free … No Docker, no server"* (`README:161-162`).

**Fork — service-heavy default** (`setup.sh`, README:79-111)

| # | Step | Moving part it adds | Evidence |
|---|------|---------------------|----------|
| 1 | `git clone` + `./setup.sh` | — | README:84-88 |
| 2 | build **stable venv** outside plugin cache, install engine **non-editable (copied in)** | a 2nd engine copy that must be re-synced every update | setup.sh:40-44 |
| 3 | run **Qdrant server** container `skill-search-qdrant` (`--restart unless-stopped`, ports 6333/6334, host volume) | a persistent container, up every session | setup.sh:49-56 |
| 4 | build + run **warm embed-shim** sidecar `skill-concierge-embed-shim` (`127.0.0.1:6363`) | a **2nd** persistent container | setup.sh:63-67 |
| 5 | `--reindex` multilingual index (+ multi-vector trigger layer) | — | setup.sh:76-77 |
| 6 | build **`prompt_intent`** actionability-gate corpus | a 3rd Qdrant collection the gate depends on | setup.sh:85-88 |
| 7 | `apply-overrides.py` → **global `~/.claude/settings.json`** | edits a global, backed-up file | setup.sh:91 |
| 8 | de-dup user-scope MCP, **restart Claude Code** | de-dup step | setup.sh (post) |
| 9 | **re-run `setup.sh` after every plugin update** | recurring deploy dependency (§11 trap) | setup.sh:101, caveats §11 |
| — | each session: `docker start skill-search-qdrant skill-concierge-embed-shim` | 2 containers to keep alive | setup.sh:103 |

**Prereqs:** Python 3.10–3.12 **and Docker/OrbStack** (`setup.sh:47-48`). Both containers are hard requirements
for the full-fidelity path.

**Delta:** ~4 stateless commands + 1 on-demand process → **~9 steps + 2 persistent containers + 3 Qdrant
collections + a global-settings edit + a re-run-on-every-update dependency.** The OG's service-free selling point
is gone; it survives only as a commented `ponytail:` note (`setup.sh:7-9`), not a supported path.

### A.2 Ongoing maintenance surface (self-verified this session)

| Burden | Cost | Evidence |
|--------|------|----------|
| **17 ADR files** | immutable-governance process | `docs/adr/` (0001–0016 + one more) = 17 files |
| **doctor.py — 13 checks** | a diagnostic tool to keep the deploy coherent | `grep -c 'def check_'` = 13 |
| **caveats.md — 11 landmines** | operator must know 11 traps, several self-inflicted | 11 `## ` sections |
| **§11 stale-engine trap** | after engine-code update, `/plugin update` refreshes cache but **not** the copied venv → MCP silently runs old code → must re-run setup | caveats §11 (self-inflicted by ADR-0004 non-editable copy) |
| **Dual-manifest bump** | `plugin.json` + `marketplace.json` bumped together or update is a silent no-op | caveats §7 |
| **Two containers to babysit** | `docker ps` must show both `Up` each session | setup.sh:103 |
| **enforcer.py = 715 LOC** | the project's single largest module, fires every `UserPromptSubmit` | `wc -l hooks/scripts/enforcer.py` = 715 |

Net: the OG's maintenance story is one self-announcing reindex guard; the fork's is a 13-check doctor, an
11-item landmine doc, a re-run-on-update ritual, a dual-manifest rule, and two containers — much of it machinery
built to contain complexity the fork itself introduced. **This part does not depend on ledger data and stands.**

---

## PART B — VALUE (data-dependent — RE-GROUNDED under the corrected discipline)

### B.1 The clean current-epoch window

Command (run this session): `python3 scripts/analyze.py --since "2026-07-04 05:32"` (v0.12.0 epoch).

```
window            : 87/1595 events   turn-windows: 29   offers: 27
fallback rate     : 9/27   33%
offered-turn conv : 5/17   29%   (offered ≥1 skill -> agent used one)
offered-turn dodge: 12/17  71%
```

The offered-turn conversion denominator is **17 real surfaced offers** (band==`offer`); the handover's
n≈14 "genuine" figure is the same order after trimming self-session noise. **Either way n ≤ 17.**

### B.2 The contamination is not noise around the signal — it *is* the whole window

I inspected every offer in the window (27 across 4 sessions). The traffic is **100% skill-concierge
meta-work** — auditing, studying the OG vendor repo, writing handoffs, session reflection, and this very audit:

- All 4 sessions are dev/audit sessions. Sample queries: *"study and analyze the original vendor repo,"*
  *"synthesize from 2 final reports,"* *"do the session handoff,"* *"update the 0.12.0 experience report,"*
  *"YOU pooled the entire ledger,"* *"add the epoch-validity caveat."*
- **9 of the 27 offers come from THIS audit session** (`sid 6dfa82e3`) — the report is polluting its own
  measurement window.
- **4 offers are literal `<task-notification>` subagent-harness events** (session `360f2c2e`), i.e. machine
  traffic, not a human deciding whether to take a skill.
- **Zero** turns in the window are organic "user has a real task, does a surfaced skill help them" traffic.

So the effective **organic-task n is ≈ 0**, not 14. A conversion rate computed on a operator-auditing-his-own-tool
window measures the auditor's behavior, not the enforcement layer's value.

### B.3 Verdict: INSUFFICIENT DATA

Per the corrected discipline (metric valid only for its epoch; exclude subagent/harness/meta + self-session;
tiny clean sample → INSUFFICIENT DATA, never pool backward): **the enforcement layer's value is UNMEASURED.**
The prior "10% / 90% / net-negative" figures were epoch-pooled across ~15 configs and subagent-contaminated —
they are withdrawn and must not be restated. There is currently **no window that can prove or disprove** whether
enforcement earns its cost.

### B.4 Measurement plan (what would actually settle it)

1. **Clean window definition.** Start = the epoch's config-freeze commit (currently `7a7da28`, 07-04 04:57;
   re-anchor on any metric-affecting commit). Never span a config change.
2. **Exclusion filter.** Drop: (a) `q` starting `<task-notification` (subagent/harness); (b) any session whose
   prompts are about skill-concierge itself (audit/dev/handoff/reflection) — grep `q` for `skill-concierge`,
   `vendor/skill-search`, `handoff`, `ledger`, `ADR`, report paths; (c) the measuring session's own `sid`.
3. **Denominator.** Count only band==`offer` turns (real surfaced offers), excluding `fallback`/`negation`/`getaway`.
4. **Organic turns needed.** A 29% point estimate on n=17 has a 95% CI of roughly ±22 pts — useless. For a
   ±10-pt CI you need **~80 clean organic offered-turns**; for a defensible ±7-pt read, **~150**. At the current
   organic rate (≈0 per audit-heavy day) that requires a deliberate **non-dev workload**: real tasks against a
   large skill catalogue, logged over a stable-config span, with the filter above applied before any rate is quoted.
5. **What to report until then:** INSUFFICIENT DATA + the raw clean n — never a rate dressed as a verdict.

### B.5 The 07-02 `embed_timeout` spike is an OPS incident, not value evidence

Per-day `embed_timeout` ran 9–20% (06-27→07-01), then spiked to ~68% on 07-02 and ~54% on 07-04. The onset is
**2 days before v0.12.0 shipped** ⇒ it does not track any config commit ⇒ it is **environmental** (shim/Docker/load),
an operational incident to triage on its own — **not** a property of the enforcement design and **not** admissible
as enforcement-value evidence. (Within the current epoch the fallback rate is 33% = 9/27; that too is a shim-health
ops signal, not a compliance signal.)

---

## PART C — RULING: is the added ops surface JUSTIFIED?

Split by whether the justification survives the value question being unmeasured.

### (a) EARNED regardless of value data — needs no ledger to justify

| Addition | Why earned | Evidence |
|----------|-----------|----------|
| **Qdrant *server*** (container) | The OG's own caveat concedes the embedded store **locks its dir to one process**; concurrent Claude sessions genuinely cannot share it. A real need the OG default cannot meet — independent of any conversion rate. | OG README embedded-store caveat; `setup.sh:49-56` |
| **Multilingual embedder** (mpnet-768) | Fixes a real EN-query→VN-skill retrieval miss — a functional capability, not a nudge. Its worth doesn't hinge on enforcement conversion (though it remains unbenchmarked on this index — caveats §1). | handover D3; `setup.sh:76` |

These two are the load-bearing justification for **going service-heavy at all**, and they hold even if
enforcement is worth nothing.

### (b) Justification DEPENDS on the enforcement value that is currently UNMEASURED

| Addition | Cost | Status |
|----------|------|--------|
| **Per-turn enforcement layer** (`enforcer.py` 715 LOC + embed-shim sidecar + per-turn latency) | 2nd container, per-`UserPromptSubmit` tax, 33% current-epoch fallback | **UNPROVEN** — value UNMEASURED (B.3). Not "net-negative" (withdrawn); simply not yet shown to earn its cost. |
| **prompt_intent actionability gate** | 3rd Qdrant collection, rebuild step, doctor check, fails-open when thin | **UNPROVEN** — its contribution to conversion is un-isolated and unmeasurable on the current window. |
| **Default-inert graveyard** (per-skill tau, deterministic routes, dominance collapse, keep-off `[]`, enrich_index) | shipped, wired, tested, **OFF** (`config/*.json = []`) | **UNEARNED (binary fact, epoch-independent)** — carried in the deploy surface for zero live effect. |
| **Self-inflicted maintenance** (§11 stale-engine, §7 dual-manifest, 13-check doctor) | governance + ritual | **MIXED** — legitimate for a real product, but a large share exists to manage complexity the fork introduced. |

**Bottom line:** The service-heavy turn is **earned for the retrieval half** (server + multilingual embedder) on
grounds that don't need the ledger. The **enforcement half** is the single heaviest addition (the 715-LOC hook +
its own container + the gate), and its justification rests entirely on a behavioral lift that the current epoch
**cannot measure** — so it is neither vindicated nor condemned; it is an **instrumented experiment whose payoff
is still pending a clean, non-dev workload window.**

---

### Unresolved
- No clean organic window exists yet; the enforcement-value question stays UNMEASURABLE until ~80–150 filtered
  non-dev offered-turns accrue under a frozen config (B.4).
- The 07-02 `embed_timeout` spike needs a separate ops root-cause (shim/Docker/load), out of D4's value scope.
- Multilingual retrieval quality is asserted, not benchmarked on the excluded-universe index (caveats §1; overlaps D3).
- ADR count is now 17 files (prior report said 16) — a new ADR landed since; cosmetic, flagged for accuracy.

**Status:** DONE
**Summary:** Ops-cost delta is real and large (2 containers + ~9 steps + re-run-on-update vs OG's ~4 stateless
commands); the entire v0.12.0 epoch window is self-referential dev/audit traffic (9 offers from this very session,
0 organic), so enforcement value is INSUFFICIENT DATA — UNMEASURED, not net-negative.
**Ruling (1 line):** Qdrant server + multilingual embedder are EARNED regardless of value data; the per-turn
enforcement layer is justified only by an enforcement value that is currently UNMEASURED — measure it with an
~80–150 clean organic offered-turn window under frozen config, subagent/meta/self-session filtered out.
