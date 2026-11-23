"""Consistency of the container files with the project, checked without Docker.

The container itself is checked by scripts/smoke-test.sh (needs Docker).
"""
from __future__ import annotations

import re
import tomllib
from pathlib import Path

import itop_mcp_poc

ROOT = Path(__file__).resolve().parent.parent
CONFIG_VARS = ("ITOP_BASE_URL", "MCP_RESOURCE_URL", "ITOP_OAUTH_ISSUER", "ITOP_API_VERSION", "MCP_MAX_ROWS",
               "MCP_HOST", "MCP_PORT", "MCP_AUDIT_LOG")
COMPOSE_VARS = ("MCP_PUBLISH_PORT", "MCP_LOG_DIR")


def _read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def _pins(lines: list[str]) -> dict[str, str]:
    pins = {}
    for line in lines:
        line = line.split("#", 1)[0].strip()
        if m := re.fullmatch(r"([A-Za-z0-9_.-]+)(?:\[[^\]]*\])?==([^\s;]+)", line):
            pins[m.group(1).lower().replace("_", "-")] = m.group(2)
    return pins


def test_compose_image_tag_matches_project_version():
    tags = re.findall(r"^\s*image:\s*itop-mcp-server:(\S+)\s*$", _read("compose.yaml"), re.M)

    assert tags == [itop_mcp_poc.__version__]


def test_image_is_based_on_python_313_slim():
    assert re.search(r"^FROM python:3\.13-slim\s*$", _read("Dockerfile"), re.M)


def test_env_example_lists_every_variable():
    text = _read(".env.example")

    for var in CONFIG_VARS + COMPOSE_VARS:
        assert re.search(rf"^#?\s*{var}=", text, re.M), f"{var} missing in .env.example"


def test_env_example_marks_required_values_and_sets_them():
    text = _read(".env.example")

    for var in ("ITOP_BASE_URL", "MCP_RESOURCE_URL"):
        assert re.search(rf"^# REQUIRED\..*\n(?:#.*\n)*{var}=\S+", text, re.M), f"{var} not marked REQUIRED"


def test_lock_file_pins_the_pyproject_dependencies_exactly():
    project = tomllib.loads(_read("pyproject.toml"))["project"]
    lock = _pins(_read("requirements.lock").splitlines())

    for name, version in _pins(project["dependencies"]).items():
        assert lock.get(name) == version, f"{name}: pyproject {version}, lock {lock.get(name)}"
    # every line of the lock file is an exact pin
    lines = [l for l in _read("requirements.lock").splitlines() if l.strip() and not l.startswith("#")]
    assert len(lines) == len(lock)


def test_compose_publishes_on_loopback_and_mounts_logs_at_default_path():
    compose = _read("compose.yaml")

    assert re.search(r'^\s*- "127\.0\.0\.1:\$\{MCP_PUBLISH_PORT:-8130\}:8130"\s*$', compose, re.M)
    assert re.search(r"^\s*- \$\{MCP_LOG_DIR:-\./logs\}:/data/logs\s*$", compose, re.M)
    assert re.search(r"^\s*read_only: true\s*$", compose, re.M)
    assert re.search(r"^\s*restart: unless-stopped\s*$", compose, re.M)


def test_build_backend_is_pinned_and_used_by_the_image_build():
    build_lock = _pins(_read("requirements-build.lock").splitlines())
    requires = _pins(tomllib.loads(_read("pyproject.toml"))["build-system"]["requires"])
    dockerfile = _read("Dockerfile")

    # setuptools and wheel pinned exactly, pyproject.toml and the build lock agree
    assert {"setuptools", "wheel"} <= build_lock.keys()
    assert requires == {name: build_lock[name] for name in ("setuptools", "wheel")}
    # every line of the build lock is an exact pin
    lines = [l for l in _read("requirements-build.lock").splitlines() if l.strip() and not l.startswith("#")]
    assert len(lines) == len(build_lock)
    # the image installs the pinned backend and builds the server with it, without build isolation
    # (which would resolve the build backend freshly from pyproject.toml)
    assert re.search(r"^COPY .*\brequirements-build\.lock\b", dockerfile, re.M)
    assert re.search(r"pip install --no-deps -r requirements-build\.lock", dockerfile)
    assert re.search(r"pip install --no-deps --no-build-isolation \.", dockerfile)
    assert "!requirements-build.lock" in _read(".dockerignore").splitlines()


def test_env_file_switch_is_marked_as_smoke_test_only():
    compose = _read("compose.yaml")
    comment = re.search(r"((?:^[ \t]*#.*\n)+)[ \t]*env_file: \$\{MCP_ENV_FILE:-\.env\}", compose, re.M)

    assert comment, "env_file needs a comment directly above it"
    assert "scripts/smoke-test.sh" in comment.group(1)
    assert "MCP_PUBLISH_PORT" in comment.group(1) and "MCP_LOG_DIR" in comment.group(1)
    # .env.example does not offer the switch as an operator setting
    assert "MCP_ENV_FILE" not in _read(".env.example")
