"""Audit Price tool — integration with the Audit Price service for procurement price analysis.

Service: "Аудит цен" — поиск и анализ цен на объекты закупки.
Covers: authentication, search requests, commercial proposals, supplier analysis,
price search, email generation, and nomenclature lookup.
"""
from __future__ import annotations

import json
from typing import Any, Dict, Optional

from ouroboros.tools.registry import ToolContext, ToolEntry


# ── HTTP helper ───────────────────────────────────────────────────────────────

def _make_request(
    method: str,
    url: str,
    token: str = "",
    json_data: Any = None,
    form_data: Any = None,
    query_params: Any = None,
) -> tuple[int, Any]:
    """Make an HTTP request. Returns (status_code, parsed_body_or_text)."""
    try:
        import requests as req_lib
    except ImportError:
        return 500, "requests library not available"

    headers: Dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        resp = req_lib.request(
            method, url, headers=headers,
            json=json_data, data=form_data, params=query_params, timeout=30,
        )
        status = resp.status_code
        try:
            body = resp.json()
        except Exception:
            body = resp.text[:3000]
        return status, body
    except Exception as e:
        return 0, str(e)


def _fmt(status: int, body: Any) -> str:
    """Format response as readable string."""
    if status == 0:
        return f"⚠️ Connection error: {body}"
    icon = "✅" if status < 400 else "❌"
    try:
        body_str = json.dumps(body, ensure_ascii=False, indent=2)
    except Exception:
        body_str = str(body)[:3000]
    return f"{icon} HTTP {status}\n{body_str}"


def _base(base_url: str) -> str:
    return base_url.rstrip("/")


# ── Action groups ─────────────────────────────────────────────────────────────

def _handle_auth(action: str, base: str, token: str, p: Dict[str, Any]) -> Optional[str]:
    """Auth actions: login, refresh_token, register."""
    if action == "login":
        username = p.get("username") or p.get("email", "")
        password = p.get("password", "")
        status, body = _make_request(
            "POST", f"{base}/api/v1/auth/jwt/login",
            form_data={"username": username, "password": password},
        )
        result = _fmt(status, body)
        if status == 200 and isinstance(body, dict):
            access = body.get("access_token", "")
            refresh = body.get("refresh_token", "")
            if access:
                result += f"\n\n💡 access_token: {access[:40]}..."
            if refresh:
                result += f"\n💡 refresh_token: {refresh[:40]}..."
        return result

    if action == "refresh_token":
        status, body = _make_request(
            "POST", f"{base}/api/v1/auth/jwt/refresh_token",
            json_data={"refresh_token": p.get("refresh_token", "")},
        )
        return _fmt(status, body)

    if action == "register":
        status, body = _make_request("POST", f"{base}/api/v1/auth/register", token=token, json_data=p)
        return _fmt(status, body)

    return None


def _handle_requests(action: str, base: str, token: str, p: Dict[str, Any]) -> Optional[str]:
    """Search request CRUD actions."""
    if action == "get_requests":
        query = {k: p[k] for k in ("search", "limit", "offset") if k in p}
        status, body = _make_request("GET", f"{base}/api/v1/search-requests", token=token, query_params=query or None)
        return _fmt(status, body)

    if action == "create_request":
        status, body = _make_request("POST", f"{base}/api/v1/search-requests", token=token, json_data=p)
        return _fmt(status, body)

    if action == "update_request":
        status, body = _make_request("PUT", f"{base}/api/v1/search-requests", token=token, json_data=p)
        return _fmt(status, body)

    if action == "patch_request":
        status, body = _make_request("PATCH", f"{base}/api/v1/search-requests", token=token, json_data=p)
        return _fmt(status, body)

    if action == "get_request":
        status, body = _make_request("GET", f"{base}/api/v1/search-requests/{p.get('request_id','')}", token=token)
        return _fmt(status, body)

    if action == "delete_request":
        status, body = _make_request("DELETE", f"{base}/api/v1/search-requests/{p.get('request_id','')}", token=token)
        return _fmt(status, body)

    if action == "get_request_items":
        rid = p.get("request_id", "")
        query = {"request_id": rid, **{k: p[k] for k in ("limit", "offset") if k in p}}
        status, body = _make_request("GET", f"{base}/api/v1/search-requests/{rid}/items", token=token, query_params=query)
        return _fmt(status, body)

    if action == "create_request_items":
        rid = p.get("request_id", "")
        status, body = _make_request("POST", f"{base}/api/v1/search-requests/{rid}/items", token=token, json_data=p.get("items", p))
        return _fmt(status, body)

    return None


