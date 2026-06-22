# DurableFlow Context

**Context durability for agentic workflows.**

DurableFlow proves that agentic execution needs a durable shell:

- checkpoint every step
- survive crashes
- gate side effects
- emit enough telemetry to explain what happened

The Context extension makes the same claim for information.

> A workflow checkpoint is incomplete unless the runtime can explain what information entered context, what was selected, what was consumed by the model, and what the workflow credited as influential in a decision.

Context is a peer extension to DurableFlow core, alongside Colony, Readiness, and Target Planner. It adds a SQLite-backed context ledger, decision lineage, and audit surfaces that make information flow durable and inspectable.

## Why This Exists

Most agent frameworks focus on execution:

```text
Prompt -> Model -> Tool -> Action
```

Most observability platforms focus on traces:

```text
Prompt -> Response -> Cost -> Latency
```

Most knowledge-management platforms focus on governance:

```text
Knowledge -> Review -> Approval -> Publication
```

Context focuses on a different question:

```text
Information -> Context -> Decision -> Action
```

Specifically:

- What did the workflow know?
- Where did that information come from?
- Which artifacts were selected?
- Which artifacts were mounted into the prompt?
- Which artifacts were credited as influential?
- Can a reviewer inspect the knowledge trail after the fact?

## Execution Durability vs Context Durability

Execution durability answers:

> Did the workflow survive crashes, retries, approval pauses, and side effects?

Context durability answers:

> What did the workflow know, where did that knowledge come from, and which sources influenced the model's decision?

These are separate concerns. A workflow can execute perfectly and still be wrong because it operated on bad information.

## What Context Adds

The extension introduces five core concepts.

**InfoArtifact**

A registered piece of information: incoming email, prior email, calendar event, tool output, prompt payload, or model response.

**ContextLedgerEvent**

An append-only record describing how information moved through a workflow:

```text
observed → retrieved → {selected, rejected} → consumed → influential
```

**DecisionRecord**

A durable record of a model decision: prompt digest, response digest, model used, token usage, cost, and workflow linkage.

**DecisionLineage**

Links decisions back to the source artifacts that influenced them.

**Context Audit Trace**

A human-readable view answering:

> What information did this workflow use?

## Run The Demo

```bash
python examples/inbox_triage_context_demo.py
python -m context.cli audit --db examples/inbox_triage_context_demo.sqlite --workflow-id wf-context-demo
```

Or use the start script:

```bash
./start.sh context
```

The first demo runs inbox triage with a `ContextLedger`. The CLI renders the same audit trace without exposing backend table names.

## MVP Scope

v0.2a (current) delivers assembly lineage with per-artifact metadata.

Included (v0.1 + v0.2a):

- artifact registration
- context lifecycle events (observed, retrieved, selected, rejected, consumed, influential)
- decision records
- explicit lineage
- deterministic fixture attribution
- assembly lineage metadata validation
- per-artifact retrieval metadata (score, rank, rejection_reason) in audit output
- rejected context display with reasons
- audit summary with observed/retrieved/selected/rejected counts
- audit CLI
- deterministic tests

Deferred:

- trust and freshness policy
- supersession
- context replay
- prompt replay
- context compaction
- OpenLineage export
- vector search
- knowledge governance workflows

The first demo is simple:

> Run inbox triage. Open audit trace. See the exact artifacts retrieved, selected, rejected with reasons, consumed, and credited as influential in the model decision.

## Design Principles

**Information Is First-Class State**

Workflows have state. Information has state too. Context records both.

**Explicit Attribution Only**

v0.1 does not infer influence from free text. Influence must come from explicit `influential_artifact_ids` or deterministic fixture attribution. Heuristic attribution is intentionally deferred.

**Append-Only Ledger**

The ledger records events. Audit views are derived from those events. The history remains intact.

**Privacy by Default**

Context stores content digests, source references, token counts, and metadata. Raw content is not persisted by default.

**Optional Adoption**

Existing DurableFlow workflows continue to run unchanged. Context is additive.

## Example

Without Context:

```text
Workflow completed successfully.

Classification:
action_required
```

With Context (v0.2a - assembly lineage):

