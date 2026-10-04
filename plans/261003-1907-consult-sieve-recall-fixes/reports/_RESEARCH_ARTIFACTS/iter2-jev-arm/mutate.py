import subprocess, sys
P = "scripts/sieve_recall.py"
orig = open(P).read()
M = [
 ("round-robin off", "        out += [c[i] for c in chunks if i < len(c)]", "        out = out + ([] if i else [x for c in chunks for x in c])"),
 ("sieve first", "for r in [{\"name\": n, \"external\": False} for n in jev_names] + list(sieve_rows):", "for r in list(sieve_rows) + [{\"name\": n, \"external\": False} for n in jev_names]:"),
 ("no dedupe", "        if k not in seen:\n            seen.add(k)\n            out.append({\"name\": r[\"name\"], \"external\": bool(r.get(\"external\"))})", "        out.append({\"name\": r[\"name\"], \"external\": bool(r.get(\"external\"))})"),
 ("no cut", "    return out[:cut]", "    return out"),
 ("retries 1", "ask(state, wide_questions, JEV_TIMEOUT_S, tiers=[tier], retries=JEV_RETRIES)", "ask(state, wide_questions, JEV_TIMEOUT_S, tiers=[tier], retries=1)"),
 ("ctx not empty", '"recent_context": "", "skills_already_loaded_this_session": []}\n    t0', '"recent_context": "x", "skills_already_loaded_this_session": []}\n    t0'),
 ("jev failure raises", "    except Exception as e:  # noqa: BLE001 — recorded per case; a Jev failure never stops the run\n        names, err = [], type(e).__name__", "    except ZeroDivisionError as e:\n        names, err = [], type(e).__name__"),
 ("offer_source ignores err", "isinstance(ledger_jev, dict) and ledger_jev and not ledger_jev.get(\"err\")", "isinstance(ledger_jev, dict) and ledger_jev"),
 ("offer_source ignores group", 'if group == "offered" and isinstance', 'if isinstance'),
 ("blocklist no-op", '    kept = [c for c in cases if not blocked(c["label"])]', '    kept = list(cases)'),
 ("no stratum stamp", '                cand[-1]["offer_source"] = offer_source(cand[-1]["group"], r.get("ledger_jev"))', '                pass'),
 ("build not blocked", 'blocked=_enf()._blocked if ITER >= 2 else None)', 'blocked=None)'),
 ("generation lost", '        if prior.get("generation"):\n            manifest["generation"] = prior["generation"]', '        pass'),
 ("iter1 hash changes", "    if ITER >= 2:   # iteration 1's fingerprint", "    if True:   # iteration 1's fingerprint"),
 ("iter2 hash ignores G6", '"G6_JEV_P90_MS": G6_JEV_P90_MS,', ''),
 ("holm m=5", "    pvals = [rules[d][\"p\"] if rules[d].get(\"G1\") else 1.0 for d in DECISIONS2]", "    pvals = [rules[d][\"p\"] if rules[d].get(\"G1\") else 1.0 for d in DECISIONS2] + [1.0, 1.0]"),
 ("g6 abs ignored", "g6_abs=G6_JEV_P90_MS if arm.startswith(\"J\") else None", "g6_abs=None"),
 ("J20 on all", '"D_J20": ("J20", "A0@20", "embed_or_none")', '"D_J20": ("J20", "A0@20", "all")'),
 ("latency not max", "max(sms, jms), info)", "sms, info)"),
 ("replay any iter", "    if ITER != 1:\n        print(\"replay-arms", "    if False:\n        print(\"replay-arms"),
 ("gate2 accepts iter1 opts", "    if args.arms or args.combine or args.composites:\n        raise RuntimeError", "    if False:\n        raise RuntimeError"),
 ("gate not dispatched", "    if ITER >= 2:\n        return cmd_gate2(man, args)", "    pass"),
 ("gate skips freeze", "    man = read_manifest()\n    check_freeze(man)\n    if ITER >= 2:", "    man = read_manifest()\n    if ITER >= 2:"),
]
try:
    for name, old, new in M:
        assert orig.count(old) == 1, (name, orig.count(old))
        open(P, "w").write(orig.replace(old, new))
        r = subprocess.run([sys.executable, "-m", "pytest", "tests/test_sieve_recall.py", "-q", "-x", "-p", "no:randomly"], capture_output=True, text=True)
        tail = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else r.stderr[-200:]
        print(("KILLED  " if r.returncode else "SURVIVED"), name, "|", tail, flush=True)
finally:
    open(P, "w").write(orig)
