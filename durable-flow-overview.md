# DurableFlow Consolidated Product Scope

**Status:** Draft summary  
**Audience:** Product management, technical leadership, and project reviewers  
**Purpose:** Consolidate the product scope of DurableFlow core and its extension tracks so the total surface area, priorities, and boundaries can be assessed without reading each implementation specification.

---

## 1. Product Thesis

DurableFlow is a small educational lab for the operational layer beneath agentic systems. Most agent demos emphasize intelligence: prompts, model choice, tool calls, retrieval, and user-visible answers. DurableFlow focuses on whether a workflow can survive production-like operating conditions: crashes, approvals, provider failures, context limits, side effects, cost pressure, unreliable compute, and audit demands.

The repo is not positioned as a production replacement for mature platforms such as Temporal, LangGraph, LiteLLM, LangSmith, or broader evaluation/observability products. Its product value is inspectability. It strips operational patterns down to local SQLite, deterministic fixtures, no required API keys, readable demos, and tests that make the underlying mechanics legible.

The core product claim is:

> A useful agentic workflow needs durable execution, controlled side effects, model fallback, cost accounting, context selection, and auditability before it can be trusted outside a demo.

The extension tracks expand that claim into adjacent product questions:

- **Colony:** Can durable execution turn spot-like compute into completable long-running work, and can that be measured against a naive baseline?
- **Agent Readiness Pack:** Can a prototype agent be evaluated for deployability through deterministic failure scenarios and a verdict-first report?
- **Context:** Can the workflow show what information it observed, retrieved, selected, rejected, consumed, and credited in a model decision?
- **Target Planner:** Can requests use a budgeted, local-first, constraint-driven target plan that escalates only on verifiable failure?
- **DataFlow preview:** Can an agentic workflow be declared and audited as a typed data transformation graph?
- **LangSmith adapter preview:** Can DurableFlow export local telemetry and context lineage into LangSmith without making LangSmith part of the core runtime?

---

## 2. Product Portfolio Summary

| Area | Current status in docs | Primary product outcome | Main audience |
|------|------------------------|-------------------------|---------------|
| DurableFlow Core | Implemented / ready | A minimal durable workflow runtime for assistant-like flows | Backend engineers and AI infrastructure teams |
| Colony | Implemented benchmark / ready spec | Measured durability benefit for spot-like compute workloads | Infrastructure evaluators and compute marketplace architects |
| Agent Readiness Pack | Implemented demo / ready spec | Ship / do-not-ship readiness verdict for agent workflows | Solutions architects, FDEs, enterprise AI deployers |
| Context | Implemented v0.2a / draft spec | Context audit trace showing knowledge lineage and assembly lineage | AI infrastructure engineers and knowledge architects |
| Target Planner | Draft spec | Budgeted local-first target selection with verifiable escalation | Platform engineers and API gateway owners |
| DataFlow | Draft spec / preview | Typed data DAG and runtime materialization lineage for agentic workflows | Workflow designers and AI infrastructure engineers |
| LangSmith Adapter | Proposal / preview | Optional export of local telemetry and context lineage to LangSmith | Production AI platform and observability teams |

The combined scope is best understood as a product suite of operational primitives, not a single monolithic framework. Each extension should remain independently useful while sharing the same DurableFlow ethos: local-first, deterministic, inspectable, and honest about boundaries.

---

## 3. Core DurableFlow Scope

### 3.1 Product Role

DurableFlow core is the foundation. It demonstrates the minimum operational shell around a multi-step LLM workflow. The reference workflow is inbox triage: ingest an email, select relevant context, classify it, draft a reply, pause for approval, and send only after approval.

The core product is not the inbox assistant itself. The inbox workflow exists to make the operational primitives concrete and testable.

### 3.2 Capabilities

DurableFlow core covers:

- **Durable execution:** workflows checkpoint after each completed step and can resume from the last durable state.
- **Crash recovery:** demos use real process termination to show restart and resume behavior.
- **Approval gates:** unsafe or user-facing actions pause until an operator approves or rejects them.
- **Approval rejection behavior:** default rejection terminates the workflow; extension workflows can choose continue semantics where rejection becomes an observation for later steps.
- **Idempotent side effects:** external actions are protected against duplicate execution after crash or retry.
- **Model routing and fallback:** a primary model path can fail over to a secondary path.
- **Cost accounting:** model calls record token usage and estimated cost per workflow step.
- **Context selection:** prior emails and calendar events are ranked and packed under a hard token budget.
- **Telemetry:** workflow events, approval decisions, model fallback, crash recovery, and completion are emitted as structured logs.

### 3.3 Demo and Proof Surface

The core proof surface is CLI-first:

- crash recovery demo
- inbox triage demo
- approval demo
- MCP write-gating demo
- context audit demo when combined with the Context extension

The intended reviewer should be able to run the demos without external credentials and inspect local artifacts such as SQLite state, telemetry, and generated reports.

### 3.4 Scope Boundaries

DurableFlow core is not:

- a general assistant framework
- a production workflow engine
- a hosted service
- a RAG platform
- a full observability product
- a policy engine or authorization framework

The core does not claim high throughput, multi-tenant isolation, distributed scheduling, or production-grade secrets management. Those are deliberately outside the educational artifact.

---

## 4. Extension: Colony

### 4.1 Product Role

Colony extends DurableFlow into a benchmark for long-running work on unreliable or spot-like compute. Its product question is measurable: does durable checkpointing and recovery improve completion rates compared with a naive retry baseline under the same loss schedule?

The headline artifact is the benchmark result, not the controller software itself.

### 4.2 Product Claim

Colony's load-bearing claim is:

> Durable execution can turn spot-like heterogeneous compute into completable work without human intervention, and the improvement can be measured against a naive baseline under an identical chaos protocol.

The benchmark must be framed carefully. It is not a claim that any specific provider is unreliable. It is a test of whether work survives the class of interruptions common to spot-priced or heterogeneous compute marketplaces.

### 4.3 Capabilities

Colony covers:

- batch execution of long-running jobs
- a durable runner that checkpoints each job stage
- a naive baseline that restarts work after failure
- seeded chaos schedules applied identically to both runners
- simulated instance loss in mock mode
- optional live smoke path against Vast.ai when credentials are available
- cost accounting based on instance time and hourly price
- recovery and migration after instance loss
- human intervention tracking, expected to remain zero in benchmark runs
- a final comparison table showing completion, cost, wall-clock time, recoveries, and interventions
- optional terminal or HTML scoreboard surfaces for live run interpretation

### 4.4 Product Proof

The product proof is a side-by-side result:

- naive runner completion rate
- durable Colony runner completion rate
- cost delta
- wall-clock delta
- recovery count
- intervention count
- identical seed / chaos profile disclosure

The methodology must include threats to validity: mock-versus-live gap, single workload, loss-rate assumptions, controller-induced termination as a live proxy, and lack of network partition or straggler modeling.

### 4.5 Scope Boundaries

Colony is not:

- a distributed scheduler
- a Temporal, Ray, or Kubernetes replacement
- a multi-agent framework
- a predictive failure system
- a broad live compute marketplace product

Spectral or predictive coordination work is explicitly future hypothesis only. The MVP succeeds or fails on measured durability, cost, and completion under a clear protocol.

---

## 5. Extension: Agent Readiness Pack

### 5.1 Product Role

The Agent Readiness Pack turns DurableFlow into a deployment-readiness evaluation layer for agentic workflows. Its central product surface is a verdict-first report that helps a responsible engineer decide whether an agent can be put in front of customer systems.

The reference agent is a support ticket triage and resolution agent. The main value is not the support agent; it is the before/after evidence showing what the durability layer buys.

### 5.2 Product Claim

The readiness extension claims:

> A fragile prototype agent can be wrapped in a durable shell, tested against production failure modes, and evaluated through a ship / do-not-ship report based on measured scenario results.

The report should answer the primary user question quickly: "Can I ship this agent without causing a customer incident?"

### 5.3 Capabilities

The readiness scope includes:

