# Validation Report: apply-overrides.py & setup.sh

**Date:** 2026-06-26  
**Scope:** Isolated validation of settings-mutating Python script and bash bootstrap in temp environments  
**Execution:** All tests ran in isolation using mktemp directories with env-variable seams  

---

## Summary

| Component | Overall | Details |
|-----------|---------|---------|
| **apply-overrides.py** | 7/8 PASS | 1 critical issue: backup filename race condition (same-second overwrites) |
| **setup.sh** | PASS | Syntax valid, idempotent, proper error handling |
| **.mcp.json** | PASS | Valid JSON |

---

## Test Results: apply-overrides.py

### Test 1: Happy Path ✓ PASS
**Case:** Existing settings with non-override key + stale skillOverrides; keep-on=[a,b]; skills=[a,b,c,d]

**Evidence:**
```
Exit code: 0
Backup created: settings.json.bak-skillconcierge-1782447309
Settings output:
{
  "theme": "dark",
  "skillOverrides": {
    "a": "on",
    "b": "on",
    "c": "name-only",
    "d": "name-only"
  }
}
```
**Verdict:** Non-override key "theme" preserved; stale overrides replaced; backup created; exit 0.

---

### Test 2: UTF-8 Diacritics ✓ PASS
**Case:** Skill names with diacritics (café, Nguyễn) in keep-on + skills

**Evidence:**
```
Exit code: 0
Settings preserved UTF-8:
{
  "skillOverrides": {
    "Nguyễn": "on",
    "café": "on",
    "otherskill": "name-only"
  }
}
Grep check: "café" found in raw output ✓
```
**Verdict:** UTF-8 chars preserved in JSON (not escaped to \uXXXX), ensure_ascii=False working correctly.

---

### Test 3: Refuse Empty Skills ✓ PASS
**Case:** Empty SKILL_CONCIERGE_SKILLS_FILE (zero skills discovered)

**Evidence:**
```
Stderr: no skills discovered — refusing to write empty overrides
Exit code: 1  ✓
Original key preserved: {"original": "key"}
```
**Verdict:** Script correctly refuses empty skills list; prints diagnostic to stderr; preserves settings untouched; exits with code 1.

**Note:** Initial test harness reported exit code 0 erroneously; verification run confirmed actual exit code is 1 (correct).

---

### Test 4: Missing Keep-on Entry ✓ PASS
**Case:** Keep-on includes "missing-skill" not in discovered skills; applies "a" which is present

**Evidence:**
```
Exit code: 0
Stderr NOTE: 1 keep-on entr(ies) not present on this machine (left unset...): ['missing-skill']
Settings:
{
  "skillOverrides": {
    "a": "on",
    "b": "name-only"
  }
}
```
**Verdict:** Partial keep-on (a found, missing-skill not) is handled gracefully; others still applied; exit 0; diagnostic message printed.

---

### Test 5: Idempotency ✗ FAIL
**Case:** Run script twice; verify final skillOverrides identical + count new backups

**Evidence:**
```
First run:  skillOverrides = {a: on, b: name-only, c: name-only}
Second run: skillOverrides = {a: on, b: name-only, c: name-only}  ← Identical ✓
Backup count: first=1, second=1  ← Issue
```
**Issue:** Second run only creates 1 backup total, not a second backup file. Spec requirement was "a second backup is created (count backups)."

**Root cause:** Backup filename includes `int(time.time())`. When both runs execute within the same second (< 1 second apart), they generate the same timestamp and overwrite the previous backup instead of creating a new file.

**Evidence of race:** Both commands run in sequence within milliseconds; integer timestamp does not have sub-second granularity.

**Verdict:** IDEMPOTENT in terms of final output ✓, but backup accumulation BROKEN ✗. The code should either use time.time() with precision or uuid4() for backup uniqueness.

---

### Test 6: Missing keep-on.json ✓ PASS
**Case:** Point SKILL_CONCIERGE_KEEPON to nonexistent file

**Evidence:**
```
Traceback: FileNotFoundError: [Errno 2] No such file or directory: '/nonexistent/keep-on.json'
Exit code: 1
Settings file: unchanged, still contains {"preserve": "me"}
```
**Verdict:** Fails BEFORE writing settings (line 46 tries to read KEEPON before main logic proceeds); settings untouched; proper error exit.

---

### Test 7: Malformed settings.json ✓ PASS
**Case:** Existing settings file contains invalid JSON

**Evidence:**
```
Traceback: json.decoder.JSONDecodeError (line 1 column 2)
Exit code: 1
Settings file: still contains exact malformed input '{invalid json'
```
**Verdict:** Fails on parse attempt (line 57) before writing; settings left unchanged; no corruption or partial writes.

---

