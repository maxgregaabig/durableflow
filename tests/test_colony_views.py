from __future__ import annotations

from pathlib import Path

from colony.render_terminal import render_comparison, render_scoreboard
from colony.view_fixtures import comparison_marginal, scoreboard_recovering


def test_scoreboard_fixture_renders_recovery_state():
    rendered = render_scoreboard(scoreboard_recovering)

    assert "recoveries 1" in rendered
    assert "job-07 RECOVERING" in rendered


def test_marginal_comparison_renders_honestly():
    rendered = render_comparison(comparison_marginal)

    assert "completion delta: +5 pts" in rendered
    assert "100%" in rendered
    assert "95%" in rendered


def test_render_terminal_imports_view_types_only():
    source = Path("colony/render_terminal.py").read_text(encoding="utf-8")

    assert "from .models" not in source
    assert "from .benchmark" not in source
