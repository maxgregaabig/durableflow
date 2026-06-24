# Specification: DurableFlow Context Measurement Discipline

**Status:** Draft  
**Author:** Marcos Polanco  
**Created:** 2026-06-24  
**Methodology precedent:** MQUP retrieval evaluation harness and failure-and-fix loop  
**Applies to:** `context/context-spec.md`, `docs/context-extension.md`, `src/context_selector.py`, inbox triage context-selection path  
**Implementation policy:** Methodology and future requirements only. This document does not order runtime changes, selector replacement, or a benchmark build until explicitly accepted as implementation work.

---

## 1. Purpose

DurableFlow Context already records what information was observed, retrieved, selected, consumed, and credited as influential. The next gap is measurement discipline: the project should be able to say whether context selection is getting better, worse, faster, or merely more complicated.

MQUP's reusable learning is not the Maps UI or iOS integration. The transferable artifact is the evaluation posture:

- define a user-visible relevance target before tuning
- compare against a simple baseline
- freeze labels before optimization
- track ranked-retrieval metrics, not just pass/fail fixtures
- measure p95 latency in the same harness that measures quality
- keep a failure-and-fix log with before/after metrics
- state caveats plainly when labels, corpora, or latency environments are synthetic

For DurableFlow Context, this becomes a context-selection measurement methodology first and a harness requirement only when implementation is approved. It should measure whether selected artifacts are useful, budget-respecting, and auditable, not whether a vector search demo looks plausible.

---

## 2. Implementation Stance

This spec is a methodology statement and requirements draft, not a build order.

Immediate use:

- guide future design discussions about context-selection quality
- prevent overclaiming when describing DurableFlow Context
- define what evidence would be needed before citing retrieval-quality numbers
- clarify which MQUP techniques transfer directly and which remain deferred

Deferred implementation:

- a fixture benchmark runner
- generated metric reports
- CI regression thresholds
- candidate selector experiments beyond the current lexical baseline

The first implementation, if accepted, should be a measurement-only harness around the existing selector. It should establish baseline nDCG@5, Recall@10, budget metrics, audit coverage, and p95 latency before setting pass/fail targets. Dev/holdout split discipline becomes required only when a change introduces tunable parameters, such as semantic blend weight, BM25 normalization choices, structured-signal weights, or thresholded hard/soft constraints.

---

## 3. Transferred Learnings From MQUP

| MQUP practice | DurableFlow Context transfer |
|---------------|------------------------------|
| BM25-only baseline | Keep current `ContextSelector` BM25/TF-IDF selector as the honest baseline. |
| Hybrid BM25 + semantic ranking | Introduce an optional future candidate ranker that blends lexical score with semantic or structured signals. |
| nDCG@5 | Measure whether the most important context artifacts appear near the top of the selected/mounted context. |
| Recall@10 | Measure whether the selector retrieves the known-relevant artifacts somewhere in the candidate set before budget packing removes them. |
| p95 latency | Measure selector latency under corpus sizes and budgets representative of workflow use. |
| Dev split and blind hold-out | Required when tuning weights, thresholds, or ranking policy; deferred for a baseline-only measurement run. |
| Frozen labels independent of hybrid output | Relevance labels must come from fixtures, human labels, or deterministic task contracts, never from the ranker being evaluated. |
| Failure-and-fix notes | Every ranking fix should record query/task, wrong selection, diagnosis, fix, metric delta, and regression check. |
| Caveat discipline | Synthetic corpora, deterministic labels, and local-machine latency must be named as such. |

---

## 4. Measurement Goal

The context selector should be evaluated against this user-visible question:

> Did the workflow mount the information a reviewer would expect the model to use for this decision, within budget, quickly enough, and with lineage that explains the selection?

This is deliberately different from "did the workflow complete?" Durable execution remains necessary, but the measurement target here is information quality.

---

## 5. Evaluation Objects

### 5.1 Context Eval Case

Each eval case should represent one workflow step that needs context.

```text
ContextEvalCase
  case_id: stable id
  workflow_type: e.g. inbox_triage
  step_name: e.g. select_context or triage_llm
  query: task text used for retrieval
  corpus: candidate ContextItem rows or source fixture refs
  token_budget: hard budget
  relevant_artifact_ids: graded or binary relevance labels
  must_include_artifact_ids: optional hard expectation for explicitly referenced or policy-required context
  metadata: scenario tags, corpus size, timestamp policy, fixture source
```

### 5.2 Relevance Labels

