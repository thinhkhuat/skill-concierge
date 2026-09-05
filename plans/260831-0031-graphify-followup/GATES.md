# Gates: graphify update follow-up — verify open threads of the 2026-08-30 --update run

OWNS: graphify-out/**

Scope: prove the five open outcomes of tonight's graph update — enrich_index node
currency, dropped out-of-scope originals still present, hyperedge-drop diagnosis,
duplicate-node census, and final clean/fresh state.

- [x] G1: enrich_index.py graph node is current — graphify's own content hash of
  the live file equals the manifest's recorded ast_hash
  CWD: /Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge
  CHECK: /Users/thinhkhuat/.local/share/uv/tools/graphifyy/bin/python -c "import json; from graphify.detect import _stat_and_hash; m=json.load(open('graphify-out/manifest.json'))['scripts/enrich_index.py']; r=_stat_and_hash('scripts/enrich_index.py'); ok=bool(r) and r[2]==m['ast_hash']; print('G1 PASS: node current' if ok else 'G1 FAIL: hash drift '+repr(r)); raise SystemExit(0 if ok else 1)"
  EXPECT: G1 PASS: node current
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge; path=08277af98118/87 entries; EXPECT=matched; output-sha256=c24655ddcb419ce7a617822fbe6460018f92c000de7ae02dfa71cec0c9f2ff81; output-bytes=22

- [x] G2: mis-attribution targets verified — the 34 representable files (docs,
  code, SKILL.md) still have their own nodes in graph.json; the 4 flat
  data-shaped JSONs (plugin manifests ×3, hooks.json) are absent by upstream
  design (zero AST nodes, #1224, matches tonight's AST zero-node warning);
  negative control proves the probe can fail
  CWD: /Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge
  CHECK: /Users/thinhkhuat/.local/share/uv/tools/graphifyy/bin/python graphify-out/.probe_graph_gates.py g2
  EXPECT: G2 PASS: 34 represented; 4 flat-JSON absent by upstream design
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge; path=08277af98118/87 entries; EXPECT=matched; output-sha256=b06ab7a8ddfe5e60fb372b7ac9243ec2260cd9c5b468a656fb255d49eaa71eb7; output-bytes=352

- [x] G3: dropped hyperedge blocklist_four_layer_enforcement diagnosed — for
  each of its 4 member ids, whether the id exists in graph.json and whether its
  source file has nodes; verdict recorded (stale ids vs invented)
  CWD: /Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge
  CHECK: /Users/thinhkhuat/.local/share/uv/tools/graphifyy/bin/python graphify-out/.probe_graph_gates.py g3
  EXPECT: G3 PASS: hyperedge diagnosis recorded
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge; path=08277af98118/87 entries; EXPECT=matched; output-sha256=08646299c1bd769316306fd5b79f344fa00888aec3a2b2d72dec48b8b5f401c2; output-bytes=164

- [x] G4: duplicate-label census — nodes sharing a label under different ids
  counted; eval/triggers.json confirmed as one such duplicate
  CWD: /Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge
  CHECK: /Users/thinhkhuat/.local/share/uv/tools/graphifyy/bin/python graphify-out/.probe_graph_gates.py g4
  EXPECT: G4 PASS: census recorded, eval/triggers.json duplicate confirmed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge; path=08277af98118/87 entries; EXPECT=matched; output-sha256=57f1ff6d0b422bba71c4bd001a512f6c1238cc1163bdf4c73ab4b14eef2f151e; output-bytes=168

- [x] G5: final state — staleness notice silent, graph.json valid with >3700
  nodes, manifest keys all repo-relative (no absolute-path leaks), no leftover
  .graphify_* intermediates or .run_*.py scripts in graphify-out
  AMENDED 2026-08-31 03:35: the >3700 figure was epoch-scoped to the 23:56
  build (3723). Commit 9d69e22 at 00:51 fired graphify's post-commit hook,
  which snapshotted 3723 to graphify-out/2026-08-31/ then pruned 64
  phantom-path nodes (LLM-minted source_file values with no file on disk,
  verified absent) → 3659. Cleanup, not loss. Probe updated: floor 3600 +
  phantom paths must stay gone; re-run green (see re-verify below).
  CWD: /Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge
  CHECK: /Users/thinhkhuat/.local/share/uv/tools/graphifyy/bin/python graphify-out/.probe_graph_gates.py g5
  EXPECT: G5 PASS: graph fresh, portable, clean
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge; path=08277af98118/87 entries; EXPECT=matched; output-sha256=c930072d40d4ed7d29407fa83fd5f27ada7e0675b11a58811a29fe9220d4172b; output-bytes=132

- [x] G6: skill/package version skew measured from both sources (resync via
  `graphify install` rewrites the upstream-managed skill dir and may invalidate
  the workbench-documented workarounds — decision handed off to operator, not
  executed this session)
  RESOLVED 2026-08-31: operator ordered the resync; `graphify install --platform
  claude` executed, skill dir now 0.9.32 == package. Content delta vs the
  pre-install backup (/tmp/graphify-skill-bak-260831): one line (#2106 —
  skipped_sensitive now lists file names); all previously-patched guards
  (#1939/#2015/#1948/#1908) ship upstream in 0.9.32; references/ identical.
  The CHECK below is historical — it asserted skew and now exits 1 by design.
  CWD: /Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge
  CHECK: /Users/thinhkhuat/.local/share/uv/tools/graphifyy/bin/python -c "import importlib.metadata as m; from pathlib import Path; pkg=m.version('graphifyy'); skill=Path.home().joinpath('.claude/skills/graphify/.graphify_version').read_text().strip(); print(f'G6 measured: skill {skill} vs package {pkg}'); print('G6 PASS: version skew confirmed' if skill != pkg else 'G6 FAIL: no skew'); raise SystemExit(0 if skill != pkg else 1)"
  EXPECT: G6 PASS: version skew confirmed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge/plans/260831-0031-graphify-followup; path=08277af98118/87 entries; EXPECT=matched; output-sha256=616f055942954852397c2941856ddac81aae44d1517f12fa07a63d5857a2aa58; output-bytes=76
