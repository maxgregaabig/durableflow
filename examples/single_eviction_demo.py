from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from colony.chaos import ChaosSchedule
from colony.controller import ColonyController
from colony.models import make_eval_batch
from colony.provider import MockProvider


def main() -> None:
    batch = make_eval_batch(batch_size=1, batch_id="single-eviction")
    schedule = ChaosSchedule.from_offsets(7, [(6.0, 0)])
    report = ColonyController(
        MockProvider(seed=7),
        schedule,
        pool_size=1,
        db_path=Path(tempfile.mkdtemp(prefix="colony-single-")) / "single_eviction.sqlite",
    ).run_batch(batch, budget=1.0, run_id="single-eviction")
    print(
        "single simulated eviction:",
        f"completed={report.jobs_completed}/{report.batch_size}",
        f"recoveries={report.recoveries}",
        f"cost=${report.total_cost_usd:.4f}",
    )


if __name__ == "__main__":
    main()
