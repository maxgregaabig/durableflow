# Contributing

Thanks for exploring **Durable Flow**. This is a small reference implementation — contributions that clarify behavior, fix bugs, or add focused exercises are welcome.

## Development setup

Requires **Python 3.11+** on macOS or Linux.

```bash
git clone <your-fork-url>
cd durableflow
./start.sh help
./start.sh test
```

Or manually:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest tests/ -v
python examples/crash_resume_demo.py
```

Examples and tests import from the `src/` package via `PYTHONPATH=.` (see `start.sh` and `pyproject.toml`).

## What to contribute

- Bug fixes with tests
- New exercises in [docs/exercises.md](docs/exercises.md)
- Documentation clarifications (especially [docs/dflow-arch.md](docs/dflow-arch.md))
- Additional workflow steps that demonstrate a primitive (keep scope minimal)

Please avoid large framework integrations or turning this into a general-purpose agent platform.

## Pull requests

1. Fork and branch from `main`
2. Run `./start.sh test` and ensure the crash demo still works
3. Keep changes focused; match existing style (stdlib-first, explicit tests)
4. Open a PR with a short description of the problem and verification steps

## Optional dependencies

Real Anthropic calls require:

```bash
pip install -e ".[providers]"
export ANTHROPIC_API_KEY=...
```

CI and core tests do not use API keys.

## Questions

Open a GitHub issue for bugs, exercise ideas, or architecture discussion.
