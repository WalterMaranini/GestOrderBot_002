"""
orders_mcp_server.py

MCP server locale per gestione Ordini / info commerciali via REST.

- Legge configurazione dei servizi REST da un file XML.
- Espone due tool MCP:
    1) list_rest_services() -> lista dei servizi e dei parametri
    2) call_rest_service(service_name, arguments) -> chiama il REST corrispondente

Da usare con il Python MCP SDK (FastMCP):
    pip install "mcp[cli]" httpx

Per avviarlo in stdio:
    python orders_mcp_server.py

Per provarlo con l'inspector MCP:
    mcp dev orders_mcp_server.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import httpx
import xml.etree.ElementTree as ET

from mcp.server.fastmcp import FastMCP, Context

# ===================== LOGGING =====================

logger = logging.getLogger("orders_mcp_server")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
)


# ===================== CONFIG DATA CLASSES =====================

@dataclass
class ParamConfig:
    """Descrive un singolo parametro di un servizio REST."""

    name: str
    required: bool
    location: str   # "path" | "query" | "body"
    type: str       # solo descrittivo, non strettamente usato


@dataclass
class ServiceConfig:
    """Descrive un singolo servizio REST (endpoint) configurato via XML."""

    name: str
    method: str
    path: str
    params: List[ParamConfig] = field(default_factory=list)


@dataclass
class RestConfig:
    """Configurazione globale: base URL + dizionario dei servizi."""

    base_url: str
    services: Dict[str, ServiceConfig]


# ===================== PARSING XML =====================

def load_rest_config_from_xml(path: str) -> RestConfig:
    """
    Carica la configurazione REST da un file XML.

    Il formato atteso è quello mostrato nell'esempio del commento iniziale.

    :param path: percorso del file XML.
    :return: RestConfig popolato.
    :raises: ValueError se il file è mancante o malformato.
    """
    if not os.path.isfile(path):
        raise ValueError(f"File XML non trovato: {path}")

    try:
        tree = ET.parse(path)
        root = tree.getroot()
    except Exception as exc:
        raise ValueError(f"Errore nel parsing XML '{path}': {exc}") from exc

    if root.tag != "RestServices":
        raise ValueError("Root XML deve essere <RestServices>")

    base_url = root.attrib.get("baseUrl", "").rstrip("/")
    if not base_url:
        raise ValueError("Attributo baseUrl mancante su <RestServices>")

    services: Dict[str, ServiceConfig] = {}

    for svc_el in root.findall("Service"):
        name = svc_el.attrib.get("name")
        method = (svc_el.attrib.get("method") or "GET").upper()
        path_attr = svc_el.attrib.get("path", "")

        if not name or not path_attr:
            logger.warning("Service senza name/path nel file XML, ignorato: %s", svc_el.attrib)
            continue

        params_cfg: List[ParamConfig] = []
        for param_el in svc_el.findall("Param"):
            p_name = param_el.attrib.get("name")
            if not p_name:
                logger.warning("Param senza name nel service '%s', ignorato", name)
                continue

            required = (param_el.attrib.get("required", "false").lower() == "true")
            location = (param_el.attrib.get("location") or "query").lower()
            if location not in {"path", "query", "body"}:
                logger.warning(
                    "location '%s' non valida per param '%s' in service '%s', "
                    "uso 'query' di default",
                    location,
                    p_name,
                    name,
                )
                location = "query"

            p_type = param_el.attrib.get("type", "string")

            params_cfg.append(
                ParamConfig(
                    name=p_name,
                    required=required,
                    location=location,
                    type=p_type,
                )
            )

        if name in services:
            logger.warning("Service duplicato '%s' nel file XML, sovrascrivo il precedente", name)

        services[name] = ServiceConfig(
            name=name,
            method=method,
            path=path_attr,
            params=params_cfg,
        )

    if not services:
        logger.warning("Nessun service definito nel file XML '%s'", path)

    logger.info("Caricata REST config: base_url=%s, services=%d", base_url, len(services))
    return RestConfig(base_url=base_url, services=services)


# ===================== MCP SERVER (FastMCP) =====================

# Legge il path del file XML da variabile d'ambiente, con default
REST_XML_PATH = os.getenv("ORDERS_REST_XML_PATH", "orders_services.xml")

try:
    REST_CONFIG = load_rest_config_from_xml(REST_XML_PATH)
    logger.info("Servizi MCP disponibili: %s", list(REST_CONFIG.services.keys()))

except Exception as exc:
    # Fallimento in fase di import: loggo e rilancio.
    logger.error("Impossibile caricare la configurazione REST: %s", exc)
    raise


# Istanza MCP
mcp = FastMCP("OrdersMCPServer")


# --------------------- Tool: list_rest_services ---------------------

@mcp.tool()
def list_rest_services() -> list[dict]:
    """
    Restituisce la lista dei servizi REST configurati, con i relativi parametri.

    Questo tool serve al modello per capire:
    - quali servizi esistono
    - quali parametri sono richiesti e dove devono essere messi (path/query/body)
    """

    items: list[dict] = []
    for svc in REST_CONFIG.services.values():
        items.append(
            {
                "name": svc.name,
                "method": svc.method,
                "path": svc.path,
                "params": [
                    {
                        "name": p.name,
                        "required": p.required,
                        "location": p.location,
                        "type": p.type,
                    }
                    for p in svc.params
                ],
            }
        )
    return items


# --------------------- Tool: call_rest_service ---------------------

@mcp.tool()
async def call_rest_service(
    service_name: str,
    arguments: dict,
    ctx: Context,
) -> dict:
    """
    Chiama un servizio REST configurato via XML.

    :param service_name: nome logico del service (attributo 'name' nel file XML).
    :param arguments: dizionario con i parametri (chiave = nome param).
                      Il modello deve passare qui tutti i parametri necessari.
    :param ctx: contesto MCP (usato qui solo per logging / progressi).
    :return: dizionario con:
             {
               "ok": bool,
               "status_code": int | None,
               "service": str,
               "request": { ... },
               "response_json": dict | None,
               "response_text": str | None,
               "error": str | None
             }
    """

    logger.info("call_rest_service: service_name=%s, arguments=%s", service_name, arguments)

    svc = REST_CONFIG.services.get(service_name)
    if not svc:
        err = f"Servizio '{service_name}' non definito nella configurazione."
        logger.error(err)
        return {
            "ok": False,
            "status_code": None,
            "service": service_name,
            "request": {},
            "response_json": None,
            "response_text": None,
            "error": err,
        }

    # Validazione parametri richiesti
    missing_required: list[str] = []
    for p in svc.params:
        if p.required and p.name not in arguments:
            missing_required.append(p.name)

    if missing_required:
        err = f"Parametri obbligatori mancanti per service '{service_name}': {', '.join(missing_required)}"
        logger.warning(err)
        return {
            "ok": False,
            "status_code": None,
            "service": service_name,
            "request": {},
            "response_json": None,
            "response_text": None,
            "error": err,
        }

    # Prepara URL, query e body
    url = REST_CONFIG.base_url + svc.path
    query_params: dict[str, Any] = {}
    body_payload: dict[str, Any] = {}

    # 1) Parametri path: rimpiazza {name} nel path
    for p in svc.params:
        if p.location == "path" and p.name in arguments:
            placeholder = "{" + p.name + "}"
            value = str(arguments[p.name])
            url = url.replace(placeholder, value)

    # 2) Parametri query
    for p in svc.params:
        if p.location == "query" and p.name in arguments:
            query_params[p.name] = arguments[p.name]

    # 3) Parametri body
    for p in svc.params:
        if p.location == "body" and p.name in arguments:
            body_payload[p.name] = arguments[p.name]

    method = svc.method.upper()
    timeout = httpx.Timeout(10.0, connect=5.0)

    request_info = {
        "method": method,
        "url": url,
        "query": query_params,
        "body": body_payload if body_payload else None,
    }

    # Logging debug
    logger.info("Effettuo richiesta REST: %s", request_info)
    await ctx.report_progress(0, 1)

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            if method == "GET":
                resp = await client.get(url, params=query_params)
            elif method == "POST":
                resp = await client.post(url, params=query_params, json=body_payload or None)
            elif method == "PUT":
                resp = await client.put(url, params=query_params, json=body_payload or None)
            elif method == "DELETE":
                resp = await client.delete(url, params=query_params, json=body_payload or None)
            else:
                err = f"Metodo HTTP '{method}' non supportato dal server MCP."
                logger.error(err)
                return {
                    "ok": False,
                    "status_code": None,
                    "service": service_name,
                    "request": request_info,
                    "response_json": None,
                    "response_text": None,
                    "error": err,
                }

        await ctx.report_progress(1, 1)

        # Provo a interpretare come JSON, se possibile
        response_json: Optional[dict] = None
        response_text: Optional[str] = None
        try:
            response_json = resp.json()
        except Exception:
            response_text = resp.text

        ok = resp.status_code >= 200 and resp.status_code < 300

        if not ok:
            logger.warning(
                "REST call non OK: service=%s status=%s body=%s",
                service_name,
                resp.status_code,
                response_text or response_json,
            )

        return {
            "ok": ok,
            "status_code": resp.status_code,
            "service": service_name,
            "request": request_info,
            "response_json": response_json,
            "response_text": response_text,
            "error": None if ok else f"HTTP {resp.status_code}",
        }

    except httpx.RequestError as exc:
        err = f"Errore di rete verso il servizio '{service_name}': {exc}"
        logger.error(err)
        return {
            "ok": False,
            "status_code": None,
            "service": service_name,
            "request": request_info,
            "response_json": None,
            "response_text": None,
            "error": err,
        }
    except Exception as exc:
        err = f"Errore imprevisto nella chiamata a '{service_name}': {exc}"
        logger.exception(err)
        return {
            "ok": False,
            "status_code": None,
            "service": service_name,
            "request": request_info,
            "response_json": None,
            "response_text": None,
            "error": err,
        }


# ===================== ENTRYPOINT STDIO =====================

if __name__ == "__main__":
    logger.info("Avvio OrdersMCPServer in modalità stdio (FastMCP.run)")
    # mcp.run() avvia il loop MCP su stdin/stdout e blocca il processo
    # (vedi docs ufficiali FastMCP).
    mcp.run()
