"""Every port-deriving caller — the vendored index owner, doctor.py, enforcer.py,
bin/skill-search-mcp and setup.sh — lands on the SAME port for every input in the shared case
table (tests/port_cases.py). The Python callers all route through
vendor/skill-search/skill_search/ports.py; the two bash scripts run before that package is
importable and keep a native `_safe_port` implementing the same rule.

Every helper below runs the CALLER'S OWN CODE — the real module for the Python callers, the
real lines extracted verbatim for the bash ones (including the launcher's health-check curl
line, the value actually USED, not just the one assigned) — never a reimplementation, so
reverting a single caller's line fails a test here."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

from port_cases import SCALAR_CASES, URL_CASES

ROOT = Path(__file__).resolve().parents[1]
VENDOR_SRC = ROOT / "vendor" / "skill-search"
DOCTOR = ROOT / "scripts" / "doctor.py"
ENFORCER = ROOT / "hooks" / "scripts" / "enforcer.py"
LAUNCHER = ROOT / "bin" / "skill-search-mcp"
SETUP = ROOT / "setup.sh"

_PORT_ENV_KEYS = ("SKILL_OWNER_QUERY_PORT", "SKILL_OWNER_EMBED_PORT",
                  "SKILL_QDRANT_URL", "EMBED_SHIM_PORT")

sys.path.insert(0, str(VENDOR_SRC))
from skill_search import ports  # noqa: E402


def _bash(script, *args):
    r = subprocess.run(["bash", "-c", script, "_", *args], capture_output=True, text=True,
                       timeout=20)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def _extract_bash_func(path, name):
    lines = path.read_text().splitlines()
    start = next(i for i, l in enumerate(lines) if l.startswith(f"{name}() {{"))
    end = next(i for i in range(start + 1, len(lines)) if lines[i] == "}")
    return "\n".join(lines[start:end + 1])


def _setup_embed_port(raw):
    """setup.sh's real `_safe_port` plus its real `EPORT=` line."""
    line = next(l for l in SETUP.read_text().splitlines() if l.startswith("EPORT="))
    assert "_safe_port" in line and "EMBED_SHIM_PORT" in line
    return _bash(f'{_extract_bash_func(SETUP, "_safe_port")}\nEMBED_SHIM_PORT="$1"\n{line}\n'
                 'echo "$EPORT"', raw)


def _launcher_health_url(raw):
    """bin/skill-search-mcp's real `_safe_port`, its real `EMBED_PORT=` line, and the URL its
    real health-check curl line actually requests (curl is stubbed to print its arguments).
    A revert of EITHER line to a raw `${EMBED_SHIM_PORT...}` read changes this URL."""
    lines = LAUNCHER.read_text().splitlines()
    assign = next(l for l in lines if l.startswith("EMBED_PORT="))
    curl_line = next(l for l in lines if "curl -s -m 1" in l and "/health" in l)
    call = curl_line[curl_line.index("curl"):curl_line.index(">/dev/null")].strip()
    script = (f'{_extract_bash_func(LAUNCHER, "_safe_port")}\n'
              'curl() { printf "%s\\n" "$@" | grep "^http"; }\n'
              f'EMBED_SHIM_PORT="$1"\n{assign}\n{call}')
    return _bash(script, raw)


def _setup_store_port(qdrant_url, tmp_path):
    """setup.sh's real store-port lines, run with $VENV/bin/python pointing at this
    interpreter with the vendored engine importable — the same module the installed venv
    carries after setup.sh's own reinstall step."""
    lines = SETUP.read_text().splitlines()
    start = next(i for i, l in enumerate(lines) if l.startswith('store_port="$('))
    end = next(i for i in range(start, len(lines)) if lines[i].rstrip().endswith(')"'))
    block = "\n".join(lines[start:end + 1])
    venv_bin = tmp_path / "venv" / "bin"
    venv_bin.mkdir(parents=True, exist_ok=True)
    shim = venv_bin / "python"
    shim.write_text(f'#!/bin/sh\nPYTHONPATH="{VENDOR_SRC}" exec "{sys.executable}" "$@"\n')
    shim.chmod(0o755)
    return _bash(f'VENV="{tmp_path / "venv"}"\nQURL="$1"\n{block}\necho "$store_port"',
                 qdrant_url)


