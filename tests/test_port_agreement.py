"""Every port-deriving caller — the vendored index owner, doctor.py, enforcer.py,
bin/skill-search-mcp, and setup.sh — must apply the identical STRICT malformed/out-of-range
-> default rule (scripts/port_grammar.py: ASCII digits only, 1-65535) for SKILL_QDRANT_URL
and EMBED_SHIM_PORT. Two prior gaps this file guards against:

1. Before the first fix, the owner and doctor fell back to the well-known port on a bad
   value while the enforcer, the launcher, and setup.sh kept trying the bad one — a single
   misconfigured env var left half the callers unable to reach the half that actually came
   up (test_every_caller_agrees_on_the_*_fallback, test_a_valid_configured_port_is_left_alone).
2. Before the second fix, callers built on a bare `int(raw)` (doctor.py, enforcer.py) were
   MORE lenient than bash's `_safe_port` and `urlsplit().port`: `int()` accepts leading and
   trailing whitespace, a leading '+' sign, an underscore digit-group separator, and
   full-width Unicode decimal digits, and treats "0" as valid — so those callers derived a
   DIFFERENT port than the strict ones from the identical env var
   (test_every_caller_rejects_lenient_forms_a_bare_int_would_accept).

Every helper below runs the CALLER'S OWN CODE — the real module for the Python callers, the
function extracted verbatim alongside its real call-site line for the bash ones — never a
reimplementation, so reverting a single caller's line fails the corresponding test."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
VENDOR_SRC = ROOT / "vendor" / "skill-search"
DOCTOR = ROOT / "scripts" / "doctor.py"
ENFORCER = ROOT / "hooks" / "scripts" / "enforcer.py"
LAUNCHER = ROOT / "bin" / "skill-search-mcp"
SETUP = ROOT / "setup.sh"

_PORT_ENV_KEYS = ("SKILL_OWNER_QUERY_PORT", "SKILL_OWNER_EMBED_PORT",
                  "SKILL_QDRANT_URL", "EMBED_SHIM_PORT")


def _extract_bash_func(path, name):
    lines = path.read_text().splitlines()
    start = next(i for i, l in enumerate(lines) if l.startswith(f"{name}() {{"))
    end = next(i for i in range(start + 1, len(lines)) if lines[i] == "}")
    return "\n".join(lines[start:end + 1])


def _setup_embed_port(raw):
    """Runs setup.sh's REAL embed-port call site (`EPORT="$(_safe_port ...)"`, line 35),
    extracted verbatim alongside `_safe_port` itself — not a reimplementation. Guards the
    M-1 gap: a caller reverted to read EMBED_SHIM_PORT directly, bypassing `_safe_port`
    entirely, would slip past a test that only re-runs the function in isolation."""
    func = _extract_bash_func(SETUP, "_safe_port")
    lines = SETUP.read_text().splitlines()
    line = next(l for l in lines if l.startswith("EPORT="))
    assert 'EPORT="$(_safe_port "${EMBED_SHIM_PORT:-}" 6363)"' in line
    script = f'{func}\nEMBED_SHIM_PORT="$1"\n{line}\necho "$EPORT"'
    r = subprocess.run(["bash", "-c", script, "_", raw], capture_output=True, text=True, timeout=10)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def _launcher_embed_port(raw):
    """Runs bin/skill-search-mcp's REAL embed-port call site (`EMBED_PORT="$(_safe_port
    ...)"`, line 137), extracted verbatim alongside `_safe_port` itself — the same M-1
    guard as `_setup_embed_port`, for the other bash caller."""
    func = _extract_bash_func(LAUNCHER, "_safe_port")
    lines = LAUNCHER.read_text().splitlines()
    line = next(l for l in lines if l.startswith("EMBED_PORT="))
    assert 'EMBED_PORT="$(_safe_port "${EMBED_SHIM_PORT:-}" 6363)"' in line
    script = f'{func}\nEMBED_SHIM_PORT="$1"\n{line}\necho "$EMBED_PORT"'
    r = subprocess.run(["bash", "-c", script, "_", raw], capture_output=True, text=True, timeout=10)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def _setup_store_port(qdrant_url):
    """Runs setup.sh's REAL two-line store-port pipeline (the sed extraction, then
    `_safe_port`), extracted verbatim, against `qdrant_url` — not a reimplementation of the
    sed pattern, which a test written independently could easily get subtly wrong."""
    func = _extract_bash_func(SETUP, "_safe_port")
    lines = SETUP.read_text().splitlines()
    idx = next(i for i, l in enumerate(lines) if l.startswith("store_port=") and "sed" in l)
    derive = "\n".join(lines[idx:idx + 2])
    assert 'store_port="$(_safe_port "$store_port" 6333)"' in derive
    script = f'{func}\nQURL="$1"\n{derive}\necho "$store_port"'
    r = subprocess.run(["bash", "-c", script, "_", qdrant_url], capture_output=True, text=True, timeout=10)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def _owner_ports(env_overrides):
    env = dict(os.environ)
    for k in _PORT_ENV_KEYS:
        env.pop(k, None)
    env.update(env_overrides)
    env["PYTHONPATH"] = str(VENDOR_SRC)
    script = "from skill_search import index_owner as io_; print(io_.QUERY_PORT); print(io_.EMBED_PORT)"
    r = subprocess.run([sys.executable, "-c", script], env=env, capture_output=True, text=True, timeout=20)
    assert r.returncode == 0, r.stderr
    query, embed = r.stdout.strip().splitlines()
    return int(query), int(embed)


def _doctor_ports(env_overrides):
    env = dict(os.environ)
    for k in _PORT_ENV_KEYS:
        env.pop(k, None)
    env.update(env_overrides)
    script = ("import importlib.util\n"
              f"spec = importlib.util.spec_from_file_location('doctor_pa', {str(DOCTOR)!r})\n"
              "mod = importlib.util.module_from_spec(spec)\n"
              "spec.loader.exec_module(mod)\n"
              "print(mod.OWNER_PORTS[0]); print(mod.OWNER_PORTS[1])\n")
    r = subprocess.run([sys.executable, "-c", script], env=env, capture_output=True, text=True, timeout=20)
    assert r.returncode == 0, r.stderr
    store, embed = r.stdout.strip().splitlines()
    return int(store), int(embed)


def _enforcer_ports(env_overrides):
    env = dict(os.environ)
    for k in _PORT_ENV_KEYS:
        env.pop(k, None)
    env.update(env_overrides)
    env.setdefault("ENFORCER_JEV_GATE", "0")
    script = ("import importlib.util\n"
              f"spec = importlib.util.spec_from_file_location('enforcer_pa', {str(ENFORCER)!r})\n"
              "mod = importlib.util.module_from_spec(spec)\n"
              "spec.loader.exec_module(mod)\n"
              "print(mod.EMBED_PORT); print(mod.QDRANT_URL)\n")
    r = subprocess.run([sys.executable, "-c", script], env=env, capture_output=True, text=True, timeout=20)
    assert r.returncode == 0, r.stderr
    embed, qdrant_url = r.stdout.strip().splitlines()
    return int(embed), qdrant_url


@pytest.mark.parametrize("raw", ["notaport", "70000", "-5", ""])
def test_every_caller_agrees_on_the_embed_port_fallback(raw):
    owner_query, owner_embed = _owner_ports({"EMBED_SHIM_PORT": raw})
    doctor_store, doctor_embed = _doctor_ports({"EMBED_SHIM_PORT": raw})
    enforcer_embed, _enforcer_qdrant = _enforcer_ports({"EMBED_SHIM_PORT": raw})
    launcher_embed = _launcher_embed_port(raw)
    setup_embed = _setup_embed_port(raw)

    assert owner_embed == 6363
    assert doctor_embed == 6363
    assert enforcer_embed == 6363
    assert launcher_embed == "6363"
    assert setup_embed == "6363"


@pytest.mark.parametrize("raw", ["http://127.0.0.1:notaport", "http://127.0.0.1:70000",
                                 "http://127.0.0.1:-5"])
def test_every_caller_agrees_on_the_store_port_fallback(raw):
    owner_query, _owner_embed = _owner_ports({"SKILL_QDRANT_URL": raw})
    doctor_store, _doctor_embed = _doctor_ports({"SKILL_QDRANT_URL": raw})
    _enforcer_embed, enforcer_qdrant = _enforcer_ports({"SKILL_QDRANT_URL": raw})
    setup_store = _setup_store_port(raw)

    assert owner_query == 6333
    assert doctor_store == 6333
    assert enforcer_qdrant == "http://localhost:6333"
    assert setup_store == "6333"


@pytest.mark.parametrize("raw", [" 7363", "7363 ", "+7363", "7_363", "７３６３", "0"])
def test_every_caller_rejects_lenient_forms_a_bare_int_would_accept(raw):
    """A bare Python `int(raw)` accepts leading/trailing whitespace, a leading sign, an
    underscore digit-group separator, and full-width Unicode decimal digits — and treats
    "0" as a valid non-negative integer. The strict port grammar (scripts/port_grammar.py,
    mirrored inline in index_owner.py, and bash's own `case … [!0-9]*` pattern) rejects
    every one of these; before this fix a caller built on plain `int()` would have derived
    a DIFFERENT port than one built on `urlsplit().port` or the bash grammar from the exact
    same env var."""
    owner_query, owner_embed = _owner_ports({"EMBED_SHIM_PORT": raw})
    doctor_store, doctor_embed = _doctor_ports({"EMBED_SHIM_PORT": raw})
    enforcer_embed, _enforcer_qdrant = _enforcer_ports({"EMBED_SHIM_PORT": raw})
    launcher_embed = _launcher_embed_port(raw)
    setup_embed = _setup_embed_port(raw)

    assert owner_embed == 6363, f"owner accepted {raw!r} as a port"
    assert doctor_embed == 6363, f"doctor accepted {raw!r} as a port"
    assert enforcer_embed == 6363, f"enforcer accepted {raw!r} as a port"
    assert launcher_embed == "6363", f"launcher accepted {raw!r} as a port"
    assert setup_embed == "6363", f"setup.sh accepted {raw!r} as a port"


def test_a_valid_configured_port_is_left_alone_everywhere():
    """The agreement rule must never override a VALID configuration — only a malformed or
    out-of-range one falls back to the default."""
    owner_query, owner_embed = _owner_ports({"SKILL_QDRANT_URL": "http://127.0.0.1:7333",
                                             "EMBED_SHIM_PORT": "7363"})
    doctor_store, doctor_embed = _doctor_ports({"SKILL_QDRANT_URL": "http://127.0.0.1:7333",
                                                "EMBED_SHIM_PORT": "7363"})
    enforcer_embed, enforcer_qdrant = _enforcer_ports({"SKILL_QDRANT_URL": "http://127.0.0.1:7333",
                                                       "EMBED_SHIM_PORT": "7363"})
    launcher_embed = _launcher_embed_port("7363")
    setup_embed = _setup_embed_port("7363")
    setup_store = _setup_store_port("http://127.0.0.1:7333")

    assert owner_query == doctor_store == 7333
    assert owner_embed == doctor_embed == enforcer_embed == 7363
    assert enforcer_qdrant == "http://127.0.0.1:7333"
    assert launcher_embed == setup_embed == "7363"
    assert setup_store == "7333"
