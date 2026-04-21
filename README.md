# CST8917 Final Project — Compare & Contrast Expense Approval Workflow

**Student name:** [Your Name]  
**Student number:** [Your Student Number]  
**Course:** CST8917 — Serverless Applications  
**Project title:** Dual Implementation of an Expense Approval Pipeline (Durable Functions vs Logic Apps + Service Bus)  
**Date:** April 21, 2026  

---

## Version A — Durable Functions (Python v2)

Version A implements the expense pipeline in **Azure Durable Functions** using the **Python programming model v2**. An HTTP trigger starts the orchestration with the submitted JSON body. An **activity** validates required fields and the allowed category set (`travel`, `meals`, `supplies`, `equipment`, `software`, `other`). Amounts under **$100** short-circuit to **auto-approval** and an activity sends the employee notification (SMTP when configured, otherwise structured **logging** for local demos). Amounts **$100 or more** enter the **human interaction pattern**: the orchestrator races **`wait_for_external_event`** (`ManagerApproval`) against a **durable timer** whose length is controlled by **`APPROVAL_TIMEOUT_SECONDS`**. If the timer wins, the expense is **auto-approved** and flagged as **escalated**; if the event wins first, the manager’s decision is interpreted as approve or reject. A separate HTTP endpoint raises the external event for a given **instance ID**. This design keeps orchestration logic in one place, uses **task_any** for the race, and cancels the surviving timer when the manager responds first, following Microsoft’s guidance for human-interaction samples.

**Challenges encountered:** configuring **storage** for the Durable Task hub locally (Azurite or Azure Storage), ensuring the **Python worker indexing** feature flag is set, and aligning **test** expectations with the **approval timeout** when demonstrating escalation without calling the manager endpoint.

---

## Version B — Logic Apps + Service Bus

Version B targets the **same business rules** using **Azure Logic Apps** for orchestration and **Azure Service Bus** for ingress and outcome routing. Incoming messages arrive on a **queue** (`expense-requests` in the deployment guide). A **Python Azure Function** exposes **`/api/validate`**, mirroring Version A’s validation rules so both stacks stay comparable. For expenses **$100 or more**, Logic Apps does not offer Durable Functions’ built-in correlation between **external events** and **timers** in a single process, so this implementation uses a **documented workaround**: the Logic App generates a **correlation ID**, registers pending state via **`/api/pending/register`** (backed by **Azure Table Storage** when `TABLE_CONNECTION_STRING` is set, otherwise an **in-memory** store for single-instance local use), emails the manager a **decision URL**, and **polls** **`/api/pending/{id}/status`** inside an **Until** loop with **Delay** until a decision appears or a **timeout** iteration limit is reached—then it publishes an **escalated** outcome. Final states are sent to a **Service Bus topic** with an **`outcome`** application property (`approved`, `rejected`, `escalated`) consumed by **filtered subscriptions**, and the employee receives email through a connector of your choice (Outlook, Gmail, SendGrid) configured in the Logic App.

**Challenges encountered:** wiring **API connections** without committing secrets, expressing **long-running waits** visually in the designer, and keeping **polling** efficient enough for demos while remaining understandable in run history screenshots.

See [version-b-logic-apps/DEPLOYMENT.md](version-b-logic-apps/DEPLOYMENT.md) and [version-b-logic-apps/logic-app/README.md](version-b-logic-apps/logic-app/README.md) for Azure steps and workflow import notes.

---

## Comparison Analysis (800–1200 words)

### Development experience

Building Version A in code felt **linear**: the orchestrator function is the **source of truth** for branching, and refactoring amounted to editing one Python module. Tooling in VS Code or Cursor with the Functions Core Tools (`func start`) gave a **tight loop** for HTTP tests, though Durable’s **replay** semantics required discipline (no non-deterministic calls in the orchestrator). Version B felt **faster for integration sketching** once connectors existed—dragging **Service Bus** and **HTTP** actions is intuitive—but **slower** when the workflow crossed **multiple connectors** and **expression** syntax (`body('Action_name')`) had to be debugged in the portal. Confidence that “the happy path is correct” came **earlier in A** because unit-style reasoning maps directly to functions; in B, confidence grew **after** inspecting **run history** and fixing misnamed actions. Overall, **Version A was faster to reason about** for control flow, while **Version B was faster to assemble integrations** if connectors were already authorized.

