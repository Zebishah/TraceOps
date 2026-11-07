# Operational Tools

TraceOps does not rely only on document retrieval.

Incidents can require live business data from operational systems.

Operational tools provide structured facts that the investigation workflow can use.

# Why Operational Data Matters

A company policy document may explain how duplicate payments should be handled.

It cannot prove which transactions actually occurred for a particular order.

Operational tools provide facts such as:

- customer information
- orders
- payment transactions
- transaction status
- transaction amount
- transaction currency
- provider identifiers

# AI and Tool Separation

The language model can decide which kind of information is relevant.

The backend tool returns structured operational data.

Sensitive conclusions can then be verified deterministically before any action is constructed.

# Example

For a duplicate-payment incident:

Incident
→ retrieve payment records
→ identify successful charge transactions
→ deterministic duplicate-payment detection
→ AI explains the situation
→ backend constructs safe refund proposal