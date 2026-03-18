"""Audit Price tool — integration with the Audit Price service for procurement price analysis.

Service: "Аудит цен" — поиск и анализ цен на объекты закупки.
Covers: authentication, search requests, commercial proposals, supplier analysis,
price search, email generation, and nomenclature lookup.
"""
from __future__ import annotations

import json
from typing import Any, Dict, Optional

from ouroboros.tools.registry import ToolContext, ToolEntry


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
            method,
            url,
            headers=headers,
            json=json_data,
            data=form_data,
            params=query_params,
            timeout=30,
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
    icon = "✅" if status < 400 else ("❌" if status >= 400 else "⚠️")
    if status == 0:
        return f"⚠️ Connection error: {body}"
    try:
        body_str = json.dumps(body, ensure_ascii=False, indent=2)
    except Exception:
        body_str = str(body)[:3000]
    return f"{icon} HTTP {status}\n{body_str}"


def _audit_price(
    ctx: ToolContext,
    action: str,
    base_url: str,
    token: str = "",
    params: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Perform an action against the Audit Price service.

    Typical flow:
      1. action=login → get JWT token
      2. Use token for all subsequent calls
      3. action=create_request → get request_id
      4. Upload files, run analysis, get results
    """
    p = params or {}
    base_url = base_url.rstrip("/")

    # ── AUTH ──────────────────────────────────────────────────────────────────

    if action == "login":
        # x-www-form-urlencoded: username + password
        username = p.get("username") or p.get("email", "")
        password = p.get("password", "")
        status, body = _make_request(
            "POST",
            f"{base_url}/api/v1/auth/jwt/login",
            form_data={"username": username, "password": password},
        )
        result = _fmt(status, body)
        if status == 200 and isinstance(body, dict):
            access = body.get("access_token", "")
            refresh = body.get("refresh_token", "")
            result += f"\n\n💡 access_token: {access[:40]}..." if access else ""
            result += f"\n💡 refresh_token: {refresh[:40]}..." if refresh else ""
        return result

    if action == "refresh_token":
        refresh = p.get("refresh_token", "")
        status, body = _make_request(
            "POST",
            f"{base_url}/api/v1/auth/jwt/refresh_token",
            json_data={"refresh_token": refresh},
        )
        return _fmt(status, body)

    if action == "register":
        status, body = _make_request(
            "POST",
            f"{base_url}/api/v1/auth/register",
            token=token,
            json_data=p,
        )
        return _fmt(status, body)

    # ── SEARCH REQUESTS ───────────────────────────────────────────────────────

    if action == "get_requests":
        query = {}
        if "search" in p:
            query["search"] = p["search"]
        if "limit" in p:
            query["limit"] = p["limit"]
        if "offset" in p:
            query["offset"] = p["offset"]
        status, body = _make_request(
            "GET",
            f"{base_url}/api/v1/search-requests",
            token=token,
            query_params=query or None,
        )
        return _fmt(status, body)

    if action == "create_request":
        status, body = _make_request(
            "POST",
            f"{base_url}/api/v1/search-requests",
            token=token,
            json_data=p,
        )
        return _fmt(status, body)

    if action == "update_request":
        status, body = _make_request(
            "PUT",
            f"{base_url}/api/v1/search-requests",
            token=token,
            json_data=p,
        )
        return _fmt(status, body)

    if action == "patch_request":
        status, body = _make_request(
            "PATCH",
            f"{base_url}/api/v1/search-requests",
            token=token,
            json_data=p,
        )
        return _fmt(status, body)

    if action == "get_request":
        request_id = p.get("request_id", "")
        status, body = _make_request(
            "GET",
            f"{base_url}/api/v1/search-requests/{request_id}",
            token=token,
        )
        return _fmt(status, body)

    if action == "delete_request":
        request_id = p.get("request_id", "")
        status, body = _make_request(
            "DELETE",
            f"{base_url}/api/v1/search-requests/{request_id}",
            token=token,
        )
        return _fmt(status, body)

    # ── COMMERCIAL PROPOSALS ──────────────────────────────────────────────────

    if action == "upload_proposals":
        # params: {request_id, files: [{name, base64_content}, ...]}
        status, body = _make_request(
            "POST",
            f"{base_url}/api/v1/upload-commercial-proposals",
            token=token,
            json_data=p,
        )
        return _fmt(status, body)

    if action == "delete_proposals":
        status, body = _make_request(
            "DELETE",
            f"{base_url}/api/v1/delete-commerical-proposals",
            token=token,
            json_data=p,
        )
        return _fmt(status, body)

    if action == "get_proposal_files":
        request_id = p.get("request_id", "")
        status, body = _make_request(
            "GET",
            f"{base_url}/api/v1/commercial-proposals/files",
            token=token,
            query_params={"request_id": request_id},
        )
        return _fmt(status, body)

    if action == "get_analysis_results":
        request_id = p.get("request_id", "")
        query: Dict[str, Any] = {"request_id": request_id}
        for k in ("limit", "offset", "suppliers", "scores", "units", "min_price", "max_price"):
            if k in p:
                query[k] = p[k]
        status, body = _make_request(
            "GET",
            f"{base_url}/api/v1/analysis-results",
            token=token,
            query_params=query,
        )
        return _fmt(status, body)

    if action == "get_analysis_excel":
        request_id = p.get("request_id", "")
        filters = {k: v for k, v in p.items() if k != "request_id"}
        status, body = _make_request(
            "POST",
            f"{base_url}/api/v1/analysis-results/excel",
            token=token,
            query_params={"request_id": request_id},
            json_data=filters or {},
        )
        return _fmt(status, body)

    if action == "upload_user_files":
        status, body = _make_request(
            "POST",
            f"{base_url}/api/v1/upload-user-files",
            token=token,
            json_data=p,
        )
        return _fmt(status, body)

    # ── SUPPLIER ──────────────────────────────────────────────────────────────

    if action == "run_supplier_analysis":
        status, body = _make_request(
            "POST",
            f"{base_url}/api/v1/supplier-results/run",
            token=token,
            json_data=p,
        )
        return _fmt(status, body)

    if action == "get_supplier_results":
        status, body = _make_request(
            "POST",
            f"{base_url}/api/v1/supplier-results/results",
            token=token,
            json_data=p,
        )
        return _fmt(status, body)

    if action == "get_supplier_excel":
        request_id = p.get("request_id", "")
        filters = {k: v for k, v in p.items() if k != "request_id"}
        status, body = _make_request(
            "POST",
            f"{base_url}/api/v1/supplier-results/excel",
            token=token,
            query_params={"request_id": request_id},
            json_data=filters or {},
        )
        return _fmt(status, body)

    # ── EMAIL ─────────────────────────────────────────────────────────────────

    if action == "get_email_body":
        request_id = p.get("request_id", "")
        status, body = _make_request(
            "GET",
            f"{base_url}/api/v1/email-body",
            token=token,
            query_params={"request_id": request_id},
        )
        return _fmt(status, body)

    if action == "create_mailto_link":
        status, body = _make_request(
            "POST",
            f"{base_url}/api/v1/mailto-link",
            token=token,
            json_data=p,
        )
        return _fmt(status, body)

    # ── PRICE SEARCH ──────────────────────────────────────────────────────────

    if action == "search_prices":
        # Run price search calculation for a request
        status, body = _make_request(
            "POST",
            f"{base_url}/api/v1/prices/run",
            token=token,
            json_data=p,
        )
        return _fmt(status, body)

    if action == "get_price_results":
        request_id = p.get("request_id", "")
        # Try POST first (some swagger versions use POST for results)
        status, body = _make_request(
            "GET",
            f"{base_url}/api/v1/prices/results",
            token=token,
            query_params={"request_id": request_id},
        )
        return _fmt(status, body)

    if action == "get_prices_excel":
        request_id = p.get("request_id", "")
        filters = {k: v for k, v in p.items() if k != "request_id"}
        status, body = _make_request(
            "POST",
            f"{base_url}/api/v1/prices/excel",
            token=token,
            query_params={"request_id": request_id},
            json_data=filters or {},
        )
        return _fmt(status, body)

    # ── NSI / NOMENCLATURE ────────────────────────────────────────────────────

    if action == "get_kpgz":
        query = {}
        for k in ("search", "limit", "offset"):
            if k in p:
                query[k] = p[k]
        status, body = _make_request(
            "GET",
            f"{base_url}/api/v1/nsi/kpgz",
            token=token,
            query_params=query or None,
        )
        return _fmt(status, body)

    if action == "get_spgz":
        query = {}
        for k in ("search", "limit", "offset", "kpgz_id"):
            if k in p:
                query[k] = p[k]
        status, body = _make_request(
            "GET",
            f"{base_url}/api/v1/nsi/spgz",
            token=token,
            query_params=query or None,
        )
        return _fmt(status, body)

    if action == "get_sktru":
        query = {}
        for k in ("search", "limit", "offset", "spgz_id"):
            if k in p:
                query[k] = p[k]
        status, body = _make_request(
            "GET",
            f"{base_url}/api/v1/nsi/sktru",
            token=token,
            query_params=query or None,
        )
        return _fmt(status, body)

    # ── REQUEST ITEMS ─────────────────────────────────────────────────────────

    if action == "get_request_items":
        request_id = p.get("request_id", "")
        query = {"request_id": request_id}
        for k in ("limit", "offset"):
            if k in p:
                query[k] = p[k]
        status, body = _make_request(
            "GET",
            f"{base_url}/api/v1/search-requests/{request_id}/items",
            token=token,
            query_params=query,
        )
        return _fmt(status, body)

    if action == "create_request_items":
        request_id = p.get("request_id", "")
        items = p.get("items", p)
        status, body = _make_request(
            "POST",
            f"{base_url}/api/v1/search-requests/{request_id}/items",
            token=token,
            json_data=items,
        )
        return _fmt(status, body)

    # ── FALLBACK: raw request ─────────────────────────────────────────────────

    if action == "raw":
        method = p.get("method", "GET").upper()
        path = p.get("path", "")
        json_data = p.get("json")
        form_data = p.get("form")
        query_params = p.get("query")
        status, body = _make_request(
            method,
            f"{base_url}{path}",
            token=token,
            json_data=json_data,
            form_data=form_data,
            query_params=query_params,
        )
        return _fmt(status, body)

    return (
        f"❓ Unknown action: '{action}'\n\n"
        "Available actions:\n"
        "  Auth:        login, refresh_token, register\n"
        "  Requests:    get_requests, create_request, update_request, patch_request,\n"
        "               get_request, delete_request\n"
        "  Proposals:   upload_proposals, delete_proposals, get_proposal_files,\n"
        "               get_analysis_results, get_analysis_excel, upload_user_files\n"
        "  Supplier:    run_supplier_analysis, get_supplier_results, get_supplier_excel\n"
        "  Email:       get_email_body, create_mailto_link\n"
        "  Prices:      search_prices, get_price_results, get_prices_excel\n"
        "  NSI:         get_kpgz, get_spgz, get_sktru\n"
        "  Items:       get_request_items, create_request_items\n"
        "  Raw:         raw (method, path, json/form/query)\n"
    )


def get_tools() -> list:
    return [
        ToolEntry(
            "audit_price",
            {
                "name": "audit_price",
                "description": (
                    "Integration with the 'Audit Price' service — a system for price auditing "
                    "of procurement objects (Аудит цен — сервис анализа цен на объекты закупки).\n\n"
                    "Supports:\n"
                    "- Authentication: login (get JWT), refresh_token, register\n"
                    "- Search Requests: create/get/update/delete price search requests\n"
                    "- Commercial Proposals (КП): upload files, get analysis results, export to Excel\n"
                    "- Supplier analysis: run relevance calculation, get supplier results\n"
                    "- Price search: search by OKPD2/name/characteristics, get results\n"
                    "- Email: generate email body and mailto links for suppliers\n"
                    "- NSI/Nomenclature: lookup КПГЗ, СПГЗ, СКТРУ directories\n\n"
                    "Typical workflow:\n"
                    "1. action=login → get token\n"
                    "2. action=create_request → get request_id\n"
                    "3. action=upload_proposals (with КП files) or action=search_prices\n"
                    "4. action=get_analysis_results or action=get_price_results\n"
                    "5. action=run_supplier_analysis → action=get_supplier_results\n"
                    "6. action=get_email_body → action=create_mailto_link"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "description": (
                                "Action to perform. One of: login, refresh_token, register, "
                                "get_requests, create_request, update_request, patch_request, "
                                "get_request, delete_request, upload_proposals, delete_proposals, "
                                "get_proposal_files, get_analysis_results, get_analysis_excel, "
                                "upload_user_files, run_supplier_analysis, get_supplier_results, "
                                "get_supplier_excel, get_email_body, create_mailto_link, "
                                "search_prices, get_price_results, get_prices_excel, "
                                "get_kpgz, get_spgz, get_sktru, "
                                "get_request_items, create_request_items, raw"
                            ),
                        },
                        "base_url": {
                            "type": "string",
                            "description": "Base URL of the Audit Price service, e.g. 'https://audit.example.com'",
                        },
                        "token": {
                            "type": "string",
                            "description": "Bearer JWT token (from login). Required for most actions except login.",
                        },
                        "params": {
                            "type": "object",
                            "description": (
                                "Parameters for the action. Examples:\n"
                                "  login: {username, password}\n"
                                "  create_request: {name, description, ...}\n"
                                "  get_analysis_results: {request_id, limit?, offset?, min_price?, max_price?}\n"
                                "  upload_proposals: {request_id, files: [{name, base64_content}]}\n"
                                "  run_supplier_analysis: {request_id}\n"
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
