# Pi / Coding-Agent Adapter Design

`factory/` should treat Pi as one possible coding-agent backend, not as the
factory itself. The factory owns the workflow definition: today that is
`CLEAR.md`; later it may be any equivalent spec-driven workflow. A coding agent
is only the executor for bounded implementation laps inside that workflow.

## Boundary

The factory is responsible for:

- selecting the active workflow and phase
- mounting approved context and artifacts
- enforcing workspace boundaries
- checkpointing each lap
- gating plans and releases
- running independent verification
- recording evidence, lineage, telemetry, and audit output
- deciding whether to remediate, advance, block, or ship

The coding agent is responsible for:

- reading the phase brief and mounted artifacts
- editing only the assigned workspace
- reporting changed files and a concise implementation summary
- producing structured claims for the verifier to test
- stopping when the assigned lap budget or scope is reached

This keeps the agent as a replaceable builder. The factory remains the
orchestrator, ledger, policy engine, and release gate.

## Adapter Pattern

The factory should expose a small adapter interface rather than hard-coding Pi:

```python
class CodingAgentAdapter:
    agent_id: str

    def implement_phase(self, request: ImplementPhaseRequest) -> ImplementPhaseResult:
        ...
```

`ImplementPhaseRequest` should include:

- `workflow_id`
- `phase_number`
- `attempt`
- `workspace_root`
- `phase_brief`
- mounted artifact references
- allowed paths
- denied paths
- test command
- time, token, and cost budgets
- required output schema

`ImplementPhaseResult` should include:

- `agent_id`
- `transcript_ref`
- `files_changed`
- `summary`
- `claims`
- `tool_errors`
- `budget_used`

Possible adapters:

- `DeterministicAgentAdapter`: current hermetic implementation for tests and
  offline demos.
- `PiAgentAdapter`: invokes Pi through print/JSON, RPC, or SDK mode.
- `CodexAgentAdapter`, `ClaudeCodeAgentAdapter`, `OpenHandsAgentAdapter`, etc.:
  same factory contract, different execution harness.

The adapter may be implemented as a direct Python class, a plugin entry point,
or an external process contract. The important point is that all adapters return
the same structured result and are subject to the same factory policies.

## Pi Integration Shape

Pi is a good candidate backend because it is a coding-agent harness with
project instructions, skills, model/provider configuration, shell tools, and
machine-readable modes. The clean integration is:

```text
phase_runner
  -> build ImplementPhaseRequest
  -> invoke Pi adapter in isolated workspace
  -> store transcript and changed-file manifest
  -> run independent verifier
  -> record evidence and lineage
  -> remediate, retry, advance, or block
```

Pi should receive a narrow task:

```text
Implement phase 2 of workflow <id>.
Use only the mounted artifacts listed below.
Edit only paths under <workspace_root>.
Do not mark work complete; the factory verifier decides completion.
Return JSON matching the requested schema.
```

Pi should not decide whether the phase passed, whether claims are verified, or
whether the workflow can ship. Those decisions stay inside the factory.

## Required Policies

### Workspace Isolation

The adapter must run against the generated workspace, not the DurableFlow source
tree, unless an operator explicitly grants a broader scope. Allowed and denied
paths should be passed in the request and checked again by the factory after the
agent returns.

### Structured Output

Agent output must be structured and parseable. Free-form summaries are useful
for operators, but the factory should rely on typed fields for files changed,
claims made, commands suggested, errors encountered, and budget usage.

### Independent Verification

No agent claim is trusted by default. The verifier must be a separate identity
from the implementer and must derive verdicts from test output, static checks,
or other ranked evidence. The adapter can propose claims; it cannot verify
them.

### Deterministic Default

The deterministic adapter should remain the default for CI, documentation
examples, and hermetic demos. Real coding-agent adapters should be opt-in:

```python
ClearConfig(agent_backend="deterministic")
ClearConfig(agent_backend="pi")
```

### Transcript Retention

The factory should store a transcript reference, changed-file manifest, command
log, and adapter metadata for each lap. Raw transcripts may be external files;
the durable state should contain stable references and digests.

### Budget Control

Each lap should have explicit limits for wall time, tokens, model spend, command
count, and retry count. If the adapter exceeds a limit, the factory records the
lap as blocked or failed and decides the next action.

### Approval Boundaries

Plan approval and release approval are factory gates. A coding agent may draft
or revise plans, but it must not bypass operator gates or convert a rejected
plan into a shipped result.

### Policy-Neutral Workflow

`CLEAR.md` is the current workflow definition, not a hard dependency of the
adapter layer. The same adapter contract should support future workflows with
different phase names, artifacts, gates, and verification policies.

## Minimal First Slice

The first non-deterministic slice should be intentionally small:

1. Add `CodingAgentAdapter` and request/result dataclasses.
2. Wrap the existing deterministic runner behind that interface.
3. Add a `PiAgentAdapter` that invokes Pi in machine-readable mode.
4. Store transcript refs and file manifests in the existing phase state.
5. Keep verifier behavior unchanged.
6. Add tests proving that the factory blocks out-of-workspace edits and ignores
   unverified agent claims.

That proves the architecture without making Pi a hidden dependency of the
factory package.