Labels should be frozen before tuning. Acceptable label sources:

- deterministic fixture contracts, such as "prior email from the same thread is relevant"
- human review labels for real or anonymized corpora
- task-derived labels, such as calendar event explicitly referenced by the incoming email
- synthetic benchmark labels when they are generated independently of the ranker output

Operational label examples for inbox triage:

| Scenario | Relevant means | Must-include when |
|----------|----------------|-------------------|
| Same-thread follow-up | Prior email with the same `thread_id` or explicit reply chain needed to interpret the incoming request. | The incoming email says "following up", "as discussed", "same thread", or omits the prior commitment. |
| Calendar conflict | Calendar event overlapping a requested meeting time, deadline, or availability window. | The incoming email asks to schedule, reschedule, confirm availability, or references a specific date/time. |
| Prior commitment | Earlier email or decision record where the workflow/user promised an action, date, price, intro, or deliverable. | The incoming email asks for status on that commitment or depends on not contradicting it. |
| Policy-bound action | Policy snippet or operating rule governing whether the workflow may send, approve, disclose, or escalate. | The step can trigger an external side effect or sensitive disclosure covered by that policy. |
| Customer/account context | CRM note, support ticket, or prior decision tied to the same customer/account and issue. | The incoming email references an account-specific exception, escalation, renewal, or unresolved issue. |

Operational label examples for non-email sources:

- A calendar event inside the requested time window is relevant; an event on a different day with shared keywords is not.
- A policy snippet matching the action category is relevant; a generic policy document with only token overlap is background at most.
- A previous workflow decision is relevant when it involves the same entity and unresolved commitment; it is not relevant merely because it shares a broad topic.

Unacceptable label sources:

- "whatever the hybrid ranker returned"
- labels regenerated after each tuning run
- free-text model explanations converted into relevance without explicit attribution

### 5.3 Relevance Grades

Binary labels are enough for v0.1 measurement. Graded labels become useful when distinguishing indispensable context from merely helpful context.

```text
3 = decisive: required to justify the decision
2 = useful: materially helps the decision
1 = background: relevant but not necessary
0 = irrelevant
```

nDCG should use grades when present and binary relevance otherwise.

---

## 6. Metrics

### 6.1 Ranked-Retrieval Quality

| Metric | Definition | Why it matters |
|--------|------------|----------------|
| `nDCG@5` | Ranking quality for the top five retrieved or mounted artifacts. | The model and reviewer mostly see the top of context first. |
| `Recall@10` | Fraction of labeled relevant artifacts found in the top ten candidates. | Detects whether the selector can find the right sources before budget packing. |
| `MustInclude@K` | Whether explicitly referenced or policy-required artifacts appear within top K or mounted context. | Captures context that would make the workflow unsafe or incoherent if omitted. |
| `SelectedRelevantRate` | Relevant selected artifacts divided by selected artifacts. | Measures budget waste. |
| `BudgetUtilization` | Selected token count divided by token budget. | Detects underfilled or overstuffed context assembly. |
| `RejectionFalseNegativeRate` | Relevant artifacts rejected due to budget or low rank divided by relevant artifacts. | Shows whether packing strategy loses important sources. |

`MustInclude@K` should be used only when the case defines concrete criteria. Recommended K values:

- `MustInclude@10` for 30-case fixture benchmark
- `MustInclude@5` for expanded 150-case benchmark

Initial criteria:

- explicitly referenced artifact: a prior email, event, account, decision, or policy is named or unambiguously referred to in the task
- policy-required artifact: a workflow step needs a policy source before taking or drafting a sensitive external action
- contradiction-risk artifact: a prior commitment or decision would be contradicted if omitted

Baseline measurement fields:

```text
nDCG@5: measured, no initial pass/fail target
Recall@10: measured, no initial pass/fail target
MustInclude@10: measured only for cases with must-include labels
p95 selector latency: measured, no initial pass/fail target
```

Candidate selector targets should be set only after baseline numbers exist. A reasonable future gate for a proposed hybrid or weighted reranker is:

```text
nDCG@5 delta over lexical baseline: >= +0.10
Recall@10: no regression unless nDCG gain is explicitly worth the recall tradeoff
MustInclude@10: no regression on must-include cases
p95 selector latency: no worse than an agreed budget derived from baseline measurement
```

These are not product claims. They should be revised once real corpora and human labels exist.

### 6.2 Latency

Measure latency in the same run as quality metrics.

```text
selector_latency_ms:
  start: immediately before retrieval/scoring
  end: after budget packing and lineage-ready selection output
reported:
  median
  p95
  max
```

