from __future__ import annotations

import json
import logging
import os
from datetime import timedelta
from typing import Any, Dict

import azure.functions as func
import azure.durable_functions as df

app = df.DFApp(http_auth_level=func.AuthLevel.ANONYMOUS)

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


@app.route(route="expenses", methods=["POST"])
@app.durable_client_input(client_name="client")
async def start_expense(req: func.HttpRequest, client: df.DurableOrchestrationClient) -> func.HttpResponse:
    """Start the expense orchestration with a JSON body (see test-durable.http)."""
    try:
        body = req.get_json()
    except ValueError:
        return func.HttpResponse(
            json.dumps({"error": "Request body must be valid JSON"}),
            status_code=400,
            mimetype="application/json",
        )

    if not isinstance(body, dict):
        return func.HttpResponse(
            json.dumps({"error": "Body must be a JSON object"}),
            status_code=400,
            mimetype="application/json",
        )

    env_timeout = int(os.environ.get("APPROVAL_TIMEOUT_SECONDS", "120"))
    timeout_sec = int(body.get("approval_timeout_seconds", env_timeout))
    merged: Dict[str, Any] = {**body, "_approval_timeout_seconds": timeout_sec}

    instance_id = await client.start_new(
        "expense_orchestration",
        client_input=merged,
    )
    return client.create_check_status_response(req, instance_id)


@app.route(route="manager/{instance_id}", methods=["POST"])
@app.durable_client_input(client_name="client")
async def manager_decision(
    req: func.HttpRequest,
    client: df.DurableOrchestrationClient,
) -> func.HttpResponse:
    """Raise ManagerApproval for the orchestration instance (manager approve / reject)."""
    instance_id = req.route_params.get("instance_id")
    if not instance_id:
        return func.HttpResponse(
            json.dumps({"error": "instance_id is required"}),
            status_code=400,
            mimetype="application/json",
        )

    try:
        payload = req.get_json()
    except ValueError:
        return func.HttpResponse(
            json.dumps({"error": "Request body must be valid JSON"}),
            status_code=400,
            mimetype="application/json",
        )

    if not isinstance(payload, dict) or "approved" not in payload:
        return func.HttpResponse(
            json.dumps({"error": "Body must include boolean 'approved'"}),
            status_code=400,
            mimetype="application/json",
        )

    approved = payload.get("approved")
    if not isinstance(approved, bool):
        return func.HttpResponse(
            json.dumps({"error": "'approved' must be a boolean"}),
            status_code=400,
            mimetype="application/json",
        )

    try:
        await client.raise_event(instance_id, "ManagerApproval", payload)
    except Exception as ex:  # noqa: BLE001 — surface client errors cleanly for HTTP
        _LOGGER.exception("raise_event failed")
        msg = str(ex)
        code = 404 if "404" in msg or "not found" in msg.lower() else 400
        return func.HttpResponse(
            json.dumps({"error": msg}),
            status_code=code,
            mimetype="application/json",
        )

    return func.HttpResponse(
        json.dumps({"status": "event_raised", "instance_id": instance_id}),
        status_code=202,
        mimetype="application/json",
    )


@app.orchestration_trigger(context_name="context")
def expense_orchestration(context: df.DurableOrchestrationContext):
    """Orchestrate validation, auto-approval, manager wait + timer (human interaction)."""
    expense: Dict[str, Any] = context.get_input() or {}
    timeout_seconds = int(expense.get("_approval_timeout_seconds", 120))

    validation = yield context.call_activity("validate_expense", expense)
    if not validation.get("valid"):
        yield context.call_activity(
            "send_expense_notification",
            {
                "employee_email": expense.get("employee_email", ""),
                "employee_name": expense.get("employee_name", ""),
                "outcome": "validation_error",
                "detail": validation.get("error", "validation failed"),
            },
        )
        return {
            "outcome": "validation_error",
            "error": validation.get("error"),
        }

    amount = float(validation["amount"])

    if amount < 100.0:
        yield context.call_activity(
            "send_expense_notification",
            {
                "employee_email": expense["employee_email"],
                "employee_name": expense["employee_name"],
                "outcome": "approved",
                "detail": "auto-approved (amount under $100)",
                "amount": amount,
                "category": validation["category"],
            },
        )
        return {
            "outcome": "approved",
            "reason": "auto",
            "amount": amount,
        }

    deadline = context.current_utc_datetime + timedelta(seconds=timeout_seconds)
    timer_task = context.create_timer(deadline)
    approval_task = context.wait_for_external_event("ManagerApproval")

    winner = yield context.task_any([timer_task, approval_task])

    if winner == timer_task:
        yield context.call_activity(
            "send_expense_notification",
            {
                "employee_email": expense["employee_email"],
                "employee_name": expense["employee_name"],
                "outcome": "escalated",
                "detail": (
                    "No manager response before timeout; recorded as escalated "
                    "(still approved per policy)"
                ),
                "amount": amount,
                "category": validation["category"],
            },
        )
        return {
            "outcome": "escalated",
            "amount": amount,
            "note": "timeout",
        }

    decision_raw = winner.result
    if not isinstance(decision_raw, dict):
        approved = False
    else:
        approved = bool(decision_raw.get("approved"))

    if approved:
        yield context.call_activity(
            "send_expense_notification",
            {
                "employee_email": expense["employee_email"],
                "employee_name": expense["employee_name"],
                "outcome": "approved",
                "detail": "approved by manager",
                "amount": amount,
                "category": validation["category"],
            },
        )
        return {"outcome": "approved", "reason": "manager", "amount": amount}

    yield context.call_activity(
        "send_expense_notification",
        {
            "employee_email": expense["employee_email"],
            "employee_name": expense["employee_name"],
            "outcome": "rejected",
            "detail": "rejected by manager",
            "amount": amount,
            "category": validation["category"],
        },
    )
    return {"outcome": "rejected", "amount": amount}


@app.activity_trigger(input_name="payload")
def validate_expense(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Validate required fields and category; normalize amount and category."""
    if not isinstance(payload, dict):
        return {"valid": False, "error": "Invalid expense payload"}

    for field in REQUIRED_FIELDS:
        val = payload.get(field)
        if val is None or (isinstance(val, str) and not val.strip()):
            return {"valid": False, "error": f"Missing required field: {field}"}

    try:
        amount = float(payload["amount"])
    except (TypeError, ValueError):
        return {"valid": False, "error": "amount must be a number"}

    if amount < 0:
        return {"valid": False, "error": "amount must be non-negative"}

    cat = str(payload["category"]).lower().strip()
    if cat not in VALID_CATEGORIES:
        return {"valid": False, "error": "Invalid category"}

    return {"valid": True, "amount": amount, "category": cat}


@app.activity_trigger(input_name="payload")
def send_expense_notification(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Notify the employee (log locally; extend with SendGrid / SMTP in Azure)."""
    outcome = payload.get("outcome", "unknown")
    email = payload.get("employee_email", "")
    detail = payload.get("detail", "")
    line = (
        f"[expense-notification] to={email!r} outcome={outcome!r} detail={detail!r} "
        f"payload={json.dumps(payload, default=str)}"
    )
    _LOGGER.info(line)
    return {"sent": True, "outcome": outcome, "logged": True}
