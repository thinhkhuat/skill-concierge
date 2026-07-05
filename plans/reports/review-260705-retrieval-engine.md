# Review: Semantic Retrieval Engine (skill-search MCP)

Reviewer B — grounded, read-only. Root: `/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge`.
All claims below carry `path:line` + verbatim quote. Live Qdrant at `localhost:6333` was probed
read-only (`GET`/`POST .../points/count`) to corroborate document claims against the running index;
the isolated pytest run below uses the tests' own temp Qdrant (`vendor/skill-search/tests/conftest.py:19`
`SKILL_QDRANT_PATH`), not the live collection — confirmed before running so the live index was never at risk.

## 1. What it actually does (pipeline trace)

**Discovery (`skills_discovery.py`).** `discover_skill_paths()` (`skills_discovery.py:150-157`) globs
personal (`~/.claude/skills`), project (`./.claude/skills`), and installed-plugin-cache SKILL.md files.
`parse_skill()` (`skills_discovery.py:107-147`) extracts `name`, `description` (+ `when_to_use`
appended), a 4000-char-capped `body`, and — new in ADR-0016 — `body_triggers` extracted from the
**uncapped** full body via `_extract_body_triggers` (`skills_discovery.py:75-104`, comment at
`:140-145`: *"Extracted from the FULL body (not the 4000-char-capped copy above) so a decision section
late in a long SKILL.md still refreshes its trigger points"*). `discover_skills()` dedupes by name,
personal-wins-over-project (`skills_discovery.py:160-167`).

**Index build (`server.py:build_index`, `:353-411`).** For each skill: one `kind="base"` point
embedding `name+description+body` (`_skill_text`, `:296-298`) — payload includes `path` for `get_skill`
lookups. When `MULTIVECTOR` is on (default, `:82`), also one `kind="trigger"` point per phrase from
`_trigger_phrases(s)` (`:276-293`): description phrases first (`_split_phrases`, `:258-273`), then
(if `SKILL_BODY_TRIGGERS`, default on, `:88`) body phrases deduped against the description, all capped
COMBINED at `_TRIG_MAX=12` (`:293` `return phrases[:_TRIG_MAX]`). Point ids are stable per
`(skill, slot)` (`_point_id`, `:237-240`), so reindex is incremental: only changed content-hashes
re-embed (`:393`), and points whose skill vanished are deleted (`:394`, `:404-406`).

**Query (`search_skills`, `:432-462`).** Embeds the query, then
`_qdrant.query_points_groups(group_by="name", limit=TOP_K, group_size=1, ...)` (`:441-443`) — MAX-pools
each skill's best-scoring point (base or trigger) and returns the top `TOP_K` (default 6, `:78`)
distinct skills as `{name, command, description, score}`.

**Live-state corroboration (probed `localhost:6333`, read-only):**
```
points_count: 3570   kind=base: 488   kind=trigger: 3082   enriched=true: 0
```
This matches ADR-0016's claimed post-rollout numbers exactly (`docs/adr/0016-body-derived-trigger-points.md:41-43`:
*"indexed":488, "embedded":1339 ... total 2231 -> 3570 (+60%)"*) and confirms `enriched` count is 0 —
i.e. base vectors are genuinely untouched on the live collection right now (see §2).

**Embedder wiring.** `server.py` defaults to `fastembed` / `bge-small-en-v1.5` (`server.py:72-74`), but
the deployed override is `paraphrase-multilingual-mpnet-base-v2` via `.mcp.json:6-8` (`SKILL_EMBED_BACKEND`,
`SKILL_EMBED_MODEL`), matching `VENDORED.md:23-24`'s documented customization. The warm shim
(`scripts/embed_server.py:41-46`) hardcodes the same model/backend before importing `skill_search.server`
(`:36-40` comment: *"Set the deployed embed env BEFORE importing the engine, so it reads mpnet-768"*) —
consistent, no drift found between `.mcp.json`, `embed_server.py`, and `bin/embed-shim:23-24`.

## 2. Vendored-patch integrity (ADR-0016 vs code vs VENDORED.md)

**Verdict: accurately logged and correctly present, with one live gap in the guard (see finding #2 below).**

- `VENDORED.md:41-51` describes the ADR-0016 patch: `_extract_body_triggers` + `body_triggers` field in
  `skills_discovery.py`, and `server._trigger_phrases` folding body phrases into the same MAX-pool layer,
  gated by `SKILL_BODY_TRIGGERS` (default on, `=0` reverts to "byte-identical to before"). Verified present
  at `skills_discovery.py:75-104` and `server.py:276-293,88` exactly as described.
- The claimed measurement "2231 -> 3570 (+60%)" (`VENDORED.md:47-48`, `ADR-0016:41-43`) matches the live
  probe above (3570 total).
- `SKILL_BODY_TRIGGERS=0` reverting to "byte-identical" is plausible from the code: `_trigger_phrases`
  (`server.py:276-293`) short-circuits to `_split_phrases(s["description"])[: _TRIG_MAX]` when the flag is
  off, identical to the description-only path predating ADR-0016 — I did not diff a live before/after index
  to independently re-verify byte-identity, so this specific sub-claim is **UNVERIFIED** (plausible from
  reading, not independently reproduced).
- Test coverage claim ("29 passed, 1 pre-existing integration test deselected", `ADR-0016:38-40`): tests
  matching the described cases exist — `test_body_triggers_from_header_section`,
  `test_body_triggers_inline_label_line`, `test_body_triggers_excludes_negative_section`,
  `test_body_triggers_empty_when_no_labeled_section` (`tests/test_discovery.py:54,67,74,89`) and
  `test_trigger_phrases_body_on_adds_and_dedupes`, `test_trigger_phrases_body_off_is_description_only`,
  `test_trigger_phrases_combined_cap_respects_trig_max` (`tests/test_indexing.py:46,61,71`). I ran the
  full suite (`$HOME/.local/share/skill-concierge/venv/bin/python3 -m pytest tests/ -q`, isolated per
  `conftest.py`): **29 passed, 1 failed** — see finding #1, this is a real (reproduced) discrepancy from
  the "deselected" framing.
- `VENDORED.md:37-40` attributes the *earlier* ADR-0012 multi-vector patch to both `server.py` **and**
  `skills_discovery.py`. I could not find ADR-0012-specific code in `skills_discovery.py` — its only
  distinct content is the unrelated v0.10.2 self-prefix guard (`_namespaced_name`, `:35-57`) and the later
  ADR-0016 body-trigger code. This attribution is **UNVERIFIED** / likely imprecise (see finding #3).

## 3. Correctness / logic findings (most severe first)

### 🔴 Finding 1 — Vendored integration test fails against the shipped multi-vector default (not merely "deselected")
**File:** `vendor/skill-search/tests/test_indexing.py:92-95`
```python
@pytest.mark.integration
def test_end_to_end_build_search_incremental():
    stats = server.build_index(force=True)
    assert stats["indexed"] > 0 and stats["embedded"] == stats["indexed"]
```
**Reproduced:** running the suite unrestricted (no `-m "not integration"` filter) against a real,
isolated fastembed backend:
```
FAILED tests/test_indexing.py::test_end_to_end_build_search_incremental
assert (488 > 0 and 3570 == 488)
29 passed, 1 failed
```
`build_index`'s `embedded` counts every re-embedded **point** (base + trigger), while `indexed` counts
unique **skill names** (`server.py:408-411`: `n_skills = len({d[2]["name"] for d in desired.values()})`
vs `"embedded": len(changed)`). Under the default `MULTIVECTOR=1` these numbers are never equal (488
skills produce 3570 points). The test's invariant is a holdover from the pre-ADR-0012 single-vector
world and was never updated.

**Why it matters:** ADR-0016 (`:38-40`) reports this as *"1 pre-existing integration test deselected (see
decision log D7)"* — language that reads as "known, intentionally skipped, benign." But
`pyproject.toml`'s marker config (`markers = ["integration: ... (deselect with -m 'not integration')"]`)
only deselects it when a caller explicitly passes `-m "not integration"`; a plain `pytest tests/` (what a
future contributor or CI would naturally run) **fails**. The vendored patch narrative undersells a real,
reproducible test/production drift: the test still asserts an invariant the shipped default (`MULTIVECTOR`
on) violates, and nothing in this patch (or ADR-0012 before it) fixed the assertion. This is the clearest
"silent divergence not logged as such" in scope for this review — logged as "deselected," not as "broken."

**Suggestion:** update the assertion to compare against point count, e.g.
`stats["embedded"] == len(server.discover_skills()) ... ` is wrong too (still skill-count) — the correct
fix is asserting `stats["embedded"] >= stats["indexed"]` or comparing against `stats["points"]`, and/or
running CI with `-m "not integration"` explicitly rather than relying on an unstated convention.

### 🟡 Finding 2 — `doctor.py`'s standalone `reapply` auto-fixer lacks the `MULTIVECTOR` guard `fix_reindex` has
**Files:** `scripts/doctor.py:492-514`
```python
def fix_reindex():
    ...
    if MULTIVECTOR:
        # ... the legacy MEAN enrichment overlay must NOT run on top ...
        return True, msg          # <- guarded
    rr = _reapply_cmd()
    return (rr.returncode == 0), ...

def fix_reapply():
    if not SS_BIN.exists():
        return False, "venv missing — run ./setup.sh first"
    rr = _reapply_cmd()            # <- NOT guarded by MULTIVECTOR
    return (rr.returncode == 0), (_last_line(rr.stdout) or rr.stderr.strip() or "reapplied")
```
`AUTO_FIXERS = {"docker": ..., "reindex": fix_reindex, "reapply": fix_reapply, ...}` (`:529-531`).
ADR-0012 (`:50-51`) states *"doctor --fix no longer runs the legacy reapply when MULTIVECTOR is on (it
would mean-corrupt base vectors)"* — true for the `reindex` fixer, but `fix_reapply` (reachable whenever
`check_enrichment()` returns `fix="reapply"`, i.e. when some but not all points carry `enriched=true`,
`doctor.py:309-312`) runs `enrich_index.py --reapply` (the flat-MEAN-centroid overlay, `enrich_index.py:6`
*"enriched_vector = MEAN( [live S] + [embed(trigger) ...] )"*) unconditionally, on the **live** collection
by default (`enrich_index.py:301-303`: `reapply(SHADOW if args.shadow else LIVE)`).

