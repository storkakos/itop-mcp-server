"""
iTop MCP-Server - eigenstaendiger Dienst, Fork von cdmx-in/itop-mcp (MIT).

Unterschied zum Upstream:
- Kein gemeinsamer Login (ITOP_USER / ITOP_PASSWORD entfernt). Jeder Aufruf bringt das
  persoenliche iTop-Token des Benutzers mit (Authorization: Bearer ...), ausgestellt von
  altioo-oauth-server in iTop. Der Server reicht es als Auth-Token-Header an rest.php weiter.
  iTop prueft damit die Rechte genau dieses Benutzers.
- Streamable HTTP, stateless: kein Zustand und kein Cache zwischen Anfragen oder Benutzern.
- 401 mit WWW-Authenticate + RFC-9728-Metadaten, die auf iTop (altioo) als Authorization-Server zeigen.
- Nur lesende Tools. Audit-Log je Aufruf (Benutzer, Tool, Argumente), Tokens nie im Log.
"""
from __future__ import annotations

import functools
import hashlib
import inspect
import json
import logging
import os
import re
import time
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.transport_security import TransportSecuritySettings

from . import __version__
from . import upstream_main as upstream

from .config import ConfigError, load_config

# Konfiguration beim Import lesen: fehlt ein Pflichtwert, bricht der Start hier ab
# (Meldung nennt die Variable, kein Traceback, kein Rueckfall auf localhost).
try:
    CONFIG = load_config(os.environ)
except ConfigError as e:
    raise SystemExit(f"Konfigurationsfehler: {e}") from None

ITOP_BASE_URL = CONFIG.itop_base_url
ITOP_API_VERSION = CONFIG.api_version
ITOP_ISSUER = CONFIG.issuer
MCP_HOST = CONFIG.host
MCP_PORT = CONFIG.port
MCP_RESOURCE_URL = CONFIG.resource_url
AUDIT_LOG = Path(CONFIG.audit_log)
MAX_ROWS = CONFIG.max_rows

log = logging.getLogger("itop-mcp-server")


def _token_id(token: str) -> str:
    """Kurzer, nicht umkehrbarer Bezeichner fuer Logs (nie das Token selbst loggen)."""
    return hashlib.sha256(token.encode()).hexdigest()[:12]


def _redact(text: str) -> str:
    return re.sub(r"[A-Za-z0-9_\-]{32,}", "***", text)


@dataclass
class _ToolCall:
    """Was ein laufender Tool-Aufruf fuer seine Audit-Zeile sammelt (siehe _audited)."""

    args: dict[str, Any]
    # (ok, Info) je iTop-Anfrage des Tools, dazu eine Ausnahme, mit der das Tool endet.
    # Die Upstream-Tools fangen Fehler selbst ab und liefern nur Text, daher kommt ok von hier.
    itop: list[tuple[bool, str]] = field(default_factory=list)
    user: str | None = None      # vom Tool selbst ermittelt (whoami), sonst schlaegt _audited nach
    refused: str | None = None   # Meldung, wenn das Tool die Eingabe vor iTop abgelehnt hat


_current_call: ContextVar[_ToolCall | None] = ContextVar("current_tool_call", default=None)


def _record_itop_call(ok: bool, info: str) -> None:
    call = _current_call.get()
    if call is not None:
        call.itop.append((ok, info))


class ITopTokenClient(upstream.ITopClient):
    """iTop-REST-Client mit dem persoenlichen Token des Aufrufers (pro Anfrage neu erzeugt)."""

    def __init__(self, base_url: str, token: str, version: str = ITOP_API_VERSION):
        super().__init__(base_url, "", "", version)
        self._token = token

    async def make_request(self, operation_data: dict) -> dict:
        headers = {
            "User-Agent": f"iTop-MCP-Server/{__version__}",
            "Content-Type": "application/x-www-form-urlencoded",
            "Auth-Token": self._token,  # Header statt URL-Parameter: landet nicht im Access-Log
        }
        if operation_data.get("operation") == "core/get":
            # Zeilenlimit fuer jede Leseabfrage, auch fuer die Upstream-Tools (smart_query_v2 will bis 100).
            # Ohne "limit" liefert iTop alle Treffer, daher fehlendes Limit ebenfalls auf MAX_ROWS setzen.
            limit = operation_data.get("limit")
            limit = limit if isinstance(limit, int) and limit > 0 else MAX_ROWS
            operation_data = {**operation_data, "limit": min(limit, MAX_ROWS)}
        try:
            result = await self._post(operation_data, headers)
        except Exception as e:
            _record_itop_call(False, str(e))
            raise
        _record_itop_call(result.get("code") == 0, str(result.get("message", "")))
        return result

    async def _post(self, operation_data: dict, headers: dict[str, str]) -> dict:
        data = {"version": self.version, "json_data": json.dumps(operation_data)}
        async with httpx.AsyncClient(timeout=60.0) as client:
            try:
                response = await client.post(self.rest_url, data=data, headers=headers)
                response.raise_for_status()
                return response.json()
            except httpx.RequestError as e:
                raise ConnectionError(f"iTop nicht erreichbar: {type(e).__name__}") from None
            except httpx.HTTPStatusError as e:
                raise ValueError(f"iTop HTTP {e.response.status_code}") from None
            except json.JSONDecodeError:
                raise ValueError("iTop lieferte kein JSON (Token abgelaufen oder Login-Seite?)") from None


