# Logic App workflow definition

`workflow-definition.json` is a **starting point** you can import into a **Logic App (Consumption)** to verify the **HTTP validation** action against your Function App.

## Import (Portal)

1. Create a **Logic App (Consumption)**.
2. Open **Logic app designer** → **Blank template** (or **Import** from **JSON** if your UI supports paste).
3. Alternatively, use **Code view** and merge this definition with the **connections** object Azure generates for **Service Bus** queue trigger and **Service Bus** send-to-topic actions.

## What you still add in the designer

Per course requirements and [DEPLOYMENT.md](../DEPLOYMENT.md), extend this workflow with:

- **Service Bus** queue trigger (replace or parallel the HTTP trigger for production tests).
- **Conditions** after `Parse_Validation` for `valid == true` vs false.
- **Compose** / **Initialize variable** for `correlationId` and amount checks (`< 100` vs `>= 100`).
- **HTTP** actions for `/api/pending/register`, `/api/pending/{id}/status` inside an **Until** loop.
- **Service Bus** actions to send messages to topic `expense-outcomes` with application property **`outcome`** set to `approved`, `rejected`, or `escalated`.
- **Email** action (Office 365 Outlook, Gmail, or SendGrid) to notify the employee.

After you complete the design in Azure, **export** the workflow and replace this file if you want the repository to match your deployed Logic App exactly (remove secrets first).