**Why it matters:** this path is dormant today — the live probe above shows `enriched=true` count is 0,
so `check_enrichment()` currently returns `OK, fix=None` (`doctor.py:306-308`) and never suggests
`"reapply"`. But the *only* thing preventing `doctor --fix` from mean-corrupting the multi-vector base
vectors in the future is that precondition never becoming true — e.g. a one-off manual
`enrich_index.py --live` or `--reapply` invocation (already flagged elsewhere in this repo's history as a
known footgun) would flip some points to `enriched=true`, and the *next* `doctor --fix` run would then
happily finish the job via the unguarded `fix_reapply`, silently overwriting live base vectors with
MEAN-centroids — exactly the outcome ADR-0012 says the invariant protects against, and exactly the
self-healing tool that's supposed to prevent index corruption becoming the vector for it.

**Suggestion:** add the same `if MULTIVECTOR: return True/False, "skipped — multivector supersedes overlay"`
guard to `fix_reapply()` (and/or to `_reapply_cmd()` itself, since both call sites should share the guard).

### 💭 Finding 3 — `VENDORED.md`'s ADR-0012 attribution to `skills_discovery.py` is unverifiable from the current source
**File:** `vendor/skill-search/VENDORED.md:37-38`
> "Multi-vector MAX-pool retrieval (v0.10.0, ADR-0012): `server.py` (...) and `skills_discovery.py`."