def _handle_proposals(action: str, base: str, token: str, p: Dict[str, Any]) -> Optional[str]:
    """Commercial proposals, analysis results, user files."""
    if action == "upload_proposals":
        status, body = _make_request("POST", f"{base}/api/v1/upload-commercial-proposals", token=token, json_data=p)
        return _fmt(status, body)

    if action == "delete_proposals":
        status, body = _make_request("DELETE", f"{base}/api/v1/delete-commerical-proposals", token=token, json_data=p)
        return _fmt(status, body)

    if action == "get_proposal_files":
        status, body = _make_request("GET", f"{base}/api/v1/commercial-proposals/files", token=token, query_params={"request_id": p.get("request_id", "")})
        return _fmt(status, body)

    if action == "get_analysis_results":
        rid = p.get("request_id", "")
        keys = ("limit", "offset", "suppliers", "scores", "units", "min_price", "max_price")
        query: Dict[str, Any] = {"request_id": rid, **{k: p[k] for k in keys if k in p}}
        status, body = _make_request("GET", f"{base}/api/v1/analysis-results", token=token, query_params=query)
        return _fmt(status, body)

    if action == "get_analysis_excel":
        rid = p.get("request_id", "")
        filters = {k: v for k, v in p.items() if k != "request_id"}
        status, body = _make_request("POST", f"{base}/api/v1/analysis-results/excel", token=token, query_params={"request_id": rid}, json_data=filters or {})
        return _fmt(status, body)

    if action == "upload_user_files":
        status, body = _make_request("POST", f"{base}/api/v1/upload-user-files", token=token, json_data=p)
        return _fmt(status, body)

    return None


def _handle_supplier(action: str, base: str, token: str, p: Dict[str, Any]) -> Optional[str]:
    """Supplier relevance analysis."""
    if action == "run_supplier_analysis":
        status, body = _make_request("POST", f"{base}/api/v1/supplier-results/run", token=token, json_data=p)
        return _fmt(status, body)

    if action == "get_supplier_results":
        status, body = _make_request("POST", f"{base}/api/v1/supplier-results/results", token=token, json_data=p)
        return _fmt(status, body)

    if action == "get_supplier_excel":
        rid = p.get("request_id", "")
        filters = {k: v for k, v in p.items() if k != "request_id"}
        status, body = _make_request("POST", f"{base}/api/v1/supplier-results/excel", token=token, query_params={"request_id": rid}, json_data=filters or {})
        return _fmt(status, body)

    return None


def _handle_email(action: str, base: str, token: str, p: Dict[str, Any]) -> Optional[str]:
    """Email body and mailto link generation."""
    if action == "get_email_body":
        status, body = _make_request("GET", f"{base}/api/v1/email-body", token=token, query_params={"request_id": p.get("request_id", "")})
        return _fmt(status, body)

    if action == "create_mailto_link":
        status, body = _make_request("POST", f"{base}/api/v1/mailto-link", token=token, json_data=p)
        return _fmt(status, body)

    return None


def _handle_prices(action: str, base: str, token: str, p: Dict[str, Any]) -> Optional[str]:
    """Price search actions."""
    if action == "search_prices":
        status, body = _make_request("POST", f"{base}/api/v1/prices/run", token=token, json_data=p)
        return _fmt(status, body)

    if action == "get_price_results":
        status, body = _make_request("GET", f"{base}/api/v1/prices/results", token=token, query_params={"request_id": p.get("request_id", "")})
        return _fmt(status, body)

    if action == "get_prices_excel":
        rid = p.get("request_id", "")
        filters = {k: v for k, v in p.items() if k != "request_id"}
        status, body = _make_request("POST", f"{base}/api/v1/prices/excel", token=token, query_params={"request_id": rid}, json_data=filters or {})
        return _fmt(status, body)

    return None


def _handle_nsi(action: str, base: str, token: str, p: Dict[str, Any]) -> Optional[str]:
    """NSI nomenclature: КПГЗ, СПГЗ, СКТРУ."""
    if action == "get_kpgz":
        query = {k: p[k] for k in ("search", "limit", "offset") if k in p}
        status, body = _make_request("GET", f"{base}/api/v1/nsi/kpgz", token=token, query_params=query or None)
        return _fmt(status, body)

    if action == "get_spgz":
        query = {k: p[k] for k in ("search", "limit", "offset", "kpgz_id") if k in p}
        status, body = _make_request("GET", f"{base}/api/v1/nsi/spgz", token=token, query_params=query or None)
        return _fmt(status, body)

    if action == "get_sktru":
        query = {k: p[k] for k in ("search", "limit", "offset", "spgz_id") if k in p}
        status, body = _make_request("GET", f"{base}/api/v1/nsi/sktru", token=token, query_params=query or None)
        return _fmt(status, body)

    return None


