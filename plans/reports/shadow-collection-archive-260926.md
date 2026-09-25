# claude_skills_shadow — archive and deletion (D3)

Date: 2026-09-26. Tool: `scripts/archive_qdrant_collection.py` (stdlib; `delete` re-runs `verify` and refuses on any failure).

Archive: `~/_ARCHIVE/skill-concierge-claude-skills-shadow-260926/`
- `points.jsonl` — every point with id, 768-dim vector and payload
- `claude_skills_shadow-3273000707820787-2026-09-25-18-25-45.snapshot` — Qdrant snapshot, 125770752 bytes
- `manifest.json` — collection info, counts, sha256 of both files

Pre-export live state: `points_count: 7080`, vectors size 768, Cosine.

Raw output:

```
$ python3.12 scripts/archive_qdrant_collection.py export --collection claude_skills_shadow --dest ~/_ARCHIVE/skill-concierge-claude-skills-shadow-260926
exported 7080 points + snapshot claude_skills_shadow-3273000707820787-2026-09-25-18-25-45.snapshot to /Users/thinhkhuat/_ARCHIVE/skill-concierge-claude-skills-shadow-260926
$ python3.12 scripts/archive_qdrant_collection.py verify --dest ~/_ARCHIVE/skill-concierge-claude-skills-shadow-260926 --expect 7080
verified: 7080 points (dim 768, unique ids, payloads present), snapshot claude_skills_shadow-3273000707820787-2026-09-25-18-25-45.snapshot 125770752 bytes sha256 ok
$ python3.12 scripts/archive_qdrant_collection.py delete --collection claude_skills_shadow --dest ~/_ARCHIVE/skill-concierge-claude-skills-shadow-260926 --expect 7080
verified: 7080 points (dim 768, unique ids, payloads present), snapshot claude_skills_shadow-3273000707820787-2026-09-25-18-25-45.snapshot 125770752 bytes sha256 ok
deleted claude_skills_shadow: true
$ curl -s http://127.0.0.1:6333/collections
{"result":{"collections":[{"name":"claude_skills"},{"name":"prompt_intent"}]},"status":"ok","time":5.792e-6}
$ curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:6333/collections/claude_skills_shadow
404
```

Restore path: `POST /collections/claude_skills_shadow/snapshots/upload` with the snapshot file, or re-upsert `points.jsonl`.
Only this collection was touched; containers, ports, images and caches are unchanged.
