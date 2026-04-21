from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

import azure.functions as func
from azure.core.exceptions import ResourceExistsError

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

_LOGGER = logging.getLogger(__name__)

REQUIRED_FIELDS = (
    "employee_name",
    "employee_email",
    "amount",
    "category",
    "description",
    "manager_email",
)
VALID_CATEGORIES = frozenset(
    ("travel", "meals", "supplies", "equipment", "software", "other")
)

_lock = threading.Lock()
_memory_store: Dict[str, Dict[str, Any]] = {}


def _validate_expense_core(body: Dict[str, Any]) -> Dict[str, Any]:
    """Same rules as Version A."""
    if not isinstance(body, dict):
        return {"valid": False, "error": "Invalid expense payload"}

    for field in REQUIRED_FIELDS:
        val = body.get(field)
        if val is None or (isinstance(val, str) and not val.strip()):
            return {"valid": False, "error": f"Missing required field: {field}"}

    try:
        amount = float(body["amount"])
    except (TypeError, ValueError):
        return {"valid": False, "error": "amount must be a number"}

    if amount < 0:
        return {"valid": False, "error": "amount must be non-negative"}

    cat = str(body["category"]).lower().strip()
    if cat not in VALID_CATEGORIES:
        return {"valid": False, "error": "Invalid category"}

    return {"valid": True, "amount": amount, "category": cat}


def _table_client():
    conn = os.environ.get("TABLE_CONNECTION_STRING") or os.environ.get(
        "AzureWebJobsStorage"
    )
    if not conn or conn == "UseDevelopmentStorage=true":
        return None
    try:
        from azure.data.tables import TableServiceClient
    except ImportError:
        return None
    return TableServiceClient.from_connection_string(conn)


def _entity_id(correlation_id: str) -> Tuple[str, str]:
    return correlation_id, "pending"


def _ensure_table(name: str) -> None:
    tc = _table_client()
    if tc is None:
        return
    try:
        tc.create_table(name)
    except ResourceExistsError:
        pass


def _persist_put(correlation_id: str, data: Dict[str, Any]) -> None:
    tc = _table_client()
    if tc is None:
        with _lock:
            _memory_store[correlation_id] = dict(data)
        return

    name = os.environ.get("PENDING_TABLE_NAME", "PendingExpenses")
    _ensure_table(name)
    table = tc.get_table_client(table_name=name)
    pk, rk = _entity_id(correlation_id)
    entity = {
        "PartitionKey": pk,
        "RowKey": rk,
        "ExpenseJson": json.dumps(data.get("expense")),
        "TimeoutSeconds": int(data.get("timeout_seconds", 120)),
        "CreatedUtc": data.get("created_utc", ""),
        "Decision": data.get("decision") or "",
    }
    table.upsert_entity(entity=entity)


def _persist_get(correlation_id: str) -> Optional[Dict[str, Any]]:
    tc = _table_client()
    if tc is None:
        with _lock:
            row = _memory_store.get(correlation_id)
            return dict(row) if row else None
    table = tc.get_table_client(table_name=os.environ.get("PENDING_TABLE_NAME", "PendingExpenses"))
    pk, rk = _entity_id(correlation_id)
    try:
        e = table.get_entity(pk, rk)
    except Exception:
        return None
    expense = json.loads(e["ExpenseJson"]) if e.get("ExpenseJson") else {}
    raw_decision = (e.get("Decision") or "").strip()
    return {
        "expense": expense,
        "timeout_seconds": int(e.get("TimeoutSeconds", 120)),
        "created_utc": e.get("CreatedUtc", ""),
        "decision": raw_decision if raw_decision else None,
    }


def _persist_update_decision(correlation_id: str, decision: str) -> None:
    tc = _table_client()
    if tc is None:
        with _lock:
            if correlation_id in _memory_store:
                _memory_store[correlation_id]["decision"] = decision
        return

    from azure.data.tables import UpdateMode

    name = os.environ.get("PENDING_TABLE_NAME", "PendingExpenses")
    table = tc.get_table_client(table_name=name)
    pk, rk = _entity_id(correlation_id)
    table.update_entity(
        entity={"PartitionKey": pk, "RowKey": rk, "Decision": decision},
        mode=UpdateMode.MERGE,
    )


