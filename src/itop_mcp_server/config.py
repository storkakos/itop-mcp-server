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

The public hosts are in normal form (normalise_host): lower case, without a trailing dot, IPv6
literals compressed. The server brings incoming Host and Origin headers into the same form before
comparing them, so equivalent spellings of the public host are accepted.
An IPv4 address must be written as a dotted quad (four decimal numbers 0-255, no leading zeros). Other
spellings that the URL standard and many resolvers also read as IPv4 (127.1, 0x7f.0.0.1, 0177.0.0.1,
2130706433; see alternative_ipv4) are refused, not normalised: in MCP_RESOURCE_URL they stop startup,
in an incoming Host or Origin header they get 421 or 403 with a message that says why.
"""
from __future__ import annotations

import ipaddress
import re
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


def normalise_host(hostname: str) -> str:
    """One spelling per host name: lower case, without the trailing dot of a fully qualified name, an
    IPv6 literal (without brackets) in compressed form. Anything that is not a valid IPv6 literal is
    only lower-cased and stripped of one trailing dot, so it can never turn into an allowed host."""
    hostname = hostname.lower()
    if ":" in hostname:
        try:
            return ipaddress.IPv6Address(hostname).compressed
        except ValueError:
            return hostname
    return hostname[:-1] if hostname.endswith(".") else hostname


# The last label of a host the URL standard (WHATWG, "ends in a number") parses as an IPv4 address:
# decimal digits, or a hexadecimal number with 0x prefix.
_NUMBER_LABEL = re.compile(r"^(?:[0-9]+|0x[0-9a-f]*)$")


def alternative_ipv4(hostname: str) -> bool:
    """True for a host (without brackets or port) that is meant as an IPv4 address but is not a dotted
    quad: short forms (127.1), hexadecimal or octal parts (0x7f.0.0.1, 0177.0.0.1), a single integer
    (2130706433), parts out of range (256.0.0.1) or too many parts (1.2.3.4.5). The rule is the URL
    standard's: a host whose last label is a number is an IPv4 address. Such a host is refused, never
    normalised (see the module docstring); a dotted quad, a name and an IPv6 literal are not affected."""
    host = hostname.lower()
    host = host[:-1] if host.endswith(".") else host
    if not host or ":" in host or not _NUMBER_LABEL.match(host.rsplit(".", 1)[-1]):
        return False
    try:
        ipaddress.IPv4Address(host)  # strict: four decimal parts 0-255, no leading zeros
    except ValueError:
        return True
    return False


def _public_host(resource_url: str) -> tuple[tuple[str, ...], str]:
    """Host-Header-Werte und Origin aus MCP_RESOURCE_URL.

    Ohne Port oder mit dem Standardport des Schemas (443/80) in der URL: "host" und
    "host:<Standardport>" (Proxys senden beides), Origin ohne Port (so senden ihn Browser).
    Mit anderem Port: nur "host:port".
    The host is in normal form (normalise_host); urlsplit already returns the scheme in lower case.
    """
    parts = urlsplit(resource_url)
    try:
        hostname, port = parts.hostname, parts.port
    except ValueError:
        hostname, port = None, None
    if parts.scheme not in DEFAULT_PORTS or not hostname:
        raise ConfigError(f"MCP_RESOURCE_URL muss eine http(s)-URL mit Host sein, ist aber {resource_url!r}")
    if alternative_ipv4(hostname):
        raise ConfigError(f"MCP_RESOURCE_URL must write an IPv4 address as a dotted quad (four decimal numbers "
                          f"0-255 without leading zeros, e.g. 192.0.2.10), but its host is {hostname!r}")
    hostname = normalise_host(hostname)
    host = f"[{hostname}]" if ":" in hostname else hostname
    if port is None or port == DEFAULT_PORTS[parts.scheme]:
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
