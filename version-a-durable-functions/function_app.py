"""Expense approval workflow — Azure Durable Functions (Python programming model v2)."""

from __future__ import annotations

import json
import logging
import os
import smtplib
from datetime import timedelta
from email.mime.text import MIMEText
from typing import Any, Optional, Tuple

import azure.durable_functions as df
import azure.functions as func

bp = df.Blueprint()

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
MANAGER_EVENT = "ManagerApproval"


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


@bp.activity_trigger(input_name="payload")
def validate_expense(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate required fields and category; normalize amount."""
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


@bp.activity_trigger(input_name="payload")
def notify_employee(payload: dict[str, Any]) -> dict[str, Any]:
    """Send outcome email or log when NOTIFY_LOG_ONLY=true."""
    expense = payload.get("expense") or {}
    final_status = payload.get("final_status", "unknown")
    mode = payload.get("approval_mode", "")
    to_addr = expense.get("employee_email", "")
    subject = f"Expense request — {final_status}"
    body = (
        f"Your expense request was processed.\n\n"
        f"Outcome: {final_status}\n"
        f"Approval path: {mode}\n"
        f"Amount: {expense.get('amount')}\n"
        f"Category: {expense.get('category')}\n"
    )

    log_only = os.environ.get("NOTIFY_LOG_ONLY", "true").lower() in ("1", "true", "yes")
    if log_only:
        logging.info("NOTIFY (log-only) to=%s: %s", to_addr, body)
        return {"sent": False, "channel": "log"}

    host = os.environ.get("SMTP_HOST", "").strip()
    if not host:
        logging.warning("NOTIFY_LOG_ONLY=false but SMTP_HOST empty; logging instead.")
        logging.info("NOTIFY to=%s: %s", to_addr, body)
        return {"sent": False, "channel": "log"}

    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER", "")
    password = os.environ.get("SMTP_PASSWORD", "")
    mail_from = os.environ.get("MAIL_FROM", user)

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = mail_from
    msg["To"] = to_addr

    with smtplib.SMTP(host, port) as smtp:
        smtp.starttls()
        if user and password:
            smtp.login(user, password)
        smtp.sendmail(mail_from, [to_addr], msg.as_string())

    return {"sent": True, "channel": "smtp"}


@bp.orchestration_trigger(context_name="context")
def expense_orchestrator(context: df.DurableOrchestrationContext):
    raw = context.get_input()
    expense = json.loads(raw) if isinstance(raw, str) else raw

    validation = yield context.call_activity(validate_expense, expense)
    if not validation["valid"]:
        return {
            "outcome": "validation_error",
            "errors": validation["errors"],
        }

    normalized = validation["normalized"]
    amount = float(normalized["amount"])

    if amount < 100.0:
        yield context.call_activity(
            notify_employee,
            {
                "final_status": "approved",
                "approval_mode": "auto",
                "expense": normalized,
            },
        )
        return {
            "outcome": "approved",
            "approval_mode": "auto",
            "expense": normalized,
        }

    timeout_sec = int(os.environ.get("APPROVAL_TIMEOUT_SECONDS", "90"))
    expiration = context.current_utc_datetime + timedelta(seconds=timeout_sec)
    timeout_task = context.create_timer(expiration)
    approval_task = context.wait_for_external_event(MANAGER_EVENT)
    winner = yield context.task_any([approval_task, timeout_task])

    if winner == approval_task:
        if hasattr(timeout_task, "is_completed") and not timeout_task.is_completed:
            timeout_task.cancel()
        payload = approval_task.result
        decision = (
            (payload.get("decision") if isinstance(payload, dict) else str(payload)) or ""
        ).lower()
        if decision in ("approve", "approved"):
            final_status = "approved"
        else:
            final_status = "rejected"

        yield context.call_activity(
            notify_employee,
            {
                "final_status": final_status,
                "approval_mode": "manager",
                "expense": normalized,
            },
        )
        return {
            "outcome": final_status,
            "approval_mode": "manager",
            "expense": normalized,
        }

    if hasattr(timeout_task, "is_completed") and not timeout_task.is_completed:
        timeout_task.cancel()

    yield context.call_activity(
        notify_employee,
        {
            "final_status": "escalated",
            "approval_mode": "escalated",
            "expense": normalized,
        },
    )
    return {
        "outcome": "escalated",
        "approval_mode": "escalated",
        "expense": normalized,
    }


@bp.route(route="expenses", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
@bp.durable_client_input(client_name="client")
async def start_expense(req: func.HttpRequest, client: df.DurableOrchestrationClient):
    try:
        body = req.get_json()
    except ValueError:
        return func.HttpResponse(
            json.dumps({"error": "Invalid JSON body"}),
            status_code=400,
            mimetype="application/json",
        )

    instance_id = await client.start_new("expense_orchestrator", client_input=body)
    logging.info("Started orchestration id=%s", instance_id)
    return client.create_check_status_response(req, instance_id)


@bp.route(route="manager/{instance_id}", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
@bp.durable_client_input(client_name="client")
async def manager_decision(req: func.HttpRequest, client: df.DurableOrchestrationClient):
    instance_id = req.route_params.get("instance_id")
    if not instance_id:
        return func.HttpResponse("Missing instance_id", status_code=400)

    try:
        body = req.get_json()
    except ValueError:
        return func.HttpResponse(
            json.dumps({"error": "Invalid JSON"}),
            status_code=400,
            mimetype="application/json",
        )

    decision = (body or {}).get("decision", "")
    await client.raise_event(instance_id, MANAGER_EVENT, {"decision": decision})
    return func.HttpResponse(
        json.dumps({"status": "event_raised", "instance_id": instance_id}),
        status_code=200,
        mimetype="application/json",
    )


app = func.FunctionApp()
app.register_functions(bp)
