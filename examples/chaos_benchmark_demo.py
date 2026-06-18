from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from colony.benchmark import Benchmark
from colony.chaos import ChaosProfile
from colony.models import make_eval_batch
from colony.provider import MockProvider, VastProvider
from colony.render_terminal import render_comparison
from colony.views import build_comparison_view


def load_profile(name: str) -> ChaosProfile:
    profiles = json.loads((ROOT / "data" / "chaos_profiles.json").read_text(encoding="utf-8"))
    raw = profiles[name]
    return ChaosProfile(name=name, **raw)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Colony naive-vs-durable chaos benchmark.")
    parser.add_argument("--profile", default="hostile", choices=["calm", "moderate", "hostile"])
    parser.add_argument("--budget", type=float, default=10.0)
    parser.add_argument("--live", action="store_true", help="Use VastProvider; requires VAST_API_KEY.")
    parser.add_argument("--output", default="benchmark_result.json")
    args = parser.parse_args()

    profile = load_profile(args.profile)
    provider_factory = (
        (lambda: VastProvider(seed=profile.seed)) if args.live else (lambda: MockProvider(seed=profile.seed))
    )
    result = Benchmark(provider_factory, profile=profile, db_dir=Path(tempfile.mkdtemp(prefix="colony-demo-"))).run(
        make_eval_batch(),
        args.budget,
    )
    print(render_comparison(build_comparison_view(result)))
    Path(args.output).write_text(result.to_json() + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