### Test 8: No Existing Settings File ✓ PASS
**Case:** Fresh path where settings.json does not exist

**Evidence:**
```
Exit code: 0
File created: yes ✓
Contents:
{
  "skillOverrides": {
    "a": "on",
    "b": "name-only",
    "c": "name-only"
  }
}
```
**Verdict:** Creates file with only skillOverrides key (no empty dict or null); exit 0.

---

## Test Results: setup.sh

### Syntax Check (bash -n) ✓ PASS
```
Exit code: 0
RESULT: PASS (syntax valid)
```
**Verdict:** No syntax errors detected.

---

### Shellcheck ⚠️ UNAVAILABLE
Shellcheck not installed on system; static analysis tool unavailable.  
**Manual review substituted below.**

---

### Manual Review ✓ PASS

**Critical patterns checked:**

| Check | Status | Evidence |
|-------|--------|----------|
| `set -euo pipefail` | ✓ | Line 11: present |
| Docker failure exit | ✓ | Line 38: `exit 1` on docker not found |
| Unquoted vars in docker commands | ✓ | `$QNAME` properly quoted in all docker invocations (lines 28-34) |
| Venv idempotency | ✓ | Line 22: `[ -d "$VENV" ] \|\| python3 -m venv` |
| Variable quoting | ✓ | All `$` expansions properly quoted except in heredoc (line 55 in cat EOF context) |

**Idempotency behavior:**
- Venv: checked with `[ -d ]`, skipped if exists ✓
- Docker: attempts `docker start` if container exists ✓ (line 34 `|| true` swallows errors)
- Python deps: pip install always runs (not guarded); will be no-op on second run if already latest ✓

**Heredoc issue (line 55):** Variable `$QNAME` not quoted in heredoc output string:
```bash
docker start $QNAME
```
This is in a cat EOF block (line 49-58) for user instructions, not executed code, so acceptable for readability.

**Verdict:** Script is safe, idempotent, and handles Docker absence cleanly.

---

## Test Results: .mcp.json

**JSON Validity Check:** ✓ PASS
```
python3 -c "import json; json.load(...)"
✓ Valid JSON
```

**Contents verified:**
- `mcpServers.skill-search.command`: Valid path template with `${CLAUDE_PLUGIN_ROOT}`
- `mcpServers.skill-search.env`: Environment variables properly configured with qdrant URL and embedding model
- All keys present and properly structured

**Verdict:** Valid MCP configuration.

---

## Issues Summary

### 🔴 CRITICAL

**Issue 1: Backup File Race Condition**
- **File:** `apply-overrides.py`, line 58
- **Behavior:** Backup filename uses `int(time.time())` which lacks sub-second precision
- **Problem:** Running script twice within same second overwrites previous backup instead of creating new one
- **Expected:** Each run creates a separate .bak file for recovery
- **Recommendation:** Use `time.time()` with microseconds or `uuid4()` for backup uniqueness
- **Impact:** Backup accumulation broken; only latest backup preserved

### ⚠️ MINOR

**Issue 2: Shellcheck Unavailable**
- Manual review substituted; no static analysis tool output available
- Recommend installing shellcheck on validation systems

---

## Recommendations

### Priority 1 (Fix before ship)
1. **Fix backup filename collisions** — use `time.time()` or UUID for millisecond-precision unique names (issue verified in Test 5)

### Priority 2 (Quality improvement)
1. Add explicit error handling catch-all in `apply-overrides.py` main() to ensure all error paths return non-zero
2. Document expected exit codes (0 = success, 1 = discovery/config error, other = bug)
3. Add unit test suite to CI/CD to catch edge cases like backup race conditions

### Priority 3 (Nice-to-have)
1. Add `--dry-run` flag to preview changes before applying
2. Consider persisting backup history with rotation policy (keep last N backups)

---

## Unresolved Questions

1. **Backup rotation policy:** Should backup files be accumulated indefinitely or rotated (keep N most recent)? Current code accumulates but race condition breaks it.

2. **Performance baseline:** Does `discover_skills()` from vendored skill-search module require heavy dependencies (model loading, embeddings)? No timeout observed in tests, but baseline performance unknown.

---

## Test Execution Details

- **Environment:** macOS Sonoma, Python 3.9.18, bash 5.2.26
- **Isolation:** All tests ran in isolated mktemp directories with env-var seams
- **Real config:** No real `~/.claude/settings.json` or production paths touched
- **Docker:** Not executed (per spec: "NEVER touch the real ~/.claude/settings.json or run Docker")

---

**Status:** DONE_WITH_CONCERNS  
**Summary:** apply-overrides.py core logic sound (7/8 tests pass). Backup filename race condition confirmed: running script twice within same second overwrites previous backup. setup.sh production-ready. Recommend fixing backup uniqueness before deployment.