def _client_for_current_request() -> ITopTokenClient:
    access = get_access_token()
    if access is None:
        raise PermissionError("Kein Token in dieser Anfrage")
    return ITopTokenClient(ITOP_BASE_URL, access.token)


# Upstream-Tools (smart_query_v2, list_operations) nutzen ab jetzt den Token-Client des Aufrufers.
upstream.get_itop_client = _client_for_current_request


class ITopTokenVerifier(TokenVerifier):
    """Prueft das Bearer-Token direkt bei iTop. Kein Cache: jede Anfrage wird neu geprueft."""

    async def verify_token(self, token: str) -> AccessToken | None:
        if not token or len(token) > 512:
            return None
        client = ITopTokenClient(ITOP_BASE_URL, token)
        try:
            res = await client.make_request({"operation": "list_operations"})
        except Exception as e:  # noqa: BLE001
            log.warning("Token-Pruefung fehlgeschlagen (%s): %s", _token_id(token), _redact(str(e)))
            return None
        if res.get("code") != 0:
            log.info("Token abgelehnt (%s): code=%s", _token_id(token), res.get("code"))
            return None
        # resource bleibt leer: iTop sagt bei list_operations nicht, fuer welche Resource das Token
        # ausgestellt wurde. Die Resource-Pruefung des SDK ist deshalb aus (siehe AuthSettings unten).
        return AccessToken(token=token, client_id="itop-personal-token", scopes=["REST/JSON"])


mcp = upstream.mcp
mcp.settings.host = MCP_HOST
mcp.settings.port = MCP_PORT
mcp.settings.stateless_http = True
mcp.settings.json_response = True
mcp.settings.auth = AuthSettings(
    issuer_url=ITOP_ISSUER,
    resource_server_url=MCP_RESOURCE_URL,
    required_scopes=["REST/JSON"],
    # Explizit aus, damit ein SDK-Update (ab 3.0 Default True) nicht still aendert, wer reinkommt.
    # Das Token wird vom ITopTokenVerifier direkt bei iTop geprueft. Ob altioo Tokens an die
    # angefragte Resource (RFC 8707) bindet und wir das auslesen koennen, ist offen (Ticket
    # docker-build 15); erst dann kann die Pruefung an.
    validate_token_resource=False,
)
mcp._token_verifier = ITopTokenVerifier()

# DNS-Rebinding-Schutz: upstream erzeugt FastMCP mit Host 127.0.0.1, dadurch sind nur Loopback-Hosts
# erlaubt, und das spaetere Setzen von settings.host aendert daran nichts. Hinter dem Reverse Proxy
# kommt aber der oeffentliche Name aus MCP_RESOURCE_URL im Host-Header an. Den zusaetzlich erlauben;
# alle anderen Hosts bleiben gesperrt (421). Loopback bleibt fuer den Container-Healthcheck.
mcp.settings.transport_security = TransportSecuritySettings(
    enable_dns_rebinding_protection=True,
    allowed_hosts=["127.0.0.1:*", "localhost:*", "[::1]:*", *CONFIG.public_hosts],
    allowed_origins=["http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*", CONFIG.public_origin],
)


def _audit(tool: str, args: dict[str, Any], user: str, ok: bool, info: str = "") -> None:
    AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "user": user,
        "token": _token_id(get_access_token().token) if get_access_token() else None,
        "tool": tool,
        "args": json.loads(_redact(json.dumps(args, ensure_ascii=False))),
        "ok": ok,
        "info": _redact(info)[:300],
    }
    with AUDIT_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _refuse(message: str) -> str:
    """Abgelehnte Eingabe: fuer die Audit-Zeile vormerken (Benutzer bleibt "?", iTop wird nicht gefragt)."""
    call = _current_call.get()
    if call is not None:
        call.refused = message
    return message


async def _get(oql: str, fields: str = "*", limit: int = MAX_ROWS) -> dict:
    client = _client_for_current_request()
    return await client.make_request(
        {"operation": "core/get", "class": oql.split()[1] if oql.upper().startswith("SELECT ") else "",
         "key": oql, "output_fields": fields, "limit": max(1, min(limit, MAX_ROWS))}
    )