### Testability

Version A was **easier to test locally** end-to-end: start the Functions host, hit **`/api/expenses`**, then **`/api/manager/{instanceId}`**, and poll the **status query URI** from the 202 response. Automated tests could wrap the **Durable REST** surface or use **Microsoft’s testing strategies** (mocking context is harder for orchestrators, but activities are plain Python and easy to unit test). Version B **depends on Azure** for faithful tests: **Service Bus** triggers and **connector** actions do not run fully on a laptop without emulators or real namespaces. You can still test the **Function** endpoints in isolation with **`test-expense.http`**, but **full workflow tests** require deployed resources and **record/replay** of Logic App runs or **manual** screenshot-based verification. Automated UI tests for the designer are uncommon; **integration tests in Azure** are the practical path.

### Error handling

Durable Functions centralizes **retries** via **activity retry policies** (optional) and **orchestrator** compensation patterns. Failures in activities surface as **orchestration failures** with rich **Application Insights** correlation. Logic Apps offer **scopes**, **retry policies per action**, and **configure run after** branches for **failure** paths—visually clear but **verbose** for complex compensation. For **transient** HTTP errors from the validation Function, both can retry; for **business validation errors**, Version A returns a **structured orchestration output**, while Version B should **branch** on `valid == false` before any Service Bus publish. **Perceived control** was higher in A for **fine-grained** exception types in Python; in B, control is **spread across** connector configuration and **run after** edges.

### Human interaction pattern

Version A’s **external event + durable timer** is the **canonical** pattern: the runtime correlates **`raise_event`** with **`wait_for_external_event`**, and **timeouts** are first-class. That felt **natural** for “wait for a manager, else escalate,” with **no polling**. Version B’s **polling + Table Storage** (or memory) models the same semantics **explicitly** and is **honest** about what Logic Apps can do out of the box, but it is **noisier** (many runs show **Delay** iterations) and requires **external state**. **Microsoft 365 Approvals** could replace polling in some tenants; this project used **HTTP + polling** for portability. **Naturalness** favored **Version A**; **transparency to non-developers** favored **Version B’s** diagram for stakeholders who think in **boxes and arrows**.

### Observability

**Application Insights** supports both stacks. Durable provides **instance-centric** traces, **custom status**, and **history** replay concepts that map well to debugging **stuck** orchestrations. Logic Apps add **run history** with **per-action inputs and outputs**, which is **excellent** for pinpointing **which connector** failed—often **faster** than reading stack traces for integration issues. For **cross-service** correlation, Version B may feel **clearer** in the portal when a failure is **inside** a connector; Version A may feel **clearer** when the bug is **algorithmic** in Python.

### Cost (illustrative, Azure Pricing Calculator)