- a durable agent runner where each reason-act-observe turn is checkpointed
- gated write tools and ungated read tools
- idempotent external writes
- max-turn and token-budget ceilings
- inherited model fallback and cost accounting
- deterministic failure injection scenarios:
  - tool timeout
  - malformed tool output
  - prompt injection
  - context overflow
  - model fallback
  - crash after side effect
- a naked baseline configuration without DurableFlow protections
- a wrapped configuration using DurableFlow protections
- scoring by Safety, Reliability, Cost, and Observability
- readiness JSON output
- rendered Markdown / CLI report
- optional MCP demo against a mock legacy CRM
- optional ADK adapter boundary, explicitly short of claiming real ADK Runner end-to-end execution

### 5.4 Product Proof

The proof surface is the before/after readiness report:

- verdict first
- blocker before metric detail
- naked score versus wrapped score
- durability delta
- category rows ordered with Safety first
- headline metrics capped so the report does not become a metrics dump
- full detail available below the decision summary

The strongest demo is the prompt-injection scenario: the naked agent executes an unsafe write, while the wrapped agent gates or blocks it.

### 5.5 Scope Boundaries

The readiness pack is not:

- a full agent framework
- an automated authorization policy engine
- proof that any arbitrary agent is production-safe
- a real Google ADK Runner integration unless a future no-network fixture proves it
- a replacement for enterprise eval, observability, and governance programs

The readiness score must never be hardcoded or decorative. It is only credible if it derives from measured scenario results.

---

## 6. Extension: Context

### 6.1 Product Role

Context extends DurableFlow from durable execution state to durable information state. The product goal is to let a reviewer understand what information entered a workflow, what was selected for a step, what was consumed by a model, and which artifacts were explicitly credited as influential.

This extension addresses an enterprise concern that execution durability alone cannot answer: a workflow may complete successfully while relying on bad, stale, irrelevant, or untraceable information.

### 6.2 Product Claim

The Context extension claims:

> A workflow checkpoint is incomplete unless the runtime can also explain what information entered context, what was selected, what was consumed by model steps, and what the workflow credited as influential in a decision.

The current v0.2a claim is lineage and assembly visibility, not full knowledge governance.

### 6.3 Capabilities

Context covers:

- information artifact registration for incoming emails, prior emails, calendar events, tool outputs, prompts, and model responses
- artifact lifecycle events:
  - observed
  - retrieved
  - selected
  - rejected
  - consumed
- decision records with prompt and response digests, model metadata, token counts, and cost
- explicit decision lineage connecting model decisions to credited source artifacts
- deterministic fixture attribution for influence
- assembly lineage metadata validation for retrieval method, score, rank, and rejection reason
- per-artifact retrieval metadata in audit output
- rejected context display with explicit reasons
- audit summary counts for observed, retrieved, selected, rejected, consumed, and influential artifacts
- selected-but-not-influential artifacts shown in audit output
- privacy-safe default behavior using digests and content references instead of raw content
- a context audit read model and CLI
- a mandatory audit boundary explaining what v0.2a does and does not prove
- deterministic integration with the inbox triage workflow

### 6.4 Product Proof

The proof surface is the Context Audit Trace. A reviewer should be able to run inbox triage, open the trace, and see:

- what information the workflow observed
- which candidate artifacts were retrieved
- which items were selected for context
- which items were rejected, with reasons such as token budget
- how retrieved artifacts ranked through scores and positions
- which items were mounted into model steps
- which selected artifacts were credited as influential
- which selected artifacts were not credited
- the boundary that trust, freshness, contradiction, policy compliance, and replay are not evaluated in v0.2a

### 6.5 Scope Boundaries

Context v0.2a is not:

- a vector database
- a RAG framework
- a knowledge-management product
- a full observability platform
- a trust or freshness policy system
- a contradiction detector
- a replay system
- an OpenLineage implementation

Influence must not be inferred from free-form model text. It is accepted only from explicit structured attribution or deterministic fixtures.

