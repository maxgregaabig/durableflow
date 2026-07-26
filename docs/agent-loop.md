# Agentic Loop

Visual reference for the reason-act-observe loop in `agent/`, bridged into the durable `WorkflowEngine`.

**Related:** [dflow-arch.md](dflow-arch.md) · [field-pattern.md](field-pattern.md) · [walkthrough.md](walkthrough.md) (Agent Readiness section) · [readiness/README.md](../readiness/README.md)

**Source file:** [agent-loop.mmd](agent-loop.mmd) (standalone Mermaid for editors and CLI)

## Where the code lives

| Piece | Module | Role |
|-------|--------|------|
| Turn contract | `agent/protocol.py` | `AgentStep.step()` → `AgentTurn` |
| Durable bridge | `agent/runner.py` | `AgentRunner` registers one engine step per turn |
| Demo agent | `agent/mini_react.py` | Deterministic ReAct `AgentStep` for readiness tests |
| Tools | `agent/tools.py` | `ToolSpec` handlers (read vs write) |
| Harness | `readiness/harness.py` | Naked vs wrapped comparison |

## Diagram choice

Use two complementary views:

1. **Flowchart (primary)** — shows how one turn maps onto `WorkflowEngine`, and where branching happens (terminal, read tool, write + approval, checkpoint). Best for understanding the durable shell.
2. **Sequence diagram (secondary)** — shows temporal message flow across `AgentStep`, `AgentRunner`, tools, and `ApprovalGate` for a single turn.

## Durable bridge (flowchart)

`AgentRunner` does not run a free-form `while` loop in memory. It pre-registers `agent_turn_0` … `agent_turn_{max_turns-1}` as linear workflow steps. Each step runs exactly one reason-act-observe cycle and checkpoints `agent_history` before the next turn can start. Resume after crash reconstructs history from `step_data` and continues at `current_step + 1`.

```mermaid
flowchart TD
    subgraph register ["Registration (AgentRunner.register)"]
        R1["Register agent_turn_0 … agent_turn_{max_turns-1}"]
        R2["Each turn = one WorkflowEngine step"]
        R1 --> R2
    end

    subgraph turn ["One turn (agent_turn_N)"]
        T0{"Last history entry<br/>is_terminal?"}
        T0 -->|yes| T_SKIP["Skip turn<br/>(already finished)"]
        T0 -->|no| T1["Build prompt from<br/>history + context"]
        T1 --> T2{"Tokens > budget?"}
        T2 -->|yes| T3["ContextSelector trims prompt"]
        T2 -->|no| T4["ModelRouter.route()"]
        T3 --> T4
        T4 --> T5["REASON: AgentStep.step()<br/>→ AgentTurn"]
        T5 --> T6{"is_terminal?"}
        T6 -->|yes| T7["OBSERVE: append turn<br/>checkpoint StepResult"]
        T6 -->|no| T8{"tool known?"}
        T8 -->|no| T9["OBSERVE: unknown_tool error<br/>checkpoint"]
        T8 -->|yes| T10{"tool.is_write?"}
        T10 -->|no| T11["ACT: execute read tool<br/>(timeout + JSON guard)"]
        T11 --> T12["OBSERVE: append observation<br/>checkpoint StepResult"]
        T10 -->|yes| T13["ACT: request_approval()<br/>PauseForApproval"]
    end

    subgraph resume ["Resume after approval"]
        A1["Operator approve / reject"]
        A2["commit handler on resume"]
        A3["Idempotency key → side_effect_log"]
        A4["Execute write once"]
        A5["OBSERVE: append approved turn<br/>checkpoint StepResult"]
        A1 --> A2 --> A3 --> A4 --> A5
    end

    subgraph persist ["Durable state"]
        P1[("step_data.agent_history")]
        P2[("step_results per turn")]
        P3[("approval_queue")]
        P4[("side_effect_log")]
    end

    R2 --> T0
    T13 --> P3
    T13 -.->|engine resume| A1
    T7 --> P1
    T9 --> P1
    T12 --> P1
    A5 --> P1
    T7 --> P2
    T9 --> P2
    T12 --> P2
    A5 --> P2
    A4 --> P4
```

## One turn (sequence)

```mermaid
sequenceDiagram
    participant Engine as WorkflowEngine
    participant Runner as AgentRunner
    participant Agent as AgentStep
    participant Router as ModelRouter
    participant Tool as Tool handler
    participant Gate as ApprovalGate
    participant Store as WorkflowStore

    Engine->>Runner: run agent_turn_N
    Runner->>Store: read agent_history from step_data
    Runner->>Router: route(prompt) [telemetry + fallback]
    Runner->>Agent: step(history, context)
    Agent-->>Runner: AgentTurn(thought, tool_name, …)

    alt terminal turn
        Runner->>Store: checkpoint history + final_answer
    else read tool
        Runner->>Tool: handler(args) [timeout bounded]
        Tool-->>Runner: observation
        Runner->>Store: checkpoint history + observation
    else write tool
        Runner->>Gate: request_approval(payload)
        Runner-->>Engine: PauseForApproval
        Note over Engine,Gate: workflow status = paused_approval
        Gate->>Gate: operator approve / reject
        Engine->>Runner: resume → commit handler
        Runner->>Store: idempotency check (side_effect_log)
        Runner->>Tool: handler(args) [once]
        Runner->>Store: log side effect + checkpoint history
    end
```

## Key invariants

1. **One turn, one checkpoint** — completed turns are never re-reasoned; resume continues at the next registered step index.
2. **History is the source of truth** — `step_data["agent_history"]` holds the full reason-act-observe trace.
3. **Writes pause; reads run** — `ToolSpec.is_write` routes through `ApprovalGate`; approved writes use idempotency keys in `side_effect_log`.
4. **Agent logic is pluggable** — any object implementing `AgentStep` (`mini_react`, ADK adapter, your own LLM loop) plugs into the same bridge.