**Assumptions:** Canada Central–style pricing class, Durable Functions on **Consumption** plan, Logic Apps **Consumption** per action, Service Bus **Standard** tier, 100 or 10,000 workflow **executions** per day scaling with **~15 actions** per Logic App run for the complex branch, **one Service Bus** message in and **one topic** message out per expense, **minimal** storage and observability overhead. Exact totals vary by region and negotiated discounts; use the [Azure Pricing Calculator](https://azure.microsoft.com/pricing/calculator/) with your subscription.

At **~100 expenses/day**, both solutions are typically **small monthly charges** dominated by **Functions executions**, **Logic App actions**, and **Service Bus** base cost. Durable may avoid **some** connector charges if HTTP is used heavily, while Logic Apps add **per-action** line items that accumulate with **polling loops** (each **Delay** + **HTTP** iteration is billable). At **~10,000 expenses/day**, **Logic App action counts** scale roughly with **actions × runs**, so **polling-heavy** designs can **outpace** well-batched Durable orchestrations unless **polling interval** and **iteration caps** are tuned. **Service Bus** Standard’s **base charge** matters at either scale; **throughput** units may enter the conversation for **very** high volumes. **Conclusion:** at low volume, **cost is unlikely to dominate** the choice; at high volume, **minimize superfluous actions** in Logic Apps and **review** Durable storage transactions for the **task hub**.

---

## Recommendation (200–300 words)

For a **production** team building this expense workflow **today**, I would **default to Azure Durable Functions** for the **core approval state machine** when the team is **comfortable with code-first development** and needs **precise human-interaction semantics** without **polling**. The **single orchestrator** with **external events and timers** reduces **moving parts**, keeps **correlation** in the platform, and simplifies **automated testing** of activities. I would still add **Application Insights**, **structured logging**, and **clear HTTP APIs** for managers.

I would **choose Logic Apps + Service Bus** when **integration breadth** and **change frequency by analysts** matter more than **compact orchestration code**—for example, if **many** SaaS connectors must be composed **without** frequent deployments, or if **operations** needs **visual** run diagnostics **without** reading Python. In that case, I would **invest** in **minimizing polling** (Approvals connector, dedicated response queue with **sessions**, or **callback** Functions) to control **cost and noise**.

**Hybrid** architectures are also valid: Durable for **long-running approval**, Logic Apps for **notifications** and **CRM** integration. The best choice depends on **team skills**, **tenant connector availability**, and **operational** ownership—not on **brand** alone.

Whichever path you pick, **document** the **manager approval** mechanism (polling vs Approvals vs queues) and **load-test** the **polling interval** so costs and **run history** noise stay acceptable under peak submission rates.

---

## References

1. Azure Durable Functions overview — [https://learn.microsoft.com/en-us/azure/azure-functions/durable/durable-functions-overview](https://learn.microsoft.com/en-us/azure/azure-functions/durable/durable-functions-overview)  
2. Durable Functions human interaction — [https://learn.microsoft.com/en-us/azure/azure-functions/durable/durable-functions-human-interaction](https://learn.microsoft.com/en-us/azure/azure-functions/durable/durable-functions-human-interaction)  
3. Azure Functions Python developer guide — [https://learn.microsoft.com/en-us/azure/azure-functions/functions-reference-python](https://learn.microsoft.com/en-us/azure/azure-functions/functions-reference-python)  
4. Azure Logic Apps workflow definition language — [https://learn.microsoft.com/en-us/azure/logic-apps/logic-apps-workflow-definition-language](https://learn.microsoft.com/en-us/azure/logic-apps/logic-apps-workflow-definition-language)  
5. Azure Service Bus topics and subscriptions — [https://learn.microsoft.com/en-us/azure/service-bus-messaging/service-bus-queues-topics-subscriptions](https://learn.microsoft.com/en-us/azure/service-bus-messaging/service-bus-queues-topics-subscriptions)  
6. Azure Pricing Calculator — [https://azure.microsoft.com/pricing/calculator/](https://azure.microsoft.com/pricing/calculator/)  

---

## AI disclosure

AI-assisted tools (including large language models in Cursor) were used to **accelerate scaffolding** (project layout, boilerplate for Azure Functions, Markdown documentation structure, and wording for this README), and to **look up** public Microsoft Learn patterns for Durable Functions APIs. All **technical decisions**, **Azure resource design**, **testing**, **deployment**, **presentation recording**, and **final validation** remain the author’s responsibility. Undisclosed use of AI is **not** intended; this section satisfies the course disclosure requirement.

---

## Repository layout

| Path | Description |
|------|-------------|
| [version-a-durable-functions/](version-a-durable-functions/) | Durable Functions app, HTTP tests |
| [version-b-logic-apps/](version-b-logic-apps/) | Validation/pending Functions, Logic App JSON starter, deployment guide |
| [presentation/](presentation/) | Slide deck and video link |

**Security:** Never commit `local.settings.json` or connection strings. Use `local.settings.example.json` as a template.

---

## Submission checklist

1. Replace **[Your Name]** and **[Your Student Number]** in this README.  
2. Create a **public** GitHub repository matching the course naming convention.  
3. Add **screenshots** under `version-b-logic-apps/screenshots/` from your Azure runs.  
4. Upload your **video** to **YouTube (unlisted)** and paste the URL in `presentation/video-link.md`.  
5. Submit the **repository URL** on Brightspace before the deadline.  
