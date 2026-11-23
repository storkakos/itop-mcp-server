"""Konfiguration aus der Umgebung (Vertrag: .scratch/docker-build/spec.md).

Pflicht:   ITOP_BASE_URL, MCP_RESOURCE_URL
Optional:  ITOP_OAUTH_ISSUER  (Standard: <ITOP_BASE_URL>/env-production/altioo-oauth-server)
           ITOP_API_VERSION   (Standard: 1.3)
           MCP_MAX_ROWS       (Standard: 50)
           MCP_HOST           (Standard: 0.0.0.0, alle Schnittstellen im Container)
           MCP_PORT           (Standard: 8130)
           MCP_AUDIT_LOG      (Standard: /data/logs/mcp-itop-audit.log)

Fehlt ein Pflichtwert, gibt es keinen Rueckfall auf localhost: der Start bricht mit einer
Meldung ab, die die Variable nennt.

MCP_RESOURCE_URL muss eine http(s)-URL mit Host sein. Host (und Port) daraus sind die
oeffentlichen Host-Header-Werte, die der Reverse Proxy durchreicht (public_hosts).
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit

DEFAULT_API_VERSION = "1.3"
DEFAULT_MAX_ROWS = 50
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8130
DEFAULT_AUDIT_LOG = "/data/logs/mcp-itop-audit.log"
ISSUER_PATH = "/env-production/altioo-oauth-server"
DEFAULT_PORTS = {"http": 80, "https": 443}


class ConfigError(ValueError):
    """Ungueltige oder fehlende Konfiguration; die Meldung nennt die Variable."""


@dataclass(frozen=True)
class Config:
    itop_base_url: str
    resource_url: str
    issuer: str
    api_version: str
    max_rows: int
    host: str
    port: int
    audit_log: str
    # Host-Header-Werte, unter denen der Server oeffentlich erreichbar ist (aus MCP_RESOURCE_URL)
    public_hosts: tuple[str, ...]
    # Origin der MCP_RESOURCE_URL (scheme://host[:port])
    public_origin: str


def _optional(env: Mapping[str, str], name: str) -> str | None:
    value = (env.get(name) or "").strip()
    return value or None


def _required(env: Mapping[str, str], name: str) -> str:
    value = _optional(env, name)
    if value is None:
        raise ConfigError(f"{name} ist nicht gesetzt (Pflichtvariable, siehe .env.example)")
    return value


def _positive_int(env: Mapping[str, str], name: str, default: int) -> int:
    value = _optional(env, name)
    if value is None:
        return default
    try:
        number = int(value)
    except ValueError:
        raise ConfigError(f"{name} muss eine ganze Zahl sein, ist aber {value!r}") from None
    if number < 1:
        raise ConfigError(f"{name} muss groesser als 0 sein, ist aber {number}")
    return number


def _public_host(resource_url: str) -> tuple[tuple[str, ...], str]:
    """Host-Header-Werte und Origin aus MCP_RESOURCE_URL.

    Ohne Port in der URL: "host" und "host:<Standardport>" (Proxys senden beides).
    Mit Port: nur "host:port".
    """
    parts = urlsplit(resource_url)
    try:
        hostname, port = parts.hostname, parts.port
    except ValueError:
        hostname, port = None, None
    if parts.scheme not in DEFAULT_PORTS or not hostname:
        raise ConfigError(f"MCP_RESOURCE_URL muss eine http(s)-URL mit Host sein, ist aber {resource_url!r}")
    host = f"[{hostname}]" if ":" in hostname else hostname
    if port is None:
        return (host, f"{host}:{DEFAULT_PORTS[parts.scheme]}"), f"{parts.scheme}://{host}"
    return (f"{host}:{port}",), f"{parts.scheme}://{host}:{port}"


def load_config(env: Mapping[str, str]) -> Config:
    base_url = _required(env, "ITOP_BASE_URL").rstrip("/")
    resource_url = _required(env, "MCP_RESOURCE_URL")
    public_hosts, public_origin = _public_host(resource_url)
    return Config(
        itop_base_url=base_url,
        resource_url=resource_url,
        issuer=_optional(env, "ITOP_OAUTH_ISSUER") or f"{base_url}{ISSUER_PATH}",
        api_version=_optional(env, "ITOP_API_VERSION") or DEFAULT_API_VERSION,
        max_rows=_positive_int(env, "MCP_MAX_ROWS", DEFAULT_MAX_ROWS),
        host=_optional(env, "MCP_HOST") or DEFAULT_HOST,
        port=_positive_int(env, "MCP_PORT", DEFAULT_PORT),
        audit_log=_optional(env, "MCP_AUDIT_LOG") or DEFAULT_AUDIT_LOG,
        public_hosts=public_hosts,
        public_origin=public_origin,
    )
