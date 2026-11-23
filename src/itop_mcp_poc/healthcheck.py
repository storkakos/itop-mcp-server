"""Container-Healthcheck: fragt die Protected-Resource-Metadaten ueber Loopback ab.

Exit 0, wenn der Server mit 200 antwortet, sonst 1. Der Metadaten-Pfad folgt RFC 9728 aus dem
Pfad von MCP_RESOURCE_URL (/mcp -> /.well-known/oauth-protected-resource/mcp); der Port ist
MCP_PORT. Der Endpunkt antwortet ohne Token, iTop wird dafuer nicht gefragt.
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


def main() -> int:
    try:
        url = metadata_url(os.environ)
        with urllib.request.urlopen(url, timeout=5) as r:
            return 0 if r.status == 200 else 1
    except (ConfigError, OSError) as e:
        print(f"unhealthy: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
