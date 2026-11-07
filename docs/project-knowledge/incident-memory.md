# Incident Memory

IncidentIQ stores useful information from resolved incidents as searchable incident memory.

The purpose is to help future investigations benefit from previous successful cases.

# Memory Flow

A successfully resolved incident can produce a memory record containing relevant incident context and resolution information.

The memory is embedded and indexed into a dedicated Qdrant collection.

# Memory Retrieval

Future incidents can search for semantically similar historical incidents.

Memory retrieval is organization-scoped.

An organization must not retrieve historical incident memories belonging to another organization.

# Why Memory Is Separate

Incident memory is different from company documents.

Company documents contain policies, manuals, and organizational knowledge.

Incident memory contains experience from previous operational cases.

Keeping separate collections makes their purpose and filtering clearer.

# Example

A new incident reports that a customer was charged twice.

IncidentIQ may retrieve:

- payment policy documents
- current payment transactions
- similar previously resolved payment incidents

The model can use all three forms of evidence while still treating live operational data as the authority for current transaction facts.