@app.route(route="validate", methods=["POST"])
def validate_expense(req: func.HttpRequest) -> func.HttpResponse:
    """Called by Logic App — mirrors Version A validation."""
    try:
        body = req.get_json()
    except ValueError:
        return _json_response({"error": "Request body must be valid JSON"}, 400)
    result = _validate_expense_core(body)
    return _json_response(result, 200)


@app.route(route="pending/register", methods=["POST"])
def pending_register(req: func.HttpRequest) -> func.HttpResponse:
    """Register a correlation id for manager approval polling (amount >= $100 path)."""
    try:
        body = req.get_json()
    except ValueError:
        return _json_response({"error": "Invalid JSON"}, 400)
    if not isinstance(body, dict):
        return _json_response({"error": "Body must be an object"}, 400)

    correlation_id = body.get("correlation_id") or str(uuid.uuid4())
    expense = body.get("expense")
    if not isinstance(expense, dict):
        return _json_response({"error": "expense object is required"}, 400)

    timeout_seconds = int(body.get("timeout_seconds", os.environ.get("APPROVAL_TIMEOUT_SECONDS", "120")))
    created = datetime.now(timezone.utc).isoformat()
    row = {
        "expense": expense,
        "timeout_seconds": timeout_seconds,
        "created_utc": created,
        "decision": None,
    }
    _persist_put(correlation_id, row)
    return _json_response({"correlation_id": correlation_id, "registered": True}, 201)


@app.route(route="pending/{correlation_id}/status", methods=["GET"])
def pending_status(req: func.HttpRequest) -> func.HttpResponse:
    """Logic App polls this until a decision exists or timeout → escalated."""
    correlation_id = ((req.route_params or {}).get("correlation_id") or "").strip()
    if not correlation_id:
        return _json_response({"error": "correlation_id is required"}, 400)
    row = _persist_get(correlation_id)
    if not row:
        return _json_response({"error": "Unknown correlation_id"}, 404)

    decision = row.get("decision")
    if decision in ("approved", "rejected", "escalated"):
        return _json_response(
            {
                "correlation_id": correlation_id,
                "resolved": True,
                "outcome": decision,
                "expense": row.get("expense"),
            },
            200,
        )

    created = row.get("created_utc")
    timeout_sec = int(row.get("timeout_seconds", 120))
    if created:
        try:
            start = datetime.fromisoformat(created.replace("Z", "+00:00"))
        except ValueError:
            start = datetime.now(timezone.utc)
    else:
        start = datetime.now(timezone.utc)

    if datetime.now(timezone.utc) - start > timedelta(seconds=timeout_sec):
        _persist_update_decision(correlation_id, "escalated")
        row = _persist_get(correlation_id) or row
        return _json_response(
            {
                "correlation_id": correlation_id,
                "resolved": True,
                "outcome": "escalated",
                "expense": row.get("expense"),
            },
            200,
        )

    return _json_response(
        {
            "correlation_id": correlation_id,
            "resolved": False,
            "outcome": None,
            "pending": True,
        },
        200,
    )


@app.route(route="pending/{correlation_id}/decision", methods=["POST"])
def pending_decision(req: func.HttpRequest) -> func.HttpResponse:
    """Manager callback — sets approved or rejected for polling to observe."""
    correlation_id = ((req.route_params or {}).get("correlation_id") or "").strip()
    if not correlation_id:
        return _json_response({"error": "correlation_id is required"}, 400)
    try:
        body = req.get_json()
    except ValueError:
        return _json_response({"error": "Invalid JSON"}, 400)
    if not isinstance(body, dict) or "approved" not in body:
        return _json_response({"error": "Body must include boolean 'approved'"}, 400)
    approved = body.get("approved")
    if not isinstance(approved, bool):
        return _json_response({"error": "'approved' must be boolean"}, 400)

    row = _persist_get(correlation_id)
    if not row:
        return _json_response({"error": "Unknown correlation_id"}, 404)

    decision = "approved" if approved else "rejected"
    _persist_update_decision(correlation_id, decision)
    return _json_response(
        {"correlation_id": correlation_id, "outcome": decision},
        200,
    )


def _json_response(data: Dict[str, Any], status: int) -> func.HttpResponse:
    return func.HttpResponse(
        json.dumps(data, default=str),
        status_code=status,
        mimetype="application/json",
    )
