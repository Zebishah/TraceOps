# Background Processing

IncidentIQ uses Inngest for durable background workflows.

Long-running or retryable operations should not depend on an HTTP request remaining open.

# Document Processing

Document processing follows a durable background flow.

Upload
→ background job created
→ Inngest event
→ document processing
→ indexing
→ job completion

Progress is persisted so the frontend can observe the job state.

# Retry Behavior

Inngest retries failed background operations according to the configured retry policy.

This is useful for temporary failures involving external systems such as vector databases or storage providers.

# Indexing Failure

If document processing succeeds but indexing continues to fail until retries are exhausted:

- the background job is marked failed
- failure information is preserved
- IncidentIQ can dispatch an indexing-failure automation to n8n
- operations staff can receive Discord and email alerts
- the failure can be recorded in an operational log

# Why Inngest and n8n Are Different

Inngest handles durable internal execution.

n8n handles external business automation.

For example:

Inngest:
retry document indexing

n8n:
notify operations staff after indexing permanently fails