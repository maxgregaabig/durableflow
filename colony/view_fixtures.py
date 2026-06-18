from __future__ import annotations

from .views import ComparisonView, ResultRow, ScoreboardView


scoreboard_calm = ScoreboardView("colony", 20, 2, 0, 0, 5, 0, 0.15, 10.0, 0, 0)
scoreboard_recovering = ScoreboardView(
    "colony", 20, 7, 1, 0, 4, 1, 0.91, 10.0, 1, 0, ["job-07 RECOVERING -> resumed"]
)
scoreboard_budget_halt = ScoreboardView("colony", 20, 9, 0, 0, 3, 2, 2.0, 2.0, 2, 0)
scoreboard_done = ScoreboardView("colony", 20, 20, 0, 0, 5, 3, 3.81, 10.0, 3, 0)

comparison_strong_delta = ComparisonView(
    ResultRow("naive", 45.0, 3.40, 612.0, "--", "--"),
    ResultRow("dflow-vast", 100.0, 3.81, 668.0, 7, 0),
    55.0,
    0.41,
    56.0,
    "hostile",
    1337,
    "mock",
)
comparison_marginal = ComparisonView(
    ResultRow("naive", 95.0, 3.40, 612.0, "--", "--"),
    ResultRow("dflow-vast", 100.0, 3.55, 630.0, 1, 0),
    5.0,
    0.15,
    18.0,
    "calm",
    42,
    "mock",
)
comparison_live_mode = ComparisonView(
    ResultRow("naive", 0.0, 0.02, 30.0, "--", "--"),
    ResultRow("dflow-vast", 100.0, 0.04, 68.0, 1, 0),
    100.0,
    0.02,
    38.0,
    "smoke",
    7,
    "live",
)
