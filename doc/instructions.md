# Final Project: Compare & Contrast — Dual Implementation of an Expense Approval Workflow

## CST8917 - Serverless Applications | Winter 2026

---

## Overview

Implement the **same business workflow** using two different Azure serverless orchestration approaches, then present a critical comparison of your experience.

You will build an **expense approval pipeline** twice:

- **Version A:** Using **Azure Durable Functions** (code-first orchestration)
- **Version B:** Using **Azure Logic Apps + Service Bus** (visual/declarative orchestration)

|               |                                                                     |
| ------------- | ------------------------------------------------------------------- |
| **Weight**    | 10% of final grade                                                  |
| **Due Date**  | See Brightspace for exact deadline                                  |
| **Type**      | Individual                                                          |
| **AI Policy** | AI tools are permitted with mandatory disclosure (see Deliverables) |

---

## Learning Objectives

- Implement the same workflow using two different serverless orchestration approaches
- Compare code-first and visual/declarative orchestration from direct experience
- Evaluate trade-offs in development experience, testability, error handling, and cost
- Present and defend technical decisions to an audience

---

## The Workflow: Expense Approval Pipeline

Both versions must implement the following business rules:

| Rule                 | Description                                                                                                                                                 |
| -------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Input**            | An expense request with: employee name, employee email, amount, category, description, and manager email                                                    |
| **Validation**       | Reject requests missing any required field or using an invalid category. Valid categories: `travel`, `meals`, `supplies`, `equipment`, `software`, `other`. |
| **Auto-Approve**     | Expenses under $100 are automatically approved — no manager needed.                                                                                         |
| **Manager Approval** | Expenses of $100 or more require manager approval. The system waits for a manager decision.                                                                 |
| **Timeout**          | If no manager decision arrives within the timeout period, the expense is auto-approved and flagged as "escalated".                                          |
| **Notification**     | The employee receives an email with the final outcome (approved, rejected, or escalated).                                                                   |

You decide the architecture, components, and how each Azure service fits together. Refer to what you learned in Labs 1-4 and Weeks 1-12 lectures.

---

## Part 1: Version A — Durable Functions

Implement the expense approval workflow using **Azure Durable Functions** (Python v2 programming model).

Your implementation must demonstrate:

- Orchestrator, activity, and client functions
- The **Human Interaction pattern** with a durable timer for timeout
- Activity chaining for validation, processing, and notification
- An HTTP endpoint that simulates a manager approving or rejecting

Create a `test-durable.http` file covering these scenarios:

| #   | Scenario                                   | Expected Outcome |
| --- | ------------------------------------------ | ---------------- |
| 1   | Valid expense under $100                   | Auto-approved    |
| 2   | Valid expense >= $100, manager approves    | Approved         |
| 3   | Valid expense >= $100, manager rejects     | Rejected         |
| 4   | Valid expense >= $100, no manager response | Escalated        |
| 5   | Missing required fields                    | Validation error |
| 6   | Invalid category                           | Validation error |

---

## Part 2: Version B — Logic Apps + Service Bus

Implement the **same workflow** using **Azure Logic Apps** and **Azure Service Bus**.

Your implementation must include:

- A Service Bus queue for incoming expense requests
- A Logic App that orchestrates the workflow
- An Azure Function for validation (called by the Logic App)
- A Service Bus topic with filtered subscriptions for outcomes (approved, rejected, escalated)
- Email notifications to the employee

How you handle the manager approval step in Logic Apps is up to you. Logic Apps does not natively support the Human Interaction pattern the way Durable Functions does — figure out a reasonable approach and document your choice.

Test the same scenarios as Version A. Capture screenshots of Logic App run history, condition branches, emails received, and topic subscription counts.

---

## Part 3: Comparison Analysis

Write a structured comparison (800-1200 words) covering **all six** of these dimensions:

