# The enforcer's contract self-test, kept out of the per-prompt hook file.
#
# Not collected by pytest (no `test_` prefix). `hooks/scripts/enforcer.py --selftest` and
# tests/test_enforcer_selftest.py compile this file and exec it inside the enforcer module's own
# namespace, so every bare name and `global` below is an enforcer global, exactly as when this
# function lived in enforcer.py. (Comments, not a docstring: an exec'd docstring would replace
# the enforcer's own __doc__.)
from __future__ import annotations


def _selftest() -> int:
    """Contract pins for the hook, one numbered section per contract.
    Run: python3 enforcer.py --selftest"""
    # Declared up-front: section (9) rebinds these BEFORE the section-(10+)
    # consolidated global line — a use-prior-to-global-declaration is a SyntaxError.
    global INVOCABLE_PLUGIN_IDS, PLUGIN_GATE
    must_fire = [
        "do not use the <skill> here",
        "please don't invoke that skill",
        "without using the test skill, just patch it",
        "skip reviewing this file",
        "never apply the formatter",
    ]
    must_not_fire = [
        "use the test skill to check this",                # affirmation
        "fix the bug where login does not work",           # bug report
        "the tests are not passing, help me debug",        # bug report
        "this deploy never finishes, investigate why",     # bug report
        "this function does not return the right value",   # bug report
        "ship this application to production",             # affirmation
    ]
    bad = []
    for t in must_fire:
        if not _REFUSAL_RE.search(t):
            bad.append("MISS (should fire): " + repr(t))
    for t in must_not_fire:
        if _REFUSAL_RE.search(t):
            bad.append("FALSE-FIRE (should stay silent): " + repr(t))
    # (1b) MAX_SHORT_WORDS counting is CJK-aware: a no-space script must not
    # collapse to one "word" (the 2026-08-25 live miss), English unchanged.
    if _word_count("帮我分析中医体质数据") <= MAX_SHORT_WORDS:
        bad.append("word_count: CJK task prompt collapsed to <=3 words (pre-gate swallow)")
    if _word_count("帮我 analyze 这个 bug today") != 5:
        bad.append("word_count: mixed CJK+English count wrong")
    if _word_count("ok 好") > MAX_SHORT_WORDS:
        bad.append("word_count: genuinely-short mixed prompt must stay <=3")
    for t in ("fix the typo", "run tests now", "one two three"):
        if _word_count(t) != len(t.split()):
            bad.append("word_count: pure-English count changed: " + repr(t))
    # (2) ranked-mandate %-share + disambiguation note
    multi = _ranked_mandate([("alpha", "desc alpha", 0.30), ("beta", "desc beta", 0.10)])
    if "(75%)" not in multi or "(25%)" not in multi:
        bad.append("ranked_mandate: expected 75%/25% shares")
    if "RELATIVE rank" not in multi:
        bad.append("ranked_mandate: missing relative-rank note for 2+ candidates")
    lone = _ranked_mandate([("alpha", "desc alpha", 0.25)])
    if "%" in lone or "RELATIVE rank" in lone:
        bad.append("ranked_mandate: lone candidate must show no share and no note")
    if "• alpha — desc alpha" not in lone:
        bad.append("ranked_mandate: lone candidate line malformed")

    # (3) actionability gate — the imperative VETO fires on task-verb openers and stays
    # off for conversational/question/approval turns (the gate suppresses ONLY non-imperatives).
    # NOTE: production main() drops prompts with <= MAX_SHORT_WORDS (3) words BEFORE _is_imperative
    # runs, so the veto only matters for prompts of 4+ words. The longer cases below represent that
    # production-reachable population; the <=3-word ones pin the function's correctness directly.
    imp_fire = ["fix the typo on line 12", "now, write the handoff", "please run the tests",
                "can you refactor this", "delete the cloned copy", "integrate the EFFORT gate",
                "let's run the tests",
                "sửa lỗi ở dòng 12", "hãy viết báo cáo", "chạy test giúp mình",
                "kiểm tra file này", "cài đặt thư viện", "phân tích log lỗi",
                "làm ơn dịch đoạn này", "tối ưu hàm này",
                "hãy sửa giúp mình cái lỗi đăng nhập ở trang chủ",
                "phân tích các log lỗi trong thư mục build hôm nay"]
    imp_off = ["how's the documentation status?", "good direction we're heading",
               "what does this function do", "i think we should reconsider",
               "thanks that worked", "yes please",
               "tài liệu thế nào rồi", "hàm này làm gì vậy",
               "mình nghĩ nên xem lại", "cảm ơn nhé",
               "cái hàm xử lý đăng nhập này hoạt động như thế nào vậy",
               "theo bạn thì mình có nên viết lại phần này không"]
    for t in imp_fire:
        if not _is_imperative(t):
            bad.append("imperative MISS (should fire): " + repr(t))
    for t in imp_off:
        if _is_imperative(t):
            bad.append("imperative FALSE-FIRE (should stay off): " + repr(t))

    # (4) keep-off hard-drop: listed names removed, order preserved, fail-open on empty set.
    surv, drp = _drop_keepoff([("a", "", 0.3), ("bad", "", 0.2), ("c", "", 0.1)], frozenset({"bad"}))
    if [n for n, _, _ in surv] != ["a", "c"] or drp != ["bad"]:
        bad.append(f"keepoff drop wrong: survivors={[n for n, _, _ in surv]} dropped={drp}")
    s2, d2 = _drop_keepoff([("a", "", 0.3)], frozenset())
    if [n for n, _, _ in s2] != ["a"] or d2 != []:
        bad.append("keepoff empty-set must pass everything through")

    # (4b) ADR-0046 blocklist drop: bare entry catches qualified twins, qualified entry is
    # exact-only, empty set is a no-op, and the kill-switch empties the loaded set.
    global BLOCKLIST, _BLOCKLIST_PATH
    _saved_bl, _saved_blp = BLOCKLIST, _BLOCKLIST_PATH
    try:
        BLOCKLIST = frozenset({"victim", "only:exact"})
        if not _blocked("victim") or not _blocked("antigravity:victim"):
            bad.append("blocklist: bare entry must catch the qualified twin")
        if _blocked("only:exact") is False or _blocked("x:exact"):
            bad.append("blocklist: qualified entry must be exact-only")
        if _blocked("innocent") or not _blocked("other:victim"):
            bad.append("blocklist: innocent must pass while a bare twin is caught")
        s3, d3 = _drop_blocklisted(
            [("a", "", 0.3), ("victim", "", 0.25), ("antigravity:victim", "", 0.2), ("c", "", 0.1)])
        if [n for n, _, _ in s3] != ["a", "c"] or d3 != ["victim", "antigravity:victim"]:
            bad.append(f"blocklist drop wrong: survivors={[n for n, _, _ in s3]} dropped={d3}")
        BLOCKLIST = frozenset()
        s4, d4 = _drop_blocklisted([("a", "", 0.3)])
        if [n for n, _, _ in s4] != ["a"] or d4 != []:
            bad.append("blocklist empty-set must pass everything through")
        # kill-switch + file read through the loader (env-seamed to a temp file)
        import tempfile as _tf
        with _tf.TemporaryDirectory() as _td:
            _BLOCKLIST_PATH = Path(_td) / "bl.json"
            _BLOCKLIST_PATH.write_text('{"blocked": ["z"]}', encoding="utf-8")
            os.environ["SKILL_BLOCKLIST"] = "0"
            if _load_blocklist() != frozenset():
                bad.append("blocklist: SKILL_BLOCKLIST=0 must empty the set")
            del os.environ["SKILL_BLOCKLIST"]
            if _load_blocklist() != frozenset({"z"}):
                bad.append("blocklist: loader must read the file when the switch is on")
    finally:
        BLOCKLIST, _BLOCKLIST_PATH = _saved_bl, _saved_blp

    # (5) a lone candidate (the `cands[:1]` fallback) renders alone: no %-share, no note.
    lone = _ranked_mandate([("a", "da", 0.30)])
    if "%" in lone or "RELATIVE rank" in lone:
        bad.append("a lone candidate must render alone (no %-share / note)")

    # (6) deterministic routes (ADR-0054: config-driven, default ON;
    # ENFORCER_DETERMINISTIC=0 empties them). Routes are pure and run before embed.
    global _ROUTES
    if os.environ.get("ENFORCER_DETERMINISTIC", "1").strip() == "0" and _ROUTES:
        bad.append("deterministic routes must be empty when ENFORCER_DETERMINISTIC=0")
    _saved_routes = _ROUTES
    try:
        _ROUTES = [("open a pull request", "ck:git")]
        hit = [n for n, _d, _s in _route_hits("please open a pull request now")]
        if hit != ["ck:git"]:
            bad.append(f"deterministic route must fire on a whole-word match: {hit}")
        if _route_hits("an unrelated prompt") != []:
            bad.append("deterministic route must not fire without a match")
        _ROUTES = [("/cook", "ak-cook"), ("open a pull request", "ck:git")]
        if _route_hits("see https://docs.typesafe.ai/cookbooks/x and open a pull requests page") != []:
            bad.append("deterministic route must not fire inside a longer word (/cookbooks)")
        if [n for n, _d, _s in _route_hits("run /cook now")] != ["ak-cook"]:
            bad.append("deterministic route must fire on a whole-word match")
        _ROUTES = [("open a pull request", "ck:git")]
        merged = _merge_route_hits(_route_hits("open a pull request"),
                                   [("other", "o", 0.5), ("ck:git", "real desc", 0.3)])
        if [n for n, _d, _s in merged] != ["ck:git", "other"]:
            bad.append(f"a named skill must lead once and its retrieved copy must drop: {merged}")
        if merged[0][1] != "real desc" or merged[0][2] != 1.0:
            bad.append("a promoted route hit must keep the retrieved description at score 1.0")
        if _merge_route_hits([], [("other", "o", 0.5)]) != [("other", "o", 0.5)]:
            bad.append("a no-hit turn must leave the retrieved candidates untouched")
        _ROUTES = []
        if _route_hits("open a pull request") != []:
            bad.append("deterministic routes must be inert when the config is empty")
    finally:
        _ROUTES = _saved_routes

    # (6b) keep-off must survive a co-configured deterministic route (ADR-0011): a route
    # pointing at a keep-off'd skill must NOT resurface it at score 1.0 (which would bypass
    # both the getaway and actionability gates). Reproduces the drop-then-route interaction.
    _saved_routes2 = _ROUTES
    try:
        _ROUTES = [("deploy the app", "chronic")]
        keepoff = frozenset({"chronic"})
        surv, _drp = _drop_keepoff([("chronic", "", 0.2), ("other", "", 0.15)], keepoff)
        det = _merge_route_hits(_route_hits("please deploy the app now", keepoff), surv)
        if any(n == "chronic" for n, _d, _s in det):
            bad.append("keep-off skill resurfaced via a deterministic route (ADR-0011 bypass)")
    finally:
        _ROUTES = _saved_routes2


    # (7) AUTHORIZED-SKIP tier: both legs inject the marker + required content when the
    # kill-switch is on, and stay fully silent (no inject call at all) when it's off.
    # Monkeypatch _inject to capture without touching real stdout.
    global _inject, AUTHORIZED_SKIP
    _saved_inject, _saved_authorized_skip = _inject, AUTHORIZED_SKIP
    _captured = []

    def _fake_inject(text):
        _captured.append(text)

    _inject = _fake_inject
    try:
        AUTHORIZED_SKIP = True
        _authorized_skip_inject("getaway", top=0.30, floor=0.45)
        _authorized_skip_inject("intent_skip")
        _authorized_skip_inject("selfref")
        _authorized_skip_inject("harness", hint=False)
        if len(_captured) != 4:
            bad.append(f"authorized-skip: expected 4 injects when flag ON, got {len(_captured)}")
        else:
            # ADR-0054 [xcut]: the harness leg carries its own LOCKED signature (the audit's
            # _AUTHORIZED_SIGNATURES), unique to it, and rides no chain hint.
            if "harness-message lane" not in _captured[3]:
                bad.append("authorized-skip: harness message missing the locked signature phrase")
            if any("harness-message lane" in c for c in _captured[:3]):
                bad.append("authorized-skip: harness signature must NOT appear in the other legs")
            if "CHAIN-HINT" in _captured[3]:
                bad.append("authorized-skip: harness leg must not carry a chain hint")
            if not all(c.startswith(AUTHORIZED_SKIP_MARKER) for c in _captured):
                bad.append("authorized-skip: injected text must start with the marker")
            if "search_skills" not in _captured[0] or "get_skill(" not in _captured[0]:
                bad.append("authorized-skip: getaway message missing search_skills escalation or get_skill nudge")
            if "0.30" not in _captured[0] or "0.45" not in _captured[0]:
                bad.append("authorized-skip: getaway message did not interpolate top/floor")
            if "conversational" not in _captured[1]:
                bad.append("authorized-skip: intent_skip message missing conversational rationale")
            # H5 [xcut#1]: the selfref leg carries the LOCKED cross-file signature (audit matches
            # this exact substring), and the signature is UNIQUE to it — a collision with the
            # getaway/intent messages (or, downstream, the H2 doctrine-table row) makes the audit
            # miscount real false-skips as authorized, masking the exact dodges H1 measures.
            if "self-referential recap lane" not in _captured[2]:
                bad.append("authorized-skip: selfref message missing the locked signature phrase")
            if ("self-referential recap lane" in _captured[0]
                    or "self-referential recap lane" in _captured[1]):
                bad.append("authorized-skip: selfref signature must NOT appear in getaway/intent messages")

        _captured.clear()
        AUTHORIZED_SKIP = False
        _authorized_skip_inject("getaway", top=0.30, floor=0.45)
        _authorized_skip_inject("intent_skip")
        _authorized_skip_inject("selfref")
        _authorized_skip_inject("harness", hint=False)
        if _captured:
            bad.append("authorized-skip: must stay silent when the kill-switch is off")
    finally:
        _inject, AUTHORIZED_SKIP = _saved_inject, _saved_authorized_skip

    # (8) H5 self-referential over-fire lane — fires ONLY on a pure recap of the agent's own prior
    # message; the whole-prompt task-verb veto + connector veto keep any task-tail prompt OUT (the
    # must-NOT-fire bypasses are the red-team's core H5 correctness case).
    selfref_fire = [
        "explain your last answer again",
        "can you rephrase your previous response",
        "summarize what you just said please",
        "expand on that point a little more",
        "reword your explanation more simply",
        "clarify your previous answer",
    ]
    selfref_off = [
        "explain your answer and implement the migration",   # task tail (verb veto)
        "rephrase your last answer as a working config",     # task tail (connector veto)
        "clarify your point by writing the actual code",     # task tail (connector veto)
        "explain how the auth middleware works",             # external object, real question
        "summarize the changes then deploy them",            # external object + task
        "rephrase the readme into plain english",            # object is the readme, not the agent
    ]
    for t in selfref_fire:
        if not _is_selfref(t):
            bad.append("selfref MISS (should fire): " + repr(t))
    for t in selfref_off:
        if _is_selfref(t):
            bad.append("selfref FALSE-FIRE (should route normally): " + repr(t))
    if SELFREF_SKIP is not True:
        bad.append("ENFORCER_SELFREF_SKIP must default ON")

    # (9) ADR-0029 chain hint — fires on a fresh same-sid seed (auto AND manual/slash),
    # survives a NEWER sub-stamped row (ADR-0020 lane), drops keep-off'd and dangling
    # successors, silent on TTL-expired / other-sid / absent-sidecar / flag-off, and the
    # line carries neither the audit marker nor the locked signature phrases (parity).
    global CHAIN_HINT, CHAIN_TTL_S, _SIDECAR_PATH, LEDGER, KEEPOFF, _NEXT_SKILLS_OVERRIDES
    global MINED_CHAINS, _MINED_CHAINS_PATH
    _saved_chain = (CHAIN_HINT, CHAIN_TTL_S, _SIDECAR_PATH, LEDGER, KEEPOFF, _NEXT_SKILLS_OVERRIDES,
                    MINED_CHAINS, _MINED_CHAINS_PATH, INVOCABLE_PLUGIN_IDS)
    with tempfile.TemporaryDirectory() as _td:
        _tdp = Path(_td)
        try:
            _sidecar = _tdp / "next-skills.json"
            _sidecar.write_text(json.dumps({
                "personal": {"seed-a": ["succ-b", "succ-c", "dead-x"],
                             "succ-b": [], "succ-c": [], "seed-k": ["succ-c"]},
                "plugin": {"pk:s": ["pk:t"], "pk:t": []},
                "project:elsewhere": {"ghost": ["spooky"], "spooky": []},
            }), encoding="utf-8")
            _led = _tdp / "ledger.log"
            _SIDECAR_PATH, LEDGER, KEEPOFF = _sidecar, _led, frozenset({"succ-c"})
            CHAIN_HINT, CHAIN_TTL_S = True, 900.0
            # the fixture's `pk` plugin id is not a real install — admit it so the
            # ADR-0052 gate ( exercising the SAME successor filters) stays inert here
            INVOCABLE_PLUGIN_IDS = (INVOCABLE_PLUGIN_IDS if isinstance(INVOCABLE_PLUGIN_IDS, set)
                                    else set()) | {"pk"}
            _now = time.time()
            _led.write_text("\n".join([
                json.dumps({"t": _now - 400, "sid": "s1", "ev": "auto", "name": "seed-a"}),
                json.dumps({"t": _now - 300, "sid": "s2", "ev": "manual", "name": "pk:s"}),
                json.dumps({"t": _now - 200, "sid": "s1", "ev": "auto", "name": "other", "sub": True}),
            ]) + "\n", encoding="utf-8")
            h = _chain_hint("s1")
            if "CHAIN-HINT: after seed-a" not in h or "succ-b" not in h:
                bad.append(f"chain-hint: expected seed-a -> succ-b line, got {h!r}")
            if "succ-c" in h or "dead-x" in h:
                bad.append(f"chain-hint: keep-off'd / dangling successors must be dropped: {h!r}")
            h2 = _chain_hint("s2")
            if "pk:s" not in h2 or "pk:t" not in h2:
                bad.append(f"chain-hint: manual (slash) seed must work via plugin scope: {h2!r}")
            # audit parity: the hint line itself must not match the marker or the
            # locked signature (else a collision miscounts real dodges as authorized).
            for _lit in ("SKILL-CHECK:", "self-referential recap lane"):
                if _lit in h:
                    bad.append(f"chain-hint: line must not contain locked literal {_lit!r}")
            # leg wiring: the hint rides an AUTHORIZED-SKIP line too (target population).
            _saved_inject2 = _inject
            _cap = []
            _inject = _cap.append
            try:
                _authorized_skip_inject("intent_skip", "s1")
                if len(_cap) != 1 or "SKILL-CHECK:" not in _cap[0] or "CHAIN-HINT:" not in _cap[0]:
                    bad.append(f"chain-hint: authorized-skip leg must carry both lines, got {_cap!r}")
            finally:
                _inject = _saved_inject2
            # TTL expiry
            _led.write_text(json.dumps(
                {"t": _now - 2000, "sid": "s1", "ev": "auto", "name": "seed-a"}) + "\n",
                encoding="utf-8")
            if _chain_hint("s1"):
                bad.append("chain-hint: TTL-expired seed must not hint")
            # other sid
            _led.write_text(json.dumps(
                {"t": _now - 10, "sid": "s9", "ev": "auto", "name": "seed-a"}) + "\n",
                encoding="utf-8")
            if _chain_hint("s1"):
                bad.append("chain-hint: another session's seed must not hint this one")
            # all-successors-keep-off'd
            _led.write_text(json.dumps(
                {"t": _now - 10, "sid": "s1", "ev": "auto", "name": "seed-k"}) + "\n",
                encoding="utf-8")
            if _chain_hint("s1"):
                bad.append("chain-hint: all-keep-off successors must yield no line")
            # absent sidecar -> fail open; flag off -> suppress
            _led.write_text(json.dumps(
                {"t": _now - 10, "sid": "s1", "ev": "auto", "name": "seed-a"}) + "\n",
                encoding="utf-8")
            _SIDECAR_PATH = _tdp / "nope.json"
            if _chain_hint("s1"):
                bad.append("chain-hint: absent sidecar must fail open to no hint")
            _SIDECAR_PATH = _sidecar
            CHAIN_HINT = False
            if _chain_hint("s1"):
                bad.append("chain-hint: flag off must suppress the line")
            CHAIN_HINT = True
            # (9b) ADR-0030 operator-owned overrides: override-wins over the sidecar
            # entry, keep-off still drops override successors, [] suppresses, and both
            # absent-file and malformed-file fail open to the sidecar value.
            _ovr = _tdp / "next-skills-overrides.json"
            _NEXT_SKILLS_OVERRIDES = _ovr
            _led.write_text(json.dumps(
                {"t": _now - 10, "sid": "s1", "ev": "auto", "name": "seed-a"}) + "\n", encoding="utf-8")
            _ovr.write_text(json.dumps({"seed-a": ["pk:t"]}), encoding="utf-8")
            h3 = _chain_hint("s1")
            if "pk:t" not in h3 or "succ-b" in h3:
                bad.append(f"chain-hint: override must win over the sidecar entry: {h3!r}")
            _ovr.write_text(json.dumps({"seed-a": ["not-in-catalogue"]}), encoding="utf-8")
            if _chain_hint("s1"):
                bad.append("chain-hint: override successor absent from the catalogue must drop (dangling)")
            _ovr.write_text(json.dumps({"seed-a": ["succ-c"]}), encoding="utf-8")
            if _chain_hint("s1"):
                bad.append("chain-hint: keep-off'd override successor must yield no line")
            _ovr.write_text(json.dumps({"seed-a": []}), encoding="utf-8")
            if _chain_hint("s1"):
                bad.append("chain-hint: empty override list must suppress the chain")
            _NEXT_SKILLS_OVERRIDES = _tdp / "nope-ovr.json"
            if "succ-b" not in _chain_hint("s1"):
                bad.append("chain-hint: absent overrides file must leave the sidecar value")
            _ovr.write_text("{not json", encoding="utf-8")
            _NEXT_SKILLS_OVERRIDES = _ovr
            if "succ-b" not in _chain_hint("s1"):
                bad.append("chain-hint: malformed overrides file must fail open to the sidecar value")
            _NEXT_SKILLS_OVERRIDES = _tdp / "nope-ovr.json"
            # (9c) ADR-0040 mined chains — lowest layer: fills an EMPTY declared entry
            # (with catalogue-visible successors only), never overrides a non-empty
            # declared value, is replaced by an explicit operator [] (applied after),
            # ignores keys from non-visible scopes, and fails open on flag-off /
            # absent / malformed file.
            _mined = _tdp / "mined-chains.json"
            _MINED_CHAINS_PATH = _mined
            _mined.write_text(json.dumps({"chains": {
                "succ-b": ["seed-a", "dead-z"],   # fills an empty declared entry
                "seed-a": ["pk:t"],               # declared non-empty -> mined ignored
                "ghost": ["seed-a"],              # key not visible (project:elsewhere)
            }}), encoding="utf-8")
            _led.write_text(json.dumps(
                {"t": _now - 10, "sid": "s1", "ev": "auto", "name": "succ-b"}) + "\n", encoding="utf-8")
            hm = _chain_hint("s1")
            if "seed-a" not in hm or "dead-z" in hm:
                bad.append(f"chain-hint: mined must fill empty declared entry, filtered: {hm!r}")
            _led.write_text(json.dumps(
                {"t": _now - 10, "sid": "s1", "ev": "auto", "name": "seed-a"}) + "\n", encoding="utf-8")
            hm2 = _chain_hint("s1")
            if "succ-b" not in hm2 or "pk:t" in hm2:
                bad.append(f"chain-hint: mined must not override a declared value: {hm2!r}")
            MINED_CHAINS = False
            _led.write_text(json.dumps(
                {"t": _now - 10, "sid": "s1", "ev": "auto", "name": "succ-b"}) + "\n", encoding="utf-8")
            if _chain_hint("s1"):
                bad.append("chain-hint: flag off must suppress the mined layer")
            MINED_CHAINS = True
            _ovr.write_text(json.dumps({"succ-b": []}), encoding="utf-8")
            _NEXT_SKILLS_OVERRIDES = _ovr
            if _chain_hint("s1"):
                bad.append("chain-hint: operator [] must replace a mined fill")
            _NEXT_SKILLS_OVERRIDES = _tdp / "nope-ovr.json"
            _led.write_text(json.dumps(
                {"t": _now - 10, "sid": "s1", "ev": "auto", "name": "seed-a"}) + "\n", encoding="utf-8")
            _MINED_CHAINS_PATH = _tdp / "nope-mined.json"
            if "succ-b" not in _chain_hint("s1"):
                bad.append("chain-hint: absent mined file must fail open to declared")
            _mined.write_text("{not json", encoding="utf-8")
            _MINED_CHAINS_PATH = _mined
            if "succ-b" not in _chain_hint("s1"):
                bad.append("chain-hint: malformed mined file must fail open to declared")
            _MINED_CHAINS_PATH = _tdp / "nope-mined.json"
        finally:
            CHAIN_HINT, CHAIN_TTL_S, _SIDECAR_PATH, LEDGER, KEEPOFF, _NEXT_SKILLS_OVERRIDES, \
                MINED_CHAINS, _MINED_CHAINS_PATH, INVOCABLE_PLUGIN_IDS = _saved_chain

    # (10) ADR-0031 installed query: _retrieve ALWAYS carries must_not tier=external
    # (byte-identical whether or not the ADR-0032 annex is on — externals cannot displace
    # installed). Its limit is RETRIEVE_LIMIT while ADR-0034's post-filter is on (over-fetch,
    # then trim to TOP_K) and exactly TOP_K when it is off. Pin the REQUEST SHAPE
    # (monkeypatched transport) and the 3-tuple parse.
    #
    # ONE consolidated `global` for every module name cases (10)-(12) rebind. Declaring them
    # per-case made a later case silently depend on an earlier one's declaration, so deleting
    # or reordering a case turned the next into an UnboundLocalError at its own save-line.
    global _post_json, EXTERNAL_ANNEX, EXTERNAL_SLOTS, EXTERNAL_FLOOR
    global CROSS_HARNESS, FOREIGN_SLOTS, FOREIGN_FLOOR, FOREIGN_SCOPES
    global ANNEX_DYNAMIC, ANNEX_MARGIN, RUNNING_HARNESS
    global _zcode_readable_skill, _commandcode_shares_personal_shelf
    global _agents_shares_personal_shelf
    _saved_dyn12 = ANNEX_DYNAMIC
    _saved_post = _post_json
    _reqs = []

    def _fake_post(url, payload, timeout):
        _reqs.append(payload)
        return {"result": {"groups": [
            {"id": "x", "hits": [{"payload": {"name": "inst", "description": "d"},
                                  "score": 0.5}]}]}}

    _post_json = _fake_post
    try:
        got = _retrieve([0.1, 0.2])
        flt = (_reqs[0] or {}).get("filter", {})
        if {"key": "tier", "match": {"value": "external"}} not in flt.get("must_not", []):
            bad.append(f"retrieve: missing must_not tier=external filter (installed query): {flt!r}")
        if _reqs[0].get("limit") != (RETRIEVE_LIMIT if CROSS_HARNESS else TOP_K):
            bad.append("retrieve: installed limit must over-fetch when ADR-0034 is on, "
                       "and be exactly TOP_K when off: {!r}".format(_reqs[0].get("limit")))
        if got != [("inst", "d", 0.5)]:
            bad.append(f"retrieve: response parse changed: {got!r}")
    finally:
        _post_json = _saved_post

    # (11) ADR-0032 external annex: _retrieve_external issues a SEPARATE must tier=external query
    # (never touches the installed query), applies EXTERNAL_FLOOR + EXTERNAL_SLOTS, derives the
    # alias, and _ranked_mandate renders a distinct annex block with the get_skill instruction.
    # Kill-switch off -> empty (no query issued).
    _saved = (EXTERNAL_ANNEX, EXTERNAL_SLOTS, EXTERNAL_FLOOR, _post_json,
              ANNEX_DYNAMIC, ANNEX_MARGIN)
    _ereqs = []

    def _fake_ext_post(url, payload, timeout):
        _ereqs.append(payload)
        return {"result": {"groups": [
            {"id": "1", "hits": [{"payload": {"name": "cat:hi", "description": "dh",
                                              "scope": "catalog:cat"}, "score": 0.75}]},
            {"id": "2", "hits": [{"payload": {"name": "cat:low", "description": "dl",
                                              "scope": "catalog:cat"}, "score": 0.30}]}]}}

    try:
        EXTERNAL_ANNEX, EXTERNAL_SLOTS, EXTERNAL_FLOOR = True, 2, 0.40
        ANNEX_DYNAMIC, ANNEX_MARGIN = False, 0.05
        _post_json = _fake_ext_post
        ext = _retrieve_external([0.1])
        req = _ereqs[0]
        if {"key": "tier", "match": {"value": "external"}} not in req.get("filter", {}).get("must", []):
            bad.append("annex query: must carry must tier=external filter: {!r}".format(req.get("filter")))
        if req.get("limit") != EXTERNAL_SLOTS * 3:
            bad.append("annex query: limit must over-fetch (EXTERNAL_SLOTS * 3)")
        if [n for n, _d, _s, _a in ext] != ["cat:hi"]:
            bad.append(f"annex: only ≥FLOOR externals kept (0.30 dropped): {ext!r}")
        if ext and ext[0][3] != "cat":
            bad.append("annex: alias not derived from scope")
        rendered = _ranked_mandate([("inst-a", "da", 0.9)], annex=ext)
        if "[external:cat]" not in rendered or "get_skill" not in rendered:
            bad.append("annex: render missing external marker or get_skill instruction")
        if "cat:low" in rendered:
            bad.append("annex: below-floor external must not render")
        # kill-switch off -> empty, no query issued
        EXTERNAL_ANNEX = False
        _ereqs.clear()
        if _retrieve_external([0.1]) != [] or _ereqs:
            bad.append("annex: kill-switch off must issue no external query and return []")
        if "[external:" in _ranked_mandate([("a", "d", 0.3)], annex=[]):
            bad.append("annex: empty annex must render no external block")

        # (11b) ADR-0036 dynamic annex floor. The rule in one function, pinned in both modes:
        # fixed mode ignores the installed top; dynamic mode is competitive with it, never
        # below the pool floor, and an absent installed top (<=0) falls back to the floor —
        # an empty inventory is the case the annex exists for, not a reason to suppress it.
        EXTERNAL_ANNEX = True
        ANNEX_DYNAMIC = False
        if _annex_floor(0.40, 0.90) != 0.40:
            bad.append("annex-floor: fixed mode must ignore the installed top")
        ANNEX_DYNAMIC = True
        if abs(_annex_floor(0.40, 0.90) - 0.85) > 1e-9:
            bad.append("annex-floor: dynamic must be top_installed - margin when above the floor")
        if _annex_floor(0.40, 0.42) != 0.40:
            bad.append("annex-floor: dynamic must never drop below the pool floor")
        if _annex_floor(0.40, 0.0) != 0.40:
            bad.append("annex-floor: no installed candidates must fall back to the pool floor")
        # end-to-end: a strong installed top prunes the 0.75 external; a weak one keeps it
        if [n for n, _d, _s, _a in _retrieve_external([0.1], top_installed=0.90)] != []:
            bad.append("annex: dynamic floor must prune externals losing to a strong installed top")
        if [n for n, _d, _s, _a in _retrieve_external([0.1], top_installed=0.55)] != ["cat:hi"]:
            bad.append("annex: dynamic floor must keep externals competitive with a weak installed top")

        # (11c) ADR-0048 complement annex. The gate is the design: a well-served intent
        # (installed top >= GETAWAY_FLOOR) admits an external ONLY if it beats that top by
        # ANNEX_BEAT; a thin intent (< GETAWAY_FLOOR) opens the annex at the plain floor;
        # demonstrated takes float a row above higher-scoring untaken rows and render
        # "used N×"; the kill-switch restores the ADR-0047 margin rule and score-only order.
        # The takes digest is rebound as the MODULE global — _TAKES_DIGEST_PATH resolves at
        # import, so a live operator digest must not leak into this leg (same class as the
        # blocklist selftest fix, 2026-08-29).
        global ANNEX_COMPLEMENT, ANNEX_BEAT, _TAKES_DIGEST_PATH
        _saved_c = (ANNEX_COMPLEMENT, ANNEX_BEAT, _TAKES_DIGEST_PATH)
        ANNEX_COMPLEMENT, ANNEX_BEAT, EXTERNAL_SLOTS = True, 0.04, 4
        import tempfile as _tf
        with _tf.TemporaryDirectory() as _td:
            _digest = Path(_td) / "takes.json"
            _digest.write_text(json.dumps({"cat:hi": 2}), encoding="utf-8")
            _TAKES_DIGEST_PATH = _digest

            def _fake_c_post(url, payload, timeout):
                return {"result": {"groups": [
                    {"id": "1", "hits": [{"payload": {"name": "cat:hi", "description": "dh",
                                                      "scope": "catalog:cat"}, "score": 0.75}]},
                    {"id": "2", "hits": [{"payload": {"name": "cat:mid", "description": "dm",
                                                      "scope": "catalog:cat"}, "score": 0.71}]},
                    {"id": "3", "hits": [{"payload": {"name": "cat:beat", "description": "db",
                                                      "scope": "catalog:cat"}, "score": 0.99}]}]}}
            _post_json = _fake_c_post
            # well-served intent (0.80 >= 0.45): floor 0.84 — the echo dies, the complement lives
            got = _retrieve_external([0.1], top_installed=0.80)
            if [n for n, _d, _s, _a in got] != ["cat:beat"]:
                bad.append(f"complement: well-served intent must keep ONLY the beater: {got!r}")
            # thin intent (0.40 < 0.45): plain floor 0.40 — annex widens, proven floats first
            EXTERNAL_FLOOR = 0.40
            got = _retrieve_external([0.1], top_installed=0.40)
            if [n for n, _d, _s, _a in got] != ["cat:hi", "cat:beat", "cat:mid"]:
                bad.append(f"complement: thin intent must rank proven-first then score: {got!r}")
            rendered = _ranked_mandate([("inst-a", "da", 0.42)], annex=got,
                                       takes={"cat:hi": 2})
            if "used 2×" not in rendered:
                bad.append("complement: proven external must render its used-N× marker")
            if rendered.find("cat:hi") > rendered.find("cat:beat"):
                bad.append("complement: render order must match the ranking (proven first)")
            # kill-switch: ADR-0047 margin rule returns (margin 0.05 in force → floor 0.75
            # drops cat:mid,
            # query order preserved — legacy mode never re-sorts — no marker)
            ANNEX_COMPLEMENT = False
            got = _retrieve_external([0.1], top_installed=0.80)
            if sorted(n for n, _d, _s, _a in got) != ["cat:beat", "cat:hi"]:
                bad.append(f"complement kill-switch: ADR-0047 margin floor must keep exactly "
                           f"the above-margin rows: {got!r}")
            if "used " in _ranked_mandate([("inst-a", "da", 0.9)], annex=got, takes={}):
                bad.append("complement kill-switch: no used-N× marker in legacy mode")
        (ANNEX_COMPLEMENT, ANNEX_BEAT, _TAKES_DIGEST_PATH) = _saved_c
        EXTERNAL_SLOTS = 2
    finally:
        (EXTERNAL_ANNEX, EXTERNAL_SLOTS, EXTERNAL_FLOOR, _post_json,
         ANNEX_DYNAMIC, ANNEX_MARGIN) = _saved

    # (12) ADR-0034 cross-harness. Pins the four things the design rests on:
    #   - a foreign-scope row is dropped from the INSTALLED offer, and the offer still fills to
    #     TOP_K from the over-fetch (no shrinkage);
    #   - an invocable TWIN in a foreign scope is KEPT installed and NOT repeated in the annex
    #     (the defect that made a pre-filter unusable: scope != invocability);
    #   - the annex query filters on the foreign scope SET, applies the floor, and renders with
    #     the harness marker + get_skill instruction, never joining the installed %-share pool;
    #   - the kill-switch restores the pre-ADR-0034 request shape and output exactly.
    _saved_xh = (CROSS_HARNESS, FOREIGN_SLOTS, FOREIGN_FLOOR, FOREIGN_SCOPES,
                 INVOCABLE_PLUGIN_IDS, _post_json)
    _freqs = []

    def _grp(gid, name, score, scope=None):
        pl = {"name": name, "description": "d-" + name}
        if scope:
            pl["scope"] = scope
        return {"id": gid, "hits": [{"payload": pl, "score": score}]}

    def _fake_xh_post(url, payload, timeout):
        _freqs.append(payload)
        flt = payload.get("filter", {})
        if flt.get("must"):                                   # the annex query
            return {"result": {"groups": [
                _grp("1", "otherpl:hi", 0.72, "codex-plugin"), _grp("2", "twinpl:dup", 0.71, "codex-plugin"),
                _grp("3", "otherpl:low", 0.31, "codex-plugin")]}}
        # the installed query: 2 foreign rows (one a twin), then plenty of installed filler
        return {"result": {"groups": [
            _grp("f1", "otherpl:hi", 0.9, "codex-plugin"),
            _grp("f2", "twinpl:dup", 0.89, "codex-plugin")]
            + [_grp(f"i{k}", f"inst-{k}", 0.8 - k / 100, "personal") for k in range(TOP_K)]}}

    _saved_rh = RUNNING_HARNESS
    try:
        if not FOREIGN_SCOPES:
            bad.append(f"cross-harness: foreign scopes unset: {FOREIGN_SCOPES!r}")
        if RUNNING_HARNESS == "claude" and (
                not all(x.startswith(("codex-", "commandcode-", "omp-", "zcode-", "dsh-", "cline-", "opencode-"))
                        for x in FOREIGN_SCOPES)
                or not {"omp-managed", "zcode-plugin"} <= set(FOREIGN_SCOPES)):
            bad.append(f"cross-harness: claude foreign scopes must be every other harness's roots: {FOREIGN_SCOPES!r}")
        # ADR-0054: the DSH/Cline personal roots must be foreign to every harness but their own.
        if RUNNING_HARNESS != "dsh" and "dsh-personal" not in FOREIGN_SCOPES:
            bad.append(f"cross-harness: dsh-personal missing from the {RUNNING_HARNESS} foreign scope set")
        if RUNNING_HARNESS != "cline" and "cline-personal" not in FOREIGN_SCOPES:
            bad.append(f"cross-harness: cline-personal missing from the {RUNNING_HARNESS} foreign scope set")
        # Nothing at module scope may touch the filesystem unguarded: `Path.cwd()` raises when
        # the working directory has been deleted (a worktree removed under a live session), and
        # an import-time raise turns a fail-silent hook into a traceback on every turn.
        _cwd = os.getcwd()
        _tmpd = tempfile.mkdtemp()
        try:
            os.chdir(_tmpd)
            os.rmdir(_tmpd)                  # cwd now deleted
            _invocable_plugin_ids()          # must not raise
            _visible_sidecar_names()         # nor this — it runs before _inject, so a raise
                                             # here costs the whole offer, silently
        except (OSError, UnicodeError, ValueError, TypeError, AttributeError, KeyError) as _e:
            bad.append("cross-harness: the import-time settings read and the chain-hint scope "
                       f"mirror must BOTH survive a deleted cwd: {type(_e).__name__}: {_e}")
        finally:
            os.chdir(_cwd)
            # os.rmdir above normally removed it; this only fires if os.chdir raised first.
            try:
                os.rmdir(_tmpd)
            except OSError:
                pass

        # `Path("").resolve()` is the CWD — a falsy env var must never be probed as a path.
        _cpr = os.environ.pop("CLAUDE_PLUGIN_ROOT", None)
        try:
            os.environ["CLAUDE_PLUGIN_ROOT"] = ""
            if (_running_harness() == "codex") != (f"{os.sep}.codex{os.sep}"
                                                   in str(Path(__file__).resolve())):
                bad.append("cross-harness: empty CLAUDE_PLUGIN_ROOT must fall through to "
                           "__file__, never resolve to the cwd")
            # A LITERAL like `$HOME/.claude` (a settings-level env block never shell-expands)
            # must also fall through — machine config debris cannot decide the harness.
            os.environ["CLAUDE_PLUGIN_ROOT"] = "$HOME/.claude"
            if (_running_harness() == "codex") != (f"{os.sep}.codex{os.sep}"
                                                   in str(Path(__file__).resolve())):
                bad.append("cross-harness: a non-absolute CLAUDE_PLUGIN_ROOT literal must fall "
                           "through to __file__, never be resolved against the cwd")
        finally:
            os.environ.pop("CLAUDE_PLUGIN_ROOT", None)
            if _cpr is not None:
                os.environ["CLAUDE_PLUGIN_ROOT"] = _cpr

        CROSS_HARNESS, FOREIGN_SLOTS, FOREIGN_FLOOR = True, 2, 0.40
        ANNEX_DYNAMIC = False   # case (12) pins the ADR-0034 shape; (11b) owns the dynamic rule
        # Pin the HARNESS DIRECTION too, not just the scope world. The assertions below model the
        # Claude-side twin rescue; run from a Codex cache path (or under garbage env) the module
        # derives RUNNING_HARNESS="codex", _invocable_twin goes deliberately blind, and exactly the
        # three twin assertions fail — a false alarm on the documented post-deploy verification
        # command (found by the first live Codex revalidation).
        RUNNING_HARNESS = "claude"
        FOREIGN_SCOPES, INVOCABLE_PLUGIN_IDS = ("codex-plugin", "codex-personal"), {"twinpl"}
        _post_json = _fake_xh_post

        _freqs.clear()
        inst = _retrieve([0.1])
        names = [n for n, _d, _s in inst]
        if _freqs[0].get("limit") != RETRIEVE_LIMIT:
            bad.append("cross-harness: installed query must over-fetch to RETRIEVE_LIMIT")
        if "scope" not in (_freqs[0].get("with_payload") or []):
            bad.append("cross-harness: installed query must request the scope payload")
        if any(c.get("key") == "scope"
               for c in _freqs[0].get("filter", {}).get("must_not", [])):
            bad.append("cross-harness: scope must be post-filtered, never a query condition "
                       "(scope != invocability): {!r}".format(_freqs[0].get("filter")))
        if "otherpl:hi" in names:
            bad.append("cross-harness: a non-invocable foreign row must not reach the offer")
        if "twinpl:dup" not in names:
            bad.append("cross-harness: an INVOCABLE twin must stay in the installed offer")
        if len(inst) != TOP_K:
            bad.append(f"cross-harness: offer must refill to TOP_K after the drop: {len(inst)}")

        # UNKNOWN must filter NOTHING. A None manifest means the twin test cannot be made, and
        # dropping on that reinstates the exact mislabelling the post-filter replaced.
        INVOCABLE_PLUGIN_IDS = None
        _freqs.clear()
        if "otherpl:hi" not in [n for n, _d, _s in _retrieve([0.1])]:
            bad.append("cross-harness: unknown plugin manifest must filter NOTHING, "
                       "never drop every foreign row")
        INVOCABLE_PLUGIN_IDS = {"twinpl"}

        _freqs.clear()
        fgn = _retrieve_foreign([0.1])
        cond = (_freqs[0].get("filter", {}).get("must") or [{}])[0]
        if cond.get("key") != "scope" or set(cond.get("match", {}).get("any") or []) != \
                set(FOREIGN_SCOPES):
            bad.append(f"cross-harness: annex query must match the foreign scope SET: {cond!r}")
        if "scope" not in (_freqs[0].get("with_payload") or []):
            bad.append("cross-harness: annex query must request the scope payload (per-row marker)")
        if [n for n, _d, _s, _h in fgn] != ["otherpl:hi"]:
            bad.append("cross-harness: annex keeps only above-floor non-twins "
                       f"(0.31 below floor, twinpl:dup invocable here): {fgn!r}")
        rendered = _ranked_mandate([("inst-a", "da", 0.9)], foreign=fgn)
        if "otherpl:hi [codex]" not in rendered or "installed under codex," not in rendered \
                or "get_skill" not in rendered:
            bad.append("cross-harness: render must mark each row with its own harness "
                       f"and carry the get_skill instruction: {rendered!r}")
        if "otherpl:low" in rendered or "twinpl:dup" in rendered:
            bad.append("cross-harness: below-floor or twin row must not render in the annex")
        if "%" in rendered.split("Other-harness")[0].split("inst-a")[1][:12]:
            bad.append("cross-harness: foreign must not join the installed %-share pool")

        # OMP direction: harness detection, foreign label/scopes, and the twin test.
        # Pin the OMP env forms and the natural marker + OMPCODE detection, then the
        # foreign-scope world and the union rule (plugin ids invocable here).
        _saved_omp_env = (os.environ.get("SKILL_CONCIERGE_HARNESS"), os.environ.get("OMPCODE"))
        _saved_rh2 = RUNNING_HARNESS
        _saved_fs2, _saved_inv2 = FOREIGN_SCOPES, INVOCABLE_PLUGIN_IDS
        try:
            # explicit env forms
            os.environ["SKILL_CONCIERGE_HARNESS"] = "omp"
            os.environ["OMPCODE"] = ""
            if _running_harness() != "omp":
                bad.append("cross-harness: SKILL_CONCIERGE_HARNESS=omp must resolve to omp")
            os.environ["SKILL_CONCIERGE_HARNESS"] = "oh-my-pi"
            if _running_harness() != "omp":
                bad.append("cross-harness: SKILL_CONCIERGE_HARNESS=oh-my-pi must resolve to omp")
            # OMP with CLAUDE markers set must resolve to omp (OMPCODE is the proof), never claude
            os.environ["SKILL_CONCIERGE_HARNESS"] = ""
            os.environ["OMPCODE"] = "1"
            if _running_harness() != "omp":
                bad.append("cross-harness: OMPCODE=1 must force omp even under claude markers")
            # claude/codex explicit values unchanged (not hijacked by OMPCODE)
            os.environ["SKILL_CONCIERGE_HARNESS"] = "claude"
            if _running_harness() != "claude":
                bad.append("cross-harness: SKILL_CONCIERGE_HARNESS=claude must stay claude")
            os.environ["SKILL_CONCIERGE_HARNESS"] = "codex"
            if _running_harness() != "codex":
                bad.append("cross-harness: SKILL_CONCIERGE_HARNESS=codex must stay codex")
            RUNNING_HARNESS = "omp"
            if _foreign_scopes() != ("codex-plugin", "commandcode-personal", "zcode-personal",
                                     "zcode-plugin", "dsh-personal", "cline-personal",
                                     "opencode-personal", "claude-synced"):
                bad.append("cross-harness: omp foreign scopes wrong: "
                           f"{_foreign_scopes()!r}")
            # twin test is active under omp (plugin ids invocable via the claude/omp union)
            INVOCABLE_PLUGIN_IDS = {"twinpl"}
            if not _invocable_twin("twinpl:dup"):
                bad.append("cross-harness: omp must rescue an invocable plugin twin")
            INVOCABLE_PLUGIN_IDS = None
            if _invocable_twin("twinpl:dup"):
                bad.append("cross-harness: omp unknown manifest must not rescue a twin")
        finally:
            os.environ.pop("SKILL_CONCIERGE_HARNESS", None)
            os.environ.pop("OMPCODE", None)
            if _saved_omp_env[0] is not None:
                os.environ["SKILL_CONCIERGE_HARNESS"] = _saved_omp_env[0]
            if _saved_omp_env[1] is not None:
                os.environ["OMPCODE"] = _saved_omp_env[1]
            RUNNING_HARNESS = _saved_rh2
            FOREIGN_SCOPES, INVOCABLE_PLUGIN_IDS = _saved_fs2, _saved_inv2

        # ZCode direction (ADR-0042): detection (explicit env, ZCODE_PLUGIN_ROOT env with the
        # falsy/non-absolute fallthroughs, explicit-env precedence), foreign label/scopes with
        # the shared-shelf personal rule, the registry twin, and the filesystem twin.
        # Mirrors the OMP direction block above.
        _saved_z_env = (os.environ.get("SKILL_CONCIERGE_HARNESS"),
                        os.environ.get("ZCODE_PLUGIN_ROOT"))
        _saved_rh3, _saved_fs3, _saved_inv3 = RUNNING_HARNESS, FOREIGN_SCOPES, INVOCABLE_PLUGIN_IDS
        _saved_fstwin, _saved_shelf = _zcode_readable_skill, _agents_shares_personal_shelf
        try:
            os.environ["SKILL_CONCIERGE_HARNESS"] = "zcode"
            if _running_harness() != "zcode":
                bad.append("cross-harness: SKILL_CONCIERGE_HARNESS=zcode must resolve to zcode")
            os.environ["SKILL_CONCIERGE_HARNESS"] = ""
            os.environ["ZCODE_PLUGIN_ROOT"] = "/tmp/.zcode/cli/plugins/cache/p/x/1.0"
            if _running_harness() != "zcode":
                bad.append("cross-harness: ZCODE_PLUGIN_ROOT set must resolve to zcode")
            os.environ["ZCODE_PLUGIN_ROOT"] = ""
            if _running_harness() == "zcode":
                bad.append("cross-harness: empty ZCODE_PLUGIN_ROOT must fall through (never the cwd)")
            os.environ["ZCODE_PLUGIN_ROOT"] = "relative/path"
            if _running_harness() == "zcode":
                bad.append("cross-harness: non-absolute ZCODE_PLUGIN_ROOT must fall through")
            # explicit SKILL_CONCIERGE_HARNESS outranks the zcode env signal
            os.environ["SKILL_CONCIERGE_HARNESS"] = "claude"
            if _running_harness() != "claude":
                bad.append("cross-harness: SKILL_CONCIERGE_HARNESS=claude must stay claude under ZCODE_PLUGIN_ROOT")
            os.environ.pop("SKILL_CONCIERGE_HARNESS", None)
            os.environ.pop("ZCODE_PLUGIN_ROOT", None)

            RUNNING_HARNESS = "zcode"
            _agents_shares_personal_shelf = lambda: True
            _fs = _foreign_scopes()
            if "personal" in _fs or "zcode-personal" in _fs or \
                    not {"plugin", "codex-plugin", "commandcode-personal", "omp-managed",
                         "dsh-personal", "cline-personal"} <= set(_fs):
                bad.append(f"cross-harness: zcode shared-shelf foreign scopes wrong: {_fs!r}")
            _agents_shares_personal_shelf = lambda: False
            if "personal" not in _foreign_scopes():
                bad.append("cross-harness: zcode divergent-shelf must foreign personal "
                           "(the per-row filesystem twin rescues what is actually readable)")
            _agents_shares_personal_shelf = _saved_shelf
            # twins: registry plugin twin, filesystem twin, a true non-twin, and the
            # unknown-manifest rule (must not rescue — mirrors the OMP assertion).
            FOREIGN_SCOPES = ("personal", "plugin")
            INVOCABLE_PLUGIN_IDS = {"twinpl"}
            if not _invocable_twin("twinpl:dup"):
                bad.append("cross-harness: zcode must rescue a registry plugin twin")
            _zcode_readable_skill = lambda n: n == "fstwin"
            INVOCABLE_PLUGIN_IDS = set()
            if not _invocable_twin("fstwin"):
                bad.append("cross-harness: zcode must rescue a filesystem twin")
            if _invocable_twin("other:nope"):
                bad.append("cross-harness: zcode must not rescue a row with no twin")
            _zcode_readable_skill = _saved_fstwin
            INVOCABLE_PLUGIN_IDS = None
            if _invocable_twin("twinpl:dup"):
                bad.append("cross-harness: zcode unknown manifest must not rescue a plugin twin")
        finally:
            os.environ.pop("SKILL_CONCIERGE_HARNESS", None)
            os.environ.pop("ZCODE_PLUGIN_ROOT", None)
            if _saved_z_env[0] is not None:
                os.environ["SKILL_CONCIERGE_HARNESS"] = _saved_z_env[0]
            if _saved_z_env[1] is not None:
                os.environ["ZCODE_PLUGIN_ROOT"] = _saved_z_env[1]
            RUNNING_HARNESS, FOREIGN_SCOPES, INVOCABLE_PLUGIN_IDS = _saved_rh3, _saved_fs3, _saved_inv3
            _zcode_readable_skill, _agents_shares_personal_shelf = _saved_fstwin, _saved_shelf

        # (ADR-0051) cline detection pins: explicit env maps, the .cline path marker,
        # the foreign-scope set (every other harness's scopes — no registry), and the
        # filesystem twin rescue on the Cline personal root.
        _saved_cl = (RUNNING_HARNESS, FOREIGN_SCOPES, INVOCABLE_PLUGIN_IDS)
        _saved_cl_env = (os.environ.get("SKILL_CONCIERGE_HARNESS"),)
        try:
            os.environ["SKILL_CONCIERGE_HARNESS"] = "cline"
            if _running_harness() != "cline":
                bad.append("cross-harness: SKILL_CONCIERGE_HARNESS=cline must resolve to cline")
            os.environ["SKILL_CONCIERGE_HARNESS"] = "cline-cli"
            if _running_harness() != "cline":
                bad.append("cross-harness: SKILL_CONCIERGE_HARNESS=cline-cli must resolve to cline")
            os.environ["SKILL_CONCIERGE_HARNESS"] = ""
            if _running_harness() == "cline":
                bad.append("cross-harness: cline must not resolve without a signal (no native env)")
            # explicit env outranks every other harness's marker
            os.environ["SKILL_CONCIERGE_HARNESS"] = "claude"
            if _running_harness() != "claude":
                bad.append("cross-harness: SKILL_CONCIERGE_HARNESS=claude must stay claude")
            os.environ.pop("SKILL_CONCIERGE_HARNESS", None)

            RUNNING_HARNESS = "cline"
            _saved_agents_shelf = _agents_shares_personal_shelf
            _agents_shares_personal_shelf = lambda: False     # divergent ~/.agents/skills
            _fs = _foreign_scopes()
            if "personal" not in _fs or "plugin" not in _fs or \
                    not {"codex-personal", "codex-plugin", "commandcode-personal",
                         "omp-personal", "omp-managed", "omp-plugin",
                         "zcode-personal", "zcode-plugin", "dsh-personal"} <= set(_fs):
                bad.append(f"cross-harness: cline foreign scopes wrong: {_fs!r}")
            # Cline and DSH read ~/.agents/skills: when it IS the Claude personal shelf, every
            # personal skill is invocable there and must stay in the offer.
            _agents_shares_personal_shelf = lambda: True
            for _h in ("cline", "dsh"):
                RUNNING_HARNESS = _h
                if "personal" in _foreign_scopes():
                    bad.append(f"cross-harness: {_h} must keep personal when ~/.agents/skills is the shelf")
            RUNNING_HARNESS = "dsh"
            _agents_shares_personal_shelf = lambda: False
            if "personal" not in _foreign_scopes():
                bad.append("cross-harness: dsh must foreign personal when ~/.agents/skills diverges")
            RUNNING_HARNESS = "cline"
            _agents_shares_personal_shelf = _saved_agents_shelf
            _fs = _foreign_scopes()
            if "cline-personal" in _fs:
                bad.append("cross-harness: cline must never foreign its own scopes")
            if _invocable_plugin_ids() is not None:
                bad.append("cross-harness: cline has no skill plugin registry — must return None")
            FOREIGN_SCOPES = ("personal", "plugin")
            INVOCABLE_PLUGIN_IDS = None
            if _invocable_twin("no-such-cline-twin-xyzzy"):
                bad.append("cross-harness: cline must not rescue a row with no filesystem twin")
        finally:
            os.environ.pop("SKILL_CONCIERGE_HARNESS", None)
            if _saved_cl_env[0] is not None:
                os.environ["SKILL_CONCIERGE_HARNESS"] = _saved_cl_env[0]
            RUNNING_HARNESS, FOREIGN_SCOPES, INVOCABLE_PLUGIN_IDS = _saved_cl

        # kill-switch off -> pre-ADR-0034 request shape and output
        CROSS_HARNESS = False
        _freqs.clear()
        _retrieve([0.1])
        if _freqs[0].get("limit") != TOP_K or "scope" in (_freqs[0].get("with_payload") or []):
            bad.append(f"cross-harness: kill-switch off must issue the pre-ADR-0034 request: {_freqs[0]!r}")
        _freqs.clear()
        if _retrieve_foreign([0.1]) != [] or _freqs:
            bad.append("cross-harness: kill-switch off must issue no annex query and return []")
        if "Other-harness" in _ranked_mandate([("a", "d", 0.3)], foreign=[]):
            bad.append("cross-harness: empty foreign annex must render no block")
    finally:
        (CROSS_HARNESS, FOREIGN_SLOTS, FOREIGN_FLOOR, FOREIGN_SCOPES,
         INVOCABLE_PLUGIN_IDS, _post_json) = _saved_xh
        ANNEX_DYNAMIC = _saved_dyn12
        RUNNING_HARNESS = _saved_rh

    # (13) ADR-0041 multi-intent shaping + route projection. Pins: two lexically
    # disjoint, score-comparable candidate groups split into 2 intents with
    # leads-first ordering; a weak second cluster does NOT split; siblings of one
    # intent stay one intent (byte-identical note); _route_of walks successors,
    # caps at 4 nodes, breaks cycles and dead ends; flags off revert to the
    # pre-0041 render; and the new lines carry neither the audit marker nor the
    # locked signature phrases (parity, same rule as the CHAIN-HINT line).
    # (_SIDECAR_PATH / _NEXT_SKILLS_OVERRIDES / _MINED_CHAINS_PATH were declared
    # global with case (9); they are only REBOUND here.)
    global MULTI_INTENT, CHAIN_PROJECTION
    _saved_41 = (MULTI_INTENT, CHAIN_PROJECTION, _MINED_CHAINS_PATH)
    try:
        # Pin both layers ON for these cases: the operator may run the selftest under an
        # env that turns a layer off (ENFORCER_MULTI_INTENT=0 is a live tuning order), and
        # the render pins below describe the ON behaviour; the flag-off cases re-set them.
        MULTI_INTENT = True
        CHAIN_PROJECTION = True
        _plan = ("plan", "scope a feature into a phased implementation roadmap with acceptance criteria", 0.40)
        _road = ("roadmap", "phased implementation roadmap milestones deliverables sequencing", 0.30)
        _test = ("test", "run the unit and integration suites, coverage gaps, failing checks", 0.36)
        _cov = ("coverage", "coverage of the unit and integration suites, gaps in assertions", 0.28)
        _c41 = [_plan, _test, _road, _cov]
        _cls = _intent_clusters(_c41)
        if len(_cls) != 2 or {c[0][0] for c in _cls} != {"plan", "test"}:
            bad.append(f"0041: expected plan/test clusters, got {[ [m[0] for m in c] for c in _cls ]!r}")
        if not _multi_intent_gate(_cls):
            bad.append("0041: comparable second cluster must pass the multi-intent gate")
        r41 = _ranked_mandate(_c41)
        if "Reads as 2 distinct intents" not in r41:
            bad.append("0041: two-intent render must carry the intent note")
        _first_rows = [l for l in r41.splitlines() if l.startswith("  • ")][:2]
        if not (_first_rows[0].startswith("  • plan") and _first_rows[1].startswith("  • test")):
            bad.append(f"0041: leads must render first, got {_first_rows!r}")
        # smoke-shaped regression (live 0.32.0 over-split): one test/fix family with
        # synonym vocabulary must NOT split into fake intents; and >MAX_INTENTS clusters
        # are capped, folding extras back as supporting rows.
        _t1 = ("ak-web-testing", "Web testing with Playwright, Vitest, k6. E2E/unit/integration/load/security/visual/a11y", 0.34)
        _t2 = ("ak-fix", "Fix bugs, errors, test failures, and CI/CD issues with intelligent routing", 0.33)
        _t3 = ("ak-test", "Run unit, integration, e2e, and UI tests. Test execution, coverage analysis, QA reports", 0.32)
        _t4 = ("dogfood", "Systematically explore and test a web application to find bugs, UX issues", 0.30)
        _t5 = ("ak-debug", "Debug systematically with root cause analysis before fixes. For bugs, test failures", 0.29)
        _smoke_cls = _intent_clusters([_t1, _t2, _t3, _t4, _t5])
        if len(_smoke_cls) > 2:
            bad.append(f"0041: same-family synonyms must not fake-split: {[ [m[0] for m in c] for c in _smoke_cls ]!r}")
        _smoke_render = _ranked_mandate([_t1, _t2, _t3, _t4, _t5])
        if "distinct intents" in _smoke_render and "8 distinct" in _smoke_render:
            bad.append("0041: smoke regression — absurd intent count")
        # cap: 4 two-member disjoint clusters -> at most MAX_INTENTS announced
        # (each non-first intent qualifies with 2 members; the 4th folds back as support)
        _dis = [("aa", "alpha beta gamma delta epsilon zeta", 0.40),
                ("aa2", "alpha beta gamma delta epsilon", 0.39),
                ("bb", "eta theta iota kappa lambda mu", 0.38),
                ("bb2", "eta theta iota kappa lambda", 0.37),
                ("cc", "nu xi omicron pi rho sigma", 0.36),
                ("cc2", "nu xi omicron pi rho", 0.35),
                ("dd", "tau upsilon phi chi psi omega", 0.34),
                ("dd2", "tau upsilon phi chi psi", 0.33)]
        _cap_render = _ranked_mandate(_dis)
        if f"Reads as {MAX_INTENTS} distinct intents" not in _cap_render:
            bad.append(f"0041: >MAX_INTENTS clusters must cap at {MAX_INTENTS}: "
                       + repr([l for l in _cap_render.splitlines() if "distinct intents" in l]))
        # singleton second cluster no longer qualifies (0.32.2 precision rule)
        _solo = [("aa", "alpha beta gamma delta epsilon zeta", 0.40),
                 ("zz", "unrelated disjoint vocabulary entirely", 0.39)]
        if "distinct intents" in _ranked_mandate(_solo):
            bad.append("0041: a singleton second cluster must not be announced as an intent")
        # weak second cluster: low score -> no split, standard note
        _weak = [_plan, ("test", "run the unit and integration suites, coverage gaps, failing checks", 0.10)]
        if "distinct intents" in _ranked_mandate(_weak):
            bad.append("0041: weak second cluster must not split the turn")
        # one intent, lexically close siblings -> original note, no split
        _single = [_plan, _road]
        r_single = _ranked_mandate(_single)
        if "distinct intents" in r_single or "pick the one matching the intent" not in r_single:
            bad.append("0041: single-intent siblings must keep the pre-0041 note")
        # _route_of: walk, cap, cycle, dead-end
        _saved_41_paths = (_SIDECAR_PATH, _NEXT_SKILLS_OVERRIDES)
        with tempfile.TemporaryDirectory() as _td41:
            _tdp41 = Path(_td41)
            _sc41 = _tdp41 / "ns.json"
            _sc41.write_text(json.dumps({"personal": {
                "a": ["b", "x"], "b": ["c"], "c": ["a"],        # a->b->c->a cycle
                "d": [],                                          # dead end
            }}), encoding="utf-8")
            _SIDECAR_PATH = _sc41
            _NEXT_SKILLS_OVERRIDES = _tdp41 / "nope.json"
            _MINED_CHAINS_PATH = _tdp41 / "nope2.json"
            _m41 = _visible_sidecar_names()
            if _route_of("a", _m41) != ["a", "b", "c"]:
                bad.append(f"0041: route must walk a->b->c and cap before the cycle: {_route_of('a', _m41)!r}")
            if _route_of("b", _m41) != ["b", "c", "a"]:
                bad.append(f"0041: mid-chain seed must walk its tail, cycle-blocked at the 4th hop: {_route_of('b', _m41)!r}")
            if _route_of("d", _m41):
                bad.append("0041: dead-end seed must yield no route")
            if _route_of("ghost", _m41):
                bad.append("0041: unknown seed must yield no route")
            if "ROUTE: if a fits" not in _ranked_mandate([("a", "desc", 0.4), ("z", "desc", 0.3)]):
                bad.append("0041: top candidate with successors must render the ROUTE line")
            for _lit in ("SKILL-CHECK:", "self-referential recap lane"):
                if _lit in _ranked_mandate([("a", "desc", 0.4)]):
                    bad.append(f"0041: render must not contain locked literal {_lit!r}")
            CHAIN_PROJECTION = False
            if "ROUTE:" in _ranked_mandate([("a", "desc", 0.4)]):
                bad.append("0041: projection flag off must suppress the ROUTE line")
            CHAIN_PROJECTION = True
            MULTI_INTENT = False
            if "distinct intents" in _ranked_mandate(_c41):
                bad.append("0041: multi-intent flag off must revert to the pre-0041 note")
            MULTI_INTENT = True
        _SIDECAR_PATH, _NEXT_SKILLS_OVERRIDES = _saved_41_paths
    finally:
        MULTI_INTENT, CHAIN_PROJECTION, _MINED_CHAINS_PATH = _saved_41

    # (15) ADR-0049 consult-intent routing — phrase-class precision + mandate render.
    cons_fire = [
        "which skills should I use for this refactor?",
        "which skill should I pick before starting the work?",
        "what skills do I have for this task — plan the chain",
        "plan a skill strategy for this migration",
        "what's the best combo of skills for this build?",
        "consult which skills fit this task",
        "please curate the skills for this pipeline work",
        "which skills to use for the deployment tonight",
        # v2 widening — replayed live miss (ledger, session 4ea5ee04, 2026-08-30)
        "which set of skills that we should be using to work on the new task",
        # v2 widening — we-form under-fire caught by the blind tester
        "what skills can we use for tomorrow's build?",
    ]
    cons_off = [
        "which skill did you just use?",            # reflexive past, not a curation ask
        "fix the login bug now",                    # plain task
        "consult the doctor about this rash",       # consult without a skill object
        "what does this function do",               # conversational
        "use the formatter on these files",         # affirmation
        "review the skill-search docs section",     # 'skill' noun without curation intent
        # v2 guards — the blind tester's parked over-fires, now held out by NEG
        "which skill should I have used earlier?",  # past-conditional
        "consult with my team about the skills gap",  # org-capability talk, not curation
    ]
    for t in cons_fire:
        if not (_CONSULT_RE.search(t) and not _CONSULT_NEG_RE.search(t)):
            bad.append("consult MISS (should fire): " + repr(t))
    for t in cons_off:
        if _CONSULT_RE.search(t) and not _CONSULT_NEG_RE.search(t):
            bad.append("consult FALSE-FIRE (should stay silent): " + repr(t))
    if "USING: skill-concierge:consult" not in CONSULT_MANDATE:
        bad.append("consult mandate: must name the USING line")
    if "SKILL_CONSULT_ROUTE" in CONSULT_MANDATE:
        bad.append("consult mandate: operator kill-switch note must not ride in the agent-facing line")
    if not CONSULT_ROUTE:
        bad.append("consult gate: default must be ON (SKILL_CONSULT_ROUTE unset = on)")

    # Plugin-enablement gate (ADR-0052 + ADR-0053): Claude AND OMP sessions gate plugin
    # rows and chain-successors on the merged INVOCABLE_PLUGIN_IDS (OMP's set unions the
    # claude registry + OMP registry enablement); DSH/Cline have no plugin registry, so
    # namespaced rows drop and plain rows pass; codex/commandcode/zcode keep their
    # foreign/twin lane semantics (pass); None filters nothing; the flag filters nothing;
    # non-namespaced rows pass.
    _saved_pg = (RUNNING_HARNESS, INVOCABLE_PLUGIN_IDS, PLUGIN_GATE)
    try:
        for lane in ("claude", "omp"):
            RUNNING_HARNESS, PLUGIN_GATE = lane, True
            INVOCABLE_PLUGIN_IDS = {"onplugin"}
            if not _plugin_gate_ok("onplugin:skill"):
                bad.append(f"plugin-enablement gate: {lane} invocable plugin row must survive")
            if _plugin_gate_ok("offplugin:skill"):
                bad.append(f"plugin-enablement gate: {lane} session-disabled plugin row must drop")
            if not _plugin_gate_ok("plain-skill"):
                bad.append(f"plugin-enablement gate: {lane} non-namespaced row must pass")
            INVOCABLE_PLUGIN_IDS = None
            if not _plugin_gate_ok("offplugin:skill"):
                bad.append(f"plugin-enablement gate: {lane} UNKNOWN manifest must filter nothing")
            INVOCABLE_PLUGIN_IDS = {"onplugin"}
        PLUGIN_GATE = False
        for lane in ("claude", "omp"):
            RUNNING_HARNESS = lane
            if not _plugin_gate_ok("offplugin:skill"):
                bad.append(f"plugin-enablement gate: {lane} flag off must filter nothing")
        PLUGIN_GATE = True
        for lane in ("dsh", "cline"):
            RUNNING_HARNESS = lane
            if _plugin_gate_ok("onplugin:skill"):
                bad.append(f"plugin-enablement gate: {lane} namespaced plugin row must drop (no registry)")
            if not _plugin_gate_ok("plain-skill"):
                bad.append(f"plugin-enablement gate: {lane} plain row must pass")
        for lane in ("codex", "commandcode", "zcode"):
            RUNNING_HARNESS = lane
            if not _plugin_gate_ok("offplugin:skill"):
                bad.append(f"plugin-enablement gate: {lane} must keep lane semantics (foreign/twin owns it)")
    finally:
        RUNNING_HARNESS, INVOCABLE_PLUGIN_IDS, PLUGIN_GATE = _saved_pg

    # Account-synced skills (`claude-synced`, named `anthropic-skills:<name>`): foreign in every
    # lane but Claude; the Claude gate passes them on SCOPE, never on the spoofable name; they
    # never enter another harness's foreign annex; their chain bucket is read only under Claude.
    _saved_sy = (RUNNING_HARNESS, INVOCABLE_PLUGIN_IDS, PLUGIN_GATE, FOREIGN_SCOPES,
                 _post_json, _SIDECAR_PATH, CROSS_HARNESS)
    try:
        for lane in ("codex", "commandcode", "omp", "zcode", "dsh", "cline", "claude"):
            RUNNING_HARNESS = lane
            if (lane == "claude") == ("claude-synced" in _foreign_scopes()):
                bad.append(f"synced: claude-synced foreign membership wrong under {lane}")
        PLUGIN_GATE, INVOCABLE_PLUGIN_IDS = True, {"onplugin"}
        RUNNING_HARNESS = "claude"
        if not _plugin_gate_ok("anthropic-skills:x", scope="claude-synced"):
            bad.append("synced gate: claude must pass a claude-synced row")
        for spoof in ("plugin", "zcode-plugin", "omp-plugin"):
            if _plugin_gate_ok("anthropic-skills:x", scope=spoof):
                bad.append(f"synced gate: a {spoof} row named anthropic-skills:x must NOT pass")
        with tempfile.TemporaryDirectory() as _d:
            _SIDECAR_PATH = Path(_d) / "next-skills.json"
            _SIDECAR_PATH.write_text(json.dumps({"claude-synced": {"anthropic-skills:x": []},
                                                 "personal": {"plain": []}}), encoding="utf-8")
            if not _plugin_gate_ok("anthropic-skills:x"):
                bad.append("synced gate: a hint name in the sidecar claude-synced bucket must pass")
            if _plugin_gate_ok("anthropic-skills:y"):
                bad.append("synced gate: a hint name absent from the claude-synced bucket must drop")
            if "anthropic-skills:x" not in _visible_sidecar_names():
                bad.append("synced mirror: claude must read the claude-synced chain bucket")
            for lane in ("omp", "dsh", "cline"):
                RUNNING_HARNESS = lane
                if _plugin_gate_ok("anthropic-skills:x", scope="claude-synced") or \
                        _plugin_gate_ok("anthropic-skills:x"):
                    bad.append(f"synced gate: {lane} must never pass a synced skill")
            for lane in ("codex", "zcode", "commandcode", "omp"):
                RUNNING_HARNESS = lane
                if "anthropic-skills:x" in _visible_sidecar_names():
                    bad.append(f"synced mirror: {lane} must not read the claude-synced bucket")
        RUNNING_HARNESS, CROSS_HARNESS = "codex", True
        FOREIGN_SCOPES = _foreign_scopes()
        _cap = []
        _post_json = lambda url, payload, timeout: (_cap.append(payload) or {"result": {"groups": []}})
        _retrieve_foreign([0.0])
        _any = _cap[0]["filter"]["must"][0]["match"]["any"] if _cap else ["<no request>"]
        if "claude-synced" in _any or "plugin" not in _any:
            bad.append(f"synced annex: the foreign-annex scope list must exclude claude-synced: {_any!r}")
    finally:
        (RUNNING_HARNESS, INVOCABLE_PLUGIN_IDS, PLUGIN_GATE, FOREIGN_SCOPES,
         _post_json, _SIDECAR_PATH, CROSS_HARNESS) = _saved_sy

    # (14) ADR-0054 harness-message lane: every harness-generated prompt shape is caught at the
    # prompt head; human prompts, OMP worker briefs, consult asks and a PASTED block
    # mid-prompt are not. Lane is ON by default.
    harness_fire = [
        "<task-notification>\n<task-id>b1</task-id>\n<summary>Monitor event: \"x\"</summary>",
        "<system-reminder> Last turn had no tool call → session idle. Reminder 1 of 3.",
        "<cross-session-message from=\"uds:/tmp/x.sock\" from-name=\"hoivu\"> FYI",
        "<teammate-message teammate_id=\"v7-planner\" color=\"blue\">{\"type\":\"idle\"}",
        "Another Claude session sent a message: <teammate-message teammate_id=\"t\">",
        "[Request interrupted by user for tool use]",
        "[SYSTEM NOTIFICATION - NOT USER INPUT]\nThis is an automated background-task event",
        "This session is being continued from a previous conversation that ran out of context.",
        "<file name=\"/var/folders/vz/T/omp-msum-o650bgz2.txt\">\nSummarize the following agent turn",
        "  <task-notification> leading whitespace still matches",
        "[Cross-session idle notice] \"peer\", which you asked to be notified about, is idle now",
    ]
    harness_off = [
        "please give a /progress-map of the build and track our implementation progress",
        "Complete assignment thoroughly:\n\n# Target\nUpdate plans/reports/x.md (EN) and its VN twin",
        "look at this <task-notification> I pasted from another session and tell me what it means",
        "commit & push pls and ensure a clean worktree afterwards",
        "which set of skills should we be using for this docx export task",
        "<file name=\"/Users/me/notes.txt\">\nsummarize my own notes file for me please",
        "what does [Cross-session idle notice] mean when it shows up in my session?",
    ]
    for p in harness_fire:
        if not _HARNESS_MSG_RE.match(p):
            bad.append(f"harness-message lane must fire on: {p[:50]!r}")
    for p in harness_off:
        if _HARNESS_MSG_RE.match(p):
            bad.append(f"harness-message lane must NOT fire on: {p[:50]!r}")
    if not HARNESS_SKIP:
        bad.append("harness-message lane must be ON by default (ENFORCER_HARNESS_SKIP unset)")

    # (6c) ADR-0054: a route can never resurface a BLOCKLISTED skill (ADR-0046 outranks it),
    # and under a harness where `personal` is foreign a bare route target must pass the
    # invocable-twin test (ADR-0034 invariant). ADR-0057: Command Code's `personal` scope
    # follows the live shelf, like ZCode's.
    _saved_6c = (_ROUTES, BLOCKLIST, RUNNING_HARNESS, FOREIGN_SCOPES,
                 _commandcode_shares_personal_shelf)
    try:
        _ROUTES = [("deploy", "victim")]
        BLOCKLIST = frozenset({"victim"})
        if _route_hits("please deploy now") != []:
            bad.append("blocklisted skill resurfaced via a deterministic route (ADR-0046 bypass)")
        BLOCKLIST = frozenset()
        if [n for n, _d, _s in _route_hits("please deploy now")] != ["victim"]:
            bad.append("route must fire once the blocklist no longer names its skill")
        RUNNING_HARNESS = "commandcode"
        _commandcode_shares_personal_shelf = lambda: True
        if "personal" in _foreign_scopes():
            bad.append("commandcode on a shared shelf (~/.commandcode/skills -> ~/.claude/skills) "
                       "must treat personal as invocable (ADR-0057)")
        _commandcode_shares_personal_shelf = lambda: False
        FOREIGN_SCOPES = _foreign_scopes()
        if "personal" not in FOREIGN_SCOPES:
            bad.append("commandcode on a divergent shelf cannot see ~/.claude/skills — personal "
                       "must stay foreign (ADR-0057)")
        _ROUTES = [("commit and push", "ak-git")]
        if _route_hits("commit and push please") != []:
            bad.append("divergent shelf: a route pinned a personal-root skill Command Code "
                       "cannot invoke (ADR-0034)")
    finally:
        (_ROUTES, BLOCKLIST, RUNNING_HARNESS, FOREIGN_SCOPES,
         _commandcode_shares_personal_shelf) = _saved_6c

    if bad:
        print("enforcer --selftest FAIL:")
        for b in bad:
            print("  " + b)
        return 1
    print(f"enforcer --selftest OK: refusal guard ({len(must_fire)} fire / "
          f"{len(must_not_fire)} silent) + ranked-mandate %-share "
          f"+ actionability imperative-veto ({len(imp_fire)} fire / {len(imp_off)} off) "
          "+ consult-intent routing (ADR-0049) "
          "+ keepoff-drop + blocklist-drop (ADR-0046) "
          "+ deterministic-routes (ADR-0054 config, ON) + authorized-skip tier "
          f"(4 injects on / silent-off) + selfref over-fire lane ({len(selfref_fire)} fire / "
          f"{len(selfref_off)} off) "
          f"+ harness-message lane ({len(harness_fire)} fire / {len(harness_off)} off) "
          "+ cross-harness annex "
          "+ plugin-enablement gate (ADR-0052+0053) "
          "+ CJK word-count (pre-gate no longer swallows no-space scripts)")
    return 0
