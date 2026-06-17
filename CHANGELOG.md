# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-06-17

### Added

- **Durable Flow** — minimal durable workflow runtime with SQLite checkpointing and crash recovery
- Inbox triage reference workflow (ingest, context selection, triage, draft, approval, send)
- Approval gate with durable pause/resume
- Multi-model routing with error and mock timeout fallback
- Per-step cost accounting and JSONL telemetry
- TF-IDF context selection under hard token budget
- Idempotent side-effect log for mock send
- Crash recovery and inbox triage demos, `start.sh` helper
- Test suite (unit + integration including subprocess crash)
- Architecture doc ([docs/dflow-arch.md](docs/dflow-arch.md)) and exercises ([docs/exercises.md](docs/exercises.md))
- MIT license

[0.1.0]: https://github.com/marcospolanco/durableflow/releases/tag/v0.1.0