Roadmap layers include trust policy, supersession, context replay, prompt replay, compaction lineage, upstream governance, exports, graph visualization, retrieval integrations, and richer dataflow views.

### 6.6 Preview: DataFlow

DataFlow is a draft sibling extension above DurableFlow core and complementary to Context. Context answers what information the model saw and credited. DataFlow asks a different question:

> What typed data products flowed through the workflow, which step contracts produced or consumed them, and did runtime materializations match the declared data DAG?

The preview design introduces `DataTypeSpec`, `StepContract`, `DataflowSpec`, `DataArtifact`, `DataDependency`, `DataflowEvent`, `DataflowLedger`, and `DataflowGraphView`. The intended inbox triage demo would declare the workflow as a typed data DAG:

```text
IncomingEmail
  -> ContextQuery
  -> SelectedContextSet
  -> TriageDecision
  -> DraftReply
  -> ApprovalDecision
  -> SentReplyReceipt
```

DataFlow should remain local, SQLite-first, and optional. It must not require Context, and Context must not require DataFlow. When both are enabled, they should cross-link only through explicit references, such as a `SelectedContextSet` data artifact pointing to selected context artifact IDs.

The current status is proposal/spec, not implemented runtime. It is on the roadmap because it makes the product story broader than execution logs and context traces: agentic workflows become typed data transformation graphs with audit surfaces.

---

## 7. Extension: Target Planner

### 7.1 Product Role

Target Planner is a draft extension for budgeted, local-first execution planning across local and cloud model targets. It provides an OpenAI-compatible proxy path where callers can request `"model": "auto"` plus constraints rather than naming a specific model.

The planner's standalone value is spend control and explainability. A team should be able to adopt it as a constrained endpoint without adopting Colony or the readiness pack.

### 7.2 Product Claim

The planner claims:

> A request can be routed through a durable, constraint-aware target plan that stays within budget, prefers local execution where permitted, and escalates to cloud only on verifiable failure.

The most important honesty boundary is that the planner is not a quality oracle. It does not predict answer quality. It records verifiable outcomes such as transport success, latency, and optional caller-supplied output checks.

### 7.3 Capabilities

Target Planner scope includes:

- OpenAI-compatible chat-completion endpoint
- `"model": "auto"` planner path
- explicit model bypass path
- constraint parsing for:
  - max cost
  - max latency
  - privacy
  - region
  - tier floor
  - objective
  - session budget
  - shadow mode
  - optional output check
- target registry covering local, economy, and frontier tiers
- local-first primary selection by default
- ordered fallback / escalation plan
- infeasible result when hard constraints cannot be met
- budget ledger with downgrade behavior near exhaustion
- plan cache for hot-path performance
- target statistics based on verifiable outcomes
- non-streaming escalation after verifiable failure
- streaming commit-before-stream rule to avoid silent mid-stream fallback
- plan trace view explaining why a request ran where it did
- value benchmark comparing planner cost and verifiable success against static model choices

### 7.4 Planned Product Proof

The planned proof surface is twofold:

- **Plan trace:** explains the selected target, constraints, alternatives, confidence, escalation, and predicted-versus-actual outcome in user language.
- **Value benchmark:** should show that the planner reduces cost against an all-frontier baseline while maintaining comparable verifiable success.

The planner should remain clearly draft until that measurable cost/value proof exists. It should be judged not only by correctness but by whether it beats static defaults on measurable cost and reliability criteria.

### 7.5 Scope Boundaries

Target Planner is not:

- a model quality predictor
- a free-floating "best model" selector
- a system with `min_quality` or hidden quality scores
- a balanced objective with opaque weights
- a web dashboard in the MVP
- a Colony portfolio optimizer
- a broad heterogeneous fleet manager

Future target kinds such as VPC endpoints, Vast GPUs, edge NPUs, and other device classes are extension paths, not MVP claims.

---

## 8. Cross-Cutting Product Principles

### 8.1 Local First

The default experience should run locally without API keys. Optional integrations can exist, but they must not be required for the core demos or tests.

### 8.2 Deterministic Proofs