async def _current_user() -> str:
    try:
        res = await _get("SELECT Person WHERE id = :current_contact_id", "friendlyname,email", 1)
        for obj in (res.get("objects") or {}).values():
            return obj["fields"].get("friendlyname") or "?"
    except Exception:  # noqa: BLE001
        pass
    return "?"


async def _user_for_audit() -> str:
    """Benutzer fuer die Audit-Zeile nachschlagen; diese Anfrage zaehlt nicht zum Ergebnis des Tools."""
    reset = _current_call.set(None)
    try:
        return await _current_user()
    finally:
        _current_call.reset(reset)


def _format(res: dict) -> str:
    if res.get("code") != 0:
        return f"iTop-Fehler {res.get('code')}: {res.get('message')}"
    objs = res.get("objects") or {}
    if not objs:
        return "Keine Treffer (oder keine Berechtigung)."
    rows = [{"key": k, "class": o.get("class"), **o.get("fields", {})} for k, o in objs.items()]
    return json.dumps({"count": len(rows), "items": rows}, ensure_ascii=False, indent=1)


# Nur lesende Tools. Schreibende Tools sind bewusst nicht vorhanden.
_READONLY_OQL = re.compile(r"^\s*SELECT\s+[A-Za-z_][A-Za-z0-9_]*(\s|$)", re.I)


@mcp.tool()
async def whoami() -> str:
    """Zeigt, als welche iTop-Person dieser Assistent gerade arbeitet (Rechte = Rechte dieser Person)."""
    user = await _current_user()
    call = _current_call.get()
    if call is not None:
        call.user = user  # die Nachfrage ist hier das Tool selbst; ok kommt aus ihrem Ergebnis
    return f"Angemeldet in iTop als: {user}"


@mcp.tool()
async def search_tickets(text: str = "", status: str = "", ticket_class: str = "UserRequest", limit: int = 20) -> str:
    """Sucht Tickets in iTop. ticket_class: UserRequest, Incident, Change, Problem oder Ticket.
    text sucht in Titel und Referenz. status z.B. new, assigned, pending, resolved, closed."""
    if ticket_class not in {"UserRequest", "Incident", "Change", "Problem", "Ticket"}:
        return _refuse("Ungueltige Ticketklasse")
    cond = []
    if text:
        t = text.replace("\\", "").replace("'", "\\'")
        cond.append(f"(title LIKE '%{t}%' OR ref LIKE '%{t}%')")
    if status:
        if not re.fullmatch(r"[a-z_]{2,30}", status):
            return _refuse("Ungueltiger Status")
        cond.append(f"status = '{status}'")
    oql = f"SELECT {ticket_class}" + (" WHERE " + " AND ".join(cond) if cond else "")
    fields = "ref,title,status,priority,caller_id_friendlyname,agent_id_friendlyname,org_id_friendlyname,start_date"
    if ticket_class == "Ticket":
        fields = "ref,title,operational_status,caller_id_friendlyname,agent_id_friendlyname,org_id_friendlyname,start_date"
    return _format(await _get(oql, fields, limit))


@mcp.tool()
async def get_ticket(ref: str) -> str:
    """Liest ein Ticket mit Beschreibung und Verlauf (Referenz z.B. R-000123 oder I-000045)."""
    if not re.fullmatch(r"[A-Z]{1,3}-\d{1,9}", ref.strip()):
        return _refuse("Ungueltige Ticketreferenz")
    res = await _get(f"SELECT Ticket WHERE ref = '{ref.strip()}'",
                     "ref,title,description,operational_status,caller_id_friendlyname,agent_id_friendlyname,"
                     "team_id_friendlyname,org_id_friendlyname,start_date,last_update,public_log", 1)
    return _format(res)


@mcp.tool()
async def oql_query(oql: str, fields: str = "friendlyname", limit: int = 20) -> str:
    """Fuehrt eine lesende OQL-Abfrage aus (nur SELECT). Beispiel: SELECT Server WHERE status='production'.
    fields: kommagetrennte Attribute oder *. Der Server kappt bei MCP_MAX_ROWS Zeilen (Standard 50)."""
    if not _READONLY_OQL.match(oql) or ";" in oql:
        return _refuse("Nur einzelne SELECT-Abfragen sind erlaubt.")
    if not re.fullmatch(r"[A-Za-z0-9_,*\s]{1,400}", fields):
        return _refuse("Ungueltige Feldliste")
    return _format(await _get(oql.strip(), fields.replace(" ", ""), limit))


