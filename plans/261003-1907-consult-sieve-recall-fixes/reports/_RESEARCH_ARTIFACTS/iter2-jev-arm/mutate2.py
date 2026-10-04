import subprocess, sys
P = "scripts/sieve_recall.py"
orig = open(P).read()
M = [
 ("no exclude", 'if exclude_ids and cand[-1]["id"] in exclude_ids:', 'if False:'),
 ("pre_router not stamped", '"pre_router" if pre_router else offer_source(', 'offer_source('),
 ("source not stamped", '"pre_router_unseen" if pre_router else "fresh"', '"fresh"'),
 ("primary excludes pre_router", '[c["id"] for c in cases if c.get("offer_source") != "jev"]', '[c["id"] for c in cases if c.get("offer_source") == "embed_or_none"]'),
 ("pool not added", "        cases = cases + pre\n", "        pass\n"),
 ("pool not blocked", "blocked=_enf()._blocked, exclude_ids", "blocked=lambda n: False, exclude_ids"),
 ("shared sessions not counted", '"sessions_shared_with_spent_cases": len({c["sid"] for c in pre} & spent)', '"sessions_shared_with_spent_cases": 0'),
 ("check_fresh keeps unseen in session test", 'cases = [c for c in cases if c.get("source") != "pre_router_unseen"]', 'pass'),
 ("check_fresh drops unseen from floor", "    cases += unseen\n", "    pass\n"),
 ("primary_cases ignores pool", 'sources["embed_or_none"] + sources["pre_router"]', 'sources["embed_or_none"]'),
 ("hash ignores sources", '"OFFER_SOURCES": OFFER_SOURCES,', ''),
]
try:
    for name, old, new in M:
        assert orig.count(old) == 1, (name, orig.count(old))
        open(P, "w").write(orig.replace(old, new))
        r = subprocess.run([sys.executable, "-m", "pytest", "tests/test_sieve_recall.py", "-q", "-x", "-p", "no:randomly"], capture_output=True, text=True)
        print(("KILLED  " if r.returncode else "SURVIVED"), name, "|", r.stdout.strip().splitlines()[-1], flush=True)
finally:
    open(P, "w").write(orig)