The repo should prefer seeded fixtures, reproducible runs, and measured before/after comparisons. Whenever a result is claimed, the path to reproduce it should be visible.

### 8.3 Verdicts Over Dumps

Where a surface supports a decision, it should lead with the decision:

- readiness report leads with ship / do-not-ship
- Colony leads with measured completion delta
- Planner trace leads with why the request ran where it did
- Context audit leads with what information was used and credited
- DataFlow graph audit should lead with what typed data products flowed into the final result
- LangSmith export should preserve DurableFlow's local verdicts and traces rather than becoming the primary decision surface

Metric tables and raw traces are supporting evidence, not the primary experience.

### 8.4 Explicit Boundaries

Each extension must state what it does not prove. This is central to the product's credibility. The docs repeatedly reject overclaiming: no quality oracle, no production scheduler, no inferred influence, no fake crash recovery, no hardcoded scores, no implied live eviction when a termination is induced.

### 8.5 Additive Extensions

Extensions should remain optional and additive. DurableFlow core should continue to work if an extension is unused. New persistence, reports, and demos should not require changes to the core workflow behavior unless explicitly justified.

### 8.6 Optional Observability Export

DurableFlow should keep local telemetry and SQLite ledgers as the source of truth. Production observability integrations can be useful, but they must preserve the local-first boundary.

The LangSmith adapter proposal is the current preview of this pattern. It would export `TelemetryLogger` events and selected `ContextLedger` records into LangSmith for trace inspection, dataset creation, and evaluation workflows. LangSmith would remain an external observer:

- no replacement of `WorkflowStore`, `ContextLedger`, approval state, or side-effect logs
- disabled by default
- optional dependency only
- lazy import from user setup or CLI paths
- non-blocking export through a bounded queue
- digest-only redaction by default
- best-effort failure semantics, with local workflow execution never waiting on LangSmith

This preview fits the production recommendation to use LangSmith for observation and evals while keeping DurableFlow focused on local execution, checkpointing, gates, idempotency, and audit records.

---

## 9. Combined User Journeys

### 9.1 Backend Engineer Learning the Core

The engineer runs the crash recovery demo, inspects how a workflow resumes, sees approval pause/resume behavior, and verifies that side effects are not duplicated. The outcome is understanding the operational primitives beneath an assistant workflow.

### 9.2 Infrastructure Evaluator Reviewing Colony

The evaluator runs the chaos benchmark and compares naive versus durable completion under the same seed. The outcome is a measured view of whether durable execution improves completion on spot-like compute.

### 9.3 FDE Evaluating an Agent

The FDE runs the readiness demo and sees the naked agent fail safety while the wrapped agent survives the six failure scenarios. The outcome is a defensible ship / do-not-ship decision and a clear statement of what the durability layer contributes.

### 9.4 Knowledge Architect Auditing Context Use

The reviewer runs inbox triage with the context ledger and opens the audit trace. The outcome is a plain-language knowledge trail showing observed, retrieved, selected, rejected, consumed, influential, and non-influential artifacts.

### 9.5 Platform Engineer Controlling Model Spend

The engineer sends a request with `"model": "auto"` and a cost or privacy constraint. The outcome is a plan trace showing why the system chose local execution, when it escalated, or why the request was infeasible.

### 9.6 Workflow Designer Previewing DataFlow

The designer sketches inbox triage as a typed data DAG, attaches existing computation to each node, and inspects the planned graph before execution. The intended outcome is a design-time and runtime view of data products such as `IncomingEmail`, `SelectedContextSet`, `TriageDecision`, and `SentReplyReceipt`.

### 9.7 Platform Team Previewing LangSmith Export

The platform team keeps DurableFlow's SQLite store and local audit views as the source of truth, then optionally exports redacted telemetry and context lineage into LangSmith. The intended outcome is production trace inspection and dataset evaluation without making LangSmith required for local demos or workflow correctness.

---

## 10. Product Risks