# Audit: genau eine Zeile je Tool-Aufruf, fuer eigene und Upstream-Tools. Jedes registrierte Tool wird
# nach dem Registrieren umhuellt (Upstream-Modul bleibt unveraendert); Name, Parameter-Schema und
# Ergebnis bleiben gleich. Ein neu hinzugefuegtes Tool ist damit automatisch auditiert.
#
# Regel fuer ok und info (README, Abschnitt "Audit log"):
# - Eingabe abgelehnt: ok=false, info "abgelehnt: ...", Benutzer "?" (iTop wird nicht gefragt).
# - Kein iTop-Aufruf: ok=false, info "kein iTop-Aufruf: <erste Zeile der Antwort>".
# - Sonst ok=true genau dann, wenn jede iTop-Anfrage des Tools ohne Fehler beantwortet wurde.
#   Faengt ein Tool einen Fehler ab und antwortet trotzdem, bleibt ok=false: von aussen ist nicht zu
#   unterscheiden, ob es sich erholt hat oder den Fehler nur in seinen Text schreibt (z. B. die
#   Vergleichsabfragen von smart_query_v2). info nennt den ersten Fehler (iTops Meldung,
#   "iTop HTTP 500", "iTop nicht erreichbar: ..."). Fuer whoami ist die Personen-Nachfrage das Tool
#   selbst: schlaegt sie fehl, ist ok=false.
# - Abgebrochen (z. B. Server faehrt herunter): ok=false, info "abgebrochen", Benutzer
#   "?" (ausser whoami kannte ihn schon). Die Zeile wird ohne weiteres await geschrieben, denn in einem
#   abgebrochenen Cancel-Scope bricht jedes await erneut ab.

# Audit-Argumente, wo sie von den Tool-Parametern abweichen (Standardwerte sind eingesetzt).
AUDIT_ARGS = {
    "whoami": lambda a: {},
    "search_tickets": lambda a: {"text": a["text"], "status": a["status"], "class": a["ticket_class"]},
    "get_ticket": lambda a: {"ref": a["ref"]},
    "oql_query": lambda a: {"oql": a["oql"], "fields": a["fields"]},
}


def _first_line(result: Any) -> str:
    lines = str(result or "").strip().splitlines()
    return lines[0] if lines else ""


def _outcome(call: _ToolCall, result: Any) -> tuple[bool, str]:
    """ok und info fuer einen zu Ende gelaufenen Aufruf (Regel oben)."""
    if call.refused is not None:
        return False, f"abgelehnt: {call.refused}"
    if not call.itop:
        return False, f"kein iTop-Aufruf: {_first_line(result)}"
    failed = [info for ok, info in call.itop if not ok]
    return (False, failed[0]) if failed else (True, "")


def _audited(name: str, fn):
    to_audit_args = AUDIT_ARGS.get(name)
    signature = inspect.signature(fn)

    @functools.wraps(fn)
    async def wrapper(**kwargs: Any) -> Any:
        if to_audit_args is None:
            args = dict(kwargs)
        else:
            bound = signature.bind_partial(**kwargs)
            bound.apply_defaults()
            args = to_audit_args(bound.arguments)
        call = _ToolCall(args)
        result: Any = None
        error: Exception | None = None
        try:
            reset = _current_call.set(call)
            try:
                result = await fn(**kwargs)
            except Exception as e:  # noqa: BLE001 - nach der Audit-Zeile unveraendert weitergeworfen
                error = e
                call.itop.append((False, str(e)))
            finally:
                _current_call.reset(reset)
            user = call.user or ("?" if call.refused is not None else await _user_for_audit())
        except BaseException:
            # Abgebrochen (CancelledError u. a.): sofort schreiben, kein await mehr.
            failed = [info for ok, info in call.itop if not ok]
            _audit(name, args, call.user or "?", False, "abgebrochen" + (f"; {failed[0]}" if failed else ""))
            raise
        _audit(name, args, user, *_outcome(call, result))
        if error is not None:
            raise error
        return result

    return wrapper


for _tool in mcp._tool_manager.list_tools():
    _tool.fn = _audited(_tool.name, _tool.fn)


def _check_audit_log_writable() -> None:
    """Audit-Log beim Start anlegen bzw. oeffnen; nicht beschreibbar -> Abbruch mit Meldung.

    Sonst faellt ein falsch berechtigter Log-Ordner (z. B. ./logs gehoert root, der Container
    laeuft ohne root) erst beim ersten Tool-Aufruf auf.
    """
    try:
        AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
        with AUDIT_LOG.open("a", encoding="utf-8"):
            pass
    except OSError as e:
        raise SystemExit(f"Konfigurationsfehler: Audit-Log {CONFIG.audit_log} ist nicht beschreibbar "
                         f"(MCP_AUDIT_LOG, Ordner und Rechte pruefen): {e.strerror or e}") from None


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    log.info("iTop MCP-Server auf %s, lauscht auf %s:%s (iTop %s, Issuer %s, Audit-Log %s)",
             MCP_RESOURCE_URL, MCP_HOST, MCP_PORT, ITOP_BASE_URL, ITOP_ISSUER, CONFIG.audit_log)
    _check_audit_log_writable()
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