# ── Main dispatcher ───────────────────────────────────────────────────────────

_UNKNOWN_ACTION_HELP = """\
❓ Unknown action: '{action}'

Available actions:
  Auth:        login, refresh_token, register
  Requests:    get_requests, create_request, update_request, patch_request,
               get_request, delete_request, get_request_items, create_request_items
  Proposals:   upload_proposals, delete_proposals, get_proposal_files,
               get_analysis_results, get_analysis_excel, upload_user_files
  Supplier:    run_supplier_analysis, get_supplier_results, get_supplier_excel
  Email:       get_email_body, create_mailto_link
  Prices:      search_prices, get_price_results, get_prices_excel
  NSI:         get_kpgz, get_spgz, get_sktru
  Raw:         raw (method, path, json/form/query)
"""


def _audit_price(
    ctx: ToolContext,
    action: str,
    base_url: str,
    token: str = "",
    params: Optional[Dict[str, Any]] = None,
) -> str:
    """Route action to the appropriate handler group."""
    p = params or {}
    base = _base(base_url)

    for handler in (_handle_auth, _handle_requests, _handle_proposals,
                    _handle_supplier, _handle_email, _handle_prices, _handle_nsi):
        result = handler(action, base, token, p)
        if result is not None:
            return result

    # Raw passthrough
    if action == "raw":
        status, body = _make_request(
            p.get("method", "GET").upper(),
            f"{base}{p.get('path', '')}",
            token=token,
            json_data=p.get("json"),
            form_data=p.get("form"),
            query_params=p.get("query"),
        )
        return _fmt(status, body)

    return _UNKNOWN_ACTION_HELP.format(action=action)


# ── Tool registration ─────────────────────────────────────────────────────────

def get_tools() -> list:
    return [
        ToolEntry(
            "audit_price",
            {
                "name": "audit_price",
                "description": (
                    "Integration with the 'Audit Price' service — price auditing for procurement "
                    "(Аудит цен — анализ цен на объекты закупки).\n\n"
                    "Groups:\n"
                    "- Auth: login, refresh_token, register\n"
                    "- Search Requests: create/get/update/delete/patch requests and their items\n"
                    "- Commercial Proposals: upload files, get analysis results, export Excel\n"
                    "- Supplier analysis: run relevance calc, get results and Excel\n"
                    "- Price search: run calculation, get results and Excel\n"
                    "- Email: generate email body and mailto links\n"
                    "- NSI nomenclature: lookup КПГЗ, СПГЗ, СКТРУ directories\n"
                    "- Raw: direct HTTP call (method, path, json/form/query)\n\n"
                    "Typical workflow:\n"
                    "1. action=login → get JWT token\n"
                    "2. action=create_request → get request_id\n"
                    "3. action=upload_proposals or search_prices\n"
                    "4. action=get_analysis_results / get_price_results"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "description": (
                                "Action to perform. One of: login, refresh_token, register, "
                                "get_requests, create_request, update_request, patch_request, "
                                "get_request, delete_request, get_request_items, create_request_items, "
                                "upload_proposals, delete_proposals, get_proposal_files, "
                                "get_analysis_results, get_analysis_excel, upload_user_files, "
                                "run_supplier_analysis, get_supplier_results, get_supplier_excel, "
                                "get_email_body, create_mailto_link, "
                                "search_prices, get_price_results, get_prices_excel, "
                                "get_kpgz, get_spgz, get_sktru, raw"
                            ),
                        },
                        "base_url": {
                            "type": "string",
                            "description": "Base URL of the Audit Price service, e.g. https://audit-price.example.com",
                        },
                        "token": {
                            "type": "string",
                            "description": "JWT access token (from login). Required for all actions except login/register.",
                        },
                        "params": {
                            "type": "object",
                            "description": (
                                "Action-specific parameters. Examples:\n"
                                "  login: {username, password}\n"
                                "  create_request: {name, description, ...}\n"
                                "  get_requests: {search?, limit?, offset?}\n"
                                "  get_analysis_results: {request_id, limit?, offset?, min_price?, max_price?}\n"
                                "  get_kpgz: {search?, limit?, offset?}\n"
                                "  raw: {method, path, json?, form?, query?}"
                            ),
                        },
                    },
                    "required": ["action", "base_url"],
                },
            },
            _audit_price,
        )
    ]
