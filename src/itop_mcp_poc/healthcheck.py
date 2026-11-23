"""Container-Healthcheck: fragt die Protected-Resource-Metadaten ueber Loopback ab.

Exit 0, wenn der Server mit 200 antwortet, sonst 1. Der Metadaten-Pfad folgt RFC 9728 aus dem
Pfad von MCP_RESOURCE_URL (/mcp -> /.well-known/oauth-protected-resource/mcp); der Port ist
MCP_PORT. Der Endpunkt antwortet ohne Token, iTop wird dafuer nicht gefragt.

Die Anfrage geht immer direkt an 127.0.0.1, nie ueber einen Proxy aus HTTP(S)_PROXY, egal was
NO_PROXY sagt. Deshalb muss MCP_HOST im Container 0.0.0.0 bleiben (siehe .env.example).
"""
from __future__ import annotations

import os
import sys
import urllib.request
from urllib.parse import urlsplit

from .config import ConfigError, load_config


def metadata_url(env) -> str:
    config = load_config(env)
    path = urlsplit(config.resource_url).path
    if path == "/":
        path = ""
    return f"http://127.0.0.1:{config.port}/.well-known/oauth-protected-resource{path}"


# Leere Proxy-Tabelle: keine Proxys aus der Umgebung, fuer jede URL.
_direct = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def main() -> int:
    try:
        url = metadata_url(os.environ)
        with _direct.open(url, timeout=5) as r:
            return 0 if r.status == 200 else 1
    except (ConfigError, OSError) as e:
        print(f"unhealthy: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
