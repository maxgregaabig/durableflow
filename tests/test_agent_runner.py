from __future__ import annotations

from pathlib import Path

from agent.mini_react import MiniReActAgent
from agent.runner import AgentRunner
from agent.tools import MockCRM, default_tools


def test_agent_runner_checkpoints_each_turn_and_gates_write(tmp_path: Path) -> None:
    crm = MockCRM.seeded()
    runner = AgentRunner(
        MiniReActAgent(),
        default_tools(crm),
        db_path=tmp_path / "agent.sqlite",
    )

    result = runner.run({"ticket_id": "T-100", "customer_id": "cust-1"})

    assert result.status == "completed"
    assert result.checkpoints >= 4
    assert result.approval_requests == 1
    assert result.side_effect_count == 1
    assert len(crm.writes) == 1


def test_agent_runner_blocks_rejected_prompt_injection(tmp_path: Path) -> None:
    crm = MockCRM.seeded()
    crm.prompt_injection = True
    runner = AgentRunner(
        MiniReActAgent(),
        default_tools(crm),
        db_path=tmp_path / "agent.sqlite",
        auto_reject_writes={"escalate"},
    )

    result = runner.run(
        {
            "ticket_id": "T-100",
            "customer_id": "cust-1",
            "force_prompt_injection": True,
        }
    )

    assert result.status == "completed"
    assert result.unauthorized_writes_blocked == 1
    assert result.side_effect_count == 0
    assert crm.writes == []

