# DurableFlow Delta Conformance Inventory

**Status:** claim inventory and scope statement; it is not evidence that the
unbuilt Aegis HTTP Gateway or its conformance suite exists.
**Lens:** the Delta Framework, as scheduled in
[`drae-dflow-workplan.md`](../proposals/drae-dflow-workplan.md).
**Scope:** whole-repository claim sweep, including proposals, tests, examples,
and historical design notes.

```text
Primary delta(s): none owned by DurableFlow standalone
Mature mechanism used: checkpointed orchestration; durable human interruption; local mock replay suppression
Violated precondition: mutable external state and mute/ambiguous external APIs
Residual property owned here: workflow progress only; Aegis owns consequential action identity, authorization, dispatch, reconciliation, and receipts
Trusted assumptions: local/mock steps may safely replay; a gateway is not yet available
Evidence level: APP_ENFORCED only for local checkpoint/pause/replay mechanics; UNVERIFIED for consequential-effect completion until WS2
Explicit non-claims: D1 authorization, D2 mute-API reconciliation, D3 delegation, D5 provenance under injection, and general D4 migration
Falsified or made redundant if: a deployed heterogeneous authority already supplies action identity, mutable-precondition enforcement, ambiguity resolution, and receipts without Aegis
```

## Inventory method

The inventory is regenerated with this command; its patterns intentionally
overmatch ordinary implementation words so a new claim cannot hide behind a
different directory.

```sh
rg -n -i 'prevent|block|ensure|guarantee|secure|safe|authoriz|governed|unauthorized|injection' \
  --glob '!*.json' --glob '!*.lock' .
```

The command output is intentionally not a fixed count: this inventory itself
contains the vocabulary it audits. A disposition applies to **every match** in
each named file set below:

| Disposition | Meaning |
|---|---|
| **fix — closed** | Claim-shaped language was changed or bounded by an explicit non-claim in this revision. |
| **accurate** | The text describes a local mechanism, bounded test result, or non-consequential domain invariant and does not assert D1, D2, or D5. |
| **allowlisted** | Identifier/test-fixture vocabulary or an historical/proposal quotation; it is not public platform language and is not a claim of current enforcement. |

### Fix — closed

`README.md`, `durable-flow-overview.md`, `docs/dflow-arch.md`,
`docs/field-pattern.md`, `docs/learning-path.md`, `docs/walkthrough.md`,
`readiness/README.md`, `readiness/docs/dflow-readiness-spec.md`,
`readiness/vocabulary.py`, `proposals/README.md`,
`proposals/aws-deployment-proposal.md`, `proposals/dataflow-spec.md`,
`proposals/frontpressure-proposal.md`, and
`proposals/multiagent-proposal.md`.

These files now say, where relevant, that a gate pauses for review rather than
authorizes an act or defeats injection, that `side_effect_log` is local
mock-replay suppression rather than reconciliation, and that consequential
effect completion is target architecture until WS2 exits. The four constrained
or deferred proposals carry their constraint in their own header.

### Accurate

`agent/adk_adapter.py`, `agent/mcp_client.py`, `agent/runner.py`, `agent/tools.py`,
`colony/colony-spec.md`, `context/README.md`,
`context/context-measurement-spec.md`, `context/context-spec.md`,
`docs/delta-conformance.md`, `docs/dflow-spec.md`, `docs/eval-gate-spec.md`, `docs/exercises.md`,
`docs/langsmith-adapter.md`, `docs/opentelemetry-adapter-proposal.md`,
`docs/superpowers/plans/2025-01-31-assembly-lineage.md`,
`docs/superpowers/specs/2025-01-31-assembly-lineage-design.md`,
`evals/cli.py`, `evals/gate.py`, `evals/render.py`, `evals/scorers.py`,
`evals/view.py`, `factory/CLEAR.md`, `factory/README.md`,
`factory/__init__.py`, `factory/audit_view.py`, `factory/clear-spec.md`,
`factory/clear_workflow.py`, `factory/phase_state.py`, `factory/pi-dev.md`,
`factory/verification_ledger.py`, `factory/workspace.py`, `infra/README.md`,
`integrations/__init__.py`, `integrations/langsmith_adapter.py`,
`integrations/langsmith_eval_export.py`, `planner/planner-spec.md`,
`proposals/delta-abep-aegis-alignment-proposal.md`,
`proposals/drae-dflow-workplan.md`,
`proposals/experiment-replay-proposal.md`,
`proposals/lifecycle-evidence-proposal.md`,
`proposals/nanoq-control-plane-query-proposal.md`,
`proposals/nanoq-tool-integration-proposal.md`,
`proposals/trajectory-evals-proposal.md`, `proposals/vast-colony-proposal.md`,
`readiness/harness.py`, `readiness/render.py`, `readiness/scoring.py`,
`readiness/view.py`, `src/approval.py`, `src/model_router.py`, `src/store.py`, `src/telemetry.py`,
`usage.md`, and `verification/deferred-items.md`.

These matches concern local validation, read-only tooling, bounded evaluation,
or clearly scoped Aegis-target architecture. In particular, the two local
review gates in `factory/clear_workflow.py` are review of workspace artifacts,
not external effects.

### Allowlisted

`CLAUDE.md`, `CONTRIBUTING.md`, `Dockerfile`, `agent/mini_react.py`,
`competitive-differentiation-and-space-map.md`, `golden.md`, and all test
fixtures: `tests/test_adk_adapter.py`, `tests/test_agent_runner.py`,
`tests/test_clear_audit_view.py`, `tests/test_clear_context.py`,
`tests/test_clear_crash_subprocess.py`, `tests/test_clear_phase_runner.py`,
`tests/test_clear_planning.py`, `tests/test_clear_remediation.py`,
`tests/test_clear_state.py`, `tests/test_clear_verification.py`,
`tests/test_eval_cases.py`, `tests/test_eval_gate.py`,
`tests/test_eval_langsmith_export.py`, `tests/test_eval_report_view.py`,
`tests/test_langsmith_adapter.py`, and `tests/test_readiness.py`.

These are developer instructions, fixture phrases, assertions, or test names.
They remain searchable because removing an honest test description would hide
the demonstrated local behavior rather than narrow a platform claim.

## Ongoing review rule

Any new hit from the command above must be added to the appropriate
disposition before merge. A new consequential write path also requires an
entry in workplan §5.2.1; it may not add authorization, CAS, unknown-state, or
effect-ledger semantics to `src/`.
