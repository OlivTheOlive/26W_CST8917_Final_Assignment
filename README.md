# CST8917 Final Project - Compare & Contrast Expense Approval Workflow

**Student name:** Olivie Bergeron
**Course:** CST8917 - Serverless Applications

[Youtube](https://youtu.be/h7qxh-GjGI4)

---

## Comparison Analysis (800-1200 words)

### Development experience

Version A (Durable Functions) felt **linear**: the orchestrator and activities live in one Python module, so refactoring meant editing ordinary code. Running **`func start`** locally gave a fast loop for HTTP tests, and errors surfaced as Python tracebacks in the terminal—familiar if you already debug code. The main mental tax was **deterministic orchestration**: you learn quickly not to call non-deterministic APIs inside the orchestrator, which the runtime documents well but still trips you up once or twice.

Version B (Logic Apps + Service Bus + Functions) felt **faster for “plumbing”** once connectors were authorized—dragging a Service Bus trigger and an HTTP action is quick. Confidence that the **whole** story was correct came **later**, after runs in Azure, because the designer hides expression wiring until something fails. Wiring **conditions**, **topic** sends, and **Until** loops took longer than the happy-path diagram suggests, especially when expression names (`body('HTTP')` vs the real action name) did not match. Overall, Version A was faster to **reason about** end-to-end; Version B was faster to **sketch integrations** if you treat the portal as the source of truth.

**Debugging on Azure (and why Logic Apps is especially painful)**  
Local debugging for Functions is acceptable; **cloud debugging is worse** because you are separated from the process: you rely on **Log stream**, **Application Insights**, and **run history** instead of breakpoints. For **Logic Apps**, debugging often **sucks** in practice: you get **run history** with green/red steps, but when something fails you see **inputs/outputs** blobs that may not match what you thought you configured. **BadRequest** or **404** on HTTP often means **headers**, **body shape**, or **subscription** issues that the designer does not validate until runtime. **Peek-lock** queues add another layer—failed runs can leave messages in odd states. **Expressions** are easy to mistype (`body('HTTP')` vs `body('HTTP_1')`), and the **Code view** is the only place to spot some mistakes. Retrying **“Submit from this action”** helps, but it does not replace a real debugger stepping through orchestration logic. In short: **Functions** fail like code; **Logic Apps** fail like misconfigured integration, and the portal UI makes you hunt through layers instead of stopping on a line.

### Testability

Version A was **easier to test locally**: start the host, call **`/api/expenses`**, then **`/api/manager/{id}`**, and poll the status URI from the 202 response. The surface area is HTTP + Durable management endpoints; you can script that with curl or REST Client. Automated tests are plausible for **activities** (plain Python) and harder for the **orchestrator** without mocking the durable context, but the split is clear.

Version B is **split across Azure**: Service Bus, Logic App, and deployed Functions. You can unit-test the **validation Function** locally like any HTTP API, but a **faithful** end-to-end test needs the **queue**, **topic**, and **Logic App** in Azure (or heavy emulators). Automated UI tests for the designer are uncommon; **integration tests in Azure** are the realistic path. For a course project, **manual** run history and screenshots are often the proof.

### Error handling

Durable Functions centralizes workflow state: activity failures become orchestration failures with history in **Application Insights**, and you can attach **retry policies** to activities. You express **branches** in code, so “what happens if validate fails?” is one `if` away.

Logic Apps exposes **per-action retry**, **scopes**, and **configure run after** for failure paths—powerful but **verbose**: each branch is another box, and compensation spreads across the canvas. A bad connector call shows clearly **which action** failed in run history, which is good for **integration** failures; algorithmic mistakes are still buried in expressions. For validation errors returned as **200 + `{ valid: false }`**, both stacks must **branch in logic**—Durable in Python, Logic Apps in conditions—so neither magically fixes bad JSON or wrong HTTP headers.

### Human interaction pattern

Version A uses **`wait_for_external_event`** plus a **durable timer** and **`task_any`**: the platform correlates **raise_event** with the waiting instance. That matches the assignment’s “wait for manager, else escalate” with **no polling** in your code.

Version B has **no** first-class equivalent. The practical approach is **correlation id** + **HTTP polling** (`GET /api/pending/{id}/status`) inside an **Until** loop with **Delay**, backed by Table Storage or in-memory state in the Function. That is **honest** about Logic Apps’ limits but noisier: run history fills with **Delay** iterations, and you must cap iterations to control cost. It feels less **natural** than Durable’s event model, but the **diagram** is easy to show to someone non-technical.

### Observability

Durable Functions gives **instance-centric** traces: instance ID, history, custom status—good for “why is this orchestration stuck?” **Application Insights** queries help correlate activities to orchestrations.

Logic Apps **run history** shows **each action’s inputs and outputs**, which is excellent when a **connector** misbehaves—you see the exact payload the designer sent. For **expression bugs**, observability is weaker: outputs look “almost right” until you notice a wrong field. **Service Bus** metrics and **dead-letter** queues add another dashboard. Neither is a substitute for stepping through code, but Logic Apps wins for **pinpointing which connector failed**; Durable wins for **algorithmic** bugs in one file.

### Cost (illustrative)

**Assumptions:** Canada Central–class pricing, Consumption Function Apps, Consumption Logic Apps (per action), Service Bus **Standard** (queue + topic), modest storage and Application Insights. Figures are **order-of-magnitude**; use the [Azure Pricing Calculator](https://azure.microsoft.com/pricing/calculator/) for your region.

At **~100 expenses/day**, both are typically **a few dollars per month** or less for a student workload: Function executions, Logic App **actions** (each **Delay** + **HTTP** in an Until loop counts), and Service Bus base charges dominate more than CPU.

At **~10,000 expenses/day**, **Logic App action count** scales with **actions × runs**. A polling-heavy **Until** loop multiplies actions fast (each iteration bills). Durable Functions scales with **orchestration turns** and **storage** for the task hub; tuning matters, but **unnecessary polling iterations** in Logic Apps can **outpace** a tight Durable orchestration if not capped. **Service Bus Standard** has a **fixed monthly component** that matters at low volume; at high volume, **throughput units** may enter the conversation.

**Conclusion:** At low volume, **cost rarely decides** the architecture; at high volume, **minimize superfluous Logic App actions** (tighter polling intervals, fewer branches) and review **Durable storage** transactions for the task hub.

---

## Recommendation (200–300 words)

For a **production** team building this expense workflow **today**, I would **default to Azure Durable Functions** for the **approval state machine** when the team is comfortable with **code-first** development and needs **clear human-interaction semantics** (external event + durable timer) **without** building polling and external state by hand. A single orchestrator, **Application Insights**, and straightforward HTTP APIs for managers reduce moving parts and make **automated testing** of activities realistic.

I would choose **Logic Apps + Service Bus** when **integration** and **operator-visible workflows** matter more than compact orchestration code—for example, many **SaaS connectors** maintained by analysts, or operations teams that need **run history per connector** without reading Python. In that case I would still **minimize polling** (shorter Until loops, sensible timeouts, or alternative patterns such as a dedicated response queue) to control **cost and noise** in run history.

**Debugging reality:** Regardless of choice, plan for **cloud-first** troubleshooting (logs, run history, metrics). If **fast iteration and precise failure diagnosis in code** are top priorities, Durable Functions has an edge; if **visibility into third-party connector behavior** is the pain point, Logic Apps run history is a genuine advantage—even though **Logic Apps expression debugging** remains frustrating compared to a normal IDE.

---

## References

1. Azure Durable Functions overview - [https://learn.microsoft.com/en-us/azure/azure-functions/durable/durable-functions-overview](https://learn.microsoft.com/en-us/azure/azure-functions/durable/durable-functions-overview)
2. Durable Functions human interaction - [https://learn.microsoft.com/en-us/azure/azure-functions/durable/durable-functions-human-interaction](https://learn.microsoft.com/en-us/azure/azure-functions/durable/durable-functions-human-interaction)
3. Azure Functions Python developer guide - [https://learn.microsoft.com/en-us/azure/azure-functions/functions-reference-python](https://learn.microsoft.com/en-us/azure/azure-functions/functions-reference-python)
4. Class labs as reference

---

## AI disclosure

## AI-assisted tools were used to **fix and accelerate scaffolding**, and to **look up** public Microsoft Learn patterns for Durable Functions APIs. All **technical decisions**, **Azure resource design**, **testing**, **deployment**, **presentation recording**, and **final validation** remained my responsibility.
