"""HTTP functions for Version B: validation and manager approval state (Logic App calls these)."""

from __future__ import annotations

import json
import logging
import os
import threading
from typing import Any, Dict, Optional, Tuple

import azure.functions as func

try:
    from azure.data.tables import TableClient, UpdateMode
except ImportError:  # pragma: no cover
    TableClient = None  # type: ignore
    UpdateMode = None  # type: ignore

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

VALID_CATEGORIES = frozenset(
    {"travel", "meals", "supplies", "equipment", "software", "other"}
)
REQUIRED_FIELDS = (
    "employee_name",
    "employee_email",
    "amount",
    "category",
    "description",
    "manager_email",
)

_memory_lock = threading.Lock()
_memory_store: Dict[str, Dict[str, Any]] = {}


def _parse_amount(raw: Any) -> Tuple[Optional[float], Optional[str]]:
    try:
        if raw is None:
            return None, "amount is required"
        v = float(raw)
        if v < 0:
            return None, "amount must be non-negative"
        return v, None
    except (TypeError, ValueError):
        return None, "amount must be a number"


def validate_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {"valid": False, "errors": ["body must be a JSON object"], "normalized": None}

    missing = [f for f in REQUIRED_FIELDS if f not in payload or payload[f] in (None, "")]
    if missing:
        return {
            "valid": False,
            "errors": [f"missing or empty: {', '.join(missing)}"],
            "normalized": None,
        }

    cat = str(payload["category"]).strip().lower()
    if cat not in VALID_CATEGORIES:
        return {
            "valid": False,
            "errors": [f"invalid category '{payload['category']}'"],
            "normalized": None,
        }

    amount, err = _parse_amount(payload.get("amount"))
    if err:
        return {"valid": False, "errors": [err], "normalized": None}

    normalized = {
        "employee_name": str(payload["employee_name"]).strip(),
        "employee_email": str(payload["employee_email"]).strip(),
        "amount": amount,
        "category": cat,
        "description": str(payload["description"]).strip(),
        "manager_email": str(payload["manager_email"]).strip(),
    }
    return {"valid": True, "errors": [], "normalized": normalized}


def _table_client() -> Optional[Any]:
    conn = os.environ.get("TABLE_CONNECTION_STRING", "").strip()
    if not conn or TableClient is None:
        return None
    table_name = os.environ.get("PENDING_TABLE_NAME", "PendingApprovals")
    return TableClient.from_connection_string(conn, table_name)


def _ensure_table(client: Any) -> None:
    try:
        client.create_table()
    except Exception as ex:  # pylint: disable=broad-except
        if "TableAlreadyExists" not in str(ex) and "409" not in str(ex):
            logging.warning("create_table: %s", ex)


def _get_row(correlation_id: str) -> Optional[Dict[str, Any]]:
    tc = _table_client()
    if tc is None:
        with _memory_lock:
            return dict(_memory_store.get(correlation_id, {})) or None
    _ensure_table(tc)
    try:
        entity = tc.get_entity(partition_key="expense", row_key=correlation_id)
        return dict(entity)
    except Exception:  # pylint: disable=broad-except
        return None


def _upsert_row(correlation_id: str, fields: Dict[str, Any]) -> None:
    tc = _table_client()
    entity = {"PartitionKey": "expense", "RowKey": correlation_id, **fields}
    if tc is None:
        with _memory_lock:
            cur = _memory_store.get(correlation_id, {})
            cur.update(fields)
            _memory_store[correlation_id] = cur
        return
    _ensure_table(tc)
    tc.upsert_entity(mode=UpdateMode.MERGE, entity=entity)  # type: ignore[union-attr]


@app.route(route="validate", methods=["POST"])
def validate_expense(req: func.HttpRequest) -> func.HttpResponse:
    """Called by Logic App HTTP action with the expense JSON body."""
    try:
        body = req.get_json()
    except ValueError:
        return func.HttpResponse(
            json.dumps({"valid": False, "errors": ["Invalid JSON"], "normalized": None}),
            status_code=200,
            mimetype="application/json",
        )
    result = validate_payload(body)
    return func.HttpResponse(
        json.dumps(result),
        status_code=200,
        mimetype="application/json",
    )


@app.route(route="pending/register", methods=["POST"])
def register_pending(req: func.HttpRequest) -> func.HttpResponse:
    """Logic App posts correlationId + normalized expense for manager path."""
    try:
        body = req.get_json()
    except ValueError:
        return func.HttpResponse(
            json.dumps({"ok": False, "error": "Invalid JSON"}),
            status_code=400,
            mimetype="application/json",
        )
    cid = (body or {}).get("correlationId") or (body or {}).get("correlation_id")
    expense = (body or {}).get("expense")
    if not cid or not isinstance(expense, dict):
        return func.HttpResponse(
            json.dumps({"ok": False, "error": "correlationId and expense required"}),
            status_code=400,
            mimetype="application/json",
        )
    _upsert_row(
        str(cid),
        {
            "Status": "waiting",
            "ExpenseJson": json.dumps(expense),
        },
    )
    base = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
    decision_url = f"{base}/api/pending/{cid}/decision" if base else ""
    return func.HttpResponse(
        json.dumps({"ok": True, "correlationId": cid, "managerDecisionUrl": decision_url}),
        status_code=200,
        mimetype="application/json",
    )


@app.route(route="pending/{cid}/status", methods=["GET"])
def pending_status(req: func.HttpRequest) -> func.HttpResponse:
    cid = req.route_params.get("cid") or ""
    row = _get_row(cid)
    if not row:
        return func.HttpResponse(
            json.dumps({"status": "unknown"}),
            status_code=404,
            mimetype="application/json",
        )
    status = row.get("Status", "waiting")
    out: Dict[str, Any] = {"status": status}
    if status in ("approved", "rejected") and row.get("Decision"):
        out["decision"] = row.get("Decision")
    return func.HttpResponse(json.dumps(out), status_code=200, mimetype="application/json")


@app.route(route="pending/{cid}/decision", methods=["POST"])
def manager_decision(req: func.HttpRequest) -> func.HttpResponse:
    """Manager (or demo) posts approve/reject; Logic App polls /status until not waiting."""
    cid = req.route_params.get("cid") or ""
    try:
        body = req.get_json()
    except ValueError:
        return func.HttpResponse(
            json.dumps({"ok": False, "error": "Invalid JSON"}),
            status_code=400,
            mimetype="application/json",
        )
    raw = (body or {}).get("decision", "")
    d = str(raw).lower()
    if d in ("approve", "approved"):
        decision = "approved"
    elif d in ("reject", "rejected"):
        decision = "rejected"
    else:
        return func.HttpResponse(
            json.dumps({"ok": False, "error": "decision must be approve or reject"}),
            status_code=400,
            mimetype="application/json",
        )
    row = _get_row(cid)
    if not row:
        return func.HttpResponse(
            json.dumps({"ok": False, "error": "unknown correlation id"}),
            status_code=404,
            mimetype="application/json",
        )
    _upsert_row(
        cid,
        {
            "Status": decision,
            "Decision": decision,
        },
    )
    return func.HttpResponse(
        json.dumps({"ok": True, "correlationId": cid, "status": decision}),
        status_code=200,
        mimetype="application/json",
    )
