# LangGraph Purpose

LangGraph orchestrates TraceOps's internal incident investigation workflow.

It manages state, branching, pause-and-resume behavior, tool execution, reviewer logic, human approval, verification, memory, and automation dispatch.

# Investigation Flow

A typical investigation can include:

Incident created
→ classify incident
→ high-risk notification when required
→ retrieve company evidence
→ select operational tool
→ retrieve live operational data
→ detect deterministic conditions
→ analyze evidence
→ recommend action
→ reviewer or critic evaluation
→ propose safe action
→ human approval when required
→ execute action
→ verify execution
→ resolve incident
→ write incident memory
→ dispatch business automation

Not every incident uses every node.

Routing depends on the category, evidence, operational facts, and safety requirements.

# AI Responsibilities

The language model is used for tasks such as:

- incident classification
- evidence analysis
- explaining findings
- recommending next steps
- reviewer or critic reasoning

# Deterministic Responsibilities

Sensitive facts and actions are not determined only by the language model.

Deterministic backend logic handles areas such as:

- exact duplicate-payment detection
- exact transaction selection
- financial amount and currency validation
- action payload construction
- idempotency
- execution verification

# Failure Isolation

External automation failures should not invalidate a successfully completed core incident workflow.

For example, failure to notify Discord through n8n does not reverse a successfully verified refund or unresolved database transaction.