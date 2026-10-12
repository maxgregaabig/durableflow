# DurableFlow Context Extension

DurableFlow Context records the information trail behind a workflow decision. The core runtime already checkpoints execution state after each step; this extension adds a small SQLite ledger for information state: what was observed, selected, mounted into a model prompt, and explicitly credited as influential.

It is not a vector database, RAG framework, knowledge-management platform, or observability platform. It records the minimal lineage needed to audit local deterministic workflows.

## OpenLineage Analogy

| OpenLineage Concept | DurableFlow Context Analog |
|---------------------|----------------------------|
| Dataset | `InfoArtifact` |
| Job | workflow step |
| Run | workflow execution |
| Lineage event | `ContextLedgerEvent` plus `DecisionLineage` |

## Run The Demo

```bash
python examples/inbox_triage_context_demo.py
python -m context.cli audit --db examples/inbox_triage_context_demo.sqlite --workflow-id wf-context-demo
```

The first command runs inbox triage with a `ContextLedger`. The second renders the same audit trace without exposing backend table names.

## What Gets Stored

The context schema is additive to the existing DurableFlow SQLite database:

- `context_artifacts`: registered source, prompt, and response artifacts
- `context_ledger_events`: observed, selected, consumed, and bookkeeping events
- `context_decisions`: model decision digests, model name, token counts, and cost
- `context_decision_lineage`: explicit influence links from decisions to source artifacts

Raw email bodies, prompts, and model responses are not persisted by default. APIs accept transient content to compute SHA-256 digests, then store only the digest, source reference, token count, and metadata.

## Before And After

Execution trace alone can answer:

- Which workflow steps completed?
- Was the workflow paused, resumed, approved, or rejected?
- What model and cost were recorded for a step?

Execution plus context trace can also answer:

- Which incoming email was observed?
- Which prior emails or calendar events were selected?
- Which artifacts were consumed by `triage_llm` or `draft_reply`?
- Which selected artifacts were explicitly credited by the mock model?

## Limits

v0.1 proves lineage, not full knowledge governance. The audit output intentionally states that freshness, trust, contradiction, policy compliance, supersession, and replay are roadmap capabilities.
