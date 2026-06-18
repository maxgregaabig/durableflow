# DurableFlow Agent Readiness Pack

The Agent Readiness Pack is the DurableFlow extension track for answering one production question:

> Can this agent be shipped near customer systems without causing an incident?

Current status: **implemented demo with optional protocol/framework boundaries**. The zero-dependency readiness demo, failure harness, scoring, view builder, Markdown/CLI renderers, MCP path, and ADK-compatible adapter boundary are present. The full spec remains at [docs/dflow-readiness-spec.md](docs/dflow-readiness-spec.md).

## Run It

```bash
python3 examples/readiness_demo.py
```

This writes:

- `readiness.json` -- domain comparison and raw scenario results
- `readiness_report.md` -- verdict-first Markdown report

The MCP path is also runnable:

```bash
python3 examples/mcp_demo.py
```

When `mcp==1.13.1` is installed, this uses the official MCP client/server protocol via FastMCP. Without the optional package, it falls back to a tiny stdio JSON protocol so the demo remains dependency-free.

## Scope

The extension turns a fragile prototype agent into a measured deployment candidate by adding:

- an agent runner that checkpoints every reason-act-observe turn
- tool interception that lets read tools execute but routes write tools through approval
- idempotency for every external write
- a failure harness for six production failure modes
- a before/after readiness report comparing a naked agent with a DurableFlow-wrapped agent
- an MCP path for gated writes against legacy CRM/ticketing-style infrastructure
- an optional ADK-compatible adapter boundary behind the same runner protocol

## Optional Boundaries

| Boundary | Current status |
|----------|----------------|
| MCP | Uses official `mcp==1.13.1` client/server protocol when installed; falls back to dependency-free stdio JSON for the local demo. |
| ADK | Verifies `google-adk==1.18.0` import, ADK `Agent` object construction, history conversion, and resume-safe adapter-boundary behavior with an ADK-compatible mock. Real Google ADK Runner end-to-end execution is not claimed yet. |

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

The report is a decision-support artifact, not a metric dump. It leads with:

1. deployment verdict: ship or do not ship
2. durability delta: what wrapping the agent changed
3. primary blocker: the single unsafe behavior that prevents deployment, when present
4. metric detail: reliability, safety, cost, and observability breakdowns

The verdict derives from measured scenario results, never hardcoded scores.

## Planned Layout

Implemented packages and demos:

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

The non-negotiable implementation claim is: no external account, API key, optional package, or network call is required for the headline readiness demo. Optional `[mcp]` proves the gated-write path across the official MCP protocol when installed. Optional `[adk]` currently proves package import, ADK object construction, history conversion, and resume-safe adapter-boundary behavior with an ADK-compatible mock. It does not yet claim a real Google ADK Runner end-to-end harness.

Read the full spec: [docs/dflow-readiness-spec.md](docs/dflow-readiness-spec.md).