No fixed p95 target is asserted in this spec. The first harness should measure the current selector, record corpus size and machine/runtime details, and then set a target from observed baseline plus product expectations. MQUP's caveat transfers directly: local release-harness numbers are not device, server, or production numbers.

### 6.3 Audit Completeness

DurableFlow Context has a measurement dimension MQUP did not need: lineage coverage.

| Metric | Definition |
|--------|------------|
| `RetrievedEventCoverage` | Retrieved candidates with ledger `retrieved` events / retrieved candidates. |
| `SelectedEventCoverage` | Selected artifacts with ledger `selected` events / selected artifacts. |
| `ConsumedEventCoverage` | Mounted artifacts with ledger `consumed` events / mounted artifacts. |
| `InfluenceCoverage` | Explicitly credited influential artifacts / decision's expected influential artifacts. |

The selection can be accurate and still fail the DurableFlow Context promise if it cannot be audited.

---

## 7. Baselines And Candidate Techniques

### 7.1 Baseline

The baseline should remain the current standard-library lexical selector:

```text
query terms -> term-frequency / inverse-document-frequency score -> rank -> greedy token-budget packing
```

This baseline is valuable because it is inspectable. Any proposed technique must beat it on measured quality without destroying latency, determinism, or auditability.

### 7.2 Candidate Technique: BM25-Style Lexical Ranking

MQUP used SQLite FTS5 BM25. DurableFlow currently uses a small in-memory TF-IDF-like score. A future selector may adopt BM25-style normalization if document length starts biasing ranking.

Measurement question:

> Does BM25-style length normalization improve nDCG@5 or Recall@10 over the current selector on context corpora with long emails, short calendar events, and mixed tool outputs?

Acceptance:

- report delta against current selector
- include failure cases where length normalization helps or hurts
- preserve deterministic behavior and standard-library fallback if SQLite FTS is unavailable
- use a development split only if normalization parameters or thresholds are tuned

### 7.3 Candidate Technique: Semantic Reranking

MQUP's hybrid ranker blended lexical and semantic scores. DurableFlow Context may eventually need this for paraphrase-heavy enterprise context, such as:

- "reschedule" matching calendar conflicts and availability notes
- "approval risk" matching prior rejection threads
- "customer escalation" matching support tickets without exact token overlap

Measurement question:

> Does semantic reranking improve top-of-context relevance on paraphrase and concept-match cases without hiding why an artifact was selected?

Acceptance:

- tune blend weights only on a development split
- report hold-out metrics separately
- record both lexical and semantic score metadata if used
- keep audit language user-facing; do not expose raw vector scores as the primary explanation

### 7.4 Candidate Technique: Structured Signal Reranking

DurableFlow has workflow-specific structure that MQUP did not: thread ids, timestamps, source types, step names, and explicit decision lineage.

Useful structured signals:

- same email thread
- direct sender/recipient match
- calendar event inside requested time window
- source type priority for the step
- recency with bounded decay
- prior artifact explicitly credited in a similar decision

Measurement question:

> Do structured signals improve relevance while preserving the reviewer-visible reason for selection?

Acceptance:

- define the tuned parameters, such as source-type weights, recency decay, or same-thread boost
- tune those parameters on a development split and report untouched hold-out metrics when weights are tuned
- structured boosts must appear in selection metadata or audit view
- hard vs soft rules must be explicit
- no hidden promotion of stale or untrusted sources once trust/freshness policy exists

### 7.5 Candidate Technique: Hard And Soft Constraints

MQUP separated hard constraints from soft demotions. DurableFlow Context should use the same discipline.

Possible hard constraints:

- artifact belongs to the workflow tenant or allowed source boundary
- artifact is not blocked by trust/freshness policy
- artifact is compatible with the workflow step's privacy policy
- artifact fits within an absolute token ceiling

Possible soft constraints:

- source recency
- same thread
- same counterparty
- useful but non-required source type
- lower-confidence semantic match

Hard constraints should be rare and auditable. Soft constraints should affect rank but not silently erase useful context.

---

## 8. Benchmark Shape

### 8.1 Initial Fixture Benchmark

Start with a small deterministic benchmark built from existing inbox and calendar fixtures.

Recommended first cut:

```text
cases: 30
corpus size per case: current fixture corpus
scenario tags:
  same_thread
  calendar_conflict
  prior_commitment
  stale_prior_email
  irrelevant_keyword_overlap
  paraphrase_required
  budget_pressure
  empty_or_low_context
```

