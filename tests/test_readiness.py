from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

from readiness.harness import AgentConfig, built_in_harness
from readiness.render import render_readiness_markdown
from readiness.scoring import ReadinessComparison, ScenarioResult, compare_readiness
from readiness.view import ReadinessState, build_readiness_view


def test_readiness_harness_scores_wrapped_above_naked() -> None:
    harness = built_in_harness()
    naked = harness.run_all(AgentConfig(wrapped=False))
    wrapped = harness.run_all(AgentConfig(wrapped=True))
    comparison = compare_readiness(naked, wrapped)

    assert len(naked) == 6
    assert len(wrapped) == 6
    assert comparison.naked is not None
    assert comparison.wrapped is not None
    assert comparison.wrapped.overall > comparison.naked.overall
    assert comparison.naked.categories["Safety"] == 0
    assert comparison.wrapped.categories["Safety"] == 100


def test_readiness_view_routes_all_states() -> None:
    passing = ScenarioResult("prompt_injection", "Safety", True, "m", 1, "ok", 1)
    failing = ScenarioResult("prompt_injection", "Safety", False, "m", 0, "bad", 1)

    empty = build_readiness_view(ReadinessComparison(None, None, {}, [], []))
    incomplete = build_readiness_view(compare_readiness([failing], []))
    ship = build_readiness_view(compare_readiness([failing], [passing]))
    block = build_readiness_view(compare_readiness([failing], [failing]))

    assert empty.state == ReadinessState.EMPTY
    assert incomplete.state == ReadinessState.INCOMPLETE
    assert ship.state == ReadinessState.VERDICT_SHIP
    assert block.state == ReadinessState.VERDICT_BLOCK
    assert len(ship.headline_metrics) <= 5


def test_readiness_renderer_imports_view_only() -> None:
    source = Path("readiness/render.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_modules = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported_from = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }

    assert "readiness.scoring" not in imported_modules | imported_from
    assert "readiness.harness" not in imported_modules | imported_from
    assert "view" in imported_from or "readiness.view" in imported_from


def test_readiness_demo_writes_json_and_markdown(tmp_path: Path) -> None:
    json_path = tmp_path / "readiness.json"
    markdown_path = tmp_path / "readiness_report.md"

    subprocess.run(
        [
            sys.executable,
            "examples/readiness_demo.py",
            "--json-output",
            str(json_path),
            "--markdown-output",
            str(markdown_path),
        ],
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    )

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    markdown = markdown_path.read_text(encoding="utf-8")
    assert payload["wrapped"]["overall"] > payload["naked"]["overall"]
    assert "**VERDICT:**" in markdown
    assert "blocked a rogue write" in markdown


def test_markdown_verdict_precedes_metric_table() -> None:
    harness = built_in_harness()
    comparison = compare_readiness(
        harness.run_all(AgentConfig(wrapped=False)),
        harness.run_all(AgentConfig(wrapped=True)),
    )
    markdown = render_readiness_markdown(build_readiness_view(comparison))

    assert markdown.index("**VERDICT:**") < markdown.index("| Category |")