| Risk | Why it matters | Product mitigation |
|------|----------------|--------------------|
| Scope reads as too broad | The repo spans workflows, compute, readiness, context, and routing | Keep each extension independently scoped and demoable |
| Artifact looks like toy code | Minimal implementation may be mistaken for low ambition | Lead with measured operational claims and clear methodology |
| Benchmark credibility gap | Mock results can be dismissed | Label mock/live clearly, include threats to validity, preserve live smoke paths where practical |
| Report becomes metric dump | Decision-makers may not extract the outcome | Use builder/view contracts and verdict-first surfaces |
| Overclaiming damages trust | Claims like quality prediction or production safety are hard to defend | Maintain explicit vocabulary guards and "what this is not" sections |
| Optional dependencies leak into demos | Reviewers may fail to run the repo | Keep default demos zero-key and zero-optional-dependency |
| Extension coupling breaks core | Additions could make the core harder to understand | Require additive behavior and core regression checks |
| Preview tracks read as shipped features | DataFlow and LangSmith adapter are proposal-stage surfaces | Label them as previews and keep implementation claims separate from product direction |

---

## 11. Suggested Product Priorities

If the goal is assessing total scope and deciding what to emphasize, the product hierarchy should be:

1. **Preserve DurableFlow core as the simple, inspectable foundation.** If the core becomes hard to understand, the extensions lose credibility.
2. **Lead public positioning with Agent Readiness or Colony depending on audience.** Readiness is strongest for enterprise agent deployment; Colony is strongest for infrastructure and compute reliability audiences.
3. **Use Context as the auditability bridge.** It deepens the enterprise story without claiming full governance.
4. **Keep Target Planner clearly draft until its value benchmark is implemented.** The planner has large product potential, but it needs measurable cost/value proof to avoid sounding like generic model routing.
5. **Use DataFlow as the next design-surface preview, not as a shipped claim.** It connects the context story to typed workflow data products.
6. **Use the LangSmith adapter as the production observability bridge.** It should export DurableFlow evidence without moving the source of truth out of DurableFlow.
7. **Avoid bundling all extensions as one required system.** The suite should be modular: core plus one extension should make sense.

---

## 12. MVP Boundaries by Area

| Area | MVP must keep | Can defer |
|------|---------------|-----------|
| Core | checkpoint/resume, approval, idempotency, fallback, cost, context selection, telemetry | production-grade scaling and hosted UI |
| Colony | durable vs naive benchmark, identical chaos schedule, cost accounting, deterministic mock, methodology | animated scoreboard, broad live matrix, predictive failure work |
| Readiness | turn checkpointing, gated writes, six failure modes, before/after verdict report | real ADK Runner, remote MCP, authorization policy |
| Context | artifact ledger, retrieved/selected/rejected/consumed events, decision lineage, assembly metadata, audit CLI, privacy-safe defaults | trust policy, supersession, replay, compaction, OpenLineage export |
| Planner | constraints, local-first plan, budget ledger, verifiable escalation, plan trace, value benchmark | web dashboard, balanced objective, ML capability backend, Colony portfolio optimization |
| DataFlow preview | typed data specs, step contracts, data artifacts, dependency edges, graph audit | visual workflow builder, full OpenLineage implementation, broad data platform |
| LangSmith adapter preview | optional telemetry sink, context export hook, deterministic run mapping, digest-only export | making LangSmith a state store, required tracing, raw payload export by default |

---

## 13. Overall Scope Assessment

DurableFlow's total product scope is coherent if treated as an operational-lab portfolio:

- **Core** proves survivable workflow execution.
- **Colony** proves durability against unreliable compute.
- **Readiness** proves deployability improvement for agents.
- **Context** proves auditability of information use.
- **Planner** aims to prove governed target selection and spend control.
- **DataFlow** previews typed data transformation graphs for agentic workflows.
- **LangSmith adapter** previews optional production telemetry and evaluation export.

The common theme is not "build an agent platform." It is "make agentic work inspectable, resumable, governable, and measurable."

The main product management challenge is focus. Each extension is credible as a standalone artifact, but together they can appear like several products. The repo should therefore present DurableFlow as a foundation with optional proof tracks, each answering one concrete operational question and avoiding claims beyond its evidence.
