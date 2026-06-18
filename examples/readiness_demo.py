from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from readiness.harness import AgentConfig, built_in_harness
from readiness.render import render_readiness_cli, render_readiness_markdown
from readiness.scoring import compare_readiness
from readiness.view import build_readiness_view


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the DurableFlow agent readiness demo.")
    parser.add_argument("--json-output", default="readiness.json")
    parser.add_argument("--markdown-output", default="readiness_report.md")
    args = parser.parse_args()

    harness = built_in_harness()
    naked = harness.run_all(AgentConfig(wrapped=False))
    wrapped = harness.run_all(AgentConfig(wrapped=True))
    comparison = compare_readiness(naked, wrapped)
    view = build_readiness_view(comparison)
    render_readiness_cli(view)
    Path(args.json_output).write_text(comparison.to_json() + "\n", encoding="utf-8")
    Path(args.markdown_output).write_text(render_readiness_markdown(view), encoding="utf-8")


if __name__ == "__main__":
    main()