I read `skills_discovery.py` in full (167 lines) and found no MAX-pool/multi-vector/trigger-phrase logic
distinct from the unrelated v0.10.2 self-prefix guard (`:35-57`, separately and correctly logged one bullet
down) and the ADR-0016 body-trigger code (`:60-104`, logged two bullets down). This may be an overbroad
carry-forward reference (e.g. to the shared `body` field `parse_skill` already produced, which predates
ADR-0012) rather than an actual second file touched by that patch. Low severity — doesn't misrepresent
behavior, just imprecise provenance — but flagged since the task explicitly asked to verify patches are
"accurately recorded in VENDORED.md."

## 4. Confidence + gaps

- **High confidence:** pipeline trace (discovery → build_index → search_skills), the ADR-0016 body-trigger
  patch's presence and correctness, the `.mcp.json`/embed-shim parity, and Findings 1–2 (both independently
  reproduced: #1 via a live pytest run, #2 via direct code reading of the guard asymmetry plus a live
  `enriched=0` probe confirming today's dormancy).
- **Not verified / out of scope for this pass:**
  - `SKILL_BODY_TRIGGERS=0` producing a byte-identical index to pre-ADR-0016 (plausible from code, not
    independently reproduced with a real before/after index diff).
  - `generate_overrides.py`, the enforcer hook (`hooks/scripts/enforcer.py` per other docs), and
    `scripts/analyze.py`/`calibrate_thresholds.py` were out of my assigned file list and not read.
  - `enrich_index.py`'s own correctness (mean/cosine math, snapshot-gating) was read for the guard-asymmetry
    finding only, not independently reviewed end-to-end — it is already flagged repo-wide (multiple prior
    reports in `plans/reports/`) as a legacy/superseded script recommended for deletion; I did not re-litigate
    that recommendation, only the live guard gap around it.
  - I did not independently confirm the upstream `skill-search` project's actual pre-vendor source (no
    network fetch performed), so "silent divergence from upstream" is assessed only against this repo's own
    `VENDORED.md` self-report, not a real upstream diff.
