# DurableFlow Agent Readiness Pack

The Agent Readiness Pack is the DurableFlow extension track for answering one production question:

> Can this agent be shipped near customer systems without causing an incident?

Current status: **spec/design track**. The repo contains the full spec at [docs/dflow-readiness-spec.md](docs/dflow-readiness-spec.md). The package implementation, readiness demo, MCP server, and ADK adapter described by the spec are not present yet.

## Scope

The planned extension turns a fragile prototype agent into a measured deployment candidate by adding:

- an agent runner that checkpoints every reason-act-observe turn
- tool interception that lets read tools execute but routes write tools through approval
- idempotency for every external write
- a failure harness for six production failure modes
- a before/after readiness report comparing a naked agent with a DurableFlow-wrapped agent
- an optional MCP path for gated writes against mock legacy CRM/ticketing infrastructure
- an optional Google ADK adapter behind the same runner protocol

## Failure Modes

The readiness harness is designed around six concrete production risks:

| Failure mode | Wrapped behavior required |
|--------------|---------------------------|
| Tool timeout | Abort the tool call, return a structured observation, and continue cleanly. |
| Malformed tool output | Convert parse failure into a structured tool error instead of crashing. |
| Prompt injection | Gate unsafe writes before they reach customer systems. |
| Context overflow | Keep context under budget and halt at max turns with a clean state. |
| Model fallback | Route through the fallback provider and record the event. |
| Crash after side effect | Use the side-effect log to prevent duplicate writes on resume. |

## Readiness Report Contract

The report is a decision-support artifact, not a metric dump. It must lead with:

1. deployment verdict: ship or do not ship
2. durability delta: what wrapping the agent changed
3. primary blocker: the single unsafe behavior that prevents deployment, when present
4. metric detail: reliability, safety, cost, and observability breakdowns

The spec requires the verdict to derive from measured scenario results, never hardcoded scores.

## Planned Layout

The spec defines these additive packages and demos:

```text
agent/
  protocol.py
  runner.py
  mini_react.py
  tools.py
  mcp_client.py
  adk_adapter.py
readiness/
  harness.py
  scoring.py
  view.py
  vocabulary.py
  render.py
mcp_server/
  legacy_crm.py
examples/
  readiness_demo.py
  mcp_demo.py
docs/
  field-pattern.md
```

## Build Contract

The non-negotiable implementation claim is: no external account, API key, optional package, or network call is required for the headline readiness demo. Optional `[mcp]` and `[adk]` paths may prove protocol and framework integration, but the core readiness report must run with the standard library plus DurableFlow.

Read the full spec: [docs/dflow-readiness-spec.md](docs/dflow-readiness-spec.md).
