"""Flags-off equivalence probe: HEAD server.py vs working tree, same fakes, no live index."""
import importlib.util, json, os, random, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
sys.path.insert(0, str(REPO / "vendor" / "skill-search"))
os.environ["SKILL_CONSULT_SLOTS"]="1"
for k in ():
    os.environ.pop(k, None)
from skill_search import server as new  # working tree (package path)
assert Path(new.__file__).resolve() == (REPO / "vendor/skill-search/skill_search/server.py").resolve(), new.__file__
spec = importlib.util.spec_from_file_location("skill_search.server_head", HERE / "server_head.py")
old = importlib.util.module_from_spec(spec); spec.loader.exec_module(old)

def grp(name, score, scope, path=True):
    pl = {"name": name, "description": "d-" + name, "scope": scope}
    if path: pl["path"] = "/p/" + name
    return {"id": name, "hits": [{"id": name, "score": score, "payload": pl}]}

def rig(mod, data, calls):
    mod.embed_queries = lambda qs: [[float(i)] for i, _ in enumerate(qs)]
    mod._staleness_warning = lambda: None
    mod._capsules = lambda: {"n3": {"purpose": "x"}}
    mod._blocked = lambda n: n == "n7"
    mod._claude_disabled_plugin_ids = lambda: {"plug"}
    class Q:
        def query_groups(self, c, v, group_by, limit, group_size=1, filter=None):
            calls.append(("qg", c, v, group_by, limit, json.dumps(filter, sort_keys=True)))
            return data[int(v[0])][:limit]
        def retrieve(self, c, ids):
            calls.append(("rt", c, tuple(ids)))
            return [{"payload": {"name": i, "path": "/r/" + str(i)}} for i in ids]
        def __getattr__(self, n):
            raise AssertionError("unexpected qdrant call " + n)
    mod._qdrant = Q()
    mod._point_id = lambda n: n

rng = random.Random(7); mism = 0; total = 0
scopes = ["personal", "plugin:plug", "catalog:x", "claude-synced", "project:/a"]
for trial in range(400):
    nq = rng.randint(1, 6)
    data = [[grp(f"{rng.choice(['','plug:'])}n{rng.randint(0,40)}", round(rng.random(), 6), rng.choice(scopes), rng.random() > .3)
             for _ in range(rng.randint(0, 45))] for _ in range(nq)]
    queries = [rng.choice(["q", "", "  ", "query two"]) for _ in range(nq)]
    top_n = rng.choice([None, 0, 1, 5, 20, 40, 99, "7"])
    for ro in ("1", "0"):
        os.environ["SKILL_ROW_ORIGIN"] = ro
        outs = []
        for mod in (old, new):
            calls = []; rig(mod, data, calls)
            try:
                r1 = mod.consult_candidates(queries, top_n)
            except Exception as e:
                r1 = "EXC " + type(e).__name__
            r2 = mod.search_skills(queries[0] or "x", queries[1:] or None)
            r3 = json.dumps(mod._fuse_ranked(data, 20, with_paths=True)) + json.dumps(mod._fuse_ranked(data, 7))
            outs.append((r1, r2, r3, calls))
        total += 1
        if outs[0] != outs[1]:
            mism += 1
            if mism < 3: print("MISMATCH trial", trial, ro)
print(f"trials {total} mismatches {mism}")
