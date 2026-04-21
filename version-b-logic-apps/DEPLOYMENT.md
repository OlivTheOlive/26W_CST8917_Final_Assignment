# Version B — Azure deployment guide

This folder contains the **Azure Functions** used by the Logic App for **validation** and **manager approval state**. The **Logic App** itself is built in the Azure Portal (or exported to `logic-app/workflow-definition.json`). Connection-based actions (Service Bus send, queue trigger) require you to create **API connections** in your resource group; those secrets must **not** be committed to git.

## Azure resources

| Resource | Purpose |
|----------|---------|
| Resource group | Holds everything below |
| **Service Bus** namespace (Standard) | Queue + topic |
| Queue `expense-requests` | Inbound expense JSON (Logic App trigger) |
| Topic `expense-outcomes` | Final outcomes with filterable properties |
| Subscriptions | `sub-approved`, `sub-rejected`, `sub-escalated` with SQL filters on `outcome` (see below) |
| **Function App** (Python 3.9+) | This code under `function_app.py` |
| **Storage account** | Required by Functions; use Table API for pending rows when `TABLE_CONNECTION_STRING` is set |
| **Logic App (Consumption)** | Orchestration, connectors, loops |

### Topic subscription filters (example)

Add a **user property** or **application property** `outcome` on messages sent to the topic (`approved`, `rejected`, `escalated`). Example SQL filter on subscription `sub-approved`:

```text
outcome = 'approved'
```

Repeat for `rejected` and `escalated`.

## Function App settings

Copy `local.settings.example.json` to `local.settings.json` locally (never commit). In Azure, set:

- `TABLE_CONNECTION_STRING` — Storage account connection string (Tables).
- `PENDING_TABLE_NAME` — Default `PendingApprovals`.
- `PUBLIC_BASE_URL` — `https://<your-function-app>.azurewebsites.net` so `register` returns a manager URL.

Create the table automatically on first run, or create an empty table named `PendingApprovals` in the storage account.

## Logic App — recommended flow

1. **Trigger:** When a message is received in a queue (`expense-requests`, peek-lock).
2. **Parse JSON** — Body of the Service Bus message = expense object.
3. **HTTP POST** `https://<function-app>/api/validate` with the same JSON body.
4. **Condition** — `valid` is `true` (from JSON `body('HTTP')['valid']` — adjust expression to your action name).
5. If **invalid:** **Send message** to topic `expense-outcomes` with property `outcome=rejected` (or `validation_error` if you prefer), then **send email** to employee describing the error.
6. If **valid** and **amount \< 100:** Send to topic with `outcome=approved`, **email** employee.
7. If **valid** and **amount ≥ 100:**
   - **Initialize variable** `correlationId` = `guid()`.
   - **HTTP POST** `/api/pending/register` with body `{ "correlationId": "<guid>", "expense": <normalized object from validate response> }`.
   - **Send email** to `manager_email` with instructions and the `managerDecisionUrl` from the register response (or build URL from `PUBLIC_BASE_URL` + `/api/pending/{correlationId}/decision`).
   - **Until** (limit e.g. 120 iterations):  
     - **Delay** 5–10 seconds.  
     - **HTTP GET** `/api/pending/{correlationId}/status`.  
     - If **status** is `approved` or `rejected`, set variable `done=true` and exit Until (use Conditions inside the loop or compose + terminate).  
   - After Until: if **status** still `waiting`, treat as **timeout** → send to topic with `outcome=escalated` and **email** employee as escalated.  
   - If **approved** or **rejected**, send to topic with the corresponding `outcome` and **email** employee.

> **Why polling?** Logic Apps does not implement Durable Functions’ single-process human-interaction primitive. Storing pending state in **Table Storage** (or memory fallback for single-instance demos) plus **HTTP polling** is a common, documentable pattern. Alternatives include Microsoft 365 **Approvals** (tenant-dependent) or a second Service Bus queue for manager replies with sessions.

## Export workflow to the repo

In the Logic App designer, **Download** or use **Export template** and save the workflow definition into `logic-app/workflow-definition.json` after you replace connection identifiers with parameters for sharing (or keep secrets out of git and describe connections only in this file).

## Local testing

1. Run **Azurite** or use real Azure Storage for Tables.
2. `func start` from this directory with `local.settings.json` configured.
3. Use `test-expense.http` against `http://localhost:7071`.

Service Bus triggers and topic sends are exercised only after deployment to Azure (or with Service Bus connection strings in local emulation if you configure them).