| Dimension                     | Question to Answer                                                                                                                                                           |
| ----------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Development Experience**    | Which was faster to build? Easier to debug? Which gave you more confidence the logic was correct?                                                                            |
| **Testability**               | Which was easier to test locally? Could you write automated tests for either?                                                                                                |
| **Error Handling**            | How does each handle failures? Which gives more control over retries and recovery?                                                                                           |
| **Human Interaction Pattern** | How did each handle "wait for manager approval"? Which was more natural?                                                                                                     |
| **Observability**             | Which made it easier to monitor runs and diagnose problems?                                                                                                                  |
| **Cost**                      | Estimate cost at ~100 expenses/day and ~10,000 expenses/day. Use the [Azure Pricing Calculator](https://azure.microsoft.com/pricing/calculator/) and state your assumptions. |

End with a **recommendation (200-300 words)**: If a team asked you to build this for production, which approach would you choose and why? When would you choose the other instead?

Be specific. "Durable Functions was easier to test" is weak. Describe _what you actually experienced_ and _why_ it mattered.

---

## Part 4: Presentation

Prepare and record a **video presentation** with a **slide deck** explaining your project.

### Slide Deck

Create a PowerPoint (or equivalent) presentation covering:

1. **Introduction** — The workflow and business rules
2. **Version A** — Architecture, key design decisions, demo of it working
3. **Version B** — Architecture, key design decisions, demo of it working
4. **Comparison** — Summary of your findings across the six dimensions (use visuals — tables, charts, or side-by-side comparisons)
5. **Recommendation** — Your verdict and reasoning
6. **Lessons Learned** — What surprised you? What would you do differently?

### Video Requirements

| Requirement   | Details                                                                                     |
| ------------- | ------------------------------------------------------------------------------------------- |
| **Duration**  | 10-15 minutes                                                                               |
| **Format**    | Screen recording with voice narration over your slide deck                                  |
| **Live Demo** | Include a live demo of both versions working (can be embedded in slides or shown alongside) |
| **Platform**  | YouTube (unlisted is fine)                                                                  |

You are presenting to a technical audience. Explain your decisions, not just what you built.

---

## Deliverables

### Repository Structure

```
CST8917-FinalProject-YourName/
├── README.md
├── version-a-durable-functions/
│   ├── function_app.py
│   ├── requirements.txt
│   ├── host.json
│   ├── local.settings.example.json
│   └── test-durable.http
├── version-b-logic-apps/
│   ├── function_app.py
│   ├── requirements.txt
│   ├── local.settings.example.json
│   ├── test-expense.http
│   └── screenshots/
└── presentation/
    ├── slides.pptx
    └── video-link.md
```

### README.md Contents

1. **Header** — Name, student number, course code, project title, date
2. **Version A Summary** — Brief description, design decisions, challenges
3. **Version B Summary** — Brief description, approach chosen for manager approval, challenges
4. **Comparison Analysis** — Full 800-1200 word comparison (Part 3)
5. **Recommendation** — 200-300 word recommendation
6. **References** — All sources with working hyperlinks
7. **AI Disclosure** — How AI was used, or explicit statement that it was not

> **Security:** Do NOT commit `local.settings.json` or any keys/connection strings. Use `local.settings.example.json` with placeholder values.

### Submission

1. Create a **public** GitHub repository with the structure above
2. Submit the **repository URL** on Brightspace before the deadline

---

## Grading Criteria

| Criterion                                | Weight | Description                                                                                                                                 |
| ---------------------------------------- | ------ | ------------------------------------------------------------------------------------------------------------------------------------------- |
| **Version A — Durable Functions**        | 20%    | Correct implementation with orchestrator, activities, human interaction pattern, and durable timer. All test cases pass.                    |
| **Version B — Logic Apps + Service Bus** | 20%    | Correct implementation with Logic App, Service Bus queue/topic, filtered subscriptions, and email. Screenshots show working workflow.       |
| **Comparison Analysis**                  | 25%    | All six dimensions addressed with specific, experience-based observations. Genuine comparison, not just describing each version separately. |
| **Presentation & Slides**                | 25%    | Clear slide deck with logical structure. Video demonstrates both versions working. Verbal explanation shows understanding of trade-offs.    |
| **Completeness & Quality**               | 10%    | All deliverables present, organized repository, proper citations, clean code, AI disclosure.                                                |

---

## Academic Integrity

- This is an **individual** project. You may discuss ideas with classmates, but all code, writing, and presentation must be your own.
- AI tools are **permitted** with mandatory disclosure.
- Plagiarism or undisclosed AI use will result in a grade of zero and may be referred to Academic Integrity procedures under Algonquin Policy AA48.
- All sources must be properly cited.