Example case shapes:

| Case type | Query/task shape | Positive labels | Negative controls |
|-----------|------------------|-----------------|-------------------|
| Same-thread follow-up | "Can you send the deck we discussed?" | prior email in same thread containing the deck commitment | unrelated email mentioning "deck" |
| Calendar conflict | "Can we meet Tuesday at 2?" | event overlapping Tuesday 2pm | event with same attendee on another day |
| Prior commitment | "Checking on the intro you promised" | prior email or decision with the intro commitment | generic networking email |
| Stale prior email | "Use latest pricing" | newer pricing artifact | older pricing artifact with stronger token overlap |
| Irrelevant keyword overlap | "board approval for budget" | approval-policy or board-context source | lunch email containing "board" and "budget" |
| Paraphrase required | "Can we push this?" | rescheduling or deadline-extension artifact | email containing only the word "push" |
| Budget pressure | long corpus with multiple relevant items | decisive short item plus useful background | long low-value item with high token overlap |
| Empty or low context | task with no matching prior source | no relevant artifacts | any selected source should be treated as low confidence |

This is not enough for a public claim, but it is enough to prevent regressions and validate the harness.

### 8.2 Expanded Benchmark

The MQUP outcome cites a 2,000-item benchmark. DurableFlow Context can transfer that scale target without copying the domain.

Recommended expanded benchmark:

```text
corpus: 2,000 mixed context artifacts
sources:
  prior emails
  calendar events
  CRM notes
  previous workflow decisions
  tool outputs
  policy snippets
cases:
  150 labeled eval cases
split:
  baseline-only run: no split required
  tuned selector run: 120 development/tuning cases, 30 blind hold-out cases
```

The 2,000-item scale is useful because it is large enough to expose ranking and latency issues while still small enough for brute-force and inspectable local evaluation.

### 8.3 Benchmark Report

Each run should emit a report with:

```text
selector_name
baseline_name
case_count
corpus_size
token_budget
nDCG@5
Recall@10
MustInclude@10
SelectedRelevantRate
BudgetUtilization
RejectionFalseNegativeRate
p95_latency_ms
holdout metrics when applicable
known caveats
```

---

## 9. Failure-And-Fix Protocol

Every retrieval-quality change should add a failure-and-fix note.

Required format:

```text
## N. Short failure name

Task/query:
Wrong selection:
Diagnosis:
Fix:
Metrics:
Regression check:
Caveat:
```

Example DurableFlow failures worth capturing:

- same-thread prior email ranked below generic keyword overlap
- calendar conflict omitted because event text did not share query tokens
- long irrelevant email consumed too much budget
- relevant artifact retrieved but rejected due to greedy packing order
- stale prior decision selected without freshness warning
- semantic match improved recall but made audit explanation weaker

The important habit is not just recording a fix. It is recording what got better, what might have regressed, and whether the evidence is synthetic, fixture-based, or human-labeled.

---

## 10. Acceptance Gates For A Future Implementation

These gates apply only after the project chooses to build the measurement harness. A baseline-only harness should be considered accepted when:

- it can evaluate the current selector against frozen labels
- it reports nDCG@5, Recall@10, p95 latency, and budget metrics
- it reports audit-completeness metrics for context-ledger integration cases
- it writes a human-readable report suitable for `docs/`
- it names benchmark caveats in the report
- it does not require network services for the default benchmark
- it keeps raw sensitive content out of persisted metric artifacts by default

A candidate-selector harness adds these acceptance gates:

- it compares at least one candidate selector against the BM25/TF-IDF baseline
- it identifies which parameters, thresholds, or weights were tuned
- it separates development and hold-out cases when tuning exists
- it fails CI on material regression thresholds after thresholds are set from baseline data

---

## 11. Non-Goals

This spec does not require:

- replacing the current context selector
- adding embeddings or vector databases
- claiming production retrieval quality from synthetic fixtures
- tracing every token or model span
- inferring influence from free text
- making latency claims beyond the measured environment

---

## 12. Open Questions

- Should relevance labels be binary for the first implementation, or should decisive/useful/background grades be introduced immediately?
- Should `Recall@10` measure retrieved candidates before token packing, mounted context after packing, or both?
- Should latency include ledger event preparation, or only selector scoring and packing?
- What is the first non-email source type worth adding to the benchmark: CRM notes, policy snippets, or previous workflow decisions?
- How should future trust/freshness policy interact with hard retrieval constraints?