def _run_module(path, name, env_overrides, expr):
    env = {k: v for k, v in os.environ.items() if k not in _PORT_ENV_KEYS}
    env.update(env_overrides)
    env.setdefault("ENFORCER_JEV_GATE", "0")
    script = ("import importlib.util\n"
              f"spec = importlib.util.spec_from_file_location({name!r}, {str(path)!r})\n"
              "mod = importlib.util.module_from_spec(spec)\n"
              "spec.loader.exec_module(mod)\n"
              f"print({expr})\n")
    r = subprocess.run([sys.executable, "-c", script], env=env, capture_output=True,
                       text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip().splitlines()


def _owner_ports(env_overrides):
    env = {k: v for k, v in os.environ.items() if k not in _PORT_ENV_KEYS}
    env.update(env_overrides)
    env["PYTHONPATH"] = str(VENDOR_SRC)
    r = subprocess.run([sys.executable, "-c",
                        "from skill_search import index_owner as o; "
                        "print(o.QUERY_PORT); print(o.EMBED_PORT)"],
                       env=env, capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    query, embed = r.stdout.strip().splitlines()
    return int(query), int(embed)


def _doctor(env_overrides):
    store, embed, qurl = _run_module(DOCTOR, "doctor_pa", env_overrides,
                                     "mod.OWNER_PORTS[0], mod.OWNER_PORTS[1], mod.QURL, sep='\\n'")
    return int(store), int(embed), qurl


def _enforcer(env_overrides):
    embed, qurl = _run_module(ENFORCER, "enforcer_pa", env_overrides,
                              "mod.EMBED_PORT, mod.QDRANT_URL, sep='\\n'")
    return int(embed), qurl


@pytest.mark.parametrize("raw,valid", SCALAR_CASES)
def test_every_caller_derives_the_same_embed_port(raw, valid):
    expected = valid if valid is not None else 6363
    assert _owner_ports({"EMBED_SHIM_PORT": raw})[1] == expected
    assert _doctor({"EMBED_SHIM_PORT": raw})[1] == expected
    assert _enforcer({"EMBED_SHIM_PORT": raw})[0] == expected
    assert _setup_embed_port(raw) == str(expected)
    assert _launcher_health_url(raw) == f"http://127.0.0.1:{expected}/health"


@pytest.mark.parametrize("url,default_port,expected_url", URL_CASES)
def test_every_caller_derives_the_same_store_address(url, default_port, expected_url, tmp_path):
    expected_port = ports.url_port(expected_url, default_port)
    env = {"SKILL_QDRANT_URL": url} if url else {}
    assert _owner_ports(env)[0] == expected_port
    doctor_store, _, doctor_url = _doctor(env)
    assert doctor_store == expected_port
    assert doctor_url.rstrip("/") == (expected_url if url else "http://localhost:6333")
    assert _enforcer(env)[1] == (expected_url if url else "http://localhost:6333")
    assert _setup_store_port(url, tmp_path) == str(expected_port)


def test_ipv6_store_url_does_not_crash_doctor_or_the_enforcer():
    """A bracketed IPv6 loopback — the address the owner itself binds — must stay a parseable
    URL everywhere; dropping the brackets used to crash doctor at import."""
    for url in ("http://[::1]", "http://[::1]:", "http://[::1]:7333"):
        _, _, doctor_url = _doctor({"SKILL_QDRANT_URL": url})
        _, enforcer_url = _enforcer({"SKILL_QDRANT_URL": url})
        assert doctor_url.startswith("http://[::1]:") and enforcer_url.startswith("http://[::1]:")