```text
Context Audit Trace for wf-context-demo: 11 selected, 14 consumed, 2 influential, 2 decisions.
Assembly: 64 observed, 59 retrieved, 11 selected, 48 rejected

Step: select_context
  Status: selected
  Mounted context:
    - prior email: email-012 [retrieved, selected]
      Source: prior_email; Reference: mock_emails:email-012
      Influence: Influential
      Retrieval: method: bm25, score: 37.71, rank: 2
    - calendar event: cal-001 [retrieved, selected]
      Source: calendar_event; Reference: mock_calendar:cal-001
      Influence: Influential
      Retrieval: method: bm25, score: 45.55, rank: 1
  Rejected context:
    - prior email: email-018 [retrieved, rejected]
      Source: prior_email; Reference: mock_emails:email-018
      Reason: token_budget
      Retrieval: score: 11.59, rank: 12
    - prior email: email-029 [retrieved, rejected]
      Source: prior_email; Reference: mock_emails:email-029
      Reason: token_budget
      Retrieval: score: 11.23, rank: 13
    [... 46 more rejected artifacts ...]

Step: triage_llm
  Decision: Decision recorded for triage_llm
    Influential sources:
      - calendar event: cal-001
      - prior email: email-012
```

The audit trace shows:
- **59 artifacts were retrieved** from the corpus of 64
- **11 were selected** for the token budget
- **48 were rejected** with explicit reasons (`token_budget`)
- Each artifact shows its **retrieval score, rank, and method**
- The **influential sources** are explicitly linked to the decision

Run the demo to see the full trace:

```bash
python examples/inbox_triage_context_demo.py
```

The result is not just execution history. It is a knowledge trail with assembly lineage.

## Relationship To Context Engineering

Modern agent systems increasingly depend on context engineering: selecting, assembling, compressing, and managing the information available to an agent. Context does not attempt to solve context engineering.

Instead, it records what happened after context engineering made its choices. It provides provenance, lineage, auditability, and inspectability for context that entered a workflow.

## Relationship To OpenLineage

Conceptually:

| Data Systems | DurableFlow Context |
|--------------|---------------------|
| Dataset | `InfoArtifact` |
| Job | workflow step |
| Run | workflow execution |
| Lineage event | `ContextLedgerEvent` plus `DecisionLineage` |

Context borrows lineage ideas from data infrastructure while remaining a small local SQLite implementation.

## What Context Is Not

Context is not:

- a vector database
- a RAG framework
- a memory system
- a knowledge graph
- an observability platform
- a knowledge-management product

It is the missing operational primitive between:

> We selected some context.

and:

> We can prove which information the workflow used and credited.

## Audit Boundary

v0.2a delivers assembly lineage with per-artifact metadata:

- retrieved/rejected events are recorded with validated metadata
- audit traces show per-artifact retrieval scores, ranks, and rejection reasons
- reviewers can inspect why artifact A was selected over artifact B
- assembly summary shows observed/retrieved/selected/rejected counts

It does not prove:

- freshness
- trustworthiness
- correctness
- contradiction resolution
- policy compliance

Those capabilities are planned as future layers built on top of the ledger.

## Future Roadmap

v0.2a (delivered June 2026):

- assembly lineage events (retrieved, rejected)
- metadata validation (required keys, unknown keys, type checks)
- per-artifact retrieval metadata in audit output (scores, ranks, reasons)
- workflow instrumentation for assembly lineage
- audit summary counts (observed, retrieved, selected, rejected)

v0.2b:

- superseded event type and labeling
- context replay reconstruction

v0.3:

- trust policy
- freshness policy
- context blocking
- prompt replay
- context compaction

v0.4:

- context governance
- human review
- knowledge approval workflows

Later:

- OpenLineage export
- graph visualization
- retrieval integrations
- multi-tenant administration

## Implementation Map

- [context/ledger.py](ledger.py) records artifacts, lifecycle events, decisions, and lineage.
- [context/audit_view.py](audit_view.py) builds and renders the user-facing audit trace.
- [context/cli.py](cli.py) exposes `python -m context.cli audit`.
- [examples/inbox_triage_context_demo.py](../examples/inbox_triage_context_demo.py) runs the end-to-end context demo.
- [docs/context-extension.md](../docs/context-extension.md) documents schema details, privacy handling, and the before/after audit comparison.
- [context/context-spec.md](context-spec.md) is the implementation spec.

## Core Idea

DurableFlow started with a simple claim:

> Agentic systems need durable execution.

Context extends that claim:

> Agentic systems also need durable information.

Execution durability explains how the workflow survived. Context durability explains what the workflow knew.
